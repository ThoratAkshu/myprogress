from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
@login_required(login_url="landing:home")
@never_cache
def notification_list_view(request):
    page = Paginator(request.user.notifications.select_related("actor"), 30).get_page(request.GET.get("page"))
    unread_ids = [notification.pk for notification in page if notification.read_at is None]
    response = render(request, "notifications/list.html", {"section": "notifications", "page": page, "unread_ids": set(unread_ids)})
    request.user.notifications.filter(pk__in=unread_ids).update(read_at=timezone.now())
    return response
