import copy
import json
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
import factory
import group_production
from tools import ktv_project as ktv, category_image_production as production
from tools import dashboard_delivery, image_review
from tools.prompt_engine import load_category_config, CategoryPromptError

REAL_ROOT = Path(__file__).resolve().parents[1]
CONFIG = dict(provider='official', base_url='', model='gpt-image-2', quality='medium', api_size='1024x1536')
PHONE = '13800138000'


class KtvWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module, name, value in [(ktv, 'ROOT', self.root), (production, 'ROOT', self.root),
                (production, 'CATEGORY_BATCH_ROOT', self.root / 'prompts/category_batches')]:
            self.stack.enter_context(patch.object(module, name, value))
        self.config = load_category_config('ktv')
        project = json.loads((REAL_ROOT / 'projects/ktv/project.json').read_text(encoding='utf-8'))
        project['inventory_policy']['sample_gate_groups'] = 1
        for role in ('cover', 'detail'):
            project['references'][role]['approved_style'] = False
        ktv.write(self.root / 'projects/ktv/project.json', ktv.dump(project))
        ktv.write(self.root / 'projects/ktv/groups/registry.json', ktv.dump(dict(created_groups=0, groups=[])))
        ktv.write(self.root / 'configs/categories/ktv.json', ktv.dump(self.config))
        ktv.write(self.root / 'projects/registry.json', ktv.dump({'schema_version': 1, 'active_project': 'ktv', 'projects': [
            {'id': 'ktv', 'definition': 'projects/ktv/project.json'}]}))
        ktv.extend_groups(1)
        self.batch = self.root / ktv.BATCH
        self.output = self.root / 'output/ktv'

    def plan(self, scope='all'):
        return production.plan('ktv', self.batch, 1, 1, PHONE, CONFIG, scope=scope, output_root=self.output)

    def test_plan_counts_license_bindings_and_frozen_resume(self):
        for scope, requests, deliveries in [('covers', 1, 1), ('details', 4, 2), ('all', 5, 3)]:
            plan = self.plan(scope)
            self.assertEqual(plan['pending_api_requests'], requests)
            self.assertEqual(plan['pending_delivery_count'], deliveries)
            binding = factory._pipe_v2_plan_bindings(plan)
            self.assertEqual(binding['pending_api_requests'], requests)
        plan = self.plan()
        manifest, overlay = production.write_production_files(plan, PHONE, license_id='test-frozen-fixture')
        loaded = production.load_frozen_manifest_runtime_records(self.batch, manifest)
        self.assertEqual(len(loaded), 5)
        self.assertTrue(all(r['generation_target_id'].startswith('ktv:v1:') for r in loaded))
        self.assertTrue(all(PHONE not in r['frozen_effective_prompt'] for r in loaded))
        overlay_data = json.loads(overlay.read_text(encoding='utf-8'))
        self.assertFalse(overlay_data['signboard_overlay_enabled'])
        self.assertEqual(overlay_data['signboard_service_items'], [])
        self.assertEqual(overlay_data['service_items'], self.config['service_buttons'])

    def test_expansion_requires_both_styles_and_preserves_history(self):
        original = (self.batch / 'prompts.jsonl').read_bytes()
        with self.assertRaises(RuntimeError):
            ktv.extend_groups(1)
        p = self.root / 'projects/ktv/project.json'
        data = ktv.read(p)
        data['references']['cover']['approved_style'] = True
        ktv.write(p, ktv.dump(data))
        with self.assertRaises(RuntimeError):
            ktv.extend_groups(1)
        data['references']['detail']['approved_style'] = True
        ktv.write(p, ktv.dump(data))
        ktv.extend_groups(2)
        self.assertTrue((self.batch / 'prompts.jsonl').read_bytes().startswith(original))
        plan = production.plan('ktv', self.batch, 1, 3, PHONE, CONFIG, output_root=self.output)
        self.assertEqual(plan['pending_api_requests'], 15)
        self.assertEqual(plan['pending_delivery_count'], 9)

    def test_scene_sampling_is_balanced_reproducible_and_linked(self):
        styles = set()
        for group in range(1, 13):
            rows, deliveries = ktv.make_group(group, self.config)
            self.assertEqual(rows, ktv.make_group(group, self.config)[0])
            scene = rows[0]['scene']
            styles.add(scene['包厢风格'])
            self.assertIn(scene['灯光'], self.config['linked_randomization']['lighting_by_style'][scene['包厢风格']])
            self.assertTrue(3 <= len(scene['水果']) <= 5)
            self.assertEqual(len({r['scene_signature'] for r in rows}), 1)
            self.assertEqual([len(d['source_generation_ids']) for d in deliveries], [1, 3, 1])
            if group % 6 == 0:
                self.assertEqual(len(styles), 6)
                styles.clear()

    def test_explicit_five_group_sample_range_keeps_approval_gate(self):
        path = self.root / 'projects/ktv/project.json'
        project = ktv.read(path)
        project['inventory_policy']['sample_gate_groups'] = 5
        ktv.write(path, ktv.dump(project))
        prefix = (self.batch / 'prompts.jsonl').read_bytes()
        ktv.extend_groups(4)
        self.assertTrue((self.batch / 'prompts.jsonl').read_bytes().startswith(prefix))
        plan = production.plan('ktv', self.batch, 1, 5, PHONE, CONFIG, output_root=self.output)
        self.assertEqual(plan['pending_api_requests'], 25)
        self.assertEqual(plan['pending_delivery_count'], 15)
        with self.assertRaises(RuntimeError):
            ktv.extend_groups(1)
        self.assertFalse(ktv.read(path)['references']['cover']['approved_style'])
        with patch.object(factory, 'ROOT', self.root), \
             patch.object(factory, 'PROJECT_REGISTRY_PATH', self.root / 'projects/registry.json'):
            factory._category_sample_range('ktv', 1, 1)
            factory._category_sample_range('ktv', 5, 1)
            with self.assertRaises(RuntimeError):
                factory._category_sample_range('ktv', 6, 1)

    def test_flare_config_preserves_parameter_and_plan_binding(self):
        flare = dict(CONFIG, model='gpt-image-2.5-flare')
        with patch.object(factory, 'effective_api_config', return_value=flare):
            self.assertEqual(factory._category_effective_config()['model'], flare['model'])
        old_plan = self.plan('covers')
        new_plan = production.plan('ktv', self.batch, 1, 1, PHONE, flare,
                                   scope='covers', output_root=self.output)
        self.assertEqual(new_plan['pending_api_requests'], 1)
        self.assertNotEqual(old_plan['plan_sha256'], new_plan['plan_sha256'])
        for field, value in [('model', 'unconfirmed-model'), ('quality', 'high'),
                             ('api_size', '1024x1024')]:
            with self.subTest(field=field), \
                 patch.object(factory, 'effective_api_config', return_value=dict(flare, **{field: value})):
                with self.assertRaises(RuntimeError):
                    factory._category_effective_config()

    def test_validator_rejects_mixed_rooms_dimensions_roles_and_units(self):
        rows, _ = ktv.make_group(1, self.config)
        for field, value in [('category_id', 'truck_rescue'), ('final_size', '1024x1536'),
                ('delivery_position', 3), ('scene_signature', 'invalid')]:
            bad = copy.deepcopy(rows)
            bad[1][field] = value
            with self.assertRaises(CategoryPromptError):
                ktv.validate_rows(bad, self.config['image_group_structure'], 1, 1)
        with self.assertRaises(CategoryPromptError):
            ktv.validate_rows(rows[:-1], self.config['image_group_structure'], 1, 1)

    def test_sample_range_stays_limited_and_all_scope_uses_batch_review(self):
        with patch.object(factory, 'ROOT', self.root), \
             patch.object(factory, 'PROJECT_REGISTRY_PATH', self.root / 'projects/registry.json'):
            factory._category_sample_range('ktv', 1, 1)
            with self.assertRaises(RuntimeError):
                factory._category_sample_range('ktv', 1, 2)
        factory._category_require_executable_scope('all', 'independent_triptych_panels')
        self.assertTrue(factory._category_scope_requires_cover_approval('details'))

    def test_local_delivery_review_and_packaging_without_visual_approval(self):
        plan = self.plan()
        records = plan['records']
        for i, record in enumerate(records):
            raw = Path(record['raw_target'])
            raw.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new('RGB', (1024, 1536), (35+i*20, 50, 70))
            draw = ImageDraw.Draw(image)
            draw.rectangle((50+i*30, 350, 500, 650+i*30), fill=(200, 150, 70))
            image.save(raw)
        self.assertEqual(production.recover_local_deliveries(plan, PHONE), 3)
        result = json.loads((self.output / 'group_0001/01_cover.validation.json').read_text(encoding='utf-8'))
        factory._validate_category_cover_record('ktv', result, 1, PHONE, (864, 1536), require_approved=False)
        with self.assertRaises(RuntimeError):
            factory._validate_category_cover_record('ktv', result, 1, PHONE, (864, 1536), require_approved=True)
        review = image_review.ReviewSession(production._delivery_records(records), self.output, self.root / 'review')
        review.run_tool()
        self.assertEqual(review.tool_state['status'], 'completed')
        with patch.object(group_production, 'ROOT', self.root):
            audit = group_production.audit_groups(1, 1, 'ktv')
            self.assertEqual(audit['groups'][0]['expected_roles'], ['cover', 'triptych', 'detail'])
            self.assertFalse(audit['groups'][0]['delivery_ready'])
        state = self.root / '.runtime/delivery.json'
        job_path = self.root / '.runtime/jobs/test.json'
        job = dict(job_id='test', project_id='ktv', group_start=1, group_count=1,
                   job_type='category-batch-production', scope='details')
        ktv.write(job_path, ktv.dump(job))
        with patch.object(factory, 'ROOT', self.root), \
             patch.object(factory, 'DASHBOARD_DELIVERY_STATE_PATH', state), \
             patch.object(factory, 'DASHBOARD_SESSION_PATH', self.root / '.runtime/session.json'), \
             patch.object(factory, 'DASHBOARD_SESSION_ARCHIVE_DIR', self.root / '.runtime/archive'):
            factory.activate_dashboard_session(job_path, job, target_records=plan['delivery_records'])
        result = dashboard_delivery.package_pending_groups(self.root, state, 'ktv', 1, 1,
            self.root / 'export', max_archive_bytes=1_000_000, manifest_dir=self.root / 'manifests')
        with zipfile.ZipFile(result['archives'][0]['path']) as archive:
            self.assertEqual(len(archive.namelist()), 3)
            self.assertTrue(all(name.endswith('.png') for name in archive.namelist()))
        for path in (self.output / 'group_0001').glob('*.validation.json'):
            self.assertFalse(json.loads(path.read_text(encoding='utf-8'))['approved'])
        self.assertEqual(dashboard_delivery.pending_group_entries(dashboard_delivery.load_state(state), 'ktv'), [])


if __name__ == '__main__':
    unittest.main()
