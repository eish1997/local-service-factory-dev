"""Local causal-prompt regressions; no image, network, or environment access."""
import copy
import json
import unittest
from pathlib import Path

from tools.business_ktv.scene import initial_strategy, prompt, sample

ROOT = Path(__file__).resolve().parents[1]


class BusinessKtvRealismTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'configs/business_ktv/scene_library.json').read_text(encoding='utf-8'))

    def forced(self, **variables):
        config = copy.deepcopy(self.config)
        for key, value in variables.items():
            config['variables'][key] = [value]
        return config

    def test_freshly_prepared_scene_keeps_event_drinks_fruit_and_traces_consistent(self):
        for room in ('酒水准备完成的空包', '商务KTV中包'):
            config = self.forced(ROOM_TYPE=room, TABLE_STATE='刚整理完成',
                                 DRINKS='已开封饮料与半杯饮品', FRUIT='已取走少量水果的果盘')
            strategy = initial_strategy(config)
            for seed in range(16):
                with self.subTest(room=room, seed=seed):
                    scene = sample(config, strategy, seed)
                    text = prompt(scene, config, strategy)
                    self.assertEqual(scene['TABLE_STATE'], '刚整理完成')
                    self.assertEqual(scene['event'], config['realism_profile']['events']['刚整理完成'])
                    self.assertEqual(scene['DRINKS'], '酒水准备盘与空杯')
                    self.assertEqual(scene['FRUIT'], '少量哈密瓜与圣女果')
                    for stale_state in ('半杯饮品', '已取走', '杯子轻微使用痕迹', '桌面轻微水渍'):
                        self.assertNotIn(stale_state, text)
                    self.assertIn(scene['event'], text)
                    self.assertIn(scene['DRINKS'], text)
                    self.assertIn(scene['FRUIT'], text)

    def test_public_areas_exclude_private_room_objects_events_and_experiments(self):
        for room in ('KTV大厅', 'KTV走廊'):
            for seed in range(8):
                config = self.forced(ROOM_TYPE=room)
                strategy = initial_strategy(config)
                scene = sample(config, strategy, seed)
                scene['experiment'] = 'FAILURE FIXTURE 文字、二维码、物品密度不合格'
                text = prompt(scene, config, strategy)
                with self.subTest(room=room, seed=seed):
                    self.assertEqual(scene['TABLE_STATE'], '不适用')
                    self.assertEqual(scene['TABLE'], '无酒水茶几')
                    for private_fragment in (
                        config['realism_profile']['geometry'], config['realism_profile']['objects'],
                        scene['screen_state'], scene['DRINKS'], scene['FRUIT'], scene['experiment'],
                        '麦克风自然放在', '点歌台只在侧面', '物品密度',
                    ):
                        self.assertNotIn(private_fragment, text)
                    for detail in scene['imperfections']:
                        self.assertFalse(any(word in detail for word in ('杯', '水果', '桌面', '冰桶', '靠枕')))

    def test_corridor_lighting_does_not_reintroduce_private_screen_or_table(self):
        for lighting in ('屏幕光搭配暖白环境灯', '暖白灯'):
            config = self.forced(ROOM_TYPE='KTV走廊', LIGHTING=lighting)
            strategy = initial_strategy(config)
            scene = sample(config, strategy, 5)
            text = prompt(scene, config, strategy)
            with self.subTest(lighting=lighting):
                for private_lighting in ('屏幕如果有画面', '附近桌面', '屏幕附近略凉', '桌子下面'):
                    self.assertNotIn(private_lighting, text)

    def test_targeted_experiment_translates_failure_without_copying_diagnosis(self):
        config = self.forced(ROOM_TYPE='商务KTV中包')
        strategy = initial_strategy(config)
        strategy['focus'] = ['FAILURE FOCUS FIXTURE: 评分低，不应进入图片提示词']
        base = sample(config, strategy, 8, mode='experiment')
        for keyword, repair in config['realism_profile']['targeted_repairs'].items():
            scene = copy.deepcopy(base)
            scene['experiment'] = f'FAILURE EXPERIMENT FIXTURE: {keyword}失败，不能通过审核'
            text = prompt(scene, config, strategy)
            with self.subTest(keyword=keyword):
                self.assertIn(repair, text)
                self.assertNotIn(scene['experiment'], text)
                self.assertNotIn(strategy['focus'][0], text)
                self.assertNotIn('FAILURE', text)
        scene = copy.deepcopy(base)
        scene['experiment'] = 'FAILURE UNKNOWN FIXTURE: 未知诊断'
        text = prompt(scene, config, strategy)
        self.assertNotIn(scene['experiment'], text)
        self.assertNotIn('FAILURE', text)

    def test_configuration_without_realism_profile_preserves_legacy_prompt_path(self):
        config = copy.deepcopy(self.config)
        config.pop('realism_profile')
        strategy = initial_strategy(config)
        for seed in (1, 19, 42):
            with self.subTest(seed=seed):
                scene = sample(config, strategy, seed)
                text = prompt(scene, config, strategy)
                self.assertNotIn('realism_profile_version', scene)
                self.assertNotIn('event', scene)
                self.assertNotIn('screen_state', scene)
                self.assertTrue(text.startswith('中国真实高端商务KTV的'))
                self.assertIn(config['prompt_structures'][0], text)
                self.assertIn('\n排除：', text)
                self.assertIn('\n本轮重点：', text)
                self.assertEqual(text, prompt(sample(config, strategy, seed), config, strategy))

    def test_private_room_layout_relations_cover_all_six_layouts_and_reach_prompt(self):
        relations = self.config['realism_profile']['layout_relations']
        self.assertEqual(len(relations), 6)
        self.assertEqual(set(relations), set(self.config['variables']['LAYOUT']))
        for layout, relation in relations.items():
            config = self.forced(ROOM_TYPE='商务KTV中包', LAYOUT=layout)
            strategy = initial_strategy(config)
            scene = sample(config, strategy, 17)
            text = prompt(scene, config, strategy)
            with self.subTest(layout=layout):
                self.assertTrue(relation.strip())
                self.assertEqual(scene['LAYOUT'], layout)
                self.assertEqual(text.count(relation), 1)
                self.assertIn(relation + config['realism_profile']['geometry'], text)
                for other_layout, other_relation in relations.items():
                    if other_layout != layout:
                        self.assertNotIn(other_relation, text)

    def test_public_areas_do_not_receive_private_layout_relations(self):
        for room, layout in (('KTV大厅', '前台与等候区错位'), ('KTV走廊', '错位包厢门与消防通道')):
            config = self.forced(ROOM_TYPE=room)
            forbidden = 'TEST FIXTURE PRIVATE LAYOUT: 主沙发面对电视且茶几靠近沙发。'
            # Exercise the public branch even if the mapping later gains a matching key.
            config['realism_profile']['layout_relations'][layout] = forbidden
            strategy = initial_strategy(config)
            scene = sample(config, strategy, 29)
            text = prompt(scene, config, strategy)
            with self.subTest(room=room):
                self.assertEqual(scene['LAYOUT'], layout)
                for relation in config['realism_profile']['layout_relations'].values():
                    self.assertNotIn(relation, text)
                self.assertIn('公共区域门洞、墙面和通行地面连续', text)

    def test_frozen_round_one_without_layout_relations_still_builds_prompts(self):
        path = ROOT / 'projects/business_ktv/preferences/history/realism_20260920/round1_scene_library.json'
        frozen = json.loads(path.read_text(encoding='utf-8'))
        self.assertNotIn('layout_relations', frozen['realism_profile'])
        for layout in frozen['variables']['LAYOUT']:
            config = copy.deepcopy(frozen)
            config['variables']['ROOM_TYPE'] = ['商务KTV中包']
            config['variables']['LAYOUT'] = [layout]
            strategy = initial_strategy(config)
            scene = sample(config, strategy, 31)
            text = prompt(scene, config, strategy)
            with self.subTest(layout=layout):
                self.assertIn(layout, text)
                self.assertIn(frozen['realism_profile']['intent'], text)
                self.assertIn(frozen['realism_profile']['geometry'], text)
                self.assertIn(scene['event'], text)
                self.assertEqual(text, prompt(sample(config, strategy, 31), config, strategy))
                for relation in self.config['realism_profile']['layout_relations'].values():
                    self.assertNotIn(relation, text)


if __name__ == '__main__':
    unittest.main()
