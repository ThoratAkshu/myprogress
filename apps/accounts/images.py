"""Channel logos and banners: checked, resized, and re-encoded on upload.

Re-encoding keeps only the pixels, so nothing else hidden in the uploaded file (metadata, other data, scripts in
an SVG) is ever served back, and every logo and banner is small enough to load quickly.
"""
import io
import uuid
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
MAX_PIXELS = 40_000_000  # refuse "decompression bombs" before decoding them
LOGO_SIZE = 400
LOGO_MAX_BYTES = 2 * 1024 * 1024
BANNER_MAX_WIDTH, BANNER_MAX_HEIGHT = 2048, 1024
BANNER_MIN_WIDTH = 600
BANNER_MAX_BYTES = 6 * 1024 * 1024


def _open(upload, max_bytes, what):
    if upload.size > max_bytes:
        raise ValidationError(f"The {what} must be {max_bytes // (1024 * 1024)} MB or smaller.")
    try:
        upload.seek(0)
        image = Image.open(upload)
        if image.format not in FORMATS:
            raise ValidationError(f"Upload the {what} as a PNG, JPEG, WebP, or GIF image.")
        if image.width * image.height > MAX_PIXELS:
            raise ValidationError(f"That {what} is too large. Use an image under 40 megapixels.")
        image.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise ValidationError(f"That file isn't an image we can read. Upload the {what} as a PNG, JPEG, WebP, or GIF.")
    return ImageOps.exif_transpose(image)


def channel_logo(upload):
    """A square 400x400 PNG, cropped from the centre. Transparency is kept."""
    image = _open(upload, LOGO_MAX_BYTES, "logo")
    image = ImageOps.fit(image.convert("RGBA"), (LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.png")


def channel_banner(upload):
    """A JPEG at most 2048x1024; the page crops it to a wide strip."""
    image = _open(upload, BANNER_MAX_BYTES, "banner")
    if image.width < BANNER_MIN_WIDTH:
        raise ValidationError(f"The banner needs to be at least {BANNER_MIN_WIDTH} pixels wide so it stays sharp.")
    image = image.convert("RGB")
    image.thumbnail((BANNER_MAX_WIDTH, BANNER_MAX_HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85, optimize=True, progressive=True)
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.jpg")
