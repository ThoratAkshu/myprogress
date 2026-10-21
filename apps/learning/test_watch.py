"""Watch (videos one at a time, like Reels), and videos that play by themselves in the Learn feed."""
import json
import re
from datetime import timedelta
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Follow
from apps.core.models import ContentView, LearningPost, PostLike
from apps.core.services import record_activity
from apps.organizations import services
from .media import YOUTUBE_VIDEO_REGEX, youtube_embed_url
from .tests import make_user


def video(author, title, minutes_ago, **fields):
    post = LearningPost.objects.create(author=author, title=title, kind="video", **{"video_file": f"learning/videos/{title.lower().replace(' ', '-')}.webm", **fields})
    LearningPost.objects.filter(pk=post.pk).update(published_at=timezone.now() - timedelta(minutes=minutes_ago))
    return post


def order(response):
    return [int(pk) for pk in re.findall(r'data-reel data-post="(\d+)"', response.content.decode())]


class WatchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.viewer = make_user("asha@example.com", "Asha", "Rao", handle="asha")
        self.author = make_user("dev@example.com", "Dev", "Patil", handle="dev")
        self.client.force_login(self.viewer)

    def test_public_videos_play_unwatched_first_then_watched_then_your_own(self):
        newest = video(self.author, "Newest", 1)
        older = video(self.author, "Older", 5)
        watched = video(self.author, "Watched before", 2)
        mine = video(self.viewer, "My own", 0)
        youtube = LearningPost.objects.create(author=self.author, title="On YouTube", kind="video", video_url="https://youtu.be/dQw4w9WgXcQ")
        LearningPost.objects.filter(pk=youtube.pk).update(published_at=timezone.now() - timedelta(minutes=10))
        video(self.author, "Draft", 3, is_public=False)
        LearningPost.objects.create(author=self.author, title="An article", kind="article", body="Text")
        LearningPost.objects.create(author=self.author, title="Elsewhere", kind="video", video_url="https://vimeo.com/123")
        LearningPost.objects.create(author=self.author, title="Not a video", kind="video", video_url="https://www.youtube.com/watch?v=abc")
        ContentView.objects.create(post=watched, viewer=self.viewer, session_key="x", viewed_on=timezone.localdate())
        response = self.client.get(reverse("learning:watch"))
        self.assertEqual(order(response), [newest.pk, older.pk, youtube.pk, watched.pk, mine.pk])
        self.assertContains(response, 'data-reel-embed="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"')
        self.assertContains(response, f'data-count-view="{reverse("learning:watched", args=[newest.pk])}"')
        self.assertContains(response, "data-autoplay muted loop playsinline")
        self.assertNotContains(response, 'action="/u/asha/follow/"')  # no Follow on your own video

    def test_a_shared_video_comes_first_and_more_load_without_repeats(self):
        posts = [video(self.author, f"Lesson {number}", number) for number in range(9)]
        start = posts[7]
        first_page = order(self.client.get(reverse("learning:watch"), {"post": start.pk}))
        self.assertEqual((first_page[0], len(first_page)), (start.pk, 6))
        more = order(self.client.get(reverse("learning:watch"), {"more": "1", "shown": ",".join(map(str, first_page))}))
        self.assertEqual(sorted(first_page + more), sorted(post.pk for post in posts))
        self.assertEqual(order(self.client.get(reverse("learning:watch"), {"more": "1", "shown": ",".join(str(post.pk) for post in posts)})), [])
        draft = video(self.author, "Draft", 1, is_public=False)
        self.assertNotEqual(order(self.client.get(reverse("learning:watch"), {"post": draft.pk}))[0], draft.pk)

    def test_likes_and_follows_answer_without_leaving_the_page(self):
        post = video(self.author, "Binary search", 1)
        xhr = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        self.assertEqual(json.loads(self.client.post(reverse("learning:like", args=[post.pk]), **xhr).content), {"liked": True, "likes": 1})
        self.assertEqual(json.loads(self.client.post(reverse("learning:like", args=[post.pk]), **xhr).content), {"liked": False, "likes": 0})
        self.assertRedirects(self.client.post(reverse("learning:like", args=[post.pk]), {"next": "/learn/watch/?post=1"}), "/learn/watch/?post=1", fetch_redirect_response=False)
        self.assertTrue(PostLike.objects.filter(post=post, user=self.viewer).exists())
        response = self.client.get(reverse("learning:watch"))
        self.assertContains(response, 'class="reel-action liked" aria-pressed="true" aria-label="Unlike"')
        self.assertEqual(json.loads(self.client.post(reverse("landing:follow", args=["dev"]), **xhr).content)["following"], True)
        self.assertContains(self.client.get(reverse("learning:watch")), 'class="reel-follow is-following">Following')

    def test_three_seconds_of_playing_count_one_view_and_never_the_authors(self):
        post = video(self.author, "Binary search", 1)
        for _ in range(2):
            self.assertEqual(self.client.post(reverse("learning:watched", args=[post.pk])).status_code, 204)
        post.refresh_from_db()
        self.assertEqual(post.views, 1)  # once per session a day, like opening the post
        self.client.force_login(self.author)
        self.client.post(reverse("learning:watched", args=[post.pk]))
        post.refresh_from_db()
        self.assertEqual(post.views, 1)
        office = make_user("office@institute.example", "Sunrise", "Office", role="organization", handle="office")
        institute = services.create_organization(office, {"name": "Sunrise", "kind": "institute", "city": "", "about": "", "website": "", "join_requires_approval": False})
        lecture = video(office, "Members only", 1, is_public=False, organization=institute)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse("learning:watched", args=[lecture.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("learning:watched", args=[post.pk])).status_code, 405)

    def test_the_learn_feed_plays_videos_and_leads_to_watch(self):
        post = video(self.author, "Binary search", 1)
        page = self.client.get(reverse("landing:workspace_section", args=["learning"]))
        self.assertContains(page, f'href="{reverse("learning:watch")}"')
        self.assertContains(page, "data-feed-video")
        self.assertContains(page, f'data-watch-url="{reverse("learning:watch")}?post={post.pk}"')  # a tap opens it in Watch
        self.assertContains(page, f'action="{reverse("learning:like", args=[post.pk])}" data-like')

    def test_nothing_to_watch_yet(self):
        page = self.client.get(reverse("learning:watch"))
        self.assertContains(page, "No videos yet")
        self.assertContains(page, "Record a video")
        recruiter = make_user("hr@acme.io", "Neha", "Shah", role="recruiter", handle="hr")
        self.client.force_login(recruiter)
        page = self.client.get(reverse("learning:watch"))
        self.assertContains(page, "No videos yet")
        self.assertNotContains(page, "Record a video")  # recruiters don't make posts
        self.client.logout()
        self.assertEqual(self.client.get(reverse("learning:watch")).status_code, 302)


class YouTubeLinkTests(SimpleTestCase):
    def test_watch_lists_exactly_the_links_the_player_can_embed(self):
        pattern = re.compile(YOUTUBE_VIDEO_REGEX)
        for url in ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ", "https://youtube.com/shorts/dQw4w9WgXcQ?feature=share",
                    "https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ", "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "https://www.youtube.com/live/dQw4w9WgXcQ",
                    "https://www.youtube.com/watch?v=abc", "https://www.youtube.com/@channel", "https://youtu.be/dQw4w9WgXcQxx", "https://vimeo.com/123", ""]:
            self.assertEqual(bool(pattern.search(url)), bool(youtube_embed_url(url)), url)


class HomeFeedTests(TestCase):
    """The home feed plays videos in place like the Learn feed, and shows a Watch row once there are a few videos."""
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.viewer = make_user("asha@example.com", "Asha", "Rao", handle="asha")
        self.author = make_user("dev@example.com", "Dev", "Patil", handle="dev")
        Follow.objects.create(follower=self.viewer, following=self.author)
        self.client.force_login(self.viewer)

    def publish(self, post):
        record_activity(post.author, "learning", "published_learning", 0, {"post_id": post.pk})
        return post

    def test_videos_play_in_the_feed_and_a_tap_opens_watch(self):
        post = self.publish(video(self.author, "Binary search", 1))
        self.publish(LearningPost.objects.create(author=self.author, title="Revision notes", kind="article", body="Text " * 50))
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, f'data-feed-video data-count-view="{reverse("learning:watched", args=[post.pk])}" data-watch-url="{reverse("learning:watch")}?post={post.pk}"')
        self.assertContains(page, f'action="{reverse("learning:like", args=[post.pk])}" data-like')
        self.assertContains(page, "<b>Revision notes</b><small>1 min read</small>")  # an article without a picture: its title on a big cover
        self.assertNotContains(page, 'class="card watch-shelf"')  # one video isn't a row

    def test_the_watch_row_shows_once_there_are_three_videos(self):
        posts = [self.publish(video(self.author, f"Lesson {number}", number)) for number in range(3)]
        page = self.client.get(reverse("landing:dashboard"))
        self.assertContains(page, 'class="card watch-shelf"', count=1)
        self.assertContains(page, '<a class="watch-tile', count=3)
        self.assertContains(page, f'href="{reverse("learning:watch")}?post={posts[0].pk}"')
        self.assertNotContains(self.client.get(reverse("landing:dashboard"), {"show": "articles"}), 'class="card watch-shelf"')
        self.assertContains(self.client.get(reverse("landing:dashboard"), {"show": "videos"}), 'class="card watch-shelf"')
