from __future__ import annotations

from copy import deepcopy
import json
import unittest

from tools.category_image_resume import ResumePlanError
from tools.category_resume_migration import (
    ACCEPTED_SOURCE_RAW_CONTRACT, RAW_CONTRACT, TOLERANT_SOURCE_RAW_CONTRACT,
    apply_generation_migration,
)
from tools.category_resume_schedule import apply_schedule_amendment
from tests import test_category_resume_schedule as schedule_tests


canonical_sha = schedule_tests.canonical_sha


class CategoryResumeMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = schedule_tests.CategoryResumeScheduleTests()
        fixture.setUp()
        self.license = fixture.license
        self.license.update({
            "job_id": "original-job", "base_url": "https://tinysnow.one/v1",
            "third_party_confirmed": True, "status": "consumed", "one_time": True,
            "plan_sha256": "e" * 64,
        })
        self.original = fixture.plan
        self.events = fixture.events + [
            {"status": "concurrency_stage", "quarantined_api_key_slots": [2, 5]},
            {"status": "resume_started", "authorization_id": "resume-" + "a" * 24},
        ]
        self.slots = fixture.slots
        self.plan = apply_schedule_amendment(self.original, self.license, self.events, self.slots)
        self.previous = {
            "kind": "category-image-resume-authorization", "status": "consumed",
            "one_time": True, "consumed_at": "2026-09-27T07:10:49+00:00",
            "authorization_id": "resume-" + "a" * 24,
            "original_plan_sha256": self.license["plan_sha256"],
            "schedule_amendment_confirmed": True,
            "schedule_amendment": deepcopy(self.plan["schedule_amendment"]),
            "max_workers": 10, "api_key_slots": list(self.slots),
            "requests_used": 5, "approved_remaining_request_budget": 1295,
            "approved_cumulative_request_budget": 1300, "original_approved_request_budget": 1400,
        }
        for key in ("job_id", "license_id", "category_id", "batch_id", "model", "quality", "size",
                    "frozen_manifest_sha256", "frozen_overlay_sha256"):
            self.previous[key] = self.plan[key]
        self.spec = {
            "model": "gpt-image-2-4k", "quality": "medium", "api_size": "1024x1536",
            "credential_epoch": "credential-" + "b" * 32, "rotated_slots": [2],
        }

    def migrate(self) -> dict:
        return apply_generation_migration(self.plan, self.license, self.events, self.previous, self.spec)

    def rehash(self) -> None:
        self.plan.pop("resume_plan_sha256", None)
        self.plan["resume_plan_sha256"] = canonical_sha(self.plan)

    def prepare_continuation(self, *, cap: int = 1078) -> dict:
        self.previous.update(approved_cumulative_request_budget=cap,
                             approved_remaining_request_budget=cap - self.previous["requests_used"])
        self.spec["api_size"] = "2560x3840"
        first = self.migrate()
        self.previous.update(
            authorization_id="resume-" + "d" * 24,
            resume_plan_sha256=first["resume_plan_sha256"],
            requests_used=self.plan["requests_used"],
            approved_remaining_request_budget=first["remaining_max_requests"],
            approved_cumulative_request_budget=first["cumulative_max_requests"],
            generation_migration=deepcopy(first["generation_migration"]),
            generation_migration_confirmed=True,
        )
        self.events.append({
            "status": "resume_started", "authorization_id": self.previous["authorization_id"],
            "resume_plan_sha256": first["resume_plan_sha256"],
            **first["generation_migration"]["new_generation"],
            "credential_epoch": self.spec["credential_epoch"],
            "requests_used_start": self.plan["requests_used"],
            "cumulative_max_requests": first["cumulative_max_requests"],
        })
        self.plan = apply_schedule_amendment(self.original, self.license, self.events, self.slots)
        self.spec.update(rotated_slots=[], accepted_source_size="2352x3520")
        return first

    def refresh_schedule(self) -> None:
        self.plan = apply_schedule_amendment(self.original, self.license, self.events, self.slots)

    def test_preserves_original_fields_and_caps_by_previous_authorization(self) -> None:
        result = self.migrate()
        self.assertEqual(result["requests_used"], 17)
        self.assertEqual(result["cumulative_max_requests"], 1300)
        self.assertEqual(result["remaining_max_requests"], 1283)
        for key in ("model", "quality", "size", "attempts_used", "attempts_remaining", "success_ids", "resumable_ids", "schedule_amendment"):
            self.assertEqual(result[key], self.plan[key], key)
        migration = result["generation_migration"]
        self.assertEqual(migration["old_generation"], {"model": "gpt-image-2.5-flare", "quality": "medium", "api_size": "1024x1536"})
        self.assertEqual(migration["new_generation"], {key: self.spec[key] for key in ("model", "quality", "api_size")})
        self.assertEqual(migration["raw_contract"], RAW_CONTRACT)
        self.assertEqual(migration["previous_authorization_sha256"], canonical_sha(self.previous))
        self.assertEqual(migration["prior_cumulative_request_cap"], 1300)

    def test_only_rotated_slots_lose_old_quarantine(self) -> None:
        migration = self.migrate()["generation_migration"]
        self.assertEqual(migration["inherited_quarantined_api_key_slots"], [2, 5])
        self.assertEqual(migration["effective_quarantined_api_key_slots"], [5])
        self.spec["rotated_slots"] = list(self.slots)
        self.assertEqual(self.migrate()["generation_migration"]["effective_quarantined_api_key_slots"], [])
        self.assertEqual(self.plan["schedule_amendment"]["inherited_quarantined_api_key_slots"], [2, 5])

    def test_no_mutation_or_shared_nested_objects(self) -> None:
        before = deepcopy((self.plan, self.license, self.events, self.previous, self.spec))
        result = self.migrate()
        result["generation_migration"]["rotated_slots"].clear()
        result["schedule_amendment"]["api_key_slots"].clear()
        result["attempts_remaining"].clear()
        self.assertEqual(before, (self.plan, self.license, self.events, self.previous, self.spec))

    def test_hash_binds_every_generation_and_rotation_parameter(self) -> None:
        baseline = self.migrate()["resume_plan_sha256"]
        for key, value in (("quality", "high"), ("api_size", "2048x3072"),
                           ("credential_epoch", "credential-" + "c" * 32), ("rotated_slots", [5])):
            old = self.spec[key]
            self.spec[key] = value
            result = self.migrate()
            self.assertNotEqual(result["resume_plan_sha256"], baseline)
            material = deepcopy(result)
            digest = material.pop("resume_plan_sha256")
            self.assertEqual(digest, canonical_sha(material))
            self.spec[key] = old
        self.previous["consumed_at"] = "2026-09-27T07:10:50+00:00"
        self.assertNotEqual(self.migrate()["resume_plan_sha256"], baseline)

    def test_explicit_auto_parameters_are_bound_without_claiming_support(self) -> None:
        self.spec.update(quality="auto", api_size="auto")
        self.assertEqual(self.migrate()["generation_migration"]["new_generation"]["api_size"], "auto")

    def test_rejects_bad_specs_without_echoing_secrets(self) -> None:
        cases = [("model", "other"), ("quality", "private-marker"), ("api_size", ""),
                 ("api_size", "100000x100000"), ("api_size", "0x0"),
                 ("credential_epoch", "sk-private-marker"), ("rotated_slots", []),
                 ("rotated_slots", [1, 1]), ("rotated_slots", [11]), ("rotated_slots", [True])]
        for key, value in cases:
            before = deepcopy(self.spec)
            self.spec[key] = value
            with self.subTest(key=key), self.assertRaises(ResumePlanError) as error:
                self.migrate()
            self.assertNotIn("private-marker", str(error.exception))
            self.spec = before
        self.spec["api_key"] = "private-marker"
        with self.assertRaises(ResumePlanError) as error:
            self.migrate()
        self.assertNotIn("private-marker", str(error.exception))

    def test_rejects_other_route_or_unconsumed_original_license(self) -> None:
        for key, value in (("base_url", "https://other.example/v1"), ("third_party_confirmed", False),
                           ("status", "active"), ("one_time", False)):
            old = self.license[key]
            self.license[key] = value
            with self.subTest(key=key), self.assertRaises(ResumePlanError):
                self.migrate()
            self.license[key] = old

    def test_rejects_unbound_or_tampered_schedule(self) -> None:
        baseline = deepcopy(self.plan)
        for change in ("missing", "quarantine", "cap", "bad_hash", "model"):
            self.plan = deepcopy(baseline)
            if change == "missing":
                self.plan.pop("schedule_amendment")
            elif change == "quarantine":
                self.plan["schedule_amendment"]["inherited_quarantined_api_key_slots"] = []
            elif change == "cap":
                self.plan["cumulative_max_requests"] += 1
            elif change == "model":
                self.plan["model"] = "gpt-image-2-4k"
            if change != "bad_hash":
                self.rehash()
            else:
                self.plan["resume_plan_sha256"] = "0" * 64
            with self.subTest(change=change), self.assertRaises(ResumePlanError):
                self.migrate()

    def test_rejects_invalid_previous_authority(self) -> None:
        for key, value in (("status", "active"), ("one_time", False), ("consumed_at", ""),
                           ("kind", "other"), ("schedule_amendment_confirmed", False),
                           ("authorization_id", "../private-marker"), ("max_workers", 1),
                           ("api_key_slots", list(reversed(self.slots)))):
            baseline = deepcopy(self.previous)
            self.previous[key] = value
            with self.subTest(key=key), self.assertRaises(ResumePlanError):
                self.migrate()
            self.previous = baseline

    def test_rejects_previous_identity_or_frozen_evidence_mismatch(self) -> None:
        for key in ("job_id", "license_id", "category_id", "batch_id", "model", "quality", "size",
                    "original_plan_sha256", "frozen_manifest_sha256", "frozen_overlay_sha256"):
            old = self.previous[key]
            self.previous[key] = "changed"
            with self.subTest(key=key), self.assertRaises(ResumePlanError):
                self.migrate()
            self.previous[key] = old

    def test_rejects_budget_expansion_rollback_and_noninteger_values(self) -> None:
        cases = [
            {"approved_cumulative_request_budget": 1401, "approved_remaining_request_budget": 1396},
            {"approved_cumulative_request_budget": 16, "approved_remaining_request_budget": 11},
            {"requests_used": 18, "approved_remaining_request_budget": 1282},
            {"approved_remaining_request_budget": 1296},
            {"approved_cumulative_request_budget": True},
            {"original_approved_request_budget": 1401},
        ]
        for changes in cases:
            baseline = deepcopy(self.previous)
            self.previous.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ResumePlanError):
                self.migrate()
            self.previous = baseline

    def test_never_reopens_exhausted_prior_cap(self) -> None:
        self.previous.update(approved_cumulative_request_budget=17, approved_remaining_request_budget=12)
        result = self.migrate()
        self.assertEqual(result["remaining_max_requests"], 0)
        self.assertEqual(result["cumulative_max_requests"], 17)

    def test_remaining_target_allowances_can_be_smaller_than_prior_cap(self) -> None:
        self.original["attempts_remaining"] = {key: int(value > 0) for key, value in self.original["attempts_remaining"].items()}
        self.plan = apply_schedule_amendment(self.original, self.license, self.events, self.slots)
        self.assertEqual(self.migrate()["cumulative_max_requests"], 709)

    def test_rejects_reset_target_usage_even_with_rehashed_plan(self) -> None:
        self.plan["attempts_used"]["target-0"] = 0
        self.rehash()
        with self.assertRaises(ResumePlanError):
            self.migrate()

    def test_rejects_nonlatest_previous_authorization(self) -> None:
        self.events.append({"status": "resume_started", "authorization_id": "resume-" + "f" * 24})
        with self.assertRaises(ResumePlanError):
            self.migrate()

    def test_rejects_reapplication(self) -> None:
        self.plan = self.migrate()
        with self.assertRaises(ResumePlanError):
            self.migrate()

    def test_source_error_content_is_not_copied_into_migration(self) -> None:
        self.events[0]["error"] = "private-marker"
        self.assertNotIn("private-marker", json.dumps(self.migrate()))

    def test_explicit_accepted_source_size_binds_a_new_narrow_contract(self) -> None:
        strict = self.migrate()
        self.spec["accepted_source_size"] = "2352x3520"
        accepted = self.migrate()
        migration = accepted["generation_migration"]
        self.assertEqual(migration["raw_contract"], ACCEPTED_SOURCE_RAW_CONTRACT)
        self.assertEqual(migration["accepted_source_size"], "2352x3520")
        self.assertNotEqual(accepted["resume_plan_sha256"], strict["resume_plan_sha256"])
        self.assertNotIn("accepted_source_size", strict["generation_migration"])
        for invalid in (None, "2340x3520", "2352X3520", "2560x3840", [2352, 3520]):
            self.spec["accepted_source_size"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ResumePlanError):
                self.migrate()

    def test_same_epoch_continuation_preserves_prior_cap_and_rotation_history(self) -> None:
        first = self.prepare_continuation()
        before = deepcopy((self.plan, self.license, self.events, self.previous, self.spec))
        result = self.migrate()
        migration = result["generation_migration"]
        self.assertEqual(result["cumulative_max_requests"], 1078)
        self.assertEqual(result["remaining_max_requests"], 1078 - 17)
        self.assertEqual(migration["prior_cumulative_request_cap"], 1078)
        self.assertEqual(migration["credential_epoch"], first["generation_migration"]["credential_epoch"])
        self.assertEqual(migration["rotated_slots"], [])
        self.assertEqual(migration["inherited_quarantined_api_key_slots"], [5])
        self.assertEqual(migration["effective_quarantined_api_key_slots"], [5])
        self.assertEqual(result["schedule_amendment"]["inherited_quarantined_api_key_slots"], [2, 5])
        self.assertEqual(migration["previous_authorization_sha256"], canonical_sha(self.previous))
        self.assertEqual(before, (self.plan, self.license, self.events, self.previous, self.spec))

    def test_same_epoch_inherits_new_failures_even_after_empty_snapshot(self) -> None:
        self.prepare_continuation()
        self.events.extend([
            {"status": "request_failed", "error_kind": "balance_exhausted", "api_key_slot": 2,
             "authorization_id": self.previous["authorization_id"], "credential_epoch": self.spec["credential_epoch"]},
            {"status": "resume_concurrency_stage", "quarantined_api_key_slots": [7]},
            {"status": "resume_concurrency_stage", "quarantined_api_key_slots": []},
        ])
        self.refresh_schedule()
        self.assertEqual(self.migrate()["generation_migration"]["effective_quarantined_api_key_slots"], [2, 5, 7])

    def test_continuation_cannot_rotate_again_change_epoch_or_profile(self) -> None:
        self.prepare_continuation()
        for key, value in (("rotated_slots", [2]), ("credential_epoch", "credential-" + "e" * 32),
                           ("api_size", "1024x1536"), ("quality", "high")):
            old = self.spec[key]
            self.spec[key] = value
            with self.subTest(key=key), self.assertRaises(ResumePlanError):
                self.migrate()
            self.spec[key] = old
        self.spec.pop("accepted_source_size")
        with self.assertRaises(ResumePlanError):
            self.migrate()

    def test_continuation_requires_bound_start_and_same_epoch_request_events(self) -> None:
        self.prepare_continuation()
        original = deepcopy(self.events)
        for key, value in (("credential_epoch", "credential-" + "f" * 32),
                           ("resume_plan_sha256", "0" * 64), ("cumulative_max_requests", 1400),
                           ("requests_used_start", 0), ("api_size", "1024x1536")):
            self.events[-1][key] = value
            self.refresh_schedule()
            with self.subTest(key=key), self.assertRaises(ResumePlanError):
                self.migrate()
            self.events = deepcopy(original)
        self.events.append({"status": "generated", "authorization_id": self.previous["authorization_id"],
                            "credential_epoch": "credential-" + "f" * 32})
        self.refresh_schedule()
        with self.assertRaises(ResumePlanError):
            self.migrate()

    def test_continuation_rejects_tampered_prior_quarantine_and_budget_chain(self) -> None:
        self.prepare_continuation()
        baseline = deepcopy(self.previous)
        for field, value in (("effective_quarantined_api_key_slots", []),
                             ("inherited_quarantined_api_key_slots", [2, 5, 5]),
                             ("raw_contract", "accept_any_size"), ("prior_cumulative_request_cap", 1000),
                             ("previous_authorization_sha256", "invalid")):
            self.previous["generation_migration"][field] = value
            with self.subTest(field=field), self.assertRaises(ResumePlanError):
                self.migrate()
            self.previous = deepcopy(baseline)
        self.previous["generation_migration_confirmed"] = False
        with self.assertRaises(ResumePlanError):
            self.migrate()

    def test_continuation_cannot_expand_cap_back_to_earlier_1374(self) -> None:
        self.prepare_continuation()
        self.previous.update(approved_cumulative_request_budget=1374,
                             approved_remaining_request_budget=1374 - 17)
        self.events[-1]["cumulative_max_requests"] = 1374
        self.refresh_schedule()
        with self.assertRaises(ResumePlanError):
            self.migrate()

    def test_continuation_rejects_duplicate_epoch_start(self) -> None:
        self.prepare_continuation()
        self.events.append(deepcopy(self.events[-1]))
        self.refresh_schedule()
        with self.assertRaises(ResumePlanError):
            self.migrate()

    def test_width_tolerance_zero_preserves_old_exact_and_strict_hashes(self) -> None:
        for accepted in (False, True):
            if accepted:
                self.spec["accepted_source_size"] = "2352x3520"
            self.spec.pop("accepted_source_width_tolerance", None)
            baseline = self.migrate()
            self.spec["accepted_source_width_tolerance"] = 0
            result = self.migrate()
            self.assertEqual(result, baseline)
            self.assertNotIn("accepted_source_width_tolerance", result["generation_migration"])

    def test_width_tolerance_16_binds_narrow_contract_and_plan_hash(self) -> None:
        self.spec["accepted_source_size"] = "2352x3520"
        exact = self.migrate()
        self.spec["accepted_source_width_tolerance"] = 16
        result = self.migrate()
        migration = result["generation_migration"]
        self.assertEqual(migration["raw_contract"], TOLERANT_SOURCE_RAW_CONTRACT)
        self.assertEqual(migration["accepted_source_width_tolerance"], 16)
        self.assertEqual(migration["accepted_source_size"], "2352x3520")
        self.assertNotEqual(result["resume_plan_sha256"], exact["resume_plan_sha256"])
        self.assertEqual(result["requests_used"], exact["requests_used"])
        self.assertEqual(result["attempts_remaining"], exact["attempts_remaining"])

    def test_rejects_any_other_width_tolerance_or_missing_base_size(self) -> None:
        self.spec["accepted_source_size"] = "2352x3520"
        for invalid in (None, True, False, "16", 16.0, -16, 1, 15, 17, 32):
            self.spec["accepted_source_width_tolerance"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ResumePlanError):
                self.migrate()
        self.spec["accepted_source_width_tolerance"] = 16
        self.spec.pop("accepted_source_size")
        with self.assertRaises(ResumePlanError):
            self.migrate()
        self.spec["accepted_source_size"] = "2336x3520"
        with self.assertRaises(ResumePlanError):
            self.migrate()

    def test_exact_to_tolerant_continuation_does_not_reset_epoch_quarantine_or_budget(self) -> None:
        self.spec["accepted_source_size"] = "2352x3520"
        self.prepare_continuation(cap=1077)
        self.events.append({"status": "resume_concurrency_stage", "quarantined_api_key_slots": [7]})
        self.refresh_schedule()
        exact = self.migrate()
        self.spec["accepted_source_width_tolerance"] = 16
        result = self.migrate()
        self.assertEqual(result["cumulative_max_requests"], 1077)
        self.assertEqual(result["attempts_used"], exact["attempts_used"])
        self.assertEqual(result["attempts_remaining"], exact["attempts_remaining"])
        migration = result["generation_migration"]
        self.assertEqual(migration["credential_epoch"], self.spec["credential_epoch"])
        self.assertEqual(migration["rotated_slots"], [])
        self.assertEqual(migration["effective_quarantined_api_key_slots"], [5, 7])
        self.assertEqual(migration["prior_cumulative_request_cap"], 1077)
        self.assertEqual(migration["raw_contract"], TOLERANT_SOURCE_RAW_CONTRACT)

    def test_prior_tolerant_contract_must_match_exactly_bound_tolerance(self) -> None:
        self.spec.update(accepted_source_size="2352x3520", accepted_source_width_tolerance=16)
        self.prepare_continuation()
        self.assertEqual(self.migrate()["generation_migration"]["raw_contract"], TOLERANT_SOURCE_RAW_CONTRACT)
        previous = deepcopy(self.previous)
        for field, value in (("accepted_source_width_tolerance", 0), ("accepted_source_width_tolerance", 32),
                             ("accepted_source_width_tolerance", True), ("accepted_source_size", "2336x3520"),
                             ("raw_contract", ACCEPTED_SOURCE_RAW_CONTRACT)):
            self.previous["generation_migration"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ResumePlanError):
                self.migrate()
            self.previous = deepcopy(previous)


if __name__ == "__main__":
    unittest.main()
