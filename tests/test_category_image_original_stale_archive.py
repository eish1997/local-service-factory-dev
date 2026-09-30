from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import factory


class OriginalStaleSessionArchiveTests(unittest.TestCase):
    def _context(self, root: Path, *, lock_pid: int = 91_002) -> dict:
        batch_dir = root / "batch_active"
        production = batch_dir / "production"
        jobs = production / "jobs"
        licenses = production / "licenses"
        logs = production / "logs"
        for path in (jobs, licenses, logs):
            path.mkdir(parents=True, exist_ok=True)

        job_id = "truck_rescue-test-job"
        license_id = "truck_rescue-test-license"
        job_path = jobs / f"{job_id}.json"
        license_path = licenses / f"{license_id}.json"
        events_path = production / f"events_{job_id}.jsonl"
        log_path = logs / f"{job_id}.log"
        lock_path = production / "generation.lock"
        job = {
            "job_id": job_id,
            "license_id": license_id,
            "status": "waiting_for_api",
            "pid": 91_001,
            "worker_pid": 91_002,
            "launcher_pid": None,
            "requests_used": 1,
            "log_file": str(log_path.resolve()),
        }
        license_data = {
            "license_id": license_id,
            "status": "consumed",
            "one_time": True,
            "requests_used": 1,
            "approved_request_budget": 4,
        }
        event = {
            "status": "request_reserved",
            "request_number": 1,
            "generation_target_id": "truck_rescue:v3:g0001:u02",
            "attempt": 1,
            "api_key_slot": 1,
        }
        event_bytes = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        job_path.write_text(json.dumps(job), encoding="utf-8")
        license_path.write_text(json.dumps(license_data), encoding="utf-8")
        events_path.write_bytes(event_bytes)
        log_path.write_text("worker stopped\n", encoding="utf-8")
        lock_path.write_text(
            json.dumps({"pid": lock_pid, "job_id": job_id}), encoding="utf-8"
        )
        resume_plan = {
            "resume_plan_sha256": "a" * 64,
            "requests_used": 1,
            "events_sha256": hashlib.sha256(event_bytes).hexdigest(),
            "event_tail_sha256": hashlib.sha256(event_bytes.rstrip()).hexdigest(),
        }
        return {
            "category_id": "truck_rescue",
            "job_id": job_id,
            "license_id": license_id,
            "batch_dir": batch_dir,
            "production_dir": production,
            "job_path": job_path,
            "job": job,
            "license_path": license_path,
            "license": license_data,
            "resume_plan": resume_plan,
        }

    def test_original_dead_worker_is_archived_before_lock_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context = self._context(Path(temporary))
            with mock.patch.object(
                factory.category_image_production,
                "pid_is_running",
                return_value=False,
            ):
                stale = factory._stale_consumed_original_session(context)
                self.assertIsNotNone(stale)
                self.assertEqual(stale["stale_session_kind"], "original")
                self.assertEqual(
                    stale["open_reservations"][0]["request_number"], 1
                )
                archive_path = factory._archive_stale_consumed_original_session(
                    context, stale
                )

            self.assertFalse(
                (Path(context["production_dir"]) / "generation.lock").exists()
            )
            archive = json.loads(archive_path.read_text(encoding="utf-8"))
            self.assertEqual(
                archive["kind"], "stale-consumed-original-crash-archive"
            )
            self.assertEqual(archive["dead_worker_pid"], 91_002)
            self.assertEqual(
                set(archive["immutable_copies"]),
                {"job", "license", "events", "log", "lock"},
            )

    def test_original_lock_pid_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context = self._context(Path(temporary), lock_pid=91_003)
            with mock.patch.object(
                factory.category_image_production,
                "pid_is_running",
                return_value=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "worker_pid 不一致"):
                    factory._stale_consumed_original_session(context)
            self.assertTrue(
                (Path(context["production_dir"]) / "generation.lock").is_file()
            )


if __name__ == "__main__":
    unittest.main()
