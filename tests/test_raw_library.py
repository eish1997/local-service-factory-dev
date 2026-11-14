"""Isolated stock/adoption tests; qualification below is synthetic fixture data."""
import hashlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tests.test_shared_tasks import SharedTasks
from tools import task_library as lib,task_worker as worker,raw_library as stock


class RawLibrary(unittest.TestCase):
    setUp=SharedTasks.setUp
    batch=SharedTasks.batch
    request=SharedTasks.request
    ready=SharedTasks.ready

    def add_stock(self,kind='detail',eligible=True):
        b=self.batch();row=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]
        unit=next(u for u in row['units'] if u['kind']==kind)
        raw=lib.unit_raw(b['category'],b['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(1024,1536),(71,99,111)).save(raw)
        lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'task':'synthetic','unit':unit['id'],'source':{}})
        asset=stock.register(b['category'],b['id'],1,unit)
        if eligible:asset=stock.qualify({'category':b['category'],'asset':asset['id'],'eligible':True,'authorization':'confirm_raw_reuse'})
        return b,unit,asset

    def test_private_original_stock_idempotent_and_qualification(self):
        b,u,a=self.add_stock(eligible=False)
        self.assertEqual(stock.register(b['category'],b['id'],1,u)['id'],a['id'])
        self.assertEqual(stock.view({'category':b['category']})['counts']['eligible'],0)
        self.assertIn('详情',a['path']);self.assertTrue(stock.valid(a))
        with self.assertRaises(ValueError):stock.qualify({'category':b['category'],'asset':a['id'],'eligible':True})
        stock.qualify({'category':b['category'],'asset':a['id'],'eligible':True,'authorization':'confirm_raw_reuse'})
        self.assertEqual(stock.view({'category':b['category']})['counts']['eligible'],1)

    def test_frozen_reuse_keeps_source_receipt_and_target_content(self):
        b,u,a=self.add_stock()
        new=lib.assemble({'category':b['category'],'count':1,'phone':'13800138000','seed':1455,'reuse_rate':100})
        self.assertEqual(new['library_reuse_count'],1);self.assertEqual(new['reuse_shortfall'],6)
        req=self.request(new,[1])
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req);self.assertEqual(p['pending_count'],6);self.assertEqual(p['library_reused_count'],1)
            task=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'adopt','authorization':'execute_selected_groups'})
        binding=stock.selection(new)['bindings'][0];unit=next(x for x in lib.selected(lib.batch_dir(new['category'],new['id']),new,[1])[0]['units'] if x['id']==binding['unit'])
        raw=lib.unit_raw(new['category'],new['id'],1,unit)
        self.assertTrue(worker.raw_evidence_valid(raw,unit))
        self.assertEqual(raw.with_suffix('.receipt.json').read_bytes(),lib.io_path(a['receipt_path']).read_bytes())
        self.assertNotEqual(lib.read(raw.with_suffix('.receipt.json'))['prompt_sha256'],unit['prompt_sha256'])
        self.assertEqual(lib.read(raw.with_suffix('.adoption.json'))['target_snapshot_sha256'],new['snapshot_sha256'])
        self.assertEqual(stock.register(new['category'],new['id'],1,unit)['id'],a['id'])

    def test_changed_asset_blocks_without_paid_fallback_and_boundaries(self):
        b,u,a=self.add_stock();new=lib.assemble({'category':b['category'],'count':1,'phone':'13800138000','seed':1455,'reuse_rate':100})
        self.assertEqual(new['library_reuse_count'],1)
        lib.io_path(a['path']).write_bytes(b'corrupt')
        with self.ready():
            p=lib.plan(self.request(new,[1]));self.assertTrue(p['blocks']);self.assertEqual(p['pending_count'],6)
        with self.assertRaises(ValueError):stock.load(b['category'],'../../secret')
        for value in (-1,101,True,'50',float('nan')):
            with self.assertRaises(ValueError):stock.reuse_rate(value)

    def test_cover_phone_match_and_deduplicate(self):
        b,u,a=self.add_stock('cover');new=lib.assemble({'category':b['category'],'count':2,'phone':'13800138000','reuse_rate':100})
        self.assertEqual(new['library_reuse_count'],0)
        same=lib.assemble({'category':b['category'],'count':2,'phone':b['phone'],'reuse_rate':100})
        self.assertEqual(same['library_reuse_count'],1)

    def test_all_reuse_requires_no_api_keys_and_uses_frozen_content(self):
        b=self.batch();rows=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])
        for unit in rows[0]['units']:
            raw=lib.unit_raw(b['category'],b['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True)
            Image.new('RGB',(1024,1536),(unit['position']*21,70,90)).save(raw)
            lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'source':{}})
            a=stock.register(b['category'],b['id'],1,unit)
            stock.qualify({'category':b['category'],'asset':a['id'],'eligible':True,'authorization':'confirm_raw_reuse'})
        new=lib.assemble({'category':b['category'],'count':1,'phone':b['phone'],'seed':1401,'reuse_rate':100});req=self.request(new,[1])
        self.assertEqual(new['library_reuse_count'],7)
        with patch.object(lib,'api_config',side_effect=ValueError('no API configured')),patch.object(lib,'readiness',side_effect=AssertionError('must not request keys')),patch.object(lib,'launch',return_value=99999999):
            p=lib.plan(req);self.assertEqual(p['pending_count'],0);self.assertEqual(p['total_max_requests'],0);self.assertFalse(p['blocks'])
            t=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'all-local','authorization':'execute_selected_groups'})
            self.assertEqual(worker.run(new['category'],new['id'],t['id'],clients=[]),0)
        state=lib.read(lib.batch_dir(new['category'],new['id'])/'tasks'/t['id']/'task.json')
        self.assertEqual(state['requests_used'],0);self.assertEqual(state['completed_units'],7)
        self.assertEqual(len(lib.view({**req,'limit':1})['groups'][0]['images']),5)

    def test_repair_preserves_adopted_panels_and_unchanged_receipt(self):
        from tools import task_actions as actions
        b,original,asset=self.add_stock('triptych_panel')
        target=lib.assemble({'category':b['category'],'count':1,'phone':b['phone'],'seed':1455,'reuse_rate':100})
        path,data=lib.load_batch(target['category'],target['id']);rows=lib.selected(path,data,[1])
        stock.adopt(target['category'],data,rows)
        binding=stock.selection(data)['bindings'][0]
        panels=[u for u in rows[0]['units'] if u['delivery_position']==2]
        adopted=next(u for u in panels if u['id']==binding['unit'])
        source=lib.unit_raw(target['category'],target['id'],1,adopted)
        self.assertTrue(worker.raw_evidence_valid(source,adopted))
        self.assertNotEqual(lib.read(source.with_suffix('.receipt.json'))['prompt_sha256'],adopted['prompt_sha256'])
        dest=lib.batch_dir(target['category'],'batch_revision_inherited')
        child=actions.prepare_repair({'group':1,'position':2},data,lib.read(path/'snapshot.json'),panels,dest,dest.name)
        fresh=lib.selected(dest,child,[1])[0]['units'];kept=fresh[panels.index(adopted)]
        copy=lib.unit_raw(target['category'],child['id'],1,kept)
        self.assertTrue(worker.raw_evidence_valid(copy,kept))
        self.assertEqual(copy.with_suffix('.receipt.json').read_bytes(),source.with_suffix('.receipt.json').read_bytes())
        with self.ready():
            plan=lib.plan(self.request(child,[1]))
        self.assertEqual(plan['pending_count'],2)
        self.assertEqual(stock.register(target['category'],child['id'],1,kept)['id'],asset['id'])
        with patch.object(lib,'launch',return_value=99999999),patch.object(lib,'readiness',side_effect=AssertionError('local restore must not require keys')):
            req={**self.request(child,[1]),'unit_ids':[kept['id']]};plan=lib.plan(req)
            task=lib.start({**req,'plan_sha256':plan['plan_sha256'],'request_id':'inherited-local','authorization':'execute_selected_groups'})
            copy.with_suffix('.inherited.json').unlink()
            resumed=lib.resume({'category':target['category'],'batch':child['id'],'task':task['id']})
            self.assertEqual(resumed['requests_used'],0)
            self.assertTrue(worker.raw_evidence_valid(copy,kept))
        lib.io_path(copy).write_bytes(b'changed')
        self.assertFalse(worker.raw_evidence_valid(copy,kept))

    def test_original_response_hash_mismatch_is_not_registered(self):
        b,u,a=self.add_stock();raw=lib.unit_raw(b['category'],b['id'],1,u)
        original=raw.parent/'provider-original.png'
        Image.new('RGB',(1200,1800),(80,70,60)).save(original)
        receipt=lib.read(raw.with_suffix('.receipt.json'))
        receipt['source']={'provider_original':str(original),'source_sha256':stock.file_hash(original),'source_returned_size':'1200x1800'}
        lib.write(raw.with_suffix('.receipt.json'),receipt)
        Image.new('RGB',(1200,1800),(1,2,3)).save(original)
        with self.assertRaisesRegex(ValueError,'来源|摘要'):
            stock.register(b['category'],b['id'],1,u)

    def test_corrupt_records_are_isolated_from_view_and_selection(self):
        b,u,a=self.add_stock();file=stock.index_file(b['category'],'a'*64)
        lib.write(file,{'created_at':'bad'})
        invalid_json=stock.index_file(b['category'],'b'*64);invalid_json.write_text('{broken',encoding='utf-8')
        view=stock.view({'category':b['category']})
        self.assertEqual(view['counts']['eligible'],1)
        self.assertEqual(view['counts']['invalid'],2)
        self.assertEqual(sum(not v['technical_valid'] for v in view['entries']),2)
        new=lib.assemble({'category':b['category'],'count':1,'phone':b['phone'],'seed':1455,'reuse_rate':100})
        self.assertEqual(new['library_reuse_count'],1)
        self.assertEqual(lib.read(file),{'created_at':'bad'})

    def test_incomplete_cover_identity_is_not_a_reuse_candidate(self):
        b,u,a=self.add_stock('cover');file=stock.index_file(b['category'],a['id'])
        damaged=lib.read(file);damaged.pop('phone');lib.write(file,damaged)
        self.assertEqual(stock.view({'category':b['category']})['counts']['invalid'],1)
        target=lib.assemble({'category':b['category'],'count':1,'phone':b['phone'],'reuse_rate':100})
        self.assertEqual(target['library_reuse_count'],0)

    def test_standard_size_response_preserves_actual_provider_bytes(self):
        b=self.batch();u=lib.selected(lib.batch_dir(b['category'],b['id']),b,[1])[0]['units'][0]
        raw=lib.unit_raw(b['category'],b['id'],1,u);payload=io.BytesIO()
        Image.new('RGB',(1024,1536),(22,33,44)).save(payload,format='PNG',compress_level=0)
        source=worker.save_task_raw(raw,payload.getvalue(),{'model':'offline-test'},'cover')
        lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':u['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'source':source})
        asset=stock.register(b['category'],b['id'],1,u)
        self.assertEqual(lib.io_path(asset['original_path']).read_bytes(),payload.getvalue())
        self.assertNotEqual(asset['raw_sha256'],asset['original_sha256'])
        self.assertEqual(asset['original_status'],'provider_original')
        self.assertEqual(asset['original_sha256'],source['source_sha256'])

    def test_registered_roots_thumbnail_recovery_and_idempotent_use(self):
        from tools import task_assets
        b,u,a=self.add_stock();old=stock.folder({'category':b['category']})
        folder=self.root/('资产'*30)/('来源'*15);lib.io_path(folder).mkdir(parents=True)
        task_assets.save({'path':str(folder.resolve())})
        current=stock.folder({'category':b['category']})
        self.assertNotEqual(current['root_id'],old['root_id'])
        self.assertEqual(stock.folder({'category':b['category'],'root_id':old['root_id']})['path'],old['path'])
        with self.assertRaises(ValueError):stock.folder({'category':b['category'],'root_id':'arbitrary-root'})
        lib.io_path(a['thumbnail']).unlink();stock.register(b['category'],b['id'],1,u)
        self.assertTrue(lib.io_path(a['thumbnail']).is_file())
        target=lib.assemble({'category':b['category'],'count':1,'phone':b['phone'],'seed':1455,'reuse_rate':100})
        rows=lib.selected(lib.batch_dir(b['category'],target['id']),target,[1])
        stock.adopt(b['category'],target,rows);stock.adopt(b['category'],target,rows)
        self.assertEqual(len(stock.load(b['category'],a['id'])['uses']),1)


if __name__=='__main__':unittest.main()
