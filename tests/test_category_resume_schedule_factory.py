from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import factory
from tests.test_balance_recovery_factory import (
    fixed_ten_resume_plan, resume_command_args, resume_command_context,
)


class ScheduleAmendmentFactoryTests(unittest.TestCase):
    def amended_plan(self):
        plan = fixed_ten_resume_plan()
        plan["schedule_amendment"] = {
            "schema_version": 1,
            "kind": "category-resume-schedule-amendment",
            "api_key_slots": list(range(1, 11)),
            "original_api_key_slots": [1, 2],
            "max_workers": 10,
            "resume_policy": factory.CATEGORY_RESUME_FIXED_TEN_POLICY,
            "inherited_quarantined_api_key_slots": [2],
            "strict_original_request_budget": plan["budget"],
        }
        return plan

    def test_no_implicit_key_expansion(self):
        args = resume_command_args(max_workers=10)
        args.api_key_slot = list(range(1, 11))
        with mock.patch.object(factory, "_category_image_resume_context") as context:
            with self.assertRaisesRegex(RuntimeError, "amend-concurrency"):
                factory._category_resume_context_for_args(args)
            context.assert_not_called()

    def test_amendment_requires_ten_way_and_explicit_slots(self):
        for workers, slots in [(1, list(range(1, 11))), (10, None)]:
            args = resume_command_args(max_workers=workers)
            args.amend_concurrency = True
            args.api_key_slot = slots
            with self.assertRaises(RuntimeError):
                factory._category_resume_context_for_args(args)

    def test_explicit_amendment_passes_slots_into_readonly_context(self):
        args = resume_command_args(max_workers=10)
        args.amend_concurrency = True
        args.api_key_slot = list(range(1, 11))
        with mock.patch.object(factory, "_category_image_resume_context", return_value={}) as context:
            self.assertEqual(factory._category_resume_context_for_args(args), {})
            context.assert_called_once_with(
                args.category, args.job_id, args.batch_dir,
                schedule_amendment_slots=list(range(1, 11)),
            )

    def test_amended_global_cap_does_not_reset_target_allowances(self):
        plan = self.amended_plan()
        plan["budget"] = 21
        plan["schedule_amendment"]["strict_original_request_budget"] = 21
        plan["remaining_max_requests"] = 19
        plan["cumulative_max_requests"] = 21
        normalized = factory._validated_category_resume_plan(plan)
        self.assertEqual(sum(normalized["attempts_remaining"].values()), 20)
        self.assertEqual(normalized["remaining_max_requests"], 19)
        self.assertEqual(normalized["additional_recovery_request_budget"], 0)
        plan["remaining_max_requests"] = 20
        plan["cumulative_max_requests"] = 22
        with self.assertRaises(RuntimeError):
            factory._validated_category_resume_plan(plan)

    def test_amendment_creates_bound_sidecar_without_mutating_original_license(self):
        plan = factory._validated_category_resume_plan(self.amended_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(Path(temporary), plan, api_key_slots=[1, 2])
            before = context["license_path"].read_bytes()
            args = resume_command_args(max_workers=10)
            args.amend_concurrency = True
            args.api_key_slot = list(range(1, 11))
            config = {
                "provider": "relay", "base_url": "https://relay.example",
                "model": "gpt-image-1", "quality": "medium", "api_size": "1024x1536",
            }
            output = io.StringIO()
            with (
                mock.patch.object(factory, "_category_resume_context_for_args", return_value=context),
                mock.patch.object(factory, "_category_effective_config", return_value=config),
                mock.patch.object(factory.category_image_production, "openai_clients_by_slot",
                                  return_value=[(n, object()) for n in range(1, 11)]),
                mock.patch.object(factory, "_category_proxy_environment", return_value={}),
                mock.patch.object(factory, "_independent_python_environment", side_effect=lambda env: env),
                mock.patch.object(factory, "_independent_python_executable", return_value="python"),
                mock.patch.object(factory.subprocess, "Popen", return_value=SimpleNamespace(pid=4321)),
                contextlib.redirect_stdout(output),
            ):
                result = factory.command_resume_category_images(args)
            self.assertEqual(result, 0, output.getvalue())
            auth_id = factory._category_resume_authorization_id("truck-job", plan["resume_plan_sha256"])
            auth = json.loads((context["production_dir"] / "resume_authorizations" / f"{auth_id}.json").read_text())
            self.assertTrue(auth["schedule_amendment_confirmed"])
            self.assertEqual(auth["schedule_amendment"], plan["schedule_amendment"])
            self.assertEqual(auth["api_key_slots"], list(range(1, 11)))
            self.assertEqual(auth["approved_additional_recovery_request_budget"], 0)
            self.assertEqual(context["license_path"].read_bytes(), before)

    def test_wrong_hash_never_creates_authorization_or_starts_worker(self):
        plan = factory._validated_category_resume_plan(self.amended_plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(Path(temporary), plan, api_key_slots=[1, 2])
            args = resume_command_args(max_workers=10)
            args.resume_plan_sha256 = "9" * 64
            with (
                mock.patch.object(factory, "_category_resume_context_for_args", return_value=context),
                mock.patch.object(factory.subprocess, "Popen") as start,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(factory.command_resume_category_images(args), 2)
            start.assert_not_called()
            self.assertFalse((context["production_dir"] / "resume_authorizations").exists())


if __name__ == "__main__":
    unittest.main()
