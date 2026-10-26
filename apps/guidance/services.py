"""Reads what a member has been doing lately and picks the one next step that moves them forward.

Watching videos, liking, commenting and following are good, but they leave nothing behind. Someone who has only been
doing that, with no project, practice or class work, is shown a concrete next step: a project shaped by what they've
been watching, or a coaching centre if they'd rather learn with a teacher. People who are already building see nothing.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from django.db.models import F
from django.urls import reverse
from django.utils import timezone
from .models import StepDismissal, StepEvent
WINDOW_DAYS = 14         # how far back "lately" goes
WATCHING_MIN = 5         # watches, likes, comments and follows in the window that make someone "mostly watching"
NEW_MEMBER_DAYS = 7
LATER_DAYS, NOT_FOR_ME_DAYS = 3, 60
# Segments, from most to least engaged.
BUILDING, STALLED, WATCHING, NEW, QUIET = "building", "stalled", "watching", "new", "quiet"
SEGMENT_LABELS = {BUILDING: "Building", STALLED: "Project on hold", WATCHING: "Mostly watching", NEW: "New member", QUIET: "Quiet"}
@dataclass
class Summary:
    """A member's last WINDOW_DAYS: what they watched and what they made, and the segment that follows from it."""
    watched: int = 0
    liked: int = 0
    commented: int = 0
    followed: int = 0
    built: int = 0
    practised: int = 0
    class_work: int = 0
    projects: list = field(default_factory=list)
    pushed_code: bool = False
    in_class: bool = False
    class_pending: bool = False
    interests: list = field(default_factory=list)
    joined_recently: bool = False
    @property
    def consumed(self):
        return self.watched + self.liked + self.commented + self.followed
    @property
    def progressed(self):
        return self.built + self.practised + self.class_work
    @property
    def segment(self):
        if self.progressed:
            return BUILDING
        if self.projects:
            return STALLED
        if self.consumed >= WATCHING_MIN:
            return WATCHING
        return NEW if self.joined_recently else QUIET
    @property
    def open_project(self):
        return next((project for project in self.projects if project.status != "complete"), None)
def activity_summary(user, now=None):
    from apps.accounts.models import Follow
    from apps.core.models import ActivityEvent, LearningPost, PostComment, PostLike, ProjectMilestone
    from apps.core.services import CODE_ACTIONS, CONTRIBUTION_ACTIONS
    from apps.organizations.models import Attendance, Membership, Submission as TaskSubmission
    from apps.practice.models import Attempt, Submission as ProblemSubmission
    now = now or timezone.now()
    since = now - timedelta(days=WINDOW_DAYS)
    summary = Summary(
        watched=ActivityEvent.objects.filter(user=user, action="viewed_learning", created_at__gte=since).count(),
        liked=PostLike.objects.filter(user=user, created_at__gte=since).count(),
        commented=PostComment.objects.filter(author=user, created_at__gte=since).count(),
        followed=Follow.objects.filter(follower=user, created_at__gte=since).count(),
        built=ActivityEvent.objects.filter(user=user, action__in=CONTRIBUTION_ACTIONS, created_at__gte=since).count()
        + ProjectMilestone.objects.filter(project__owner=user, completed_at__gte=since).count(),
        # Sign-in questions are asked of everyone, so only questions they chose to answer count.
        practised=Attempt.objects.filter(user=user, created_at__gte=since).exclude(context="signin").count()
        + ProblemSubmission.objects.filter(user=user, created_at__gte=since).count(),
        class_work=TaskSubmission.objects.filter(student=user, submitted_at__gte=since).count()
        + Attendance.objects.filter(student=user, joined_at__gte=since).count(),
        projects=list(user.projects.order_by("-updated_at")[:20]),
        pushed_code=ActivityEvent.objects.filter(user=user, action__in=CODE_ACTIONS).exists(),
        in_class=Membership.objects.filter(user=user, status="active", role="student").exists(),
        class_pending=Membership.objects.filter(user=user, status="pending").exists(),
        joined_recently=user.date_joined >= now - timedelta(days=NEW_MEMBER_DAYS),
    )
    # What they've been watching: the skills and languages of the projects behind those videos and posts.
    topics = Counter()
    watched_posts = LearningPost.objects.filter(unique_views__viewer=user, unique_views__created_at__gte=since).select_related("project__repository").distinct()[:50]
    for post in watched_posts:
        project = post.project
        if project:
            topics.update({skill.lower(): skill for skill in project.skill_list}.values())
            topics.update((getattr(project, "repository", None) and project.repository.languages or {}).keys())
    summary.interests = [name for name, _ in topics.most_common(2)]
    return summary
def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"
def _about(interests):
    return f" about {' and '.join(interests)}" if interests else ""
def _steps(user, summary):
    """Every step that fits this member right now, keyed by name: title, reason, icon, main and other action."""
    project_url = reverse("landing:workspace_section", args=["projects"]) + "#new-project"
    centres_url = reverse("organizations:find")
    practice = {"label": "Solve a practice problem", "url": reverse("practice:problems")}
    centre = None if summary.in_class or summary.class_pending else {"label": "Prefer a teacher? Find a coaching centre", "url": centres_url}
    steps = {}
    if not summary.projects:
        if summary.watched:
            reason = (f"You watched {_plural(summary.watched, 'video')}{_about(summary.interests)} in the last two weeks but haven't "
                      "built anything yet. A small project you finish shows more than anything you watch.")
        else:
            reason = "Projects are how people here show what they can do. Start a small one; add code and milestones as you go."
        steps["start_project"] = {
            "title": "Turn what you're watching into a project" if summary.watched else "Start your first project", "reason": reason,
            "icon": "box", "primary": {"label": "Start a project", "url": project_url}, "secondary": centre or practice, "not_for_me": "I don't want to do projects",
            "highlights": ["Pick a small idea", "Push your code", "Share what you built"], "tags": summary.interests,
        }
    project = summary.open_project
    if project and not summary.pushed_code:
        steps["add_code"] = {
            "title": f"Add code to {project.title}", "icon": "code", "highlights": ["Create the repository", "Push your first commit", "It shows on your profile"],
            "reason": "A project counts once it has code. Create its repository and push your first commit; it takes a few minutes.",
            "primary": {"label": "Open the project", "url": reverse("landing:project", args=[project.pk])}, "secondary": centre or practice, "not_for_me": "Not for me",
        }
    if project:
        milestone = project.milestones.filter(is_complete=False).first()
        steps["resume_project"] = {
            "title": f"Pick up {project.title}", "icon": "git-commit",
            "highlights": [f"Next: {milestone.title}" if milestone else "Add a milestone", "Push a commit", "Keep the project moving"],
            "reason": "Nothing has moved on it in the last two weeks." + (f" Next milestone: {milestone.title}." if milestone else " Add a milestone so you know what to do next."),
            "primary": {"label": "Continue the project", "url": reverse("landing:project", args=[project.pk])}, "secondary": centre or practice, "not_for_me": "Not for me",
        }
    if centre:
        steps["join_centre"] = {
            "title": "Learn with a coaching centre", "icon": "users", "highlights": ["Live classes", "Tasks a teacher reviews", "Progress on your profile"],
            "reason": "Coaching centres on MyProgress run live classes, set tasks and review your work, and your progress shows on your profile. "
                      "A good fit if you'd rather learn with guidance than on your own.",
            "primary": {"label": "Find a coaching centre", "url": centres_url},
            "secondary": None if summary.projects else {"label": "Start a project instead", "url": project_url}, "not_for_me": "Not for me",
        }
    steps["practice"] = {
        "title": "Solve one practice problem", "icon": "terminal", "highlights": ["One problem", "About ten minutes", "Examples to test against"],
        "reason": "Ten minutes on a coding problem keeps your skills sharp, and it's a quick win when a project feels too big.",
        "primary": {"label": "Practise now", "url": practice["url"]}, "secondary": None, "not_for_me": "Not for me",
    }
    return steps
ORDER = {
    WATCHING: ["start_project", "join_centre", "practice"],
    NEW: ["start_project", "join_centre", "practice"],
    QUIET: ["start_project", "join_centre", "practice"],
    STALLED: ["add_code", "resume_project", "join_centre", "practice"],
}
def next_steps(user, summary=None, now=None):
    """The steps to suggest, best first, leaving out ones the member put aside. Empty for people already building."""
    summary = summary or activity_summary(user, now)
    order = ORDER.get(summary.segment)
    if not order:
        return []
    now = now or timezone.now()
    hidden = set(StepDismissal.objects.filter(user=user, until__gt=now).values_list("step", flat=True))
    steps = _steps(user, summary)
    chosen = []
    for key in order:
        if key in steps and key not in hidden:
            step = {"key": key, **steps[key]}
            if step["secondary"] and step["secondary"]["url"] == reverse("organizations:find") and "join_centre" in hidden:
                step["secondary"] = None  # they said coaching centres aren't for them
            chosen.append(step)
    return chosen
def next_step(user, summary=None):
    """The one step for the home feed, or None. Only for students and professionals."""
    from apps.accounts.access import user_role
    if user_role(user) != "developer":
        return None
    steps = next_steps(user, summary)
    return steps[0] if steps else None
def record(user, step, action):
    """Count today's shown / opened / put aside for this step."""
    event, created = StepEvent.objects.get_or_create(user=user, step=step, action=action, day=timezone.localdate())
    if not created:
        StepEvent.objects.filter(pk=event.pk).update(count=F("count") + 1)
def record_shown(user, step):
    """Once a day per step: refreshing the home page isn't another showing."""
    StepEvent.objects.get_or_create(user=user, step=step, action="shown", day=timezone.localdate())
def dismiss(user, step, reason):
    days = NOT_FOR_ME_DAYS if reason == "not_for_me" else LATER_DAYS
    StepDismissal.objects.update_or_create(user=user, step=step, defaults={"reason": reason, "until": timezone.now() + timedelta(days=days)})
    record(user, step, "dismissed")
def find_step(user, key):
    return next((step for step in next_steps(user) if step["key"] == key), None)
