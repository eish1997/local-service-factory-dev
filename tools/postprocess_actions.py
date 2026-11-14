"""Explicit local restyling. Content comes from frozen business inputs, never presets."""
import copy
from pathlib import Path
import secrets
import shutil
from tools import task_library as lib, postprocess_rules as rules, image_versions as versions

def presets(request):
    lib.category_dir(request['category'])
    return [{'id':p['id'],'name':p['name'],'roles':p['roles']} for p in rules.load(request['category']).get('presets',[])]

def apply(request):
    from tools.task_actions import ensure_idle
    from tools.postprocess_view import view
    from tools import category_image_production as images
    category=request['category'];lib.category_dir(category)
    batch=request.get('batch','legacy');group=request.get('group')
    if type(group)!=int or group<1:raise ValueError('请选择组')
    scope=request.get('scope','image')
    if scope not in {'image','group'}:raise ValueError('后处理只支持组或图片')
    token=lib.identifier(request.get('request_id') or 'local_'+secrets.token_hex(12))
    log=lib.ROOT/'.runtime/postprocess_operations'/f'{token}.json'
    signature=lib.digest({k:request.get(k) for k in ('category','batch','group','position','scope','preset')})
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
        ensure_idle(category)
        if log.exists():
            prior=lib.read(log)
            if prior['signature']!=signature:raise ValueError('请求标识已用于其他后处理')
            return prior['result']
        initial=view({**request,'position':None} if scope=='group' else request)
        positions=[i['position'] for i in initial['images']] if scope=='group' else [initial['position']]
        documents=[view({**request,'position':p}) for p in positions]
        if any(not d['delivery']['exists'] or not d['sources'] or any(not s['exists'] for s in d['sources']) for d in documents):raise ValueError('缺少成品或可追溯原图，不能重新后处理；保留当前图片')
        if batch=='legacy':
            phone=lib.confirmed_phone(category);cfg=lib.business_config(category);snapshot={}
        else:
            path,data=lib.load_batch(category,batch);phone=data['phone'];snapshot=lib.read(path/'snapshot.json');cfg=snapshot['business']
        services=lib.overlay_services(cfg)
        catalog=rules.load(category);pool=catalog.get('presets',[])
        wanted=request.get('preset','random');staged=[];stage_folders=[];previous_family=None
        original_config=images.load_category_config
        images.load_category_config=lambda c:copy.deepcopy(cfg) if c==category else original_config(c)
        try:
            for d in documents:
                selected=[p for p in pool if d['kind'] in p['roles']]
                if wanted=='random':
                    structures=[p for p in selected if 'structure' in p]
                    if structures:selected=structures
                    current=d['parameters'].get('rules') or {}
                    last_family=current.get('template',{}).get('structure',{}).get('family')
                    if last_family and any(p.get('structure',{}).get('family')!=last_family for p in selected):selected=[p for p in selected if p.get('structure',{}).get('family')!=last_family]
                    different=[p for p in selected if p.get('structure',{}).get('family')!=previous_family]
                    if different:selected=different
                    selected=[p for p in selected if p['id']!=current.get('preset_id')]
                    if not selected:raise ValueError('没有可切换的其他后处理预设')
                    preset=secrets.choice(selected)
                else:
                    preset=next((p for p in selected if p['id']==wanted),None)
                    if preset is None:raise ValueError('该图片不支持此后处理预设')
                previous_family=preset.get('structure',{}).get('family')
                frozen=copy.deepcopy(snapshot.get('postprocess') or catalog)
                for section,values in preset['parameters'].items():frozen['parameters'].setdefault(section,{}).update(copy.deepcopy(values))
                if 'theme' in catalog['parameters']:frozen['parameters']['theme']=copy.deepcopy(catalog['parameters']['theme'])
                if 'structure' in preset:frozen.update(template=copy.deepcopy(preset),layout_seed=secrets.randbelow(2**53),layout_variant=True)
                frozen['preset_id']=preset['id'];frozen['preset_name']=preset['name'];frozen['preset_rules_version']=catalog['rules_version']
                # Keep staged paths short on ordinary Windows installations.
                target=Path(d['delivery']['path']);stage=target.parent/'.pp'/lib.digest(token)[:12];stage.mkdir(parents=True,exist_ok=True)
                stage_folders.append((target,stage));candidate=stage/target.name
                raw_paths=[Path(s['path']) for s in d['sources']]
                validation=lib.read(target.with_suffix('.validation.json')) if target.with_suffix('.validation.json').exists() else {}
                recorded_items=d['parameters'].get('services',{}).get('items')
                saved_lines=lib.saved_service_items(category)
                content=list(saved_lines) if saved_lines is not None else recorded_items if isinstance(recorded_items,list) else services
                if not content and saved_lines is None and not isinstance(recorded_items,list):raise ValueError('项目缺少已确认服务文案')
                if batch!='legacy':
                    row=lib.selected(path,data,[group])[0];units=[u for u in row['units'] if u['delivery_position']==d['position']]
                else:units=[]
                if d['kind']=='triptych':
                    if len(raw_paths)!=3:raise ValueError('三拼缺少三个原图')
                    if not units:raise ValueError('历史三拼缺少冻结布局与面板角色，不能重做')
                    records=[]
                    for u,raw in zip(sorted(units,key=lambda u:u['panel_index']),raw_paths):
                        records.append({**u,'raw_target':str(raw),'category_id':category,'generation_kind':'triptych_panel','group_index':u['source_group'],'index':u['position'],'generation_target_id':u['id'],'delivery_target_id':f'{batch}:{group}:{d["position"]}'})
                    images.compose_triptych(records,candidate,phone,content,postprocess_rules=frozen)
                else:
                    source_group=units[0]['source_group'] if units else validation.get('group_index',group)
                    role=units[0].get('service_role') if units else validation.get('service_role')
                    final_size=validation.get('postprocess_record',{}).get('layout',{}).get('photo_size') or (units[0]['final_size'] if units else validation.get('final_size'))
                    images.apply_overlays(raw_paths[0],candidate,phone,d['kind'],source_group,d['position'],content,final_size,service_role=role,category_id=category,structure_version=validation.get('structure_version'),generation_mode=validation.get('generation_mode'),postprocess_rules=frozen,overlay_profile=validation.get('overlay_profile'),preserve_signboard=True)
                staged.append((d,candidate,preset,raw_paths))
            published=[];rollbacks=[]
            try:
                for d,candidate,preset,raw_paths in staged:
                    target=Path(d['delivery']['path'])
                    history_file=versions.index_path(target)
                    previous=lib.read(history_file)['current'] if history_file.exists() else None
                    fresh=versions.publish(target,candidate,category,'postprocess',old_sources=raw_paths,new_sources=raw_paths,event_id=token+':'+str(d['position']))
                    idx=lib.read(history_file)
                    if previous is None:previous=idx['versions'][0]['id']
                    rollbacks.append((target,previous))
                    published.append({'position':d['position'],'version':fresh['id'],'preset':preset['id'],'name':preset['name']})
                result={'group':group,'images':published,'api_requests':0}
                lib.write(log,{'signature':signature,'result':result});return result
            except Exception:
                for target,previous in reversed(rollbacks):
                    idx=lib.read(versions.index_path(target));entry=next(v for v in idx['versions'] if v['id']==previous)
                    versions.activate(target,entry,category);idx['current']=previous;lib.write(versions.index_path(target),idx)
                raise
        finally:
            images.load_category_config=original_config
            for target,stage in stage_folders:
                # Remove only this operation's staging folder, never any production evidence.
                intended=(target.parent/'.postprocess-staging').resolve()
                folder=stage.resolve()
                if folder.name==token and folder.parent==intended:
                    shutil.rmtree(folder,ignore_errors=True)
