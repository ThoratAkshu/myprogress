from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import Profile
from apps.core.models import LearningPost
from apps.promotions.tests import centre, live_post, make_user
class LearnFeedAdsTests(TestCase):
    """Learn's feeds carry the same ads as the home feed: MyProgress's suggestion once, and sponsored posts."""
    def setUp(self):
        self.viewer = make_user("viewer@example.com")
        author = make_user("author@example.com")
        for number in range(13):
            LearningPost.objects.create(author=author, title=f"Build log {number:02d}", kind="article", body="Notes", is_public=True)
        LearningPost.objects.create(author=self.viewer, title="My own notes", kind="article", body="Notes", is_public=True)
        owner = make_user("owner@sunrise.in", role="organization")
        self.promotion = live_post(owner, centre(owner, is_listed=True))
        self.client.force_login(self.viewer)
        self.url = reverse("landing:workspace_section", args=["learning"])
    def kinds(self, items):
        return ["suggestion" if item.get("next_step") else "sponsored" if item.get("sponsored") else "post" for item in items]
    def test_for_you_has_the_suggestion_and_a_sponsored_post(self):
        page = self.client.get(self.url, {"tab": "for-you"})
        kinds = self.kinds(page.context["learning_items"])
        self.assertEqual(kinds.index("suggestion"), 3)  # after the 3rd post
        self.assertEqual(kinds.index("sponsored"), 8)   # after the 7th post, so the two never sit together
        self.assertEqual(kinds.count("post"), 10)
        self.assertContains(page, "Recommended for you")
        self.assertContains(page, "Weekend Python batch")
        self.assertContains(page, "guidance/feed")
    def test_pages_that_load_while_scrolling_bring_sponsored_posts_but_not_the_suggestion_again(self):
        cards = self.client.get(self.url, {"tab": "for-you", "cards": "1", "page": 2}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertContains(cards, "data-ad-card")
        self.assertContains(cards, "Weekend Python batch")
        self.assertNotContains(cards, "Recommended for you")
    def test_my_content_has_no_ads(self):
        page = self.client.get(self.url, {"tab": "mine"})
        self.assertEqual(self.kinds(page.context["learning_items"]), ["post"])
        self.assertNotContains(page, "data-ad-card")
