from __future__ import annotations

import json
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "projects" / "pipe_unclogging"
V2_DIR = PROJECT_DIR / "groups" / "schema_v2_5"
ACTIVE_BATCH = (
    ROOT
    / "prompts"
    / "category_batches"
    / "pipe_unclogging"
    / "batch_v2_5_active"
)
STRUCTURE_VERSION = "pipe_unclogging_v2_1cover_1triptych_3details"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


class PipeUncloggingV2ManifestTests(unittest.TestCase):
    def test_project_points_to_v2_without_erasing_legacy_history(self) -> None:
        project = load_json(PROJECT_DIR / "project.json")
        content = project["content_group"]
        self.assertEqual(content["structure_version"], STRUCTURE_VERSION)
        self.assertEqual(content["generation_mode"], "independent_triptych_panels")
        self.assertEqual(
            (
                content["cover_count"],
                content["triptych_count"],
                content["detail_count"],
                content["total_images"],
                content["generation_unit_count"],
            ),
            (1, 1, 3, 5, 7),
        )
        self.assertEqual(
            project["prompt_sources"]["active_batch"],
            "prompts/category_batches/pipe_unclogging/batch_v2_5_active",
        )
        self.assertEqual(
            project["prompt_sources"]["production_manifest"],
            "projects/pipe_unclogging/groups/schema_v2_5/production_manifest.jsonl",
        )
        legacy = project["prompt_sources"]["legacy_manifest_set"]
        self.assertTrue(legacy["read_only"])
        self.assertEqual(legacy["group_schema"], "legacy_1_cover_8_details")
        self.assertEqual(
            len(load_jsonl(PROJECT_DIR / "groups" / "production_manifest.jsonl")),
            90,
        )
        self.assertEqual(
            len(
                load_jsonl(
                    ROOT
                    / "prompts"
                    / "category_batches"
                    / "pipe_unclogging"
                    / "batch_20260710_054132_003104"
                    / "prompts.jsonl"
                )
            ),
            90,
        )

    def test_thirty_groups_have_seven_generation_units_and_five_deliveries(self) -> None:
        generation = load_jsonl(ACTIVE_BATCH / "prompts.jsonl")
        deliveries = load_jsonl(V2_DIR / "production_manifest.jsonl")
        registry = load_json(V2_DIR / "registry.json")
        self.assertEqual(len(generation), 210)
        self.assertEqual(len(deliveries), 150)
        self.assertEqual(registry["created_groups"], 30)
        self.assertEqual(registry["next_group_index"], 31)

        by_group_generation: dict[int, list[dict]] = defaultdict(list)
        by_group_delivery: dict[int, list[dict]] = defaultdict(list)
        for row in generation:
            by_group_generation[int(row["group_index"])].append(row)
        for row in deliveries:
            by_group_delivery[int(row["group_index"])].append(row)

        generation_ids: set[str] = set()
        delivery_ids: set[str] = set()
        height_cycle = ("1024x1408", "1024x1472", "1024x1536")
        layout_cycle = (
            "stacked_equal",
            "top_feature_bottom_pair",
            "top_pair_bottom_feature",
        )
        for group_index in range(1, 31):
            units = sorted(
                by_group_generation[group_index],
                key=lambda row: int(row["generation_position"]),
            )
            products = sorted(
                by_group_delivery[group_index],
                key=lambda row: int(row["position"]),
            )
            self.assertEqual(
                [row["generation_role"] for row in units],
                [
                    "cover",
                    "triptych_panel",
                    "triptych_panel",
                    "triptych_panel",
                    "detail",
                    "detail",
                    "detail",
                ],
            )
            self.assertEqual(
                [int(row["delivery_position"]) for row in units],
                [1, 2, 2, 2, 3, 4, 5],
            )
            service_roles = [row["service_role"] for row in units[1:]]
            self.assertEqual(len(service_roles), 6)
            self.assertEqual(len(set(service_roles)), 6)
            self.assertEqual(
                [row["role"] for row in products],
                ["cover", "triptych", "detail", "detail", "detail"],
            )
            self.assertEqual(
                [row["filename"] for row in products],
                [
                    "01_cover.png",
                    "02_triptych.png",
                    "03_detail.png",
                    "04_detail.png",
                    "05_detail.png",
                ],
            )
            expected_size = height_cycle[(group_index - 1) % 3]
            expected_layout = layout_cycle[((group_index - 1) // 3) % 3]
            self.assertEqual({row["final_size"] for row in units}, {expected_size})
            self.assertEqual({row["final_size"] for row in products}, {expected_size})
            self.assertEqual(
                {row["triptych_layout_id"] for row in units},
                {expected_layout},
            )
            self.assertEqual(products[1]["triptych_layout_id"], expected_layout)
            self.assertEqual(len(products[1]["source_generation_ids"]), 3)
            for row in units:
                self.assertEqual(row["structure_version"], STRUCTURE_VERSION)
                self.assertNotIn(row["generation_id"], generation_ids)
                generation_ids.add(row["generation_id"])
            for row in products:
                self.assertEqual(row["structure_version"], STRUCTURE_VERSION)
                self.assertNotIn(row["delivery_id"], delivery_ids)
                delivery_ids.add(row["delivery_id"])

        first_nine_combinations = {
            (
                by_group_generation[index][0]["height_profile_id"],
                by_group_generation[index][0]["triptych_layout_id"],
            )
            for index in range(1, 10)
        }
        self.assertEqual(len(first_nine_combinations), 9)


if __name__ == "__main__":
    unittest.main()
