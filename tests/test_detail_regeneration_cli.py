from __future__ import annotations

import argparse
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import factory


class DetailRegenerationCliTests(unittest.TestCase):
    def args(self, **changes):
        values = dict(category="truck_rescue", batch_dir=None, group_start=242,
                      group_count=1, generation_target_id="truck_rescue:v3:g0242:u05",
                      phone="13437186038", reason="用户要求替换疑似相似详情", confirm_rejected=True)
        values.update(changes)
        return argparse.Namespace(**values)

    def test_requires_explicit_replacement_confirmation(self):
        with patch.object(factory, "_category_image_error", return_value=1), \
                patch.object(factory, "_category_sample_range") as sample:
            self.assertEqual(factory.command_prepare_category_detail_regeneration(
                self.args(confirm_rejected=False)), 1)
            sample.assert_not_called()

    def test_rejects_multiple_groups_before_preparing(self):
        with patch.object(factory, "_category_image_error", return_value=1), \
                patch.object(factory, "_category_sample_range") as sample:
            self.assertEqual(factory.command_prepare_category_detail_regeneration(
                self.args(group_count=2)), 1)
            sample.assert_not_called()

    def test_public_parser_requires_target_and_defaults_to_one_group(self):
        args = factory.build_parser().parse_args([
            "prepare-category-detail-regeneration", "--category", "truck_rescue",
            "--group-start", "242", "--generation-target-id", "truck_rescue:v3:g0242:u05",
            "--phone", "13437186038", "--reason", "用户要求替换疑似相似详情", "--confirm-rejected",
        ])
        self.assertEqual(args.group_count, 1)
        self.assertIs(args.handler, factory.command_prepare_category_detail_regeneration)
        self.assertTrue(args.confirm_rejected)

    def test_forwards_only_exact_target_to_local_preparation(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(factory, "_category_sample_range"))
            stack.enter_context(patch.object(factory, "category_active_batch_dir", return_value=Path("batch")))
            stack.enter_context(patch.object(factory, "_category_confirmed_phone", return_value="13437186038"))
            stack.enter_context(patch.object(factory, "_category_effective_config", return_value={"model": "gpt-image-2"}))
            stack.enter_context(patch.object(factory, "_category_output_root", return_value=Path("output")))
            prepare = stack.enter_context(patch.object(factory.category_image_production,
                "prepare_detail_regeneration", return_value={"archive_root": "archive"}))
            stack.enter_context(patch("builtins.print"))
            self.assertEqual(factory.command_prepare_category_detail_regeneration(self.args()), 0)
            prepare.assert_called_once_with("truck_rescue", Path("batch"), 242, 1,
                "13437186038", {"model": "gpt-image-2"}, Path("output"),
                "用户要求替换疑似相似详情", "truck_rescue:v3:g0242:u05")


if __name__ == "__main__":
    unittest.main()
