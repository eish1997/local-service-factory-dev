"""Isolated repair, storage, rendering and licence failure paths; no API calls."""
import hashlib
import unittest
from unittest.mock import patch
from PIL import Image
from tools import task_library as lib,task_worker as worker,task_actions as actions
from tests import test_task_continuation as continuation,test_shared_tasks as shared


class TaskRobustness(unittest.TestCase):
    setUp=shared.SharedTasks.setUp
    batch=shared.SharedTasks.batch
    request=shared.SharedTasks.request
    ready=shared.SharedTasks.ready
    create_task=continuation.TaskContinuation.create_task
    payload=continuation.TaskContinuation.payload
    seed=continuation.TaskContinuation.seed

    def raw(self,b,group,unit):
        target=lib.unit_raw(b['category'],b['id'],group,unit);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(self.payload())
        lib.write(target.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        return target

    def render(self,category,batch,data,rows,snapshot):
        for row in rows:
            positions={u['delivery_position'] for u in row['units']}
            for pos in positions:
                units=[u for u in row['units'] if u['delivery_position']==pos]
                if not all(worker.raw_valid(category,batch,row['group'],u) for u in units):continue
                kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
                target=lib.delivery_path(category,batch,row['group'],pos,kind);target.parent.mkdir(parents=True,exist_ok=True)
                Image.new('RGB',worker.images.parse_size(units[0]['final_size']),'blue').save(target)
                lib.write(target.with_suffix('.validation.json'),{'status':'pending','service_role':units[0].get('service_role'),'postprocess_record':{'sources':[str(lib.unit_raw(category,batch,row['group'],u)) for u in units]}})

    def start_repair(self,b,position,token='repair'):
        child=lib.dispatch('repair-prepare',{'category':b['category'],'batch':b['id'],'group':1,'position':position,'request_id':token})
        req={'category':b['category'],'batch':child['id'],'groups':[1]}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(req)
            task=lib.start({**req,'request_id':'run-'+token,'authorization':'execute_selected_groups','plan_sha256':plan['plan_sha256']})
        return child,task,plan

    def test_triptych_repairs_only_missing_panel_and_parent_can_continue(self):
        b,req,target,file,rows=self.create_task();units=rows[0]['units'];panels=[u for u in units if u['delivery_position']==2]
        for u in panels[:2]:self.raw(b,1,u)
        attempts={u['id']:1 for u in panels[:2]};attempts[panels[2]['id']]=2
        results={u['id']:{'status':'generated'} for u in panels[:2]};results[panels[2]['id']]={'status':'failed','error':'transient'}
        self.seed(file,results,attempts);lic=(file.parent/'license.json').read_bytes()
        base=lib.batch_dir(b['category'],b['id']);evidence={p:p.read_bytes() for p in (base/'manifest.json',base/'groups/0001.json',base/'snapshot.json')}
        raw_before={u['id']:lib.unit_raw(b['category'],b['id'],1,u).read_bytes() for u in panels[:2]}
        child,task,plan=self.start_repair(b,2)
        self.assertEqual((plan['pending_count'],plan['reused_count'],plan['max_requests']),(1,2,2))
        fresh=lib.selected(lib.batch_dir(b['category'],child['id']),child,[1])[0]['units']
        self.assertEqual([u['prompt'] for u in fresh],[u['prompt'] for u in panels])
        self.assertEqual([u['service_role'] for u in fresh],[u['service_role'] for u in panels])
        calls=[]
        self.assertEqual(worker.run(b['category'],child['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=self.render),0)
        self.assertEqual(calls,[panels[2]['prompt']])
        self.assertEqual((file.parent/'license.json').read_bytes(),lic);self.assertEqual(lib.read(file)['status'],'paused')
        for p,content in evidence.items():self.assertEqual(p.read_bytes(),content)
        for u in panels[:2]:self.assertEqual(lib.unit_raw(b['category'],b['id'],1,u).read_bytes(),raw_before[u['id']])
        self.assertTrue(all(worker.raw_valid(b['category'],b['id'],1,u) for u in panels))
        self.assertEqual(lib.view({**req,'limit':1})['groups'][0]['status'],'paused')
        with self.ready(),patch.object(lib,'launch',return_value=99999999):resumed=lib.resume(target)
        self.assertEqual((resumed['resume_summary']['ready_count'],resumed['resume_summary']['reused_count']),(4,3))
        worker.run(b['category'],b['id'],target['task'],generate=lambda *a:self.payload(),clients=[(1,object())],render=self.render)
        done=lib.read(file);self.assertEqual(done['status'],'completed');self.assertEqual(done['requests_used'],8)
        self.assertEqual(done['attempts'][panels[2]['id']],2)

    def test_uncertain_download_and_local_save_forbid_new_paid_repair(self):
        b,req,target,file,rows=self.create_task();unit=rows[0]['units'][0]
        for i,result in enumerate(({'status':'request_reserved'},{'status':'failed','error':'image_download_failed'},{'status':'failed','error':'local_save_failed'})):
            self.seed(file,{unit['id']:result},{unit['id']:1})
            for mode in ('repair','reassemble'):
                with self.assertRaisesRegex(ValueError,'核对已返回结果'):
                    actions.prepare_replacement({'category':b['category'],'batch':b['id'],'group':1,'position':1,'request_id':f'blocked-{i}-{mode}','mode':mode})

    def test_corrupt_raw_receipt_skips_without_stopping_other_units(self):
        b,req,target,file,rows=self.create_task();unit=rows[0]['units'][0];raw=self.raw(b,1,unit)
        raw.with_suffix('.receipt.json').write_text('{broken',encoding='utf-8');before=raw.read_bytes();calls=[]
        self.assertFalse(worker.raw_valid(b['category'],b['id'],1,unit))
        worker.run(b['category'],b['id'],target['task'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=lambda *a:None)
        self.assertNotIn(unit['prompt'],calls);self.assertEqual(len(calls),6);self.assertEqual(raw.read_bytes(),before)
        self.assertEqual(lib.read(file)['resume_summary']['reasons'],{'saved_result':1})
        raw.with_suffix('.receipt.json').write_text('[]',encoding='utf-8')
        self.assertFalse(worker.raw_valid(b['category'],b['id'],1,unit))

    def test_repair_preparation_recovers_interrupted_reused_copy_idempotently(self):
        b=self.batch();path=lib.batch_dir(b['category'],b['id']);units=lib.selected(path,b,[1])[0]['units'];panels=[u for u in units if u['delivery_position']==2]
        self.raw(b,1,panels[0]);self.raw(b,1,panels[1])
        req={'category':b['category'],'batch':b['id'],'group':1,'position':2,'request_id':'copy-recovery','mode':'repair'}
        from tools import category_4k_raw
        original=category_4k_raw.publish_immutable_bytes;calls=[]
        def interrupted(a,c):
            calls.append(1)
            if len(calls)==2:raise PermissionError('temporary reader lock')
            return original(a,c)
        with patch.object(category_4k_raw,'publish_immutable_bytes',side_effect=interrupted):
            with self.assertRaises(PermissionError):actions.prepare_replacement(req)
        self.assertEqual(len(calls),2)
        child=actions.prepare_replacement(req)
        with self.ready():plan=lib.plan({'category':b['category'],'batch':child['id'],'groups':[1]})
        self.assertEqual((plan['pending_count'],plan['reused_count'],plan['max_requests']),(1,2,2))

    def test_failed_revision_can_repair_its_saved_panels_without_other_scope(self):
        b=self.batch();req={'category':b['category'],'batch':b['id'],'group':1,'position':2}
        child=actions.prepare_replacement({**req,'request_id':'failed-revision'})
        fresh=lib.selected(lib.batch_dir(b['category'],child['id']),child,[1])[0]['units']
        self.raw(child,1,fresh[0]);self.raw(child,1,fresh[1])
        repaired=lib.dispatch('repair-prepare',{**req,'source_revision':child['id'],'request_id':'repair-revision'})
        with self.ready():plan=lib.plan({'category':b['category'],'batch':repaired['id'],'groups':[1]})
        self.assertEqual((plan['pending_count'],plan['reused_count']),(1,2))
        row=lib.selected(lib.batch_dir(b['category'],repaired['id']),repaired,[1])[0]
        self.assertEqual([u['prompt'] for u in row['units']],[u['prompt'] for u in fresh])
        other=self.batch()
        with self.assertRaisesRegex(ValueError,'关联不一致'):lib.dispatch('repair-prepare',{**req,'batch':other['id'],'source_revision':child['id'],'request_id':'wrong-source'})

    def test_timeout_after_response_never_reissues_generation(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=[];original=worker.save_task_raw
        def save(raw,*args):
            if raw.stem==bad['id']:raise TimeoutError('local filesystem timeout')
            return original(raw,*args)
        with patch.object(worker,'save_task_raw',side_effect=save):
            worker.run(b['category'],b['id'],target['task'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=lambda *a:None)
        state=lib.read(file);self.assertEqual(len(calls),7);self.assertEqual(calls.count(bad['prompt']),1)
        self.assertEqual(state['results'][bad['id']]['error'],'local_save_failed');self.assertEqual(state['resume_summary']['reasons'],{'saved_result':1})

    def overlay(self,raw,target,*args,**kwargs):
        target.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',worker.images.parse_size(args[5]),'blue').save(target)
        lib.write(target.with_suffix('.validation.json'),{'status':'pending','postprocess_record':{'sources':[str(raw)]}})

    def triptych(self,records,target,*args,**kwargs):
        target.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',worker.images.parse_size(records[0]['final_size']),'blue').save(target)
        lib.write(target.with_suffix('.validation.json'),{'status':'pending','postprocess_record':{'sources':[r['raw_target'] for r in records]}})

    def test_local_render_failure_finishes_api_work_then_recovers_without_keys(self):
        b,req,target,file,rows=self.create_task();calls=[];render_calls=[]
        def overlay(raw,out,*a,**kw):
            render_calls.append(kw['delivery_target_id'])
            if kw['delivery_target_id'].endswith(':d1'):raise OSError('font unavailable')
            self.overlay(raw,out,*a,**kw)
        with patch.object(worker.images,'apply_overlays',side_effect=overlay),patch.object(worker.images,'compose_triptych',side_effect=self.triptych):
            code=worker.run(b['category'],b['id'],target['task'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())])
        state=lib.read(file);self.assertEqual(code,1);self.assertEqual(len(calls),7);self.assertEqual(state['status'],'failed')
        self.assertEqual(len(state['local_render_errors']),1);self.assertEqual(state['local_render_errors'][0]['attempts'],2)
        self.assertEqual(len(lib.view({**req,'limit':1})['groups'][0]['images']),4)
        lic=(file.parent/'license.json').read_bytes()
        with patch.object(lib,'api_config',side_effect=AssertionError('API setup must not run')),patch.object(lib,'readiness',side_effect=AssertionError('keys must not be required')),patch.object(lib,'launch',return_value=99999999):lib.resume(target)
        with patch.object(worker.images,'apply_overlays',side_effect=self.overlay),patch.object(worker.images,'compose_triptych',side_effect=self.triptych),patch.object(worker.images,'openai_clients_by_slot') as clients:
            self.assertEqual(worker.run(b['category'],b['id'],target['task']),0);clients.assert_not_called()
        self.assertEqual(lib.read(file)['status'],'completed');self.assertEqual((file.parent/'license.json').read_bytes(),lic)

    def test_licence_rejects_corrupt_counts_and_out_of_scope_unit(self):
        b,req,target,file,rows=self.create_task();state=lib.read(file);lic=lib.read(file.parent/'license.json');unit=rows[0]['units'][0]['id']
        corrupt=[{'requests_used':1,'attempts':{unit:3}},{'requests_used':1,'attempts':{unit:True}},{'requests_used':1,'attempts':{unit:-1}},{'requests_used':2,'attempts':{unit:1}},{'requests_used':1,'attempts':{'other-unit':1}}]
        for values in corrupt:
            lib.write(file.parent/'license.json',{**lic,**values})
            with self.assertRaises(ValueError):lib.synchronize_license(file,state.copy())
        lib.write(file.parent/'license.json',lic)
        with self.assertRaisesRegex(ValueError,'超过许可'):lib.synchronize_license(file,{**state,'requests_used':1,'attempts':{unit:1}})

    def test_local_render_recovery_with_other_blocked_units_needs_no_api(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][-1]
        for unit in rows[0]['units'][:-1]:self.raw(b,1,unit)
        self.seed(file,{bad['id']:{'status':'failed','error':'unknown','http_status':451}},{bad['id']:1})
        with patch.object(worker.images,'apply_overlays',side_effect=OSError('local failure')),patch.object(worker.images,'compose_triptych',side_effect=self.triptych):
            self.assertEqual(worker.run(b['category'],b['id'],target['task']),1)
        lic=(file.parent/'license.json').read_bytes()
        with patch.object(lib,'api_config',side_effect=AssertionError('no API')),patch.object(lib,'readiness',side_effect=AssertionError('no keys')),patch.object(lib,'launch',return_value=99999999):lib.resume(target)
        with patch.object(worker.images,'apply_overlays',side_effect=self.overlay),patch.object(worker.images,'compose_triptych',side_effect=self.triptych),patch.object(worker.images,'openai_clients_by_slot') as clients:
            self.assertEqual(worker.run(b['category'],b['id'],target['task']),0);clients.assert_not_called()
        self.assertEqual(lib.read(file)['status'],'completed_with_errors')
        self.assertEqual((file.parent/'license.json').read_bytes(),lic)

    def test_cancelled_worker_and_client_cleanup_do_not_corrupt_outcome(self):
        b,req,target,file,rows=self.create_task();state=lib.read(file);state['status']='cancelled';lib.write(file,state)
        calls=[];self.assertEqual(worker.run(b['category'],b['id'],target['task'],generate=lambda *a:calls.append(a),clients=[(1,object())],render=lambda *a:None),1)
        self.assertEqual(calls,[]);self.assertEqual(lib.read(file)['status'],'cancelled')
        b,req,target,file,rows=self.create_task()
        class Client:
            def close(self):raise OSError('close failed')
        self.assertEqual(worker.run(b['category'],b['id'],target['task'],generate=lambda *a:self.payload(),clients=[(1,Client())],render=lambda *a:None),0)
        self.assertEqual(lib.read(file)['status'],'completed')

    def test_parallel_revisions_cannot_generate_same_delivery_twice(self):
        b=self.batch();request={'category':b['category'],'batch':b['id'],'group':1,'position':1}
        first=actions.prepare_replacement({**request,'request_id':'first'});second=actions.prepare_replacement({**request,'request_id':'second'})
        with self.ready(),patch.object(lib,'launch',return_value=__import__('os').getpid()):
            req={'category':b['category'],'batch':first['id'],'groups':[1]};plan=lib.plan(req)
            lib.start({**req,'request_id':'active','authorization':'execute_selected_groups','plan_sha256':plan['plan_sha256']})
            other=lib.plan({'category':b['category'],'batch':second['id'],'groups':[1]})
            self.assertTrue(any('同一图片范围' in s for s in other['blocks']))

    def test_bad_authentication_slot_is_isolated_and_other_keys_continue(self):
        b,req,target,file,rows=self.create_task();bad=object();good=object();calls=[]
        class Unauthorized(Exception):status_code=401
        def generate(c,cfg,p):
            calls.append(c)
            if c is bad:raise Unauthorized('private credential must not be recorded')
            return self.payload()
        worker.run(b['category'],b['id'],target['task'],generate=generate,clients=[(1,bad),(2,good)],render=lambda *a:None)
        state=lib.read(file);self.assertEqual(state['status'],'completed');self.assertEqual(state['requests_used'],8)
        self.assertEqual(calls.count(bad),1);self.assertEqual(state['quarantined_slots'],[1])

    def test_delivery_state_lock_conflict_keeps_other_units(self):
        b,req,target,file,rows=self.create_task();units=rows[0]['units'];calls=[]
        reserved=lib.read(file.parent/'license.json')['requests_used']
        original=worker.lib.lock
        def locked(path,wait_seconds=0):
            if str(path).replace('\\','/').endswith('dashboard_delivery_state.lock'):
                raise ValueError('已有操作正在进行，请稍后重试')
            return original(path,wait_seconds)
        with patch.object(worker.lib,'lock',side_effect=locked),patch.object(worker.images,'apply_overlays',side_effect=self.overlay),patch.object(worker.images,'compose_triptych',side_effect=self.triptych):
            worker.run(b['category'],b['id'],target['task'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())])
        state=lib.read(file)
        self.assertNotEqual(state['status'],'failed')
        self.assertNotIn('请让 Agent 检查',state.get('error') or '')
        self.assertEqual(len(calls),len(units))
        self.assertEqual(state['requests_used'],reserved+len(units))
        self.assertEqual(lib.read(file.parent/'license.json')['requests_used'],state['requests_used'])
        for unit in units:
            self.assertEqual(state['attempts'][unit['id']],1)
            self.assertTrue(worker.raw_valid(b['category'],b['id'],1,unit))

    def test_lock_release_permission_error_does_not_fail_the_batch(self):
        from pathlib import Path
        probe=lib.ROOT/'.runtime'/'permission-release.lock'
        real=Path.unlink
        def blocked(target,*args,**kwargs):
            if target.name.endswith('.lock'):raise PermissionError('sharing violation')
            return real(target,*args,**kwargs)
        with patch.object(Path,'unlink',blocked):
            with lib.lock(probe):
                self.assertTrue(probe.exists())
            self.assertFalse(probe.exists())
            with lib.lock(probe):
                self.assertTrue(probe.exists())
        b,req,target,file,rows=self.create_task();units=rows[0]['units'];calls=[]
        with patch.object(Path,'unlink',blocked),patch.object(worker.images,'apply_overlays',side_effect=self.overlay),patch.object(worker.images,'compose_triptych',side_effect=self.triptych):
            worker.run(b['category'],b['id'],target['task'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())])
        state=lib.read(file)
        self.assertNotEqual(state['status'],'failed')
        self.assertNotIn('请让 Agent 检查',state.get('error') or '')
        self.assertEqual(len(calls),len(units))
        self.assertTrue(all(worker.raw_valid(b['category'],b['id'],1,unit) for unit in units))

    def test_manifest_mismatch_fails_with_its_own_message(self):
        b,req,target,file,rows=self.create_task();state=lib.read(file);lic=lib.read(file.parent/'license.json');calls=[]
        state['manifest_sha256']='0'*64;lic['terms']['manifest_sha256']='0'*64;state['license_sha256']=lib.digest(lic['terms'])
        lib.write(file.parent/'license.json',lic);lib.write(file,state)
        worker.run(b['category'],b['id'],target['task'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=lambda *a:None)
        done=lib.read(file)
        self.assertEqual(done['status'],'failed')
        self.assertIn('冻结任务清单不一致',done.get('error') or '')
        self.assertNotIn('请让 Agent 检查',done.get('error') or '')
        self.assertEqual(calls,[])
        self.assertEqual(done.get('requests_used',0),0)

    def test_download_panel_does_not_block_sibling_repair(self):
        b=self.batch();path=lib.batch_dir(b['category'],b['id'])
        panels=[u for u in lib.selected(path,b,[1])[0]['units'] if u['delivery_position']==2]
        self.assertEqual(len(panels),3)
        download,exhausted,kept=panels
        req={'category':b['category'],'batch':b['id'],'groups':[1],'unit_ids':[u['id'] for u in panels],'auto_complete':True}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(req);self.assertFalse(plan['blocks'])
            task=lib.start({**req,'request_id':'sibling-repair','plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups'})
        file=path/'tasks'/task['id']/'task.json'
        self.raw(b,1,kept)
        self.seed(file,{
            download['id']:{'status':'failed','error':'image_download_failed','request_number':1,'attempt':1},
            exhausted['id']:{'status':'failed','error':'transient','request_number':3,'attempt':2},
            kept['id']:{'status':'generated','request_number':2,'attempt':1},
        },{download['id']:1,exhausted['id']:2,kept['id']:1})
        calls=[]
        with self.ready():
            worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=self.render)
        state=lib.read(file)
        self.assertNotIn(download['prompt'],calls)
        self.assertEqual(state['attempts'][download['id']],1)
        self.assertEqual(calls,[exhausted['prompt']])
        self.assertLessEqual(state['auto_recovery']['requests_used'],2)
        self.assertGreaterEqual(state['auto_recovery']['requests_used'],1)
        child=next(iter(state['auto_recovery']['children'].values()))
        self.assertEqual(child['units'],[exhausted['id']])
        self.assertTrue(worker.raw_valid(b['category'],child['batch'],1,lib.selected(lib.batch_dir(b['category'],child['batch']),lib.load_batch(b['category'],child['batch'])[1],[1])[0]['units'][1]))

    def test_missing_triptych_panel_is_recorded_without_new_post(self):
        b,req,target,file,rows=self.create_task();units=rows[0]['units']
        panels=[u for u in units if u['kind']=='triptych_panel']
        self.assertGreaterEqual(len(panels),2)
        missing=panels[0]
        for unit in units:
            if unit is not missing:self.raw(b,1,unit)
        self.seed(file,{u['id']:{'status':'generated'} for u in units},{u['id']:1 for u in units})
        calls=[];composed=[]
        with patch.object(worker.images,'apply_overlays',side_effect=self.overlay),patch.object(worker.images,'compose_triptych',side_effect=lambda *a,**k:composed.append(1)):
            worker.run(b['category'],b['id'],target['task'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())])
        state=lib.read(file)
        records=[item for item in state.get('local_render_errors') or [] if item['position']==missing['delivery_position']]
        self.assertEqual(calls,[])
        self.assertEqual(composed,[])
        self.assertEqual(state['attempts'][missing['id']],1)
        self.assertEqual(state['requests_used'],len(units))
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['error'],'MissingRaw')
        self.assertEqual(records[0]['attempts'],0)


if __name__=='__main__':unittest.main()
