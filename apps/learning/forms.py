import subprocess
from django import forms
from django.utils import timezone
from apps.organizations.services import staff_organizations
from apps.core.git_service import list_branches
from apps.core.models import LearningPost
from .media import MAX_THUMBNAIL_BYTES, validate_video_file
from .timeline import clean_captions, clean_chapters
MIN_ARTICLE_LENGTH = 200
class LearningPostForm(forms.ModelForm):
    publish_at = forms.DateTimeField(required=False, label="Release to students later (optional)", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M"])
    kind = forms.ChoiceField(choices=[("article", "Article"), ("video", "Video")], widget=forms.RadioSelect)
    video_file = forms.FileField(required=False, validators=[validate_video_file], widget=forms.ClearableFileInput(attrs={"accept": "video/mp4,video/webm"}))
    thumbnail = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={"accept": "image/*"}))
    class Meta:
        model = LearningPost
        fields = ["title", "kind", "project", "branch", "summary", "body", "video_script", "chapters", "captions", "video_url", "video_file", "thumbnail", "is_public", "organization", "publish_at"]
        labels = {"project": "Project this explains", "video_script": "Video script", "video_url": "Or link a video (YouTube or any https URL)", "is_public": "Publish publicly", "organization": "Share only with my organization"}
        help_texts = {"project": "", "video_script": "", "chapters": "", "captions": ""}
        widgets = {"summary": forms.Textarea(attrs={"rows": 3, "placeholder": "One or two sentences on what readers will learn."}), "body": forms.Textarea(attrs={"rows": 18, "placeholder": "## The problem\n\n## How I built it\n\n## What I'd do differently"}), "title": forms.TextInput(attrs={"placeholder": "How I built ..."}), "chapters": forms.Textarea(attrs={"rows": 5, "placeholder": "0:00 Intro\n1:20 The data model\n4:05 Deploying"}), "captions": forms.Textarea(attrs={"rows": 6, "placeholder": "WEBVTT", "spellcheck": "false"}), "video_script": forms.Textarea(attrs={"rows": 12, "placeholder": "INTRO\nHi, I'm ... In this video I'll show how I built ...\n\nDEMO\n[SHOW: the running app]"})}
    def __init__(self, *args, user=None, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = user.projects.order_by("title") if user else self.fields["project"].queryset.none()
        self.fields["project"].empty_label = "Not about a specific project"
        # Teachers can share a lecture or notes with their organization only, instead of publicly.
        self.fields["organization"].queryset = staff_organizations(user) if user else self.fields["organization"].queryset.none()
        self.fields["organization"].empty_label = "No, use the setting above"
        self.fields["organization"].help_text = ""
    def clean_video_url(self):
        url = self.cleaned_data.get("video_url", "")
        if url and not url.lower().startswith(("https://", "http://")):
            raise forms.ValidationError("Video links must start with https://.")
        return url
    def clean_chapters(self):
        try:
            return clean_chapters(self.cleaned_data.get("chapters"))
        except ValueError as error:
            raise forms.ValidationError(str(error))
    def clean_captions(self):
        try:
            return clean_captions(self.cleaned_data.get("captions"))
        except ValueError as error:
            raise forms.ValidationError(str(error))
    def clean_thumbnail(self):
        thumbnail = self.cleaned_data.get("thumbnail")
        if thumbnail and getattr(thumbnail, "size", 0) > MAX_THUMBNAIL_BYTES:
            raise forms.ValidationError("Thumbnails must be 5 MB or smaller.")
        return thumbnail
    def clean(self):
        cleaned = super().clean()
        if cleaned.get("organization"):
            cleaned["is_public"] = False  # organization posts never appear publicly
        publish_at = cleaned.get("publish_at")
        if publish_at and not cleaned.get("organization"):
            self.add_error("publish_at", "Scheduling is for posts shared with your organization.")
        elif publish_at and publish_at <= timezone.now() and publish_at != getattr(self.instance, "publish_at", None):
            self.add_error("publish_at", "Pick a time in the future, or leave it empty to share now.")
        project, branch = cleaned.get("project"), (cleaned.get("branch") or "").strip()
        cleaned["branch"] = branch
        if branch:
            repository = getattr(project, "repository", None) if project else None
            try:
                known = {item["name"] for item in list_branches(repository)} if repository else set()
            except (subprocess.CalledProcessError, OSError, ValueError):
                known = set()
            if branch not in known:
                self.add_error("branch", "Pick a branch from this project's repository.")
        kind = cleaned.get("kind")
        has_video = bool(cleaned.get("video_file") or cleaned.get("video_url"))
        if kind == "video" and not has_video:
            self.add_error("video_file", "Upload a video or add a video link.")
        if kind == "article" and len((cleaned.get("body") or "").strip()) < MIN_ARTICLE_LENGTH:
            self.add_error("body", f"Articles need at least {MIN_ARTICLE_LENGTH} characters so they help other developers.")
        return cleaned
class ArticleImageForm(forms.Form):
    """An image pasted, dropped, or uploaded into the article editor."""
    image = forms.ImageField()
    def clean_image(self):
        image = self.cleaned_data["image"]
        if image.size > MAX_THUMBNAIL_BYTES:
            raise forms.ValidationError("Images must be 5 MB or smaller.")
        if getattr(image, "image", None) is None or image.image.format not in {"PNG", "JPEG", "GIF", "WEBP"}:
            raise forms.ValidationError("Upload a PNG, JPEG, GIF, or WebP image.")
        return image
