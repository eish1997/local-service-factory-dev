from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_category_image_resume_worker import write_json
from tests import test_category_resume_schedule_worker as schedule_tests
from tools import category_4k_raw
from tools import category_image_resume_worker as worker
from tools.category_resume_migration import apply_generation_migration
from tools.category_resume_schedule import apply_schedule_amendment


class CategoryResumeMigrationWorkerTests(unittest.TestCase):
    def fixture(self, root: Path, *, cap: int | None = None):
        item = schedule_tests.CategoryResumeScheduleWorkerTests().fixture(root)
        item.license.update(model="gpt-image-2.5-flare", base_url="https://tinysnow.one/v1", third_party_confirmed=True)
        item.base_plan["model"] = item.license["model"]
        item.authorization.update(model=item.license["model"], base_url=item.license["base_url"])
        previous_id = "resume-" + "a" * 24
        events = item.events() + [{"status": "resume_started", "authorization_id": previous_id}]
        item.events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        item.base_plan["events_sha256"] = worker._file_sha256(item.events_path)
        scheduled = apply_schedule_amendment(item.base_plan, item.license, events, list(range(1, 11)))
        previous = deepcopy(item.authorization)
        prior_cap = scheduled["cumulative_max_requests"] if cap is None else cap
        previous.update(
            status="consumed", consumed_at="2026-09-27T16:00:00+08:00",
            authorization_id=previous_id,
            approved_cumulative_request_budget=prior_cap,
            approved_remaining_request_budget=prior_cap - previous["requests_used"],
        )
        item.previous_path = item.authorization_path.parent / f"{previous_id}.json"
        write_json(item.previous_path, previous)
        spec = {
            "model": "gpt-image-2-4k", "quality": "medium", "api_size": "1024x1536",
            "credential_epoch": "credential-" + "b" * 32, "rotated_slots": [2],
        }
        plan = apply_generation_migration(scheduled, item.license, events, previous, spec)
        item.migrated_plan = plan
        item.authorization.update(
            generation_migration=deepcopy(plan["generation_migration"]),
            generation_migration_confirmed=True,
            schedule_amendment=deepcopy(plan["schedule_amendment"]),
            events_sha256=plan["events_sha256"],
            resume_plan_sha256=plan["resume_plan_sha256"],
            approved_remaining_request_budget=plan["remaining_max_requests"],
            approved_cumulative_request_budget=plan["cumulative_max_requests"],
        )
        item.session["resume_plan_sha256"] = plan["resume_plan_sha256"]
        item.write()
        return item

    def run_fixture(self, item, generator, *, on_materialize=None):
        with (
            patch.object(worker.category_image_resume, "build_resume_plan", return_value=deepcopy(item.base_plan)),
            patch.object(worker.production, "load_frozen_manifest_runtime_records", return_value=deepcopy(item.records)),
            patch.object(category_4k_raw, "save_4k_raw_png", return_value={"saved_raw_sha256": "f" * 64}) as saver,
            patch.object(worker, "_materialize_ready_deliveries", side_effect=on_materialize or (lambda *args: 0)),
        ):
            result = worker.resume_category_images(
                item.batch, item.job_path, item.license_path, item.authorization_path,
                item.migrated_plan["resume_plan_sha256"], session_path=item.session_path,
                clients=[(slot, slot) for slot in range(1, 11)], generate_one=generator,
                config={"provider": "relay", "base_url": "https://tinysnow.one/v1",
                        "model": "gpt-image-2.5-flare", "quality": "medium", "api_size": "1024x1536"},
            )
            return result, saver

    def test_effective_model_is_sidecar_only_and_explicitly_rotated_slot_reenabled(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            calls = []

            def generate(slot, config, prompt):
                calls.append((slot, deepcopy(config), prompt))
                return b"image"

            result, saver = self.run_fixture(item, generate)
            self.assertEqual(result["status"], "awaiting_review")
            self.assertIn(2, [slot for slot, _, _ in calls])
            self.assertEqual(len(calls), 21)
            self.assertEqual({config["model"] for _, config, _ in calls}, {"gpt-image-2-4k"})
            self.assertEqual(saver.call_count, 21)
            self.assertEqual(json.loads(item.license_path.read_text())["model"], "gpt-image-2.5-flare")
            reserved = [event for event in item.events() if event["status"] == "request_reserved"]
            self.assertEqual({event["credential_epoch"] for event in reserved}, {"credential-" + "b" * 32})
            self.assertEqual({event["model"] for event in reserved}, {"gpt-image-2-4k"})

    def test_tampered_migration_is_rejected_before_consumption_or_request(self):
        for field, value in (("new_generation", {"model": "other"}), ("effective_quarantined_api_key_slots", [2]),
                             ("previous_authorization_sha256", "c" * 64), ("raw_contract", "unsafe")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                item = self.fixture(Path(folder))
                item.authorization["generation_migration"][field] = value
                write_json(item.authorization_path, item.authorization)
                calls = []
                with self.assertRaises((worker.ResumeExecutionError, worker.category_image_resume.ResumePlanError)):
                    self.run_fixture(item, lambda *args: calls.append(args))
                self.assertEqual(calls, [])
                self.assertEqual(json.loads(item.authorization_path.read_text())["status"], "active")

    def test_prior_authority_is_rechecked_under_lock_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            real_acquire = worker.production.acquire_lock

            def acquire(*args):
                lock = real_acquire(*args)
                changed = json.loads(item.previous_path.read_text())
                changed["approved_cumulative_request_budget"] += 1
                write_json(item.previous_path, changed)
                return lock

            calls, materialized = [], []
            with patch.object(worker.production, "acquire_lock", side_effect=acquire):
                with self.assertRaises(worker.ResumeExecutionError):
                    self.run_fixture(item, lambda *args: calls.append(args), on_materialize=lambda *args: materialized.append(args))
            self.assertEqual(calls, [])
            self.assertEqual(materialized, [])
            self.assertEqual(json.loads(item.authorization_path.read_text())["status"], "active")

    def test_prior_cumulative_cap_is_never_reexpanded_to_original_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder), cap=5)
            calls = []
            result, _ = self.run_fixture(item, lambda *args: calls.append(args) or b"image")
            self.assertEqual(result["status"], "paused_request_budget")
            self.assertEqual(result["requests_used_end"], 5)
            self.assertEqual(len(calls), 4)
            checkpoint = json.loads(item.job_path.read_text())["checkpoint"]
            self.assertEqual(checkpoint["remaining_request_budget"], 0)
            session_checkpoint = json.loads(item.session_path.read_text())["checkpoint"]
            self.assertEqual(session_checkpoint["remaining_request_budget"], 0)

    def test_new_balance_failure_reisolates_rotated_slot_without_budget_refund(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            calls = []

            def generate(slot, config, prompt):
                calls.append((slot, prompt))
                if slot == 2:
                    raise RuntimeError("INSUFFICIENT_BALANCE")
                return b"image"

            result, _ = self.run_fixture(item, generate)
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual([slot for slot, _ in calls].count(2), 1)
            self.assertEqual(len(calls), 22)
            self.assertEqual(result["requests_used_end"], 23)
            self.assertEqual(json.loads(item.job_path.read_text())["quarantined_api_key_slots"], [2])
            new_failures = [event for event in item.events() if event.get("status") == "request_failed"
                            and event.get("authorization_id") == item.authorization_id]
            self.assertEqual(len(new_failures), 1)
            self.assertEqual(new_failures[0]["credential_epoch"], "credential-" + "b" * 32)


if __name__ == "__main__":
    unittest.main()
