from datetime import timedelta
from decimal import Decimal
from django.db.models import Count, Sum
from django.utils import timezone
from apps.accounts.models import Profile
from .models import ActivityEvent, DailyLoopCompletion, EarningTransaction
def record_activity(user, event_type, action, points=1, metadata=None):
    return ActivityEvent.objects.create(user=user, event_type=event_type, action=action, points=points, metadata=metadata or {})
def complete_daily_step(user, step):
    return DailyLoopCompletion.objects.get_or_create(user=user, step=step, completed_on=timezone.localdate())
def calculate_score(user):
    project_points = min(user.projects.filter(status="complete").count() * 12 + user.projects.count() * 3, 40)
    unique_views = user.learning_posts.aggregate(total=Count("unique_views"))["total"] or 0
    learning_points = min(user.learning_posts.count() * 5 + unique_views, 20)
    impact_points = min(user.follower_relationships.count() * 2, 15)
    since = timezone.now() - timedelta(days=30)
    activity_points = min(ActivityEvent.objects.filter(user=user, created_at__gte=since).aggregate(total=Sum("points"))["total"] or 0, 25)
    return min(project_points + learning_points + impact_points + activity_points, 100)
def refresh_rank(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.score = calculate_score(user)
    profile.save(update_fields=["score"])
    profile.rank = Profile.objects.filter(score__gt=profile.score, role="developer").count() + 1
    profile.save(update_fields=["rank"])
    return profile
CONTRIBUTION_ACTIONS = {"created_project", "created_repository", "created_repository_file", "pushed_commits"}
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
def language_breakdown(repositories, limit=6):
    totals = {}
    for languages in repositories.values_list("languages", flat=True):
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
