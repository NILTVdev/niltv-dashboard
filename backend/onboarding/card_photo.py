"""Finalist card photos for niltv.com/communitystar.

Any JPEG, PNG or WebP becomes an 800px square WebP with no metadata, stored on
the content CDN under a hash of its bytes, so the immutable cache header is safe.
"""

from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.config import get_settings

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 50_000_000
SIZE = 800
_FORMATS = ("JPEG", "PNG", "WEBP")


class PhotoError(ValueError):
    """The upload is not a usable image. The message is safe to show."""


def to_card_webp(data: bytes) -> bytes:
    """Upright, centre-cropped, 800px square WebP. EXIF, GPS and every other
    metadata block stay behind: only the pixels are copied across."""
    if len(data) > MAX_BYTES:
        raise PhotoError("the photo must be 5 MB or smaller")
    try:
        with Image.open(io.BytesIO(data), formats=_FORMATS) as src:
            if src.width * src.height > MAX_PIXELS:
                raise PhotoError("the photo is too large")
            upright = ImageOps.exif_transpose(src).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as e:
        if isinstance(e, PhotoError):
            raise
        raise PhotoError("upload a JPEG, PNG or WebP image") from e
    square = ImageOps.fit(upright, (SIZE, SIZE), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    clean = Image.new("RGB", square.size)
    clean.paste(square)
    out = io.BytesIO()
    clean.save(out, format="WEBP", quality=85, method=6)
    return out.getvalue()


def upload(application_id: int, webp: bytes) -> str:
    """Put the card on the content bucket and return its public URL."""
    import boto3

    s = get_settings()
    digest = hashlib.sha256(webp).hexdigest()[:12]
    key = f"library/communitystar/finalists/{application_id}-{digest}.webp"
    boto3.client("s3", region_name=s.aws_region).put_object(
        Bucket=s.community_star_photo_bucket, Key=key, Body=webp,
        ContentType="image/webp", CacheControl="public, max-age=31536000, immutable")
    return f"{s.community_star_photo_cdn.rstrip('/')}/{key}"
