"""Bounded, read-only card diagnostics. Never infer a new execution licence."""
import datetime
import json
from tools import task_library as lib

ERRORS={'transient':'临时故障','retryable_rejection':'未识别原因的拒绝，整批额度内重试','balance_exhausted':'余额不足','authentication_failed':'鉴权失败',
        'image_download_failed':'返回图片下载失败','local_save_failed':'本地保存失败','request_rejected':'请求被拒绝'}
STATUSES={'request_reserved':'已预留请求，结果待核实','generated':'图片已返回','failed':'请求失败','unknown':'记录缺失'}


def safe_time(value):
    try:return datetime.datetime.fromisoformat(value).isoformat() if isinstance(value,str) and len(value)<=40 else None
    except ValueError:return None


def events(state):
    """Allowlisted projections only; bounded file reads and per-unit records."""
    base=lib.batch_dir(state['category'],state['batch'])
    path=base/'tasks'/lib.identifier(state['id'])/'events.jsonl'
    rows={};note=None
    try:
        path.resolve().relative_to(base.resolve())
        if not lib.io_path(path).exists():return rows,'逐次事件未登记，显示许可计数和末次状态'
        if lib.io_path(path).stat().st_size>2*1024*1024:return rows,'事件记录超过读取上限，显示许可计数和末次状态'
        with lib.io_path(path).open(encoding='utf-8') as source:
            for line in source:
                if len(line)>8192:note='部分事件记录无效';continue
                try:event=json.loads(line)
                except (ValueError,TypeError):note='部分事件记录无效';continue
                if not isinstance(event,dict):note='部分事件记录无效';continue
                uid=event.get('unit');kind=event.get('kind')
                if not isinstance(uid,str) or not isinstance(kind,str) or uid not in state['attempts'] or kind not in {'request_reserved','generated','failed'}:continue
                records=rows.setdefault(uid,[])
                if kind=='request_reserved':
                    number=event.get('request')
                    if type(number) is not int or not 1<=number<=state['requests_used']:continue
                    if any(r['request_number']==number for r in records):continue
                    if len(records)>=state['attempts'][uid]:continue
                    records.append({'attempt':len(records)+1,'request_number':number,'status':kind,'at':safe_time(event.get('at'))})
                elif records:
                    records[-1].update(status=kind)
                    if kind=='failed':records[-1]['error_code']=event.get('error') if isinstance(event.get('error'),str) and event['error'] in ERRORS else 'non_retryable'
    except (OSError,ValueError):return {},'事件记录不可读取，显示许可计数和末次状态'
    return rows,note


def view(request):
    from tools.task_queue import view as queue_view
    category=request['category'];batch=lib.identifier(request['batch']);uid=lib.identifier(request['unit'])
    detail={'unit':uid};queue_view({'category':category,'batch':batch,'summary_only':True},_detail=detail)
    if 'card' not in detail:raise ValueError('原图卡片不存在或已移除')
    card=detail['card'];licences=[];used=0;maximum=0;future=0;notes=[]
    from tools.task_budget import progress
    shared_parent=next((s for s in detail['states'] if s.get('auto_complete',{}).get('mode')=='continuous'),None)
    shared=shared_parent.get('_queue_shared_budget') if shared_parent else None
    if request.get('card_id') not in (None,card['id']):raise ValueError('原图卡片关联已变化')
    # Display envelopes only when the child is actually assigned to the frozen
    # parent. This is a read check, never execution validation or ledger repair.
    for child in detail['states']:
        binding=child.get('_automatic_parent')
        if not binding:continue
        parent=next((s for s in detail['states'] if s['batch']==binding.get('batch') and s['id']==binding.get('task')),None)
        entry=parent.get('auto_recovery',{}).get('children',{}).get(child['id']) if parent else None
        from tools.task_auto_recovery import child_ids,cycle_limit
        number=binding.get('round')
        if (not parent or not isinstance(entry,dict) or type(number) is not int or
            not parent.get('auto_complete',{}).get('enabled') or not 1<=number<=cycle_limit(parent) or
            entry.get('batch')!=child['batch'] or entry.get('round')!=number or
            child_ids(parent,entry['group'],entry['position'],number)!=(child['batch'],child['id']) or
            parent['_queue_unit'] not in entry.get('units',[]) or parent['_queue_unit'] not in parent['auto_complete']['units'] or
            child['max_requests']>2*len(entry['units'])):
            raise ValueError('原图补缺记录与冻结父许可不一致')
    frozen_reuse={}
    for state in detail['states']:
        unit=state['_queue_unit'];count=state['attempts'].get(unit,0)
        cfg=state.get('auto_complete',{})
        if state['batch'] not in frozen_reuse:
            from tools.raw_library import selection
            _,data=lib.load_batch(category,state['batch'])
            frozen_reuse[state['batch']]={item['unit'] for item in selection(data)['bindings']}
        if state.get('_pending_frozen'):
            retained=unit not in state['pending_unit_ids']
        else:
            retained=state.get('_queue_inherited') or unit in frozen_reuse[state['batch']] or cfg.get('enabled') and unit not in cfg.get('units',[])
            if not retained:notes.append('旧许可未冻结初始生成单元，展示单元两次硬上限；能否继续仍以原任务校验为准')
        limit=0 if retained else min(2,state['max_requests'])
        if count>limit:raise ValueError('原图计数超过冻结素材范围')
        remaining=min(max(0,limit-count),max(0,state['max_requests']-state['requests_used']))
        binding=state.get('_automatic_parent');round_number=binding['round'] if binding else 0
        if cfg.get('enabled') and cfg.get('mode')!='continuous' and unit in cfg.get('units',[]):
            issued={parent.get('round') for child in detail['states'] if (parent:=child.get('_automatic_parent')) and parent.get('batch')==state['batch'] and parent.get('task')==state['id']}
            future+=2*max(0,cfg['rounds']-len(issued))
        records,note=events(state) if count else ({},None);records=records.get(unit,[])
        if note:notes.append(note)
        result=state.get('results',{}).get(unit,{})
        unassigned=[]
        if len(records)<count:
            notes.append('部分逐次记录缺失；无法确定序号的事件单独展示，许可计数不变')
            saved=records;records=[{'attempt':i+1,'status':'unknown','at':None} for i in range(count)]
            for event in saved:
                number=result.get('attempt')
                if (type(number) is int and 1<=number<=count and
                    type(result.get('request_number')) is int and event['request_number']==result['request_number']):
                    records[number-1]={**event,'attempt':number}
                else:unassigned.append({**event,'attempt':None})
        if records:
            if result.get('status') in STATUSES:records[-1]['status']=result['status']
            if result.get('error'):records[-1]['error_code']=result['error'] if isinstance(result['error'],str) and result['error'] in ERRORS else 'non_retryable'
            code=result.get('http_status')
            if type(code) is int and 100<=code<=599:records[-1]['http_status']=code
        for record in records+unassigned:
            record['message']=STATUSES.get(record['status'],STATUSES['unknown'])
            if record.get('error_code'):record['error_message']=ERRORS.get(record['error_code'],'不适合自动重试的错误')
        licences.append({'task':state['id'],'batch':state['batch'],'unit':unit,'round':round_number,
                         'used':count,'maximum':limit,'remaining':remaining,'task_remaining':max(0,state['max_requests']-state['requests_used']),
                         'attempts':records,'unassigned_events':unassigned,'status':state['status'],'continuous':bool(shared)})
        used+=count;maximum+=limit
    from tools.task_recovery import blocked_reason
    recovery_block=any(blocked_reason(state,{'id':state['_queue_unit']}) in {'uncertain','download','saved_result'} for state in detail['states'])
    if card['column']=='completed':next_action='原图已保存；成品已回填' if detail['ready'] else '原图已保存；等待其它来源或本地后处理，可继续原任务恢复'
    elif card['stage']=='unsubmitted':next_action='选择此卡，查看执行信息后开始'
    elif card['reason']=='cancelled_task':next_action='关联执行已取消，原图仍未完成；请重新查看执行计划，不能继续被取消的任务'
    elif recovery_block:next_action='先核对或找回已有结果；不能再次付费请求此素材'
    elif card['unit_paused']:next_action='继续此原图，沿用原许可'
    elif shared and not shared['remaining']:next_action='整批额度已用尽，原图等待追加额度；保留全部已完成结果和尝试记录'
    elif shared and card['reason'] in {'attempts','budget'}:next_action='在整批剩余额度内等待持续补齐，当前许可计数保留'
    elif card['reason'] in {'non_retryable','attempts','budget'}:next_action='查看安全错误及补缺记录；需要新增请求时另行查看有界补生成计划'
    else:next_action='等待调度或继续原任务，沿用冻结范围与剩余额度'
    return {'card':card,'licences':licences,'shared_budget':shared,'budget':{'used':used,'issued_maximum':maximum,'unissued_repair_maximum':future,
            'maximum':maximum+future,'remaining_envelope':max(0,maximum+future-used)},
            'delivery':{'position':card['position'],'ready':detail['ready'],'path':str(detail['target']) if detail['ready'] else None},
            'next_action':next_action,'notes':list(dict.fromkeys(notes)),
            'budget_note':'上限来自已有许可和冻结补缺范围，不代表当前可发送次数；仍受整任务余量、失败类别和暂停状态约束。未提交不表示已授权。'}
