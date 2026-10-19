"""The developer view: MyProgress as a code editor, its generated dark theme, and switching it on and off."""
import json
from datetime import timedelta
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from . import ide_theme, services
from .tests import make_user


class ThemeTests(TestCase):
    def test_the_generated_theme_matches_the_stylesheets(self):
        self.assertEqual(ide_theme.OUTPUT.read_text(encoding="utf8"), ide_theme.build(), "Run `manage.py build_ide_css` after changing a stylesheet.")

    def test_light_colours_turn_dark_and_the_rest_keep_their_order(self):
        css = "".join(ide_theme.rules(ide_theme.parse(""".card{background:#fff;color:#1f2328;border:1px solid #e2e8f0}
            .badge{background:#dcfce7;color:#166534}.pale{background:linear-gradient(180deg,#fde68a,#fef3c7)}
            .button.primary{background:var(--violet);color:#fff}.pill.active{background:var(--ink);color:#fff}
            .dark{background:#0f172a;color:#fff}@media (max-width:600px){.card{background:#f8fafc}}body.app .x{color:#475569}""")))
        for expected in ["body.ide .card{background:var(--ide-panel);color:var(--ide-ink);border:1px solid var(--ide-line)}",
                         "body.ide .badge{background:hsla(141,70%,60%,.13);color:hsl(143,74%,72%)}",
                         "body.ide .pale{background:hsla(48,70%,60%,.16)}",
                         "body.ide .button.primary{background:var(--ide-accent-strong);color:#fff}",  # white text on the light accent: deeper blue
                         "body.ide .pill.active{background:var(--ide-accent-strong);color:#fff}",
                         "body.ide .dark{background:#0f172a;color:#fff}",  # copied as it is, so it keeps its place in the cascade
                         "@media (max-width:600px){body.ide .card{background:var(--ide-panel)}",
                         "body.ide.app .x{color:var(--ide-muted)}"]:
            self.assertIn(expected, css)


class SwitchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = make_user("dev@example.com", languages=["python", "javascript"])
        self.client.force_login(self.user)

    def fresh(self):
        return services.profile(type(self.user).objects.get(pk=self.user.pk))

    def switch(self, on, next_url="/dashboard/", **extra):
        return self.client.post(reverse("practice:mode"), {"on": "1" if on else "0", "next": next_url}, **extra)

    def test_developer_mode_is_the_editor_and_its_toggle_is_under_me(self):
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "dev-mode ide")
        self.assertContains(page, "ide-auto.css")
        self.assertContains(page, '<span class="nav-file" aria-hidden="true">home.py</span>')
        self.assertContains(page, "Python, JavaScript · Beginner")  # the status bar
        menu = page.content.decode().split('<details class="app-menu">')[1].split("</details>")[0]
        self.assertIn('role="switch" aria-checked="true" aria-labelledby="mode-toggle-menu"', menu)  # under Me, the profile menu
        self.assertIn('<b id="mode-toggle-menu">Developer mode</b>', menu)
        self.assertIn("Off any time · 3 of 3 tries left", menu)
        self.assertEqual(page.content.decode().count('role="switch"'), 1)  # the only switch: not in the header, the card or the palette
        self.assertNotContains(page, "Developer view")
        self.assertNotContains(page, "mode-arriving")
        commands = json.loads(page.content.decode().split('<script id="ide-commands" type="application/json">')[1].split("</script>")[0])
        labels = [command["label"] for command in commands]
        self.assertIn("New project", labels)
        self.assertIn("Watch: Binary search (Python)", labels)
        self.assertNotIn("Languages and level", labels)
        self.assertEqual(commands[-1]["label"], "Sign out")
        self.assertRedirects(self.switch(False, "/practice/"), "/practice/", fetch_redirect_response=False)
        self.assertFalse(services.is_on(type(self.user).objects.get(pk=self.user.pk)))
        page = self.client.get(reverse("landing:dashboard"))
        for gone in ["ide-auto.css", "dev-mode", "nav-file", "ide-status", "data-dock", 'href="/practice/problems/"']:
            self.assertNotContains(page, gone)  # the normal MyProgress: no editor look, no Practice tab
        self.assertContains(page, 'role="switch" aria-checked="false" aria-labelledby="mode-toggle-menu"')
        self.assertContains(page, "3 tries every 15 min")  # turning it off didn't use a try
        self.assertContains(page, "Find the toggle under Me")
        self.assertRedirects(self.client.get(reverse("practice:problems")), reverse("landing:dashboard"))  # practice waits for the toggle
        self.assertRedirects(self.switch(True, "https://evil.example/"), reverse("landing:dashboard"), fetch_redirect_response=False)
        practice = self.fresh()
        self.assertEqual((practice.enabled, practice.languages), (True, ["python", "javascript"]))  # back as they left it

    def test_the_page_after_a_switch_turns_in_once(self):
        self.switch(False)
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "mode-arriving mode-to-off")
        self.assertContains(page, "Developer mode is off. Your answers are kept")
        self.assertNotContains(page, "data-mode-intro")
        page = self.client.get(reverse("landing:dashboard"))
        self.assertNotContains(page, "mode-arriving")  # only the first page after switching
        self.switch(False)  # already off: nothing to show
        self.assertNotContains(self.client.get(reverse("landing:dashboard")), "mode-arriving")
        self.switch(True, "/practice/problems/")
        page = self.client.get(reverse("practice:problems"))
        self.assertContains(page, "mode-arriving mode-to-on")
        self.assertContains(page, "in developer mode")
        self.assertContains(page, '<form method="dialog"')
        self.assertContains(page, "mode-switch.js")
        self.assertNotContains(self.client.get(reverse("practice:problems")), "data-mode-intro")

    def test_three_tries_in_fifteen_minutes_and_turning_off_is_free(self):
        for on in [False, True, False, True, False, True]:  # three round trips: only turning it on uses a try
            self.assertRedirects(self.switch(on), "/dashboard/", fetch_redirect_response=False)
        self.assertTrue(self.fresh().enabled)
        self.assertEqual(len(self.fresh().switches), 3)
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "Off any time · on again in 15 min")
        self.assertNotContains(page, 'aria-describedby="mode-toggle-menu-note" disabled')  # it can still go off
        self.switch(False)
        self.assertFalse(self.fresh().enabled)  # never stuck in developer mode
        self.client.get(reverse("landing:dashboard"))  # the page that shows the switch
        response = self.switch(True, follow=True)
        self.assertContains(response, "You can try developer mode 3 times in 15 minutes. Try again in 15 min.")
        self.assertFalse(self.fresh().enabled)  # a fourth try waits
        self.assertNotContains(response, "mode-arriving")
        self.assertContains(response, "Try again in 15 min")
        self.assertContains(response, 'aria-describedby="mode-toggle-menu-note" disabled')
        practice = self.fresh()
        practice.switches = [(timezone.now() - timedelta(minutes=minutes)).isoformat() for minutes in (16, 10, 2)]
        practice.save()
        user = type(self.user).objects.get(pk=self.user.pk)
        self.assertEqual(services.switch_allowance(user)["left"], 1)  # the oldest try is past the window
        self.switch(True)
        user = type(self.user).objects.get(pk=self.user.pk)
        self.assertTrue(services.is_on(user))
        self.assertEqual(services.switch_allowance(user), {"left": 0, "limit": 3, "window": 15, "minutes": 5})  # the try 10 minutes ago frees up first
        self.assertEqual(services.switch_mode(user, True), "unchanged")  # asking for what's already on isn't a try

    def test_on_phones_the_toggle_is_on_your_own_profile(self):
        handle = self.user.profile.handle
        page = self.client.get(reverse("landing:public_profile", args=[handle]))
        self.assertContains(page, 'id="developer-mode"')
        self.assertContains(page, 'aria-labelledby="mode-toggle-profile"')
        other = make_user("other@example.com")
        self.assertNotContains(self.client.get(reverse("landing:public_profile", args=[other.profile.handle])), 'id="developer-mode"')

    def test_someone_who_never_used_it_can_turn_it_on_and_others_cannot(self):
        newcomer = make_user("new@example.com", practising=False)
        self.client.force_login(newcomer)
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, 'role="switch" aria-checked="false"')
        self.assertNotContains(page, "ide-auto.css")
        self.switch(True)
        practice = services.profile(type(newcomer).objects.get(pk=newcomer.pk))
        self.assertEqual((practice.enabled, practice.languages, practice.level), (True, ["python"], "beginner"))
        recruiter = make_user("hr@acme.io", role="recruiter", practising=False)
        self.client.force_login(recruiter)
        self.assertNotContains(self.client.get(reverse("landing:dashboard"), follow=True), "mode-toggle")
        self.assertNotEqual(self.switch(True).status_code, 302)  # not theirs to switch (access policy)
        self.assertFalse(services.is_on(recruiter))
