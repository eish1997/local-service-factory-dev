from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.category_image_resume import ResumePlanError
from tools.category_resume_schedule import apply_schedule_amendment
from tests.test_category_image_resume import ResumeFixture


def canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class CategoryResumeScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.license = {
            "license_id": "original-license",
            "category_id": "truck_rescue",
            "batch_id": "batch_schedule_fixture",
            "group_start": 274,
            "group_count": 100,
            "scope": "all",
            "provider": "relay",
            "model": "gpt-image-2.5-flare",
            "quality": "medium",
            "size": "1024x1536",
            "max_attempts": 2,
            "retry_policy": "classified_once_v1",
            "api_key_slots": [1, 2],
            "approved_request_budget": 1400,
            "requests_used": 17,
        }
        identity = {
            key: value
            for key, value in self.license.items()
            if key not in {"api_key_slots", "approved_request_budget", "requests_used"}
        }
        ids = [f"target-{number}" for number in range(700)]
        remaining = {target_id: 2 for target_id in ids}
        used = {target_id: 0 for target_id in ids}
        for target_id in ids[:8]:
            remaining[target_id] = 0
            used[target_id] = 2
        used[ids[8]] = 1  # One balance failure does not consume this target's allowance.
        self.plan = {
            "schema_version": 1,
            **identity,
            "job_id": "original-job",
            "budget": 1400,
            "requests_used": 17,
            "remaining_max_requests": 1384,
            "cumulative_max_requests": 1401,
            "balance_failure_request_count": 1,
            "counts": {"total": 700, "resumable": 692},
            "resumable_ids": ids[8:],
            "success_ids": ids[:8],
            "attempts_used": used,
            "attempts_remaining": remaining,
            "frozen_manifest_sha256": "a" * 64,
            "frozen_overlay_sha256": "b" * 64,
            "events_sha256": "c" * 64,
            "event_tail_sha256": "d" * 64,
        }
        self.plan["resume_plan_sha256"] = canonical_sha(self.plan)
        self.slots = list(range(1, 11))
        self.events = [
            {"status": "request_failed", "error_kind": "balance_exhausted", "api_key_slot": 2},
            {"status": "concurrency_stage", "quarantined_api_key_slots": [2]},
        ]

    def amend(self) -> dict:
        return apply_schedule_amendment(self.plan, self.license, self.events, self.slots)

    def test_original_budget_includes_balance_requests_without_compensation(self) -> None:
        amended = self.amend()
        self.assertEqual(amended["remaining_max_requests"], 1383)
        self.assertEqual(amended["cumulative_max_requests"], 1400)
        self.assertEqual(amended["requests_used"], 17)
        self.assertEqual(amended["schedule_amendment"]["strict_original_request_budget"], 1400)

    def test_per_target_total_can_be_the_smaller_limit(self) -> None:
        self.plan["attempts_remaining"] = {target_id: 1 for target_id in self.plan["resumable_ids"]}
        amended = self.amend()
        self.assertEqual(amended["remaining_max_requests"], 692)
        self.assertEqual(amended["cumulative_max_requests"], 709)

    def test_exhausted_global_budget_is_never_reopened(self) -> None:
        self.plan["requests_used"] = self.license["requests_used"] = 1400
        amended = self.amend()
        self.assertEqual(amended["remaining_max_requests"], 0)
        self.assertEqual(amended["cumulative_max_requests"], 1400)

    def test_exact_amendment_contract(self) -> None:
        self.assertEqual(
            self.amend()["schedule_amendment"],
            {
                "schema_version": 1,
                "kind": "category-resume-schedule-amendment",
                "api_key_slots": list(range(1, 11)),
                "original_api_key_slots": [1, 2],
                "max_workers": 10,
                "resume_policy": "fixed_10_probe_policy_circuit_v1",
                "inherited_quarantined_api_key_slots": [2],
                "strict_original_request_budget": 1400,
            },
        )

    def test_accepts_real_validated_resume_plan_without_rewriting_frozen_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResumeFixture(Path(temporary))
            fixture.license["api_key_slots"] = [1, 2]
            fixture.write()
            files = [fixture.job_path, fixture.license_path, fixture.manifest_path, fixture.overlay_path, fixture.events_path]
            before = [path.read_bytes() for path in files]
            base = fixture.plan()
            amended = apply_schedule_amendment(base, fixture.license, fixture.events, self.slots)
            self.assertEqual(before, [path.read_bytes() for path in files])
            self.assertEqual(amended["requests_used"], 22)
            self.assertEqual(amended["remaining_max_requests"], 1172)
            self.assertEqual(amended["cumulative_max_requests"], 1194)
            self.assertEqual(amended["attempts_remaining"], base["attempts_remaining"])
            self.assertEqual(amended["resumable_ids"], base["resumable_ids"])

    def test_inherits_current_legacy_and_event_quarantines_without_unquarantining(self) -> None:
        private_error = "Error code: 403 INSUFFICIENT_BALANCE insufficient account balance private-marker"
        self.events.extend(
            [
                {"status": "request_failed", "error_kind": "non_retryable", "api_key_slot": 3, "error": private_error},
                {"status": "request_failed", "error_kind": "non_retryable", "api_key_slot": 4, "error": "Error code: 403 billing_error insufficient balance"},
                {"status": "resume_concurrency_stage", "quarantined_api_key_slots": [5, 12]},
                {"status": "request_failed", "error_kind": "balance_exhausted", "api_key_slot": 13},
                {"status": "generated", "api_key_slot": 2},
                {"status": "concurrency_stage", "quarantined_api_key_slots": []},
            ]
        )
        amended = self.amend()
        self.assertEqual(amended["schedule_amendment"]["inherited_quarantined_api_key_slots"], [2, 3, 4, 5])
        self.assertNotIn("private-marker", json.dumps(amended))

    def test_does_not_infer_balance_from_unrelated_errors_or_success(self) -> None:
        self.events = [
            {"status": "request_failed", "error_kind": "non_retryable", "api_key_slot": 2, "error": "Error code: 403 permission denied"},
            {"status": "request_failed", "error_kind": "transient", "api_key_slot": 3, "error": "INSUFFICIENT_BALANCE insufficient account balance"},
            {"status": "generated", "error_kind": "balance_exhausted", "api_key_slot": 4},
        ]
        self.assertEqual(self.amend()["schedule_amendment"]["inherited_quarantined_api_key_slots"], [])

    def test_plan_hash_binds_slot_selection_and_order(self) -> None:
        first = self.amend()
        self.slots[-1] = 11
        second = self.amend()
        self.slots.reverse()
        third = self.amend()
        hashes = {result["resume_plan_sha256"] for result in (first, second, third)}
        self.assertEqual(len(hashes), 3)
        material = dict(first)
        stored_hash = material.pop("resume_plan_sha256")
        self.assertEqual(stored_hash, canonical_sha(material))
        self.assertEqual(first, apply_schedule_amendment(self.plan, self.license, self.events, list(range(1, 11))))

    def test_no_input_mutation_or_shared_nested_objects(self) -> None:
        before = deepcopy((self.plan, self.license, self.events, self.slots))
        amended = self.amend()
        self.assertEqual(before, (self.plan, self.license, self.events, self.slots))
        allowed_changes = {"remaining_max_requests", "cumulative_max_requests", "resume_plan_sha256"}
        for key in self.plan:
            if key not in allowed_changes:
                self.assertEqual(self.plan[key], amended[key], key)
        amended["counts"]["total"] = 0
        amended["attempts_remaining"]["target-8"] = 0
        amended["schedule_amendment"]["api_key_slots"].clear()
        amended["schedule_amendment"]["original_api_key_slots"].clear()
        self.assertEqual(before, (self.plan, self.license, self.events, self.slots))

    def test_rejects_malformed_selected_slots(self) -> None:
        cases = [None, "1,2,3,4,5,6,7,8,9,10", tuple(self.slots), [], self.slots[:-1], self.slots + [11]]
        cases.extend([[1, 2, 3, 4, 5, 6, 7, 8, 9, value] for value in (9, 0, -1, True, 10.0, "10")])
        for slots in cases:
            with self.subTest(slots=slots), self.assertRaises(ResumePlanError):
                apply_schedule_amendment(self.plan, self.license, self.events, slots)

    def test_rejects_malformed_or_missing_original_slots(self) -> None:
        for original in (None, [], [1, 1], [True, 2], [1, 2.0], [1, "2"], [0, 2], [1, 11]):
            with self.subTest(original=original), self.assertRaises(ResumePlanError):
                apply_schedule_amendment(self.plan, {**self.license, "api_key_slots": original}, self.events, self.slots)

    def test_rejects_changed_identity_or_budget(self) -> None:
        for key in ("license_id", "category_id", "batch_id", "scope", "provider", "model", "quality", "size", "retry_policy", "group_start", "group_count", "max_attempts", "budget", "requests_used"):
            plan = deepcopy(self.plan)
            plan[key] = plan[key] + 1 if type(plan[key]) is int else "changed"
            with self.subTest(key=key), self.assertRaises(ResumePlanError):
                apply_schedule_amendment(plan, self.license, self.events, self.slots)
        with self.assertRaises(ResumePlanError):
            apply_schedule_amendment(self.plan, {**self.license, "job_id": "other-job"}, self.events, self.slots)

    def test_rejects_already_overspent_ledger(self) -> None:
        self.plan["requests_used"] = self.license["requests_used"] = 1401
        with self.assertRaises(ResumePlanError):
            self.amend()

    def test_rejects_too_few_resumable_targets_and_count_mismatch(self) -> None:
        self.plan["counts"]["resumable"] = 9
        with self.assertRaises(ResumePlanError):
            self.amend()
        self.plan["resumable_ids"] = self.plan["resumable_ids"][:9]
        with self.assertRaises(ResumePlanError):
            self.amend()

    def test_rejects_bad_quarantine_evidence_without_exposing_error(self) -> None:
        for event in (
            {"status": "request_failed", "error_kind": "balance_exhausted", "error": "private-marker"},
            {"status": "concurrency_stage", "quarantined_api_key_slots": [True]},
            {"status": "concurrency_stage", "quarantined_api_key_slots": "2"},
        ):
            with self.subTest(event=event), self.assertRaises(ResumePlanError) as raised:
                apply_schedule_amendment(self.plan, self.license, [event], self.slots)
            self.assertNotIn("private-marker", str(raised.exception))

    def test_rejects_reapplying_amendment(self) -> None:
        with self.assertRaises(ResumePlanError):
            apply_schedule_amendment(self.amend(), self.license, self.events, self.slots)


if __name__ == "__main__":
    unittest.main()
