"""Sponsored posts: coaching centres, recruiters and companies on MyProgress promote themselves in the home feed.

A sponsor writes a post and picks who should see it (by what they've been doing lately, what they study or work as,
their skills and city). Staff review every post before it goes live. Members see each post at most a few times a
day, labelled Sponsored, and can hide it or report it.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
AUDIENCES = [
    ("everyone", "Everyone"),
    ("watching", "Mostly watching, nothing built yet"),
    ("new", "New members"),
    ("building", "Building projects"),
    ("students", "Students"),
    ("professionals", "Working professionals"),
]
class Promotion(models.Model):
    SPONSORS = [("organization", "Coaching centre or institute"), ("recruiter", "Recruiter"), ("company", "Company")]
    STATUSES = [("draft", "Draft"), ("pending", "Waiting for review"), ("live", "Live"), ("rejected", "Changes needed"), ("paused", "Paused"), ("ended", "Ended")]
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="promotions")
    sponsor_kind = models.CharField(max_length=20, choices=SPONSORS)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, null=True, blank=True, related_name="promotions")
    company = models.ForeignKey("companies.Company", on_delete=models.CASCADE, null=True, blank=True, related_name="promotions")
    sponsor_name = models.CharField(max_length=120, help_text="Shown on the post: the centre, company or recruiter's company")
    headline = models.CharField(max_length=90)
    body = models.TextField(max_length=280)
    image = models.ImageField(upload_to="promotions/", blank=True)
    cta_label = models.CharField(max_length=30, default="Learn more")
    cta_url = models.CharField(max_length=300, blank=True, help_text="Where the button goes: a page on MyProgress (starting with /) or an https:// address. Empty sends people to the sponsor's own page.")
    audiences = models.JSONField(default=list, blank=True)
    skills = models.CharField(max_length=300, blank=True, help_text="Comma-separated; only people with one of these skills or languages see it")
    city = models.CharField(max_length=80, blank=True, help_text="Only people in this city see it")
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    max_views = models.PositiveIntegerField(null=True, blank=True, help_text="Stop after this many views")
    status = models.CharField(max_length=10, choices=STATUSES, default="draft", db_index=True)
    review_note = models.CharField(max_length=300, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    views = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
    def __str__(self):
        return f"{self.headline} ({self.sponsor_name})"
    @property
    def skill_list(self):
        return [skill.strip() for skill in self.skills.split(",") if skill.strip()]
    @property
    def sponsor_initials(self):
        words = [word for word in self.sponsor_name.split() if word[:1].isalnum()]
        return "".join(word[0] for word in words[:2]).upper() or "AD"
    @property
    def audience_labels(self):
        labels = dict(AUDIENCES)
        return [labels[key] for key in self.audiences if key in labels] or ["Everyone"]
    @property
    def click_rate(self):
        return round(self.clicks * 100 / self.views, 1) if self.views else 0
    @property
    def is_running(self):
        today = timezone.localdate()
        return (self.status == "live" and (not self.starts_on or self.starts_on <= today) and (not self.ends_on or self.ends_on >= today)
                and (self.max_views is None or self.views < self.max_views))
    @property
    def editable(self):
        return self.status in {"draft", "rejected", "paused", "live"}
class PromotionView(models.Model):
    """One member's views of one post on one day: the frequency cap, and the unique reach the sponsor sees."""
    promotion = models.ForeignKey(Promotion, on_delete=models.CASCADE, related_name="view_days")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    day = models.DateField(default=timezone.localdate)
    count = models.PositiveSmallIntegerField(default=1)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["promotion", "user", "day"], name="one_promotion_view_row_per_day")]
class PromotionClick(models.Model):
    promotion = models.ForeignKey(Promotion, on_delete=models.CASCADE, related_name="click_rows")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
class PromotionHide(models.Model):
    """A member hid a post: they never see it again. Reports go to staff, and enough of them pause the post."""
    REASONS = [("not_interested", "Not interested"), ("misleading", "Misleading or a scam"), ("offensive", "Offensive")]
    promotion = models.ForeignKey(Promotion, on_delete=models.CASCADE, related_name="hides")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=20, choices=REASONS, default="not_interested")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["promotion", "user"], name="one_hide_per_promotion")]
