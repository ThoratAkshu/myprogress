"""Which kind of account may open each page: one table, checked on the server for every request.

Hiding a link only changes what people see; typing the address, or editing the page in the browser's
inspector, still reaches the server. So every named URL is listed here, and the middleware refuses a
request whose account type isn't allowed before the view runs. A URL missing from the table is refused
for everyone (fail closed), and a test checks that every URL is listed.

The table answers "may this kind of account open this kind of page". Each view still checks the object:
that the post is yours, that you're a member of that organization, that the repository lets you read it.
"""
DEVELOPER, RECRUITER, ORGANIZATION = "developer", "recruiter", "organization"
ALL_ROLES = frozenset({DEVELOPER, RECRUITER, ORGANIZATION})
# Anyone, signed in or not. The view decides what each visitor gets (public pages, token links, Git, its own sign-in).
PUBLIC = "public"

CREATORS = frozenset({DEVELOPER, ORGANIZATION})  # write posts and record lectures in the studio
HIRING = frozenset({RECRUITER, ORGANIZATION})  # talent search, shortlists, outreach
DEVELOPERS = frozenset({DEVELOPER})

# Workspace sections: the leaderboard is for everyone; the rest is a developer's own workspace.
WORKSPACE_SECTIONS = {"rankings": ALL_ROLES}


def _workspace_section(kwargs):
    return WORKSPACE_SECTIONS.get(kwargs.get("section"), DEVELOPERS)


POLICY = {
    # Public pages, sign-in and account recovery.
    "landing:home": PUBLIC, "landing:register": PUBLIC, "landing:register_details": PUBLIC, "landing:login": PUBLIC, "landing:logout": PUBLIC,
    "landing:two_step": PUBLIC,  # the second step of signing in, before there's an account to check
    "landing:verify_email": PUBLIC, "landing:health": PUBLIC, "landing:search": PUBLIC, "landing:search_suggest": PUBLIC,
    "landing:public_profile": PUBLIC, "landing:project": PUBLIC,
    "landing:password_reset": PUBLIC, "landing:password_reset_done": PUBLIC, "landing:password_reset_confirm": PUBLIC, "landing:password_reset_complete": PUBLIC,
    # Git over HTTP signs in with an account email and write key; the repository decides who may read or push.
    "landing:git_root": PUBLIC, "landing:git_http": PUBLIC,
    # Repositories: public ones are readable by anyone; private ones and every change are checked per repository.
    "landing:repository": PUBLIC,
    "code:blob": PUBLIC, "code:raw": PUBLIC, "code:commit": PUBLIC, "code:issues": PUBLIC, "code:issue": PUBLIC, "code:pulls": PUBLIC, "code:pull": PUBLIC,
    "code:issue_create": PUBLIC, "code:issue_comment": PUBLIC, "code:issue_state": PUBLIC, "code:pull_create": PUBLIC, "code:pull_merge": PUBLIC, "code:collaborators": PUBLIC, "code:leave": PUBLIC,
    "repository_invitations:list": PUBLIC, "repository_invitations:detail": PUBLIC,  # the views check who the invitation is for
    # Companies own repositories together, like organizations on GitHub. Students and professionals create and run
    # them; anyone can see a company's public repositories, and the views check membership for the rest.
    "companies:list": DEVELOPERS, "companies:repository_create": DEVELOPERS, "companies:people": DEVELOPERS, "companies:team_create": DEVELOPERS,
    "companies:team": DEVELOPERS, "companies:settings": DEVELOPERS, "companies:detail": PUBLIC, "companies:invitation": PUBLIC, "code:transfer": DEVELOPERS,
    # Developer mode: coding practice for students and professionals, at sign-in, in the Learn dock and the Practice tab.
    "practice:home": DEVELOPERS, "practice:setup": DEVELOPERS, "practice:choose": DEVELOPERS, "practice:level": DEVELOPERS, "practice:warmup": DEVELOPERS, "practice:quiz": DEVELOPERS,
    "practice:next": DEVELOPERS, "practice:answer": DEVELOPERS,
    "practice:problems": DEVELOPERS, "practice:problem": DEVELOPERS, "practice:problem_tests": DEVELOPERS, "practice:submit": DEVELOPERS,
    "practice:lab": DEVELOPERS, "practice:challenge": DEVELOPERS, "practice:walkthrough": DEVELOPERS, "practice:mode": DEVELOPERS,
    # Every signed-in account.
    "landing:dashboard": ALL_ROLES,  # sends each account type to its own home
    "landing:account_identity": ALL_ROLES, "landing:update_profile": ALL_ROLES, "landing:channel_settings": ALL_ROLES, "landing:follow": ALL_ROLES,
    "landing:security": ALL_ROLES, "landing:resend_verification": ALL_ROLES, "landing:dismiss_verify_banner": ALL_ROLES, "landing:learning_view": ALL_ROLES,
    "notifications:list": ALL_ROLES,
    "landing:workspace_section": _workspace_section,
    # A developer's own workspace: projects, repositories, Git keys, the daily loop, earnings, recruiter requests.
    "landing:create_project": DEVELOPERS, "landing:update_project": DEVELOPERS, "landing:create_repository": DEVELOPERS,
    "landing:issue_git_token": DEVELOPERS, "landing:complete_loop": DEVELOPERS,
    "earnings:home": DEVELOPERS, "earnings:payment_details": DEVELOPERS,
    "recruiting:respond_contact": DEVELOPERS,
    # Hiring: recruiters, and organizations hiring their own students.
    "recruiting:search": HIRING, "recruiting:shortlists": HIRING, "recruiting:shortlist_entry": HIRING, "recruiting:shortlist_add": HIRING,
    "recruiting:contact": HIRING, "recruiting:outreach": HIRING,
    # Learning posts: anyone can read what they're allowed to see; developers and organizations create.
    "learning:detail": PUBLIC, "learning:captions": PUBLIC, "learning:media": PUBLIC,
    "learning:like": ALL_ROLES, "learning:comment": ALL_ROLES, "learning:comment_delete": ALL_ROLES,
    "learning:create": CREATORS, "learning:edit": CREATORS, "learning:delete": CREATORS,
    "learning:studio_branches": CREATORS, "learning:studio_draft": CREATORS, "learning:studio_preview": CREATORS, "learning:studio_image": CREATORS,
    "learning:studio_files": CREATORS, "learning:studio_file": CREATORS, "learning:studio_assist": CREATORS,
    # Organizations. Only organization accounts start one; inside, membership and the member's role decide.
    "organizations:create": frozenset({ORGANIZATION}),
    "organizations:calendar_feed": PUBLIC,  # calendar apps fetch it without signing in; the private address is the key
    "organizations:join": PUBLIC, "organizations:accept_invite": PUBLIC,  # explain the invitation first; joining needs a sign-in
    "organizations:certificate": PUBLIC,  # public certificate verification
    "organizations:parent_report": PUBLIC, "organizations:parent_emails": PUBLIC,  # the private link is the key
    **{f"organizations:{name}": ALL_ROLES for name in [
        "home", "overview", "members", "member", "member_action", "parent_access", "invite", "import", "import_template", "leave",
        "channel", "channel_delete", "channel_publish", "release_now", "channel_file", "playlist", "playlist_create", "playlist_save", "tasks", "task", "task_delete", "task_file",
        "review", "submission_file", "settings", "leaderboard", "certificates", "classes", "live_class", "join_class", "class_room", "cancel_class",
        "class_calendar", "calendar_reset", "live_now", "teaching_board", "recording_start", "recording_piece", "recording_finish", "recording_edit", "recording_file",
        "watch", "class_stream", "class_stream_bytes", "class_chat",
    ]},
    # The finance console has its own sign-in for finance staff (see earnings.views.finance_required).
    **{f"finance:{name}": PUBLIC for name in [
        "overview", "login", "logout", "payouts", "close_month", "sync_payments", "prepare_run", "send_run", "payouts_csv", "payout_paid",
        "payout_reject", "razorpayx_webhook", "revenue", "revenue_csv", "revenue_delete", "treasury", "company_account", "settings", "creators", "creator", "audit",
    ]},
}
# Django's admin checks staff status itself; static and media files have no URL name.
EXEMPT_NAMESPACES = {"admin"}

ROLE_LABELS = {DEVELOPER: "developer", RECRUITER: "recruiter", ORGANIZATION: "organization"}


def user_role(user):
    """The account type. Accounts without a profile yet are developers, as when a profile is first created."""
    profile = getattr(user, "profile", None) if user.is_authenticated else None
    return getattr(profile, "role", None) or DEVELOPER


def allowed_roles(view_name, kwargs):
    """PUBLIC, a set of account types, or None when the URL isn't in the table (refused)."""
    rule = POLICY.get(view_name)
    return rule(kwargs) if callable(rule) else rule
