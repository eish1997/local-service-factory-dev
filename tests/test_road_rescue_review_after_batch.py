from __future__ import annotations

import unittest
from unittest.mock import patch

import factory
from tests.test_category_single_target_probe import BATCH, CONFIG, OUTPUT, PHONE
from tools import category_image_production as production


class RoadRescueReviewAfterBatchTests(unittest.TestCase):
    def test_triptych_all_scope_generates_full_batch_before_review(self) -> None:
        for category in ("road_rescue", "pipe_unclogging", "truck_rescue", "ktv"):
            with self.subTest(category=category):
                factory._category_require_executable_scope(
                    "all", "independent_triptych_panels", category_id=category
                )
        self.assertFalse(factory._category_scope_requires_cover_approval("all"))
        self.assertTrue(factory._category_scope_requires_cover_approval("details"))

    def test_legacy_review_flag_is_all_scope_only(self) -> None:
        factory._category_require_executable_scope(
            "all", "independent_triptych_panels", category_id="road_rescue", review_after_batch=True
        )
        for scope in ("details", "covers"):
            with self.assertRaises(RuntimeError):
                factory._category_require_executable_scope(
                    scope, "independent_triptych_panels", category_id="road_rescue", review_after_batch=True
                )
        factory._category_require_executable_scope("all", "independent_delivery_images")

    def test_all_plan_contains_cover_triptych_and_details_with_exact_budget(self) -> None:
        with (
            patch.object(production, "reusable_target", return_value=False),
            patch.object(production, "valid_png", return_value=False),
            patch.object(production, "target_review_status", return_value=None),
        ):
            plan = production.plan("road_rescue", BATCH, 316, 1, PHONE, CONFIG, scope="all", output_root=OUTPUT)
        self.assertEqual(plan["pending_api_requests"], 7)
        self.assertEqual(plan["pending_delivery_count"], 5)
        self.assertEqual(len(plan["pending_generation_target_ids"]), 7)
        self.assertEqual({entry["generation_kind"] for entry in plan["manifest_entries"]}, {"cover", "triptych_panel", "detail"})
        self.assertTrue(all(entry["status"] == "pending" for entry in plan["manifest_entries"]))


if __name__ == "__main__":
    unittest.main()
