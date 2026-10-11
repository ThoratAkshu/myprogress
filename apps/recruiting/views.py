from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from apps.accounts.decorators import role_required
from apps.accounts.models import Profile
from apps.core.models import ActivityEvent
from apps.notifications.services import notify
from apps.core.services import CODE_ACTIONS, CONTRIBUTION_ACTIONS, active_coding_days, language_breakdown, platform_languages, visible_developers
from .models import ContactRequest, Shortlist, ShortlistEntry
def requests_url():
    """Where developers answer recruiters: Learn, then Network."""
    return f'{reverse("landing:workspace_section", args=["learning"])}?tab=network&view=requests'
recruiter_required = role_required("recruiter", "organization")
DAILY_CONTACT_LIMIT = 20
UNVERIFIED_DAILY_CONTACT_LIMIT = 3
def daily_contact_limit(user):
    profile = Profile.objects.filter(user=user).first()
    return DAILY_CONTACT_LIMIT if profile and profile.is_verified_recruiter else UNVERIFIED_DAILY_CONTACT_LIMIT
SORTS = {"score": "Highest score", "active": "Recently active", "new": "Newest members"}
def _safe_next(request, fallback):
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return next_url
    return fallback
def _candidate(handle):
    return get_object_or_404(Profile.objects.select_related("user"), handle=handle, role="developer", recruiter_visible=True)
@recruiter_required
def talent_search_view(request):
    filters = {key: request.GET.get(key, "").strip() for key in ["q", "language", "skill", "location", "min_score", "active", "sort"]}
    profiles = visible_developers()
    for term in filters["q"].split()[:5]:
        profiles = profiles.filter(Q(user__first_name__icontains=term) | Q(user__last_name__icontains=term) | Q(headline__icontains=term) | Q(skills__icontains=term) | Q(handle__icontains=term))
    if filters["language"]:
        profiles = profiles.filter(user__repositories__languages__has_key=filters["language"])
    if filters["skill"]:
        profiles = profiles.filter(skills__icontains=filters["skill"])
    if filters["location"]:
        profiles = profiles.filter(location__icontains=filters["location"])
    if filters["min_score"].isdigit():
        profiles = profiles.filter(score__gte=int(filters["min_score"]))
    if filters["active"]:
        profiles = profiles.filter(user__activity_events__action__in=CODE_ACTIONS, user__activity_events__created_at__gte=timezone.now() - timedelta(days=30))
    last_active = ActivityEvent.objects.filter(user=OuterRef("user"), action__in=CONTRIBUTION_ACTIONS).order_by("-created_at").values("created_at")[:1]
    profiles = profiles.distinct().annotate(last_active=Subquery(last_active))
    sort = filters["sort"] if filters["sort"] in SORTS else "score"
    ordering = {"score": ["-score", F("last_active").desc(nulls_last=True)], "active": [F("last_active").desc(nulls_last=True), "-score"], "new": ["-user__date_joined"]}[sort]
    page = Paginator(profiles.order_by(*ordering, "pk"), 12).get_page(request.GET.get("page"))
    candidate_ids = [profile.user_id for profile in page]
    shortlisted = set(ShortlistEntry.objects.filter(shortlist__owner=request.user, candidate_id__in=candidate_ids).values_list("candidate_id", flat=True))
    request_status = dict(ContactRequest.objects.filter(recruiter=request.user, developer_id__in=candidate_ids).order_by("created_at").values_list("developer_id", "status"))
    for profile in page:
        repositories = profile.user.repositories.all()
        verified = [repository for repository in repositories if repository.languages]
        profile.top_languages = language_breakdown([repository.languages for repository in repositories], limit=3)
        profile.verified_projects = len(verified)
        profile.shipped_projects = sum(1 for repository in verified if repository.project.status == "complete")
        profile.coding_days = active_coding_days(profile.user)
        profile.is_shortlisted = profile.user_id in shortlisted
        profile.contact_status = request_status.get(profile.user_id)
    query = request.GET.copy()
    query.pop("page", None)
    context = {"score_options": [("", "Any"), ("25", "25+"), ("50", "50+"), ("75", "75+")], "verified_recruiter": daily_contact_limit(request.user) == DAILY_CONTACT_LIMIT, "unverified_limit": UNVERIFIED_DAILY_CONTACT_LIMIT, "full_limit": DAILY_CONTACT_LIMIT, "section": "talent", "page": page, "filters": filters, "sort": sort, "sorts": SORTS, "languages": platform_languages(), "shortlists": request.user.shortlists.all(), "querystring": query.urlencode(), "has_filters": any(filters[key] for key in ["q", "language", "skill", "location", "min_score", "active"])}
    return render(request, "recruiting/search.html", context)
@recruiter_required
def shortlists_view(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()[:100]
        if request.POST.get("action") == "delete":
            request.user.shortlists.filter(pk=request.POST.get("shortlist_id")).delete()
            messages.success(request, "Shortlist deleted.")
            return redirect("recruiting:shortlists")
        if not name:
            messages.error(request, "Give the shortlist a name.")
            return redirect("recruiting:shortlists")
        shortlist, created = Shortlist.objects.get_or_create(owner=request.user, name=name)
        if created:
            messages.success(request, f"Shortlist “{name}” created.")
        return redirect(f'{reverse("recruiting:shortlists")}?list={shortlist.pk}')
    shortlists = list(request.user.shortlists.annotate(entry_count=Count("entries")))
    active = next((shortlist for shortlist in shortlists if str(shortlist.pk) == request.GET.get("list")), shortlists[0] if shortlists else None)
    entries = active.entries.select_related("candidate__profile") if active else []
    stage_counts = dict(active.entries.values_list("stage").annotate(total=Count("id"))) if active else {}
    pipeline = [{"key": key, "label": label, "count": stage_counts.get(key, 0)} for key, label in ShortlistEntry.STAGE_CHOICES]
    context = {"section": "shortlists", "shortlists": shortlists, "active": active, "entries": entries, "pipeline": pipeline, "stages": ShortlistEntry.STAGE_CHOICES}
    return render(request, "recruiting/shortlists.html", context)
@recruiter_required
@require_POST
def shortlist_add_view(request, handle):
    candidate = _candidate(handle)
    shortlist = request.user.shortlists.filter(pk=request.POST.get("shortlist")).first() if request.POST.get("shortlist") else None
    if not shortlist:
        shortlist, _ = Shortlist.objects.get_or_create(owner=request.user, name="My shortlist")
    _, created = ShortlistEntry.objects.get_or_create(shortlist=shortlist, candidate=candidate.user)
    messages.success(request, f"{candidate.user.get_full_name() or candidate.handle} {'added to' if created else 'is already in'} “{shortlist.name}”.")
    return redirect(_safe_next(request, reverse("landing:public_profile", args=[candidate.handle])))
@recruiter_required
@require_POST
def shortlist_entry_view(request, entry_id):
    entry = get_object_or_404(ShortlistEntry, pk=entry_id, shortlist__owner=request.user)
    target = f'{reverse("recruiting:shortlists")}?list={entry.shortlist_id}'
    if request.POST.get("action") == "remove":
        entry.delete()
        messages.success(request, "Candidate removed from the shortlist.")
        return redirect(target)
    if request.POST.get("stage") in dict(ShortlistEntry.STAGE_CHOICES):
        entry.stage = request.POST["stage"]
    entry.note = request.POST.get("note", entry.note)[:5000]
    entry.save(update_fields=["stage", "note", "updated_at"])
    messages.success(request, "Candidate updated.")
    return redirect(target)
@recruiter_required
@require_POST
def contact_view(request, handle):
    candidate = _candidate(handle)
    fallback = reverse("landing:public_profile", args=[candidate.handle])
    role_title = request.POST.get("role_title", "").strip()[:120]
    message = request.POST.get("message", "").strip()[:2000]
    if not role_title or len(message) < 20:
        messages.error(request, "Add the role title and a message of at least 20 characters.")
        return redirect(_safe_next(request, fallback))
    limit = daily_contact_limit(request.user)
    if ContactRequest.objects.filter(recruiter=request.user, created_at__gte=timezone.now() - timedelta(days=1)).count() >= limit:
        messages.error(request, f"You can send up to {limit} contact requests per day." + ("" if limit == DAILY_CONTACT_LIMIT else f" Confirm a company email to raise this to {DAILY_CONTACT_LIMIT}."))
        return redirect(_safe_next(request, fallback))
    try:
        with transaction.atomic():
            ContactRequest.objects.create(recruiter=request.user, developer=candidate.user, role_title=role_title, message=message)
            notify(candidate.user, request.user, "contact_request", f"{request.user.get_full_name() or 'A recruiter'} wants to talk to you about {role_title}", requests_url())
    except IntegrityError:
        messages.error(request, "You already have a pending request with this developer.")
        return redirect(_safe_next(request, fallback))
    ShortlistEntry.objects.filter(shortlist__owner=request.user, candidate=candidate.user, stage="saved").update(stage="contacted", updated_at=timezone.now())
    messages.success(request, f"Request sent. {candidate.user.first_name or candidate.handle} will see it under Learn, then Network.")
    return redirect(_safe_next(request, fallback))
@recruiter_required
def outreach_view(request):
    sent = request.user.sent_contact_requests.select_related("developer__profile")
    counts = dict(sent.values_list("status").annotate(total=Count("id")))
    context = {"section": "outreach", "sent": sent, "counts": counts, "daily_limit": daily_contact_limit(request.user), "full_limit": DAILY_CONTACT_LIMIT, "sent_today": sent.filter(created_at__gte=timezone.now() - timedelta(days=1)).count()}
    return render(request, "recruiting/outreach.html", context)
@login_required(login_url="landing:home")
@require_POST
def respond_contact_view(request, request_id):
    contact = get_object_or_404(ContactRequest, pk=request_id, developer=request.user, status="pending")
    action = request.POST.get("action")
    if action in {"accept", "decline"}:
        contact.status = "accepted" if action == "accept" else "declined"
        contact.responded_at = timezone.now()
        contact.save(update_fields=["status", "responded_at"])
        notify(contact.recruiter, request.user, "contact_response", f"{request.user.get_full_name() or 'A developer'} {contact.status} your request about {contact.role_title}", reverse("recruiting:outreach"))
        messages.success(request, "Request accepted. Your email is now shared with the recruiter." if action == "accept" else "Request declined.")
    return redirect(requests_url())
