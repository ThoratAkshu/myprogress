"""The earning engine: coins for posts, the follower milestone, coin conversion, payouts, and the master account."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone
from apps.core.models import EarningTransaction
from apps.notifications.services import notify
from .models import CoinTransaction, CreatorAccount, EarningSettings, FinanceAuditLog, PayoutRequest, TreasuryEntry
UPI_PATTERN = re.compile(r"^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$")
ZERO = Decimal("0")
PENDING_MESSAGE = "You already have a withdrawal in progress. You can request another once it's paid."
class PayoutError(Exception):
    """A withdrawal that can't go ahead, with a message safe to show the creator."""
def earnings_url():
    return reverse("landing:workspace_section", args=["earnings"])
def rupees(amount):
    """Indian-style grouping: ₹1,25,000 for whole amounts, ₹10.50 otherwise."""
    amount = Decimal(amount or 0).quantize(Decimal("0.01"))
    whole, _, paise = f"{abs(amount):.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    grouped = ",".join(groups + [tail])
    return f"{'-' if amount < 0 else ''}₹{grouped}" + ("" if paise == "00" else f".{paise}")
def account_for(user):
    return CreatorAccount.objects.get_or_create(user=user)[0]
def log(actor, action, details):
    FinanceAuditLog.objects.create(actor=actor, action=action, details=details[:300])
def coin_balance(user):
    return CoinTransaction.objects.filter(user=user).aggregate(total=Sum("amount"))["total"] or 0
def rupee_balance(user):
    """Money in the creator's wallet: credits and adjustments, minus withdrawals (pending ones included)."""
    totals = EarningTransaction.objects.filter(user=user).aggregate(
        added=Sum("amount", filter=Q(transaction_type__in=["credit", "adjustment"])), taken=Sum("amount", filter=Q(transaction_type="payout")))
    return (totals["added"] or ZERO) - (totals["taken"] or ZERO)
def follower_count(user, rules=None):
    rules = rules or EarningSettings.current()
    followers = user.follower_relationships.all()
    if rules.confirmed_followers_only:
        followers = followers.filter(follower__profile__email_verified_at__isnull=False)
    return followers.count()
def is_earning(account, rules):
    return bool(rules.program_enabled and account.eligible_since and not account.suspended)

def settle(user):
    """Turn every full block of coins into rupees, for creators who have unlocked earnings. Returns rupees added."""
    rules = EarningSettings.current()
    with transaction.atomic():
        account = CreatorAccount.objects.select_for_update().get(pk=account_for(user).pk)
        if not is_earning(account, rules) or not rules.coins_per_conversion:
            return ZERO
        blocks = coin_balance(user) // rules.coins_per_conversion
        if blocks <= 0:
            return ZERO
        coins, amount = blocks * rules.coins_per_conversion, rules.rupees_per_conversion * blocks
        CoinTransaction.objects.create(user=user, amount=-coins, kind="conversion", description=f"Converted {coins} coins to {rupees(amount)}")
        EarningTransaction.objects.create(user=user, transaction_type="credit", amount=amount, description=f"{coins} coins converted")
    notify(user, None, "earnings", f"Your {coins} coins just became {rupees(amount)} in your wallet.", earnings_url())
    return amount

def refresh_creator(user):
    """Unlock earnings, and pay the one-time bonus, the first time a creator reaches the follower goal."""
    rules = EarningSettings.current()
    if not rules.program_enabled:
        return
    unlocked = False
    with transaction.atomic():
        account = CreatorAccount.objects.select_for_update().get(pk=account_for(user).pk)
        if account.eligible_since is None and follower_count(user, rules) >= rules.follower_goal:
            now = timezone.now()
            account.eligible_since = now
            if account.follower_bonus_paid_at is None and rules.follower_bonus > 0:
                EarningTransaction.objects.create(user=user, transaction_type="credit", amount=rules.follower_bonus, description=f"Bonus for reaching {rules.follower_goal} followers")
                account.follower_bonus_paid_at = now
            account.save(update_fields=["eligible_since", "follower_bonus_paid_at"])
            unlocked = True
    if unlocked:
        bonus = f" and {rupees(rules.follower_bonus)} was added to your wallet" if rules.follower_bonus > 0 else ""
        notify(user, None, "earnings", f"You reached {rules.follower_goal} followers! Earnings are unlocked{bonus}.", earnings_url())
        settle(user)

def post_coins(post, rules):
    return rules.coins_per_video if post.kind == "video" else rules.coins_per_article
def _post_net(post):
    return CoinTransaction.objects.filter(post=post).aggregate(total=Sum("amount"))["total"] or 0
def sync_post_coins(post):
    """Give coins once for a public post, and take them back if it's unpublished. Returns the coins given."""
    rules = EarningSettings.current()
    net = _post_net(post)
    if post.is_public and net <= 0 and rules.program_enabled:
        today = CoinTransaction.objects.filter(user=post.author, kind="post", created_at__date=timezone.localdate()).count()
        coins = post_coins(post, rules)
        if today >= rules.daily_post_limit or not coins:
            return 0
        label = "Video" if post.kind == "video" else "Article"
        CoinTransaction.objects.create(user=post.author, amount=coins, kind="post", post=post, description=f"{label}: {post.title}"[:200])
        settle(post.author)
        return coins
    if not post.is_public and net > 0:
        CoinTransaction.objects.create(user=post.author, amount=-net, kind="reversal", post=post, description=f"Unpublished: {post.title}"[:200])
    return 0
def reverse_post_coins(post):
    """Take back a post's coins when it's deleted, so posting and deleting can't farm coins."""
    net = _post_net(post)
    if net > 0:
        CoinTransaction.objects.create(user=post.author, amount=-net, kind="reversal", post=post, description=f"Deleted: {post.title}"[:200])

def request_payout(user, amount, upi_id, payout_name):
    """Reserve money from the wallet for a withdrawal the finance team will send."""
    rules = EarningSettings.current()
    account = account_for(user)
    if not is_earning(account, rules):
        raise PayoutError("Withdrawals open once your earnings are unlocked." if not account.suspended else "Withdrawals are paused on your account. Contact support.")
    try:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise PayoutError("Enter an amount in rupees, like 100.")
    upi_id, payout_name = upi_id.strip(), payout_name.strip()
    if PayoutRequest.objects.filter(user=user, status="pending").exists():
        raise PayoutError(PENDING_MESSAGE)
    if amount < rules.minimum_payout:
        raise PayoutError(f"The smallest withdrawal is {rupees(rules.minimum_payout)}.")
    if amount > rupee_balance(user):
        raise PayoutError("That's more than your wallet balance.")
    if not UPI_PATTERN.match(upi_id):
        raise PayoutError("Enter a UPI ID like name@okbank.")
    if not payout_name:
        raise PayoutError("Enter the name on your bank account.")
    with transaction.atomic():
        if PayoutRequest.objects.select_for_update().filter(user=user, status="pending").exists():
            raise PayoutError(PENDING_MESSAGE)
        payout = PayoutRequest.objects.create(user=user, amount=amount, upi_id=upi_id, payout_name=payout_name[:120])
        EarningTransaction.objects.create(user=user, transaction_type="payout", amount=amount, description=f"Withdrawal to {upi_id}")
        account.upi_id, account.payout_name = upi_id, payout_name[:120]
        account.save(update_fields=["upi_id", "payout_name"])
    return payout
def mark_payout_paid(payout, actor, reference):
    with transaction.atomic():
        payout = PayoutRequest.objects.select_for_update().get(pk=payout.pk)
        if payout.status != "pending":
            raise PayoutError("This withdrawal was already processed.")
        payout.status, payout.processed_at, payout.processed_by, payout.reference = "paid", timezone.now(), actor, reference.strip()[:100]
        payout.save(update_fields=["status", "processed_at", "processed_by", "reference"])
        TreasuryEntry.objects.create(kind="payout", amount=payout.amount, reference=payout.reference, payout=payout, created_by=actor, note=f"Payout to {payout.user.get_full_name() or payout.user.email}"[:200])
        log(actor, "payout_paid", f"Paid {rupees(payout.amount)} to {payout.user.email} ({payout.upi_id}), reference {payout.reference or 'none'}")
    notify(payout.user, None, "earnings", f"{rupees(payout.amount)} was sent to {payout.upi_id}.", earnings_url())
    return payout
def reject_payout(payout, actor, reason):
    with transaction.atomic():
        payout = PayoutRequest.objects.select_for_update().get(pk=payout.pk)
        if payout.status != "pending":
            raise PayoutError("This withdrawal was already processed.")
        payout.status, payout.processed_at, payout.processed_by, payout.note = "rejected", timezone.now(), actor, reason.strip()[:200]
        payout.save(update_fields=["status", "processed_at", "processed_by", "note"])
        EarningTransaction.objects.create(user=payout.user, transaction_type="adjustment", amount=payout.amount, description="Withdrawal returned to your wallet")
        log(actor, "payout_rejected", f"Returned {rupees(payout.amount)} to {payout.user.email}: {payout.note or 'no reason given'}")
    notify(payout.user, None, "earnings", f"Your withdrawal of {rupees(payout.amount)} was returned to your wallet. {payout.note}".strip(), earnings_url())
    return payout
def adjust(user, actor, coins=0, amount=ZERO, reason=""):
    """A manual correction by the finance team: add or remove coins or rupees, with a reason."""
    if coins:
        CoinTransaction.objects.create(user=user, amount=coins, kind="adjustment", description=reason[:200] or "Adjustment by MyProgress")
    if amount:
        EarningTransaction.objects.create(user=user, transaction_type="adjustment", amount=amount, description=reason[:180] or "Adjustment by MyProgress")
    changes = ([f"{coins:+d} coins"] if coins else []) + ([f"{'+' if amount > 0 else ''}{rupees(amount)}"] if amount else [])
    log(actor, "adjustment", f"{user.email}: {', '.join(changes)}. {reason}")
    if coins > 0:
        settle(user)

def treasury_balance():
    totals = TreasuryEntry.objects.aggregate(added=Sum("amount", filter=Q(kind="deposit")), taken=Sum("amount", filter=Q(kind__in=["withdrawal", "payout"])))
    return (totals["added"] or ZERO) - (totals["taken"] or ZERO)
def owed_to_creators():
    """Wallet balances plus withdrawals waiting to be sent: what the master account must be able to cover."""
    totals = EarningTransaction.objects.aggregate(added=Sum("amount", filter=Q(transaction_type__in=["credit", "adjustment"])), taken=Sum("amount", filter=Q(transaction_type="payout")))
    pending = PayoutRequest.objects.filter(status="pending").aggregate(total=Sum("amount"))["total"] or ZERO
    return (totals["added"] or ZERO) - (totals["taken"] or ZERO) + pending

def _monthly(user, months=6):
    """Coins from posts and rupees credited in each of the last few months, for the chart."""
    first = timezone.localdate().replace(day=1)
    rows = []
    for back in range(months - 1, -1, -1):
        year, month = divmod(first.year * 12 + first.month - 1 - back, 12)
        rows.append({"key": (year, month + 1), "label": date(year, month + 1, 1).strftime("%b"), "coins": 0, "rupees": ZERO})
    by_key = {row["key"]: row for row in rows}
    since = date(*rows[0]["key"], 1)
    coin_rows = CoinTransaction.objects.filter(user=user, kind="post", amount__gt=0, created_at__date__gte=since).annotate(month=TruncMonth("created_at")).values("month").annotate(total=Sum("amount"))
    money_rows = EarningTransaction.objects.filter(user=user, transaction_type="credit", created_at__date__gte=since).annotate(month=TruncMonth("created_at")).values("month").annotate(total=Sum("amount"))
    for field, source in (("coins", coin_rows), ("rupees", money_rows)):
        for row in source:
            key = (row["month"].year, row["month"].month)
            if key in by_key:
                by_key[key][field] = row["total"]
    peak = max([row["coins"] for row in rows] + [1])
    for row in rows:
        row["height"] = round(row["coins"] * 100 / peak)
    return rows
def creator_dashboard(user):
    """Everything the creator earnings page shows."""
    rules = EarningSettings.current()
    account = account_for(user)
    followers = follower_count(user, rules)
    earning = is_earning(account, rules)
    coins = coin_balance(user)
    per = max(rules.coins_per_conversion, 1)
    in_block = max(coins, 0) % per
    to_next = per - in_block
    wallet = rupee_balance(user)
    money = EarningTransaction.objects.filter(user=user)
    lifetime = money.filter(Q(transaction_type="credit") | Q(transaction_type="adjustment", amount__gt=0)).aggregate(total=Sum("amount"))["total"] or ZERO
    coins_earned = CoinTransaction.objects.filter(user=user, kind="post", amount__gt=0).aggregate(total=Sum("amount"))["total"] or 0
    payouts = PayoutRequest.objects.filter(user=user)
    posts = user.learning_posts.filter(is_public=True)
    post_count = posts.count()
    paid = payouts.filter(status="paid").aggregate(total=Sum("amount"))["total"] or ZERO
    journey = [
        {"title": "Publish your first post", "detail": f"Articles earn {rules.coins_per_article} coins, videos {rules.coins_per_video}.", "done": post_count > 0},
        {"title": f"Collect {per} coins", "detail": f"Every {per} coins becomes {rupees(rules.rupees_per_conversion)}.", "done": coins_earned >= per},
        {"title": f"Reach {rules.follower_goal} followers", "detail": f"Unlocks earnings and a {rupees(rules.follower_bonus)} bonus." if rules.follower_bonus > 0 else "Unlocks earnings.", "done": account.eligible_since is not None},
        {"title": "Make your first withdrawal", "detail": f"Send your wallet to UPI from {rupees(rules.minimum_payout)}.", "done": paid > 0},
    ]
    next_step = next((index for index, step in enumerate(journey) if not step["done"]), None)
    return {
        "rules": rules, "account": account, "earning": earning, "program_paused": not rules.program_enabled,
        "followers": followers, "follower_percent": min(100, round(followers * 100 / max(rules.follower_goal, 1))), "followers_needed": max(rules.follower_goal - followers, 0),
        "coins": coins, "coins_in_block": in_block, "coins_to_next": to_next, "coin_percent": round(in_block * 100 / per),
        "locked_rupees": rules.rupees_per_conversion * (max(coins, 0) // per) if not earning else ZERO,
        "articles_to_next": -(-to_next // rules.coins_per_article) if rules.coins_per_article else None,
        "videos_to_next": -(-to_next // rules.coins_per_video) if rules.coins_per_video else None,
        "wallet": wallet, "to_minimum": max(rules.minimum_payout - wallet, ZERO), "lifetime": lifetime, "paid_out": paid, "coins_earned": coins_earned,
        "pending_payout": payouts.filter(status="pending").first(), "can_withdraw": earning and wallet >= rules.minimum_payout,
        "coin_history": list(CoinTransaction.objects.filter(user=user)[:8]), "money_history": list(money.order_by("-created_at", "-id")[:8]), "payouts": list(payouts[:6]),
        "months": _monthly(user), "post_count": post_count, "video_count": posts.filter(kind="video").count(),
        "journey": journey, "next_step": next_step, "journey_done": sum(step["done"] for step in journey),
    }
