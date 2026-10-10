from datetime import timedelta
from django.db.models import Count
from django.utils import timezone
from apps.accounts.models import Profile
from .git_service import user_can_access
from .models import ActivityEvent, LearningPost, PostLike, Project, Repository
from .services import visible_developers
FEED_ACTIONS = {"published_learning", "created_project", "created_repository", "pushed_commits", "merged_pull_request"}
def _events(user_ids, limit):
    events = ActivityEvent.objects.filter(action__in=FEED_ACTIONS).select_related("user__profile").order_by("-created_at")
    if user_ids is not None:
        events = events.filter(user_id__in=user_ids)
    return list(events[:limit])
def _hydrate(viewer, events, limit):
    """Turn activity events into feed items, dropping anything the viewer may not see."""
    wanted = {"post": set(), "project": set(), "repository": set()}
    for event in events:
        metadata = event.metadata or {}
        if event.action == "published_learning":
            wanted["post"].add(metadata.get("post_id"))
        elif event.action == "created_project":
            wanted["project"].add(metadata.get("project_id"))
        else:
            wanted["repository"].add(metadata.get("repository_id"))
    posts = {post.pk: post for post in LearningPost.objects.filter(pk__in=wanted["post"], is_public=True).select_related("project").annotate(like_count=Count("likes", distinct=True), comment_count=Count("comments", distinct=True))}
    projects = {project.pk: project for project in Project.objects.filter(pk__in=wanted["project"], is_public=True)}
    repositories = {repository.pk: repository for repository in Repository.objects.filter(pk__in=wanted["repository"]).select_related("project", "owner__profile") if user_can_access(viewer, repository)}
    liked = set(PostLike.objects.filter(user=viewer, post_id__in=posts).values_list("post_id", flat=True)) if viewer.is_authenticated else set()
    items, pushes = [], {}
    for event in events:
        metadata = event.metadata or {}
        item = {"key": f"{event.action}:{event.pk}", "action": event.action, "actor": event.user, "profile": getattr(event.user, "profile", None), "created_at": event.created_at, "suggested": False}
        if event.action == "published_learning":
            post = posts.get(metadata.get("post_id"))
            if not post:
                continue
            item.update(post=post, liked=post.pk in liked)
        elif event.action == "created_project":
            project = projects.get(metadata.get("project_id"))
            if not project:
                continue
            item["project"] = project
        else:
            repository = repositories.get(metadata.get("repository_id"))
            if not repository:
                continue
            item["repository"] = repository
            if event.action == "pushed_commits":
                day = (event.user_id, repository.pk, timezone.localdate(event.created_at))
                if day in pushes:
                    pushes[day]["commits"] += int(metadata.get("commits", 0))
                    continue
                item["commits"] = int(metadata.get("commits", 0))
                pushes[day] = item
            else:
                item["number"] = metadata.get("issue")
        items.append(item)
        if len(items) >= limit:
            break
    return items
def build_feed(viewer, limit=25):
    """Activity from people the viewer follows plus their own, newest first.

    When the network is too quiet, public activity from everyone fills in so a
    new member never lands on an empty home page.
    """
    following = list(viewer.following_relationships.values_list("following_id", flat=True))
    items = _hydrate(viewer, _events(following + [viewer.pk], limit * 4), limit)
    if len(items) < 3:
        seen = {item["key"] for item in items}
        items += [{**item, "suggested": True} for item in _hydrate(viewer, _events(None, limit * 4), limit) if item["key"] not in seen]
    return items[:limit]
def people_you_may_know(viewer, limit=5):
    """Developers the viewer doesn't follow yet, preferring shared languages and skills."""
    excluded = set(viewer.following_relationships.values_list("following_id", flat=True)) | {viewer.pk}
    my_languages = {language for languages in viewer.repositories.values_list("languages", flat=True) for language in (languages or {})}
    my_profile = Profile.objects.filter(user=viewer).first()
    my_skills = {skill.lower() for skill in my_profile.skill_list} if my_profile else set()
    candidates = list(visible_developers().exclude(user_id__in=excluded).order_by("-score")[:60])
    for candidate in candidates:
        languages = {language for repository in candidate.user.repositories.all() for language in (repository.languages or {})}
        candidate.shared = sorted(languages & my_languages) + [skill for skill in candidate.skill_list if skill.lower() in my_skills and skill not in languages]
    candidates.sort(key=lambda candidate: (-len(candidate.shared), -candidate.score))
    return candidates[:limit]
def trending_posts(limit=4, days=30):
    since = timezone.now() - timedelta(days=days)
    return LearningPost.objects.filter(is_public=True, published_at__gte=since).select_related("author__profile").annotate(like_count=Count("likes", distinct=True)).order_by("-like_count", "-views", "-published_at")[:limit]
