"""Offline migration contracts; never call a live release service."""
import os
import unittest
from unittest.mock import patch
from tools import software_release as software

class SetupTests(unittest.TestCase):
    def test_same_repository_is_initialized_once(self):
        cfg={'owner':'test','software_repo':'unified','rules_repo':'unified'}
        with patch.dict(os.environ,{},clear=True), patch.object(software.paths,'config',return_value=cfg), patch.object(software.protocol,'github',side_effect=[{'login':'test'},{'private':False,'html_url':'https://github.com/test/unified'}]) as api:
            result=software.setup({'authorization':'initialize_update_repositories'})
        self.assertEqual(len(result['repositories']),1)
        self.assertEqual(api.call_count,2)
        self.assertTrue(all(c.args[0]=='GET' for c in api.call_args_list))

    def test_private_repository_is_not_made_public(self):
        cfg={'owner':'test','software_repo':'unified','rules_repo':'unified'}
        with patch.dict(os.environ,{},clear=True), patch.object(software.paths,'config',return_value=cfg), patch.object(software.protocol,'github',side_effect=[{'login':'test'},{'private':True}]) as api:
            with self.assertRaises(ValueError):software.setup({'authorization':'initialize_update_repositories'})
        self.assertTrue(all(c.args[0]=='GET' for c in api.call_args_list))

class LatestTests(unittest.TestCase):
    def test_only_stable_software_latest_is_accepted(self):
        software.validate_latest(None,'1.4.18')
        software.validate_latest({'tag_name':'v1.4.17'},'1.4.18')
        for latest in ({'tag_name':'rules-123'}, {'tag_name':'1.4.17'}, {'tag_name':'v1.4.17','draft':True}, {'tag_name':'v1.4.17','prerelease':True}, {'tag_name':'v1.4.18'}, {'tag_name':'v2.0.0'}):
            with self.subTest(latest=latest), self.assertRaises(ValueError):software.validate_latest(latest,'1.4.18')

class RuleRepositoryTests(unittest.TestCase):
    def test_foreign_and_legacy_heads_rejected_before_plan_creation(self):
        import tempfile, json
        from pathlib import Path
        from tools import rule_updates as rules
        cfg={'owner':'test','rules_repo':'unified'}
        from uuid import uuid4
        tmp=rules.paths.CODE_ROOT/'.runtime'/('migration-test-'+uuid4().hex)
        tmp.mkdir(parents=True)
        with patch.object(rules,'local',return_value=tmp), patch.object(rules.paths,'config',return_value=cfg), patch.object(rules,'export_documents') as export:
            file=Path(tmp)/'remote_head.json'
            for head in ({'sha':'old'}, {'sha':'old','repository':{'owner':'test','repo':'old'}}):
                original=json.dumps(head);file.write_text(original,encoding='utf-8')
                with self.assertRaises(ValueError):rules.release_plan({'version':'200'})
                self.assertEqual(file.read_text(encoding='utf-8'),original)
                export.assert_not_called()
            file.write_text(json.dumps({'sha':'current','repository':rules.repository_identity(cfg)}),encoding='utf-8')
            self.assertEqual(rules.tracked_head(cfg)['sha'],'current')

class SoftwareFailureTests(unittest.TestCase):
    def run_publish(self, latest=None, fail_upload=False, bad_download=False):
        from pathlib import Path
        from uuid import uuid4
        folder=software.paths.CODE_ROOT/'.runtime'/('software-fixture-'+uuid4().hex)
        folder.mkdir(parents=True)
        cfg={'owner':'test','software_repo':'unified','app_version':'1.4.18','public_keys':{'test':'fixture'}}
        names=['LocalServiceFactory-1.4.18-setup.exe','LocalServiceFactory-1.4.18-setup.exe.blockmap','latest.yml']
        for name in names:(folder/name).write_bytes(b'isolated fixture')
        import json
        (folder/'build-provenance.json').write_text(json.dumps({'schema_version':1,'source_sha':'a'*40,'version':'1.4.18','repository':{'owner':'test','repo':'unified'},'files':{name:software.protocol.sha((folder/name).read_bytes()) for name in names}}),encoding='utf-8')
        calls=[]; uploads={}
        def github(method,url,body=None,raw=None):
            calls.append((method,url,body))
            if method=='GET':
                if '/commits/' in url:return {'sha':'a'*40}
                if url.endswith('/releases/latest'):return latest
                if '/git/ref/heads/' in url:return {'object':{'sha':'a'*40}}
                if url.endswith('/unified'):return {'default_branch':'main'}
                return None
            if raw is not None:
                if fail_upload:raise TimeoutError('ambiguous upload')
                uploads[url.split('name=')[1]]=raw
            if url.endswith('/releases'):return {'id':1,'upload_url':'https://uploads.github.com/fixture{?name}','html_url':'fixture'}
            return {}
        def download(url,*args,**kwargs):
            return b'corrupted' if bad_download else uploads[url.rsplit('/',1)[1]]
        with patch.dict(os.environ,{},clear=True), patch.object(software.paths,'config',return_value=cfg), patch.object(software.protocol,'github',side_effect=github), patch.object(software.protocol,'sign',side_effect=lambda payload,*a:{'payload':payload}), patch.object(software.protocol,'verify',side_effect=lambda envelope,*a:envelope['payload']), patch.object(software.protocol,'download',side_effect=download):
            plan=software.release_plan({'directory':str(folder)})
            try:result=software.publish({**plan,'authorization':'publish_software_update'})
            except (ValueError,TimeoutError) as exc:result=exc
        return result,calls

    def test_wrong_latest_has_no_remote_writes(self):
        result,calls=self.run_publish(latest={'tag_name':'rules-200'})
        self.assertIsInstance(result,ValueError)
        self.assertTrue(all(method=='GET' for method,_,_ in calls))

    def test_upload_timeout_and_bad_download_keep_lock_and_latest(self):
        for fault in ({'fail_upload':True},{'bad_download':True}):
            with self.subTest(fault=fault):
                result,calls=self.run_publish(**fault)
                self.assertIsInstance(result,Exception)
                self.assertFalse(any(method=='DELETE' for method,_,_ in calls))
                self.assertFalse(any(body and body.get('make_latest')=='true' for _,_,body in calls))

    def test_verified_assets_precede_latest_and_lock_release(self):
        result,calls=self.run_publish(latest={'tag_name':'v1.4.17'})
        self.assertTrue(result['published'])
        self.assertEqual(calls[-2][2],{'make_latest':'true'})
        self.assertEqual(calls[-1][0],'DELETE')
        release=next(body for method,url,body in calls if method=='POST' and url.endswith('/releases'))
        self.assertEqual(release['target_commitish'],'a'*40)
        self.assertEqual(release['make_latest'],'false')

class RecoveryTests(unittest.TestCase):
    def test_draft_or_foreign_lock_never_reuploads_or_unlocks(self):
        plan={'version':'1.4.18','source_sha':'a'*40,'files':{}}
        cfg={'owner':'test','software_repo':'unified'}
        for lock in (None,{'object':{'sha':'b'*40}},{'object':{'sha':'a'*40}}):
            with patch.dict(os.environ,{},clear=True), patch.object(software.paths,'config',return_value=cfg), patch.object(software,'release_plan',return_value=plan), patch.object(software.protocol,'github',side_effect=[lock,{'draft':True},{'object':{'sha':'a'*40}},None]) as api:
                result=software.recover({'authorization':'finalize_software_recovery'})
            self.assertFalse(result['recoverable'])
            self.assertTrue(all(c.args[0]=='GET' for c in api.call_args_list))

    def test_verified_recovery_only_promotes_and_unlocks(self):
        import json
        plan={'version':'1.4.18','source_sha':'a'*40,'files':{'LocalServiceFactory-1.4.18-setup.exe':'digest'},'directory':'fixture'}
        payload={'kind':'software','source_sha':'a'*40,'version':'1.4.18','sha256':'digest','files':plan['files']}
        release={'id':3,'draft':False,'assets':[{'name':n} for n in [*plan['files'],'software-manifest.json']]}
        from pathlib import Path
        for authorized in (False,True):
            with patch.dict(os.environ,{},clear=True), patch.object(software.paths,'config',return_value={'owner':'test','software_repo':'unified','public_keys':{}}), patch.object(software,'release_plan',return_value=plan), patch.object(software.protocol,'github',side_effect=[{'object':{'sha':'a'*40}},release,{'object':{'sha':'a'*40}},None,{},{}]) as api, patch.object(Path,'stat') as stat, patch.object(software.protocol,'download',side_effect=[b'fixture',json.dumps({'payload':payload}).encode()]), patch.object(software.protocol,'sha',return_value='digest'), patch.object(software.protocol,'verify',return_value=payload):
                stat.return_value.st_size=7
                result=software.recover({**plan,**({'authorization':'finalize_software_recovery'} if authorized else {})})
            mutations=[c.args[0] for c in api.call_args_list if c.args[0]!='GET']
            self.assertEqual(mutations,['PATCH','DELETE'] if authorized else [])
            self.assertFalse(result['uploaded'])

class ProvenanceTests(unittest.TestCase):
    def test_missing_tampered_record_and_changed_artifacts_are_rejected(self):
        import json
        from uuid import uuid4
        folder=software.paths.CODE_ROOT/'.runtime'/('provenance-'+uuid4().hex);folder.mkdir(parents=True)
        cfg={'owner':'test','software_repo':'unified','app_version':'1.4.18'}
        names=['LocalServiceFactory-1.4.18-setup.exe','LocalServiceFactory-1.4.18-setup.exe.blockmap','latest.yml']
        for name in names:(folder/name).write_bytes(b'fixture')
        record={'schema_version':1,'source_sha':'a'*40,'version':'1.4.18','repository':{'owner':'test','repo':'unified'},'files':{n:software.protocol.sha(b'fixture') for n in names}}
        file=folder/'build-provenance.json'
        with patch.object(software.paths,'config',return_value=cfg):
            with self.assertRaises(FileNotFoundError):software.release_plan({'directory':str(folder)})
            for change in ({'source_sha':'invalid'},{'version':'1.4.17'},{'repository':{'owner':'test','repo':'old'}},{'files':{}}):
                file.write_text(json.dumps({**record,**change}),encoding='utf-8')
                with self.assertRaises(ValueError):software.release_plan({'directory':str(folder)})
            file.write_text(json.dumps(record),encoding='utf-8')
            self.assertEqual(software.release_plan({'directory':str(folder)})['source_sha'],'a'*40)
            (folder/names[0]).write_bytes(b'changed')
            with self.assertRaises(ValueError):software.release_plan({'directory':str(folder)})

class ExportBoundaryTests(unittest.TestCase):
    def test_urls_and_javascript_are_not_windows_paths(self):
        from development.export_source import clean_text
        for value in ('https://github.com/${cfg.owner}/${cfg.software_repo}/releases/latest/download/software-manifest.json', "replace(/Error: /g, '')", 'https://example.com/v1'):
            self.assertEqual(clean_text(value),value)
        self.assertEqual(clean_text('C:/Users/example/private.txt'),'<local-path>')

class RuleFailureTests(unittest.TestCase):
    def test_duplicate_upload_failure_and_manifest_mismatch_preserve_index(self):
        import json
        from uuid import uuid4
        from tools import rule_updates as rules
        root=software.paths.CODE_ROOT/'.runtime'/('rule-fault-'+uuid4().hex)
        folder=root/'release_plans/200';folder.mkdir(parents=True)
        cfg={'owner':'test','rules_repo':'unified','public_keys':{},'max_rules_bytes':1024}
        payload={'source_sha':'a'*40,'version':'200','url':'https://github.com/test/unified/releases/download/rules-200/rules.zip','sha256':software.protocol.sha(b'fixture'),'files':{}}
        (folder/'rules.zip').write_bytes(b'fixture')
        (folder/'payload.json').write_text(json.dumps(payload),encoding='utf-8')
        (folder/'plan.json').write_text(json.dumps({'source_sha':'a'*40,'repository':rules.repository_identity(cfg),'validated':True,'base_sha':None}),encoding='utf-8')
        for fault in ('duplicate','timeout','manifest'):
            calls=[]
            def github(method,url,body=None,raw=None):
                calls.append((method,url,body))
                if method=='GET':return {'sha':'a'*40} if '/commits/' in url else {'object':{'sha':'existing'}} if fault=='duplicate' and '/git/ref/' in url else None
                if raw is not None and fault=='timeout':raise TimeoutError('uncertain upload')
                if method=='POST' and url.endswith('/releases'):return {'id':1,'upload_url':'https://uploads.github.com/fixture{?name}'}
                return {}
            with patch.dict(os.environ,{},clear=True), patch.object(rules,'local',return_value=root), patch.object(rules.paths,'config',return_value=cfg), patch.object(rules,'validate_payload'), patch.object(rules.protocol,'sign',return_value={'payload':payload}), patch.object(rules.protocol,'verify',return_value={'wrong':'manifest'}), patch.object(rules.protocol,'download',side_effect=[b'fixture',b'{}']), patch.object(rules.protocol,'github',side_effect=github):
                with self.assertRaises((ValueError,TimeoutError)):rules.publish({'version':'200','authorization':'publish_project_update'})
            self.assertFalse(any(method=='PUT' for method,_,_ in calls))
            self.assertFalse(any(body and body.get('make_latest')=='true' for _,_,body in calls))
            if fault=='duplicate':self.assertTrue(all(method=='GET' for method,_,_ in calls))
            self.assertFalse((root/'remote_head.json').exists())

class StaticAssetTests(unittest.TestCase):
    def test_offline_icons_have_valid_svg_namespace_and_brand_assets(self):
        import xml.etree.ElementTree as ET
        root=software.paths.CODE_ROOT/'dashboard'
        icons=[root/'branding/logo.svg',*(root/'renderer/vendor/lucide').glob('*.svg')]
        self.assertGreater(len(icons),1)
        for icon in icons:
            self.assertEqual(ET.parse(icon).getroot().tag,'{http://www.w3.org/2000/svg}svg',str(icon))
        self.assertTrue((root/'branding/logo.png').read_bytes().startswith(bytes([137,80,78,71])))
        self.assertTrue((root/'branding/logo.ico').read_bytes().startswith(bytes([0,0,1,0])))
