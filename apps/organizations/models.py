"""Organizations: institutes, colleges and teams whose members follow a private channel, do tasks, and whose growth teachers can see."""
import secrets
from datetime import timedelta
import uuid
from django.conf import settings
from pathlib import PurePosixPath
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from django.db import models
MATERIAL_EXTENSIONS = ["pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "csv", "txt", "md", "zip", "png", "jpg", "jpeg", "ipynb", "py", "js", "java", "c", "cpp", "sql"]
MAX_FILE_BYTES = 25 * 1024 * 1024
def private_upload(instance, filename):
    """Files live under a random folder, so their address can't be guessed; downloads go through a members-only view."""
    org_id = getattr(instance, "organization_id", None) or instance.task.organization_id
    return f"organizations/{org_id}/{uuid.uuid4().hex}/{PurePosixPath(filename).name}"
def new_invite_code():
    return secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
class Organization(models.Model):
    KINDS = [("institute", "Institute or coaching centre"), ("college", "College or university"), ("bootcamp", "Bootcamp"), ("company", "Company team"), ("community", "Community")]
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    kind = models.CharField(max_length=20, choices=KINDS, default="institute")
    about = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    website = models.URLField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="organizations_owned")
    invite_code = models.CharField(max_length=16, unique=True, default=new_invite_code)
    join_requires_approval = models.BooleanField(default=False, help_text="New members wait until a teacher approves them")
    show_leaderboard = models.BooleanField(default=True, help_text="Students can see the class leaderboard")
    parent_digest = models.BooleanField(default=True, help_text="Parents with a report link get a weekly summary email")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["name"]
    def __str__(self):
        return self.name
    @property
    def initials(self):
        words = [word for word in self.name.split() if word[:1].isalnum()]
        return "".join(word[0] for word in words[:2]).upper() or self.name[:2].upper()
class Membership(models.Model):
    ROLES = [("owner", "Owner"), ("teacher", "Teacher"), ("student", "Student")]
    STATUSES = [("active", "Active"), ("pending", "Waiting for approval")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="org_memberships")
    role = models.CharField(max_length=10, choices=ROLES, default="student")
    status = models.CharField(max_length=10, choices=STATUSES, default="active")
    group = models.CharField(max_length=60, blank=True, help_text="Batch or class, like Batch A 2026")
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    joined_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["role", "joined_at"]
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="one_membership_per_organization")]
    @property
    def is_staff(self):
        return self.status == "active" and self.role in {"owner", "teacher"}
class Invite(models.Model):
    """An email invitation. The shared invite link works without one; this adds a role, a group, and tracking."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invites")
    email = models.EmailField()
    name = models.CharField(max_length=120, blank=True)
    role = models.CharField(max_length=10, choices=[("student", "Student"), ("teacher", "Teacher")], default="student")
    group = models.CharField(max_length=60, blank=True)
    token = models.CharField(max_length=40, unique=True, default=secrets.token_urlsafe)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    class Meta:
        ordering = ["-created_at"]
class ChannelPost(models.Model):
    """An announcement or study material in the organization channel. Lectures and notes are learning posts shared with the organization."""
    KINDS = [("announcement", "Announcement"), ("material", "Study material")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="channel_posts")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    kind = models.CharField(max_length=20, choices=KINDS, default="announcement")
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    file = models.FileField(upload_to=private_upload, blank=True, validators=[FileExtensionValidator(MATERIAL_EXTENSIONS)])
    link = models.URLField(blank=True)
    group = models.CharField(max_length=60, blank=True, help_text="Only this batch sees it; empty means everyone")
    pinned = models.BooleanField(default=False)
    publish_at = models.DateTimeField(null=True, blank=True, help_text="Hidden from students until then; empty means straight away")
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-pinned", "-created_at"]
    @property
    def shown_at(self):
        return self.publish_at or self.created_at
    def is_scheduled(self, now):
        return bool(self.publish_at and self.publish_at > now)
    @property
    def file_name(self):
        return PurePosixPath(self.file.name).name if self.file else ""
class ChannelSeen(models.Model):
    post = models.ForeignKey(ChannelPost, on_delete=models.CASCADE, related_name="seen_by")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    seen_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="one_seen_per_member")]
class Task(models.Model):
    """Work set by teachers, in place of projects: instructions, a due date and points."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tasks")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    title = models.CharField(max_length=160)
    instructions = models.TextField()
    due_at = models.DateTimeField(null=True, blank=True)
    points = models.PositiveSmallIntegerField(default=10)
    group = models.CharField(max_length=60, blank=True, help_text="Only this batch gets it; empty means every student")
    resource_link = models.URLField(blank=True)
    attachment = models.FileField(upload_to=private_upload, blank=True, validators=[FileExtensionValidator(MATERIAL_EXTENSIONS)])
    publish_at = models.DateTimeField(null=True, blank=True, help_text="Hidden from students until then; empty means straight away")
    announced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
    def __str__(self):
        return self.title
    def is_scheduled(self, now):
        return bool(self.publish_at and self.publish_at > now)
    @property
    def attachment_name(self):
        return PurePosixPath(self.attachment.name).name if self.attachment else ""
class Submission(models.Model):
    STATUSES = [("submitted", "Waiting for review"), ("changes", "Needs changes"), ("approved", "Approved")]
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="task_submissions")
    text = models.TextField(blank=True)
    link = models.URLField(blank=True)
    file = models.FileField(upload_to=private_upload, blank=True, validators=[FileExtensionValidator(MATERIAL_EXTENSIONS)])
    repository = models.ForeignKey("core.Repository", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=10, choices=STATUSES, default="submitted")
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-updated_at"]
        constraints = [models.UniqueConstraint(fields=["task", "student"], name="one_submission_per_task")]
    @property
    def file_name(self):
        return PurePosixPath(self.file.name).name if self.file else ""
class LiveClass(models.Model):
    """A scheduled live lecture. Students join through MyProgress, which records attendance, then go to the meeting."""
    JOIN_OPENS_MINUTES = 15
    LATE_AFTER_MINUTES = 10
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="live_classes")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    title = models.CharField(max_length=160)
    agenda = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=60)
    meeting_link = models.URLField(blank=True, help_text="Google Meet, Zoom or any https link; empty makes a free Jitsi room")
    group = models.CharField(max_length=60, blank=True, help_text="Only this batch; empty means everyone")
    recording = models.ForeignKey("core.LearningPost", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    series = models.CharField(max_length=32, blank=True, db_index=True, help_text="Shared by every class created together as a repeating series")
    reminded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["starts_at"]
    def __str__(self):
        return self.title
    def save(self, *args, **kwargs):
        if not self.meeting_link:
            self.meeting_link = f"https://{settings.JITSI_DOMAIN or 'meet.jit.si'}/MyProgress-{self.organization.slug}-{secrets.token_hex(6)}"
        super().save(*args, **kwargs)
    @property
    def ends_at(self):
        return self.starts_at + timedelta(minutes=self.duration_minutes)
    def state(self, now):
        if now >= self.ends_at:
            return "over"
        if now >= self.starts_at:
            return "live"
        return "open" if now >= self.starts_at - timedelta(minutes=self.JOIN_OPENS_MINUTES) else "upcoming"
class Attendance(models.Model):
    STATUSES = [("present", "Present"), ("late", "Late"), ("absent", "Absent")]
    live_class = models.ForeignKey(LiveClass, on_delete=models.CASCADE, related_name="attendance")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="class_attendance")
    status = models.CharField(max_length=10, choices=STATUSES)
    joined_at = models.DateTimeField(null=True, blank=True)
    marked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", help_text="A teacher who set it by hand")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["live_class", "student"], name="one_attendance_per_class")]
def certificate_code():
    """A short code people can type to check a certificate, like MP-7KQ2-X9DA."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"MP-{raw[:4]}-{raw[4:]}"
class Certificate(models.Model):
    """A certificate an organization gives a student. Anyone can check it at its public address."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="certificates")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="certificates")
    title = models.CharField(max_length=160, help_text="Like Full-stack Web Development, Batch A 2026")
    description = models.CharField(max_length=300, blank=True)
    code = models.CharField(max_length=20, unique=True, default=certificate_code)
    issued_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    issued_at = models.DateTimeField(auto_now_add=True)
    show_on_profile = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=200, blank=True)
    class Meta:
        ordering = ["-issued_at"]
    def __str__(self):
        return f"{self.title} for {self.student}"
def parent_token():
    return secrets.token_urlsafe(24)
class ParentAccess(models.Model):
    """A private, read-only progress report link for a student's parent or guardian. No account needed."""
    RELATIONS = [("parent", "Parent"), ("guardian", "Guardian")]
    member = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="parents")
    name = models.CharField(max_length=120)
    email = models.EmailField()
    relation = models.CharField(max_length=10, choices=RELATIONS, default="parent")
    token = models.CharField(max_length=64, unique=True, default=parent_token)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    digest_sent_at = models.DateTimeField(null=True, blank=True, help_text="When the last weekly summary email went out")
    digest_stopped_at = models.DateTimeField(null=True, blank=True, help_text="The parent turned the weekly email off")
    class Meta:
        ordering = ["-created_at"]
class ClassRecording(models.Model):
    """A live class recorded on the teaching board. The browser uploads it a few seconds at a time while the class
    happens, so a long class never has to sit in the teacher's memory or go up as one huge file."""
    live_class = models.ForeignKey(LiveClass, on_delete=models.CASCADE, related_name="recordings")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    token = models.CharField(max_length=32, unique=True, default=secrets.token_hex)
    extension = models.CharField(max_length=5, default="webm")
    pieces = models.PositiveIntegerField(default=0)
    size = models.PositiveBigIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    post = models.ForeignKey("core.LearningPost", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    class Meta:
        ordering = ["-started_at"]
    @property
    def file_name(self):
        """Where the upload lands in media storage: the private folder, which only members-only views serve."""
        return f"private/class-recordings/{self.token}.{self.extension}"
