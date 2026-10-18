"""The developer view: MyProgress as a code editor, its generated dark theme, and switching it on and off."""
import json
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
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

    def test_developer_mode_shows_the_editor_and_it_can_be_switched_off(self):
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "dev-mode ide")
        self.assertContains(page, "ide-auto.css")
        self.assertContains(page, '<span class="nav-file" aria-hidden="true">home.py</span>')
        self.assertContains(page, "Python, JavaScript · Beginner")  # the status bar
        self.assertContains(page, "Switch to the normal view")
        self.assertContains(page, 'role="switch" aria-checked="true" aria-label="Developer view"')
        self.assertNotContains(page, "view-arriving")
        commands = json.loads(page.content.decode().split('<script id="ide-commands" type="application/json">')[1].split("</script>")[0])
        labels = [command["label"] for command in commands]
        self.assertIn("New project", labels)
        self.assertIn("Watch: Binary search (Python)", labels)
        self.assertEqual(commands[-1]["label"], "Sign out")
        response = self.client.post(reverse("practice:ui"), {"ide": "0", "next": "/practice/"})
        self.assertRedirects(response, "/practice/", fetch_redirect_response=False)
        page = self.client.get(reverse("landing:dashboard"))
        self.assertNotContains(page, "ide-auto.css")
        self.assertNotContains(page, "dev-mode ide")
        self.assertNotContains(page, "nav-file")  # the normal view's tabs are plain: Home, not home.py
        self.assertNotContains(page, "ide-status")
        self.assertContains(page, "Switch to the developer view")
        self.assertContains(page, 'role="switch" aria-checked="false" aria-label="Developer view"')
        self.assertRedirects(self.client.post(reverse("practice:ui"), {"ide": "1", "next": "https://evil.example/"}), reverse("landing:dashboard"), fetch_redirect_response=False)
        self.assertTrue(services.profile(self.user.__class__.objects.get(pk=self.user.pk)).ide_ui)

    def test_the_page_after_a_switch_turns_in_once(self):
        self.client.post(reverse("practice:ui"), {"ide": "0", "next": "/dashboard/"})
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "view-arriving view-to-off")
        self.assertContains(page, "Normal view is on.")
        self.assertNotContains(page, "data-view-intro")
        page = self.client.get(reverse("landing:dashboard"))
        self.assertNotContains(page, "view-arriving")  # only the first page after switching
        self.assertNotContains(page, "Normal view is on.")
        self.client.post(reverse("practice:ui"), {"ide": "0", "next": "/dashboard/"})  # already off: nothing to show
        self.assertNotContains(self.client.get(reverse("landing:dashboard")), "view-arriving")
        self.client.post(reverse("practice:ui"), {"ide": "1", "next": "/practice/problems/"})
        page = self.client.get(reverse("practice:problems"))
        self.assertContains(page, "view-arriving view-to-on")
        self.assertContains(page, "You're in the developer view")
        self.assertContains(page, '<form method="dialog"')
        self.assertContains(page, "view-switch.js")
        self.assertNotContains(self.client.get(reverse("practice:problems")), "data-view-intro")

    def test_without_developer_mode_there_is_no_editor(self):
        services.disable(self.user)
        page = self.client.get(reverse("landing:dashboard"))
        self.assertNotContains(page, "ide-auto.css")
        self.assertNotContains(page, "ide-status")
        self.assertNotContains(page, "ide-switch")
        self.assertNotContains(page, "view-switch.js")
        self.assertContains(page, "Turn on developer mode")
