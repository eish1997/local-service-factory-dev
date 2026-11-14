"""Native route contract, isolated from customer data and all network calls."""
import unittest
import hashlib
from PIL import Image
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from tests import test_shared_tasks as shared
from tools import task_library as lib, task_worker as worker, task_native as native


class NativeTasks(unittest.TestCase):
    setUp = shared.SharedTasks.setUp

    def assemble(self, **extra):
        return lib.assemble({**dict(category='road_rescue', count=1, seed=1401,
                                 phone='13800138000'), **extra})

    def test_native_assembly_and_plan_do_not_probe_api(self):
        with (patch.object(lib, 'api_config', side_effect=AssertionError('API config')),
             patch.object(lib, 'readiness', side_effect=AssertionError('API readiness'))):
            batch = self.assemble(generation_route='codex_native')
            result = lib.dispatch('native-plan', dict(category=batch['category'], batch=batch['id'], groups=[1], instance_id=native.instance()['instance_id']))
        self.assertEqual(result['raw_count'], 7)
        self.assertEqual(result['delivery_count'], 5)
        self.assertEqual(result['max_tool_calls'], 14)
        self.assertIsNone(result['authorization'])
        self.assertFalse(result['api_called'])

    def test_route_is_frozen_and_legacy_default_is_api(self):
        old = self.assemble(request_id='same')
        self.assertEqual(lib.generation_route({}), 'api')
        self.assertEqual(self.assemble(request_id='same', generation_route='api')['id'], old['id'])
        with self.assertRaises(ValueError):
            self.assemble(request_id='same', generation_route='codex_native')
        with self.assertRaises(ValueError):
            self.assemble(generation_route='unknown')
        with self.assertRaisesRegex(ValueError, '不能转换'):
            native.plan(dict(category=old['category'], batch=old['id'], groups=[1]))

    def test_api_entries_reject_before_tasks_licenses_or_probes(self):
        batch = self.assemble(generation_route='codex_native')
        request = dict(category=batch['category'], batch=batch['id'], groups=[1], task='absent')
        with (patch.object(lib, 'api_config', side_effect=AssertionError('API config')),
             patch.object(lib, 'launch', side_effect=AssertionError('worker launched'))):
            for operation in ('plan', 'start', 'resume', 'retry'):
                with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'API 执行入口'):
                    lib.dispatch(operation, request)
            for entry in (worker.run, worker._run):
                with self.assertRaisesRegex(ValueError, 'API 执行入口'):
                    entry(batch['category'], batch['id'], 'absent')
        self.assertFalse((lib.batch_dir(batch['category'], batch['id'])/'tasks').exists())

    def test_agent_and_dashboard_freeze_identical_native_prompts(self):
        a = self.assemble(source='agent', generation_route='codex_native')
        b = self.assemble(source='dashboard', generation_route='codex_native')
        self.assertEqual(a['manifest_sha256'], b['manifest_sha256'])
        self.assertEqual(a['snapshot_sha256'], b['snapshot_sha256'])

    def authorized(self, cap=2, category='road_rescue', uid='g0001_u01'):
        batch = self.assemble(generation_route='codex_native', category=category)
        request = dict(category=batch['category'], batch=batch['id'], groups=[1],
                       unit_ids=[uid], instance_id=native.instance()['instance_id'])
        planned = native.plan(request)
        request.update(scope='scope-one', max_tool_calls=cap, plan_sha256=planned['plan_sha256'],
                       authorization='execute_native_selected_units')
        native.dispatch('native-authorize', request)
        return {**request, 'unit': uid}

    def test_reservation_survives_unknown_result_and_never_refunds(self):
        request = self.authorized()
        claim = native.dispatch('native-claim', request)
        request['claim'] = claim['claim']
        first = native.dispatch('native-reserve', request)
        self.assertTrue(first['new_reservation'])
        self.assertFalse(native.dispatch('native-reserve', request)['new_reservation'])
        native.dispatch('native-outcome', {**request, 'outcome': 'uncertain', 'evidence': 'test interruption'})
        with self.assertRaisesRegex(ValueError, '不能重新生成'):
            native.dispatch('native-claim', request)
        native.dispatch('native-outcome', {**request, 'outcome': 'confirmed_failure', 'evidence': 'explicit tool error without image'})
        old_claim = request['claim']
        request['claim'] = native.dispatch('native-claim', request)['claim']
        with self.assertRaisesRegex(ValueError, '领取标识'):
            native.dispatch('native-reserve', {**request, 'claim': old_claim})
        native.dispatch('native-reserve', request)
        native.dispatch('native-outcome', {**request, 'outcome': 'confirmed_failure', 'evidence': 'second failure'})
        with self.assertRaisesRegex(ValueError, '额度已耗尽'):
            native.dispatch('native-claim', request)
        state = native.dispatch('native-status', request)
        self.assertEqual(state['scopes']['scope-one']['calls_used'], 2)
        self.assertEqual(state['units']['g0001_u01']['status'], 'failed')

    def test_parallel_claim_has_one_winner_and_cancel_rejects_late_result(self):
        request = self.authorized()
        def attempt():
            try:return native.dispatch('native-claim', request)
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        winners = [r for r in results if r]
        self.assertEqual(len(winners), 1)
        request['claim'] = winners[0]['claim']
        native.dispatch('native-reserve', request)
        native.dispatch('native-cancel', {**request, 'authorization': 'cancel_native_batch'})
        with self.assertRaisesRegex(ValueError, '已取消'):
            native.dispatch('native-outcome', {**request, 'outcome': 'confirmed_failure', 'evidence': 'late'})
        self.assertEqual(native.dispatch('native-status', request)['scopes']['scope-one']['calls_used'], 1)

    def test_changed_instance_and_new_scope_cannot_reset_lower_budget(self):
        request = self.authorized(cap=1)
        with self.assertRaisesRegex(ValueError, '实例不匹配'):
            native.dispatch('native-claim', {**request, 'instance_id': 'other'})
        with self.assertRaisesRegex(ValueError, '已有执行范围'):
            native.dispatch('native-authorize', {**request, 'scope': 'fresh-budget',
                'plan_sha256': native.plan(request)['plan_sha256']})
        request['claim'] = native.dispatch('native-claim', request)['claim']
        native.dispatch('native-reserve', request)
        native.dispatch('native-outcome', {**request, 'outcome': 'confirmed_failure', 'evidence': 'known failure'})
        with self.assertRaisesRegex(ValueError, '额度已耗尽'):
            native.dispatch('native-claim', request)

    def returned(self, **options):
        request = self.authorized(**options)
        request['claim'] = native.dispatch('native-claim', request)['claim']
        native.dispatch('native-reserve', request)
        file = self.root/'synthetic.png'
        Image.new('RGB', (1024, 1536), (75, 110, 145)).save(file)
        request.update(file=str(file.resolve()), sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                       source_kind='synthetic_test')
        native.dispatch('native-register', request)
        return request

    def test_ingest_preserves_native_evidence_and_is_idempotent(self):
        request = self.returned()
        first = native.dispatch('native-ingest', request)
        second = native.dispatch('native-ingest', request)
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'raw_saved')
        self.assertEqual(len(first['attempts']), 1)
        from tools.raw_library import load
        asset = load(request['category'], first['asset'])
        self.assertEqual(asset['review']['decision'], 'unreviewed')
        proof = lib.read(asset['receipt_path'])
        self.assertEqual(proof['provider'], 'codex_native')
        self.assertTrue(proof['mock'])
        self.assertNotIn('slot', proof)
        with self.assertRaisesRegex(ValueError, '不能覆盖'):
            native.dispatch('native-register', {**request, 'sha256': 'a'*64})
        copy = self.root/'same-bytes.png'
        from pathlib import Path
        copy.write_bytes(Path(request['file']).read_bytes())
        self.assertEqual(native.dispatch('native-register', {**request, 'file': str(copy.resolve())}), first)

    def test_returned_result_blocks_retry_and_recovers_receipt_write_crash(self):
        request = self.returned()
        with self.assertRaisesRegex(ValueError, '已有返回文件'):
            native.dispatch('native-outcome', {**request, 'outcome': 'confirmed_failure', 'evidence': 'not allowed'})
        real_write = lib.write
        def fail_receipt(path, value):
            if str(path).endswith('.receipt.json'):
                raise OSError('simulated crash after bytes')
            return real_write(path, value)
        with patch.object(lib, 'write', side_effect=fail_receipt), self.assertRaises(OSError):
            native.dispatch('native-ingest', request)
        from pathlib import Path
        Path(request['file']).unlink()  # Recovery must use the explicit persisted staging evidence.
        recovered = native.dispatch('native-ingest', request)
        self.assertEqual(recovered['status'], 'raw_saved')
        self.assertEqual(len(recovered['attempts']), 1)

    def test_single_raw_materializes_current_card_and_delivery_queue(self):
        request = self.returned()
        native.dispatch('native-ingest', request)
        first = native.dispatch('native-materialize', request)
        record = first['state']['units'][request['unit']]
        self.assertEqual(record['status'], 'completed')
        view = lib.view(request)
        self.assertEqual(len(view['groups'][0]['images']), 1)
        image = view['groups'][0]['images'][0]
        self.assertNotEqual(image['review'], 'approved')
        from pathlib import Path
        self.assertTrue(Path(image['path']).is_file())
        before = Path(image['path']).read_bytes()
        again = native.dispatch('native-recover', request)
        self.assertEqual(again['state']['scopes']['scope-one']['calls_used'], 1)
        self.assertEqual(before, Path(image['path']).read_bytes())
        queue = lib.read(self.root/'.runtime/dashboard_delivery_state.json')
        item = queue['projects']['road_rescue']['pending_library_groups'][f"{request['batch']}:1"]
        self.assertEqual(len(item['paths']), 1)
        self.assertEqual(item['expected_image_count'], 5)

    def test_full_group_triptych_history_and_packaging_use_shared_results(self):
        batch = self.assemble(generation_route='codex_native')
        request = dict(category=batch['category'], batch=batch['id'], groups=[1],
                       instance_id=native.instance()['instance_id'], scope='whole-group')
        planned = native.plan(request)
        native.dispatch('native-authorize', {**request, 'plan_sha256': planned['plan_sha256'],
            'max_tool_calls': 7, 'authorization': 'execute_native_selected_units'})
        for index, unit in enumerate(planned['units']):
            bound = {**request, 'unit': unit['id']}
            bound['claim'] = native.dispatch('native-claim', bound)['claim']
            native.dispatch('native-reserve', bound)
            file = self.root/f'synthetic-{index}.png'
            Image.new('RGB', (1024, 1536), (40+index*25, 100, 160)).save(file)
            native.dispatch('native-register', {**bound, 'file': str(file.resolve()),
                'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'source_kind': 'synthetic_test'})
            native.dispatch('native-ingest', bound)
        result = native.dispatch('native-materialize', request)
        self.assertFalse(result['render_failures'])
        self.assertTrue(all(r['status'] == 'completed' for r in result['state']['units'].values()))
        images = lib.view(request)['groups'][0]['images']
        self.assertEqual(len(images), 5)
        from tools import image_versions
        from pathlib import Path
        histories = []
        for image in images:
            target = lib.delivery_path(batch['category'], batch['id'], 1, image['position'], image['kind'])
            histories.append((image_versions.index_path(target), lib.read(image_versions.index_path(target))))
            self.assertNotEqual(image['review'], 'approved')
            if image['kind'] == 'triptych':
                metadata = lib.read(target.with_suffix('.validation.json'))
                self.assertEqual(len(metadata['postprocess_record']['sources']), 3)
                expected = [u['service_role'] for u in planned['units'] if u['kind'] == 'triptych_panel']
                self.assertEqual(metadata['panel_service_roles'], expected)
        native.dispatch('native-recover', request)
        for file, before in histories:self.assertEqual(lib.read(file), before)
        # An explicit local revision becomes current; recovery/package must not revert to parent raws.
        current = lib.delivery_path(batch['category'], batch['id'], 1, 1, 'cover')
        candidate = current.parent/'synthetic-local-revision.png'
        with Image.open(current) as image:size=image.size
        Image.new('RGB', size, (140, 80, 65)).save(candidate)
        lib.write(candidate.with_suffix('.validation.json'), lib.read(current.with_suffix('.validation.json')))
        image_versions.publish(current, candidate, batch['category'], 'local_test_revision', event_id='native-test-revision')
        revised = current.read_bytes()
        native.dispatch('native-recover', request)
        self.assertEqual(current.read_bytes(), revised)
        export = self.root/'export';export.mkdir()
        from tools.task_assets import package
        package({**request, 'destination': str(export.resolve())})
        import zipfile
        archives = list(export.glob('*.zip'));self.assertEqual(len(archives), 1)
        with zipfile.ZipFile(archives[0]) as archive:
            self.assertEqual(len(archive.namelist()), 5)
            for image in images:
                name = next(n for n in archive.namelist() if n.endswith('/'+Path(image['path']).name))
                self.assertEqual(archive.read(name), Path(image['path']).read_bytes())
        queue_before = lib.read(self.root/'.runtime/dashboard_delivery_state.json')
        native.dispatch('native-recover', request)
        self.assertEqual(lib.read(self.root/'.runtime/dashboard_delivery_state.json'), queue_before)

    def test_cancel_during_render_preserves_raw_and_does_not_publish(self):
        request = self.returned()
        native.dispatch('native-ingest', request)
        original = worker.images.apply_overlays
        def cancel_after_render(*args, **kwargs):
            result = original(*args, **kwargs)
            native.dispatch('native-cancel', {**request, 'authorization': 'cancel_native_batch'})
            self.assertEqual(self.update_probe()['installs'],0)
            return result
        with patch.object(worker.images, 'apply_overlays', side_effect=cancel_after_render):
            with self.assertRaisesRegex(ValueError, '已取消'):
                native.dispatch('native-materialize', request)
        self.assertFalse(lib.view(request)['groups'][0]['images'])
        state = native.dispatch('native-status', request)
        self.assertEqual(state['scopes']['scope-one']['calls_used'], 1)
        self.assertIn('asset', state['units'][request['unit']])
        self.assertEqual(self.update_probe()['installs'],1)

    def test_render_failure_retries_locally_without_new_calls(self):
        request = self.returned()
        native.dispatch('native-ingest', request)
        with patch.object(worker.images, 'apply_overlays', side_effect=OSError('local renderer failure')):
            failed = native.dispatch('native-materialize', request)
        self.assertEqual(failed['state']['units'][request['unit']]['status'], 'raw_saved')
        self.assertTrue(failed['render_failures'])
        recovered = native.dispatch('native-recover', request)
        self.assertEqual(recovered['state']['units'][request['unit']]['status'], 'completed')
        self.assertEqual(recovered['state']['scopes']['scope-one']['calls_used'], 1)

    def test_deleted_or_changed_snapshot_rejects_late_ingestion(self):
        for change in ('deleted', 'snapshot'):
            with self.subTest(change=change):
                request = self.returned()
                path, batch = lib.load_batch(request['category'], request['batch'])
                if change == 'deleted':
                    batch['deleted_groups'] = [1]
                    lib.write(path/'batch.json', batch)
                else:
                    snapshot = lib.read(path/'snapshot.json')
                    snapshot['tampered'] = True
                    lib.write(path/'snapshot.json', snapshot)
                with self.assertRaises(ValueError):native.dispatch('native-ingest', request)
                self.assertEqual(native.dispatch('native-status', request)['scopes']['scope-one']['calls_used'], 1)

    def test_bad_returned_file_remains_charged_and_blocks_regeneration(self):
        request = self.authorized()
        request['claim'] = native.dispatch('native-claim', request)['claim']
        native.dispatch('native-reserve', request)
        invalid = self.root/'invalid.png';invalid.write_bytes(b'not an image')
        with self.assertRaises(OSError):
            native.dispatch('native-register', {**request, 'file': str(invalid.resolve()),
                'sha256': hashlib.sha256(invalid.read_bytes()).hexdigest(), 'source_kind': 'synthetic_test'})
        with self.assertRaisesRegex(ValueError, '已有返回文件'):
            native.dispatch('native-outcome', {**request, 'outcome': 'confirmed_failure', 'evidence': 'invalid image'})
        state = native.dispatch('native-status', request)
        self.assertEqual(state['units'][request['unit']]['status'], 'uncertain')
        self.assertEqual(state['scopes']['scope-one']['calls_used'], 1)

    def test_business_ktv_native_delivery_keeps_phone_without_scene_title(self):
        request = self.returned(category='business_ktv', uid='g0001_u04')
        native.dispatch('native-ingest', request)
        result = native.dispatch('native-materialize', request)
        self.assertEqual(result['state']['units'][request['unit']]['status'], 'completed')
        path, data = lib.load_batch(request['category'], request['batch'])
        unit = lib.scoped_rows(path, data, [1], [request['unit']])[0]['units'][0]
        target = lib.delivery_path(request['category'], request['batch'], 1, unit['delivery_position'], unit['kind'])
        metadata = lib.read(target.with_suffix('.validation.json'))
        self.assertIn('电话：13800138000', metadata['expected_text'])
        self.assertNotIn(unit['service_role'], metadata['expected_text'])
        self.assertFalse(metadata.get('approved'))

    def test_parallel_reservation_issues_one_call_permit(self):
        request = self.authorized()
        request['claim'] = native.dispatch('native-claim', request)['claim']
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: native.dispatch('native-reserve', request), range(2)))
        self.assertEqual(sum(r['new_reservation'] for r in replies), 1)
        self.assertEqual(native.dispatch('native-status', request)['scopes']['scope-one']['calls_used'], 1)

    def test_plan_respects_unknown_results_and_lower_scope_cap(self):
        request = self.authorized(cap=1)
        request['claim'] = native.dispatch('native-claim', request)['claim']
        native.dispatch('native-reserve', request)
        plan = native.plan(request)
        self.assertEqual(plan['max_tool_calls'], 0)
        self.assertEqual(plan['ready_units'], [])
        self.assertEqual(plan['pending_units'], [request['unit']])
        native.dispatch('native-outcome', {**request, 'outcome': 'confirmed_failure', 'evidence': 'known failure'})
        self.assertEqual(native.plan(request)['max_tool_calls'], 0)
        native.dispatch('native-cancel', {**request, 'authorization': 'cancel_native_batch'})
        self.assertEqual(native.plan(request)['status'], 'cancelled')
        self.assertEqual(lib.view(request)['groups'][0]['units'][0]['native_status'], 'cancelled')

    def test_two_public_cli_processes_cannot_claim_the_same_unit(self):
        request = self.authorized()
        import json, os, subprocess, sys
        from tools import runtime_paths
        env = {**os.environ, 'FACTORY_DATA_HOME': str(self.root.resolve()), 'PYTHONIOENCODING': 'utf-8'}
        command = [sys.executable, '-X', 'utf8', str(runtime_paths.CODE_ROOT/'factory.py'), 'tasks', 'native-claim']
        processes = [subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding='utf-8', env=env) for _ in range(2)]
        for process in processes:
            process.stdin.write(json.dumps(request));process.stdin.close();process.stdin=None
        replies = []
        for process in processes:
            out, error = process.communicate(timeout=30)
            self.assertFalse(error)
            replies.append(json.loads(out))
        self.assertEqual(sum(reply['ok'] for reply in replies), 1)

    def test_installed_descriptor_discovery_and_unbound_install_guard(self):
        import os, subprocess, sys
        from tools import runtime_paths
        install = self.root/'fixture-install'
        engine = install/'resources/engine'
        python = install/'resources/python/python.exe'
        data = self.root/'fixture-data'
        (engine/'tools').mkdir(parents=True)
        (engine/'tools/task_native.py').write_text('# presence fixture only', encoding='utf-8')
        python.parent.mkdir(parents=True);python.write_bytes(b'fixture, never execute')
        (data/'.runtime').mkdir(parents=True)
        lib.write(engine/'distribution/update-config.json', {'app_version': '0.0.0-test'})
        script = "require(process.argv[1]).recordInstance(...process.argv.slice(2))"
        subprocess.run(['node', '-e', script, str(runtime_paths.CODE_ROOT/'dashboard/installed-runtime.js'),
                        str(data), str(engine), str(python), '0.0.0-test'], check=True, capture_output=True, timeout=15)
        result = native.discover({'install_roots': [str(install.resolve())], 'data_roots': [str(data.resolve())]})
        found = next(i for i in result['installations'] if i['install_root'] == str(install.resolve()))
        self.assertIsNone(result['selected'])
        self.assertEqual(found['data_instances'][0]['data_root'], str(data.resolve()))
        expected = lib.digest({'data_root': os.path.normcase(str(data.resolve()))})
        self.assertEqual(found['data_instances'][0]['instance_id'], expected)
        self.assertTrue(found['requires_instance_check'])
        with patch.object(runtime_paths, 'CODE_ROOT', engine), patch.object(sys, 'executable', str(python)), patch.dict(os.environ):
            os.environ.pop('FACTORY_DATA_HOME', None)
            os.environ.pop('FACTORY_INSTALL_HOME', None)
            with self.assertRaisesRegex(ValueError, '必须显式绑定'):
                native.instance()

    def test_batch_deleted_during_render_is_not_resurrected(self):
        request = self.returned()
        native.dispatch('native-ingest', request)
        path, _ = lib.load_batch(request['category'], request['batch'])
        original = worker.images.apply_overlays
        def delete_after_render(*args, **kwargs):
            result = original(*args, **kwargs)
            (path/'batch.json').unlink()
            (path/'native-execution.json').unlink()
            return result
        with patch.object(worker.images, 'apply_overlays', side_effect=delete_after_render):
            with self.assertRaises(FileNotFoundError):native.dispatch('native-materialize', request)
        self.assertFalse((path/'batch.json').exists())
        self.assertFalse((path/'native-execution.json').exists())

    def test_missing_working_raw_recovers_saved_evidence_without_generation(self):
        request = self.returned()
        native.dispatch('native-ingest', request)
        native.dispatch('native-materialize', request)
        path, data = lib.load_batch(request['category'], request['batch'])
        unit = lib.scoped_rows(path, data, [1], [request['unit']])[0]['units'][0]
        raw = lib.unit_raw(request['category'], request['batch'], 1, unit)
        original = lib.io_path(raw).read_bytes();lib.io_path(raw).unlink()
        plan = native.plan(request)
        self.assertEqual(plan['max_tool_calls'], 0)
        self.assertEqual(plan['blocked_units'][0]['reason'], 'raw_evidence_missing')
        recovered = native.dispatch('native-recover', request)
        self.assertEqual(lib.io_path(raw).read_bytes(), original)
        self.assertEqual(recovered['state']['scopes']['scope-one']['calls_used'], 1)

    def test_partial_recovery_does_not_expand_to_another_authorized_group(self):
        batch = self.assemble(generation_route='codex_native', count=2)
        base = dict(category=batch['category'], batch=batch['id'], scope='two-groups',
                    instance_id=native.instance()['instance_id'])
        planned = native.plan({**base, 'groups': [1, 2]})
        native.dispatch('native-authorize', {**base, 'groups': [1, 2],
            'plan_sha256': planned['plan_sha256'], 'max_tool_calls': 2,
            'authorization': 'execute_native_selected_units'})
        for group in (1, 2):
            request = {**base, 'unit': f'g{group:04d}_u01'}
            request['claim'] = native.dispatch('native-claim', request)['claim']
            native.dispatch('native-reserve', request)
            file = self.root/f'group-{group}.png'
            Image.new('RGB', (1024, 1536), (group*60, 80, 120)).save(file)
            native.dispatch('native-register', {**request, 'file': str(file.resolve()),
                'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'source_kind': 'synthetic_test'})
        result = native.dispatch('native-recover', {**base, 'groups': [1]})
        self.assertEqual(result['state']['units']['g0001_u01']['status'], 'completed')
        self.assertEqual(result['state']['units']['g0002_u01']['status'], 'uncertain')
        self.assertFalse(lib.view(base)['groups'][1]['images'])
        self.assertEqual(result['state']['scopes']['two-groups']['calls_used'], 2)

    def test_manual_handoff_recovers_a_registered_missing_tool_file(self):
        request = self.authorized()
        request['claim'] = native.dispatch('native-claim', request)['claim']
        native.dispatch('native-reserve', request)
        file = self.root/'manually-saved.png'
        Image.new('RGB', (1024, 1536), (90, 120, 80)).save(file)
        source = {**request, 'file': str((self.root/'missing-return.png').resolve()),
                  'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                  'source_kind': 'tool_return', 'synthetic': True, 'tool_result_id': 'synthetic-fixture-id'}
        with self.assertRaises(ValueError):native.dispatch('native-register', source)
        saved = native.dispatch('native-register', {**source, 'file': str(file.resolve()), 'handoff': 'manual_saved'})
        self.assertEqual(saved['manual_recovery']['kind'], 'manual_saved')
        record = native.dispatch('native-ingest', request)
        from tools.raw_library import load
        proof = lib.read(load(request['category'], record['asset'])['receipt_path'])
        self.assertEqual(proof['handoff']['kind'], 'manual_saved')
        self.assertEqual(proof['native_binding']['tool_result_id'], 'synthetic-fixture-id')
        self.assertTrue(proof['mock'])
        self.assertEqual(len(record['attempts']), 1)



    def update_probe(self):
        """Run the real updater admission with signed synthetic bytes and a stub installer."""
        import subprocess, json
        from tools import runtime_paths
        script = """
        const path=require('path');
        const base=process.argv[1],root=process.argv[2];
        const {fixture}=require(path.join(base,'dashboard/tests/update-fixture.js'));
        const {hasActiveNativeTasks,readLibraryJobs}=require(path.join(base,'dashboard/tasks.js'));
        (async()=>{const f=fixture(hasActiveNativeTasks,root);await f.service.check();
          const active=hasActiveNativeTasks(root),apiJobs=readLibraryJobs(root).length;
          f.app.emit('before-quit',{preventDefault(){}});
          console.log(JSON.stringify({active,apiJobs,installs:f.installs(),state:f.service.getState().state}));
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """
        result=subprocess.run(['node','-e',script,str(runtime_paths.CODE_ROOT),str(self.root)],
                              capture_output=True,text=True,check=True,timeout=30)
        return json.loads(result.stdout)

    def test_native_call_blocks_actual_updater_until_manual_state(self):
        request=self.authorized()
        request['claim']=native.dispatch('native-claim',request)['claim']
        native.dispatch('native-reserve',request)
        self.assertEqual(self.update_probe(),dict(active=True,apiJobs=0,installs=0,state='ready'))
        native.dispatch('native-outcome',{**request,'outcome':'uncertain','evidence':'explicit interrupted tool'})
        self.assertEqual(self.update_probe()['installs'],1)
        state=native.load_state(lib.batch_dir(request['category'],request['batch']))
        self.assertEqual(state['scopes'][request['scope']]['calls_used'],1)

    def test_update_competes_with_actual_ingest(self):
        request=self.returned()
        from tools import category_4k_raw
        publish=category_4k_raw.publish_immutable_bytes
        def during_write(*args,**kwargs):
            self.assertTrue((self.root/'.runtime/task-admin.lock').exists())
            self.assertEqual(self.update_probe()['installs'],0)
            return publish(*args,**kwargs)
        with patch.object(category_4k_raw,'publish_immutable_bytes',side_effect=during_write):
            native.dispatch('native-ingest',request)
        self.assertEqual(self.update_probe()['installs'],1)

    def test_update_competes_with_actual_render_and_allows_completion(self):
        request=self.returned();native.dispatch('native-ingest',request)
        render=worker.materialize
        def during_render(*args,**kwargs):
            self.assertFalse((self.root/'.runtime/task-admin.lock').exists())
            self.assertEqual(self.update_probe(),dict(active=True,apiJobs=0,installs=0,state='ready'))
            return render(*args,**kwargs)
        with patch.object(worker,'materialize',side_effect=during_render):
            native.dispatch('native-materialize',request)
        self.assertEqual(list((self.root/'.runtime/native-writes').glob('*.lock')),[])
        self.assertEqual(self.update_probe()['installs'],1)

    def test_install_marker_rejects_every_native_mutation_without_state_change(self):
        request=self.returned();path=lib.batch_dir(request['category'],request['batch'])
        before=(path/'native-execution.json').read_bytes()
        self.assertEqual(self.update_probe()['installs'],1)
        for operation in ('authorize','claim','reserve','register','ingest','outcome','cancel','materialize','recover'):
            with self.subTest(operation=operation),self.assertRaisesRegex(ValueError,'正在安装'):
                native.dispatch('native-'+operation,request)
        self.assertEqual((path/'native-execution.json').read_bytes(),before)
        self.assertFalse((self.root/'.runtime/native-writes').exists())

    def test_install_wins_native_admission_race(self):
        import contextlib
        request=self.returned();native.dispatch('native-ingest',request)
        original=lib.lock;fired=False
        @contextlib.contextmanager
        def racing_lock(path,**kwargs):
            nonlocal fired
            if path==self.root/'.runtime/task-admin.lock' and not fired:
                fired=True
                self.assertEqual(self.update_probe()['installs'],1)
            with original(path,**kwargs):yield
        with patch.object(lib,'lock',side_effect=racing_lock),patch.object(worker,'materialize',side_effect=AssertionError('render started')):
            with self.assertRaisesRegex(ValueError,'正在安装'):
                native.dispatch('native-materialize',request)
        self.assertTrue(fired)
        self.assertFalse((self.root/'.runtime/native-writes').exists())

    def test_crashed_native_writer_does_not_permanently_block_update(self):
        import subprocess,sys
        request=self.returned();native.dispatch('native-ingest',request)
        path=lib.batch_dir(request['category'],request['batch'])
        state=native.load_state(path);state['units'][request['unit']]['status']='rendering'
        lib.write(path/'native-execution.json',state)
        script="""
import os,sys
from pathlib import Path
from tools import task_library as lib,task_native as native
lib.ROOT=Path(sys.argv[1])
with native.write_guard():os._exit(0)
"""
        subprocess.run([sys.executable,'-X','utf8','-c',script,str(self.root)],check=True,timeout=20)
        self.assertEqual(len(list((self.root/'.runtime/native-writes').glob('*.lock'))),1)
        self.assertEqual(self.update_probe()['installs'],1)

    def test_native_non_api_size_preserves_returned_bytes_and_renders(self):
        from pathlib import Path
        for size in [(941,1672),(1086,1448)]:
            with self.subTest(size=size):
                request=self.authorized();request['claim']=native.dispatch('native-claim',request)['claim']
                native.dispatch('native-reserve',request)
                file=self.root/f'native-{size[0]}.png';Image.new('RGB',size,(95,110,120)).save(file)
                payload=file.read_bytes();request.update(file=str(file.resolve()),sha256=hashlib.sha256(payload).hexdigest(),source_kind='synthetic_test')
                native.dispatch('native-register',request);record=native.dispatch('native-ingest',request)
                result=native.dispatch('native-materialize',request)
                self.assertEqual(result['state']['units'][request['unit']]['status'],'completed')
                from tools.raw_library import load
                asset=load(request['category'],record['asset']);receipt=lib.read(asset['receipt_path'])
                self.assertEqual(Path(receipt['source']['provider_original']).read_bytes(),payload)
                self.assertEqual(receipt['source']['source_returned_size'],f'{size[0]}x{size[1]}')
                self.assertEqual(receipt['source']['normalized_to'],'1024x1536')
                self.assertEqual(result['state']['scopes'][request['scope']]['calls_used'],1)
                # API size validation remains strict; native acceptance cannot relax it.
                with self.assertRaisesRegex(Exception,'预期'):
                    worker.save_task_raw(self.root/f'api-{size[0]}.png',payload,{'provider':'openai'},'cover')


if __name__ == '__main__':
    unittest.main()
