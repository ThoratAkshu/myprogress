from django.urls import path
from .views import invitation_detail_view, invitation_list_view
app_name = "repository_invitations"
urlpatterns = [
    path("", invitation_list_view, name="list"),
    path("<str:token>/", invitation_detail_view, name="detail"),
]
