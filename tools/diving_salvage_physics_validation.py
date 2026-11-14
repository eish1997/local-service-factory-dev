import copy

def validate_physics_cases(c):
    from tools.diving_salvage import assemble
    from tools.diving_salvage_visual import validate_group
    from tools.diving_salvage_physics import freeze_geometry
    cases=[('objects',None,None),('live_rescue',None,None),('deceased_recovery',None,None),('underwater_work','install',None),('pipeline','underwater_pipeline','industrial'),('pipeline','clean','domestic')]
    positive=0;negative=0;poses=set()
    for b,op,cat in cases:
        for seed in range(20):
            g=assemble(c,seed,branch=b,operation=op,pipe_category=cat);validate_group(g);assert g==assemble(c,seed,branch=b,operation=op,pipe_category=cat)
            for shot in g['shots']:
                p=shot['physical_scene'];assert p['body_continuity'] in shot['prompt'];assert p['contact_rule'] in shot['prompt']
                if p['bundle']:
                    poses.add(p['bundle']['id']);assert p['bundle']['placement'] in shot['prompt'];assert p['bundle']['support'] in shot['prompt']
                if shot.get('equipment_only'):assert not shot['shot_variables']['visible_ids'] and p['mode']=='static'
            positive+=1
    source=assemble(c,7,branch='live_rescue')
    # Do not accept wrong water/land sides, hidden support, broken limbs or unowned contacts.
    for index in [1,5,6]:
        for field,value in [('target_side','land' if index!=6 else 'water'),('support_visible',False),('limb_integrity','broken')]:
            bad=copy.deepcopy(source);bad['shots'][index]['physical_scene']['bundle'][field]=value
            try:validate_group(bad)
            except ValueError:negative+=1
            else:raise AssertionError((index,field))
    for edit in ['role','contact','spacing','crop','depth','splash']:
        bad=copy.deepcopy(source);shot=bad['shots'][5]
        if edit=='role':shot['physical_scene']['bundle']['contact_map'][0][0]='ghost'
        elif edit=='contact':shot['physical_scene']['bundle']['contact_map'][0][2]='wrong_wrist'
        elif edit=='spacing':shot['shot_variables']['relation']='far apart, floating contact'
        elif edit=='crop':shot['shot_variables']['body']='hands only, all support hidden'
        elif edit=='depth':bad['anchor']['physical_geometry']['depth']='shallow'
        else:bad['shots'][1]['physical_scene']['bundle']['splash']=True
        try:validate_group(bad)
        except ValueError:negative+=1
        else:raise AssertionError(edit)
    a=copy.deepcopy(source['anchor']);a['environment']['selected']['depth']='shallow'
    try:freeze_geometry(c,a)
    except ValueError:negative+=1
    else:raise AssertionError('Shallow entry accepted')
    a=copy.deepcopy(source['anchor']);a['environment']['selected']['water_level']='lower';assert freeze_geometry(c,a)['depth'] in ['working','deep']
    return {'physical_positive_groups':positive,'physical_negative_cases':negative,'physical_pose_bundles_seen':sorted(poses),'pixel_review_performed':False}
