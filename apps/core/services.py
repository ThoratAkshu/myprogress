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
def score_breakdown(user):
    """Score only work that leaves evidence: pushed code, published content, and a complete profile. Logins and button clicks never count."""
    projects = list(user.projects.select_related("repository"))
    verified = [project for project in projects if project.has_verified_code]
    shipped = sum(1 for project in verified if project.status == "complete")
    building = len(verified) - shipped
    coding_days = active_coding_days(user)
    post_count = user.learning_posts.filter(is_public=True).count()
    unique_views = ContentView.objects.filter(post__author=user, post__is_public=True, viewer__isnull=False).exclude(viewer=user).values("post", "viewer").distinct().count()
    followers = user.follower_relationships.count()
    profile = Profile.objects.filter(user=user).first()
    profile_checks = [bool(profile and profile.headline), bool(profile and profile.bio), bool(profile and profile.skills), bool(profile and profile.location), any(project.is_public for project in projects)]
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
    credits = EarningTransaction.objects.filter(user=user, transaction_type__in=["credit", "adjustment"]).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    payouts = EarningTransaction.objects.filter(user=user, transaction_type="payout").aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return credits - payouts
