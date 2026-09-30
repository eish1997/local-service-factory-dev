import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from tools import category_image_production as production


class BusinessKtvSharedOverlayTests(unittest.TestCase):
    PHONE = '18271918609'
    WORDS = ['商K预定', '豪华包厢', '欢聚时光', '商务聚会',
             '本地商务', '公司团建', '缤纷果盘', '丰富酒水']
    PROFILE = 'interior_phone_eight_services'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def source(self, size=(1536, 1024), name='raw.png'):
        path = self.root / name
        image = Image.new('RGB', size, (83, 117, 149))
        draw = ImageDraw.Draw(image)
        for x in range(0, size[0], 61):
            draw.rectangle((x, 0, min(x + 19, size[0] - 1), size[1] - 1),
                           fill=(x % 251, 54, 180))
        for y in range(0, size[1], 73):
            draw.line((0, y, size[0] - 1, y), fill=(212, y % 251, 91), width=3)
        image.save(path)
        return path

    def overlay(self, raw, target, **overrides):
        options = dict(phone=self.PHONE, role='cover', group_index=1, position=1,
                       service_items=list(self.WORDS), category_id='business_ktv',
                       structure_version='business_ktv_raw_local_overlay_v1',
                       generation_mode='existing_raw_local_overlay',
                       generation_target_id='business_ktv:fixture:raw:1',
                       delivery_target_id='business_ktv:fixture:localtext:1',
                       overlay_profile=self.PROFILE)
        options.update(overrides)
        return production.apply_overlays(raw, target, **options)

    def test_shared_interior_layout_preserves_category_and_explicit_metadata(self):
        raw, target = self.source(), self.root / 'overlay.png'
        with patch.object(production, '_direct_signboard_overlay',
                          side_effect=AssertionError('Interior must not draw a signboard')), \
             patch.object(production, '_fit_image',
                          side_effect=AssertionError('Interior must not crop or resample')):
            result = self.overlay(raw, target, final_size=(1536, 1024))
        self.assertEqual(result['category_id'], 'business_ktv')
        self.assertEqual(result['structure_version'], 'business_ktv_raw_local_overlay_v1')
        self.assertEqual(result['generation_mode'], 'existing_raw_local_overlay')
        self.assertEqual(result['overlay_profile'], self.PROFILE)
        self.assertEqual(result['expected_text'], [f'电话：{self.PHONE}', *self.WORDS])
        self.assertEqual(result['raw_api_size'], '1536x1024')
        self.assertEqual(result['final_size'], '1536x1024')
        self.assertEqual(result['overlay_style']['service_layout'], 'four_by_two')
        self.assertEqual(result['overlay_style']['signboard_style'], 'not_applicable_interior')
        self.assertIsNone(result['overlay_style']['signboard_quad'])
        self.assertFalse(result['approved'])
        self.assertFalse(result['manual_visual_approval'])
        saved = json.loads(target.with_suffix('.validation.json').read_text(encoding='utf-8'))
        self.assertEqual(saved, result)

    def test_native_canvas_and_all_pixels_outside_text_bands_are_unchanged(self):
        for number, size in enumerate(((1536, 1024), (1024, 1536), (512, 768)), 1):
            with self.subTest(size=size):
                raw = self.source(size, f'raw_{number}.png')
                before = hashlib.sha256(raw.read_bytes()).hexdigest()
                target = self.root / f'overlay_{number}.png'
                self.overlay(raw, target)
                self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), before)
                with Image.open(raw) as source, Image.open(target) as output:
                    self.assertEqual(output.size, size)
                    difference = ImageChops.difference(source.convert('RGB'), output.convert('RGB'))
                width, height = size
                phone_box = (int(width * .025), int(height * .43),
                             int(width * .975), int(height * .535))
                footer_box = (int(width * .025), int(height * .80),
                              int(width * .975), int(height * .975))
                self.assertIsNotNone(difference.crop(phone_box).getbbox())
                self.assertIsNotNone(difference.crop(footer_box).getbbox())
                draw = ImageDraw.Draw(difference)
                draw.rectangle(phone_box, fill=(0, 0, 0))
                draw.rectangle(footer_box, fill=(0, 0, 0))
                self.assertIsNone(difference.getbbox())

    def test_profile_overrides_road_layout_without_changing_category(self):
        raw, target = self.source((512, 768)), self.root / 'road_profile.png'
        with patch.object(production, '_direct_signboard_overlay',
                          side_effect=AssertionError('No signboard for interior profile')), \
             patch.object(production, 'road_rescue_bottom_service_style',
                          side_effect=AssertionError('Profile must not inherit road footer')):
            result = self.overlay(raw, target, category_id='road_rescue', group_index=1100)
        self.assertEqual(result['category_id'], 'road_rescue')
        self.assertEqual(result['expected_text'], [f'电话：{self.PHONE}', *self.WORDS])
        self.assertEqual(result['overlay_style']['center_phone_region'], [.025, .43, .975, .535])
        self.assertEqual(result['overlay_style']['bottom_service_region'], [.045, .80, .955, .965])
        self.assertEqual(result['overlay_style']['service_layout'], 'four_by_two')
        self.assertIsNone(result['overlay_style']['bottom_service_style'])

    def test_invalid_profile_role_or_service_words_fail_before_writing(self):
        raw = self.source((512, 768))
        cases = (
            {'overlay_profile': 'unknown'},
            {'role': 'detail'},
            {'service_items': self.WORDS[:-1]},
            {'service_items': self.WORDS + ['多余']},
            {'service_items': self.WORDS[:-1] + [' ']},
            {'service_items': self.WORDS[:-1] + [None]},
        )
        for index, options in enumerate(cases):
            with self.subTest(options=options):
                target = self.root / f'invalid_{index}.png'
                with self.assertRaises(production.CategoryPromptError):
                    self.overlay(raw, target, **options)
                self.assertFalse(target.exists())
                self.assertFalse(target.with_suffix('.validation.json').exists())

    def test_profile_rejects_resizing_or_unsupported_source_dimensions(self):
        raw = self.source((1536, 1024))
        target = self.root / 'invalid_size.png'
        with self.assertRaises(production.CategoryPromptError):
            self.overlay(raw, target, final_size='1024x1536')
        self.assertFalse(target.exists())
        for number, size in enumerate(((511, 768), (8193, 512))):
            with self.subTest(size=size):
                raw = self.source(size, f'invalid_size_{number}.png')
                with self.assertRaises(production.CategoryPromptError):
                    self.overlay(raw, target)
                self.assertFalse(target.exists())

    def test_profile_cannot_replace_the_original(self):
        raw = self.source((512, 768))
        before = raw.read_bytes()
        with self.assertRaises(production.CategoryPromptError):
            self.overlay(raw, raw)
        self.assertEqual(raw.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
