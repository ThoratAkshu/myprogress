"""Account security, in Security settings: changing the email or password, and two-step sign-in (set up there and
asked for after the password)."""
import time
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from apps.common.ratelimit import is_limited, rate_limit, record_hit
from apps.core.audit import record, security_log
from apps.core.services import record_activity
from . import identity, two_factor
from .emails import EMAIL_UNDO_SALT, email_change_from_token, send_email_change_link, send_email_changed_notice, send_password_changed_notice
from .forms import EmailChangeForm, PasswordChangeForm
from .models import Profile, TwoFactor

PENDING = "two_step_pending"
PENDING_SECONDS = 5 * 60
WRONG_CODES, WRONG_CODES_WINDOW = 5, 15 * 60


def begin_two_step(request, user, remember, next_url):
    """The password was right; remember who's signing in until they give the code. They aren't signed in yet."""
    request.session[PENDING] = {"user": user.pk, "remember": remember, "next": next_url, "at": int(time.time())}


def finish_sign_in(request, user, remember, next_url, how=""):
    login(request, user)
    record(request, "account.sign_in", f"signed in{how}", user=user)
    record_activity(user, "login", "signed_in", 1)
    request.session.set_expiry(60 * 60 * 24 * 30 if remember else 0)
    if not (next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure())):
        next_url = reverse("landing:dashboard")
    from apps.practice.services import open_in_developer_mode, start_warmup
    if open_in_developer_mode(request, user):  # just turned on from the home page: what's new first, questions from next time
        return redirect(next_url)
    if start_warmup(request, user, next_url):  # developer mode: one question before going on
        return redirect("practice:warmup")
    return redirect(next_url)


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
            response = finish_sign_in(request, user, pending["remember"], pending["next"], " with a recovery code" if recovery else " with two-step sign-in")
            if recovery:
                left = two_factor.recovery_codes_left(user)
                messages.warning(request, f"You signed in with a recovery code; {left} left. If you lost your phone, set up two-step sign-in again in Security settings.")
            return response
        record_hit(key, WRONG_CODES_WINDOW)
        record(request, "account.wrong_code", "entered a wrong recovery code" if recovery else "entered a wrong two-step code", actor=user, user=user)
        messages.error(request, "That recovery code doesn't work. Each one works once." if recovery else "That code isn't right. Enter the newest 6-digit code from your authenticator app.")
    return render(request, "landing/two_step.html", {"recovery": recovery})


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Choosing a new password from the emailed link, noted in the account's security log."""
    def form_valid(self, form):
        response = super().form_valid(form)
        record(self.request, "account.password", "reset the password from an emailed link", actor=form.user, user=form.user)
        return response


def _requiring_companies(user):
    from apps.companies.models import Company
    return Company.objects.filter(require_two_factor=True, members__user=user)


@login_required(login_url="landing:home")
@never_cache
@rate_limit("security", 30, 600)
def security_view(request):
    """How you sign in: change your email (it takes effect from a link sent to the new address) or password, and turn
    two-step sign-in on (scan a QR code, confirm a code, keep the recovery codes) or off."""
    device = TwoFactor.objects.filter(user=request.user).first()
    action =request.POST.get("action") if request.method == "POST" else ""
    email_form = EmailChangeForm(request.user, request.POST if action == "email" else None)
    password_form = PasswordChangeForm(request.user, request.POST if action == "password" else None)
    context = {"section": "security", "requiring": _requiring_companies(request.user), "email_form": email_form, "password_form": password_form}
    if action == "email" and email_form.is_valid():
        new_email = email_form.cleaned_data["email"]
        if send_email_change_link(request, request.user, new_email):
            record(request, "account.email_requested", f"asked to change the sign-in email to {new_email}", user=request.user)
            messages.success(request, f"We sent a link to {new_email}. Open it to finish; until then you sign in with {request.user.email}.")
            return redirect(f'{reverse("landing:security")}#email')
        messages.error(request, "We couldn't send the email right now. Try again later.")
    elif action == "password" and password_form.is_valid():
        password_form.save()
        update_session_auth_hash(request, password_form.user)  # this device stays signed in; the others are signed out
        record(request, "account.password", "changed the password", user=request.user)
        send_password_changed_notice(request, request.user)
        messages.success(request, "Password changed. Other devices were signed out.")
        return redirect(f'{reverse("landing:security")}#password')
    elif request.method == "POST" and action not in {"email", "password"}:
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
                record(request, "account.two_step", "turned on two-step sign-in", user=request.user)
                messages.success(request, "Two-step sign-in is on. Next time you sign in, we'll ask for a code from your app.")
            else:
                messages.error(request, "That code isn't right. Check that your phone sets its time automatically, then enter the newest code.")
        elif action in {"codes", "disable"} and enabled:
            if not request.user.check_password(request.POST.get("password", "")):
                messages.error(request, "Your password isn't right.")
            elif action == "codes":
                context["new_codes"] = two_factor.new_recovery_codes(request.user)
                record(request, "account.recovery_codes", "made new recovery codes", user=request.user)
                messages.success(request, "New recovery codes made. The old ones no longer work.")
            elif two_factor.check_code(device, request.POST.get("code", "")) or two_factor.use_recovery_code(request.user, request.POST.get("code", "")):
                two_factor.turn_off(request.user)
                record(request, "account.two_step", "turned off two-step sign-in", user=request.user)
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
    context["events"] = security_log(request.user)
    return render(request, "landing/security.html", context)


@never_cache
def confirm_email_change_view(request, token):
    """The link sent to a new email: opening it makes that the sign-in email (and proves it's theirs)."""
    user, new_email = email_change_from_token(token)
    back = "landing:security" if request.user.is_authenticated else "landing:home"
    problem = "" if user else "That link no longer works. It may have expired, or the email was already changed. Ask for a new one in Security."
    if user and User.objects.filter(Q(username__iexact=new_email) | Q(email__iexact=new_email)).exclude(pk=user.pk).exists():
        problem = f"{new_email} is now used by another account, so the change can't be made."
    if user and not problem:
        profile, _ = Profile.objects.get_or_create(user=user)
        problem = identity.email_problem(new_email, profile.role)
    if problem:
        messages.error(request, problem)
        return redirect(back)
    old_email = user.email
    try:
        with transaction.atomic():
            user.email = user.username = new_email
            user.save(update_fields=["email", "username"])
            profile.email_verified_at = timezone.now()
            changed = ["email_verified_at"]
            website = profile.company_website
            if profile.role == "recruiter" and website and not identity.same_company(identity.domain_of(new_email), identity.host_of(website)):
                profile.company_website = ""  # it has to be on the email's domain
                changed.append("company_website")
            profile.save(update_fields=changed)
    except IntegrityError:
        messages.error(request, f"{new_email} is now used by another account, so the change can't be made.")
        return redirect(back)
    record(request, "account.email", f"changed the sign-in email from {old_email} to {new_email}", actor=user, user=user)
    send_email_changed_notice(request, user, old_email)
    messages.success(request, f"Done. You now sign in with {new_email}." + (" Your company website was on another domain, so it was removed; add the new one in Edit profile." if "company_website" in changed else ""))
    return redirect(back)


@never_cache
@rate_limit("email-undo", 10, 3600, per="ip")
def undo_email_change_view(request, token):
    """The link sent to the old email after a change. It asks first (mail scanners open links), then puts the old
    email back and clears the password, which signs every device out, so the owner can choose a new one."""
    user, old_email = email_change_from_token(token, salt=EMAIL_UNDO_SALT)
    if not user:
        messages.error(request, "That link no longer works. It may have expired, or the email was changed again.")
        return redirect("landing:home")
    if request.method == "POST":
        if User.objects.filter(Q(username__iexact=old_email) | Q(email__iexact=old_email)).exclude(pk=user.pk).exists():
            messages.error(request, f"{old_email} is now used by another account, so it can't be put back.")
            return redirect("landing:home")
        changed_to = user.email
        user.email = user.username = old_email
        user.set_unusable_password()
        user.save(update_fields=["email", "username", "password"])
        Profile.objects.filter(user=user).update(email_verified_at=timezone.now())
        record(request, "account.email", f"put the sign-in email back to {old_email} from {changed_to}, and signed everyone out", actor=user, user=user)
        if request.user == user:
            logout(request)
        messages.success(request, f"Your account signs in with {old_email} again, and everyone was signed out. Enter {old_email} below to choose a new password.")
        return redirect("landing:password_reset")
    return render(request, "landing/undo_email_change.html", {"changed_to": user.email, "old_email": old_email})
