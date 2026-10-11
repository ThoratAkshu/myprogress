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
        rankings_url = reverse("landing:workspace_section", args=["rankings"])
        page = self.client.get(rankings_url)
        for label in ["Home", "Rankings", "Projects", "Learn", "Notifications", "Create"]:
            self.assertContains(page, f"<span>{label}</span>", html=False)
        self.assertNotContains(page, "<span>Network</span>", html=False)
        self.assertContains(page, f'<a class="active" href="{rankings_url}">', html=False)
        old_network = self.client.get(reverse("landing:workspace_section", args=["network"]))
        self.assertRedirects(old_network, reverse("landing:workspace_section", args=["learning"]) + "?tab=network", fetch_redirect_response=False)
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
    def test_composer_buttons_filter_the_feed_to_videos_articles_or_projects(self):
        video = LearningPost.objects.create(author=self.friend, title="Ledger video walkthrough", kind="video", video_url="https://youtu.be/dQw4w9WgXcQ")
        article = LearningPost.objects.create(author=self.friend, title="Ledger article", body="x")
        project = Project.objects.create(owner=self.friend, title="Ledger project")
        self.event(self.friend, "published_learning", post_id=video.pk)
        self.event(self.friend, "published_learning", post_id=article.pk)
        self.event(self.friend, "created_project", project_id=project.pk)
        def shown(show):
            response = self.client.get(reverse("landing:dashboard"), {"show": show})
            return response, [item.get("post", item.get("project")) for item in response.context["feed"]]
        response, items = shown("videos")
        self.assertEqual(items, [video])
        self.assertContains(response, 'class="active" href="/dashboard/" aria-current="true"')
        self.assertContains(response, "Showing only videos")
        self.assertEqual(shown("articles")[1], [article])
        self.assertEqual(shown("projects")[1], [project])
        response, items = shown("bogus")
        self.assertEqual(len(items), 3)
        self.assertNotContains(response, "Showing only")
        self.assertContains(response, 'href="?show=videos"')
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
        self.assertContains(posts, 'class="card post-card"', count=1)
        self.assertContains(posts, "data-expand-post")
        self.assertEqual(self.client.get(url, {"tab": "bogus"}).context["tab"], "overview")
class ProjectPageTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com", "Olivia", "Owner")
        self.project = Project.objects.create(owner=self.owner, title="Ledger", summary="Double-entry ledger", skills="Go")
        self.secret = Project.objects.create(owner=self.owner, title="Secret plan", is_public=False)
    def test_public_projects_are_visible_and_private_ones_only_to_the_owner(self):
        url = reverse("landing:project", args=[self.project.pk])
        page = self.client.get(url)
        self.assertContains(page, "Double-entry ledger")
        self.assertNotContains(page, "Update project")
        self.assertEqual(self.client.get(reverse("landing:project", args=[self.secret.pk])).status_code, 404)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("landing:project", args=[self.secret.pk])), "Update project")
        self.assertContains(self.client.get(url), "Create repository")
    def test_updating_from_the_project_page_returns_there(self):
        self.client.force_login(self.owner)
        url = reverse("landing:project", args=[self.project.pk])
        response = self.client.post(reverse("landing:update_project", args=[self.project.pk]), {"summary": "Updated", "next": url})
        self.assertRedirects(response, url)
    def test_projects_list_links_rows_to_project_pages(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("landing:workspace_section", args=["projects"]))
        self.assertContains(page, f'<a href="{reverse("landing:project", args=[self.project.pk])}">Ledger</a>', html=False)
        self.assertContains(page, "data-filter-search")
class NetworkTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.me = make_user("me@example.com", "Mira", "Kapoor", skills="Django")
        self.asha = make_user("asha@example.com", "Asha", "Rao", headline="Backend engineer", location="Pune", skills="Django, Postgres")
        self.ravi = make_user("ravi@example.com", "Ravi", "Menon", headline="Go developer", location="Bengaluru")
        self.hana = make_user("hana@example.com", "Hana", "Iyer", role="recruiter", headline="Talent at Acme")
        for user, slug, languages in [(self.me, "mine", {"Python": 900}), (self.asha, "ledger", {"Python": 800, "SQL": 100}), (self.ravi, "queue", {"Go": 700})]:
            Repository.objects.create(project=Project.objects.create(owner=user, title=slug), owner=user, slug=slug, languages=languages)
        Follow.objects.create(follower=self.me, following=self.ravi)
        Follow.objects.create(follower=self.ravi, following=self.asha)
        Follow.objects.create(follower=self.asha, following=self.me)
        self.url = reverse("landing:workspace_section", args=["learning"])
        self.client.force_login(self.me)
    def people(self, **params):
        response = self.client.get(self.url, {"tab": "network", **params})
        page = response.context["network_page"]
        return response, [person.user for person in (page.object_list if page else response.context["network_suggestions"])]
    def test_anyone_can_be_found_by_name_skill_language_place_or_role(self):
        response, suggested = self.people()
        self.assertIn(self.asha, suggested)
        self.assertNotIn(self.me, suggested)
        self.assertContains(response, "People you may know")
        self.assertEqual(self.people(q="asha")[1], [self.asha])
        self.assertEqual(self.people(q="postgres")[1], [self.asha])
        self.assertEqual(self.people(language="Go")[1], [self.ravi])
        self.assertEqual(self.people(location="pune")[1], [self.asha])
        self.assertEqual(self.people(role="recruiter")[1], [self.hana])
        response, everyone = self.people(q="a")
        self.assertEqual(everyone[0], self.asha)  # followed by someone Mira follows
        self.assertContains(response, "Followed by 1 you follow")
        self.assertContains(response, 'title="You both write Python"')
    def test_following_followers_and_requests_lists(self):
        response, following = self.people(view="following")
        self.assertEqual(following, [self.ravi])
        self.assertContains(response, 'aria-pressed="true"')
        response, followers = self.people(view="followers")
        self.assertEqual(followers, [self.asha])
        self.assertContains(response, "Follow</button>")
        response = self.client.get(self.url, {"tab": "network", "view": "requests"})
        self.assertContains(response, "No recruiter requests yet")
        self.assertContains(self.client.get(self.url), 'href="?tab=network"')
    def test_follow_updates_in_place_for_scripts(self):
        url = reverse("landing:follow", args=[self.asha.profile.handle])
        response = self.client.post(url, headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(response.json(), {"following": True, "followers": 2})
        self.assertEqual(self.client.post(url, headers={"X-Requested-With": "XMLHttpRequest"}).json(), {"following": False, "followers": 1})
