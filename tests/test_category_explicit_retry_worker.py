from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_category_explicit_retry import make_case, rehash
from tests.test_category_image_resume_worker import write_json
from tools import category_4k_raw
from tools import category_image_resume_worker as worker
from tools.category_explicit_retry import apply_explicit_retry


PROXY = "http://127.0.0.1:7897"
NETWORK_ENV = {
    "PIPE_CATEGORY_NETWORK_MODE": "proxy:" + PROXY,
    "HTTP_PROXY": PROXY, "HTTPS_PROXY": PROXY, "ALL_PROXY": "",
    "http_proxy": PROXY, "https_proxy": PROXY, "all_proxy": "", "NO_PROXY": "", "no_proxy": "",
}


class ExplicitWorkerFixture:
    def __init__(self, root: Path):
        case = make_case()
        self.batch = root / "batch_v3_fixture"
        self.base_plan, self.license = case["plan"], case["license"]
        self.previous, self.initial_events, self.ids = case["previous"], case["events"], case["ids"]
        self.authorization_id = "resume-" + "a" * 24
        production = self.batch / "production"
        self.job_path = production / "jobs" / (self.base_plan["job_id"] + ".json")
        self.license_path = production / "licenses" / (self.base_plan["license_id"] + ".json")
        self.manifest_path = production / "manifests" / "frozen.jsonl"
        self.overlay_path = production / "overlays" / "frozen.json"
        self.events_path = production / ("events_" + self.base_plan["job_id"] + ".jsonl")
        self.authorization_path = production / "resume_authorizations" / (self.authorization_id + ".json")
        self.previous_path = self.authorization_path.parent / (self.previous["authorization_id"] + ".json")
        self.session_path = production / "resume_sessions" / (self.authorization_id + ".json")
        self.previous_session_path = self.session_path.parent / (self.previous["authorization_id"] + ".json")
        self.lock_path = production / "generation.lock"
        self.records = []
        for target_id in self.base_plan["attempts_used"]:
            group, pos = int(target_id.split(":g")[1][:4]), int(target_id[-2:])
            dpos = 1 if pos == 1 else 2 if pos in (2, 3, 4) else pos - 2
            delivery = f"truck_rescue:v3:g{group:04d}:d{dpos:02d}"
            self.records.append({
                "category_id": "truck_rescue", "generation_target_id": target_id,
                "delivery_target_id": delivery, "group_index": group,
                "generation_position": pos, "delivery_position": dpos,
                "generation_kind": "cover" if pos == 1 else "triptych_panel" if pos in (2, 3, 4) else "detail",
                "panel_index": pos - 1, "frozen_effective_prompt": "ORIGINAL:" + target_id,
                "target": str(root / "output" / f"{group}_{dpos}.png"),
                "legacy_target": str(root / "legacy" / f"{group}_{dpos}.png"),
                "raw_target": str(root / "raw" / f"{group}_{pos}.png"),
                "final_size": "1024x1536", "service_items": ["货车救援"],
            })
        by_id = {record["generation_target_id"]: record for record in self.records}
        for event in self.initial_events:
            if event["status"] == "request_reserved":
                event["effective_prompt_sha256"] = hashlib.sha256(
                    by_id[event["generation_target_id"]]["frozen_effective_prompt"].encode()
                ).hexdigest()
        self.selected_paths = {by_id[target]["target"] for target in self.ids}
        self.reusable_paths = {record["target"] for record in self.records} - self.selected_paths
        self.materialized = []
        self.manifest_path.parent.mkdir(parents=True)
        self.manifest_path.write_text("{}\n", encoding="utf-8")
        write_json(self.overlay_path, {"phone": "13437186038"})
        self.events_path.write_text("".join(json.dumps(event) + "\n" for event in self.initial_events), encoding="utf-8")
        self.base_plan.update(
            frozen_manifest_sha256=worker._file_sha256(self.manifest_path),
            frozen_overlay_sha256=worker._file_sha256(self.overlay_path),
            events_sha256=worker._file_sha256(self.events_path),
        )
        self.previous.update({key: self.base_plan[key] for key in ("frozen_manifest_sha256", "frozen_overlay_sha256")})
        self.license.update(
            production_manifest=str(self.manifest_path), overlay_plan=str(self.overlay_path),
            manifest_sha256=self.base_plan["frozen_manifest_sha256"], phone="13437186038",
        )
        self.job = {
            "job_id": self.base_plan["job_id"], "license_id": self.base_plan["license_id"],
            "status": "completed_with_errors", "pid": None, "worker_pid": None,
            "resume_authorization_id": self.previous["authorization_id"],
            "network_mode": NETWORK_ENV["PIPE_CATEGORY_NETWORK_MODE"],
            "requests_used": 713, "failed": 2, "completed": 498,
        }
        write_json(self.job_path, self.job)
        write_json(self.license_path, self.license)
        write_json(self.previous_path, self.previous)
        previous_session = {
            "schema_version": 1, "kind": "category-image-resume-session",
            "authorization_id": self.previous["authorization_id"], "job_id": self.job["job_id"],
            "license_id": self.job["license_id"], "resume_plan_sha256": self.previous["resume_plan_sha256"],
            "status": "completed_with_errors", "pid": None,
        }
        write_json(self.previous_session_path, previous_session)
        rehash(self.base_plan)
        self.plan = apply_explicit_retry(self.base_plan, self.license, self.initial_events, self.previous, self.ids)
        plan = self.plan
        self.authorization = {key: deepcopy(plan[key]) for key in (
            "job_id", "license_id", "category_id", "batch_id", "resume_plan_sha256", "frozen_manifest_sha256",
            "frozen_overlay_sha256", "events_sha256", "event_tail_sha256", "requests_used", "max_attempts",
            "retry_policy", "provider", "model", "quality", "size", "generation_migration", "explicit_retry",
        )}
        self.authorization.update(
            schema_version=1, kind=worker.AUTHORIZATION_KIND, authorization_id=self.authorization_id,
            status="active", one_time=True, created_at="2026-09-28T00:00:00+08:00",
            approved_remaining_request_budget=2, approved_cumulative_request_budget=715,
            approved_resumable_count=2, approved_resumable_ids_sha256=worker._canonical_sha256(self.ids),
            original_plan_sha256=self.license["plan_sha256"], original_approved_request_budget=1400,
            original_license_sha256=worker._file_sha256(self.license_path),
            original_job_sha256=worker._file_sha256(self.job_path),
            approved_exhausted_count=0, approved_exhausted_ids_sha256=worker._canonical_sha256([]),
            approved_balance_recoverable_count=0, approved_balance_recoverable_ids_sha256=worker._canonical_sha256([]),
            approved_balance_failure_request_count=10, approved_additional_recovery_request_budget=0,
            attempts_used_sha256=worker._canonical_sha256(plan["attempts_used"]),
            attempts_remaining_sha256=worker._canonical_sha256(plan["attempts_remaining"]),
            per_target_attempts_sha256=worker._canonical_sha256({"used": plan["attempts_used"], "remaining": plan["attempts_remaining"]}),
            base_url=self.license["base_url"], max_workers=1, api_key_slots=[7, 9],
            resume_policy=worker.SERIAL_RESUME_POLICY, resume_confirmed=True, paid_confirmed=True,
            third_party_confirmed=True, generation_migration_confirmed=True, explicit_retry_confirmed=True,
            previous_resume_session_sha256=worker._file_sha256(self.previous_session_path),
            explicit_retry_network_mode=self.job["network_mode"],
        )
        write_json(self.authorization_path, self.authorization)
        write_json(self.session_path, dict(previous_session, authorization_id=self.authorization_id,
                                         resume_plan_sha256=plan["resume_plan_sha256"], status="queued",
                                         created_at="2026-09-28T00:00:00+08:00"))

    def materialize(self, delivery, *args, **kwargs):
        assert delivery["target"] in self.selected_paths, "historical image rewritten"
        assert kwargs == {"allow_rejected_replacement": False}
        self.materialized.append(delivery["target"])
        self.reusable_paths.add(delivery["target"])

    def events(self):
        return [json.loads(line) for line in self.events_path.read_text(encoding="utf-8").splitlines()]

    def run(self, generator, *, env=None, clients=None, saver=None):
        network_env = dict(NETWORK_ENV, **(env or {}))
        for upper, lower in (("HTTP_PROXY", "http_proxy"), ("HTTPS_PROXY", "https_proxy"), ("NO_PROXY", "no_proxy")):
            if env and upper in env:
                network_env[lower] = env[upper]
        with (
            patch.dict(os.environ, network_env),
            patch.object(worker.category_image_resume, "build_resume_plan", return_value=deepcopy(self.base_plan)),
            patch.object(worker.production, "load_frozen_manifest_runtime_records", return_value=deepcopy(self.records)),
            patch.object(worker.production, "reusable_target", side_effect=lambda path, size: str(path) in self.reusable_paths),
            patch.object(worker.production, "_materialize_delivery", side_effect=self.materialize),
            patch.object(category_4k_raw, "save_4k_raw_png", side_effect=saver or (lambda *a, **kw: {"saved_raw_sha256": "f" * 64})) as save,
            patch.object(worker, "ThreadPoolExecutor", side_effect=AssertionError("must stay serial")),
            patch.object(worker.production, "content_policy_retry_for_record", side_effect=AssertionError("must keep original prompt")),
            patch.object(worker.production, "acquire_lock", side_effect=AssertionError("must never clear old lock")),
        ):
            result = worker.resume_category_images(
                self.batch, self.job_path, self.license_path, self.authorization_path,
                self.plan["resume_plan_sha256"], session_path=self.session_path,
                clients=clients or [(7, 7), (9, 9)], generate_one=generator,
                config={"provider": "relay", "base_url": "https://tinysnow.one/v1", "model": "gpt-image-2.5-flare",
                        "quality": "medium", "api_size": "1024x1536"},
            )
            return result, save


class CategoryExplicitRetryWorkerTests(unittest.TestCase):
    def test_two_original_attempts_exact_slots_caps_and_no_historical_materialization(self):
        with tempfile.TemporaryDirectory() as folder:
            item = ExplicitWorkerFixture(Path(folder))
            previous_bytes = item.previous_path.read_bytes(), item.previous_session_path.read_bytes()
            calls = []
            result, saver = item.run(lambda slot, config, prompt: calls.append((slot, deepcopy(config), prompt)) or b"image")
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual([call[0] for call in calls], [7, 9])
            self.assertEqual([call[2] for call in calls], ["ORIGINAL:" + target for target in item.ids])
            self.assertEqual({call[1]["model"] for call in calls}, {"gpt-image-2-4k"})
            self.assertEqual(saver.call_count, 2)
            for call in saver.call_args_list:
                self.assertEqual(call.kwargs["accepted_source_size"], "2352x3520")
                self.assertEqual(call.kwargs["accepted_source_width_tolerance"], 16)
            reserved = [event for event in item.events() if event["status"] == "request_reserved"][-2:]
            self.assertEqual([event["request_number"] for event in reserved], [714, 715])
            self.assertEqual([event["attempt"] for event in reserved], [2, 2])
            self.assertEqual([event["retry_prompt_variant"] for event in reserved], ["original", "original"])
            self.assertEqual(set(item.materialized), item.selected_paths)
            job = json.loads(item.job_path.read_text(encoding="utf-8"))
            self.assertEqual((job["completed"], job["failed"]), (500, 0))
            license_data = json.loads(item.license_path.read_text(encoding="utf-8"))
            self.assertEqual((license_data["requests_used"], license_data["model"]), (715, "gpt-image-2.5-flare"))
            self.assertEqual(previous_bytes, (item.previous_path.read_bytes(), item.previous_session_path.read_bytes()))
            self.assertFalse(item.lock_path.exists())

    def test_any_first_failure_stops_without_prompt_rewrite_retry_or_key_failover(self):
        for kind in ("non_retryable", "transient", "content_policy", "balance_exhausted"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                item = ExplicitWorkerFixture(Path(folder))
                generator = Mock(side_effect=RuntimeError("synthetic rejection"))
                with patch.object(worker.production, "classify_request_error", return_value=kind):
                    result, _ = item.run(generator)
                self.assertEqual(result["status"], "paused_api_errors")
                self.assertEqual(generator.call_count, 1)
                self.assertEqual(generator.call_args.args[0], 7)
                self.assertEqual(result["requests_used_end"], 714)
                job = json.loads(item.job_path.read_text(encoding="utf-8"))
                self.assertEqual((job["completed"], job["failed"]), (498, 2))
                event = [e for e in item.events() if e["status"] == "request_failed"][-1]
                self.assertFalse(event["will_retry"])
                self.assertFalse(event["api_key_failover_eligible"])
                self.assertEqual(event["error_kind"], kind)

    def test_second_failure_keeps_first_success_and_reports_one_unresolved(self):
        with tempfile.TemporaryDirectory() as folder:
            item = ExplicitWorkerFixture(Path(folder))
            generator = Mock(side_effect=[b"image", RuntimeError("synthetic")])
            result, _ = item.run(generator)
            self.assertEqual(result["status"], "paused_api_errors")
            self.assertEqual(generator.call_count, 2)
            job = json.loads(item.job_path.read_text(encoding="utf-8"))
            self.assertEqual((job["completed"], job["failed"], job["requests_used"]), (499, 1, 715))

    def assert_preflight_failure(self, item, **kwargs):
        generator = Mock(return_value=b"never")
        with self.assertRaises((worker.ResumeExecutionError, worker.category_image_resume.ResumePlanError)):
            item.run(generator, **kwargs)
        generator.assert_not_called()
        self.assertEqual(json.loads(item.authorization_path.read_text(encoding="utf-8"))["status"], "active")

    def test_dead_and_malformed_locks_are_never_deleted_or_consumed(self):
        for payload in (b'{"pid":0,"job_id":"old"}', b"not-json"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as folder:
                item = ExplicitWorkerFixture(Path(folder))
                item.lock_path.write_bytes(payload)
                self.assert_preflight_failure(item)
                self.assertEqual(item.lock_path.read_bytes(), payload)

    def test_changed_previous_session_after_lock_rejected_before_consumption(self):
        with tempfile.TemporaryDirectory() as folder:
            item = ExplicitWorkerFixture(Path(folder))
            acquire = worker._acquire_explicit_retry_lock
            def tamper(*args):
                result = acquire(*args)
                item.previous_session_path.write_text("{}", encoding="utf-8")
                return result
            with patch.object(worker, "_acquire_explicit_retry_lock", side_effect=tamper):
                self.assert_preflight_failure(item)
            self.assertFalse(item.lock_path.exists())

    def test_historical_invalid_output_cannot_be_rewritten(self):
        with tempfile.TemporaryDirectory() as folder:
            item = ExplicitWorkerFixture(Path(folder))
            item.reusable_paths.pop()
            self.assert_preflight_failure(item)
            self.assertEqual(item.materialized, [])

    def test_changed_route_slot_prompt_or_existing_selected_output_is_rejected(self):
        for mutation in ("network", "bypass", "slots", "prompt", "output"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                item = ExplicitWorkerFixture(Path(folder))
                kwargs = {}
                if mutation == "network": kwargs["env"] = {"HTTPS_PROXY": "http://other:123"}
                if mutation == "bypass": kwargs["env"] = {"NO_PROXY": ".tinysnow.one"}
                if mutation == "slots": kwargs["clients"] = [(9, 9), (7, 7)]
                if mutation == "prompt":
                    next(record for record in item.records if record["generation_target_id"] == item.ids[0])["frozen_effective_prompt"] += "changed"
                if mutation == "output":
                    output = Path(next(iter(item.selected_paths)))
                    output.parent.mkdir(parents=True)
                    output.write_bytes(b"preserve existing")
                self.assert_preflight_failure(item, **kwargs)


if __name__ == "__main__":
    unittest.main()
