"""A frozen shared POST cap. Reservations survive every ambiguous crash window."""
from tools import task_library as lib


class SnapshotChanged(ValueError):
    """A read crossed an atomic ledger update; rebuild the entire read context."""


def continuous(state):
    return state.get('auto_complete',{}).get('mode')=='continuous'


def context(state):
    binding=state.get('parent_budget')
    if binding:
        if not isinstance(binding,dict) or set(binding)!={'category','batch','task','license_sha256'}:
            raise ValueError('共享额度父关联无效')
        if binding['category']!=state['category']:raise ValueError('共享额度项目不一致')
        base=lib.batch_dir(binding['category'],binding['batch'])/'tasks'/lib.identifier(binding['task'])
        parent=lib.read(base/'task.json');licence=lib.read(base/'license.json')
        if parent['license_sha256']!=binding['license_sha256']:raise ValueError('共享额度父许可已变化')
        entry=parent.get('auto_recovery',{}).get('children',{}).get(state['id'])
        _,childdata=lib.load_batch(state['category'],state['batch'])
        if (not isinstance(entry,dict) or entry.get('batch')!=state['batch'] or
            childdata.get('automatic_repair_parent')!={'batch':binding['batch'],'task':binding['task'],'round':entry.get('round')}):
            raise ValueError('共享额度子许可没有父登记')
    elif continuous(state):
        base=lib.batch_dir(state['category'],state['batch'])/'tasks'/lib.identifier(state['id'])
        parent=state;licence=lib.read(base/'license.json')
    else:return None
    terms=licence['terms']
    if lib.digest(terms)!=parent['license_sha256'] or any(parent.get(k)!=v for k,v in terms.items()):
        raise ValueError('共享额度父许可校验失败')
    cfg=terms.get('auto_complete',{})
    cap=cfg.get('total_max_requests')
    if cfg.get('mode')!='continuous' or type(cap) is not int or not 0<=cap<=100000:
        raise ValueError('共享额度冻结上限无效')
    owner={'category':terms['category'],'batch':terms['batch'],'task':terms['id']}
    return base,parent,{'schema_version':1,'owner':owner,'license_sha256':parent['license_sha256'],'maximum':cap}


def binding(parent):
    return {'category':parent['category'],'batch':parent['batch'],'task':parent['id'],'license_sha256':parent['license_sha256']}


def load(state,*,memo=None):
    ctx=context(state)
    if ctx is None:return None
    base,parent,expected=ctx;file=lib.io_path(base/'budget.json')
    cache_key=('budget',str(base))
    if memo is not None and cache_key in memo:return memo[cache_key]
    if not file.is_file() or file.stat().st_size>64*1024*1024:raise ValueError('共享额度账本缺失或过大，禁止再次请求')
    saved=lib.read(file)
    if not isinstance(saved,dict) or any(saved.get(k)!=v for k,v in expected.items()):
        raise ValueError('共享额度账本与冻结许可不一致')
    entries=saved.get('reservations')
    if (not isinstance(entries,list) or len(entries)>expected['maximum'] or
            saved.get('reservations_sha256')!=lib.digest(entries)):
        raise ValueError('共享额度预留记录损坏')
    identities=set();ordinals={}
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)!={'batch','task','license_sha256','unit','origin','attempt','number','at'}:
            raise ValueError('共享额度请求身份无效')
        for key in ('batch','task','unit'):lib.identifier(entry[key])
        origin=entry['origin']
        if (not isinstance(origin,list) or len(origin)!=3 or origin[0]!=parent['batch'] or
            type(origin[1]) is not int or origin[1] not in parent['groups'] or origin[2] not in parent.get('pending_unit_ids',[]) or
            not isinstance(entry['license_sha256'],str) or len(entry['license_sha256'])!=64):
            raise ValueError('共享额度冻结原卡无效')
        if type(entry['attempt']) is not int or not 1<=entry['attempt']<=2 or type(entry['number']) is not int or entry['number']<1:
            raise ValueError('共享额度请求序号无效')
        identity=(entry['batch'],entry['task'],entry['number'])
        if identity in identities:raise ValueError('共享额度重复预留')
        identities.add(identity)
        ordinal=(entry['batch'],entry['task'],entry['unit'])
        if entry['attempt']!=ordinals.get(ordinal,0)+1:raise ValueError('共享额度素材序号不连续')
        ordinals[ordinal]=entry['attempt']
    result=base,parent,saved
    if memo is not None:memo[cache_key]=result
    return result


def licence_snapshot(file,memo=None):
    key=('licence',str(file))
    if memo is None:return lib.read(file)
    if key not in memo:memo[key]=lib.read(file)
    return memo[key]


def initialize(state):
    ctx=context(state)
    if ctx is None or state.get('parent_budget'):return
    base,parent,expected=ctx
    # Called only after creating a brand-new frozen licence, before launching it.
    with lib.lock(base/'budget.lock'):
        if lib.io_path(base/'budget.json').exists():raise ValueError('共享额度已经登记，不能重置')
        lib.write(base/'budget.json',{**expected,'reservations':[],'reservations_sha256':lib.digest([])})


def project(state,licence,*,memo=None):
    """Pure projection: an orphan reservation becomes unknown, never a free retry."""
    loaded=load(state,memo=memo)
    if loaded is None:return state,licence
    entries=[e for e in loaded[2]['reservations'] if e['batch']==state['batch'] and e['task']==state['id']]
    attempts={};results=dict(state.get('results',{}))
    pending=set(licence['terms'].get('pending_unit_ids',[]))
    for number,e in enumerate(entries,1):
        if e['license_sha256']!=state['license_sha256'] or e['number']!=number or e['unit'] not in pending:
            raise ValueError('共享额度预留与子许可不一致')
        attempts[e['unit']]=e['attempt']
        if e['attempt']>state['attempts'].get(e['unit'],0):
            results[e['unit']]={'status':'request_reserved','request_number':number,'attempt':e['attempt']}
    if (len(entries)>licence['terms']['max_requests'] or licence['requests_used']>len(entries) or state['requests_used']>len(entries) or
        any(v>attempts.get(k,0) for k,v in licence['attempts'].items()) or any(v>attempts.get(k,0) for k,v in state['attempts'].items())):
        if memo is not None:
            fresh=load(state)
            if fresh[2]['reservations']!=loaded[2]['reservations']:
                raise SnapshotChanged('看板查询期间额度已更新，请重新建立完整快照')
        raise ValueError('许可已用次数缺少共享额度预留')
    return ({**state,'requests_used':len(entries),'attempts':attempts,'results':results},
            {**licence,'requests_used':len(entries),'attempts':attempts})


def reconcile(file,state,licence,*,persist=False):
    projected,updated=project(state,licence)
    if persist and updated!=licence:lib.write(file.parent/'license.json',updated)
    state.update(projected)
    return updated


def reserve(state,unit,number,attempt):
    ctx=context(state)
    if ctx is None:return True
    base,parent,_=ctx
    from tools.task_queue import origin_keys
    path,data=lib.load_batch(state['category'],state['batch'])
    rows=lib.task_rows(path,data,state)
    scoped=[{**r,'units':[u for u in r['units'] if u['id']==unit]} for r in rows]
    scoped=[r for r in scoped if r['units']]
    keys=origin_keys(state['category'],state['batch'],scoped)
    if len(keys)!=1:raise ValueError('共享额度原卡身份无效')
    origin=list(next(iter(keys)))
    if origin[0]!=parent['batch'] or origin[2] not in parent.get('pending_unit_ids',[]):raise ValueError('共享额度请求超出原卡范围')
    with lib.lock(base/'budget.lock'):
        _,_,saved=load(state);entries=saved['reservations']
        if any(e['batch']==state['batch'] and e['task']==state['id'] and e['number']==number for e in entries):
            raise ValueError('共享额度请求身份已预留，必须先核对结果，不能再次发送')
        if type(number) is not int or number!=state['requests_used']+1 or type(attempt) is not int or attempt!=state['attempts'].get(unit,0)+1 or not 1<=attempt<=2:
            raise ValueError('共享额度请求序号不符合当前许可')
        if len(entries)>=saved['maximum']:return False
        entries.append({'batch':state['batch'],'task':state['id'],'license_sha256':state['license_sha256'],
                        'unit':unit,'origin':origin,'attempt':attempt,'number':number,'at':lib.now()})
        saved['reservations_sha256']=lib.digest(entries);lib.write(base/'budget.json',saved)
    return True


def progress(state,*,memo=None):
    loaded=load(state,memo=memo)
    if loaded is None:return None
    saved=loaded[2];used=len(saved['reservations'])
    return {'used':used,'maximum':saved['maximum'],'remaining':saved['maximum']-used}
