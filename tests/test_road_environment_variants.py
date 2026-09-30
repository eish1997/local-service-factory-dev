import json
import unittest
from pathlib import Path
from generate_group_prompts import cover_prompt_v3
from tools.road_environment_variants import ENVIRONMENTS, choose_incidental


class EnvironmentTests(unittest.TestCase):
    def test_incidental_elements_remain_optional_for_every_environment(self):
        for env in ENVIRONMENTS:
            choices = [choose_incidental(env, g) for g in range(1240, 1440)]
            self.assertTrue(any(not v['selected'] for v in choices))
            self.assertEqual(set().union(*(set(v['selected']) for v in choices)),
                             {'tree', 'cyclist', 'traffic', 'pedestrian'})
            self.assertTrue(all(len(v['selected']) <= 2 for v in choices))
            self.assertEqual(choices[0], choose_incidental(env, 1240))
            if env['id'] == 'suburban_courtyard':
                self.assertTrue(all('院内作业区不穿行' in v['placement'] for v in choices))

    def test_environment_rotation_and_consistency(self):
        root = Path(__file__).resolve().parent.parent
        library = json.loads((root/'projects/road_rescue/cover_scene_library.json').read_text(encoding='utf-8'))
        profile = json.loads((root/'projects/road_rescue/cover_visual_profile_v3.json').read_text(encoding='utf-8'))
        pairs = set()
        previous = None
        for group in range(1240, 1282):
            prompt, scene = cover_prompt_v3(group, library, profile, ['15795643941'])
            env = scene['environment_plan']
            self.assertNotEqual(previous, env['id'])
            previous = env['id']
            pairs.add((env['id'], scene['composition_family']))
            for key in ('facade', 'ground', 'neighbours', 'activity', 'business'):
                self.assertIn(env[key], prompt)
            self.assertEqual(scene['location'], env['setting'])
            if env['camera_area'] == 'yard':
                self.assertNotIn('街对面', scene['camera_instruction'])
                self.assertNotIn('路缘', scene['foreground'])
            self.assertIn('单开间' if env['bays'] == 1 else '两开间', scene['sign_shape'])
            self.assertEqual(scene['phones'], ['15795643941'])
        self.assertEqual(len(pairs), 42)
