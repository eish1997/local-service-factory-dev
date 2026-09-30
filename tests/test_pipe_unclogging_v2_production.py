from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tools import category_image_production as production


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_BATCH = (
    ROOT
    / "prompts"
    / "category_batches"
    / "pipe_unclogging"
    / "batch_v2_5_active"
)
OUTPUT_ROOT = ROOT / "output" / "pipe_unclogging"
PHONE = "13317112954"


def local_config() -> dict:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    config.update(
        {
            "provider": "official",
            "base_url": "",
            "model": "gpt-image-2",
            "quality": "medium",
            "api_size": "1024x1536",
        }
    )
    return config


def no_existing_plan(scope: str, group_count: int = 3) -> dict:
    with (
        patch.object(production, "reusable_target", return_value=False),
        patch.object(production, "valid_png", return_value=False),
        patch.object(production, "target_review_status", return_value=None),
    ):
        return production.plan(
            "pipe_unclogging",
            ACTIVE_BATCH,
            1,
            group_count,
            PHONE,
            local_config(),
            scope=scope,
            output_root=OUTPUT_ROOT,
        )


class PipeUncloggingV2ProductionTests(unittest.TestCase):
    def test_plan_separates_generation_requests_from_delivery_files(self) -> None:
        covers = no_existing_plan("covers")
        details = no_existing_plan("details")
        all_scope = no_existing_plan("all")

        self.assertEqual(
            (
                covers["total_generation_targets"],
                covers["total_delivery_targets"],
                covers["pending_api_requests"],
                covers["pending_delivery_count"],
            ),
            (3, 3, 3, 3),
        )
        self.assertEqual(
            (
                details["total_generation_targets"],
                details["total_delivery_targets"],
                details["pending_api_requests"],
                details["pending_delivery_count"],
            ),
            (18, 12, 18, 12),
        )
        self.assertEqual(
            (
                all_scope["total_generation_targets"],
                all_scope["total_delivery_targets"],
                all_scope["pending_api_requests"],
                all_scope["pending_delivery_count"],
            ),
            (21, 15, 21, 15),
        )
        self.assertEqual(
            [recipe["height_profile_id"] for recipe in all_scope["group_recipes"]],
            ["height_1408", "height_1472", "height_1536"],
        )
        self.assertEqual(
            [recipe["final_sizes"] for recipe in all_scope["group_recipes"]],
            [["1024x1408"], ["1024x1472"], ["1024x1536"]],
        )
        self.assertEqual(
            len(set(all_scope["generation_target_ids"])),
            len(all_scope["generation_target_ids"]),
        )
        self.assertEqual(
            len(set(all_scope["delivery_target_ids"])),
            len(all_scope["delivery_target_ids"]),
        )

    def test_plan_recovers_triptych_panels_locally_and_requests_only_missing_units(self) -> None:
        def three_panels_are_local(path: Path, _size: tuple[int, int]) -> bool:
            return "triptych_panel" in Path(path).name

        with (
            patch.object(production, "reusable_target", return_value=False),
            patch.object(production, "valid_png", side_effect=three_panels_are_local),
            patch.object(production, "target_review_status", return_value=None),
        ):
            plan = production.plan(
                "pipe_unclogging",
                ACTIVE_BATCH,
                1,
                1,
                PHONE,
                local_config(),
                scope="details",
                output_root=OUTPUT_ROOT,
            )
        self.assertEqual(plan["total_generation_targets"], 6)
        self.assertEqual(plan["total_delivery_targets"], 4)
        self.assertEqual(plan["recoverable_delivery_count"], 1)
        self.assertEqual(plan["pending_delivery_count"], 4)
        self.assertEqual(plan["pending_api_requests"], 3)

        def only_two_panels_are_local(path: Path, _size: tuple[int, int]) -> bool:
            return Path(path).name in {
                "u02_triptych_panel_1.png",
                "u03_triptych_panel_2.png",
            }

        with (
            patch.object(production, "reusable_target", return_value=False),
            patch.object(production, "valid_png", side_effect=only_two_panels_are_local),
            patch.object(production, "target_review_status", return_value=None),
        ):
            partial = production.plan(
                "pipe_unclogging",
                ACTIVE_BATCH,
                1,
                1,
                PHONE,
                local_config(),
                scope="details",
                output_root=OUTPUT_ROOT,
            )
        self.assertEqual(partial["recoverable_delivery_count"], 0)
        self.assertEqual(partial["pending_api_requests"], 4)

        with (
            patch.object(
                production,
                "reusable_target",
                side_effect=lambda path, _size: Path(path).name == "02_triptych.png",
            ),
            patch.object(production, "valid_png", return_value=False),
            patch.object(production, "target_review_status", return_value=None),
        ):
            final_exists = production.plan(
                "pipe_unclogging",
                ACTIVE_BATCH,
                1,
                1,
                PHONE,
                local_config(),
                scope="details",
                output_root=OUTPUT_ROOT,
            )
        self.assertEqual(final_exists["existing_delivery_count"], 1)
        self.assertEqual(final_exists["pending_delivery_count"], 3)
        self.assertEqual(final_exists["pending_api_requests"], 3)

    def test_height_tampering_is_rejected_before_a_plan_can_be_authorized(self) -> None:
        original = no_existing_plan("all", group_count=1)
        self.assertEqual(original["group_recipes"][0]["final_sizes"], ["1024x1408"])
        rows = copy.deepcopy(production.read_prompts(ACTIVE_BATCH))
        for row in rows:
            if int(row["group_index"]) == 1:
                row["height_profile_id"] = "height_1472"
                row["final_size"] = "1024x1472"
        with (
            patch.object(production, "read_prompts", return_value=rows),
            patch.object(production, "reusable_target", return_value=False),
            patch.object(production, "valid_png", return_value=False),
            patch.object(production, "target_review_status", return_value=None),
        ):
            with self.assertRaises(production.CategoryPromptError):
                production.plan(
                    "pipe_unclogging",
                    ACTIVE_BATCH,
                    1,
                    1,
                    PHONE,
                    local_config(),
                    scope="all",
                    output_root=OUTPUT_ROOT,
                )

    def test_triptych_is_composed_locally_and_records_three_component_fingerprints(self) -> None:
        records = production.record_targets(
            ACTIVE_BATCH,
            production.selected_records(ACTIVE_BATCH, 1, 1),
            OUTPUT_ROOT,
        )
        panel_records = [
            dict(record)
            for record in records
            if record["generation_kind"] == "triptych_panel"
        ]
        service_items = json.loads(
            (ROOT / "configs" / "categories" / "pipe_unclogging.json").read_text(
                encoding="utf-8-sig"
            )
        )["service_buttons"]
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            colors = [(190, 80, 50), (45, 140, 90), (55, 90, 175)]
            for record, color in zip(panel_records, colors):
                raw = temporary_root / Path(record["raw_target"]).name
                Image.new("RGB", (1024, 1536), color).save(raw, format="PNG")
                record["raw_target"] = str(raw)
            target = temporary_root / "02_triptych.png"
            validation = production.compose_triptych(
                panel_records,
                target,
                PHONE,
                service_items,
            )

            self.assertTrue(production.valid_png(target, (1024, 1408)))
            self.assertEqual(validation["role"], "triptych")
            self.assertEqual(validation["final_size"], "1024x1408")
            self.assertIn(f"电话：{PHONE}", validation["expected_text"])
            self.assertEqual(production.TRIPTYCH_SERVICE_SEPARATOR, " · ")
            self.assertEqual(production.TRIPTYCH_PANEL_ANCHOR_Y, 0.4)
            self.assertEqual(len(validation["panel_generation_target_ids"]), 3)
            self.assertEqual(len(validation["panel_fingerprints"]), 3)
            self.assertEqual(
                [row["panel_index"] for row in validation["panel_fingerprints"]],
                [1, 2, 3],
            )
            self.assertTrue(
                all(
                    len(row["fingerprint"]["scene_phash64"]) == 16
                    for row in validation["panel_fingerprints"]
                )
            )
            sidecar = json.loads(
                target.with_suffix(".validation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(sidecar["image_sha256"], validation["image_sha256"])

    def test_v3_license_fails_closed_when_structure_binding_is_missing(self) -> None:
        run_plan = no_existing_plan("covers", group_count=1)
        payload = {
            "status": "active",
            "kind": "category-image-production",
            "one_time": True,
            "production_schema_version": 3,
            "structure_version": run_plan["structure_version"],
            "generation_mode": run_plan["generation_mode"],
            "category_id": run_plan["category_id"],
            "batch_dir": run_plan["batch_dir"],
            "group_start": 1,
            "group_count": 1,
            "scope": "covers",
            "output_root": run_plan["output_root"],
            "manifest_sha256": run_plan["manifest_sha256"],
            "plan_sha256": run_plan["plan_sha256"],
            "generation_targets_sha256": run_plan["generation_targets_sha256"],
            "delivery_targets_sha256": run_plan["delivery_targets_sha256"],
            "pending_generation_targets_sha256": run_plan[
                "pending_generation_targets_sha256"
            ],
            "pending_delivery_targets_sha256": run_plan[
                "pending_delivery_targets_sha256"
            ],
            "group_recipes_sha256": run_plan["group_recipes_sha256"],
            "provider": "official",
            "base_url": "",
            "model": "gpt-image-2",
            "quality": "medium",
            "size": "1024x1536",
            "api_key_slots": [1],
            "max_attempts": 1,
            "sdk_max_retries": 0,
            "approved_generation_target_ids": run_plan[
                "pending_generation_target_ids"
            ],
            "approved_delivery_target_ids": run_plan[
                "pending_delivery_target_ids"
            ],
            "approved_api_request_count": 1,
            "approved_delivery_count": 1,
            "approved_image_count": 1,
            "approved_request_budget": 1,
            "max_workers": 1,
        }
        with tempfile.TemporaryDirectory() as temporary:
            license_path = Path(temporary) / "license.json"
            license_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            production.validate_license(
                license_path,
                run_plan,
                local_config(),
                [1],
                1,
            )
            del payload["structure_version"]
            license_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "structure_version"):
                production.validate_license(
                    license_path,
                    run_plan,
                    local_config(),
                    [1],
                    1,
                )


if __name__ == "__main__":
    unittest.main()
