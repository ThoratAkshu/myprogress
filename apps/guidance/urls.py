from django.urls import path
from . import views
app_name = "guidance"
urlpatterns = [
    path("report/", views.report_view, name="report"),
    path("<slug:step>/", views.go_view, name="go"),
    path("<slug:step>/dismiss/", views.dismiss_view, name="dismiss"),
]
