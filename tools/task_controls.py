"""Unit pause intent is separate from mutable worker progress and frozen licences."""
import secrets
from tools import task_library as lib


def controls_file(state):
    return lib.batch_dir(state['category'],state['batch'])/'tasks'/state['id']/'unit-controls.json'


def direct(state):
    file=controls_file(state)
    if not lib.io_path(file).exists():return set()
    value=lib.read(file)
    paused=value.get('paused')
    if not isinstance(paused,list) or any(not isinstance(u,str) for u in paused):raise ValueError('单元暂停记录无效')
    return set(paused)


def paused(state,data=None):
    result=direct(state)
    if data is None:data=lib.load_batch(state['category'],state['batch'])[1]
    binding=data.get('automatic_repair_parent')
    if binding:
        parent=lib.read(lib.batch_dir(state['category'],binding['batch'])/'tasks'/binding['task']/'task.json')
        origin=direct(parent);target=data['replacement']
        path,pdata=lib.load_batch(state['category'],binding['batch'])
        old=[u for u in lib.selected(path,pdata,[target['group']])[0]['units'] if u['delivery_position']==target['position']]
        fresh=lib.selected(lib.batch_dir(state['category'],state['batch']),data,[1])[0]['units']
        if len(old)!=len(fresh):raise ValueError('补缺暂停范围映射不一致')
        result.update(b['id'] for a,b in zip(old,fresh) if a['id'] in origin)
    return result


def change(state,unit_ids,pause):
    path,data=lib.load_batch(state['category'],state['batch'])
    valid={u['id'] for r in lib.task_rows(path,data,state) for u in r['units']}
    if not isinstance(unit_ids,list) or not unit_ids or any(not isinstance(u,str) for u in unit_ids) or len(set(unit_ids))!=len(unit_ids) or not set(unit_ids)<=valid:raise ValueError('单元控制超出原任务许可范围')
    ids=direct(state)
    if pause:ids.update(unit_ids)
    else:ids.difference_update(unit_ids)
    file=controls_file(state);value=lib.read(file) if lib.io_path(file).exists() else {}
    value.update(paused=sorted(ids),updated_at=lib.now())
    if not pause:value['resume_epoch']=secrets.token_hex(16)
    lib.write(file,value)
    return sorted(ids)


def resume_epoch(state):
    file=controls_file(state)
    own=lib.read(file).get('resume_epoch') if lib.io_path(file).exists() else None
    _,data=lib.load_batch(state['category'],state['batch']);binding=data.get('automatic_repair_parent')
    if not binding:return own
    parent={'category':state['category'],'batch':binding['batch'],'id':binding['task']}
    file=controls_file(parent);epoch=lib.read(file).get('resume_epoch') if lib.io_path(file).exists() else None
    return lib.digest({'own':own,'parent':epoch})
