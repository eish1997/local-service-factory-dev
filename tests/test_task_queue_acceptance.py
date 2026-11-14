"""Remaining queue gates, synthetic audit metadata and local pixels only."""
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tests.test_shared_tasks import SharedTasks
from tools import task_library as lib,task_worker as worker,raw_library as stock


class QueueContentGates(unittest.TestCase):
    setUp=SharedTasks.setUp
    batch=SharedTasks.batch

    def seed(self,b,status=None):
        originals={}
        for unit in lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units']:
            raw=lib.unit_raw(b['category'],b['id'],1,unit);lib.io_path(raw.parent).mkdir(parents=True,exist_ok=True)
            Image.new('RGB',(1024,1536),'gray').save(lib.io_path(raw))
            receipt={'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw)}
            if status is not None:
                receipt['audit']={'image_sha256':receipt['raw_sha256'],'status':status,
                    'production_approved':status=='accepted','vision_model':'offline-fixture-only',
                    'failure_reasons':['synthetic rejected record'] if status=='rejected' else []}
            lib.write(raw.with_suffix('.receipt.json'),receipt)
            originals[str(raw)]=lib.io_path(raw).read_bytes()
            originals[str(raw.with_suffix('.receipt.json'))]=lib.io_path(raw.with_suffix('.receipt.json')).read_bytes()
        return originals

    def test_ktv_retained_raw_local_restore_preserves_audit_and_never_autoapproves(self):
        for status in (None,'rejected','accepted'):
            with self.subTest(status=status):
                b=self.batch('business_ktv');originals=self.seed(b,status)
                req={'category':b['category'],'batch':b['id'],'groups':[1],
                     'auto_complete':{'mode':'continuous','total_max_requests':0}}
                with (patch.object(lib,'api_config',side_effect=AssertionError('free local recovery needs no API')),
                      patch.object(lib,'readiness',side_effect=AssertionError('no paid dispatch'))):
                    plan=lib.plan(req);self.assertEqual((plan['pending_count'],plan['total_max_requests'],plan['blocks']),(0,0,[]))
                    with patch.object(lib,'launch',return_value=99999999):
                        task=lib.start({**req,'plan_sha256':plan['plan_sha256'],'request_id':'local-'+str(status),'authorization':'execute_selected_groups'})
                def forbidden(*args):raise AssertionError('no paid request')
                self.assertEqual(worker.run(b['category'],b['id'],task['id'],generate=forbidden,clients=[]),0)
                for path,data in originals.items():self.assertEqual(lib.io_path(path).read_bytes(),data)
                view=lib.view(req);self.assertTrue(view['groups'][0]['images'])
                self.assertNotEqual(view['groups'][0]['status'],'approved')
                for image in view['groups'][0]['images']:
                    validation=lib.read(Path(image['path']).with_suffix('.validation.json'))
                    self.assertFalse(validation.get('approved'));self.assertFalse(validation.get('manual_visual_approval'))
                    self.assertNotEqual(image['review'],'approved')
                inventory=stock.view({'category':b['category']})
                self.assertTrue(inventory['entries'])
                self.assertTrue(all(e['eligibility']=='unconfirmed' for e in inventory['entries']))

    def test_ktv_qualified_reuse_is_not_blocked_by_vision(self):
        b=self.batch('business_ktv');self.seed(b)
        unit=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units'][0]
        asset=stock.register(b['category'],b['id'],1,unit)
        stock.qualify({'category':b['category'],'asset':asset['id'],'eligible':True,'authorization':'confirm_raw_reuse'})
        self.assertEqual(stock.load(b['category'],asset['id'])['eligibility'],'eligible')
        target=lib.assemble({'category':b['category'],'count':1,'phone':b['phone'],'seed':1401,'reuse_rate':100})
        self.assertEqual(target['library_reuse_count'],1)
        req={'category':target['category'],'batch':target['id'],'groups':[1]}
        with patch.object(lib,'api_config',return_value={'model':'local-only'}),patch.object(lib,'readiness',return_value=([],[])):
            plan=lib.plan(req)
            self.assertFalse(any('视觉审核' in message for message in plan['blocks']))
