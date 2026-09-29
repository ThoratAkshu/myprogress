from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import hashlib
import secrets
import uuid
class Project(models.Model):
    STATUS_CHOICES = [("planning", "Planning"), ("building", "Building"), ("review", "In review"), ("complete", "Complete")]
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="projects")
    title = models.CharField(max_length=140)
    summary = models.TextField(blank=True)
    skills = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="planning")
    progress = models.PositiveSmallIntegerField(default=0)
    time_spent_hours = models.PositiveIntegerField(default=0)
    repository_url = models.URLField(blank=True)
    live_url = models.URLField(blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-updated_at"]
    def __str__(self):
        return self.title
    @property
    def skill_list(self):
        return [skill.strip() for skill in self.skills.split(",") if skill.strip()]
    @property
    def calculated_progress(self):
        total = self.milestones.count()
        return round(self.milestones.filter(is_complete=True).count() / total * 100) if total else self.progress
class ProjectMilestone(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=160)
    is_complete = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    class Meta:
        ordering = ["position", "id"]
class LearningPost(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="learning_posts")
    title = models.CharField(max_length=180)
    summary = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=[("article", "Article"), ("video", "Video"), ("document", "Document")], default="article")
    published_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=True)
    thumbnail = models.ImageField(upload_to="learning/", blank=True)
    video_url = models.URLField(blank=True)
    views = models.PositiveIntegerField(default=0)
    earnings = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    class Meta:
        ordering = ["-published_at"]
    def __str__(self):
        return self.title
class ContentView(models.Model):
    post = models.ForeignKey(LearningPost, on_delete=models.CASCADE, related_name="unique_views")
    viewer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="content_views")
    session_key = models.CharField(max_length=40)
    viewed_on = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "session_key", "viewed_on"], name="unique_daily_content_view")]
class ActivityEvent(models.Model):
    EVENT_TYPES = [("project", "Project"), ("learning", "Learning"), ("network", "Network"), ("profile", "Profile"), ("login", "Login")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="activity_events")
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    action = models.CharField(max_length=80)
    points = models.PositiveSmallIntegerField(default=1)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
class EarningTransaction(models.Model):
    TYPES = [("credit", "Credit"), ("payout", "Payout"), ("adjustment", "Adjustment")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="earning_transactions")
    post = models.ForeignKey(LearningPost, on_delete=models.SET_NULL, null=True, blank=True, related_name="earning_transactions")
    transaction_type = models.CharField(max_length=20, choices=TYPES, default="credit")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=180)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
class DailyLoopCompletion(models.Model):
    STEP_CHOICES = [("build", "Build"), ("learn", "Learn"), ("share", "Share")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="daily_loop_completions")
    step = models.CharField(max_length=10, choices=STEP_CHOICES)
    completed_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "step", "completed_on"], name="unique_daily_loop_step")]
class Repository(models.Model):
    VISIBILITY_CHOICES = [("private", "Private"), ("public", "Public")]
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="repository")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="repositories")
    slug = models.SlugField(max_length=100)
    storage_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    default_branch = models.CharField(max_length=100, default="main")
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default="private")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "slug"], name="unique_owner_repository_slug")]
    def __str__(self):
        return f"{self.owner.username}/{self.slug}"
class RepositoryCollaborator(models.Model):
    ROLE_CHOICES = [("read", "Read"), ("write", "Write"), ("maintain", "Maintain")]
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name="collaborators")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="repository_memberships")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="read")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["repository", "user"], name="unique_repository_collaborator")]
class GitAccessToken(models.Model):
    SCOPE_CHOICES = [("read", "Read repositories"), ("write", "Read and write repositories")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="git_tokens")
    name = models.CharField(max_length=80)
    prefix = models.CharField(max_length=12, db_index=True)
    token_hash = models.CharField(max_length=64)
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, default="write")
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    @classmethod
    def issue(cls, user, name, scope="write"):
        prefix = secrets.token_hex(4)
        raw = f"mp_{prefix}_{secrets.token_urlsafe(32)}"
        token = cls.objects.create(user=user, name=name, prefix=prefix, token_hash=hashlib.sha256(raw.encode()).hexdigest(), scope=scope)
        return token, raw
    def matches(self, raw):
        return secrets.compare_digest(self.token_hash, hashlib.sha256(raw.encode()).hexdigest())
    @property
    def is_valid(self):
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())
