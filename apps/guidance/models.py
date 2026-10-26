"""Next-step suggestions: what each member was told to try, and what they did with it."""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
STEPS = [
    ("start_project", "Start a project"), ("add_code", "Add code to a project"), ("resume_project", "Pick up a project"),
    ("join_centre", "Join a coaching centre"), ("practice", "Practise a problem"),
]
class StepDismissal(models.Model):
    """A suggestion the member put aside: "Not now" hides it for a few days, "Not for me" for two months."""
    REASONS = [("later", "Not now"), ("not_for_me", "Not for me")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="step_dismissals")
    step = models.CharField(max_length=30, choices=STEPS)
    reason = models.CharField(max_length=12, choices=REASONS)
    until = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "step"], name="one_dismissal_per_step")]
class StepEvent(models.Model):
    """How often a member was shown, opened or put aside a suggestion on one day, for the staff report."""
    ACTIONS = [("shown", "Shown"), ("clicked", "Opened"), ("dismissed", "Put aside")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="step_events")
    step = models.CharField(max_length=30, choices=STEPS)
    action = models.CharField(max_length=10, choices=ACTIONS)
    day = models.DateField(default=timezone.localdate)
    count = models.PositiveIntegerField(default=1)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "step", "action", "day"], name="one_step_event_per_day")]
        indexes = [models.Index(fields=["day", "step"], name="step_event_day_idx")]
