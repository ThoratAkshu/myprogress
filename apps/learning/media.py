import re
import struct
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
def _mp4_seconds(handle):
    """The length an MP4 states in its movie header (mvhd), wherever the movie box sits in the file."""
    end, at = handle.seek(0, 2), 0
    while at + 8 <= end:
        handle.seek(at)
        header = handle.read(16)
        size, kind = struct.unpack(">I4s", header[:8])
        start = 8
        if size == 1:
            size, start = struct.unpack(">Q", header[8:16])[0], 16
        elif size == 0:
            size = end - at
        if size < start:
            return 0
        if kind == b"moov":
            handle.seek(at + start)
            movie = handle.read(min(size - start, 1024 * 1024))
            child = 0
            while child + 8 <= len(movie):
                child_size, child_kind = struct.unpack(">I4s", movie[child:child + 8])
                if child_kind == b"mvhd":
                    body = movie[child + 8:child + child_size]
                    scale, length = struct.unpack(">II", body[12:20]) if body[0] == 0 else struct.unpack(">IQ", body[20:32])
                    return length // scale if scale else 0
                if child_size < 8:
                    return 0
                child += child_size
            return 0
        at += size
    return 0
def video_seconds(path):
    """A WebM's or MP4's length in whole seconds, from its header; 0 when the file doesn't say."""
    from apps.organizations.recordings import header_duration_ms
    try:
        with open(path, "rb") as handle:
            head = handle.read(12)
            if head[4:8] == b"ftyp":
                return _mp4_seconds(handle)
        return header_duration_ms(path) // 1000 if head[:4] == b"\x1aE\xdf\xa3" else 0
    except (OSError, ValueError, IndexError, struct.error):
        return 0
def note_duration(post):
    """Keep the post's video length, shown on its thumbnail, in step with its video file."""
    try:
        seconds = video_seconds(post.video_file.path) if post.video_file else 0
    except NotImplementedError:  # remote storage: no local file to read
        return
    if seconds != post.duration:
        type(post).objects.filter(pk=post.pk).update(duration=seconds)
        post.duration = seconds
