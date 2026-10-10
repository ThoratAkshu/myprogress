"""Video chapters ("1:20 The data model", one per line) and WebVTT captions: parsing and validation."""
import re
CHAPTER_LINE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s+(.{1,100})$")
CUE_TIMING = re.compile(r"^((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3})\s+-->\s+((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3})")
CUE_TAGS = re.compile(r"<[^>]*>")
MAX_CAPTIONS_CHARS = 300_000
def format_stamp(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
def _vtt_seconds(stamp):
    parts = stamp.replace(",", ".").split(":")
    seconds = float(parts[-1]) + int(parts[-2]) * 60
    return seconds + (int(parts[-3]) * 3600 if len(parts) == 3 else 0)
def parse_chapters(text):
    """Chapters sorted by time; lines that aren't "m:ss Title" are skipped."""
    chapters = []
    for line in (text or "").splitlines():
        match = CHAPTER_LINE.match(line.strip())
        if match:
            hours, minutes, secs, title = match.groups()
            seconds = int(hours or 0) * 3600 + int(minutes) * 60 + int(secs)
            chapters.append({"seconds": seconds, "stamp": format_stamp(seconds), "title": title.strip()})
    return sorted(chapters, key=lambda chapter: chapter["seconds"])
def clean_chapters(text):
    """Normalized chapter text, or ValueError naming the first line that isn't a chapter."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in lines:
        match = CHAPTER_LINE.match(line)
        if not match or int(match.group(3)) > 59 or (match.group(1) and int(match.group(2)) > 59):
            raise ValueError(f"“{line[:40]}” isn't a chapter. Write each one as a time and a title, like 1:20 The data model.")
    return "\n".join(f"{chapter['stamp']} {chapter['title']}" for chapter in parse_chapters("\n".join(lines)))
def parse_captions(text):
    """Caption cues as plain text with their start times, for the transcript."""
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text or ""):
        lines = [line.strip() for line in block.strip().splitlines()]
        for index, line in enumerate(lines):
            match = CUE_TIMING.match(line)
            if match:
                words = " ".join(CUE_TAGS.sub("", part) for part in lines[index + 1:] if part).strip()
                if words:
                    start = _vtt_seconds(match.group(1))
                    cues.append({"seconds": int(start), "stamp": format_stamp(start), "text": words})
                break
    return cues
def clean_captions(text):
    text = (text or "").strip().replace("\r\n", "\n")
    if not text:
        return ""
    if not text.startswith("WEBVTT"):
        raise ValueError("Captions must be in WebVTT format and start with WEBVTT.")
    if len(text) > MAX_CAPTIONS_CHARS:
        raise ValueError("Captions are too long. Keep them under 300,000 characters.")
    return text + "\n"
