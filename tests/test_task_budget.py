"""Shared request cap and continued completion, entirely isolated/offline."""
import unittest
from unittest.mock import patch
from tests.test_task_robustness import TaskRobustness
from tools import task_library as lib,task_worker as worker,task_budget as budget,task_queue as queue


class ContinuousBudget(unittest.TestCase):
    setUp=TaskRobustness.setUp
    batch=TaskRobustness.batch
    ready=TaskRobustness.ready
    payload=TaskRobustness.payload
    render=TaskRobustness.render

    def prepare(self,cap,single=True):
        b=self.batch();req={'category':b['category'],'batch':b['id'],'groups':[1],
                            'auto_complete':{'mode':'continuous','total_max_requests':cap}}
        if single:req['unit_ids']=['g0001_u01']
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(req)
            self.assertFalse(plan['blocks'])
            task=lib.start({**req,'request_id':'continuous','plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups'})
        file=lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json'
        return b,req,task,file

    def execute(self,b,task,generate):
        with self.ready():return worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object()),(2,object()),(3,object())],render=self.render)

    def test_seventh_request_completes_without_fixed_rounds(self):
        b,req,task,file=self.prepare(7);calls=[]
        def generate(*args):
            calls.append(args[-1])
            if len(calls)<7:raise TimeoutError('timed out')
            return self.payload()
        self.execute(b,task,generate)
        state=lib.read(file)
        self.assertEqual((len(calls),state['status'],state['completed_units']),(7,'completed',1))
        self.assertEqual(budget.progress(state),{'used':7,'maximum':7,'remaining':0})
        children=state['auto_recovery']['children']
        self.assertEqual(len(children),3)
        licences=[lib.read(lib.batch_dir(b['category'],e['batch'])/'tasks'/tid/'license.json') for tid,e in children.items()]
        self.assertEqual([l['terms']['max_requests'] for l in licences],[2,2,1])
        self.assertTrue(all(max(l['attempts'].values())<=2 for l in licences))
        self.assertEqual(lib.read(file.parent/'license.json')['requests_used'],2)

    def test_odd_total_exhaustion_keeps_card_missing_and_does_not_reset(self):
        b,req,task,file=self.prepare(5);calls=[]
        def generate(*args):calls.append(args[-1]);raise TimeoutError('timed out')
        self.execute(b,task,generate);state=lib.read(file)
        self.assertEqual((len(calls),budget.progress(state)['used']),(5,5))
        self.assertEqual(state['auto_recovery']['phase'],'等待追加额度')
        card=queue.view(req)['cards'][0]
        self.assertEqual((card['column'],card['attempts']),('ongoing',5))
        with self.assertRaises(ValueError):lib.resume({**req,'task':task['id']})
        self.execute(b,task,generate)
        self.assertEqual(len(calls),5)

    @unittest.skipUnless(__import__('os').name=='nt','Windows task file paths')
    def test_long_child_task_paths_keep_events_controls_and_public_paths(self):
        import os
        from tools import task_controls as controls,runtime_paths
        from pathlib import Path
        root=self.root/('long-task-'+('x'*max(1,185-len(str(self.root.absolute()))-11)))
        lib.io_path(root).mkdir(parents=True,exist_ok=True)
        with patch.object(lib,'ROOT',root),patch.dict(os.environ,{'FACTORY_DATA_HOME':str(root)}):
            runtime_paths.installed_rules.cache_clear()
            try:
                b,req,task,file=self.prepare(7);calls=[]
                assembly={'category':b['category'],'count':1,'phone':b['phone'],'seed':1401,'request_id':'long-idempotent-'+'x'*32}
                duplicate=lib.assemble(assembly)
                self.assertEqual(lib.assemble(assembly)['id'],duplicate['id'])
                self.assertEqual({batch['id'] for batch in lib.batches(b['category'])},{b['id'],duplicate['id']})
                with self.assertRaisesRegex(ValueError,'同一请求标识'):
                    lib.assemble({**assembly,'count':2})
                before=lib.io_path(file.parent/'license.json').read_bytes()
                lib.write(file.parent/'pause.json',{'created_at':lib.now()})
                with self.ready(),patch.object(lib,'launch',return_value=99999999):
                    lib.resume({**req,'task':task['id']})
                self.assertFalse(lib.io_path(file.parent/'pause.json').exists())
                self.assertEqual(lib.io_path(file.parent/'license.json').read_bytes(),before)
                def generate(*args):
                    calls.append(args[-1])
                    if len(calls)<7:raise TimeoutError('timed out')
                    return self.payload()
                with self.ready():worker.run(b['category'],b['id'],task['id'],generate=generate,clients=[(1,object())])
                state=lib.read(file)
                self.assertEqual((len(calls),state['status']),(7,'completed'))
                tid,entry=list(state['auto_recovery']['children'].items())[-1]
                childfile=lib.batch_dir(b['category'],entry['batch'])/'tasks'/tid/'task.json'
                self.assertGreater(len(str(childfile)),300)
                child=lib.read(childfile)
                self.assertEqual(len(lib.jobs(childfile.parent.parent.parent)),1)
                events=lib.io_path(childfile.parent/'events.jsonl').read_text(encoding='utf-8')
                self.assertTrue(events.strip())
                from tools.task_queue_details import events as read_events
                parsed,note=read_events(child)
                self.assertTrue(parsed.get('g0001_u01'));self.assertIsNone(note)
                controls.change(child,['g0001_u01'],True)
                self.assertIn('g0001_u01',controls.direct(child))
                controls.change(child,['g0001_u01'],False)
                self.assertFalse(controls.direct(child));self.assertTrue(controls.resume_epoch(child))
                self.assertEqual(budget.progress(state)['used'],7)
                board=queue.view(req)
                self.assertEqual((board['total'],board['counts']['completed']), (7,1))
                self.assertEqual(board['cards'][0]['attempts'],7)
                from tools import raw_library as stock
                inventory=stock.view({'category':b['category']})
                self.assertEqual((inventory['counts']['total'],inventory['counts']['invalid']),(1,0))
                registered=inventory['entries'][0]
                self.assertEqual(stock.load(b['category'],registered['id'])['id'],registered['id'])
                childrow=lib.selected(lib.batch_dir(b['category'],entry['batch']),lib.load_batch(b['category'],entry['batch'])[1],[1])[0]
                self.assertEqual(stock.register(b['category'],entry['batch'],1,childrow['units'][0])['id'],registered['id'])
                from tools import task_actions as actions
                with patch.object(lib,'alive',return_value=True):
                    active={**child,'status':'running','pid':os.getpid()}
                    lib.write(childfile,active)
                    with self.assertRaisesRegex(ValueError,'有关联任务正在运行'):
                        actions.ensure_idle(b['category'])
                    lib.write(childfile,child)
                frozen=[lib.batch_dir(b['category'],entry['batch'])/name for name in ('batch.json','snapshot.json','groups/0001.json')]
                original=[lib.io_path(p).read_bytes() for p in frozen]
                def forbidden(*args):raise AssertionError('completed replay cannot issue a POST')
                with self.ready():worker.run(b['category'],b['id'],task['id'],generate=forbidden,clients=[])
                self.assertEqual([lib.io_path(p).read_bytes() for p in frozen],original)
                for delivery in lib.view(req)['groups'][0]['images']:
                    self.assertFalse(delivery['path'].startswith('\\\\?\\'))
            finally:runtime_paths.installed_rules.cache_clear()

    def test_orphan_reservation_becomes_unknown_without_new_post(self):
        b,req,task,file=self.prepare(7)
        self.assertTrue(budget.reserve(task,'g0001_u01',1,1))
        self.assertEqual(lib.read(file.parent/'license.json')['requests_used'],0)
        state=lib.read(file);licence=lib.synchronize_license(file,state)
        self.assertEqual((licence['requests_used'],state['results']['g0001_u01']['status']),(1,'request_reserved'))
        lib.write(file,state)
        def generate(*args):raise AssertionError('unknown reservation must never POST')
        self.execute(b,state,generate)
        self.assertEqual(budget.progress(lib.read(file))['used'],1)
        self.assertFalse(lib.read(file)['auto_recovery']['children'])
        with self.assertRaisesRegex(ValueError,'已预留'):budget.reserve(state,'g0001_u01',1,1)

    def test_jobs_projection_restores_orphan_without_mutating_readonly_licence(self):
        b,req,task,file=self.prepare(7)
        before=(file.parent/'license.json').read_bytes()
        budget.reserve(task,'g0001_u01',1,1)
        projected=lib.jobs(file.parent.parent.parent)[0]
        self.assertEqual(projected['requests_used'],1)
        licence=lib.synchronize_license(file,projected)
        self.assertEqual(licence['requests_used'],1)
        self.assertEqual((file.parent/'license.json').read_bytes(),before)
        self.assertEqual(queue.view(req)['request_counts']['used'],1)
        self.assertEqual((file.parent/'license.json').read_bytes(),before)

    def test_queue_budget_and_attempts_share_one_query_snapshot(self):
        b,req,task,file=self.prepare(7);original=budget.load;calls=[];changed=[]
        def load(state,**kwargs):
            calls.append(state['id'])
            if len(calls)==3:
                changed.append(True)
                budget.reserve(task,'g0001_u01',1,1)
            return original(state,**kwargs)
        with patch.object(budget,'load',side_effect=load):first=queue.view(req)
        self.assertTrue(changed)
        self.assertEqual(first['request_counts']['used'],sum(c['attempts'] for c in first['cards']))
        second=queue.view(req)
        self.assertEqual(second['request_counts']['used'],1)
        self.assertEqual(sum(c['attempts'] for c in second['cards']),1)

    def test_resume_skips_exhausted_history_and_finishes_next_attempt(self):
        b,req,task,file=self.prepare(9);calls=[]
        def generate(*args):
            calls.append(args[-1])
            if len(calls)==5:lib.pause({**req,'task':task['id']})
            if len(calls)<=5:raise TimeoutError('timed out')
            return self.payload()
        self.execute(b,task,generate)
        paused=lib.read(file)
        self.assertEqual((paused['status'],budget.progress(paused)['used']),('paused',5))
        with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.resume({**req,'task':task['id']})
        self.execute(b,task,generate)
        finished=lib.read(file)
        self.assertEqual((finished['status'],len(calls),budget.progress(finished)['used']),('completed',6,6))

    def test_concurrent_dispatch_never_exceeds_shared_cap(self):
        b,req,task,file=self.prepare(8,single=False);calls=[]
        def generate(*args):calls.append(args[-1]);raise TimeoutError('timed out')
        self.execute(b,task,generate)
        self.assertEqual(len(calls),8)
        state=lib.read(file)
        self.assertEqual(budget.progress(state),{'used':8,'maximum':8,'remaining':0})
        self.assertEqual(state['requests_used'],8)

    def test_resume_after_exhausting_latest_child_uses_remaining_pool(self):
        b,req,task,file=self.prepare(9);calls=[]
        def generate(*args):
            calls.append(args[-1])
            if len(calls)==6:lib.pause({**req,'task':task['id']})
            if len(calls)<=6:raise TimeoutError('timed out')
            return self.payload()
        self.execute(b,task,generate)
        self.assertEqual((lib.read(file)['status'],len(calls)),('paused',6))
        with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.resume({**req,'task':task['id']})
        self.execute(b,task,generate)
        self.assertEqual((lib.read(file)['status'],len(calls),budget.progress(lib.read(file))['remaining']),('completed',7,2))

    def test_query_rebuilds_entire_snapshot_when_child_advances_after_parent_read(self):
        b,req,task,file=self.prepare(9);calls=[]
        def generate(*args):
            calls.append(args[-1])
            if len(calls)==5:lib.pause({**req,'task':task['id']})
            raise TimeoutError('timed out')
        self.execute(b,task,generate)
        parent=lib.read(file);entry=list(parent['auto_recovery']['children'].items())[-1]
        tid,binding=entry;childfile=lib.batch_dir(b['category'],binding['batch'])/'tasks'/tid/'task.json'
        child=lib.read(childfile);licence=lib.read(childfile.parent/'license.json');uid=child['pending_unit_ids'][0]
        original=budget.licence_snapshot;changed=[]
        def snapshot(path,memo=None):
            if path==childfile.parent/'license.json' and not changed:
                changed.append(True)
                self.assertTrue(budget.reserve(child,uid,child['requests_used']+1,child['attempts'][uid]+1))
                child['requests_used']+=1;child['attempts'][uid]+=1
                licence['requests_used']=child['requests_used'];licence['attempts']=dict(child['attempts'])
                lib.write(childfile.parent/'license.json',licence);lib.write(childfile,child)
            return original(path,memo)
        with patch.object(budget,'licence_snapshot',side_effect=snapshot):result=queue.view(req)
        self.assertTrue(changed)
        self.assertEqual((result['request_counts']['used'],sum(c['attempts'] for c in result['cards'])),(6,6))

    def test_missing_budget_cannot_be_reinitialized_or_request(self):
        b,req,task,file=self.prepare(7)
        (file.parent/'budget.json').rename(file.parent/'missing-budget.evidence')
        with self.assertRaisesRegex(ValueError,'账本缺失'):lib.synchronize_license(file,lib.read(file))
        self.assertEqual(lib.read(file.parent/'license.json')['requests_used'],0)

    def test_plan_rejects_invalid_caps_and_does_not_raise_user_input(self):
        b=self.batch();req={'category':b['category'],'batch':b['id'],'groups':[1]}
        with self.ready():
            for cap in (True,6,-1,8.5,'10',100001):
                with self.assertRaises(ValueError):lib.plan({**req,'auto_complete':{'mode':'continuous','total_max_requests':cap}})
            plan=lib.plan({**req,'auto_complete':{'mode':'continuous','total_max_requests':7}})
            self.assertEqual((plan['max_requests'],plan['total_max_requests']),(7,7))

    def test_zero_cap_with_all_verified_raws_never_requests_api(self):
        b=self.batch();path=lib.batch_dir(b['category'],b['id'])
        for unit in lib.selected(path,b,[1])[0]['units']:TaskRobustness.raw(self,b,1,unit)
        req={'category':b['category'],'batch':b['id'],'groups':[1],'auto_complete':{'mode':'continuous','total_max_requests':0}}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(req);self.assertEqual((plan['pending_count'],plan['total_max_requests']),(0,0))
            task=lib.start({**req,'request_id':'free','plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups'})
        def forbidden(*args):raise AssertionError('zero cap cannot POST')
        self.execute(b,task,forbidden)
        state=lib.read(path/'tasks'/task['id']/'task.json')
        self.assertEqual((state['status'],budget.progress(state)['used']),('completed',0))
        self.assertEqual(queue.view(req)['request_counts'],{'used':0,'maximum':0})
