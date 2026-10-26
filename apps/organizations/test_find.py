from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import Profile
from apps.notifications.models import Notification
from . import services
from .models import Membership, Organization
def make_user(email, role="developer"):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=email.split("@")[0].title())
    Profile.objects.create(user=user, handle=email.replace("@", "-").replace(".", "-"), role=role)
    return user
def centre(name, slug, **fields):
    owner = make_user(f"owner@{slug}.in", role="organization")
    organization = Organization.objects.create(owner=owner, name=name, slug=slug, **fields)
    Membership.objects.create(organization=organization, user=owner, role="owner", status="active")
    return organization
class FindCentreTests(TestCase):
    def setUp(self):
        self.listed = centre("Sunrise Coding", "sunrise", is_listed=True, city="Pune", courses="Python, Web development", listing_pitch="Weekend batches for beginners")
        self.other = centre("Bay Data Academy", "bay", is_listed=True, city="Mumbai", courses="Data science, SQL")
        self.hidden = centre("Private Institute", "private", is_listed=False, city="Pune", courses="Python")
        self.student = make_user("asha@example.com")
    def test_only_listed_centres_appear_and_can_be_searched(self):
        page = self.client.get(reverse("organizations:find_centres"))
        self.assertContains(page, "Sunrise Coding")
        self.assertContains(page, "Bay Data Academy")
        self.assertNotContains(page, "Private Institute")
        self.assertContains(page, "Weekend batches for beginners")
        python = self.client.get(reverse("organizations:find_centres"), {"q": "python"})
        self.assertContains(python, "Sunrise Coding")
        self.assertNotContains(python, "Bay Data Academy")
        mumbai = self.client.get(reverse("organizations:find_centres"), {"city": "Mumbai"})
        self.assertNotContains(mumbai, "Sunrise Coding")
        self.assertContains(mumbai, "Bay Data Academy")
        self.assertEqual(self.client.get(reverse("organizations:listing", args=["private"])).status_code, 404)
    def test_asking_to_join_from_the_list_always_waits_for_a_teacher(self):
        self.assertFalse(self.listed.join_requires_approval)  # even when the invite link joins straight away
        self.client.force_login(self.student)
        page = self.client.get(reverse("organizations:listing", args=["sunrise"]))
        self.assertContains(page, "Ask to join")
        self.assertContains(page, "Python")
        self.client.post(reverse("organizations:listing", args=["sunrise"]))
        member = Membership.objects.get(organization=self.listed, user=self.student)
        self.assertEqual((member.status, member.role), ("pending", "student"))
        self.assertTrue(Notification.objects.filter(recipient=self.listed.owner, text__contains="asked to join").exists())
        self.assertContains(self.client.get(reverse("organizations:find_centres")), "Request sent")
        self.assertContains(self.client.get(reverse("organizations:listing", args=["sunrise"])), "waiting for a teacher")
    def test_an_invite_code_opens_the_join_page(self):
        response = self.client.get(reverse("organizations:find"), {"code": self.hidden.invite_code})
        self.assertRedirects(response, reverse("organizations:join", args=[self.hidden.invite_code]), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("organizations:find"), {"code": "nope"}, follow=True), "doesn&#x27;t match a class")
    def test_find_is_a_reserved_slug(self):
        self.assertEqual(services.unique_slug("Find"), "find-org")
    def test_centres_choose_to_be_listed_in_settings(self):
        self.client.force_login(self.hidden.owner)
        page = self.client.get(reverse("organizations:settings", args=["private"]))
        self.assertContains(page, "List us in Find a coaching centre")
