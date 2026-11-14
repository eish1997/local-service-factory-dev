"""Bounded public downloads, canonical signatures and GitHub release publishing."""
import base64
import hashlib
import json
import os
import shutil
import subprocess
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def sha(value):return hashlib.sha256(value).hexdigest()

def public_url(url):
    p=urlparse(url)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or not (p.hostname in {'github.com','api.github.com'} or (p.hostname or '').endswith('.githubusercontent.com')):
        raise ValueError('更新下载地址不是允许的 GitHub HTTPS 地址')
    return url

class Redirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        public_url(newurl)
        if request.has_header('Authorization'):raise ValueError('发布请求不允许转发凭证')
        return super().redirect_request(request,fp,code,msg,headers,newurl)

def download(url,limit=16*1024*1024,accept='application/octet-stream',*,timeout=25,attempts=3):
    public_url(url)
    for attempt in range(attempts):
        try:
            with build_opener(Redirect()).open(Request(url,headers={'User-Agent':'LocalServiceFactory/1','Accept':accept}),timeout=timeout) as response:
                if int(response.headers.get('Content-Length','0'))>limit:raise ValueError('更新文件过大')
                data=response.read(limit+1)
            if len(data)>limit:raise ValueError('更新文件过大')
            return data
        except HTTPError:
            # HTTP failures need a different route or a later check, not an
            # immediate repeat against the same exhausted anonymous quota.
            raise
        except (URLError, TimeoutError, ConnectionError):
            if attempt==attempts-1:raise

def verify(envelope,keys):
    if not isinstance(envelope,dict) or envelope.get('key_id') not in keys:raise ValueError('发布签名公钥未配置或不受信任')
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(keys[envelope['key_id']],validate=True)).verify(
            base64.b64decode(envelope['signature'],validate=True),canonical(envelope['payload']))
    except Exception:raise ValueError('发布签名校验失败') from None
    return envelope['payload']

def sign(payload,key_id,keyfile,keys):
    from pathlib import Path
    key=load_pem_private_key(Path(keyfile).read_bytes(),password=None)
    envelope={'payload':payload,'key_id':key_id,'signature':base64.b64encode(key.sign(canonical(payload))).decode()}
    verify(envelope,keys)
    return envelope

def github(method,path,body=None,raw=None):
    token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token and shutil.which('gh'):
        result=subprocess.run(['gh','auth','token'],capture_output=True,text=True,timeout=15,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode==0:token=result.stdout.strip()
    if not token:raise ValueError('维护端尚未配置 GitHub 发布凭证；请在本机配置，不在对话中发送')
    url=path if path.startswith('https://uploads.github.com/') else 'https://api.github.com'+path
    headers={'User-Agent':'LocalServiceFactory/1','Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    if raw is not None:headers['Content-Type']='application/octet-stream'
    elif body is not None:headers['Content-Type']='application/json'
    # Only reads are automatically retried; an interrupted mutation may have succeeded.
    for attempt in range(3 if method=='GET' else 1):
        try:
            with build_opener(Redirect()).open(Request(url,data=raw if raw is not None else canonical(body) if body is not None else None,headers=headers,method=method),timeout=3600 if raw is not None else 60) as response:
                data=response.read(2*1024*1024)
                return json.loads(data) if data else {}
        except HTTPError as error:
            if error.code==404 and method=='GET':return None
            raise ValueError(f'GitHub 发布请求失败（HTTP {error.code}），未推进最新版本指向') from None
        except (URLError, TimeoutError, ConnectionError):
            if method!='GET' or attempt==2:raise
