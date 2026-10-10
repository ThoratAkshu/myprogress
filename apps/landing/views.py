from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from datetime import timedelta
from collections import Counter
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from django.utils.text import slugify
from django.views.generic import TemplateView
from apps.accounts.forms import EmailLoginForm, ProfileForm, RegistrationForm
from apps.accounts.models import Follow, Profile
from apps.core.models import ContentView, DailyLoopCompletion, EarningTransaction, GitAccessToken, LearningPost, Project, ProjectMilestone, Repository, RepositoryCollaborator
from apps.core.services import complete_daily_step, contribution_calendar, earning_balance, language_breakdown, leaderboard, platform_languages, record_activity, refresh_rank, score_breakdown
from apps.learning.views import record_post_view
from apps.notifications.services import notify
from apps.recruiting.models import RECRUITER_ROLES, ContactRequest, PortfolioView, ShortlistEntry
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from apps.core.git_service import authenticate_git_request, branch_heads, clean_repo_path, commit_file, count_new_commits, create_branch, find_readme, initialize_repository, last_commit, list_branches, list_commits, list_contributors, list_tree, object_type, read_blob, refresh_repository_languages, resolve_ref, smart_http, user_can_access
from apps.code.access import RepositoryDenied, breadcrumbs, load_repository, repository_context
from urllib.parse import urlencode
import logging
logger = logging.getLogger(__name__)
@method_decorator(never_cache, name="dispatch")
class LandingPageView(TemplateView):
    template_name = "landing/index.html"
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("landing:dashboard")
        return super().dispatch(request, *args, **kwargs)
@never_cache
def register_view(request):
    if request.user.is_authenticated:
        return redirect("landing:dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = User.objects.create_user(username=form.cleaned_data["email"], email=form.cleaned_data["email"], password=form.cleaned_data["password"], first_name=form.cleaned_data["first_name"].strip(), last_name=form.cleaned_data["last_name"].strip())
            Profile.objects.create(user=user, role=form.cleaned_data["role"])
        login(request, user)
        request.session.cycle_key()
        return redirect("landing:dashboard")
    if request.method == "POST":
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return render(request, "landing/register.html", {"form": form})
def login_view(request):
    if request.method != "POST":
        return redirect("landing:home")
    form = EmailLoginForm(request, request.POST)
    if form.is_valid():
        login(request, form.user)
        record_activity(form.user, "login", "signed_in", 1)
        request.session.set_expiry(60 * 60 * 24 * 30 if form.cleaned_data["remember"] else 0)
        next_url = request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect("landing:dashboard")
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)
    return redirect("landing:home")
@require_POST
def logout_view(request):
    logout(request)
    return redirect("landing:home")
@login_required(login_url="landing:home")
@never_cache
def dashboard_view(request):
    if Profile.objects.filter(user=request.user, role__in=RECRUITER_ROLES).exists():
        return redirect("recruiting:search")
    return render(request, "landing/dashboard.html", _workspace_context(request))

@login_required(login_url="landing:home")
def account_identity_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return JsonResponse({"name": request.user.get_full_name() or request.user.username, "account": request.user.email or request.user.username, "role": profile.get_role_display(), "initials": ((request.user.first_name[:1] + request.user.last_name[:1]) or request.user.username[:2]).upper()})
def _workspace_context(request, section="overview"):
    profile = refresh_rank(request.user)
    projects = request.user.projects.all()
    posts = LearningPost.objects.filter(is_public=True).select_related("author__profile")[:3]
    project_count = request.user.projects.count()
    completed_count = request.user.projects.filter(status="complete").count()
    setup_items = [bool(profile.headline), bool(profile.skills), project_count > 0, True]
    own_posts = request.user.learning_posts.all()
    today = timezone.localdate()
    active_dates = {timezone.localdate(value) for value in request.user.activity_events.values_list("created_at", flat=True)}
    weekly_days = [{"label": (today - timedelta(days=offset)).strftime("%a")[:1], "date": (today - timedelta(days=offset)).day, "active": today - timedelta(days=offset) in active_dates, "today": offset == 0} for offset in range(6, -1, -1)]
    streak = 0
    cursor = today
    while cursor in active_dates:
        streak += 1
        cursor -= timedelta(days=1)
    loop_steps = set(request.user.daily_loop_completions.filter(completed_on=today).values_list("step", flat=True))
    return {"section": section, "profile": profile, "projects": projects, "posts": posts, "own_posts": own_posts, "project_count": project_count, "completed_count": completed_count, "learning_count": own_posts.count(), "total_views": ContentView.objects.filter(post__author=request.user).count(), "total_earnings": earning_balance(request.user), "transactions": request.user.earning_transactions.all()[:10], "follower_count": request.user.follower_relationships.count(), "following_count": request.user.following_relationships.count(), "weekly_days": weekly_days, "weekly_active_count": sum(day["active"] for day in weekly_days), "streak": streak, "loop_steps": loop_steps, "loop_completed_count": len(loop_steps), "setup_percent": sum(setup_items) * 25, "initials": ((request.user.first_name[:1] + request.user.last_name[:1]) or request.user.username[:2]).upper()}
@login_required(login_url="landing:home")
@never_cache
def workspace_section_view(request, section):
    allowed = {"portfolio", "projects", "learning", "earnings", "rankings", "network"}
    if section not in allowed:
        return redirect("landing:dashboard")
    context = _workspace_context(request, section)
    if section == "projects":
        projects = list(request.user.projects.select_related("repository").prefetch_related("milestones"))
        skill_counts = Counter(skill for project in projects for skill in project.skill_list)
        context["projects"] = projects
        context["project_status_counts"] = Counter(project.status for project in projects)
        context["project_skills"] = sorted(skill_counts.items(), key=lambda item: (-item[1], item[0].lower()))
        context["repositories"] = request.user.repositories.select_related("project")
        context["shared_repositories"] = request.user.repository_memberships.select_related("repository__owner__profile")
        context["new_git_token"] = request.session.pop("new_git_token", None)
    if section == "rankings":
        language = request.GET.get("language", "").strip()
        board = list(leaderboard(language or None))
        for entry in board:
            top = language_breakdown([repository.languages for repository in entry.user.repositories.all()], limit=1)
            entry.top_language = top[0]["name"] if top else ""
        context.update({"score_components": score_breakdown(request.user), "leaderboard": board, "leaderboard_language": language, "languages": platform_languages(), "is_recruiter": context["profile"].role in RECRUITER_ROLES})
    if section == "learning":
        tabs = [("for-you", "For you"), ("following", "Following"), ("mine", f"My content {context['learning_count']}")]
        tab = request.GET.get("tab") if request.GET.get("tab") in dict(tabs) else "for-you"
        posts = LearningPost.objects.select_related("author__profile", "project").annotate(like_count=Count("likes", distinct=True), comment_count=Count("comments", distinct=True))
        if tab == "mine":
            posts = posts.filter(author=request.user)
        elif tab == "following":
            posts = posts.filter(is_public=True, author__in=request.user.following_relationships.values("following"))
        else:
            posts = posts.filter(is_public=True)
        context.update({"learning_tabs": tabs, "learning_tab": tab, "learning_page": Paginator(posts.order_by("-published_at"), 12).get_page(request.GET.get("page"))})
    if section == "network":
        context["contact_requests"] = request.user.contact_requests.select_related("recruiter__profile")[:20]
    if section == "portfolio":
        views = PortfolioView.objects.filter(profile=context["profile"], viewed_on__gte=timezone.localdate() - timedelta(days=30))
        context["portfolio_views"] = views.count()
        context["recruiter_views"] = views.filter(viewer_role__in=RECRUITER_ROLES).count()
    return render(request, "landing/workspace_section.html", context)
@login_required(login_url="landing:home")
@require_POST
def create_project_view(request):
    title = request.POST.get("title", "").strip()
    if not title:
        messages.error(request, "Project title is required.")
        return redirect("landing:dashboard")
    project = request.user.projects.create(title=title[:140], summary=request.POST.get("summary", "").strip(), skills=request.POST.get("skills", "").strip(), status="planning")
    ProjectMilestone.objects.bulk_create([ProjectMilestone(project=project, title=title, position=position) for position, title in enumerate(["Plan the solution", "Build the core", "Document the work", "Publish a demo"])])
    record_activity(request.user, "project", "created_project", 3, {"project_id": project.pk})
    complete_daily_step(request.user, "build")
    refresh_rank(request.user)
    messages.success(request, "Project created. You can now add its proof of work.")
    return redirect("landing:dashboard")
@login_required(login_url="landing:home")
@require_POST
def update_project_view(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    live_url = request.POST.get("live_url", "").strip()
    if live_url:
        try:
            URLValidator(schemes=["http", "https"])(live_url)
        except ValidationError:
            messages.error(request, "Enter a full live demo URL starting with https://.")
            return redirect("landing:workspace_section", section="projects")
    project.summary = request.POST.get("summary", "").strip()
    project.skills = ", ".join(dict.fromkeys(skill.strip() for skill in request.POST.get("skills", "").split(",") if skill.strip()))[:500]
    project.live_url = live_url[:200]
    project.is_public = request.POST.get("is_public") == "on"
    completed_ids = {int(value) for value in request.POST.getlist("milestones") if value.isdigit()}
    milestones = list(project.milestones.all())
    for milestone in milestones:
        if (milestone.pk in completed_ids) != milestone.is_complete:
            milestone.is_complete = milestone.pk in completed_ids
            milestone.completed_at = timezone.now() if milestone.is_complete else None
    ProjectMilestone.objects.bulk_update(milestones, ["is_complete", "completed_at"])
    completed = sum(milestone.is_complete for milestone in milestones)
    project.status = "complete" if milestones and completed == len(milestones) else "building" if completed else "planning"
    project.save(update_fields=["summary", "skills", "live_url", "is_public", "status", "updated_at"])
    refresh_rank(request.user)
    messages.success(request, "Project shipped. Push code to its repository so it counts as verified." if project.status == "complete" and not project.has_verified_code else "Project updated.")
    return redirect("landing:workspace_section", section="projects")
@login_required(login_url="landing:home")
def learning_view(request, post_id):
    """Old share links: record the view and send readers to the post page (never off-site)."""
    post = LearningPost.objects.filter(pk=post_id, is_public=True).first()
    if not post:
        return redirect("landing:workspace_section", section="learning")
    record_post_view(request, post)
    return redirect("learning:detail", post_id=post.pk)
@login_required(login_url="landing:home")
@require_POST
def complete_loop_view(request, step):
    if step not in {"build", "learn", "share"}:
        return redirect("landing:dashboard")
    complete_daily_step(request.user, step)
    event_type = {"build": "project", "learn": "learning", "share": "network"}[step]
    record_activity(request.user, event_type, f"completed_{step}_loop", 1)
    return redirect("landing:dashboard")
@login_required(login_url="landing:home")
@require_POST
def create_repository_view(request, project_id):
    project = Project.objects.filter(pk=project_id, owner=request.user).first()
    if not project or hasattr(project, "repository"):
        messages.error(request, "That project is unavailable or already has a repository.")
        return redirect("landing:workspace_section", section="projects")
    base_slug = slugify(request.POST.get("name") or project.title)[:90] or f"project-{project.pk}"
    slug = base_slug
    counter = 2
    while Repository.objects.filter(owner=request.user, slug=slug).exists():
        slug = f"{base_slug[:85]}-{counter}"
        counter += 1
    visibility = request.POST.get("visibility") if request.POST.get("visibility") in {"private", "public"} else "private"
    repository = Repository.objects.create(project=project, owner=request.user, slug=slug, visibility=visibility)
    try:
        initialize_repository(repository)
    except Exception:
        repository.delete()
        messages.error(request, "Repository storage could not be initialized.")
        return redirect("landing:workspace_section", section="projects")
    record_activity(request.user, "project", "created_repository", 5, {"repository_id": repository.pk})
    messages.success(request, "Repository created. Create a token before your first push.")
    return redirect("landing:repository", repository_id=repository.pk)
def repository_view(request, repository_id):
    try:
        repository = load_repository(request, repository_id)
    except RepositoryDenied as denied:
        return denied.response
    context = repository_context(request, repository, "code")
    can_write, can_admin, branches = context["can_write"], context["can_admin"], context["branches"]
    allowed_tabs = {"code", "branches", "commits", "contributors", "settings"} if can_admin else {"code", "branches", "commits", "contributors"}
    active_tab = request.GET.get("tab", "code") if request.GET.get("tab", "code") in allowed_tabs else "code"
    if request.method == "POST":
        action = request.POST.get("action")
        if (action in {"add_file", "create_branch"} and not can_write) or (action == "settings" and not can_admin):
            messages.error(request, "You do not have permission to change this repository.")
            return redirect("landing:repository", repository_id=repository.pk)
        try:
            if action == "add_file":
                commit_file(repository, request.POST.get("path", ""), request.POST.get("content", ""), request.user, request.POST.get("message", ""))
                record_activity(request.user, "project", "created_repository_file", 2, {"repository_id": repository.pk})
                refresh_repository_languages(repository)
                refresh_rank(request.user)
                messages.success(request, "File committed to the repository.")
                return redirect(f'{reverse("landing:repository", args=[repository.pk])}?tab=code')
            if action == "create_branch":
                create_branch(repository, request.POST.get("name", "").strip(), request.POST.get("source") or repository.default_branch)
                messages.success(request, "Branch created successfully.")
                return redirect(f'{reverse("landing:repository", args=[repository.pk])}?tab=branches')
            if action == "settings":
                visibility = request.POST.get("visibility")
                default_branch = request.POST.get("default_branch")
                branch_names = {branch["name"] for branch in list_branches(repository)}
                if visibility in {"private", "public"}:
                    repository.visibility = visibility
                if default_branch in branch_names:
                    repository.default_branch = default_branch
                repository.save(update_fields=["visibility", "default_branch", "updated_at"])
                refresh_repository_languages(repository)
                messages.success(request, "Repository settings updated.")
                return redirect(f'{reverse("landing:repository", args=[repository.pk])}?tab=settings')
        except (ValueError, RuntimeError) as error:
            messages.error(request, str(error))
        except Exception:
            messages.error(request, "The Git operation could not be completed. Check the values and try again.")
    ref, path, files, readme, latest, commits, contributors = repository.default_branch, "", [], None, None, [], []
    if branches:
        try:
            ref = resolve_ref(repository, request.GET.get("ref"))
            path = clean_repo_path(request.GET.get("path"))
        except ValueError as error:
            messages.error(request, str(error))
            return redirect("landing:repository", repository_id=repository.pk)
    if branches and active_tab == "code":
        kind = object_type(repository, ref, path) if path else "tree"
        if kind == "blob":
            return redirect(f'{reverse("code:blob", args=[repository.pk])}?{urlencode({"ref": ref, "path": path})}')
        if kind != "tree":
            messages.error(request, "That folder does not exist on this branch.")
            return redirect(f'{reverse("landing:repository", args=[repository.pk])}?{urlencode({"ref": ref})}')
        files = list_tree(repository, ref, path)
        readme_entry = find_readme(files)
        if readme_entry:
            blob = read_blob(repository, ref, readme_entry["path"])
            if not blob["binary"] and not blob["truncated"]:
                readme = {"name": readme_entry["name"], "text": blob["data"].decode("utf-8", errors="replace"), "markdown": readme_entry["name"].lower().endswith((".md", ".markdown"))}
        latest = last_commit(repository, ref, path)
    if branches and active_tab == "commits":
        commits = list_commits(repository, ref)
    if branches and active_tab == "contributors":
        contributors = list_contributors(repository, ref)
    context.update({"active_tab": active_tab, "ref": ref, "path": path, "crumbs": breadcrumbs(path), "parent_path": "/".join(path.split("/")[:-1]) if path else None, "files": files, "readme": readme, "latest_commit": latest, "commits": commits, "contributors": contributors, "new_git_token": request.session.pop("new_git_token", None), "has_write_token": request.user.is_authenticated and request.user.git_tokens.filter(scope="write", revoked_at__isnull=True).exists(), "collaborators": repository.collaborators.select_related("user__profile") if active_tab == "settings" else [], "role_choices": RepositoryCollaborator.ROLE_CHOICES})
    return render(request, "landing/repository.html", context)
@login_required(login_url="landing:home")
@require_POST
def issue_git_token_view(request):
    scope = request.POST.get("scope") if request.POST.get("scope") in {"read", "write"} else "write"
    token, raw = GitAccessToken.issue(request.user, request.POST.get("name", "Local development")[:80], scope)
    request.session["new_git_token"] = raw
    messages.success(request, "MyProgress write key created. Copy it now; it will not be shown again.")
    repository = Repository.objects.filter(pk=request.POST.get("repository_id"), owner=request.user).first()
    if repository:
        return redirect("landing:repository", repository_id=repository.pk)
    return redirect("landing:workspace_section", section="projects")
@csrf_exempt
def git_http_view(request, owner_id, slug, service_path=""):
    repository = Repository.objects.filter(owner_id=owner_id, slug=slug).first()
    if not repository:
        return HttpResponse(status=404)
    write = "git-receive-pack" in service_path or request.GET.get("service") == "git-receive-pack"
    token = authenticate_git_request(request)
    git_user = token.user if token else None
    if write and (not token or token.scope != "write"):
        response = HttpResponse("MyProgress Credentials required: use your MyProgress account email and write key.", status=401)
        response["WWW-Authenticate"] = 'Basic realm="MyProgress Credentials"'
        response["X-MyProgress-Auth"] = "account-email-and-write-key"
        return response
    if not user_can_access(git_user, repository, write=write):
        response = HttpResponse("MyProgress repository access denied. Use your MyProgress account email and write key.", status=401 if not token else 403)
        response["WWW-Authenticate"] = 'Basic realm="MyProgress Credentials"'
        response["X-MyProgress-Auth"] = "account-email-and-write-key"
        return response
    request.user = git_user or request.user
    previous_heads = None
    if write and request.method == "POST":
        try:
            previous_heads = branch_heads(repository)
        except Exception:
            logger.exception("Could not snapshot branches before push to repository %s", repository.pk)
    try:
        status, headers, body = smart_http(repository, request, service_path)
    except Exception:
        return HttpResponse("Git service unavailable", status=500)
    if previous_heads is not None and status == 200:
        _record_push(repository, git_user, previous_heads)
    response = HttpResponse(body, status=status)
    for key in ["Content-Type", "Cache-Control", "Expires", "Pragma"]:
        if key in headers:
            response[key] = headers[key]
    return response
def _record_push(repository, user, previous_heads):
    try:
        commits = count_new_commits(repository, previous_heads)
        refresh_repository_languages(repository)
        if commits:
            record_activity(user, "project", "pushed_commits", min(commits, 5), {"repository_id": repository.pk, "commits": commits})
            complete_daily_step(user, "build")
            refresh_rank(user)
    except Exception:
        logger.exception("Could not record push activity for repository %s", repository.pk)
def public_profile_view(request, handle):
    profile = get_object_or_404(Profile.objects.select_related("user"), handle=handle)
    owner = profile.user
    profile = refresh_rank(owner)
    repositories = owner.repositories.all()
    public_repositories = repositories.filter(visibility="public").select_related("project")
    projects = list(owner.projects.filter(is_public=True).select_related("repository").prefetch_related("milestones"))
    explainers = dict(owner.learning_posts.filter(is_public=True, project__isnull=False).order_by("published_at").values_list("project_id", "pk"))
    for project in projects:
        project.explainer_id = explainers.get(project.pk)
    is_following = request.user.is_authenticated and Follow.objects.filter(follower=request.user, following=owner).exists()
    viewer_profile = Profile.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    if viewer_profile and request.user != owner:
        try:
            PortfolioView.objects.get_or_create(profile=profile, viewer=request.user, viewed_on=timezone.localdate(), defaults={"viewer_role": viewer_profile.role})
        except IntegrityError:
            pass
    can_recruit = bool(viewer_profile and viewer_profile.role in RECRUITER_ROLES and profile.role == "developer" and profile.recruiter_visible and request.user != owner)
    context = {"profile": profile, "owner": owner, "projects": projects, "public_repositories": public_repositories, "languages": language_breakdown(repositories.values_list("languages", flat=True)), "calendar": contribution_calendar(owner), "posts": owner.learning_posts.filter(is_public=True)[:6], "completed_count": sum(1 for project in projects if project.status == "complete" and project.has_verified_code), "follower_count": owner.follower_relationships.count(), "following_count": owner.following_relationships.count(), "is_owner": request.user == owner, "is_following": is_following, "can_recruit": can_recruit, "owner_initials": ((owner.first_name[:1] + owner.last_name[:1]) or owner.username[:2]).upper()}
    if can_recruit:
        context["viewer_shortlists"] = request.user.shortlists.all()
        context["is_shortlisted"] = ShortlistEntry.objects.filter(shortlist__owner=request.user, candidate=owner).exists()
        context["contact_status"] = ContactRequest.objects.filter(recruiter=request.user, developer=owner).order_by("-created_at").values_list("status", flat=True).first()
    return render(request, "landing/profile.html", context)
@login_required(login_url="landing:home")
@require_POST
def update_profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    form = ProfileForm(request.POST, instance=profile)
    if form.is_valid():
        form.save()
        refresh_rank(request.user)
        messages.success(request, "Portfolio updated.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("landing:workspace_section", section="portfolio")
@login_required(login_url="landing:home")
@require_POST
def follow_view(request, handle):
    profile = get_object_or_404(Profile.objects.select_related("user"), handle=handle)
    if profile.user != request.user:
        follow, created = Follow.objects.get_or_create(follower=request.user, following=profile.user)
        if created:
            follower_handle = Profile.objects.get_or_create(user=request.user)[0].handle
            notify(profile.user, request.user, "follow", f"{request.user.get_full_name() or follower_handle} started following you", reverse("landing:public_profile", args=[follower_handle]))
        else:
            follow.delete()
        refresh_rank(profile.user)
    return redirect("landing:public_profile", handle=profile.handle)
