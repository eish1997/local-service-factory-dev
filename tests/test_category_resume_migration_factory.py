from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys

import factory
from tests.test_balance_recovery_factory import resume_command_args, resume_command_context
from tests.test_category_resume_schedule_factory import ScheduleAmendmentFactoryTests


class GenerationMigrationFactoryTests(unittest.TestCase):
    def test_relay_model_check_is_non_image_zero_retry_and_does_not_edit_config(self):
        client = mock.Mock()
        client.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id="gpt-image-2-4k")])
        constructor = mock.Mock(return_value=client)
        config = {"provider": "relay", "base_url": "https://tinysnow.one/v1", "model": "gpt-image-2.5-flare"}
        with (
            mock.patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=constructor)}),
            mock.patch("importlib.util.find_spec", return_value=object()),
            mock.patch.object(factory, "effective_api_config", return_value=config),
            mock.patch.object(factory, "load_json", return_value={}),
            mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-placeholder"}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = factory.command_test_relay(SimpleNamespace(confirm_network=True, model="gpt-image-2-4k"))
        self.assertEqual(result, 0)
        constructor.assert_called_once_with(base_url=config["base_url"], max_retries=0, timeout=30)
        client.images.generate.assert_not_called()
        self.assertEqual(config["model"], "gpt-image-2.5-flare")

    def args(self):
        args = resume_command_args(max_workers=10)
        args.amend_concurrency = True
        args.api_key_slot = list(range(1, 11))
        args.migrate_model = "gpt-image-2-4k"
        args.migrate_quality = "medium"
        args.migrate_size = "2560x3840"
        args.credential_epoch = "credential-" + "a" * 32
        args.rotate_key_slot = list(range(1, 11))
        args.previous_authorization_id = "resume-" + "b" * 24
        return args

    def plan(self):
        plan = ScheduleAmendmentFactoryTests().amended_plan()
        plan["generation_migration"] = {
            "new_generation": {"model": "gpt-image-2-4k", "quality": "medium", "api_size": "2560x3840"},
            "credential_epoch": "credential-" + "a" * 32,
            "rotated_slots": list(range(1, 11)),
            "effective_quarantined_api_key_slots": [],
            "prior_cumulative_request_cap": plan["cumulative_max_requests"],
        }
        return plan

    def test_explicit_migration_passes_exact_spec(self):
        args = self.args()
        with mock.patch.object(factory, "_category_image_resume_context", return_value={}) as context:
            factory._category_resume_context_for_args(args)
        self.assertEqual(context.call_args.kwargs["generation_migration_spec"], {
            "model": args.migrate_model, "quality": args.migrate_quality, "api_size": args.migrate_size,
            "credential_epoch": args.credential_epoch, "rotated_slots": args.rotate_key_slot,
        })
        self.assertEqual(context.call_args.kwargs["previous_authorization_id"], args.previous_authorization_id)

    def test_partial_migration_never_builds_context(self):
        for name in ("migrate_model", "migrate_quality", "migrate_size", "credential_epoch", "rotate_key_slot", "previous_authorization_id", "amend_concurrency"):
            with self.subTest(name=name):
                args = self.args()
                setattr(args, name, None)
                with mock.patch.object(factory, "_category_image_resume_context") as context:
                    with self.assertRaises(RuntimeError):
                        factory._category_resume_context_for_args(args)
                    context.assert_not_called()

    def test_accepted_source_size_binds_no_new_credential_rotation(self):
        args = self.args()
        args.accepted_source_size = "2352x3520"
        args.rotate_key_slot = None
        with mock.patch.object(factory, "_category_image_resume_context", return_value={}) as context:
            factory._category_resume_context_for_args(args)
        spec = context.call_args.kwargs["generation_migration_spec"]
        self.assertEqual(spec["accepted_source_size"], "2352x3520")
        self.assertEqual(spec["rotated_slots"], [])
        self.assertEqual(spec["credential_epoch"], args.credential_epoch)

    def test_prior_cap_constrains_normalized_plan(self):
        plan = self.plan()
        plan["generation_migration"]["prior_cumulative_request_cap"] = 10
        plan["remaining_max_requests"] = 10 - plan["requests_used"]
        plan["cumulative_max_requests"] = 10
        checked = factory._validated_category_resume_plan(plan)
        self.assertEqual(checked["cumulative_max_requests"], 10)
        plan["remaining_max_requests"] += 1
        plan["cumulative_max_requests"] += 1
        with self.assertRaises(RuntimeError):
            factory._validated_category_resume_plan(plan)

    def test_width_tolerance_is_bound_without_rotating_credentials(self):
        args = self.args()
        args.accepted_source_size = "2352x3520"
        args.accepted_source_width_tolerance = 16
        args.rotate_key_slot = None
        with mock.patch.object(factory, "_category_image_resume_context", return_value={}) as context:
            factory._category_resume_context_for_args(args)
        spec = context.call_args.kwargs["generation_migration_spec"]
        self.assertEqual(spec["accepted_source_width_tolerance"], 16)
        self.assertEqual(spec["accepted_source_size"], "2352x3520")
        self.assertEqual(spec["rotated_slots"], [])

    def test_width_tolerance_without_anchor_never_builds_context(self):
        args = self.args()
        args.accepted_source_width_tolerance = 16
        with mock.patch.object(factory, "_category_image_resume_context") as context:
            with self.assertRaises(RuntimeError):
                factory._category_resume_context_for_args(args)
            context.assert_not_called()

    def test_task_sidecar_does_not_change_original_license_or_global_config(self):
        plan = factory._validated_category_resume_plan(self.plan())
        with tempfile.TemporaryDirectory() as temporary:
            context = resume_command_context(Path(temporary), plan, api_key_slots=[1, 2])
            before = context["license_path"].read_bytes()
            config = {"provider": "relay", "base_url": "https://relay.example", "model": "gpt-image-1", "quality": "medium", "api_size": "1024x1536"}
            output = io.StringIO()
            with (
                mock.patch.object(factory, "_category_resume_context_for_args", return_value=context),
                mock.patch.object(factory, "_category_effective_config", return_value=config),
                mock.patch.object(factory.category_image_production, "openai_clients_by_slot", return_value=[(n, object()) for n in range(1, 11)]) as clients,
                mock.patch.object(factory, "_category_proxy_environment", return_value={}),
                mock.patch.object(factory, "_independent_python_environment", side_effect=lambda env: env),
                mock.patch.object(factory, "_independent_python_executable", return_value="python"),
                mock.patch.object(factory.subprocess, "Popen", return_value=SimpleNamespace(pid=4321)),
                contextlib.redirect_stdout(output),
            ):
                result = factory.command_resume_category_images(self.args())
            self.assertEqual(result, 0, output.getvalue())
            self.assertEqual(clients.call_args.args[0]["model"], "gpt-image-2-4k")
            self.assertEqual(clients.call_args.args[0]["api_size"], "2560x3840")
            self.assertEqual(config["model"], "gpt-image-1")
            self.assertEqual(context["license_path"].read_bytes(), before)
            auth_id = factory._category_resume_authorization_id("truck-job", plan["resume_plan_sha256"])
            auth = json.loads((context["production_dir"] / "resume_authorizations" / f"{auth_id}.json").read_text())
            self.assertTrue(auth["generation_migration_confirmed"])
            self.assertEqual(auth["generation_migration"], plan["generation_migration"])
            self.assertEqual(auth["model"], "gpt-image-1")


if __name__ == "__main__":
    unittest.main()
