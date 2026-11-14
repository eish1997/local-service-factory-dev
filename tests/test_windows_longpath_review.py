"""Independent embedded-Windows long-path I/O and history regression."""
import unittest
from pathlib import Path
from unittest.mock import patch
import uuid
from PIL import Image
from tools import task_library as lib, image_versions as versions


@unittest.skipUnless(__import__('os').name == 'nt', 'Windows extended paths')
class WindowsLongPathReview(unittest.TestCase):
    def setUp(self):
        self.root = lib.ROOT/'.runtime'/('windows-longpath-review-'+uuid.uuid4().hex)
        self.root.mkdir()
        self.guard = patch.object(lib, 'ROOT', self.root)
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_json_io_over_300_and_temp_name_boundary(self):
        base = self.root/('a'*100)/('b'*100)
        for name in ('image.validation.json', 'index.json'):
            target = base/name
            self.assertGreater(len(str(target)), 300)
            lib.write(target, {'path': str(target), 'value': '保留普通元数据路径'})
            self.assertEqual(lib.read(target)['path'], str(target))
            self.assertFalse(lib.read(target)['path'].startswith('\\\\?\\'))

    def test_complete_publish_retains_original_and_new_versions_over_260(self):
        folder = self.root/'output'/'road_rescue'/('photo-'+('a'*130))/'group_0001'
        target = folder/'01_cover.png'
        candidate = folder/'preview.png'
        self.assertGreater(len(str(target)), 260)
        lib.io_path(folder).mkdir(parents=True, exist_ok=True)
        with lib.io_path(target).open('wb') as out:
            Image.new('RGB', (100, 150), 'blue').save(out, format='PNG')
        old = lib.io_path(target).read_bytes()
        lib.write(target.with_suffix('.validation.json'), {'status': 'pending'})
        with lib.io_path(candidate).open('wb') as out:
            Image.new('RGB', (100, 150), 'red').save(out, format='PNG')
        new = lib.io_path(candidate).read_bytes()
        lib.write(candidate.with_suffix('.validation.json'), {'status': 'pending'})
        entry = versions.publish(target, candidate, 'road_rescue', 'review')
        index = lib.read(versions.index_path(target))
        self.assertEqual(len(index['versions']), 2)
        self.assertEqual(lib.io_path(Path(index['versions'][0]['path'])).read_bytes(), old)
        self.assertEqual(lib.io_path(target).read_bytes(), new)
        self.assertEqual(index['current'], entry['id'])
        self.assertTrue(all(not v['path'].startswith('\\\\?\\') for v in index['versions']))
        versions.activate(target, index['versions'][0], 'road_rescue')
        self.assertEqual(lib.io_path(target).read_bytes(), old)

    def test_registered_source_image_over_260_remains_visible(self):
        from tools import postprocess_view
        path = self.root/'output'/'road_rescue'/('source-'+('a'*130))/'raw_1.png'
        self.assertGreater(len(str(path)), 260)
        lib.io_path(path.parent).mkdir(parents=True, exist_ok=True)
        with lib.io_path(path).open('wb') as out:
            Image.new('RGB', (100, 150), 'blue').save(out, format='PNG')
        result = postprocess_view.image(path, 'road_rescue', '来源')
        self.assertTrue(result['exists'])
        self.assertEqual(result['size'], [100, 150])
        self.assertFalse(result['path'].startswith('\\\\?\\'))


if __name__ == '__main__':
    unittest.main()
