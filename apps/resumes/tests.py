from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import Profile
from apps.core.models import ActivityEvent, LearningPost, Project, ProjectMilestone, Repository
from apps.organizations.models import Certificate, Organization
from apps.recruiting.models import ContactRequest, PortfolioView
from .models import ResumeSettings
def make_user(email, role="developer", **profile):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=email.split("@")[0].title(), last_name="Test")
    Profile.objects.create(user=user, handle=email.split("@")[0], role=role, **profile)
    return user
class ResumeTests(TestCase):
    def setUp(self):
        self.student = make_user("asha@example.com", headline="Backend developer in training", location="Pune, India", skills="Python, Django, SQL",
                                 occupation="student", institution="COEP", graduation_year=2027, links={"github": "https://github.com/asha"})
        self.public = Project.objects.create(owner=self.student, title="Budget API", summary="Tracks spending by category.", skills="Django, REST", status="complete")
        repository = Repository.objects.create(project=self.public, owner=self.student, slug="budget-api", visibility="public", languages={"Python": 9000, "HTML": 1000})
        ProjectMilestone.objects.create(project=self.public, title="Build the core", is_complete=True)
        ProjectMilestone.objects.create(project=self.public, title="Publish a demo")
        ActivityEvent.objects.create(user=self.student, event_type="project", action="pushed_commits", metadata={"repository_id": repository.pk, "commits": 12})
        self.private = Project.objects.create(owner=self.student, title="Secret side project", is_public=False)
        owner = make_user("owner@sunrise.in", role="organization")
        organization = Organization.objects.create(owner=owner, name="Sunrise Coding", slug="sunrise")
        Certificate.objects.create(organization=organization, student=self.student, title="Python foundations")
        LearningPost.objects.create(author=self.student, title="How I built Budget API", kind="article", body="Notes", is_public=True)
        self.recruiter = make_user("hr@acme.com", role="recruiter", company_name="Acme")
    def test_a_student_makes_their_resume_from_their_work(self):
        self.client.force_login(self.student)
        page = self.client.get(reverse("resumes:mine"))
        for text in ["Asha Test", "Backend developer in training", "COEP", "Class of 2027", "Budget API", "12 commits", "1 of 2 milestones done",
                     "Python foundations", "How I built Budget API", "Student at COEP, graduating in 2027.", "asha@example.com", "Download PDF"]:
            self.assertContains(page, text)
        self.assertContains(page, "Secret side project")  # their own copy may show private projects
        response = self.client.post(reverse("resumes:mine"), {"template": "classic", "summary": "  I build small, well-tested APIs. ", "phone": "+91 98765 43210",
                                                                "projects": [self.public.pk], "sections": ["certificates", "stats"], "recruiters_can_download": "on"})
        self.assertRedirects(response, reverse("resumes:mine"))
        settings = ResumeSettings.objects.get(user=self.student)
        self.assertEqual((settings.template, settings.summary, settings.project_ids, settings.show_email), ("classic", "I build small, well-tested APIs.", [self.public.pk], False))
        self.assertEqual(sorted(settings.hidden_sections), ["practice", "writing"])
        page = self.client.get(reverse("resumes:mine"))
        self.assertContains(page, "is-classic")
        self.assertContains(page, "I build small, well-tested APIs.")
        self.assertNotContains(page, "How I built Budget API")
        self.assertNotContains(page, 'href="mailto:asha@example.com"')
    def test_ticking_a_box_redraws_just_the_resume(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("resumes:mine"), {"template": "modern", "summary": "", "phone": "", "show_email": "on", "sections": ["stats"]}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertContains(response, 'class="resume-sheet is-modern"')
        self.assertNotContains(response, "resume-editor")
        self.assertContains(self.client.post(reverse("resumes:mine"), {"template": "modern", "phone": "call me"}), "Enter a phone number", status_code=400)
    def test_a_recruiter_gets_the_public_resume(self):
        ResumeSettings.objects.create(user=self.student, phone="+91 98765 43210")
        self.client.force_login(self.recruiter)
        page = self.client.get(reverse("resumes:candidate", args=["asha"]))
        self.assertContains(page, "Budget API")
        self.assertNotContains(page, "Secret side project")
        self.assertNotContains(page, "asha@example.com")
        self.assertNotContains(page, "+91 98765 43210")
        self.assertContains(page, "once they accept your contact request")
        self.assertTrue(PortfolioView.objects.filter(profile=self.student.profile, viewer=self.recruiter).exists())
        ContactRequest.objects.create(recruiter=self.recruiter, developer=self.student, message="Hi", status="accepted")
        page = self.client.get(reverse("resumes:candidate", args=["asha"]))
        self.assertContains(page, "asha@example.com")
        self.assertContains(page, "+91 98765 43210")
        profile = self.client.get(reverse("landing:public_profile", args=["asha"]))
        self.assertContains(profile, reverse("resumes:candidate", args=["asha"]))
    def test_students_can_turn_recruiter_downloads_off(self):
        ResumeSettings.objects.create(user=self.student, recruiters_can_download=False)
        self.client.force_login(self.recruiter)
        self.assertEqual(self.client.get(reverse("resumes:candidate", args=["asha"])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("landing:public_profile", args=["asha"])), reverse("resumes:candidate", args=["asha"]))
        Profile.objects.filter(user=self.student).update(recruiter_visible=False)
        ResumeSettings.objects.filter(user=self.student).update(recruiters_can_download=True)
        self.assertEqual(self.client.get(reverse("resumes:candidate", args=["asha"])).status_code, 404)  # hidden from recruiters altogether
    def test_who_can_open_which_page(self):
        self.client.force_login(self.student)
        self.assertNotEqual(self.client.get(reverse("resumes:candidate", args=["asha"])).status_code, 200)  # students make their own, not others'
        self.client.force_login(self.recruiter)
        self.assertNotEqual(self.client.get(reverse("resumes:mine")).status_code, 200)
        search = self.client.get(reverse("recruiting:search"))
        self.assertContains(search, reverse("resumes:candidate", args=["asha"]))
