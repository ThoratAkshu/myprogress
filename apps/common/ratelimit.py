"""Small fixed-window rate limits backed by Django's cache.

Counters live in the default cache, so configure Redis (REDIS_URL) when running
more than one process; the local-memory cache only limits within one process.
"""
import time
from functools import wraps
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
def client_ip(request):
    if settings.TRUST_X_FORWARDED_FOR and request.META.get("HTTP_X_FORWARDED_FOR"):
        return request.META["HTTP_X_FORWARDED_FOR"].split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")
def _bucket(key, window):
    return f"ratelimit:{key}:{int(time.time() // window)}"
def hits(key, window):
    return cache.get(_bucket(key, window), 0)
def record_hit(key, window):
    bucket = _bucket(key, window)
    cache.add(bucket, 0, timeout=window + 1)
    try:
        return cache.incr(bucket)
    except ValueError:
        cache.set(bucket, 1, timeout=window + 1)
        return 1
def is_limited(key, limit, window):
    return hits(key, window) >= limit
def too_many_requests(window, message="Too many requests. Please wait a moment and try again."):
    response = HttpResponse(message, status=429, content_type="text/plain; charset=utf-8")
    response["Retry-After"] = str(window)
    return response
def rate_limit(scope, limit, window, per="user", methods=("POST",)):
    """Allow `limit` requests per `window` seconds for each user (or IP), counting only `methods`."""
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method in methods:
                identity = f"user:{request.user.pk}" if per == "user" and request.user.is_authenticated else f"ip:{client_ip(request)}"
                if record_hit(f"{scope}:{identity}", window) > limit:
                    return too_many_requests(window)
            return view(request, *args, **kwargs)
        return wrapped
    return decorator
