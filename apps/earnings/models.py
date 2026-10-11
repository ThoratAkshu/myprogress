"""Creator earnings: the rules, coins, payouts, and the platform's master (treasury) account."""
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import models
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
    minimum_payout = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("100"), help_text="Smallest withdrawal in rupees")
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
    upi_id = models.CharField(max_length=100, blank=True)
    payout_name = models.CharField(max_length=120, blank=True)
    def __str__(self):
        return f"Creator account of {self.user}"
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
class PayoutRequest(models.Model):
    STATUSES = [("pending", "Pending"), ("paid", "Paid"), ("rejected", "Rejected")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payout_requests")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    upi_id = models.CharField(max_length=100)
    payout_name = models.CharField(max_length=120)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reference = models.CharField(max_length=100, blank=True, help_text="UPI or bank transfer reference (UTR)")
    note = models.CharField(max_length=200, blank=True)
    class Meta:
        ordering = ["-requested_at"]
class TreasuryEntry(models.Model):
    """The master account: money the owner adds, takes back, or pays out to creators."""
    KINDS = [("deposit", "Money added"), ("withdrawal", "Money taken out"), ("payout", "Creator payout")]
    kind = models.CharField(max_length=20, choices=KINDS)
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Always positive; the kind decides the direction")
    reference = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=200, blank=True)
    payout = models.OneToOneField(PayoutRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="treasury_entry")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "treasury entries"
class FinanceAuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=60)
    details = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
