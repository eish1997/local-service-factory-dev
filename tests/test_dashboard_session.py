from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import factory


class DashboardSessionTests(unittest.TestCase):
    def test_activate_and_archive_dashboard_session_preserves_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runtime = root / ".runtime"
            session_path = runtime / "dashboard_session.json"
            archive_dir = runtime / "dashboard_archive" / "sessions"
            delivery_state = runtime / "dashboard_delivery_state.json"
            job_path = runtime / "jobs" / "job-1.json"
            target = root / "output" / "road_rescue" / "group_0001" / "02_triptych.png"
            job_path.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            job = {
                "job_id": "job-1",
                "project_id": "road_rescue",
                "group_start": 1,
                "group_count": 1,
                "scope": "details",
            }
            job_path.write_text(json.dumps(job), encoding="utf-8")
            target.write_bytes(b"preserved-image")
            record = {
                "target": str(target),
                "group_index": 1,
                "delivery_position": 2,
                "delivery_kind": "triptych",
            }

            with (
                patch.object(factory, "ROOT", root),
                patch.object(factory, "DASHBOARD_SESSION_PATH", session_path),
                patch.object(factory, "DASHBOARD_SESSION_ARCHIVE_DIR", archive_dir),
                patch.object(factory, "DASHBOARD_DELIVERY_STATE_PATH", delivery_state),
            ):
                factory.activate_dashboard_session(job_path, job, target_records=[record])
                active = json.loads(session_path.read_text(encoding="utf-8"))
                self.assertEqual(active["mode"], "job")
                self.assertEqual(active["job_id"], "job-1")
                self.assertEqual(active["expected_targets"][0]["path"], "output/road_rescue/group_0001/02_triptych.png")
                queue = json.loads(delivery_state.read_text(encoding="utf-8"))
                self.assertIn("1", queue["projects"]["road_rescue"]["pending_groups"])

                archived = factory.archive_dashboard_session("test archive")
                waiting = json.loads(session_path.read_text(encoding="utf-8"))
                self.assertTrue(archived and archived.is_file())
                self.assertEqual(waiting["mode"], "waiting")
                self.assertIsNone(waiting["job_id"])
                self.assertEqual(target.read_bytes(), b"preserved-image")
                queue_after_archive = json.loads(delivery_state.read_text(encoding="utf-8"))
                self.assertIn(
                    "1", queue_after_archive["projects"]["road_rescue"]["pending_groups"]
                )

    def test_dashboard_target_outside_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            outside = root / "not-output.png"
            outside.write_bytes(b"x")
            with patch.object(factory, "ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "正式 output"):
                    factory._dashboard_target_descriptors([{"target": str(outside)}])


if __name__ == "__main__":
    unittest.main()
