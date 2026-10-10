import secrets
from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
def unique_handle(user, exclude_pk=None):
    base = slugify(user.get_full_name())[:32].strip("-") or f"developer-{secrets.token_hex(3)}"
    handle = base
    counter = 2
    while Profile.objects.filter(handle=handle).exclude(pk=exclude_pk).exists():
        handle = f"{base}-{counter}"
        counter += 1
    return handle
class Profile(models.Model):
    ROLE_CHOICES = [("developer", "Developer"), ("recruiter", "Recruiter"), ("organization", "Organization")]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    handle = models.SlugField(max_length=40, unique=True, null=True, blank=True, help_text="Public portfolio address: /u/<handle>/")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="developer")
    headline = models.CharField(max_length=160, blank=True)
    location = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    skills = models.CharField(max_length=500, blank=True, help_text="Comma-separated skills")
    rank = models.PositiveIntegerField(null=True, blank=True)
    score = models.PositiveIntegerField(default=0)
    recruiter_visible = models.BooleanField(default=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} profile"
    def save(self, *args, **kwargs):
        if not self.handle:
            self.handle = unique_handle(self.user, exclude_pk=self.pk)
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "handle"}
        super().save(*args, **kwargs)
    @property
    def skill_list(self):
        return [skill.strip() for skill in self.skills.split(",") if skill.strip()]
    @property
    def email_domain(self):
        return self.user.email.rsplit("@", 1)[-1].lower() if "@" in self.user.email else ""
    @property
    def is_verified_recruiter(self):
        """A recruiter who confirmed an email on a company domain (not a free mailbox provider)."""
        return self.role in {"recruiter", "organization"} and self.email_verified_at is not None and bool(self.email_domain) and self.email_domain not in FREE_EMAIL_DOMAINS
FREE_EMAIL_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "ymail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "zoho.com", "yandex.com", "mail.com", "gmx.com", "rediffmail.com"}
class Follow(models.Model):
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name="following_relationships")
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name="follower_relationships")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["follower", "following"], name="unique_user_follow")]
        ordering = ["-created_at"]
    def __str__(self):
        return f"{self.follower} follows {self.following}"
