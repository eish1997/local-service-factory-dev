"""Future-only reference learning; local contracts are not visual approval."""
from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter

import generate_truck_rescue_groups as groups
from tools import truck_rescue_signage as signage
from tools import truck_scene_diversity_v3 as scene


# Captured in memory before the 374 learning change, including prompts, delivery
# rows, group rows and registry rows. No production manifest is read or written.
HISTORICAL_ROWS_SHA256 = "cc3b90bbb13bf4202107d740634a9158c805af9d6cd3c804aaa8e93d52c2696c"
HISTORICAL_NAMES_SHA256 = "619ff2e51dc1dca36d2cce616379d225e8c09db2b9147088d4bf86d7f6c23b59"
HISTORICAL_SIGNAGE_SHA256 = "1b3eed8b638b9bce8a5341309b6dabe3bc6475a21188f245252a2cef0d14e812"


def digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


class TruckReferenceLearning374Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(groups.CATEGORY_CONFIG_PATH.read_text(encoding="utf-8-sig"))
        cls.library = groups._cover_library()
        cls.names = json.loads(signage.DEFAULT_LIBRARY_PATH.read_text(encoding="utf-8-sig"))["brand_name_candidates"]

    def test_all_historical_rows_1_to_373_are_identical(self):
        self.assertEqual(digest(groups._build_rows(1, 373, 1, self.config)), HISTORICAL_ROWS_SHA256)

    def test_historical_names_and_sign_mapping_are_identical(self):
        self.assertEqual(digest(self.names[:280]), HISTORICAL_NAMES_SHA256)
        self.assertEqual(digest([signage.signage_variant(i) for i in range(94, 374)]), HISTORICAL_SIGNAGE_SHA256)

    def test_thirty_ordinary_names_are_unique_distributed_and_not_name_style(self):
        expected = "永兴 广源 诚信 兴旺 利民 富强 华丰 新生 永胜 正和 福满 新辉 振业 永发 同心 立新 惠民 众诚 万家 久安 昌盛 百顺 和美 友好 惠丰 荣安 德盛 合力 平顺 聚力".split()
        additions = self.names[280:310]
        self.assertEqual([row["name"] for row in additions], expected)
        self.assertEqual(len(set(expected)), 30)
        self.assertFalse(set(expected) & {row["name"] for row in self.names[:280]})
        self.assertFalse(set(expected) & signage.FORBIDDEN_BRAND_NAMES)
        self.assertLessEqual(max(Counter("".join(expected)).values()), 4)
        self.assertFalse(any(set(name) & set("驰捷擎护") for name in expected))
        self.assertFalse(any(name.startswith(("老", "小", "阿")) for name in expected))
        self.assertEqual(Counter(row["suffix"] for row in additions), Counter({suffix: 6 for suffix in signage.ALLOWED_INDUSTRY_SUFFIXES}))
        for i, name in enumerate(expected, 374):
            self.assertEqual(signage.signage_variant(i)["brand_name"], name)
        with self.assertRaisesRegex(signage.TruckRescueSignageError, "candidates exhausted"):
            signage.signage_variant(signage.NAMING_EPOCH_GROUP + len(self.names))

    def test_five_composition_choices_are_balanced_not_one_stack(self):
        variants = [scene.cover_variant(self.library, i) for i in range(374, 404)]
        self.assertEqual(Counter(row["composition_family"] for row in variants), Counter({row[0]: 6 for row in scene.LEARNED_COMPOSITIONS}))
        self.assertEqual(len({row["camera_id"] for row in variants}), 12)
        self.assertEqual(len({row["major_signature"] for row in variants}), 30)
        self.assertEqual(len({row["event_id"] for row in variants}), 8)
        self.assertNotIn("reference_learning_version", scene.cover_variant(self.library, 373))
        for left, right in zip([scene.cover_variant(self.library, 373)] + variants, variants):
            self.assertNotEqual(left["camera_id"], right["camera_id"])
            self.assertNotEqual(left["event_id"], right["event_id"])
        for left, right in zip(variants, variants[1:]):
            self.assertNotEqual(left["composition_family"], right["composition_family"])

    def test_work_details_are_bound_to_the_single_business_event(self):
        event_map = {row[0]: row for row in scene.COVER_EVENTS}
        for i in range(374, 404):
            variant = scene.cover_variant(self.library, i)
            self.assertEqual(variant, scene.cover_variant(self.library, i))
            self.assertEqual(variant["reference_learning_version"], scene.REFERENCE_LEARNING_VERSION)
            self.assertEqual(variant["work_detail_id"], variant["event_id"] + "_placement")
            self.assertEqual(variant["work_detail"], scene.COVER_WORK_DETAILS[variant["event_id"]])
            self.assertEqual(variant["front_activity"], event_map[variant["event_id"]][1])
            self.assertEqual(variant["shop_state"], event_map[variant["event_id"]][2])
            self.assertEqual(variant["local_text_learning_policy"], "optional_supplement_not_global_template")

    def test_future_prompts_use_concrete_choices_and_keep_raw_photo_contract(self):
        for i in range(374, 404):
            variant = groups._cover_variant(self.library, i)
            prompt = groups._cover_positive_prompt(variant)
            self.assertIn(variant["composition_emphasis"], prompt)
            self.assertIn(variant["work_detail"], prompt)
            self.assertIn(variant["full_store_name"], prompt)
            self.assertIn("不要求每图同时呈现门头、车间、前景工人三层", prompt)
            self.assertIn("原图绝不提前生成中部电话条", prompt)
            self.assertNotIn("至少两种环境层次", prompt)
            self.assertNotIn("13407128962", prompt)  # confirmed data is injected later

    def test_new_group_rows_keep_seven_raw_five_delivery_and_six_roles(self):
        generation, deliveries, group_rows, registry = groups._build_rows(374, 30, 2612, self.config)
        self.assertEqual([len(rows) for rows in (generation, deliveries, group_rows, registry)], [210, 150, 30, 30])
        self.assertEqual(len({row["positive_prompt"] for row in generation}), 210)
        self.assertTrue(all(not row["api_called"] for row in generation))
        covers = [row for row in generation if row["generation_kind"] == "cover"]
        self.assertEqual(len(covers), 30)
        for row in covers:
            self.assertEqual(row["scene"]["reference_learning_version"], scene.REFERENCE_LEARNING_VERSION)
            self.assertEqual(row["cover_variant"]["composition_family"], row["scene"]["composition_family"])
        for row in group_rows:
            self.assertEqual(len(set(row["service_roles"])), 6)
            self.assertEqual(row["total_images"], 5)
            self.assertEqual(row["generation_unit_count"], 7)


if __name__ == "__main__":
    unittest.main()
