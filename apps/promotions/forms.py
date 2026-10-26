from django import forms
from django.core.exceptions import ValidationError
from apps.accounts.images import promotion_image
from .models import AUDIENCES, Promotion
from .services import clean_destination
class PromotionForm(forms.ModelForm):
    sponsor = forms.ChoiceField(label="Promote as")
    audiences = forms.MultipleChoiceField(choices=AUDIENCES, required=False, widget=forms.CheckboxSelectMultiple, label="Who should see it",
                                          help_text="Pick none for everyone. A member who fits any of these can see it.")
    upload = forms.ImageField(required=False, label="Image (optional)", help_text="Cropped to 1200 × 628. PNG, JPEG, WebP or GIF, up to 4 MB.")
    remove_image = forms.BooleanField(required=False, label="Remove the image")
    class Meta:
        model = Promotion
        fields = ["headline", "body", "cta_label", "cta_url", "skills", "city", "starts_on", "ends_on", "max_views"]
        labels = {"headline": "Headline", "body": "Text", "cta_label": "Button", "cta_url": "Button link (optional)", "skills": "Skills or languages (optional)",
                  "city": "City (optional)", "starts_on": "Start (optional)", "ends_on": "End (optional)", "max_views": "Stop after this many views (optional)"}
        widgets = {
            "headline": forms.TextInput(attrs={"placeholder": "Weekend Python batch starts 3 November", "data-preview": "headline"}),
            "body": forms.Textarea(attrs={"rows": 3, "maxlength": 280, "placeholder": "Live classes, weekly projects and a mentor who reviews your code.", "data-preview": "body"}),
            "cta_label": forms.TextInput(attrs={"data-preview": "cta"}),
            "cta_url": forms.TextInput(attrs={"placeholder": "Leave empty to send people to your page"}),
            "skills": forms.TextInput(attrs={"placeholder": "Python, Django"}),
            "city": forms.TextInput(attrs={"placeholder": "Pune"}),
            "starts_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "ends_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
    def __init__(self, *args, sponsors=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.sponsors = {option["key"]: option for option in sponsors}
        self.fields["sponsor"].choices = [(option["key"], f"{option['name']} ({'coaching centre' if option['kind'] == 'organization' else option['kind']})") for option in sponsors]
        instance = self.instance
        if instance.pk:
            self.initial.setdefault("audiences", instance.audiences)
            current = f"organization:{instance.organization_id}" if instance.organization_id else f"company:{instance.company_id}" if instance.company_id else "recruiter"
            self.initial.setdefault("sponsor", current)
        if len(sponsors) == 1:
            self.fields["sponsor"].widget = forms.HiddenInput()
            self.initial["sponsor"] = sponsors[0]["key"]
    def clean_cta_url(self):
        return clean_destination(self.cleaned_data.get("cta_url"))
    def clean_cta_label(self):
        return (self.cleaned_data.get("cta_label") or "").strip() or "Learn more"
    def clean_upload(self):
        upload = self.cleaned_data.get("upload")
        return promotion_image(upload) if upload else None
    def clean(self):
        data = super().clean()
        if data.get("starts_on") and data.get("ends_on") and data["ends_on"] < data["starts_on"]:
            self.add_error("ends_on", "The end can't be before the start.")
        if data.get("max_views") == 0:
            self.add_error("max_views", "Leave it empty for no limit, or enter a number above 0.")
        return data
    def save(self, commit=True):
        promotion = super().save(commit=False)
        option = self.sponsors[self.cleaned_data["sponsor"]]
        promotion.sponsor_kind, promotion.sponsor_name = option["kind"], option["name"]
        promotion.organization, promotion.company = option["organization"], option["company"]
        promotion.audiences = [key for key in self.cleaned_data.get("audiences", []) if key != "everyone"]
        if self.cleaned_data.get("remove_image") and promotion.image:
            promotion.image.delete(save=False)
            promotion.image = None
        if self.cleaned_data.get("upload"):
            if promotion.image:
                promotion.image.delete(save=False)
            promotion.image.save(self.cleaned_data["upload"].name, self.cleaned_data["upload"], save=False)
        if commit:
            promotion.save()
        return promotion
