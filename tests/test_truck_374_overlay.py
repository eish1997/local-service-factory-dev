from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

from tools import category_image_production as production
from tools import truck_cover_typography


PHONE = "13407128962"
ITEMS = [
    "货车救援", "货车维修", "应急送油", "爆胎救援", "货车补胎",
    "货车换胎", "发动机检修", "搭电启动", "刹车检修", "制动检修",
]


class Truck374OverlayTests(unittest.TestCase):
    def test_history_and_other_categories_keep_legacy_parameters(self) -> None:
        for index in (1, 94, 274, 370, 371, 372, 373):
            self.assertEqual(production.cover_overlay_style(index, "truck_rescue"), production.cover_overlay_style(index))
            self.assertEqual(production.cover_style_version("truck_rescue", index), 2)
            self.assertEqual(production.cover_center_phone_region("truck_rescue", index), [.025, .43, .975, .535])
        for category in ("pipe_unclogging", "pet_transport", "road_rescue", "ktv"):
            for index in (373, 374, 378, 403):
                self.assertEqual(production.cover_overlay_style(index, category), production.cover_overlay_style(index))
        self.assertEqual(production.cover_style_version("truck_rescue", 374), 3)
        with self.assertRaises(ValueError):
            truck_cover_typography.cover_plan(373)

    def test_thirty_groups_have_five_balanced_layouts_and_minority_reference(self) -> None:
        plans = [truck_cover_typography.cover_plan(index) for index in range(374, 404)]
        self.assertEqual(Counter(plan["family"] for plan in plans), {
            "quiet_two_rows": 6, "staggered_rows": 6, "split_columns": 6,
            "featured_rows": 6, "reference_outline": 6,
        })
        self.assertEqual(sum(plan["reference_supplement"] for plan in plans), 6)
        self.assertEqual(len({plan["style_id"] for plan in plans}), 30)
        self.assertEqual(len({tuple(plan["center_phone_region"]) for plan in plans}), 5)
        for index, plan in zip(range(374, 404), plans):
            self.assertEqual(plan, truck_cover_typography.cover_plan(index))
        for left, right in zip(plans, plans[1:]):
            self.assertNotEqual(left["family"], right["family"])
            self.assertNotEqual(left["bottom_service_style"]["layout"], right["bottom_service_style"]["layout"])

    def test_typography_is_decoupled_from_scene_five_cycle(self) -> None:
        families = [
            "quiet_two_rows", "staggered_rows", "split_columns",
            "featured_rows", "reference_outline",
        ]
        plans = [truck_cover_typography.cover_plan(374 + offset) for offset in range(30)]
        self.assertEqual([plan["family"] for plan in plans[:5]], families)
        for start in range(0, 30, 5):
            self.assertEqual({plan["family"] for plan in plans[start:start + 5]}, set(families))
        for scene_index in range(5):
            # Each scene family meets all five typography families by group 398.
            self.assertEqual({plans[offset]["family"] for offset in range(scene_index, 25, 5)}, set(families))
        for offset, plan in enumerate(plans):
            family_index = (offset % 5 + 2 * (offset // 5)) % 5
            self.assertEqual(plan["family"], families[family_index])
            self.assertEqual(plan, truck_cover_typography.cover_plan(374 + offset))

    def test_all_families_render_complete_text_within_boxes_at_three_heights(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for height in (1408, 1472, 1536):
                raw = root / "raw.png"
                Image.new("RGB", (1024, height), (91, 123, 157)).save(raw)
                for index in range(374, 379):
                    plan = truck_cover_typography.cover_plan(index)
                    calls = []
                    original = production._centered_text

                    def checked_text(draw, box, text, font, fill, stroke=0, stroke_fill=None):
                        bounds = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
                        self.assertLessEqual(bounds[2] - bounds[0], box[2] - box[0])
                        self.assertLessEqual(bounds[3] - bounds[1], box[3] - box[1])
                        self.assertGreaterEqual(font.size, 30)
                        calls.append((text, box))
                        return original(draw, box, text, font, fill, stroke, stroke_fill)

                    target = root / f"cover_{index}_{height}.png"
                    with patch.object(production, "_centered_text", side_effect=checked_text):
                        result = production.apply_overlays(
                            raw, target, PHONE, "cover", index, 1, ITEMS,
                            f"1024x{height}", category_id="truck_rescue",
                        )
                    self.assertEqual([text for text, _ in calls], [f"电话：{PHONE}", *ITEMS])
                    self.assertEqual(result["expected_text"], [f"电话：{PHONE}", *ITEMS, f"联系电话：{PHONE}"])
                    self.assertEqual(result["overlay_style"]["version"], 3)
                    self.assertEqual(result["overlay_style"]["typography_version"], 2)
                    self.assertEqual(result["overlay_style"]["center_phone_region"], plan["center_phone_region"])
                    self.assertEqual(result["overlay_style"]["bottom_service_region"], plan["bottom_service_region"])
                    self.assertEqual(result["overlay_style"]["reference_supplement"], plan["reference_supplement"])
                    self.assertFalse(result["approved"])
                    boxes = [box for _, box in calls]
                    for position, box in enumerate(boxes):
                        x1, y1, x2, y2 = box
                        self.assertTrue(0 <= x1 < x2 <= 1024)
                        self.assertTrue(height * .45 <= y1 < y2 <= height)
                        for other in boxes[position + 1:]:
                            self.assertFalse(min(x2, other[2]) > max(x1, other[0]) and min(y2, other[3]) > max(y1, other[1]))
                    with Image.open(raw) as source, Image.open(target) as rendered:
                        # No new local text over the physical sign or central work area.
                        for region in ((0, 0, 1024, int(height * .45)), (0, int(height * .64), 1024, int(height * .82))):
                            self.assertIsNone(ImageChops.difference(source.crop(region), rendered.crop(region)).getbbox())

    def test_new_cover_rejects_incomplete_words_but_detail_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw.png"
            Image.new("RGB", (1024, 1536), (91, 123, 157)).save(raw)
            with self.assertRaises(production.CategoryPromptError):
                production.apply_overlays(raw, root / "invalid.png", PHONE, "cover", 374, 1, ITEMS[:9], category_id="truck_rescue")
            self.assertFalse((root / "invalid.png").exists())
            # The new planner is never consulted for details, including future groups.
            with patch.object(truck_cover_typography, "cover_plan", side_effect=AssertionError("detail must not use cover plan")):
                result = production.apply_overlays(raw, root / "detail.png", PHONE, "detail", 374, 3, ITEMS, category_id="truck_rescue")
            self.assertEqual(result["overlay_style"], {"version": 1, "name": "detail_panel_grid"})


def write_fixture_sheet(root: Path) -> Path:
    """Local typography evidence only; deliberately not a generated shop image."""
    root.mkdir(parents=True, exist_ok=True)
    raw = root / "neutral_test_background.png"
    Image.new("RGB", (1024, 1536), (116, 126, 133)).save(raw)
    sheet = Image.new("RGB", (2048, 1920), "white")
    for offset, index in enumerate((374, 380, 386, 392, 398)):
        target = root / f"group_{index}_fixture.png"
        production.apply_overlays(raw, target, PHONE, "cover", index, 1, ITEMS, category_id="truck_rescue")
        with Image.open(target) as rendered:
            phone_crop = rendered.crop((0, 650, 1024, 990))
            footer_crop = rendered.crop((0, 1250, 1024, 1536))
            column, row = offset % 2, offset // 2
            sheet.paste(phone_crop, (column * 1024, row * 640))
            sheet.paste(footer_crop, (column * 1024, row * 640 + 345))
    target = root / "contact_sheet.jpg"
    sheet.save(target, quality=95)
    return target


if __name__ == "__main__":
    unittest.main()
