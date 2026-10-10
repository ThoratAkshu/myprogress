from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
def redirect_back(request, fallback, *args, **kwargs):
    """Redirect to a same-site `next` URL from the form, or to the fallback."""
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect(fallback, *args, **kwargs)
