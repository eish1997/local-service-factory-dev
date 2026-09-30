from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tools import category_image_production as production
from tools.prompt_engine import CategoryPromptError


ROOT = Path(__file__).resolve().parents[1]
BATCH = (
    ROOT
    / "prompts"
    / "category_batches"
    / "road_rescue"
    / "batch_v3_5_active"
)
OUTPUT = ROOT / "output" / "road_rescue"
PHONE = "15377029700"
CONFIG = {
    "provider": "official",
    "base_url": "",
    "model": "gpt-image-2",
    "quality": "medium",
    "api_size": "1024x1536",
}


class CategorySingleTargetProbeTests(unittest.TestCase):
    def probe_plan(self, target_id: str) -> dict:
        with (
            patch.object(production, "reusable_target", return_value=False),
            patch.object(production, "valid_png", return_value=False),
            patch.object(production, "target_review_status", return_value=None),
        ):
            return production.plan(
                "road_rescue",
                BATCH,
                316,
                3,
                PHONE,
                CONFIG,
                scope="details",
                output_root=OUTPUT,
                generation_target_id=target_id,
            )

    def test_probe_plan_binds_exactly_one_missing_standalone_detail(self) -> None:
        target_id = "road_rescue:v3:g0316:u07"
        run_plan = self.probe_plan(target_id)

        self.assertEqual(run_plan["generation_target_id"], target_id)
        self.assertEqual(run_plan["generation_target_ids"], [target_id])
        self.assertEqual(run_plan["pending_generation_target_ids"], [target_id])
        self.assertEqual(run_plan["pending_api_requests"], 1)
        self.assertEqual(run_plan["pending_delivery_count"], 1)
        self.assertEqual(run_plan["delivery_target_ids"], ["road_rescue:v3:g0316:d05"])

    def test_probe_rejects_triptych_component(self) -> None:
        with self.assertRaisesRegex(CategoryPromptError, "不能选择首图或三拼组件"):
            self.probe_plan("road_rescue:v3:g0316:u02")

    def test_probe_rejects_target_outside_selected_groups(self) -> None:
        with self.assertRaisesRegex(CategoryPromptError, "不在当前组范围内"):
            self.probe_plan("road_rescue:v3:g0319:u07")


if __name__ == "__main__":
    unittest.main()
