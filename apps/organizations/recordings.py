"""Class recordings from the teaching board: pieces appended to one private file as the class happens. When the
class ends, a seekable copy is written (browsers record WebM without a length or a seek index), and that copy is
what the teacher trims and cuts. Cuts land on keyframes, so the kept parts are copied as they are, without
re-encoding: an hour-long class is cut in seconds."""
import bisect
import os
import shutil
import struct
import tempfile
from django.conf import settings

EBML, SEGMENT, SEEK_HEAD, INFO = 0x1A45DFA3, 0x18538067, 0x114D9B74, 0x1549A966
TIMECODE_SCALE, DURATION = 0x2AD7B1, 0x4489
TRACKS, TRACK_ENTRY, TRACK_NUMBER, TRACK_TYPE = 0x1654AE6B, 0xAE, 0xD7, 0x83
CLUSTER, CLUSTER_TIMECODE, SIMPLE_BLOCK, BLOCK_GROUP, BLOCK, REFERENCE_BLOCK = 0x1F43B675, 0xE7, 0xA3, 0xA0, 0xA1, 0xFB
SEEK, SEEK_ID, SEEK_POSITION = 0x4DBB, 0x53AB, 0x53AC
CUES, CUE_POINT, CUE_TIME, CUE_TRACK_POSITIONS, CUE_TRACK, CUE_CLUSTER_POSITION = 0x1C53BB6B, 0xBB, 0xB3, 0xB7, 0xF7, 0xF1
TAGS, CHAPTERS, ATTACHMENTS = 0x1254C367, 0x1043A770, 0x1941A469
SEGMENT_LEVEL = {SEEK_HEAD, INFO, TRACKS, CUES, TAGS, CHAPTERS, ATTACHMENTS}  # these end a cluster of unknown size
HEAD_BYTES = 64 * 1024
READ_BYTES = 4 * 1024 * 1024
RECENT_KEYFRAMES = 30  # enough for a student to join a few seconds behind the teacher


def media_path(name):
    return os.path.join(settings.MEDIA_ROOT, *name.split("/"))


def file_path(recording):
    return media_path(recording.file_name)


def source_path(recording):
    """The whole recording the editor plays and cuts: the seekable copy, or the upload for recordings made before
    copies were written (or that aren't WebM)."""
    return media_path(recording.source_name or recording.file_name)


def start_file(recording):
    path = file_path(recording)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


def append_piece(recording, upload):
    """Add a piece after the pieces accepted so far (`recording.size`). Bytes past that are from a request that
    failed after writing, and its piece is being sent again, so they're dropped rather than kept twice."""
    with open(file_path(recording), "r+b") as handle:
        handle.truncate(recording.size)
        handle.seek(recording.size)
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


def _id_bytes(element_id):
    return element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")


def _size_bytes(size, length=None):
    length = length or next(n for n in range(1, 9) if size < (1 << (7 * n)) - 1)
    return ((1 << (7 * length)) | size).to_bytes(length, "big")


def _uint_bytes(value):
    return value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")


def _el(element_id, payload):
    return _id_bytes(element_id) + _size_bytes(len(payload)) + payload


class _Reader:
    """Reads a file a window at a time, so walking a long recording never holds it all in memory."""
    def __init__(self, handle):
        self.handle = handle
        self.size = handle.seek(0, os.SEEK_END)
        self.base, self.data = 0, b""

    def read(self, at, length):
        if at < self.base or at + length > self.base + len(self.data):
            self.handle.seek(at)
            self.data, self.base = self.handle.read(max(length, READ_BYTES)), at
        return self.data[at - self.base:at - self.base + length]

    def element(self, at):
        """_element at a position in the file; the positions it returns are in the file too."""
        element_id, size_at, start, size, unknown = _element(self.read(at, 12), 0)
        return element_id, at + size_at, at + start, size, unknown


def _scan(path):
    """How a browser-made WebM is laid out: the header elements to keep, and each cluster with where its timecode
    is and whether it starts with a video keyframe. An element cut off at the end (a class that ended mid-upload)
    is left out."""
    with open(path, "rb") as handle:
        reader = _Reader(handle)
        element_id, _, start, size, _ = reader.element(0)
        if element_id != EBML:
            raise ValueError("Not a WebM file")
        ebml = reader.read(0, start + size)
        element_id, _, at, segment_size, unknown = reader.element(len(ebml))
        if element_id != SEGMENT:
            raise ValueError("Not a WebM file")
        media_end = reader.size if unknown else min(reader.size, at + segment_size)
        scale, video, info, tracks = 1_000_000, None, b"", b""
        while True:  # the header elements, up to the first cluster; an old seek index or cue index is dropped
            element_id, _, start, size, unknown = reader.element(at)
            if element_id == CLUSTER:
                break
            if unknown or start + size > media_end:
                raise ValueError("Unexpected WebM layout")
            body = reader.read(start, size)
            if element_id == INFO:
                child = 0
                while child < size:
                    child_id, _, child_start, child_size, _ = _element(body, child)
                    if child_id == TIMECODE_SCALE:
                        scale = _uint(body, child_start, child_size) or 1_000_000
                    if child_id != DURATION:  # a new length is written
                        info += body[child:child_start + child_size]
                    child = child_start + child_size
            elif element_id == TRACKS:
                tracks = reader.read(at, start + size - at)
                for entry_id, entry_start, entry_size in _children(body, 0, size):
                    if entry_id == TRACK_ENTRY:
                        fields = {child_id: _uint(body, child_start, child_size) for child_id, child_start, child_size in _children(body, entry_start, entry_start + entry_size) if child_id in {TRACK_NUMBER, TRACK_TYPE}}
                        if fields.get(TRACK_TYPE) == 1 and video is None:
                            video = fields.get(TRACK_NUMBER)
            at = start + size
        if not tracks:
            raise ValueError("No tracks in this recording")
        clusters, cluster, end_ticks = [], None, 0
        while at < media_end:  # clusters of unknown size: walk their children as they come
            try:
                element_id, _, start, size, unknown = reader.element(at)
                if element_id == CLUSTER:
                    if cluster:
                        clusters.append({**cluster, "end": at})
                    cluster = {"offset": at, "tc_at": 0, "tc_size": 0, "ticks": None, "key": False, "decided": False}
                    at = start
                    continue
                if element_id in SEGMENT_LEVEL or unknown or start + size > media_end:
                    break  # the cue index after the clusters, or the end of what was uploaded
                if cluster and element_id == CLUSTER_TIMECODE:
                    cluster.update(tc_at=start, tc_size=size, ticks=int.from_bytes(reader.read(start, size), "big"))
                elif cluster and cluster["ticks"] is not None and element_id in {SIMPLE_BLOCK, BLOCK_GROUP}:
                    block, referenced = start, False
                    if element_id == BLOCK_GROUP:
                        block, inner = None, start
                        while inner < start + size:
                            child_id, _, child_start, child_size, _ = reader.element(inner)
                            if child_id == BLOCK:
                                block = child_start
                            elif child_id == REFERENCE_BLOCK:
                                referenced = True
                            inner = child_start + child_size
                    if block is not None:
                        head = reader.read(block, 12)
                        track, track_length, _ = _vint(head, 0, False)
                        end_ticks = max(end_ticks, cluster["ticks"] + struct.unpack_from(">h", head, track_length)[0])
                        if track == video and not cluster["decided"]:
                            cluster["decided"] = True
                            cluster["key"] = bool(head[track_length + 2] & 0x80) if element_id == SIMPLE_BLOCK else not referenced
            except (ValueError, IndexError, struct.error):
                break
            at = start + size
        if cluster:
            clusters.append({**cluster, "end": at})
    return {"ebml": ebml, "info": info, "tracks": tracks, "scale": scale, "video": video, "end_ticks": end_ticks, "clusters": [item for item in clusters if item["ticks"] is not None]}


def _runs(layout, hint_ms=0):
    """The parts a recording can be cut into: each starts at a video keyframe and runs until the next one, so it
    plays on its own. [start ticks, end ticks, clusters] each."""
    runs = []
    for cluster in layout["clusters"]:
        if not runs or cluster["key"]:
            runs.append([cluster["ticks"], 0, [cluster]])
        else:
            runs[-1][2].append(cluster)
    end = max(layout["end_ticks"], round(hint_ms * 1_000_000 / layout["scale"]))
    for index, run in enumerate(runs):
        run[1] = runs[index + 1][0] if index + 1 < len(runs) else max(end, run[0] + 1)
    return runs


def _copy(handle, out, start, end):
    handle.seek(start)
    left = end - start
    while left > 0:
        chunk = handle.read(min(left, 1024 * 1024))
        if not chunk:
            raise ValueError("The recording ends early")
        out.write(chunk)
        left -= len(chunk)


def write_copy(source, destination, keep_ms=None, hint_ms=0):
    """Write `source` again as a WebM players can seek in: a seek index at the front, the length in its info and a
    keyframe index (cues) at the end. With `keep_ms` (pairs of milliseconds from snap_parts), only the parts that
    start inside them are kept, with cluster timecodes moved down so they play one after another; the video
    itself is copied as it is. Returns {"duration_ms", "keyframes_ms", "size"} of the new file."""
    layout = _scan(source)
    runs = _runs(layout, hint_ms)
    to_ms = lambda ticks: round(ticks * layout["scale"] / 1_000_000)  # noqa: E731
    kept = [run for run in runs if keep_ms is None or any(start <= to_ms(run[0]) < end for start, end in keep_ms)]
    if not kept:
        raise ValueError("Nothing of the recording is kept")
    placed, position, out_ticks = [], 0, 0  # (cluster, new timecode, where it lands among the clusters, starts a part)
    for start, end, clusters in kept:
        shift = start - out_ticks
        for index, cluster in enumerate(clusters):
            placed.append((cluster, max(0, cluster["ticks"] - shift), position, index == 0))
            position += cluster["end"] - cluster["offset"]
        out_ticks += max(0, end - start)
    info = _el(INFO, layout["info"] + _el(DURATION, struct.pack(">d", float(out_ticks))))
    tracks, video = layout["tracks"], layout["video"]

    def seek_head(positions):
        return _el(SEEK_HEAD, b"".join(_el(SEEK, _el(SEEK_ID, _id_bytes(element)) + _el(SEEK_POSITION, at.to_bytes(8, "big"))) for element, at in positions))
    entries = [INFO, TRACKS] + ([CUES] if video else [])
    head_length = len(seek_head([(element, 0) for element in entries]))
    clusters_at = head_length + len(info) + len(tracks)  # positions count from the start of the segment's data
    cues = _el(CUES, b"".join(
        _el(CUE_POINT, _el(CUE_TIME, _uint_bytes(ticks)) + _el(CUE_TRACK_POSITIONS, _el(CUE_TRACK, _uint_bytes(video)) + _el(CUE_CLUSTER_POSITION, _uint_bytes(clusters_at + at))))
        for _, ticks, at, first in placed if first
    )) if video else b""
    seek = seek_head([(INFO, head_length), (TRACKS, head_length + len(info))] + ([(CUES, clusters_at + position)] if cues else []))
    segment = _id_bytes(SEGMENT) + _size_bytes(len(seek) + len(info) + len(tracks) + position + len(cues), 8)
    folder = os.path.dirname(destination)
    os.makedirs(folder, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=folder, suffix=".part")
    try:
        with os.fdopen(descriptor, "wb") as out, open(source, "rb") as handle:
            out.write(layout["ebml"] + segment + seek + info + tracks)
            for cluster, ticks, _, _ in placed:
                _copy(handle, out, cluster["offset"], cluster["tc_at"])
                out.write(ticks.to_bytes(cluster["tc_size"], "big"))
                _copy(handle, out, cluster["tc_at"] + cluster["tc_size"], cluster["end"])
            out.write(cues)
            size = out.tell()
        os.replace(temporary, destination)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return {"duration_ms": to_ms(out_ticks), "keyframes_ms": [to_ms(ticks) for _, ticks, _, first in placed if first], "size": size}


def snap_parts(parts, marks):
    """Kept parts as [start, end] milliseconds, moved to the nearest places the video can be cut (`marks`: its
    keyframes and its end), with overlapping parts merged and empty ones dropped."""
    marks = sorted(set(marks))
    if not marks:
        return []

    def nearest(ms):
        index = bisect.bisect_left(marks, ms)
        return min(marks[max(0, index - 1):index + 1], key=lambda mark: abs(mark - ms))
    snapped = []
    for start, end in sorted(parts):
        start, end = nearest(start), nearest(end)
        if end <= start:
            continue
        if snapped and start <= snapped[-1][1]:
            snapped[-1][1] = max(snapped[-1][1], end)
        else:
            snapped.append([start, end])
    return snapped


def prepare_source(recording, hint_ms=0):
    """Write the seekable copy of a finished recording that the editor plays and cuts, and note its length and
    keyframes on `recording` (the caller saves it). False when the upload isn't a WebM this can read: the upload
    itself is then the source, and it can't be cut."""
    if recording.extension != "webm":
        return False
    name = f"private/class-recordings/{recording.token}-full.webm"
    try:
        result = write_copy(file_path(recording), media_path(name), None, hint_ms)
    except (ValueError, IndexError, struct.error, OverflowError):
        return False
    recording.source_name, recording.duration_ms, recording.keyframes = name, result["duration_ms"], result["keyframes_ms"]
    return True


def remove_upload(recording):
    """Delete the class as it was uploaded now the seekable copy has taken its place. False if the file is still
    open (Windows), so it's tried again later."""
    if not recording.source_name or recording.source_name == recording.file_name:
        return True
    try:
        os.remove(file_path(recording))
    except FileNotFoundError:
        pass
    except PermissionError:
        return False
    return True


def place_whole(source, destination):
    """The whole recording at `destination` without using more disk where the file system allows it (a second
    name for the same file), else a copy."""
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copyfile(source, destination)


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


def header_duration_ms(path):
    """The length a WebM's header states, in milliseconds; 0 when it doesn't say."""
    with open(path, "rb") as handle:
        head = handle.read(HEAD_BYTES)
    try:
        element_id, _, start, size, _ = _element(head, 0)
        if element_id != EBML:
            return 0
        element_id, _, at, _, _ = _element(head, start + size)
        if element_id != SEGMENT:
            return 0
        while at < len(head):
            element_id, _, start, size, unknown = _element(head, at)
            if element_id == CLUSTER or unknown:
                return 0  # the clusters started without a length
            if element_id == INFO:
                scale, duration = 1_000_000, 0.0
                for child_id, child_start, child_size in _children(head, start, min(start + size, len(head))):
                    if child_id == TIMECODE_SCALE:
                        scale = _uint(head, child_start, child_size) or 1_000_000
                    elif child_id == DURATION and child_size in {4, 8}:
                        duration = struct.unpack(">d" if child_size == 8 else ">f", head[child_start:child_start + child_size])[0]
                return max(0, round(duration * scale / 1_000_000))
            at = start + size
    except (ValueError, IndexError, struct.error):
        pass
    return 0


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
