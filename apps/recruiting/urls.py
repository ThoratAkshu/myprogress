from django.urls import path
from .views import contact_view, outreach_view, respond_contact_view, shortlist_add_view, shortlist_entry_view, shortlists_view, talent_search_view
app_name = "recruiting"
urlpatterns = [
    path("", talent_search_view, name="search"),
    path("shortlists/", shortlists_view, name="shortlists"),
    path("shortlist-entries/<int:entry_id>/", shortlist_entry_view, name="shortlist_entry"),
    path("candidates/<slug:handle>/shortlist/", shortlist_add_view, name="shortlist_add"),
    path("candidates/<slug:handle>/contact/", contact_view, name="contact"),
    path("outreach/", outreach_view, name="outreach"),
    path("requests/<int:request_id>/respond/", respond_contact_view, name="respond_contact"),
]
