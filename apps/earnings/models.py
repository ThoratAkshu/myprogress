"""Creator earnings: the rules, coins, payouts, and the platform's master (treasury) account."""
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
class EarningSettings(models.Model):
    """The earning rules, editable from the finance console. There is only ever one row."""
    program_enabled = models.BooleanField(default=True, help_text="Turn earning on or off for everyone")
    follower_goal = models.PositiveIntegerField(default=100, help_text="Followers needed to unlock earnings")
    follower_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("10"), help_text="One-time reward in rupees when a creator reaches the follower goal")
    coins_per_article = models.PositiveIntegerField(default=5)
    coins_per_video = models.PositiveIntegerField(default=10)
    coins_per_conversion = models.PositiveIntegerField(default=100, help_text="Coins that turn into rupees")
    rupees_per_conversion = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("10"))
    daily_post_limit = models.PositiveIntegerField(default=5, help_text="Posts per creator per day that earn coins")
    minimum_payout = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("100"), help_text="Payment threshold: a finished month's balance must reach this to be paid")
    payout_day = models.PositiveSmallIntegerField(default=21, help_text="Day of the month payments go out, for the month before")
    tds_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"), help_text="Tax deducted at source from each payment, in percent")
    require_pan = models.BooleanField(default=True, help_text="Hold payments until the creator adds a PAN")
    auto_send = models.BooleanField(default=False, help_text="Send payments through the payout provider on payment day without waiting for approval")
    confirmed_followers_only = models.BooleanField(default=False, help_text="Count only followers who confirmed their email")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    class Meta:
        verbose_name_plural = "earning settings"
        permissions = [("access_finance", "Can use the finance console")]
    @classmethod
    def current(cls):
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings
class CreatorAccount(models.Model):
    """A creator's place in the program: when they unlocked earnings, and where payouts go."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="creator_account")
    eligible_since = models.DateTimeField(null=True, blank=True)
    follower_bonus_paid_at = models.DateTimeField(null=True, blank=True)
    suspended = models.BooleanField(default=False)
    suspended_reason = models.CharField(max_length=200, blank=True)
    METHODS = [("upi", "UPI"), ("bank", "Bank account")]
    payout_name = models.CharField(max_length=120, blank=True, help_text="Legal name, as on the bank account and PAN")
    pan = models.CharField(max_length=10, blank=True)
    payout_method = models.CharField(max_length=10, choices=METHODS, default="upi")
    upi_id = models.CharField(max_length=100, blank=True)
    bank_account = models.CharField(max_length=18, blank=True)
    ifsc = models.CharField(max_length=11, blank=True)
    hold_payments = models.BooleanField(default=False, help_text="The creator asked to hold payments")
    details_updated_at = models.DateTimeField(null=True, blank=True)
    provider_contact_id = models.CharField(max_length=40, blank=True)
    provider_fund_account_id = models.CharField(max_length=40, blank=True)
    def __str__(self):
        return f"Creator account of {self.user}"
    @property
    def masked_pan(self):
        return f"•••••{self.pan[5:]}" if self.pan else ""
    @property
    def destination(self):
        """Where payments go, safe to show: UPI arjun@okhdfc or Bank ••••4321 (HDFC0001234)."""
        if self.payout_method == "bank":
            return f"Bank ••••{self.bank_account[-4:]} ({self.ifsc})" if self.bank_account and self.ifsc else ""
        return f"UPI {self.upi_id}" if self.upi_id else ""
class CoinTransaction(models.Model):
    KINDS = [("post", "Post reward"), ("reversal", "Post removed"), ("conversion", "Converted to rupees"), ("adjustment", "Adjustment")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="coin_transactions")
    amount = models.IntegerField(help_text="Positive coins earned, negative coins spent or removed")
    kind = models.CharField(max_length=20, choices=KINDS)
    post = models.ForeignKey("core.LearningPost", on_delete=models.SET_NULL, null=True, blank=True, related_name="coin_transactions")
    description = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at", "-id"]
class PaymentRun(models.Model):
    """One month's payments, like YouTube's monthly AdSense payment: earnings close on the 1st and are paid on payment day."""
    STATUSES = [("scheduled", "Scheduled"), ("ready", "Ready to send"), ("sending", "Sending"), ("completed", "Completed")]
    month = models.DateField(unique=True, help_text="First day of the month being paid for")
    scheduled_for = models.DateField()
    status = models.CharField(max_length=12, choices=STATUSES, default="scheduled")
    created_at = models.DateTimeField(auto_now_add=True)
    prepared_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    class Meta:
        ordering = ["-month"]
    def __str__(self):
        return f"Payments for {self.month:%B %Y}"
class PayoutRequest(models.Model):
    """One creator's payment within a run. `amount` leaves the wallet; the creator receives it minus `tds_amount`."""
    STATUSES = [("pending", "Waiting to send"), ("processing", "Sending"), ("paid", "Paid"), ("rejected", "Returned")]
    run = models.ForeignKey(PaymentRun, on_delete=models.PROTECT, null=True, blank=True, related_name="payouts")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payout_requests")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    tds_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    destination = models.CharField(max_length=80, blank=True)
    upi_id = models.CharField(max_length=100, blank=True)
    payout_name = models.CharField(max_length=120)
    provider_payout_id = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reference = models.CharField(max_length=100, blank=True, help_text="UPI or bank transfer reference (UTR)")
    note = models.CharField(max_length=200, blank=True)
    class Meta:
        ordering = ["-requested_at"]
        constraints = [models.UniqueConstraint(fields=["run", "user"], name="one_payout_per_creator_per_run")]
    @property
    def net_amount(self):
        return self.amount - self.tds_amount
class CompanyAccount(models.Model):
    """The business behind the master account: its legal details and the bank account creator money is kept in. Only ever one row."""
    ACCOUNT_TYPES = [("current", "Current account"), ("savings", "Savings account")]
    business_name = models.CharField(max_length=150, blank=True, help_text="Registered name of the business")
    pan = models.CharField(max_length=10, blank=True, help_text="Business PAN")
    gstin = models.CharField(max_length=15, blank=True)
    billing_email = models.EmailField(blank=True)
    address = models.CharField(max_length=300, blank=True)
    account_holder = models.CharField(max_length=150, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=18, blank=True)
    ifsc = models.CharField(max_length=11, blank=True)
    branch = models.CharField(max_length=100, blank=True)
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPES, default="current")
    upi_id = models.CharField(max_length=100, blank=True, help_text="UPI ID linked to this account, for quick top-ups")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    class Meta:
        verbose_name_plural = "company account"
    @classmethod
    def current(cls):
        return cls.objects.get_or_create(pk=1)[0]
    @property
    def is_set_up(self):
        return bool(self.business_name and self.account_number and self.ifsc)
    @property
    def masked_account(self):
        return f"••••{self.account_number[-4:]}" if self.account_number else ""
class TreasuryEntry(models.Model):
    """The master account: money the owner adds, takes back, or pays out to creators."""
    KINDS = [("deposit", "Money added"), ("withdrawal", "Money taken out"), ("payout", "Creator payout"), ("tax", "Tax paid to government")]
    METHODS = [("neft", "NEFT / RTGS"), ("imps", "IMPS"), ("upi", "UPI"), ("cheque", "Cheque"), ("cash", "Cash deposit")]
    SOURCES = [("founders", "Founders' own money"), ("investors", "Investors"), ("revenue", "Business revenue"), ("loan", "Loan"), ("other", "Other")]
    kind = models.CharField(max_length=20, choices=KINDS)
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Always positive; the kind decides the direction")
    entry_date = models.DateField(default=timezone.localdate, help_text="When the money actually moved")
    method = models.CharField(max_length=10, choices=METHODS, blank=True)
    source = models.CharField(max_length=10, choices=SOURCES, blank=True, help_text="Where added money came from")
    reference = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=200, blank=True)
    payout = models.OneToOneField(PayoutRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="treasury_entry")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-entry_date", "-created_at"]
        verbose_name_plural = "treasury entries"
class RevenueEntry(models.Model):
    """Money the company earned, recorded by finance for the revenue report. Money moved into the master account is not revenue."""
    SOURCES = [("recruiters", "Recruiter plans"), ("ads", "Advertising"), ("sponsorships", "Sponsorships"), ("services", "Services"), ("other", "Other")]
    source = models.CharField(max_length=20, choices=SOURCES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    received_on = models.DateField()
    reference = models.CharField(max_length=100, blank=True, help_text="Invoice number or bank reference")
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-received_on", "-id"]
        verbose_name_plural = "revenue entries"
class FinanceAuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=60)
    details = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
