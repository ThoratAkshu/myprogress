from django.db import models
from django.contrib.auth.models import User
from apps.accounts.models import Profile
RECRUITER_ROLES = {"recruiter", "organization"}
class Shortlist(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shortlists")
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="unique_owner_shortlist_name")]
    def __str__(self):
        return self.name
class ShortlistEntry(models.Model):
    STAGE_CHOICES = [("saved", "Saved"), ("contacted", "Contacted"), ("interviewing", "Interviewing"), ("offer", "Offer"), ("hired", "Hired"), ("declined", "Not a fit")]
    shortlist = models.ForeignKey(Shortlist, on_delete=models.CASCADE, related_name="entries")
    candidate = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shortlist_entries")
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default="saved")
    note = models.TextField(blank=True, help_text="Private to the recruiter who owns the shortlist")
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-updated_at"]
        constraints = [models.UniqueConstraint(fields=["shortlist", "candidate"], name="unique_shortlist_candidate")]
class ContactRequest(models.Model):
    STATUS_CHOICES = [("pending", "Pending"), ("accepted", "Accepted"), ("declined", "Declined")]
    recruiter = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_contact_requests")
    developer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="contact_requests")
    role_title = models.CharField(max_length=120)
    message = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["recruiter", "developer"], condition=models.Q(status="pending"), name="unique_pending_contact_request")]
class PortfolioView(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="portfolio_views")
    viewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="portfolio_views_made")
    viewer_role = models.CharField(max_length=20)
    viewed_on = models.DateField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "viewer", "viewed_on"], name="unique_daily_portfolio_view")]
