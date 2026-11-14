"""Bounded read-only inspection of registered delivery images and source evidence."""
from pathlib import Path
from tools import task_library as lib

def confined(path, category, base=None):
    from tools.task_assets import roots
    path=Path(path).resolve()
    parents=[Path(base).resolve()] if base else [r/category for r in roots()|{lib.ROOT/'.runtime/image-work'}]
    if not any(parent.resolve() in path.parents for parent in parents): raise ValueError('后处理图片路径越界')
    return path

def image(path, category, label, base=None):
    path=confined(path,category,base)
    result={'label':label,'path':str(path),'exists':lib.io_path(path).is_file(),'size':None}
    if result['exists']:
        result['revision']=str(lib.io_path(path).stat().st_mtime_ns)+'-'+str(lib.io_path(path).stat().st_size)
        try:
            from PIL import Image
            with Image.open(lib.io_path(path)) as source:
                result['size']=list(source.size)
        except (OSError,ValueError): result['error']='图片无法解码'
    return result

def read_record(file):
    file=lib.io_path(file)
    if not file.is_file(): return {}
    if file.stat().st_size>1024*1024: raise ValueError('后处理记录过大')
    return lib.read(file)

def registered_raw_paths(category,record,fallback=(),base=None):
    """Only explicit render sources or frozen shared units, never a tree scan."""
    if not isinstance(record,dict):raise ValueError('后处理来源记录无效')
    values=record.get('sources')
    if values is not None and (not isinstance(values,list) or any(not isinstance(p,str) or not p for p in values)):
        raise ValueError('后处理来源须为路径列表')
    values=values or list(fallback)
    if len(values)>3:raise ValueError('来源图片数量异常')
    return [confined(p,category,base) for p in values]

def view(request):
    category=request['category'];lib.category_dir(category)
    batch=request.get('batch','legacy');group=request.get('group');position=request.get('position')
    if group is not None and (type(group)!=int or group<1): raise ValueError('组号无效')
    if position is not None and (type(position)!=int or position<1): raise ValueError('图片位置无效')
    frozen=None;units=[];base=None
    if batch=='legacy':
        from tools.task_actions import legacy_entries
        entries=legacy_entries(category)
        if not isinstance(entries,dict):raise ValueError('历史登记格式损坏')
        valid_entries=[r for r in entries.values() if isinstance(r,dict) and type(r.get('group_index')) is int and r['group_index']>0]
        choices=sorted({r['group_index'] for r in valid_entries})
        if len(choices)>10000: raise ValueError('历史组数量过大')
        group=group if group is not None else next(iter(choices),None)
        if group is None: return {'category':category,'batch':batch,'groups':[],'images':[],'sources':[],'note':'暂无已登记历史图片'}
        if group not in choices: raise ValueError('历史组不存在')
        paths=[p for r in valid_entries if r['group_index']==group and isinstance(r.get('paths'),list) for p in r['paths']]
        slots={}
        for value in paths:
            try:
                if not isinstance(value,str):continue
                path=confined(value,category);number=int(path.name.split('_',1)[0])
                if number<1:continue
            except (OSError,ValueError,TypeError):continue
            slots[number]=path
        options=[{'position':n,'kind':'triptych' if 'triptych' in p.stem else 'cover' if 'cover' in p.stem else 'detail'} for n,p in sorted(slots.items())]
        position=position if position is not None else next(iter(slots),None)
        if position not in slots: raise ValueError('历史图片位置不存在')
        target=slots[position]
    else:
        path,data=lib.load_batch(category,batch)
        choices=[g for g in range(1,data.get('completed_groups',0)+1) if g not in data.get('deleted_groups',[])]
        group=group if group is not None else next(iter(choices),None)
        if group is None: return {'category':category,'batch':batch,'groups':[],'images':[],'sources':[],'note':'批次尚未组装完成'}
        if group not in choices: raise ValueError('组不存在')
        row=lib.selected(path,data,[group])[0]
        available=[u for u in row['units'] if u['delivery_position'] not in data.get('deleted_images',{}).get(str(group),[])]
        slots={u['delivery_position']:('triptych' if u['kind']=='triptych_panel' else u['kind']) for u in available}
        options=[{'position':n,'kind':k} for n,k in sorted(slots.items())]
        position=position if position is not None else next(iter(slots),None)
        if position not in slots: raise ValueError('图片位置不存在')
        base=lib.work_dir(category,batch)
        target=lib.delivery_path(category,batch,group,position,slots[position])
        source_batch,source_group,units,_=lib.delivery_source(category,batch,group,position)
        frozen=read_record(path/'snapshot.json').get('postprocess')
    target=confined(target,category,base)
    validation=lib.validation_record(confined(target.with_suffix('.validation.json'),category,base))
    record=validation.get('postprocess_record',{})
    # Only actual render evidence can identify historical raw images. Never guess filenames.
    source_base=None if record.get('sources') or (batch!='legacy' and source_batch!=batch) else base
    raw_paths=registered_raw_paths(category,record,[lib.unit_raw(category,source_batch,source_group,u) for u in units] if batch!='legacy' else [],source_base)
    sources=[]
    for index,value in enumerate(raw_paths):
        raw=confined(value,category,source_base)
        item=image(raw,category,'素材 '+str(index+1),source_base)
        receipt=lib.validation_record(confined(raw.with_suffix('.receipt.json'),category,source_base))
        evidence=receipt.get('source',{})
        if not isinstance(evidence,dict):evidence={}
        item['normalization']={k:evidence[k] for k in ('source_returned_size','normalized_to','normalization_mode') if k in evidence}
        archive=evidence.get('provider_original') or evidence.get('original_archive') or evidence.get('archive_path') or evidence.get('source_archive')
        if archive:
            try: item['original']=image(archive,category,'高清源图',source_base)
            except ValueError: item['original_note']='高清源图记录指向未登记位置；不读取该路径'
        sources.append(item)
    # Return only inspection fields, never entire receipts/tasks or download credentials.
    return {'category':category,'batch':batch,'group':group,'position':position,'groups':choices,'images':options,
            'kind':next(i['kind'] for i in options if i['position']==position),
            'sources':sources,'delivery':image(target,category,'成品',base),
            'parameters':record,'frozen_rules':frozen,
            'validation':{**{k:validation[k] for k in ('status','approved','decision','expected_text','service_role','panel_service_roles','final_size','overlay_style','triptych_recipe','note') if k in validation},'mock':validation.get('mock') is True},
            'note':'当前实际处理记录' if record else '部分历史参数未记录；不使用当前默认规则补齐'}
