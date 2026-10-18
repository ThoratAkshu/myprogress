"""Two-step sign-in: codes from an authenticator app after the password, recovery codes, and companies that require it."""
import base64
import re
import time
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from apps.accounts import two_factor
from apps.accounts.models import Profile, RecoveryCode, TwoFactor
from apps.accounts.views import PENDING
from apps.code.tests import RepositoryTestCase, make_user
from apps.companies.models import Company, CompanyInvitation, CompanyMember
from apps.core.git_service import repository_role
from apps.core.models import Repository

PASSWORD = "StrongPass!482"


def next_code(device):
    """A code the server takes now. Each code works once per 30 seconds, so act as if the last one was a while ago."""
    TwoFactor.objects.filter(pk=device.pk).update(last_step=0)
    return two_factor.code_at(device.secret, two_factor.current_step())


def turn_on(client, user):
    client.force_login(user)
    client.post(reverse("landing:security"), {"action": "start"})
    device = TwoFactor.objects.get(user=user)
    page = client.post(reverse("landing:security"), {"action": "confirm", "code": next_code(device)})
    return device, re.findall(r"<code>([a-z0-9]{5}-[a-z0-9]{5})</code>", page.content.decode())


class CodeTests(TestCase):
    def test_codes_match_the_standard_and_each_works_once(self):
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(two_factor.code_at(secret, 59 // 30), "287082")  # RFC 6238's test vector, last 6 digits
        user = User.objects.create_user("codes@example.com", "codes@example.com", PASSWORD)
        device = TwoFactor.objects.create(user=user, secret=two_factor.new_secret())
        code = two_factor.code_at(device.secret, two_factor.current_step())
        self.assertFalse(two_factor.check_code(device, "000000" if code != "000000" else "111111"))
        self.assertTrue(two_factor.check_code(device, f"{code[:3]} {code[3:]}"))  # spaces are fine
        self.assertFalse(two_factor.check_code(device, code))  # but not twice
        self.assertFalse(two_factor.check_code(device, two_factor.code_at(device.secret, two_factor.current_step() + 5)))  # too far ahead


class TwoStepSignInTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("asha@example.com", "asha@example.com", PASSWORD, first_name="Asha")
        Profile.objects.create(user=self.user)

    def sign_in(self, **extra):
        return self.client.post(reverse("landing:login"), {"email": "asha@example.com", "password": PASSWORD, **extra})

    def test_setting_it_up_and_signing_in_with_a_code(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("landing:security"))
        self.assertContains(page, "Set up two-step sign-in")
        self.client.post(reverse("landing:security"), {"action": "start"})
        page = self.client.get(reverse("landing:security"))
        self.assertContains(page, "<svg")  # the QR code
        device = TwoFactor.objects.get(user=self.user)
        self.assertContains(page, two_factor.readable_secret(device.secret))
        self.assertContains(self.client.post(reverse("landing:security"), {"action": "confirm", "code": "000000" if next_code(device) != "000000" else "111111"}), "That code isn")
        self.assertFalse(two_factor.enabled(self.user))
        device, codes = turn_on(self.client, self.user)
        self.assertTrue(two_factor.enabled(self.user))
        self.assertEqual(len(codes), 10)
        self.assertEqual(RecoveryCode.objects.filter(user=self.user).count(), 10)
        self.assertNotIn(codes[0], RecoveryCode.objects.values_list("code_hash", flat=True))  # only hashes are kept
        # The password alone doesn't sign in any more.
        self.client.logout()
        self.assertRedirects(self.sign_in(next="/learn/"), reverse("landing:two_step"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(self.client.post(reverse("landing:two_step"), {"code": "12345"}, follow=True), "That code isn")
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post(reverse("landing:two_step"), {"code": next_code(device)})
        self.assertRedirects(response, "/learn/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.assertNotIn(PENDING, self.client.session)
        # A recovery code works once.
        self.client.logout()
        self.sign_in()
        self.client.post(reverse("landing:two_step"), {"method": "recovery", "code": codes[0].upper()})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        self.sign_in()
        self.assertContains(self.client.post(reverse("landing:two_step"), {"method": "recovery", "code": codes[0]}, follow=True), "That recovery code doesn")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_codes_and_slow_sign_ins_start_over(self):
        device, _ = turn_on(self.client, self.user)
        self.client.logout()
        self.sign_in()
        for _ in range(5):
            self.client.post(reverse("landing:two_step"), {"code": "000000"})
        self.assertRedirects(self.client.post(reverse("landing:two_step"), {"code": next_code(device)}), f'{reverse("landing:home")}#signin', fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        cache.clear()
        self.sign_in()
        session = self.client.session
        session[PENDING] = {**session[PENDING], "at": int(time.time()) - 600}
        session.save()
        self.assertRedirects(self.client.get(reverse("landing:two_step")), f'{reverse("landing:home")}#signin', fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("landing:two_step")), f'{reverse("landing:home")}#signin', fetch_redirect_response=False)  # nobody waiting

    def test_turning_it_off_takes_the_password_and_a_code(self):
        device, codes = turn_on(self.client, self.user)
        url = reverse("landing:security")
        self.assertContains(self.client.post(url, {"action": "disable", "password": "wrong", "code": next_code(device)}), "Your password isn")
        self.assertContains(self.client.post(url, {"action": "disable", "password": PASSWORD, "code": "000000"}), "That code isn")
        new_codes = re.findall(r"<code>([a-z0-9]{5}-[a-z0-9]{5})</code>", self.client.post(url, {"action": "codes", "password": PASSWORD}).content.decode())
        self.assertFalse(two_factor.use_recovery_code(self.user, codes[1]))  # replaced
        self.client.post(url, {"action": "disable", "password": PASSWORD, "code": new_codes[0]})
        self.assertFalse(TwoFactor.objects.filter(user=self.user).exists())
        self.assertFalse(RecoveryCode.objects.filter(user=self.user).exists())
        self.client.logout()
        self.sign_in()
        self.assertIn("_auth_user_id", self.client.session)


class CompanyTwoStepTests(RepositoryTestCase):
    """A company that requires two-step sign-in lets nobody reach its repositories without it."""
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.force_login(self.owner)
        self.client.post(reverse("companies:list"), {"name": "Acme Labs"})
        self.company = Company.objects.get()
        self.client.post(reverse("companies:repository_create", args=[self.company.slug]), {"title": "Billing API"})
        self.repo = self.company.repositories.get()
        self.member = make_user("mate@example.com", "Team", "Mate")
        CompanyMember.objects.create(company=self.company, user=self.member)
        self.settings = reverse("companies:settings", args=[self.company.slug])

    def role(self, user):
        return repository_role(user, Repository.objects.get(pk=self.repo.pk))  # with the company as it is now

    def require(self):
        return self.client.post(self.settings, {"action": "security", "repository_creation": "all", "members_change_visibility": "on", "members_invite_outside": "on", "require_two_factor": "on"}, follow=True)

    def test_members_need_two_step_sign_in_to_reach_the_code_and_to_join(self):
        self.assertContains(self.require(), "Turn on two-step sign-in for your own account first")
        self.assertFalse(Company.objects.get().require_two_factor)
        turn_on(self.client, self.owner)
        self.client.force_login(self.owner)
        self.require()
        self.assertTrue(Company.objects.get().require_two_factor)
        self.assertEqual(self.role(self.owner), "owner")
        self.assertIsNone(self.role(self.member))
        self.assertContains(self.client.get(f'{reverse("companies:detail", args=[self.company.slug])}?tab=people'), "No two-step sign-in", count=1)
        self.client.force_login(self.member)
        page = self.client.get(reverse("companies:detail", args=[self.company.slug]))
        self.assertContains(page, "requires two-step sign-in")
        self.assertNotContains(page, "acme-labs/billing-api")
        self.assertContains(self.client.get(reverse("landing:security")), "Acme Labs requires two-step sign-in")
        turn_on(self.client, self.member)
        self.assertEqual(self.role(self.member), "read")
        # Joining takes it too.
        newcomer = make_user("new@example.com", "New", "Comer")
        invitation = CompanyInvitation.objects.create(company=self.company, invited_by=self.owner, user=newcomer)
        self.client.force_login(newcomer)
        link = reverse("companies:invitation", args=[invitation.token])
        self.assertContains(self.client.get(link), "Acme Labs requires two-step sign-in")
        self.client.post(link, {"action": "accept"})
        self.assertFalse(CompanyMember.objects.filter(user=newcomer).exists())
        turn_on(self.client, newcomer)
        self.client.post(link, {"action": "accept"})
        self.assertTrue(CompanyMember.objects.filter(user=newcomer).exists())
