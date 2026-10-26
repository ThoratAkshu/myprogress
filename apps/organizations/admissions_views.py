"""Find a coaching centre (classes by course and place, centre pages, sending an enquiry, Your enquiries) and a
centre's Admissions tab (answering enquiries, listing classes)."""
from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from apps.accounts.access import DEVELOPER, user_role
from apps.common.ratelimit import rate_limit
from . import admissions, services
from .forms import BatchForm, EnquiryForm, EnquiryReplyForm
from .models import Batch, Enquiry, Membership, Organization
from .views import _organization, _render
CLASSES_PAGE_SIZE = 12
INBOX_PAGE_SIZE = 25
MODES = [("", "At a centre or online"), ("centre", "At a centre"), ("online", "Online")]
def _sender(user):
    """Students and professionals send enquiries; recruiters and organizations can look but not ask."""
    return user.is_authenticated and user_role(user) == DEVELOPER
def _open_classes(organization, exclude=None):
    batches = organization.batches.filter(is_open=True).order_by(F("starts_on").asc(nulls_last=True), "title")
    return batches.exclude(pk=exclude.pk) if exclude else batches
def _open_enquiry(user, organization, batch=None):
    if not user.is_authenticated:
        return None
    return Enquiry.objects.filter(student=user, organization=organization, batch=batch, status__in=Enquiry.OPEN).first()
def find_view(request):
    """Find a coaching centre, by class: open classes at listed centres by course and place. With no city chosen yet,
    the search starts in the member's own city when classes are listed there. An invite code goes to the centres tab,
    which opens it, as the code box there and older links do."""
    if request.GET.get("code", "").strip():
        from .views import find_centres_view
        return find_centres_view(request)
    cities, areas = admissions.places()
    query = request.GET.get("q", "").strip()[:80]
    city = request.GET.get("city", "").strip()[:80] if "city" in request.GET else admissions.default_city(request.user, cities)
    area = request.GET.get("area", "").strip()[:80]
    mode = request.GET.get("mode", "") if request.GET.get("mode") in {"centre", "online"} else ""
    level = request.GET.get("level", "") if request.GET.get("level") in dict(Batch.LEVELS) else ""
    page = Paginator(admissions.search_batches(query, city, area, mode, level), CLASSES_PAGE_SIZE).get_page(request.GET.get("page"))
    city_areas = areas.get(city, []) if city else sorted({name for names in areas.values() for name in names}, key=str.lower)
    where = ", ".join(part for part in [area, city] if part)
    scope = "online" if mode == "online" else (f"in {where}" + ("" if mode == "centre" else " and online")) if where else ""
    return render(request, "organizations/find.html", {
        "section": "organization", "find_tab": "classes", "page": page, "query": query, "city": city, "area": area, "mode": mode, "level": level,
        "cities": cities, "city_areas": city_areas, "modes": MODES, "levels": Batch.LEVELS, "searched": bool(query or city or area or mode or level),
        "any_open": admissions.open_batches().exists(), "unread": admissions.unread_for_student(request.user), "scope": scope,
        "city_from_profile": bool(city) and "city" not in request.GET,
        "params": urlencode({"q": query, "city": city, "area": area, "mode": mode, "level": level}),
    })
def _centre_page(request, organization, form=None):
    existing = Membership.objects.filter(organization=organization, user=request.user).first() if request.user.is_authenticated else None
    return render(request, "organizations/centre.html", {
        "section": "organization", "organization": organization, "existing": existing, "batches": _open_classes(organization),
        "student_count": organization.memberships.filter(status="active", role="student").count(), "shared": services.SHARED_WITH_TEACHERS,
        "viewer_is_staff": services.is_staff(organization, request.user), "can_send": _sender(request.user) and admissions.can_enquire(organization, request.user),
        "form": form or EnquiryForm(), "open_enquiry": _open_enquiry(request.user, organization), "listed": True,
    })
def centre_view(request, slug):
    """A listed centre's page: where it is and how to reach it, its open classes, an enquiry form, and Ask to join.
    Asking to join from here always waits for a teacher's approval."""
    organization = get_object_or_404(Organization, slug=slug, is_listed=True)
    if request.method == "POST" and request.user.is_authenticated:
        if not Membership.objects.filter(organization=organization, user=request.user).exists():
            services.join(organization, request.user, require_approval=True)
            messages.success(request, f"Request sent. A teacher at {organization.name} will approve it.")
        return redirect("organizations:listing", slug=organization.slug)
    return _centre_page(request, organization)
def _batch_page(request, batch, form=None):
    organization = batch.organization
    return render(request, "organizations/batch.html", {
        "section": "organization", "batch": batch, "organization": organization, "others": _open_classes(organization, exclude=batch)[:4],
        "viewer_is_staff": services.is_staff(organization, request.user), "can_send": batch.is_open and _sender(request.user) and admissions.can_enquire(organization, request.user),
        "form": form or EnquiryForm(initial={"batch": batch.pk}), "open_enquiry": _open_enquiry(request.user, organization, batch),
    })
def batch_view(request, batch_id):
    batch = get_object_or_404(Batch.objects.select_related("organization"), pk=batch_id, organization__is_listed=True)
    return _batch_page(request, batch)
@login_required(login_url="landing:home")
@require_POST
@rate_limit("enquiry", 30, 3600)
def enquire_view(request, slug):
    """Send an enquiry about one class (batch in the form) or the centre in general."""
    organization = get_object_or_404(Organization, slug=slug, is_listed=True)
    form = EnquiryForm(request.POST)
    batch_id = request.POST.get("batch", "")
    batch = get_object_or_404(Batch, pk=batch_id, organization=organization) if batch_id.isdigit() else None
    if not form.is_valid():
        return _batch_page(request, batch, form) if batch else _centre_page(request, organization, form)
    try:
        enquiry, started = admissions.send_enquiry(organization, request.user, form.cleaned_data["message"], batch, form.cleaned_data["phone"])
    except admissions.EnquiryRefused as refusal:
        messages.error(request, str(refusal))
        return redirect("organizations:batch", batch_id=batch.pk) if batch else redirect("organizations:listing", slug=organization.slug)
    messages.success(request, f"Enquiry sent to {organization.name}. You'll get a notification when they reply." if started else "Added to your enquiry. The centre has been told.")
    return redirect("organizations:my_enquiry", enquiry_id=enquiry.pk)
@login_required(login_url="landing:home")
def my_enquiries_view(request):
    enquiries = Enquiry.objects.filter(student=request.user).select_related("organization", "batch").prefetch_related("messages")
    page = Paginator(enquiries, INBOX_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "organizations/my_enquiries.html", {"section": "organization", "find_tab": "enquiries", "page": page, "unread": admissions.unread_for_student(request.user)})
@login_required(login_url="landing:home")
def my_enquiry_view(request, enquiry_id):
    enquiry = get_object_or_404(Enquiry.objects.select_related("organization", "batch"), pk=enquiry_id, student=request.user)
    form = EnquiryReplyForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                admissions.reply(enquiry, request.user, form.cleaned_data["text"], from_centre=False)
            except admissions.EnquiryRefused as refusal:
                messages.error(request, str(refusal))
            return redirect("organizations:my_enquiry", enquiry_id=enquiry.pk)
    else:
        admissions.mark_read(enquiry, for_centre=False)
    return render(request, "organizations/my_enquiry.html", {"section": "organization", "find_tab": "enquiries", "enquiry": enquiry, "thread": enquiry.messages.select_related("author__profile"),
                                                              "form": form, "can_reply": enquiry.status in Enquiry.OPEN, "unread": admissions.unread_for_student(request.user)})
@login_required(login_url="landing:home")
def admissions_view(request, slug):
    """The centre's enquiries, newest activity first, with unread ones marked."""
    organization, member = _organization(request, slug, staff=True)
    show = request.GET.get("show", "open") if request.GET.get("show") in dict(admissions.INBOX_FILTERS) else "open"
    query = request.GET.get("q", "").strip()[:80]
    enquiries = admissions.inbox(organization, show, query).prefetch_related("messages")
    counts = dict(Enquiry.objects.filter(organization=organization).values("status").annotate(total=Count("pk")).values_list("status", "total"))
    counts["open"] = sum(counts.get(status, 0) for status in Enquiry.OPEN)
    counts["all"] = sum(counts.get(status, 0) for status, _ in Enquiry.STATUSES)
    page = Paginator(enquiries, INBOX_PAGE_SIZE).get_page(request.GET.get("page"))
    return _render(request, "admissions.html", organization, member, "admissions", {
        "page": page, "show": show, "query": query, "filters": [(key, label, counts.get(key, 0)) for key, label in admissions.INBOX_FILTERS],
        "admissions_tab": "enquiries", "class_count": organization.batches.filter(is_open=True).count(),
    })
@login_required(login_url="landing:home")
def enquiry_view(request, slug, enquiry_id):
    organization, member = _organization(request, slug, staff=True)
    enquiry = get_object_or_404(Enquiry.objects.select_related("student__profile", "batch"), pk=enquiry_id, organization=organization)
    form = EnquiryReplyForm(request.POST or None)
    if request.method == "POST":
        action = request.POST.get("action", "reply")
        if action == "status":
            admissions.set_status(enquiry, request.POST.get("status", ""))
            messages.success(request, f"Marked as {enquiry.get_status_display().lower()}.")
            return redirect("organizations:enquiry", slug=slug, enquiry_id=enquiry.pk)
        if action == "invite":
            join_url = request.build_absolute_uri(reverse("organizations:join", args=[organization.invite_code]))
            admissions.reply(enquiry, request.user, admissions.invite_text(enquiry, join_url), from_centre=True)
            messages.success(request, "Invite link sent. They'll see it with your other replies.")
            return redirect("organizations:enquiry", slug=slug, enquiry_id=enquiry.pk)
        if form.is_valid():
            admissions.reply(enquiry, request.user, form.cleaned_data["text"], from_centre=True)
            return redirect("organizations:enquiry", slug=slug, enquiry_id=enquiry.pk)
    else:
        admissions.mark_read(enquiry, for_centre=True)
    joined = Membership.objects.filter(organization=organization, user=enquiry.student).first()
    others = Enquiry.objects.filter(organization=organization, student=enquiry.student).exclude(pk=enquiry.pk).select_related("batch")[:5]
    return _render(request, "admissions_enquiry.html", organization, member, "admissions", {
        "enquiry": enquiry, "thread": enquiry.messages.select_related("author__profile"), "form": form, "statuses": Enquiry.STATUSES, "membership": joined, "others": others,
    })
@login_required(login_url="landing:home")
def batches_view(request, slug):
    """The classes the centre lists in Find a coaching centre, and a form for a new one."""
    organization, member = _organization(request, slug, staff=True)
    form = BatchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        batch = form.save(commit=False)
        batch.organization, batch.created_by = organization, request.user
        batch.save()
        messages.success(request, "Class listed." if organization.is_listed else "Class saved. Students will find it once you list your centre in Settings.")
        return redirect("organizations:batches", slug=slug)
    batches = organization.batches.annotate(enquiry_count=Count("enquiries"), open_count=Count("enquiries", filter=Q(enquiries__status__in=Enquiry.OPEN))).order_by("-is_open", F("starts_on").asc(nulls_last=True), "title")
    return _render(request, "admissions_classes.html", organization, member, "admissions", {"form": form, "batches": batches, "admissions_tab": "classes"})
@login_required(login_url="landing:home")
def batch_edit_view(request, slug, batch_id):
    organization, member = _organization(request, slug, staff=True)
    batch = get_object_or_404(Batch, pk=batch_id, organization=organization)
    if request.method == "POST" and request.POST.get("action") == "delete":
        if batch.enquiries.exists():
            messages.error(request, "Students have asked about this class, so it can't be deleted. Stop taking enquiries instead.")
            return redirect("organizations:batch_edit", slug=slug, batch_id=batch.pk)
        batch.delete()
        messages.success(request, "Class deleted.")
        return redirect("organizations:batches", slug=slug)
    form = BatchForm(request.POST or None, instance=batch)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Class updated.")
        return redirect("organizations:batches", slug=slug)
    return _render(request, "admissions_class_edit.html", organization, member, "admissions", {"form": form, "batch": batch, "admissions_tab": "classes"})
