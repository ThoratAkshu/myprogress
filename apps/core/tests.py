from datetime import timedelta
from io import StringIO
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Follow, Profile
from apps.core.models import ActivityEvent, Project, ProjectMilestone, Repository
from apps.core.services import calculate_score, leaderboard, refresh_rank, score_breakdown
def make_developer(email, first_name="Dev", last_name="Eloper", **profile_fields):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, **profile_fields)
    return user
def add_project(user, title, status="planning", languages=None, is_public=True):
    project = Project.objects.create(owner=user, title=title, status=status, is_public=is_public)
    if languages is not None:
        Repository.objects.create(project=project, owner=user, slug=title.lower().replace(" ", "-"), languages=languages)
    return project
def push_on(user, days_ago):
    event = ActivityEvent.objects.create(user=user, event_type="project", action="pushed_commits", points=5, metadata={"commits": 3})
    ActivityEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
class ScoringTests(TestCase):
    def test_logins_and_checklist_clicks_never_add_points(self):
        user = make_developer("idle@example.com")
        for _ in range(30):
            ActivityEvent.objects.create(user=user, event_type="login", action="signed_in", points=1)
            ActivityEvent.objects.create(user=user, event_type="network", action="completed_share_loop", points=1)
        self.client.force_login(user)
        for step in ["build", "learn", "share"]:
            self.client.post(reverse("landing:complete_loop", args=[step]))
        self.assertEqual(calculate_score(user), 0)
    def test_only_projects_with_pushed_code_count_as_shipped_work(self):
        user = make_developer("builder@example.com")
        add_project(user, "Claimed only", status="complete")
        add_project(user, "Empty repo", status="complete", languages={})
        add_project(user, "Shipped", status="complete", languages={"Python": 100})
        add_project(user, "Building", status="building", languages={"Go": 100})
        shipped = next(component for component in score_breakdown(user) if component["key"] == "shipped")
        self.assertEqual(shipped["points"], 16)
        self.assertEqual(shipped["detail"], "1 shipped and 1 in progress with pushed code")
    def test_consistency_counts_distinct_days_in_last_90(self):
        user = make_developer("steady@example.com")
        for _ in range(5):
            push_on(user, 0)
        push_on(user, 3)
        push_on(user, 89)
        push_on(user, 120)
        consistency = next(component for component in score_breakdown(user) if component["key"] == "consistency")
        self.assertEqual(consistency["points"], 3)
    def test_components_are_capped_and_total_is_at_most_100(self):
        user = make_developer("max@example.com", headline="h", bio="b", skills="s", location="l")
        for index in range(5):
            add_project(user, f"Project {index}", status="complete", languages={"Python": 10})
        for day in range(40):
            push_on(user, day)
        for index in range(15):
            Follow.objects.create(follower=make_developer(f"fan{index}@example.com"), following=user)
        components = {component["key"]: component for component in score_breakdown(user)}
        self.assertEqual(components["shipped"]["points"], 35)
        self.assertEqual(components["consistency"]["points"], 25)
        self.assertEqual(components["community"]["points"], 10)
        self.assertEqual(components["profile"]["points"], 10)
        self.assertEqual(calculate_score(user), 80)
    def test_rank_ties_share_a_position_and_command_refreshes_everyone(self):
        leader = make_developer("leader@example.com", "Lead", "Er")
        tied_a = make_developer("a@example.com", "Tie", "A")
        tied_b = make_developer("b@example.com", "Tie", "B")
        add_project(leader, "Leader app", status="complete", languages={"Python": 1})
        add_project(tied_a, "A app", status="building", languages={"Go": 1})
        add_project(tied_b, "B app", status="building", languages={"Go": 1})
        call_command("refresh_scores", stdout=StringIO())
        ranks = dict(Profile.objects.values_list("user__email", "rank"))
        self.assertEqual(ranks, {"leader@example.com": 1, "a@example.com": 2, "b@example.com": 2})
        self.assertEqual(refresh_rank(tied_a).rank, 2)
    def test_leaderboard_respects_visibility_role_and_language(self):
        python_dev = make_developer("py@example.com", "Py", "Dev")
        go_dev = make_developer("go@example.com", "Go", "Dev")
        hidden = make_developer("hidden@example.com", "Hid", "Den", recruiter_visible=False)
        recruiter = make_developer("hr@example.com", "Hr", "Person", role="recruiter")
        add_project(python_dev, "Py app", status="complete", languages={"Python": 10})
        add_project(go_dev, "Go app", status="building", languages={"Go": 10})
        add_project(hidden, "Hidden app", status="complete", languages={"Python": 10})
        Profile.objects.filter(user=recruiter).update(score=99)
        call_command("refresh_scores", stdout=StringIO())
        self.assertEqual([profile.user.email for profile in leaderboard()], ["py@example.com", "go@example.com"])
        self.assertEqual([profile.user.email for profile in leaderboard("Go")], ["go@example.com"])
        self.client.force_login(go_dev)
        page = self.client.get(reverse("landing:workspace_section", args=["rankings"]), {"language": "Python"})
        self.assertContains(page, "Top Python developers")
        self.assertContains(page, "Py Dev")
        self.assertNotContains(page, "Hid Den")
class ProjectUpdateTests(TestCase):
    def test_completing_all_milestones_ships_the_project(self):
        user = make_developer("ship@example.com")
        project = add_project(user, "Shipper", languages={"Python": 10})
        milestones = ProjectMilestone.objects.bulk_create([ProjectMilestone(project=project, title=title, position=index) for index, title in enumerate(["Plan", "Build"])])
        self.client.force_login(user)
        url = reverse("landing:update_project", args=[project.pk])
        self.client.post(url, {"milestones": [milestones[0].pk], "summary": "Updated", "skills": "Django, Django", "live_url": "https://demo.example.com", "is_public": "on"})
        project.refresh_from_db()
        self.assertEqual((project.status, project.skills, project.calculated_progress), ("building", "Django", 50))
        self.client.post(url, {"milestones": [milestone.pk for milestone in milestones], "is_public": "on"})
        project.refresh_from_db()
        self.assertEqual(project.status, "complete")
        self.assertIsNotNone(project.milestones.get(pk=milestones[1].pk).completed_at)
        self.assertGreaterEqual(Profile.objects.get(user=user).score, 12)
    def test_invalid_live_url_and_other_owners_are_rejected(self):
        owner = make_developer("owner@example.com")
        intruder = make_developer("intruder@example.com")
        project = add_project(owner, "Mine")
        url = reverse("landing:update_project", args=[project.pk])
        self.client.force_login(owner)
        self.client.post(url, {"summary": "Changed", "live_url": "javascript:alert(1)"})
        project.refresh_from_db()
        self.assertEqual((project.summary, project.live_url), ("", ""))
        self.client.force_login(intruder)
        self.assertEqual(self.client.post(url, {"summary": "Hacked"}).status_code, 404)
