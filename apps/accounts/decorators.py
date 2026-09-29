from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
def role_required(*allowed_roles):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            profile = getattr(request.user, "profile", None)
            if profile and profile.role in allowed_roles:
                return view(request, *args, **kwargs)
            messages.error(request, "You do not have permission to access that page.")
            return redirect("landing:dashboard")
        return wrapped
    return decorator
