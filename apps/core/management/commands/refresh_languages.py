from django.core.management.base import BaseCommand
from apps.core.git_service import refresh_repository_languages, repository_path
from apps.core.models import Repository
class Command(BaseCommand):
    help = "Recompute code languages for every repository (for example, repositories pushed before language detection existed)."
    def handle(self, *args, **options):
        updated, missing, failed = 0, 0, 0
        for repository in Repository.objects.iterator():
            if not repository_path(repository).exists():
                missing += 1
                continue
            try:
                refresh_repository_languages(repository)
                updated += 1
            except Exception as error:
                failed += 1
                self.stderr.write(f"{repository}: {error}")
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} repositories ({missing} without storage, {failed} failed)."))
