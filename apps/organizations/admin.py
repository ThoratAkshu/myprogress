from django.contrib import admin
from .models import ChannelPost, Invite, Membership, Organization, Submission, Task
@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "owner", "city", "created_at"]
    search_fields = ["name", "slug", "owner__email"]
@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["organization", "user", "role", "status", "group", "joined_at"]
    list_filter = ["role", "status"]
    search_fields = ["organization__name", "user__email"]
@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ["organization", "email", "role", "created_at", "accepted_at"]
@admin.register(ChannelPost)
class ChannelPostAdmin(admin.ModelAdmin):
    list_display = ["organization", "kind", "title", "author", "created_at"]
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["organization", "title", "due_at", "points"]
@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["task", "student", "status", "score", "updated_at"]
    list_filter = ["status"]
