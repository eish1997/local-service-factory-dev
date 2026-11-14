"""Explicit 400 rejection recovery in frozen continuous caps; no provider API."""
import unittest
from unittest.mock import patch
from tests.test_task_budget import ContinuousBudget
from tools import task_library as lib,task_budget as budget,task_queue as queue,task_request_errors as errors


class Rejected(Exception):
    status_code=400


class RejectionRecovery(unittest.TestCase):
    setUp=ContinuousBudget.setUp
    batch=ContinuousBudget.batch
    ready=ContinuousBudget.ready
    payload=ContinuousBudget.payload
    render=ContinuousBudget.render
    prepare=ContinuousBudget.prepare
    execute=ContinuousBudget.execute

    def test_unknown_400_continues_across_child_licences_without_expanding_cap(self):
        b,req,task,file=self.prepare(7);calls=[]
        def generate(*args):
            calls.append(args[-1])
            if len(calls)<7:raise Rejected('upstream rejected request')
            return self.payload()
        self.execute(b,task,generate);state=lib.read(file)
        self.assertEqual((len(calls),state['status'],budget.progress(state)['used']),(7,'completed',7))
        self.assertEqual(len(set(calls)),1,'frozen prompt must not be rewritten')
        self.assertEqual(queue.view(req)['cards'][0]['attempts'],7)
        self.assertEqual(len(state['auto_recovery']['children']),3)

    def test_known_invalid_400_stops_only_bad_unit_and_keeps_safe_diagnostics(self):
        b,req,task,file=self.prepare(30,single=False);bad=lib.task_rows(file.parent.parent.parent,b,task)[0]['units'][0];calls=[]
        def generate(*args):
            calls.append(args[-1])
            if args[-1]==bad['prompt']:raise Rejected('invalid parameter size private-provider-secret')
            return self.payload()
        self.execute(b,task,generate);state=lib.read(file)
        self.assertEqual((state['status'],len(calls),calls.count(bad['prompt'])),('completed_with_errors',7,1))
        self.assertEqual(state['results'][bad['id']]['rejection_kind'],'parameters')
        self.assertNotIn('private-provider-secret',lib.io_path(file).read_text(encoding='utf-8'))
        self.assertEqual(queue.view(req)['counts']['completed'],6)
        with self.ready(),self.assertRaises(ValueError):lib.resume({**req,'task':task['id']})

    def test_finished_148_unknown_400_resumes_same_cap_with_original_or_child_room(self):
        for used in (1,2):
            with self.subTest(old_requests=used):
                b,req,task,file=self.prepare(5)
                path=file.parent.parent.parent
                frozen={name:lib.io_path(path/name).read_bytes() for name in ('manifest.json','snapshot.json','groups/0001.json')}
                real_retryable=errors.retryable
                def old_policy(state,result):
                    if result.get('error')=='request_rejected':return max(state['attempts'].values(),default=0)<used
                    return real_retryable(state,result)
                with patch.object(errors,'classify',return_value=('request_rejected',None)),patch.object(errors,'retryable',side_effect=old_policy):
                    self.execute(b,task,lambda *args:(_ for _ in ()).throw(Rejected('upstream rejected request')))
                old=lib.read(file);terms=lib.read(file.parent/'license.json')['terms']
                self.assertTrue(old['auto_recovery']['finished']);self.assertEqual(budget.progress(old)['used'],used)
                with self.ready(),patch.object(lib,'launch',return_value=99999999):lib.resume({**req,'task':task['id']})
                self.assertFalse(lib.read(file)['auto_recovery']['finished'])
                self.execute(b,task,lambda *args:self.payload());state=lib.read(file)
                self.assertEqual((state['status'],budget.progress(state)),('completed',{'used':used+1,'maximum':5,'remaining':4-used}))
                self.assertEqual(lib.read(file.parent/'license.json')['terms'],terms)
                self.assertEqual({name:lib.io_path(path/name).read_bytes() for name in frozen},frozen)

    def test_persistent_unknown_400_exhausts_cap_without_false_completion_or_reset(self):
        b,req,task,file=self.prepare(5);calls=[]
        def generate(*args):calls.append(args[-1]);raise Rejected('upstream rejected request')
        self.execute(b,task,generate);state=lib.read(file)
        self.assertEqual((len(calls),state['status'],budget.progress(state)['remaining']),(5,'completed_with_errors',0))
        self.assertEqual(queue.view(req)['cards'][0]['column'],'ongoing')
        with self.ready(),self.assertRaises(ValueError):lib.resume({**req,'task':task['id']})
        self.assertEqual(budget.progress(lib.read(file))['used'],5)

    def test_failed_resume_validation_does_not_reopen_finished_ledger(self):
        b,req,task,file=self.prepare(5)
        real_retryable=errors.retryable
        def old_policy(state,result):
            if result.get('error')=='request_rejected':return max(state['attempts'].values(),default=0)<2
            return real_retryable(state,result)
        with patch.object(errors,'classify',return_value=('request_rejected',None)),patch.object(errors,'retryable',side_effect=old_policy):
            self.execute(b,task,lambda *args:(_ for _ in ()).throw(Rejected('upstream rejected request')))
        ledger=lib.read(file)['auto_recovery'];licence=lib.io_path(file.parent/'license.json').read_bytes()
        with self.ready(),self.assertRaises(ValueError):lib.resume({**req,'task':task['id'],'only_failed':True})
        self.assertEqual(lib.read(file)['auto_recovery'],ledger)
        with self.ready(),patch.object(lib,'api_config',return_value={'model':'changed'}),self.assertRaisesRegex(ValueError,'API配置已变化'):
            lib.resume({**req,'task':task['id']})
        self.assertEqual(lib.read(file)['auto_recovery'],ledger)
        self.assertEqual(lib.io_path(file.parent/'license.json').read_bytes(),licence)

    def test_explicit_invalid_policy_and_ambiguous_results_remain_blocked(self):
        for message,reason in (('unsupported model','model'),('invalid size','parameters'),('invalid parameter timeout','parameters'),('policy violation','content')):
            self.assertEqual(errors.classify(Rejected(message)),('request_rejected',reason))
        from tools.task_recovery import blocked_reason
        state={'auto_complete':{'mode':'continuous'},'requests_used':1,'max_requests':2,'attempts':{'u':1},
               'results':{'u':{'status':'request_reserved','error':'request_rejected','http_status':400}}}
        self.assertEqual(blocked_reason(state,{'id':'u'}),'uncertain')
        state['results']['u']={'status':'failed','error':'image_download_failed','http_status':400}
        self.assertEqual(blocked_reason(state,{'id':'u'}),'download')
