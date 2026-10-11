"""Organization rules: who can see what, joining, invites, and the growth numbers teachers see."""
from collections import defaultdict
from datetime import timedelta
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Max, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from apps.accounts.models import Profile
from apps.core.models import ActivityEvent, LearningPost, Repository
from apps.core.services import CODE_ACTIONS
from apps.notifications.services import notify
from .models import Attendance, ChannelPost, Invite, LiveClass, Membership, Organization, Submission, Task
# What teachers can see about a student, shown to students before they join.
SHARED_WITH_TEACHERS = ["Your score, rank and coding days", "How many projects and public posts you have", "Your task submissions and scores", "When you were last active"]
def membership(organization, user):
    if not user.is_authenticated:
        return None
    return Membership.objects.filter(organization=organization, user=user, status="active").first()
def is_staff(organization, user):
    member = membership(organization, user)
    return bool(member and member.is_staff)
def staff_organizations(user):
    return Organization.objects.filter(memberships__user=user, memberships__status="active", memberships__role__in=["owner", "teacher"]).distinct()
def member_organizations(user):
    return Organization.objects.filter(memberships__user=user, memberships__status="active").distinct()
def visible_to(queryset, member):
    """Channel posts and tasks for everyone, plus those for the member's own group. Staff see everything."""
    if member is None:
        return queryset.none()
    if member.is_staff:
        return queryset
    return queryset.filter(Q(group="") | Q(group__iexact=member.group))
RESERVED_SLUGS = {"new", "join", "invite"}
def unique_slug(name):
    base = slugify(name)[:50] or "organization"
    if base in RESERVED_SLUGS:
        base = f"{base}-org"
    slug, number = base, 2
    while Organization.objects.filter(slug=slug).exists():
        slug, number = f"{base[:45]}-{number}", number + 1
    return slug
@transaction.atomic
def create_organization(owner, data):
    organization = Organization.objects.create(owner=owner, slug=unique_slug(data["name"]), **data)
    Membership.objects.create(organization=organization, user=owner, role="owner", status="active")
    return organization
def channel_url(organization):
    return reverse("organizations:channel", args=[organization.slug])
def staff_of(organization):
    return User.objects.filter(org_memberships__organization=organization, org_memberships__status="active", org_memberships__role__in=["owner", "teacher"])
def students_of(organization, group=""):
    members = Membership.objects.filter(organization=organization, status="active", role="student").select_related("user__profile")
    return members.filter(group__iexact=group) if group else members
def display_name(user):
    return user.get_full_name() or getattr(getattr(user, "profile", None), "handle", None) or user.email
@transaction.atomic
def join(organization, user, invite=None):
    """Join from the shared link or an email invite. Returns the membership; it may wait for approval."""
    existing = Membership.objects.filter(organization=organization, user=user).first()
    if existing:
        return existing
    approved = invite is not None or not organization.join_requires_approval
    member = Membership.objects.create(organization=organization, user=user, role=invite.role if invite else "student", group=invite.group if invite else "", status="active" if approved else "pending", invited_by=invite.created_by if invite else None)
    if invite:
        invite.accepted_at, invite.accepted_by = timezone.now(), user
        invite.save(update_fields=["accepted_at", "accepted_by"])
    text = f"{display_name(user)} joined {organization.name}" if approved else f"{display_name(user)} asked to join {organization.name}"
    for teacher in staff_of(organization):
        notify(teacher, user, "organization", text, reverse("organizations:members", args=[organization.slug]))
    return member
def notify_members(organization, actor, text, url, group=""):
    """Tell every member who can see something new; the person who posted it is skipped."""
    members = Membership.objects.filter(organization=organization, status="active").select_related("user")
    for member in members:
        if member.is_staff or not group or member.group.lower() == group.lower():
            notify(member.user, actor, "organization", text, url)
def invite_by_email(organization, actor, emails, role, group, send):
    """Create an invite for each new address and email it. Returns (created, skipped)."""
    created, skipped = [], []
    members = {email.lower() for email in Membership.objects.filter(organization=organization).values_list("user__email", flat=True)}
    open_invites = {email.lower() for email in Invite.objects.filter(organization=organization, accepted_at__isnull=True).values_list("email", flat=True)}
    for email in emails:
        if email.lower() in members or email.lower() in open_invites:
            skipped.append(email)
            continue
        invite = Invite.objects.create(organization=organization, email=email, role=role, group=group, created_by=actor)
        send(invite)
        created.append(invite)
        open_invites.add(email.lower())
    return created, skipped

def _streak(days, today):
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak
def task_load(organization, member, tasks=None):
    """The tasks a student has been given so far."""
    tasks = tasks if tasks is not None else list(Task.objects.filter(organization=organization))
    return [task for task in tasks if not task.group or task.group.lower() == member.group.lower()]
def student_growth(organization, group="", query="", sort="score"):
    """One row per student with their growth: built in a handful of queries, so it stays quick for hundreds of students."""
    members = list(students_of(organization, group))
    if query:
        needle = query.lower()
        members = [member for member in members if needle in display_name(member.user).lower() or needle in member.user.email.lower() or needle in (getattr(getattr(member.user, "profile", None), "handle", "") or "").lower()]
    ids = [member.user_id for member in members]
    now, today = timezone.now(), timezone.localdate()
    code_days = defaultdict(set)
    for user_id, created in ActivityEvent.objects.filter(user_id__in=ids, action__in=CODE_ACTIONS, created_at__gte=now - timedelta(days=60)).values_list("user_id", "created_at"):
        code_days[user_id].add(timezone.localdate(created))
    last_active = dict(ActivityEvent.objects.filter(user_id__in=ids).exclude(action="signed_in").values("user_id").annotate(last=Max("created_at")).values_list("user_id", "last"))
    projects = dict(Repository.objects.filter(owner_id__in=ids).exclude(languages={}).values("owner_id").annotate(total=Count("id")).values_list("owner_id", "total"))
    posts = dict(LearningPost.objects.filter(author_id__in=ids, is_public=True).values("author_id").annotate(total=Count("id")).values_list("author_id", "total"))
    tasks = list(Task.objects.filter(organization=organization))
    held = [live for live in LiveClass.objects.filter(organization=organization, starts_at__lt=now) if live.ends_at <= now]
    attended = defaultdict(set)
    for user_id, class_id in Attendance.objects.filter(live_class__in=held, student_id__in=ids, status__in=["present", "late"]).values_list("student_id", "live_class_id"):
        attended[user_id].add(class_id)
    submissions = defaultdict(list)
    for submission in Submission.objects.filter(task__organization=organization, student_id__in=ids).select_related("task"):
        submissions[submission.student_id].append(submission)
    rows = []
    for member in members:
        given = task_load(organization, member, tasks)
        done = {submission.task_id: submission for submission in submissions[member.user_id]}
        due = [task for task in given if task.due_at and task.due_at < now]
        scored = [submission for submission in done.values() if submission.score is not None and submission.task.points]
        profile = getattr(member.user, "profile", None)
        their_classes = [live.pk for live in held if not live.group or live.group.lower() == member.group.lower()]
        came = len([class_id for class_id in their_classes if class_id in attended[member.user_id]])
        rows.append({
            "classes_held": len(their_classes), "classes_attended": came, "attendance": round(came * 100 / len(their_classes)) if their_classes else None,
            "member": member, "user": member.user, "profile": profile, "score": profile.score if profile else 0, "rank": profile.rank if profile else None,
            "coding_days": len({day for day in code_days[member.user_id] if day > today - timedelta(days=30)}), "streak": _streak(code_days[member.user_id], today),
            "projects": projects.get(member.user_id, 0), "posts": posts.get(member.user_id, 0),
            "tasks_given": len(given), "tasks_submitted": len([task for task in given if task.id in done]), "tasks_approved": len([task for task in given if task.id in done and done[task.id].status == "approved"]),
            "tasks_missed": len([task for task in due if task.id not in done]),
            "task_percent": round(sum(submission.score * 100 / submission.task.points for submission in scored) / len(scored)) if scored else None,
            "last_active": last_active.get(member.user_id),
        })
    keys = {"score": lambda row: (-row["score"], display_name(row["user"]).lower()), "name": lambda row: display_name(row["user"]).lower(), "active": lambda row: -(row["last_active"].timestamp() if row["last_active"] else 0), "tasks": lambda row: (-(row["tasks_submitted"]), row["tasks_missed"]), "coding": lambda row: -row["coding_days"], "attendance": lambda row: -(row["attendance"] if row["attendance"] is not None else -1)}
    rows.sort(key=keys.get(sort, keys["score"]))
    return rows
def overview(organization):
    """The numbers on the organization's home: who's active, task progress, and what needs a teacher."""
    rows = student_growth(organization)
    week_ago = timezone.now() - timedelta(days=7)
    given = sum(row["tasks_given"] for row in rows)
    submitted = sum(row["tasks_submitted"] for row in rows)
    with_classes = [row["attendance"] for row in rows if row["attendance"] is not None]
    return {
        "attendance": round(sum(with_classes) / len(with_classes)) if with_classes else None, "next_class": next_class(organization, None),
        "students": len(rows), "active_week": len([row for row in rows if row["last_active"] and row["last_active"] >= week_ago]),
        "average_score": round(sum(row["score"] for row in rows) / len(rows)) if rows else 0,
        "completion": round(submitted * 100 / given) if given else None,
        "to_review": Submission.objects.filter(task__organization=organization, status="submitted").select_related("student__profile", "task")[:6],
        "to_review_count": Submission.objects.filter(task__organization=organization, status="submitted").count(),
        "pending": Membership.objects.filter(organization=organization, status="pending").count(),
        "posts_week": ChannelPost.objects.filter(organization=organization, created_at__gte=week_ago).count() + LearningPost.objects.filter(organization=organization, published_at__gte=week_ago).count(),
        "top": rows[:5], "quiet": [row for row in rows if not row["last_active"] or row["last_active"] < week_ago][:5],
        "upcoming": Task.objects.filter(organization=organization, due_at__gte=timezone.now()).order_by("due_at")[:5],
    }
def student_summary(user):
    """For a student's own dashboard: each organization with tasks still to do and the newest channel item."""
    summary = []
    for member in Membership.objects.filter(user=user, status="active").select_related("organization"):
        organization = member.organization
        given = task_load(organization, member)
        submitted = set(Submission.objects.filter(task__organization=organization, student=user).values_list("task_id", flat=True))
        open_tasks = sorted([task for task in given if task.id not in submitted], key=lambda task: (task.due_at is None, task.due_at or timezone.now()))
        latest = visible_to(ChannelPost.objects.filter(organization=organization), member).first()
        summary.append({"organization": organization, "member": member, "open_tasks": open_tasks[:3], "open_count": len(open_tasks), "latest": latest, "next_class": next_class(organization, member)})
    return summary

def classes_for(organization, member):
    return visible_to(LiveClass.objects.filter(organization=organization), member) if member else LiveClass.objects.filter(organization=organization)
def next_class(organization, member):
    """The class that's live now or coming up next."""
    now = timezone.now()
    for live in classes_for(organization, member).filter(starts_at__gte=now - timedelta(hours=12)).order_by("starts_at")[:20]:
        if live.ends_at > now:
            return live
    return None
def join_class(live_class, user):
    """Record a student's attendance when they join: present on time, late after the grace period. Teachers' marks win."""
    now = timezone.now()
    status = "late" if now > live_class.starts_at + timedelta(minutes=LiveClass.LATE_AFTER_MINUTES) else "present"
    attendance, created = Attendance.objects.get_or_create(live_class=live_class, student=user, defaults={"status": status, "joined_at": now})
    if not created and attendance.joined_at is None and attendance.marked_by is None:
        attendance.status, attendance.joined_at = status, now
        attendance.save(update_fields=["status", "joined_at"])
    return attendance
def class_roster(live_class):
    """Every student expected at a class, with their attendance if any."""
    students = students_of(live_class.organization, live_class.group)
    marks = {mark.student_id: mark for mark in live_class.attendance.all()}
    return [{"member": member, "attendance": marks.get(member.user_id)} for member in students]
def send_class_reminders():
    """Tell members a class starts soon; each class is reminded once. Returns how many classes were reminded."""
    now = timezone.now()
    due = LiveClass.objects.filter(reminded_at__isnull=True, starts_at__gt=now, starts_at__lte=now + timedelta(minutes=LiveClass.JOIN_OPENS_MINUTES)).select_related("organization")
    count = 0
    for live in due:
        starts = timezone.localtime(live.starts_at).strftime("%I:%M %p").lstrip("0")
        notify_members(live.organization, None, f"{live.title} starts at {starts}. Join from {live.organization.name}.", reverse("organizations:live_class", args=[live.organization.slug, live.pk]), live.group)
        live.reminded_at = now
        live.save(update_fields=["reminded_at"])
        count += 1
    return count
