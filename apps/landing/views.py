from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import redirect, render
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
from apps.accounts.forms import EmailLoginForm, RegistrationForm
from apps.accounts.models import Profile
from apps.core.models import ContentView, DailyLoopCompletion, EarningTransaction, GitAccessToken, LearningPost, Project, ProjectMilestone, Repository
from apps.core.services import complete_daily_step, earning_balance, record_activity, refresh_rank
from apps.core.git_service import authenticate_git_request, commit_file, create_branch, initialize_repository, list_branches, list_commits, list_contributors, list_files, smart_http, user_can_access
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
    return render(request, "landing/dashboard.html", _workspace_context(request))

@login_required(login_url="landing:home")
def account_identity_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return JsonResponse({"name": request.user.get_full_name() or request.user.username, "account": request.user.email or request.user.username, "role": profile.get_role_display(), "initials": ((request.user.first_name[:1] + request.user.last_name[:1]) or request.user.username[:2]).upper()})
def _workspace_context(request, section="overview"):
    profile = refresh_rank(request.user)
    projects = request.user.projects.all()
    posts = LearningPost.objects.filter(is_public=True).select_related("author")[:3]
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
        context["new_git_token"] = request.session.pop("new_git_token", None)
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
    messages.success(request, "Project created. You can now add its proof of work.")
    return redirect("landing:dashboard")
@login_required(login_url="landing:home")
def learning_view(request, post_id):
    post = LearningPost.objects.filter(pk=post_id, is_public=True).first()
    if not post:
        return redirect("landing:workspace_section", section="learning")
    if not request.session.session_key:
        request.session.create()
    view, created = ContentView.objects.get_or_create(post=post, session_key=request.session.session_key, viewed_on=timezone.localdate(), defaults={"viewer": request.user})
    if created:
        record_activity(request.user, "learning", "viewed_learning", 1, {"post_id": post.pk})
    complete_daily_step(request.user, "learn")
    return redirect(post.video_url or reverse("landing:workspace_section", kwargs={"section": "learning"}))
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
    repository = Repository.objects.create(project=project, owner=request.user, slug=slug, visibility=request.POST.get("visibility", "private"))
    try:
        initialize_repository(repository)
    except Exception:
        repository.delete()
        messages.error(request, "Repository storage could not be initialized.")
        return redirect("landing:workspace_section", section="projects")
    record_activity(request.user, "project", "created_repository", 5, {"repository_id": repository.pk})
    messages.success(request, "Repository created. Create a token before your first push.")
    return redirect("landing:repository", repository_id=repository.pk)
@login_required(login_url="landing:home")
def repository_view(request, repository_id):
    repository = Repository.objects.select_related("project", "owner").filter(pk=repository_id).first()
    if not repository or not user_can_access(request.user, repository):
        messages.error(request, "You do not have access to that repository.")
        return redirect("landing:workspace_section", section="projects")
    allowed_tabs = {"code", "branches", "commits", "contributors", "settings"}
    active_tab = request.GET.get("tab", "code")
    active_tab = active_tab if active_tab in allowed_tabs else "code"
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_file":
                commit_file(repository, request.POST.get("path", ""), request.POST.get("content", ""), request.user, request.POST.get("message", ""))
                record_activity(request.user, "project", "created_repository_file", 2, {"repository_id": repository.pk})
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
                messages.success(request, "Repository settings updated.")
                return redirect(f'{reverse("landing:repository", args=[repository.pk])}?tab=settings')
        except (ValueError, RuntimeError) as error:
            messages.error(request, str(error))
        except Exception:
            messages.error(request, "The Git operation could not be completed. Check the values and try again.")
    branches = list_branches(repository)
    clone_url = request.build_absolute_uri(reverse("landing:git_root", kwargs={"owner_id": repository.owner_id, "slug": repository.slug}))
    files = list_files(repository) if branches and active_tab == "code" else []
    commits = list_commits(repository) if branches and active_tab in {"commits", "contributors"} else []
    contributors = list_contributors(repository) if branches and active_tab == "contributors" else []
    context = {"repository": repository, "branches": branches, "files": files, "commits": commits, "contributors": contributors, "active_tab": active_tab, "clone_url": clone_url, "new_git_token": request.session.pop("new_git_token", None), "has_write_token": request.user.git_tokens.filter(scope="write", revoked_at__isnull=True).exists(), "initials": ((request.user.first_name[:1] + request.user.last_name[:1]) or request.user.username[:2]).upper()}
    return render(request, "landing/repository.html", context)
@login_required(login_url="landing:home")
@require_POST
def issue_git_token_view(request):
    token, raw = GitAccessToken.issue(request.user, request.POST.get("name", "Local development")[:80], request.POST.get("scope", "write"))
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
    try:
        status, headers, body = smart_http(repository, request, service_path)
    except Exception:
        return HttpResponse("Git service unavailable", status=500)
    response = HttpResponse(body, status=status)
    for key in ["Content-Type", "Cache-Control", "Expires", "Pragma"]:
        if key in headers:
            response[key] = headers[key]
    return response
