from django.db import models
from django.contrib.auth.models import User
class Notification(models.Model):
    KIND_CHOICES = [("follow", "New follower"), ("like", "Like"), ("comment", "Comment"), ("contact_request", "Contact request"), ("contact_response", "Contact response"), ("collaborator", "Repository access"), ("issue", "Issue activity"), ("pull", "Pull request activity"), ("earnings", "Earnings")]
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    text = models.CharField(max_length=255)
    url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at"], name="notification_unread_idx")]
    def __str__(self):
        return self.text
