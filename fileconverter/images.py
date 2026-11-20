"""Image -> PDF with page setup. No Qt imports."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
DPI = 300
PAPER_MM = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4)}


class ImageError(Exception):
    """The file could not be read as an image."""


@dataclass(frozen=True)
class PageSetup:
    size: Literal["A4", "Letter", "Fit"] = "A4"
    orientation: Literal["Auto", "Portrait", "Landscape"] = "Auto"
    margin_mm: float = 10.0


def _mm_to_px(mm: float) -> int:
    return round(mm / 25.4 * DPI)


def _flatten(im: Image.Image) -> Image.Image:
    """Return an RGB image; transparent areas become white."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return im.convert("RGB")


def to_pdf(src: Path, setup: PageSetup, workdir: Path) -> Path:
    try:
        with Image.open(src) as raw:
            raw.seek(0)  # GIF/TIFF: first frame only
            im = _flatten(ImageOps.exif_transpose(raw))
    except (OSError, SyntaxError, ValueError) as e:
        raise ImageError(f"cannot read image: {src.name}") from e

    margin = _mm_to_px(setup.margin_mm)
    if setup.size == "Fit":
        page_w, page_h = im.width + 2 * margin, im.height + 2 * margin
    else:
        w_mm, h_mm = PAPER_MM[setup.size]
        landscape = setup.orientation == "Landscape" or (
            setup.orientation == "Auto" and im.width > im.height
        )
        if landscape:
            w_mm, h_mm = h_mm, w_mm
        page_w, page_h = _mm_to_px(w_mm), _mm_to_px(h_mm)
        box_w, box_h = max(page_w - 2 * margin, 1), max(page_h - 2 * margin, 1)
        scale = min(box_w / im.width, box_h / im.height)
        new_size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
        if new_size != im.size:
            im = im.resize(new_size, Image.Resampling.LANCZOS)

    page = Image.new("RGB", (page_w, page_h), "white")
    page.paste(im, ((page_w - im.width) // 2, (page_h - im.height) // 2))
    out = workdir / f"{src.stem}-{uuid.uuid4().hex[:8]}.pdf"
    page.save(out, "PDF", resolution=DPI)
    return out
