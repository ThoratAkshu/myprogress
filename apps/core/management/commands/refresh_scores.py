from bisect import bisect_left
from django.core.management.base import BaseCommand
from apps.accounts.models import Profile
from apps.core.services import calculate_score, record_rank_snapshots
class Command(BaseCommand):
    help = "Recalculate every developer's progress score and global rank. Schedule daily so time-windowed points decay."
    def handle(self, *args, **options):
        profiles = list(Profile.objects.filter(role="developer").select_related("user"))
        for profile in profiles:
            profile.score = calculate_score(profile.user)
        descending = sorted(-profile.score for profile in profiles)
        for profile in profiles:
            profile.rank = bisect_left(descending, -profile.score) + 1
        Profile.objects.bulk_update(profiles, ["score", "rank"], batch_size=500)
        record_rank_snapshots(replace=True)
        self.stdout.write(self.style.SUCCESS(f"Refreshed {len(profiles)} developer scores."))
