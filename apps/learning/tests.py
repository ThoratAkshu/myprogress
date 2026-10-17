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
        self.assertIn('<h2 id="architecture">Architecture</h2>', html)
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
    def test_browser_recording_and_captured_thumbnail_publish_as_a_video_post(self):
        import io
        from PIL import Image
        page = self.client.get(reverse("learning:create"), {"kind": "video"})
        self.assertContains(page, 'data-record-mode="screen-camera"')
        self.assertContains(page, 'id="recorder-dialog"')
        frame = io.BytesIO()
        Image.new("RGB", (64, 36), "#0f172a").save(frame, "JPEG")
        recording = SimpleUploadedFile("walkthrough-2026-10-10.webm", b"\x1aE\xdf\xa3" + b"\x00" * 64, content_type="video/webm")
        thumbnail = SimpleUploadedFile("thumbnail.jpg", frame.getvalue(), content_type="image/jpeg")
        response = self.client.post(reverse("learning:create"), {"title": "Ledger walkthrough", "kind": "video", "project": self.project.pk, "summary": "", "body": "", "video_script": "INTRO\nHi.", "video_file": recording, "thumbnail": thumbnail, "is_public": "on"})
        post = LearningPost.objects.get(title="Ledger walkthrough")
        self.assertRedirects(response, reverse("learning:detail", args=[post.pk]))
        self.assertTrue(post.video_file.name.endswith(".webm"))
        self.assertTrue(post.thumbnail.name.endswith(".jpg"))
        self.assertEqual(post.video_script, "INTRO\nHi.")
    def test_format_comes_first_and_the_studio_offers_drawing_notes_and_trimming(self):
        page = self.client.get(reverse("learning:create"), {"kind": "video"}).content.decode()
        self.assertLess(page.index('class="format-picker"'), page.index('class="studio-source"'))
        self.assertIn('<input type="radio" name="kind" value="video"', page)
        for control in ['data-record-mode="board"', 'data-ink-tool="pen"', 'data-ink-tool="zoom"', 'data-ink-color="#ef4444"', 'data-ink-action="board"', '<option value="chalk">Chalkboard</option>', 'data-pane="notes"', 'value="top-center"', "data-note-add", "data-clip-editor", 'data-clip-action="cut"', "data-edit-file-input", "recorder-ink.js", "recorder-editor.js"]:
            self.assertIn(control, page)
    def test_background_upload_gets_the_post_address_and_keeps_the_success_message(self):
        data = {"title": "Uploaded in the background", "kind": "article", "summary": "", "body": ARTICLE, "is_public": "on"}
        response = self.client.post(reverse("learning:create"), data, headers={"X-Requested-With": "XMLHttpRequest"})
        post = LearningPost.objects.get(title="Uploaded in the background")
        self.assertEqual(response.json(), {"redirect": reverse("learning:detail", args=[post.pk])})
        self.assertContains(self.client.get(response.json()["redirect"]), "Published. Share the link")
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
        self.assertContains(self.client.get(reverse("learning:create"), {"project": self.project.pk}), f'<input type="radio" name="project" value="{self.project.pk}" checked>')
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
        self.assertContains(response, '<h3 id="design">Design</h3>', html=False)
        self.assertContains(response, "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
        self.assertNotContains(response, "author@example.com")
        draft = LearningPost.objects.create(author=self.author, title="Draft", is_public=False)
        self.assertEqual(self.client.get(reverse("learning:detail", args=[draft.pk])).status_code, 404)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("learning:detail", args=[draft.pk])).status_code, 404)
        self.client.force_login(self.author)
        self.assertContains(self.client.get(reverse("learning:detail", args=[draft.pk])), "Private draft")
    def test_text_articles_open_in_the_left_pane_and_learn_shows_a_vertical_feed(self):
        article = LearningPost.objects.create(author=self.author, title="Queues explained", body="## Why queues\nThey smooth out bursts. " * 20)
        response = self.client.get(reverse("learning:detail", args=[article.pk]))
        self.assertContains(response, '<div class="ig-media is-article" id="write-up">')
        self.assertContains(response, '<h3 id="why-queues">Why queues</h3>', html=False)
        self.assertNotContains(response, 'class="card write-up"')
        PostLike.objects.create(post=article, user=self.reader)
        self.client.force_login(self.reader)
        learn = self.client.get(reverse("landing:workspace_section", args=["learning"]))
        self.assertContains(learn, 'class="card post-card"', count=2)
        self.assertContains(learn, f'id="post-{article.pk}"')
        self.assertContains(learn, 'class="ig-icon-button liked" aria-pressed="true"', count=1)
        self.assertContains(learn, f'href="/learn/{article.pk}/" data-expand-post')
        self.assertContains(learn, "data-more hidden>more</button>")
        response = self.client.post(reverse("learning:like", args=[self.post.pk]), {"next": f"/dashboard/learning/#post-{self.post.pk}"})
        self.assertRedirects(response, f"/dashboard/learning/#post-{self.post.pk}", fetch_redirect_response=False)
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
class StudioTests(TestCase):
    def setUp(self):
        from apps.core.git_service import commit_file, create_branch, initialize_repository
        from apps.core.models import Repository
        self.storage = tempfile.TemporaryDirectory()
        self.override = override_settings(GIT_REPOSITORY_ROOT=self.storage.name, ANTHROPIC_API_KEY="")
        self.override.enable()
        self.author = make_user("author@example.com", "Asha", "Rao")
        self.project = Project.objects.create(owner=self.author, title="Ledger", summary="A double-entry ledger service.")
        self.repository = Repository.objects.create(project=self.project, owner=self.author, slug="ledger")
        initialize_repository(self.repository)
        commit_file(self.repository, "README.md", "# Ledger\n\nTracks money with double-entry bookkeeping.\n", self.author, "Add README")
        commit_file(self.repository, "ledger/post.py", "def post(entry):\n    return entry\n", self.author, "Post balanced entries")
        create_branch(self.repository, "feature/refunds", "main")
        self.client.force_login(self.author)
    def tearDown(self):
        self.override.disable()
        self.storage.cleanup()
    def draft(self, **data):
        return self.client.post(reverse("learning:studio_draft"), {"project": self.project.pk, "branch": "main", "kind": "article", **data})
    def test_branches_are_listed_only_for_the_owner(self):
        response = self.client.get(reverse("learning:studio_branches"), {"project": self.project.pk})
        self.assertEqual(response.json()["default"], "main")
        self.assertEqual({branch["name"] for branch in response.json()["branches"]}, {"main", "feature/refunds"})
        self.client.force_login(make_user("other@example.com", "Oth", "Er"))
        self.assertEqual(self.client.get(reverse("learning:studio_branches"), {"project": self.project.pk}).status_code, 404)
        self.assertEqual(self.draft().status_code, 404)
    def test_starter_draft_is_built_from_the_branch_without_an_api_key(self):
        draft = self.draft().json()
        self.assertEqual(draft["source"], "starter")
        self.assertEqual(draft["title"], "How I built Ledger")
        self.assertIn("Post balanced entries", draft["body"])
        self.assertIn("`ledger/`", draft["body"])
        self.assertIn("**Python**", draft["body"])
        self.assertIn("[SHOW: ledger/]", draft["video_script"])
        self.assertIn("ANTHROPIC_API_KEY", draft["notice"])
        self.assertGreaterEqual(len(draft["body"]), 200)
    def test_ai_draft_uses_the_model_and_sends_branch_facts_not_source_code(self):
        from types import SimpleNamespace
        from unittest import mock
        reply = SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(type="tool_use", input={"title": "How I built a ledger in Python", "summary": "Double-entry basics.", "body": "## What it is\n\nA ledger.", "video_script": "INTRO\nHi."})])
        with override_settings(ANTHROPIC_API_KEY="test-key", AI_MODEL="test-model"), mock.patch("anthropic.Anthropic") as client_class:
            client_class.return_value.messages.create.return_value = reply
            draft = self.draft(kind="video").json()
        self.assertEqual(draft["source"], "ai")
        self.assertEqual(draft["title"], "How I built a ledger in Python")
        call = client_class.return_value.messages.create.call_args.kwargs
        self.assertEqual(call["model"], "test-model")
        prompt = call["messages"][0]["content"]
        self.assertIn("Post balanced entries", prompt)
        self.assertIn("ledger/post.py", prompt)
        self.assertNotIn("return entry", prompt)
    def test_ai_failure_falls_back_to_a_starter_draft(self):
        from unittest import mock
        with override_settings(ANTHROPIC_API_KEY="test-key"), mock.patch("anthropic.Anthropic", side_effect=RuntimeError("network down")):
            draft = self.draft().json()
        self.assertEqual(draft["source"], "starter")
        self.assertIn("unavailable", draft["notice"])
    def test_unknown_branch_is_rejected_when_drafting_and_publishing(self):
        self.assertEqual(self.draft(branch="nope").status_code, 400)
        data = {"title": "Refunds", "kind": "article", "project": self.project.pk, "summary": "", "body": ARTICLE, "is_public": "on"}
        response = self.client.post(reverse("learning:create"), {**data, "branch": "nope"})
        self.assertContains(response, "Pick a branch from this project")
        response = self.client.post(reverse("learning:create"), {**data, "branch": "feature/refunds", "video_script": "INTRO"})
        post = LearningPost.objects.get(title="Refunds")
        self.assertRedirects(response, reverse("learning:detail", args=[post.pk]))
        self.assertEqual(post.branch, "feature/refunds")
    def test_drafts_can_come_from_a_recording_transcript_without_a_project(self):
        transcript = "Today I'll show how the ledger posts balanced entries. Every entry has a debit and a credit."
        response = self.client.post(reverse("learning:studio_draft"), {"project": "", "transcript": transcript, "chapters": "0:00 Intro\n1:05 Posting entries", "kind": "video"})
        draft = response.json()
        self.assertEqual(draft["source"], "starter")
        self.assertEqual(draft["title"], "Today I'll show how the ledger posts balanced entries")
        self.assertIn("- 1:05 Posting entries", draft["body"])
        self.assertIn("your recording", draft["notice"])
        self.assertEqual(self.client.post(reverse("learning:studio_draft"), {"project": ""}).status_code, 400)
        from types import SimpleNamespace
        from unittest import mock
        reply = SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(type="tool_use", input={"title": "Balanced entries", "summary": "s", "body": "b", "video_script": "v"})])
        with override_settings(ANTHROPIC_API_KEY="test-key"), mock.patch("anthropic.Anthropic") as client_class:
            client_class.return_value.messages.create.return_value = reply
            self.client.post(reverse("learning:studio_draft"), {"project": self.project.pk, "branch": "main", "transcript": transcript})
        prompt = client_class.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn('"recording"', prompt)
        self.assertIn("debit and a credit", prompt)
class TimelineTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # publishing is rate limited per user, and user ids repeat between tests
    def test_chapters_are_parsed_sorted_and_validated(self):
        from .timeline import clean_chapters, parse_chapters
        self.assertEqual(clean_chapters("1:20 The data model\n0:00   Intro\n\n1:02:03 Wrap up"), "0:00 Intro\n1:20 The data model\n1:02:03 Wrap up")
        self.assertEqual(parse_chapters("0:00 Intro\nnot a chapter\n0:45 Setup")[1], {"seconds": 45, "stamp": "0:45", "title": "Setup"})
        for bad in ["Intro at the start", "0:75 Too many seconds"]:
            with self.assertRaises(ValueError):
                clean_chapters(bad)
    def test_captions_are_validated_and_read_as_a_transcript(self):
        from .timeline import clean_captions, parse_captions
        vtt = "WEBVTT\n\n1\n00:00:01.500 --> 00:00:04.000\nHello <b>everyone</b>\n\n2\n00:01:05.000 --> 00:01:07.000\nNow the <script>code</script>\n"
        self.assertEqual(parse_captions(vtt), [{"seconds": 1, "stamp": "0:01", "text": "Hello everyone"}, {"seconds": 65, "stamp": "1:05", "text": "Now the code"}])
        self.assertEqual(clean_captions(""), "")
        with self.assertRaises(ValueError):
            clean_captions("1\n00:00:01.000 --> 00:00:02.000\nNo header")
    def test_published_chapters_and_captions_show_on_the_post_and_player(self):
        author = make_user("author@example.com", "Asha", "Rao")
        reader = make_user("reader@example.com", "Ravi", "Reader")
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        with override_settings(MEDIA_ROOT=media):
            self.client.force_login(author)
            video = lambda: SimpleUploadedFile("walkthrough.webm", b"\x1aE\xdf\xa3" + b"\x00" * 64, content_type="video/webm")
            data = {"title": "Ledger tour", "kind": "video", "summary": "", "body": "", "is_public": "on", "chapters": "1:20 Posting\n0:00 Intro", "captions": "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHi, I'm Asha & this is <i>Ledger</i>\n"}
            response = self.client.post(reverse("learning:create"), {**data, "video_file": video(), "chapters": "Posting at one twenty"})
            self.assertContains(response, "isn&#x27;t a chapter")
            self.client.post(reverse("learning:create"), {**data, "video_file": video()})
            post = LearningPost.objects.get(title="Ledger tour")
            self.assertEqual(post.chapters, "0:00 Intro\n1:20 Posting")
            self.client.force_login(reader)
            page = self.client.get(reverse("learning:detail", args=[post.pk]))
            self.assertContains(page, f'<track kind="captions" label="Captions" src="/learn/{post.pk}/captions.vtt" default>')
            self.assertContains(page, '<button type="button" data-seek="80"><span>1:20</span>Posting</button>', html=False)
            self.assertContains(page, "Hi, I&#x27;m Asha &amp; this is Ledger")
            captions = self.client.get(reverse("learning:captions", args=[post.pk]))
            self.assertEqual(captions["Content-Type"], "text/vtt; charset=utf-8")
            self.assertTrue(captions.content.startswith(b"WEBVTT"))
            LearningPost.objects.filter(pk=post.pk).update(is_public=False)
            self.assertEqual(self.client.get(reverse("learning:captions", args=[post.pk])).status_code, 404)
            editor = self.client.get(reverse("learning:create"), {"kind": "video"})
            for control in ['data-setting="layout"', 'value="bottom-left" data-setting="position"', 'value="sunset" data-setting="background"', 'data-setting="captions"', 'data-recorder-action="chapter"', "recorder-scene.js"]:
                self.assertContains(editor, control)
class ArticleFormatTests(SimpleTestCase):
    def test_new_blocks_render_safely(self):
        html = render_article("A *quiet* ~~old~~ word and 2*3*4 stays.\n\n1. First\n2. Second\n\n> Just a quote\n\n> [!TIP]\n> Use **indexes**\n\n---\n\n~~~js\nconst a = '```';\n~~~")
        self.assertIn("<em>quiet</em> <del>old</del>", html)
        self.assertIn("2*3*4 stays", html)
        self.assertIn("<ol><li>First</li><li>Second</li></ol>", html)
        self.assertIn("<blockquote><p>Just a quote</p></blockquote>", html)
        self.assertIn('<aside class="callout callout-tip"><b class="callout-title">Tip</b><p>Use <strong>indexes</strong></p></aside>', html)
        self.assertIn("<hr>", html)
        self.assertIn('<pre><code class="language-js">const a = &#x27;```&#x27;;</code></pre>', html)
    def test_only_uploaded_images_are_shown_and_headings_get_unique_anchors(self):
        from .formatting import article_outline
        html = render_article("![Login page](/media/learning/images/abc123.png)\n\n![x](https://evil.example/track.png)\n\n![x](/media/learning/images/../secret.png)\n\n## Setup\n\n## Setup\n\n```\n## not a heading\n```")
        self.assertIn('<figure><img src="/media/learning/images/abc123.png" alt="Login page" loading="lazy"><figcaption>Login page</figcaption></figure>', html)
        self.assertNotIn('<img src="https://evil.example', html)
        self.assertNotIn('src="/media/learning/images/../secret.png"', html)
        self.assertIn('<h3 id="setup">Setup</h3>', html)
        self.assertIn('<h3 id="setup-2">Setup</h3>', html)
        self.assertEqual([item["anchor"] for item in article_outline("## Setup\n\n## Setup\n\n```\n## not a heading\n```")], ["setup", "setup-2"])
class ArticleStudioTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        from apps.core.git_service import commit_file, initialize_repository
        from apps.core.models import Repository
        cache.clear()
        self.storage = tempfile.TemporaryDirectory()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(GIT_REPOSITORY_ROOT=self.storage.name, MEDIA_ROOT=self.media, ANTHROPIC_API_KEY="")
        self.override.enable()
        self.author = make_user("author@example.com", "Asha", "Rao")
        self.project = Project.objects.create(owner=self.author, title="Ledger")
        repository = Repository.objects.create(project=self.project, owner=self.author, slug="ledger")
        initialize_repository(repository)
        commit_file(repository, "ledger/post.py", "def post(entry):\n    return entry\n", self.author, "Add posting")
        commit_file(repository, "logo.png", "\x00binary", self.author, "Add logo")
        self.client.force_login(self.author)
    def tearDown(self):
        self.override.disable()
        self.storage.cleanup()
        shutil.rmtree(self.media, ignore_errors=True)
    def test_preview_renders_like_the_published_post(self):
        response = self.client.post(reverse("learning:studio_preview"), {"body": "## Plan\n<script>x</script> **go**"})
        self.assertEqual(response.json()["html"], '<h3 id="plan">Plan</h3>\n<p>&lt;script&gt;x&lt;/script&gt; <strong>go</strong></p>')
    def test_images_upload_as_markdown_and_other_files_are_refused(self):
        import io
        from PIL import Image
        picture = io.BytesIO()
        Image.new("RGB", (8, 8), "#2563eb").save(picture, "PNG")
        response = self.client.post(reverse("learning:studio_image"), {"image": SimpleUploadedFile("my shot.png", picture.getvalue(), content_type="image/png"), "alt": "Login [page]"})
        data = response.json()
        self.assertRegex(data["url"], r"^/media/learning/images/[0-9a-f]{32}\.png$")
        self.assertEqual(data["markdown"], f"![Login page]({data['url']})")
        self.assertIn("<figure>", render_article(data["markdown"]))
        refused = self.client.post(reverse("learning:studio_image"), {"image": SimpleUploadedFile("notes.png", b"not an image", content_type="image/png")})
        self.assertEqual(refused.status_code, 400)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("learning:studio_image")).status_code, 302)
    def test_repository_files_can_be_listed_and_read_by_the_owner_only(self):
        params = {"project": self.project.pk, "branch": "main"}
        self.assertEqual(self.client.get(reverse("learning:studio_files"), params).json()["paths"], ["ledger/post.py", "logo.png"])
        file = self.client.get(reverse("learning:studio_file"), {**params, "path": "ledger/post.py"}).json()
        self.assertEqual((file["language"], file["content"]), ("py", "def post(entry):\n    return entry\n"))
        self.assertEqual(self.client.get(reverse("learning:studio_file"), {**params, "path": "logo.png"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("learning:studio_file"), {**params, "path": "../secrets"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("learning:studio_file"), {**params, "path": "missing.py"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("learning:studio_files"), {**params, "branch": "nope"}).status_code, 400)
        self.client.force_login(make_user("other@example.com", "Oth", "Er"))
        self.assertEqual(self.client.get(reverse("learning:studio_files"), params).status_code, 404)
    def test_ai_writing_help_needs_a_key_and_returns_the_rewrite(self):
        from types import SimpleNamespace
        from unittest import mock
        url = reverse("learning:studio_assist")
        self.assertEqual(self.client.post(url, {"action": "improve", "text": "the ledger is fast"}).status_code, 503)
        self.assertEqual(self.client.post(url, {"action": "delete-everything", "text": "x"}).status_code, 400)
        reply = SimpleNamespace(content=[SimpleNamespace(type="text", text="The ledger posts entries quickly.")])
        with override_settings(ANTHROPIC_API_KEY="test-key"), mock.patch("anthropic.Anthropic") as client_class:
            client_class.return_value.messages.create.return_value = reply
            response = self.client.post(url, {"action": "improve", "text": "the ledger is fast", "title": "Ledger"})
        self.assertEqual(response.json(), {"text": "The ledger posts entries quickly."})
        prompt = client_class.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("<text>\nthe ledger is fast\n</text>", prompt)
        self.assertIn("Article title: Ledger", prompt)
    def test_editor_and_reading_tools_are_on_the_pages(self):
        editor = self.client.get(reverse("learning:create"))
        for control in ['data-format="voice"', 'data-template="tutorial"', 'data-callout="tip"', 'data-assist="explain"', 'data-editor-view="split"', 'id="repo-code-dialog"', "article-editor.js", 'data-ai="off"']:
            self.assertContains(editor, control)
        post = LearningPost.objects.create(author=self.author, title="Ledger notes", body="## Setup\nInstall it.\n\n## Usage\nRun it.")
        page = self.client.get(reverse("learning:detail", args=[post.pk]))
        self.assertContains(page, '<nav class="ig-toc" aria-label="On this page">')
        self.assertContains(page, '<a href="#usage">Usage</a>')
        self.assertContains(page, "data-listen")
