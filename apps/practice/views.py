"""Developer mode: setting it up, the question at sign-in, the Practice tab, quizzes, problems, the code lab, and the Learn dock's API."""
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from apps.common.ratelimit import rate_limit
from . import lab, problems, services
from .models import LANGUAGES, LEVELS, Attempt, Question, Submission

QUIZ = "practice_quiz"


def _chosen(request):
    value = request.POST.get("choice", "")
    return int(value) if value.isdigit() else None


def _off(request):
    """A practice page with developer mode off: back home, with where the switch is."""
    if services.can_practise(request.user):
        messages.info(request, "Developer mode is off. Turn it on with the toggle under Me.")
    return redirect("landing:dashboard")


@login_required(login_url="landing:home")
def setup_view(request):
    """The old Languages and level page: the language and level are chosen on the Questions tab now."""
    return redirect(f'{reverse("practice:home")}#practice-choice' if services.is_on(request.user) else "landing:dashboard")


@login_required(login_url="landing:home")
@require_POST
def choose_view(request):
    """Pick the language and level questions come in, from the menus on the Questions tab (like LeetCode's)."""
    if not services.is_on(request.user):
        return _off(request)
    services.choose(request.user, request.POST.get("language"), request.POST.get("level"))
    return redirect(f'{reverse("practice:home")}#practice-choice')


@login_required(login_url="landing:home")
@never_cache
def home_view(request):
    """The Practice tab: progress, a quick quiz, and what you answered lately."""
    if not services.is_on(request.user):
        return _off(request)
    practice = services.profile(request.user)
    recent = Attempt.objects.filter(user=request.user).select_related("question")[:6]
    counts = {row["language"]: row["total"] for row in Question.objects.filter(is_active=True).values("language").annotate(total=Count("id"))}
    return render(request, "practice/home.html", {"section": "practice", "practice": practice, "progress": services.progress(request.user),
                                                  "level_up": services.level_up(request.user), "levels": dict(LEVELS), "recent": recent,
                                                  "language": (practice.languages or services.DEFAULT_LANGUAGES)[0],
                                                  "language_choices": [(key, name, counts.get(key, 0)) for key, name in LANGUAGES], "level_choices": LEVELS})


@login_required(login_url="landing:home")
@require_POST
def level_view(request):
    """Move to another level, from the Practice tab's suggestion."""
    practice = services.profile(request.user)
    if practice and request.POST.get("level") in dict(LEVELS):
        practice.level = request.POST["level"]
        practice.save(update_fields=["level"])
        messages.success(request, f"You're on {practice.get_level_display()} questions now.")
    return redirect("practice:home")


@login_required(login_url="landing:home")
@never_cache
def warmup_view(request):
    """The question at sign-in. It must be answered, right or wrong, before anything else opens."""
    pending = request.session.get(services.WARMUP)
    if not pending:
        return redirect("landing:dashboard")
    question = Question.objects.filter(pk=pending["question"], is_active=True).first() or services.next_question(request.user)
    if question is None:
        request.session.pop(services.WARMUP, None)
        return redirect(pending["next"])
    attempt = None
    if request.method == "POST" and _chosen(request) is not None:
        try:
            attempt = services.check(request.user, question, _chosen(request), "signin")
        except ValueError:
            messages.error(request, "Pick one of the answers.")
        else:
            request.session.pop(services.WARMUP, None)
    elif request.method == "POST":
        messages.error(request, "Pick an answer to continue. Right or wrong, you'll get in.")
    return render(request, "practice/warmup.html", {"section": "practice-warmup", "question": question, "attempt": attempt, "next_url": pending["next"],
                                                    "practice": services.profile(request.user)})


@login_required(login_url="landing:home")
@never_cache
def quiz_view(request):
    """Five questions in a row, one at a time, with the explanation after each."""
    if not services.is_on(request.user):
        return _off(request)
    state = request.session.get(QUIZ)
    if request.GET.get("new") == "1" or not state:
        ids = []
        for _ in range(services.QUIZ_LENGTH):
            question = services.next_question(request.user, exclude=ids)
            if question is None:
                break
            ids.append(question.pk)
        request.session[QUIZ] = {"ids": ids, "index": 0, "right": 0, "chosen": None}
        return redirect("practice:quiz")
    if request.GET.get("step") == "next" and state["chosen"] is not None:
        state.update(index=state["index"] + 1, chosen=None)
        request.session[QUIZ] = state
        return redirect("practice:quiz")
    total = len(state["ids"])
    if state["index"] >= total:
        return render(request, "practice/quiz.html", {"section": "practice", "finished": True, "right": state["right"], "total": total})
    question = get_object_or_404(Question, pk=state["ids"][state["index"]])
    attempt = None
    if request.method == "POST" and state["chosen"] is None and _chosen(request) is not None:
        try:
            attempt = services.check(request.user, question, _chosen(request), "quiz")
        except ValueError:
            messages.error(request, "Pick one of the answers.")
        else:
            state.update(chosen=attempt.chosen, right=state["right"] + attempt.correct)
            request.session[QUIZ] = state
    elif state["chosen"] is not None:  # reloaded after answering: show the same result again
        attempt = Attempt(question=question, chosen=state["chosen"], correct=state["chosen"] == question.answer)
    return render(request, "practice/quiz.html", {"section": "practice", "question": question, "attempt": attempt, "number": state["index"] + 1, "total": total,
                                                  "percent": round(100 * (state["index"] + (1 if attempt else 0)) / total), "last": state["index"] + 1 == total})


@login_required(login_url="landing:home")
@never_cache
def next_api(request):
    """The Learn dock's next question."""
    if not services.is_on(request.user):
        raise Http404
    skip = [int(value) for value in request.GET.getlist("skip") if value.isdigit()][:20]
    question = services.next_question(request.user, exclude=skip)
    return JsonResponse({"question": services.payload(question) if question else None, "practice_url": reverse("practice:home")})


@login_required(login_url="landing:home")
@require_POST
@rate_limit("practice-answer", 120, 600)
def answer_api(request):
    """Check the Learn dock's answer and explain it."""
    if not services.is_on(request.user):
        raise Http404
    question = get_object_or_404(Question, pk=request.POST.get("question", "0") if request.POST.get("question", "").isdigit() else 0, is_active=True)
    chosen = _chosen(request)
    try:
        attempt = services.check(request.user, question, chosen if chosen is not None else -1, "dock")
    except ValueError:
        return JsonResponse({"error": "Pick one of the answers."}, status=400)
    progress = services.progress(request.user)
    return JsonResponse({"correct": attempt.correct, "answer": question.answer, "explanation": question.explanation,
                         "progress": {"answered": progress["answered"], "accuracy": progress["accuracy"], "streak": progress["streak"]}})


# The code lab: walkthroughs to watch, run in the browser (see lab.py).
def _lab_language(request):
    practice = services.profile(request.user)
    mine = [key for key in ((practice.languages if practice else None) or []) if key in lab.RUNNABLE] or ["python"]
    chosen = request.GET.get("language")
    return (chosen if chosen in lab.RUNNABLE else mine[0]), mine, practice


def _runner_urls():
    return {"workerUrl": static("landing/js/python-worker.js"), "runnerUrl": static("landing/js/python_runner.py")}


@login_required(login_url="landing:home")
@never_cache
def lab_view(request):
    """Walkthroughs to watch, in a runnable language."""
    if not services.is_on(request.user):
        return _off(request)
    chosen, mine, practice = _lab_language(request)
    walkthroughs = [dict(item, preview="\n".join(item["code"].splitlines()[:5])) for item in lab.WALKTHROUGHS if item["language"] == chosen]
    return render(request, "practice/lab.html", {
        "section": "practice", "practice": practice, "chosen": chosen, "walkthroughs": walkthroughs,
        "languages": [(key, label, key in mine) for key, label in lab.RUNNABLE.items()],
        "not_runnable": [dict(LANGUAGES)[key] for key in ((practice.languages if practice else None) or []) if key not in lab.RUNNABLE],
    })


@login_required(login_url="landing:home")
@never_cache
def walkthrough_view(request, key):
    item = lab.WALKTHROUGH_BY_KEY.get(key)
    if not services.is_on(request.user):
        return _off(request)
    if not item:
        raise Http404
    same = [other for other in lab.WALKTHROUGHS if other["language"] == item["language"]]
    position = same.index(item)
    data = {"language": item["language"], "code": item["code"], **_runner_urls()}
    return render(request, "practice/workspace.html", {"section": "practice", "item": item, "data": data, "language_label": lab.RUNNABLE[item["language"]],
                                                       "next_item": same[position + 1] if position + 1 < len(same) else None})


@login_required(login_url="landing:home")
def old_challenge_view(request, key):
    """The code lab's challenges became problems: old links go to the problem each one turned into."""
    language = "javascript" if key.startswith("js-") else "python"
    slug = lab.OLD_CHALLENGES.get(key[3:] if key[:3] in ("py-", "js-") else key)
    if not slug:
        return redirect("practice:problems", permanent=True)
    return redirect(f'{reverse("practice:problem", args=[slug])}?language={language}', permanent=True)


# Problems, like LeetCode's (see problems.py). The person's browser runs the tests; the server keeps what it reports.
ACCEPTANCE_FROM = 5  # acceptance rates show once a problem has this many submissions, so a rate means something
STATES = [("todo", "To do"), ("attempted", "Attempted"), ("solved", "Solved")]


def _acceptance(row):
    if not row or row["total"] < ACCEPTANCE_FROM:
        return None
    return round(100 * row["accepted"] / row["total"], 1)


def _submission_row(submission):
    return {"id": submission.pk, "status": submission.status, "label": submission.get_status_display(), "passed": submission.passed,
            "total": submission.total, "ms": round(submission.runtime_ms, 1), "language": submission.language,
            "languageLabel": lab.RUNNABLE.get(submission.language, submission.language), "code": submission.code,
            "when": date_format(timezone.localtime(submission.created_at), "j M Y, H:i")}


def _as_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@login_required(login_url="landing:home")
@never_cache
def problems_view(request):
    """The problem set: filters, the problem of the day, what you've solved by difficulty, and acceptance rates."""
    if not services.is_on(request.user):
        return _off(request)
    mine = Submission.objects.filter(user=request.user)
    solved = set(mine.filter(status="accepted").values_list("slug", flat=True))
    tried = set(mine.values_list("slug", flat=True))
    counts = {row["slug"]: row for row in Submission.objects.values("slug").annotate(total=Count("pk"), accepted=Count("pk", filter=Q(status="accepted")))}
    query = request.GET.get("q", "").strip()[:80]
    difficulty = request.GET.get("difficulty", "")
    topic = request.GET.get("topic", "")
    state = request.GET.get("status", "")
    rows = []
    for item in problems.PROBLEMS:
        mark = "solved" if item["slug"] in solved else "attempted" if item["slug"] in tried else "todo"
        if query and query.lower() not in item["title"].lower() and query.lstrip("#") != str(item["number"]):
            continue
        if difficulty in problems.LABELS and item["difficulty"] != difficulty:
            continue
        if topic in problems.TOPICS and topic not in item["topics"]:
            continue
        if state in dict(STATES) and mark != state:
            continue
        rows.append(dict(item, state=mark, acceptance=_acceptance(counts.get(item["slug"]))))
    by_difficulty = []
    for key, label in problems.DIFFICULTIES:
        slugs = [item["slug"] for item in problems.PROBLEMS if item["difficulty"] == key]
        done = sum(1 for slug in slugs if slug in solved)
        by_difficulty.append({"key": key, "label": label, "solved": done, "total": len(slugs), "percent": round(100 * done / len(slugs)) if slugs else 0})
    today = problems.of_the_day(timezone.localdate())
    return render(request, "practice/problems.html", {
        "section": "practice", "rows": rows, "total": len(problems.PROBLEMS), "solved_count": len(solved), "by_difficulty": by_difficulty,
        "today": dict(today, state="solved" if today["slug"] in solved else "attempted" if today["slug"] in tried else "todo"),
        "query": query, "difficulty": difficulty, "topic": topic, "state": state, "filtered": bool(query or difficulty or topic or state),
        "difficulties": problems.DIFFICULTIES, "topics": problems.TOPICS, "states": STATES, "acceptance_from": ACCEPTANCE_FROM,
    })


@login_required(login_url="landing:home")
@never_cache
def problem_view(request, slug):
    """A problem: its description, editorial and your submissions, beside an editor that runs the tests in the browser."""
    item = problems.BY_SLUG.get(slug)
    if not services.is_on(request.user):
        return _off(request)
    if not item:
        raise Http404
    chosen, mine, practice = _lab_language(request)
    submissions = list(Submission.objects.filter(user=request.user, slug=slug)[:30])
    counts = Submission.objects.filter(slug=slug).aggregate(total=Count("pk"), accepted=Count("pk", filter=Q(status="accepted")))
    position = problems.PROBLEMS.index(item)
    examples = [{"inputs": [(name, _as_json(value)) for name, value in zip(item["params"], test["args"])], "output": _as_json(test["expected"]), "why": test["why"]}
                for test in item["tests"][:item["examples"]]]
    data = {
        "slug": slug, "language": chosen, "params": item["params"], "compare": item["compare"],
        "languages": {key: {"label": lab.RUNNABLE[key], "fn": value["fn"], "starter": value["starter"], "solution": value["solution"]} for key, value in item["languages"].items()},
        "cases": [{"args": test["args"], "expected": test["expected"]} for test in item["tests"][:item["examples"]]],
        "submissions": [_submission_row(submission) for submission in submissions],
        "testsUrl": reverse("practice:problem_tests", args=[slug]), "submitUrl": reverse("practice:submit", args=[slug]), **_runner_urls(),
    }
    return render(request, "practice/problem.html", {
        "section": "practice", "item": item, "data": data, "examples": examples, "chosen": chosen,
        "statement": [problems.inline_code(part) for part in item["statement"].split("\n\n")],
        "editorial": [problems.inline_code(part) for part in item["editorial"].split("\n\n")],
        "hints": [problems.inline_code(hint) for hint in item["hints"]],
        "solved": Submission.objects.filter(user=request.user, slug=slug, status="accepted").exists(),
        "stats": dict(counts, rate=_acceptance(counts)), "acceptance_from": ACCEPTANCE_FROM,
        "previous": problems.PROBLEMS[position - 1] if position else None, "total": len(problems.PROBLEMS),
        "next": problems.PROBLEMS[position + 1] if position + 1 < len(problems.PROBLEMS) else None,
        "languages": list(lab.RUNNABLE.items()),
    })


@login_required(login_url="landing:home")
@never_cache
def problem_tests_api(request, slug):
    """Every test, hidden ones too, for Submit to run in the browser."""
    item = problems.BY_SLUG.get(slug)
    if not services.is_on(request.user) or not item:
        raise Http404
    return JsonResponse({"compare": item["compare"], "tests": [{"args": test["args"], "expected": test["expected"]} for test in item["tests"]]})


@login_required(login_url="landing:home")
@require_POST
@rate_limit("practice-submit", 60, 600)
def submit_api(request, slug):
    """Keep a submission: the code, and how it did against every test in the person's browser."""
    item = problems.BY_SLUG.get(slug)
    if not services.is_on(request.user) or not item:
        raise Http404
    language = request.POST.get("language", "")
    status = request.POST.get("status", "")
    code = request.POST.get("code", "")
    try:
        passed, total = int(request.POST.get("passed", "")), int(request.POST.get("total", ""))
        runtime = float(request.POST.get("runtime_ms", "0"))
    except ValueError:
        return JsonResponse({"error": "That submission didn't come through properly. Submit again."}, status=400)
    if (language not in item["languages"] or status not in dict(Submission.STATUSES) or not code.strip() or len(code) > 20000
            or total != len(item["tests"]) or not 0 <= passed <= total or (status == "accepted") != (passed == total) or not 0 <= runtime < 600000):
        return JsonResponse({"error": "That submission didn't come through properly. Submit again."}, status=400)
    first = status == "accepted" and not Submission.objects.filter(user=request.user, slug=slug, status="accepted").exists()
    submission = Submission.objects.create(user=request.user, slug=slug, language=language, code=code, status=status, passed=passed, total=total, runtime_ms=runtime)
    return JsonResponse({"submission": _submission_row(submission), "firstSolve": first,
                         "solved": Submission.objects.filter(user=request.user, status="accepted").values("slug").distinct().count()})


@login_required(login_url="landing:home")
@require_POST
def mode_view(request):
    """The toggle under Me: developer mode on or off, at most SWITCH_LIMIT times in SWITCH_WINDOW. The next page plays
    the second half of the flip, and after switching on, shows what's new."""
    if services.can_practise(request.user):
        wanted = request.POST.get("on") == "1"
        outcome = services.switch_mode(request.user, wanted)
        if outcome == "switched":
            request.session[services.SWITCHED] = "on" if wanted else "off"
        elif outcome == "limited":
            allowance = services.switch_allowance(request.user)
            messages.error(request, f"You can switch developer mode {allowance['limit']} times in {allowance['window']} minutes. Try again in {allowance['minutes']} min.")
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse("landing:dashboard")
    return redirect(target)
