"""Both real publisher paths against one stateful, offline GitHub fixture."""
import base64,json,os,unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from tools import software_release as software,rule_updates as rules

class InterleavingTests(unittest.TestCase):
    def test_both_orders_keep_software_latest(self):
        for order in (('software','rules'),('rules','software')):
            with self.subTest(order=order):self.exercise(order)

    def exercise(self,order):
        root=software.paths.CODE_ROOT/'.runtime'/('interleave-'+uuid4().hex);root.mkdir(parents=True)
        cfg={'owner':'test','software_repo':'unified','rules_repo':'unified','app_version':'1.4.18','public_keys':{},'max_rules_bytes':1024}
        files={}
        for name in ['LocalServiceFactory-1.4.18-setup.exe','LocalServiceFactory-1.4.18-setup.exe.blockmap','latest.yml']:
            (root/name).write_bytes(name.encode());files[name]=software.protocol.sha(name.encode())
        (root/'build-provenance.json').write_text(json.dumps({'schema_version':1,'source_sha':'a'*40,'version':'1.4.18','repository':{'owner':'test','repo':'unified'},'files':files}),encoding='utf-8')
        folder=root/'release_plans/200';folder.mkdir(parents=True)
        payload={'source_sha':'a'*40,'version':'200','files':{},'sha256':software.protocol.sha(b'rules'),'url':'https://github.com/test/unified/releases/download/rules-200/rules.zip'}
        (folder/'payload.json').write_text(json.dumps(payload),encoding='utf-8');(folder/'rules.zip').write_bytes(b'rules')
        (folder/'plan.json').write_text(json.dumps({'source_sha':'a'*40,'repository':rules.repository_identity(cfg),'base_sha':None,'validated':True}),encoding='utf-8')
        releases={};tags={};state={'latest':None,'head':None,'lock':False}
        def github(method,url,body=None,raw=None):
            if method=='GET':
                if '/commits/' in url:return {'sha':'a'*40}
                if '/git/ref/heads/' in url:return {'object':{'sha':'b'*40}}
                if '/git/ref/tags/' in url:return tags.get(url.rsplit('/',1)[1])
                if url.endswith('/releases/latest'):return state['latest']
                if '/releases/tags/' in url:return next((r for r in releases.values() if r['tag_name']==url.rsplit('/',1)[1]),None)
                if '/contents/' in url:return state['head']
                return {'default_branch':'main'}
            if raw is not None:
                ident,name=url.split('/assets?name=');releases[int(ident.rsplit('/',1)[1])]['uploads'][name]=raw;return {}
            if method=='POST' and url.endswith('/git/refs'):
                self.assertFalse(state['lock']);state['lock']=True;return {}
            if method=='POST' and url.endswith('/releases'):
                ident=len(releases)+1;r={**body,'id':ident,'uploads':{},'upload_url':f'https://uploads.github.com/{ident}/assets{{?name}}','html_url':'fixture'};releases[ident]=r;tags[body['tag_name']]={'object':{'sha':body['target_commitish']}};return r
            if method=='PATCH':
                r=releases[int(url.rsplit('/',1)[1])];r.update(body)
                if body.get('make_latest')=='true':state['latest']=r
                return r
            if method=='PUT':
                self.assertEqual(body.get('sha'),None);state['head']={'sha':'index-sha','content':body['content']};return {'content':{'sha':'index-sha'}}
            if method=='DELETE':state['lock']=False;return {}
            raise AssertionError((method,url))
        def download(url,*args,**kwargs):
            tag,name=url.split('/download/')[1].split('/')
            return next(r for r in releases.values() if r['tag_name']==tag)['uploads'][name]
        with patch.dict(os.environ,{},clear=True),patch.object(software.paths,'config',return_value=cfg),patch.object(rules,'local',return_value=root),patch.object(rules,'validate_payload'),patch.object(software.protocol,'github',side_effect=github),patch.object(software.protocol,'download',side_effect=download),patch.object(software.protocol,'sign',side_effect=lambda p,*a:{'payload':p}),patch.object(software.protocol,'verify',side_effect=lambda e,*a:e['payload']):
            for kind in order:
                if kind=='software':software.publish({**software.release_plan({'directory':str(root)}),'authorization':'publish_software_update'})
                else:rules.publish({'version':'200','authorization':'publish_project_update'})
        self.assertEqual(state['latest']['tag_name'],'v1.4.18');self.assertFalse(state['lock'])
        index=json.loads(base64.b64decode(state['head']['content']))['payload'];self.assertEqual(index,payload)
        self.assertTrue(all(r['target_commitish']=='a'*40 for r in releases.values()))
