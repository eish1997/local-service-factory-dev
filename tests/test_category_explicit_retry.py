from __future__ import annotations

from copy import deepcopy
import json
import unittest

from tools.category_image_resume import ResumePlanError, _canonical_sha256
from tools.category_explicit_retry import apply_explicit_retry
from tools.category_resume_migration import TOLERANT_SOURCE_RAW_CONTRACT


def rehash(plan: dict) -> None:
    plan.pop("resume_plan_sha256", None)
    plan["resume_plan_sha256"] = _canonical_sha256(plan)


def make_case() -> dict:
    """A file-free fixture with 698 successes, two failed details and 713 calls."""

    target_ids = [f"truck_rescue:v3:g{group:04d}:u{position:02d}"
                  for group in range(274, 374) for position in range(1, 8)]
    selected = ["truck_rescue:v3:g0324:u05", "truck_rescue:v3:g0334:u07"]
    used_map = {target: 1 for target in target_ids}
    for target in target_ids[:13]:
        used_map[target] = 2
    license_data = {
        "license_id": "truck-original-license",
        "category_id": "truck_rescue", "batch_id": "batch_v3_fixture",
        "group_start": 274, "group_count": 100, "scope": "all", "provider": "relay",
        "base_url": "https://tinysnow.one/v1", "third_party_confirmed": True,
        "model": "gpt-image-2.5-flare", "quality": "medium", "size": "1024x1536",
        "max_attempts": 2, "retry_policy": "classified_once_v1", "api_key_slots": [1, 2],
        "status": "consumed", "one_time": True, "requests_used": 713,
        "approved_request_budget": 1400, "approved_api_request_count": 700, "plan_sha256": "a" * 64,
    }
    plan = {
        key: deepcopy(license_data[key]) for key in (
            "license_id", "category_id", "batch_id", "group_start", "group_count",
            "scope", "provider", "model", "quality", "size", "max_attempts", "retry_policy",
        )
    }
    plan.update({
        "schema_version": 1, "job_id": "truck-original-job", "requests_used": 713, "budget": 1400,
        "remaining_max_requests": 0, "cumulative_max_requests": 713,
        "counts": {"total": 700, "success": 698, "exhausted": 2, "balance_recoverable": 0,
                   "unknown": 0, "unattempted": 0, "resumable": 0},
        "attempts_used": used_map, "attempts_remaining": {target: 0 for target in target_ids},
        "success_ids": [target for target in target_ids if target not in selected],
        "exhausted_ids": list(selected), "resumable_ids": [], "balance_recoverable_ids": [],
        "unknown_ids": [], "unattempted_ids": [], "balance_failure_request_count": 10,
        "frozen_manifest_sha256": "b" * 64, "frozen_overlay_sha256": "c" * 64,
        "events_sha256": "d" * 64, "event_tail_sha256": "e" * 64,
    })
    migration = {
        "schema_version": 1, "kind": "category-resume-generation-migration",
        "old_generation": {"model": plan["model"], "quality": plan["quality"], "api_size": plan["size"]},
        "new_generation": {"model": "gpt-image-2-4k", "quality": "medium", "api_size": "2560x3840"},
        "raw_contract": TOLERANT_SOURCE_RAW_CONTRACT, "accepted_source_size": "2352x3520",
        "accepted_source_width_tolerance": 16, "credential_epoch": "credential-" + "f" * 32,
        "rotated_slots": [], "previous_authorization_id": "resume-" + "1" * 24,
        "previous_authorization_sha256": "2" * 64, "prior_cumulative_request_cap": 1077,
        "inherited_quarantined_api_key_slots": [], "effective_quarantined_api_key_slots": [],
    }
    previous = {
        "kind": "category-image-resume-authorization", "authorization_id": "resume-" + "3" * 24,
        "status": "consumed", "one_time": True, "consumed_at": "2026-09-27T22:00:00+08:00",
        "resume_confirmed": True, "paid_confirmed": True, "third_party_confirmed": True,
        "requests_used": 360, "approved_remaining_request_budget": 706,
        "approved_cumulative_request_budget": 1066, "original_approved_request_budget": 1400,
        "original_plan_sha256": license_data["plan_sha256"], "resume_plan_sha256": "4" * 64,
        "base_url": license_data["base_url"], "max_workers": 10,
        "resume_policy": "fixed_10_probe_policy_circuit_v1", "api_key_slots": list(range(1, 11)),
        "schedule_amendment_confirmed": True,
        "schedule_amendment": {"api_key_slots": list(range(1, 11)), "strict_original_request_budget": 1400},
        "generation_migration_confirmed": True, "generation_migration": migration,
    }
    for key in ("job_id", "license_id", "category_id", "batch_id", "provider", "model", "quality", "size",
                "frozen_manifest_sha256", "frozen_overlay_sha256"):
        previous[key] = plan[key]
    events = [{
        "status": "resume_started", "authorization_id": previous["authorization_id"],
        "resume_plan_sha256": previous["resume_plan_sha256"], **migration["new_generation"],
        "credential_epoch": migration["credential_epoch"], "requests_used_start": 360,
        "cumulative_max_requests": 1066, "resume_policy": previous["resume_policy"],
        "max_workers": 10, "api_key_slots": list(range(1, 11)),
    }]
    for index, (target, request_number, slot) in enumerate(zip(selected, (368, 440), (7, 9))):
        group, position = ((324, 5), (334, 7))[index]
        identity = {
            "authorization_id": previous["authorization_id"], "resume_plan_sha256": previous["resume_plan_sha256"],
            "generation_target_id": target, "delivery_target_id": f"truck_rescue:v3:g{group:04d}:d{position-2:02d}",
            "group_index": group, "generation_position": position, "delivery_position": position - 2,
            "request_number": request_number, "api_key_slot": slot, "attempt": 1,
            "retry_prompt_variant": "original", "credential_epoch": migration["credential_epoch"],
            **migration["new_generation"],
        }
        events.extend([
            {"status": "request_reserved", **identity,
             "effective_prompt_sha256": ("5" if index == 0 else "6") * 64,
             "raw_target": f"raw/group_{group:04d}/{position:02d}.png",
             "delivery_target": f"output/group_{group:04d}/{position-2:02d}.png"},
            {"status": "request_failed", **identity, "error_kind": "non_retryable", "will_retry": False,
             "api_key_failover_eligible": False,
             "error": "error_type=APIStatusError; error_kind=non_retryable; http_status=451"},
        ])
    rehash(plan)
    return {"plan": plan, "license": license_data, "events": events, "previous": previous, "ids": selected}


class CategoryExplicitRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = make_case()

    def apply(self) -> dict:
        return apply_explicit_retry(self.case["plan"], self.case["license"], self.case["events"],
                                    self.case["previous"], self.case["ids"])

    def test_only_two_explicit_attempt_two_requests_and_original_configuration(self) -> None:
        result = self.apply()
        self.assertEqual(result["requests_used"], 713)
        self.assertEqual(result["cumulative_max_requests"], 715)
        self.assertEqual(result["remaining_max_requests"], 2)
        self.assertEqual(result["attempts_used"], self.case["plan"]["attempts_used"])
        self.assertEqual(result["counts"]["success"], 698)
        self.assertEqual(result["counts"]["exhausted"], 0)
        self.assertEqual(result["counts"]["explicit_retry"], 2)
        self.assertEqual(result["explicit_retry_ids"], self.case["ids"])
        self.assertEqual(result["resumable_ids"], self.case["ids"])
        self.assertEqual(result["generation_migration"], self.case["previous"]["generation_migration"])
        self.assertNotIn("schedule_amendment", result)
        sidecar = result["explicit_retry"]
        self.assertEqual(sidecar["api_key_slots"], [7, 9])
        self.assertEqual(sidecar["max_workers"], 1)
        self.assertTrue(sidecar["stop_on_any_failure"])
        self.assertFalse(sidecar["allow_key_failover"])
        self.assertEqual(sidecar["retry_prompt_variant"], "original")
        self.assertEqual(sidecar["prior_cumulative_request_cap"], 1066)
        self.assertEqual([item["next_attempt"] for item in sidecar["targets"]], [2, 2])
        self.assertEqual([item["source_request_number"] for item in sidecar["targets"]], [368, 440])
        self.assertEqual(sidecar["previous_authorization_sha256"], _canonical_sha256(self.case["previous"]))

    def test_deep_copy_and_hash_binding_keep_input_history_unchanged(self) -> None:
        before = deepcopy(self.case)
        result = self.apply()
        material = deepcopy(result)
        digest = material.pop("resume_plan_sha256")
        self.assertEqual(digest, _canonical_sha256(material))
        result["generation_migration"]["rotated_slots"].append(1)
        result["attempts_used"].clear()
        result["explicit_retry"]["targets"].clear()
        self.assertEqual(before, self.case)

    def test_legacy_license_without_job_id_uses_bound_previous_job(self) -> None:
        self.assertNotIn("job_id", self.case["license"])
        self.assertEqual(self.apply()["job_id"], self.case["plan"]["job_id"])
        self.case["license"]["job_id"] = self.case["plan"]["job_id"]
        self.assertEqual(self.apply()["remaining_max_requests"], 2)
        self.case["license"]["job_id"] = "another-job"
        with self.assertRaises(ResumePlanError):
            self.apply()

    def test_single_selected_target_does_not_reopen_other_failure(self) -> None:
        self.case["ids"] = self.case["ids"][:1]
        result = self.apply()
        self.assertEqual(result["cumulative_max_requests"], 714)
        self.assertEqual(result["counts"]["exhausted"], 1)
        self.assertEqual(result["attempts_remaining"]["truck_rescue:v3:g0334:u07"], 0)

    def test_target_order_and_prompt_digest_are_bound(self) -> None:
        first = self.apply()
        self.case["ids"].reverse()
        second = self.apply()
        self.assertNotEqual(first["resume_plan_sha256"], second["resume_plan_sha256"])
        self.assertEqual(second["explicit_retry"]["api_key_slots"], [9, 7])
        self.case["events"][1]["effective_prompt_sha256"] = "7" * 64
        self.assertNotEqual(second["resume_plan_sha256"], self.apply()["resume_plan_sha256"])

    def test_invalid_or_successful_selection_is_rejected(self) -> None:
        original = list(self.case["ids"])
        for ids in ([], original + [original[0]], [original[0], original[0]],
                    ["truck_rescue:v3:g0274:u05"], ["truck_rescue:v3:g0324:u01"], ["outside"], None):
            self.case["ids"] = ids
            with self.subTest(ids=ids), self.assertRaises(ResumePlanError):
                self.apply()

    def test_already_used_second_attempt_and_changed_base_are_rejected(self) -> None:
        self.case["plan"]["attempts_used"][self.case["ids"][0]] = 2
        rehash(self.case["plan"])
        with self.assertRaises(ResumePlanError):
            self.apply()
        self.case = make_case()
        self.case["plan"]["resume_plan_sha256"] = "0" * 64
        with self.assertRaises(ResumePlanError):
            self.apply()

    def test_only_explicit_non_retryable_451_is_eligible(self) -> None:
        for mutation in ({"error_kind": "content_policy"}, {"error_kind": "balance_exhausted"},
                         {"error_kind": "transient"}, {"will_retry": True}, {"api_key_failover_eligible": True},
                         {"error": "error_type=APIStatusError; error_kind=non_retryable; http_status=403"},
                         {"error": "error_type=APIStatusError; error_kind=non_retryable; http_status=401"},
                         {"error": "private-provider-body"}, {"provider_original": "source.png"}):
            self.case = make_case()
            self.case["events"][2].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ResumePlanError) as raised:
                self.apply()
            self.assertNotIn("private-provider-body", str(raised.exception))

    def test_mismatched_source_slot_prompt_or_generation_is_rejected(self) -> None:
        for mutation in ({"api_key_slot": 8}, {"attempt": 2}, {"request_number": 369},
                         {"retry_prompt_variant": "safe"}, {"model": "other"},
                         {"credential_epoch": "credential-" + "a" * 32},
                         {"effective_prompt_sha256": "invalid"}):
            self.case = make_case()
            self.case["events"][1].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ResumePlanError):
                self.apply()

    def test_source_slot_quarantine_is_not_cleared_or_switched(self) -> None:
        self.case["events"].append({"status": "resume_concurrency_stage", "quarantined_api_key_slots": [7]})
        with self.assertRaises(ResumePlanError):
            self.apply()
        self.case["ids"] = self.case["ids"][1:]
        result = self.apply()
        self.assertEqual(result["explicit_retry"]["api_key_slots"], [9])
        self.assertEqual(result["explicit_retry"]["effective_quarantined_api_key_slots"], [7])

    def test_no_budget_reopening_from_original_or_earlier_migration_cap(self) -> None:
        self.case["previous"].update(approved_cumulative_request_budget=714,
                                     approved_remaining_request_budget=354)
        self.case["events"][0]["cumulative_max_requests"] = 714
        with self.assertRaises(ResumePlanError):
            self.apply()
        self.case["ids"] = self.case["ids"][:1]
        self.assertEqual(self.apply()["cumulative_max_requests"], 714)

    def test_bad_or_stale_previous_authority_is_rejected(self) -> None:
        for mutation in ({"status": "active"}, {"one_time": False}, {"job_id": "other"},
                         {"original_plan_sha256": "8" * 64}, {"base_url": "https://other.example/v1"},
                         {"explicit_retry": {}}, {"requests_used": 359}):
            self.case = make_case()
            self.case["previous"].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ResumePlanError):
                self.apply()
        self.case = make_case()
        self.case["events"].append({"status": "resume_started", "authorization_id": "resume-" + "9" * 24})
        with self.assertRaises(ResumePlanError):
            self.apply()

    def test_duplicate_failure_success_or_reapplying_is_rejected(self) -> None:
        for status in ("request_failed", "generated", "provider_source_recovered"):
            self.case = make_case()
            self.case["events"].append({**self.case["events"][2], "status": status})
            with self.subTest(status=status), self.assertRaises(ResumePlanError):
                self.apply()
        self.case = make_case()
        self.case["plan"] = self.apply()
        with self.assertRaises(ResumePlanError):
            self.apply()


if __name__ == "__main__":
    unittest.main()
