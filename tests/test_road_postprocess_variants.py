import json
import unittest
from pathlib import Path
from generate_group_prompts import cover_prompt_v3


class PostprocessTests(unittest.TestCase):
    def test_rotation_and_prompt_integration_preserve_other_axes(self):
        root = Path(__file__).resolve().parent.parent
        library = json.loads((root/'projects/road_rescue/cover_scene_library.json').read_text(encoding='utf-8'))
        profile = json.loads((root/'projects/road_rescue/cover_visual_profile_v3.json').read_text(encoding='utf-8'))
        for variant in (0, 2):
            seen = set()
            previous = None
            for group in range(1260, 1276):
                prompt, scene = cover_prompt_v3(group, library, profile, ['15795643941'], variant)
                treatment = scene['postprocess_plan']
                seen.add(treatment['id'])
                self.assertNotEqual(previous, treatment['id'])
                previous = treatment['id']
                for key in ('name', 'color', 'tone', 'texture'):
                    self.assertIn(treatment[key], prompt)
                self.assertEqual(treatment['mode'], 'generation_prompt_only')
                self.assertEqual(scene['phones'], ['15795643941'])
                self.assertIn(scene['store_name'], prompt)
                self.assertIn(scene['camera_instruction'], prompt)
                self.assertIn(scene['environment_plan']['facade'], prompt)
                self.assertEqual((prompt, scene), cover_prompt_v3(group, library, profile, ['15795643941'], variant))
            self.assertEqual(len(seen), 8)
