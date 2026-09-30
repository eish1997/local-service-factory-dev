from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import dashboard_delivery


class DashboardDeliveryTests(unittest.TestCase):
    def _make_group(self, root: Path, group_index: int, count: int = 2) -> None:
        group = root / "output" / "road_rescue" / f"group_{group_index:04d}"
        group.mkdir(parents=True)
        for position in range(1, count + 1):
            (group / f"{position:02d}_detail.png").write_bytes(
                bytes([64 + group_index]) * 200_000
            )

    def test_packaging_splits_under_limit_and_removes_only_packaged_groups(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state_path = root / ".runtime" / "dashboard_delivery_state.json"
            destination = root / "desktop"
            for group_index in range(1, 4):
                self._make_group(root, group_index)
            dashboard_delivery.register_pending_groups(
                state_path,
                "road_rescue",
                [1, 2, 3],
                expected_image_count=2,
                job_id="job-1",
            )

            result = dashboard_delivery.package_pending_groups(
                root,
                state_path,
                "road_rescue",
                1,
                3,
                destination,
                max_archive_bytes=1_000_000,
                manifest_dir=root / ".runtime" / "package_manifests",
            )

            self.assertEqual(len(result["archives"]), 2)
            for archive in result["archives"]:
                path = Path(archive["path"])
                self.assertLessEqual(path.stat().st_size, 1_000_000)
                with zipfile.ZipFile(path) as payload:
                    self.assertTrue(payload.namelist())
            state = dashboard_delivery.load_state(state_path)
            self.assertEqual(
                dashboard_delivery.pending_group_entries(state, "road_rescue"), []
            )
            self.assertTrue(Path(result["manifest_path"]).is_file())
            self.assertTrue(
                (root / "output" / "road_rescue" / "group_0001" / "01_detail.png").is_file()
            )

    def test_incomplete_group_is_not_packaged_or_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state_path = root / ".runtime" / "dashboard_delivery_state.json"
            self._make_group(root, 1, count=1)
            dashboard_delivery.register_pending_groups(
                state_path,
                "road_rescue",
                [1],
                expected_image_count=2,
            )

            with self.assertRaisesRegex(RuntimeError, "实际 1 张"):
                dashboard_delivery.package_pending_groups(
                    root,
                    state_path,
                    "road_rescue",
                    1,
                    1,
                    root / "desktop",
                    max_archive_bytes=1_000_000,
                )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("1", state["projects"]["road_rescue"]["pending_groups"])
            self.assertFalse((root / "desktop").exists())


if __name__ == "__main__":
    unittest.main()
