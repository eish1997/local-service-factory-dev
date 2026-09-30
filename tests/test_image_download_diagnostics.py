from __future__ import annotations

import binascii
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import httpx
from openai import APITimeoutError

import image_generate
from tools.category_generation_profile import select_profile


CONFIG = {
    "provider": "relay", "base_url": "https://tinysnow.one/v1",
    "model": "gpt-image-2.5-flare", "quality": "medium", "api_size": "1024x1536",
}
PRIVATE_URL = "https://cdn.example/private-image.png?signature=private-test-value"


class ImageDownloadDiagnosticsTests(unittest.TestCase):
    def client(self, *, encoded=None, url=PRIVATE_URL):
        generate = Mock(return_value=SimpleNamespace(
            data=[SimpleNamespace(b64_json=encoded, url=url)],
        ))
        return SimpleNamespace(images=SimpleNamespace(generate=generate))

    def response(self, *, payload=b"image-bytes", error=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {"Content-Type": "image/png"}
        response.getcode.return_value = 200
        response.read1.side_effect = error if error is not None else [payload, b""]
        return response

    def test_sdk_timeout_preserves_original_exception_and_makes_one_post(self):
        client = self.client()
        error = APITimeoutError(request=httpx.Request("POST", "https://api.example/images"))
        client.images.generate.side_effect = error
        with patch.object(image_generate, "_image_download_opener") as download:
            with self.assertRaises(APITimeoutError) as caught:
                image_generate.generate_one(client, CONFIG, "private prompt")
        self.assertIs(caught.exception, error)
        self.assertEqual(image_generate.safe_stage_metadata(error)["error_stage"], "api_generate")
        self.assertEqual(error.response_kind, "unknown")
        client.images.generate.assert_called_once()
        download.assert_not_called()

    def test_download_open_timeout_is_safe_and_does_not_repost(self):
        client = self.client()
        error = TimeoutError("timed out " + PRIVATE_URL)
        with patch("urllib.request.OpenerDirector.open", side_effect=error) as download:
            with self.assertRaises(image_generate.ReturnedImageDownloadError) as caught:
                image_generate.generate_one(client, CONFIG, "private prompt")
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(caught.exception.error_stage, "image_download_open")
        self.assertEqual(caught.exception.response_kind, "url")
        self.assertEqual(download.call_args.kwargs, {"timeout": 60})
        self.assertNotIn("private", json.dumps(image_generate.safe_stage_metadata(caught.exception)))
        client.images.generate.assert_called_once()
        download.assert_called_once()

    def test_download_read_timeout_is_safe_and_does_not_repost(self):
        client = self.client()
        error = TimeoutError("timed out")
        response = self.response(error=error)
        with patch("urllib.request.OpenerDirector.open", return_value=response) as download:
            with self.assertRaises(image_generate.ReturnedImageDownloadError) as caught:
                image_generate.generate_one(client, CONFIG, "prompt")
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(caught.exception.error_stage, "image_download_read")
        self.assertEqual(caught.exception.response_kind, "url")
        self.assertGreaterEqual(caught.exception.elapsed_seconds, 0)
        client.images.generate.assert_called_once()
        download.assert_called_once()
        response.read1.assert_called_once()

    def test_invalid_base64_is_decode_failure_without_url_download(self):
        client = self.client(encoded="a")
        with patch.object(image_generate, "_image_download_opener") as download:
            with self.assertRaises(binascii.Error) as caught:
                image_generate.generate_one(client, CONFIG, "prompt")
        self.assertEqual(caught.exception.error_stage, "image_decode")
        self.assertEqual(caught.exception.response_kind, "base64")
        client.images.generate.assert_called_once()
        download.assert_not_called()

    def test_empty_response_is_decode_failure(self):
        client = self.client(encoded=None, url=None)
        with self.assertRaises(RuntimeError) as caught:
            image_generate.generate_one(client, CONFIG, "prompt")
        self.assertEqual(caught.exception.error_stage, "image_decode")
        self.assertEqual(caught.exception.response_kind, "unknown")
        client.images.generate.assert_called_once()

    def test_successful_base64_keeps_bytes_and_never_downloads(self):
        client = self.client(encoded="aW1hZ2U=")
        with patch.object(image_generate, "download_image_url") as download:
            self.assertEqual(image_generate.generate_one(client, CONFIG, "prompt"), b"image")
        client.images.generate.assert_called_once()
        download.assert_not_called()

    def test_old_url_call_remains_compatible(self):
        client = self.client()
        with patch.object(image_generate, "download_image_url", return_value=b"image") as download:
            self.assertEqual(image_generate.generate_one(client, CONFIG, "prompt"), b"image")
        download.assert_called_once_with(PRIVATE_URL)
        client.images.generate.assert_called_once()

    def test_only_full_new_profile_uses_180_second_socket_timeout(self):
        canonical = select_profile(CONFIG, "truck_rescue", "tinysnow-4k-dual-source-v1")
        invalid_profile = dict(canonical, generation_profile=dict(canonical["generation_profile"], quality="low"))
        configs = [
            (canonical, 180),
            (CONFIG, 60),
            (dict(CONFIG, model="gpt-image-2-4k"), 60),
            (dict(CONFIG, generation_profile="tinysnow-4k-dual-source-v1"), 60),
            (invalid_profile, 60),
            (dict(canonical, model="another-model"), 60),
        ]
        for config, expected in configs:
            with self.subTest(config=config):
                client = self.client()
                with patch("urllib.request.OpenerDirector.open", return_value=self.response()) as download:
                    self.assertEqual(image_generate.generate_one(client, config, "prompt"), b"image-bytes")
                self.assertEqual(download.call_args.kwargs, {"timeout": expected})
                download.assert_called_once()
                client.images.generate.assert_called_once()

    def test_elapsed_metadata_is_phase_local_and_bounded(self):
        error = TimeoutError("private body")
        with patch.object(image_generate.time, "monotonic", side_effect=[10.0, 10.0, 12.34567]):
            with patch("urllib.request.OpenerDirector.open", side_effect=error):
                with self.assertRaises(image_generate.ReturnedImageDownloadError) as caught:
                    image_generate.download_image_url(PRIVATE_URL)
        self.assertEqual(image_generate.safe_stage_metadata(caught.exception), {
            "error_stage": "image_download_open", "elapsed_seconds": 2.346, "response_kind": "url",
        })

    def test_new_profile_download_timeout_never_resubmits_generation(self):
        config = select_profile(CONFIG, "truck_rescue", "tinysnow-4k-dual-source-v1")
        client = self.client()
        error = TimeoutError("timed out")
        with patch("urllib.request.OpenerDirector.open", side_effect=error) as download:
            with self.assertRaises(image_generate.ReturnedImageDownloadError) as caught:
                image_generate.generate_one(client, config, "prompt")
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(caught.exception.error_stage, "image_download_open")
        self.assertEqual(download.call_args.kwargs, {"timeout": 180})
        client.images.generate.assert_called_once()
        download.assert_called_once()

    def test_read_only_exception_diagnostics_do_not_mask_original_failure(self):
        class ReadOnlyError(Exception):
            def __setattr__(self, name, value):
                raise RuntimeError("attributes unavailable")

        error = ReadOnlyError("original error")
        client = self.client()
        client.images.generate.side_effect = error
        with self.assertRaises(ReadOnlyError) as caught:
            image_generate.generate_one(client, CONFIG, "prompt")
        self.assertIs(caught.exception, error)
        self.assertEqual(image_generate.safe_stage_metadata(error), {})

    def test_metadata_rejects_untrusted_values_without_exception_text(self):
        error = RuntimeError("private prompt key URL response body")
        error.error_stage = "api_generate"
        error.elapsed_seconds = 1.234567
        error.response_kind = "url"
        error.url = PRIVATE_URL
        error.api_key = "private-key"
        self.assertEqual(image_generate.safe_stage_metadata(error), {
            "error_stage": "api_generate", "elapsed_seconds": 1.235, "response_kind": "url",
        })
        for invalid in (float("nan"), float("inf"), -1, 86401, 10 ** 400, True, "private"):
            error.elapsed_seconds = invalid
            self.assertNotIn("elapsed_seconds", image_generate.safe_stage_metadata(error))
        error.response_kind = ["url"]
        self.assertNotIn("response_kind", image_generate.safe_stage_metadata(error))
        for invalid in (PRIVATE_URL, ["api_generate"], None):
            error.error_stage = invalid
            self.assertEqual(image_generate.safe_stage_metadata(error), {})
        self.assertEqual(image_generate.safe_stage_metadata(RuntimeError("private")), {})


if __name__ == "__main__":
    unittest.main()
