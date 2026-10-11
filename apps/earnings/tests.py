import itertools
import time
from decimal import Decimal
from io import StringIO
from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from apps.accounts.models import Follow, Profile
from apps.core.models import EarningTransaction, LearningPost
from apps.notifications.models import Notification
from . import services
from .models import CoinTransaction, CreatorAccount, EarningSettings, FinanceAuditLog, PayoutRequest, TreasuryEntry
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
class PayoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.creator = make_user("creator@example.com", "Cre", "Ator")
        self.admin = make_user("owner@example.com", "Own", "Er", is_staff=True, is_superuser=True)
        EarningSettings.objects.create(pk=1, follower_goal=1, follower_bonus=Decimal("150"))
        add_followers(self.creator, 1)
        services.refresh_creator(self.creator)
    def test_withdrawal_checks(self):
        with self.assertRaisesMessage(services.PayoutError, "smallest withdrawal"):
            services.request_payout(self.creator, "50", "cre@okaxis", "Cre Ator")
        with self.assertRaisesMessage(services.PayoutError, "more than your wallet"):
            services.request_payout(self.creator, "500", "cre@okaxis", "Cre Ator")
        with self.assertRaisesMessage(services.PayoutError, "UPI ID"):
            services.request_payout(self.creator, "100", "not-a-upi", "Cre Ator")
        services.request_payout(self.creator, "100", "cre@okaxis", "Cre Ator")
        self.assertEqual(wallet(self.creator), Decimal("50"))
        with self.assertRaisesMessage(services.PayoutError, "already have a withdrawal"):
            services.request_payout(self.creator, "100", "cre@okaxis", "Cre Ator")
    def test_locked_creators_cannot_withdraw(self):
        other = make_user("other@example.com")
        EarningTransaction.objects.create(user=other, transaction_type="adjustment", amount=Decimal("500"), description="Test")
        with self.assertRaisesMessage(services.PayoutError, "unlocked"):
            services.request_payout(other, "100", "o@okaxis", "Other")
    def test_paid_payouts_leave_the_master_account_and_rejected_ones_return_to_the_wallet(self):
        TreasuryEntry.objects.create(kind="deposit", amount=Decimal("1000"))
        payout = services.request_payout(self.creator, "100", "cre@okaxis", "Cre Ator")
        self.assertEqual(services.owed_to_creators(), Decimal("150"))
        services.mark_payout_paid(payout, self.admin, "UTR123")
        self.assertEqual(services.treasury_balance(), Decimal("900"))
        self.assertEqual(services.owed_to_creators(), Decimal("50"))
        self.assertTrue(FinanceAuditLog.objects.filter(action="payout_paid", details__contains="UTR123").exists())
        with self.assertRaises(services.PayoutError):
            services.mark_payout_paid(payout, self.admin, "again")
        EarningTransaction.objects.create(user=self.creator, transaction_type="adjustment", amount=Decimal("100"), description="Top up")
        second = services.request_payout(self.creator, "120", "cre@okaxis", "Cre Ator")
        services.reject_payout(second, self.admin, "UPI ID didn't match the name")
        self.assertEqual(wallet(self.creator), Decimal("150"))
        self.assertEqual(services.treasury_balance(), Decimal("900"))
    def test_creator_can_withdraw_from_the_earnings_page(self):
        self.client.force_login(self.creator)
        page = self.client.get(reverse("landing:workspace_section", args=["earnings"]))
        self.assertContains(page, "Withdraw to UPI")
        self.assertContains(page, "₹150")
        response = self.client.post(reverse("earnings:withdraw"), {"amount": "120", "upi_id": "cre@okaxis", "payout_name": "Cre Ator"}, follow=True)
        self.assertContains(response, "Withdrawal of ₹120 requested")
        self.assertContains(response, "is on its way to cre@okaxis")
        self.assertEqual(PayoutRequest.objects.get().amount, Decimal("120"))
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
        self.assertContains(page, "Withdrawals open at 100 followers")
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
        EarningSettings.objects.create(pk=1, follower_goal=1, follower_bonus=Decimal("200"))
        add_followers(self.creator, 1)
        services.refresh_creator(self.creator)
        services.request_payout(self.creator, "150", "cre@okaxis", "Cre Ator")
        self.finance_login()
        for name, args in [("finance:overview", []), ("finance:payouts", []), ("finance:treasury", []), ("finance:settings", []), ("finance:creators", []), ("finance:creator", [self.creator.pk]), ("finance:audit", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
        overview = self.client.get(reverse("finance:overview"))
        self.assertContains(overview, "The master account is short by ₹200")
        self.assertContains(self.client.get(reverse("finance:creators")), "Cre Ator")
    def test_rules_treasury_payouts_and_adjustments(self):
        self.finance_login()
        response = self.client.post(reverse("finance:settings"), {"program_enabled": "on", "follower_goal": "50", "follower_bonus": "25", "coins_per_article": "6", "coins_per_video": "12", "coins_per_conversion": "100", "rupees_per_conversion": "10", "daily_post_limit": "5", "minimum_payout": "100"})
        self.assertRedirects(response, reverse("finance:settings"), fetch_redirect_response=False)
        rules = EarningSettings.current()
        self.assertEqual((rules.follower_goal, rules.coins_per_article, rules.updated_by), (50, 6, self.owner))
        self.assertTrue(FinanceAuditLog.objects.filter(action="rules_changed", details__contains="follower_goal 100 → 50").exists())
        bad = self.client.post(reverse("finance:settings"), {"follower_goal": "0", "follower_bonus": "10", "coins_per_article": "5", "coins_per_video": "10", "coins_per_conversion": "100", "rupees_per_conversion": "10", "daily_post_limit": "5", "minimum_payout": "100"})
        self.assertContains(bad, "Must be at least 1.")
        self.client.post(reverse("finance:treasury"), {"kind": "deposit", "amount": "500", "reference": "NEFT1", "note": "October budget"})
        self.assertEqual(services.treasury_balance(), Decimal("500"))
        over = self.client.post(reverse("finance:treasury"), {"kind": "withdrawal", "amount": "900", "reference": "", "note": ""})
        self.assertContains(over, "only holds ₹500")
        EarningSettings.objects.update(follower_goal=1, follower_bonus=0)
        add_followers(self.creator, 1)
        services.refresh_creator(self.creator)
        self.client.post(reverse("finance:creator", args=[self.creator.pk]), {"action": "adjust", "coins": "", "amount": "300", "reason": "Launch prize"})
        self.assertEqual(wallet(self.creator), Decimal("300"))
        payout = services.request_payout(self.creator, "300", "cre@okaxis", "Cre Ator")
        self.client.post(reverse("finance:payout_paid", args=[payout.pk]), {"reference": "UTR999"})
        payout.refresh_from_db()
        self.assertEqual((payout.status, payout.reference, payout.processed_by), ("paid", "UTR999", self.owner))
        self.assertEqual(services.treasury_balance(), Decimal("200"))
    def test_pausing_a_creator_stops_withdrawals_and_tells_them(self):
        EarningSettings.objects.create(pk=1, follower_goal=1, follower_bonus=Decimal("150"))
        add_followers(self.creator, 1)
        services.refresh_creator(self.creator)
        self.finance_login()
        self.client.post(reverse("finance:creator", args=[self.creator.pk]), {"action": "suspend", "reason": "Followers look fake"})
        with self.assertRaisesMessage(services.PayoutError, "paused"):
            services.request_payout(self.creator, "100", "cre@okaxis", "Cre Ator")
        self.assertTrue(Notification.objects.filter(recipient=self.creator, text__contains="Followers look fake").exists())
        self.client.post(reverse("finance:creator", args=[self.creator.pk]), {"action": "restore"})
        services.request_payout(self.creator, "100", "cre@okaxis", "Cre Ator")
    def test_payout_csv_neutralises_formulas(self):
        EarningSettings.objects.create(pk=1, follower_goal=1, follower_bonus=Decimal("150"))
        add_followers(self.creator, 1)
        services.refresh_creator(self.creator)
        services.request_payout(self.creator, "100", "cre@okaxis", "=HYPERLINK(1)")
        self.finance_login()
        body = self.client.get(reverse("finance:payouts_csv")).content.decode()
        self.assertIn("'=HYPERLINK(1)", body)
        self.assertIn("cre@okaxis,100.00", body)
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
