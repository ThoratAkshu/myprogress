import base64
import os
import re
import shutil
import subprocess
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.parse import quote
from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail, signing
from django.core.cache import cache
from django.core.management import call_command
from django.test import LiveServerTestCase, TestCase, override_settings
from django.urls import reverse
from apps.accounts.emails import VERIFICATION_SALT, verification_token
from apps.accounts.models import Profile
from apps.core.git_service import initialize_repository, list_branches
from apps.core.models import ActivityEvent, GitAccessToken, LearningPost, Project, Repository
def make_user(email, first_name="Asha", last_name="Rao", role="developer"):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, role=role)
    return user
class GitStreamingTests(LiveServerTestCase):
    def setUp(self):
        cache.clear()
        self.storage = tempfile.TemporaryDirectory()
        self.override = override_settings(GIT_REPOSITORY_ROOT=self.storage.name)
        self.override.enable()
        self.user = make_user("pusher@example.com", "Push", "Er")
        self.repository = Repository.objects.create(project=Project.objects.create(owner=self.user, title="Big"), owner=self.user, slug="big")
        initialize_repository(self.repository)
        _, token = GitAccessToken.issue(self.user, "push")
        self.remote = self.live_server_url.replace("://", f"://{quote(self.user.username, safe='')}:{quote(token, safe='')}@", 1) + reverse("landing:git_root", args=[self.user.pk, self.repository.slug])
    def tearDown(self):
        self.override.disable()
        self.storage.cleanup()
    def push_random_file(self, size):
        if not shutil.which(settings.GIT_EXECUTABLE):
            self.skipTest("Git executable is unavailable")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "Push Er", "GIT_AUTHOR_EMAIL": "pusher@example.com", "GIT_COMMITTER_NAME": "Push Er", "GIT_COMMITTER_EMAIL": "pusher@example.com"}
        with tempfile.TemporaryDirectory() as root:
            run = lambda *args: subprocess.run([settings.GIT_EXECUTABLE, "-c", "credential.helper=", *args], cwd=root, env=env, capture_output=True, text=True)
            run("init", "-b", "main")
            Path(root, "data.bin").write_bytes(os.urandom(size))
            Path(root, "main.py").write_bytes(b"print('big')\n")
            run("add", ".")
            run("commit", "-m", "Big commit")
            return run("push", self.remote, "main")
    def test_pushes_larger_than_gits_post_buffer_stream_through(self):
        result = self.push_random_file(3 * 1024 * 1024)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list_branches(self.repository)[0]["subject"], "Big commit")
        self.assertEqual(ActivityEvent.objects.get(user=self.user, action="pushed_commits").metadata["commits"], 1)
        self.repository.refresh_from_db()
        self.assertEqual(self.repository.languages, {"Python": 13})
    def test_pushes_over_the_configured_limit_are_rejected(self):
        with override_settings(GIT_MAX_REQUEST_BYTES=512 * 1024):
            result = self.push_random_file(2 * 1024 * 1024)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("413", result.stderr)
        self.assertEqual(list_branches(self.repository), [])
class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
    def test_failed_logins_lock_the_account_for_a_while(self):
        make_user("victim@example.com")
        make_user("other@example.com")
        for _ in range(10):
            self.client.post(reverse("landing:login"), {"email": "victim@example.com", "password": "wrong-password"})
        response = self.client.post(reverse("landing:login"), {"email": "victim@example.com", "password": "StrongPass!482"}, follow=True)
        self.assertContains(response, "Too many failed sign-in attempts")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.post(reverse("landing:login"), {"email": "other@example.com", "password": "StrongPass!482"}), reverse("landing:dashboard"))
    def test_bad_git_credentials_are_throttled_per_address(self):
        owner = make_user("owner@example.com")
        storage = tempfile.mkdtemp()
        with override_settings(GIT_REPOSITORY_ROOT=storage):
            repository = Repository.objects.create(project=Project.objects.create(owner=owner, title="Locked"), owner=owner, slug="locked")
            initialize_repository(repository)
            url = reverse("landing:git_http", args=[owner.pk, "locked", "info/refs"]) + "?service=git-upload-pack"
            bad = "Basic " + base64.b64encode(b"owner@example.com:mp_bad_guess").decode()
            statuses = [self.client.get(url, HTTP_AUTHORIZATION=bad).status_code for _ in range(31)]
        shutil.rmtree(storage, ignore_errors=True)
        self.assertEqual(statuses[:30], [401] * 30)
        self.assertEqual(statuses[30], 429)
    def test_comment_spam_gets_429(self):
        author = make_user("author@example.com")
        post = LearningPost.objects.create(author=author, title="Post", body="x")
        self.client.force_login(make_user("spammer@example.com", "Spam", "Mer"))
        statuses = [self.client.post(reverse("learning:comment", args=[post.pk]), {"body": f"spam {index}"}).status_code for index in range(21)]
        self.assertEqual(statuses[:20], [302] * 20)
        self.assertEqual(statuses[20], 429)
class EmailVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
    def test_registration_sends_a_link_that_verifies_the_email(self):
        self.client.post(reverse("landing:register"), {"first_name": "Hana", "last_name": "Iyer", "email": "hana@acme.io", "password": "StrongPass!482", "role": "recruiter", "company_name": "Acme", "terms": "1"})
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://\S+/account/verify/\S+/", mail.outbox[0].body).group(0)
        self.assertContains(self.client.get(reverse("recruiting:search")), "Confirm your email")
        response = self.client.get(link, follow=True)
        self.assertContains(response, "You&#x27;re now a verified recruiter.")
        profile = Profile.objects.get(user__email="hana@acme.io")
        self.assertIsNotNone(profile.email_verified_at)
        self.assertTrue(profile.is_verified_recruiter)
        self.assertNotContains(self.client.get(reverse("recruiting:search")), "Confirm your email")
    def test_tampered_expired_or_stale_tokens_are_rejected(self):
        user = make_user("dev@example.com")
        token = verification_token(user)
        self.client.get(reverse("landing:verify_email", args=[token[:-2] + "xx"]))
        expired = signing.dumps({"user": user.pk, "email": user.email}, salt=VERIFICATION_SALT)
        with mock.patch("apps.accounts.emails.VERIFICATION_MAX_AGE", -1):
            self.client.get(reverse("landing:verify_email", args=[expired]))
        User.objects.filter(pk=user.pk).update(email="changed@example.com")
        self.client.get(reverse("landing:verify_email", args=[token]))
        self.assertIsNone(Profile.objects.get(user=user).email_verified_at)
    def test_resending_is_limited(self):
        self.client.force_login(make_user("dev@example.com"))
        statuses = [self.client.post(reverse("landing:resend_verification")).status_code for _ in range(4)]
        self.assertEqual(statuses, [302, 302, 302, 429])
        self.assertEqual(len(mail.outbox), 3)
    def test_reminder_banner_can_be_closed_until_the_next_sign_in(self):
        user = make_user("dev@example.com")
        self.client.force_login(user)
        dashboard = reverse("landing:dashboard")
        self.assertContains(self.client.get(dashboard), "Close this reminder")
        response = self.client.post(reverse("landing:dismiss_verify_banner"), headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(response.status_code, 204)
        self.assertNotContains(self.client.get(dashboard), "Confirm your email")
        self.client.logout()
        self.client.force_login(user)
        self.assertContains(self.client.get(dashboard), "Confirm your email")
class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
    def test_reset_flow_changes_the_password(self):
        make_user("forgetful@example.com")
        self.assertContains(self.client.get(reverse("landing:home")), reverse("landing:password_reset"))
        self.assertRedirects(self.client.post(reverse("landing:password_reset"), {"email": "FORGETFUL@example.com"}), reverse("landing:password_reset_done"))
        link = re.search(r"https?://\S+/account/reset/\S+/", mail.outbox[0].body).group(0)
        form_page = self.client.get(link, follow=True)
        self.assertContains(form_page, "Choose a new password")
        self.client.post(form_page.redirect_chain[-1][0], {"new_password1": "EvenStronger!93", "new_password2": "EvenStronger!93"})
        self.assertRedirects(self.client.post(reverse("landing:login"), {"email": "forgetful@example.com", "password": "EvenStronger!93"}), reverse("landing:dashboard"))
        self.client.logout()
        self.assertContains(self.client.get(link, follow=True), "This reset link no longer works")
    def test_unknown_emails_get_the_same_response_and_no_email(self):
        self.assertRedirects(self.client.post(reverse("landing:password_reset"), {"email": "nobody@example.com"}), reverse("landing:password_reset_done"))
        self.assertEqual(mail.outbox, [])
class OperationsTests(TestCase):
    def test_health_endpoint_reports_dependencies(self):
        response = self.client.get(reverse("landing:health"))
        self.assertEqual((response.status_code, response.json()), (200, {"status": "ok", "database": "ok", "git": "ok"}))
        with override_settings(GIT_EXECUTABLE="definitely-not-git"):
            response = self.client.get(reverse("landing:health"))
        self.assertEqual((response.status_code, response.json()["git"]), (503, "error"))
    def test_refresh_languages_backfills_old_repositories(self):
        from apps.code.tests import commit_files
        owner = make_user("owner@example.com")
        storage = tempfile.mkdtemp()
        with override_settings(GIT_REPOSITORY_ROOT=storage):
            repository = Repository.objects.create(project=Project.objects.create(owner=owner, title="Old"), owner=owner, slug="old")
            Repository.objects.create(project=Project.objects.create(owner=owner, title="Ghost"), owner=owner, slug="ghost")
            initialize_repository(repository)
            commit_files(repository, {"app.go": "package main\n"}, "Old push")
            output = StringIO()
            call_command("refresh_languages", stdout=output)
        shutil.rmtree(storage, ignore_errors=True)
        repository.refresh_from_db()
        self.assertEqual(repository.languages, {"Go": 13})
        self.assertIn("Updated 1 repositories (1 without storage, 0 failed)", output.getvalue())
    def test_cross_origin_requests_are_not_granted_credentials(self):
        response = self.client.get(reverse("landing:home"), HTTP_ORIGIN="https://evil.example")
        self.assertNotIn("Access-Control-Allow-Origin", response)
        self.assertNotIn("Access-Control-Allow-Credentials", response)
    def test_static_files_use_hashed_compressed_storage(self):
        from config.settings import base
        self.assertEqual(base.STORAGES["staticfiles"]["BACKEND"], "whitenoise.storage.CompressedManifestStaticFilesStorage")
        self.assertFalse(hasattr(base, "STATICFILES_STORAGE"))
        self.assertEqual(base.DATA_UPLOAD_MAX_MEMORY_SIZE, 10 * 1024 * 1024)
class DevelopmentMediaTests(TestCase):
    def test_uploads_are_served_with_byte_ranges_so_videos_can_seek(self):
        from django.http import Http404
        from django.test import RequestFactory
        from apps.common.views import serve_media
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        Path(media, "learning").mkdir()
        Path(media, "learning", "clip.webm").write_bytes(bytes(range(100)))
        factory = RequestFactory()
        with override_settings(MEDIA_ROOT=media):
            whole = serve_media(factory.get("/media/learning/clip.webm"), "learning/clip.webm")
            self.assertEqual((whole.status_code, whole["Accept-Ranges"]), (200, "bytes"))
            self.assertEqual(b"".join(whole.streaming_content), bytes(range(100)))
            part = serve_media(factory.get("/media/learning/clip.webm", HTTP_RANGE="bytes=10-19"), "learning/clip.webm")
            self.assertEqual((part.status_code, part["Content-Range"], part["Content-Length"]), (206, "bytes 10-19/100", "10"))
            self.assertEqual(b"".join(part.streaming_content), bytes(range(10, 20)))
            tail = serve_media(factory.get("/", HTTP_RANGE="bytes=-5"), "learning/clip.webm")
            self.assertEqual(b"".join(tail.streaming_content), bytes(range(95, 100)))
            self.assertEqual(serve_media(factory.get("/", HTTP_RANGE="bytes=500-"), "learning/clip.webm").status_code, 416)
            for path in ["../secret.txt", "learning/missing.webm"]:
                with self.assertRaises(Http404):
                    serve_media(factory.get("/"), path)
