"""Companies: people who own repositories together, like an organization on GitHub. Owners run the company, every
member gets its base permission on its repositories, and teams get more on the repositories they work on."""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from apps.core.models import RepositoryCollaborator, invitation_expiry, invitation_token


class Company(models.Model):
    BASE_ROLES = [("none", "No access"), ("read", "Read"), ("write", "Write")]
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=60, unique=True)
    description = models.CharField(max_length=240, blank=True)
    website = models.URLField(blank=True)
    base_role = models.CharField(max_length=10, choices=BASE_ROLES, default="read", help_text="What every member can do in every repository of the company")
    # Security, set by owners. Domains are added by an owner with a confirmed email on them, so a company can't claim
    # someone else's; with members_from_domains on, only people with a confirmed email there can join.
    REPOSITORY_CREATION = [("all", "Public and private"), ("private", "Private only"), ("none", "Owners only")]
    email_domains = models.JSONField(default=list, blank=True)
    members_from_domains = models.BooleanField(default=False, help_text="Only people with a confirmed email on the company's domains can join")
    repository_creation = models.CharField(max_length=10, choices=REPOSITORY_CREATION, default="all", help_text="What members (not owners) can create")
    members_change_visibility = models.BooleanField(default=True, help_text="Repository admins who are members can make repositories public or private")
    members_invite_outside = models.BooleanField(default=True, help_text="Repository admins who are members can invite people from outside the company")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"
    def __str__(self):
        return self.name
    @property
    def initials(self):
        words = [word for word in self.name.split() if word[:1].isalnum()]
        return ("".join(word[0] for word in words[:2]) or self.slug[:2]).upper()


class CompanyMember(models.Model):
    ROLES = [("owner", "Owner"), ("member", "Member")]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="company_memberships")
    role = models.CharField(max_length=10, choices=ROLES, default="member")
    joined_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["role", "joined_at"]
        constraints = [models.UniqueConstraint(fields=["company", "user"], name="company_member_once")]


class CompanyInvitation(models.Model):
    """An invitation to join a company, accepted like a repository invitation: by that account, or by an account
    with that confirmed email address."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="invitations")
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name="company_invitations")
    email = models.EmailField(blank=True)
    role = models.CharField(max_length=10, choices=CompanyMember.ROLES, default="member")
    token = models.CharField(max_length=64, unique=True, default=invitation_token)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=invitation_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-created_at"]
    @property
    def is_open(self):
        return self.accepted_at is None and self.declined_at is None
    @property
    def is_expired(self):
        return self.is_open and self.expires_at <= timezone.now()
    @property
    def invitee(self):
        return self.user.profile.handle if self.user_id and hasattr(self.user, "profile") else self.email


class Team(models.Model):
    """A group of a company's members, given access to some of its repositories together."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80)
    description = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["company", "slug"], name="team_slug_once")]
    def __str__(self):
        return self.name


class TeamMember(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_memberships")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "user"], name="team_member_once")]


class TeamRepository(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="repositories")
    repository = models.ForeignKey("core.Repository", on_delete=models.CASCADE, related_name="team_access")
    role = models.CharField(max_length=10, choices=RepositoryCollaborator.ROLE_CHOICES, default="write")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "repository"], name="team_repository_once")]
