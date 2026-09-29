import base64
import os
import re
import subprocess
import tempfile
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from .models import GitAccessToken, Repository
SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,98}$")
def repository_path(repository):
    root = Path(settings.GIT_REPOSITORY_ROOT).resolve()
    path = (root / f"{repository.storage_key}.git").resolve()
    if root not in path.parents:
        raise ValueError("Invalid repository storage path")
    return path
def run_git(*args, cwd=None, timeout=30):
    return subprocess.run([settings.GIT_EXECUTABLE, *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=timeout)
def initialize_repository(repository):
    path = repository_path(repository)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Repository storage already exists")
    run_git("init", "--bare", f"--initial-branch={repository.default_branch}", str(path))
    run_git("config", "http.receivepack", "true", cwd=path)
    run_git("config", "receive.denyNonFastForwards", "true", cwd=path)
    return path
def list_branches(repository):
    path = repository_path(repository)
    result = run_git("for-each-ref", "--format=%(refname:short)|%(objectname:short)|%(committerdate:iso8601)|%(subject)", "refs/heads", cwd=path)
    branches = []
    for line in result.stdout.splitlines():
        name, commit, updated, subject = (line.split("|", 3) + ["", "", "", ""])[:4]
        branches.append({"name": name, "commit": commit, "updated": updated, "subject": subject})
    return branches

def list_files(repository, ref=None):
    ref = ref or repository.default_branch
    result = run_git("ls-tree", "-l", ref, cwd=repository_path(repository))
    files = []
    for line in result.stdout.splitlines():
        metadata, name = line.split("\t", 1)
        mode, kind, object_id, size = metadata.split()
        files.append({"name": name, "kind": kind, "size": None if size == "-" else int(size), "object_id": object_id, "mode": mode})
    return files

def list_commits(repository, ref=None, limit=50):
    ref = ref or repository.default_branch
    result = run_git("log", f"-{limit}", "--date=iso-strict", "--format=%H%x1f%h%x1f%an%x1f%ae%x1f%ad%x1f%s", ref, cwd=repository_path(repository))
    return [dict(zip(("id", "short_id", "author", "email", "date", "subject"), line.split("\x1f", 5))) for line in result.stdout.splitlines()]

def list_contributors(repository, ref=None):
    commits = list_commits(repository, ref, limit=500)
    contributors = {}
    for commit in commits:
        key = commit["email"].lower()
        contributor = contributors.setdefault(key, {"name": commit["author"], "email": commit["email"], "commits": 0})
        contributor["commits"] += 1
    return sorted(contributors.values(), key=lambda contributor: (-contributor["commits"], contributor["name"].lower()))

def create_branch(repository, name, source=None):
    if not SAFE_REF.fullmatch(name) or ".." in name or name.endswith((".", "/")):
        raise ValueError("Use letters, numbers, dots, dashes, underscores, or slashes for the branch name.")
    if name in {branch["name"] for branch in list_branches(repository)}:
        raise ValueError("That branch already exists.")
    run_git("branch", name, source or repository.default_branch, cwd=repository_path(repository))

def commit_file(repository, relative_path, content, user, message=""):
    relative_path = relative_path.strip().replace("\\", "/").lstrip("/")
    parts = Path(relative_path).parts
    if not relative_path or ".." in parts or len(relative_path) > 240:
        raise ValueError("Enter a safe file path inside the repository.")
    if len(content.encode("utf-8")) > 1_000_000:
        raise ValueError("Web-created files must be smaller than 1 MB.")
    with tempfile.TemporaryDirectory() as checkout_root:
        checkout = Path(checkout_root) / "checkout"
        run_git("clone", str(repository_path(repository)), str(checkout))
        branches = list_branches(repository)
        if not branches:
            run_git("checkout", "-b", repository.default_branch, cwd=checkout)
        target = (checkout / relative_path).resolve()
        if checkout.resolve() not in target.parents:
            raise ValueError("Invalid file path.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        run_git("config", "user.name", user.get_full_name() or user.username, cwd=checkout)
        run_git("config", "user.email", user.email or user.username, cwd=checkout)
        run_git("add", "--", relative_path, cwd=checkout)
        run_git("commit", "-m", (message.strip() or f"Add {relative_path}")[:200], cwd=checkout)
        run_git("push", "origin", repository.default_branch, cwd=checkout)
def user_can_access(user, repository, write=False):
    if not user or not user.is_authenticated:
        return not write and repository.visibility == "public"
    if repository.owner_id == user.id:
        return True
    roles = ["write", "maintain"] if write else ["read", "write", "maintain"]
    return repository.collaborators.filter(user=user, role__in=roles).exists()
def authenticate_git_request(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return None
    try:
        username, raw = base64.b64decode(header[6:]).decode("utf-8").split(":", 1)
        if not raw.startswith("mp_"):
            return None
        prefix = raw.split("_", 2)[1]
        token = GitAccessToken.objects.select_related("user").filter(prefix=prefix, revoked_at__isnull=True).first()
        if not token or not token.is_valid or not token.matches(raw) or username.lower() != token.user.username.lower():
            return None
        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])
        return token
    except (ValueError, UnicodeDecodeError):
        return None
def smart_http(repository, request, service_path):
    path = repository_path(repository)
    env = os.environ.copy()
    env.update({"GIT_PROJECT_ROOT": str(path.parent), "GIT_HTTP_EXPORT_ALL": "1", "PATH_INFO": f"/{path.name}/{service_path}", "REQUEST_METHOD": request.method, "QUERY_STRING": request.META.get("QUERY_STRING", ""), "CONTENT_TYPE": request.content_type or "", "CONTENT_LENGTH": str(len(request.body)), "REMOTE_USER": str(request.user.pk) if request.user.is_authenticated else ""})
    process = subprocess.run([settings.GIT_EXECUTABLE, "http-backend"], input=request.body, capture_output=True, env=env, timeout=120)
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors="replace"))
    separator = b"\r\n\r\n" if b"\r\n\r\n" in process.stdout else b"\n\n"
    header_blob, body = process.stdout.split(separator, 1)
    headers = {}
    status = 200
    for line in header_blob.decode("latin1").splitlines():
        key, value = line.split(":", 1)
        if key.lower() == "status":
            status = int(value.strip().split()[0])
        else:
            headers[key.strip()] = value.strip()
    return status, headers, body
