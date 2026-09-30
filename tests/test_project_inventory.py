from __future__ import annotations

import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageEnhance

from tools import project_inventory as inventory


class ProjectInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        (self.root / "projects").mkdir(parents=True)
        (self.root / "output").mkdir(parents=True)
        self.ready: dict[tuple[str, int], bool] = {}
        self._create_project("project_a", category="同一类目")
        self._create_project("project_b", category="同一类目")
        registry = {
            "projects": [
                {
                    "id": "project_a",
                    "definition": "projects/project_a/project.json",
                },
                {
                    "id": "project_b",
                    "definition": "projects/project_b/project.json",
                },
            ]
        }
        self._write_json(self.root / "projects" / "registry.json", registry)
        self.patchers = [
            mock.patch.object(inventory, "ROOT", self.root),
            mock.patch.object(
                inventory,
                "PROJECT_REGISTRY_PATH",
                self.root / "projects" / "registry.json",
            ),
            mock.patch.object(inventory, "OUTPUT_ROOT", (self.root / "output").resolve()),
            mock.patch("group_production.audit_groups", side_effect=self._audit_groups),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _create_project(self, project_id: str, category: str) -> None:
        project_dir = self.root / "projects" / project_id
        groups_dir = project_dir / "groups"
        groups_dir.mkdir(parents=True)
        definition = {
            "schema_version": 1,
            "id": project_id,
            "name": project_id,
            "category": category,
            "content_group": {
                "cover_count": 1,
                "detail_count": 1,
                "total_images": 2,
            },
            "prompt_sources": {
                "production_manifest": f"projects/{project_id}/groups/production_manifest.jsonl"
            },
            "group_registry": f"projects/{project_id}/groups/registry.json",
            "inventory_ledger": f"projects/{project_id}/groups/inventory.json",
            "inventory_policy": {"target_available_groups": 30},
            "output_dir": f"output/{project_id}",
        }
        self._write_json(project_dir / "project.json", definition)
        self._write_json(
            groups_dir / "registry.json",
            {
                "project_id": project_id,
                "group_size": 2,
                "groups": [{"group_index": index} for index in range(1, 4)],
            },
        )
        (groups_dir / "production_manifest.jsonl").write_text("", encoding="utf-8")

    def _audit_groups(self, start: int, count: int, project_id: str) -> dict[str, object]:
        rows = []
        for index in range(start, start + count):
            is_ready = self.ready.get((project_id, index), True)
            rows.append(
                {
                    "group_index": index,
                    "delivery_ready": is_ready,
                    "image_complete": is_ready,
                    "text_approved": is_ready,
                }
            )
        return {
            "project_id": project_id,
            "group_start": start,
            "group_count": count,
            "delivery_ready_groups": sum(bool(row["delivery_ready"]) for row in rows),
            "groups": rows,
        }

    @staticmethod
    def _make_image(path: Path, seed: int) -> None:
        randomizer = random.Random(seed)
        image = Image.new("RGB", (90, 140))
        pixels = [
            (
                randomizer.randrange(256),
                randomizer.randrange(256),
                randomizer.randrange(256),
            )
            for _ in range(90 * 140)
        ]
        image.putdata(pixels)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")

    def _manifest_path(self, project_id: str) -> Path:
        return self.root / "projects" / project_id / "groups" / "production_manifest.jsonl"

    def _history_path(self, project_id: str) -> Path:
        return self.root / "projects" / project_id / "groups" / "inventory_history.jsonl"

    def _read_history(self, project_id: str) -> list[dict[str, object]]:
        path = self._history_path(project_id)
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def _write_group(
        self,
        project_id: str,
        group_index: int,
        *,
        cover_seed: int,
        detail_seed: int,
    ) -> list[Path]:
        group_dir = self.root / "output" / project_id / f"group_{group_index:04d}"
        paths = [group_dir / "01_cover.png", group_dir / "02_detail.png"]
        self._make_image(paths[0], cover_seed)
        self._make_image(paths[1], detail_seed)
        records = [
            {
                "project_id": project_id,
                "group_index": group_index,
                "position": 1,
                "role": "cover",
                "filename": paths[0].name,
                "target": paths[0].relative_to(self.root).as_posix(),
                "prompt_sha256": f"cover-{group_index}",
            },
            {
                "project_id": project_id,
                "group_index": group_index,
                "position": 2,
                "role": "detail",
                "filename": paths[1].name,
                "target": paths[1].relative_to(self.root).as_posix(),
                "prompt_sha256": f"detail-{group_index}",
            },
        ]
        manifest = self._manifest_path(project_id)
        with manifest.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return paths

    def _copy_group_with_optional_overlay_change(
        self,
        project_id: str,
        source_paths: list[Path],
        group_index: int,
        *,
        change_excluded_overlay_pixel: bool,
    ) -> list[Path]:
        group_dir = self.root / "output" / project_id / f"group_{group_index:04d}"
        paths = [group_dir / "01_cover.png", group_dir / "02_detail.png"]
        group_dir.mkdir(parents=True, exist_ok=True)
        for source, target in zip(source_paths, paths):
            shutil.copy2(source, target)
            if change_excluded_overlay_pixel:
                with Image.open(target) as opened:
                    image = opened.convert("RGB")
                old = image.getpixel((4, 70))
                image.putpixel((4, 70), ((old[0] + 1) % 256, old[1], old[2]))
                image.save(target, format="PNG")
        records = [
            {
                "project_id": project_id,
                "group_index": group_index,
                "position": 1,
                "role": "cover",
                "filename": paths[0].name,
                "target": paths[0].relative_to(self.root).as_posix(),
                "prompt_sha256": f"cover-{group_index}",
            },
            {
                "project_id": project_id,
                "group_index": group_index,
                "position": 2,
                "role": "detail",
                "filename": paths[1].name,
                "target": paths[1].relative_to(self.root).as_posix(),
                "prompt_sha256": f"detail-{group_index}",
            },
        ]
        with self._manifest_path(project_id).open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return paths

    def test_register_is_idempotent_and_consumed_deletion_keeps_history(self) -> None:
        paths = self._write_group("project_a", 1, cover_seed=101, detail_seed=201)

        first = inventory.register_groups("project_a", 1, 1)
        second = inventory.register_groups("project_a", 1, 1)

        self.assertEqual(first["registered_groups"], [1])
        self.assertEqual(second["registered_groups"], [])
        self.assertEqual(second["already_registered"], [{"group_index": 1, "state": "available"}])
        history = self._read_history("project_a")
        self.assertEqual(len(history), 1)
        fingerprint = history[0]["images"][0]["fingerprint"]
        self.assertEqual(len(fingerprint["file_sha256"]), 64)
        self.assertEqual(len(fingerprint["rgb_sha256"]), 64)
        self.assertEqual(len(fingerprint["scene_phash64"]), 16)
        self.assertEqual(len(fingerprint["scene_dhash256"]), 64)

        with self.assertRaises(ValueError):
            inventory.mark_used("project_a", 1, confirm=False)
        inventory.mark_used("project_a", 1, confirm=True)
        repeated = inventory.mark_used("project_a", 1, confirm=True)
        self.assertTrue(repeated["already_marked"])
        for path in paths:
            path.unlink()
        snapshot_file = self.root / "projects" / "project_a" / "groups" / "inventory.json"
        snapshot_file.unlink()
        snapshot = inventory.sync_inventory("project_a")

        history = self._read_history("project_a")
        self.assertEqual([row["event_type"] for row in history], ["available", "consumed"])
        self.assertEqual(snapshot["summary"]["consumed_groups"], 1)
        self.assertEqual(snapshot["summary"]["unexpected_groups"], 0)
        group = next(row for row in snapshot["groups"] if row["group_index"] == 1)
        self.assertEqual(group["disk_state"], "consumed_files_missing_expected")
        self.assertEqual(snapshot["summary"]["historical_unique_images"], 2)

    def test_exact_history_duplicate_is_always_blocked(self) -> None:
        first_paths = self._write_group("project_a", 1, cover_seed=301, detail_seed=401)
        inventory.register_groups("project_a", 1, 1)
        self._copy_group_with_optional_overlay_change(
            "project_a", first_paths, 2, change_excluded_overlay_pixel=False
        )

        with self.assertRaises(inventory.ExactDuplicateError):
            inventory.register_groups("project_a", 2, 1, allow_near_duplicates=True)

        self.assertEqual(len(self._read_history("project_a")), 1)

    def test_exact_duplicate_inside_first_group_is_blocked(self) -> None:
        paths = self._write_group("project_a", 1, cover_seed=351, detail_seed=451)
        shutil.copy2(paths[0], paths[1])

        with self.assertRaises(inventory.ExactDuplicateError):
            inventory.register_groups("project_a", 1, 1, allow_near_duplicates=True)

        self.assertEqual(self._read_history("project_a"), [])

    def test_near_duplicate_is_blocked_until_human_override(self) -> None:
        first_paths = self._write_group("project_a", 1, cover_seed=501, detail_seed=601)
        inventory.register_groups("project_a", 1, 1)
        self._copy_group_with_optional_overlay_change(
            "project_a", first_paths, 2, change_excluded_overlay_pixel=True
        )

        with self.assertRaises(inventory.NearDuplicateError):
            inventory.register_groups("project_a", 2, 1)
        result = inventory.register_groups(
            "project_a", 2, 1, allow_near_duplicates=True
        )

        self.assertEqual(result["registered_groups"], [2])
        self.assertTrue(result["near_duplicate_override_used"])

    def test_scene_hash_catches_brightness_and_small_crop(self) -> None:
        source = self.root / "source.png"
        bright = self.root / "bright.png"
        cropped = self.root / "cropped.png"
        self._make_image(source, seed=650)
        with Image.open(source) as opened:
            image = opened.convert("RGB")
        ImageEnhance.Brightness(image).enhance(1.08).save(bright, format="PNG")
        width, height = image.size
        margin_x, margin_y = max(1, int(width * 0.03)), max(1, int(height * 0.03))
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image.crop((margin_x, margin_y, width - margin_x, height - margin_y)).resize(
            (width, height), resampling
        ).save(cropped, format="PNG")

        base = {"role": "cover", "fingerprint": inventory.image_fingerprint(source, "cover")}
        for candidate_path in (bright, cropped):
            with self.subTest(candidate=candidate_path.name):
                candidate = {
                    "role": "cover",
                    "fingerprint": inventory.image_fingerprint(candidate_path, "cover"),
                }
                matched, _, _ = inventory._near_match(base, candidate)
                self.assertTrue(matched)

    def test_identical_images_in_another_project_are_not_compared(self) -> None:
        self._write_group("project_a", 1, cover_seed=701, detail_seed=801)
        self._write_group("project_b", 1, cover_seed=701, detail_seed=801)

        inventory.register_groups("project_a", 1, 1)
        result = inventory.register_groups("project_b", 1, 1)

        self.assertEqual(result["registered_groups"], [1])
        self.assertEqual(len(self._read_history("project_a")), 1)
        self.assertEqual(len(self._read_history("project_b")), 1)

    def test_triptych_panel_fingerprints_are_compared_with_standalone_details(self) -> None:
        output_root = self.root / "output" / "pipe_unclogging"
        group_dir = output_root / "group_0001"
        filenames = [
            "01_cover.png",
            "02_triptych.png",
            "03_detail.png",
            "04_detail.png",
            "05_detail.png",
        ]
        roles = ["cover", "triptych", "detail", "detail", "detail"]
        targets = [group_dir / filename for filename in filenames]
        for seed, target in enumerate(targets, start=2001):
            self._make_image(target, seed)

        panel_paths = [self.root / f"panel_{index}.png" for index in range(1, 4)]
        # Reusing the exact scene behind standalone detail 03 must be detected
        # even though it is hidden inside the composed triptych deliverable.
        shutil.copy2(targets[2], panel_paths[0])
        self._make_image(panel_paths[1], 3102)
        self._make_image(panel_paths[2], 3103)
        panel_fingerprints = [
            {
                "generation_target_id": f"panel-{index}",
                "panel_index": index,
                "service_role": f"服务{index}",
                "fingerprint": inventory.image_fingerprint(path, "detail"),
            }
            for index, path in enumerate(panel_paths, start=1)
        ]
        self._write_json(
            targets[1].with_suffix(".validation.json"),
            {"panel_fingerprints": panel_fingerprints},
        )
        records = [
            {
                "group_index": 1,
                "position": position,
                "delivery_position": position,
                "role": role,
                "filename": target.name,
                "target": target,
                "expected_size": "90x140",
            }
            for position, (role, target) in enumerate(zip(roles, targets), start=1)
        ]

        images = inventory._fingerprinted_group(1, records, output_root)
        comparison = inventory._comparison_images(images)
        self.assertEqual(len(images), 5)
        self.assertEqual(len(images[1]["components"]), 3)
        self.assertEqual(len(comparison), 8)
        exact, _ = inventory._within_group_duplicate_candidates(1, comparison)
        self.assertTrue(
            any(
                {str(match["candidate"][1]), str(match["historical"][1])}
                == {"2.panel1", "3"}
                for match in exact
            ),
            exact,
        )

    def test_available_missing_file_is_unexpected(self) -> None:
        paths = self._write_group("project_a", 1, cover_seed=901, detail_seed=1001)
        inventory.register_groups("project_a", 1, 1)
        paths[0].unlink()

        snapshot = inventory.sync_inventory("project_a")

        self.assertEqual(snapshot["summary"]["available_groups"], 0)
        self.assertEqual(snapshot["summary"]["registered_available_groups"], 1)
        self.assertEqual(snapshot["summary"]["unexpected_groups"], 1)
        group = next(row for row in snapshot["groups"] if row["group_index"] == 1)
        self.assertEqual(group["disk_state"], "unexpected_missing")
        self.assertTrue(group["unexpected"])

    def test_consumed_group_replacement_is_still_unexpected(self) -> None:
        paths = self._write_group("project_a", 1, cover_seed=951, detail_seed=1051)
        inventory.register_groups("project_a", 1, 1)
        inventory.mark_used("project_a", 1, confirm=True)
        self._make_image(paths[0], seed=9999)

        snapshot = inventory.sync_inventory("project_a")

        self.assertEqual(snapshot["summary"]["unexpected_groups"], 1)
        group = next(row for row in snapshot["groups"] if row["group_index"] == 1)
        self.assertEqual(group["disk_state"], "consumed_files_changed_unexpected")
        self.assertTrue(group["unexpected"])

    def test_contact_sheet_is_6_by_5_and_inventory_target_is_30(self) -> None:
        self._write_group("project_a", 1, cover_seed=1101, detail_seed=1201)
        inventory.register_groups("project_a", 1, 1)

        snapshot = inventory.sync_inventory("project_a", create_contact_sheet=True)
        sheet_path = self.root / snapshot["summary"]["contact_sheet"]

        self.assertTrue(sheet_path.is_file())
        self.assertEqual(
            sheet_path.parent,
            self.root / "output" / "project_a" / "_previews",
        )
        with Image.open(sheet_path) as sheet:
            self.assertEqual(sheet.size, (1150, 1500))
        self.assertEqual(snapshot["summary"]["target_available_groups"], 30)
        self.assertEqual(snapshot["summary"]["missing_to_target"], 29)

    def test_incomplete_or_corrupt_group_never_enters_history(self) -> None:
        self._write_group("project_a", 1, cover_seed=1301, detail_seed=1401)
        self.ready[("project_a", 1)] = False
        with self.assertRaises(inventory.GroupNotDeliveryReadyError):
            inventory.register_groups("project_a", 1, 1)

        paths = self._write_group("project_a", 2, cover_seed=1501, detail_seed=1601)
        paths[1].write_bytes(b"not an image")
        with self.assertRaises(inventory.GroupNotDeliveryReadyError):
            inventory.register_groups("project_a", 2, 1)

        self.assertEqual(self._read_history("project_a"), [])


if __name__ == "__main__":
    unittest.main()
