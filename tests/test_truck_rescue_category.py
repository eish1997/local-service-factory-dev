from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import generate_truck_rescue_groups as groups
import factory
from tools import category_image_production, truck_rescue_signage


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "categories" / "truck_rescue.json"
PROJECT_PATH = ROOT / "projects" / "truck_rescue" / "project.json"

EXPECTED_ROLES = (
    "货车没油救援",
    "货车爆胎救援",
    "货车换轮胎",
    "货车发动机故障",
    "卡车搭电",
    "货车刹车故障",
)

EXPECTED_SERVICE_WORDS = (
    "货车救援",
    "货车维修",
    "应急送油",
    "爆胎救援",
    "货车补胎",
    "货车换胎",
    "发动机检修",
    "搭电启动",
    "刹车检修",
    "制动检修",
)


class TruckRescueCategoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        cls.project = json.loads(PROJECT_PATH.read_text(encoding="utf-8-sig"))

    def test_category_has_exact_six_roles_ten_service_words_and_v3_shape(self) -> None:
        structure = self.config["image_group_structure"]

        self.assertEqual(self.config["category_id"], "truck_rescue")
        self.assertEqual(tuple(self.config["scene_types"]), EXPECTED_ROLES)
        self.assertEqual(tuple(structure["detail_roles"]), EXPECTED_ROLES)
        self.assertEqual(tuple(structure["service_role_pool"]), EXPECTED_ROLES)
        self.assertEqual(tuple(groups.ROLE_IDS), EXPECTED_ROLES)
        self.assertEqual(tuple(self.config["service_items"]), EXPECTED_SERVICE_WORDS)
        self.assertEqual(tuple(self.config["service_buttons"]), EXPECTED_SERVICE_WORDS)
        self.assertEqual(len(set(self.config["service_buttons"])), 10)

        self.assertEqual(
            structure["structure_version"],
            "truck_rescue_v3_1cover_1triptych_3details",
        )
        self.assertEqual(structure["generation_mode"], "independent_triptych_panels")
        self.assertEqual(structure["cover_count"], 1)
        self.assertEqual(structure["triptych_count"], 1)
        self.assertEqual(structure["triptych_panel_count"], 3)
        self.assertEqual(structure["detail_count"], 3)
        self.assertEqual(structure["total_per_group"], 5)
        self.assertEqual(structure["delivery_unit_count"], 5)
        self.assertEqual(structure["generation_unit_count"], 7)
        self.assertEqual(structure["service_roles_per_group"], 6)
        self.assertEqual(
            structure["generation_roles"],
            ["cover", "triptych_panel", "triptych_panel", "triptych_panel", "detail", "detail", "detail"],
        )
        self.assertEqual(
            structure["delivery_roles"],
            ["cover", "triptych", "detail", "detail", "detail"],
        )

    def test_project_matches_category_shape_and_keeps_three_group_sample_gate(self) -> None:
        content_group = self.project["content_group"]
        structure = self.config["image_group_structure"]

        self.assertEqual(content_group["structure_version"], structure["structure_version"])
        self.assertEqual(content_group["generation_mode"], structure["generation_mode"])
        self.assertEqual(content_group["total_images"], 5)
        self.assertEqual(content_group["delivery_unit_count"], 5)
        self.assertEqual(content_group["generation_unit_count"], 7)
        self.assertEqual(content_group["service_roles_per_group"], 6)
        self.assertEqual(tuple(content_group["service_role_pool"]), EXPECTED_ROLES)
        self.assertEqual(self.project["inventory_policy"]["sample_gate_groups"], 3)
        self.assertFalse(self.project["required_fields"]["contact_phones"]["confirmed"])
        self.assertEqual(self.project["required_fields"]["contact_phones"]["values"], [])
        self.assertTrue(self.project["required_fields"]["service_words"]["confirmed"])
        self.assertEqual(
            tuple(self.project["required_fields"]["service_words"]["values"]),
            EXPECTED_SERVICE_WORDS,
        )
        self.assertEqual(
            self.config["service_buttons_status"],
            "user_confirmed_for_visible_text_generation",
        )
        self.assertTrue(self.project["references"]["cover"]["approved_style"])
        self.assertEqual(
            self.project["references"]["cover"]["sample_approval_evidence"],
            "projects/truck_rescue/groups/sample_cover_approval.json",
        )

    def test_role_variants_use_explicit_truck_condition_fields(self) -> None:
        self.assertEqual(tuple(groups.ROLE_VARIANTS), EXPECTED_ROLES)
        all_powertrains: set[str] = set()
        all_brake_systems: set[str] = set()

        for role, variants in groups.ROLE_VARIANTS.items():
            with self.subTest(role=role):
                self.assertEqual(len(variants), 3)
                for variant in variants:
                    self.assertEqual(
                        set(variant),
                        {"vehicle", "powertrain", "brake_system", "location", "action", "tools"},
                    )
                    self.assertTrue(
                        any(
                            term in variant["vehicle"]
                            for term in ("货车", "卡车", "牵引车", "货运皮卡")
                        )
                    )
                    self.assertFalse(
                        any(term in variant["vehicle"] for term in ("轿车", "SUV", "MPV", "乘用车"))
                    )
                    self.assertIn(variant["powertrain"], {"combustion", "unspecified"})
                    self.assertIn(variant["brake_system"], {"air", "hydraulic", "unspecified"})
                    all_powertrains.add(variant["powertrain"])
                    all_brake_systems.add(variant["brake_system"])

        self.assertTrue(
            all(
                variant["powertrain"] == "combustion"
                for variant in groups.ROLE_VARIANTS["货车没油救援"]
            )
        )
        self.assertEqual(
            {variant["brake_system"] for variant in groups.ROLE_VARIANTS["货车刹车故障"]},
            {"air", "hydraulic"},
        )
        self.assertIn("combustion", all_powertrains)
        self.assertIn("air", all_brake_systems)
        self.assertIn("hydraulic", all_brake_systems)

        all_variants = [
            variant for variants in groups.ROLE_VARIANTS.values() for variant in variants
        ]
        self.assertEqual(len(all_variants), 18)
        self.assertEqual(
            sum(
                any(term in variant["vehicle"] for term in ("重型", "重卡", "牵引车", "半挂"))
                for variant in all_variants
            ),
            8,
        )
        pickup_variants = [
            variant for variant in all_variants if "大型全尺寸货运皮卡" in variant["vehicle"]
        ]
        self.assertEqual(len(pickup_variants), 1)
        self.assertEqual(pickup_variants[0]["brake_system"], "hydraulic")
        self.assertIn("额定电压", pickup_variants[0]["action"])

        vehicle_mix = self.config["vehicle_mix_policy"]
        self.assertEqual(vehicle_mix["heavy_truck_weight"], "slightly_increased")
        self.assertEqual(vehicle_mix["large_cargo_pickup_frequency"], "low")
        self.assertIn("大型全尺寸货运皮卡", vehicle_mix["allowed_large_pickups"])
        self.assertIn("普通家用小皮卡", vehicle_mix["forbidden_pickups"])
        self.assertNotIn("皮卡", self.config["negative_prompt"])

        semantics = self.config["conditional_semantics"]
        self.assertIn("diesel", semantics)
        self.assertIn("voltage_24v", semantics)
        self.assertIn("air_brake", semantics)
        self.assertIn("spare_tire", semantics)
        self.assertIn("tire_patch", semantics)

    def test_future_cover_vehicle_mix_preserves_approved_three_groups(self) -> None:
        library = groups._cover_library()
        manifest_path = ROOT / "projects" / "truck_rescue" / "groups" / "generation_manifest.jsonl"
        active_cover_activities = []
        for line in manifest_path.read_text(encoding="utf-8-sig").splitlines():
            row = json.loads(line)
            if row["generation_kind"] == "cover" and row["group_index"] <= 3:
                active_cover_activities.append(row["scene"]["front_activity"])

        regenerated_cover_activities = [
            groups._cover_variant(library, group_index)["front_activity"]
            for group_index in range(1, 4)
        ]
        self.assertEqual(regenerated_cover_activities, active_cover_activities)

        future_cover_activities = [
            groups._cover_variant(library, group_index)["front_activity"]
            for group_index in range(4, 10)
        ]
        self.assertEqual(
            sum("大型全尺寸货运皮卡" in activity for activity in future_cover_activities),
            1,
        )
        self.assertEqual(
            sum(
                any(
                    term in activity
                    for term in ("重型牵引卡车", "重型自卸货车")
                )
                for activity in future_cover_activities
            ),
            2,
        )

    def test_cover_effective_prompt_injects_only_the_confirmed_phone(self) -> None:
        phone = "13812345678"
        prompt = category_image_production.effective_prompt(
            {
                "category_id": "truck_rescue",
                "group_index": 94,
                "generation_kind": "cover",
                "prompt": "写实中国货车救援维修门店，门头预留联系信息区。",
            },
            phone,
        )
        self.assertIn("货车救援维修封面最高优先级覆盖规则", prompt)
        self.assertIn("驰护货车维修救援", prompt)
        self.assertIn("字高比例约0.95至1.05", prompt)
        self.assertNotIn("最大或最醒目", prompt)
        self.assertIn(f"号码必须清楚准确写成“{phone}”", prompt)
        self.assertEqual(prompt.count(phone), 1)

    def test_cover_effective_prompt_preserves_400_hotline_hyphens(self) -> None:
        phone = "400-677-1311"
        persisted = truck_rescue_signage.signage_variant(174)
        prompt = category_image_production.effective_prompt(
            {
                "category_id": "truck_rescue",
                "group_index": 174,
                "generation_kind": "cover",
                "cover_variant": persisted,
                "prompt": "写实中国货车救援维修门店，门头预留联系信息区。",
            },
            phone,
        )
        self.assertIn(f"号码必须清楚准确写成“{phone}”", prompt)
        self.assertEqual(prompt.count(phone), 1)

    def test_cover_overlay_renders_400_hotline_and_records_exact_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "raw.png"
            target = root / "cover.png"
            Image.new("RGB", (1024, 1536), (90, 105, 115)).save(source)
            validation = category_image_production.apply_overlays(
                source,
                target,
                "400-677-1311",
                "cover",
                174,
                1,
                list(EXPECTED_SERVICE_WORDS),
                category_id="truck_rescue",
            )
            self.assertTrue(target.is_file())
            self.assertIn("电话：400-677-1311", validation["expected_text"])
            self.assertIn("联系电话：400-677-1311", validation["expected_text"])

    def test_groups_before_94_keep_legacy_signage_semantics(self) -> None:
        prompt = category_image_production.effective_prompt(
            {
                "category_id": "truck_rescue",
                "group_index": 93,
                "generation_kind": "cover",
                "prompt": (
                    "写实中国货车救援维修门店。"
                    "主招牌最大业务词必须清楚准确写成“货车救援维修”，门头预留联系信息区。"
                ),
            },
            "13812345678",
        )
        self.assertNotIn("货车门头命名最高优先级覆盖规则", prompt)
        self.assertNotIn("驰护货车维修救援", prompt)
        self.assertIn(
            "主招牌最大业务词必须清楚准确写成“货车救援维修”",
            prompt,
        )

    def test_group_95_uses_persisted_name_even_if_library_selector_changes(self) -> None:
        persisted = truck_rescue_signage.signage_variant(95)
        legacy_hierarchy = (
            f"本组实体门头完整主名称只能清楚准确写成“{persisted['full_store_name']}”，"
            f"不得出现第二店名；其中两字寓意字号“{persisted['brand_name']}”最大或最醒目，"
            f"含义为“{persisted['brand_meaning']}”，行业尾缀“{persisted['industry_suffix']}”次大。"
            "信息排版采用：左侧约三成板面突出两字字号，右侧约七成排行业尾缀与确认电话，"
            "服务小字沿下沿横向排列，不做悬浮字幕。"
        )
        record = {
            "category_id": "truck_rescue",
            "group_index": 95,
            "generation_kind": "cover",
            "cover_variant": persisted,
            "prompt": "写实中国货车救援维修门店，门头预留联系信息区。" + legacy_hierarchy,
        }
        with patch.object(
            truck_rescue_signage,
            "signage_variant",
            side_effect=AssertionError("persisted group must not recompute signage"),
        ):
            prompt = category_image_production.effective_prompt(
                record,
                "13812345678",
            )
        self.assertIn(persisted["full_store_name"], prompt)
        self.assertIn("字高比例约0.95至1.05", prompt)
        self.assertNotIn("最大或最醒目", prompt)
        self.assertNotIn("左侧约三成板面突出两字字号", prompt)
        self.assertEqual(prompt.count("13812345678"), 1)

    def test_signage_override_keeps_brand_root_at_normal_balanced_size(self) -> None:
        text = truck_rescue_signage.signage_override_text(
            truck_rescue_signage.signage_variant(94)
        )
        self.assertIn("字高比例约0.95至1.05", text)
        self.assertIn("完整主名称应作为一个均衡整体", text)
        self.assertNotIn("最大或最醒目", text)
        self.assertNotIn("行业尾缀次大", text)

    def test_project_tuning_rule_rejects_a_group_specific_full_name(self) -> None:
        with self.assertRaisesRegex(
            category_image_production.CategoryPromptError,
            "不得固化某一组完整店名",
        ):
            category_image_production._validate_project_tuning_note(
                "truck_rescue",
                "样片使用驰护货车维修救援，其他组沿用同样规则。",
            )

    def test_approved_truck_tuning_rule_does_not_leak_group_94_name(self) -> None:
        batch_dir = (
            ROOT
            / "prompts"
            / "category_batches"
            / "truck_rescue"
            / "batch_v3_active"
        )
        record = category_image_production.record_targets(
            batch_dir,
            category_image_production.selected_records(
                batch_dir,
                95,
                1,
                "truck_rescue",
            ),
            ROOT / "output" / "truck_rescue",
            "truck_rescue",
        )[0]
        prompt = category_image_production.effective_prompt(
            record,
            "13812345678",
        )
        self.assertIn("捷擎重卡维修救援", prompt)
        self.assertNotIn("驰护货车维修救援", prompt)
        self.assertIn("项目已批准的长期门头规则", prompt)

    def test_group_95_missing_persisted_signage_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            truck_rescue_signage.TruckRescueSignageError,
            "must use persisted signage",
        ):
            category_image_production.effective_prompt(
                {
                    "category_id": "truck_rescue",
                    "group_index": 95,
                    "generation_kind": "cover",
                    "prompt": "写实中国货车救援维修门店，门头预留联系信息区。",
                },
                "13812345678",
            )

    def test_group_94_production_metadata_backfills_and_cleans_legacy_signage(self) -> None:
        batch_dir = (
            ROOT
            / "prompts"
            / "category_batches"
            / "truck_rescue"
            / "batch_v3_active"
        )
        records = category_image_production.selected_records(
            batch_dir,
            94,
            1,
            "truck_rescue",
        )
        record = category_image_production.record_targets(
            batch_dir,
            records,
            ROOT / "output" / "truck_rescue",
            "truck_rescue",
        )[0]
        entry = category_image_production.build_manifest_entries(
            batch_dir,
            [record],
            "13812345678",
            list(EXPECTED_SERVICE_WORDS),
            {
                "model": "gpt-image-2",
                "quality": "medium",
                "api_size": "1024x1536",
            },
        )[0]
        self.assertEqual(
            entry["cover_variant"]["full_store_name"],
            "驰护货车维修救援",
        )
        self.assertNotIn(
            "货车救援维修主字",
            entry["cover_variant"]["signboard_variant"],
        )
        self.assertIn(
            "完整主名称实体字",
            entry["cover_variant"]["signboard_variant"],
        )

    def test_eighty_meaningful_signboard_names_are_unique_and_deterministic(self) -> None:
        variants = [
            truck_rescue_signage.signage_variant(group_index)
            for group_index in range(94, 174)
        ]
        self.assertEqual(len(variants), 80)
        self.assertEqual(variants[0]["full_store_name"], "驰护货车维修救援")
        self.assertEqual(variants[50]["full_store_name"], "承衡货车维修救援")
        self.assertEqual(variants[-1]["full_store_name"], "稳拓货车救援维修")
        self.assertEqual(len({item["brand_name"] for item in variants}), 80)
        self.assertEqual(len({item["full_store_name"] for item in variants}), 80)
        self.assertTrue(
            all(
                item["industry_suffix"]
                in truck_rescue_signage.ALLOWED_INDUSTRY_SUFFIXES
                for item in variants
            )
        )
        self.assertFalse(
            any(
                item["brand_name"] in truck_rescue_signage.FORBIDDEN_BRAND_NAMES
                for item in variants
            )
        )
        library = groups._cover_library()
        cover_variants = [
            groups._cover_variant(library, group_index)
            for group_index in range(94, 144)
        ]
        self.assertEqual(
            len({item["camera_composition"] for item in cover_variants}),
            len(library["camera_compositions"]),
        )
        self.assertEqual(
            len({item["signboard_variant"] for item in cover_variants}),
            len(library["signboard_variants"]),
        )

    def test_groups_94_to_273_have_180_unique_names_without_wraparound(self) -> None:
        variants = [
            truck_rescue_signage.signage_variant(group_index)
            for group_index in range(94, 274)
        ]
        self.assertEqual(len(variants), 180)
        self.assertEqual(variants[80]["full_store_name"], "锐应货车维修救援")
        self.assertEqual(variants[129]["full_store_name"], "捷应货车救援维修")
        self.assertEqual(variants[130]["full_store_name"], "速安货车维修救援")
        self.assertEqual(variants[-1]["full_store_name"], "路畅货车救援维修")
        self.assertEqual(len({item["brand_name"] for item in variants}), 180)
        self.assertEqual(len({item["full_store_name"] for item in variants}), 180)
        with self.assertRaisesRegex(
            truck_rescue_signage.TruckRescueSignageError,
            "candidates exhausted",
        ):
            first_unavailable = truck_rescue_signage.NAMING_EPOCH_GROUP + len(
                truck_rescue_signage.load_signage_library()["brand_name_candidates"]
            )
            truck_rescue_signage.signage_variant(first_unavailable)

    def test_triptych_all_scope_can_be_authorized_for_full_batch_review(self) -> None:
        factory._category_require_executable_scope(
            "all",
            "independent_triptych_panels",
        )
        factory._category_require_executable_scope(
            "covers",
            "independent_triptych_panels",
        )
        factory._category_require_executable_scope(
            "details",
            "independent_triptych_panels",
        )
        factory._category_require_executable_scope(
            "all",
            "independent_delivery_images",
        )

    def test_cover_effective_prompt_rejects_another_phone(self) -> None:
        with self.assertRaises(category_image_production.CategoryPromptError):
            category_image_production.effective_prompt(
                {
                    "category_id": "truck_rescue",
                    "generation_kind": "cover",
                    "prompt": "写实货车救援维修门店，门头电话13800138000。",
                },
                "13812345678",
            )

    def test_single_group_signage_tuning_draft_is_isolated_to_bound_cover(self) -> None:
        draft = {
            "project_id": "truck_rescue",
            "role": "cover",
            "dimension": "店名与业务文字",
            "action": "add",
            "note": "完整主名称写成驰护货车维修救援，不再使用第二店名。",
            "status": "active",
        }
        environment = {
            category_image_production.TUNING_SAMPLE_PROJECT_ENV: "truck_rescue",
            category_image_production.TUNING_SAMPLE_GROUP_ENV: "94",
        }
        cover_94 = {
            "category_id": "truck_rescue",
            "group_index": 94,
            "generation_kind": "cover",
            "prompt": (
                "写实中国货车救援维修门店。"
                "主招牌最大业务词必须清楚准确写成“货车救援维修”，门头预留联系信息区。"
            ),
        }
        cover_95 = {
            **cover_94,
            "group_index": 95,
            "cover_variant": truck_rescue_signage.signage_variant(95),
        }

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                category_image_production,
                "_load_active_tuning_sample_drafts",
                return_value=[draft],
            ),
        ):
            bound_prompt = category_image_production.effective_prompt(
                cover_94, "13812345678"
            )
            other_prompt = category_image_production.effective_prompt(
                cover_95, "13812345678"
            )

        self.assertIn("本次单张调优样片覆盖规则", bound_prompt)
        self.assertIn("驰护货车维修救援", bound_prompt)
        self.assertIn("寓意字号、行业尾缀、六类服务小字", bound_prompt)
        self.assertNotIn(
            "主招牌最大业务词必须清楚准确写成“货车救援维修”",
            bound_prompt,
        )
        self.assertNotIn("本次单张调优样片覆盖规则", other_prompt)
        self.assertIn("捷擎重卡维修救援", other_prompt)
        self.assertNotIn(
            "主招牌最大业务词必须清楚准确写成“货车救援维修”",
            other_prompt,
        )
        self.assertEqual(bound_prompt.count("13812345678"), 1)


if __name__ == "__main__":
    unittest.main()
