from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import Profile
from apps.core.models import LearningPost
from apps.earnings.models import EarningSettings
from .views import LIVE_STATS_MINIMUM
def make_user(email, first_name, last_name, **profile):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, handle=email.split("@")[0], **profile)
    return user
class HomePageTests(TestCase):
    """The public home page only says things that are true."""
    def test_no_invented_numbers_or_quotes(self):
        page = self.client.get(reverse("landing:home"))
        for claim in ["2,400+", "25k+", "140k", "8.4k", "92%", "94% match", "Only verified recruiters can contact you"]:
            self.assertNotContains(page, claim)
        self.assertContains(page, "Free for developers.")
        self.assertContains(page, "Sample data")
        self.assertNotContains(self.client.get(reverse("landing:register")), "Early developer community member")
    def test_earning_rules_on_the_page_follow_the_finance_settings(self):
        EarningSettings.objects.update_or_create(pk=1, defaults={"coins_per_article": 7, "coins_per_video": 12, "follower_goal": 250, "payout_day": 15})
        page = self.client.get(reverse("landing:home"))
        self.assertContains(page, "+7")
        self.assertContains(page, "+12")
        self.assertContains(page, "250")
        self.assertContains(page, "paid every month")
        self.assertContains(page, "around the 15th")
        self.assertContains(page, "Published · +12 coins")
    def test_live_leaderboard_and_posts_are_real(self):
        page = self.client.get(reverse("landing:home"))
        self.assertContains(page, "The leaderboard is waiting for its first names.")
        self.assertNotContains(page, "Fresh from the community")
        author = make_user("asha@example.com", "Asha", "Rao", headline="Django engineer", score=64)
        make_user("hidden@example.com", "Hid", "Den", score=90, recruiter_visible=False)
        LearningPost.objects.create(author=author, title="How I built a ledger in Go", kind="article", body="Notes", is_public=True)
        LearningPost.objects.create(author=author, title="Private draft", kind="article", body="Notes", is_public=False)
        page = self.client.get(reverse("landing:home"))
        self.assertContains(page, "Asha Rao")
        self.assertContains(page, reverse("landing:public_profile", args=["asha"]))
        self.assertNotContains(page, "Hid Den")
        self.assertContains(page, "How I built a ledger in Go")
        self.assertNotContains(page, "Private draft")
    def test_live_counts_only_show_once_they_mean_something(self):
        self.assertNotContains(self.client.get(reverse("landing:home")), "developers are already building")
        User.objects.bulk_create([User(username=f"dev{number}@example.com") for number in range(LIVE_STATS_MINIMUM)])
        Profile.objects.bulk_create([Profile(user=user, handle=user.username.split("@")[0]) for user in User.objects.filter(username__startswith="dev")])
        page = self.client.get(reverse("landing:home"))
        self.assertContains(page, f"{LIVE_STATS_MINIMUM} developers")
        self.assertContains(page, "are already building on MyProgress")
