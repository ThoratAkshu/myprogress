from datetime import date
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from apps.earnings import services
from apps.earnings.models import EarningSettings, PaymentRun
from apps.earnings.payouts import get_provider
class Command(BaseCommand):
    help = "Run the monthly payment cycle. Schedule it daily: it closes last month on the 1st, prepares payments on payment day, sends them when auto-send is on, and checks payments still sending."
    def add_arguments(self, parser):
        parser.add_argument("--today", help="Act as if today were this date (YYYY-MM-DD), for testing")
    def handle(self, today=None, **options):
        try:
            today = date.fromisoformat(today) if today else timezone.localdate()
        except ValueError:
            raise CommandError("Use --today YYYY-MM-DD.")
        rules = EarningSettings.current()
        last_month = services.previous_month(today.replace(day=1))
        run = PaymentRun.objects.filter(month=last_month).first()
        if run is None:
            run, _ = services.close_month(last_month, today=today)
            self.stdout.write(f"Closed {last_month:%B %Y}; payments scheduled for {run.scheduled_for}.")
        if run.status == "scheduled" and today >= run.scheduled_for:
            run, candidates = services.prepare_run(run)
            self.stdout.write(f"Prepared {len(candidates['to_pay'])} payments, {services.rupees(candidates['total_net'])} to send; {len(candidates['held'])} on hold.")
        if run.status == "ready" and rules.auto_send and get_provider():
            try:
                sent, failures = services.send_run(run)
                self.stdout.write(f"Sent {sent} payments; {len(failures)} failed.")
            except services.PayoutError as error:
                self.stderr.write(f"Payments were not sent: {error}")
        checked = services.sync_sending()
        if checked:
            self.stdout.write(f"Checked {checked} payments still sending.")
