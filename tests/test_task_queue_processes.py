"""Actual process-boundary queue checks, with no provider API or production data."""
import collections
import hashlib
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tests.test_shared_tasks import SharedTasks
from tools import task_assets as assets, task_library as lib, task_queue as queue
from tools import task_worker as worker


class QueueProcessIntegration(unittest.TestCase):
    setUp = SharedTasks.setUp
    batch = SharedTasks.batch
    request = SharedTasks.request

    def prepare(self, category, model, color, single=False, phone=None, cap=None):
        if phone is None:
            batch = self.batch(category)
        else:
            batch = lib.assemble({'category': category, 'count': 1, 'seed': 1401, 'phone': phone})
        request = self.request(batch, [1])
        if single:
            request['unit_ids'] = ['g0001_u01']
        if cap is not None:request['auto_complete']={'mode':'continuous','total_max_requests':cap}
        config = {'model': model, 'api_size': '1024x1536', 'quality': 'medium', 'output_format': 'png'}
        with patch.object(lib, 'api_config', return_value=config), patch.object(lib, 'readiness', return_value=([], [1])), patch.object(lib, 'launch', return_value=99999999):
            plan = lib.plan(request)
            task = lib.start({**request, 'plan_sha256': plan['plan_sha256'], 'request_id': model,
                              'authorization': 'execute_selected_groups'})
        rows = lib.task_rows(lib.batch_dir(category, batch['id']), batch, task)
        file = self.root / 'process-specs.json'
        specs = lib.read(file) if file.exists() else {}
        specs[task['id']] = {'config': config, 'color': color,
                             'prompts': [u['prompt_sha256'] for r in rows for u in r['units']]}
        lib.write(file, specs)
        lib.write(self.root / 'fixture-catalog.json', self.configs)
        return batch, task, rows

    def launch(self, batch, task, mode='run'):
        helper = Path(__file__).with_name('queue_process_fixture.py')
        child = subprocess.Popen([sys.executable, '-X', 'utf8', str(helper), str(self.root),
                                  batch['category'], batch['id'], task['id'], mode],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

        self.addCleanup(cleanup)
        return child

    def wait_for(self, condition, children=(), seconds=25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return
            for child in children:
                if child.poll() is not None:
                    output = child.communicate(timeout=5)[0]
                    self.fail('fixture exited before checkpoint: ' + output[-2000:])
            time.sleep(.05)
        self.fail('fixture checkpoint not observed')

    def journal(self):
        import json
        file = self.root / 'process-journal.jsonl'
        return [json.loads(line) for line in file.read_text(encoding='utf-8').splitlines()] if file.exists() else []

    def statefile(self, batch, task):
        return lib.io_path(lib.batch_dir(batch['category'], batch['id']) / 'tasks' / task['id'] / 'task.json',force=True)

    def test_two_real_workers_share_slots_keep_frozen_context_and_survive_new_reader(self):
        self.assert_two_worker_contexts()

    def test_continuous_multi_batch_contexts_and_new_reader_keep_separate_caps(self):
        self.assert_two_worker_contexts(cap=10)

    def assert_two_worker_contexts(self,cap=None):
        first = self.prepare('road_rescue', 'offline-red', 'red',cap=cap)
        changed_root = self.root.parent / (self.root.name + '-中文原图资产')
        changed_root.mkdir()
        assets.save({'path': str(changed_root.resolve())})
        second = self.prepare('truck_rescue', 'offline-blue', 'blue', phone='13800138000',cap=cap)
        children = [self.launch(batch, task) for batch, task, _ in (first, second)]
        self.wait_for(lambda: all((self.root / ('ready-' + task['id'])).exists() for _, task, _ in (first, second)), children)
        (self.root / 'process-go').write_text('authorized isolated fixtures', encoding='utf-8')
        for child in children:
            output = child.communicate(timeout=55)[0]
            self.assertEqual(child.returncode, 0, output[-2000:])
        journal = self.journal()
        active = None
        owners = []
        for event in journal:
            if event['kind'] == 'post':
                self.assertIsNone(active, 'same slot was used simultaneously')
                active = event['task']; owners.append(active)
            elif event['kind'] == 'return':
                self.assertEqual(active, event['task']); active = None
        self.assertIsNone(active)
        self.assertEqual(collections.Counter(owners), {first[1]['id']: 7, second[1]['id']: 7})
        self.assertLessEqual(max(len(list(group)) for _, group in __import__('itertools').groupby(owners)), 2)
        all_cards = queue.view({'summary_only': True})
        self.assertEqual((all_cards['total'], all_cards['counts']['completed'], all_cards['delivery_counts']['ready']), (14, 14, 10))
        if cap is not None:self.assertEqual(all_cards['request_counts'],{'used':14,'maximum':2*cap})
        for batch, task, rows in (first, second):
            state = lib.read(self.statefile(batch, task))
            self.assertEqual((state['status'], state['requests_used']), ('completed', 7))
            snapshot = lib.read(lib.batch_dir(batch['category'], batch['id']) / 'snapshot.json')
            spec = lib.read(self.root / 'process-specs.json')[task['id']]
            events = [e for e in journal if e['task'] == task['id'] and e['kind'] == 'post']
            self.assertEqual({e['prompt'] for e in events}, set(spec['prompts']))
            for row in rows:
                for unit in row['units']:
                    self.assertTrue(worker.raw_valid(batch['category'], batch['id'], row['group'], unit))
                    kind = 'triptych' if unit['kind'] == 'triptych_panel' else unit['kind']
                    target = lib.delivery_path(batch['category'], batch['id'], 1, unit['delivery_position'], kind)
                    validation = lib.read(target.with_suffix('.validation.json'))
                    self.assertIn(snapshot['batch_contact']['phone'], str(validation['expected_text']))
                    self.assertTrue(worker.delivery_valid(target, unit))
        # A separately imported reader reconstructs the same stable card IDs.
        code = "import sys,json;from pathlib import Path;from tools import task_library as l,task_queue as q;l.ROOT=Path(sys.argv[1]);r=q.view({'limit':200});print(json.dumps({'total':r['total'],'ids':sorted(c['id'] for c in r['cards'])}))"
        fresh = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(self.root)], capture_output=True, text=True, timeout=25)
        self.assertEqual(fresh.returncode, 0, fresh.stderr[-2000:])
        import json
        value = json.loads(fresh.stdout)
        self.assertEqual(value['total'], 14)
        self.assertEqual(value['ids'], sorted(c['id'] for c in queue.view({'limit': 200})['cards']))

    def test_actual_kill_unknown_and_spooled_result_never_post_again(self):
        for mode, exhausted in (('crash_unknown', False), ('crash_returned', False), ('crash_returned', True)):
            with self.subTest(mode=mode, exhausted=exhausted):
                batch, task, rows = self.prepare('road_rescue', 'offline-' + mode + str(exhausted), 'gray', single=True)
                (self.root / 'process-go').write_text('isolated single-unit checkpoint', encoding='utf-8')
                child = self.launch(batch, task, mode)
                checkpoint = self.root / ('checkpoint-' + task['id'])
                self.wait_for(checkpoint.exists, [child])
                file = self.statefile(batch, task)
                before = lib.read(file.parent / 'license.json')
                self.assertEqual(before['requests_used'], 1)
                child.kill(); child.communicate(timeout=5)
                self.assertIsNotNone(child.returncode)
                if exhausted:
                    state = lib.read(file)
                    state.setdefault('auto_recovery', {})['local_attempts'] = {rows[0]['units'][0]['id']: 3}
                    lib.write(file, state)
                    from tools.task_auto_recovery import has_returned_evidence
                    self.assertFalse(has_returned_evidence(batch['category'], batch['id'], state, rows))
                resumed = self.launch(batch, task, 'resume')
                output = resumed.communicate(timeout=35)[0]
                self.assertEqual(resumed.returncode, 0, output[-2000:])
                after = lib.read(file.parent / 'license.json')
                self.assertEqual(after, before, 'process recovery changed licence/counters')
                self.assertEqual(len([e for e in self.journal() if e['task'] == task['id'] and e['kind'] == 'post']), 1)
                raw_ok = worker.raw_valid(batch['category'], batch['id'], 1, rows[0]['units'][0])
                result = lib.read(self.root / ('process-result-' + task['id'] + '.json'))
                if mode == 'crash_unknown':
                    self.assertTrue(result['resume_blocked']); self.assertFalse(raw_ok)
                else:
                    self.assertTrue(raw_ok); self.assertEqual(result['state'], 'completed')
                    if exhausted:
                        ledger = lib.read(file)['auto_recovery']; uid = rows[0]['units'][0]['id']
                        self.assertEqual(ledger['local_attempts'][uid], 4)
                        self.assertEqual(ledger['local_limits'][uid], 6)
                        self.assertEqual(len(ledger['local_resume_grants']), 1)

    def test_continuous_cap_survives_actual_kill_before_licence_and_after_return(self):
        from tools import task_budget as budget
        for mode in ('crash_budget_reserved','crash_unknown','crash_returned'):
            with self.subTest(mode=mode):
                batch,task,rows=self.prepare('road_rescue','offline-cap-'+mode,'gray',single=True,cap=7)
                (self.root/'process-go').write_text('isolated cap checkpoints',encoding='utf-8')
                child=self.launch(batch,task,mode)
                self.wait_for((self.root/('checkpoint-'+task['id'])).exists,[child])
                file=self.statefile(batch,task)
                before_budget=(file.parent/'budget.json').read_bytes()
                before_licence=(file.parent/'license.json').read_bytes()
                self.assertEqual(budget.progress(lib.read(file))['used'],1)
                if mode=='crash_budget_reserved':self.assertEqual(lib.read(file.parent/'license.json')['requests_used'],0)
                child.kill();child.communicate(timeout=5)
                resumed=self.launch(batch,task,'resume');output=resumed.communicate(timeout=35)[0]
                self.assertEqual(resumed.returncode,0,output[-2000:])
                self.assertEqual((file.parent/'budget.json').read_bytes(),before_budget)
                if mode=='crash_budget_reserved':
                    import json
                    after=lib.read(file.parent/'license.json')
                    self.assertEqual(after['terms'],json.loads(before_licence)['terms'])
                    self.assertEqual((after['requests_used'],after['attempts']), (1,{'g0001_u01':1}))
                else:self.assertEqual((file.parent/'license.json').read_bytes(),before_licence)
                self.assertEqual(sum(e['kind']=='post' and e['task']==task['id'] for e in self.journal()),0 if mode=='crash_budget_reserved' else 1)
                cards=queue.view({'category':batch['category'],'batch':batch['id']})
                self.assertEqual(cards['request_counts']['used'],1)
                self.assertEqual(worker.raw_valid(batch['category'],batch['id'],1,rows[0]['units'][0]),mode=='crash_returned')
                if mode=='crash_returned':self.assertEqual(lib.read(file)['status'],'completed')

    def test_exhausted_pool_recovers_and_publishes_child_return_without_api(self):
        from tools import task_budget as budget
        batch,task,rows=self.prepare('road_rescue','offline-child-return','gray',single=True,cap=3)
        (self.root/'process-go').write_text('isolated returned child',encoding='utf-8')
        child=self.launch(batch,task,'crash_child_returned')
        self.wait_for((self.root/('checkpoint-'+task['id'])).exists,[child])
        file=self.statefile(batch,task);before=(file.parent/'budget.json').read_bytes()
        self.assertEqual(budget.progress(lib.read(file)),{'used':3,'maximum':3,'remaining':0})
        child.kill();child.communicate(timeout=5)
        resumed=self.launch(batch,task,'resume');output=resumed.communicate(timeout=35)[0]
        self.assertEqual(resumed.returncode,0,output[-2000:])
        self.assertEqual((file.parent/'budget.json').read_bytes(),before)
        self.assertEqual(sum(e['kind']=='post' for e in self.journal()),3)
        self.assertEqual(lib.read(file)['status'],'completed')
        self.assertTrue(worker.raw_valid(batch['category'],batch['id'],1,rows[0]['units'][0]))
        result=queue.view({'category':batch['category'],'batch':batch['id']})
        self.assertEqual((result['request_counts']['used'],result['counts']['completed'],result['delivery_counts']['ready']),(3,1,1))

    def test_free_child_recovery_rejects_changed_frozen_manifest_without_post(self):
        batch,task,rows=self.prepare('road_rescue','offline-child-tamper','gray',single=True,cap=3)
        (self.root/'process-go').write_text('isolated frozen child',encoding='utf-8')
        child=self.launch(batch,task,'crash_child_returned')
        self.wait_for((self.root/('checkpoint-'+task['id'])).exists,[child])
        file=self.statefile(batch,task);before=(file.parent/'budget.json').read_bytes()
        child.kill();child.communicate(timeout=5)
        entry=next(iter(lib.read(file)['auto_recovery']['children'].values()))
        path,data=lib.load_batch(batch['category'],entry['batch']);row=lib.read(path/'groups/0001.json')
        row['units'][0]['service_role']='changed fixture theme';row['sha256']=lib.digest(row['units'])
        manifest=[{'group':1,'sha256':row['sha256']}];data['manifest_sha256']=lib.digest(manifest)
        lib.write(path/'groups/0001.json',row);lib.write(path/'manifest.json',manifest);lib.write(path/'batch.json',data)
        resumed=self.launch(batch,task,'resume');output=resumed.communicate(timeout=35)[0]
        self.assertEqual(resumed.returncode,0,output[-2000:])
        self.assertTrue(lib.read(self.root/('process-result-'+task['id']+'.json'))['resume_blocked'])
        self.assertEqual((file.parent/'budget.json').read_bytes(),before)
        self.assertEqual(sum(e['kind']=='post' for e in self.journal()),3)
        self.assertFalse(lib.delivery_path(batch['category'],batch['id'],1,1,'cover').exists())
        self.assertNotEqual(lib.read(file)['status'],'completed')

    def test_disk_and_stock_failures_recover_free_and_export_failure_keeps_evidence(self):
        import errno
        import io
        import zipfile
        from PIL import Image
        from tools import raw_library as stock
        encoded=io.BytesIO();Image.new('RGB',(1024,1536),'gray').save(encoded,format='PNG')
        for stage in ('raw', 'stock'):
            with self.subTest(stage=stage):
                batch,task,rows=self.prepare('road_rescue','offline-storage-'+stage,'gray')
                bad=rows[0]['units'][0]['id'];calls=[]
                original_save=worker.save_task_raw;original_register=stock.register
                def save(path,*args,**kwargs):
                    if stage=='raw' and path.stem==bad:
                        raise OSError(errno.ENOSPC,'fixture disk full')
                    return original_save(path,*args,**kwargs)
                def register(category,batch_id,group,unit):
                    if stage=='stock' and unit['id']==bad:
                        raise OSError(errno.ENOSPC,'fixture stock unavailable')
                    return original_register(category,batch_id,group,unit)
                with patch.object(worker,'save_task_raw',side_effect=save),patch.object(stock,'register',side_effect=register):
                    worker.run(batch['category'],batch['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),encoded.getvalue())[1],clients=[(1,object())])
                file=self.statefile(batch,task);license_bytes=(file.parent/'license.json').read_bytes()
                state=lib.read(file)
                self.assertEqual(len(calls),7)
                self.assertEqual(state['status'],'failed' if stage=='stock' else 'completed_with_errors')
                if stage=='stock':self.assertTrue(state['local_library_errors'])
                target={'category':batch['category'],'batch':batch['id'],'task':task['id']}
                with patch.object(lib,'api_config',side_effect=AssertionError('free recovery needs no API')),patch.object(lib,'readiness',side_effect=AssertionError('free recovery needs no keys')),patch.object(lib,'launch',return_value=99999999):
                    lib.resume(target)
                code=worker.run(batch['category'],batch['id'],task['id'],generate=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected new POST')),clients=[(1,object())])
                self.assertEqual(code,0);self.assertEqual(lib.read(file)['status'],'completed')
                self.assertEqual((file.parent/'license.json').read_bytes(),license_bytes)
                self.assertEqual(len(list(file.parent.parent.glob('*/license.json'))),1)
                queuefile=self.root/'.runtime/dashboard_delivery_state.json';queue_bytes=queuefile.read_bytes()
                evidence={}
                for unit in rows[0]['units']:
                    raw=lib.unit_raw(batch['category'],batch['id'],1,unit)
                    self.assertTrue(worker.raw_valid(batch['category'],batch['id'],1,unit))
                    evidence[raw]=raw.read_bytes();evidence[raw.with_suffix('.receipt.json')]=raw.with_suffix('.receipt.json').read_bytes()
                destination=self.root/('exports-'+stage);destination.mkdir()
                request={**target,'groups':[1],'destination':str(destination)}
                for failure in ('write','verify'):
                    with self.subTest(archive=failure):
                        guard=patch.object(zipfile.ZipFile,'write',side_effect=OSError(errno.ENOSPC,'fixture archive full')) if failure=='write' else patch.object(zipfile.ZipFile,'testzip',return_value='bad-entry')
                        with guard,self.assertRaises((OSError,ValueError)):
                            assets.package(request)
                        self.assertEqual(queuefile.read_bytes(),queue_bytes)
                        self.assertEqual(list(destination.iterdir()),[])
                        self.assertTrue(all(path.read_bytes()==data for path,data in evidence.items()))
                exported=assets.package(request)
                with zipfile.ZipFile(exported['path']) as archive:
                    self.assertEqual(len(archive.namelist()),5);self.assertIsNone(archive.testzip())
                # Shared package is an export: review and delivery queue stay intact.
                self.assertEqual(queuefile.read_bytes(),queue_bytes)
                self.assertEqual((file.parent/'license.json').read_bytes(),license_bytes)


if __name__ == '__main__':
    unittest.main()
