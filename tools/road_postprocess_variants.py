"""Prompt-level finished-photo treatments, not a local image filter renderer."""

from tools import variable_catalog
import random

POSTPROCESS_PRESETS = [
    dict(id='neutral_direct', name='自然直出', color='中性白平衡、正常饱和度，保留建筑和招牌原色', tone='中等对比度，保留真实室内外明暗差，不全面提亮暗部', texture='适度手机锐度，画面干净但不磨皮、不抹掉材料纹理'),
    dict(id='warm_daily', name='暖调生活照', color='可感知的轻暖米黄色调，红黄略暖，白墙只是暖白，肤色不橙', tone='中低对比度，亮部柔和过渡，阴影仍有层次', texture='保留普通手机细节，像相册里适量调暖后的日常照片，不加光晕'),
    dict(id='cool_documentary', name='冷调纪实', color='整体轻冷蓝灰调，绿蓝稍收敛，白墙微冷而肤色正常', tone='中等偏高对比度，黑位略深但店内工具仍可辨', texture='清楚克制的手机细节，不添加青橙分离或金属科幻色'),
    dict(id='muted_soft', name='低饱和柔和', color='明显但适量降低全局饱和度，招牌仍保留红蓝绿等原色，不变黑白', tone='轻压高光、略抬黑位，柔和低对比度，不能泛灰到像蒙雾', texture='锐化较轻，保留墙面和工具纹理，文字边缘仍清楚'),
    dict(id='clear_vivid', name='手机鲜明', color='适量增加鲜明度，让招牌和工装颜色更鲜活，但不改色相、不过饱和', tone='中高对比度，亮部通透，暗部不死黑，不做HDR光边', texture='适量手机锐化，材质清楚但不过度微对比，像普通相册鲜明滤镜'),
    dict(id='soft_bright', name='明亮柔光', color='自然中性略暖，色彩保持正常，不加粉色美颜色', tone='整体曝光感小幅提高，阴影适量提亮、强高光压回；店内仍明显暗于室外，不能把夜景变白天', texture='降低生硬锐化，保留实拍纹理，不虚化、不磨皮、不使用发光柔焦'),
    dict(id='restrained_film', name='轻胶片色感', color='暖高光与中性略冷阴影的克制色彩变化，绿略偏橄榄但店牌品牌色不改', tone='柔和高光曲线、轻微褪黑感，对比适中，不做复古年代场景', texture='仅极轻自然细颗粒感，正常观看不可盖住数字，不加划痕、漏光、日期戳或胶片边框'),
    dict(id='shared_phone_photo', name='转发照片质感', color='中性色彩略收敛，像普通手机照片经过一次社交平台保存', tone='常规对比度，高光保留普通手机有限动态范围，不拉成灰片', texture='极轻JPEG压缩与降噪痕迹，细节稍软；不得出现明显方块、重影、模糊号码或二次截图边框')
]


@variable_catalog.managed('road_rescue',finish_result=False)
def choose_postprocess(group_index, variant=0, first_group_index=1089):
    order = list(range(len(POSTPROCESS_PRESETS)))
    random.Random(f'road_postprocess_v1:{variant}').shuffle(order)
    choice = dict(POSTPROCESS_PRESETS[order[(group_index-first_group_index) % len(order)]])
    choice['version'] = 'road_postprocess_v1'
    choice['mode'] = 'generation_prompt_only'
    choice['strength'] = '适中可感知，不夸张'
    return choice


def postprocess_instruction(choice):
    return (f"本张最终照片后期变量：{choice['name']}，强度为{choice['strength']}。"
            f"色彩：{choice['color']}；明暗：{choice['tone']}；质感：{choice['texture']}。"
            "设备描述规定基础成像，本节规定最终色调，在冷暖、饱和度和对比度方面以本节为准。"
            "只执行本张这一套处理，不叠加其他滤镜；保持场景时段、真实光源、建筑结构与人物动作不变。"
            "实体招牌中文字、数字和完整电话必须清楚准确，不漂白字、不压黑字、不改变内容。"
            "不加滤镜名称、水印、边框或参数，不做电影青橙、重度褪色、强HDR、暗角或商业海报色。"
            "这是生成最终照片观感的要求；中央电话和底部服务字仍由后续本地程序清晰叠加，不属于滤镜处理范围。")
