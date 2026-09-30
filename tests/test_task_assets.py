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
        self.assertEqual(folder['path'],str(lib.output_dir(b['category'],b['id'])/'group_0001'))
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


if __name__=='__main__':unittest.main()
