"""Organization rules: who can see what, joining, invites, and the growth numbers teachers see."""
import csv
import io
import logging
import re
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlparse
import jwt
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Max, Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from apps.accounts.models import Profile
from apps.core.models import ActivityEvent, LearningPost, Repository
from apps.core.services import CODE_ACTIONS
from apps.notifications.services import notify
from . import recordings
from .models import Attendance, Certificate, ChannelPost, ClassRecording, Playlist, PlaylistItem, ParentAccess, Invite, LiveClass, Membership, Organization, Submission, Task
logger = logging.getLogger(__name__)
# Class points: task points earned, plus these for each class attended and each coding day in the last 30.
POINTS_PER_CLASS = 5
POINTS_PER_CODING_DAY = 1
# What teachers can see about a student, shown to students before they join.
SHARED_WITH_TEACHERS = ["Your score, rank and coding days", "How many projects and public posts you have", "Your task submissions and scores", "Your attendance at live classes", "When you were last active", "Teachers can share a progress report with your parent or guardian, and you can see who has it"]
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
RESERVED_SLUGS = {"new", "join", "invite", "certificates", "parent", "classes-now"}
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
    """The tasks a student has been given so far; tasks waiting for their release time don't count yet."""
    tasks = tasks if tasks is not None else list(Task.objects.filter(organization=organization))
    now = timezone.now()
    return [task for task in tasks if (not task.group or task.group.lower() == member.group.lower()) and not task.is_scheduled(now)]
def student_growth(organization, group="", query="", sort="score", users=None):
    """One row per student with their growth: built in a handful of queries, so it stays quick for hundreds of students."""
    members = list(students_of(organization, group))
    if users is not None:
        members = [member for member in members if member.user_id in users]
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
            "task_points": sum(submission.score for submission in scored),
            "last_active": last_active.get(member.user_id),
        })
    for row in rows:
        row["class_points"] = row["task_points"] + POINTS_PER_CLASS * row["classes_attended"] + POINTS_PER_CODING_DAY * row["coding_days"]
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
        "posts_week": published(ChannelPost.objects.filter(organization=organization, created_at__gte=week_ago)).count() + LearningPost.objects.filter(organization=organization, published_at__gte=week_ago).count(),
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
        latest = channel_posts_for(organization, member).first()
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
        if not LiveClass.objects.filter(pk=live.pk, reminded_at__isnull=True).update(reminded_at=now):
            continue  # another run already reminded this class
        starts = timezone.localtime(live.starts_at).strftime("%I:%M %p").lstrip("0")
        notify_members(live.organization, None, f"{live.title} starts at {starts}. Join from {live.organization.name}.", reverse("organizations:live_class", args=[live.organization.slug, live.pk]), live.group)
        count += 1
    return count
def remove_class_uploads():
    """Delete classes as they were uploaded once no student can still be catching up on the broadcast; the seekable
    copy the teacher edits stays. Returns how many were removed."""
    count = 0
    for recording in ClassRecording.objects.filter(upload_kept_until__lte=timezone.now()):
        if recordings.remove_upload(recording):  # a file still being read (Windows) is tried again next time
            ClassRecording.objects.filter(pk=recording.pk).update(upload_kept_until=None)
            count += 1
    return count
def run_due_jobs():
    """Everything that happens on a schedule: scheduled posts, lectures and tasks, class reminders, and removing
    class uploads that have a seekable copy. Returns (published, released, reminded, removed)."""
    return publish_due_posts(), release_due_items(), send_class_reminders(), remove_class_uploads()
def upcoming_classes(user, days=7, limit=6):
    """Live classes for someone's dashboard: live now or starting within `days`, from every organization they're in.
    Each has .organization, .member and .current (the state now) set; students also get .mine (their attendance)."""
    now = timezone.now()
    classes = []
    for member in Membership.objects.filter(user=user, status="active").select_related("organization"):
        window = classes_for(member.organization, member).filter(starts_at__gte=now - timedelta(hours=12), starts_at__lte=now + timedelta(days=days)).select_related("organization")
        for live in window.order_by("starts_at")[:limit * 2]:
            if live.ends_at > now:
                live.member, live.current = member, live.state(now)
                classes.append(live)
    classes.sort(key=lambda live: live.starts_at)
    classes = classes[:limit]
    marks = dict(Attendance.objects.filter(live_class__in=classes, student=user).values_list("live_class_id", "status"))
    for live in classes:
        live.mine = marks.get(live.pk)
    return classes
def class_alerts(user):
    """Classes to alert someone about right now: open to join (from 15 minutes before) or live, and not joined yet."""
    return [live for live in upcoming_classes(user, days=1, limit=10) if live.current in {"open", "live"} and not live.mine]
def _ics_text(text):
    """Text escaped for an iCalendar value: backslashes, semicolons, commas and line breaks."""
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
def class_calendar(classes, page_url):
    """An iCalendar file for one class or a series, with an alarm 15 minutes before each class.
    page_url(live) gives the class page; the meeting link itself stays in MyProgress, which takes attendance."""
    stamp = lambda moment: moment.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MyProgress//Live classes//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for live in classes:
        url = page_url(live)
        lines += ["BEGIN:VEVENT", f"UID:live-class-{live.pk}@myprogress", f"DTSTAMP:{stamp(timezone.now())}", f"DTSTART:{stamp(live.starts_at)}", f"DTEND:{stamp(live.ends_at)}",
                  f"SUMMARY:{_ics_text(live.title)} ({_ics_text(live.organization.name)})", f"DESCRIPTION:{_ics_text((live.agenda + chr(10) + chr(10) if live.agenda else '') + 'Join from MyProgress: ' + url)}", f"URL:{url}",
                  "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_text(live.title)} starts in 15 minutes", "TRIGGER:-PT15M", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    # Lines longer than 75 octets are folded, as the format requires.
    folded = []
    for line in lines:
        data = line.encode("utf-8")
        while len(data) > 75:
            cut = 75
            while (data[cut] & 0xC0) == 0x80:  # don't split a character
                cut -= 1
            folded.append(data[:cut].decode("utf-8"))
            data = b" " + data[cut:]
        folded.append(data.decode("utf-8"))
    return "\r\n".join(folded) + "\r\n"

LEADERBOARD_METRICS = [("class_points", "Class points"), ("task_points", "Task points"), ("attendance", "Attendance"), ("coding_days", "Coding days"), ("score", "MyProgress score")]
def leaderboard(organization, metric="class_points", group=""):
    """Students ranked by one measure; equal values share a rank, and students with no attendance yet come last on that board."""
    rows = student_growth(organization, group=group)
    value = (lambda row: row[metric] if row[metric] is not None else -1)
    rows.sort(key=lambda row: (-value(row), display_name(row["user"]).lower()))
    rank, previous = 0, None
    for position, row in enumerate(rows, start=1):
        if value(row) != previous:
            rank, previous = position, value(row)
        row["position"], row["value"] = rank, row[metric]
    return rows
def issue_certificates(organization, actor, students, title, description):
    """Give each student a certificate, skipping anyone who already holds one with the same title. Returns those created."""
    holders = set(Certificate.objects.filter(organization=organization, title__iexact=title, revoked_at__isnull=True).values_list("student_id", flat=True))
    created = []
    for student in students:
        if student.pk in holders:
            continue
        certificate = Certificate.objects.create(organization=organization, student=student, title=title, description=description, issued_by=actor)
        notify(student, actor, "organization", f"{organization.name} awarded you a certificate: {title}", reverse("organizations:certificate", args=[certificate.code]))
        created.append(certificate)
    return created
def progress_report(member):
    """What a parent sees: the student's attendance, tasks, coding and certificates in this organization."""
    organization, now = member.organization, timezone.now()
    row = (student_growth(organization, users={member.user_id}) or [None])[0]
    given = task_load(organization, member)
    submissions = {submission.task_id: submission for submission in Submission.objects.filter(task__organization=organization, student=member.user)}
    tasks = [{"task": task, "submission": submissions.get(task.pk), "missed": task.due_at and task.due_at < now and task.pk not in submissions} for task in given]
    held = [live for live in classes_for(organization, member).filter(starts_at__lt=now).order_by("-starts_at")[:20] if live.ends_at <= now][:10]
    marks = dict(Attendance.objects.filter(live_class__in=held, student=member.user).values_list("live_class_id", "status"))
    return {
        "row": row, "upcoming": [item for item in tasks if not item["submission"] and item["task"].due_at and item["task"].due_at >= now][:5],
        "recent_tasks": sorted([item for item in tasks if item["submission"] or item["missed"]], key=lambda item: item["task"].due_at or item["task"].created_at, reverse=True)[:8],
        "classes": [{"live": live, "status": marks.get(live.pk, "absent")} for live in held],
        "certificates": Certificate.objects.filter(organization=organization, student=member.user, revoked_at__isnull=True),
    }
IMPORT_LIMIT = 500
IMPORT_COLUMNS = {"email": "email", "e-mail": "email", "email address": "email", "name": "name", "full name": "name", "student name": "name", "batch": "group", "group": "group", "class": "group", "section": "group", "role": "role", "type": "role"}
def parse_member_csv(organization, data):
    """Read an uploaded spreadsheet of people to invite and say what will happen to each row, before anything is sent."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in row)]
    if not rows:
        return [], "The file is empty."
    header = [cell.strip().lower() for cell in rows[0]]
    if any(IMPORT_COLUMNS.get(cell) == "email" for cell in header):
        columns = [IMPORT_COLUMNS.get(cell) for cell in header]
        rows = rows[1:]
    else:
        columns = ["email", "name", "group", "role"]
    if len(rows) > IMPORT_LIMIT:
        return [], f"Import up to {IMPORT_LIMIT} people at a time; this file has {len(rows)}."
    members = {email.lower() for email in Membership.objects.filter(organization=organization).values_list("user__email", flat=True)}
    invited = {email.lower() for email in Invite.objects.filter(organization=organization, accepted_at__isnull=True).values_list("email", flat=True)}
    seen, parsed = set(), []
    first_line = 2 if header and any(IMPORT_COLUMNS.get(cell) == "email" for cell in header) else 1
    for number, cells in enumerate(rows, start=first_line):
        record = {"line": number, "email": "", "name": "", "group": "", "role": "student"}
        for column, cell in zip(columns, cells):
            if column:
                record[column] = cell.strip()
        record["email"] = record["email"].lower()
        record["name"], record["group"] = record["name"][:120], record["group"][:60]
        record["role"] = "teacher" if record["role"].strip().lower() == "teacher" else "student"
        try:
            validate_email(record["email"])
            valid = True
        except ValidationError:
            valid = False
        if not valid:
            record["status"] = "Invalid email"
        elif record["email"] in seen:
            record["status"] = "Listed twice"
        elif record["email"] in members:
            record["status"] = "Already a member"
        elif record["email"] in invited:
            record["status"] = "Already invited"
        else:
            record["status"] = "ok"
        seen.add(record["email"])
        parsed.append(record)
    return parsed, ""
def invite_rows(organization, actor, rows, send):
    """Create and send an invite for each new row from an import. Returns the invites created."""
    created = []
    members = {email.lower() for email in Membership.objects.filter(organization=organization).values_list("user__email", flat=True)}
    invited = {email.lower() for email in Invite.objects.filter(organization=organization, accepted_at__isnull=True).values_list("email", flat=True)}
    for row in rows:
        if row["email"] in members or row["email"] in invited:
            continue
        invite = Invite.objects.create(organization=organization, email=row["email"], name=row["name"], role=row["role"], group=row["group"], created_by=actor)
        send(invite)
        created.append(invite)
        invited.add(row["email"])
    return created
def published(posts):
    """Channel posts students may see now: posted straight away, or whose scheduled time has come."""
    return posts.filter(Q(publish_at__isnull=True) | Q(publish_at__lte=timezone.now()))
def channel_posts_for(organization, member):
    posts = visible_to(ChannelPost.objects.filter(organization=organization), member)
    return posts if member and member.is_staff else published(posts)
def announce_post(post, actor=None):
    """Tell members about a channel post, once."""
    notify_members(post.organization, actor or post.author, f"{post.organization.name}: {post.title}", f"{channel_url(post.organization)}?tab=posts#post-{post.pk}", post.group)
    post.notified_at = timezone.now()
    post.save(update_fields=["notified_at"])
def publish_due_posts():
    """Announce scheduled posts whose time has come. Returns how many were published."""
    now = timezone.now()
    due = ChannelPost.objects.filter(publish_at__lte=now, notified_at__isnull=True).select_related("organization", "author")
    count = 0
    for post in due:
        if ChannelPost.objects.filter(pk=post.pk, notified_at__isnull=True).update(notified_at=now):  # claimed by this run
            announce_post(post)
            count += 1
    return count
def released(items):
    """Lectures or tasks students may see now: released straight away, or whose release time has come."""
    return items.filter(Q(publish_at__isnull=True) | Q(publish_at__lte=timezone.now()))
def tasks_for(organization, member):
    tasks = visible_to(Task.objects.filter(organization=organization), member)
    return tasks if member and member.is_staff else released(tasks)
def lessons_for(organization, member):
    """The organization's lectures and notes, and its class recordings even when they were published for everyone
    (those leave the organization so they can be public, but they're still the class's lectures)."""
    recordings_published = ClassRecording.objects.filter(live_class__organization=organization, post__isnull=False).values("post")
    lessons = LearningPost.objects.filter(Q(organization=organization) | Q(pk__in=recordings_published, is_public=True))
    return lessons if member and member.is_staff else released(lessons)
def lesson_organization(post):
    """The organization a lecture belongs to: the one it's shared with, or the one whose class it recorded."""
    if post.organization_id:
        return post.organization
    recording = ClassRecording.objects.filter(post=post).select_related("live_class__organization").first()
    return recording.live_class.organization if recording else None
def playlists_for(organization, member):
    """Playlists for everyone in the organization, plus those for the member's batch. Staff see them all."""
    return visible_to(Playlist.objects.filter(organization=organization), member)
def playlist_lectures(playlist, member):
    """The playlist's items this member may open, in order, each with its lecture or notes as .post."""
    allowed = lessons_for(playlist.organization, member)
    return list(playlist.items.filter(post__in=allowed).select_related("post__author__profile").order_by("position", "pk"))
def add_to_playlist(playlist, post):
    """Put a lecture at the end of a playlist, once. Returns True if it was added."""
    end = playlist.items.aggregate(end=Max("position"))["end"]
    _, created = PlaylistItem.objects.get_or_create(playlist=playlist, post=post, defaults={"position": 0 if end is None else end + 1})
    if created:
        Playlist.objects.filter(pk=playlist.pk).update(updated_at=timezone.now())
    return created
def announce_lesson(post, actor=None):
    """Tell the organization's members a new lecture or set of notes is in their channel, once."""
    label = "lecture" if post.kind == "video" else "notes"
    notify_members(post.organization, actor or post.author, f"New {label} in {post.organization.name}: {post.title}", reverse("learning:detail", args=[post.pk]))
    type(post).objects.filter(pk=post.pk).update(announced_at=timezone.now())
def announce_task(task, actor=None):
    when = timezone.localtime(task.due_at) if task.due_at else None
    due = f", due {when:%b} {when.day}" if when else ""
    notify_members(task.organization, actor or task.created_by, f"New task in {task.organization.name}: {task.title}{due}", reverse("organizations:task", args=[task.organization.slug, task.pk]), task.group)
    Task.objects.filter(pk=task.pk).update(announced_at=timezone.now())
def release_due_items():
    """Announce lectures and tasks whose release time has come. Returns how many were released."""
    now, count = timezone.now(), 0
    for post in LearningPost.objects.filter(organization__isnull=False, publish_at__lte=now, announced_at__isnull=True).select_related("organization", "author"):
        if LearningPost.objects.filter(pk=post.pk, announced_at__isnull=True).update(announced_at=now):
            announce_lesson(post)
            count += 1
    for task in Task.objects.filter(publish_at__lte=now, announced_at__isnull=True).select_related("organization", "created_by"):
        if Task.objects.filter(pk=task.pk, announced_at__isnull=True).update(announced_at=now):
            announce_task(task)
            count += 1
    return count
def class_dates(starts_at, repeat, days=(), count=1):
    """When each class in a series happens, keeping the same local time even across daylight-saving changes."""
    first = timezone.localtime(starts_at)
    if repeat == "weekly":
        weekdays = {first.weekday()}
    elif repeat == "weekdays":
        weekdays = {0, 1, 2, 3, 4}
    elif repeat == "days":
        weekdays = {int(day) for day in days}
    else:
        return [starts_at]
    dates, day = [], first.date()
    while len(dates) < count:
        if day.weekday() in weekdays:
            dates.append(timezone.make_aware(datetime.combine(day, first.time().replace(tzinfo=None))))
        day += timedelta(days=1)
    return dates
def schedule_classes(organization, actor, data):
    """Create one class, or a repeating series sharing one meeting room. Returns the classes created."""
    fields = {key: data[key] for key in ["title", "agenda", "duration_minutes", "meeting_link", "group"]}
    repeat = data.get("repeat") or "none"
    dates = class_dates(data["starts_at"], repeat, data.get("days") or (), data.get("occurrences") or 1)
    series = secrets.token_hex(8) if len(dates) > 1 else ""
    created = []
    for when in dates:
        live = LiveClass(organization=organization, created_by=actor, starts_at=when, series=series, **fields)
        live.save()
        fields["meeting_link"] = live.meeting_link  # the whole series uses the first class's room
        created.append(live)
    first = timezone.localtime(created[0].starts_at)
    at = first.strftime("%I:%M %p").lstrip("0")
    if len(created) == 1:
        text = f"Live class scheduled: {created[0].title}, {first:%a} {first:%b} {first.day} at {at}"
    else:
        chosen = [dict(WEEKDAY_NAMES)[str(day)] for day in sorted({int(day) for day in data.get("days") or ()})]
        listed = ", ".join(chosen[:-1]) + " and " + chosen[-1] if len(chosen) > 1 else "".join(chosen)
        names = {"weekly": f"every {first:%A}", "weekdays": "every weekday"}.get(repeat) or "every " + listed
        text = f"Live classes scheduled: {created[0].title}, {names} at {at}, {len(created)} classes from {first:%b} {first.day}"
    notify_members(organization, actor, text, reverse("organizations:live_class", args=[organization.slug, created[0].pk]), created[0].group)
    return created
WEEKDAY_NAMES = [("0", "Monday"), ("1", "Tuesday"), ("2", "Wednesday"), ("3", "Thursday"), ("4", "Friday"), ("5", "Saturday"), ("6", "Sunday")]
def series_position(live):
    """(number, total) of a class within its series, or None."""
    if not live.series:
        return None
    ids = list(LiveClass.objects.filter(series=live.series).order_by("starts_at").values_list("pk", flat=True))
    return (ids.index(live.pk) + 1, len(ids)) if live.pk in ids else None
DIGEST_GAP = timedelta(days=6)
def weekly_digest(member, now=None):
    """One student's last 7 days and next 7, for the weekly parent email. None when there's nothing to say."""
    organization, now = member.organization, now or timezone.now()
    since, until = now - timedelta(days=7), now + timedelta(days=7)
    visible = classes_for(organization, member)
    held = [live for live in visible.filter(starts_at__gte=since, starts_at__lt=now).order_by("starts_at") if live.ends_at <= now]
    marks = dict(Attendance.objects.filter(live_class__in=held, student=member.user).values_list("live_class_id", "status"))
    classes = [{"live": live, "status": marks.get(live.pk, "absent")} for live in held]
    given = task_load(organization, member)
    submissions = {submission.task_id: submission for submission in Submission.objects.filter(task__organization=organization, student=member.user)}
    def this_week(submission):
        return submission.submitted_at >= since or (submission.reviewed_at and submission.reviewed_at >= since)
    tasks = [{"task": task, "submission": submissions[task.pk]} for task in given if task.pk in submissions and this_week(submissions[task.pk])]
    missed = sorted([task for task in given if task.due_at and since <= task.due_at < now and task.pk not in submissions], key=lambda task: task.due_at)
    due = sorted([task for task in given if task.due_at and now <= task.due_at < until and task.pk not in submissions], key=lambda task: task.due_at)
    next_classes = list(visible.filter(starts_at__gte=now, starts_at__lt=until).order_by("starts_at")[:10])
    if not (classes or tasks or missed or due or next_classes):
        return None
    return {
        "since": since, "now": now, "classes": classes, "attended": len([item for item in classes if item["status"] != "absent"]),
        "tasks": tasks, "missed": missed, "due": due, "next_classes": next_classes,
        "row": (student_growth(organization, users={member.user_id}) or [None])[0],
    }
def send_parent_digests(site_url, now=None):
    """Email each parent a summary of their student's week. Each parent gets at most one every 6 days, so an extra run sends nothing twice.
    Returns (sent, quiet): quiet parents had nothing new this week and get nothing."""
    now = now or timezone.now()
    accesses = (ParentAccess.objects.filter(revoked_at__isnull=True, digest_stopped_at__isnull=True, member__status="active", member__role="student", member__organization__parent_digest=True)
                .filter(Q(digest_sent_at__isnull=True) | Q(digest_sent_at__lte=now - DIGEST_GAP)).select_related("member__organization", "member__user__profile"))
    digests, sent, quiet = {}, 0, 0
    for access in accesses:
        member = access.member
        if member.pk not in digests:
            digests[member.pk] = weekly_digest(member, now)
        digest = digests[member.pk]
        if digest is None:
            quiet += 1
            continue
        stop_url = site_url + reverse("organizations:parent_emails", args=[access.token])
        context = {"access": access, "member": member, "organization": member.organization, "student": display_name(member.user), "digest": digest,
                   "report_url": site_url + reverse("organizations:parent_report", args=[access.token]), "stop_url": stop_url}
        message = EmailMultiAlternatives(f"{context['student']}'s week at {member.organization.name}", render_to_string("organizations/emails/parent_digest.txt", context), None, [access.email],
                                         headers={"List-Unsubscribe": f"<{stop_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
        message.attach_alternative(render_to_string("organizations/emails/parent_digest.html", context), "text/html")
        try:
            message.send()
        except Exception:
            logger.exception("Could not send the weekly email for parent access %s", access.pk)
            continue
        access.digest_sent_at = now
        access.save(update_fields=["digest_sent_at"])
        sent += 1
    return sent, quiet
JITSI_ROOM = re.compile(r"[A-Za-z0-9_-]{6,120}")
def video_room(live):
    """The Jitsi room a class is held in inside MyProgress, or None when it links out instead:
    no Jitsi server is set up, or the teacher gave the class its own link (Zoom, Google Meet...)."""
    domain = settings.JITSI_DOMAIN.lower()
    link = urlparse(live.meeting_link)
    room = link.path.strip("/")
    if not domain or link.scheme != "https" or not JITSI_ROOM.fullmatch(room):
        return None
    host = link.netloc.lower()
    # Rooms made for classes before the server was set up move to it; they were only ever named here.
    return room if host == domain or (host == "meet.jit.si" and room.startswith("MyProgress-")) else None
def video_token(live, user, staff, room, now=None):
    """A signed pass into one class room, for Jitsi servers with token authentication. Teachers come in as moderators."""
    if not (settings.JITSI_APP_ID and settings.JITSI_APP_SECRET):
        return ""
    now = now or timezone.now()
    payload = {
        "aud": "jitsi", "iss": settings.JITSI_APP_ID, "sub": settings.JITSI_DOMAIN, "room": room, "moderator": staff,
        "nbf": int((now - timedelta(minutes=5)).timestamp()), "exp": int((max(now, live.ends_at) + timedelta(hours=2)).timestamp()),
        "context": {"user": {"id": str(user.pk), "name": display_name(user), "moderator": staff, "affiliation": "owner" if staff else "member"}},
    }
    return jwt.encode(payload, settings.JITSI_APP_SECRET, algorithm="HS256")
