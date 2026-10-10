import shutil
import tempfile
from pathlib import Path
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from apps.accounts.models import Follow, Profile
from apps.core.models import ContentView, LearningPost, PostComment, PostLike, Project
from apps.core.services import score_breakdown
from apps.notifications.models import Notification
from .formatting import render_article
from .media import MAX_VIDEO_BYTES, validate_video_file, youtube_embed_url
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
ARTICLE = "I built the ledger service with Go and PostgreSQL. " * 6
def make_user(email, first_name, last_name, **profile_fields):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, **profile_fields)
    return user
class ArticleFormattingTests(SimpleTestCase):
    def test_author_markup_is_escaped(self):
        html = render_article('<script>alert(1)</script>\n<img src=x onerror="alert(1)">')
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)
    def test_only_http_links_are_created_and_attributes_cannot_break_out(self):
        html = render_article('javascript:alert(1) and https://example.com/a"onmouseover="alert(1) and see https://docs.example.com/guide.')
        self.assertNotIn('href="javascript', html)
        self.assertNotIn('onmouseover="', html)
        self.assertIn('<a href="https://docs.example.com/guide" rel="nofollow noopener" target="_blank">https://docs.example.com/guide</a>.', html)
    def test_supported_blocks(self):
        source = "# Architecture\nThe **core** uses `select_related`.\n\n- Fast\n- Simple\n\n```python\nif a < b and '**x**':\n    pass\n```"
        html = render_article(source)
        self.assertIn("<h2>Architecture</h2>", html)
        self.assertIn("<p>The <strong>core</strong> uses <code>select_related</code>.</p>", html)
        self.assertIn("<ul><li>Fast</li><li>Simple</li></ul>", html)
        self.assertIn('<pre><code class="language-python">if a &lt; b and &#x27;**x**&#x27;:\n    pass</code></pre>', html)
    def test_inline_code_is_not_formatted_and_bad_language_names_are_dropped(self):
        self.assertIn("<code>**raw**</code>", render_article("`**raw**`"))
        self.assertIn("<pre><code>x</code></pre>", render_article('```"><script>\nx\n```'))
class MediaTests(SimpleTestCase):
    def test_video_signatures_are_checked(self):
        validate_video_file(SimpleUploadedFile("demo.mp4", MP4_BYTES, content_type="video/mp4"))
        validate_video_file(SimpleUploadedFile("demo.webm", b"\x1aE\xdf\xa3" + b"\x00" * 32, content_type="video/webm"))
        for upload in [SimpleUploadedFile("evil.mp4", b"<html><script>alert(1)</script></html>"), SimpleUploadedFile("demo.avi", MP4_BYTES), SimpleUploadedFile("demo.webm", MP4_BYTES)]:
            with self.assertRaises(ValidationError):
                validate_video_file(upload)
        large = SimpleUploadedFile("big.mp4", MP4_BYTES)
        large.size = MAX_VIDEO_BYTES + 1
        with self.assertRaises(ValidationError):
            validate_video_file(large)
    def test_youtube_links_become_privacy_friendly_embeds(self):
        expected = "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
        for url in ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "https://youtu.be/dQw4w9WgXcQ", "https://youtube.com/shorts/dQw4w9WgXcQ"]:
            self.assertEqual(youtube_embed_url(url), expected)
        for url in ["https://vimeo.com/123", "https://www.youtube.com/watch?v=bad\"id", "https://evil.example/youtu.be/dQw4w9WgXcQ", ""]:
            self.assertEqual(youtube_embed_url(url), "")
class PublishingTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.author = make_user("author@example.com", "Asha", "Rao")
        self.project = Project.objects.create(owner=self.author, title="Ledger")
        self.client.force_login(self.author)
    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
    def test_article_needs_substance_and_links_only_to_own_projects(self):
        url = reverse("learning:create")
        self.client.post(url, {"title": "Short", "kind": "article", "body": "Too short.", "is_public": "on"})
        other_project = Project.objects.create(owner=make_user("other@example.com", "Other", "Dev"), title="Not mine")
        response = self.client.post(url, {"title": "Sneaky", "kind": "article", "body": ARTICLE, "project": other_project.pk, "is_public": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(LearningPost.objects.exists())
        response = self.client.post(url, {"title": "How I built Ledger", "kind": "article", "body": ARTICLE, "project": self.project.pk, "summary": "Go + Postgres", "is_public": "on"})
        post = LearningPost.objects.get()
        self.assertRedirects(response, reverse("learning:detail", args=[post.pk]))
        self.assertEqual((post.author, post.project), (self.author, self.project))
        self.assertTrue(self.author.activity_events.filter(action="published_learning").exists())
        self.assertTrue(self.author.daily_loop_completions.filter(step="share").exists())
        self.assertContains(self.client.get(reverse("learning:create"), {"project": self.project.pk}), f'<option value="{self.project.pk}" selected>')
    def test_video_upload_replace_and_delete_manage_files(self):
        self.client.post(reverse("learning:create"), {"title": "Walkthrough", "kind": "video", "video_file": SimpleUploadedFile("one.mp4", MP4_BYTES, content_type="video/mp4"), "is_public": "on"})
        post = LearningPost.objects.get()
        first_file = Path(self.media) / post.video_file.name
        self.assertTrue(first_file.exists())
        self.assertContains(self.client.get(reverse("learning:detail", args=[post.pk])), f'<video class="post-video" controls preload="metadata" src="{post.video_file.url}"')
        self.client.post(reverse("learning:edit", args=[post.pk]), {"title": "Walkthrough v2", "kind": "video", "video_file": SimpleUploadedFile("two.mp4", MP4_BYTES, content_type="video/mp4"), "is_public": "on"})
        post.refresh_from_db()
        second_file = Path(self.media) / post.video_file.name
        self.assertFalse(first_file.exists())
        self.assertTrue(second_file.exists())
        self.client.post(reverse("learning:delete", args=[post.pk]))
        self.assertFalse(LearningPost.objects.exists())
        self.assertFalse(second_file.exists())
    def test_disguised_video_is_rejected(self):
        response = self.client.post(reverse("learning:create"), {"title": "Evil", "kind": "video", "video_file": SimpleUploadedFile("evil.mp4", b"<html><script>alert(1)</script>", content_type="video/mp4"), "is_public": "on"})
        self.assertContains(response, "That file is not a valid video.")
        self.assertFalse(LearningPost.objects.exists())
    def test_only_the_author_can_edit_or_delete(self):
        post = LearningPost.objects.create(author=self.author, title="Mine", body=ARTICLE)
        self.client.force_login(make_user("intruder@example.com", "In", "Truder"))
        self.assertEqual(self.client.get(reverse("learning:edit", args=[post.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("learning:delete", args=[post.pk])).status_code, 404)
        self.assertTrue(LearningPost.objects.filter(pk=post.pk).exists())
class ReadingAndEngagementTests(TestCase):
    def setUp(self):
        self.author = make_user("author@example.com", "Asha", "Rao")
        self.reader = make_user("reader@example.com", "Ravi", "Reader")
        self.post = LearningPost.objects.create(author=self.author, title="How I built Ledger", body="## Design\nUse **queues**.", video_url="https://youtu.be/dQw4w9WgXcQ")
        self.url = reverse("learning:detail", args=[self.post.pk])
    def test_public_posts_render_for_anyone_and_drafts_only_for_the_author(self):
        response = self.client.get(self.url)
        self.assertContains(response, "<h3>Design</h3>", html=False)
        self.assertContains(response, "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
        self.assertNotContains(response, "author@example.com")
        draft = LearningPost.objects.create(author=self.author, title="Draft", is_public=False)
        self.assertEqual(self.client.get(reverse("learning:detail", args=[draft.pk])).status_code, 404)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("learning:detail", args=[draft.pk])).status_code, 404)
        self.client.force_login(self.author)
        self.assertContains(self.client.get(reverse("learning:detail", args=[draft.pk])), "Private draft")
    def test_views_count_once_per_session_per_day_and_never_for_the_author(self):
        self.client.get(self.url)
        self.client.get(self.url)
        self.client.force_login(self.author)
        self.client.get(self.url)
        self.post.refresh_from_db()
        self.assertEqual((self.post.views, ContentView.objects.count()), (1, 1))
    def test_legacy_share_links_never_redirect_off_site(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("landing:learning_view", args=[self.post.pk]))
        self.assertRedirects(response, self.url)
        self.assertTrue(self.reader.daily_loop_completions.filter(step="learn").exists())
    def test_likes_toggle_and_notify_the_author_once(self):
        self.client.force_login(self.reader)
        like_url = reverse("learning:like", args=[self.post.pk])
        self.client.post(like_url)
        self.assertContains(self.client.get(self.url), "<b class=\"ig-likes\">1 like</b>", html=False)
        self.client.post(like_url)
        self.assertFalse(PostLike.objects.exists())
        self.assertEqual(Notification.objects.filter(recipient=self.author, kind="like").count(), 1)
        self.client.force_login(self.author)
        self.client.post(like_url)
        self.assertEqual(Notification.objects.count(), 1)
    def test_comments_notify_and_can_be_removed_by_commenter_or_author_only(self):
        self.assertRedirects(self.client.post(reverse("learning:comment", args=[self.post.pk]), {"body": "Hi"}), "/?next=" + reverse("learning:comment", args=[self.post.pk]), fetch_redirect_response=False)
        self.client.force_login(self.reader)
        self.client.post(reverse("learning:comment", args=[self.post.pk]), {"body": "Why queues over cron?"})
        comment = PostComment.objects.get()
        self.assertContains(self.client.get(self.url), "Why queues over cron?")
        notification = Notification.objects.get(recipient=self.author, kind="comment")
        self.assertTrue(notification.url.endswith(f"#comment-{comment.pk}"))
        self.client.force_login(make_user("stranger@example.com", "Str", "Anger"))
        self.assertEqual(self.client.post(reverse("learning:comment_delete", args=[comment.pk])).status_code, 404)
        self.client.force_login(self.author)
        self.client.post(reverse("learning:comment_delete", args=[comment.pk]))
        self.assertFalse(PostComment.objects.exists())
    def test_teaching_score_counts_signed_in_readers_only(self):
        teaching = lambda: next(component for component in score_breakdown(self.author) if component["key"] == "teaching")
        self.client.get(self.url)
        self.client.force_login(self.author)
        self.client.get(self.url)
        self.assertEqual(teaching()["detail"], "1 published post, 0 signed-in readers")
        for index in range(10):
            self.client.force_login(make_user(f"r{index}@example.com", "Reader", str(index)))
            self.client.get(self.url)
        self.assertEqual(teaching()["points"], 5)
class FeedTests(TestCase):
    def test_tabs_show_everyone_followed_authors_and_own_drafts(self):
        me = make_user("me@example.com", "Me", "Dev")
        followed = make_user("followed@example.com", "Fol", "Lowed")
        stranger = make_user("stranger@example.com", "Str", "Anger")
        Follow.objects.create(follower=me, following=followed)
        LearningPost.objects.create(author=followed, title="Followed post")
        LearningPost.objects.create(author=stranger, title="Stranger post")
        LearningPost.objects.create(author=stranger, title="Stranger draft", is_public=False)
        LearningPost.objects.create(author=me, title="My draft", is_public=False)
        self.client.force_login(me)
        url = reverse("landing:workspace_section", args=["learning"])
        titles = lambda tab: [post.title for post in self.client.get(url, {"tab": tab}).context["learning_page"]]
        self.assertEqual(sorted(titles("for-you")), ["Followed post", "Stranger post"])
        self.assertEqual(titles("following"), ["Followed post"])
        self.assertEqual(titles("mine"), ["My draft"])
    def test_portfolio_links_projects_to_their_explainer(self):
        author = make_user("author@example.com", "Asha", "Rao")
        project = Project.objects.create(owner=author, title="Ledger")
        post = LearningPost.objects.create(author=author, title="How I built Ledger", project=project)
        response = self.client.get(reverse("landing:public_profile", args=["asha-rao"]))
        self.assertContains(response, f'<a href="{reverse("learning:detail", args=[post.pk])}">▷ How I built this</a>', html=False)
