from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.models import User
from urllib.parse import urlsplit
from .images import channel_banner, channel_logo
from .models import SOCIAL_LINKS, Profile
class RegistrationForm(forms.Form):
    ROLE_CHOICES = [("developer", "Student or professional"), ("recruiter", "Recruiter"), ("organization", "Organization")]
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(max_length=254)
    password = forms.CharField(widget=forms.PasswordInput)
    role = forms.ChoiceField(choices=ROLE_CHOICES)
    terms = forms.BooleanField()
    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email
    def clean_password(self):
        password = self.cleaned_data["password"]
        password_validation.validate_password(password)
        return password
class EmailLoginForm(forms.Form):
    email = forms.EmailField(max_length=254)
    password = forms.CharField(widget=forms.PasswordInput)
    remember = forms.BooleanField(required=False)
    user = None
    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
    def clean(self):
        cleaned = super().clean()
        if cleaned.get("email") and cleaned.get("password"):
            self.user = authenticate(self.request, username=cleaned["email"].strip().lower(), password=cleaned["password"])
            if self.user is None:
                raise forms.ValidationError("The email or password is incorrect.")
            if not self.user.is_active:
                raise forms.ValidationError("This account has been disabled.")
        return cleaned
class ProfileForm(forms.ModelForm):
    handle = forms.SlugField(min_length=3, max_length=40, help_text="Letters, numbers, and dashes.")
    class Meta:
        model = Profile
        fields = ["handle", "headline", "location", "bio", "skills", "recruiter_visible", "show_email"]
    def clean_handle(self):
        handle = self.cleaned_data["handle"].strip().lower()
        if Profile.objects.filter(handle=handle).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("That portfolio address is already taken.")
        return handle
    def clean_skills(self):
        return ", ".join(dict.fromkeys(skill.strip() for skill in self.cleaned_data["skills"].split(",") if skill.strip()))
class ChannelForm(forms.ModelForm):
    """The public channel every account brands: name, tagline, about, logo, banner, colour, and links."""
    remove_logo = forms.BooleanField(required=False)
    remove_banner = forms.BooleanField(required=False)
    class Meta:
        model = Profile
        fields = ["channel_name", "headline", "bio", "location", "avatar", "banner", "brand_color"]
        labels = {"channel_name": "Channel name", "headline": "Tagline", "bio": "About", "avatar": "Logo", "banner": "Banner", "brand_color": "Brand colour"}
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5, "maxlength": 2000}),
            "avatar": forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp,image/gif"}),
            "banner": forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp,image/gif"}),
            "brand_color": forms.RadioSelect,
        }
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        self.fields["channel_name"].widget.attrs.update({"maxlength": 80, "placeholder": self.instance.display_channel_name if self.instance.pk else ""})
        self.fields["headline"].widget.attrs["placeholder"] = "What your channel is about, in one line"
        self.fields["bio"].max_length = 2000
        saved = self.instance.links if isinstance(self.instance.links, dict) else {}
        for kind, label, domains in SOCIAL_LINKS:
            example = f"https://{domains[0]}/…" if domains else "https://your-site.com"
            self.fields[f"link_{kind}"] = forms.URLField(required=False, max_length=300, label=label, initial=saved.get(kind, ""), assume_scheme="https", widget=forms.URLInput(attrs={"placeholder": example}))
    def link_fields(self):
        return [self[f"link_{kind}"] for kind, _, _ in SOCIAL_LINKS]
    def clean(self):
        cleaned = super().clean()
        links = {}
        for kind, label, domains in SOCIAL_LINKS:
            url = (cleaned.get(f"link_{kind}") or "").strip()
            if not url:
                continue
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            if parts.scheme != "https" or not host:
                self.add_error(f"link_{kind}", f"Use a full https:// address for {label}.")
            elif domains and not any(host == domain or host.endswith(f".{domain}") for domain in domains):
                self.add_error(f"link_{kind}", f"That isn't a {label} address. It should be on {domains[0]}.")
            else:
                links[kind] = url
        cleaned["links"] = links
        return cleaned
    def clean_avatar(self):
        upload = self.cleaned_data.get("avatar")
        return channel_logo(upload) if upload and upload is not getattr(self.instance, "avatar", None) and hasattr(upload, "content_type") else upload
    def clean_banner(self):
        upload = self.cleaned_data.get("banner")
        return channel_banner(upload) if upload and upload is not getattr(self.instance, "banner", None) and hasattr(upload, "content_type") else upload
    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.links = self.cleaned_data["links"]
        replaced = []
        for field, remove in [("avatar", "remove_logo"), ("banner", "remove_banner")]:
            previous = self.initial.get(field)
            if self.cleaned_data.get(remove) and field not in self.changed_data:
                setattr(profile, field, "")
            if previous and (self.cleaned_data.get(remove) or field in self.changed_data):
                replaced.append(previous)
        if commit:
            profile.save()
            for old in replaced:  # the old logo or banner is no longer used anywhere
                old.storage.delete(old.name)
        return profile
