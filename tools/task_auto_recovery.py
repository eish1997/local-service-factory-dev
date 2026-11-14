"""Frozen completion policies; bounded repair licences retain main counters."""
import hashlib
import os
import re
from tools import task_library as lib


def policy(value,pending):
    if isinstance(value,dict) and value.get('mode')=='continuous':
        if set(value)-{'mode','total_max_requests'}:raise ValueError('持续补齐仅支持 mode 和 total_max_requests')
        cap=value.get('total_max_requests')
        if type(cap) is not int or not len(pending)<=cap<=100000:raise ValueError('整批最高请求数须为整数，至少覆盖每份待生成素材一次且不超过100000')
        main=min(len(pending)*2,cap)
        return {'enabled':bool(pending),'mode':'continuous','total_max_requests':cap,'max_requests':cap-main,'units':list(pending)}
    if isinstance(value,dict):
        if set(value)-{'enabled','rounds'}:raise ValueError('自动补缺配置仅支持 enabled 和 rounds')
        enabled=value.get('enabled',True);rounds=value.get('rounds',2)
    else:enabled=value;rounds=2
    if type(enabled) is not bool or type(rounds) is not int or not 1<=rounds<=2:
        raise ValueError('自动补缺最多两轮，每轮每个缺失素材最多两次请求')
    return {'enabled':enabled,'rounds':rounds if enabled else 0,'max_requests':len(pending)*2*rounds if enabled else 0,'units':list(pending) if enabled else []}


def cycle_limit(state):
    cfg=state.get('auto_complete',{})
    return cfg['total_max_requests'] if cfg.get('mode')=='continuous' else cfg.get('rounds',0)


def child_ids(parent,group,position,round_number):
    token=hashlib.sha256(f'{parent["batch"]}:{parent["id"]}:{group}:{position}:{round_number}'.encode()).hexdigest()[:28]
    return 'batch_revision_auto_'+token,'auto-'+token


def validate_child_parent(category,data,parent):
    """Private worker path only; public requests cannot choose a parent licence."""
    p=lib.batch_dir(category,parent['batch'])/'tasks'/parent['id']/'task.json'
    live=lib.read(p);lib.synchronize_license(p,live)
    cfg=live.get('auto_complete',{});binding=data.get('automatic_repair_parent',{})
    target=data.get('replacement',{});round_number=binding.get('round')
    if (live!=parent or live.get('pid')!=os.getpid() or live['status']!='recovering' or
            not cfg.get('enabled') or type(round_number) is not int or not 1<=round_number<=cycle_limit(live) or
            binding.get('task')!=live['id'] or binding.get('batch')!=live['batch'] or
            target.get('batch')!=live['batch'] or target.get('group') not in live['groups']):
        raise ValueError('自动补缺与原任务授权不一致')
    child,task=child_ids(live,target['group'],target['position'],round_number)
    if data['id']!=child or data.get('revision_kind')!='repair':raise ValueError('自动补缺标识无效')
    entry=live.get('auto_recovery',{}).get('children',{}).get(task)
    if not entry or entry['batch']!=child or entry['round']!=round_number:raise ValueError('自动补缺额度未登记')
    original=lib.selected(lib.batch_dir(category,live['batch']),lib.load_batch(category,live['batch'])[1],[target['group']])[0]['units']
    original=[u for u in original if u['delivery_position']==target['position']]
    fresh=lib.selected(lib.batch_dir(category,child),data,[1])[0]['units']
    if len(original)!=len(fresh) or any(a.get('service_role')!=b.get('service_role') or (a['prompt_sha256']!=b['prompt_sha256'] and not b.get('rebuilt_from_rejection')) for a,b in zip(original,fresh)):
        raise ValueError('自动补缺必须保留原提示词、主题及三拼顺序')
    from tools.task_worker import raw_valid
    childfile=lib.batch_dir(category,child)/'tasks'/task/'task.json'
    licensed=lib.read(childfile).get('unit_ids') if lib.io_path(childfile).exists() else None
    missing=[a['id'] for a,b in zip(original,fresh) if a['id'] in entry['units'] and (licensed is None or b['id'] in licensed) and not raw_valid(category,child,1,b)]
    if not set(missing)<=set(entry['units'])<=set(cfg['units']):raise ValueError('自动补缺素材超出冻结额度')
    validate_ledger(category,live)


def validate_ledger(category,state):
    cfg=state.get('auto_complete',{});per_round={}
    entries=state.get('auto_recovery',{}).get('children',{})
    targets={}
    if entries:
        origin=lib.batch_dir(category,state['batch'])
        for row in lib.task_rows(origin,lib.load_batch(category,state['batch'])[1],state):
            targets.update({u['id']:(row['group'],u['delivery_position']) for u in row['units']})
    for tid,e in entries.items():
        if (type(e.get('round')) is not int or not 1<=e['round']<=cycle_limit(state) or
                e.get('group') not in state['groups'] or type(e.get('position')) is not int or
                child_ids(state,e['group'],e['position'],e['round'])!=(e.get('batch'),tid)):
            raise ValueError('自动补缺范围或轮次无效')
        units=e.get('units',[])
        if len(units)!=len(set(units)) or not set(units)<=set(cfg['units']):raise ValueError('自动补缺素材超出许可')
        if any(targets.get(uid)!=(e['group'],e['position']) for uid in units):raise ValueError('自动补缺素材与图片范围不一致')
        bucket=per_round.setdefault(e['round'],set())
        if bucket.intersection(units):raise ValueError('同一素材在同轮重复预留补缺额度')
        bucket.update(units)
        file=lib.batch_dir(category,e['batch'])/'tasks'/tid/'task.json'
        if lib.io_path(file).exists():
            child=lib.read(file);lib.synchronize_license(file,child)
            binding=lib.load_batch(category,e['batch'])[1]
            if (child['groups']!=[1] or child.get('auto_complete',{}).get('enabled') or
                    child['manifest_sha256']!=binding['manifest_sha256'] or
                    binding.get('replacement')!={'batch':state['batch'],'group':e['group'],'position':e['position']} or
                    binding.get('automatic_repair_parent')!={'batch':state['batch'],'task':state['id'],'round':e['round']} or
                    child['max_requests']>len(units)*2 or child['config']!=state['config'] or not set(child['slots'])<=set(state['slots'])):
                raise ValueError('补缺子许可超出原授权')
    if cfg.get('mode')=='continuous':
        from tools.task_budget import progress
        progress(state)  # Mandatory frozen cap and reservation integrity check.
    elif sum(len(v)*2 for v in per_round.values())>cfg.get('max_requests',0):raise ValueError('自动补缺总额度超出许可')


def download_context(path,state,unit,result):
    from tools import category_image_production as images
    number=result.get('request_number');attempt=result.get('attempt') or state.get('attempts',{}).get(unit['id'])
    if type(number) is not int or type(attempt) is not int:return None
    ctx=images.image_download_context(path,state.get('download_job_id',state['id']),{'license_id':state['id'],'plan_sha256':state['plan_sha256']},unit['id'],number,attempt,state['config'],unit['prompt'])
    ctx['root']=str(lib.ROOT/'.runtime/image_download_receipts');return ctx


def spool_path(state,unit,number):
    identity=lib.digest({'category':state['category'],'batch':state['batch'],'task':state['id']})[:32]
    return lib.ROOT/'.runtime/returned-images'/identity/f'{unit["id"]}-{number}.bin'


def save_returned(state,unit,number,payload):
    if not isinstance(payload,bytes) or not 0<len(payload)<=64*1024*1024:raise ValueError('已返回图片数据无效')
    path=spool_path(state,unit,number);lib.io_path(path.parent).mkdir(parents=True,exist_ok=True)
    temporary=lib.io_path(path.with_suffix('.tmp'));temporary.write_bytes(payload);temporary.replace(lib.io_path(path))
    lib.write(path.with_suffix('.json'),{'task':state['id'],'batch':state['batch'],'unit':unit['id'],'request':number,
        'prompt_sha256':unit['prompt_sha256'],'payload_sha256':hashlib.sha256(payload).hexdigest()})


def returned_evidence_units(category,batch,state,rows,*,include_exhausted=False):
    """Read-only local recovery readiness, independent of paid repair rounds."""
    from tools import task_worker as worker,image_download_receipts as receipts
    path=lib.batch_dir(category,batch);units=[]
    ledger=state.get('auto_recovery',{})
    counts=ledger.get('local_attempts',{});limits=ledger.get('local_limits',{})
    for row in rows:
        for unit in row['units']:
            uid=unit['id']
            if not include_exhausted and counts.get(uid,0)>=limits.get(uid,3):continue
            if worker.raw_valid(category,batch,row['group'],unit):continue
            result=state.get('results',{}).get(unit['id'],{})
            context=download_context(path,state,unit,result)
            if context is None:continue
            saved=spool_path(state,unit,result['request_number'])
            if lib.io_path(saved).is_file() and lib.io_path(saved.with_suffix('.json')).is_file():
                units.append(uid);continue
            try:
                if receipts.load_pending_url(context):units.append(uid)
            except (OSError,ValueError,KeyError,TypeError,receipts.ReturnedImageDownloadError):pass
    return units


def has_returned_evidence(category,batch,state,rows):
    return bool(returned_evidence_units(category,batch,state,rows))


def prepare_local_resume(category,batch,state,rows,scope=None):
    """Explicit continue grants at most three more free attempts, retaining history."""
    for uid in returned_evidence_units(category,batch,state,rows,include_exhausted=True):
        if scope is not None and uid not in scope:continue
        ledger=state.setdefault('auto_recovery',{})
        count=ledger.get('local_attempts',{}).get(uid,0)
        limits=ledger.setdefault('local_limits',{})
        if count>=limits.get(uid,3):
            limits[uid]=count+3
            ledger.setdefault('local_resume_grants',[]).append({'unit':uid,'at':lib.now(),'from':count,'limit':count+3})


def recover_returned(category,batch,state,rows,file,once=False,only_ids=None):
    """Only private saved bytes or existing encrypted URL GETs; never an image POST."""
    from tools import task_worker as worker,image_download_receipts as receipts
    import image_generate
    path=lib.batch_dir(category,batch)
    counts=state.setdefault('auto_recovery',{}).setdefault('local_attempts',{})
    for row in rows:
        for unit in row['units']:
            uid=unit['id'];result=state.get('results',{}).get(uid,{})
            if only_ids is not None and uid not in only_ids:continue
            if worker.raw_valid(category,batch,row['group'],unit):continue
            ctx=download_context(path,state,unit,result)
            limit=state['auto_recovery'].get('local_limits',{}).get(uid,3)
            if ctx is None or counts.get(uid,0)>=limit:continue
            for _ in range(1):
                if pause_requested(category,batch,state):return
                counts[uid]=counts.get(uid,0)+1;lib.write(file,state)
                try:
                    saved=spool_path(state,unit,result['request_number']);meta=lib.read(saved.with_suffix('.json')) if lib.io_path(saved.with_suffix('.json')).exists() else None
                    if meta:
                        expected={'task':state['id'],'batch':batch,'unit':uid,'request':result['request_number'],'prompt_sha256':unit['prompt_sha256']}
                        if any(meta.get(k)!=v for k,v in expected.items()) or lib.io_path(saved).stat().st_size>64*1024*1024:raise ValueError('已返回图片凭据不一致')
                        payload=lib.io_path(saved).read_bytes()
                        if hashlib.sha256(payload).hexdigest()!=meta['payload_sha256']:raise ValueError('已返回图片损坏')
                    else:
                        url=receipts.load_pending_url(ctx)
                        payload=image_generate.download_image_url(url,timeout=180)
                        save_returned(state,unit,result['request_number'],payload)
                    raw=lib.unit_raw(category,batch,row['group'],unit)
                    stage=raw.parent/'.recovery'/f'{uid}-{result["request_number"]}.png';lib.io_path(stage.parent).mkdir(parents=True,exist_ok=True)
                    source=worker.save_task_raw(stage,payload,state['config'],unit['kind'])
                    sha=hashlib.sha256(lib.io_path(stage).read_bytes()).hexdigest()
                    lib.write(stage.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':sha,'task':state['id'],'unit':uid,'source':source})
                    if not worker.raw_evidence_valid(stage,unit):raise ValueError('恢复原图校验失败')
                    for prior in (raw,raw.with_suffix('.receipt.json')):
                        if lib.io_path(prior).exists():
                            evidence=stage.parent/f'{uid}-{result["request_number"]}-{counts[uid]}-{prior.name}.evidence'
                            lib.io_path(prior).replace(lib.io_path(evidence))
                    lib.io_path(stage).replace(lib.io_path(raw));lib.io_path(stage.with_suffix('.receipt.json')).replace(lib.io_path(raw.with_suffix('.receipt.json')))
                    receipts.mark_materialized(ctx,sha)
                    state['results'][uid]={'status':'generated','recovered_locally':True,'request_number':result['request_number'],'attempt':result['attempt']}
                    lib.write(file,state);break
                except Exception as error:
                    state['auto_recovery'].setdefault('local_errors',{})[uid]=type(error).__name__;lib.write(file,state)


def pause_requested(category,batch,state):
    if lib.io_path(lib.batch_dir(category,batch)/'tasks'/state['id']/'pause.json').exists():return True
    data=lib.load_batch(category,batch)[1];parent=data.get('automatic_repair_parent')
    return bool(parent and lib.io_path(lib.batch_dir(category,parent['batch'])/'tasks'/parent['task']/'pause.json').exists())


def remaining(state):
    cfg=state.get('auto_complete',{})
    return bool(cfg.get('enabled') and not state.get('auto_recovery',{}).get('finished'))


def paid_continuation(category,batch,rows,state):
    """Read-only: distinguish remaining repair POSTs from free/local recovery."""
    from tools import task_worker as worker,task_recovery as recovery
    if not state.get('auto_complete',{}).get('enabled'):return False
    if state['auto_complete'].get('mode')!='continuous' and not remaining(state):return False
    validate_ledger(category,state)
    if state['auto_complete'].get('mode')=='continuous':
        from tools.task_budget import progress
        if not progress(state)['remaining']:return False
    for row in rows:
        for position in sorted({u['delivery_position'] for u in row['units']}):
            units=[u for u in row['units'] if u['delivery_position']==position]
            if all(worker.raw_valid(category,batch,row['group'],u) for u in units):continue
            source_batch=batch;source_group=row['group'];source_units=units;source_state=state;last_round=0
            numbers=sorted({e['round'] for e in state.get('auto_recovery',{}).get('children',{}).values()
                            if e['group']==row['group'] and e['position']==position})
            for number in numbers:
                child,tid=child_ids(state,row['group'],position,number);path=lib.batch_dir(category,child)
                if not lib.io_path(path/'batch.json').exists():continue
                childdata=lib.load_batch(category,child)[1]
                source_batch=child;source_group=1;source_units=lib.selected(path,childdata,[1])[0]['units'];last_round=number
                file=path/'tasks'/tid/'task.json'
                source_state=lib.read(file) if lib.io_path(file).exists() else None
                if source_state is not None:lib.synchronize_license(file,source_state)
            if all(worker.raw_valid(category,source_batch,source_group,u) for u in source_units):continue
            if source_state is not None:
                ready,summary=recovery.partition(category,source_batch,[{'group':source_group,'units':source_units}],source_state)
                if last_round and ready:return True
                blocked_reasons={item['reason'] for item in summary['blocked']}
                if blocked_reasons&{'uncertain','download','saved_result'}:
                    if (not ready and state['auto_complete'].get('mode')=='continuous'
                            and blocked_reasons<={'uncertain','download','non_retryable'}):return True
                    continue
                if last_round>=cycle_limit(state):continue
            elif last_round:
                # A crash during reused-raw copy does not authorize another POST.
                binding=childdata['repair_source'];original=lib.load_batch(category,binding['batch'])
                by_id={u['id']:u for r in lib.selected(original[0],original[1],[binding['group']]) for u in r['units']}
                source_units=[by_id[uid] for uid in binding['units']]
                source_batch=binding['batch'];source_group=binding['group']
                if all(worker.raw_valid(category,source_batch,source_group,u) for u in source_units):continue
                try:recovery.protect_returned_results(category,source_batch,source_group,source_units)
                except ValueError:continue
            if any((lib.io_path(lib.unit_raw(category,source_batch,source_group,u)).exists() or
                    lib.io_path(lib.unit_raw(category,source_batch,source_group,u).with_suffix('.receipt.json')).exists())
                   for u in source_units if not worker.raw_valid(category,source_batch,source_group,u)):continue
            if any(u['id'] not in state['auto_complete']['units'] for u in units
                   if not worker.raw_valid(category,batch,row['group'],u)):continue
            if not recovery.automatic_candidates(category,source_batch,source_group,source_units):
                if state['auto_complete'].get('mode')=='continuous' and recovery.leftover_ids(category,source_batch,source_group,source_units)[0]:return True
                continue
            return True
    return False


def restore_child_slots(state,child):
    """Only a new, explicitly validated parent resume can lift old isolation."""
    epoch=state.get('resume_key_epoch')
    if epoch and child.get('parent_key_epoch')!=epoch:
        child['quarantined_slots']=[];child['parent_key_epoch']=epoch
    child['quarantined_slots']=sorted(set(child.get('quarantined_slots',[]))|set(state.get('quarantined_slots',[])))


def final_failures(state):
    """Return bounded, non-secret diagnostics for the latest unresolved child only."""
    from tools import task_worker as worker,task_recovery as recovery
    if not state.get('auto_recovery') or state.get('status')=='completed':return []
    try:
        category=state['category'];path,data=lib.load_batch(category,state['batch'])
        targets={};failures={}
        # Polling the dashboard must not hash every successful photograph again.
        candidates={item['unit'] for item in state.get('resume_summary',{}).get('blocked',[]) if 'unit' in item}
        candidates.update(uid for entry in state['auto_recovery'].get('children',{}).values() for uid in entry.get('units',[]))
        candidates.update(uid for uid,result in state.get('results',{}).items() if result.get('status') in {'failed','request_reserved'})
        for row in lib.task_rows(path,data,state):
            for unit in row['units']:
                targets[unit['id']]=(row['group'],unit)
                if unit['id'] not in candidates:continue
                if worker.raw_valid(category,state['batch'],row['group'],unit):continue
                reason=recovery.blocked_reason(state,unit) or 'uncertain'
                failures[unit['id']]={'unit':unit['id'],'group':row['group'],'position':unit['delivery_position'],
                    'round':0,'reason':reason,'message':recovery.REASONS[reason]}
                result=state.get('results',{}).get(unit['id'],{});code=result.get('http_status');classification=result.get('error')
                if type(code) is int and 100<=code<=599:failures[unit['id']]['http_status']=code
                if isinstance(classification,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}',classification):failures[unit['id']]['classification']=classification
        entries=state['auto_recovery'].get('children',{})
        for tid,e in sorted(entries.items(),key=lambda pair:pair[1].get('round',0)):
            if child_ids(state,e['group'],e['position'],e['round'])!=(e['batch'],tid):continue
            childpath,childdata=lib.load_batch(category,e['batch']);file=childpath/'tasks'/tid/'task.json'
            if not lib.io_path(file).exists():continue
            child=lib.read(file);lib.synchronize_license(file,child)
            original=[u for g,u in targets.values() if g==e['group'] and u['delivery_position']==e['position']]
            fresh=lib.selected(childpath,childdata,[1])[0]['units']
            if len(original)!=len(fresh):continue
            for unit,source in zip(original,fresh):
                if unit['id'] not in failures:continue
                result=child.get('results',{}).get(source['id'],{})
                reason=recovery.blocked_reason(child,source) or 'uncertain'
                item={**failures[unit['id']],'round':e['round'],'reason':reason,'message':recovery.REASONS[reason]}
                classification=result.get('error')
                if isinstance(classification,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}',classification):item['classification']=classification
                code=result.get('http_status')
                if type(code) is int and 100<=code<=599:item['http_status']=code
                failures[unit['id']]=item
        return list(failures.values())
    except (OSError,ValueError,KeyError,TypeError):return []


def public_progress(state):
    if state.get('auto_complete',{}).get('mode')=='continuous':
        from tools.task_budget import progress
        budget=progress(state)
        return {'total_requests_used':budget['used'],'total_max_requests':budget['maximum'],
                'shared_budget':budget,'auto_failures':final_failures(state)}
    used=0
    for tid,e in state.get('auto_recovery',{}).get('children',{}).items():
        try:
            if child_ids(state,e['group'],e['position'],e['round'])!=(e['batch'],tid):continue
            used+=lib.read(lib.batch_dir(state['category'],e['batch'])/'tasks'/tid/'license.json')['requests_used']
        except (OSError,ValueError,KeyError,TypeError):pass
    return {'total_requests_used':state['requests_used']+used,'total_max_requests':state['max_requests']+state.get('auto_complete',{}).get('max_requests',0),'auto_failures':final_failures(state)}


def open_leftover_repairs(category,batch,task,state,render_rows,snapshot,ledger,blocked,hooks,persist,publish_child):
    """One child licence after the batch is otherwise finished. Old charges stay."""
    from tools import task_worker as worker,task_actions as actions,task_recovery as recovery
    from tools.task_budget import progress
    if state.get('auto_complete',{}).get('mode')!='continuous' or pause_requested(category,batch,state):return False
    if not progress(state)['remaining']:return False
    number=max((entry['round'] for entry in ledger['children'].values()),default=0)+1
    if number>cycle_limit(state):return False
    follow=False
    for row in render_rows:
        for position in sorted({u['delivery_position'] for u in row['units']}):
            if pause_requested(category,batch,state):return True
            units=[u for u in row['units'] if u['delivery_position']==position]
            if all(worker.raw_valid(category,batch,row['group'],u) for u in units):continue
            from tools.task_controls import paused as paused_units
            missing_units=[u for u in units if not worker.raw_valid(category,batch,row['group'],u)]
            if missing_units and all(u['id'] in paused_units(state,lib.load_batch(category,batch)[1]) for u in missing_units):continue
            kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
            review=lib.validation_record(lib.delivery_path(category,batch,row['group'],position,kind).with_suffix('.validation.json'))
            if review.get('status') in {'rejected','needs_fix'} or review.get('decision')=='rejected':continue
            allowed,reassemble=recovery.leftover_ids(category,batch,row['group'],units)
            done=set(ledger.get('reassembly_blocked') or [])
            allowed=[uid for uid in allowed if uid not in done]
            reassemble=[uid for uid in reassemble if uid not in done]
            if not allowed:continue
            child,tid=child_ids(state,row['group'],position,number)
            try:
                with lib.lock(lib.ROOT/'.runtime/task-admin.lock',wait_seconds=10):
                    dest=lib.batch_dir(category,child)
                    req={'category':category,'batch':batch,'group':row['group'],'position':position,'source':'automatic-repair',
                         '_automatic_unit_ids':allowed,'_allow_blocked_reasons':['uncertain','download'],'_reassemble_unit_ids':reassemble}
                    if lib.io_path(dest/'batch.json').exists():saved=lib.read(dest/'batch.json');actions.restore_repair_sources(category,saved)
                    else:
                        saved=actions.prepare_repair(req,lib.load_batch(category,batch)[1],snapshot,units,dest,child)
                        saved['automatic_repair_parent']={'batch':batch,'task':task,'round':number};lib.write(dest/'batch.json',saved)
                    fresh=lib.selected(dest,saved,[1])[0]['units']
                    eligible={i for i,u in enumerate(units) if u['id'] in allowed}
                    missing=[a['id'] for i,(a,b) in enumerate(zip(units,fresh)) if i in eligible and a['id'] in state['auto_complete']['units'] and not worker.raw_valid(category,child,1,b)]
                    if not missing or not set(missing)<=set(state['auto_complete']['units']):raise ValueError('缺失素材不在原任务补缺许可内')
                    ledger['children'].setdefault(tid,{'batch':child,'round':number,'group':row['group'],'position':position,'units':missing})
                    persist()
                    childfile=dest/'tasks'/tid/'task.json'
                    if not lib.io_path(childfile).exists():
                        request={'category':category,'batch':child,'groups':[1],'auto_complete':False,'request_id':tid,'authorization':'execute_selected_groups','source':'automatic-repair'}
                        request['unit_ids']=[b['id'] for a,b in zip(units,fresh) if a['id'] in missing]
                        if lib.apply_detected_models(file,state):persist()
                        planned=lib.plan(request,_parent=state)
                        if planned['blocks']:raise ValueError('；'.join(planned['blocks']))
                        lib._start({**request,'plan_sha256':planned['plan_sha256']},_parent=state,launch_task=False)
                        c=lib.read(childfile);restore_child_slots(state,c);lib.write(childfile,c)
                    else:
                        c=lib.read(childfile);lib.synchronize_license(childfile,c)
                        if c['status']=='cancelled':raise ValueError('补缺任务已取消')
                        restore_child_slots(state,c)
                        c.update(pid=os.getpid(),status='queued');lib.write(childfile,c)
                worker.run(category,child,tid,**hooks)
                c=lib.read(childfile);state['quarantined_slots']=sorted(set(state.get('quarantined_slots',[]))|set(c.get('quarantined_slots',[])))
                recover_returned(category,child,c,lib.selected(dest,saved,[1]),childfile)
                publish_child(dest,saved,c,childfile)
                if c['status']=='paused' and c.get('resume_summary',{}).get('ready_count'):follow=True
                if c.get('resume_summary',{}).get('paused_count'):follow=True
                persist()
            except ValueError as error:
                blocked.append({'group':row['group'],'position':position,'round':number,'reason':str(error)[:200]})
                if '未能组成不同提示词' in str(error):
                    saved_ids=ledger.setdefault('reassembly_blocked',[])
                    for uid in reassemble:
                        if uid not in saved_ids:saved_ids.append(uid)
                if 'API配置' in str(error) or '密钥' in str(error) or 'Key' in str(error):follow=True
            if follow:return True
    return follow


def finish(category,batch,task,**hooks):
    from tools import task_worker as worker,task_actions as actions,task_recovery as recovery
    path,data=lib.load_batch(category,batch);file=path/'tasks'/task/'task.json';state=lib.read(file)
    if state['status']!='recovering':return 0 if state['status'] in {'completed','completed_with_errors'} else 1
    with lib.lock(file.parent/'worker.lock'):
        lib.synchronize_license(file,state)
        rows=lib.task_rows(path,data,state);render_rows=lib.delivery_rows(path,data,state);snapshot=lib.read(path/'snapshot.json')
        ledger=state.setdefault('auto_recovery',{});ledger.setdefault('children',{})
        def persist():
            validate_ledger(category,state)
            used=0
            for tid,e in ledger['children'].items():
                childfile=lib.batch_dir(category,e['batch'])/'tasks'/tid/'task.json'
                if lib.io_path(childfile).exists():
                    child=lib.read(childfile);lib.synchronize_license(childfile,child);used+=child['requests_used']
            ledger['requests_used']=used;state['updated_at']=lib.now();lib.write(file,state)
        def local_render():
            if hooks.get('render'):hooks['render'](category,batch,lib.load_batch(category,batch)[1],render_rows,snapshot)
            else:
                tries=ledger.setdefault('render_attempts',{})
                state['local_library_errors']=worker.register_library(category,batch,rows)
                state['local_render_errors']=worker.materialize(category,batch,lib.load_batch(category,batch)[1],render_rows,snapshot,attempts=tries)
            persist()
        def publish_child(dest,saved,childstate,childfile):
            childrows=lib.selected(dest,saved,[1]);fresh=childrows[0]['units']
            if not all(worker.raw_valid(category,saved['id'],1,u) for u in fresh):return
            if hooks.get('render'):hooks['render'](category,saved['id'],saved,childrows,lib.read(dest/'snapshot.json'))
            else:worker.materialize(category,saved['id'],saved,childrows,lib.read(dest/'snapshot.json'))
            with lib.lock(lib.ROOT/'.runtime/task-admin.lock',wait_seconds=10):
                if actions.commit_replacement(category,saved['id'],saved):
                    childstate.update(status='completed',completed_units=len(fresh),error=None,finished_at=lib.now())
                    lib.write(childfile,childstate)
        ledger['phase']='恢复返回图片';persist();recover_returned(category,batch,state,rows,file)
        for tid,entry in ledger['children'].items():
            childpath=lib.batch_dir(category,entry['batch']);childfile=childpath/'tasks'/tid/'task.json'
            if not lib.io_path(childfile).exists():continue
            childstate=lib.read(childfile);lib.synchronize_license(childfile,childstate,repair_budget=True)
            childdata=lib.load_batch(category,entry['batch'])[1]
            if childstate['manifest_sha256']!=childdata['manifest_sha256']:
                raise ValueError('补齐子任务冻结清单不一致，不能免费恢复或发布')
            validate_child_parent(category,childdata,state)
            recover_returned(category,entry['batch'],childstate,lib.task_rows(childpath,childdata,childstate),childfile)
            publish_child(childpath,childdata,childstate,childfile)
        local_render()
        blocked=[];waiting=False;unit_waiting=False
        continuous=state['auto_complete'].get('mode')=='continuous'
        existing_cycle_max=max((e['round'] for e in ledger['children'].values()),default=0)
        from tools.task_budget import progress
        for number in range(1,cycle_limit(state)+1):
            before_used=progress(state)['used'] if continuous else None
            if continuous and not progress(state)['remaining']:break
            ledger.update(phase='持续补齐中' if continuous else f'自动补缺第 {number} 轮',round=number);persist()
            for row in render_rows:
                positions=sorted({u['delivery_position'] for u in row['units']})
                for position in positions:
                    if pause_requested(category,batch,state):waiting=True;break
                    units=[u for u in row['units'] if u['delivery_position']==position]
                    kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
                    if all(worker.raw_valid(category,batch,row['group'],u) for u in units):continue
                    from tools.task_controls import paused as paused_units
                    paused_ids=paused_units(state,data)
                    missing_units=[u for u in units if not worker.raw_valid(category,batch,row['group'],u)]
                    if missing_units and all(u['id'] in paused_ids for u in missing_units):unit_waiting=True;continue
                    target=lib.delivery_path(category,batch,row['group'],position,kind)
                    review=lib.validation_record(target.with_suffix('.validation.json'))
                    if review.get('status') in {'rejected','needs_fix'} or review.get('decision')=='rejected':
                        blocked.append({'group':row['group'],'position':position,'reason':'图片未通过审核，不能自动重做'});continue
                    child,tid=child_ids(state,row['group'],position,number)
                    try:
                        with lib.lock(lib.ROOT/'.runtime/task-admin.lock',wait_seconds=10):
                            dest=lib.batch_dir(category,child)
                            prior_id=child_ids(state,row['group'],position,number-1)[0] if number>1 else None
                            req={'category':category,'batch':batch,'group':row['group'],'position':position,'source':'automatic-repair'}
                            if prior_id and lib.io_path(lib.batch_dir(category,prior_id)/'batch.json').exists():req['source_revision']=prior_id
                            candidate_batch=prior_id if req.get('source_revision') else batch
                            candidate_group=1 if req.get('source_revision') else row['group']
                            candidate_data=lib.load_batch(category,candidate_batch)
                            candidate_units=[u for u in lib.selected(candidate_data[0],candidate_data[1],[candidate_group])[0]['units'] if u['delivery_position']==position]
                            allowed=recovery.automatic_candidates(category,candidate_batch,candidate_group,candidate_units)
                            # Existing child licences remain authoritative, including
                            # requests still available after an earlier pause.
                            if not allowed and not lib.io_path(dest/'tasks'/tid/'task.json').exists():
                                blocked.append({'group':row['group'],'position':position,'round':number,'reason':'不可自动重复的请求需核对；冻结提示词不原样重发'})
                                continue
                            req['_automatic_unit_ids']=allowed
                            if lib.io_path(dest/'batch.json').exists():saved=lib.read(dest/'batch.json');actions.restore_repair_sources(category,saved)
                            else:
                                saved=actions.prepare_repair(req,lib.load_batch(category,batch)[1],snapshot,units,dest,child)
                                saved['automatic_repair_parent']={'batch':batch,'task':task,'round':number};lib.write(dest/'batch.json',saved)
                            fresh=lib.selected(dest,saved,[1])[0]['units']
                            eligible_indices={i for i,u in enumerate(candidate_units) if u['id'] in allowed}
                            missing=[a['id'] for i,(a,b) in enumerate(zip(units,fresh)) if i in eligible_indices and a['id'] in state['auto_complete']['units'] and not worker.raw_valid(category,child,1,b)]
                            if not set(missing)<=set(state['auto_complete']['units']):raise ValueError('缺失素材不在原任务补缺许可内')
                            ledger['children'].setdefault(tid,{'batch':child,'round':number,'group':row['group'],'position':position,'units':missing})
                            persist()
                            childfile=dest/'tasks'/tid/'task.json'
                            if not lib.io_path(childfile).exists():
                                request={'category':category,'batch':child,'groups':[1],'auto_complete':False,'request_id':tid,'authorization':'execute_selected_groups','source':'automatic-repair'}
                                request['unit_ids']=[b['id'] for a,b in zip(units,fresh) if a['id'] in missing]
                                if lib.apply_detected_models(file,state):persist()
                                planned=lib.plan(request,_parent=state)
                                if planned['blocks']:raise ValueError('；'.join(planned['blocks']))
                                lib._start({**request,'plan_sha256':planned['plan_sha256']},_parent=state,launch_task=False)
                                c=lib.read(childfile);restore_child_slots(state,c);lib.write(childfile,c)
                            else:
                                c=lib.read(childfile);lib.synchronize_license(childfile,c)
                                if c['status']=='cancelled':raise ValueError('补缺任务已取消')
                                restore_child_slots(state,c)
                                c.update(pid=os.getpid(),status='queued');lib.write(childfile,c)
                        worker.run(category,child,tid,**hooks)
                        c=lib.read(childfile);state['quarantined_slots']=sorted(set(state.get('quarantined_slots',[]))|set(c.get('quarantined_slots',[])))
                        # Returned child results are restored for free before any next round.
                        recover_returned(category,child,c,lib.selected(dest,saved,[1]),childfile)
                        publish_child(dest,saved,c,childfile)
                        if c['status']=='paused' and c.get('resume_summary',{}).get('ready_count'):waiting=True
                        if c.get('resume_summary',{}).get('paused_count'):unit_waiting=True
                        persist()
                    except ValueError as error:
                        blocked.append({'group':row['group'],'position':position,'round':number,'reason':str(error)[:200]})
                        # Configuration/key problems preserve the unspent envelope for resume.
                        if 'API配置' in str(error) or '密钥' in str(error) or 'Key' in str(error):waiting=True
                    if waiting:break
                if waiting:break
            if waiting:break
            if continuous and number>existing_cycle_max and progress(state)['used']==before_used:break
        if continuous and not waiting and progress(state)['remaining']:
            if open_leftover_repairs(category,batch,task,state,render_rows,snapshot,ledger,blocked,hooks,persist,publish_child):waiting=True
        local_render()
        _,summary=recovery.partition(category,batch,rows,state);state['resume_summary']=summary
        complete=summary['reused_count']==state['total_units'] and not state.get('local_render_errors') and not state.get('local_library_errors') and (
            state.get('unit_ids') is not None or all(worker.delivery_valid(lib.delivery_path(category,batch,r['group'],u['delivery_position'],'triptych' if u['kind']=='triptych_panel' else u['kind']),u) for r in rows for u in r['units']))
        waiting=waiting or unit_waiting or summary.get('paused_count',0)>0
        if continuous and not complete and has_returned_evidence(category,batch,state,rows):waiting=True
        leftover_open=False
        if continuous and not complete and not pause_requested(category,batch,state) and progress(state)['remaining'] and summary['ready_count']==0:
            skipped=set(ledger.get('reassembly_blocked') or [])
            for row in rows:
                for position in {u['delivery_position'] for u in row['units']}:
                    ids,_=recovery.leftover_ids(category,batch,row['group'],[u for u in row['units'] if u['delivery_position']==position])
                    if any(uid not in skipped for uid in ids):leftover_open=True;break
                if leftover_open:break
        ledger['blocked']=blocked;ledger['finished']=not waiting and not leftover_open
        if leftover_open:ledger['phase']='待继续补齐'
        else:ledger['phase']='已完成' if complete else '已暂停' if waiting else ('等待追加额度' if not progress(state)['remaining'] else '原图待处理') if continuous else '补缺已结束'
        state.update(status='completed' if complete else 'paused' if waiting or leftover_open else 'completed_with_errors',completed_units=summary['reused_count'],skipped_units=summary['blocked_count'],finished_at=lib.now())
        ledger['failures']=final_failures(state)
        state['error']=None if complete else '已按要求暂停，继续将沿用剩余补缺额度' if pause_requested(category,batch,state) else '自动补缺暂不可继续，剩余额度已保留' if waiting and not leftover_open else f'自动补缺已结束，仍缺 {state["total_units"]-summary["reused_count"]} 个素材'+(f'，另有 {len(state.get("local_render_errors",[]))} 张本地合成待处理' if state.get('local_render_errors') else '')+'；请展开查看原因'
        if leftover_open:state['error']=f'待继续补齐，仍缺 {state["total_units"]-summary["reused_count"]} 个素材；结果不明、下载失败和明确拒绝会在剩余额度内重新请求'
        elif continuous and not complete and not waiting:state['error']=ledger['phase']+f'，仍缺 {state["total_units"]-summary["reused_count"]} 个素材；已完成结果及尝试记录保留'
        if state.get('local_library_errors'):state['error']+='；原图库归档待本地恢复，不需要重新生图'
        persist();return 0 if not waiting else 1
