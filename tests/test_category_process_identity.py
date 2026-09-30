from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from tools import category_process_identity as identity


class CategoryProcessIdentityTests(unittest.TestCase):
    def probe(self, birth, *, job=None, alive=True, image=None):
        if job is None:
            job = {"status": "paused_balance_exhausted", "finished_at": "2026-09-27T17:06:54+08:00"}
        with (patch.object(identity.production, "pid_is_running", return_value=alive),
              patch.object(identity, "_process_creation_time_utc", return_value=birth),
              patch.object(identity, "_process_image_and_windows_directory", return_value=image)):
            return identity.recorded_job_pid_is_running(40612, job)

    def test_newer_birth_proves_pid_reuse(self):
        self.assertFalse(self.probe(datetime(2026, 9, 27, 14, 9, 13, tzinfo=timezone.utc)))

    def test_equal_or_older_birth_is_still_live(self):
        for second in (53, 54):
            with self.subTest(second=second):
                self.assertTrue(self.probe(datetime(2026, 9, 27, 9, 6, second, tzinfo=timezone.utc)))

    def test_missing_birth_or_timestamp_is_live(self):
        self.assertTrue(self.probe(None))
        birth = datetime(2026, 9, 28, tzinfo=timezone.utc)
        for job in ({"status": "paused_balance_exhausted"},
                    {"status": "paused_balance_exhausted", "finished_at": "bad"},
                    {"status": "paused_balance_exhausted", "finished_at": "2026-09-27T17:06:54"}):
            with self.subTest(job=job):
                self.assertTrue(self.probe(birth, job=job))

    def test_active_job_never_discounts_a_live_pid(self):
        self.assertTrue(self.probe(datetime(2026, 9, 28, tzinfo=timezone.utc), job={
            "status": "running", "finished_at": "2026-09-27T17:06:54+08:00",
        }))

    def test_absent_process_is_not_live(self):
        self.assertFalse(self.probe(None, alive=False))

    def test_later_update_is_conservative_and_fallback_is_supported(self):
        birth = datetime(2026, 9, 27, 14, tzinfo=timezone.utc)
        job = {"status": "paused_balance_exhausted", "finished_at": "2026-09-27T17:06:54+08:00",
               "updated_at": "2026-09-27T23:00:00+08:00"}
        self.assertTrue(self.probe(birth, job=job))
        self.assertFalse(self.probe(birth, job={"status": "paused_balance_exhausted",
                                              "updated_at": "2026-09-27T17:06:54+08:00"}))

    def test_exact_system_conhost_is_not_paused_python_worker_even_before_latest_checkpoint(self):
        for folder in ("System32", "SysWOW64"):
            with self.subTest(folder=folder):
                self.assertFalse(self.probe(datetime(2026, 9, 27, 14, 9, tzinfo=timezone.utc),
                                           job={"status": "paused_resume_probe_failed",
                                                "finished_at": "2026-09-27T22:27:00+08:00"},
                                           image=(rf"C:\Windows\{folder}\conhost.exe", r"C:\Windows")))

    def test_conhost_name_outside_system_directory_or_unknown_path_remains_live(self):
        for image in ((r"E:\apps\conhost.exe", r"C:\Windows"),
                      (r"C:\Windows\Temp\conhost.exe", r"C:\Windows"),
                      (r"C:\Windows\System32\python.exe", r"C:\Windows"),
                      ("conhost.exe", r"C:\Windows"), None):
            with self.subTest(image=image):
                self.assertTrue(self.probe(None, image=image))

    def test_active_job_does_not_discount_even_exact_system_conhost(self):
        self.assertTrue(self.probe(None, job={"status": "running"},
                                   image=(r"C:\Windows\System32\conhost.exe", r"C:\Windows")))

    def test_process_image_query_failure_is_not_a_nonworker_proof(self):
        with patch.object(identity, "_process_image_and_windows_directory", side_effect=OSError("access denied")):
            self.assertFalse(identity._is_known_system_conhost(40612))


if __name__ == "__main__":
    unittest.main()
