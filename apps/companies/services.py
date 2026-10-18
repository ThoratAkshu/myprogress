"""What companies do: create one, add repositories to it, bring people in and let them go."""
import logging
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from apps.code.invitations import name
from apps.core.git_service import initialize_repository, user_can_access
from apps.core.models import Project, Repository
from apps.notifications.services import notify
from .models import Company, CompanyInvitation, CompanyMember, Team, TeamMember

logger = logging.getLogger(__name__)
RESERVED = {"new", "invitations"}
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


def team_slug(company, text):
    return unique_slug(text, lambda slug: Team.objects.filter(company=company, slug=slug).exists(), limit=80)
