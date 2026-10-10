import mimetypes
import os
import re
from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils._os import safe_join
RANGE_HEADER = re.compile(r"bytes=(\d*)-(\d*)")
CHUNK_SIZE = 64 * 1024
def _read_range(path, start, length):
    with open(path, "rb") as handle:
        handle.seek(start)
        while length > 0:
            chunk = handle.read(min(CHUNK_SIZE, length))
            if not chunk:
                return
            length -= len(chunk)
            yield chunk
def serve_media(request, path):
    """Uploaded files in development, with byte ranges so videos can seek (nginx does this in production)."""
    try:
        full_path = safe_join(settings.MEDIA_ROOT, path)
    except Exception:
        raise Http404
    if not os.path.isfile(full_path):
        raise Http404
    size = os.path.getsize(full_path)
    content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
    match = RANGE_HEADER.fullmatch(request.headers.get("Range", "").strip())
    if match and any(match.groups()):
        first, last = match.groups()
        start, end = (int(first), min(int(last), size - 1) if last else size - 1) if first else (max(0, size - int(last)), size - 1)
        if start >= size or start > end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        response = StreamingHttpResponse(_read_range(full_path, start, end - start + 1), status=206, content_type=content_type)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(end - start + 1)
    else:
        response = FileResponse(open(full_path, "rb"), content_type=content_type)
    response["Accept-Ranges"] = "bytes"
    return response
