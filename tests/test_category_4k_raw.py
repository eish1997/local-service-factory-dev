from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.category_4k_raw import (
    ACCEPTED_SOURCE_CONTRACT, RAW_CONTRACT, WIDTH_TOLERANCE_SOURCE_CONTRACT, save_4k_raw_png,
)
from tools.category_image_production import RawImageContractError


GENERATION = {"model": "gpt-image-2-4k", "quality": "medium", "api_size": "1024x1536"}


def payload(size: tuple[int, int]) -> bytes:
    stream = io.BytesIO()
    with Image.new("RGB", size, (35, 70, 110)) as source:
        source.save(stream, "PNG")
    return stream.getvalue()


class Category4KRawTests(unittest.TestCase):
    def save(self, root: Path, data: bytes, **kwargs):
        return save_4k_raw_png(
            root / "raw" / "group_0001" / "01.png", data,
            archive_root=root / "provider_originals", generation=GENERATION,
            credential_epoch="credential-" + "a" * 32, **kwargs,
        )

    def test_4k_source_is_byte_preserved_and_working_raw_downsampled(self):
        for size in ((2560, 3840), (2731, 4096)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                data = payload(size)
                saved = self.save(root, data)
                self.assertEqual(Path(saved["provider_original"]).read_bytes(), data)
                self.assertEqual(saved["source_sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual(saved["raw_contract"], RAW_CONTRACT)
                self.assertEqual(saved["source_returned_size"], f"{size[0]}x{size[1]}")
                working = root / "raw" / "group_0001" / "01.png"
                with Image.open(working) as image:
                    self.assertEqual(image.size, (1024, 1536))
                self.assertEqual(saved["saved_raw_sha256"], hashlib.sha256(working.read_bytes()).hexdigest())
                self.assertFalse(saved["source_is_upscaled_by_factory"])
                self.assertEqual(json.loads(Path(saved["provider_original_metadata"]).read_text()), saved)

    def test_rejects_lower_resolution_landscape_and_unexpected_ratio_but_keeps_evidence(self):
        for size in ((1024, 1536), (2048, 3072), (4096, 2731), (2160, 3840), (3000, 4000)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                data = payload(size)
                with self.assertRaises(RawImageContractError) as caught:
                    self.save(root, data)
                evidence = caught.exception.evidence
                self.assertEqual(evidence["archive_status"], "rejected")
                self.assertEqual(Path(evidence["provider_original"]).read_bytes(), data)
                self.assertFalse((root / "raw" / "group_0001" / "01.png").exists())

    def test_corrupt_response_is_preserved_without_working_image(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RawImageContractError) as caught:
                self.save(Path(folder), b"invalid-image-response")
            self.assertEqual(Path(caught.exception.evidence["provider_original"]).read_bytes(), b"invalid-image-response")

    def test_existing_raw_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "raw" / "group_0001" / "01.png"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"existing-original")
            with self.assertRaises(RawImageContractError):
                self.save(root, b"new")
            self.assertEqual(original.read_bytes(), b"existing-original")

    def test_only_explicit_model_uses_adapter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(RawImageContractError):
                save_4k_raw_png(root / "01.png", b"new", archive_root=root / "archive",
                                generation={**GENERATION, "model": "gpt-image-2"}, credential_epoch="epoch")
            self.assertFalse((root / "archive").exists())

    def test_explicit_exact_source_contract_preserves_earlier_rejection_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = payload((2352, 3520))
            with self.assertRaises(RawImageContractError) as rejected:
                self.save(root, data)
            old_evidence = rejected.exception.evidence
            original = Path(old_evidence["provider_original"])
            old_sidecar = Path(old_evidence["provider_original_metadata"])
            old_metadata_bytes = old_sidecar.read_bytes()
            saved = self.save(root, data, accepted_source_size="2352x3520")
            self.assertEqual(saved["raw_contract"], ACCEPTED_SOURCE_CONTRACT)
            self.assertEqual(saved["source_returned_size"], "2352x3520")
            self.assertEqual(saved["accepted_source_size"], "2352x3520")
            self.assertEqual(saved["normalization_mode"], "accepted_source_lanczos_downsample_legacy")
            self.assertEqual(original.read_bytes(), data)
            self.assertEqual(old_sidecar.read_bytes(), old_metadata_bytes)
            self.assertNotEqual(saved["provider_original_metadata"], str(old_sidecar))
            self.assertEqual(saved["prior_provider_original_metadata"], str(old_sidecar))
            with Image.open(root / "raw" / "group_0001" / "01.png") as image:
                self.assertEqual(image.size, (1024, 1536))
            self.assertEqual(json.loads(Path(saved["provider_original_metadata"]).read_text()), saved)

    def test_explicit_source_contract_accepts_no_other_dimensions(self):
        for size in ((2352, 3519), (2351, 3520), (3520, 2352), (2560, 3840), (1024, 1536)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                with self.assertRaises(RawImageContractError) as rejected:
                    self.save(root, payload(size), accepted_source_size="2352x3520")
                self.assertEqual(rejected.exception.evidence["raw_contract"], ACCEPTED_SOURCE_CONTRACT)
                self.assertFalse((root / "raw" / "group_0001" / "01.png").exists())

    def test_arbitrary_explicit_source_size_is_rejected_without_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(RawImageContractError):
                self.save(root, b"unused", accepted_source_size="1024x1536")
            self.assertFalse((root / "provider_originals").exists())

    def test_explicit_width_tolerance_accepts_only_two_bound_source_sizes(self):
        for size in ((2336, 3520), (2352, 3520)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                data = payload(size)
                saved = self.save(root, data, accepted_source_size="2352x3520",
                                  accepted_source_width_tolerance=16)
                self.assertEqual(saved["raw_contract"], WIDTH_TOLERANCE_SOURCE_CONTRACT)
                self.assertEqual(saved["accepted_source_width_tolerance"], 16)
                self.assertEqual(saved["source_returned_size"], f"{size[0]}x{size[1]}")
                self.assertEqual(Path(saved["provider_original"]).read_bytes(), data)
                self.assertEqual(saved["source_sha256"], hashlib.sha256(data).hexdigest())
                self.assertFalse(saved["source_is_upscaled_by_factory"])
                with Image.open(root / "raw" / "group_0001" / "01.png") as working:
                    self.assertEqual(working.size, (1024, 1536))
                self.assertEqual(json.loads(Path(saved["provider_original_metadata"]).read_text()), saved)

    def test_width_tolerance_does_not_accept_intermediate_wider_or_wrong_height_images(self):
        for size in ((2335, 3520), (2337, 3520), (2344, 3520), (2351, 3520),
                     (2353, 3520), (2368, 3520), (2336, 3519), (3520, 2336)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                with self.assertRaises(RawImageContractError) as rejected:
                    self.save(root, payload(size), accepted_source_size="2352x3520",
                              accepted_source_width_tolerance=16)
                self.assertEqual(rejected.exception.evidence["raw_contract"], WIDTH_TOLERANCE_SOURCE_CONTRACT)
                self.assertEqual(rejected.exception.evidence["accepted_source_width_tolerance"], 16)
                self.assertFalse((root / "raw" / "group_0001" / "01.png").exists())

    def test_width_tolerance_requires_exact_integer_and_explicit_anchor(self):
        for anchor, tolerance in ((None, 16), ("2352x3520", 8), ("2352x3520", -16),
                                  ("2352x3520", 16.0), ("2352x3520", True), ("2352x3520", "16")):
            with self.subTest(anchor=anchor, tolerance=tolerance), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                with self.assertRaises(RawImageContractError):
                    self.save(root, b"unused", accepted_source_size=anchor,
                              accepted_source_width_tolerance=tolerance)
                self.assertFalse((root / "provider_originals").exists())

    def test_width_tolerance_preserves_exact_contract_rejection_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = payload((2336, 3520))
            with self.assertRaises(RawImageContractError) as rejected:
                self.save(root, data, accepted_source_size="2352x3520")
            old_sidecar = Path(rejected.exception.evidence["provider_original_metadata"])
            old_bytes = old_sidecar.read_bytes()
            saved = self.save(root, data, accepted_source_size="2352x3520",
                              accepted_source_width_tolerance=16)
            self.assertEqual(old_sidecar.read_bytes(), old_bytes)
            self.assertNotEqual(saved["provider_original_metadata"], str(old_sidecar))
            self.assertEqual(saved["prior_provider_original_metadata"], str(old_sidecar))
            self.assertEqual(saved["raw_contract"], WIDTH_TOLERANCE_SOURCE_CONTRACT)


if __name__ == "__main__":
    unittest.main()
