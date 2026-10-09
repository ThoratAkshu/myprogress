from django.urls import path
from .views import notification_list_view
app_name = "notifications"
urlpatterns = [path("", notification_list_view, name="list")]
