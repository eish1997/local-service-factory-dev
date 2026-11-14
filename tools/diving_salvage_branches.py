"""Branch-specific visual content assembly; no production/provider access."""
import copy
import random

def resolve_pipe_sources(config, read_source):
    result=copy.deepcopy(config)
    mapping=result['pipe_source_mapping'];source=read_source(mapping['path'])
    resolved={}
    for key,role in mapping['roles'].items():
        record=source['scene_types'].get(role)
        if not record or not record.get('legal_combinations'):
            raise ValueError('Existing pipe role mapping is missing: '+key)
        resolved[key]={'path':mapping['path'],'role':role,'legal_combinations':copy.deepcopy(record['legal_combinations'])}
    result['resolved_pipe_sources']=resolved
    return result

def choose(rng,rows,identifier,label):
    allowed=[r for r in rows if identifier is None or r['id']==identifier]
    if not allowed: raise ValueError('Incompatible or unknown '+label)
    return copy.deepcopy(rng.choice(allowed))

def freeze(config,seed,branch,operation=None,pipe_category=None,site_id=None):
    if branch not in config['branches'] or branch=='objects': raise ValueError('Invalid service branch')
    rng=random.Random(seed);b=config['branches'][branch]
    anchor={'seed':seed,'branch':branch,'branch_name':b['name'],'lighting':rng.choice(config['lighting']),
            'water':rng.choice(config['water']),'bottom':rng.choice(config['bottom'])}
    wet=True
    if branch in ['live_rescue','deceased_recovery']:
        if operation is not None or pipe_category is not None: raise ValueError('Person branches do not accept object or pipe operations')
        anchor['person']=copy.deepcopy(rng.choice(config['person_profiles'][b['person_status']]))
        if branch=='deceased_recovery':
            anchor['person']['visible_part']=rng.choice(anchor['person']['discovery_visible_parts'])
        anchor['operation']={'id':branch,'name':b['name'],'action':b['rule']}
        anchor['equipment']=config['branch_equipment'][branch]
        sites=[s for s in config['sites'] if s['id'] in b['sites']]
        anchor['target']=anchor['person']['identity']
    elif branch=='underwater_work':
        if pipe_category is not None: raise ValueError('Use pipeline branch for pipe-category operations')
        operation=config.get('underwater_operation_aliases',{}).get(operation,operation)
        job=choose(rng,config['underwater_jobs'],operation,'underwater operation')
        if job.get('variants'):
            variant=copy.deepcopy(rng.choice(job['variants']));job.update(variant)
            job['selected_variant']=variant
        anchor['operation']=job;anchor['target']=job['target']+'，'+job['feature']
        anchor['equipment']=config['branch_equipment']['work_diving']+'；'+job['equipment']
        sites=[s for s in config['sites'] if s['id'] in job['sites']]
    else:
        if pipe_category not in config['pipe_categories']: raise ValueError('Explicit pipe category is required')
        cat=config['pipe_categories'][pipe_category]
        job=choose(rng,[j for j in config['pipe_jobs'] if j['id'] in cat['jobs']],operation,'pipe operation')
        anchor['pipe_category']=pipe_category;anchor['pipe_category_name']=cat['name'];anchor['operation']=job
        wet=job['id']=='underwater_pipeline'
        anchor['target']=cat['target']+'，固定接缝、管径观感、颜色与原有磨损一致'
        anchor['equipment']=job['domestic_equipment'] if pipe_category=='domestic' else job['equipment']
        sites=[s for s in config['sites'] if s['id'] in config['underwater_pipe_sites']] if wet else [s for s in cat['sites'] if job['id'] in s.get('operations',cat['jobs'])]
        key=pipe_category+'.'+job['id']
        if key in config['pipe_source_mapping']['roles']:
            source=config.get('resolved_pipe_sources',{}).get(key)
            if source is None: raise ValueError('Pipe source mapping must be resolved and frozen before assembly')
            anchor['pipe_source_mapping']=copy.deepcopy(source)
            anchor['pipe_source_mapping']['selected_combination']=rng.randrange(len(source['legal_combinations']))
    if wet: sites=[s for s in sites if s['id'] in config['entry_sites']]
    anchor['site']=choose(rng,sites,site_id,'site')
    if anchor['site'].get('target'):anchor['target']=anchor['site']['target']+'，固定位置、颜色和原有痕迹一致'
    anchor['underwater']=wet
    if wet: anchor['team']=copy.deepcopy(rng.choice(config['teams']))
    else:
        anchor['team']={'workers':config['branch_equipment']['land_team']}
        anchor['water']=None;anchor['bottom']=None
        if anchor.get('pipe_category')=='domestic': anchor['lighting']='固定室内自然光，天气不作为随机维度'
    anchor['allowed_covers']=list(b['covers'])
    if branch=='pipeline' and wet: anchor['allowed_covers']=list(config['branches']['underwater_work']['covers'])
    return anchor

def assemble(config,seed,plan,branch,operation=None,pipe_category=None,cover_type=None,site_id=None,storefront_name=False):
    from tools.diving_salvage import plan_check,digest
    from tools.diving_salvage_visual import freeze_visual, finalize
    a=freeze_visual(config,freeze(config,seed,branch,operation,pipe_category,site_id))
    stage_list=copy.deepcopy(config['branch_stages'][branch])
    if branch=='pipeline':
        if a['underwater']: stage_list.insert(0,config['entry_stage'])
        elif config.get('land_survey_stage'): stage_list.insert(1,config['land_survey_stage'])
    stages={s['id']:s for s in stage_list}
    plan=[[s['id']] for s in stage_list] if plan is None else plan
    plan_check({'stages':stage_list},plan)
    rng=random.Random(seed+991)
    cover=choose(rng,[c for c in config['covers'] if c['id'] in a['allowed_covers']],cover_type,'cover for branch')
    stage_for={'storefront':None,'before_entry':'prepare','underwater_discovery':('locate' if branch=='live_rescue' else ('treat' if branch=='pipeline' else 'work')),
               'surface_team':{'live_rescue':'assist','deceased_recovery':'transfer','underwater_work':'finish','pipeline':'finish'}[branch]}
    if branch=='deceased_recovery':stage_for['underwater_discovery']='discover'
    cover_stage=stage_for[cover['id']]
    cover_action={
       'storefront':'独立虚构本地服务门店，普通门面与装备入口，不显示待救者、遇难者或把门店放在作业水域',
       'before_entry':'专业队员在岸或船上准备入水，身体尚未进入水中，无提前水花',
       'underwater_discovery':'水下队员探照观察与搜寻定位，不举物展示，不展示遇难者身体',
       'surface_team':{'live_rescue':'水面与岸船人员接应活人，不作医疗操作演示','deceased_recovery':'水面与岸船工作人员接应全身覆盖的担架，远中景且尊重逝者','underwater_work':'水中工作人员与岸船人员接应作业装备和绳线，不回收设施本体','pipeline':'水下管道工作人员与岸船人员接应工具和绳线，不举起整条管道'}[branch]
    }[cover['id']]
    if branch=='deceased_recovery' and cover['id']=='underwater_discovery':
        cover_action='水下发现定位：要求看见'+a['person']['visible_part']+'；遗体保持完整，其余由浑水、地形、淤泥或画框自然遮住，不展示全身或面部'
    if branch=='underwater_work' and cover['id']=='underwater_discovery':
        cover_action='定位实际作业部位并呈现核心作业动作：'+a['operation']['action']+'；不强加遗失物或人体，不虚构巨大火焰爆炸。'
    seq=[] if cover_stage is None else [cover_stage]
    shots=[{'kind':'cover','type':cover['id'],'stages':seq,'action':cover_action}]
    shots += [{'kind':'detail','type':'timeline','stages':list(p),'action':stages[p[-1]]['action']} for p in plan]
    team='；'.join(str(v) for v in a['team'].values())
    identity=(f"固定分支：{a['branch_name']}。固定主体或作业部位：{a['target']}。具体作业：{a['operation']['name']}。"
        f"固定地点：{a['site']['name']}，{a['site']['detail']}。固定人员与服装：{team}。固定装备组合：{a['equipment']}。"
        f"固定光线：{a['lighting']}。")
    if a['underwater']: identity+=f"固定水体：{a['water']}；固定水底：{a['bottom']}；不突然变成透明泳池。"
    else: identity+='陆地管道现场，禁止潜水员、潜水服、水下景象；家庭管道禁止大型市政工地与大型设备。'
    restriction=config['branches'][branch]['rule']
    if branch in ['underwater_work','pipeline']: restriction+='作业画面不混入被救者或遗体，也不套用寻找物品、沾泥回收或成果举物。'
    for i,shot in enumerate(shots):
        stage=shot['stages'][-1] if shot['stages'] else None
        state=stages[stage]['state'] if stage else '独立门店展示，不呈现案例主体或提前呈现完工'
        camera=['环境全景','人物工作中景','部位与工具关系近景'][i%3]
        if branch in ['live_rescue','deceased_recovery']: camera=['环境全景','工作人员与接应中景'][i%2]
        extra=''
        if shot['kind']=='detail' and stage in ['work','treat']: extra=a['operation']['action']
        if len(shot['stages'])>1: extra+='合并阶段只表现最后阶段的单一瞬间，不拼接相互矛盾的状态。'
        if branch=='deceased_recovery' and stage=='discover':
            extra+='本张要求局部可见：'+a['person']['visible_part']+'；同组衣着固定，遗体完整，禁止断肢，不出现面部、裸露皮肤、伤口、血液或腐败。其余自然遮挡，非猎奇特写。'
        text_rule='不生成任何文字。'
        if storefront_name and shot['type']=='storefront': text_rule='仅允许门头业务名“潜水打捞”，不出现联系方式或其他文字。'
        shot.update(position=i+1,state=state,camera=camera,anchor_sha256=digest(a))
        shot['prompt']='\n'.join([config['branch_common_prompt'],identity,cover['name'] if shot['kind']=='cover' else '→'.join(stages[s]['name'] for s in shot['stages']),shot['action'],state,camera,extra,restriction,config['branch_negative'],text_rule])
        shot['prompt_sha256']=digest(shot['prompt'])
    return finalize(config,{'seed':seed,'branch':branch,'anchor':a,'anchor_sha256':digest(a),'selected_cover':cover['id'],'shot_plan':copy.deepcopy(plan),'shots':shots,
            'selection':{'branch':branch,'operation':operation,'pipe_category':pipe_category,'cover_type':cover_type,'site_id':site_id,'storefront_name':storefront_name}})

def validate(config):
    cases=[]
    for b in ['live_rescue','deceased_recovery']: cases.append((b,None,None))
    cases += [('underwater_work',j['id'],None) for j in config['underwater_jobs']]
    cases += [('pipeline',j,k) for k,v in config['pipe_categories'].items() for j in v['jobs']]
    checked=0;covered=set();pipe_cats=set()
    for b,op,cat in cases:
        ids=[s['id'] for s in config['branch_stages'][b]]
        plans=[[[s] for s in ids]]
        a=freeze(config,721,b,op,cat)
        for cover in a['allowed_covers']:
            for plan in plans:
                g=assemble(config,721,plan,b,op,cat,cover)
                assert g==assemble(config,721,plan,b,op,cat,cover)
                assert len({s['anchor_sha256'] for s in g['shots']})==1
                assert g['shots'][-1]['state']==config['branch_stages'][b][-1]['state']
                assert all(g['anchor']['target'] in s['prompt'] for s in g['shots'] if not s.get('equipment_only'))
                if b in ['live_rescue','deceased_recovery']:
                    assert g['anchor']['person']['status']==config['branches'][b]['person_status']
                    assert 'object' not in g['anchor'] and cover not in ['result','emerging']
                    assert all('特写' not in s['camera'] for s in g['shots'])
                if cat=='domestic':
                    assert not g['anchor']['underwater'] and 'diver' not in g['anchor']['team']
                    assert g['selected_cover']=='storefront' and g['anchor']['water'] is None
                checked+=1;covered.add(b)
                if cat: pipe_cats.add(cat)
    rejected=0
    bad=[('pipeline','underwater_pipeline','domestic',None,None),('pipeline','trenchless','domestic',None,None),('pipeline','trenchless','industrial',None,None),('pipeline','clean','domestic','underwater_discovery',None),('pipeline','clean','domestic',None,'dock'),('underwater_work','weld',None,None,'pond'),('live_rescue',None,None,'result',None),('deceased_recovery',None,None,'emerging',None),('live_rescue','weld',None,None,None),('underwater_work','cut','domestic',None,None)]
    for b,op,cat,cover,site in bad:
        plan=[[s['id']] for s in config['branch_stages'][b]]
        try: assemble(config,721,plan,b,op,cat,cover,site)
        except ValueError: rejected+=1
        else: raise AssertionError('Incompatible input accepted')
    # A foreign branch's timeline cannot silently become a recovery sequence.
    for b in ['underwater_work','pipeline']:
        try: assemble(config,721,[[s['id']] for s in config['stages']],b,pipe_category='domestic' if b=='pipeline' else None)
        except ValueError: rejected+=1
        else: raise AssertionError('Foreign timeline accepted')
    return {'branch_combinations_checked':checked,'branch_invalid_inputs_rejected':rejected,'branches':sorted(covered|{'objects'}),'pipe_categories':sorted(pipe_cats),'underwater_operations':len(config['underwater_jobs']),'pipe_category_operation_pairs':sum(len(v['jobs']) for v in config['pipe_categories'].values())}


def validate_deceased_discovery(config):
    from tools.diving_salvage import assemble as public_assemble
    ids=[s['id'] for s in config['branch_stages']['deceased_recovery']]
    assert ids==['confirm','prepare','discover','transfer','handover']
    checked=0
    for seed in range(30):
        for cover in config['branches']['deceased_recovery']['covers']:
            g=public_assemble(config,seed,[[s] for s in ids],branch='deceased_recovery',cover_type=cover)
            assert g==public_assemble(config,seed,[[s] for s in ids],branch='deceased_recovery',cover_type=cover)
            assert g['anchor']['person']['status']=='deceased'
            assert not any('search' in shot['stages'] for shot in g['shots'] if shot['kind']=='detail')
            assert len(g['shots'])==6
            for shot in g['shots']:
                stage=shot['stages'][-1] if shot['stages'] else None
                if stage=='discover':
                    assert shot['capture_device']=='underwater_action_camera'
                    assert '本张要求局部可见' in shot['prompt']
                    assert g['anchor']['person']['visible_part'] in shot['prompt']
                    assert '不展示遇难者身体' not in shot['action']
                    assert '断肢' in shot['prompt']
                if stage in ['confirm','prepare']:assert '不出现' in shot['state'] or '不预置' in shot['state']
                if stage in ['transfer','handover']:assert '覆盖' in shot['action']
            if cover=='underwater_discovery':assert g['shots'][0]['stages']==['discover']
            checked+=1
    try:public_assemble(config,1,[[s] for s in ids if s!='discover'],branch='deceased_recovery')
    except ValueError:pass
    else:raise AssertionError('Missing discovery timeline accepted')
    try:public_assemble(config,1,[[s] for s in ['confirm','prepare','search','discover','transfer','handover']],branch='deceased_recovery')
    except ValueError:pass
    else:raise AssertionError('Removed standalone search accepted')
    return {'deceased_discovery_groups_checked':checked,'missing_discovery_rejected':True,'removed_search_rejected':True,'standalone_search_details':0,'surface_coverage_preserved':True}
