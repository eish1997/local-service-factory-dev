"""Seeded group identities and compatible shot-level visual combinations."""
import copy,random,json,hashlib

def rng_for(seed,label):
    return random.Random(int.from_bytes(hashlib.sha256(f'{seed}:{label}'.encode()).digest()[:8],'big'))

def freeze_group(config,a):
    a=copy.deepcopy(a);p=config['variation_pools'];r=rng_for(a['seed'],'group-cast');wet=a.get('underwater',True)
    lead=r.choice(p['lead']);suit=r.choice(p['suit']);support=r.sample(p['support'],r.choice([1,2,3]) if wet else r.choice([1,2]));clothes=r.sample(p['clothes'],len(support));vest=r.choice(p['vest']);kit=r.choice(p['kit'])
    members=[{'id':'lead','identity':lead,'clothing':suit if wet else r.choice(p['clothes'])}]+[{'id':f'support{i+1}','identity':v,'clothing':clothes[i]} for i,v in enumerate(support)]
    a['cast']=members
    a['team']={'diver':lead+'，'+suit,'assistants':'；'.join(m['id']+'：'+m['identity']+'，'+m['clothing']+'，'+vest for m in members[1:]),'equipment':kit} if wet else {'workers':'；'.join(m['id']+'：'+m['identity']+'，'+m['clothing'] for m in members)}
    a['group_variation']={'lead':lead,'suit':suit if wet else None,'support':support,'clothes':clothes,'vest':vest if wet else None,'kit':kit if wet else a['equipment']}
    if wet:
        rr=rng_for(a['seed'],'water');ids=config['water_compatibility'][a['site']['id']]
        a['water_profile_id']=rr.choice(ids);a['water']=config['variation_pools']['water'][a['water_profile_id']]
        a['entry_location']=config['entry_sites'][a['site']['id']]
    from tools.diving_salvage_physics import freeze_geometry
    a['physical_geometry']=freeze_geometry(config,a)
    return a

def select_shot(config,g,s,submerged,used,physical):
    p=config['variation_pools'];a=g['anchor'];stage=s['stages'][-1] if s['stages'] else None;r=rng_for(g['seed'],f'shot:{s["position"]}:{stage}')
    equipment=s.get('equipment_only',False);entry=stage=='entry_airborne';store=s['type']=='storefront'
    views=p['water_view'] if submerged else p['shore_view']
    if submerged and g.get('branch')=='deceased_recovery':views={k:v for k,v in views.items() if k!='pov'}
    if physical['bundle']:views={k:v for k,v in views.items() if k in ['side','diagonal','across']}
    if entry:views={k:v for k,v in views.items() if k in ['side','diagonal']}
    available=[k for k in views if k not in used.setdefault('water' if submerged else 'shore',set())]
    if not available:available=list(views)
    view=r.choice(available);used['water' if submerged else 'shore'].add(view)
    selected={'view':views[view],'distance':r.choice(p['water_distance'] if submerged else p['shore_distance']),
        'direction':r.choice(p['direction']),'negative_space':r.choice(p['negative_space']),
        'occlusion':r.choice(p['water_occlusion'] if submerged else p['shore_occlusion'])}
    if physical['bundle']:
        from tools.diving_salvage_physics import joint_variables
        selected.update(joint_variables(physical));selected['view_id']=view
        return selected
    if entry:selected['distance']='中景保留离岸位置、全身与未接触的水面';selected['occlusion']='无遮挡关键入水动作'
    if equipment or store:
        selected.update(visible_people='0人，画内无身体与手部',body='只见装备静物' if equipment else '只见独立门店',task='装备自然放置' if equipment else '服务门店外观',progress='静物状态',relation='无需人物关系',facing='无人');visible=[]
    elif submerged:
        visible=['lead'];selected['body']='第一视角只见自己的手或工具，不出现自己的全身或脸' if view=='pov' else r.choice(p['body'])
        selected['visible_people']='作业人员只见主作业者或其局部，其余队员在画外；不限制本阶段应见目标'
        selected['task']=s['action'];selected['progress']=r.choice(p['water_progress']);selected['facing']='专注实际目标或部位，不看镜头'
        selected['relation']=r.choice(p['target_relation']);selected['target_position']=r.choice(p['target_position'])
        selected['target_scale']=r.choice(p['target_scale_large'] if a.get('object',{}).get('size')=='large' else p['target_scale'])
        if g.get('branch')=='deceased_recovery':selected['distance']='克制的中景，非人体猎奇特写';selected['body']='潜水员半身或局部，遇难者头部不入镜'
    else:
        if entry:visible=['lead'];task='主潜水员低落差离开平台的滞空瞬间，尚未触水，无提前水花'
        elif stage=='prepare':
            visible=r.sample([m['id'] for m in a['cast']],r.choice([1,2]));task=r.choice(p['prepare_task'])
        elif stage in ['recover','transfer','assist']:visible=['lead',a['cast'][1]['id']];task=s['action']
        else:visible=r.sample([m['id'] for m in a['cast']],r.choice([1,2]));task=r.choice(p['finish_task'] if len(visible)>1 else p['finish_task'][:2])+'；核心动作：'+s['action']
        selected.update(visible_people='画内作业人员只见'+','.join(visible)+'；其他队员在画外，本阶段应见目标按状态出现',body='全身，离岸和水面间隙清楚' if entry else r.choice(p['shore_body']),task=task,
            progress=r.choice(p['shore_progress']),facing=r.choice(p['facing']),relation=r.choice(p['spacing']) if len(visible)>1 else '只有一个作业者或其局部，不围站')
        if entry:selected['progress']='身体刚离开平台、尚未触水';selected['facing']='自然朝向入水区域，不看镜头'
        elif selected['body']=='人物全身但不居中':selected['distance']='中景容纳人物全身及关键工作区域'
    if s['kind']=='cover' and submerged:selected['cover_structure']=p['cover_structure'][3] if view=='pov' else r.choice([x for i,x in enumerate(p['cover_structure']) if i!=3])
    selected['visible_ids']=visible;selected['view_id']=view
    return selected

def apply_shot(config,g,s,submerged,used):
    # Remove old deterministic camera line, rather than append a competing camera.
    s['prompt']=s['prompt'].replace(s['camera'],'')
    from tools.diving_salvage_physics import plan,render
    physical=plan(config,g,s,submerged);s['physical_scene']=physical
    v=select_shot(config,g,s,submerged,used,physical);s['shot_variables']=v
    if physical['bundle']:
        s['prompt']=s['prompt'].replace(s['action'],physical['bundle']['action'])
        s['action']=physical['bundle']['action']
    s['prompt']+='\n'+render(physical)
    s['camera']=v['view'];s['framing']=v['direction']+'；'+v['negative_space']
    text='本张唯一镜头组合（冻结队伍只是身份档案，不要求全员入画）：\n'+'\n'.join(k+'：'+str(x) for k,x in v.items() if k not in ['visible_ids','view_id'])
    s['prompt']+='\n'+text
    if s['stages']==['entry_airborne']:s['prompt']+='\n本次入水位置：'+g['anchor']['entry_location']+'。动作预览在前，随后装备与准备详情是过程回看；不是站岸边准备，不是高台极限跳水，不提供入水教程。'
    return text

def check_variations(g):
    wet=g['anchor']['visual']['underwater_capable'];n=g['content_group']['total_images']
    if len(g['shots'])!=n:raise ValueError('Wrong wet/land count')
    if wet and g['shots'][1]['stages']!=['entry_airborne']:raise ValueError('Entry preview must be first detail')
    equipment=g['shots'][2 if wet else 1]
    if not equipment.get('equipment_only') or equipment['shot_variables']['visible_ids']:raise ValueError('Equipment must be unpeopled')
    for s in g['shots']:
        v=s.get('shot_variables',{})
        if not v:raise ValueError('Missing shot variables')
        if v['view_id']=='pov' and '全身或脸' not in v['body']:raise ValueError('POV body conflict')
        if set(v['visible_ids'])-set(m['id'] for m in g['anchor']['cast']):raise ValueError('Unknown visible cast')
    water=[s['shot_variables']['view_id'] for s in g['shots'] if s['capture_device']=='underwater_action_camera']
    if len(water)!=len(set(water)):raise ValueError('Repeated underwater camera within group')

def signature(g):
    return json.dumps({'branch':g.get('branch','objects'),'pipe_category':g['anchor'].get('pipe_category'),'target':g['anchor'].get('target'),'operation':g['anchor'].get('operation'),'object':g['anchor'].get('object'),'group':g['anchor']['group_variation'],'site':g['anchor']['site']['id'],'environment':g['anchor']['environment']['selected'],
        'shots':[s['shot_variables'] for s in g['shots']]},sort_keys=True,ensure_ascii=False)

def assemble_batch(builder,seed,count):
    seen=set();groups=[];suppressed=0
    for i in range(count):
        for attempt in range(20):
            g=builder(seed+i+attempt*1000003);sig=signature(g)
            if sig not in seen:seen.add(sig);groups.append(g);break
            suppressed+=1
        else:raise ValueError('Cannot find distinct compatible combination in bounded batch attempts')
    return groups,{'duplicates_suppressed':suppressed,'unique_combinations':len(seen),'persistent_state':False}
