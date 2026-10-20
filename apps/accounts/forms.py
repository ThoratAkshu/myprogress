from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.models import User
from django.db.models import Q
from urllib.parse import urlsplit
from apps.organizations.models import Organization
from . import identity
from .images import channel_banner, channel_logo
from .models import SOCIAL_LINKS, Profile
class RegistrationForm(forms.Form):
    """A new account, and who they are: what each account type has to tell us is in identity.check()."""
    ROLE_CHOICES = [("developer", "Student or professional"), ("recruiter", "Recruiter"), ("organization", "Organization")]
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(max_length=254)
    password = forms.CharField(widget=forms.PasswordInput)
    role = forms.ChoiceField(choices=ROLE_CHOICES)
    terms = forms.BooleanField()
    organization_name = forms.CharField(max_length=120, required=False, label="Organization name")
    organization_kind = forms.ChoiceField(choices=Organization.KINDS, required=False, label="Type")
    organization_city = forms.CharField(max_length=80, required=False, label="City")
    organization_about = forms.CharField(max_length=500, required=False, label="What you teach and who it's for", widget=forms.Textarea)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        identity.add_fields(self, "any")
    def clean(self):
        cleaned = super().clean()
        role, email = cleaned.get("role"), cleaned.get("email")
        if email and role:
            problem = identity.email_problem(email, role)
            if problem:
                self.add_error("email", problem)
        cleaned["identity"] = identity.check(self, role, email or "")
        if role == "organization":
            for name, message in [("organization_name", "Give your organization's name."), ("organization_kind", "Choose what kind of organization it is."),
                                  ("organization_about", "Tell students what you teach and who it's for.")]:
                if not " ".join((cleaned.get(name) or "").split()):
                    self.add_error(name, message)
        return cleaned
    def organization_data(self):
        """The institute an organization account starts with."""
        clean = lambda name: " ".join(self.cleaned_data[name].split())
        return {"name": clean("organization_name"), "kind": self.cleaned_data["organization_kind"], "city": clean("organization_city"), "about": self.cleaned_data["organization_about"].strip()}
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
IDENTITY_FIELDS = ["occupation", "institution", "graduation_year", "job_title", "company_name", "company_website"]
IMAGE_TYPES = "image/png,image/jpeg,image/webp,image/gif"
def add_link_fields(form, saved):
    """One https field per kind of link a channel can show, filled with the saved links."""
    saved = saved if isinstance(saved, dict) else {}
    for kind, label, domains in SOCIAL_LINKS:
        example = f"https://{domains[0]}/…" if domains else "https://your-site.com"
        form.fields[f"link_{kind}"] = forms.URLField(required=False, max_length=300, label=label, initial=saved.get(kind, ""), assume_scheme="https", widget=forms.URLInput(attrs={"placeholder": example}))
def clean_links(form, cleaned):
    """The links to save by kind; each must be a full https address, on the right site where the kind has one."""
    links = {}
    for kind, label, domains in SOCIAL_LINKS:
        url = (cleaned.get(f"link_{kind}") or "").strip()
        if not url:
            continue
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host:
            form.add_error(f"link_{kind}", f"Use a full https:// address for {label}.")
        elif domains and not any(host == domain or host.endswith(f".{domain}") for domain in domains):
            form.add_error(f"link_{kind}", f"That isn't a {label} address. It should be on {domains[0]}.")
        else:
            links[kind] = url
    return links
class ImageUploadsMixin:
    """Logo and banner uploads are re-encoded (accounts/images.py), and a replaced or removed file is deleted once
    the profile is saved. IMAGES lists (field, remove checkbox) for the images the form has."""
    IMAGES = []
    def clean_avatar(self):
        upload = self.cleaned_data.get("avatar")
        return channel_logo(upload) if upload and upload is not getattr(self.instance, "avatar", None) and hasattr(upload, "content_type") else upload
    def clean_banner(self):
        upload = self.cleaned_data.get("banner")
        return channel_banner(upload) if upload and upload is not getattr(self.instance, "banner", None) and hasattr(upload, "content_type") else upload
    def apply_images(self, profile):
        """Clear the images ticked for removal; return the old files that are no longer used."""
        replaced = []
        for field, remove in self.IMAGES:
            previous = self.initial.get(field)
            if self.cleaned_data.get(remove) and field not in self.changed_data:
                setattr(profile, field, "")
            if previous and (self.cleaned_data.get(remove) or field in self.changed_data):
                replaced.append(previous)
        return replaced
class EditProfileForm(ImageUploadsMixin, forms.ModelForm):
    """Everything about you, on one page: your name and photo, who you are, headline, about, skills, address, links,
    and who can see what. What's asked depends on the account type: students and professionals say where they study
    or work, recruiters name the company they hire for, and organizations describe their institute (a second form,
    OrganizationDetailsForm). The account type itself never changes here."""
    IMAGES = [("avatar", "remove_logo")]
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, required=False, label="Last name")
    handle = forms.SlugField(max_length=40, label="Profile address", help_text="Letters, numbers and dashes.")
    bio = forms.CharField(max_length=2000, required=False, label="About", widget=forms.Textarea(attrs={"rows": 5}))
    remove_logo = forms.BooleanField(required=False)
    class Meta:
        model = Profile
        fields = ["handle", "headline", "location", "bio", "skills", "avatar", "recruiter_visible", "show_email"]
        labels = {"avatar": "Photo", "recruiter_visible": "Show my profile in recruiter search", "show_email": "Show my email on my public page"}
        widgets = {"avatar": forms.FileInput(attrs={"accept": IMAGE_TYPES})}
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        self.role = self.instance.role
        user = self.instance.user
        self.initial.setdefault("first_name", user.first_name)
        self.initial.setdefault("last_name", user.last_name)
        if self.role != "developer":  # skills and recruiter search are for students and professionals
            del self.fields["skills"], self.fields["recruiter_visible"]
        if self.role == "organization":  # the institute's city is shown instead
            del self.fields["location"]
        if self.role in {"developer", "recruiter"}:
            identity.add_fields(self, self.role)
            for name in IDENTITY_FIELDS:
                if name in self.fields:
                    self.initial.setdefault(name, getattr(self.instance, name))
        add_link_fields(self, self.instance.links)
        placeholders = {"headline": {"developer": "Backend developer · Django and React", "recruiter": "Hiring backend engineers in Pune", "organization": "Coding classes for school and college students"}[self.role],
                        "location": "Pune, India", "skills": "Python, Django, React, PostgreSQL",
                        "bio": {"developer": "What you build, what you're learning and what you're looking for.", "recruiter": "The roles you hire for and what your team works on.", "organization": "What your channel shares, and who it's for."}[self.role]}
        for name, text in placeholders.items():
            if name in self.fields:
                self.fields[name].widget.attrs["placeholder"] = text
        self.fields["headline"].widget.attrs["maxlength"] = 160
        self.fields["bio"].widget.attrs["maxlength"] = 2000
        if self.role == "organization":
            self.fields["handle"].label = "Channel address"
            self.fields["avatar"].label = "Logo"
            self.fields["headline"].label = "Tagline"
            self.fields["bio"].label = "Channel description"
    def clean_handle(self):
        handle = self.cleaned_data["handle"].strip().lower()
        if handle != self.instance.handle and len(handle) < 3:  # older, shorter addresses can stay as they are
            raise forms.ValidationError("Use at least 3 characters.")
        if Profile.objects.filter(handle=handle).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("That address is already taken.")
        return handle
    def clean_skills(self):
        return ", ".join(dict.fromkeys(skill.strip() for skill in self.cleaned_data["skills"].split(",") if skill.strip()))[:500]
    def clean(self):
        cleaned = super().clean()
        cleaned["links"] = clean_links(self, cleaned)
        if self.role in {"developer", "recruiter"}:
            cleaned["identity"] = identity.check(self, self.role, self.instance.user.email)
        return cleaned
    def identity_fields(self):
        return [self[name] for name in IDENTITY_FIELDS if name in self.fields]
    def link_fields(self):
        return [self[f"link_{kind}"] for kind, _, _ in SOCIAL_LINKS]
    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.links = self.cleaned_data["links"]
        for name, value in self.cleaned_data.get("identity", {}).items():
            setattr(profile, name, value)
        replaced = self.apply_images(profile)
        user = profile.user
        user.first_name, user.last_name = self.cleaned_data["first_name"], self.cleaned_data["last_name"]
        if commit:
            user.save(update_fields=["first_name", "last_name"])
            profile.save()
            for old in replaced:  # the old photo is no longer used anywhere
                old.storage.delete(old.name)
        return profile
class ChannelForm(ImageUploadsMixin, forms.ModelForm):
    """How the public channel looks: its name, logo, banner and colour. What it says (headline, about, links) is in
    Edit profile."""
    IMAGES = [("avatar", "remove_logo"), ("banner", "remove_banner")]
    remove_logo = forms.BooleanField(required=False)
    remove_banner = forms.BooleanField(required=False)
    class Meta:
        model = Profile
        fields = ["channel_name", "avatar", "banner", "brand_color"]
        labels = {"channel_name": "Channel name", "avatar": "Logo", "banner": "Banner", "brand_color": "Brand colour"}
        widgets = {"avatar": forms.FileInput(attrs={"accept": IMAGE_TYPES}), "banner": forms.FileInput(attrs={"accept": IMAGE_TYPES}), "brand_color": forms.RadioSelect}
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        self.fields["channel_name"].widget.attrs.update({"maxlength": 80, "placeholder": self.instance.display_channel_name if self.instance.pk else ""})
    def save(self, commit=True):
        profile = super().save(commit=False)
        replaced = self.apply_images(profile)
        if commit:
            profile.save()
            for old in replaced:  # the old logo or banner is no longer used anywhere
                old.storage.delete(old.name)
        return profile
class EmailChangeForm(forms.Form):
    """A new sign-in email. It only takes effect once they open the link we send to it (accounts/emails.py)."""
    email = forms.EmailField(max_length=150, label="New email")  # it's the username too, which holds 150 characters
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}), label="Your password")
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if email == self.user.email.lower():
            raise forms.ValidationError("That's already your email.")
        if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("An account with this email already exists.")
        problem = identity.email_problem(email, self.user.profile.role)
        if problem:
            raise forms.ValidationError(problem)
        return email
    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Your password isn't right.")
        return password
class PasswordChangeForm(auth_forms.PasswordChangeForm):
    """A new password, after the current one. Saving it signs out every other device."""
    error_messages = {**auth_forms.PasswordChangeForm.error_messages, "password_incorrect": "Your current password isn't right.", "password_mismatch": "The two new passwords don't match."}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, label in [("old_password", "Current password"), ("new_password1", "New password"), ("new_password2", "New password again")]:
            self.fields[name].label = label
            self.fields[name].help_text = ""
            self.fields[name].widget.attrs.pop("autofocus", None)
