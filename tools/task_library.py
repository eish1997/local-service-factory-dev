"""Single public workflow for Agent and Electron. No network in assembly/read/plan."""
import argparse
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime,timezone
from tools import variable_catalog as vc, runtime_paths

ROOT=runtime_paths.data_root()
ACTIVE={'queued','running'}

def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
    try:
        with temp.open('w',encoding='utf-8') as out:
            json.dump(value,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
        # Windows readers may briefly hold a file without delete sharing.
        # Retry only the local atomic replacement, never an image request.
        for attempt in range(8):
            try: os.replace(temp,path);break
            except PermissionError:
                if attempt==7: raise
                time.sleep(.025*(attempt+1))
    finally:
        if temp.exists(): temp.unlink()
def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',value): raise ValueError('无效标识')
    return value

def category_dir(category):
    if category not in {p['id'] for p in vc.projects()}: raise ValueError('未知业务')
    return ROOT/'prompts/library'/category

def batch_dir(category,batch): return category_dir(category)/identifier(batch)
def load_batch(category,batch):
    path=batch_dir(category,batch);data=read(path/'batch.json')
    if data['category']!=category or data['id']!=batch: raise ValueError('批次身份不一致')
    return path,data

def alive(pid):
    from tools.category_image_production import pid_is_running
    return bool(pid and pid_is_running(int(pid)))

@contextlib.contextmanager
def lock(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    # Persistent process lock; never remove a lock owned by a living process.
    for attempt in range(2):
        try: fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY);break
        except FileExistsError:
            try: owner=read(path)
            except Exception: raise ValueError('任务锁正在建立，请稍后重试')
            if alive(owner.get('pid')): raise ValueError('已有操作正在进行，请稍后重试')
            path.unlink()
    else: raise ValueError('无法取得任务锁')
    try:
        os.write(fd,json.dumps({'pid':os.getpid(),'created_at':now()}).encode());os.close(fd)
        yield
    finally:
        if path.exists(): path.unlink()

def confirmed_phone(category):
    from tools.contact_numbers import normalize_contact_number
    definition=vc.read_json(vc.project_dir(category)/'project.json')
    field=definition.get('required_fields',{}).get('contact_phones',{})
    numbers=list(field.get('values',[])) if field.get('confirmed') else []
    runtime=ROOT/'.runtime/projects'/category/'business.json'
    if runtime.exists():
        value=read(runtime)
        if value.get('user_confirmed') and value.get('contact_phones'):
            stored=value['contact_phones']
            if numbers and set(numbers)!=set(stored): raise ValueError('联系电话确认记录冲突，请让 Agent 核对')
            numbers=stored
    if not numbers: raise ValueError('尚未确认该业务联系电话，请在 Agent 对话中确认后组装')
    if len(set(numbers))!=1: raise ValueError('该业务有多个已确认号码，请由 Agent 明确本批次使用的号码后再组装')
    return normalize_contact_number(numbers[0])

def business_config(category):
    path=runtime_paths.CODE_ROOT/('configs/business_ktv/scene_library.json' if category=='business_ktv' else f'configs/categories/{category}.json')
    return runtime_paths.read_json(path) if runtime_paths.rule_file(path).exists() else {}

def projects():
    result=[]
    for p in vc.projects():
        definition=runtime_paths.read_json(vc.project_dir(p['id'])/'project.json')
        result.append({**p,'structure':definition['content_group'],'assembly_blocked':None,
                       'required_assembly_fields':['count','phone']})
    return result

def assemble(request):
    with lock(ROOT/'.runtime/task-admin.lock'):
        return _assemble(request)

def _assemble(request):
    if (ROOT/'.runtime/updates/installing.json').exists():raise ValueError('软件正在安装更新，请重新打开看板后操作')
    category=request['category']; count=request.get('count');seed=request.get('seed')
    if type(count)!=int or not 1<=count<=100: raise ValueError('组数必须为 1–100 的整数')
    phone=request.get('phone')
    if not isinstance(phone,str) or not re.fullmatch(r'1[3-9][0-9]{9}',phone):
        raise ValueError('请填写本批次的有效 11 位手机号，不能自动沿用历史号码')
    if seed is None: seed=secrets.randbelow(1_000_000)+1401
    if type(seed)!=int or not 1401<=seed<=2_000_000: raise ValueError('种子须为 1401–2000000 的整数')
    source=request.get('source','agent')
    if source not in {'agent','dashboard'}: raise ValueError('来源不正确')
    request_id=identifier(request.get('request_id') or secrets.token_hex(16))
    home=category_dir(category)
    with lock(home/'assemble.lock'):
        previous=home/'requests'/f'{request_id}.json'
        signature=digest({k:request.get(k) for k in ('category','count','seed','phone')})
        if previous.exists():
            old=read(previous)
            if old['signature']!=signature: raise ValueError('同一请求标识不能用于不同组装内容')
            return read(home/old['batch']/'batch.json')
        catalog=copy.deepcopy(vc.load(category));vc.validate(catalog)
        config=business_config(category)
        batch='batch_'+phone+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+secrets.token_hex(5)
        path=home/batch;path.mkdir(parents=True)
        definition=runtime_paths.read_json(vc.project_dir(category)/'project.json');structure=definition['content_group']
        from tools.task_assets import settings
        summary={'asset_root':settings()['path'],'schema_version':1,'id':batch,'name':f'{phone} · {count} 组','category':category,'source':source,'seed':seed,'count':count,
                 'created_at':now(),'status':'assembling','completed_groups':0,'phone':phone,'revision':catalog['revision'],
                 'structure':structure,'api_called':False,'request_id':request_id}
        write(previous,{'signature':signature,'batch':batch});write(path/'batch.json',summary)
        try:
            from tools.task_groups import build_group
            snapshot={'rules_version':runtime_paths.version(),'catalog':catalog,'business':config,'project':definition,
                      'batch_contact':{'phone':phone,'confirmation':'explicit_batch_input'}}
            summary['snapshot_sha256']=digest(snapshot)
            write(path/'snapshot.json',snapshot)
            manifest=[]
            for group in range(1,count+1):
                units=build_group(category,seed+group-1,phone,catalog,config)
                expected=structure.get('generation_unit_count') or structure['cover_count']+structure['detail_count']
                if len(units)!=expected: raise ValueError('完整组生成单元数量不符合业务结构')
                for unit in units:
                    unit['id']=f'g{group:04d}_u{unit["position"]:02d}'
                    unit['prompt_sha256']=hashlib.sha256(unit['prompt'].encode()).hexdigest()
                row={'group':group,'units':units,'sha256':digest(units)}
                write(path/'groups'/f'{group:04d}.json',row);manifest.append({'group':group,'sha256':row['sha256']})
                summary['completed_groups']=group;write(path/'batch.json',summary)
            summary.update(status='ready',prompt_count=count*expected,manifest_sha256=digest(manifest))
            write(path/'manifest.json',manifest);write(path/'batch.json',summary)
            return summary
        except Exception as error:
            summary.update(status='failed',error=str(error));write(path/'batch.json',summary);raise

def batches(category):
    return sorted([b for p in category_dir(category).glob('batch_*/batch.json') if not (b:=read(p)).get('replacement')],key=lambda b:b['created_at'],reverse=True)

def selected(path,data,groups):
    if data['status']!='ready': raise ValueError('批次尚未完成组装')
    if not isinstance(groups,list) or not groups or any(type(g)!=int or not 1<=g<=data['count'] for g in groups) or len(set(groups))!=len(groups): raise ValueError('请选择有效且不重复的组')
    if digest(read(path/'snapshot.json'))!=data['snapshot_sha256']: raise ValueError('批次配置快照已改变')
    manifest=read(path/'manifest.json')
    if digest(manifest)!=data['manifest_sha256']: raise ValueError('批次清单校验失败')
    hashes={r['group']:r['sha256'] for r in manifest};result=[]
    for g in sorted(groups):
        if g in data.get('deleted_groups',[]):raise ValueError('所选组已删除')
        row=read(path/'groups'/f'{g:04d}.json')
        if row['sha256']!=hashes[g] or digest(row['units'])!=hashes[g]: raise ValueError('提示词文件已改变，禁止使用旧任务继续')
        row['units']=[u for u in row['units'] if u['delivery_position'] not in data.get('deleted_images',{}).get(str(g),[])]
        if not row['units']:raise ValueError('所选组没有可生成图片')
        result.append(row)
    return result

def output_dir(category,batch):
    from tools.task_assets import batch_root
    _,data=load_batch(category,batch)
    return batch_root(data)/category/'library'/identifier(batch)
def unit_raw(category,batch,group,unit): return output_dir(category,batch)/f'group_{group:04d}'/'raw'/f'{unit["id"]}.png'
def delivery_path(category,batch,group,position,kind): return output_dir(category,batch)/f'group_{group:04d}'/f'{position:02d}_{kind}.png'

def jobs(path):
    rows=[]
    for p in (path/'tasks').glob('*/task.json'):
        row=read(p)
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['updated_at'])).total_seconds()
        if row['status'] in ACTIVE and ((row.get('pid') and not alive(row['pid'])) or (not row.get('pid') and age>30)): row={**row,'status':'interrupted'}
        rows.append(row)
    return sorted(rows,key=lambda row:row['created_at'],reverse=True)

def view(request):
    path,data=load_batch(request['category'],request['batch']);offset=request.get('offset',0);limit=request.get('limit',20)
    if type(offset)!=int or offset<0 or type(limit)!=int or not 1<=limit<=100: raise ValueError('分页参数错误')
    rows=[];task_rows=jobs(path)
    if not data.get('replacement'):
        for p in category_dir(data['category']).glob('batch_revision_*/batch.json'):
            revision=read(p);target=revision.get('replacement',{})
            if target.get('batch')==data['id']:
                task_rows.extend({**t,'groups':[target['group']],'replacement_position':target['position']} for t in jobs(p.parent))
        task_rows.sort(key=lambda t:t['created_at'],reverse=True)
    for g in range(offset+1,min(data.get('completed_groups',0),offset+limit)+1):
        if g in data.get('deleted_groups',[]):continue
        row=read(path/'groups'/f'{g:04d}.json');delivered={}
        row['units']=[u for u in row['units'] if u['delivery_position'] not in data.get('deleted_images',{}).get(str(g),[])]
        for u in row['units']:
            kind='triptych' if u['kind']=='triptych_panel' else u['kind'];target=delivery_path(data['category'],data['id'],g,u['delivery_position'],kind)
            if target.exists():
                review=target.with_suffix('.validation.json');validation=read(review) if review.exists() else {}
                decision='approved' if validation.get('approved') is True else validation.get('decision') or validation.get('status') or 'pending'
                delivered[u['delivery_position']]={'path':str(target),'position':u['delivery_position'],'kind':kind,'review':decision}
        relevant=next((t for t in task_rows if g in t['groups']),None)
        row.update(images=list(delivered.values()),task=relevant['id'] if relevant else None,
                   status=('approved' if all(i['review']=='approved' for i in delivered.values()) else 'needs_fix' if any(i['review'] in {'needs_fix','rejected'} for i in delivered.values()) else 'generated') if len(delivered)==len({u['delivery_position'] for u in row['units']}) else (relevant['status'] if relevant else 'prompt_ready'))
        if not request.get('include_prompts',True):
            row['units']=[{k:v for k,v in u.items() if k not in {'prompt','variables'}} for u in row['units']]
        rows.append(row)
    return {'batch':data,'groups':rows,'tasks':task_rows,'total':data['count']}

def api_config():
    import factory
    config=factory.effective_api_config(factory.load_json(runtime_paths.CODE_ROOT/'config.json'))
    if config.get('model')=='gpt-image-2-4k':
        if config.get('provider')!='relay' or str(config.get('base_url','')).rstrip('/')!='https://tinysnow.one/v1':
            raise ValueError('gpt-image-2-4k 仅配置了 tinysnow 尺寸方案')
        config.update(quality='medium',api_size='2560x3840',raw_contract='tinysnow_2336_2352x3520_to_legacy_v1')
    elif config.get('model') not in {'gpt-image-2','gpt-image-2.5-flare'} or config.get('quality')!='medium' or config.get('api_size')!='1024x1536':
        raise ValueError('模型或尺寸不在已配置的生成方案内')
    allowed=('provider','model','quality','api_size','output_format','base_url','raw_contract')
    return {k:config[k] for k in allowed if k in config}

def readiness(category,config,snapshot):
    import image_generate
    reasons=[]
    image_generate.load_project_env(); slots=list(range(1,len(image_generate.configured_api_keys())+1))
    if not slots: reasons.append('尚未配置 API Key，请让 Agent 协助设置')
    if category=='business_ktv': reasons.append('商务KTV当前需要 Agent 实时读取图片完成视觉审核，尚无可供后台任务调用的自动视觉审核通道')
    if not (snapshot['business'].get('service_items') or snapshot['business'].get('service_buttons')):
        reasons.append('该业务缺少统一生成所需的已确认底部服务词配置，请由 Agent 补齐')
    return reasons,slots

def validate_batch_phone(category,data,snapshot):
    contact=snapshot.get('batch_contact')
    if contact:
        if contact.get('confirmation')!='explicit_batch_input' or contact.get('phone')!=data['phone']:
            raise ValueError('批次手机号与冻结确认记录不一致')
    elif confirmed_phone(category)!=data['phone']:
        raise ValueError('当前确认电话与旧批次不同，请由 Agent 处理')

def plan(request):
    category=request['category'];batch=request['batch'];path,data=load_batch(category,batch)
    rows=selected(path,data,request['groups']);snapshot=read(path/'snapshot.json')
    validate_batch_phone(category,data,snapshot)
    blocks=[]
    try: config=api_config()
    except Exception as error: config={};blocks.append(str(error))
    more,slots=readiness(category,config,snapshot);blocks+=more
    for row in rows:
        for unit in row['units']:
            kind='triptych' if unit['kind']=='triptych_panel' else unit['kind']
            review=delivery_path(category,batch,row['group'],unit['delivery_position'],kind).with_suffix('.validation.json')
            if review.exists() and (read(review).get('status') in {'rejected','needs_fix'} or read(review).get('decision')=='rejected'):
                blocks.append('所选组包含未通过审核的图片，请由 Agent 按反馈处理，不自动重复生成');break
    from tools.task_worker import raw_valid
    pending=[];reused=0
    for row in rows:
        for unit in row['units']:
            if raw_valid(category,batch,row['group'],unit): reused+=1
            else: pending.append(unit['id'])
    for task in jobs(path):
        if task['status'] in ACTIVE and set(task['groups'])&set(request['groups']): blocks.append('所选组已有运行任务')
        elif task['status'] not in {'completed','cancelled'} and set(task['groups'])&set(request['groups']): blocks.append('所选组已有未完成任务，请继续原任务，不能另建预算')
    for p in category_dir(category).glob('batch_revision_*/batch.json'):
        revision=read(p);target=revision.get('replacement',{})
        if target.get('batch')==batch and target.get('group') in request['groups'] and any(t['status'] not in {'completed','cancelled'} for t in jobs(p.parent)):
            blocks.append('所选组已有单图重生成任务，请先处理该任务')
    result={'category':category,'batch':batch,'groups':sorted(request['groups']),'group_count':len(rows),'pending':pending,
            'pending_count':len(pending),'reused_count':reused,'max_requests':len(pending)*2,'config':config,'slots':slots,
            'max_workers':len(slots),'concurrency':'key_pool','manifest_sha256':data['manifest_sha256'],'blocks':blocks}
    result['plan_sha256']=digest(result)
    return result

def launch(category,batch,task):
    path=batch_dir(category,batch)/'tasks'/task
    log=(path/'worker.log').open('ab')
    kwargs={'cwd':str(ROOT),'stdin':subprocess.DEVNULL,'stdout':log,'stderr':log}
    if os.name=='nt': kwargs['creationflags']=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS
    else: kwargs['start_new_session']=True
    entry=runtime_paths.CODE_ROOT if os.environ.get('FACTORY_DATA_HOME') else ROOT
    try: proc=subprocess.Popen([sys.executable,'-X','utf8',str(entry/'factory.py'),'tasks','worker','--category',category,'--batch',batch,'--task',task],**kwargs)
    finally: log.close()
    return proc.pid

def start(request):
    with lock(ROOT/'.runtime/task-admin.lock'):
        return _start(request)

def _start(request):
    if (ROOT/'.runtime/updates/installing.json').exists():raise ValueError('软件正在安装更新，请重新打开看板后执行任务')
    category=request['category'];batch=request['batch'];path,data=load_batch(category,batch)
    token=identifier(request['request_id'])
    if request.get('authorization')!='execute_selected_groups': raise ValueError('缺少本次所选组的明确执行指令')
    with lock(path/'control.lock'):
        file=path/'tasks'/token/'task.json'
        if file.exists():
            prior=read(file)
            if prior['groups']!=sorted(request['groups']): raise ValueError('请求标识已用于其他范围')
            return prior
        planned=plan(request)
        if planned['blocks']: raise ValueError('；'.join(planned['blocks']))
        if request.get('plan_sha256')!=planned['plan_sha256']: raise ValueError('任务计划已变化，请刷新执行信息')
        record={'schema_version':1,'id':token,'category':category,'batch':batch,'groups':planned['groups'],'source':request.get('source','agent'),
                'status':'queued','pid':None,'created_at':now(),'updated_at':now(),'config':planned['config'],
                'slots':planned['slots'],'max_workers':planned['max_workers'],'max_requests':planned['max_requests'],
                'total_units':planned['pending_count']+planned['reused_count'],'reused_units':planned['reused_count'],
                'requests_used':0,'attempts':{},'results':{},'manifest_sha256':data['manifest_sha256'],
                'plan_sha256':planned['plan_sha256'],'authorization':'execute_selected_groups'}
        terms={k:record[k] for k in ('id','category','batch','groups','config','slots','max_workers','max_requests','manifest_sha256','authorization')}
        record['license_sha256']=digest(terms)
        file.parent.mkdir(parents=True,exist_ok=True)
        with (file.parent/'license.json').open('x',encoding='utf-8') as out: json.dump({'terms':terms,'requests_used':0,'attempts':{}},out,ensure_ascii=False)
        write(file,record)
        try: record['pid']=launch(category,batch,token)
        except Exception:
            record.update(status='failed_to_start');write(file,record);raise
        write(file,record)
        return record

def synchronize_license(file,state):
    license=read(file.parent/'license.json');terms=license['terms']
    if digest(terms)!=state.get('license_sha256') or any(state.get(k)!=v for k,v in terms.items()):
        raise ValueError('任务范围、模型或预算与一次性许可不一致')
    if not 0<=license['requests_used']<=terms['max_requests']: raise ValueError('许可请求计数无效')
    state['requests_used']=max(state['requests_used'],license['requests_used'])
    for key,used in license['attempts'].items():
        if used>state['attempts'].get(key,0):
            state['attempts'][key]=used;state['results'][key]={'status':'request_reserved'}
    return license


def pause(request):
    category=request['category'];batch=request['batch'];path,data=load_batch(category,batch);task=identifier(request['task'])
    with lock(path/'control.lock'):
        file=path/'tasks'/task/'task.json';row=read(file)
        if row['status'] not in ACTIVE: return row
        write(file.parent/'pause.json',{'requested_at':now()})
        return {**row,'pause_requested':True}

def resume(request):
    with lock(ROOT/'.runtime/task-admin.lock'):
        return _resume(request)

def _resume(request):
    if (ROOT/'.runtime/updates/installing.json').exists():raise ValueError('软件正在安装更新，请重新打开看板后继续任务')
    category=request['category'];batch=request['batch'];path,data=load_batch(category,batch);task=identifier(request['task'])
    with lock(path/'control.lock'):
        file=path/'tasks'/task/'task.json';row=read(file)
        synchronize_license(file,row)
        if row['status'] in ACTIVE and alive(row.get('pid')): return row
        if row['status']=='completed': return row
        if row['status']=='cancelled':raise ValueError('该任务的目标已删除或重新组装，不能继续')
        selected(path,data,row['groups'])
        if api_config()!=row['config']: raise ValueError('API配置已变化，不能以不同模型或线路继续原任务')
        validate_batch_phone(category,data,read(path/'snapshot.json'))
        blocks,slots=readiness(category,row['config'],read(path/'snapshot.json'))
        if blocks: raise ValueError('；'.join(blocks))
        if not set(row['slots'])<=set(slots): raise ValueError('原任务绑定的 Key 槽位缺失')
        from tools.task_worker import raw_valid
        records=selected(path,data,row['groups'])
        pending=[u for r in records for u in r['units'] if not raw_valid(category,batch,r['group'],u)]
        unsafe=[u for u in pending if row['results'].get(u['id'],{}).get('status')=='request_reserved' or row['results'].get(u['id'],{}).get('error') not in (None,'transient','balance_exhausted')]
        if unsafe: raise ValueError('存在结果不确定或不适合重试的请求，请由 Agent 检查已有结果；不会重复付费生成')
        if pending and (row['requests_used']>=row['max_requests'] or all(row['attempts'].get(u['id'],0)>=2 for u in pending)): raise ValueError('原任务请求预算或单图重试次数已耗尽，请由 Agent 处理')
        only_failed=request.get('only_failed') is True
        retry_ids=[u['id'] for u in pending if row['results'].get(u['id'],{}).get('status')=='failed' and row['attempts'].get(u['id'],0)<2]
        if only_failed and not retry_ids: raise ValueError('没有可在剩余预算内重试的失败项')
        pause_file=file.parent/'pause.json'
        if pause_file.exists(): pause_file.unlink()
        row.update(status='queued',pid=None,updated_at=now(),retry_unit_ids=retry_ids if only_failed else None);write(file,row)
        try: row['pid']=launch(category,batch,task)
        except Exception: row.update(status='failed_to_start');write(file,row);raise
        write(file,row);return row

def legacy_group(request):
    category=request['category'];category_dir(category);group=request.get('group')
    if type(group)!=int or group<1: raise ValueError('组号无效')
    project=vc.read_json(vc.project_dir(category)/'project.json');sources=project.get('prompt_sources',{})
    candidates=[sources.get('generation_manifest')] if sources.get('generation_manifest') else []
    if not candidates or not (ROOT/str(candidates[0])).is_file(): candidates=[sources.get('cover_manifest'),sources.get('detail_manifest'),sources.get('production_manifest')]
    result=[];missing=[];seen=set()
    for value in candidates:
        if not value: continue
        path=(ROOT/value).resolve()
        if ROOT.resolve() not in path.parents or not path.is_file(): missing.append(str(value));continue
        with path.open(encoding='utf-8-sig') as source:
            for i,line in enumerate(source):
                if i>=100000: break
                try: row=json.loads(line)
                except ValueError: continue
                if row.get('group_index')!=group: continue
                prompt=row.get('effective_prompt') or row.get('prompt') or row.get('positive_prompt')
                if not isinstance(prompt,str) or not prompt or prompt in seen: continue
                seen.add(prompt);result.append({'position':row.get('generation_position') or row.get('position') or len(result)+1,'kind':row.get('generation_kind') or row.get('role','detail'),'prompt':prompt,'service_role':row.get('service_role'),'historical':True})
                if len(result)>=30: break
    return {'group':group,'units':result,'note':'历史提示词，仅展示原记录；没有记录的变量与配置版本不推测补齐。' if result else '该组提示词未在当前登记来源中找到；旧图片保持可查看。','missing_sources':missing}


def dispatch(operation,request):
    if operation in {'assets-view','assets-save','open-folder','package'}:
        from tools import task_assets
        return {'assets-view':lambda r:task_assets.settings(),'assets-save':task_assets.save,'open-folder':task_assets.open_folder,'package':task_assets.package}[operation](request)
    if operation in {'delete','replacement-prepare'}:
        from tools import task_actions
        return task_actions.delete(request) if operation=='delete' else task_actions.prepare_replacement(request)
    if operation in {'keys-view','keys-save'}:
        from tools import task_keys
        return task_keys.view(request) if operation=='keys-view' else task_keys.save(request)
    if operation=='legacy-group': return legacy_group(request)
    if operation=='projects': return projects()
    if operation=='assemble': return assemble(request)
    if operation=='batches': return batches(request['category'])
    if operation=='view': return view(request)
    if operation=='plan': return plan(request)
    if operation=='start': return start(request)
    if operation=='resume': return resume(request)
    if operation=='pause': return pause(request)
    if operation=='retry': return resume({**request,'only_failed':True})
    raise ValueError('不支持的任务操作')

def cli(args):
    if args.operation=='worker':
        from tools.task_worker import run
        return run(args.category,args.batch,args.task)
    try:
        request=json.load(sys.stdin) if not sys.stdin.isatty() else {}
        result=dispatch(args.operation,request)
        print(json.dumps({'ok':True,'data':result},ensure_ascii=False));return 0
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False));return 1

def add_arguments(subparsers):
    p=subparsers.add_parser('tasks',help='Agent与看板共用的内容组及生成任务')
    p.add_argument('operation',choices=['projects','assemble','batches','view','plan','start','resume','pause','retry','delete','replacement-prepare','keys-view','keys-save','legacy-group','assets-view','assets-save','open-folder','package','worker'])
    p.add_argument('--category');p.add_argument('--batch');p.add_argument('--task');p.set_defaults(handler=cli)
