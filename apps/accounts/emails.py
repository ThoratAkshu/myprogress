import logging
from django.contrib.auth.models import User
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.crypto import constant_time_compare, salted_hmac
logger = logging.getLogger(__name__)
VERIFICATION_SALT = "myprogress.email-verification"
VERIFICATION_MAX_AGE = 60 * 60 * 24 * 3
def verification_token(user):
    return signing.dumps({"user": user.pk, "email": user.email.lower()}, salt=VERIFICATION_SALT)
def user_from_verification_token(token):
    """Return the user a valid, unexpired token was issued for, or None. Tokens die if the email changes."""
    try:
        data = signing.loads(token, salt=VERIFICATION_SALT, max_age=VERIFICATION_MAX_AGE)
    except signing.BadSignature:
        return None
    user = User.objects.filter(pk=data.get("user"), is_active=True).first()
    return user if user and user.email.lower() == data.get("email") else None
def send_verification_email(request, user):
    link = request.build_absolute_uri(reverse("landing:verify_email", args=[verification_token(user)]))
    body = f"Hi {user.first_name or 'there'},\n\nConfirm your email address for MyProgress:\n\n{link}\n\nThe link works for 3 days. Recruiters: verifying a company email marks you as a verified recruiter and raises your daily contact limit.\n\nIf you didn't create an account, ignore this email."
    try:
        send_mail("Confirm your MyProgress email", body, None, [user.email])
        return True
    except Exception:
        logger.exception("Could not send verification email to user %s", user.pk)
        return False
# Changing the sign-in email: the new address only replaces the old one when its owner opens the link we send to it,
# so a typo can't lock anyone out. The old address then gets a link to undo the change for a week. Each link dies
# once the account's email is something else.
EMAIL_CHANGE_SALT, EMAIL_UNDO_SALT = "myprogress.email-change", "myprogress.email-change-undo"
EMAIL_UNDO_MAX_AGE = 60 * 60 * 24 * 7
def _password_check(user):
    # A change link also dies when the password changes (an undo clears it), so an old link can't redo the change.
    # The undo link doesn't: whoever changed the email could otherwise cancel it by changing the password too.
    return salted_hmac(EMAIL_CHANGE_SALT, user.password).hexdigest()[:20]
def email_change_token(user, new_email, salt=EMAIL_CHANGE_SALT):
    data = {"user": user.pk, "from": user.email.lower(), "to": new_email.lower()}
    if salt == EMAIL_CHANGE_SALT:
        data["check"] = _password_check(user)
    return signing.dumps(data, salt=salt)
def email_change_from_token(token, salt=EMAIL_CHANGE_SALT):
    """(user, the email to change to) for a valid, unexpired link that still applies, or (None, "")."""
    try:
        data = signing.loads(token, salt=salt, max_age=EMAIL_UNDO_MAX_AGE if salt == EMAIL_UNDO_SALT else VERIFICATION_MAX_AGE)
    except signing.BadSignature:
        return None, ""
    user = User.objects.filter(pk=data.get("user"), is_active=True).first()
    if not user or user.email.lower() != data.get("from") or salt == EMAIL_CHANGE_SALT and not constant_time_compare(data.get("check", ""), _password_check(user)):
        return None, ""
    return user, data.get("to", "")
def _send(subject, body, address, user):
    try:
        send_mail(subject, body, None, [address])
        return True
    except Exception:
        logger.exception("Could not send %r to user %s", subject, user.pk)
        return False
def send_email_change_link(request, user, new_email):
    link = request.build_absolute_uri(reverse("landing:confirm_email_change", args=[email_change_token(user, new_email)]))
    return _send("Confirm your new MyProgress email", f"Hi {user.first_name or 'there'},\n\nYou asked to sign in to MyProgress with this email instead of {user.email}. Open this link to make the change:\n\n{link}\n\nThe link works for 3 days. Until you open it, your account keeps using {user.email}.\n\nIf you didn't ask for this, ignore this email.", new_email, user)
def send_email_changed_notice(request, user, old_email):
    """To the old address: the email changed, with a link to undo it if that wasn't them."""
    link = request.build_absolute_uri(reverse("landing:undo_email_change", args=[email_change_token(user, old_email, salt=EMAIL_UNDO_SALT)]))
    return _send("Your MyProgress email was changed", f"Hi {user.first_name or 'there'},\n\nYour MyProgress account now signs in with {user.email} instead of this address.\n\nIf this was you, there's nothing to do. If it wasn't, someone knows your password. Open this link within 7 days to put this address back and sign everyone out:\n\n{link}", old_email, user)
def send_password_changed_notice(request, user):
    link = request.build_absolute_uri(reverse("landing:password_reset"))
    return _send("Your MyProgress password was changed", f"Hi {user.first_name or 'there'},\n\nThe password for your MyProgress account was just changed, and other devices were signed out.\n\nIf this was you, there's nothing to do. If it wasn't, reset your password now:\n\n{link}", user.email, user)
