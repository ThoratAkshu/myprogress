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
def _map_time(seconds, parts):
    """Where a moment of the original lands once only `parts` ([start, end] seconds) are kept; a moment in a removed
    part moves to where the next kept part starts. None past the end."""
    offset = 0
    for start, end in parts:
        if seconds < start:
            return offset
        if seconds <= end:
            return offset + seconds - start
        offset += end - start
    return None
def remap_chapters(text, parts):
    """Chapters moved to match a video cut down to `parts`; when two land on the same second, the later one wins."""
    total = sum(end - start for start, end in parts)
    moved = {}
    for chapter in parse_chapters(text):
        seconds = _map_time(chapter["seconds"], parts)
        if seconds is not None and seconds < total - 1:
            moved[int(seconds)] = chapter["title"]
    return "\n".join(f"{format_stamp(seconds)} {title}" for seconds, title in sorted(moved.items()))
def _vtt_stamp(seconds):
    hours, rest = divmod(round(seconds * 1000), 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f"{hours:02d}:{minutes:02d}:{rest // 1000:02d}.{rest % 1000:03d}"
def remap_captions(text, parts):
    """WebVTT captions for a video cut down to `parts`: cues in removed parts dropped, the rest moved to match."""
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text or ""):
        lines = [line.rstrip() for line in block.strip().splitlines()]
        for index, line in enumerate(lines):
            match = CUE_TIMING.match(line.strip())
            if not match:
                continue
            words = "\n".join(part for part in lines[index + 1:] if part.strip())
            start, end = _vtt_seconds(match.group(1)), _vtt_seconds(match.group(2))
            kept = [(a, b) for a, b in parts if b > start and a < end]
            if words and kept:
                new_start, new_end = _map_time(max(start, kept[0][0]), parts), _map_time(min(end, kept[-1][1]), parts)
                if new_end - new_start >= 0.2:
                    cues.append(f"{len(cues) + 1}\n{_vtt_stamp(new_start)} --> {_vtt_stamp(new_end)}\n{words}")
            break
    return "WEBVTT\n\n" + "\n\n".join(cues) + "\n" if cues else ""
def clean_captions(text):
    text = (text or "").strip().replace("\r\n", "\n")
    if not text:
        return ""
    if not text.startswith("WEBVTT"):
        raise ValueError("Captions must be in WebVTT format and start with WEBVTT.")
    if len(text) > MAX_CAPTIONS_CHARS:
        raise ValueError("Captions are too long. Keep them under 300,000 characters.")
    return text + "\n"
