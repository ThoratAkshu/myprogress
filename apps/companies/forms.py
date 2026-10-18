from django import forms
from .models import Company, Team


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ["name", "description", "website"]
        labels = {"name": "Company name", "description": "What it does (optional)", "website": "Website (optional)"}
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Acme Labs"}), "description": forms.TextInput(attrs={"placeholder": "We build tools for small shops"})}


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "description"]
        labels = {"name": "Team name", "description": "What the team works on (optional)"}
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Backend"})}
