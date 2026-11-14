"""Private, reproducible local previews. Applying a preview never renders again."""
import copy
from pathlib import Path
import random
import secrets
import shutil
from PIL import Image, ImageOps
from tools import task_library as lib, postprocess_rules as rules, image_versions as versions

def folder(category, session):
    from tools.task_assets import roots
    lib.category_dir(category);session=lib.identifier(session)
    if not session.startswith('pp_'):raise ValueError('预览会话无效')
    for root in roots():
        path=(root/category/'.postprocess'/session).resolve()
        if path.is_dir() and (root/category).resolve() in path.parents:return path
    raise ValueError('预览会话不存在')

def content(category,batch, imported=False):
    if batch=='legacy':
        if imported:raise ValueError('导入图片需选择有确认电话的批次')
        return lib.confirmed_phone(category),lib.business_config(category),{}
    path,data=lib.load_batch(category,batch);snap=lib.read(path/'snapshot.json')
    lib.validate_batch_phone(category,data,snap)
    return data['phone'],lib.business_config(category) if imported else snap['business'],snap

def context(request):
    from tools.postprocess_view import view
    category=request['category'];batch=request.get('batch','legacy');imported=bool(request.get('image_path'))
    phone,cfg,snapshot=content(category,batch,imported)
    items=lib.overlay_services(cfg)
    d=None;units=[];validation={}
    if imported:
        source=Path(request['image_path']).resolve()
        if source.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:raise ValueError('仅支持 PNG、JPEG、WebP')
        kind=request.get('kind','cover')
        if kind not in {'cover','detail'}:raise ValueError('导入图只支持封面或详情')
        paths=[source];target=None
    else:
        d=view(request);kind=d['kind'];paths=[Path(i['path']) for i in d['sources']]
        if not d['delivery']['exists'] or not paths or any(not lib.io_path(p).is_file() for p in paths):raise ValueError('缺少成品或可追溯原图，保留当前图片')
        target=d['delivery']['path'];validation=lib.validation_record(Path(target).with_suffix('.validation.json'))
        recorded_items=d['parameters'].get('services',{}).get('items')
        if isinstance(recorded_items,list):items=recorded_items
        if batch!='legacy':
            _,_,units,_=lib.delivery_source(category,batch,d['group'],d['position'])
            units=copy.deepcopy(units)
            # A selected historical image keeps its actual caption, even when
            # the most recent generated revision used another frozen theme.
            if kind=='triptych' and isinstance(validation.get('panel_service_roles'),list) and len(validation['panel_service_roles'])==len(units):
                for u,role in zip(units,validation['panel_service_roles']):u['service_role']=role
            elif kind=='detail' and 'service_role' in validation:units[0]['service_role']=validation['service_role']
        if kind=='triptych' and not units:raise ValueError('历史三拼缺少冻结面板记录')
    # An explicitly recorded empty supplementary list is valid: retain the
    # task theme and phone without inventing services for that project.
    saved=lib.saved_service_items(category)
    if saved is not None:items=saved
    elif not items:
        recorded=isinstance(d['parameters'].get('services',{}).get('items'),list) if d else False
        if imported or not recorded:raise ValueError('项目缺少已确认服务词')
    fingerprints=[{'path':str(p),'sha256':versions.revision(p)} for p in paths]
    return {'category':category,'batch':batch,'group':d['group'] if d else None,'position':d['position'] if d else None,'kind':kind,'imported':imported,'phone':phone,'business':cfg,'services':items,'snapshot':snapshot,'units':units,'validation':validation,'target':target,'target_sha256':versions.revision(target) if target else None,'inputs':fingerprints,'catalog':rules.load(category)}

def image_size(path):
    with Image.open(lib.io_path(path)) as source:return list(source.size)

def create(request):
    from tools.task_assets import settings
    if request.get('import_session'):
        _,prior=load({'category':request['category'],'session':request['import_session']})
        if not prior['imported']:raise ValueError('此会话不是导入图片')
        request={**request,'image_path':prior['inputs'][0]['path'],'kind':request.get('kind',prior['kind'])}
    c=context(request);identity='pp_'+secrets.token_hex(6);dest=Path(settings()['path'])/c['category']/'.postprocess'/identity;dest.mkdir(parents=True)
    c['session']=identity;c['sources']=[];c['previews']={}
    for i,item in enumerate(c['inputs']):
        out=dest/f'raw_{i+1}.png'
        if c['imported']:
            with Image.open(lib.io_path(item['path'])) as image:ImageOps.exif_transpose(image).convert('RGB').save(out)
        else:shutil.copyfile(lib.io_path(item['path']),lib.io_path(out))
        c['sources'].append(str(out))
    lib.write(dest/'session.json',c)
    base=lib.base_service_items(c['category']);shown=list(c['services'])
    return {'session':identity,'kind':c['kind'],'sources':[{'path':p,'label':'原图 '+str(i+1),'size':image_size(p)} for i,p in enumerate(c['sources'])],'phone':c['phone'],'services':shown,'original_phone':c['phone'],'original_services':base if len(shown)!=len(base) else shown,'custom':lib.saved_service_items(c['category']) is not None,'imported':c['imported'],'presets':[{'id':p['id'],'name':p['name'],'roles':p['roles'],'structured':'structure' in p} for p in c['catalog']['presets']]}

def shown_text(c):
    override=c.get('text_override')
    if isinstance(override,dict):return override['phone'],list(override['services'])
    return c['phone'],list(c['services'])

def update_text(request):
    """Service lines stay with the category for the next new batch. Phone stays on this preview."""
    path,_=load(request)
    with lib.lock(path/'preview.lock'):
        c=lib.read(path/'session.json');fresh(c)
        if request.get('reset') is True:
            base=lib.base_service_items(c['category'])
            c.pop('text_override',None);lib.remember_service_items(c['category'],base);c['services']=base
        else:
            from tools.contact_numbers import normalize_contact_number
            try:phone=normalize_contact_number(request.get('phone'))
            except ValueError:
                if request.get('persist_only') is not True:raise ValueError('请填写11位手机号或400服务号')
                phone=None
            cleaned=lib.clean_service_lines(request.get('services'))
            lib.remember_service_items(c['category'],cleaned);c['services']=list(cleaned)
            if phone is None:
                override=c.get('text_override')
                if isinstance(override,dict):override['services']=list(cleaned)
            elif phone==c['phone']:c.pop('text_override',None)
            else:c['text_override']={'phone':phone,'services':list(cleaned)}
        c['previews']={};lib.write(path/'session.json',c)
        phone,services=shown_text(c)
        return {'session':c['session'],'phone':phone,'services':services,'original_phone':c['phone'],'original_services':lib.base_service_items(c['category']),'custom':lib.saved_service_items(c['category']) is not None}

def load(request):
    path=folder(request['category'],request['session']);return path,lib.read(path/'session.json')

def fresh(c):
    if rules.load(c['category'])!=c['catalog']:raise ValueError('预设规则已更新，预览过期，请重新预览')
    phone,cfg,snap=content(c['category'],c['batch'],c['imported'])
    if phone!=c['phone'] or cfg!=c['business'] or snap!=c['snapshot']:raise ValueError('批次内容已变化，预览过期，请重新预览')
    if any(versions.revision(i['path'])!=i['sha256'] for i in c['inputs']):raise ValueError('输入图片已变化，预览过期，请重新预览')
    if c['target'] and versions.revision(c['target'])!=c['target_sha256']:raise ValueError('当前图片版本已变化，预览过期，请重新预览')

def render(c,target,frozen):
    from tools import category_image_production as images
    original=images.load_category_config;images.load_category_config=lambda cat:copy.deepcopy(c['business']) if cat==c['category'] else original(cat)
    try:
        units=c['units'];v=c['validation'];category=c['category'];kind=c['kind'];phone,services=shown_text(c)
        if kind=='triptych':
            records=[{**u,'raw_target':raw,'category_id':category,'generation_kind':'triptych_panel','group_index':u['source_group'],'index':u['position'],'generation_target_id':u['id'],'delivery_target_id':c['session']} for u,raw in zip(sorted(units,key=lambda u:u['panel_index']),c['sources'])]
            return images.compose_triptych(records,target,phone,services,postprocess_rules=frozen)
        return images.apply_overlays(Path(c['sources'][0]),target,phone,kind,units[0]['source_group'] if units else v.get('group_index',1),c['position'] or 1,services,v.get('postprocess_record',{}).get('layout',{}).get('photo_size') or (units[0]['final_size'] if units else v.get('final_size') or [1024,1536]),service_role=units[0].get('service_role') if units else v.get('service_role'),category_id=category,structure_version=v.get('structure_version'),generation_mode=v.get('generation_mode'),postprocess_rules=frozen,overlay_profile=v.get('overlay_profile'),preserve_signboard=True)
    finally:images.load_category_config=original

def preview(request):
    path,c=load(request)
    with lib.lock(path/'preview.lock'):
        c=lib.read(path/'session.json');fresh(c)
        supplied_seed=request.get('seed') is not None
        seed=request.get('seed')
        if seed is not None and (type(seed)!=int or not 0<=seed<2**53):raise ValueError('随机种子无效')
        seed=seed if seed is not None else secrets.randbelow(2**53);rng=random.Random(seed)
        pool=[p for p in c['catalog']['presets'] if c['kind'] in p['roles']]
        _,services=shown_text(c)
        if len(services)!=len(c['services']) or len(services)!=len(lib.base_service_items(c['category'])):
            structural=[p for p in pool if 'structure' in p]
            if request.get('preset') not in {None,'random'} and request.get('preset') not in {p['id'] for p in structural}:raise ValueError('这个样式按原来的文字条数排版。增减文字后请换结构模板，或恢复原来的条数')
            if not structural:raise ValueError('增减文字后需要结构模板，当前没有可用样式')
            pool=structural
        if request.get('preset')=='random':
            structures=[p for p in pool if 'structure' in p]
            if structures:pool=structures
            last=next(reversed(list(c['previews'].values())),None)
            previous=last['validation'].get('layout',{}).get('family') if last else None
            different=[p for p in pool if p.get('structure',{}).get('family')!=previous]
            if different:pool=different
        preset=next((p for p in pool if p['id']==request.get('preset')),None) if request.get('preset')!='random' else rng.choice(pool) if pool else None
        if not preset:raise ValueError('预设不适用此图片')
        frozen=copy.deepcopy(c['snapshot'].get('postprocess') or c['catalog'])
        parameters=copy.deepcopy(preset['parameters'])
        if request.get('variant') is True:
            last=next((p for p in reversed(list(c['previews'].values())) if p['preset']==preset['id']),None)
            for section,choices in preset.get('variations',{}).items():
                previous=last['parameters']['parameters'].get(section,{}) if last and not supplied_seed else {}
                different=[choice for choice in choices if any(previous.get(k)!=v for k,v in choice.items())]
                parameters.setdefault(section,{}).update(copy.deepcopy(rng.choice(different or choices)))
        for section,values in parameters.items():frozen['parameters'].setdefault(section,{}).update(values)
        # New preview styling uses current theme design with the old task's
        # frozen text; never infer content from the photo or another task.
        if 'theme' in c['catalog']['parameters']:frozen['parameters']['theme']=copy.deepcopy(c['catalog']['parameters']['theme'])
        if 'structure' in preset:frozen.update(template=copy.deepcopy(preset),layout_seed=seed,layout_variant=request.get('variant') is True)
        rules.validate_sections(frozen['parameters']);frozen.update(preset_id=preset['id'],preset_name=preset['name'],preset_rules_version=c['catalog']['rules_version'])
        identity='pv_'+secrets.token_hex(6);target=path/(identity+'.png');validation=render(c,target,frozen)
        item={'id':identity,'preset':preset['id'],'name':preset['name'],'seed':seed,'path':str(target),'sha256':versions.revision(target),'parameters':frozen,'input_fingerprint':lib.digest(c['inputs']),'rules_version':c['catalog']['rules_version'],'validation':validation.get('postprocess_record',{}),'api_requests':0,'size':image_size(target)}
        c['previews'][identity]=item;lib.write(path/'session.json',c);return item

def sequence(request):
    """Batch previews rotate dominant structures; output never replaces deliveries."""
    sessions=request.get('sessions');seed=request.get('seed',secrets.randbelow(2**53))
    if not isinstance(sessions,list) or not 1<=len(sessions)<=100 or type(seed)!=int or not 0<=seed<2**53:raise ValueError('批量预览输入无效')
    rng=random.Random(seed);previous=None;last_signature=None;results=[]
    for identity in sessions:
        _,c=load({'category':request['category'],'session':identity})
        pool=[p for p in c['catalog']['presets'] if 'structure' in p and c['kind'] in p['roles']]
        fixed=request.get('preset')
        if fixed:pool=[p for p in pool if p['id']==fixed]
        else:pool=[p for p in pool if p['structure']['family']!=previous]
        if not pool:raise ValueError('缺少可轮换的结构模板')
        chosen=rng.choice(pool);tried=set()
        # At most three seeded variants to avoid adjacent identical group positions.
        for attempt in range(3):
            item=preview({'category':request['category'],'session':identity,'preset':chosen['id'],'seed':rng.randrange(2**53),'variant':request.get('variant',True)})
            layout=item['validation']['layout'];signature=lib.digest([(g['kind'],g['zone'],g['board']) for g in layout['groups']])
            if not layout['fallback'] and (signature!=last_signature or fixed and request.get('variant') is False):break
            tried.add(chosen['id'])
            alternatives=[p for p in pool if p['id'] not in tried]
            if not fixed and alternatives:chosen=rng.choice(alternatives)
        distinct=not layout['fallback'] and signature!=last_signature
        previous=layout['family'];last_signature=signature;results.append({'session':identity,**item,'sequence_seed':seed,'sequence_index':len(results),'layout_distinct':distinct})
    return {'seed':seed,'previews':results,'api_requests':0}

def apply(request):
    from tools.task_actions import ensure_idle
    path,c=load(request)
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
        ensure_idle(c['category']);fresh(c)
        item=c['previews'].get(request.get('preview'))
        if not item:raise ValueError('预览不存在')
        candidate=Path(item['path']).resolve()
        if candidate.parent!=path or versions.revision(candidate)!=item['sha256']:raise ValueError('预览文件不完整')
        if c['imported']:
            if not request.get('destination'):raise ValueError('请选择保存位置')
            dest=Path(request['destination']).resolve()
            from tools.task_assets import roots
            if dest.suffix.lower()!='.png' or str(dest).lower()==c['inputs'][0]['path'].lower() or any(root.resolve() in dest.parents for root in roots()):raise ValueError('导出应为 PNG，且不能覆盖原图或工厂资产')
            temp=dest.with_suffix('.postprocess.tmp');shutil.copyfile(lib.io_path(candidate),lib.io_path(temp));lib.io_path(temp).replace(lib.io_path(dest))
            return {'path':str(dest),'api_requests':0}
        entry=versions.publish(c['target'],candidate,c['category'],'postprocess',old_sources=[i['path'] for i in c['inputs']],new_sources=c['sources'],event_id=c['session']+':'+item['id'])
        return {'version':entry['id'],'path':c['target'],'api_requests':0}
