"""One bounded continuation policy for public tasks and background workers."""
REASONS={
    'uncertain':'请求结果不确定',
    'download':'已返回图片但下载失败',
    'non_retryable':'错误不适合自动重试',
    'saved_result':'已生成结果缺少有效本地凭据',
    'attempts':'单图两次请求已用尽',
    'budget':'原任务请求预算已用尽',
    'user_pause':'此原图已暂停，其他图片继续调度',
    'cancelled_task':'关联执行已取消，原图仍未完成；请为该原图重新查看执行计划',
}


def blocked_reason(state,unit):
    uid=unit['id'];used=state.get('attempts',{}).get(uid,0)
    result=state.get('results',{}).get(uid,{})
    status=result.get('status');error=result.get('error')
    if unit.get('inherited_raw'):return 'saved_result'
    if 'pending_unit_ids' in state and uid not in state['pending_unit_ids']:return 'saved_result'
    if status=='request_reserved':return 'uncertain'
    if error=='image_download_failed':return 'download'
    if status=='generated' or error=='local_save_failed':return 'saved_result'
    from tools.task_request_errors import retryable
    can_retry=retryable(state,result)
    if not can_retry:return 'non_retryable'
    # A lost result must not turn an already reserved request into a new POST.
    if used and (status!='failed' or error is None or not can_retry):return 'uncertain'
    if used>=2:return 'attempts'
    if state['requests_used']>=state['max_requests']:return 'budget'
    return None


def partition(category,batch,rows,state):
    from tools.task_worker import raw_valid
    from tools.task_controls import paused
    paused_ids=paused(state)
    ready=[];blocked=[];reused=0;reasons={};retained_ids=[]
    for row in rows:
        for unit in row['units']:
            if raw_valid(category,batch,row['group'],unit):reused+=1;retained_ids.append(unit['id']);continue
            reason='user_pause' if unit['id'] in paused_ids else blocked_reason(state,unit)
            if reason is None:
                from tools import task_library as lib
                raw=lib.unit_raw(category,batch,row['group'],unit)
                if lib.io_path(raw).exists() or lib.io_path(raw.with_suffix('.receipt.json')).exists():reason='saved_result'
            if reason is None:ready.append((row['group'],unit));continue
            result=state.get('results',{}).get(unit['id'],{})
            item={'unit':unit['id'],'group':row['group'],'position':unit['delivery_position'],'reason':reason,'message':REASONS[reason]}
            if type(result.get('http_status')) is int and 100<=result['http_status']<=599:item['http_status']=result['http_status']
            blocked.append(item);reasons[reason]=reasons.get(reason,0)+1
    retry_count=sum(state.get('results',{}).get(u['id'],{}).get('status')=='failed' for _,u in ready)
    summary={'ready_count':len(ready),'retry_count':retry_count,'blocked_count':len(blocked),'reused_count':reused,
             'remaining_requests':max(0,state['max_requests']-state['requests_used']),'reasons':reasons,'blocked':blocked,'paused_count':reasons.get('user_pause',0),'retained_unit_ids':retained_ids}
    return ready,summary


def protect_returned_results(category,batch,group,units,allow_reasons=None):
    """An explicit repair is a new bounded task, never a lost-response retry."""
    from tools import task_library as lib
    from tools.task_worker import raw_valid
    allowed=set(allow_reasons or ())&{'uncertain','download'}
    tasks=lib.jobs(lib.batch_dir(category,batch))
    for unit in units:
        if raw_valid(category,batch,group,unit):continue
        if unit.get('inherited_raw'):raise ValueError('冻结继承素材待本地恢复，不能重新付费生成')
        reason=None
        for task in tasks:
            if group not in task['groups']:continue
            reason=blocked_reason(task,unit)
            if reason:break
        raw=lib.unit_raw(category,batch,group,unit)
        if lib.io_path(raw).exists() or lib.io_path(raw.with_suffix('.receipt.json')).exists():
            if reason in allowed:continue
            raise ValueError('已有本地原图或凭据但校验未通过，请先检查或恢复，不能重复付费生成')
        if reason in {'uncertain','download','saved_result'} and reason not in allowed:
            raise ValueError(REASONS[reason]+'：请先核对已返回结果；补生成不会重新付费请求此项')


def automatic_candidates(category,batch,group,units):
    """New repair licences may cover exhausted transient work, never blind rejections."""
    from tools import task_library as lib
    from tools.task_worker import raw_valid
    tasks=lib.jobs(lib.batch_dir(category,batch));allowed=[]
    for task in tasks:
        if task.get('parent_budget') or task.get('auto_complete',{}).get('mode')=='continuous':
            file=lib.batch_dir(category,batch)/'tasks'/task['id']/'task.json'
            lib.synchronize_license(file,task)
    for unit in units:
        if raw_valid(category,batch,group,unit):continue
        raw=lib.unit_raw(category,batch,group,unit)
        if unit.get('inherited_raw') or lib.io_path(raw).exists() or lib.io_path(raw.with_suffix('.receipt.json')).exists():continue
        blocked=False
        for task in tasks:
            if group not in task['groups']:continue
            if blocked_reason(task,unit) in {'uncertain','download','saved_result','non_retryable'}:blocked=True;break
        if not blocked:allowed.append(unit['id'])
    return allowed


def repair_panels(category,batch,group,unit):
    """Repair revisions of one parent panel, oldest first."""
    from tools import task_library as lib
    position=unit['delivery_position']
    path,data=lib.load_batch(category,batch)
    original=[u for u in lib.selected(path,data,[group])[0]['units'] if u['delivery_position']==position]
    index=next(i for i,item in enumerate(original) if item['id']==unit['id'])
    found=[]
    for linked in lib.io_glob(lib.category_dir(category),'batch_revision_*/batch.json'):
        child=lib.read(linked)
        if child.get('replacement')!={'batch':batch,'group':group,'position':position} or child.get('revision_kind')!='repair':continue
        fresh=lib.selected(linked.parent,child,[1])[0]['units']
        if index<len(fresh):found.append((child.get('created_at') or '',child,fresh[index]))
    found.sort(key=lambda item:item[0])
    return found


def proven_panel(category,batch,group,unit):
    """A newer repair prompt can already have a valid raw before the position is published."""
    from tools import task_library as lib
    from tools.task_worker import raw_evidence_valid
    for _,child,panel in reversed(repair_panels(category,batch,group,unit)):
        raw=lib.unit_raw(category,child['id'],1,panel)
        if raw_evidence_valid(raw,panel):return child,panel,raw
    return None


def effective_reason(category,batch,group,unit):
    """Parent exhaustion does not hide a rejection already recorded on the newest repair."""
    from tools import task_library as lib
    from tools.task_worker import raw_valid
    if raw_valid(category,batch,group,unit) or proven_panel(category,batch,group,unit):return None
    history=repair_panels(category,batch,group,unit)
    if history:
        child,panel=history[-1][1],history[-1][2]
        for task in lib.jobs(lib.batch_dir(category,child['id'])):
            reason=blocked_reason(task,panel)
            if reason:return reason
    for task in lib.jobs(lib.batch_dir(category,batch)):
        if group not in task.get('groups',[]):continue
        reason=blocked_reason(task,unit)
        if reason:return reason
    return None


def leftover_ids(category,batch,group,units):
    """End-of-batch only: uncertain, failed downloads, and explicit rejections."""
    from tools.task_worker import raw_valid
    missing=[]
    for unit in units:
        if raw_valid(category,batch,group,unit) or proven_panel(category,batch,group,unit):continue
        missing.append((unit['id'],effective_reason(category,batch,group,unit)))
    if not missing or any(reason not in {'uncertain','download','non_retryable'} for _,reason in missing):
        return [],[]
    return [uid for uid,_ in missing],[uid for uid,reason in missing if reason=='non_retryable']


def no_work_message(summary,only_failed=False):
    details='、'.join(f'{REASONS[k]} {v} 张' for k,v in summary['reasons'].items())
    prefix='没有可在原预算内重试的失败项' if only_failed else '没有可在原预算内继续的图片'
    return prefix+(f'；{details}。已保留现有结果，请检查这些图片；不会重复付费生成' if details else '；尚未开始的图片请使用继续原任务')
