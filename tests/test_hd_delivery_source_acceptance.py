from __future__ import annotations

import json
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image

import factory
from tests.test_category_source_size_acceptance import png, rejected_fixture
from tools import category_4k_raw as adapter
from tools import category_generation_profile as profiles
from tools import category_image_production as production
from tools import category_image_resume as ledger
from tools import category_source_size_acceptance as acceptance
from tools import image_download_receipts as receipts


POLICY = adapter.HD_DELIVERY_SOURCE_POLICY


def road_contract():
    profile = profiles.select_profile(
        {"provider": "relay", "base_url": "https://tinysnow.one/v1", "model": "gpt-image-2.5-flare",
         "quality": "medium", "api_size": "1024x1536"},
        "road_rescue", profiles.TINYSNOW_4K_DUAL_SOURCE)["generation_profile"]
    license_data = {
        "schema_version": 3, "production_schema_version": 3, "category_id": "road_rescue",
        "structure_version": "road_rescue_v3_1cover_1triptych_3details",
        "generation_mode": "independent_triptych_panels", "phone_sent_to_model": True,
        "scope": "all", "group_start": 1140, "group_count": 1, "generation_profile": profile,
        **{key: profile[key] for key in ("provider", "base_url", "model", "quality")},
        "size": profile["api_size"], "api_key_slots": list(range(1, 11)), "max_workers": 10,
        "concurrency_policy": "adaptive_ramp_v1", "sdk_max_retries": 0,
    }
    overlay = {
        "schema_version": 4, "production_schema_version": 3,
        "signboard_overlay_scope": "model_generated_physical_signboard_phone",
        "cover_signboard_region_mode": "source_generated_physical_signboard_phone",
        "cover_overlay_style": "source-generated-signboard-phone_no-local-signboard-overlay_rotating-high-contrast-typography",
        "signboard_title": None, "signboard_service_items": [], "cover_signboard_region": None,
        "signboard_overlay_enabled": False,
    }
    return license_data, overlay


class HdDeliverySourceAcceptanceTests(unittest.TestCase):
    def test_road_resume_keeps_its_own_phone_and_layout_contract(self):
        license_data, overlay = road_contract()
        ledger._validate_phone_mode(license_data, overlay)
        profile = license_data["generation_profile"]
        row = {"generation_kind": "cover", "group_index": 1140,
               "generation_profile": profile, "raw_api_size": "1024x1536"}
        with patch.object(ledger.truck_cover_typography, "cover_plan",
                          side_effect=AssertionError("road must not use truck typography")):
            result = ledger._profile_resume_bindings(license_data, {"generation_profile": profile}, [row], overlay, [])
        self.assertEqual(result["profile_max_workers"], 10)
        self.assertEqual(result["generation_profile"]["category_id"], "road_rescue")
        for key, value in (("structure_version", "truck_rescue_v3_1cover_1triptych_3details"),
                           ("category_id", "home_appliance_repair")):
            broken = deepcopy(license_data)
            broken[key] = value
            with self.assertRaises(ledger.ResumePlanError):
                ledger._validate_phone_mode(broken, overlay)
        for key, value in (("signboard_overlay_enabled", True),
                           ("cover_overlay_style", "truck-cover-v3-full-per-group-plan")):
            with self.assertRaises(ledger.ResumePlanError):
                ledger._validate_phone_mode(license_data, {**overlay, key: value})

    def test_road_mobile_phone_instruction_is_exact_and_not_shared_with_truck(self):
        phone = "19986904047"
        row = {"schema_version": 3, "overlay_schema_version": 4, "category_id": "road_rescue",
               "generation_kind": "cover", "role": "cover", "source_positive_prompt": "real storefront",
               "negative_prompt": "no incorrect phone", "effective_prompt": (
                   f"门头实体板面内只使用确认号码“{phone}”，号码完整清楚地处于原图上方百分之四十以内，"
                   "中部百分之五十至六十是后期电话条区域，两处不能重叠。")}
        ledger._validate_model_phone_prompt(row, phone, 1)
        for change in ({"category_id": "truck_rescue"}, {"effective_prompt": phone},
                       {"effective_prompt": row["effective_prompt"].replace(phone, "15377029700")},
                       {"generation_kind": "detail", "role": "detail"}):
            with self.assertRaises(ledger.ResumePlanError):
                ledger._validate_model_phone_prompt({**row, **change}, phone, 1)

    def test_clear_delivery_sized_sources_are_accepted_with_honest_dimensions(self):
        for size in ((1025, 1534), (1024, 1536), (1264, 1920), (2352, 3520)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                payload = png(size)
                result = adapter.save_4k_raw_png(root / "raw.png", payload,
                    archive_root=root / "originals", credential_epoch=None,
                    generation={"model": "gpt-image-2-4k", "quality": "medium", "api_size": "2560x3840"},
                    source_size_policy=POLICY)
                self.assertEqual(result["source_size_policy"], POLICY)
                self.assertEqual(result["source_returned_size"], f"{size[0]}x{size[1]}")
                self.assertEqual(Path(result["provider_original"]).read_bytes(), payload)
                self.assertFalse(result["source_is_upscaled_by_factory"])
                self.assertEqual(result["working_raw_is_upscaled"], max(1024 / size[0], 1536 / size[1]) > 1)
                with Image.open(root / "raw.png") as image:
                    self.assertEqual(image.size, (1024, 1536))

    def test_hd_policy_rejects_thumbnails_landscape_and_corrupt_images(self):
        for payload in (png((128, 192)), png((999, 1500)), png((1000, 1399)),
                        png((1536, 1024)), png((1000, 2000)), b"invalid"):
            with self.assertRaises(production.RawImageContractError):
                adapter.prepare_source_size_raw(payload, source_size_policy=POLICY)
        # The separately authorized older policy is unchanged.
        _, metadata = adapter.prepare_source_size_raw(png((128, 192)))
        self.assertEqual(metadata["source_size_policy"], adapter.DECODABLE_SOURCE_POLICY)

    def test_legacy_size_error_recovers_without_rewriting_paid_ledger(self):
        with rejected_fixture() as item:
            events = ledger._load_jsonl(item.events_path, "fixture events")
            failed = next(event for event in events if event.get("request_number") == 8 and event["status"] == "request_failed")
            failed.update(error_kind="image_download_failed",
                          error="error_type=RawImageContractError; error_kind=image_download_failed")
            failed.pop("archive_status")
            item.events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
            prefix = item.events_path.read_bytes()
            unchanged = {path: path.read_bytes() for path in (item.job_path, item.license_path, item.source, item.rejected_metadata)}
            result = acceptance.accept_source_sizes(item.batch, item.job_path, item.license_path,
                                                     confirm=True, policy_id=POLICY)
            self.assertEqual((result["request_delta"], result["recovered_count"], result["requests_used"]), (0, 1, 9))
            self.assertEqual(result["policy_id"], POLICY)
            self.assertTrue(item.events_path.read_bytes().startswith(prefix))
            for path, content in unchanged.items():
                self.assertEqual(path.read_bytes(), content)
            receipts.assert_no_pending_for_job(item.context["root"], item.job["job_id"])
            plan = ledger.build_resume_plan(item.batch, item.job_path, item.license_path)
            self.assertEqual(plan["source_size_acceptance"]["policy_id"], POLICY)
            self.assertIn(item.context["generation_target_id"], plan["success_ids"])
            self.assertNotIn(item.context["generation_target_id"], plan["resumable_ids"])
            self.assertEqual(acceptance.accept_source_sizes(item.batch, item.job_path, item.license_path,
                                                           confirm=True, policy_id=POLICY), result)
            with self.assertRaises(ledger.ResumePlanError):
                acceptance.accept_source_sizes(item.batch, item.job_path, item.license_path, confirm=True)

    def test_download_failures_without_proven_archived_size_rejection_do_not_match(self):
        base = {"status": "request_failed", "will_retry": False, "error_kind": "image_download_failed"}
        self.assertFalse(acceptance._is_archived_size_rejection(base))
        self.assertFalse(acceptance._is_archived_size_rejection({**base, "error": "error_type=TimeoutError;"}))
        self.assertFalse(acceptance._is_archived_size_rejection({**base, "error": "error_type=RawImageContractError;"}))

    def test_cli_policy_is_explicit_and_does_not_change_the_old_default(self):
        command = ["accept-category-source-sizes", "--category", "road_rescue", "--job-id", "fixture", "--confirm"]
        self.assertEqual(factory.build_parser().parse_args(command).source_policy, "decodable")
        self.assertEqual(factory.build_parser().parse_args(command + ["--source-policy", "hd-delivery"]).source_policy, "hd-delivery")


if __name__ == "__main__":
    unittest.main()
