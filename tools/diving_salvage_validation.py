"""Offline content-contract regression and sampled variability evidence."""
import copy,collections

def validate_all(c):
    from tools.diving_salvage import assemble,digest
    from tools.diving_salvage_visual import validate_group
    from tools.diving_salvage_environment import validate_environment
    from tools.diving_salvage_variation import signature,assemble_batch
    cases=[('objects',None,None),('live_rescue',None,None),('deceased_recovery',None,None)]+[('underwater_work',j['id'],None) for j in c['underwater_jobs']]+[('pipeline',j,k) for k,v in c['pipe_categories'].items() for j in v['jobs']]
    signatures=set();counts={k:collections.Counter() for k in ['water_view','shore_view','lead','team_size','water','cover_structure','site','visible_people']};groups=0;negative=0;plans=set()
    for b,op,cat in cases:
        for seed in range(30):
            kw={'branch':b,'operation':op,'pipe_category':cat};g=assemble(c,seed,**kw);a=g['anchor'];wet=a['visual']['underwater_capable'];validate_group(g);validate_environment(c,a)
            assert g==assemble(c,seed,**kw)
            assert len({s['anchor_sha256'] for s in g['shots']})==1 and g['anchor_sha256']==digest(a)
            assert len(g['shots'])==7
            equipment=g['shots'][2 if wet else 1];assert equipment['equipment_only'] and not equipment['shot_variables']['visible_ids']
            assert g['shots'][3]['stages']==['prepare']
            assert ('entry_airborne' in [s['stages'][0] for s in g['shots'][1:]])==wet
            assert (g['selected_cover']=='underwater_discovery')==wet
            for s in g['shots']:
                assert s['environment']==a['environment'];v=s['shot_variables']
                for k,value in v.items():
                    if k not in ['visible_ids','view_id']:assert str(value) in s['prompt']
                key='water_view' if s['capture_device']=='underwater_action_camera' else 'shore_view';counts[key][v['view_id']]+=1;counts['visible_people'][str(len(v['visible_ids']))]+=1
                if 'cover_structure' in v:counts['cover_structure'][v['cover_structure']]+=1
            counts['lead'][a['cast'][0]['identity']]+=1;counts['team_size'][str(len(a['cast']))]+=1;counts['site'][a['site']['id']]+=1
            if wet:counts['water'][a['water_profile_id']]+=1;assert a['site']['id'] in c['entry_sites']
            signatures.add(signature(g));groups+=1;plans.add(len(g['shots'])-1)
            if seed==0:
                for plan in [g['shot_plan'][:-1],g['shot_plan']+[g['shot_plan'][-1]],list(reversed(g['shot_plan']))]:
                    try:assemble(c,seed,plan,**kw)
                    except ValueError:negative+=1
                    else:raise AssertionError('Bad timeline accepted')
                for key,value in [('raw_generation_size','1536x1024'),('final_size','1536x1024')]:
                    bad=copy.deepcopy(g);bad['shots'][0][key]=value
                    try:validate_group(bad)
                    except ValueError:negative+=1
                    else:raise AssertionError('Bad dimension accepted')
                bad=copy.deepcopy(g);bad['shots'][0]['generation_input']['referenced_image_paths']=['previous.png']
                try:validate_group(bad)
                except ValueError:negative+=1
                else:raise AssertionError('Reference chain accepted')
    for obj in c['objects']:
        g=assemble(c,71,object_id=obj['id']);assert g['anchor']['object']['size'] in g['anchor']['site']['sizes']
    for b,op,cat in cases:
        g=assemble(c,8,branch=b,operation=op,pipe_category=cat)
        if g['anchor']['visual']['underwater_capable']:
            for cover in c['legacy_cover_definitions']:
                try:assemble(c,8,branch=b,operation=op,pipe_category=cat,cover_type=cover['id'])
                except ValueError:negative+=1
                else:raise AssertionError('Legacy cover accepted')
    for target in ['car','boat','large_machine']:
        try:assemble(c,1,object_id=target,site_id='pool')
        except ValueError:negative+=1
        else:raise AssertionError('Large object shallow pool')
    for op in ['underwater_pipeline','trenchless']:
        try:assemble(c,1,branch='pipeline',operation=op,pipe_category='domestic')
        except ValueError:negative+=1
        else:raise AssertionError('Domestic mismatch')
    batch,stats=assemble_batch(lambda seed:assemble(c,seed),900,100)
    assert stats['unique_combinations']==100
    # Forced repeat verifies bounded detection instead of silent duplication.
    try:assemble_batch(lambda seed:batch[0],900,2)
    except ValueError:negative+=1
    else:raise AssertionError('Duplicate batch accepted')
    assert len(counts['water_view'])==6 and len(counts['lead'])==6 and len(counts['water'])==6
    from tools.diving_salvage_physics_validation import validate_physics_cases
    physics_checks=validate_physics_cases(c)
    return {**physics_checks,'ok':True,'api_called':False,'sampled_groups':groups,'routes':len(cases),'object_types':len(c['objects']),
        'unique_group_combinations':len(signatures),'duplicate_rate':1-len(signatures)/groups,'negative_checks':negative,
        'detail_counts':sorted(plans),'batch':stats,'pool_dimensions':len(c['variation_pools']),
        'pool_candidates':sum(len(v) for v in c['variation_pools'].values()),'distributions':{k:dict(v) for k,v in counts.items()}}
