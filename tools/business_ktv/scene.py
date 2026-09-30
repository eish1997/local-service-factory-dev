"""Seeded, constrained scene and realism sampling. Never calls a model."""

from tools import variable_catalog
import hashlib
import json
import random


STRUCTURAL = ('ROOM_TYPE', 'LAYOUT', 'SOFA', 'TABLE', 'ROOM_STYLE',
              'CAMERA_POSITION', 'CAMERA_DISTANCE', 'COMPOSITION')


def signature(scene):
    return '|'.join(scene[k] for k in STRUCTURAL)


@variable_catalog.managed('business_ktv','detail',documents=(('config','configs/business_ktv/scene_library.json'),),finish_result=False)
def sample(config, strategy, seed, previous=(), mode='explore'):
    rng = random.Random(seed)
    variables = config['variables']
    preferences = config.get('style_preferences', {}).get('selection_multipliers', {})
    # Exploration ignores learned success weights; explicit style preferences apply to all modes.
    explore = mode != 'inherit'
    for _ in range(300):
        scene = {}
        for key, values in variables.items():
            factors = [preferences.get(key, {}).get(v, 1) for v in values]
            if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not .1 <= v <= 5 for v in factors):
                raise ValueError('风格偏好系数必须在0.1—5之间，不能永久排除变量')
            weights = [(1 if explore else strategy['weights'].get(key, {}).get(v, 1)) * factor for v, factor in zip(values, factors)]
            scene[key] = rng.choices(values, weights=weights)[0]
        room = scene['ROOM_TYPE']
        if room in ('KTV大厅', 'KTV走廊'):
            scene.update(TABLE_STATE='不适用', TABLE='无酒水茶几', SOFA='公共区域等候座椅' if room == 'KTV大厅' else '无沙发',
                         LAYOUT='前台与等候区错位' if room == 'KTV大厅' else '错位包厢门与消防通道')
            scene['CAMERA_POSITION'] = rng.choice(['门口斜拍', '正常人眼高度', '房间角落'])
            scene['CAMERA_DISTANCE'] = rng.choice(['中景', '广角环境'])
        elif room == '酒水准备完成的空包':
            scene['TABLE_STATE'] = '刚整理完成'
        elif room == '消费后的包厢':
            scene['TABLE_STATE'] = '消费结束状态'
        elif room == '正在消费的包厢':
            scene['TABLE_STATE'] = rng.choice(['正常消费状态', '轻微凌乱', '水果+酒水'])
        # Structural changes must involve >=3 dimensions, never just lighting/props.
        if any(sum(scene[k] != old[k] for k in STRUCTURAL) < 3 for old in previous):
            continue
        combo = '|'.join(scene[k] for k in config['optimization']['combination_keys'])
        if not explore and rng.random() > strategy.get('combinations', {}).get(combo, 1):
            continue
        imperfections = list(config['imperfections'])
        if room in ('KTV大厅', 'KTV走廊'):
            imperfections = [x for x in imperfections if not any(w in x for w in ('杯', '水果', '桌面', '冰桶', '靠枕'))]
        if scene['TABLE_STATE'] == '刚整理完成':
            imperfections = [x for x in imperfections if '使用痕迹' not in x and '水渍' not in x]
        scene['imperfections'] = variable_catalog.sample_unique(rng, imperfections, rng.randint(2, min(4, len(set(imperfections)))))
        scene['seed'] = seed
        scene['exploration'] = explore
        scene['mode'] = mode
        profile = config.get('realism_profile')
        if profile:
            # Keep the sampled state causally consistent; persist the resolved variables.
            if scene['TABLE_STATE'] == '刚整理完成':
                if scene['DRINKS'] == '已开封饮料与半杯饮品':
                    scene['DRINKS'] = '酒水准备盘与空杯'
                if scene['FRUIT'] == '已取走少量水果的果盘':
                    scene['FRUIT'] = '少量哈密瓜与圣女果'
            scene['realism_profile_version'] = profile['version']
            scene['screen_state'] = rng.choice(profile['screen_states'])
            scene['event'] = profile['events'].get(scene['TABLE_STATE'], '营业中的公共区域，保持正常通行。')
            for scene_key, mapping_key, variable in (('sofa_detail', 'sofa_details', 'SOFA'), ('table_detail', 'table_details', 'TABLE')):
                if mapping_key in profile:
                    scene[scene_key] = profile[mapping_key].get(scene[variable], '')
        scene['signature'] = hashlib.sha256(signature(scene).encode()).hexdigest()
        return scene
    raise ValueError('结构差异约束无法满足，停止准备本轮；请扩大场景库，不放宽为仅换灯光。')


@variable_catalog.managed('business_ktv','detail',documents=(('config','configs/business_ktv/scene_library.json'),))
def prompt(scene, config, strategy):
    if config.get('realism_profile'):
        return causal_prompt(scene, config, strategy)
    public = scene['ROOM_TYPE'] in ('KTV大厅', 'KTV走廊')
    geometry = ('公共区域保持通行宽度，门洞、地面、墙面透视连续。' if public else
                '电视、触控点歌设备与麦克风自然可辨；座位朝向屏幕，茶几低于坐姿胸口，保留进出通道。')
    objects = '' if public else f"桌面处于{scene['TABLE_STATE']}，{scene['DRINKS']}，{scene['FRUIT']}，物品密度{scene['DENSITY']}。"
    return (f"中国真实高端商务KTV的{scene['ROOM_TYPE']}，工作人员用手机随手记录现场，无摆拍人物。\n"
            f"{scene['ROOM_STYLE']}，{scene['LAYOUT']}，{scene['SOFA']}，{scene['TABLE']}。{geometry}\n"
            f"从{scene['CAMERA_POSITION']}拍摄{scene['CAMERA_DISTANCE']}，{scene['COMPOSITION']}；广角只用正常手机视角，不用超广角。\n"
            f"{scene['LIGHTING']}，有实际灯具来源，辅助彩光不过度染满房间。{objects}\n"
            f"现场自然细节：{'、'.join(scene['imperfections'])}。整洁但有正常使用感。\n"
            + config['prompt_structures'][strategy.get('prompt_structure', 0) % len(config['prompt_structures'])]
            + '\n排除：' + '、'.join(config['negative'])
            + '\n本轮重点：' + '；'.join(strategy.get('focus', []))
            + (f"\n定向实验：针对{scene['experiment']}，减少物品遮挡，检查接触点和材质反射，换用不同空间结构。" if scene.get('experiment') else ''))


def causal_prompt(scene, config, strategy):
    """Narrate one usable scene, without copying scores/diagnoses into prompts."""
    profile = config['realism_profile']
    public = scene['ROOM_TYPE'] in ('KTV大厅','KTV走廊')
    room = scene['ROOM_TYPE'].replace('豪华VIP包','VIP包厢').replace('超大商务包','较大的商务包厢')
    materials = profile['materials_by_style'][scene['ROOM_STYLE']]
    lighting = profile['lighting_by_choice'][scene['LIGHTING']]
    if public:
        lighting = profile.get('public_lighting', '公共区域以正常暖白顶灯照明，壁灯照亮附近墙面，较远位置允许自然变暗。')
    setting = f"眼前是{room}，{scene['LAYOUT']}，{scene['SOFA']}，{scene['TABLE']}。{materials}。"
    if public:
        setting += profile.get('public_interior_structure', '')
    else:
        setting += profile.get('interior_structure', '')
        setting += scene.get('sofa_detail', '') + scene.get('table_detail', '')
    layout = profile.get('layout_relations', {}).get(scene['LAYOUT'], '')
    scene_detail = ('公共区域门洞、墙面和通行地面连续，不放酒水果盘。' if public else
        f"{layout}{profile['geometry']}{scene['event']}{profile['objects']}{scene['DRINKS']}；{scene['FRUIT']}，物品密度{scene['DENSITY']}。"
        f"{scene['screen_state']}麦克风自然放在支架或桌侧，点歌台只在侧面露出一部分。")
    imperfections = [item for item in scene['imperfections'] if item not in ('轻微手机HDR','灯光局部过曝','不同色温混合','玻璃真实反射')]
    details = ('偶然细节：'+'、'.join(imperfections[:2])+'，这些痕迹只出现在合理的位置。') if imperfections else ''
    # Translate diagnoses into positive, scoped experiments; never paste failure prose.
    targeted = ''
    if not public and scene.get('experiment'):
        for word, repair in profile.get('targeted_repairs', {}).items():
            if word in scene['experiment']:
                targeted = repair
                break
    return '\n'.join([profile['intent'],setting,scene_detail,
        f"从{scene['CAMERA_POSITION']}拍摄{scene['CAMERA_DISTANCE']}，{scene['COMPOSITION']}。{profile['camera']}",
        lighting,details,targeted,profile['constraints']])


def initial_strategy(config):
    return {'version': 1, 'weights': {k: {v: 1.0 for v in values} for k, values in config['variables'].items()},
            'combinations': {}, 'focus': [], 'prompt_structure': 0, 'best_realism': 0,
            'stagnant_rounds': 0, 'diagnosis_count': 0}


def improve(strategy, rows, config, recent_rounds):
    from collections import Counter
    result = json.loads(json.dumps(strategy))
    scored = [r for r in rows if r.get('audit')]
    winners = sorted((r for r in scored if r['audit']['decision'] == 'approved'),
                     key=lambda r: r['audit']['total_score'], reverse=True)[:3]
    low = [r for r in scored if r['audit']['decision'] == 'rejected']
    failures_now = Counter(reason for r in low for reason in r['audit'].get('failure_reasons', []))
    result['focus'] = [reason for reason, _ in failures_now.most_common(4)]
    result['verified_realism_rules'] = list(dict.fromkeys(reason for r in winners for reason in r['audit'].get('success_reasons', [])))
    result['feature_analysis'] = {
        label: {key: dict(Counter(r['scene'][key] for r in group)) for key in config['variables']}
        for label, group in (('high_score', winners), ('low_score', low))}
    # Learn photographic realism rather than cloning winning room geometry.
    learnable = ('LIGHTING', 'DENSITY', 'TABLE_STATE')
    for group, multiplier in ((winners, 1.12), (low, .85)):
        for row in group:
            for key, weights in result['weights'].items():
                if key not in learnable:
                    continue
                value = row['scene'].get(key)
                if value in weights:
                    weights[value] = round(max(.3, min(3, weights[value] * multiplier)), 5)
            combo = '|'.join(row['scene'][k] for k in config['optimization']['combination_keys'])
            result['combinations'][combo] = max(.3, min(1, result['combinations'].get(combo, .8) * multiplier))
    best = max((r['audit']['realism_score'] for r in winners), default=0)
    improved = best > result['best_realism'] + config['optimization']['improvement_delta']
    result['stagnant_rounds'] = 0 if improved else result['stagnant_rounds'] + 1
    result['best_realism'] = max(best, result['best_realism'])
    diagnosis = None
    if result['stagnant_rounds'] >= 5:
        failures = Counter(reason for batch in recent_rounds[-4:] + [scored]
                           for r in batch for reason in r.get('audit', {}).get('failure_reasons', []))
        result['focus'] = [reason for reason, _ in failures.most_common(4)] or ['减少场景陈列感，扩大布局与机位探索']
        result['prompt_structure'] += 1
        # Re-open every dimension (including density/style), never permanently delete it.
        for weights in result['weights'].values():
            for value in weights:
                weights[value] = round((weights[value] + 1) / 2, 5)
        result['combinations'] = {k: (v + 1) / 2 for k, v in result['combinations'].items()}
        result['stagnant_rounds'] = 0
        result['diagnosis_count'] += 1
        diagnosis = {'failure_counts': dict(failures), 'actions': ['场景/机位/灯光/密度/装修权重回温', '切换提示词结构', '追加失败原因负面约束'],
                     'allocation': {'inherit': .5, 'explore': .3, 'experiment': .2}}
    result['version'] += 1
    return result, winners, diagnosis
