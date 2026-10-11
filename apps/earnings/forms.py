import re
from decimal import Decimal
from django import forms
from django.utils import timezone
from .models import CreatorAccount, EarningSettings, RevenueEntry, TreasuryEntry
UPI_PATTERN = re.compile(r"^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$")
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_PATTERN = re.compile(r"^[0-9]{9,18}$")
class EarningSettingsForm(forms.ModelForm):
    class Meta:
        model = EarningSettings
        fields = ["program_enabled", "follower_goal", "follower_bonus", "coins_per_article", "coins_per_video", "coins_per_conversion", "rupees_per_conversion", "daily_post_limit", "minimum_payout", "confirmed_followers_only", "payout_day", "tds_percent", "require_pan", "auto_send"]
        labels = {"follower_bonus": "Follower bonus (₹)", "rupees_per_conversion": "Rupees per conversion (₹)", "minimum_payout": "Payment threshold (₹)", "coins_per_conversion": "Coins per conversion", "payout_day": "Payment day of the month", "tds_percent": "Tax deducted at source (%)"}
    def clean(self):
        cleaned = super().clean()
        for field in ["follower_goal", "coins_per_conversion"]:
            if cleaned.get(field) == 0:
                self.add_error(field, "Must be at least 1.")
        for field in ["follower_bonus", "rupees_per_conversion", "minimum_payout"]:
            if cleaned.get(field) is not None and cleaned[field] < 0:
                self.add_error(field, "Can't be negative.")
        if cleaned.get("payout_day") is not None and not 1 <= cleaned["payout_day"] <= 28:
            self.add_error("payout_day", "Pick a day from 1 to 28, so every month has it.")
        if cleaned.get("tds_percent") is not None and not 0 <= cleaned["tds_percent"] <= 50:
            self.add_error("tds_percent", "Enter a percentage from 0 to 50.")
        return cleaned
class PaymentDetailsForm(forms.Form):
    """The creator's payment profile, like AdSense payment settings: who to pay, where, and their PAN for tax."""
    payout_name = forms.CharField(max_length=120, label="Legal name")
    pan = forms.CharField(max_length=10, required=False, label="PAN")
    payout_method = forms.ChoiceField(choices=CreatorAccount.METHODS, widget=forms.RadioSelect)
    upi_id = forms.CharField(max_length=100, required=False, label="UPI ID")
    bank_account = forms.CharField(max_length=18, required=False, label="Account number")
    bank_account_confirm = forms.CharField(max_length=18, required=False, label="Account number again")
    ifsc = forms.CharField(max_length=11, required=False, label="IFSC")
    hold_payments = forms.BooleanField(required=False, label="Hold my payments")
    def clean_payout_name(self):
        return " ".join(self.cleaned_data["payout_name"].split())
    def clean_pan(self):
        pan = self.cleaned_data["pan"].strip().upper()
        if pan and not PAN_PATTERN.match(pan):
            raise forms.ValidationError("A PAN looks like ABCDE1234F.")
        return pan
    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("payout_method")
        upi, account, ifsc = cleaned.get("upi_id", "").strip(), cleaned.get("bank_account", "").replace(" ", ""), cleaned.get("ifsc", "").strip().upper()
        if method == "upi":
            if not UPI_PATTERN.match(upi):
                self.add_error("upi_id", "Enter a UPI ID like name@okbank.")
            account, ifsc = "", ""
        elif method == "bank":
            if not ACCOUNT_PATTERN.match(account):
                self.add_error("bank_account", "Enter the account number, 9 to 18 digits.")
            elif account != cleaned.get("bank_account_confirm", "").replace(" ", ""):
                self.add_error("bank_account_confirm", "The account numbers don't match.")
            if not IFSC_PATTERN.match(ifsc):
                self.add_error("ifsc", "An IFSC looks like HDFC0001234.")
            upi = ""
        cleaned.update(upi_id=upi, bank_account=account, ifsc=ifsc)
        return cleaned
class TreasuryEntryForm(forms.ModelForm):
    kind = forms.ChoiceField(choices=[("deposit", "Add money"), ("withdrawal", "Take money out"), ("tax", "Tax paid to government")])
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    class Meta:
        model = TreasuryEntry
        fields = ["kind", "amount", "reference", "note"]
        labels = {"reference": "Bank reference (UTR)"}
class RevenueEntryForm(forms.ModelForm):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), label="Amount (₹)")
    received_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Received on")
    class Meta:
        model = RevenueEntry
        fields = ["source", "amount", "received_on", "reference", "note"]
        labels = {"reference": "Invoice or bank reference"}
    def clean_received_on(self):
        received_on = self.cleaned_data["received_on"]
        if received_on > timezone.localdate():
            raise forms.ValidationError("Record money once it has arrived, not before.")
        return received_on
class AdjustmentForm(forms.Form):
    coins = forms.IntegerField(required=False, min_value=-100000, max_value=100000, initial=0)
    amount = forms.DecimalField(required=False, max_digits=10, decimal_places=2, min_value=Decimal("-100000"), max_value=Decimal("100000"), label="Rupees")
    reason = forms.CharField(max_length=180)
    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("coins") and not cleaned.get("amount"):
            raise forms.ValidationError("Enter coins or rupees to add or remove.")
        return cleaned
