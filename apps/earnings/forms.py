import re
from decimal import Decimal
from django import forms
from django.utils import timezone
from .models import CompanyAccount, CreatorAccount, EarningSettings, RevenueEntry, TreasuryEntry
UPI_PATTERN = re.compile(r"^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$")
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_PATTERN = re.compile(r"^[0-9]{9,18}$")
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
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
    """One form per action on the master account page: add money, take money out, or pay tax."""
    KINDS = {"deposit", "withdrawal", "tax"}
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), label="Amount (₹)", widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}))
    entry_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    class Meta:
        model = TreasuryEntry
        fields = ["amount", "entry_date", "method", "source", "reference", "note"]
    def __init__(self, *args, kind="deposit", **kwargs):
        super().__init__(*args, prefix=kind, initial={"entry_date": timezone.localdate(), **kwargs.pop("initial", {})}, **kwargs)
        self.kind = kind
        self.fields["method"].choices = [("", "Choose how")] + TreasuryEntry.METHODS
        self.fields["source"].choices = [("", "Choose where")] + TreasuryEntry.SOURCES
        self.fields["method"].label = "How it was sent"
        self.fields["method"].required = kind != "tax"
        if kind == "deposit":
            self.fields["entry_date"].label = "Date received"
            self.fields["source"].label = "Where the money came from"
            self.fields["source"].required = True
            self.fields["reference"].label = "Bank reference (UTR)"
        else:
            del self.fields["source"]
            self.fields["entry_date"].label = "Date paid" if kind == "tax" else "Date"
            self.fields["reference"].label = "Challan number" if kind == "tax" else "Bank reference (UTR)"
            self.fields["reference"].required = kind == "tax"
            self.fields["note"].label = "Tax period, like TDS for October 2026" if kind == "tax" else "Reason"
            self.fields["note"].required = kind == "withdrawal"
    def clean_entry_date(self):
        entry_date = self.cleaned_data["entry_date"]
        if entry_date > timezone.localdate():
            raise forms.ValidationError("Record money once it has moved, not before.")
        return entry_date
    def save(self, commit=True):
        entry = super().save(commit=False)
        entry.kind = self.kind
        if commit:
            entry.save()
        return entry
class CompanyAccountForm(forms.ModelForm):
    """The business and bank behind the master account. Leave the account number empty to keep the saved one."""
    account_number_confirm = forms.CharField(max_length=18, required=False, label="Account number again")
    class Meta:
        model = CompanyAccount
        fields = ["business_name", "pan", "gstin", "billing_email", "address", "account_holder", "bank_name", "account_number", "account_number_confirm", "ifsc", "branch", "account_type", "upi_id"]
        labels = {"business_name": "Registered business name", "pan": "Business PAN", "gstin": "GSTIN", "account_holder": "Account holder name", "account_number": "Account number", "ifsc": "IFSC", "upi_id": "UPI ID"}
        widgets = {"account_number": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved_number = self.instance.account_number
        self.initial["account_number"] = ""  # never sent back to the browser
        self.fields["account_number"].widget.attrs["placeholder"] = f"Saved: ending {self.saved_number[-4:]}" if self.saved_number else "9 to 18 digits"
        for name in ["business_name", "account_holder", "bank_name", "ifsc"]:
            self.fields[name].required = True
    def clean_pan(self):
        pan = self.cleaned_data["pan"].strip().upper()
        if pan and not PAN_PATTERN.match(pan):
            raise forms.ValidationError("A PAN looks like ABCDE1234F.")
        return pan
    def clean_gstin(self):
        gstin = self.cleaned_data["gstin"].strip().upper()
        if gstin and not GSTIN_PATTERN.match(gstin):
            raise forms.ValidationError("A GSTIN has 15 characters, like 27ABCDE1234F1Z5.")
        return gstin
    def clean_ifsc(self):
        ifsc = self.cleaned_data["ifsc"].strip().upper()
        if not IFSC_PATTERN.match(ifsc):
            raise forms.ValidationError("An IFSC looks like HDFC0001234.")
        return ifsc
    def clean_upi_id(self):
        upi = self.cleaned_data["upi_id"].strip()
        if upi and not UPI_PATTERN.match(upi):
            raise forms.ValidationError("Enter a UPI ID like business@okhdfc.")
        return upi
    def clean(self):
        cleaned = super().clean()
        number = cleaned.get("account_number", "").replace(" ", "")
        if not number:
            if not self.saved_number:
                self.add_error("account_number", "Enter the account number.")
            cleaned["account_number"] = self.saved_number
        elif not ACCOUNT_PATTERN.match(number):
            self.add_error("account_number", "Enter the account number, 9 to 18 digits.")
        elif number != cleaned.get("account_number_confirm", "").replace(" ", ""):
            self.add_error("account_number_confirm", "The account numbers don't match.")
        else:
            cleaned["account_number"] = number
        return cleaned
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
