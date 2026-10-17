"""Class recordings from the teaching board: pieces appended to one private file as the class happens, then a
Duration written into the WebM so players can show the length and seek (browsers record WebM without one)."""
import os
import struct
import tempfile
from django.conf import settings

EBML, SEGMENT, SEEK_HEAD, INFO = 0x1A45DFA3, 0x18538067, 0x114D9B74, 0x1549A966
TIMECODE_SCALE, DURATION = 0x2AD7B1, 0x4489
TRACKS, TRACK_ENTRY, TRACK_NUMBER, TRACK_TYPE = 0x1654AE6B, 0xAE, 0xD7, 0x83
CLUSTER, CLUSTER_TIMECODE, SIMPLE_BLOCK, BLOCK_GROUP, BLOCK, REFERENCE_BLOCK = 0x1F43B675, 0xE7, 0xA3, 0xA0, 0xA1, 0xFB
HEAD_BYTES = 64 * 1024
RECENT_KEYFRAMES = 30  # enough for a student to join a few seconds behind the teacher


def file_path(recording):
    return os.path.join(settings.MEDIA_ROOT, *recording.file_name.split("/"))


def start_file(recording):
    path = file_path(recording)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


def append_piece(recording, upload):
    with open(file_path(recording), "ab") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)


def starts_like_video(recording):
    with open(file_path(recording), "rb") as handle:
        header = handle.read(12)
    return header[:4] == b"\x1aE\xdf\xa3" or header[4:8] == b"ftyp"


def _vint(data, at, keep_marker):
    first = data[at]
    length = 1
    while length <= 8 and not first & (0x80 >> (length - 1)):
        length += 1
    if length > 8 or at + length > len(data):
        raise ValueError("Unexpected WebM layout")
    mask = (0x80 >> (length - 1)) - 1
    value = first if keep_marker else first & mask
    unknown = (first & mask) == mask
    for index in range(1, length):
        value = value * 256 + data[at + index]
        if data[at + index] != 0xFF:
            unknown = False
    return value, length, unknown


def _element(data, at):
    """(id, where the size starts, where the data starts, size, size unknown)"""
    element_id, id_length, _ = _vint(data, at, True)
    size, size_length, unknown = _vint(data, at + id_length, False)
    return element_id, at + id_length, at + id_length + size_length, size, unknown


def _uint(data, start, size):
    return int.from_bytes(data[start:start + size], "big")


def _children(data, start, end):
    """(id, data start, size) of each child element in data[start:end]."""
    at = start
    while at < end:
        element_id, _, child_start, size, _ = _element(data, at)
        yield element_id, child_start, size
        at = child_start + size


def keyframes_path(recording):
    return file_path(recording) + ".keys"


def index_stream(recording):
    """Read the part of a broadcast uploaded since last time. Notes where the header ends (what every student's
    player needs first) and where each cluster that starts with a video keyframe begins (where a student joining
    late can start). Browsers start a new cluster at each keyframe; the board asks for one every 2 seconds.
    Returns the updated state; the caller saves it. Stops at an element that isn't complete yet and picks it up
    on the next piece."""
    state = dict(recording.stream_state or {})
    scanned = state.get("scanned", 0)
    with open(file_path(recording), "rb") as handle:
        handle.seek(scanned)
        data = handle.read()
    at, found = 0, []
    try:
        if state.get("init") is None:
            element_id, _, start, size, _ = _element(data, 0)
            if element_id != EBML:
                raise ValueError("Not a WebM stream")
            element_id, _, at, _, _ = _element(data, start + size)
            if element_id != SEGMENT:
                raise ValueError("Not a WebM stream")
            while True:  # the Segment's header elements, up to the first cluster
                element_id, _, start, size, unknown = _element(data, at)
                if element_id == CLUSTER:
                    state["init"] = scanned + at
                    break
                if unknown or start + size > len(data):
                    raise IndexError("Header not complete yet")
                if element_id == INFO:
                    for child_id, child_start, child_size in _children(data, start, start + size):
                        if child_id == TIMECODE_SCALE:
                            state["scale"] = _uint(data, child_start, child_size)
                elif element_id == TRACKS:
                    for entry_id, entry_start, entry_size in _children(data, start, start + size):
                        if entry_id == TRACK_ENTRY:
                            fields = {child_id: _uint(data, child_start, child_size) for child_id, child_start, child_size in _children(data, entry_start, entry_start + entry_size) if child_id in {TRACK_NUMBER, TRACK_TYPE}}
                            if fields.get(TRACK_TYPE) == 1:
                                state["video"] = fields.get(TRACK_NUMBER)
                at = start + size
        scale = state.get("scale") or 1_000_000
        while at < len(data):  # clusters (unknown size: their children follow in the stream) and their contents
            element_id, _, start, size, unknown = _element(data, at)
            if element_id == CLUSTER:
                state["cluster"] = {"offset": scanned + at, "ms": None, "decided": False}
                at = start
                continue
            if start + size > len(data):
                break  # not complete yet
            cluster = state.get("cluster")
            if cluster and element_id == CLUSTER_TIMECODE:
                cluster["ms"] = round(_uint(data, start, size) * scale / 1_000_000)
                state["last_ms"] = cluster["ms"]
            elif cluster and not cluster["decided"] and element_id in {SIMPLE_BLOCK, BLOCK_GROUP}:
                track, keyframe = None, False
                if element_id == SIMPLE_BLOCK:
                    track, track_length, _ = _vint(data, start, False)
                    keyframe = bool(data[start + track_length + 2] & 0x80)
                else:
                    referenced = False
                    for child_id, child_start, _ in _children(data, start, start + size):
                        if child_id == BLOCK:
                            track, _, _ = _vint(data, child_start, False)
                        elif child_id == REFERENCE_BLOCK:
                            referenced = True
                    keyframe = not referenced
                if track == state.get("video"):
                    cluster["decided"] = True
                    if keyframe and cluster["ms"] is not None:
                        found.append([cluster["offset"], cluster["ms"]])
            at = start + size
    except (ValueError, IndexError):
        pass  # an element cut off at the end of what's uploaded so far
    # The header is read in one go from the start of the file, so until it's complete nothing counts as read.
    state["scanned"] = scanned + at if state.get("init") is not None else 0
    if found:
        state["recent"] = (state.get("recent", []) + found)[-RECENT_KEYFRAMES:]
        with open(keyframes_path(recording), "a", encoding="ascii") as handle:
            handle.writelines(f"{offset} {ms}\n" for offset, ms in found)
    return state


def join_point(state, behind_ms=4000):
    """Where a student joining now starts: the latest keyframe at least `behind_ms` before the live edge, so the
    player has a little buffer, or the earliest one kept."""
    recent = state.get("recent") or []
    if not recent:
        return None
    edge = state.get("last_ms") or recent[-1][1]
    for offset, ms in reversed(recent):
        if edge - ms >= behind_ms:
            return offset
    return recent[0][0]


def _patched_head(head, milliseconds):
    """The file's first bytes with a Duration in the Segment Info, or None when the layout isn't the simple one browsers write."""
    element_id, _, data_start, size, _ = _element(head, 0)
    if element_id != EBML:
        return None
    element_id, _, segment_start, _, unknown = _element(head, data_start + size)
    if element_id != SEGMENT or not unknown:
        return None
    at = segment_start
    while at < len(head) - 16:
        element_id, size_at, data_start, size, unknown = _element(head, at)
        if element_id == SEEK_HEAD or unknown:
            return None  # a seek index or a cluster comes first
        if element_id == INFO:
            end = data_start + size
            if end > len(head):
                return None
            scale, duration_at, duration_size, child = 1_000_000, -1, 0, data_start
            while child < end:
                child_id, _, child_data, child_size, _ = _element(head, child)
                if child_id == TIMECODE_SCALE:
                    scale = int.from_bytes(head[child_data:child_data + child_size], "big") or 1_000_000
                elif child_id == DURATION:
                    duration_at, duration_size = child_data, child_size
                child = child_data + child_size
            duration = milliseconds * 1_000_000 / scale
            if duration_at >= 0 and duration_size in {4, 8}:
                patched = bytearray(head)
                struct.pack_into(">d" if duration_size == 8 else ">f", patched, duration_at, duration)
                return bytes(patched)
            duration_element = b"\x44\x89\x88" + struct.pack(">d", duration)
            new_size = b"\x01" + (size + len(duration_element)).to_bytes(7, "big")
            return head[:size_at] + new_size + head[data_start:end] + duration_element + head[end:]
        at = data_start + size
    return None


def add_duration(path, milliseconds):
    """Write the recording's length into a browser-made WebM. Returns True when the file changed."""
    with open(path, "rb") as handle:
        head = handle.read(HEAD_BYTES)
    try:
        patched = _patched_head(head, milliseconds)
    except (ValueError, IndexError):
        return False
    if patched is None:
        return False
    if len(patched) == len(head):
        with open(path, "r+b") as handle:
            handle.write(patched)
        return True
    # The new element makes the header longer, so the whole file is rewritten next to it, then swapped in.
    folder = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(dir=folder, suffix=".part")
    try:
        with os.fdopen(descriptor, "wb") as out, open(path, "rb") as source:
            out.write(patched)
            source.seek(len(head))
            while chunk := source.read(1024 * 1024):
                out.write(chunk)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return True
