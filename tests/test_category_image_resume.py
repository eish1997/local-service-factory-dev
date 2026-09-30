from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools import category_image_resume


PHONE = "13407128962"
MODEL = "gpt-image-2"
QUALITY = "medium"
SIZE = "1024x1536"
STRUCTURE = "truck_rescue_v3_1cover_1triptych_3details"
MODE = "independent_triptych_panels"


def json_sha(value: object) -> str:
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


class ResumeFixture:
    def __init__(self, root: Path, *, explicit_reservations: bool = False) -> None:
        self.batch = root / "truck_rescue" / "batch_resume_fixture"
        production = self.batch / "production"
        self.job_id = "job-fixture"
        self.license_id = "license-fixture"
        self.job_path = production / "jobs" / f"{self.job_id}.json"
        self.license_path = production / "licenses" / f"{self.license_id}.json"
        self.manifest_path = production / "manifests" / f"{self.license_id}.jsonl"
        self.overlay_path = production / "overlay_plans" / f"{self.license_id}.json"
        self.events_path = production / f"events_{self.job_id}.jsonl"
        self.batch.mkdir(parents=True)
        self.rows = self._rows()
        self.target_ids = [row["generation_target_id"] for row in self.rows]
        _, delivery_material = category_image_resume._delivery_material(self.rows)
        self.delivery_ids = [row["delivery_target_id"] for row in self.rows]
        self.generation_hash = category_image_resume._generation_target_hash(self.rows)
        self.delivery_hash = json_sha(delivery_material)
        self.group_recipes = [
            {
                "group_index": group,
                "height_profile_id": "height_1536",
                "final_sizes": [SIZE],
                "triptych_layout_id": None,
                "triptych_recipe": None,
            }
            for group in range(44, 144)
        ]
        self.events = self._legacy_events()
        if explicit_reservations:
            self.events = self._with_reservations(self.events)
        self.license = self._license()
        self.job = self._job()
        self.overlay = self._overlay()
        self.write()

    def _rows(self) -> list[dict]:
        rows: list[dict] = []
        for index in range(600):
            group = 44 + index // 6
            position = 2 + index % 6
            target_id = f"truck_rescue:v3:g{group:04d}:u{position:02d}"
            delivery_id = f"truck_rescue:v3:g{group:04d}:d{position:02d}"
            prompt = f"真实中国货车维修现场，测试冻结目标 {index + 1}。"
            rows.append(
                {
                    "schema_version": 3,
                    "structure_version": STRUCTURE,
                    "generation_mode": MODE,
                    "category_id": "truck_rescue",
                    "batch_id": "batch_resume_fixture",
                    "target_id": target_id,
                    "generation_target_id": target_id,
                    "delivery_target_id": delivery_id,
                    "group_index": group,
                    "position": position,
                    "generation_position": position,
                    "delivery_position": position,
                    "generation_kind": "detail",
                    "service_role": "货车维修",
                    "panel_index": None,
                    "height_profile_id": "height_1536",
                    "final_size": SIZE,
                    "triptych_layout_id": None,
                    "source_positive_prompt": prompt,
                    "negative_prompt": "测试排除项",
                    "effective_prompt": prompt,
                    "effective_prompt_sha256": hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest(),
                    "target": (
                        f"output/truck_rescue/group_{group:04d}/"
                        f"{position:02d}_detail.png"
                    ),
                    "raw_target": (
                        f"raw/group_{group:04d}/{position:02d}_detail.png"
                    ),
                    "model": MODEL,
                    "quality": QUALITY,
                    "size": SIZE,
                    "confirmed_phone": PHONE,
                    "status": "pending",
                }
            )
        return rows

    def _identity(self, index: int) -> dict:
        row = self.rows[index]
        return {
            "generation_target_id": row["generation_target_id"],
            "delivery_target_id": row["delivery_target_id"],
            "group_index": row["group_index"],
            "generation_position": row["generation_position"],
            "delivery_position": row["delivery_position"],
        }

    def _generated(self, index: int) -> dict:
        row = self.rows[index]
        raw = self.batch / row["raw_target"]
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(f"fixture-image-{index}".encode("ascii"))
        return {
            "status": "generated",
            **self._identity(index),
            "raw_target": row["raw_target"],
            "delivery_target": row["target"],
            "attempt": 1,
            "saved_raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        }

    def _failure(self, index: int, attempt: int) -> dict:
        return {
            "status": "request_failed",
            **self._identity(index),
            "attempt": attempt,
            "error_kind": "content_policy",
            "will_retry": attempt == 1,
        }

    def _stage(
        self, stage: int, phase: str, workers: int, failed: int, requests: int
    ) -> dict:
        return {
            "status": "concurrency_stage",
            "stage": stage,
            "phase": phase,
            "worker_count": workers,
            "request_count": workers,
            "failed_count": failed,
            "api_requests_used_total": requests,
            "retry_count_total": 0 if stage < 3 else 5,
        }

    def _legacy_events(self) -> list[dict]:
        # Completed prefix: probe(1), stage(4), stage(6).  The six-target
        # stage has one success and five targets exhausted after two attempts.
        events = [self._generated(0), self._stage(1, "probe", 1, 0, 1)]
        events.extend(self._generated(index) for index in range(1, 5))
        events.append(self._stage(2, "adaptive", 4, 0, 5))
        for index in (5, 6, 8, 9, 10):
            events.extend((self._failure(index, 1), self._failure(index, 2)))
        events.append(self._generated(7))
        events.append(self._stage(3, "adaptive", 6, 5, 16))
        # The next five-target stage was interrupted: index 13 exhausted while
        # 11, 12, 14 and 15 have paid reservations but no terminal events.
        events.extend((self._failure(13, 1), self._failure(13, 2)))
        return events

    def _with_reservations(self, events: list[dict]) -> list[dict]:
        result: list[dict] = []
        request_number = 0
        for event in events:
            if event["status"] in {"generated", "request_failed"}:
                request_number += 1
                row = self.rows[
                    self.target_ids.index(event["generation_target_id"])
                ]
                result.append(
                    {
                        "status": "request_reserved",
                        **self._identity(self.target_ids.index(event["generation_target_id"])),
                        "raw_target": row["raw_target"],
                        "delivery_target": row["target"],
                        "attempt": event["attempt"],
                        "request_number": request_number,
                    }
                )
                event = {**event, "request_number": request_number}
            result.append(event)
        for index in (11, 12, 14, 15):
            request_number += 1
            row = self.rows[index]
            result.append(
                {
                    "status": "request_reserved",
                    **self._identity(index),
                    "raw_target": row["raw_target"],
                    "delivery_target": row["target"],
                    "attempt": 1,
                    "request_number": request_number,
                }
            )
        self.assert_request_count = request_number
        return result

    def _license(self) -> dict:
        pending_generation_hash = json_sha(self.target_ids)
        pending_delivery_hash = json_sha(self.delivery_ids)
        return {
            "schema_version": 3,
            "production_schema_version": 3,
            "kind": "category-image-production",
            "license_id": self.license_id,
            "status": "consumed",
            "one_time": True,
            "consumed_at": "2026-08-12T09:14:33+00:00",
            "category_id": "truck_rescue",
            "batch_id": self.batch.name,
            "batch_dir": str(self.batch.resolve()),
            "group_start": 44,
            "group_count": 100,
            "scope": "details",
            "generation_target_id": None,
            "plan_sha256": "a" * 64,
            "structure_version": STRUCTURE,
            "generation_mode": MODE,
            "provider": "relay",
            "base_url": "https://example.invalid/v1",
            "third_party_confirmed": True,
            "model": MODEL,
            "quality": QUALITY,
            "size": SIZE,
            "phone": PHONE,
            "phone_sent_to_model": False,
            "contact_sha256": hashlib.sha256(PHONE.encode("utf-8")).hexdigest(),
            "production_manifest": str(self.manifest_path.resolve()),
            "overlay_plan": str(self.overlay_path.resolve()),
            "manifest_sha256": json_sha(self.rows),
            "generation_target_ids": self.target_ids,
            "approved_generation_target_ids": self.target_ids,
            "pending_generation_target_ids": self.target_ids,
            "generation_targets_sha256": self.generation_hash,
            "pending_generation_targets_sha256": pending_generation_hash,
            "delivery_target_ids": self.delivery_ids,
            "approved_delivery_target_ids": self.delivery_ids,
            "pending_delivery_target_ids": self.delivery_ids,
            "delivery_targets_sha256": self.delivery_hash,
            "pending_delivery_targets_sha256": pending_delivery_hash,
            "targets_sha256": self.delivery_hash,
            "approved_targets_sha256": pending_delivery_hash,
            "pending_targets_sha256": pending_delivery_hash,
            "group_recipes": self.group_recipes,
            "group_recipes_sha256": json_sha(self.group_recipes),
            "approved_api_request_count": 600,
            "approved_request_budget": 1200,
            "max_attempts": 2,
            "retry_policy": "classified_once_v1",
            "concurrency_policy": "adaptive_ramp_v1",
            "requests_used": 22,
        }

    def _job(self) -> dict:
        stages = [
            {key: value for key, value in event.items() if key != "status"}
            for event in self.events
            if event["status"] == "concurrency_stage"
        ]
        return {
            "schema_version": 2,
            "job_id": self.job_id,
            "license_id": self.license_id,
            "job_type": "category-batch-production",
            "category_id": "truck_rescue",
            "project_id": "truck_rescue",
            "batch_id": self.batch.name,
            "batch_dir": str(self.batch.resolve()),
            "status": "running",
            "group_start": 44,
            "group_count": 100,
            "scope": "details",
            "generation_target_id": None,
            "plan_sha256": "a" * 64,
            "structure_version": STRUCTURE,
            "generation_mode": MODE,
            "generation_targets_sha256": self.generation_hash,
            "delivery_targets_sha256": self.delivery_hash,
            "pending_generation_target_ids": self.target_ids,
            "pending_delivery_target_ids": self.delivery_ids,
            "model": MODEL,
            "quality": QUALITY,
            "size": SIZE,
            "max_attempts": 2,
            "retry_policy": "classified_once_v1",
            "concurrency_policy": "adaptive_ramp_v1",
            "concurrency_history": stages,
            "max_worker_count": 10,
            "requests_used": 22,
        }

    def _overlay(self) -> dict:
        return {
            "schema_version": 3,
            "category_id": "truck_rescue",
            "license_id": self.license_id,
            "scope": "details",
            "plan_sha256": "a" * 64,
            "structure_version": STRUCTURE,
            "generation_mode": MODE,
            "generation_target_ids": self.target_ids,
            "pending_generation_target_ids": self.target_ids,
            "delivery_target_ids": self.delivery_ids,
            "pending_delivery_target_ids": self.delivery_ids,
            "generation_targets_sha256": self.generation_hash,
            "delivery_targets_sha256": self.delivery_hash,
            "group_recipes": self.group_recipes,
            "group_recipes_sha256": json_sha(self.group_recipes),
            "phone": PHONE,
            "center_phone_text": f"电话：{PHONE}",
            "signboard_phone_text": f"联系电话：{PHONE}",
        }

    def write(self) -> None:
        write_jsonl(self.manifest_path, self.rows)
        write_json(self.overlay_path, self.overlay)
        write_jsonl(self.events_path, self.events)
        write_json(self.license_path, self.license)
        write_json(self.job_path, self.job)

    def plan(self) -> dict:
        return category_image_resume.build_resume_plan(
            self.batch, self.job_path, self.license_path
        )


class CategoryImageResumeTests(unittest.TestCase):
    def make_fixture(
        self, root: Path, *, explicit_reservations: bool = False
    ) -> ResumeFixture:
        return ResumeFixture(root, explicit_reservations=explicit_reservations)

    def test_exact_legacy_ledger_and_stable_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.make_fixture(Path(temporary))
            first = fixture.plan()
            second = fixture.plan()
        self.assertEqual(
            first["counts"],
            {
                "total": 600,
                "success": 6,
                "exhausted": 6,
                "balance_recoverable": 0,
                "unknown": 4,
                "unattempted": 584,
                "resumable": 588,
            },
        )
        self.assertEqual(first["requests_used"], 22)
        self.assertEqual(first["remaining_max_requests"], 1172)
        self.assertEqual(first["cumulative_max_requests"], 1194)
        self.assertEqual(first["budget"], 1200)
        self.assertEqual(first["balance_failure_request_count"], 0)
        self.assertEqual(first["resume_plan_sha256"], second["resume_plan_sha256"])
        self.assertRegex(first["resume_plan_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(set(first["success_ids"]).isdisjoint(first["resumable_ids"]))
        self.assertTrue(set(first["exhausted_ids"]).isdisjoint(first["resumable_ids"]))
        self.assertTrue(
            all(first["attempts_remaining"][target] == 1 for target in first["unknown_ids"])
        )
        self.assertEqual(
            first["resumable_ids"],
            [
                target
                for target in fixture.target_ids
                if target in set(first["unknown_ids"] + first["unattempted_ids"])
            ],
        )

    def test_explicit_request_reserved_ledger_matches_legacy_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.make_fixture(Path(temporary), explicit_reservations=True)
            plan = fixture.plan()
        self.assertEqual(plan["counts"]["unknown"], 4)
        self.assertEqual(plan["counts"]["resumable"], 588)
        self.assertEqual(plan["requests_used"], 22)
        self.assertEqual(plan["remaining_max_requests"], 1172)

    def test_balance_failure_recognizes_frozen_legacy_error_without_broadening(self) -> None:
        legacy = {
            "status": "request_failed",
            "error_kind": "non_retryable",
            "error": (
                "Error code: 403 - {'code': 'INSUFFICIENT_BALANCE', "
                "'message': 'Insufficient account balance'}"
            ),
        }
        self.assertTrue(category_image_resume._is_balance_failure(legacy))
        nested_billing = {
            "status": "request_failed",
            "error_kind": "non_retryable",
            "error": (
                "Error code: 403 - {'error': {'message': "
                "'insufficient balance', 'type': 'billing_error'}}"
            ),
        }
        self.assertTrue(category_image_resume._is_balance_failure(nested_billing))
        self.assertTrue(
            category_image_resume._is_balance_failure(
                {"status": "request_failed", "error_kind": "balance_exhausted"}
            )
        )
        self.assertFalse(
            category_image_resume._is_balance_failure(
                {**legacy, "error": "Error code: 403 - policy denied"}
            )
        )
        self.assertFalse(
            category_image_resume._is_balance_failure(
                {**nested_billing, "error": nested_billing["error"].replace("403", "400")}
            )
        )

    def test_balance_failure_is_recoverable_without_consuming_target_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.make_fixture(Path(temporary))
            index = 16
            row = fixture.rows[index]
            identity = fixture._identity(index)
            events = [
                {
                    "status": "request_reserved",
                    **identity,
                    "raw_target": row["raw_target"],
                    "delivery_target": row["target"],
                    "attempt": 1,
                    "request_number": 23,
                },
                {
                    "status": "request_failed",
                    **identity,
                    "attempt": 1,
                    "request_number": 23,
                    "error_kind": "balance_exhausted",
                    "will_retry": False,
                },
            ]
            with fixture.events_path.open("a", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            fixture.license["requests_used"] = 23
            fixture.job["requests_used"] = 23
            write_json(fixture.license_path, fixture.license)
            write_json(fixture.job_path, fixture.job)
            plan = fixture.plan()

        target_id = fixture.target_ids[index]
        self.assertEqual(plan["counts"]["balance_recoverable"], 1)
        self.assertEqual(plan["balance_recoverable_ids"], [target_id])
        self.assertEqual(plan["attempts_used"][target_id], 1)
        self.assertEqual(plan["attempts_remaining"][target_id], 2)
        self.assertEqual(plan["balance_failure_request_count"], 1)
        self.assertIn(target_id, plan["resumable_ids"])

    def test_balance_failure_does_not_block_later_effective_second_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.make_fixture(Path(temporary))
            index = 16
            row = fixture.rows[index]
            identity = fixture._identity(index)
            raw = fixture.batch / row["raw_target"]
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"recovered-after-balance")
            events = [
                {
                    "status": "request_reserved",
                    **identity,
                    "raw_target": row["raw_target"],
                    "delivery_target": row["target"],
                    "attempt": 1,
                    "request_number": 23,
                },
                {
                    "status": "request_failed",
                    **identity,
                    "attempt": 1,
                    "request_number": 23,
                    "error_kind": "balance_exhausted",
                    "will_retry": False,
                },
                {
                    "status": "request_reserved",
                    **identity,
                    "raw_target": row["raw_target"],
                    "delivery_target": row["target"],
                    "attempt": 2,
                    "request_number": 24,
                },
                {
                    "status": "request_failed",
                    **identity,
                    "attempt": 2,
                    "request_number": 24,
                    "error_kind": "transient",
                    "will_retry": True,
                },
                {
                    "status": "request_reserved",
                    **identity,
                    "raw_target": row["raw_target"],
                    "delivery_target": row["target"],
                    "attempt": 3,
                    "request_number": 25,
                },
                {
                    "status": "generated",
                    **identity,
                    "raw_target": row["raw_target"],
                    "delivery_target": row["target"],
                    "attempt": 3,
                    "request_number": 25,
                    "saved_raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                },
            ]
            with fixture.events_path.open("a", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            fixture.license["requests_used"] = 25
            fixture.job["requests_used"] = 25
            write_json(fixture.license_path, fixture.license)
            write_json(fixture.job_path, fixture.job)
            plan = fixture.plan()

        target_id = fixture.target_ids[index]
        self.assertIn(target_id, plan["success_ids"])
        self.assertNotIn(target_id, plan["balance_recoverable_ids"])
        self.assertEqual(plan["attempts_used"][target_id], 3)
        self.assertEqual(plan["attempts_remaining"][target_id], 0)
        self.assertEqual(plan["balance_failure_request_count"], 1)

    def test_ambiguous_legacy_missing_requests_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.make_fixture(Path(temporary))
            fixture.license["requests_used"] = 21
            fixture.job["requests_used"] = 21
            fixture.write()
            with self.assertRaisesRegex(
                category_image_resume.ResumePlanError, "多种分配方式"
            ):
                fixture.plan()

    def test_tampered_ids_hash_and_budget_are_rejected(self) -> None:
        mutations = {
            "id": lambda fixture: fixture.job.__setitem__(
                "license_id", "different-license"
            ),
            "hash": lambda fixture: fixture.rows[0].__setitem__(
                "effective_prompt", "被篡改的提示词"
            ),
            "budget": lambda fixture: fixture.license.__setitem__(
                "approved_request_budget", 1199
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = self.make_fixture(Path(temporary))
                mutate(fixture)
                fixture.write()
                with self.assertRaises(category_image_resume.ResumePlanError):
                    fixture.plan()

    def test_tampered_generated_raw_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.make_fixture(Path(temporary))
            raw = fixture.batch / fixture.rows[0]["raw_target"]
            raw.write_bytes(b"tampered")
            with self.assertRaisesRegex(
                category_image_resume.ResumePlanError, "成功原图哈希不一致"
            ):
                fixture.plan()

    def test_legacy_prefix_and_multiple_explicit_resume_epochs_replan_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.make_fixture(Path(temporary))

            first_index = 16
            first_row = fixture.rows[first_index]
            first_raw = fixture.batch / first_row["raw_target"]
            first_raw.parent.mkdir(parents=True, exist_ok=True)
            first_raw.write_bytes(b"first-resume-success")
            first_identity = fixture._identity(first_index)
            first_events = [
                {
                    "status": "request_reserved",
                    **first_identity,
                    "raw_target": first_row["raw_target"],
                    "delivery_target": first_row["target"],
                    "attempt": 1,
                    "request_number": 23,
                },
                {
                    "status": "generated",
                    **first_identity,
                    "raw_target": first_row["raw_target"],
                    "delivery_target": first_row["target"],
                    "attempt": 1,
                    "request_number": 23,
                    "saved_raw_sha256": hashlib.sha256(
                        first_raw.read_bytes()
                    ).hexdigest(),
                },
            ]
            with fixture.events_path.open("a", encoding="utf-8") as handle:
                for event in first_events:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            fixture.license["requests_used"] = 23
            fixture.job["requests_used"] = 23
            write_json(fixture.license_path, fixture.license)
            write_json(fixture.job_path, fixture.job)
            first_plan = fixture.plan()

            second_index = 17
            second_identity = fixture._identity(second_index)
            second_row = fixture.rows[second_index]
            second_events = [
                {
                    "status": "request_reserved",
                    **second_identity,
                    "raw_target": second_row["raw_target"],
                    "delivery_target": second_row["target"],
                    "attempt": 1,
                    "request_number": 24,
                },
                {
                    "status": "request_failed",
                    **second_identity,
                    "attempt": 1,
                    "request_number": 24,
                    "error_kind": "content_policy",
                    "will_retry": True,
                },
                {
                    "status": "request_reserved",
                    **second_identity,
                    "raw_target": second_row["raw_target"],
                    "delivery_target": second_row["target"],
                    "attempt": 2,
                    "request_number": 25,
                },
                {
                    "status": "request_failed",
                    **second_identity,
                    "attempt": 2,
                    "request_number": 25,
                    "error_kind": "content_policy",
                    "will_retry": False,
                },
            ]
            with fixture.events_path.open("a", encoding="utf-8") as handle:
                for event in second_events:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            fixture.license["requests_used"] = 25
            fixture.job["requests_used"] = 25
            write_json(fixture.license_path, fixture.license)
            write_json(fixture.job_path, fixture.job)
            second_plan = fixture.plan()

        self.assertEqual(first_plan["counts"]["success"], 7)
        self.assertEqual(first_plan["counts"]["resumable"], 587)
        self.assertEqual(first_plan["remaining_max_requests"], 1170)
        self.assertEqual(second_plan["counts"]["success"], 7)
        self.assertEqual(second_plan["counts"]["exhausted"], 7)
        self.assertEqual(second_plan["counts"]["unknown"], 4)
        self.assertEqual(second_plan["counts"]["unattempted"], 582)
        self.assertEqual(second_plan["counts"]["resumable"], 586)
        self.assertEqual(second_plan["remaining_max_requests"], 1168)
        self.assertNotEqual(
            first_plan["resume_plan_sha256"], second_plan["resume_plan_sha256"]
        )

    def test_explicit_epoch_rejects_later_legacy_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.make_fixture(Path(temporary))
            row = fixture.rows[16]
            identity = fixture._identity(16)
            events = [
                {
                    "status": "request_reserved",
                    **identity,
                    "raw_target": row["raw_target"],
                    "delivery_target": row["target"],
                    "attempt": 1,
                    "request_number": 23,
                },
                {
                    "status": "request_failed",
                    **identity,
                    "attempt": 1,
                    "error_kind": "transient",
                    "will_retry": False,
                },
            ]
            with fixture.events_path.open("a", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            fixture.license["requests_used"] = 23
            fixture.job["requests_used"] = 23
            write_json(fixture.license_path, fixture.license)
            write_json(fixture.job_path, fixture.job)
            with self.assertRaisesRegex(
                category_image_resume.ResumePlanError,
                "显式预留时期之后",
            ):
                fixture.plan()


if __name__ == "__main__":
    unittest.main()
