"""Batch reuse qualification stays project-scoped and separate from review."""
import unittest
from PIL import Image
from tests.test_shared_tasks import SharedTasks
from tools import task_library as lib,raw_library as stock


class BulkQualification(unittest.TestCase):
    setUp=SharedTasks.setUp
    batch=SharedTasks.batch

    def inventory(self,category='road_rescue'):
        batch=self.batch(category);rows=lib.selected(lib.batch_dir(category,batch['id']),batch,[1]);assets=[]
        for index,unit in enumerate(rows[0]['units']):
            raw=lib.unit_raw(category,batch['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True)
            Image.new('RGB',(1024,1536),(index*30,60,90)).save(raw)
            lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw)})
            assets.append(stock.register(category,batch['id'],1,unit))
        return batch,assets

    def confirm(self,category,ids,eligible=True):
        return lib.dispatch('raw-library-qualify',{'category':category,'assets':ids,'eligible':eligible,'authorization':'confirm_raw_reuse','source':'dashboard'})

    def test_selection_crosses_pages_is_read_only_and_excludes_disqualified(self):
        batch,assets=self.inventory();category=batch['category']
        self.confirm(category,[assets[0]['id']]);self.confirm(category,[assets[1]['id']],False)
        lib.io_path(assets[2]['path']).write_bytes(b'corrupt')
        file=stock.index_file(category,assets[3]['id']);value=stock.load(category,assets[3]['id']);value['missing_information']=['尚未核对'];lib.write(file,value)
        before={a['id']:stock.file_hash(stock.index_file(category,a['id'])) for a in assets}
        selection=lib.dispatch('raw-library-view',{'category':category,'selection':'pending','limit':1})
        self.assertEqual(selection['entries'],[])
        self.assertEqual(set(selection['selected_ids']),{a['id'] for a in assets[4:]})
        self.assertEqual(before,{a['id']:stock.file_hash(stock.index_file(category,a['id'])) for a in assets})

    def test_bulk_confirm_is_idempotent_preserves_raws_reviews_and_frozen_batch(self):
        batch,assets=self.inventory();category=batch['category'];ids=[a['id'] for a in assets]
        batch_hash=stock.file_hash(lib.batch_dir(category,batch['id'])/'batch.json')
        evidence={a['id']:(stock.file_hash(a['original_path']),stock.file_hash(a['path']),stock.file_hash(a['receipt_path'])) for a in assets}
        result=self.confirm(category,ids);self.assertEqual(result['updated'],7);self.assertEqual(result['failed'],[])
        first=[stock.load(category,id)['qualification'] for id in ids]
        again=self.confirm(category,ids);self.assertEqual(again['updated'],0);self.assertEqual(again['unchanged'],7)
        self.assertEqual(first,[stock.load(category,id)['qualification'] for id in ids])
        for a in assets:
            now=stock.load(category,a['id']);self.assertEqual(now['review'],a['review']);self.assertEqual(now['uses'],a['uses'])
            self.assertEqual(evidence[a['id']],(stock.file_hash(a['original_path']),stock.file_hash(a['path']),stock.file_hash(a['receipt_path'])))
        self.assertEqual(batch_hash,stock.file_hash(lib.batch_dir(category,batch['id'])/'batch.json'))
        new=lib.assemble({'category':category,'count':1,'phone':batch['phone'],'seed':1401,'reuse_rate':100})
        self.assertEqual(new['library_reuse_count'],7)
        self.assertEqual(self.confirm(category,ids,False)['updated'],7)
        self.assertEqual(stock.view({'category':category})['counts']['eligible'],0)

    def test_invalid_requests_write_nothing_and_changed_asset_is_isolated(self):
        batch,assets=self.inventory();category=batch['category'];ids=[a['id'] for a in assets]
        malformed=[[],ids[:1]*2,ids[:1]+['../../secret'],[True],ids[:1]*101]
        for value in malformed:
            with self.assertRaises(ValueError):self.confirm(category,value)
        with self.assertRaises(ValueError):stock.qualify({'category':category,'assets':ids,'eligible':True})
        with self.assertRaises(ValueError):stock.qualify({'category':category,'asset':ids[0],'assets':ids,'eligible':True,'authorization':'confirm_raw_reuse'})
        self.assertEqual(stock.view({'category':category})['counts']['eligible'],0)
        lib.io_path(assets[1]['path']).write_bytes(b'changed after selection')
        result=self.confirm(category,ids+['f'*64])
        self.assertEqual(result['updated'],6);self.assertEqual(len(result['failed']),2)
        self.assertEqual(stock.load(category,assets[1]['id'])['eligibility'],'unconfirmed')
        foreign=self.confirm('truck_rescue',ids);self.assertEqual(len(foreign['failed']),7);self.assertEqual(foreign['updated'],0)
        self.assertEqual(stock.load(category,ids[0])['eligibility'],'eligible')

    def test_business_ktv_shares_reuse_confirmation(self):
        batch,assets=self.inventory('business_ktv');ids=[a['id'] for a in assets]
        self.assertEqual(set(stock.view({'category':'business_ktv','selection':'pending'})['selected_ids']),set(ids))
        result=self.confirm('business_ktv',ids)
        self.assertEqual(result['updated'],len(ids));self.assertEqual(result['failed'],[])
        self.assertTrue(all(stock.load('business_ktv',id)['eligibility']=='eligible' for id in ids))
