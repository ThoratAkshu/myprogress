from django.db import models
from django.contrib.auth.models import User
class Profile(models.Model):
    ROLE_CHOICES = [("developer", "Developer"), ("recruiter", "Recruiter"), ("organization", "Organization")]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="developer")
    headline = models.CharField(max_length=160, blank=True)
    location = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    skills = models.CharField(max_length=500, blank=True, help_text="Comma-separated skills")
    rank = models.PositiveIntegerField(null=True, blank=True)
    score = models.PositiveIntegerField(default=0)
    recruiter_visible = models.BooleanField(default=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} profile"
    @property
    def skill_list(self):
        return [skill.strip() for skill in self.skills.split(",") if skill.strip()]
class Follow(models.Model):
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name="following_relationships")
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name="follower_relationships")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["follower", "following"], name="unique_user_follow")]
        ordering = ["-created_at"]
    def __str__(self):
        return f"{self.follower} follows {self.following}"
