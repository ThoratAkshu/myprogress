from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from apps.accounts.models import Profile
from apps.code.invitations import ROLE_HELP, mask, name, problem
from apps.common.ratelimit import rate_limit
from apps.core.models import RepositoryCollaborator, invitation_expiry, invitation_token
from apps.notifications.services import notify
from . import services
from .forms import CompanyForm, TeamForm
from .models import Company, CompanyInvitation, CompanyMember, Team, TeamMember, TeamRepository

TABS = ("repositories", "people", "teams", "settings")


def _url(company, tab=""):
    return f'{reverse("companies:detail", args=[company.slug])}{f"?tab={tab}" if tab else ""}'


def _company(request, slug, owner=False):
    """The company and the visitor's membership; 404 for people who aren't members (or owners, if needed)."""
    company = get_object_or_404(Company, slug=slug)
    member = services.membership(company, request.user)
    if member is None or (owner and member.role != "owner"):
        raise Http404
    return company, member


@login_required(login_url="landing:home")
@rate_limit("create-company", 10, 3600)
def company_list_view(request):
    """Your companies, and a new one."""
    form = CompanyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        company = services.create_company(request.user, form.cleaned_data["name"], form.cleaned_data["description"], form.cleaned_data["website"])
        messages.success(request, f"{company.name} is ready, and you're its owner. Add a repository, then invite your team.")
        return redirect(_url(company))
    companies = services.companies_for(request.user).annotate(member_count=Count("members", distinct=True), repository_count=Count("repositories", distinct=True))
    roles = dict(CompanyMember.objects.filter(user=request.user).values_list("company_id", "role"))
    for company in companies:
        company.my_role = roles.get(company.pk)
    return render(request, "companies/list.html", {"section": "code", "companies": companies, "form": form, "invitations": services.pending_for(request.user)})


def company_detail_view(request, slug):
    """A company's page. Anyone sees its public repositories; members see what they can reach, its people and teams;
    owners also its settings."""
    company = get_object_or_404(Company, slug=slug)
    member = services.membership(company, request.user)
    tab = request.GET.get("tab") if request.GET.get("tab") in TABS else "repositories"
    if (tab in {"people", "teams"} and not member) or (tab == "settings" and not (member and member.role == "owner")):
        tab = "repositories"
    context = {"section": "code", "company": company, "member": member, "tab": tab, "is_owner": bool(member and member.role == "owner"),
               "member_count": company.members.count(), "repositories": services.visible_repositories(company, request.user)}
    if tab == "people":
        context["people"] = company.members.select_related("user__profile").annotate(team_count=Count("user__team_memberships", filter=Q(user__team_memberships__team__company=company)))
        context["owner_count"] = company.members.filter(role="owner").count()
        if context["is_owner"]:
            context["invitations"] = services.open_invitations(company)
    elif tab == "teams":
        context["teams"] = company.teams.annotate(member_count=Count("memberships", distinct=True), repository_count=Count("repositories", distinct=True))
        context["team_form"] = TeamForm()
    elif tab == "settings":
        context["form"] = CompanyForm(instance=company)
        context["base_roles"] = [(key, label, services.BASE_ROLE_HELP[key]) for key, label in Company.BASE_ROLES]
    return render(request, "companies/detail.html", context)


@login_required(login_url="landing:home")
@require_POST
@rate_limit("create-repository", 20, 3600)
def repository_create_view(request, slug):
    company, member = _company(request, slug)
    title = " ".join(request.POST.get("title", "").split())[:200]
    if not title:
        messages.error(request, "Give the repository a name.")
        return redirect(_url(company))
    try:
        repository = services.create_repository(company, request.user, title, request.POST.get("summary", "")[:500], "public" if request.POST.get("visibility") == "public" else "private")
    except Exception:
        messages.error(request, "Repository storage couldn't be set up. Try again.")
        return redirect(_url(company))
    messages.success(request, f"Created {repository.full_name}. Everyone in {company.name} can reach it as the company allows; push to it with your write key.")
    return redirect("landing:repository", repository_id=repository.pk)


def _invitee(text):
    """(user, email) for an invitation by @handle or email, or raise ValueError with what's wrong."""
    text = text.strip()
    if "@" in text.strip("@") and "." in text.rsplit("@", 1)[-1]:
        try:
            validate_email(text)
        except ValidationError:
            raise ValueError("That email address doesn't look right.")
        email = text.lower()
        return User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first(), email
    profile = Profile.objects.select_related("user").filter(handle=text.lstrip("@").lower()).first()
    if not profile:
        raise ValueError("No MyProgress account has that handle. Check it, or invite them by email.")
    return profile.user, ""


@login_required(login_url="landing:home")
@require_POST
@rate_limit("company-people", 60, 3600)
def people_view(request, slug):
    """Invite, change and remove people (owners), or leave (anyone in it)."""
    company, member = _company(request, slug)
    action, back = request.POST.get("action", ""), _url(company, "people")
    owners = company.members.filter(role="owner")
    if action == "leave":
        if member.role == "owner" and owners.count() == 1:
            messages.error(request, "You're the only owner. Make someone else an owner first, or delete the company.")
            return redirect(back)
        services.let_go(member, request.user)
        messages.success(request, f"You left {company.name}. Your projects there stay with the company.")
        return redirect("companies:list")
    if member.role != "owner":
        raise Http404
    item = request.POST.get("id", "")
    item = int(item) if item.isdigit() else 0
    role = "owner" if request.POST.get("role") == "owner" else "member"
    if action in {"role", "remove"}:
        target = company.members.filter(pk=item).select_related("user").first()
        if target is None:
            raise Http404
        if target.role == "owner" and (role == "member" or action == "remove") and owners.count() == 1:
            messages.error(request, "A company needs at least one owner. Make someone else an owner first.")
        elif action == "role":
            CompanyMember.objects.filter(pk=target.pk).update(role=role)
            messages.success(request, f"{name(target.user)} is now {'an owner' if role == 'owner' else 'a member'}.")
        else:
            services.let_go(target, request.user)
            notify(target.user, request.user, "collaborator", f"{name(request.user)} removed you from {company.name}", reverse("companies:list"))
            messages.success(request, f"{name(target.user)} is no longer in {company.name}. Their projects there passed to you.")
    elif action == "cancel":
        services.open_invitations(company).filter(pk=item).delete()
        messages.success(request, "Invitation cancelled. Its link no longer works.")
    elif action == "resend":
        invitation = services.open_invitations(company).filter(pk=item).first()
        if invitation:
            invitation.token, invitation.expires_at = invitation_token(), invitation_expiry()
            invitation.save(update_fields=["token", "expires_at"])
            services.send_invitation(request, invitation)
            messages.success(request, f"Invitation sent again to {invitation.invitee}.")
    else:
        try:
            user, email = _invitee(request.POST.get("invitee", ""))
        except ValueError as error:
            messages.error(request, str(error))
            return redirect(back)
        if user and company.members.filter(user=user).exists():
            messages.error(request, f"{name(user)} is already in {company.name}.")
            return redirect(back)
        if user and getattr(getattr(user, "profile", None), "role", "developer") != "developer":
            messages.error(request, "Companies are for student and professional accounts; that account is a recruiter or an organization.")
            return redirect(back)
        invitation = services.open_invitations(company).filter(Q(user=user) if user else Q(user__isnull=True, email__iexact=email)).first()
        if invitation:
            invitation.role, invitation.token, invitation.expires_at, invitation.invited_by = role, invitation_token(), invitation_expiry(), request.user
            invitation.save(update_fields=["role", "token", "expires_at", "invited_by"])
        else:
            invitation = CompanyInvitation.objects.create(company=company, invited_by=request.user, user=user, email="" if user else email, role=role)
        if user:
            notify(user, request.user, "collaborator", f"{name(request.user)} invited you to join {company.name}", reverse("companies:invitation", args=[invitation.token]))
        services.send_invitation(request, invitation)
        messages.success(request, f"Invitation sent. They join {company.name} as {'an owner' if role == 'owner' else 'a member'} when they accept.")
    return redirect(back)


@login_required(login_url="landing:home")
@require_POST
def team_create_view(request, slug):
    company, member = _company(request, slug, owner=True)
    form = TeamForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Give the team a name.")
        return redirect(_url(company, "teams"))
    team = form.save(commit=False)
    team.company, team.slug = company, services.team_slug(company, team.name)
    team.save()
    messages.success(request, f"Team {team.name} created. Add its people and the repositories it works on.")
    return redirect("companies:team", slug=company.slug, team_slug=team.slug)


def team_view(request, slug, team_slug):
    """A team: who's in it and which repositories it can reach, with what role. Owners change all of that here."""
    if not request.user.is_authenticated:
        return redirect(f'{reverse("landing:home")}?next={request.path}')
    company, member = _company(request, slug)
    team = get_object_or_404(Team, company=company, slug=team_slug)
    if request.method == "POST":
        if member.role != "owner":
            raise Http404
        action = request.POST.get("action", "")
        item = request.POST.get("id", "")
        item = int(item) if item.isdigit() else 0
        role = request.POST.get("role") if request.POST.get("role") in dict(RepositoryCollaborator.ROLE_CHOICES) else "write"
        if action == "add_member":
            joining = company.members.filter(pk=item).select_related("user").first()
            if joining:
                TeamMember.objects.get_or_create(team=team, user=joining.user)
                notify(joining.user, request.user, "collaborator", f"{name(request.user)} added you to the {team.name} team in {company.name}", reverse("companies:team", args=[company.slug, team.slug]))
        elif action == "remove_member":
            team.memberships.filter(pk=item).delete()
        elif action == "add_repository":
            repository = company.repositories.filter(pk=item).first()
            if repository:
                TeamRepository.objects.update_or_create(team=team, repository=repository, defaults={"role": role})
        elif action == "update_repository":
            team.repositories.filter(pk=item).update(role=role)
        elif action == "remove_repository":
            team.repositories.filter(pk=item).delete()
        elif action == "details":
            form = TeamForm(request.POST, instance=team)
            if form.is_valid():
                form.save()
        elif action == "delete":
            team.delete()
            messages.success(request, f"Deleted the {team.name} team. Its people are still in {company.name}.")
            return redirect(_url(company, "teams"))
        return redirect("companies:team", slug=company.slug, team_slug=team.slug)
    in_team = set(team.memberships.values_list("user_id", flat=True))
    on_team = set(team.repositories.values_list("repository_id", flat=True))
    return render(request, "companies/team.html", {
        "section": "code", "company": company, "member": member, "team": team, "is_owner": member.role == "owner",
        "memberships": team.memberships.select_related("user__profile"), "team_repositories": team.repositories.select_related("repository__company", "repository__project"),
        "addable_members": company.members.exclude(user_id__in=in_team).select_related("user__profile"),
        "addable_repositories": company.repositories.exclude(pk__in=on_team).select_related("company"),
        "role_choices": RepositoryCollaborator.ROLE_CHOICES, "role_help": ROLE_HELP,
    })


@login_required(login_url="landing:home")
@require_POST
def settings_view(request, slug):
    company, member = _company(request, slug, owner=True)
    if request.POST.get("action") == "delete":
        if request.POST.get("confirm", "").strip() != company.slug:
            messages.error(request, f"Type {company.slug} to confirm deleting the company.")
            return redirect(_url(company, "settings"))
        services.delete_company(company)
        messages.success(request, f"Deleted {company.name}. Its repositories went back to the members who made them.")
        return redirect("companies:list")
    form = CompanyForm(request.POST, instance=company)
    if form.is_valid():
        company = form.save(commit=False)
        if request.POST.get("base_role") in dict(Company.BASE_ROLES):
            company.base_role = request.POST["base_role"]
        company.save()
        messages.success(request, "Company settings saved.")
    else:
        messages.error(request, "Check the company's name and website.")
    return redirect(_url(company, "settings"))


def invitation_view(request, token):
    """An invitation to join a company: Accept or Decline, for the account or email address it was sent to."""
    invitation = get_object_or_404(CompanyInvitation.objects.select_related("company", "invited_by__profile", "user__profile"), token=token)
    if request.user.is_authenticated and services.membership(invitation.company, request.user):
        return redirect(_url(invitation.company))
    issue, needs_confirmation = problem(invitation, request.user) if request.user.is_authenticated else ("", False)
    usable = invitation.is_open and not invitation.is_expired
    if request.method == "POST" and request.user.is_authenticated and usable and not issue:
        if request.POST.get("action") == "decline":
            services.decline(invitation, request.user)
            messages.success(request, f"You declined the invitation to {invitation.company.name}.")
            return redirect("repository_invitations:list")
        services.accept(invitation, request.user)
        messages.success(request, f"Welcome to {invitation.company.name}.")
        return redirect(_url(invitation.company))
    return render(request, "companies/invitation.html", {
        "invitation": invitation, "company": invitation.company, "usable": usable, "problem": issue, "needs_confirmation": needs_confirmation,
        "masked_email": mask(invitation.email) if invitation.email else "", "base_role_help": services.BASE_ROLE_HELP[invitation.company.base_role],
        "member_count": invitation.company.members.count(), "section": "code",
    })
