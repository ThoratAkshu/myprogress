"""The code lab: its walkthroughs run, the Python runner traces code and checks problem tests, and the pages open."""
import importlib.util
import json
from pathlib import Path
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from . import lab, services
from .tests import make_user

spec = importlib.util.spec_from_file_location("python_runner", Path(settings.BASE_DIR) / "apps/landing/static/landing/js/python_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)  # the same file the browser runs under Pyodide


def run(code, **options):
    if "tests" in options:
        options["tests"] = json.dumps(options["tests"])
    return json.loads(runner.run(code, **options))


class ContentTests(TestCase):
    def test_python_walkthroughs_run_cleanly_in_a_few_steps(self):
        for item in lab.WALKTHROUGHS:
            if item["language"] == "python":
                with self.subTest(item["key"]):
                    result = run(item["code"], trace=True, limit=1500)
                    self.assertIsNone(result["error"])
                    self.assertTrue(result["output"])
                    self.assertLess(len(result["steps"]), 200)
                    self.assertTrue(result["steps"][-1]["done"])

    def test_every_walkthrough_is_complete_in_both_languages(self):
        for item in lab.WALKTHROUGHS:
            self.assertIn(item["language"], lab.RUNNABLE)
            self.assertTrue(item["prompt"] and item["title"])
        for language in lab.RUNNABLE:
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

    def test_problem_tests_compare_answers_as_json(self):
        code = "def pair(a, b):\n    print('checking', a)\n    return (a, b)\n\ndef half(n):\n    return n / 2\n\ndef flag(n):\n    return 1 if n else 0\n"
        tests = run(code, tests=[
            {"fn": "pair", "args": [0, 1], "expected": [0, 1]},  # a tuple is a JSON list
            {"fn": "pair", "args": [1, 0], "expected": [0, 1], "compare": "sorted"},
            {"fn": "pair", "args": [1, 0], "expected": [0, 1]},
            {"fn": "half", "args": [1], "expected": 0.5000001, "compare": "float"},
            {"fn": "flag", "args": [1], "expected": True},  # 1 isn't true
            {"fn": "half", "args": ["x"], "expected": 1},
            {"fn": "missing", "args": [], "expected": 1},
            {"fn": "half", "args": [3]},  # your own case: no answer to check
        ])["tests"]
        self.assertEqual([test["passed"] for test in tests], [True, True, False, True, False, False, False, None])
        self.assertEqual((tests[0]["got"], tests[0]["stdout"]), ("[0, 1]", "checking 0\n"))
        self.assertIn("TypeError", tests[5]["error"])
        self.assertEqual(tests[5]["line"], 6)
        self.assertEqual(tests[6]["error"], "NameError: There's no function called missing. Keep the name the starter code gave it.")
        self.assertEqual(tests[7]["got"], "1.5")
        nested = run("def groups():\n    return [['b', 'a'], ['c']]\n", tests=[{"fn": "groups", "args": [], "expected": [["c"], ["a", "b"]], "compare": "nested"}])
        self.assertTrue(nested["tests"][0]["passed"])
        args = run("def grow(items):\n    items.append(1)\n    return len(items)\n", tests=[{"fn": "grow", "args": [[]], "expected": 1}] * 2)
        self.assertEqual([test["passed"] for test in args["tests"]], [True, True])  # each test gets fresh arguments


class LabPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = make_user("dev@example.com", languages=["javascript", "java"])
        self.client.force_login(self.user)

    def test_the_lab_lists_walkthroughs_in_your_language(self):
        page = self.client.get(reverse("practice:lab"))
        self.assertContains(page, 'href="/practice/watch/js-factorial/"')
        self.assertContains(page, "Java can't run in the browser here yet")
        self.assertContains(page, reverse("practice:problems"))
        self.assertContains(self.client.get(reverse("practice:lab"), {"language": "python"}), 'href="/practice/watch/py-factorial/"')
        self.assertEqual(self.client.get(reverse("practice:walkthrough", args=["nope"])).status_code, 404)

    def test_old_challenge_links_go_to_the_problem_they_became(self):
        self.assertRedirects(self.client.get("/practice/code/js-two-sum/"), "/practice/problems/two-sum/?language=javascript", status_code=301)
        self.assertRedirects(self.client.get("/practice/code/py-sum-evens/"), "/practice/problems/sum-of-even-numbers/?language=python", status_code=301)
        self.assertRedirects(self.client.get("/practice/code/py-char-counts/"), "/practice/problems/", status_code=301)

    def test_every_walkthrough_page_opens(self):
        for item in lab.WALKTHROUGHS:
            self.assertContains(self.client.get(reverse("practice:walkthrough", args=[item["key"]])), item["title"])

    def test_walkthroughs_and_who_can_use_the_lab(self):
        page = self.client.get(reverse("practice:walkthrough", args=["py-bubble-sort"]))
        self.assertEqual(page.context["data"]["code"], lab.WALKTHROUGH_BY_KEY["py-bubble-sort"]["code"])
        self.assertContains(page, "python-worker.js")
        self.assertContains(page, "lab-core.js")
        self.assertContains(self.client.get(reverse("practice:walkthrough", args=["js-bubble-sort"])), "acorn@8.12.1")
        services.disable(self.user)
        self.assertRedirects(self.client.get(reverse("practice:lab")), reverse("practice:setup"))
        self.assertRedirects(self.client.get(reverse("practice:walkthrough", args=["py-bubble-sort"])), reverse("practice:setup"))
