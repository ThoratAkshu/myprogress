"""Two-step sign-in: after the password, a 6-digit code from an authenticator app (TOTP, RFC 6238), or a one-time
recovery code if the phone is lost. The same codes Google Authenticator, Microsoft Authenticator and 1Password make."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode
from django.db import transaction
from django.utils import timezone
from .models import RecoveryCode, TwoFactor

ISSUER = "MyProgress"
STEP_SECONDS = 30
DIGITS = 6
RECOVERY_CODES = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i to misread


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_at(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def current_step():
    return int(time.time()) // STEP_SECONDS


def enabled(user):
    return user.is_authenticated and TwoFactor.objects.filter(user=user, enabled_at__isnull=False).exists()


def check_code(device, code):
    """Whether the code is right now (or one step either side, for phone clocks that drift). Each code works once."""
    code = "".join(character for character in str(code) if character.isdigit())
    if len(code) != DIGITS:
        return False
    now = current_step()
    for step in (now - 1, now, now + 1):
        if hmac.compare_digest(code_at(device.secret, step), code):
            # Only if no later code was used already: a code seen over someone's shoulder can't be replayed.
            return TwoFactor.objects.filter(pk=device.pk, last_step__lt=step).update(last_step=step) == 1
    return False


def setup_uri(user, secret):
    """What the QR code holds: authenticator apps read the account name, issuer and secret from it."""
    label = quote(f"{ISSUER}:{user.email or user.username}")
    return f"otpauth://totp/{label}?{urlencode({'secret': secret, 'issuer': ISSUER, 'digits': DIGITS, 'period': STEP_SECONDS})}"


def qr_svg(uri):
    """The QR code as inline SVG, or "" if segno isn't installed (the key can still be typed in)."""
    try:
        import segno
    except ImportError:
        return ""
    return segno.make(uri, error="m").svg_inline(scale=5, border=2, dark="#0f172a", light="#ffffff", omitsize=True)


def readable_secret(secret):
    return " ".join(secret[index:index + 4] for index in range(0, len(secret), 4))


def _digest(code):
    return hashlib.sha256("".join(character for character in code.lower() if character.isalnum()).encode()).hexdigest()


def new_recovery_codes(user):
    """Ten fresh one-time codes; the old ones stop working. Only their hashes are kept, so show these once."""
    codes = ["-".join("".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(5)) for _ in range(2)) for _ in range(RECOVERY_CODES)]
    with transaction.atomic():
        RecoveryCode.objects.filter(user=user).delete()
        RecoveryCode.objects.bulk_create([RecoveryCode(user=user, code_hash=_digest(code)) for code in codes])
    return codes


def use_recovery_code(user, code):
    return RecoveryCode.objects.filter(user=user, code_hash=_digest(code), used_at__isnull=True).update(used_at=timezone.now()) == 1


def recovery_codes_left(user):
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


def turn_on(device):
    device.enabled_at = timezone.now()
    device.save(update_fields=["enabled_at"])
    return new_recovery_codes(device.user)


def turn_off(user):
    with transaction.atomic():
        TwoFactor.objects.filter(user=user).delete()
        RecoveryCode.objects.filter(user=user).delete()
