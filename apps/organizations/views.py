"""Organization workspace: home, students' growth, the private channel, tasks, invites and settings."""
import csv
import logging
import os
import secrets
from datetime import timedelta
from itertools import groupby
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files import File
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from apps.accounts.models import Profile
from apps.common.ratelimit import rate_limit
from apps.common.templatetags.ui import public_name
from apps.common.views import ranged_file_response, stored_file_response
from apps.core.models import ContentView, LearningPost
from apps.core.services import progress_facts, score_breakdown
from apps.learning.formatting import render_article
from apps.learning.media import MAX_THUMBNAIL_BYTES, place_post_files
from apps.learning.timeline import clean_captions, clean_chapters, format_stamp, remap_captions, remap_chapters
from apps.learning.views import studio_options
from apps.earnings.services import sync_post_coins
from apps.notifications.services import notify
from . import recordings, services
from .middleware import OrganizationUnavailable
from .forms import CertificateForm, ChannelPostForm, ParentForm, InviteForm, LiveClassForm, MemberForm, OrganizationForm, RecordingForm, ReviewForm, SubmissionForm, TaskForm
from .models import Attendance, Certificate, ChannelPost, ClassMessage, ClassRecording, ParentAccess, ChannelSeen, Invite, LiveClass, Membership, Organization, Submission, Task
logger = logging.getLogger(__name__)
GROWTH_SORTS = [("score", "Score"), ("active", "Recently active"), ("attendance", "Attendance"), ("coding", "Coding days"), ("tasks", "Tasks done"), ("name", "Name")]

def _organization(request, slug, staff=False):
    """The organization and the viewer's membership. Outsiders get the same 404 whether or not it exists, so private organizations stay invisible."""
    organization = Organization.objects.filter(slug=slug).first()
    member = services.membership(organization, request.user) if organization else None
    if member is None or (staff and not member.is_staff):
        raise OrganizationUnavailable(staff_only=member is not None)
    return organization, member
def _render(request, template, organization, member, section, context=None):
    groups = sorted({group for group in Membership.objects.filter(organization=organization).exclude(group="").values_list("group", flat=True)}, key=str.lower)
    return render(request, f"organizations/{template}", {"organization": organization, "member": member, "org_section": section, "section": "organization", "org_groups": groups, **(context or {})})
def _back(request, fallback):
    target = request.POST.get("next", "")
    return redirect(target if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}) else fallback)

@login_required(login_url="landing:home")
def home_view(request):
    """Where the Organization link goes: your organization, the list if you're in several, or a way to start or join one."""
    staff = list(services.staff_organizations(request.user))
    if len(staff) == 1:
        return redirect("organizations:overview", slug=staff[0].slug)
    joined = list(services.member_organizations(request.user))
    if len(joined) == 1 and not staff:
        return redirect("organizations:channel", slug=joined[0].slug)
    profile = Profile.objects.filter(user=request.user).first()
    if not joined and profile and profile.role == "organization":
        return redirect("organizations:create")
    pending = Membership.objects.filter(user=request.user, status="pending").select_related("organization")
    return render(request, "organizations/home.html", {"section": "organization", "organizations": joined, "staff_ids": {organization.pk for organization in staff}, "pending": pending})
@login_required(login_url="landing:home")
@rate_limit("create-organization", 5, 3600)
def create_view(request):
    form = OrganizationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        organization = services.create_organization(request.user, form.cleaned_data)
        messages.success(request, f"{organization.name} is ready. Share the invite link with your students.")
        return redirect("organizations:invite", slug=organization.slug)
    return render(request, "organizations/create.html", {"section": "organization", "form": form})

@login_required(login_url="landing:home")
def overview_view(request, slug):
    organization, member = _organization(request, slug)
    if not member.is_staff:
        return redirect("organizations:channel", slug=slug)
    return _render(request, "overview.html", organization, member, "overview", {"stats": services.overview(organization), "invite_url": request.build_absolute_uri(reverse("organizations:join", args=[organization.invite_code]))})

@login_required(login_url="landing:home")
def members_view(request, slug):
    organization, member = _organization(request, slug, staff=True)
    group, query = request.GET.get("group", "").strip()[:60], request.GET.get("q", "").strip()[:80]
    sort = request.GET.get("sort") if request.GET.get("sort") in dict(GROWTH_SORTS) else "score"
    rows = services.student_growth(organization, group=group, query=query, sort=sort)
    if request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{organization.slug}-students-{timezone.localdate():%Y-%m-%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["name", "email", "batch", "score", "rank", "coding_days_30", "streak", "projects", "public_posts", "tasks_given", "tasks_submitted", "tasks_approved", "tasks_missed", "task_score_percent", "classes_held", "classes_attended", "attendance_percent", "last_active"])
        for row in rows:
            writer.writerow([services.display_name(row["user"]), row["user"].email, row["member"].group, row["score"], row["rank"] or "", row["coding_days"], row["streak"], row["projects"], row["posts"], row["tasks_given"], row["tasks_submitted"], row["tasks_approved"], row["tasks_missed"], "" if row["task_percent"] is None else row["task_percent"], row["classes_held"], row["classes_attended"], "" if row["attendance"] is None else row["attendance"], row["last_active"].strftime("%Y-%m-%d") if row["last_active"] else ""])
        return response
    staff = Membership.objects.filter(organization=organization, status="active", role__in=["owner", "teacher"]).select_related("user__profile")
    pending = Membership.objects.filter(organization=organization, status="pending").select_related("user__profile")
    return _render(request, "members.html", organization, member, "members", {"rows": rows, "staff": staff, "pending": pending, "group": group, "query": query, "sort": sort, "sorts": GROWTH_SORTS, "week_ago": timezone.now() - timedelta(days=7)})
@login_required(login_url="landing:home")
def member_detail_view(request, slug, user_id):
    organization, member = _organization(request, slug, staff=True)
    student = get_object_or_404(Membership.objects.select_related("user__profile"), organization=organization, user_id=user_id, status="active")
    form = MemberForm(request.POST or None, instance=student, can_change_role=member.role == "owner" and student.role != "owner")
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("organizations:member", slug=slug, user_id=user_id)
    row = next((row for row in services.student_growth(organization) if row["user"].pk == student.user_id), None)
    tasks = services.task_load(organization, student)
    submissions = {submission.task_id: submission for submission in Submission.objects.filter(task__organization=organization, student=student.user)}
    return _render(request, "member_detail.html", organization, member, "members", {
        "student": student, "row": row, "form": form, "breakdown": score_breakdown(student.user, progress_facts(student.user)),
        "task_rows": [{"task": task, "submission": submissions.get(task.pk)} for task in tasks], "now": timezone.now(),
        "recent_posts": student.user.learning_posts.filter(is_public=True).order_by("-published_at")[:4],
        "parents": student.parents.all(), "parent_form": ParentForm(),
    })
@login_required(login_url="landing:home")
@require_POST
def member_action_view(request, slug, user_id):
    organization, member = _organization(request, slug, staff=True)
    target = get_object_or_404(Membership, organization=organization, user_id=user_id)
    action = request.POST.get("action")
    if target.role == "owner":
        messages.error(request, "The owner can't be removed.")
    elif action == "approve" and target.status == "pending":
        target.status = "active"
        target.save(update_fields=["status"])
        notify(target.user, request.user, "organization", f"You're now a member of {organization.name}.", services.channel_url(organization))
        messages.success(request, f"{services.display_name(target.user)} can now see {organization.name}.")
    elif action in {"decline", "remove"} and (member.role == "owner" or target.role == "student"):
        target.delete()
        messages.success(request, f"{services.display_name(target.user)} was removed." if action == "remove" else "Request declined.")
    else:
        messages.error(request, "You can't do that.")
    return _back(request, reverse("organizations:members", args=[slug]))

def _invite_sender(request, organization):
    """Emails one invite: a personal greeting when the import gave a name, and what joining means."""
    def send(invite):
        link = request.build_absolute_uri(reverse("organizations:accept_invite", args=[invite.token]))
        greeting = f"Hi {invite.name.split()[0]}," if invite.name.strip() else "Hi,"
        batch = f" in {invite.group}" if invite.group else ""
        body = f"{greeting}\n\n{services.display_name(request.user)} invited you to join {organization.name}{batch} on MyProgress as a {invite.get_role_display().lower()}.\n\nJoin here:\n{link}\n\nMembers see the organization's lectures, notes, study material and tasks. Teachers can see each student's progress on MyProgress.\n"
        try:
            send_mail(f"Join {organization.name} on MyProgress", body, None, [invite.email])
        except Exception:
            logger.exception("Could not send an organization invite to %s", invite.email)
    return send
@login_required(login_url="landing:home")
def invite_view(request, slug):
    organization, member = _organization(request, slug, staff=True)
    form = InviteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        created, skipped = services.invite_by_email(organization, request.user, form.cleaned_data["emails"], form.cleaned_data["role"], form.cleaned_data["group"].strip(), _invite_sender(request, organization))
        messages.success(request, f"Invited {len(created)} {'person' if len(created) == 1 else 'people'}." + (f" {len(skipped)} already invited or a member." if skipped else ""))
        return redirect("organizations:invite", slug=slug)
    invites = Paginator(Invite.objects.filter(organization=organization).select_related("accepted_by"), 25).get_page(request.GET.get("page"))
    return _render(request, "invite.html", organization, member, "invite", {"form": form, "invites": invites, "invite_url": request.build_absolute_uri(reverse("organizations:join", args=[organization.invite_code]))})
def join_view(request, code):
    """The shared invite link. Shows the organization and exactly what teachers will see before anyone joins."""
    organization = get_object_or_404(Organization, invite_code=code)
    return _join(request, organization, None)
def accept_invite_view(request, token):
    invite = get_object_or_404(Invite.objects.select_related("organization"), token=token)
    if invite.accepted_at and invite.accepted_by != request.user:
        messages.error(request, "This invitation was already used. Ask for a new one.")
        return redirect("landing:dashboard" if request.user.is_authenticated else "landing:home")
    return _join(request, invite.organization, invite)
def _mask_email(email):
    name, _, domain = email.partition("@")
    return f"{name[:1]}{'•' * max(len(name) - 1, 2)}@{domain}"
def _invite_problem(invite, user):
    """Why this account can't use an emailed invitation ("" if it can), and whether confirming the email fixes it.
    An invitation belongs to the address it was sent to, so a forwarded or leaked link is useless to anyone else.
    Teacher invitations also need that address confirmed, so nobody can sign up with someone else's email first."""
    if invite is None or not user.is_authenticated or (invite.accepted_by_id == user.pk):
        return "", False
    if user.email.strip().lower() != invite.email.strip().lower():
        return f"This invitation was sent to {_mask_email(invite.email)}. Sign in with that email to accept it, or ask {invite.organization.name} to invite {user.email}.", False
    profile = Profile.objects.filter(user=user).first()
    if invite.role != "student" and not (profile and profile.email_verified_at):
        return "Teacher invitations need a confirmed email. Open the confirmation link we emailed you, then open this invitation again.", True
    return "", False
def _join(request, organization, invite):
    existing = Membership.objects.filter(organization=organization, user=request.user).first() if request.user.is_authenticated else None
    problem, needs_confirmation = ("", False) if existing else _invite_problem(invite, request.user)
    if request.method == "POST" and request.user.is_authenticated and not existing and not problem:
        member = services.join(organization, request.user, invite)
        if member.status == "active":
            messages.success(request, f"Welcome to {organization.name}.")
            return redirect("organizations:channel", slug=organization.slug)
        messages.success(request, f"Request sent. A teacher at {organization.name} will approve it.")
        return redirect("organizations:home")
    if existing and existing.status == "active":
        return redirect("organizations:channel", slug=organization.slug)
    return render(request, "organizations/join.html", {"organization": organization, "invite": invite, "existing": existing, "invite_problem": problem, "needs_confirmation": needs_confirmation, "shared": services.SHARED_WITH_TEACHERS, "member_count": organization.memberships.filter(status="active").count()})
@login_required(login_url="landing:home")
@require_POST
def leave_view(request, slug):
    organization, member = _organization(request, slug)
    if member.role == "owner":
        messages.error(request, "The owner can't leave. Transfer or delete the organization instead.")
        return redirect("organizations:settings", slug=slug)
    member.delete()
    messages.success(request, f"You left {organization.name}. Its teachers can no longer see your progress.")
    return redirect("organizations:home")

def _channel_items(organization, member, kind=""):
    """Announcements, study material, and lectures and notes shared from the studio, newest first. Teachers also get
    the posts still waiting for their scheduled time, kept apart from what students can see."""
    now = timezone.now()
    posts = services.channel_posts_for(organization, member).select_related("author__profile")
    lessons = services.lessons_for(organization, member).select_related("author__profile").annotate(comment_count=Count("comments", distinct=True))
    if kind in {"announcement", "material"}:
        lessons = lessons.none()
        posts = posts.filter(kind=kind)
    elif kind in {"video", "article"}:
        posts = posts.none()
        lessons = lessons.filter(kind=kind)
    posts = list(posts[:200])
    scheduled = sorted([{"type": "post", "item": post, "when": post.publish_at, "pinned": False} for post in posts if post.is_scheduled(now)], key=lambda entry: entry["when"])
    items = [{"type": "post", "item": post, "when": post.shown_at, "pinned": post.pinned} for post in posts if not post.is_scheduled(now)]
    lessons = list(lessons[:200])
    scheduled += [{"type": "lesson", "item": lesson, "when": lesson.publish_at, "pinned": False} for lesson in lessons if lesson.publish_at and lesson.publish_at > now]
    scheduled.sort(key=lambda entry: entry["when"])
    items += [{"type": "lesson", "item": lesson, "when": lesson.publish_at or lesson.published_at, "pinned": False} for lesson in lessons if not (lesson.publish_at and lesson.publish_at > now)]
    items.sort(key=lambda entry: entry["when"], reverse=True)
    return scheduled, [entry for entry in items if entry["pinned"]], [entry for entry in items if not entry["pinned"]]
@login_required(login_url="landing:home")
def channel_view(request, slug):
    organization, member = _organization(request, slug)
    kind = request.GET.get("kind", "")
    form = ChannelPostForm(request.POST or None, request.FILES or None) if member.is_staff else None
    if request.method == "POST":
        if not member.is_staff:
            raise Http404
        if form.is_valid():
            post = form.save(commit=False)
            post.organization, post.author = organization, request.user
            post.save()
            if post.publish_at:
                when = timezone.localtime(post.publish_at)
                messages.success(request, f"Scheduled for {when:%a} {when:%b} {when.day}, {when.strftime('%I:%M %p').lstrip('0')}. Students can't see it until then.")
            else:
                services.announce_post(post, request.user)
                messages.success(request, "Posted to the channel.")
            return redirect("organizations:channel", slug=slug)
    scheduled, pinned, items = _channel_items(organization, member, kind)
    page = Paginator(items, 20).get_page(request.GET.get("page"))
    today = timezone.localdate()
    def day_label(entry):
        day = timezone.localtime(entry["when"]).date()
        if day == today:
            return "Today"
        return "Yesterday" if (today - day).days == 1 else f"{day:%A}, {day:%b} {day.day}"
    days = [(label, list(entries)) for label, entries in groupby(page.object_list, key=day_label)]
    post_ids = [entry["item"].pk for entry in pinned + list(page.object_list) if entry["type"] == "post"]
    ChannelSeen.objects.bulk_create([ChannelSeen(post_id=post_id, user=request.user) for post_id in post_ids], ignore_conflicts=True)
    seen = dict(ChannelSeen.objects.filter(post_id__in=post_ids).values("post_id").annotate(total=Count("id")).values_list("post_id", "total")) if member.is_staff else {}
    lesson_ids = [entry["item"].pk for entry in pinned + list(page.object_list) if entry["type"] == "lesson"]
    watched = dict(ContentView.objects.filter(post_id__in=lesson_ids, viewer__isnull=False).values("post_id").annotate(total=Count("viewer", distinct=True)).values_list("post_id", "total")) if member.is_staff else {}
    return _render(request, "channel.html", organization, member, "channel", {
        "shared_with": member.parents.filter(revoked_at__isnull=True) if not member.is_staff else [],
        "next_class": services.next_class(organization, member), "now": timezone.now(), "form": form, "scheduled": scheduled, "pinned": pinned, "days": days, "page": page, "kind": kind, "seen": seen, "watched": watched,
        "member_count": Membership.objects.filter(organization=organization, status="active").count(),
    })
@login_required(login_url="landing:home")
@require_POST
def channel_delete_view(request, slug, post_id):
    organization, member = _organization(request, slug, staff=True)
    post = get_object_or_404(ChannelPost, pk=post_id, organization=organization)
    if post.file:
        post.file.delete(save=False)
    post.delete()
    messages.success(request, "Removed from the channel.")
    return redirect("organizations:channel", slug=slug)

def _send_file(field):
    if not field:
        raise Http404
    try:
        return FileResponse(field.open("rb"), as_attachment=True, filename=field.name.rsplit("/", 1)[-1])
    except FileNotFoundError:
        raise Http404
@login_required(login_url="landing:home")
def channel_file_view(request, slug, post_id):
    organization, member = _organization(request, slug)
    post = get_object_or_404(services.channel_posts_for(organization, member), pk=post_id)
    return _send_file(post.file)
@login_required(login_url="landing:home")
def task_file_view(request, slug, task_id):
    organization, member = _organization(request, slug)
    task = get_object_or_404(services.tasks_for(organization, member), pk=task_id)
    return _send_file(task.attachment)
@login_required(login_url="landing:home")
def submission_file_view(request, slug, submission_id):
    organization, member = _organization(request, slug)
    submission = get_object_or_404(Submission, pk=submission_id, task__organization=organization)
    if not member.is_staff and submission.student != request.user:
        raise Http404
    return _send_file(submission.file)

@login_required(login_url="landing:home")
def tasks_view(request, slug):
    organization, member = _organization(request, slug)
    form = TaskForm(request.POST or None, request.FILES or None) if member.is_staff else None
    if request.method == "POST":
        if not member.is_staff:
            raise Http404
        if form.is_valid():
            task = form.save(commit=False)
            task.organization, task.created_by = organization, request.user
            task.save()
            if task.publish_at:
                when = timezone.localtime(task.publish_at)
                messages.success(request, f"Task scheduled. Students see it, and are told, on {when:%a} {when:%b} {when.day} at {when.strftime('%I:%M %p').lstrip('0')}.")
            else:
                services.announce_task(task, request.user)
                messages.success(request, "Task created. Students have been told.")
            return redirect("organizations:task", slug=slug, task_id=task.pk)
    tasks = list(services.tasks_for(organization, member).annotate(submitted=Count("submissions"), approved=Count("submissions", filter=Q(submissions__status="approved")), waiting=Count("submissions", filter=Q(submissions__status="submitted"))))
    now = timezone.now()
    if member.is_staff:
        students = list(services.students_of(organization))
        for task in tasks:
            task.assigned = len([student for student in students if not task.group or student.group.lower() == task.group.lower()])
            task.percent = round(task.submitted * 100 / task.assigned) if task.assigned else 0
    else:
        mine = {submission.task_id: submission for submission in Submission.objects.filter(task__organization=organization, student=request.user)}
        for task in tasks:
            task.mine = mine.get(task.pk)
            task.state = task.mine.status if task.mine else "overdue" if task.due_at and task.due_at < now else "todo"
    return _render(request, "tasks.html", organization, member, "tasks", {"tasks": tasks, "form": form, "now": now})
@login_required(login_url="landing:home")
def task_detail_view(request, slug, task_id):
    organization, member = _organization(request, slug)
    task = get_object_or_404(services.tasks_for(organization, member), pk=task_id)
    context = {"task": task, "instructions": render_article(task.instructions), "now": timezone.now()}
    if member.is_staff:
        students = [student for student in services.students_of(organization) if not task.group or student.group.lower() == task.group.lower()]
        submissions = {submission.student_id: submission for submission in task.submissions.select_related("student__profile", "repository__project", "reviewed_by")}
        status = request.GET.get("status", "")
        rows = [{"student": student, "submission": submissions.get(student.user_id)} for student in students]
        context.update({"rows": [row for row in rows if not status or (row["submission"].status if row["submission"] else "missing") == status], "status": status,
                        "counts": {"missing": len([row for row in rows if not row["submission"]]), **{key: len([row for row in rows if row["submission"] and row["submission"].status == key]) for key in ["submitted", "changes", "approved"]}}})
    else:
        submission = Submission.objects.filter(task=task, student=request.user).first()
        form = SubmissionForm(request.POST or None, request.FILES or None, instance=submission, student=request.user)
        if request.method == "POST" and form.is_valid():
            if submission and submission.status == "approved":
                messages.error(request, "This task is already approved.")
                return redirect("organizations:task", slug=slug, task_id=task.pk)
            saved = form.save(commit=False)
            saved.task, saved.student, saved.status = task, request.user, "submitted"
            saved.save()
            for teacher in services.staff_of(organization):
                notify(teacher, request.user, "organization", f"{services.display_name(request.user)} submitted {task.title}", reverse("organizations:task", args=[slug, task.pk]))
            messages.success(request, "Submitted. Your teacher will review it.")
            return redirect("organizations:task", slug=slug, task_id=task.pk)
        context.update({"submission": submission, "form": form})
    return _render(request, "task_detail.html", organization, member, "tasks", context)
@login_required(login_url="landing:home")
@require_POST
def review_view(request, slug, submission_id):
    organization, member = _organization(request, slug, staff=True)
    submission = get_object_or_404(Submission.objects.select_related("task", "student"), pk=submission_id, task__organization=organization)
    form = ReviewForm(request.POST, points=submission.task.points)
    if form.is_valid():
        submission.status, submission.score, submission.feedback = form.cleaned_data["status"], form.cleaned_data["score"], form.cleaned_data["feedback"].strip()
        submission.reviewed_by, submission.reviewed_at = request.user, timezone.now()
        submission.save(update_fields=["status", "score", "feedback", "reviewed_by", "reviewed_at", "updated_at"])
        result = "approved" if submission.status == "approved" else "needs changes"
        score = f" ({submission.score}/{submission.task.points})" if submission.score is not None else ""
        notify(submission.student, request.user, "organization", f"Your work on {submission.task.title} was {result}{score}", reverse("organizations:task", args=[slug, submission.task_id]))
        messages.success(request, f"Review saved for {services.display_name(submission.student)}.")
    else:
        messages.error(request, " ".join(error for errors in form.errors.values() for error in errors))
    return _back(request, reverse("organizations:task", args=[slug, submission.task_id]))
@login_required(login_url="landing:home")
@require_POST
def task_delete_view(request, slug, task_id):
    organization, member = _organization(request, slug, staff=True)
    task = get_object_or_404(Task, pk=task_id, organization=organization)
    task.delete()
    messages.success(request, "Task deleted.")
    return redirect("organizations:tasks", slug=slug)

@login_required(login_url="landing:home")
def settings_view(request, slug):
    organization, member = _organization(request, slug, staff=True)
    if member.role != "owner":
        raise Http404
    form = OrganizationForm(request.POST or None, instance=organization)
    if request.method == "POST":
        if request.POST.get("action") == "new_code":
            organization.invite_code = Organization._meta.get_field("invite_code").default()
            organization.save(update_fields=["invite_code"])
            messages.success(request, "New invite link created. The old one no longer works.")
            return redirect("organizations:invite", slug=slug)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("organizations:settings", slug=slug)
    return _render(request, "settings.html", organization, member, "settings", {"form": form})

@login_required(login_url="landing:home")
def classes_view(request, slug):
    organization, member = _organization(request, slug)
    form = LiveClassForm(request.POST or None) if member.is_staff else None
    if request.method == "POST":
        if not member.is_staff:
            raise Http404
        if form.is_valid():
            created = services.schedule_classes(organization, request.user, form.cleaned_data)
            messages.success(request, (f"{len(created)} classes scheduled." if len(created) > 1 else "Class scheduled.") + " Members have been told, and they'll get a reminder 15 minutes before each one.")
            return redirect("organizations:live_class", slug=slug, class_id=created[0].pk)
    now = timezone.now()
    classes = list(services.classes_for(organization, member).select_related("recording"))
    for live in classes:
        live.current = live.state(now)
    totals = dict(LiveClass.objects.filter(organization=organization).exclude(series="").values("series").annotate(total=Count("id")).values_list("series", "total"))
    seen = {}
    for live in sorted(classes, key=lambda live: live.starts_at):
        if live.series:
            seen[live.series] = seen.get(live.series, 0) + 1
            live.position = (seen[live.series], totals.get(live.series, 1))
    upcoming = [live for live in classes if live.current != "over"]
    past = sorted([live for live in classes if live.current == "over"], key=lambda live: live.starts_at, reverse=True)[:30]
    if member.is_staff:
        counts = dict(Attendance.objects.filter(live_class__in=past, status__in=["present", "late"]).values("live_class_id").annotate(total=Count("id")).values_list("live_class_id", "total"))
        students = list(services.students_of(organization))
        for live in past:
            live.came = counts.get(live.pk, 0)
            live.expected = len([student for student in students if not live.group or student.group.lower() == live.group.lower()])
    else:
        mine = dict(Attendance.objects.filter(live_class__in=past, student=request.user).values_list("live_class_id", "status"))
        for live in past:
            live.mine = mine.get(live.pk, "absent")
    return _render(request, "classes.html", organization, member, "classes", {"form": form, "upcoming": upcoming, "past": past, "in_app_video": bool(settings.JITSI_DOMAIN)})
@login_required(login_url="landing:home")
def class_detail_view(request, slug, class_id):
    organization, member = _organization(request, slug)
    live = get_object_or_404(services.classes_for(organization, member).select_related("recording"), pk=class_id)
    now = timezone.now()
    if request.method == "POST":
        if not member.is_staff:
            raise Http404
        action = request.POST.get("action")
        if action == "attendance":
            for row in services.class_roster(live):
                status = request.POST.get(f"status-{row['member'].user_id}", "")
                if status in {"present", "late", "absent"} and (not row["attendance"] or row["attendance"].status != status):
                    Attendance.objects.update_or_create(live_class=live, student=row["member"].user, defaults={"status": status, "marked_by": request.user})
            messages.success(request, "Attendance saved.")
        elif action == "absent_rest":
            roster = services.class_roster(live)
            Attendance.objects.bulk_create([Attendance(live_class=live, student=row["member"].user, status="absent", marked_by=request.user) for row in roster if not row["attendance"]], ignore_conflicts=True)
            messages.success(request, "Everyone who didn't join is marked absent.")
        elif action == "recording":
            recording = LearningPost.objects.filter(organization=organization, pk=request.POST.get("recording") or 0).first()
            live.recording = recording
            live.save(update_fields=["recording"])
            if recording:
                services.notify_members(organization, request.user, f"Recording of {live.title} is ready", reverse("learning:detail", args=[recording.pk]), live.group)
            messages.success(request, "Recording attached." if recording else "Recording removed.")
        return redirect("organizations:live_class", slug=slug, class_id=live.pk)
    context = {"live": live, "state": live.state(now), "now": now, "position": services.series_position(live), "in_app": services.video_room(live) is not None, "jitsi_domain": settings.JITSI_DOMAIN}
    if member.is_staff:
        roster = services.class_roster(live)
        context.update({"statuses": Attendance.STATUSES, "roster": roster, "came": len([row for row in roster if row["attendance"] and row["attendance"].status in {"present", "late"}]), "recordings": LearningPost.objects.filter(organization=organization, kind="video").order_by("-published_at")[:30], "class_recordings": _finished_recordings(live)})
    else:
        context["mine"] = Attendance.objects.filter(live_class=live, student=request.user).first()
    return _render(request, "class_detail.html", organization, member, "classes", context)
@login_required(login_url="landing:home")
def class_join_view(request, slug, class_id):
    """Students join through here so attendance is recorded, then go on to the meeting."""
    organization, member = _organization(request, slug)
    live = get_object_or_404(services.classes_for(organization, member), pk=class_id)
    state = live.state(timezone.now())
    if state == "upcoming":
        messages.info(request, f"The class opens {LiveClass.JOIN_OPENS_MINUTES} minutes before it starts.")
        return redirect("organizations:live_class", slug=slug, class_id=live.pk)
    if state == "over":
        messages.info(request, "This class has ended." + (" The recording is below." if live.recording_id else ""))
        return redirect("organizations:live_class", slug=slug, class_id=live.pk)
    if live.in_myprogress:
        if not member.is_staff:
            services.join_class(live, request.user)
        return redirect("organizations:teaching_board" if member.is_staff else "organizations:watch", slug=slug, class_id=live.pk)
    if services.video_room(live):
        return redirect("organizations:class_room", slug=slug, class_id=live.pk)
    if not member.is_staff:
        services.join_class(live, request.user)
    return redirect(live.meeting_link)
@login_required(login_url="landing:home")
def class_room_view(request, slug, class_id):
    """The class held inside MyProgress: the Jitsi room embedded in the page. Coming in marks a student present, or late."""
    organization, member = _organization(request, slug)
    live = get_object_or_404(services.classes_for(organization, member), pk=class_id)
    room = services.video_room(live)
    if room is None or live.state(timezone.now()) not in {"open", "live"}:
        return redirect("organizations:join_class", slug=slug, class_id=live.pk)
    mine = None if member.is_staff else services.join_class(live, request.user)
    response = _render(request, "class_room.html", organization, member, "classes", {"live": live, "room": room, "domain": settings.JITSI_DOMAIN, "token": services.video_token(live, request.user, member.is_staff, room), "display_name": services.display_name(request.user), "mine": mine})
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
@login_required(login_url="landing:home")
def class_calendar_view(request, slug, class_id):
    """The class, or every class still to come in its series, as a calendar file with a reminder 15 minutes before."""
    organization, member = _organization(request, slug)
    visible = services.classes_for(organization, member).select_related("organization")
    live = get_object_or_404(visible, pk=class_id)
    classes = [live]
    if request.GET.get("series") and live.series:
        classes = list(visible.filter(series=live.series, starts_at__gte=timezone.now() - timedelta(hours=12)).order_by("starts_at")) or [live]
    body = services.class_calendar(classes, lambda item: request.build_absolute_uri(reverse("organizations:live_class", args=[slug, item.pk])))
    name = f"{slug}-series" if len(classes) > 1 else f"{slug}-class-{live.pk}"
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}.ics"'
    return response
def _finished_recordings(live):
    """A class's recordings from the teaching board, newest first, each with its length to show."""
    finished = list(live.recordings.filter(finished_at__isnull=False).select_related("post"))
    for item in finished:
        item.length = format_stamp(item.duration_ms / 1000) if item.duration_ms else ""
    return finished
def _teaching_class(request, slug, class_id):
    """A class its teachers run: only staff of the class's organization get here."""
    organization, member = _organization(request, slug, staff=True)
    return organization, member, get_object_or_404(LiveClass, pk=class_id, organization=organization)
@login_required(login_url="landing:home")
def teaching_board_view(request, slug, class_id):
    """The video studio for a live class: whiteboard, pen, notes, zoom and screen + camera, shown to students by
    sharing the board's window in the call, and recorded straight into the class's recording."""
    organization, member, live = _teaching_class(request, slug, class_id)
    upload = {name: reverse(f"organizations:recording_{name}", args=[slug, live.pk]) for name in ["start", "piece", "finish"]}
    upload.update(chunk=upload.pop("piece"), title=live.title, max_minutes=min(240, live.duration_minutes + 60))
    if live.in_myprogress:  # broadcast to the class's watch page, with its chat
        upload.update(broadcast=True, chat=reverse("organizations:class_chat", args=[slug, live.pk]))
    response = render(request, "organizations/teaching_board.html", {
        **studio_options(), "organization": organization, "member": member, "live": live, "section": "organization",
        "studio_host": "live", "studio_upload": upload, "join_url": reverse("organizations:join_class", args=[slug, live.pk]),
        "past_recordings": _finished_recordings(live)[:5],
    })
    response["Cache-Control"] = "private, no-store"
    return response
@login_required(login_url="landing:home")
@require_POST
@rate_limit("class-recording", 20, 3600)
def recording_start_view(request, slug, class_id):
    organization, member, live = _teaching_class(request, slug, class_id)
    kind = request.POST.get("type", "")[:80]
    broadcast = request.POST.get("live") == "1" and live.in_myprogress and not kind.startswith("video/mp4")
    if broadcast:  # one broadcast at a time per class: going live again replaces the previous one
        ClassRecording.objects.filter(live_class=live, is_live=True).update(is_live=False)
    recording = ClassRecording.objects.create(live_class=live, created_by=request.user, extension="mp4" if kind.startswith("video/mp4") else "webm", mime=kind, is_live=broadcast)
    recordings.start_file(recording)
    return JsonResponse({"recording": recording.token})
@login_required(login_url="landing:home")
@require_POST
def recording_piece_view(request, slug, class_id):
    """One piece of a recording in progress, appended in order. A piece sent twice (a retry) is acknowledged, not added again."""
    organization, member, live = _teaching_class(request, slug, class_id)
    piece, seq = request.FILES.get("piece"), request.POST.get("seq", "")
    if piece is None or not seq.isdigit():
        return JsonResponse({"error": "Send a piece and its number."}, status=400)
    with transaction.atomic():
        recording = get_object_or_404(ClassRecording.objects.select_for_update(), token=request.POST.get("recording", ""), live_class=live, created_by=request.user, finished_at__isnull=True)
        if int(seq) < recording.pieces:
            return JsonResponse({"received": recording.pieces})
        if int(seq) > recording.pieces:
            return JsonResponse({"error": "A piece is missing.", "expected": recording.pieces}, status=409)
        if recording.size + piece.size > settings.CLASS_RECORDING_MAX_BYTES:
            return JsonResponse({"error": "This recording reached the size limit, so it stopped here."}, status=413)
        recordings.append_piece(recording, piece)
        recording.pieces += 1
        recording.size += piece.size
        recording.last_piece_at = timezone.now()
        if recording.extension == "webm":
            recording.stream_state = recordings.index_stream(recording)
        recording.save(update_fields=["pieces", "size", "last_piece_at", "stream_state"])
    return JsonResponse({"received": recording.pieces})
@login_required(login_url="landing:home")
@require_POST
def recording_finish_view(request, slug, class_id):
    """End a recording: write the seekable copy the teacher trims and cuts, and keep what the board sent with it
    (chapters, captions, a thumbnail). Nothing is shared until the teacher publishes it from the editor."""
    organization, member, live = _teaching_class(request, slug, class_id)
    with transaction.atomic():
        recording = get_object_or_404(ClassRecording.objects.select_for_update(), token=request.POST.get("recording", ""), live_class=live, created_by=request.user, finished_at__isnull=True)
        if not recording.pieces or not recordings.starts_like_video(recording):
            return JsonResponse({"error": "Nothing playable was uploaded for this recording."}, status=400)
        broadcast = recording.is_live
        recording.finished_at = timezone.now()
        recording.is_live = False
        recording.save(update_fields=["finished_at", "is_live"])
    milliseconds = request.POST.get("duration_ms", "")
    recording.duration_ms = min(int(milliseconds), 24 * 3600 * 1000) if milliseconds.isdigit() else 0

    def cleaned(clean, value):
        try:
            return clean(value)
        except ValueError:
            return ""
    when = timezone.localtime(live.starts_at)
    recording.title = f"{live.title} (class recording)"[:180]
    recording.summary = f"Recorded live in class on {when:%a} {when:%b} {when.day}." + (f" For {live.group}." if live.group else "")
    recording.chapters = cleaned(clean_chapters, request.POST.get("chapters", "")[:3000])
    recording.captions = cleaned(clean_captions, request.POST.get("captions", ""))
    if recordings.prepare_source(recording, recording.duration_ms):
        # Students watching the broadcast may still be a few seconds behind; the upload goes once they can't be.
        recording.upload_kept_until = timezone.now() + (UPLOAD_KEPT_FOR if broadcast else timedelta(0))
    elif recording.extension == "webm" and recording.duration_ms:
        recordings.add_duration(recordings.file_path(recording), recording.duration_ms)  # at least show its length
    thumbnail = request.FILES.get("thumbnail")
    if thumbnail and thumbnail.size <= MAX_THUMBNAIL_BYTES and thumbnail.content_type in {"image/jpeg", "image/png", "image/webp"}:
        recording.thumbnail.save(f"{recording.token}.jpg", thumbnail, save=False)
    recording.save()
    return JsonResponse({"edit_url": reverse("organizations:recording_edit", args=[slug, live.pk, recording.pk]), "size": recording.size})
UPLOAD_KEPT_FOR = timedelta(minutes=10)
def _class_recording(request, slug, class_id, recording_id):
    """A finished recording of a class, for that class's teachers."""
    organization, member, live = _teaching_class(request, slug, class_id)
    recording = get_object_or_404(ClassRecording.objects.select_related("post"), pk=recording_id, live_class=live, finished_at__isnull=False)
    return organization, member, live, recording
@login_required(login_url="landing:home")
def recording_file_view(request, slug, class_id, recording_id, which):
    """The whole recording, or its thumbnail, for the teachers editing it. Students only ever get the published lecture."""
    organization, member, live, recording = _class_recording(request, slug, class_id, recording_id)
    if which == "video":
        path = recordings.source_path(recording)
        if not os.path.isfile(path):
            raise Http404
        response = ranged_file_response(request, path)
        response["Cache-Control"] = "private, no-store"
        return response
    field = recording.thumbnail or (recording.post.thumbnail if recording.post_id else None)
    if which != "thumbnail" or not field:
        raise Http404
    return stored_file_response(request, field)
def _kept_parts(recording, parts):
    """The parts to keep, moved to where the recording can be cut; [] keeps all of it, and None (the timeline sent
    nothing) keeps the last edit. ValueError when nothing would be left."""
    if parts is None:
        return recording.parts
    if not recording.can_cut or not parts:
        return []
    marks = [*recording.keyframes, recording.duration_ms]
    snapped = recordings.snap_parts(parts, marks)
    if not snapped:
        raise ValueError("Keep at least part of the recording.")
    return [] if snapped == [[min(marks), max(marks)]] else snapped
def _publish_recording(request, organization, live, recording, published_parts, new_thumbnail):
    """Make or update the lecture students (or everyone) watch: the kept parts in a file of their own, with the
    chapters and captions moved to match. `published_parts` are the parts its file has now. True if it's new."""
    post = recording.post
    public = recording.audience == "public"
    previous = post.video_file.name if post else ""
    if post is None or recording.parts != published_parts or public != post.is_public:
        extension = "webm" if recording.source_name else recording.extension
        name = f"{'' if public else 'private/'}learning/videos/class-{recording.token[:16]}-{secrets.token_hex(4)}.{extension}"
        if recording.parts:
            recordings.write_copy(recordings.source_path(recording), recordings.media_path(name), recording.parts, recording.duration_ms)
        else:
            recordings.place_whole(recordings.source_path(recording), recordings.media_path(name))
    else:
        name = previous
    seconds = [[start / 1000, end / 1000] for start, end in recording.parts]
    created = post is None
    if created:
        post = LearningPost(author=recording.created_by or request.user, kind="video")
    post.title, post.summary = recording.title, recording.summary
    post.chapters = remap_chapters(recording.chapters, seconds) if seconds else recording.chapters
    post.captions = remap_captions(recording.captions, seconds) if seconds else recording.captions
    post.organization, post.is_public = (None, True) if public else (organization, False)  # organization lectures are never public
    post.video_file.name = name
    post.save()
    if recording.thumbnail and (created or new_thumbnail):
        old = post.thumbnail.name
        with recording.thumbnail.open("rb") as handle:
            post.thumbnail.save(f"class-{recording.token[:16]}.jpg", File(handle), save=True)
        if old:
            post.thumbnail.storage.delete(old)
    place_post_files(post)  # the thumbnail goes into, or out of, the private folder with the video
    if previous and previous != name and previous not in {recording.file_name, recording.source_name}:
        post.video_file.storage.delete(previous)
    recording.post = post
    if live.recording_id is None:
        live.recording = post
        live.save(update_fields=["recording"])
    if created:
        services.notify_members(organization, request.user, f"Recording of {live.title} is ready", reverse("learning:detail", args=[post.pk]), live.group)
        LearningPost.objects.filter(pk=post.pk).update(announced_at=timezone.now())
    sync_post_coins(post)
    return created
@login_required(login_url="landing:home")
@rate_limit("recording-edit", 60, 3600)
def recording_edit_view(request, slug, class_id, recording_id):
    """The class recording in the studio editor: trim the start and end, cut out parts, set its details, and
    publish it to the class's students or to everyone on the teacher's channel."""
    organization, member, live, recording = _class_recording(request, slug, class_id, recording_id)
    if not recording.source_name and recording.extension == "webm" and os.path.isfile(recordings.file_path(recording)):
        if recordings.prepare_source(recording, recording.duration_ms):  # recorded before the editor: make its copy now
            recording.save(update_fields=["source_name", "duration_ms", "keyframes"])
    if not recording.title:  # recorded before the editor: start from its lecture
        post = recording.post
        recording.title = (post.title if post else f"{live.title} (class recording)")[:180]
        if post:
            recording.summary, recording.chapters, recording.captions, recording.audience = post.summary, post.chapters, post.captions, "public" if post.is_public else "members"
        recording.save(update_fields=["title", "summary", "chapters", "captions", "audience"])
    missing = not os.path.isfile(recordings.source_path(recording))
    form = RecordingForm(request.POST or None, request.FILES or None, initial={"title": recording.title, "summary": recording.summary, "chapters": recording.chapters, "audience": recording.audience})
    if request.method == "POST" and missing:
        form.add_error(None, "The recording's video file is gone, so it can't be published.")
    elif request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            parts = _kept_parts(recording, data["parts"])
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            with transaction.atomic():
                recording = ClassRecording.objects.select_for_update().select_related("post").get(pk=recording.pk)
                published_parts = recording.parts
                recording.title, recording.summary, recording.chapters, recording.audience, recording.parts = data["title"], data["summary"], data["chapters"], data["audience"], parts
                if data["thumbnail"]:
                    if recording.thumbnail:
                        recording.thumbnail.storage.delete(recording.thumbnail.name)
                    recording.thumbnail.save(f"{recording.token}.jpg", data["thumbnail"], save=False)
                publish = request.POST.get("action") == "publish" or recording.post_id
                created = publish and _publish_recording(request, organization, live, recording, published_parts, bool(data["thumbnail"]))
                recording.save()
            if not publish:
                messages.success(request, "Draft saved. Students can't see it until you publish it.")
            elif recording.audience == "public":
                messages.success(request, f"{'Published' if created else 'Saved'}: everyone can watch it on your channel{', and your students were told' if created else ''}.")
            else:
                messages.success(request, f"{'Published' if created else 'Saved'}: your students can watch it{' and were told' if created else ''}.")
            return redirect("organizations:recording_edit", slug=slug, class_id=live.pk, recording_id=recording.pk)
    seconds = lambda ms: round(ms / 1000, 3)  # noqa: E731
    context = {
        "live": live, "recording": recording, "form": form,
        "video_url": reverse("organizations:recording_file", args=[slug, live.pk, recording.pk, "video"]),
        "thumbnail_url": reverse("organizations:recording_file", args=[slug, live.pk, recording.pk, "thumbnail"]) if recording.thumbnail or (recording.post_id and recording.post.thumbnail) else "",
        "editor": {"duration": seconds(recording.duration_ms), "marks": [seconds(ms) for ms in recording.keyframes] if recording.can_cut else [], "parts": [[seconds(a), seconds(b)] for a, b in recording.parts]},
        "channel_name": public_name(recording.post.author if recording.post_id else recording.created_by or request.user),
        "missing": missing,
    }
    response = _render(request, "recording_edit.html", organization, member, "classes", context)
    response["Cache-Control"] = "private, no-store"
    return response
def _watchable(request, slug, class_id):
    """A class this member may watch: their organization's, for their batch."""
    organization, member = _organization(request, slug)
    return organization, member, get_object_or_404(services.classes_for(organization, member), pk=class_id)
@login_required(login_url="landing:home")
def watch_view(request, slug, class_id):
    """A class held inside MyProgress, for students: the teacher's board live, a few seconds behind, and the class chat."""
    organization, member, live = _watchable(request, slug, class_id)
    if not live.in_myprogress:
        return redirect("organizations:live_class", slug=slug, class_id=live.pk)
    if member.is_staff:
        return redirect("organizations:teaching_board", slug=slug, class_id=live.pk)
    state = live.state(timezone.now())
    if state in {"open", "live"}:
        services.join_class(live, request.user)
    response = _render(request, "watch.html", organization, member, "classes", {
        "live": live, "state": state, "now": timezone.now(),
        "stream_url": reverse("organizations:class_stream", args=[slug, live.pk]), "bytes_url": reverse("organizations:class_stream_bytes", args=[slug, live.pk]),
        "chat_url": reverse("organizations:class_chat", args=[slug, live.pk]),
    })
    response["Cache-Control"] = "private, no-store"
    return response
def _stream_state(recording):
    if recording is None:
        return "waiting"
    if recording.finished_at or (not recording.is_live and recording.stream_state.get("init") is not None):
        return "ended"
    if recording.stream_state.get("init") is None:
        return "waiting"
    if recording.last_piece_at and timezone.now() - recording.last_piece_at > timedelta(seconds=12):
        return "paused"
    return "live" if recording.stream_state.get("recent") else "starting"
@login_required(login_url="landing:home")
def stream_view(request, slug, class_id):
    """Where a student's player starts: the stream's header, and a keyframe a few seconds behind the teacher."""
    organization, member, live = _watchable(request, slug, class_id)
    recording = live.recordings.order_by("-started_at").first()
    state = _stream_state(recording)
    data = {"state": state, "recording_url": reverse("learning:detail", args=[live.recording_id]) if live.recording_id else ""}
    if recording and state in {"live", "paused", "starting"}:
        codecs = recording.mime.partition("codecs=")[2]
        data.update(recording=recording.token, mime=f'video/webm; codecs="{codecs}"' if codecs else "video/webm", init=recording.stream_state["init"], start=recordings.join_point(recording.stream_state), size=recording.size)
    response = JsonResponse(data)
    response["Cache-Control"] = "private, no-store"
    return response
STREAM_READ_LIMIT = 4 * 1024 * 1024
@login_required(login_url="landing:home")
def stream_bytes_view(request, slug, class_id):
    """A slice of the broadcast as uploaded so far, for the student's player to append."""
    organization, member, live = _watchable(request, slug, class_id)
    recording = get_object_or_404(ClassRecording, live_class=live, token=request.GET.get("recording", ""))
    start, end = request.GET.get("from", ""), request.GET.get("to", "")
    if not start.isdigit() or (end and not end.isdigit()):
        return HttpResponse(status=400)
    start = int(start)
    stop = min(int(end) if end else recording.size, start + STREAM_READ_LIMIT, recording.size)
    if start >= stop:
        response = HttpResponse(status=204)
    else:
        try:
            with open(recordings.file_path(recording), "rb") as handle:
                handle.seek(start)
                response = HttpResponse(handle.read(stop - start), content_type="application/octet-stream")
        except FileNotFoundError:
            raise Http404  # the class ended a while ago and only its seekable copy is kept
    response["X-Stream-Size"] = str(recording.size)
    response["X-Stream-State"] = _stream_state(recording)
    response["Cache-Control"] = "private, no-store"
    return response
CHAT_BATCH = 100
@login_required(login_url="landing:home")
@rate_limit("class-chat", 30, 60)
def class_chat_view(request, slug, class_id):
    """The class chat: messages, raised hands, and, for teachers, how many students are watching."""
    organization, member, live = _watchable(request, slug, class_id)
    now = timezone.now()
    if request.method == "POST":
        action = request.POST.get("action", "say")
        if action == "say":
            text = " ".join(request.POST.get("text", "").split())[:500]
            if text:
                ClassMessage.objects.create(live_class=live, author=request.user, text=text)
        elif action in {"raise", "lower"} and not member.is_staff:
            Attendance.objects.filter(live_class=live, student=request.user).update(hand_raised_at=now if action == "raise" else None)
        elif action == "lower" and member.is_staff:
            Attendance.objects.filter(live_class=live, student_id=request.POST.get("student") or 0).update(hand_raised_at=None)
        elif action == "delete" and member.is_staff:
            ClassMessage.objects.filter(live_class=live, pk=request.POST.get("message") or 0).delete()
        else:
            return JsonResponse({"error": "That isn't something you can do here."}, status=400)
        return JsonResponse({"ok": True})
    after = request.GET.get("after", "0")
    teachers = set(services.staff_of(organization).values_list("pk", flat=True))
    rows = live.messages.filter(pk__gt=int(after) if after.isdigit() else 0).select_related("author__profile")[:CHAT_BATCH]
    data = {"messages": [{"id": message.pk, "name": public_name(message.author), "text": message.text, "mine": message.author_id == request.user.pk, "teacher": message.author_id in teachers, "time": timezone.localtime(message.created_at).strftime("%I:%M %p").lstrip("0")} for message in rows]}
    if member.is_staff:
        seen = Attendance.objects.filter(live_class=live).select_related("student__profile")
        data["watching"] = seen.filter(last_seen_at__gte=now - timedelta(seconds=30)).count()
        data["hands"] = [{"student": mark.student_id, "name": public_name(mark.student)} for mark in seen.filter(hand_raised_at__isnull=False).order_by("hand_raised_at")]
    else:
        if live.state(now) in {"open", "live"}:
            services.join_class(live, request.user)  # opened the page early: present once the class opens
        mine = Attendance.objects.filter(live_class=live, student=request.user)
        mine.update(last_seen_at=now)
        data["hand"] = mine.filter(hand_raised_at__isnull=False).exists()
    response = JsonResponse(data)
    response["Cache-Control"] = "private, no-store"
    return response
@login_required(login_url="landing:home")
def live_now_view(request):
    """Classes to alert this person about right now (open to join or live, not joined yet), for the alert on every page."""
    alerts = [{
        "id": live.pk, "title": live.title, "organization": live.organization.name, "state": live.current, "teacher": live.member.is_staff,
        "starts_at": live.starts_at.isoformat(), "join_url": reverse("organizations:join_class", args=[live.organization.slug, live.pk]),
        "page_url": reverse("organizations:live_class", args=[live.organization.slug, live.pk]),
    } for live in services.class_alerts(request.user)]
    response = JsonResponse({"classes": alerts})
    response["Cache-Control"] = "private, no-store"
    return response
@login_required(login_url="landing:home")
@require_POST
def class_delete_view(request, slug, class_id):
    organization, member = _organization(request, slug, staff=True)
    live = get_object_or_404(LiveClass, pk=class_id, organization=organization)
    if request.POST.get("scope") == "following" and live.series:
        later = LiveClass.objects.filter(organization=organization, series=live.series, starts_at__gte=live.starts_at)
        count = later.count()
        later.delete()
        messages.success(request, f"Cancelled {count} class{'es' if count != 1 else ''} in the series.")
    else:
        live.delete()
        messages.success(request, "Class cancelled.")
    return redirect("organizations:classes", slug=slug)

@login_required(login_url="landing:home")
def leaderboard_view(request, slug):
    organization, member = _organization(request, slug)
    if not member.is_staff and not organization.show_leaderboard:
        raise Http404
    metric = request.GET.get("by") if request.GET.get("by") in dict(services.LEADERBOARD_METRICS) else "class_points"
    group = request.GET.get("group", "").strip()[:60]
    if not member.is_staff and request.GET.get("group") is None:
        group = member.group  # students start on their own batch
    rows = services.leaderboard(organization, metric, group)
    mine = next((row for row in rows if row["user"].pk == request.user.pk), None)
    return _render(request, "leaderboard.html", organization, member, "leaderboard", {
        "rows": rows, "podium": rows[:3] if len(rows) >= 3 else [], "metric": metric, "metric_label": dict(services.LEADERBOARD_METRICS)[metric], "metrics": services.LEADERBOARD_METRICS,
        "group": group, "mine": mine, "per_class": services.POINTS_PER_CLASS, "per_day": services.POINTS_PER_CODING_DAY,
    })
@login_required(login_url="landing:home")
def certificates_view(request, slug):
    organization, member = _organization(request, slug)
    if not member.is_staff:
        certificates = Certificate.objects.filter(organization=organization, student=request.user)
        if request.method == "POST":
            certificate = get_object_or_404(certificates, pk=request.POST.get("certificate") or 0)
            certificate.show_on_profile = request.POST.get("show") == "1"
            certificate.save(update_fields=["show_on_profile"])
            messages.success(request, "Shown on your profile." if certificate.show_on_profile else "Hidden from your profile.")
            return redirect("organizations:certificates", slug=slug)
        return _render(request, "certificates.html", organization, member, "certificates", {"certificates": certificates})
    group = request.GET.get("group", "").strip()[:60]
    rows = services.student_growth(organization, group=group, sort="name")
    by_id = {str(row["user"].pk): row for row in rows}
    form = CertificateForm(request.POST or None, choices=[(key, services.display_name(row["user"])) for key, row in by_id.items()] if request.method == "POST" else [])
    if request.method == "POST" and request.POST.get("action") == "revoke":
        certificate = get_object_or_404(Certificate, pk=request.POST.get("certificate") or 0, organization=organization)
        certificate.revoked_at, certificate.revoked_reason = timezone.now(), request.POST.get("reason", "").strip()[:200]
        certificate.save(update_fields=["revoked_at", "revoked_reason"])
        messages.success(request, f"Certificate {certificate.code} revoked. Its public page now says so.")
        return redirect("organizations:certificates", slug=slug)
    if request.method == "POST":
        all_rows = {str(row["user"].pk): row for row in services.student_growth(organization)}
        form.fields["students"].choices = [(key, services.display_name(row["user"])) for key, row in all_rows.items()]
        if form.is_valid():
            created = services.issue_certificates(organization, request.user, [all_rows[key]["user"] for key in form.cleaned_data["students"]], form.cleaned_data["title"].strip(), form.cleaned_data["description"].strip())
            skipped = len(form.cleaned_data["students"]) - len(created)
            messages.success(request, f"Issued {len(created)} certificate{'' if len(created) == 1 else 's'}." + (f" {skipped} already had this one." if skipped else ""))
            return redirect("organizations:certificates", slug=slug)
    issued = Certificate.objects.filter(organization=organization).select_related("student__profile", "issued_by")
    return _render(request, "certificates.html", organization, member, "certificates", {"form": form, "rows": rows, "group": group, "issued": Paginator(issued, 30).get_page(request.GET.get("page"))})
def certificate_view(request, code):
    """The public page that proves a certificate is real. No sign-in needed."""
    certificate = get_object_or_404(Certificate.objects.select_related("organization", "student__profile", "issued_by"), code=code.upper())
    return render(request, "organizations/certificate.html", {"certificate": certificate, "verify_url": request.build_absolute_uri(reverse("organizations:certificate", args=[certificate.code]))})
def _send_parent_link(request, access):
    link = request.build_absolute_uri(reverse("organizations:parent_report", args=[access.token]))
    student = services.display_name(access.member.user)
    organization = access.member.organization
    body = f"Hello {access.name},\n\n{organization.name} has shared {student}'s progress report with you on MyProgress.\n\nOpen it any time:\n{link}\n\nIt shows attendance at live classes, task results, upcoming deadlines and certificates. You don't need an account. Please keep this link private; the institute can turn it off whenever you ask.\n"
    if organization.parent_digest:
        body += "\nOnce a week you'll also get a short summary by email, with a link in it to stop.\n"
    try:
        send_mail(f"{student}'s progress at {organization.name}", body, None, [access.email])
    except Exception:
        logger.exception("Could not send a parent report link to %s", access.email)
@login_required(login_url="landing:home")
@require_POST
def parent_access_view(request, slug, user_id):
    """Add, resend or turn off a parent's report link, from the student's page."""
    organization, member = _organization(request, slug, staff=True)
    student = get_object_or_404(Membership, organization=organization, user_id=user_id, status="active", role="student")
    action = request.POST.get("action", "add")
    if action == "add":
        form = ParentForm(request.POST)
        if form.is_valid():
            access = form.save(commit=False)
            access.member, access.created_by = student, request.user
            access.save()
            _send_parent_link(request, access)
            notify(student.user, request.user, "organization", f"{organization.name} shared your progress report with {access.name} ({access.get_relation_display().lower()})" + (", who also gets a weekly summary email" if organization.parent_digest else ""), services.channel_url(organization))
            messages.success(request, f"Sent the progress report link to {access.email}.")
        else:
            messages.error(request, " ".join(error for errors in form.errors.values() for error in errors))
    else:
        access = get_object_or_404(ParentAccess, pk=request.POST.get("access") or 0, member=student)
        if action == "resend" and not access.revoked_at:
            _send_parent_link(request, access)
            messages.success(request, f"Sent the link to {access.email} again.")
        elif action == "revoke":
            access.revoked_at = timezone.now()
            access.save(update_fields=["revoked_at"])
            messages.success(request, f"{access.name}'s link no longer works.")
    return redirect(f'{reverse("organizations:member", args=[slug, user_id])}#parents')
def parent_report_view(request, token):
    """The parent's read-only report. The link is the key, so it can be turned off at any time."""
    access = ParentAccess.objects.select_related("member__organization", "member__user__profile").filter(token=token).first()
    if access is None or access.revoked_at:
        return render(request, "organizations/parent_report.html", {"gone": True}, status=404)
    access.last_viewed_at = timezone.now()
    access.save(update_fields=["last_viewed_at"])
    response = render(request, "organizations/parent_report.html", {"access": access, "member": access.member, "organization": access.member.organization, "report": services.progress_report(access.member), "now": timezone.now()})
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
@csrf_exempt
def parent_emails_view(request, token):
    """Turn a parent's weekly email off or back on. The token in the link is the key; mail apps POST here for one-click unsubscribe."""
    access = ParentAccess.objects.select_related("member__organization", "member__user__profile").filter(token=token, revoked_at__isnull=True).first()
    if access is None:
        return render(request, "organizations/parent_report.html", {"gone": True}, status=404)
    if request.method == "POST":
        if request.POST.get("action") == "resume":
            access.digest_stopped_at = None
        elif not access.digest_stopped_at:
            access.digest_stopped_at = timezone.now()
        access.save(update_fields=["digest_stopped_at"])
        if request.POST.get("List-Unsubscribe") == "One-Click":
            return HttpResponse("You won't get the weekly email any more.", content_type="text/plain")
        return redirect("organizations:parent_emails", token=token)
    response = render(request, "organizations/parent_emails.html", {"access": access, "organization": access.member.organization, "student": services.display_name(access.member.user)})
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response

IMPORT_SESSION_KEY = "organization_import"
@login_required(login_url="landing:home")
def import_view(request, slug):
    """Upload a spreadsheet of students, check every row, then send the invites."""
    organization, member = _organization(request, slug, staff=True)
    action = request.POST.get("action") if request.method == "POST" else ""
    if action == "confirm":
        saved = request.session.pop(IMPORT_SESSION_KEY, None)
        if not saved or saved.get("organization") != organization.pk:
            messages.error(request, "That import expired. Upload the file again.")
            return redirect("organizations:import", slug=slug)
        created = services.invite_rows(organization, request.user, saved["rows"], _invite_sender(request, organization))
        messages.success(request, f"Sent {len(created)} invite{'' if len(created) == 1 else 's'}. They show below as they join.")
        return redirect("organizations:invite", slug=slug)
    rows, error = [], ""
    if action == "preview":
        upload = request.FILES.get("file")
        if not upload:
            error = "Choose a CSV file."
        elif upload.size > 1024 * 1024:
            error = "The file is too big; keep it under 1 MB."
        elif not upload.name.lower().endswith((".csv", ".txt")):
            error = "Upload a .csv file. In Excel or Google Sheets, use File, then Download or Save as, then CSV."
        else:
            rows, error = services.parse_member_csv(organization, upload.read())
            ready = [row for row in rows if row["status"] == "ok"]
            request.session[IMPORT_SESSION_KEY] = {"organization": organization.pk, "rows": ready}
    ready = [row for row in rows if row["status"] == "ok"]
    return _render(request, "import.html", organization, member, "invite", {"rows": rows, "ready": ready, "skipped": len(rows) - len(ready), "error": error, "limit": services.IMPORT_LIMIT})
@login_required(login_url="landing:home")
def import_template_view(request, slug):
    _organization(request, slug, staff=True)
    response = HttpResponse("email,name,batch,role\nasha@example.com,Asha Rao,Batch A 2026,student\nravi@example.com,Ravi Kumar,Batch A 2026,student\nteacher@example.com,Meera Joshi,,teacher\n", content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="students-template.csv"'
    return response
@login_required(login_url="landing:home")
@require_POST
def channel_publish_view(request, slug, post_id):
    """Publish a scheduled post straight away."""
    organization, member = _organization(request, slug, staff=True)
    post = get_object_or_404(ChannelPost, pk=post_id, organization=organization)
    if post.notified_at is None:
        post.publish_at = timezone.now()
        post.save(update_fields=["publish_at"])
        services.announce_post(post, request.user)
        messages.success(request, f"Published {post.title}.")
    return redirect("organizations:channel", slug=slug)
@login_required(login_url="landing:home")
@require_POST
def release_now_view(request, slug, kind, item_id):
    """Release a scheduled lecture or task straight away."""
    organization, member = _organization(request, slug, staff=True)
    now = timezone.now()
    if kind == "lesson":
        item = get_object_or_404(LearningPost, pk=item_id, organization=organization)
        if item.announced_at is None:
            LearningPost.objects.filter(pk=item.pk).update(publish_at=now)
            services.announce_lesson(item, request.user)
        target = reverse("organizations:channel", args=[slug])
    elif kind == "task":
        item = get_object_or_404(Task, pk=item_id, organization=organization)
        if item.announced_at is None:
            Task.objects.filter(pk=item.pk).update(publish_at=now)
            services.announce_task(item, request.user)
        target = reverse("organizations:task", args=[slug, item.pk])
    else:
        raise Http404
    messages.success(request, f"Released {item.title}. Members have been told.")
    return redirect(target)
