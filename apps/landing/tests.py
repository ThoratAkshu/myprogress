import os
import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from django.conf import settings
from django.contrib.auth.models import User
from django.test import LiveServerTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Follow, Profile
from apps.core.git_service import commit_file, detect_languages, initialize_repository
from apps.core.models import ActivityEvent, GitAccessToken, Project, Repository, RepositoryCollaborator
from apps.core.services import contribution_calendar, language_breakdown
def make_user(email, first_name="Asha", last_name="Rao"):
    return User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
class PublicPortfolioTests(TestCase):
    def test_registration_assigns_a_unique_public_handle(self):
        self.client.post(reverse("landing:register"), {"first_name": "Asha", "last_name": "Rao", "email": "asha@example.com", "password": "StrongPass!482", "role": "developer", "terms": "1"})
        self.client.logout()
        self.client.post(reverse("landing:register"), {"first_name": "Asha", "last_name": "Rao", "email": "asha2@example.com", "password": "StrongPass!482", "role": "developer", "terms": "1"})
        self.assertEqual(User.objects.get(username="asha@example.com").profile.handle, "asha-rao")
        self.assertEqual(User.objects.get(username="asha2@example.com").profile.handle, "asha-rao-2")
    def test_profiles_created_lazily_also_get_a_handle(self):
        user = make_user("lazy@example.com", "Lazy", "Dev")
        self.client.force_login(user)
        self.client.get(reverse("landing:dashboard"))
        self.assertEqual(user.profile.handle, "lazy-dev")
    def test_public_profile_is_visible_anonymously_without_leaking_email(self):
        user = make_user("asha@example.com")
        Profile.objects.create(user=user, headline="Django developer", skills="Django, React")
        Project.objects.create(owner=user, title="Visible project", status="complete")
        Project.objects.create(owner=user, title="Hidden project", is_public=False)
        response = self.client.get(reverse("landing:public_profile", args=["asha-rao"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Django developer")
        self.assertContains(response, "Visible project")
        self.assertNotContains(response, "Hidden project")
        self.assertNotContains(response, "asha@example.com")
        self.assertContains(response, "Sign in to follow")
        self.assertEqual(self.client.get(reverse("landing:public_profile", args=["nobody-here"])).status_code, 404)
    def test_owner_can_edit_portfolio_and_handle_must_be_unique(self):
        user = make_user("asha@example.com")
        Profile.objects.create(user=make_user("taken@example.com", "Taken", "Name"))
        self.client.force_login(user)
        self.client.get(reverse("landing:dashboard"))
        response = self.client.post(reverse("landing:update_profile"), {"handle": "Asha-Builds", "headline": "Backend engineer", "location": "Pune", "bio": "I build APIs.", "skills": "Django, Django, PostgreSQL ,", "recruiter_visible": "on"})
        self.assertRedirects(response, reverse("landing:workspace_section", args=["portfolio"]))
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.handle, "asha-builds")
        self.assertEqual(user.profile.skills, "Django, PostgreSQL")
        self.assertTrue(user.profile.recruiter_visible)
        self.client.post(reverse("landing:update_profile"), {"handle": "taken-name", "headline": "Changed"})
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.handle, "asha-builds")
        self.assertEqual(user.profile.headline, "Backend engineer")
    def test_follow_toggles_and_self_follow_is_ignored(self):
        follower = make_user("follower@example.com", "Fol", "Lower")
        developer = make_user("dev@example.com", "Dev", "Eloper")
        Profile.objects.create(user=follower)
        Profile.objects.create(user=developer)
        self.client.force_login(follower)
        url = reverse("landing:follow", args=["dev-eloper"])
        self.assertRedirects(self.client.post(url), reverse("landing:public_profile", args=["dev-eloper"]))
        self.assertTrue(Follow.objects.filter(follower=follower, following=developer).exists())
        self.assertContains(self.client.get(reverse("landing:public_profile", args=["dev-eloper"])), "Following ✓")
        self.client.post(url)
        self.assertFalse(Follow.objects.filter(follower=follower, following=developer).exists())
        self.client.post(reverse("landing:follow", args=["fol-lower"]))
        self.assertFalse(Follow.objects.exists())
        self.assertEqual(self.client.get(url).status_code, 405)
class ContributionAndLanguageTests(TestCase):
    def test_contribution_calendar_counts_real_work_only(self):
        user = make_user("asha@example.com")
        ActivityEvent.objects.create(user=user, event_type="project", action="pushed_commits", points=5, metadata={"commits": 7})
        ActivityEvent.objects.create(user=user, event_type="project", action="created_project", points=3)
        ActivityEvent.objects.create(user=user, event_type="login", action="signed_in", points=1)
        ActivityEvent.objects.create(user=user, event_type="project", action="completed_build_loop", points=1)
        old = ActivityEvent.objects.create(user=user, event_type="project", action="created_project", points=3)
        ActivityEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
        calendar = contribution_calendar(user)
        self.assertEqual(calendar["total"], 8)
        self.assertEqual(calendar["active_days"], 1)
        self.assertEqual(calendar["days"][0]["date"].weekday(), 6)
        self.assertEqual(calendar["days"][-1]["date"], timezone.localdate())
        self.assertEqual(calendar["days"][-1]["level"], 3)
        self.assertGreaterEqual(calendar["weeks"] * 7, len(calendar["days"]))
    def test_language_breakdown_groups_small_languages(self):
        user = make_user("asha@example.com")
        languages = {"Python": 600, "JavaScript": 200, "HTML": 100, "CSS": 50, "Shell": 20, "Go": 15, "Rust": 10, "C": 5}
        Repository.objects.create(project=Project.objects.create(owner=user, title="One"), owner=user, slug="one", languages=languages)
        breakdown = language_breakdown(user.repositories.values_list("languages", flat=True))
        self.assertEqual(breakdown[0], {"name": "Python", "percent": 60.0})
        self.assertEqual(breakdown[-1], {"name": "Other", "percent": 1.5})
        self.assertEqual(language_breakdown([]), [])
class RepositoryPermissionTests(TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.override = override_settings(GIT_REPOSITORY_ROOT=self.storage.name)
        self.override.enable()
        self.owner = make_user("owner@example.com", "Own", "Er")
        self.repository = Repository.objects.create(project=Project.objects.create(owner=self.owner, title="Secret"), owner=self.owner, slug="secret")
        initialize_repository(self.repository)
        commit_file(self.repository, "app.py", "print('hi')\n", self.owner, "Initial")
    def tearDown(self):
        self.override.disable()
        self.storage.cleanup()
    def test_read_collaborator_cannot_write_or_change_settings(self):
        reader = make_user("reader@example.com", "Read", "Er")
        RepositoryCollaborator.objects.create(repository=self.repository, user=reader, role="read")
        self.client.force_login(reader)
        url = reverse("landing:repository", args=[self.repository.pk])
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "data-add-file-toggle")
        self.assertNotContains(page, "?tab=settings")
        self.client.post(url, {"action": "settings", "visibility": "public", "default_branch": "main"})
        self.client.post(url, {"action": "add_file", "path": "evil.txt", "content": "x", "message": "evil"})
        self.client.post(url, {"action": "create_branch", "name": "evil", "source": "main"})
        self.repository.refresh_from_db()
        self.assertEqual(self.repository.visibility, "private")
        self.assertEqual(self.client.get(url, {"tab": "settings"}).context["active_tab"], "code")
        from apps.core.git_service import list_branches, list_files
        self.assertEqual([branch["name"] for branch in list_branches(self.repository)], ["main"])
        self.assertNotIn("evil.txt", {item["name"] for item in list_files(self.repository)})
    def test_signed_in_strangers_can_read_public_repositories_only(self):
        stranger = make_user("stranger@example.com", "Str", "Anger")
        self.client.force_login(stranger)
        url = reverse("landing:repository", args=[self.repository.pk])
        self.assertRedirects(self.client.get(url), reverse("landing:workspace_section", args=["projects"]))
        Repository.objects.filter(pk=self.repository.pk).update(visibility="public")
        self.assertEqual(self.client.get(url).status_code, 200)
    def test_language_detection_ignores_vendored_code(self):
        commit_file(self.repository, "web/app.js", "console.log('hi');\n", self.owner, "JS")
        commit_file(self.repository, "node_modules/lib/index.js", "x" * 5000, self.owner, "Vendored")
        commit_file(self.repository, "static/app.min.js", "x" * 5000, self.owner, "Minified")
        commit_file(self.repository, "README.md", "# Secret\n", self.owner, "Docs")
        self.assertEqual(detect_languages(self.repository), {"JavaScript": 19, "Python": 12})
    def test_web_commit_refreshes_repository_languages(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("landing:repository", args=[self.repository.pk]), {"action": "add_file", "path": "src/main.go", "content": "package main\n", "message": "Go"})
        self.repository.refresh_from_db()
        self.assertEqual(self.repository.languages, {"Python": 12, "Go": 13})
class PushTrackingTests(LiveServerTestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.override = override_settings(GIT_REPOSITORY_ROOT=self.storage.name)
        self.override.enable()
    def tearDown(self):
        self.override.disable()
        self.storage.cleanup()
    def test_push_records_new_commits_and_languages(self):
        if not shutil.which(settings.GIT_EXECUTABLE):
            self.skipTest("Git executable is unavailable")
        user = make_user("pusher@example.com", "Push", "Er")
        repository = Repository.objects.create(project=Project.objects.create(owner=user, title="Pushed"), owner=user, slug="pushed")
        initialize_repository(repository)
        _, raw_token = GitAccessToken.issue(user, "Push test")
        remote = self.live_server_url.replace("://", f"://{quote(user.username, safe='')}:{quote(raw_token, safe='')}@", 1) + reverse("landing:git_root", args=[user.pk, repository.slug])
        # No credential helper: the key is already in the URL, and a helper would save it to the developer's keychain.
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": ""}
        def git(*args):
            result = subprocess.run([settings.GIT_EXECUTABLE, *args], cwd=checkout, capture_output=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        with tempfile.TemporaryDirectory() as root:
            checkout = Path(root)
            git("init", "-b", "main")
            git("config", "user.email", user.email)
            git("config", "user.name", "Push Er")
            (checkout / "main.py").write_bytes(b"print('one')\n")
            git("add", ".")
            git("commit", "-m", "One")
            (checkout / "app.ts").write_bytes(b"export const two = 2;\n")
            git("add", ".")
            git("commit", "-m", "Two")
            git("remote", "add", "origin", remote)
            git("push", "-u", "origin", "main")
            (checkout / "README.md").write_bytes(b"# Pushed\n")
            git("add", ".")
            git("commit", "-m", "Three")
            git("push")
            git("checkout", "-b", "feature")
            git("push", "-u", "origin", "feature")
        pushes = list(ActivityEvent.objects.filter(user=user, action="pushed_commits").order_by("created_at").values_list("metadata", flat=True))
        self.assertEqual([push["commits"] for push in pushes], [2, 1])
        repository.refresh_from_db()
        self.assertEqual(repository.languages, {"TypeScript": 22, "Python": 13})
        self.assertEqual(contribution_calendar(user)["total"], 3)
        self.assertTrue(user.daily_loop_completions.filter(step="build").exists())
