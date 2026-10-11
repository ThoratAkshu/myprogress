"""Payout providers: send creator payments to UPI or a bank account. RazorpayX is supported; without keys payments are sent by hand."""
import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from decimal import Decimal
from django.conf import settings
class ProviderError(Exception):
    """The provider refused or couldn't be reached; the message is safe to show finance staff."""
class RazorpayX:
    name = "RazorpayX"
    base_url = "https://api.razorpay.com/v1"
    # Payout states that mean the money will not arrive.
    FAILED = {"rejected", "cancelled", "reversed", "failed"}
    def __init__(self, key_id, key_secret, account_number, timeout=20):
        self.auth = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        self.account_number = account_number
        self.timeout = timeout
    def _request(self, method, path, body=None, idempotency_key=None):
        request = urllib.request.Request(f"{self.base_url}{path}", method=method, data=json.dumps(body).encode() if body is not None else None)
        request.add_header("Authorization", f"Basic {self.auth}")
        request.add_header("Content-Type", "application/json")
        if idempotency_key:
            request.add_header("X-Payout-Idempotency", idempotency_key)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read()).get("error", {}).get("description", "")
            except (ValueError, AttributeError):
                detail = ""
            raise ProviderError(detail or f"RazorpayX answered {error.code}.") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ProviderError("Couldn't reach RazorpayX. Try again in a few minutes.") from error
    def ensure_fund_account(self, account):
        """Create the creator's contact and fund account once, and again whenever their payment details change."""
        changed = []
        if not account.provider_contact_id:
            contact = self._request("POST", "/contacts", {"name": account.payout_name[:50], "email": account.user.email, "type": "vendor", "reference_id": f"user-{account.user_id}"})
            account.provider_contact_id = contact["id"]
            changed.append("provider_contact_id")
        if not account.provider_fund_account_id:
            if account.payout_method == "bank":
                body = {"contact_id": account.provider_contact_id, "account_type": "bank_account", "bank_account": {"name": account.payout_name[:120], "ifsc": account.ifsc, "account_number": account.bank_account}}
            else:
                body = {"contact_id": account.provider_contact_id, "account_type": "vpa", "vpa": {"address": account.upi_id}}
            account.provider_fund_account_id = self._request("POST", "/fund_accounts", body)["id"]
            changed.append("provider_fund_account_id")
        if changed:
            account.save(update_fields=changed)
        return account.provider_fund_account_id
    def send(self, payout, account):
        """Start a payout of the net amount. The idempotency key makes retries safe: RazorpayX never pays the same item twice."""
        fund_account_id = self.ensure_fund_account(account)
        result = self._request("POST", "/payouts", {
            "account_number": self.account_number, "fund_account_id": fund_account_id, "amount": int(payout.net_amount * 100), "currency": "INR",
            "mode": "UPI" if account.payout_method == "upi" else "IMPS", "purpose": "payout", "queue_if_low_balance": True,
            "reference_id": f"payout-{payout.pk}", "narration": "MyProgress creator payout",
        }, idempotency_key=f"myprogress-payout-{payout.pk}")
        return {"id": result.get("id", ""), "status": result.get("status", ""), "utr": result.get("utr") or ""}
    def fetch(self, provider_payout_id):
        result = self._request("GET", f"/payouts/{provider_payout_id}")
        return {"id": result.get("id", ""), "status": result.get("status", ""), "utr": result.get("utr") or "", "reason": (result.get("status_details") or {}).get("description") or result.get("failure_reason") or ""}
def get_provider():
    """The configured payout provider, or None when payments are sent by hand."""
    if settings.RAZORPAYX_KEY_ID and settings.RAZORPAYX_KEY_SECRET and settings.RAZORPAYX_ACCOUNT_NUMBER:
        return RazorpayX(settings.RAZORPAYX_KEY_ID, settings.RAZORPAYX_KEY_SECRET, settings.RAZORPAYX_ACCOUNT_NUMBER)
    return None
def valid_webhook(body, signature):
    secret = settings.RAZORPAYX_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
def paise_to_rupees(paise):
    return (Decimal(paise or 0) / 100).quantize(Decimal("0.01"))
