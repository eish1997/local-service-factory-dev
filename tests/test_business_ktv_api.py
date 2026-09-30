"""Offline adapter regressions; all images and vision evidence are TEST FIXTURES.

No test opens .env, creates a real client, or makes a network/image API request.
"""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from tools import business_ktv as plugin
from tools.business_ktv.api_adapter import ApiGenerator
from tools.business_ktv.auditor import CHECKS, SCORES, CodexVisionAuditor, MockAuditor
from tools.category_image_production import atomic_json, load_json
from tools.iteration_engine import IterationEngine, MockGenerator
from tools.project_inventory import image_fingerprint

ROOT = Path(__file__).resolve().parents[1]
SESSION = 'TEST-FIXTURE-VISION-SESSION'
API_CONFIG = {
    'model': 'fixture-image-model', 'quality': 'medium', 'api_size': '1024x1536',
    'provider': 'official', 'base_url': '', 'output_format': 'png',
}


class FixtureApiGenerator(ApiGenerator):
    """Run real scheduling/licensing, replacing only the paid generation call."""

    def __init__(self, config=None, slots=None, payload=None):
        super().__init__(copy.deepcopy(config or API_CONFIG), [1, 2] if slots is None else slots)
        self.calls = []
        self.payload = payload

    def generate(self, record, slot):
        self.calls.append((record['index'], slot))
        return self.payload or MockGenerator().generate(record, 'fixture')


class BusinessKtvApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='business-ktv-api-fixture-', dir=ROOT / '.runtime')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = load_json(ROOT / 'configs/business_ktv/scene_library.json')
        self.config.update(backend='api', vision_session=SESSION)
        for target in (
            'image_generate.load_project_env',
            'image_generate.configured_api_keys',
            'tools.category_image_production.openai_clients_by_slot',
        ):
            guard = patch(target, side_effect=AssertionError('Offline fixture must not read env or create clients'))
            guard.start()
            self.addCleanup(guard.stop)

    def engine(self, generator=None, auditor=None, root=None):
        return IterationEngine(root or self.root, copy.deepcopy(self.config), plugin,
                               generator or FixtureApiGenerator(), auditor or CodexVisionAuditor(SESSION))

    def awaiting(self, count=1, generator=None):
        engine = self.engine(generator=generator)
        engine.create(count)
        state = engine.run()
        self.assertEqual(state['status'], 'awaiting_vision')
        self.assertEqual(state['request_count'], count)
        return engine

    def evidence(self, engine, row, **changes):
        candidates = engine._history() + [r for r in engine.state['records'] if r['index'] != row['index'] and r.get('fingerprint')]
        evidence = {
            **{name: 96 for name in SCORES}, 'ai_artifact_score': 4,
            'fixture_only': True, 'source': 'vision', 'pixels_read': True,
            'reviewer_model': 'TEST-FIXTURE-NOT-A-REAL-VISION-MODEL',
            'reviewed_at': '2026-09-20T00:00:00Z', 'vision_session': SESSION,
            'job_id': engine.state['job_id'], 'index': row['index'],
            'image_sha256': image_fingerprint(Path(row['path']))['file_sha256'],
            'checks': {name: 'pass' for name in CHECKS},
            'observations': {name: 'TEST FIXTURE observation: ' + name for name in CHECKS},
            'structural_description': 'TEST FIXTURE geometric image, not a real KTV photograph',
            'visual_comparisons': [
                {'image_sha256': image_fingerprint(Path(r['path']))['file_sha256'],
                 'similarity_score': 10, 'reason': 'TEST FIXTURE intentionally distinct geometry'}
                for r in candidates
            ],
            'failure_reasons': [], 'success_reasons': ['TEST FIXTURE only'],
        }
        evidence.update(changes)
        return evidence

    def write_evidence(self, engine, row, evidence=None):
        path = Path(row['path']).parent.parent / 'vision' / f"{row['index']:06d}.review.json"
        atomic_json(path, self.evidence(engine, row) if evidence is None else evidence)

    def test_license_records_scoped_budget_slots_and_model(self):
        engine = self.engine()
        state = engine.create(5)
        license = load_json(engine.generator.license_path)
        self.assertEqual(license['job_id'], state['job_id'])
        self.assertEqual(license['planned_images'], 5)
        self.assertEqual(license['max_requests'], 10)
        self.assertEqual(license['key_slots'], [1, 2])
        self.assertEqual(license['api_config'], API_CONFIG)
        self.assertEqual(license['sdk_max_retries'], 0)
        self.assertTrue(license['one_time'])
        self.assertEqual(license['used_requests'], 0)
        self.assertEqual(engine.generator.calls, [])

    def test_empty_duplicate_and_invalid_slots_rejected_before_clients(self):
        for slots in ([], [1, 1], [0], [-1], ['1'], [True]):
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                ApiGenerator(API_CONFIG, slots)

    def test_sample_scope_refuses_sixteen_or_continuous(self):
        for count, continuous in ((16, False), (1, True), (15, True)):
            with self.subTest(count=count, continuous=continuous), self.assertRaises(ValueError):
                self.engine().create(count, continuous=continuous)

    def test_prepare_rejects_unlicensed_slot_and_duplicate_budget(self):
        engine = self.engine()
        state = engine.create(1)
        engine._plan_round()
        row = state['records'][0]
        row.update(attempts=1)
        state['request_count'] = 1
        with self.assertRaises(ValueError):
            engine.generator.prepare_request(state, row, 99)
        engine.generator.prepare_request(state, row, 1)
        self.assertEqual(load_json(engine.generator.license_path)['used_requests'], 1)
        with self.assertRaises(ValueError):
            engine.generator.prepare_request(state, row, 1)
        state['request_count'] = 3
        with self.assertRaises(ValueError):
            engine.generator.prepare_request(state, row, 1)

    def test_prepare_rejects_prompt_tampering_and_excess_retry(self):
        engine = self.engine()
        state = engine.create(1)
        engine._plan_round()
        row = state['records'][0]
        state['request_count'] = 1
        row['attempts'] = 4
        with self.assertRaises(ValueError):
            engine.generator.prepare_request(state, row, 1)
        row['attempts'] = 1
        row['prompt'] += 'tampered'
        with self.assertRaises(ValueError):
            engine.generator.prepare_request(state, row, 1)
        self.assertEqual(load_json(engine.generator.license_path)['used_requests'], 0)

    def test_resume_rejects_changed_api_configuration(self):
        engine = self.awaiting()
        changes = {'model': 'other', 'quality': 'high', 'api_size': '512x512',
                   'provider': 'relay', 'base_url': 'https://fixture.invalid/v1', 'output_format': 'jpeg'}
        for key, value in changes.items():
            config = {**API_CONFIG, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.engine(FixtureApiGenerator(config)).resume()
        with self.assertRaises(ValueError):
            self.engine(FixtureApiGenerator(slots=[1])).resume()
        self.assertEqual(load_json(engine.generator.license_path)['used_requests'], 1)

    def test_license_binding_rejects_task_or_budget_tampering(self):
        engine = self.awaiting()
        original = load_json(engine.generator.license_path)
        for field, value in (('job_id', 'other-job'), ('max_requests', 999),
                             ('planned_images', 999), ('key_slots', [3]), ('used_requests', 3)):
            atomic_json(engine.generator.license_path, {**original, field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.engine().resume()
        atomic_json(engine.generator.license_path, original)

    def test_awaiting_evidence_resume_does_not_generate_again(self):
        engine = self.awaiting()
        row = engine.state['records'][0]
        self.assertEqual(row['status'], 'awaiting_vision')
        self.write_evidence(engine, row)
        resumed = self.engine()
        resumed.resume()
        state = resumed.run()
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['request_count'], 1)
        self.assertEqual(state['success_count'], 1)
        self.assertTrue(state['records'][0]['audit']['production_approved'])
        self.assertEqual(resumed.generator.calls, [])
        self.assertEqual(load_json(resumed.generator.license_path)['status'], 'consumed')
        finished = self.engine()
        finished.resume()
        self.assertEqual(finished.run()['request_count'], 1)
        self.assertEqual(finished.generator.calls, [])

    def test_resume_without_evidence_keeps_image_and_request_count(self):
        engine = self.awaiting()
        before = Path(engine.state['records'][0]['path']).read_bytes()
        resumed = self.engine()
        resumed.resume()
        state = resumed.run()
        self.assertEqual(state['status'], 'awaiting_vision')
        self.assertEqual(state['request_count'], 1)
        self.assertEqual(resumed.generator.calls, [])
        self.assertEqual(Path(state['records'][0]['path']).read_bytes(), before)

    def test_fifteen_photo_batch_requires_complete_vision_and_never_regenerates_on_resume(self):
        engine = self.engine()
        engine.create(15, batch_size=15)
        state = engine.run()
        self.assertEqual(state['status'], 'awaiting_vision')
        self.assertEqual(state['generated_images'], 15)
        self.assertEqual(state['request_count'], 15)
        self.assertEqual(len(engine.generator.calls), 15)
        self.assertTrue(all(r['status'] == 'awaiting_vision' and r['audit'] is None for r in state['records']))
        license = load_json(engine.generator.license_path)
        self.assertEqual((license['planned_images'], license['max_requests'], license['used_requests']), (15, 30, 15))
        original_fingerprints = {r['index']: r['fingerprint']['file_sha256'] for r in state['records']}

        resumed = self.engine()
        resumed.resume()
        self.assertEqual(resumed.run()['status'], 'awaiting_vision')
        self.assertEqual(resumed.generator.calls, [])
        first = resumed.state['records'][0]
        complete = self.evidence(resumed, first)
        comparisons = complete['visual_comparisons']
        self.assertEqual(len({c['image_sha256'] for c in comparisons}), 14)
        for missing in range(14):
            incomplete = copy.deepcopy(complete)
            del incomplete['visual_comparisons'][missing]
            self.write_evidence(resumed, first, incomplete)
            with self.subTest(missing_index=missing + 2), self.assertRaisesRegex(ValueError, '缺少.*结构对照'):
                resumed._review(first)
            self.assertIsNone(first['audit'])
        blocked = resumed.run()
        self.assertEqual(blocked['status'], 'audit_blocked')
        self.assertEqual(blocked['success_count'], 0)
        self.assertEqual(blocked['request_count'], 15)

        for row in resumed.state['records']:
            self.write_evidence(resumed, row)
        finished = self.engine()
        finished.resume()
        state = finished.run()
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['request_count'], 15)
        self.assertEqual(state['generated_images'], 15)
        self.assertEqual(finished.generator.calls, [])
        self.assertTrue(all(r['status'] in ('accepted', 'rejected') for r in state['records']))
        for row in state['records']:
            self.assertEqual(row['fingerprint']['file_sha256'], original_fingerprints[row['index']])
            self.assertEqual(row['audit']['production_approved'], row['status'] == 'accepted')
        license = load_json(finished.generator.license_path)
        self.assertEqual((license['status'], license['used_requests'], license['max_requests']), ('consumed', 15, 30))

    def test_api_constructor_requires_actual_vision_capability(self):
        with self.assertRaises(ValueError):
            self.engine(auditor=MockAuditor())

    def test_mock_and_human_evidence_block_api_approval(self):
        engine = self.awaiting()
        row = engine.state['records'][0]
        for source in ('mock', 'human'):
            self.write_evidence(engine, row, self.evidence(engine, row, source=source))
            resumed = self.engine()
            resumed.resume()
            with self.subTest(source=source):
                state = resumed.run()
                self.assertEqual(state['status'], 'audit_blocked')
                self.assertEqual(state['success_count'], 0)
                self.assertEqual(state['request_count'], 1)
                self.assertEqual(resumed.generator.calls, [])

    def test_cross_job_sha_session_index_and_missing_observation_rejected(self):
        engine = self.awaiting()
        row = engine.state['records'][0]
        invalid = (
            {'job_id': 'other-job'}, {'image_sha256': '0' * 64}, {'vision_session': 'other-session'},
            {'index': 99}, {'observations': {}}, {'reviewer_model': ''}, {'pixels_read': False},
            {'checks': {**{name: 'pass' for name in CHECKS}, '空间结构': 'not_applicable'}},
        )
        for changes in invalid:
            self.write_evidence(engine, row, self.evidence(engine, row, **changes))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                engine.auditor.review(Path(row['path']), row, image_fingerprint(Path(row['path'])))

    def test_pixel_duplicate_rejected_and_never_production_approved(self):
        payload = MockGenerator().generate({'scene': {'seed': 42}}, 'fixture')
        engine = self.awaiting(2, FixtureApiGenerator(payload=payload))
        for row in engine.state['records']:
            self.write_evidence(engine, row)
        resumed = self.engine()
        resumed.resume()
        state = resumed.run()
        self.assertEqual(state['request_count'], 2)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['success_count'], 0)
        for row in state['records']:
            self.assertEqual(row['status'], 'rejected')
            self.assertTrue(row['audit']['diversity_rejected'])
            self.assertFalse(row['audit']['production_approved'])

    def test_missing_visual_comparison_blocks_current_batch(self):
        engine = self.awaiting(2)
        for row in engine.state['records']:
            self.write_evidence(engine, row, self.evidence(engine, row, visual_comparisons=[]))
        resumed = self.engine()
        resumed.resume()
        state = resumed.run()
        self.assertEqual(state['status'], 'audit_blocked')
        self.assertEqual(state['success_count'], 0)
        self.assertEqual(state['request_count'], 2)

    def test_visual_semantic_similarity_is_an_independent_hard_gate(self):
        engine = self.awaiting(2)
        for row in engine.state['records']:
            evidence = self.evidence(engine, row)
            evidence['visual_comparisons'][0]['similarity_score'] = 97
            self.write_evidence(engine, row, evidence)
        resumed = self.engine()
        resumed.resume()
        state = resumed.run()
        self.assertEqual(state['success_count'], 0)
        for row in state['records']:
            self.assertFalse(row['audit']['production_approved'])
            self.assertEqual(row['audit']['visual_similarity_score'], 97)

    def test_mock_and_api_history_outputs_and_best_are_isolated(self):
        config = copy.deepcopy(self.config)
        config['backend'] = 'mock'
        mock = IterationEngine(self.root, config, plugin)
        mock.create(1)
        mock_state = mock.run()
        mock_file = Path(mock_state['records'][0]['path'])
        engine = self.awaiting(generator=FixtureApiGenerator(payload=mock_file.read_bytes()))
        self.assertNotEqual(mock.base, engine.base)
        self.assertEqual(engine._history(), [])
        row = engine.state['records'][0]
        self.write_evidence(engine, row)
        resumed = self.engine()
        resumed.resume()
        state = resumed.run()
        self.assertEqual(state['success_count'], 1)
        self.assertEqual(state['records'][0]['audit']['compared_images'], 0)
        self.assertTrue((self.root / 'output/business_ktv/mock/best').is_dir())
        self.assertTrue((self.root / 'output/business_ktv/api/best').is_dir())

    def test_total_request_budget_is_durable_across_resume(self):
        class Fail(FixtureApiGenerator):
            def generate(self, record, slot):
                self.calls.append((record['index'], slot))
                raise TimeoutError('TEST FIXTURE timeout')
        engine = self.engine(Fail())
        engine.create(1)
        state = engine.run()
        self.assertEqual(state['status'], 'budget_exhausted')
        self.assertEqual(state['request_count'], 2)
        self.assertEqual(load_json(engine.generator.license_path)['used_requests'], 2)
        resumed = self.engine(Fail())
        resumed.resume()
        self.assertEqual(resumed.run()['request_count'], 2)
        self.assertEqual(resumed.generator.calls, [])

    def test_three_consecutive_errors_stop_before_remaining_images(self):
        class Fail(FixtureApiGenerator):
            def generate(self, record, slot):
                raise TimeoutError('TEST FIXTURE timeout')
        engine = self.engine(Fail())
        engine.create(5)
        state = engine.run()
        self.assertEqual(state['status'], 'circuit_open')
        self.assertEqual(state['request_count'], 3)
        self.assertEqual(state['records'][0]['attempts'], 3)
        self.assertEqual(state['generated_images'], 0)

    def test_real_adapter_invokes_shared_primitive_once_and_closes_client(self):
        buffer = io.BytesIO()
        Image.new('RGB', (1024, 1536), 'gray').save(buffer, 'PNG')
        payload = buffer.getvalue()
        client = MagicMock()
        client.with_options.return_value = client
        adapter = ApiGenerator(API_CONFIG, [1])
        target = self.root / 'adapter-fixture.png'
        with patch('tools.category_image_production.openai_clients_by_slot', return_value=[(1, client)]) as clients, \
                patch('image_generate.generate_one', return_value=payload) as generate:
            result = adapter.generate({'prompt': 'TEST FIXTURE', 'path': str(target)}, 1)
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.size, (1024, 1536))
            self.assertEqual(image.format, 'PNG')
        self.assertEqual(target.with_suffix('.provider.bin').read_bytes(), payload)
        clients.assert_called_once_with(API_CONFIG, [1])
        generate.assert_called_once_with(client, API_CONFIG, 'TEST FIXTURE')
        client.with_options.assert_called_once_with(timeout=180)
        adapter.finish({'status': 'awaiting_vision'})
        client.close.assert_called_once()

    def test_real_adapter_rejects_unreadable_or_tiny_payload_without_retry(self):
        tiny = io.BytesIO()
        Image.new('RGB', (32, 32)).save(tiny, 'PNG')
        for payload in (b'not-an-image', tiny.getvalue()):
            adapter = ApiGenerator(API_CONFIG, [1])
            adapter.clients[1] = MagicMock()
            target = self.root / f'invalid-fixture-{len(payload)}.png'
            with self.subTest(size=len(payload)), patch('image_generate.generate_one', return_value=payload) as generate:
                with self.assertRaises((ValueError, OSError)):
                    adapter.generate({'prompt': 'TEST FIXTURE', 'path': str(target)}, 1)
                self.assertEqual(generate.call_count, 1)
                self.assertEqual(target.with_suffix('.provider.bin').read_bytes(), payload)


if __name__ == '__main__':
    unittest.main()
