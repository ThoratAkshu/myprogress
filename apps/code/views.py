from apps.common.ratelimit import rate_limit
from functools import wraps
from pathlib import PurePosixPath
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.accounts.models import Profile
from apps.core.git_service import MAX_RAW_BYTES, MergeConflict, can_merge_cleanly, clean_repo_path, commit_detail, compare_branches, merge_branches, object_type, read_blob, refresh_repository_languages, resolve_ref, user_can_access, user_can_administer
from apps.core.models import Issue, IssueComment, Repository, RepositoryCollaborator, RepositoryInvitation, invitation_expiry, invitation_token
from apps.core.services import record_activity
from apps.notifications.services import notify
from . import invitations
from .access import RepositoryDenied, breadcrumbs, create_issue, load_repository, repository_context
MARKDOWN_SUFFIXES = {".md", ".markdown"}
def repository_page(write=False):
    def decorator(view):
        @wraps(view)
        def wrapped(request, repository_id, *args, **kwargs):
            try:
                repository = load_repository(request, repository_id, write=write)
            except RepositoryDenied as denied:
                return denied.response
            return view(request, repository, *args, **kwargs)
        return wrapped
    return decorator
def _name(user):
    if not user:
        return "Someone"
    return user.get_full_name() or Profile.objects.get_or_create(user=user)[0].handle
def _repo_label(repository):
    return repository.full_name
def _code_root(repository, ref=None):
    query = f"?ref={ref}" if ref and ref != repository.default_branch else ""
    return f'{reverse("landing:repository", args=[repository.pk])}{query}'
def _locate(request, repository):
    ref = resolve_ref(repository, request.GET.get("ref"))
    path = clean_repo_path(request.GET.get("path"))
    if not path or object_type(repository, ref, path) != "blob":
        raise ValueError("That file does not exist on this branch.")
    return ref, path
@repository_page()
def blob_view(request, repository):
    try:
        ref, path = _locate(request, repository)
    except ValueError as error:
        messages.error(request, str(error))
        return redirect(_code_root(repository))
    blob = read_blob(repository, ref, path)
    text = "" if blob["binary"] or blob["truncated"] else blob["data"].decode("utf-8", errors="replace")
    context = repository_context(request, repository, "code")
    context.update({"ref": ref, "path": path, "file_name": PurePosixPath(path).name, "crumbs": breadcrumbs(path)[:-1], "blob": blob, "lines": text.splitlines(), "is_markdown": PurePosixPath(path).suffix.lower() in MARKDOWN_SUFFIXES and bool(text), "text": text, "show_source": request.GET.get("source") == "1"})
    return render(request, "code/blob.html", context)
@repository_page()
def raw_view(request, repository):
    try:
        ref, path = _locate(request, repository)
    except ValueError:
        raise Http404
    blob = read_blob(repository, ref, path, limit=MAX_RAW_BYTES)
    if blob["truncated"]:
        return HttpResponse("File is too large to download from the web. Clone the repository instead.", status=413, content_type="text/plain")
    response = HttpResponse(blob["data"], content_type="application/octet-stream" if blob["binary"] else "text/plain; charset=utf-8")
    disposition = "attachment" if blob["binary"] else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{PurePosixPath(path).name.replace(chr(34), "")}"'
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response
@repository_page()
def commit_view(request, repository, sha):
    try:
        commit, files, truncated = commit_detail(repository, sha)
    except ValueError:
        raise Http404
    context = repository_context(request, repository, "commits")
    context.update({"commit": commit, "files": files, "truncated": truncated, "additions": sum(file["additions"] for file in files), "deletions": sum(file["deletions"] for file in files), "show_email": context["can_write"]})
    return render(request, "code/commit.html", context)
@repository_page()
def issue_list_view(request, repository, kind):
    state = "closed" if request.GET.get("state") == "closed" else "open"
    issues = repository.issues.filter(kind=kind).select_related("author__profile").prefetch_related("comments")
    issues = issues.filter(state="open") if state == "open" else issues.exclude(state="open")
    context = repository_context(request, repository, "pulls" if kind == "pull" else "issues")
    closed_count = repository.issues.filter(kind=kind).exclude(state="open").count()
    context.update({"kind": kind, "state": state, "issues": issues, "closed_count": closed_count})
    return render(request, "code/issues.html", context)
@login_required(login_url="landing:home")
@repository_page()
@rate_limit("issue", 10, 600)
def issue_create_view(request, repository):
    title, body = request.POST.get("title", "").strip()[:200], request.POST.get("body", "").strip()[:20000]
    if request.method == "POST":
        if not title:
            messages.error(request, "Give the issue a title.")
        else:
            issue = create_issue(repository, kind="issue", author=request.user, title=title, body=body)
            record_activity(request.user, "project", "opened_issue", 1, {"repository_id": repository.pk, "issue": issue.number})
            notify(repository.owner, request.user, "issue", f"{_name(request.user)} opened issue #{issue.number} in {_repo_label(repository)}: {title}", reverse("code:issue", args=[repository.pk, issue.number]))
            return redirect("code:issue", repository_id=repository.pk, number=issue.number)
    context = repository_context(request, repository, "issues")
    context.update({"kind": "issue", "form_title": title, "form_body": body})
    return render(request, "code/issue_form.html", context)
@login_required(login_url="landing:home")
@repository_page(write=True)
@rate_limit("pull-request", 10, 600)
def pull_create_view(request, repository):
    context = repository_context(request, repository, "pulls")
    names = [branch["name"] for branch in context["branches"]]
    source = request.POST.get("source") or request.GET.get("source") or next((name for name in names if name != repository.default_branch), "")
    target = request.POST.get("target") or request.GET.get("target") or repository.default_branch
    title, body = request.POST.get("title", "").strip()[:200], request.POST.get("body", "").strip()[:20000]
    commits, files, truncated = [], [], False
    if source in names and target in names and source != target:
        commits, files, truncated = compare_branches(repository, target, source)
    if request.method == "POST":
        if source not in names or target not in names or source == target:
            messages.error(request, "Choose two different branches.")
        elif not commits:
            messages.error(request, f"{source} has no commits that {target} doesn't already have.")
        elif repository.issues.filter(kind="pull", state="open", source_branch=source, target_branch=target).exists():
            messages.error(request, "An open pull request already exists for these branches.")
        elif not title:
            messages.error(request, "Give the pull request a title.")
        else:
            pull = create_issue(repository, kind="pull", author=request.user, title=title, body=body, source_branch=source, target_branch=target)
            record_activity(request.user, "project", "opened_pull_request", 1, {"repository_id": repository.pk, "issue": pull.number})
            notify(repository.owner, request.user, "pull", f"{_name(request.user)} opened pull request #{pull.number} in {_repo_label(repository)}: {title}", reverse("code:pull", args=[repository.pk, pull.number]))
            return redirect("code:pull", repository_id=repository.pk, number=pull.number)
    context.update({"kind": "pull", "branch_names": names, "source": source, "target": target, "commits": commits, "files": files, "truncated": truncated, "additions": sum(file["additions"] for file in files), "deletions": sum(file["deletions"] for file in files), "form_title": title or (commits[-1]["subject"] if len(commits) == 1 else ""), "form_body": body})
    return render(request, "code/issue_form.html", context)
@repository_page()
def issue_detail_view(request, repository, number):
    issue = get_object_or_404(Issue.objects.select_related("author__profile", "closed_by"), repository=repository, number=number)
    expected = "code:pull" if issue.kind == "pull" else "code:issue"
    if request.resolver_match.view_name != expected:
        return redirect(expected, repository_id=repository.pk, number=number)
    context = repository_context(request, repository, "pulls" if issue.kind == "pull" else "issues")
    branch_names = {branch["name"] for branch in context["branches"]}
    commits, files, truncated, mergeable = [], [], False, None
    if issue.kind == "pull" and {issue.source_branch, issue.target_branch} <= branch_names:
        commits, files, truncated = compare_branches(repository, issue.target_branch, issue.source_branch)
        if issue.state == "open" and commits:
            mergeable = can_merge_cleanly(repository, issue.target_branch, issue.source_branch)
    can_change_state = request.user.is_authenticated and (context["can_write"] or request.user == issue.author)
    context.update({"issue": issue, "comments": issue.comments.select_related("author__profile"), "commits": commits, "files": files, "truncated": truncated, "additions": sum(file["additions"] for file in files), "deletions": sum(file["deletions"] for file in files), "mergeable": mergeable, "branches_exist": {issue.source_branch, issue.target_branch} <= branch_names, "can_change_state": can_change_state, "tab": request.GET.get("tab", "conversation")})
    return render(request, "code/issue_detail.html", context)
def _issue_url(issue):
    return reverse("code:pull" if issue.kind == "pull" else "code:issue", args=[issue.repository_id, issue.number])
@login_required(login_url="landing:home")
@require_POST
@repository_page()
@rate_limit("issue-comment", 30, 600)
def issue_comment_view(request, repository, number):
    issue = get_object_or_404(Issue, repository=repository, number=number)
    body = request.POST.get("body", "").strip()[:5000]
    if not body:
        messages.error(request, "Write a comment before posting.")
        return redirect(_issue_url(issue))
    comment = _add_comment(request, repository, issue, body)
    return redirect(f"{_issue_url(issue)}#comment-{comment.pk}")
def _add_comment(request, repository, issue, body):
    comment = IssueComment.objects.create(issue=issue, author=request.user, body=body)
    label = "pull request" if issue.kind == "pull" else "issue"
    for recipient in {issue.author, repository.owner} - {None, request.user}:
        notify(recipient, request.user, issue.kind, f"{_name(request.user)} commented on {label} #{issue.number} in {_repo_label(repository)}", f"{_issue_url(issue)}#comment-{comment.pk}")
    return comment
@login_required(login_url="landing:home")
@require_POST
@repository_page()
def issue_state_view(request, repository, number):
    issue = get_object_or_404(Issue, repository=repository, number=number)
    if not (user_can_access(request.user, repository, write=True) or request.user == issue.author) or issue.state == "merged":
        messages.error(request, "You can't change the state of this item.")
        return redirect(_issue_url(issue))
    if request.POST.get("action") == "close" and issue.state == "open":
        issue.state, issue.closed_by, issue.closed_at = "closed", request.user, timezone.now()
    elif request.POST.get("action") == "reopen" and issue.state == "closed":
        issue.state, issue.closed_by, issue.closed_at = "open", None, None
    issue.save(update_fields=["state", "closed_by", "closed_at", "updated_at"])
    if request.POST.get("body", "").strip():
        _add_comment(request, repository, issue, request.POST["body"].strip()[:5000])
    return redirect(_issue_url(issue))
@login_required(login_url="landing:home")
@require_POST
@repository_page(write=True)
def pull_merge_view(request, repository, number):
    pull = get_object_or_404(Issue, repository=repository, number=number, kind="pull", state="open")
    try:
        pull.merge_commit = merge_branches(repository, pull.target_branch, pull.source_branch, request.user, f"Merge pull request #{pull.number} from {pull.source_branch}\n\n{pull.title}")
    except MergeConflict as conflict:
        messages.error(request, str(conflict))
        return redirect(_issue_url(pull))
    pull.state, pull.closed_by, pull.closed_at = "merged", request.user, timezone.now()
    pull.save(update_fields=["state", "merge_commit", "closed_by", "closed_at", "updated_at"])
    refresh_repository_languages(repository)
    record_activity(request.user, "project", "merged_pull_request", 1, {"repository_id": repository.pk, "issue": pull.number})
    notify(pull.author, request.user, "pull", f"{_name(request.user)} merged your pull request #{pull.number} in {_repo_label(repository)}", _issue_url(pull))
    messages.success(request, f"Merged {pull.source_branch} into {pull.target_branch}.")
    return redirect(_issue_url(pull))
@login_required(login_url="landing:home")
@require_POST
@rate_limit("repository-access", 60, 3600)
def collaborators_view(request, repository_id):
    try:
        repository = load_repository(request, repository_id)
    except RepositoryDenied as denied:
        return denied.response
    settings_url = f'{reverse("landing:repository", args=[repository.pk])}?tab=settings#collaborators'
    if not user_can_administer(request.user, repository):
        messages.error(request, "Only the owner and admins manage who has access.")
        return redirect("landing:repository", repository_id=repository.pk)
    action = request.POST.get("action", "invite")
    role = request.POST.get("role") if request.POST.get("role") in dict(RepositoryCollaborator.ROLE_CHOICES) else "write"
    item = request.POST.get("id", "")
    item = int(item) if item.isdigit() else 0
    if action == "remove":
        removed = repository.collaborators.filter(pk=item).select_related("user").first()
        if removed:
            removed.delete()
            notify(removed.user, request.user, "collaborator", f"{_name(request.user)} removed your access to {_repo_label(repository)}", reverse("landing:workspace_section", args=["projects"]))
            messages.success(request, f"{_name(removed.user)} no longer has access.")
    elif action == "update":
        repository.collaborators.filter(pk=item).update(role=role)
        messages.success(request, f"Role changed to {dict(RepositoryCollaborator.ROLE_CHOICES)[role]}.")
    elif action == "cancel":
        invitations.open_invitations(repository).filter(pk=item).delete()
        messages.success(request, "Invitation cancelled. Its link no longer works.")
    elif action == "resend":
        invitation = invitations.open_invitations(repository).filter(pk=item).first()
        if invitation:
            invitation.token, invitation.expires_at = invitation_token(), invitation_expiry()  # the old link stops working
            invitation.save(update_fields=["token", "expires_at"])
            invitations.send_email(request, invitation)
            messages.success(request, f"Invitation sent again to {invitation.invitee}. It works for another 7 days.")
    else:
        _invite(request, repository, request.POST.get("invitee", "").strip(), role)
    return redirect(settings_url)
def _invite(request, repository, invitee, role):
    """Invite someone by @handle or email. An email that belongs to a MyProgress account invites that account."""
    if "@" in invitee.strip("@") and "." in invitee.rsplit("@", 1)[-1]:
        try:
            validate_email(invitee)
        except ValidationError:
            return messages.error(request, "That email address doesn't look right.")
        email = invitee.lower()
        user = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first()
    else:
        email = ""
        profile = Profile.objects.select_related("user").filter(handle=invitee.lstrip("@").lower()).first()
        if not profile:
            return messages.error(request, "No MyProgress account has that handle. Check it, or invite them by email.")
        user = profile.user
    if user == repository.owner:
        return messages.error(request, "That's the owner: they already have full access.")
    if user and repository.collaborators.filter(user=user).exists():
        return messages.error(request, f"{_name(user)} already has access. Change their role below.")
    waiting = invitations.open_invitations(repository).filter(Q(user=user) if user else Q(user__isnull=True, email__iexact=email)).first()
    if waiting:
        waiting.role, waiting.token, waiting.expires_at, waiting.invited_by = role, invitation_token(), invitation_expiry(), request.user
        waiting.save(update_fields=["role", "token", "expires_at", "invited_by"])
        invitation = waiting
    else:
        invitation = RepositoryInvitation.objects.create(repository=repository, invited_by=request.user, user=user, email="" if user else email, role=role)
    if user:
        notify(user, request.user, "collaborator", f"{_name(request.user)} invited you to collaborate on {_repo_label(repository)} ({invitation.get_role_display()} access)", reverse("repository_invitations:detail", args=[invitation.token]))
    invitations.send_email(request, invitation)
    messages.success(request, f"Invitation sent to {invitee}. They get {invitation.get_role_display()} access when they accept it.")
@login_required(login_url="landing:home")
@require_POST
def transfer_view(request, repository_id):
    """Move your own repository into a company you're in. Its Git address stays; access then follows the company."""
    from apps.companies import services as companies
    from apps.companies.models import Company
    repository = get_object_or_404(Repository.objects.select_related("owner__profile"), pk=repository_id, owner=request.user, company__isnull=True)
    company = Company.objects.filter(slug=request.POST.get("company", ""), members__user=request.user).first()
    if company is None:
        messages.error(request, "Pick one of your companies.")
        return redirect(f'{reverse("landing:repository", args=[repository.pk])}?tab=settings')
    try:
        companies.transfer(repository, company)
    except ValueError as error:
        messages.error(request, str(error))
        return redirect(f'{reverse("landing:repository", args=[repository.pk])}?tab=settings')
    messages.success(request, f"Moved to {company.name}: it's {repository.full_name} now. Its members reach it as the company allows, and its collaborators keep their access.")
    return redirect("landing:repository", repository_id=repository.pk)
@login_required(login_url="landing:home")
@require_POST
def leave_view(request, repository_id):
    """A collaborator gives up their access to someone else's repository."""
    membership = RepositoryCollaborator.objects.select_related("repository__owner").filter(repository_id=repository_id, user=request.user).first()
    if membership is None:
        raise Http404
    membership.delete()
    notify(membership.repository.owner, request.user, "collaborator", f"{_name(request.user)} left {_repo_label(membership.repository)}", f'{reverse("landing:repository", args=[repository_id])}?tab=settings#collaborators')
    messages.success(request, f"You left {_repo_label(membership.repository)}.")
    return redirect("landing:workspace_section", section="projects")
def invitation_detail_view(request, token):
    """An invitation to collaborate: what it offers, and Accept or Decline. Signed-out visitors are asked to sign in
    or create an account with the invited email."""
    invitation = get_object_or_404(RepositoryInvitation.objects.select_related("repository__owner__profile", "repository__project", "invited_by", "user__profile"), token=token)
    if invitation.accepted_at and request.user.is_authenticated and invitation.user_id == request.user.pk:
        return redirect("landing:repository", repository_id=invitation.repository_id)
    issue, needs_confirmation = invitations.problem(invitation, request.user) if request.user.is_authenticated else ("", False)
    usable = invitation.is_open and not invitation.is_expired
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect(f'{reverse("landing:home")}?next={request.path}')
        if usable and not issue:
            if request.POST.get("action") == "decline":
                invitations.decline(invitation, request.user)
                messages.success(request, f"You declined the invitation to {_repo_label(invitation.repository)}.")
                return redirect("repository_invitations:list")
            invitations.accept(invitation, request.user)
            messages.success(request, f"You now have {invitation.get_role_display()} access to {_repo_label(invitation.repository)}.")
            return redirect("landing:repository", repository_id=invitation.repository_id)
    return render(request, "code/invitation.html", {
        "invitation": invitation, "repository": invitation.repository, "label": _repo_label(invitation.repository), "usable": usable, "problem": issue,
        "needs_confirmation": needs_confirmation, "abilities": invitations.abilities(invitation.role), "masked_email": invitations.mask(invitation.email) if invitation.email else "", "section": "code",
    })
@login_required(login_url="landing:home")
def invitation_list_view(request):
    """Invitations waiting for you, to accept or decline."""
    waiting = list(invitations.pending_for(request.user))
    for invitation in waiting:
        invitation.abilities = invitations.abilities(invitation.role)
    from apps.companies.services import pending_for as company_invitations
    return render(request, "code/invitations.html", {"invitations": waiting, "company_invitations": list(company_invitations(request.user)), "section": "code"})
