"""Sponsored posts: sponsors write and track them, staff review them, members open, hide or report them."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from apps.common.ratelimit import rate_limit
from . import services
from .forms import PromotionForm
from .models import Promotion, PromotionHide
def _own(request, promotion_id):
    return get_object_or_404(Promotion, pk=promotion_id, created_by=request.user)
@login_required(login_url="landing:home")
def list_view(request):
    sponsors = services.sponsor_options(request.user)
    promotions = Promotion.objects.filter(created_by=request.user).annotate(
        reach=Count("view_days__user", distinct=True), report_count=Count("hides", filter=~Q(hides__reason="not_interested"), distinct=True))
    return render(request, "promotions/list.html", {"section": "sponsored", "sponsors": sponsors, "promotions": promotions})
@login_required(login_url="landing:home")
@rate_limit("promotion-edit", 40, 3600)
def edit_view(request, promotion_id=None):
    sponsors = services.sponsor_options(request.user)
    if not sponsors:
        return redirect("promotions:list")
    promotion = _own(request, promotion_id) if promotion_id else Promotion(created_by=request.user, sponsor_name=sponsors[0]["name"], sponsor_kind=sponsors[0]["kind"])
    if promotion.pk and not promotion.editable:
        messages.error(request, "This post can't be changed while it's waiting for review.")
        return redirect("promotions:list")
    form = PromotionForm(request.POST or None, request.FILES or None, instance=promotion, sponsors=sponsors)
    if request.method == "POST" and form.is_valid():
        was_live = promotion.status in {"live", "paused"}
        promotion = form.save()
        if request.POST.get("submit") or was_live:
            services.submit(promotion)  # every change to a running post is checked again
            messages.success(request, "Sent for review. Staff usually check sponsored posts within a working day.")
        else:
            messages.success(request, "Saved as a draft.")
        return redirect("promotions:list")
    return render(request, "promotions/form.html", {"section": "sponsored", "form": form, "promotion": promotion})
@login_required(login_url="landing:home")
@require_POST
def action_view(request, promotion_id):
    promotion = _own(request, promotion_id)
    action = request.POST.get("action")
    if action == "submit" and promotion.status in {"draft", "rejected"}:
        services.submit(promotion)
        messages.success(request, "Sent for review.")
    elif action == "pause" and promotion.status == "live":
        promotion.status = "paused"
        promotion.save(update_fields=["status", "updated_at"])
        messages.success(request, "Paused. Members won't see it until you resume it.")
    elif action == "resume" and promotion.status == "paused":
        if promotion.review_note:  # paused after reports: staff look again first
            services.submit(promotion)
            messages.success(request, "Sent for review before it runs again.")
        else:
            promotion.status = "live"
            promotion.save(update_fields=["status", "updated_at"])
            messages.success(request, "Running again.")
    elif action == "end" and promotion.status in {"live", "paused", "pending"}:
        promotion.status = "ended"
        promotion.save(update_fields=["status", "updated_at"])
        messages.success(request, "Ended. Its numbers stay here.")
    elif action == "delete" and promotion.status in {"draft", "rejected"}:
        if promotion.image:
            promotion.image.delete(save=False)
        promotion.delete()
        messages.success(request, "Deleted.")
    else:
        messages.error(request, "That can't be done to this post now.")
    return redirect("promotions:list")
def _staff_only(request):
    if not request.user.is_staff:
        raise Http404
@login_required(login_url="landing:home")
def review_view(request):
    """Staff: posts waiting for review, live posts, and posts members reported."""
    _staff_only(request)
    tab = request.GET.get("tab") if request.GET.get("tab") in {"pending", "live", "reported"} else "pending"
    posts = Promotion.objects.select_related("created_by__profile", "organization", "company").annotate(
        report_count=Count("hides", filter=~Q(hides__reason="not_interested"), distinct=True))
    if tab == "pending":
        posts = posts.filter(status="pending").order_by("submitted_at")
    elif tab == "live":
        posts = posts.filter(status="live").order_by("-reviewed_at")
    else:
        posts = posts.filter(report_count__gt=0).order_by("-report_count")
    counts = {"pending": Promotion.objects.filter(status="pending").count(), "live": Promotion.objects.filter(status="live").count(),
              "reported": Promotion.objects.filter(hides__reason__in=["misleading", "offensive"]).distinct().count()}
    return render(request, "promotions/review.html", {"section": "", "tab": tab, "posts": posts[:100], "counts": counts})
@login_required(login_url="landing:home")
@require_POST
def review_action_view(request, promotion_id):
    _staff_only(request)
    promotion = get_object_or_404(Promotion, pk=promotion_id)
    action = request.POST.get("action")
    if action == "approve" and promotion.status in {"pending", "paused", "rejected"}:
        services.approve(promotion, request.user)
        messages.success(request, f"\"{promotion.headline}\" is live.")
    elif action == "reject" and promotion.status in {"pending", "live", "paused"}:
        note = request.POST.get("note", "").strip()
        if not note:
            messages.error(request, "Say what needs to change, so the sponsor can fix it.")
        else:
            services.reject(promotion, request.user, note)
            messages.success(request, "Sent back with your note.")
    else:
        messages.error(request, "That can't be done to this post now.")
    tab = request.POST.get("tab") if request.POST.get("tab") in {"pending", "live", "reported"} else "pending"
    return redirect(f"{reverse('promotions:review')}?tab={tab}")
@login_required(login_url="landing:home")
def go_view(request, promotion_id):
    """The post's button: counts the click and opens the sponsor's link (checked when the post was saved)."""
    promotion = get_object_or_404(Promotion, pk=promotion_id, status="live")
    if promotion.created_by_id != request.user.pk:
        services.record_click(promotion, request.user)
    return redirect(services.destination(promotion))
@login_required(login_url="landing:home")
@require_POST
@rate_limit("promotion-hide", 60, 3600)
def hide_view(request, promotion_id):
    promotion = get_object_or_404(Promotion, pk=promotion_id)
    reason = request.POST.get("reason") if request.POST.get("reason") in dict(PromotionHide.REASONS) else "not_interested"
    services.hide(promotion, request.user, reason)
    text = "Thanks. We hid it and staff will look at your report." if reason != "not_interested" else "Hidden. You won't see this post again."
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": True, "message": text})
    messages.success(request, text)
    return redirect("landing:dashboard")
