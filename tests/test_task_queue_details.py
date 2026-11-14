"""Card diagnostics use frozen ledgers, bounded events and canonical identities."""
import collections
import json
import unittest
from unittest.mock import patch
from tests.test_task_auto_recovery import AutomaticCompletion
from tests.test_task_queue import RawQueue
from tools import task_library as lib,task_queue as queue,task_queue_details as details,task_worker as worker


class QueueDetails(unittest.TestCase):
    setUp=RawQueue.setUp
    batch=RawQueue.batch
    request=RawQueue.request
    ready=RawQueue.ready
    payload=RawQueue.payload

    def test_lost_retained_raw_does_not_spend_other_units_frozen_budget(self):
        b=self.batch();from tests.test_task_queue import RawQueue
        req,first=RawQueue.complete_one(self,b,'retained-origin')
        request={**self.request(b,[1]),'auto_complete':False}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(request);task=lib.start({**request,'plan_sha256':p['plan_sha256'],'request_id':'lost-retained-mixed','authorization':'execute_selected_groups'})
        unit=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units'][0]
        raw=lib.unit_raw(b['category'],b['id'],1,unit);raw.resolve().relative_to(self.root.resolve());raw.unlink()
        calls=[]
        worker.run(b['category'],b['id'],task['id'],generate=lambda c,cfg,prompt:(calls.append(prompt) or self.payload()),clients=[(1,object())],render=lambda *a:None)
        self.assertEqual(len(calls),6);self.assertNotIn(unit['prompt'],calls)
        file=lib.batch_dir(b['category'],b['id'])/'tasks'/task['id']/'task.json'
        self.assertEqual(lib.read(file)['status'],'completed_with_errors')
        self.assertNotIn(unit['id'],lib.read(file.parent/'license.json')['attempts'])
    complete_one=RawQueue.complete_one

    def card(self,b,unit='g0001_u01'):
        return {'category':b['category'],'batch':b['id'],'unit':unit}

    def test_retry_records_safe_errors_and_read_only_ledger(self):
        b=self.batch();req={**self.request(b,[1]),'unit_ids':['g0001_u01']};calls=[]
        def generate(*args):
            calls.append(args)
            if len(calls)==1:raise TimeoutError('timed out secret-provider-url-token')
            return self.payload()
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req);t=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'retry-detail','authorization':'execute_selected_groups'})
            worker.run(b['category'],b['id'],t['id'],generate=generate,clients=[(1,object())],render=lambda *a:None)
        path=lib.batch_dir(b['category'],b['id'])/'tasks'/t['id']
        with (path/'events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'unit':[],'kind':'failed','error':{'secret':'secret-provider-url-token'}})+'\n{"truncated":')
        saved={name:(path/name).read_bytes() for name in ('task.json','license.json','events.jsonl')}
        result=lib.dispatch('queue-detail',self.card(b));records=result['licences'][0]['attempts']
        self.assertEqual([r['status'] for r in records],['failed','generated'])
        self.assertEqual(records[0]['error_code'],'transient');self.assertEqual(result['budget']['used'],2)
        self.assertEqual(result['budget']['maximum'],2);self.assertEqual(result['budget']['remaining_envelope'],0)
        self.assertIn('原图已保存',result['next_action']);self.assertNotIn('secret-provider',json.dumps(result))
        self.assertTrue(result['notes']);self.assertTrue(all((path/name).read_bytes()==value for name,value in saved.items()))

    def test_reserved_counter_without_events_cannot_offer_repeated_post(self):
        b=self.batch();req={**self.request(b,[1]),'unit_ids':['g0001_u01']}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req);t=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'reserved-detail','authorization':'execute_selected_groups'})
        path=lib.batch_dir(b['category'],b['id'])/'tasks'/t['id'];ledger=lib.read(path/'license.json')
        ledger.update(requests_used=1,attempts={'g0001_u01':1});lib.write(path/'license.json',ledger)
        original=(path/'task.json').read_bytes();result=details.view(self.card(b))
        self.assertEqual(result['budget']['used'],1);self.assertEqual(result['licences'][0]['attempts'][0]['status'],'request_reserved')
        self.assertIn('不能再次付费',result['next_action']);self.assertEqual((path/'task.json').read_bytes(),original)
        from tools import task_controls
        task_controls.change(t,['g0001_u01'],True)
        paused=details.view(self.card(b));self.assertTrue(paused['card']['unit_paused'])
        self.assertIn('不能再次付费',paused['next_action'])
        (path/'events.jsonl').write_bytes(b'x'*(2*1024*1024+1))
        self.assertIn('超过读取上限',details.view(self.card(b))['notes'][0])
        state=lib.read(path/'task.json');state.update(requests_used=1,attempts={'g0001_u01':1},results={'g0001_u01':{'status':'failed','error':'image_download_failed'}});lib.write(path/'task.json',state)
        self.assertEqual(details.view(self.card(b))['card']['reason'],'user_pause')
        self.assertIn('不能再次付费',details.view(self.card(b))['next_action'])

    def test_canonical_card_identity_and_separate_manual_revision(self):
        from tools.task_actions import prepare_replacement
        a=self.batch();b=self.batch();req,t=self.complete_one(a)
        base=details.view(self.card(a));other=details.view(self.card(b))
        self.assertEqual(base['budget']['used'],1);self.assertEqual(other['budget']['used'],0)
        with self.assertRaisesRegex(ValueError,'关联'):details.view({**self.card(b),'card_id':base['card']['id']})
        with self.assertRaises(ValueError):details.view(self.card(a,'../../license'))
        child=prepare_replacement({**req,'group':1,'position':1,'request_id':'detail-revision'})
        c_req={**req,'batch':child['id'],'unit_ids':['g0001_u01']}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(c_req);revision=lib.start({**c_req,'plan_sha256':p['plan_sha256'],'request_id':'detail-revision-start','authorization':'execute_selected_groups'})
            worker.run(a['category'],child['id'],revision['id'],generate=lambda *a:self.payload(),clients=[(1,object())],render=lambda *a:None)
        result=details.view(self.card(a));self.assertEqual(len(result['licences']),2)
        self.assertEqual(result['budget']['used'],2);self.assertEqual(result['budget']['maximum'],4)
        self.assertEqual(result['card']['id'],base['card']['id']);self.assertTrue(all(r['round']==0 for r in result['licences']))

    def test_partial_events_do_not_invent_attempt_ordinals_or_success(self):
        b=self.batch();req={**self.request(b,[1]),'unit_ids':['g0001_u01']}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req);t=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'partial-events','authorization':'execute_selected_groups'})
        path=lib.batch_dir(b['category'],b['id'])/'tasks'/t['id'];ledger=lib.read(path/'license.json')
        ledger.update(requests_used=2,attempts={'g0001_u01':2});lib.write(path/'license.json',ledger)
        state=lib.read(path/'task.json');state.update(requests_used=2,attempts={'g0001_u01':2},results={'g0001_u01':{'status':'generated','attempt':2,'request_number':2}});lib.write(path/'task.json',state)
        lines=[{'kind':'request_reserved','unit':'g0001_u01','request':2},{'kind':'generated','unit':'g0001_u01'}]
        (path/'events.jsonl').write_text('\n'.join(json.dumps(row) for row in lines),encoding='utf-8')
        result=details.view(self.card(b));records=result['licences'][0]['attempts']
        self.assertEqual([(r['attempt'],r['status']) for r in records],[(1,'unknown'),(2,'generated')])
        self.assertTrue(any('逐次记录缺失' in note for note in result['notes']));self.assertEqual(result['budget']['used'],2)
        state['results']['g0001_u01'].pop('attempt');lib.write(path/'task.json',state)
        value=details.view(self.card(b));self.assertEqual(value['licences'][0]['attempts'][0]['status'],'unknown')
        self.assertIsNone(value['licences'][0]['unassigned_events'][0]['attempt'])


class AutomaticCardDetails(unittest.TestCase):
    setUp=AutomaticCompletion.setUp
    batch=AutomaticCompletion.batch
    request=AutomaticCompletion.request
    ready=AutomaticCompletion.ready
    payload=AutomaticCompletion.payload
    render=AutomaticCompletion.render
    create_task=AutomaticCompletion.create_task
    execute=AutomaticCompletion.execute

    def test_two_rounds_are_allocations_inside_one_card_envelope(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][3];calls=collections.Counter()
        def generate(c,cfg,prompt):
            calls[prompt]+=1
            if prompt==bad['prompt'] and calls[prompt]<6:raise TimeoutError('timed out')
            return self.payload()
        scope={'category':b['category'],'batch':b['id'],'unit':bad['id']}
        before=details.view(scope);self.assertEqual(before['budget']['maximum'],6)
        self.assertEqual(before['budget']['unissued_repair_maximum'],4)
        self.assertEqual(self.execute(b,target,generate),0)
        value=details.view(scope);self.assertEqual(value['budget']['used'],6)
        self.assertEqual(value['budget']['maximum'],6);self.assertEqual(value['budget']['unissued_repair_maximum'],0)
        self.assertEqual([r['round'] for r in value['licences']],[0,1,2]);self.assertTrue(all(r['used']==2 for r in value['licences']))
        self.assertEqual([r['unit'] for r in value['licences']],[bad['id'],'g0001_u03','g0001_u03'])
        state=lib.read(file);entry=next(iter(state['auto_recovery']['children'].values()));entry['round']=2;lib.write(file,state)
        with self.assertRaisesRegex(ValueError,'父许可'):details.view(scope)


class ReusedCardDetails(unittest.TestCase):
    from tests.test_raw_library import RawLibrary as _fixtures
    setUp=_fixtures.setUp
    batch=_fixtures.batch
    request=_fixtures.request
    ready=_fixtures.ready
    add_stock=_fixtures.add_stock

    def test_library_reused_card_has_no_paid_allocation_in_mixed_task(self):
        b,unit,asset=self.add_stock()
        target=lib.assemble({'category':b['category'],'count':1,'phone':b['phone'],'seed':1455,'reuse_rate':100})
        req={**self.request(target,[1]),'auto_complete':True}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req);lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'mixed-library-budget','authorization':'execute_selected_groups'})
        from tools.raw_library import selection
        bound=selection(target)['bindings'][0]['unit']
        result=details.view({'category':target['category'],'batch':target['id'],'unit':bound})
        self.assertEqual(result['budget']['maximum'],0);self.assertEqual(result['budget']['used'],0)
        self.assertEqual(result['licences'][0]['maximum'],0);self.assertEqual(result['card']['source_type'],'library')

    def test_disabled_auto_repair_retains_zero_allocation_without_erasing_old_attempts(self):
        from tests.test_task_queue import RawQueue
        b=self.batch();request,first=RawQueue.complete_one(self,b,'retained-first')
        req={**self.request(b,[1]),'auto_complete':False}
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req);second=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'retained-mixed','authorization':'execute_selected_groups'})
        value=details.view({'category':b['category'],'batch':b['id'],'unit':'g0001_u01'})
        self.assertEqual([(r['used'],r['maximum']) for r in value['licences']],[(1,2),(0,0)])
        path=lib.batch_dir(b['category'],b['id'])/'tasks'/first['id'];state=lib.read(path/'task.json');ledger=lib.read(path/'license.json')
        state.pop('pending_unit_ids');ledger['terms'].pop('pending_unit_ids');state['license_sha256']=lib.digest(ledger['terms'])
        lib.write(path/'task.json',state);lib.write(path/'license.json',ledger)
        old=details.view({'category':b['category'],'batch':b['id'],'unit':'g0001_u01'})
        self.assertEqual(old['licences'][0]['used'],1);self.assertEqual(old['licences'][0]['maximum'],2)
        self.assertTrue(any('旧许可' in note for note in old['notes']))

    payload=RawQueue.payload


if __name__=='__main__':unittest.main()
