from django.contrib import admin
from django.urls import include, path
from django.contrib.staticfiles.views import serve as serve_static
from django.urls import re_path
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.landing.urls")),
    re_path(r"^static/(?P<path>.*)$", serve_static),
]
