from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tools import category_image_resume_worker as worker


CONFIG = {
    "provider": "relay",
    "base_url": "https://example.invalid/v1",
    "model": "gpt-image-2",
    "quality": "medium",
    "api_size": "1024x1536",
}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ResumeWorkerFixture:
    def __init__(
        self,
        root: Path,
        *,
        success: int = 0,
        exhausted: int = 0,
        unknown: int = 0,
        unattempted: int = 1,
        budget: int | None = None,
        max_workers: int = 4,
    ) -> None:
        self.batch = root / "truck_rescue" / "batch_worker_fixture"
        production = self.batch / "production"
        self.job_id = "job-worker-fixture"
        self.license_id = "license-worker-fixture"
        self.authorization_id = "resume-auth-fixture"
        self.job_path = production / "jobs" / f"{self.job_id}.json"
        self.license_path = production / "licenses" / f"{self.license_id}.json"
        self.manifest_path = production / "manifests" / f"{self.license_id}.jsonl"
        self.authorization_path = (
            production / "resume_authorizations" / f"{self.authorization_id}.json"
        )
        self.session_path = production / "resume_sessions" / f"{self.authorization_id}.json"
        self.events_path = production / f"events_{self.job_id}.jsonl"
        self.batch.mkdir(parents=True)
        counts = {
            "success": success,
            "exhausted": exhausted,
            "unknown": unknown,
            "unattempted": unattempted,
        }
        self.classes: dict[str, str] = {}
        self.records: list[dict] = []
        index = 0
        for class_name, count in counts.items():
            for _ in range(count):
                index += 1
                target_id = f"truck_rescue:v3:g0044:u{index + 1:02d}"
                self.classes[target_id] = class_name
                self.records.append(
                    {
                        "category_id": "truck_rescue",
                        "generation_target_id": target_id,
                        "delivery_target_id": f"truck_rescue:v3:g0044:d{index + 1:02d}",
                        "group_index": 44,
                        "generation_position": index + 1,
                        "delivery_position": index + 1,
                        "generation_kind": "detail",
                        "service_role": "货车换轮胎",
                        "scene": {
                            "vehicle": "中型货车",
                            "location": "普通维修作业位",
                            "action": "工作人员安装匹配车轮并紧固螺母",
                            "tools": "轮挡、支撑架和扭力扳手",
                        },
                        "frozen_effective_prompt": f"ORIGINAL:{target_id}",
                        "target": str(
                            worker.production.ROOT
                            / "output"
                            / "truck_rescue"
                            / "group_0044"
                            / f"{index + 1:02d}_detail.png"
                        ),
                        "raw_target": str(
                            self.batch / "raw" / "group_0044" / f"{index + 1:02d}.png"
                        ),
                        "legacy_target": str(
                            self.batch / "images" / "group_0044" / f"{index + 1:02d}.png"
                        ),
                        "final_size": "1024x1536",
                        "height_profile_id": "height_1536",
                        "triptych_layout_id": None,
                        "service_items": ["货车救援"],
                    }
                )
        self.ids = [record["generation_target_id"] for record in self.records]
        self.success_ids = [key for key in self.ids if self.classes[key] == "success"]
        self.exhausted_ids = [key for key in self.ids if self.classes[key] == "exhausted"]
        self.unknown_ids = [key for key in self.ids if self.classes[key] == "unknown"]
        self.unattempted_ids = [key for key in self.ids if self.classes[key] == "unattempted"]
        self.resumable_ids = self.unknown_ids + self.unattempted_ids
        self.attempts_used = {
            key: {"success": 1, "exhausted": 2, "unknown": 1, "unattempted": 0}[
                self.classes[key]
            ]
            for key in self.ids
        }
        self.attempts_remaining = {
            key: {"success": 0, "exhausted": 0, "unknown": 1, "unattempted": 2}[
                self.classes[key]
            ]
            for key in self.ids
        }
        requests_used = sum(self.attempts_used.values())
        remaining = sum(self.attempts_remaining.values())
        cumulative = requests_used + remaining
        self.plan = {
            "schema_version": 1,
            "job_id": self.job_id,
            "license_id": self.license_id,
            "category_id": "truck_rescue",
            "batch_id": self.batch.name,
            "group_start": 44,
            "group_count": 1,
            "scope": "details",
            "provider": "relay",
            "model": CONFIG["model"],
            "quality": CONFIG["quality"],
            "size": CONFIG["api_size"],
            "max_attempts": 2,
            "retry_policy": "classified_once_v1",
            "budget": cumulative if budget is None else budget,
            "requests_used": requests_used,
            "remaining_max_requests": remaining,
            "cumulative_max_requests": cumulative,
            "counts": {
                "total": len(self.ids),
                "success": success,
                "exhausted": exhausted,
                "balance_recoverable": 0,
                "unknown": unknown,
                "unattempted": unattempted,
                "resumable": len(self.resumable_ids),
            },
            "success_ids": self.success_ids,
            "exhausted_ids": self.exhausted_ids,
            "balance_recoverable_ids": [],
            "unknown_ids": self.unknown_ids,
            "unattempted_ids": self.unattempted_ids,
            "resumable_ids": self.resumable_ids,
            "attempts_used": self.attempts_used,
            "attempts_remaining": self.attempts_remaining,
            "balance_failure_request_count": 0,
            "frozen_manifest_sha256": "1" * 64,
            "frozen_overlay_sha256": "2" * 64,
            "events_sha256": "3" * 64,
            "event_tail_sha256": "4" * 64,
            "resume_plan_sha256": "5" * 64,
        }
        api_key_slot_count = max(4, max_workers)
        self.license = {
            "status": "consumed",
            "one_time": True,
            "license_id": self.license_id,
            "provider": CONFIG["provider"],
            "base_url": CONFIG["base_url"],
            "model": CONFIG["model"],
            "quality": CONFIG["quality"],
            "size": CONFIG["api_size"],
            "phone": "13407128962",
            "manifest_sha256": "a" * 64,
            "production_manifest": str(self.manifest_path.resolve()),
            "api_key_slots": list(range(1, api_key_slot_count + 1)),
            "requests_used": requests_used,
            "approved_request_budget": self.plan["budget"],
            "plan_sha256": "b" * 64,
        }
        self.job = {
            "job_id": self.job_id,
            "license_id": self.license_id,
            "status": "running",
            "requests_used": requests_used,
            "failed": exhausted,
            "failed_request_attempts": exhausted * 2,
            "retry_count": exhausted,
            "relay_normalized_responses": 0,
        }
        # The factory binds the pre-consumption bytes of the original job and
        # license.  Compute those only after both payloads are final.
        self.authorization = {
            "schema_version": 1,
            "kind": worker.AUTHORIZATION_KIND,
            "authorization_id": self.authorization_id,
            "status": "active",
            "one_time": True,
            "job_id": self.job_id,
            "license_id": self.license_id,
            "category_id": "truck_rescue",
            "batch_id": self.batch.name,
            "resume_plan_sha256": self.plan["resume_plan_sha256"],
            "frozen_manifest_sha256": self.plan["frozen_manifest_sha256"],
            "frozen_overlay_sha256": self.plan["frozen_overlay_sha256"],
            "events_sha256": self.plan["events_sha256"],
            "event_tail_sha256": self.plan["event_tail_sha256"],
            "requests_used": requests_used,
            "approved_remaining_request_budget": remaining,
            "approved_cumulative_request_budget": cumulative,
            "approved_resumable_count": len(self.resumable_ids),
            "approved_resumable_ids_sha256": worker._canonical_sha256(self.resumable_ids),
            "original_plan_sha256": self.license["plan_sha256"],
            "original_approved_request_budget": self.plan["budget"],
            "approved_exhausted_count": len(self.exhausted_ids),
            "approved_exhausted_ids_sha256": worker._canonical_sha256(self.exhausted_ids),
            "approved_balance_recoverable_count": len(
                self.plan.get("balance_recoverable_ids", [])
            ),
            "approved_balance_recoverable_ids_sha256": worker._canonical_sha256(
                self.plan.get("balance_recoverable_ids", [])
            ),
            "approved_balance_failure_request_count": int(
                self.plan.get("balance_failure_request_count", 0)
            ),
            "approved_additional_recovery_request_budget": max(
                0, int(cumulative) - int(self.plan["budget"])
            ),
            "attempts_used_sha256": worker._canonical_sha256(self.attempts_used),
            "attempts_remaining_sha256": worker._canonical_sha256(self.attempts_remaining),
            "per_target_attempts_sha256": worker._canonical_sha256(
                {"used": self.attempts_used, "remaining": self.attempts_remaining}
            ),
            "max_attempts": 2,
            "retry_policy": "classified_once_v1",
            "provider": CONFIG["provider"],
            "base_url": CONFIG["base_url"],
            "model": CONFIG["model"],
            "quality": CONFIG["quality"],
            "size": CONFIG["api_size"],
            "max_workers": max_workers,
            "resume_policy": (
                worker.SERIAL_RESUME_POLICY
                if max_workers == 1
                else (
                    worker.FIXED_TEN_RESUME_POLICY
                    if max_workers == 10
                    else worker.PARALLEL_RESUME_POLICY
                )
            ),
            "resume_confirmed": True,
            "paid_confirmed": True,
            "third_party_confirmed": True,
            "created_at": "2026-08-12T10:00:00+00:00",
        }
        if max_workers == 10:
            self.authorization["api_key_slots"] = self.license["api_key_slots"][:10]
        self.session = {
            "schema_version": 1,
            "kind": "category-image-resume-session",
            "authorization_id": self.authorization_id,
            "job_id": self.job_id,
            "license_id": self.license_id,
            "resume_plan_sha256": self.plan["resume_plan_sha256"],
            "status": "queued",
            "pid": None,
            "created_at": "2026-08-12T10:00:00+00:00",
        }
        self.write()

    def write(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text("{}\n", encoding="utf-8")
        write_json(self.license_path, self.license)
        write_json(self.job_path, self.job)
        self.authorization["original_license_sha256"] = worker._file_sha256(
            self.license_path
        )
        self.authorization["original_job_sha256"] = worker._file_sha256(
            self.job_path
        )
        write_json(self.authorization_path, self.authorization)
        write_json(self.session_path, self.session)

    def run(self, generator, *, clients: int = 4, materialize=None):
        client_list = [(index, index) for index in range(1, clients + 1)]
        safe_prompt = lambda record, prompt: (
            f"SAFE:{record['generation_target_id']}",
            "content_policy_safe_v2_truck",
        )
        materialize_patch = (
            patch.object(worker, "_materialize_ready_deliveries", side_effect=materialize)
            if materialize is not None
            else patch.object(worker, "_materialize_ready_deliveries", return_value=0)
        )
        with (
            patch.object(
                worker.category_image_resume,
                "build_resume_plan",
                return_value=deepcopy(self.plan),
            ),
            patch.object(
                worker.production,
                "load_frozen_manifest_runtime_records",
                return_value=deepcopy(self.records),
            ),
            patch.object(worker.production, "save_raw_png", return_value={"saved_raw_sha256": "f" * 64}),
            patch.object(worker.production, "content_policy_retry_for_record", side_effect=safe_prompt),
            materialize_patch,
        ):
            return worker.resume_category_images(
                self.batch,
                self.job_path,
                self.license_path,
                self.authorization_path,
                self.plan["resume_plan_sha256"],
                session_path=self.session_path,
                clients=client_list,
                generate_one=generator,
                config=CONFIG,
            )

    def events(self) -> list[dict]:
        if not self.events_path.is_file():
            return []
        return [
            json.loads(line)
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class CategoryImageResumeWorkerTests(unittest.TestCase):
    def test_authorized_success_skips_success_exhausted_and_unknown_is_original_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), success=1, exhausted=1, unknown=1, unattempted=1
            )
            calls: list[str] = []

            def generate(client, config, prompt):
                del client, config
                events = fixture.events()
                self.assertEqual(events[-1]["status"], "request_reserved")
                license_data = json.loads(fixture.license_path.read_text(encoding="utf-8"))
                self.assertEqual(license_data["requests_used"], events[-1]["request_number"])
                calls.append(prompt)
                return b"image"

            result = fixture.run(generate, clients=2)
            terminal_exists = Path(result["terminal_evidence"]).is_file()
            session = json.loads(fixture.session_path.read_text(encoding="utf-8"))
            authorization = json.loads(
                fixture.authorization_path.read_text(encoding="utf-8")
            )
        self.assertEqual(result["status"], "completed_with_errors")
        self.assertEqual(session["status"], "completed_with_errors")
        self.assertIsNone(session["pid"])
        self.assertEqual(authorization["status"], "consumed")
        self.assertEqual(
            calls,
            [
                f"ORIGINAL:{fixture.unattempted_ids[0]}",
                f"ORIGINAL:{fixture.unknown_ids[0]}",
            ],
        )
        self.assertNotIn(fixture.success_ids[0], "".join(calls))
        self.assertNotIn(fixture.exhausted_ids[0], "".join(calls))
        self.assertTrue(terminal_exists)

    def test_factory_starting_pid_race_is_accepted_for_current_worker_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(Path(temporary), unattempted=1)
            fixture.session.update({"status": "starting", "pid": worker.os.getpid()})
            fixture.write()
            result = fixture.run(
                lambda client, config, prompt: b"image",
                clients=1,
            )
        self.assertEqual(result["status"], "awaiting_review")

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(Path(temporary), unattempted=1)
            fixture.session.update({"status": "starting", "pid": worker.os.getpid() + 100000})
            fixture.write()
            with self.assertRaisesRegex(
                worker.ResumeExecutionError, "续跑会话初态"
            ):
                fixture.run(lambda client, config, prompt: b"image", clients=1)

    def test_starting_pid_accepts_only_current_or_windows_direct_parent(self) -> None:
        self.assertTrue(
            worker._initial_session_state_allowed(
                "starting",
                101,
                current_pid=101,
                parent_pid=202,
                allow_parent_pid=True,
            )
        )
        self.assertTrue(
            worker._initial_session_state_allowed(
                "starting",
                202,
                current_pid=101,
                parent_pid=202,
                allow_parent_pid=True,
            )
        )
        self.assertFalse(
            worker._initial_session_state_allowed(
                "starting",
                202,
                current_pid=101,
                parent_pid=202,
                allow_parent_pid=False,
            )
        )
        for invalid_pid in (None, True, 0, -1, 303, "202"):
            with self.subTest(pid=invalid_pid):
                self.assertFalse(
                    worker._initial_session_state_allowed(
                        "starting",
                        invalid_pid,
                        current_pid=101,
                        parent_pid=202,
                        allow_parent_pid=True,
                    )
                )

    @unittest.skipUnless(os.name == "nt", "Windows venv redirector integration")
    def test_real_windows_venv_redirector_launcher_pid_handshake(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session_path = Path(temporary) / "session.json"
            script = """
import json, os, sys, time
from pathlib import Path
from tools import category_image_resume_worker as worker
path = Path(sys.argv[1])
deadline = time.monotonic() + 5
while not path.is_file() and time.monotonic() < deadline:
    time.sleep(0.01)
plan = {"job_id": "job", "license_id": "license", "resume_plan_sha256": "5" * 64}
accepted = False
error = None
try:
    worker._validate_session(path, "authorization", plan)
    accepted = True
except Exception as exc:
    error = str(exc)
print(json.dumps({"accepted": accepted, "error": error, "pid": os.getpid(), "ppid": os.getppid()}), flush=True)
"""
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(session_path)],
                cwd=worker.production.ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            write_json(
                session_path,
                {
                    "schema_version": 1,
                    "kind": "category-image-resume-session",
                    "authorization_id": "authorization",
                    "job_id": "job",
                    "license_id": "license",
                    "resume_plan_sha256": "5" * 64,
                    "status": "starting",
                    "pid": process.pid,
                    "created_at": "2026-08-13T00:00:00+00:00",
                },
            )
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            result = json.loads(stdout)

        if result["pid"] == process.pid:
            self.skipTest("current interpreter does not use a child-process redirector")
        self.assertEqual(result["ppid"], process.pid)
        self.assertTrue(result["accepted"], result["error"])

    def test_zero_request_dead_starting_session_can_be_safely_reset_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(Path(temporary), unattempted=1)
            fixture.session.update({"status": "starting", "pid": 999999999})
            fixture.write()
            self.assertEqual(fixture.events(), [])
            before = json.loads(fixture.license_path.read_text(encoding="utf-8"))
            self.assertEqual(before["requests_used"], 0)
            reset = json.loads(fixture.session_path.read_text(encoding="utf-8"))
            reset.update({"status": "queued", "pid": None})
            write_json(fixture.session_path, reset)

            result = fixture.run(lambda client, config, prompt: b"image", clients=1)
            reserved = [
                event for event in fixture.events() if event["status"] == "request_reserved"
            ]
            authorization = json.loads(
                fixture.authorization_path.read_text(encoding="utf-8")
            )

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(len(reserved), 1)
        self.assertEqual(reserved[0]["request_number"], 1)
        self.assertEqual(reserved[0]["attempt"], 1)
        self.assertEqual(authorization["status"], "consumed")

    def test_legacy_four_way_authorization_without_new_bindings_can_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=1, max_workers=4
            )
            fixture.authorization.pop("resume_policy")
            for key in worker._BALANCE_AUTHORIZATION_FIELDS:
                fixture.authorization.pop(key)
            write_json(fixture.authorization_path, fixture.authorization)

            result = fixture.run(
                lambda client, config, prompt: b"image",
                clients=1,
            )
            authorization = json.loads(
                fixture.authorization_path.read_text(encoding="utf-8")
            )
            started = next(
                event
                for event in fixture.events()
                if event["status"] == "resume_started"
            )

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(authorization["status"], "consumed")
        self.assertNotIn("resume_policy", authorization)
        self.assertEqual(started["resume_policy"], worker.PARALLEL_RESUME_POLICY)

    def test_missing_modern_bindings_are_allowed_only_for_exact_legacy_four_way(self) -> None:
        cases = (
            ("serial_missing_policy", 1, ("resume_policy",)),
            (
                "serial_missing_balance",
                1,
                ("approved_balance_failure_request_count",),
            ),
            ("fixed_ten_missing_policy", 10, ("resume_policy",)),
            (
                "fixed_ten_missing_balance",
                10,
                ("approved_balance_failure_request_count",),
            ),
            (
                "modern_four_missing_balance",
                4,
                ("approved_balance_failure_request_count",),
            ),
            (
                "partial_legacy_four",
                4,
                (
                    "resume_policy",
                    "approved_balance_recoverable_ids_sha256",
                    "approved_balance_failure_request_count",
                    "approved_additional_recovery_request_budget",
                ),
            ),
        )
        for name, max_workers, missing in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                fixture = ResumeWorkerFixture(
                    Path(temporary),
                    unattempted=11 if max_workers == 10 else 1,
                    max_workers=max_workers,
                )
                for key in missing:
                    fixture.authorization.pop(key)
                write_json(fixture.authorization_path, fixture.authorization)
                calls: list[str] = []

                with self.assertRaises(worker.ResumeExecutionError):
                    fixture.run(
                        lambda client, config, prompt: calls.append(prompt),
                        clients=10 if max_workers == 10 else 1,
                    )
                authorization = json.loads(
                    fixture.authorization_path.read_text(encoding="utf-8")
                )

            self.assertEqual(calls, [])
            self.assertEqual(authorization["status"], "active")

    def test_content_policy_uses_safe_v2_but_transient_retry_stays_original(self) -> None:
        for error_text, expected_second in (
            ("content policy violation", "SAFE"),
            ("request timeout", "ORIGINAL"),
        ):
            with self.subTest(error=error_text), tempfile.TemporaryDirectory() as temporary:
                fixture = ResumeWorkerFixture(Path(temporary), unattempted=1)
                calls: list[str] = []

                def generate(client, config, prompt):
                    del client, config
                    calls.append(prompt)
                    if len(calls) == 1:
                        raise RuntimeError(error_text)
                    return b"image"

                result = fixture.run(generate, clients=1)
                variants = [
                    event["retry_prompt_variant"]
                    for event in fixture.events()
                    if event["status"] == "request_reserved"
                ]
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual(len(calls), 2)
            self.assertTrue(calls[1].startswith(expected_second))
            self.assertEqual(
                variants,
                [
                    "original",
                    (
                        "content_policy_safe_v2_truck"
                        if expected_second == "SAFE"
                        else "original"
                    ),
                ],
            )

    def test_insufficient_balance_pauses_immediately_without_reserving_next_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=3, max_workers=1
            )
            calls: list[str] = []

            def reject_for_balance(client, config, prompt):
                del client, config
                calls.append(prompt)
                raise RuntimeError(
                    "Error code: 403 - {'error': {'message': "
                    "'insufficient balance', 'type': 'billing_error'}}"
                )

            result = fixture.run(reject_for_balance, clients=1)
            events = fixture.events()
            reserved = [
                event for event in events if event["status"] == "request_reserved"
            ]
            failures = [
                event for event in events if event["status"] == "request_failed"
            ]
            session = json.loads(fixture.session_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "paused_balance_exhausted")
        self.assertEqual(session["status"], "paused_balance_exhausted")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(reserved), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["error_kind"], "balance_exhausted")
        self.assertFalse(failures[0]["will_retry"])
        self.assertEqual(events[-1]["status"], "paused_balance_exhausted")
        self.assertIsNone(result["terminal_evidence"])

    def test_authorization_binding_and_budget_overflow_fail_before_consumption(self) -> None:
        mutations = {
            "job_id": lambda fixture: fixture.authorization.__setitem__("job_id", "other-job"),
            "original_budget": lambda fixture: fixture.authorization.__setitem__(
                "original_approved_request_budget", fixture.plan["budget"] + 1
            ),
            "exhausted_count": lambda fixture: fixture.authorization.__setitem__(
                "approved_exhausted_count", 99
            ),
            "exhausted_hash": lambda fixture: fixture.authorization.__setitem__(
                "approved_exhausted_ids_sha256", "0" * 64
            ),
            "attempts_used_hash": lambda fixture: fixture.authorization.__setitem__(
                "attempts_used_sha256", "0" * 64
            ),
            "attempts_remaining_hash": lambda fixture: fixture.authorization.__setitem__(
                "attempts_remaining_sha256", "0" * 64
            ),
            "per_target_hash": lambda fixture: fixture.authorization.__setitem__(
                "per_target_attempts_sha256", "0" * 64
            ),
            "max_attempts": lambda fixture: fixture.authorization.__setitem__("max_attempts", 3),
            "max_workers": lambda fixture: fixture.authorization.__setitem__("max_workers", 2),
            "resume_policy": lambda fixture: fixture.authorization.__setitem__(
                "resume_policy", "other"
            ),
            "retry_policy": lambda fixture: fixture.authorization.__setitem__(
                "retry_policy", "other"
            ),
            "provider": lambda fixture: fixture.authorization.__setitem__("provider", "other"),
            "base_url": lambda fixture: fixture.authorization.__setitem__(
                "base_url", "https://other.invalid/v1"
            ),
            "model": lambda fixture: fixture.authorization.__setitem__("model", "other"),
            "quality": lambda fixture: fixture.authorization.__setitem__("quality", "other"),
            "size": lambda fixture: fixture.authorization.__setitem__("size", "1024x1024"),
            "resume_confirmed": lambda fixture: fixture.authorization.__setitem__(
                "resume_confirmed", False
            ),
            "paid_confirmed": lambda fixture: fixture.authorization.__setitem__(
                "paid_confirmed", False
            ),
            "third_party_confirmed": lambda fixture: fixture.authorization.__setitem__(
                "third_party_confirmed", False
            ),
            "license_hash": lambda fixture: fixture.authorization.__setitem__(
                "original_license_sha256", "0" * 64
            ),
            "job_hash": lambda fixture: fixture.authorization.__setitem__(
                "original_job_sha256", "0" * 64
            ),
            "budget_overflow": lambda fixture: fixture.plan.__setitem__(
                "budget", fixture.plan["cumulative_max_requests"] - 1
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(binding=name), tempfile.TemporaryDirectory() as temporary:
                fixture = ResumeWorkerFixture(Path(temporary), unattempted=1)
                mutate(fixture)
                write_json(fixture.authorization_path, fixture.authorization)
                calls: list[str] = []
                with self.assertRaises(worker.ResumeExecutionError):
                    fixture.run(lambda client, config, prompt: calls.append(prompt), clients=1)
                authorization = json.loads(
                    fixture.authorization_path.read_text(encoding="utf-8")
                )
                session = json.loads(fixture.session_path.read_text(encoding="utf-8"))
            self.assertEqual(calls, [])
            self.assertEqual(authorization["status"], "active")
            self.assertEqual(session["status"], "queued")

    def test_probe_failure_pauses_without_terminal_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(Path(temporary), unattempted=1)

            def reject(client, config, prompt):
                del client, config, prompt
                raise RuntimeError("content policy violation")

            result = fixture.run(reject, clients=1)
            session = json.loads(fixture.session_path.read_text(encoding="utf-8"))
            summaries = fixture.batch / "production" / "resume_summaries"
        self.assertEqual(result["status"], "paused_resume_probe_failed")
        self.assertEqual(session["status"], "paused_resume_probe_failed")
        self.assertIsNone(result["terminal_evidence"])
        self.assertFalse(summaries.exists())

    def test_stage_two_and_stage_four_policy_storms_pause(self) -> None:
        for count, successful_prefix in ((3, 1), (7, 3)):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                fixture = ResumeWorkerFixture(Path(temporary), unattempted=count)
                safe_success = set(fixture.unattempted_ids[:successful_prefix])

                def generate(client, config, prompt):
                    del client, config
                    target_id = prompt.split(":", 1)[1]
                    if target_id in safe_success:
                        return b"image"
                    raise RuntimeError("content policy violation")

                result = fixture.run(generate, clients=4 if count == 7 else 2)
                stages = [
                    event
                    for event in fixture.events()
                    if event["status"] == "resume_concurrency_stage"
                ]
                session = json.loads(fixture.session_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "paused_policy_circuit")
            self.assertEqual(session["status"], "paused_policy_circuit")
            self.assertTrue(stages[-1]["circuit_breaker_triggered"])
            self.assertEqual(stages[-1]["worker_count"], 2 if count == 3 else 4)
            self.assertIsNone(result["terminal_evidence"])

    def test_fixed_ten_runs_one_probe_then_only_ten_wide_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=23, max_workers=10
            )
            result = fixture.run(
                lambda client, config, prompt: b"image",
                clients=10,
            )
            stages = [
                event
                for event in fixture.events()
                if event["status"] == "resume_concurrency_stage"
            ]
            terminal = json.loads(
                Path(result["terminal_evidence"]).read_text(encoding="utf-8")
            )

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(
            [stage["worker_count"] for stage in stages], [1, 10, 10, 2]
        )
        self.assertEqual(
            [stage["phase"] for stage in stages],
            [
                "resume_probe",
                "resume_fixed_10",
                "resume_fixed_10",
                "resume_fixed_10",
            ],
        )
        self.assertTrue(all(stage["in_flight_drained"] for stage in stages))
        self.assertEqual(terminal["resume_policy"], worker.FIXED_TEN_RESUME_POLICY)

    def test_fixed_ten_balance_failure_switches_key_and_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=22, max_workers=10
            )
            probe_id = fixture.unattempted_ids[0]
            current_stage = set(fixture.unattempted_ids[1:11])
            balance_target = fixture.unattempted_ids[1]
            barrier = threading.Barrier(10)
            called_targets: list[str] = []
            calls_lock = threading.Lock()
            balance_failed = False

            def generate(client, config, prompt):
                nonlocal balance_failed
                del config
                target_id = prompt.split(":", 1)[1]
                with calls_lock:
                    called_targets.append(target_id)
                if target_id == probe_id:
                    return b"image"
                if target_id in current_stage and not (
                    target_id == balance_target and balance_failed
                ):
                    barrier.wait(timeout=5)
                    if target_id == balance_target and client == 1 and not balance_failed:
                        balance_failed = True
                        raise RuntimeError(
                            "Error code: 403 - {'code': 'INSUFFICIENT_BALANCE'}"
                        )
                    return b"image"
                return b"image"

            result = fixture.run(generate, clients=10)
            events = fixture.events()
            stages = [
                event
                for event in events
                if event["status"] == "resume_concurrency_stage"
            ]
            reserved_ids = [
                event["generation_target_id"]
                for event in events
                if event["status"] == "request_reserved"
            ]

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(set(called_targets), set(fixture.unattempted_ids))
        self.assertEqual(set(reserved_ids), set(fixture.unattempted_ids))
        self.assertEqual(called_targets.count(balance_target), 2)
        self.assertEqual(reserved_ids.count(balance_target), 2)
        self.assertEqual(len(stages), 4)
        self.assertEqual(stages[-1]["worker_count"], 3)
        self.assertEqual(stages[1]["balance_failure_count"], 1)
        self.assertEqual(stages[1]["balance_failover_target_count"], 1)
        self.assertEqual(stages[1]["quarantined_api_key_slots"], [1])
        self.assertEqual(stages[1]["remaining_api_key_slot_count"], 9)
        self.assertTrue(all(stage["in_flight_drained"] for stage in stages))
        self.assertEqual(events[-1]["status"], "resume_completed")

    def test_fixed_ten_any_double_policy_failure_stops_after_drained_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=22, max_workers=10
            )
            probe_id = fixture.unattempted_ids[0]
            current_stage = set(fixture.unattempted_ids[1:11])
            rejected_target = fixture.unattempted_ids[1]
            never_dispatched = set(fixture.unattempted_ids[11:])
            called_targets: list[str] = []
            calls_lock = threading.Lock()

            def generate(client, config, prompt):
                del client, config
                target_id = prompt.split(":", 1)[1]
                with calls_lock:
                    called_targets.append(target_id)
                if target_id == probe_id:
                    return b"image"
                if target_id not in current_stage:
                    self.fail(f"target after policy breaker was requested: {target_id}")
                if target_id == rejected_target:
                    raise RuntimeError("content policy violation")
                return b"image"

            result = fixture.run(generate, clients=10)
            events = fixture.events()
            stages = [
                event
                for event in events
                if event["status"] == "resume_concurrency_stage"
            ]

        self.assertEqual(result["status"], "paused_policy_circuit")
        self.assertFalse(set(called_targets) & never_dispatched)
        self.assertEqual(called_targets.count(rejected_target), 2)
        self.assertEqual(len(stages), 2)
        self.assertEqual(stages[-1]["content_policy_double_failure_count"], 1)
        self.assertTrue(stages[-1]["fixed_ten_any_double_policy_failure"])
        self.assertTrue(stages[-1]["circuit_breaker_triggered"])
        self.assertEqual(stages[-1]["drained_result_count"], 10)
        self.assertEqual(stages[-1]["stage_requests_used"], 11)
        self.assertTrue(stages[-1]["in_flight_drained"])

    def test_fixed_ten_probe_double_policy_failure_stops_before_parallel_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=12, max_workers=10
            )
            calls: list[str] = []

            def reject(client, config, prompt):
                del client, config
                calls.append(prompt)
                raise RuntimeError("content policy violation")

            result = fixture.run(reject, clients=10)
            stages = [
                event
                for event in fixture.events()
                if event["status"] == "resume_concurrency_stage"
            ]

        self.assertEqual(result["status"], "paused_policy_circuit")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["worker_count"], 1)
        self.assertTrue(stages[0]["fixed_ten_any_double_policy_failure"])
        self.assertTrue(stages[0]["circuit_breaker_triggered"])

    def test_fixed_ten_never_exceeds_ten_in_flight_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=31, max_workers=10
            )
            probe_id = fixture.unattempted_ids[0]
            barrier = threading.Barrier(10)
            state_lock = threading.Lock()
            active = 0
            maximum_active = 0

            def generate(client, config, prompt):
                nonlocal active, maximum_active
                del client, config
                target_id = prompt.split(":", 1)[1]
                if target_id == probe_id:
                    return b"image"
                with state_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    barrier.wait(timeout=5)
                    return b"image"
                finally:
                    with state_lock:
                        active -= 1

            result = fixture.run(generate, clients=10)
            stages = [
                event
                for event in fixture.events()
                if event["status"] == "resume_concurrency_stage"
            ]

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(maximum_active, 10)
        self.assertEqual([stage["worker_count"] for stage in stages], [1, 10, 10, 10])
        self.assertTrue(all(stage["worker_count"] <= 10 for stage in stages))

    def test_fixed_ten_requires_exact_policy_slots_and_clients_before_consumption(self) -> None:
        mutations = {
            "policy": lambda fixture: fixture.authorization.__setitem__(
                "resume_policy", worker.PARALLEL_RESUME_POLICY
            ),
            "missing_slots": lambda fixture: fixture.authorization.pop("api_key_slots"),
            "reordered_slots": lambda fixture: fixture.authorization.__setitem__(
                "api_key_slots", list(reversed(fixture.authorization["api_key_slots"]))
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                fixture = ResumeWorkerFixture(
                    Path(temporary), unattempted=11, max_workers=10
                )
                mutate(fixture)
                write_json(fixture.authorization_path, fixture.authorization)
                calls: list[str] = []
                with self.assertRaises(worker.ResumeExecutionError):
                    fixture.run(
                        lambda client, config, prompt: calls.append(prompt),
                        clients=10,
                    )
                authorization = json.loads(
                    fixture.authorization_path.read_text(encoding="utf-8")
                )
            self.assertEqual(calls, [])
            self.assertEqual(authorization["status"], "active")

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=11, max_workers=10
            )
            calls: list[str] = []
            with self.assertRaisesRegex(worker.ResumeExecutionError, "客户端"):
                fixture.run(
                    lambda client, config, prompt: calls.append(prompt),
                    clients=9,
                )
            authorization = json.loads(
                fixture.authorization_path.read_text(encoding="utf-8")
            )
        self.assertEqual(calls, [])
        self.assertEqual(authorization["status"], "active")

    def test_materialization_runs_only_on_main_thread_after_each_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(Path(temporary), unattempted=7)
            main_thread = threading.get_ident()
            calls: list[tuple[int, int]] = []

            def materialize(deliveries, successful_ids, phone, service_items):
                del deliveries, phone, service_items
                calls.append((threading.get_ident(), len(successful_ids)))
                return len(successful_ids)

            result = fixture.run(
                lambda client, config, prompt: b"image",
                clients=4,
                materialize=materialize,
            )

        self.assertEqual(result["status"], "awaiting_review")
        self.assertTrue(all(thread_id == main_thread for thread_id, _ in calls))
        # Initial local reuse scan, probe, ramp-2, fixed-4, and final closure.
        self.assertEqual([count for _, count in calls], [0, 1, 3, 7, 7])

    def test_serial_authorization_never_constructs_a_thread_pool(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=3, max_workers=1
            )
            materialized: list[int] = []

            def materialize(deliveries, successful_ids, phone, service_items):
                del deliveries, phone, service_items
                materialized.append(len(successful_ids))
                return len(successful_ids)

            with patch.object(
                worker,
                "ThreadPoolExecutor",
                side_effect=AssertionError("serial resume must not create a thread pool"),
            ):
                result = fixture.run(
                    lambda client, config, prompt: b"image",
                    clients=1,
                    materialize=materialize,
                )
            stages = [
                event
                for event in fixture.events()
                if event["status"] == "resume_concurrency_stage"
            ]

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual([stage["worker_count"] for stage in stages], [1, 1, 1])
        self.assertEqual(
            [stage["phase"] for stage in stages],
            ["resume_probe", "resume_serial", "resume_serial"],
        )
        self.assertEqual(materialized, [0, 1, 2, 3, 3])

    def test_serial_double_policy_rejection_pauses_before_next_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=3, max_workers=1
            )
            first, rejected, never_requested = fixture.unattempted_ids
            calls: list[str] = []

            def generate(client, config, prompt):
                del client, config
                calls.append(prompt)
                if first in prompt:
                    return b"image"
                if rejected in prompt:
                    raise RuntimeError("content policy violation")
                self.fail(f"target after serial policy breaker was requested: {prompt}")

            result = fixture.run(generate, clients=1)
            events = fixture.events()
            stages = [
                event
                for event in events
                if event["status"] == "resume_concurrency_stage"
            ]
            reserved = [
                event for event in events if event["status"] == "request_reserved"
            ]

        self.assertEqual(result["status"], "paused_policy_circuit")
        self.assertNotIn(never_requested, "".join(calls))
        self.assertEqual(
            [(event["generation_target_id"], event["retry_prompt_variant"]) for event in reserved],
            [
                (first, "original"),
                (rejected, "original"),
                (rejected, "content_policy_safe_v2_truck"),
            ],
        )
        self.assertTrue(stages[-1]["circuit_breaker_triggered"])
        self.assertTrue(stages[-1]["serial_target_double_policy_failure"])
        self.assertIsNone(result["terminal_evidence"])

    def test_serial_probe_double_policy_is_a_policy_circuit_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(
                Path(temporary), unattempted=2, max_workers=1
            )
            result = fixture.run(
                lambda client, config, prompt: (_ for _ in ()).throw(
                    RuntimeError("content policy violation")
                ),
                clients=1,
            )
            stages = [
                event
                for event in fixture.events()
                if event["status"] == "resume_concurrency_stage"
            ]

        self.assertEqual(result["status"], "paused_policy_circuit")
        self.assertTrue(stages[0]["circuit_breaker_triggered"])
        self.assertTrue(stages[0]["serial_target_double_policy_failure"])
        self.assertIsNone(result["terminal_evidence"])

    def test_terminal_evidence_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            worker._write_terminal_evidence(path, {"status": "done"})
            with self.assertRaises(worker.ResumeExecutionError):
                worker._write_terminal_evidence(path, {"status": "changed"})
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload, {"status": "done"})

    def test_unexpected_exception_marks_session_failed_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(Path(temporary), unattempted=1)
            with (
                patch.object(
                    worker.category_image_resume,
                    "build_resume_plan",
                    return_value=deepcopy(fixture.plan),
                ),
                patch.object(
                    worker.production,
                    "load_frozen_manifest_runtime_records",
                    return_value=deepcopy(fixture.records),
                ),
                patch.object(worker.production, "save_raw_png", return_value={}),
                patch.object(worker, "_materialize_ready_deliveries", return_value=0),
                patch.object(worker.production, "_request_stage_result", side_effect=RuntimeError("boom")),
            ):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    worker.resume_category_images(
                        fixture.batch,
                        fixture.job_path,
                        fixture.license_path,
                        fixture.authorization_path,
                        fixture.plan["resume_plan_sha256"],
                        session_path=fixture.session_path,
                        clients=[(1, object())],
                        generate_one=lambda client, config, prompt: b"image",
                        config=CONFIG,
                    )
            session = json.loads(fixture.session_path.read_text(encoding="utf-8"))
            lock = fixture.batch / "production" / "generation.lock"
        self.assertEqual(session["status"], "failed")
        self.assertIsNone(session["pid"])
        self.assertFalse(lock.exists())

    def test_cli_preflight_exception_marks_only_bound_current_session_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeWorkerFixture(Path(temporary), unattempted=1)
            fixture.session.update({"status": "starting", "pid": worker.os.getpid()})
            fixture.write()
            argv = [
                "category_image_resume_worker",
                "run",
                "--batch-dir",
                str(fixture.batch),
                "--job-file",
                str(fixture.job_path),
                "--license",
                str(fixture.license_path),
                "--resume-authorization",
                str(fixture.authorization_path),
                "--session-file",
                str(fixture.session_path),
                "--resume-plan-sha256",
                fixture.plan["resume_plan_sha256"],
            ]
            with (
                patch("sys.argv", argv),
                patch.object(
                    worker,
                    "resume_category_images",
                    side_effect=worker.ResumeExecutionError("preflight failed"),
                ),
                self.assertRaises(SystemExit) as stopped,
            ):
                worker.main()
            self.assertEqual(stopped.exception.code, 1)
            session = json.loads(fixture.session_path.read_text(encoding="utf-8"))

        self.assertEqual(session["status"], "failed")
        self.assertIsNone(session["pid"])
        self.assertEqual(
            session["last_error"],
            worker.production.safe_request_error_summary(worker.ResumeExecutionError("preflight failed")),
        )
        self.assertNotIn("preflight failed", session["last_error"])


if __name__ == "__main__":
    unittest.main()
