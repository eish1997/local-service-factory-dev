"""Truck-compatible capture pools copied from road rescue; new catalog tasks only."""
import copy
import random
from tools import variable_catalog as vc


def enabled():
    ctx = vc.CURRENT.get()
    return bool(ctx and any(d.get('binding', {}).get('module') == __name__
                            for d in ctx['catalog']['dimensions']))


@vc.managed('truck_rescue', finish_result=False)
def choose(group_index, position, cover=False, override_heavy=None):
    rng = random.Random(f'truck_shared_v1:{group_index}:{position}')
    heavy = (group_index + position - 1) % 5 != 0
    if override_heavy is not None:
        heavy = override_heavy
    vehicles = HEAVY_VEHICLES if heavy else OTHER_VEHICLES
    # Rotate independently of the five-unit mix so all heavy body types appear.
    vehicle = vehicles[(group_index // 5 + position * 3) % len(vehicles)]
    treatment = PHOTO_TREATMENTS[(group_index + position * 3) % len(PHOTO_TREATMENTS)]
    flaw = rng.choices(SNAPSHOT_FLAWS, weights=[x['weight'] for x in SNAPSHOT_FLAWS])[0]
    device = CAPTURE_DEVICES[(group_index + position * 2) % len(CAPTURE_DEVICES)]
    roll = rng.choice(HANDHELD_ROLL) if rng.random() < .45 else 0
    incidental = rng.sample(BACKGROUND_ELEMENTS, min(rng.choices([0,1,2], [3,5,2])[0], len(BACKGROUND_ELEMENTS)))
    result = {'heavy': heavy, 'vehicle': vehicle, 'device': device,
              'treatment': treatment, 'flaw': flaw, 'roll': roll,
              'incidental': incidental}
    if cover:
        result.update(environment=COVER_ENVIRONMENTS[group_index % len(COVER_ENVIRONMENTS)],
                      material=SIGN_MATERIALS[group_index % len(SIGN_MATERIALS)],
                      sign_layout=SIGN_LAYOUTS[(group_index // 3) % len(SIGN_LAYOUTS)],
                      sign_wear=SIGN_WEAR[(group_index // 7) % len(SIGN_WEAR)])
    return result


def capture_instruction(choice):
    if choice['device']['id'].startswith('professional_'):
        incidental='；'.join(x['description'] for x in choice['incidental']) or '不额外添加生活元素'
        return ('\n本次指定摄影设备：'+choice['device']['description']+
                '自然中性白平衡，真实材质和正常曝光，不套手机降噪、转发压缩、手抖、失焦或胶片滤镜。'
                '相机型号只作为成像要求，不在照片里写型号、参数或品牌水印；后续本地电话和服务词保持清楚。'
                '\n背景生活元素：'+incidental+'；只在当前场景可见的独立通道或边缘出现，不进入维修区，不遮挡电话或关键动作，不额外添加未选元素。')
    from tools.road_postprocess_variants import postprocess_instruction
    from tools.road_snapshot_variants import snapshot_instruction
    flaw = choice['flaw']['description'].replace('{motion_target}', '当前已选作业人员的手腕与工具末端')
    snapshot = {'description': flaw, 'strength': '很轻，招牌号码和操作接触点保持可辨',
                'roll_description': f"整幅照片自然横滚{choice['roll']}度，建筑透视一致，无旋转黑边；后续本地叠字保持水平"}
    treatment = {**choice['treatment'], 'strength': '适量可感知，不夸张'}
    incidental = '；'.join(x['description'] for x in choice['incidental']) or '不额外添加生活元素'
    return ('\n手机成像：' + choice['device']['description'] + '。'
            + postprocess_instruction(treatment) + snapshot_instruction(snapshot)
            + '\n背景生活元素：' + incidental
            + '；只在既有场景可见的独立通行车道或边缘出现，院内无可见道路时不添加经过车流；'
              '不进入维修区，不遮挡招牌电话、车辆故障部位与关键动作，不添加其他未选元素。')


def vehicle_geometry(vehicle, heavy, cab_state):
    if '半挂' in vehicle:
        axles='本次选定三轴6×4牵引车，前一轴、后两轴；连接普通三轴半挂车，挂车后方三轴成组；牵引车和挂车通过真实鞍座连接，不把挂车画成车头自己的短货箱'
    elif '8×4' in vehicle:
        axles='本次选定四轴8×4载货底盘，前两轴与后两轴位置明确，货厢固定在同一连续车架上，不额外添加第五轴'
    elif '牵引' in vehicle:
        axles='本次选定三轴6×4牵引车，前一轴、后两轴，未连接挂车时车架后段与鞍座可见，不能凭空接出货厢'
    elif heavy:
        axles='本次选定三轴6×4平头重型载货底盘，前一轴、后两轴，驾驶室与货厢属于同一连续车架，不随机增加或删除车轴'
    else:
        axles='本次选定普通两轴平头轻中型商用载货底盘，前后一轴，货厢与驾驶室保持真实长度关系，不画成重卡多轴底盘'
    cab=(
        '驾驶室状态只允许这一种：平头驾驶室整体向车辆前方绕原车前部下方铰接点翻转并可靠锁止，'
        '前挡风玻璃、车顶、两侧车门作为同一刚性壳体共同旋转，不把挡风玻璃当作单独掀开的发动机盖。'
        '发动机留在原车架上，车架、轮轴、车轮与货厢全部原位静止，发动机不能跟着驾驶室悬浮翻走。'
        '只露出真实原发动机空间，后背与车架间的翻转间隙连贯，不向后翻、不侧翻、不垂直升起整个车头，'
        '不同时再加一套轿车式前机盖；师傅站在车侧安全位置，不钻悬起驾驶室下方。'
        if cab_state=='tilted' else
        '驾驶室保持正常落位并锁止，驾驶室外壳与底盘连接完整；本次不翻转驾驶室、不掀开轿车式前机盖，'
        '不凭空暴露整个发动机、不画升起或断开的车头。允许正常打开车门，但开车门不等于翻转驾驶室。'
    )
    return ('\n车辆结构硬约束：'+axles+'。'+cab+
            '驾驶室保持真实平头货车宽高，货厢与驾驶室宽度协调，轮胎尺寸与车身、师傅身高相称。'
            '同一轴左右轮、轮毂和轮胎同心，所有未拆卸车轮接地；遮挡可以隐藏轮子，不能用遮挡制造多余轮轴。'
            '不把大车缩成小车头加巨大货箱，不拉长驾驶室、不挤短轴距、不拼接两种车型。'
            '需要整体车身时后退用普通手机正常透视；近景允许只取真实局部，不能为塞进招牌和叠字区域把全车压缩变形。')


def enhance_rows(rows, seed):
    """Only new shared tasks with the new catalog; old frozen data stay unchanged."""
    if not enabled():
        return rows
    import re
    from tools.truck_scene_diversity_v3 import EVENTS, ROLES
    result = copy.deepcopy(rows)
    for position, row in enumerate(result, 1):
        cover = row['generation_kind'] == 'cover'
        override_heavy = None
        if not cover:
            for dim in vc.CURRENT.get()['catalog']['dimensions']:
                if dim['id'] in vc.FORCE.get() and dim.get('binding',{}).get('name')=='EVENTS' and dim['binding'].get('dictkey')==row['service_role']:
                    forced = vc.option_pool(dim, EVENTS[row['service_role']])[0]
                    override_heavy = '重型' in forced[1] or '重卡' in forced[1]
        choice = choose(seed, position, cover, override_heavy)
        scene = row['scene']
        positive = row['positive_prompt']
        cab_state='closed'
        if cover:
            old = scene['front_activity']
            action = re.sub(r'(?:一辆)?(?:已熄火的燃油)?(?:空气制动)?(?:轻型栏板货车|中型载货车|中型货车|重型平头货车|重型载货车|重型牵引车|重型厢式货车|货车)',
                            choice['vehicle'], old, count=1)
            if action == old:
                action = '本次故障车辆为' + choice['vehicle'] + '；' + old
            positive = positive.replace(old, action)
            scene['front_activity'] = action
            env = choice['environment']
            positive = positive.replace(scene['storefront_location'], env['setting'])
            positive = positive.replace(scene['storefront_layout'], env['facade'] + '；' + env['ground'])
            material = '；'.join(choice['material'])
            positive = positive.replace(scene['signboard_variant'], material + '；' + choice['sign_wear'])
            existing_layout=scene.get('sign_information_layout')
            if existing_layout:
                # Two compatible layout pools are alternatives, never conflicting directives.
                if seed % 2 == 0:
                    choice['sign_layout']=existing_layout
                else:
                    positive=positive.replace(existing_layout,choice['sign_layout'])
                    scene['sign_information_layout']=choice['sign_layout']
            positive += '\n实体主招牌排版：' + choice['sign_layout'] + '；电话始终位于同一主招牌板内。'
            if env['camera_area'] == 'yard':
                positive = positive.replace('街对面', '场地对侧').replace('右侧街道纵深', '右侧独立通道纵深')
            scene.update(storefront_location=env['setting'], storefront_layout=env['facade'], signboard_variant=material)
            if not choice['heavy'] and ('气路' in action or '空气制动' in action):
                corrected = choice['vehicle']+'停稳在外侧工位，师傅用灯检查可见液压制动软管外观，车轮着地且轮挡到位，不拆卸管线'
                positive = positive.replace(action, corrected)
                scene['front_activity'] = corrected
                detail = scene.get('work_detail')
                if detail:
                    scene['work_detail']='工作灯与检查镜只在可见液压制动软管外侧使用，工具不排成展示列'
                    positive = positive.replace(detail,scene['work_detail'])
            if not choice['heavy']:
                positive=positive.replace('匹配24V','匹配车辆额定低压系统')
        else:
            role = row['service_role']
            pool = EVENTS[role]
            for dim in vc.CURRENT.get()['catalog']['dimensions']:
                if dim.get('binding', {}).get('name') == 'EVENTS' and dim['binding'].get('dictkey') == role:
                    pool = vc.option_pool(dim, pool)
                    break
            candidates = [x for x in pool if ('重型' in x[1] or '重卡' in x[1]) == choice['heavy']]
            if not candidates:
                raise ValueError('该作业角色缺少与重卡比例匹配的车辆动作工具组合：' + role)
            event = candidates[(seed // 5 + ROLES.index(role)) % len(candidates)]
            if role=='货车发动机故障' and event[0] in {'engine_sensor','engine_line'}:
                cab_state='tilted'
            if choice['heavy']:
                # Trailer-wheel and empty tipper phases cannot be paired with an arbitrary body.
                if '挂车' in event[1] or '挂车' in event[4]:
                    compatible = [v for v in HEAVY_VEHICLES if '半挂' in v]
                    for dim in vc.CURRENT.get()['catalog']['dimensions']:
                        if dim.get('source')=='HEAVY_VEHICLES':
                            compatible=[o['value'] for o in dim['options'] if o['enabled'] and '半挂' in o['value']]
                    if not compatible: raise ValueError('挂车作业缺少半挂重卡候选')
                    choice['vehicle']=compatible[(seed//5+position)%len(compatible)]
                if '未连接挂车' in event[1]: choice['vehicle']='6×4重型牵引车，未连接挂车'
                if '自卸' in event[1]: choice['vehicle']='空载8×4重型自卸货车，车斗完全落下'
            vehicle = choice['vehicle'] + ('，' + event[1].split('，', 1)[1] if '，' in event[1] else '')
            for key, value in [('vehicle',vehicle), ('action',event[4]), ('tools',event[5])]:
                positive = positive.replace(scene[key], value)
                scene[key] = value
            scene.update(event_id=event[0], powertrain=event[2], brake_system=event[3])
        positive += ('\n车型约束：' + choice['vehicle']
                     + ('；无真实品牌，保留重卡多轴、大尺寸轮胎和对应驾驶室比例，不能缩成小货车。' if choice['heavy'] else '；无真实品牌，保持所选轻中型商用货车比例。')
                     + '仅重卡搭电使用匹配24V低压系统的设备，其他车型按实际低压系统匹配；'
                       '空气制动不混用液压储液壶；换轮使用额定重型支撑与车轮搬运设备。')
        positive+=vehicle_geometry(choice['vehicle'],choice['heavy'],cab_state)
        if choice['device']['id'].startswith('professional_'):
            choice['roll']=0
            positive=positive.replace('普通手机','专业相机').replace('手机纪实照片','相机纪实照片').replace('手机工作记录','相机工作记录').replace('手机随手','相机现场').replace('手机机位','相机机位').replace('手机两倍焦段','相机50mm焦段')
        positive += capture_instruction(choice)
        row.update(positive_prompt=positive, source_positive_prompt=positive,
                   prompt=positive + '\n严格排除：' + row['negative_prompt'])
        scene['shared_variants'] = choice
        scene['vehicle_geometry']={'version':'truck_geometry_v1','cab_state':cab_state,'vehicle':choice['vehicle']}
    return result

CAPTURE_DEVICES = [{'id': 'older_android_main', 'name': '较早款安卓手机主摄', 'description': '普通较早款安卓手机主摄随手直拍；动态范围有限，亮处略易过曝，店内暗部细节自然丢失，白平衡微暖，细节稍软但电话号码清晰，不人为叠加颗粒或污渍'}, {'id': 'budget_android_main', 'name': '入门安卓手机主摄', 'description': '入门安卓手机默认相机；阴影有轻微色噪与涂抹感，边缘适度软件锐化，曝光不完全均匀，普通生活记录质感，不能把整张图故意模糊'}, {'id': 'standard_phone_main', 'name': '普通手机标准主摄', 'description': '普通手机标准主摄原相机；中性色彩，中等对比度，适度细节，保留室内外真实亮度差，不开美颜、鲜艳滤镜、强HDR或人像虚化'}, {'id': 'phone_two_x', 'name': '手机两倍取景', 'description': '从稍远处用普通手机两倍取景，透视由实际较远距离决定，画面略有数码细节损失，背景与门店保持自然空间关系，不做电影长焦虚化，不能仍用贴近门口的超广角视角'}, {'id': 'older_iphone_main', 'name': '较早款苹果手机主摄', 'description': '较早款苹果手机主摄普通直出，色彩克制，局部高光容易偏亮，暗部不过分提亮，自然手机细节，不模拟人像模式或商业修图'}, {'id': 'work_phone_dusk', 'name': '普通工作手机暮色手持', 'description': '普通工作手机在傍晚手持直拍；普通门店灯光与天光有色温差，暗部轻微噪点，快速动作可有轻微拖影但招牌号码必须清晰，不使用长曝光夜景合成或霓虹电影调色'}]

PHOTO_TREATMENTS = [{'id': 'neutral_direct', 'name': '自然直出', 'color': '中性白平衡、正常饱和度，保留建筑和招牌原色', 'tone': '中等对比度，保留真实室内外明暗差，不全面提亮暗部', 'texture': '适度手机锐度，画面干净但不磨皮、不抹掉材料纹理'}, {'id': 'warm_daily', 'name': '暖调生活照', 'color': '可感知的轻暖米黄色调，红黄略暖，白墙只是暖白，肤色不橙', 'tone': '中低对比度，亮部柔和过渡，阴影仍有层次', 'texture': '保留普通手机细节，像相册里适量调暖后的日常照片，不加光晕'}, {'id': 'cool_documentary', 'name': '冷调纪实', 'color': '整体轻冷蓝灰调，绿蓝稍收敛，白墙微冷而肤色正常', 'tone': '中等偏高对比度，黑位略深但店内工具仍可辨', 'texture': '清楚克制的手机细节，不添加青橙分离或金属科幻色'}, {'id': 'muted_soft', 'name': '低饱和柔和', 'color': '明显但适量降低全局饱和度，招牌仍保留红蓝绿等原色，不变黑白', 'tone': '轻压高光、略抬黑位，柔和低对比度，不能泛灰到像蒙雾', 'texture': '锐化较轻，保留墙面和工具纹理，文字边缘仍清楚'}, {'id': 'clear_vivid', 'name': '手机鲜明', 'color': '适量增加鲜明度，让招牌和工装颜色更鲜活，但不改色相、不过饱和', 'tone': '中高对比度，亮部通透，暗部不死黑，不做HDR光边', 'texture': '适量手机锐化，材质清楚但不过度微对比，像普通相册鲜明滤镜'}, {'id': 'soft_bright', 'name': '明亮柔光', 'color': '自然中性略暖，色彩保持正常，不加粉色美颜色', 'tone': '整体曝光感小幅提高，阴影适量提亮、强高光压回；店内仍明显暗于室外，不能把夜景变白天', 'texture': '降低生硬锐化，保留实拍纹理，不虚化、不磨皮、不使用发光柔焦'}, {'id': 'restrained_film', 'name': '轻胶片色感', 'color': '暖高光与中性略冷阴影的克制色彩变化，绿略偏橄榄但店牌品牌色不改', 'tone': '柔和高光曲线、轻微褪黑感，对比适中，不做复古年代场景', 'texture': '仅极轻自然细颗粒感，正常观看不可盖住数字，不加划痕、漏光、日期戳或胶片边框'}, {'id': 'shared_phone_photo', 'name': '转发照片质感', 'color': '中性色彩略收敛，像普通手机照片经过一次社交平台保存', 'tone': '常规对比度，高光保留普通手机有限动态范围，不拉成灰片', 'texture': '极轻JPEG压缩与降噪痕迹，细节稍软；不得出现明显方块、重影、模糊号码或二次截图边框'}]

SNAPSHOT_FLAWS = [{'id': 'none', 'description': '本图对焦正常，无额外运动模糊或手抖重影，保持普通随手拍清晰度', 'weight': 25}, {'id': 'motion', 'description': '{motion_target}在真实动作方向上有少量短距离动态模糊，静止门框与招牌保持稳定；不为模糊额外添加人物车辆，不做速度线或长曝光光轨', 'weight': 25}, {'id': 'handshake', 'description': '按快门时轻微手抖，整幅静态边缘存在一致方向的极短拖影，细节略软但字形不重复分叉；不把招牌单独锐化成粘贴图层', 'weight': 15}, {'id': 'focus', 'description': '自动对焦略有偏差，焦点在门口附近，远近细节轻微变软；不做专业人像大光圈虚化，不用涂抹式局部模糊，招牌数字仍可直接辨读', 'weight': 20}, {'id': 'awkward_crop', 'description': '取景略仓促，随机截断一小段邻铺、非关键车身或屋檐，主体稍偏心；完整店名、电话和关键作业动作不能裁掉，不增加大块空地', 'weight': 15}]

HANDHELD_ROLL = [-3, -2, -1, 1, 2, 3]

BACKGROUND_ELEMENTS = [{'id': 'tree', 'description': '环境边缘的普通树木'}, {'id': 'cyclist', 'description': '在合法通行区域经过的骑车人'}, {'id': 'traffic', 'description': '低频经过车辆'}, {'id': 'pedestrian', 'description': '中远景路过行人'}]

HEAVY_VEHICLES = ['6×4重型牵引车，连接普通栏板半挂车', '6×4重型牵引车，连接封闭厢式半挂车', '6×4重型牵引车，连接仓栅半挂车', '6×4重型牵引车，连接平板半挂车', '8×4重型栏板载货车', '8×4重型仓栅载货车', '重型厢式载货车', '空载8×4重型自卸货车，车斗完全落下']

OTHER_VEHICLES = ['中型栏板载货车', '轻型厢式货车']

COVER_ENVIRONMENTS = [{'id': 'county_low_row', 'name': '县城低层沿街铺', 'bays': 1, 'setting': '县城辅街一排低层汽车服务铺', 'facade': '一至两层自建商铺，抹灰墙与局部裸砖相接，铁皮短雨棚，双扇折叠铁门，不套用居民楼立面', 'ground': '足够容纳重卡的独立平整硬化工位，与行车道和行人通道隔离；维修不在狭窄人行道进行', 'neighbours': '五金铺侧墙和一扇关闭的邻铺门，建筑宽窄高低不齐', 'activity': '背景安静，无近景行人或骑车人', 'edge': '邻铺短雨棚边', 'camera_area': 'street', 'business': '货车救援维修'}, {'id': 'logistics_steel_shed', 'name': '物流园钢棚', 'bays': 2, 'setting': '物流园内部普通汽车救援服务铺', 'facade': '独立单层钢结构棚房，灰蓝压型钢板墙，大跨度方钢梁和高开间推拉门，招牌固定于棚檐，无楼上住宅窗和空调排阵', 'ground': '足够容纳重卡的独立平整硬化工位，与行车道和行人通道隔离；维修不在狭窄人行道进行', 'neighbours': '仓库侧墙和远处装卸通道，不出现紧贴生活零售邻铺', 'activity': '远处可有小型搬运车，近景无人横穿', 'edge': '棚柱侧缘', 'camera_area': 'yard', 'business': '货车救援维修'}, {'id': 'suburban_courtyard', 'name': '城郊院落式门店', 'bays': 2, 'setting': '城郊辅路旁可进车的小院汽车服务铺', 'facade': '院内低矮砖混平房，普通双开铁门打开，实用瓦楞雨棚，主招牌固定在实际车间门楣而非院门或围墙', 'ground': '足够容纳重卡的独立平整硬化工位，与行车道和行人通道隔离；维修不在狭窄人行道进行', 'neighbours': '低围墙、侧边小储物间，远处少量普通民房', 'activity': '安静工作院落，不添加过路行人或电动车', 'edge': '打开的院门边缘，仅一小角', 'camera_area': 'yard', 'business': '货车救援维修'}, {'id': 'industrial_brick_workshop', 'name': '旧工业厂房服务铺', 'bays': 2, 'setting': '小工业园边缘的汽车服务车间', 'facade': '普通红砖厂房外墙，较高侧窗，灰色钢门敞开，实用平屋顶，两开间跨度不同，不加住宅阳台', 'ground': '足够容纳重卡的独立平整硬化工位，与行车道和行人通道隔离；维修不在狭窄人行道进行', 'neighbours': '相邻设备维修车间的无字金属门与普通厂区围栏', 'activity': '可有一名远处工人背影，没有城市车流', 'edge': '砖柱侧边', 'camera_area': 'yard', 'business': '货车救援维修'}, {'id': 'town_roadside_bungalow', 'name': '乡镇路边平房', 'bays': 1, 'setting': '乡镇连接路旁普通汽车救援店', 'facade': '单层水泥抹灰平房，低坡瓦顶，实用铁门和一扇侧窗，招牌安装在车间门口檐下，不做破败废屋', 'ground': '足够容纳重卡的独立平整硬化工位，与行车道和行人通道隔离；维修不在狭窄人行道进行', 'neighbours': '一侧低矮民房，另一侧空隙能看见普通树篱，非荒野场景', 'activity': '背景无行人或骑车人，远处道路只作环境', 'edge': '一侧屋檐小角', 'camera_area': 'street', 'business': '货车救援维修'}, {'id': 'commercial_parking_edge', 'name': '商用停车场边服务铺', 'bays': 1, 'setting': '普通露天商用停车场边的小型汽车救援铺', 'facade': '停车场边独立低矮混凝土服务房，普通铝合金门与侧面工作通道，实用浅色外墙，无居民楼上层', 'ground': '足够容纳重卡的独立平整硬化工位，与行车道和行人通道隔离；维修不在狭窄人行道进行', 'neighbours': '背景低围栏与零散停放的普通车辆，没有连续商业街门头', 'activity': '现场安静，车停着而非形成前景过路车流', 'edge': '服务房侧墙', 'camera_area': 'yard', 'business': '货车救援维修'}]

SIGN_MATERIALS = [('喷绘布绷在普通方管框架上，四周收边和少量紧固点真实', '普通红底白字，黄色仅强调电话号码'), ('彩钢扣板底加普通平面贴字，扣板竖向接缝与字面一致透视', '常见蓝底白字，服务行用白底深蓝字'), ('普通铝塑板拼接贴膜字，包边与板缝可见，不做光滑效果图', '白底红色主字，深色服务小字'), ('旧招牌框架内新换喷绘面，框架与画面新旧程度略不同', '绿色底白字，电话用浅黄信息区'), ('普通金属底板配简易PVC实体字，字的厚度和固定阴影克制', '浅灰底深蓝字，电话区红字'), ('薄型普通灯箱门头，铝边框、接缝和亚克力面板真实，白天不强行发光', '乳白底红蓝文字，信息条分色但不做渐变')]

SIGN_LAYOUTS = ['完整店名横排占主要宽度，服务小字紧凑排在下方一行，电话在右下联系区', '完整店名在左侧较大，右侧独立电话联系块，服务词按自然间距排在底部色带', '标题分两段紧凑排列，服务词分上下两小行，电话号码单独横排在板面下沿', '主标题偏左不追求几何居中，服务词在右侧两列，电话跨板面下部排列', '上方完整店名粗字，下方分色信息条包含服务词和电话，字距紧凑，像当地广告店排版']

SIGN_WEAR = ['正常使用数年，边沿局部积灰，主文字保持清晰', '近期更换板面，安装框架略旧，不能把整个门店翻新成展厅', '日晒侧轻微褪色，雨痕只在边沿和紧固件下方出现，不统一做旧']

