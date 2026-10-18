"""What companies do: create one, add repositories to it, bring people in and let them go."""
import logging
import re
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from apps.accounts.identity import DISPOSABLE_EMAIL_DOMAINS, PERSONAL_EMAIL_DOMAINS, domain_of
from apps.accounts.models import Profile, TwoFactor
from apps.code.invitations import name
from apps.core.git_service import initialize_repository, user_can_access
from apps.core.models import Project, Repository, RepositoryCollaborator, RepositoryInvitation
from apps.notifications.services import notify
from .models import Company, CompanyInvitation, CompanyMember, Team, TeamMember

logger = logging.getLogger(__name__)
RESERVED = {"new", "invitations"}
CREATION_HELP = {"all": "Members create private and public repositories",
                 "private": "Members create private repositories; only owners make public ones",
                 "none": "Only owners create repositories, and move repositories into the company"}
BASE_ROLE_HELP = {"none": "Members only reach the repositories their teams or invitations give them",
                  "read": "Every member can view and clone every repository, even private ones",
                  "write": "Every member can also push, branch and merge pull requests in every repository"}


def membership(company, user):
    if not user.is_authenticated:
        return None
    return CompanyMember.objects.filter(company=company, user=user).first()


def companies_for(user):
    # By id, so counting a company's members afterwards counts all of them, not just this person's row.
    return Company.objects.filter(pk__in=CompanyMember.objects.filter(user=user).values("company")) if user.is_authenticated else Company.objects.none()


def unique_slug(text, taken, limit=60):
    base = slugify(text)[:limit - 4] or "company"
    slug, counter = base, 2
    while slug in RESERVED or taken(slug):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def create_company(user, name_, description="", website=""):
    with transaction.atomic():
        company = Company.objects.create(name=name_.strip(), slug=unique_slug(name_, lambda slug: Company.objects.filter(slug=slug).exists()), description=description.strip(), website=website, created_by=user)
        CompanyMember.objects.create(company=company, user=user, role="owner")
    return company


def repository_slug(company, owner, text):
    """A name free both in the company and among the repositories its maker owns (their Git address uses it)."""
    taken = Q(owner=owner) | Q(company=company) if company else Q(owner=owner)
    return unique_slug(text, lambda slug: Repository.objects.filter(taken, slug=slug).exists(), limit=90)


def create_repository(company, user, title, summary="", visibility="private"):
    """A new project and its repository, owned by the company. The member who makes it is its admin."""
    with transaction.atomic():
        project = Project.objects.create(owner=user, title=title.strip()[:200], summary=summary.strip(), is_public=visibility == "public")
        repository = Repository.objects.create(project=project, owner=user, company=company, slug=repository_slug(company, user, title), visibility=visibility)
    try:
        initialize_repository(repository)
    except Exception:
        project.delete()
        raise
    return repository


def transfer(repository, company):
    """Move a personal repository into a company. Its Git address stays the same; who can reach it now follows the
    company, and its existing collaborators keep their access."""
    if Repository.objects.filter(company=company, slug=repository.slug).exclude(pk=repository.pk).exists():
        raise ValueError(f"{company.name} already has a repository called {repository.slug}. Rename yours first.")
    repository.company = company
    repository.save(update_fields=["company", "updated_at"])


def visible_repositories(company, user):
    repositories = company.repositories.select_related("project", "owner__profile", "company").order_by("-updated_at")
    return [repository for repository in repositories if user_can_access(user, repository)]


def let_go(member, actor):
    """Take someone out of the company: out of its teams, and their projects there pass to whoever let them go (an
    owner), so nothing in the company stays theirs. Repositories keep their Git addresses."""
    with transaction.atomic():
        TeamMember.objects.filter(team__company=member.company, user=member.user).delete()
        receiver = actor if actor != member.user else CompanyMember.objects.filter(company=member.company, role="owner").exclude(user=member.user).select_related("user").first().user
        Project.objects.filter(owner=member.user, repository__company=member.company).update(owner=receiver)
        member.delete()


def delete_company(company):
    """Repositories go back to whoever holds their project now: the member who made them, or the owner their projects
    passed to when that member left, so nobody who left gets a repository back."""
    with transaction.atomic():
        for repository in company.repositories.select_related("project"):
            if repository.project.owner_id != repository.owner_id:
                repository.owner = repository.project.owner
                if Repository.objects.filter(owner=repository.owner, slug=repository.slug).exclude(pk=repository.pk).exists():
                    repository.slug = repository_slug(None, repository.owner, repository.slug)
                repository.save(update_fields=["owner", "slug"])
        company.delete()


def open_invitations(company):
    return company.invitations.filter(accepted_at__isnull=True, declined_at__isnull=True).select_related("user__profile", "invited_by")


def pending_for(user):
    from apps.accounts.models import Profile
    if not user.is_authenticated:
        return CompanyInvitation.objects.none()
    mine = Q(user=user)
    profile = Profile.objects.filter(user=user).first()
    if profile and profile.email_verified_at and user.email:
        mine |= Q(user__isnull=True, email__iexact=user.email)
    return CompanyInvitation.objects.filter(mine, accepted_at__isnull=True, declined_at__isnull=True, expires_at__gt=timezone.now()).select_related("company", "invited_by")


def send_invitation(request, invitation):
    recipient = invitation.user.email if invitation.user_id else invitation.email
    if not recipient:
        return
    link = request.build_absolute_uri(reverse("companies:invitation", args=[invitation.token]))
    role = "an owner, who runs the company with the other owners" if invitation.role == "owner" else "a member"
    body = (f"Hi,\n\n{name(invitation.invited_by)} invited you to join {invitation.company.name} on MyProgress as {role}. "
            f"Its members work on the company's repositories together.\n\nAccept or decline here (the link works for 7 days):\n{link}\n\n"
            "If you don't have a MyProgress account yet, create one with this email address to accept.\n")
    try:
        send_mail(f"Join {invitation.company.name} on MyProgress", body, None, [recipient])
    except Exception:
        logger.exception("Could not send a company invitation to %s", recipient)


def accept(invitation, user):
    with transaction.atomic():
        member, _ = CompanyMember.objects.get_or_create(company=invitation.company, user=user, defaults={"role": invitation.role})
        CompanyInvitation.objects.filter(pk=invitation.pk).update(user=user, accepted_at=timezone.now())
    if invitation.invited_by_id:
        notify(invitation.invited_by, user, "collaborator", f"{name(user)} joined {invitation.company.name}", f'{reverse("companies:detail", args=[invitation.company.slug])}?tab=people')
    return member


def decline(invitation, user):
    CompanyInvitation.objects.filter(pk=invitation.pk).update(declined_at=timezone.now())
    if invitation.invited_by_id:
        notify(invitation.invited_by, user, "collaborator", f"{name(user)} declined your invitation to {invitation.company.name}", f'{reverse("companies:detail", args=[invitation.company.slug])}?tab=people')


DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def on_domains(email, domains):
    """An address at acme.com or a part of it (eu.acme.com) is on acme.com."""
    domain = domain_of(email)
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in domains)


def has_confirmed_email(user):
    return bool(user.email) and Profile.objects.filter(user=user, email_verified_at__isnull=False).exists()


def clean_domains(company, owner, text):
    """The email domains an owner saves. Ones already on the company stay; adding one takes the saving owner's
    confirmed email on it, so nobody can claim another company's domain. Raises ValueError with what's wrong."""
    wanted = list(dict.fromkeys(part.strip().lower().removeprefix("@") for part in re.split(r"[,\s]+", text) if part.strip()))
    if len(wanted) > 5:
        raise ValueError("Add up to 5 domains.")
    for domain in wanted:
        if not DOMAIN.match(domain):
            raise ValueError(f"{domain} isn't a domain. Write it like acme.com.")
        if domain in PERSONAL_EMAIL_DOMAINS or domain in DISPOSABLE_EMAIL_DOMAINS:
            raise ValueError(f"Anyone can have an address at {domain}, so it can't stand for {company.name}.")
        if domain not in company.email_domains and not (has_confirmed_email(owner) and on_domains(owner.email, [domain])):
            raise ValueError(f"To add {domain}, you need a confirmed email on it; yours is {owner.email}. An owner with an @{domain} email can add it.")
    return wanted


def domains_label(company):
    return " or ".join(f"@{domain}" for domain in company.email_domains)


def only_from_domains(company):
    return company.members_from_domains and bool(company.email_domains)


def invite_problem(company, user, email):
    """Why this person can't be invited ("" if they can): companies that only take people from their domains."""
    address = user.email if user else email
    if only_from_domains(company) and not on_domains(address, company.email_domains):
        return f"Only people with a {domains_label(company)} email can join {company.name}, and {address} isn't one."
    return ""


def uses_two_step(user):
    return TwoFactor.objects.filter(user=user, enabled_at__isnull=False).exists()


def join_problem(company, user):
    """Why this account can't join ("" if it can), and whether confirming its email would fix it."""
    if company.require_two_factor and not uses_two_step(user):
        return f"{company.name} requires two-step sign-in. Turn it on in Security settings, then open this invitation again.", False
    if not only_from_domains(company):
        return "", False
    if not on_domains(user.email, company.email_domains):
        return f"Only people with a confirmed {domains_label(company)} email can join {company.name}. Your account's email is {user.email}.", False
    if not has_confirmed_email(user):
        return f"Confirm your email first: open the link we sent to {user.email}, then open this invitation again.", True
    return "", False


def creation_problem(company, member, visibility):
    """Why this member can't create this repository ("" if they can)."""
    if member.role == "owner" or company.repository_creation == "all":
        return ""
    if company.repository_creation == "none":
        return f"Only {company.name}'s owners create repositories. Ask one of them."
    if visibility == "public":
        return f"Members create private repositories in {company.name}; only its owners make public ones."
    return ""


def outside_problem(repository, actor, user):
    """Why this admin can't give access to someone outside the repository's company ("" if they can)."""
    company = repository.company
    if not company or company.members_invite_outside or (user and company.members.filter(user=user).exists()):
        return ""
    if company.members.filter(user=actor, role="owner").exists():
        return ""
    return f"Only {company.name}'s owners give access to people outside the company. Invite a member, or ask an owner."


def outside_collaborators(company):
    """People outside the company with access to its repositories, each with what they reach."""
    rows = (RepositoryCollaborator.objects.filter(repository__company=company).exclude(user__in=company.members.values("user"))
            .select_related("user__profile", "repository").order_by("user__first_name", "user_id", "repository__slug"))
    people = {}
    for row in rows:
        people.setdefault(row.user_id, {"user": row.user, "access": []})["access"].append(row)
    return list(people.values())


def remove_outside(company, user):
    """Take an outside collaborator off every repository of the company, and cancel their waiting invitations."""
    with transaction.atomic():
        RepositoryCollaborator.objects.filter(repository__company=company, user=user).delete()
        RepositoryInvitation.objects.filter(repository__company=company, user=user, accepted_at__isnull=True, declined_at__isnull=True).delete()


SECURITY_FIELDS = ["email_domains", "members_from_domains", "repository_creation", "members_change_visibility", "members_invite_outside", "require_two_factor"]


def security_changes(before, company):
    """One sentence for the change log per security setting an owner changed."""
    changes = []
    if before["email_domains"] != company.email_domains:
        changes.append(f"set the email domains to {', '.join(company.email_domains)}" if company.email_domains else "removed the email domains")
    if before["members_from_domains"] != company.members_from_domains:
        changes.append("let only people from its email domains join" if company.members_from_domains else "let people from any email domain join")
    if before["repository_creation"] != company.repository_creation:
        changes.append(f"set who creates repositories to “{company.get_repository_creation_display()}”")
    if before["members_change_visibility"] != company.members_change_visibility:
        changes.append("let repository admins change visibility" if company.members_change_visibility else "kept visibility changes to owners")
    if before["members_invite_outside"] != company.members_invite_outside:
        changes.append("let repository admins invite people from outside the company" if company.members_invite_outside else "kept access for people outside the company to owners")
    if before["require_two_factor"] != company.require_two_factor:
        changes.append("required two-step sign-in" if company.require_two_factor else "stopped requiring two-step sign-in")
    return changes


def team_slug(company, text):
    return unique_slug(text, lambda slug: Team.objects.filter(company=company, slug=slug).exists(), limit=80)
