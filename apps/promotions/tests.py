import io
from datetime import timedelta
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from apps.accounts.models import Profile
from apps.core.models import ActivityEvent, LearningPost
from apps.notifications.models import Notification
from apps.organizations.models import Membership, Organization
from . import services
from .models import Promotion, PromotionHide, PromotionView
def make_user(email, role="developer", staff=False, **profile):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=email.split("@")[0].title(), last_name="Test", is_staff=staff)
    Profile.objects.create(user=user, handle=email.split("@")[0], role=role, **profile)
    return user
def watched(user, count=8):
    for _ in range(count):
        ActivityEvent.objects.create(user=user, event_type="learning", action="viewed_learning", metadata={})
def public_activity(count=4):
    """Posts from someone else, so the home feed has items for sponsored posts to sit between."""
    author = make_user(f"author{User.objects.count()}@example.com")
    for number in range(count):
        post = LearningPost.objects.create(author=author, title=f"How I built thing {number}", kind="article", body="Notes", is_public=True)
        ActivityEvent.objects.create(user=author, event_type="learning", action="published_learning", metadata={"post_id": post.pk})
def centre(owner, **fields):
    organization = Organization.objects.create(owner=owner, name=fields.pop("name", "Sunrise Coding"), slug=fields.pop("slug", "sunrise"), **fields)
    Membership.objects.create(organization=organization, user=owner, role="owner", status="active")
    return organization
def live_post(owner, organization=None, **fields):
    defaults = {"sponsor_kind": "organization" if organization else "recruiter", "organization": organization, "sponsor_name": organization.name if organization else "Acme",
                "headline": "Weekend Python batch", "body": "Live classes and a mentor who reviews your code.", "status": "live", "submitted_at": timezone.now()}
    return Promotion.objects.create(created_by=owner, **{**defaults, **fields})
class SponsorTests(TestCase):
    def test_who_may_sponsor(self):
        owner = make_user("owner@sunrise.in", role="organization")
        organization = centre(owner)
        self.assertEqual([option["key"] for option in services.sponsor_options(owner)], [f"organization:{organization.pk}"])
        unconfirmed = make_user("hr@acme.com", role="recruiter", company_name="Acme")
        self.assertEqual(services.sponsor_options(unconfirmed), [])
        confirmed = make_user("talent@acme.com", role="recruiter", company_name="Acme", email_verified_at=timezone.now())
        self.assertEqual(services.sponsor_options(confirmed)[0]["name"], "Acme")
        student = make_user("student@example.com")
        self.client.force_login(student)
        self.assertContains(self.client.get(reverse("promotions:list")), "Sponsored posts are for coaching centres, recruiters and companies")
        self.assertRedirects(self.client.get(reverse("promotions:create")), reverse("promotions:list"))
    def test_write_review_and_go_live(self):
        owner = make_user("owner@sunrise.in", role="organization")
        organization = centre(owner, is_listed=True)
        staff = make_user("staff@myprogress.in", staff=True)
        self.client.force_login(owner)
        response = self.client.post(reverse("promotions:create"), {
            "sponsor": f"organization:{organization.pk}", "headline": "Weekend Python batch", "body": "Live classes every Saturday.",
            "cta_label": "See the batch", "audiences": ["watching", "students"], "skills": "Python", "city": "Pune", "submit": "1",
        })
        self.assertRedirects(response, reverse("promotions:list"))
        promotion = Promotion.objects.get()
        self.assertEqual((promotion.status, promotion.sponsor_name, promotion.audiences), ("pending", "Sunrise Coding", ["watching", "students"]))
        self.assertTrue(Notification.objects.filter(recipient=staff, kind="promotion").exists())
        # Only staff review.
        self.assertEqual(self.client.get(reverse("promotions:review")).status_code, 404)
        self.client.post(reverse("promotions:review_action", args=[promotion.pk]), {"action": "approve"})
        self.assertEqual(Promotion.objects.get().status, "pending")
        self.client.force_login(staff)
        self.assertContains(self.client.get(reverse("promotions:review")), "Weekend Python batch")
        self.client.post(reverse("promotions:review_action", args=[promotion.pk]), {"action": "reject", "note": ""})
        self.assertEqual(Promotion.objects.get().status, "pending")  # sending back needs a note
        self.client.post(reverse("promotions:review_action", args=[promotion.pk]), {"action": "approve"})
        promotion.refresh_from_db()
        self.assertEqual((promotion.status, promotion.reviewed_by), ("live", staff))
        self.assertTrue(Notification.objects.filter(recipient=owner, kind="promotion", text__contains="is live").exists())
        # Any change to a live post goes back for review.
        self.client.force_login(owner)
        self.client.post(reverse("promotions:edit", args=[promotion.pk]), {"sponsor": f"organization:{organization.pk}", "headline": "Weekday Python batch", "body": "Evenings.", "cta_label": "See it"})
        self.assertEqual(Promotion.objects.get().status, "pending")
    def test_button_links_are_checked(self):
        owner = make_user("owner@sunrise.in", role="organization")
        organization = centre(owner)
        self.client.force_login(owner)
        base = {"sponsor": f"organization:{organization.pk}", "headline": "Batch", "body": "Classes.", "cta_label": "Go"}
        for bad in ["javascript:alert(1)", "//evil.example/", "http://plain.example/", "ftp://files.example/"]:
            page = self.client.post(reverse("promotions:create"), {**base, "cta_url": bad})
            self.assertContains(page, "Use a page on MyProgress", msg_prefix=bad)
        for good in ["/org/find/", "https://sunrise.example/batches"]:
            self.client.post(reverse("promotions:create"), {**base, "cta_url": good})
        self.assertEqual(sorted(Promotion.objects.values_list("cta_url", flat=True)), ["/org/find/", "https://sunrise.example/batches"])
    def test_images_are_cropped_to_the_feed_shape(self):
        owner = make_user("owner@sunrise.in", role="organization")
        organization = centre(owner)
        buffer = io.BytesIO()
        Image.new("RGB", (1600, 1600), "#2563eb").save(buffer, "PNG")
        self.client.force_login(owner)
        self.client.post(reverse("promotions:create"), {"sponsor": f"organization:{organization.pk}", "headline": "Batch", "body": "Classes.", "cta_label": "Go",
                                                        "upload": SimpleUploadedFile("square.png", buffer.getvalue(), content_type="image/png")})
        promotion = Promotion.objects.get()
        with Image.open(promotion.image.path) as image:
            self.assertEqual((image.format, image.size), ("JPEG", (1200, 628)))
        promotion.image.delete(save=False)
class FeedTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@sunrise.in", role="organization")
        self.organization = centre(self.owner, is_listed=True)
        self.member = make_user("asha@example.com", occupation="student", institution="COEP", skills="Python, SQL", location="Pune, India")
        User.objects.filter(pk=self.member.pk).update(date_joined=timezone.now() - timedelta(days=30))
        watched(self.member)
        public_activity()
        self.client.force_login(self.member)
    def feed_promotions(self):
        page = self.client.get(reverse("landing:dashboard"))
        return [item["promotion"] for item in page.context["feed"] if item.get("sponsored")], page
    def test_an_empty_feed_shows_no_sponsored_post_and_counts_no_view(self):
        LearningPost.objects.all().delete()
        promotion = live_post(self.owner, self.organization)
        self.assertEqual(self.feed_promotions()[0], [])
        promotion.refresh_from_db()
        self.assertEqual(promotion.views, 0)
    def test_a_matching_post_shows_in_the_feed_and_counts_a_view(self):
        promotion = live_post(self.owner, self.organization, audiences=["watching"], skills="Python", city="Pune")
        shown, page = self.feed_promotions()
        self.assertEqual(shown, [promotion])
        self.assertContains(page, "Sponsored · Coaching centre or institute")
        self.assertContains(page, "Shown to people exploring what to learn and people interested in Python.")
        promotion.refresh_from_db()
        self.assertEqual(promotion.views, 1)
        self.assertEqual(PromotionView.objects.get(promotion=promotion, user=self.member).count, 1)
    def test_targeting_leaves_out_people_it_wasnt_meant_for(self):
        for fields in [{"audiences": ["building"]}, {"skills": "Java"}, {"city": "Chennai"}, {"audiences": ["professionals"]}]:
            live_post(self.owner, self.organization, **fields)
        live_post(self.owner, self.organization, status="pending", headline="Not approved")
        live_post(self.owner, self.organization, ends_on=timezone.localdate() - timedelta(days=1), headline="Finished")
        live_post(self.owner, self.organization, max_views=5, views=5, headline="Used up")
        self.assertEqual(self.feed_promotions()[0], [])
    def test_a_post_appears_at_most_three_times_a_day(self):
        live_post(self.owner, self.organization)
        for _ in range(services.DAILY_CAP):
            self.assertEqual(len(self.feed_promotions()[0]), 1)
        self.assertEqual(self.feed_promotions()[0], [])
    def test_no_ads_for_your_own_centre_or_your_own_post(self):
        live_post(self.owner, self.organization)
        Membership.objects.create(organization=self.organization, user=self.member, role="student", status="active")
        self.assertEqual(self.feed_promotions()[0], [])
        from apps.guidance.services import activity_summary
        self.assertEqual(services.for_feed(self.owner, activity_summary(self.owner)), [])
    def test_recruiter_posts_reach_members_who_are_not_in_any_centre_too(self):
        recruiter = make_user("talent@acme.com", role="recruiter", company_name="Acme", email_verified_at=timezone.now())
        other = make_user("other@sunrise.in", role="organization")
        centre(other, name="Other Centre", slug="other")
        Membership.objects.create(organization=Organization.objects.get(slug="other"), user=self.member, role="student", status="active")
        promotion = live_post(recruiter, None, sponsor_name="Acme", headline="We're hiring Python interns")
        self.assertEqual(self.feed_promotions()[0], [promotion])
    def test_clicking_opens_the_sponsor_page_and_counts(self):
        promotion = live_post(self.owner, self.organization)
        response = self.client.get(reverse("promotions:go", args=[promotion.pk]))
        self.assertRedirects(response, reverse("organizations:listing", args=["sunrise"]), fetch_redirect_response=False)
        promotion.refresh_from_db()
        self.assertEqual(promotion.clicks, 1)
        promotion.status = "paused"
        promotion.save()
        self.assertEqual(self.client.get(reverse("promotions:go", args=[promotion.pk])).status_code, 404)
    def test_hiding_and_reporting(self):
        promotion = live_post(self.owner, self.organization)
        response = self.client.post(reverse("promotions:hide", args=[promotion.pk]), {"reason": "not_interested"}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(response.json()["message"], "Hidden. You won't see this post again.")
        self.assertEqual(self.feed_promotions()[0], [])
        for number in range(services.REPORTS_TO_PAUSE - 1):
            PromotionHide.objects.create(promotion=promotion, user=make_user(f"r{number}@example.com"), reason="misleading")
        services.hide(promotion, make_user("last@example.com"), "offensive")  # the report that reaches the limit
        promotion.refresh_from_db()
        self.assertEqual(promotion.status, "paused")
        self.assertTrue(Notification.objects.filter(recipient=self.owner, text__contains="paused after reports").exists())
        # Resuming a post paused by reports sends it to staff first.
        self.client.force_login(self.owner)
        self.client.post(reverse("promotions:action", args=[promotion.pk]), {"action": "resume"})
        self.assertEqual(Promotion.objects.get(pk=promotion.pk).status, "pending")
class PlacementTests(TestCase):
    def test_slots(self):
        posts = [Promotion(pk=1), Promotion(pk=2)]
        feed = [{"key": str(number)} for number in range(15)]
        placed = services.place(feed, posts)
        self.assertEqual([index for index, item in enumerate(placed) if item.get("sponsored")], [3, 12])
        short = services.place([{"key": "a"}], posts[:services.room([{"key": "a"}])])
        self.assertEqual([item.get("sponsored", False) for item in short], [False, True])
        self.assertEqual(services.room([]), 0)
        self.assertEqual(services.room(feed), 2)
    def test_a_myprogress_suggestion_goes_first_and_sponsored_posts_move_down(self):
        house = {"key": "next-step:start_project", "next_step": True}
        feed = [{"key": str(number)} for number in range(15)]
        self.assertEqual(services.room(feed, house=True), 2)  # sponsors keep both slots
        placed = services.place(feed, [Promotion(pk=1), Promotion(pk=2)], house)
        self.assertEqual([index for index, item in enumerate(placed) if item.get("next_step")], [3])
        self.assertEqual([index for index, item in enumerate(placed) if item.get("sponsored")], [8, 17])  # after the 7th and 15th posts
        short = services.place([{"key": "a"}], [Promotion(pk=1)], house)
        self.assertEqual([item["key"] for item in short], ["a", "next-step:start_project", "sponsored:1"])
        self.assertEqual(services.place([], [], house), [])  # an empty feed shows it above the empty-feed message instead
