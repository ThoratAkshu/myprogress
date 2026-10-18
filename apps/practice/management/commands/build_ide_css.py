from django.core.management.base import BaseCommand
from apps.practice.ide_theme import OUTPUT, build


class Command(BaseCommand):
    help = "Regenerate the developer UI's dark theme (ide-auto.css) from the app's stylesheets."

    def handle(self, *args, **options):
        css = build()
        OUTPUT.write_text(css, encoding="utf8", newline="\n")
        self.stdout.write(f"Wrote {OUTPUT.name}: {css.count('{')} rules, {len(css) // 1024} KB")
