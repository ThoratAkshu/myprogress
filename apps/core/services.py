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
def earning_balance(user):
    credits = EarningTransaction.objects.filter(user=user, transaction_type__in=["credit", "adjustment"]).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    payouts = EarningTransaction.objects.filter(user=user, transaction_type="payout").aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return credits - payouts
