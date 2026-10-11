from django.urls import path, reverse_lazy
from django.views.generic import RedirectView
from .views import withdraw_view
app_name = "earnings"
urlpatterns = [
    path("", RedirectView.as_view(url=reverse_lazy("landing:workspace_section", args=["earnings"])), name="home"),
    path("withdraw/", withdraw_view, name="withdraw"),
]
