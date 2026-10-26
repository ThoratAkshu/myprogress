"""Organizations: institutes, colleges and teams whose members follow a private channel, do tasks, and whose growth teachers can see."""
import secrets
from datetime import timedelta
import uuid
from django.conf import settings
from pathlib import PurePosixPath
from urllib.parse import quote_plus
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
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
    # Find a coaching centre: organizations choose to be listed; students then ask to join and a teacher approves.
    is_listed = models.BooleanField(default=False, help_text="Show it in Find a coaching centre so students can ask to join")
    listing_pitch = models.CharField(max_length=160, blank=True, help_text="One line for the list, like Full-stack web development, weekend batches")
    courses = models.CharField(max_length=300, blank=True, help_text="Comma-separated, so students can search for them")
    # Where and how to reach the centre, shown on its listing so students can search by place and visit or call.
    area = models.CharField(max_length=80, blank=True, help_text="Neighbourhood or locality, like Kothrud")
    address = models.CharField(max_length=255, blank=True, help_text="Street address students can visit")
    pincode = models.CharField(max_length=10, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True, help_text="Shown on your listing. Leave it empty to take enquiries only through MyProgress.")
    opening_hours = models.CharField(max_length=120, blank=True, help_text="Like Mon–Sat, 8 am – 8 pm")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["name"]
    def __str__(self):
        return self.name
    @property
    def place(self):
        return ", ".join(part for part in [self.area, self.city] if part)
    @property
    def map_url(self):
        """A Google Maps search for the address; no key or embed needed."""
        query = ", ".join(part for part in [self.name, self.address, self.area, self.city, self.pincode] if part)
        return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(query) if (self.address or self.area) else ""
    @property
    def initials(self):
        words = [word for word in self.name.split() if word[:1].isalnum()]
        return "".join(word[0] for word in words[:2]).upper() or self.name[:2].upper()
    @property
    def course_list(self):
        return [course.strip() for course in self.courses.split(",") if course.strip()]
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
    token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)  # 43 characters
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
    meeting_link = models.URLField(blank=True, help_text="Google Meet, Zoom or any https link; empty holds the class inside MyProgress")
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
        # Without a link the class happens inside MyProgress: the teacher broadcasts from the teaching board. An
        # institute that runs its own Jitsi server gets a video call room there instead.
        if not self.meeting_link and settings.JITSI_DOMAIN:
            self.meeting_link = f"https://{settings.JITSI_DOMAIN}/MyProgress-{self.organization.slug}-{secrets.token_hex(6)}"
        super().save(*args, **kwargs)
    @property
    def in_myprogress(self):
        """Held inside MyProgress: broadcast from the teaching board, watched and chatted about on the class's watch page."""
        return not self.meeting_link
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
    last_seen_at = models.DateTimeField(null=True, blank=True, help_text="Last moment the student was on the class's watch page")
    hand_raised_at = models.DateTimeField(null=True, blank=True)
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
    token = models.CharField(max_length=64, unique=True, default=secrets.token_hex)  # 64 characters
    extension = models.CharField(max_length=5, default="webm")
    mime = models.CharField(max_length=80, blank=True, help_text="The recorder's type and codecs, which students' players need")
    is_live = models.BooleanField(default=False, help_text="Being broadcast to students right now")
    last_piece_at = models.DateTimeField(null=True, blank=True)
    stream_state = models.JSONField(default=dict, blank=True, help_text="Where the stream's header ends and its recent keyframes start, for students joining")
    pieces = models.PositiveIntegerField(default=0)
    size = models.PositiveBigIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    upload_kept_until = models.DateTimeField(null=True, blank=True, help_text="Students may still be catching up on the broadcast until then; the upload is deleted after")
    # After the class: a seekable copy, edited and published by the teacher. Students see nothing until it's published.
    source_name = models.CharField(max_length=255, blank=True, help_text="The seekable copy the editor plays and cuts; empty for older recordings")
    duration_ms = models.PositiveIntegerField(default=0)
    keyframes = models.JSONField(default=list, blank=True, help_text="Where the recording can be cut, in milliseconds")
    parts = models.JSONField(default=list, blank=True, help_text="The parts kept, as [start, end] milliseconds; empty keeps it all")
    title = models.CharField(max_length=180, blank=True)
    summary = models.TextField(blank=True)
    chapters = models.TextField(blank=True, help_text="On the recording's own timeline; moved to match the cuts when published")
    captions = models.TextField(blank=True, help_text="WebVTT on the recording's own timeline")
    thumbnail = models.ImageField(upload_to="private/class-recordings/", blank=True)
    AUDIENCES = [("members", "Students"), ("public", "Everyone")]
    audience = models.CharField(max_length=10, choices=AUDIENCES, default="members")
    post = models.ForeignKey("core.LearningPost", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", help_text="The published lecture; none while it's a draft")
    class Meta:
        ordering = ["-started_at"]
    @property
    def file_name(self):
        """Where the upload lands in media storage: the private folder, which only members-only views serve."""
        return f"private/class-recordings/{self.token}.{self.extension}"
    @property
    def can_cut(self):
        return bool(self.source_name and len(self.keyframes) > 1)
    @property
    def status(self):
        if not self.post_id:
            return "draft"
        return "public" if self.post.is_public else "members"
class ClassMessage(models.Model):
    """A chat message during a class held inside MyProgress. Members only, kept with the class."""
    live_class = models.ForeignKey(LiveClass, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    text = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["created_at", "pk"]
def calendar_token():
    return secrets.token_urlsafe(32)  # 43 characters
class CalendarFeed(models.Model):
    """A private calendar address with someone's live classes, which calendar apps subscribe to and check for
    changes. Whoever has the address can read the class times, so it can be turned off (and a new one made)."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="class_calendar")
    token = models.CharField(max_length=64, unique=True, default=calendar_token)
    created_at = models.DateTimeField(auto_now_add=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
class Playlist(models.Model):
    """A course in the class channel: lectures and notes in the order students should take them."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="playlists")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    group = models.CharField(max_length=60, blank=True, help_text="Only for this batch; empty for everyone")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-updated_at", "-pk"]
    def __str__(self):
        return self.title
class PlaylistItem(models.Model):
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="items")
    post = models.ForeignKey("core.LearningPost", on_delete=models.CASCADE, related_name="+")
    position = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["position", "pk"]
        constraints = [models.UniqueConstraint(fields=["playlist", "post"], name="playlist_item_once")]
class Batch(models.Model):
    """A class a listed centre runs for new students: what, when, where and for how much. Students find these in
    Find a coaching centre by course and place, and send the centre an enquiry about one."""
    MODES = [("centre", "At the centre"), ("online", "Online"), ("both", "At the centre or online")]
    LEVELS = [("beginner", "Beginner"), ("intermediate", "Intermediate"), ("advanced", "Advanced"), ("all", "All levels")]
    FEE_PERIODS = [("course", "for the course"), ("month", "a month")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="batches")
    title = models.CharField(max_length=120, help_text="Like Python for beginners, weekend batch")
    course = models.CharField(max_length=60, help_text="The subject students search for, like Python")
    description = models.TextField(max_length=2000, blank=True, help_text="What students learn and who it's for")
    level = models.CharField(max_length=12, choices=LEVELS, default="beginner")
    mode = models.CharField(max_length=10, choices=MODES, default="centre")
    area = models.CharField(max_length=80, blank=True, help_text="Leave empty to use the centre's area")
    city = models.CharField(max_length=80, blank=True, help_text="Leave empty to use the centre's city")
    schedule = models.CharField(max_length=120, help_text="Days and time, like Sat and Sun, 10 am – 1 pm")
    starts_on = models.DateField(null=True, blank=True)
    duration = models.CharField(max_length=60, blank=True, help_text="Like 3 months")
    fee = models.PositiveIntegerField(null=True, blank=True, help_text="In rupees. Leave it empty to share it when students ask.")
    fee_period = models.CharField(max_length=10, choices=FEE_PERIODS, default="course")
    seats = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Leave it empty if there's no limit")
    is_open = models.BooleanField(default=True, help_text="Taking enquiries. Turn it off when the batch is full.")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["starts_on", "title"]
    def __str__(self):
        return self.title
    @property
    def where_area(self):
        return self.area or self.organization.area
    @property
    def where_city(self):
        return self.city or self.organization.city
    @property
    def place(self):
        return ", ".join(part for part in [self.where_area, self.where_city] if part)
    @property
    def in_person(self):
        return self.mode in {"centre", "both"}
    @property
    def has_started(self):
        return bool(self.starts_on and self.starts_on < timezone.localdate())
class Enquiry(models.Model):
    """A student's question to a listed centre, about one class or the centre in general. Both sides write back and
    forth on it; the centre keeps track of where it stands."""
    STATUSES = [("new", "New"), ("replied", "Replied"), ("joined", "Joined"), ("closed", "Closed")]
    OPEN = {"new", "replied"}
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="enquiries")
    batch = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True, related_name="enquiries")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enquiries")
    phone = models.CharField(max_length=20, blank=True, help_text="Shared only with this centre")
    status = models.CharField(max_length=10, choices=STATUSES, default="new", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(default=timezone.now)
    student_read_at = models.DateTimeField(null=True, blank=True)
    centre_read_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-last_message_at"]
    def __str__(self):
        return f"{self.student} → {self.organization}"
    @property
    def topic(self):
        return self.batch.title if self.batch else "General enquiry"
    @property
    def last_message(self):
        """The newest message, from the prefetched ones when the list prefetched them."""
        messages = list(self.messages.all())
        return messages[-1] if messages else None
    @property
    def unread_for_centre(self):
        return not self.centre_read_at or self.centre_read_at < self.last_message_at
    @property
    def unread_for_student(self):
        return not self.student_read_at or self.student_read_at < self.last_message_at
class EnquiryMessage(models.Model):
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    from_centre = models.BooleanField(default=False)
    text = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["created_at", "pk"]
