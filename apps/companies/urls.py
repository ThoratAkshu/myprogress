from django.urls import path
from . import views
app_name = "companies"
urlpatterns = [
    path("", views.company_list_view, name="list"),
    path("invitations/<str:token>/", views.invitation_view, name="invitation"),
    path("<slug:slug>/", views.company_detail_view, name="detail"),
    path("<slug:slug>/repositories/new/", views.repository_create_view, name="repository_create"),
    path("<slug:slug>/people/", views.people_view, name="people"),
    path("<slug:slug>/teams/new/", views.team_create_view, name="team_create"),
    path("<slug:slug>/teams/<slug:team_slug>/", views.team_view, name="team"),
    path("<slug:slug>/settings/", views.settings_view, name="settings"),
]
