from datetime import timedelta
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Profile
from apps.core.models import ActivityEvent, Project, Repository
from apps.core.services import refresh_rank
from .models import ContactRequest, PortfolioView, Shortlist, ShortlistEntry
from .views import DAILY_CONTACT_LIMIT
def make_user(email, first_name, last_name, role="developer", **profile_fields):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, role=role, **profile_fields)
    return user
def give_code(user, title, languages, status="complete"):
    project = Project.objects.create(owner=user, title=title, status=status)
    Repository.objects.create(project=project, owner=user, slug=title.lower().replace(" ", "-"), languages=languages)
    ActivityEvent.objects.create(user=user, event_type="project", action="pushed_commits", points=5, metadata={"commits": 2})
    refresh_rank(user)
class RecruiterAccessTests(TestCase):
    def test_recruiters_land_in_talent_search_and_developers_are_kept_out(self):
        recruiter = make_user("hr@example.com", "Hana", "Recruiter", role="recruiter")
        developer = make_user("dev@example.com", "Dev", "Eloper")
        self.client.force_login(recruiter)
        self.assertRedirects(self.client.get(reverse("landing:dashboard")), reverse("recruiting:search"))
        page = self.client.get(reverse("recruiting:search"))
        self.assertContains(page, "RECRUITER MODE")
        self.assertContains(page, "Shortlists")
        self.client.force_login(developer)
        for name in ["recruiting:search", "recruiting:shortlists", "recruiting:outreach"]:
            self.assertRedirects(self.client.get(reverse(name)), reverse("landing:dashboard"), fetch_redirect_response=False)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("recruiting:search")).status_code, 302)
    def test_organizations_have_recruiter_access(self):
        self.client.force_login(make_user("org@example.com", "Org", "Team", role="organization"))
        self.assertEqual(self.client.get(reverse("recruiting:search")).status_code, 200)
class TalentSearchTests(TestCase):
    def setUp(self):
        self.recruiter = make_user("hr@example.com", "Hana", "Recruiter", role="recruiter")
        self.python_dev = make_user("py@example.com", "Priya", "Sharma", headline="Django backend engineer", skills="Django, PostgreSQL", location="Pune")
        self.go_dev = make_user("go@example.com", "Gopal", "Rao", headline="Infra engineer", skills="Kubernetes", location="Bengaluru")
        self.hidden = make_user("hidden@example.com", "Hidden", "Person", recruiter_visible=False)
        self.other_recruiter = make_user("hr2@example.com", "Other", "Recruiter", role="recruiter")
        give_code(self.python_dev, "Api", {"Python": 900, "HTML": 100})
        give_code(self.go_dev, "Infra", {"Go": 500}, status="building")
        give_code(self.hidden, "Secret", {"Python": 100})
        self.client.force_login(self.recruiter)
    def names(self, **params):
        return [profile.user.first_name for profile in self.client.get(reverse("recruiting:search"), params).context["page"]]
    def test_only_visible_developers_are_listed_ranked_by_score(self):
        self.assertEqual(self.names(), ["Priya", "Gopal"])
    def test_filters_by_verified_language_skill_location_text_and_score(self):
        self.assertEqual(self.names(language="Go"), ["Gopal"])
        self.assertEqual(self.names(language="Rust"), [])
        self.assertEqual(self.names(skill="django"), ["Priya"])
        self.assertEqual(self.names(location="bengaluru"), ["Gopal"])
        self.assertEqual(self.names(q="priya backend"), ["Priya"])
        self.assertEqual(self.names(q="priya infra"), [])
        self.assertEqual(self.names(min_score="15"), ["Priya"])
    def test_active_filter_requires_code_pushed_in_last_30_days(self):
        ActivityEvent.objects.filter(user=self.go_dev).update(created_at=timezone.now() - timedelta(days=45))
        self.assertEqual(self.names(active="1"), ["Priya"])
    def test_cards_show_verified_evidence(self):
        response = self.client.get(reverse("recruiting:search"))
        priya = response.context["page"][0]
        self.assertEqual([language["name"] for language in priya.top_languages], ["Python", "HTML"])
        self.assertEqual((priya.verified_projects, priya.shipped_projects, priya.coding_days), (1, 1, 1))
        self.assertContains(response, "Python <small>90%</small>", html=False)
        self.assertNotContains(response, "py@example.com")
class ShortlistTests(TestCase):
    def setUp(self):
        self.recruiter = make_user("hr@example.com", "Hana", "Recruiter", role="recruiter")
        self.developer = make_user("dev@example.com", "Dev", "Eloper")
        self.client.force_login(self.recruiter)
    def test_add_is_idempotent_and_creates_a_default_list(self):
        url = reverse("recruiting:shortlist_add", args=["dev-eloper"])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(Shortlist.objects.get(owner=self.recruiter).name, "My shortlist")
        self.assertEqual(ShortlistEntry.objects.count(), 1)
        profile_page = self.client.get(reverse("landing:public_profile", args=["dev-eloper"]))
        self.assertContains(profile_page, "☆ Shortlisted")
    def test_named_lists_stages_and_private_notes(self):
        self.client.post(reverse("recruiting:shortlists"), {"name": "Backend, Pune"})
        shortlist = Shortlist.objects.get(owner=self.recruiter, name="Backend, Pune")
        self.client.post(reverse("recruiting:shortlist_add", args=["dev-eloper"]), {"shortlist": shortlist.pk})
        entry = ShortlistEntry.objects.get(shortlist=shortlist)
        self.client.post(reverse("recruiting:shortlist_entry", args=[entry.pk]), {"action": "update", "stage": "interviewing", "note": "Strong system design"})
        entry.refresh_from_db()
        self.assertEqual((entry.stage, entry.note), ("interviewing", "Strong system design"))
        page = self.client.get(reverse("recruiting:shortlists"), {"list": shortlist.pk})
        self.assertContains(page, "Strong system design")
        self.client.post(reverse("recruiting:shortlist_entry", args=[entry.pk]), {"action": "remove"})
        self.assertFalse(ShortlistEntry.objects.exists())
    def test_other_recruiters_cannot_touch_entries_and_hidden_developers_cannot_be_added(self):
        shortlist = Shortlist.objects.create(owner=self.recruiter, name="Mine")
        entry = ShortlistEntry.objects.create(shortlist=shortlist, candidate=self.developer, note="secret")
        self.client.force_login(make_user("hr2@example.com", "Other", "Recruiter", role="recruiter"))
        self.assertEqual(self.client.post(reverse("recruiting:shortlist_entry", args=[entry.pk]), {"action": "remove"}).status_code, 404)
        self.assertNotContains(self.client.get(reverse("recruiting:shortlists")), "secret")
        make_user("shy@example.com", "Shy", "Dev", recruiter_visible=False)
        self.assertEqual(self.client.post(reverse("recruiting:shortlist_add", args=["shy-dev"])).status_code, 404)
        self.assertTrue(ShortlistEntry.objects.filter(pk=entry.pk).exists())
class ContactRequestTests(TestCase):
    def setUp(self):
        self.recruiter = make_user("hr@example.com", "Hana", "Recruiter", role="recruiter", headline="Talent at Acme")
        self.developer = make_user("dev@example.com", "Dev", "Eloper")
        self.url = reverse("recruiting:contact", args=["dev-eloper"])
        self.message = {"role_title": "Backend Engineer", "message": "Your Django API project stood out to our team."}
    def test_request_flow_shares_email_only_after_acceptance(self):
        self.client.force_login(self.recruiter)
        Shortlist.objects.create(owner=self.recruiter, name="Backend").entries.create(candidate=self.developer)
        self.client.post(self.url, self.message)
        contact = ContactRequest.objects.get()
        self.assertEqual(ShortlistEntry.objects.get().stage, "contacted")
        self.assertNotContains(self.client.get(reverse("recruiting:outreach")), "dev@example.com")
        self.client.force_login(self.developer)
        network = self.client.get(reverse("landing:workspace_section", args=["network"]))
        self.assertContains(network, "Backend Engineer")
        self.assertContains(network, "Talent at Acme")
        self.assertNotContains(network, "hr@example.com")
        self.assertContains(self.client.get(reverse("landing:dashboard")), 'class="nav-alert">1<')
        self.client.post(reverse("recruiting:respond_contact", args=[contact.pk]), {"action": "accept"})
        contact.refresh_from_db()
        self.assertEqual(contact.status, "accepted")
        self.assertContains(self.client.get(reverse("landing:workspace_section", args=["network"])), "mailto:hr@example.com")
        self.client.force_login(self.recruiter)
        self.assertContains(self.client.get(reverse("recruiting:outreach")), "mailto:dev@example.com")
        self.assertContains(self.client.get(reverse("landing:public_profile", args=["dev-eloper"])), "mailto:dev@example.com")
    def test_duplicate_pending_requests_short_messages_and_daily_limit_are_blocked(self):
        self.client.force_login(self.recruiter)
        self.client.post(self.url, {"role_title": "Role", "message": "too short"})
        self.assertFalse(ContactRequest.objects.exists())
        self.client.post(self.url, self.message)
        self.client.post(self.url, self.message)
        self.assertEqual(ContactRequest.objects.count(), 1)
        for index in range(DAILY_CONTACT_LIMIT):
            make_user(f"dev{index}@example.com", "Bulk", f"Dev{index}")
            self.client.post(reverse("recruiting:contact", args=[f"bulk-dev{index}"]), self.message)
        self.assertEqual(ContactRequest.objects.count(), DAILY_CONTACT_LIMIT)
    def test_only_the_recipient_can_respond_and_developers_cannot_send(self):
        contact = ContactRequest.objects.create(recruiter=self.recruiter, developer=self.developer, **self.message)
        self.client.force_login(make_user("other@example.com", "Other", "Dev"))
        self.assertEqual(self.client.post(reverse("recruiting:respond_contact", args=[contact.pk]), {"action": "accept"}).status_code, 404)
        self.client.post(reverse("recruiting:contact", args=["dev-eloper"]), self.message)
        self.assertEqual(ContactRequest.objects.count(), 1)
        contact.refresh_from_db()
        self.assertEqual(contact.status, "pending")
class PortfolioViewTests(TestCase):
    def test_views_are_counted_once_per_viewer_per_day_and_recruiters_separately(self):
        developer = make_user("dev@example.com", "Dev", "Eloper")
        recruiter = make_user("hr@example.com", "Hana", "Recruiter", role="recruiter")
        peer = make_user("peer@example.com", "Peer", "Dev")
        url = reverse("landing:public_profile", args=["dev-eloper"])
        self.client.get(url)
        for viewer in [recruiter, recruiter, peer, developer]:
            self.client.force_login(viewer)
            self.client.get(url)
        self.assertEqual(PortfolioView.objects.count(), 2)
        self.client.force_login(developer)
        portfolio = self.client.get(reverse("landing:workspace_section", args=["portfolio"]))
        self.assertEqual((portfolio.context["portfolio_views"], portfolio.context["recruiter_views"]), (2, 1))
