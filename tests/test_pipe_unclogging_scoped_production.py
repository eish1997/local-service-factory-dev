from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
import unittest
from argparse import Namespace
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tools import category_image_production


CONFIG = {
    "provider": "relay",
    "base_url": "https://example.invalid/v1",
    "model": "gpt-image-2",
    "quality": "medium",
    "api_size": "1024x1536",
}
PHONE = "13317112954"
STRUCTURE_VERSION = "pipe_unclogging_v2_1cover_1triptych_3details"
GENERATION_MODE = "independent_triptych_panels"


class PipeUncloggingScopedProductionTests(unittest.TestCase):
    def make_v2_batch(self, root: Path, group_count: int) -> Path:
        batch_dir = root / "pipe_unclogging" / "batch_v2_fixture"
        batch_dir.mkdir(parents=True)
        structure = category_image_production.load_category_config(
            "pipe_unclogging"
        )["image_group_structure"]
        service_roles = list(structure["service_role_pool"])
        height_profiles = list(structure["height_profiles"])
        layouts = list(structure["triptych_layouts"])
        generation_kinds = [
            "cover",
            "triptych_panel",
            "triptych_panel",
            "triptych_panel",
            "detail",
            "detail",
            "detail",
        ]
        delivery_positions = [1, 2, 2, 2, 3, 4, 5]
        rows: list[dict] = []

        for group_index in range(1, group_count + 1):
            height_profile = height_profiles[(group_index - 1) % len(height_profiles)]
            final_size = f"{height_profile['width']}x{height_profile['height']}"
            layout = layouts[
                ((group_index - 1) // len(height_profiles)) % len(layouts)
            ]
            selected_roles = [
                service_roles[(group_index - 1 + offset) % len(service_roles)]
                for offset in range(6)
            ]
            cover_variant = {
                axis: f"fixture-{axis}-{group_index}"
                for axis in category_image_production.COVER_VARIATION_STEPS
            }

            for generation_position, generation_kind in enumerate(
                generation_kinds, start=1
            ):
                panel_index = (
                    generation_position - 1
                    if generation_kind == "triptych_panel"
                    else None
                )
                service_role = (
                    None
                    if generation_kind == "cover"
                    else selected_roles[generation_position - 2]
                )
                if generation_kind == "cover":
                    raw_name = "u01_cover.png"
                elif generation_kind == "triptych_panel":
                    raw_name = (
                        f"u{generation_position:02d}_triptych_panel_{panel_index}.png"
                    )
                else:
                    raw_name = (
                        f"u{generation_position:02d}_detail_"
                        f"{generation_position - 4}.png"
                    )
                prompt = (
                    f"Local test fixture for group {group_index}, "
                    f"generation unit {generation_position}."
                )
                row = {
                    "schema_version": 2,
                    "structure_version": STRUCTURE_VERSION,
                    "generation_mode": GENERATION_MODE,
                    "project_id": "pipe_unclogging",
                    "category_id": "pipe_unclogging",
                    "index": (group_index - 1) * 7 + generation_position,
                    "group_index": group_index,
                    "generation_position": generation_position,
                    "generation_id": (
                        f"pipe_unclogging:v2:g{group_index:04d}:"
                        f"u{generation_position:02d}"
                    ),
                    "role": generation_kind,
                    "generation_kind": generation_kind,
                    "service_role": service_role,
                    "delivery_position": delivery_positions[generation_position - 1],
                    "raw_target": str(
                        batch_dir
                        / "raw"
                        / f"group_{group_index:04d}"
                        / raw_name
                    ),
                    "raw_size": "1024x1536",
                    "expected_size": final_size,
                    "final_size": final_size,
                    "height_profile_id": height_profile["id"],
                    "triptych_layout_id": layout["id"],
                    "variation_cycle_index": group_index,
                    "triptych_panel_index": panel_index,
                    "triptych_panel_box": (
                        layout["panels"][panel_index - 1]
                        if panel_index is not None
                        else None
                    ),
                    "positive_prompt": prompt,
                    "negative_prompt": "test exclusions",
                    "prompt": prompt,
                    "status": "prompt_ready",
                    "api_called": False,
                }
                if generation_kind == "cover":
                    row["cover_variant"] = cover_variant
                    row["cover_variant_signature"] = f"{group_index:064x}"
                rows.append(row)

        (batch_dir / "prompts.jsonl").write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        return batch_dir

    def make_truck_v3_batch(self, root: Path) -> Path:
        source_batch = self.make_v2_batch(root, 1)
        batch_dir = root / "truck_rescue" / "batch_v3_fixture"
        batch_dir.parent.mkdir(parents=True)
        source_batch.rename(batch_dir)
        roles = [
            "货车没油救援",
            "货车爆胎救援",
            "货车换轮胎",
            "货车发动机故障",
            "卡车搭电",
            "货车刹车故障",
        ]
        rows = [
            json.loads(line)
            for line in (batch_dir / "prompts.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        for row in rows:
            generation_position = int(row["generation_position"])
            row["category_id"] = "truck_rescue"
            row["project_id"] = "truck_rescue"
            row["structure_version"] = "truck_rescue_v3_1cover_1triptych_3details"
            row["generation_id"] = (
                f"truck_rescue:v3:g0001:u{generation_position:02d}"
            )
            row["raw_target"] = str(
                batch_dir
                / "raw"
                / "group_0001"
                / Path(str(row["raw_target"])).name
            )
            if generation_position == 1:
                row["service_role"] = None
                continue
            role = roles[generation_position - 2]
            row["service_role"] = role
            row["scene"] = {
                "scene_type": "truck_service_fixture",
                "vehicle_policy": "truck_only",
                "vehicle": "中型载货货车",
                "location": "物流园货车维修工位",
                "action": "工作人员完成本角色的具体货车维修动作",
                "tools": "轮挡、检修灯和货车专用工具",
            }
            row["positive_prompt"] = (
                f"货车详情测试：{role}。车辆为{row['scene']['vehicle']}，"
                f"地点为{row['scene']['location']}。{row['scene']['action']}。"
                f"工具为{row['scene']['tools']}。"
            )
            row["negative_prompt"] = "LONG_ENGLISH_NEGATIVE_PROMPT"
            row["prompt"] = (
                row["positive_prompt"] + "严格排除：" + row["negative_prompt"]
            )
        (batch_dir / "prompts.jsonl").write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        return batch_dir

    def license_payload(
        self,
        run_plan: dict,
        license_id: str,
        *,
        slots: list[int] | None = None,
        max_workers: int = 1,
        max_attempts: int = 1,
    ) -> dict:
        key_slots = slots or [1]
        pending_api = int(run_plan["pending_api_requests"])
        pending_delivery = int(run_plan["pending_delivery_count"])
        return {
            "schema_version": 2,
            "production_schema_version": run_plan["production_schema_version"],
            "structure_version": run_plan["structure_version"],
            "generation_mode": run_plan["generation_mode"],
            "kind": "category-image-production",
            "license_id": license_id,
            "status": "active",
            "one_time": True,
            "category_id": run_plan["category_id"],
            "batch_id": run_plan["batch_id"],
            "batch_dir": run_plan["batch_dir"],
            "group_start": run_plan["group_start"],
            "group_count": run_plan["group_count"],
            "scope": run_plan["scope"],
            "output_root": run_plan["output_root"],
            "phone": PHONE,
            "manifest_sha256": run_plan["manifest_sha256"],
            "plan_sha256": run_plan["plan_sha256"],
            "targets_sha256": run_plan["targets_sha256"],
            "generation_targets_sha256": run_plan["generation_targets_sha256"],
            "delivery_targets_sha256": run_plan["delivery_targets_sha256"],
            "pending_generation_targets_sha256": run_plan[
                "pending_generation_targets_sha256"
            ],
            "pending_delivery_targets_sha256": run_plan[
                "pending_delivery_targets_sha256"
            ],
            "group_recipes_sha256": run_plan["group_recipes_sha256"],
            "approved_target_ids": run_plan["pending_target_ids"],
            "approved_targets_sha256": run_plan["pending_targets_sha256"],
            "approved_generation_target_ids": run_plan[
                "pending_generation_target_ids"
            ],
            "approved_delivery_target_ids": run_plan[
                "pending_delivery_target_ids"
            ],
            "provider": CONFIG["provider"],
            "base_url": CONFIG["base_url"],
            "model": CONFIG["model"],
            "quality": CONFIG["quality"],
            "size": CONFIG["api_size"],
            "approved_api_request_count": pending_api,
            "approved_delivery_count": pending_delivery,
            "approved_image_count": pending_delivery,
            "approved_request_budget": pending_api * max_attempts,
            "max_attempts": max_attempts,
            "retry_policy": (
                category_image_production.CLASSIFIED_RETRY_POLICY
                if max_attempts == 2
                else category_image_production.NO_RETRY_POLICY
            ),
            "sdk_max_retries": 0,
            "max_workers": max_workers,
            "api_key_slots": key_slots,
            "third_party_confirmed": True,
            "requests_used": 0,
        }

    def test_scope_plans_bind_stable_exact_target_sets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 3)
                all_plan = category_image_production.plan(
                    "pipe_unclogging", batch_dir, 1, 3, PHONE, CONFIG
                )
                covers = category_image_production.plan(
                    "pipe_unclogging", batch_dir, 1, 3, PHONE, CONFIG, scope="covers"
                )
                covers_again = category_image_production.plan(
                    "pipe_unclogging", batch_dir, 1, 3, PHONE, CONFIG, scope="covers"
                )
                details = category_image_production.plan(
                    "pipe_unclogging", batch_dir, 1, 3, PHONE, CONFIG, scope="details"
                )

        self.assertEqual((all_plan["total_images"], all_plan["pending_api_images"]), (15, 21))
        self.assertEqual(all_plan["total_generation_targets"], 21)
        self.assertEqual(all_plan["total_delivery_targets"], 15)
        self.assertEqual((covers["total_images"], covers["pending_api_images"]), (3, 3))
        self.assertEqual((details["total_images"], details["pending_api_images"]), (12, 18))
        self.assertEqual(
            [record["delivery_kind"] for record in all_plan["delivery_records"][:5]],
            ["cover", "triptych", "detail", "detail", "detail"],
        )
        self.assertTrue(all(record["position"] == 1 for record in covers["records"]))
        self.assertTrue(all(record["position"] > 1 for record in details["records"]))
        self.assertEqual(covers["target_ids"], covers_again["target_ids"])
        self.assertEqual(covers["pending_target_ids"], covers_again["pending_target_ids"])
        self.assertEqual(covers["targets_sha256"], covers_again["targets_sha256"])
        self.assertEqual(covers["plan_sha256"], covers_again["plan_sha256"])
        self.assertNotEqual(covers["plan_sha256"], details["plan_sha256"])

    def test_formal_output_recovers_triptych_and_detail_but_not_needs_fix_cover(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "pipe_unclogging"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 1)
                legacy_records = category_image_production.record_targets(
                    batch_dir,
                    category_image_production.selected_records(batch_dir, 1, 1),
                    formal_root,
                )
                cover = legacy_records[0]
                target = Path(cover["target"])
                raw_target = Path(cover["raw_target"])
                target.parent.mkdir(parents=True, exist_ok=True)
                raw_target.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1024, 1408), (170, 170, 170)).save(target)
                Image.new("RGB", (1024, 1536), (170, 170, 170)).save(raw_target)
                target.with_suffix(".validation.json").write_text(
                    json.dumps({"status": "needs_fix"}, ensure_ascii=False),
                    encoding="utf-8",
                )
                for record in [*legacy_records[1:4], legacy_records[4]]:
                    raw_target = Path(record["raw_target"])
                    raw_target.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (1024, 1536), (170, 170, 170)).save(raw_target)
                covers = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="covers",
                    output_root=formal_root,
                )
                details = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                with self.assertRaises(category_image_production.CategoryPromptError):
                    category_image_production.plan(
                        "pipe_unclogging",
                        batch_dir,
                        1,
                        1,
                        PHONE,
                        CONFIG,
                        output_root=root / "elsewhere",
                    )

        self.assertEqual((covers["recoverable_images"], covers["pending_api_images"]), (0, 1))
        self.assertEqual((details["recoverable_images"], details["pending_api_images"]), (2, 2))
        self.assertEqual(len(details["recoverable_records"]), 4)
        self.assertTrue(all(Path(record["target"]).is_relative_to(formal_root) for record in details["records"]))
        self.assertTrue(
            all(Path(record["legacy_target"]).is_relative_to(batch_dir / "images") for record in details["records"])
        )
        self.assertTrue(
            all(Path(record["raw_target"]).is_relative_to(batch_dir / "raw") for record in details["records"])
        )

    def test_license_scoped_artifacts_are_immutable_and_legacy_paths_remain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 1)
                run_plan = category_image_production.plan(
                    "pipe_unclogging", batch_dir, 1, 1, PHONE, CONFIG, scope="covers"
                )
                license_id = "pipe-test-license"
                manifest, overlay = category_image_production.write_production_files(
                    run_plan, PHONE, license_id
                )
                category_image_production.write_production_files(run_plan, PHONE, license_id)
                changed = deepcopy(run_plan)
                changed["manifest_entries"][0]["effective_prompt"] += " changed"
                with self.assertRaises(RuntimeError):
                    category_image_production.write_production_files(changed, PHONE, license_id)
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 1, license_id
                )
                category_image_production.write_new_license(target_license, {"license_id": license_id})
                with self.assertRaises(RuntimeError):
                    category_image_production.write_new_license(target_license, {"license_id": "other"})

        self.assertIn("production\\manifests", str(manifest))
        self.assertIn("production\\overlay_plans", str(overlay))
        self.assertIn("production\\licenses", str(target_license))
        legacy = category_image_production.license_path("pipe_unclogging", Path("batch"), 1, 1)
        self.assertEqual(legacy.name, "authorization_groups_0001_0001.json")

    def test_load_frozen_manifest_runtime_records_binds_prompt_scene_ids_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "truck_rescue"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_truck_v3_batch(root)
                run_plan = category_image_production.plan(
                    "truck_rescue",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                license_id = "truck-frozen-runtime-test"
                manifest_file, _ = (
                    category_image_production.write_production_files(
                        run_plan, PHONE, license_id
                    )
                )
                frozen_entries = [
                    json.loads(line)
                    for line in manifest_file.read_text(
                        encoding="utf-8"
                    ).splitlines()
                ]

                records = (
                    category_image_production.load_frozen_manifest_runtime_records(
                        batch_dir,
                        manifest_file,
                        run_plan["manifest_sha256"],
                    )
                )

                self.assertEqual(len(records), 6)
                self.assertEqual(
                    [record["generation_target_id"] for record in records],
                    [entry["generation_target_id"] for entry in frozen_entries],
                )
                self.assertEqual(
                    len(category_image_production._delivery_records(records)), 4
                )
                for record, entry in zip(records, frozen_entries):
                    self.assertNotIn("effective_prompt", record)
                    self.assertEqual(
                        record["frozen_effective_prompt"], entry["effective_prompt"]
                    )
                    self.assertEqual(
                        record["frozen_effective_prompt_sha256"],
                        entry["effective_prompt_sha256"],
                    )
                    self.assertEqual(
                        record["frozen_manifest_sha256"],
                        run_plan["manifest_sha256"],
                    )
                    self.assertEqual(
                        record["prompt_source"], "frozen_production_manifest"
                    )
                    self.assertTrue(
                        Path(record["raw_target"]).is_relative_to(batch_dir / "raw")
                    )
                    self.assertTrue(
                        Path(record["legacy_target"]).is_relative_to(
                            batch_dir / "images"
                        )
                    )
                    self.assertTrue(
                        Path(record["target"]).is_relative_to(formal_root)
                    )
                    self.assertEqual(
                        set((record["scene"] or {}).keys())
                        >= {"vehicle", "location", "action", "tools"},
                        True,
                    )
                    with self.assertRaisesRegex(
                        category_image_production.CategoryPromptError,
                        "禁止重算 original prompt",
                    ):
                        category_image_production.effective_prompt(record, PHONE)

    def test_load_frozen_manifest_runtime_records_rejects_hash_path_and_scene_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "truck_rescue"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_truck_v3_batch(root)
                run_plan = category_image_production.plan(
                    "truck_rescue",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                license_id = "truck-frozen-runtime-rejection-test"
                manifest_file, _ = (
                    category_image_production.write_production_files(
                        run_plan, PHONE, license_id
                    )
                )
                with self.assertRaisesRegex(
                    category_image_production.CategoryPromptError,
                    "SHA-256 与许可证不一致",
                ):
                    category_image_production.load_frozen_manifest_runtime_records(
                        batch_dir, manifest_file, "0" * 64
                    )

                entries = [
                    json.loads(line)
                    for line in manifest_file.read_text(
                        encoding="utf-8"
                    ).splitlines()
                ]
                entries[0]["raw_target"] = "raw/../outside.png"
                path_tampered = manifest_file.with_name("path-tampered.jsonl")
                path_tampered.write_text(
                    "".join(
                        json.dumps(entry, ensure_ascii=False) + "\n"
                        for entry in entries
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    category_image_production.CategoryPromptError,
                    "raw_target 必须位于 raw/ 下",
                ):
                    category_image_production.load_frozen_manifest_runtime_records(
                        batch_dir,
                        path_tampered,
                        category_image_production.manifest_sha256(entries),
                    )

                source_rows = [
                    json.loads(line)
                    for line in (batch_dir / "prompts.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                source_row = next(
                    row
                    for row in source_rows
                    if int(row["index"]) == int(entries[0]["source_index"])
                )
                source_row["scene"]["action"] = "已漂移且未绑定的动作"
                (batch_dir / "prompts.jsonl").write_text(
                    "".join(
                        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                        for row in source_rows
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    category_image_production.CategoryPromptError,
                    "scene 未绑定",
                ):
                    category_image_production.load_frozen_manifest_runtime_records(
                        batch_dir,
                        manifest_file,
                        run_plan["manifest_sha256"],
                    )

    def test_validate_license_binds_scope_plan_targets_budget_and_workers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 3)
                run_plan = category_image_production.plan(
                    "pipe_unclogging", batch_dir, 1, 3, PHONE, CONFIG, scope="covers"
                )
                license_id = "pipe-validation-test"
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 3, license_id
                )
                payload = self.license_payload(
                    run_plan, license_id, slots=[1, 2], max_workers=2
                )
                category_image_production.write_new_license(target_license, payload)
                validated = category_image_production.validate_license(
                    target_license, run_plan, CONFIG, [1, 2], 2
                )
                self.assertEqual(validated["license_id"], license_id)

                changed = deepcopy(run_plan)
                changed["pending_target_ids"][0] = "pipe_unclogging:g9999:p01:s999999"
                changed["pending_targets_sha256"] = category_image_production._json_sha256(
                    changed["pending_target_ids"]
                )
                with self.assertRaises(RuntimeError):
                    category_image_production.validate_license(
                        target_license, changed, CONFIG, [1, 2], 2
                    )

                bad_budget_path = root / "bad-budget.json"
                bad_budget = deepcopy(payload)
                bad_budget["approved_request_budget"] += 1
                bad_budget_path.write_text(json.dumps(bad_budget), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    category_image_production.validate_license(
                        bad_budget_path, run_plan, CONFIG, [1, 2], 2
                    )

    def test_validate_fixed_ten_license_requires_ten_keys_and_workers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 2)
                run_plan = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    2,
                    PHONE,
                    CONFIG,
                    scope="details",
                )
                license_id = "pipe-fixed-ten-validation-test"
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 2, license_id
                )
                slots = list(range(1, 11))
                payload = self.license_payload(
                    run_plan, license_id, slots=slots, max_workers=10
                )
                payload["concurrency_policy"] = (
                    category_image_production.FIXED_TEN_CONCURRENCY_POLICY
                )
                category_image_production.write_new_license(target_license, payload)

                validated = category_image_production.validate_license(
                    target_license, run_plan, CONFIG, slots, 10
                )
                self.assertEqual(
                    validated["concurrency_policy"],
                    category_image_production.FIXED_TEN_CONCURRENCY_POLICY,
                )

                invalid_path = root / "invalid-fixed-ten.json"
                invalid_payload = deepcopy(payload)
                invalid_payload["max_workers"] = 9
                invalid_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "固定10路许可证"):
                    category_image_production.validate_license(
                        invalid_path, run_plan, CONFIG, slots, 9
                    )

    def test_validate_retry_license_binds_double_request_budget(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 1)
                run_plan = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                )
                license_id = "pipe-retry-validation-test"
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 1, license_id
                )
                payload = self.license_payload(
                    run_plan,
                    license_id,
                    slots=[1],
                    max_workers=1,
                    max_attempts=2,
                )
                category_image_production.write_new_license(target_license, payload)

                validated = category_image_production.validate_license(
                    target_license, run_plan, CONFIG, [1], 1
                )
                self.assertEqual(validated["max_attempts"], 2)
                self.assertEqual(
                    validated["approved_request_budget"],
                    run_plan["pending_api_requests"] * 2,
                )

                invalid_path = root / "invalid-retry-budget.json"
                invalid_payload = deepcopy(payload)
                invalid_payload["approved_request_budget"] -= 1
                invalid_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "待 API 目标数乘以"):
                    category_image_production.validate_license(
                        invalid_path, run_plan, CONFIG, [1], 1
                    )

    def test_details_worker_uses_first_key_respects_worker_limit_and_output_events(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "pipe_unclogging"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 1)
                run_plan = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                license_id = "pipe-worker-test"
                category_image_production.write_production_files(run_plan, PHONE, license_id)
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 1, license_id
                )
                payload = self.license_payload(
                    run_plan, license_id, slots=[1, 2], max_workers=1
                )
                category_image_production.write_new_license(target_license, payload)
                job_dir = category_image_production.jobs_dir(batch_dir)
                job_dir.mkdir(parents=True)
                job_path = job_dir / "pipe-worker-job.json"
                job_path.write_text(
                    json.dumps({"job_id": "pipe-worker-job", "license_id": license_id}),
                    encoding="utf-8",
                )
                first_client, second_client = object(), object()
                used_clients: list[object] = []

                def fake_generate(client: object, config: dict, prompt: str) -> bytes:
                    del config, prompt
                    used_clients.append(client)
                    return b"not-written"

                args = Namespace(
                    category="pipe_unclogging",
                    batch_dir=str(batch_dir),
                    group_start=1,
                    group_count=1,
                    license=str(target_license),
                    job_file=str(job_path),
                    scope="details",
                    output_root=str(formal_root),
                    license_id=license_id,
                    max_workers=1,
                )
                with (
                    patch.object(category_image_production.image_generate, "load_json", return_value=CONFIG),
                    patch.object(category_image_production.image_generate, "apply_provider_config", return_value=CONFIG),
                    patch.object(
                        category_image_production,
                        "openai_clients_by_slot",
                        return_value=[(1, first_client), (2, second_client)],
                    ),
                    patch.object(category_image_production, "_font", return_value=None),
                    patch.object(category_image_production.image_generate, "generate_one", side_effect=fake_generate),
                    patch.object(category_image_production, "save_raw_png"),
                    patch.object(category_image_production, "apply_overlays"),
                    patch.object(category_image_production, "write_production_summary"),
                ):
                    result = category_image_production.run(args)

                events_path = (
                    category_image_production.production_dir(batch_dir)
                    / "events_pipe-worker-job.jsonl"
                )
                events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
                generated_events = [
                    event for event in events if event.get("status") == "generated"
                ]

        self.assertEqual(result, 1)  # No fake PNGs were persisted, so final integrity check fails.
        self.assertEqual(len(used_clients), 6)
        self.assertTrue(all(client is first_client for client in used_clients))
        self.assertTrue(
            all(
                event["delivery_target"].startswith("output/pipe_unclogging/")
                for event in generated_events
            )
        )
        self.assertTrue(
            all(
                event["raw_target"].startswith("raw/group_0001/")
                for event in generated_events
            )
        )

    def test_request_budget_guard_is_hard(self) -> None:
        self.assertEqual(category_image_production.reserve_request(0, 1), 1)
        with self.assertRaises(RuntimeError):
            category_image_production.reserve_request(1, 1)

    def test_request_error_classification_and_content_policy_prompt(self) -> None:
        self.assertEqual(
            category_image_production.classify_request_error(
                RuntimeError("Connection error")
            ),
            "transient",
        )
        self.assertEqual(
            category_image_production.classify_request_error(
                RuntimeError("content_policy_violation")
            ),
            "content_policy",
        )
        self.assertEqual(
            category_image_production.classify_request_error(
                RuntimeError(
                    "Error code: 403 - {'code': 'INSUFFICIENT_BALANCE', "
                    "'message': 'Insufficient account balance'}"
                )
            ),
            "balance_exhausted",
        )
        self.assertEqual(
            category_image_production.classify_request_error(
                RuntimeError(
                    "Error code: 403 - {'error': {'message': "
                    "'insufficient balance', 'type': 'billing_error'}}"
                )
            ),
            "balance_exhausted",
        )
        self.assertIsNone(
            category_image_production.classify_request_error(
                RuntimeError(
                    "Error code: 403 - {'error': {'message': "
                    "'account disabled', 'type': 'billing_error'}}"
                )
            )
        )
        self.assertIsNone(
            category_image_production.classify_request_error(
                RuntimeError(
                    "Error code: 400 - {'error': {'message': "
                    "'insufficient balance', 'type': 'billing_error'}}"
                )
            )
        )
        self.assertEqual(
            category_image_production.classify_request_error(
                RuntimeError(
                    "您的请求无法用于生成图像。该请求可能因安全政策被拦截，或不适合进行图像生成。"
                )
            ),
            "content_policy",
        )
        self.assertIsNone(
            category_image_production.classify_request_error(
                RuntimeError("invalid local image dimensions")
            )
        )
        original = "送油救援，合规油桶。无血腥画面、危险站位和违规占道。"
        retried = category_image_production.content_policy_retry_prompt(original)
        self.assertIn("送油救援", retried)
        self.assertIn("合规油桶", retried)
        self.assertIn("内容安全重试说明", retried)
        self.assertIn("日常本地生活服务工作记录", retried)
        self.assertNotIn("血腥", retried)

    def test_truck_content_policy_safe_v2_covers_six_positive_roles(self) -> None:
        role_keywords = {
            "货车没油救援": ("油表", "燃油", "输油软管"),
            "货车爆胎救援": ("爆裂轮胎", "轮辋", "更换方案"),
            "货车换轮胎": ("旧车轮", "备胎", "紧固螺母"),
            "货车发动机故障": ("故障码", "启动回路", "线束连接"),
            "卡车搭电": ("额定电压", "辅助电源", "跨接线"),
            "货车刹车故障": ("制动压力", "管路连接", "轮端制动部件"),
        }
        forbidden = (
            "伤害",
            "不安全",
            "冲突",
            "LONG_ENGLISH_NEGATIVE_PROMPT",
            "严格排除",
            "不",
            "无",
        )
        for index, (role, expected_keywords) in enumerate(
            role_keywords.items()
        ):
            with self.subTest(role=role):
                generation_kind = "triptych_panel" if index < 3 else "detail"
                record = {
                    "category_id": "truck_rescue",
                    "generation_kind": generation_kind,
                    "service_role": role,
                    "scene": {
                        "vehicle": "中型载货货车",
                        "location": "物流园货车维修工位",
                        "action": "原动作含不表现冲突、伤害和不安全行为",
                        "tools": "轮挡、检修灯和货车专用工具",
                    },
                    "negative_prompt": "LONG_ENGLISH_NEGATIVE_PROMPT",
                    "prompt": "LONG_ENGLISH_NEGATIVE_PROMPT",
                }
                before = deepcopy(record)

                prepared, variant = (
                    category_image_production.content_policy_retry_for_record(
                        record, "LONG_ENGLISH_NEGATIVE_PROMPT"
                    )
                )

                self.assertEqual(record, before)
                self.assertEqual(variant, "content_policy_safe_v2_truck")
                self.assertIn(role, prepared)
                self.assertIn("中型载货货车", prepared)
                self.assertIn("物流园货车维修工位", prepared)
                self.assertIn("轮挡、检修灯和货车专用工具", prepared)
                for keyword in expected_keywords:
                    self.assertIn(keyword, prepared)
                for term in forbidden:
                    self.assertNotIn(term, prepared)
                self.assertIsNone(re.search(r"[A-Za-z]{2,}", prepared))
                self.assertLess(len(prepared), 500)
                if generation_kind == "triptych_panel":
                    self.assertIn("三拼图的一个独立面板", prepared)
                    self.assertIn("四周保留可裁切背景", prepared)
                else:
                    self.assertIn("画面中部横向区域", prepared)
                    self.assertIn("本地添加服务标签、电话和服务词", prepared)

    def test_non_truck_details_and_truck_cover_keep_content_policy_safe_v1(self) -> None:
        original = "送油救援，合规油桶。无血腥画面、危险站位和违规占道。"
        expected = category_image_production.content_policy_retry_prompt(original)
        for record in (
            {"category_id": "pipe_unclogging", "generation_kind": "detail"},
            {"category_id": "truck_rescue", "generation_kind": "cover"},
        ):
            with self.subTest(record=record):
                prepared, variant = (
                    category_image_production.content_policy_retry_for_record(
                        record, original
                    )
                )
                self.assertEqual(prepared, expected)
                self.assertEqual(variant, "content_policy_safe_v1")

    def test_worker_retries_transient_failure_once_within_license_budget(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "pipe_unclogging"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 1)
                run_plan = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                license_id = "pipe-worker-retry-test"
                category_image_production.write_production_files(
                    run_plan, PHONE, license_id
                )
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 1, license_id
                )
                payload = self.license_payload(
                    run_plan,
                    license_id,
                    slots=[1],
                    max_workers=1,
                    max_attempts=2,
                )
                category_image_production.write_new_license(target_license, payload)
                job_dir = category_image_production.jobs_dir(batch_dir)
                job_dir.mkdir(parents=True)
                job_path = job_dir / "pipe-worker-retry-job.json"
                job_path.write_text(
                    json.dumps(
                        {"job_id": "pipe-worker-retry-job", "license_id": license_id}
                    ),
                    encoding="utf-8",
                )
                calls: list[str] = []

                def fake_generate(_client: object, _config: dict, prompt: str) -> bytes:
                    calls.append(prompt)
                    if len(calls) == 1:
                        raise RuntimeError("Connection error")
                    return b"not-written"

                args = Namespace(
                    category="pipe_unclogging",
                    batch_dir=str(batch_dir),
                    group_start=1,
                    group_count=1,
                    license=str(target_license),
                    job_file=str(job_path),
                    scope="details",
                    output_root=str(formal_root),
                    license_id=license_id,
                    max_workers=1,
                )
                with (
                    patch.object(
                        category_image_production.image_generate,
                        "load_json",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production.image_generate,
                        "apply_provider_config",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production,
                        "openai_clients_by_slot",
                        return_value=[(1, object())],
                    ),
                    patch.object(category_image_production, "_font", return_value=None),
                    patch.object(
                        category_image_production.image_generate,
                        "generate_one",
                        side_effect=fake_generate,
                    ),
                    patch.object(category_image_production, "save_raw_png"),
                    patch.object(category_image_production, "apply_overlays"),
                    patch.object(category_image_production, "write_production_summary"),
                    patch.object(category_image_production.time, "sleep"),
                ):
                    result = category_image_production.run(args)

                events_path = (
                    category_image_production.production_dir(batch_dir)
                    / "events_pipe-worker-retry-job.jsonl"
                )
                events = [
                    json.loads(line)
                    for line in events_path.read_text(encoding="utf-8").splitlines()
                ]
                failed_events = [
                    event for event in events if event.get("status") == "request_failed"
                ]
                generated_events = [
                    event for event in events if event.get("status") == "generated"
                ]
                job = category_image_production.load_json(job_path)

        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 7)
        self.assertEqual(len(failed_events), 1)
        self.assertTrue(failed_events[0]["will_retry"])
        self.assertEqual(failed_events[0]["attempt"], 1)
        self.assertEqual(generated_events[0]["attempt"], 2)
        self.assertEqual(job["requests_used"], 7)
        self.assertEqual(job["retry_count"], 1)
        self.assertEqual(job["failed"], 0)

    def test_worker_persists_request_reservation_before_api_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "pipe_unclogging"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 1)
                run_plan = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                license_id = "pipe-worker-reservation-crash-test"
                category_image_production.write_production_files(
                    run_plan, PHONE, license_id
                )
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 1, license_id
                )
                payload = self.license_payload(run_plan, license_id)
                category_image_production.write_new_license(target_license, payload)
                job_dir = category_image_production.jobs_dir(batch_dir)
                job_dir.mkdir(parents=True)
                job_id = "pipe-worker-reservation-crash-job"
                job_path = job_dir / f"{job_id}.json"
                job_path.write_text(
                    json.dumps({"job_id": job_id, "license_id": license_id}),
                    encoding="utf-8",
                )
                events_path = (
                    category_image_production.production_dir(batch_dir)
                    / f"events_{job_id}.jsonl"
                )
                visible_during_api: list[dict] = []
                license_visible_during_api: list[dict] = []
                attempted_prompts: list[str] = []

                def crash_after_reservation(
                    _client: object, _config: dict, prompt: str
                ) -> bytes:
                    attempted_prompts.append(prompt)
                    visible_during_api.extend(
                        json.loads(line)
                        for line in events_path.read_text(encoding="utf-8").splitlines()
                    )
                    license_visible_during_api.append(
                        category_image_production.load_json(target_license)
                    )
                    raise KeyboardInterrupt("simulated process crash")

                args = Namespace(
                    category="pipe_unclogging",
                    batch_dir=str(batch_dir),
                    group_start=1,
                    group_count=1,
                    license=str(target_license),
                    job_file=str(job_path),
                    scope="details",
                    output_root=str(formal_root),
                    license_id=license_id,
                    max_workers=1,
                )
                with (
                    patch.object(
                        category_image_production.image_generate,
                        "load_json",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production.image_generate,
                        "apply_provider_config",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production,
                        "openai_clients_by_slot",
                        return_value=[(1, object())],
                    ),
                    patch.object(category_image_production, "_font", return_value=None),
                    patch.object(
                        category_image_production.image_generate,
                        "generate_one",
                        side_effect=crash_after_reservation,
                    ),
                    patch.object(category_image_production, "save_raw_png"),
                    patch.object(category_image_production, "apply_overlays"),
                    patch.object(category_image_production, "write_production_summary"),
                ):
                    with self.assertRaisesRegex(
                        KeyboardInterrupt, "simulated process crash"
                    ):
                        category_image_production.run(args)

                persisted_events = [
                    json.loads(line)
                    for line in events_path.read_text(encoding="utf-8").splitlines()
                ]
                license_after_crash = category_image_production.load_json(
                    target_license
                )

        self.assertEqual(len(attempted_prompts), 1)
        self.assertEqual(visible_during_api, persisted_events)
        self.assertEqual(license_visible_during_api[0]["requests_used"], 1)
        self.assertEqual(len(persisted_events), 1)
        reservation = persisted_events[0]
        self.assertEqual(reservation["status"], "request_reserved")
        self.assertEqual(reservation["request_number"], 1)
        self.assertEqual(reservation["attempt"], 1)
        self.assertEqual(reservation["retry_prompt_variant"], "original")
        self.assertEqual(reservation["api_key_slot"], 1)
        self.assertEqual(
            reservation["generation_target_id"],
            run_plan["pending_records"][0]["generation_target_id"],
        )
        self.assertTrue(reservation["raw_target"].startswith("raw/group_0001/"))
        self.assertTrue(
            reservation["delivery_target"].startswith(
                "output/pipe_unclogging/group_0001/"
            )
        )
        self.assertEqual(
            reservation["effective_prompt_sha256"],
            hashlib.sha256(attempted_prompts[0].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(license_after_crash["requests_used"], 1)

    def test_reservation_event_failure_prevents_license_count_and_api_call(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "pipe_unclogging"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 1)
                run_plan = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                license_id = "pipe-worker-reservation-write-failure-test"
                category_image_production.write_production_files(
                    run_plan, PHONE, license_id
                )
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 1, license_id
                )
                payload = self.license_payload(run_plan, license_id)
                category_image_production.write_new_license(target_license, payload)
                job_dir = category_image_production.jobs_dir(batch_dir)
                job_dir.mkdir(parents=True)
                job_path = job_dir / "pipe-worker-reservation-write-failure-job.json"
                job_path.write_text(
                    json.dumps(
                        {
                            "job_id": "pipe-worker-reservation-write-failure-job",
                            "license_id": license_id,
                        }
                    ),
                    encoding="utf-8",
                )
                args = Namespace(
                    category="pipe_unclogging",
                    batch_dir=str(batch_dir),
                    group_start=1,
                    group_count=1,
                    license=str(target_license),
                    job_file=str(job_path),
                    scope="details",
                    output_root=str(formal_root),
                    license_id=license_id,
                    max_workers=1,
                )
                with (
                    patch.object(
                        category_image_production.image_generate,
                        "load_json",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production.image_generate,
                        "apply_provider_config",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production,
                        "openai_clients_by_slot",
                        return_value=[(1, object())],
                    ),
                    patch.object(category_image_production, "_font", return_value=None),
                    patch.object(
                        category_image_production,
                        "append_event",
                        side_effect=OSError("reservation ledger unavailable"),
                    ),
                    patch.object(
                        category_image_production.image_generate, "generate_one"
                    ) as api_call,
                    patch.object(category_image_production, "write_production_summary"),
                ):
                    with self.assertRaisesRegex(
                        OSError, "reservation ledger unavailable"
                    ):
                        category_image_production.run(args)

                license_after_failure = category_image_production.load_json(
                    target_license
                )

        api_call.assert_not_called()
        self.assertEqual(license_after_failure["requests_used"], 0)

    def test_truck_safe_v2_retry_variant_is_persisted_before_retry_api_call(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "truck_rescue"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_truck_v3_batch(root)
                run_plan = category_image_production.plan(
                    "truck_rescue",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                license_id = "truck-worker-safe-v2-event-test"
                category_image_production.write_production_files(
                    run_plan, PHONE, license_id
                )
                target_license = category_image_production.license_path(
                    "truck_rescue", batch_dir, 1, 1, license_id
                )
                payload = self.license_payload(
                    run_plan, license_id, max_attempts=2
                )
                category_image_production.write_new_license(target_license, payload)
                job_dir = category_image_production.jobs_dir(batch_dir)
                job_dir.mkdir(parents=True)
                job_id = "truck-worker-safe-v2-event-job"
                job_path = job_dir / f"{job_id}.json"
                job_path.write_text(
                    json.dumps({"job_id": job_id, "license_id": license_id}),
                    encoding="utf-8",
                )
                events_path = (
                    category_image_production.production_dir(batch_dir)
                    / f"events_{job_id}.jsonl"
                )
                calls: list[str] = []
                retry_event_visible_at_api: list[dict] = []

                def fail_once_then_succeed(
                    _client: object, _config: dict, prompt: str
                ) -> bytes:
                    calls.append(prompt)
                    if len(calls) == 1:
                        raise RuntimeError("content_policy_violation")
                    if len(calls) == 2:
                        retry_event_visible_at_api.extend(
                            json.loads(line)
                            for line in events_path.read_text(
                                encoding="utf-8"
                            ).splitlines()
                            if json.loads(line).get("status") == "request_reserved"
                        )
                    return b"not-written"

                args = Namespace(
                    category="truck_rescue",
                    batch_dir=str(batch_dir),
                    group_start=1,
                    group_count=1,
                    license=str(target_license),
                    job_file=str(job_path),
                    scope="details",
                    output_root=str(formal_root),
                    license_id=license_id,
                    max_workers=1,
                )
                with (
                    patch.object(
                        category_image_production.image_generate,
                        "load_json",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production.image_generate,
                        "apply_provider_config",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production,
                        "openai_clients_by_slot",
                        return_value=[(1, object())],
                    ),
                    patch.object(category_image_production, "_font", return_value=None),
                    patch.object(
                        category_image_production.image_generate,
                        "generate_one",
                        side_effect=fail_once_then_succeed,
                    ),
                    patch.object(category_image_production, "save_raw_png"),
                    patch.object(category_image_production, "apply_overlays"),
                    patch.object(category_image_production, "write_production_summary"),
                    patch.object(category_image_production.time, "sleep"),
                ):
                    result = category_image_production.run(args)

                reservations = [
                    event
                    for event in (
                        json.loads(line)
                        for line in events_path.read_text(
                            encoding="utf-8"
                        ).splitlines()
                    )
                    if event.get("status") == "request_reserved"
                ]

        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 7)
        self.assertEqual(len(retry_event_visible_at_api), 2)
        retry_reservation = retry_event_visible_at_api[1]
        self.assertEqual(retry_reservation["attempt"], 2)
        self.assertEqual(
            retry_reservation["retry_prompt_variant"],
            "content_policy_safe_v2_truck",
        )
        self.assertEqual(
            retry_reservation["effective_prompt_sha256"],
            hashlib.sha256(calls[1].encode("utf-8")).hexdigest(),
        )
        self.assertNotIn("LONG_ENGLISH_NEGATIVE_PROMPT", calls[1])
        self.assertEqual(
            sum(
                event["retry_prompt_variant"] == "content_policy_safe_v2_truck"
                for event in reservations
            ),
            1,
        )

    def test_worker_stops_after_stage_content_policy_double_rejection_storm(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "pipe_unclogging"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 1)
                run_plan = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                license_id = "pipe-worker-policy-breaker-test"
                category_image_production.write_production_files(
                    run_plan, PHONE, license_id
                )
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 1, license_id
                )
                payload = self.license_payload(
                    run_plan,
                    license_id,
                    slots=[1, 2, 3, 4],
                    max_workers=4,
                    max_attempts=2,
                )
                category_image_production.write_new_license(target_license, payload)
                job_dir = category_image_production.jobs_dir(batch_dir)
                job_dir.mkdir(parents=True)
                job_path = job_dir / "pipe-worker-policy-breaker-job.json"
                job_path.write_text(
                    json.dumps(
                        {
                            "job_id": "pipe-worker-policy-breaker-job",
                            "license_id": license_id,
                        }
                    ),
                    encoding="utf-8",
                )
                calls: list[str] = []

                def fake_generate(
                    _client: object, _config: dict, prompt: str
                ) -> bytes:
                    calls.append(prompt)
                    if len(calls) == 1:
                        return b"probe-success"
                    raise RuntimeError("content_policy_violation")

                args = Namespace(
                    category="pipe_unclogging",
                    batch_dir=str(batch_dir),
                    group_start=1,
                    group_count=1,
                    license=str(target_license),
                    job_file=str(job_path),
                    scope="details",
                    output_root=str(formal_root),
                    license_id=license_id,
                    max_workers=4,
                )
                with (
                    patch.object(
                        category_image_production.image_generate,
                        "load_json",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production.image_generate,
                        "apply_provider_config",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production,
                        "openai_clients_by_slot",
                        return_value=[
                            (1, object()),
                            (2, object()),
                            (3, object()),
                            (4, object()),
                        ],
                    ),
                    patch.object(category_image_production, "_font", return_value=None),
                    patch.object(
                        category_image_production.image_generate,
                        "generate_one",
                        side_effect=fake_generate,
                    ),
                    patch.object(category_image_production, "save_raw_png"),
                    patch.object(category_image_production, "apply_overlays"),
                    patch.object(category_image_production, "write_production_summary"),
                    patch.object(category_image_production.time, "sleep"),
                ):
                    result = category_image_production.run(args)

                events_path = (
                    category_image_production.production_dir(batch_dir)
                    / "events_pipe-worker-policy-breaker-job.jsonl"
                )
                events = [
                    json.loads(line)
                    for line in events_path.read_text(encoding="utf-8").splitlines()
                ]
                adaptive_stages = [
                    event
                    for event in events
                    if event.get("status") == "concurrency_stage"
                    and event.get("phase") == "adaptive"
                ]
                final_policy_failures = [
                    event
                    for event in events
                    if event.get("status") == "request_failed"
                    and event.get("error_kind") == "content_policy"
                    and event.get("will_retry") is False
                ]
                reservations = [
                    event
                    for event in events
                    if event.get("status") == "request_reserved"
                ]
                job = category_image_production.load_json(job_path)

        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 9)
        self.assertEqual(len(reservations), 9)
        self.assertEqual(
            sorted(event["request_number"] for event in reservations),
            list(range(1, 10)),
        )
        self.assertEqual(
            sum(
                event["retry_prompt_variant"] == "content_policy_safe_v1"
                for event in reservations
            ),
            4,
        )
        self.assertTrue(
            all(len(event["effective_prompt_sha256"]) == 64 for event in reservations)
        )
        self.assertEqual(len(final_policy_failures), 4)
        self.assertEqual(len(adaptive_stages), 1)
        self.assertTrue(adaptive_stages[0]["circuit_breaker_triggered"])
        self.assertEqual(
            adaptive_stages[0]["content_policy_double_failure_count"], 4
        )
        self.assertEqual(
            adaptive_stages[0]["content_policy_double_failure_rate"], 1.0
        )
        self.assertTrue(job["content_policy_circuit_breaker_triggered"])
        self.assertEqual(job["requests_used"], 9)
        self.assertEqual(job["retry_count"], 4)
        self.assertEqual(job["failed"], 4)

    def test_worker_quarantines_balance_slot_and_requeues_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            formal_root = root / "output" / "pipe_unclogging"
            with (
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "ROOT", root),
            ):
                batch_dir = self.make_v2_batch(root, 1)
                run_plan = category_image_production.plan(
                    "pipe_unclogging",
                    batch_dir,
                    1,
                    1,
                    PHONE,
                    CONFIG,
                    scope="details",
                    output_root=formal_root,
                )
                license_id = "pipe-worker-balance-breaker-test"
                category_image_production.write_production_files(
                    run_plan, PHONE, license_id
                )
                target_license = category_image_production.license_path(
                    "pipe_unclogging", batch_dir, 1, 1, license_id
                )
                payload = self.license_payload(
                    run_plan,
                    license_id,
                    slots=[1, 2, 3, 4],
                    max_workers=4,
                    max_attempts=2,
                )
                category_image_production.write_new_license(target_license, payload)
                job_dir = category_image_production.jobs_dir(batch_dir)
                job_dir.mkdir(parents=True)
                job_path = job_dir / "pipe-worker-balance-breaker-job.json"
                job_path.write_text(
                    json.dumps(
                        {
                            "job_id": "pipe-worker-balance-breaker-job",
                            "license_id": license_id,
                        }
                    ),
                    encoding="utf-8",
                )
                calls: list[str] = []
                call_lock = threading.Lock()

                def fake_generate(
                    _client: object, _config: dict, prompt: str
                ) -> bytes:
                    with call_lock:
                        calls.append(prompt)
                        call_number = len(calls)
                    if call_number == 2:
                        raise RuntimeError(
                            "Error code: 403 - {'error': {'message': "
                            "'insufficient balance', 'type': 'billing_error'}}"
                        )
                    return b"provider-success"

                args = Namespace(
                    category="pipe_unclogging",
                    batch_dir=str(batch_dir),
                    group_start=1,
                    group_count=1,
                    license=str(target_license),
                    job_file=str(job_path),
                    scope="details",
                    output_root=str(formal_root),
                    license_id=license_id,
                    max_workers=4,
                )
                with (
                    patch.object(
                        category_image_production.image_generate,
                        "load_json",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production.image_generate,
                        "apply_provider_config",
                        return_value=CONFIG,
                    ),
                    patch.object(
                        category_image_production,
                        "openai_clients_by_slot",
                        return_value=[
                            (1, object()),
                            (2, object()),
                            (3, object()),
                            (4, object()),
                        ],
                    ),
                    patch.object(category_image_production, "_font", return_value=None),
                    patch.object(
                        category_image_production.image_generate,
                        "generate_one",
                        side_effect=fake_generate,
                    ),
                    patch.object(category_image_production, "save_raw_png"),
                    patch.object(category_image_production, "_materialize_delivery"),
                    patch.object(category_image_production, "write_production_summary"),
                ):
                    result = category_image_production.run(args)

                events_path = (
                    category_image_production.production_dir(batch_dir)
                    / "events_pipe-worker-balance-breaker-job.jsonl"
                )
                events = [
                    json.loads(line)
                    for line in events_path.read_text(encoding="utf-8").splitlines()
                ]
                reservations = [
                    event
                    for event in events
                    if event.get("status") == "request_reserved"
                ]
                terminals = [
                    event
                    for event in events
                    if event.get("status") in {"generated", "request_failed"}
                ]
                terminal_by_target_attempt = {
                    (event["generation_target_id"], event["attempt"]): event
                    for event in terminals
                }
                adaptive_stages = [
                    event
                    for event in events
                    if event.get("status") == "concurrency_stage"
                    and event.get("phase") == "adaptive"
                ]
                balance_failures = [
                    event
                    for event in terminals
                    if event.get("status") == "request_failed"
                    and event.get("error_kind") == "balance_exhausted"
                ]
                job = category_image_production.load_json(job_path)

        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 7)
        self.assertEqual(len(reservations), 7)
        self.assertEqual(len(terminals), 7)
        for reservation in reservations:
            terminal = terminal_by_target_attempt[
                (reservation["generation_target_id"], reservation["attempt"])
            ]
            self.assertEqual(
                terminal["request_number"], reservation["request_number"]
            )
        self.assertEqual(len(balance_failures), 1)
        self.assertFalse(balance_failures[0]["will_retry"])
        self.assertTrue(balance_failures[0]["api_key_failover_eligible"])
        self.assertEqual(len(adaptive_stages), 2)
        self.assertEqual(adaptive_stages[0]["request_count"], 4)
        self.assertEqual(adaptive_stages[0]["dispatched_target_count"], 4)
        self.assertEqual(adaptive_stages[0]["drained_result_count"], 4)
        self.assertTrue(adaptive_stages[0]["in_flight_drained"])
        self.assertEqual(adaptive_stages[0]["balance_exhausted_count"], 1)
        self.assertFalse(adaptive_stages[0]["balance_circuit_breaker_triggered"])
        self.assertFalse(adaptive_stages[0]["circuit_breaker_triggered"])
        self.assertEqual(
            adaptive_stages[0]["balance_failover_target_count"], 1
        )
        self.assertEqual(len(adaptive_stages[0]["quarantined_api_key_slots"]), 1)
        self.assertEqual(adaptive_stages[0]["remaining_api_key_slot_count"], 3)
        self.assertNotIn("balance_circuit_breaker_triggered", job)
        self.assertEqual(len(job["quarantined_api_key_slots"]), 1)
        self.assertEqual(job["api_key_failover_count"], 1)
        self.assertEqual(job["requests_used"], 7)
        self.assertEqual(job["retry_count"], 0)
        self.assertEqual(job["failed"], 0)

    def test_adaptive_concurrency_ramps_to_ten(self) -> None:
        records = [{"id": index} for index in range(38)]
        clients = [(index, object()) for index in range(1, 11)]
        attempted: list[int] = []

        def run_one(_slot: int, _client: object, record: dict) -> bool:
            attempted.append(record["id"])
            return True

        history = category_image_production.run_adaptive_request_batches(
            records, clients, 10, run_one
        )

        self.assertEqual(
            [stage["worker_count"] for stage in history],
            [4, 6, 8, 10, 10],
        )
        self.assertEqual(sorted(attempted), list(range(38)))

    def test_adaptive_concurrency_degrades_without_retrying_failures(self) -> None:
        records = [{"id": index} for index in range(20)]
        clients = [(index, object()) for index in range(1, 11)]
        attempted: list[int] = []

        def run_one(_slot: int, _client: object, record: dict) -> bool:
            attempted.append(record["id"])
            return record["id"] != 5

        history = category_image_production.run_adaptive_request_batches(
            records, clients, 10, run_one
        )

        self.assertEqual(
            [stage["worker_count"] for stage in history],
            [4, 6, 5, 5],
        )
        self.assertEqual([stage["failed_count"] for stage in history], [0, 1, 0, 0])
        self.assertEqual(sorted(attempted), list(range(20)))
        self.assertEqual(len(attempted), len(set(attempted)))

    def test_adaptive_content_policy_failure_storm_stops_future_stages(self) -> None:
        records = [{"id": index} for index in range(12)]
        clients = [(index, object()) for index in range(1, 5)]
        attempted: list[int] = []

        def run_one(
            _slot: int, _client: object, record: dict
        ) -> bool | category_image_production.RequestBatchResult:
            attempted.append(record["id"])
            if record["id"] in {0, 1}:
                return category_image_production.RequestBatchResult(
                    success=False,
                    final_error_kind="content_policy",
                    attempt_count=2,
                    content_policy_rejection_count=2,
                )
            return True

        history = category_image_production.run_adaptive_request_batches(
            records, clients, 4, run_one
        )

        self.assertEqual(sorted(attempted), [0, 1, 2, 3])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["failed_count"], 2)
        self.assertEqual(history[0]["content_policy_double_failure_count"], 2)
        self.assertEqual(history[0]["content_policy_double_failure_rate"], 0.5)
        self.assertTrue(history[0]["circuit_breaker_triggered"])

    def test_adaptive_balance_failure_drains_stage_and_stops_future_stages(self) -> None:
        records = [{"id": index} for index in range(12)]
        clients = [(index, object()) for index in range(1, 5)]
        attempted: list[int] = []

        def run_one(
            _slot: int, _client: object, record: dict
        ) -> bool | category_image_production.RequestBatchResult:
            attempted.append(record["id"])
            if record["id"] == 0:
                return category_image_production.RequestBatchResult(
                    success=False,
                    final_error_kind="balance_exhausted",
                )
            return True

        history = category_image_production.run_adaptive_request_batches(
            records, clients, 4, run_one
        )

        self.assertEqual(sorted(attempted), [0, 1, 2, 3])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["dispatched_target_count"], 4)
        self.assertEqual(history[0]["drained_result_count"], 4)
        self.assertTrue(history[0]["in_flight_drained"])
        self.assertEqual(history[0]["balance_exhausted_count"], 1)
        self.assertTrue(history[0]["balance_circuit_breaker_triggered"])
        self.assertFalse(history[0]["circuit_breaker_triggered"])

    def test_content_policy_circuit_breaker_ignores_below_half_stage(self) -> None:
        records = [{"id": index} for index in range(20)]
        clients = [(index, object()) for index in range(1, 11)]
        attempted: list[int] = []

        def run_one(
            _slot: int, _client: object, record: dict
        ) -> bool | category_image_production.RequestBatchResult:
            attempted.append(record["id"])
            if record["id"] in {0, 1}:
                return category_image_production.RequestBatchResult(
                    success=False,
                    final_error_kind="content_policy",
                    attempt_count=2,
                    content_policy_rejection_count=2,
                )
            return True

        history = category_image_production.run_fixed_request_batches(
            records, clients, 10, run_one
        )

        self.assertEqual(sorted(attempted), list(range(20)))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["content_policy_double_failure_count"], 2)
        self.assertEqual(history[0]["content_policy_double_failure_rate"], 0.2)
        self.assertFalse(history[0]["circuit_breaker_triggered"])

    def test_fixed_ten_concurrency_does_not_downshift_or_retry(self) -> None:
        records = [{"id": index} for index in range(25)]
        clients = [(index, object()) for index in range(1, 11)]
        attempted: list[int] = []

        def run_one(_slot: int, _client: object, record: dict) -> bool:
            attempted.append(record["id"])
            return record["id"] not in {2, 13, 21}

        history = category_image_production.run_fixed_request_batches(
            records, clients, 10, run_one
        )

        self.assertEqual(
            [stage["worker_count"] for stage in history],
            [10, 10, 5],
        )
        self.assertEqual(
            [stage["failed_count"] for stage in history],
            [1, 1, 1],
        )
        self.assertEqual(sorted(attempted), list(range(25)))
        self.assertEqual(len(attempted), len(set(attempted)))

    def test_fixed_content_policy_failure_storm_stops_future_stages(self) -> None:
        records = [{"id": index} for index in range(25)]
        clients = [(index, object()) for index in range(1, 11)]
        attempted: list[int] = []

        def run_one(
            _slot: int, _client: object, record: dict
        ) -> bool | category_image_production.RequestBatchResult:
            attempted.append(record["id"])
            if record["id"] < 5:
                return category_image_production.RequestBatchResult(
                    success=False,
                    final_error_kind="content_policy",
                    attempt_count=2,
                    content_policy_rejection_count=2,
                )
            return True

        history = category_image_production.run_fixed_request_batches(
            records, clients, 10, run_one
        )

        self.assertEqual(sorted(attempted), list(range(10)))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["failed_count"], 5)
        self.assertEqual(history[0]["content_policy_double_failure_count"], 5)
        self.assertEqual(history[0]["content_policy_double_failure_rate"], 0.5)
        self.assertTrue(history[0]["circuit_breaker_triggered"])

    def test_fixed_balance_failure_drains_stage_and_stops_future_stages(self) -> None:
        records = [{"id": index} for index in range(25)]
        clients = [(index, object()) for index in range(1, 11)]
        attempted: list[int] = []

        def run_one(
            _slot: int, _client: object, record: dict
        ) -> bool | category_image_production.RequestBatchResult:
            attempted.append(record["id"])
            if record["id"] == 2:
                return category_image_production.RequestBatchResult(
                    success=False,
                    final_error_kind="balance_exhausted",
                )
            return True

        history = category_image_production.run_fixed_request_batches(
            records, clients, 10, run_one
        )

        self.assertEqual(sorted(attempted), list(range(10)))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["dispatched_target_count"], 10)
        self.assertEqual(history[0]["drained_result_count"], 10)
        self.assertTrue(history[0]["in_flight_drained"])
        self.assertEqual(history[0]["balance_exhausted_count"], 1)
        self.assertTrue(history[0]["balance_circuit_breaker_triggered"])
        self.assertFalse(history[0]["circuit_breaker_triggered"])


if __name__ == "__main__":
    unittest.main()
