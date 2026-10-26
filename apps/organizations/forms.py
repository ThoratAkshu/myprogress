import json
from datetime import timedelta
from django import forms
from django.utils import timezone
from django.core.validators import validate_email
from apps.core.models import Repository
from apps.learning.media import MAX_THUMBNAIL_BYTES
from apps.learning.timeline import clean_chapters
from .models import MAX_FILE_BYTES, Batch, Certificate, ClassRecording, ParentAccess, Playlist, ChannelPost, LiveClass, Membership, Organization, Submission, Task
def check_size(upload):
    if upload and getattr(upload, "size", 0) > MAX_FILE_BYTES:
        raise forms.ValidationError("Files can be up to 25 MB.")
    return upload
CENTRE_FIELDS = ["area", "address", "pincode", "contact_phone", "opening_hours"]
CENTRE_LABELS = {"area": "Area or locality", "pincode": "PIN code", "contact_phone": "Phone for enquiries (optional)", "opening_hours": "Opening hours"}
CENTRE_WIDGETS = {"area": forms.TextInput(attrs={"placeholder": "Kothrud"}), "address": forms.TextInput(attrs={"placeholder": "2nd floor, Lane 5, Karve Road"}),
                  "pincode": forms.TextInput(attrs={"placeholder": "411038", "inputmode": "numeric"}), "contact_phone": forms.TextInput(attrs={"placeholder": "+91 98765 43210", "inputmode": "tel"}),
                  "opening_hours": forms.TextInput(attrs={"placeholder": "Mon–Sat, 8 am – 8 pm"})}
class CentreDetailsMixin:
    """Where the centre is and how to reach it, for Find a coaching centre; on both Settings and Edit profile."""
    def clean_pincode(self):
        from .admissions import PINCODE
        value = self.cleaned_data["pincode"].replace(" ", "")
        if value and not PINCODE.match(value):
            raise forms.ValidationError("Enter the 6-digit PIN code.")
        return value
    def clean_contact_phone(self):
        from .admissions import clean_phone
        try:
            return clean_phone(self.cleaned_data["contact_phone"])
        except ValueError as error:
            raise forms.ValidationError(str(error))
class OrganizationForm(CentreDetailsMixin, forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "kind", "city", *CENTRE_FIELDS, "website", "about", "join_requires_approval", "show_leaderboard", "parent_digest", "is_listed", "listing_pitch", "courses"]
        labels = {"name": "Organization name", "kind": "Type", "about": "About", "join_requires_approval": "Approve new members before they join", "show_leaderboard": "Show the class leaderboard to students", "parent_digest": "Email parents a weekly summary",
                  "is_listed": "List us in Find a coaching centre", "listing_pitch": "One line for the list", "courses": "Courses you teach", **CENTRE_LABELS}
        widgets = {"about": forms.Textarea(attrs={"rows": 3, "placeholder": "What you teach and who it's for."}), "name": forms.TextInput(attrs={"placeholder": "Sunrise Coding Institute"}),
                   "listing_pitch": forms.TextInput(attrs={"placeholder": "Full-stack web development, weekend batches"}), "courses": forms.TextInput(attrs={"placeholder": "Python, Web development, Data science"}), **CENTRE_WIDGETS}
class OrganizationDetailsForm(CentreDetailsMixin, forms.ModelForm):
    """An organization account's institute, edited from Edit profile: how students and parents know it. Joining and
    class rules stay in the organization's own Settings."""
    about = forms.CharField(max_length=2000, required=False, label="About the institute", widget=forms.Textarea(attrs={"rows": 4, "placeholder": "What you teach and who it's for."}))
    class Meta:
        model = Organization
        fields = ["name", "kind", "city", *CENTRE_FIELDS, "website", "about"]
        labels = {"name": "Institute name", "kind": "Type", **CENTRE_LABELS}
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Sunrise Coding Institute"}),
                   "city": forms.TextInput(attrs={"placeholder": "Pune"}), "website": forms.URLInput(attrs={"placeholder": "https://your-institute.com"}), **CENTRE_WIDGETS}
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        kwargs.setdefault("prefix", "org")
        super().__init__(*args, **kwargs)
    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())
class InviteForm(forms.Form):
    emails = forms.CharField(widget=forms.Textarea(attrs={"rows": 4, "placeholder": "one@example.com, two@example.com\nor one email per line"}), label="Email addresses")
    role = forms.ChoiceField(choices=[("student", "Student"), ("teacher", "Teacher")], initial="student")
    group = forms.CharField(max_length=60, required=False, label="Batch (optional)", widget=forms.TextInput(attrs={"placeholder": "Batch A 2026"}))
    def clean_emails(self):
        raw = self.cleaned_data["emails"].replace(";", ",").replace("\n", ",")
        emails = list(dict.fromkeys(email.strip().lower() for email in raw.split(",") if email.strip()))
        bad = []
        for email in emails:
            try:
                validate_email(email)
            except forms.ValidationError:
                bad.append(email)
        if bad:
            raise forms.ValidationError(f"These don't look like email addresses: {', '.join(bad[:5])}")
        if not emails:
            raise forms.ValidationError("Add at least one email address.")
        if len(emails) > 200:
            raise forms.ValidationError("Invite up to 200 people at a time.")
        return emails
class MemberForm(forms.ModelForm):
    class Meta:
        model = Membership
        fields = ["role", "group"]
        labels = {"group": "Batch"}
    def __init__(self, *args, can_change_role=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [("teacher", "Teacher"), ("student", "Student")]
        if not can_change_role:
            del self.fields["role"]
class ChannelPostForm(forms.ModelForm):
    publish_at = forms.DateTimeField(required=False, label="Publish later (optional)", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M"])
    class Meta:
        model = ChannelPost
        fields = ["kind", "title", "body", "file", "link", "group", "publish_at", "pinned"]
        labels = {"kind": "Type", "body": "Message", "file": "File (PDF, slides, notes, code… up to 25 MB)", "link": "Link (optional)", "group": "Only for batch (optional)", "pinned": "Pin to the top"}
        widgets = {"body": forms.Textarea(attrs={"rows": 4, "placeholder": "Today's lecture covers…"}), "title": forms.TextInput(attrs={"placeholder": "Week 3 notes: SQL joins"})}
    def clean_file(self):
        return check_size(self.cleaned_data.get("file"))
    def clean_publish_at(self):
        publish_at = self.cleaned_data.get("publish_at")
        if publish_at and publish_at <= timezone.now():
            raise forms.ValidationError("Pick a time in the future, or leave it empty to post now.")
        return publish_at
    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") == "material" and not cleaned.get("file") and not cleaned.get("link"):
            raise forms.ValidationError("Study material needs a file or a link.")
        return cleaned
class TaskForm(forms.ModelForm):
    publish_at = forms.DateTimeField(required=False, label="Release later (optional)", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M"])
    due_at = forms.DateTimeField(required=False, label="Due", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M"])
    class Meta:
        model = Task
        fields = ["title", "instructions", "due_at", "points", "group", "publish_at", "resource_link", "attachment"]
        labels = {"group": "Only for batch (optional)", "resource_link": "Reference link (optional)", "attachment": "Attachment (optional)"}
        widgets = {"instructions": forms.Textarea(attrs={"rows": 6, "placeholder": "What to build, how it will be checked, and what to submit."}), "title": forms.TextInput(attrs={"placeholder": "Build a REST API for a todo app"})}
    def clean_attachment(self):
        return check_size(self.cleaned_data.get("attachment"))
    def clean(self):
        cleaned = super().clean()
        publish_at, due_at = cleaned.get("publish_at"), cleaned.get("due_at")
        if publish_at and publish_at <= timezone.now():
            self.add_error("publish_at", "Pick a time in the future, or leave it empty to set the task now.")
        elif publish_at and due_at and due_at <= publish_at:
            self.add_error("due_at", "The due date has to come after the task is released.")
        return cleaned
    def clean_points(self):
        points = self.cleaned_data["points"]
        if not 1 <= points <= 1000:
            raise forms.ValidationError("Use between 1 and 1000 points.")
        return points
class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ["text", "link", "file", "repository"]
        labels = {"text": "Your answer or notes", "link": "Link (live demo, document…)", "file": "File (up to 25 MB)", "repository": "One of your repositories"}
        widgets = {"text": forms.Textarea(attrs={"rows": 5, "placeholder": "What you did, and anything your teacher should know."})}
    def __init__(self, *args, student=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["repository"].queryset = Repository.objects.filter(owner=student).select_related("project") if student else Repository.objects.none()
        self.fields["repository"].empty_label = "No repository"
        self.fields["repository"].label_from_instance = lambda repository: repository.project.title if repository.project_id else repository.slug
    def clean_file(self):
        return check_size(self.cleaned_data.get("file"))
    def clean(self):
        cleaned = super().clean()
        if not any([cleaned.get("text", "").strip(), cleaned.get("link"), cleaned.get("file"), cleaned.get("repository"), self.instance.file]):
            raise forms.ValidationError("Add an answer, a link, a file, or a repository.")
        return cleaned
class ReviewForm(forms.Form):
    status = forms.ChoiceField(choices=[("approved", "Approve"), ("changes", "Ask for changes")])
    score = forms.IntegerField(required=False, min_value=0)
    feedback = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3, "placeholder": "What was good, and what to improve."}))
    def __init__(self, *args, points=10, **kwargs):
        super().__init__(*args, **kwargs)
        self.points = points
        self.fields["score"].max_value = points
        self.fields["score"].widget.attrs["max"] = points
    def clean_score(self):
        score = self.cleaned_data.get("score")
        if score is not None and score > self.points:
            raise forms.ValidationError(f"The most this task is worth is {self.points}.")
        return score
WEEKDAYS = [("0", "Mon"), ("1", "Tue"), ("2", "Wed"), ("3", "Thu"), ("4", "Fri"), ("5", "Sat"), ("6", "Sun")]
class LiveClassForm(forms.ModelForm):
    repeat = forms.ChoiceField(choices=[("none", "Doesn't repeat"), ("weekly", "Every week"), ("weekdays", "Every weekday (Mon to Fri)"), ("days", "On chosen days")], initial="none", required=False, label="Repeat")
    days = forms.MultipleChoiceField(choices=WEEKDAYS, required=False, widget=forms.CheckboxSelectMultiple, label="On")
    occurrences = forms.IntegerField(min_value=2, max_value=60, initial=8, required=False, label="Number of classes")
    starts_at = forms.DateTimeField(label="Starts", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M"])
    field_order = ["title", "starts_at", "duration_minutes", "repeat", "days", "occurrences", "meeting_link", "group", "agenda"]
    class Meta:
        model = LiveClass
        fields = ["title", "starts_at", "duration_minutes", "meeting_link", "group", "agenda"]
        labels = {"duration_minutes": "Length (minutes)", "meeting_link": "Meeting link (optional)", "group": "Only for batch (optional)", "agenda": "Agenda (optional)"}
        widgets = {"title": forms.TextInput(attrs={"placeholder": "Live: building a REST API"}), "agenda": forms.Textarea(attrs={"rows": 3, "placeholder": "What we'll cover, and anything to prepare."}), "meeting_link": forms.URLInput(attrs={"placeholder": "Leave empty to teach inside MyProgress, or paste a Meet or Zoom link"})}
    def clean_starts_at(self):
        starts_at = self.cleaned_data["starts_at"]
        if starts_at < timezone.now() - timedelta(hours=1):
            raise forms.ValidationError("Pick a time that hasn't passed.")
        return starts_at
    def clean_duration_minutes(self):
        minutes = self.cleaned_data["duration_minutes"]
        if not 10 <= minutes <= 480:
            raise forms.ValidationError("Classes can run from 10 minutes to 8 hours.")
        return minutes
    def clean_meeting_link(self):
        link = self.cleaned_data.get("meeting_link", "")
        if link and not link.startswith("https://"):
            raise forms.ValidationError("Meeting links must start with https://.")
        return link
    def clean(self):
        cleaned = super().clean()
        if cleaned.get("repeat") == "days" and not cleaned.get("days"):
            self.add_error("days", "Pick the days the class happens.")
        if (cleaned.get("repeat") or "none") != "none" and not cleaned.get("occurrences"):
            self.add_error("occurrences", "How many classes in the series?")
        return cleaned
class CertificateForm(forms.Form):
    title = forms.CharField(max_length=160, widget=forms.TextInput(attrs={"placeholder": "Full-stack Web Development"}))
    description = forms.CharField(max_length=300, required=False, label="Description (optional)", widget=forms.TextInput(attrs={"placeholder": "Completed 12 weeks of projects, tasks and live classes"}))
    students = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple, error_messages={"required": "Pick at least one student."})
    def __init__(self, *args, choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["students"].choices = choices
class ParentForm(forms.ModelForm):
    class Meta:
        model = ParentAccess
        fields = ["name", "email", "relation"]
        labels = {"name": "Parent or guardian's name", "relation": "Relation"}
class RecordingForm(forms.Form):
    """A class recording's details in the editor, with the parts kept (seconds, from the timeline)."""
    title = forms.CharField(max_length=180)
    summary = forms.CharField(required=False, max_length=5000, label="Description", widget=forms.Textarea(attrs={"rows": 3, "placeholder": "What the class covered, for students looking for it later."}))
    chapters = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 5, "placeholder": "0:00 Introduction\n4:30 Inner joins"}))
    thumbnail = forms.ImageField(required=False)
    audience = forms.ChoiceField(choices=ClassRecording.AUDIENCES, widget=forms.RadioSelect)
    parts = forms.CharField(required=False, widget=forms.HiddenInput)
    playlist = forms.TypedChoiceField(required=False, coerce=int, empty_value=None, label="Add to a playlist")
    def __init__(self, *args, playlists=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["playlist"].choices = [("", "Not now"), *[(playlist.pk, playlist.title) for playlist in playlists]]
    def clean_chapters(self):
        try:
            return clean_chapters(self.cleaned_data.get("chapters"))
        except ValueError as error:
            raise forms.ValidationError(str(error))
    def clean_thumbnail(self):
        thumbnail = self.cleaned_data.get("thumbnail")
        if thumbnail and thumbnail.size > MAX_THUMBNAIL_BYTES:
            raise forms.ValidationError("Thumbnails must be 5 MB or smaller.")
        return thumbnail
    def clean_parts(self):
        """[[start, end], ...] in milliseconds, or None when the timeline didn't send any (keep the last edit)."""
        text = self.cleaned_data.get("parts", "")
        if not text:
            return None
        try:
            parts = json.loads(text)
            if not isinstance(parts, list) or len(parts) > 1000:
                raise ValueError
            return [[max(0, round(float(start) * 1000)), max(0, round(float(end) * 1000))] for start, end in parts]
        except (TypeError, ValueError):
            raise forms.ValidationError("The edit couldn't be read. Reload the page and edit again.")
class PlaylistForm(forms.ModelForm):
    class Meta:
        model = Playlist
        fields = ["title", "description", "group"]
        labels = {"group": "Only for batch (optional)"}
        widgets = {"title": forms.TextInput(attrs={"placeholder": "Linux, from zero"}), "description": forms.Textarea(attrs={"rows": 3, "placeholder": "What the course covers, and in what order to take it."})}
class BatchForm(forms.ModelForm):
    """A class the centre lists in Find a coaching centre."""
    starts_on = forms.DateField(required=False, label="Starts on (optional)", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), input_formats=["%Y-%m-%d"])
    field_order = ["title", "course", "level", "mode", "schedule", "starts_on", "duration", "fee", "fee_period", "seats", "area", "city", "description", "is_open"]
    class Meta:
        model = Batch
        fields = ["title", "course", "level", "mode", "schedule", "starts_on", "duration", "fee", "fee_period", "seats", "area", "city", "description", "is_open"]
        labels = {"title": "Class name", "course": "Course", "mode": "Where", "schedule": "Days and time", "duration": "Length (optional)", "fee": "Fee in ₹ (optional)", "fee_period": "Fee is",
                  "seats": "Seats (optional)", "area": "Area (optional)", "city": "City (optional)", "description": "What students learn (optional)", "is_open": "Taking enquiries"}
        widgets = {"title": forms.TextInput(attrs={"placeholder": "Python for beginners, weekend batch"}), "course": forms.TextInput(attrs={"placeholder": "Python"}),
                   "schedule": forms.TextInput(attrs={"placeholder": "Sat and Sun, 10 am – 1 pm"}), "duration": forms.TextInput(attrs={"placeholder": "3 months"}),
                   "fee": forms.NumberInput(attrs={"placeholder": "12000", "min": 0}), "seats": forms.NumberInput(attrs={"placeholder": "20", "min": 1}),
                   "area": forms.TextInput(attrs={"placeholder": "The centre's area"}), "city": forms.TextInput(attrs={"placeholder": "The centre's city"}),
                   "description": forms.Textarea(attrs={"rows": 4, "placeholder": "Topics, projects students build, and who it suits."})}
    def clean_title(self):
        return " ".join(self.cleaned_data["title"].split())
    def clean_course(self):
        return " ".join(self.cleaned_data["course"].split())
class EnquiryForm(forms.Form):
    message = forms.CharField(min_length=10, max_length=2000, label="Your question", widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Hi, I'd like to know about the next batch, the fees and whether beginners can join."}))
    phone = forms.CharField(max_length=20, required=False, label="Phone (optional)", widget=forms.TextInput(attrs={"placeholder": "+91 98765 43210", "inputmode": "tel", "autocomplete": "tel"}))
    batch = forms.IntegerField(required=False, widget=forms.HiddenInput)
    def clean_message(self):
        return self.cleaned_data["message"].strip()
    def clean_phone(self):
        from .admissions import clean_phone
        try:
            return clean_phone(self.cleaned_data["phone"])
        except ValueError as error:
            raise forms.ValidationError(str(error))
class EnquiryReplyForm(forms.Form):
    text = forms.CharField(max_length=2000, label="Reply", widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Write a reply"}))
    def clean_text(self):
        text = self.cleaned_data["text"].strip()
        if not text:
            raise forms.ValidationError("Write a reply first.")
        return text
