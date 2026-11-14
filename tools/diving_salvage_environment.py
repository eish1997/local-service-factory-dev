"""Compatible site facets, frozen once per group and rendered by shot medium."""
import copy
import random

def validate_environment(config,anchor):
    e=anchor['environment'];p=config['environment_profiles'][anchor['site']['id']]
    for key,value in e['selected'].items():
        if value not in p[key]:raise ValueError('环境变量与地点不兼容: '+key)
    wet=anchor.get('underwater',True)
    if not wet and any(e['selected'].get(k) for k in ['depth','water_level','visibility']):raise ValueError('陆地场景不能混入水下变量')
    if wet and anchor.get('object',{}).get('size')=='large' and e['selected']['depth']=='shallow':raise ValueError('大型打捞不能使用浅沟水深')
    if anchor.get('object',{}).get('size')=='large' and not p['heavy_recovery']:raise ValueError('场地无大型目标回收空间')

def freeze(config,anchor):
    a=copy.deepcopy(anchor);rng=random.Random(a['seed']+43191)
    p=config['environment_profiles'][a['site']['id']];pools=config['environment_pools']
    keys=['bank','surroundings','surface','wear','weather_time','light_source']
    if a.get('underwater',True): keys+=['depth','water_level','visibility']
    selected={k:rng.choice(p[k]) for k in keys}
    lights=list(p['light_source'])
    if selected['weather_time'] not in ['sun_am','sun_pm']: lights=[x for x in lights if x!='side_sun']
    selected['light_source']=rng.choice(lights)
    values={k:pools[k][v] for k,v in selected.items()}
    a['environment']={'site_id':a['site']['id'],'selected':selected,'values':values,'heavy_recovery':p['heavy_recovery']}
    a['lighting']=values['weather_time']+'；'+values['light_source']
    validate_environment(config,a)
    return a

def render(anchor,submerged,storefront=False):
    if storefront:return "门店为独立服务展示；本组案例场地变量仅存档，不把门店强行放在岸边或水下，不展示案例人物与目标。"
    e=anchor['environment']['values']
    if submerged:
        return ('固定水下环境：'+anchor['water']+'；'+e['depth']+'；'+e['water_level']+'；'+e['visibility']+
                '。光在水中自然衰减；岸边与周边建筑仅为案例定位锚点，不要求水下画面出现天空、地面或建筑。')
    return ('固定场地细节：'+e['bank']+'；周边只取一项：'+e['surroundings']+'；地面/接近位置：'+e['surface']+'；'+e['wear']+
            '；'+e['weather_time']+'；实际光源：'+e['light_source']+'。不要将候选背景全部塞进一张图。')

def validate(config):
    from tools.diving_salvage import assemble
    cases=[('objects',None,None),('live_rescue',None,None),('deceased_recovery',None,None),('underwater_work','inspect_record',None),
           ('pipeline','clean','domestic'),('pipeline','inspect','municipal'),('pipeline','inspect','industrial'),('pipeline','underwater_pipeline','industrial')]
    observed=set();signatures=set();checked=0
    for b,op,cat in cases:
        stages=config['stages'] if b=='objects' else config['branch_stages'][b];plan=[[s['id']] for s in stages]
        for seed in range(100):
            g=assemble(config,seed,plan,branch=b,operation=op,pipe_category=cat)
            assert g==assemble(config,seed,plan,branch=b,operation=op,pipe_category=cat)
            a=g['anchor'];validate_environment(config,a);observed.add(a['site']['id']);signatures.add(str(a['environment']['selected']))
            for shot in g['shots']:
                wet=shot['capture_device']=='underwater_action_camera'
                assert render(a,wet,shot['type']=='storefront') in shot['prompt']
                assert shot['environment']==a['environment']
                assert shot['anchor_sha256']==g['anchor_sha256']
            checked+=1
    rejected=0
    # Every profile rejects values not in its allowed pool, not just unknown sites.
    for b,op,cat in cases:
        stages=config['stages'] if b=='objects' else config['branch_stages'][b]
        a=assemble(config,9,[[s['id']] for s in stages],branch=b,operation=op,pipe_category=cat)['anchor']
        a['environment']['selected']['bank']='not_allowed'
        try:validate_environment(config,a)
        except ValueError:rejected+=1
        else:raise AssertionError('Invalid site facet accepted')
    for target in ['car','boat','large_machine']:
        try:assemble(config,1,[[s['id']] for s in config['stages']],object_id=target,site_id='irrigation')
        except ValueError:rejected+=1
        else:raise AssertionError('Large target in shallow canal')
    try:assemble(config,1,[[s['id']] for s in config['branch_stages']['pipeline']],branch='pipeline',operation='trenchless',pipe_category='municipal',site_id='utility_gallery')
    except ValueError:rejected+=1
    else:raise AssertionError('Trenchless indoor mismatch')
    shallow=assemble(config,1,[[s['id']] for s in config['stages']],object_id='phone',site_id='irrigation')['anchor']
    shallow['environment']['selected']['depth']='deep'
    try:validate_environment(config,shallow)
    except ValueError:rejected+=1
    else:raise AssertionError('Deep water in shallow canal')
    assert len(observed)>=25 and len(signatures)>300
    return {'environment_groups_checked':checked,'environment_invalid_inputs_rejected':rejected,
            'environment_sites_seen':len(observed),'unique_environment_combinations':len(signatures),
            'configured_site_count':len(config['environment_profiles']),
            'environment_pool_counts':{k:len(v) for k,v in config['environment_pools'].items()}}
