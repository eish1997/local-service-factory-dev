from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tools import category_image_production as production


class CategoryDetailRegenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.batch_root = self.root / "prompts" / "category_batches"
        self.batch = self.batch_root / "truck_rescue" / "batch_test"
        self.output = self.root / "output" / "truck_rescue"
        self.target = self.output / "group_0242" / "03_detail.png"
        self.raw = self.batch / "raw" / "group_0242" / "05_detail.png"
        self.other = self.output / "group_0242" / "04_detail.png"
        for path, color in [(self.target, "red"), (self.raw, "blue"), (self.other, "green")]:
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1024, 1536), color).save(path)
        self.phone = "13437186038"
        self.target_id = "truck_rescue:v3:g0242:u05"
        self.delivery_id = "truck_rescue:v3:g0242:d03"
        self.validation = self.target.with_suffix(".validation.json")
        self.previous = {
            "status": "needs_user_review", "approved": False, "manual_visual_approval": False,
            "category_id": "truck_rescue", "group_index": 242, "delivery_position": 3,
            "generation_target_id": self.target_id, "delivery_target_id": self.delivery_id,
            "generation_kind": "detail", "role": "detail", "final_size": "1024x1536",
            "expected_text": [f"电话：{self.phone}"], "postprocessed_locally": True,
            "image_sha256": production._file_sha256(self.target),
        }
        production.atomic_json(self.validation, self.previous)
        self.record = {
            "category_id": "truck_rescue", "group_index": 242, "generation_position": 5,
            "delivery_position": 3, "generation_kind": "detail", "role": "detail",
            "generation_target_id": self.target_id, "delivery_target_id": self.delivery_id,
            "target": str(self.target), "legacy_target": str(self.target),
            "raw_target": str(self.raw), "final_size": "1024x1536",
            "structure_version": "truck_rescue_v3", "generation_mode": "independent_triptych_panels",
        }
        self.fake_plan = {"delivery_records": production._delivery_records([self.record])}
        self.config = {"provider": "official", "model": "gpt-image-2", "quality": "medium",
                       "api_size": "1024x1536"}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(production, "ROOT", self.root))
        self.stack.enter_context(patch.object(production, "CATEGORY_BATCH_ROOT", self.batch_root))
        self.network = self.stack.enter_context(patch.object(
            production.image_generate, "generate_one", side_effect=AssertionError("network forbidden")))

    def prepare(self, **changes):
        args = dict(category_id="truck_rescue", batch_dir=self.batch, group_start=242,
                    group_count=1, phone=self.phone, config=self.config, output_root=self.output,
                    reason="疑似相似，用户要求替换", generation_target_id=self.target_id)
        args.update(changes)
        with patch.object(production, "plan", return_value=self.fake_plan) as mocked:
            result = production.prepare_detail_regeneration(**args)
            self.assertEqual(mocked.call_args.kwargs["scope"], "details")
            self.assertEqual(mocked.call_args.kwargs["generation_target_id"], self.target_id)
            return result

    def snapshot(self):
        return {str(path): path.read_bytes() for path in
                (self.target, self.raw, self.other, self.validation)}

    def test_archive_preserves_evidence_and_real_plan_requires_one_request(self):
        before = self.snapshot()
        result = self.prepare()
        self.assertFalse(result["api_called"])
        self.assertEqual(result["paid_requests"], 0)
        item = result["results"][0]
        for name, source in [("image", self.target), ("raw", self.raw), ("validation", self.validation)]:
            archived = Path(item[f"archived_{name}"])
            self.assertEqual(archived.read_bytes(), before[str(source)])
            self.assertEqual(production._file_sha256(archived), item[f"{name}_sha256"])
        for path in (self.target, self.raw, self.other):
            self.assertEqual(path.read_bytes(), before[str(path)])
        self.assertEqual(production.load_json(self.validation)["status"], "rejected")
        self.assertTrue(production.load_json(self.validation)["replacement_required"])
        self.assertTrue(Path(result["manifest_path"]).is_file())
        with (patch.object(production, "selected_records", return_value=[self.record]),
              patch.object(production, "record_targets", return_value=[self.record]),
              patch.object(production, "build_manifest_entries", return_value=[]),
              patch.object(production, "load_category_config", return_value={"service_buttons": ["服务"] * 10}),
              patch.object(production, "_validate_tuning_sample_scope")):
            plan = production.plan("truck_rescue", self.batch, 242, 1, self.phone, self.config,
                                   scope="details", output_root=self.output,
                                   generation_target_id=self.target_id)
        self.assertEqual(plan["pending_api_requests"], 1)
        self.assertEqual(plan["pending_generation_target_ids"], [self.target_id])
        self.assertFalse((self.batch / "production" / "generation.lock").exists())
        self.network.assert_not_called()

    def test_rejects_approved_or_already_rejected_validation(self):
        for status in ("approved", "needs_fix", "rejected"):
            with self.subTest(status=status):
                production.atomic_json(self.validation, self.previous | {"status": status})
                before = self.snapshot()
                with self.assertRaisesRegex(RuntimeError, "已批准"):
                    self.prepare()
                self.assertEqual(before, self.snapshot())

    def test_rejects_lock_without_removing_it(self):
        path = self.batch / "production" / "generation.lock"
        production.atomic_json(path, {"pid": 0, "job_id": "stale"})
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, "generation.lock"):
            self.prepare()
        self.assertTrue(path.exists())
        self.assertEqual(before, self.snapshot())

    def test_rejects_phone_sha_and_identity_mismatch(self):
        for replacement in ({"expected_text": ["电话：13407128962"]},
                            {"image_sha256": "0" * 64}, {"group_index": 243},
                            {"generation_target_id": "truck_rescue:v3:g0242:u06"}):
            with self.subTest(replacement=replacement):
                production.atomic_json(self.validation, self.previous | replacement)
                before = self.snapshot()
                with self.assertRaises(RuntimeError):
                    self.prepare()
                self.assertEqual(before, self.snapshot())

    def test_copy_failure_never_changes_validation_or_images(self):
        before = self.snapshot()
        real_copy = shutil.copy2
        def failing_copy(source, target):
            if Path(source) == self.raw:
                raise OSError("simulated copy failure")
            return real_copy(source, target)
        with patch.object(production.shutil, "copy2", side_effect=failing_copy):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.prepare()
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.batch / "production" / "generation.lock").exists())

    def test_rejects_non_single_detail_scope(self):
        for changes in ({"group_count": 2}, {"generation_target_id": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.prepare(**changes)
        self.fake_plan = copy.deepcopy(self.fake_plan)
        self.fake_plan["delivery_records"][0]["delivery_kind"] = "triptych"
        with self.assertRaisesRegex(RuntimeError, "独立详情"):
            self.prepare()

    def test_active_metadata_blocks_even_disjoint_ranges(self):
        for directory, status in (("jobs", "running"), ("resume_sessions", "resume_running"),
                                  ("licenses", "active"), ("resume_authorizations", "active")):
            with self.subTest(directory=directory):
                path = self.batch / "production" / directory / "test.json"
                production.atomic_json(path, {"status": status, "group_start": 1, "group_count": 1})
                before = self.snapshot()
                with self.assertRaises(RuntimeError):
                    self.prepare()
                self.assertEqual(before, self.snapshot())
                path.unlink()

    def test_terminal_and_disjoint_paused_history_do_not_block(self):
        root = self.batch / "production"
        production.atomic_json(root / "jobs" / "finished.json", {"status": "awaiting_review", "pid": 123})
        production.atomic_json(root / "resume_sessions" / "paused.json",
                               {"status": "paused_policy_circuit", "group_start": 1, "group_count": 1})
        production.atomic_json(root / "licenses" / "consumed.json", {"status": "consumed"})
        self.prepare()

    def historical_resume(self, *, session_changes=None, job_changes=None):
        root = self.batch / "production"
        job = {"job_id": "historical", "status": "completed_with_errors",
               "group_start": 44, "group_count": 100}
        session = {"job_id": "historical", "status": "running", "pid": 239552}
        job.update(job_changes or {})
        session.update(session_changes or {})
        job_path = root / "jobs" / "historical.json"
        session_path = root / "resume_sessions" / "historical-resume.json"
        production.atomic_json(job_path, job)
        production.atomic_json(session_path, session)
        return job_path, session_path

    def test_dead_historical_resume_of_finished_disjoint_job_does_not_block(self):
        paths = self.historical_resume()
        historical_bytes = {path: path.read_bytes() for path in paths}
        with patch.object(production, "pid_is_running", return_value=False):
            self.prepare()
        self.assertEqual(historical_bytes, {path: path.read_bytes() for path in paths})

    def test_live_historical_resume_still_blocks(self):
        self.historical_resume()
        before = self.snapshot()
        with patch.object(production, "pid_is_running", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "仍存活"):
                self.prepare()
        self.assertEqual(before, self.snapshot())

    def test_dead_historical_resume_requires_all_identity_range_and_terminal_evidence(self):
        variants = [({"pid": None}, {}), ({"job_id": "missing"}, {}),
                    ({}, {"job_id": "different"}), ({}, {"status": "paused_policy_circuit"}),
                    ({}, {"group_start": 242}), ({}, {"group_count": None}),
                    ({"group_start": 242, "group_count": 1}, {}),
                    ({"group_start": 44}, {})]
        for session_changes, job_changes in variants:
            with self.subTest(session=session_changes, job=job_changes):
                self.historical_resume(session_changes=session_changes, job_changes=job_changes)
                before = self.snapshot()
                with patch.object(production, "pid_is_running", return_value=False):
                    with self.assertRaises(RuntimeError):
                        self.prepare()
                self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
