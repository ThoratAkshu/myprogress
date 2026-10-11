from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from datetime import timedelta
import math
from collections import Counter
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils.text import slugify
from django.views.generic import TemplateView
from apps.accounts.emails import send_verification_email, user_from_verification_token
from apps.accounts.forms import EmailLoginForm, ProfileForm, RegistrationForm
from apps.accounts.models import Follow, Profile
from apps.common.http import redirect_back
from apps.core.feed import FEED_FILTERS, build_feed, people_you_may_know, trending_posts
from apps.core.network import NETWORK_ROLES, NETWORK_SORTS, NETWORK_VIEWS, decorate_people, find_people, follower_people, following_people, suggested_people
from apps.core.models import ContentView, DailyLoopCompletion, EarningTransaction, GitAccessToken, LearningPost, PostLike, Project, ProjectMilestone, Repository, RepositoryCollaborator
from apps.earnings.models import EarningSettings
from apps.organizations.services import student_summary
from apps.earnings.services import creator_dashboard, refresh_creator
from apps.core.services import achievements,coding_streak, complete_daily_step, contribution_calendar, earning_balance, language_breakdown, leaderboard, platform_languages, progress_facts, record_activity, record_rank_snapshots, refresh_rank, score_breakdown, weekly_movement
from apps.learning.views import record_post_view
from apps.notifications.services import notify
from apps.recruiting.models import RECRUITER_ROLES, ContactRequest, PortfolioView, ShortlistEntry
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from apps.common.templatetags.ui import avatar_tone, initials
from apps.common.ratelimit import client_ip, is_limited, rate_limit, record_hit, too_many_requests
from apps.core.git_service import GitRequestTooLarge, authenticate_git_request, branch_heads, clean_repo_path, commit_file, count_new_commits, create_branch, find_readme, initialize_repository, last_commit, list_branches, list_commits, list_contributors, list_tree, object_type, read_blob, refresh_repository_languages, resolve_ref, smart_http, user_can_access
from apps.code.access import RepositoryDenied, breadcrumbs, load_repository, repository_context
from urllib.parse import urlencode
import logging
import shutil
from django.conf import settings
from django.db import connection
logger = logging.getLogger(__name__)
GIT_AUTH_FAILURE_LIMIT, GIT_AUTH_FAILURE_WINDOW = 30, 300
LOGIN_FAILURES_PER_EMAIL, LOGIN_FAILURES_PER_IP, LOGIN_FAILURE_WINDOW = 10, 30, 900
# Live counts only appear once they're big enough to mean something; until then the page states plain facts.
LIVE_STATS_MINIMUM = 50
@method_decorator(never_cache, name="dispatch")
class LandingPageView(TemplateView):
    template_name = "landing/index.html"
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("landing:dashboard")
        return super().dispatch(request, *args, **kwargs)
    def get_context_data(self, **kwargs):
        """Everything on the home page is real: the earning rules as configured, and live developers and posts."""
        context = super().get_context_data(**kwargs)
        top = list(leaderboard(limit=5))
        for profile in top:
            languages = Counter()
            for repository in profile.user.repositories.all():
                languages.update(repository.languages or {})
            profile.top_language = languages.most_common(1)[0][0] if languages else ""
        developers = Profile.objects.filter(role="developer").count()
        rules = EarningSettings.current()
        coins_from = max(rules.coins_per_conversion - rules.coins_per_video, 0)
        context.update({
            "rules": rules,
            # Sample numbers for the earnings clip, worked out from the live rules so the clip always matches them.
            "tour": {"coins_from": coins_from, "ring_from": round(coins_from * 100 / max(rules.coins_per_conversion, 1)), "followers_from": max(rules.follower_goal - 3, 0), "balance_from": 260, "balance_to": 260 + rules.rupees_per_conversion},
            "top_developers": top,
            "latest_posts": list(LearningPost.objects.filter(is_public=True).select_related("author__profile").order_by("-published_at")[:3]),
            "live_stats": {"developers": developers, "repositories": Repository.objects.exclude(languages={}).count(), "posts": LearningPost.objects.filter(is_public=True).count()} if developers >= LIVE_STATS_MINIMUM else None,
        })
        return context
@never_cache
@rate_limit("register", 10, 3600, per="ip")
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
        send_verification_email(request, user)
        messages.success(request, f"Welcome! We sent a confirmation link to {user.email}.")
        next_url = request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)  # back to an organization invite, for example
        return redirect("landing:dashboard")
    if request.method == "POST":
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return render(request, "landing/register.html", {"form": form, "next": request.POST.get("next") or request.GET.get("next", "")})
def login_view(request):
    if request.method != "POST":
        return redirect("landing:home")
    email = request.POST.get("email", "").strip().lower()[:254]
    failure_keys = [(f"login-fail:ip:{client_ip(request)}", LOGIN_FAILURES_PER_IP)] + ([(f"login-fail:email:{email}", LOGIN_FAILURES_PER_EMAIL)] if email else [])
    if any(is_limited(key, limit, LOGIN_FAILURE_WINDOW) for key, limit in failure_keys):
        messages.error(request, "Too many failed sign-in attempts. Wait 15 minutes or reset your password.")
        return redirect("landing:home")
    form = EmailLoginForm(request, request.POST)
    if not form.is_valid():
        for key, _ in failure_keys:
            record_hit(key, LOGIN_FAILURE_WINDOW)
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
    role = Profile.objects.filter(user=request.user).values_list("role", flat=True).first()
    if role == "organization":
        return redirect("organizations:home")
    if role in RECRUITER_ROLES:
        return redirect("recruiting:search")
    context = _workspace_context(request)
    show = request.GET.get("show") if request.GET.get("show") in FEED_FILTERS else ""
    context.update({"classes": student_summary(request.user), "feed": build_feed(request.user, show=show), "feed_show": show, "suggestions": people_you_may_know(request.user), "trending": trending_posts(), "portfolio_views": PortfolioView.objects.filter(profile=context["profile"], viewed_on__gte=timezone.localdate() - timedelta(days=30)).count()})
    return render(request, "landing/dashboard.html", context)

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
RANKING_SCOPES = {"global": "Global", "following": "Following", "nearby": "Near you", "rising": "Rising this week"}
def _rankings_context(request, profile):
    """The leaderboard (global, people you follow, your city, or this week's climbers) and, for developers, their standing."""
    is_recruiter = profile.role in RECRUITER_ROLES
    scope = request.GET.get("scope") if request.GET.get("scope") in RANKING_SCOPES else "global"
    language = request.GET.get("language", "").strip()[:40]
    city = (profile.location or "").split(",")[0].strip()
    record_rank_snapshots()
    repositories = Repository.objects.only("id", "owner_id", "languages")
    people = Profile.objects.filter(role="developer", score__gt=0).filter(Q(recruiter_visible=True) | Q(user=request.user)).select_related("user").prefetch_related(Prefetch("user__repositories", queryset=repositories))
    if language:
        people = people.filter(user__in=Repository.objects.filter(languages__has_key=language).values("owner"))
    if scope == "following":
        people = people.filter(user_id__in=[*request.user.following_relationships.values_list("following_id", flat=True), request.user.pk])
    elif scope == "nearby":
        people = people.filter(location__icontains=city) if city else people.none()
    ordered = people.order_by("-score", "user__date_joined")
    if scope == "rising":
        candidates = list(ordered[:500])
        movement = weekly_movement([entry.user_id for entry in candidates])
        board = sorted((entry for entry in candidates if movement.get(entry.user_id, {}).get("rank", 0) > 0), key=lambda entry: (-movement[entry.user_id]["rank"], -entry.score))[:25]
    else:
        board = list(ordered[:50])
        movement = weekly_movement([entry.user_id for entry in board])
    previous_score, position = None, 0
    for index, entry in enumerate(board, start=1):
        if scope == "rising" or entry.score != previous_score:
            position = index
        previous_score, entry.position = entry.score, position
        totals = Counter()
        for repository in entry.user.repositories.all():
            totals.update(repository.languages or {})
        entry.top_language = totals.most_common(1)[0][0] if totals else ""
        change = movement.get(entry.user_id, {})
        entry.climb, entry.drop, entry.gained = max(change.get("rank", 0), 0), max(-change.get("rank", 0), 0), change.get("score", 0)
        entry.is_me = entry.user_id == request.user.pk
    context = {"ranking_scope": scope, "ranking_scopes": RANKING_SCOPES, "ranking_city": city, "leaderboard_language": language, "languages": platform_languages(), "is_recruiter": is_recruiter,
               "podium": board[:3] if scope != "rising" and len(board) >= 3 else [], "leaderboard": board[3:] if scope != "rising" and len(board) >= 3 else board}
    if is_recruiter:
        return context
    if profile.score and scope != "rising" and not any(entry.is_me for entry in board) and people.filter(user=request.user).exists():
        profile.position = ordered.filter(score__gt=profile.score).count() + 1
        context["my_row"] = profile
    facts = progress_facts(request.user)
    components = score_breakdown(request.user, facts)
    for component in components:
        component["available"] = component["max"] - component["points"]
    ranked = Profile.objects.filter(role="developer", score__gt=0).count()
    target = Profile.objects.filter(role="developer", score__gt=profile.score).select_related("user").order_by("score", "rank").first()
    mine = weekly_movement([request.user.pk]).get(request.user.pk, {})
    badges = achievements(facts, profile)
    circumference = 2 * math.pi * 52
    context.update({
        "score_components": components, "best_move": max(components, key=lambda component: component["available"]), "badges": badges, "badges_earned": sum(badge["earned"] for badge in badges),
        "ranked_total": ranked, "top_percent": max(1, math.ceil(profile.rank * 100 / ranked)) if profile.score and profile.rank and ranked else None,
        "rank_change": mine.get("rank", 0), "score_change": mine.get("score", 0), "streak": coding_streak(request.user),
        "target": target, "target_gap": target.score - profile.score + 1 if target else 0, "target_percent": round(profile.score * 100 / (target.score + 1)) if target else 100,
        "ring_circumference": round(circumference, 2), "ring_offset": round(circumference * (1 - min(profile.score, 100) / 100), 2),
    })
    return context
def network_url(view="discover"):
    """Where the Network tab lives: under Learn."""
    return f'{reverse("landing:workspace_section", args=["learning"])}?tab=network' + (f"&view={view}" if view != "discover" else "")
def _network_context(request, pending):
    """Learn's Network tab: search anyone, people you may know, who you follow, followers, and recruiter requests."""
    view = request.GET.get("view") if request.GET.get("view") in NETWORK_VIEWS else "discover"
    filters = {"query": request.GET.get("q", "").strip()[:100], "language": request.GET.get("language", "").strip()[:40], "location": request.GET.get("location", "").strip()[:60], "role": request.GET.get("role") if request.GET.get("role") in NETWORK_ROLES else "", "sort": request.GET.get("sort") if request.GET.get("sort") in NETWORK_SORTS else "relevant"}
    searching = any(filters[key] for key in ("query", "language", "location", "role"))
    people, suggestions = None, []
    if view == "discover" and searching:
        people = find_people(request.user, **filters)
    elif view == "following":
        people = following_people(request.user)
    elif view == "followers":
        people = follower_people(request.user)
    elif view == "discover":
        suggestions = decorate_people(request.user, suggested_people(request.user, limit=9))
    page = Paginator(people, 12).get_page(request.GET.get("page")) if people is not None else None
    if page:
        decorate_people(request.user, page.object_list)
    params = {key: value for key, value in {"q": filters["query"], "language": filters["language"], "location": filters["location"], "role": filters["role"], "sort": filters["sort"] if filters["sort"] != "relevant" else ""}.items() if value}
    return {
        "network_view": view, "network_views": NETWORK_VIEWS, "network_filters": filters, "network_searching": searching, "network_page": page, "network_suggestions": suggestions,
        "network_roles": NETWORK_ROLES, "network_sorts": NETWORK_SORTS, "network_languages": platform_languages(), "network_querystring": urlencode({"tab": "network", "view": view, **params}),
        "network_counts": {"following": request.user.following_relationships.count(), "followers": request.user.follower_relationships.count(), "requests": pending},
        "contact_requests": request.user.contact_requests.select_related("recruiter__profile")[:20] if view == "requests" else [],
    }
@login_required(login_url="landing:home")
@never_cache
def workspace_section_view(request, section):
    allowed = {"portfolio", "projects", "learning", "earnings", "rankings", "network"}
    if section not in allowed:
        return redirect("landing:dashboard")
    if section == "network":
        return redirect(network_url("requests" if request.user.contact_requests.filter(status="pending").exists() else "discover"))
    context = _workspace_context(request, section)
    if section == "projects":
        projects = list(request.user.projects.select_related("repository").prefetch_related("milestones"))
        skill_counts = Counter(skill for project in projects for skill in project.skill_list)
        context["projects"] = projects
        context["project_status_counts"] = Counter(project.status for project in projects)
        context["project_skills"] = sorted(skill_counts.items(), key=lambda item: (-item[1], item[0].lower()))
        context["repositories"] = request.user.repositories.select_related("project")
        context["shared_repositories"] = request.user.repository_memberships.select_related("repository__owner__profile")
        for project in projects:
            project.milestones_done = sum(milestone.is_complete for milestone in project.milestones.all())
        context["new_git_token"] = request.session.pop("new_git_token", None)
    if section == "rankings":
        context.update(_rankings_context(request, context["profile"]))
    if section == "earnings":
        context.update(creator_dashboard(request.user))
    if section == "learning":
        pending = request.user.contact_requests.filter(status="pending").count()
        tabs = [("for-you", "For you"), ("following", "Following"), ("mine", f"My content {context['learning_count']}"), ("network", f"Network {pending}" if pending else "Network")]
        tab = request.GET.get("tab") if request.GET.get("tab") in dict(tabs) else "for-you"
        context.update({"learning_tabs": tabs, "learning_tab": tab})
        if tab == "network":
            context.update(_network_context(request, pending))
        else:
            posts = LearningPost.objects.select_related("author__profile", "project").annotate(like_count=Count("likes", distinct=True), comment_count=Count("comments", distinct=True))
            if tab == "mine":
                posts = posts.filter(author=request.user)
            elif tab == "following":
                posts = posts.filter(is_public=True, author__in=request.user.following_relationships.values("following"))
            else:
                posts = posts.filter(is_public=True)
            creators = list(User.objects.filter(pk__in=request.user.following_relationships.values("following"), learning_posts__is_public=True).annotate(latest_post=Max("learning_posts__published_at")).select_related("profile").order_by("-latest_post")[:12])
            for creator in creators:
                creator.posted_recently = creator.latest_post >= timezone.now() - timedelta(days=7)
            page = Paginator(posts.order_by("-published_at"), 10).get_page(request.GET.get("page"))
            context.update({"learning_creators": creators, "learning_page": page, "liked_ids": set(PostLike.objects.filter(user=request.user, post_id__in=[post.pk for post in page]).values_list("post_id", flat=True))})
    if section == "portfolio":
        views = PortfolioView.objects.filter(profile=context["profile"], viewed_on__gte=timezone.localdate() - timedelta(days=30))
        context["portfolio_views"] = views.count()
        context["recruiter_views"] = views.filter(viewer_role__in=RECRUITER_ROLES).count()
    return render(request, "landing/workspace_section.html", context)
@login_required(login_url="landing:home")
@require_POST
@rate_limit("create-project", 30, 3600)
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
            return redirect_back(request, "landing:workspace_section", section="projects")
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
    return redirect_back(request, "landing:workspace_section", section="projects")
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
@rate_limit("create-repository", 20, 3600)
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
@rate_limit("git-token", 10, 3600)
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
    failure_key = f"git-auth-fail:{client_ip(request)}"
    if is_limited(failure_key, GIT_AUTH_FAILURE_LIMIT, GIT_AUTH_FAILURE_WINDOW):
        return too_many_requests(GIT_AUTH_FAILURE_WINDOW, "Too many failed Git sign-ins from this address. Wait a few minutes and try again.")
    token = authenticate_git_request(request)
    if token is None and request.headers.get("Authorization"):
        record_hit(failure_key, GIT_AUTH_FAILURE_WINDOW)
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
    on_success = (lambda: _record_push(repository, git_user, previous_heads)) if previous_heads is not None else None
    try:
        status, headers, body = smart_http(repository, request, service_path, on_success=on_success, stream=request.method == "POST")
    except GitRequestTooLarge:
        return HttpResponse("This push is larger than the server allows. Split it into smaller pushes.", status=413, content_type="text/plain")
    except Exception:
        logger.exception("Git service failed for repository %s", repository.pk)
        return HttpResponse("Git service unavailable", status=500)
    response = StreamingHttpResponse(body, status=status) if request.method == "POST" else HttpResponse(body, status=status)
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
    public_repositories = list(repositories.filter(visibility="public").select_related("project").order_by("-updated_at"))
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
    context = {"profile": profile, "owner": owner, "projects": projects, "public_repositories": public_repositories, "languages": language_breakdown(repositories.values_list("languages", flat=True)), "calendar": contribution_calendar(owner), "posts": owner.learning_posts.filter(is_public=True).select_related("author__profile", "project").annotate(like_count=Count("likes", distinct=True), comment_count=Count("comments", distinct=True)), "tab": request.GET.get("tab") if request.GET.get("tab") in {"repositories", "projects", "posts"} else "overview", "completed_count": sum(1 for project in projects if project.status == "complete" and project.has_verified_code), "follower_count": owner.follower_relationships.count(), "following_count": owner.following_relationships.count(), "is_owner": request.user == owner, "is_following": is_following, "can_recruit": can_recruit, "owner_initials": ((owner.first_name[:1] + owner.last_name[:1]) or owner.username[:2]).upper()}
    if context["tab"] == "posts" and request.user.is_authenticated:
        context["liked_ids"] = set(PostLike.objects.filter(user=request.user, post__author=owner).values_list("post_id", flat=True))
    if can_recruit:
        context["viewer_shortlists"] = request.user.shortlists.all()
        context["is_shortlisted"] = ShortlistEntry.objects.filter(shortlist__owner=request.user, candidate=owner).exists()
        context["contact_status"] = ContactRequest.objects.filter(recruiter=request.user, developer=owner).order_by("-created_at").values_list("status", flat=True).first()
    # The owner always sees their email; everyone else only when the owner shares it or accepted their contact request.
    context["email_visible"] = bool(owner.email) and (request.user == owner or profile.show_email or context.get("contact_status") == "accepted")
    return render(request, "landing/profile.html", context)
@login_required(login_url="landing:home")
@require_POST
@rate_limit("profile", 30, 600)
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
@rate_limit("follow", 60, 600)
def follow_view(request, handle):
    profile = get_object_or_404(Profile.objects.select_related("user"), handle=handle)
    if profile.user != request.user:
        follow, created = Follow.objects.get_or_create(follower=request.user, following=profile.user)
        if created:
            follower_handle = Profile.objects.get_or_create(user=request.user)[0].handle
            notify(profile.user, request.user, "follow", f"{request.user.get_full_name() or follower_handle} started following you", reverse("landing:public_profile", args=[follower_handle]))
            refresh_creator(profile.user)
        else:
            follow.delete()
        refresh_rank(profile.user)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        following = Follow.objects.filter(follower=request.user, following=profile.user).exists()
        return JsonResponse({"following": following, "followers": profile.user.follower_relationships.count()})
    return redirect_back(request, "landing:public_profile", handle=profile.handle)
def verify_email_view(request, token):
    user = user_from_verification_token(token)
    if not user:
        messages.error(request, "That confirmation link is invalid or has expired. Request a new one from your dashboard.")
        return redirect("landing:dashboard" if request.user.is_authenticated else "landing:home")
    profile, _ = Profile.objects.get_or_create(user=user)
    if not profile.email_verified_at:
        profile.email_verified_at = timezone.now()
        profile.save(update_fields=["email_verified_at"])
    messages.success(request, "Email confirmed." + (" You're now a verified recruiter." if profile.is_verified_recruiter else ""))
    return redirect("landing:dashboard" if request.user.is_authenticated else "landing:home")
@login_required(login_url="landing:home")
@require_POST
@rate_limit("verify-email", 3, 3600)
def resend_verification_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if profile.email_verified_at:
        messages.success(request, "Your email is already confirmed.")
    elif send_verification_email(request, request.user):
        messages.success(request, f"We sent a new confirmation link to {request.user.email}.")
    else:
        messages.error(request, "We couldn't send the email right now. Try again later.")
    return redirect(request.META.get("HTTP_REFERER") if url_has_allowed_host_and_scheme(request.META.get("HTTP_REFERER", ""), allowed_hosts={request.get_host()}, require_https=request.is_secure()) else "landing:dashboard")
@login_required(login_url="landing:home")
@require_POST
def dismiss_verification_banner_view(request):
    """Hide the confirm-your-email banner until the next sign-in."""
    request.session["verify_banner_hidden"] = True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return HttpResponse(status=204)
    return redirect(request.META.get("HTTP_REFERER") if url_has_allowed_host_and_scheme(request.META.get("HTTP_REFERER", ""), allowed_hosts={request.get_host()}, require_https=request.is_secure()) else "landing:dashboard")
def health_view(request):
    """Liveness/readiness probe for load balancers: database and git must both work."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    checks["git"] = "ok" if shutil.which(settings.GIT_EXECUTABLE) else "error"
    healthy = all(value == "ok" for value in checks.values())
    return JsonResponse({"status": "ok" if healthy else "error", **checks}, status=200 if healthy else 503)
SEARCH_TYPES = {"people": "People", "repositories": "Repositories", "posts": "Posts"}
def _search(query):
    """People, public repositories, and public posts matching every word of the query."""
    people, repositories, posts = Profile.objects.none(), Repository.objects.none(), LearningPost.objects.none()
    if query:
        people = Profile.objects.select_related("user")
        repositories = Repository.objects.filter(visibility="public").select_related("owner__profile", "project")
        posts = LearningPost.objects.filter(is_public=True).select_related("author__profile", "project")
        for term in query.split()[:5]:
            people = people.filter(Q(user__first_name__icontains=term) | Q(user__last_name__icontains=term) | Q(handle__icontains=term) | Q(headline__icontains=term) | Q(skills__icontains=term) | Q(location__icontains=term))
            repositories = repositories.filter(Q(slug__icontains=term) | Q(project__title__icontains=term) | Q(project__summary__icontains=term) | Q(owner__profile__handle__icontains=term))
            posts = posts.filter(Q(title__icontains=term) | Q(summary__icontains=term) | Q(body__icontains=term))
        people, repositories, posts = people.order_by("-score", "handle"), repositories.order_by("-updated_at"), posts.order_by("-published_at")
    return people, repositories, posts
@rate_limit("search-suggest", 120, 60, per="ip", methods=("GET",))
def search_suggest_view(request):
    """Instant results for the header search box, as you type."""
    query = request.GET.get("q", "").strip()[:100]
    people, repositories, posts = _search(query if len(query) >= 2 else "")
    return JsonResponse({
        "people": [{"name": profile.user.get_full_name() or profile.handle, "detail": profile.headline or profile.location or f"@{profile.handle}", "url": reverse("landing:public_profile", args=[profile.handle]), "initials": initials(profile.user), "tone": avatar_tone(profile.user)} for profile in people[:4]],
        "repositories": [{"name": f"{repository.owner.profile.handle}/{repository.slug}", "detail": (repository.project.summary or "")[:90], "url": reverse("landing:repository", args=[repository.pk]), "language": next(iter(repository.languages or {}), "")} for repository in repositories[:3]],
        "posts": [{"name": post.title, "detail": f"{post.get_kind_display()} by {post.author.get_full_name() or post.author.profile.handle}", "url": reverse("learning:detail", args=[post.pk]), "kind": post.kind} for post in posts[:3]],
    })
def search_view(request):
    query = request.GET.get("q", "").strip()[:100]
    kind = request.GET.get("type") if request.GET.get("type") in SEARCH_TYPES else "all"
    people, repositories, posts = _search(query)
    limit = 20 if kind != "all" else 5
    following = set(request.user.following_relationships.values_list("following_id", flat=True)) if request.user.is_authenticated else set()
    context = {"section": "search", "search_query": query, "kind": kind, "types": SEARCH_TYPES, "counts": {"people": people.count(), "repositories": repositories.count(), "posts": posts.count()}, "people": people[:limit] if kind in {"all", "people"} else [], "repositories": repositories[:limit] if kind in {"all", "repositories"} else [], "posts": posts[:limit] if kind in {"all", "posts"} else [], "following": following}
    return render(request, "landing/search.html", context)
def project_detail_view(request, project_id):
    project = get_object_or_404(Project.objects.select_related("owner", "repository").prefetch_related("milestones"), pk=project_id)
    is_owner = request.user == project.owner
    if not project.is_public and not is_owner:
        raise Http404
    repository = getattr(project, "repository", None)
    visible_repository = repository if repository and user_can_access(request.user, repository) else None
    posts = project.learning_posts.all() if is_owner else project.learning_posts.filter(is_public=True)
    milestones = list(project.milestones.all())
    context = {
        "section": "projects" if is_owner else "",
        "project": project,
        "owner_profile": Profile.objects.get_or_create(user=project.owner)[0],
        "is_owner": is_owner,
        "repository": visible_repository,
        "repository_hidden": bool(repository and not visible_repository),
        "languages": language_breakdown([visible_repository.languages]) if visible_repository else [],
        "posts": posts.annotate(like_count=Count("likes", distinct=True), comment_count=Count("comments", distinct=True)),
        "milestones": milestones,
        "milestones_done": sum(milestone.is_complete for milestone in milestones),
    }
    return render(request, "landing/project_detail.html", context)
