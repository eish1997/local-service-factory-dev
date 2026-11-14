"""Continuation after one unsafe failure, with simulated responses only."""
import io
import unittest
from unittest.mock import patch
from PIL import Image
from tools import task_library as lib,task_worker as worker,task_recovery as recovery
from tests import test_shared_tasks as shared


class TaskContinuation(unittest.TestCase):
    setUp=shared.SharedTasks.setUp
    batch=shared.SharedTasks.batch
    request=shared.SharedTasks.request
    ready=shared.SharedTasks.ready

    def create_task(self,count=1):
        b=self.batch(count=count);req=self.request(b,list(range(1,count+1)))
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req)
            task=lib.start({**req,'request_id':'continuation','authorization':'execute_selected_groups','plan_sha256':p['plan_sha256']})
        target={'category':b['category'],'batch':b['id'],'task':task['id']}
        path=lib.batch_dir(b['category'],b['id']);file=path/'tasks'/task['id']/'task.json'
        return b,req,target,file,lib.selected(path,b,req['groups'])

    def payload(self):
        out=io.BytesIO();Image.new('RGB',(1024,1536),'gray').save(out,format='PNG');return out.getvalue()

    def seed(self,file,results,attempts):
        state=lib.read(file);state.update(status='paused',results=results,attempts=attempts,requests_used=sum(attempts.values()))
        lic=lib.read(file.parent/'license.json');lic.update(requests_used=state['requests_used'],attempts=attempts)
        lib.write(file.parent/'license.json',lic);lib.write(file,state)
        return lic

    def execute(self,b,target,generate):
        return worker.run(b['category'],b['id'],target['task'],generate=generate,clients=[(1,object())],render=lambda *a:None)

    def test_one_non_retryable_does_not_block_remaining_or_new_batch(self):
        b,req,target,file,rows=self.create_task()
        captured=[]
        class Blocked(Exception):status_code=451
        def generate(c,cfg,p):
            if p==rows[0]['units'][0]['prompt']:raise Blocked('provider response must never be persisted')
            captured.append(p);return self.payload()
        self.execute(b,target,generate)
        done=lib.read(file)
        bad=rows[0]['units'][0]['id']
        self.assertEqual(done['status'],'completed_with_errors')
        self.assertEqual(done['skipped_units'],1)
        self.assertEqual(done['resume_summary']['reasons'],{'non_retryable':1})
        self.assertEqual(done['completed_units'],6);self.assertEqual(done['requests_used'],7)
        self.assertEqual(done['attempts'][bad],1);self.assertEqual(done['max_requests'],14)
        self.assertNotIn(rows[0]['units'][0]['prompt'],captured)
        self.assertEqual(done['resume_summary']['ready_count'],0)
        self.assertNotIn('provider response',file.read_text('utf-8'))
        with self.ready(),patch.object(lib,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'错误不适合自动重试 1 张'):lib.resume(target)
            launch.assert_not_called()
            self.assertTrue(lib.plan(req)['blocks'])
            new=self.batch();self.assertEqual(lib.plan(self.request(new,[1]))['blocks'],[])

    def test_transient_automatically_retried_once_without_changing_prompt(self):
        b,req,target,file,rows=self.create_task();calls={};payload=self.payload()
        def generate(c,cfg,p):
            calls[p]=calls.get(p,0)+1
            if calls[p]==1:raise TimeoutError('timed out')
            return payload
        self.assertEqual(self.execute(b,target,generate),0)
        state=lib.read(file)
        self.assertEqual(state['status'],'completed');self.assertEqual(state['requests_used'],14)
        self.assertEqual(state['completed_units'],7);self.assertEqual(set(calls.values()),{2})
        self.assertEqual(set(calls),{u['prompt'] for u in rows[0]['units']})
        self.assertEqual(lib.read(file.parent/'license.json')['attempts'],state['attempts'])

    def test_repeated_transient_skips_and_finishes_other_units(self):
        b,req,target,file,rows=self.create_task();bad={u['prompt'] for u in rows[0]['units'][:3]};calls={}
        def generate(c,cfg,p):
            calls[p]=calls.get(p,0)+1
            if p in bad:raise TimeoutError('timed out')
            return self.payload()
        self.assertEqual(self.execute(b,target,generate),0)
        state=lib.read(file)
        self.assertEqual(state['status'],'completed_with_errors');self.assertEqual(state['completed_units'],4)
        self.assertEqual(state['requests_used'],10);self.assertEqual(state['skipped_units'],3)
        self.assertEqual(state['resume_summary']['reasons'],{'attempts':3})
        self.assertTrue(all(n==2 if p in bad else n==1 for p,n in calls.items()))

    def test_all_transient_failures_stop_at_frozen_cap_without_pause(self):
        b,req,target,file,rows=self.create_task()
        def fail(*a):raise TimeoutError('timed out')
        self.assertEqual(self.execute(b,target,fail),0)
        state=lib.read(file)
        self.assertEqual(state['status'],'completed_with_errors');self.assertEqual(state['requests_used'],14)
        self.assertEqual(state['skipped_units'],7);self.assertEqual(set(state['attempts'].values()),{2})

    def test_returned_download_failure_skipped_without_second_generation(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=[]
        def generate(c,cfg,p):
            calls.append(p)
            if p==bad['prompt']:raise ValueError('returned image download')
            return self.payload()
        original=worker.images.classify_request_error
        with patch.object(worker.images,'classify_request_error',side_effect=lambda e:'image_download_failed' if isinstance(e,ValueError) else original(e)):
            self.execute(b,target,generate)
        state=lib.read(file)
        self.assertEqual(state['status'],'completed_with_errors');self.assertEqual(state['requests_used'],7)
        self.assertEqual(calls.count(bad['prompt']),1);self.assertEqual(state['resume_summary']['reasons'],{'download':1})

    def test_balance_failover_and_all_slots_unavailable_are_bounded(self):
        b,req,target,file,rows=self.create_task();first=object();second=object();calls=[]
        def generate(c,cfg,p):
            calls.append(c)
            if c is first:raise ValueError('balance')
            return self.payload()
        with patch.object(worker.images,'classify_request_error',return_value='balance_exhausted'):
            worker.run(b['category'],b['id'],target['task'],generate=generate,clients=[(1,first),(2,second)],render=lambda *a:None)
        state=lib.read(file);self.assertEqual(state['status'],'completed');self.assertEqual(state['requests_used'],8)
        self.assertEqual(calls.count(first),1);self.assertEqual(state['quarantined_slots'],[1])
        b,req,target,file,rows=self.create_task()
        with patch.object(worker.images,'classify_request_error',return_value='balance_exhausted'):
            self.execute(b,target,lambda *a:(_ for _ in ()).throw(ValueError('balance')))
        state=lib.read(file);self.assertEqual(state['status'],'paused');self.assertEqual(state['requests_used'],1)
        self.assertEqual(state['resume_summary']['ready_count'],7);self.assertIn('所有可用密钥槽位',state['error'])

    def test_crash_reserved_request_is_skipped_and_license_kept(self):
        b,req,target,file,rows=self.create_task();uid=rows[0]['units'][0]['id']
        lic=lib.read(file.parent/'license.json');lic.update(requests_used=1,attempts={uid:1});lib.write(file.parent/'license.json',lic)
        with self.ready(),patch.object(lib,'launch',return_value=99999999):saved=lib.resume(target)
        self.assertEqual(saved['resume_summary']['reasons'],{'uncertain':1})
        self.assertEqual(lib.read(file.parent/'license.json'),lic)
        prompts=[];self.execute(b,target,lambda c,cfg,p:(prompts.append(p),self.payload())[1])
        self.assertNotIn(rows[0]['units'][0]['prompt'],prompts)
        done=lib.read(file);self.assertEqual(done['attempts'][uid],1);self.assertEqual(done['requests_used'],7)
        self.assertEqual(done['results'][uid]['status'],'request_reserved')

    def test_download_exhausted_and_unknown_are_never_dispatched(self):
        b,req,target,file,rows=self.create_task();units=rows[0]['units']
        results={units[0]['id']:{'status':'failed','error':'image_download_failed','receipt_id':'a'*64},
                 units[1]['id']:{'status':'failed','error':'transient'},
                 units[2]['id']:{'status':'failed','error':'APIStatusError','http_status':401}}
        attempts={units[0]['id']:1,units[1]['id']:2,units[2]['id']:1}
        self.seed(file,results,attempts)
        with self.ready(),patch.object(lib,'launch',return_value=99999999):saved=lib.resume(target)
        self.assertEqual(saved['resume_summary']['reasons'],{'download':1,'attempts':1,'non_retryable':1})
        self.assertEqual(saved['resume_summary']['blocked'][2]['http_status'],401)
        captured=[];self.execute(b,target,lambda c,cfg,p:(captured.append(p),self.payload())[1])
        done=lib.read(file);self.assertEqual(done['requests_used'],8)
        for u in units[:3]:self.assertNotIn(u['prompt'],captured);self.assertEqual(done['attempts'][u['id']],attempts[u['id']])
        self.assertEqual(done['results'][units[0]['id']]['receipt_id'],'a'*64)

    def test_retry_only_safe_failure_not_unstarted_or_unsafe(self):
        b,req,target,file,rows=self.create_task();units=rows[0]['units']
        self.seed(file,{units[0]['id']:{'status':'failed','error':'transient'},units[1]['id']:{'status':'failed','error':'APIStatusError'}},{units[0]['id']:1,units[1]['id']:1})
        with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.dispatch('retry',target)
        captured=[];self.execute(b,target,lambda c,cfg,p:(captured.append(p),self.payload())[1])
        self.assertTrue(captured==[units[0]['prompt']]);self.assertEqual(lib.read(file)['requests_used'],3)
        with self.ready(),patch.object(lib,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'没有可在原预算内重试'):lib.dispatch('retry',target)
            launch.assert_not_called()
        with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.resume(target)
        self.execute(b,target,lambda *a:self.payload())
        done=lib.read(file);self.assertEqual(done['requests_used'],8);self.assertEqual(done['attempts'][units[1]['id']],1)

    def test_budget_exhaustion_blocks_without_new_license_or_request(self):
        b,req,target,file,rows=self.create_task();attempts={u['id']:2 for u in rows[0]['units']}
        self.seed(file,{u['id']:{'status':'failed','error':'transient'} for u in rows[0]['units']},attempts)
        lic=(file.parent/'license.json').read_bytes()
        with self.ready(),patch.object(lib,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'单图两次请求已用尽 7 张'):lib.resume(target)
            launch.assert_not_called()
        self.assertEqual((file.parent/'license.json').read_bytes(),lic)
        captured=[];self.execute(b,target,lambda *a:captured.append(a))
        self.assertEqual(captured,[]);self.assertEqual(lib.read(file)['requests_used'],14)

    def test_valid_saved_image_reused_even_if_last_status_unknown(self):
        b,req,target,file,rows=self.create_task();unit=rows[0]['units'][0]
        raw=lib.unit_raw(b['category'],b['id'],1,unit);raw.parent.mkdir(parents=True);raw.write_bytes(self.payload())
        lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':worker.hashlib.sha256(raw.read_bytes()).hexdigest()})
        before=raw.read_bytes();self.seed(file,{unit['id']:{'status':'request_reserved'}},{unit['id']:1})
        with self.ready(),patch.object(lib,'launch',return_value=99999999):saved=lib.resume(target)
        self.assertEqual(saved['resume_summary']['reused_count'],1);self.assertEqual(saved['resume_summary']['blocked_count'],0)
        self.execute(b,target,lambda *a:self.payload())
        self.assertEqual(raw.read_bytes(),before);self.assertEqual(lib.read(file)['status'],'completed')
        self.assertEqual(lib.read(file)['requests_used'],7)

    def test_all_saved_at_request_cap_only_resumes_local_render(self):
        b,req,target,file,rows=self.create_task();units=rows[0]['units']
        payload=self.payload()
        for unit in units:
            raw=lib.unit_raw(b['category'],b['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True);raw.write_bytes(payload)
            lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':worker.hashlib.sha256(payload).hexdigest()})
        self.seed(file,{u['id']:{'status':'generated'} for u in units},{u['id']:2 for u in units})
        lic=(file.parent/'license.json').read_bytes()
        with self.ready(),patch.object(lib,'launch',return_value=99999999):saved=lib.resume(target)
        self.assertEqual(saved['resume_summary']['reused_count'],7)
        with self.ready(),patch.object(worker.images,'openai_clients_by_slot') as clients:
            rendered=[]
            result=worker.run(b['category'],b['id'],target['task'],render=lambda *a:rendered.append(1))
            clients.assert_not_called()
        self.assertEqual(result,0);self.assertEqual(rendered,[1])
        self.assertEqual((file.parent/'license.json').read_bytes(),lic)
        self.assertEqual(lib.read(file)['requests_used'],14)

    def test_new_http_failure_keeps_only_safe_status_diagnostic(self):
        b,req,target,file,rows=self.create_task()
        class Unauthorized(Exception):status_code=451
        def fail(*a):raise Unauthorized('secret key or signed URL must not enter records')
        self.execute(b,target,fail)
        state=lib.read(file);uid=rows[0]['units'][0]['id']
        self.assertEqual(state['status'],'completed_with_errors');self.assertEqual(state['requests_used'],7)
        self.assertEqual(set(state['attempts'].values()),{1})
        self.assertEqual(state['results'][uid]['http_status'],451)
        self.assertEqual(state['resume_summary']['blocked'][0]['http_status'],451)
        self.assertNotIn('secret key',file.read_text('utf-8'))
        self.assertNotIn('signed URL',(file.parent/'events.jsonl').read_text('utf-8'))

    def test_resume_clears_stale_local_execution_error(self):
        b=self.batch();req={'category':b['category'],'batch':b['id'],'groups':[1],'auto_complete':{'mode':'continuous','total_max_requests':20}}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(req);self.assertFalse(plan['blocks'])
            task=lib.start({**req,'request_id':'resume-clear','plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups'})
        file=lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json'
        state=lib.read(file);state.update(status='failed',pid=None,error='ValueError：本地执行失败，请让 Agent 检查');lib.write(file,state)
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            saved=lib.resume({'category':b['category'],'batch':b['id'],'task':task['id']})
        self.assertEqual(saved['status'],'queued')
        self.assertFalse(saved.get('error'))
        self.assertEqual(saved['auto_recovery']['phase'],'待继续补齐')
        self.assertNotIn('本地执行失败',lib.read(file).get('error') or '')

    def test_preflight_failure_is_not_a_returned_download(self):
        import base64
        from types import SimpleNamespace
        from unittest.mock import Mock
        import image_generate
        b=self.batch();req={**self.request(b,[1]),'unit_ids':['g0001_u01']}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(req);self.assertFalse(plan['blocks'])
            task=lib.start({**req,'request_id':'preflight','plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups'})
        file=lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json'
        failed={'done':False}
        def preflight(ctx):
            if not failed['done']:
                failed['done']=True
                raise image_generate.ReturnedImageDownloadError()
        image=SimpleNamespace(b64_json=base64.b64encode(self.payload()).decode(),url=None)
        client=SimpleNamespace(images=SimpleNamespace(generate=Mock(return_value=SimpleNamespace(data=[image]))))
        config=lib.read(file)['config']
        with patch.object(lib,'api_config',return_value=config),patch.object(lib,'readiness',return_value=([], [1])),patch.object(image_generate.image_download_receipts,'preflight_context',side_effect=preflight):
            worker.run(b['category'],b['id'],task['id'],clients=[(1,client)],render=lambda *a:None)
        state=lib.read(file);result=state['results']['g0001_u01']
        self.assertNotEqual(result.get('error'),'image_download_failed')
        self.assertEqual(client.images.generate.call_count,1)
        self.assertEqual(state['attempts']['g0001_u01'],2)
        self.assertEqual(state['requests_used'],2)
        self.assertEqual(result['status'],'generated')

    def test_pending_url_is_fetched_once_in_the_same_run(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        import image_generate
        b=self.batch();req={**self.request(b,[1]),'unit_ids':['g0001_u01']}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(req);self.assertFalse(plan['blocks'])
            task=lib.start({**req,'request_id':'pending-url','plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups'})
        file=lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json'
        image=SimpleNamespace(b64_json=None,url='https://example.com/private-returned.png')
        client=SimpleNamespace(images=SimpleNamespace(generate=Mock(return_value=SimpleNamespace(data=[image]))))
        downloads={'n':0}
        def download(url,*args,**kwargs):
            downloads['n']+=1
            if downloads['n']==1:raise TimeoutError('download failed')
            return self.payload()
        config=lib.read(file)['config']
        unit=lib.selected(lib.batch_dir(b['category'],b['id']),lib.load_batch(b['category'],b['id'])[1],[1])[0]['units'][0]
        with patch.object(lib,'api_config',return_value=config),patch.object(lib,'readiness',return_value=([], [1])),patch.object(image_generate,'download_image_url',side_effect=download):
            worker.run(b['category'],b['id'],task['id'],clients=[(1,client)],render=lambda *a:None)
        state=lib.read(file);result=state['results']['g0001_u01']
        self.assertEqual(unit['id'],'g0001_u01')
        self.assertEqual(client.images.generate.call_count,1)
        self.assertEqual(state['requests_used'],1)
        self.assertEqual(state['attempts']['g0001_u01'],1)
        self.assertEqual(downloads['n'],2)
        self.assertTrue(worker.raw_valid(b['category'],b['id'],1,unit))
        self.assertEqual(result['status'],'generated')
        self.assertNotIn('private-returned.png',file.read_text('utf-8'))


if __name__=='__main__':unittest.main()
