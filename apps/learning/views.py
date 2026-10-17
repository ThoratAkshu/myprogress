import logging
import re
import subprocess
import uuid
from pathlib import PurePosixPath
from django.conf import settings
from apps.common.http import redirect_back
from apps.common.ratelimit import rate_limit
from apps.common.views import stored_file_response
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, F
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.accounts.access import user_role
from apps.accounts.models import Profile
from apps.core.git_service import clean_repo_path, object_type, read_blob
from apps.core.models import ArticleImage, ContentView, LearningPost, PostComment, PostLike, Project
from apps.core.services import complete_daily_step, record_activity, refresh_rank
from apps.earnings.services import reverse_post_coins, sync_post_coins
from apps.notifications.services import notify
from apps.organizations.services import announce_lesson, membership, staff_organizations
from .assist import ACTIONS as ASSIST_ACTIONS, AssistUnavailable, assist
from .formatting import article_outline, render_article
from .forms import ArticleImageForm, LearningPostForm
from .media import place_post_files, youtube_embed_url
from .studio import StudioError, branch_paths, draft_post, lecture_plan, project_branches
from .timeline import parse_captions, parse_chapters
MAX_INSERT_BYTES = 300_000
logger = logging.getLogger(__name__)
def _display_name(user):
    return user.get_full_name() or getattr(getattr(user, "profile", None), "handle", None) or "A developer"
def _visible_post(request, post_id):
    post = get_object_or_404(LearningPost.objects.select_related("author__profile", "project__repository"), pk=post_id)
    if not post.is_public and post.author != request.user:
        member = membership(post.organization, request.user) if post.organization_id else None
        if member is None or (not member.is_staff and post.publish_at and post.publish_at > timezone.now()):
            raise Http404  # outsiders, and students before a scheduled lecture's release
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
        "chapters": parse_chapters(post.chapters),
        "transcript": parse_captions(post.captions),
        "outline": article_outline(post.body) if not post.has_video else [],
    }
    return render(request, "learning/post_detail.html", context)
@login_required(login_url="landing:home")
@rate_limit("publish", 10, 3600)
def post_create_view(request):
    lecturer = user_role(request.user) == "organization"
    initial = {"kind": request.GET.get("kind") if request.GET.get("kind") in {"article", "video"} else "video" if lecturer else "article", "is_public": True}
    organizations = staff_organizations(request.user)
    # An institute's lectures go to its own students unless it chooses otherwise.
    organization = organizations.filter(slug=request.GET.get("org", "")).first() or (organizations.first() if lecturer else None)
    if organization:
        initial.update(organization=organization.pk, is_public=False)
    project_id = request.GET.get("project", "")
    if project_id.isdigit() and request.user.projects.filter(pk=project_id).exists():
        initial["project"] = int(project_id)
    form = LearningPostForm(request.POST or None, request.FILES or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        post.author = request.user
        post.save()
        place_post_files(post)
        record_activity(request.user, "learning", "published_learning", 4, {"post_id": post.pk})
        complete_daily_step(request.user, "share")
        refresh_rank(request.user)
        coins = sync_post_coins(post)
        earned = f" You earned {coins} coins." if coins else ""
        if post.organization_id and post.publish_at:
            when = timezone.localtime(post.publish_at)
            messages.success(request, f"Scheduled for {post.organization.name} on {when:%a} {when:%b} {when.day}, {when.strftime('%I:%M %p').lstrip('0')}. Students can't see it until then.")
        elif post.organization_id:
            announce_lesson(post, request.user)
            messages.success(request, f"Shared with {post.organization.name}. Only its members can see it.")
        else:
            messages.success(request, f"Published. Share the link so other developers can learn from it.{earned}" if post.is_public else "Saved as a private draft.")
        return _published(request, post)
    return render(request, "learning/post_form.html", _form_context(request, form))
def _published(request, post):
    """Studio uploads run in the background and get the post's address as JSON, so the success message waits for that page."""
    url = reverse("learning:detail", args=[post.pk])
    return JsonResponse({"redirect": url}) if request.headers.get("X-Requested-With") == "XMLHttpRequest" else redirect(url)
# Choices for the recorder's layout templates; colors match recorder-scene.js.
RECORDER_CORNERS = [("top-left", "Top left"), ("top-right", "Top right"), ("bottom-left", "Bottom left"), ("bottom-right", "Bottom right")]
RECORDER_BACKGROUNDS = [("midnight", "Midnight", ("#0f172a", "#1e3a8a")), ("ocean", "Ocean", ("#1d4ed8", "#0ea5e9")), ("sunset", "Sunset", ("#f97316", "#db2777")), ("forest", "Forest", ("#065f46", "#0d9488")), ("graphite", "Graphite", ("#111827", "#374151"))]
# Drawing tools in the studio; paper styles are drawn by recorder-ink.js.
INK_COLORS = [("#ef4444", "Red"), ("#facc15", "Yellow"), ("#22c55e", "Green"), ("#38bdf8", "Blue"), ("#ffffff", "White"), ("#0f172a", "Black")]
BOARD_PAPERS = [("grid", "Grid paper"), ("lined", "Lined paper"), ("dots", "Dotted paper"), ("plain", "Plain white"), ("chalk", "Chalkboard")]
NOTE_PLACES = [("top-right", "Top right"), ("top-left", "Top left"), ("top-center", "Top center"), ("center", "Center"), ("bottom-left", "Bottom left"), ("bottom-center", "Bottom center"), ("bottom-right", "Bottom right")]
def studio_options():
    """The choices the studio dialog offers; the post form and the live-class teaching board both use it."""
    return {"recorder_corners": RECORDER_CORNERS, "recorder_backgrounds": RECORDER_BACKGROUNDS, "ink_colors": INK_COLORS, "board_papers": BOARD_PAPERS, "note_places": NOTE_PLACES}
def _form_context(request, form, post=None):
    lecturer = user_role(request.user) == "organization"
    return {"section": "organization" if lecturer else "learning", "is_lecturer": lecturer, "form": form, "post": post, "studio_projects": [] if lecturer else _studio_projects(request.user), **studio_options(), "ai_enabled": bool(settings.ANTHROPIC_API_KEY)}
def media_view(request, post_id, which):
    """An organization post's video or thumbnail, only for people who can see the post."""
    post = _visible_post(request, post_id)
    field = {"video": post.video_file, "thumbnail": post.thumbnail}.get(which)
    if not field:
        raise Http404
    return stored_file_response(request, field)
def captions_view(request, post_id):
    """The post's captions as a WebVTT file for the video player."""
    post = _visible_post(request, post_id)
    if not post.captions:
        raise Http404
    return HttpResponse(post.captions, content_type="text/vtt; charset=utf-8")
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
    recording = {"transcript": request.POST.get("transcript", "").strip()[:20000], "chapters": request.POST.get("chapters", "").strip()[:3000]}
    lecture = lecture_plan(request.POST.get("topic"), request.POST.get("points"), request.POST.get("audience"))
    if lecture:
        project = None
    elif request.POST.get("project", ""):
        project = _owned_project(request, request.POST.get("project", ""))
    elif recording["transcript"]:
        project = None
    elif user_role(request.user) == "organization":
        return JsonResponse({"error": "Write what the lecture is about first, or record with live captions on so the studio can draft from what you said."}, status=400)
    else:
        return JsonResponse({"error": "Pick a project, or record with live captions on so the studio can draft from what you said."}, status=400)
    kind = "video" if request.POST.get("kind") == "video" else "article"
    try:
        draft, source, notice = draft_post(project, request.POST.get("branch", "").strip() if project else "", _display_name(request.user), kind, recording, lecture=lecture)
    except StudioError as error:
        return JsonResponse({"error": str(error)}, status=400)
    except (subprocess.CalledProcessError, OSError, ValueError):
        logger.exception("Could not read branch for project %s", getattr(project, "pk", None))
        return JsonResponse({"error": "Could not read that branch. Try again."}, status=500)
    return JsonResponse({**draft, "source": source, "notice": notice})
@login_required(login_url="landing:home")
@require_POST
@rate_limit("studio-preview", 300, 600)
def studio_preview_view(request):
    """The article rendered exactly as it will be published."""
    return JsonResponse({"html": render_article(request.POST.get("body", "")[:100_000])})
@login_required(login_url="landing:home")
@require_POST
@rate_limit("article-image", 60, 3600)
def studio_image_view(request):
    form = ArticleImageForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = form.errors.get("image") or ["Upload a PNG, JPEG, GIF, or WebP image."]
        return JsonResponse({"error": errors[0]}, status=400)
    upload = form.cleaned_data["image"]
    upload.name = f"{uuid.uuid4().hex}.{upload.image.format.lower().replace('jpeg', 'jpg')}"
    image = ArticleImage.objects.create(owner=request.user, image=upload)
    alt = " ".join(re.sub(r"[\[\]]", " ", request.POST.get("alt", "")).split())[:100] or "Screenshot"
    return JsonResponse({"url": image.image.url, "markdown": f"![{alt}]({image.image.url})"})
def _studio_branch(request):
    """The author's project repository and the requested branch, or a JSON error response."""
    project = _owned_project(request, request.GET.get("project", ""))
    try:
        repository, branches = project_branches(project)
    except (subprocess.CalledProcessError, OSError, ValueError):
        logger.exception("Could not list branches for project %s", project.pk)
        return None, None, JsonResponse({"error": "Could not read this project's repository."}, status=500)
    branch = request.GET.get("branch", "")
    if not repository or branch not in {item["name"] for item in branches}:
        return None, None, JsonResponse({"error": "Pick a project and a branch at the top of the page first."}, status=400)
    return repository, branch, None
@login_required(login_url="landing:home")
def studio_files_view(request):
    repository, branch, error = _studio_branch(request)
    return error or JsonResponse({"paths": branch_paths(repository, branch)[:5000]})
@login_required(login_url="landing:home")
def studio_file_view(request):
    repository, branch, error = _studio_branch(request)
    if error:
        return error
    try:
        path = clean_repo_path(request.GET.get("path", ""))
    except ValueError:
        return JsonResponse({"error": "That isn't a valid file path."}, status=400)
    if not path or object_type(repository, branch, path) != "blob":
        return JsonResponse({"error": "That file isn't on this branch."}, status=404)
    blob = read_blob(repository, branch, path, limit=MAX_INSERT_BYTES)
    if blob["truncated"]:
        return JsonResponse({"error": "That file is too large to insert (over 300 KB)."}, status=400)
    if blob["binary"]:
        return JsonResponse({"error": "That file isn't text, so it can't be inserted as code."}, status=400)
    return JsonResponse({"path": path, "language": PurePosixPath(path).suffix.lstrip(".").lower()[:20], "content": blob["data"].decode("utf-8", errors="replace")})
@login_required(login_url="landing:home")
@require_POST
@rate_limit("studio-assist", 40, 3600)
def studio_assist_view(request):
    action, text = request.POST.get("action", ""), request.POST.get("text", "").strip()
    if action not in ASSIST_ACTIONS or not text:
        return JsonResponse({"error": "Select some text for the AI to work on."}, status=400)
    try:
        result = assist(action, text, request.POST.get("title", ""))
    except AssistUnavailable:
        return JsonResponse({"error": "AI writing help is off on this server. Add an ANTHROPIC_API_KEY to its .env to turn it on."}, status=503)
    except Exception:
        logger.exception("AI writing help failed")
        result = ""
    if not result:
        return JsonResponse({"error": "AI writing help isn't available right now. Try again in a minute."}, status=502)
    return JsonResponse({"text": result})
@login_required(login_url="landing:home")
def post_edit_view(request, post_id):
    post = get_object_or_404(LearningPost, pk=post_id, author=request.user)
    previous = {"video_file": post.video_file.name, "thumbnail": post.thumbnail.name}
    shared_before = post.organization_id
    form = LearningPostForm(request.POST or None, request.FILES or None, user=request.user, instance=post)
    if request.method == "POST" and form.is_valid():
        post = form.save()
        place_post_files(post)
        if post.organization_id != shared_before:
            type(post).objects.filter(pk=post.pk).update(announced_at=None)
            post.announced_at = None
        if post.organization_id and post.announced_at is None and not (post.publish_at and post.publish_at > timezone.now()):
            announce_lesson(post, request.user)
        _delete_replaced_files(post, form, previous)
        refresh_rank(request.user)
        coins = sync_post_coins(post)
        messages.success(request, f"Post updated. You earned {coins} coins." if coins else "Post updated.")
        return _published(request, post)
    return render(request, "learning/post_form.html", _form_context(request, form, post))
@login_required(login_url="landing:home")
@require_POST
def post_delete_view(request, post_id):
    post = get_object_or_404(LearningPost, pk=post_id, author=request.user)
    for field in [post.video_file, post.thumbnail]:
        if field:
            field.storage.delete(field.name)
    reverse_post_coins(post)
    organization = post.organization
    post.delete()
    refresh_rank(request.user)
    messages.success(request, "Post deleted.")
    if organization:
        return redirect("organizations:channel", slug=organization.slug)
    if user_role(request.user) != "developer":
        return redirect("landing:dashboard")
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
