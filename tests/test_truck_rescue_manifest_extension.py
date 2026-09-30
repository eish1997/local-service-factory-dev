from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import generate_truck_rescue_groups as groups


SOURCE_ROOT = Path(__file__).resolve().parents[1]
PHONE = "13812345678"
HOTLINE = "400-677-1311"
EXPECTED_ROLES = set(groups.ROLE_IDS)


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


class TruckRescueTemporaryWorkspace(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project_dir = self.root / "projects" / "truck_rescue"
        self.groups_dir = self.project_dir / "groups"
        self.batch_dir = (
            self.root
            / "prompts"
            / "category_batches"
            / "truck_rescue"
            / groups.BATCH_NAME
        )
        self.config_path = self.root / "configs" / "categories" / "truck_rescue.json"
        self.business_path = self.root / ".runtime" / "projects" / "truck_rescue" / "business.json"

        for relative in (
            Path("configs/categories/truck_rescue.json"),
            Path("projects/truck_rescue/project.json"),
            Path("projects/truck_rescue/cover_scene_library.json"),
            Path("projects/truck_rescue/category_content_profile.json"),
            Path("projects/truck_rescue/groups/registry.json"),
        ):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE_ROOT / relative, target)

        # The live project may already have approved covers. Gate tests need
        # an isolated pre-approval copy as well as an empty group registry.
        isolated_project_path = self.project_dir / "project.json"
        isolated_project = json.loads(
            isolated_project_path.read_text(encoding="utf-8-sig")
        )
        isolated_project["references"]["cover"]["approved_style"] = False
        isolated_project["references"]["cover"]["sample_approval_evidence"] = None
        isolated_project_path.write_text(
            json.dumps(isolated_project, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # The real project may already contain sample groups. Every test starts
        # from an isolated empty registry so live onboarding state cannot turn
        # an initial-creation assertion into an extension assertion.
        (self.groups_dir / "registry.json").write_text(
            json.dumps(groups._registry(1, []), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self.patch = mock.patch.multiple(
            groups,
            ROOT=self.root,
            PROJECT_DIR=self.project_dir,
            GROUPS_DIR=self.groups_dir,
            REGISTRY_PATH=self.groups_dir / "registry.json",
            BATCH_DIR=self.batch_dir,
            CATEGORY_CONFIG_PATH=self.config_path,
            COVER_LIBRARY_PATH=self.project_dir / "cover_scene_library.json",
            BUSINESS_PATH=self.business_path,
        )
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temporary.cleanup()

    def confirm_phone(self) -> None:
        self.business_path.parent.mkdir(parents=True, exist_ok=True)
        self.business_path.write_text(
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

    def confirm_service_words(self) -> None:
        project_path = self.project_dir / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8-sig"))
        config = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        project["required_fields"]["service_words"]["confirmed"] = True
        project["required_fields"]["service_words"]["values"] = list(
            config["service_buttons"]
        )
        project_path.write_text(
            json.dumps(project, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def approve_samples(self) -> None:
        evidence = self.project_dir / "cover_approvals" / "groups_0001_0003.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            json.dumps(
                {
                    "category_id": "truck_rescue",
                    "group_start": 1,
                    "group_count": 3,
                    "approved": True,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        project_path = self.project_dir / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8-sig"))
        project["references"]["cover"]["approved_style"] = True
        project["references"]["cover"]["sample_approval_evidence"] = evidence.relative_to(
            self.root
        ).as_posix()
        project_path.write_text(
            json.dumps(project, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class TruckRescueManifestExtensionTests(TruckRescueTemporaryWorkspace):
    def test_confirmed_400_hotline_allows_local_manifest_creation(self) -> None:
        self.confirm_service_words()
        self.business_path.parent.mkdir(parents=True, exist_ok=True)
        self.business_path.write_text(
            json.dumps(
                {
                    "project_id": "truck_rescue",
                    "contact_phones": [HOTLINE],
                    "user_confirmed": True,
                    "placeholder_only": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = groups.extend_truck_rescue_groups(3)
        self.assertEqual(result["group_count"], 3)
        self.assertFalse(result["api_called"])

    def test_multiple_confirmed_phones_allow_local_manifest_creation(self) -> None:
        self.confirm_service_words()
        self.business_path.parent.mkdir(parents=True, exist_ok=True)
        self.business_path.write_text(
            json.dumps(
                {
                    "project_id": "truck_rescue",
                    "contact_phones": [PHONE, "13912345678"],
                    "user_confirmed": True,
                    "placeholder_only": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = groups.extend_truck_rescue_groups(3)
        self.assertEqual(result["group_count"], 3)
        self.assertFalse(result["api_called"])

    def test_initial_creation_requires_confirmed_phone_and_exactly_three_groups(self) -> None:
        with self.assertRaisesRegex(
            groups.TruckRescueManifestError,
            "CONTACT_CONFIRMATION_REQUIRED",
        ):
            groups.extend_truck_rescue_groups(3)

        self.confirm_phone()
        self.confirm_service_words()
        for invalid_count in (1, 2, 4):
            with self.subTest(count=invalid_count), self.assertRaisesRegex(
                groups.TruckRescueManifestError,
                "首次只允许建立第1至第3组三组样片清单",
            ):
                groups.extend_truck_rescue_groups(invalid_count)

        result = groups.extend_truck_rescue_groups(3)
        self.assertEqual(result["operation"], "create_sample_manifests")
        self.assertEqual(result["group_start"], 1)
        self.assertEqual(result["group_count"], 3)
        self.assertEqual(result["generation_unit_count"], 21)
        self.assertEqual(result["delivery_file_count"], 15)
        self.assertFalse(result["api_called"])

    def test_initial_manifests_are_truck_only_and_cover_all_six_roles(self) -> None:
        self.confirm_phone()
        self.confirm_service_words()
        groups.extend_truck_rescue_groups(3)

        generation = read_jsonl(self.groups_dir / "generation_manifest.jsonl")
        deliveries = read_jsonl(self.groups_dir / "production_manifest.jsonl")
        group_manifest = read_jsonl(self.groups_dir / "group_manifest.jsonl")
        self.assertEqual(len(generation), 21)
        self.assertEqual(len(deliveries), 15)
        self.assertEqual(len(group_manifest), 3)

        all_powertrains: set[str] = set()
        all_brake_systems: set[str] = set()
        role_scene_signatures: dict[str, set[tuple[str, str, str]]] = {
            role: set() for role in EXPECTED_ROLES
        }
        for group_index in range(1, 4):
            group_generation = [row for row in generation if row["group_index"] == group_index]
            group_deliveries = [row for row in deliveries if row["group_index"] == group_index]
            self.assertEqual(
                [row["generation_kind"] for row in group_generation],
                ["cover", "triptych_panel", "triptych_panel", "triptych_panel", "detail", "detail", "detail"],
            )
            self.assertEqual(
                [row["delivery_position"] for row in group_generation],
                [1, 2, 2, 2, 3, 4, 5],
            )
            self.assertEqual(
                [row["panel_index"] for row in group_generation[1:4]],
                [1, 2, 3],
            )
            self.assertEqual({row["service_role"] for row in group_generation[1:]}, EXPECTED_ROLES)
            self.assertEqual(
                [row["role"] for row in group_deliveries],
                ["cover", "triptych", "detail", "detail", "detail"],
            )
            triptych = group_deliveries[1]
            self.assertEqual(
                triptych["source_generation_ids"],
                [row["generation_id"] for row in group_generation[1:4]],
            )
            self.assertEqual(len(triptych["source_generation_ids"]), 3)
            self.assertEqual(len(set(triptych["service_roles"])), 3)

            for row in group_generation:
                self.assertEqual(
                    row["source_lineage"],
                    "projects/truck_rescue/category_content_profile.json",
                )
                self.assertNotIn("road_rescue", row["source_lineage"])
            for row in group_generation[1:]:
                scene = row["scene"]
                vehicle = scene["vehicle"]
                self.assertEqual(scene["vehicle_policy"], "truck_only")
                self.assertTrue(
                    any(
                        term in vehicle
                        for term in ("货车", "卡车", "牵引车", "货运皮卡")
                    )
                )
                self.assertFalse(any(term in vehicle for term in ("轿车", "SUV", "MPV", "乘用车")))
                self.assertIn(scene["powertrain"], {"combustion", "unspecified"})
                self.assertIn(scene["brake_system"], {"air", "hydraulic", "unspecified"})
                all_powertrains.add(scene["powertrain"])
                all_brake_systems.add(scene["brake_system"])
                role_scene_signatures[row["service_role"]].add(
                    (scene["vehicle"], scene["location"], scene["action"])
                )
                if row["service_role"] == "货车没油救援":
                    self.assertEqual(scene["powertrain"], "combustion")
                if row["service_role"] == "货车刹车故障":
                    self.assertIn(scene["brake_system"], {"air", "hydraulic"})

        for row in group_manifest:
            self.assertEqual(set(row["service_roles"]), EXPECTED_ROLES)
            self.assertEqual(row["generation_unit_count"], 7)
            self.assertEqual(row["total_images"], 5)
            self.assertEqual(
                row["source_lineage"],
                "projects/truck_rescue/category_content_profile.json",
            )
            self.assertNotIn("road_rescue", row["source_lineage"])
        self.assertIn("combustion", all_powertrains)
        self.assertIn("air", all_brake_systems)
        self.assertIn("hydraulic", all_brake_systems)
        self.assertTrue(
            all(len(signatures) == 3 for signatures in role_scene_signatures.values())
        )

    def test_unapproved_samples_block_extension_then_approved_extension_preserves_prefixes(self) -> None:
        self.confirm_phone()
        self.confirm_service_words()
        groups.extend_truck_rescue_groups(3)

        with self.assertRaisesRegex(
            groups.TruckRescueManifestError,
            "样片尚未正式批准",
        ):
            groups.extend_truck_rescue_groups(1)

        group_names = (
            "group_manifest.jsonl",
            "generation_manifest.jsonl",
            "production_manifest.jsonl",
            "extension_history.jsonl",
        )
        batch_names = (
            "prompts.jsonl",
            "cover_prompts.jsonl",
            "triptych_panel_prompts.jsonl",
            "detail_prompts.jsonl",
            "manifest.jsonl",
            "delivery_manifest.jsonl",
        )
        prefixes = {
            path: path.read_bytes()
            for path in (
                *(self.groups_dir / name for name in group_names),
                *(self.batch_dir / name for name in batch_names),
            )
        }

        self.approve_samples()
        result = groups.extend_truck_rescue_groups(2)
        self.assertEqual(result["operation"], "extend_manifests")
        self.assertEqual(result["old_group_count"], 3)
        self.assertEqual(result["added_group_count"], 2)
        self.assertEqual(result["new_group_start"], 4)
        self.assertEqual(result["new_group_end"], 5)
        self.assertEqual(result["new_generation_units"], 14)
        self.assertTrue(result["historical_prefix_preserved"])
        self.assertFalse(result["api_called"])

        for path, prefix in prefixes.items():
            with self.subTest(path=path.name):
                self.assertTrue(path.read_bytes().startswith(prefix))

        registry = json.loads((self.groups_dir / "registry.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(registry["created_groups"], 5)
        self.assertEqual(registry["first_group_index"], 1)
        self.assertEqual(registry["last_group_index"], 5)
        self.assertEqual(registry["next_group_index"], 6)
        self.assertEqual(len(read_jsonl(self.groups_dir / "generation_manifest.jsonl")), 35)
        self.assertEqual(len(read_jsonl(self.groups_dir / "production_manifest.jsonl")), 25)
        extended_generation = read_jsonl(self.groups_dir / "generation_manifest.jsonl")
        group_4_scenes = [
            row["scene"]
            for row in extended_generation
            if row["group_index"] == 4 and row["service_role"] is not None
        ]
        self.assertEqual(len(group_4_scenes), 6)
        self.assertEqual(
            sum(
                any(term in scene["vehicle"] for term in ("重型", "重卡", "牵引车", "半挂"))
                for scene in group_4_scenes
            ),
            2,
        )
        pickup_scenes = [
            scene for scene in group_4_scenes if "大型全尺寸货运皮卡" in scene["vehicle"]
        ]
        self.assertEqual(len(pickup_scenes), 1)
        self.assertEqual(pickup_scenes[0]["brake_system"], "hydraulic")
        self.assertIn("额定电压", pickup_scenes[0]["action"])
        history = read_jsonl(self.groups_dir / "extension_history.jsonl")
        self.assertEqual(history[-1]["operation"], "extend_manifests")
        self.assertEqual(history[-1]["group_start"], 4)
        self.assertEqual(history[-1]["group_count"], 2)
        self.assertFalse(history[-1]["api_called"])

    def test_groups_94_to_273_use_unique_names_and_preserve_prefixes(self) -> None:
        self.confirm_phone()
        self.confirm_service_words()
        groups.extend_truck_rescue_groups(3)
        self.approve_samples()
        groups.extend_truck_rescue_groups(91)

        protected_paths = (
            self.groups_dir / "group_manifest.jsonl",
            self.groups_dir / "generation_manifest.jsonl",
            self.groups_dir / "production_manifest.jsonl",
            self.batch_dir / "prompts.jsonl",
            self.batch_dir / "cover_prompts.jsonl",
            self.batch_dir / "triptych_panel_prompts.jsonl",
            self.batch_dir / "detail_prompts.jsonl",
            self.batch_dir / "manifest.jsonl",
            self.batch_dir / "delivery_manifest.jsonl",
        )
        prefixes = {path: path.read_bytes() for path in protected_paths}

        result = groups.extend_truck_rescue_groups(49)
        self.assertEqual(result["new_group_start"], 95)
        self.assertEqual(result["new_group_end"], 143)
        self.assertEqual(result["new_generation_units"], 343)
        self.assertTrue(result["historical_prefix_preserved"])
        self.assertFalse(result["api_called"])
        for path, prefix in prefixes.items():
            with self.subTest(path=path.name):
                self.assertTrue(path.read_bytes().startswith(prefix))

        generation = read_jsonl(self.groups_dir / "generation_manifest.jsonl")
        covers = [
            row
            for row in generation
            if row["generation_kind"] == "cover" and 94 <= row["group_index"] <= 143
        ]
        self.assertEqual(len(covers), 50)
        self.assertEqual(
            covers[0]["cover_variant"]["full_store_name"],
            "驰护货车维修救援",
        )
        self.assertEqual(
            len({row["cover_variant"]["brand_name"] for row in covers}),
            50,
        )
        self.assertEqual(
            len({row["cover_variant"]["full_store_name"] for row in covers}),
            50,
        )
        for row in covers:
            full_name = row["cover_variant"]["full_store_name"]
            self.assertIn(full_name, row["positive_prompt"])
            self.assertNotIn(
                "主招牌最大业务词必须清楚准确写成“货车救援维修”",
                row["positive_prompt"],
            )

        prefixes_at_143 = {path: path.read_bytes() for path in protected_paths}
        result = groups.extend_truck_rescue_groups(30)
        self.assertEqual(result["new_group_start"], 144)
        self.assertEqual(result["new_group_end"], 173)
        self.assertEqual(result["new_generation_units"], 210)
        self.assertTrue(result["historical_prefix_preserved"])
        self.assertFalse(result["api_called"])
        for path, prefix in prefixes_at_143.items():
            with self.subTest(path=path.name):
                self.assertTrue(path.read_bytes().startswith(prefix))

        generation = read_jsonl(self.groups_dir / "generation_manifest.jsonl")
        all_named_covers = [
            row
            for row in generation
            if row["generation_kind"] == "cover" and 94 <= row["group_index"] <= 173
        ]
        new_covers = [row for row in all_named_covers if row["group_index"] >= 144]
        expected_new_names = [
            "承衡", "载衡", "铸护", "砥护", "慎修", "毅稳", "厚固", "韧固", "厚行", "恪行",
            "拓韧", "朴程", "磐稳", "矩途", "敦守", "正守", "守矩", "协援", "久擎", "信擎",
            "勤匠", "淬匠", "梁承", "磐承", "准修", "实修", "砺矩", "善路", "衡毅", "稳拓",
        ]
        self.assertEqual(
            [row["cover_variant"]["brand_name"] for row in new_covers],
            expected_new_names,
        )
        self.assertEqual(len(all_named_covers), 80)
        self.assertEqual(
            len({row["cover_variant"]["brand_name"] for row in all_named_covers}),
            80,
        )

        prefixes_at_173 = {path: path.read_bytes() for path in protected_paths}
        result = groups.extend_truck_rescue_groups(50)
        self.assertEqual(result["new_group_start"], 174)
        self.assertEqual(result["new_group_end"], 223)
        self.assertEqual(result["new_generation_units"], 350)
        self.assertTrue(result["historical_prefix_preserved"])
        self.assertFalse(result["api_called"])
        for path, prefix in prefixes_at_173.items():
            with self.subTest(path=path.name):
                self.assertTrue(path.read_bytes().startswith(prefix))

        generation = read_jsonl(self.groups_dir / "generation_manifest.jsonl")
        all_named_covers = [
            row
            for row in generation
            if row["generation_kind"] == "cover" and 94 <= row["group_index"] <= 223
        ]
        new_covers = [row for row in all_named_covers if row["group_index"] >= 174]
        self.assertEqual(len(new_covers), 50)
        self.assertEqual(new_covers[0]["cover_variant"]["brand_name"], "锐应")
        self.assertEqual(new_covers[-1]["cover_variant"]["brand_name"], "捷应")
        self.assertEqual(len(all_named_covers), 130)
        self.assertEqual(
            len({row["cover_variant"]["brand_name"] for row in all_named_covers}),
            130,
        )

        prefixes_at_223 = {path: path.read_bytes() for path in protected_paths}
        result = groups.extend_truck_rescue_groups(50)
        self.assertEqual(result["new_group_start"], 224)
        self.assertEqual(result["new_group_end"], 273)
        self.assertEqual(result["new_generation_units"], 350)
        self.assertTrue(result["historical_prefix_preserved"])
        self.assertFalse(result["api_called"])
        for path, prefix in prefixes_at_223.items():
            with self.subTest(path=path.name):
                self.assertTrue(path.read_bytes().startswith(prefix))

        generation = read_jsonl(self.groups_dir / "generation_manifest.jsonl")
        all_named_covers = [
            row
            for row in generation
            if row["generation_kind"] == "cover" and 94 <= row["group_index"] <= 273
        ]
        new_covers = [row for row in all_named_covers if row["group_index"] >= 224]
        self.assertEqual(len(new_covers), 50)
        self.assertEqual(new_covers[0]["cover_variant"]["brand_name"], "速安")
        self.assertEqual(new_covers[-1]["cover_variant"]["brand_name"], "路畅")
        self.assertEqual(len(all_named_covers), 180)
        self.assertEqual(
            len({row["cover_variant"]["brand_name"] for row in all_named_covers}),
            180,
        )


if __name__ == "__main__":
    unittest.main()
