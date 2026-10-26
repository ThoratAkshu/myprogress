"""Resumes made from a member's MyProgress work. Only their choices are stored here; the facts (projects, code,
certificates, write-ups, score) are read live each time, so a resume is never out of date."""
from django.contrib.auth.models import User
from django.db import models
class ResumeSettings(models.Model):
    TEMPLATES = [("modern", "Modern"), ("classic", "Classic")]
    SECTIONS = [("certificates", "Certificates"), ("writing", "Writing and videos"), ("practice", "Practice problems"), ("stats", "MyProgress stats")]
    MAX_PROJECTS = 6
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="resume_settings")
    template = models.CharField(max_length=10, choices=TEMPLATES, default="modern")
    summary = models.TextField(max_length=800, blank=True, help_text="Empty uses a summary written from your work")
    phone = models.CharField(max_length=20, blank=True)
    show_email = models.BooleanField(default=True)
    project_ids = models.JSONField(default=list, blank=True, help_text="Chosen projects in order; empty picks the strongest")
    hidden_sections = models.JSONField(default=list, blank=True)
    recruiters_can_download = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return f"Resume settings for {self.user}"
