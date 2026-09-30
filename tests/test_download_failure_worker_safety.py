"""Paid URL failures must never become another POST (all APIs are mocked)."""
from contextlib import contextmanager
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
import threading
from unittest.mock import MagicMock, Mock, patch

import image_generate
from tools import category_image_production as production
from tools import category_image_resume as core
from tools import category_image_resume_worker as worker
from tools import image_download_receipts as receipts
from tests import test_category_generation_profile as normal_fixtures
from tests.test_category_generation_profile import truck_fixture, license_fixture
from tests.test_category_profile_resume import profile_fixture, authorize_resume, run_resume


class DownloadFailureWorkerSafetyTests(unittest.TestCase):
    def client(self):
        return SimpleNamespace(images=SimpleNamespace(generate=Mock(return_value=SimpleNamespace(
            data=[SimpleNamespace(b64_json=None, url="https://cdn.example/image.png?signature=fixture-secret")],
        ))))

    @contextmanager
    def download(self, phase):
        if phase == "open":
            call = Mock(side_effect=TimeoutError("timeout fixture-secret"))
        else:
            response = MagicMock()
            response.getcode.return_value = 200
            response.headers = {"Content-Type": "image/png"}
            response.read1.side_effect = TimeoutError("timeout fixture-secret")
            call = Mock(return_value=response)
        with patch.object(image_generate, "_image_download_opener", return_value=SimpleNamespace(open=call)):
            yield call

    def test_normal_probe_open_and_read_failure_makes_one_post_and_pauses(self):
        for phase in ("open", "read"):
            with self.subTest(phase=phase), truck_fixture(374) as item:
                lic = license_fixture(item)
                client, original_generate = self.client(), image_generate.generate_one
                with self.download(phase) as download:
                    code, job, events = normal_fixtures.CategoryGenerationProfileWorkerTests().run_worker(
                        item, lic, original_generate, lambda *a, **k: self.fail("raw saved"), [(1, client), (2, client)],
                    )
                self.assertEqual(code, 1)
                client.images.generate.assert_called_once()
                download.assert_called_once()
                self.assertEqual((job["status"], job["requests_used"]), ("paused_image_download", 1))
                self.assertEqual(job["checkpoint"]["remaining_request_budget"], 13)
                self.assertFalse(job["checkpoint"]["generation_resubmit_allowed"])
                self.assertEqual(sum(e["status"] == "request_reserved" for e in events), 1)
                failure = next(e for e in events if e["status"] == "request_failed")
                self.assertEqual(failure["error_kind"], "image_download_failed")
                self.assertFalse(failure["will_retry"])
                self.assertNotIn("fixture-secret", json.dumps(events))
                with self.assertRaises(Exception):
                    receipts.assert_no_pending_for_job(item.root / ".runtime/image_download_receipts", "new-profile-job")

    def test_resume_probe_open_and_read_failure_keeps_existing_count_and_budget(self):
        for phase in ("open", "read"):
            with self.subTest(phase=phase), profile_fixture() as item:
                plan, auth, session = authorize_resume(item)
                client, original_generate = self.client(), image_generate.generate_one
                with self.download(phase) as download:
                    result, _ = run_resume(item, plan, auth, session,
                                           lambda _client, config, prompt: original_generate(client, config, prompt))
                client.images.generate.assert_called_once()
                download.assert_called_once()
                self.assertEqual((result["status"], result["requests_used_start"], result["requests_used_end"]),
                                 ("paused_image_download", 2, 3))
                job = production.load_json(item.job_path)
                self.assertEqual(job["checkpoint"]["remaining_request_budget"], 11)
                self.assertFalse(job["checkpoint"]["generation_resubmit_allowed"])
                events = [json.loads(line) for line in item.events_path.read_text().splitlines()]
                self.assertEqual(sum(e["status"] == "request_reserved" for e in events), 3)
                self.assertEqual(production.load_json(item.license_path)["approved_request_budget"], 14)
                with patch.object(core, "RECEIPT_ROOT", item.root / ".runtime/image_download_receipts"):
                    with self.assertRaises(Exception):
                        core.build_resume_plan(item.batch, item.job_path, item.license_path)

    def test_url_stage_classification_wins_over_billing_or_policy_words(self):
        for phase in ("image_download_open", "image_download_read"):
            error = TimeoutError("INSUFFICIENT_BALANCE content_policy_violation timeout")
            error.error_stage, error.response_kind = phase, "url"
            self.assertEqual(production.classify_request_error(error), "image_download_failed")
        error = TimeoutError("timeout")
        error.error_stage, error.response_kind = "api_generate", "unknown"
        self.assertEqual(production.classify_request_error(error), "transient")

    def test_fixed_and_adaptive_stage_download_failure_drains_and_never_dispatches_next_stage(self):
        for scheduler in (production.run_fixed_request_batches, production.run_adaptive_request_batches):
            with self.subTest(scheduler=scheduler.__name__):
                calls = []
                def run(slot, client, record):
                    calls.append(record)
                    return production.RequestBatchResult(False, final_error_kind="image_download_failed")
                stages = scheduler(list(range(20)), [(1, 1), (2, 2)], 2, run, balance_failover=True)
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(stages), 1)
                self.assertTrue(stages[0]["in_flight_drained"])
                self.assertEqual(stages[0]["balance_failover_target_count"], 0)

    def test_normal_and_resume_workers_pause_after_inflight_download_stage(self):
        def successful_response():
            response = MagicMock()
            response.getcode.return_value = 200
            response.headers = {"Content-Type": "image/png"}
            response.read1.side_effect = [b"fixture-image", b""]
            return response
        def download_stage():
            gate, calls = threading.Lock(), []
            def open_url(*args, **kwargs):
                with gate:
                    calls.append(1)
                    if len(calls) == 1:
                        return successful_response()
                raise TimeoutError("download timed out")
            return SimpleNamespace(open=Mock(side_effect=open_url))
        def save(path, payload, **kwargs):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return {"saved_raw_sha256": hashlib.sha256(payload).hexdigest()}
        with truck_fixture(374) as item:
            lic = license_fixture(item)
            client, original_generate = self.client(), image_generate.generate_one
            with patch.object(image_generate, "_image_download_opener", return_value=download_stage()):
                _, job, events = normal_fixtures.CategoryGenerationProfileWorkerTests().run_worker(
                    item, lic, original_generate, save, [(1, client), (2, client)],
                )
            self.assertEqual(job["status"], "paused_image_download")
            self.assertEqual(len(job["concurrency_history"]), 2)
            self.assertLessEqual(client.images.generate.call_count, 3)
            self.assertEqual(job["requests_used"], client.images.generate.call_count)
            self.assertTrue(job["concurrency_history"][-1]["in_flight_drained"])
        with profile_fixture(2) as item:
            plan, auth, session = authorize_resume(item)
            client = self.client()
            with patch.object(image_generate, "_image_download_opener", return_value=download_stage()):
                result, _ = run_resume(item, plan, auth, session,
                    lambda _client, config, prompt: image_generate.generate_one(client, config, prompt), save)
            self.assertEqual(result["status"], "paused_image_download")
            job = production.load_json(item.job_path)
            self.assertEqual(len(job["resume_concurrency_history"]), 2)
            self.assertLessEqual(client.images.generate.call_count, 5)
            self.assertEqual(job["requests_used"], 2 + client.images.generate.call_count)
            self.assertTrue(job["resume_concurrency_history"][-1]["in_flight_drained"])

    def test_current_shape_preserves_four_used_two_exhausted_208_targets_416_remaining(self):
        with profile_fixture(30) as item:
            events = [json.loads(line) for line in item.events_path.read_text().splitlines()]
            row = item.plan["manifest_entries"][1]
            for attempt in (1, 2):
                identity = {key: row[key] for key in ("generation_target_id", "delivery_target_id", "group_index", "generation_position", "delivery_position")}
                events.extend([
                    {**identity, "status": "request_reserved", "request_number": 2 + attempt,
                     "attempt": attempt, "api_key_slot": 1, "raw_target": row["raw_target"], "delivery_target": row["target"],
                     "effective_prompt_sha256": row["effective_prompt_sha256"], "retry_prompt_variant": "original"},
                    {**identity, "status": "request_failed", "request_number": 2 + attempt,
                     "attempt": attempt, "api_key_slot": 1, "error_kind": "transient", "error_stage": "image_download_open",
                     "response_kind": "url", "will_retry": attempt == 1},
                ])
            item.events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
            for path in (item.job_path, item.license_path):
                value = production.load_json(path)
                value["requests_used"] = 4
                if path == item.job_path:
                    value["failed"] = 2
                production.atomic_json(path, value)
            plan = core.build_resume_plan(item.batch, item.job_path, item.license_path)
            self.assertEqual((plan["requests_used"], plan["counts"]["exhausted"], plan["counts"]["resumable"],
                              plan["remaining_max_requests"], plan["cumulative_max_requests"]), (4, 2, 208, 416, 420))

    def test_historical_download_failure_without_receipt_is_excluded_even_retry_true(self):
        with profile_fixture() as item:
            events = [json.loads(line) for line in item.events_path.read_text().splitlines()][:2]
            events[1].update(error_stage="image_download_open", response_kind="url", will_retry=True)
            item.events_path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
            for path in (item.job_path, item.license_path):
                value = production.load_json(path)
                value["requests_used"] = 1
                production.atomic_json(path, value)
            plan = core.build_resume_plan(item.batch, item.job_path, item.license_path)
            target = events[1]["generation_target_id"]
            self.assertIn(target, plan["exhausted_ids"])
            self.assertNotIn(target, plan["resumable_ids"])
            self.assertEqual(plan["attempts_used"][target], 1)
            self.assertEqual(plan["attempts_remaining"][target], 0)
            self.assertEqual((plan["requests_used"], plan["remaining_max_requests"]), (1, 12))

    def test_resume_pending_receipt_blocks_before_authorization_consumption(self):
        with profile_fixture() as item:
            plan, auth, session = authorize_resume(item)
            with patch.object(receipts, "assert_no_pending_for_job", side_effect=RuntimeError("pending private receipt")):
                with self.assertRaises(Exception):
                    run_resume(item, plan, auth, session, lambda *a: self.fail("API called"))
            self.assertEqual(production.load_json(auth)["status"], "active")
            self.assertEqual(production.load_json(item.license_path)["requests_used"], 2)

    def test_new_profile_unknown_reservation_cannot_become_fresh_post(self):
        with profile_fixture() as item:
            first = item.events_path.read_text().splitlines()[0]
            item.events_path.write_text(first + "\n", encoding="utf-8")
            for path in (item.job_path, item.license_path):
                value = production.load_json(path)
                value["requests_used"] = 1
                production.atomic_json(path, value)
            with self.assertRaisesRegex(core.ResumePlanError, "结果未知"):
                core.build_resume_plan(item.batch, item.job_path, item.license_path)

    def test_returned_bytes_then_save_timeout_never_reposts_normal_or_resume(self):
        response = MagicMock()
        response.getcode.return_value = 200
        response.headers = {"Content-Type": "image/png"}
        response.read1.side_effect = [b"fixture-returned-image", b""]
        def reject_save(*args, **kwargs):
            raise TimeoutError("save timed out")
        with truck_fixture(374) as item:
            lic = license_fixture(item)
            client, original_generate = self.client(), image_generate.generate_one
            with patch.object(image_generate, "_image_download_opener", return_value=SimpleNamespace(open=Mock(return_value=response))):
                _, job, events = normal_fixtures.CategoryGenerationProfileWorkerTests().run_worker(
                    item, lic, original_generate, reject_save, [(1, client), (2, client)],
                )
            client.images.generate.assert_called_once()
            self.assertEqual(job["status"], "paused_image_download")
            self.assertEqual(sum(e["status"] == "request_reserved" for e in events), 1)
            with self.assertRaises(Exception):
                receipts.assert_no_pending_for_job(item.root / ".runtime/image_download_receipts", "new-profile-job")
        with profile_fixture() as item:
            plan, auth, session = authorize_resume(item)
            client = self.client()
            response.read1.side_effect = [b"fixture-returned-image", b""]
            with patch.object(image_generate, "_image_download_opener", return_value=SimpleNamespace(open=Mock(return_value=response))):
                result, _ = run_resume(item, plan, auth, session,
                    lambda _client, config, prompt: image_generate.generate_one(client, config, prompt), reject_save)
            client.images.generate.assert_called_once()
            self.assertEqual((result["status"], result["requests_used_end"]), ("paused_image_download", 3))
            events = [json.loads(line) for line in item.events_path.read_text().splitlines()]
            self.assertEqual(sum(e["status"] == "request_reserved" for e in events), 3)
            with self.assertRaises(Exception):
                receipts.assert_no_pending_for_job(item.root / ".runtime/image_download_receipts", item.job["job_id"])

    def test_normal_pending_receipt_blocks_before_license_consumption(self):
        with truck_fixture(374) as item:
            lic = license_fixture(item)
            with patch.object(receipts, "assert_no_pending_for_job", side_effect=RuntimeError("pending private receipt")):
                with self.assertRaises(Exception):
                    normal_fixtures.CategoryGenerationProfileWorkerTests().run_worker(item, lic, lambda *a: self.fail("API called"), None)
            self.assertEqual(production.load_json(lic.path)["status"], "active")

    def test_malformed_context_fails_before_reservation_or_post(self):
        with profile_fixture() as item:
            plan, auth, session = authorize_resume(item)
            with patch.object(production, "image_download_context", return_value={"root": str(item.root)}):
                result, _ = run_resume(item, plan, auth, session, lambda *a: self.fail("API called"))
            self.assertEqual(result["status"], "paused_image_download")
            self.assertEqual(production.load_json(item.license_path)["requests_used"], 2)
            events = [json.loads(line) for line in item.events_path.read_text().splitlines()]
            self.assertEqual(sum(e["status"] == "request_reserved" for e in events), 2)
            self.assertEqual(production.load_json(item.job_path)["checkpoint"]["reason"], "image_download_failed")


if __name__ == "__main__":
    unittest.main()
