"""Index registered production sources; never scan image trees or rewrite evidence."""
import re
from pathlib import Path
from PIL import Image
from tools import task_library as lib,raw_library as stock
from tools.postprocess_view import view,confined,read_record


def selected_version_source(category,delivery,source):
    """Only the selected, hash-verified version can identify archived raw copies."""
    if delivery is None:return False
    from tools import image_versions as versions
    target=confined(delivery,category)
    root=versions.version_root(target).resolve()
    if root not in source.parents:return False
    index=read_record(confined(versions.index_path(target),category))
    if not isinstance(index,dict):return False
    rows=index.get('versions')
    if not isinstance(rows,list) or len(rows)>1000:return False
    entry=next((r for r in rows if isinstance(r,dict) and r.get('id')==index.get('current')),None)
    if not entry:return False
    image=confined(entry.get('path'),category)
    if root not in image.parents or source.parent!=image.parent:return False
    if stock.file_hash(image)!=entry.get('sha256') or stock.file_hash(target)!=entry['sha256']:return False
    validation=read_record(confined(image.with_suffix('.validation.json'),category))
    if not isinstance(validation,dict):return False
    record=validation.get('postprocess_record',{})
    paths=record.get('sources') if isinstance(record,dict) else None
    return isinstance(paths,list) and any(isinstance(p,str) and confined(p,category)==source for p in paths)


def shared_match(context,category,candidates,source,issue,group,position,delivery=None):
    """Load frozen rows only in the batch directory of the actual source."""
    source=confined(source,category)
    archived=False
    try:archived=selected_version_source(category,delivery,source)
    except (OSError,ValueError,TypeError,KeyError):pass
    if archived:
        proof=confined(source.with_suffix('.receipt.json'),category)
        if lib.io_path(source).stat().st_size>64*1024*1024 or lib.io_path(proof).stat().st_size>1024*1024:return None
        raw_sha=stock.file_hash(source);proof_sha=stock.file_hash(proof)
    for batch,source_group in candidates:
        try:
            raw_folder=(context.output(category,batch)/f'group_{source_group:04d}'/'raw').resolve()
            if source.parent!=raw_folder and not archived:continue
            for unit in context.row(category,batch,source_group)['units']:
                raw=confined(context.raw(category,batch,source_group,unit),category)
                if raw==source:return batch,source_group,unit
                if archived and unit['delivery_position']==position:
                    from tools.task_worker import raw_evidence_valid
                    receipt=confined(raw.with_suffix('.receipt.json'),category)
                    if raw_evidence_valid(raw,unit) and stock.file_hash(raw)==raw_sha and stock.file_hash(receipt)==proof_sha:
                        return batch,source_group,unit
        except (OSError,ValueError,TypeError,KeyError):issue(group,position,'关联修订缺失或冻结记录损坏')
    return None


def keep_mock_unconfirmed(category,asset,inspection):
    if inspection['validation'].get('mock') is not True:return asset
    file=stock.index_file(category,asset['id'])
    with lib.lock(file.with_suffix('.lock'),wait_seconds=10):
        value=stock.load(category,asset['id'])
        value['missing_information']=sorted(set([*value.get('missing_information',[]),'模拟素材不能自动复用']))
        value['eligibility']='unconfirmed'
        # Preserve previous review evidence; this annotation cannot approve it.
        lib.write(file,value);return value


def register_legacy(category,group,position,panel,inspection,item):
    raw=confined(item['path'],category)
    if not item['exists']:raise ValueError('登记原图缺失')
    if lib.io_path(raw).stat().st_size>64*1024*1024:raise ValueError('原图超过安全读取上限')
    with Image.open(lib.io_path(raw)) as im:
        size=list(im.size);format=im.format
        if not 0<size[0]<=16384 or not 0<size[1]<=16384 or size[0]*size[1]>40000000:raise ValueError('原图像素超限')
        im.load()
    kind='cover' if inspection['kind']=='cover' else 'detail'
    validation=inspection['validation'];missing=[]
    roles=validation.get('panel_service_roles')
    theme=(roles[panel-1] if isinstance(roles,list) and len(roles)==len(inspection['sources']) else '') if inspection['kind']=='triptych' else validation.get('service_role','')
    theme=theme if isinstance(theme,str) else ''
    if kind=='detail' and not theme.strip():missing.append('未记录详情主题')
    # A rendered phone is not proof of task-confirmed signboard contact.
    phone=None
    if kind=='cover':missing.append('缺少冻结门头号码确认')
    if size!=[1024,1536] or format!='PNG':missing.append('工作图规格不适用')
    receipt_path=confined(raw.with_suffix('.receipt.json'),category)
    receipt=None;receipt_exists=lib.io_path(receipt_path).is_file()
    if receipt_exists:
        try:receipt=read_record(receipt_path)
        except (ValueError,OSError,TypeError):missing.append('原图收据损坏')
    else:missing.append('未保存原图收据')
    raw_hash=stock.file_hash(raw)
    prompt=receipt.get('prompt_sha256') if isinstance(receipt,dict) else None
    if not isinstance(prompt,str) or not re.fullmatch(r'[a-f0-9]{64}',prompt):prompt=None;missing.append('缺少原提示词指纹')
    if isinstance(receipt,dict) and receipt.get('raw_sha256')!=raw_hash:missing.append('收据与原图摘要不一致')
    original=raw;original_status='working_only';original_size=size
    if item.get('original'):
        if not item['original']['exists']:missing.append('高清原图缺失')
        else:
            original=confined(item['original']['path'],category)
            if lib.io_path(original).stat().st_size>64*1024*1024:raise ValueError('高清原图超过安全读取上限')
            with Image.open(lib.io_path(original)) as im:
                original_size=list(im.size)
                if not 0<im.width<=16384 or not 0<im.height<=16384 or im.width*im.height>40000000:raise ValueError('高清原图像素超限')
                im.load()
            original_status='provider_original'
    elif item.get('original_note'):missing.append('高清来源未登记')
    original_hash=stock.file_hash(original)
    source_data=receipt.get('source') if isinstance(receipt,dict) else None
    if original_status=='provider_original' and (not isinstance(source_data,dict) or source_data.get('source_sha256')!=original_hash):missing.append('高清来源摘要未验证')
    if validation.get('mock') is True or isinstance(receipt,dict) and receipt.get('mock') is True:missing.append('模拟素材不能自动复用')
    asset=lib.digest({'category':category,'original':original_hash,'kind':kind,'theme':theme,'phone':phone})
    file=stock.index_file(category,asset)
    with lib.lock(file.with_suffix('.lock'),wait_seconds=10):
        if file.exists():
            old=stock.load(category,asset)
            if not stock.valid(old):raise ValueError('已有历史登记失效，原记录保留')
            stock.ensure_thumbnail(old);return old
        base=Path(stock.folder({'category':category})['path'])/('门头' if kind=='cover' else '详情')
        if kind=='detail':base=base/re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',theme or '未标注主题')[:70].rstrip('. ')
        # The destination is constructed under the registered stock folder;
        # it is distinct from production's root/category photo locations.
        base=stock.confined(base/asset)
        from tools.category_4k_raw import publish_immutable_bytes
        work=base/'work.png';source=base/('original'+original.suffix.lower());proof=base/'receipt.json';thumb=base/'thumbnail.jpg'
        publish_immutable_bytes(work,lib.io_path(raw).read_bytes())
        publish_immutable_bytes(source,lib.io_path(original).read_bytes())
        if receipt_exists:
            if lib.io_path(receipt_path).stat().st_size>1024*1024:raise ValueError('原图收据超过安全读取上限')
            publish_immutable_bytes(proof,lib.io_path(receipt_path).read_bytes())
        target=confined(inspection['delivery']['path'],category)
        result={'id':asset,'category':category,'kind':kind,'theme':theme,'phone':phone,
            'path':str(work),'original_path':str(source),'thumbnail':str(thumb),'receipt_path':str(proof) if receipt_exists else None,
            'raw_sha256':raw_hash,'original_sha256':original_hash,'receipt_sha256':stock.file_hash(proof) if receipt_exists else None,
            'original_size':original_size,'working_size':size,'original_status':original_status,
            'source':{'kind':'legacy','batch':'legacy','group':group,'unit':f'd{position}-p{panel}','prompt_sha256':prompt,
                'registration':{'delivery':str(target),'position':position,'panel':panel,'raw_path':str(raw),
                    'delivery_sha256':stock.file_hash(target) if lib.io_path(target).is_file() else None,
                    'validation_sha256':stock.file_hash(target.with_suffix('.validation.json')) if lib.io_path(target.with_suffix('.validation.json')).is_file() else None}},
            'review':{'decision':'unreviewed','basis':None,'historical_delivery_decision':'approved' if validation.get('approved') is True else validation.get('decision') or validation.get('status') or 'unknown'},
            'missing_information':sorted(set(missing)),'uses':[],'eligibility':'unconfirmed','qualification':None,'created_at':lib.now()}
        stock.ensure_thumbnail(result);lib.write(file,result);return result


def reindex(request):
    category=request['category'];lib.category_dir(category);batch=request['batch']
    if any(k in request for k in ('path','paths','image_path','root')):raise ValueError('原图索引仅接受登记批次和组号')
    groups=request.get('groups')
    if groups is not None and (not isinstance(groups,list) or not groups or any(type(g)!=int or g<1 for g in groups) or len(set(groups))!=len(groups)):raise ValueError('原图索引组号无效')
    saved=set();missing=0;issues=[];items=[]
    def issue(group,position,message):
        nonlocal missing
        missing+=1
        if len(issues)<50:issues.append({'group':group,'position':position,'reason':message})
    from tools.task_queue import ReadContext
    context=ReadContext();revisions=[]
    for file in lib.category_dir(category).glob('batch_revision_*/batch.json'):
        try:
            revision=lib.read(file)
            if not isinstance(revision,dict):raise ValueError()
            lib.identifier(revision.get('id'))
            revisions.append(revision)
        except (OSError,ValueError,TypeError):issue(None,None,'修订登记损坏，原记录保留')
    if batch=='legacy':
        from tools.task_actions import legacy_entries
        entries=legacy_entries(category)
        if not isinstance(entries,dict):raise ValueError('历史登记格式损坏')
        for row in entries.values():
            if not isinstance(row,dict) or type(row.get('group_index')) is not int or row['group_index']<1:issue(None,None,'历史组登记损坏，原记录保留')
        choices=sorted({r['group_index'] for r in entries.values() if isinstance(r,dict) and type(r.get('group_index')) is int and r['group_index']>0})
        if groups is not None and not set(groups)<=set(choices):raise ValueError('历史索引组未登记')
        groups=groups if groups is not None else choices
        if len(groups)>10000:raise ValueError('历史索引组过多')
        for group in groups:
            positions=set()
            for row in entries.values():
                if not isinstance(row,dict) or row.get('group_index')!=group:continue
                paths=row.get('paths',[])
                if not isinstance(paths,list):issue(group,None,'历史路径登记损坏');continue
                for value in paths:
                    try:
                        if not isinstance(value,str):raise ValueError()
                        target=confined(value,category);position=int(target.name.split('_',1)[0])
                        if position<1:raise ValueError()
                        positions.add(position)
                    except (OSError,ValueError,TypeError):issue(group,None,'历史成品路径未登记或越界')
            if not positions:issue(group,None,'历史登记缺少图片路径')
            for position in sorted(positions):
                try:
                    inspection=view({'category':category,'batch':'legacy','group':group,'position':position})
                    if not inspection['sources']:issue(group,position,'历史成品没有原图来源记录')
                    for panel,item in enumerate(inspection['sources'],1):
                        try:
                            candidates=[(r['id'],1) for r in revisions if r.get('replacement')=={'batch':'legacy','group':group,'position':position} and isinstance(r.get('id'),str)]
                            match=shared_match(context,category,candidates,item['path'],issue,group,position,inspection['delivery']['path'])
                            asset=stock.register(category,*match) if match else register_legacy(category,group,position,panel,inspection,item)
                            asset=keep_mock_unconfirmed(category,asset,inspection);saved.add(asset['id'])
                            if len(items)<200:items.append({'group':group,'position':position,'panel':panel,'asset':asset['id'],'missing_information':asset.get('missing_information',[])})
                        except (OSError,ValueError,TypeError,KeyError):issue(group,position,'历史原图缺失、损坏或来源校验失败')
                except (OSError,ValueError,TypeError,KeyError):issue(group,position,'历史成品来源记录损坏或越界')
    else:
        path,data=context.load(category,batch)
        groups=groups if groups is not None else [g for g in range(1,data['count']+1) if g not in data.get('deleted_groups',[])]
        rows=lib.selected(path,data,groups) if groups else []
        for row in rows:
            for position in dict.fromkeys(u['delivery_position'] for u in row['units']):
                original=[u for u in row['units'] if u['delivery_position']==position]
                try:
                    inspection=view({'category':category,'batch':batch,'group':row['group'],'position':position})
                    candidates=[(batch,row['group'])]
                    for revision in revisions:
                        if revision.get('replacement')=={'batch':batch,'group':row['group'],'position':position}:
                            candidates.append((revision['id'],1))
                    for panel,item in enumerate(inspection['sources']):
                        match=shared_match(context,category,candidates,item['path'],issue,row['group'],position,inspection['delivery']['path'])
                        if not match:issue(row['group'],position,'当前来源未关联冻结原图单元');continue
                        try:
                            asset=keep_mock_unconfirmed(category,stock.register(category,*match),inspection);saved.add(asset['id'])
                            if len(items)<200:items.append({'group':row['group'],'position':position,'panel':panel+1,'asset':asset['id']})
                        except (OSError,ValueError,TypeError,KeyError):issue(row['group'],position,'当前原图缺失或来源校验失败')
                except (OSError,ValueError,TypeError,KeyError):issue(row['group'],position,'当前成品来源记录损坏或越界')
    return {'registered':len(saved),'missing_or_adopted':missing,'issues':issues,'items':items,
        'scope':'registered_delivery_queue' if batch=='legacy' else 'registered_shared_batch',
        'note':'历史索引仅覆盖已登记来源；已打包且没有登记的历史不扫描补齐' if batch=='legacy' else '已按当前成品来源关联冻结单元；没有记录的来源不猜测'}
