from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import factory
import generate_truck_rescue_groups as groups
from tools import category_image_production, prompt_engine


SOURCE_ROOT = Path(__file__).resolve().parents[1]
PHONE = "13812345678"
HOTLINE = "400-677-1311"
PLAN_CONFIG = {
    "provider": "official",
    "base_url": "",
    "model": "gpt-image-2",
    "quality": "medium",
    "api_size": "1024x1536",
}


class TruckRescueFactoryWorkflowTests(unittest.TestCase):
    def test_factory_prompt_engine_and_production_register_truck_rescue(self) -> None:
        self.assertIn("truck_rescue", factory.CATEGORY_IMAGE_PROJECT_IDS)
        self.assertIn("truck_rescue", category_image_production.SUPPORTED_CATEGORY_IDS)
        self.assertIn(
            "truck_rescue",
            category_image_production.MODEL_GENERATED_SIGNBOARD_CATEGORIES,
        )
        self.assertEqual(
            category_image_production.CATEGORY_SIGNBOARD_TITLES["truck_rescue"],
            "货车救援维修",
        )
        loaded = prompt_engine.load_category_config("truck_rescue")
        self.assertEqual(loaded["category_id"], "truck_rescue")
        self.assertEqual(len(loaded["service_buttons"]), 10)

        parser = factory.build_parser()
        extend_args = parser.parse_args(
            ["extend-category-groups", "--category", "truck_rescue", "--count", "2"]
        )
        self.assertEqual(extend_args.category, "truck_rescue")
        plan_args = parser.parse_args(
            [
                "category-image-plan",
                "--category",
                "truck_rescue",
                "--group-start",
                "1",
                "--group-count",
                "3",
                "--scope",
                "covers",
            ]
        )
        self.assertEqual(plan_args.category, "truck_rescue")
        self.assertEqual(plan_args.group_start, 1)
        self.assertEqual(plan_args.group_count, 3)
        approve_args = parser.parse_args(
            [
                "approve-category-sample-covers",
                "--category",
                "truck_rescue",
                "--group-start",
                "144",
                "--group-count",
                "10",
                "--phone",
                PHONE,
                "--note",
                "已人工确认",
                "--confirm",
            ]
        )
        self.assertEqual(approve_args.phone, PHONE)

    def test_cover_evidence_binds_explicit_phone_to_recorded_phone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "output" / "truck_rescue" / "group_0144" / "01_cover.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"png-placeholder")
            validation_path = image.with_suffix(".validation.json")
            validation_path.write_text(
                json.dumps(
                    {
                        "expected_text": [f"电话：{PHONE}"],
                        "image_sha256": "frozen-image-sha256",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(factory, "ROOT", root),
                mock.patch.object(factory, "_category_output_root", return_value=image.parents[1]),
                mock.patch.object(factory, "_category_cover_expected_size", return_value=(1024, 1536)),
                mock.patch.object(factory.category_image_production, "valid_png", return_value=True),
                mock.patch.object(factory, "_category_confirmed_phone", return_value=PHONE) as confirmed,
                mock.patch.object(factory, "_validate_category_cover_record"),
                mock.patch.object(factory, "_sha256_file", return_value="frozen-image-sha256"),
            ):
                evidence = factory._category_cover_approval_evidence(
                    "truck_rescue", 144, 1, expected_phone=PHONE
                )
            confirmed.assert_called_once_with("truck_rescue", PHONE)
            self.assertEqual(evidence["groups"][0]["group_index"], 144)

    def test_cover_evidence_rejects_phone_mismatch(self) -> None:
        other_phone = "13912345678"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "output" / "truck_rescue" / "group_0144" / "01_cover.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"png-placeholder")
            image.with_suffix(".validation.json").write_text(
                json.dumps({"expected_text": [f"电话：{other_phone}"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            with (
                mock.patch.object(factory, "ROOT", root),
                mock.patch.object(factory, "_category_output_root", return_value=image.parents[1]),
                mock.patch.object(factory, "_category_cover_expected_size", return_value=(1024, 1536)),
                mock.patch.object(factory.category_image_production, "valid_png", return_value=True),
                mock.patch.object(factory, "_category_confirmed_phone", return_value=PHONE),
            ):
                with self.assertRaisesRegex(RuntimeError, "与本次指定号码.*不一致"):
                    factory._category_cover_approval_evidence(
                        "truck_rescue", 144, 1, expected_phone=PHONE
                    )

    def test_factory_sample_gate_allows_only_exact_three_group_initial_range(self) -> None:
        definition = json.loads(
            (SOURCE_ROOT / "projects" / "truck_rescue" / "project.json").read_text(
                encoding="utf-8-sig"
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path = root / "projects" / "truck_rescue" / "groups" / "registry.json"
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry_path.write_text(
                json.dumps(
                    {
                        "project_id": "truck_rescue",
                        "created_groups": 3,
                        "groups": [{"group_index": index} for index in range(1, 4)],
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(factory, "ROOT", root),
                mock.patch.object(factory, "project_definition", return_value=definition),
            ):
                factory._category_sample_range("truck_rescue", 1, 3)
                for invalid_count in (1, 2, 4):
                    with self.subTest(count=invalid_count), self.assertRaisesRegex(
                        RuntimeError,
                        "只允许先做第 1 至第 3 组",
                    ):
                        factory._category_sample_range("truck_rescue", 1, invalid_count)

    def test_three_group_plans_have_exact_cover_detail_and_all_request_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_dir = root / "projects" / "truck_rescue"
            groups_dir = project_dir / "groups"
            batch_dir = (
                root
                / "prompts"
                / "category_batches"
                / "truck_rescue"
                / groups.BATCH_NAME
            )
            config_path = root / "configs" / "categories" / "truck_rescue.json"
            business_path = root / ".runtime" / "projects" / "truck_rescue" / "business.json"
            for relative in (
                Path("configs/categories/truck_rescue.json"),
                Path("projects/truck_rescue/project.json"),
                Path("projects/truck_rescue/cover_scene_library.json"),
                Path("projects/truck_rescue/category_content_profile.json"),
                Path("projects/truck_rescue/groups/registry.json"),
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(SOURCE_ROOT / relative, target)
            (groups_dir / "registry.json").write_text(
                json.dumps(groups._registry(1, []), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            business_path.parent.mkdir(parents=True, exist_ok=True)
            business_path.write_text(
                json.dumps(
                    {
                        "project_id": "truck_rescue",
                        "contact_phones": [PHONE],
                        "user_confirmed": True,
                        "placeholder_only": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            category = json.loads(config_path.read_text(encoding="utf-8-sig"))
            project_path = project_dir / "project.json"
            project = json.loads(project_path.read_text(encoding="utf-8-sig"))
            project["required_fields"]["service_words"]["confirmed"] = True
            project["required_fields"]["service_words"]["values"] = list(
                category["service_buttons"]
            )
            project_path.write_text(
                json.dumps(project, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with mock.patch.multiple(
                groups,
                ROOT=root,
                PROJECT_DIR=project_dir,
                GROUPS_DIR=groups_dir,
                REGISTRY_PATH=groups_dir / "registry.json",
                BATCH_DIR=batch_dir,
                CATEGORY_CONFIG_PATH=config_path,
                COVER_LIBRARY_PATH=project_dir / "cover_scene_library.json",
                BUSINESS_PATH=business_path,
            ):
                groups.extend_truck_rescue_groups(3)

            expected = {
                "covers": (3, 3, 1, 1),
                "details": (18, 12, 6, 4),
                "all": (21, 15, 7, 5),
            }
            with (
                mock.patch.object(category_image_production, "ROOT", root),
                mock.patch.object(
                    category_image_production,
                    "CATEGORY_BATCH_ROOT",
                    root / "prompts" / "category_batches",
                ),
                mock.patch.object(
                    category_image_production,
                    "load_category_config",
                    return_value=category,
                ),
                mock.patch.object(
                    category_image_production.image_generate,
                    "generate_one",
                    side_effect=AssertionError("计划阶段不得调用图片 API"),
                ),
            ):
                for phone in (PHONE, HOTLINE):
                    for scope, (
                        request_count,
                        delivery_count,
                        units_per_group,
                        deliveries_per_group,
                    ) in expected.items():
                        with self.subTest(phone=phone, scope=scope):
                            run_plan = category_image_production.plan(
                                "truck_rescue",
                                batch_dir,
                                1,
                                3,
                                phone,
                                PLAN_CONFIG,
                                scope=scope,
                            )
                            self.assertEqual(run_plan["structure_version"], groups.STRUCTURE_VERSION)
                            self.assertEqual(run_plan["generation_mode"], groups.GENERATION_MODE)
                            self.assertEqual(run_plan["pending_api_requests"], request_count)
                            self.assertEqual(run_plan["total_generation_targets"], request_count)
                            self.assertEqual(run_plan["delivery_count"], delivery_count)
                            self.assertEqual(run_plan["pending_delivery_count"], delivery_count)
                            self.assertEqual(run_plan["generation_unit_count"], units_per_group)
                            self.assertEqual(run_plan["delivery_unit_count"], deliveries_per_group)
                            self.assertEqual(len(run_plan["group_recipes"]), 3)
                            bindings = factory._pipe_v2_plan_bindings(run_plan)
                            self.assertEqual(bindings["structure_version"], groups.STRUCTURE_VERSION)
                            self.assertEqual(bindings["pending_api_requests"], request_count)
                            self.assertEqual(bindings["delivery_count"], delivery_count)


if __name__ == "__main__":
    unittest.main()
