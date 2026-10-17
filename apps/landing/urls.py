from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from apps.common.ratelimit import rate_limit
from .views import LandingPageView, account_identity_view, channel_settings_view, complete_loop_view, create_project_view, create_repository_view, dashboard_view, follow_view, git_http_view, issue_git_token_view, learning_view, login_view, logout_view, public_profile_view, register_view, repository_view, update_profile_view, update_project_view, workspace_section_view, verify_email_view, resend_verification_view, dismiss_verification_banner_view, health_view, search_view, project_detail_view, search_suggest_view
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
    path("projects/<int:project_id>/", project_detail_view, name="project"),
    path("projects/<int:project_id>/update/", update_project_view, name="update_project"),
    path("learning/<int:post_id>/view/", learning_view, name="learning_view"),
    path("daily-loop/<str:step>/complete/", complete_loop_view, name="complete_loop"),
    path("projects/<int:project_id>/repository/create/", create_repository_view, name="create_repository"),
    path("repositories/<int:repository_id>/", repository_view, name="repository"),
    path("settings/git-tokens/create/", issue_git_token_view, name="issue_git_token"),
    path("settings/profile/", update_profile_view, name="update_profile"),
    path("settings/channel/", channel_settings_view, name="channel_settings"),
    path("u/<slug:handle>/", public_profile_view, name="public_profile"),
    path("u/<slug:handle>/follow/", follow_view, name="follow"),
    path("account/verify/<str:token>/", verify_email_view, name="verify_email"),
    path("account/verify-resend/", resend_verification_view, name="resend_verification"),
    path("account/verify-banner/dismiss/", dismiss_verification_banner_view, name="dismiss_verify_banner"),
    path("account/password-reset/", rate_limit("password-reset", 5, 3600, per="ip")(auth_views.PasswordResetView.as_view(template_name="landing/password_reset_form.html", email_template_name="landing/emails/password_reset.txt", subject_template_name="landing/emails/password_reset_subject.txt", success_url=reverse_lazy("landing:password_reset_done"))), name="password_reset"),
    path("account/password-reset/sent/", auth_views.PasswordResetDoneView.as_view(template_name="landing/password_reset_done.html"), name="password_reset_done"),
    path("account/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="landing/password_reset_confirm.html", success_url=reverse_lazy("landing:password_reset_complete")), name="password_reset_confirm"),
    path("account/reset/done/", auth_views.PasswordResetCompleteView.as_view(template_name="landing/password_reset_complete.html"), name="password_reset_complete"),
    path("healthz", health_view, name="health"),
    path("search/", search_view, name="search"),
    path("search/suggest/", search_suggest_view, name="search_suggest"),
    path("git/<int:owner_id>/<slug:slug>.git", git_http_view, {"service_path": ""}, name="git_root"),
    path("git/<int:owner_id>/<slug:slug>.git/<path:service_path>", git_http_view, name="git_http"),
]
