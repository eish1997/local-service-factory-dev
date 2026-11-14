"""Independent review of frozen automatic repair scope and crash recovery."""
import collections
import unittest
from unittest.mock import patch
from tools import task_library as lib,task_worker as worker,task_auto_recovery as auto,task_actions as actions
from tests import test_task_auto_recovery as fixtures


class AutomaticReview(unittest.TestCase):
    setUp=fixtures.AutomaticCompletion.setUp
    batch=fixtures.AutomaticCompletion.batch
    ready=fixtures.AutomaticCompletion.ready
    payload=fixtures.AutomaticCompletion.payload
    render=fixtures.AutomaticCompletion.render
    request=fixtures.AutomaticCompletion.request
    create_task=fixtures.AutomaticCompletion.create_task
    execute=fixtures.AutomaticCompletion.execute

    def test_automatic_children_cannot_plan_or_resume_outside_parent(self):
        b,req,target,file,rows=self.create_task();state=lib.read(file)
        child,tid=auto.child_ids(state,1,1,1)
        saved=actions.prepare_repair({'group':1,'position':1},b,
            lib.read(lib.batch_dir(b['category'],b['id'])/'snapshot.json'),[rows[0]['units'][0]],lib.batch_dir(b['category'],child),child)
        saved['automatic_repair_parent']={'batch':b['id'],'task':target['task'],'round':1}
        lib.write(lib.batch_dir(b['category'],child)/'batch.json',saved)
        with self.ready(),self.assertRaisesRegex(ValueError,'原任务'):
            lib.plan({'category':b['category'],'batch':child,'groups':[1]})
        with self.assertRaisesRegex(ValueError,'原任务'):
            lib.resume({'category':b['category'],'batch':child,'task':tid})

    def test_ledger_units_are_bound_to_their_delivery(self):
        b,req,target,file,rows=self.create_task(count=2);state=lib.read(file)
        child,tid=auto.child_ids(state,1,1,1)
        state['auto_recovery']={'children':{tid:{'batch':child,'group':1,'position':1,'round':1,'units':[rows[1]['units'][0]['id']]}}}
        with self.assertRaisesRegex(ValueError,'图片范围'):auto.validate_ledger(b['category'],state)

    def test_latest_failure_replaces_exhausted_main_diagnostic_without_secret(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=collections.Counter()
        class Blocked(Exception):status_code=451
        def generate(client,cfg,prompt):
            calls[prompt]+=1
            if prompt==bad['prompt']:
                if calls[prompt]<=2:raise TimeoutError('timed out')
                raise Blocked('secret-provider-URL-must-not-be-displayed')
            return self.payload()
        self.execute(b,target,generate);state=lib.read(file)
        failures=auto.public_progress(state)['auto_failures']
        self.assertEqual(len(failures),1)
        self.assertEqual((failures[0]['unit'],failures[0]['round'],failures[0]['http_status']),(bad['id'],2,451))
        self.assertEqual(failures[0]['reason'],'non_retryable')
        self.assertEqual(state['auto_recovery']['failures'],failures)
        self.assertNotIn('secret-provider',str(state))
        self.assertEqual(calls[bad['prompt']],4)

    def test_child_crash_reservation_does_not_repeat_paid_request_on_resume(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=collections.Counter()
        def generate(client,cfg,prompt):
            calls[prompt]+=1
            if prompt==bad['prompt']:
                if calls[prompt]<=2:raise TimeoutError('timed out')
                raise KeyboardInterrupt('simulated process exit after reservation')
            return self.payload()
        with self.assertRaises(KeyboardInterrupt):self.execute(b,target,generate)
        state=lib.read(file);self.assertEqual(state['status'],'recovering')
        entry=next(iter(state['auto_recovery']['children'].values()))
        child,tid=auto.child_ids(state,1,1,1);childfile=lib.batch_dir(b['category'],child)/'tasks'/tid/'task.json'
        self.assertEqual(lib.read(childfile)['requests_used'],1)
        self.execute(b,target,lambda client,cfg,prompt:(calls.update([prompt]),self.payload())[1])
        done=lib.read(file)
        self.assertEqual(done['status'],'completed_with_errors')
        self.assertEqual(calls[bad['prompt']],3)
        self.assertEqual(done['auto_recovery']['requests_used'],1)
        self.assertEqual(auto.public_progress(done)['auto_failures'][0]['reason'],'uncertain')

    def test_encrypted_returned_url_is_recovered_by_get_without_new_post(self):
        from tools import image_download_receipts as receipts
        b,req,target,file,rows=self.create_task();unit=rows[0]['units'][0];state=lib.read(file)
        result={'status':'failed','error':'image_download_failed','request_number':1,'attempt':1}
        state.update(requests_used=1,attempts={unit['id']:1},results={unit['id']:result})
        lic=lib.read(file.parent/'license.json');lic.update(requests_used=1,attempts=state['attempts'])
        lib.write(file.parent/'license.json',lic);lib.write(file,state)
        context=auto.download_context(lib.batch_dir(b['category'],b['id']),state,unit,result)
        receipts.save_returned_url(context,'https://example.com/private-returned.png')
        calls=[]
        with patch('image_generate.download_image_url',return_value=self.payload()) as download:
            self.execute(b,target,lambda client,cfg,prompt:(calls.append(prompt),self.payload())[1])
        done=lib.read(file)
        self.assertEqual(done['status'],'completed');self.assertEqual(len(calls),6)
        self.assertNotIn(unit['prompt'],calls);self.assertEqual(download.call_count,1)
        self.assertEqual(done['auto_recovery']['requests_used'],0)
        self.assertEqual(auto.public_progress(done)['auto_failures'],[])
        self.assertNotIn('private-returned.png',str(done))

    def test_direct_automatic_child_worker_cannot_run_under_paused_parent(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=collections.Counter()
        def generate(client,cfg,prompt):
            calls[prompt]+=1
            if prompt==bad['prompt'] and calls[prompt]<=2:raise TimeoutError('timed out')
            if prompt==bad['prompt']:
                lib.write(file.parent/'pause.json',{'requested_at':lib.now()})
                raise TimeoutError('timed out')
            return self.payload()
        self.execute(b,target,generate);state=lib.read(file);self.assertEqual(state['status'],'paused')
        child,tid=auto.child_ids(state,1,1,1);dispatch=[]
        worker.run(b['category'],child,tid,generate=lambda *args:(dispatch.append(1),self.payload())[1],clients=[(1,object())],render=self.render)
        self.assertEqual(dispatch,[])

    def test_free_recovery_raw_and_provider_archive_over_300_characters(self):
        from tools import category_image_production as images,category_4k_raw as fourk
        from PIL import Image
        import io
        raw=self.root/('a'*95)/('b'*95)/'.recovery'/'g0001_u01-2.png'
        self.assertGreater(len(str(raw)),300)
        result=worker.save_task_raw(raw,self.payload(),{'model':'offline-test'},'detail')
        self.assertTrue(images.valid_png(raw,(1024,1536)))
        lib.write(raw.with_suffix('.receipt.json'),result)
        source=io.BytesIO();Image.new('RGB',(2352,3520),'gray').save(source,format='PNG')
        target=raw.with_name('fourk.png')
        cfg={'model':'gpt-image-2-4k','raw_contract':fourk.WIDTH_TOLERANCE_SOURCE_CONTRACT,'api_size':'2560x3840','quality':'medium','provider':'relay','base_url':'https://tinysnow.one/v1'}
        saved=worker.save_task_raw(target,source.getvalue(),cfg,'detail')
        self.assertTrue(images.valid_png(target,(1024,1536)))
        self.assertGreater(len(saved['provider_original']),300)
        self.assertFalse(saved['provider_original'].startswith('\\\\?\\'))
        self.assertTrue(lib.io_path(saved['provider_original']).is_file())
        self.assertEqual(lib.read(saved['provider_original_metadata'])['provider_original'],saved['provider_original'])
        from tools import graphic_templates as graphics
        batch=self.batch();snapshot=lib.read(lib.batch_dir(batch['category'],batch['id'])/'snapshot.json')
        frozen=graphics.production_rules(snapshot['postprocess'],0,42,'detail')
        delivery=raw.with_name('detail.png')
        graphics.render_delivery(Image.new('RGB',(1024,1536),'gray'),delivery,'15795643941',['汽车救援','搭电救援'],frozen,'detail','road_rescue',[raw],extra={'service_role':'搭电救援'})
        self.assertTrue(images.valid_png(delivery,(1024,1536)))
        self.assertEqual(lib.read(delivery.with_suffix('.validation.json'))['postprocess_record']['sources'],[str(raw)])

    def test_explicit_resume_reenables_validated_recharged_slots(self):
        b,req,target,file,rows=self.create_task()
        with patch.object(worker.images,'classify_request_error',return_value='balance_exhausted'):
            self.execute(b,target,lambda *args:(_ for _ in ()).throw(ValueError('balance')))
        before=lib.read(file);self.assertEqual(before['status'],'paused');self.assertEqual(before['quarantined_slots'],[1])
        license_before=lib.read(file.parent/'license.json')
        with self.ready(),patch.object(lib,'launch',return_value=99999999):resumed=lib.resume(target)
        self.assertEqual(resumed['quarantined_slots'],[]);self.assertTrue(resumed['resume_key_epoch'])
        self.assertEqual(lib.read(file.parent/'license.json'),license_before)
        calls=[];self.execute(b,target,lambda *args:(calls.append(1),self.payload())[1])
        done=lib.read(file);self.assertEqual(done['status'],'completed');self.assertEqual(len(calls),7)
        self.assertEqual(done['requests_used'],8);self.assertEqual(max(done['attempts'].values()),2)

    def test_parent_resume_reenables_previously_quarantined_automatic_child_once(self):
        b,req,target,file,rows=self.create_task();bad=rows[0]['units'][0];calls=collections.Counter()
        def generate(client,cfg,prompt):
            calls[prompt]+=1
            if prompt==bad['prompt'] and calls[prompt]<=2:raise TimeoutError('timed out')
            if prompt==bad['prompt'] and calls[prompt]==3:raise ValueError('balance')
            return self.payload()
        original=worker.images.classify_request_error
        with patch.object(worker.images,'classify_request_error',side_effect=lambda error:'balance_exhausted' if isinstance(error,ValueError) else original(error)):
            self.execute(b,target,generate)
        before=lib.read(file);self.assertEqual(before['status'],'paused');self.assertEqual(before['resume_summary']['ready_count'],0)
        child,tid=auto.child_ids(before,1,1,1);childfile=lib.batch_dir(b['category'],child)/'tasks'/tid/'task.json'
        self.assertEqual(lib.read(childfile)['quarantined_slots'],[1]);parent_license=lib.read(file.parent/'license.json')
        with self.ready(),patch.object(lib,'launch',return_value=99999999):resumed=lib.resume(target)
        self.assertEqual(resumed['quarantined_slots'],[]);self.assertTrue(resumed['resume_key_epoch'])
        self.assertEqual(lib.read(file.parent/'license.json'),parent_license)
        self.execute(b,target,generate);done=lib.read(file);childstate=lib.read(childfile)
        self.assertEqual(done['status'],'completed');self.assertEqual(calls[bad['prompt']],4)
        self.assertEqual(done['requests_used'],before['requests_used']);self.assertEqual(done['auto_recovery']['requests_used'],2)
        self.assertEqual(len(done['auto_recovery']['children']),1)
        self.assertEqual(childstate['parent_key_epoch'],done['resume_key_epoch'])
        childstate['quarantined_slots']=[1]
        auto.restore_child_slots(done,childstate)
        self.assertEqual(childstate['quarantined_slots'],[1])

    def test_invalid_resume_preserves_quarantine(self):
        b,req,target,file,rows=self.create_task()
        with patch.object(worker.images,'classify_request_error',return_value='authentication_failed'):
            self.execute(b,target,lambda *args:(_ for _ in ()).throw(ValueError('authentication')))
        before=lib.read(file);license_before=lib.read(file.parent/'license.json')
        with self.ready(),patch.object(lib,'api_config',return_value={**before['config'],'model':'changed'}),patch.object(lib,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'API配置已变化'):lib.resume(target)
            launch.assert_not_called()
        with self.ready(),patch.object(lib,'readiness',return_value=([],[2,3,4])),patch.object(lib,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'槽位缺失'):lib.resume(target)
            launch.assert_not_called()
        after=lib.read(file);self.assertEqual(after['quarantined_slots'],[1])
        self.assertNotIn('resume_key_epoch',after);self.assertEqual(lib.read(file.parent/'license.json'),license_before)

    def test_local_only_resume_needs_no_api_and_keeps_quarantine(self):
        b,req,target,file,rows=self.create_task()
        self.execute(b,target,lambda *args:self.payload());state=lib.read(file)
        state.update(status='paused',local_render_errors=[{'group':1,'position':1,'error':'OSError'}],quarantined_slots=[1])
        lib.write(file,state)
        with patch.object(lib,'api_config',side_effect=AssertionError('local recovery must not check API')),patch.object(lib,'readiness',side_effect=AssertionError('local recovery must not check keys')),patch.object(lib,'launch',return_value=99999999):
            resumed=lib.resume(target)
        self.assertEqual(resumed['quarantined_slots'],[1]);self.assertNotIn('resume_key_epoch',resumed)


if __name__=='__main__':unittest.main()
