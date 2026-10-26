from datetime import timedelta
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Profile
from apps.core.models import ActivityEvent, ContentView, LearningPost, Project, ProjectMilestone
from apps.organizations.models import Membership, Organization
from . import services
from .models import StepDismissal, StepEvent
def make_user(email, role="developer", **profile):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=email.split("@")[0].title(), last_name="Test")
    Profile.objects.create(user=user, handle=email.split("@")[0], role=role, **profile)
    return user
def watched(user, count, days_ago=1):
    for _ in range(count):
        event = ActivityEvent.objects.create(user=user, event_type="learning", action="viewed_learning", metadata={})
        ActivityEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
class SegmentTests(TestCase):
    def test_only_watching_is_its_own_segment(self):
        user = make_user("scroller@example.com")
        User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=30))
        user.refresh_from_db()
        self.assertEqual(services.activity_summary(user).segment, services.QUIET)
        watched(user, services.WATCHING_MIN)
        self.assertEqual(services.activity_summary(user).segment, services.WATCHING)
        # Watching two weeks ago doesn't count any more.
        old = make_user("old@example.com")
        User.objects.filter(pk=old.pk).update(date_joined=timezone.now() - timedelta(days=60))
        old.refresh_from_db()
        watched(old, 10, days_ago=services.WINDOW_DAYS + 2)
        self.assertEqual(services.activity_summary(old).segment, services.QUIET)
    def test_making_something_means_building(self):
        user = make_user("builder@example.com")
        watched(user, 20)
        ActivityEvent.objects.create(user=user, event_type="project", action="pushed_commits", metadata={})
        self.assertEqual(services.activity_summary(user).segment, services.BUILDING)
        self.assertIsNone(services.next_step(user))
    def test_interests_come_from_the_projects_behind_watched_videos(self):
        user = make_user("viewer@example.com")
        author = make_user("author@example.com")
        project = Project.objects.create(owner=author, title="Shop API", skills="Python, Django")
        post = LearningPost.objects.create(author=author, title="How I built a shop API", kind="video", project=project, video_url="https://youtu.be/abc")
        ContentView.objects.create(post=post, viewer=user, session_key="s1")
        watched(user, services.WATCHING_MIN)
        summary = services.activity_summary(user)
        self.assertIn("Python", summary.interests)
        step = services.next_step(user, summary)
        self.assertEqual(step["key"], "start_project")
        self.assertIn("about Python", step["reason"])
class HomeFeedTests(TestCase):
    def setUp(self):
        self.user = make_user("asha@example.com", occupation="student", institution="COEP")
        User.objects.filter(pk=self.user.pk).update(date_joined=timezone.now() - timedelta(days=30))
        watched(self.user, 8)
        self.client.force_login(self.user)
    def test_someone_only_watching_is_offered_a_project_or_a_coaching_centre(self):
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "Recommended for you")  # nothing in their feed yet: it shows above the empty-feed message
        self.assertContains(page, "Turn what you&#x27;re watching into a project")
        self.assertContains(page, "You watched 8 videos")
        self.assertContains(page, "Prefer a teacher? Find a coaching centre")
        self.client.get(reverse("landing:dashboard"))
        shown = StepEvent.objects.get(user=self.user, step="start_project", action="shown")
        self.assertEqual(shown.count, 1)  # once a day, however often they refresh
    def test_the_suggestion_sits_in_the_feed_like_a_sponsored_post(self):
        author = make_user("writer@example.com")
        for number in range(5):
            post = LearningPost.objects.create(author=author, title=f"Build log {number}", kind="article", body="Notes", is_public=True)
            ActivityEvent.objects.create(user=author, event_type="learning", action="published_learning", metadata={"post_id": post.pk})
        page = self.client.get(reverse("landing:dashboard"))
        # After the 3rd post, the first sponsored slot, not pinned above the feed.
        self.assertEqual([index for index, item in enumerate(page.context["feed"]) if item.get("next_step")], [3])
        self.assertContains(page, "Recommended for you", count=1)
        self.assertContains(page, "Not now")
        self.assertContains(page, "I don&#x27;t want to do projects")
    def test_opening_a_suggestion_goes_to_its_page_and_is_counted(self):
        response = self.client.get(reverse("guidance:go", args=["start_project"]))
        self.assertRedirects(response, reverse("landing:workspace_section", args=["projects"]) + "#new-project", fetch_redirect_response=False)
        response = self.client.get(reverse("guidance:go", args=["start_project"]) + "?to=other")
        self.assertRedirects(response, reverse("organizations:find"), fetch_redirect_response=False)
        self.assertEqual(StepEvent.objects.get(user=self.user, step="start_project", action="clicked").count, 2)
        # Unknown or no-longer-fitting steps just go home; the link never carries an address of its own.
        self.assertRedirects(self.client.get(reverse("guidance:go", args=["share_secrets"])), reverse("landing:dashboard"), fetch_redirect_response=False)
    def test_not_wanting_projects_leads_to_coaching_centres(self):
        self.client.post(reverse("guidance:dismiss", args=["start_project"]), {"reason": "not_for_me"})
        dismissal = StepDismissal.objects.get(user=self.user, step="start_project")
        self.assertGreater(dismissal.until, timezone.now() + timedelta(days=services.NOT_FOR_ME_DAYS - 1))
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "Learn with a coaching centre")
        self.assertContains(page, "Find a coaching centre")
        response = self.client.post(reverse("guidance:dismiss", args=["join_centre"]), {"reason": "later"}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(response.json(), {"ok": True, "next": "practice"})
        self.assertContains(self.client.get(reverse("landing:dashboard")), "Solve one practice problem")
    def test_members_of_a_class_are_not_sent_to_find_one(self):
        owner = make_user("teacher@example.com", role="organization")
        organization = Organization.objects.create(owner=owner, name="Sunrise Coding", slug="sunrise")
        Membership.objects.create(organization=organization, user=self.user, role="student", status="active")
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "Turn what you&#x27;re watching into a project")
        self.assertNotContains(page, "Prefer a teacher?")
        self.assertContains(page, "Solve a practice problem")
class ProjectStepTests(TestCase):
    def test_a_project_without_code_then_a_stalled_one(self):
        user = make_user("ravi@example.com")
        project = Project.objects.create(owner=user, title="Budget app")
        Project.objects.filter(pk=project.pk).update(updated_at=timezone.now() - timedelta(days=20))
        self.assertEqual(services.next_step(user)["key"], "add_code")
        self.assertEqual(services.next_step(user)["title"], "Add code to Budget app")
        event = ActivityEvent.objects.create(user=user, event_type="project", action="pushed_commits", metadata={})
        ActivityEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=30))
        ProjectMilestone.objects.create(project=project, title="Charts page")
        step = services.next_step(user)
        self.assertEqual(step["key"], "resume_project")
        self.assertIn("Next milestone: Charts page.", step["reason"])
        self.assertEqual(step["primary"]["url"], reverse("landing:project", args=[project.pk]))
    def test_only_students_and_professionals_get_steps(self):
        recruiter = make_user("hr@example.com", role="recruiter")
        watched(recruiter, 10)
        self.assertIsNone(services.next_step(recruiter))
class ReportTests(TestCase):
    def test_staff_see_who_is_only_watching(self):
        member = make_user("scroll@example.com")
        watched(member, 6)
        builder = make_user("build@example.com")
        ActivityEvent.objects.create(user=builder, event_type="project", action="created_project", metadata={})
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("guidance:report")).status_code, 404)
        staff = make_user("staff@example.com")
        User.objects.filter(pk=staff.pk).update(is_staff=True)
        self.client.force_login(staff)
        page = self.client.get(reverse("guidance:report"))
        self.assertEqual(page.context["watching_only"], 1)
        self.assertEqual(page.context["building"], 1)
        self.assertContains(page, "Start a project")
