from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "renumber_project_groups",
    SOURCE_ROOT / "tools" / "renumber_project_groups.py",
)
renumber = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(renumber)


class RenumberProjectGroupsTests(unittest.TestCase):
    def test_drop_thirteen_and_compact_metadata_without_missing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project_id = "home_appliance_repair"
            project = root / "projects" / project_id
            groups_dir = project / "groups"
            prompts_dir = project / "prompts"
            output = root / "output" / project_id
            runtime = root / ".runtime" / "projects" / project_id
            groups_dir.mkdir(parents=True)
            prompts_dir.mkdir(parents=True)
            output.mkdir(parents=True)
            runtime.mkdir(parents=True)
            for index in range(1, 17):
                group_dir = output / f"group_{index:04d}"
                (group_dir / "raw").mkdir(parents=True)
                if index in {14, 15, 16}:
                    (group_dir / "01_cover.png").write_bytes(b"png")
                    (group_dir / "raw" / "cover_raw.png").write_bytes(b"raw")
                    for position, (slug, _) in enumerate(renumber.DETAILS, start=2):
                        (group_dir / f"{position:02d}_detail_{slug}.png").write_bytes(b"png")
                        (group_dir / "raw" / f"{slug}_raw.png").write_bytes(b"raw")
            validation = output / "group_0016" / "01_cover.validation.json"
            validation.write_text(json.dumps({"image": str(output / "group_0016" / "01_cover.png")}), encoding="utf-8")
            registry = {
                "schema_version": 1, "project_id": project_id, "group_size": 9,
                "cover_count": 1, "detail_count": 8, "created_groups": 16,
                "next_group_index": 17, "groups": [{"group_index": i} for i in range(1, 17)],
            }
            (groups_dir / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
            prompt = "old prompt"
            digest = hashlib.sha256(prompt.encode()).hexdigest()
            group_row = {
                "project_id": project_id, "group_index": 16,
                "cover": {"group_index": 16, "position": 1},
                "details": [
                    {"index": 120 + offset, "position": offset + 1, "title": title, "slug": slug}
                    for offset, (slug, title) in enumerate(renumber.DETAILS, start=1)
                ],
            }
            cover_row = {"project_id": project_id, "group_index": 16, "prompt": prompt, "prompt_sha256": digest}
            detail_rows = [
                {
                    "project_id": project_id, "group_index": 16, "index": 120 + offset,
                    "position": offset + 1, "title": title, "slug": slug,
                    "prompt": prompt, "prompt_sha256": digest,
                }
                for offset, (slug, title) in enumerate(renumber.DETAILS, start=1)
            ]
            group_path = Path("output") / project_id / "group_0016"
            production = [{
                "project_id": project_id, "group_index": 16, "position": 1, "role": "cover",
                "filename": "01_cover.png", "target": str(group_path / "01_cover.png"),
                "source": str(group_path / "raw" / "cover_raw.png"),
                "prompt": prompt, "prompt_sha256": digest,
            }]
            for offset, (slug, title) in enumerate(renumber.DETAILS, start=1):
                position = offset + 1
                filename = f"{position:02d}_detail_{slug}.png"
                production.append({
                    "project_id": project_id, "group_index": 16, "position": position, "role": "detail",
                    "detail_index": 120 + offset, "filename": filename,
                    "target": str(group_path / filename), "source": None,
                    "prompt": prompt, "prompt_sha256": digest, "local_label": title,
                })
            for path, rows in (
                (groups_dir / "group_manifest.jsonl", [group_row]),
                (groups_dir / "production_manifest.jsonl", production),
                (prompts_dir / "cover_prompts.jsonl", [cover_row]),
                (prompts_dir / "detail_prompts.jsonl", detail_rows),
            ):
                path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            (project / "project.json").write_text(json.dumps({
                "prompt_sources": {"detail_prompt_count": 8, "available_complete_detail_sets": 1},
            }), encoding="utf-8")

            with patch.object(renumber, "ROOT", root), patch("factory.active_group_jobs", return_value=[]):
                state = renumber.preflight(project_id, 13)
                migration = root / ".runtime" / "migrations" / "test"
                migration.mkdir(parents=True)
                renumber.move_output_groups(state, migration, 13)
                renumber.rename_runtime_backups(state, migration, 13)
                renumber.transform_metadata(state, project_id, 13, "13317195304")
                result = renumber.verify(state, project_id)

            self.assertEqual(result["groups"], 3)
            self.assertEqual(result["images"], 27)
            self.assertEqual(sorted(path.name for path in output.iterdir()), ["group_0001", "group_0002", "group_0003"])
            self.assertTrue((migration / "deleted_groups" / "group_0001").is_dir())
            moved_validation = json.loads((output / "group_0003" / validation.name).read_text(encoding="utf-8"))
            self.assertIn("group_0003", moved_validation["image"])
            details = renumber.load_jsonl(prompts_dir / "detail_prompts.jsonl")
            self.assertEqual([row["index"] for row in details], list(range(1, 25)))


if __name__ == "__main__":
    unittest.main()
