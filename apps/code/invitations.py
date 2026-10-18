"""Inviting people to collaborate on a repository, as on GitHub: an invitation by MyProgress handle or by email,
access only once they accept, and roles from Read to Admin."""
import logging
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Profile
from apps.core.models import RepositoryCollaborator, RepositoryInvitation
from apps.notifications.services import notify

logger = logging.getLogger(__name__)
ROLE_HELP = [
    ("read", "Read", "View and clone the code, even when it's private, and open issues"),
    ("write", "Write", "Also push, create branches, and open and merge pull requests"),
    ("maintain", "Maintain", "Also the repository's settings, like its default branch"),
    ("admin", "Admin", "Also its visibility, and inviting, changing and removing people"),
]


def abilities(role):
    """Everything a role allows, as sentences that stand on their own: Read's, then Write's, and so on up to it."""
    found = []
    for key, _, text in ROLE_HELP:
        text = text.removeprefix("Also ")
        found.append(text[0].upper() + text[1:])
        if key == role:
            break
    return found


def name(user):
    return user.get_full_name() or getattr(getattr(user, "profile", None), "handle", "") or "A MyProgress member"


def label(repository):
    return repository.full_name


def open_invitations(repository):
    return repository.invitations.filter(accepted_at__isnull=True, declined_at__isnull=True).select_related("user__profile", "invited_by")


def pending_for(user):
    """Invitations waiting for this person: sent to their account, or to their email once they've confirmed it."""
    if not user.is_authenticated:
        return RepositoryInvitation.objects.none()
    mine = Q(user=user)
    profile = Profile.objects.filter(user=user).first()
    if profile and profile.email_verified_at and user.email:
        mine |= Q(user__isnull=True, email__iexact=user.email)
    return RepositoryInvitation.objects.filter(mine, accepted_at__isnull=True, declined_at__isnull=True, expires_at__gt=timezone.now()).select_related("repository__owner__profile", "invited_by")


def mask(email):
    local, _, domain = email.partition("@")
    return f"{local[:1]}{'•' * max(len(local) - 1, 2)}@{domain}"


def problem(invitation, user):
    """Why this account can't accept the invitation ("" if it can), and whether confirming its email would fix it."""
    if invitation.user_id:
        if invitation.user_id != user.pk:
            return "This invitation is for another MyProgress account. Ask the owner to invite you.", False
        return "", False
    if user.email.strip().lower() != invitation.email.strip().lower():
        return f"This invitation was sent to {mask(invitation.email)}. Sign in with that email to accept it, or ask the owner to invite {user.email}.", False
    profile = Profile.objects.filter(user=user).first()
    if not (profile and profile.email_verified_at):
        return "Confirm your email first: open the link we emailed you, then open this invitation again.", True
    return "", False


def send_email(request, invitation):
    """The invitation by email, with what the role allows and a link to accept it."""
    recipient = invitation.user.email if invitation.user_id else invitation.email
    if not recipient:
        return
    link = request.build_absolute_uri(reverse("repository_invitations:detail", args=[invitation.token]))
    role = dict((key, text) for key, _, text in ROLE_HELP)[invitation.role]
    body = (f"Hi,\n\n{name(invitation.invited_by)} invited you to collaborate on {label(invitation.repository)} on MyProgress, with "
            f"{invitation.get_role_display()} access: {role[0].lower()}{role[1:]}.\n\nAccept or decline here (the link works for 7 days):\n{link}\n\n"
            "If you don't have a MyProgress account yet, create one with this email address to accept.\n")
    try:
        send_mail(f"{name(invitation.invited_by)} invited you to {label(invitation.repository)}", body, None, [recipient])
    except Exception:
        logger.exception("Could not send a repository invitation to %s", recipient)


def accept(invitation, user):
    """Give the access the invitation offered. Returns the collaborator."""
    with transaction.atomic():
        collaborator, _ = RepositoryCollaborator.objects.update_or_create(repository=invitation.repository, user=user, defaults={"role": invitation.role})
        RepositoryInvitation.objects.filter(pk=invitation.pk).update(user=user, accepted_at=timezone.now())
    if invitation.invited_by_id:
        notify(invitation.invited_by, user, "collaborator", f"{name(user)} accepted your invitation to {label(invitation.repository)}", f'{reverse("landing:repository", args=[invitation.repository_id])}?tab=settings#collaborators')
    return collaborator


def decline(invitation, user):
    RepositoryInvitation.objects.filter(pk=invitation.pk).update(declined_at=timezone.now())
    if invitation.invited_by_id:
        notify(invitation.invited_by, user, "collaborator", f"{name(user)} declined your invitation to {label(invitation.repository)}", f'{reverse("landing:repository", args=[invitation.repository_id])}?tab=settings#collaborators')
