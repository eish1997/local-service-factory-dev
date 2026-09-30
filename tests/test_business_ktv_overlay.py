import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import image_generate
from tools import category_image_production as production
from tools.business_ktv import overlay


class BusinessKtvOverlayTests(unittest.TestCase):
    """Local fixture data only: no real contacts, credentials, or API clients."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job_id = 'fixture-completed-api-job'
        self.base = self.root / 'database/business_ktv/api'
        self.run = self.base / 'runs' / self.job_id
        self.output = self.root / 'output/business_ktv/api' / self.job_id
        self.policy_path = self.root / 'configs/business_ktv/local_overlay.json'
        self.contact_path = self.root / '.runtime/projects/business_ktv/business.json'
        self.policy = {
            'category_id': 'business_ktv', 'enabled': True,
            'profile': 'interior_phone_eight_services',
            'phone_source': '.runtime/projects/business_ktv/business.json',
            'service_words': ['商K预定', '豪华包厢', '欢聚时光', '商务聚会',
                              '本地商务', '公司团建', '缤纷果盘', '丰富酒水'],
            'fixture': True,
        }
        self.contact = {'project_id': 'business_ktv', 'user_confirmed': True,
                        'contact_phones': ['13800138000'], 'fixture': True}
        self.state = {'job_id': self.job_id, 'category_id': 'business_ktv',
                      'backend': 'api', 'status': 'completed', 'records': []}
        for index, status in enumerate(('accepted', 'rejected'), 1):
            path = self.output / 'raw' / f'{index:06}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (512, 768), (35 + index * 30, 105, 151)).save(path)
            self.state['records'].append({
                'index': index, 'path': str(path), 'status': status,
                'audit': {'image_sha256': self.digest(path),
                          'production_approved': status == 'accepted',
                          'failure_reasons': [] if status == 'accepted' else ['fixture rejection'],
                          'fixture': True},
            })
        self.write(self.policy_path, self.policy)
        self.write(self.contact_path, self.contact)
        self.write(self.run / 'checkpoint.json', self.state)
        self.write(self.base / 'checkpoint.json',
                   {'job_id': self.job_id, 'path': str(self.run / 'checkpoint.json')})
        for target in ('openai_clients_by_slot', 'ApiGenerator.generate', 'generate_one'):
            if target == 'openai_clients_by_slot':
                guard = patch.object(production, target, side_effect=AssertionError('Fixture forbids API clients'))
            elif target == 'generate_one':
                guard = patch.object(image_generate, target, side_effect=AssertionError('Fixture forbids generation'))
            else:
                guard = patch('tools.business_ktv.api_adapter.' + target,
                              side_effect=AssertionError('Fixture forbids API generation'))
            guard.start()
            self.addCleanup(guard.stop)

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def snapshot(self):
        return {p.relative_to(self.root): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def assert_no_outputs(self):
        self.assertEqual(list(self.output.glob('local_text_*')), [])
        self.assertFalse((self.run / 'local_text_latest.json').exists())

    def test_render_adds_separate_pending_outputs_and_preserves_original_evidence(self):
        before = self.snapshot()
        result = overlay.render_job(self.root, self.job_id)
        self.assertEqual(result['api_requests'], 0)
        self.assertEqual(result['status'], 'awaiting_vision_text')
        self.assertEqual(result['category_id'], 'business_ktv')
        self.assertEqual(result['phone'], '13800138000')
        self.assertEqual(len(result['images']), 2)
        destination = Path(result['directory'])
        self.assertTrue(destination.is_relative_to(self.output))
        for item, source in zip(result['images'], self.state['records']):
            self.assertEqual(item['source_status'], source['status'])
            self.assertEqual(item['source_image_sha256'], source['audit']['image_sha256'])
            self.assertEqual(item['status'], 'awaiting_vision_text')
            self.assertFalse(item['approved'])
            target = Path(item['path'])
            self.assertTrue(target.is_relative_to(destination))
            self.assertEqual(self.digest(target), item['image_sha256'])
            validation = json.loads(target.with_suffix('.validation.json').read_text(encoding='utf-8'))
            self.assertEqual(validation['category_id'], 'business_ktv')
            self.assertEqual(validation['structure_version'], 'business_ktv_independent_photos_v1')
            self.assertEqual(validation['generation_mode'], 'local_text_from_audited_raw')
            self.assertEqual(validation['status'], 'awaiting_vision_text')
            self.assertFalse(validation['approved'])
            self.assertFalse(validation['production_approved'])
            self.assertFalse(validation['manual_visual_approval'])
            self.assertEqual(validation['source_status'], source['status'])
            self.assertEqual(validation['source_audit'], source['audit'])
            self.assertEqual(validation['expected_text'], ['电话：13800138000', *self.policy['service_words']])
        after = self.snapshot()
        for path, content in before.items():
            self.assertEqual(after[path], content, f'Original file changed: {path}')
        pointer = self.run / 'local_text_latest.json'
        for relative in after.keys() - before.keys():
            path = self.root / relative
            self.assertTrue(path.is_relative_to(destination) or path == pointer,
                            f'Unexpected write outside derived output: {path}')

    def test_repeated_render_reuses_manifest_and_keeps_existing_validation(self):
        first = overlay.render_job(self.root, self.job_id)
        validation_path = Path(first['images'][0]['path']).with_suffix('.validation.json')
        validation = json.loads(validation_path.read_text(encoding='utf-8'))
        validation['fixture_review_note'] = 'Existing independent evidence must be retained.'
        self.write(validation_path, validation)
        before = self.snapshot()
        with patch.object(overlay, 'apply_overlays', side_effect=AssertionError('Must reuse local output')):
            second = overlay.render_job(self.root)
        self.assertEqual(second, first)
        self.assertEqual(self.snapshot(), before)

    def test_unconfirmed_or_invalid_fixture_phone_is_rejected(self):
        cases = (
            {'user_confirmed': False},
            {'user_confirmed': 'true'},
            {'contact_phones': []},
            {'contact_phones': ['13800138000', '13900139000']},
            {'contact_phones': ['invalid']},
        )
        for change in cases:
            with self.subTest(change=change):
                self.write(self.contact_path, {**self.contact, **change})
                with self.assertRaises(ValueError):
                    overlay.render_job(self.root, self.job_id)
                self.assert_no_outputs()

    def test_path_traversal_and_dot_job_ids_are_rejected(self):
        for job_id in ('../outside', '..', '.', 'nested/job', 'nested\\job', str(self.root)):
            with self.subTest(job_id=job_id):
                with self.assertRaises(ValueError):
                    overlay.render_job(self.root, job_id)
                self.assert_no_outputs()

    def test_source_sha_mismatch_stops_before_rendering_any_image(self):
        state = copy.deepcopy(self.state)
        state['records'][1]['audit']['image_sha256'] = '0' * 64
        self.write(self.run / 'checkpoint.json', state)
        before = self.snapshot()
        with patch.object(overlay, 'apply_overlays', side_effect=AssertionError('All sources must validate first')):
            with self.assertRaises(ValueError):
                overlay.render_job(self.root, self.job_id)
        self.assertEqual(self.snapshot(), before)
        self.assert_no_outputs()

    def test_incomplete_jobs_are_rejected(self):
        for status in ('generating', 'awaiting_vision', 'stopped', 'budget_exhausted'):
            with self.subTest(status=status):
                self.write(self.run / 'checkpoint.json', {**self.state, 'status': status})
                with self.assertRaises(ValueError):
                    overlay.render_job(self.root, self.job_id)
                self.assert_no_outputs()

    def test_mock_other_category_or_contact_source_cannot_enter(self):
        cases = (
            ('state', {'backend': 'mock'}),
            ('state', {'category_id': 'ktv'}),
            ('policy', {'category_id': 'ktv'}),
            ('contact', {'project_id': 'ktv'}),
            ('policy', {'phone_source': '.runtime/projects/ktv/business.json'}),
        )
        for kind, change in cases:
            with self.subTest(kind=kind, change=change):
                self.write(self.run / 'checkpoint.json', {**self.state, **(change if kind == 'state' else {})})
                self.write(self.policy_path, {**self.policy, **(change if kind == 'policy' else {})})
                self.write(self.contact_path, {**self.contact, **(change if kind == 'contact' else {})})
                with self.assertRaises(ValueError):
                    overlay.render_job(self.root, self.job_id)
                self.assert_no_outputs()


if __name__ == '__main__':
    unittest.main()
