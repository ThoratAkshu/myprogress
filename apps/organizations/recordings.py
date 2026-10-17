"""Class recordings from the teaching board: pieces appended to one private file as the class happens, then a
Duration written into the WebM so players can show the length and seek (browsers record WebM without one)."""
import os
import struct
import tempfile
from django.conf import settings

EBML, SEGMENT, SEEK_HEAD, INFO = 0x1A45DFA3, 0x18538067, 0x114D9B74, 0x1549A966
TIMECODE_SCALE, DURATION = 0x2AD7B1, 0x4489
HEAD_BYTES = 64 * 1024


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
