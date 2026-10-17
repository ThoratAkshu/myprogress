from django.core.management.base import BaseCommand
from apps.organizations import services
class Command(BaseCommand):
    help = "Organization jobs to run every few minutes: publishes scheduled channel posts, lectures and tasks, and reminds members 15 minutes before a live class."
    def handle(self, **options):
        published, released, reminded = services.run_due_jobs()
        if published:
            self.stdout.write(f"Published {published} scheduled post{'s' if published != 1 else ''}.")
        if released:
            self.stdout.write(f"Released {released} scheduled lecture{'s' if released != 1 else ''} or task{'s' if released != 1 else ''}.")
        if reminded:
            self.stdout.write(f"Sent reminders for {reminded} class{'es' if reminded != 1 else ''}.")
