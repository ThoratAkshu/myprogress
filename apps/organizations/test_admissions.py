from datetime import timedelta
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Profile
from apps.notifications.models import Notification
from . import admissions
from .models import Batch, Enquiry, Membership, Organization
def make_user(email, role="developer", **profile):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=email.split("@")[0].title(), last_name="Test")
    Profile.objects.create(user=user, handle=email.replace("@", "-").replace(".", "-"), role=role, **profile)
    return user
def centre(name, slug, **fields):
    owner = make_user(f"owner@{slug}.in", role="organization")
    organization = Organization.objects.create(owner=owner, name=name, slug=slug, **fields)
    Membership.objects.create(organization=organization, user=owner, role="owner", status="active")
    return organization
def listed_class(organization, title, **fields):
    defaults = {"course": "Python", "schedule": "Sat and Sun, 10 am – 1 pm", "mode": "centre"}
    return Batch.objects.create(organization=organization, title=title, **{**defaults, **fields})
class ClassSearchTests(TestCase):
    def setUp(self):
        self.pune = centre("Sunrise Coding", "sunrise", is_listed=True, city="Pune", area="Kothrud", pincode="411038", address="Lane 5, Karve Road", contact_phone="+91 98765 43210")
        self.mumbai = centre("Bay Data Academy", "bay", is_listed=True, city="Mumbai", area="Andheri")
        self.hidden = centre("Private Institute", "private", is_listed=False, city="Pune")
        self.weekend = listed_class(self.pune, "Python for beginners, weekend batch", fee=12000, starts_on=timezone.localdate() + timedelta(days=10), duration="3 months")
        self.online = listed_class(self.mumbai, "SQL from zero, online", course="SQL", mode="online", fee=4500, fee_period="month")
        self.andheri = listed_class(self.mumbai, "Data science evenings", course="Data science")
        self.closed = listed_class(self.pune, "Full batch", is_open=False)
        self.secret = listed_class(self.hidden, "Hidden class")
    def titles(self, **params):
        page = self.client.get(reverse("organizations:find"), params)
        return [batch.title for batch in page.context["page"].object_list]
    def test_only_open_classes_at_listed_centres_are_searchable(self):
        self.assertEqual(sorted(self.titles(city="")), sorted([self.weekend.title, self.online.title, self.andheri.title]))
        self.assertEqual(self.titles(city="", q="sql"), [self.online.title])
        self.assertEqual(self.titles(city="", q="sunrise"), [self.weekend.title])  # the centre's name finds its classes too
    def test_a_city_keeps_its_own_classes_first_and_online_ones_after(self):
        self.assertEqual(self.titles(city="Pune"), [self.weekend.title, self.online.title])
        self.assertEqual(self.titles(city="Pune", mode="centre"), [self.weekend.title])
        self.assertEqual(self.titles(city="Pune", mode="online"), [self.online.title])
        self.assertEqual(self.titles(city="", area="Kothrud", mode="centre"), [self.weekend.title])
        self.assertEqual(self.titles(city="", area="411038", mode="centre"), [self.weekend.title])  # a PIN code works as the area
        self.assertEqual(self.titles(city="Mumbai", area="Andheri", mode="centre"), [self.andheri.title])
    def test_a_class_held_elsewhere_is_found_where_it_is_held(self):
        branch = listed_class(self.pune, "Python at the Mumbai branch", city="Mumbai", area="Dadar")
        self.assertIn(branch.title, self.titles(city="Mumbai", mode="centre"))
        self.assertNotIn(branch.title, self.titles(city="Pune", mode="centre"))
    def test_the_first_search_uses_the_members_own_city(self):
        student = make_user("asha@example.com", location="Pune, India")
        self.client.force_login(student)
        page = self.client.get(reverse("organizations:find"))
        self.assertEqual(page.context["city"], "Pune")
        self.assertContains(page, "where you live")
        self.assertEqual(len(self.titles(city="")), 3)  # choosing Any city shows everything
    def test_the_class_page_has_the_details(self):
        page = self.client.get(reverse("organizations:batch", args=[self.weekend.pk]))
        self.assertContains(page, "Python for beginners, weekend batch")
        self.assertContains(page, "₹12,000")
        self.assertContains(page, "Sat and Sun, 10 am – 1 pm")
        self.assertContains(page, "Kothrud, Pune")
        self.assertContains(page, "+91 98765 43210")
        self.assertContains(page, "https://www.google.com/maps/search/?api=1&amp;query=")
        self.assertContains(page, "Create a free account to ask")
        self.assertContains(self.client.get(reverse("organizations:batch", args=[self.online.pk])), "₹4,500 a month")
        self.assertEqual(self.client.get(reverse("organizations:batch", args=[self.secret.pk])).status_code, 404)
    def test_the_centre_page_lists_its_open_classes_and_contact_details(self):
        page = self.client.get(reverse("organizations:listing", args=["sunrise"]))
        self.assertContains(page, self.weekend.title)
        self.assertNotContains(page, "Full batch")
        self.assertContains(page, "Lane 5, Karve Road, Kothrud, Pune 411038")
        self.assertContains(page, "Open in Google Maps")
    def test_old_invite_code_links_still_open_the_join_page(self):
        response = self.client.get(reverse("organizations:find"), {"code": self.hidden.invite_code})
        self.assertRedirects(response, reverse("organizations:join", args=[self.hidden.invite_code]), fetch_redirect_response=False)
    def test_rupees_use_indian_grouping(self):
        from .templatetags.org_tags import rupees
        self.assertEqual([rupees(value) for value in [999, 12000, 120000, 1200000]], ["₹999", "₹12,000", "₹1,20,000", "₹12,00,000"])
class EnquiryTests(TestCase):
    def setUp(self):
        self.organization = centre("Sunrise Coding", "sunrise", is_listed=True, city="Pune")
        self.teacher = make_user("teacher@sunrise.in")
        Membership.objects.create(organization=self.organization, user=self.teacher, role="teacher", status="active")
        self.batch = listed_class(self.organization, "Python for beginners")
        self.student = make_user("asha@example.com")
        self.url = reverse("organizations:enquire", args=["sunrise"])
    def send(self, message="Is there a batch for beginners next month?", **extra):
        return self.client.post(self.url, {"message": message, "batch": self.batch.pk, **extra})
    def test_a_student_asks_about_a_class_and_the_teachers_are_told(self):
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse("organizations:batch", args=[self.batch.pk])), "Send enquiry")
        response = self.send(phone="98765 43210")
        enquiry = Enquiry.objects.get(student=self.student)
        self.assertRedirects(response, reverse("organizations:my_enquiry", args=[enquiry.pk]))
        self.assertEqual((enquiry.batch, enquiry.phone, enquiry.status), (self.batch, "98765 43210", "new"))
        self.assertEqual(enquiry.messages.get().text, "Is there a batch for beginners next month?")
        for teacher in (self.organization.owner, self.teacher):
            self.assertTrue(Notification.objects.filter(recipient=teacher, text__contains="asked about Python for beginners").exists())
        # Asking again about the same class adds to the same conversation.
        self.send("Also, are classes in English?")
        self.assertEqual(Enquiry.objects.filter(student=self.student).count(), 1)
        self.assertEqual(enquiry.messages.count(), 2)
        page = self.client.get(reverse("organizations:batch", args=[self.batch.pk]))
        self.assertContains(page, "See the conversation")
    def test_a_general_enquiry_from_the_centre_page(self):
        self.client.force_login(self.student)
        self.client.post(self.url, {"message": "Do you teach Java on weekdays?"})
        self.assertEqual(Enquiry.objects.get(student=self.student).topic, "General enquiry")
    def test_bad_input_shows_on_the_form(self):
        self.client.force_login(self.student)
        page = self.send(phone="call me")
        self.assertContains(page, "Enter a phone number")
        self.assertContains(self.send(message="Hi"), "Ensure this value has at least 10 characters")
        self.assertFalse(Enquiry.objects.exists())
    def test_closed_classes_and_the_daily_limit_are_refused(self):
        self.client.force_login(self.student)
        Batch.objects.filter(pk=self.batch.pk).update(is_open=False)
        self.send()
        self.assertFalse(Enquiry.objects.exists())
        Batch.objects.filter(pk=self.batch.pk).update(is_open=True)
        for number in range(admissions.ENQUIRIES_PER_DAY):
            other = listed_class(self.organization, f"Class {number}")
            self.client.post(self.url, {"message": "Is there a seat left in this one?", "batch": other.pk})
        self.assertEqual(Enquiry.objects.count(), admissions.ENQUIRIES_PER_DAY)
        response = self.client.post(self.url, {"message": "One more question for you", "batch": self.batch.pk}, follow=True)
        self.assertContains(response, "up to 10 new enquiries a day")
        self.assertEqual(Enquiry.objects.count(), admissions.ENQUIRIES_PER_DAY)
    def test_teachers_recruiters_and_visitors_cannot_send(self):
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse("organizations:batch", args=[self.batch.pk])), "arrive in")
        self.send()
        self.assertFalse(Enquiry.objects.exists())
        self.client.force_login(make_user("hr@acme.com", role="recruiter"))
        self.assertEqual(self.send().status_code, 403)
        self.client.logout()
        self.assertEqual(self.send().status_code, 302)
        self.assertFalse(Enquiry.objects.exists())
    def test_students_only_see_their_own_enquiries(self):
        self.client.force_login(self.student)
        self.send()
        enquiry = Enquiry.objects.get()
        self.client.force_login(make_user("other@example.com"))
        self.assertEqual(self.client.get(reverse("organizations:my_enquiry", args=[enquiry.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("organizations:my_enquiries")), "Python for beginners")
class AdmissionsTests(TestCase):
    def setUp(self):
        self.organization = centre("Sunrise Coding", "sunrise", is_listed=True, city="Pune")
        self.owner = self.organization.owner
        self.batch = listed_class(self.organization, "Python for beginners")
        self.student = make_user("asha@example.com", location="Pune, India")
        self.enquiry, _ = admissions.send_enquiry(self.organization, self.student, "When does the next batch start?", self.batch, "98765 43210")
    def test_the_centre_answers_and_the_student_sees_the_reply(self):
        self.client.force_login(self.owner)
        inbox = self.client.get(reverse("organizations:admissions", args=["sunrise"]))
        self.assertContains(inbox, "When does the next batch start?")
        self.assertEqual(inbox.context["admissions_unread"], 1)
        url = reverse("organizations:enquiry", args=["sunrise", self.enquiry.pk])
        page = self.client.get(url)
        self.assertContains(page, "98765 43210")
        self.assertEqual(admissions.unread_for_centre(self.organization), 0)  # opening it reads it
        self.client.post(url, {"action": "reply", "text": "On 5 November. Come for a free demo class on Saturday."})
        self.enquiry.refresh_from_db()
        self.assertEqual(self.enquiry.status, "replied")
        self.assertTrue(Notification.objects.filter(recipient=self.student, text__contains="Sunrise Coding replied").exists())
        self.client.force_login(self.student)
        self.assertEqual(admissions.unread_for_student(self.student), 1)
        self.assertContains(self.client.get(reverse("organizations:my_enquiries")), "Come for a free demo class")
        thread = self.client.get(reverse("organizations:my_enquiry", args=[self.enquiry.pk]))
        self.assertContains(thread, "Come for a free demo class on Saturday.")
        self.assertEqual(admissions.unread_for_student(self.student), 0)
        self.client.post(reverse("organizations:my_enquiry", args=[self.enquiry.pk]), {"text": "Great, see you on Saturday."})
        self.assertTrue(Notification.objects.filter(recipient=self.owner, text__contains="wrote again").exists())
    def test_sending_the_invite_link_and_closing(self):
        self.client.force_login(self.owner)
        url = reverse("organizations:enquiry", args=["sunrise", self.enquiry.pk])
        self.client.post(url, {"action": "invite"})
        self.assertIn(reverse("organizations:join", args=[self.organization.invite_code]), self.enquiry.messages.last().text)
        self.client.post(url, {"action": "status", "status": "closed"})
        self.enquiry.refresh_from_db()
        self.assertEqual(self.enquiry.status, "closed")
        self.assertNotContains(self.client.get(reverse("organizations:admissions", args=["sunrise"])), url)  # closed ones leave the Open list
        self.assertContains(self.client.get(reverse("organizations:admissions", args=["sunrise"]), {"show": "closed"}), url)
        self.client.force_login(self.student)
        self.client.post(reverse("organizations:my_enquiry", args=[self.enquiry.pk]), {"text": "Hello again"})
        self.assertEqual(self.enquiry.messages.filter(text="Hello again").count(), 0)
    def test_students_of_the_centre_cannot_open_admissions(self):
        Membership.objects.create(organization=self.organization, user=self.student, role="student", status="active")
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("organizations:admissions", args=["sunrise"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("organizations:batches", args=["sunrise"])).status_code, 404)
    def test_listing_editing_and_deleting_classes(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("organizations:batches", args=["sunrise"]), {
            "title": "  Web development,   evening batch ", "course": "Web development", "level": "beginner", "mode": "both", "schedule": "Mon to Fri, 7 pm – 9 pm",
            "starts_on": "2026-12-01", "duration": "6 months", "fee": "30000", "fee_period": "course", "seats": "25", "area": "", "city": "", "description": "", "is_open": "on",
        })
        self.assertRedirects(response, reverse("organizations:batches", args=["sunrise"]))
        created = Batch.objects.get(course="Web development")
        self.assertEqual((created.title, created.created_by, created.where_city), ("Web development, evening batch", self.owner, "Pune"))
        edit = reverse("organizations:batch_edit", args=["sunrise", created.pk])
        self.client.post(edit, {"title": created.title, "course": "Web development", "level": "beginner", "mode": "both", "schedule": "Mon to Fri, 7 pm – 9 pm", "fee_period": "course"})
        created.refresh_from_db()
        self.assertFalse(created.is_open)  # unticked: no longer taking enquiries
        self.client.post(edit, {"action": "delete"})
        self.assertFalse(Batch.objects.filter(pk=created.pk).exists())
        # A class students asked about can't be deleted, so its conversations keep their class.
        self.client.post(reverse("organizations:batch_edit", args=["sunrise", self.batch.pk]), {"action": "delete"})
        self.assertTrue(Batch.objects.filter(pk=self.batch.pk).exists())
    def test_centre_details_in_settings_and_edit_profile(self):
        self.client.force_login(self.owner)
        settings_url = reverse("organizations:settings", args=["sunrise"])
        data = {"name": "Sunrise Coding", "kind": "institute", "city": "Pune", "area": "Kothrud", "address": "Lane 5", "pincode": "4110", "contact_phone": "", "opening_hours": "", "website": "", "about": "", "is_listed": "on", "listing_pitch": "", "courses": ""}
        self.assertContains(self.client.post(settings_url, data), "Enter the 6-digit PIN code.")
        self.client.post(settings_url, {**data, "pincode": "411 038", "contact_phone": "+91 98765 43210", "opening_hours": "Mon–Sat, 8 am – 8 pm"})
        self.organization.refresh_from_db()
        self.assertEqual((self.organization.area, self.organization.pincode, self.organization.contact_phone), ("Kothrud", "411038", "+91 98765 43210"))
        profile_page = self.client.get(reverse("landing:update_profile"))
        for name in ["org-area", "org-address", "org-pincode", "org-contact_phone", "org-opening_hours"]:
            self.assertContains(profile_page, f'name="{name}"')
    def test_reserved_slugs(self):
        from .services import unique_slug
        self.assertEqual(unique_slug("Centres"), "centres-org")
        self.assertEqual(unique_slug("Enquiries"), "enquiries-org")
