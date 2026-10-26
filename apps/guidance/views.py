"""Next steps: open or put aside the suggestion on the home feed, and the staff report on how members spend their time."""
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from . import services
from .models import STEPS, StepEvent
STEP_KEYS = {key for key, _ in STEPS}
@login_required(login_url="landing:home")
def go_view(request, step):
    """Opens a suggestion's main action (or its other one with ?to=other), counting the click. The address comes from
    the step itself, worked out again here, never from the link, so this can't be used to send people elsewhere."""
    found = services.find_step(request.user, step) if step in STEP_KEYS else None
    if not found:
        return redirect("landing:dashboard")
    action = found["secondary"] if request.GET.get("to") == "other" and found["secondary"] else found["primary"]
    services.record(request.user, step, "clicked")
    return redirect(action["url"])
@login_required(login_url="landing:home")
@require_POST
def dismiss_view(request, step):
    if step not in STEP_KEYS:
        raise Http404
    services.dismiss(request.user, step, "not_for_me" if request.POST.get("reason") == "not_for_me" else "later")
    if request.headers.get("x-requested-with") == "fetch":
        upcoming = services.next_step(request.user)
        return JsonResponse({"ok": True, "next": upcoming["key"] if upcoming else None})
    return redirect("landing:dashboard")
REPORT_DAYS = 30
@login_required(login_url="landing:home")
def report_view(request):
    """Staff only: who is only watching, and how members respond to the suggestions."""
    if not request.user.is_staff:
        raise Http404
    from apps.core.models import ActivityEvent
    from apps.core.services import CONTRIBUTION_ACTIONS
    since = timezone.now() - timedelta(days=services.WINDOW_DAYS)
    developers = User.objects.filter(is_active=True).filter(Q(profile__role="developer") | Q(profile__isnull=True))
    active = developers.filter(id__in=ActivityEvent.objects.filter(created_at__gte=since).exclude(action="signed_in").values("user_id"))
    # Members who watched at least WATCHING_MIN videos and made nothing: no project work, pushes or posts.
    counted = developers.annotate(
        watched=Count("activity_events", filter=Q(activity_events__action="viewed_learning", activity_events__created_at__gte=since), distinct=True),
        made=Count("activity_events", filter=Q(activity_events__action__in=CONTRIBUTION_ACTIONS, activity_events__created_at__gte=since), distinct=True),
    )
    watching_only = counted.filter(watched__gte=services.WATCHING_MIN, made=0).count()
    building = counted.filter(made__gt=0).count()
    report_since = timezone.localdate() - timedelta(days=REPORT_DAYS)
    totals = {row["step"]: row for row in StepEvent.objects.filter(day__gte=report_since).values("step").annotate(
        shown=Count("user", filter=Q(action="shown"), distinct=True),
        clicked=Sum("count", filter=Q(action="clicked")),
        dismissed=Sum("count", filter=Q(action="dismissed")),
    )}
    steps = []
    for key, label in STEPS:
        row = totals.get(key, {})
        shown, clicked = row.get("shown") or 0, row.get("clicked") or 0
        steps.append({"key": key, "label": label, "shown": shown, "clicked": clicked, "dismissed": row.get("dismissed") or 0,
                      "rate": round(clicked * 100 / shown) if shown else 0})
    return render(request, "guidance/report.html", {
        "section": "", "window_days": services.WINDOW_DAYS, "report_days": REPORT_DAYS, "watching_min": services.WATCHING_MIN,
        "active": active.count(), "watching_only": watching_only, "building": building, "steps": steps,
    })
