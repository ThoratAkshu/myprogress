import hashlib
import hmac
import io
import itertools
import json
import time
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock
from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Follow, Profile
from apps.core.models import EarningTransaction, LearningPost
from apps.notifications.models import Notification
from . import services
from .models import CoinTransaction, CreatorAccount, EarningSettings, FinanceAuditLog, PaymentRun, PayoutRequest, TreasuryEntry
from .payouts import ProviderError, RazorpayX, get_provider
from .views import FINANCE_SESSION_KEY
PASSWORD = "StrongPass!482"
ARTICLE = "I built the ledger service with Go and PostgreSQL. " * 6
def make_user(email, first_name="Dev", last_name="Eloper", **extra):
    user = User.objects.create_user(username=email, email=email, password=PASSWORD, first_name=first_name, last_name=last_name, **extra)
    Profile.objects.create(user=user, handle=email.split("@")[0].replace(".", "-"))
    return user
FAN_NUMBERS = itertools.count()
def add_followers(user, count):
    numbers = [next(FAN_NUMBERS) for _ in range(count)]
    fans = User.objects.bulk_create([User(username=f"fan{number}@example.com", email=f"fan{number}@example.com") for number in numbers])
    Follow.objects.bulk_create([Follow(follower=fan, following=user) for fan in fans])
def post(user, kind="article", title="Ledger", public=True):
    return LearningPost.objects.create(author=user, title=title, kind=kind, body=ARTICLE, is_public=public)
def wallet(user):
    return services.rupee_balance(user)
class RupeeFormatTests(SimpleTestCase):
    def test_indian_grouping_and_paise(self):
        self.assertEqual(services.rupees(0), "₹0")
        self.assertEqual(services.rupees(10), "₹10")
        self.assertEqual(services.rupees(Decimal("10.5")), "₹10.50")
        self.assertEqual(services.rupees(125000), "₹1,25,000")
        self.assertEqual(services.rupees(12345678), "₹1,23,45,678")
        self.assertEqual(services.rupees(-50), "-₹50")
class EarningRuleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.creator = make_user("creator@example.com", "Cre", "Ator")
        EarningSettings.current()
    def test_articles_and_videos_earn_coins_but_no_money_before_the_follower_goal(self):
        self.assertEqual(services.sync_post_coins(post(self.creator)), 5)
        self.assertEqual(services.sync_post_coins(post(self.creator, kind="video")), 10)
        self.assertEqual(services.coin_balance(self.creator), 15)
        self.assertEqual(wallet(self.creator), 0)
    def test_a_hundred_coins_stay_saved_until_a_hundred_followers_then_both_rewards_pay(self):
        EarningSettings.objects.update(daily_post_limit=50)
        for index in range(10):
            services.sync_post_coins(post(self.creator, kind="video", title=f"Video {index}"))
        self.assertEqual(services.coin_balance(self.creator), 100)
        self.assertEqual(wallet(self.creator), 0)
        add_followers(self.creator, 99)
        services.refresh_creator(self.creator)
        self.assertIsNone(services.account_for(self.creator).eligible_since)
        fan = make_user("hundredth@example.com", "Hun", "Dredth")
        self.client.force_login(fan)
        self.client.post(reverse("landing:follow", args=[self.creator.profile.handle]))
        account = services.account_for(self.creator)
        self.assertIsNotNone(account.eligible_since)
        self.assertIsNotNone(account.follower_bonus_paid_at)
        self.assertEqual(wallet(self.creator), Decimal("20"))  # 10 bonus + 100 coins converted to 10
        self.assertEqual(services.coin_balance(self.creator), 0)
        self.assertTrue(Notification.objects.filter(recipient=self.creator, kind="earnings", text__contains="100 followers").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.creator, kind="earnings", text__contains="100 coins").exists())
    def test_bonus_is_paid_once_even_if_followers_leave_and_come_back(self):
        EarningSettings.objects.update(follower_goal=2)
        add_followers(self.creator, 2)
        services.refresh_creator(self.creator)
        Follow.objects.filter(following=self.creator).delete()
        services.refresh_creator(self.creator)
        add_followers(self.creator, 3)
        services.refresh_creator(self.creator)
        self.assertEqual(EarningTransaction.objects.filter(user=self.creator, description__startswith="Bonus").count(), 1)
        self.assertIsNotNone(services.account_for(self.creator).eligible_since)
    def test_coins_convert_every_hundred_once_unlocked(self):
        EarningSettings.objects.update(follower_goal=1, follower_bonus=0, daily_post_limit=50)
        add_followers(self.creator, 1)
        services.refresh_creator(self.creator)
        for index in range(21):
            services.sync_post_coins(post(self.creator, title=f"Article {index}"))
        self.assertEqual(wallet(self.creator), Decimal("10"))
        self.assertEqual(services.coin_balance(self.creator), 5)
        self.assertEqual(CoinTransaction.objects.filter(user=self.creator, kind="conversion").count(), 1)
    def test_daily_limit_stops_coin_farming(self):
        for index in range(6):
            services.sync_post_coins(post(self.creator, title=f"Article {index}"))
        self.assertEqual(services.coin_balance(self.creator), 25)
    def test_unpublishing_or_deleting_takes_coins_back_and_republishing_pays_once(self):
        article = post(self.creator)
        services.sync_post_coins(article)
        services.sync_post_coins(article)
        self.assertEqual(services.coin_balance(self.creator), 5)
        article.is_public = False
        services.sync_post_coins(article)
        self.assertEqual(services.coin_balance(self.creator), 0)
        article.is_public = True
        services.sync_post_coins(article)
        self.assertEqual(services.coin_balance(self.creator), 5)
        services.reverse_post_coins(article)
        article.delete()
        self.assertEqual(services.coin_balance(self.creator), 0)
    def test_private_drafts_earn_nothing_and_the_program_switch_stops_new_coins(self):
        self.assertEqual(services.sync_post_coins(post(self.creator, public=False)), 0)
        EarningSettings.objects.update(program_enabled=False)
        self.assertEqual(services.sync_post_coins(post(self.creator)), 0)
        self.assertEqual(services.coin_balance(self.creator), 0)
    def test_confirmed_followers_only(self):
        EarningSettings.objects.update(follower_goal=2, confirmed_followers_only=True)
        add_followers(self.creator, 2)
        services.refresh_creator(self.creator)
        self.assertIsNone(services.account_for(self.creator).eligible_since)
    def test_publishing_through_the_studio_awards_coins_and_says_so(self):
        self.client.force_login(self.creator)
        response = self.client.post(reverse("learning:create"), {"title": "Ledger notes", "kind": "article", "body": ARTICLE, "is_public": "on"}, follow=True)
        self.assertContains(response, "You earned 5 coins.")
        created = LearningPost.objects.get(title="Ledger notes")
        self.client.post(reverse("learning:delete", args=[created.pk]))
        self.assertEqual(services.coin_balance(self.creator), 0)
    def test_suspended_creators_keep_coins_but_do_not_convert(self):
        EarningSettings.objects.update(follower_goal=1, follower_bonus=0, coins_per_conversion=5)
        add_followers(self.creator, 1)
        services.refresh_creator(self.creator)
        CreatorAccount.objects.filter(user=self.creator).update(suspended=True)
        services.sync_post_coins(post(self.creator))
        self.assertEqual(services.coin_balance(self.creator), 5)
        self.assertEqual(wallet(self.creator), 0)
def months():
    this_month = timezone.localdate().replace(day=1)
    return services.previous_month(this_month), this_month
def into_last_month(user):
    """Move a creator's money history into last month, so it belongs to a closed month."""
    last, _ = months()
    EarningTransaction.objects.filter(user=user).update(created_at=services._midnight(last) + timedelta(days=2))
def pay_ready(user, **changes):
    data = {"payout_name": "Cre Ator", "pan": "ABCDE1234F", "payout_method": "upi", "upi_id": "cre@okaxis", "bank_account": "", "ifsc": "", "hold_payments": False, **changes}
    return services.save_payment_details(services.account_for(user), data)
def unlocked_creator(email="creator@example.com", bonus="150"):
    EarningSettings.objects.update_or_create(pk=1, defaults={"follower_goal": 1, "follower_bonus": Decimal(bonus)})
    user = make_user(email, "Cre", "Ator")
    add_followers(user, 1)
    services.refresh_creator(user)
    return user
def closed_run(*creators):
    for creator in creators:
        into_last_month(creator)
    return services.close_month(months()[0])[0]
def signed(body, secret="whsec_test"):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
class FakeProvider:
    name = "RazorpayX"
    def __init__(self, status="processing", fail=""):
        self.status, self.fail, self.sent = status, fail, []
    def send(self, payout, account):
        if self.fail:
            raise ProviderError(self.fail)
        self.sent.append(payout.pk)
        return {"id": f"pout_{payout.pk}", "status": self.status, "utr": ""}
    def fetch(self, provider_payout_id):
        return {"id": provider_payout_id, "status": "processed", "utr": "UTR777", "reason": ""}
class PaymentCycleTests(TestCase):
    """Monthly payments like YouTube's: close on the 1st, pay on payment day, hold when details are missing."""
    def setUp(self):
        cache.clear()
        self.creator = unlocked_creator()
        self.admin = make_user("owner@example.com", "Own", "Er", is_staff=True, is_superuser=True)
    def test_closing_a_month_schedules_payment_day_and_tells_creators(self):
        pay_ready(self.creator)
        run = closed_run(self.creator)
        last, this = months()
        self.assertEqual((run.month, run.scheduled_for, run.status), (last, this.replace(day=21), "scheduled"))
        text = Notification.objects.get(recipient=self.creator, text__contains="earnings are final").text
        self.assertIn(f"Your {last:%B} earnings are final: ₹150.", text)
        self.assertIn(f"₹150 will be paid around {this:%B} 21.", text)
        self.assertFalse(services.close_month(last)[1])
        with self.assertRaisesMessage(services.PayoutError, "after it ends"):
            services.close_month(this)
    def test_only_the_closed_balance_is_paid_and_this_months_money_waits(self):
        pay_ready(self.creator)
        run = closed_run(self.creator)
        EarningTransaction.objects.create(user=self.creator, transaction_type="credit", amount=Decimal("40"), description="This month")
        run, candidates = services.prepare_run(run)
        payout = PayoutRequest.objects.get(run=run)
        self.assertEqual((payout.amount, payout.destination, payout.status), (Decimal("150"), "UPI cre@okaxis", "pending"))
        self.assertEqual(wallet(self.creator), Decimal("40"))
        self.assertEqual(run.status, "ready")
        with self.assertRaisesMessage(services.PayoutError, "already prepared"):
            services.prepare_run(run)
    def test_holds_and_threshold(self):
        held_pan = unlocked_creator("nopan@example.com")
        pay_ready(held_pan, pan="")
        holding = unlocked_creator("holding@example.com")
        pay_ready(holding, hold_payments=True)
        small = unlocked_creator("small@example.com", bonus="40")
        pay_ready(small)
        no_details = unlocked_creator("nodetails@example.com")
        pay_ready(self.creator)
        for user in [held_pan, holding, small, no_details, self.creator]:
            into_last_month(user)
        candidates = services.payment_candidates(months()[0])
        self.assertEqual([row["user"] for row in candidates["to_pay"]], [self.creator])
        self.assertEqual([row["user"] for row in candidates["below"]], [small])
        labels = {row["user"].email: row["hold_labels"] for row in candidates["held"]}
        self.assertEqual(labels["nopan@example.com"], ["No PAN"])
        self.assertEqual(labels["holding@example.com"], ["Creator is holding"])
        self.assertIn("No payment details", labels["nodetails@example.com"])
        EarningSettings.objects.update(require_pan=False)
        self.assertIn(held_pan, [row["user"] for row in services.payment_candidates(months()[0])["to_pay"]])
    def test_tax_is_held_back_and_tracked_until_paid_to_the_government(self):
        EarningSettings.objects.update(tds_percent=Decimal("10"))
        pay_ready(self.creator)
        TreasuryEntry.objects.create(kind="deposit", amount=Decimal("1000"))
        run, _ = services.prepare_run(closed_run(self.creator))
        payout = run.payouts.get()
        self.assertEqual((payout.tds_amount, payout.net_amount), (Decimal("15.00"), Decimal("135.00")))
        services.mark_payout_paid(payout, self.admin, "UTR1")
        self.assertEqual(services.treasury_balance(), Decimal("865"))
        self.assertEqual(services.tax_to_deposit(), Decimal("15"))
        self.assertTrue(Notification.objects.filter(recipient=self.creator, text="₹135 was sent to UPI cre@okaxis after ₹15 tax.").exists())
        TreasuryEntry.objects.create(kind="tax", amount=Decimal("15"))
        self.assertEqual((services.tax_to_deposit(), services.treasury_balance()), (Decimal("0"), Decimal("850")))
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
    def test_returned_payments_go_back_to_the_balance_and_hold_until_details_change(self):
        pay_ready(self.creator)
        run, _ = services.prepare_run(closed_run(self.creator))
        services.reject_payout(run.payouts.get(), self.admin, "UPI ID not found")
        self.assertEqual(wallet(self.creator), Decimal("150"))
        self.assertEqual(EarningTransaction.objects.filter(user=self.creator, transaction_type="refund").count(), 1)
        self.assertEqual(services.creator_dashboard(self.creator)["lifetime"], Decimal("150"))
        account = services.account_for(self.creator)
        self.assertEqual([hold["code"] for hold in services.payment_holds(account, EarningSettings.current())], ["failed"])
        pay_ready(self.creator, upi_id="cre@okhdfc")
        self.assertEqual(services.payment_holds(services.account_for(self.creator), EarningSettings.current()), [])
    def test_provider_sends_and_webhooks_confirm_or_return(self):
        second = unlocked_creator("second@example.com")
        pay_ready(self.creator)
        pay_ready(second, upi_id="second@okaxis")
        run, _ = services.prepare_run(closed_run(self.creator, second))
        fake = FakeProvider()
        with mock.patch("apps.earnings.services.get_provider", return_value=fake):
            with self.assertRaisesMessage(services.PayoutError, "Add money first"):
                services.send_run(run, self.admin)
            TreasuryEntry.objects.create(kind="deposit", amount=Decimal("1000"))
            sent, failures = services.send_run(run, self.admin)
        self.assertEqual((sent, failures), (2, []))
        first, other = run.payouts.get(user=self.creator), run.payouts.get(user=second)
        self.assertEqual((first.status, first.provider_payout_id), ("processing", f"pout_{first.pk}"))
        with override_settings(RAZORPAYX_WEBHOOK_SECRET="whsec_test"):
            body = json.dumps({"event": "payout.processed", "payload": {"payout": {"entity": {"id": f"pout_{first.pk}", "status": "processed", "utr": "UTR4242", "reference_id": f"payout-{first.pk}"}}}}).encode()
            self.assertEqual(self.client.post(reverse("finance:razorpayx_webhook"), body, content_type="application/json", headers={"X-Razorpay-Signature": "forged"}).status_code, 400)
            self.assertEqual(self.client.post(reverse("finance:razorpayx_webhook"), body, content_type="application/json", headers={"X-Razorpay-Signature": signed(body)}).status_code, 200)
            body = json.dumps({"event": "payout.reversed", "payload": {"payout": {"entity": {"id": f"pout_{other.pk}", "status": "reversed", "status_details": {"description": "Beneficiary bank rejected the payment"}}}}}).encode()
            self.client.post(reverse("finance:razorpayx_webhook"), body, content_type="application/json", headers={"X-Razorpay-Signature": signed(body)})
        first.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((first.status, first.reference), ("paid", "UTR4242"))
        self.assertEqual((other.status, other.note), ("rejected", "Beneficiary bank rejected the payment"))
        self.assertEqual(wallet(second), Decimal("150"))
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
    def test_statuses_are_checked_when_a_webhook_is_missed(self):
        pay_ready(self.creator)
        TreasuryEntry.objects.create(kind="deposit", amount=Decimal("1000"))
        run, _ = services.prepare_run(closed_run(self.creator))
        with mock.patch("apps.earnings.services.get_provider", return_value=FakeProvider()):
            services.send_run(run)
            self.assertEqual(services.sync_sending(), 1)
        self.assertEqual(run.payouts.get().reference, "UTR777")
    def test_provider_errors_leave_the_payment_waiting(self):
        pay_ready(self.creator)
        TreasuryEntry.objects.create(kind="deposit", amount=Decimal("1000"))
        run, _ = services.prepare_run(closed_run(self.creator))
        with mock.patch("apps.earnings.services.get_provider", return_value=FakeProvider(fail="Invalid VPA")):
            sent, failures = services.send_run(run)
        payout = run.payouts.get()
        self.assertEqual((sent, payout.status, payout.note), (0, "pending", "Invalid VPA"))
    def test_daily_job_closes_on_the_first_and_pays_on_payment_day(self):
        pay_ready(self.creator)
        into_last_month(self.creator)
        last, this = months()
        call_command("run_payment_cycle", "--today", this.isoformat(), stdout=StringIO())
        self.assertEqual(PaymentRun.objects.get(month=last).status, "scheduled")
        call_command("run_payment_cycle", "--today", this.replace(day=20).isoformat(), stdout=StringIO())
        self.assertEqual(PaymentRun.objects.get(month=last).status, "scheduled")
        EarningSettings.objects.update(auto_send=True)
        TreasuryEntry.objects.create(kind="deposit", amount=Decimal("1000"))
        with mock.patch("apps.earnings.services.get_provider", return_value=FakeProvider()), mock.patch("apps.earnings.management.commands.run_payment_cycle.get_provider", return_value=FakeProvider()):
            call_command("run_payment_cycle", "--today", this.replace(day=21).isoformat(), stdout=StringIO())
        run = PaymentRun.objects.get(month=last)
        payout = run.payouts.get()
        self.assertEqual((run.status, payout.status, payout.reference), ("completed", "paid", "UTR777"))
class RazorpayXTests(TestCase):
    def setUp(self):
        self.creator = unlocked_creator()
        self.calls = []
    def fake_urlopen(self, request, timeout):
        body = json.loads(request.data) if request.data else None
        self.calls.append({"path": request.full_url.split("/v1", 1)[1], "body": body, "key": request.get_header("X-payout-idempotency")})
        replies = {"/contacts": {"id": "cont_1"}, "/fund_accounts": {"id": "fa_1"}}
        return io.BytesIO(json.dumps(replies.get(self.calls[-1]["path"], {"id": "pout_9", "status": "processing"})).encode())
    def payout(self, account):
        return PayoutRequest.objects.create(user=self.creator, amount=Decimal("150"), tds_amount=Decimal("15"), payout_name=account.payout_name, destination=account.destination)
    def test_upi_payout_requests(self):
        account = pay_ready(self.creator)
        payout = self.payout(account)
        provider = RazorpayX("rzp_test", "secret", "2323230000000000")
        with mock.patch("urllib.request.urlopen", side_effect=self.fake_urlopen):
            result = provider.send(payout, account)
            provider.send(payout, account)
        self.assertEqual(result["id"], "pout_9")
        self.assertEqual([call["path"] for call in self.calls], ["/contacts", "/fund_accounts", "/payouts", "/payouts"])
        self.assertEqual(self.calls[1]["body"]["vpa"], {"address": "cre@okaxis"})
        sent = self.calls[2]
        self.assertEqual((sent["body"]["amount"], sent["body"]["mode"], sent["body"]["fund_account_id"], sent["key"]), (13500, "UPI", "fa_1", f"myprogress-payout-{payout.pk}"))
        self.assertEqual(services.account_for(self.creator).provider_fund_account_id, "fa_1")
    def test_bank_payouts_use_imps_and_new_details_make_a_new_fund_account(self):
        account = pay_ready(self.creator, payout_method="bank", upi_id="", bank_account="123456784321", ifsc="HDFC0001234")
        account.provider_contact_id, account.provider_fund_account_id = "cont_1", "fa_old"
        account.save()
        pay_ready(self.creator, payout_method="bank", upi_id="", bank_account="999956784321", ifsc="HDFC0001234")
        account = services.account_for(self.creator)
        self.assertEqual((account.provider_contact_id, account.provider_fund_account_id), ("cont_1", ""))
        with mock.patch("urllib.request.urlopen", side_effect=self.fake_urlopen):
            RazorpayX("rzp_test", "secret", "2323230000000000").send(self.payout(account), account)
        self.assertEqual([call["path"] for call in self.calls], ["/fund_accounts", "/payouts"])
        self.assertEqual(self.calls[0]["body"]["bank_account"], {"name": "Cre Ator", "ifsc": "HDFC0001234", "account_number": "999956784321"})
        self.assertEqual(self.calls[1]["body"]["mode"], "IMPS")
    def test_provider_is_only_used_with_all_keys(self):
        self.assertIsNone(get_provider())
        with override_settings(RAZORPAYX_KEY_ID="rzp_test", RAZORPAYX_KEY_SECRET="secret", RAZORPAYX_ACCOUNT_NUMBER="2323230000000000"):
            self.assertIsInstance(get_provider(), RazorpayX)
class PaymentSettingsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.creator = unlocked_creator()
        self.client.force_login(self.creator)
    def save(self, **changes):
        data = {"payout_name": "Cre Ator", "pan": "abcde1234f", "payout_method": "upi", "upi_id": "cre@okaxis", **changes}
        return self.client.post(reverse("earnings:payment_details"), data, follow=True)
    def test_creator_sets_up_payments_and_mistakes_are_explained(self):
        self.assertContains(self.save(pan="12345"), "A PAN looks like ABCDE1234F.")
        self.assertEqual(services.account_for(self.creator).pan, "")
        self.assertContains(self.save(payout_method="bank", bank_account="123456784321", bank_account_confirm="123456784320", ifsc="HDFC0001234"), "The account numbers don&#x27;t match.")
        self.assertContains(self.save(payout_method="bank", bank_account="123456784321", bank_account_confirm="123456784321", ifsc="hdfc0001234"), "We&#x27;ll pay you at Bank ••••4321 (HDFC0001234).")
        account = services.account_for(self.creator)
        self.assertEqual((account.pan, account.ifsc, account.masked_pan), ("ABCDE1234F", "HDFC0001234", "•••••1234F"))
        self.save(payout_method="bank", bank_account="", ifsc="HDFC0001234", hold_payments="on")
        account = services.account_for(self.creator)
        self.assertEqual((account.bank_account, account.hold_payments), ("123456784321", True))
        self.assertTrue(FinanceAuditLog.objects.filter(action="payment_details_changed", details__contains="Bank ••••4321").exists())
    def test_earnings_page_shows_what_happens_next(self):
        page = self.client.get(reverse("landing:workspace_section", args=["earnings"]))
        self.assertContains(page, "Set up payments")
        self.assertContains(page, "Add your PAN.")
        pay_ready(self.creator)
        into_last_month(self.creator)
        page = self.client.get(reverse("landing:workspace_section", args=["earnings"]))
        self.assertContains(page, "₹150 will be paid")
        self.assertContains(page, "Paid around the 21st")
        services.prepare_run(services.close_month(months()[0])[0])
        self.assertContains(self.client.get(reverse("landing:workspace_section", args=["earnings"])), "₹150 is on its way to UPI cre@okaxis")
class CreatorDashboardTests(TestCase):
    def test_locked_dashboard_shows_progress_and_saved_coins(self):
        creator = make_user("new@example.com", "New", "Bie")
        add_followers(creator, 37)
        services.sync_post_coins(post(creator, kind="video"))
        self.client.force_login(creator)
        page = self.client.get(reverse("landing:workspace_section", args=["earnings"]))
        self.assertContains(page, "Unlock earnings")
        self.assertContains(page, "63 more followers to unlock earnings and a ₹10 bonus")
        self.assertContains(page, "10 coins saved for you")
        self.assertContains(page, "Payments start at 100 followers")
        self.assertContains(page, "+5")
        self.assertContains(page, "+10")
class FinanceConsoleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user("owner@example.com", "Own", "Er", is_staff=True, is_superuser=True)
        self.creator = make_user("creator@example.com", "Cre", "Ator")
    def finance_login(self, user=None, password=PASSWORD):
        return self.client.post(reverse("finance:login"), {"email": (user or self.owner).email, "password": password})
    def test_console_needs_its_own_sign_in_even_for_a_signed_in_owner(self):
        self.assertRedirects(self.client.get(reverse("finance:overview")), f'{reverse("finance:login")}?next=%2Ffinance%2F', fetch_redirect_response=False)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("finance:overview")).status_code, 302)
        self.assertContains(self.client.get(reverse("finance:login")), 'value="owner@example.com"')
        self.assertRedirects(self.finance_login(), reverse("finance:overview"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("finance:overview")), "Master account")
        self.assertTrue(FinanceAuditLog.objects.filter(action="signed_in", actor=self.owner).exists())
    def test_people_without_finance_access_are_turned_away(self):
        response = self.finance_login(self.creator)
        self.assertContains(response, "can&#x27;t use the finance console")
        self.assertNotIn("_auth_user_id", self.client.session)
        staff = make_user("staff@example.com", is_staff=True)
        self.assertContains(self.finance_login(staff), "can&#x27;t use the finance console")
        staff.user_permissions.add(Permission.objects.get(codename="access_finance"))
        self.assertRedirects(self.finance_login(staff), reverse("finance:overview"), fetch_redirect_response=False)
        self.client.force_login(self.creator)
        self.assertEqual(self.client.get(reverse("finance:payouts")).status_code, 302)
    def test_wrong_passwords_are_rate_limited(self):
        for _ in range(5):
            self.finance_login(password="wrong")
        self.assertContains(self.finance_login(), "Too many failed attempts")
    def test_console_locks_after_idle_time_and_on_sign_out(self):
        self.finance_login()
        session = self.client.session
        session[FINANCE_SESSION_KEY] = time.time() - 31 * 60
        session.save()
        self.assertEqual(self.client.get(reverse("finance:overview")).status_code, 302)
        self.finance_login()
        self.client.post(reverse("finance:logout"))
        self.assertEqual(self.client.get(reverse("finance:overview")).status_code, 302)
    def test_every_page_renders(self):
        self.creator = unlocked_creator("payee@example.com")
        pay_ready(self.creator)
        closed_run(self.creator)
        self.finance_login()
        for name, args in [("finance:overview", []), ("finance:payouts", []), ("finance:treasury", []), ("finance:settings", []), ("finance:creators", []), ("finance:creator", [self.creator.pk]), ("finance:audit", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
        self.assertContains(self.client.get(reverse("finance:overview")), "The master account is short by ₹150")
        payments = self.client.get(reverse("finance:payouts"))
        self.assertContains(payments, "Will be paid")
        self.assertContains(payments, "Prepare payments")
        self.assertContains(payments, "Manual payments")
        self.assertContains(self.client.get(reverse("finance:creators")), "Cre Ator")
    def test_rules_treasury_and_adjustments(self):
        self.finance_login()
        rules = {"program_enabled": "on", "follower_goal": "50", "follower_bonus": "25", "coins_per_article": "6", "coins_per_video": "12", "coins_per_conversion": "100", "rupees_per_conversion": "10", "daily_post_limit": "5", "minimum_payout": "100", "payout_day": "21", "tds_percent": "1", "require_pan": "on"}
        self.assertRedirects(self.client.post(reverse("finance:settings"), rules), reverse("finance:settings"), fetch_redirect_response=False)
        saved = EarningSettings.current()
        self.assertEqual((saved.follower_goal, saved.coins_per_article, saved.tds_percent, saved.updated_by), (50, 6, Decimal("1"), self.owner))
        self.assertTrue(FinanceAuditLog.objects.filter(action="rules_changed", details__contains="follower_goal 100 → 50").exists())
        self.assertContains(self.client.post(reverse("finance:settings"), {**rules, "follower_goal": "0"}), "Must be at least 1.")
        self.assertContains(self.client.post(reverse("finance:settings"), {**rules, "payout_day": "31"}), "Pick a day from 1 to 28")
        self.client.post(reverse("finance:treasury"), {"kind": "deposit", "amount": "500", "reference": "NEFT1", "note": "October budget"})
        self.assertEqual(services.treasury_balance(), Decimal("500"))
        self.assertContains(self.client.post(reverse("finance:treasury"), {"kind": "withdrawal", "amount": "900", "reference": "", "note": ""}), "only holds ₹500")
        EarningSettings.objects.update(follower_goal=1, follower_bonus=0)
        add_followers(self.creator, 1)
        services.refresh_creator(self.creator)
        self.client.post(reverse("finance:creator", args=[self.creator.pk]), {"action": "adjust", "coins": "", "amount": "300", "reason": "Launch prize"})
        self.assertEqual(wallet(self.creator), Decimal("300"))
    def test_preparing_and_paying_a_month_by_hand(self):
        self.creator = unlocked_creator("payee@example.com")
        pay_ready(self.creator, payout_name="=HYPERLINK(1)")
        run = closed_run(self.creator)
        self.finance_login()
        self.client.post(reverse("finance:prepare_run", args=[run.pk]))
        run.refresh_from_db()
        self.assertEqual(run.status, "ready")
        body = self.client.get(reverse("finance:payouts_csv", args=[run.pk])).content.decode()
        self.assertIn("'=HYPERLINK(1)", body)
        self.assertIn("upi,cre@okaxis,,,150.00,0.00,150.00", body)
        self.assertContains(self.client.post(reverse("finance:send_run", args=[run.pk]), follow=True), "No payout provider is connected")
        payout = run.payouts.get()
        self.client.post(reverse("finance:payout_paid", args=[payout.pk]), {"reference": "UTR999"})
        payout.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual((payout.status, payout.reference, payout.processed_by, run.status), ("paid", "UTR999", self.owner, "completed"))
    def test_sending_through_the_provider_from_the_console(self):
        self.creator = unlocked_creator("payee@example.com")
        pay_ready(self.creator)
        run, _ = services.prepare_run(closed_run(self.creator))
        self.finance_login()
        fake = FakeProvider()
        with mock.patch("apps.earnings.services.get_provider", return_value=fake), mock.patch("apps.earnings.views.get_provider", return_value=fake):
            self.assertContains(self.client.post(reverse("finance:send_run", args=[run.pk]), follow=True), "Add money first")
            TreasuryEntry.objects.create(kind="deposit", amount=Decimal("1000"))
            self.assertContains(self.client.post(reverse("finance:send_run", args=[run.pk]), follow=True), "1 payment sent to RazorpayX.")
        self.assertEqual(run.payouts.get().status, "processing")
    def test_close_month_from_the_console(self):
        self.creator = unlocked_creator("payee@example.com")
        into_last_month(self.creator)
        self.finance_login()
        self.assertContains(self.client.get(reverse("finance:payouts")), f"Close {months()[0]:%B}")
        self.client.post(reverse("finance:close_month"))
        self.assertTrue(PaymentRun.objects.filter(month=months()[0]).exists())
    def test_pausing_a_creator_holds_payments_and_tells_them(self):
        self.creator = unlocked_creator("payee@example.com")
        pay_ready(self.creator)
        self.finance_login()
        self.client.post(reverse("finance:creator", args=[self.creator.pk]), {"action": "suspend", "reason": "Followers look fake"})
        self.assertEqual([hold["code"] for hold in services.payment_holds(services.account_for(self.creator), EarningSettings.current())], ["suspended"])
        self.assertTrue(Notification.objects.filter(recipient=self.creator, text__contains="Followers look fake").exists())
        self.client.post(reverse("finance:creator", args=[self.creator.pk]), {"action": "restore"})
        self.assertEqual(services.payment_holds(services.account_for(self.creator), EarningSettings.current()), [])
    def test_only_finance_staff_see_the_console_in_the_menu(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("landing:dashboard")), "Finance console")
        self.client.force_login(self.creator)
        self.assertNotContains(self.client.get(reverse("landing:dashboard")), "Finance console")
        self.assertRedirects(self.client.get("/earnings/"), reverse("landing:workspace_section", args=["earnings"]))
    def test_finance_admin_command_grants_and_revokes_access(self):
        call_command("create_finance_admin", "creator@example.com", stdout=StringIO())
        self.creator.refresh_from_db()
        self.assertTrue(self.creator.is_staff)
        self.assertRedirects(self.finance_login(self.creator), reverse("finance:overview"), fetch_redirect_response=False)
        call_command("create_finance_admin", "creator@example.com", "--revoke", stdout=StringIO())
        self.assertFalse(User.objects.get(pk=self.creator.pk).has_perm("earnings.access_finance"))

