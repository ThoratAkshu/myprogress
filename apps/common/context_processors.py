from functools import lru_cache
from django.conf import settings
from apps.accounts.models import Profile
from apps.organizations.services import staff_organizations
from apps.practice import services as practice
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
    def dev_mode():
        return practice.is_on(user)
    @lru_cache(maxsize=None)
    def ide():
        return practice.ide_on(user)
    @lru_cache(maxsize=None)
    def view_switched():  # "on" or "off" on the first page after the developer view was switched, then gone
        return request.session.pop(practice.SWITCHED, None) if hasattr(request, "session") else None
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
        "nav_is_organization": lambda: bool(nav_profile() and nav_profile().role == "organization"),
        "nav_org": lambda: staff_organizations(user).first(),
        "nav_has_organizations": lambda: user.org_memberships.filter(status="active").exists(),
        "nav_can_finance": lambda: user.is_superuser or (user.is_staff and user.has_perm("earnings.access_finance")),
        "nav_dev_mode": dev_mode,
        "nav_ide": ide,
        "nav_view_switched": view_switched,
        "nav_ide_status": lambda: practice.status_bar(user),
        "nav_ide_commands": lambda: practice.palette(user),
    }
