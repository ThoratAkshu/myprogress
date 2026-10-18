from django.shortcuts import redirect
from .services import WARMUP

# Pages that stay open while the sign-in question waits: the question itself, and signing out.
OPEN = {"practice:warmup", "landing:logout"}


class WarmupMiddleware:
    """With developer mode on, signing in asks one coding question. Until it's answered (right or wrong), every
    page leads to it. Background requests, static files and the admin carry on as usual."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not getattr(request, "user", None) or not request.user.is_authenticated or WARMUP not in request.session:
            return None
        match = request.resolver_match
        if match is None or match.url_name is None or match.view_name in OPEN or "admin" in match.namespaces:
            return None
        if request.headers.get("Sec-Fetch-Dest") == "empty" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return None  # fetches from a page already open
        return redirect("practice:warmup")
