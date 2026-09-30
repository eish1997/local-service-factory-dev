import json
import unittest
from pathlib import Path
from generate_group_prompts import cover_prompt_v3
from tools.road_composition_variants import choose_composition


class CompositionTests(unittest.TestCase):
    def test_adjacent_and_cycle_boundaries(self):
        for variant in (0, 1, 3):
            values = [choose_composition(i, variant) for i in range(1240, 1360)]
            for a, b in zip(values, values[1:]):
                self.assertNotEqual(a['id'], b['id'])
                self.assertNotEqual(a['camera'], b['camera'])
                self.assertNotEqual(a['subject'], b['subject'])
            self.assertEqual(len({v['id'] for v in values[:6]}), 6)

    def test_prompt_uses_one_coherent_plan(self):
        root = Path(__file__).resolve().parent.parent
        library = json.loads((root/'projects/road_rescue/cover_scene_library.json').read_text(encoding='utf-8'))
        profile = json.loads((root/'projects/road_rescue/cover_visual_profile_v3.json').read_text(encoding='utf-8'))
        for i in range(1240, 1252):
            prompt, scene = cover_prompt_v3(i, library, profile, ['15795643941'])
            plan = scene['composition_plan']
            for key in ('camera', 'scale', 'subject', 'activity', 'foreground'):
                self.assertIn(plan[key], prompt)
            self.assertEqual(scene['workshop_activity'], plan['activity'])
            self.assertEqual(scene['phones'], ['15795643941'])
            self.assertIn(scene['store_name'], prompt)
            self.assertIsNone(scene['visual_reality_anchor_id'])
            self.assertEqual((prompt, scene), cover_prompt_v3(i, library, profile, ['15795643941']))
