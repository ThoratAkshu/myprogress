from functools import lru_cache
from django.conf import settings
from apps.accounts.models import Profile
from apps.recruiting.models import RECRUITER_ROLES
THEMES = {"ocean", "emerald", "midnight"}
def ui_theme(request):
    """The color theme: ?theme= previews one for the rest of the session, otherwise UI_THEME."""
    requested = request.GET.get("theme") if hasattr(request, "GET") else None
    if requested in THEMES and hasattr(request, "session"):
        request.session["ui_theme"] = requested
    session_theme = request.session.get("ui_theme") if hasattr(request, "session") else None
    return {"ui_theme": session_theme if session_theme in THEMES else (settings.UI_THEME if settings.UI_THEME in THEMES else "midnight")}
def workspace_navigation(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    @lru_cache(maxsize=None)
    def nav_profile():
        return Profile.objects.get_or_create(user=user)[0]
    return {
        "nav_profile": nav_profile,
        "nav_is_recruiter": lambda: bool(nav_profile() and nav_profile().role in RECRUITER_ROLES),
        "nav_initials": ((user.first_name[:1] + user.last_name[:1]) or user.username[:2]).upper(),
        "nav_project_count": lambda: user.projects.count(),
        "nav_learning_count": lambda: user.learning_posts.count(),
        "nav_pending_requests": lambda: user.contact_requests.filter(status="pending").count(),
        "nav_shortlist_count": lambda: user.shortlists.count(),
        "nav_unread_notifications": lambda: user.notifications.filter(read_at__isnull=True).count(),
    }
