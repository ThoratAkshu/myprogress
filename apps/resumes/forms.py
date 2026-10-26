from django import forms
from .models import ResumeSettings
class ResumeSettingsForm(forms.ModelForm):
    """The choices on Your resume. Projects and sections are picked from what the member has."""
    projects = forms.TypedMultipleChoiceField(coerce=int, required=False, widget=forms.CheckboxSelectMultiple, label="Projects to show")
    sections = forms.MultipleChoiceField(choices=ResumeSettings.SECTIONS, required=False, widget=forms.CheckboxSelectMultiple, label="Sections")
    class Meta:
        model = ResumeSettings
        fields = ["template", "summary", "phone", "show_email", "recruiters_can_download"]
        labels = {"template": "Layout", "summary": "Summary", "phone": "Phone (optional)", "show_email": "Show my email", "recruiters_can_download": "Recruiters can download it from my profile"}
        widgets = {"template": forms.RadioSelect, "summary": forms.Textarea(attrs={"rows": 4}), "phone": forms.TextInput(attrs={"placeholder": "+91 98765 43210", "inputmode": "tel"})}
    def __init__(self, *args, projects=(), generated_summary="", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["projects"].choices = [(project.pk, project.title + ("" if project.is_public else " (private)")) for project in projects]
        self.fields["summary"].widget.attrs["placeholder"] = generated_summary or "A few lines about you and what you build."
        if not self.is_bound:
            self.fields["projects"].initial = list(self.instance.project_ids)
            self.fields["sections"].initial = [key for key, _ in ResumeSettings.SECTIONS if key not in self.instance.hidden_sections]
    def clean_phone(self):
        from apps.organizations.admissions import clean_phone
        try:
            return clean_phone(self.cleaned_data["phone"])
        except ValueError as error:
            raise forms.ValidationError(str(error))
    def clean_projects(self):
        chosen = self.cleaned_data["projects"]
        if len(chosen) > ResumeSettings.MAX_PROJECTS:
            raise forms.ValidationError(f"Choose up to {ResumeSettings.MAX_PROJECTS} projects.")
        return chosen
    def save(self, commit=True):
        settings = super().save(commit=False)
        settings.summary = settings.summary.strip()
        settings.project_ids = self.cleaned_data["projects"]
        settings.hidden_sections = [key for key, _ in ResumeSettings.SECTIONS if key not in self.cleaned_data["sections"]]
        if commit:
            settings.save()
        return settings
