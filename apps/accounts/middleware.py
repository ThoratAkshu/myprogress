"""Enforce apps.accounts.access on every request, before the view runs."""
import logging
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.cache import patch_cache_control
from .access import EXEMPT_NAMESPACES, PUBLIC, ROLE_LABELS, allowed_roles, user_role

logger = logging.getLogger(__name__)


def _wants_json(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")


def _who(roles):
    labels = [ROLE_LABELS[role] for role in ("developer", "recruiter", "organization") if role in roles]
    return f"{' and '.join(labels)} accounts" if labels else "nobody"


class RoleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Pages made for one signed-in person must never be kept by a shared cache or proxy.
        if getattr(request, "user", None) is not None and request.user.is_authenticated and not response.has_header("Cache-Control"):
            patch_cache_control(response, private=True)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match is None or match.url_name is None or set(match.namespaces) & EXEMPT_NAMESPACES:
            return None  # static and media files, and the admin site's own staff check
        roles = allowed_roles(match.view_name, view_kwargs)
        if roles == PUBLIC:
            return None
        if roles is None:
            logger.warning("Refused %s: the URL %s has no entry in apps.accounts.access.POLICY", request.path, match.view_name)
            return HttpResponseForbidden("This page isn't available.")
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("landing:home"))
        if user_role(request.user) in roles:
            return None
        text = f"That page is only for {_who(roles)}."
        if _wants_json(request):
            return JsonResponse({"error": text}, status=403)
        if request.method not in {"GET", "HEAD"}:
            return HttpResponseForbidden(text)
        messages.error(request, text)
        return redirect("landing:dashboard")
