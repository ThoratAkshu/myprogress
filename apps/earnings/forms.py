from decimal import Decimal
from django import forms
from .models import EarningSettings, TreasuryEntry
class EarningSettingsForm(forms.ModelForm):
    class Meta:
        model = EarningSettings
        fields = ["program_enabled", "follower_goal", "follower_bonus", "coins_per_article", "coins_per_video", "coins_per_conversion", "rupees_per_conversion", "daily_post_limit", "minimum_payout", "confirmed_followers_only"]
        labels = {"follower_bonus": "Follower bonus (₹)", "rupees_per_conversion": "Rupees per conversion (₹)", "minimum_payout": "Minimum withdrawal (₹)", "coins_per_conversion": "Coins per conversion"}
    def clean(self):
        cleaned = super().clean()
        for field in ["follower_goal", "coins_per_conversion"]:
            if cleaned.get(field) == 0:
                self.add_error(field, "Must be at least 1.")
        for field in ["follower_bonus", "rupees_per_conversion", "minimum_payout"]:
            if cleaned.get(field) is not None and cleaned[field] < 0:
                self.add_error(field, "Can't be negative.")
        return cleaned
class TreasuryEntryForm(forms.ModelForm):
    kind = forms.ChoiceField(choices=[("deposit", "Add money"), ("withdrawal", "Take money out")])
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    class Meta:
        model = TreasuryEntry
        fields = ["kind", "amount", "reference", "note"]
        labels = {"reference": "Bank reference (UTR)"}
class AdjustmentForm(forms.Form):
    coins = forms.IntegerField(required=False, min_value=-100000, max_value=100000, initial=0)
    amount = forms.DecimalField(required=False, max_digits=10, decimal_places=2, min_value=Decimal("-100000"), max_value=Decimal("100000"), label="Rupees")
    reason = forms.CharField(max_length=180)
    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("coins") and not cleaned.get("amount"):
            raise forms.ValidationError("Enter coins or rupees to add or remove.")
        return cleaned
