import json
import unittest
from pathlib import Path
from generate_group_prompts import cover_prompt_v3


class CaptureDeviceTests(unittest.TestCase):
    def test_device_constraints_and_reproducibility(self):
        root = Path(__file__).resolve().parent.parent
        library = json.loads((root / 'projects/road_rescue/cover_scene_library.json').read_text(encoding='utf-8'))
        profile = json.loads((root / 'projects/road_rescue/cover_visual_profile_v3.json').read_text(encoding='utf-8'))
        shots = {s['id']: s for s in profile['shot_presets']}
        seen = set()
        for group in range(1241, 1361):
            result = cover_prompt_v3(group, library, profile, ['15795643941'])
            self.assertEqual(result, cover_prompt_v3(group, library, profile, ['15795643941']))
            prompt, scene = result
            device = scene['capture_device_id']
            seen.add(device)
            self.assertIn('拍摄设备与成像特征', prompt)
            if device == 'work_phone_dusk':
                self.assertIn(scene['visual_light_id'], ('late_daylight', 'shop_light_dusk'))
            if device == 'phone_two_x':
                self.assertIn('两倍', scene['camera_instruction'])
        self.assertGreaterEqual(len(seen), 4)
