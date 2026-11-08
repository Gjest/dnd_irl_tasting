"""Photo uploads for bowls and the shopping list.

Every upload is decoded and saved again as a fresh JPEG under a random name.
That throws away anything a file could carry besides the picture, including
the EXIF data phones add, GPS position and all.
"""

import os
import re
import secrets
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_SIDE = 1600
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}
ACCEPT_ATTRIBUTE = "image/jpeg,image/png,image/webp"
NAME_PATTERN = re.compile(r"[0-9a-f]{32}\.jpg")

# A tiny file can claim gigantic dimensions and eat all memory when decoded.
Image.MAX_IMAGE_PIXELS = 40_000_000


class ImageError(ValueError):
    pass


def save_upload(upload, directory):
    """Stores an uploaded photo and returns its file name, or None if there was none."""
    if upload is None or not upload.filename:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload.stream) as original:
                if original.format not in ACCEPTED_FORMATS:
                    raise ImageError("Erlaubt sind Fotos als JPEG, PNG oder WebP.")
                original.load()
                # Phones store "rotate me" in EXIF, which is about to be dropped.
                picture = ImageOps.exif_transpose(original).convert("RGB")
    except ImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError):
        raise ImageError("Das Foto ließ sich nicht lesen. Erlaubt sind JPEG, PNG und WebP.") from None
    picture.thumbnail((MAX_SIDE, MAX_SIDE))
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    name = f"{secrets.token_hex(16)}.jpg"
    tmp = directory / f"{name}.tmp"
    picture.save(tmp, "JPEG", quality=82, optimize=True)
    os.replace(tmp, directory / name)
    return name


def referenced(data):
    return {
        entry["image"]
        for entry in data["chips"] + data["shopping"]
        if entry.get("image")
    }


def discard(directory, names, data):
    """Deletes the given photos unless a bowl or list item still shows them."""
    still_used = referenced(data)
    for name in names:
        if name and name not in still_used and NAME_PATTERN.fullmatch(name):
            (Path(directory) / name).unlink(missing_ok=True)
