from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from PIL import Image

from generate_group_prompts import cover_prompt_v3
from generate_road_rescue_v3_groups import _cover_record
from tools.category_image_production import (
    ROAD_RESCUE_COVER_V3_FIRST_GROUP,
    apply_overlays,
    build_manifest_entries,
    cover_center_phone_region,
    cover_style_version,
    effective_prompt,
    write_production_files,
)


ROOT = Path(__file__).resolve().parent.parent
PHONE = "15795643941"
SERVICE_ITEMS = [
    "汽车救援", "搭电救援", "拖车服务", "补胎换胎", "送油救援",
    "困境救援", "地库救援", "车辆救援", "高速救援", "城市路救援",
]


class RoadRescueCoverVisualV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = json.loads(
            (ROOT / "projects/road_rescue/cover_scene_library.json").read_text(encoding="utf-8")
        )
        cls.profile = json.loads(
            (ROOT / "projects/road_rescue/cover_visual_profile_v3.json").read_text(encoding="utf-8")
        )

    def test_future_visual_plan_is_structurally_balanced(self) -> None:
        first = self.profile["first_group_index"]
        self.assertEqual(first, 1089)
        scenes = []
        for group_index in range(first, first + 100):
            prompt, scene = cover_prompt_v3(group_index, self.library, self.profile, [PHONE])
            self.assertEqual(scene["cover_template_version"], self.profile["version"])
            self.assertEqual(scene["phones"], [PHONE])
            self.assertNotIn(PHONE, prompt)
            self.assertIn(scene["main_business_word"], prompt)
            self.assertIn(scene["business_line"], prompt)
            self.assertEqual(
                scene["target_mode"], self.profile["target_mode"]["version"]
            )
            self.assertIn("目标模式 realism_dehomogenization_target_v1：", prompt)
            scenes.append(scene)

        used_signatures: set[str] = set()
        scenes = []
        for group_index in range(first, first + 100):
            record, signature = _cover_record(
                group_index, group_index * 7,
                {"id": "height_1408", "width": 1024, "height": 1408},
                {"id": "stacked_equal"}, 1, [PHONE], self.library, used_signatures,
            )
            self.assertEqual(record["cover_variant_signature"], signature)
            self.assertNotIn(signature, used_signatures)
            used_signatures.add(signature)
            scenes.append(record["scene"])
        self.assertEqual(len(used_signatures), 100)
        shot_counts = Counter(scene["visual_shot_id"] for scene in scenes)
        light_counts = Counter(scene["visual_light_id"] for scene in scenes)
        vehicle_counts = Counter(scene["visual_vehicle_presence"] for scene in scenes)
        anchor_counts = Counter(scene["visual_reality_anchor_id"] for scene in scenes)
        self.assertEqual(len(shot_counts), 12)
        self.assertLessEqual(max(shot_counts.values()) - min(shot_counts.values()), 1)
        self.assertEqual(len(light_counts), 7)
        self.assertEqual(set(vehicle_counts), {0, 1, 2, 3})
        self.assertTrue(all(vehicle_counts[index] == 25 for index in range(4)))
        self.assertTrue(all(
            left["visual_shot_id"] != right["visual_shot_id"]
            for left, right in zip(scenes, scenes[1:])
        ))
        self.assertEqual(
            set(anchor_counts),
            {item["id"] for item in self.profile["target_mode"]["reality_anchors"]},
        )
        self.assertTrue(all(
            left["visual_reality_anchor_id"] != right["visual_reality_anchor_id"]
            for left, right in zip(scenes, scenes[1:])
        ))

    def test_scene_selections_are_compatible_and_retry_keeps_primary_axes(self) -> None:
        for index in range(1089, 1189):
            _, scene = cover_prompt_v3(index, self.library, self.profile, [PHONE])
            shot = next(item for item in self.profile["shot_presets"] if item["id"] == scene["visual_shot_id"])
            if shot["bays"] == 1:
                self.assertNotEqual(scene["business_mode"], self.library["business_modes"][3])
                self.assertNotEqual(scene["workshop_activity"], self.library["workshop_activities"][0])
                self.assertNotEqual(scene["foreground"], self.library["foreground_elements"][4])
            if not shot.get("corner"):
                self.assertNotEqual(scene["sign_shape"], self.library["sign_shapes"][4])
            vehicle = scene["visual_vehicle_presence"]
            if vehicle == 3:
                self.assertNotEqual(scene["business_mode"], self.library["business_modes"][0])
            if vehicle == 0:
                self.assertNotEqual(scene["business_mode"], self.library["business_modes"][2])
            for variant in (1, 2, 3):
                _, retried = cover_prompt_v3(index, self.library, self.profile, [PHONE], variant)
                for key in ("visual_shot_id", "visual_light_id", "visual_vehicle_presence", "visual_worker_presentation", "phones"):
                    self.assertEqual(scene[key], retried[key])

    def test_overlay_plan_records_boundary_and_keeps_other_categories_unchanged(self) -> None:
        self.assertEqual(self.profile["first_group_index"], ROAD_RESCUE_COVER_V3_FIRST_GROUP)
        self.assertEqual(cover_style_version("road_rescue", 1088), 8)
        self.assertEqual(cover_style_version("road_rescue", 1089), 10)
        for category in ("pipe_unclogging", "home_appliance_repair", "truck_rescue", "ktv"):
            self.assertEqual(cover_style_version(category, 1089), cover_style_version(category, 1088))
            self.assertEqual(cover_center_phone_region(category, 1089), [0.025, 0.43, 0.975, 0.535])
        with tempfile.TemporaryDirectory() as temporary:
            for start, count, version in ((1088, 1, 8), (1089, 1, 10), (1088, 2, None)):
                _, overlay = write_production_files({
                    "batch_dir": temporary, "category_id": "road_rescue",
                    "group_start": start, "group_count": count,
                    "manifest_entries": [], "service_items": SERVICE_ITEMS,
                }, PHONE)
                data = json.loads(overlay.read_text(encoding="utf-8"))
                self.assertEqual(data["cover_style_version"], version)
                if start + count > 1089:
                    self.assertEqual(data["cover_styles_by_group"]["1089"], {
                        "version": 10, "center_phone_region": [0.025, 0.5, 0.975, 0.6],
                        "bottom_service_region": [0.0, 0.855, 1.0, 1.0],
                        "bottom_service_style_id": "compact-v2__porcelain_red__short_rule",
                    })

    def test_future_only_manifest_and_runtime_phone(self) -> None:
        height = {"id": "height_1408", "width": 1024, "height": 1408}
        layout = {"id": "stacked_equal"}
        legacy, _ = _cover_record(1088, 1, height, layout, 1, [PHONE], self.library, set())
        future, _ = _cover_record(1089, 2, height, layout, 1, [PHONE], self.library, set())
        self.assertEqual(legacy["cover_template_version"], "road_rescue_storefront_mobile_v2")
        self.assertEqual(future["cover_template_version"], "road_rescue_storefront_mobile_v3")
        self.assertNotIn(PHONE, future["prompt"])
        prepared = effective_prompt(future, PHONE)
        self.assertIn(f"号码“{PHONE}”", prepared)
        self.assertIn("百分之五十至六十是后期电话条区域", prepared)
        self.assertNotIn("道路救援封面最高优先级覆盖规则", prepared)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for record, version in ((legacy, 8), (future, 10)):
                record.update(
                    generation_target_id=record["generation_id"],
                    delivery_target_id=f"delivery:{record['group_index']}",
                    target=directory / "cover.png", legacy_target=directory / "legacy.png",
                )
                entry = build_manifest_entries(directory, [record], PHONE, SERVICE_ITEMS, {
                    "model": "local-test-only", "quality": "medium", "api_size": "1024x1536",
                })[0]
                self.assertEqual(entry["cover_style_version"], version)
                self.assertEqual(entry["target_mode"], {
                    "enabled": True,
                    "version": "realism_dehomogenization_target_v1",
                })
                if version == 10:
                    self.assertEqual(entry["cover_center_phone_region"], [0.025, 0.5, 0.975, 0.6])
                else:
                    self.assertNotIn("cover_center_phone_region", entry)

    def test_future_phone_strip_moves_below_signboard_area(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            raw = directory / "raw.png"
            Image.new("RGB", (1024, 1536), (120, 130, 140)).save(raw)
            results = {}
            for group_index in (989, 1089):
                target = directory / f"cover_{group_index}.png"
                validation = apply_overlays(
                    raw, target, PHONE, "cover", group_index, 1, SERVICE_ITEMS,
                    category_id="road_rescue",
                )
                self.assertEqual(validation["overlay_style"]["version"], 10 if group_index == 1089 else 8)
                if group_index == 1089:
                    self.assertEqual(validation["overlay_style"]["center_phone_region"], [0.025, 0.5, 0.975, 0.6])
                with Image.open(target) as image:
                    results[group_index] = (
                        image.convert("RGB").getpixel((30, int(1536 * 0.45))),
                        image.convert("RGB").getpixel((30, int(1536 * 0.55))),
                    )
            background = (120, 130, 140)
            self.assertNotEqual(results[989][0], background)
            self.assertEqual(results[1089][0], background)
            self.assertNotEqual(results[1089][1], background)


if __name__ == "__main__":
    unittest.main()
