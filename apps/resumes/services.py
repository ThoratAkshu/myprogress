"""Builds a resume from someone's MyProgress work. The owner sees everything they chose; a recruiter sees only what
is public (public projects, certificates on the profile, public posts), and contact details only on the same terms
as the profile: the email when it's shared or their contact request was accepted, the phone only after acceptance."""
from django.urls import reverse
from apps.core.models import ActivityEvent, LearningPost
from apps.core.services import active_coding_days, language_breakdown
from .models import ResumeSettings
STATUS_LABELS = {"planning": "Planning", "building": "In progress", "complete": "Shipped"}
LINK_LABELS = {"website": "Website", "github": "GitHub", "linkedin": "LinkedIn", "x": "X", "youtube": "YouTube", "instagram": "Instagram", "facebook": "Facebook"}
CODING_WINDOW_DAYS = 90
def settings_for(user):
    return ResumeSettings.objects.filter(user=user).first() or ResumeSettings(user=user)
def recruiter_can_see(owner, recruiter):
    """Whether a recruiter may open this person's resume: a developer who is visible to recruiters and hasn't turned
    resume downloads off."""
    profile = getattr(owner, "profile", None)
    return bool(profile and profile.role == "developer" and profile.recruiter_visible and settings_for(owner).recruiters_can_download and recruiter != owner)
def contact_accepted(owner, viewer):
    from apps.recruiting.models import ContactRequest
    return ContactRequest.objects.filter(recruiter=viewer, developer=owner, status="accepted").exists()
def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"
def _projects(owner, settings, for_owner):
    """The projects to show, in the owner's order when they chose some, otherwise the strongest ones first."""
    projects = owner.projects.select_related("repository").prefetch_related("milestones")
    if not for_owner:
        projects = projects.filter(is_public=True)
    projects = list(projects)
    chosen = [pk for pk in settings.project_ids if isinstance(pk, int)]
    if chosen:
        order = {pk: at for at, pk in enumerate(chosen)}
        projects = sorted((project for project in projects if project.pk in order), key=lambda project: order[project.pk])
    else:
        # Picked for them: public projects only, since a private one's link opens for nobody else.
        strength = {"complete": 0, "building": 1, "planning": 2}
        projects = [project for project in projects if project.is_public]
        projects.sort(key=lambda project: (not project.has_verified_code, strength.get(project.status, 3), -project.updated_at.timestamp()))
        projects = projects[:4]
    return projects[:ResumeSettings.MAX_PROJECTS]
def _commits(repository_ids):
    """Commits pushed to each repository, from the push records MyProgress keeps."""
    counts = {}
    for metadata in ActivityEvent.objects.filter(action="pushed_commits", metadata__repository_id__in=repository_ids).values_list("metadata", flat=True):
        key = metadata.get("repository_id")
        counts[key] = counts.get(key, 0) + int(metadata.get("commits", 0) or 0)
    return counts
def written_summary(profile, facts):
    """A factual summary from what they've done, used when they haven't written their own."""
    parts = []
    if profile.occupation == "student" and profile.institution:
        parts.append(f"Student at {profile.institution}" + (f", graduating in {profile.graduation_year}" if profile.graduation_year else "") + ".")
    elif profile.job_title and profile.company_name:
        parts.append(f"{profile.job_title} at {profile.company_name}.")
    elif profile.headline:
        parts.append(profile.headline.rstrip(".") + ".")
    tools = facts["languages"][:3] or profile.skill_list[:3]
    if tools:
        parts.append(f"Builds with {', '.join(tools[:-1]) + ' and ' + tools[-1] if len(tools) > 1 else tools[0]}.")
    work = []
    if facts["projects"]:
        work.append(_plural(facts["projects"], "project") + (f" ({facts['shipped']} shipped)" if facts["shipped"] else ""))
    if facts["commits"]:
        work.append(_plural(facts["commits"], "commit"))
    if facts["coding_days"]:
        work.append(f"{_plural(facts['coding_days'], 'coding day')} in the last {CODING_WINDOW_DAYS} days")
    if work:
        parts.append("On MyProgress: " + ", ".join(work) + ".")
    return " ".join(parts)
def build_resume(owner, viewer, absolute):
    """Everything the resume shows, as plain data for the template. `absolute` turns a path into a full address."""
    profile = owner.profile
    settings = settings_for(owner)
    for_owner = viewer == owner
    hidden = set(settings.hidden_sections)
    projects = _projects(owner, settings, for_owner)
    repositories = [project.repository for project in projects if getattr(project, "repository", None)]
    commits = _commits([repository.pk for repository in repositories])
    all_repositories = owner.repositories.all() if for_owner else owner.repositories.filter(visibility="public")
    languages = language_breakdown([repository.languages for repository in all_repositories], limit=6)
    entries = []
    for project in projects:
        repository = getattr(project, "repository", None)
        milestones = list(project.milestones.all())
        done = sum(item.is_complete for item in milestones)
        tools = [item["name"] for item in language_breakdown([repository.languages], limit=3)] if repository else []
        commit_count = commits.get(repository.pk, 0) if repository else 0
        meta = [", ".join(tools or project.skill_list[:4]), _plural(commit_count, "commit") if commit_count else "", f"{done} of {len(milestones)} milestones done" if milestones else ""]
        entries.append({
            "title": project.title, "status": STATUS_LABELS.get(project.status, project.get_status_display()), "summary": project.summary,
            "meta": [part for part in meta if part], "commits": commit_count,
            "live_url": project.live_url, "url": absolute(reverse("landing:project", args=[project.pk])) if project.is_public else "", "private": not project.is_public,
        })
    facts = {
        "projects": len(owner.projects.all() if for_owner else owner.projects.filter(is_public=True)),
        "shipped": (owner.projects.all() if for_owner else owner.projects.filter(is_public=True)).filter(status="complete").count(),
        "commits": sum(int(metadata.get("commits", 0) or 0) for metadata in ActivityEvent.objects.filter(user=owner, action="pushed_commits").values_list("metadata", flat=True)),
        "coding_days": active_coding_days(owner, CODING_WINDOW_DAYS),
        "languages": [item["name"] for item in languages if item["name"] != "Other"],
    }
    accepted = not for_owner and contact_accepted(owner, viewer)
    email = owner.email if owner.email and ((for_owner and settings.show_email) or (not for_owner and (profile.show_email or accepted))) else ""
    phone = settings.phone if (for_owner or accepted) else ""
    certificates = [] if "certificates" in hidden else [
        {"title": certificate.title, "organization": certificate.organization.name, "issued": certificate.issued_at, "url": absolute(reverse("organizations:certificate", args=[certificate.code]))}
        for certificate in owner.certificates.filter(revoked_at__isnull=True, show_on_profile=True).select_related("organization").order_by("-issued_at")[:4]]
    posts = LearningPost.objects.filter(author=owner, is_public=True).order_by("-views", "-published_at")
    writing = [] if "writing" in hidden else [{"title": post.title, "kind": "Video" if post.kind == "video" else "Article", "views": post.views, "url": absolute(post.get_absolute_url())} for post in posts[:3]]
    solved = 0 if "practice" in hidden else owner.submissions.filter(status="accepted").values("slug").distinct().count()
    return {
        "name": owner.get_full_name() or profile.handle, "headline": profile.headline, "location": profile.location,
        "email": email, "phone": phone, "portfolio_url": absolute(reverse("landing:public_profile", args=[profile.handle])) if profile.handle else "",
        "links": [{"label": LINK_LABELS.get(kind, kind.title()), "url": url} for kind, url in (profile.links or {}).items() if url][:4],
        "summary": settings.summary.strip() or written_summary(profile, facts), "generated_summary": written_summary(profile, facts),
        "skills": profile.skill_list[:14], "languages": languages,
        "education": {"institution": profile.institution, "year": profile.graduation_year} if profile.institution else None,
        "experience": {"title": profile.job_title, "company": profile.company_name} if profile.job_title or profile.company_name else None,
        "projects": entries, "certificates": certificates, "writing": writing, "post_count": posts.count(), "solved": solved,
        "stats": None if "stats" in hidden else {"score": profile.score, "rank": profile.rank, "coding_days": facts["coding_days"], "commits": facts["commits"], "window": CODING_WINDOW_DAYS},
        "template": settings.template, "for_owner": for_owner,
    }
