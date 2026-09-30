"""Offline regressions for reversible modern-interior preferences and old prompts."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

from tools.business_ktv.scene import initial_strategy, prompt, sample

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / 'projects/business_ktv/preferences/history/modern_interior_20260920'


class BusinessKtvModernTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'configs/business_ktv/scene_library.json').read_text(encoding='utf-8'))
        self.frozen = json.loads((HISTORY / 'before_scene_library.json').read_text(encoding='utf-8'))

    def private_config(self):
        config = copy.deepcopy(self.config)
        config['variables']['ROOM_TYPE'] = ['商务KTV中包']
        return config

    def test_preferences_affect_all_modes_without_mutating_learned_strategy(self):
        config = self.private_config()
        # Exercise the mechanism with a fixed fixture, independent of live taste.
        preferred_sofas = {'灰米色模块皮沙发', '烟灰织物沙发'}
        config['style_preferences'] = {
            'source': 'TEST FIXTURE ONLY',
            'selection_multipliers': {
                'SOFA': {value: 3.0 if value in preferred_sofas else .5
                         for value in config['variables']['SOFA']},
            },
        }
        neutral = copy.deepcopy(config)
        neutral.pop('style_preferences')
        strategy = initial_strategy(config)
        strategy.update(version=12, best_realism=91, diagnosis_count=3, focus=['preserved fixture diagnosis'])
        strategy['weights']['SOFA']['灰米色模块皮沙发'] = 1.6
        strategy['combinations'] = {'preserved fixture combination': .7}
        before = copy.deepcopy(strategy)
        for mode in ('inherit', 'explore', 'experiment'):
            neutral_scenes = [sample(neutral, strategy, seed, mode=mode) for seed in range(256)]
            preferred_scenes = [sample(config, strategy, seed, mode=mode) for seed in range(256)]
            neutral_count = sum(s['SOFA'] in preferred_sofas for s in neutral_scenes)
            preferred_count = sum(s['SOFA'] in preferred_sofas for s in preferred_scenes)
            with self.subTest(mode=mode):
                self.assertGreater(preferred_count, neutral_count + 32)
                self.assertEqual({s['SOFA'] for s in preferred_scenes}, set(config['variables']['SOFA']))
                self.assertEqual(strategy, before)

    def test_invalid_preference_factors_fail_before_sampling(self):
        for mode in ('inherit', 'explore', 'experiment'):
            for value in (0, -1, '2', None, True, float('nan'), float('inf'), .09, 5.01):
                config = self.private_config()
                config['style_preferences']['selection_multipliers']['SOFA']['灰米色模块皮沙发'] = value
                strategy = initial_strategy(config)
                with self.subTest(mode=mode, value=value), self.assertRaises(ValueError):
                    sample(config, strategy, 11, mode=mode)

    def test_old_variables_and_nonzero_access_remain_intact(self):
        self.assertEqual(self.config['variables'], self.frozen['variables'])
        self.assertEqual(initial_strategy(self.config)['weights'], initial_strategy(self.frozen)['weights'])
        preferences = self.config['style_preferences']['selection_multipliers']
        for variable, values in self.config['variables'].items():
            for value in values:
                with self.subTest(variable=variable, value=value):
                    self.assertGreater(preferences.get(variable, {}).get(value, 1), 0)
        self.assertEqual(self.config['realism_profile']['lighting_by_choice'],
                         self.frozen['realism_profile']['lighting_by_choice'])
        self.assertEqual(self.config['realism_profile']['public_lighting'],
                         self.frozen['realism_profile']['public_lighting'])

    def test_details_keep_original_furniture_identity_and_reach_prompt(self):
        profile = self.config['realism_profile']
        self.assertEqual(set(profile['sofa_details']), set(self.config['variables']['SOFA']))
        self.assertEqual(set(profile['table_details']), set(self.config['variables']['TABLE']))
        sofa_identity = {
            '灰米色模块皮沙发': ('灰米色', '皮革'),
            '深棕低靠背皮沙发': ('深棕', '皮革'),
            '暗红分段软包沙发': ('暗红', '软包'),
            '烟灰织物沙发': ('烟灰', '织物', '织纹'),
            '驼色皮革长短沙发组合': ('驼色', '皮革', '长短'),
            '深蓝哑光软包沙发': ('深蓝', '哑光', '软包'),
        }
        table_identity = {
            '两张错位低方茶几': ('两张', '低方', '错位'),
            '一张圆角长石材茶几': ('一张', '石材', '长茶几', '圆角'),
            '两张大小不同圆茶几': ('两张', '大小不同', '圆茶几'),
            '单张深木长茶几': ('深木', '长茶几', '木纹'),
            '三张分散方形矮几': ('三张', '方形', '矮几', '分散'),
        }
        for sofa in self.config['variables']['SOFA']:
            for table in self.config['variables']['TABLE']:
                config = self.private_config()
                config['variables']['SOFA'] = [sofa]
                config['variables']['TABLE'] = [table]
                strategy = initial_strategy(config)
                scene = sample(config, strategy, 17)
                text = prompt(scene, config, strategy)
                with self.subTest(sofa=sofa, table=table):
                    self.assertEqual(scene['SOFA'], sofa)
                    self.assertEqual(scene['TABLE'], table)
                    self.assertEqual(scene['sofa_detail'], profile['sofa_details'][sofa])
                    self.assertEqual(scene['table_detail'], profile['table_details'][table])
                    self.assertIn(sofa, text)
                    self.assertIn(table, text)
                    self.assertEqual(text.count(scene['sofa_detail']), 1)
                    self.assertEqual(text.count(scene['table_detail']), 1)
                    for marker in sofa_identity[sofa]:
                        self.assertIn(marker, scene['sofa_detail'])
                    for marker in table_identity[table]:
                        self.assertIn(marker, scene['table_detail'])
                    if sofa == '烟灰织物沙发':
                        self.assertNotIn('皮革', scene['sofa_detail'])
                    if table == '单张深木长茶几':
                        self.assertNotIn('石材台面', scene['table_detail'])
                        self.assertNotIn('玻璃台面', scene['table_detail'])

    def test_prompt_consumes_persisted_details_instead_of_remapping_objects(self):
        config = self.private_config()
        strategy = initial_strategy(config)
        scene = sample(config, strategy, 21)
        for key in ('sofa_details', 'table_details'):
            config['realism_profile'][key] = {
                value: 'UNRELATED REPLACEMENT FIXTURE' for value in config['realism_profile'][key]
            }
        text = prompt(scene, config, strategy)
        self.assertIn(scene['sofa_detail'], text)
        self.assertIn(scene['table_detail'], text)
        self.assertNotIn('UNRELATED REPLACEMENT FIXTURE', text)

    def test_public_areas_do_not_receive_private_furniture_or_screen_wall(self):
        for room in ('KTV大厅', 'KTV走廊'):
            config = copy.deepcopy(self.config)
            config['variables']['ROOM_TYPE'] = [room]
            strategy = initial_strategy(config)
            scene = sample(config, strategy, 23)
            text = prompt(scene, config, strategy)
            with self.subTest(room=room):
                self.assertEqual(scene['sofa_detail'], '')
                self.assertEqual(scene['table_detail'], '')
                for details in ('sofa_details', 'table_details'):
                    for description in config['realism_profile'][details].values():
                        self.assertNotIn(description, text)
                self.assertNotIn('屏幕墙', text)
                self.assertIn(config['realism_profile']['public_lighting'], text)

    def test_frozen_v4_seeds_and_prompts_match_prechange_implementation(self):
        spec = importlib.util.spec_from_file_location('business_ktv_modern_legacy_fixture', HISTORY / 'before_scene.py')
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        self.assertNotIn('style_preferences', self.frozen)
        self.assertNotIn('sofa_details', self.frozen['realism_profile'])
        for mode in ('inherit', 'explore', 'experiment'):
            for seed in (0, 1, 19, 42, 85, 109, 301):
                strategy = old.initial_strategy(self.frozen)
                strategy['weights']['LIGHTING'][self.frozen['variables']['LIGHTING'][0]] = 1.8
                expected = old.sample(self.frozen, strategy, seed, mode=mode)
                actual = sample(self.frozen, strategy, seed, mode=mode)
                if mode == 'experiment':
                    expected['experiment'] = actual['experiment'] = '材质与文字观察 fixture'
                with self.subTest(mode=mode, seed=seed):
                    self.assertEqual(actual, expected)
                    self.assertEqual(prompt(actual, self.frozen, strategy), old.prompt(expected, self.frozen, strategy))


if __name__ == '__main__':
    unittest.main()
