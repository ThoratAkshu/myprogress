"""The home page's developer mode for visitors: real numbers and content, and signing in with it on."""
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from apps.accounts.test_two_factor import next_code, turn_on
from apps.practice import lab, problems, services
from apps.practice.models import PracticeProfile, Question
from apps.practice.tests import PASSWORD, make_user


class HomeDeveloperModeTests(TestCase):
    def test_the_developer_page_is_built_from_the_real_content(self):
        page = self.client.get(reverse("landing:home"))
        self.assertContains(page, 'role="switch" aria-checked="false" data-dev-switch')
        self.assertContains(page, 'data-for-mode="dev"')
        self.assertContains(page, "Wake me up")  # Matri, asleep in the normal hero
        dev = page.context["dev"]
        self.assertEqual(dev["problems"], len(problems.PROBLEMS))
        self.assertEqual(dev["questions"], Question.objects.filter(is_active=True).count())
        self.assertEqual(dev["walkthroughs"], len(lab.WALKTHROUGHS))
        self.assertEqual(sum(row["count"] for row in dev["difficulties"]), len(problems.PROBLEMS))
        self.assertEqual(dev["more"], len(problems.PROBLEMS) - len(dev["samples"]))
        self.assertContains(page, f'<b data-count="{len(problems.PROBLEMS)}">{len(problems.PROBLEMS)}</b><span>Problems with hidden tests')
        for item in dev["samples"]:
            self.assertContains(page, item["title"])  # sample problems are real ones
        self.assertContains(page, dev["question"]["explanation"].replace("'", "&#x27;"))
        self.assertContains(page, "sum_evens.js")
        self.assertContains(page, '"acorn": "https://cdn.jsdelivr.net/npm/acorn@8.12.1/dist/acorn.js"')
        self.assertContains(page, f'{reverse("landing:register_details", args=["recruiter"])}"')  # Pick your path
        self.assertContains(page, f"try it {services.SWITCH_LIMIT} times in 15 minutes, and turn it off any time")
        self.assertNotContains(page, "Two Sum II")
        for name in ["home.py", "dry_run.js", "problems/", "questions.py", "editor.json", "faq.md"]:
            self.assertContains(page, f"</i>{name}</a>")  # developer mode's header: file tabs

    def test_the_sign_up_pages_follow_developer_mode_without_a_toggle(self):
        for url in [reverse("landing:register"), reverse("landing:register_details", args=["developer"]), reverse("landing:register_details", args=["organization"])]:
            page = self.client.get(url)
            self.assertNotContains(page, "data-dev-switch")  # chosen on the home page; sign-up only follows it
            self.assertContains(page, 'class="auth-story-body dev-story" data-for-mode="dev"')
            self.assertContains(page, f"{len(problems.PROBLEMS)} interview-style problems")
            self.assertContains(page, "landing-dev.js")
        self.assertContains(self.client.get(reverse("landing:register")), "Starts in developer mode")
        self.assertContains(self.client.get(reverse("landing:register_details", args=["developer"])), "You'll start in developer mode:")
        self.assertContains(self.client.get(reverse("landing:register_details", args=["organization"])), "Developer mode is for student and professional accounts.")


class SignInWithDeveloperModeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def sign_in(self, email, developer_mode="1"):
        return self.client.post(reverse("landing:login"), {"email": email, "password": PASSWORD, "developer_mode": developer_mode})

    def test_signing_in_with_the_toggle_on_opens_developer_mode(self):
        make_user("dev@example.com", practising=False)
        self.assertRedirects(self.sign_in("dev@example.com"), reverse("landing:dashboard"), fetch_redirect_response=False)  # no sign-in question this time
        self.assertTrue(PracticeProfile.objects.get(user__email="dev@example.com").enabled)
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "mode-arriving mode-to-on")
        self.assertContains(page, "in developer mode")
        self.client.logout()
        self.assertRedirects(self.sign_in("dev@example.com"), reverse("practice:warmup"), fetch_redirect_response=False)  # already on: the usual question

    def test_the_toggle_off_or_a_recruiter_changes_nothing(self):
        make_user("off@example.com", practising=False)
        self.sign_in("off@example.com", developer_mode="")
        self.assertFalse(PracticeProfile.objects.filter(user__email="off@example.com", enabled=True).exists())
        self.client.logout()
        make_user("hr@acme.io", role="recruiter", practising=False)
        self.assertRedirects(self.sign_in("hr@acme.io"), reverse("landing:dashboard"), fetch_redirect_response=False)
        self.assertFalse(PracticeProfile.objects.filter(user__email="hr@acme.io", enabled=True).exists())
        self.client.logout()
        self.sign_in("nobody@example.com")  # a wrong password leaves nothing behind for the next sign-in
        self.assertNotIn(services.WANTS_ON, self.client.session)

    def test_it_waits_for_the_second_step(self):
        user = make_user("safe@example.com", practising=False)
        device, _ = turn_on(self.client, user)
        self.client.logout()
        self.assertRedirects(self.sign_in("safe@example.com"), reverse("landing:two_step"))
        self.assertFalse(PracticeProfile.objects.filter(user=user, enabled=True).exists())
        self.client.post(reverse("landing:two_step"), {"code": next_code(device)})
        self.assertTrue(PracticeProfile.objects.get(user=user).enabled)
