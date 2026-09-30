import json
import unittest
from pathlib import Path
from generate_group_prompts import cover_prompt_v3
from tools.road_signboard_variants import choose_signboard, SERVICES


class SignboardVariantsTests(unittest.TestCase):
    def test_diversity_and_category_bounds(self):
        variants = [choose_signboard(i, 0, narrow=True) for i in range(1241, 1341)]
        self.assertGreater(len({v['title'] for v in variants}), 5)
        self.assertGreater(len({v['business_line'] for v in variants}), 80)
        self.assertEqual(len({v['material'] for v in variants}), 6)
        for v in variants:
            self.assertEqual(v['title'], v['name_prefix'] + v['name_suffix'])
            self.assertEqual(v['title'], v['store_name'])
            self.assertNotIn(v['title'], ['汽车救援', '道路救援', '拖车服务'])
            self.assertTrue(set(v['services']).issubset(SERVICES))
            self.assertTrue(3 <= len(v['services']) <= 4)
            self.assertEqual(len(v['services']), len(set(v['services'])))
    def test_phone_remains_input_and_layout_is_reproducible(self):
        root = Path(__file__).resolve().parent.parent
        library = json.loads((root/'projects/road_rescue/cover_scene_library.json').read_text(encoding='utf-8'))
        profile = json.loads((root/'projects/road_rescue/cover_visual_profile_v3.json').read_text(encoding='utf-8'))
        a = cover_prompt_v3(1241, library, profile, ['15795643941'])
        b = cover_prompt_v3(1241, library, profile, ['19986904047'])
        self.assertEqual(a[1]['signboard_variant'], b[1]['signboard_variant'])
        self.assertEqual(a[1]['phones'], ['15795643941'])
        self.assertEqual(b[1]['phones'], ['19986904047'])
        self.assertEqual(a, cover_prompt_v3(1241, library, profile, ['15795643941']))
        self.assertNotIn('较小店名只写', a[0])
        self.assertEqual(a[1]['store_name'], a[1]['signboard_variant']['store_name'])
        self.assertIn(a[1]['store_name'], a[0])
