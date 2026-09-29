from django.urls import path
from .views import LandingPageView, account_identity_view, complete_loop_view, create_project_view, create_repository_view, dashboard_view, git_http_view, issue_git_token_view, learning_view, login_view, logout_view, register_view, repository_view, workspace_section_view
app_name = "landing"
urlpatterns = [
    path("", LandingPageView.as_view(), name="home"),
    path("register/", register_view, name="register"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("account/identity/", account_identity_view, name="account_identity"),
    path("dashboard/<str:section>/", workspace_section_view, name="workspace_section"),
    path("projects/create/", create_project_view, name="create_project"),
    path("learning/<int:post_id>/view/", learning_view, name="learning_view"),
    path("daily-loop/<str:step>/complete/", complete_loop_view, name="complete_loop"),
    path("projects/<int:project_id>/repository/create/", create_repository_view, name="create_repository"),
    path("repositories/<int:repository_id>/", repository_view, name="repository"),
    path("settings/git-tokens/create/", issue_git_token_view, name="issue_git_token"),
    path("git/<int:owner_id>/<slug:slug>.git", git_http_view, {"service_path": ""}, name="git_root"),
    path("git/<int:owner_id>/<slug:slug>.git/<path:service_path>", git_http_view, name="git_http"),
]
