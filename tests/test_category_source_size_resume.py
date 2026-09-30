"""Task-bound source-size resume tests; temporary evidence and fake APIs only."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image

from tools import category_image_production as production
from tools import category_image_resume as core
from tools import category_image_resume_worker as worker
from tools import category_source_size_acceptance as source_acceptance
from tests.test_category_profile_resume import profile_fixture, authorize_resume, run_resume
from tests.test_category_source_size_acceptance import rejected_fixture, accept


def truncate_to_first_attempt(item, *, terminal=True, download=False):
    events = [json.loads(line) for line in item.events_path.read_text().splitlines()][:2 if terminal else 1]
    if terminal:
        events[1].update(error_stage="image_download_open" if download else "api_generate",
                         response_kind="url" if download else "unknown", will_retry=True)
    item.events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    for path in (item.job_path, item.license_path):
        value = production.load_json(path)
        value["requests_used"] = 1
        if path == item.job_path:
            value.update(failed=0, failed_request_attempts=1, retry_count=0)
        production.atomic_json(path, value)
    return events[0]["generation_target_id"]


@contextmanager
def bound_acceptance(item):
    """Integration seam: helper owns validation; worker must bind its whole result."""
    value = {
        "policy_id": "provider_decodable_size_to_legacy_v1", "confirmed": True,
        "job_id": item.job["job_id"], "license_id": item.license["license_id"],
        "category_id": "truck_rescue", "phone": item.license["phone"],
        "group_start": item.license["group_start"], "group_count": item.license["group_count"],
        "scope": item.license["scope"], "original_plan_sha256": item.license["plan_sha256"],
        "generation_profile_sha256": core._canonical_sha256(item.license["generation_profile"]),
        "manifest_sha256": item.license["manifest_sha256"],
        "overlay_sha256": core._file_sha256(Path(item.license["overlay_plan"])),
        "approved_request_budget": item.license["approved_request_budget"],
    }
    value["acceptance_sha256"] = core._canonical_sha256(value)
    with patch.object(source_acceptance, "load_acceptance", return_value=value), \
         patch.object(source_acceptance, "validated_recoveries", return_value={}):
        yield value


class CategorySourceSizeResumeTests(unittest.TestCase):
    def test_real_sidecar_rejects_profile_and_other_job_scope_tampering(self):
        for field, changed in (("job_id", "other-job"), ("category_id", "road_rescue"),
                               ("generation_profile_sha256", "a" * 64)):
            with self.subTest(field=field), profile_fixture() as item:
                before = item.license_path.read_bytes()
                summary = source_acceptance.accept_source_sizes(item.batch, item.job_path, item.license_path, confirm=True)
                original = core.build_resume_plan(item.batch, item.job_path, item.license_path)
                self.assertEqual(original["source_size_acceptance"]["acceptance_sha256"], summary["acceptance_sha256"])
                path = Path(summary["acceptance_path"])
                value = production.load_json(path)
                value[field] = changed
                value["acceptance_sha256"] = core._canonical_sha256({k: v for k, v in value.items() if k != "acceptance_sha256"})
                production.atomic_json(path, value)
                with self.assertRaises(core.ResumePlanError):
                    core.build_resume_plan(item.batch, item.job_path, item.license_path)
                self.assertEqual(item.license_path.read_bytes(), before)

    def test_terminal_api_failure_can_use_only_remaining_second_attempt(self):
        with profile_fixture() as item:
            target = truncate_to_first_attempt(item)
            plan, auth, session = authorize_resume(item)
            self.assertIn(target, plan["resumable_ids"])
            self.assertEqual((plan["attempts_used"][target], plan["attempts_remaining"][target]), (1, 1))
            contexts = []
            result, _ = run_resume(item, plan, auth, session,
                                   lambda _client, config, _prompt: contexts.append(config["_image_download_context"]) or b"raw")
            selected = [ctx for ctx in contexts if ctx["generation_target_id"] == target]
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["attempt"], 2)
            self.assertEqual(result["requests_used_end"], 8)

    def test_reserved_without_terminal_stays_blocked(self):
        with profile_fixture() as item:
            truncate_to_first_attempt(item, terminal=False)
            with self.assertRaisesRegex(core.ResumePlanError, "结果未知"):
                core.build_resume_plan(item.batch, item.job_path, item.license_path)

    def test_historical_download_failure_does_not_gain_second_attempt(self):
        with profile_fixture() as item:
            target = truncate_to_first_attempt(item, download=True)
            plan = core.build_resume_plan(item.batch, item.job_path, item.license_path)
            self.assertIn(target, plan["exhausted_ids"])
            self.assertNotIn(target, plan["resumable_ids"])
            self.assertEqual(plan["attempts_used"][target], 1)

    def test_acceptance_is_hash_bound_and_adapter_receives_only_task_policy(self):
        with profile_fixture() as item, bound_acceptance(item) as acceptance:
            before = item.license_path.read_bytes()
            plan, auth, session = authorize_resume(item)
            for payload in (plan, production.load_json(auth), production.load_json(session)):
                self.assertEqual(payload["source_size_acceptance"], acceptance)
            result, adapter = run_resume(item, plan, auth, session, lambda *args: b"raw")
            self.assertEqual(result["status"], "completed_with_errors")
            for call in adapter.call_args_list:
                self.assertEqual(call.kwargs["source_size_policy"], acceptance["policy_id"])
                self.assertEqual(call.kwargs["accepted_source_size"], "2352x3520")
                self.assertEqual(call.kwargs["generation"]["generation_profile"], item.config["generation_profile"])
            events = [json.loads(line) for line in item.events_path.read_text().splitlines()]
            new_requests = [event for event in events if event.get("resume") is True
                            and event.get("status") in {"request_reserved", "generated", "request_failed"}]
            self.assertTrue(new_requests)
            for event in new_requests:
                self.assertEqual(event["raw_contract"], acceptance["policy_id"])
                self.assertEqual(event["source_size_acceptance_sha256"], acceptance["acceptance_sha256"])
            after = production.load_json(item.license_path)
            frozen = json.loads(before)
            after.pop("requests_used")
            frozen.pop("requests_used")
            self.assertEqual(after, frozen)

    def test_auth_and_session_reject_changed_or_missing_acceptance(self):
        for target in ("auth", "session"):
            for edit in ("missing", "policy", "job", "profile"):
                with self.subTest(target=target, edit=edit), profile_fixture() as item, bound_acceptance(item):
                    plan, auth, session = authorize_resume(item)
                    path = auth if target == "auth" else session
                    payload = production.load_json(path)
                    if edit == "missing":
                        payload.pop("source_size_acceptance")
                    else:
                        key = {"policy": "policy_id", "job": "job_id", "profile": "generation_profile_sha256"}[edit]
                        payload["source_size_acceptance"][key] = "tampered"
                    production.atomic_json(path, payload)
                    with self.assertRaises(worker.ResumeExecutionError):
                        run_resume(item, plan, auth, session, lambda *args: self.fail("API called"))
                    self.assertEqual(production.load_json(auth)["status"], "active")

    def test_locked_acceptance_change_rejects_before_consumption(self):
        with profile_fixture() as item, bound_acceptance(item) as acceptance:
            plan, auth, session = authorize_resume(item)
            original_lock = worker._acquire_explicit_retry_lock
            def acquire(*args):
                result = original_lock(*args)
                acceptance["confirmed"] = False
                return result
            with patch.object(worker, "_acquire_explicit_retry_lock", side_effect=acquire):
                with self.assertRaises(worker.ResumeExecutionError):
                    run_resume(item, plan, auth, session, lambda *args: self.fail("API called"))
            self.assertEqual(production.load_json(auth)["status"], "active")

    def test_other_job_without_acceptance_keeps_exact_source_contract(self):
        with profile_fixture() as item:
            plan, auth, session = authorize_resume(item)
            self.assertNotIn("source_size_acceptance", plan)
            _, adapter = run_resume(item, plan, auth, session, lambda *args: b"raw")
            self.assertTrue(all("source_size_policy" not in call.kwargs for call in adapter.call_args_list))

    def test_local_materialization_creates_04_without_touching_existing_05(self):
        with profile_fixture() as item:
            deliveries = production._delivery_records(item.plan["records"])
            selected = {int(row["delivery_position"]): row for row in deliveries}
            fourth, fifth = selected[4], selected[5]
            raw = Path(fourth["records"][0]["raw_target"])
            raw.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1024, 1536), "gray").save(raw)
            existing = Path(fifth["target"])
            existing.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", production.parse_size(fifth["final_size"]), "blue").save(existing)
            before = existing.read_bytes()
            def overlay(source, target, *_args, **_kwargs):
                self.assertEqual(Path(target), Path(fourth["target"]))
                Image.new("RGB", production.parse_size(fourth["final_size"]), "gray").save(target)
            successful = set(fourth["generation_target_ids"] + fifth["generation_target_ids"])
            with patch.object(production, "apply_overlays", side_effect=overlay) as render:
                completed = worker._materialize_ready_deliveries(deliveries, successful, item.license["phone"], [])
            self.assertEqual(completed, 2)
            render.assert_called_once()
            self.assertEqual(existing.read_bytes(), before)

    def test_recovered_eighth_request_keeps_nine_used_and_407_remaining(self):
        with profile_fixture(30) as item, bound_acceptance(item):
            events = []
            raw_bytes = b"fixture-existing-raw"
            raw_hash = hashlib.sha256(raw_bytes).hexdigest()
            schedule = [(0, 1), (0, 2), (1, 1), (1, 2), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1)]
            for number, (index, attempt) in enumerate(schedule, 1):
                row = item.plan["manifest_entries"][index]
                identity = {key: row[key] for key in ("generation_target_id", "delivery_target_id", "group_index", "generation_position", "delivery_position")}
                common = {**identity, "attempt": attempt, "request_number": number, "api_key_slot": 1}
                events.append({**common, "status": "request_reserved", "raw_target": row["raw_target"],
                               "delivery_target": row["target"], "effective_prompt_sha256": row["effective_prompt_sha256"],
                               "retry_prompt_variant": "original"})
                if number in (5, 6, 9):
                    raw = item.batch / row["raw_target"]
                    raw.parent.mkdir(parents=True, exist_ok=True)
                    raw.write_bytes(raw_bytes)
                    events.append({**common, "status": "generated", "raw_target": row["raw_target"],
                                   "delivery_target": row["target"], "saved_raw_sha256": raw_hash})
                else:
                    events.append({**common, "status": "request_failed", "will_retry": number in (1, 3, 7),
                                   "error_kind": "raw_contract_rejected" if number == 8 else "transient",
                                   "error_stage": "image_download_open" if number in (3, 4) else "api_generate",
                                   "response_kind": "url" if number in (3, 4) else "unknown"})
            recovered_row = item.plan["manifest_entries"][5]
            recovery = {**{key: recovered_row[key] for key in ("generation_target_id", "delivery_target_id", "group_index", "generation_position", "delivery_position")},
                        "status": "source_size_recovered", "attempt": 1, "request_number": 8,
                        "api_called": False, "request_delta": 0, "saved_raw_sha256": raw_hash}
            raw = item.batch / recovered_row["raw_target"]
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(raw_bytes)
            events.append(recovery)
            item.events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
            for path in (item.job_path, item.license_path):
                value = production.load_json(path)
                value["requests_used"] = 9
                production.atomic_json(path, value)
            with patch.object(source_acceptance, "validated_recoveries", return_value={recovered_row["generation_target_id"]: recovery}):
                plan = core.build_resume_plan(item.batch, item.job_path, item.license_path)
            self.assertEqual(plan["counts"], {"total": 210, "success": 4, "exhausted": 2,
                "balance_recoverable": 0, "unknown": 1, "unattempted": 203, "resumable": 204})
            self.assertEqual((plan["requests_used"], plan["remaining_max_requests"], plan["cumulative_max_requests"], plan["budget"]),
                             (9, 407, 416, 420))
            self.assertEqual(plan["attempts_used"][recovered_row["generation_target_id"]], 1)
            self.assertEqual(sum(event["status"] == "request_failed" for event in events), 6)

    def test_real_recovery_reconciles_failed_count_before_next_group_probe_fails(self):
        with rejected_fixture(30) as item:
            original_events = item.events_path.read_bytes()
            recovery = accept(item)
            self.assertEqual((recovery["request_delta"], recovery["recovered_count"]), (0, 1))
            self.assertEqual(production.load_json(item.job_path)["failed"], 3)
            plan, auth, session = authorize_resume(item)
            self.assertEqual((plan["requests_used"], len(plan["exhausted_ids"]),
                              plan["remaining_max_requests"], plan["cumulative_max_requests"]),
                             (9, 2, 407, 416))
            calls = []

            def fail_probe(client, config, _prompt):
                calls.append((client, config["_image_download_context"]))
                error = RuntimeError("fixture HTTP 400 bad request")
                error.status_code = 400
                raise error

            result, adapter = run_resume(item, plan, auth, session, fail_probe)
            self.assertEqual(len(calls), 1)
            slot, context = calls[0]
            self.assertEqual((slot, context["generation_target_id"], context["request_number"], context["attempt"]),
                             (1, "truck_rescue:v3:g0375:u01", 10, 1))
            self.assertEqual(adapter.call_count, 0)
            self.assertEqual((result["status"], result["requests_used_start"], result["requests_used_end"]),
                             ("paused_resume_probe_failed", 9, 10))
            job = production.load_json(item.job_path)
            self.assertEqual((job["failed"], job["failed_request_attempts"], job["retry_count"], job["requests_used"]),
                             (3, 7, 2, 10))
            license_data = production.load_json(item.license_path)
            self.assertEqual((license_data["requests_used"], license_data["approved_request_budget"]), (10, 420))
            self.assertTrue(item.events_path.read_bytes().startswith(original_events))
            events = core._load_jsonl(item.events_path, "fixture events")
            recoveries = [event for event in events if event.get("status") == "source_size_recovered"]
            self.assertEqual(len(recoveries), 1)
            self.assertEqual((recoveries[0]["request_number"], recoveries[0]["api_called"], recoveries[0]["request_delta"]),
                             (8, False, 0))
            self.assertEqual(sum(event.get("status") == "request_reserved" for event in events), 10)
            self.assertEqual(sum(event.get("status") == "request_failed" for event in events), 7)
            failure = next(event for event in events if event.get("status") == "request_failed" and event["request_number"] == 10)
            self.assertEqual((failure["generation_target_id"], failure["error_kind"], failure["will_retry"]),
                             ("truck_rescue:v3:g0375:u01", "non_retryable", False))


if __name__ == "__main__":
    unittest.main()
