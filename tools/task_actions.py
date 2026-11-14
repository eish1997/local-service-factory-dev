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
    if lib.io_path(root/'.runtime/updates/installing.json').exists():raise ValueError('软件正在安装更新，请重新打开看板后操作')
    patterns=['prompts/library/*/batch_*/tasks/*/task.json','.runtime/jobs/*.json','prompts/category_batches/*/*/production/jobs/*.json']
    for pattern in patterns:
        for file in lib.io_glob(root,pattern):
            row=lib.read(file);cat=row.get('category') or row.get('project_id') or row.get('category_id')
            if category and cat and cat!=category:continue
            if row.get('status') in {'queued','starting','running','recovering','waiting_for_api'} and (not row.get('pid') or lib.alive(row['pid'])):
                raise ValueError('有关联任务正在运行，请暂停并等待当前请求收尾后操作')

def ensure_target_idle(category,batch,group,position):
    """Image repair conflicts with its actual raw targets, not an entire project."""
    if lib.io_path(lib.ROOT/'.runtime/updates/installing.json').exists():raise ValueError('软件正在安装更新，请稍后操作')
    from tools.task_worker import raw_valid
    candidates=[lib.load_batch(category,batch)]
    for file in lib.io_glob(lib.category_dir(category),'batch_revision_*/batch.json'):
        data=lib.read(file)
        if data.get('replacement')=={'batch':batch,'group':group,'position':position}:candidates.append((file.parent,data))
    for path,data in candidates:
        for state in lib.jobs(path):
            if state['status'] not in lib.ACTIVE:continue
            for row in lib.task_rows(path,data,state):
                for unit in row['units']:
                    if (data.get('replacement') or row['group']==group and unit['delivery_position']==position) and not raw_valid(category,data['id'],row['group'],unit):
                        raise ValueError('此图仍在原任务调度或补缺中；其它图片可继续，无需暂停整个项目')

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

def remove_batch_images(category,batch,subdir=''):
    for directory in {lib.output_dir(category,batch),lib.work_dir(category,batch)}:
        remove(directory/subdir)

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
            paths=[lib.ROOT/p/category for p in ['output','projects','prompts/library','prompts/category_batches','.runtime/projects','.runtime/image-work']]
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
            for revision in lib.io_glob(lib.category_dir(category),'batch_revision_*/batch.json'):
                saved=lib.read(revision)
                if saved.get('replacement',{}).get('batch')==batch:remove_batch_images(category,saved['id']);remove(revision.parent)
            remove_batch_images(category,batch);remove(path);queue_remove(category,batch)
            return {'deleted':True,'scope':scope}
        if group>data['count'] or group in data.get('deleted_groups',[]):raise ValueError('该组不存在')
        row=lib.read(path/'groups'/f'{group:04d}.json')
        positions={u['delivery_position'] for u in row['units']}-set(data.get('deleted_images',{}).get(str(group),[]))
        if scope=='image' and position not in positions:raise ValueError('该图片占位不存在')
        for revision in lib.io_glob(lib.category_dir(category),'batch_revision_*/batch.json'):
            saved=lib.read(revision);target=saved.get('replacement',{})
            if target.get('batch')==batch and target.get('group')==group and (scope=='group' or target.get('position')==position):
                remove_batch_images(category,saved['id']);remove(revision.parent);remove(path/'revisions'/f'{saved["id"]}.json')
        if scope=='group' or len(positions)==1:
            data.setdefault('deleted_groups',[]).append(group)
            data['prompt_count']=max(0,data['prompt_count']-sum(u['delivery_position'] in positions for u in row['units']))
            remove_batch_images(category,batch,f'group_{group:04d}');remove(path/'groups'/f'{group:04d}.json')
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
                remove(lib.output_dir(category,batch)/f'group_{group:04d}'/target.name)
            queue_remove(category,batch,group,position)
        # Paused scopes cannot be resumed after a destructive user operation.
        for taskfile in lib.io_glob(path/'tasks','*/task.json'):
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
    if '_automatic_unit_ids' in request:raise ValueError('自动补缺内部范围不能由公开请求指定')
    category=request['category'];batch=request['batch'];group=request.get('group');position=request.get('position')
    if type(group)!=int or type(position)!=int:raise ValueError('请选择单张图片')
    mode=request.get('mode','reassemble')
    if mode not in {'reassemble','repair'}:raise ValueError('单图生成方式无效')
    if mode=='repair' and batch=='legacy':raise ValueError('历史批次请使用重新组装，不能猜测原冻结提示词')
    token=lib.identifier(request['request_id'])
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
        if batch=='legacy':ensure_idle(category)
        else:ensure_target_idle(category,batch,group,position)
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
            lib.require_api(data)
            original=lib.selected(path,data,[group])[0]
            original_snapshot=lib.read(path/'snapshot.json')
        units=[u for u in original['units'] if u['delivery_position']==position]
        if not units:raise ValueError('该图片已删除或不存在')
        if batch!='legacy':
            from tools.task_recovery import protect_returned_results
            source,g,current_units,_=lib.delivery_source(category,batch,group,position)
            protect_returned_results(category,source,g,current_units)
            for linked in lib.io_glob(lib.category_dir(category),'batch_revision_*/batch.json'):
                child_data=lib.read(linked)
                if child_data.get('replacement')=={'batch':batch,'group':group,'position':position}:
                    if child_data.get('revision_kind')=='repair' and not lib.jobs(linked.parent):restore_repair_sources(category,child_data)
                    prior_units=lib.selected(linked.parent,child_data,[1])[0]['units']
                    protect_returned_results(category,child_data['id'],1,prior_units)
        child='batch_revision_'+token;dest=lib.category_dir(category)/child
        if (dest/'batch.json').exists():
            prior=lib.read(dest/'batch.json')
            if prior['replacement']!={'batch':batch,'group':group,'position':position}:raise ValueError('请求标识已用于其他图片')
            if prior.get('revision_kind','reassemble')!=mode:raise ValueError('请求标识已用于不同生成方式')
            if 'sample_variable_choices' in prior and prior['sample_variable_choices']!=request.get('variable_choices',{}):raise ValueError('请求标识已用于不同拍摄设备选择')
            if mode=='repair':
                if request.get('source_revision') and prior['repair_source']['batch']!=request['source_revision']:raise ValueError('请求标识已用于其他补生成来源')
                restore_repair_sources(category,prior)
            return prior
        if mode=='repair':return prepare_repair(request,data,original_snapshot,units,dest,child)
        from tools.task_groups import build_group
        catalog=copy.deepcopy(lib.vc.load(category));lib.vc.validate(catalog)
        snapshot=copy.deepcopy(original_snapshot)
        saved_lines=lib.saved_service_items(category)
        if saved_lines is not None:snapshot.setdefault('business',{})['service_items']=list(saved_lines)
        choices=request.get('variable_choices',{})
        if not isinstance(choices,dict):raise ValueError('变量选择须为对象')
        for source,option_id in choices.items():
            if source!='CAPTURE_DEVICES':raise ValueError('单图样片目前仅支持指定拍摄设备')
            dimension=next((d for d in catalog['dimensions'] if d['source']==source),None)
            if not dimension or not any(o['id']==option_id for o in dimension['options']):raise ValueError('拍摄设备候选不存在')
            for option in dimension['options']:option['enabled']=option['id']==option_id
        lib.vc.validate(catalog)
        snapshot['catalog']=catalog
        seed=secrets.randbelow(1000000)+1401
        if category=='diving_salvage' and snapshot['business'].get('task_type')=='random':
            snapshot['business']['task_type']=units[0]['salvage_context']['task_type']
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
               'structure':{**data['structure'],'total_images':1},'source':request.get('source','agent'),
               'sample_variable_choices':choices}
        saved.pop('replacements',None)
        saved.pop('raw_reuse_sha256',None)
        lib.write(dest/'snapshot.json',snapshot);lib.write(dest/'groups/0001.json',row);lib.write(dest/'manifest.json',manifest);lib.write(dest/'batch.json',saved)
        return saved

def prepare_repair(request,data,snapshot,units,dest,child):
    """Explicit one-delivery repair; reuse proven panels and exact frozen text."""
    from tools.task_worker import raw_valid,delivery_valid,resolve_raw
    category=data['category'];batch=data['id'];group=request['group'];position=request['position']
    if request.get('variable_choices'):raise ValueError('补生成沿用冻结提示词，不能同时改变量')
    source,g,source_units,snapshot=lib.delivery_source(category,batch,group,position)
    if request.get('source_revision'):
        source=lib.identifier(request['source_revision']);source_path,source_data=lib.load_batch(category,source)
        if source_data.get('replacement')!={'batch':batch,'group':group,'position':position}:raise ValueError('补生成来源与原图片关联不一致')
        g=1;source_units=lib.selected(source_path,source_data,[1])[0]['units'];snapshot=lib.read(source_path/'snapshot.json')
        if len(source_units)!=len(units):raise ValueError('补生成来源结构不兼容')
    from tools.task_recovery import protect_returned_results
    protected=source_units
    if request.get('_automatic_unit_ids') is not None:
        if request.get('source')!='automatic-repair':raise ValueError('自动修复范围只由父任务管理')
        protected=[u for u in source_units if u['id'] in request['_automatic_unit_ids']]
    allow=set(request.get('_allow_blocked_reasons') or ())
    if allow and request.get('source')!='automatic-repair':raise ValueError('自动修复范围只由父任务管理')
    protect_returned_results(category,source,g,protected,allow)
    kind='triptych' if source_units[0]['kind']=='triptych_panel' else source_units[0]['kind']
    if all(raw_valid(category,source,g,u) for u in source_units) and delivery_valid(lib.delivery_path(category,batch,group,position,kind),source_units[0]):
        raise ValueError('此图原图已齐且成品存在，无需付费补生成；换效果请用重新后处理或重新组装')
    from tools.task_recovery import proven_panel,repair_panels
    fresh=copy.deepcopy(source_units);reused=0;carried=[]
    for i,(u,prior) in enumerate(zip(fresh,source_units)):
        u['id']=f'g0001_u{i+1:02d}'
        u.pop('inherited_raw',None)
        resolved=resolve_raw(category,source,g,prior)
        proven=proven_panel(category,batch,group,prior) if not resolved and request.get('source')=='automatic-repair' and source==batch else None
        if proven:
            child_data,panel,raw=proven
            u['prompt']=panel['prompt'];u['prompt_sha256']=panel['prompt_sha256']
            if panel['prompt_sha256']!=prior['prompt_sha256']:u['rebuilt_from_rejection']=True
            resolved=(child_data['id'],1,panel,raw)
            carried.append((u,raw))
        if resolved:
            from tools.raw_library import file_hash
            sb,sg,su,raw=resolved;receipt=raw.with_suffix('.receipt.json');asset=None
            if lib.io_path(raw.with_suffix('.adoption.json')).exists():asset=lib.read(raw.with_suffix('.adoption.json'))['asset']
            elif su.get('inherited_raw'):asset=su['inherited_raw'].get('asset')
            u['inherited_raw']={'source':{'batch':sb,'group':sg,'unit':su['id'],'prompt_sha256':su['prompt_sha256']},
                'raw_sha256':file_hash(raw),'receipt_sha256':file_hash(receipt),'asset':asset}
            reused+=1
    reassemble=set(request.get('_reassemble_unit_ids') or ())
    if reassemble:
        if request.get('source')!='automatic-repair':raise ValueError('自动修复范围只由父任务管理')
        from tools.task_groups import build_group
        catalog=copy.deepcopy(snapshot.get('catalog') or lib.vc.load(category))
        pending=set(reassemble)
        tried={}
        for prior in source_units:
            tried[prior['id']]={prior.get('prompt')}
            for _,_,panel in repair_panels(category,batch,group,prior):
                if panel.get('prompt'):tried[prior['id']].add(panel['prompt'])
        if category=='diving_salvage' and snapshot['business'].get('task_type')=='random':
            snapshot['business']['task_type']=source_units[0]['salvage_context']['task_type']
        for bump in range(6):
            seed=secrets.randbelow(1000000)+1401+bump
            full=build_group(category,seed,data['phone'],catalog,snapshot['business'])
            built=[item for item in full if item['delivery_position']==position]
            if len(built)<len(fresh):raise ValueError('当前图片结构与原批次不兼容')
            for i,(u,prior) in enumerate(zip(fresh,source_units)):
                if prior['id'] not in pending or u.get('inherited_raw'):pending.discard(prior['id']);continue
                role=prior.get('service_role');prompt=None
                if role:
                    siblings=[item for item in source_units if item.get('service_role')==role]
                    occurrence=siblings.index(prior)
                    candidates=[item for item in full if item.get('service_role')==role]
                    if occurrence<len(candidates):prompt=candidates[occurrence].get('prompt')
                elif i<len(built) and not built[i].get('service_role'):
                    prompt=built[i].get('prompt')
                if prompt and prompt not in tried[prior['id']]:
                    u['prompt']=prompt
                    u['prompt_sha256']=hashlib.sha256(prompt.encode()).hexdigest()
                    u['rebuilt_from_rejection']=True
                    u.pop('inherited_raw',None)
                    tried[prior['id']].add(prompt)
                    pending.discard(prior['id'])
            if not pending:break
        if pending:raise ValueError('明确拒绝的图片未能组成不同提示词，未再次付费')
    row={'group':1,'units':fresh,'sha256':lib.digest(fresh)};manifest=[{'group':1,'sha256':row['sha256']}]
    saved={**data,'id':child,'count':1,'completed_groups':1,'status':'ready','created_at':lib.now(),
        'prompt_count':len(fresh),'deleted_groups':[],'deleted_images':{},'replacement':{'batch':batch,'group':group,'position':position},
        'revision_kind':'repair','repair_source':{'batch':source,'group':g,'units':[u['id'] for u in source_units]},'snapshot_sha256':lib.digest(snapshot),'manifest_sha256':lib.digest(manifest),
        'structure':{**data['structure'],'total_images':1},'source':request.get('source','agent'),'sample_variable_choices':{},'repair_reused_units':reused}
    saved.pop('replacements',None)
    saved.pop('raw_reuse_sha256',None)
    lib.write(dest/'snapshot.json',snapshot);lib.write(dest/'groups/0001.json',row);lib.write(dest/'manifest.json',manifest);lib.write(dest/'batch.json',saved)
    restore_repair_sources(category,saved)
    if carried:
        from tools.category_4k_raw import publish_immutable_bytes
        for u,raw in carried:
            target=lib.unit_raw(category,child,1,u);lib.io_path(target.parent).mkdir(parents=True,exist_ok=True)
            publish_immutable_bytes(lib.io_path(target),lib.io_path(raw).read_bytes())
            publish_immutable_bytes(lib.io_path(target.with_suffix('.receipt.json')),lib.io_path(raw.with_suffix('.receipt.json')).read_bytes())
            binding=u['inherited_raw']
            lib.write(target.with_suffix('.inherited.json'),{'category':category,'batch':child,'unit':u['id'],
                'snapshot_sha256':saved['snapshot_sha256'],'binding_sha256':lib.digest(binding)})
    return saved

def restore_repair_sources(category,child):
    from tools.task_worker import raw_evidence_valid,resolve_raw
    source=child['repair_source'];path,data=lib.load_batch(category,source['batch'])
    rows=lib.selected(path,data,[source['group']])[0]['units'];by_id={u['id']:u for u in rows}
    fresh=lib.selected(lib.batch_dir(category,child['id']),child,[1])[0]['units']
    if len(fresh)!=len(source['units']):raise ValueError('补生成素材绑定不一致')
    for u,uid in zip(fresh,source['units']):
        prior=by_id.get(uid)
        if not prior or (prior['prompt_sha256']!=u['prompt_sha256'] and not u.get('rebuilt_from_rejection')):
            raise ValueError('补生成素材与冻结提示词不一致')
        if u.get('rebuilt_from_rejection'):continue
        resolved=resolve_raw(category,source['batch'],source['group'],prior)
        raw=resolved[3] if resolved else lib.unit_raw(category,source['batch'],source['group'],prior);target=lib.unit_raw(category,child['id'],1,u)
        binding=u.get('inherited_raw')
        if binding and not raw_evidence_valid(target,u):
            from tools.raw_library import file_hash
            receipt=target.with_suffix('.receipt.json')
            if lib.io_path(target).is_file() and lib.io_path(receipt).is_file() and file_hash(target)==binding['raw_sha256'] and file_hash(receipt)==binding['receipt_sha256']:
                lib.write(target.with_suffix('.inherited.json'),{'category':category,'batch':child['id'],'unit':u['id'],
                    'snapshot_sha256':child['snapshot_sha256'],'binding_sha256':lib.digest(binding)})
        actual=resolved[2] if resolved else prior
        if raw_evidence_valid(raw,actual) and not raw_evidence_valid(target,u):
            if binding:
                from tools.raw_library import file_hash
                if file_hash(raw)!=binding['raw_sha256'] or file_hash(raw.with_suffix('.receipt.json'))!=binding['receipt_sha256']:
                    raise ValueError('冻结继承素材已改变，不能替换来源或重新付费')
            lib.io_path(target.parent).mkdir(parents=True,exist_ok=True)
            from tools.category_4k_raw import publish_immutable_bytes
            publish_immutable_bytes(target,lib.io_path(raw).read_bytes())
            publish_immutable_bytes(target.with_suffix('.receipt.json'),lib.io_path(raw.with_suffix('.receipt.json')).read_bytes())
            if binding:lib.write(target.with_suffix('.inherited.json'),{'category':category,'batch':child['id'],'unit':u['id'],
                'snapshot_sha256':child['snapshot_sha256'],'binding_sha256':lib.digest(binding)})

def commit_replacement(category,batch,data):
    target=data.get('replacement')
    if not target:return
    from tools.task_worker import raw_valid
    row=lib.read(lib.batch_dir(category,batch)/'groups/0001.json')
    if target['batch']=='legacy':
        if not any(r['group_index']==target['group'] for r in legacy_entries(category).values()):raise ValueError('历史组已删除')
        kind='triptych' if row['units'][0]['kind']=='triptych_panel' else row['units'][0]['kind']
        source=lib.delivery_path(category,batch,1,target['position'],kind)
        if not lib.io_path(source).exists():return
        folder=lib.ROOT/'output'/category/f'group_{target["group"]:04d}'
        matches=list(folder.glob(f'{target["position"]:02d}_*.png'))
        original=matches[0] if matches else folder/f'{target["position"]:02d}_{kind}.png'
        from tools.image_versions import publish
        publish(original,source,category,'generation',new_sources=[lib.unit_raw(category,batch,1,u) for u in row['units']],event_id=batch)
        queue_remove(category,batch);return True
    path,parent=lib.load_batch(category,target['batch'])
    if target['group'] in parent.get('deleted_groups',[]) or target['position'] in parent.get('deleted_images',{}).get(str(target['group']),[]):raise ValueError('原图片已删除，不能替换')
    if not all(raw_valid(category,batch,1,u) for u in row['units']):return
    kind='triptych' if row['units'][0]['kind']=='triptych_panel' else row['units'][0]['kind']
    source=lib.delivery_path(category,batch,1,target['position'],kind)
    if not lib.io_path(source).exists():return
    original=lib.delivery_path(category,target['batch'],target['group'],target['position'],kind)
    # Publish only a complete replacement. A failed generation never removes the old image.
    lib.io_path(original.parent).mkdir(parents=True,exist_ok=True)
    from tools.image_versions import publish
    prior_rows=lib.read(path/'groups'/f'{target["group"]:04d}.json')['units']
    publish(original,source,category,'generation',old_sources=[lib.unit_raw(category,target['batch'],target['group'],u) for u in prior_rows if u['delivery_position']==target['position']],new_sources=[lib.unit_raw(category,batch,1,u) for u in row['units']],event_id=batch)
    overrides=parent.setdefault('replacements',{});overrides[f'{target["group"]}:{target["position"]}']=batch
    original_file=path/'groups'/f'{target["group"]:04d}.json';old=lib.read(original_file)
    lib.write(path/'revisions'/f'{batch}.json',{'group':old,'snapshot':lib.read(lib.batch_dir(category,batch)/'snapshot.json')})
    # Keep the parent's manifests, raw evidence and every bound licence immutable.
    # Active delivery content is resolved through this published child revision.
    lib.write(path/'batch.json',parent)
    queue_remove(category,batch)
    file=lib.ROOT/'.runtime/dashboard_delivery_state.json'
    with lib.lock(file.with_suffix('.lock')):
        from tools.dashboard_delivery import load_state,SCHEMA_VERSION
        state=load_state(lib.io_path(file))
        pool=state.setdefault('projects',{}).setdefault(category,{}).setdefault('pending_library_groups',{})
        key=f'{target["batch"]}:{target["group"]}';entry=pool.setdefault(key,{'batch_id':target['batch'],'group_index':target['group'],'expected_image_count':parent['structure']['total_images'],'paths':[]})
        relative=str(original.resolve())
        if relative not in entry['paths']:entry['paths'].append(relative)
        lib.write(file,{**state,'schema_version':SCHEMA_VERSION,'updated_at':lib.now()})
    return True
