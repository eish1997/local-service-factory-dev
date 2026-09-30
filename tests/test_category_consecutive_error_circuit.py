from __future__ import annotations

import json
import io
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests import test_pipe_unclogging_scoped_production as fixtures
from tools import category_image_production as production


class CategoryConsecutiveErrorCircuitTests(unittest.TestCase):
    def failure(self, kind: str | None = "transient") -> production.RequestBatchResult:
        return production.RequestBatchResult(
            success=False, final_error_kind=kind, attempt_count=2,
        )

    def schedule(self, results: list[object], workers: int = 2) -> tuple[list[int], list[dict]]:
        attempted: list[int] = []

        def run_one(_slot: int, _client: object, record: dict) -> object:
            attempted.append(record["id"])
            return results[record["id"]]

        history = production.run_adaptive_request_batches(
            [{"id": index} for index in range(len(results))],
            [(index + 1, object()) for index in range(workers)],
            workers,
            run_one,
        )
        return attempted, history

    def test_consecutive_transient_failures_cross_stages_and_stop_dispatch(self) -> None:
        attempted, history = self.schedule([self.failure()] * 10)
        self.assertEqual(sorted(attempted), [0, 1, 2, 3])
        self.assertEqual(len(history), 2)
        self.assertEqual(
            [stage["consecutive_api_failure_count"] for stage in history], [2, 4],
        )
        self.assertTrue(history[-1]["api_error_circuit_breaker_triggered"])
        self.assertEqual(history[-1]["undispatched_target_count"], 6)
        self.assertTrue(all(stage["in_flight_drained"] for stage in history))

    def test_success_resets_counter_across_stages(self) -> None:
        results = [self.failure(), self.failure(), True,
                   self.failure(), self.failure(), True, self.failure(), True]
        attempted, history = self.schedule(results)
        self.assertEqual(sorted(attempted), list(range(len(results))))
        self.assertEqual(
            [stage["consecutive_api_failure_count"] for stage in history], [2, 1, 0, 0],
        )
        self.assertFalse(any(stage["api_error_circuit_breaker_triggered"] for stage in history))

    def test_threshold_latches_until_drained_even_if_later_target_succeeds(self) -> None:
        attempted, history = self.schedule(
            [self.failure(), self.failure(), self.failure(), True, True, True],
        )
        self.assertEqual(sorted(attempted), [0, 1, 2, 3])
        self.assertEqual(history[-1]["consecutive_api_failure_count"], 0)
        self.assertEqual(history[-1]["consecutive_api_failure_peak"], 3)
        self.assertTrue(history[-1]["api_error_circuit_breaker_triggered"])

    def test_balance_failures_do_not_count_or_reset_other_failures(self) -> None:
        result = production._consecutive_api_error_stage_result(
            [self.failure("balance_exhausted"), self.failure(None)], 2,
        )
        self.assertEqual(result["consecutive_api_failure_count"], 3)
        self.assertTrue(result["api_error_circuit_breaker_triggered"])
        balance_only = production._consecutive_api_error_stage_result(
            [self.failure("balance_exhausted")] * 4, 0,
        )
        self.assertFalse(balance_only["api_error_circuit_breaker_triggered"])

    def test_unclassified_failures_are_also_bounded(self) -> None:
        attempted, history = self.schedule([self.failure(None)] * 6, workers=1)
        self.assertEqual(attempted, [0, 1, 2])
        self.assertTrue(history[-1]["api_error_circuit_breaker_triggered"])

    def run_fake_worker(
        self, *, probe_succeeds: bool, error_message: str = "connection error",
    ) -> dict:
        helper = fixtures.PipeUncloggingScopedProductionTests()
        with tempfile.TemporaryDirectory(prefix="category-circuit-") as raw:
            root = Path(raw)
            with (
                patch.object(production, "CATEGORY_BATCH_ROOT", root),
                patch.object(production, "ROOT", root),
                patch.object(production, "ACTIVE_JOB_PATH", None),
                patch.object(production, "ACTIVE_LICENSE_PATH", None),
                patch.object(production, "ACTIVE_LOCK_PATH", None),
            ):
                batch_dir = helper.make_v2_batch(root, 2)
                output = root / "output" / "pipe_unclogging"
                run_plan = production.plan(
                    "pipe_unclogging", batch_dir, 1, 2, fixtures.PHONE,
                    fixtures.CONFIG, scope="details", output_root=output,
                )
                license_id = "consecutive-error-license"
                production.write_production_files(run_plan, fixtures.PHONE, license_id)
                license_path = production.license_path(
                    "pipe_unclogging", batch_dir, 1, 2, license_id,
                )
                license_payload = helper.license_payload(
                    run_plan, license_id, slots=[1, 2], max_workers=2, max_attempts=2,
                )
                license_payload["concurrency_policy"] = production.ADAPTIVE_CONCURRENCY_POLICY
                production.write_new_license(license_path, license_payload)
                job_path = production.jobs_dir(batch_dir) / "consecutive-error-job.json"
                production.atomic_json(job_path, {
                    "job_id": "consecutive-error-job", "license_id": license_id,
                })
                first_prompt = production.effective_prompt(
                    run_plan["pending_records"][0], fixtures.PHONE,
                )
                calls: list[str] = []

                def fake_generate(_client: object, _config: dict, prompt: str) -> bytes:
                    calls.append(prompt)
                    if probe_succeeds and prompt == first_prompt:
                        return b"simulated-success"
                    error = RuntimeError(error_message)
                    error.status_code = 503
                    raise error

                args = Namespace(
                    category="pipe_unclogging", batch_dir=str(batch_dir),
                    group_start=1, group_count=2, license=str(license_path),
                    job_file=str(job_path), scope="details", output_root=str(output),
                    license_id=license_id, max_workers=2,
                )
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    patch.object(production.image_generate, "load_json", return_value=fixtures.CONFIG),
                    patch.object(production.image_generate, "apply_provider_config", return_value=fixtures.CONFIG),
                    patch.object(production, "openai_clients_by_slot", return_value=[(1, object()), (2, object())]),
                    patch.object(production, "_font", return_value=None),
                    patch.object(production.image_generate, "generate_one", side_effect=fake_generate),
                    patch.object(production, "save_raw_png", return_value={}),
                    patch.object(production, "_materialize_delivery"),
                    patch.object(production.time, "sleep"),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    exit_code = production.run(args)
                events_path = production.production_dir(batch_dir) / "events_consecutive-error-job.jsonl"
                summary_path = production.summary_path(batch_dir, 1, 2, license_id)
                return {
                    "exit_code": exit_code,
                    "job": production.load_json(job_path),
                    "license": production.load_json(license_path),
                    "summary": production.load_json(summary_path),
                    "calls": calls,
                    "events": [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()],
                    "lock_exists": (production.production_dir(batch_dir) / "generation.lock").exists(),
                    "stdout": stdout.getvalue(),
                    "stderr": stderr.getvalue(),
                }

    def test_worker_persists_paused_state_and_exact_remaining_checkpoint(self) -> None:
        result = self.run_fake_worker(probe_succeeds=True)
        job = result["job"]
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(job["status"], "paused_api_errors")
        self.assertEqual(result["summary"]["status"], "paused_api_errors")
        self.assertEqual(job["requests_used"], 9)
        self.assertEqual(job["retry_count"], 4)
        self.assertEqual(job["failed"], 4)
        self.assertEqual(job["current_worker_count"], 0)
        self.assertTrue(job["api_error_circuit_breaker_triggered"])
        self.assertEqual(job["api_error_circuit_breaker_failure_count"], 4)
        self.assertEqual(job["stop_reason"], "consecutive_non_balance_api_failures")
        checkpoint = job["checkpoint"]
        self.assertEqual(checkpoint["remaining_request_budget"], 15)
        self.assertEqual(len(checkpoint["unfinished_generation_target_ids"]), 11)
        self.assertEqual(len(checkpoint["unattempted_generation_target_ids"]), 7)
        self.assertEqual(sum(checkpoint["api_requests_by_generation_target"].values()), 9)
        self.assertEqual(max(checkpoint["logical_attempts_by_generation_target"].values()), 2)
        self.assertTrue(checkpoint["in_flight_drained"])
        self.assertEqual(result["license"]["status"], "consumed")
        self.assertEqual(result["license"]["requests_used"], 9)
        self.assertEqual(result["license"]["approved_request_budget"], 24)
        self.assertEqual(len(result["calls"]), 9)
        self.assertFalse(result["lock_exists"])

    def test_failed_probe_stops_without_dispatching_an_adaptive_stage(self) -> None:
        result = self.run_fake_worker(probe_succeeds=False)
        job = result["job"]
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(job["status"], "paused_probe_failed")
        self.assertEqual(result["summary"]["status"], "paused_probe_failed")
        self.assertEqual(len(result["calls"]), 2)
        self.assertEqual(job["requests_used"], 2)
        self.assertEqual(job["current_worker_count"], 0)
        self.assertEqual([stage["phase"] for stage in job["concurrency_history"]], ["probe"])
        self.assertEqual(job["checkpoint"]["remaining_request_budget"], 22)
        self.assertEqual(len(job["checkpoint"]["unattempted_generation_target_ids"]), 11)
        self.assertFalse(result["lock_exists"])

    def test_request_error_body_and_fake_key_are_not_persisted_or_printed(self) -> None:
        fake_key = "[credential omitted]"
        provider_body = "PRIVATE_PROVIDER_BODY"
        result = self.run_fake_worker(
            probe_succeeds=False,
            error_message=f"connection error: Authorization=Bearer {fake_key}; {provider_body}",
        )
        evidence = json.dumps({
            key: result[key]
            for key in ("job", "events", "summary", "stdout", "stderr")
        })
        self.assertNotIn(fake_key, evidence)
        self.assertNotIn(provider_body, evidence)
        self.assertEqual(
            result["job"]["last_error"],
            "error_type=RuntimeError; error_kind=transient; http_status=503",
        )
        self.assertTrue(all(
            event["error"] == result["job"]["last_error"]
            for event in result["events"] if event.get("status") == "request_failed"
        ))

    def test_fatal_error_guard_suppresses_raw_traceback(self) -> None:
        fake_key = "sk-FAKE_FATAL_KEY"
        error = RuntimeError(f"server error {fake_key} PRIVATE_FATAL_BODY")
        error.status_code = 500
        with tempfile.TemporaryDirectory(prefix="category-error-guard-") as raw:
            job_path = Path(raw) / "job.json"
            lock_path = Path(raw) / "generation.lock"
            production.atomic_json(job_path, {"job_id": "fake-fatal-job"})
            production.atomic_json(lock_path, {"job_id": "fake-fatal-job"})
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.object(production, "main", side_effect=error),
                patch.object(production, "ACTIVE_JOB_PATH", job_path),
                patch.object(production, "ACTIVE_LOCK_PATH", lock_path),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit) as stopped,
            ):
                production.main_with_error_handling()
            job = production.load_json(job_path)
            self.assertFalse(lock_path.exists())
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(
            job["last_error"],
            "error_type=RuntimeError; error_kind=transient; http_status=500",
        )
        evidence = json.dumps(job) + stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(fake_key, evidence)
        self.assertNotIn("PRIVATE_FATAL_BODY", evidence)

    def test_error_summary_ignores_unstructured_status_and_unknown_kind(self) -> None:
        error = RuntimeError("PRIVATE_BODY")
        error.status_code = "503 sk-FAKE_STATUS_KEY"
        summary = production.safe_request_error_summary(error, "sk-FAKE_KIND_KEY")
        self.assertEqual(summary, "error_type=RuntimeError; error_kind=non_retryable")

    def test_safe_paused_states_are_idle_without_restoring_license(self) -> None:
        with tempfile.TemporaryDirectory(prefix="category-paused-idle-") as raw:
            batch_dir = Path(raw)
            license_path = production.production_dir(batch_dir) / "licenses" / "test.json"
            production.atomic_json(license_path, {"status": "consumed", "requests_used": 9})
            job_path = production.jobs_dir(batch_dir) / "paused.json"
            for status in ("paused_api_errors", "paused_probe_failed", "paused_balance_exhausted"):
                with self.subTest(status=status):
                    production.atomic_json(job_path, {
                        "job_id": "paused", "status": status,
                        "group_start": 1, "group_count": 1,
                    })
                    production._require_detail_regeneration_idle(batch_dir, 1)
                    self.assertEqual(production.load_json(job_path)["status"], status)
                    self.assertEqual(production.load_json(license_path), {
                        "status": "consumed", "requests_used": 9,
                    })


if __name__ == "__main__":
    unittest.main()
