from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import factory
from tools import category_batch_audit, category_image_production, prompt_engine


ROOT = Path(__file__).resolve().parent.parent


class PipeUncloggingCategoryTests(unittest.TestCase):
    def test_config_has_fixed_nine_image_group(self) -> None:
        config = prompt_engine.load_category_config("pipe_unclogging")
        structure = config["image_group_structure"]
        self.assertEqual(structure["cover_count"], 1)
        self.assertEqual(structure["detail_count"], 8)
        self.assertEqual(structure["total_per_group"], 9)
        self.assertEqual(len(structure["detail_roles"]), 8)

    def test_detail_prompt_never_uses_road_rescue_elements(self) -> None:
        config = prompt_engine.load_category_config("pipe_unclogging")
        record = prompt_engine.build_prompt_record(config, "厨房下水道疏通", 1, __import__("random").Random(2))
        text = record["positive_prompt"]
        for forbidden in ("高速路", "拖车", "救援车", "换胎", "搭电", "家电拆机", "开锁工具"):
            self.assertNotIn(forbidden, text)
        self.assertIn("目标模式 realism_dehomogenization_target_v1：", text)
        self.assertIsNone(record["scene"]["weather"])
        self.assertTrue(prompt_engine.scene_matches_legal_combination(config, record["role"], record["scene"]))

    def test_every_role_uses_only_legal_business_combinations(self) -> None:
        config = prompt_engine.load_category_config("pipe_unclogging")
        roles = ["cover", *config["image_group_structure"]["detail_roles"]]
        rng = __import__("random").Random(20260710)
        for role in roles:
            for index in range(50):
                record = prompt_engine.build_prompt_record(config, role, index + 1, rng)
                self.assertTrue(prompt_engine.scene_matches_legal_combination(config, role, record["scene"]), record)

    def test_indoor_and_outdoor_details_do_not_cross(self) -> None:
        config = prompt_engine.load_category_config("pipe_unclogging")
        rng = __import__("random").Random(88)
        for index in range(100):
            indoor = prompt_engine.build_prompt_record(config, "厨房下水道疏通", index + 1, rng)
            outdoor = prompt_engine.build_prompt_record(config, "抽粪清淤/化粪池清理", index + 1, rng)
            self.assertNotIn("室外", indoor["scene"]["environment_detail"])
            self.assertNotIn("室内", outdoor["scene"]["lighting"])

    def test_group_batch_contains_one_cover_and_eight_fixed_details(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.object(prompt_engine, "CATEGORY_BATCH_ROOT", root):
                result = prompt_engine.generate_batch("pipe_unclogging", None, 1, True)
            records = [json.loads(line) for line in (result["batch_dir"] / "prompts.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 9)
        self.assertEqual([record["role"] for record in records], ["cover", "厨房下水道疏通", "马桶疏通", "地漏疏通", "主管道疏通", "高压清洗管道", "管道内窥镜检测", "抽粪清淤/化粪池清理", "餐饮店后厨油污管道"])

    def test_ten_cover_prompts_keep_legal_source_scenes_and_unique_variants(self) -> None:
        config = {
            "provider": "relay",
            "base_url": "https://example.invalid/v1",
            "model": "gpt-image-2",
            "quality": "medium",
            "api_size": "1024x1536",
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(prompt_engine, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
            ):
                generated = prompt_engine.generate_batch("pipe_unclogging", None, 10, True)
                run_plan = category_image_production.plan(
                    "pipe_unclogging", generated["batch_dir"], 1, 10, "13317112954", config
                )
        cover_records = [record for record in run_plan["records"] if record["role"] == "cover"]
        cover_entries = [entry for entry in run_plan["manifest_entries"] if entry["role"] == "cover"]
        self.assertEqual(len(cover_entries), 10)
        self.assertEqual(len({entry["effective_prompt"] for entry in cover_entries}), 10)
        self.assertEqual(len({entry["cover_variant_signature"] for entry in cover_entries}), 10)
        self.assertGreaterEqual(
            len({(entry["cover_variant"]["camera"], entry["cover_variant"]["distance"]) for entry in cover_entries}),
            6,
        )
        for record, entry in zip(cover_records, cover_entries):
            prompt = entry["effective_prompt"]
            self.assertIn(record["scene"]["location"], prompt)
            self.assertIn(record["scene"]["worker_action"], prompt)
            self.assertIn(record["scene"]["tool"], prompt)
            self.assertIn("不要生成黑色整条电话带", prompt)
            self.assertIsNone(re.search(r"1[3-9]\d{9}", prompt))
            self.assertEqual(entry["cover_style_version"], 2)

    def test_mock_audit_never_creates_images(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.object(prompt_engine, "CATEGORY_BATCH_ROOT", root), patch.object(category_batch_audit, "CATEGORY_BATCH_ROOT", root):
                result = prompt_engine.generate_batch("pipe_unclogging", 2, None, True)
                audited = category_batch_audit.audit_batch("pipe_unclogging", str(result["batch_dir"]), "mock")
            batch_dir = audited["batch_dir"]
            self.assertTrue((batch_dir / "audit_report.json").is_file())
            self.assertTrue((batch_dir / "audit_report.csv").is_file())
            self.assertTrue((batch_dir / "audit_report_readable.txt").is_file())
            self.assertTrue((batch_dir / "review_log.xlsx").is_file())
            self.assertFalse(any(path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} for path in batch_dir.rglob("*")))

    def test_paid_plan_is_batch_local_and_uses_strict_fixed_roles(self) -> None:
        config = {
            "provider": "relay",
            "base_url": "https://example.invalid/v1",
            "model": "gpt-image-2",
            "quality": "medium",
            "api_size": "1024x1536",
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(prompt_engine, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
            ):
                generated = prompt_engine.generate_batch("pipe_unclogging", None, 1, True)
                run_plan = category_image_production.plan(
                    "pipe_unclogging", generated["batch_dir"], 1, 1, "13317112954", config
                )
                manifest_file, overlay_file = category_image_production.write_production_files(
                    run_plan, "13317112954"
                )
            batch_dir = generated["batch_dir"].resolve()
            self.assertEqual(run_plan["total_images"], 9)
            self.assertEqual(run_plan["pending_api_images"], 9)
            self.assertEqual(len(run_plan["manifest_entries"]), 9)
            self.assertTrue(manifest_file.is_relative_to(batch_dir))
            self.assertTrue(overlay_file.is_relative_to(batch_dir))
            for record in run_plan["records"]:
                self.assertTrue(Path(record["target"]).resolve().is_relative_to(batch_dir))
                self.assertTrue(Path(record["raw_target"]).resolve().is_relative_to(batch_dir))
            prompts_by_role = {entry["role"]: entry["effective_prompt"] for entry in run_plan["manifest_entries"]}
            self.assertIn("高压清洗机", prompts_by_role["高压清洗管道"])
            self.assertIn("不能只有吸污管", prompts_by_role["高压清洗管道"])
            self.assertIn("不能只做检测", prompts_by_role["主管道疏通"])
            self.assertIn("2:3竖图", prompts_by_role["cover"])
            self.assertNotIn("电话：13317112954", prompts_by_role["cover"])

    def test_needs_fix_cover_requires_new_api_image_even_when_png_and_raw_exist(self) -> None:
        from PIL import Image

        config = {
            "provider": "relay",
            "base_url": "https://example.invalid/v1",
            "model": "gpt-image-2",
            "quality": "medium",
            "api_size": "1024x1536",
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(prompt_engine, "CATEGORY_BATCH_ROOT", root),
                patch.object(category_image_production, "CATEGORY_BATCH_ROOT", root),
            ):
                generated = prompt_engine.generate_batch("pipe_unclogging", None, 1, True)
                records = category_image_production.record_targets(
                    generated["batch_dir"],
                    category_image_production.selected_records(generated["batch_dir"], 1, 1),
                )
                cover = records[0]
                target = Path(cover["target"])
                raw_target = Path(cover["raw_target"])
                target.parent.mkdir(parents=True)
                raw_target.parent.mkdir(parents=True)
                Image.new("RGB", (1024, 1536), (180, 180, 180)).save(target)
                Image.new("RGB", (1024, 1536), (180, 180, 180)).save(raw_target)
                target.with_suffix(".validation.json").write_text(
                    json.dumps({"status": "needs_fix"}, ensure_ascii=False),
                    encoding="utf-8",
                )
                run_plan = category_image_production.plan(
                    "pipe_unclogging", generated["batch_dir"], 1, 1, "13317112954", config
                )
        self.assertEqual(run_plan["existing_images"], 0)
        self.assertEqual(run_plan["recoverable_images"], 0)
        self.assertEqual(run_plan["pending_api_images"], 9)

    def test_paid_worker_rejects_job_or_license_outside_batch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            batch = root / "batch_test"
            batch.mkdir()
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            expected_license = category_image_production.license_path("pipe_unclogging", batch, 1, 1)
            expected_license.parent.mkdir(parents=True)
            expected_license.write_text("{}", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                category_image_production.validate_worker_paths(batch, 1, 1, outside, outside)

    def test_paid_clients_disable_sdk_retries(self) -> None:
        config = {"base_url": "https://example.invalid/v1"}
        with (
            patch.object(category_image_production.image_generate, "load_project_env"),
            patch.object(
                category_image_production.image_generate,
                "configured_api_keys",
                return_value=["test-key"],
            ),
            patch("openai.OpenAI") as client_factory,
        ):
            clients = category_image_production.openai_clients_by_slot(config, [1])
        self.assertEqual(clients[0][0], 1)
        self.assertEqual(client_factory.call_args.kwargs["max_retries"], 0)
        self.assertEqual(client_factory.call_args.kwargs["base_url"], config["base_url"])

    def test_paid_worker_module_entrypoint_imports_from_repo_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "tools.category_image_production", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Pipe-unclogging category image production worker", completed.stdout)

    def test_effective_prompt_requires_blank_matte_physical_signboard(self) -> None:
        prompt = category_image_production.effective_prompt(
            {
                "category_id": "pipe_unclogging",
                "generation_kind": "cover",
                "prompt": "写实管道疏通门店，门头留空。",
            },
            "13317112954",
        )
        self.assertIn("管道疏通封面最高优先级覆盖规则", prompt)
        self.assertIn("哑光实体招牌板面", prompt)
        self.assertIn("不得生成灯箱、LED灯带", prompt)
        self.assertIn("另一块覆盖原门头的新底板", prompt)

    def test_local_overlays_keep_visual_approval_false(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "raw.png"
            target = root / "final.png"
            Image.new("RGB", (1024, 1536), (180, 180, 180)).save(source)
            service_items = ["厨房疏通", "马桶疏通", "地漏疏通", "主管道疏通", "高压清洗", "内窥检测", "抽粪清淤", "后厨油污"]
            validation = category_image_production.apply_overlays(
                source, target, "13317112954", "cover", 1, 1, service_items
            )
            self.assertTrue(target.is_file())
            self.assertFalse(validation["approved"])
            self.assertEqual(validation["status"], "needs_user_review")
            self.assertIn("电话：13317112954", validation["expected_text"])
            self.assertIn("联系电话：13317112954", validation["expected_text"])
            self.assertEqual(validation["overlay_style"]["version"], 3)
            self.assertEqual(
                validation["overlay_style"]["signboard_style"],
                "direct_text_on_detected_physical_signboard",
            )
            self.assertIn(validation["overlay_style"]["service_layout"], category_image_production.COVER_SERVICE_LAYOUTS)
            with Image.open(target) as rendered:
                self.assertEqual(rendered.convert("RGB").getpixel((0, int(rendered.height * 0.49))), (180, 180, 180))

    def test_pipe_signboard_keeps_original_board_pixels_without_new_panel(self) -> None:
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "raw.png"
            target = root / "final.png"
            image = Image.new("RGB", (1024, 1536), (156, 156, 156))
            board = [(85, 90), (950, 150), (925, 390), (70, 325)]
            ImageDraw.Draw(image).polygon(board, fill=(32, 118, 77))
            image.save(source)
            untouched = image.getpixel((115, 125))
            validation = category_image_production.apply_overlays(
                source,
                target,
                "13317112954",
                "cover",
                1,
                1,
                ["厨房疏通", "马桶疏通", "地漏疏通", "主管道疏通", "高压清洗", "内窥检测", "抽粪清淤", "后厨油污"],
                category_id="pipe_unclogging",
            )
            self.assertEqual(validation["overlay_style"]["signboard_detection"], "upper_color_component")
            self.assertEqual(len(validation["overlay_style"]["signboard_quad"]), 4)
            with Image.open(target) as rendered:
                self.assertEqual(rendered.convert("RGB").getpixel((115, 125)), untouched)

    def test_dashboard_uses_current_session_without_scanning_historical_images(self) -> None:
        main_js = (ROOT / "dashboard" / "main.js").read_text(encoding="utf-8")
        session_js = (ROOT / "dashboard" / "session.js").read_text(encoding="utf-8")
        self.assertIn("readDashboardSession", main_js)
        self.assertIn("buildSessionGallery", main_js)
        self.assertNotIn("listPngFiles(outputDir)", main_js)
        self.assertIn("events_${job.job_id}.jsonl", session_js)
        self.assertNotIn("writeFileSync(path.join(projectRoot, 'projects', 'registry.json')", main_js)

    def test_category_network_preflight_falls_back_to_direct_without_stale_proxy(self) -> None:
        stale = {
            "HTTP_PROXY": "http://127.0.0.1:7897",
            "HTTPS_PROXY": "http://127.0.0.1:7897",
            "all_proxy": "http://127.0.0.1:7897",
        }
        with (
            patch.dict(os.environ, stale, clear=False),
            patch("socket.create_connection", side_effect=OSError("not listening")),
            patch.object(factory, "_category_endpoint_reachable", return_value=True),
        ):
            env = factory._category_proxy_environment({"base_url": "https://example.invalid/v1"})
        self.assertEqual(env["PIPE_CATEGORY_NETWORK_MODE"], "direct")
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            self.assertNotIn(key, env)


if __name__ == "__main__":
    unittest.main()
