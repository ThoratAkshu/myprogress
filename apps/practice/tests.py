"""Developer mode: the question bank, choosing a language and level, the question at sign-in, quizzes, the Learn dock and progress."""
import contextlib
import io
from unittest import mock
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape
from apps.accounts.models import Profile
from . import bank, services
from .models import LANGUAGES, LEVELS, Attempt, PracticeProfile, Question

PASSWORD = "StrongPass!482"


def make_user(email, role="developer", practising=True, **practice):
    user = User.objects.create_user(username=email, email=email, password=PASSWORD, first_name="Asha", last_name="Rao")
    Profile.objects.create(user=user, role=role, occupation="student", institution="Pune University")
    if practising:
        services.enable(user, **practice)
    return user


class BankTests(TestCase):
    def test_every_question_is_well_formed(self):
        keys = [data["key"] for data in bank.QUESTIONS]
        self.assertEqual(len(keys), len(set(keys)))
        for data in bank.QUESTIONS:
            with self.subTest(data["key"]):
                self.assertIn(data["language"], dict(LANGUAGES))
                self.assertIn(data["level"], dict(LEVELS))
                self.assertIn(data["kind"], dict(Question.KINDS))
                self.assertGreaterEqual(len(data["choices"]), 3)
                self.assertEqual(len(set(data["choices"])), len(data["choices"]))
                self.assertLess(data["answer"], len(data["choices"]))
                self.assertTrue(data["explanation"])

    def test_python_output_questions_print_their_answer(self):
        checked = 0
        for data in bank.QUESTIONS:
            if data["language"] == "python" and data["kind"] == "output":
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    exec(data["code"], {})  # our own code, from bank.py
                self.assertEqual(out.getvalue().strip(), data["choices"][data["answer"]], data["key"])
                checked += 1
        self.assertGreater(checked, 25)

    def test_the_database_follows_the_bank(self):
        self.assertEqual(Question.objects.filter(is_active=True).count(), len(bank.QUESTIONS))  # loaded after migrate
        Question.objects.create(key="ai-made", language="python", level="beginner", kind="concept", topic="AI", prompt="?", choices=["a", "b", "c"], answer=0, explanation=".", source="ai")
        edited = [dict(data, prompt="Changed?") if data["key"] == "py-b-def" else data for data in bank.QUESTIONS if data["key"] != "py-b-slice"]
        with mock.patch.object(services, "QUESTIONS", edited):
            services.sync_questions()
        self.assertEqual(Question.objects.get(key="py-b-def").prompt, "Changed?")
        self.assertFalse(Question.objects.get(key="py-b-slice").is_active)  # removed from the bank: retired, answers kept
        self.assertTrue(Question.objects.get(key="ai-made").is_active)  # not the bank's to retire
        services.sync_questions()
        self.assertTrue(Question.objects.get(key="py-b-slice").is_active)


class SetupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_sign_up_follows_the_pages_developer_mode_toggle(self):
        form = self.client.get(reverse("landing:register_details", args=["developer"]))
        self.assertContains(form, '<input type="hidden" name="developer_mode" value="" data-dev-field>')  # filled in by the page's toggle
        self.assertNotContains(form, 'type="checkbox" name="developer_mode"')  # no separate switch in the form
        details = {"first_name": "Asha", "last_name": "Rao", "password": PASSWORD, "occupation": "student", "institution": "Pune University", "terms": "1"}
        response = self.client.post(reverse("landing:register_details", args=["developer"]), {**details, "email": "asha@example.com"})
        self.assertRedirects(response, reverse("landing:dashboard"), fetch_redirect_response=False)
        self.assertFalse(PracticeProfile.objects.filter(user__email="asha@example.com").exists())  # the toggle was off
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, 'role="switch" aria-checked="false" aria-labelledby="mode-toggle-menu"')
        self.assertNotContains(page, "mode-arriving")
        self.client.logout()
        self.client.post(reverse("landing:register_details", args=["developer"]), {**details, "email": "ravi@example.com", "developer_mode": "1"})
        practice = PracticeProfile.objects.get(user__email="ravi@example.com")
        self.assertEqual((practice.enabled, practice.languages, practice.level), (True, ["python"], "beginner"))
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, "mode-arriving mode-to-on")  # the dashboard turns into developer mode and shows what's new
        self.client.logout()
        self.client.post(reverse("landing:register_details", args=["recruiter"]), {"first_name": "Hana", "last_name": "Iyer", "email": "hana@acme.io", "password": PASSWORD,
                                                                                   "company_name": "Acme", "terms": "1", "developer_mode": "1"})
        self.assertFalse(PracticeProfile.objects.filter(user__email="hana@acme.io").exists())  # developer mode is for students and professionals

    def test_choosing_the_language_and_level_on_the_questions_tab(self):
        user = make_user("dev@example.com")
        self.client.force_login(user)
        page = self.client.get(reverse("practice:home"))
        self.assertContains(page, '<select name="language" aria-label="Language">')
        self.assertContains(page, '<option value="python" selected>Python (')
        self.assertContains(page, '<option value="beginner" selected>Beginner</option>')
        self.assertNotContains(page, "Languages and level")
        self.assertRedirects(self.client.post(reverse("practice:choose"), {"language": "javascript", "level": "intermediate"}), "/practice/#practice-choice", fetch_redirect_response=False)
        practice = PracticeProfile.objects.get(user=user)
        self.assertEqual((practice.languages, practice.level), (["javascript"], "intermediate"))
        self.client.post(reverse("practice:choose"), {"language": "cobol", "level": "guru"})  # not on the menus: nothing changes
        practice.refresh_from_db()
        self.assertEqual((practice.languages, practice.level), (["javascript"], "intermediate"))
        page = self.client.get(reverse("practice:home"))
        self.assertContains(page, '<option value="javascript" selected>JavaScript (')
        self.assertContains(page, "lang-row is-current")
        self.assertContains(self.client.get(reverse("landing:dashboard"), follow=True), "data-dock")  # the Learn dock on other pages
        self.assertRedirects(self.client.get(reverse("practice:setup")), "/practice/#practice-choice", fetch_redirect_response=False)  # the old page
        services.disable(user)
        response = self.client.get(reverse("practice:home"), follow=True)
        self.assertRedirects(response, reverse("landing:dashboard"))
        self.assertContains(response, "Developer mode is off. Turn it on with the toggle under Me.")
        self.assertRedirects(self.client.get(reverse("practice:setup")), reverse("landing:dashboard"), fetch_redirect_response=False)

    def test_only_students_and_professionals_have_it(self):
        recruiter = make_user("hr@acme.io", role="recruiter", practising=False)
        services.enable(recruiter)
        self.assertFalse(services.is_on(recruiter))
        self.client.force_login(recruiter)
        self.assertNotEqual(self.client.get(reverse("practice:setup")).status_code, 200)


class SignInQuestionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = make_user("dev@example.com")

    def sign_in(self, next_url=""):
        return self.client.post(reverse("landing:login"), {"email": "dev@example.com", "password": PASSWORD, "next": next_url})

    def test_a_question_must_be_answered_before_anything_else(self):
        self.assertRedirects(self.sign_in("/learn/"), reverse("practice:warmup"))
        page = self.client.get(reverse("practice:warmup"))
        self.assertContains(page, "One question, then you're in.")
        question = page.context["question"]
        for url in [reverse("landing:dashboard"), reverse("practice:home"), reverse("landing:workspace_section", args=["projects"])]:
            self.assertRedirects(self.client.get(url), reverse("practice:warmup"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("practice:next"), HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 200)  # background requests carry on
        self.assertContains(self.client.post(reverse("practice:warmup"), {}), "Pick an answer to continue")
        wrong = (question.answer + 1) % len(question.choices)
        page = self.client.post(reverse("practice:warmup"), {"choice": wrong})
        self.assertContains(page, "Good try. You're in.")
        self.assertContains(page, escape(question.explanation))
        self.assertContains(page, 'href="/learn/"')  # on to where they were going
        attempt = Attempt.objects.get(user=self.user)
        self.assertEqual((attempt.question, attempt.correct, attempt.context), (question, False, "signin"))
        self.assertEqual(self.client.get(reverse("landing:dashboard"), follow=True).status_code, 200)
        # The next sign-in brings a new question.
        self.client.logout()
        self.sign_in()
        self.assertNotEqual(self.client.get(reverse("practice:warmup")).context["question"], question)

    def test_signing_out_is_always_open_and_others_go_straight_in(self):
        self.sign_in()
        self.assertRedirects(self.client.post(reverse("landing:logout")), reverse("landing:home"), fetch_redirect_response=False)
        services.disable(self.user)
        self.assertRedirects(self.sign_in(), reverse("landing:dashboard"), fetch_redirect_response=False)


class EngineTests(TestCase):
    def setUp(self):
        self.user = make_user("dev@example.com", languages=["python"], level="beginner")

    def test_new_questions_first_then_other_levels_then_the_missed_ones(self):
        beginner = list(Question.objects.filter(language="python", level="beginner"))
        for question in beginner[:-1]:
            services.check(self.user, question, question.answer, "quiz")
        self.assertEqual(services.next_question(self.user), beginner[-1])  # the one left at their level
        services.check(self.user, beginner[-1], (beginner[-1].answer + 1) % 3, "quiz")
        self.assertEqual(services.next_question(self.user).level, "intermediate")  # then new ones at another level
        for question in Question.objects.filter(language="python").exclude(level="beginner"):
            services.check(self.user, question, question.answer, "quiz")
        self.assertEqual(services.next_question(self.user), beginner[-1])  # everything seen: the one they missed comes back
        self.assertNotEqual(services.next_question(self.user, exclude=[beginner[-1].pk]), beginner[-1])
        with self.assertRaises(ValueError):
            services.check(self.user, beginner[0], 9, "quiz")

    def test_progress_and_moving_up_a_level(self):
        questions = list(Question.objects.filter(language="python", level="beginner")[:10])
        for index, question in enumerate(questions):
            services.check(self.user, question, question.answer if index < 8 else (question.answer + 1) % 3, "dock")
        progress = services.progress(self.user)
        self.assertEqual((progress["answered"], progress["accuracy"], progress["streak"], progress["today"]), (10, 80, 1, 10))
        self.assertEqual(progress["languages"][0]["seen"], 10)
        self.assertEqual(services.level_up(self.user), "intermediate")
        self.client.force_login(self.user)
        page = self.client.get(reverse("practice:home"))
        self.assertContains(page, "Ready for Intermediate questions?")
        self.client.post(reverse("practice:level"), {"level": "intermediate"})
        self.assertEqual(PracticeProfile.objects.get(user=self.user).level, "intermediate")


class QuizAndDockTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = make_user("dev@example.com")
        self.client.force_login(self.user)

    def test_a_quiz_is_five_questions_with_a_score(self):
        self.client.get(f'{reverse("practice:quiz")}?new=1')
        right = 0
        for number in range(1, 6):
            page = self.client.get(reverse("practice:quiz"))
            self.assertContains(page, f"Question {number} of 5")
            question = page.context["question"]
            choice = question.answer if number % 2 else (question.answer + 1) % len(question.choices)
            right += choice == question.answer
            self.client.post(reverse("practice:quiz"), {"choice": choice})
            self.client.post(reverse("practice:quiz"), {"choice": question.answer})  # a second answer doesn't count
            self.assertContains(self.client.get(reverse("practice:quiz")), escape(question.explanation))  # reloading shows the result again
            self.client.get(f'{reverse("practice:quiz")}?step=next')
        self.assertContains(self.client.get(reverse("practice:quiz")), f"You got {right} of 5 right")
        self.assertEqual(Attempt.objects.filter(user=self.user, context="quiz").count(), 5)
        self.assertEqual(len({attempt.question_id for attempt in Attempt.objects.all()}), 5)  # five different questions

    def test_the_learn_dock_asks_and_explains(self):
        data = self.client.get(reverse("practice:next")).json()["question"]
        self.assertNotIn("answer", data)
        self.assertNotIn("explanation", data)
        question = Question.objects.get(pk=data["id"])
        result = self.client.post(reverse("practice:answer"), {"question": question.pk, "choice": question.answer}).json()
        self.assertEqual((result["correct"], result["answer"], result["explanation"], result["progress"]["answered"]), (True, question.answer, question.explanation, 1))
        self.assertEqual(self.client.post(reverse("practice:answer"), {"question": question.pk, "choice": 7}).status_code, 400)
        self.assertNotEqual(self.client.get(reverse("practice:next")).json()["question"]["id"], question.pk)  # answered ones wait their turn
        services.disable(self.user)
        self.assertEqual(self.client.get(reverse("practice:next")).status_code, 404)
