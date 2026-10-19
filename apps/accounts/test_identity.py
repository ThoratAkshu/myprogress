"""Who someone is: asked at sign-up for each account type, editable in channel settings, and searchable by recruiters."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Profile
from apps.organizations.models import Membership, Organization
from apps.recruiting.models import ContactRequest

PASSWORD = "StrongPass!482"


def sign_up(client, role, email, **answers):
    return client.post(reverse("landing:register_details", args=[role]), {"first_name": "Asha", "last_name": "Rao", "email": email, "password": PASSWORD, "terms": "1", **answers})


def make_user(email, role="developer", **profile):
    user = User.objects.create_user(username=email, email=email, password=PASSWORD, first_name="Asha", last_name="Rao")
    profile.setdefault("email_verified_at", timezone.now())  # so the reminder isn't behind the confirm-your-email one
    Profile.objects.create(user=user, role=role, handle=email.split("@")[0].replace(".", "-"), **profile)
    return user


class SignUpIdentityTests(TestCase):
    def setUp(self):
        cache.clear()  # sign-ups are rate limited
        self.addCleanup(cache.clear)

    def test_students_and_professionals_say_which_they_are(self):
        self.assertContains(sign_up(self.client, "developer", "nobody@example.com"), "Choose whether you&#x27;re a student or a working professional.")
        self.assertContains(sign_up(self.client, "developer", "nobody@example.com", occupation="student"), "Tell us your college or school.")
        self.assertContains(sign_up(self.client, "developer", "nobody@example.com", occupation="professional", company_name="Acme"), "Tell us what you do")
        self.assertFalse(User.objects.filter(email="nobody@example.com").exists())
        sign_up(self.client, "developer", "student@example.com", occupation="student", institution="  Pune   University ", graduation_year="2027", job_title="Ignored")
        student = Profile.objects.get(user__email="student@example.com")
        self.assertEqual((student.occupation, student.institution, student.graduation_year, student.job_title, student.headline), ("student", "Pune University", 2027, "", "Student at Pune University"))
        self.client.logout()
        sign_up(self.client, "developer", "pro@example.com", occupation="professional", job_title="Backend developer", company_name="Acme", institution="Ignored")
        professional = Profile.objects.get(user__email="pro@example.com")
        self.assertEqual((professional.occupation, professional.job_title, professional.company_name, professional.institution, professional.headline), ("professional", "Backend developer", "Acme", "", "Backend developer at Acme"))
        self.assertFalse(professional.needs_identity)

    def test_recruiters_name_their_company_and_sign_up_with_its_email(self):
        self.assertContains(sign_up(self.client, "recruiter", "hr@gmail.com", company_name="Acme"), "gmail.com is a personal email provider")
        self.assertContains(sign_up(self.client, "recruiter", "hr@mailinator.com", company_name="Acme"), "mailinator.com addresses are temporary")
        self.assertContains(sign_up(self.client, "recruiter", "hr@acme.io"), "Name the company you hire for.")
        self.assertContains(sign_up(self.client, "recruiter", "hr@acme.io", company_name="Acme", company_website="https://other.com"), "the company website should be on acme.io too")
        self.assertFalse(User.objects.filter(email__startswith="hr@").exists())
        sign_up(self.client, "recruiter", "hr@acme.io", company_name="Acme", job_title="Talent lead", company_website="https://careers.acme.io/jobs")
        recruiter = Profile.objects.get(user__email="hr@acme.io")
        self.assertEqual((recruiter.company_name, recruiter.company_website, recruiter.headline, recruiter.occupation), ("Acme", "https://careers.acme.io/jobs", "Talent lead at Acme", ""))

    def test_organizations_describe_themselves_and_start_with_their_institute(self):
        response = sign_up(self.client, "organization", "office@gmail.com", organization_kind="institute")
        for message in ["Give your organization&#x27;s name.", "Tell students what you teach and who it&#x27;s for."]:
            self.assertContains(response, message)
        self.assertContains(response, '<fieldset class="signup-details"><legend>Your organization')  # the same form again after an error
        sign_up(self.client, "organization", "office@gmail.com", organization_name="Sunrise Coding Institute", organization_kind="institute", organization_city="Pune", organization_about="Full-stack batches for college students")
        organization = Organization.objects.get()
        self.assertEqual((organization.name, organization.kind, organization.city, organization.about, organization.owner.email), ("Sunrise Coding Institute", "institute", "Pune", "Full-stack batches for college students", "office@gmail.com"))
        self.assertTrue(Membership.objects.filter(organization=organization, user=organization.owner, role="owner").exists())
        self.assertFalse(organization.owner.profile.needs_identity)
        self.assertNotContains(self.client.get(reverse("organizations:overview", args=[organization.slug])), "Tell people who you are")

    def test_the_account_type_comes_first_then_its_own_form(self):
        page = self.client.get(reverse("landing:register"), {"next": "/org/join/abc/"})
        self.assertContains(page, "Step 1 of 2")
        for account in ["developer", "recruiter", "organization"]:
            self.assertContains(page, f'href="/register/{account}/?next=/org/join/abc/"')
        self.assertNotContains(page, "<form")  # no form until the type is chosen
        page = self.client.get(reverse("landing:register_details", args=["developer"]), {"next": "/org/join/abc/"})
        self.assertContains(page, "Step 2 of 2")
        self.assertContains(page, "<strong>Student or professional</strong>")
        self.assertContains(page, '<fieldset class="signup-details"><legend>About you')
        self.assertNotContains(page, "Your company")
        self.assertNotContains(page, "Your organization")
        self.assertContains(page, '<input type="hidden" name="next" value="/org/join/abc/">')
        page = self.client.get(reverse("landing:register_details", args=["organization"]))
        self.assertContains(page, "<legend>Your organization")
        self.assertNotContains(page, "About you")
        self.assertRedirects(self.client.get(reverse("landing:register_details", args=["wizard"])), reverse("landing:register"))
        page = sign_up(self.client, "recruiter", "hr@gmail.com", company_name="Acme")
        self.assertContains(page, '<fieldset class="signup-details"><legend>Your company')
        self.assertContains(page, 'value="Acme"')
        self.assertContains(page, "Work email")
        response = self.client.post(reverse("landing:register_details", args=["developer"]), {"first_name": "Mallory", "last_name": "X", "email": "m@example.com", "password": PASSWORD,
                                                                                              "role": "organization", "occupation": "student", "institution": "Pune University", "terms": "1"})
        self.assertRedirects(response, reverse("landing:dashboard"), fetch_redirect_response=False)
        self.assertEqual(User.objects.get(email="m@example.com").profile.role, "developer")  # the type comes from step 1, not the posted form


class LaterIdentityTests(TestCase):
    """Accounts made before sign-up asked are reminded, and anyone can change their answers in channel settings."""
    def save(self, user, **answers):
        self.client.force_login(user)
        return self.client.post(reverse("landing:channel_settings"), {"channel_name": "", "headline": "", "bio": "", "location": "", "brand_color": "ocean", **answers})

    def test_older_accounts_are_reminded_until_they_answer(self):
        developer = make_user("dev@example.com")
        self.client.force_login(developer)
        self.assertContains(self.client.get(reverse("landing:dashboard")), "Tell people who you are")
        page = self.client.get(reverse("landing:channel_settings"))
        self.assertContains(page, "Who you are")
        self.assertNotContains(page, "Tell people who you are")
        self.assertContains(self.save(developer), "Choose whether you")
        self.save(developer, occupation="student", institution="Pune University", graduation_year="2027")
        self.save(developer, occupation="professional", job_title="Data analyst", institution="Pune University")  # switching clears the student answers
        profile = Profile.objects.get(user=developer)
        self.assertEqual((profile.occupation, profile.job_title, profile.institution, profile.graduation_year), ("professional", "Data analyst", "", None))
        self.assertNotContains(self.client.get(reverse("landing:dashboard")), "Tell people who you are")

    def test_the_reminder_can_be_closed_until_the_next_sign_in(self):
        self.client.force_login(make_user("later@example.com"))
        self.client.post(reverse("landing:dismiss_verify_banner"), {"banner": "identity"})
        self.assertNotContains(self.client.get(reverse("landing:dashboard")), "Tell people who you are")

    def test_recruiters_keep_their_website_on_their_email_domain(self):
        recruiter = make_user("hr@acme.io", role="recruiter")
        self.client.force_login(recruiter)
        self.assertContains(self.client.get(reverse("recruiting:search")), "Add the company you hire for")
        self.assertContains(self.save(recruiter, company_name="Acme", company_website="https://other.com"), "should be on acme.io too")
        self.save(recruiter, company_name="Acme", company_website="https://acme.io")
        self.assertEqual(Profile.objects.get(user=recruiter).company_name, "Acme")


class TalentStageTests(TestCase):
    def test_recruiters_filter_for_students_or_professionals(self):
        make_user("student@example.com", occupation="student", institution="Pune University", headline="Student at Pune University")
        make_user("pro@example.com", occupation="professional", job_title="SRE", headline="SRE at Acme")
        self.client.force_login(make_user("hr@acme.io", role="recruiter", company_name="Acme"))
        url = reverse("recruiting:search")
        for stage, shown, hidden in [("student", "Student at Pune University", "SRE at Acme"), ("professional", "SRE at Acme", "Student at Pune University")]:
            page = self.client.get(url, {"stage": stage})
            self.assertContains(page, shown)
            self.assertNotContains(page, hidden)
        page = self.client.get(url)
        for headline in ["Student at Pune University", "SRE at Acme"]:
            self.assertContains(page, headline)

    def test_developers_see_which_company_is_contacting_them(self):
        developer = make_user("student@example.com", occupation="student", institution="Pune University")
        recruiter = make_user("hr@acme.io", role="recruiter", company_name="Acme", job_title="Talent lead", headline="Hiring for everything")
        ContactRequest.objects.create(recruiter=recruiter, developer=developer, role_title="Backend Engineer", message="Your API project stood out.")
        self.client.force_login(developer)
        page = self.client.get(reverse("landing:workspace_section", args=["learning"]) + "?tab=network&view=requests")
        self.assertContains(page, "Asha Rao · Talent lead at Acme")
