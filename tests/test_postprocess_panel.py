import copy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4
from PIL import Image
from tools import task_library as lib, postprocess_view as view, postprocess_rules as rules, category_image_production as render

class PostprocessPanel(unittest.TestCase):
    def setUp(self):
        self.root=lib.ROOT/'.runtime'/('postprocess-test-'+uuid4().hex);self.root.mkdir()
        self.override=patch.object(lib,'ROOT',self.root);self.override.start();self.addCleanup(self.override.stop)
        self.batch=lib.assemble({'category':'road_rescue','count':1,'seed':1401,'phone':'13800138000'})
        self.request={'category':'road_rescue','batch':self.batch['id'],'group':1,'position':1}

    def test_snapshot_and_readonly_missing_states(self):
        path=lib.batch_dir('road_rescue',self.batch['id'])
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}
        result=view.view(self.request)
        self.assertEqual(lib.dispatch('postprocess-view',self.request)['position'],1)
        self.assertEqual(len(lib.dispatch('view',{**self.request,'limit':1})['groups']),1)
        self.assertFalse(result['delivery']['exists']);self.assertEqual(len(result['sources']),1)
        self.assertEqual(result['frozen_rules']['engine_version'],1)
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in before})
        with self.assertRaises(ValueError):view.view({**self.request,'batch':'../escape'})
        with self.assertRaises(ValueError):view.view({**self.request,'group':True})
        with self.assertRaises(ValueError):view.view({**self.request,'position':99})

    def test_new_batches_materialize_templates_and_old_snapshot_stays_frozen(self):
        from collections import Counter
        from tools import task_worker as worker, graphic_templates
        for category in ('road_rescue','truck_rescue'):
            batch=lib.assemble({'category':category,'count':1,'seed':1421,'phone':'13800138000'})
            path=lib.batch_dir(category,batch['id']);snapshot=lib.read(path/'snapshot.json')
            self.assertTrue(snapshot['postprocess']['auto_layout'])
            row=lib.read(path/'groups/0001.json');raw_bytes={}
            for unit in row['units']:
                raw=lib.unit_raw(category,batch['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True)
                Image.new('RGB',(1024,1536),'#626b76').save(raw);raw_bytes[raw]=raw.read_bytes()
                lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':hashlib.sha256(raw_bytes[raw]).hexdigest()})
            worker.materialize(category,batch['id'],batch,[row],snapshot)
            families=[];target_bytes={}
            services=snapshot['business'].get('service_items') or snapshot['business']['service_buttons']
            for position in sorted({u['delivery_position'] for u in row['units']}):
                unit=next(u for u in row['units'] if u['delivery_position']==position)
                kind='triptych' if unit['kind']=='triptych_panel' else unit['kind']
                target=lib.delivery_path(category,batch['id'],1,position,kind)
                record=lib.read(target.with_suffix('.validation.json'))['postprocess_record']
                layout=record['layout'];families.append(layout['family']);target_bytes[target]=target.read_bytes()
                self.assertEqual(layout['phone'],batch['phone']);self.assertFalse(layout['fallback'])
                expected=render._record_overlay_service_items(unit,services) if kind!='triptych' else services
                self.assertEqual(Counter(w for group in layout['groups'] if group['kind']!='phone' for w in group['words']),Counter(expected))
                phone=next(g for g in layout['groups'] if g['kind']=='phone')
                width,height=layout['photo_size'];box=phone['box']
                self.assertLessEqual(abs((box[0]+box[2])/2-width/2),1)
                self.assertLessEqual(abs((box[1]+box[3])/2-height/2),1)
            self.assertTrue(all(a!=b for a,b in zip(families,families[1:])))
            with patch.object(rules,'load',side_effect=AssertionError('must use frozen snapshot')):
                worker.materialize(category,batch['id'],batch,[row],snapshot)
            self.assertTrue(all(p.read_bytes()==b for p,b in raw_bytes.items()))
            self.assertTrue(all(p.read_bytes()==b for p,b in target_bytes.items()))
            old=copy.deepcopy(snapshot['postprocess']);old['auto_layout']=False
            self.assertIs(graphic_templates.production_rules(old,0,7,'cover'),old)

    def test_render_consumes_frozen_rules_and_preserves_raw(self):
        path=lib.batch_dir('road_rescue',self.batch['id']);row=lib.read(path/'groups/0001.json');u=row['units'][0]
        raw=lib.unit_raw('road_rescue',self.batch['id'],1,u);raw.parent.mkdir(parents=True);Image.new('RGB',(1024,1536),'gray').save(raw)
        before=raw.read_bytes();target=lib.delivery_path('road_rescue',self.batch['id'],1,1,'cover')
        frozen=copy.deepcopy(lib.read(path/'snapshot.json')['postprocess'])
        frozen['parameters']['cover']={'phone_region':[.1,.35,.9,.45],'phone_color':[200,10,10,255],'phone_font_ratio':.05,'service_columns':2,'service_region':[.05,.8,.95,.98]}
        result=render.apply_overlays(raw,target,'13800138000','cover',1401,1,['轮胎检查','搭电服务']*5,postprocess_rules=frozen,category_id='road_rescue')
        self.assertEqual(raw.read_bytes(),before)
        actual=result['postprocess_record'];self.assertEqual(actual['phone']['box'],[102,537,921,691]);self.assertEqual(actual['phone']['color'],[200,10,10,255])
        self.assertEqual(actual['rules'],frozen)
        with patch.object(rules,'load',side_effect=AssertionError('must not use current rules')):
            inspected=view.view(self.request)
        self.assertEqual(inspected['parameters']['rules'],frozen)
        self.assertTrue(inspected['delivery']['exists'])

    def test_triptych_override_and_detail(self):
        path=lib.batch_dir('road_rescue',self.batch['id']);row=lib.read(path/'groups/0001.json');units=[u for u in row['units'] if u['kind']=='triptych_panel'];records=[]
        for u in units:
            raw=lib.unit_raw('road_rescue',self.batch['id'],1,u);raw.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(1024,1536),'gray').save(raw)
            records.append({**u,'category_id':'road_rescue','raw_target':str(raw),'group_index':1401,'index':u['position'],'generation_kind':u['kind'],'generation_target_id':u['id'],'delivery_target_id':'triptych'})
        frozen=rules.load('road_rescue');frozen['parameters']['triptych']={'gutter_px':12,'content_height_ratio':.75,'phone_color':[10,20,30,255]}
        target=lib.delivery_path('road_rescue',self.batch['id'],1,2,'triptych')
        result=render.compose_triptych(records,target,'13800138000',['搭电','轮胎'],postprocess_rules=frozen)
        self.assertEqual(result['triptych_recipe']['gutter_px'],12)
        inspected=view.view({**self.request,'position':2});self.assertEqual(len(inspected['sources']),3);self.assertEqual(inspected['kind'],'triptych')
        u=next(u for u in row['units'] if u['kind']=='detail');raw=lib.unit_raw('road_rescue',self.batch['id'],1,u);Image.new('RGB',(1024,1536),'gray').save(raw)
        target=lib.delivery_path('road_rescue',self.batch['id'],1,u['delivery_position'],'detail')
        render.apply_overlays(raw,target,'13800138000','detail',1401,u['delivery_position'],['搭电','轮胎'],category_id='road_rescue',postprocess_rules=frozen)
        self.assertTrue(view.view({**self.request,'position':u['delivery_position']})['delivery']['exists'])

    def test_legacy_and_untrusted_source_path(self):
        target=self.root/'output/road_rescue/group_0009/01_cover.png';target.parent.mkdir(parents=True);Image.new('RGB',(30,40)).save(target)
        lib.write(self.root/'.runtime/dashboard_delivery_state.json',{'projects':{'road_rescue':{'pending_groups':{'9':{'group_index':9,'paths':[str(target)]}}}}})
        req={'category':'road_rescue','batch':'legacy','group':9,'position':1}
        self.assertEqual(view.view(req)['sources'],[])
        lib.write(target.with_suffix('.validation.json'),{'postprocess_record':{'sources':[str(self.root/'configs/secret.png')]}})
        with self.assertRaisesRegex(ValueError,'越界'):view.view(req)

    def test_rules_validation_and_public_export(self):
        from tools import rule_updates, variable_catalog
        doc={'schema_version':1,'engine_version':1,'defaults':{'cover':{'phone_stroke':False}},'projects':{}}
        with self.assertRaises(ValueError):rules.validate(doc)
        doc['defaults']={'cover':{'font_family':'../../private'}}
        with self.assertRaises(ValueError):rules.validate(doc)
        # Test the postprocess package against isolated valid catalogs, not mutable
        # production variable overrides from unrelated work on this maintainer host.
        with patch.object(variable_catalog,'load',side_effect=variable_catalog.defaults):docs=rule_updates.export_documents()
        self.assertIn('configs/postprocess.json',docs)
        self.assertNotIn(b'13800138000',docs['configs/postprocess.json'])
        import json
        exported=json.loads(docs['configs/postprocess.json']);rules.validate(exported)
        self.assertEqual(set(exported['layout_categories']),set(__import__('tools.rule_updates',fromlist=['PROJECTS']).PROJECTS))
        self.assertEqual(set(exported['auto_layout_categories']),set(__import__('tools.rule_updates',fromlist=['PROJECTS']).PROJECTS))
        self.assertEqual(len([p for p in exported['presets'] if 'structure' in p]),18)
        from tools import runtime_paths
        clean=self.root/'clean-rules';(clean/'configs').mkdir(parents=True)
        (clean/'configs/postprocess.json').write_bytes(docs['configs/postprocess.json'])
        lib.write(clean/'manifest.json',{'version':'200'})
        with runtime_paths.use_rules(clean):
            self.assertTrue(rules.load('truck_rescue')['auto_layout'])
            self.assertEqual(len(rules.load('truck_rescue')['presets']),22)
            self.assertTrue(rules.load('pet_transport')['auto_layout'])
            self.assertEqual(len(rules.load('pet_transport')['presets']),22)

    def test_registered_custom_assets_and_frozen_rules(self):
        from tools import task_assets
        custom=self.root/'custom-assets';custom.mkdir()
        task_assets.save({'path':str(custom)})
        frozen=rules.load('road_rescue')
        frozen['parameters']['detail']={'phone_color':[50,60,70,255]}
        with patch.object(rules,'load',return_value=frozen):
            batch=lib.assemble({'category':'road_rescue','count':1,'seed':1402,'phone':'13800138000'})
        req={**self.request,'batch':batch['id']}
        with patch.object(rules,'load',side_effect=AssertionError('current rules must not be read')):
            result=view.view(req)
        self.assertTrue(Path(result['delivery']['path']).is_relative_to(custom))
        self.assertEqual(result['frozen_rules'],frozen)
        self.assertEqual(lib.load_batch('road_rescue',batch['id'])[1]['snapshot_sha256'],lib.digest(lib.read(lib.batch_dir('road_rescue',batch['id'])/'snapshot.json')))

    def test_incompatible_rule_bundle_rejected(self):
        from tools import rule_updates, runtime_paths, variable_catalog
        with patch.object(variable_catalog,'load',side_effect=variable_catalog.defaults):docs=rule_updates.export_documents()
        payload={'kind':'rules','schema':1,'version':'100','min_app':'1.4.0','engine_major':1,'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in docs.items()}}
        cfg={**runtime_paths.config(),'app_version':'1.3.1'}
        with self.assertRaisesRegex(ValueError,'更新软件'):rule_updates.validate_payload(payload,cfg)
        cfg['app_version']='1.4.0';rule_updates.validate_payload(payload,cfg)
        rules.validate({'schema_version':1,'engine_version':1,'defaults':{},'projects':{}})
        with self.assertRaises(ValueError):rules.validate({'schema_version':2,'engine_version':1,'defaults':{},'projects':{}})

if __name__=='__main__':unittest.main()
