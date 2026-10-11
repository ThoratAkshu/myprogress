"""The company revenue report: what MyProgress earned, what creators cost, and what's left."""
from datetime import date
from decimal import Decimal
from django.contrib.auth.models import User
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from apps.core.models import EarningTransaction, LearningPost
from .models import PayoutRequest, RevenueEntry
from .services import BONUS_PREFIX, ZERO, _midnight, next_month, owed_to_creators, previous_month, treasury_balance
PERIODS = [("this_month", "This month"), ("last_month", "Last month"), ("3m", "Last 3 months"), ("12m", "Last 12 months"), ("fy", "This financial year"), ("all", "All time")]
def months_back(first, count):
    for _ in range(count):
        first = previous_month(first)
    return first
def financial_year_start(today):
    """India's financial year runs April to March."""
    return date(today.year if today.month >= 4 else today.year - 1, 4, 1)
def period_range(key, today=None):
    """(first day, day after the last, label) for a report period."""
    today = today or timezone.localdate()
    this_month = today.replace(day=1)
    label = dict(PERIODS).get(key, "This month")
    if key == "last_month":
        return previous_month(this_month), this_month, label
    if key == "3m":
        return months_back(this_month, 2), next_month(this_month), label
    if key == "12m":
        return months_back(this_month, 11), next_month(this_month), label
    if key == "fy":
        start = financial_year_start(today)
        return start, next_month(this_month), f"FY {start.year}–{str(start.year + 1)[2:]}"
    if key == "all":
        first_revenue = RevenueEntry.objects.order_by("received_on").values_list("received_on", flat=True).first()
        first_cost = EarningTransaction.objects.order_by("created_at").values_list("created_at", flat=True).first()
        candidates = [this_month] + ([first_revenue.replace(day=1)] if first_revenue else []) + ([timezone.localtime(first_cost).date().replace(day=1)] if first_cost else [])
        return min(candidates), next_month(this_month), label
    return this_month, next_month(this_month), dict(PERIODS)["this_month"]
def _between(start, end):
    return {"created_at__gte": _midnight(start), "created_at__lt": _midnight(end)}
def creator_costs(start, end):
    """What creators earned in the period (the company's cost, whether or not it's been paid yet)."""
    entries = EarningTransaction.objects.filter(**_between(start, end))
    totals = entries.aggregate(
        bonuses=Sum("amount", filter=Q(transaction_type="credit", description__startswith=BONUS_PREFIX)),
        conversions=Sum("amount", filter=Q(transaction_type="credit") & ~Q(description__startswith=BONUS_PREFIX)),
        adjustments=Sum("amount", filter=Q(transaction_type="adjustment")))
    costs = {key: value or ZERO for key, value in totals.items()}
    costs["total"] = costs["bonuses"] + costs["conversions"] + costs["adjustments"]
    return costs
def monthly_rows(start, end):
    """Revenue, creator cost, profit and cash paid for each month in the range, oldest first."""
    rows, month = [], start.replace(day=1)
    while month < end:
        rows.append({"month": month, "revenue": ZERO, "cost": ZERO, "paid": ZERO})
        month = next_month(month)
    by_month = {row["month"]: row for row in rows}
    def fill(field, queryset):
        for item in queryset:
            key = item["month"].date() if hasattr(item["month"], "date") else item["month"]
            if key.replace(day=1) in by_month:
                by_month[key.replace(day=1)][field] += item["total"] or ZERO
    fill("revenue", RevenueEntry.objects.filter(received_on__gte=start, received_on__lt=end).annotate(month=TruncMonth("received_on")).values("month").annotate(total=Sum("amount")))
    fill("cost", EarningTransaction.objects.filter(transaction_type__in=["credit", "adjustment"], **_between(start, end)).annotate(month=TruncMonth("created_at")).values("month").annotate(total=Sum("amount")))
    fill("paid", PayoutRequest.objects.filter(status="paid", processed_at__gte=_midnight(start), processed_at__lt=_midnight(end)).annotate(month=TruncMonth("processed_at")).values("month").annotate(total=Sum("amount")))
    peak = max([max(row["revenue"], row["cost"]) for row in rows] + [Decimal("1")])
    for row in rows:
        row["net"] = row["revenue"] - row["cost"]
        row["margin"] = round(row["net"] * 100 / row["revenue"]) if row["revenue"] else None
        row["revenue_height"], row["cost_height"] = round(row["revenue"] * 100 / peak), round(row["cost"] * 100 / peak)
    return rows
def revenue_report(period="this_month", today=None):
    today = today or timezone.localdate()
    start, end, label = period_range(period, today)
    revenue_entries = RevenueEntry.objects.filter(received_on__gte=start, received_on__lt=end)
    revenue = revenue_entries.aggregate(total=Sum("amount"))["total"] or ZERO
    labels = dict(RevenueEntry.SOURCES)
    by_source = [{"source": labels[row["source"]], "total": row["total"]} for row in revenue_entries.values("source").annotate(total=Sum("amount")).order_by("-total")]
    for row in by_source:
        row["percent"] = round(row["total"] * 100 / revenue) if revenue else 0
    costs = creator_costs(start, end)
    paid = PayoutRequest.objects.filter(status="paid", processed_at__gte=_midnight(start), processed_at__lt=_midnight(end)).aggregate(total=Sum("amount"), tax=Sum("tds_amount"))
    earners = EarningTransaction.objects.filter(transaction_type__in=["credit", "adjustment"], **_between(start, end)).values("user").annotate(total=Sum("amount")).filter(total__gt=0)
    posts = LearningPost.objects.filter(is_public=True, published_at__gte=_midnight(start), published_at__lt=_midnight(end)).count()
    top = list(earners.order_by("-total")[:5])
    people = User.objects.select_related("profile").in_bulk([row["user"] for row in top])
    # Months of cover: the master account against the average creator cost of the last three full months.
    this_month = today.replace(day=1)
    recent = creator_costs(months_back(this_month, 3), this_month)["total"] / 3
    balance = treasury_balance()
    net = revenue - costs["total"]
    chart_start = months_back(end, 12) if period in {"this_month", "last_month", "3m"} else max(start, months_back(this_month, 23))
    return {
        "period": period, "label": label, "start": start, "end": end, "last_day": date.fromordinal(end.toordinal() - 1),
        "revenue": revenue, "costs": costs, "net": net, "margin": round(net * 100 / revenue) if revenue else None,
        "paid": paid["total"] or ZERO, "tax_held": paid["tax"] or ZERO, "by_source": by_source,
        "earning_creators": earners.count(), "posts": posts, "cost_per_post": costs["total"] / posts if posts else None,
        "cost_per_creator": costs["total"] / earners.count() if earners.count() else None,
        "top_creators": [{"user": people.get(row["user"]), "total": row["total"]} for row in top if people.get(row["user"])],
        "balance": balance, "owed": owed_to_creators(), "cover_months": (balance / recent) if recent > 0 else None,
        "months": monthly_rows(chart_start, end),
        "entry_count": revenue_entries.count(),
    }
