"""Category-bounded, reproducible signboard variation; contact data is external."""

from tools import variable_catalog
import random

SHOP_PREFIXES = ['顺达', '宏顺', '鑫诚', '诚运', '安顺', '永顺', '鸿达', '顺通',
                 '路顺', '众诚', '万通', '兴达', '恒达', '顺发', '诚信', '平安']
OWNER_PREFIXES = ['老周', '老张', '老陈', '老李', '小刘', '小杨', '阿强', '阿辉']
SHOP_SUFFIXES = ['汽车救援服务部', '道路救援服务站', '汽修救援', '汽车维修救援',
                 '拖车救援服务部', '汽车服务部']
OWNER_SUFFIXES = ['汽修救援', '汽车维修救援', '拖车救援', '汽车救援']
SERVICES = ['搭电救援', '拖车服务', '补胎换胎', '送油救援', '困境救援',
            '地库救援', '车辆救援', '高速救援', '城市路救援']
FABRICATIONS = [
    ('喷绘布绷在普通方管框架上，四周收边和少量紧固点真实', '普通红底白字，黄色仅强调电话号码'),
    ('彩钢扣板底加普通平面贴字，扣板竖向接缝与字面一致透视', '常见蓝底白字，服务行用白底深蓝字'),
    ('普通铝塑板拼接贴膜字，包边与板缝可见，不做光滑效果图', '白底红色主字，深色服务小字'),
    ('旧招牌框架内新换喷绘面，框架与画面新旧程度略不同', '绿色底白字，电话用浅黄信息区'),
    ('普通金属底板配简易PVC实体字，字的厚度和固定阴影克制', '浅灰底深蓝字，电话区红字'),
    ('薄型普通灯箱门头，铝边框、接缝和亚克力面板真实，白天不强行发光', '乳白底红蓝文字，信息条分色但不做渐变')
]
LAYOUTS = [
    '完整店名横排占主要宽度，服务小字紧凑排在下方一行，电话在右下联系区',
    '完整店名在左侧较大，右侧独立电话联系块，服务词按自然间距排在底部色带',
    '标题分两段紧凑排列，服务词分上下两小行，电话号码单独横排在板面下沿',
    '主标题偏左不追求几何居中，服务词在右侧两列，电话跨板面下部排列',
    '上方完整店名粗字，下方分色信息条包含服务词和电话，字距紧凑，像当地广告店排版'
]
CONDITIONS = ['正常使用数年，边沿局部积灰，主文字保持清晰',
              '近期更换板面，安装框架略旧，不能把整个门店翻新成展厅',
              '日晒侧轻微褪色，雨痕只在边沿和紧固件下方出现，不统一做旧']


@variable_catalog.managed('road_rescue',finish_result=False)
def choose_signboard(group_index, variant, *, narrow=False):
    rng = random.Random(f'road_signboard_v2:{group_index}:{variant}')
    naming_style = rng.choice(['trade_name', 'owner_name'])
    forced=variable_catalog.FORCE.get()
    if any(variable_catalog.uid(k) in forced for k in ('OWNER_PREFIXES','OWNER_SUFFIXES')): naming_style='owner_name'
    elif any(variable_catalog.uid(k) in forced for k in ('SHOP_PREFIXES','SHOP_SUFFIXES')): naming_style='trade_name'
    if naming_style == 'owner_name':
        prefix, suffix = rng.choice(OWNER_PREFIXES), rng.choice(OWNER_SUFFIXES)
    else:
        prefix, suffix = rng.choice(SHOP_PREFIXES), rng.choice(SHOP_SUFFIXES)
    title = prefix + suffix
    services = variable_catalog.sample_unique(rng, SERVICES, rng.randint(3, 4 if narrow else 6))
    separator = rng.choice([' · ', '  ', '｜'])
    material, palette = rng.choice(FABRICATIONS)
    return {'version': 'road_signboard_v2', 'title': title, 'store_name': title,
            'naming_style': naming_style, 'name_prefix': prefix, 'name_suffix': suffix,
            'services': services,
            'business_line': separator.join(services), 'material': material,
            'palette': palette, 'layout': rng.choice(LAYOUTS),
            'condition': rng.choice(CONDITIONS)}
