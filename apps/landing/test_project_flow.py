from django.test import TestCase
from django.urls import reverse
from apps.core.git_service import commit_file, initialize_repository
from apps.core.models import LearningPost, Project, Repository
from apps.promotions.tests import centre, live_post, make_user
class NewProjectTests(TestCase):
    def test_creating_a_project_stays_on_projects_with_it_in_view(self):
        user = make_user("asha@example.com")
        self.client.force_login(user)
        response = self.client.post(reverse("landing:create_project"), {"title": "Budget app", "visibility": "private"})
        project = Project.objects.get(owner=user)
        self.assertRedirects(response, reverse("landing:workspace_section", args=["projects"]) + f"#project-{project.pk}", fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("landing:workspace_section", args=["projects"])), f'id="project-{project.pk}"')
        missing = self.client.post(reverse("landing:create_project"), {"title": " "})
        self.assertRedirects(missing, reverse("landing:workspace_section", args=["projects"]) + "#new-project", fetch_redirect_response=False)
class PushNoticeTests(TestCase):
    """An open project or repository page learns about a push from its code version and offers a refresh."""
    def setUp(self):
        self.owner = make_user("owner@example.com")
        project = Project.objects.create(owner=self.owner, title="Ledger", is_public=False)
        self.repository = Repository.objects.create(project=project, owner=self.owner, slug="ledger", visibility="private")
        initialize_repository(self.repository)
        self.state = reverse("code:state", args=[self.repository.pk])
        self.client.force_login(self.owner)
    def version(self):
        return self.client.get(self.state).json()["version"]
    def test_the_version_changes_when_code_arrives(self):
        page = self.client.get(reverse("landing:project", args=[self.repository.project_id]))
        self.assertContains(page, "data-push-watch")
        self.assertContains(page, "landing/js/push-notice")
        before = self.version()
        self.assertEqual(before, page.context["code_version"])
        commit_file(self.repository, "README.md", "# Ledger\n", self.owner, "First commit")
        after = self.version()
        self.assertNotEqual(before, after)
        self.assertEqual(self.client.get(reverse("landing:repository", args=[self.repository.pk])).context["code_version"], after)
    def test_private_repositories_keep_their_state_to_themselves(self):
        self.client.force_login(make_user("stranger@example.com"))
        self.assertEqual(self.client.get(self.state).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.state).status_code, 404)
class WatchAdsTests(TestCase):
    """Watch puts ads between the videos as full-height slides: the suggestion in the first batch, and sponsored posts."""
    def setUp(self):
        self.viewer = make_user("viewer@example.com")
        author = make_user("author@example.com")
        for number in range(14):
            LearningPost.objects.create(author=author, title=f"Walkthrough {number:02d}", kind="video", video_url="https://youtu.be/dQw4w9WgXcQ", is_public=True)
        owner = make_user("owner@sunrise.in", role="organization")
        live_post(owner, centre(owner, is_listed=True))
        self.client.force_login(self.viewer)
    def kinds(self, response):
        return ["suggestion" if item.get("next_step") else "sponsored" if item.get("sponsored") else "video" for item in response.context["reel_items"]]
    def test_the_first_batch_has_the_suggestion_and_later_batches_sponsored_posts(self):
        first = self.client.get(reverse("learning:watch"))
        kinds = self.kinds(first)
        self.assertEqual(kinds.index("suggestion"), 3)
        self.assertIn("sponsored", kinds)
        self.assertContains(first, "reel-ad")
        self.assertContains(first, "guidance/feed")
        more = self.client.get(reverse("learning:watch"), {"more": "1", "shown": ",".join(str(pk) for pk in LearningPost.objects.order_by("-published_at").values_list("pk", flat=True)[:6])})
        self.assertNotIn("suggestion", self.kinds(more))
        self.assertContains(more, "Weekend Python batch")
