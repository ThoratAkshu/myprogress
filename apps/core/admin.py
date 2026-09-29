from django.contrib import admin
from .models import ActivityEvent, ContentView, DailyLoopCompletion, EarningTransaction, GitAccessToken, LearningPost, Project, ProjectMilestone, Repository, RepositoryCollaborator
admin.site.register(Project)
admin.site.register(LearningPost)
admin.site.register(ProjectMilestone)
admin.site.register(ContentView)
admin.site.register(ActivityEvent)
admin.site.register(EarningTransaction)
admin.site.register(DailyLoopCompletion)
admin.site.register(Repository)
admin.site.register(RepositoryCollaborator)
admin.site.register(GitAccessToken)
