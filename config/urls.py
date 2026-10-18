from django.conf import settings
from django.contrib import admin
from apps.common.views import serve_media
from django.urls import include, path
from django.contrib.staticfiles.views import serve as serve_static
from django.urls import re_path
urlpatterns = [
    path("admin/", admin.site.urls),
    path("recruit/", include("apps.recruiting.urls")),
    path("learn/", include("apps.learning.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("earnings/", include("apps.earnings.urls")),
    path("finance/", include("apps.earnings.finance_urls")),
    path("org/", include("apps.organizations.urls")),
    path("repositories/invitations/", include("apps.code.invitation_urls")),
    path("repositories/<int:repository_id>/", include("apps.code.urls")),
    path("", include("apps.landing.urls")),
    re_path(r"^static/(?P<path>.*)$", serve_static),
]
# Development only: production should serve uploads from object storage or the web server.
if settings.DEBUG:
    urlpatterns += [re_path(rf"^{settings.MEDIA_URL.lstrip('/')}(?P<path>.*)$", serve_media)]
