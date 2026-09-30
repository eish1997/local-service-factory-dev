import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops
from tools import category_image_production as production
from tools.prompt_engine import load_category_config


class KtvOverlayTests(unittest.TestCase):
    def test_interior_cover_and_detail_use_confirmed_words_at_9_16(self):
        config = load_category_config('ktv')
        words = config['service_buttons']
        self.assertEqual(words, ['商K预定', '豪华包厢', '欢聚时光', '商务聚会',
                                 '本地商务', '公司团建', '缤纷果盘', '丰富酒水'])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / 'raw.png'
            Image.new('RGB', (1024, 1536), (83, 117, 149)).save(raw)
            with patch.object(production, '_direct_signboard_overlay',
                              side_effect=AssertionError('KTV must not paint a signboard')):
                for role in ('cover', 'detail'):
                    target = root / f'{role}.png'
                    result = production.apply_overlays(raw, target, '13800138000',
                        role, 1, 1, words, final_size='864x1536', category_id='ktv',
                        service_role='包厢细节', structure_version=config['image_group_structure']['structure_version'])
                    self.assertEqual(result['final_size'], '864x1536')
                    self.assertFalse(result['approved'])
                    self.assertEqual(result['expected_text'][:9], ['电话：13800138000', *words])
                    with Image.open(target) as image:
                        self.assertEqual(image.size, (864, 1536))
                        if role == 'cover':
                            plain = Image.new('RGB', (864, 600), (83, 117, 149))
                            self.assertIsNone(ImageChops.difference(plain, image.crop((0, 0, 864, 600))).getbbox())
                    if role == 'cover':
                        self.assertEqual(result['overlay_style']['signboard_style'], 'not_applicable_interior')
                        self.assertEqual(result['overlay_style']['service_layout'], 'four_by_two')

    def test_triptych_composes_then_adds_all_eight_words(self):
        config = load_category_config('ktv')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = []
            for i, label in enumerate(('包厢空间', '酒水桌面', '大型水果拼盘'), 1):
                raw = root / f'panel{i}.png'
                Image.new('RGB', (1024, 1536), (i*60, 80, 100)).save(raw)
                records.append(dict(raw_target=str(raw), panel_index=i, index=i,
                    generation_kind='triptych_panel', generation_target_id=f'ktv:test:{i}',
                    delivery_target_id='ktv:test:triptych', category_id='ktv', group_index=1,
                    final_size='864x1536', triptych_layout_id='stacked_equal', service_role=label,
                    structure_version=config['image_group_structure']['structure_version']))
            result = production.compose_triptych(records, root / 'triptych.png',
                                                   '13800138000', config['service_buttons'])
            self.assertEqual(result['final_size'], '864x1536')
            self.assertEqual(result['expected_text'][-8:], config['service_buttons'])
            self.assertFalse(result['approved'])
            self.assertEqual(len(result['panel_fingerprints']), 3)


if __name__ == '__main__':
    unittest.main()
