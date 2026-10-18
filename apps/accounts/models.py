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
# Channel brand colours: (key, label, (from, to)) for the banner gradient when there's no banner image.
BRAND_COLORS = [
    ("ocean", "Ocean", ("#0369a1", "#0ea5e9")), ("midnight", "Midnight", ("#0f172a", "#1e3a8a")), ("emerald", "Emerald", ("#065f46", "#10b981")),
    ("violet", "Violet", ("#4c1d95", "#8b5cf6")), ("sunset", "Sunset", ("#c2410c", "#f59e0b")), ("rose", "Rose", ("#9f1239", "#f43f5e")), ("graphite", "Graphite", ("#1f2937", "#4b5563")),
]
# Links a channel can show: (kind, label, domains the link must be on; empty means any https site).
SOCIAL_LINKS = [
    ("website", "Website", ()), ("youtube", "YouTube", ("youtube.com", "youtu.be")), ("linkedin", "LinkedIn", ("linkedin.com",)), ("github", "GitHub", ("github.com",)),
    ("x", "X", ("x.com", "twitter.com")), ("instagram", "Instagram", ("instagram.com",)), ("facebook", "Facebook", ("facebook.com", "fb.com")),
]
class Profile(models.Model):
    ROLE_CHOICES = [("developer", "Student or professional"), ("recruiter", "Recruiter"), ("organization", "Organization")]
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
    show_email = models.BooleanField(default=False, help_text="Show the account email to everyone who views the profile")
    avatar = models.ImageField(upload_to="avatars/", blank=True, help_text="The channel logo or profile photo, stored as a 400x400 PNG")
    email_verified_at = models.DateTimeField(null=True, blank=True)
    # The public channel: every account brands its page with a name, logo, banner, colour, and links.
    channel_name = models.CharField(max_length=80, blank=True)
    banner = models.ImageField(upload_to="channels/banners/", blank=True)
    brand_color = models.CharField(max_length=12, choices=[(key, label) for key, label, _ in BRAND_COLORS], default="ocean")
    links = models.JSONField(default=dict, blank=True, help_text="Social and website links by kind, all https")
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} profile"
    def save(self, *args, **kwargs):
        if not self.handle:
            self.handle = unique_handle(self.user, exclude_pk=self.pk)
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "handle"}
        super().save(*args, **kwargs)
    @property
    def display_channel_name(self):
        """The channel's name: the one chosen, else an institute's own name, else the person's name or handle."""
        if self.channel_name:
            return self.channel_name
        if self.role == "organization":
            organization = self.user.organizations_owned.order_by("created_at").first()
            if organization:
                return organization.name
        return self.user.get_full_name() or f"@{self.handle}"
    @property
    def channel_links(self):
        """The saved links in a fixed order, as (kind, label, url)."""
        saved = self.links if isinstance(self.links, dict) else {}
        return [(kind, label, saved[kind]) for kind, label, _ in SOCIAL_LINKS if saved.get(kind)]
    @property
    def brand_gradient(self):
        return next((colors for key, _, colors in BRAND_COLORS if key == self.brand_color), BRAND_COLORS[0][2])
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
