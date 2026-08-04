#!/usr/bin/env python
"""Regenerate the "under construction" cover placeholder that `cg contribution create` seeds.

    bin/gen-default-cover-image

The result is committed as package data
(`codingame_tools/contribution_manager/assets/cover-placeholder.png`) and shipped in the wheel, so
generating it needs Pillow but *using* it doesn't. That's the whole point of doing it this way: the
image is identical for every contribution, so rendering it at runtime would make every consumer of
this library carry a 15 MB compiled imaging dependency to produce a constant. Pillow is therefore a
dev-only dependency, exactly like the docs generator's.

Deliberately ugly. A cover is the one seeded placeholder that's *visible*--`cg contribution push`
uploads whatever is in `data/cover.png`--so it has to be impossible to mistake for finished artwork
when the author looks at their own contribution page. A tasteful title card would sail through
unnoticed and end up published. Contributions start as private drafts, so nobody else sees this in
the meantime.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "codingame_tools" / "contribution_manager" / "assets" / "cover-placeholder.png"

WIDTH, HEIGHT = 1920, 1080
"""Matches CodinGame's own cover art (measured from a real published contribution)."""

BACKGROUND = (24, 24, 27)
HAZARD_YELLOW = (250, 204, 21)
HAZARD_DARK = (24, 24, 27)
CONE_ORANGE = (249, 115, 22)
CONE_STRIPE = (250, 250, 250)
HAT_YELLOW = (253, 224, 71)
TEXT = (250, 204, 21)
SUBTEXT = (161, 161, 170)

STRIPE_BAND = 90
STRIPE_WIDTH = 60


def _hazard_band(draw: ImageDraw.ImageDraw, top: int) -> None:
    """A band of diagonal hazard stripes across the full width."""
    draw.rectangle([0, top, WIDTH, top + STRIPE_BAND], fill=HAZARD_DARK)
    # Start well left of 0 so the slanted stripes cover the left edge too.
    for x in range(-STRIPE_BAND, WIDTH + STRIPE_BAND, STRIPE_WIDTH * 2):
        draw.polygon(
            [
                (x, top + STRIPE_BAND),
                (x + STRIPE_WIDTH, top + STRIPE_BAND),
                (x + STRIPE_WIDTH + STRIPE_BAND, top),
                (x + STRIPE_BAND, top),
            ],
            fill=HAZARD_YELLOW,
        )


def _traffic_cone(draw: ImageDraw.ImageDraw, cx: int, base_y: int, height: int) -> None:
    half = height * 0.32
    draw.polygon([(cx, base_y - height), (cx - half, base_y), (cx + half, base_y)], fill=CONE_ORANGE)
    # Two reflective bands. Each is a trapezoid matching the cone's own width at that height--
    # `half * f` is the half-width `f` of the way down from the apex--so they don't overhang.
    for lo, hi in ((0.42, 0.54), (0.62, 0.74)):
        y_top, y_bottom = base_y - height * hi, base_y - height * lo
        w_top = half * hi
        w_bottom = half * lo
        draw.polygon(
            [(cx - w_top, y_top), (cx + w_top, y_top), (cx + w_bottom, y_bottom), (cx - w_bottom, y_bottom)],
            fill=CONE_STRIPE,
        )
    draw.rounded_rectangle(
        [cx - half * 1.35, base_y - height * 0.06, cx + half * 1.35, base_y], radius=10, fill=CONE_ORANGE)


def _hard_hat(draw: ImageDraw.ImageDraw, cx: int, base_y: int, width: int) -> None:
    half = width / 2
    draw.ellipse([cx - half, base_y - width * 0.22, cx + half, base_y + width * 0.12], fill=HAT_YELLOW)
    draw.pieslice(
        [cx - half * 0.66, base_y - width * 0.62, cx + half * 0.66, base_y + width * 0.20],
        start=180, end=360, fill=HAT_YELLOW,
    )
    draw.rectangle([cx - half * 0.10, base_y - width * 0.58, cx + half * 0.10, base_y - width * 0.10],
                   fill=CONE_ORANGE)


def render(path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)

    _hazard_band(draw, 0)
    _hazard_band(draw, HEIGHT - STRIPE_BAND)

    title_font = ImageFont.load_default(size=150)
    sub_font = ImageFont.load_default(size=52)
    note_font = ImageFont.load_default(size=40)

    def centered(text: str, font: ImageFont.FreeTypeFont, y: int, fill: tuple[int, int, int]) -> None:
        draw.text(((WIDTH - draw.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)

    centered("UNDER", title_font, 250, TEXT)
    centered("CONSTRUCTION", title_font, 400, TEXT)
    centered("This is a placeholder cover image.", sub_font, 610, SUBTEXT)
    centered("Replace data/cover.png before submitting for review.", note_font, 680, SUBTEXT)

    ground = HEIGHT - STRIPE_BAND - 40
    _traffic_cone(draw, 300, ground, 300)
    _traffic_cone(draw, 1620, ground, 300)
    _hard_hat(draw, 960, ground - 30, 260)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT_PATH
    render(output)
    print(f"wrote {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
