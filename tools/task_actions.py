"""Explicit destructive actions and single-delivery revisions, shared by both entries."""
import copy
import hashlib
import os
from pathlib import Path
import secrets
import shutil
from tools import task_library as lib

def ensure_idle(category=None):
    root=lib.ROOT
    if (root/'.runtime/updates/installing.json').exists():raise ValueError('软件正在安装更新，请重新打开看板后操作')
    patterns=['prompts/library/*/batch_*/tasks/*/task.json','.runtime/jobs/*.json','prompts/category_batches/*/*/production/jobs/*.json']
    for pattern in patterns:
        for file in root.glob(pattern):
            row=lib.read(file);cat=row.get('category') or row.get('project_id') or row.get('category_id')
            if category and cat and cat!=category:continue
            if row.get('status') in {'queued','starting','running','waiting_for_api'} and (not row.get('pid') or lib.alive(row['pid'])):
                raise ValueError('有关联任务正在运行，请暂停并等待当前请求收尾后操作')

def confined(path):
    from tools.task_assets import roots
    path=Path(path);resolved=path.resolve();candidates={lib.ROOT.resolve(),*roots()}
    root=next((r for r in sorted(candidates,key=lambda x:len(x.parts),reverse=True) if r in resolved.parents),None)
    if root is None or path.is_symlink():raise ValueError('拒绝操作项目目录之外的路径')
    # Refuse reparse/junction paths before recursive removal.
    for part in [path,*path.parents]:
        if part==root:break
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):raise ValueError('目标含链接目录，不能直接删除')
    return path

def remove(path):
    path=confined(path)
    if path.is_dir():shutil.rmtree(path)
    elif path.exists():path.unlink()

def queue_remove(category,batch=None,group=None,position=None):
    file=lib.ROOT/'.runtime/dashboard_delivery_state.json'
    if not file.exists():return
    with lib.lock(file.with_suffix('.lock')):
        state=lib.read(file);projects=state.get('projects',{})
        if batch is None:projects.pop(category,None)
        elif category in projects:
            pool=projects[category].get('pending_groups' if batch=='legacy' else 'pending_library_groups',{})
            for key,row in list(pool.items()):
                if batch!='legacy' and row.get('batch_id')!=batch:continue
                if group is not None and row.get('group_index')!=group:continue
                if position is None:pool.pop(key,None)
                else:
                    row['paths']=[p for p in row.get('paths',[]) if not Path(p).name.startswith(f'{position:02d}_')]
                    row['expected_image_count']=max(0,row.get('expected_image_count',1)-1)
        lib.write(file,state)

def delete(request):
    category=lib.identifier(request['category']);scope=request.get('scope')
    if scope not in {'project','batch','group','image'}:raise ValueError('删除范围无效')
    lib.category_dir(category)
    if request.get('authorization')!='delete_selected':raise ValueError('缺少删除确认')
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
        ensure_idle(category)
        if scope=='project':
            file=lib.ROOT/'projects/registry.json'
            from tools import runtime_paths
            registry=runtime_paths.read_json(runtime_paths.CODE_ROOT/'projects/registry.json') if os.environ.get('FACTORY_DATA_HOME') else lib.read(file)
            project=next(p for p in registry['projects'] if p['id']==category)
            if request.get('confirmation')!='删除'+project['name']+'项目':raise ValueError('确认文字不正确')
            # Shared code/templates are not owned by a project and are never deleted.
            paths=[lib.ROOT/p/category for p in ['output','projects','prompts/library','prompts/category_batches','.runtime/projects']]
            from tools.task_assets import roots
            paths += [r/category for r in roots() if r!=lib.ROOT/'output']
            paths += [lib.ROOT/'configs/categories'/f'{category}.json']
            if category=='business_ktv':paths.append(lib.ROOT/'configs/business_ktv')
            for path in paths:confined(path)
            for path in paths:remove(path)
            registry['projects']=[p for p in registry['projects'] if p['id']!=category]
            if registry.get('active_project')==category:registry['active_project']=registry['projects'][0]['id'] if registry['projects'] else None
            if os.environ.get('FACTORY_DATA_HOME'):
                hidden=set(runtime_paths.hidden_projects());hidden.add(category)
                lib.write(lib.ROOT/'.runtime/hidden_projects.json',{'projects':sorted(hidden)})
            else:lib.write(file,registry)
            queue_remove(category)
            return {'deleted':True,'scope':scope}
        batch=request['batch'];group=request.get('group');position=request.get('position')
        if scope in {'group','image'} and (type(group)!=int or group<1):raise ValueError('组号无效')
        if scope=='image' and (type(position)!=int or position<1):raise ValueError('图片位置无效')
        if batch=='legacy':
            return delete_legacy(category,scope,group,position)
        path,data=lib.load_batch(category,batch)
        if data.get('replacement'):raise ValueError('请从原批次操作替换任务')
        if scope=='batch':
            for revision in lib.category_dir(category).glob('batch_revision_*/batch.json'):
                saved=lib.read(revision)
                if saved.get('replacement',{}).get('batch')==batch:remove(lib.output_dir(category,saved['id']));remove(revision.parent)
            remove(lib.output_dir(category,batch));remove(path);queue_remove(category,batch)
            return {'deleted':True,'scope':scope}
        if group>data['count'] or group in data.get('deleted_groups',[]):raise ValueError('该组不存在')
        row=lib.read(path/'groups'/f'{group:04d}.json')
        positions={u['delivery_position'] for u in row['units']}-set(data.get('deleted_images',{}).get(str(group),[]))
        if scope=='image' and position not in positions:raise ValueError('该图片占位不存在')
        for revision in lib.category_dir(category).glob('batch_revision_*/batch.json'):
            saved=lib.read(revision);target=saved.get('replacement',{})
            if target.get('batch')==batch and target.get('group')==group and (scope=='group' or target.get('position')==position):
                remove(lib.output_dir(category,saved['id']));remove(revision.parent);remove(path/'revisions'/f'{saved["id"]}.json')
        if scope=='group' or len(positions)==1:
            data.setdefault('deleted_groups',[]).append(group)
            data['prompt_count']=max(0,data['prompt_count']-sum(u['delivery_position'] in positions for u in row['units']))
            remove(lib.output_dir(category,batch)/f'group_{group:04d}');remove(path/'groups'/f'{group:04d}.json')
            queue_remove(category,batch,group)
        else:
            data.setdefault('deleted_images',{}).setdefault(str(group),[]).append(position)
            data['prompt_count']=max(0,data['prompt_count']-sum(u['delivery_position']==position for u in row['units']))
            for u in row['units']:
                if u['delivery_position']!=position:continue
                raw=lib.unit_raw(category,batch,group,u)
                remove(raw);remove(raw.with_suffix('.receipt.json'))
                kind='triptych' if u['kind']=='triptych_panel' else u['kind']
                target=lib.delivery_path(category,batch,group,position,kind)
                remove(target);remove(target.with_suffix('.validation.json'))
            queue_remove(category,batch,group,position)
        # Paused scopes cannot be resumed after a destructive user operation.
        for taskfile in (path/'tasks').glob('*/task.json'):
            task=lib.read(taskfile)
            if group in task['groups'] and task['status']!='completed':task['status']='cancelled';lib.write(taskfile,task)
        data['visible_count']=data['count']-len(data.get('deleted_groups',[]))
        lib.write(path/'batch.json',data)
        return {'deleted':True,'scope':scope}

def legacy_entries(category):
    file=lib.ROOT/'.runtime/dashboard_delivery_state.json'
    return lib.read(file).get('projects',{}).get(category,{}).get('pending_groups',{}) if file.exists() else {}

def delete_legacy(category,scope,group,position):
    entries=legacy_entries(category)
    matched=[r for r in entries.values() if group is None or r['group_index']==group]
    if not matched:raise ValueError('历史批次或组已不存在')
    for row in matched:
        folder=lib.ROOT/'output'/category/f'group_{row["group_index"]:04d}'
        if scope=='image':
            for file in folder.glob(f'{position:02d}_*'):remove(file)
            queue_remove(category,'legacy',group,position)
        else:remove(folder);queue_remove(category,'legacy',row['group_index'])
    return {'deleted':True,'scope':scope}

def prepare_replacement(request):
    category=request['category'];batch=request['batch'];group=request.get('group');position=request.get('position')
    if type(group)!=int or type(position)!=int:raise ValueError('请选择单张图片')
    token=lib.identifier(request['request_id'])
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
        ensure_idle(category)
        if batch=='legacy':
            if not any(r['group_index']==group for r in legacy_entries(category).values()):raise ValueError('历史组已不存在')
            definition=lib.read(lib.vc.project_dir(category)/'project.json')
            phone=lib.confirmed_phone(category)
            from tools.task_groups import build_group
            original={'units':build_group(category,1401,phone,lib.vc.load(category),lib.business_config(category))}
            data={'category':category,'phone':phone,'structure':definition['content_group'],'revision':0,'name':f'{phone} · 单图更新'}
            original_snapshot={'business':lib.business_config(category),'project':definition,'batch_contact':{'phone':phone,'confirmation':'explicit_batch_input'}}
        else:
            path,data=lib.load_batch(category,batch)
            original=lib.selected(path,data,[group])[0]
            original_snapshot=lib.read(path/'snapshot.json')
        units=[u for u in original['units'] if u['delivery_position']==position]
        if not units:raise ValueError('该图片已删除或不存在')
        child='batch_revision_'+token;dest=lib.category_dir(category)/child
        if (dest/'batch.json').exists():
            prior=lib.read(dest/'batch.json')
            if prior['replacement']!={'batch':batch,'group':group,'position':position}:raise ValueError('请求标识已用于其他图片')
            return prior
        from tools.task_groups import build_group
        catalog=copy.deepcopy(lib.vc.load(category));lib.vc.validate(catalog)
        snapshot=original_snapshot;snapshot['catalog']=catalog
        seed=secrets.randbelow(1000000)+1401
        candidates=build_group(category,seed,data['phone'],catalog,snapshot['business'])
        fresh=[u for u in candidates if u['delivery_position']==position]
        if len(fresh)!=len(units):raise ValueError('当前图片结构与原批次不兼容')
        for i,u in enumerate(fresh):
            u['final_size']=units[i]['final_size']
            u['id']=f'g0001_u{i+1:02d}';u['prompt_sha256']=hashlib.sha256(u['prompt'].encode()).hexdigest()
        row={'group':1,'units':fresh,'sha256':lib.digest(fresh)};manifest=[{'group':1,'sha256':row['sha256']}]
        saved={**data,'id':child,'count':1,'completed_groups':1,'status':'ready','created_at':lib.now(),'seed':seed,'revision':catalog['revision'],
               'prompt_count':len(fresh),'deleted_groups':[],'deleted_images':{},'replacement':{'batch':batch,'group':group,'position':position},
               'snapshot_sha256':lib.digest(snapshot),'manifest_sha256':lib.digest(manifest),
               'structure':{**data['structure'],'total_images':1},'source':request.get('source','agent')}
        lib.write(dest/'snapshot.json',snapshot);lib.write(dest/'groups/0001.json',row);lib.write(dest/'manifest.json',manifest);lib.write(dest/'batch.json',saved)
        return saved

def commit_replacement(category,batch,data):
    target=data.get('replacement')
    if not target:return
    from tools.task_worker import raw_valid
    row=lib.read(lib.batch_dir(category,batch)/'groups/0001.json')
    if target['batch']=='legacy':
        if not any(r['group_index']==target['group'] for r in legacy_entries(category).values()):raise ValueError('历史组已删除')
        kind='triptych' if row['units'][0]['kind']=='triptych_panel' else row['units'][0]['kind']
        source=lib.delivery_path(category,batch,1,target['position'],kind)
        if not source.exists():return
        folder=lib.ROOT/'output'/category/f'group_{target["group"]:04d}'
        matches=list(folder.glob(f'{target["position"]:02d}_*.png'))
        original=matches[0] if matches else folder/f'{target["position"]:02d}_{kind}.png'
        original.parent.mkdir(parents=True,exist_ok=True);temp=original.with_suffix('.replacement.tmp');shutil.copyfile(source,temp);os.replace(temp,original)
        if source.with_suffix('.validation.json').exists():shutil.copyfile(source.with_suffix('.validation.json'),original.with_suffix('.validation.json'))
        queue_remove(category,batch);return
    path,parent=lib.load_batch(category,target['batch'])
    if target['group'] in parent.get('deleted_groups',[]) or target['position'] in parent.get('deleted_images',{}).get(str(target['group']),[]):raise ValueError('原图片已删除，不能替换')
    if not all(raw_valid(category,batch,1,u) for u in row['units']):return
    kind='triptych' if row['units'][0]['kind']=='triptych_panel' else row['units'][0]['kind']
    source=lib.delivery_path(category,batch,1,target['position'],kind)
    if not source.exists():return
    original=lib.delivery_path(category,target['batch'],target['group'],target['position'],kind)
    # Publish only a complete replacement. A failed generation never removes the old image.
    original.parent.mkdir(parents=True,exist_ok=True)
    temp=original.with_suffix('.replacement.tmp');shutil.copyfile(source,temp);os.replace(temp,original)
    validation=source.with_suffix('.validation.json')
    if validation.exists():shutil.copyfile(validation,original.with_suffix('.validation.json'))
    overrides=parent.setdefault('replacements',{});overrides[f'{target["group"]}:{target["position"]}']=batch
    original_file=path/'groups'/f'{target["group"]:04d}.json';old=lib.read(original_file)
    lib.write(path/'revisions'/f'{batch}.json',{'group':old,'snapshot':lib.read(lib.batch_dir(category,batch)/'snapshot.json')})
    previous=[u for u in old['units'] if u['delivery_position']==target['position']]
    for fresh,prior in zip(row['units'],previous):
        updated={**fresh,'id':prior['id'],'position':prior['position']}
        raw=lib.unit_raw(category,target['batch'],target['group'],updated);raw.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(lib.unit_raw(category,batch,1,fresh),raw)
        receipt=lib.read(lib.unit_raw(category,batch,1,fresh).with_suffix('.receipt.json'))
        lib.write(raw.with_suffix('.receipt.json'),receipt)
        old['units'][old['units'].index(prior)]=updated
    old['sha256']=lib.digest(old['units']);lib.write(original_file,old)
    manifest=lib.read(path/'manifest.json')
    for item in manifest:
        if item['group']==target['group']:item['sha256']=old['sha256']
    lib.write(path/'manifest.json',manifest);parent['manifest_sha256']=lib.digest(manifest)
    for file in (path/'tasks').glob('*/task.json'):
        task=lib.read(file)
        if task['status']!='completed':task['status']='cancelled';lib.write(file,task)
    lib.write(path/'batch.json',parent)
    queue_remove(category,batch)
    file=lib.ROOT/'.runtime/dashboard_delivery_state.json'
    with lib.lock(file.with_suffix('.lock')):
        state=lib.read(file) if file.exists() else {'projects':{}}
        pool=state.setdefault('projects',{}).setdefault(category,{}).setdefault('pending_library_groups',{})
        key=f'{target["batch"]}:{target["group"]}';entry=pool.setdefault(key,{'batch_id':target['batch'],'group_index':target['group'],'expected_image_count':parent['structure']['total_images'],'paths':[]})
        relative=str(original.resolve())
        if relative not in entry['paths']:entry['paths'].append(relative)
        lib.write(file,state)
