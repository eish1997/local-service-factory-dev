from __future__ import annotations

import io
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import image_generate
from tests.test_image_download_receipts import PRIVATE_URL, context_for, fake_dpapi
from tools import image_download_receipts as receipts


CONFIG = {"provider": "relay", "model": "gpt-image-2-4k", "quality": "medium", "api_size": "2560x3840"}


def response(payload=b"png-bytes", *, headers=None, status=200):
    stream = io.BytesIO(payload)
    return SimpleNamespace(headers=headers or {"Content-Type": "image/png"},
                           getcode=lambda: status, read1=stream.read1, read=stream.read,
                           close=Mock(wraps=stream.close))


class ImageDownloadSafetyTests(unittest.TestCase):
    def test_each_redirect_is_get_without_auth_and_intermediate_body_not_read(self):
        initial = response(status=302, headers={"Location": "/final.png?token=private"})
        initial.read = Mock(side_effect=AssertionError("redirect body was read"))
        initial.read1 = initial.read
        final = response()
        opener = Mock(open=Mock(side_effect=[initial, final]))
        with patch.object(image_generate, "_image_download_opener", return_value=opener):
            self.assertEqual(image_generate.download_image_url(PRIVATE_URL), b"png-bytes")
        self.assertEqual(opener.open.call_count, 2)
        initial.read.assert_not_called()
        initial.close.assert_called_once()
        for call in opener.open.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.data)
            self.assertEqual(set(dict(request.header_items())), {"User-agent"})

    def test_urllib_redirect_error_body_is_closed_not_consumed(self):
        body = Mock()
        redirect = HTTPError(PRIVATE_URL, 302, "private-message", {"Location": "https://new.example.invalid/image"}, body)
        opener = Mock(open=Mock(side_effect=[redirect, response()]))
        with patch.object(image_generate, "_image_download_opener", return_value=opener):
            self.assertEqual(image_generate.download_image_url(PRIVATE_URL), b"png-bytes")
        body.read.assert_not_called()
        body.close.assert_called_once()

    def test_unsafe_redirects_stop_before_next_request(self):
        for url in ("http://images.example.invalid/a", "ftp://images.example.invalid/a", "https://user:pass@images.example.invalid/a", "https://127.0.0.1/a"):
            with self.subTest(url=url):
                opener = Mock(open=Mock(return_value=response(status=302, headers={"Location": url})))
                with patch.object(image_generate, "_image_download_opener", return_value=opener):
                    with self.assertRaises(image_generate.ReturnedImageDownloadError) as caught:
                        image_generate.download_image_url(PRIVATE_URL)
                self.assertEqual(opener.open.call_count, 1)
                self.assertIsNone(caught.exception.__context__)
                self.assertNotIn(url, str(caught.exception))

    def test_redirect_count_is_bounded_to_five(self):
        opener = Mock(open=Mock(side_effect=lambda *a, **k: response(status=302, headers={"Location": "/again"})))
        with patch.object(image_generate, "_image_download_opener", return_value=opener):
            with self.assertRaises(image_generate.ReturnedImageDownloadError):
                image_generate.download_image_url(PRIVATE_URL)
        self.assertEqual(opener.open.call_count, 6)

    def test_declared_and_streamed_byte_limits_reject_safely(self):
        for item in (response(headers={"Content-Type": "image/png", "Content-Length": "9"}), response(b"123456789")):
            with patch.object(image_generate, "MAX_IMAGE_DOWNLOAD_BYTES", 8):
                with patch.object(image_generate, "_image_download_opener", return_value=Mock(open=Mock(return_value=item))):
                    with self.assertRaises(image_generate.ReturnedImageDownloadError):
                        image_generate.download_image_url(PRIVATE_URL)
            item.close.assert_called_once()

    def test_short_body_cannot_be_reported_as_success(self):
        item = response(b"short", headers={"Content-Type": "image/png", "Content-Length": "8"})
        with patch.object(image_generate, "_image_download_opener", return_value=Mock(open=Mock(return_value=item))):
            with self.assertRaises(image_generate.ReturnedImageDownloadError) as caught:
                image_generate.download_image_url(PRIVATE_URL)
        self.assertEqual(caught.exception.error_stage, "image_download_read")
        item.close.assert_called_once()

    def test_http_error_and_timeout_never_leak_url_in_exception_chain(self):
        failures = [TimeoutError(PRIVATE_URL), HTTPError(PRIVATE_URL, 403, "private-token", {}, io.BytesIO(b"secret-body"))]
        for error in failures:
            with self.subTest(error_type=type(error).__name__):
                opener = Mock(open=Mock(side_effect=error))
                with patch.object(image_generate, "_image_download_opener", return_value=opener):
                    with self.assertRaises(image_generate.ReturnedImageDownloadError) as caught:
                        image_generate.download_image_url(PRIVATE_URL)
                self.assertIsNone(caught.exception.__context__)
                self.assertIsNone(caught.exception.__cause__)
                self.assertTrue(caught.exception.retry_forbidden)
                self.assertNotIn("private", json.dumps(image_generate.safe_stage_metadata(caught.exception)))
                opener.open.assert_called_once()

    def test_url_receipt_is_durable_before_get_and_stays_pending_after_download(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
            context = context_for(directory)
            client = SimpleNamespace(images=SimpleNamespace(generate=Mock(return_value=SimpleNamespace(data=[SimpleNamespace(b64_json=None, url=PRIVATE_URL)]))))
            def get(url):
                self.assertEqual(receipts.load_pending_url(context), PRIVATE_URL)
                return b"source"
            with patch.object(image_generate, "download_image_url", side_effect=get):
                self.assertEqual(image_generate.generate_one(client, dict(CONFIG, _image_download_context=context), "prompt"), b"source")
            client.images.generate.assert_called_once()
            with self.assertRaises(receipts.ReturnedImageDownloadError):
                receipts.assert_no_pending_for_job(directory, "job-123")

    def test_failed_download_or_checkpoint_never_reposts(self):
        for checkpoint_failure in (False, True):
            with self.subTest(checkpoint_failure=checkpoint_failure), tempfile.TemporaryDirectory() as directory:
                with patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
                    context = context_for(directory)
                    client = SimpleNamespace(images=SimpleNamespace(generate=Mock(return_value=SimpleNamespace(data=[SimpleNamespace(b64_json=None, url=PRIVATE_URL)]))))
                    save = receipts.save_returned_url
                    with patch.object(receipts, "save_returned_url", side_effect=receipts.ReturnedImageDownloadError() if checkpoint_failure else save):
                        with patch.object(image_generate, "download_image_url", side_effect=TimeoutError(PRIVATE_URL)) as download:
                            with self.assertRaises(image_generate.ReturnedImageDownloadError) as caught:
                                image_generate.generate_one(client, dict(CONFIG, _image_download_context=context), "prompt")
                    client.images.generate.assert_called_once()
                    self.assertEqual(download.call_count, 0 if checkpoint_failure else 1)
                    self.assertIsNone(caught.exception.__context__)
                    self.assertIsNone(caught.exception.__cause__)

    def test_preflight_unsupported_or_binding_mismatch_prevents_post(self):
        with tempfile.TemporaryDirectory() as directory:
            context = context_for(directory)
            client = SimpleNamespace(images=SimpleNamespace(generate=Mock()))
            with patch.object(receipts, "_dpapi", side_effect=OSError("unsupported")):
                with self.assertRaises(image_generate.ReturnedImageDownloadError):
                    image_generate.generate_one(client, dict(CONFIG, _image_download_context=context), "prompt")
            with patch.object(receipts, "_dpapi", side_effect=fake_dpapi):
                with self.assertRaises(image_generate.ReturnedImageDownloadError):
                    image_generate.generate_one(client, dict(CONFIG, _image_download_context=context), "changed prompt")
            client.images.generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
