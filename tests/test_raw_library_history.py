"""Isolated registered-history indexing; images and receipts are synthetic fixtures."""
import hashlib
import unittest
from PIL import Image
from tests.test_shared_tasks import SharedTasks
from tools import task_library as lib,raw_library as stock


class HistoryStock(unittest.TestCase):
    setUp=SharedTasks.setUp
    batch=SharedTasks.batch

    def legacy(self,group=88,kind='detail',themes=None,receipt=True):
        category='road_rescue';base=lib.ROOT/'output'/category/f'group_{group:04d}'
        base.mkdir(parents=True);raws=[]
        for panel in range(3 if kind=='triptych' else 1):
            raw=base/f'raw_{panel}.png';Image.new('RGB',(1024,1536),(panel*30+20,group,100)).save(raw);raws.append(raw)
            if receipt:lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':hashlib.sha256(f'legacy-{group}-{panel}'.encode()).hexdigest(),'raw_sha256':stock.file_hash(raw),'source':{}})
        target=base/f'01_{kind}.png';Image.new('RGB',(1024,1536),'gray').save(target)
        validation={'approved':True,'status':'approved','postprocess_record':{'sources':list(map(str,raws))}}
        if kind=='triptych':validation['panel_service_roles']=themes or ['搭电救援','拖车救援','换胎救援']
        else:validation['service_role']=themes[0] if themes else '拖车救援'
        lib.write(target.with_suffix('.validation.json'),validation)
        file=lib.ROOT/'.runtime/dashboard_delivery_state.json';queue=lib.read(file) if file.exists() else {'projects':{}}
        queue.setdefault('projects',{}).setdefault(category,{}).setdefault('pending_groups',{})[str(group)]={'group_index':group,'paths':[str(target)],'expected_image_count':1}
        lib.write(file,queue);return category,target,raws

    def test_registered_legacy_detail_preserves_evidence_and_needs_qualification(self):
        category,target,raws=self.legacy();original={p:p.read_bytes() for p in [target,target.with_suffix('.validation.json'),raws[0],raws[0].with_suffix('.receipt.json')]}
        result=stock.reindex({'category':category,'batch':'legacy','groups':[88]})
        self.assertEqual(result['registered'],1);self.assertEqual(result['missing_or_adopted'],0)
        asset=stock.load(category,result['items'][0]['asset'])
        self.assertEqual(asset['source']['kind'],'legacy');self.assertEqual(asset['source']['registration']['panel'],1)
        self.assertEqual(asset['eligibility'],'unconfirmed');self.assertEqual(asset['review']['decision'],'unreviewed')
        self.assertEqual(asset['review']['historical_delivery_decision'],'approved')
        self.assertTrue(stock.content_ready(asset));self.assertTrue(all(p.read_bytes()==data for p,data in original.items()))
        repeated=stock.reindex({'category':category,'batch':'legacy','groups':[88]})
        self.assertEqual(repeated['items'][0]['asset'],asset['id'])
        accepted=stock.qualify({'category':category,'asset':asset['id'],'eligible':True,'authorization':'confirm_raw_reuse'})
        self.assertEqual(accepted['qualification']['original_sha256'],asset['original_sha256'])

    def test_unknown_phone_receipt_and_theme_remain_visible_but_not_reusable(self):
        category,_,_=self.legacy(kind='cover',receipt=False)
        result=stock.reindex({'category':category,'batch':'legacy','groups':[88]});asset=stock.load(category,result['items'][0]['asset'])
        self.assertIsNone(asset['phone']);self.assertIsNone(asset['receipt_path']);self.assertIsNone(asset['source']['prompt_sha256'])
        self.assertTrue(stock.valid(asset));self.assertFalse(stock.content_ready(asset))
        visible=stock.view({'category':category})['entries'][0];self.assertFalse(visible['can_qualify']);self.assertTrue(visible['missing_information'])
        with self.assertRaises(ValueError):stock.qualify({'category':category,'asset':asset['id'],'eligible':True,'authorization':'confirm_raw_reuse'})
        self.legacy(group=89,themes=[''])
        second=stock.reindex({'category':category,'batch':'legacy','groups':[89]});detail=stock.load(category,second['items'][0]['asset'])
        self.assertFalse(stock.content_ready(detail))
        forged={**detail,'eligibility':'eligible'};lib.write(stock.index_file(category,detail['id']),forged)
        b=self.batch();rows=lib.selected(lib.batch_dir(category,b['id']),b,[1]);rows[0]['units'][0].update(kind='detail',service_role='')
        self.assertEqual(stock.choose(category,b,rows,100)['actual'],0)

    def test_triptych_sources_and_themes_keep_order_without_inheriting_review(self):
        category,_,raws=self.legacy(kind='triptych')
        result=stock.reindex({'category':category,'batch':'legacy','groups':[88]})
        self.assertEqual(result['registered'],3);self.assertEqual([x['panel'] for x in result['items']],[1,2,3])
        assets=[stock.load(category,x['asset']) for x in result['items']]
        self.assertEqual([x['theme'] for x in assets],['搭电救援','拖车救援','换胎救援'])
        self.assertEqual([x['raw_sha256'] for x in assets],[stock.file_hash(p) for p in raws])
        self.assertTrue(all(x['eligibility']=='unconfirmed' for x in assets))

    def test_shared_index_uses_actual_current_sources_including_selected_old_version(self):
        from tools.task_actions import prepare_replacement
        b=self.batch();category=b['category'];path=lib.batch_dir(category,b['id']);old=lib.selected(path,b,[1])[0]['units'][0]
        child=prepare_replacement({'category':category,'batch':b['id'],'group':1,'position':1,'request_id':'history-index'})
        fresh=lib.selected(lib.batch_dir(category,child['id']),child,[1])[0]['units'][0]
        for batch,unit,color in ((b['id'],old,'gray'),(child['id'],fresh,'blue')):
            raw=lib.unit_raw(category,batch,1,unit);raw.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(1024,1536),color).save(raw)
            lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'source':{}})
        data=lib.read(path/'batch.json');data['replacements']={'1:1':child['id']};lib.write(path/'batch.json',data)
        target=lib.delivery_path(category,b['id'],1,1,'cover');Image.new('RGB',(1024,1536),'gray').save(target)
        for source_batch,source_unit in ((child['id'],fresh),(b['id'],old)):
            lib.write(target.with_suffix('.validation.json'),{'postprocess_record':{'sources':[str(lib.unit_raw(category,source_batch,1,source_unit))]}})
            result=stock.reindex({'category':category,'batch':b['id'],'groups':[1]})
            cover=stock.load(category,next(x['asset'] for x in result['items'] if x['position']==1))
            self.assertEqual(cover['source']['batch'],source_batch)

    def test_missing_bad_records_do_not_hide_good_registered_history(self):
        category,target,raws=self.legacy();self.legacy(group=89)
        bad=lib.ROOT/'output'/category/'group_0089'/'01_detail.validation.json'
        lib.write(bad,{'postprocess_record':{'sources':'not-a-list'}})
        result=stock.reindex({'category':category,'batch':'legacy','groups':[88,89]})
        self.assertEqual(result['registered'],1);self.assertGreater(result['missing_or_adopted'],0);self.assertTrue(result['issues'])
        raw_receipt=raws[0].with_suffix('.receipt.json');original=raw_receipt.read_bytes()
        with self.assertRaises(ValueError):stock.reindex({'category':category,'batch':'legacy','groups':[88],'path':'outside'})
        self.assertEqual(raw_receipt.read_bytes(),original)

    def test_cross_project_source_is_rejected_before_reading(self):
        category,target,_=self.legacy();other=lib.ROOT/'output'/'truck_rescue'/'raw.png';other.parent.mkdir(parents=True);Image.new('RGB',(1024,1536),'red').save(other)
        lib.write(target.with_suffix('.validation.json'),{'postprocess_record':{'sources':[str(other)]}})
        result=stock.reindex({'category':category,'batch':'legacy','groups':[88]})
        self.assertEqual(result['registered'],0);self.assertTrue(result['issues'])

    def test_legacy_registered_shared_revision_keeps_frozen_contact(self):
        from tools.task_actions import prepare_replacement
        category,target,_=self.legacy(kind='cover');b=self.batch()
        child=prepare_replacement({'category':category,'batch':b['id'],'group':1,'position':1,'request_id':'legacy-shared-source'})
        path=lib.batch_dir(category,child['id']);data=lib.read(path/'batch.json')
        data['replacement']={'batch':'legacy','group':88,'position':1};lib.write(path/'batch.json',data)
        unit=lib.selected(path,data,[1])[0]['units'][0];raw=lib.unit_raw(category,data['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(1024,1536),'green').save(raw)
        lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'source':{}})
        lib.write(target.with_suffix('.validation.json'),{'postprocess_record':{'sources':[str(raw)]}})
        result=stock.reindex({'category':category,'batch':'legacy','groups':[88]});asset=stock.load(category,result['items'][0]['asset'])
        self.assertEqual(asset['source']['batch'],child['id']);self.assertEqual(asset['phone'],child['phone'])
        self.assertEqual(asset['eligibility'],'unconfirmed')
        lib.write(target.with_suffix('.validation.json'),{'mock':True,'postprocess_record':{'sources':[str(raw)]}})
        flagged=stock.reindex({'category':category,'batch':'legacy','groups':[88]})
        self.assertFalse(stock.content_ready(stock.load(category,flagged['items'][0]['asset'])))

    def test_provider_original_cannot_bypass_project_boundary(self):
        from unittest.mock import patch
        b=self.batch();category=b['category'];unit=lib.selected(lib.batch_dir(category,b['id']),b,[1])[0]['units'][0]
        raw=lib.unit_raw(category,b['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(1024,1536),'gray').save(raw)
        other=lib.ROOT/'output'/'truck_rescue'/'foreign.png';other.parent.mkdir(parents=True);Image.new('RGB',(1024,1536),'red').save(other)
        lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'source':{'provider_original':str(other),'source_sha256':stock.file_hash(other)}})
        real_hash=stock.file_hash
        def checked_hash(path):
            self.assertNotEqual(lib.io_path(path).resolve(),other.resolve(),'foreign file must not be read')
            return real_hash(path)
        with patch.object(stock,'file_hash',side_effect=checked_hash):
            with self.assertRaises(ValueError):stock.register(category,b['id'],1,unit)
            result=stock.reindex({'category':category,'batch':b['id'],'groups':[1]})
        self.assertEqual(result['registered'],0);self.assertTrue(result['issues'])

    def test_mock_delivery_and_bad_legacy_row_are_isolated(self):
        category,target,_=self.legacy();self.legacy(group=89)
        file=lib.ROOT/'.runtime/dashboard_delivery_state.json';data=lib.read(file)
        data['projects'][category]['pending_groups']['bad']={'paths':[]};lib.write(file,data)
        record=lib.read(target.with_suffix('.validation.json'));record['mock']=True;lib.write(target.with_suffix('.validation.json'),record)
        result=stock.reindex({'category':category,'batch':'legacy','groups':[88,89]})
        self.assertEqual(result['registered'],2);self.assertTrue(result['issues'])
        asset=stock.load(category,next(i['asset'] for i in result['items'] if i['group']==88))
        self.assertIn('模拟素材不能自动复用',asset['missing_information']);self.assertFalse(stock.content_ready(asset))
        with self.assertRaises(ValueError):stock.qualify({'category':category,'asset':asset['id'],'eligible':True,'authorization':'confirm_raw_reuse'})

    def test_unrelated_damaged_revision_does_not_block_current_source(self):
        from tools.task_actions import prepare_replacement
        b=self.batch();category=b['category'];path=lib.batch_dir(category,b['id']);unit=lib.selected(path,b,[1])[0]['units'][0]
        raw=lib.unit_raw(category,b['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(1024,1536),'gray').save(raw)
        lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'source':{}})
        child=prepare_replacement({'category':category,'batch':b['id'],'group':1,'position':1,'request_id':'unused-bad'})
        childpath=lib.batch_dir(category,child['id']);lib.write(childpath/'groups/0001.json',{'units':[]})
        invalid=lib.category_dir(category)/'batch_revision_invalid';lib.write(invalid/'batch.json',[])
        result=stock.reindex({'category':category,'batch':b['id'],'groups':[1]})
        self.assertEqual(result['registered'],1);self.assertTrue(result['issues'])

    def test_shared_receipt_mock_cannot_qualify(self):
        b=self.batch();category=b['category'];unit=lib.selected(lib.batch_dir(category,b['id']),b,[1])[0]['units'][0]
        raw=lib.unit_raw(category,b['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(1024,1536),'gray').save(raw)
        lib.write(raw.with_suffix('.receipt.json'),{'mock':True,'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'source':{}})
        asset=stock.register(category,b['id'],1,unit)
        self.assertFalse(stock.content_ready(asset))
        with self.assertRaises(ValueError):stock.qualify({'category':category,'asset':asset['id'],'eligible':True,'authorization':'confirm_raw_reuse'})

    def test_linked_adoption_and_inheritance_sidecars_not_read(self):
        import os
        from unittest.mock import patch
        from tools import task_worker as worker
        b=self.batch();category=b['category'];unit=lib.selected(lib.batch_dir(category,b['id']),b,[1])[0]['units'][0]
        raw=lib.unit_raw(category,b['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(1024,1536),'gray').save(raw)
        lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'source':{}})
        foreign=lib.ROOT/'output'/'truck_rescue'/'foreign.json';foreign.parent.mkdir(parents=True);lib.write(foreign,{'private_marker':'do-not-read'})
        for suffix in ('.adoption.json','.inherited.json'):
            link=raw.with_suffix(suffix)
            try:os.symlink(foreign,link)
            except OSError as error:self.skipTest('无法创建文件链接：'+type(error).__name__)
            actual_read=lib.read
            def guarded(path):
                self.assertNotEqual(lib.io_path(path).resolve(),foreign.resolve(),'external proof must not be read')
                return actual_read(path)
            with patch.object(lib,'read',side_effect=guarded):
                self.assertFalse(worker.raw_evidence_valid(raw,unit))
                with self.assertRaises(ValueError):stock.register(category,b['id'],1,unit)
                self.assertFalse(stock.adoption_valid(raw,unit) if suffix=='.adoption.json' else stock.inheritance_valid(raw,unit))
            link.unlink()

    def test_junction_raw_directory_is_rejected_before_image_or_proof_read(self):
        import os,subprocess
        from unittest.mock import patch
        from tools import task_worker as worker
        if os.name!='nt':self.skipTest('Windows目录联接测试')
        b=self.batch();category=b['category'];unit=lib.selected(lib.batch_dir(category,b['id']),b,[1])[0]['units'][0]
        raw=lib.unit_raw(category,b['id'],1,unit);raw.parent.parent.mkdir(parents=True,exist_ok=True)
        foreign=lib.ROOT/'output'/'truck_rescue'/'foreign-dir';foreign.mkdir(parents=True)
        Image.new('RGB',(1024,1536),'red').save(foreign/raw.name)
        lib.write((foreign/raw.name).with_suffix('.adoption.json'),{'private_marker':'do-not-read'})
        command="New-Item -ItemType Junction -Path '"+str(raw.parent).replace("'","''")+"' -Target '"+str(foreign).replace("'","''")+"' -ErrorAction Stop | Out-Null"
        result=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,'目录联接必须真实建立')
        self.assertEqual(raw.resolve().parent,foreign.resolve())
        with patch.object(worker.images,'valid_png',side_effect=AssertionError('不得先读取外部图片')):
            self.assertFalse(worker.raw_evidence_valid(raw,unit))
            with self.assertRaises(ValueError):stock.register(category,b['id'],1,unit)


if __name__=='__main__':unittest.main()
