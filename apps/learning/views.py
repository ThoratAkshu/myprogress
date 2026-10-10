import logging
import subprocess
from apps.common.http import redirect_back
from apps.common.ratelimit import rate_limit
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.accounts.models import Profile
from apps.core.models import ContentView, LearningPost, PostComment, PostLike, Project
from apps.core.services import complete_daily_step, record_activity, refresh_rank
from apps.notifications.services import notify
from .forms import LearningPostForm
from .media import youtube_embed_url
from .studio import StudioError, draft_post, project_branches
logger = logging.getLogger(__name__)
def _display_name(user):
    return user.get_full_name() or getattr(getattr(user, "profile", None), "handle", None) or "A developer"
def _visible_post(request, post_id):
    post = get_object_or_404(LearningPost.objects.select_related("author__profile", "project__repository"), pk=post_id)
    if not post.is_public and post.author != request.user:
        raise Http404
    return post
def record_post_view(request, post):
    """Count one view per browser session per day; the author's own views never count."""
    if request.user.is_authenticated and request.user == post.author:
        return
    if not request.session.session_key:
        request.session.create()
    viewer = request.user if request.user.is_authenticated else None
    try:
        with transaction.atomic():
            _, created = ContentView.objects.get_or_create(post=post, session_key=request.session.session_key, viewed_on=timezone.localdate(), defaults={"viewer": viewer})
    except IntegrityError:
        created = False
    if created:
        LearningPost.objects.filter(pk=post.pk).update(views=F("views") + 1)
        if viewer:
            record_activity(viewer, "learning", "viewed_learning", 1, {"post_id": post.pk})
    if viewer:
        complete_daily_step(viewer, "learn")
def _delete_replaced_files(post, form, previous):
    for field in ["video_file", "thumbnail"]:
        old = previous.get(field)
        if field in form.changed_data and old and old != getattr(post, field).name:
            getattr(post, field).storage.delete(old)
def post_detail_view(request, post_id):
    post = _visible_post(request, post_id)
    post.author.profile, _ = Profile.objects.get_or_create(user=post.author)
    record_post_view(request, post)
    post.refresh_from_db(fields=["views"])
    context = {
        "post": post,
        "comments": post.comments.select_related("author__profile"),
        "like_count": post.likes.count(),
        "liked": request.user.is_authenticated and post.likes.filter(user=request.user).exists(),
        "is_author": request.user == post.author,
        "embed_url": youtube_embed_url(post.video_url),
        "more_posts": post.author.learning_posts.filter(is_public=True).exclude(pk=post.pk).annotate(like_count=Count("likes", distinct=True), comment_count=Count("comments", distinct=True))[:6],
        "is_following": request.user.is_authenticated and post.author.follower_relationships.filter(follower=request.user).exists(),
        "reading_minutes": max(1, round(len(post.body.split()) / 200)),
    }
    return render(request, "learning/post_detail.html", context)
@login_required(login_url="landing:home")
@rate_limit("publish", 10, 3600)
def post_create_view(request):
    initial = {"kind": request.GET.get("kind") if request.GET.get("kind") in {"article", "video"} else "article", "is_public": True}
    project_id = request.GET.get("project", "")
    if project_id.isdigit() and request.user.projects.filter(pk=project_id).exists():
        initial["project"] = int(project_id)
    form = LearningPostForm(request.POST or None, request.FILES or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        post.author = request.user
        post.save()
        record_activity(request.user, "learning", "published_learning", 4, {"post_id": post.pk})
        complete_daily_step(request.user, "share")
        refresh_rank(request.user)
        messages.success(request, "Published. Share the link so other developers can learn from it." if post.is_public else "Saved as a private draft.")
        return redirect("learning:detail", post_id=post.pk)
    return render(request, "learning/post_form.html", {"section": "learning", "form": form, "studio_projects": _studio_projects(request.user)})
def _studio_projects(user):
    """The author's projects as cards for the studio's project picker."""
    cards = []
    for project in user.projects.select_related("repository").order_by("-updated_at"):
        repository = getattr(project, "repository", None)
        languages = repository.languages if repository else {}
        cards.append({"pk": project.pk, "title": project.title, "language": next(iter(languages), ""), "has_code": bool(languages), "has_repository": repository is not None})
    return cards
def _owned_project(request, project_id):
    if not str(project_id).isdigit():
        raise Http404
    return get_object_or_404(Project.objects.select_related("repository"), pk=project_id, owner=request.user)
@login_required(login_url="landing:home")
def studio_branches_view(request):
    project = _owned_project(request, request.GET.get("project", ""))
    try:
        repository, branches = project_branches(project)
    except (subprocess.CalledProcessError, OSError, ValueError):
        logger.exception("Could not list branches for project %s", project.pk)
        return JsonResponse({"error": "Could not read this project's repository."}, status=500)
    return JsonResponse({"has_repository": repository is not None, "default": repository.default_branch if repository else "", "branches": [{"name": branch["name"], "updated": branch["updated"][:10], "subject": branch["subject"]} for branch in branches]})
@login_required(login_url="landing:home")
@require_POST
@rate_limit("studio-draft", 20, 3600)
def studio_draft_view(request):
    project = _owned_project(request, request.POST.get("project", ""))
    kind = "video" if request.POST.get("kind") == "video" else "article"
    try:
        draft, source, notice = draft_post(project, request.POST.get("branch", "").strip(), _display_name(request.user), kind)
    except StudioError as error:
        return JsonResponse({"error": str(error)}, status=400)
    except (subprocess.CalledProcessError, OSError, ValueError):
        logger.exception("Could not read branch for project %s", project.pk)
        return JsonResponse({"error": "Could not read that branch. Try again."}, status=500)
    return JsonResponse({**draft, "source": source, "notice": notice})
@login_required(login_url="landing:home")
def post_edit_view(request, post_id):
    post = get_object_or_404(LearningPost, pk=post_id, author=request.user)
    previous = {"video_file": post.video_file.name, "thumbnail": post.thumbnail.name}
    form = LearningPostForm(request.POST or None, request.FILES or None, user=request.user, instance=post)
    if request.method == "POST" and form.is_valid():
        post = form.save()
        _delete_replaced_files(post, form, previous)
        refresh_rank(request.user)
        messages.success(request, "Post updated.")
        return redirect("learning:detail", post_id=post.pk)
    return render(request, "learning/post_form.html", {"section": "learning", "form": form, "post": post, "studio_projects": _studio_projects(request.user)})
@login_required(login_url="landing:home")
@require_POST
def post_delete_view(request, post_id):
    post = get_object_or_404(LearningPost, pk=post_id, author=request.user)
    for field in [post.video_file, post.thumbnail]:
        if field:
            field.storage.delete(field.name)
    post.delete()
    refresh_rank(request.user)
    messages.success(request, "Post deleted.")
    return redirect(f'{reverse("landing:workspace_section", args=["learning"])}?tab=mine')
@login_required(login_url="landing:home")
@require_POST
@rate_limit("like", 120, 600)
def like_view(request, post_id):
    post = _visible_post(request, post_id)
    like, created = PostLike.objects.get_or_create(post=post, user=request.user)
    if created:
        notify(post.author, request.user, "like", f"{_display_name(request.user)} liked “{post.title}”", reverse("learning:detail", args=[post.pk]))
    else:
        like.delete()
    return redirect_back(request, f'{reverse("learning:detail", args=[post.pk])}#engagement')
@login_required(login_url="landing:home")
@require_POST
@rate_limit("post-comment", 20, 600)
def comment_view(request, post_id):
    post = _visible_post(request, post_id)
    body = request.POST.get("body", "").strip()
    if not body:
        messages.error(request, "Write a comment before posting.")
    else:
        Profile.objects.get_or_create(user=request.user)
        comment = PostComment.objects.create(post=post, author=request.user, body=body[:2000])
        notify(post.author, request.user, "comment", f"{_display_name(request.user)} commented on “{post.title}”", f'{reverse("learning:detail", args=[post.pk])}#comment-{comment.pk}')
    return redirect(f'{reverse("learning:detail", args=[post.pk])}#comments')
@login_required(login_url="landing:home")
@require_POST
def comment_delete_view(request, comment_id):
    comment = get_object_or_404(PostComment.objects.select_related("post"), pk=comment_id)
    if request.user not in {comment.author, comment.post.author}:
        raise Http404
    comment.delete()
    return redirect(f'{reverse("learning:detail", args=[comment.post_id])}#comments')
