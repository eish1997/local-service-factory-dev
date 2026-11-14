from pathlib import Path
import io
import unittest
import zipfile
from PIL import Image
from unittest.mock import patch
from tools import task_library as lib, task_assets as assets, task_worker as worker, task_actions
from tests import test_shared_tasks as shared


class AssetTasks(unittest.TestCase):
    setUp=shared.SharedTasks.setUp
    batch=shared.SharedTasks.batch
    request=shared.SharedTasks.request
    ready=shared.SharedTasks.ready

    def test_location_freezes_and_exports_only_complete_selected_images(self):
        old=self.batch()
        destination=self.root/'export';destination.mkdir()
        newroot=self.root.parent/(self.root.name+'-assets');newroot.mkdir()
        assets.save({'path':str(newroot.resolve())})
        b=self.batch(count=2)
        self.assertEqual(lib.output_dir(old['category'],old['id']).parents[2],self.root/'output')
        self.assertEqual(lib.output_dir(b['category'],b['id']).parents[2],newroot)
        request={**self.request(b,[1]),'destination':str(destination.resolve())}
        with self.assertRaisesRegex(ValueError,'未齐'):assets.package(request)
        for row in lib.selected(lib.batch_dir(b['category'],b['id']),b,[1]):
            for unit in row['units']:
                kind='triptych' if unit['kind']=='triptych_panel' else unit['kind']
                file=lib.delivery_path(b['category'],b['id'],1,unit['delivery_position'],kind)
                file.parent.mkdir(parents=True,exist_ok=True)
                Image.new('RGB',(4,4),'gray').save(file)
            (file.parent/'private.json').write_text('excluded')
            from tools.image_versions import publish_finished_png
            for png in file.parent.glob('*.png'):publish_finished_png(png,b['category'])
        first=assets.package(request);second=assets.package(request)
        self.assertNotEqual(first['path'],second['path'])
        with zipfile.ZipFile(first['path']) as z:
            self.assertEqual(len(z.namelist()),5)
            self.assertTrue(all(n.startswith(f'road_rescue/{b["id"]}/group_0001/') and n.endswith('.png') for n in z.namelist()))
            self.assertIsNone(z.testzip())
        with patch('tools.dashboard_delivery.DEFAULT_MAX_ARCHIVE_BYTES',69000):
            split=assets.package(request)
        self.assertGreater(len(split['paths']),1)
        names=[]
        for file in split['paths']:
            with zipfile.ZipFile(file) as z:names.extend(z.namelist())
        self.assertEqual(len(set(names)),5)
        with self.assertRaisesRegex(ValueError,'未齐'):assets.package({**request,'groups':None})
        folder=assets.open_folder({**request,'scope':'image','group':1,'position':1})
        self.assertEqual(len(list(lib.io_path(Path(folder['path'])).iterdir())),5)
        self.assertTrue(all(p.suffix=='.png' for p in lib.io_path(Path(folder['path'])).iterdir()))
        task_actions.delete({**request,'scope':'group','group':1,'authorization':'delete_selected'})
        self.assertFalse((lib.output_dir(b['category'],b['id'])/'group_0001').exists())

    def test_unregistered_path_and_invalid_settings_rejected(self):
        with self.assertRaises(ValueError):assets.save({'path':str(self.root)})
        with self.assertRaises(ValueError):assets.save({'path':'relative'})
        b=self.batch();b['asset_root']=str(self.root.parent/'not-registered')
        with self.assertRaises(ValueError):assets.batch_root(b)
        with self.assertRaises(ValueError):task_actions.confined(self.root.parent/'unowned')

    def test_worker_materializes_external_assets(self):
        target=self.root.parent/(self.root.name+'-assets');target.mkdir()
        assets.save({'path':str(target.resolve())});b=self.batch();request=self.request(b,[1])
        with self.ready(),patch.object(lib,'launch',return_value=99999999):
            plan=lib.plan(request)
            state=lib.start({**request,'plan_sha256':plan['plan_sha256'],'authorization':'execute_selected_groups','request_id':'external'})
        payload=io.BytesIO();Image.new('RGB',(1024,1536),'gray').save(payload,format='PNG')
        worker.run(b['category'],b['id'],state['id'],generate=lambda *args:payload.getvalue(),clients=[(1,object())])
        view=lib.view(request)
        self.assertEqual(len(view['groups'][0]['images']),5)
        self.assertTrue(all(str(target) in r['path'] for r in view['groups'][0]['images']))
        group_dir=Path(view['groups'][0]['images'][0]['path']).parent
        self.assertEqual(sorted(p.name for p in group_dir.iterdir()),['01_cover.png','02_triptych.png','03_detail.png','04_detail.png','05_detail.png'])

    @unittest.skipUnless(__import__('os').name=='nt','Windows extended paths')
    def test_custom_asset_root_over_300_registers_and_preserves_public_paths(self):
        from tools import raw_library as stock
        target=self.root/'中文资产'/('a'*72)/('b'*72)/('c'*72)
        self.assertGreater(len(str(target)),300);lib.io_path(target).mkdir(parents=True)
        settings=assets.save({'path':str(target)})
        self.assertEqual(settings['path'],str(target));self.assertFalse(settings['path'].startswith('\\\\?\\'))
        old=self.batch();row=lib.selected(lib.batch_dir(old['category'],old['id']),old,[1])[0]
        unit=row['units'][0];raw=lib.unit_raw(old['category'],old['id'],1,unit)
        lib.io_path(raw.parent).mkdir(parents=True);Image.new('RGB',(1024,1536),'gray').save(lib.io_path(raw))
        lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':stock.file_hash(raw)})
        asset=stock.register(old['category'],old['id'],1,unit);self.assertTrue(stock.valid(asset))
        for key in ('path','original_path','receipt_path'):self.assertFalse(asset[key].startswith('\\\\?\\'))
        for pos in {u['delivery_position'] for u in row['units']}:
            kind='triptych' if pos==2 else 'cover' if pos==1 else 'detail'
            png=lib.delivery_path(old['category'],old['id'],1,pos,kind)
            lib.io_path(png.parent).mkdir(parents=True,exist_ok=True);Image.new('RGB',(4,4),'blue').save(lib.io_path(png))
        self.assertEqual(len(lib.view(self.request(old,[1]))['groups'][0]['images']),5)
        exported=assets.package({**self.request(old,[1]),'destination':str(target)})
        self.assertFalse(exported['path'].startswith('\\\\?\\'))
        with zipfile.ZipFile(lib.io_path(exported['path'])) as archive:self.assertEqual(len(archive.infolist()),5);self.assertIsNone(archive.testzip())
        from tools.image_versions import publish_finished_png
        for png in lib.io_glob(raw.parent.parent,'*.png'):publish_finished_png(png,old['category'])
        self.assertEqual(len(list(lib.io_path(Path(assets.open_folder({**self.request(old,[1]),'scope':'group','group':1})['path'])).iterdir())),5)
        switched=self.root/'short-assets';switched.mkdir();assets.save({'path':str(switched)})
        roots=stock.folder({'category':old['category']})['roots']
        prior=next(r for r in roots if str(target) in r['path'])
        self.assertFalse(prior['current']);self.assertEqual(stock.folder({'category':old['category'],'root_id':prior['id']})['path'],prior['path'])
        self.assertTrue(stock.valid(stock.load(old['category'],asset['id'])))

    def images_for(self,b,group):
        written=[]
        row=lib.selected(lib.batch_dir(b['category'],b['id']),b,[group])[0]
        for unit in row['units']:
            kind='triptych' if unit['kind']=='triptych_panel' else unit['kind']
            file=lib.delivery_path(b['category'],b['id'],group,unit['delivery_position'],kind)
            if file not in written:
                file.parent.mkdir(parents=True,exist_ok=True)
                Image.new('RGB',(4,4),'gray').save(file)
                written.append(file)
        return written

    def test_complete_groups_export_when_another_group_is_incomplete(self):
        b=self.batch(count=2);destination=self.root/'export';destination.mkdir()
        complete=self.images_for(b,1)
        statefile=lib.ROOT/'.runtime/dashboard_delivery_state.json'
        pool={f'{b["id"]}:{group}':{'batch_id':b['id'],'group_index':group,'expected_image_count':len(complete),'paths':[]} for group in (1,2)}
        lib.write(statefile,{'schema_version':1,'updated_at':lib.now(),'projects':{b['category']:{'pending_library_groups':pool}},'package_history':[]})
        result=assets.package({**self.request(b,[1,2]),'destination':str(destination.resolve())})
        self.assertEqual(result['incomplete_groups'],[2])
        self.assertEqual(result['groups'],[1])
        with zipfile.ZipFile(result['path']) as z:
            names=z.namelist()
            self.assertTrue(names)
            self.assertTrue(all('/group_0001/' in n for n in names))
            self.assertFalse(any('/group_0002/' in n for n in names))
            self.assertIsNone(z.testzip())
        queued=lib.read(statefile)['projects'][b['category']]['pending_library_groups']
        self.assertIn(f'{b["id"]}:2',queued)
        empty=self.batch(count=2)
        with self.assertRaises(ValueError) as caught:
            assets.package({**self.request(empty,[1,2]),'destination':str(destination.resolve())})
        text=str(caught.exception)
        self.assertIn('第 1 组',text)
        self.assertIn('第 2 组',text)


if __name__=='__main__':unittest.main()
