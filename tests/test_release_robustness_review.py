"""Independent release-review regressions, fully local and isolated."""
import unittest
from unittest.mock import patch
from PIL import Image
from tools import task_library as lib, task_worker as worker, task_actions as actions, image_versions
from tests import test_task_robustness as fixture


class ReleaseRobustnessReview(unittest.TestCase):
    setUp = fixture.TaskRobustness.setUp
    batch = fixture.TaskRobustness.batch
    request = fixture.TaskRobustness.request
    ready = fixture.TaskRobustness.ready
    payload = fixture.TaskRobustness.payload
    raw = fixture.TaskRobustness.raw
    seed = fixture.TaskRobustness.seed
    create_task = fixture.TaskRobustness.create_task
    render = fixture.TaskRobustness.render
    overlay = fixture.TaskRobustness.overlay
    triptych = fixture.TaskRobustness.triptych

    def test_corrupt_validation_does_not_hide_whole_batch(self):
        b = self.batch()
        row = lib.selected(lib.batch_dir(b['category'], b['id']), b, [1])[0]
        unit = row['units'][0]
        self.raw(b, 1, unit)
        target = lib.delivery_path(b['category'], b['id'], 1, 1, 'cover')
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', worker.images.parse_size(unit['final_size']), 'blue').save(target)
        for text in ('{broken', '[]'):
            target.with_suffix('.validation.json').write_text(text, encoding='utf-8')
            data = lib.view({'category': b['category'], 'batch': b['id'], 'limit': 1})
            self.assertEqual(data['groups'][0]['images'][0]['review'], 'pending')
            with self.ready():
                plan = lib.plan(self.request(b, [1]))
            self.assertEqual(plan['pending_count'], len(row['units']) - 1)

    def test_malformed_nested_validation_preserves_old_image_history(self):
        b = self.batch()
        target = lib.delivery_path(b['category'], b['id'], 1, 1, 'cover')
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (1024, 1536), 'blue').save(target)
        target.with_suffix('.validation.json').write_text('{"postprocess_record":null}', encoding='utf-8')
        prior = target.read_bytes()
        entry = image_versions.store(target, target, b['category'], 'original')
        self.assertEqual(__import__('pathlib').Path(entry['path']).read_bytes(), prior)
        self.assertEqual(target.read_bytes(), prior)

    def test_parent_local_recovery_uses_published_revision_sources(self):
        b, req, target_req, file, rows = self.create_task()
        original = rows[0]['units'][0]
        self.raw(b, 1, original)
        self.seed(file, {original['id']: {'status': 'generated'}}, {original['id']: 1})
        child = actions.prepare_replacement({'category': b['category'], 'batch': b['id'], 'group': 1, 'position': 1, 'request_id': 'review-published-source'})
        child_req = {'category': b['category'], 'batch': child['id'], 'groups': [1]}
        with self.ready(), patch.object(lib, 'launch', return_value=99999999):
            plan = lib.plan(child_req)
            task = lib.start({**child_req, 'request_id': 'review-child', 'authorization': 'execute_selected_groups', 'plan_sha256': plan['plan_sha256']})
        self.assertEqual(worker.run(b['category'], child['id'], task['id'], generate=lambda *a: self.payload(), clients=[(1, object())], render=self.render), 0)
        new_units = lib.selected(lib.batch_dir(b['category'], child['id']), child, [1])[0]['units']
        new_raw = lib.unit_raw(b['category'], child['id'], 1, new_units[0])
        canonical = lib.delivery_path(b['category'], b['id'], 1, 1, 'cover')
        canonical.write_bytes(b'corrupt isolated current image')
        cover_sources = []
        def overlay(raw, out, *a, **kw):
            if kw['delivery_target_id'].endswith(':d1'):
                cover_sources.append(raw)
            return self.overlay(raw, out, *a, **kw)
        with patch.object(worker.images, 'apply_overlays', side_effect=overlay), patch.object(worker.images, 'compose_triptych', side_effect=self.triptych):
            worker.run(b['category'], b['id'], target_req['task'], generate=lambda *a: self.payload(), clients=[(1, object())])
        self.assertEqual(cover_sources, [new_raw])
        self.assertEqual(lib.read(lib.batch_dir(b['category'], b['id'])/'batch.json')['replacements']['1:1'], child['id'])

    def test_postprocess_missing_metadata_uses_current_revision_sources(self):
        from tools import postprocess_view
        b = self.batch()
        units = lib.selected(lib.batch_dir(b['category'], b['id']), b, [1])[0]['units']
        self.raw(b, 1, units[0])
        req = {'category': b['category'], 'batch': b['id'], 'group': 1, 'position': 1}
        child = actions.prepare_replacement({**req, 'request_id': 'review-missing-sidecar'})
        child_units = lib.selected(lib.batch_dir(b['category'], child['id']), child, [1])[0]['units']
        for unit in child_units:
            self.raw(child, 1, unit)
        self.render(b['category'], child['id'], child, [{'group': 1, 'units': child_units}], {})
        actions.commit_replacement(b['category'], child['id'], child)
        target = lib.delivery_path(b['category'], b['id'], 1, 1, 'cover')
        target.with_suffix('.validation.json').write_text('{broken', encoding='utf-8')
        value = postprocess_view.view(req)
        self.assertEqual(value['sources'][0]['path'], str(lib.unit_raw(b['category'], child['id'], 1, child_units[0]).resolve()))

    def test_temporary_admin_lock_does_not_fail_finished_revision(self):
        import threading
        import time
        b = self.batch()
        child = actions.prepare_replacement({'category': b['category'], 'batch': b['id'], 'group': 1, 'position': 1, 'request_id': 'review-admin-contention'})
        req = {'category': b['category'], 'batch': child['id'], 'groups': [1]}
        with self.ready(), patch.object(lib, 'launch', return_value=99999999):
            plan = lib.plan(req)
            task = lib.start({**req, 'request_id': 'review-admin-child', 'authorization': 'execute_selected_groups', 'plan_sha256': plan['plan_sha256']})
        held = threading.Event()
        release = threading.Event()
        def holder():
            with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
                held.set()
                release.wait(5)
                time.sleep(.15)
        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(held.wait(5))
        def render(*args):
            self.render(*args)
            release.set()
        try:
            code = worker.run(b['category'], child['id'], task['id'], generate=lambda *a: self.payload(), clients=[(1, object())], render=render)
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(code, 0)
        self.assertEqual(lib.read(lib.batch_dir(b['category'], child['id'])/'tasks'/task['id']/'task.json')['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
