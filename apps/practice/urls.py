from django.urls import path
from . import views

app_name = "practice"
urlpatterns = [
    path("", views.home_view, name="home"),
    path("setup/", views.setup_view, name="setup"),
    path("level/", views.level_view, name="level"),
    path("warm-up/", views.warmup_view, name="warmup"),
    path("quiz/", views.quiz_view, name="quiz"),
    path("api/next/", views.next_api, name="next"),
    path("api/answer/", views.answer_api, name="answer"),
]
