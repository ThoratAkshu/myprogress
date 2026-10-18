"""The class channel: an institute's lectures, notes and posts for its members, laid out like a video channel."""
import io
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
from PIL import Image
from apps.accounts.models import Profile
from apps.common.templatetags.ui import clock
from apps.core.models import LearningPost
from apps.learning.media import note_duration, video_seconds
from . import recordings, services
from .models import ChannelPost
from .test_board import class_webm

MEDIA = tempfile.mkdtemp()


def make_user(email, role="developer", first_name="Asha", last_name="Rao"):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, role=role, handle=email.split("@")[0].replace(".", "-"))
    return user


def mp4(seconds, scale=1000, movie_last=True):
    """An MP4 with its movie header (mvhd) after the media, the way many cameras and phones write it."""
    box = lambda kind, payload: struct.pack(">I4s", 8 + len(payload), kind) + payload  # noqa: E731
    movie = box(b"moov", box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, scale, seconds * scale) + b"\x00" * 80))
    media = box(b"mdat", b"\x00" * 5000)
    return box(b"ftyp", b"isom\x00\x00\x02\x00") + (media + movie if movie_last else movie + media)


class VideoLengthTests(SimpleTestCase):
    def test_the_length_is_read_from_webm_and_mp4_files(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = lambda name: os.path.join(folder, name)  # noqa: E731
        with open(path("raw.webm"), "wb") as handle:
            handle.write(class_webm())
        self.assertEqual(video_seconds(path("raw.webm")), 0)  # a browser's own recording doesn't say
        recordings.write_copy(path("raw.webm"), path("class.webm"), None, 125_400)
        self.assertEqual(video_seconds(path("class.webm")), 125)
        for name, data in [("late.mp4", mp4(3725)), ("early.mp4", mp4(61, scale=600, movie_last=False))]:
            with open(path(name), "wb") as handle:
                handle.write(data)
        self.assertEqual((video_seconds(path("late.mp4")), video_seconds(path("early.mp4"))), (3725, 61))
        with open(path("text.webm"), "wb") as handle:
            handle.write(b"not a video")
        self.assertEqual(video_seconds(path("text.webm")), 0)
        self.assertEqual([clock(5), clock(125), clock(3725)], ["0:05", "2:05", "1:02:05"])


@override_settings(MEDIA_ROOT=MEDIA, ORGANIZATION_JOBS_EVERY_SECONDS=0)
class ClassChannelTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.owner = make_user("office@institute.example", role="organization", first_name="Sunrise", last_name="Office")
        self.organization = services.create_organization(self.owner, {"name": "Sunrise Coding Institute", "kind": "institute", "city": "Pune", "about": "Linux and Python, from zero.", "website": "", "join_requires_approval": False})
        buffer = io.BytesIO()
        Image.new("RGB", (1200, 300), "#065f46").save(buffer, "PNG")
        profile = Profile.objects.get(user=self.owner)
        profile.brand_color = "emerald"
        profile.banner.save("banner.png", SimpleUploadedFile("banner.png", buffer.getvalue(), content_type="image/png"))
        self.student = make_user("asha@example.com")
        services.join(self.organization, self.student)
        lecture = lambda title, **fields: LearningPost.objects.create(author=self.owner, organization=self.organization, is_public=False, title=title, **{"kind": "video", **fields})  # noqa: E731
        now = timezone.now()
        self.basics = lecture("Linux basics", duration=122, views=5)
        self.shell = lecture("Shell scripting", duration=3725, views=40)
        LearningPost.objects.filter(pk=self.shell.pk).update(published_at=now - timedelta(days=3))
        self.notes = lecture("Linux cheat sheet", kind="article", body="cd ls pwd " * 120)
        lecture("Next week: permissions", duration=600, publish_at=now + timedelta(days=2))
        ChannelPost.objects.create(organization=self.organization, author=self.owner, kind="announcement", title="Holiday on Monday", body="No class")
        self.url = reverse("organizations:channel", args=[self.organization.slug])

    def test_students_see_their_class_like_a_video_channel(self):
        self.client.force_login(self.student)
        home = self.client.get(self.url)
        for text in ["<h1>Sunrise Coding Institute</h1>", "Linux and Python, from zero.", "--brand-from:#065f46", "channels/banners/", "Linux basics", "2:02", "1:02:05", "Linux cheat sheet", "2 min read", "Holiday on Monday"]:
            self.assertContains(home, text)
        self.assertNotContains(home, "Next week: permissions")  # not released yet
        self.assertNotContains(home, "Watched")
        self.client.get(reverse("learning:detail", args=[self.basics.pk]))
        self.assertContains(self.client.get(self.url), "Watched", count=1)
        popular = self.client.get(self.url, {"tab": "videos", "sort": "popular"}).content.decode()
        self.assertLess(popular.index("Shell scripting"), popular.index("Linux basics"))
        latest = self.client.get(self.url, {"tab": "videos"}).content.decode()
        self.assertLess(latest.index("Linux basics"), latest.index("Shell scripting"))
        self.assertNotIn("Linux cheat sheet", latest)
        notes = self.client.get(self.url, {"tab": "notes"})
        self.assertContains(notes, "Linux cheat sheet")
        self.assertNotContains(notes, "Shell scripting")
        posts = self.client.get(self.url, {"tab": "posts"})
        self.assertContains(posts, "Holiday on Monday")
        self.assertNotContains(posts, "Linux basics")
        self.assertContains(self.client.get(self.url, {"kind": "video"}), 'href="?tab=videos" aria-current="page"')  # older links open the matching tab
        about = self.client.get(self.url, {"tab": "about"})
        for text in ["2 members", "Leave Sunrise Coding Institute", reverse("landing:public_profile", args=["office"])]:
            self.assertContains(about, text)
        self.assertNotContains(home, "Your logo, banner and colors")  # only the institute customizes its channel

    def test_teachers_see_who_opened_what_and_what_is_still_scheduled(self):
        self.client.force_login(self.student)
        self.client.get(reverse("learning:detail", args=[self.shell.pk]))
        self.client.force_login(self.owner)
        videos = self.client.get(self.url, {"tab": "videos"})
        for text in ["Opened by 1 of 2", "Opened by 0 of 2", "Next week: permissions", "Release now", "Record a lecture", "Your logo, banner and colors"]:
            self.assertContains(videos, text)
        self.assertNotContains(videos, "Watched")
        self.assertContains(self.client.get(self.url), "Next week: permissions")  # scheduled items wait on the home tab too

    def test_a_lecture_keeps_its_length_when_its_video_changes(self):
        with open(os.path.join(MEDIA, "talk.mp4"), "wb") as handle:
            handle.write(mp4(95))
        self.basics.video_file.name = "talk.mp4"
        note_duration(self.basics)
        self.basics.refresh_from_db()
        self.assertEqual(self.basics.duration, 95)
