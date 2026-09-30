"""Future truck sign names vary without renaming any historical group."""

from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter

from tools import truck_rescue_signage as signage


class TruckNames274DiversityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(signage.DEFAULT_LIBRARY_PATH.read_text(encoding="utf-8-sig"))
        cls.candidates = cls.payload["brand_name_candidates"]
        cls.previous = cls.candidates[:180]
        cls.additions = cls.candidates[180:280]
        cls.names = [item["name"] for item in cls.additions]

    def test_historical_180_candidate_records_are_unchanged(self) -> None:
        material = json.dumps(self.previous, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(
            hashlib.sha256(material.encode("utf-8")).hexdigest(),
            "1046a76b837797e4725839932a7b2729aa079618535035c18af61ca47fd5a59e",
        )

    def test_100_new_names_are_unique_safe_two_character_names(self) -> None:
        self.assertEqual(len(self.additions), 100)
        self.assertEqual(len(set(self.names)), 100)
        previous_names = {item["name"] for item in self.previous}
        all_names = previous_names | set(self.names)
        self.assertFalse(previous_names.intersection(self.names))
        for item in self.additions:
            name = item["name"]
            with self.subTest(name=name):
                self.assertRegex(name, r"^[\u4e00-\u9fff]{2}$")
                self.assertNotIn(name, signage.FORBIDDEN_BRAND_NAMES)
                self.assertFalse(name[::-1] in all_names, f"reversed name collision: {name}")
                self.assertFalse(set(name).intersection("驰捷达顺通"))
                self.assertTrue(item["meaning"].strip())
                self.assertIn(item["suffix"], signage.ALLOWED_INDUSTRY_SUFFIXES)

    def test_new_roots_have_broad_character_distribution(self) -> None:
        frequencies = Counter("".join(self.names))
        self.assertGreaterEqual(len(frequencies), 90)
        self.assertLessEqual(max(frequencies.values()), 4)

    def test_neighboring_three_groups_share_no_name_characters(self) -> None:
        # Include the previous three names so the append boundary is covered.
        window = [item["name"] for item in self.previous[-3:]] + self.names
        for position in range(3, len(window)):
            for distance in range(1, 4):
                with self.subTest(name=window[position], distance=distance):
                    self.assertFalse(
                        set(window[position]).intersection(window[position - distance])
                    )

    def test_all_five_industry_suffixes_have_twenty_new_names(self) -> None:
        self.assertEqual(
            Counter(item["suffix"] for item in self.additions),
            Counter({suffix: 20 for suffix in signage.ALLOWED_INDUSTRY_SUFFIXES}),
        )

    def test_new_group_mapping_is_deterministic_and_still_bounded(self) -> None:
        for group_index in range(274, 374):
            with self.subTest(group_index=group_index):
                variant = signage.signage_variant(group_index)
                expected = self.additions[group_index - 274]
                self.assertEqual(variant["brand_name"], expected["name"])
                self.assertEqual(variant["brand_meaning"], expected["meaning"])
                self.assertEqual(variant["full_store_name"], expected["name"] + expected["suffix"])
                self.assertEqual(variant, signage.signage_variant(group_index))
                text = signage.signage_override_text(variant)
                self.assertIn("接近的正常实体字高", text)
                self.assertIn("人工合成的虚构称呼", text)
        first_unavailable = signage.NAMING_EPOCH_GROUP + len(self.candidates)
        with self.assertRaisesRegex(signage.TruckRescueSignageError, "candidates exhausted"):
            signage.signage_variant(first_unavailable)


if __name__ == "__main__":
    unittest.main()
