from django.urls import path
from .views import comment_delete_view, comment_view, like_view, post_create_view, post_delete_view, post_detail_view, post_edit_view
app_name = "learning"
urlpatterns = [
    path("new/", post_create_view, name="create"),
    path("<int:post_id>/", post_detail_view, name="detail"),
    path("<int:post_id>/edit/", post_edit_view, name="edit"),
    path("<int:post_id>/delete/", post_delete_view, name="delete"),
    path("<int:post_id>/like/", like_view, name="like"),
    path("<int:post_id>/comments/", comment_view, name="comment"),
    path("comments/<int:comment_id>/delete/", comment_delete_view, name="comment_delete"),
]
