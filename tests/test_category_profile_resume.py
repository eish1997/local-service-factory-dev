"""Real frozen-data fixtures, fake launcher/API only; never production state."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import factory
import generate_truck_rescue_groups as groups
from tools import category_generation_profile as profiles
from tools import category_image_production as production
from tools import category_image_resume as core
from tools import category_image_resume_worker as worker
from tools import category_4k_raw

BASE = {"provider": "relay", "base_url": "https://tinysnow.one/v1", "model": "gpt-image-2.5-flare", "quality": "medium", "api_size": "1024x1536"}
PHONE = "13407128962"


@contextmanager
def profile_fixture(count=1):
    with tempfile.TemporaryDirectory(prefix="profile-resume-") as folder, ExitStack() as stack:
        root = Path(folder)
        batch = root / "prompts/category_batches/truck_rescue/batch_v3_active"
        batch.mkdir(parents=True)
        category = json.loads(groups.CATEGORY_CONFIG_PATH.read_text(encoding="utf-8-sig"))
        rows = groups._build_rows(374, count, 2612, category)[0]
        (batch / "prompts.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        library = root / "projects/truck_rescue/cover_scene_library.json"
        library.parent.mkdir(parents=True)
        shutil.copyfile(groups.COVER_LIBRARY_PATH, library)
        stack.enter_context(patch.object(production, "ROOT", root))
        stack.enter_context(patch.object(production, "CATEGORY_BATCH_ROOT", root / "prompts/category_batches"))
        config = profiles.select_profile(BASE, "truck_rescue", profiles.TINYSNOW_4K_DUAL_SOURCE)
        plan = production.plan("truck_rescue", batch, 374, count, PHONE, config, scope="all", output_root=root / "output/truck_rescue")
        for name, result in (("_category_effective_config", BASE), ("category_active_batch_dir", batch),
                             ("_category_confirmed_phone", PHONE), ("_category_output_root", root / "output/truck_rescue"),
                             ("selected_key_slots", list(range(1, 11))), ("_category_proxy_environment", {"PIPE_CATEGORY_NETWORK_MODE": "fixture"})):
            stack.enter_context(patch.object(factory, name, return_value=result))
        stack.enter_context(patch.object(factory, "_category_sample_range"))
        stack.enter_context(patch.object(factory, "activate_dashboard_session"))
        stack.enter_context(patch.object(factory, "launch_dashboard_compact", return_value=False))
        launch = stack.enter_context(patch.object(factory.subprocess, "Popen", return_value=SimpleNamespace(pid=987654)))
        stack.enter_context(redirect_stdout(io.StringIO()))
        args = factory.build_parser().parse_args([
            "confirm-start-category-images", "--category", "truck_rescue", "--group-start", "374", "--group-count", str(count),
            "--scope", "all", "--phone", PHONE, "--generation-profile", profiles.TINYSNOW_4K_DUAL_SOURCE,
            "--plan-sha256", plan["plan_sha256"], "--max-requests", str(count * 14), "--auto-retry-limit", "1",
            "--max-workers", "10", "--confirm-paid", "--confirm-third-party",
        ])
        if factory.command_confirm_start_category_images(args) != 0:
            raise AssertionError("fixture authorization/start failed")
        license_path = production.license_path("truck_rescue", batch, 374, count, args.created_license_id)
        job_path = next(production.jobs_dir(batch).glob("*.json"))
        lic, job = production.load_json(license_path), production.load_json(job_path)
        lic.update(status="consumed", consumed_at=production.now_iso(), requests_used=2)
        job.update(status="paused_probe_failed", requests_used=2, failed=1, failed_request_attempts=2, retry_count=1, worker_pid=None, pid=None)
        production.atomic_json(license_path, lic)
        production.atomic_json(job_path, job)
        events_path = production.production_dir(batch) / f"events_{job['job_id']}.jsonl"
        record = plan["records"][0]
        identity = {key: record[key] for key in ("generation_target_id", "delivery_target_id", "group_index", "generation_position", "delivery_position")}
        events = []
        for attempt in (1, 2):
            events.append({**identity, "status": "request_reserved", "request_number": attempt, "attempt": attempt, "api_key_slot": 1,
                           "raw_target": plan["manifest_entries"][0]["raw_target"], "delivery_target": plan["manifest_entries"][0]["target"],
                           "effective_prompt_sha256": plan["manifest_entries"][0]["effective_prompt_sha256"], "retry_prompt_variant": "original"})
            events.append({**identity, "status": "request_failed", "request_number": attempt, "attempt": attempt, "api_key_slot": 1,
                           "error_kind": "transient", "will_retry": attempt == 1, "error": "TimeoutError"})
        events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        yield SimpleNamespace(root=root, batch=batch, plan=plan, config=config, license=lic, job=job,
                              license_path=license_path, job_path=job_path, events_path=events_path, launch=launch)


def authorize_resume(item):
    plan = core.build_resume_plan(item.batch, item.job_path, item.license_path)
    args = factory.build_parser().parse_args([
        "resume-category-images", "--category", "truck_rescue", "--job-id", item.job["job_id"],
        "--resume-plan-sha256", plan["resume_plan_sha256"], "--confirm-resume", "--confirm-paid", "--confirm-third-party",
    ])
    if factory.command_resume_category_images(args) != 0:
        raise AssertionError("fixture resume authorization failed")
    auth = next((production.production_dir(item.batch) / "resume_authorizations").glob("*.json"))
    session = production.production_dir(item.batch) / "resume_sessions" / auth.name
    data = production.load_json(session)
    data.update(status="queued", pid=None)
    production.atomic_json(session, data)
    return plan, auth, session


def run_resume(item, plan, auth, session, generator, saver=None):
    def save(path, payload, **kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture-raw")
        return {"saved_raw_sha256": hashlib.sha256(b"fixture-raw").hexdigest(), "source_returned_size": "2336x3520"}
    with (patch.object(category_4k_raw, "save_4k_raw_png", side_effect=saver or save) as adapter,
          patch.object(production, "save_raw_png", side_effect=AssertionError("legacy adapter used")),
          patch.object(worker, "_materialize_ready_deliveries", side_effect=lambda deliveries, ids, *_args:
                       sum(set(row["generation_target_ids"]).issubset(ids) for row in deliveries))):
        result = worker.resume_category_images(item.batch, item.job_path, item.license_path, auth, plan["resume_plan_sha256"],
                                              session_path=session, clients=[(i, i) for i in range(1, 11)], generate_one=generator, config=BASE)
    return result, adapter


class CategoryProfileResumeTests(unittest.TestCase):
    def test_30_groups_keep_exhausted_cover_and_exact_418_plus_two_budget(self):
        with profile_fixture(30) as item:
            plan = core.build_resume_plan(item.batch, item.job_path, item.license_path)
            self.assertEqual(plan["counts"], dict(total=210, success=0, exhausted=1, balance_recoverable=0, unknown=0, unattempted=209, resumable=209))
            self.assertEqual((plan["requests_used"], plan["remaining_max_requests"], plan["cumulative_max_requests"], plan["budget"]), (2, 418, 420, 420))
            self.assertEqual(plan["exhausted_ids"], ["truck_rescue:v3:g0374:u01"])
            self.assertEqual(plan["generation_profile"], item.config["generation_profile"])
            self.assertEqual(plan["profile_max_workers"], 10)
            self.assertEqual(factory._validated_category_resume_plan(plan)["additional_recovery_request_budget"], 0)

    def test_profile_and_complete_overlay_are_fail_closed(self):
        for target in ("profile", "overlay", "raw_size", "job_profile", "sdk_retries", "fixed_policy"):
            with self.subTest(target=target), profile_fixture() as item:
                if target == "overlay":
                    path = Path(item.license["overlay_plan"])
                    value = production.load_json(path)
                    value["cover_styles_by_group"]["374"]["phone_ink"][0] = 0
                    production.atomic_json(path, value)
                elif target == "job_profile":
                    value = production.load_json(item.job_path)
                    value.pop("generation_profile")
                    production.atomic_json(item.job_path, value)
                elif target == "profile":
                    value = production.load_json(item.license_path)
                    value["generation_profile"]["accepted_source_sizes"] = ["2344x3520"]
                    production.atomic_json(item.license_path, value)
                elif target in {"sdk_retries", "fixed_policy"}:
                    value = production.load_json(item.license_path)
                    value["sdk_max_retries" if target == "sdk_retries" else "concurrency_policy"] = 1 if target == "sdk_retries" else "fixed_10_v1"
                    production.atomic_json(item.license_path, value)
                else:
                    path = Path(item.license["production_manifest"])
                    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                    rows[0]["raw_api_size"] = "2560x3840"
                    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
                with self.assertRaises((ValueError, core.ResumePlanError)):
                    core.build_resume_plan(item.batch, item.job_path, item.license_path)

    def test_public_resume_binds_profile_session_and_adaptive_not_fixed(self):
        with profile_fixture() as item:
            before = item.license_path.read_bytes()
            plan, auth, session = authorize_resume(item)
            for path in (auth, session):
                payload = production.load_json(path)
                self.assertEqual(payload["generation_profile"], plan["generation_profile"])
                self.assertEqual(payload["resume_policy"], core.PROFILE_RESUME_POLICY)
                self.assertEqual(payload["max_workers"], plan["profile_max_workers"])
            self.assertEqual(item.license_path.read_bytes(), before)
            self.assertEqual(BASE["model"], "gpt-image-2.5-flare")

    def test_worker_restores_4k_skips_exhausted_and_ramps_adaptively(self):
        with profile_fixture(5) as item:
            plan, auth, session = authorize_resume(item)
            calls = []
            def generate(client, config, prompt):
                self.assertEqual({key: value for key, value in config.items() if key != "_image_download_context"}, item.config)
                context = config["_image_download_context"]
                self.assertEqual(context["job_id"], item.job["job_id"])
                self.assertEqual(context["license_id"], item.license["license_id"])
                self.assertEqual(context["original_plan_sha256"], item.license["plan_sha256"])
                self.assertEqual(context["effective_prompt_sha256"], hashlib.sha256(prompt.encode("utf-8")).hexdigest())
                calls.append(prompt)
                return b"source"
            result, adapter = run_resume(item, plan, auth, session, generate)
            self.assertEqual(len(calls), 34)
            self.assertNotIn(item.plan["manifest_entries"][0]["effective_prompt"], calls)
            self.assertEqual(result["requests_used_end"], 36)
            self.assertEqual(result["status"], "completed_with_errors")
            for call in adapter.call_args_list:
                self.assertEqual(call.kwargs["accepted_source_size"], "2352x3520")
                self.assertEqual(call.kwargs["accepted_source_width_tolerance"], 16)
            history = production.load_json(item.job_path)["resume_concurrency_history"]
            self.assertEqual([row["worker_count"] for row in history[:5]], [1, 4, 6, 8, 10])
            self.assertTrue(all(row["phase"] == "resume_adaptive" for row in history[1:]))
            job = production.load_json(item.job_path)
            self.assertEqual((job["completed"], job["failed"]), (24, 1))
            terminal = production.load_json(Path(result["terminal_evidence"]))
            self.assertEqual(terminal["preexisting_exhausted_ids"], plan["exhausted_ids"])

    def test_209_successes_finish_149_deliveries_with_original_failure(self):
        with profile_fixture(30) as item:
            plan, auth, session = authorize_resume(item)
            result, adapter = run_resume(item, plan, auth, session, lambda *args: b"source")
            self.assertEqual(adapter.call_count, 209)
            job = production.load_json(item.job_path)
            self.assertEqual((job["status"], job["completed"], job["failed"], job["requests_used"]),
                             ("completed_with_errors", 149, 1, 211))
            terminal = production.load_json(Path(result["terminal_evidence"]))
            self.assertEqual(terminal["preexisting_exhausted_ids"], ["truck_rescue:v3:g0374:u01"])

    def test_launcher_transition_at_lock_is_allowed_but_wrong_pid_rejected(self):
        for wrong_pid in (False, True):
            with self.subTest(wrong_pid=wrong_pid), profile_fixture() as item:
                plan, auth, session = authorize_resume(item)
                original_lock = worker._acquire_explicit_retry_lock
                def lock_and_publish(*args):
                    acquired = original_lock(*args)
                    value = production.load_json(session)
                    value.update(status="starting", pid=os.getpid() + 999999 if wrong_pid else os.getpid(),
                                 updated_at=production.now_iso(), launch_mode="independent_process")
                    production.atomic_json(session, value)
                    return acquired
                with patch.object(worker, "_acquire_explicit_retry_lock", side_effect=lock_and_publish):
                    if wrong_pid:
                        with self.assertRaises(worker.ResumeExecutionError):
                            run_resume(item, plan, auth, session, lambda *args: self.fail("API called"))
                        self.assertEqual(production.load_json(auth)["status"], "active")
                    else:
                        result, _ = run_resume(item, plan, auth, session, lambda *args: b"source")
                        self.assertEqual(result["status"], "completed_with_errors")

    def test_bad_source_probe_keeps_evidence_and_pauses_without_retry(self):
        with profile_fixture() as item:
            plan, auth, session = authorize_resume(item)
            calls = []
            def reject(*args, **kwargs):
                raise production.RawImageContractError("size", evidence={"source_returned_size": "2344x3520"})
            result, _ = run_resume(item, plan, auth, session, lambda *args: calls.append(args) or b"source", reject)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["requests_used_end"], 3)
            job = production.load_json(item.job_path)
            self.assertEqual(job["checkpoint"]["reason"], "raw_contract_rejected")
            self.assertEqual(job["checkpoint"]["remaining_request_budget"], 11)

    def test_bad_source_inside_stage_drains_and_stops_before_next_stage(self):
        with profile_fixture(2) as item:
            plan, auth, session = authorize_resume(item)
            calls, save_calls = [], []
            gate = threading.Lock()
            def save(path, payload, **kwargs):
                with gate:
                    save_calls.append(path)
                    if len(save_calls) == 2:
                        raise production.RawImageContractError("size", evidence={"source_returned_size": "2344x3520"})
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"raw")
                return {"saved_raw_sha256": hashlib.sha256(b"raw").hexdigest()}
            result, _ = run_resume(item, plan, auth, session, lambda *args: calls.append(args) or b"source", save)
            self.assertEqual(result["status"], "paused_api_errors")
            self.assertLessEqual(len(calls), 5)
            job = production.load_json(item.job_path)
            self.assertEqual(len(job["resume_concurrency_history"]), 2)
            self.assertEqual(job["checkpoint"]["reason"], "raw_contract_rejected")

    def test_profile_is_rechecked_after_lock_before_authorization_consumption(self):
        with profile_fixture() as item:
            plan, auth, session = authorize_resume(item)
            original_lock = worker._acquire_explicit_retry_lock
            def lock_and_tamper(*args):
                acquired = original_lock(*args)
                value = production.load_json(item.license_path)
                value["generation_profile"]["quality"] = "high"
                production.atomic_json(item.license_path, value)
                return acquired
            with patch.object(worker, "_acquire_explicit_retry_lock", side_effect=lock_and_tamper):
                with self.assertRaises(worker.ResumeExecutionError):
                    run_resume(item, plan, auth, session, lambda *args: self.fail("API called"))
            self.assertEqual(production.load_json(auth)["status"], "active")
            self.assertEqual(production.load_json(item.license_path)["requests_used"], 2)

    def test_inherited_quarantine_is_bound_and_never_used(self):
        with profile_fixture() as item:
            job = production.load_json(item.job_path)
            job["quarantined_api_key_slots"] = [1]
            production.atomic_json(item.job_path, job)
            plan, auth, session = authorize_resume(item)
            self.assertEqual(plan["profile_quarantined_api_key_slots"], [1])
            calls = []
            run_resume(item, plan, auth, session, lambda slot, *_args: calls.append(slot) or b"source")
            self.assertNotIn(1, calls)

    def test_balance_failover_cannot_expand_original_budget(self):
        with profile_fixture() as item:
            plan, auth, session = authorize_resume(item)
            calls, seen = [], set()
            def generate(client, config, prompt):
                calls.append(client)
                if client == 1:
                    raise RuntimeError("INSUFFICIENT_BALANCE")
                if prompt not in seen:
                    seen.add(prompt)
                    error = RuntimeError("transient")
                    error.status_code = 503
                    raise error
                return b"source"
            result, _ = run_resume(item, plan, auth, session, generate)
            self.assertEqual(result["requests_used_end"], 14)
            self.assertEqual(len(calls), 12)
            self.assertEqual(calls.count(1), 1)
            job = production.load_json(item.job_path)
            self.assertEqual(job["status"], "paused_request_budget")
            self.assertEqual(job["checkpoint"]["remaining_request_budget"], 0)
            self.assertEqual(job["quarantined_api_key_slots"], [1])
            self.assertEqual(production.load_json(item.license_path)["approved_request_budget"], 14)

    def test_auth_or_session_tampering_fails_before_consumption_or_api(self):
        for target in ("auth", "session"):
            with self.subTest(target=target), profile_fixture() as item:
                plan, auth, session = authorize_resume(item)
                path = auth if target == "auth" else session
                payload = production.load_json(path)
                payload["generation_profile"]["api_size"] = "1024x1536"
                production.atomic_json(path, payload)
                with self.assertRaises(worker.ResumeExecutionError):
                    run_resume(item, plan, auth, session, lambda *args: self.fail("API called"))
                self.assertEqual(production.load_json(auth)["status"], "active")
                self.assertEqual(production.load_json(item.license_path)["requests_used"], 2)


if __name__ == "__main__":
    unittest.main()
