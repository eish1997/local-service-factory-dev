from __future__ import annotations

from argparse import Namespace
from contextlib import ExitStack, contextmanager, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import factory
from tests import test_pipe_unclogging_scoped_production as fixtures
from tools import category_4k_raw
from tools import category_generation_profile as profiles
from tools import category_image_production as production


BASE = {"provider": "relay", "base_url": "https://tinysnow.one/v1",
        "model": "gpt-image-2.5-flare", "quality": "medium", "api_size": "1024x1536"}
PROFILE_ID = profiles.TINYSNOW_4K_DUAL_SOURCE


@contextmanager
def truck_fixture(group_index=1):
    helper = fixtures.PipeUncloggingScopedProductionTests()
    with tempfile.TemporaryDirectory(prefix="new-profile-") as folder, ExitStack() as stack:
        root = Path(folder)
        for name, value in (("ROOT", root), ("CATEGORY_BATCH_ROOT", root),
                            ("ACTIVE_JOB_PATH", None), ("ACTIVE_LICENSE_PATH", None),
                            ("ACTIVE_LOCK_PATH", None)):
            stack.enter_context(patch.object(production, name, value))
        batch = helper.make_truck_v3_batch(root)
        if group_index != 1:
            path = batch / "prompts.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            structure = production.load_category_config("truck_rescue")["image_group_structure"]
            from tools.truck_rescue_signage import signage_variant
            signage = signage_variant(group_index, Path(__file__).resolve().parents[1] / "projects" / "truck_rescue" / "cover_scene_library.json")
            height = structure["height_profiles"][(group_index - 1) % len(structure["height_profiles"])]
            layout = structure["triptych_layouts"][((group_index - 1) // len(structure["height_profiles"])) % len(structure["triptych_layouts"])]
            for row in rows:
                row["group_index"] = group_index
                row["height_profile_id"] = height["id"]
                row["final_size"] = row["expected_size"] = f"{height['width']}x{height['height']}"
                row["triptych_layout_id"] = layout["id"]
                if row["triptych_panel_index"] is not None:
                    row["triptych_panel_box"] = layout["panels"][row["triptych_panel_index"] - 1]
                row["generation_id"] = row["generation_id"].replace("g0001", f"g{group_index:04d}")
                row["raw_target"] = str(Path(row["raw_target"]).parent.parent / f"group_{group_index:04d}" / Path(row["raw_target"]).name)
                if row["generation_kind"] == "cover":
                    row["cover_variant"].update(signage)
                    if group_index >= 374:
                        import generate_truck_rescue_groups as groups
                        variant = groups._cover_variant(groups._cover_library(), group_index)
                        row["cover_variant"] = variant
                        row["scene"] = deepcopy(variant)
                        row["positive_prompt"] = groups._cover_positive_prompt(variant)
                        row["prompt"] = row["positive_prompt"] + "严格排除：" + row["negative_prompt"]
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            library = root / "projects" / "truck_rescue" / "cover_scene_library.json"
            library.parent.mkdir(parents=True)
            shutil.copyfile(Path(__file__).resolve().parents[1] / "projects" / "truck_rescue" / library.name, library)
        config = profiles.select_profile(BASE, "truck_rescue", PROFILE_ID)
        run_plan = production.plan("truck_rescue", batch, group_index, 1, fixtures.PHONE, config,
                                   scope="all", output_root=root / "output" / "truck_rescue")
        yield SimpleNamespace(root=root, batch=batch, helper=helper, config=config, plan=run_plan)


def license_fixture(item):
    license_id = "new-profile-fixture"
    manifest, overlay = production.write_production_files(item.plan, fixtures.PHONE, license_id)
    license_path = production.license_path("truck_rescue", item.batch, item.plan["group_start"], 1, license_id)
    data = item.helper.license_payload(item.plan, license_id, slots=[1, 2], max_workers=2, max_attempts=2)
    data.update({key: item.config[key] for key in ("provider", "base_url", "model", "quality")})
    data.update(size=item.config["api_size"], generation_profile=deepcopy(item.config["generation_profile"]),
                concurrency_policy=production.ADAPTIVE_CONCURRENCY_POLICY,
                production_manifest=str(manifest), overlay_plan=str(overlay))
    production.write_new_license(license_path, data)
    job_path = production.jobs_dir(item.batch) / "new-profile-job.json"
    production.atomic_json(job_path, {"job_id": "new-profile-job", "license_id": license_id,
                                     "model": item.config["model"], "quality": item.config["quality"],
                                     "size": item.config["api_size"],
                                     "generation_profile": deepcopy(data["generation_profile"])})
    return SimpleNamespace(path=license_path, data=data, job=job_path, manifest=manifest,
                           args=Namespace(category="truck_rescue", batch_dir=str(item.batch),
                                          group_start=item.plan["group_start"], group_count=1, license=str(license_path),
                                          job_file=str(job_path), scope="all", output_root=item.plan["output_root"],
                                          license_id=license_id, max_workers=2))


class CategoryGenerationProfileTests(unittest.TestCase):
    def test_profile_is_explicit_exact_and_does_not_change_global_config(self):
        before = deepcopy(BASE)
        config = profiles.select_profile(BASE, "truck_rescue", PROFILE_ID)
        self.assertEqual(BASE, before)
        self.assertEqual(config["api_size"], "2560x3840")
        self.assertEqual(config["generation_profile"]["accepted_source_sizes"], ["2336x3520", "2352x3520"])
        self.assertEqual(profiles.select_profile(BASE, "road_rescue", None), BASE)
        for category, base, profile_id in (("pipe_unclogging", BASE, PROFILE_ID),
                                           ("truck_rescue", {**BASE, "base_url": "https://other.invalid/v1"}, PROFILE_ID),
                                           ("truck_rescue", BASE, "unknown"),
                                           ("truck_rescue", config, None)):
            with self.subTest(category=category, profile_id=profile_id), self.assertRaises(ValueError):
                profiles.select_profile(base, category, profile_id)

    def test_road_profile_is_category_bound_and_keeps_truck_contract_unchanged(self):
        before = deepcopy(BASE)
        truck = profiles.select_profile(BASE, "truck_rescue", PROFILE_ID)
        road = profiles.select_profile(BASE, "road_rescue", PROFILE_ID)
        self.assertEqual(BASE, before)
        self.assertEqual(truck["generation_profile"], profiles._PROFILE)
        self.assertEqual(road["generation_profile"], {**truck["generation_profile"], "category_id": "road_rescue"})
        self.assertEqual(profiles.config_profile(road, "road_rescue"), road["generation_profile"])
        for config, category in ((road, "truck_rescue"), (truck, "road_rescue"), (road, "pipe_unclogging")):
            with self.subTest(category=category), self.assertRaises(ValueError):
                profiles.config_profile(config, category)

    def test_road_license_restore_preserves_explicit_model_and_rejects_cross_category(self):
        config = profiles.select_profile(BASE, "road_rescue", PROFILE_ID)
        license_data = {key: config[key] for key in ("provider", "base_url", "model", "quality", "generation_profile")}
        license_data.update(category_id="road_rescue", size="2560x3840")
        self.assertEqual(profiles.from_license(BASE, "road_rescue", license_data), config)
        for data in ({**license_data, "category_id": "truck_rescue"},
                     {**license_data, "generation_profile": profiles.select_profile(BASE, "truck_rescue", PROFILE_ID)["generation_profile"]},
                     {**license_data, "size": "1024x1536"}):
            with self.assertRaises(ValueError):
                profiles.from_license(BASE, "road_rescue", data)

    def test_road_plan_binds_4k_without_changing_delivery_or_business_prompt(self):
        from tests.test_category_single_target_probe import BATCH, OUTPUT, PHONE
        config = profiles.select_profile(BASE, "road_rescue", PROFILE_ID)
        with (patch.object(production, "reusable_target", return_value=False),
              patch.object(production, "valid_png", return_value=False),
              patch.object(production, "target_review_status", return_value=None)):
            road = production.plan("road_rescue", BATCH, 316, 1, PHONE, config, scope="all", output_root=OUTPUT)
            legacy = production.plan("road_rescue", BATCH, 316, 1, PHONE, BASE, scope="all", output_root=OUTPUT)
        self.assertEqual(road["pending_api_requests"], 7)
        self.assertEqual(road["delivery_count"], 5)
        self.assertEqual(road["expected_size"], [1024, 1536])
        self.assertNotEqual(road["plan_sha256"], legacy["plan_sha256"])
        self.assertEqual(road["generation_profile"]["category_id"], "road_rescue")
        for entry, old in zip(road["manifest_entries"], legacy["manifest_entries"]):
            self.assertEqual(entry["size"], "2560x3840")
            self.assertEqual(entry["raw_api_size"], "1024x1536")
            self.assertEqual(entry["generation_profile"], road["generation_profile"])
            self.assertEqual(entry["final_size"], old["final_size"])
            self.assertEqual(entry["effective_prompt"], old["effective_prompt"])

    def test_partial_or_tampered_profiles_fail_closed(self):
        config = profiles.select_profile(BASE, "truck_rescue", PROFILE_ID)
        for key, value in (("api_size", "1024x1536"), ("accepted_source_width_tolerance", 17),
                           ("accepted_source_sizes", ["2344x3520"]), ("schema_version", True),
                           ("raw_contract", "arbitrary")):
            changed = deepcopy(config)
            changed["generation_profile"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                profiles.config_profile(changed, "truck_rescue")
        with self.assertRaises(ValueError):
            profiles.config_profile({**config, "quality": "high"}, "truck_rescue")

    def test_new_profile_plan_and_frozen_records_separate_request_from_working_raw(self):
        with truck_fixture() as item:
            legacy = production.plan("truck_rescue", item.batch, 1, 1, fixtures.PHONE, BASE,
                                     scope="all", output_root=item.plan["output_root"])
            self.assertEqual(item.plan["pending_api_requests"], 7)
            self.assertEqual(item.plan["delivery_count"], 5)
            self.assertEqual(item.plan["expected_size"], [1024, 1536])
            self.assertNotEqual(legacy["plan_sha256"], item.plan["plan_sha256"])
            self.assertNotIn("generation_profile", legacy)
            lic = license_fixture(item)
            rows = production.load_frozen_manifest_runtime_records(item.batch, lic.manifest, item.plan["manifest_sha256"])
            self.assertEqual(len(rows), 7)
            for entry in item.plan["manifest_entries"]:
                self.assertEqual(entry["size"], "2560x3840")
                self.assertEqual(entry["raw_api_size"], "1024x1536")
                self.assertEqual(entry["generation_profile"], item.plan["generation_profile"])
            for row in rows:
                self.assertEqual(row["generation_profile"], item.plan["generation_profile"])
            production.validate_license(lic.path, item.plan, item.config, [1, 2], 2)
            lic.data["concurrency_policy"] = production.FIXED_TEN_CONCURRENCY_POLICY
            production.atomic_json(lic.path, lic.data)
            with self.assertRaisesRegex(RuntimeError, "adaptive"):
                production.validate_license(lic.path, item.plan, item.config, [1, 2], 2)
            lic.data["concurrency_policy"] = production.ADAPTIVE_CONCURRENCY_POLICY
            lic.data["generation_profile"]["api_size"] = "2048x3072"
            production.atomic_json(lic.path, lic.data)
            with self.assertRaises(RuntimeError):
                production.validate_license(lic.path, item.plan, item.config, [1, 2], 2)

    def test_license_restore_requires_matching_profile_and_route(self):
        with truck_fixture() as item:
            lic = license_fixture(item)
            self.assertEqual(profiles.from_license(BASE, "truck_rescue", lic.data), item.config)
            for changed in ({**lic.data, "generation_profile": None},
                            {**lic.data, "size": "1024x1536"},
                            {key: value for key, value in lic.data.items() if key != "generation_profile"}):
                with self.assertRaises(ValueError):
                    profiles.from_license(BASE, "truck_rescue", changed)
            with self.assertRaises(ValueError):
                profiles.from_license({**BASE, "base_url": "https://other.invalid/v1"}, "truck_rescue", lic.data)

    def test_factory_cli_authorization_and_start_restore_same_task_profile(self):
        with truck_fixture(374) as item, ExitStack() as stack:
            for name, value in (("_category_effective_config", BASE),
                                ("category_active_batch_dir", item.batch),
                                ("_category_confirmed_phone", fixtures.PHONE),
                                ("_category_output_root", Path(item.plan["output_root"])),
                                ("selected_key_slots", [1, 2]),
                                ("_category_proxy_environment", {"PIPE_CATEGORY_NETWORK_MODE": "fixture"})):
                stack.enter_context(patch.object(factory, name, return_value=value))
            stack.enter_context(patch.object(factory, "_category_sample_range"))
            stack.enter_context(patch.object(factory, "activate_dashboard_session"))
            stack.enter_context(patch.object(factory, "launch_dashboard_compact", return_value=False))
            launch = stack.enter_context(patch.object(factory.subprocess, "Popen", return_value=SimpleNamespace(pid=987654)))
            stack.enter_context(redirect_stdout(io.StringIO()))
            args = factory.build_parser().parse_args([
                "confirm-start-category-images", "--category", "truck_rescue", "--group-start", "374",
                "--group-count", "1", "--scope", "all", "--phone", fixtures.PHONE,
                "--generation-profile", PROFILE_ID, "--plan-sha256", item.plan["plan_sha256"],
                "--max-requests", "14", "--auto-retry-limit", "1", "--max-workers", "2",
                "--confirm-paid", "--confirm-third-party",
            ])
            self.assertEqual(factory.command_confirm_start_category_images(args), 0)
            path = production.license_path("truck_rescue", item.batch, 374, 1, args.created_license_id)
            data = production.load_json(path)
            self.assertEqual(data["generation_profile"], item.plan["generation_profile"])
            self.assertEqual(data["model"], "gpt-image-2-4k")
            self.assertEqual(data["approved_request_budget"], 14)
            launch.assert_called_once()
            jobs = list(production.jobs_dir(item.batch).glob("*.json"))
            self.assertEqual(len(jobs), 1)
            self.assertEqual(production.load_json(jobs[0])["generation_profile"], data["generation_profile"])
            # Start must reject even a nested local layout edit before spawning.
            overlay_path = Path(data["overlay_plan"])
            overlay = production.load_json(overlay_path)
            overlay["cover_styles_by_group"]["374"]["bottom_service_style"]["font_scale"] = 1.5
            production.atomic_json(overlay_path, overlay)
            launch.reset_mock()
            self.assertEqual(factory.command_start_category_images(Namespace(
                category="truck_rescue", batch_dir=None, group_start=374, group_count=1,
                scope="all", license_id=args.created_license_id,
            )), 2)
            launch.assert_not_called()

    def test_complete_typography_plan_is_hash_bound_and_tampering_rejected(self):
        with truck_fixture(374) as item:
            from tools import truck_cover_typography
            expected = json.loads(json.dumps(truck_cover_typography.cover_plan(374)))
            entry = next(row for row in item.plan["manifest_entries"] if row["generation_kind"] == "cover")
            self.assertEqual(entry["cover_typography_plan"], expected)
            self.assertEqual(item.plan["cover_styles_by_group"], {"374": expected})
            lic = license_fixture(item)
            production.validate_frozen_cover_typography(item.plan, lic.data)
            self.assertEqual(production.load_json(Path(lic.data["overlay_plan"]))["cover_styles_by_group"], {"374": expected})
            changed_plan = deepcopy(item.plan)
            changed_plan["cover_styles_by_group"]["374"]["phone_ink"][0] = 0
            with self.assertRaises(production.CategoryPromptError):
                production.validate_frozen_cover_typography(changed_plan, lic.data)
            entries = deepcopy(item.plan["manifest_entries"])
            entries[0]["cover_typography_plan"]["bottom_service_style"]["font_scale"] = 2.0
            self.assertNotEqual(production.manifest_sha256(entries), item.plan["manifest_sha256"])
            lic.manifest.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in entries), encoding="utf-8")
            with self.assertRaises(production.CategoryPromptError):
                production.validate_frozen_cover_typography(item.plan, lic.data)


class CategoryGenerationProfileWorkerTests(unittest.TestCase):
    def run_worker(self, item, lic, generator, saver, clients=None):
        with (patch.object(production.image_generate, "load_json", return_value=BASE),
              patch.object(production.image_generate, "apply_provider_config", return_value=BASE),
              patch.object(production, "openai_clients_by_slot", return_value=clients or [(1, "slot-1"), (2, "slot-2")]),
              patch.object(production, "_font", return_value=None),
              patch.object(production.image_generate, "generate_one", side_effect=generator),
              patch.object(category_4k_raw, "save_4k_raw_png", side_effect=saver),
              patch.object(production, "save_raw_png") as legacy_saver,
              patch.object(production, "_materialize_delivery"),
              patch.object(production.time, "sleep"), redirect_stdout(io.StringIO())):
            code = production.run(lic.args)
            legacy_saver.assert_not_called()
        events = production.production_dir(item.batch) / "events_new-profile-job.jsonl"
        return code, production.load_json(lic.job), [json.loads(line) for line in events.read_text().splitlines()]

    def test_worker_uses_exact_profile_adapter_and_logs_actual_parameters(self):
        with truck_fixture(374) as item:
            lic = license_fixture(item)
            calls, saves = [], []
            def generate(_client, config, _prompt):
                calls.append(deepcopy(config))
                return b"fixture"
            def save(*args, **kwargs):
                saves.append(kwargs)
                return {"source_returned_size": "2336x3520", "normalized": True}
            _, job, events = self.run_worker(item, lic, generate, save)
            self.assertEqual(len(calls), 7)
            self.assertEqual(job["requests_used"], 7)
            self.assertEqual(job["concurrency_history"][0]["phase"], "probe")
            self.assertTrue(all({key: value for key, value in config.items() if key != "_image_download_context"} == item.config for config in calls))
            for config in calls:
                context = config["_image_download_context"]
                self.assertEqual(context["job_id"], "new-profile-job")
                self.assertEqual(context["license_id"], lic.data["license_id"])
                self.assertEqual(context["original_plan_sha256"], lic.data["plan_sha256"])
                self.assertIn(context["generation_target_id"], [row["generation_target_id"] for row in item.plan["manifest_entries"]])
            self.assertTrue(all(save["accepted_source_width_tolerance"] == 16 for save in saves))
            self.assertTrue(all(save["credential_epoch"] is None for save in saves))
            for event in events:
                if event["status"] in {"request_reserved", "generated"}:
                    self.assertEqual(event["model"], "gpt-image-2-4k")
                    self.assertEqual(event["api_size"], "2560x3840")
                    self.assertEqual(event["raw_api_size"], "1024x1536")
                    self.assertEqual(event["generation_profile_id"], PROFILE_ID)

    def test_profile_or_job_tampering_fails_before_client_or_consumption(self):
        for tamper in ("profile", "job", "job_model"):
            with self.subTest(tamper=tamper), truck_fixture() as item:
                lic = license_fixture(item)
                if tamper == "profile":
                    lic.data["generation_profile"]["accepted_source_sizes"] = ["2344x3520"]
                    production.atomic_json(lic.path, lic.data)
                else:
                    job = production.load_json(lic.job)
                    if tamper == "job":
                        job.pop("generation_profile")
                    else:
                        job["model"] = "gpt-image-2.5-flare"
                    production.atomic_json(lic.job, job)
                with (patch.object(production.image_generate, "load_json", return_value=BASE),
                      patch.object(production.image_generate, "apply_provider_config", return_value=BASE),
                      patch.object(production, "openai_clients_by_slot") as clients):
                    with self.assertRaises((ValueError, RuntimeError)):
                        production.run(lic.args)
                    clients.assert_not_called()
                self.assertEqual(production.load_json(lic.path)["status"], "active")
                self.assertFalse((production.production_dir(item.batch) / "generation.lock").exists())

    def test_frozen_typography_tampering_blocks_worker_before_consumption(self):
        with truck_fixture(374) as item:
            lic = license_fixture(item)
            path = Path(lic.data["overlay_plan"])
            overlay = production.load_json(path)
            overlay["cover_styles_by_group"]["374"]["center_phone_region"][1] = 0.1
            production.atomic_json(path, overlay)
            with (patch.object(production.image_generate, "load_json", return_value=BASE),
                  patch.object(production.image_generate, "apply_provider_config", return_value=BASE),
                  patch.object(production, "openai_clients_by_slot") as clients):
                with self.assertRaises(production.CategoryPromptError):
                    production.run(lic.args)
                clients.assert_not_called()
            self.assertEqual(production.load_json(lic.path)["status"], "active")

    def test_profile_balance_failover_quarantines_only_failed_licensed_slot(self):
        with truck_fixture() as item:
            lic = license_fixture(item)
            slots = []
            def generate(client, _config, _prompt):
                slots.append(client)
                if client == "slot-1":
                    error = RuntimeError("INSUFFICIENT_BALANCE")
                    error.status_code = 403
                    raise error
                return b"fixture"
            _, job, events = self.run_worker(item, lic, generate, lambda *args, **kwargs: {})
            self.assertEqual(slots, ["slot-1"] + ["slot-2"] * 7)
            self.assertEqual(job["requests_used"], 8)
            self.assertEqual(job["quarantined_api_key_slots"], [1])
            self.assertEqual(sum(event["status"] == "request_reserved" for event in events), 8)
            self.assertEqual(production.load_json(lic.path)["requests_used"], 8)

    def test_profile_budget_exhaustion_after_balance_failovers_saves_checkpoint(self):
        with truck_fixture() as item:
            lic = license_fixture(item)
            lic.data.update(api_key_slots=[1, 2, 3], max_workers=3)
            lic.args.max_workers = 3
            production.atomic_json(lic.path, lic.data)
            calls, attempts = [], {}
            probe_prompt = production.effective_prompt(item.plan["pending_records"][0], fixtures.PHONE)
            def generate(client, _config, prompt):
                calls.append(client)
                if client != "slot-3":
                    error = RuntimeError("INSUFFICIENT_BALANCE")
                    error.status_code = 403
                    raise error
                attempts[prompt] = attempts.get(prompt, 0) + 1
                if prompt != probe_prompt and attempts[prompt] == 1:
                    error = RuntimeError("connection error")
                    error.status_code = 503
                    raise error
                return b"fixture"
            code, job, events = self.run_worker(item, lic, generate, lambda *args, **kwargs: {},
                                                clients=[(i, f"slot-{i}") for i in (1, 2, 3)])
            self.assertEqual(code, 1)
            self.assertEqual(len(calls), 14)
            self.assertEqual(job["requests_used"], 14)
            self.assertEqual(job["status"], "paused_api_errors")
            self.assertEqual(job["stop_reason"], "request_budget_exhausted")
            self.assertEqual(job["checkpoint"]["remaining_request_budget"], 0)
            self.assertEqual(len(job["checkpoint"]["unfinished_generation_target_ids"]), 1)
            self.assertEqual(job["quarantined_api_key_slots"], [1, 2])
            self.assertEqual(sum(event["status"] == "request_reserved" for event in events), 14)
            self.assertEqual(production.load_json(lic.path)["requests_used"], 14)

    def test_bad_source_probe_stops_after_one_request_without_retry(self):
        with truck_fixture() as item:
            lic = license_fixture(item)
            calls = []
            def generate(*args):
                calls.append(args)
                return b"fixture"
            def reject(*args, **kwargs):
                raise production.RawImageContractError("wrong dimensions", evidence={"source_returned_size": "2344x3520"})
            code, job, events = self.run_worker(item, lic, generate, reject)
            self.assertEqual(code, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(job["status"], "paused_probe_failed")
            self.assertEqual(job["requests_used"], 1)
            failures = [event for event in events if event["status"] == "request_failed"]
            self.assertEqual(failures[0]["error_kind"], "raw_contract_rejected")
            self.assertFalse(failures[0]["will_retry"])

    def test_bad_source_after_probe_stops_remaining_stages(self):
        with truck_fixture() as item:
            lic = license_fixture(item)
            calls, saves = [], []
            def generate(*args):
                calls.append(args)
                return b"fixture"
            def save(*args, **kwargs):
                saves.append(args)
                if len(saves) > 1:
                    raise production.RawImageContractError("wrong dimensions")
                return {}
            code, job, _ = self.run_worker(item, lic, generate, save)
            self.assertEqual(code, 1)
            self.assertLessEqual(len(calls), 3)
            self.assertEqual(job["status"], "paused_api_errors")
            self.assertEqual(job["stop_reason"], "raw_contract_rejected")
            self.assertLess(job["requests_used"], 7)
            self.assertEqual(job["checkpoint"]["remaining_request_budget"], 14 - len(calls))


if __name__ == "__main__":
    unittest.main()
