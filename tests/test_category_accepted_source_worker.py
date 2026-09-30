from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from tests import test_category_resume_migration_worker as migration_tests
from tests.test_category_image_resume_worker import write_json
from tests.test_category_4k_raw import payload
from tools import category_4k_raw
from tools import category_image_resume_worker as worker
from tools.category_resume_migration import apply_generation_migration
from tools.category_resume_schedule import apply_schedule_amendment


class CategoryAcceptedSourceWorkerTests(unittest.TestCase):
    def fixture(self, root: Path, *, cap: int | None = None, locally_recovered: bool = False,
                width_tolerance: int = 0, fresh_quarantine: bool = True):
        item = migration_tests.CategoryResumeMigrationWorkerTests().fixture(root, cap=cap)
        # A first generation-migration session consumed one balance request in
        # the new credential epoch. Source acceptance must not unlock that slot.
        previous = deepcopy(item.authorization)
        previous_id = "resume-" + "c" * 24
        previous.update(authorization_id=previous_id, status="consumed",
                        consumed_at="2026-09-27T18:00:00+08:00")
        previous_path = item.authorization_path.parent / f"{previous_id}.json"
        write_json(previous_path, previous)
        old_migration = previous["generation_migration"]
        epoch = old_migration["credential_epoch"]
        target_id = item.base_plan["balance_recoverable_ids"][0]
        events = item.events() + [{
            "status": "resume_started", "authorization_id": previous_id,
            **old_migration["new_generation"], "credential_epoch": epoch,
            "resume_plan_sha256": previous["resume_plan_sha256"],
            "requests_used_start": previous["requests_used"],
            "cumulative_max_requests": previous["approved_cumulative_request_budget"],
        }]
        if fresh_quarantine:
            events.append({
            "status": "request_failed", "authorization_id": previous_id,
            "credential_epoch": epoch, "request_number": 2,
            "generation_target_id": target_id, "api_key_slot": 5, "attempt": 2,
            "error_kind": "balance_exhausted", "will_retry": False,
            })
        if locally_recovered:
            # This fixture mocks the core ledger; its source-receipt validation
            # is covered separately by test_category_source_recovery.
            events.append({"status": "provider_source_recovered"})
            item.job.update(failed=1, failed_request_attempts=2)
        item.events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        base = item.base_plan
        used = 2 if fresh_quarantine else 1
        base["requests_used"] = used
        base["attempts_used"][target_id] = used
        base["balance_failure_request_count"] = used
        base["events_sha256"] = worker._file_sha256(item.events_path)
        item.license["requests_used"] = used
        item.job.update(requests_used=used, status="paused_balance_exhausted",
                        quarantined_api_key_slots=[5] if fresh_quarantine else [])
        scheduled = apply_schedule_amendment(base, item.license, events, list(range(1, 11)))
        plan = apply_generation_migration(scheduled, item.license, events, previous, {
            **old_migration["new_generation"], "credential_epoch": epoch,
            "rotated_slots": [], "accepted_source_size": "2352x3520",
            **({"accepted_source_width_tolerance": width_tolerance} if width_tolerance else {}),
        })
        item.migrated_plan = plan
        item.authorization.update(
            generation_migration=deepcopy(plan["generation_migration"]),
            schedule_amendment=deepcopy(plan["schedule_amendment"]),
            resume_plan_sha256=plan["resume_plan_sha256"], requests_used=used,
            events_sha256=plan["events_sha256"], approved_balance_failure_request_count=used,
            approved_remaining_request_budget=plan["remaining_max_requests"],
            approved_cumulative_request_budget=plan["cumulative_max_requests"],
            attempts_used_sha256=worker._canonical_sha256(plan["attempts_used"]),
            attempts_remaining_sha256=worker._canonical_sha256(plan["attempts_remaining"]),
            per_target_attempts_sha256=worker._canonical_sha256({
                "used": plan["attempts_used"], "remaining": plan["attempts_remaining"],
            }),
        )
        item.session["resume_plan_sha256"] = plan["resume_plan_sha256"]
        item.write()
        return item

    def run_fixture(self, item, generator):
        return migration_tests.CategoryResumeMigrationWorkerTests().run_fixture(item, generator)

    def run_with_adapter(self, item, generator, adapter):
        with (
            patch.object(worker.category_image_resume, "build_resume_plan", return_value=deepcopy(item.base_plan)),
            patch.object(worker.production, "load_frozen_manifest_runtime_records", return_value=deepcopy(item.records)),
            patch.object(worker, "_materialize_ready_deliveries", return_value=0),
            patch.object(category_4k_raw, "save_4k_raw_png", side_effect=adapter) as saver,
        ):
            result = worker.resume_category_images(
                item.batch, item.job_path, item.license_path, item.authorization_path,
                item.migrated_plan["resume_plan_sha256"], session_path=item.session_path,
                clients=[(slot, slot) for slot in range(1, 11)], generate_one=generator,
                config={"provider": "relay", "base_url": "https://tinysnow.one/v1",
                        "model": "gpt-image-2.5-flare", "quality": "medium", "api_size": "1024x1536"},
            )
            return result, saver

    def test_consumed_migration_chain_keeps_new_quarantine_and_passes_exact_source_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            calls = []
            result, saver = self.run_fixture(item, lambda *args: calls.append(args) or b"image")
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual(result["requests_used_start"], 2)
            self.assertEqual(result["requests_used_end"], 23)
            self.assertEqual(len(calls), 21)
            self.assertEqual(calls[0][0], 1)
            used_slots = [args[0] for args in calls]
            self.assertIn(2, used_slots)  # Old-epoch slot 2 remains unquarantined.
            self.assertNotIn(5, used_slots)  # New-epoch failure remains quarantined.
            self.assertEqual(saver.call_count, 21)
            self.assertEqual({call.kwargs["accepted_source_size"] for call in saver.call_args_list}, {"2352x3520"})
            self.assertEqual({call.kwargs["credential_epoch"] for call in saver.call_args_list}, {"credential-" + "b" * 32})
            self.assertEqual(json.loads(item.license_path.read_text())["model"], "gpt-image-2.5-flare")
            self.assertEqual(json.loads(item.job_path.read_text())["quarantined_api_key_slots"], [5])

    def test_inherited_migration_cap_stops_without_expanding_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder), cap=5)
            calls = []
            result, saver = self.run_fixture(item, lambda *args: calls.append(args) or b"image")
            self.assertEqual(result["status"], "paused_request_budget")
            self.assertEqual(result["requests_used_end"], 5)
            self.assertEqual(len(calls), 3)
            self.assertEqual(saver.call_count, 3)
            self.assertEqual(json.loads(item.job_path.read_text())["checkpoint"]["remaining_request_budget"], 0)

    def test_local_recovery_reconciles_target_failure_without_refunding_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder), locally_recovered=True)
            result, _ = self.run_fixture(item, lambda *args: b"image")
            job = json.loads(item.job_path.read_text())
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual(result["requests_used_start"], 2)
            self.assertEqual(result["requests_used_end"], 23)
            self.assertEqual(job["failed"], 0)
            self.assertEqual(job["failed_request_attempts"], 2)

    def test_failed_probe_never_dispatches_parallel_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            calls = []

            def reject(*args):
                calls.append(args)
                raise RuntimeError("invalid unsupported request")

            result, saver = self.run_fixture(item, reject)
            self.assertEqual(result["status"], "paused_resume_probe_failed")
            self.assertEqual(result["requests_used_end"], 3)
            self.assertEqual(len(calls), 1)
            self.assertEqual(saver.call_count, 0)
            history = json.loads(item.job_path.read_text())["resume_concurrency_history"]
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["worker_count"], 1)

    def test_width_tolerance_2336_probe_then_ten_way_passes_bound_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder), width_tolerance=16, fresh_quarantine=False)
            data = payload((2336, 3520))
            real_save = category_4k_raw.save_4k_raw_png
            calls = []
            probe_result = []

            def save(path, source, **kwargs):
                self.assertEqual(kwargs["accepted_source_size"], "2352x3520")
                self.assertEqual(kwargs["accepted_source_width_tolerance"], 16)
                with Image.open(io.BytesIO(source)) as image:
                    self.assertEqual(image.size, (2336, 3520))
                # Decode/downsample only the serial probe. The later dispatch
                # is a scheduler mock, avoiding ten parallel 8MP test decodes.
                if not probe_result:
                    probe_result.append(real_save(path, source, **kwargs))
                return dict(probe_result[0])

            result, saver = self.run_with_adapter(item, lambda *args: calls.append(args) or data, save)
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual(len(calls), 21)
            self.assertEqual(saver.call_count, 21)
            self.assertEqual(result["requests_used_start"], 1)
            self.assertEqual(result["requests_used_end"], 22)
            self.assertEqual(probe_result[0]["raw_contract"], category_4k_raw.WIDTH_TOLERANCE_SOURCE_CONTRACT)
            self.assertEqual(probe_result[0]["source_returned_size"], "2336x3520")
            history = json.loads(item.job_path.read_text())["resume_concurrency_history"]
            self.assertEqual([stage["worker_count"] for stage in history], [1, 10, 10])

    def test_width_tolerance_disallowed_source_fails_probe_without_parallel_generation(self):
        for size in ((2344, 3520), (2336, 3519), (3520, 2336)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                item = self.fixture(Path(folder), width_tolerance=16, fresh_quarantine=False)
                data = payload(size)
                calls = []
                result, saver = self.run_with_adapter(
                    item, lambda *args: calls.append(args) or data, category_4k_raw.save_4k_raw_png,
                )
                self.assertEqual(result["status"], "paused_resume_probe_failed")
                self.assertEqual(len(calls), 1)
                self.assertEqual(saver.call_count, 1)
                self.assertEqual(result["requests_used_end"], 2)
                failures = [event for event in item.events() if event.get("authorization_id") == item.authorization_id
                            and event.get("status") == "request_failed"]
                self.assertEqual(len(failures), 1)
                self.assertEqual(failures[0]["raw_contract"], category_4k_raw.WIDTH_TOLERANCE_SOURCE_CONTRACT)
                self.assertEqual(failures[0]["source_returned_size"], f"{size[0]}x{size[1]}")
                history = json.loads(item.job_path.read_text())["resume_concurrency_history"]
                self.assertEqual([stage["worker_count"] for stage in history], [1])

    def test_width_tolerance_tampering_fails_before_request_or_consumption(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder), width_tolerance=16)
            item.authorization["generation_migration"]["accepted_source_width_tolerance"] = 32
            write_json(item.authorization_path, item.authorization)
            calls = []
            with self.assertRaises((worker.ResumeExecutionError, worker.category_image_resume.ResumePlanError)):
                self.run_fixture(item, lambda *args: calls.append(args) or b"image")
            self.assertEqual(calls, [])
            self.assertEqual(json.loads(item.authorization_path.read_text())["status"], "active")


if __name__ == "__main__":
    unittest.main()
