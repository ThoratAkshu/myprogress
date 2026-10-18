import base64
import os
import re
import subprocess
import logging
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from .models import GitAccessToken, Repository
logger = logging.getLogger(__name__)
SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,98}$")
def repository_path(repository):
    root = Path(settings.GIT_REPOSITORY_ROOT).resolve()
    path = (root / f"{repository.storage_key}.git").resolve()
    if root not in path.parents:
        raise ValueError("Invalid repository storage path")
    return path
def run_git(*args, cwd=None, timeout=30):
    return subprocess.run([settings.GIT_EXECUTABLE, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=timeout)
def run_git_bytes(*args, cwd=None, timeout=30):
    return subprocess.run([settings.GIT_EXECUTABLE, *args], cwd=cwd, capture_output=True, check=True, timeout=timeout).stdout
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
ROLE_LEVELS = {"read": 1, "write": 2, "maintain": 3, "admin": 4}
def repository_role(user, repository):
    """"owner", a role from ROLE_LEVELS, or None. A company's repository is the company's: its owners have it all,
    the member who made it is an admin while they're a member, every member gets the company's base permission,
    and teams get what they were given; the highest of these, and of any collaborator role, counts."""
    if not user or not user.is_authenticated:
        return None
    collaborator = repository.collaborators.filter(user=user).values_list("role", flat=True).first()
    if not repository.company_id:
        return "owner" if repository.owner_id == user.id else collaborator
    from apps.companies.models import CompanyMember, TeamRepository
    member = CompanyMember.objects.filter(company_id=repository.company_id, user=user).select_related("company").first()
    if member and member.role == "owner":
        return "owner"
    roles = [collaborator] if collaborator else []
    if member:
        if repository.owner_id == user.id:
            roles.append("admin")
        if member.company.base_role != "none":
            roles.append(member.company.base_role)
        roles += list(TeamRepository.objects.filter(repository=repository, team__memberships__user=user).values_list("role", flat=True))
    return max(roles, key=lambda role: ROLE_LEVELS.get(role, 0)) if roles else None
def _at_least(user, repository, role):
    found = repository_role(user, repository)
    return found == "owner" or (found is not None and ROLE_LEVELS.get(found, 0) >= ROLE_LEVELS[role])
def user_can_access(user, repository, write=False):
    """Read: view and clone. Write: push, branch, and merge pull requests. Anyone may read a public repository."""
    return _at_least(user, repository, "write" if write else "read") or (not write and repository.visibility == "public")
def user_can_maintain(user, repository):
    """The repository's settings, like its default branch, without its visibility or who has access."""
    return _at_least(user, repository, "maintain")
def user_can_administer(user, repository):
    """Everything but deleting the project: visibility, and inviting, changing and removing collaborators."""
    return _at_least(user, repository, "admin")
def user_can_change_visibility(user, repository):
    """Admins make a repository public or private, unless its company keeps that to its owners."""
    role = repository_role(user, repository)
    if role == "owner":
        return True
    return ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS["admin"] and not (repository.company_id and not repository.company.members_change_visibility)
LANGUAGE_FILENAMES = {"Dockerfile": "Dockerfile", "Makefile": "Makefile", "CMakeLists.txt": "CMake"}
LANGUAGE_EXTENSIONS = {
    ".py": "Python", ".ipynb": "Jupyter Notebook", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".sass": "SCSS", ".less": "Less", ".vue": "Vue", ".svelte": "Svelte",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".groovy": "Groovy", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++", ".cs": "C#", ".fs": "F#", ".swift": "Swift", ".m": "Objective-C", ".dart": "Dart",
    ".sql": "SQL", ".sh": "Shell", ".bash": "Shell", ".ps1": "PowerShell", ".r": "R", ".jl": "Julia", ".lua": "Lua", ".pl": "Perl", ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang", ".hs": "Haskell", ".clj": "Clojure", ".sol": "Solidity", ".tf": "HCL", ".zig": "Zig",
}
VENDORED_DIRECTORIES = {"node_modules", "vendor", "dist", "build", "venv", ".venv", "__pycache__", "site-packages", "bower_components", ".next", "target"}
def detect_languages(repository, ref=None):
    ref = ref or repository.default_branch
    result = run_git("ls-tree", "-r", "-l", "-z", "--full-tree", ref, cwd=repository_path(repository))
    totals = {}
    for entry in result.stdout.split("\0"):
        if "\t" not in entry:
            continue
        metadata, name = entry.split("\t", 1)
        _, kind, _, size = metadata.split()
        path = Path(name)
        if kind != "blob" or size == "-" or VENDORED_DIRECTORIES.intersection(path.parts[:-1]) or name.endswith((".min.js", ".min.css")):
            continue
        language = LANGUAGE_FILENAMES.get(path.name) or LANGUAGE_EXTENSIONS.get(path.suffix.lower())
        if language:
            totals[language] = totals.get(language, 0) + int(size)
    return dict(sorted(totals.items(), key=lambda item: -item[1]))
def refresh_repository_languages(repository):
    branches = {branch["name"] for branch in list_branches(repository)}
    repository.languages = detect_languages(repository) if repository.default_branch in branches else {}
    repository.save(update_fields=["languages"])
    return repository.languages
def branch_heads(repository):
    result = run_git("for-each-ref", "--format=%(objectname)", "refs/heads", cwd=repository_path(repository))
    return set(result.stdout.split())
def count_new_commits(repository, previous_heads):
    new_heads = branch_heads(repository) - previous_heads
    if not new_heads:
        return 0
    exclusions = ["--not", *previous_heads] if previous_heads else []
    return int(run_git("rev-list", "--count", *new_heads, *exclusions, cwd=repository_path(repository)).stdout.strip() or 0)
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
CHUNK_SIZE = 64 * 1024
class GitRequestTooLarge(Exception):
    pass
def _read_chunked(stream):
    """Decode a chunked request body for servers (like runserver) that pass it through undecoded."""
    while True:
        size = int(stream.readline(1024).split(b";", 1)[0].strip() or b"0", 16)
        if size == 0:
            while stream.readline(1024) not in (b"\r\n", b"\n", b""):
                pass
            return
        remaining = size
        while remaining:
            chunk = stream.read(min(remaining, CHUNK_SIZE))
            if not chunk:
                raise ValueError("Incomplete chunked request body")
            remaining -= len(chunk)
            yield chunk
        stream.readline(1024)
def _request_body(request):
    """Return (chunks, length) without loading the body into memory.

    Git sends large pushes with chunked transfer encoding and no Content-Length.
    Those are spooled to a temporary file so git http-backend always receives a
    fixed-length stream and never has to buffer the push itself.
    """
    limit = settings.GIT_MAX_REQUEST_BYTES
    if request.META.get("CONTENT_LENGTH"):
        length = int(request.META["CONTENT_LENGTH"])
        if length > limit:
            raise GitRequestTooLarge()
        return iter(lambda: request.read(CHUNK_SIZE), b""), length
    if "chunked" not in request.META.get("HTTP_TRANSFER_ENCODING", "").lower():
        return iter(()), 0
    stream = request.META["wsgi.input"]
    if request.META.get("wsgi.input_terminated"):
        chunks = iter(lambda: stream.read(CHUNK_SIZE), b"")
    else:
        # Django's development server wraps the socket in LimitedStream(limit=Content-Length), which is
        # zero for chunked requests, so read the socket underneath and decode the chunks here.
        raw = SimpleNamespace(read=getattr(stream, "_read", stream.read), readline=getattr(stream, "_readline", stream.readline))
        chunks = _read_chunked(raw)
    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    for chunk in chunks:
        spool.write(chunk)
        if spool.tell() > limit:
            spool.close()
            raise GitRequestTooLarge()
    length = spool.tell()
    spool.seek(0)
    def drain():
        with spool:
            yield from iter(lambda: spool.read(CHUNK_SIZE), b"")
    return drain(), length
class GitBackendStream:
    """Streams git http-backend output to the client and cleans up the process however the response ends."""
    def __init__(self, process, first_chunk, stderr, timer, on_success):
        self.process, self.pending, self.stderr, self.timer, self.on_success = process, first_chunk, stderr, timer, on_success
        self.finished = False
    def __iter__(self):
        return self
    def __next__(self):
        if self.pending:
            chunk, self.pending = self.pending, b""
            return chunk
        chunk = self.process.stdout.read1(CHUNK_SIZE) if not self.finished else b""
        if chunk:
            return chunk
        if not self.finished:
            self.finished = True
            if self.process.wait(timeout=30) == 0 and self.on_success:
                self.on_success()
            elif self.process.returncode:
                self.stderr.seek(0)
                logger.warning("git http-backend exited %s: %s", self.process.returncode, self.stderr.read(2000).decode(errors="replace"))
        self.close()
        raise StopIteration
    def close(self):
        self.timer.cancel()
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        for handle in (self.process.stdout, self.process.stdin, self.stderr):
            try:
                handle.close()
            except OSError:
                pass
def smart_http(repository, request, service_path, on_success=None, stream=True):
    """Run git http-backend as a CGI process, streaming the request in and (when stream=True) the response out."""
    path = repository_path(repository)
    body, length = _request_body(request)
    env = os.environ.copy()
    env.update({"GIT_PROJECT_ROOT": str(path.parent), "GIT_HTTP_EXPORT_ALL": "1", "PATH_INFO": f"/{path.name}/{service_path}", "REQUEST_METHOD": request.method, "QUERY_STRING": request.META.get("QUERY_STRING", ""), "CONTENT_TYPE": request.META.get("CONTENT_TYPE", ""), "CONTENT_LENGTH": str(length), "REMOTE_USER": str(request.user.pk) if request.user.is_authenticated else "", "HTTP_CONTENT_ENCODING": request.META.get("HTTP_CONTENT_ENCODING", ""), "HTTP_GIT_PROTOCOL": request.META.get("HTTP_GIT_PROTOCOL", "")})
    stderr = tempfile.TemporaryFile()
    process = subprocess.Popen([settings.GIT_EXECUTABLE, "http-backend"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, env=env)
    timer = threading.Timer(settings.GIT_HTTP_TIMEOUT, process.kill)
    timer.daemon = True
    timer.start()
    def feed():
        try:
            for chunk in body:
                process.stdin.write(chunk)
        except (OSError, ValueError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
    threading.Thread(target=feed, daemon=True).start()
    buffer = b""
    while b"\r\n\r\n" not in buffer and b"\n\n" not in buffer:
        chunk = process.stdout.read1(CHUNK_SIZE)
        if not chunk:
            break
        buffer += chunk
    separator = b"\r\n\r\n" if b"\r\n\r\n" in buffer else b"\n\n"
    if separator not in buffer:
        stream = GitBackendStream(process, b"", stderr, timer, None)
        stream.close()
        raise RuntimeError("git http-backend returned no headers")
    header_blob, first_chunk = buffer.split(separator, 1)
    headers, status = {}, 200
    for line in header_blob.decode("latin1").splitlines():
        key, value = line.split(":", 1)
        if key.lower() == "status":
            status = int(value.strip().split()[0])
        else:
            headers[key.strip()] = value.strip()
    body = GitBackendStream(process, first_chunk, stderr, timer, on_success if status == 200 else None)
    return status, headers, body if stream else b"".join(body)
COMMIT_SHA = re.compile(r"^[0-9a-f]{7,40}$")
MAX_VIEW_BYTES = 1_000_000
MAX_RAW_BYTES = 25 * 1024 * 1024
MAX_DIFF_CHARS = 400_000
README_NAMES = ("readme.md", "readme.markdown", "readme.txt", "readme")
class MergeConflict(Exception):
    pass
def resolve_ref(repository, ref=None):
    names = {branch["name"] for branch in list_branches(repository)}
    ref = ref or repository.default_branch
    if ref not in names:
        raise ValueError("That branch does not exist.")
    return ref
def clean_repo_path(path):
    path = (path or "").replace("\\", "/").strip("/")
    if any(character in path for character in "\x00\n\r") or ".." in path.split("/") or len(path) > 400:
        raise ValueError("Invalid path.")
    return "/".join(part for part in path.split("/") if part)
def object_type(repository, ref, path):
    try:
        return run_git("cat-file", "-t", f"{ref}:{path}", cwd=repository_path(repository)).stdout.strip()
    except subprocess.CalledProcessError:
        return None
def list_tree(repository, ref, path=""):
    output = run_git_bytes("ls-tree", "-l", "-z", f"{ref}:{path}", cwd=repository_path(repository)).decode("utf-8", errors="replace")
    entries = []
    for entry in output.split("\0"):
        if "\t" not in entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, kind, object_id, size = metadata.split()
        entries.append({"name": name, "path": f"{path}/{name}" if path else name, "kind": kind, "size": None if size == "-" else int(size), "object_id": object_id, "mode": mode})
    return sorted(entries, key=lambda item: (item["kind"] != "tree", item["name"].lower()))
def read_blob(repository, ref, path, limit=MAX_VIEW_BYTES):
    cwd = repository_path(repository)
    size = int(run_git("cat-file", "-s", f"{ref}:{path}", cwd=cwd).stdout.strip())
    data = run_git_bytes("cat-file", "blob", f"{ref}:{path}", cwd=cwd) if size <= limit else b""
    return {"size": size, "data": data, "truncated": size > limit, "binary": b"\0" in data[:8000]}
def find_readme(entries):
    by_name = {entry["name"].lower(): entry for entry in entries if entry["kind"] == "blob"}
    return next((by_name[name] for name in README_NAMES if name in by_name), None)
def last_commit(repository, ref, path=""):
    args = ["log", "-1", "--date=iso-strict", "--format=%H%x1f%h%x1f%an%x1f%ad%x1f%s", ref]
    if path:
        args += ["--", path]
    line = run_git(*args, cwd=repository_path(repository)).stdout.strip()
    return dict(zip(("id", "short_id", "author", "date", "subject"), line.split("\x1f", 4))) if line else None
def parse_diff(text):
    files, current, old_line, new_line, in_hunk = [], None, 0, 0, False
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            parts = raw.split(" b/", 1)
            current = {"path": parts[1] if len(parts) > 1 else raw[11:], "lines": [], "additions": 0, "deletions": 0, "binary": False, "status": "modified"}
            files.append(current)
            in_hunk = False
            continue
        if current is None:
            continue
        if raw.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            old_line, new_line = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
            current["lines"].append({"kind": "hunk", "text": raw, "old": "", "new": ""})
            in_hunk = True
            continue
        if not in_hunk:
            if raw.startswith("new file mode"):
                current["status"] = "added"
            elif raw.startswith("deleted file mode"):
                current["status"] = "deleted"
            elif raw.startswith(("rename from", "similarity index")):
                current["status"] = "renamed"
            elif raw.startswith(("Binary files", "GIT binary patch")):
                current["binary"] = True
            continue
        if raw.startswith("+"):
            current["lines"].append({"kind": "add", "text": raw[1:], "old": "", "new": new_line})
            current["additions"] += 1
            new_line += 1
        elif raw.startswith("-"):
            current["lines"].append({"kind": "del", "text": raw[1:], "old": old_line, "new": ""})
            current["deletions"] += 1
            old_line += 1
        elif not raw.startswith("\\"):
            current["lines"].append({"kind": "context", "text": raw[1:] if raw.startswith(" ") else raw, "old": old_line, "new": new_line})
            old_line += 1
            new_line += 1
    return files
def _diff_text(*args, cwd):
    text = run_git_bytes(*args, cwd=cwd, timeout=60).decode("utf-8", errors="replace")
    return text[:MAX_DIFF_CHARS], len(text) > MAX_DIFF_CHARS
def commit_detail(repository, sha):
    cwd = repository_path(repository)
    if not COMMIT_SHA.fullmatch(sha or ""):
        raise ValueError("Unknown commit.")
    try:
        kind = run_git("cat-file", "-t", sha, cwd=cwd).stdout.strip()
    except subprocess.CalledProcessError:
        kind = None
    if kind != "commit":
        raise ValueError("Unknown commit.")
    meta = run_git("show", "-s", "--date=iso-strict", "--format=%H%x1f%h%x1f%an%x1f%ae%x1f%ad%x1f%s%x1f%P%x1f%b", sha, cwd=cwd).stdout
    commit = dict(zip(("id", "short_id", "author", "email", "date", "subject", "parents", "body"), meta.split("\x1f", 7)))
    commit["parents"] = commit.get("parents", "").split()
    commit["body"] = commit.get("body", "").strip()
    text, truncated = _diff_text("show", "--format=", "--patch", "--no-color", "--find-renames", sha, cwd=cwd)
    return commit, parse_diff(text), truncated
def compare_branches(repository, base, head):
    cwd = repository_path(repository)
    log = run_git("log", "--date=iso-strict", "--format=%H%x1f%h%x1f%an%x1f%ae%x1f%ad%x1f%s", f"{base}..{head}", cwd=cwd).stdout
    commits = [dict(zip(("id", "short_id", "author", "email", "date", "subject"), line.split("\x1f", 5))) for line in log.splitlines()]
    text, truncated = _diff_text("diff", "--no-color", "--find-renames", f"{base}...{head}", cwd=cwd)
    return commits, parse_diff(text), truncated
def can_merge_cleanly(repository, base, head):
    result = subprocess.run([settings.GIT_EXECUTABLE, "merge-tree", "--write-tree", base, head], cwd=repository_path(repository), capture_output=True, timeout=60)
    return {0: True, 1: False}.get(result.returncode)
def merge_branches(repository, base, head, user, message):
    with tempfile.TemporaryDirectory() as checkout_root:
        checkout = Path(checkout_root) / "checkout"
        run_git("clone", "--branch", base, str(repository_path(repository)), str(checkout), timeout=120)
        run_git("config", "user.name", user.get_full_name() or user.username, cwd=checkout)
        run_git("config", "user.email", user.email or user.username, cwd=checkout)
        merge = subprocess.run([settings.GIT_EXECUTABLE, "merge", "--no-ff", "-m", message[:200], f"origin/{head}"], cwd=checkout, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if merge.returncode:
            raise MergeConflict("These branches have conflicts. Merge them locally, push the result, then try again.")
        sha = run_git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
        run_git("push", "origin", f"HEAD:refs/heads/{base}", cwd=checkout, timeout=120)
    return sha
