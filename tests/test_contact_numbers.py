from __future__ import annotations

import unittest

from tools.contact_numbers import (
    contains_contact_number,
    extract_contact_numbers,
    is_canonical_contact_number,
    normalize_contact_number,
)


class ContactNumberTests(unittest.TestCase):
    def test_mobile_numbers_keep_legacy_canonical_form(self) -> None:
        self.assertEqual(normalize_contact_number("138 0013 8000"), "13800138000")
        self.assertTrue(is_canonical_contact_number("13800138000"))

    def test_400_hotline_keeps_stable_hyphenated_display_form(self) -> None:
        self.assertEqual(normalize_contact_number("4006771311"), "400-677-1311")
        self.assertEqual(normalize_contact_number("400-677-1311"), "400-677-1311")
        self.assertTrue(is_canonical_contact_number("400-677-1311"))
        self.assertFalse(is_canonical_contact_number("4006771311"))

    def test_extracts_mobile_and_400_numbers_without_partial_matches(self) -> None:
        text = "电话：400-677-1311，备用联系电话：13800138000"
        self.assertEqual(
            extract_contact_numbers(text),
            ["400-677-1311", "13800138000"],
        )
        self.assertTrue(contains_contact_number(text))
        self.assertFalse(contains_contact_number("订单号140067713119"))

    def test_rejects_invalid_400_numbers(self) -> None:
        for value in ("400-67-1311", "400-677-131", "800-677-1311"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_contact_number(value)


if __name__ == "__main__":
    unittest.main()
