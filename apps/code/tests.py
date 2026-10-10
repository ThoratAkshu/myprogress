import os
import subprocess
import tempfile
from pathlib import Path
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from apps.accounts.models import Profile
from apps.core.git_service import initialize_repository, list_branches, parse_diff, repository_path
from apps.core.models import Issue, Project, Repository, RepositoryCollaborator
from apps.notifications.models import Notification
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "author@example.com", "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "author@example.com"}
def make_user(email, first_name, last_name):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user)
    return user
def git(*args, cwd):
    return subprocess.run([settings.GIT_EXECUTABLE, *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True, text=True).stdout
def commit_files(repository, files, message, branch="main", base=None):
    """Commit files to a branch of a bare repository through a throwaway local clone."""
    with tempfile.TemporaryDirectory() as root:
        checkout = Path(root) / "work"
        git("clone", str(repository_path(repository)), str(checkout), cwd=root)
        existing = {line.strip().replace("origin/", "") for line in git("branch", "-r", cwd=checkout).splitlines()}
        if branch in existing:
            git("checkout", branch, cwd=checkout)
        elif base:
            git("checkout", "-b", branch, f"origin/{base}", cwd=checkout)
        else:
            git("checkout", "--orphan", branch, cwd=checkout)
        for name, content in files.items():
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else content.encode())
        git("add", "-A", cwd=checkout)
        git("commit", "-m", message, cwd=checkout)
        git("push", "origin", branch, cwd=checkout)
        return git("rev-parse", "HEAD", cwd=checkout).strip()
class RepositoryTestCase(TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.override = override_settings(GIT_REPOSITORY_ROOT=self.storage.name)
        self.override.enable()
        self.owner = make_user("owner@example.com", "Olivia", "Owner")
        self.repository = Repository.objects.create(project=Project.objects.create(owner=self.owner, title="Ledger", summary="Double-entry ledger"), owner=self.owner, slug="ledger", visibility="public")
        initialize_repository(self.repository)
        self.first_sha = commit_files(self.repository, {"README.md": "# Ledger\n\nSee [docs](https://example.com/docs).\n", "src/app.py": "print('hi')\n", "src/util/math.py": "def add(a, b):\n    return a + b\n", "web/index.js": "document.body.innerHTML = '<script>alert(1)</script>';\n", "logo.bin": b"\x00\x01\x02binary"}, "Initial commit")
        self.url = reverse("landing:repository", args=[self.repository.pk])
    def tearDown(self):
        self.override.disable()
        self.storage.cleanup()
    def blob_url(self, path, ref="main", **extra):
        query = "&".join(f"{key}={value}" for key, value in {"ref": ref, "path": path, **extra}.items())
        return f'{reverse("code:blob", args=[self.repository.pk])}?{query}'
class BrowsingTests(RepositoryTestCase):
    def test_root_lists_folders_first_renders_readme_and_latest_commit(self):
        response = self.client.get(self.url)
        names = [item["name"] for item in response.context["files"]]
        self.assertEqual(names, ["src", "web", "logo.bin", "README.md"])
        self.assertContains(response, '<h2 id="ledger">Ledger</h2>', html=False)
        self.assertContains(response, '<a href="https://example.com/docs" rel="nofollow noopener" target="_blank">docs</a>', html=False)
        self.assertContains(response, "Initial commit")
    def test_folders_breadcrumbs_and_redirect_to_files(self):
        response = self.client.get(self.url, {"path": "src"})
        self.assertEqual([item["path"] for item in response.context["files"]], ["src/util", "src/app.py"])
        self.assertEqual(response.context["parent_path"], "")
        nested = self.client.get(self.url, {"path": "src/util"})
        self.assertEqual([crumb["name"] for crumb in nested.context["crumbs"]], ["src", "util"])
        self.assertRedirects(self.client.get(self.url, {"path": "src/app.py"}), self.blob_url("src/app.py"), fetch_redirect_response=False)
    def test_bad_refs_paths_and_missing_folders_are_rejected(self):
        for params in [{"ref": "--output=/tmp/x"}, {"ref": "nope"}, {"path": "../secrets"}, {"path": "src/../../etc"}]:
            self.assertRedirects(self.client.get(self.url, params), self.url, fetch_redirect_response=False)
        self.assertEqual(self.client.get(self.url, {"path": "missing"}).status_code, 302)
    def test_file_view_escapes_code_and_previews_markdown(self):
        response = self.client.get(self.blob_url("web/index.js"))
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, 'id="L1"')
        readme = self.client.get(self.blob_url("README.md"))
        self.assertContains(readme, '<h2 id="ledger">Ledger</h2>', html=False)
        self.assertContains(self.client.get(self.blob_url("README.md", source=1)), "# Ledger")
        self.assertContains(self.client.get(self.blob_url("logo.bin")), "Binary file.")
    def test_branch_switch_shows_branch_files(self):
        commit_files(self.repository, {"FEATURE.md": "new\n"}, "Add feature notes", branch="feature/notes", base="main")
        names = [item["name"] for item in self.client.get(self.url, {"ref": "feature/notes"}).context["files"]]
        self.assertIn("FEATURE.md", names)
        self.assertNotIn("FEATURE.md", [item["name"] for item in self.client.get(self.url).context["files"]])
    def test_raw_files_are_never_served_as_html(self):
        commit_files(self.repository, {"page.html": "<script>alert(1)</script>"}, "Add page")
        raw = reverse("code:raw", args=[self.repository.pk])
        response = self.client.get(raw, {"ref": "main", "path": "page.html"})
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("sandbox", response["Content-Security-Policy"])
        binary = self.client.get(raw, {"ref": "main", "path": "logo.bin"})
        self.assertEqual(binary["Content-Type"], "application/octet-stream")
        self.assertTrue(binary["Content-Disposition"].startswith("attachment"))
        self.assertEqual(self.client.get(raw, {"ref": "main", "path": "missing.txt"}).status_code, 404)
    def test_commit_page_shows_the_diff(self):
        sha = commit_files(self.repository, {"src/app.py": "print('hello')\n"}, "Say hello")
        response = self.client.get(reverse("code:commit", args=[self.repository.pk, sha]))
        self.assertContains(response, "Say hello")
        self.assertContains(response, "print(&#x27;hello&#x27;)")
        self.assertEqual((response.context["additions"], response.context["deletions"]), (1, 1))
        self.assertEqual(self.client.get(reverse("code:commit", args=[self.repository.pk, "zzzz"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("code:commit", args=[self.repository.pk, "deadbeef"])).status_code, 404)
class AccessTests(RepositoryTestCase):
    def test_anonymous_visitors_read_public_repositories_without_write_controls(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-add-file-toggle")
        self.assertNotContains(response, "DESKTOP READY CHECK")
        self.assertNotContains(response, "?tab=settings")
        self.assertEqual(self.client.get(self.blob_url("src/app.py")).status_code, 200)
        contributors = self.client.get(self.url, {"tab": "contributors"})
        self.assertContains(contributors, "Test Author")
        self.assertNotContains(contributors, "author@example.com")
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(self.url, {"tab": "contributors"}), "author@example.com")
    def test_private_repositories_require_permission(self):
        Repository.objects.filter(pk=self.repository.pk).update(visibility="private")
        for url in [self.url, self.blob_url("src/app.py"), reverse("code:issues", args=[self.repository.pk]), reverse("code:raw", args=[self.repository.pk]) + "?ref=main&path=src/app.py"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith("/?next="))
        self.client.force_login(make_user("stranger@example.com", "Str", "Anger"))
        self.assertRedirects(self.client.get(self.blob_url("src/app.py")), reverse("landing:workspace_section", args=["projects"]))
class DiffParserTests(SimpleTestCase):
    def test_removed_lines_that_look_like_headers_are_kept(self):
        diff = "diff --git a/q.sql b/q.sql\nindex 1..2 100644\n--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,2 @@\n--- old comment\n+++ new comment\n select 1;\n\\ No newline at end of file\n"
        [file] = parse_diff(diff)
        self.assertEqual(file["path"], "q.sql")
        self.assertEqual([(line["kind"], line["text"]) for line in file["lines"]], [("hunk", "@@ -1,2 +1,2 @@"), ("del", "-- old comment"), ("add", "++ new comment"), ("context", "select 1;")])
        self.assertEqual((file["additions"], file["deletions"]), (1, 1))
class CollaboratorTests(RepositoryTestCase):
    def setUp(self):
        super().setUp()
        Repository.objects.filter(pk=self.repository.pk).update(visibility="private")
        self.teammate = make_user("mate@example.com", "Team", "Mate")
        self.collaborators_url = reverse("code:collaborators", args=[self.repository.pk])
    def test_owner_adds_updates_and_removes_collaborators(self):
        self.client.force_login(self.owner)
        self.client.post(self.collaborators_url, {"action": "add", "handle": "@Team-Mate", "role": "write"})
        membership = RepositoryCollaborator.objects.get(repository=self.repository)
        self.assertEqual((membership.user, membership.role), (self.teammate, "write"))
        self.assertEqual(Notification.objects.get(recipient=self.teammate).text, "Olivia Owner gave you write access to olivia-owner/ledger")
        self.client.post(self.collaborators_url, {"action": "add", "handle": "olivia-owner", "role": "read"})
        self.client.post(self.collaborators_url, {"action": "add", "handle": "nobody", "role": "read"})
        self.assertEqual(RepositoryCollaborator.objects.count(), 1)
        self.client.force_login(self.teammate)
        page = self.client.get(self.url)
        self.assertContains(page, "data-add-file-toggle")
        self.assertNotContains(page, "?tab=settings")
        self.assertContains(self.client.get(reverse("landing:workspace_section", args=["projects"])), "olivia-owner/ledger")
        self.client.post(self.collaborators_url, {"action": "remove", "collaborator_id": membership.pk})
        self.assertTrue(RepositoryCollaborator.objects.exists())
        self.client.force_login(self.owner)
        self.client.post(self.collaborators_url, {"action": "update", "collaborator_id": membership.pk, "role": "maintain"})
        membership.refresh_from_db()
        self.assertEqual(membership.role, "maintain")
        self.client.post(self.collaborators_url, {"action": "remove", "collaborator_id": membership.pk})
        self.assertFalse(RepositoryCollaborator.objects.exists())
        self.client.force_login(self.teammate)
        self.assertEqual(self.client.get(self.url).status_code, 302)
class IssueTests(RepositoryTestCase):
    def test_signed_in_users_open_issues_on_public_repositories(self):
        create_url = reverse("code:issue_create", args=[self.repository.pk])
        self.assertTrue(self.client.get(create_url)["Location"].startswith("/?next="))
        reporter = make_user("reporter@example.com", "Rita", "Reporter")
        self.client.force_login(reporter)
        response = self.client.post(create_url, {"title": "Balance is wrong", "body": "Steps: `add(1, 2)`"})
        issue = Issue.objects.get()
        self.assertRedirects(response, reverse("code:issue", args=[self.repository.pk, 1]))
        self.assertEqual((issue.number, issue.kind, issue.author), (1, "issue", reporter))
        self.assertEqual(Notification.objects.get(recipient=self.owner, kind="issue").text, "Rita Reporter opened issue #1 in olivia-owner/ledger: Balance is wrong")
        self.assertContains(self.client.get(reverse("code:issues", args=[self.repository.pk])), "Balance is wrong")
        self.client.force_login(self.owner)
        self.client.post(reverse("code:issue_comment", args=[self.repository.pk, 1]), {"body": "Thanks, looking into it."})
        self.assertTrue(Notification.objects.filter(recipient=reporter, kind="issue").exists())
    def test_only_the_author_or_writers_can_close_and_reopen(self):
        reporter = make_user("reporter@example.com", "Rita", "Reporter")
        Issue.objects.create(repository=self.repository, number=1, author=reporter, title="Bug")
        state_url = reverse("code:issue_state", args=[self.repository.pk, 1])
        self.client.force_login(make_user("bystander@example.com", "By", "Stander"))
        self.client.post(state_url, {"action": "close"})
        self.assertEqual(Issue.objects.get().state, "open")
        self.client.force_login(reporter)
        self.client.post(state_url, {"action": "close", "body": "Fixed by upgrading."})
        issue = Issue.objects.get()
        self.assertEqual((issue.state, issue.closed_by), ("closed", reporter))
        self.assertEqual(issue.comments.get().body, "Fixed by upgrading.")
        self.assertContains(self.client.get(reverse("code:issues", args=[self.repository.pk]), {"state": "closed"}), "Bug")
        self.client.force_login(self.owner)
        self.client.post(state_url, {"action": "reopen"})
        self.assertEqual(Issue.objects.get().state, "open")
class PullRequestTests(RepositoryTestCase):
    def setUp(self):
        super().setUp()
        self.writer = make_user("writer@example.com", "Wes", "Writer")
        RepositoryCollaborator.objects.create(repository=self.repository, user=self.writer, role="write")
        commit_files(self.repository, {"src/util/math.py": "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n"}, "Add subtraction", branch="feature/sub", base="main")
        self.create_url = reverse("code:pull_create", args=[self.repository.pk])
    def test_writer_opens_pull_request_and_owner_merges_it(self):
        Issue.objects.create(repository=self.repository, number=1, author=self.owner, title="Need subtraction")
        self.client.force_login(self.writer)
        preview = self.client.get(self.create_url, {"source": "feature/sub", "target": "main"})
        self.assertEqual([commit["subject"] for commit in preview.context["commits"]], ["Add subtraction"])
        self.assertEqual(preview.context["form_title"], "Add subtraction")
        self.client.post(self.create_url, {"source": "feature/sub", "target": "main", "title": "Add subtraction", "body": "Closes #1"})
        pull = Issue.objects.get(kind="pull")
        self.assertEqual(pull.number, 2)
        detail = self.client.get(reverse("code:pull", args=[self.repository.pk, 2]), {"tab": "files"})
        self.assertContains(detail, "def sub(a, b):")
        self.assertIs(detail.context["mergeable"], True)
        self.assertRedirects(self.client.get(reverse("code:issue", args=[self.repository.pk, 2])), reverse("code:pull", args=[self.repository.pk, 2]))
        self.client.post(self.create_url, {"source": "feature/sub", "target": "main", "title": "Duplicate"})
        self.assertEqual(Issue.objects.filter(kind="pull").count(), 1)
        self.client.force_login(self.owner)
        self.client.post(reverse("code:pull_merge", args=[self.repository.pk, 2]))
        pull.refresh_from_db()
        self.assertEqual(pull.state, "merged")
        main = next(branch for branch in list_branches(self.repository) if branch["name"] == "main")
        self.assertTrue(main["subject"].startswith("Merge pull request #2 from feature/sub"))
        self.assertTrue(pull.merge_commit.startswith(main["commit"]))
        self.assertTrue(Notification.objects.filter(recipient=self.writer, kind="pull", text__contains="merged your pull request #2").exists())
        self.assertContains(self.client.get(self.blob_url("src/util/math.py")), "def sub(a, b):")
    def test_conflicts_block_merging_and_branches_must_differ(self):
        commit_files(self.repository, {"src/util/math.py": "def add(a, b):\n    return b + a\n"}, "Reorder operands")
        commit_files(self.repository, {"src/util/math.py": "def add(a, b):\n    return a + b + 0\n"}, "Conflicting change", branch="feature/sub")
        self.client.force_login(self.owner)
        self.client.post(self.create_url, {"source": "main", "target": "main", "title": "Same branch"})
        self.assertFalse(Issue.objects.exists())
        self.client.post(self.create_url, {"source": "feature/sub", "target": "main", "title": "Conflicting"})
        detail = self.client.get(reverse("code:pull", args=[self.repository.pk, 1]))
        self.assertIs(detail.context["mergeable"], False)
        self.assertContains(detail, "This branch has conflicts.")
        response = self.client.post(reverse("code:pull_merge", args=[self.repository.pk, 1]), follow=True)
        self.assertContains(response, "These branches have conflicts.")
        self.assertEqual(Issue.objects.get().state, "open")
    def test_readers_cannot_open_or_merge_pull_requests(self):
        reader = make_user("reader@example.com", "Rea", "Der")
        self.client.force_login(reader)
        self.client.post(self.create_url, {"source": "feature/sub", "target": "main", "title": "Sneaky"})
        self.assertFalse(Issue.objects.exists())
        pull = Issue.objects.create(repository=self.repository, number=1, kind="pull", author=self.writer, title="PR", source_branch="feature/sub", target_branch="main")
        self.client.post(reverse("code:pull_merge", args=[self.repository.pk, 1]))
        pull.refresh_from_db()
        self.assertEqual(pull.state, "open")
