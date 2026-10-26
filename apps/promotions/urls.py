from django.urls import path
from . import views
app_name = "promotions"
urlpatterns = [
    path("", views.list_view, name="list"),
    path("new/", views.edit_view, name="create"),
    path("review/", views.review_view, name="review"),
    path("<int:promotion_id>/edit/", views.edit_view, name="edit"),
    path("<int:promotion_id>/action/", views.action_view, name="action"),
    path("<int:promotion_id>/review/", views.review_action_view, name="review_action"),
    path("<int:promotion_id>/go/", views.go_view, name="go"),
    path("<int:promotion_id>/hide/", views.hide_view, name="hide"),
]
