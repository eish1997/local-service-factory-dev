"""Task-scoped acceptance fixtures only: no API, network or production-state writes."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image

from tools import category_4k_raw as raw_adapter
from tools import category_image_production as production
from tools import category_image_resume as core
from tools import category_source_size_acceptance as sizes
from tools import image_download_receipts as receipts
from tests.test_category_profile_resume import profile_fixture
from tests.test_image_download_receipts import fake_dpapi, PRIVATE_URL


def png(size=(1264, 1920)):
    output = io.BytesIO()
    Image.new("RGB", size, "#456789").save(output, format="PNG")
    return output.getvalue()


@contextmanager
def rejected_fixture(count=1):
    with profile_fixture(count) as item, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
        events = [json.loads(line) for line in item.events_path.read_text().splitlines()]
        rows = item.plan["manifest_entries"]
        # A second exhausted target and three successful sources match the live
        # nine-request ledger without touching it.
        for number, index, attempt, status in ((3, 1, 1, "failed"), (4, 1, 2, "failed"),
                                               (5, 2, 1, "generated"), (6, 3, 1, "generated"),
                                               (7, 4, 1, "transient"), (8, 5, 1, "rejected"),
                                               (9, 6, 1, "generated")):
            row = rows[index]
            identity = {key: row[key] for key in ("generation_target_id", "delivery_target_id", "group_index", "generation_position", "delivery_position")}
            reserve = {**identity, "status": "request_reserved", "request_number": number, "attempt": attempt,
                       "api_key_slot": 1, "raw_target": row["raw_target"], "delivery_target": row["target"],
                       "effective_prompt_sha256": row["effective_prompt_sha256"], "retry_prompt_variant": "original"}
            events.append(reserve)
            event = {**identity, "status": "request_failed", "request_number": number, "attempt": attempt,
                     "api_key_slot": 1, "error_kind": "transient", "will_retry": status == "transient" or (status == "failed" and attempt == 1)}
            raw = core._relative_artifact_path(item.batch, row["raw_target"], "fixture raw")
            if status == "generated":
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(png((1024, 1536)))
                event = {**reserve, "status": "generated", "saved_raw_sha256": production._file_sha256(raw)}
            elif status == "rejected":
                item.payload = png()
                with unittest.TestCase().assertRaises(production.RawImageContractError) as caught:
                    raw_adapter.save_4k_raw_png(raw, item.payload,
                        archive_root=item.batch / "production/provider_originals" / item.job["job_id"],
                        generation=item.config, credential_epoch=None, accepted_source_size="2352x3520",
                        accepted_source_width_tolerance=16)
                evidence = caught.exception.evidence
                event.update({key: evidence[key] for key in ("source_returned_size", "source_sha256", "raw_contract", "archive_status")})
                event.update(error_kind="raw_contract_rejected", will_retry=False)
                for key in ("provider_original", "provider_original_metadata"):
                    event[key] = production._artifact_reference(evidence[key], item.batch)
                item.raw = raw
                item.source = Path(evidence["provider_original"])
                item.rejected_metadata = Path(evidence["provider_original_metadata"])
                item.context = {"root": str(item.root / ".runtime/image_download_receipts"),
                    "job_id": item.job["job_id"], "license_id": item.license["license_id"],
                    "generation_target_id": row["generation_target_id"], "request_number": number,
                    "attempt": attempt, "model": item.config["model"], "quality": item.config["quality"],
                    "api_size": item.config["api_size"], "effective_prompt_sha256": row["effective_prompt_sha256"],
                    "original_plan_sha256": item.license["plan_sha256"]}
                receipts.save_returned_url(item.context, PRIVATE_URL)
            events.append(event)
        item.events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        item.job.update(status="paused_api_errors", requests_used=9, failed=3, failed_request_attempts=6, retry_count=2)
        item.license.update(requests_used=9)
        production.atomic_json(item.job_path, item.job)
        production.atomic_json(item.license_path, item.license)
        item.events = events
        yield item


def accept(item):
    return sizes.accept_source_sizes(item.batch, item.job_path, item.license_path, confirm=True)


def load(item):
    return sizes.load_acceptance(item.batch, production.load_json(item.job_path), production.load_json(item.license_path),
                                 production._file_sha256(Path(item.license["production_manifest"])),
                                 production._file_sha256(Path(item.license["overlay_plan"])))


class SourceSizeAcceptanceTests(unittest.TestCase):
    def test_nine_used_420_cap_recovery_is_append_only_and_no_api(self):
        with rejected_fixture(30) as item:
            preserved = {path: path.read_bytes() for path in (item.job_path, item.license_path, item.source, item.rejected_metadata,
                          Path(item.license["production_manifest"]), Path(item.license["overlay_plan"]))}
            prefix = item.events_path.read_bytes()
            result = accept(item)
            self.assertEqual((result["requests_used"], result["approved_request_budget"], result["request_delta"], result["recovered_count"]), (9, 420, 0, 1))
            self.assertFalse(result["api_called"])
            self.assertNotIn("source_size_acceptance", result)
            self.assertNotIn("https", json.dumps(result))
            self.assertTrue(item.events_path.read_bytes().startswith(prefix))
            for path, content in preserved.items():
                self.assertEqual(path.read_bytes(), content)
            acceptance = load(item)
            events = core._load_jsonl(item.events_path, "fixture events")
            used, remaining, classes = core._account_attempts(item.batch, item.plan["manifest_entries"], events, item.job, item.license, acceptance)
            self.assertEqual(sum(used.values()), 9)
            self.assertEqual(classes[item.context["generation_target_id"]], "success")
            self.assertEqual(sum(value == "success" for value in classes.values()), 4)
            self.assertEqual(sum(value == "exhausted" for value in classes.values()), 2)
            self.assertEqual(remaining[item.context["generation_target_id"]], 0)
            receipts.assert_no_pending_for_job(item.context["root"], item.job["job_id"])
            with Image.open(item.raw) as image:
                self.assertEqual(image.size, (1024, 1536))

    def test_repeated_call_does_not_overwrite_or_append_twice(self):
        with rejected_fixture() as item:
            first = accept(item)
            original = (item.raw.read_bytes(), item.events_path.read_bytes(), Path(first["acceptance_path"]).read_bytes())
            self.assertEqual(accept(item), first)
            self.assertEqual((item.raw.read_bytes(), item.events_path.read_bytes(), Path(first["acceptance_path"]).read_bytes()), original)

    def test_failures_between_sidecar_raw_event_and_receipt_are_reentrant(self):
        for stage in ("sidecar", "raw", "event", "receipt"):
            with self.subTest(stage=stage), rejected_fixture() as item:
                if stage in {"sidecar", "raw"}:
                    original = sizes.publish_immutable_bytes
                    def interrupt(path, content):
                        original(path, content)
                        if (stage == "sidecar" and path.name == item.job["job_id"] + ".json") or (stage == "raw" and path == item.raw):
                            raise OSError("fixture interruption")
                    manager = patch.object(sizes, "publish_immutable_bytes", side_effect=interrupt)
                elif stage == "event":
                    manager = patch.object(sizes, "_append_recovery", side_effect=OSError("fixture before append"))
                else:
                    manager = patch.object(receipts, "mark_materialized", side_effect=OSError("fixture after append"))
                with manager, self.assertRaises(OSError):
                    accept(item)
                result = accept(item)
                self.assertEqual(result["requests_used"], 9)
                events = core._load_jsonl(item.events_path, "fixture events")
                self.assertEqual(sum(event.get("status") == "source_size_recovered" for event in events), 1)
                receipts.assert_no_pending_for_job(item.context["root"], item.job["job_id"])

    def test_existing_unrelated_raw_is_never_overwritten(self):
        with rejected_fixture() as item:
            item.raw.parent.mkdir(parents=True, exist_ok=True)
            item.raw.write_bytes(b"unrelated")
            prefix = item.events_path.read_bytes()
            with self.assertRaises(production.RawImageContractError):
                accept(item)
            self.assertEqual(item.raw.read_bytes(), b"unrelated")
            self.assertEqual(item.events_path.read_bytes(), prefix)

    def test_confirm_lock_and_live_process_block(self):
        for stage in ("confirm", "lock", "process"):
            with self.subTest(stage=stage), rejected_fixture() as item:
                if stage == "lock":
                    (item.batch / "production/generation.lock").write_bytes(b"other owner")
                if stage == "process":
                    item.job["worker_pid"] = 98765
                    production.atomic_json(item.job_path, item.job)
                with patch.object(sizes, "recorded_job_pid_is_running", return_value=stage == "process"), self.assertRaises(core.ResumePlanError):
                    sizes.accept_source_sizes(item.batch, item.job_path, item.license_path, confirm=stage != "confirm")
                self.assertFalse(item.raw.exists())
                self.assertFalse(sizes._path(item.batch, item.job["job_id"]).exists())

    def test_locked_evidence_change_fails_closed(self):
        from tools import category_source_recovery
        with rejected_fixture() as item:
            acquire = category_source_recovery._acquire_recovery_lock
            def change_after_lock(path, job_id):
                owned = acquire(path, job_id)
                item.events_path.write_text(item.events_path.read_text() + '{"status":"changed"}\n')
                return owned
            with patch.object(category_source_recovery, "_acquire_recovery_lock", side_effect=change_after_lock), self.assertRaises(core.ResumePlanError):
                accept(item)
            self.assertFalse(item.raw.exists())

    def test_binding_prefix_and_recovery_tampering_are_rejected(self):
        for field in ("phone", "original_plan_sha256", "events_prefix", "recovery_event", "rejected_metadata", "source", "receipt"):
            with self.subTest(field=field), rejected_fixture() as item:
                result = accept(item)
                if field in {"phone", "original_plan_sha256"}:
                    value = json.loads(Path(result["acceptance_path"]).read_text())
                    value[field] = "changed"
                    value["acceptance_sha256"] = sizes._canonical({key: val for key, val in value.items() if key != "acceptance_sha256"})
                    Path(result["acceptance_path"]).write_text(json.dumps(value))
                elif field == "events_prefix":
                    item.events_path.write_text(item.events_path.read_text().replace('"transient"', '"changed"', 1))
                elif field == "recovery_event":
                    item.events_path.write_text(item.events_path.read_text().replace('"request_delta": 0', '"request_delta": -1'))
                elif field == "rejected_metadata":
                    item.rejected_metadata.write_text("{}")
                elif field == "source":
                    item.source.write_bytes(png((100, 100)))
                elif field == "receipt":
                    receipts._path(item.context).write_text("{}")
                with self.assertRaises((core.ResumePlanError, ValueError, KeyError, receipts.ReturnedImageDownloadError)):
                    accept(item)

    def test_unapproved_recovery_and_other_job_do_not_inherit_policy(self):
        with rejected_fixture() as item:
            self.assertIsNone(load(item))
            with self.assertRaises(core.ResumePlanError):
                sizes.validated_recoveries(item.batch, [], [{"status": "source_size_recovered"}], item.job, item.license, None)
            accept(item)
            other = {**item.job, "job_id": "another-job"}
            self.assertIsNone(sizes.load_acceptance(item.batch, other, item.license, "a" * 64, "b" * 64))

    def test_receipt_request_binding_mismatch_blocks_before_acceptance(self):
        for field, replacement in (("generation_target_id", "truck_rescue:v3:g0374:u07"),
                                   ("effective_prompt_sha256", "b" * 64), ("attempt", 2)):
            with self.subTest(field=field), rejected_fixture() as item:
                receipt_path = receipts._path(item.context)
                receipt_path.unlink()  # Isolated fake receipt only, never production.
                receipts.save_returned_url({**item.context, field: replacement}, PRIVATE_URL)
                with self.assertRaises((core.ResumePlanError, ValueError, receipts.ReturnedImageDownloadError)):
                    accept(item)
                self.assertFalse(item.raw.exists())
                self.assertFalse(sizes._path(item.batch, item.job["job_id"]).exists())

    def test_any_size_adapter_reports_enlargement_and_keeps_legacy_gate(self):
        with rejected_fixture() as item:
            for index, dimensions in enumerate(((1264, 1920), (64, 96), (128, 64), (1, 1))):
                path = item.batch / "raw/test" / f"accepted{index}.png"
                payload = png(dimensions)
                result = raw_adapter.save_4k_raw_png(path, payload, archive_root=item.batch / "production/fixture-sources",
                    generation=item.config, credential_epoch=None, source_size_policy=sizes.POLICY_ID)
                self.assertEqual(Path(result["provider_original"]).read_bytes(), payload)
                self.assertEqual(result["source_returned_size"], f"{dimensions[0]}x{dimensions[1]}")
                self.assertEqual(result["working_raw_is_upscaled"], dimensions != (1264, 1920))
                self.assertFalse(result["source_is_upscaled_by_factory"])
                self.assertIn("fit_legacy", result["normalization_mode"])
            with self.assertRaises(production.RawImageContractError):
                raw_adapter.save_4k_raw_png(item.batch / "raw/legacy.png", png(), archive_root=item.batch / "production/fixture-sources",
                    generation=item.config, credential_epoch=None, accepted_source_size="2352x3520", accepted_source_width_tolerance=16)

    def test_decode_byte_pixel_dimension_and_unknown_policy_guards(self):
        for payload in (b"", b"not an image"):
            with self.assertRaises(production.RawImageContractError):
                raw_adapter.prepare_source_size_raw(payload)
        with patch.object(raw_adapter, "MAX_SOURCE_BYTES", 2), self.assertRaises(production.RawImageContractError):
            raw_adapter.prepare_source_size_raw(b"123")
        for name in ("MAX_SOURCE_PIXELS", "MAX_SOURCE_DIMENSION"):
            with patch.object(raw_adapter, name, 5), self.assertRaises(production.RawImageContractError):
                raw_adapter.prepare_source_size_raw(png((10, 10)))
        with rejected_fixture() as item, self.assertRaises(production.RawImageContractError):
            raw_adapter.save_4k_raw_png(item.raw, png(), archive_root=item.batch / "production/fixture-sources",
                generation=item.config, credential_epoch=None, source_size_policy="unconfirmed")

    def test_policy_decode_and_unsafe_pixel_rejections_keep_paid_bytes(self):
        for kind in ("corrupt", "pixels", "dimension", "bytes"):
            with self.subTest(kind=kind), rejected_fixture() as item:
                payload = b"paid but corrupt" if kind == "corrupt" else png((10, 10))
                limits = {"pixels": "MAX_SOURCE_PIXELS", "dimension": "MAX_SOURCE_DIMENSION", "bytes": "MAX_SOURCE_BYTES"}
                manager = patch.object(raw_adapter, limits.get(kind, "MAX_SOURCE_PIXELS"), 5 if kind != "corrupt" else 40_000_000)
                archive = item.batch / "production/safety-source-fixture"
                with manager, self.assertRaises(production.RawImageContractError) as caught:
                    raw_adapter.save_4k_raw_png(item.raw, payload, archive_root=archive,
                        generation=item.config, credential_epoch=None, source_size_policy=sizes.POLICY_ID)
                self.assertFalse(item.raw.exists())
                if kind == "bytes":
                    self.assertFalse(archive.exists())
                else:
                    evidence = caught.exception.evidence
                    self.assertEqual(Path(evidence["provider_original"]).read_bytes(), payload)
                    self.assertEqual(json.loads(Path(evidence["provider_original_metadata"]).read_text())["archive_status"], "rejected")

    def test_extreme_aspect_resize_has_only_bounded_target_intermediate(self):
        resize = Image.Image.resize
        sizes_seen = []
        def checked_resize(image, size, *args, **kwargs):
            sizes_seen.append(size)
            self.assertLessEqual(size[0] * size[1], 1024 * 1536)
            return resize(image, size, *args, **kwargs)
        for size in ((1, 16384), (16384, 1)):
            with self.subTest(size=size), patch.object(Image.Image, "resize", new=checked_resize), patch.object(production, "_fit_image", side_effect=AssertionError("unbounded legacy fit")):
                raw, result = raw_adapter.prepare_source_size_raw(png(size))
                with Image.open(io.BytesIO(raw)) as image:
                    self.assertEqual(image.size, (1024, 1536))
                self.assertTrue(result["working_raw_is_upscaled"])
        self.assertEqual(sizes_seen, [(1024, 1536), (1024, 1536)])


if __name__ == "__main__":
    unittest.main()
