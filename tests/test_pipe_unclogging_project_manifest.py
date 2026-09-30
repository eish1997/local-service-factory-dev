from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import generate_pipe_unclogging_groups as pipe_groups
from tools.prompt_engine import load_category_config, scene_matches_legal_combination


ROOT = Path(__file__).resolve().parents[1]
LEGACY_BATCH = (
    ROOT
    / "prompts"
    / "category_batches"
    / "pipe_unclogging"
    / "batch_20260710_054132_003104"
)


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def tree_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    result: dict[str, tuple[int, int, str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result[path.relative_to(root).as_posix()] = (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return result


class PipeUncloggingProjectManifestTests(unittest.TestCase):
    def test_imports_real_legacy_batch_read_only_and_filters_needs_fix_cover(self) -> None:
        self.assertTrue(LEGACY_BATCH.is_dir(), "legacy pipe-unclogging fixture is missing")
        batch_before = tree_snapshot(LEGACY_BATCH)
        with tempfile.TemporaryDirectory() as temporary:
            project_dir = Path(temporary) / "projects" / "pipe_unclogging"
            result = pipe_groups.import_legacy_batch(project_dir, LEGACY_BATCH)

            self.assertEqual(result["group_start"], 1)
            self.assertEqual(result["group_count"], 10)
            self.assertEqual(result["image_count"], 90)
            self.assertEqual(result["reusable_sources"], 2)
            self.assertFalse(result["api_called"])

            covers = load_jsonl(project_dir / "prompts" / "cover_prompts.jsonl")
            details = load_jsonl(project_dir / "prompts" / "detail_prompts.jsonl")
            groups = load_jsonl(project_dir / "groups" / "group_manifest.jsonl")
            production = load_jsonl(project_dir / "groups" / "production_manifest.jsonl")
            registry = json.loads(
                (project_dir / "groups" / "registry.json").read_text(encoding="utf-8")
            )

            self.assertEqual(len(covers), 10)
            self.assertEqual(len(details), 80)
            self.assertEqual(len(groups), 10)
            self.assertEqual(len(production), 90)
            self.assertEqual(registry["created_groups"], 10)
            self.assertEqual(registry["next_group_index"], 11)

            signatures = [row["cover_variant_signature"] for row in covers]
            self.assertEqual(len(signatures), len(set(signatures)))
            self.assertTrue(all(row["cover_style_version"] == 2 for row in covers))
            self.assertTrue(
                all(row["legacy_batch_id"] == LEGACY_BATCH.name for row in covers + details)
            )
            self.assertTrue(
                all(row["source_lineage"]["kind"] == "legacy_category_batch" for row in production)
            )

            first_group = {
                int(row["position"]): row
                for row in production
                if int(row["group_index"]) == 1
            }
            self.assertIsNone(first_group[1]["source"])
            self.assertEqual(first_group[1]["source_review_status"], "needs_fix")
            self.assertFalse(first_group[1]["source_reuse_eligible"])
            self.assertIsNotNone(first_group[3]["source"])
            self.assertIsNotNone(first_group[9]["source"])
            reused = [row for row in production if row["source"]]
            self.assertEqual(
                {(row["group_index"], row["position"]) for row in reused},
                {(1, 3), (1, 9)},
            )
            for row in reused:
                source = Path(row["source"])
                if not source.is_absolute():
                    source = ROOT / source
                self.assertTrue(source.is_file())

            for row in production:
                expected_name = "01_cover.png" if row["position"] == 1 else f"{row['position']:02d}_detail.png"
                self.assertEqual(
                    row["target"],
                    f"output/pipe_unclogging/group_{row['group_index']:04d}/{expected_name}",
                )
                self.assertFalse(row["api_called"])
            self.assertFalse((Path(temporary) / "output").exists())

            project_before_retry = {
                path.relative_to(project_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in project_dir.rglob("*")
                if path.is_file()
            }
            with self.assertRaises(pipe_groups.PipeProjectManifestError):
                pipe_groups.import_legacy_batch(project_dir, LEGACY_BATCH)
            project_after_retry = {
                path.relative_to(project_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in project_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(project_before_retry, project_after_retry)

        self.assertEqual(batch_before, tree_snapshot(LEGACY_BATCH))

    def test_append_uses_next_index_legal_combinations_and_complete_history_uniqueness(self) -> None:
        config = load_category_config("pipe_unclogging")
        phone_pattern = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
        with tempfile.TemporaryDirectory() as temporary:
            project_dir = Path(temporary) / "projects" / "pipe_unclogging"
            first = pipe_groups.append_groups(25, project_dir)
            self.assertEqual(first["group_start"], 1)
            self.assertEqual(first["next_group_index"], 26)
            self.assertFalse(first["api_called"])

            cover_path = project_dir / "prompts" / "cover_prompts.jsonl"
            detail_path = project_dir / "prompts" / "detail_prompts.jsonl"
            group_path = project_dir / "groups" / "group_manifest.jsonl"
            production_path = project_dir / "groups" / "production_manifest.jsonl"
            first_covers = load_jsonl(cover_path)
            first_details = load_jsonl(detail_path)
            first_groups = load_jsonl(group_path)
            first_production = load_jsonl(production_path)

            self.assertEqual(len(first_covers), 25)
            self.assertEqual(len(first_details), 200)
            self.assertEqual(len(first_groups), 25)
            self.assertEqual(len(first_production), 225)
            self.assertEqual(
                len({row["cover_variant_signature"] for row in first_covers}), 25
            )
            for row in first_covers:
                self.assertTrue(scene_matches_legal_combination(config, "cover", row["scene"]))
                self.assertEqual(row["source_lineage"]["kind"], "prompt_engine")
            for row in first_details:
                self.assertTrue(
                    scene_matches_legal_combination(config, row["title"], row["scene"]),
                    f"illegal detail combination: group={row['group_index']} position={row['position']}",
                )
                self.assertEqual(row["source_lineage"]["kind"], "prompt_engine")
            for row in first_production:
                self.assertIsNone(row["source"])
                self.assertFalse(row["api_called"])
                self.assertIsNone(phone_pattern.search(row["prompt"]))

            second = pipe_groups.append_groups(5, project_dir)
            self.assertEqual(second["group_start"], 26)
            self.assertEqual(second["next_group_index"], 31)
            covers = load_jsonl(cover_path)
            details = load_jsonl(detail_path)
            groups = load_jsonl(group_path)
            production = load_jsonl(production_path)
            registry = json.loads(
                (project_dir / "groups" / "registry.json").read_text(encoding="utf-8")
            )

            self.assertEqual(covers[:25], first_covers)
            self.assertEqual(details[:200], first_details)
            self.assertEqual(groups[:25], first_groups)
            self.assertEqual(production[:225], first_production)
            self.assertEqual([row["group_index"] for row in covers[25:]], list(range(26, 31)))
            self.assertEqual([row["index"] for row in details], list(range(1, 241)))
            signatures = [row["cover_variant_signature"] for row in covers]
            self.assertEqual(len(signatures), len(set(signatures)))
            self.assertEqual(registry["created_groups"], 30)
            self.assertEqual(registry["next_group_index"], 31)
            self.assertEqual(
                [row["cover_variant_signature"] for row in registry["groups"]], signatures
            )
            self.assertEqual(len(production), 270)
            for row in production:
                expected_name = "01_cover.png" if row["position"] == 1 else f"{row['position']:02d}_detail.png"
                self.assertEqual(
                    row["target"],
                    f"output/pipe_unclogging/group_{row['group_index']:04d}/{expected_name}",
                )
            self.assertFalse((Path(temporary) / "output").exists())


if __name__ == "__main__":
    unittest.main()
