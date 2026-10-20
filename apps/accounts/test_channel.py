"""Every account brands a public channel: name, logo, banner, colour, and links."""
import io
import os
import shutil
import tempfile
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from apps.accounts.models import Profile
from apps.core.models import LearningPost
from apps.organizations import services

MEDIA = tempfile.mkdtemp()
# Who they are; each account type reads what applies to it.
IDENTITY = {"occupation": "student", "institution": "Pune University", "company_name": "Acme"}
BODY = "Clear notes on how loops work, with examples and practice questions for every step. " * 4


def make_user(email, role="developer", first_name="Asha", last_name="Rao"):
    user = User.objects.create_user(username=email, email=email, password="StrongPass!482", first_name=first_name, last_name=last_name)
    Profile.objects.create(user=user, role=role, handle=email.split("@")[0].replace(".", "-"))
    return user


def picture(size, kind="PNG", name="logo.png"):
    buffer = io.BytesIO()
    Image.new("RGB", size, "#0369a1").save(buffer, kind)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{kind.lower()}")


@override_settings(MEDIA_ROOT=MEDIA)
class ChannelTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.institute = make_user("office@sunrise.example", role="organization", first_name="Sunrise", last_name="Office")
        self.organization = services.create_organization(self.institute, {"name": "Sunrise Coding Institute", "kind": "institute", "city": "Pune", "about": "Full-stack batches", "website": "", "join_requires_approval": False})

    def save(self, user, **data):
        self.client.force_login(user)
        return self.client.post(reverse("landing:channel_settings"), {"channel_name": "", "brand_color": "ocean", **data})

    def edit(self, user, **data):
        """Edit profile, where the headline, about and links are."""
        self.client.force_login(user)
        fields = {"first_name": user.first_name, "last_name": user.last_name, "handle": user.profile.handle, "headline": "", "bio": "", **IDENTITY}
        organization = user.organizations_owned.first()
        if organization:
            fields.update({"org-name": organization.name, "org-kind": organization.kind, "org-city": organization.city, "org-website": organization.website, "org-about": organization.about})
        return self.client.post(reverse("landing:update_profile"), {**fields, **data})

    def test_every_account_type_can_customize_its_channel(self):
        for user in [self.institute, make_user("hr@company.example", role="recruiter"), make_user("dev@example.com")]:
            self.client.force_login(user)
            self.assertContains(self.client.get(reverse("landing:channel_settings")), "Customize your channel")
            self.assertContains(self.client.get(reverse("landing:update_profile")), 'name="link_youtube"')
        page = self.client.get(reverse("landing:channel_settings"))
        self.assertContains(page, "Make one")
        self.assertContains(page, reverse("landing:update_profile"))
        self.assertNotContains(page, 'name="link_youtube"')  # what the channel says is in Edit profile
        self.assertNotContains(page, 'name="headline"')

    def test_logo_banner_colour_and_links_are_saved_cleaned_up(self):
        response = self.save(self.institute, channel_name="Sunrise Academy", brand_color="emerald", avatar=picture((900, 500)), banner=picture((1800, 600), "JPEG", "banner.jpg"))
        profile = Profile.objects.get(user=self.institute)
        self.assertRedirects(response, reverse("landing:public_profile", args=[profile.handle]))
        self.assertEqual((profile.channel_name, profile.brand_color), ("Sunrise Academy", "emerald"))
        self.edit(self.institute, headline="Coding classes in Pune", link_youtube="https://www.youtube.com/@sunrise", link_website="https://sunrise.example", link_instagram="")
        profile.refresh_from_db()
        self.assertEqual((profile.headline, profile.links), ("Coding classes in Pune", {"youtube": "https://www.youtube.com/@sunrise", "website": "https://sunrise.example"}))
        self.assertTrue(profile.avatar)  # saving Edit profile without a new photo keeps the logo
        with Image.open(profile.avatar.path) as logo:
            self.assertEqual((logo.format, logo.size), ("PNG", (400, 400)))  # re-encoded, cropped square
        with Image.open(profile.banner.path) as banner:
            self.assertEqual(banner.format, "JPEG")
        old_logo = profile.avatar.path
        self.save(self.institute, channel_name="Sunrise Academy", avatar=picture((400, 400)))
        self.assertFalse(os.path.exists(old_logo))  # the replaced logo is deleted
        profile.refresh_from_db()
        self.save(self.institute, channel_name="Sunrise Academy", remove_logo="on", remove_banner="on")
        profile.refresh_from_db()
        self.assertEqual((profile.avatar.name, profile.banner.name), ("", ""))

    def test_bad_links_and_files_are_refused(self):
        response = self.edit(self.institute, link_youtube="https://evil.example/watch", link_x="http://x.com/sunrise", avatar=SimpleUploadedFile("logo.png", b"not really an image", content_type="image/png"))
        self.assertContains(response, "That isn&#x27;t a YouTube address")
        self.assertContains(response, "Use a full https:// address for X")
        self.assertContains(response, "Upload a valid image")
        self.assertContains(self.save(self.institute, avatar=SimpleUploadedFile("logo.png", b"not really an image", content_type="image/png")), "Upload a valid image")
        svg = SimpleUploadedFile("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>', content_type="image/svg+xml")
        self.assertContains(self.save(self.institute, avatar=svg), "Upload a valid image")
        self.assertContains(self.save(self.institute, banner=picture((300, 100))), "at least 600 pixels wide")
        profile = Profile.objects.get(user=self.institute)
        self.assertEqual((profile.avatar.name, profile.links), ("", {}))

    def test_an_institute_gets_a_public_channel_under_its_own_name(self):
        video = LearningPost.objects.create(author=self.institute, title="Loops, live", kind="video", video_url="https://www.youtube.com/watch?v=abc", body="", is_public=True)
        LearningPost.objects.create(author=self.institute, title="Revision sheet: loops", kind="article", body=BODY, is_public=True)
        LearningPost.objects.create(author=self.institute, title="Batch A only", kind="article", body=BODY, is_public=False, organization=self.organization)
        Profile.objects.filter(user=self.institute).update(links={"website": "https://sunrise.example"})
        handle = self.institute.profile.handle
        page = self.client.get(reverse("landing:public_profile", args=[handle]))
        for text in ["<h1 class=\"profile-name\">Sunrise Coding Institute", "Loops, live", "Revision sheet: loops", "Videos <b>1</b>", "Notes <b>1</b>", "Institute or coaching centre", 'rel="me noopener nofollow ugc"']:
            self.assertContains(page, text)
        self.assertNotContains(page, "Batch A only")
        self.assertNotContains(page, "Repositories")
        self.assertNotContains(page, "Open your class channel")
        about = self.client.get(reverse("landing:public_profile", args=[handle]), {"tab": "about"})
        self.assertContains(about, "1 member")
        self.assertContains(about, "Full-stack batches")
        student = make_user("student@example.com")
        services.join(self.organization, student)
        self.client.force_login(student)
        self.assertContains(self.client.get(reverse("landing:public_profile", args=[handle])), "Open your class channel")
        self.assertEqual(video.author, self.institute)

    def test_logos_replace_initials_across_the_site(self):
        self.save(self.institute, avatar=picture((400, 400)))
        logo = Profile.objects.get(user=self.institute).avatar.url
        developer = make_user("dev@example.com")
        self.client.force_login(developer)
        page = self.client.get(reverse("landing:public_profile", args=[self.institute.profile.handle]))
        self.assertContains(page, f'<img src="{logo}" alt="" loading="lazy" decoding="async">')
        services.join(self.organization, developer)
        self.assertContains(self.client.get(reverse("organizations:channel", args=[self.organization.slug])), logo)
        portfolio = self.client.get(reverse("landing:public_profile", args=[developer.profile.handle]))
        self.assertContains(portfolio, "Repositories")
        self.assertContains(portfolio, ">AR</span>")  # no logo yet: initials
