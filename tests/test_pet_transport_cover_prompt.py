from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import factory
import generate_pet_transport_groups
from tools import category_image_production
from tools.prompt_engine import CategoryPromptError


class PetTransportCoverPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parent.parent
        prompt_path = (
            root
            / "prompts/category_batches/pet_transport"
            / "batch_v1_1plus5_10groups/prompts.jsonl"
        )
        cls.rows = [
            json.loads(line)
            for line in prompt_path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]

    def test_cover_reuses_road_rescue_real_storefront_style(self) -> None:
        record = next(row for row in self.rows if row["generation_kind"] == "cover")

        prompt = category_image_production.effective_prompt(record, "18271918609")

        self.assertNotIn("?", prompt)
        self.assertIn("门店外景全景", prompt)
        self.assertIn("与真实中国汽车救援门店工作记录照一致", prompt)
        self.assertIn("只把汽车救援业务元素替换为宠物托运业务元素", prompt)
        self.assertIn("完整拍到主招牌、店门或卷帘门、门店一层外立面", prompt)
        self.assertIn("猫狗只作为真实交接现场中的次要服务对象", prompt)
        self.assertIn("绝不允许卡通化、动漫化", prompt)
        self.assertIn("联系电话：18271918609", prompt)
        self.assertIn("猫咪托运 · 狗狗托运 · 上门接送 · 照护交接", prompt)
        self.assertNotIn("管道疏通", prompt)

    def test_all_cover_prompts_keep_real_style_but_vary_scene_axes(self) -> None:
        covers = [row for row in self.rows if row["generation_kind"] == "cover"]
        prompts = [
            category_image_production.effective_prompt(row, "18271918609")
            for row in covers
        ]

        self.assertEqual(len(covers), 30)
        self.assertEqual(len(set(prompts)), 30)
        self.assertTrue(all("门店外景全景" in prompt for prompt in prompts))
        self.assertTrue(all("严格排除：卡通、动漫、漫画、插画" in prompt for prompt in prompts))

    def test_cover_rejects_unconfirmed_phone_before_rebuilding_prompt(self) -> None:
        record = next(row for row in self.rows if row["generation_kind"] == "cover")
        record = {**record, "prompt": "写实宠物托运门店，门头电话13800138000。"}

        with self.assertRaises(CategoryPromptError):
            category_image_production.effective_prompt(record, "18271918609")

    def test_detail_also_forbids_cartoon_or_anime_style(self) -> None:
        record = next(row for row in self.rows if row["generation_kind"] == "detail")

        prompt = category_image_production.effective_prompt(record, "18271918609")

        self.assertIn("宠物托运全局写实硬规则", prompt)
        self.assertIn("普通手机拍摄的真实工作记录", prompt)
        self.assertIn("绝不允许卡通、动漫、漫画、插画", prompt)
        self.assertNotIn("18271918609", prompt)

    def test_detail_overlay_uses_unique_pet_keywords_in_road_rescue_grid(self) -> None:
        first = {
            "category_id": "pet_transport",
            "generation_kind": "detail",
            "service_role": "笼具检查",
            "group_index": 11,
            "delivery_position": 2,
        }
        second = {**first, "group_index": 12, "delivery_position": 3}
        base_items = [
            "猫咪托运",
            "狗狗托运",
            "宠物托运",
            "上门接送",
            "照护交接",
            "笼具检查",
            "安全装车",
            "到达交接",
        ]

        first_items = category_image_production._record_overlay_service_items(
            first, base_items
        )
        second_items = category_image_production._record_overlay_service_items(
            second, base_items
        )

        self.assertEqual(len(first_items), 10)
        self.assertEqual(len(set(first_items)), 10)
        self.assertNotIn("笼具检查", first_items)
        self.assertNotEqual(first_items, second_items)
        self.assertTrue(all("救援" not in item and "拖车" not in item for item in first_items))

    def test_all_scope_is_available_without_prior_cover_range_approval(self) -> None:
        self.assertFalse(factory._category_scope_requires_cover_approval("covers"))
        self.assertFalse(factory._category_scope_requires_cover_approval("all"))
        self.assertTrue(factory._category_scope_requires_cover_approval("details"))
        args = factory.build_parser().parse_args([
            "confirm-start-category-images",
            "--category", "pet_transport",
            "--group-start", "11",
            "--group-count", "20",
            "--scope", "all",
            "--plan-sha256", "test-plan",
            "--max-requests", "120",
        ])
        self.assertEqual(args.scope, "all")

    def test_extended_detail_prompt_reserves_ten_pet_keyword_grid(self) -> None:
        prompt = generate_pet_transport_groups._detail_prompt(
            11, 2, "接宠交接"
        )

        self.assertIn("两行十宫格宠物托运服务词", prompt)
        self.assertIn("普通手机拍摄的工作记录", prompt)
        self.assertNotIn("18271918609", prompt)
        self.assertIn("道路救援业务元素", prompt)

    def test_pet_cover_style_version_is_incremented(self) -> None:
        self.assertEqual(category_image_production.cover_style_version("pet_transport"), 3)

    def test_cover_signboards_vary_beyond_white_without_copying_reference(self) -> None:
        covers = [row for row in self.rows if row["generation_kind"] == "cover"]
        prompts = [
            category_image_production.effective_prompt(row, "18271918609")
            for row in covers
        ]

        self.assertTrue(all("门头底色不固定为白色" in prompt for prompt in prompts))
        for expected_color in ("暖棕色", "深灰蓝", "暖灰色", "克制砖红色", "柔和米白色"):
            self.assertTrue(any(expected_color in prompt for prompt in prompts))
        self.assertIn("暖棕色", prompts[1])
        self.assertIn("深灰蓝", prompts[2])
        self.assertIn("暖灰色", prompts[3])
        self.assertIn("克制砖红色", prompts[4])
        self.assertIn("柔和米白色", prompts[5])
        self.assertTrue(all("立体发光字" in prompt for prompt in prompts))
        self.assertTrue(all("萌宠驾到" not in prompt for prompt in prompts))
        self.assertTrue(all("手机状态栏" in prompt for prompt in prompts))

    def test_approved_signboard_density_rule_is_used_by_batch_prompts(self) -> None:
        record = next(row for row in self.rows if row["generation_kind"] == "cover")

        prompt = category_image_production.effective_prompt(record, "18271918609")

        self.assertIn("项目已批准的长期门头规则", prompt)
        self.assertIn("信息密度与横向占用", prompt)

    def test_single_group_tuning_draft_is_injected_only_into_bound_cover(self) -> None:
        covers = [row for row in self.rows if row["generation_kind"] == "cover"]
        draft = {
            "project_id": "pet_transport",
            "role": "cover",
            "dimension": "年代感",
            "action": "strengthen",
            "note": "主要呈现2022-2026年维护良好的较新社区底商，通透玻璃门窗和干净哑光招牌。",
            "status": "active",
        }
        environment = {
            category_image_production.TUNING_SAMPLE_PROJECT_ENV: "pet_transport",
            category_image_production.TUNING_SAMPLE_GROUP_ENV: "1",
        }

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                category_image_production,
                "_load_active_tuning_sample_drafts",
                return_value=[draft],
            ),
        ):
            first = category_image_production.effective_prompt(covers[0], "18271918609")
            second = category_image_production.effective_prompt(covers[1], "18271918609")

        self.assertIn("本次单张调优样片覆盖规则", first)
        self.assertIn("2022-2026年维护良好的较新社区底商", first)
        self.assertNotIn("本次单张调优样片覆盖规则", second)

    def test_tuning_draft_scope_rejects_multiple_groups_or_details(self) -> None:
        environment = {
            category_image_production.TUNING_SAMPLE_PROJECT_ENV: "pet_transport",
            category_image_production.TUNING_SAMPLE_GROUP_ENV: "1",
        }
        with patch.dict(os.environ, environment, clear=False):
            category_image_production._validate_tuning_sample_scope(
                "pet_transport", 1, 1, "covers"
            )
            with self.assertRaises(CategoryPromptError):
                category_image_production._validate_tuning_sample_scope(
                    "pet_transport", 1, 2, "covers"
                )
            with self.assertRaises(CategoryPromptError):
                category_image_production._validate_tuning_sample_scope(
                    "pet_transport", 1, 1, "details"
                )


if __name__ == "__main__":
    unittest.main()
