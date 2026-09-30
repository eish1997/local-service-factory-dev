"""Local-only future scene contracts; none is evidence of visual uniqueness."""
from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter
from unittest import mock

import generate_truck_rescue_groups as groups
from tools import truck_scene_diversity_v3 as scene


# Captured before changing the generator, 2026-09-27. Contains all four result
# lists from _build_rows(1,273,1): prompts, deliveries, group rows and registry.
LEGACY_GENERATOR_SHA256 = "33fd36b6442366956059573b1401f50508ab0fffc581bc7a5c03ba74bc29e8a4"
LEGACY_ROWS_SHA256 = "0cba872930782d0b94f01c7e019a0e051c47232511a4739c462ba4fbdcc94ec0"


class TruckSceneDiversityV3Tests(unittest.TestCase):
    def config(self):
        return json.loads(groups.CATEGORY_CONFIG_PATH.read_text(encoding="utf-8-sig"))

    def test_legacy_1_to_273_rows_match_prechange_baseline(self):
        result = groups._build_rows(1, 273, 1, self.config())
        actual = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(actual, LEGACY_ROWS_SHA256)

    def test_epoch_guard_and_determinism(self):
        with self.assertRaises(ValueError):
            scene.detail_variant(scene.ROLES[0], 273)
        with self.assertRaises(ValueError):
            scene.cover_variant(groups._cover_library(), 273)
        self.assertEqual(scene.detail_variant(scene.ROLES[0], 274), scene.detail_variant(scene.ROLES[0], 274))

    def test_600_detail_prompts_and_major_scenes_unique_within_role(self):
        prompts = set()
        for role in scene.ROLES:
            variants = [scene.detail_variant(role, index) for index in range(274, 374)]
            self.assertEqual(len({v["major_signature"] for v in variants}), 100)
            for left, right in zip(variants, variants[1:]):
                self.assertNotEqual(left["camera_id"], right["camera_id"])
                self.assertNotEqual(left["event_id"], right["event_id"])
            cameras = Counter(v["camera_id"] for v in variants)
            self.assertEqual(len(cameras), 6)
            self.assertLessEqual(max(cameras.values()) - min(cameras.values()), 1)
            self.assertEqual(len({v["event_id"] for v in variants}), 4)
            self.assertEqual(len({v["location_id"] for v in variants}), 5)
            self.assertEqual(len({v["light_id"] for v in variants}), 7)
            for v in variants:
                prompts.add(scene.detail_positive_prompt(role, groups.ROLE_IDS[role], v, "detail"))
        self.assertEqual(len(prompts), 600)

    def test_100_covers_have_decoupled_major_axes(self):
        variants = [scene.cover_variant(groups._cover_library(), i) for i in range(274, 374)]
        self.assertEqual(len({v["major_signature"] for v in variants}), 100)
        self.assertEqual(len({v["camera_id"] for v in variants}), 12)
        self.assertEqual(len({v["event_id"] for v in variants}), 8)
        self.assertGreaterEqual(len({(v["camera_id"], v["location_id"]) for v in variants}), 60)
        for left, right in zip(variants, variants[1:]):
            self.assertNotEqual(left["camera_id"], right["camera_id"])
            self.assertNotEqual(left["event_id"], right["event_id"])

    def test_event_mechanics_are_bound_and_auditable(self):
        for role in scene.ROLES:
            for group_index in range(274, 298):
                variant = scene.detail_variant(role, group_index)
                for key in ("scene_version", "event_id", "camera_id", "light_id", "major_signature", "vehicle", "powertrain", "brake_system", "action", "tools"):
                    self.assertTrue(variant[key], key)
                self.assertEqual(variant["scene_version"], scene.SCENE_VERSION)
                event = next(item for item in scene.EVENTS[role] if item[0] == variant["event_id"])
                self.assertEqual((variant["vehicle"], variant["powertrain"], variant["brake_system"], variant["action"], variant["tools"]), event[1:])
                if role == "货车刹车故障" and variant["brake_system"] == "hydraulic":
                    self.assertNotIn("压力表", variant["tools"])
                    self.assertNotIn("检漏液", variant["tools"])
                if role == "卡车搭电":
                    self.assertIn("额定电压", variant["tools"])
        torque = next(x for x in scene.EVENTS["货车换轮胎"] if x[0] == "wheel_torque")
        self.assertIn("着地", torque[1])
        self.assertNotIn("千斤顶", torque[-1])
        loosen = next(x for x in scene.EVENTS["货车换轮胎"] if x[0] == "wheel_loosen")
        self.assertIn("全部车轮仍着地", loosen[4])
        dual = next(x for x in scene.EVENTS["货车爆胎救援"] if x[0] == "blowout_dual")
        self.assertIn("内侧轮胎", dual[4])
        self.assertNotIn("内胎", dual[4])

    def test_generator_routes_only_future_rows_and_keeps_700_500_shape(self):
        # Signage has an independent bounded pool. Test the scene integration
        # without extending its live names or any on-disk manifests.
        with mock.patch.object(groups, "signage_variant", return_value={}):
            generated, deliveries, _, _ = groups._build_rows(274, 100, 1912, self.config())
        self.assertEqual(len(generated), 700)
        self.assertEqual(len(deliveries), 500)
        self.assertEqual(len({r["positive_prompt"] for r in generated}), 700)
        self.assertTrue(all(r["scene"]["scene_version"] == scene.SCENE_VERSION for r in generated))
        self.assertTrue(all(r["scene"]["major_signature"] for r in generated))
        self.assertTrue(all(not r["api_called"] for r in generated))
        legacy = groups._build_rows(1, 273, 1, self.config())[0]
        old_prompts = {r["positive_prompt"] for r in legacy}
        self.assertFalse(any(r["positive_prompt"] in old_prompts for r in generated))


if __name__ == "__main__":
    unittest.main()
