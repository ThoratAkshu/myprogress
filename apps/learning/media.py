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
