from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import factory


def balance_resume_plan() -> dict:
    success = "truck_rescue:v3:g0044:u02"
    balance = "truck_rescue:v3:g0102:u03"
    unattempted = "truck_rescue:v3:g0125:u05"
    attempts_used = {success: 1, balance: 1, unattempted: 0}
    attempts_remaining = {success: 0, balance: 2, unattempted: 2}
    return {
        "schema_version": 1,
        "job_id": "truck-job",
        "license_id": "truck-license",
        "category_id": "truck_rescue",
        "batch_id": "batch_v3_active",
        "provider": "relay",
        "model": "gpt-image-1",
        "quality": "medium",
        "size": "1024x1536",
        "max_attempts": 2,
        "retry_policy": "classified_once_v1",
        "budget": 6,
        "requests_used": 2,
        "remaining_max_requests": 4,
        "cumulative_max_requests": 6,
        "balance_failure_request_count": 1,
        "counts": {
            "total": 3,
            "success": 1,
            "exhausted": 0,
            "balance_recoverable": 1,
            "unknown": 0,
            "unattempted": 1,
            "resumable": 2,
        },
        "success_ids": [success],
        "exhausted_ids": [],
        "balance_recoverable_ids": [balance],
        "unknown_ids": [],
        "unattempted_ids": [unattempted],
        "resumable_ids": [balance, unattempted],
        "attempts_used": attempts_used,
        "attempts_remaining": attempts_remaining,
        "resume_plan_sha256": "a" * 64,
        "frozen_manifest_sha256": "b" * 64,
        "frozen_overlay_sha256": "c" * 64,
        "events_sha256": "d" * 64,
        "event_tail_sha256": "e" * 64,
    }


def fixed_ten_resume_plan() -> dict:
    plan = balance_resume_plan()
    existing = plan["unattempted_ids"][0]
    added = [f"truck_rescue:v3:g{group:04d}:u05" for group in range(126, 134)]
    unattempted = [existing, *added]
    success = plan["success_ids"][0]
    balance = plan["balance_recoverable_ids"][0]
    plan.update(
        {
            "budget": 22,
            "remaining_max_requests": 20,
            "cumulative_max_requests": 22,
            "counts": {
                "total": 11,
                "success": 1,
                "exhausted": 0,
                "balance_recoverable": 1,
                "unknown": 0,
                "unattempted": 9,
                "resumable": 10,
            },
            "unattempted_ids": unattempted,
            "resumable_ids": [balance, *unattempted],
            "attempts_used": {success: 1, balance: 1, **dict.fromkeys(unattempted, 0)},
            "attempts_remaining": {
                success: 0,
                balance: 2,
                **dict.fromkeys(unattempted, 2),
            },
        }
    )
    return plan


def no_balance_resume_plan() -> dict:
    success = "truck_rescue:v3:g0044:u02"
    unattempted = "truck_rescue:v3:g0044:u03"
    return {
        "schema_version": 1,
        "job_id": "truck-job",
        "license_id": "truck-license",
        "category_id": "truck_rescue",
        "batch_id": "batch_v3_active",
        "provider": "relay",
        "model": "gpt-image-1",
        "quality": "medium",
        "size": "1024x1536",
        "max_attempts": 2,
        "retry_policy": "classified_once_v1",
        "budget": 3,
        "requests_used": 1,
        "remaining_max_requests": 2,
        "cumulative_max_requests": 3,
        "balance_failure_request_count": 0,
        "counts": {
            "total": 2,
            "success": 1,
            "exhausted": 0,
            "balance_recoverable": 0,
            "unknown": 0,
            "unattempted": 1,
            "resumable": 1,
        },
        "success_ids": [success],
        "exhausted_ids": [],
        "balance_recoverable_ids": [],
        "unknown_ids": [],
        "unattempted_ids": [unattempted],
        "resumable_ids": [unattempted],
        "attempts_used": {success: 1, unattempted: 0},
        "attempts_remaining": {success: 0, unattempted: 2},
        "resume_plan_sha256": "a" * 64,
        "frozen_manifest_sha256": "b" * 64,
        "frozen_overlay_sha256": "c" * 64,
        "events_sha256": "d" * 64,
        "event_tail_sha256": "e" * 64,
    }


def resume_command_context(
    root: Path,
    plan: dict,
    *,
    api_key_slots: list[int] | None = None,
) -> dict:
    batch = root / "batch_v3_active"
    production = batch / "production"
    job_path = production / "jobs" / "truck-job.json"
    license_path = production / "licenses" / "truck-license.json"
    job_path.parent.mkdir(parents=True)
    license_path.parent.mkdir(parents=True)
    job = {"job_id": "truck-job", "requests_used": plan["requests_used"]}
    job_path.write_text(json.dumps(job), encoding="utf-8")
    license_data = {
        "license_id": "truck-license",
        "plan_sha256": "f" * 64,
        "approved_request_budget": plan["approved_request_budget"],
        "requests_used": plan["requests_used"],
        "max_attempts": 2,
        "retry_policy": "classified_once_v1",
        "provider": "relay",
        "base_url": "https://relay.example",
        "model": "gpt-image-1",
        "quality": "medium",
        "size": "1024x1536",
        "third_party_confirmed": True,
    }
    if api_key_slots is not None:
        license_data["api_key_slots"] = api_key_slots
    license_path.write_text(json.dumps(license_data), encoding="utf-8")
    return {
        "category_id": "truck_rescue",
        "job_id": "truck-job",
        "license_id": "truck-license",
        "batch_dir": batch,
        "production_dir": production,
        "job_path": job_path,
        "job": job,
        "license_path": license_path,
        "license": license_data,
        "resume_plan": plan,
    }


def resume_command_args(*, max_workers: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        category="truck_rescue",
        job_id="truck-job",
        batch_dir=None,
        resume_plan_sha256="a" * 64,
        max_workers=max_workers,
        confirm_resume=True,
        confirm_paid=True,
        confirm_third_party=True,
        archive_stale_consumed_session=False,
    )


class BalanceRecoveryFactoryTests(unittest.TestCase):
    def _assert_launch_failed_restart(self, max_workers: int) -> None:
        plan = factory._validated_category_resume_plan(fixed_ten_resume_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(
                Path(temporary), plan, api_key_slots=list(range(1, 11))
            )
            event_path = (
                context["production_dir"] / "events_truck-job.jsonl"
            )
            event_bytes = (
                json.dumps({"status": "generated", "request_number": 2}).encode()
                + b"\n"
            )
            event_path.write_bytes(event_bytes)
            event_lines = [line for line in event_bytes.splitlines() if line.strip()]
            plan["events_sha256"] = hashlib.sha256(event_bytes).hexdigest()
            plan["event_tail_sha256"] = hashlib.sha256(
                event_lines[-1]
            ).hexdigest()

            config = {
                "provider": "relay",
                "base_url": "https://relay.example",
                "model": "gpt-image-1",
                "quality": "medium",
                "api_size": "1024x1536",
            }
            clients = [(slot, object()) for slot in range(1, 11)]
            restart_args = SimpleNamespace(
                category="truck_rescue",
                job_id="truck-job",
                batch_dir=None,
                resume_plan_sha256="a" * 64,
                confirm_resume=True,
                confirm_paid=True,
                confirm_third_party=True,
            )
            restarted_process = SimpleNamespace(pid=8765)
            output = io.StringIO()

            with (
                mock.patch.object(
                    factory, "_category_image_resume_context", return_value=context
                ),
                mock.patch.object(factory, "_category_effective_config", return_value=config),
                mock.patch.object(
                    factory.category_image_production,
                    "openai_clients_by_slot",
                    return_value=clients,
                ),
                mock.patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                mock.patch.object(
                    factory, "_independent_python_environment", side_effect=lambda env: env
                ),
                mock.patch.object(
                    factory, "_independent_python_executable", return_value="python"
                ),
                mock.patch.object(
                    factory.subprocess,
                    "Popen",
                    side_effect=[OSError("launcher unavailable"), restarted_process],
                ) as popen,
                mock.patch.object(
                    factory.category_image_production.image_generate,
                    "generate_one",
                    side_effect=AssertionError("factory 不得调用图片 API"),
                ),
                contextlib.redirect_stdout(output),
            ):
                first = factory.command_resume_category_images(
                    resume_command_args(max_workers=max_workers)
                )
                authorization_path = next(
                    (context["production_dir"] / "resume_authorizations").glob("*.json")
                )
                authorization_before = authorization_path.read_bytes()
                session_path = next(
                    (context["production_dir"] / "resume_sessions").glob("*.json")
                )
                failed_session = json.loads(session_path.read_text(encoding="utf-8"))
                restarted = factory.command_restart_resume_category_images(restart_args)

            self.assertEqual(first, 2, output.getvalue())
            self.assertEqual(failed_session["status"], "launch_failed")
            self.assertIsNone(failed_session["pid"])
            self.assertEqual(restarted, 0, output.getvalue())
            self.assertEqual(popen.call_count, 2)
            self.assertEqual(authorization_path.read_bytes(), authorization_before)
            session = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(session["status"], "starting")
            self.assertEqual(session["pid"], 8765)
            self.assertEqual(session["previous_launcher_pid"], 0)
            self.assertEqual(session["restart_count"], 1)

    def test_serial_launch_failed_session_reuses_same_zero_request_authorization(self) -> None:
        self._assert_launch_failed_restart(1)

    def test_fixed_ten_launch_failed_session_reuses_same_zero_request_authorization(self) -> None:
        self._assert_launch_failed_restart(10)

    def test_launch_failed_restart_rejects_pid_lock_and_failure_evidence_tamper(self) -> None:
        plan = factory._validated_category_resume_plan(fixed_ten_resume_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(
                Path(temporary), plan, api_key_slots=list(range(1, 11))
            )
            event_path = context["production_dir"] / "events_truck-job.jsonl"
            event_bytes = b'{"status":"generated","request_number":2}\n'
            event_path.write_bytes(event_bytes)
            plan["events_sha256"] = hashlib.sha256(event_bytes).hexdigest()
            plan["event_tail_sha256"] = hashlib.sha256(
                event_bytes.strip()
            ).hexdigest()
            config = {
                "provider": "relay",
                "base_url": "https://relay.example",
                "model": "gpt-image-1",
                "quality": "medium",
                "api_size": "1024x1536",
            }

            with (
                mock.patch.object(
                    factory, "_category_image_resume_context", return_value=context
                ),
                mock.patch.object(factory, "_category_effective_config", return_value=config),
                mock.patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                mock.patch.object(
                    factory, "_independent_python_environment", side_effect=lambda env: env
                ),
                mock.patch.object(
                    factory, "_independent_python_executable", return_value="python"
                ),
                mock.patch.object(
                    factory.subprocess, "Popen", side_effect=OSError("launcher unavailable")
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    factory.command_resume_category_images(
                        resume_command_args(max_workers=1)
                    ),
                    2,
                )

            session_path = next(
                (context["production_dir"] / "resume_sessions").glob("*.json")
            )
            original_session = session_path.read_bytes()
            mutations = {
                "pid": lambda: session_path.write_text(
                    json.dumps(
                        {
                            **json.loads(original_session.decode("utf-8")),
                            "pid": 9876,
                        }
                    ),
                    encoding="utf-8",
                ),
                "last_error": lambda: session_path.write_text(
                    json.dumps(
                        {
                            **json.loads(original_session.decode("utf-8")),
                            "last_error": "forged",
                        }
                    ),
                    encoding="utf-8",
                ),
                "lock": lambda: (context["production_dir"] / "generation.lock").write_text(
                    json.dumps({"job_id": "truck-job", "pid": 0}),
                    encoding="utf-8",
                ),
            }
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    session_path.write_bytes(original_session)
                    lock_path = context["production_dir"] / "generation.lock"
                    if lock_path.exists():
                        lock_path.unlink()
                    mutate()
                    with self.assertRaises(RuntimeError):
                        factory._validate_zero_request_resume_relaunch(
                            context, "a" * 64
                        )

    def test_legacy_parallel_authorization_compatibility_is_exactly_scoped(self) -> None:
        no_balance_plan = {
            "balance_recoverable_target_ids": [],
            "balance_failure_request_count": 0,
            "additional_recovery_request_budget": 0,
        }
        legacy = {"max_workers": 4}

        self.assertTrue(
            factory._is_legacy_category_resume_parallel_authorization(
                legacy, no_balance_plan
            )
        )
        for name, authorization, plan in (
            ("serial", {"max_workers": 1}, no_balance_plan),
            ("fixed_ten", {"max_workers": 10}, no_balance_plan),
            (
                "policy_present",
                {
                    "max_workers": 4,
                    "resume_policy": "probe_then_2_then_4_policy_circuit_v1",
                },
                no_balance_plan,
            ),
            (
                "partial_balance_binding",
                {
                    "max_workers": 4,
                    "approved_balance_recoverable_count": 0,
                },
                no_balance_plan,
            ),
            (
                "balance_plan",
                legacy,
                {
                    "balance_recoverable_target_ids": ["target"],
                    "balance_failure_request_count": 1,
                    "additional_recovery_request_budget": 0,
                },
            ),
        ):
            with self.subTest(case=name):
                self.assertFalse(
                    factory._is_legacy_category_resume_parallel_authorization(
                        authorization, plan
                    )
                )

    def test_zero_request_preflight_accepts_only_exact_legacy_four_way_schema(self) -> None:
        plan = factory._validated_category_resume_plan(no_balance_resume_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(Path(temporary), plan)
            event_path = context["production_dir"] / "events_truck-job.jsonl"
            event_bytes = b'{"status":"generated","request_number":1}\n'
            event_path.write_bytes(event_bytes)
            plan["events_sha256"] = hashlib.sha256(event_bytes).hexdigest()
            plan["event_tail_sha256"] = hashlib.sha256(
                event_bytes.strip()
            ).hexdigest()
            config = {
                "provider": "relay",
                "base_url": "https://relay.example",
                "model": "gpt-image-1",
                "quality": "medium",
                "api_size": "1024x1536",
            }

            with (
                mock.patch.object(
                    factory, "_category_image_resume_context", return_value=context
                ),
                mock.patch.object(
                    factory, "_category_effective_config", return_value=config
                ),
                mock.patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                mock.patch.object(
                    factory,
                    "_independent_python_environment",
                    side_effect=lambda env: env,
                ),
                mock.patch.object(
                    factory, "_independent_python_executable", return_value="python"
                ),
                mock.patch.object(
                    factory.subprocess,
                    "Popen",
                    side_effect=OSError("launcher unavailable"),
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    factory.command_resume_category_images(
                        resume_command_args(max_workers=1)
                    ),
                    2,
                )

            authorization_path = next(
                (context["production_dir"] / "resume_authorizations").glob("*.json")
            )
            authorization = json.loads(
                authorization_path.read_text(encoding="utf-8")
            )
            authorization["max_workers"] = 4
            authorization.pop("resume_policy")
            for key in factory.CATEGORY_RESUME_BALANCE_AUTHORIZATION_FIELDS:
                authorization.pop(key)
            authorization_path.write_text(
                json.dumps(authorization, ensure_ascii=False), encoding="utf-8"
            )

            relaunch = factory._validate_zero_request_resume_relaunch(
                context, "a" * 64
            )
            self.assertEqual(relaunch["authorization"]["max_workers"], 4)

            authorization["max_workers"] = 1
            authorization["resume_policy"] = factory.CATEGORY_RESUME_SERIAL_POLICY
            authorization_path.write_text(
                json.dumps(authorization, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "冻结计划一致"):
                factory._validate_zero_request_resume_relaunch(
                    context, "a" * 64
                )

    def test_resume_plan_validator_keeps_balance_failures_recoverable(self) -> None:
        plan = factory._validated_category_resume_plan(balance_resume_plan())

        self.assertEqual(
            plan["balance_recoverable_target_ids"],
            ["truck_rescue:v3:g0102:u03"],
        )
        self.assertEqual(
            plan["resumable_target_ids"],
            [
                "truck_rescue:v3:g0102:u03",
                "truck_rescue:v3:g0125:u05",
            ],
        )
        self.assertEqual(plan["remaining_max_requests"], 4)
        self.assertEqual(plan["cumulative_max_requests"], 6)

    def test_resume_plan_validator_rejects_unbound_balance_recovery(self) -> None:
        plan = balance_resume_plan()
        plan["resumable_ids"] = ["truck_rescue:v3:g0125:u05"]

        with self.assertRaisesRegex(RuntimeError, "余额可恢复"):
            factory._validated_category_resume_plan(plan)

    def test_resume_plan_validator_requires_historical_balance_request(self) -> None:
        plan = balance_resume_plan()
        balance = plan["balance_recoverable_ids"][0]
        plan["attempts_used"][balance] = 0
        plan["requests_used"] = 1
        plan["cumulative_max_requests"] = 5

        with self.assertRaisesRegex(RuntimeError, "缺少历史请求证据"):
            factory._validated_category_resume_plan(plan)

    def test_resume_plan_validator_allows_only_credited_budget_extension(self) -> None:
        plan = balance_resume_plan()
        plan["budget"] = 5
        plan["balance_failure_request_count"] = 1

        validated = factory._validated_category_resume_plan(plan)
        self.assertEqual(validated["additional_recovery_request_budget"], 1)

        plan["budget"] = 4
        with self.assertRaisesRegex(RuntimeError, "余额失败请求抵扣"):
            factory._validated_category_resume_plan(plan)

    def test_read_only_plan_prints_balance_class_and_new_exact_authorization(self) -> None:
        plan = factory._validated_category_resume_plan(balance_resume_plan())
        context = {
            "category_id": "truck_rescue",
            "job_id": "truck-job",
            "license_id": "truck-license",
            "batch_dir": Path("batch_v3_active"),
            "resume_plan": plan,
        }
        output = io.StringIO()
        args = SimpleNamespace(
            category="truck_rescue", job_id="truck-job", batch_dir=None
        )

        with (
            mock.patch.object(
                factory, "_category_image_resume_context", return_value=context
            ),
            contextlib.redirect_stdout(output),
        ):
            result = factory.command_category_image_resume_plan(args)

        rendered = output.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("余额不足可恢复 1", rendered)
        self.assertIn("续跑最多 API 请求：4 次", rendered)
        self.assertIn("累计最多 API 请求：6 / 6 次", rendered)
        self.assertIn("充值后启动仍必须使用本次新 resume_plan_sha256", rendered)
        self.assertIn("未写文件、未创建许可证、未启动进程、未调用 API", rendered)

    def test_read_only_plan_can_show_explicit_fixed_ten_without_clients_or_writes(self) -> None:
        plan = factory._validated_category_resume_plan(fixed_ten_resume_plan())
        context = {
            "category_id": "truck_rescue",
            "job_id": "truck-job",
            "license_id": "truck-license",
            "batch_dir": Path("batch_v3_active"),
            "license": {"api_key_slots": list(range(1, 11))},
            "resume_plan": plan,
        }
        output = io.StringIO()
        args = SimpleNamespace(
            category="truck_rescue",
            job_id="truck-job",
            batch_dir=None,
            max_workers=10,
        )

        with (
            mock.patch.object(
                factory, "_category_image_resume_context", return_value=context
            ),
            mock.patch.object(
                factory.category_image_production, "openai_clients_by_slot"
            ) as open_clients,
            contextlib.redirect_stdout(output),
        ):
            result = factory.command_category_image_resume_plan(args)

        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("单请求探针成功后固定10路", output.getvalue())
        self.assertIn("--max-workers 10", output.getvalue())
        self.assertIn("未写文件、未创建许可证、未启动进程、未调用 API", output.getvalue())
        open_clients.assert_not_called()

    def test_resume_parser_rejects_unsupported_concurrency(self) -> None:
        parser = factory.build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "resume-category-images",
                    "--category",
                    "truck_rescue",
                    "--job-id",
                    "truck-job",
                    "--resume-plan-sha256",
                    "a" * 64,
                    "--max-workers",
                    "4",
                ]
            )

    def test_fixed_ten_resume_binds_policy_and_verified_slots(self) -> None:
        plan = factory._validated_category_resume_plan(fixed_ten_resume_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(
                Path(temporary), plan, api_key_slots=list(range(1, 11))
            )
            output = io.StringIO()
            process = SimpleNamespace(pid=4321)
            config = {
                "provider": "relay",
                "base_url": "https://relay.example",
                "model": "gpt-image-1",
                "quality": "medium",
                "api_size": "1024x1536",
            }
            clients = [(slot, object()) for slot in range(1, 11)]

            with (
                mock.patch.object(
                    factory, "_category_image_resume_context", return_value=context
                ),
                mock.patch.object(factory, "_category_effective_config", return_value=config),
                mock.patch.object(
                    factory.category_image_production,
                    "openai_clients_by_slot",
                    return_value=clients,
                ) as open_clients,
                mock.patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                mock.patch.object(
                    factory, "_independent_python_environment", side_effect=lambda env: env
                ),
                mock.patch.object(
                    factory, "_independent_python_executable", return_value="python"
                ),
                mock.patch.object(factory.subprocess, "Popen", return_value=process),
                contextlib.redirect_stdout(output),
            ):
                result = factory.command_resume_category_images(
                    resume_command_args(max_workers=10)
                )

            self.assertEqual(result, 0, output.getvalue())
            authorization_id = factory._category_resume_authorization_id(
                "truck-job", "a" * 64
            )
            authorization_path = (
                context["production_dir"]
                / "resume_authorizations"
                / f"{authorization_id}.json"
            )
            authorization = json.loads(
                authorization_path.read_text(encoding="utf-8")
            )
            self.assertEqual(authorization["max_workers"], 10)
            self.assertEqual(
                authorization["resume_policy"],
                factory.CATEGORY_RESUME_FIXED_TEN_POLICY,
            )
            self.assertEqual(authorization["api_key_slots"], list(range(1, 11)))
            open_clients.assert_called_once_with(config, list(range(1, 11)))
            self.assertIn("单请求探针成功后固定10路", output.getvalue())

    def test_fixed_ten_resume_fails_closed_when_frozen_slots_are_insufficient(self) -> None:
        plan = factory._validated_category_resume_plan(fixed_ten_resume_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(
                Path(temporary), plan, api_key_slots=list(range(1, 10))
            )
            process = mock.Mock()
            open_clients = mock.Mock()
            output = io.StringIO()
            config = {
                "provider": "relay",
                "base_url": "https://relay.example",
                "model": "gpt-image-1",
                "quality": "medium",
                "api_size": "1024x1536",
            }

            with (
                mock.patch.object(
                    factory, "_category_image_resume_context", return_value=context
                ),
                mock.patch.object(factory, "_category_effective_config", return_value=config),
                mock.patch.object(
                    factory.category_image_production,
                    "openai_clients_by_slot",
                    open_clients,
                ),
                mock.patch.object(factory.subprocess, "Popen", process),
                contextlib.redirect_stdout(output),
            ):
                result = factory.command_resume_category_images(
                    resume_command_args(max_workers=10)
                )

            self.assertEqual(result, 2)
            self.assertIn("至少10个 API Key 槽位", output.getvalue())
            self.assertFalse((context["production_dir"] / "resume_authorizations").exists())
            open_clients.assert_not_called()
            process.assert_not_called()

    def test_existing_authorization_cannot_be_hot_switched_to_fixed_ten(self) -> None:
        plan = factory._validated_category_resume_plan(fixed_ten_resume_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(
                Path(temporary), plan, api_key_slots=list(range(1, 11))
            )
            authorization_id = factory._category_resume_authorization_id(
                "truck-job", "a" * 64
            )
            authorization_path = (
                context["production_dir"]
                / "resume_authorizations"
                / f"{authorization_id}.json"
            )
            authorization_path.parent.mkdir(parents=True)
            existing = {
                "authorization_id": authorization_id,
                "resume_plan_sha256": "a" * 64,
                "status": "consumed",
                "max_workers": 1,
                "resume_policy": factory.CATEGORY_RESUME_SERIAL_POLICY,
            }
            authorization_path.write_text(
                json.dumps(existing, ensure_ascii=False), encoding="utf-8"
            )
            before = authorization_path.read_bytes()
            output = io.StringIO()

            with (
                mock.patch.object(
                    factory, "_category_image_resume_context", return_value=context
                ),
                mock.patch.object(factory, "_category_effective_config") as config,
                mock.patch.object(
                    factory.category_image_production, "openai_clients_by_slot"
                ) as open_clients,
                mock.patch.object(factory.subprocess, "Popen") as popen,
                contextlib.redirect_stdout(output),
            ):
                result = factory.command_resume_category_images(
                    resume_command_args(max_workers=10)
                )

            self.assertEqual(result, 2)
            self.assertIn("授权证据已存在", output.getvalue())
            self.assertEqual(authorization_path.read_bytes(), before)
            config.assert_not_called()
            open_clients.assert_not_called()
            popen.assert_not_called()

    def test_new_resume_authorization_binds_balance_recoverable_set(self) -> None:
        plan = factory._validated_category_resume_plan(balance_resume_plan())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = root / "batch_v3_active"
            production = batch / "production"
            job_path = production / "jobs" / "truck-job.json"
            license_path = production / "licenses" / "truck-license.json"
            job_path.parent.mkdir(parents=True)
            license_path.parent.mkdir(parents=True)
            job_path.write_text(
                json.dumps({"job_id": "truck-job", "requests_used": 2}),
                encoding="utf-8",
            )
            license_data = {
                "license_id": "truck-license",
                "plan_sha256": "f" * 64,
                "approved_request_budget": 6,
                "requests_used": 2,
                "max_attempts": 2,
                "retry_policy": "classified_once_v1",
                "provider": "relay",
                "base_url": "https://relay.example",
                "model": "gpt-image-1",
                "quality": "medium",
                "size": "1024x1536",
                "third_party_confirmed": True,
            }
            license_path.write_text(
                json.dumps(license_data), encoding="utf-8"
            )
            context = {
                "category_id": "truck_rescue",
                "job_id": "truck-job",
                "license_id": "truck-license",
                "batch_dir": batch,
                "production_dir": production,
                "job_path": job_path,
                "job": {"job_id": "truck-job", "requests_used": 2},
                "license_path": license_path,
                "license": license_data,
                "resume_plan": plan,
            }
            args = SimpleNamespace(
                category="truck_rescue",
                job_id="truck-job",
                batch_dir=None,
                resume_plan_sha256="a" * 64,
                confirm_resume=True,
                confirm_paid=True,
                confirm_third_party=True,
                archive_stale_consumed_session=False,
            )
            process = SimpleNamespace(pid=4321)
            output = io.StringIO()
            config = {
                "provider": "relay",
                "base_url": "https://relay.example",
                "model": "gpt-image-1",
                "quality": "medium",
                "api_size": "1024x1536",
            }

            with (
                mock.patch.object(
                    factory, "_category_image_resume_context", return_value=context
                ),
                mock.patch.object(factory, "_category_effective_config", return_value=config),
                mock.patch.object(
                    factory,
                    "_category_proxy_environment",
                    return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:test"},
                ),
                mock.patch.object(
                    factory, "_independent_python_environment", side_effect=lambda env: env
                ),
                mock.patch.object(
                    factory, "_independent_python_executable", return_value="python"
                ),
                mock.patch.object(factory.subprocess, "Popen", return_value=process),
                contextlib.redirect_stdout(output),
            ):
                result = factory.command_resume_category_images(args)

            self.assertEqual(result, 0, output.getvalue())
            authorization_id = factory._category_resume_authorization_id(
                "truck-job", "a" * 64
            )
            authorization_path = (
                production
                / "resume_authorizations"
                / f"{authorization_id}.json"
            )
            authorization = json.loads(
                authorization_path.read_text(encoding="utf-8")
            )
            balance_ids = plan["balance_recoverable_target_ids"]
            self.assertEqual(authorization["approved_balance_recoverable_count"], 1)
            self.assertEqual(
                authorization["approved_balance_recoverable_ids_sha256"],
                factory._json_sha256(balance_ids),
            )
            self.assertEqual(authorization["approved_remaining_request_budget"], 4)
            self.assertEqual(authorization["approved_cumulative_request_budget"], 6)
            self.assertEqual(
                authorization["approved_balance_failure_request_count"], 1
            )
            self.assertEqual(
                authorization["approved_additional_recovery_request_budget"], 0
            )
            self.assertIn("余额不足可恢复目标：1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
