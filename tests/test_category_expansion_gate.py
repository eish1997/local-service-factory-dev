from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import factory


class CategoryExpansionGateTests(unittest.TestCase):
    def test_cover_size_accepts_generation_kind_from_category_manifest(self) -> None:
        records = [
            {
                "group_index": 1,
                "generation_kind": "cover",
                "final_size": "1024x1536",
            },
            {
                "group_index": 1,
                "generation_kind": "detail",
                "final_size": "1024x1536",
            },
        ]
        with patch.object(factory, "_category_production_records", return_value=records):
            self.assertEqual(
                factory._category_cover_expected_size("pet_transport", 1),
                (1024, 1536),
            )

    def test_registered_exact_cover_range_can_enter_details(self) -> None:
        evidence = {
            "groups": [{"group_index": 1}, {"group_index": 2}],
            "sha256": "approved-range-sha",
        }
        registered = {
            "project_id": "pet_transport",
            "group_start": 1,
            "group_count": 2,
            "sha256": "approved-range-sha",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            approvals_dir = (
                root / "projects" / "pet_transport" / "groups" / "cover_approvals"
            )
            approvals_dir.mkdir(parents=True)
            approval_path = approvals_dir / "group_0001_0002_approved.json"
            approval_path.write_text(
                json.dumps(registered, ensure_ascii=False), encoding="utf-8"
            )
            with patch.object(factory, "ROOT", root):
                factory._category_require_registered_cover_approval(
                    "pet_transport", evidence
                )

    def test_historical_sample_phone_is_read_from_its_approval_record(self) -> None:
        validation = {
            "expected_text": [
                "电话：15377029700",
                "汽车救援",
                "联系电话：15377029700",
            ]
        }
        self.assertEqual(
            factory._category_validation_phone(validation, 316),
            "15377029700",
        )

    def test_historical_sample_rejects_mixed_approved_phone_numbers(self) -> None:
        validation = {
            "expected_text": [
                "电话：15377029700",
                "联系电话：19986904047",
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "没有唯一已批准手机号"):
            factory._category_validation_phone(validation, 316)

    def test_historical_sample_phone_accepts_canonical_400_hotline(self) -> None:
        validation = {
            "expected_text": [
                "电话：400-677-1311",
                "联系电话：400-677-1311",
            ]
        }
        self.assertEqual(
            factory._category_validation_phone(validation, 174),
            "400-677-1311",
        )

    def test_initial_sample_range_is_allowed_without_prior_approval(self) -> None:
        with patch.object(factory, "_category_sample_gate_range", return_value=(316, 3)):
            factory._category_sample_range("road_rescue", 316, 3)

    def test_expansion_is_blocked_until_sample_is_registered(self) -> None:
        with (
            patch.object(factory, "_category_sample_gate_range", return_value=(316, 3)),
            patch.object(
                factory,
                "_category_require_registered_cover_approval",
                side_effect=RuntimeError("missing sample approval"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "只允许先做第 316 至第 318 组"):
                factory._category_sample_range("road_rescue", 319, 10)

    def test_approved_sample_unlocks_only_complete_active_manifest_ranges(self) -> None:
        complete = [
            {"group_index": group_index, "position": position}
            for group_index in range(319, 329)
            for position in range(1, 6)
        ]
        definition = {"content_group": {"total_images": 5}}
        with (
            patch.object(factory, "_category_sample_gate_range", return_value=(316, 3)),
            patch.object(factory, "_category_require_registered_cover_approval"),
            patch.object(factory, "project_definition", return_value=definition),
            patch.object(factory, "_category_production_records", return_value=complete),
        ):
            factory._category_sample_range("road_rescue", 319, 10)

        with (
            patch.object(factory, "_category_sample_gate_range", return_value=(316, 3)),
            patch.object(factory, "_category_require_registered_cover_approval"),
            patch.object(factory, "project_definition", return_value=definition),
            patch.object(factory, "_category_production_records", return_value=complete[:-1]),
        ):
            with self.assertRaisesRegex(RuntimeError, "不在当前活动清单"):
                factory._category_sample_range("road_rescue", 319, 10)


if __name__ == "__main__":
    unittest.main()
