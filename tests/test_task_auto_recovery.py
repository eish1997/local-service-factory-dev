"""Automatic completion with isolated simulated APIs; no production requests."""
import collections
import threading
import unittest
from unittest.mock import patch
from tools import task_library as lib,task_worker as worker,task_auto_recovery as auto
from tests import test_task_robustness as fixtures


class AutomaticCompletion(unittest.TestCase):
    setUp=fixtures.TaskRobustness.setUp
    batch=fixtures.TaskRobustness.batch
    ready=fixtures.TaskRobustness.ready
    payload=fixtures.TaskRobustness.payload
    render=fixtures.TaskRobustness.render
    raw=fixtures.TaskRobustness.raw
    seed=fixtures.TaskRobustness.seed
    create_task=fixtures.TaskRobustness.create_task

    def request(self,b,groups):return {'category':b['category'],'batch':b['id'],'groups':groups,'auto_complete':True}

    def execute(self,b,target,generate):
        with self.ready():return worker.run(b['category'],b['id'],target['task'],generate=generate,clients=[(1,object())],render=self.render)

    def test_two_rounds_finish_exact_frozen_missing_panel(self):
        b,req,target,file,rows=self.create_task();units=rows[0]['units'];bad=units[3];calls=collections.Counter()
        base=lib.batch_dir(b['category'],b['id']);original={p:p.read_bytes() for p in (base/'snapshot.json',base/'manifest.json',base/'groups/0001.json')}
        def generate(c,cfg,p):
            calls[p]+=1
            if p==bad['prompt'] and calls[p]<6:raise TimeoutError('timed out')
            return self.payload()
        self.assertEqual(self.execute(b,target,generate),0)
        state=lib.read(file);self.assertEqual(state['status'],'completed')
        self.assertEqual((state['requests_used'],state['auto_recovery']['requests_used']),(8,4))
        self.assertEqual(calls[bad['prompt']],6);self.assertTrue(all(calls[u['prompt']]==1 for u in units if u!=bad))
        self.assertEqual(state['completed_units'],7)
        for p,value in original.items():self.assertEqual(p.read_bytes(),value)
        for entry in state['auto_recovery']['children'].values():
            child=lib.load_batch(b['category'],entry['batch'])[1]
            fresh=lib.selected(lib.batch_dir(b['category'],child['id']),child,[1])[0]['units']
            self.assertEqual([u['prompt'] for u in fresh],[u['prompt'] for u in units if u['delivery_position']==bad['delivery_position']])
            self.assertEqual(len(entry['units']),1)
        self.assertTrue(all(worker.raw_valid(b['category'],b['id'],1,u) for u in units))
        self.assertEqual(lib.read(file.parent/'license.json')['requests_used'],8)
        self.assertEqual(state['auto_complete']['max_requests'],28)

    def test_exhaustion_is_bounded_across_resume(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=[]
        def generate(c,cfg,p):
            calls.append(p)
            if p==bad['prompt']:raise TimeoutError('timed out')
            return self.payload()
        self.execute(b,target,generate);state=lib.read(file)
        self.assertEqual(state['status'],'completed_with_errors');self.assertEqual(calls.count(bad['prompt']),6)
        self.assertEqual(state['auto_recovery']['requests_used'],4)
        with self.assertRaisesRegex(ValueError,'没有可'):lib.resume(target)
        before=len(calls);self.execute(b,target,generate);self.assertEqual(len(calls),before)

    def test_local_save_failure_recovers_without_new_post(self):
        b,req,target,file,rows=self.create_task();calls=[];original=worker.save_task_raw
        def flaky(*args,**kwargs):
            if not calls:raise AssertionError('request must arrive first')
            if len(calls)==1 and '.recovery' not in str(args[0]):raise OSError('disk failure')
            return original(*args,**kwargs)
        with patch.object(worker,'save_task_raw',side_effect=flaky):
            self.execute(b,target,lambda c,cfg,p:(calls.append(p),self.payload())[1])
        state=lib.read(file);self.assertEqual(state['status'],'completed');self.assertEqual(len(calls),7)
        self.assertEqual(state['auto_recovery']['requests_used'],0)
        self.assertTrue(state['results'][rows[0]['units'][0]['id']]['recovered_locally'])

    def test_unknown_request_is_not_paid_again(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];state=lib.read(file)
        state.update(attempts={bad['id']:1},requests_used=1,results={bad['id']:{'status':'request_reserved','request_number':1,'attempt':1}})
        lic=lib.read(file.parent/'license.json');lic.update(attempts=state['attempts'],requests_used=1)
        lib.write(file.parent/'license.json',lic);lib.write(file,state);calls=[]
        self.execute(b,target,lambda c,cfg,p:(calls.append(p),self.payload())[1])
        state=lib.read(file);self.assertEqual(state['status'],'completed_with_errors');self.assertNotIn(bad['prompt'],calls)
        self.assertEqual(len(calls),6);self.assertEqual(state['auto_recovery']['requests_used'],0)

    def test_parent_pause_is_seen_by_child_and_resume_reuses_envelope(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=collections.Counter()
        def generate(c,cfg,p):
            calls[p]+=1
            if p==bad['prompt'] and calls[p]<=2:raise TimeoutError('timed out')
            if p==bad['prompt'] and calls[p]==3:lib.write(file.parent/'pause.json',{'requested_at':lib.now()});raise TimeoutError('timed out')
            return self.payload()
        self.execute(b,target,generate);state=lib.read(file);self.assertEqual(state['status'],'paused')
        self.assertFalse(state['auto_recovery']['finished']);self.assertEqual(calls[bad['prompt']],3)
        with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.resume(target)
        self.execute(b,target,generate);state=lib.read(file);self.assertEqual(state['status'],'completed')
        self.assertEqual(calls[bad['prompt']],4);self.assertEqual(len(state['auto_recovery']['children']),1)

    def test_policy_bound_and_public_child_cannot_expand(self):
        b,req,target,file,rows=self.create_task();state=lib.read(file)
        self.assertEqual(state['max_requests']+state['auto_complete']['max_requests'],42)
        for value in ({'rounds':3},{'rounds':True},{'max_requests':500},'yes'):
            with self.assertRaises(ValueError):auto.policy(value,['u'])
        child,tid=auto.child_ids(state,1,1,1)
        from tools import task_actions
        with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
            saved=task_actions.prepare_repair({'group':1,'position':1},b,lib.read(lib.batch_dir(b['category'],b['id'])/'snapshot.json'),[rows[0]['units'][0]],lib.batch_dir(b['category'],child),child)
        with self.ready(),self.assertRaisesRegex(ValueError,'递归'):
            lib.plan({'category':b['category'],'batch':child,'groups':[1],'auto_complete':True})

    def test_unit_pause_does_not_spend_repair_rounds_or_stop_other_repairs(self):
        b,req,target,file,rows=self.create_task();paused=rows[0]['units'][0];bad=rows[0]['units'][4];calls=collections.Counter()
        lib.pause({**target,'unit_ids':[paused['id']]})
        def generate(c,cfg,p):
            calls[p]+=1
            if p==bad['prompt'] and calls[p]<=2:raise TimeoutError('timed out')
            return self.payload()
        self.execute(b,target,generate);state=lib.read(file)
        self.assertEqual(state['status'],'paused');self.assertFalse(state['auto_recovery']['finished'])
        self.assertEqual(calls[paused['prompt']],0);self.assertEqual(calls[bad['prompt']],3)
        self.assertTrue(all(e['position']!=paused['delivery_position'] for e in state['auto_recovery']['children'].values()))
        with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.resume({**target,'unit_ids':[paused['id']]})
        self.execute(b,target,generate);state=lib.read(file)
        self.assertEqual(state['status'],'completed');self.assertEqual(calls[paused['prompt']],1)

    def test_stable_rejection_does_not_repeat_unchanged_paid_prompt(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=collections.Counter()
        class Rejected(Exception):status_code=400
        def generate(c,cfg,p):
            calls[p]+=1
            if p==bad['prompt']:raise Rejected('unsafe provider text')
            return self.payload()
        self.execute(b,target,generate);state=lib.read(file)
        self.assertEqual(state['status'],'completed_with_errors');self.assertEqual(calls[bad['prompt']],1)
        self.assertEqual(state['auto_recovery']['requests_used'],0)
        self.assertEqual(state['requests_used'],7)

    def test_parent_unit_resume_during_child_final_render_is_not_lost(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=collections.Counter()
        closing=threading.Event();release=threading.Event();child_renders=[];errors=[]
        def generate(c,cfg,p):
            calls[p]+=1
            if p==bad['prompt'] and calls[p]<=3:
                if calls[p]==3:lib.pause({**target,'unit_ids':[bad['id']]})
                raise TimeoutError('timed out')
            return self.payload()
        def render(category,batch,data,*args):
            if data.get('automatic_repair_parent'):
                child_renders.append(1)
                if len(child_renders)==2:closing.set();self.assertTrue(release.wait(10))
            self.render(category,batch,data,*args)
        def run():
            try:
                with self.ready():worker.run(b['category'],b['id'],target['task'],generate=generate,clients=[(1,object())],render=render)
            except Exception as e:errors.append(e)
        thread=threading.Thread(target=run);thread.start()
        try:
            self.assertTrue(closing.wait(15))
            with self.ready(),patch.object(lib,'launch',side_effect=AssertionError('must retain live owner')):
                lib.resume({**target,'unit_ids':[bad['id']]})
        finally:release.set();thread.join(15)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(calls[bad['prompt']],4);self.assertEqual(lib.read(file)['status'],'completed')
        self.assertEqual(len(lib.read(file)['auto_recovery']['children']),1)

    def test_failed_local_get_consumes_one_attempt(self):
        from tools import image_download_receipts as receipts
        import image_generate
        b,req,target,file,rows=self.create_task();unit=rows[0]['units'][0]
        state=lib.read(file)
        state.update(status='paused',results={unit['id']:{'status':'failed','error':'image_download_failed','request_number':1,'attempt':1}},attempts={unit['id']:1},requests_used=1)
        lic=lib.read(file.parent/'license.json');lic.update(requests_used=1,attempts=state['attempts'])
        lib.write(file.parent/'license.json',lic);lib.write(file,state)
        state=lib.read(file)
        context=auto.download_context(lib.batch_dir(b['category'],b['id']),state,unit,state['results'][unit['id']])
        receipts.save_returned_url(context,'https://example.com/private-returned.png')
        with patch.object(image_generate,'download_image_url',side_effect=TimeoutError('timed out')) as download:
            auto.recover_returned(b['category'],b['id'],state,rows,file)
        done=lib.read(file)
        self.assertEqual(download.call_count,1)
        self.assertEqual(done['auto_recovery']['local_attempts'][unit['id']],1)
        self.assertEqual(done['requests_used'],1)
        self.assertNotEqual(done['results'][unit['id']].get('status'),'generated')
        self.assertNotIn('private-returned.png',file.read_text('utf-8'))

    def test_pending_download_evidence_keeps_continuation_open(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        import image_generate
        b=self.batch();req={'category':b['category'],'batch':b['id'],'groups':[1],'unit_ids':['g0001_u01'],'auto_complete':{'mode':'continuous','total_max_requests':20}}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(req);self.assertFalse(plan['blocks'])
            task=lib.start({**req,'request_id':'evidence-open','plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups'})
        file=lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json'
        image=SimpleNamespace(b64_json=None,url='https://example.com/private-returned.png')
        client=SimpleNamespace(images=SimpleNamespace(generate=Mock(return_value=SimpleNamespace(data=[image]))))
        config=lib.read(file)['config']
        with patch.object(lib,'api_config',return_value=config),patch.object(lib,'readiness',return_value=([], [1])),patch.object(image_generate,'download_image_url',side_effect=TimeoutError('timed out')):
            worker.run(b['category'],b['id'],task['id'],clients=[(1,client)],render=self.render)
        state=lib.read(file)
        self.assertEqual(client.images.generate.call_count,2)
        self.assertEqual(state['requests_used'],1)
        self.assertEqual(state['auto_recovery']['requests_used'],1)
        self.assertFalse(state['auto_recovery']['finished'])
        self.assertNotIn('private-returned.png',file.read_text('utf-8'))

    def _continuous(self,token,cap=20):
        b=self.batch();path=lib.batch_dir(b['category'],b['id']);units=lib.selected(path,b,[1])[0]['units']
        req={'category':b['category'],'batch':b['id'],'groups':[1],'auto_complete':{'mode':'continuous','total_max_requests':cap}}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(req);self.assertFalse(plan['blocks'])
            task=lib.start({**req,'request_id':token,'plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups'})
        return b,path,units,path/'tasks'/task['id']/'task.json',task

    def charge(self,file,units):
        state=lib.read(file);budget=lib.read(file.parent/'budget.json');entries=[]
        for number,unit in enumerate(units,1):
            entries.append({'batch':state['batch'],'task':state['id'],'license_sha256':state['license_sha256'],'unit':unit['id'],
                'origin':[state['batch'],1,unit['id']],'attempt':1,'number':number,'at':lib.now()})
        budget['reservations']=entries;budget['reservations_sha256']=lib.digest(entries);lib.write(file.parent/'budget.json',budget)

    def test_finished_batch_reposts_uncertain_without_refund(self):
        b,path,units,file,task=self._continuous('leftover-uncertain');bad=units[0]
        for unit in units:
            if unit is not bad:self.raw(b,1,unit)
        results={u['id']:{'status':'generated','request_number':1,'attempt':1} for u in units}
        results[bad['id']]={'status':'request_reserved','request_number':1,'attempt':1}
        self.seed(file,results,{u['id']:1 for u in units});self.charge(file,units)
        frozen=(path/'groups/0001.json').read_bytes();charged=lib.read(file)['requests_used'];calls=[]
        with self.ready():
            worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=self.render)
        state=lib.read(file)
        self.assertEqual(calls,[bad['prompt']])
        self.assertEqual(state['requests_used'],charged)
        self.assertEqual(state['attempts'][bad['id']],1)
        self.assertEqual(state['auto_recovery']['requests_used'],1)
        self.assertEqual(state['status'],'completed')
        self.assertEqual((path/'groups/0001.json').read_bytes(),frozen)
        self.assertTrue(worker.raw_valid(b['category'],b['id'],1,bad))

    def test_finished_batch_reassembles_rejected_prompt(self):
        b,path,units,file,task=self._continuous('leftover-rejected');bad=units[0]
        for unit in units:
            if unit is not bad:self.raw(b,1,unit)
        results={u['id']:{'status':'generated','request_number':1,'attempt':1} for u in units}
        results[bad['id']]={'status':'failed','error':'request_rejected','http_status':400,'rejection_kind':'content','request_number':1,'attempt':1}
        self.seed(file,results,{u['id']:1 for u in units});self.charge(file,units)
        frozen=(path/'groups/0001.json').read_bytes();charged=lib.read(file)['requests_used'];calls=[]
        with self.ready():
            worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=self.render)
        state=lib.read(file)
        self.assertEqual(len(calls),1)
        self.assertNotEqual(calls[0],bad['prompt'])
        self.assertEqual(state['requests_used'],charged)
        self.assertEqual(state['attempts'][bad['id']],1)
        self.assertEqual(state['status'],'completed')
        self.assertEqual((path/'groups/0001.json').read_bytes(),frozen)
        self.assertTrue(worker.raw_valid(b['category'],b['id'],1,bad))

    def test_leftover_stops_when_shared_cap_is_exhausted(self):
        b,path,units,file,task=self._continuous('leftover-capped',cap=7);self.assertEqual(len(units),7);bad=units[0]
        for unit in units:
            if unit is not bad:self.raw(b,1,unit)
        results={u['id']:{'status':'generated','request_number':1,'attempt':1} for u in units}
        results[bad['id']]={'status':'request_reserved','request_number':1,'attempt':1}
        self.seed(file,results,{u['id']:1 for u in units});self.charge(file,units)
        calls=[]
        with self.ready():
            worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=self.render)
        state=lib.read(file)
        self.assertEqual(calls,[])
        self.assertEqual(state['requests_used'],len(units))
        self.assertEqual(state['auto_recovery'].get('requests_used',0),0)
        self.assertEqual(state['auto_recovery']['phase'],'等待追加额度')

    def charge_attempts(self,file,units,attempts):
        state=lib.read(file);budget=lib.read(file.parent/'budget.json');entries=[];number=1
        for attempt in range(1,max(attempts.values())+1):
            for unit in units:
                if attempts[unit['id']]<attempt:continue
                entries.append({'batch':state['batch'],'task':state['id'],'license_sha256':state['license_sha256'],'unit':unit['id'],
                    'origin':[state['batch'],1,unit['id']],'attempt':attempt,'number':number,'at':lib.now()})
                number+=1
        budget['reservations']=entries;budget['reservations_sha256']=lib.digest(entries);lib.write(file.parent/'budget.json',budget)

    def test_rejection_reassembly_keeps_service_role(self):
        from tools import task_groups
        b,path,units,file,task=self._continuous('leftover-role');bad=next(u for u in units if u.get('service_role'))
        for unit in units:
            if unit is not bad:self.raw(b,1,unit)
        results={u['id']:{'status':'generated','request_number':1,'attempt':1} for u in units}
        results[bad['id']]={'status':'failed','error':'request_rejected','http_status':400,'rejection_kind':'content','request_number':1,'attempt':1}
        self.seed(file,results,{u['id']:1 for u in units});self.charge(file,units)
        real=task_groups.build_group
        def wrapped(category,seed,phone,catalog,config):
            rows=real(category,seed,phone,catalog,config)
            for row in rows:row['prompt']=f"ROLE:{row.get('service_role')}:SEED:{seed}"
            for row in rows:
                if row.get('service_role')==bad['service_role'] and row['delivery_position']==bad['delivery_position']:
                    row['service_role']='其他服务';row['prompt']='ROLE:其他服务'
            for row in rows:
                if row['delivery_position']!=bad['delivery_position'] and row.get('kind')=='detail':
                    row['service_role']=bad['service_role'];row['prompt']=f"ROLE:{bad['service_role']}";break
            return rows
        calls=[]
        with self.ready(),patch.object(task_groups,'build_group',side_effect=wrapped):
            worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=self.render)
        state=lib.read(file)
        self.assertEqual(calls,[f"ROLE:{bad['service_role']}"])
        self.assertNotIn('ROLE:其他服务',calls)
        child=next(iter(state['auto_recovery']['children'].values()))
        fresh=lib.selected(lib.batch_dir(b['category'],child['batch']),lib.load_batch(b['category'],child['batch'])[1],[1])[0]['units']
        self.assertEqual(fresh[0]['service_role'],bad['service_role'])
        self.assertEqual(state['status'],'completed')

    def test_child_rejection_after_exhausted_parent_is_reassembled(self):
        b,path,units,file,task=self._continuous('leftover-child-reject');bad=units[0]
        for unit in units:
            if unit is not bad:self.raw(b,1,unit)
        attempts={u['id']:1 for u in units};attempts[bad['id']]=2
        results={u['id']:{'status':'generated','request_number':1,'attempt':1} for u in units}
        results[bad['id']]={'status':'failed','error':'transient','request_number':2,'attempt':2}
        self.seed(file,results,attempts);self.charge_attempts(file,units,attempts)
        class Rejected(Exception):status_code=400
        calls=[]
        def generate(c,cfg,p):
            calls.append(p)
            if p==bad['prompt']:raise Rejected('content policy')
            return self.payload()
        with self.ready():
            worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object())],render=self.render)
        state=lib.read(file)
        self.assertEqual(calls.count(bad['prompt']),1)
        self.assertEqual(len(calls),2)
        self.assertNotEqual(calls[1],bad['prompt'])
        self.assertEqual(state['attempts'][bad['id']],2)
        self.assertEqual(state['requests_used'],sum(attempts.values()))
        self.assertEqual(state['status'],'completed')

    def test_successful_rebuilt_panel_is_not_paid_again(self):
        from tools import task_groups
        b,path,units,file,task=self._continuous('leftover-reuse');panels=[u for u in units if u['delivery_position']==2]
        self.assertEqual(len(panels),3);kept,done,again=panels
        for unit in units:
            if unit not in (done,again):self.raw(b,1,unit)
        results={u['id']:{'status':'generated','request_number':1,'attempt':1} for u in units}
        for unit in (done,again):results[unit['id']]={'status':'failed','error':'request_rejected','http_status':400,'rejection_kind':'content','request_number':1,'attempt':1}
        self.seed(file,results,{u['id']:1 for u in units});self.charge(file,units)
        real=task_groups.build_group
        def wrapped(category,seed,phone,catalog,config):
            rows=real(category,seed,phone,catalog,config)
            for row in rows:row['prompt']=f"ROLE:{row.get('service_role')}:SEED:{seed}"
            return rows
        class Rejected(Exception):status_code=400
        calls=[];failed=True
        def generate(c,cfg,p):
            nonlocal failed
            calls.append(p)
            if failed and f"ROLE:{again['service_role']}:" in p:
                failed=False;raise Rejected('content policy')
            return self.payload()
        with self.ready(),patch.object(task_groups,'build_group',side_effect=wrapped):
            worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object())],render=self.render)
            first=list(calls)
            worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object())],render=self.render)
        success=[p for p in calls if f"ROLE:{done['service_role']}:" in p]
        self.assertEqual(len(success),1)
        self.assertEqual(success, [p for p in first if f"ROLE:{done['service_role']}:" in p])
        self.assertNotIn(f"ROLE:{kept['service_role']}:",''.join(calls))
        self.assertEqual(lib.read(file)['requests_used'],len(units))
        self.assertTrue(worker.raw_valid(b['category'],b['id'],1,done))

    def test_saved_result_sibling_does_not_stay_open(self):
        b,path,units,file,task=self._continuous('leftover-mixed');panels=[u for u in units if u['delivery_position']==2]
        kept,download,saved=panels
        for unit in units:
            if unit not in (download,saved):self.raw(b,1,unit)
        results={u['id']:{'status':'generated','request_number':1,'attempt':1} for u in units}
        results[download['id']]={'status':'failed','error':'image_download_failed','request_number':1,'attempt':1}
        results[saved['id']]={'status':'failed','error':'local_save_failed','request_number':1,'attempt':1}
        self.seed(file,results,{u['id']:1 for u in units});self.charge(file,units)
        calls=[]
        with self.ready():
            worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=self.render)
        state=lib.read(file)
        self.assertEqual(calls,[])
        self.assertNotEqual(state['auto_recovery']['phase'],'待继续补齐')
        self.assertTrue(state['auto_recovery']['finished'])
        self.assertEqual(state['auto_recovery'].get('requests_used',0),0)

    def test_reassembly_failure_does_not_stay_open(self):
        from tools import task_groups
        b,path,units,file,task=self._continuous('leftover-no-prompt');bad=units[0]
        for unit in units:
            if unit is not bad:self.raw(b,1,unit)
        results={u['id']:{'status':'generated','request_number':1,'attempt':1} for u in units}
        results[bad['id']]={'status':'failed','error':'request_rejected','http_status':400,'rejection_kind':'content','request_number':1,'attempt':1}
        self.seed(file,results,{u['id']:1 for u in units});self.charge(file,units)
        real=task_groups.build_group
        def wrapped(category,seed,phone,catalog,config):
            rows=real(category,seed,phone,catalog,config)
            for row in rows:
                if row['delivery_position']==bad['delivery_position']:row['prompt']=bad['prompt'];row['service_role']=bad.get('service_role')
            return rows
        calls=[]
        with self.ready(),patch.object(task_groups,'build_group',side_effect=wrapped):
            worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,p:(calls.append(p),self.payload())[1],clients=[(1,object())],render=self.render)
        state=lib.read(file)
        self.assertEqual(calls,[])
        self.assertNotEqual(state['auto_recovery']['phase'],'待继续补齐')
        self.assertTrue(state['auto_recovery']['finished'])
        self.assertEqual(state['requests_used'],len(units))


if __name__=='__main__':unittest.main()
