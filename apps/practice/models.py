"""Developer mode: students and professionals practise in their languages, at their level, all over MyProgress."""
from django.contrib.auth.models import User
from django.db import models

LANGUAGES = [("python", "Python"), ("javascript", "JavaScript"), ("java", "Java"), ("cpp", "C++")]
LEVELS = [("beginner", "Beginner"), ("intermediate", "Intermediate"), ("advanced", "Advanced")]


class PracticeProfile(models.Model):
    """Someone's developer mode: on or off, the languages they practise and their level."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="practice")
    enabled = models.BooleanField(default=True)
    languages = models.JSONField(default=list, help_text="Language keys, Python first by default")
    level = models.CharField(max_length=20, choices=LEVELS, default="beginner")
    ide_ui = models.BooleanField(default=True, help_text="Show MyProgress as a code editor: the developer UI")
    started_at = models.DateTimeField(auto_now_add=True)

    @property
    def language_labels(self):
        names = dict(LANGUAGES)
        return [names[key] for key in self.languages if key in names]


class Question(models.Model):
    """A multiple-choice question: a concept, what some code prints, or where its bug is. Seeded questions keep a
    stable key, so editing the bank updates them in place."""
    KINDS = [("concept", "Concept"), ("output", "What does it print?"), ("bug", "Find the bug")]
    key = models.SlugField(max_length=80, unique=True)
    language = models.CharField(max_length=20, choices=LANGUAGES, db_index=True)
    level = models.CharField(max_length=20, choices=LEVELS, db_index=True)
    kind = models.CharField(max_length=20, choices=KINDS)
    topic = models.CharField(max_length=60)
    prompt = models.TextField()
    code = models.TextField(blank=True)
    choices = models.JSONField()
    answer = models.PositiveSmallIntegerField(help_text="Index of the right choice")
    explanation = models.TextField()
    source = models.CharField(max_length=10, default="bank", help_text="bank: written in bank.py")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["language", "level", "key"]

    def __str__(self):
        return self.key


class Attempt(models.Model):
    """One answer, wherever it was given: at sign-in, in the Learn dock, or in a quiz."""
    CONTEXTS = [("signin", "Sign-in"), ("dock", "Learn dock"), ("quiz", "Quiz")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="practice_attempts")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="attempts")
    chosen = models.PositiveSmallIntegerField()
    correct = models.BooleanField()
    context = models.CharField(max_length=10, choices=CONTEXTS)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class ChallengeSolve(models.Model):
    """A code-lab challenge solved: every test passed in the person's browser. helped: after "Show me how"."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="challenge_solves")
    key = models.SlugField(max_length=80)
    language = models.CharField(max_length=20, choices=LANGUAGES)
    code = models.TextField()
    helped = models.BooleanField(default=False)
    solved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="challenge_solved_once")]
