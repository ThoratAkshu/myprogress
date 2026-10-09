from django import forms
from apps.core.models import LearningPost
from .media import MAX_THUMBNAIL_BYTES, validate_video_file
MIN_ARTICLE_LENGTH = 200
class LearningPostForm(forms.ModelForm):
    kind = forms.ChoiceField(choices=[("article", "Article"), ("video", "Video")], widget=forms.RadioSelect)
    video_file = forms.FileField(required=False, validators=[validate_video_file], widget=forms.ClearableFileInput(attrs={"accept": "video/mp4,video/webm"}))
    thumbnail = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={"accept": "image/*"}))
    class Meta:
        model = LearningPost
        fields = ["title", "kind", "project", "summary", "body", "video_url", "video_file", "thumbnail", "is_public"]
        labels = {"project": "Project this explains", "video_url": "Or link a video (YouTube or any https URL)", "is_public": "Publish publicly"}
        help_texts = {"project": ""}
        widgets = {"summary": forms.Textarea(attrs={"rows": 3, "placeholder": "One or two sentences on what readers will learn."}), "body": forms.Textarea(attrs={"rows": 18, "placeholder": "## The problem\n\n## How I built it\n\n## What I'd do differently"}), "title": forms.TextInput(attrs={"placeholder": "How I built ..."})}
    def __init__(self, *args, user=None, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = user.projects.order_by("title") if user else self.fields["project"].queryset.none()
        self.fields["project"].empty_label = "Not about a specific project"
    def clean_video_url(self):
        url = self.cleaned_data.get("video_url", "")
        if url and not url.lower().startswith(("https://", "http://")):
            raise forms.ValidationError("Video links must start with https://.")
        return url
    def clean_thumbnail(self):
        thumbnail = self.cleaned_data.get("thumbnail")
        if thumbnail and getattr(thumbnail, "size", 0) > MAX_THUMBNAIL_BYTES:
            raise forms.ValidationError("Thumbnails must be 5 MB or smaller.")
        return thumbnail
    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        has_video = bool(cleaned.get("video_file") or cleaned.get("video_url"))
        if kind == "video" and not has_video:
            self.add_error("video_file", "Upload a video or add a video link.")
        if kind == "article" and len((cleaned.get("body") or "").strip()) < MIN_ARTICLE_LENGTH:
            self.add_error("body", f"Articles need at least {MIN_ARTICLE_LENGTH} characters so they help other developers.")
        return cleaned
