from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import Profile
from .models import Notification
from .services import notify
def make_user(email, first_name, last_name, role="developer"):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, role=role)
    return user
class NotificationTests(TestCase):
    def test_follow_and_recruiter_events_notify_the_other_person(self):
        developer = make_user("dev@example.com", "Dev", "Eloper")
        fan = make_user("fan@example.com", "Fan", "Person")
        recruiter = make_user("hr@example.com", "Hana", "Iyer", role="recruiter")
        self.client.force_login(fan)
        self.client.post(reverse("landing:follow", args=["dev-eloper"]))
        self.client.post(reverse("landing:follow", args=["dev-eloper"]))
        self.client.force_login(recruiter)
        self.client.post(reverse("recruiting:contact", args=["dev-eloper"]), {"role_title": "Backend Engineer", "message": "Your ledger project stood out to our team."})
        texts = list(Notification.objects.filter(recipient=developer).order_by("created_at").values_list("text", flat=True))
        self.assertEqual(texts, ["Fan Person started following you", "Hana Iyer wants to talk to you about Backend Engineer"])
        self.client.force_login(developer)
        request_id = developer.contact_requests.get().pk
        self.client.post(reverse("recruiting:respond_contact", args=[request_id]), {"action": "accept"})
        self.assertEqual(Notification.objects.get(recipient=recruiter).text, "Dev Eloper accepted your request about Backend Engineer")
    def test_list_marks_read_and_shows_only_my_notifications(self):
        me = make_user("me@example.com", "Me", "Dev")
        other = make_user("other@example.com", "Other", "Dev")
        notify(me, other, "like", "Other Dev liked “Ledger”", "/learn/1/")
        notify(other, me, "like", "Me Dev liked “Secret”", "/learn/2/")
        self.assertIsNone(notify(me, me, "like", "self", "/"))
        self.client.force_login(me)
        dashboard = self.client.get(reverse("landing:dashboard"))
        self.assertContains(dashboard, 'aria-label="Notifications">♢<i></i>')
        page = self.client.get(reverse("notifications:list"))
        self.assertContains(page, "Other Dev liked “Ledger”")
        self.assertNotContains(page, "Secret")
        self.assertContains(page, 'class="notification-row unread"')
        self.assertFalse(me.notifications.filter(read_at__isnull=True).exists())
        self.assertNotContains(self.client.get(reverse("landing:dashboard")), 'aria-label="Notifications">♢<i></i>')
        self.assertTrue(other.notifications.filter(read_at__isnull=True).exists())
