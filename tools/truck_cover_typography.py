"""Deterministic, truck-only cover typography for newly appended groups.

This is a layout plan, not approval evidence.  The reference-like outline is
one of five options; all options retain the same confirmed phone and ten words.
"""

from __future__ import annotations

from typing import Any


FIRST_GROUP = 374
STYLE_VERSION = 3
TYPOGRAPHY_VERSION = 2

_FAMILIES = (
    ("quiet_two_rows", "service_two_rows", (0.025, 0.49, 0.975, 0.585), 0.855),
    ("staggered_rows", "service_staggered", (0.025, 0.54, 0.975, 0.635), 0.83),
    ("split_columns", "service_split_columns", (0.025, 0.455, 0.975, 0.55), 0.83),
    ("featured_rows", "service_featured_top", (0.025, 0.515, 0.975, 0.61), 0.83),
    ("reference_outline", "service_centered", (0.025, 0.48, 0.975, 0.575), 0.83),
)
_PALETTES = (
    ("chalk_red", (251, 248, 242, 255), (45, 43, 40, 255), (169, 41, 36, 255)),
    ("navy_white", (28, 50, 66, 255), (250, 249, 242, 255), (246, 221, 136, 255)),
    ("warm_grey", (235, 232, 226, 255), (44, 48, 50, 255), (60, 99, 116, 255)),
    ("brick_cream", (128, 46, 41, 255), (255, 247, 227, 255), (250, 215, 156, 255)),
    ("cream_green", (249, 247, 231, 255), (40, 66, 54, 255), (74, 105, 67, 255)),
    ("graphite_white", (47, 51, 54, 255), (249, 249, 245, 255), (221, 225, 222, 255)),
)


def cover_plan(group_index: int) -> dict[str, Any]:
    if group_index < FIRST_GROUP:
        raise ValueError("truck cover typography applies only from group 374")
    offset = group_index - FIRST_GROUP
    family_count = len(_FAMILIES)
    # Shift each five-group block so the scene's own five-cycle cannot lock
    # one composition permanently to one local text layout.
    family_index = (offset % family_count + 2 * (offset // family_count)) % family_count
    family, layout, phone_region, bottom_top = _FAMILIES[family_index]
    palette, background, ink, accent = _PALETTES[(offset // len(_FAMILIES)) % len(_PALETTES)]
    reference = family == "reference_outline"
    style_id = f"truck-cover-v3__{family}__{palette}"
    return {
        "version": STYLE_VERSION,
        "typography_version": TYPOGRAPHY_VERSION,
        "style_id": style_id,
        "family": family,
        "reference_supplement": reference,
        "center_phone_region": list(phone_region),
        "bottom_service_region": [0.0, bottom_top, 1.0, 1.0],
        "phone_style": "outlined" if reference else "plain_band",
        "phone_fill": None if reference else background,
        "phone_ink": (255, 240, 163, 255) if reference else ink,
        "bottom_service_style": {
            "version": 1,
            "style_id": style_id,
            "name": palette,
            "layout": layout,
            "background": background,
            "text_colors": ((255, 255, 255, 255),) if reference else (ink,),
            "stroke_fill": (0, 0, 0, 255) if reference else background,
            "accent_color": accent,
            "separator": (*ink[:3], 90),
            "accent": "short_rule",
            "font_scale": 1.0,
        },
    }
