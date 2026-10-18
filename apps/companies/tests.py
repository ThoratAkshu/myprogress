"""Companies own repositories together, like organizations on GitHub."""
from django.core import mail
from django.urls import reverse
from apps.accounts.models import Profile
from apps.code.tests import RepositoryTestCase, make_user
from apps.core.git_service import initialize_repository, repository_role, user_can_access, user_can_maintain
from apps.core.models import Project, Repository, RepositoryCollaborator
from apps.notifications.models import Notification
from .models import Company, CompanyInvitation, CompanyMember, Team, TeamMember, TeamRepository


class CompanyTestCase(RepositoryTestCase):
    def setUp(self):
        super().setUp()
        self.teammate = make_user("mate@example.com", "Team", "Mate")
        self.client.force_login(self.owner)
        self.client.post(reverse("companies:list"), {"name": "Acme Labs", "description": "Tools for small shops", "website": ""})
        self.company = Company.objects.get()
        self.detail = reverse("companies:detail", args=[self.company.slug])

    def new_repository(self, title, user=None, visibility="private"):
        self.client.force_login(user or self.owner)
        self.client.post(reverse("companies:repository_create", args=[self.company.slug]), {"title": title, "visibility": visibility})
        return Repository.objects.get(company=self.company, project__title=title)

    def join(self, user, role="member"):
        return CompanyMember.objects.create(company=self.company, user=user, role=role)


class CompanyTests(CompanyTestCase):
    def test_a_student_creates_a_company_and_its_repositories(self):
        self.assertEqual((self.company.slug, CompanyMember.objects.get().role), ("acme-labs", "owner"))
        repository = self.new_repository("Billing API")
        self.assertEqual((repository.slug, repository.owner, repository.project.owner, repository.full_name), ("billing-api", self.owner, self.owner, "acme-labs/billing-api"))
        page = self.client.get(reverse("landing:repository", args=[repository.pk]))
        self.assertContains(page, f'href="{self.detail}" title="Owned by Acme Labs">acme-labs</a>')
        self.assertContains(self.client.get(f"{reverse('landing:repository', args=[repository.pk])}?tab=settings"), "Owned by <a")
        self.assertContains(self.client.get(reverse("landing:workspace_section", args=["projects"])), "Acme Labs")
        self.new_repository("Website", visibility="public")
        self.client.logout()
        public = self.client.get(self.detail)
        self.assertContains(public, "acme-labs/website")
        self.assertNotContains(public, "acme-labs/billing-api")  # private: members only
        self.assertNotContains(public, "?tab=people")
        recruiter = make_user("hire@example.com", "Rita", "Recruiter")
        Profile.objects.filter(user=recruiter).update(role="recruiter")
        self.client.force_login(recruiter)
        self.assertNotEqual(self.client.get(reverse("companies:list")).status_code, 200)  # companies are for students and professionals

    def test_members_reach_repositories_through_the_base_permission_teams_and_what_they_made(self):
        repository = self.new_repository("Billing API")
        self.join(self.teammate)
        self.assertEqual(repository_role(self.teammate, repository), "read")  # the default base permission
        self.assertFalse(user_can_access(self.teammate, repository, write=True))
        Company.objects.filter(pk=self.company.pk).update(base_role="none")
        repository.refresh_from_db()
        self.assertIsNone(repository_role(self.teammate, repository))
        self.client.force_login(self.teammate)
        self.assertEqual(self.client.get(reverse("landing:repository", args=[repository.pk])).status_code, 302)
        # A team gets more on the repositories it works on.
        self.client.force_login(self.owner)
        self.client.post(reverse("companies:team_create", args=[self.company.slug]), {"name": "Backend", "description": "APIs"})
        team = Team.objects.get()
        team_url = reverse("companies:team", args=[self.company.slug, team.slug])
        self.client.post(team_url, {"action": "add_member", "id": CompanyMember.objects.get(user=self.teammate).pk})
        self.client.post(team_url, {"action": "add_repository", "id": repository.pk, "role": "maintain"})
        self.assertEqual(repository_role(self.teammate, repository), "maintain")
        self.assertTrue(user_can_maintain(self.teammate, repository))
        self.assertTrue(Notification.objects.filter(recipient=self.teammate, text="Olivia Owner added you to the Backend team in Acme Labs").exists())
        self.client.post(team_url, {"action": "update_repository", "id": TeamRepository.objects.get().pk, "role": "read"})
        self.assertEqual(repository_role(self.teammate, repository), "read")
        Company.objects.filter(pk=self.company.pk).update(base_role="write")
        repository.refresh_from_db()
        self.assertEqual(repository_role(self.teammate, repository), "write")  # the highest of all counts
        own = self.new_repository("Teammate tool", user=self.teammate)
        self.assertEqual(repository_role(self.teammate, own), "admin")  # what you made, you administer
        self.assertEqual(repository_role(self.owner, own), "owner")  # company owners have it all
        outsider = make_user("guest@example.com", "Gus", "Guest")
        RepositoryCollaborator.objects.create(repository=repository, user=outsider, role="read")
        self.assertEqual(repository_role(outsider, repository), "read")  # outside collaborators keep their own access
        self.client.force_login(self.teammate)
        self.assertEqual(self.client.post(team_url, {"action": "delete"}).status_code, 404)  # only owners change teams
        self.assertContains(self.client.get(team_url), "Backend")

    def test_people_are_invited_and_let_go(self):
        response = self.client.post(reverse("companies:people", args=[self.company.slug]), {"action": "invite", "invitee": "@team-mate", "role": "member"}, follow=True)
        self.assertContains(response, "Invitation sent. They join Acme Labs as a member when they accept.")
        invitation = CompanyInvitation.objects.get()
        link = reverse("companies:invitation", args=[invitation.token])
        self.assertIn(link, mail.outbox[0].body)
        self.assertEqual(Notification.objects.get(recipient=self.teammate).url, link)
        self.client.force_login(self.teammate)
        self.assertContains(self.client.get(reverse("repository_invitations:list")), "Acme Labs")
        self.assertContains(self.client.get(link), "Join Acme Labs")
        self.assertRedirects(self.client.post(link, {"action": "accept"}), self.detail)
        self.assertEqual(CompanyMember.objects.get(user=self.teammate).role, "member")
        self.assertTrue(Notification.objects.filter(recipient=self.owner, text="Team Mate joined Acme Labs").exists())
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("companies:list")), "Owner · 2 members")  # everyone counted, not just you
        recruiter = make_user("hire@example.com", "Rita", "Recruiter")
        Profile.objects.filter(user=recruiter).update(role="recruiter")
        self.client.force_login(self.owner)
        self.assertContains(self.client.post(reverse("companies:people", args=[self.company.slug]), {"action": "invite", "invitee": "hire@example.com"}, follow=True), "Companies are for student and professional accounts")
        # What a member made stays with the company when they go.
        made = self.new_repository("Teammate tool", user=self.teammate)
        team = Team.objects.create(company=self.company, name="Backend", slug="backend")
        TeamMember.objects.create(team=team, user=self.teammate)
        self.client.force_login(self.owner)
        self.client.post(reverse("companies:people", args=[self.company.slug]), {"action": "remove", "id": CompanyMember.objects.get(user=self.teammate).pk})
        made.refresh_from_db()
        self.assertFalse(CompanyMember.objects.filter(user=self.teammate).exists())
        self.assertFalse(TeamMember.objects.exists())
        self.assertEqual(made.project.owner, self.owner)
        self.assertIsNone(repository_role(self.teammate, made))
        self.assertTrue(Notification.objects.filter(recipient=self.teammate, text="Olivia Owner removed you from Acme Labs").exists())
        # A company always keeps an owner.
        people = reverse("companies:people", args=[self.company.slug])
        self.assertContains(self.client.post(people, {"action": "leave"}, follow=True), "You&#x27;re the only owner")
        self.client.post(people, {"action": "role", "id": CompanyMember.objects.get(user=self.owner).pk, "role": "member"})
        self.assertEqual(CompanyMember.objects.get(user=self.owner).role, "owner")
        self.join(self.teammate, role="owner")
        self.assertRedirects(self.client.post(people, {"action": "leave"}), reverse("companies:list"))
        self.assertFalse(CompanyMember.objects.filter(user=self.owner).exists())
        self.assertEqual(Project.objects.get(repository=made).owner, self.teammate)  # passed to the remaining owner

    def test_your_repository_moves_into_a_company_and_keeps_its_git_address(self):
        RepositoryCollaborator.objects.create(repository=self.repository, user=self.teammate, role="write")
        clone = self.client.get(self.url).context["clone_url"]
        settings_page = self.client.get(f"{self.url}?tab=settings")
        self.assertContains(settings_page, "Move to a company")
        self.client.post(reverse("code:transfer", args=[self.repository.pk]), {"company": "acme-labs"})
        self.repository.refresh_from_db()
        self.assertEqual((self.repository.company, self.repository.full_name), (self.company, "acme-labs/ledger"))
        self.assertEqual(self.client.get(self.url).context["clone_url"], clone)
        self.assertEqual(repository_role(self.teammate, self.repository), "write")  # its collaborators keep their access
        stranger = make_user("stranger@example.com", "Sam", "Stranger")
        theirs = Repository.objects.create(project=Project.objects.create(owner=stranger, title="Ledger"), owner=stranger, slug="ledger")
        initialize_repository(theirs)
        self.client.force_login(stranger)
        self.client.post(reverse("code:transfer", args=[theirs.pk]), {"company": "acme-labs"})  # not in the company
        theirs.refresh_from_db()
        self.assertIsNone(theirs.company)
        self.join(stranger)
        self.assertContains(self.client.post(reverse("code:transfer", args=[theirs.pk]), {"company": "acme-labs"}, follow=True), "Acme Labs already has a repository called ledger")

    def test_deleting_a_company_gives_nothing_back_to_people_who_left(self):
        self.join(self.teammate)
        made = self.new_repository("Teammate tool", user=self.teammate)
        mine = self.new_repository("Billing API")
        self.client.post(reverse("companies:people", args=[self.company.slug]), {"action": "remove", "id": CompanyMember.objects.get(user=self.teammate).pk})
        settings = reverse("companies:settings", args=[self.company.slug])
        self.client.post(settings, {"action": "delete", "confirm": "wrong"})
        self.assertTrue(Company.objects.exists())
        self.client.post(settings, {"action": "delete", "confirm": "acme-labs"})
        self.assertFalse(Company.objects.exists())
        made.refresh_from_db()
        mine.refresh_from_db()
        self.assertEqual((made.company, made.owner, mine.owner), (None, self.owner, self.owner))
        self.assertIsNone(repository_role(self.teammate, made))

    def test_only_the_right_people_see_and_change_each_part(self):
        member = make_user("member@example.com", "Mo", "Member")
        self.join(member)
        settings = reverse("companies:settings", args=[self.company.slug])
        self.client.post(settings, {"name": "Acme Labs", "description": "", "website": "", "base_role": "write"})
        self.company.refresh_from_db()
        self.assertEqual(self.company.base_role, "write")
        self.client.force_login(member)
        self.assertContains(self.client.get(f"{self.detail}?tab=people"), "Mo Member")
        self.assertNotContains(self.client.get(f"{self.detail}?tab=settings"), "Base permission")
        self.assertEqual(self.client.post(settings, {"name": "Taken", "base_role": "none"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("companies:people", args=[self.company.slug]), {"action": "invite", "invitee": "@team-mate"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("companies:team_create", args=[self.company.slug]), {"name": "Mine"}).status_code, 404)
        self.client.force_login(self.teammate)  # not in the company
        self.assertNotContains(self.client.get(f"{self.detail}?tab=people"), "Mo Member")
        self.assertEqual(self.client.post(reverse("companies:repository_create", args=[self.company.slug]), {"title": "Sneaky"}).status_code, 404)
        self.assertFalse(Repository.objects.filter(company=self.company).exists())
