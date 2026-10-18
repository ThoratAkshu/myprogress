import tempfile
from datetime import timedelta
from importlib import import_module
from io import StringIO
from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Follow, Profile
from apps.core.git_service import initialize_repository
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
class RankingsPageTests(TestCase):
    def setUp(self):
        self.me = make_developer("me@example.com", "Mira", "Kapoor", location="Pune, India")
        self.leo = make_developer("leo@example.com", "Leo", "Fernandes", location="Goa")
        self.asha = make_developer("asha@example.com", "Asha", "Rao", location="Pune")
        self.zed = make_developer("zed@example.com", "Zed", "Shah", location="Delhi")
        add_project(self.me, "Mine", status="building", languages={"Python": 10})
        add_project(self.leo, "Leo app", status="complete", languages={"Go": 10})
        add_project(self.asha, "Asha app", status="complete", languages={"Python": 10})
        add_project(self.asha, "Asha two", status="complete", languages={"Python": 10})
        add_project(self.zed, "Zed app", status="building", languages={"Rust": 10})
        for days_ago in [0, 1, 2]:
            push_on(self.me, days_ago)
        push_on(self.me, 5)
        Follow.objects.create(follower=self.me, following=self.leo)
        call_command("refresh_scores", stdout=StringIO())
        self.url = reverse("landing:workspace_section", args=["rankings"])
        self.client.force_login(self.me)
    def test_standing_shows_rank_streak_weekly_change_and_next_target(self):
        from apps.core.models import RankSnapshot
        from apps.core.services import coding_streak
        self.assertEqual(coding_streak(self.me), 3)
        me = Profile.objects.get(user=self.me)
        RankSnapshot.objects.create(user=self.me, day=timezone.localdate() - timedelta(days=5), rank=me.rank + 2, score=max(me.score - 4, 0))
        page = self.client.get(self.url)
        self.assertContains(page, f"#{me.rank}")
        self.assertContains(page, "Up 2 places this week")
        self.assertContains(page, "+4 this week")
        self.assertContains(page, "3-day coding streak")
        above = Profile.objects.filter(role="developer", score__gt=me.score).order_by("score").first()
        self.assertContains(page, f"{above.score - me.score + 1} point")
        self.assertContains(page, "Fastest way up")
        self.assertContains(page, "of 11 earned")
        self.assertContains(page, "First push")
        self.assertTrue(RankSnapshot.objects.filter(user=self.leo, day=timezone.localdate()).exists())
    def test_scopes_compare_with_people_you_follow_your_city_and_this_weeks_climbers(self):
        from apps.core.models import RankSnapshot
        following = self.client.get(self.url, {"scope": "following"})
        names = [entry.user for entry in [*following.context["podium"], *following.context["leaderboard"]]]
        self.assertEqual(set(names), {self.me, self.leo})
        nearby = self.client.get(self.url, {"scope": "nearby"})
        self.assertEqual({entry.user for entry in [*nearby.context["podium"], *nearby.context["leaderboard"]]}, {self.me, self.asha})
        self.assertContains(nearby, "Top developers in Pune")
        zed = Profile.objects.get(user=self.zed)
        RankSnapshot.objects.create(user=self.zed, day=timezone.localdate() - timedelta(days=3), rank=zed.rank + 3, score=zed.score)
        rising = self.client.get(self.url, {"scope": "rising"})
        self.assertEqual([entry.user for entry in rising.context["leaderboard"]], [self.zed])
        self.assertContains(rising, "▲ 3")
        overall = self.client.get(self.url)
        self.assertEqual(len(overall.context["podium"]), 3)
        self.assertEqual([entry.is_me for entry in overall.context["podium"]], [False, False, True])
        self.assertContains(overall, 'class="podium-3 is-me"')
    def test_recruiters_see_the_leaderboard_without_a_personal_standing(self):
        recruiter = make_developer("hr@example.com", "Hana", "Iyer", role="recruiter")
        self.client.force_login(recruiter)
        page = self.client.get(self.url)
        self.assertContains(page, "Developer leaderboard")
        self.assertNotContains(page, "Your global rank")
        self.assertNotContains(page, "Achievements")
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
class ProjectVisibilityTests(TestCase):
    """A project and its code share one visibility: private unless its owner makes it public."""
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.override = override_settings(GIT_REPOSITORY_ROOT=self.storage.name)
        self.override.enable()
        self.owner = make_developer("vis@example.com", "Vera", "Owner")
        self.client.force_login(self.owner)
    def tearDown(self):
        self.override.disable()
        self.storage.cleanup()
    def private_repository(self, owner=None):
        project = Project.objects.create(owner=self.owner, title="Ledger", is_public=False)
        repository = Repository.objects.create(project=project, owner=owner or self.owner, slug="ledger", visibility="private")
        initialize_repository(repository)
        return project, repository
    def test_new_projects_are_private_unless_made_public_and_their_code_follows(self):
        page = self.client.get(reverse("landing:workspace_section", args=["projects"]))
        self.assertContains(page, 'name="visibility" value="private" checked')
        self.client.post(reverse("landing:create_project"), {"title": "Quiet tool"})
        self.client.post(reverse("landing:create_project"), {"title": "Open tool", "visibility": "public"})
        quiet, loud = self.owner.projects.get(title="Quiet tool"), self.owner.projects.get(title="Open tool")
        self.assertEqual((quiet.is_public, loud.is_public), (False, True))
        for project, asked in [(quiet, "public"), (loud, "private")]:  # the code can't be set apart from its project
            self.client.post(reverse("landing:create_repository", args=[project.pk]), {"visibility": asked})
        self.assertEqual((quiet.repository.visibility, loud.repository.visibility), ("private", "public"))
        page = self.client.get(reverse("landing:workspace_section", args=["projects"]))
        self.assertContains(page, 'name="visibility" value="public" checked')  # the open project's Update dialog
        self.assertContains(page, "is-private")
    def test_changing_it_on_the_project_or_the_repository_changes_both(self):
        project, repository = self.private_repository()
        self.client.post(reverse("landing:update_project", args=[project.pk]), {"summary": "Now open", "visibility": "public"})
        project.refresh_from_db()
        repository.refresh_from_db()
        self.assertEqual((project.is_public, repository.visibility, project.summary), (True, "public", "Now open"))
        self.client.post(reverse("landing:repository", args=[repository.pk]), {"action": "settings", "visibility": "private", "default_branch": "main"})
        project.refresh_from_db()
        repository.refresh_from_db()
        self.assertEqual((project.is_public, repository.visibility), (False, "private"))
    def test_only_the_repositorys_admins_change_who_sees_its_code(self):
        project, repository = self.private_repository(owner=make_developer("maker@example.com"))
        response = self.client.post(reverse("landing:update_project", args=[project.pk]), {"summary": "Edited", "visibility": "public"}, follow=True)
        self.assertContains(response, "Only the repository&#x27;s admins can change who can see its code")
        project.refresh_from_db()
        repository.refresh_from_db()
        self.assertEqual((project.is_public, repository.visibility, project.summary), (False, "private", "Edited"))
    def test_existing_projects_take_their_repositorys_visibility(self):
        project, repository = self.private_repository()
        Project.objects.filter(pk=project.pk).update(is_public=True)  # how projects started before
        loose = add_project(self.owner, "No code yet")
        import_module("apps.core.migrations.0018_project_visibility_follows_repository").align(django_apps, None)
        project.refresh_from_db()
        loose.refresh_from_db()
        self.assertEqual((project.is_public, loose.is_public), (False, True))
