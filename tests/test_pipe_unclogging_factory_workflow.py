from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import factory


ROOT = Path(__file__).resolve().parents[1]
PIPE_BATCH = (
    ROOT
    / "prompts"
    / "category_batches"
    / "pipe_unclogging"
    / "batch_v2_5_active"
)
LEGACY_PIPE_BATCH = (
    ROOT
    / "prompts"
    / "category_batches"
    / "pipe_unclogging"
    / "batch_20260710_054132_003104"
)
PHONE = "13317112954"


def license_snapshot() -> dict[str, str]:
    """Capture every existing pipe/group license without changing local state."""
    result: dict[str, str] = {}
    roots = [
        PIPE_BATCH / "production",
        LEGACY_PIPE_BATCH / "production",
        factory.GROUP_LICENSE_DIR,
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.json"):
            relative = path.relative_to(root).as_posix().lower()
            if "license" not in relative and "authorization" not in relative:
                continue
            result[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def pipe_config() -> dict:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    config.update({"provider": "official", "base_url": ""})
    return config


def resume_config() -> dict:
    config = pipe_config()
    config.update(
        {
            "provider": "relay",
            "base_url": "https://relay.example.test/v1",
            "model": "gpt-image-2",
            "quality": "medium",
            "api_size": "1024x1536",
        }
    )
    return config


def v2_plan(
    scope: str,
    *,
    pending_api_requests: int,
    delivery_count: int,
    pending_delivery_count: int,
    plan_sha256: str,
) -> dict:
    generation_count = 3 if scope == "covers" else 18
    generation_ids = [f"generation-{index}" for index in range(1, generation_count + 1)]
    delivery_ids = [f"delivery-{index}" for index in range(1, delivery_count + 1)]
    sizes = ("1024x1408", "1024x1472", "1024x1536")
    recipes = [
        {
            "group_index": index,
            "height_profile_id": f"height_{sizes[index - 1].split('x')[1]}",
            "final_sizes": [sizes[index - 1]],
            "triptych_layout_id": None if scope == "covers" else "stacked_equal",
            "triptych_recipe": None if scope == "covers" else {"layout_id": "stacked_equal"},
        }
        for index in range(1, 4)
    ]
    return {
        "job_id": "job-safe",
        "license_id": "license-safe",
        "category_id": "pipe_unclogging",
        "batch_id": "batch_test",
        "provider": "relay",
        "model": "gpt-image-2",
        "quality": "medium",
        "size": "1024x1536",
        "max_attempts": 2,
        "retry_policy": "classified_once_v1",
        "production_schema_version": 3,
        "structure_version": "pipe_unclogging_v2_1cover_1triptych_3details",
        "generation_mode": "independent_triptych_panels",
        "generation_unit_count": 7,
        "delivery_count": delivery_count,
        "total_generation_targets": generation_count,
        "total_delivery_targets": delivery_count,
        "generation_target_ids": generation_ids,
        "generation_targets_sha256": "generation-targets",
        "delivery_target_ids": delivery_ids,
        "delivery_targets_sha256": "delivery-targets",
        "pending_generation_target_ids": generation_ids[:pending_api_requests],
        "pending_generation_targets_sha256": "pending-generation-targets",
        "pending_delivery_target_ids": delivery_ids[:pending_delivery_count],
        "pending_delivery_targets_sha256": "pending-delivery-targets",
        "pending_api_requests": pending_api_requests,
        "pending_delivery_count": pending_delivery_count,
        "group_recipes": recipes,
        "existing_images": 0,
        "recoverable_images": 0,
        "plan_sha256": plan_sha256,
        "manifest_sha256": "manifest-123",
        "output_root": str(factory.PIPE_OUTPUT_ROOT.resolve()),
    }


def resume_plan() -> dict:
    success = ["success-1", "success-2"]
    exhausted = ["exhausted-1"]
    unknown = ["unknown-1", "unknown-2"]
    unattempted = ["new-1", "new-2", "new-3"]
    attempts_used = {
        "success-1": 1,
        "success-2": 1,
        "exhausted-1": 2,
        "unknown-1": 1,
        "unknown-2": 1,
        "new-1": 0,
        "new-2": 0,
        "new-3": 0,
    }
    attempts_remaining = {
        "success-1": 0,
        "success-2": 0,
        "exhausted-1": 0,
        "unknown-1": 1,
        "unknown-2": 1,
        "new-1": 2,
        "new-2": 2,
        "new-3": 2,
    }
    return {
        "success_ids": success,
        "exhausted_ids": exhausted,
        "unknown_ids": unknown,
        "unattempted_ids": unattempted,
        "resumable_ids": unknown + unattempted,
        "attempts_used": attempts_used,
        "attempts_remaining": attempts_remaining,
        "requests_used": 6,
        "remaining_max_requests": 8,
        "cumulative_max_requests": 14,
        "budget": 20,
        "counts": {
            "total": 8,
            "success": 2,
            "exhausted": 1,
            "unknown": 2,
            "unattempted": 3,
            "resumable": 5,
        },
        "resume_plan_sha256": "a" * 64,
        "frozen_manifest_sha256": "b" * 64,
        "frozen_overlay_sha256": "d" * 64,
        "events_sha256": "c" * 64,
        "event_tail_sha256": "e" * 64,
    }


def resume_plan_for_events(events_path: Path) -> dict:
    plan = resume_plan()
    event_bytes = events_path.read_bytes()
    event_lines = [line for line in event_bytes.splitlines() if line.strip()]
    plan["events_sha256"] = hashlib.sha256(event_bytes).hexdigest()
    plan["event_tail_sha256"] = hashlib.sha256(event_lines[-1]).hexdigest()
    return plan


def stale_resume_plan_for_events(events_path: Path, plan_hash: str = "9" * 64) -> dict:
    plan = resume_plan_for_events(events_path)
    plan.update(
        {
            "success_ids": ["success-1", "success-2", "new-1"],
            "exhausted_ids": ["exhausted-1"],
            "unknown_ids": ["unknown-1", "unknown-2", "new-2", "new-3"],
            "unattempted_ids": [],
            "resumable_ids": ["unknown-1", "unknown-2", "new-2", "new-3"],
            "attempts_used": {
                "success-1": 1,
                "success-2": 1,
                "exhausted-1": 2,
                "unknown-1": 1,
                "unknown-2": 1,
                "new-1": 1,
                "new-2": 1,
                "new-3": 1,
            },
            "attempts_remaining": {
                "success-1": 0,
                "success-2": 0,
                "exhausted-1": 0,
                "unknown-1": 1,
                "unknown-2": 1,
                "new-1": 0,
                "new-2": 1,
                "new-3": 1,
            },
            "requests_used": 9,
            "remaining_max_requests": 4,
            "cumulative_max_requests": 13,
            "counts": {
                "total": 8,
                "success": 3,
                "exhausted": 1,
                "unknown": 4,
                "unattempted": 0,
                "resumable": 4,
            },
            "resume_plan_sha256": plan_hash,
            "max_attempts": 2,
            "retry_policy": "classified_once_v1",
            "provider": "relay",
            "model": "gpt-image-2",
            "quality": "medium",
            "size": "1024x1536",
        }
    )
    return plan


class PipeUncloggingFactoryWorkflowTests(unittest.TestCase):
    @staticmethod
    def _resume_fixture(temporary: str, *, pid: int = 4321) -> tuple[Path, Path, Path]:
        batch = (Path(temporary) / "batch_test").resolve()
        jobs_dir = batch / "production" / "jobs"
        licenses_dir = batch / "production" / "licenses"
        jobs_dir.mkdir(parents=True)
        licenses_dir.mkdir(parents=True)
        job_path = jobs_dir / "job-safe.json"
        license_path = licenses_dir / "license-safe.json"
        job_path.write_text(
            json.dumps(
                {
                    "job_id": "job-safe",
                    "license_id": "license-safe",
                    "category_id": "pipe_unclogging",
                    "project_id": "pipe_unclogging",
                    "batch_id": batch.name,
                    "batch_dir": str(batch),
                    "pid": pid,
                    "requests_used": 6,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        license_path.write_text(
            json.dumps(
                {
                    "license_id": "license-safe",
                    "status": "consumed",
                    "one_time": True,
                    "plan_sha256": "f" * 64,
                    "approved_request_budget": 20,
                    "max_attempts": 2,
                    "retry_policy": "classified_once_v1",
                    "provider": "relay",
                    "base_url": "https://relay.example.test/v1",
                    "third_party_confirmed": True,
                    "model": "gpt-image-2",
                    "quality": "medium",
                    "size": "1024x1536",
                    "requests_used": 6,
                }
            ),
            encoding="utf-8",
        )
        return batch, job_path, license_path

    @staticmethod
    def _add_resume_event_fixture(batch: Path, job_id: str = "job-safe") -> Path:
        events_path = batch / "production" / f"events_{job_id}.jsonl"
        events_path.write_text(
            json.dumps({"status": "generated", "request_number": 6}) + "\n",
            encoding="utf-8",
        )
        return events_path

    @classmethod
    def _consumed_stale_resume_fixture(
        cls, temporary: str, *, authorization_id: str = "resume-old", pid: int = 2468
    ) -> tuple[dict, dict, Path, Path, Path]:
        batch, job_path, license_path = cls._resume_fixture(temporary, pid=0)
        production = batch / "production"
        job = json.loads(job_path.read_text(encoding="utf-8"))
        license_data = json.loads(license_path.read_text(encoding="utf-8"))
        job.update({"requests_used": 9, "worker_pid": pid})
        license_data["requests_used"] = 9
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        license_path.write_text(
            json.dumps(license_data, ensure_ascii=False), encoding="utf-8"
        )

        authorization_dir = production / "resume_authorizations"
        session_dir = production / "resume_sessions"
        log_dir = production / "logs"
        authorization_dir.mkdir(parents=True)
        session_dir.mkdir(parents=True)
        log_dir.mkdir(parents=True)
        authorization_path = authorization_dir / f"{authorization_id}.json"
        session_path = session_dir / f"{authorization_id}.json"
        log_path = log_dir / f"{authorization_id}.log"
        authorization = {
            "schema_version": 1,
            "kind": "category-image-resume-authorization",
            "authorization_id": authorization_id,
            "status": "consumed",
            "one_time": True,
            "job_id": "job-safe",
            "license_id": "license-safe",
            "category_id": "pipe_unclogging",
            "batch_id": batch.name,
            "resume_plan_sha256": "a" * 64,
            "requests_used": 6,
            "approved_cumulative_request_budget": 14,
        }
        session = {
            "schema_version": 1,
            "kind": "category-image-resume-session",
            "authorization_id": authorization_id,
            "job_id": "job-safe",
            "license_id": "license-safe",
            "category_id": "pipe_unclogging",
            "batch_id": batch.name,
            "resume_plan_sha256": "a" * 64,
            "status": "running",
            "pid": pid,
            "authorization_file": str(authorization_path.resolve()),
            "log_file": str(log_path.resolve()),
        }
        authorization_path.write_text(
            json.dumps(authorization, ensure_ascii=False), encoding="utf-8"
        )
        session_path.write_text(
            json.dumps(session, ensure_ascii=False), encoding="utf-8"
        )
        log_path.write_bytes(b"worker-started\nexternal-stop\n")
        events_path = production / "events_job-safe.jsonl"
        events = [
            {"status": "generated", "request_number": 6},
            {
                "status": "request_reserved",
                "authorization_id": authorization_id,
                "request_number": 7,
                "generation_target_id": "new-1",
                "attempt": 1,
                "api_key_slot": 1,
            },
            {
                "status": "generated",
                "authorization_id": authorization_id,
                "request_number": 7,
                "generation_target_id": "new-1",
                "attempt": 1,
            },
            {
                "status": "request_reserved",
                "authorization_id": authorization_id,
                "request_number": 8,
                "generation_target_id": "new-2",
                "attempt": 1,
                "api_key_slot": 2,
            },
            {
                "status": "request_reserved",
                "authorization_id": authorization_id,
                "request_number": 9,
                "generation_target_id": "new-3",
                "attempt": 1,
                "api_key_slot": 3,
            },
        ]
        events_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in events),
            encoding="utf-8",
        )
        lock_path = production / "generation.lock"
        lock_path.write_text(
            json.dumps({"job_id": "job-safe", "pid": pid}, ensure_ascii=False),
            encoding="utf-8",
        )
        plan = factory._validated_category_resume_plan(
            stale_resume_plan_for_events(events_path)
        )
        context = {
            "category_id": "pipe_unclogging",
            "job_id": "job-safe",
            "license_id": "license-safe",
            "batch_dir": batch,
            "production_dir": production,
            "job_path": job_path,
            "job": job,
            "license_path": license_path,
            "license": license_data,
            "resume_plan": plan,
        }
        with patch.object(
            factory.category_image_production, "pid_is_running", return_value=False
        ):
            stale = factory._stale_consumed_resume_session(context)
        assert stale is not None
        return context, stale, authorization_path, session_path, events_path

    def test_category_image_resume_plan_is_read_only_and_prints_ledger_counts(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "category-image-resume-plan",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "job-safe",
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            batch, job_path, license_path = self._resume_fixture(temporary)
            before = {
                path: path.read_bytes()
                for path in (job_path, license_path)
            }
            output = io.StringIO()
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=resume_plan(),
                ) as build_resume,
                patch.object(
                    factory,
                    "write_json_atomic",
                    side_effect=AssertionError("只读续跑计划不应写文件"),
                ),
                patch.object(
                    factory.category_image_production,
                    "write_new_license",
                    side_effect=AssertionError("只读续跑计划不应创建许可证"),
                ),
                patch.object(
                    factory.category_image_production.image_generate,
                    "generate_one",
                    side_effect=AssertionError("只读续跑计划不应调用图片 API"),
                ),
                patch.object(
                    factory.subprocess,
                    "Popen",
                    side_effect=AssertionError("只读续跑计划不应启动进程"),
                ),
                redirect_stdout(output),
            ):
                result = args.handler(args)

            rendered = output.getvalue()
            self.assertEqual(result, 0, rendered)
            self.assertIn(
                "目标分类：成功 2；已耗尽 1；中断保守计次 2；未尝试 3；可续跑 5。",
                rendered,
            )
            self.assertIn("已使用 API 请求：6 次。", rendered)
            self.assertIn("续跑最多 API 请求：8 次。", rendered)
            self.assertIn("累计最多 API 请求：14 / 20 次。", rendered)
            self.assertIn(f"resume_plan_sha256：{'a' * 64}", rendered)
            self.assertIn("未写文件、未创建许可证、未启动进程、未调用 API", rendered)
            build_resume.assert_called_once_with(batch, job_path, license_path)
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_category_image_resume_plan_rejects_unsafe_job_id_before_lookup(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "category-image-resume-plan",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "../outside",
            ]
        )
        output = io.StringIO()
        with (
            patch.object(
                factory,
                "category_active_batch_dir",
                side_effect=AssertionError("非法 job-id 不应进入批次查找"),
            ),
            patch.object(factory, "_build_category_image_resume_plan") as build_resume,
            redirect_stdout(output),
        ):
            result = args.handler(args)

        self.assertEqual(result, 2)
        self.assertIn("job-id 只能包含字母、数字、下划线和连字符", output.getvalue())
        build_resume.assert_not_called()

    def test_category_image_resume_plan_blocks_live_job_process(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "category-image-resume-plan",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "job-safe",
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            batch, _, _ = self._resume_fixture(temporary, pid=4321)
            output = io.StringIO()
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=True,
                ),
                patch.object(factory, "_build_category_image_resume_plan") as build_resume,
                redirect_stdout(output),
            ):
                result = args.handler(args)

        self.assertEqual(result, 2)
        self.assertIn("任务进程仍在运行", output.getvalue())
        build_resume.assert_not_called()

    def test_category_image_resume_plan_blocks_active_generation_lock(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "category-image-resume-plan",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "job-safe",
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            batch, _, _ = self._resume_fixture(temporary, pid=0)
            lock_path = batch / "production" / "generation.lock"
            lock_path.write_text(
                json.dumps({"job_id": "other-job", "pid": 9876}),
                encoding="utf-8",
            )
            output = io.StringIO()
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=True,
                ),
                patch.object(factory, "_build_category_image_resume_plan") as build_resume,
                redirect_stdout(output),
            ):
                result = args.handler(args)

        self.assertEqual(result, 2)
        self.assertIn("该批次仍有活动生产锁：other-job", output.getvalue())
        build_resume.assert_not_called()

    def test_resume_category_images_writes_bound_sidecar_and_starts_one_worker(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "resume-category-images",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "job-safe",
                "--resume-plan-sha256",
                "a" * 64,
                "--confirm-resume",
                "--confirm-paid",
                "--confirm-third-party",
            ]
        )

        class FakeProcess:
            pid = 2468

        with tempfile.TemporaryDirectory() as temporary:
            batch, job_path, license_path = self._resume_fixture(temporary, pid=0)
            originals = {
                job_path: job_path.read_bytes(),
                license_path: license_path.read_bytes(),
            }
            output = io.StringIO()
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=resume_plan(),
                ),
                patch.object(
                    factory.category_image_production,
                    "write_new_license",
                    side_effect=AssertionError("续跑入口不应新建生产许可证"),
                ),
                patch.object(
                    factory.category_image_production.image_generate,
                    "generate_one",
                    side_effect=AssertionError("factory入口不应直接调用图片 API"),
                ),
                patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                patch.object(
                    factory, "_category_effective_config", return_value=resume_config()
                ),
                patch.object(
                    factory.subprocess, "Popen", return_value=FakeProcess()
                ) as popen,
                redirect_stdout(output),
            ):
                result = args.handler(args)

            rendered = output.getvalue()
            self.assertEqual(result, 0, rendered)
            self.assertIn("可续跑目标：5；本次最多请求：8；累计最多请求：14 / 20", rendered)
            self.assertIn("已耗尽目标：1；这些目标不会在本次续跑中再次请求", rendered)
            authorizations = list(
                (batch / "production" / "resume_authorizations").glob("*.json")
            )
            sessions = list((batch / "production" / "resume_sessions").glob("*.json"))
            self.assertEqual(len(authorizations), 1)
            self.assertEqual(len(sessions), 1)
            authorization = json.loads(authorizations[0].read_text(encoding="utf-8"))
            session = json.loads(sessions[0].read_text(encoding="utf-8"))
            self.assertEqual(authorization["status"], "active")
            self.assertTrue(authorization["one_time"])
            self.assertEqual(authorization["job_id"], "job-safe")
            self.assertEqual(authorization["license_id"], "license-safe")
            self.assertEqual(authorization["original_plan_sha256"], "f" * 64)
            self.assertEqual(authorization["resume_plan_sha256"], "a" * 64)
            self.assertEqual(authorization["approved_resumable_count"], 5)
            self.assertEqual(authorization["approved_exhausted_count"], 1)
            self.assertEqual(authorization["approved_remaining_request_budget"], 8)
            self.assertEqual(authorization["approved_cumulative_request_budget"], 14)
            self.assertEqual(authorization["original_approved_request_budget"], 20)
            self.assertEqual(authorization["max_workers"], 1)
            self.assertEqual(
                authorization["resume_policy"], "serial_probe_policy_circuit_v1"
            )
            self.assertEqual(
                authorization["approved_resumable_ids_sha256"],
                factory._json_sha256(resume_plan()["resumable_ids"]),
            )
            self.assertEqual(session["status"], "starting")
            self.assertEqual(session["pid"], 2468)
            self.assertEqual(
                session["authorization_file"], str(authorizations[0].resolve())
            )
            command = popen.call_args.args[0]
            self.assertEqual(
                command[:4],
                [
                    factory._independent_python_executable(),
                    "-m",
                    "tools.category_image_resume_worker",
                    "run",
                ],
            )
            for flag, expected in (
                ("--batch-dir", str(batch)),
                ("--job-file", str(job_path)),
                ("--license", str(license_path)),
                ("--resume-authorization", str(authorizations[0].resolve())),
                ("--session-file", str(sessions[0].resolve())),
                ("--resume-plan-sha256", "a" * 64),
            ):
                self.assertEqual(command[command.index(flag) + 1], expected)
            self.assertEqual(
                popen.call_args.kwargs["env"]["PIPE_CATEGORY_NETWORK_MODE"],
                "proxy:test",
            )
            self.assertEqual(
                originals, {path: path.read_bytes() for path in originals}
            )

    def test_resume_category_images_requires_all_three_confirmations_before_writes(self) -> None:
        parser = factory.build_parser()
        base = [
            "resume-category-images",
            "--category",
            "pipe_unclogging",
            "--job-id",
            "job-safe",
            "--resume-plan-sha256",
            "a" * 64,
        ]
        confirmations = (
            "--confirm-resume",
            "--confirm-paid",
            "--confirm-third-party",
        )
        for omitted in confirmations:
            args = parser.parse_args(base + [value for value in confirmations if value != omitted])
            with (
                self.subTest(omitted=omitted),
                patch.object(
                    factory,
                    "_category_image_resume_context",
                    side_effect=AssertionError("确认不全时不应读取或写入生产上下文"),
                ),
                patch.object(factory.subprocess, "Popen") as popen,
                redirect_stdout(io.StringIO()),
            ):
                result = args.handler(args)
            self.assertEqual(result, 2)
            popen.assert_not_called()

    def test_resume_category_images_rejects_stale_hash_without_sidecar(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "resume-category-images",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "job-safe",
                "--resume-plan-sha256",
                "9" * 64,
                "--confirm-resume",
                "--confirm-paid",
                "--confirm-third-party",
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            batch, _, _ = self._resume_fixture(temporary, pid=0)
            output = io.StringIO()
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=resume_plan(),
                ),
                patch.object(factory.subprocess, "Popen") as popen,
                redirect_stdout(output),
            ):
                result = args.handler(args)

            self.assertEqual(result, 2)
            self.assertIn("续跑计划校验码已变化", output.getvalue())
            self.assertFalse((batch / "production" / "resume_authorizations").exists())
            self.assertFalse((batch / "production" / "resume_sessions").exists())
            popen.assert_not_called()

    def test_resume_category_images_rejects_duplicate_active_sidecar(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "resume-category-images",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "job-safe",
                "--resume-plan-sha256",
                "a" * 64,
                "--confirm-resume",
                "--confirm-paid",
                "--confirm-third-party",
            ]
        )

        class FakeProcess:
            pid = 2468

        with tempfile.TemporaryDirectory() as temporary:
            batch, _, _ = self._resume_fixture(temporary, pid=0)
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=resume_plan(),
                ),
                patch.object(
                    factory, "_category_effective_config", return_value=resume_config()
                ),
                patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                patch.object(
                    factory.subprocess, "Popen", return_value=FakeProcess()
                ) as popen,
                redirect_stdout(io.StringIO()),
            ):
                first = args.handler(args)
                second = args.handler(args)

            self.assertEqual(first, 0)
            self.assertEqual(second, 2)
            popen.assert_called_once()
            self.assertEqual(
                len(list((batch / "production" / "resume_authorizations").glob("*.json"))),
                1,
            )

    def test_resume_category_images_records_launch_failure_without_consuming_sidecar(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "resume-category-images",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "job-safe",
                "--resume-plan-sha256",
                "a" * 64,
                "--confirm-resume",
                "--confirm-paid",
                "--confirm-third-party",
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            batch, _, _ = self._resume_fixture(temporary, pid=0)
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=resume_plan(),
                ),
                patch.object(
                    factory, "_category_effective_config", return_value=resume_config()
                ),
                patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                patch.object(factory.subprocess, "Popen", side_effect=OSError("boom")),
                redirect_stdout(io.StringIO()),
            ):
                result = args.handler(args)

            self.assertEqual(result, 2)
            authorization_path = next(
                (batch / "production" / "resume_authorizations").glob("*.json")
            )
            session_path = next(
                (batch / "production" / "resume_sessions").glob("*.json")
            )
            authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
            session = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(authorization["status"], "active")
            self.assertEqual(session["status"], "launch_failed")
            self.assertIsNone(session["pid"])

    def test_resume_authorization_exclusive_write_never_overwrites_existing_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "resume_authorizations" / "resume-safe.json"
            original = {"status": "active", "binding": "original"}
            factory._write_json_exclusive(path, original)
            first_bytes = path.read_bytes()

            with self.assertRaisesRegex(RuntimeError, "禁止覆盖"):
                factory._write_json_exclusive(
                    path, {"status": "active", "binding": "replacement"}
                )

            self.assertEqual(path.read_bytes(), first_bytes)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_stale_resume_crash_archive_preserves_evidence_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context, stale, authorization_path, session_path, events_path = (
                self._consumed_stale_resume_fixture(temporary)
            )
            production = Path(context["production_dir"])
            lock_path = production / "generation.lock"
            original_paths = {
                "authorization": authorization_path,
                "session": session_path,
                "events": events_path,
                "job": Path(context["job_path"]),
                "license": Path(context["license_path"]),
                "log": Path(stale["log_path"]),
                "lock": lock_path,
            }
            original_bytes = {key: path.read_bytes() for key, path in original_paths.items()}
            with patch.object(
                factory.category_image_production, "pid_is_running", return_value=False
            ):
                archive_path = factory._archive_stale_consumed_resume_session(
                    context, stale
                )

            self.assertFalse(lock_path.exists())
            for label in ("authorization", "session", "events", "job", "license", "log"):
                self.assertEqual(original_paths[label].read_bytes(), original_bytes[label])
            archive_bytes = archive_path.read_bytes()
            archive = json.loads(archive_bytes.decode("utf-8"))
            self.assertEqual(
                [row["request_number"] for row in archive["open_reserved_requests"]],
                [8, 9],
            )
            self.assertEqual(set(archive["immutable_copies"]), set(original_paths))
            for label, row in archive["immutable_copies"].items():
                copy_path = archive_path.parent / row["name"]
                self.assertEqual(copy_path.read_bytes(), original_bytes[label])
                self.assertEqual(row["sha256"], hashlib.sha256(original_bytes[label]).hexdigest())
                self.assertEqual(row["size"], len(original_bytes[label]))
            self.assertTrue(
                factory._valid_stale_resume_archive(
                    production,
                    session_path,
                    stale["session"],
                    authorization_path,
                    stale["authorization"],
                )
            )

            stale_without_lock = dict(stale, lock_payload=None)
            with patch.object(
                factory.category_image_production, "pid_is_running", return_value=False
            ):
                repeated = factory._archive_stale_consumed_resume_session(
                    context, stale_without_lock
                )
            self.assertEqual(repeated, archive_path)
            self.assertEqual(archive_path.read_bytes(), archive_bytes)

    def test_stale_resume_crash_archive_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context, stale, authorization_path, session_path, _ = (
                self._consumed_stale_resume_fixture(temporary)
            )
            production = Path(context["production_dir"])
            with patch.object(
                factory.category_image_production, "pid_is_running", return_value=False
            ):
                archive_path = factory._archive_stale_consumed_resume_session(
                    context, stale
                )
            archive = json.loads(archive_path.read_text(encoding="utf-8"))
            archive["authorization_cumulative_request_cap"] += 1
            archive_path.write_text(
                json.dumps(archive, ensure_ascii=False), encoding="utf-8"
            )
            with patch.object(
                factory.category_image_production, "pid_is_running", return_value=False
            ):
                self.assertFalse(
                    factory._valid_stale_resume_archive(
                        production,
                        session_path,
                        stale["session"],
                        authorization_path,
                        stale["authorization"],
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "已有续跑会话"):
                    factory._require_no_active_resume_session(
                        production / "resume_authorizations",
                        production / "resume_sessions",
                        "job-safe",
                        "license-safe",
                    )

    def test_stale_resume_crash_archive_rejects_copy_duplicate_and_lock_cas_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context, stale, authorization_path, session_path, _ = (
                self._consumed_stale_resume_fixture(temporary)
            )
            production = Path(context["production_dir"])
            original_write = factory._write_json_exclusive

            def tamper_lock_after_sidecar(path: Path, payload: dict) -> None:
                original_write(path, payload)
                if path.name == "archive.json":
                    Path(stale["lock_path"]).write_text(
                        json.dumps({"job_id": "job-safe", "pid": 9999}),
                        encoding="utf-8",
                    )

            with (
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(factory, "_write_json_exclusive", side_effect=tamper_lock_after_sidecar),
                self.assertRaisesRegex(RuntimeError, "发生变化"),
            ):
                factory._archive_stale_consumed_resume_session(context, stale)
            lock_path = Path(stale["lock_path"])
            self.assertTrue(lock_path.is_file())

            archive_path = next(
                (production / "resume_crash_archives").glob("*/archive.json")
            )
            lock_copy = archive_path.parent / "generation.lock.json"
            lock_copy.write_bytes(lock_copy.read_bytes() + b"tamper")
            with patch.object(
                factory.category_image_production, "pid_is_running", return_value=False
            ):
                self.assertFalse(
                    factory._valid_stale_resume_archive(
                        production,
                        session_path,
                        stale["session"],
                        authorization_path,
                        stale["authorization"],
                    )
                )
            duplicate = production / "resume_crash_archives" / "resume-old_duplicated"
            duplicate.mkdir()
            (duplicate / "archive.json").write_bytes(archive_path.read_bytes())
            with patch.object(
                factory.category_image_production, "pid_is_running", return_value=False
            ):
                self.assertFalse(
                    factory._valid_stale_resume_archive(
                        production,
                        session_path,
                        stale["session"],
                        authorization_path,
                        stale["authorization"],
                    )
                )

    def test_archived_old_resume_does_not_match_a_new_generation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context, stale, _, _, _ = self._consumed_stale_resume_fixture(temporary)
            production = Path(context["production_dir"])
            with patch.object(
                factory.category_image_production, "pid_is_running", return_value=False
            ):
                factory._archive_stale_consumed_resume_session(context, stale)

            new_authorization_id = "resume-new"
            authorization_dir = production / "resume_authorizations"
            session_dir = production / "resume_sessions"
            log_dir = production / "logs"
            old_auth = dict(stale["authorization"])
            old_auth.update(
                {
                    "authorization_id": new_authorization_id,
                    "resume_plan_sha256": "9" * 64,
                    "requests_used": 9,
                    "approved_cumulative_request_budget": 13,
                }
            )
            new_auth_path = authorization_dir / f"{new_authorization_id}.json"
            new_session_path = session_dir / f"{new_authorization_id}.json"
            new_log_path = log_dir / f"{new_authorization_id}.log"
            old_auth["status"] = "consumed"
            new_auth_path.write_text(json.dumps(old_auth), encoding="utf-8")
            new_session = dict(stale["session"])
            new_session.update(
                {
                    "authorization_id": new_authorization_id,
                    "resume_plan_sha256": "9" * 64,
                    "pid": 3579,
                    "authorization_file": str(new_auth_path.resolve()),
                    "log_file": str(new_log_path.resolve()),
                }
            )
            new_session_path.write_text(json.dumps(new_session), encoding="utf-8")
            new_log_path.write_text("new worker stopped\n", encoding="utf-8")
            (production / "generation.lock").write_text(
                json.dumps({"job_id": "job-safe", "pid": 3579}), encoding="utf-8"
            )
            with patch.object(
                factory.category_image_production, "pid_is_running", return_value=False
            ):
                matched = factory._stale_consumed_resume_session(context)
            self.assertIsNotNone(matched)
            self.assertEqual(matched["authorization_id"], new_authorization_id)
            self.assertEqual(matched["session_pid"], 3579)

    def test_restart_resume_category_images_reuses_active_authorization_after_zero_requests(self) -> None:
        parser = factory.build_parser()
        start_args = parser.parse_args(
            [
                "resume-category-images",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "job-safe",
                "--resume-plan-sha256",
                "a" * 64,
                "--confirm-resume",
                "--confirm-paid",
                "--confirm-third-party",
            ]
        )
        restart_args = parser.parse_args(
            [
                "restart-resume-category-images",
                "--category",
                "pipe_unclogging",
                "--job-id",
                "job-safe",
                "--resume-plan-sha256",
                "a" * 64,
                "--confirm-resume",
                "--confirm-paid",
                "--confirm-third-party",
            ]
        )

        class FirstProcess:
            pid = 2468

        class RestartProcess:
            pid = 3579

        with tempfile.TemporaryDirectory() as temporary:
            batch, job_path, license_path = self._resume_fixture(temporary, pid=0)
            events_path = self._add_resume_event_fixture(batch)
            frozen_plan = resume_plan_for_events(events_path)
            output = io.StringIO()
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=frozen_plan,
                ),
                patch.object(
                    factory, "_category_effective_config", return_value=resume_config()
                ),
                patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                patch.object(
                    factory.subprocess,
                    "Popen",
                    side_effect=[FirstProcess(), RestartProcess()],
                ) as popen,
                patch.object(
                    factory.category_image_production,
                    "write_new_license",
                    side_effect=AssertionError("零请求重启不应新建生产许可证"),
                ),
                patch.object(
                    factory.category_image_production.image_generate,
                    "generate_one",
                    side_effect=AssertionError("factory重启入口不应调用图片 API"),
                ),
                redirect_stdout(output),
            ):
                first = start_args.handler(start_args)
                authorization_path = next(
                    (batch / "production" / "resume_authorizations").glob("*.json")
                )
                authorization_bytes = authorization_path.read_bytes()
                original_job = job_path.read_bytes()
                original_license = license_path.read_bytes()
                restarted = restart_args.handler(restart_args)

            rendered = output.getvalue()
            self.assertEqual(first, 0, rendered)
            self.assertEqual(restarted, 0, rendered)
            self.assertIn("已使用原授权重新启动", rendered)
            self.assertIn("可续跑目标：5；本次最多请求：8；累计最多请求：14 / 20", rendered)
            self.assertEqual(popen.call_count, 2)
            self.assertEqual(
                len(list((batch / "production" / "resume_authorizations").glob("*.json"))),
                1,
            )
            self.assertEqual(authorization_path.read_bytes(), authorization_bytes)
            session_path = next(
                (batch / "production" / "resume_sessions").glob("*.json")
            )
            session = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(session["status"], "starting")
            self.assertEqual(session["pid"], 3579)
            self.assertEqual(session["previous_launcher_pid"], 2468)
            self.assertEqual(session["restart_count"], 1)
            self.assertEqual(session["restart_reason"], "zero_request_startup_failure")
            self.assertEqual(job_path.read_bytes(), original_job)
            self.assertEqual(license_path.read_bytes(), original_license)
            command = popen.call_args_list[1].args[0]
            self.assertIn("--resume-authorization", command)
            self.assertIn("--session-file", command)
            self.assertEqual(
                command[command.index("--resume-plan-sha256") + 1], "a" * 64
            )
            self.assertEqual(
                popen.call_args_list[1].kwargs["env"]["PIPE_CATEGORY_NETWORK_MODE"],
                "proxy:test",
            )

    def test_restart_resume_category_images_requires_all_confirmations_before_context(self) -> None:
        parser = factory.build_parser()
        base = [
            "restart-resume-category-images",
            "--category",
            "pipe_unclogging",
            "--job-id",
            "job-safe",
            "--resume-plan-sha256",
            "a" * 64,
        ]
        confirmations = (
            "--confirm-resume",
            "--confirm-paid",
            "--confirm-third-party",
        )
        for omitted in confirmations:
            args = parser.parse_args(base + [value for value in confirmations if value != omitted])
            with (
                self.subTest(omitted=omitted),
                patch.object(
                    factory,
                    "_category_image_resume_context",
                    side_effect=AssertionError("确认不全时不应读取生产上下文"),
                ),
                patch.object(factory.subprocess, "Popen") as popen,
                redirect_stdout(io.StringIO()),
            ):
                result = args.handler(args)
            self.assertEqual(result, 2)
            popen.assert_not_called()

    def test_restart_resume_category_images_rejects_live_launcher_without_writes(self) -> None:
        parser = factory.build_parser()
        common = [
            "--category",
            "pipe_unclogging",
            "--job-id",
            "job-safe",
            "--resume-plan-sha256",
            "a" * 64,
            "--confirm-resume",
            "--confirm-paid",
            "--confirm-third-party",
        ]
        start_args = parser.parse_args(["resume-category-images", *common])
        restart_args = parser.parse_args(["restart-resume-category-images", *common])

        class FirstProcess:
            pid = 2468

        with tempfile.TemporaryDirectory() as temporary:
            batch, _, _ = self._resume_fixture(temporary, pid=0)
            events_path = self._add_resume_event_fixture(batch)
            frozen_plan = resume_plan_for_events(events_path)
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=frozen_plan,
                ),
                patch.object(
                    factory, "_category_effective_config", return_value=resume_config()
                ),
                patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory.subprocess, "Popen", return_value=FirstProcess()
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(start_args.handler(start_args), 0)
            authorization_path = next(
                (batch / "production" / "resume_authorizations").glob("*.json")
            )
            session_path = next(
                (batch / "production" / "resume_sessions").glob("*.json")
            )
            before = {
                authorization_path: authorization_path.read_bytes(),
                session_path: session_path.read_bytes(),
            }
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=frozen_plan,
                ),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=True,
                ),
                patch.object(factory.subprocess, "Popen") as popen,
                redirect_stdout(io.StringIO()),
            ):
                result = restart_args.handler(restart_args)

            self.assertEqual(result, 2)
            popen.assert_not_called()
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_restart_resume_category_images_rejects_consumed_authorization(self) -> None:
        parser = factory.build_parser()
        common = [
            "--category",
            "pipe_unclogging",
            "--job-id",
            "job-safe",
            "--resume-plan-sha256",
            "a" * 64,
            "--confirm-resume",
            "--confirm-paid",
            "--confirm-third-party",
        ]
        start_args = parser.parse_args(["resume-category-images", *common])
        restart_args = parser.parse_args(["restart-resume-category-images", *common])

        class FirstProcess:
            pid = 2468

        with tempfile.TemporaryDirectory() as temporary:
            batch, _, _ = self._resume_fixture(temporary, pid=0)
            events_path = self._add_resume_event_fixture(batch)
            frozen_plan = resume_plan_for_events(events_path)
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=frozen_plan,
                ),
                patch.object(
                    factory, "_category_effective_config", return_value=resume_config()
                ),
                patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                patch.object(
                    factory.subprocess, "Popen", return_value=FirstProcess()
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(start_args.handler(start_args), 0)
            authorization_path = next(
                (batch / "production" / "resume_authorizations").glob("*.json")
            )
            authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
            authorization["status"] = "consumed"
            authorization_path.write_text(
                json.dumps(authorization, ensure_ascii=False), encoding="utf-8"
            )
            session_path = next(
                (batch / "production" / "resume_sessions").glob("*.json")
            )
            session_before = session_path.read_bytes()
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=frozen_plan,
                ),
                patch.object(factory.subprocess, "Popen") as popen,
                redirect_stdout(io.StringIO()),
            ):
                result = restart_args.handler(restart_args)

            self.assertEqual(result, 2)
            popen.assert_not_called()
            self.assertEqual(session_path.read_bytes(), session_before)

    def test_restart_resume_category_images_rejects_any_job_license_or_event_delta(self) -> None:
        parser = factory.build_parser()
        common = [
            "--category",
            "pipe_unclogging",
            "--job-id",
            "job-safe",
            "--resume-plan-sha256",
            "a" * 64,
            "--confirm-resume",
            "--confirm-paid",
            "--confirm-third-party",
        ]
        start_args = parser.parse_args(["resume-category-images", *common])
        restart_args = parser.parse_args(["restart-resume-category-images", *common])

        class FirstProcess:
            pid = 2468

        for changed_file in ("job", "license", "events"):
            with self.subTest(changed_file=changed_file), tempfile.TemporaryDirectory() as temporary:
                batch, job_path, license_path = self._resume_fixture(temporary, pid=0)
                events_path = self._add_resume_event_fixture(batch)
                frozen_plan = resume_plan_for_events(events_path)
                with (
                    patch.object(factory, "category_active_batch_dir", return_value=batch),
                    patch.object(
                        factory.category_image_production,
                        "pid_is_running",
                        return_value=False,
                    ),
                    patch.object(
                        factory,
                        "_build_category_image_resume_plan",
                        return_value=frozen_plan,
                    ),
                    patch.object(
                        factory, "_category_effective_config", return_value=resume_config()
                    ),
                    patch.object(
                        factory,
                        "_category_proxy_environment",
                        return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                    ),
                    patch.object(
                        factory.subprocess, "Popen", return_value=FirstProcess()
                    ),
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(start_args.handler(start_args), 0)
                if changed_file == "events":
                    with events_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"status": "resume_started"}) + "\n")
                else:
                    target = job_path if changed_file == "job" else license_path
                    payload = json.loads(target.read_text(encoding="utf-8"))
                    payload["requests_used"] = 7
                    target.write_text(
                        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                    )
                session_path = next(
                    (batch / "production" / "resume_sessions").glob("*.json")
                )
                session_before = session_path.read_bytes()
                with (
                    patch.object(factory, "category_active_batch_dir", return_value=batch),
                    patch.object(
                        factory.category_image_production,
                        "pid_is_running",
                        return_value=False,
                    ),
                    patch.object(
                        factory,
                        "_build_category_image_resume_plan",
                        return_value=frozen_plan,
                    ),
                    patch.object(factory.subprocess, "Popen") as popen,
                    redirect_stdout(io.StringIO()),
                ):
                    result = restart_args.handler(restart_args)

                self.assertEqual(result, 2)
                popen.assert_not_called()
                self.assertEqual(session_path.read_bytes(), session_before)

    def test_restart_resume_category_images_restores_dead_starting_session_on_popen_failure(self) -> None:
        parser = factory.build_parser()
        common = [
            "--category",
            "pipe_unclogging",
            "--job-id",
            "job-safe",
            "--resume-plan-sha256",
            "a" * 64,
            "--confirm-resume",
            "--confirm-paid",
            "--confirm-third-party",
        ]
        start_args = parser.parse_args(["resume-category-images", *common])
        restart_args = parser.parse_args(["restart-resume-category-images", *common])

        class FirstProcess:
            pid = 2468

        with tempfile.TemporaryDirectory() as temporary:
            batch, _, _ = self._resume_fixture(temporary, pid=0)
            events_path = self._add_resume_event_fixture(batch)
            frozen_plan = resume_plan_for_events(events_path)
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=frozen_plan,
                ),
                patch.object(
                    factory, "_category_effective_config", return_value=resume_config()
                ),
                patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                patch.object(
                    factory.subprocess, "Popen", return_value=FirstProcess()
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(start_args.handler(start_args), 0)

            authorization_path = next(
                (batch / "production" / "resume_authorizations").glob("*.json")
            )
            authorization_bytes = authorization_path.read_bytes()
            session_path = next(
                (batch / "production" / "resume_sessions").glob("*.json")
            )
            with (
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(
                    factory.category_image_production,
                    "pid_is_running",
                    return_value=False,
                ),
                patch.object(
                    factory,
                    "_build_category_image_resume_plan",
                    return_value=frozen_plan,
                ),
                patch.object(
                    factory, "_category_effective_config", return_value=resume_config()
                ),
                patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                patch.object(factory.subprocess, "Popen", side_effect=OSError("boom")),
                redirect_stdout(io.StringIO()),
            ):
                result = restart_args.handler(restart_args)

            self.assertEqual(result, 2)
            self.assertEqual(authorization_path.read_bytes(), authorization_bytes)
            session = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(session["status"], "starting")
            self.assertEqual(session["pid"], 2468)
            self.assertEqual(session["restart_count"], 1)
            self.assertIn("OSError", session["last_restart_launch_error"])

    def test_cover_approval_record_is_bound_to_group_position_and_phone(self) -> None:
        validation = {
            "category_id": "pipe_unclogging",
            "group_index": 1,
            "position": 1,
            "role": "cover",
            "postprocessed_locally": True,
            "expected_text": [f"电话：{PHONE}", f"联系电话：{PHONE}"],
            "expected_size": "1024x1408",
            "status": "approved",
            "approved": True,
            "manual_visual_approval": True,
        }
        factory._validate_pipe_cover_record(
            validation, 1, PHONE, (1024, 1408), require_approved=True
        )
        for key, bad_value in (("group_index", 2), ("position", 2), ("postprocessed_locally", False)):
            broken = dict(validation)
            broken[key] = bad_value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                factory._validate_pipe_cover_record(
                    broken, 1, PHONE, (1024, 1408), require_approved=True
                )

    def test_stale_job_timestamp_is_not_treated_as_active_forever(self) -> None:
        recent = {"updated_at": datetime.now(timezone.utc).isoformat()}
        old = {
            "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        }
        self.assertTrue(factory._recent_job_update(recent))
        self.assertFalse(factory._recent_job_update(old))

    def test_cover_authorization_binds_exact_plan_without_calling_image_api(self) -> None:
        parser = factory.build_parser()
        args = parser.parse_args(
            [
                "authorize-category-images",
                "--category",
                "pipe_unclogging",
                "--scope",
                "covers",
                "--plan-sha256",
                "plan-123",
                "--max-requests",
                "6",
                "--auto-retry-limit",
                "1",
                "--confirm-paid",
            ]
        )
        config = pipe_config()
        run_plan = v2_plan(
            "covers",
            pending_api_requests=3,
            delivery_count=3,
            pending_delivery_count=3,
            plan_sha256="plan-123",
        )
        with tempfile.TemporaryDirectory() as temporary:
            batch = Path(temporary) / "batch_test"
            batch.mkdir()

            def fake_license_path(_category, _batch, _start, _count, license_id=None):
                if license_id:
                    return batch / "production" / "licenses" / f"{license_id}.json"
                return batch / "production" / "old-license.json"

            with (
                patch.object(factory, "_category_effective_config", return_value=config),
                patch.object(factory, "category_active_batch_dir", return_value=batch),
                patch.object(factory, "_category_confirmed_phone", return_value=PHONE),
                patch.object(factory, "_category_output_root", return_value=factory.PIPE_OUTPUT_ROOT),
                patch.object(factory, "selected_key_slots", return_value=[1]),
                patch.object(factory.category_image_production, "plan", return_value=run_plan),
                patch.object(
                    factory.category_image_production,
                    "write_production_files",
                    return_value=(batch / "manifest.jsonl", batch / "overlay.json"),
                ),
                patch.object(
                    factory.category_image_production,
                    "license_path",
                    side_effect=fake_license_path,
                ),
                patch.object(factory.category_image_production, "write_new_license") as write_license,
                patch.object(
                    factory.category_image_production.image_generate,
                    "generate_one",
                    side_effect=AssertionError("授权阶段不应调用生图接口"),
                ),
                redirect_stdout(io.StringIO()),
            ):
                result = args.handler(args)

        self.assertEqual(result, 0)
        payload = write_license.call_args.args[1]
        self.assertEqual(payload["scope"], "covers")
        self.assertEqual(payload["approved_image_count"], 3)
        self.assertEqual(payload["approved_request_budget"], 6)
        self.assertEqual(payload["approved_target_ids"], run_plan["delivery_target_ids"])
        self.assertEqual(
            payload["approved_generation_target_ids"],
            run_plan["generation_target_ids"],
        )
        self.assertEqual(payload["plan_sha256"], "plan-123")
        self.assertEqual(payload["production_schema_version"], 3)
        self.assertEqual(payload["max_attempts"], 2)
        self.assertEqual(
            payload["retry_policy"],
            factory.category_image_production.CLASSIFIED_RETRY_POLICY,
        )
        self.assertEqual(payload["sdk_max_retries"], 0)
        self.assertEqual(payload["max_workers"], 1)

    def test_details_authorization_stops_before_license_without_cover_evidence(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "authorize-category-images",
                "--category",
                "pipe_unclogging",
                "--scope",
                "details",
                "--plan-sha256",
                "details-plan",
                "--max-requests",
                "18",
                "--confirm-paid",
            ]
        )
        run_plan = v2_plan(
            "details",
            pending_api_requests=18,
            delivery_count=12,
            pending_delivery_count=12,
            plan_sha256="details-plan",
        )
        with (
            patch.object(factory, "_pipe_effective_config", return_value=pipe_config()),
            patch.object(factory, "pipe_active_batch_dir", return_value=PIPE_BATCH),
            patch.object(factory, "_pipe_confirmed_phone", return_value=PHONE),
            patch.object(factory, "selected_key_slots", return_value=[1, 2]),
            patch.object(factory.category_image_production, "plan", return_value=run_plan),
            patch.object(
                factory,
                "_pipe_cover_approval_evidence",
                side_effect=RuntimeError("首图尚未确认"),
            ),
            patch.object(factory.category_image_production, "write_new_license") as write_license,
            redirect_stdout(io.StringIO()),
        ):
            result = args.handler(args)

        self.assertEqual(result, 2)
        write_license.assert_not_called()

    def test_sample_commands_default_to_exactly_three_groups(self) -> None:
        parser = factory.build_parser()
        commands = [
            ["category-image-plan"],
            [
                "authorize-category-images",
                "--category",
                "pipe_unclogging",
                "--scope",
                "covers",
                "--plan-sha256",
                "test-plan",
                "--max-requests",
                "3",
            ],
            [
                "start-category-images",
                "--category",
                "pipe_unclogging",
                "--scope",
                "covers",
                "--license-id",
                "test-license",
            ],
            [
                "confirm-start-category-images",
                "--category",
                "pipe_unclogging",
                "--scope",
                "covers",
                "--plan-sha256",
                "test-plan",
                "--max-requests",
                "3",
            ],
        ]
        for command in commands:
            with self.subTest(command=command[0]):
                args = parser.parse_args(command)
                self.assertEqual(args.group_start, 1)
                self.assertEqual(args.group_count, 3)
                if command[0] == "category-image-plan":
                    self.assertEqual(args.scope, "all")

    def test_category_worker_limit_defaults_to_ten_available_keys(self) -> None:
        slots = list(range(1, 11))
        self.assertEqual(factory._category_max_workers(None, slots, 90), 10)
        self.assertEqual(factory._category_max_workers(None, slots, 3), 3)
        self.assertEqual(factory._category_max_workers(6, slots, 90), 6)
        with self.assertRaisesRegex(RuntimeError, "1 到 10"):
            factory._category_max_workers(11, slots, 90)

    def test_fixed_ten_policy_is_explicit_on_paid_commands(self) -> None:
        parser = factory.build_parser()
        for command in ("authorize-category-images", "confirm-start-category-images"):
            with self.subTest(command=command):
                args = parser.parse_args(
                    [
                        command,
                        "--category",
                        "road_rescue",
                        "--scope",
                        "details",
                        "--plan-sha256",
                        "plan-123",
                        "--max-requests",
                        "40",
                        "--max-workers",
                        "10",
                        "--concurrency-policy",
                        "fixed-10",
                    ]
                )
                self.assertEqual(args.max_workers, 10)
                self.assertEqual(args.concurrency_policy, "fixed-10")

        plan_args = parser.parse_args(
            ["category-image-plan", "--auto-retry-limit", "1"]
        )
        self.assertEqual(plan_args.auto_retry_limit, 1)

    def test_confirm_start_authorizes_then_starts_exactly_once(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "confirm-start-category-images",
                "--category",
                "pipe_unclogging",
                "--scope",
                "covers",
                "--plan-sha256",
                "plan-123",
                "--max-requests",
                "3",
                "--confirm-paid",
            ]
        )

        def authorize(namespace):
            namespace.created_license_id = "one-click-license"
            return 0

        with (
            patch.object(factory, "command_authorize_category_images", side_effect=authorize) as authorize_mock,
            patch.object(factory, "command_start_category_images", return_value=0) as start_mock,
        ):
            result = args.handler(args)

        self.assertEqual(result, 0)
        authorize_mock.assert_called_once_with(args)
        start_mock.assert_called_once()
        start_args = start_mock.call_args.args[0]
        self.assertEqual(start_args.license_id, "one-click-license")
        self.assertEqual(start_args.scope, "covers")

    def test_confirm_start_never_starts_when_authorization_fails(self) -> None:
        args = factory.build_parser().parse_args(
            [
                "confirm-start-category-images",
                "--category",
                "pipe_unclogging",
                "--scope",
                "covers",
                "--plan-sha256",
                "stale-plan",
                "--max-requests",
                "3",
            ]
        )
        with (
            patch.object(factory, "command_authorize_category_images", return_value=2),
            patch.object(factory, "command_start_category_images") as start_mock,
        ):
            result = args.handler(args)

        self.assertEqual(result, 2)
        start_mock.assert_not_called()

    def test_category_image_plan_counts_real_first_three_groups_without_license(self) -> None:
        self.assertTrue(PIPE_BATCH.is_dir(), "管道疏通 v2 活动批次不存在")
        parser = factory.build_parser()
        config = pipe_config()
        before = license_snapshot()
        expected = {
            "covers": (
                "最终要交付 3 张成品；成品已有 0 张；可本地恢复 0 张；还缺 3 张成品。",
                "本次仍需 3 次付费图片请求。",
            ),
            "details": (
                "最终要交付 12 张成品；成品已有 0 张；可本地恢复 0 张；还缺 12 张成品。",
                "本次仍需 18 次付费图片请求。",
            ),
        }

        for scope, expected_lines in expected.items():
            with self.subTest(scope=scope):
                args = parser.parse_args(["category-image-plan", "--scope", scope])
                output = io.StringIO()
                with (
                    patch.object(factory, "_category_effective_config", return_value=config),
                    patch.object(factory, "_category_confirmed_phone", return_value=PHONE),
                    patch.object(factory, "category_active_batch_dir", return_value=PIPE_BATCH),
                    patch.object(factory, "_category_output_root", return_value=factory.PIPE_OUTPUT_ROOT),
                    patch.object(
                        factory.category_image_production,
                        "plan",
                        return_value=v2_plan(
                            scope,
                            pending_api_requests=3 if scope == "covers" else 18,
                            delivery_count=3 if scope == "covers" else 12,
                            pending_delivery_count=3 if scope == "covers" else 12,
                            plan_sha256=f"{scope}-plan",
                        ),
                    ),
                    patch.object(
                        factory,
                        "write_json_atomic",
                        side_effect=AssertionError("核算命令不应写入任何 JSON"),
                    ),
                    patch.object(
                        factory.category_image_production,
                        "write_new_license",
                        side_effect=AssertionError("核算命令不应创建许可证"),
                    ),
                    patch.object(
                        factory.category_image_production.image_generate,
                        "generate_one",
                        side_effect=AssertionError("核算命令不应调用生图接口"),
                    ),
                    redirect_stdout(output),
                ):
                    result = args.handler(args)

                self.assertEqual(result, 0, output.getvalue())
                for expected_line in expected_lines:
                    self.assertIn(expected_line, output.getvalue())
                self.assertIn(
                    "本次最终成品尺寸：1024x1408, 1024x1472, 1024x1536",
                    output.getvalue(),
                )
                self.assertIn("本命令未创建许可证、未调用 API、未产生费用。", output.getvalue())

        self.assertEqual(before, license_snapshot())

    def test_generic_group_authorize_and_start_are_blocked_for_pipe(self) -> None:
        parser = factory.build_parser()
        authorize = parser.parse_args(
            [
                "authorize-groups",
                "--project-id",
                "pipe_unclogging",
                "--group-start",
                "1",
                "--group-count",
                "3",
                "--max-requests",
                "27",
                "--confirm-paid",
            ]
        )
        start = parser.parse_args(
            [
                "start-groups",
                "--project-id",
                "pipe_unclogging",
                "--group-start",
                "1",
                "--group-count",
                "3",
            ]
        )
        before = license_snapshot()

        with (
            patch.object(
                factory,
                "write_json_atomic",
                side_effect=AssertionError("通用入口不应写入许可证或任务"),
            ),
            patch.object(
                factory.subprocess,
                "Popen",
                side_effect=AssertionError("通用入口不应启动任务"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "3组样板安全入口"):
                authorize.handler(authorize)
            with self.assertRaisesRegex(RuntimeError, "不能使用通用 start-groups"):
                start.handler(start)

        self.assertEqual(before, license_snapshot())

    def test_project_status_recognizes_formal_pipe_project(self) -> None:
        args = factory.build_parser().parse_args(
            ["project-status", "pipe_unclogging"]
        )
        output = io.StringIO()
        with (
            patch.object(
                factory,
                "write_json_atomic",
                side_effect=AssertionError("项目状态命令不应写文件"),
            ),
            redirect_stdout(output),
        ):
            result = args.handler(args)

        rendered = output.getvalue()
        self.assertEqual(result, 0, rendered)
        self.assertIn("PROJECT_STATUS id=pipe_unclogging name=管道疏通", rendered)
        self.assertIn("Groups created: 30", rendered)
        self.assertIn(
            "Content group: 1 cover + 1 triptych + 3 details = 5 delivery images",
            rendered,
        )
        self.assertIn("这个类目现在已经是正式项目，不会再报 unknown project。", rendered)
        self.assertIn("本命令只读取本地记录，不生成图片、不调用 API、不收费。", rendered)


if __name__ == "__main__":
    unittest.main()
