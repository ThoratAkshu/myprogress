"""Account security: two-step sign-in, set up in Security settings and asked for after the password."""
import time
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from apps.common.ratelimit import is_limited, rate_limit, record_hit
from apps.core.services import record_activity
from . import two_factor
from .models import TwoFactor

PENDING = "two_step_pending"
PENDING_SECONDS = 5 * 60
WRONG_CODES, WRONG_CODES_WINDOW = 5, 15 * 60


def begin_two_step(request, user, remember, next_url):
    """The password was right; remember who's signing in until they give the code. They aren't signed in yet."""
    request.session[PENDING] = {"user": user.pk, "remember": remember, "next": next_url, "at": int(time.time())}


def finish_sign_in(request, user, remember, next_url):
    login(request, user)
    record_activity(user, "login", "signed_in", 1)
    request.session.set_expiry(60 * 60 * 24 * 30 if remember else 0)
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect("landing:dashboard")


@never_cache
def two_step_view(request):
    """The second step of signing in: a code from the authenticator app, or a recovery code."""
    pending = request.session.get(PENDING)
    user = User.objects.filter(pk=pending["user"], is_active=True).first() if pending else None
    device = TwoFactor.objects.filter(user=user, enabled_at__isnull=False).first() if user else None
    if device is None or time.time() - pending["at"] > PENDING_SECONDS:
        request.session.pop(PENDING, None)
        if pending:
            messages.error(request, "That took too long. Sign in again.")
        return redirect(f'{reverse("landing:home")}#signin')
    recovery = request.GET.get("method") == "recovery" or request.POST.get("method") == "recovery"
    if request.method == "POST":
        key = f"two-step-wrong:{user.pk}"
        if is_limited(key, WRONG_CODES, WRONG_CODES_WINDOW):
            request.session.pop(PENDING, None)
            messages.error(request, "Too many wrong codes. Wait 15 minutes, then sign in again.")
            return redirect(f'{reverse("landing:home")}#signin')
        code = request.POST.get("code", "")
        if two_factor.use_recovery_code(user, code) if recovery else two_factor.check_code(device, code):
            request.session.pop(PENDING, None)
            response = finish_sign_in(request, user, pending["remember"], pending["next"])
            if recovery:
                left = two_factor.recovery_codes_left(user)
                messages.warning(request, f"You signed in with a recovery code; {left} left. If you lost your phone, set up two-step sign-in again in Security settings.")
            return response
        record_hit(key, WRONG_CODES_WINDOW)
        messages.error(request, "That recovery code doesn't work. Each one works once." if recovery else "That code isn't right. Enter the newest 6-digit code from your authenticator app.")
    return render(request, "landing/two_step.html", {"recovery": recovery})


def _requiring_companies(user):
    from apps.companies.models import Company
    return Company.objects.filter(require_two_factor=True, members__user=user)


@login_required(login_url="landing:home")
@never_cache
@rate_limit("security", 30, 600)
def security_view(request):
    """Turn two-step sign-in on (scan a QR code, confirm a code, keep the recovery codes) or off."""
    device = TwoFactor.objects.filter(user=request.user).first()
    context = {"section": "security", "requiring": _requiring_companies(request.user)}
    if request.method == "POST":
        action = request.POST.get("action")
        enabled = bool(device and device.enabled_at)
        if action == "start" and not enabled:
            device, _ = TwoFactor.objects.update_or_create(user=request.user, defaults={"secret": two_factor.new_secret(), "enabled_at": None, "last_step": 0})
            return redirect("landing:security")
        if action == "cancel" and device and not enabled:
            device.delete()
            return redirect("landing:security")
        if action == "confirm" and device and not enabled:
            if two_factor.check_code(device, request.POST.get("code", "")):
                context["new_codes"] = two_factor.turn_on(device)
                messages.success(request, "Two-step sign-in is on. Next time you sign in, we'll ask for a code from your app.")
            else:
                messages.error(request, "That code isn't right. Check that your phone sets its time automatically, then enter the newest code.")
        elif action in {"codes", "disable"} and enabled:
            if not request.user.check_password(request.POST.get("password", "")):
                messages.error(request, "Your password isn't right.")
            elif action == "codes":
                context["new_codes"] = two_factor.new_recovery_codes(request.user)
                messages.success(request, "New recovery codes made. The old ones no longer work.")
            elif two_factor.check_code(device, request.POST.get("code", "")) or two_factor.use_recovery_code(request.user, request.POST.get("code", "")):
                two_factor.turn_off(request.user)
                names = ", ".join(company.name for company in context["requiring"])
                messages.success(request, "Two-step sign-in is off." + (f" {names} require{'s' if len(context['requiring']) == 1 else ''} it, so you can't reach their repositories until you turn it on again." if names else ""))
                return redirect("landing:security")
            else:
                messages.error(request, "That code isn't right. Enter a code from your app, or one of your recovery codes.")
        device = TwoFactor.objects.filter(user=request.user).first()
    context["device"] = device
    if device and not device.enabled_at:
        uri = two_factor.setup_uri(request.user, device.secret)
        context.update(setup_qr=two_factor.qr_svg(uri), setup_key=two_factor.readable_secret(device.secret), setup_uri=uri)
    elif device:
        context["codes_left"] = two_factor.recovery_codes_left(request.user)
    return render(request, "landing/security.html", context)
