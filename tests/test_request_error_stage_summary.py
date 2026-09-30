"""Transport diagnostics must not expose URLs, response bodies or keys."""
import unittest

from tools.category_image_production import safe_request_error_summary


class RequestErrorStageSummaryTests(unittest.TestCase):
    def test_legacy_exception_summary_unchanged(self):
        self.assertEqual(
            safe_request_error_summary(TimeoutError("sensitive response"), "transient"),
            "error_type=TimeoutError; error_kind=transient",
        )

    def test_only_safe_download_stage_metadata_is_logged(self):
        error = TimeoutError("https://private.invalid/image?token=secret")
        error.error_stage = "image_download_read"
        error.response_kind = "url"
        error.elapsed_seconds = 60.125
        summary = safe_request_error_summary(error, "transient")
        self.assertIn("error_stage=image_download_read", summary)
        self.assertIn("response_kind=url", summary)
        self.assertIn("elapsed_seconds=60.125", summary)
        self.assertNotIn("private", summary)
        self.assertNotIn("secret", summary)

    def test_malformed_metadata_cannot_enter_summary(self):
        error = TimeoutError("sensitive")
        error.error_stage = "url-with-token"
        error.response_kind = "secret"
        error.elapsed_seconds = "secret"
        summary = safe_request_error_summary(error, "transient")
        self.assertEqual(summary, "error_type=TimeoutError; error_kind=transient")


if __name__ == "__main__":
    unittest.main()
