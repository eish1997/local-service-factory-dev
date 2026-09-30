from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools import category_image_production as production


def png_payload(size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, (34, 96, 142))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class RelayRawNormalizationTests(unittest.TestCase):
    def test_exact_size_keeps_strict_raw_contract_without_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "raw" / "group_0316" / "detail_01.png"
            archive_root = root / "production" / "provider_originals" / "job-1"

            result = production.save_raw_png(
                target,
                png_payload(production.RAW_API_SIZE),
                production.RAW_API_SIZE,
                provider="relay",
                archive_root=archive_root,
            )

            self.assertTrue(production.valid_png(target, production.RAW_API_SIZE))
            self.assertFalse(result["normalized"])
            self.assertEqual(result["normalization_mode"], "none")
            self.assertFalse(archive_root.exists())

    def test_relay_941x1672_is_archived_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "raw" / "group_0316" / "detail_02.png"
            archive_root = root / "production" / "provider_originals" / "job-2"
            payload = png_payload((941, 1672))

            result = production.save_raw_png(
                target,
                payload,
                production.RAW_API_SIZE,
                provider="relay",
                archive_root=archive_root,
                anchor_y=0.5,
            )

            original = Path(result["provider_original"])
            metadata_path = Path(result["provider_original_metadata"])
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(original.read_bytes(), payload)
            self.assertTrue(production.valid_png(target, production.RAW_API_SIZE))
            self.assertEqual(result["source_returned_size"], "941x1672")
            self.assertTrue(result["normalized"])
            self.assertEqual(result["normalization_mode"], "lanczos_cover_crop")
            self.assertEqual(metadata["archive_status"], "normalized")
            self.assertEqual(metadata["saved_raw_sha256"], production._file_sha256(target))

    def test_non_relay_size_mismatch_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "raw" / "group_0316" / "detail_03.png"
            archive_root = root / "production" / "provider_originals" / "job-3"

            with self.assertRaises(production.RawImageContractError):
                production.save_raw_png(
                    target,
                    png_payload((941, 1672)),
                    production.RAW_API_SIZE,
                    provider="official",
                    archive_root=archive_root,
                )

            self.assertFalse(target.exists())
            self.assertFalse(archive_root.exists())

    def test_unsafe_relay_shape_is_archived_but_not_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "raw" / "group_0316" / "detail_04.png"
            archive_root = root / "production" / "provider_originals" / "job-4"
            payload = png_payload((640, 640))

            with self.assertRaises(production.RawImageContractError) as raised:
                production.save_raw_png(
                    target,
                    payload,
                    production.RAW_API_SIZE,
                    provider="relay",
                    archive_root=archive_root,
                )

            evidence = raised.exception.evidence
            original = Path(evidence["provider_original"])
            metadata = json.loads(
                Path(evidence["provider_original_metadata"]).read_text(encoding="utf-8")
            )
            self.assertEqual(original.read_bytes(), payload)
            self.assertEqual(metadata["archive_status"], "rejected")
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
