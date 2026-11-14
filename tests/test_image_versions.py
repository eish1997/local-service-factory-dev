import copy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile
from PIL import Image
from tools import task_library as lib, task_worker as worker, task_actions as actions, task_assets as assets
from tools import image_versions as versions, postprocess_actions as restyle, postprocess_rules as rules

class ImageVersions(unittest.TestCase):
    def setUp(self):
        self.root=lib.ROOT/'.runtime'/('versions-test-'+uuid4().hex);self.root.mkdir()
        self.override=patch.object(lib,'ROOT',self.root);self.override.start();self.addCleanup(self.override.stop)
        self.batch=lib.assemble({'category':'road_rescue','count':1,'seed':1401,'phone':'13800138000'})
        self.req={'category':'road_rescue','batch':self.batch['id'],'group':1,'position':1}
        self.seed(self.batch,'gray')

    def seed(self,batch,color):
        path,data=lib.load_batch(batch['category'],batch['id']);row=lib.selected(path,data,[1])[0]
        for u in row['units']:
            raw=lib.unit_raw(batch['category'],batch['id'],1,u);raw.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(1024,1536),color).save(raw)
            lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':u['prompt_sha256'],'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest()})
        worker.materialize(batch['category'],batch['id'],data,[row],lib.read(path/'snapshot.json'))

    def target(self,position=1,kind='cover'):return lib.delivery_path('road_rescue',self.batch['id'],1,position,kind)

    def test_generation_replacement_history_cache_and_selected_pack(self):
        target=self.target();original=target.read_bytes();detail=self.target(3,'detail');other=detail.read_bytes()
        revision=lib.dispatch('view',{**self.req,'limit':1})['groups'][0]['images'][0]['revision']
        child=actions.prepare_replacement({**self.req,'request_id':'replace-one'})
        self.assertEqual(target.read_bytes(),original)
        self.seed(child,'blue');actions.commit_replacement('road_rescue',child['id'],child)
        self.assertNotEqual(target.read_bytes(),original);self.assertEqual(detail.read_bytes(),other)
        changed=lib.dispatch('view',{**self.req,'limit':1})['groups'][0]['images'][0]['revision'];self.assertNotEqual(changed,revision)
        history=versions.history(self.req);self.assertEqual(len(history['versions']),2)
        new=target.read_bytes();actions.commit_replacement('road_rescue',child['id'],child);self.assertEqual(target.read_bytes(),new);self.assertEqual(len(versions.history(self.req)['versions']),2)
        first=history['versions'][-1];versions.select({**self.req,'version':first['id']});self.assertEqual(target.read_bytes(),original)
        destination=self.root/'exports';destination.mkdir();result=assets.package({**self.req,'groups':[1],'destination':str(destination)})
        with zipfile.ZipFile(result['paths'][0]) as z:
            entry=next(n for n in z.namelist() if n.endswith('/01_cover.png'));self.assertEqual(z.read(entry),original)

    def test_random_reprocessing_preserves_content_and_raw_and_idempotent(self):
        target=self.target();before=lib.read(target.with_suffix('.validation.json'));raw=Path(before['postprocess_record']['sources'][0]);raw_bytes=raw.read_bytes()
        request={**self.req,'scope':'image','preset':'random','request_id':'style-one'}
        first=restyle.apply(request);snapshot=target.read_bytes();self.assertEqual(restyle.apply(request),first);self.assertEqual(target.read_bytes(),snapshot)
        second=restyle.apply({**request,'request_id':'style-two'});self.assertNotEqual(first['images'][0]['preset'],second['images'][0]['preset'])
        after=lib.read(target.with_suffix('.validation.json'));self.assertEqual(after['expected_text'],before['expected_text']);self.assertEqual(raw.read_bytes(),raw_bytes)
        self.assertEqual(first['api_requests'],0);self.assertEqual(len(versions.history(self.req)['versions']),3)

    def test_selected_history_survives_late_publish_materialize_index_and_pack(self):
        from tools import raw_library as stock
        target=self.target();original=target.read_bytes()
        original_sources=lib.read(target.with_suffix('.validation.json'))['postprocess_record']['sources']
        source_hashes=[stock.file_hash(Path(p)) for p in original_sources]
        child=actions.prepare_replacement({**self.req,'request_id':'late-after-history'})
        self.seed(child,'blue');actions.commit_replacement('road_rescue',child['id'],child)
        self.assertNotEqual(target.read_bytes(),original)
        history=versions.history(self.req);old=history['versions'][-1]
        versions.select({**self.req,'version':old['id']})
        before_index=lib.read(versions.index_path(target))
        selected_validation=lib.read(target.with_suffix('.validation.json'))
        # Late replay of B must not reactivate it after the user selected A.
        actions.commit_replacement('road_rescue',child['id'],child)
        path,data=lib.load_batch('road_rescue',self.batch['id'])
        row=lib.selected(path,data,[1])[0]
        self.assertEqual(worker.materialize('road_rescue',self.batch['id'],data,[row],lib.read(path/'snapshot.json')),[])
        indexed=stock.reindex({'category':'road_rescue','batch':self.batch['id'],'groups':[1]})
        cover=next(a for a in indexed['items'] if a.get('position')==1)
        asset=stock.load('road_rescue',cover['asset'])
        self.assertEqual(asset['raw_sha256'],source_hashes[0])
        self.assertEqual(target.read_bytes(),original)
        self.assertEqual(lib.read(target.with_suffix('.validation.json')),selected_validation)
        self.assertEqual(lib.read(versions.index_path(target)),before_index)
        destination=self.root/'late-exports';destination.mkdir()
        result=assets.package({**self.req,'groups':[1],'destination':str(destination)})
        with zipfile.ZipFile(result['paths'][0]) as archive:
            name=next(n for n in archive.namelist() if n.endswith('/01_cover.png'))
            self.assertEqual(archive.read(name),original)
        self.assertEqual(versions.history(self.req)['current'],old['id'])

    def test_group_restyle_and_missing_source_keeps_old(self):
        result=restyle.apply({**self.req,'scope':'group','preset':'blue_white','request_id':'style-group'})
        self.assertEqual(len(result['images']),5)
        self.assertEqual(lib.read(self.target(2,'triptych').with_suffix('.validation.json'))['postprocess_record']['rules']['preset_id'],'blue_white')
        before=self.target().read_bytes();validation=lib.read(self.target().with_suffix('.validation.json'));Path(validation['postprocess_record']['sources'][0]).unlink()
        with self.assertRaisesRegex(ValueError,'原图'):restyle.apply({**self.req,'scope':'group','preset':'random','request_id':'missing-raw'})
        self.assertEqual(self.target().read_bytes(),before)

    def test_damaged_archived_index_and_validation_are_isolated(self):
        from tools import raw_library as stock
        target=self.target();index_file=versions.index_path(target);index=lib.read(index_file)
        current=next(v for v in index['versions'] if v['id']==index['current'])
        validation_file=Path(current['path']).with_suffix('.validation.json')
        for file in (index_file,validation_file):
            with self.subTest(file=file.name):
                before=file.read_bytes();lib.write(file,[]);damaged=file.read_bytes()
                try:
                    result=stock.reindex({'category':'road_rescue','batch':self.batch['id'],'groups':[1]})
                    self.assertTrue(result['issues'])
                    self.assertFalse(any(item['position']==1 for item in result['items']))
                    self.assertTrue(any(item['position']==3 for item in result['items']))
                    self.assertEqual(file.read_bytes(),damaged)
                finally:file.write_bytes(before)

    def test_history_selection_during_render_prevents_late_publish(self):
        self.assert_inflight_selection_protected(False)

    def test_equal_byte_history_selection_during_render_prevents_late_publish(self):
        self.assert_inflight_selection_protected(True)

    def assert_inflight_selection_protected(self,equal_bytes):
        target=self.target();old_bytes=target.read_bytes()
        if equal_bytes:
            versions.publish(target,target,'road_rescue','same-pixels',event_id='equal-pixel-history')
            history=versions.history(self.req)
            self.assertNotEqual(history['versions'][0]['id'],history['versions'][-1]['id'])
            self.assertEqual(history['versions'][0]['sha256'],history['versions'][-1]['sha256'])
        child=actions.prepare_replacement({**self.req,'request_id':'render-selection-race'})
        self.seed(child,'blue')
        if not equal_bytes:actions.commit_replacement('road_rescue',child['id'],child)
        old=versions.history(self.req)['versions'][-1]
        path,data=lib.load_batch('road_rescue',child['id']);row=lib.selected(path,data,[1])[0]
        units=[u for u in row['units'] if u['delivery_position']==1];snapshot=lib.read(path/'snapshot.json')
        render=worker.images.apply_overlays;selected=[]
        def delayed(*args,**kwargs):
            result=render(*args,**kwargs)
            versions.select({**self.req,'version':old['id']});selected.append(True)
            return result
        with patch.object(worker.images,'apply_overlays',side_effect=delayed):
            with self.assertRaisesRegex(ValueError,'当前版本已改变'):
                worker.render_delivery('road_rescue',child['id'],data,row,1,units,snapshot,
                    snapshot['business'].get('service_items') or snapshot['business'].get('service_buttons'),5,target)
        self.assertTrue(selected);self.assertEqual(target.read_bytes(),old_bytes)
        self.assertEqual(versions.history(self.req)['current'],old['id'])
        export=self.root/'race-export';export.mkdir()
        result=assets.package({**self.req,'groups':[1],'destination':str(export)})
        with zipfile.ZipFile(result['path']) as archive:
            entry=next(n for n in archive.namelist() if n.endswith('/01_cover.png'))
            self.assertEqual(archive.read(entry),old_bytes)

    def test_group_render_and_publish_failure_roll_back_current(self):
        files=[self.target(1,'cover'),self.target(2,'triptych'),self.target(3,'detail'),self.target(4,'detail'),self.target(5,'detail')]
        before=[p.read_bytes() for p in files]
        request={**self.req,'scope':'group','preset':'blue_white'}
        with patch('tools.category_image_production.apply_overlays',side_effect=RuntimeError('render failed')):
            with self.assertRaisesRegex(RuntimeError,'render failed'):restyle.apply({**request,'request_id':'render-failure'})
        self.assertEqual([p.read_bytes() for p in files],before)
        self.assertFalse(any((p.parent/'.postprocess-staging'/'render-failure').exists() for p in files))
        publish=versions.publish;calls=[]
        def fail_second(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('publish failed')
            return publish(*args,**kwargs)
        with patch.object(versions,'publish',side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError,'publish failed'):restyle.apply({**request,'request_id':'publish-failure'})
        self.assertEqual([p.read_bytes() for p in files],before)
        history=versions.history(self.req)
        selected=next(v for v in history['versions'] if v['id']==history['current'])
        self.assertEqual(selected['sha256'],hashlib.sha256(before[0]).hexdigest())

    def test_no_content_in_presets_and_invalid_version_path(self):
        catalog=rules.load('road_rescue');self.assertGreaterEqual(len(catalog['presets']),3)
        doc={'schema_version':1,'engine_version':1,'defaults':{},'projects':{},'presets':[{'id':'evil','name':'bad','roles':['cover'],'parameters':{'cover':{'phone':'13900139000'}}}]}
        with self.assertRaises(ValueError):rules.validate(doc)
        restyle.apply({**self.req,'scope':'image','preset':'plain_dark','request_id':'valid'})
        with self.assertRaises(ValueError):versions.select({**self.req,'version':'../bad'})
        path=versions.index_path(self.target());index=lib.read(path);index['versions'][0]['path']=str(self.root/'private.png');lib.write(path,index)
        with self.assertRaises(ValueError):versions.history(self.req)

if __name__=='__main__':unittest.main()
