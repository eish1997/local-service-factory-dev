from __future__ import annotations

import json
import io
import os
import hashlib
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import factory
import image_generate
import generate_prompts
import generate_group_prompts
import group_production
import visual_style_profiles
from tools import validate_cover_text


ROOT = Path(__file__).resolve().parent.parent


class FactorySafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

    def make_license(self, directory: Path, **changes: object) -> Path:
        payload = {
            "version": 1,
            "license_id": "test-license",
            "status": "active",
            "approved_count": 3,
            "approved_model": self.config["model"],
            "approved_quality": self.config["quality"],
            "approved_size": self.config["api_size"],
            "approved_base_url": self.config.get("base_url", ""),
            "approved_provider": self.config.get("provider", "official"),
            "start_index": None,
            "end_index": None,
            "one_time": True,
        }
        payload.update(changes)
        path = directory / "license.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_license_is_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = self.make_license(Path(raw))
            result = image_generate.consume_execution_license(path, 3, self.config, 1, 3)
            self.assertEqual(result["status"], "consumed")
            with self.assertRaisesRegex(RuntimeError, "not active"):
                image_generate.consume_execution_license(path, 1, self.config, 1, 1)

    def test_license_rejects_excess_count(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = self.make_license(Path(raw), approved_count=2)
            with self.assertRaisesRegex(RuntimeError, "exceeds licensed count"):
                image_generate.consume_execution_license(path, 3, self.config, 1, 3)

    def test_license_rejects_config_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = self.make_license(Path(raw), approved_quality="low")
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                image_generate.consume_execution_license(path, 1, self.config, 1, 1)

    def test_project_style_is_applied(self) -> None:
        suffix = image_generate.project_style_suffix()
        self.assertIn("普通手机", suffix)
        self.assertIn("已拒绝", suffix)

    def test_api_setup_never_prints_key(self) -> None:
        secret = "TEST_SECRET_NEVER_PRINT_THIS"
        output = io.StringIO()
        with patch.dict(os.environ, {"OPENAI_API_KEY": secret}, clear=False), redirect_stdout(output):
            factory.command_setup_api(SimpleNamespace(check=False))
        rendered = output.getvalue()
        self.assertNotIn(secret, rendered)
        self.assertIn("value is never displayed", rendered)

    def test_project_env_loads_key_without_echo(self) -> None:
        secret = "TEST_LOCAL_ENV_SECRET"
        with tempfile.TemporaryDirectory() as raw:
            env_path = Path(raw) / ".env"
            env_path.write_text(f"# private\nOPENAI_API_KEY={secret}\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                output = io.StringIO()
                with redirect_stdout(output):
                    loaded = factory.load_project_env(env_path)
                self.assertTrue(loaded)
                self.assertEqual(os.environ["OPENAI_API_KEY"], secret)
                self.assertNotIn(secret, output.getvalue())

    def test_project_env_loads_multiple_keys_without_echo(self) -> None:
        first = "TEST_LOCAL_ENV_SECRET_ONE"
        second = "TEST_LOCAL_ENV_SECRET_TWO"
        with tempfile.TemporaryDirectory() as raw:
            env_path = Path(raw) / ".env"
            env_path.write_text(
                f"OPENAI_API_KEY={first}\nOPENAI_API_KEY_2={second}\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                output = io.StringIO()
                with patch.object(image_generate, "ROOT", Path(raw)), redirect_stdout(output):
                    loaded = image_generate.load_project_env()
                    keys = image_generate.configured_api_keys()
                self.assertTrue(loaded)
                self.assertEqual(keys, [first, second])
                self.assertNotIn(first, output.getvalue())
                self.assertNotIn(second, output.getvalue())
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(image_generate, "ROOT", Path(raw)):
                    self.assertTrue(image_generate.load_project_env())
                    self.assertEqual(image_generate.configured_api_keys(), [first, second])

    def test_numbered_api_keys_extend_to_ten_slots(self) -> None:
        env = {"OPENAI_API_KEY": "KEY_1", **{f"OPENAI_API_KEY_{index}": f"KEY_{index}" for index in range(2, 11)}}
        with patch.dict(os.environ, env, clear=True), patch.object(image_generate, "load_project_env", return_value=True):
            self.assertEqual(image_generate.configured_api_keys(), [f"KEY_{index}" for index in range(1, 11)])

    def test_api_key_slots_are_split_evenly_by_project(self) -> None:
        split = factory.split_slots_evenly(list(range(1, 11)), ["road_rescue", "lock_service"])
        self.assertEqual(split["road_rescue"], [1, 2, 3, 4, 5])
        self.assertEqual(split["lock_service"], [6, 7, 8, 9, 10])

    def test_active_group_jobs_are_rebalanced_by_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            jobs_dir = Path(raw)
            first = jobs_dir / "first.json"
            second = jobs_dir / "second.json"
            first.write_text(json.dumps({
                "job_id": "first", "job_type": "group-production", "project_id": "road_rescue",
                "status": "running", "api_key_policy": "fair-share", "api_key_slots": list(range(1, 11)),
            }), encoding="utf-8")
            second.write_text(json.dumps({
                "job_id": "second", "job_type": "group-production", "project_id": "lock_service",
                "status": "queued", "api_key_policy": "fair-share", "api_key_slots": [],
            }), encoding="utf-8")
            with patch.object(factory, "JOBS_DIR", jobs_dir), patch.object(factory, "configured_key_count", return_value=10):
                assignments = factory.rebalance_active_api_key_slots()
            self.assertEqual(assignments["first"], [1, 2, 3, 4, 5])
            self.assertEqual(assignments["second"], [6, 7, 8, 9, 10])
            self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["api_key_slots"], [1, 2, 3, 4, 5])
            self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["api_key_slots"], [6, 7, 8, 9, 10])

    def test_dead_group_job_does_not_reserve_api_key_slots(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            jobs_dir = Path(raw)
            stale = jobs_dir / "stale.json"
            stale.write_text(json.dumps({
                "job_id": "stale", "job_type": "group-production", "project_id": "home_appliance_repair",
                "status": "waiting_for_api", "group_start": 16, "group_count": 60,
                "pid": 12345, "created_at": "2026-07-11T00:00:00+00:00", "api_key_slots": [1, 2, 3],
            }), encoding="utf-8")
            with (
                patch.object(factory, "JOBS_DIR", jobs_dir),
                patch.object(factory, "group_job_process_alive", return_value=False),
            ):
                self.assertEqual(factory.active_group_job_entries(), [])
                self.assertEqual(factory.active_api_key_slots(), set())

    def test_private_env_is_excluded_from_delivery(self) -> None:
        pack_source = (ROOT / "tools" / "pack.py").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn('".env"', pack_source)
        self.assertIn(".env", gitignore.splitlines())

    def test_relay_url_requires_safe_https(self) -> None:
        self.assertEqual(
            factory.validate_public_https_url("https://relay.example/v1/", "base URL"),
            "https://relay.example/v1",
        )
        for unsafe in [
            "http://relay.example/v1",
            "https://user:pass@relay.example/v1",
            "https://relay.example/v1?key=secret",
            "https://relay.example/v1#section",
        ]:
            with self.assertRaises(ValueError):
                factory.validate_public_https_url(unsafe, "base URL")

    def test_relay_env_update_preserves_key(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"
            path.write_text("OPENAI_API_KEY=PRIVATE_TEST_VALUE\nOPENAI_PROVIDER=official\n", encoding="utf-8")
            factory.write_env_values(
                {
                    "OPENAI_PROVIDER": "relay",
                    "OPENAI_BASE_URL": "https://relay.example/v1",
                    "OPENAI_IMAGE_MODEL": "image-model",
                },
                path,
            )
            values = factory.parse_env_file(path)
            self.assertEqual(values["OPENAI_API_KEY"], "PRIVATE_TEST_VALUE")
            self.assertEqual(values["OPENAI_PROVIDER"], "relay")
            self.assertEqual(values["OPENAI_BASE_URL"], "https://relay.example/v1")

    def test_provider_registry_has_unique_known_statuses(self) -> None:
        registry = factory.load_provider_registry()
        providers = registry["providers"]
        self.assertEqual(len({item["id"] for item in providers}), len(providers))
        self.assertTrue({item["status"] for item in providers} <= {
            "verified", "config_compatible", "partial", "unavailable", "retired"
        })
        tinysnow = next(item for item in providers if item["id"] == "tinysnow")
        self.assertEqual(tinysnow["status"], "partial")
        self.assertTrue(tinysnow["known_limitations"])

    def test_help_lists_provider_registry(self) -> None:
        output = io.StringIO()
        with patch.object(factory, "run_python", return_value=0), redirect_stdout(output):
            factory.command_help(SimpleNamespace())
        rendered = output.getvalue()
        self.assertIn("OpenAI 官方", rendered)
        self.assertIn("TinySnow", rendered)

    def test_provider_info_is_available(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = factory.command_provider_info(SimpleNamespace(provider_id="tinysnow"))
        self.assertEqual(result, 0)
        self.assertIn("https://tinysnow.one/v1", output.getvalue())

    def test_relay_image_request_omits_output_format(self) -> None:
        class Images:
            def __init__(self) -> None:
                self.kwargs = {}

            def generate(self, **kwargs: object) -> object:
                self.kwargs = kwargs
                return SimpleNamespace(data=[SimpleNamespace(b64_json="aW1hZ2U=")])

        images = Images()
        client = SimpleNamespace(images=images)
        config = dict(self.config, provider="relay")
        self.assertEqual(image_generate.generate_one(client, config, "test"), b"image")
        self.assertNotIn("output_format", images.kwargs)

    def test_relay_image_response_accepts_https_url(self) -> None:
        class Images:
            def generate(self, **kwargs: object) -> object:
                return SimpleNamespace(data=[SimpleNamespace(b64_json=None, url="https://cdn.example/image.png")])

        client = SimpleNamespace(images=Images())
        config = dict(self.config, provider="relay")
        with patch.object(image_generate, "download_image_url", return_value=b"image-from-url") as download:
            self.assertEqual(image_generate.generate_one(client, config, "test"), b"image-from-url")
        download.assert_called_once_with("https://cdn.example/image.png")

    def test_background_job_progress_is_atomic_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "job.json"
            path.write_text(json.dumps({"job_id": "job-1", "status": "queued"}), encoding="utf-8")
            image_generate.update_job(path, status="waiting_for_api", current_index=7)
            job = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(job["status"], "waiting_for_api")
            self.assertEqual(job["current_index"], 7)
            self.assertIn("updated_at", job)

    @unittest.skipUnless(os.name == "nt", "Windows process flags only")
    def test_group_worker_is_hidden_and_breaks_away_from_launcher(self) -> None:
        flags = factory.hidden_independent_worker_flags()
        self.assertTrue(flags & factory.subprocess.CREATE_NO_WINDOW)
        self.assertTrue(flags & factory.subprocess.DETACHED_PROCESS)
        self.assertTrue(flags & factory.subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(flags & factory.subprocess.CREATE_BREAKAWAY_FROM_JOB)

    def test_road_rescue_project_is_one_cover_plus_eight_details(self) -> None:
        project = factory.project_definition("road_rescue")
        self.assertEqual(project["content_group"]["cover_count"], 1)
        self.assertEqual(project["content_group"]["detail_count"], 8)
        self.assertEqual(project["content_group"]["total_images"], 9)

    def test_road_rescue_cover_prompt_keeps_local_overlay_zones_unpainted(self) -> None:
        library = json.loads((ROOT / "projects/road_rescue/cover_scene_library.json").read_text(encoding="utf-8"))
        prompt, scene = generate_group_prompts.cover_prompt(1, library, ["13800138000"])
        self.assertIn("13800138000", prompt)
        self.assertEqual(scene["phones"], ["13800138000"])
        self.assertEqual(scene["phone_bar_text"], "13800138000")
        self.assertIn("中部偏下和底部只保留连续真实", prompt)
        self.assertIn("电话胶囊", prompt)
        self.assertIn("蓝色服务方格", prompt)
        self.assertNotIn("大号粗体、高对比随机颜色", prompt)
        self.assertNotIn("叠加两行五列十宫格服务词", prompt)
        self.assertIn("主标题、业务信息和真实结构细节三个层级", prompt)
        self.assertIn("本地图像处理程序不会再向门头添加任何文字或底板", prompt)
        self.assertIn("realistic_mobile_documentary_v2", prompt)
        self.assertNotIn("15795643941", prompt)
        self.assertRegex(prompt, r"2014|2018|2019|2022|2023|2026")
        self.assertNotIn("两层旧瓷砖", prompt)
        self.assertIn("经营形态", prompt)
        self.assertIn("维修作业", prompt)
        self.assertIn("街道状态", prompt)
        self.assertEqual(scene["visual_style_version"], "realistic_mobile_documentary_v2")
        self.assertEqual(scene["category_config_version"], "road_rescue_category_content_v1")

    def test_contact_confirmation_is_local_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime = Path(raw)
            args = SimpleNamespace(project_id="road_rescue", phone=["13800138000"], confirm=True)
            with patch.object(factory, "RUNTIME_DIR", runtime), redirect_stdout(io.StringIO()):
                self.assertEqual(factory.command_confirm_contact(args), 0)
            payload = json.loads((runtime / "projects/road_rescue/business.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["user_confirmed"])
            self.assertEqual(payload["contact_phones"], ["13800138000"])

    def test_contact_confirmation_preserves_400_hotline_display_format(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime = Path(raw)
            args = SimpleNamespace(
                project_id="truck_rescue",
                phone=["400-677-1311"],
                confirm=True,
            )
            with patch.object(factory, "RUNTIME_DIR", runtime), redirect_stdout(io.StringIO()):
                self.assertEqual(factory.command_confirm_contact(args), 0)
            payload = json.loads(
                (runtime / "projects/truck_rescue/business.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["contact_phones"], ["400-677-1311"])
            self.assertFalse(payload["placeholder_only"])

    def test_cover_phone_bar_preserves_original_backup(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            image = root / "01_cover.png"
            backup_dir = root / "backups"
            Image.new("RGB", (720, 1280), (32, 32, 32)).save(image)
            before = image.read_bytes()
            self.assertTrue(factory.draw_cover_phone_bar(image, "13800138000", 1, backup_dir))
            self.assertNotEqual(image.read_bytes(), before)
            backup = backup_dir / "group_0001_01_cover.png"
            self.assertTrue(backup.is_file())
            self.assertEqual(backup.read_bytes(), before)

    def test_group_license_is_bound_and_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "license.json"
            payload = {
                "kind": "group-production", "status": "active", "project_id": "road_rescue",
                "group_start": 1, "group_count": 1, "manifest_sha256": "manifest",
                "provider": "relay", "base_url": "https://relay.example/v1", "model": "image-model",
                "approved_image_count": 9, "approved_request_budget": 9,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = group_production.consume_license(path, {
                "project_id": "road_rescue", "group_start": 1, "group_count": 1,
                "manifest_sha256": "manifest", "pending_api_images": 9,
            }, {"provider": "relay", "base_url": "https://relay.example/v1", "model": "image-model"})
            self.assertEqual(result["status"], "consumed")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["requests_used"], 0)

    def test_group_atomic_json_retries_transient_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "license.json"
            original_replace = Path.replace
            calls = {"count": 0}

            def flaky_replace(self: Path, target: Path) -> Path:
                if target == path and calls["count"] == 0:
                    calls["count"] += 1
                    raise PermissionError("temporarily locked")
                return original_replace(self, target)

            with patch.object(Path, "replace", flaky_replace):
                group_production.atomic_json(path, {"requests_used": 1})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"requests_used": 1})
            self.assertEqual(calls["count"], 1)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_api_key_slot_hard_failure_detection(self) -> None:
        self.assertTrue(group_production.api_key_slot_hard_failure(
            'Error code: 404 - {"type": "model_not_found"}'
        ))
        self.assertTrue(group_production.api_key_slot_hard_failure(
            'Model "gpt-image-2" is not supported by any configured account in this group'
        ))
        self.assertTrue(group_production.api_key_slot_hard_failure("403 INSUFFICIENT_BALANCE"))
        self.assertFalse(group_production.api_key_slot_hard_failure("502 Bad Gateway"))
        self.assertFalse(group_production.api_key_slot_hard_failure("content_policy_violation"))

    def test_api_key_quarantine_is_scoped_to_provider_and_model(self) -> None:
        config = {"provider": "relay", "base_url": "https://tinysnow.one/v1", "model": "gpt-image-2"}
        with tempfile.TemporaryDirectory() as raw:
            quarantine_path = Path(raw) / "api_key_slot_quarantine.json"
            with patch.object(group_production, "API_KEY_QUARANTINE_PATH", quarantine_path):
                self.assertEqual(group_production.quarantined_api_key_slots(config), set())
                group_production.quarantine_api_key_slot(1, config, "model_not_found", "job-one")
                self.assertEqual(group_production.quarantined_api_key_slots(config), {1})
                self.assertEqual(
                    group_production.quarantined_api_key_slots({**config, "model": "other-model"}),
                    set(),
                )

    def test_fair_share_skips_quarantined_api_key_slots(self) -> None:
        config = {"provider": "relay", "base_url": "https://tinysnow.one/v1", "model": "gpt-image-2"}
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir()
            quarantine_path = root / "api_key_slot_quarantine.json"
            job_path = jobs_dir / "job.json"
            job_path.write_text(json.dumps({
                "job_id": "job",
                "job_type": "group-production",
                "project_id": "road_rescue",
                "status": "queued",
                "group_start": 1,
                "group_count": 1,
                "api_key_policy": "fair-share",
                "api_key_slots": [],
                "created_at": "2026-07-14T00:00:00+00:00",
            }), encoding="utf-8")
            with (
                patch.object(factory, "JOBS_DIR", jobs_dir),
                patch.object(factory, "configured_key_count", return_value=3),
                patch.object(factory, "effective_api_config", return_value=config),
                patch.object(group_production, "API_KEY_QUARANTINE_PATH", quarantine_path),
            ):
                group_production.quarantine_api_key_slot(1, config, "model_not_found", "previous-job")
                assignments = factory.rebalance_active_api_key_slots()
            self.assertEqual(assignments["job"], [2, 3])
            self.assertEqual(json.loads(job_path.read_text(encoding="utf-8"))["api_key_slots"], [2, 3])

    def test_group_plan_reuses_only_decodable_png_images(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            valid_target = root / "valid-target.png"
            corrupt_target = root / "corrupt-target.png"
            valid_source = root / "valid-source.png"
            corrupt_source = root / "corrupt-source.png"
            Image.new("RGB", (32, 48), (10, 20, 30)).save(valid_target)
            Image.new("RGB", (32, 48), (30, 20, 10)).save(valid_source)
            corrupt_target.write_bytes(b"not-a-png")
            corrupt_source.write_bytes(b"not-a-png")
            records = [
                {"target": str(valid_target), "source": None, "prompt_sha256": "a"},
                {"target": str(corrupt_target), "source": None, "prompt_sha256": "b"},
                {"target": str(root / "copy.png"), "source": str(valid_source), "prompt_sha256": "c"},
                {"target": str(root / "bad-copy.png"), "source": str(corrupt_source), "prompt_sha256": "d"},
                {"target": str(root / "missing.png"), "source": str(root / "absent.png"), "prompt_sha256": "e"},
            ]
            with patch.object(group_production, "production_records", return_value=records):
                result = group_production.plan(1, 1, "home_appliance_repair")
            self.assertEqual(result["existing"], 1)
            self.assertEqual(result["reusable_without_api"], 1)
            self.assertEqual(result["reusable_images"], 2)
            self.assertEqual(result["invalid_existing"], 1)
            self.assertEqual(result["pending_api_images"], 3)

    def test_group_lock_rejects_concurrent_task(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(group_production, "LOCK_PATH", Path(raw) / "lock.json"):
            group_production.acquire_lock("job-one")
            with self.assertRaisesRegex(RuntimeError, "another group task"):
                group_production.acquire_lock("job-two")

    def test_manual_cover_validation_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            image = Path(raw) / "cover.png"
            image.write_bytes(b"not-decoded-in-manual-mode")
            payload = validate_cover_text.manual_approve(image, ["店名", "88888888"], "human checked")
            self.assertTrue(payload["approved"])
            self.assertEqual(payload["status"], "manual_approved")
            self.assertTrue(validate_cover_text.validation_path(image).is_file())

    def test_group_style_is_project_scoped(self) -> None:
        suffix = group_production.project_style_suffix("cover")
        self.assertIn("汽车救援项目风格", suffix)
        self.assertIn("汽车救援门头首图风格档案", suffix)

    def test_projects_share_visual_style_profile(self) -> None:
        road = factory.project_definition("road_rescue")
        home = factory.project_definition("home_appliance_repair")
        self.assertEqual(
            road["prompt_sources"]["visual_style"],
            "configs/visual_styles/realistic_mobile_documentary_v2.json",
        )
        self.assertEqual(road["prompt_sources"]["visual_style"], home["prompt_sources"]["visual_style"])
        suffix = visual_style_profiles.prompt_suffix("road_rescue", "road_rescue_detail")
        self.assertIn("realistic_mobile_documentary_v2", suffix)
        self.assertIn("不要电影海报式灯光", suffix)

    def test_road_rescue_business_assets_hash_is_unchanged(self) -> None:
        scene = json.loads((ROOT / "scene_library.json").read_text(encoding="utf-8"))
        cover = json.loads((ROOT / "projects/road_rescue/cover_scene_library.json").read_text(encoding="utf-8"))
        project = factory.project_definition("road_rescue")
        asset = {
            "project_id": project["id"],
            "group_total": project["content_group"]["total_images"],
            "cover_count": project["content_group"]["cover_count"],
            "detail_count": project["content_group"]["detail_count"],
            "service_grid": factory.ROAD_RESCUE_SERVICE_GRID,
            "store_name_prefixes": cover["store_name_prefixes"],
            "store_name_suffixes": cover["store_name_suffixes"],
            "business_lines": cover["business_lines"],
            "rescue_jobs": [item["name"] for item in scene["rescue_jobs"]],
            "job_actions": [item["action"] for item in scene["rescue_jobs"]],
            "tools": sorted({tool for item in scene["rescue_jobs"] for tool in item["tools"]}),
            "vehicle_types": scene["vehicle_types"],
            "rescue_vehicle_policies": sorted(scene["rescue_vehicles_by_policy"].keys()),
            "locations": sorted({value for values in scene["location_groups"].values() for value in values}),
            "negative_constraints": scene["negative_constraints"],
            "output_dir": project["output_dir"],
            "group_registry": project["group_registry"],
        }
        encoded = json.dumps(asset, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self.assertEqual(digest, "e1c00771a1a692cf2b36288b27442da12dd82935a746bbd11a7a00648b145225")

    def test_road_rescue_detail_prompts_use_visual_lens_without_appliance_content(self) -> None:
        scene = json.loads((ROOT / "scene_library.json").read_text(encoding="utf-8"))
        records = generate_prompts.generate_records(self.config, scene, 8, seed=20260713)
        self.assertEqual(len(records), 8)
        self.assertTrue(all(item["visual_style_version"] == "realistic_mobile_documentary_v2" for item in records))
        self.assertTrue(all(item["category_config_version"] == "road_rescue_category_content_v1" for item in records))
        for item in records:
            self.assertIn("镜头选择：", item["prompt"])
            self.assertIn("realistic_mobile_documentary_v2", item["prompt"])
            self.assertIn("visual_lens", item["scene"])
            self.assertNotIn("洗衣机维修", item["prompt"])
            self.assertNotIn("油烟机维修", item["prompt"])

    def test_prompt_tuning_draft_is_excluded_from_batch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            approved = root / "approved.jsonl"
            drafts = root / "drafts.jsonl"
            approved.write_text(json.dumps({
                "action": "keep", "dimension": "真实感", "note": "保持手机实拍", "status": "active"
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            drafts.write_text(json.dumps({
                "action": "weaken", "dimension": "年代感", "note": "不要太新", "status": "active"
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            with patch.object(generate_group_prompts, "TUNING_RULES_PATH", approved), patch.object(
                generate_group_prompts, "TUNING_DRAFTS_PATH", drafts
            ):
                sample_suffix = generate_group_prompts.tuning_suffix(include_drafts=True)
                batch_suffix = generate_group_prompts.tuning_suffix(include_drafts=False)
            self.assertIn("不要太新", sample_suffix)
            self.assertNotIn("不要太新", batch_suffix)
            self.assertIn("保持手机实拍", batch_suffix)

    def test_tuning_guide_exposes_user_dimensions(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            factory.command_tune_prompt_guide(SimpleNamespace(project_id="road_rescue"))
        rendered = output.getvalue()
        self.assertIn("年代感", rendered)
        self.assertIn("电话大小与位置", rendered)
        self.assertIn("加强 / 减弱 / 新增 / 删除 / 保持", rendered)

    def test_group_detail_selection_skips_rejected_snow_scenes(self) -> None:
        detail_records = [
            {"index": 1, "scene": {"weather": "小雪，路面薄雪", "rescue_job": "雪地救援"}, "prompt": "雪地救援"},
            *[
                {"index": index, "scene": {"weather": "普通晴天", "rescue_job": "搭电救援"}, "prompt": "普通晴天"}
                for index in range(2, 10)
            ],
        ]
        chunks = generate_group_prompts.select_detail_chunks(
            detail_records, used_indices=set(), group_count=1, reject_snow=True
        )
        self.assertEqual(chunks, [[2, 3, 4, 5, 6, 7, 8, 9]])

    def test_group_detail_selection_requires_current_visual_style_when_requested(self) -> None:
        detail_records = [
            {"index": 1, "visual_style_version": "old", "scene": {}, "prompt": "old"},
            *[
                {
                    "index": index,
                    "visual_style_version": "realistic_mobile_documentary_v2",
                    "scene": {},
                    "prompt": "new",
                }
                for index in range(2, 10)
            ],
        ]
        chunks = generate_group_prompts.select_detail_chunks(
            detail_records,
            used_indices=set(),
            group_count=1,
            reject_snow=False,
            desired_visual_style="realistic_mobile_documentary_v2",
        )
        self.assertEqual(chunks, [[2, 3, 4, 5, 6, 7, 8, 9]])


if __name__ == "__main__":
    unittest.main()
