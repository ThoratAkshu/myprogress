from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.db import IntegrityError, transaction
from django.db.models import Count, Max
from django.shortcuts import redirect
from django.urls import reverse
from apps.accounts.models import Profile
from apps.core.git_service import list_branches, user_can_access, user_can_administer
from apps.core.models import Issue, Repository
class RepositoryDenied(Exception):
    def __init__(self, response):
        self.response = response
def load_repository(request, repository_id, write=False):
    """Return a repository the user may read (or write), or raise RepositoryDenied with the right redirect."""
    repository = Repository.objects.select_related("project", "owner").filter(pk=repository_id).first()
    if repository and user_can_access(request.user, repository, write=write):
        return repository
    if not request.user.is_authenticated:
        raise RepositoryDenied(redirect_to_login(request.get_full_path(), login_url=reverse("landing:home")))
    if repository and write and user_can_access(request.user, repository):
        messages.error(request, "You need write access for that.")
        raise RepositoryDenied(redirect("landing:repository", repository_id=repository.pk))
    messages.error(request, "You do not have access to that repository.")
    raise RepositoryDenied(redirect("landing:workspace_section", section="projects"))
def repository_context(request, repository, active_tab, branches=None):
    branches = list_branches(repository) if branches is None else branches
    counts = dict(repository.issues.filter(state="open").values_list("kind").annotate(total=Count("id")))
    owner_profile, _ = Profile.objects.get_or_create(user=repository.owner)
    return {
        "repository": repository,
        "owner_profile": owner_profile,
        "branches": branches,
        "can_write": user_can_access(request.user, repository, write=True),
        "can_admin": user_can_administer(request.user, repository),
        "active_tab": active_tab,
        "clone_url": request.build_absolute_uri(reverse("landing:git_root", kwargs={"owner_id": repository.owner_id, "slug": repository.slug})),
        "open_issue_count": counts.get("issue", 0),
        "open_pull_count": counts.get("pull", 0),
    }
def breadcrumbs(path):
    parts = path.split("/") if path else []
    return [{"name": part, "path": "/".join(parts[:index + 1])} for index, part in enumerate(parts)]
def create_issue(repository, **fields):
    for attempt in range(3):
        try:
            with transaction.atomic():
                number = (repository.issues.aggregate(highest=Max("number"))["highest"] or 0) + 1
                return Issue.objects.create(repository=repository, number=number, **fields)
        except IntegrityError:
            if attempt == 2:
                raise
