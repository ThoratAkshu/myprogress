from django.urls import path
from .views import media_view, captions_view, comment_delete_view, comment_view, like_view, post_create_view, post_delete_view, post_detail_view, post_edit_view, studio_assist_view, studio_branches_view, studio_draft_view, studio_file_view, studio_files_view, studio_image_view, studio_preview_view, watch_view, watched_view
app_name = "learning"
urlpatterns = [
    path("new/", post_create_view, name="create"),
    path("watch/", watch_view, name="watch"),
    path("studio/branches/", studio_branches_view, name="studio_branches"),
    path("studio/draft/", studio_draft_view, name="studio_draft"),
    path("studio/preview/", studio_preview_view, name="studio_preview"),
    path("studio/image/", studio_image_view, name="studio_image"),
    path("studio/files/", studio_files_view, name="studio_files"),
    path("studio/file/", studio_file_view, name="studio_file"),
    path("studio/assist/", studio_assist_view, name="studio_assist"),
    path("<int:post_id>/", post_detail_view, name="detail"),
    path("<int:post_id>/edit/", post_edit_view, name="edit"),
    path("<int:post_id>/captions.vtt", captions_view, name="captions"),
    path("<int:post_id>/media/<str:which>/", media_view, name="media"),
    path("<int:post_id>/delete/", post_delete_view, name="delete"),
    path("<int:post_id>/like/", like_view, name="like"),
    path("<int:post_id>/watched/", watched_view, name="watched"),
    path("<int:post_id>/comments/", comment_view, name="comment"),
    path("comments/<int:comment_id>/delete/", comment_delete_view, name="comment_delete"),
]
