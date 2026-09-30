from __future__ import annotations

from copy import deepcopy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tests.test_category_image_resume import ResumeFixture, write_json, write_jsonl
from tools import category_image_resume as ledger
from tools import category_source_recovery as recovery
from tools.category_4k_raw import save_4k_raw_png
from tools.category_image_production import RawImageContractError


class CategorySourceRecoveryTests(unittest.TestCase):
    def fixture(self, root: Path, *, source_size=(2352, 3520), prior_accepted=False):
        item = ResumeFixture(root, explicit_reservations=True)
        item.index = 16
        item.row = item.rows[item.index]
        item.raw = item.batch / item.row["raw_target"]
        item.generation = {"model": "gpt-image-2-4k", "quality": "medium", "api_size": "2560x3840"}
        item.epoch = "credential-" + "b" * 32
        item.archive = item.batch / "production" / "provider_originals" / item.job_id
        stream = io.BytesIO()
        with Image.new("RGB", source_size, (70, 80, 90)) as image:
            image.save(stream, "PNG")
        item.payload = stream.getvalue()
        with self.assertRaises(RawImageContractError) as caught:
            save_4k_raw_png(item.raw, item.payload, archive_root=item.archive,
                           generation=item.generation, credential_epoch=item.epoch,
                           accepted_source_size="2352x3520" if prior_accepted else None)
        item.evidence = caught.exception.evidence
        item.source = Path(item.evidence["provider_original"])
        item.metadata = Path(item.evidence["provider_original_metadata"])
        item.authorization_id = "resume-" + "c" * 24
        item.authorization_path = item.batch / "production" / "resume_authorizations" / f"{item.authorization_id}.json"
        item.authorization = {
            "authorization_id": item.authorization_id, "job_id": item.job_id,
            "license_id": item.license_id, "category_id": item.license["category_id"],
            "batch_id": item.batch.name, "status": "consumed", "one_time": True,
            "consumed_at": "2026-09-27T14:27:00+00:00",
            "kind": "category-image-resume-authorization", "generation_migration_confirmed": True,
            "resume_plan_sha256": "d" * 64,
            "generation_migration": {"new_generation": item.generation, "credential_epoch": item.epoch},
        }
        if prior_accepted:
            item.authorization["generation_migration"].update(
                raw_contract="tinysnow_2352x3520_to_legacy_v1", accepted_source_size="2352x3520",
            )
        item.failed = {
            "status": "request_failed", **item._identity(item.index), "request_number": 23,
            "attempt": 1, "will_retry": False, "error_kind": "non_retryable",
            "authorization_id": item.authorization_id, "resume_plan_sha256": "d" * 64,
            "raw_contract": item.evidence["raw_contract"], "archive_status": "rejected",
            "source_returned_size": f"{source_size[0]}x{source_size[1]}", "source_sha256": item.evidence["source_sha256"],
            "provider_original": item.source.relative_to(item.batch).as_posix(),
        }
        item.events.extend([
            {"status": "resume_started", "authorization_id": item.authorization_id},
            {"status": "request_reserved", **item._identity(item.index), "request_number": 23,
             "attempt": 1, "raw_target": item.row["raw_target"], "delivery_target": item.row["target"]},
            item.failed,
        ])
        item.license["requests_used"] = 23
        item.job.update(status="paused_resume_probe_failed", requests_used=23, pid=None,
                        worker_pid=None, resume_authorization_id=item.authorization_id,
                        failed=7, failed_request_attempts=12, retry_count=5)
        item.session_path = item.batch / "production" / "resume_sessions" / f"{item.authorization_id}.json"
        item.session = {
            "job_id": item.job_id, "license_id": item.license_id,
            "authorization_id": item.authorization_id, "resume_plan_sha256": "d" * 64,
            "status": "paused_resume_probe_failed", "requests_used_end": 23, "pid": None,
        }
        if prior_accepted:
            item.job["status"] = item.session["status"] = "paused_api_errors"
        item.write()
        write_json(item.authorization_path, item.authorization)
        write_json(item.session_path, item.session)
        return item

    def recover(self, item, **kwargs):
        return recovery.recover_provider_source(
            item.batch, item.job_path, item.license_path,
            request_number=23, accepted_source_size="2352x3520", confirm=True, **kwargs,
        )

    def test_recovery_is_append_only_and_keeps_all_request_and_retry_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            before = item.plan()
            files = [item.job_path, item.license_path, item.manifest_path, item.overlay_path,
                     item.authorization_path, item.session_path, item.source, item.metadata]
            unchanged = {path: path.read_bytes() for path in files}
            old_events = item.events_path.read_bytes()
            old_raw = {item.batch / row["raw_target"]: (item.batch / row["raw_target"]).read_bytes()
                       for row in item.rows if (item.batch / row["raw_target"]).is_file()}
            result = self.recover(item)
            after = item.plan()
            self.assertEqual(result["status"], "provider_source_recovered")
            self.assertFalse(result["api_called"])
            self.assertEqual(after["requests_used"], 23)
            self.assertEqual(before["attempts_used"], after["attempts_used"])
            self.assertEqual(before["attempts_remaining"], after["attempts_remaining"])
            self.assertEqual(after["counts"]["success"], before["counts"]["success"] + 1)
            self.assertNotIn(item.row["generation_target_id"], after["resumable_ids"])
            self.assertTrue(item.events_path.read_bytes().startswith(old_events))
            self.assertEqual(len(item.events_path.read_text(encoding="utf-8").splitlines()), len(item.events) + 1)
            for path, data in {**unchanged, **old_raw}.items():
                self.assertEqual(path.read_bytes(), data)
            with Image.open(item.raw) as image:
                self.assertEqual(image.size, (1024, 1536))
            self.assertFalse((item.batch / "production" / "generation.lock").exists())
            stable = item.events_path.read_bytes()
            self.assertEqual(self.recover(item)["status"], "already_recovered")
            self.assertEqual(item.events_path.read_bytes(), stable)

    def test_raw_png_alone_does_not_override_failed_terminal(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            item.raw.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1024, 1536)).save(item.raw)
            plan = item.plan()
            self.assertIn(item.row["generation_target_id"], plan["exhausted_ids"])
            with self.assertRaises(ledger.ResumePlanError):
                self.recover(item)

    def test_duplicate_generated_terminal_cannot_replace_failed_request(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            item.raw.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1024, 1536)).save(item.raw)
            event = {**item.failed, "status": "generated", "raw_target": item.row["raw_target"],
                     "delivery_target": item.row["target"], "saved_raw_sha256": ledger._file_sha256(item.raw)}
            write_jsonl(item.events_path, item.events + [event])
            with self.assertRaisesRegex(ledger.ResumePlanError, "重复结果"):
                item.plan()

    def test_invalid_source_error_or_metadata_refused_without_new_raw_or_event(self):
        for changed in ("source_hash", "source_path", "failure_kind", "metadata", "latest_authorization"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                item = self.fixture(Path(folder))
                if changed == "source_hash":
                    item.source.write_bytes(b"tampered")
                elif changed == "source_path":
                    item.failed["provider_original"] = "../../outside.png"
                elif changed == "failure_kind":
                    item.failed["error_kind"] = "content_policy"
                elif changed == "metadata":
                    data = json.loads(item.metadata.read_text())
                    data["rejection_reason"] = "decode failed"
                    write_json(item.metadata, data)
                else:
                    item.events.append({"status": "resume_started", "authorization_id": "other"})
                write_jsonl(item.events_path, item.events)
                original = item.events_path.read_bytes()
                with self.assertRaises(ledger.ResumePlanError):
                    self.recover(item)
                self.assertEqual(item.events_path.read_bytes(), original)
                self.assertFalse(item.raw.exists())

    def test_lock_and_live_process_block_before_any_write(self):
        for scenario in ("lock", "pid"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as folder:
                item = self.fixture(Path(folder))
                lock = item.batch / "production" / "generation.lock"
                if scenario == "lock":
                    lock.write_bytes(b"keep even malformed old lock")
                else:
                    item.job["pid"] = 123
                    write_json(item.job_path, item.job)
                before = item.events_path.read_bytes()
                with patch.object(recovery, "recorded_job_pid_is_running", return_value=True):
                    with self.assertRaises(ledger.ResumePlanError):
                        self.recover(item)
                self.assertEqual(item.events_path.read_bytes(), before)
                self.assertFalse(item.raw.exists())
                if scenario == "lock":
                    self.assertEqual(lock.read_bytes(), b"keep even malformed old lock")

    def test_competing_lock_is_never_cleared_and_evidence_rechecked_under_lock(self):
        for scenario in ("competing_lock", "changed_auth"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as folder:
                item = self.fixture(Path(folder))
                acquire = recovery._acquire_recovery_lock
                lock_path = item.batch / "production" / "generation.lock"
                def race(path, job_id):
                    if scenario == "competing_lock":
                        path.write_bytes(b"another stale lock must survive")
                        return acquire(path, job_id)
                    owned = acquire(path, job_id)
                    changed = deepcopy(item.authorization)
                    changed["extra_change"] = True
                    write_json(item.authorization_path, changed)
                    return owned
                before = item.events_path.read_bytes()
                with patch.object(recovery, "_acquire_recovery_lock", side_effect=race):
                    with self.assertRaises(ledger.ResumePlanError):
                        self.recover(item)
                self.assertEqual(item.events_path.read_bytes(), before)
                self.assertFalse(item.raw.exists())
                if scenario == "competing_lock":
                    self.assertEqual(lock_path.read_bytes(), b"another stale lock must survive")
                else:
                    self.assertFalse(lock_path.exists())

    def test_local_save_then_append_failure_is_reusable_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            with patch.object(recovery.production, "append_event", side_effect=OSError("local failure")):
                with self.assertRaises(OSError):
                    self.recover(item)
            self.assertTrue(item.raw.exists())
            raw_sha = ledger._file_sha256(item.raw)
            with patch.object(recovery, "save_4k_raw_png", side_effect=AssertionError("must reuse")):
                result = self.recover(item)
            self.assertEqual(result["saved_raw_sha256"], raw_sha)

    def test_recovery_receipt_tampering_is_rejected_by_read_only_ledger(self):
        for field, value in (("failed_event_sha256", "0" * 64), ("saved_raw_sha256", "0" * 64),
                             ("api_called", True), ("attempt", 2),
                             ("recovery_metadata_sha256", "0" * 64),
                             ("accepted_source_width_tolerance", 16)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                item = self.fixture(Path(folder))
                self.recover(item)
                events = [json.loads(line) for line in item.events_path.read_text(encoding="utf-8").splitlines()]
                events[-1][field] = value
                write_jsonl(item.events_path, events)
                with self.assertRaises(ledger.ResumePlanError):
                    item.plan()

    def test_recovery_remains_valid_after_later_resume_but_cannot_recover_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            self.recover(item)
            events = [json.loads(line) for line in item.events_path.read_text(encoding="utf-8").splitlines()]
            recovered = events[-1]
            write_jsonl(item.events_path, events + [{"status": "resume_started", "authorization_id": "later"}])
            self.assertIn(item.row["generation_target_id"], item.plan()["success_ids"])
            write_jsonl(item.events_path, events + [recovered])
            with self.assertRaisesRegex(ledger.ResumePlanError, "重复本地"):
                item.plan()

    def test_explicit_width_tolerance_recovers_2336_source_without_refund(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder), source_size=(2336, 3520), prior_accepted=True)
            before = item.plan()
            original = {path: path.read_bytes() for path in (
                item.job_path, item.license_path, item.authorization_path, item.session_path,
                item.metadata, item.source,
            )}
            result = self.recover(item, accepted_source_width_tolerance=16)
            after = item.plan()
            self.assertEqual(result["requests_used"], 23)
            self.assertEqual(before["attempts_used"], after["attempts_used"])
            self.assertEqual(before["attempts_remaining"], after["attempts_remaining"])
            self.assertIn(item.row["generation_target_id"], after["success_ids"])
            for path, data in original.items():
                self.assertEqual(path.read_bytes(), data)
            receipt = json.loads(item.events_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(receipt["accepted_source_width_tolerance"], 16)
            metadata = json.loads((item.batch / receipt["recovery_metadata"]).read_text())
            self.assertEqual(metadata["raw_contract"], "tinysnow_2336_2352x3520_to_legacy_v1")
            self.assertEqual(metadata["source_returned_size"], "2336x3520")
            self.assertEqual(metadata["accepted_source_width_tolerance"], 16)

    def test_width_tolerance_never_accepts_other_width_height_or_implicit_authority(self):
        for size, tolerance in (((2368, 3520), 16), ((2320, 3520), 16), ((2336, 3504), 16),
                                ((2336, 3520), 0), ((2336, 3520), 15), ((2336, 3520), 32),
                                ((2336, 3520), True), ((2336, 3520), "16")):
            with self.subTest(size=size, tolerance=tolerance), tempfile.TemporaryDirectory() as folder:
                item = self.fixture(Path(folder), source_size=size, prior_accepted=True)
                original = item.events_path.read_bytes()
                with self.assertRaises(ledger.ResumePlanError):
                    self.recover(item, accepted_source_width_tolerance=tolerance)
                self.assertFalse(item.raw.exists())
                self.assertEqual(item.events_path.read_bytes(), original)

    def test_width_receipt_and_original_exact_contract_tampering_is_rejected(self):
        for scenario in ("old_auth_contract", "old_metadata_anchor", "receipt_tolerance", "new_metadata_tolerance"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as folder:
                item = self.fixture(Path(folder), source_size=(2336, 3520), prior_accepted=True)
                if scenario == "old_auth_contract":
                    item.authorization["generation_migration"]["raw_contract"] = "tinysnow_4k_to_legacy_v1"
                    write_json(item.authorization_path, item.authorization)
                elif scenario == "old_metadata_anchor":
                    metadata = json.loads(item.metadata.read_text())
                    metadata["accepted_source_size"] = "2336x3520"
                    write_json(item.metadata, metadata)
                else:
                    self.recover(item, accepted_source_width_tolerance=16)
                    events = [json.loads(line) for line in item.events_path.read_text(encoding="utf-8").splitlines()]
                    if scenario == "receipt_tolerance":
                        events[-1]["accepted_source_width_tolerance"] = 0
                    else:
                        metadata_path = item.batch / events[-1]["recovery_metadata"]
                        metadata = json.loads(metadata_path.read_text())
                        metadata["accepted_source_width_tolerance"] = 0
                        write_json(metadata_path, metadata)
                        events[-1]["recovery_metadata_sha256"] = ledger._file_sha256(metadata_path)
                    write_jsonl(item.events_path, events)
                with self.assertRaises(ledger.ResumePlanError):
                    self.recover(item, accepted_source_width_tolerance=16)

    def test_old_2352_receipt_survives_nine_bounded_width_recoveries_and_later_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            item = self.fixture(Path(folder))
            self.recover(item)
            old_prefix = item.events_path.read_bytes()
            old_raw = item.raw.read_bytes()
            events = [json.loads(line) for line in item.events_path.read_text(encoding="utf-8").splitlines()]
            old_event_count = len(events)
            authorization = deepcopy(item.authorization)
            authorization["authorization_id"] = "resume-" + "e" * 24
            authorization["resume_plan_sha256"] = "f" * 64
            authorization["generation_migration"].update(
                raw_contract="tinysnow_2352x3520_to_legacy_v1", accepted_source_size="2352x3520",
            )
            auth_path = item.authorization_path.parent / f"{authorization['authorization_id']}.json"
            session_path = item.session_path.parent / auth_path.name
            write_json(auth_path, authorization)
            events.append({"status": "resume_started", "authorization_id": authorization["authorization_id"]})
            stream = io.BytesIO()
            Image.new("RGB", (2336, 3520), (80, 90, 100)).save(stream, "PNG")
            payload = stream.getvalue()
            frozen_sources = {item.source: item.source.read_bytes(), item.metadata: item.metadata.read_bytes()}
            for index in range(17, 26):
                row = item.rows[index]
                raw = item.batch / row["raw_target"]
                with self.assertRaises(RawImageContractError) as caught:
                    save_4k_raw_png(raw, payload, archive_root=item.archive, generation=item.generation,
                                   credential_epoch=item.epoch, accepted_source_size="2352x3520")
                evidence = caught.exception.evidence
                for key in ("provider_original", "provider_original_metadata"):
                    path = Path(evidence[key])
                    frozen_sources[path] = path.read_bytes()
                request_number = index + 7
                events.extend([
                    {"status": "request_reserved", **item._identity(index), "request_number": request_number,
                     "attempt": 1, "raw_target": row["raw_target"], "delivery_target": row["target"]},
                    {**item.failed, **item._identity(index), "request_number": request_number,
                     "authorization_id": authorization["authorization_id"], "resume_plan_sha256": "f" * 64,
                     "raw_contract": evidence["raw_contract"], "source_returned_size": "2336x3520",
                     "source_sha256": evidence["source_sha256"],
                     "provider_original": Path(evidence["provider_original"]).relative_to(item.batch).as_posix()},
                ])
            # Simulate the later worker's append-only events without rewriting
            # the old LF receipt through Windows text newline conversion.
            with item.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                for event in events[old_event_count:]:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.assertTrue(item.events_path.read_bytes().startswith(old_prefix))
            item.job.update(requests_used=32, status="paused_api_errors", resume_authorization_id=authorization["authorization_id"])
            item.license["requests_used"] = 32
            write_json(item.job_path, item.job)
            write_json(item.license_path, item.license)
            write_json(session_path, {**item.session, "authorization_id": authorization["authorization_id"],
                                     "resume_plan_sha256": "f" * 64, "status": "paused_api_errors", "requests_used_end": 32})
            for path in (item.job_path, item.license_path, auth_path, session_path):
                frozen_sources[path] = path.read_bytes()
            before = item.plan()
            for request_number in range(24, 33):
                recovery.recover_provider_source(
                    item.batch, item.job_path, item.license_path, request_number=request_number,
                    accepted_source_size="2352x3520", accepted_source_width_tolerance=16, confirm=True,
                )
            after = item.plan()
            self.assertEqual(after["requests_used"], 32)
            self.assertEqual(before["attempts_used"], after["attempts_used"])
            self.assertEqual(before["attempts_remaining"], after["attempts_remaining"])
            self.assertEqual(after["counts"]["success"], before["counts"]["success"] + 9)
            self.assertEqual(old_raw, item.raw.read_bytes())
            self.assertTrue(item.events_path.read_bytes().startswith(old_prefix))
            for path, original in frozen_sources.items():
                self.assertEqual(path.read_bytes(), original)
            current = [json.loads(line) for line in item.events_path.read_text(encoding="utf-8").splitlines()]
            current.append({"status": "resume_started", "authorization_id": "later-resume"})
            write_jsonl(item.events_path, current)
            self.assertEqual(item.plan()["counts"], after["counts"])


if __name__ == "__main__":
    unittest.main()
