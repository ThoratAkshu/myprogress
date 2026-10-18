"""Developer mode: setting it up, the question at sign-in, the Practice tab, quizzes, and the Learn dock's API."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from apps.common.ratelimit import rate_limit
from . import lab, services
from .models import LANGUAGES, LEVELS, Attempt, ChallengeSolve, Question

QUIZ = "practice_quiz"


def _chosen(request):
    value = request.POST.get("choice", "")
    return int(value) if value.isdigit() else None


@login_required(login_url="landing:home")
def setup_view(request):
    """Turn developer mode on (or off) and choose languages and level. Also the welcome after signing up with it."""
    practice = services.profile(request.user)
    if request.method == "POST":
        if request.POST.get("action") == "off":
            services.disable(request.user)
            messages.success(request, "Developer mode is off. Your answers are kept if you turn it on again.")
            return redirect("practice:setup")
        languages = [key for key in request.POST.getlist("languages") if key in dict(LANGUAGES)]
        if not languages:
            messages.error(request, "Pick at least one language to practise.")
        else:
            was_on = services.is_on(request.user)
            services.enable(request.user, languages, request.POST.get("level"))
            messages.success(request, "Saved. Your questions follow your new choices." if was_on else "Developer mode is on. Here's your first quiz; next time you sign in, a question will be waiting.")
            return redirect("practice:home" if was_on else "practice:quiz")
    chosen = (practice.languages if practice else None) or services.DEFAULT_LANGUAGES
    counts = {row["language"]: row["total"] for row in Question.objects.filter(is_active=True).values("language").annotate(total=Count("id"))}
    return render(request, "practice/setup.html", {
        "section": "practice", "practice": practice, "is_on": services.is_on(request.user), "welcome": request.GET.get("welcome") == "1",
        "languages": [{"key": key, "name": name, "note": services.LANGUAGE_NOTES[key], "count": counts.get(key, 0), "checked": key in chosen} for key, name in LANGUAGES],
        "levels": [{"key": key, "name": name, "note": services.LEVEL_NOTES[key], "checked": key == (practice.level if practice else "beginner")} for key, name in LEVELS],
    })


@login_required(login_url="landing:home")
@never_cache
def home_view(request):
    """The Practice tab: progress, a quick quiz, and what you answered lately."""
    if not services.is_on(request.user):
        return redirect("practice:setup")
    practice = services.profile(request.user)
    recent = Attempt.objects.filter(user=request.user).select_related("question")[:6]
    return render(request, "practice/home.html", {"section": "practice", "practice": practice, "progress": services.progress(request.user),
                                                  "level_up": services.level_up(request.user), "levels": dict(LEVELS), "recent": recent})


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
        return redirect("practice:setup")
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


# The code lab: challenges with tests and walkthroughs, run in the browser (see lab.py).
HELPED = "practice_lab_helped"  # session: challenges whose worked solution was shown


def _lab_language(request):
    practice = services.profile(request.user)
    mine = [key for key in ((practice.languages if practice else None) or []) if key in lab.RUNNABLE] or ["python"]
    chosen = request.GET.get("language")
    return (chosen if chosen in lab.RUNNABLE else mine[0]), mine, practice


@login_required(login_url="landing:home")
@never_cache
def lab_view(request):
    """Challenges to solve and walkthroughs to watch, in a runnable language."""
    if not services.is_on(request.user):
        return redirect("practice:setup")
    chosen, mine, practice = _lab_language(request)
    solved = {solve.key: solve for solve in ChallengeSolve.objects.filter(user=request.user)}
    levels = []
    for level, label in LEVELS:
        items = [dict(item, solved=solved.get(item["key"])) for item in lab.CHALLENGES if item["language"] == chosen and item["level"] == level]
        if items:
            levels.append((level, label, items))
    walkthroughs = [dict(item, preview="\n".join(item["code"].splitlines()[:5])) for item in lab.WALKTHROUGHS if item["language"] == chosen]
    total = sum(len(items) for _, _, items in levels)
    return render(request, "practice/lab.html", {
        "section": "practice", "practice": practice, "chosen": chosen, "levels": levels, "walkthroughs": walkthroughs, "total": total,
        "solved_count": sum(1 for _, _, items in levels for item in items if item["solved"]),
        "languages": [(key, label, key in mine) for key, label in lab.RUNNABLE.items()],
        "not_runnable": [dict(LANGUAGES)[key] for key in ((practice.languages if practice else None) or []) if key not in lab.RUNNABLE],
    })


def _workspace(request, item, mode):
    same = [other for other in (lab.CHALLENGES if mode == "challenge" else lab.WALKTHROUGHS) if other["language"] == item["language"]]
    position = same.index(item)
    data = {"mode": mode, "key": item["key"], "language": item["language"], "title": item["title"],
            "workerUrl": static("landing/js/python-worker.js"), "runnerUrl": static("landing/js/python_runner.py")}
    solve = None
    if mode == "challenge":
        solve = ChallengeSolve.objects.filter(user=request.user, key=item["key"]).first()
        data.update(starter=item["starter"], tests=item["tests"], solvedUrl=reverse("practice:solved", args=[item["key"]]), solutionUrl=reverse("practice:solution", args=[item["key"]]))
    else:
        data.update(code=item["code"])
    return render(request, "practice/workspace.html", {"section": "practice", "item": item, "mode": mode, "data": data, "solved": solve,
                                                       "language_label": lab.RUNNABLE[item["language"]], "next_item": same[position + 1] if position + 1 < len(same) else None})


@login_required(login_url="landing:home")
@never_cache
def challenge_view(request, key):
    item = lab.CHALLENGE_BY_KEY.get(key)
    if not services.is_on(request.user):
        return redirect("practice:setup")
    if not item:
        raise Http404
    return _workspace(request, item, "challenge")


@login_required(login_url="landing:home")
@never_cache
def walkthrough_view(request, key):
    item = lab.WALKTHROUGH_BY_KEY.get(key)
    if not services.is_on(request.user):
        return redirect("practice:setup")
    if not item:
        raise Http404
    return _workspace(request, item, "walkthrough")


@login_required(login_url="landing:home")
@never_cache
def solution_api(request, key):
    """The worked solution for "Show me how". Solving afterwards counts as solved with help."""
    item = lab.CHALLENGE_BY_KEY.get(key)
    if not services.is_on(request.user) or not item:
        raise Http404
    helped = set(request.session.get(HELPED, []))
    helped.add(key)
    request.session[HELPED] = sorted(helped)
    return JsonResponse({"solution": item["solution"]})


@login_required(login_url="landing:home")
@require_POST
@rate_limit("practice-solved", 60, 600)
def solved_api(request, key):
    """Every test passed in the browser: keep the code that passed."""
    item = lab.CHALLENGE_BY_KEY.get(key)
    if not services.is_on(request.user) or not item:
        raise Http404
    helped = key in request.session.get(HELPED, [])
    code = request.POST.get("code", "")[:20000]
    solve, created = ChallengeSolve.objects.get_or_create(user=request.user, key=key, defaults={"language": item["language"], "code": code, "helped": helped})
    if not created:
        solve.code = code
        solve.helped = solve.helped and helped  # solving it again on your own counts
        solve.save(update_fields=["code", "helped"])
    return JsonResponse({"solved": ChallengeSolve.objects.filter(user=request.user).count(), "helped": solve.helped})


@login_required(login_url="landing:home")
@require_POST
def ui_view(request):
    """Switch between the developer UI (a code editor look) and the classic one."""
    practice = services.profile(request.user)
    if practice and services.is_on(request.user):
        practice.ide_ui = request.POST.get("ide") == "1"
        practice.save(update_fields=["ide_ui"])
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse("landing:dashboard")
    return redirect(target)
