from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
from tools import category_image_production as production


class CoverTypographyTests(unittest.TestCase):
    def test_ten_services_use_distinct_nonoverlapping_boxes(self):
        signatures = set()
        for height in (1408, 1472, 1536):
            for layout in production.COVER_SERVICE_LAYOUTS:
                boxes = production._cover_service_boxes(1024, height, layout, 10)
                self.assertEqual(len(boxes), 10)
                signatures.add(tuple(boxes))
                for i, (left, top, right, bottom) in enumerate(boxes):
                    self.assertTrue(0 <= left < right <= 1024)
                    self.assertTrue(height * .70 <= top < bottom <= height)
                    for other in boxes[i + 1:]:
                        self.assertTrue(right <= other[0] or other[2] <= left or
                                        bottom <= other[1] or other[3] <= top)
        self.assertEqual(len(signatures), 9)

    def test_render_styles_preserve_signboard_and_require_review(self):
        items = ['汽车救援', '搭电救援', '拖车服务', '补胎换胎', '送油救援',
                 '困境救援', '地库救援', '车辆救援', '高速救援', '城市路救援']
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'raw.png'
            background = Image.new('RGB', (1024, 1536), (83, 117, 149))
            background.save(source)
            hashes = set()
            for group in range(1, 5):
                target = root / f'{group}.png'
                result = production.apply_overlays(source, target, '400-677-1311',
                    'cover', group, 1, items, category_id='road_rescue')
                self.assertFalse(result['approved'])
                self.assertEqual(result['status'], 'needs_user_review')
                self.assertTrue(all(item in result['expected_text'] for item in items))
                self.assertEqual(result['overlay_style']['typography_version'], 1)
                hashes.add(result['image_sha256'])
                with Image.open(target) as image:
                    self.assertIsNone(ImageChops.difference(
                        background.crop((0, 0, 1024, 640)), image.crop((0, 0, 1024, 640))).getbbox())
            self.assertEqual(len(hashes), 4)

    def test_phone_and_long_service_text_fit_at_all_heights(self):
        draw = ImageDraw.Draw(Image.new('RGB', (1024, 1536)))
        for height in (1408, 1472, 1536):
            for layout in production.COVER_SERVICE_LAYOUTS:
                for box in production._cover_service_boxes(1024, height, layout, 10):
                    font = production._fit_font(draw, '城市路救援', int((box[2]-box[0])*.90),
                        min(int(1024*.043), int((box[3]-box[1])*.62)), min_size=15, stroke=2)
                    bounds = draw.textbbox((0, 0), '城市路救援', font=font, stroke_width=2)
                    self.assertLessEqual(bounds[2]-bounds[0], box[2]-box[0])
                    self.assertLessEqual(bounds[3]-bounds[1], box[3]-box[1])
        for phone in ('电话：400-677-1311', '电话：13800138000'):
            font = production._fit_font(draw, phone, 921, 83, stroke=6)
            bounds = draw.textbbox((0, 0), phone, font=font, stroke_width=6)
            self.assertLessEqual(bounds[2]-bounds[0], 921)


if __name__ == '__main__':
    unittest.main()
