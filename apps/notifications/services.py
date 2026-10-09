from .models import Notification
def notify(recipient, actor, kind, text, url=""):
    if not recipient or recipient == actor:
        return None
    return Notification.objects.create(recipient=recipient, actor=actor, kind=kind, text=text[:255], url=url[:255])
