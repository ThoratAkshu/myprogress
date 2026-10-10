from django.urls import reverse
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
    @property
    def has_verified_code(self):
        repository = getattr(self, "repository", None)
        return bool(repository and repository.languages)
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
    video_file = models.FileField(upload_to="learning/videos/", blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="learning_posts", help_text="The project this post explains")
    branch = models.CharField(max_length=255, blank=True, help_text="The repository branch this post explains")
    video_script = models.TextField(blank=True, help_text="Private script the author reads while recording")
    chapters = models.TextField(blank=True, help_text="One chapter per line, like 1:20 The data model")
    captions = models.TextField(blank=True, help_text="WebVTT captions for the video")
    body = models.TextField(blank=True)
    views = models.PositiveIntegerField(default=0)
    earnings = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    class Meta:
        ordering = ["-published_at"]
    def __str__(self):
        return self.title
    def get_absolute_url(self):
        return reverse("learning:detail", args=[self.pk])
    @property
    def has_video(self):
        return bool(self.video_file or self.video_url)
    @property
    def reading_minutes(self):
        return max(1, round(len(self.body.split()) / 200))
class ArticleImage(models.Model):
    """An image an author uploaded to use inside their articles."""
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="article_images")
    image = models.ImageField(upload_to="learning/images/")
    created_at = models.DateTimeField(auto_now_add=True)
class PostLike(models.Model):
    post = models.ForeignKey(LearningPost, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="post_likes")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="unique_post_like")]
class PostComment(models.Model):
    post = models.ForeignKey(LearningPost, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="post_comments")
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["created_at"]
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
    languages = models.JSONField(default=dict, blank=True, help_text="Bytes of code per language on the default branch")
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
class Issue(models.Model):
    """Issues and pull requests share one model so they share one number sequence per repository."""
    KIND_CHOICES = [("issue", "Issue"), ("pull", "Pull request")]
    STATE_CHOICES = [("open", "Open"), ("closed", "Closed"), ("merged", "Merged")]
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name="issues")
    number = models.PositiveIntegerField()
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="issue")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="authored_issues")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="open")
    source_branch = models.CharField(max_length=100, blank=True)
    target_branch = models.CharField(max_length=100, blank=True)
    merge_commit = models.CharField(max_length=40, blank=True)
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["repository", "number"], name="unique_repository_issue_number")]
    def __str__(self):
        return f"#{self.number} {self.title}"
class IssueComment(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="issue_comments")
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["created_at"]
