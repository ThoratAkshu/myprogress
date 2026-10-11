from datetime import timedelta
from decimal import Decimal
from django.db.models import Prefetch, Sum
from django.utils import timezone
from apps.accounts.models import Profile
from .models import ActivityEvent, ContentView, DailyLoopCompletion, EarningTransaction, Repository
CONTRIBUTION_ACTIONS = {"created_project", "created_repository", "created_repository_file", "pushed_commits", "published_learning", "opened_issue", "opened_pull_request", "merged_pull_request"}
CODE_ACTIONS = {"created_repository_file", "pushed_commits"}
def record_activity(user, event_type, action, points=1, metadata=None):
    return ActivityEvent.objects.create(user=user, event_type=event_type, action=action, points=points, metadata=metadata or {})
def complete_daily_step(user, step):
    return DailyLoopCompletion.objects.get_or_create(user=user, step=step, completed_on=timezone.localdate())
def active_coding_days(user, days=90):
    since = timezone.now() - timedelta(days=days)
    return len({timezone.localdate(value) for value in ActivityEvent.objects.filter(user=user, action__in=CODE_ACTIONS, created_at__gte=since).values_list("created_at", flat=True)})
def progress_facts(user):
    """The counts the score and achievements are built from."""
    projects = list(user.projects.select_related("repository"))
    verified = [project for project in projects if project.has_verified_code]
    shipped = sum(1 for project in verified if project.status == "complete")
    profile = Profile.objects.filter(user=user).first()
    profile_checks = [bool(profile and profile.headline), bool(profile and profile.bio), bool(profile and profile.skills), bool(profile and profile.location), any(project.is_public for project in projects)]
    return {
        "shipped": shipped,
        "building": len(verified) - shipped,
        "coding_days": active_coding_days(user),
        "posts": user.learning_posts.filter(is_public=True).count(),
        "readers": ContentView.objects.filter(post__author=user, post__is_public=True, viewer__isnull=False).exclude(viewer=user).values("post", "viewer").distinct().count(),
        "followers": user.follower_relationships.count(),
        "profile_sections": sum(profile_checks),
        "pushed_code": ActivityEvent.objects.filter(user=user, action__in=CODE_ACTIONS).exists(),
    }
def score_breakdown(user, facts=None):
    """Score only work that leaves evidence: pushed code, published content, and a complete profile. Logins and button clicks never count."""
    facts = facts or progress_facts(user)
    shipped, building, coding_days, post_count, unique_views, followers = facts["shipped"], facts["building"], facts["coding_days"], facts["posts"], facts["readers"], facts["followers"]
    profile_checks = [True] * facts["profile_sections"]
    components = [
        {"key": "shipped", "label": "Verified shipped work", "points": min(shipped * 12 + building * 4, 35), "max": 35, "detail": f"{shipped} shipped and {building} in progress with pushed code", "hint": "Push code to a project repository, then complete its milestones."},
        {"key": "consistency", "label": "Coding consistency", "points": min(coding_days, 25), "max": 25, "detail": f"{coding_days} active coding day{'s' if coding_days != 1 else ''} in the last 90", "hint": "Push commits on more days rather than more commits on one day."},
        {"key": "teaching", "label": "Teaching", "points": min(post_count * 4 + unique_views // 10, 20), "max": 20, "detail": f"{post_count} published post{'s' if post_count != 1 else ''}, {unique_views} signed-in reader{'s' if unique_views != 1 else ''}", "hint": "Explain how you built a project in a video or guide."},
        {"key": "community", "label": "Community", "points": min(followers, 10), "max": 10, "detail": f"{followers} follower{'s' if followers != 1 else ''}", "hint": "Help others and share your work so developers follow you."},
        {"key": "profile", "label": "Profile completeness", "points": sum(profile_checks) * 2, "max": 10, "detail": f"{sum(profile_checks)} of 5 sections complete", "hint": "Add a headline, about, skills, location, and a public project."},
    ]
    for component in components:
        component["percent"] = round(component["points"] * 100 / component["max"])
    return components
def calculate_score(user):
    return sum(component["points"] for component in score_breakdown(user))
def refresh_rank(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.score = calculate_score(user)
    profile.rank = Profile.objects.filter(score__gt=profile.score, role="developer").exclude(pk=profile.pk).count() + 1
    profile.save(update_fields=["score", "rank"])
    return profile
def visible_developers():
    repositories = Repository.objects.select_related("project").only("id", "owner_id", "languages", "project__id", "project__status")
    return Profile.objects.filter(role="developer", recruiter_visible=True).select_related("user").prefetch_related(Prefetch("user__repositories", queryset=repositories))
def leaderboard(language=None, limit=25):
    profiles = visible_developers().filter(score__gt=0)
    if language:
        profiles = profiles.filter(user__repositories__languages__has_key=language).distinct()
    return profiles.order_by("-score", "user__date_joined")[:limit]
def coding_streak(user):
    """Consecutive days with pushed code, ending today (or yesterday, so the streak survives until tonight)."""
    days = {timezone.localdate(value) for value in ActivityEvent.objects.filter(user=user, action__in=CODE_ACTIONS, created_at__gte=timezone.now() - timedelta(days=400)).values_list("created_at", flat=True)}
    cursor = timezone.localdate()
    if cursor not in days:
        cursor -= timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak
def record_rank_snapshots(day=None, replace=False):
    """Save today's rank and score for every ranked developer, for weekly movement. `replace` rewrites today's."""
    from .models import RankSnapshot
    day = day or timezone.localdate()
    if replace:
        RankSnapshot.objects.filter(day=day).delete()
    existing = set(RankSnapshot.objects.filter(day=day).values_list("user_id", flat=True))
    missing = Profile.objects.filter(role="developer", score__gt=0, rank__isnull=False).exclude(user_id__in=existing).values_list("user_id", "rank", "score")
    RankSnapshot.objects.bulk_create([RankSnapshot(user_id=user_id, day=day, rank=rank, score=score) for user_id, rank, score in missing], ignore_conflicts=True)
def weekly_movement(user_ids, days=7):
    """{user_id: {"rank": places climbed (negative if dropped), "score": points gained}} against about a week ago."""
    from .models import RankSnapshot
    today = timezone.localdate()
    earliest = {}
    for snapshot in RankSnapshot.objects.filter(user_id__in=user_ids, day__gte=today - timedelta(days=days), day__lt=today).order_by("day"):
        earliest.setdefault(snapshot.user_id, snapshot)
    current = dict(Profile.objects.filter(user_id__in=list(earliest)).values_list("user_id", "rank"))
    scores = dict(Profile.objects.filter(user_id__in=list(earliest)).values_list("user_id", "score"))
    return {user_id: {"rank": snapshot.rank - (current.get(user_id) or snapshot.rank), "score": (scores.get(user_id) or 0) - snapshot.score} for user_id, snapshot in earliest.items()}
ACHIEVEMENTS = [
    ("first_push", "First push", "Push code to a MyProgress repository.", "git-commit", "pushed_code", 1),
    ("on_a_roll", "On a roll", "Push code on 7 different days in 90 days.", "zap", "coding_days", 7),
    ("marathon", "Marathon coder", "Push code on 30 different days in 90 days.", "activity", "coding_days", 30),
    ("shipper", "Shipper", "Ship a project with verified code.", "check-circle", "shipped", 1),
    ("serial_shipper", "Serial shipper", "Ship 3 projects with verified code.", "box", "shipped", 3),
    ("teacher", "Teacher", "Publish your first learning post.", "book-open", "posts", 1),
    ("mentor", "Mentor", "Publish 5 learning posts.", "award", "posts", 5),
    ("audience", "Audience", "Reach 50 signed-in readers.", "eye", "readers", 50),
    ("rising_voice", "Rising voice", "Get 10 followers.", "users", "followers", 10),
    ("all_set", "All set", "Complete all 5 profile sections.", "user", "profile_sections", 5),
    ("top_ten", "Top 10", "Reach the global top 10.", "trending-up", "top_ten", 1),
]
def achievements(facts, profile):
    """Badges earned from real work, with progress toward the ones still locked."""
    values = {**facts, "pushed_code": int(facts["pushed_code"]), "top_ten": int(bool(profile.score and profile.rank and profile.rank <= 10))}
    badges = []
    for key, title, description, icon, fact, goal in ACHIEVEMENTS:
        value = min(values[fact], goal)
        badges.append({"key": key, "title": title, "description": description, "icon": icon, "earned": value >= goal, "value": value, "goal": goal, "percent": round(value * 100 / goal)})
    return badges
def platform_languages():
    totals = {}
    for languages in Repository.objects.filter(owner__profile__role="developer", owner__profile__recruiter_visible=True).values_list("languages", flat=True):
        for language, size in (languages or {}).items():
            totals[language] = totals.get(language, 0) + size
    return sorted(totals, key=lambda language: -totals[language])
def contribution_calendar(user, days=365):
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    start -= timedelta(days=(start.weekday() + 1) % 7)
    counts = {}
    events = ActivityEvent.objects.filter(user=user, action__in=CONTRIBUTION_ACTIONS, created_at__date__gte=start - timedelta(days=1))
    for created_at, action, metadata in events.values_list("created_at", "action", "metadata"):
        day = timezone.localdate(created_at)
        if day >= start:
            counts[day] = counts.get(day, 0) + (int(metadata.get("commits", 1)) if action == "pushed_commits" else 1)
    calendar_days = []
    months = []
    for offset in range((today - start).days + 1):
        day = start + timedelta(days=offset)
        count = counts.get(day, 0)
        level = 0 if not count else 1 if count < 3 else 2 if count < 6 else 3 if count < 10 else 4
        calendar_days.append({"date": day, "count": count, "level": level})
        if day.day == 1 or offset == 0:
            months.append({"label": day.strftime("%b"), "column": offset // 7 + 1})
    if len(months) > 1 and months[1]["column"] - months[0]["column"] < 3:
        months.pop(0)
    return {"days": calendar_days, "months": months, "weeks": (len(calendar_days) + 6) // 7, "total": sum(counts.values()), "active_days": len(counts)}
def language_breakdown(language_maps, limit=6):
    totals = {}
    for languages in language_maps:
        for language, size in (languages or {}).items():
            totals[language] = totals.get(language, 0) + size
    grand_total = sum(totals.values())
    if not grand_total:
        return []
    ranked = sorted(totals.items(), key=lambda item: -item[1])
    breakdown = [{"name": name, "percent": round(size * 100 / grand_total, 1)} for name, size in ranked[:limit]]
    if len(ranked) > limit:
        breakdown.append({"name": "Other", "percent": round(sum(size for _, size in ranked[limit:]) * 100 / grand_total, 1)})
    return breakdown
def earning_balance(user):
    credits = EarningTransaction.objects.filter(user=user, transaction_type__in=["credit", "adjustment", "refund"]).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    payouts = EarningTransaction.objects.filter(user=user, transaction_type="payout").aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return credits - payouts
