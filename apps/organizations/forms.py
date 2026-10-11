from datetime import timedelta
from django import forms
from django.utils import timezone
from django.core.validators import validate_email
from apps.core.models import Repository
from .models import MAX_FILE_BYTES, Certificate, ParentAccess, ChannelPost, LiveClass, Membership, Organization, Submission, Task
def check_size(upload):
    if upload and getattr(upload, "size", 0) > MAX_FILE_BYTES:
        raise forms.ValidationError("Files can be up to 25 MB.")
    return upload
class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "kind", "city", "website", "about", "join_requires_approval", "show_leaderboard"]
        labels = {"name": "Organization name", "kind": "Type", "about": "About", "join_requires_approval": "Approve new members before they join", "show_leaderboard": "Show the class leaderboard to students"}
        widgets = {"about": forms.Textarea(attrs={"rows": 3, "placeholder": "What you teach and who it's for."}), "name": forms.TextInput(attrs={"placeholder": "Sunrise Coding Institute"})}
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
    due_at = forms.DateTimeField(required=False, label="Due", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M"])
    class Meta:
        model = Task
        fields = ["title", "instructions", "due_at", "points", "group", "resource_link", "attachment"]
        labels = {"group": "Only for batch (optional)", "resource_link": "Reference link (optional)", "attachment": "Attachment (optional)"}
        widgets = {"instructions": forms.Textarea(attrs={"rows": 6, "placeholder": "What to build, how it will be checked, and what to submit."}), "title": forms.TextInput(attrs={"placeholder": "Build a REST API for a todo app"})}
    def clean_attachment(self):
        return check_size(self.cleaned_data.get("attachment"))
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
class LiveClassForm(forms.ModelForm):
    starts_at = forms.DateTimeField(label="Starts", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M"])
    class Meta:
        model = LiveClass
        fields = ["title", "starts_at", "duration_minutes", "meeting_link", "group", "agenda"]
        labels = {"duration_minutes": "Length (minutes)", "meeting_link": "Meeting link (optional)", "group": "Only for batch (optional)", "agenda": "Agenda (optional)"}
        widgets = {"title": forms.TextInput(attrs={"placeholder": "Live: building a REST API"}), "agenda": forms.Textarea(attrs={"rows": 3, "placeholder": "What we'll cover, and anything to prepare."}), "meeting_link": forms.URLInput(attrs={"placeholder": "https://meet.google.com/... or leave empty for a free Jitsi room"})}
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
