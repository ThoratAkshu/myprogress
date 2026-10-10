import tempfile
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.accounts.models import Follow, Profile
from apps.core.models import ActivityEvent, LearningPost, Project, Repository
def make_user(email, first_name, last_name, **profile_fields):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, **profile_fields)
    return user
class AppShellTests(TestCase):
    def test_navigation_depends_on_role_and_highlights_the_current_page(self):
        make_user("dev@example.com", "Dev", "Eloper")
        self.client.force_login(User.objects.get(username="dev@example.com"))
        network_url = reverse("landing:workspace_section", args=["network"])
        page = self.client.get(network_url)
        for label in ["Home", "Network", "Projects", "Learn", "Notifications", "Create"]:
            self.assertContains(page, f"<span>{label}</span>", html=False)
        self.assertContains(page, f'<a class="active" href="{network_url}">', html=False)
        recruiter = make_user("hr@example.com", "Hana", "Iyer", role="recruiter")
        self.client.force_login(recruiter)
        page = self.client.get(reverse("recruiting:search"))
        self.assertContains(page, "<span>Talent</span>", html=False)
        self.assertNotContains(page, "<span>Create</span>", html=False)
        self.client.logout()
        guest = self.client.get(reverse("landing:public_profile", args=["dev-eloper"]))
        self.assertContains(guest, "Join now")
        self.assertNotContains(guest, "<span>Notifications</span>", html=False)
    def test_users_without_a_profile_still_get_a_working_header(self):
        bare = User.objects.create_user(username="bare@example.com", email="bare@example.com", password="StrongPass!482", first_name="Bare", last_name="User")
        self.client.force_login(bare)
        self.assertEqual(self.client.get(reverse("notifications:list")).status_code, 200)
        self.assertEqual(bare.profile.handle, "bare-user")
class FeedTests(TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.override = override_settings(GIT_REPOSITORY_ROOT=self.storage.name)
        self.override.enable()
        self.me = make_user("me@example.com", "Me", "Dev")
        self.friend = make_user("friend@example.com", "Fri", "End")
        self.stranger = make_user("stranger@example.com", "Str", "Anger")
        Follow.objects.create(follower=self.me, following=self.friend)
        self.client.force_login(self.me)
    def tearDown(self):
        self.override.disable()
        self.storage.cleanup()
    def event(self, user, action, **metadata):
        return ActivityEvent.objects.create(user=user, event_type="project", action=action, points=1, metadata=metadata)
    def test_feed_shows_followed_public_activity_and_hides_private_work(self):
        public_repo = Repository.objects.create(project=Project.objects.create(owner=self.friend, title="Open"), owner=self.friend, slug="open", visibility="public")
        private_repo = Repository.objects.create(project=Project.objects.create(owner=self.friend, title="Classified", is_public=False), owner=self.friend, slug="classified")
        post = LearningPost.objects.create(author=self.friend, title="How I built Open", body="x")
        draft = LearningPost.objects.create(author=self.friend, title="Unfinished draft", is_public=False)
        self.event(self.friend, "pushed_commits", repository_id=public_repo.pk, commits=2)
        self.event(self.friend, "pushed_commits", repository_id=public_repo.pk, commits=3)
        self.event(self.friend, "pushed_commits", repository_id=private_repo.pk, commits=9)
        self.event(self.friend, "published_learning", post_id=post.pk)
        self.event(self.friend, "published_learning", post_id=draft.pk)
        self.event(self.friend, "created_project", project_id=private_repo.project_id)
        self.event(self.stranger, "created_project", project_id=Project.objects.create(owner=self.stranger, title="Not followed").pk)
        response = self.client.get(reverse("landing:dashboard"))
        feed = response.context["feed"]
        network = [item for item in feed if not item["suggested"]]
        self.assertEqual([item["action"] for item in network], ["published_learning", "pushed_commits"])
        self.assertEqual(network[1]["commits"], 5)
        self.assertEqual([item["actor"] for item in feed if item["suggested"]], [self.stranger])
        self.assertContains(response, "How I built Open")
        self.assertContains(response, "Pushed 5 commits to")
        for hidden in ["classified", "Unfinished draft"]:
            self.assertNotContains(response, hidden)
    def test_quiet_feeds_fall_back_to_suggested_public_activity(self):
        Follow.objects.all().delete()
        self.event(self.stranger, "created_project", project_id=Project.objects.create(owner=self.stranger, title="Public thing").pk)
        response = self.client.get(reverse("landing:dashboard"))
        self.assertTrue(response.context["feed"][0]["suggested"])
        self.assertContains(response, "Popular on MyProgress")
        self.assertContains(response, "Suggested for you")
    def test_liking_and_following_from_the_feed_return_to_the_feed(self):
        post = LearningPost.objects.create(author=self.friend, title="Post", body="x")
        home = reverse("landing:dashboard")
        self.assertRedirects(self.client.post(reverse("learning:like", args=[post.pk]), {"next": home}), home, fetch_redirect_response=False)
        self.assertRedirects(self.client.post(reverse("landing:follow", args=["str-anger"]), {"next": home}), home, fetch_redirect_response=False)
        self.assertRedirects(self.client.post(reverse("landing:follow", args=["str-anger"]), {"next": "https://evil.example/"}), reverse("landing:public_profile", args=["str-anger"]), fetch_redirect_response=False)
    def test_suggestions_skip_people_already_followed_and_prefer_shared_languages(self):
        Repository.objects.create(project=Project.objects.create(owner=self.me, title="Mine"), owner=self.me, slug="mine", languages={"Go": 10})
        gopher = make_user("gopher@example.com", "Go", "Pher")
        Repository.objects.create(project=Project.objects.create(owner=gopher, title="Gopher"), owner=gopher, slug="gopher", languages={"Go": 5})
        Profile.objects.filter(user=self.stranger).update(score=90)
        suggestions = self.client.get(reverse("landing:dashboard")).context["suggestions"]
        self.assertEqual([profile.user for profile in suggestions], [gopher, self.stranger])
        self.assertEqual(suggestions[0].shared, ["Go"])
class SearchAndProfileTabTests(TestCase):
    def setUp(self):
        self.owner = make_user("asha@example.com", "Asha", "Rao", headline="Django engineer", skills="Django")
        Repository.objects.create(project=Project.objects.create(owner=self.owner, title="Ledger API", summary="Double-entry ledger"), owner=self.owner, slug="ledger-api", visibility="public", languages={"Python": 10})
        Repository.objects.create(project=Project.objects.create(owner=self.owner, title="Ledger secrets"), owner=self.owner, slug="ledger-secrets")
        LearningPost.objects.create(author=self.owner, title="Building a ledger in Django", body="x")
        LearningPost.objects.create(author=self.owner, title="Ledger draft", is_public=False)
    def test_search_finds_people_public_repositories_and_posts(self):
        response = self.client.get(reverse("landing:search"), {"q": "ledger"})
        self.assertEqual(response.context["counts"], {"people": 0, "repositories": 1, "posts": 1})
        self.assertContains(response, "asha-rao/ledger-api")
        self.assertNotContains(response, "ledger-secrets")
        self.assertNotContains(response, "Ledger draft")
        people = self.client.get(reverse("landing:search"), {"q": "django asha", "type": "people"})
        self.assertEqual([profile.handle for profile in people.context["people"]], ["asha-rao"])
        self.assertContains(self.client.get(reverse("landing:search"), {"q": "zzzz"}), "No results")
    def test_profile_tabs_show_repositories_and_post_grid(self):
        url = reverse("landing:public_profile", args=["asha-rao"])
        repositories = self.client.get(url, {"tab": "repositories"})
        self.assertContains(repositories, 'class="repo-list-name"', count=1)
        self.assertContains(repositories, "#3572A5")
        posts = self.client.get(url, {"tab": "posts"})
        self.assertContains(posts, 'class="post-tile"', count=1)
        self.assertEqual(self.client.get(url, {"tab": "bogus"}).context["tab"], "overview")
