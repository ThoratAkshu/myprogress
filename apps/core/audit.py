"""The change log: who changed access, visibility or security settings, and when, as on GitHub's audit and security
logs. Events are sentences after the actor's name ("made acme-labs/api public"), kept even if the repository goes."""
from apps.common.ratelimit import client_ip
from .models import AuditEvent


def record(request, action, text, *, actor=None, user=None, company=None, repository=None):
    """Log one change. The actor is whoever's signed in unless given; a company repository's events also go in its
    company's log."""
    if actor is None and request is not None and request.user.is_authenticated:
        actor = request.user
    company_id = company.pk if company else (repository.company_id if repository is not None else None)
    return AuditEvent.objects.create(actor=actor, user=user, company_id=company_id, repository=repository, action=action, text=text[:300],
                                     ip=client_ip(request)[:64] if request is not None else "")


def company_log(company):
    return company.audit_events.select_related("actor__profile")


def repository_log(repository, limit=30):
    return repository.audit_events.select_related("actor__profile")[:limit]


def security_log(user, limit=20):
    return user.security_events.all()[:limit]
