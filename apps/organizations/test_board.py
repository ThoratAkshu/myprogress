"""The teaching board: the video studio inside a live class, shared into the call and recorded as the class recording."""
import os
import shutil
import struct
import tempfile
from datetime import timedelta
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Profile
from apps.core.models import LearningPost
from apps.notifications.models import Notification
from . import recordings, services
from .models import ClassRecording, LiveClass

MEDIA = tempfile.mkdtemp()
UNKNOWN_SIZE = b"\x01\xff\xff\xff\xff\xff\xff\xff"


def make_user(email, role="developer", first_name="Asha", last_name="Rao"):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, role=role, handle=email.split("@")[0].replace(".", "-"))
    return user


def element(element_id, payload):
    return element_id + bytes([0x80 | len(payload)]) + payload


def browser_webm(cluster_bytes=600):
    """The start of a WebM laid out the way browsers record it: no Duration, and a Segment of unknown size."""
    header = element(b"\x1a\x45\xdf\xa3", element(b"\x42\x86", b"\x01") + element(b"\x42\x82", b"webm"))
    info = element(b"\x15\x49\xa9\x66", element(b"\x2a\xd7\xb1", (1_000_000).to_bytes(3, "big")) + element(b"\x4d\x80", b"Chrome"))
    tracks = element(b"\x16\x54\xae\x6b", b"\x00" * 40)
    cluster = b"\x1f\x43\xb6\x75" + UNKNOWN_SIZE + b"\xab" * cluster_bytes
    return header + b"\x18\x53\x80\x67" + UNKNOWN_SIZE + info + tracks + cluster


def read_duration(data):
    """The Duration in milliseconds from the Segment Info, or None."""
    _, _, start, size, _ = recordings._element(data, 0)
    _, _, at, _, _ = recordings._element(data, start + size)
    element_id, _, start, size, _ = recordings._element(data, at)
    assert element_id == recordings.INFO
    child = start
    while child < start + size:
        child_id, _, child_start, child_size, _ = recordings._element(data, child)
        if child_id == recordings.DURATION:
            return struct.unpack(">d", data[child_start:child_start + child_size])[0]
        child = child_start + child_size
    return None


class DurationTests(SimpleTestCase):
    def test_the_length_is_written_into_a_browser_recording(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "class.webm")
        original = browser_webm(cluster_bytes=70_000)  # longer than the part that's read and rewritten
        with open(path, "wb") as handle:
            handle.write(original)
        self.assertTrue(recordings.add_duration(path, 3_725_500))
        with open(path, "rb") as handle:
            patched = handle.read()
        self.assertEqual(read_duration(patched), 3_725_500)
        self.assertEqual(len(patched), len(original) + 11 + 7)  # the Duration element, and a wider Info size
        self.assertTrue(patched.endswith(original[-60_000:]))  # the video data after the header is untouched
        self.assertTrue(recordings.add_duration(path, 1000))  # a second pass updates it in place
        with open(path, "rb") as handle:
            self.assertEqual(read_duration(handle.read()), 1000)
        with open(path, "wb") as handle:
            handle.write(b"not a video at all, just text" * 10)
        self.assertFalse(recordings.add_duration(path, 1000))


@override_settings(MEDIA_ROOT=MEDIA, ORGANIZATION_JOBS_EVERY_SECONDS=0)
class TeachingBoardTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.owner = make_user("office@institute.example", role="organization", first_name="Sunrise", last_name="Office")
        self.organization = services.create_organization(self.owner, {"name": "Sunrise Coding Institute", "kind": "institute", "city": "Pune", "about": "", "website": "", "join_requires_approval": False})
        self.student = make_user("asha@example.com")
        services.join(self.organization, self.student)
        self.live = LiveClass.objects.create(organization=self.organization, created_by=self.owner, title="SQL joins", starts_at=timezone.now() - timedelta(minutes=5), duration_minutes=60, agenda="INTRO\nWhat a join is")
        self.url = lambda name: reverse(f"organizations:{name}", args=[self.organization.slug, self.live.pk])

    def test_only_teachers_open_the_board_and_it_carries_the_studio(self):
        self.client.force_login(self.owner)
        page = self.client.get(self.url("teaching_board"))
        for text in ['data-host="live"', f'data-chunk-url="{self.url("recording_piece")}"', 'data-record-mode="board"', 'data-ink-tool="pen"', 'data-pane="notes"', "Share board", "What a join is", "csrfmiddlewaretoken"]:
            self.assertContains(page, text)
        self.assertEqual(page["Cache-Control"], "private, no-store")
        self.assertRedirects(self.client.get(self.url("join_class")), self.url("teaching_board"))  # starting the class opens the board
        LiveClass.objects.filter(pk=self.live.pk).update(meeting_link="https://meet.google.com/abc-defg-hij")
        self.assertContains(self.client.get(self.url("live_class")), "Open teaching board")  # a class in another app: share the board into it
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url("teaching_board")).status_code, 404)
        self.assertNotContains(self.client.get(self.url("live_class")), "Open teaching board")
        self.assertEqual(self.client.post(self.url("recording_start")).status_code, 404)

    def test_a_recording_uploads_in_pieces_and_becomes_the_class_recording(self):
        self.client.force_login(self.owner)
        token = self.client.post(self.url("recording_start"), {"type": "video/webm"}).json()["recording"]
        data = browser_webm(cluster_bytes=3000)
        pieces = [data[:1000], data[1000:2200], data[2200:]]
        send = lambda seq, piece: self.client.post(self.url("recording_piece"), {"recording": token, "seq": str(seq), "piece": SimpleUploadedFile(f"piece-{seq}.webm", piece, content_type="video/webm")})
        self.assertEqual(send(0, pieces[0]).json(), {"received": 1})
        self.assertEqual(send(0, pieces[0]).json(), {"received": 1})  # a retry is acknowledged, not appended twice
        self.assertEqual(send(2, pieces[2]).status_code, 409)
        self.assertEqual(send(1, pieces[1]).json(), {"received": 2})
        self.assertEqual(send(2, pieces[2]).json(), {"received": 3})
        recording = ClassRecording.objects.get(token=token)
        self.assertEqual(recording.size, len(data))
        thumbnail = SimpleUploadedFile("thumbnail.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64, content_type="image/jpeg")
        response = self.client.post(self.url("recording_finish"), {"recording": token, "duration_ms": "1800000", "chapters": "0:00 Intro\n12:30 Left joins", "captions": "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello class", "thumbnail": thumbnail})
        post = LearningPost.objects.get(title="SQL joins (class recording)")
        self.assertEqual(response.json()["post_url"], reverse("learning:detail", args=[post.pk]))
        self.assertEqual((post.organization, post.is_public, post.kind, post.chapters), (self.organization, False, "video", "0:00 Intro\n12:30 Left joins"))
        self.assertTrue(post.video_file.name.startswith("private/class-recordings/"))
        self.assertTrue(post.thumbnail.name.startswith("private/"))
        with open(post.video_file.path, "rb") as handle:
            self.assertEqual(read_duration(handle.read()), 1_800_000)
        self.live.refresh_from_db()
        self.assertEqual(self.live.recording, post)
        self.assertTrue(Notification.objects.filter(recipient=self.student, text="Recording of SQL joins is ready").exists())
        self.assertEqual(send(3, b"more").status_code, 404)  # finished recordings take no more pieces
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("learning:media", args=[post.pk, "video"])).status_code, 200)  # members can watch it
        outsider = make_user("outsider@example.com")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse("learning:media", args=[post.pk, "video"])).status_code, 404)

    def test_recordings_stay_with_their_teacher_and_their_size_limit(self):
        self.client.force_login(self.owner)
        token = self.client.post(self.url("recording_start")).json()["recording"]
        teacher = make_user("teacher@example.com", first_name="Meera", last_name="Joshi")
        services.join(self.organization, teacher).__class__.objects.filter(user=teacher).update(role="teacher")
        self.client.force_login(teacher)
        piece = lambda seq, data: {"recording": token, "seq": str(seq), "piece": SimpleUploadedFile("piece.webm", data, content_type="video/webm")}
        self.assertEqual(self.client.post(self.url("recording_piece"), piece(0, b"\x1aE\xdf\xa3")).status_code, 404)  # someone else's recording
        self.client.force_login(self.owner)
        with override_settings(CLASS_RECORDING_MAX_BYTES=10):
            self.assertEqual(self.client.post(self.url("recording_piece"), piece(0, b"\x1aE\xdf\xa3" * 4)).status_code, 413)
        self.assertEqual(self.client.post(self.url("recording_finish"), {"recording": token, "duration_ms": "1000"}).status_code, 400)  # nothing playable yet
        self.assertFalse(LearningPost.objects.exists())


def stream_webm():
    """A broadcast the way browsers record it: a header with a video and an audio track, then clusters of unknown
    size. Clusters 1 and 3 start with a video keyframe; cluster 2 doesn't."""
    header = element(b"\x1a\x45\xdf\xa3", element(b"\x42\x82", b"webm"))
    info = element(b"\x15\x49\xa9\x66", element(b"\x2a\xd7\xb1", (1_000_000).to_bytes(3, "big")))
    tracks = element(b"\x16\x54\xae\x6b", element(b"\xae", element(b"\xd7", b"\x01") + element(b"\x83", b"\x01")) + element(b"\xae", element(b"\xd7", b"\x02") + element(b"\x83", b"\x02")))
    video = lambda keyframe: element(b"\xa0", element(b"\xa1", b"\x81\x00\x00\x00" + b"V" * 30) + (b"" if keyframe else element(b"\xfb", b"\xfe")))
    audio = element(b"\xa3", b"\x82\x00\x00\x80" + b"A" * 12)
    cluster = lambda ms, keyframe: b"\x1f\x43\xb6\x75" + UNKNOWN_SIZE + element(b"\xe7", ms.to_bytes(2, "big")) + video(keyframe) + audio + video(False)
    head = header + b"\x18\x53\x80\x67" + UNKNOWN_SIZE + info + tracks
    clusters = [cluster(0, True), cluster(1000, False), cluster(2000, True)]
    return head, clusters


class StreamIndexTests(SimpleTestCase):
    def test_keyframes_are_found_as_pieces_arrive(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        head, clusters = stream_webm()
        data = head + b"".join(clusters)
        recording = ClassRecording(token="t", stream_state={})
        with self.settings(MEDIA_ROOT=folder):
            os.makedirs(os.path.dirname(recordings.file_path(recording)))
            with open(recordings.file_path(recording), "wb") as handle:
                handle.write(data[:len(head) - 5])  # the header isn't complete yet
            recording.stream_state = recordings.index_stream(recording)
            self.assertEqual(recording.stream_state["scanned"], 0)
            self.assertIsNone(recording.stream_state.get("init"))
            for end in [len(head) + 20, len(head) + len(clusters[0]) + 7, len(data)]:  # pieces cut mid-element
                with open(recordings.file_path(recording), "wb") as handle:
                    handle.write(data[:end])
                recording.stream_state = recordings.index_stream(recording)
            state = recording.stream_state
            first, third = len(head), len(head) + len(clusters[0]) + len(clusters[1])
            self.assertEqual((state["init"], state["video"], state["last_ms"]), (len(head), 1, 2000))
            self.assertEqual(state["recent"], [[first, 0], [third, 2000]])
            self.assertEqual(recordings.join_point(state, behind_ms=1500), first)
            self.assertEqual(recordings.join_point(state, behind_ms=0), third)
            with open(recordings.keyframes_path(recording)) as handle:
                self.assertEqual(handle.read().split(), [str(first), "0", str(third), "2000"])


@override_settings(MEDIA_ROOT=MEDIA, ORGANIZATION_JOBS_EVERY_SECONDS=0)
class LiveInMyProgressTests(TestCase):
    """Classes without a meeting link happen inside MyProgress: broadcast from the board, watched and chatted about."""
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.owner = make_user("office@institute.example", role="organization", first_name="Sunrise", last_name="Office")
        self.organization = services.create_organization(self.owner, {"name": "Sunrise Coding Institute", "kind": "institute", "city": "Pune", "about": "", "website": "", "join_requires_approval": False})
        self.student = make_user("asha@example.com")
        services.join(self.organization, self.student)
        self.live = LiveClass.objects.create(organization=self.organization, created_by=self.owner, title="SQL joins", starts_at=timezone.now() - timedelta(minutes=5), duration_minutes=60)
        self.url = lambda name: reverse(f"organizations:{name}", args=[self.organization.slug, self.live.pk])

    def go_live(self):
        self.client.force_login(self.owner)
        token = self.client.post(self.url("recording_start"), {"type": "video/webm;codecs=vp9,opus", "live": "1"}).json()["recording"]
        head, clusters = stream_webm()
        for seq, piece in enumerate([head + clusters[0], clusters[1] + clusters[2]]):
            self.client.post(self.url("recording_piece"), {"recording": token, "seq": str(seq), "piece": SimpleUploadedFile("piece.webm", piece, content_type="video/webm")})
        return token, len(head), len(head) + len(clusters[0]) + len(clusters[1]) + len(clusters[2])

    def test_a_class_without_a_link_happens_inside_myprogress(self):
        self.assertEqual(self.live.meeting_link, "")
        self.client.force_login(self.student)
        self.assertRedirects(self.client.get(self.url("join_class")), self.url("watch"))
        page = self.client.get(self.url("watch"))
        self.assertContains(page, f'data-stream-url="{self.url("class_stream")}"')
        self.assertContains(page, "Raise hand")
        self.assertEqual(self.client.get(self.url("class_stream")).json()["state"], "waiting")
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(self.url("watch")), self.url("teaching_board"))
        board = self.client.get(self.url("teaching_board"))
        self.assertContains(board, 'data-broadcast="1"')
        self.assertContains(board, "Go live")
        self.assertContains(board, 'data-panel-tab="class"')

    def test_students_follow_the_broadcast_from_a_recent_keyframe(self):
        token, init, size = self.go_live()
        recording = ClassRecording.objects.get(token=token)
        self.assertTrue(recording.is_live)
        self.client.force_login(self.student)
        manifest = self.client.get(self.url("class_stream")).json()
        self.assertEqual((manifest["state"], manifest["recording"], manifest["init"], manifest["size"]), ("live", token, init, size))
        self.assertEqual(manifest["mime"], 'video/webm; codecs="vp9,opus"')
        self.assertIn(manifest["start"], [offset for offset, _ in recording.stream_state["recent"]])
        header = self.client.get(self.url("class_stream_bytes"), {"recording": token, "from": "0", "to": str(init)})
        with open(recordings.file_path(recording), "rb") as handle:
            self.assertEqual(header.content, handle.read(init))
        self.assertEqual(header["X-Stream-State"], "live")
        self.assertEqual(self.client.get(self.url("class_stream_bytes"), {"recording": token, "from": str(size)}).status_code, 204)
        ClassRecording.objects.filter(pk=recording.pk).update(last_piece_at=timezone.now() - timedelta(seconds=30))
        self.assertEqual(self.client.get(self.url("class_stream")).json()["state"], "paused")
        self.client.force_login(self.owner)
        self.client.post(self.url("recording_finish"), {"recording": token, "duration_ms": "3000"})
        self.client.force_login(self.student)
        ended = self.client.get(self.url("class_stream")).json()
        self.assertEqual(ended["state"], "ended")
        self.assertTrue(ended["recording_url"])
        outsider = make_user("outsider@example.com")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.url("class_stream")).status_code, 404)
        self.assertEqual(self.client.get(self.url("class_stream_bytes"), {"recording": token, "from": "0"}).status_code, 404)

    def test_the_class_chat_with_hands_and_who_is_watching(self):
        from .models import Attendance
        self.client.force_login(self.student)
        self.client.get(self.url("join_class"))
        self.client.post(self.url("class_chat"), {"action": "say", "text": "  Is a LEFT JOIN   slower? "})
        self.client.post(self.url("class_chat"), {"action": "raise"})
        mine = self.client.get(self.url("class_chat")).json()
        self.assertEqual([(m["text"], m["mine"], m["teacher"]) for m in mine["messages"]], [("Is a LEFT JOIN slower?", True, False)])
        self.assertTrue(mine["hand"])
        self.assertNotIn("watching", mine)  # only teachers see who's here
        self.client.force_login(self.owner)
        board = self.client.get(self.url("class_chat")).json()
        self.assertEqual((board["watching"], [hand["name"] for hand in board["hands"]]), (1, ["Asha Rao"]))
        self.assertEqual(board["messages"][0]["name"], "Asha Rao")
        self.client.post(self.url("class_chat"), {"action": "say", "text": "Good question!"})
        self.client.post(self.url("class_chat"), {"action": "lower", "student": str(self.student.pk)})
        self.assertIsNone(Attendance.objects.get(student=self.student).hand_raised_at)
        after = board["messages"][0]["id"]
        newer = self.client.get(self.url("class_chat"), {"after": str(after)}).json()["messages"]
        self.assertEqual([(m["text"], m["teacher"]) for m in newer], [("Good question!", True)])
        self.client.post(self.url("class_chat"), {"action": "delete", "message": str(after)})
        self.client.force_login(self.student)
        self.assertEqual([m["text"] for m in self.client.get(self.url("class_chat")).json()["messages"]], ["Good question!"])
        self.assertEqual(self.client.post(self.url("class_chat"), {"action": "delete", "message": str(newer[0]["id"])}).status_code, 400)  # students can't remove messages
        outsider = make_user("outsider@example.com")
        self.client.force_login(outsider)
        self.assertEqual(self.client.post(self.url("class_chat"), {"action": "say", "text": "hi"}).status_code, 404)

    def test_classes_with_an_automatic_jitsi_room_move_inside_myprogress(self):
        import importlib
        from django.apps import apps
        migration = importlib.import_module("apps.organizations.migrations.0012_live_in_myprogress")
        auto = LiveClass.objects.create(organization=self.organization, title="Old", starts_at=timezone.now(), meeting_link="https://meet.jit.si/MyProgress-sunrise-abc123")
        zoom = LiveClass.objects.create(organization=self.organization, title="Zoom", starts_at=timezone.now(), meeting_link="https://zoom.us/j/123")
        migration.classes_into_myprogress(apps, None)
        auto.refresh_from_db()
        zoom.refresh_from_db()
        self.assertEqual((auto.meeting_link, zoom.meeting_link), ("", "https://zoom.us/j/123"))
