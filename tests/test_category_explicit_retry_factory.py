from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import factory
from tests.test_balance_recovery_factory import balance_resume_plan, resume_command_args, resume_command_context


def retry_plan():
    plan = balance_resume_plan()
    ids = [*plan["balance_recoverable_ids"], *plan["unattempted_ids"]]
    plan.update(
        balance_recoverable_ids=[], unattempted_ids=[], explicit_retry_ids=ids,
        requests_used=3, remaining_max_requests=2, cumulative_max_requests=5,
        balance_failure_request_count=0,
    )
    for target in ids:
        plan["attempts_used"][target] = 1
        plan["attempts_remaining"][target] = 1
    plan["counts"].update(balance_recoverable=0, unattempted=0, explicit_retry=2)
    plan["explicit_retry"] = {
        "max_workers": 1, "stop_on_any_failure": True, "allow_key_failover": False,
        "retry_prompt_variant": "original", "prior_cumulative_request_cap": 6,
        "targets": [{"generation_target_id": target, "api_key_slot": slot}
                    for target, slot in zip(ids, [7, 9])],
    }
    plan["generation_migration"] = {
        "new_generation": {"model": "gpt-image-2-4k", "quality": "medium", "api_size": "2560x3840"},
        "prior_cumulative_request_cap": 6,
    }
    return plan


class ExplicitRetryFactoryTests(unittest.TestCase):
    def args(self):
        args = resume_command_args()
        args.explicit_retry_target_id = retry_plan()["explicit_retry_ids"]
        args.previous_authorization_id = "resume-previous"
        return args

    def test_explicit_selection_routes_without_migration_or_key_override(self):
        args = self.args()
        with mock.patch.object(factory, "_category_image_resume_context", return_value={}) as context:
            factory._category_resume_context_for_args(args)
        self.assertEqual(context.call_args.kwargs, {
            "explicit_retry_target_ids": args.explicit_retry_target_id,
            "previous_authorization_id": "resume-previous",
        })

    def test_conflicting_options_rejected_before_context(self):
        for key, value in [
            ("max_workers", 10), ("amend_concurrency", True), ("api_key_slot", [8]),
            ("migrate_model", "other"), ("credential_epoch", "new"),
            ("rotate_key_slot", [7]), ("accepted_source_width_tolerance", 16),
            ("archive_stale_consumed_session", True), ("previous_authorization_id", None),
        ]:
            with self.subTest(key=key):
                args = self.args()
                setattr(args, key, value)
                with mock.patch.object(factory, "_category_image_resume_context") as context:
                    with self.assertRaises(RuntimeError):
                        factory._category_resume_context_for_args(args)
                    context.assert_not_called()

    def test_explicit_partition_preserves_used_and_allows_only_once(self):
        checked = factory._validated_category_resume_plan(retry_plan())
        self.assertEqual(checked["requests_used"], 3)
        self.assertEqual(checked["remaining_max_requests"], 2)
        self.assertEqual(checked["explicit_retry_target_ids"], checked["resumable_target_ids"])
        for change in ["attempt", "cap", "stop", "partition", "extra"]:
            bad = retry_plan()
            target = bad["explicit_retry_ids"][0]
            if change == "attempt":
                bad["attempts_remaining"][target] = 2
            elif change == "cap":
                bad["explicit_retry"]["prior_cumulative_request_cap"] = 4
            elif change == "stop":
                bad["explicit_retry"]["stop_on_any_failure"] = False
            elif change == "partition":
                bad["unknown_ids"] = [target]
            else:
                bad["remaining_max_requests"] += 1
                bad["cumulative_max_requests"] += 1
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                factory._validated_category_resume_plan(bad)

    def test_network_is_pinned_without_fallback(self):
        config = {"base_url": "https://relay.example/v1"}
        job = {"network_mode": "proxy:http://127.0.0.1:7897"}
        with mock.patch.object(factory, "_category_endpoint_reachable", return_value=True) as probe:
            env = factory._category_explicit_retry_environment(config, job)
        probe.assert_called_once_with("https://relay.example/v1/models", "http://127.0.0.1:7897")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7897")
        with mock.patch.object(factory, "_category_endpoint_reachable", return_value=False) as probe:
            with self.assertRaises(RuntimeError):
                factory._category_explicit_retry_environment(config, job)
        self.assertEqual(probe.call_count, 1)

    def test_authorization_preserves_original_license_and_binds_two_original_slots(self):
        plan = factory._validated_category_resume_plan(retry_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(Path(temporary), plan, api_key_slots=[1, 2])
            context["previous_resume_session_sha256"] = "7" * 64
            before = context["license_path"].read_bytes()
            args = self.args()
            config = {"provider": "relay", "base_url": "https://relay.example", "model": "gpt-image-1", "quality": "medium", "api_size": "1024x1536"}
            output = io.StringIO()
            with (
                mock.patch.object(factory, "_category_resume_context_for_args", return_value=context),
                mock.patch.object(factory, "_category_effective_config", return_value=config),
                mock.patch.object(factory.category_image_production, "openai_clients_by_slot", return_value=[(7, object()), (9, object())]) as clients,
                mock.patch.object(factory, "_category_explicit_retry_environment", return_value={"PIPE_CATEGORY_NETWORK_MODE": "proxy:http://127.0.0.1:7897"}),
                mock.patch.object(factory, "_independent_python_environment", side_effect=lambda env: env),
                mock.patch.object(factory, "_independent_python_executable", return_value="python"),
                mock.patch.object(factory.subprocess, "Popen", return_value=SimpleNamespace(pid=4321)),
                contextlib.redirect_stdout(output),
            ):
                result = factory.command_resume_category_images(args)
            self.assertEqual(result, 0, output.getvalue())
            self.assertEqual(clients.call_args.args[1], [7, 9])
            self.assertEqual(context["license_path"].read_bytes(), before)
            auth_id = factory._category_resume_authorization_id("truck-job", plan["resume_plan_sha256"])
            auth = json.loads((context["production_dir"] / "resume_authorizations" / f"{auth_id}.json").read_text())
            self.assertTrue(auth["explicit_retry_confirmed"])
            self.assertEqual(auth["api_key_slots"], [7, 9])
            self.assertEqual(auth["max_workers"], 1)
            self.assertEqual(auth["approved_remaining_request_budget"], 2)
            self.assertEqual(auth["previous_resume_session_sha256"], "7" * 64)
            self.assertEqual(auth["generation_migration"], plan["generation_migration"])
            self.assertEqual(config["model"], "gpt-image-1")

    def test_changed_evidence_creates_no_authorization(self):
        plan = factory._validated_category_resume_plan(retry_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(Path(temporary), plan, api_key_slots=[1, 2])
            context["previous_resume_session_sha256"] = "7" * 64
            changed = copy.deepcopy(context)
            changed["previous_resume_session_sha256"] = "8" * 64
            config = {"provider": "relay", "base_url": "https://relay.example", "model": "gpt-image-1", "quality": "medium", "api_size": "1024x1536"}
            with (
                mock.patch.object(factory, "_category_resume_context_for_args", side_effect=[context, changed]),
                mock.patch.object(factory, "_category_effective_config", return_value=config),
                mock.patch.object(factory.category_image_production, "openai_clients_by_slot", return_value=[(7, object()), (9, object())]),
                mock.patch.object(factory, "_category_explicit_retry_environment", return_value={}),
                mock.patch.object(factory.subprocess, "Popen") as start,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(factory.command_resume_category_images(self.args()), 2)
            start.assert_not_called()
            self.assertFalse((context["production_dir"] / "resume_authorizations").exists())


if __name__ == "__main__":
    unittest.main()
