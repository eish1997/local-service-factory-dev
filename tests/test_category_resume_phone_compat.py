from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tests.test_category_image_resume import PHONE, ResumeFixture, json_sha
from tools import category_image_resume


class ModelPhoneFixture(ResumeFixture):
    """Small frozen-v3 fixture; no production config or API is loaded."""

    def __init__(self, root: Path, *, covers_only: bool = False) -> None:
        self.covers_only = covers_only
        super().__init__(root)

    def _rows(self) -> list[dict]:
        rows = super()._rows()[: 1 if self.covers_only else 2]
        for row in rows:
            row["role"] = row["generation_kind"]
            row["overlay_schema_version"] = 4
        cover = rows[0]
        cover.update(
            generation_kind="cover",
            role="cover",
            position=1,
            generation_position=1,
            delivery_position=1,
            generation_target_id="truck_rescue:v3:g0044:u01",
            target_id="truck_rescue:v3:g0044:u01",
            delivery_target_id="truck_rescue:v3:g0044:d01",
        )
        cover["effective_prompt"] += (
            "门头联系电话必须由图像模型作为真实实体招牌排版的一部分自然生成，"
            f"号码必须清楚准确写成“{PHONE}”"
        )
        cover["effective_prompt_sha256"] = hashlib.sha256(
            cover["effective_prompt"].encode("utf-8")
        ).hexdigest()
        return rows

    def _legacy_events(self) -> list[dict]:
        events = []
        for index, row in enumerate(self.rows):
            events.append(
                {
                    "status": "request_reserved",
                    **self._identity(index),
                    "raw_target": row["raw_target"],
                    "delivery_target": row["target"],
                    "attempt": 1,
                    "request_number": index + 1,
                }
            )
            if index == 0:
                events.append({**self._generated(index), "request_number": 1})
        return events

    def _license(self) -> dict:
        self.group_recipes = self.group_recipes[:1]
        result = super()._license()
        result.update(
            group_count=1,
            scope="covers" if self.covers_only else "all",
            phone_sent_to_model=True,
            approved_api_request_count=len(self.rows),
            approved_request_budget=len(self.rows) * 2,
            requests_used=len(self.rows),
        )
        return result

    def _job(self) -> dict:
        result = super()._job()
        result.update(
            group_count=1,
            scope="covers" if self.covers_only else "all",
            requests_used=len(self.rows),
        )
        return result

    def _overlay(self) -> dict:
        result = super()._overlay()
        result.update(
            schema_version=4,
            production_schema_version=3,
            scope="covers" if self.covers_only else "all",
            signboard_overlay_enabled=False,
            signboard_overlay_scope="model_generated_physical_signboard_phone",
            cover_signboard_region_mode="source_generated_physical_signboard_phone",
            cover_overlay_style=(
                "source-generated-signboard-phone_no-local-signboard-overlay_"
                "rotating-high-contrast-typography"
            ),
            signboard_title=None,
            signboard_service_items=[],
            cover_signboard_region=None,
        )
        return result

    def rebind_prompt_hashes(self) -> None:
        for row in self.rows:
            row["effective_prompt_sha256"] = hashlib.sha256(
                row["effective_prompt"].encode("utf-8")
            ).hexdigest()
        self.license["manifest_sha256"] = json_sha(self.rows)
        self.write()


class CategoryResumePhoneCompatTests(unittest.TestCase):
    def test_current_all_mode_is_readonly_and_preserves_raw_and_unknown_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ModelPhoneFixture(Path(temporary))
            paths = (
                fixture.manifest_path,
                fixture.overlay_path,
                fixture.license_path,
                fixture.job_path,
                fixture.events_path,
            )
            before = {path: path.read_bytes() for path in paths}
            first = fixture.plan()
            self.assertEqual(first, fixture.plan())
            self.assertEqual(before, {path: path.read_bytes() for path in paths})
            self.assertEqual(first["success_ids"], fixture.target_ids[:1])
            self.assertEqual(first["unknown_ids"], fixture.target_ids[1:])
            self.assertEqual(first["resumable_ids"], fixture.target_ids[1:])
            self.assertEqual(first["requests_used"], 2)
            self.assertEqual(first["remaining_max_requests"], 1)
            self.assertEqual(first["budget"], 4)
            self.assertEqual(
                first["frozen_manifest_sha256"],
                hashlib.sha256(before[fixture.manifest_path]).hexdigest(),
            )

    def test_current_covers_mode_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ModelPhoneFixture(Path(temporary), covers_only=True)
            self.assertEqual(fixture.plan()["counts"]["success"], 1)

    def test_false_mode_still_rejects_phone_in_each_prompt_field(self) -> None:
        for field in ("effective_prompt", "source_positive_prompt", "negative_prompt"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                fixture.license["phone_sent_to_model"] = False
                fixture.rows[0]["effective_prompt"] = "phone-free frozen prompt"
                fixture.rows[0][field] += PHONE
                fixture.rebind_prompt_hashes()
                with self.assertRaisesRegex(category_image_resume.ResumePlanError, "phone_sent_to_model=false"):
                    fixture.plan()

    def test_unknown_boolean_mode_is_rejected(self) -> None:
        for value in (None, "true", 1, 0):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                fixture.license["phone_sent_to_model"] = value
                fixture.write()
                with self.assertRaisesRegex(category_image_resume.ResumePlanError, "明确布尔值"):
                    fixture.plan()

    def test_unverified_license_version_category_and_scope_are_rejected(self) -> None:
        for key, value in (
            ("schema_version", 2),
            ("production_schema_version", 4),
            ("category_id", "road_rescue"),
            ("structure_version", "truck_rescue_v4"),
            ("generation_mode", "unknown"),
            ("scope", "details"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                fixture.license[key] = value
                if key in fixture.job:
                    fixture.job[key] = value
                if key in fixture.overlay and key != "schema_version":
                    fixture.overlay[key] = value
                if key == "category_id":
                    fixture.job["project_id"] = value
                fixture.write()
                with self.assertRaises(category_image_resume.ResumePlanError):
                    fixture.plan()

    def test_overlay_mode_and_phone_bindings_fail_closed(self) -> None:
        for key, value in (
            ("schema_version", 3),
            ("production_schema_version", 4),
            ("signboard_overlay_enabled", True),
            ("signboard_overlay_scope", "title_services_and_phone"),
            ("cover_signboard_region_mode", "unknown"),
            ("cover_overlay_style", "unknown"),
            ("signboard_title", "local title"),
            ("signboard_service_items", ["local service"]),
            ("cover_signboard_region", [0, 0, 1, 1]),
            ("phone", "13437186038"),
            ("center_phone_text", "wrong"),
            ("signboard_phone_text", "wrong"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                fixture.overlay[key] = value
                fixture.write()
                with self.assertRaises(category_image_resume.ResumePlanError):
                    fixture.plan()

    def test_missing_explicit_overlay_mode_fields_fail_closed(self) -> None:
        for key in ("signboard_title", "cover_signboard_region", "signboard_overlay_enabled"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                fixture.overlay.pop(key)
                fixture.write()
                with self.assertRaises(category_image_resume.ResumePlanError):
                    fixture.plan()

    def test_wrong_missing_extra_or_noncover_contact_is_rejected(self) -> None:
        for index, replacement in (
            (0, "no contact"),
            (0, "13437186038"),
            (0, f"{PHONE} 400-123-4567"),
            (1, PHONE),
        ):
            with self.subTest(index=index, replacement=replacement), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                fixture.rows[index]["effective_prompt"] = replacement
                fixture.rebind_prompt_hashes()
                with self.assertRaises(category_image_resume.ResumePlanError):
                    fixture.plan()

    def test_confirmed_phone_without_signboard_instruction_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ModelPhoneFixture(Path(temporary))
            fixture.rows[0]["effective_prompt"] = f"center phone {PHONE}"
            fixture.rebind_prompt_hashes()
            with self.assertRaisesRegex(category_image_resume.ResumePlanError, "实体招牌号码指令"):
                fixture.plan()

    def test_source_or_negative_contact_cannot_masquerade_as_injection(self) -> None:
        for field in ("source_positive_prompt", "negative_prompt"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                fixture.rows[0][field] += PHONE
                fixture.rebind_prompt_hashes()
                with self.assertRaisesRegex(category_image_resume.ResumePlanError, field):
                    fixture.plan()

    def test_missing_source_or_negative_prompt_is_rejected(self) -> None:
        for field in ("source_positive_prompt", "negative_prompt"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                fixture.rows[0].pop(field)
                fixture.rebind_prompt_hashes()
                with self.assertRaisesRegex(category_image_resume.ResumePlanError, field):
                    fixture.plan()

    def test_cover_scope_and_actual_cover_presence_are_required(self) -> None:
        for mutation in ("cover_scope_with_details", "no_covers", "unknown_kind"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                if mutation == "cover_scope_with_details":
                    for payload in (fixture.license, fixture.job, fixture.overlay):
                        payload["scope"] = "covers"
                else:
                    kind = "detail" if mutation == "no_covers" else "unknown"
                    fixture.rows[0].update(
                        generation_kind=kind, role=kind, effective_prompt="no phone"
                    )
                fixture.rebind_prompt_hashes()
                with self.assertRaises(category_image_resume.ResumePlanError):
                    fixture.plan()

    def test_row_version_role_and_confirmed_phone_are_bound(self) -> None:
        for key, value in (
            ("schema_version", 2),
            ("overlay_schema_version", 3),
            ("role", "detail"),
            ("confirmed_phone", "13437186038"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                fixture.rows[0][key] = value
                fixture.rebind_prompt_hashes()
                with self.assertRaises(category_image_resume.ResumePlanError):
                    fixture.plan()

    def test_manifest_content_and_order_still_require_original_bindings(self) -> None:
        for mutation in ("content", "order"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                fixture = ModelPhoneFixture(Path(temporary))
                if mutation == "content":
                    fixture.rows[1]["source_positive_prompt"] += " changed"
                else:
                    fixture.rows.reverse()
                    fixture.license["manifest_sha256"] = json_sha(fixture.rows)
                fixture.write()
                with self.assertRaises(category_image_resume.ResumePlanError):
                    fixture.plan()

    def test_generated_raw_hash_still_rejects_changed_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ModelPhoneFixture(Path(temporary))
            (fixture.batch / fixture.rows[0]["raw_target"]).write_bytes(b"modified")
            with self.assertRaisesRegex(category_image_resume.ResumePlanError, "成功原图哈希不一致"):
                fixture.plan()


if __name__ == "__main__":
    unittest.main()
