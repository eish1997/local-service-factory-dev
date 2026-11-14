"""Pre-composition scene constraints. Descriptive illustration, not rescue instruction."""
import copy

def freeze_geometry(config,a):
    wet=a.get('underwater',True)
    if not wet:return {'mode':'land','water_side':None,'support_surface':'现有室内地面或工作台'}
    depth=a['environment']['selected'].get('depth')
    if depth not in ['working','deep'] or a['site']['id'] not in config['entry_sites']:
        raise ValueError('Airborne entry incompatible with site/depth')
    bank=a['environment']['selected']['bank']
    kind='platform' if a['site']['id'] in ['dock','drydock','harbor','ship_side'] else 'bank'
    return {'mode':kind,'bank_id':bank,'depth':depth,'water_level':a['environment']['selected']['water_level'],
        'water_side':'岸缘外侧连续水域','land_side':'水线内侧稳定干燥作业面',
        'support_surface':'作业船或码头现有平台' if kind=='platform' else '岸段现有稳定维护台阶或平整作业位置',
        'boundary':'岸坡或平台边缘与水线清楚相接；地面在岸侧，水域在外侧；局部遮挡仍可判断两侧位置',
        'depth_rule':'水位高低与水深是不同变量；低水位不等于浅水。入水区具有与潜水者体量相称的水柱空间，不能画成露底浅滩或泥坑；不凭图像宣称现场安全。'}

def plan(config,g,s,submerged):
    from tools.diving_salvage_variation import rng_for
    a=g['anchor'];stage=s['stages'][-1] if s['stages'] else None;branch=g.get('branch','objects')
    mode='ordinary'
    if s.get('equipment_only') or s['type']=='storefront':mode='static'
    elif stage=='entry_airborne':mode='entry'
    elif branch=='live_rescue' and stage=='assist':mode='live_water'
    elif branch=='live_rescue' and stage=='handover':mode='live_land'
    elif branch=='deceased_recovery' and stage in ['transfer','handover']:mode='covered_water' if stage=='transfer' else 'covered_land'
    elif branch=='objects' and stage=='recover':mode='item_water' if a['object']['size']=='small' else 'load_water'
    elif branch=='objects' and stage=='handover':mode='item_land'
    rows=config['physical_scene_rules']['bundles'].get(mode,[])
    bundle=copy.deepcopy(rng_for(g['seed'],'physics:'+str(s['position'])).choice(rows)) if rows else None
    return {'mode':mode,'geometry':copy.deepcopy(a['physical_geometry']),'bundle':bundle,
        'body_continuity':'每个可见身体从肩、躯干、骨盆至腿连续；关节方向与动作一致，遮挡只能遮住身体不能把肢体插入土岸或平台。水下腿可由水体自然遮住但必须仍在水域一侧。',
        'contact_rule':'每条手臂明确属于对应角色，手指与接触点连续；不交叉错接手臂，不凭画外支撑解释悬空受力或缺失肢体。',
        'render_note':config['physical_scene_rules']['note']}

def joint_variables(p):
    b=p['bundle']
    if not b:return {}
    return {'distance':'中景保留岸水边界、身体连续性及全部必要支撑',
        'body':b['body'],'visible_people':b['visible'],'visible_ids':list(b['crew']),
        'task':b['action'],'relation':b['relation'],'facing':'各角色关注各自接触点，不看镜头',
        'progress':'同一成套姿态关系的进行中瞬间，不与其他姿态拼接',
        'occlusion':'只允许边缘轻遮挡，不遮必要的接触点、支撑面和岸水边界'}

def render(p):
    lines=['前置空间与接触约束（先满足，再选择构图）：',p['body_continuity'],p['contact_rule'],p['render_note']]
    geom=p['geometry']
    if geom['mode']!='land':lines += [geom['boundary'],geom['depth_rule'],'固定岸上支撑：'+geom['support_surface']]
    b=p['bundle']
    if b:
        lines += ['成套姿态：'+b['id'],b['placement'],b['support'],b['action'],b['relation'],'接触归属：'+'；'.join(b['contacts'])]
    return '\n'.join(lines)

def validate_group(g):
    wet=g['anchor']['visual']['underwater_capable'];geom=g['anchor']['physical_geometry']
    if wet and (geom['depth'] not in ['working','deep'] or geom['water_level']!=g['anchor']['environment']['selected']['water_level']):raise ValueError('Depth/waterline mismatch')
    ids={m['id'] for m in g['anchor']['cast']}
    for s in g['shots']:
        p=s.get('physical_scene');v=s['shot_variables']
        if not p or p['geometry']!=geom:raise ValueError('Missing or changed scene geometry')
        b=p['bundle']
        if s.get('equipment_only') and (p['mode']!='static' or v['visible_ids']):raise ValueError('Static frame contains people')
        if not b:continue
        if set(b['crew'])-ids:raise ValueError('Contact role missing from frozen cast')
        expected=joint_variables(p)
        if any(v.get(k)!=value for k,value in expected.items()):raise ValueError('Random camera broke joint pose')
        if b['target_side'] not in {'water','land','none'}:raise ValueError('Invalid body side')
        required={'live_water':'water','covered_water':'water','item_water':'water','load_water':'water','live_land':'land','covered_land':'land','item_land':'land','entry':'none'}
        if b['target_side']!=required[p['mode']]:raise ValueError('Body on wrong side of waterline')
        if b['limb_integrity']!='continuous' or b['support_visible'] is not True:raise ValueError('Body or support missing')
        for owner,part,receiver in b['contact_map']:
            if owner not in ids or part not in ['left_hand','right_hand','both_hands'] or receiver not in b['contact_targets']:raise ValueError('Invalid contact ownership')
        if p['mode']=='entry' and (b['touches_water'] or b['splash']):raise ValueError('Entry has premature water contact')
