"""Edit profile, for every account type, and changing the sign-in email or password in Security."""
import os
import re
import shutil
import tempfile
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image
from apps.accounts.models import Profile
from apps.core.models import AuditEvent
from apps.organizations import services
from apps.organizations.models import Organization
from .test_channel import picture

MEDIA = tempfile.mkdtemp()
PASSWORD = "StrongPass!482"


def make_user(email, role="developer", **profile):
    user = User.objects.create_user(username=email, email=email, password=PASSWORD, first_name="Asha", last_name="Rao")
    Profile.objects.create(user=user, role=role, handle=email.split("@")[0].replace(".", "-"), **profile)
    return user


def link_in(message, name):
    path = re.search(r"http://testserver(/account/email/" + name + r"/[^\s]+/)", message.body)
    return path.group(1)


@override_settings(MEDIA_ROOT=MEDIA)
class EditProfileTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.student = make_user("asha@example.com", occupation="student", institution="Pune University")
        self.recruiter = make_user("hr@acme.io", role="recruiter", company_name="Acme")
        self.office = make_user("office@sunrise.example", role="organization")
        self.institute = services.create_organization(self.office, {"name": "Sunrise Coding Institute", "kind": "institute", "city": "Pune", "about": "Full-stack batches", "website": "", "join_requires_approval": False})

    def edit(self, user, **data):
        self.client.force_login(user)
        return self.client.post(reverse("landing:update_profile"), {"first_name": user.first_name, "handle": user.profile.handle, **data})

    def test_each_account_type_gets_its_own_questions(self):
        everyone = ['name="first_name"', 'name="last_name"', 'name="handle"', 'name="headline"', 'name="bio"', 'name="avatar"', 'name="link_github"', 'name="show_email"', reverse("landing:security")]
        pages = {}
        for user in [self.student, self.recruiter, self.office]:
            self.client.force_login(user)
            pages[user.profile.role] = page = self.client.get(reverse("landing:update_profile"))
            for field in everyone:
                self.assertContains(page, field)
        for field in ['name="occupation"', 'name="institution"', 'name="skills"', 'name="recruiter_visible"', 'name="location"']:
            self.assertContains(pages["developer"], field)
        self.assertNotContains(pages["developer"], 'name="org-name"')
        for field in ['name="company_name"', 'name="company_website"', 'name="location"']:
            self.assertContains(pages["recruiter"], field)
        for field in ['name="skills"', 'name="recruiter_visible"', 'name="occupation"']:
            self.assertNotContains(pages["recruiter"], field)
        for text in ['name="org-name"', 'value="Sunrise Coding Institute"', 'name="org-kind"', 'name="org-about"', "Channel description", "Your institute"]:
            self.assertContains(pages["organization"], text)
        for field in ['name="location"', 'name="skills"', 'name="occupation"', 'name="company_name"']:
            self.assertNotContains(pages["organization"], field)

    def test_every_account_type_finds_it_under_me(self):
        for user in [self.student, self.recruiter, self.office]:
            self.client.force_login(user)
            page = self.client.get(reverse("landing:public_profile", args=[user.profile.handle]))
            self.assertContains(page, f'href="{reverse("landing:update_profile")}"', count=2)  # the Me menu and the button on their own page

    def test_a_student_edits_every_detail(self):
        response = self.edit(self.student, first_name="Asha", last_name="Kulkarni", handle="asha-k", headline="Student at Pune University", location="Pune, India", bio="I build small APIs.",
                             skills="Python, Django, python", occupation="student", institution="COEP", graduation_year="2027", show_email="on",
                             link_github="https://github.com/asha", avatar=picture((600, 600)))
        self.assertRedirects(response, reverse("landing:public_profile", args=["asha-k"]))
        user = User.objects.get(pk=self.student.pk)
        profile = user.profile
        self.assertEqual((user.first_name, user.last_name), ("Asha", "Kulkarni"))
        self.assertEqual((profile.handle, profile.headline, profile.location, profile.bio), ("asha-k", "Student at Pune University", "Pune, India", "I build small APIs."))
        self.assertEqual((profile.skills, profile.institution, profile.graduation_year), ("Python, Django, python", "COEP", 2027))
        self.assertEqual((profile.show_email, profile.recruiter_visible, profile.links), (True, False, {"github": "https://github.com/asha"}))
        with Image.open(profile.avatar.path) as photo:
            self.assertEqual((photo.format, photo.size), ("PNG", (400, 400)))
        page = self.client.get(reverse("landing:public_profile", args=["asha-k"]))
        self.assertContains(page, "Asha Kulkarni")
        self.assertContains(page, "Student at Pune University")
        old_photo = profile.avatar.path
        self.edit(User.objects.get(pk=self.student.pk), occupation="student", institution="COEP", remove_logo="on")
        self.assertEqual(Profile.objects.get(pk=profile.pk).avatar.name, "")
        self.assertFalse(os.path.exists(old_photo))

    def test_a_recruiter_edits_the_company_but_not_developer_settings(self):
        response = self.edit(self.recruiter, company_name="Acme Labs", job_title="Talent lead", company_website="https://careers.acme.io", headline="Hiring in Pune", skills="Hacking", recruiter_visible="on")
        self.assertRedirects(response, reverse("landing:public_profile", args=[self.recruiter.profile.handle]))
        profile = Profile.objects.get(user=self.recruiter)
        self.assertEqual((profile.company_name, profile.job_title, profile.company_website, profile.headline, profile.skills), ("Acme Labs", "Talent lead", "https://careers.acme.io", "Hiring in Pune", ""))
        self.assertContains(self.edit(self.recruiter, company_name=""), "Name the company you hire for.")

    def test_an_organization_edits_its_institute_and_channel(self):
        slug = self.institute.slug
        response = self.edit(self.office, first_name="Meera", headline="Coding classes in Pune", bio="Weekend batches.", location="Mumbai",
                             **{"org-name": "Sunrise Academy", "org-kind": "bootcamp", "org-city": "Nashik", "org-website": "https://sunrise.example", "org-about": "Python and web batches."})
        self.assertRedirects(response, reverse("landing:public_profile", args=[self.office.profile.handle]))
        institute = Organization.objects.get(pk=self.institute.pk)
        self.assertEqual((institute.name, institute.kind, institute.city, institute.website, institute.about, institute.slug), ("Sunrise Academy", "bootcamp", "Nashik", "https://sunrise.example", "Python and web batches.", slug))
        profile = Profile.objects.get(user=self.office)
        self.assertEqual((profile.headline, profile.bio, profile.location, User.objects.get(pk=self.office.pk).first_name), ("Coding classes in Pune", "Weekend batches.", "", "Meera"))
        response = self.edit(self.office, headline="Changed", **{"org-name": "", "org-kind": "bootcamp"})
        self.assertContains(response, "This field is required.")
        self.assertEqual(Profile.objects.get(user=self.office).headline, "Coding classes in Pune")  # nothing is saved while either part has a mistake

    def test_mistakes_are_shown_and_nothing_is_saved(self):
        response = self.edit(self.student, first_name="", handle=self.office.profile.handle, headline="Changed", bio="x" * 2001, occupation="student", institution="COEP")
        for error in ["That address is already taken.", "This field is required.", "Ensure this value has at most 2000 characters"]:
            self.assertContains(response, error)
        self.assertContains(response, f'href="{reverse("landing:public_profile", args=["asha"])}"')  # links still use the saved address
        profile = Profile.objects.get(user=self.student)
        self.assertEqual((profile.handle, profile.headline, profile.institution, User.objects.get(pk=self.student.pk).first_name), ("asha", "", "Pune University", "Asha"))
        self.assertContains(self.edit(self.student, handle="ab", occupation="student", institution="COEP"), "Use at least 3 characters.")
        self.assertRedirects(self.edit(self.recruiter, headline="Hiring", company_name="Acme"), reverse("landing:public_profile", args=["hr"]))  # an older, shorter address can stay

    def test_the_account_type_and_score_never_change_here(self):
        self.edit(self.student, occupation="student", institution="COEP", role="organization", score="999", email_verified_at="2026-01-01", **{"org-name": "Mine", "org-kind": "institute"})
        profile = Profile.objects.get(user=self.student)
        self.assertEqual((profile.role, profile.email_verified_at), ("developer", None))
        self.assertNotEqual(profile.score, 999)
        self.assertFalse(Organization.objects.filter(name="Mine").exists())


class EmailChangeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = make_user("asha@example.com")
        self.client.force_login(self.user)

    def ask(self, email, password=PASSWORD):
        return self.client.post(reverse("landing:security"), {"action": "email", "email": email, "password": password})

    def test_the_new_email_only_takes_effect_from_the_link_sent_to_it(self):
        response = self.ask("Asha.Rao@Example.org")
        self.assertRedirects(response, reverse("landing:security") + "#email", fetch_redirect_response=False)
        self.assertEqual((len(mail.outbox), mail.outbox[0].to), (1, ["asha.rao@example.org"]))
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "asha@example.com")
        self.client.logout()  # the link works from any browser, like the phone the email is read on
        self.client.get(link_in(mail.outbox[0], "confirm"))
        user = User.objects.get(pk=self.user.pk)
        self.assertEqual((user.email, user.username), ("asha.rao@example.org", "asha.rao@example.org"))
        self.assertIsNotNone(user.profile.email_verified_at)
        self.assertEqual(authenticate(username="asha.rao@example.org", password=PASSWORD), user)
        self.assertIsNone(authenticate(username="asha@example.com", password=PASSWORD))
        notice = mail.outbox[1]
        self.assertEqual(notice.to, ["asha@example.com"])
        self.assertIn("/account/email/undo/", notice.body)
        self.assertEqual(list(AuditEvent.objects.filter(user=user).values_list("action", flat=True).order_by("pk")), ["account.email_requested", "account.email"])

    def test_wrong_password_taken_and_throwaway_emails_are_refused(self):
        make_user("taken@example.com")
        for email, password, error in [("new@example.org", "wrong", "Your password isn&#x27;t right."), ("TAKEN@example.com", PASSWORD, "An account with this email already exists."),
                                       ("me@mailinator.com", PASSWORD, "addresses are temporary"), ("asha@example.com", PASSWORD, "That&#x27;s already your email.")]:
            self.assertContains(self.ask(email, password), error)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_link_stops_working_once_it_no_longer_applies(self):
        self.ask("first@example.org")
        self.ask("second@example.org")
        first, second = link_in(mail.outbox[0], "confirm"), link_in(mail.outbox[1], "confirm")
        self.client.get(second)
        self.client.get(first)  # made for the old email, so it does nothing now
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "second@example.org")
        self.ask("third@example.org", PASSWORD)
        self.client.post(reverse("landing:security"), {"action": "password", "old_password": PASSWORD, "new_password1": "Another!Pass93", "new_password2": "Another!Pass93"})
        self.client.get(link_in(mail.outbox[-2], "confirm"))  # asked before the password changed
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "second@example.org")

    def test_recruiters_keep_a_work_email_and_their_website_follows_it(self):
        recruiter = make_user("hr@acme.io", role="recruiter", company_name="Acme", company_website="https://acme.io")
        self.client.force_login(recruiter)
        self.assertContains(self.ask("hr@gmail.com"), "Recruiters sign up with their work email")
        self.ask("hr@newco.io")
        response = self.client.get(link_in(mail.outbox[0], "confirm"), follow=True)
        self.assertContains(response, "Your company website was on another domain, so it was removed")
        profile = Profile.objects.get(user=recruiter)
        self.assertEqual((profile.user.email, profile.company_website), ("hr@newco.io", ""))
        self.assertTrue(profile.is_verified_recruiter)

    def test_the_old_address_can_undo_the_change(self):
        self.ask("intruder@example.org")
        confirm = link_in(mail.outbox[0], "confirm")
        self.client.get(confirm)
        undo = link_in(mail.outbox[1], "undo")
        owner = Client()
        page = owner.get(undo)  # mail scanners open links: opening it only asks
        self.assertContains(page, "Put asha@example.com back")
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "intruder@example.org")
        self.assertRedirects(owner.post(undo), reverse("landing:password_reset"))
        user = User.objects.get(pk=self.user.pk)
        self.assertEqual((user.email, user.username, user.has_usable_password()), ("asha@example.com", "asha@example.com", False))
        self.assertEqual(self.client.get(reverse("landing:security")).status_code, 302)  # signed out everywhere
        self.assertNotIn("_auth_user_id", self.client.session)
        self.client.get(confirm)  # the first link can't redo the change
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "asha@example.com")
        owner.post(undo)
        self.assertEqual(AuditEvent.objects.filter(user=user, text__startswith="put the sign-in email back").count(), 1)


class PasswordChangeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = make_user("asha@example.com")

    def change(self, client, old, new, again=None):
        return client.post(reverse("landing:security"), {"action": "password", "old_password": old, "new_password1": new, "new_password2": again or new})

    def test_changing_it_keeps_this_device_and_signs_out_the_others(self):
        laptop, phone = Client(), Client()
        for client in [laptop, phone]:
            client.force_login(self.user)
        self.assertRedirects(self.change(laptop, PASSWORD, "Brand!New42pass"), reverse("landing:security") + "#password", fetch_redirect_response=False)
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password("Brand!New42pass"))
        self.assertEqual(laptop.get(reverse("landing:security")).status_code, 200)
        self.assertEqual(phone.get(reverse("landing:security")).status_code, 302)
        self.assertTrue(AuditEvent.objects.filter(user=self.user, action="account.password").exists())
        self.assertEqual((mail.outbox[0].to, mail.outbox[0].subject), (["asha@example.com"], "Your MyProgress password was changed"))

    def test_mistakes_are_explained(self):
        self.client.force_login(self.user)
        self.assertContains(self.change(self.client, "wrong", "Brand!New42pass"), "Your current password isn&#x27;t right.")
        self.assertContains(self.change(self.client, PASSWORD, "Brand!New42pass", "Brand!New42pasz"), "The two new passwords don&#x27;t match.")
        self.assertContains(self.change(self.client, PASSWORD, "73829104"), "This password is entirely numeric.")
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(PASSWORD))
