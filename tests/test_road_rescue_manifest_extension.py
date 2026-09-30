from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import generate_road_rescue_v3_groups as groups


def jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


class RoadRescueManifestExtensionTests(unittest.TestCase):
    def test_extension_preserves_existing_jsonl_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_dir = root / "projects" / "road_rescue"
            schema_dir = project_dir / "groups" / groups.V3_SCHEMA_DIR_NAME
            batch_dir = root / "prompts" / "category_batches" / "road_rescue" / groups.V3_BATCH_NAME
            schema_dir.mkdir(parents=True)
            batch_dir.mkdir(parents=True)

            old_groups = [
                {"group_index": 316, "cover_variant_signature": "cover-316"},
                {"group_index": 317, "cover_variant_signature": "cover-317"},
            ]
            roles = ["汽车搭电", "补胎换胎", "拖车服务", "送油救援", "困境救援", "地库救援"]
            old_generation = []
            for index in range(1, 15):
                position = ((index - 1) % 7) + 1
                old_generation.append(
                    {
                        "index": index,
                        "generation_role": "cover" if position == 1 else "detail",
                        "service_role": None if position == 1 else roles[(position - 2) % len(roles)],
                    }
                )
            old_delivery = [{"delivery_id": f"old-{index}"} for index in range(10)]
            old_schema_text = {
                "group_manifest.jsonl": jsonl(old_groups),
                "generation_manifest.jsonl": jsonl(old_generation),
                "production_manifest.jsonl": jsonl(old_delivery),
            }
            old_batch_text = {
                "prompts.jsonl": jsonl(old_generation),
                "cover_prompts.jsonl": jsonl(old_generation[::7]),
                "triptych_panel_prompts.jsonl": jsonl(old_generation[1:4] + old_generation[8:11]),
                "detail_prompts.jsonl": jsonl(old_generation[4:7] + old_generation[11:14]),
                "manifest.jsonl": jsonl([{"id": index} for index in range(14)]),
                "delivery_manifest.jsonl": jsonl(old_delivery),
            }
            for name, content in old_schema_text.items():
                (schema_dir / name).write_text(content, encoding="utf-8", newline="\n")
            for name, content in old_batch_text.items():
                (batch_dir / name).write_text(content, encoding="utf-8", newline="\n")

            registry = {
                "structure_version": groups.V3_STRUCTURE_VERSION,
                "created_groups": 2,
                "first_group_index": 316,
                "last_group_index": 317,
                "next_group_index": 318,
                "groups": old_groups,
                "created_at": "old",
            }
            summary = {
                "group_start": 316,
                "group_count": 2,
                "generation_unit_count": 14,
                "delivery_file_count": 10,
                "created_at": "old",
            }
            (schema_dir / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
            (batch_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            (project_dir / "project.json").write_text(
                json.dumps({"prompt_sources": {}, "content_group": {}}),
                encoding="utf-8",
            )

            def fake_build(start: int, count: int, **kwargs):
                self.assertEqual((start, count), (318, 2))
                self.assertEqual(kwargs["global_index_start"], 15)
                self.assertEqual(kwargs["initial_cover_signatures"], {"cover-316", "cover-317"})
                new_groups = [
                    {"group_index": 318, "cover_variant_signature": "cover-318"},
                    {"group_index": 319, "cover_variant_signature": "cover-319"},
                ]
                new_generation = [{"index": index} for index in range(15, 29)]
                new_delivery = [{"delivery_id": f"new-{index}"} for index in range(10)]
                schema_files = {
                    "registry.json": json.dumps({"groups": new_groups}),
                    "group_manifest.jsonl": jsonl(new_groups),
                    "generation_manifest.jsonl": jsonl(new_generation),
                    "production_manifest.jsonl": jsonl(new_delivery),
                }
                batch_files = {
                    "prompts.jsonl": jsonl(new_generation),
                    "cover_prompts.jsonl": jsonl(new_generation[::7]),
                    "triptych_panel_prompts.jsonl": jsonl(new_generation[1:4] + new_generation[8:11]),
                    "detail_prompts.jsonl": jsonl(new_generation[4:7] + new_generation[11:14]),
                    "manifest.jsonl": jsonl([{"id": index} for index in range(14, 28)]),
                    "delivery_manifest.jsonl": jsonl(new_delivery),
                }
                return schema_files, batch_files, {"created_at": "new"}

            with (
                mock.patch.object(groups, "ROOT", root),
                mock.patch.object(groups, "PROJECT_DIR", project_dir),
                mock.patch.object(groups, "_build_payloads", side_effect=fake_build),
            ):
                result = groups.extend_v3_5_groups(2)

            self.assertEqual(result["group_start"], 318)
            self.assertEqual(result["new_last_group_index"], 319)
            self.assertTrue(result["verified_history_prefix_unchanged"])
            self.assertFalse(result["api_called"])
            for name, prefix in old_schema_text.items():
                self.assertTrue((schema_dir / name).read_text(encoding="utf-8").startswith(prefix))
            for name, prefix in old_batch_text.items():
                self.assertTrue((batch_dir / name).read_text(encoding="utf-8").startswith(prefix))
            updated_registry = json.loads((schema_dir / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(updated_registry["created_groups"], 4)
            self.assertEqual(updated_registry["last_group_index"], 319)
            history = [json.loads(line) for line in (schema_dir / "extension_history.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(history[-1]["verified_history_prefix_unchanged"])


if __name__ == "__main__":
    unittest.main()
