"""Shared documentary style and strict portrait contract for salvage drafts."""
import copy
import random

CONTRACT={'orientation':'portrait','ratio':'2:3','raw_generation_size':'1024x1536','final_size':'1024x1536'}

def validate_contract(config):
    if config.get('output_contract')!=CONTRACT:
        raise ValueError('潜水打捞首图和详情必须统一竖版1024x1536，2:3')

def freeze_visual(config,anchor):
    validate_contract(config)
    from tools.diving_salvage_environment import freeze as freeze_environment
    a=freeze_environment(config,anchor);rng=random.Random(a['seed']+8701)
    indoor=a['site'].get('indoor',False)
    wet=a.get('underwater',True)
    from tools.diving_salvage_variation import freeze_group
    a=freeze_group(config,a)
    light=(config['documentary']['indoor_light'] if indoor else
           a['lighting']+'；'+a['site'].get('light_context','光线来自天空与实际周边建筑遮挡'))
    light=a['lighting']
    a['visual']={'capture_style':'companion_documentary','light':light,'indoor':indoor,
                 'underwater_capable':wet,'framing_offset':rng.randrange(len(config['documentary']['framing'])),
                 'output_contract':copy.deepcopy(CONTRACT)}
    return a

def finalize(config,group):
    from tools.diving_salvage import digest
    validate_contract(config)
    a=group['anchor'];v=a['visual'];rules=config['documentary']
    group['output_contract']=copy.deepcopy(CONTRACT)
    detail_count=6 if v['underwater_capable'] or config.get('land_survey_stage') else 5
    group['content_group']={'cover_count':1,'detail_count':detail_count,'total_images':detail_count+1}
    used_views={}
    group['anchor_sha256']=digest(a)
    for i,s in enumerate(group['shots']):
        stage=s['stages'][-1] if s['stages'] else None
        branch=group.get('branch','objects')
        submerged=v['underwater_capable'] and (s['type']=='underwater_discovery' or
          (s['kind']=='detail' and ((branch=='objects' and stage in ['search','discover']) or
          (branch=='live_rescue' and stage=='locate') or
          (branch=='deceased_recovery' and stage=='discover') or
          (branch=='underwater_work' and stage in ['work','inspect']) or
          (branch=='pipeline' and stage in ['confirm','treat','recheck']))))
        equipment_only=s['kind']=='detail' and stage=='confirm'
        if equipment_only:
            submerged=False
            equipment=a.get('equipment') or (a['team']['equipment']+'；回收适配：'+a['recovery'])
            if a.get('underwater',True) and a.get('equipment'): equipment=a['team']['equipment']+'; '+equipment
            # Person and target identities stay frozen in anchor, outside this still-life prompt.
            s['prompt']='\n'.join([config['equipment_display_rule'], '本次装备：'+equipment,
                '固定场地：'+a['site']['name']+'，'+a['site']['detail'],
                'AI服务示意，非真实客户案例；自然现场装备静物记录，不出现人物或手部。'])
            s['action']='纯装备静物展示';s['camera']='装备与自然放置位置的中近景';s['equipment_only']=True
        device=rules['underwater_capture'] if submerged else rules['surface_capture']
        from tools.diving_salvage_variation import apply_shot
        apply_shot(config,group,s,submerged,used_views)
        framing=s['framing']
        natural_result=rules['result'] if branch=='objects' and (s['type']=='result' or stage=='handover') else ''
        from tools.diving_salvage_environment import render as render_environment
        environment_text=render_environment(a,submerged,s['type']=='storefront')
        s['environment']=copy.deepcopy(a['environment'])
        s.update(raw_generation_size=CONTRACT['raw_generation_size'],final_size=CONTRACT['final_size'],
                 output_ratio='2:3',orientation='portrait',capture_device='underwater_action_camera' if submerged else 'phone',
                 framing=framing,anchor_sha256=group['anchor_sha256'])
        # These are actual frozen prompt instructions, not documentation-only metadata.
        s['prompt']+='\n'+'\n'.join(['首图与详情均为竖版1024×1536，宽高比2:3，禁止横图。',
            (config['equipment_display_rule'] if equipment_only else rules['behavior']),device,('自然侧方记录装备，全部关键器材清晰可辨' if equipment_only else framing),environment_text,('水中自然衰减的环境光，局部作业灯有明确来源' if submerged else '当前自然光：'+v['light']),rules['light_constraints'],
            rules['underwater_visibility'] if submerged else '',natural_result])
        if s['kind']=='cover' and s['type']=='underwater_discovery':
            s['prompt']+='\n'+config['cover_policy']['rule']
            s['camera']='水下定位照片，斜向空间层次与明确视觉焦点，非猎奇近拍'
        s['prompt']+='\n'+config['independent_generation']['rule']
        s['generation_input']={'mode':'text_to_image','referenced_image_paths':[],'num_last_images_to_include':0,'recursive_generated_references':False}
        s['prompt_sha256']=digest(s['prompt'])
    validate_group(group)
    return group

def validate_group(group):
    from tools.diving_salvage_physics import validate_group as validate_physics
    validate_physics(group)
    for shot in group.get('shots',[]):
        if shot.get('generation_input')!={'mode':'text_to_image','referenced_image_paths':[],'num_last_images_to_include':0,'recursive_generated_references':False}:
            raise ValueError('Independent text-only draft cannot bind previous generated images')
    n=group.get('content_group',{}).get('detail_count',6)
    from tools.diving_salvage_variation import check_variations
    check_variations(group)
    if len(group.get('shots',[]))!=n+1 or [s['kind'] for s in group['shots']]!=['cover']+['detail']*n:
        raise ValueError('每组图片数量必须符合冻结结构')
    if group.get('content_group')!={'cover_count':1,'detail_count':n,'total_images':n+1}:
        raise ValueError('冻结张数合同不一致')
    if group.get('output_contract')!=CONTRACT or group['anchor'].get('visual',{}).get('output_contract')!=CONTRACT:
        raise ValueError('组尺寸合同缺失或不一致')
    for s in group['shots']:
        if (s.get('raw_generation_size')!='1024x1536' or s.get('final_size')!='1024x1536'
                or s.get('output_ratio')!='2:3' or s.get('orientation')!='portrait'):
            raise ValueError('首图/详情横图或尺寸不一致')

def validate(config):
    from tools.diving_salvage import assemble
    cases=[('objects',None,None),('live_rescue',None,None),('deceased_recovery',None,None),
           ('underwater_work','inspect_record',None),('pipeline','clean','domestic'),
           ('pipeline','inspect','municipal'),('pipeline','underwater_pipeline','industrial')]
    checked=0;rejected=0;sites=set();angles=set();water=set()
    for branch,operation,cat in cases:
        stages=config['stages'] if branch=='objects' else config['branch_stages'][branch]
        plan=[[s['id']] for s in stages]
        for seed in range(40):
            g=assemble(config,seed,plan,branch=branch,operation=operation,pipe_category=cat)
            assert g==assemble(config,seed,plan,branch=branch,operation=operation,pipe_category=cat)
            validate_group(g);sites.add(g['anchor']['site']['id'])
            angles.update(s['framing'] for s in g['shots'])
            if g['anchor']['water']:water.add(g['anchor']['water'])
            assert all((config['equipment_display_rule'] if s.get('equipment_only') else config['documentary']['behavior']) in s['prompt'] for s in g['shots'])
            if cat=='domestic':assert all(s['capture_device']=='phone' for s in g['shots'])
            if branch in ['objects','underwater_work']:assert any(s['capture_device']=='underwater_action_camera' for s in g['shots'])
            if seed==0:
                for field,value in [('final_size','1536x1024'),('raw_generation_size','1536x1024'),('output_ratio','3:2')]:
                    bad=copy.deepcopy(g);bad['shots'][-1][field]=value
                    try:validate_group(bad)
                    except ValueError:rejected+=1
                    else:raise AssertionError('Invalid dimensions accepted')
                bad=copy.deepcopy(config);bad['output_contract']['final_size']='1536x1024'
                try:assemble(bad,seed,plan,branch=branch,operation=operation,pipe_category=cat)
                except ValueError:rejected+=1
                else:raise AssertionError('Landscape config accepted')
            checked+=1
    assert len(sites)>=8 and len(angles)>=4 and len(water)>=3
    # Scenic sites remain possible but cannot dominate the configured object pool.
    scenic=sum(bool(assemble(config,s,[[x['id']] for x in config['stages']])['anchor']['site'].get('scenic')) for s in range(200))
    assert scenic<40
    return {'visual_groups_checked':checked,'dimension_rejections':rejected,'sites_seen':len(sites),
            'framing_variants':len(angles),'water_variants':len(water),'scenic_groups_out_of_200':scenic}


def validate_fixed_groups(config):
    from tools.diving_salvage import assemble
    cases=[('objects',None,None),('live_rescue',None,None),('deceased_recovery',None,None),('underwater_work','measure',None),('pipeline','inspect','municipal'),('pipeline','clean','domestic'),('pipeline','underwater_pipeline','industrial')]
    rejected=0
    for b,op,cat in cases:
        ids=[s['id'] for s in (config['stages'] if b=='objects' else config['branch_stages'][b])]
        assert len(ids)==5 and 'search' not in ids
        plan=[[s] for s in ids]
        g=assemble(config,321,plan,branch=b,operation=op,pipe_category=cat)
        validate_group(g)
        for wrong in [plan[:-1],plan+[plan[-1]],plan[:2]+[['search']]+plan[2:],[ids],list(reversed(plan))]:
            try:assemble(config,321,wrong,branch=b,operation=op,pipe_category=cat)
            except ValueError:rejected+=1
            else:raise AssertionError('Wrong detail count or redundant timeline accepted')
        bad=copy.deepcopy(g);bad['shots'].append(copy.deepcopy(g['shots'][-1]))
        try:validate_group(bad)
        except ValueError:rejected+=1
        else:raise AssertionError('Wrong frozen count accepted')
    return {'fixed_group_routes_checked':len(cases),'count_or_timeline_errors_rejected':rejected,'cover_count':1,'detail_count':5,'total_images':6}
