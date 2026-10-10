import logging
from django.contrib.auth.models import User
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse
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
