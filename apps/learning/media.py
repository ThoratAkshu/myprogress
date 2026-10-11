import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from django.core.exceptions import ValidationError
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 5 * 1024 * 1024
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
def validate_video_file(upload):
    extension = Path(upload.name).suffix.lower()
    if extension not in {".mp4", ".webm"}:
        raise ValidationError("Upload an MP4 or WebM video.")
    if upload.size > MAX_VIDEO_BYTES:
        raise ValidationError("Videos must be 200 MB or smaller.")
    upload.seek(0)
    header = upload.read(12)
    upload.seek(0)
    is_mp4 = header[4:8] == b"ftyp"
    is_webm = header[:4] == b"\x1aE\xdf\xa3"
    if not (is_mp4 if extension == ".mp4" else is_webm):
        raise ValidationError("That file is not a valid video.")
def youtube_embed_url(url):
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    video_id = ""
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = parsed.path.split("/")[2]
    elif host == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/")[0]
    return f"https://www.youtube-nocookie.com/embed/{video_id}" if YOUTUBE_ID.match(video_id) else ""
PRIVATE_PREFIX = "private/"
def place_post_files(post):
    """Keep an organization post's video and thumbnail in the private folder, which is only reachable through
    the members-only media view, and move them back out if the post becomes public."""
    private = bool(post.organization_id and not post.is_public)
    moved = []
    for field_name in ["video_file", "thumbnail"]:
        field = getattr(post, field_name)
        if not field or field.name.startswith(PRIVATE_PREFIX) == private:
            continue
        storage, old_name = field.storage, field.name
        new_name = PRIVATE_PREFIX + old_name if private else old_name[len(PRIVATE_PREFIX):]
        with storage.open(old_name, "rb") as handle:
            field.name = storage.save(new_name, handle)
        storage.delete(old_name)
        moved.append(field_name)
    if moved:
        type(post).objects.filter(pk=post.pk).update(**{name: getattr(post, name).name for name in moved})
    return moved
