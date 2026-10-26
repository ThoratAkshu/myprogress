"""Who may sponsor posts, which sponsored posts a member sees in their feed, and counting views, clicks and reports."""
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from apps.guidance.services import BUILDING, NEW, QUIET, STALLED, WATCHING
from apps.notifications.services import notify
from .models import Promotion, PromotionClick, PromotionHide, PromotionView
DAILY_CAP = 3            # times one member sees the same post in a day
FEED_SLOTS = (3, 11)     # sponsored posts go after the 3rd and the 11th feed item
HOUSE_SLOT = 3           # MyProgress's own suggestion (the next step) takes the 3rd instead...
SLOTS_AFTER_HOUSE = (7, 15)  # ...and sponsored posts move down, so sponsors keep both slots and never sit next to it
REPORTS_TO_PAUSE = 5     # reports (misleading or offensive) that pause a post until staff look at it
CANDIDATES = 60          # live posts considered for one feed
def sponsor_options(user):
    """What this account can promote: centres it owns, the company a confirmed recruiter hires for, companies it owns."""
    from apps.companies.models import Company
    from apps.organizations.models import Organization
    options = []
    for organization in Organization.objects.filter(memberships__user=user, memberships__role="owner", memberships__status="active").distinct():
        options.append({"key": f"organization:{organization.pk}", "kind": "organization", "name": organization.name, "organization": organization, "company": None})
    profile = getattr(user, "profile", None)
    if profile and profile.role == "recruiter" and profile.email_verified_at:
        options.append({"key": "recruiter", "kind": "recruiter", "name": profile.company_name or user.get_full_name() or profile.handle, "organization": None, "company": None})
    for company in Company.objects.filter(members__user=user, members__role="owner").distinct():
        options.append({"key": f"company:{company.pk}", "kind": "company", "name": company.name, "organization": None, "company": company})
    return options
def default_destination(promotion):
    """The sponsor's own page: a listed centre's page in Find a coaching centre, a company page, or the channel."""
    if promotion.organization_id:
        organization = promotion.organization
        if organization.is_listed:
            return reverse("organizations:listing", args=[organization.slug])
        owner = getattr(organization.owner, "profile", None)
        return reverse("landing:public_profile", args=[owner.handle]) if owner and owner.handle else reverse("organizations:find")
    if promotion.company_id:
        return reverse("companies:detail", args=[promotion.company.slug])
    profile = getattr(promotion.created_by, "profile", None)
    return reverse("landing:public_profile", args=[profile.handle]) if profile and profile.handle else "/"
def clean_destination(url):
    """A page on MyProgress (/path) or an https:// address; anything else is refused."""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    try:
        URLValidator(schemes=["https"])(url)
    except ValidationError:
        raise ValidationError("Use a page on MyProgress (starting with /) or a full https:// address.")
    return url
def destination(promotion):
    return promotion.cta_url or default_destination(promotion)
def viewer_profile(viewer, summary):
    """What targeting looks at, gathered once per feed."""
    profile = getattr(viewer, "profile", None)
    skills = {skill.lower() for skill in (profile.skill_list if profile else [])}
    skills |= {language.lower() for languages in viewer.repositories.values_list("languages", flat=True) for language in (languages or {})}
    skills |= {topic.lower() for topic in summary.interests}
    return {"segment": summary.segment, "occupation": profile.occupation if profile else "", "skills": skills,
            "city": (profile.location if profile else "").strip().lower(), "in_class": summary.in_class}
def match(promotion, viewer):
    """(score, why) when the post is meant for this member, else None. `why` is the reason shown on the post."""
    audiences = set(promotion.audiences or [])
    reasons, score = [], 1
    if audiences and "everyone" not in audiences:
        fits = {
            "watching": viewer["segment"] in {WATCHING, QUIET}, "new": viewer["segment"] == NEW,
            "building": viewer["segment"] in {BUILDING, STALLED},
            "students": viewer["occupation"] == "student", "professionals": viewer["occupation"] == "professional",
        }
        matched = [key for key in audiences if fits.get(key)]
        if not matched:
            return None
        score += 2
        reasons.append({"watching": "people exploring what to learn", "new": "new members", "building": "people building projects",
                        "students": "students", "professionals": "working professionals"}[matched[0]])
    wanted = {skill.lower() for skill in promotion.skill_list}
    if wanted:
        shared = wanted & viewer["skills"]
        if not shared:
            return None
        score += 2 * min(len(shared), 2)
        reasons.append(f"people interested in {next(skill for skill in promotion.skill_list if skill.lower() in shared)}")
    if promotion.city:
        if viewer["city"] and promotion.city.strip().lower() not in viewer["city"]:
            return None
        if viewer["city"]:
            score += 2
            reasons.append(f"people in {promotion.city.strip()}")
    # Coaching centres help most those who are only watching; hiring posts those already building.
    if promotion.sponsor_kind == "organization" and viewer["segment"] in {WATCHING, NEW, QUIET} and not viewer["in_class"]:
        score += 2
    if promotion.sponsor_kind in {"recruiter", "company"} and viewer["segment"] in {BUILDING, STALLED}:
        score += 2
    why = "Shown to " + " and ".join(reasons[:2]) + "." if reasons else "Shown to everyone on MyProgress."
    return score, why
def running():
    today = timezone.localdate()
    return (Promotion.objects.filter(status="live")
            .filter(Q(starts_on__isnull=True) | Q(starts_on__lte=today)).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))
            .filter(Q(max_views__isnull=True) | Q(views__lt=F("max_views"))))
def for_feed(viewer, summary, slots=len(FEED_SLOTS)):
    """Up to `slots` sponsored posts for this member's feed, best match first. Views are counted by into_feed, only
    for the posts that actually get a place."""
    candidates = list(running().exclude(created_by=viewer).exclude(hides__user=viewer)
                      .exclude(organization__memberships__user=viewer)  # no ads for a centre they already belong to
                      .select_related("organization__owner__profile", "company", "created_by__profile").order_by("-submitted_at")[:CANDIDATES])
    if not candidates:
        return []
    today = timezone.localdate()
    seen = dict(PromotionView.objects.filter(user=viewer, day=today, promotion__in=candidates).values_list("promotion_id", "count"))
    viewer_info = viewer_profile(viewer, summary)
    scored = []
    for promotion in candidates:
        if seen.get(promotion.pk, 0) >= DAILY_CAP:
            continue
        result = match(promotion, viewer_info)
        if result:
            score, why = result
            scored.append((score - seen.get(promotion.pk, 0), promotion.views, promotion, why))
    scored.sort(key=lambda row: (-row[0], row[1]))  # best match, then the post seen least overall
    chosen = []
    for _, _, promotion, why in scored[:slots]:
        promotion.why = why
        chosen.append(promotion)
    return chosen
def record_views(viewer, promotions):
    today = timezone.localdate()
    for promotion in promotions:
        row, created = PromotionView.objects.get_or_create(promotion=promotion, user=viewer, day=today)
        if not created:
            PromotionView.objects.filter(pk=row.pk).update(count=F("count") + 1)
        Promotion.objects.filter(pk=promotion.pk).update(views=F("views") + 1)
def room(items, house=False):
    """How many sponsored posts this feed has room for: one per slot it reaches, or one at the end of a short feed.
    An empty feed gets none, so new members still see what to do first."""
    return sum(1 for slot in (SLOTS_AFTER_HOUSE if house else FEED_SLOTS) if len(items) >= slot) or (1 if items else 0)
def place(items, promotions, house=None):
    """The feed with sponsored posts after its 3rd and 11th items. A short feed gets one, at the end.
    With a MyProgress suggestion (house), it goes after the 3rd item and sponsored posts after the 7th and 15th.
    An empty feed gets neither: the page shows the suggestion above its empty-feed message instead."""
    items = list(items)
    house_at = min(HOUSE_SLOT, len(items))
    for number, (slot, promotion) in enumerate(zip(SLOTS_AFTER_HOUSE if house else FEED_SLOTS, promotions)):
        entry = {"key": f"sponsored:{promotion.pk}", "sponsored": True, "promotion": promotion}
        if len(items) - number >= slot:
            items.insert(slot + number, entry)
        elif number == 0 and items:
            items.append(entry)
    if house and items:
        items.insert(house_at, house)
    return items
def into_feed(viewer, summary, items, house=None):
    """The feed with the sponsored posts that fit this member, counting a view for each one placed."""
    items = list(items)
    slots = room(items, bool(house))
    chosen = for_feed(viewer, summary, slots) if slots else []
    record_views(viewer, chosen)
    return place(items, chosen, house)
def with_ads(viewer, items, suggest=True):
    """Any feed's items with ads among them: MyProgress's suggestion for this member (when `suggest`; a feed that
    loads more as you scroll asks for it on its first batch only) and the sponsored posts that fit them. Learn and
    Watch use it; the home feed does the same with the summary it already has."""
    from apps.guidance import services as guidance
    summary = guidance.activity_summary(viewer)
    step = guidance.next_step(viewer, summary) if suggest else None
    if step:
        guidance.record_shown(viewer, step["key"])
    return into_feed(viewer, summary, items, {"key": f"next-step:{step['key']}", "next_step": True, "step": step} if step else None)
def record_click(promotion, user):
    PromotionClick.objects.create(promotion=promotion, user=user)
    Promotion.objects.filter(pk=promotion.pk).update(clicks=F("clicks") + 1)
def hide(promotion, user, reason):
    _, created = PromotionHide.objects.get_or_create(promotion=promotion, user=user, defaults={"reason": reason})
    if not created or reason == "not_interested":
        return
    reports = promotion.hides.exclude(reason="not_interested").count()
    if reports >= REPORTS_TO_PAUSE and promotion.status == "live":
        Promotion.objects.filter(pk=promotion.pk).update(status="paused", review_note="Paused automatically after reports from members. Staff will review it.")
        notify(promotion.created_by, None, "promotion", f"Your sponsored post \"{promotion.headline}\" was paused after reports from members. Staff will review it.", reverse("promotions:list"))
def reports(promotion):
    return promotion.hides.exclude(reason="not_interested").count()
def submit(promotion):
    promotion.status, promotion.submitted_at, promotion.review_note = "pending", timezone.now(), ""
    promotion.save(update_fields=["status", "submitted_at", "review_note", "updated_at"])
    for staff in User.objects.filter(is_staff=True, is_active=True)[:20]:
        notify(staff, promotion.created_by, "promotion", f"Sponsored post to review: \"{promotion.headline}\" by {promotion.sponsor_name}", reverse("promotions:review"))
def approve(promotion, reviewer):
    promotion.status, promotion.reviewed_by, promotion.reviewed_at, promotion.review_note = "live", reviewer, timezone.now(), ""
    promotion.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
    notify(promotion.created_by, reviewer, "promotion", f"Your sponsored post \"{promotion.headline}\" is live.", reverse("promotions:list"))
def reject(promotion, reviewer, note):
    promotion.status, promotion.reviewed_by, promotion.reviewed_at, promotion.review_note = "rejected", reviewer, timezone.now(), note.strip()[:300]
    promotion.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
    notify(promotion.created_by, reviewer, "promotion", f"Your sponsored post \"{promotion.headline}\" needs changes: {promotion.review_note}", reverse("promotions:list"))
