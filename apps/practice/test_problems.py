"""Problems: every reference solution passes its tests through the real runner, the list filters and counts, and
submissions are kept only when they add up."""
import datetime
import re
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from . import problems
from .models import Submission
from .test_lab import run
from .tests import make_user

LIMIT = 1000000  # problem.js runs and submits with this step limit


def jobs(item, language="python"):
    fn = item["languages"][language]["fn"]
    return [{"fn": fn, "args": test["args"], "expected": test["expected"], "compare": item["compare"]} for test in item["tests"]]


class ContentTests(TestCase):
    def test_the_set_is_numbered_and_complete(self):
        self.assertEqual([item["number"] for item in problems.PROBLEMS], list(range(1, len(problems.PROBLEMS) + 1)))
        self.assertEqual(len(problems.BY_SLUG), len(problems.PROBLEMS))
        counts = {key: sum(1 for item in problems.PROBLEMS if item["difficulty"] == key) for key in problems.LABELS}
        self.assertEqual(counts, {"easy": 13, "medium": 14, "hard": 6})
        for item in problems.PROBLEMS:
            with self.subTest(item["slug"]):
                self.assertRegex(item["slug"], r"^[a-z0-9-]+$")
                self.assertTrue(item["statement"] and item["editorial"] and item["constraints"] and item["hints"] and item["complexity"])
                self.assertIn(item["compare"], ["exact", "sorted", "nested", "float"])
                self.assertGreaterEqual(len(item["tests"]), item["examples"] + 2)  # hidden tests beyond the examples
                self.assertTrue(set(item["topics"]) <= set(problems.TOPICS))
                for test in item["tests"]:
                    self.assertEqual(len(test["args"]), len(item["params"]))
                python, javascript = item["languages"]["python"], item["languages"]["javascript"]
                self.assertIn(f"def {python['fn']}(", python["solution"])
                self.assertIn(f"function {javascript['fn']}(", javascript["solution"])
                self.assertNotIn("_", javascript["fn"])

    def test_every_python_solution_passes_and_every_starter_fails(self):
        for item in problems.PROBLEMS:
            with self.subTest(item["slug"]):
                solved = run(item["languages"]["python"]["solution"], limit=LIMIT, tests=jobs(item))
                self.assertIsNone(solved["error"])
                self.assertEqual([test["passed"] for test in solved["tests"]], [True] * len(item["tests"]), solved["tests"])
                started = run(item["languages"]["python"]["starter"], limit=LIMIT, tests=jobs(item))
                self.assertIn(False, [test["passed"] for test in started["tests"]])

    def test_statements_show_code_safely_and_the_daily_problem_rotates(self):
        self.assertEqual(problems.inline_code("Use `a<b` & <b>"), "Use <code>a&lt;b</code> &amp; &lt;b&gt;")
        month = [problems.of_the_day(datetime.date(2026, 1, 1) + datetime.timedelta(days=offset))["slug"] for offset in range(len(problems.PROBLEMS))]
        self.assertEqual(len(set(month)), len(problems.PROBLEMS))  # every problem once before any repeats


class PageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = make_user("dev@example.com", languages=["javascript", "python"])
        self.client.force_login(self.user)

    def submit(self, slug="two-sum", **fields):
        data = {"language": "python", "code": "def two_sum(nums, target):\n    return [0, 1]\n", "status": "accepted", "passed": "6", "total": "6", "runtime_ms": "0.42"}
        data.update(fields)
        return self.client.post(reverse("practice:submit", args=[slug]), data)

    def test_the_list_filters_and_shows_what_you_solved(self):
        page = self.client.get(reverse("practice:problems"))
        self.assertEqual(len(page.context["rows"]), len(problems.PROBLEMS))
        self.assertContains(page, "Problem of the day")
        self.assertContains(page, 'href="/practice/problems/two-sum/"')
        self.assertEqual([row["slug"] for row in self.client.get(reverse("practice:problems"), {"q": "anagram"}).context["rows"]], ["valid-anagram", "group-anagrams"])
        self.assertEqual([row["slug"] for row in self.client.get(reverse("practice:problems"), {"q": "#9"}).context["rows"]], ["binary-search"])
        hard = self.client.get(reverse("practice:problems"), {"difficulty": "hard"}).context["rows"]
        self.assertEqual({row["difficulty"] for row in hard}, {"hard"})
        self.assertTrue(all("Stack" in row["topics"] for row in self.client.get(reverse("practice:problems"), {"topic": "Stack"}).context["rows"]))
        self.assertEqual(len(self.client.get(reverse("practice:problems"), {"difficulty": "silly", "topic": "Nope"}).context["rows"]), len(problems.PROBLEMS))
        self.submit()
        self.submit("valid-parentheses", status="wrong", passed="3", total=str(len(problems.BY_SLUG["valid-parentheses"]["tests"])), code="def is_valid(s):\n    return True\n")
        page = self.client.get(reverse("practice:problems"))
        self.assertEqual(page.context["solved_count"], 1)
        self.assertEqual(page.context["by_difficulty"][0], {"key": "easy", "label": "Easy", "solved": 1, "total": 13, "percent": 8})
        states = {row["slug"]: row["state"] for row in page.context["rows"]}
        self.assertEqual((states["two-sum"], states["valid-parentheses"], states["valid-palindrome"]), ("solved", "attempted", "todo"))
        self.assertEqual([row["slug"] for row in self.client.get(reverse("practice:problems"), {"status": "solved"}).context["rows"]], ["two-sum"])
        self.assertContains(self.client.get(reverse("practice:problems"), {"q": "zzz"}), "No problems match those filters.")

    def test_acceptance_shows_only_once_there_are_enough_submissions(self):
        for status, passed in [("accepted", 6), ("wrong", 2), ("wrong", 5), ("error", 0)]:
            self.submit(status=status, passed=str(passed))
        row = next(row for row in self.client.get(reverse("practice:problems")).context["rows"] if row["slug"] == "two-sum")
        self.assertIsNone(row["acceptance"])
        self.assertContains(self.client.get(reverse("practice:problem", args=["two-sum"])), "(4 so far)")
        other = make_user("other@example.com")
        self.client.force_login(other)
        self.submit()
        row = next(row for row in self.client.get(reverse("practice:problems")).context["rows"] if row["slug"] == "two-sum")
        self.assertEqual(row["acceptance"], 40.0)
        page = self.client.get(reverse("practice:problem", args=["two-sum"]))
        self.assertEqual(page.context["stats"], {"total": 5, "accepted": 2, "rate": 40.0})
        self.assertEqual(len(page.context["data"]["submissions"]), 1)  # only your own

    def test_a_problem_page_has_the_examples_but_not_the_hidden_tests(self):
        item = problems.BY_SLUG["two-sum"]
        page = self.client.get(reverse("practice:problem", args=["two-sum"]))
        data = page.context["data"]
        self.assertEqual(data["language"], "javascript")  # the first language you practise
        self.assertEqual(data["cases"], [{"args": test["args"], "expected": test["expected"]} for test in item["tests"][:3]])
        self.assertEqual(data["languages"]["javascript"]["starter"], "function twoSum(nums, target) {\n  \n}\n")
        self.assertContains(page, "<b>Input:</b> nums = [2,7,11,15], target = 9")
        self.assertContains(page, "<code>target</code>")
        self.assertContains(page, "problem.js")
        self.assertEqual(self.client.get(reverse("practice:problem", args=["two-sum"]), {"language": "python"}).context["data"]["language"], "python")
        tests = self.client.get(reverse("practice:problem_tests", args=["two-sum"])).json()
        self.assertEqual(len(tests["tests"]), len(item["tests"]))
        self.assertEqual(self.client.get(reverse("practice:problem", args=["nope"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("practice:problem_tests", args=["nope"])).status_code, 404)

    def test_submissions_are_kept_when_they_add_up(self):
        first = self.submit().json()
        self.assertTrue(first["firstSolve"])
        self.assertEqual((first["submission"]["label"], first["submission"]["passed"], first["submission"]["ms"], first["solved"]), ("Accepted", 6, 0.4, 1))
        self.assertFalse(self.submit().json()["firstSolve"])
        self.assertEqual(self.submit(status="compile", passed="0").json()["submission"]["label"], "Compile Error")
        for bad in [{"total": "5"}, {"passed": "5"}, {"status": "wrong"}, {"status": "great"}, {"language": "java"}, {"code": "  "},
                    {"passed": "x"}, {"passed": "7", "total": "6"}, {"runtime_ms": "-1"}, {"code": "x" * 20001}]:
            with self.subTest(bad):
                self.assertEqual(self.submit(**bad).status_code, 400)
        self.assertEqual(Submission.objects.filter(user=self.user).count(), 3)
        self.assertEqual(self.submit("nope").status_code, 404)
        page = self.client.get(reverse("practice:problem", args=["two-sum"]))
        self.assertTrue(page.context["solved"])
        self.assertEqual([row["status"] for row in page.context["data"]["submissions"]], ["compile", "accepted", "accepted"])

    def test_only_developers_in_developer_mode_get_problems(self):
        recruiter = make_user("hr@acme.io", role="recruiter", practising=False)
        self.client.force_login(recruiter)
        self.assertNotEqual(self.client.get(reverse("practice:problems")).status_code, 200)
        self.assertNotEqual(self.submit().status_code, 200)
        dormant = make_user("later@example.com", practising=False)
        self.client.force_login(dormant)
        self.assertRedirects(self.client.get(reverse("practice:problems")), reverse("practice:setup"))
        self.assertRedirects(self.client.get(reverse("practice:problem", args=["two-sum"])), reverse("practice:setup"))
        self.assertEqual(self.submit().status_code, 404)
        self.assertFalse(Submission.objects.exists())

    def test_the_palette_and_tabs_lead_to_problems(self):
        page = self.client.get(reverse("practice:home"))
        self.assertContains(page, 'href="/practice/problems/"')
        labels = [item["label"] for item in page.context["nav_ide_commands"]()]
        self.assertIn("1. Two Sum", labels)
        self.assertTrue(re.search(r'href="/practice/problems/"[^>]*>.*?<span class="nav-label">Practice</span>', page.content.decode(), re.S))
