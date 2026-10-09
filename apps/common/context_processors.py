from functools import lru_cache
from apps.accounts.models import Profile
from apps.recruiting.models import RECRUITER_ROLES
def workspace_navigation(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    @lru_cache(maxsize=None)
    def nav_profile():
        return Profile.objects.filter(user=user).first()
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
