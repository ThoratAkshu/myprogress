from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.contrib.staticfiles.views import serve as serve_static
from django.urls import re_path
urlpatterns = [
    path("admin/", admin.site.urls),
    path("recruit/", include("apps.recruiting.urls")),
    path("learn/", include("apps.learning.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("repositories/<int:repository_id>/", include("apps.code.urls")),
    path("", include("apps.landing.urls")),
    re_path(r"^static/(?P<path>.*)$", serve_static),
]
# Development only: production should serve uploads from object storage or the web server.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
