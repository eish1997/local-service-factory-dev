import subprocess,unittest
from pathlib import Path
from uuid import uuid4
from development.sync_repository import synchronize

class SyncTests(unittest.TestCase):
    def test_release_index_survives_fast_forward_dirty_review_and_merge(self):
        root=Path(__file__).resolve().parents[1]/'.runtime'/('git-sync-'+uuid4().hex);root.mkdir(parents=True)
        def run(*args,cwd=root):
            return subprocess.check_output(['git',*map(str,args)],cwd=cwd,stderr=subprocess.PIPE,text=True).strip()
        remote=root/'remote.git';run('init','--bare',remote)
        local=root/'local';publisher=root/'publisher';run('clone',remote,local)
        for repo in (local,):
            run('config','user.name','Offline Test',cwd=repo);run('config','user.email','offline@example.invalid',cwd=repo)
        (local/'code.txt').write_text('base');run('add','code.txt',cwd=local);run('commit','-m','base',cwd=local);run('push','-u','origin','HEAD',cwd=local)
        run('clone',remote,publisher);run('config','user.name','Offline Test',cwd=publisher);run('config','user.email','offline@example.invalid',cwd=publisher)
        index=b'{"signature":"isolated fixture","payload":{"version":"200"}}'
        (publisher/'release-index.json').write_bytes(index);run('add','release-index.json',cwd=publisher);run('commit','-m','Publish rules',cwd=publisher);run('push',cwd=publisher)
        self.assertEqual(synchronize(local)['state'],'fast_forwarded');self.assertEqual((local/'release-index.json').read_bytes(),index)
        (local/'code.txt').write_text('local edit')
        new=index.replace(b'200',b'201');(publisher/'release-index.json').write_bytes(new);run('commit','-am','next rules',cwd=publisher);run('push',cwd=publisher)
        self.assertEqual(synchronize(local)['state'],'review_required');self.assertEqual((local/'code.txt').read_text(),'local edit');self.assertEqual((local/'release-index.json').read_bytes(),index)
        run('commit','-am','reviewed source',cwd=local)
        self.assertEqual(synchronize(local)['state'],'review_required')
        run('merge','--no-edit','@{upstream}',cwd=local)
        self.assertEqual((local/'release-index.json').read_bytes(),new);self.assertEqual((local/'code.txt').read_text(),'local edit')
