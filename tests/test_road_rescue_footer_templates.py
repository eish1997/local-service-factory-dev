from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from tools import category_image_production as production


ITEMS = [
    "汽车救援", "搭电救援", "拖车服务", "补胎换胎", "送油救援",
    "困境救援", "地库救援", "车辆救援", "高速救援", "城市路救援",
]


class RoadRescueFooterTemplateTests(unittest.TestCase):
    def test_rotation_is_balanced_reproducible_and_has_no_adjacent_layout_repeat(self) -> None:
        styles = [production.road_rescue_bottom_service_style(index) for index in range(1090, 1234)]
        self.assertEqual(len({style["style_id"] for style in styles}), 144)
        self.assertEqual(set(Counter(style["layout"] for style in styles).values()), {18})
        self.assertEqual(len({style["layout"] for style in styles}), 8)
        self.assertEqual(len({style["name"] for style in styles}), 6)
        self.assertEqual(len({style["accent"] for style in styles}), 3)
        for start in range(0, 144, 8):
            self.assertEqual(len({style["layout"] for style in styles[start:start + 8]}), 8)
        for index in range(1090, 1380):
            current = production.road_rescue_bottom_service_style(index)
            self.assertEqual(current, production.road_rescue_bottom_service_style(index))
            self.assertNotEqual(current["layout"], production.road_rescue_bottom_service_style(index + 1)["layout"])
        counts = Counter(style["layout"] for style in styles[:50])
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_all_templates_fit_words_and_render_at_all_production_heights(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for height in (1408, 1472, 1536):
                source = root / "raw.png"
                background = (91, 123, 157)
                Image.new("RGB", (1024, height), background).save(source)
                for offset in range(8):
                    index = 1090 + offset
                    style = production.road_rescue_bottom_service_style(index)
                    boxes = production._cover_service_boxes(1024, height, style["layout"], 10)
                    self.assertEqual(len(boxes), 10)
                    region = production.road_rescue_bottom_service_region(index)
                    draw = ImageDraw.Draw(Image.new("RGB", (1024, height)))
                    for position, (item, box) in enumerate(zip(ITEMS, boxes)):
                        x1, y1, x2, y2 = box
                        self.assertTrue(0 <= x1 < x2 <= 1024)
                        self.assertTrue(height * region[1] <= y1 < y2 <= height)
                        for other in boxes[position + 1:]:
                            self.assertFalse(min(x2, other[2]) > max(x1, other[0]) and min(y2, other[3]) > max(y1, other[1]))
                        font = production._fit_font(draw, item, int((x2 - x1) * .91), int(1024 * .034), min_size=15)
                        self.assertGreaterEqual(font.size, 30)
                        bounds = draw.textbbox((0, 0), item, font=font)
                        self.assertLessEqual(bounds[2] - bounds[0], (x2 - x1) * .91)
                        self.assertLess(bounds[3] - bounds[1], y2 - y1)
                    target = root / f"cover_{index}.png"
                    result = production.apply_overlays(source, target, "15795643941", "cover", index, 1, ITEMS, f"1024x{height}", category_id="road_rescue")
                    self.assertEqual(result["expected_text"][1:11], ITEMS)
                    self.assertEqual(result["overlay_style"]["version"], 11)
                    self.assertEqual(result["overlay_style"]["bottom_service_style"]["version"], 3)
                    self.assertEqual(result["overlay_style"]["bottom_service_region"], region)
                    with Image.open(target) as rendered:
                        self.assertEqual(rendered.convert("RGB").getpixel((512, int(height * .80))), background)
                        self.assertEqual(rendered.convert("RGB").getpixel((1023, height - 1)), style["background"][:3])

    def test_version_boundary_and_per_group_plan_regions(self) -> None:
        self.assertEqual(production.cover_style_version("road_rescue", 1088), 8)
        self.assertEqual(production.cover_style_version("road_rescue", 1089), 10)
        self.assertEqual(production.cover_style_version("road_rescue", 1090), 11)
        self.assertEqual(production.road_rescue_bottom_service_style(1089)["layout"], "compact_five_by_two")
        for category in ("pipe_unclogging", "home_appliance_repair", "truck_rescue", "ktv"):
            self.assertEqual(production.cover_style_version(category, 1089), production.cover_style_version(category, 1090))
        with tempfile.TemporaryDirectory() as temporary:
            for start, count in ((1089, 2), (1090, 8), (1090, 1)):
                _, path = production.write_production_files({
                    "batch_dir": temporary, "category_id": "road_rescue",
                    "group_start": start, "group_count": count,
                    "manifest_entries": [], "service_items": ITEMS,
                }, "15795643941")
                payload = json.loads(path.read_text(encoding="utf-8"))
                for index in range(start, start + count):
                    self.assertEqual(payload["cover_styles_by_group"][str(index)]["bottom_service_region"], production.road_rescue_bottom_service_region(index))
                if count > 1:
                    self.assertIsNone(payload["cover_bottom_service_region"])
                else:
                    self.assertEqual(payload["cover_bottom_service_region"], [0, .83, 1, 1])


if __name__ == "__main__":
    unittest.main()
