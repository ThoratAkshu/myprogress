"""The code lab: its content is right, the Python runner traces and tests code, and solves are recorded."""
import importlib.util
import json
from pathlib import Path
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from . import lab, services
from .models import ChallengeSolve
from .tests import make_user

spec = importlib.util.spec_from_file_location("python_runner", Path(settings.BASE_DIR) / "apps/landing/static/landing/js/python_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)  # the same file the browser runs under Pyodide


def run(code, **options):
    if "tests" in options:
        options["tests"] = json.dumps(options["tests"])
    return json.loads(runner.run(code, **options))


class ContentTests(TestCase):
    def test_every_python_solution_passes_and_every_starter_fails(self):
        python = [item for item in lab.CHALLENGES if item["language"] == "python"]
        self.assertEqual(len(python), 6)
        for item in python:
            with self.subTest(item["key"]):
                solved = run(item["solution"], tests=item["tests"])
                self.assertIsNone(solved["error"])
                self.assertTrue(all(test["passed"] for test in solved["tests"]), solved["tests"])
                self.assertFalse(all(test["passed"] for test in run(item["starter"], tests=item["tests"])["tests"]))

    def test_python_walkthroughs_run_cleanly_in_a_few_steps(self):
        for item in lab.WALKTHROUGHS:
            if item["language"] == "python":
                with self.subTest(item["key"]):
                    result = run(item["code"], trace=True, limit=1500)
                    self.assertIsNone(result["error"])
                    self.assertTrue(result["output"])
                    self.assertLess(len(result["steps"]), 200)
                    self.assertTrue(result["steps"][-1]["done"])

    def test_every_item_is_complete_and_both_languages_match(self):
        for item in lab.CHALLENGES + lab.WALKTHROUGHS:
            self.assertIn(item["language"], lab.RUNNABLE)
            self.assertTrue(item["prompt"] and item["title"])
        for language in lab.RUNNABLE:
            self.assertEqual(len([item for item in lab.CHALLENGES if item["language"] == language]), 6)
            self.assertEqual(len([item for item in lab.WALKTHROUGHS if item["language"] == language]), 6)


class RunnerTests(TestCase):
    def test_a_dry_run_records_lines_variables_stack_and_output(self):
        result = run(lab.WALKTHROUGH_BY_KEY["py-factorial"]["code"], trace=True, limit=1500)
        steps = result["steps"]
        self.assertEqual(steps[0]["line"], 1)
        self.assertEqual(max(len(step["stack"]) for step in steps), 5)  # main and four calls deep
        deepest = next(step for step in steps if len(step["stack"]) == 5)
        self.assertEqual((deepest["stack"][-1], deepest["vars"]), ("factorial", {"n": "1"}))
        self.assertEqual((result["output"], steps[-1]["out"]), ("24\n", "24\n"))
        self.assertEqual(steps[-1]["vars"]["factorial"], "function factorial")

    def test_errors_loops_and_input_are_reported_kindly(self):
        self.assertEqual(run("x = 1\ny = x / 0\n")["error"], {"line": 2, "message": "ZeroDivisionError: division by zero"})
        self.assertEqual(run("def f(:\n    pass\n")["error"]["line"], 1)
        self.assertIn("Stopped after 500 steps", run("while True:\n    pass\n", limit=500)["error"]["message"])
        self.assertIn("input() can't ask you anything here", run("name = input()\n")["error"]["message"])
        tests = run("def double(n):\n    return n * 3\n", tests=[{"call": "double(2)", "expected": "4"}, {"call": "double('x')", "expected": "'xx'"}])["tests"]
        self.assertEqual([(test["got"], test["passed"]) for test in tests], [("6", False), ("'xxx'", False)])


class LabPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = make_user("dev@example.com", languages=["javascript", "java"])
        self.client.force_login(self.user)

    def test_the_lab_lists_challenges_and_walkthroughs_in_your_language(self):
        page = self.client.get(reverse("practice:lab"))
        self.assertContains(page, "Reverse the words")
        self.assertContains(page, 'href="/practice/code/js-sum-evens/"')
        self.assertContains(page, 'href="/practice/watch/js-factorial/"')
        self.assertContains(page, "Java can't run in the browser here yet")
        self.assertContains(self.client.get(reverse("practice:lab"), {"language": "python"}), 'href="/practice/code/py-sum-evens/"')
        self.assertEqual(self.client.get(reverse("practice:challenge", args=["nope"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("practice:challenge", args=["py-swap"])).status_code, 404)  # a walkthrough, not a challenge

    def test_a_challenge_is_solved_with_or_without_help(self):
        page = self.client.get(reverse("practice:challenge", args=["py-two-sum"]))
        self.assertContains(page, "Two numbers that add up")
        data = page.context["data"]
        self.assertEqual((data["starter"], data["tests"][0]["call"]), (lab.CHALLENGE_BY_KEY["py-two-sum"]["starter"], "two_sum([2, 7, 11, 15], 9)"))
        self.assertNotIn("solution", data)  # only on request
        self.assertNotContains(page, "seen[target - n]")
        solved = reverse("practice:solved", args=["py-two-sum"])
        self.client.post(solved, {"code": "def two_sum(nums, target): ..."})
        self.assertFalse(ChallengeSolve.objects.get(user=self.user, key="py-two-sum").helped)
        self.assertEqual(self.client.get(reverse("practice:solution", args=["py-sum-evens"])).json()["solution"], lab.CHALLENGE_BY_KEY["py-sum-evens"]["solution"])
        response = self.client.post(reverse("practice:solved", args=["py-sum-evens"]), {"code": "x"}).json()
        self.assertEqual((response["solved"], response["helped"]), (2, True))
        self.assertContains(self.client.get(reverse("practice:lab"), {"language": "python"}), "solved with help")
        self.client.post(reverse("practice:solved", args=["py-sum-evens"]), {"code": "y"})
        self.assertTrue(ChallengeSolve.objects.get(key="py-sum-evens").helped)  # still after help in this session
        session = self.client.session
        session["practice_lab_helped"] = []
        session.save()
        self.client.post(reverse("practice:solved", args=["py-sum-evens"]), {"code": "z"})
        solve = ChallengeSolve.objects.get(key="py-sum-evens")
        self.assertEqual((solve.helped, solve.code), (False, "z"))  # solved again on their own
        self.assertEqual(self.client.post(reverse("practice:solved", args=["py-swap"]), {"code": "x"}).status_code, 404)

    def test_every_challenge_and_walkthrough_page_opens(self):
        for item in lab.CHALLENGES:
            self.assertContains(self.client.get(reverse("practice:challenge", args=[item["key"]])), item["title"])
        for item in lab.WALKTHROUGHS:
            self.assertContains(self.client.get(reverse("practice:walkthrough", args=[item["key"]])), item["title"])
        self.assertEqual(self.client.get(reverse("practice:challenge", args=["py-binary-search"])).context["mode"], "challenge")  # shares its key with a walkthrough
        self.assertEqual(self.client.get(reverse("practice:walkthrough", args=["py-binary-search"])).context["mode"], "walkthrough")

    def test_walkthroughs_and_who_can_use_the_lab(self):
        page = self.client.get(reverse("practice:walkthrough", args=["py-bubble-sort"]))
        self.assertEqual(page.context["data"]["code"], lab.WALKTHROUGH_BY_KEY["py-bubble-sort"]["code"])
        self.assertContains(page, "python-worker.js")
        self.assertContains(self.client.get(reverse("practice:walkthrough", args=["js-bubble-sort"])), "acorn@8.12.1")
        services.disable(self.user)
        self.assertRedirects(self.client.get(reverse("practice:lab")), reverse("practice:setup"))
        self.assertEqual(self.client.get(reverse("practice:solution", args=["py-sum-evens"])).status_code, 404)
