"""Developer mode's engine: who has it on, which question comes next (new ones first, then the ones you missed),
answers, and progress."""
from datetime import timedelta
from django.db import connection
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone
from .bank import QUESTIONS
from .models import LANGUAGES, LEVELS, Attempt, PracticeProfile, Question

DEFAULT_LANGUAGES = ["python"]
QUIZ_LENGTH = 5
LEVEL_UP_WINDOW, LEVEL_UP_RIGHT = 10, 8  # 8 of your last 10 at a level right: time to move up
WARMUP = "practice_warmup"  # session key: the sign-in question still waiting for an answer
BANK_FIELDS = ["language", "level", "kind", "topic", "prompt", "code", "choices", "answer", "explanation"]
LANGUAGE_NOTES = {"python": "Readable and everywhere: scripts, data, AI and the web.", "javascript": "The language of the browser, and of servers with Node.",
                  "java": "Strongly typed and object-oriented: Android, banks and big backends.", "cpp": "Close to the machine: games, systems and competitive programming."}
LEVEL_NOTES = {"beginner": "Syntax, types, loops and functions.", "intermediate": "Collections, scope, errors and the standard library.",
               "advanced": "Closures, concurrency, memory and the language's corners."}


def sync_questions(**kwargs):
    """Make the database's bank match bank.py: add new questions, update edited ones, retire removed ones."""
    if Question._meta.db_table not in connection.introspection.table_names():
        return  # practice isn't migrated yet
    existing = {question.key: question for question in Question.objects.all()}
    for data in QUESTIONS:
        question = existing.get(data["key"])
        if question is None:
            Question.objects.create(key=data["key"], **{field: data[field] for field in BANK_FIELDS})
        elif not question.is_active or any(getattr(question, field) != data[field] for field in BANK_FIELDS):
            for field in BANK_FIELDS:
                setattr(question, field, data[field])
            question.is_active = True
            question.save()
    Question.objects.filter(source="bank", is_active=True).exclude(key__in=[data["key"] for data in QUESTIONS]).update(is_active=False)


def profile(user):
    if not user.is_authenticated:
        return None
    if not hasattr(user, "_practice_profile"):
        user._practice_profile = PracticeProfile.objects.filter(user=user).first()
    return user._practice_profile


def is_on(user):
    """Developer mode is for students and professionals who turned it on."""
    from apps.accounts.access import user_role
    practice = profile(user)
    return bool(practice and practice.enabled) and user_role(user) == "developer"


def enable(user, languages=None, level=None):
    languages = [key for key in dict.fromkeys(languages or []) if key in dict(LANGUAGES)] or DEFAULT_LANGUAGES
    level = level if level in dict(LEVELS) else "beginner"
    practice, _ = PracticeProfile.objects.update_or_create(user=user, defaults={"enabled": True, "languages": languages, "level": level})
    user._practice_profile = practice
    return practice


def disable(user):
    PracticeProfile.objects.filter(user=user).update(enabled=False)
    if hasattr(user, "_practice_profile"):
        del user._practice_profile


def next_question(user, exclude=()):
    """A question they haven't seen at their level; then one they haven't seen at the nearest other level (the next
    one up first); once they've seen them all, the ones they got wrong come back first, then the longest ago."""
    practice = profile(user)
    languages = (practice.languages if practice else None) or DEFAULT_LANGUAGES
    level = practice.level if practice else "beginner"
    mine = Question.objects.filter(is_active=True, language__in=languages).exclude(pk__in=list(exclude))
    seen = Attempt.objects.filter(user=user).values("question")
    order = [key for key, _ in LEVELS]
    position = order.index(level)
    for candidate in [level, *order[position + 1:], *reversed(order[:position])]:
        question = mine.filter(level=candidate).exclude(pk__in=seen).order_by("?").first()
        if question:
            return question
    latest = Attempt.objects.filter(user=user, question=OuterRef("pk")).order_by("-created_at", "-pk")
    again = mine.annotate(last_right=Subquery(latest.values("correct")[:1]), last_seen=Subquery(latest.values("created_at")[:1]))
    return again.order_by("last_right", "last_seen", "pk").filter(level=level).first() or again.order_by("last_right", "last_seen", "pk").first()


def check(user, question, chosen, context):
    """Record an answer. Raises ValueError for a choice that isn't one of the question's."""
    chosen = int(chosen)
    if not 0 <= chosen < len(question.choices):
        raise ValueError("That isn't one of the choices.")
    return Attempt.objects.create(user=user, question=question, chosen=chosen, correct=chosen == question.answer, context=context)


def start_warmup(request, user, next_url):
    """At sign-in: pick the question they must answer before going on. False if developer mode is off or the bank is empty."""
    if not is_on(user):
        return False
    question = next_question(user)
    if question is None:
        return False
    request.session[WARMUP] = {"question": question.pk, "next": next_url}
    return True


def streak(days):
    """Days in a row with at least one answer, up to today (or yesterday, if they haven't practised yet today)."""
    today = timezone.localdate()
    cursor = today if today in days else today - timedelta(days=1)
    count = 0
    while cursor in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


def progress(user):
    attempts = Attempt.objects.filter(user=user)
    totals = attempts.aggregate(answered=Count("id"), right=Count("id", filter=Q(correct=True)))
    since = timezone.now() - timedelta(days=400)
    days = {timezone.localdate(moment) for moment in attempts.filter(created_at__gte=since).values_list("created_at", flat=True)}
    practice = profile(user)
    languages = (practice.languages if practice else None) or DEFAULT_LANGUAGES
    names = dict(LANGUAGES)
    rows = []
    for key in languages:
        available = Question.objects.filter(is_active=True, language=key).count()
        done = attempts.filter(question__language=key).values("question").distinct().count()
        mine = attempts.filter(question__language=key).aggregate(answered=Count("id"), right=Count("id", filter=Q(correct=True)))
        rows.append({"key": key, "name": names.get(key, key), "seen": done, "available": available, "percent": round(100 * done / available) if available else 0,
                     "accuracy": round(100 * mine["right"] / mine["answered"]) if mine["answered"] else None})
    return {"answered": totals["answered"], "right": totals["right"], "accuracy": round(100 * totals["right"] / totals["answered"]) if totals["answered"] else None,
            "streak": streak(days), "today": attempts.filter(created_at__date=timezone.localdate()).count(), "languages": rows}


def level_up(user):
    """The next level, when they got at least 8 of their last 10 at this level right."""
    practice = profile(user)
    order = [key for key, _ in LEVELS]
    if not practice or practice.level == order[-1]:
        return None
    recent = list(Attempt.objects.filter(user=user, question__level=practice.level).values_list("correct", flat=True)[:LEVEL_UP_WINDOW])
    if len(recent) == LEVEL_UP_WINDOW and sum(recent) >= LEVEL_UP_RIGHT:
        return order[order.index(practice.level) + 1]
    return None


def payload(question):
    """A question for the browser, without its answer."""
    return {"id": question.pk, "language": question.get_language_display(), "level": question.get_level_display(), "kind": question.get_kind_display(),
            "topic": question.topic, "prompt": question.prompt, "code": question.code, "choices": question.choices, "lang": question.language, "type": question.kind}


def ide_on(user):
    """The developer UI: MyProgress dressed as a code editor, for people in developer mode who keep it on."""
    return is_on(user) and profile(user).ide_ui


def status_bar(user):
    """What the developer UI's status bar shows: languages, level, streak and today's answers."""
    practice = profile(user)
    since = timezone.now() - timedelta(days=60)
    days = {timezone.localdate(moment) for moment in Attempt.objects.filter(user=user, created_at__gte=since).values_list("created_at", flat=True)}
    return {"languages": ", ".join(practice.language_labels) or "Python", "level": practice.get_level_display(), "streak": streak(days),
            "today": Attempt.objects.filter(user=user, created_at__date=timezone.localdate()).count()}


def palette(user):
    """The developer UI's command palette (Ctrl+K): every place and action, by name."""
    from django.urls import reverse
    from apps.accounts.models import Profile
    from . import lab
    handle = Profile.objects.filter(user=user).values_list("handle", flat=True).first()

    def go(label, url, hint):
        return {"label": label, "url": url, "hint": hint}
    projects = reverse("landing:workspace_section", args=["projects"])
    items = [
        go("Home", reverse("landing:dashboard"), "home.py"),
        go("Projects", projects, "projects/"),
        go("New project", f"{projects}#new-project", "project --new"),
        go("Practice", reverse("practice:home"), "practice.sh"),
        go("Start a quick quiz", f'{reverse("practice:quiz")}?new=1', "quiz --new"),
        go("Code lab", reverse("practice:lab"), "lab/"),
        go("Rankings", reverse("landing:workspace_section", args=["rankings"]), "rankings.json"),
        go("Learn", reverse("landing:workspace_section", args=["learning"]), "learn.md"),
        go("Write a post", reverse("learning:create"), "post --new"),
        go("Classes", reverse("organizations:home"), "classes.ts"),
        go("Notifications", reverse("notifications:list"), "inbox.log"),
        go("Companies", reverse("companies:list"), "companies/"),
        go("Your profile", reverse("landing:public_profile", args=[handle]), f"@{handle}") if handle else None,
        go("Customize your channel", reverse("landing:channel_settings"), "channel.css"),
        go("Security", reverse("landing:security"), "security.lock"),
        go("Languages and level", reverse("practice:setup"), "settings.json"),
    ]
    items += [go(f"Watch: {item['title']} ({'Python' if item['language'] == 'python' else 'JavaScript'})", reverse("practice:walkthrough", args=[item["key"]]), "watch")
              for item in lab.WALKTHROUGHS]
    items += [{"label": "Switch to the classic look", "post": reverse("practice:ui"), "fields": {"ide": "0"}, "hint": "ui --classic"},
              {"label": "Sign out", "post": reverse("landing:logout"), "fields": {}, "hint": "exit"}]
    return [item for item in items if item]
