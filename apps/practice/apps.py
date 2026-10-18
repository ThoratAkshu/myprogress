from django.apps import AppConfig
from django.db.models.signals import post_migrate


def sync_question_bank(sender, **kwargs):
    from .services import sync_questions
    sync_questions()


class PracticeConfig(AppConfig):
    name = "apps.practice"

    def ready(self):
        # The question bank lives in code (bank.py) and is brought up to date after every migrate.
        post_migrate.connect(sync_question_bank, sender=self)
