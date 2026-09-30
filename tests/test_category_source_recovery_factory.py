from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import factory


class CategorySourceRecoveryFactoryTests(unittest.TestCase):
    def test_public_wrapper_uses_bound_paths_and_exact_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            batch = Path(temporary).resolve()
            production = batch / "production"
            job_path = production / "jobs" / "truck-job.json"
            license_path = production / "licenses" / "truck-license.json"
            job_path.parent.mkdir(parents=True)
            license_path.parent.mkdir(parents=True)
            job_path.write_text(json.dumps({"job_id": "truck-job", "category_id": "truck_rescue", "license_id": "truck-license"}), encoding="utf-8")
            license_path.write_text("{}", encoding="utf-8")
            args = SimpleNamespace(category="truck_rescue", batch_dir=None, job_id="truck-job",
                                   request_number=349, accepted_source_size="2352x3520", confirm=True)
            with (
                mock.patch.object(factory, "category_active_batch_dir", return_value=batch),
                mock.patch("tools.category_source_recovery.recover_provider_source", return_value={"api_calls": 0}) as recover,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(factory.command_recover_category_provider_source(args), 0)
            recover.assert_called_once_with(batch, job_path, license_path,
                                            request_number=349, accepted_source_size="2352x3520", confirm=True)

            args.accepted_source_width_tolerance = 16
            args.request_number = 352
            with (
                mock.patch.object(factory, "category_active_batch_dir", return_value=batch),
                mock.patch("tools.category_source_recovery.recover_provider_source", return_value={"api_calls": 0}) as tolerant_recover,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(factory.command_recover_category_provider_source(args), 0)
            tolerant_recover.assert_called_once_with(
                batch, job_path, license_path, request_number=352,
                accepted_source_size="2352x3520", accepted_source_width_tolerance=16,
                confirm=True,
            )

    def test_bad_job_id_is_rejected_without_recovery(self):
        args = SimpleNamespace(category="truck_rescue", batch_dir=None, job_id="../outside",
                               request_number=349, accepted_source_size="2352x3520", confirm=True)
        with (
            mock.patch("tools.category_source_recovery.recover_provider_source") as recover,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(factory.command_recover_category_provider_source(args), 2)
        recover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
