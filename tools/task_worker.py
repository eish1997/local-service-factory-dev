"""Detached shared task runner; reuses existing clients, request and image renderers."""
import copy
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from tools import task_library as lib
from tools import category_image_production as images
import image_generate


def save_task_raw(raw,payload,config,kind):
    if config.get('model')=='gpt-image-2-4k':
        from tools.category_4k_raw import save_4k_raw_png, WIDTH_TOLERANCE_SOURCE_CONTRACT
        if (config.get('raw_contract')!=WIDTH_TOLERANCE_SOURCE_CONTRACT or
                config.get('api_size')!='2560x3840' or config.get('quality')!='medium' or
                config.get('provider')!='relay' or str(config.get('base_url','')).rstrip('/')!='https://tinysnow.one/v1'):
            raise ValueError('TinySnow 4K 冻结请求参数或源图尺寸方案不一致')
        return save_4k_raw_png(raw,payload,archive_root=raw.parent/'originals',generation=config,
                              credential_epoch=None,anchor_y=0.0 if kind=='cover' else 0.5,
                              accepted_source_size='2352x3520',accepted_source_width_tolerance=16)
    return images.save_raw_png(raw,payload,(1024,1536),provider=config.get('provider'),archive_root=raw.parent/'originals')


def raw_valid(category,batch,group,unit):
    raw=lib.unit_raw(category,batch,group,unit);receipt=raw.with_suffix('.receipt.json')
    if not images.valid_png(raw,(1024,1536)) or not receipt.exists(): return False
    saved=lib.read(receipt)
    return saved.get('prompt_sha256')==unit['prompt_sha256'] and saved.get('raw_sha256')==hashlib.sha256(raw.read_bytes()).hexdigest()


def materialize(category,batch,data,rows,snapshot):
    cfg=snapshot['business'];services=cfg.get('service_items') or cfg.get('service_buttons') or []
    original=images.load_category_config
    images.load_category_config=lambda c:copy.deepcopy(cfg) if c==category else original(c)
    try:
        for row in rows:
            by_position={}
            for unit in row['units']: by_position.setdefault(unit['delivery_position'],[]).append(unit)
            for position,units in by_position.items():
                if not all(raw_valid(category,batch,row['group'],u) for u in units): continue
                kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
                target=lib.delivery_path(category,batch,row['group'],position,kind)
                if target.exists() and target.with_suffix('.validation.json').exists(): continue
                target.parent.mkdir(parents=True,exist_ok=True)
                records=[]
                for u in units:
                    record={**u,'index':(row['group']-1)*len(row['units'])+u['position'],'category_id':category,'generation_kind':u['kind'],'group_index':u['source_group'],
                        'raw_target':str(lib.unit_raw(category,batch,row['group'],u)),
                        'generation_target_id':f'{batch}:{u["id"]}','delivery_target_id':f'{batch}:g{row["group"]}:d{position}'}
                    record['service_items']=images._record_overlay_service_items(record,services)
                    records.append(record)
                if kind=='triptych': images.compose_triptych(records,target,data['phone'],services)
                else:
                    record=records[0]
                    images.apply_overlays(Path(record['raw_target']),target,data['phone'],kind,record['group_index'],position,
                        record['service_items'],record['final_size'],service_role=record.get('service_role'),
                        generation_target_id=record['generation_target_id'],delivery_target_id=record['delivery_target_id'],
                        category_id=category,structure_version=record['structure_version'],generation_mode=record['generation_mode'])
            # Persist the new namespace alongside the original unpackaged queue.
            produced=[]
            for position,units in by_position.items():
                kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
                target=lib.delivery_path(category,batch,row['group'],position,kind)
                if target.exists(): produced.append(str(target.resolve()))
            if produced and not data.get('replacement'):
                from tools.dashboard_delivery import load_state,write_state
                statefile=lib.ROOT/'.runtime/dashboard_delivery_state.json'
                with lib.lock(statefile.with_suffix('.lock')):
                    state=load_state(statefile)
                    project=state['projects'].setdefault(category,{'pending_groups':{}})
                    project.setdefault('pending_library_groups',{})[f'{batch}:{row["group"]}']={'batch_id':batch,'group_index':row['group'],'expected_image_count':len(by_position),'paths':produced,'updated_at':lib.now()}
                    write_state(statefile,state)
    finally: images.load_category_config=original


def _run(category,batch,task,*,generate=None,clients=None,render=None):
    path,data=lib.load_batch(category,batch);task=lib.identifier(task);file=path/'tasks'/task/'task.json'
    # Parent publishes pid under control lock; waiting avoids overwriting reserved requests.
    for _ in range(100):
        if not (path/'control.lock').exists(): break
        time.sleep(.05)
    with lib.lock(path/'tasks'/task/'worker.lock'):
        state=lib.read(file)
        license=lib.synchronize_license(file,state)
        if state['status']=='completed': return 0
        if state.get('authorization')!='execute_selected_groups': raise ValueError('任务缺少范围授权')
        rows=lib.selected(path,data,state['groups']);snapshot=lib.read(path/'snapshot.json')
        if state['manifest_sha256']!=data['manifest_sha256']: raise ValueError('冻结任务清单不一致')
        if generate is None:
            if lib.api_config()!=state['config']: raise ValueError('API配置与任务不一致')
            lib.validate_batch_phone(category,data,snapshot)
            blocks,_=lib.readiness(category,state['config'],snapshot)
            if blocks: raise ValueError('；'.join(blocks))
        config=copy.deepcopy(state['config']);guard=threading.Lock();stop=threading.Event();quarantine=set()
        state.update(status='running',pid=os.getpid(),updated_at=lib.now(),error=None)
        lib.write(file,state)
        def persist(): state['updated_at']=lib.now();lib.write(file,state)
        def event(value):
            with (file.parent/'events.jsonl').open('a',encoding='utf-8') as out: out.write(json.dumps({**value,'at':lib.now()},ensure_ascii=False)+'\n')
        def request_one(item,slot,client):
            while not stop.is_set() and not (file.parent/'pause.json').exists():
                lease=lib.lock(lib.ROOT/'.runtime/api-slots'/f'slot-{slot}.lock')
                try:lease.__enter__()
                except ValueError:time.sleep(.15);continue
                try:return perform_request(item,slot,client)
                finally:lease.__exit__(None,None,None)
            return False
        def perform_request(item,slot,client):
            group,unit=item;uid=unit['id']
            with guard:
                if stop.is_set() or (file.parent/'pause.json').exists() or slot in quarantine or state['requests_used']>=state['max_requests'] or state['attempts'].get(uid,0)>=2: return False
                state['requests_used']+=1;state['attempts'][uid]=state['attempts'].get(uid,0)+1
                state['results'][uid]={'status':'request_reserved','slot':slot,'attempt':state['attempts'][uid]}
                license.update(requests_used=state['requests_used'],attempts=dict(state['attempts']))
                lib.write(file.parent/'license.json',license);persist()
                request_number=state['requests_used'];attempt_number=state['attempts'][uid]
                event({'kind':'request_reserved','unit':uid,'group':group,'slot':slot,'model':config['model'],'request':state['requests_used'],'prompt_sha256':unit['prompt_sha256']})
            try:
                request_config=dict(config)
                if generate is None:
                    context=images.image_download_context(path,task,{'license_id':task,'plan_sha256':state['plan_sha256']},uid,request_number,attempt_number,config,unit['prompt'])
                    context['root']=str(lib.ROOT/'.runtime/image_download_receipts')
                    request_config['_image_download_context']=context
                payload=(generate or image_generate.generate_one)(client,request_config,unit['prompt'])
                raw=lib.unit_raw(category,batch,group,unit);raw.parent.mkdir(parents=True,exist_ok=True)
                save_result=save_task_raw(raw,payload,config,unit['kind'])
                lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'task':task,'unit':uid,'source':save_result})
                with guard:
                    state['results'][uid]={'status':'generated','slot':slot};state['consecutive_errors']=0
                    state['completed_units']=state.get('reused_units',0)+sum(v.get('status')=='generated' for v in state['results'].values())
                    event({'kind':'generated','unit':uid,'group':group,'slot':slot});persist()
                return True
            except Exception as error:
                classification=images.classify_request_error(error)
                with guard:
                    # Never persist provider exceptions which may contain keys or signed URLs.
                    state['results'][uid]={'status':'failed','slot':slot,'error':classification or type(error).__name__}
                    if isinstance(error,getattr(image_generate,'ReturnedImageDownloadError',())): state['results'][uid]['receipt_id']=getattr(error,'receipt_id',None)
                    state['consecutive_errors']=state.get('consecutive_errors',0)+1
                    if classification=='balance_exhausted': quarantine.add(slot)
                    if classification=='image_download_failed' or classification is None: stop.set()
                    if state['consecutive_errors']>=3: stop.set()
                    event({'kind':'failed','unit':uid,'group':group,'slot':slot,'error':classification or type(error).__name__});persist()
                return False
        try:
            queue=[(row['group'],u) for row in rows for u in row['units'] if not raw_valid(category,batch,row['group'],u) and state['attempts'].get(u['id'],0)<2]
            if state.get('retry_unit_ids') is not None:
                queue=[item for item in queue if item[1]['id'] in state['retry_unit_ids']]
            clients=(clients if clients is not None else images.openai_clients_by_slot(config,state['slots'])) if queue else []
            stage=0;limit=max(1,min(state['max_workers'],len(clients)));last_success=True
            while queue and not stop.is_set() and not (file.parent/'pause.json').exists() and state['requests_used']<state['max_requests']:
                available=[c for c in clients if c[0] not in quarantine]
                if not available: break
                width=min(limit,len(available),len(queue))
                chunk=queue[:width];queue=queue[width:]
                with ThreadPoolExecutor(max_workers=width) as pool:
                    outcomes=list(as_completed([pool.submit(request_one,item,*available[i]) for i,item in enumerate(chunk)]))
                    last_success=all(f.result() for f in outcomes)
                if any(slot not in quarantine for slot,_ in clients):
                    queue=[item for item in chunk if state['results'].get(item[1]['id'],{}).get('error')=='balance_exhausted' and state['attempts'].get(item[1]['id'],0)<2]+queue
                stage+=1
                (render or materialize)(category,batch,data,rows,snapshot)
            (render or materialize)(category,batch,data,rows,snapshot)
            done=all(raw_valid(category,batch,row['group'],u) for row in rows for u in row['units'])
            if done and data.get('replacement'):
                from tools.task_actions import commit_replacement
                with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
                    commit_replacement(category,batch,data)
            state.update(status='completed' if done else 'paused',completed_units=sum(raw_valid(category,batch,row['group'],u) for row in rows for u in row['units']),
                         quarantined_slots=sorted(quarantine),finished_at=lib.now())
            if not done: state['error']='已按要求暂停调度，已发出请求已收尾' if (file.parent/'pause.json').exists() else '请求预算耗尽' if state['requests_used']>=state['max_requests'] else '部分图片尚未完成；可在原预算内继续任务'
            persist();return 0 if done else 1
        except Exception as error:
            state.update(status='failed',error=type(error).__name__+'：本地执行失败，请让 Agent 检查',finished_at=lib.now());persist();return 1
        finally:
            for _,client in clients or []:
                if hasattr(client,'close'): client.close()


def run(category,batch,task,**test_hooks):
    try:
        from tools import runtime_paths
        snapshot=lib.read(lib.batch_dir(category,batch)/'snapshot.json')
        version=snapshot.get('rules_version','workspace')
        if version!='workspace':
            from tools.rule_updates import valid_version
            root=lib.ROOT/'.runtime/rules'/valid_version(version)
            if not (root/'manifest.json').is_file():raise ValueError('该批次冻结规则版本缺失，不能改用新规则继续')
            with runtime_paths.use_rules(root):return _run(category,batch,task,**test_hooks)
        return _run(category,batch,task,**test_hooks)
    except Exception as error:
        path=lib.batch_dir(category,batch)/'tasks'/lib.identifier(task)/'task.json'
        if path.exists():
            state=lib.read(path)
            # A second worker must not mark the legitimate owner as failed.
            if state.get('pid')!=os.getpid() and state.get('pid') and lib.alive(state['pid']): return 1
            state.update(status='failed',error=str(error) if isinstance(error,ValueError) else type(error).__name__,updated_at=lib.now())
            lib.write(path,state)
        return 1
