from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import factory
from tools import category_image_production


class PipeSignboardOverlayV3Tests(unittest.TestCase):
    def test_prompt_demands_blank_matte_physical_signboard(self) -> None:
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

    def test_text_is_warped_onto_board_without_colored_panel(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "raw.png"
            target = root / "cover.png"
            image = Image.new("RGB", (1024, 1536), (156, 156, 156))
            board = [(85, 90), (950, 150), (925, 390), (70, 325)]
            ImageDraw.Draw(image).polygon(board, fill=(32, 118, 77))
            untouched = image.getpixel((115, 125))
            image.save(source)

            validation = category_image_production.apply_overlays(
                source,
                target,
                "13317112954",
                "cover",
                1,
                1,
                [
                    "厨房疏通",
                    "马桶疏通",
                    "地漏疏通",
                    "主管道疏通",
                    "高压清洗",
                    "内窥检测",
                    "抽粪清淤",
                    "后厨油污",
                ],
                category_id="pipe_unclogging",
            )

            style = validation["overlay_style"]
            self.assertEqual(style["version"], 3)
            self.assertEqual(
                style["signboard_style"],
                "direct_text_on_detected_physical_signboard",
            )
            self.assertEqual(style["signboard_detection"], "upper_color_component")
            self.assertEqual(len(style["signboard_quad"]), 4)
            with Image.open(target) as rendered:
                self.assertEqual(rendered.convert("RGB").getpixel((115, 125)), untouched)

    def test_local_rebuild_command_is_explicit_and_paid_free(self) -> None:
        parser = factory.build_parser()
        args = parser.parse_args(
            [
                "rebuild-category-covers",
                "--category",
                "pipe_unclogging",
                "--reason",
                "用户拒绝旧门头底板",
                "--confirm-rejected",
            ]
        )
        self.assertIs(args.handler, factory.command_rebuild_category_covers)
        self.assertTrue(args.confirm_rejected)


if __name__ == "__main__":
    unittest.main()
