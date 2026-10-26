"""Find a coaching centre: the classes listed centres run, searched by course and place, and the enquiries students
send them. A centre's teachers answer enquiries in Admissions; the student follows the reply in Your enquiries."""
import re
from datetime import timedelta
from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.urls import reverse
from django.utils import timezone
from apps.notifications.services import notify
from .models import Batch, Enquiry, EnquiryMessage, Organization
from .services import display_name, is_staff, staff_of
ENQUIRIES_PER_DAY = 10   # new enquiries one student can start in 24 hours; writing again on an open one doesn't count
PHONE = re.compile(r"^\+?[0-9][0-9 -]{6,18}[0-9]$")
PINCODE = re.compile(r"^[0-9]{6}$")
class EnquiryRefused(Exception):
    pass
def clean_phone(value):
    """A phone number as people type it: digits, spaces, dashes and a leading +. Returns it tidied, or raises ValueError."""
    value = " ".join((value or "").split())
    if value and not PHONE.match(value):
        raise ValueError("Enter a phone number with 8 to 15 digits, like +91 98765 43210.")
    return value
def city_of(location):
    """The city in a profile location like "Pune, India"."""
    return (location or "").split(",")[0].strip()
def open_batches():
    """Classes taking enquiries at listed centres, with the place they're held: their own, or else the centre's."""
    return Batch.objects.filter(is_open=True, organization__is_listed=True).select_related("organization").annotate(
        held_city=Case(When(city="", then=F("organization__city")), default=F("city")),
        held_area=Case(When(area="", then=F("organization__area")), default=F("area")),
    )
def search_batches(query="", city="", area="", mode="", level=""):
    """Open classes matching a search. A city or area narrows the classes held at a centre; online classes are open to
    every city, so they stay in (after the local ones) unless the search asks for classes at a centre only."""
    found = open_batches()
    if query:
        found = found.filter(Q(title__icontains=query) | Q(course__icontains=query) | Q(description__icontains=query)
                             | Q(organization__name__icontains=query) | Q(organization__courses__icontains=query))
    if mode == "centre":
        found = found.filter(mode__in=["centre", "both"])
    elif mode == "online":
        found = found.filter(mode__in=["online", "both"])
    if level in dict(Batch.LEVELS) and level != "all":
        found = found.filter(level__in=[level, "all"])
    local = Q()
    if city:
        local &= Q(held_city__iexact=city)
    if area:
        local &= Q(held_area__icontains=area) | Q(organization__pincode=area)
    if city or area:
        local &= Q(mode__in=["centre", "both"])
        found = found.filter(local) if mode == "centre" else found.filter(local | Q(mode__in=["online", "both"]))
        found = found.annotate(nearby=Case(When(local, then=Value(0)), default=Value(1), output_field=IntegerField()))
    else:
        found = found.annotate(nearby=Value(0, output_field=IntegerField()))
    today = timezone.localdate()
    started = Case(When(starts_on__lt=today, then=Value(1)), default=Value(0), output_field=IntegerField())
    return found.annotate(started=started).order_by("nearby", "started", F("starts_on").asc(nulls_last=True), "title")
def places():
    """Cities with open classes or listed centres, and the areas in each, for the search's menus."""
    cities, areas = {}, {}
    rows = list(open_batches().values_list("held_city", "held_area")) + list(Organization.objects.filter(is_listed=True).values_list("city", "area"))
    for city, area in rows:
        if city:
            key = city.strip().lower()
            cities.setdefault(key, city.strip())
            if area:
                areas.setdefault(key, set()).add(area.strip())
    return sorted(cities.values(), key=str.lower), {cities[key]: sorted(names, key=str.lower) for key, names in areas.items()}
def default_city(user, cities):
    """The member's own city when classes are listed there, so the first search is local."""
    profile = getattr(user, "profile", None) if user.is_authenticated else None
    mine = city_of(getattr(profile, "location", "")).lower()
    return next((city for city in cities if city.lower() == mine), "") if mine else ""
def can_enquire(organization, user):
    return bool(user.is_authenticated and not is_staff(organization, user))
def _thread_url(enquiry, for_centre):
    if for_centre:
        return reverse("organizations:enquiry", args=[enquiry.organization.slug, enquiry.pk])
    return reverse("organizations:my_enquiry", args=[enquiry.pk])
@transaction.atomic
def send_enquiry(organization, student, text, batch=None, phone=""):
    """Start an enquiry, or add to the student's open one about the same class. Returns (enquiry, started).
    The centre's owner and teachers are told either way."""
    if not can_enquire(organization, student):
        raise EnquiryRefused("You can't send an enquiry to a centre you teach at.")
    if batch is not None and (batch.organization_id != organization.pk or not batch.is_open):
        raise EnquiryRefused("This class isn't taking enquiries any more.")
    enquiry = Enquiry.objects.select_for_update().filter(organization=organization, student=student, batch=batch, status__in=Enquiry.OPEN).first()
    started = enquiry is None
    if started:
        if Enquiry.objects.filter(student=student, created_at__gte=timezone.now() - timedelta(days=1)).count() >= ENQUIRIES_PER_DAY:
            raise EnquiryRefused(f"You can send up to {ENQUIRIES_PER_DAY} new enquiries a day. Try again tomorrow, or write on one you've already sent.")
        enquiry = Enquiry.objects.create(organization=organization, batch=batch, student=student, phone=phone)
        note = f"{display_name(student)} asked about {batch.title}" if batch else f"{display_name(student)} sent {organization.name} an enquiry"
    else:
        note = f"{display_name(student)} wrote again about {enquiry.topic}"
    EnquiryMessage.objects.create(enquiry=enquiry, author=student, text=text)
    enquiry.phone = phone or enquiry.phone
    enquiry.last_message_at = enquiry.student_read_at = timezone.now()
    enquiry.save(update_fields=["phone", "last_message_at", "student_read_at"])
    for teacher in staff_of(organization):
        notify(teacher, student, "organization", note, _thread_url(enquiry, for_centre=True))
    return enquiry, started
@transaction.atomic
def reply(enquiry, author, text, from_centre):
    """A message on an enquiry from either side. The centre's first reply moves a new enquiry to Replied."""
    if not from_centre and enquiry.status not in Enquiry.OPEN:
        raise EnquiryRefused("This enquiry is closed. Send a new one from the centre's page.")
    EnquiryMessage.objects.create(enquiry=enquiry, author=author, from_centre=from_centre, text=text)
    now = timezone.now()
    enquiry.last_message_at = now
    fields = ["last_message_at"]
    if from_centre:
        enquiry.centre_read_at = now
        fields.append("centre_read_at")
        if enquiry.status == "new":
            enquiry.status = "replied"
            fields.append("status")
        notify(enquiry.student, author, "organization", f"{enquiry.organization.name} replied about {enquiry.topic}", _thread_url(enquiry, for_centre=False))
    else:
        enquiry.student_read_at = now
        fields.append("student_read_at")
        for teacher in staff_of(enquiry.organization):
            notify(teacher, author, "organization", f"{display_name(author)} wrote again about {enquiry.topic}", _thread_url(enquiry, for_centre=True))
    enquiry.save(update_fields=fields)
def invite_text(enquiry, join_url):
    return f"You're welcome to join {enquiry.organization.name}. Use this link to join: {join_url}"
def set_status(enquiry, status):
    if status in dict(Enquiry.STATUSES):
        enquiry.status = status
        enquiry.save(update_fields=["status"])
def mark_read(enquiry, for_centre):
    field = "centre_read_at" if for_centre else "student_read_at"
    setattr(enquiry, field, timezone.now())
    enquiry.save(update_fields=[field])
UNREAD_FOR_CENTRE = Q(centre_read_at__isnull=True) | Q(centre_read_at__lt=F("last_message_at"))
UNREAD_FOR_STUDENT = Q(student_read_at__lt=F("last_message_at"))
def unread_for_centre(organization):
    return Enquiry.objects.filter(UNREAD_FOR_CENTRE, organization=organization).count()
def unread_for_student(user):
    return Enquiry.objects.filter(UNREAD_FOR_STUDENT, student=user).count() if user.is_authenticated else 0
INBOX_FILTERS = [("open", "Open"), ("new", "New"), ("replied", "Replied"), ("joined", "Joined"), ("closed", "Closed"), ("all", "All")]
def inbox(organization, show="open", query=""):
    enquiries = Enquiry.objects.filter(organization=organization).select_related("student__profile", "batch")
    if show == "open":
        enquiries = enquiries.filter(status__in=Enquiry.OPEN)
    elif show in dict(Enquiry.STATUSES):
        enquiries = enquiries.filter(status=show)
    if query:
        enquiries = enquiries.filter(Q(student__first_name__icontains=query) | Q(student__last_name__icontains=query) | Q(student__email__icontains=query)
                                     | Q(batch__title__icontains=query) | Q(messages__text__icontains=query)).distinct()
    return enquiries
