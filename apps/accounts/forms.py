from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.models import User
class RegistrationForm(forms.Form):
    ROLE_CHOICES = [("developer", "Developer"), ("recruiter", "Recruiter"), ("organization", "Organization")]
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
