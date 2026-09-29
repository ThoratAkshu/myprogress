from django.contrib.auth.models import User
from django.test import TestCase, LiveServerTestCase
from django.test import override_settings
from django.urls import reverse
import base64
import tempfile
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote
class AuthenticationFlowTests(TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("landing:dashboard"))
        self.assertEqual(response.status_code, 302)
    def test_registration_creates_user_profile_and_session(self):
        response = self.client.post(reverse("landing:register"), {"first_name": "Asha", "last_name": "Rao", "email": "ASHA@example.com", "password": "StrongPass!482", "role": "developer", "terms": "1"})
        self.assertRedirects(response, reverse("landing:dashboard"))
        user = User.objects.get(username="asha@example.com")
        self.assertEqual(user.profile.role, "developer")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(username="asha@example.com", email="asha@example.com", password="StrongPass!482")
        response = self.client.post(reverse("landing:register"), {"first_name": "Asha", "last_name": "Rao", "email": "ASHA@example.com", "password": "StrongPass!482", "role": "developer", "terms": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(email__iexact="asha@example.com").count(), 1)
    def test_login_and_post_only_logout(self):
        User.objects.create_user(username="asha@example.com", email="asha@example.com", password="StrongPass!482")
        response = self.client.post(reverse("landing:login"), {"email": "ASHA@example.com", "password": "StrongPass!482"})
        self.assertRedirects(response, reverse("landing:dashboard"))
        self.assertEqual(self.client.get(reverse("landing:logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("landing:logout")), reverse("landing:home"))
    def test_authenticated_user_cannot_return_to_login_page(self):
        user = User.objects.create_user(username="asha@example.com", email="asha@example.com", password="StrongPass!482")
        self.client.force_login(user)
        response = self.client.get(reverse("landing:home"))
        self.assertRedirects(response, reverse("landing:dashboard"))
        dashboard = self.client.get(reverse("landing:dashboard"))
        self.assertIn("no-cache", dashboard.headers["Cache-Control"])
    def test_authenticated_user_can_create_project(self):
        user = User.objects.create_user(username="builder@example.com", password="StrongPass!482")
        self.client.force_login(user)
        response = self.client.post(reverse("landing:create_project"), {"title": "Portfolio API", "summary": "A documented API", "skills": "Django, PostgreSQL"})
        self.assertRedirects(response, reverse("landing:dashboard"))
        project = user.projects.get(title="Portfolio API")
        self.assertEqual(project.milestones.count(), 4)
        self.assertTrue(user.activity_events.filter(action="created_project").exists())
        self.assertTrue(user.daily_loop_completions.filter(step="build").exists())
    def test_all_workspace_sections_require_auth_and_render(self):
        sections = ["portfolio", "projects", "learning", "earnings", "rankings", "network"]
        for section in sections:
            self.assertEqual(self.client.get(reverse("landing:workspace_section", args=[section])).status_code, 302)
        user = User.objects.create_user(username="tabs@example.com", password="StrongPass!482")
        self.client.force_login(user)
        for section in sections:
            response = self.client.get(reverse("landing:workspace_section", args=[section]))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, section.title())
    def test_learning_views_are_unique_per_session_and_complete_loop(self):
        from apps.core.models import ContentView, LearningPost
        author = User.objects.create_user(username="author@example.com", password="StrongPass!482")
        viewer = User.objects.create_user(username="viewer@example.com", password="StrongPass!482")
        post = LearningPost.objects.create(author=author, title="Django architecture")
        self.client.force_login(viewer)
        self.client.get(reverse("landing:learning_view", args=[post.pk]))
        self.client.get(reverse("landing:learning_view", args=[post.pk]))
        self.assertEqual(ContentView.objects.filter(post=post).count(), 1)
        self.assertTrue(viewer.daily_loop_completions.filter(step="learn").exists())
    def test_private_git_repository_and_hashed_token(self):
        from apps.core.git_service import repository_path
        from apps.core.models import GitAccessToken, Project
        user = User.objects.create_user(username="git@example.com", password="StrongPass!482")
        project = Project.objects.create(owner=user, title="Native Git")
        self.client.force_login(user)
        with tempfile.TemporaryDirectory() as storage:
            with override_settings(GIT_REPOSITORY_ROOT=storage):
                response = self.client.post(reverse("landing:create_repository", args=[project.pk]), {"visibility": "private"})
                repository = user.repositories.get()
                self.assertTrue(repository_path(repository).exists())
                self.assertRedirects(response, reverse("landing:repository", args=[repository.pk]))
                token, raw = GitAccessToken.issue(user, "Test token")
                self.assertNotEqual(token.token_hash, raw)
                git_url = reverse("landing:git_http", args=[user.pk, repository.slug, "info/refs"]) + "?service=git-upload-pack"
                self.client.logout()
                challenge = self.client.get(git_url)
                self.assertEqual(challenge.status_code, 401)
                self.assertEqual(challenge["WWW-Authenticate"], 'Basic realm="MyProgress Credentials"')
                password_basic = base64.b64encode(f"{user.username}:StrongPass!482".encode()).decode()
                self.assertEqual(self.client.get(git_url, HTTP_AUTHORIZATION=f"Basic {password_basic}").status_code, 401)
                wrong_account_basic = base64.b64encode(f"someone@example.com:{raw}".encode()).decode()
                self.assertEqual(self.client.get(git_url, HTTP_AUTHORIZATION=f"Basic {wrong_account_basic}").status_code, 401)
                basic = base64.b64encode(f"{user.username}:{raw}".encode()).decode()
                self.assertEqual(self.client.get(git_url, HTTP_AUTHORIZATION=f"Basic {basic}").status_code, 200)
                push_url = reverse("landing:git_http", args=[user.pk, repository.slug, "info/refs"]) + "?service=git-receive-pack"
                self.assertEqual(self.client.get(push_url, HTTP_AUTHORIZATION=f"Basic {basic}").status_code, 200)

class RealGitWorkflowTests(LiveServerTestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(GIT_REPOSITORY_ROOT=self.storage.name)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.storage.cleanup()

    def test_user_can_clone_commit_and_push_first_branch(self):
        from django.conf import settings
        from apps.core.git_service import initialize_repository, list_branches
        from apps.core.models import GitAccessToken, Project, Repository
        if not shutil.which(settings.GIT_EXECUTABLE):
            self.skipTest("Git executable is unavailable")
        user = User.objects.create_user(username="launch@example.com", password="StrongPass!482")
        project = Project.objects.create(owner=user, title="First Launch")
        repository = Repository.objects.create(project=project, owner=user, slug="first-launch")
        initialize_repository(repository)
        _, raw_token = GitAccessToken.issue(user, "Integration test")
        authenticated_url = self.live_server_url.replace("://", f"://{quote(user.username, safe='')}:{quote(raw_token, safe='')}@", 1) + reverse("landing:git_root", args=[user.pk, repository.slug])
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        with tempfile.TemporaryDirectory() as checkout_root:
            checkout = Path(checkout_root) / "first-launch"
            subprocess.run([settings.GIT_EXECUTABLE, "clone", authenticated_url, str(checkout)], check=True, capture_output=True, env=environment)
            (checkout / "README.md").write_text("# First Launch\n", encoding="utf-8")
            subprocess.run([settings.GIT_EXECUTABLE, "config", "user.email", user.email or user.username], cwd=checkout, check=True)
            subprocess.run([settings.GIT_EXECUTABLE, "config", "user.name", "Launch User"], cwd=checkout, check=True)
            subprocess.run([settings.GIT_EXECUTABLE, "add", "README.md"], cwd=checkout, check=True)
            subprocess.run([settings.GIT_EXECUTABLE, "commit", "-m", "First launch"], cwd=checkout, check=True, capture_output=True)
            subprocess.run([settings.GIT_EXECUTABLE, "branch", "-M", repository.default_branch], cwd=checkout, check=True)
            push = subprocess.run([settings.GIT_EXECUTABLE, "push", "-u", "origin", repository.default_branch], cwd=checkout, capture_output=True, env=environment)
            self.assertEqual(push.returncode, 0, push.stderr.decode(errors="replace"))
        branches = list_branches(repository)
        self.assertEqual(branches[0]["name"], repository.default_branch)
        self.assertEqual(branches[0]["subject"], "First launch")
        self.client.force_login(user)
        for tab in ("code", "branches", "commits", "contributors", "settings"):
            response = self.client.get(reverse("landing:repository", args=[repository.pk]), {"tab": tab})
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "launch%40example.com@")
        identity = self.client.get(reverse("landing:account_identity"))
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.json()["account"], user.username)
        response = self.client.post(reverse("landing:repository", args=[repository.pk]), {"action": "add_file", "path": "docs/hello.md", "content": "# Hello\n", "message": "Add hello guide"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list_branches(repository)[0]["subject"], "Add hello guide")
        response = self.client.post(reverse("landing:repository", args=[repository.pk]), {"action": "create_branch", "name": "feature/welcome", "source": repository.default_branch})
        self.assertEqual(response.status_code, 302)
        self.assertIn("feature/welcome", {branch["name"] for branch in list_branches(repository)})
        response = self.client.post(reverse("landing:repository", args=[repository.pk]), {"action": "settings", "visibility": "public", "default_branch": "feature/welcome"})
        self.assertEqual(response.status_code, 302)
        repository.refresh_from_db()
        self.assertEqual(repository.visibility, "public")
        self.assertEqual(repository.default_branch, "feature/welcome")
