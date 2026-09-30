from __future__ import annotations

import os
import unittest
from unittest import mock

from tools import category_image_production


@unittest.skipUnless(os.name == "nt", "Windows-specific PID probe regression")
class WindowsPidLivenessTests(unittest.TestCase):
    def test_live_process_probe_never_calls_os_kill(self) -> None:
        with mock.patch.object(
            category_image_production.os,
            "kill",
            side_effect=AssertionError("os.kill must not be used on Windows"),
        ):
            self.assertTrue(category_image_production.pid_is_running(os.getpid()))

    def test_missing_process_probe_never_calls_os_kill(self) -> None:
        with mock.patch.object(
            category_image_production.os,
            "kill",
            side_effect=AssertionError("os.kill must not be used on Windows"),
        ):
            self.assertFalse(
                category_image_production.pid_is_running(2_147_483_647)
            )


if __name__ == "__main__":
    unittest.main()
