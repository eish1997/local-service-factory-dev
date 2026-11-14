"""Offline shared-workflow coverage for salvage task types."""
import copy
from pathlib import Path
import uuid
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
from tools import task_library as lib, task_groups, variable_catalog as vc
from tools.task_diving_salvage import task_types

class DivingShared(unittest.TestCase):
    def setUp(self):
        root=lib.ROOT/'.runtime'/('diving-shared-test-'+uuid.uuid4().hex)
        root.mkdir()
        self.tmp=SimpleNamespace(name=str(root))
        self.patch=patch.object(lib,'ROOT',Path(self.tmp.name));self.patch.start();self.addCleanup(self.patch.stop)
        self.config=lib.business_config('diving_salvage')
        self.catalog=vc.load('diving_salvage')

    def batch(self,**kw):
        return lib.assemble({'category':'diving_salvage','count':1,'seed':1451,'phone':'13800138000','services':['潜水打捞'],**kw})

    def test_all_types_seven_and_frozen_continuity(self):
        for item in task_types(self.config):
            with self.subTest(task_type=item['id']):
                rows=task_groups.build_group('diving_salvage',1451,'13800138000',self.catalog,{**self.config,'task_type':item['id']})
                self.assertEqual(len(rows),7)
                self.assertEqual([u['kind'] for u in rows],['cover']+['detail']*6)
                self.assertEqual(len({u['salvage_context']['anchor_sha256'] for u in rows}),1)
                self.assertEqual(len({u['prompt'] for u in rows}),7)
                self.assertTrue(all(u['final_size']=='1024x1536' for u in rows))
                branch=item['selection']['branch']
                stages=self.config['stages'] if branch=='objects' else self.config['branch_stages'][branch]
                names={s['id']:s['name'] for s in [*stages,self.config['entry_stage'],self.config['land_survey_stage']]}
                self.assertIsNone(rows[0]['service_role'])
                for unit in rows[1:]:
                    stage=unit['salvage_context']['shot']['stages'][-1]
                    self.assertEqual(unit['service_role'],names[stage])
                if branch!='deceased_recovery':
                    self.assertTrue(all('逝者' not in (u['service_role'] or '') for u in rows))
                shots=[u['salvage_context']['shot'] for u in rows]
                if not rows[0]['salvage_context']['anchor']['visual']['underwater_capable']:
                    self.assertEqual(shots[2]['stages'],['site_survey'])
                    self.assertNotIn(['entry_airborne'],[s['stages'] for s in shots])
                    self.assertIn('13800138000',rows[0]['prompt'])
                else:self.assertNotIn('13800138000',rows[0]['prompt'])

    def test_shared_assembly_identity_selection_and_validation(self):
        a=self.batch(source='agent',task_type='pipeline:domestic:clean',request_id='same')
        b=self.batch(source='dashboard',task_type='pipeline:domestic:clean')
        self.assertEqual(a['manifest_sha256'],b['manifest_sha256'])
        self.assertEqual(a['prompt_count'],7)
        self.assertFalse(a['api_called'])
        self.assertEqual(a['id'],self.batch(task_type='pipeline:domestic:clean',request_id='same')['id'])
        with self.assertRaises(ValueError):self.batch(task_type='objects',request_id='same')
        with self.assertRaises(ValueError):self.batch(task_type='pipeline:domestic:underwater_pipeline')
        with self.assertRaises(ValueError):self.batch(phone='')
        path=lib.batch_dir('diving_salvage',a['id']);snap=lib.read(path/'snapshot.json')
        self.assertEqual(snap['business']['task_type'],'pipeline:domestic:clean')
        self.assertIn('resolved_pipe_sources',snap['business'])
        self.assertTrue(snap['postprocess']['auto_layout'])
        lib.selected(path,a,[1])

    def test_plan_budget_without_production(self):
        b=self.batch(task_type='underwater_work:cut')
        with patch.object(lib,'api_config',return_value={'model':'offline-test','api_size':'1024x1536','quality':'medium','output_format':'png'}),patch.object(lib,'readiness',return_value=([],[1])):
            p=lib.plan({'category':'diving_salvage','batch':b['id'],'groups':[1],'auto_complete':False})
            request={'category':'diving_salvage','batch':b['id'],'groups':[1]}
            automatic=lib.plan({**request,'auto_complete':'automatic_cap'})
            explicit=lib.plan({**request,'auto_complete':{'mode':'continuous','total_max_requests':42}})
            self.assertEqual(automatic['total_max_requests'],42)
            self.assertEqual(automatic['plan_sha256'],explicit['plan_sha256'])
        self.assertEqual(p['pending_count'],7)
        self.assertEqual(p['max_requests'],14)
        self.assertFalse(p['blocks'])

    def test_local_overlay_uses_batch_phone_services_and_caption(self):
        from tools.graphic_templates import production_rules
        from tools.category_image_production import apply_overlays
        b=self.batch();path=lib.batch_dir('diving_salvage',b['id']);snap=lib.read(path/'snapshot.json')
        raw=Path(self.tmp.name)/'raw.png';Image.new('RGB',(1024,1536),(85,110,125)).save(raw)
        for role in ['cover','detail']:
            out=Path(self.tmp.name)/(role+'.png')
            rules=production_rules(snap['postprocess'],0,1451,role)
            apply_overlays(raw,out,b['phone'],role,1451,1,['潜水打捞'],'1024x1536',service_role='纯装备展示' if role=='detail' else None,category_id='diving_salvage',postprocess_rules=rules)
            with Image.open(out) as image:self.assertEqual(image.size,(1024,1536))
            validation=lib.read(out.with_suffix('.validation.json'))
            self.assertIn('13800138000',str(validation))
            self.assertIn('潜水打捞',str(validation))
            self.assertNotIn('联系电话：13800138000',validation['expected_text'])


    def test_entry_caption_hidden_without_removing_phone_or_services(self):
        from tools.graphic_templates import production_rules
        from tools.category_image_production import apply_overlays
        from tools.postprocess_rules import load
        raw=Path(self.tmp.name)/'entry-raw.png'
        Image.new('RGB',(1024,1536),(85,110,125)).save(raw)
        for index,caption in enumerate(['滞空入水动作预览','纯装备展示']):
            target=Path(self.tmp.name)/f'entry-caption-{index}.png'
            rules=production_rules(load('diving_salvage'),1,1451,'detail')
            result=apply_overlays(raw,target,'13800138000','detail',1451,2,['潜水打捞','打捞手机'],'1024x1536',service_role=caption,category_id='diving_salvage',postprocess_rules=rules)
            self.assertIn('电话：13800138000',result['expected_text'])
            self.assertIn('打捞手机',result['expected_text'])
            if index==0:
                self.assertNotIn(caption,result['expected_text'])
                self.assertEqual(result['postprocess_record']['themes'],[])
            else:self.assertIn(caption,result['expected_text'])

if __name__=='__main__':unittest.main()
