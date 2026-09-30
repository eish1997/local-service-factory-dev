import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from PIL import Image
from tools import image_review
import factory


class ImageReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'output'
        self.output.mkdir()
        self.records = []
        for index in range(2):
            path = self.output / f'{index}.png'
            Image.new('RGB', (128, 192), (50, 90, 130)).save(path)
            validation = {'status': 'needs_user_review', 'approved': False,
                          'manual_visual_approval': False, 'postprocessed_locally': True,
                          'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            path.with_suffix('.validation.json').write_text(json.dumps(validation))
            self.records.append(dict(target=str(path), group_index=index+1,
                                     delivery_kind='detail', final_size='128x192'))
        self.callback = Mock()
        self.session = image_review.ReviewSession(self.records, self.output, self.root / 'reports', self.callback)

    def test_manual_mode_does_not_run_fingerprints(self):
        with patch.object(image_review.inventory, 'image_fingerprint') as fingerprint:
            state = self.session.state()
            self.assertEqual(state['tool']['status'], 'not_run')
            fingerprint.assert_not_called()

    def test_tool_detects_duplicates_without_mutating_approval(self):
        before = [Path(r['target']).with_suffix('.validation.json').read_bytes() for r in self.records]
        self.session.run_tool()
        report = self.session.tool_state
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['pairs'][0]['kind'], 'exact_duplicate')
        self.assertFalse(report['visual_approval'])
        self.assertEqual(before, [Path(r['target']).with_suffix('.validation.json').read_bytes() for r in self.records])
        self.callback.assert_not_called()

    def test_corrupt_missing_size_and_hash_mismatch_are_reported(self):
        Path(self.records[0]['target']).write_bytes(b'corrupt')
        self.records[1]['final_size'] = '1x1'
        self.session.records[1]['size'] = '1x1'
        vp=Path(self.records[1]['target']).with_suffix('.validation.json')
        v=json.loads(vp.read_text(encoding='utf-8'));v['image_sha256']='wrong';vp.write_text(json.dumps(v))
        self.session.run_tool()
        rows=self.session.tool_state['checks']
        self.assertTrue(rows[0]['problems'])
        self.assertEqual(len(rows[1]['problems']), 2)

    def test_manual_approval_requires_view_and_matching_hash(self):
        with self.assertRaises(ValueError):
            self.session.decide(0, 'approved', '已核对', None)
        data=self.session.image_bytes(0)
        digest=hashlib.sha256(data).hexdigest()
        self.session.decide(0, 'approved', '已核对电话、场景和动作', digest)
        vp=Path(self.records[0]['target']).with_suffix('.validation.json')
        self.assertTrue(json.loads(vp.read_text(encoding='utf-8'))['manual_visual_approval'])
        event=json.loads(next(self.session.directory.glob('manual_*.json')).read_text(encoding='utf-8'))
        self.assertFalse(event['previous_validation']['approved'])
        self.assertTrue(event['applied'])

    def test_changed_image_cannot_be_approved_from_old_view(self):
        digest=hashlib.sha256(self.session.image_bytes(0)).hexdigest()
        Image.new('RGB', (128,192), 'red').save(self.records[0]['target'])
        self.session.image_bytes(0)
        with self.assertRaises(ValueError):
            self.session.decide(0, 'approved', '已核对', digest)

    def test_cover_delegates_to_existing_gate_and_rejection_revokes_approval(self):
        self.session.records[0]['role']='cover'
        digest=hashlib.sha256(self.session.image_bytes(0)).hexdigest()
        self.session.decide(0,'approved','门头及电话已核对',digest)
        self.callback.assert_called_once()
        self.session.decide(0,'rejected','电话错误',digest)
        value=json.loads(Path(self.records[0]['target']).with_suffix('.validation.json').read_text(encoding='utf-8'))
        self.assertFalse(value['approved'])
        self.assertFalse(value['manual_visual_approval'])

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            image_review.ReviewSession([dict(self.records[0],target=str(self.root/'outside.png'))],
                                      self.output,self.root/'reports')

    def test_public_modes_parse(self):
        for mode in ('manual','tool'):
            args=factory.build_parser().parse_args(['review-category-images','--category','road_rescue',
                '--group-start','316','--group-count','3','--mode',mode])
            self.assertEqual(args.handler,factory.command_review_category_images)

    def test_server_requires_token_and_same_origin_for_writes(self):
        server=image_review.serve(self.session)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            with self.assertRaises(HTTPError) as error:
                urlopen(base+'/state')
            self.assertEqual(error.exception.code,403)
            query='?token='+self.session.token
            with urlopen(base+'/state'+query) as r:
                self.assertEqual(json.load(r)['tool']['status'],'not_run')
            request=Request(base+'/tool'+query,data=b'{}',headers={'Content-Type':'application/json','Origin':'https://example.com'})
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code,403)
            with urlopen(base+'/'+query) as r:
                self.assertIn('人工验收',r.read().decode())
            with urlopen(base+'/image/0'+query) as r:
                digest=r.headers['X-Image-SHA256'];r.read()
            payload={'id':0,'decision':'approved','note':'已人工核对','confirmed':False,'viewed_sha256':digest}
            headers={'Content-Type':'application/json','Origin':base}
            with self.assertRaises(HTTPError):
                urlopen(Request(base+'/decision'+query,data=json.dumps(payload).encode(),headers=headers))
            payload['confirmed']=True
            with urlopen(Request(base+'/decision'+query,data=json.dumps(payload).encode(),headers=headers)) as r:
                self.assertTrue(json.load(r)['saved'])
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    unittest.main()
