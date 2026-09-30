"""Public source-size acceptance routing; fixture data only, no API or worker."""
from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import patch

import factory
from tests.test_category_profile_resume import profile_fixture


class CategorySourceSizeFactoryTests(unittest.TestCase):
    def _args(self, item, *extra):
        return factory.build_parser().parse_args([
            "accept-category-source-sizes", "--category", "truck_rescue",
            "--job-id", item.job["job_id"], "--batch-dir", str(item.batch), *extra,
        ])

    def test_explicit_acceptance_is_required_without_local_writes(self):
        with profile_fixture() as item, redirect_stdout(io.StringIO()):
            before = item.license_path.read_bytes(), item.job_path.read_bytes()
            with patch("tools.category_source_size_acceptance.accept_source_sizes") as accept:
                self.assertEqual(factory.command_accept_category_source_sizes(self._args(item)), 2)
                accept.assert_not_called()
            self.assertEqual(before, (item.license_path.read_bytes(), item.job_path.read_bytes()))

    def test_exact_job_identity_is_checked_before_acceptance(self):
        with profile_fixture() as item, redirect_stdout(io.StringIO()):
            args = self._args(item, "--confirm")
            args.category = "road_rescue"
            with patch("tools.category_source_size_acceptance.accept_source_sizes") as accept:
                self.assertEqual(factory.command_accept_category_source_sizes(args), 2)
                accept.assert_not_called()

    def test_public_acceptance_routes_only_local_recovery_no_worker(self):
        with profile_fixture() as item, redirect_stdout(io.StringIO()):
            launch_count = item.launch.call_count
            before = item.license_path.read_bytes(), item.job_path.read_bytes()
            with patch("tools.category_source_size_acceptance.accept_source_sizes",
                       return_value={"api_called": False, "requests_used": 2, "recovered_count": 1}) as accept:
                self.assertEqual(factory.command_accept_category_source_sizes(self._args(item, "--confirm")), 0)
                accept.assert_called_once_with(item.batch, item.job_path, item.license_path, confirm=True)
            self.assertEqual(item.launch.call_count, launch_count)
            self.assertEqual(before, (item.license_path.read_bytes(), item.job_path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
