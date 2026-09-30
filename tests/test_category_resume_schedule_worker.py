from __future__ import annotations

import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tests.test_category_image_resume_worker import CONFIG, ResumeWorkerFixture, write_json
from tools import category_image_resume_worker as worker
from tools.category_resume_schedule import apply_schedule_amendment


class CategoryResumeScheduleWorkerTests(unittest.TestCase):
    def fixture(self, root: Path, *, balance_requests: int = 1) -> ResumeWorkerFixture:
        item = ResumeWorkerFixture(root, unknown=1, unattempted=20, max_workers=10)
        balance_id = item.unknown_ids[0]
        base = item.plan
        base["counts"].update(unknown=0, balance_recoverable=1)
        base["unknown_ids"] = []
        base["balance_recoverable_ids"] = [balance_id]
        base["attempts_used"][balance_id] = balance_requests
        base["attempts_remaining"][balance_id] = 2
        base["requests_used"] = balance_requests
        base["balance_failure_request_count"] = balance_requests
        base["remaining_max_requests"] = sum(base["attempts_remaining"].values())
        base["cumulative_max_requests"] = balance_requests + base["remaining_max_requests"]
        item.license.update({
            key: base[key] for key in (
                "license_id", "category_id", "batch_id", "group_start", "group_count",
                "scope", "provider", "model", "quality", "size", "max_attempts", "retry_policy",
            )
        })
        item.license.update(api_key_slots=[1, 2], max_workers=2, requests_used=balance_requests)
        item.job.update(requests_used=balance_requests, quarantined_api_key_slots=[2])
        events = [{
            "status": "request_failed", "request_number": index,
            "generation_target_id": balance_id, "api_key_slot": 2, "attempt": index,
            "error_kind": "balance_exhausted", "will_retry": False,
        } for index in range(1, balance_requests + 1)]
        item.events_path.write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8",
        )
        overlay_path = item.batch / "production" / "overlay_plans" / "fixture.json"
        write_json(overlay_path, {"phone": item.license["phone"]})
        item.license["overlay_plan"] = str(overlay_path)
        base["events_sha256"] = worker._file_sha256(item.events_path)
        base["frozen_manifest_sha256"] = worker._file_sha256(item.manifest_path)
        base["frozen_overlay_sha256"] = worker._file_sha256(overlay_path)
        item.base_plan = deepcopy(base)
        item.amended_plan = apply_schedule_amendment(base, item.license, events, list(range(1, 11)))
        plan = item.amended_plan
        item.authorization.update({
            "schedule_amendment": deepcopy(plan["schedule_amendment"]),
            "events_sha256": plan["events_sha256"],
            "frozen_manifest_sha256": plan["frozen_manifest_sha256"],
            "frozen_overlay_sha256": plan["frozen_overlay_sha256"],
            "schedule_amendment_confirmed": True,
            "api_key_slots": list(range(1, 11)),
            "resume_plan_sha256": plan["resume_plan_sha256"],
            "requests_used": balance_requests,
            "approved_remaining_request_budget": plan["remaining_max_requests"],
            "approved_cumulative_request_budget": plan["cumulative_max_requests"],
            "approved_balance_recoverable_count": 1,
            "approved_balance_recoverable_ids_sha256": worker._canonical_sha256([balance_id]),
            "approved_balance_failure_request_count": balance_requests,
            "approved_additional_recovery_request_budget": 0,
            "attempts_used_sha256": worker._canonical_sha256(plan["attempts_used"]),
            "attempts_remaining_sha256": worker._canonical_sha256(plan["attempts_remaining"]),
            "per_target_attempts_sha256": worker._canonical_sha256({
                "used": plan["attempts_used"], "remaining": plan["attempts_remaining"],
            }),
        })
        item.session["resume_plan_sha256"] = plan["resume_plan_sha256"]
        item.write()
        return item

    def run_fixture(self, item: ResumeWorkerFixture, generator, *, materialize=None):
        with (
            patch.object(worker.category_image_resume, "build_resume_plan", return_value=deepcopy(item.base_plan)),
            patch.object(worker.production, "load_frozen_manifest_runtime_records", return_value=deepcopy(item.records)),
            patch.object(worker.production, "save_raw_png", return_value={"saved_raw_sha256": "f" * 64}),
            patch.object(worker, "_materialize_ready_deliveries", side_effect=materialize or (lambda *args: 0)),
        ):
            return worker.resume_category_images(
                item.batch, item.job_path, item.license_path, item.authorization_path,
                item.amended_plan["resume_plan_sha256"], session_path=item.session_path,
                clients=[(slot, slot) for slot in range(1, 11)],
                generate_one=generator, config=CONFIG,
            )

    def test_valid_amendment_never_uses_inherited_quarantined_slot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            item = self.fixture(Path(raw))
            calls = []
            live_widths = []

            def generate(slot, _config, prompt):
                calls.append((slot, prompt))
                live_widths.append(json.loads(item.job_path.read_text())["current_worker_count"])
                return b"image"

            result = self.run_fixture(item, generate)
            job = json.loads(item.job_path.read_text(encoding="utf-8"))
            license_data = json.loads(item.license_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual(calls[0][0], 1)
            self.assertNotIn(2, [slot for slot, _prompt in calls])
            self.assertEqual([stage["worker_count"] for stage in job["resume_concurrency_history"]], [1, 9, 9, 2])
            self.assertEqual(len(calls), 21)
            self.assertEqual(live_widths[0], 1)
            self.assertEqual(set(live_widths), {1, 9, 2})
            self.assertEqual(job["current_worker_count"], 0)
            self.assertEqual(job["worker_count"], 0)
            self.assertEqual(license_data["api_key_slots"], [1, 2])
            self.assertEqual(license_data["approved_request_budget"], item.license["approved_request_budget"])
            self.assertEqual(license_data["phone"], item.license["phone"])
            self.assertEqual(license_data["model"], item.license["model"])
            self.assertEqual(license_data["requests_used"], 22)

    def test_amendment_tampering_fails_before_any_request(self) -> None:
        for mutation in ("quarantine", "budget", "original_slots", "confirmation", "extra_budget"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as raw:
                item = self.fixture(Path(raw))
                if mutation == "quarantine":
                    item.authorization["schedule_amendment"]["inherited_quarantined_api_key_slots"] = []
                elif mutation == "budget":
                    item.authorization["schedule_amendment"]["strict_original_request_budget"] += 1
                elif mutation == "original_slots":
                    item.authorization["schedule_amendment"]["original_api_key_slots"] = [1, 2, 3]
                elif mutation == "confirmation":
                    item.authorization["schedule_amendment_confirmed"] = False
                else:
                    item.authorization["approved_additional_recovery_request_budget"] = 1
                write_json(item.authorization_path, item.authorization)
                calls = []
                with self.assertRaises(worker.ResumeExecutionError):
                    self.run_fixture(item, lambda *args: calls.append(args) or b"image")
                self.assertEqual(calls, [])
                self.assertEqual(json.loads(item.authorization_path.read_text())["status"], "active")

    def test_original_budget_is_hard_cap_even_during_parallel_retries(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            item = self.fixture(Path(raw), balance_requests=8)
            attempts = {}
            calls = []

            def generate(slot, _config, prompt):
                calls.append((slot, prompt))
                attempts[prompt] = attempts.get(prompt, 0) + 1
                if attempts[prompt] == 1:
                    raise RuntimeError("connection error")
                return b"image"

            result = self.run_fixture(item, generate)
            job = json.loads(item.job_path.read_text(encoding="utf-8"))
            license_data = json.loads(item.license_path.read_text(encoding="utf-8"))
            budget = item.license["approved_request_budget"]
            self.assertEqual(result["status"], "paused_request_budget")
            self.assertEqual(license_data["requests_used"], budget)
            self.assertEqual(len(calls), budget - 8)
            self.assertEqual(job["checkpoint"]["remaining_request_budget"], 0)
            self.assertTrue(job["checkpoint"]["in_flight_drained"])
            self.assertTrue(job["checkpoint"]["unfinished_generation_target_ids"])
            self.assertNotIn(2, [slot for slot, _prompt in calls])

    def test_transient_storm_drains_one_stage_stops_and_redacts_errors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            item = self.fixture(Path(raw))
            probe_prompt = item.records[1]["frozen_effective_prompt"]
            calls = []

            def generate(slot, _config, prompt):
                calls.append((slot, prompt))
                if prompt == probe_prompt:
                    return b"probe"
                error = RuntimeError("connection error sk-FAKE_RESUME_KEY PRIVATE_PROVIDER_BODY")
                error.status_code = 503
                raise error

            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = self.run_fixture(item, generate)
            job = json.loads(item.job_path.read_text(encoding="utf-8"))
            session = json.loads(item.session_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "paused_api_errors")
            self.assertEqual(session["status"], "paused_api_errors")
            self.assertEqual(len(calls), 19)
            self.assertEqual(job["requests_used"], 20)
            self.assertEqual(len(job["resume_concurrency_history"]), 2)
            self.assertTrue(job["resume_concurrency_history"][-1]["in_flight_drained"])
            self.assertEqual(job["api_error_circuit_breaker_failure_count"], 9)
            self.assertEqual(job["checkpoint"]["remaining_request_budget"], 22)
            evidence = json.dumps(job) + json.dumps(session) + item.events_path.read_text() + stdout.getvalue() + stderr.getvalue()
            self.assertNotIn("sk-FAKE_RESUME_KEY", evidence)
            self.assertNotIn("PRIVATE_PROVIDER_BODY", evidence)
            self.assertIn("error_kind=transient", evidence)

    def test_cli_failure_never_prints_provider_body(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            item = self.fixture(Path(raw))
            args = Namespace(
                command="run", batch_dir=str(item.batch), job_file=str(item.job_path),
                license=str(item.license_path), resume_authorization=str(item.authorization_path),
                resume_plan_sha256=item.amended_plan["resume_plan_sha256"],
                session_file=str(item.session_path),
            )
            error = RuntimeError("connection error sk-FAKE_CLI_KEY PRIVATE_CLI_BODY")
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.object(worker, "build_parser") as parser,
                patch.object(worker, "resume_category_images", side_effect=error),
                redirect_stdout(stdout), redirect_stderr(stderr),
                self.assertRaises(SystemExit) as stopped,
            ):
                parser.return_value.parse_args.return_value = args
                worker.main()
            self.assertEqual(stopped.exception.code, 1)
            evidence = item.session_path.read_text() + stdout.getvalue() + stderr.getvalue()
            self.assertNotIn("sk-FAKE_CLI_KEY", evidence)
            self.assertNotIn("PRIVATE_CLI_BODY", evidence)

    def test_transient_then_balance_does_not_refund_previous_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            item = self.fixture(Path(raw))
            target = item.records[2]
            special_prompt = target["frozen_effective_prompt"]
            attempts = []

            def generate(slot, _config, prompt):
                if prompt != special_prompt:
                    return b"image"
                attempts.append(slot)
                if len(attempts) == 2:
                    raise RuntimeError("INSUFFICIENT_BALANCE")
                if len(attempts) <= 3:
                    raise RuntimeError("connection error")
                return b"must-not-be-requested"

            result = self.run_fixture(item, generate)
            events = [json.loads(line) for line in item.events_path.read_text().splitlines()]
            target_failures = [
                event for event in events
                if event.get("generation_target_id") == target["generation_target_id"]
                and event.get("status") == "request_failed"
            ]
            self.assertEqual(len(attempts), 3)
            self.assertNotEqual(attempts[1], attempts[2])
            self.assertEqual([event["error_kind"] for event in target_failures], ["transient", "balance_exhausted", "transient"])
            self.assertEqual([event["will_retry"] for event in target_failures], [True, False, False])
            self.assertEqual(result["status"], "completed_with_errors")
            self.assertIn(target["generation_target_id"], result["failed_ids"])

    def test_locked_revalidation_prevents_stale_ledger_and_any_delivery_write(self) -> None:
        for evidence in ("job", "license", "events", "manifest", "overlay"):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as raw:
                item = self.fixture(Path(raw))
                path = {
                    "job": item.job_path,
                    "license": item.license_path,
                    "events": item.events_path,
                    "manifest": item.manifest_path,
                    "overlay": Path(item.license["overlay_plan"]),
                }[evidence]
                acquire_lock = worker.production.acquire_lock
                calls, materialized = [], []

                def changed_while_acquiring(*args):
                    path.write_bytes(path.read_bytes() + b" ")
                    return acquire_lock(*args)

                with patch.object(worker.production, "acquire_lock", side_effect=changed_while_acquiring):
                    with self.assertRaisesRegex(worker.ResumeExecutionError, "取得生产锁后"):
                        self.run_fixture(
                            item, lambda *args: calls.append(args) or b"image",
                            materialize=lambda *args: materialized.append(args) or 0,
                        )
                self.assertEqual(calls, [])
                self.assertEqual(materialized, [])
                self.assertEqual(json.loads(item.authorization_path.read_text())["status"], "active")
                self.assertFalse((item.batch / "production" / "generation.lock").exists())

    def test_existing_reusable_delivery_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            image = Path(raw) / "existing.png"
            image.write_bytes(b"existing-image-evidence")
            delivery = {
                "target": str(image), "final_size": "1024x1536",
                "generation_target_ids": ["already-successful"],
            }
            with (
                patch.object(worker.production, "reusable_target", return_value=True),
                patch.object(worker.production, "apply_overlays") as overlays,
                patch.object(worker.production, "compose_triptych") as triptych,
            ):
                completed = worker._materialize_ready_deliveries(
                    [delivery], {"already-successful"}, "13437186038", ["货车救援"],
                )
            self.assertEqual(completed, 1)
            self.assertEqual(image.read_bytes(), b"existing-image-evidence")
            overlays.assert_not_called()
            triptych.assert_not_called()

    def test_cover_policy_retry_uses_existing_safe_v1_and_preserves_phone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            item = self.fixture(Path(raw))
            cover = item.records[1]
            phone = str(item.license["phone"])
            original = f"普通中国街边货车救援维修门店，门头电话{phone}，不得出现水印。"
            cover.update(generation_kind="cover", service_role=None, frozen_effective_prompt=original)
            safe_prompt, variant = worker.production.content_policy_retry_for_record(cover, original)
            self.assertEqual(variant, "content_policy_safe_v1")
            self.assertIn(phone, safe_prompt)
            self.assertIn("货车救援维修门店", safe_prompt)
            cover_calls = []

            def generate(_slot, _config, prompt):
                if prompt in {original, safe_prompt}:
                    cover_calls.append(prompt)
                    if len(cover_calls) == 1:
                        raise RuntimeError("content_policy_violation")
                return b"image"

            result = self.run_fixture(item, generate)
            events = [json.loads(line) for line in item.events_path.read_text().splitlines()]
            reservations = [
                event for event in events if event.get("status") == "request_reserved"
                and event.get("generation_target_id") == cover["generation_target_id"]
            ]
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual(cover_calls, [original, safe_prompt])
            self.assertEqual([event["retry_prompt_variant"] for event in reservations], ["original", "content_policy_safe_v1"])
            self.assertEqual([event["attempt"] for event in reservations], [1, 2])

    def test_unknown_retry_variant_fails_before_second_request(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            item = self.fixture(Path(raw))
            cover = item.records[1]
            cover.update(generation_kind="cover", service_role=None)
            calls = []

            def generate(*args):
                calls.append(args)
                raise RuntimeError("content_policy_violation")

            with patch.object(worker.production, "content_policy_retry_for_record", return_value=("UNKNOWN", "unknown_variant")):
                with self.assertRaisesRegex(worker.ResumeExecutionError, "匹配图种"):
                    self.run_fixture(item, generate)
            self.assertEqual(len(calls), 1)
            license_data = json.loads(item.license_path.read_text())
            self.assertEqual(license_data["requests_used"], item.license["requests_used"] + 1)


if __name__ == "__main__":
    unittest.main()
