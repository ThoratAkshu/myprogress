"""The earning engine: coins for posts, the follower milestone, coin conversion, monthly payments, and the master account."""
from apps.accounts.access import user_role
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone
from apps.core.models import EarningTransaction
from apps.notifications.services import notify
from .models import CoinTransaction, CreatorAccount, EarningSettings, FinanceAuditLog, PaymentRun, PayoutRequest, TreasuryEntry
from .payouts import ProviderError, RazorpayX, get_provider
ZERO = Decimal("0")
ADDS = ["credit", "adjustment", "refund"]
BONUS_PREFIX = "Bonus for reaching"
class PayoutError(Exception):
    """A payment step that can't go ahead, with a message safe to show."""
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
def _balance(entries):
    totals = entries.aggregate(added=Sum("amount", filter=Q(transaction_type__in=ADDS)), taken=Sum("amount", filter=Q(transaction_type="payout")))
    return (totals["added"] or ZERO) - (totals["taken"] or ZERO)
def rupee_balance(user):
    """Money in the creator's balance: credits, adjustments and returned payments, minus payments."""
    return _balance(EarningTransaction.objects.filter(user=user))
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
                EarningTransaction.objects.create(user=user, transaction_type="credit", amount=rules.follower_bonus, description=f"{BONUS_PREFIX} {rules.follower_goal} followers")
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
    # Earnings are a developer's: institutes and recruiters have no earnings page, so their posts don't earn coins.
    if post.is_public and net <= 0 and rules.program_enabled and user_role(post.author) == "developer":
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

def next_month(first):
    year, month = divmod(first.year * 12 + first.month, 12)
    return date(year, month + 1, 1)
def previous_month(first):
    year, month = divmod(first.year * 12 + first.month - 2, 12)
    return date(year, month + 1, 1)
def payment_date(month, rules):
    """Earnings for a month are paid on payment day of the month after, like YouTube's payment around the 21st."""
    return next_month(month).replace(day=min(max(rules.payout_day, 1), 28))
def _midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))
def closed_balance(user, cutoff):
    """What a creator can be paid for months that ended before `cutoff`: their balance then, never more than now."""
    then = _balance(EarningTransaction.objects.filter(user=user, created_at__lt=_midnight(cutoff)))
    return max(min(then, rupee_balance(user)), ZERO)
def tax_for(amount, rules):
    return (amount * rules.tds_percent / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def payment_holds(account, rules):
    """Why a creator wouldn't be paid, each with what they can do about it. An empty list means they will be paid."""
    holds = []
    if not rules.program_enabled:
        holds.append({"code": "paused", "text": "The creator program is paused. Your balance is safe."})
    if account.eligible_since is None:
        holds.append({"code": "locked", "text": f"Payments start once you reach {rules.follower_goal} followers."})
    if account.suspended:
        holds.append({"code": "suspended", "text": "Payments are paused on your account. Contact support."})
    if account.hold_payments:
        holds.append({"code": "creator_hold", "text": "You chose to hold payments. Your balance keeps adding up until you turn this off."})
    if not account.payout_name or not account.destination:
        holds.append({"code": "details", "text": "Add your payment details: your legal name and a UPI ID or bank account."})
    if rules.require_pan and not account.pan:
        holds.append({"code": "pan", "text": "Add your PAN. It's needed for tax before we can pay you."})
    last = PayoutRequest.objects.filter(user=account.user).first()
    if last and last.status == "rejected" and (account.details_updated_at is None or account.details_updated_at < (last.processed_at or last.requested_at)):
        holds.append({"code": "failed", "text": f"Your last payment didn't go through{': ' + last.note if last.note else ''}. Check your payment details."})
    return holds
HOLD_LABELS = {"paused": "Program paused", "locked": "Not unlocked", "suspended": "Paused by finance", "creator_hold": "Creator is holding", "details": "No payment details", "pan": "No PAN", "failed": "Last payment failed"}
def payment_candidates(month, rules=None):
    """For a finished month: who would be paid and how much, who is on hold and why, and who is under the threshold."""
    rules = rules or EarningSettings.current()
    cutoff = next_month(month)
    already = set(PayoutRequest.objects.filter(run__month=month).values_list("user_id", flat=True))
    result = {"to_pay": [], "held": [], "below": []}
    for user in User.objects.filter(earning_transactions__created_at__lt=_midnight(cutoff)).exclude(pk__in=already).distinct().select_related("creator_account", "profile"):
        amount = closed_balance(user, cutoff)
        if amount <= 0:
            continue
        account = account_for(user)
        holds = payment_holds(account, rules)
        row = {"user": user, "account": account, "amount": amount, "tds": tax_for(amount, rules), "holds": holds, "hold_labels": [HOLD_LABELS[hold["code"]] for hold in holds]}
        row["net"] = amount - row["tds"]
        result["held" if holds else "below" if amount < rules.minimum_payout else "to_pay"].append(row)
    for key in result:
        result[key].sort(key=lambda row: -row["amount"])
    result["total"] = sum((row["amount"] for row in result["to_pay"]), ZERO)
    result["total_tds"] = sum((row["tds"] for row in result["to_pay"]), ZERO)
    result["total_net"] = result["total"] - result["total_tds"]
    return result

def close_month(month, actor=None, today=None):
    """Close a finished month: schedule its payment run and tell each creator what they earned. Safe to call again."""
    rules = EarningSettings.current()
    if next_month(month) > (today or timezone.localdate()):
        raise PayoutError("A month can only be closed after it ends.")
    run, created = PaymentRun.objects.get_or_create(month=month, defaults={"scheduled_for": payment_date(month, rules)})
    if not created:
        return run, False
    log(actor, "month_closed", f"{month:%B %Y} closed. Payments go out on {run.scheduled_for:%B} {run.scheduled_for.day}.")
    earned = EarningTransaction.objects.filter(created_at__gte=_midnight(month), created_at__lt=_midnight(next_month(month))).filter(Q(transaction_type="credit") | Q(transaction_type="adjustment", amount__gt=0)).values("user").annotate(total=Sum("amount"))
    for row in earned:
        user = User.objects.get(pk=row["user"])
        balance = closed_balance(user, next_month(month))
        holds = payment_holds(account_for(user), rules)
        if holds:
            then = f" To get paid: {holds[0]['text'][0].lower()}{holds[0]['text'][1:]}"
        elif balance >= rules.minimum_payout:
            then = f" {rupees(balance)} will be paid around {run.scheduled_for:%B} {run.scheduled_for.day}."
        else:
            then = f" We pay once your balance reaches {rupees(rules.minimum_payout)}; it carries over until then."
        notify(user, None, "earnings", f"Your {month:%B} earnings are final: {rupees(row['total'])}.{then}", earnings_url())
    return run, True
def prepare_run(run, actor=None):
    """Payment day: move each eligible creator's closed balance out of their wallet into a payment."""
    rules = EarningSettings.current()
    with transaction.atomic():
        run = PaymentRun.objects.select_for_update().get(pk=run.pk)
        if run.status != "scheduled":
            raise PayoutError("These payments were already prepared.")
        candidates = payment_candidates(run.month, rules)
        payouts = []
        for row in candidates["to_pay"]:
            account = row["account"]
            payouts.append(PayoutRequest.objects.create(run=run, user=row["user"], amount=row["amount"], tds_amount=row["tds"], destination=account.destination, upi_id=account.upi_id if account.payout_method == "upi" else "", payout_name=account.payout_name))
            EarningTransaction.objects.create(user=row["user"], transaction_type="payout", amount=row["amount"], description=f"Payment for {run.month:%B %Y}")
        run.status, run.prepared_at = ("ready" if payouts else "completed"), timezone.now()
        run.save(update_fields=["status", "prepared_at"])
        log(actor, "payments_prepared", f"{run.month:%B %Y}: {len(payouts)} creators, {rupees(candidates['total'])} including {rupees(candidates['total_tds'])} tax; {len(candidates['held'])} on hold")
    for payout in payouts:
        notify(payout.user, None, "earnings", f"Your {run.month:%B} payment of {rupees(payout.net_amount)} is being sent to {payout.destination}.", earnings_url())
    for row in candidates["held"]:
        if not {"locked", "paused"} & {hold["code"] for hold in row["holds"]}:
            notify(row["user"], None, "earnings", f"We couldn't pay your {rupees(row['amount'])} for {run.month:%B}. {row['holds'][0]['text']}", earnings_url())
    return run, candidates
def available_to_send():
    """Master account money not already promised to payments the provider is still sending."""
    sending = PayoutRequest.objects.filter(status="processing").aggregate(total=Sum("amount"), tax=Sum("tds_amount"))
    return treasury_balance() - ((sending["total"] or ZERO) - (sending["tax"] or ZERO))
def send_run(run, actor=None):
    """Send every waiting payment in a run through the payout provider. Returns (sent, failures)."""
    provider = get_provider()
    if provider is None:
        raise PayoutError("No payout provider is connected. Send each payment from your bank, then mark it paid with its reference.")
    waiting = list(run.payouts.filter(status="pending").select_related("user"))
    if not waiting:
        raise PayoutError("Nothing is waiting to be sent.")
    needed, available = sum((payout.net_amount for payout in waiting), ZERO), available_to_send()
    if needed > available:
        raise PayoutError(f"These payments need {rupees(needed)} but the master account has {rupees(available)} free. Add money first.")
    run.status, run.approved_at, run.approved_by = "sending", timezone.now(), actor
    run.save(update_fields=["status", "approved_at", "approved_by"])
    sent, failures = 0, []
    for payout in waiting:
        try:
            result = provider.send(payout, account_for(payout.user))
        except ProviderError as error:
            payout.note = str(error)[:200]
            payout.save(update_fields=["note"])
            failures.append((payout, str(error)))
            continue
        payout.status, payout.provider_payout_id, payout.note = "processing", result["id"][:40], ""
        payout.save(update_fields=["status", "provider_payout_id", "note"])
        sent += 1
        apply_provider_status(payout, result["status"], result["utr"])
    log(actor, "payments_sent", f"{run.month:%B %Y}: {sent} sent through {provider.name}, {len(failures)} failed")
    finish_run(run)
    return sent, failures
def apply_provider_status(payout, status, utr="", reason=""):
    """Record what the provider says happened to a payment."""
    payout.refresh_from_db()
    if payout.status not in {"pending", "processing"}:
        return
    if status == "processed":
        mark_payout_paid(payout, None, utr or payout.provider_payout_id)
    elif status in RazorpayX.FAILED:
        reject_payout(payout, None, reason or "The bank couldn't complete this payment.")
def handle_provider_event(payload):
    """A RazorpayX webhook. Returns True when it matched one of our payments."""
    entity = ((payload.get("payload") or {}).get("payout") or {}).get("entity") or {}
    reference = str(entity.get("reference_id") or "")
    payout = PayoutRequest.objects.filter(provider_payout_id=entity.get("id") or "-").first()
    if payout is None and reference.startswith("payout-") and reference[7:].isdigit():
        payout = PayoutRequest.objects.filter(pk=int(reference[7:])).first()
    if payout is None:
        return False
    reason = (entity.get("status_details") or {}).get("description") or entity.get("failure_reason") or ""
    apply_provider_status(payout, entity.get("status", ""), entity.get("utr") or "", reason)
    return True
def sync_sending():
    """Ask the provider about payments still sending, in case a webhook was missed."""
    provider = get_provider()
    if provider is None:
        return 0
    checked = 0
    for payout in PayoutRequest.objects.filter(status="processing").exclude(provider_payout_id=""):
        try:
            result = provider.fetch(payout.provider_payout_id)
        except ProviderError:
            continue
        apply_provider_status(payout, result["status"], result["utr"], result["reason"])
        checked += 1
    return checked
def finish_run(run):
    if run and run.status in {"ready", "sending"} and not run.payouts.filter(status__in=["pending", "processing"]).exists():
        run.status = "completed"
        run.save(update_fields=["status"])

def mark_payout_paid(payout, actor, reference):
    with transaction.atomic():
        payout = PayoutRequest.objects.select_for_update().get(pk=payout.pk)
        if payout.status not in {"pending", "processing"}:
            raise PayoutError("This payment was already processed.")
        payout.status, payout.processed_at, payout.processed_by, payout.reference = "paid", timezone.now(), actor, reference.strip()[:100]
        payout.save(update_fields=["status", "processed_at", "processed_by", "reference"])
        TreasuryEntry.objects.create(kind="payout", amount=payout.net_amount, reference=payout.reference, payout=payout, created_by=actor, note=f"Payment to {payout.payout_name or payout.user.email}"[:200])
        log(actor, "payout_paid", f"Paid {rupees(payout.net_amount)} to {payout.user.email} ({payout.destination}), tax {rupees(payout.tds_amount)}, reference {payout.reference or 'none'}")
    tax = f" after {rupees(payout.tds_amount)} tax" if payout.tds_amount else ""
    notify(payout.user, None, "earnings", f"{rupees(payout.net_amount)} was sent to {payout.destination}{tax}.", earnings_url())
    finish_run(payout.run)
    return payout
def reject_payout(payout, actor, reason):
    """Cancel a payment that can't go through and put the money back in the creator's balance."""
    with transaction.atomic():
        payout = PayoutRequest.objects.select_for_update().get(pk=payout.pk)
        if payout.status not in {"pending", "processing"}:
            raise PayoutError("This payment was already processed.")
        payout.status, payout.processed_at, payout.processed_by, payout.note = "rejected", timezone.now(), actor, reason.strip()[:200]
        payout.save(update_fields=["status", "processed_at", "processed_by", "note"])
        EarningTransaction.objects.create(user=payout.user, transaction_type="refund", amount=payout.amount, description="Payment returned to your balance")
        log(actor, "payout_returned", f"Returned {rupees(payout.amount)} to {payout.user.email}: {payout.note or 'no reason given'}")
    notify(payout.user, None, "earnings", f"Your payment of {rupees(payout.net_amount)} couldn't be sent and is back in your balance. {payout.note}".strip(), earnings_url())
    finish_run(payout.run)
    return payout
def save_payment_details(account, data):
    """Store the creator's payment profile; new destination details mean a new fund account at the provider."""
    destination_before = (account.payout_method, account.upi_id, account.bank_account, account.ifsc, account.payout_name)
    account.payout_name, account.pan, account.payout_method = data["payout_name"], data["pan"], data["payout_method"]
    account.upi_id, account.bank_account, account.ifsc = data["upi_id"], data["bank_account"], data["ifsc"]
    account.hold_payments = data["hold_payments"]
    fields = ["payout_name", "pan", "payout_method", "upi_id", "bank_account", "ifsc", "hold_payments"]
    if destination_before != (account.payout_method, account.upi_id, account.bank_account, account.ifsc, account.payout_name):
        account.details_updated_at, account.provider_fund_account_id = timezone.now(), ""
        fields += ["details_updated_at", "provider_fund_account_id"]
        log(account.user, "payment_details_changed", f"{account.user.email} now paid to {account.destination}, PAN {account.masked_pan or 'not given'}")
    elif account.details_updated_at is None:
        account.details_updated_at = timezone.now()
        fields.append("details_updated_at")
    account.save(update_fields=fields)
    return account

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
    totals = TreasuryEntry.objects.aggregate(added=Sum("amount", filter=Q(kind="deposit")), taken=Sum("amount", filter=Q(kind__in=["withdrawal", "payout", "tax"])))
    return (totals["added"] or ZERO) - (totals["taken"] or ZERO)
def owed_to_creators():
    """Every creator balance plus payments not yet sent: what the master account must be able to cover."""
    waiting = PayoutRequest.objects.filter(status__in=["pending", "processing"]).aggregate(total=Sum("amount"))["total"] or ZERO
    return _balance(EarningTransaction.objects.all()) + waiting
def tax_to_deposit():
    """Tax held back from creator payments that hasn't been paid to the government yet."""
    held = PayoutRequest.objects.filter(status="paid").aggregate(total=Sum("tds_amount"))["total"] or ZERO
    paid = TreasuryEntry.objects.filter(kind="tax").aggregate(total=Sum("amount"))["total"] or ZERO
    return held - paid

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
        {"title": "Get your first payment", "detail": f"Paid monthly to UPI or your bank once your balance reaches {rupees(rules.minimum_payout)}.", "done": paid > 0},
    ]
    next_step = next((index for index, step in enumerate(journey) if not step["done"]), None)
    today = timezone.localdate()
    this_month = today.replace(day=1)
    last_run = PaymentRun.objects.filter(month=previous_month(this_month)).first()
    if last_run is None or last_run.status == "scheduled":
        next_date, next_amount, estimated = payment_date(previous_month(this_month), rules), closed_balance(user, this_month), False
    else:
        next_date, next_amount, estimated = payment_date(this_month, rules), wallet, True
    holds = [hold for hold in payment_holds(account, rules) if hold["code"] not in {"locked", "paused"}]
    this_month_earned = money.filter(created_at__gte=_midnight(this_month)).filter(Q(transaction_type="credit") | Q(transaction_type="adjustment", amount__gt=0)).aggregate(total=Sum("amount"))["total"] or ZERO
    return {
        "rules": rules, "account": account, "earning": earning, "program_paused": not rules.program_enabled,
        "followers": followers, "follower_percent": min(100, round(followers * 100 / max(rules.follower_goal, 1))), "followers_needed": max(rules.follower_goal - followers, 0),
        "coins": coins, "coins_in_block": in_block, "coins_to_next": to_next, "coin_percent": round(in_block * 100 / per),
        "locked_rupees": rules.rupees_per_conversion * (max(coins, 0) // per) if not earning else ZERO,
        "articles_to_next": -(-to_next // rules.coins_per_article) if rules.coins_per_article else None,
        "videos_to_next": -(-to_next // rules.coins_per_video) if rules.coins_per_video else None,
        "wallet": wallet, "lifetime": lifetime, "paid_out": paid, "coins_earned": coins_earned, "this_month_earned": this_month_earned,
        "sending_payout": payouts.filter(status__in=["pending", "processing"]).first(), "holds": holds,
        "next_payment": {"date": next_date, "amount": next_amount, "estimated": estimated, "due": next_date <= today, "will_pay": earning and not holds and next_amount >= rules.minimum_payout, "short_by": max(rules.minimum_payout - next_amount, ZERO)},
        "has_details": bool(account.payout_name and account.destination),
        "coin_history": list(CoinTransaction.objects.filter(user=user)[:8]), "money_history": list(money.order_by("-created_at", "-id")[:8]), "payouts": list(payouts.select_related("run")[:12]),
        "months": _monthly(user), "post_count": post_count, "video_count": posts.filter(kind="video").count(),
        "journey": journey, "next_step": next_step, "journey_done": sum(step["done"] for step in journey),
    }
