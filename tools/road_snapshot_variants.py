"""Bounded amateur capture flaws; independent of device and color treatment."""
import random
from tools import variable_catalog

FLAWS = [{'id': 'none', 'description': '本图对焦正常，无额外运动模糊或手抖重影，保持普通随手拍清晰度', 'weight': 25}, {'id': 'motion', 'description': '{motion_target}在真实动作方向上有少量短距离动态模糊，静止门框与招牌保持稳定；不为模糊额外添加人物车辆，不做速度线或长曝光光轨', 'weight': 25}, {'id': 'handshake', 'description': '按快门时轻微手抖，整幅静态边缘存在一致方向的极短拖影，细节略软但字形不重复分叉；不把招牌单独锐化成粘贴图层', 'weight': 15}, {'id': 'focus', 'description': '自动对焦略有偏差，焦点在门口附近，远近细节轻微变软；不做专业人像大光圈虚化，不用涂抹式局部模糊，招牌数字仍可直接辨读', 'weight': 20}, {'id': 'awkward_crop', 'description': '取景略仓促，随机截断一小段邻铺、非关键车身或屋檐，主体稍偏心；完整店名、电话和关键作业动作不能裁掉，不增加大块空地', 'weight': 15}]
ROLL_ANGLES = [-3,-2,-1,1,2,3]


@variable_catalog.managed("road_rescue",finish_result=False)
def choose_snapshot(group_index, variant, environment, postprocess):
    rng = random.Random(f'road_snapshot_v1:{group_index}:{variant}')
    # At most one optical flaw, plus an optional modest camera roll.
    selected_flaw = rng.choices(FLAWS,weights=[f['weight'] for f in FLAWS])[0]
    optical = selected_flaw['id']
    selected = environment['incidental']['selected']
    motion_targets = {
        'cyclist': '本组已选的骑车人及车轮',
        'traffic': '本组已选的经过车辆',
        'pedestrian': '本组已选的行人摆动手脚',
    }
    moving = [motion_targets[k] for k in selected if k in motion_targets]
    motion_target = rng.choice(moving) if moving else '正在作业的师傅手腕与工具末端'
    roll = rng.choice(ROLL_ANGLES) if rng.random() < .45 else 0
    low_strength = postprocess['id'] in {'shared_phone_photo', 'restrained_film', 'muted_soft', 'soft_bright'}
    return {'version': 'road_snapshot_v1', 'mode': 'generation_prompt_only',
            'optical_flaw': optical, 'description': selected_flaw['description'].replace('{motion_target}', motion_target),
            'motion_target': motion_target if optical == 'motion' else None,
            'roll_degrees': roll,
            'strength': '很轻，避免与已有柔化、颗粒或压缩叠加损失' if low_strength else '轻微但可感知',
            'roll_description': ('相机横滚保持自然近水平，不追加歪斜' if not roll else
                f'手机握持不正，整幅照片随相机向{"右" if roll > 0 else "左"}微旋转约{abs(roll)}度，门楣和地平线一致倾斜，不自动拉正；不是改变门店透视或把建筑局部扭歪，不留旋转黑边')}


def snapshot_instruction(snapshot):
    return (f"随手拍与拍摄失误变量：{snapshot['description']}；强度：{snapshot['strength']}。"
            f"握持角度：{snapshot['roll_description']}。"
            "这一节指定轻微成像缺陷和整幅横滚角度，优先于通用完全清晰、正常对焦或水平取景措辞；不改变所选机位、环境、事件或后期色调。"
            "只采用所选失误，不把手抖、失焦、重颗粒和压缩同时叠满；主体仍可辨识，完整店名不得缺字，电话始终来自输入且每位可读。"
            "不要把模糊只涂在特定物体上做假特效，不磨皮、不改变肢体数量或车辆结构。"
            "以上只作用于原始场景照片，后续中央电话条与底部文字保持水平清楚。")
