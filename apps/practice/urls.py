from django.urls import path
from . import views

app_name = "practice"
urlpatterns = [
    path("", views.home_view, name="home"),
    path("setup/", views.setup_view, name="setup"),
    path("choose/", views.choose_view, name="choose"),
    path("level/", views.level_view, name="level"),
    path("warm-up/", views.warmup_view, name="warmup"),
    path("quiz/", views.quiz_view, name="quiz"),
    path("api/next/", views.next_api, name="next"),
    path("api/answer/", views.answer_api, name="answer"),
    path("problems/", views.problems_view, name="problems"),
    path("problems/<slug:slug>/", views.problem_view, name="problem"),
    path("problems/<slug:slug>/tests/", views.problem_tests_api, name="problem_tests"),
    path("problems/<slug:slug>/submit/", views.submit_api, name="submit"),
    path("code/", views.lab_view, name="lab"),
    path("code/<slug:key>/", views.old_challenge_view, name="challenge"),
    path("watch/<slug:key>/", views.walkthrough_view, name="walkthrough"),
    path("mode/", views.mode_view, name="mode"),
]
