"""Immutable delivery history; canonical delivery path is always the selected version."""
import copy
import hashlib
import os
from pathlib import Path
import secrets
import shutil
from tools import task_library as lib

def version_root(target): return Path(target).parent/'.v'/Path(target).name.split('_',1)[0]
def index_path(target): return version_root(target)/'index.json'
def revision(path):
    path=lib.io_path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def selection_token(target):
    """Rendering CAS includes the selected identity, even for equal-byte versions."""
    path=index_path(target)
    index=lib.read(path) if lib.io_path(path).is_file() else None
    if index is not None and (not isinstance(index,dict) or not isinstance(index.get('current'),str)):
        raise ValueError('当前版本登记损坏，不能覆盖已有成品')
    return (revision(target),index['current'] if index else None)

def safe(path, category):
    from tools.postprocess_view import confined
    return confined(path,category)

def store(target, source, category, operation, sources=()):
    source=safe(source,category);target=safe(target,category)
    identity='v_'+secrets.token_hex(6);folder=version_root(target)/identity;lib.io_path(folder).mkdir(parents=True)
    image=folder/'image.png';shutil.copyfile(lib.io_path(source),lib.io_path(image))
    sidecar=lib.io_path(source.with_suffix('.validation.json'))
    try:
        validation=lib.read(sidecar) if sidecar.exists() else {}
        if not isinstance(validation,dict):raise ValueError('invalid validation record')
        if 'postprocess_record' in validation and not isinstance(validation['postprocess_record'],dict):raise ValueError('invalid render record')
        record=validation.get('postprocess_record',{})
        if 'rules' in record and not isinstance(record['rules'],dict):raise ValueError('invalid render rules')
        if 'sources' in record and not isinstance(record['sources'],list):raise ValueError('invalid render sources')
    except (OSError,ValueError,TypeError):
        if sidecar.is_file():shutil.copyfile(sidecar,lib.io_path(folder/'original-validation.corrupt.json'))
        validation={'status':'pending','note':'原校验记录损坏，已保留原记录；此版本未审核'}
    recorded=validation.get('postprocess_record',{}).get('sources') or sources
    copied=[]
    for i,value in enumerate(recorded):
        try: raw=safe(value,category)
        except ValueError: continue
        if not lib.io_path(raw).is_file(): continue
        destination=folder/f'raw_{i+1}.png';shutil.copyfile(lib.io_path(raw),lib.io_path(destination));copied.append(str(destination.resolve()))
        receipt=lib.io_path(raw.with_suffix('.receipt.json'))
        if receipt.exists(): shutil.copyfile(receipt,lib.io_path(destination.with_suffix('.receipt.json')))
    if copied:
        validation.setdefault('postprocess_record',{})['sources']=copied
    lib.write(image.with_suffix('.validation.json'),validation)
    return {'id':identity,'path':str(image.resolve()),'sha256':revision(image),'created_at':lib.now(),'operation':operation,'preset_id':validation.get('postprocess_record',{}).get('rules',{}).get('preset_id') if validation.get('postprocess_record',{}).get('rules') else None}

def publish_finished_png(target,category):
    work=lib.ROOT/'.runtime/image-work'/category/'library'
    if not target.is_relative_to(work):return
    batch,group,name=target.relative_to(work).parts
    _,data=lib.load_batch(category,batch)
    if data.get('replacement'):return
    output=safe(lib.output_dir(category,batch)/group/name,category)
    lib.io_path(output.parent).mkdir(parents=True,exist_ok=True)
    temp=lib.io_path(output.with_suffix('.'+secrets.token_hex(6)+'.tmp'))
    try:
        shutil.copyfile(lib.io_path(target),temp)
        os.replace(temp,lib.io_path(output))
    finally:
        temp.unlink(missing_ok=True)

def activate(target, entry, category):
    target=safe(target,category);source=safe(entry['path'],category)
    if version_root(target).resolve() not in source.parents or revision(source)!=entry['sha256']: raise ValueError('历史版本文件不完整')
    lib.io_path(target.parent).mkdir(parents=True,exist_ok=True)
    staged=target.with_suffix('.version.tmp');shutil.copyfile(lib.io_path(source),lib.io_path(staged))
    validation=copy.deepcopy(lib.read(source.with_suffix('.validation.json')))
    validation['selected_version_id']=entry['id']
    # Canonical file and validation are protected by the shared administrative lock.
    os.replace(lib.io_path(staged),lib.io_path(target));lib.write(target.with_suffix('.validation.json'),validation)
    publish_finished_png(target,category)

def publish(target, candidate, category, operation, old_sources=(), new_sources=(), event_id=None):
    target=safe(target,category);candidate=safe(candidate,category)
    path=index_path(target);index=lib.read(path) if lib.io_path(path).exists() else {'schema_version':1,'current':None,'versions':[]}
    if event_id:
        prior=next((v for v in index['versions'] if v.get('event_id')==event_id),None)
        if prior:return prior
    previous=None
    if lib.io_path(target).is_file():
        existing=next((v for v in index['versions'] if v['id']==index['current'] and v['sha256']==revision(target)),None)
        if existing: previous=existing
        else:
            previous=store(target,target,category,'original',old_sources);index['versions'].append(previous)
            index['current']=previous['id'];lib.write(path,index)
    fresh=store(target,candidate,category,operation,new_sources)
    if event_id:fresh['event_id']=event_id
    try:
        activate(target,fresh,category);index['versions'].append(fresh);index['current']=fresh['id'];lib.write(path,index)
    except Exception:
        if previous:activate(target,previous,category)
        raise
    return fresh

def history(request):
    from tools.postprocess_view import view
    data=view(request);target=Path(data['delivery']['path']);path=index_path(target)
    index=lib.read(path) if lib.io_path(path).exists() else {'current':None,'versions':[]}
    versions=[]
    if len(index['versions'])>1000:raise ValueError('历史版本过多，请由 Agent 检查')
    for entry in reversed(index['versions']):
        file=safe(entry['path'],request['category'])
        if version_root(target).resolve() not in file.parents:raise ValueError('历史版本路径越界')
        versions.append({k:entry.get(k) for k in ('id','path','sha256','created_at','operation','preset_id')})
    if not versions and lib.io_path(target).is_file():versions=[{'id':'current','path':str(target),'sha256':revision(target),'operation':'original','created_at':None}]
    return {'current':index['current'] or 'current','versions':versions,'target':str(target)}

def select(request):
    from tools.task_actions import ensure_idle
    from tools.postprocess_view import view
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
        ensure_idle(request['category'])
        data=view(request);target=Path(data['delivery']['path']);index=lib.read(index_path(target))
        entry=next((v for v in index['versions'] if v['id']==request.get('version')),None)
        if not entry:raise ValueError('历史版本不存在')
        previous=next(v for v in index['versions'] if v['id']==index['current'])
        try:activate(target,entry,request['category']);index['current']=entry['id'];lib.write(index_path(target),index)
        except Exception:activate(target,previous,request['category']);raise
        return {'current':entry['id'],'revision':entry['sha256']}
