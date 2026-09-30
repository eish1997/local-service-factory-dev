from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from tools import image_download_receipts as receipts


PRIVATE_URL = "https://images.example.invalid/private/path.png?signature=private-test-token"


def fake_dpapi(data, entropy, *, decrypt):
    # Test-only authenticated codec; never used as a runtime crypto fallback.
    if decrypt:
        plain = bytes(value ^ 91 for value in data[32:])
        if data[:32] != hashlib.sha256(entropy + plain).digest():
            raise ValueError("fake authentication failed")
        return plain
    return hashlib.sha256(entropy + data).digest() + bytes(value ^ 91 for value in data)


def context_for(root, *, request_number=3, target="truck_rescue:v3:g0374:u03"):
    return {
        "root": str(Path(root).resolve()), "job_id": "job-123", "license_id": "license-123",
        "generation_target_id": target, "request_number": request_number, "attempt": 1,
        "model": "gpt-image-2-4k", "quality": "medium", "api_size": "2560x3840",
        "effective_prompt_sha256": hashlib.sha256(b"prompt").hexdigest(),
        "original_plan_sha256": "a" * 64,
    }


class ImageDownloadReceiptTests(unittest.TestCase):
    def test_encrypted_pending_roundtrip_and_materialized_gate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
            context = context_for(directory)
            identifier = receipts.save_returned_url(context, PRIVATE_URL)
            path = Path(directory) / "job-123" / "00000003.json"
            contents = path.read_text()
            self.assertNotIn("private", contents)
            self.assertNotIn("https", contents)
            self.assertEqual(len(identifier), 64)
            self.assertEqual(receipts.load_pending_url(context), PRIVATE_URL)
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.assert_no_pending_for_job(directory, "job-123")
            self.assertTrue(receipts.mark_materialized(context, "b" * 64))
            receipts.assert_no_pending_for_job(directory, "job-123")
            self.assertTrue(receipts.mark_materialized(context, "b" * 64))
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.mark_materialized(context, "c" * 64)

    def test_existing_receipt_never_overwritten_or_rebound(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
            context = context_for(directory)
            receipts.save_returned_url(context, PRIVATE_URL)
            path = Path(directory) / "job-123" / "00000003.json"
            before = path.read_bytes()
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.save_returned_url(context, "https://other.example.invalid/image")
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.load_pending_url(dict(context, generation_target_id="different:target"))
            self.assertEqual(path.read_bytes(), before)

    def test_plaintext_status_tampering_cannot_clear_pending(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
            context = context_for(directory)
            receipts.save_returned_url(context, PRIVATE_URL)
            path = Path(directory) / "job-123" / "00000003.json"
            value = json.loads(path.read_bytes())
            value.update(state="materialized", raw_sha256="b" * 64)
            path.write_text(json.dumps(value))
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.assert_no_pending_for_job(directory, "job-123")

    def test_atomic_failure_leaves_blocking_claim_and_safe_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
            context = context_for(directory)
            with patch.object(receipts.os, "replace", side_effect=OSError(PRIVATE_URL)):
                with self.assertRaises(receipts.ReturnedImageDownloadError) as caught:
                    receipts.save_returned_url(context, PRIVATE_URL)
            self.assertIsNone(caught.exception.__context__)
            self.assertNotIn("private", str(caught.exception))
            self.assertTrue((Path(directory) / "job-123" / "00000003.claim").exists())
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.assert_no_pending_for_job(directory, "job-123")
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.assert_no_pending_for_target(directory, "job-123", context["generation_target_id"])
            receipts.assert_no_pending_for_target(directory, "job-123", "other:target")

    def test_target_gate_ignores_other_inflight_but_rejects_same_target(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
            context = context_for(directory)
            receipts.save_returned_url(context, PRIVATE_URL)
            receipts.preflight_context(context_for(directory, request_number=4, target="other:target"))
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.preflight_context(context_for(directory, request_number=4))

    def test_disappeared_claim_or_temp_requires_verified_final_receipt(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
            context = context_for(directory)
            receipts.save_returned_url(context, PRIVATE_URL)
            job = Path(directory) / "job-123"
            for stale in (job / "00000003.claim", job / "00000003.json.stale.tmp"):
                with self.subTest(stale=stale.name), patch.object(Path, "iterdir", return_value=iter([stale])):
                    receipts.assert_no_pending_for_target(directory, "job-123", "other:target")
                with patch.object(Path, "iterdir", return_value=iter([stale])):
                    with self.assertRaises(receipts.ReturnedImageDownloadError):
                        receipts.assert_no_pending_for_target(directory, "job-123", context["generation_target_id"])
            receipts.mark_materialized(context, "b" * 64)
            with patch.object(Path, "iterdir", return_value=iter([job / "00000003.claim"])):
                receipts.assert_no_pending_for_target(directory, "job-123", context["generation_target_id"])
            with patch.object(Path, "iterdir", return_value=iter([job / "00000004.claim"])):
                with self.assertRaises(receipts.ReturnedImageDownloadError):
                    receipts.assert_no_pending_for_target(directory, "job-123", "other:target")

    def test_other_thread_cannot_observe_half_published_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
            context = context_for(directory)
            writing, allow_publish, checking = threading.Event(), threading.Event(), threading.Event()
            original = receipts._write_atomic
            def paused_write(*args):
                writing.set()
                if not allow_publish.wait(2):
                    raise AssertionError("publication was not released")
                return original(*args)
            def other_target_check():
                checking.set()
                receipts.assert_no_pending_for_target(directory, "job-123", "other:target")
            with patch.object(receipts, "_write_atomic", side_effect=paused_write), ThreadPoolExecutor(max_workers=2) as executor:
                saved = executor.submit(receipts.save_returned_url, context, PRIVATE_URL)
                self.assertTrue(writing.wait(2))
                checked = executor.submit(other_target_check)
                self.assertTrue(checking.wait(2))
                try:
                    self.assertFalse(checked.done())
                finally:
                    allow_publish.set()
                self.assertEqual(len(saved.result(timeout=2)), 64)
                checked.result(timeout=2)

    def test_unsupported_encryption_has_no_files_or_unsafe_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(receipts, "_dpapi", side_effect=OSError(PRIVATE_URL)):
                with self.assertRaises(receipts.ReturnedImageDownloadError) as caught:
                    receipts.preflight_context(context_for(directory))
            self.assertIsNone(caught.exception.__context__)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_no_receipt_base64_materialization_is_noop_before_hash_check(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(receipts.mark_materialized(context_for(directory), None))
            receipts.assert_no_pending_for_job(directory, "job-123")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_bad_paths_and_corrupt_receipts_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
            context = context_for(directory)
            for change in ({"job_id": "../escape"}, {"root": "relative"}, {"request_number": True},
                           {"effective_prompt_sha256": "private"}):
                with self.subTest(change=change), self.assertRaises(receipts.ReturnedImageDownloadError):
                    receipts.preflight_context(dict(context, **change))
            job = Path(directory) / "job-123"
            job.mkdir(exist_ok=True)
            (job / "00000003.json").write_bytes(b"partial")
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.assert_no_pending_for_job(directory, "job-123")

    @unittest.skipUnless(os.name == "nt", "Windows CurrentUser DPAPI smoke")
    def test_windows_dpapi_memory_roundtrip(self):
        receipts.preflight_receipt_support()

    @unittest.skipUnless(os.name == "nt", "Windows CurrentUser DPAPI smoke")
    def test_windows_dpapi_dummy_url_roundtrip_and_entropy_tamper(self):
        # Dummy .invalid URL only: no network, API credentials or real responses.
        with tempfile.TemporaryDirectory() as directory:
            context = context_for(directory)
            receipts.preflight_receipt_support()
            receipts.save_returned_url(context, PRIVATE_URL)
            self.assertEqual(receipts.load_pending_url(context), PRIVATE_URL)
            receipts.mark_materialized(context, "b" * 64)
            receipts.assert_no_pending_for_job(directory, "job-123")
            encrypted = receipts._dpapi(b"dummy", b"entropy-a", decrypt=False)
            with self.assertRaises(OSError):
                receipts._dpapi(encrypted, b"entropy-b", decrypt=True)


if __name__ == "__main__":
    unittest.main()
