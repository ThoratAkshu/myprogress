"""The people side of Learn: find anyone on MyProgress, see who you follow and who follows you."""
from collections import Counter
from django.db.models import Count, Q
from apps.accounts.models import Profile
from .models import Repository
RECRUITER_ROLES = {"recruiter", "organization"}
NETWORK_VIEWS = {"discover": "Discover", "following": "Following", "followers": "Followers", "requests": "Recruiter requests"}
NETWORK_ROLES = {"": "Everyone", "developer": "Students and professionals", "recruiter": "Recruiters"}
NETWORK_SORTS = {"relevant": "Most relevant", "score": "Highest progress score", "followers": "Most followers", "newest": "Newest members"}
def _people(viewer):
    following_ids = list(viewer.following_relationships.values_list("following_id", flat=True))
    return Profile.objects.exclude(user=viewer).filter(user__is_active=True).select_related("user").prefetch_related("user__repositories").annotate(
        follower_total=Count("user__follower_relationships", distinct=True),
        mutual=Count("user__follower_relationships", filter=Q(user__follower_relationships__follower_id__in=following_ids), distinct=True),
    )
def find_people(viewer, query="", language="", location="", role="", sort="relevant"):
    """Everyone matching the search, most relevant first: people your network follows, then progress score."""
    people = _people(viewer)
    for term in query.split()[:5]:
        people = people.filter(Q(user__first_name__icontains=term) | Q(user__last_name__icontains=term) | Q(handle__icontains=term) | Q(headline__icontains=term) | Q(skills__icontains=term) | Q(location__icontains=term))
    if language:
        people = people.filter(user__in=Repository.objects.filter(languages__has_key=language).values("owner"))
    if location:
        people = people.filter(location__icontains=location)
    if role == "developer":
        people = people.filter(role="developer")
    elif role == "recruiter":
        people = people.filter(role__in=RECRUITER_ROLES)
    order = {"score": ["-score", "handle"], "followers": ["-follower_total", "-score", "handle"], "newest": ["-user__date_joined", "handle"]}.get(sort, ["-mutual", "-score", "-follower_total", "handle"])
    return people.order_by(*order)
def suggested_people(viewer, limit=9):
    """People you may know (shared languages and skills first), with the same details as search results."""
    from .feed import people_you_may_know
    ids = [profile.pk for profile in people_you_may_know(viewer, limit=limit)]
    found = {profile.pk: profile for profile in _people(viewer).filter(pk__in=ids)}
    return [found[pk] for pk in ids if pk in found]
def following_people(viewer):
    return _people(viewer).filter(user__in=viewer.following_relationships.values("following")).order_by("user__first_name", "handle")
def follower_people(viewer):
    return _people(viewer).filter(user__in=viewer.follower_relationships.values("follower")).order_by("user__first_name", "handle")
def decorate_people(viewer, profiles):
    """Add each person's top languages, the languages you share, and whether you follow them."""
    following = set(viewer.following_relationships.values_list("following_id", flat=True))
    mine = {language for languages in viewer.repositories.values_list("languages", flat=True) for language in (languages or {})}
    for profile in profiles:
        totals = Counter()
        for repository in profile.user.repositories.all():
            totals.update(repository.languages or {})
        profile.top_languages = [name for name, _ in totals.most_common(3)]
        profile.shared_languages = [name for name in profile.top_languages if name in mine]
        profile.is_followed = profile.user_id in following
    return profiles
