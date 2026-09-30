"""Explicit software release publishing, separate from rule publication."""
import base64
import json
import os
from pathlib import Path
from tools import runtime_paths as paths, update_protocol as protocol

def setup(request):
    if request.get('authorization')!='initialize_update_repositories' or os.environ.get('FACTORY_DATA_HOME'):raise ValueError('初始化仓库需要维护端明确指令')
    cfg=paths.config();user=protocol.github('GET','/user');result=[]
    for repo in (cfg['software_repo'],cfg['rules_repo']):
        existing=protocol.github('GET',f'/repos/{cfg["owner"]}/{repo}')
        if existing:
            if existing.get('private'):raise ValueError('分发仓库必须公开，不能自动改变现有仓库权限')
            result.append(existing['html_url']);continue
        endpoint='/user/repos' if user['login'].lower()==cfg['owner'].lower() else '/orgs/'+cfg['owner']+'/repos'
        created=protocol.github('POST',endpoint,{'name':repo,'private':False,'auto_init':True,'description':'Local Service Image Factory official distribution'})
        result.append(created['html_url'])
    return {'repositories':result,'published_release':False}

def release_plan(request):
    cfg=paths.config();version=cfg['app_version'];folder=Path(request['directory']).resolve()
    names=[f'LocalServiceFactory-{version}-setup.exe',f'LocalServiceFactory-{version}-setup.exe.blockmap','latest.yml']
    if not all((folder/n).is_file() for n in names):raise ValueError('缺少安装包、差分文件或 latest.yml，请先明确授权构建')
    files={name:protocol.sha((folder/name).read_bytes()) for name in names}
    return {'version':version,'directory':str(folder),'files':files,'uploaded':False}

def publish(request):
    if request.get('authorization')!='publish_software_update' or os.environ.get('FACTORY_DATA_HOME'):raise ValueError('软件发布只允许维护端在明确发布指令后执行')
    cfg=paths.config();plan=release_plan(request)
    if request.get('files')!=plan['files']:raise ValueError('构建产物已变化，请重新检查发布计划')
    version=plan['version'];repo=f'/repos/{cfg["owner"]}/{cfg["software_repo"]}'
    payload={'kind':'software','version':version,'sha256':plan['files'][f'LocalServiceFactory-{version}-setup.exe'],'files':plan['files']}
    envelope=protocol.sign(payload,os.environ.get('FACTORY_RELEASE_KEY_ID') or 'release-2026-09',
                           os.environ.get('FACTORY_RELEASE_KEY_FILE') or paths.data_root()/'.runtime/private/release-signing.pem',cfg['public_keys'])
    # Creating a unique Git ref is an atomic publishing lock; leave it for explicit recovery on error.
    metadata=protocol.github('GET',repo)
    if not metadata or not metadata.get('default_branch'):raise ValueError('请先初始化软件发布仓库')
    ref=protocol.github('GET',repo+'/git/ref/heads/'+metadata['default_branch'])
    if not ref:raise ValueError('软件仓库默认分支不存在')
    protocol.github('POST',repo+'/git/refs',{'ref':'refs/tags/software-publish-lock','sha':ref['object']['sha']})
    latest=protocol.github('GET',repo+'/releases/latest')
    if latest:
        from tools.rule_updates import app_tuple
        if app_tuple(latest['tag_name'].removeprefix('v'))>=app_tuple(version):raise ValueError('软件版本必须高于已发布版本，请检查发布计划与锁')
    release=protocol.github('POST',repo+'/releases',{'tag_name':'v'+version,'name':'软件 '+version,'draft':True})
    upload=release['upload_url'].split('{')[0]
    for name in plan['files']:protocol.github('POST',upload+'?name='+name,raw=(Path(plan['directory'])/name).read_bytes())
    protocol.github('POST',upload+'?name=software-manifest.json',raw=protocol.canonical(envelope))
    protocol.github('PATCH',repo+'/releases/'+str(release['id']),{'draft':False,'make_latest':'false'})
    base=f'https://github.com/{cfg["owner"]}/{cfg["software_repo"]}/releases/download/v{version}/'
    for name,expected in plan['files'].items():
        size=(Path(plan['directory'])/name).stat().st_size
        if protocol.sha(protocol.download(base+name,size+1))!=expected:raise ValueError('软件公开下载校验失败，尚未设为最新版本')
    downloaded=protocol.verify(json.loads(protocol.download(base+'software-manifest.json',1024*1024)),cfg['public_keys'])
    if downloaded!=payload:raise ValueError('软件公开签名清单不一致，尚未设为最新版本')
    protocol.github('PATCH',repo+'/releases/'+str(release['id']),{'make_latest':'true'})
    protocol.github('DELETE',repo+'/git/refs/tags/software-publish-lock')
    return {'published':True,'version':version,'url':release['html_url']}
