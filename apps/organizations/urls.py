from django.urls import path
from . import views
app_name = "organizations"
urlpatterns = [
    path("", views.home_view, name="home"),
    path("new/", views.create_view, name="create"),
    path("join/<str:code>/", views.join_view, name="join"),
    path("invite/<str:token>/", views.accept_invite_view, name="accept_invite"),
    path("<slug:slug>/", views.overview_view, name="overview"),
    path("<slug:slug>/students/", views.members_view, name="members"),
    path("<slug:slug>/students/<int:user_id>/", views.member_detail_view, name="member"),
    path("<slug:slug>/students/<int:user_id>/action/", views.member_action_view, name="member_action"),
    path("<slug:slug>/invite/", views.invite_view, name="invite"),
    path("<slug:slug>/leave/", views.leave_view, name="leave"),
    path("<slug:slug>/channel/", views.channel_view, name="channel"),
    path("<slug:slug>/channel/<int:post_id>/delete/", views.channel_delete_view, name="channel_delete"),
    path("<slug:slug>/channel/<int:post_id>/file/", views.channel_file_view, name="channel_file"),
    path("<slug:slug>/tasks/", views.tasks_view, name="tasks"),
    path("<slug:slug>/tasks/<int:task_id>/", views.task_detail_view, name="task"),
    path("<slug:slug>/tasks/<int:task_id>/delete/", views.task_delete_view, name="task_delete"),
    path("<slug:slug>/tasks/<int:task_id>/file/", views.task_file_view, name="task_file"),
    path("<slug:slug>/submissions/<int:submission_id>/review/", views.review_view, name="review"),
    path("<slug:slug>/submissions/<int:submission_id>/file/", views.submission_file_view, name="submission_file"),
    path("<slug:slug>/settings/", views.settings_view, name="settings"),
]
