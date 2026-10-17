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
        self.assertContains(self.client.get(self.url("live_class")), "Open teaching board")
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
