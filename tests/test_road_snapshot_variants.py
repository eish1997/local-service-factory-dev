import json
import unittest
from pathlib import Path
from generate_group_prompts import cover_prompt_v3


class SnapshotTests(unittest.TestCase):
    def test_flaws_are_bounded_and_use_existing_motion(self):
        root = Path(__file__).resolve().parent.parent
        lib = json.loads((root/'projects/road_rescue/cover_scene_library.json').read_text(encoding='utf-8'))
        profile = json.loads((root/'projects/road_rescue/cover_visual_profile_v3.json').read_text(encoding='utf-8'))
        seen, rolls = set(), set()
        for g in range(1260, 1380):
            prompt, scene = cover_prompt_v3(g, lib, profile, ['15795643941'])
            s = scene['snapshot_plan']
            seen.add(s['optical_flaw']); rolls.add(s['roll_degrees'])
            self.assertLessEqual(abs(s['roll_degrees']), 3)
            self.assertIn(s['description'], prompt)
            self.assertIn(s['roll_description'], prompt)
            self.assertEqual(scene['phones'], ['15795643941'])
            self.assertIn(scene['store_name'], prompt)
            self.assertEqual((prompt, scene), cover_prompt_v3(g, lib, profile, ['15795643941']))
            elements = scene['environment_plan']['incidental']['selected']
            if s['optical_flaw'] == 'motion' and not set(elements) & {'cyclist', 'traffic', 'pedestrian'}:
                self.assertIn('师傅', s['motion_target'])
            if scene['postprocess_id'] in {'shared_phone_photo', 'restrained_film', 'muted_soft', 'soft_bright'}:
                self.assertIn('很轻', s['strength'])
        self.assertEqual(seen, {'none', 'motion', 'handshake', 'focus', 'awkward_crop'})
        self.assertTrue({-3, -2, -1, 0, 1, 2, 3}.issubset(rolls))
