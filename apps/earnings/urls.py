from django.urls import path, reverse_lazy
from django.views.generic import RedirectView
from .views import payment_details_view
app_name = "earnings"
urlpatterns = [
    path("", RedirectView.as_view(url=reverse_lazy("landing:workspace_section", args=["earnings"])), name="home"),
    path("payment-details/", payment_details_view, name="payment_details"),
]
