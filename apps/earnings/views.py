"""Creator payment settings, the RazorpayX webhook, and the owner's finance console with its own sign-in."""
import csv
import json
import time
from datetime import date
from functools import wraps
from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Case, Count, DecimalField, IntegerField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from apps.accounts.forms import EmailLoginForm
from apps.common.ratelimit import client_ip, is_limited, rate_limit, record_hit
from apps.core.models import EarningTransaction
from apps.notifications.services import notify
from . import services
from .forms import AdjustmentForm, EarningSettingsForm, PaymentDetailsForm, TreasuryEntryForm
from .models import CoinTransaction, CreatorAccount, EarningSettings, FinanceAuditLog, PaymentRun, PayoutRequest, TreasuryEntry
from .payouts import get_provider, valid_webhook
FINANCE_SESSION_KEY = "finance_unlocked_at"
FINANCE_IDLE_SECONDS = 30 * 60
FINANCE_LOGIN_FAILURES, FINANCE_LOGIN_WINDOW = 5, 900

@login_required(login_url="landing:home")
@require_POST
@rate_limit("payment-details", 20, 3600)
def payment_details_view(request):
    account = services.account_for(request.user)
    data = request.POST.copy()
    if data.get("payout_method") == "bank" and not data.get("bank_account", "").strip() and account.bank_account:
        data["bank_account"] = data["bank_account_confirm"] = account.bank_account  # keep the saved number
    form = PaymentDetailsForm(data)
    if form.is_valid():
        account = services.save_payment_details(account, form.cleaned_data)
        messages.success(request, "Payments are on hold, as you asked." if account.hold_payments else f"Payment details saved. We'll pay you at {account.destination}.")
        return redirect(services.earnings_url())
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)
    return redirect(f"{services.earnings_url()}#payment-settings")
@csrf_exempt
@require_POST
def razorpayx_webhook_view(request):
    """Payment status from RazorpayX. Only requests signed with the webhook secret are trusted."""
    if not valid_webhook(request.body, request.headers.get("X-Razorpay-Signature", "")):
        return HttpResponseBadRequest("bad signature")
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("bad payload")
    services.handle_provider_event(payload)
    return HttpResponse("ok")

def can_use_finance(user):
    return bool(user.is_authenticated and user.is_active and (user.is_superuser or (user.is_staff and user.has_perm("earnings.access_finance"))))
def finance_required(view):
    """The console has its own sign-in: a finance-permitted staff account that re-entered its password, locked after 30 idle minutes."""
    @wraps(view)
    @never_cache
    def wrapper(request, *args, **kwargs):
        if not can_use_finance(request.user) or time.time() - request.session.get(FINANCE_SESSION_KEY, 0) > FINANCE_IDLE_SECONDS:
            request.session.pop(FINANCE_SESSION_KEY, None)
            return redirect(f'{reverse("finance:login")}?{urlencode({"next": request.get_full_path()})}')
        request.session[FINANCE_SESSION_KEY] = time.time()
        return view(request, *args, **kwargs)
    return wrapper
def _render(request, template, active, context=None):
    pending = PayoutRequest.objects.filter(status__in=["pending", "processing"])
    return render(request, f"earnings/finance/{template}", {"active": active, "pending_count": pending.count(), "idle_minutes": FINANCE_IDLE_SECONDS // 60, **(context or {})})

@never_cache
def finance_login_view(request):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()) or not next_url.startswith("/finance/"):
        next_url = reverse("finance:overview")
    form = EmailLoginForm(request, request.POST or None, initial={"email": request.user.email if can_use_finance(request.user) else ""})
    if request.method == "POST":
        failures = f"finance-login-fail:{client_ip(request)}"
        if is_limited(failures, FINANCE_LOGIN_FAILURES, FINANCE_LOGIN_WINDOW):
            form.add_error(None, "Too many failed attempts. Wait 15 minutes and try again.")
        elif form.is_valid() and can_use_finance(form.user):
            if request.user != form.user:
                login(request, form.user)
            else:
                request.session.cycle_key()
            request.session[FINANCE_SESSION_KEY] = time.time()
            services.log(form.user, "signed_in", f"Signed in to the finance console from {client_ip(request)}")
            return redirect(next_url)
        else:
            record_hit(failures, FINANCE_LOGIN_WINDOW)
            if form.is_valid():
                services.log(form.user, "denied", f"Account without finance access tried to sign in from {client_ip(request)}")
                form.add_error(None, "This account can't use the finance console. Ask the owner for finance access.")
    return render(request, "earnings/finance/login.html", {"form": form, "next": next_url, "idle_minutes": FINANCE_IDLE_SECONDS // 60})
@require_POST
def finance_logout_view(request):
    if can_use_finance(request.user):
        services.log(request.user, "signed_out", "Signed out of the finance console")
    logout(request)
    return redirect("finance:login")

@finance_required
def overview_view(request):
    rules = EarningSettings.current()
    balance, owed = services.treasury_balance(), services.owed_to_creators()
    month_start = timezone.localdate().replace(day=1)
    waiting = PayoutRequest.objects.filter(status__in=["pending", "processing"])
    paid_month = PayoutRequest.objects.filter(status="paid", processed_at__date__gte=month_start)
    accounts = CreatorAccount.objects.all()
    credits_month = EarningTransaction.objects.filter(transaction_type="credit", created_at__date__gte=month_start)
    months = []
    for back in range(5, -1, -1):
        year, month = divmod(month_start.year * 12 + month_start.month - 1 - back, 12)
        start = date(year, month + 1, 1)
        entries = TreasuryEntry.objects.filter(created_at__date__gte=start, created_at__date__lt=services.next_month(start))
        months.append({"label": start.strftime("%b"), "deposits": entries.filter(kind="deposit").aggregate(total=Sum("amount"))["total"] or 0, "payouts": entries.filter(kind="payout").aggregate(total=Sum("amount"))["total"] or 0})
    peak = max([max(item["deposits"], item["payouts"]) for item in months] + [1])
    for item in months:
        item["deposit_height"], item["payout_height"] = round(item["deposits"] * 100 / peak), round(item["payouts"] * 100 / peak)
    last_month = services.previous_month(month_start)
    run = PaymentRun.objects.filter(month=last_month).first()
    if run is None or run.status == "scheduled":
        preview = services.payment_candidates(last_month, rules)
        next_run = {"month": last_month, "date": run.scheduled_for if run else services.payment_date(last_month, rules), "count": len(preview["to_pay"]), "total": preview["total"], "held": len(preview["held"])}
    else:
        next_run = {"month": month_start, "date": services.payment_date(month_start, rules), "count": None, "total": None, "held": None}
    return _render(request, "overview.html", "overview", {
        "rules": rules, "balance": balance, "owed": owed, "cover": balance - owed, "shortfall": max(owed - balance, 0), "tax_due": services.tax_to_deposit(),
        "pending_total": waiting.aggregate(total=Sum("amount"))["total"] or 0, "pending_list": waiting.select_related("user__profile", "run")[:5],
        "paid_month_total": paid_month.aggregate(total=Sum("amount"))["total"] or 0, "paid_month_count": paid_month.count(),
        "earned_month": credits_month.aggregate(total=Sum("amount"))["total"] or 0, "next_run": next_run,
        "earning_creators": accounts.filter(eligible_since__isnull=False, suspended=False).count(), "new_creators": accounts.filter(eligible_since__date__gte=month_start).count(),
        "suspended_creators": accounts.filter(suspended=True).count(), "coins_out": CoinTransaction.objects.aggregate(total=Sum("amount"))["total"] or 0,
        "months": months, "recent_log": FinanceAuditLog.objects.select_related("actor")[:6],
    })

def _payments_url(run=None, status=None):
    query = {key: value for key, value in {"run": run.pk if run else None, "status": status}.items() if value}
    return f'{reverse("finance:payouts")}{"?" + urlencode(query) if query else ""}'
@finance_required
def payouts_view(request):
    """Payment runs: one per month, closed on the 1st and paid on payment day, like YouTube's AdSense payments."""
    rules = EarningSettings.current()
    today = timezone.localdate()
    last_month = services.previous_month(today.replace(day=1))
    runs = PaymentRun.objects.annotate(count=Count("payouts"), total=Sum("payouts__amount"))
    run = runs.filter(pk=request.GET["run"]).first() if request.GET.get("run", "").isdigit() else runs.filter(month=last_month).first() or runs.first()
    preview = services.payment_candidates(run.month if run else last_month, rules) if run is None or run.status == "scheduled" else None
    status = request.GET.get("status") if request.GET.get("status") in {"pending", "processing", "paid", "rejected"} else "all"
    payouts = run.payouts.select_related("user__profile", "processed_by").order_by(Case(When(status="pending", then=0), When(status="processing", then=1), default=2), "-amount") if run else PayoutRequest.objects.none()
    counts = dict(payouts.order_by().values_list("status").annotate(total=Count("id"))) if run else {}
    if status != "all":
        payouts = payouts.filter(status=status)
    waiting = run.payouts.filter(status="pending") if run else PayoutRequest.objects.none()
    waiting_net = sum((payout.net_amount for payout in waiting), services.ZERO)
    available = services.available_to_send()
    provider = get_provider()
    return _render(request, "payouts.html", "payouts", {
        "rules": rules, "run": run, "runs": runs[:12], "last_month": last_month, "last_month_closed": PaymentRun.objects.filter(month=last_month).exists(),
        "preview": preview, "status": status, "page": Paginator(payouts, 25).get_page(request.GET.get("page")), "counts": counts,
        "waiting_count": waiting.count(), "waiting_net": waiting_net, "available": available, "send_shortfall": max(waiting_net - available, 0), "balance": services.treasury_balance(),
        "pager_extra": urlencode({"run": run.pk, **({"status": status} if status != "all" else {})}) if run else "",
        "provider": provider, "webhook_url": request.build_absolute_uri(reverse("finance:razorpayx_webhook")), "today": today,
    })
@finance_required
@require_POST
def close_month_view(request):
    try:
        run, _ = services.close_month(services.previous_month(timezone.localdate().replace(day=1)), request.user)
        messages.success(request, f"{run.month:%B} is closed. Creators were told what they earned.")
        return redirect(_payments_url(run))
    except services.PayoutError as error:
        messages.error(request, str(error))
    return redirect("finance:payouts")
@finance_required
@require_POST
def prepare_run_view(request, run_id):
    run = get_object_or_404(PaymentRun, pk=run_id)
    try:
        run, candidates = services.prepare_run(run, request.user)
        messages.success(request, f"{len(candidates['to_pay'])} payment{'' if len(candidates['to_pay']) == 1 else 's'} ready, {services.rupees(candidates['total_net'])} to send." if candidates["to_pay"] else "Nobody was due a payment this month.")
    except services.PayoutError as error:
        messages.error(request, str(error))
    return redirect(_payments_url(run))
@finance_required
@require_POST
def send_run_view(request, run_id):
    run = get_object_or_404(PaymentRun, pk=run_id)
    try:
        sent, failures = services.send_run(run, request.user)
        messages.success(request, f"{sent} payment{'' if sent == 1 else 's'} sent to {get_provider().name}." + (f" {len(failures)} failed: {failures[0][1]}" if failures else ""))
    except services.PayoutError as error:
        messages.error(request, str(error))
    return redirect(_payments_url(run))
@finance_required
@require_POST
def sync_payments_view(request):
    checked = services.sync_sending()
    messages.success(request, f"Checked {checked} payment{'' if checked == 1 else 's'} with the provider.")
    return redirect(request.POST.get("next") if url_has_allowed_host_and_scheme(request.POST.get("next", ""), allowed_hosts={request.get_host()}) else "finance:payouts")
def _csv_cell(value):
    """Stop spreadsheet apps from running a cell as a formula."""
    value = str(value)
    return f"'{value}" if value[:1] in {"=", "+", "-", "@", "\t", "\r"} else value
@finance_required
def payouts_csv_view(request, run_id):
    """A run's waiting payments as a CSV for a bank or payout provider's bulk upload."""
    run = get_object_or_404(PaymentRun, pk=run_id)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="payments-{run.month:%Y-%m}.csv"'
    writer = csv.writer(response)
    writer.writerow(["payout_id", "name", "method", "upi_id", "account_number", "ifsc", "amount_inr", "tax_inr", "gross_inr", "email"])
    for payout in run.payouts.filter(status="pending").select_related("user__creator_account").order_by("pk"):
        account = payout.user.creator_account
        bank = account.payout_method == "bank" and account.destination == payout.destination
        writer.writerow([payout.pk, _csv_cell(payout.payout_name), "bank" if bank else "upi", _csv_cell(payout.upi_id), _csv_cell(account.bank_account if bank else ""), _csv_cell(account.ifsc if bank else ""), payout.net_amount, payout.tds_amount, payout.amount, _csv_cell(payout.user.email)])
    services.log(request.user, "exported", f"Downloaded the {run.month:%B %Y} payments CSV")
    return response
@finance_required
@require_POST
def payout_paid_view(request, payout_id):
    payout = get_object_or_404(PayoutRequest, pk=payout_id)
    if payout.user == request.user and not request.user.is_superuser:
        messages.error(request, "Another finance admin has to confirm your own payment.")
    else:
        try:
            services.mark_payout_paid(payout, request.user, request.POST.get("reference", ""))
            messages.success(request, f"Marked {services.rupees(payout.net_amount)} to {payout.payout_name} as paid.")
        except services.PayoutError as error:
            messages.error(request, str(error))
    return redirect(_payments_url(payout.run))
@finance_required
@require_POST
def payout_reject_view(request, payout_id):
    payout = get_object_or_404(PayoutRequest, pk=payout_id)
    try:
        services.reject_payout(payout, request.user, request.POST.get("reason", ""))
        messages.success(request, f"Returned {services.rupees(payout.amount)} to {payout.payout_name}'s balance.")
    except services.PayoutError as error:
        messages.error(request, str(error))
    return redirect(_payments_url(payout.run))

@finance_required
def treasury_view(request):
    form = TreasuryEntryForm(request.POST or None)
    balance = services.treasury_balance()
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        if entry.kind in {"withdrawal", "tax"} and entry.amount > balance:
            form.add_error("amount", f"The master account only holds {services.rupees(balance)}.")
        else:
            entry.created_by = request.user
            entry.save()
            services.log(request.user, f"treasury_{entry.kind}", f"{entry.get_kind_display()}: {services.rupees(entry.amount)} {entry.reference}".strip())
            messages.success(request, f"{'Added' if entry.kind == 'deposit' else 'Recorded tax payment of' if entry.kind == 'tax' else 'Took out'} {services.rupees(entry.amount)}.")
            return redirect("finance:treasury")
    totals = TreasuryEntry.objects.values("kind").annotate(total=Sum("amount"))
    owed = services.owed_to_creators()
    return _render(request, "treasury.html", "treasury", {"form": form, "balance": balance, "owed": owed, "shortfall": max(owed - balance, 0), "tax_due": services.tax_to_deposit(), "totals": {row["kind"]: row["total"] for row in totals}, "page": Paginator(TreasuryEntry.objects.select_related("created_by", "payout__user"), 25).get_page(request.GET.get("page"))})

@finance_required
def settings_view(request):
    rules = EarningSettings.current()
    before = {field: getattr(rules, field) for field in EarningSettingsForm.Meta.fields}
    form = EarningSettingsForm(request.POST or None, instance=rules)
    if request.method == "POST" and form.is_valid():
        rules = form.save(commit=False)
        rules.updated_by = request.user
        rules.save()
        changes = [f"{field} {before[field]} → {getattr(rules, field)}" for field in before if before[field] != getattr(rules, field)]
        services.log(request.user, "rules_changed", "; ".join(changes) or "Saved without changes")
        messages.success(request, "Earning rules saved. They apply from now on; past earnings stay as they are.")
        return redirect("finance:settings")
    return _render(request, "settings.html", "settings", {"form": form, "rules": rules})

def _creators():
    coins = CoinTransaction.objects.filter(user=OuterRef("pk")).order_by().values("user").annotate(total=Sum("amount")).values("total")
    added = EarningTransaction.objects.filter(user=OuterRef("pk"), transaction_type__in=["credit", "adjustment"]).order_by().values("user").annotate(total=Sum("amount")).values("total")
    taken = EarningTransaction.objects.filter(user=OuterRef("pk"), transaction_type="payout").order_by().values("user").annotate(total=Sum("amount")).values("total")
    money = DecimalField(max_digits=12, decimal_places=2)
    return User.objects.select_related("profile", "creator_account").annotate(
        coin_total=Coalesce(Subquery(coins, output_field=IntegerField()), Value(0)),
        wallet_total=Coalesce(Subquery(added, output_field=money), Value(0, output_field=money)) - Coalesce(Subquery(taken, output_field=money), Value(0, output_field=money)),
        follower_total=Count("follower_relationships", distinct=True))
@finance_required
def creators_view(request):
    query = request.GET.get("q", "").strip()[:100]
    show = request.GET.get("show") if request.GET.get("show") in {"earning", "locked", "suspended"} else "all"
    creators = _creators()
    if query:
        creators = creators.filter(Q(email__icontains=query) | Q(profile__handle__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))
    else:
        creators = creators.filter(Q(creator_account__isnull=False) | Q(learning_posts__isnull=False)).distinct()
    if show == "earning":
        creators = creators.filter(creator_account__eligible_since__isnull=False, creator_account__suspended=False)
    elif show == "locked":
        creators = creators.filter(Q(creator_account__isnull=True) | Q(creator_account__eligible_since__isnull=True))
    elif show == "suspended":
        creators = creators.filter(creator_account__suspended=True)
    page = Paginator(creators.order_by("-wallet_total", "-coin_total", "pk"), 25).get_page(request.GET.get("page"))
    return _render(request, "creators.html", "creators", {"page": page, "query": query, "show": show, "rules": EarningSettings.current()})
@finance_required
def creator_detail_view(request, user_id):
    creator = get_object_or_404(_creators(), pk=user_id)
    account = services.account_for(creator)
    adjust_form = AdjustmentForm(request.POST or None) if request.POST.get("action") == "adjust" else AdjustmentForm()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "adjust" and adjust_form.is_valid():
            data = adjust_form.cleaned_data
            services.adjust(creator, request.user, coins=data["coins"] or 0, amount=data["amount"] or 0, reason=data["reason"])
            messages.success(request, "Adjustment saved.")
            return redirect("finance:creator", user_id=creator.pk)
        if action in {"suspend", "restore"}:
            account.suspended = action == "suspend"
            account.suspended_reason = request.POST.get("reason", "").strip()[:200] if account.suspended else ""
            account.save(update_fields=["suspended", "suspended_reason"])
            services.log(request.user, "creator_suspended" if account.suspended else "creator_restored", f"{creator.email}: {account.suspended_reason or 'restored'}")
            notify(creator, None, "earnings", "Earnings are paused on your account." + (f" {account.suspended_reason}" if account.suspended_reason else "") if account.suspended else "Earnings are active on your account again.", services.earnings_url())
            if not account.suspended:
                services.settle(creator)
            messages.success(request, "Creator paused." if account.suspended else "Creator restored.")
            return redirect("finance:creator", user_id=creator.pk)
    return _render(request, "creator_detail.html", "creators", {
        "creator": creator, "account": account, "adjust_form": adjust_form, "rules": EarningSettings.current(), "followers": services.follower_count(creator), "holds": services.payment_holds(account, EarningSettings.current()),
        "coin_history": CoinTransaction.objects.filter(user=creator).select_related("post")[:20], "money_history": EarningTransaction.objects.filter(user=creator).order_by("-created_at", "-id")[:20],
        "payouts": PayoutRequest.objects.filter(user=creator)[:10], "post_count": creator.learning_posts.filter(is_public=True).count(),
    })

@finance_required
def audit_view(request):
    return _render(request, "audit.html", "audit", {"page": Paginator(FinanceAuditLog.objects.select_related("actor"), 40).get_page(request.GET.get("page"))})
