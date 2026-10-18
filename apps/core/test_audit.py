"""The change log: who changed access, visibility and security settings, and when; each log only for who may see it."""
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from apps.accounts.test_two_factor import next_code, turn_on
from apps.companies.models import CompanyMember, Team
from apps.companies.tests import CompanyTestCase
from apps.core.models import AuditEvent, RepositoryCollaborator


class ChangeLogTests(CompanyTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def test_owners_see_who_changed_people_teams_access_and_settings(self):
        self.join(self.teammate)
        repository = self.new_repository("Billing API")
        people = reverse("companies:people", args=[self.company.slug])
        self.client.force_login(self.owner)
        self.client.post(people, {"action": "invite", "invitee": "new@example.com", "role": "owner"})
        self.client.post(people, {"action": "role", "id": CompanyMember.objects.get(user=self.teammate).pk, "role": "owner"})
        self.client.post(reverse("companies:settings", args=[self.company.slug]), {"action": "security", "repository_creation": "private", "members_invite_outside": "on"})
        self.client.post(reverse("companies:team_create", args=[self.company.slug]), {"name": "Backend"})
        team = Team.objects.get()
        self.client.post(reverse("companies:team", args=[self.company.slug, team.slug]), {"action": "add_repository", "id": repository.pk, "role": "maintain"})
        self.client.post(f"{reverse('landing:repository', args=[repository.pk])}", {"action": "settings", "visibility": "public", "default_branch": "main"})
        page = self.client.get(f"{self.detail}?tab=log")
        for line in ["Olivia Owner</b> created acme-labs/billing-api as a private repository", "invited new@example.com to join as an owner", "made Team Mate an owner",
                     "set who creates repositories to “Private only”", "kept visibility changes to owners", "created the Backend team",
                     "gave the Backend team Maintain access to acme-labs/billing-api", "made acme-labs/billing-api public"]:
            self.assertContains(page, line)
        self.assertNotContains(page, "let repository admins invite people from outside")  # unchanged settings aren't logged
        self.assertEqual(AuditEvent.objects.filter(action="repository.visibility").get().company, self.company)
        # Members don't see the log.
        CompanyMember.objects.filter(user=self.teammate).update(role="member")
        self.client.force_login(self.teammate)
        page = self.client.get(f"{self.detail}?tab=log")
        self.assertNotContains(page, "made acme-labs/billing-api public")
        self.assertNotContains(page, "?tab=log")

    def test_repository_admins_see_its_access_log(self):
        reader = self.teammate
        url = reverse("landing:repository", args=[self.repository.pk])
        access = reverse("code:collaborators", args=[self.repository.pk])
        self.client.post(access, {"action": "invite", "invitee": "@team-mate", "role": "read"})
        collaborator = RepositoryCollaborator.objects.create(repository=self.repository, user=reader, role="read")
        self.client.post(access, {"action": "update", "id": collaborator.pk, "role": "write"})
        self.client.post(url, {"action": "settings", "visibility": "private", "default_branch": "main"})
        page = self.client.get(f"{url}?tab=settings")
        for line in ["Access log", "invited Team Mate to olivia-owner/ledger with Read access", "changed Team Mate&#x27;s access to olivia-owner/ledger from Read to Write", "made olivia-owner/ledger private"]:
            self.assertContains(page, line)
        RepositoryCollaborator.objects.filter(pk=collaborator.pk).update(role="maintain")
        self.client.force_login(reader)
        self.assertNotContains(self.client.get(f"{url}?tab=settings"), "Access log")  # maintainers don't see it; admins do

    def test_your_security_log_has_sign_ins_and_two_step_changes(self):
        device, _ = turn_on(self.client, self.teammate)
        self.client.logout()
        sign_in = {"email": "mate@example.com", "password": "StrongPass!482"}
        self.client.post(reverse("landing:login"), sign_in)
        self.client.post(reverse("landing:two_step"), {"code": "000000" if next_code(device) != "000000" else "111111"})
        self.client.post(reverse("landing:two_step"), {"code": next_code(device)})
        page = self.client.get(reverse("landing:security"))
        for line in ["Signed in with two-step sign-in", "Entered a wrong two-step code", "Turned on two-step sign-in", "127.0.0.1"]:
            self.assertContains(page, line)
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse("landing:security")), "Entered a wrong two-step code")  # only your own
        # Choosing a new password from the emailed link is in it too.
        self.client.logout()
        link = reverse("landing:password_reset_confirm", args=[urlsafe_base64_encode(force_bytes(self.teammate.pk)), default_token_generator.make_token(self.teammate)])
        form = self.client.get(link, follow=True)
        self.client.post(form.request["PATH_INFO"], {"new_password1": "AnotherPass!9931", "new_password2": "AnotherPass!9931"})
        self.assertTrue(AuditEvent.objects.filter(user=self.teammate, action="account.password").exists())
        self.assertEqual(len(mail.outbox), 0)
