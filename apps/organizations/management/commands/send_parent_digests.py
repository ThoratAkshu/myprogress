from django.conf import settings
from django.core.management.base import BaseCommand
from apps.organizations import services
class Command(BaseCommand):
    help = "Weekly: emails each parent or guardian a summary of their student's week. Each parent gets at most one every 6 days, so an extra run sends nothing twice."
    def add_arguments(self, parser):
        parser.add_argument("--site-url", default="", help="Address for links in the email, like https://myprogress.example.com (defaults to the SITE_URL setting)")
    def handle(self, **options):
        site_url = (options["site_url"] or settings.SITE_URL).rstrip("/")
        sent, quiet = services.send_parent_digests(site_url)
        self.stdout.write(f"Sent {sent} weekly parent email{'s' if sent != 1 else ''}." + (f" Skipped {quiet} with nothing new this week." if quiet else ""))
