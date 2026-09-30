"""Future-only truck scenes: coherent business events, not independent prop bags.

The 274 epoch is deliberate. Historical source rows and prompts must retain their
original interpretation. This module has no filesystem/network side effects.
"""
from __future__ import annotations

from tools import variable_catalog

import hashlib
import json


EPOCH_GROUP = 274
SCENE_VERSION = "truck_realism_diversity_v3_g0274"
REFERENCE_LEARNING_EPOCH_GROUP = 374
REFERENCE_LEARNING_VERSION = "truck_reference_learning_v1_g0374"
ROLES = ("货车没油救援", "货车爆胎救援", "货车换轮胎", "货车发动机故障", "卡车搭电", "货车刹车故障")

# Each event fixes the problem, vehicle, work phase, and compatible equipment.
# Camera/ordinary light may vary; the mechanics are never randomly recombined.
EVENTS = {
    "货车没油救援": (
        ("fuel_neck", "燃油动力中型厢式货车", "combustion", "unspecified", "一名戴手套的工作人员站在侧置油箱旁，把防静电输油软管端口稳妥放入已打开的加油口，密闭合规燃油容器放在吸油垫上；只记录加注前接管这一刻", "与车辆燃料相匹配的合规封闭容器、防静电输油软管、吸油垫、手套和警示锥"),
        ("fuel_transfer", "柴油动力重型栏板载货车", "diesel", "air", "工作人员半蹲在车侧油箱旁，双手分别稳定防静电软管与转移设备进行少量应急柴油补充；车辆熄火停稳，轮挡到位，无洒漏、无烟火", "柴油合规封闭容器、专用转移设备、防静电软管、吸油垫、轮挡和防护手套"),
        ("fuel_finish", "燃油动力轻型栏板货车", "combustion", "hydraulic", "工作人员完成少量应急补油后正旋紧油箱盖，已停止输油的软管封好放在接液垫上；画面只表现补油结束复查，不混入维修发动机或更换油箱", "与燃料匹配的封闭容器、封口输油软管、接液垫、防护手套和警示锥"),
        ("fuel_setup", "柴油动力重型牵引车，未连接挂车", "diesel", "air", "工作人员在停稳牵引车侧面核对油箱口与柴油容器标识的位置，容器密闭且软管尚未接入，另一只手扶住转移设备；表现应急送油准备，不表现泄漏事故", "合规柴油容器、封闭转移设备、防静电软管、吸油垫、轮挡和警示锥"),
    ),
    "货车爆胎救援": (
        ("blowout_sidewall", "重型载货卡车，外侧后胎侧壁爆裂且完全停稳", "combustion", "air", "工作人员在轮胎侧方蹲下，用检修灯照亮裂口并观察轮辋，手不伸入悬空车底；只诊断严重破损，不塞胶条、不安装新胎", "检修灯、重型轮挡、警示锥和安全手套"),
        ("blowout_dual", "重型半挂货车，挂车双胎外胎撕裂", "unspecified", "air", "工作人员站在挂车外侧，侧身弯腰用小型检查镜查看双胎间隙有无残留物，车轮着地且已固定；不把完整内侧轮胎画成拆卸悬浮车轮", "检查镜、工作灯、重型轮挡、警示锥和手套"),
        ("blowout_rim", "中型冷藏货车，后轮胎面严重脱落", "unspecified", "unspecified", "师傅在车辆侧面观察残存胎体与轮辋边缘，单手持灯，另一手指向受损部位但不接触锋利断面；现场没有新轮胎展示或补胎动作", "手持检修灯、防割手套、轮挡和警示锥"),
        ("blowout_assess", "重型自卸货车，空载且后外轮爆裂", "combustion", "air", "救援人员在已隔离的作业区记录后轮损坏情况，站立俯身观察胎体裂口，手中纸质记录夹不出现可读文字；车辆不顶升，只有检查判断这一阶段", "检修灯、记录夹、重型轮挡和警示锥"),
    ),
    "货车换轮胎": (
        ("wheel_loosen", "中型栏板货车，车旁有尺寸匹配的完整备用车轮", "unspecified", "unspecified", "车辆全部车轮仍着地且驻车轮挡已固定，工作人员把轮毂套筒套牢在螺母上松开一颗螺母；千斤顶尚未升起，不同时表现拆轮或装轮", "货车规格长柄套筒扳手、轮挡、匹配备用车轮和待用液压千斤顶"),
        ("wheel_align", "重型载货卡车，待安装的后轮总成由搬运架承托", "combustion", "air", "两名工作人员在车侧配合推动轮胎搬运架，将完整车轮对准轮毂螺柱；正确顶升点已有重型千斤顶和可靠支撑，无人钻入车底", "重型千斤顶、承载匹配的支撑架、轮挡、车轮搬运架和匹配车轮总成"),
        ("wheel_seat", "轻型厢式货车，适配备用车轮已经贴合轮毂", "unspecified", "hydraulic", "工作人员在可靠支撑车辆的外侧半蹲，双手用套筒初步紧固已对位车轮的螺母；车轮没有悬浮且不把胎体徒手从轮辋拆下", "轻卡额定规格液压千斤顶、支撑架、轮挡和车轮套筒工具"),
        ("wheel_torque", "重型牵引车，刚更换的外侧车轮已着地", "combustion", "air", "工作人员侧身双手握扭力扳手，套筒明确接触一颗轮毂螺母，记录更换完成后的力矩复核；旧轮放在后方安全位置，不再表现顶升拆卸", "货车规格扭力扳手、轮挡、适配套筒和置于安全位置的旧轮"),
    ),
    "货车发动机故障": (
        ("engine_sensor", "重型平头载货卡车，驾驶室已安全翻起并锁止", "combustion", "air", "维修人员站在发动机侧面，用万用表探针检查可接近的传感器线束端子，手部有明确接触点；只表现电路诊断，不拆整台发动机", "万用表、绝缘探针、检修灯和绝缘手套"),
        ("engine_codes", "中型平头厢式货车，驾驶室翻转并可靠锁止", "combustion", "unspecified", "师傅在发动机外侧的工具车旁读取商用车诊断平板，诊断线从设备自然接到车辆诊断接口，屏幕无可读品牌和代码；另一手扶住设备", "商用车诊断平板、诊断线、普通工具车和工作灯"),
        ("engine_line", "柴油重型牵引车，翻起驾驶室露出柴油发动机侧面", "diesel", "air", "工作人员用照明灯查看已熄火发动机的低压燃油管路外观与接头，手不接触高压喷油管，不拆卸带压部件；只做静态漏损诊断", "检修灯、防护手套、诊断平板和吸油垫"),
        ("engine_terminal", "燃油轻型平头栏板货车，驾驶室按车型结构翻起并锁止", "combustion", "hydraulic", "维修人员站在车侧，用万用表检查启动电路的可接近低压连接点，另一手持绝缘探针；车辆已驻车断开启动操作，不同时加油搭电", "万用表、绝缘探针、工作灯、轮挡和手套"),
    ),
    "卡车搭电": (
        ("jump_voltage", "重型载货卡车，侧置低压蓄电池箱打开", "combustion", "air", "工作人员俯身用万用表核对低压蓄电池电压与极性；专业启动电源关闭放在地面，粗线夹尚未连接，呈现辅助启动前确认阶段", "与额定电压匹配的商用车启动电源、粗规格跨接线、万用表、绝缘手套和轮挡"),
        ("jump_positive", "轻型栏板货车，侧置蓄电池端子可见", "combustion", "hydraulic", "戴绝缘手套的工作人员依照该车说明把粗跨接线正极夹稳定接在指定正极端子；启动设备保持关闭，另一线夹有绝缘防护且不接触车身，不出现火花", "匹配车辆额定电压的低压启动设备、粗规格跨接线、绝缘夹、绝缘手套和护目镜"),
        ("jump_ground", "中型厢式货车，低压蓄电池箱打开且驻车完成", "combustion", "unspecified", "工作人员从车辆外侧核对已接好的正极线与车辆指定接地点，最后一个夹子清楚咬合指定接地点；设备与线材按额定规格匹配，不固定宣称24V", "额定电压匹配的辅助启动设备、粗规格跨接线、绝缘护具和轮挡"),
        ("jump_check", "重型牵引车，车侧低压蓄电池箱及连接点清楚", "combustion", "air", "工作人员站在连接完成的蓄电池箱旁查看电压表，双手不移动带电线夹；粗线从专业低压辅助电源自然接到指定端子及接地点，画面没有高压充电枪", "与额定电压匹配的重型低压启动设备、粗规格跨接线、电压表、绝缘手套和轮挡"),
    ),
    "货车刹车故障": (
        ("brake_fluid", "轻型厢式货车，明确为液压制动系统", "unspecified", "hydraulic", "工作人员在可接近的制动液储液壶旁用灯检查液位与周边软管外观，车辆已驻车且轮挡到位；不出现储气筒或气压表，不将检查画成故障车继续行驶", "工作灯、制动液检测工具、防护手套和轮挡"),
        ("brake_airline", "重型牵引车，明确为空气制动系统", "combustion", "air", "工作人员站在车侧可接近的气路接头处涂少量检漏液并观察，制动管路与接头真实连通，车轮固定；只检查外侧接头，不钻车底、不拆卸带压管线", "检漏液、检修灯、制动诊断设备、手套和重型轮挡"),
        ("brake_wheel", "中型载货卡车，明确为液压制动系统", "unspecified", "hydraulic", "工作人员在车轮外侧用检修灯检查轮端制动软管及可见连接处，车轮不拆卸，车辆停稳；只检查渗漏和磨损，不混用空气干燥器", "工作灯、检查镜、液压制动诊断工具、手套和轮挡"),
        ("brake_pressure", "重型半挂货车，明确为空气制动系统", "combustion", "air", "技术人员在驾驶室打开的车门外读取连接好的商用车诊断设备，检查制动压力与报警状态；画面只表现静态诊断，轮挡和驻车状态可辨，无道路行驶", "商用车制动诊断设备、诊断连接线、轮挡和警示锥"),
    ),
}

DETAIL_CAMERAS = (
    ("left_mid", "从故障部位左前侧手机眼平中景拍摄，故障车占左侧，动作位于右侧中景"),
    ("right_mid", "从故障部位右前侧手机中景斜拍，车辆占右侧，人物和设备在左侧，不是左前机位镜头"),
    ("side_close", "从安全作业区侧面腰部高度中近景记录，重点是手、工具与当前故障部位，不强求完整车头"),
    ("over_shoulder", "从工作人员肩侧稍后方中近景拍摄，肩背只占边缘，操作接触点和设备清楚，不遮挡关键动作"),
    ("rear_observer", "从工作区斜后侧稍远的手机视角记录，车辆侧面形成纵深，保留必要警戒区而非整齐展示工具"),
    ("slight_high", "从身高范围内略高于操作点的手机机位斜拍，形成自然俯视，绝非航拍，手部和车辆接触点可见"),
)
LOCATIONS = (
    ("logistics_bay", "物流园普通货车停车区内独立划出的硬化维修位，背景为仓库侧墙和少量货架"),
    ("industrial_yard", "工业园维修院内的平整水泥工位，侧后方为旧砖墙和普通金属门"),
    ("freight_market", "城郊货运市场外围封闭作业位，背景仅露普通沿街库房与围栏"),
    ("road_service", "国道货运服务点远离行车道的硬化安全作业区，背景可见低矮房屋与路肩"),
    ("warehouse_side", "普通仓储院落的侧边检修区，地面平整坚实，背景有装卸雨棚但作业不占用通道"),
)
LIGHTS = (
    ("overcast_dry", "干燥阴天的普通散射光，地面无积水"),
    ("morning_side", "上午普通侧光，车辆投下自然阴影，地面干燥"),
    ("afternoon_open", "下午白昼自然光，亮度轻微不均，禁止电影调色"),
    ("canopy_shade", "遮雨棚边缘的明暗过渡，环境仍是白昼，地面干燥"),
    ("winter_soft", "初冬普通柔和日光，无雪、无雾、无湿地反光"),
    ("late_day", "天色尚亮的傍晚自然光加一盏实用工作灯，不做蓝橙电影效果"),
    ("cloud_break", "薄云遮日的普通自然光，局部曝光略有差异，颜色克制"),
)
WORKWEAR = (
    "穿有自然褶皱的灰褐工作服", "穿深绿色普通工装", "穿灰色上衣和深色工作裤",
    "穿暗红棕色耐磨上衣", "穿深灰工装配局部反光条", "穿洗旧的卡其色工作上衣",
    "穿藏蓝工作裤和浅灰上衣", "穿橄榄色工装配防护手套",
)

# The architecture and camera are paired to preserve usable signboards. Other
# axes rotate independently across cycles; no single location owns one camera.
COVER_FRAMES = (
    ("left_two_bay", "两开间普通卷帘门门店，维修区和工具区分开", "从左前方斜拍中远景，保留右侧街道纵深"),
    ("right_corner", "转角地面门店，主招牌仅装在面向道路的主立面", "从右侧转角斜拍，主招牌仍可辨，侧墙形成深度"),
    ("front_offset", "一层单开间高门洞维修铺，门前有安全硬化工位", "街对面普通眼平偏轴拍摄，门店偏左，不做正面对称"),
    ("entrance_near", "深门洞货车维修铺，门口退让出可通行区域", "站在入口外侧近距离斜拍，门框边缘轻度裁切但主招牌完整"),
    ("low_canopy", "普通钢雨棚下的两开间维修店，雨棚不遮挡主招牌", "略低于眼平的手机机位轻仰拍，保留雨棚厚度和二层墙面"),
    ("high_steps", "沿街维修店地坪略低于外侧人行通道，门前坡道真实", "从通道正常站立高度略俯拍，非航拍，保留招牌和工位"),
    ("passing_left", "普通长条建筑中的维修门店，邻店边缘可见", "从左侧路过的随手手机斜拍，画面轻微偏斜，不把门头居中"),
    ("passing_right", "独立单层维修铺，侧边有一块正常使用的硬化空地", "从右侧经过的手机中远景，侧墙与作业区构成纵深"),
    ("yard_observer", "维修院入口内侧的地面门店，主招牌固定于维修门上方", "从院落边缘向门店眼平斜拍，前景只有少量围栏边缘不遮文字"),
    ("tele_mid", "普通两层临街建筑底层维修铺，外墙有正常管线", "稍远手机两倍焦段中景，保留主招牌、一层工位和部分二层墙面"),
    ("workbay_side", "宽门洞单层维修店，工位延伸到门内阴影处", "从室外工位侧方看向主招牌和门内，突出室内外前后层次"),
    ("setback_front", "建筑首层退台下的普通维修门店，门前场地与道路有距离", "从场地外沿眼平偏右中景记录，招牌偏上、人物自然偏侧"),
)
COVER_EVENTS = (
    ("cover_tire_check", "一辆中型载货车停在门前侧边；一名师傅蹲在后轮外侧用检修灯检查轮胎，轮挡到位，无拆轮动作", "工位开放营业，工具只放必要两三件，通道空出"),
    ("cover_engine", "重型平头货车在室外可靠停稳且驾驶室翻起锁止，师傅站在车侧读取诊断平板，不吊装发动机", "门洞打开，维修动作在室外，店内只露普通工具柜"),
    ("cover_jump", "轻型栏板货车停在店侧，师傅核对侧置蓄电池电压，关闭的匹配启动设备放在车边，粗线尚未连接", "维修门开启，店内有人影自然整理工具但不摆拍"),
    ("cover_wheel", "货车在坚实室外工位上由额定重型支撑承托，两名师傅用搬运架将匹配车轮对准轮毂，人员不在车底", "营业中的维修铺，门前只保留本次换轮所需设备，通道不堆轮胎"),
    ("cover_fuel_prep", "一辆已熄火的燃油中型货车停稳，师傅在侧面检查密闭燃油容器与封好软管，表现应急补油前准备，无洒漏", "门洞半升但可正常进出，所有燃油准备在室外通风工位，不是店内加油"),
    ("cover_brake", "空气制动重型载货车停在外侧工位，师傅站在车侧可接近气路接头处用检漏液检查，轮挡与警戒到位", "卷帘门打开，维修现场正常使用，有一辆工具车自然靠墙"),
    ("cover_torque", "中型货车新换车轮已落地，师傅在车侧用套筒接触螺母进行扭矩复核，旧轮放在后方安全区域", "正常营业工位，门内有少量工作痕迹，不把工具排成整齐展示列"),
    ("cover_tools", "师傅在侧边工具车上把扭力扳手放回抽屉，身后停稳的货车只露部分车侧，表示一次维修刚结束而非站立合影", "临近收工但仍营业，门洞开启，另一侧工具柜已收拢，地面无统一湿路反光"),
)

# These are choices, not a new universal foreground/workshop/signboard stack.
# Frame indexes refer to the frozen v3 pairs above; never resize/reorder them.
LEARNED_COMPOSITIONS = (
    ("storefront_overview", (2, 9, 11), "以普通门店整体与入口关系为主，维修只占一侧，允许少量空地，不把工人推到统一前景"),
    ("side_work", (10, 1, 5), "侧面作业是视觉重点，门店招牌在上方可读，车侧可局部裁切，不另摆一个面向镜头的人"),
    ("entrance_close", (3,), "入口外近景记录门框、工具取用区和当前作业关系，招牌完整可读，不要求整辆货车和整排工位入画"),
    ("street_snapshot", (6, 7), "像从街侧经过时随手拍到营业中的维修铺，邻店或侧墙只是自然边缘，人物不必在画面中央"),
    ("natural_depth", (8, 0, 4), "本组可借鉴门头、工位与侧前方作业的自然前后层次，但不要强行排成上中下三块，也不把这种层次复制到其他构图类别"),
)

# Only the selected business event supplies its real-world detail. A fuel scene
# must not acquire spare wheels merely to make a shop look more "authentic".
COVER_WORK_DETAILS = {
    "cover_tire_check": "检修灯正在照向后轮检查部位，备用手套随手放在靠墙小凳上；轮挡在车轮处，通行位置不摆展示用轮胎",
    "cover_engine": "诊断平板由师傅实际握持读取，连接线沿车侧接到诊断接口；普通工具车停在伸手可取的侧后方，不在门口整齐列成道具",
    "cover_jump": "万用表探针接触低压蓄电池检查点，关闭的启动设备放在车旁干燥平整处；未接线夹有绝缘保护，不把线缆绕成装饰性圆环",
    "cover_wheel": "待装车轮由搬运架承托并靠近轮毂，支撑架位于正确受力位置；当前要用的套筒靠作业侧收纳，不额外堆出一排新胎",
    "cover_fuel_prep": "密闭合规燃油容器和封好的软管留在室外通风工位的吸油垫上，远离热源；这里只准备补油，店内不陈列油桶墙",
    "cover_brake": "小瓶检漏液与检查位置相邻，师傅正在外侧可接近的气路接头处检查；气路真实连通，不把气压设备、轮胎和油桶混成展示堆",
    "cover_torque": "扭力扳手套筒牢靠接触已落地车轮的螺母，旧轮放在后方不挡通道的位置；不用的顶升工具已退出当前作业位置",
    "cover_tools": "正在收回抽屉的扭力扳手与手部有明确接触，工具车靠近刚结束的工位；少量抹布留在台面一角，抽屉并非全部同时展开展示",
}


def _signature(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()


def _offset(group_index: int) -> int:
    if group_index < EPOCH_GROUP:
        raise ValueError("truck scene v3 applies only to group 274 and later")
    return group_index - EPOCH_GROUP


@variable_catalog.managed('truck_rescue',finish_result=False)
def detail_variant(role: str, group_index: int) -> dict[str, str]:
    offset = _offset(group_index)
    role_index = ROLES.index(role)
    event_index = (offset + offset // 6 + role_index) % len(EVENTS[role])
    event_id, vehicle, powertrain, brake_system, action, tools = EVENTS[role][event_index]
    camera_id, camera = DETAIL_CAMERAS[(offset + role_index) % len(DETAIL_CAMERAS)]
    location_id, location = LOCATIONS[(offset * 2 + offset // 24 + role_index) % len(LOCATIONS)]
    light_id, lighting = LIGHTS[(offset * 3 + offset // 7 + role_index) % len(LIGHTS)]
    clothing = WORKWEAR[(offset * 3 + role_index) % len(WORKWEAR)]
    return {
        "scene_version": SCENE_VERSION, "event_id": event_id, "camera_id": camera_id,
        "light_id": light_id, "location_id": location_id,
        "major_signature": _signature(role, event_id, camera_id, location_id),
        "vehicle": vehicle, "powertrain": powertrain, "brake_system": brake_system,
        "location": location, "action": action, "tools": tools,
        "camera_composition": camera, "lighting": lighting, "workwear": clothing,
    }


@variable_catalog.managed('truck_rescue',finish_result=False)
def cover_variant(library: dict[str, list[str]], group_index: int) -> dict[str, str]:
    offset = _offset(group_index)
    camera_id, layout, camera = COVER_FRAMES[offset % len(COVER_FRAMES)]
    event_id, action, state = COVER_EVENTS[(offset * 3 + offset // 12) % len(COVER_EVENTS)]
    locations = library["storefront_locations"]
    location_index = (offset * 5 + offset // 12) % len(locations)
    light_id, light = LIGHTS[(offset * 3 + offset // 12) % len(LIGHTS)]
    signs = library["signboard_variants"]
    vehicle_id = (offset + offset // 12) % 4
    support_vehicle = (
        "没有第二辆完整服务车，故障货车与当前工具就是业务证据",
        "只在画面边缘露出普通工具服务车后部，不占据主前景，不遮门头",
        "没有额外救援车，仅靠工作灯、轮挡和当前故障车辆呈现业务",
        "普通工具服务车停在侧后方阴影内，只露小部分无品牌车身",
    )[vehicle_id]
    variant = {
        "scene_version": SCENE_VERSION, "event_id": event_id, "camera_id": camera_id,
        "light_id": light_id, "location_id": f"cover_location_{location_index}",
        "major_signature": _signature(camera_id, event_id, str(location_index), str(vehicle_id)),
        "storefront_location": locations[location_index], "storefront_layout": layout,
        "camera_composition": camera, "shop_state": state, "weather_atmosphere": light,
        "front_activity": action, "service_vehicle": support_vehicle,
        "signboard_variant": signs[(offset * 5 + offset // 12) % len(signs)],
        "workwear": WORKWEAR[(offset * 3 + offset // 8) % len(WORKWEAR)],
    }
    if group_index >= REFERENCE_LEARNING_EPOCH_GROUP:
        learned_offset = group_index - REFERENCE_LEARNING_EPOCH_GROUP
        family, frame_indexes, emphasis = LEARNED_COMPOSITIONS[learned_offset % len(LEARNED_COMPOSITIONS)]
        frame_index = frame_indexes[(learned_offset // len(LEARNED_COMPOSITIONS)) % len(frame_indexes)]
        camera_id, layout, camera = COVER_FRAMES[frame_index]
        variant.update({
            "reference_learning_version": REFERENCE_LEARNING_VERSION,
            "composition_family": family,
            "composition_emphasis": emphasis,
            "work_detail_id": event_id + "_placement",
            "work_detail": COVER_WORK_DETAILS[event_id],
            "local_text_learning_policy": "optional_supplement_not_global_template",
            "camera_id": camera_id,
            "storefront_layout": layout,
            "camera_composition": camera,
            "major_signature": _signature(camera_id, event_id, str(location_index), str(vehicle_id), family),
        })
    return variant


def cover_positive_prompt(variant: dict[str, str], signage_rule: str) -> str:
    learned = variant.get("reference_learning_version") == REFERENCE_LEARNING_VERSION
    learning_prompt = (
        f"本组构图侧重点：{variant['composition_emphasis']}。"
        f"工作中的实际摆放细节：{variant['work_detail']}。"
        "店面、工具和人员根据这次业务自然形成画面，不复刻参考底图，不把相同道具位置当作固定风格。"
        if learned else ""
    )
    environment_prompt = (
        "环境只保留与当前机位相符的墙体、门框、雨棚或邻店边缘，正常磨损与板缝自然出现；"
        "不要求每图同时呈现门头、车间、前景工人三层，不把每一幅都做旧做脏。"
        if learned else
        "保持普通墙体、卷帘门上沿、雨棚或邻店边缘至少两种环境层次，保留板缝与正常使用痕迹，但不把每一幅都做旧做脏。"
    )
    return (
        "真实中国货车救援维修小店的普通手机纪实照片，仅表现一次具体业务瞬间，不是招牌设计稿、广告海报、展厅或商业大片。"
        f"位置：{variant['storefront_location']}；建筑与工位：{variant['storefront_layout']}。"
        f"本次唯一业务事件：{variant['front_activity']}；营业状态：{variant['shop_state']}。"
        f"拍摄站位：{variant['camera_composition']}；光线：{variant['weather_atmosphere']}。"
        f"{learning_prompt}"
        f"人物{variant['workwear']}，专注动作而不看镜头。车辆关系：{variant['service_vehicle']}。"
        "车辆是无品牌的货运车辆，不出现乘用车；车身颜色由朴素灰、暗红、旧蓝、深绿自然选择，不要批量固定白色车头、左前视角和蓝衣师傅。"
        f"实体招牌材质：{variant['signboard_variant']}。{signage_rule}"
        "主招牌内部另有准确的小字“应急送油 · 爆胎救援 · 货车换胎 · 发动机检修 · 搭电启动 · 刹车检修”。"
        "联系电话必须刻印或安装在同一实体招牌主板内部的联系信息区，跟随板面透视与自然光；精确号码仅由当前确认数据注入，不能自造号码。"
        f"{environment_prompt}"
        "招牌及其电话位于画面上部40%内且可读；中部43%至53.5%是本地电话条安全区，下部70%至96.5%是本地十服务词安全区。"
        "人物头手、关键操作与招牌文字不落入覆盖区；保持动作可辨，不强迫所有车辆全部入画。"
        "原图绝不提前生成中部电话条、底部按钮、宫格、边框或UI。无水印、二维码、可读车牌、真实品牌标志和未经确认的地区时效价格承诺。"
    )


def detail_positive_prompt(role: str, role_id: str, variant: dict[str, str], generation_kind: str) -> str:
    reserve = (
        "本图只是一张独立实景三拼面板，不生成拼贴或边框；关键动作留在中央安全区，四周保留少量可裁切环境。"
        if generation_kind == "triptych_panel" else
        "顶部3.5%至10.5%留给本地角色文字，中部49%至58.5%和底部83.5%至97.5%为本地电话与服务词安全区，关键动作不被这些区域遮住。"
    )
    return (
        "真实中国货车救援维修现场的普通手机工作记录，不是宣传摆拍、海报、插画或3D。"
        f"服务角色：{role}；规范语义：{role_id}。车辆：{variant['vehicle']}；地点：{variant['location']}。"
        f"只表现当前阶段：{variant['action']}。本阶段所需设备：{variant['tools']}。"
        f"镜头：{variant['camera_composition']}；光线：{variant['lighting']}；人员{variant['workwear']}，不看镜头。"
        "只保留一个到两个自然工作痕迹，例如工具轻微磨损或墙面斑驳，不统一湿地面、不把工具均匀摆一排。"
        "车辆完全停稳，驻车、警戒、轮挡和支撑严格服从当前动作阶段；手与工具接触真实，软管线缆真实连通，不复制多余轮胎或肢体。"
        "货车车身可用普通灰、暗红、旧蓝或深绿，不反复使用白色车头与蓝衣工人作为主构图。"
        f"{reserve}原图不生成电话、文字条、标签、UI、可读车牌、品牌、二维码、水印或商业承诺。"
    )
