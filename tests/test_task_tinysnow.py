import io
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from PIL import Image
from tools import task_library as lib, task_worker as worker


class TinySnowTasks(unittest.TestCase):
    def config(self):
        with patch('factory.effective_api_config',return_value={
            'provider':'relay','base_url':'https://tinysnow.one/v1',
            'model':'gpt-image-2-4k','quality':'medium','api_size':'1024x1536','output_format':'png'}):
            return lib.api_config()

    def test_default_contract_and_wrong_provider(self):
        cfg=self.config()
        self.assertEqual(cfg['api_size'],'2560x3840')
        self.assertEqual(cfg['raw_contract'],'tinysnow_2336_2352x3520_to_legacy_v1')
        with patch('factory.effective_api_config',return_value={**cfg,'base_url':'https://other.example/v1'}):
            with self.assertRaises(ValueError):lib.api_config()

    def test_actual_source_contract_archives_and_normalizes(self):
        root=Path('.runtime')/('test-shared-4k-'+uuid4().hex)
        root.mkdir(parents=True)
        for width in (2336,2352,2340):
            data=io.BytesIO();Image.new('RGB',(width,3520),'gray').save(data,format='PNG')
            raw=root/str(width)/'raw.png';raw.parent.mkdir()
            if width==2340:
                with self.assertRaises(Exception):worker.save_task_raw(raw,data.getvalue(),self.config(),'cover')
                self.assertFalse(raw.exists())
            else:
                result=worker.save_task_raw(raw,data.getvalue(),self.config(),'cover')
                with Image.open(raw) as image:self.assertEqual(image.size,(1024,1536))
                self.assertTrue(result)
            self.assertTrue(any(p.is_file() and p.read_bytes()==data.getvalue() for p in (raw.parent/'originals').rglob('*')))


if __name__=='__main__':unittest.main()
