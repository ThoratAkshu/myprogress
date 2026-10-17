"""Access between account types and between people: every page is checked on the server, not just hidden."""
import shutil
import tempfile
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import get_resolver, reverse
from django.urls.resolvers import URLResolver
from django.utils import timezone
from apps.accounts.access import POLICY
from apps.accounts.models import Profile
from apps.core.models import LearningPost, Project
from apps.organizations import services
from apps.organizations.models import Certificate, Invite, Membership
from apps.recruiting.models import Shortlist, ShortlistEntry

PASSWORD = "StrongPass!482"
ARTICLE = "## Why\n\n" + "Plain words about how the ledger posts entries and why each step matters. " * 4


def make_user(email, role="developer", first_name="Test", last_name="User"):
    user = User.objects.create_user(username=email, email=email, password=PASSWORD, first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, role=role, handle=email.split("@")[0])
    return user


def url_names(patterns, namespace=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            inner = f"{namespace}:{pattern.namespace}" if namespace and pattern.namespace else pattern.namespace or namespace
            yield from url_names(pattern.url_patterns, inner)
        elif pattern.name:
            yield f"{namespace}:{pattern.name}" if namespace else pattern.name


class PolicyCoverageTests(TestCase):
    def test_every_page_has_an_access_rule(self):
        missing = sorted(name for name in set(url_names(get_resolver().url_patterns)) if not name.startswith("admin:") and name not in POLICY)
        self.assertEqual(missing, [], "Add these URLs to apps/accounts/access.py POLICY")


MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class RoleBoundaryTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.developer = make_user("dev@example.com")
        self.recruiter = make_user("hr@company.example", role="recruiter")
        self.organization = make_user("office@institute.example", role="organization")

    def assertBlocked(self, user, url, who):
        self.client.force_login(user)
        response = self.client.get(url, follow=True)
        self.assertEqual(response.redirect_chain[0][0], reverse("landing:dashboard"), url)
        self.assertContains(response, f"That page is only for {who}.")

    def assertOpens(self, user, url):
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, f"{user.profile.role} {url}")

    def test_each_account_type_only_opens_its_own_pages(self):
        developer_pages = [reverse("landing:workspace_section", args=[section]) for section in ["portfolio", "projects", "learning", "earnings"]]
        for url in developer_pages:
            self.assertOpens(self.developer, url)
            self.assertBlocked(self.recruiter, url, "developer accounts")
            self.assertBlocked(self.organization, url, "developer accounts")
        for url in [reverse("recruiting:search"), reverse("recruiting:shortlists"), reverse("recruiting:outreach")]:
            self.assertOpens(self.recruiter, url)
            self.assertOpens(self.organization, url)
            self.assertBlocked(self.developer, url, "recruiter and organization accounts")
        studio = reverse("learning:create")
        self.assertOpens(self.developer, studio)
        self.assertOpens(self.organization, studio)
        self.assertBlocked(self.recruiter, studio, "developer and organization accounts")
        self.assertOpens(self.organization, reverse("organizations:create"))
        self.assertBlocked(self.developer, reverse("organizations:create"), "organization accounts")
        self.assertBlocked(self.recruiter, reverse("organizations:create"), "organization accounts")
        for user in [self.developer, self.recruiter, self.organization]:
            self.assertOpens(user, reverse("landing:workspace_section", args=["rankings"]))
            self.assertOpens(user, reverse("notifications:list"))

    def test_signed_out_visitors_are_sent_to_sign_in(self):
        for url in [reverse("landing:workspace_section", args=["projects"]), reverse("recruiting:search"), reverse("learning:create"), reverse("notifications:list"), reverse("organizations:home")]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith(reverse("landing:home")), url)
        self.assertEqual(self.client.get(reverse("landing:public_profile", args=["dev"])).status_code, 200)

    def test_forms_and_data_endpoints_refuse_the_wrong_account_type(self):
        self.client.force_login(self.recruiter)
        self.assertEqual(self.client.post(reverse("landing:create_project"), {"title": "Sneaky"}).status_code, 403)
        self.assertFalse(Project.objects.exists())
        response = self.client.post(reverse("learning:studio_preview"), {"body": "# hi"}, headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("developer and organization accounts", response.json()["error"])
        self.assertEqual(self.client.post(reverse("learning:create"), {"title": "Post", "kind": "article", "body": ARTICLE, "is_public": "on"}).status_code, 403)
        self.assertFalse(LearningPost.objects.exists())
        self.assertEqual(self.client.post(reverse("landing:issue_git_token"), {"name": "laptop"}).status_code, 403)
        self.assertFalse(self.recruiter.git_tokens.exists())
        self.client.force_login(self.developer)
        candidate = make_user("candidate@example.com")
        self.assertEqual(self.client.post(reverse("recruiting:contact", args=["candidate"]), {"role_title": "Backend", "message": "x" * 30}).status_code, 403)
        self.assertFalse(candidate.contact_requests.exists())
        self.assertEqual(self.client.post(reverse("organizations:create"), {"name": "Mine", "kind": "institute"}).status_code, 403)
        self.client.force_login(self.organization)
        self.assertEqual(self.client.post(reverse("earnings:payment_details"), {"payout_method": "upi"}).status_code, 403)

    def test_changing_the_role_in_the_page_does_nothing(self):
        self.client.force_login(self.recruiter)
        self.client.post(reverse("landing:update_profile"), {"handle": "hiring-team", "headline": "Hiring", "role": "developer", "score": "999", "rank": "1", "email_verified_at": "2026-01-01"})
        profile = Profile.objects.get(user=self.recruiter)
        self.assertEqual((profile.role, profile.email_verified_at, profile.headline), ("recruiter", None, "Hiring"))
        self.assertNotEqual(profile.score, 999)  # the score is worked out from real activity, never taken from the form

    def test_private_pages_are_not_kept_by_shared_caches(self):
        self.client.force_login(self.developer)
        self.assertIn("private", self.client.get(reverse("landing:workspace_section", args=["rankings"]))["Cache-Control"])


@override_settings(MEDIA_ROOT=MEDIA)
class OtherPeoplesDataTests(TestCase):
    """Changing an id in the address or the page never reaches someone else's things."""

    def setUp(self):
        cache.clear()
        self.owner = make_user("owner@example.com")
        self.other = make_user("other@example.com")
        self.project = Project.objects.create(owner=self.owner, title="Private ledger", is_public=False)
        self.post = LearningPost.objects.create(author=self.owner, title="Draft", kind="article", body=ARTICLE, is_public=False)
        self.client.force_login(self.other)

    def test_projects_and_posts_stay_with_their_owner(self):
        self.assertEqual(self.client.get(reverse("landing:project", args=[self.project.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("landing:update_project", args=[self.project.pk]), {"summary": "Taken over", "is_public": "on"}).status_code, 404)
        self.project.refresh_from_db()
        self.assertEqual((self.project.summary, self.project.is_public), ("", False))
        self.assertEqual(self.client.get(reverse("learning:detail", args=[self.post.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("learning:edit", args=[self.post.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("learning:delete", args=[self.post.pk])).status_code, 404)
        self.assertTrue(LearningPost.objects.filter(pk=self.post.pk).exists())
        self.assertEqual(self.client.get(reverse("learning:studio_branches"), {"project": self.project.pk}).status_code, 404)
        self.assertEqual(self.client.post(reverse("learning:create"), {"title": "Mine now", "kind": "article", "body": ARTICLE, "project": self.project.pk, "is_public": "on"}).status_code, 200)
        self.assertFalse(LearningPost.objects.filter(title="Mine now").exists())

    def test_recruiters_cannot_touch_each_others_shortlists(self):
        first, second = make_user("first@hire.example", role="recruiter"), make_user("second@hire.example", role="recruiter")
        entry = ShortlistEntry.objects.create(shortlist=Shortlist.objects.create(owner=first, name="Zeta payments team"), candidate=self.owner)
        self.client.force_login(second)
        self.assertEqual(self.client.post(reverse("recruiting:shortlist_entry", args=[entry.pk]), {"action": "remove"}).status_code, 404)
        self.assertTrue(ShortlistEntry.objects.filter(pk=entry.pk).exists())
        self.assertNotContains(self.client.get(reverse("recruiting:shortlists")), "Zeta payments team")


@override_settings(MEDIA_ROOT=MEDIA)
class InvitationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.office = make_user("office@institute.example", role="organization")
        self.institute = services.create_organization(self.office, {"name": "Sunrise Institute", "kind": "institute", "city": "", "about": "", "website": "", "join_requires_approval": True})

    def invite(self, email, role):
        return Invite.objects.create(organization=self.institute, email=email, role=role, created_by=self.office)

    def test_a_forwarded_invitation_is_useless_to_anyone_else(self):
        invite = self.invite("meera@example.com", "teacher")
        stranger = make_user("stranger@example.com")
        self.client.force_login(stranger)
        page = self.client.post(reverse("organizations:accept_invite", args=[invite.token]))
        self.assertContains(page, "This invitation was sent to m••••@example.com")
        self.assertFalse(Membership.objects.filter(user=stranger).exists())
        self.assertFalse(Invite.objects.get(pk=invite.pk).accepted_at)

    def test_teacher_invitations_need_a_confirmed_email(self):
        invite = self.invite("meera@example.com", "teacher")
        meera = make_user("meera@example.com")
        self.client.force_login(meera)
        page = self.client.post(reverse("organizations:accept_invite", args=[invite.token]))
        self.assertContains(page, "Teacher invitations need a confirmed email")
        self.assertFalse(Membership.objects.filter(user=meera).exists())
        Profile.objects.filter(user=meera).update(email_verified_at=timezone.now())
        self.client.post(reverse("organizations:accept_invite", args=[invite.token]))
        self.assertEqual(Membership.objects.get(user=meera).role, "teacher")

    def test_the_invited_student_joins_straight_away(self):
        invite = self.invite("Asha@Example.com", "student")
        asha = make_user("asha@example.com")
        self.client.force_login(asha)
        self.client.post(reverse("organizations:accept_invite", args=[invite.token]))
        self.assertEqual(Membership.objects.get(user=asha).status, "active")

    def test_the_public_certificate_never_shows_an_email(self):
        student = make_user("quiet@example.com", first_name="", last_name="")
        services.join(self.institute, student, self.invite("quiet@example.com", "student"))
        certificate = Certificate.objects.create(organization=self.institute, student=student, issued_by=self.office, title="Python basics")
        self.client.logout()
        page = self.client.get(reverse("organizations:certificate", args=[certificate.code]))
        self.assertContains(page, "@quiet")
        self.assertNotContains(page, "quiet@example.com")
