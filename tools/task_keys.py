"""Private key-pool settings shared by Agent commands and the dashboard."""
import os
import re
import secrets
from urllib.parse import urlparse
from tools import task_library as lib

KEY=re.compile(r'OPENAI_API_KEY(?:_\d+)?$|OPENAI_API_KEYS$')
def env():
    file=lib.ROOT/'.env';text=file.read_text(encoding='utf-8-sig') if file.exists() else ''
    values={}
    for line in text.splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1);values[k.strip()]=v.strip().strip('"\'')
    return text,values

def current():
    _,values=env();keys=[]
    names=['OPENAI_API_KEY']+sorted([k for k in values if re.fullmatch(r'OPENAI_API_KEY_\d+',k)],key=lambda k:int(k.rsplit('_',1)[1]))
    for name in names:
        if values.get(name) and values[name] not in keys:keys.append(values[name])
    for value in re.split(r'[\s,;]+',values.get('OPENAI_API_KEYS','')):
        if value and value not in keys:keys.append(value)
    host=urlparse(values.get('OPENAI_BASE_URL','')).hostname
    name=('tinysnow' if host=='tinysnow.one' else host or '已配置中转') if values.get('OPENAI_PROVIDER')=='relay' else 'OpenAI 官方'
    return {'id':values.get('OPENAI_PROVIDER','official'),'name':name,
            'provider':values.get('OPENAI_PROVIDER','official'),'base_url':values.get('OPENAI_BASE_URL',''),
            'model':values.get('OPENAI_IMAGE_MODEL',''),'keys':keys}

def channels():
    active=current();file=lib.ROOT/'.runtime/private/api_channels.json'
    rows=lib.read(file).get('channels',[]) if file.exists() else []
    rows=[r for r in rows if r['id']!=active['id']]+[active]
    return active,rows

def view(request=None):
    active,rows=channels();revision=lib.digest([env()[0],rows])
    return {'active':active['id'],'revision':revision,'channels':[
        {k:v for k,v in r.items() if k!='keys'}|{'slots':[{'slot':i+1,'label':f'密钥 {i+1} · 已保存'} for i in range(len(r['keys']))],
        'limit':len(r['keys'])} for r in rows]}

def save(request):
    from tools.task_actions import ensure_idle
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
        ensure_idle()
        active,rows=channels()
        if request.get('revision')!=view()['revision']:raise ValueError('密钥配置已变化，请重新打开后保存')
        channel=next((r for r in rows if r['id']==request.get('channel')),None)
        if channel is None:raise ValueError('只能选择已配置并确认的渠道；新渠道请通过 Agent 设置')
        entries=request.get('rows')
        if not isinstance(entries,list):raise ValueError('密钥行数无效')
        keys=[];seen={}
        for index,entry in enumerate(entries,1):
            value=entry.get('value','')
            if isinstance(value,str):value=value.strip()
            if not value and type(entry.get('keep_slot')) is int:
                slot=entry['keep_slot']
                if not 1<=slot<=len(channel['keys']):raise ValueError('密钥槽位已变化')
                value=channel['keys'][slot-1]
            if not isinstance(value,str) or not value.strip() or re.search(r'[\s"\'\x00-\x1f]',value):raise ValueError('每行请填写有效密钥，空白行请删除')
            if value in seen:raise ValueError(f'第 {index} 行与第 {seen[value]} 行密钥重复，请移除重复行')
            seen[value]=index;keys.append(value)
        channel={**channel,'keys':keys};rows=[channel if r['id']==channel['id'] else r for r in rows]
        # All values stay on private disk/stdin; never return secrets to the UI or logs.
        lib.write(lib.ROOT/'.runtime/private/api_channels.json',{'channels':rows})
        text,_=env();managed={'OPENAI_PROVIDER','OPENAI_BASE_URL','OPENAI_IMAGE_MODEL'}
        lines=[line for line in text.splitlines() if not ('=' in line and (KEY.fullmatch(line.split('=',1)[0].strip()) or line.split('=',1)[0].strip() in managed))]
        lines=[line for line in lines if not line.startswith('FACTORY_KEY_POOL_MANAGED=')]
        lines += ['FACTORY_KEY_POOL_MANAGED=1',f'OPENAI_PROVIDER={channel["provider"]}',f'OPENAI_BASE_URL={channel["base_url"]}',f'OPENAI_IMAGE_MODEL={channel["model"]}']
        lines += [f'{"OPENAI_API_KEY" if i==0 else "OPENAI_API_KEY_"+str(i+1)}={key}' for i,key in enumerate(keys)]
        file=lib.ROOT/'.env';temp=file.with_name('.env.'+secrets.token_hex(6)+'.tmp')
        try:
            temp.write_text('\n'.join(lines)+'\n',encoding='utf-8');os.replace(temp,file)
        finally:
            if temp.exists():temp.unlink()
        return view()
