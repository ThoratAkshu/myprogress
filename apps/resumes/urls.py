from django.urls import path
from . import views
app_name = "resumes"
urlpatterns = [
    path("", views.my_resume_view, name="mine"),
    path("<slug:handle>/", views.candidate_resume_view, name="candidate"),
]
