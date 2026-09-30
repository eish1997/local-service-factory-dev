"""Category-compatible building and surroundings bundles, separate from camera rotation."""

from tools import variable_catalog
import random

INCIDENTAL_TYPES = [
    {'id':'tree','description':'环境边缘的普通树木'},
    {'id':'cyclist','description':'在合法通行区域经过的骑车人'},
    {'id':'traffic','description':'低频经过车辆'},
    {'id':'pedestrian','description':'中远景路过行人'},
]

ENVIRONMENTS = [
    dict(id='community_ground_floor', name='社区底商', bays=1, setting='普通住宅小区外围的汽车服务底商', facade='楼上生活阳台、浅色涂料墙，单开间卷帘门，侧边普通玻璃小门，局部维护痕迹', ground='窄人行道、低路缘和普通沥青辅路，作业只在店前合法铺装空间', neighbours='一侧生活服务邻铺，另一侧居民楼入口，邻铺文字不必可读', activity='背景可有一名步行居民，没有必须经过的骑车人', edge='楼道侧墙', camera_area='street', business='社区汽车维护兼道路救援的小店'),
    dict(id='county_low_row', name='县城低层沿街铺', bays=1, setting='县城辅街一排低层汽车服务铺', facade='一至两层自建商铺，抹灰墙与局部裸砖相接，铁皮短雨棚，双扇折叠铁门，不套用居民楼立面', ground='水泥硬化门前接沥青辅街，地面有自然修补接缝，不满地油污', neighbours='五金铺侧墙和一扇关闭的邻铺门，建筑宽窄高低不齐', activity='背景安静，无近景行人或骑车人', edge='邻铺短雨棚边', camera_area='street', business='县城汽车快修兼拖车救援服务铺'),
    dict(id='logistics_steel_shed', name='物流园钢棚', bays=2, setting='物流园内部普通汽车救援服务铺', facade='独立单层钢结构棚房，灰蓝压型钢板墙，大跨度方钢梁和高开间推拉门，招牌固定于棚檐，无楼上住宅窗和空调排阵', ground='园区混凝土硬地，有伸缩缝与少量停车线，不添加城市人行道路缘', neighbours='仓库侧墙和远处装卸通道，不出现紧贴生活零售邻铺', activity='远处可有小型搬运车，近景无人横穿', edge='棚柱侧缘', camera_area='yard', business='物流园拖车与应急救援设备维护站'),
    dict(id='suburban_courtyard', name='城郊院落式门店', bays=2, setting='城郊辅路旁可进车的小院汽车服务铺', facade='院内低矮砖混平房，普通双开铁门打开，实用瓦楞雨棚，主招牌固定在实际车间门楣而非院门或围墙', ground='院内水泥作业地面，院边少量碎石，车辆和设备均在平整硬地，不出现城市停车格', neighbours='低围墙、侧边小储物间，远处少量普通民房', activity='安静工作院落，不添加过路行人或电动车', edge='打开的院门边缘，仅一小角', camera_area='yard', business='有院内作业空间的汽车维修与救援服务铺'),
    dict(id='industrial_brick_workshop', name='旧工业厂房服务铺', bays=2, setting='小工业园边缘的汽车服务车间', facade='普通红砖厂房外墙，较高侧窗，灰色钢门敞开，实用平屋顶，两开间跨度不同，不加住宅阳台', ground='厂区混凝土路面和排水沟盖，局部轮胎使用印记', neighbours='相邻设备维修车间的无字金属门与普通厂区围栏', activity='可有一名远处工人背影，没有城市车流', edge='砖柱侧边', camera_area='yard', business='工业园车辆应急救援与维修车间'),
    dict(id='town_roadside_bungalow', name='乡镇路边平房', bays=1, setting='乡镇连接路旁普通汽车救援店', facade='单层水泥抹灰平房，低坡瓦顶，实用铁门和一扇侧窗，招牌安装在车间门口檐下，不做破败废屋', ground='平整水泥操作区接窄路肩，边界少量自然杂草，作业区无泥坑', neighbours='一侧低矮民房，另一侧空隙能看见普通树篱，非荒野场景', activity='背景无行人或骑车人，远处道路只作环境', edge='一侧屋檐小角', camera_area='street', business='乡镇汽车修理兼道路救援服务店'),
    dict(id='commercial_parking_edge', name='商用停车场边服务铺', bays=1, setting='普通露天商用停车场边的小型汽车救援铺', facade='停车场边独立低矮混凝土服务房，普通铝合金门与侧面工作通道，实用浅色外墙，无居民楼上层', ground='铺装场地和少量车位线，工作位与行车通道分开，不堆满车辆', neighbours='背景低围栏与零散停放的普通车辆，没有连续商业街门头', activity='现场安静，车停着而非形成前景过路车流', edge='服务房侧墙', camera_area='yard', business='停车场车辆应急维护与道路救援服务铺')
]


@variable_catalog.managed('road_rescue',finish_result=False)
def choose_environment(group_index, variant=0, first_group_index=1089):
    order = list(range(len(ENVIRONMENTS)))
    random.Random(f'road_environment_v1:{variant}').shuffle(order)
    environment = dict(ENVIRONMENTS[order[(group_index-first_group_index) % len(order)]])
    incidental = choose_incidental(environment, group_index, variant)
    environment['incidental'] = incidental
    environment['activity'] = incidental['description']
    return environment


def choose_incidental(environment, group_index, variant=0):
    """Sample zero to two context-safe life elements, never a mandatory trio."""
    rng = random.Random(f'road_incidental_v1:{group_index}:{variant}')
    env_id = environment['id']
    if environment['camera_area'] == 'street':
        placement = '公共道路背景，不能闯入维修操作区'
        tree = '路边树木只在一侧边缘自然露出，树种与当地普通街景相容'
        cyclist = '一名骑自行车或电动车的人从道路中远景正常经过'
        traffic = '一至两辆普通车辆在远处道路经过，低频车流，不堆成车阵'
    elif env_id == 'suburban_courtyard':
        placement = '仅打开院门外可见的道路，院内作业区不穿行'
        tree = '院墙边有一棵普通树，枝叶只占画面边缘小部分'
        cyclist = '院门外道路远处一名骑车人经过，门外道路不可见时不强塞人物'
        traffic = '院门外可见道路远处一辆普通车经过，不进入院内作业区'
    else:
        placement = '园区或停车场的独立通行车道，与维修操作区分开'
        tree = '围栏或场地边界有少量绿化树，不能替代指定建筑背景'
        cyclist = '一名通勤骑车人沿场地通行车道缓慢经过，不穿过工位'
        traffic = '一辆符合园区或停车场环境的普通车辆在独立车道低速通过，无城市密集车流'
    pool = {'tree': tree, 'cyclist': cyclist, 'traffic': traffic,
            'pedestrian': '一名普通行人在允许通行的边缘中远景自然经过，不围观、不摆拍'}
    defaults = {'tree':'环境边缘的普通树木','cyclist':'在合法通行区域经过的骑车人','traffic':'低频经过车辆','pedestrian':'中远景路过行人'}
    pool = {item['id']:(pool.get(item['id'],item['description']) if item['description']==defaults.get(item['id']) else item['description']+'；'+placement) for item in INCIDENTAL_TYPES}
    # None is a real outcome; one element is most common; never require all three.
    count = rng.choices([0, 1, 2], weights=[3, 5, 2])[0]
    selected = rng.sample(list(pool), min(count,len(pool)))
    description = ('本图不添加额外树木、骑车人、路过行人或动态车流，保留环境本身已有静物'
                   if not selected else '随机生活元素：' + '；'.join(pool[k] for k in selected))
    description += '；位置约束：' + placement + '；不得遮挡完整店名、电话和关键操作，生活元素只作次要背景，未选元素不额外添加'
    return {'version': 'road_incidental_v1', 'selected': selected,
            'placement': placement, 'description': description}


def adapt_composition(composition, environment):
    result = dict(composition)
    if environment['camera_area'] == 'yard':
        result['camera'] = result['camera'].replace('街对面', '场地对侧').replace('从对面正常人行台阶上', '从场地入口低台阶上')
        result['foreground'] = result['foreground'].replace('路缘', '场地边界').replace('路面', '硬化地面')
    return result
