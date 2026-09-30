"""Future-only signboard structure rotation, independent of new name choices."""

import unittest

from tools.truck_rescue_signage import load_signage_library, signage_variant


class TruckSignageRotationV3Tests(unittest.TestCase):
    def test_historical_sign_structure_mapping_is_unchanged(self):
        library = load_signage_library()
        for group_index in range(94, 274):
            offset = group_index - 94
            actual = signage_variant(group_index)
            for key, step, shift in (
                ("sign_information_layout", 2, 0),
                ("sign_accent_detail", 5, 1),
                ("sign_installation_detail", 5, 2),
            ):
                values = library[key + "s"]
                self.assertEqual(actual[key], values[(offset * step + shift) % len(values)])

    def test_future_accent_and_installation_pairs_are_decoupled(self):
        variants = [signage_variant(index) for index in range(274, 374)]
        pairs = [(row["sign_accent_detail"], row["sign_installation_detail"]) for row in variants]
        library = load_signage_library()
        self.assertEqual(
            len(set(pairs)),
            len(library["sign_accent_details"]) * len(library["sign_installation_details"]),
        )
        self.assertTrue(all(first != second for first, second in zip(pairs, pairs[1:])))


if __name__ == "__main__":
    unittest.main()
