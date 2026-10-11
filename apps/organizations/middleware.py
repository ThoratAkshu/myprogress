"""Organization pages someone can't open explain why, instead of showing a bare 404."""
from django.http import Http404
from django.shortcuts import render
class OrganizationUnavailable(Http404):
    """An organization page the visitor can't open. It reads the same whether or not the organization exists."""
    def __init__(self, staff_only=False):
        super().__init__("Organization page unavailable")
        self.staff_only = staff_only
class OrganizationAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        return self.get_response(request)
    def process_exception(self, request, exception):
        if isinstance(exception, OrganizationUnavailable):
            return render(request, "organizations/unavailable.html", {"section": "organization", "staff_only": exception.staff_only}, status=404)
        return None
