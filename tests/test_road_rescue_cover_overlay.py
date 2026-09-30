from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

from tools import category_image_production
from tools.prompt_engine import CategoryPromptError
from generate_group_prompts import cover_prompt
from generate_road_rescue_v3_groups import _cover_record


class RoadRescueCoverOverlayTests(unittest.TestCase):
    def test_prepare_regeneration_archives_paid_raw_and_marks_cover_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            batch_dir = root / "batch_test"
            raw_target = batch_dir / "raw" / "group_0316" / "u01_cover.png"
            target = root / "output" / "group_0316" / "01_cover.png"
            validation_path = target.with_suffix(".validation.json")
            raw_target.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            Image.new("RGB", (1024, 1536), (40, 60, 80)).save(raw_target)
            Image.new("RGB", (1024, 1536), (80, 100, 120)).save(target)
            validation_path.write_text(
                json.dumps({
                    "status": "needs_user_review",
                    "approved": False,
                    "manual_visual_approval": False,
                }),
                encoding="utf-8",
            )
            original_validation_bytes = validation_path.read_bytes()
            run_plan = {
                "delivery_records": [{
                    "delivery_kind": "cover",
                    "group_index": 316,
                    "target": str(target),
                    "records": [{"raw_target": str(raw_target)}],
                }],
            }

            with patch.object(category_image_production, "plan", return_value=run_plan):
                result = category_image_production.prepare_cover_regeneration(
                    "road_rescue",
                    batch_dir,
                    316,
                    1,
                    "15377029700",
                    {},
                    root / "output",
                    "实体门头丰富度不足",
                )

            current = json.loads(validation_path.read_text(encoding="utf-8"))
            archived = result["results"][0]
            self.assertEqual(current["status"], "rejected")
            self.assertTrue(current["replacement_required"])
            self.assertEqual(current["rejection_reason"], "实体门头丰富度不足")
            self.assertTrue(Path(archived["archived_image"]).is_file())
            self.assertTrue(Path(archived["archived_validation"]).is_file())
            self.assertTrue(Path(archived["archived_raw"]).is_file())
            self.assertTrue(raw_target.is_file())
            self.assertEqual(
                Path(archived["archived_validation"]).read_bytes(),
                original_validation_bytes,
            )
            self.assertEqual(
                archived["validation_sha256"],
                hashlib.sha256(original_validation_bytes).hexdigest(),
            )

    def test_effective_prompt_requires_native_signboard_phone(self) -> None:
        prompt = category_image_production.effective_prompt(
                {
                    "category_id": "road_rescue",
                    "generation_kind": "cover",
                    "prompt": (
                        "写实道路救援门店，门头主标题必须清晰准确。"
                        "\n道路救援 v3 补充规则：原始生图画面不要生成任何真实电话号码、二维码、水印、价格或可读车牌；"
                        "门头联系电话、中心电话条和底部十宫格服务词全部由本地图像处理程序叠加。"
                        "画面中部偏下必须为后期电话条保留干净横向区域，不要放关键人脸。"
                        "画面底部必须为本地后处理十宫格服务项目区保留规整空间，不要放核心动作。"
                        "最终电话号码还会在图片生成完成后由本地图像处理程序居中叠加，"
                        "使用大号粗体、高对比随机颜色、半透明深色底条，确保预览缩略图中也能看清。"
                        "图片底部还会由本地图像处理程序叠加两行五列十宫格服务词；"
                        "原始照片不要生成按钮、卡片、色块或任何服务文字。"
                    ),
                },
            "15377029700",
        )

        self.assertIn("道路救援封面最高优先级覆盖规则", prompt)
        self.assertIn("门头联系电话必须由图像模型作为真实实体招牌排版的一部分自然生成", prompt)
        self.assertIn("号码必须清楚准确写成“15377029700”", prompt)
        self.assertIn("店名、汽车救援主业务词、服务小字、联系电话四层信息", prompt)
        self.assertIn("本地图像处理程序不再向门头区域添加任何文字或底板", prompt)
        self.assertIn("发光叠加板", prompt)
        self.assertIn("电话胶囊", prompt)
        self.assertIn("蓝色服务方格", prompt)
        self.assertIn("只能留空实景", prompt)
        self.assertNotIn("门头联系电话、中心电话条和底部十宫格服务词全部由本地图像处理程序叠加", prompt)
        self.assertNotIn("大号粗体、高对比随机颜色", prompt)
        self.assertNotIn("叠加两行五列十宫格服务词", prompt)

    def test_effective_prompt_rejects_unconfirmed_signboard_phone(self) -> None:
        with self.assertRaises(CategoryPromptError):
            category_image_production.effective_prompt(
                {
                    "category_id": "road_rescue",
                    "generation_kind": "cover",
                    "prompt": "写实道路救援门店，门头号码为13800138000。",
                },
                "15377029700",
            )

    def test_cover_prompt_uses_richer_native_signboard_variables(self) -> None:
        root = Path(__file__).resolve().parent.parent
        library = json.loads((root / "projects/road_rescue/cover_scene_library.json").read_text(encoding="utf-8"))

        prompt, scene = cover_prompt(346, library, ["15377029700"])

        for key in ("sign_information_layouts", "sign_accent_details", "sign_installation_details"):
            self.assertGreaterEqual(len(library[key]), 5)
            self.assertIn(scene[key], prompt)
        for key in (
            "signboard_realism_rules",
            "signboard_framing_rules",
            "keyword_hierarchy_rules",
        ):
            self.assertGreaterEqual(len(library[key]), 3)
            for rule in library[key]:
                self.assertIn(rule, prompt)
        self.assertEqual(
            scene["cover_template_version"],
            "road_rescue_storefront_mobile_v2",
        )
        self.assertIn("门头模板版本：road_rescue_storefront_mobile_v2", prompt)
        self.assertIn(scene["main_business_word"], {"汽车救援", "道路救援", "拖车服务"})
        self.assertIn(f"店名不得比“{scene['main_business_word']}”更大或更醒目", prompt)
        self.assertIn("禁止孤立招牌铺满画面", prompt)
        self.assertIn("禁止4比1以上的过窄超长条", prompt)
        self.assertIn("不做正交矫正", prompt)
        self.assertIn("右侧楔形图标区", prompt)
        self.assertIn("主标题、业务信息和真实结构细节三个层级", prompt)
        self.assertIn("门头主招牌板面内部必须把联系电话自然排版成实体招牌内容", prompt)
        self.assertIn("15377029700", prompt)
        self.assertIn("本地图像处理程序不会再向门头添加任何文字或底板", prompt)

    def test_signboard_region_has_no_local_overlay_but_requires_native_phone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "raw.png"
            target = root / "cover.png"
            background = (83, 117, 149)
            Image.new("RGB", (1024, 1536), background).save(source)

            validation = category_image_production.apply_overlays(
                source,
                target,
                "15377029700",
                "cover",
                316,
                1,
                [
                    "汽车救援",
                    "搭电救援",
                    "拖车服务",
                    "补胎换胎",
                    "送油救援",
                    "困境救援",
                    "地库救援",
                    "车辆救援",
                    "高速救援",
                    "城市路救援",
                ],
                category_id="road_rescue",
            )

            self.assertEqual(validation["overlay_style"]["version"], 8)
            self.assertEqual(
                validation["overlay_style"]["signboard_style"],
                "source_generated_physical_signboard_phone_no_local_overlay",
            )
            self.assertIn("联系电话：15377029700", validation["expected_text"])
            self.assertIsNone(validation["overlay_style"]["signboard_detection"])
            self.assertIsNone(validation["overlay_style"]["signboard_quad"])
            self.assertEqual(
                validation["overlay_style"]["bottom_service_backing"],
                "opaque_mask",
            )
            expected_bottom_style = (
                category_image_production.road_rescue_bottom_service_style(316)
            )
            self.assertEqual(
                validation["overlay_style"]["bottom_service_style"]["style_id"],
                expected_bottom_style["style_id"],
            )
            with Image.open(target) as rendered:
                rendered_rgb = rendered.convert("RGB")
                source_top = Image.new("RGB", (1024, 512), background)
                rendered_top = rendered_rgb.crop((0, 0, 1024, 512))
                self.assertIsNone(ImageChops.difference(source_top, rendered_top).getbbox())
                self.assertEqual(rendered_rgb.getpixel((40, 80)), background)
                expected_background = expected_bottom_style["background"][:3]
                self.assertEqual(rendered_rgb.getpixel((30, 1200)), expected_background)
                self.assertEqual(rendered_rgb.getpixel((512, 1535)), expected_background)

    def test_bottom_service_style_rotates_through_120_combinations(self) -> None:
        styles = [
            category_image_production.road_rescue_bottom_service_style(group_index)
            for group_index in range(1, 121)
        ]

        self.assertEqual(len({style["style_id"] for style in styles}), 120)
        self.assertEqual(len({style["name"] for style in styles}), 8)
        self.assertEqual(
            {style["layout"] for style in styles},
            {"three_rows", "two_columns", "four_by_two"},
        )
        self.assertEqual(len({style["accent"] for style in styles}), 5)
        self.assertTrue(all(style["background"][3] == 255 for style in styles))

    def test_future_v3_cover_record_tracks_mobile_signboard_template_version(self) -> None:
        root = Path(__file__).resolve().parent.parent
        library = json.loads(
            (root / "projects/road_rescue/cover_scene_library.json").read_text(
                encoding="utf-8"
            )
        )
        record, _signature = _cover_record(
            346,
            1,
            {"id": "height_1408", "width": 1024, "height": 1408},
            {"id": "stacked_equal"},
            1,
            ["15377029700"],
            library,
            set(),
        )

        self.assertEqual(
            record["cover_template_version"],
            "road_rescue_storefront_mobile_v2",
        )
        self.assertEqual(
            record["scene"]["cover_template_version"],
            "road_rescue_storefront_mobile_v2",
        )

    def test_compact_footer_has_two_rows_uniform_legible_type_and_rotating_palette(self) -> None:
        items = ["汽车救援", "搭电救援", "拖车服务", "补胎换胎", "送油救援", "困境救援", "地库救援", "车辆救援", "高速救援", "城市路救援"]
        from PIL import ImageDraw

        styles = [category_image_production.road_rescue_bottom_service_style(1089)]
        self.assertEqual(styles[0]["style_id"], "compact-v2__porcelain_red__short_rule")
        self.assertTrue(all(style["layout"] == "compact_five_by_two" for style in styles))
        self.assertTrue(all(style["background"][3] == 255 for style in styles))
        for height in (1408, 1472, 1536):
            boxes = category_image_production._cover_service_boxes(1024, height, "compact_five_by_two", 10)
            self.assertEqual(len(boxes), 10)
            self.assertEqual(len({box[1] for box in boxes}), 2)
            draw = ImageDraw.Draw(Image.new("RGB", (1024, height)))
            fonts = [category_image_production._fit_font(draw, item, int((box[2] - box[0]) * .91), int(1024 * .034), min_size=15) for item, box in zip(items, boxes)]
            font = min(fonts, key=lambda item: item.size)
            self.assertGreaterEqual(font.size, 30)
            for item, box in zip(items, boxes):
                bounds = draw.textbbox((0, 0), item, font=font)
                self.assertLessEqual(bounds[2] - bounds[0], (box[2] - box[0]) * .91)
                self.assertLess(bounds[3] - bounds[1], box[3] - box[1])
            with tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / "raw.png"
                target = Path(temporary) / "cover.png"
                background = (83, 117, 149)
                Image.new("RGB", (1024, height), background).save(source)
                validation = category_image_production.apply_overlays(source, target, "15795643941", "cover", 1089, 1, items, f"1024x{height}", category_id="road_rescue")
                self.assertEqual(validation["overlay_style"]["version"], 10)
                self.assertEqual(validation["overlay_style"]["bottom_service_style"]["version"], 2)
                self.assertEqual(validation["expected_text"][1:11], items)
                with Image.open(target) as rendered:
                    self.assertEqual(rendered.convert("RGB").getpixel((512, int(height * .82))), background)
                    self.assertEqual(rendered.convert("RGB").getpixel((0, height - 1)), styles[0]["background"][:3])


if __name__ == "__main__":
    unittest.main()
