"""Organization pages someone can't open explain why, instead of showing a bare 404. Scheduled organization jobs
(class reminders, scheduled posts, lectures and tasks) also run from here as people use the site, so they still
happen when no cron job runs run_organization_jobs."""
import logging
from django.conf import settings
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import render

logger = logging.getLogger(__name__)
JOBS_LOCK_KEY = "organization-jobs-ran"


class OrganizationUnavailable(Http404):
    """An organization page the visitor can't open. It reads the same whether or not the organization exists."""
    def __init__(self, staff_only=False):
        super().__init__("Organization page unavailable")
        self.staff_only = staff_only


class OrganizationAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # At most once a minute across the site (the cache entry is the lock). Each job claims what it sends, so a
        # cron run at the same moment can't send anything twice.
        every = settings.ORGANIZATION_JOBS_EVERY_SECONDS
        if every and cache.add(JOBS_LOCK_KEY, True, every):
            from . import services
            try:
                services.run_due_jobs()
            except Exception:
                logger.exception("Scheduled organization jobs failed")
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, OrganizationUnavailable):
            return render(request, "organizations/unavailable.html", {"section": "organization", "staff_only": exception.staff_only}, status=404)
        return None
