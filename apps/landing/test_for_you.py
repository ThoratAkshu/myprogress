from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import Profile
from apps.core.models import LearningPost
class ForYouLoopTests(TestCase):
    """For you keeps going: each request gives the next page of posts, and after the last page the first again."""
    def setUp(self):
        self.viewer = User.objects.create_user(username="v@example.com", email="v@example.com", password="StrongPass!482")
        Profile.objects.create(user=self.viewer, handle="viewer")
        author = User.objects.create_user(username="a@example.com", email="a@example.com", password="StrongPass!482", first_name="Asha")
        Profile.objects.create(user=author, handle="asha")
        for number in range(13):
            LearningPost.objects.create(author=author, title=f"Build log {number:02d}", kind="article", body="Notes", is_public=True)
        LearningPost.objects.create(author=author, title="Private draft", kind="article", body="Notes", is_public=False)
        self.client.force_login(self.viewer)
        self.url = reverse("landing:workspace_section", args=["learning"])
    def cards(self, page):
        return self.client.get(self.url, {"tab": "for-you", "cards": "1", "page": page}, HTTP_X_REQUESTED_WITH="fetch")
    def test_the_page_starts_the_loop(self):
        page = self.client.get(self.url, {"tab": "for-you"})
        self.assertContains(page, "data-for-you")
        self.assertContains(page, 'data-next-page="2"')
        self.assertContains(page, "landing/js/for-you")
        self.assertContains(page, "data-for-you-pager")  # the Newer / Older links stay for browsers without JavaScript
    def test_after_the_last_page_it_starts_again(self):
        second = self.cards(2)
        self.assertContains(second, "Build log 02")
        self.assertNotContains(second, "Build log 12")
        self.assertContains(second, 'data-next-page="1"')
        self.assertNotContains(second, "Private draft")
        self.assertContains(self.cards(1), 'data-next-page="2"')
    def test_other_tabs_keep_their_pages(self):
        self.assertNotContains(self.client.get(self.url, {"tab": "mine"}), "data-for-you")
