"""Build truck-rescue v3 manifests without calling any image or network API.

The truck category deliberately reuses only the road-rescue delivery structure:
one cover, three independently generated triptych panels, and three independent
details.  Its roles, vehicles, actions, tools, locations, and source lineage are
truck-only and never read ``prompts/road_rescue_prompts.jsonl``.
"""

from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog

import argparse
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.truck_rescue_signage import (
    NAMING_EPOCH_GROUP,
    signage_override_text,
    signage_variant,
)
from tools.contact_numbers import is_canonical_contact_number
from tools import truck_scene_diversity_v3


ROOT = Path(__file__).resolve().parent
PROJECT_ID = "truck_rescue"
CATEGORY_NAME = "货车救援维修"
STRUCTURE_VERSION = "truck_rescue_v3_1cover_1triptych_3details"
GENERATION_MODE = "independent_triptych_panels"
BATCH_NAME = "batch_v3_active"
PROJECT_DIR = ROOT / "projects" / PROJECT_ID
GROUPS_DIR = PROJECT_DIR / "groups"
REGISTRY_PATH = GROUPS_DIR / "registry.json"
BATCH_DIR = ROOT / "prompts" / "category_batches" / PROJECT_ID / BATCH_NAME
CATEGORY_CONFIG_PATH = ROOT / "configs" / "categories" / f"{PROJECT_ID}.json"
COVER_LIBRARY_PATH = PROJECT_DIR / "cover_scene_library.json"
BUSINESS_PATH = ROOT / ".runtime" / "projects" / PROJECT_ID / "business.json"
UNIT_COUNT = 7
DELIVERY_COUNT = 5

ROLE_IDS = {
    "货车没油救援": "truck_out_of_fuel_rescue",
    "货车爆胎救援": "truck_tire_blowout_rescue",
    "货车换轮胎": "truck_wheel_replacement",
    "货车发动机故障": "truck_engine_fault_diagnosis",
    "卡车搭电": "truck_battery_jump_start",
    "货车刹车故障": "truck_brake_fault_diagnosis",
}

ROLE_VARIANTS: dict[str, tuple[dict[str, str], ...]] = {
    "货车没油救援": (
        {
            "vehicle": "明确为燃油动力的中型厢式货车",
            "powertrain": "combustion",
            "brake_system": "unspecified",
            "location": "国道货运通道旁的安全停车带",
            "action": "工作人员先确认车辆停稳并核对油表与油箱口，再用合规应急燃油容器和防静电输油软管补充与车辆匹配的燃油",
            "tools": "合规应急燃油容器、防静电输油软管、吸油垫、防护手套和路锥",
        },
        {
            "vehicle": "明确为燃油动力的轻型栏板货车",
            "powertrain": "combustion",
            "brake_system": "unspecified",
            "location": "物流园货车停车区边缘的安全作业位",
            "action": "工作人员检查燃油表和侧置油箱后，使用封闭容器与防静电软管进行少量应急补充，现场无洒漏",
            "tools": "封闭式应急燃油容器、防静电软管、吸油垫、警示锥和灭火器",
        },
        {
            "vehicle": "明确为燃油动力的重型载货卡车",
            "powertrain": "combustion",
            "brake_system": "air",
            "location": "工业园货运道路旁的封闭检修位",
            "action": "工作人员确认车辆熄火、驻车和轮挡到位，核对油量后补充与该车匹配的燃油并复查接口",
            "tools": "合规燃油容器、防静电加注软管、轮挡、吸油垫、防护手套和警示灯",
        },
    ),
    "货车爆胎救援": (
        {
            "vehicle": "重型载货卡车，后轮胎体明显爆裂但车辆完全静止",
            "powertrain": "combustion",
            "brake_system": "air",
            "location": "工业园重型货车停车区的安全硬化区域",
            "action": "工作人员先设置警戒区和轮挡，再检查爆裂轮胎、轮辋与异物，本场景只表现检查和救援判断，不安装新胎",
            "tools": "大型警示牌、重型轮挡、检修灯、轮胎撬棒和重型支撑架",
        },
        {
            "vehicle": "重型牵引车半挂组合，挂车外侧轮胎爆裂且车辆停稳",
            "powertrain": "combustion",
            "brake_system": "air",
            "location": "高速服务区货车停车区的维修作业位",
            "action": "救援人员封闭安全作业区，观察胎体破口、双胎间隙和轮辋状况，判断需要更换而不是简单补胎",
            "tools": "大型警示牌、重型轮挡、检修灯、胎压表和支撑架",
        },
        {
            "vehicle": "冷藏货车，后轴单侧轮胎严重破损且车辆完全静止",
            "powertrain": "unspecified",
            "brake_system": "unspecified",
            "location": "物流园装卸区旁的独立安全检修位",
            "action": "工作人员完成驻车和轮挡后检查轮胎侧壁、胎面和轮辋，明确严重爆胎不能画成胶条补胎",
            "tools": "轮挡、路锥、重型千斤顶待命、支撑架和工作灯",
        },
    ),
    "货车换轮胎": (
        {
            "vehicle": "轻型厢式货车，匹配尺寸的完整备胎清楚放在车旁",
            "powertrain": "unspecified",
            "brake_system": "hydraulic",
            "location": "城郊货车维修区的坚实水泥作业面",
            "action": "工作人员在轮挡和支撑到位后拆下旧车轮、对位安装匹配备胎，并按交叉顺序紧固螺母",
            "tools": "货车用液压千斤顶、支撑架、轮挡、车轮扳手和扭力扳手",
        },
        {
            "vehicle": "中型栏板货车，货车尺寸备胎与旧车轮同时可见",
            "powertrain": "unspecified",
            "brake_system": "unspecified",
            "location": "普通国道路边的硬化安全停车区",
            "action": "工作人员先松螺母再从正确顶升点抬升车辆，移除旧轮并安装备胎，最后使用扭力工具复核",
            "tools": "重型液压千斤顶、支撑架、轮挡、冲击扳手和扭力扳手",
        },
        {
            "vehicle": "重型载货卡车，匹配后轴结构的货车车轮总成放置在安全位置",
            "powertrain": "combustion",
            "brake_system": "air",
            "location": "物流园流动维修工位的平整硬化地面",
            "action": "两名工作人员配合移动车轮总成，完成轮毂对位、安装与交叉紧固，车辆由重型支撑可靠承托",
            "tools": "重型千斤顶、重型支撑架、轮挡、大扭矩套筒工具和轮胎搬运辅助架",
        },
    ),
    "货车发动机故障": (
        {
            "vehicle": "重型平头载货卡车，驾驶室按规范翻转并可靠锁止",
            "powertrain": "combustion",
            "brake_system": "air",
            "location": "工业园重卡维修门店外的独立诊断工位",
            "action": "维修人员先读取故障码和数据流，再检查燃油供给、启动电路与线束连接，不默认拆卸或大修发动机",
            "tools": "货车诊断平板、万用表、检修灯、绝缘探针和基础机修工具",
        },
        {
            "vehicle": "轻型厢式货车，发动机舱盖打开并由支撑杆固定",
            "powertrain": "combustion",
            "brake_system": "hydraulic",
            "location": "城郊货车快修门店的普通维修位",
            "action": "维修人员读取故障信息并检查蓄电池端子、启动回路、燃油管路和可见连接点，保持先诊断后维修",
            "tools": "诊断仪、万用表、工作灯、端子清洁工具和手工具箱",
        },
        {
            "vehicle": "重型牵引卡车，驾驶室翻转后发动机与周边管线自然可见",
            "powertrain": "combustion",
            "brake_system": "air",
            "location": "物流园重卡维修区的独立诊断工位",
            "action": "技术人员连接商用车诊断设备，查看故障码并检查启动、供油和传感器线路，不表现吊装发动机",
            "tools": "商用车诊断电脑、万用表、检修灯、绝缘手套和常用机修工具",
        },
    ),
    "卡车搭电": (
        {
            "vehicle": "大型全尺寸货运皮卡，开放式货厢有明确商用载货与工具使用痕迹，发动机舱内蓄电池位置打开且车辆完全停稳",
            "powertrain": "combustion",
            "brake_system": "hydraulic",
            "location": "城郊货运市场停车区的安全检修位",
            "action": "工作人员先核对车辆额定电压、正负极和端子状态，再用粗规格跨接线连接匹配电压的辅助电源",
            "tools": "与该大型货运皮卡额定规格匹配的专业启动电源、粗规格跨接线、绝缘夹、万用表和绝缘手套",
        },
        {
            "vehicle": "轻型栏板货车，蓄电池端子和线束连接点清楚可见",
            "powertrain": "combustion",
            "brake_system": "hydraulic",
            "location": "县城货运街道旁的封闭作业位",
            "action": "工作人员用万用表确认电压并核对极性，随后连接与该车额定电压匹配的重型启动设备",
            "tools": "匹配额定电压的启动设备、粗规格搭电线、万用表、绝缘手套和警示锥",
        },
        {
            "vehicle": "重型载货卡车，侧置蓄电池箱开启且轮挡到位",
            "powertrain": "combustion",
            "brake_system": "air",
            "location": "工业园货运通道旁的安全停车区",
            "action": "救援人员先确认额定电压和连接顺序，再使用商用车级辅助电源跨接启动，画面不出现火花或反接",
            "tools": "商用车级重型启动电源、粗规格跨接线、万用表、绝缘护具和轮挡",
        },
    ),
    "货车刹车故障": (
        {
            "vehicle": "轻型厢式货车，明确为液压制动系统并在维修位停稳",
            "powertrain": "unspecified",
            "brake_system": "hydraulic",
            "location": "城郊货车维修门店的平整检修位",
            "action": "工作人员在驻车和轮挡到位后检查制动液、液压软管与轮端制动部件，人员不进入无可靠支撑的车底",
            "tools": "检修灯、诊断仪、制动液检测工具、轮挡和可靠支撑架",
        },
        {
            "vehicle": "中型载货卡车，明确为空气制动系统并完全静止",
            "powertrain": "combustion",
            "brake_system": "air",
            "location": "物流园货车维修区的安全检修位",
            "action": "技术人员查看制动气压并检查气管、空气干燥器、储气筒和制动气室的连接与漏气点",
            "tools": "制动压力表、检漏液、诊断设备、检修灯、轮挡和支撑架",
        },
        {
            "vehicle": "重型牵引车半挂组合，明确为空气制动系统且驻车完成",
            "powertrain": "combustion",
            "brake_system": "air",
            "location": "高速服务区货车维修工位的封闭安全区",
            "action": "工作人员先布置警戒和轮挡，再检查仪表气压、挂车气路连接和轮端制动组件，不表现故障车辆继续行驶",
            "tools": "压力检测设备、检漏液、商用车诊断仪、轮挡、警示锥和可靠支撑架",
        },
    ),
}

CAMERAS = (
    "普通手机眼平中景，从货车左前侧轻微斜拍",
    "维修人员视角的普通手机中近景，人物不看镜头",
    "从货车右后侧稍远记录，车辆、工具和警戒区关系完整",
    "轻微高机位手机抓拍，保留真实透视但不使用航拍",
    "从安全作业区边缘侧拍，画面带少量道路和环境纵深",
    "普通手机两倍焦段稍远拍摄，细节清楚但不过度锐化",
)

LIGHTING = (
    "普通阴天自然漫射光",
    "晴天白昼自然光，色彩克制",
    "雨后白天柔和环境光，路面只有少量湿痕",
    "工作日傍晚的普通环境光与检修灯混合照明",
    "上午自然侧光与真实手机自动曝光",
)

FALLBACK_COVER_LIBRARY = {
    "storefront_locations": [
        "物流园货运通道旁的两开间货车维修门店",
        "工业园主路边的普通货车流动抢修门店",
        "国道货运服务区内的实用型货车维修铺",
        "城郊货车维修集中区的临街小店",
        "高速服务区货车停车区旁的维修服务点",
        "县城货运市场外围的普通货车快修门店",
    ],
    "storefront_layouts": [
        "两开间卷帘门，一侧维修、一侧工具与接待",
        "宽门面配普通钢结构雨棚和清楚的作业通道",
        "转角门店，招牌沿主立面自然安装但不过度延伸",
        "单层独立门店，门前有可供货车短暂停靠的硬化场地",
    ],
    "camera_compositions": [
        "从左前方四十五度的普通手机中远景",
        "从右前方轻斜拍摄并保留货运道路纵深",
        "街对面眼平全景，完整拍到招牌、卷帘门和门前场地",
        "站在门店入口外侧稍低机位拍摄，货车与门店形成自然前后关系",
        "路边经过时的随手抓拍角度，略有偏斜但主体清楚",
    ],
    "shop_states": [
        "卷帘门完全打开，师傅正在正常作业",
        "一扇卷帘门半开、一扇完全打开，呈现真实营业状态",
        "刚开始营业，工作人员整理重型工具和轮胎设备",
        "维修区有一辆货车停稳检修，门前通道保持畅通",
    ],
    "weather_atmospheres": [
        "普通阴天白昼",
        "晴天上午自然光",
        "雨后白天，地面有少量真实湿痕",
        "初冬干冷的普通日光",
        "夏季略闷热的自然漫射光",
    ],
    "front_activities": [
        "一名师傅检查货车轮胎，另一人整理搭电和诊断设备",
        "门店工位内的中型货车打开发动机检修位置，工作人员使用诊断仪",
        "门前摆放重型千斤顶、轮挡和货车尺寸轮胎，工作人员准备换胎",
        "流动维修服务车停在侧面，师傅在工具舱取用检修设备",
        "货车制动与底盘检查正在可靠支撑的工位内进行",
    ],
    "service_vehicles": [
        "一辆带重型工具舱的货车流动维修服务车停在门店侧面",
        "一辆中重型清障救援车只露出部分车身与警示设备，不遮挡招牌",
        "一辆普通工程救援服务车停在门店后侧，车身不出现品牌和号码",
        "不出现完整救援车，只通过重型工具舱、轮挡、检修灯和货车轮胎体现业务",
    ],
    "signboard_variants": [
        "深灰蓝哑光铝塑板配清楚的浅色实体字",
        "克制砖红色普通门头板配米白立体字",
        "暖灰色金属门头配深色与小面积黄色强调字",
        "深绿色实用型门头板配白色实体字",
        "浅灰蓝普通门头板配深蓝实体字",
    ],
}


class TruckRescueManifestError(ValueError):
    """Raised when local truck-rescue manifest state is incomplete or unsafe."""


@variable_catalog.document_loader
def _load_json(path: Path) -> dict[str, Any]:
    return runtime_paths.read_json(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TruckRescueManifestError(f"JSONL parse failed: {path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise TruckRescueManifestError(f"JSONL row must be an object: {path}:{line_number}")
        rows.append(row)
    return rows


def _jsonl_text(rows: Iterable[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _append_text(existing: str, addition: str) -> str:
    if existing and not existing.endswith("\n"):
        existing += "\n"
    return existing + addition


def _confirmed_phone_gate() -> None:
    if not BUSINESS_PATH.is_file():
        raise TruckRescueManifestError(
            "CONTACT_CONFIRMATION_REQUIRED: 先由用户明确确认货车项目手机号，再建立首图清单"
        )
    business = _load_json(BUSINESS_PATH)
    phones = [str(value).strip() for value in business.get("contact_phones") or []]
    if (
        business.get("user_confirmed") is not True
        or business.get("placeholder_only") is True
        or not phones
        or len(set(phones)) != len(phones)
        or any(not is_canonical_contact_number(phone) for phone in phones)
    ):
        raise TruckRescueManifestError(
            "CONTACT_CONFIRMATION_REQUIRED: 货车项目必须登记用户明确确认的有效联系电话"
        )


def _negative_prompt(config: dict[str, Any]) -> str:
    value = config.get("negative_prompt")
    if isinstance(value, list):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _structure(config: dict[str, Any]) -> dict[str, Any]:
    structure = config.get("image_group_structure")
    if not isinstance(structure, dict):
        raise TruckRescueManifestError("truck_rescue category config is missing image_group_structure")
    expected = {
        "structure_version": STRUCTURE_VERSION,
        "generation_mode": GENERATION_MODE,
        "cover_count": 1,
        "triptych_count": 1,
        "triptych_panel_count": 3,
        "detail_count": 3,
        "total_per_group": DELIVERY_COUNT,
        "generation_unit_count": UNIT_COUNT,
        "service_roles_per_group": 6,
    }
    for key, value in expected.items():
        if structure.get(key) != value:
            raise TruckRescueManifestError(f"truck_rescue {key} must be {value!r}")
    role_pool = structure.get("service_role_pool")
    if role_pool != list(ROLE_IDS):
        raise TruckRescueManifestError("truck_rescue service_role_pool must be the six canonical truck roles")
    heights = structure.get("height_profiles")
    layouts = structure.get("triptych_layouts")
    if not isinstance(heights, list) or len(heights) != 3:
        raise TruckRescueManifestError("truck_rescue requires three height profiles")
    if not isinstance(layouts, list) or len(layouts) != 3:
        raise TruckRescueManifestError("truck_rescue requires three triptych layouts")
    return structure


@variable_catalog.managed('truck_rescue',finish_result=False)
def _cover_library() -> dict[str, list[str]]:
    configured = _load_json(COVER_LIBRARY_PATH) if COVER_LIBRARY_PATH.is_file() else {}
    aliases = {
        "storefront_locations": ("storefront_locations", "locations", "facade_archetypes"),
        "storefront_layouts": ("storefront_layouts",),
        "camera_compositions": ("camera_compositions",),
        "shop_states": ("shop_states",),
        "weather_atmospheres": ("weather_atmospheres",),
        "front_activities": ("front_activities", "workshop_activities"),
        "service_vehicles": (
            "service_vehicles",
            "service_vehicle_prominence",
            "support_vehicles",
        ),
        "signboard_variants": (
            "signboard_variants",
            "sign_color_schemes",
            "sign_surface_styles",
        ),
    }
    result: dict[str, list[str]] = {}
    for key, fallback in FALLBACK_COVER_LIBRARY.items():
        values = None
        for source_key in aliases[key]:
            candidate = configured.get(source_key)
            if isinstance(candidate, list) and candidate and all(
                isinstance(item, str) and item.strip() for item in candidate
            ):
                values = candidate
                break
        if not isinstance(values, list) or not values or not all(
            isinstance(item, str) and item.strip() for item in values
        ):
            values = fallback
        result[key] = [str(item).strip() for item in values]
    return result


def _height_and_layout(
    structure: dict[str, Any], group_index: int
) -> tuple[dict[str, Any], dict[str, Any], int]:
    heights = list(structure["height_profiles"])
    layouts = list(structure["triptych_layouts"])
    height = dict(heights[(group_index - 1) % len(heights)])
    layout = dict(layouts[((group_index - 1) // len(heights)) % len(layouts)])
    cycle_index = (group_index - 1) % (len(heights) * len(layouts))
    return height, layout, cycle_index


def _assigned_roles(role_pool: list[str], group_index: int) -> list[str]:
    start = (group_index - 1) % len(role_pool)
    return [role_pool[(start + offset) % len(role_pool)] for offset in range(6)]


@variable_catalog.managed('truck_rescue','cover',finish_result=False)
def _cover_variant(library: dict[str, list[str]], group_index: int) -> dict[str, str]:
    if group_index >= truck_scene_diversity_v3.EPOCH_GROUP:
        variant = truck_scene_diversity_v3.cover_variant(library, group_index)
        variant.update(signage_variant(group_index, COVER_LIBRARY_PATH))
        return variant
    offset = group_index - 1

    def choose(key: str, step: int, shift: int = 0) -> str:
        values = library[key]
        return values[(offset * step + shift) % len(values)]

    front_activities = library["front_activities"]
    if group_index <= 3:
        # Preserve the exact activity choices already used by the approved
        # three-cover sample gate, even when future-only items are appended.
        legacy_length = min(len(front_activities), 6)
        front_activity = front_activities[(offset * 2 + 1) % legacy_length]
    else:
        # Future covers traverse the full pool. The shift starts with appended
        # heavy-truck / large-cargo-pickup items without changing groups 1-3.
        front_activity = front_activities[(offset + 3) % len(front_activities)]

    variant = {
        "storefront_location": choose("storefront_locations", 1),
        "storefront_layout": choose("storefront_layouts", 3, 1),
        "camera_composition": choose("camera_compositions", 5),
        "shop_state": choose("shop_states", 3),
        "weather_atmosphere": choose("weather_atmospheres", 4),
        "front_activity": front_activity,
        "service_vehicle": choose("service_vehicles", 3, 1),
        "signboard_variant": choose("signboard_variants", 5),
    }
    if group_index >= NAMING_EPOCH_GROUP:
        variant.update(signage_variant(group_index, COVER_LIBRARY_PATH))
    return variant


@variable_catalog.managed('truck_rescue','cover',finish_result=False)
def _cover_positive_prompt(variant: dict[str, str]) -> str:
    if variant.get("scene_version") == truck_scene_diversity_v3.SCENE_VERSION:
        signage_rule = (
            signage_override_text(variant)
            if variant.get("full_store_name")
            else "主招牌唯一完整名称为“货车救援维修”。"
        )
        return truck_scene_diversity_v3.cover_positive_prompt(variant, signage_rule)
    service_line = "应急送油 · 爆胎救援 · 货车换胎 · 发动机检修 · 搭电启动 · 刹车检修"
    if variant.get("full_store_name"):
        signage_rule = (
            f"{signage_override_text(variant)}"
            "两字寓意字号和行业尾缀共同构成唯一完整主名称，下层服务小字清楚准确写成"
        )
    else:
        signage_rule = "主招牌最大业务词必须清楚准确写成“货车救援维修”，下层服务小字清楚准确写成"
    return (
        "一张完全依靠文字描述生成、不使用参考图片的写实中国货车救援维修门店照片。"
        "最高优先级是普通实体门店外景全景，不是招牌设计稿、广告海报、门店效果图或室内特写。"
        f"门店位置：{variant['storefront_location']}；门面结构：{variant['storefront_layout']}；"
        f"营业状态：{variant['shop_state']}；天气与光线：{variant['weather_atmosphere']}。"
        f"门前真实业务：{variant['front_activity']}；救援车辆关系：{variant['service_vehicle']}。"
        "所有主要车辆、轮胎、千斤顶、支撑和维修设备都必须符合轻卡、中卡、重卡、厢式货车、载货卡车、牵引车半挂组合，或低频出现的大型全尺寸货运皮卡的尺度，"
        "后续批次适度提高重型载货卡车、重型牵引车和半挂组合的出现比例；大型全尺寸货运皮卡可以作为商用货车主体低频出现，普通家用小皮卡和乘用化皮卡不得混入。"
        f"门头采用{variant['signboard_variant']}，必须是建筑上真实安装、有板材拼缝、包边、固定结构、轻微灰尘雨痕和自然投影的实体主招牌。"
        f"{signage_rule}"
        f"“{service_line}”。同一主招牌板面内部必须留有清楚的联系电话信息区；"
        "确切号码由生产计划根据用户当前确认号码安全注入，不得出现占位号码或其他号码。"
        f"拍摄方式：{variant['camera_composition']}；完整拍到主招牌、卷帘门、门店一层外立面、门前硬化场地、货车业务证据和一侧环境边缘。"
        "普通智能手机临时记录质感，自然透视、轻微手持偏斜、手机噪点、玻璃反光、地面灰尘水迹与正常使用痕迹真实；"
        "画面实用、克制、可信，不豪华、不破败。"
        "中部43%至53.5%留出横向可读背景供本地添加大电话，下部70%至96.5%以硬化场地或街面为主供本地添加十个服务词；"
        "人物脸、手、货车轮胎、诊断动作和门头核心文字不得落入主要覆盖区。"
        "原图不要提前生成中部电话条、底部服务按钮、卡片、边框或宫格UI。"
    )


@variable_catalog.managed('truck_rescue','detail',finish_result=False)
def _detail_positive_prompt(
    role: str,
    variant: dict[str, str],
    group_index: int,
    relative_index: int,
    generation_kind: str,
) -> str:
    if variant.get("scene_version") == truck_scene_diversity_v3.SCENE_VERSION:
        return truck_scene_diversity_v3.detail_positive_prompt(
            role, ROLE_IDS[role], variant, generation_kind,
        )
    camera = CAMERAS[((group_index - 1) * 2 + relative_index) % len(CAMERAS)]
    lighting = LIGHTING[((group_index - 1) * 3 + relative_index) % len(LIGHTING)]
    unit_note = (
        "本图是三拼图中的一个独立实景面板，只表现当前一个故障处理现场，不自行生成拼贴、边框、标题或分栏。"
        if generation_kind == "triptych_panel"
        else "顶部3.5%至10.5%留出简洁背景供本地添加当前服务角色标签。"
    )
    reserve = (
        "主体保持在中央安全区，四周保留少量可裁切背景供本地组成三拼图。"
        if generation_kind == "triptych_panel"
        else "中部49%至58.5%留出横向简洁背景，底部83.5%至97.5%留出简洁背景供本地添加电话与十个服务词。"
    )
    return (
        "真实中国货车救援维修详情源图，普通手机拍摄的现场工作记录，不是海报、插画、CG、3D或广告摄影。"
        f"服务角色：{role}；规范语义：{ROLE_IDS[role]}。"
        f"目标车辆：{variant['vehicle']}；地点：{variant['location']}。"
        f"工作人员动作：{variant['action']}；工具与设备：{variant['tools']}。"
        "车辆必须完全停稳，警戒、驻车、轮挡、顶升或支撑措施按当前动作合理出现；工具、轮胎、车轴、蓄电池和制动部件均与当前具体货车或大型全尺寸货运皮卡的额定规格和承载尺度匹配。"
        f"拍摄方式：{camera}；光线：{lighting}。人物不看镜头，手部和工具接触关系真实，保留正常工作痕迹。"
        f"{unit_note}{reserve}关键动作、轮胎、端子、发动机诊断点或制动检查点不得被叠字区遮挡。"
        "原图不生成电话、可读车牌、品牌、价格、二维码、水印、文字条、按钮或UI。"
    )


@variable_catalog.managed('truck_rescue','$role',finish_result='always')
def _record(
    *,
    index: int,
    group_index: int,
    generation_position: int,
    generation_kind: str,
    delivery_position: int,
    service_role: str | None,
    height: dict[str, Any],
    layout: dict[str, Any],
    cycle_index: int,
    positive_prompt: str,
    negative_prompt: str,
    scene: dict[str, Any],
    cover_variant: dict[str, str] | None = None,
    panel_index: int | None = None,
) -> dict[str, Any]:
    final_size = f"{int(height['width'])}x{int(height['height'])}"
    generation_id = f"{PROJECT_ID}:v3:g{group_index:04d}:u{generation_position:02d}"
    if generation_kind == "cover":
        raw_filename = "01_cover.png"
    elif generation_kind == "triptych_panel":
        raw_filename = f"02_triptych_panel_{panel_index:02d}.png"
    else:
        raw_filename = f"{delivery_position:02d}_detail.png"
    delivery_filename = (
        "01_cover.png"
        if delivery_position == 1
        else "02_triptych.png"
        if delivery_position == 2
        else f"{delivery_position:02d}_detail.png"
    )
    prompt = positive_prompt + f"\n严格排除：{negative_prompt}"
    result: dict[str, Any] = {
        "schema_version": 3,
        "index": index,
        "category_id": PROJECT_ID,
        "project_id": PROJECT_ID,
        "group_index": group_index,
        "generation_position": generation_position,
        "delivery_position": delivery_position,
        "generation_role": generation_kind,
        "generation_kind": generation_kind,
        "service_role": service_role,
        "service_role_id": ROLE_IDS.get(str(service_role)),
        "panel_index": panel_index,
        "structure_version": STRUCTURE_VERSION,
        "generation_mode": GENERATION_MODE,
        "height_profile_id": str(height["id"]),
        "final_size": final_size,
        "expected_size": final_size,
        "raw_size": "1024x1536",
        "triptych_layout_id": str(layout["id"]) if generation_kind == "triptych_panel" else None,
        "triptych_panel_box": (
            dict(layout["panels"][int(panel_index) - 1])
            if generation_kind == "triptych_panel" and panel_index is not None
            else None
        ),
        "variation_cycle_index": cycle_index,
        "generation_id": generation_id,
        "raw_target": (
            f"prompts/category_batches/{PROJECT_ID}/{BATCH_NAME}/raw/"
            f"group_{group_index:04d}/{raw_filename}"
        ),
        "delivery_target": f"output/{PROJECT_ID}/group_{group_index:04d}/{delivery_filename}",
        "source_lineage": f"projects/{PROJECT_ID}/category_content_profile.json",
        "scene": scene,
        "source_positive_prompt": positive_prompt,
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "prompt": prompt,
        "prompt_sha256": _sha256_text(prompt),
        "status": "prompt_ready",
        "api_called": False,
    }
    if cover_variant is not None:
        material = json.dumps(cover_variant, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        result["cover_variant"] = cover_variant
        result["cover_variant_signature"] = _sha256_text(material)
    return result


def _delivery_row(
    group_index: int,
    delivery_position: int,
    role: str,
    height: dict[str, Any],
    layout: dict[str, Any],
    cycle_index: int,
    generation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    final_size = f"{int(height['width'])}x{int(height['height'])}"
    filename = (
        "01_cover.png"
        if delivery_position == 1
        else "02_triptych.png"
        if delivery_position == 2
        else f"{delivery_position:02d}_detail.png"
    )
    return {
        "schema_version": 3,
        "structure_version": STRUCTURE_VERSION,
        "generation_mode": GENERATION_MODE,
        "project_id": PROJECT_ID,
        "category_id": PROJECT_ID,
        "group_index": group_index,
        "delivery_position": delivery_position,
        "delivery_id": f"{PROJECT_ID}:v3:g{group_index:04d}:d{delivery_position:02d}",
        "role": role,
        "delivery_role": role,
        "filename": filename,
        "target": f"output/{PROJECT_ID}/group_{group_index:04d}/{filename}",
        "source_generation_ids": [str(row["generation_id"]) for row in generation_rows],
        "service_roles": [str(row["service_role"]) for row in generation_rows if row.get("service_role")],
        "raw_size": "1024x1536",
        "expected_size": final_size,
        "final_size": final_size,
        "height_profile_id": str(height["id"]),
        "triptych_layout_id": str(layout["id"]) if role == "triptych" else None,
        "triptych_layout": layout if role == "triptych" else None,
        "triptych_gutter_px": 8 if role == "triptych" else None,
        "variation_cycle_index": cycle_index,
        "validation_status": "pending",
        "status": "prompt_ready",
        "api_called": False,
    }


@variable_catalog.managed('truck_rescue',finish_result=False)
def _build_rows(
    start_group: int,
    count: int,
    index_start: int,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    structure = _structure(config)
    role_pool = [str(value) for value in structure["service_role_pool"]]
    negative_prompt = _negative_prompt(config)
    library = _cover_library()
    generation_rows: list[dict[str, Any]] = []
    delivery_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    registry_groups: list[dict[str, Any]] = []

    for group_index in range(start_group, start_group + count):
        height, layout, cycle_index = _height_and_layout(structure, group_index)
        roles = _assigned_roles(role_pool, group_index)
        cover_variant = _cover_variant(library, group_index)
        base_index = index_start + (group_index - start_group) * UNIT_COUNT
        cover = _record(
            index=base_index,
            group_index=group_index,
            generation_position=1,
            generation_kind="cover",
            delivery_position=1,
            service_role=None,
            height=height,
            layout=layout,
            cycle_index=cycle_index,
            positive_prompt=_cover_positive_prompt(cover_variant),
            negative_prompt=negative_prompt,
            scene={
                "scene_type": "truck_rescue_storefront",
                "vehicle_policy": "truck_only",
                **cover_variant,
            },
            cover_variant=cover_variant,
        )
        group_generation = [cover]
        for relative_index, role in enumerate(roles, 1):
            generation_position = relative_index + 1
            generation_kind = "triptych_panel" if relative_index <= 3 else "detail"
            delivery_position = 2 if relative_index <= 3 else relative_index - 1
            variants = ROLE_VARIANTS[role]
            # 角色顺序会随组号轮换，因此变体只按组号推进；若把相对位置也
            # 加入索引，同一角色的两项变化会互相抵消，跨组反而永远选中
            # 同一个现场变体。
            variant = dict(variants[(group_index - 1) % len(variants)])
            if group_index >= truck_scene_diversity_v3.EPOCH_GROUP:
                variant = truck_scene_diversity_v3.detail_variant(role, group_index)
            positive = _detail_positive_prompt(
                role,
                variant,
                group_index,
                relative_index,
                generation_kind,
            )
            group_generation.append(
                _record(
                    index=base_index + relative_index,
                    group_index=group_index,
                    generation_position=generation_position,
                    generation_kind=generation_kind,
                    delivery_position=delivery_position,
                    service_role=role,
                    height=height,
                    layout=layout,
                    cycle_index=cycle_index,
                    positive_prompt=positive,
                    negative_prompt=negative_prompt,
                    scene={
                        "scene_type": ROLE_IDS[role],
                        "vehicle_policy": "truck_only",
                        **variant,
                    },
                    panel_index=relative_index if relative_index <= 3 else None,
                )
            )
        if len({str(row["service_role"]) for row in group_generation[1:]}) != 6:
            raise TruckRescueManifestError(f"group {group_index} must contain six distinct truck roles")

        group_deliveries = [
            _delivery_row(group_index, 1, "cover", height, layout, cycle_index, [group_generation[0]]),
            _delivery_row(group_index, 2, "triptych", height, layout, cycle_index, group_generation[1:4]),
        ]
        for delivery_position, source in enumerate(group_generation[4:], 3):
            group_deliveries.append(
                _delivery_row(
                    group_index,
                    delivery_position,
                    "detail",
                    height,
                    layout,
                    cycle_index,
                    [source],
                )
            )
        signature_material = {
            "cover": cover["cover_variant_signature"],
            "height": height["id"],
            "layout": layout["id"],
            "roles": roles,
            "scenes": [row["scene"] for row in group_generation[1:]],
        }
        composition_signature = _sha256_text(
            json.dumps(signature_material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        group_row = {
            "schema_version": 3,
            "structure_version": STRUCTURE_VERSION,
            "generation_mode": GENERATION_MODE,
            "project_id": PROJECT_ID,
            "group_index": group_index,
            "total_images": DELIVERY_COUNT,
            "generation_unit_count": UNIT_COUNT,
            "generation_units": [row["generation_id"] for row in group_generation],
            "delivery_files": [row["delivery_id"] for row in group_deliveries],
            "service_roles": roles,
            "height_profile": height,
            "final_size": group_deliveries[0]["final_size"],
            "triptych_layout": layout,
            "variation_cycle_index": cycle_index,
            "cover_variant_signature": cover["cover_variant_signature"],
            "composition_signature": composition_signature,
            "source_lineage": f"projects/{PROJECT_ID}/category_content_profile.json",
            "status": "prompt_ready",
            "api_called": False,
        }
        group_rows.append(group_row)
        registry_groups.append(
            {
                "group_index": group_index,
                "structure_version": STRUCTURE_VERSION,
                "generation_mode": GENERATION_MODE,
                "group_size": DELIVERY_COUNT,
                "generation_unit_count": UNIT_COUNT,
                "final_size": group_deliveries[0]["final_size"],
                "height_profile_id": str(height["id"]),
                "triptych_layout_id": str(layout["id"]),
                "variation_cycle_index": cycle_index,
                "service_roles": roles,
                "cover_variant_signature": cover["cover_variant_signature"],
                "composition_signature": composition_signature,
                "status": "prompt_ready",
            }
        )
        generation_rows.extend(group_generation)
        delivery_rows.extend(group_deliveries)
    return generation_rows, delivery_rows, group_rows, registry_groups


def _batch_manifest_rows(generation_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": 3,
            "structure_version": STRUCTURE_VERSION,
            "generation_mode": GENERATION_MODE,
            "category_id": PROJECT_ID,
            "index": row["index"],
            "group_index": row["group_index"],
            "generation_position": row["generation_position"],
            "generation_id": row["generation_id"],
            "role": row["generation_role"],
            "generation_kind": row["generation_kind"],
            "service_role": row["service_role"],
            "status": "prompt_ready",
            "raw_target": row["raw_target"],
            "delivery_target": row["delivery_target"],
            "api_called": False,
        }
        for row in generation_rows
    ]


def _summary(first_group: int, group_count: int) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "structure_version": STRUCTURE_VERSION,
        "generation_mode": GENERATION_MODE,
        "category_id": PROJECT_ID,
        "category_name": CATEGORY_NAME,
        "mode": "truck_only_active_v3_manifests",
        "group_start": first_group,
        "group_count": group_count,
        "generation_unit_count": group_count * UNIT_COUNT,
        "cover_generation_count": group_count,
        "triptych_panel_generation_count": group_count * 3,
        "detail_generation_count": group_count * 3,
        "delivery_file_count": group_count * DELIVERY_COUNT,
        "delivery_structure": {
            "cover_count": 1,
            "triptych_count": 1,
            "detail_count": 3,
            "total_per_group": DELIVERY_COUNT,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "api_called": False,
    }


def _registry(
    first_group: int,
    groups: list[dict[str, Any]],
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    count = len(groups)
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 3,
        "structure_version": STRUCTURE_VERSION,
        "generation_mode": GENERATION_MODE,
        "project_id": PROJECT_ID,
        "group_size": DELIVERY_COUNT,
        "generation_unit_count": UNIT_COUNT,
        "cover_count": 1,
        "triptych_count": 1,
        "triptych_panel_count": 3,
        "detail_count": 3,
        "created_groups": count,
        "first_group_index": first_group if count else 1,
        "last_group_index": first_group + count - 1 if count else 0,
        "next_group_index": first_group + count if count else 1,
        "active_batch": f"prompts/category_batches/{PROJECT_ID}/{BATCH_NAME}",
        "groups": groups,
        "created_at": created_at or now,
        "updated_at": now,
        "api_called": False,
    }


def _project_has_approved_samples(project: dict[str, Any]) -> bool:
    cover = project.get("references", {}).get("cover", {})
    evidence = str(cover.get("sample_approval_evidence") or "").strip()
    if cover.get("approved_style") is not True or not evidence:
        return False
    path = (ROOT / evidence).resolve()
    return PROJECT_DIR.resolve() in path.parents and path.is_file()


def _confirmed_service_words_gate(project: dict[str, Any], config: dict[str, Any]) -> None:
    field = project.get("required_fields", {}).get("service_words", {})
    configured = [str(value) for value in config.get("service_buttons") or []]
    recorded = [str(value) for value in field.get("values") or []]
    if field.get("confirmed") is not True or recorded != configured:
        raise TruckRescueManifestError(
            "SERVICE_WORD_CONFIRMATION_REQUIRED: 请先确认货车底部十个可见服务词，尤其是否提供货车补胎"
        )


def _update_project(project: dict[str, Any], group_count: int, *, initial: bool) -> None:
    prompt_sources = dict(project.get("prompt_sources", {}))
    prompt_sources.update(
        {
            "category_config": f"configs/categories/{PROJECT_ID}.json",
            "category_content_profile": f"projects/{PROJECT_ID}/category_content_profile.json",
            "category_config_version": "truck_rescue_category_content_v1",
            "visual_style": "configs/visual_styles/realistic_mobile_documentary_v2.json",
            "visual_style_version": "realistic_mobile_documentary_v2",
            "active_batch": f"prompts/category_batches/{PROJECT_ID}/{BATCH_NAME}",
            "cover_manifest": f"prompts/category_batches/{PROJECT_ID}/{BATCH_NAME}/cover_prompts.jsonl",
            "triptych_panel_manifest": f"prompts/category_batches/{PROJECT_ID}/{BATCH_NAME}/triptych_panel_prompts.jsonl",
            "detail_manifest": f"prompts/category_batches/{PROJECT_ID}/{BATCH_NAME}/detail_prompts.jsonl",
            "generation_manifest": f"projects/{PROJECT_ID}/groups/generation_manifest.jsonl",
            "production_manifest": f"projects/{PROJECT_ID}/groups/production_manifest.jsonl",
            "cover_prompt_count": group_count,
            "triptych_panel_prompt_count": group_count * 3,
            "detail_prompt_count": group_count * 3,
            "service_prompt_count": group_count * 6,
            "generation_unit_count": group_count * UNIT_COUNT,
            "delivery_file_count": group_count * DELIVERY_COUNT,
            "available_complete_groups": group_count,
        }
    )
    project["prompt_sources"] = prompt_sources
    project["group_registry"] = f"projects/{PROJECT_ID}/groups/registry.json"
    project["output_dir"] = f"output/{PROJECT_ID}"
    project["status"] = "sample_prompts_ready" if initial else "formal_batch_extended"
    _atomic_json(PROJECT_DIR / "project.json", project)


def _write_initial(
    project: dict[str, Any],
    registry: dict[str, Any],
    count: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    if count != 3:
        raise TruckRescueManifestError("货车新类目首次只允许建立第1至第3组三组样片清单")
    if int(registry.get("created_groups") or 0) != 0:
        raise TruckRescueManifestError("truck_rescue initial registry is not empty")
    managed_files = (
        GROUPS_DIR / "group_manifest.jsonl",
        GROUPS_DIR / "generation_manifest.jsonl",
        GROUPS_DIR / "production_manifest.jsonl",
        BATCH_DIR / "prompts.jsonl",
    )
    if any(path.is_file() and path.stat().st_size for path in managed_files):
        raise TruckRescueManifestError("truck_rescue initial manifests already contain data; refusing to overwrite")
    generation, deliveries, groups, registry_groups = _build_rows(1, count, 1, config)
    batch_manifest = _batch_manifest_rows(generation)
    summary = _summary(1, count)
    now = summary["updated_at"]
    new_registry = _registry(1, registry_groups, created_at=now)
    group_files = {
        "group_manifest.jsonl": _jsonl_text(groups),
        "generation_manifest.jsonl": _jsonl_text(generation),
        "production_manifest.jsonl": _jsonl_text(deliveries),
        "extension_history.jsonl": _jsonl_text(
            [
                {
                    "operation": "create_sample_manifests",
                    "group_start": 1,
                    "group_count": count,
                    "created_at": now,
                    "api_called": False,
                }
            ]
        ),
    }
    batch_files = {
        "prompts.jsonl": _jsonl_text(generation),
        "cover_prompts.jsonl": _jsonl_text([row for row in generation if row["generation_kind"] == "cover"]),
        "triptych_panel_prompts.jsonl": _jsonl_text([row for row in generation if row["generation_kind"] == "triptych_panel"]),
        "detail_prompts.jsonl": _jsonl_text([row for row in generation if row["generation_kind"] == "detail"]),
        "manifest.jsonl": _jsonl_text(batch_manifest),
        "delivery_manifest.jsonl": _jsonl_text(deliveries),
        "summary.json": json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        "README_THIS_BATCH.txt": (
            "货车救援维修 v3 活动清单\n\n"
            "每组交付5张：1张首图、1张由3个独立现场组成的三拼图、3张独立详情图。\n"
            "每组7个生成单元，六个现场严格覆盖六个不同货车故障角色。\n"
            "本批次只创建本地提示词与清单，没有调用图片接口，也没有生成图片。\n"
        ),
    }
    for name, value in group_files.items():
        _atomic_text(GROUPS_DIR / name, value)
    for name, value in batch_files.items():
        _atomic_text(BATCH_DIR / name, value)
    _atomic_json(REGISTRY_PATH, new_registry)
    _update_project(project, count, initial=True)
    return {
        "project_id": PROJECT_ID,
        "operation": "create_sample_manifests",
        "group_start": 1,
        "group_count": count,
        "generation_unit_count": len(generation),
        "delivery_file_count": len(deliveries),
        "historical_prefix_preserved": True,
        "api_called": False,
    }


def _write_extension(
    project: dict[str, Any],
    registry: dict[str, Any],
    count: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    if not _project_has_approved_samples(project):
        raise TruckRescueManifestError("货车三组首图样片尚未正式批准，不能继续扩组")
    existing_count = int(registry.get("created_groups") or 0)
    first_group = int(registry.get("first_group_index") or 1)
    last_group = int(registry.get("last_group_index") or 0)
    if existing_count < 3 or last_group != first_group + existing_count - 1:
        raise TruckRescueManifestError("truck_rescue registry range is inconsistent")
    group_names = ("group_manifest.jsonl", "generation_manifest.jsonl", "production_manifest.jsonl")
    batch_names = (
        "prompts.jsonl",
        "cover_prompts.jsonl",
        "triptych_panel_prompts.jsonl",
        "detail_prompts.jsonl",
        "manifest.jsonl",
        "delivery_manifest.jsonl",
    )
    old_group_bytes = {name: (GROUPS_DIR / name).read_bytes() for name in group_names}
    old_batch_bytes = {name: (BATCH_DIR / name).read_bytes() for name in batch_names}
    old_generation = _load_jsonl(GROUPS_DIR / "generation_manifest.jsonl")
    old_deliveries = _load_jsonl(GROUPS_DIR / "production_manifest.jsonl")
    old_groups = _load_jsonl(GROUPS_DIR / "group_manifest.jsonl")
    if len(old_generation) != existing_count * UNIT_COUNT:
        raise TruckRescueManifestError("truck_rescue generation manifest count is inconsistent")
    if len(old_deliveries) != existing_count * DELIVERY_COUNT:
        raise TruckRescueManifestError("truck_rescue production manifest count is inconsistent")
    if len(old_groups) != existing_count:
        raise TruckRescueManifestError("truck_rescue group manifest count is inconsistent")
    append_start = last_group + 1
    generation, deliveries, groups, registry_groups = _build_rows(
        append_start,
        count,
        max(int(row["index"]) for row in old_generation) + 1,
        config,
    )
    additions = {
        "group_manifest.jsonl": _jsonl_text(groups),
        "generation_manifest.jsonl": _jsonl_text(generation),
        "production_manifest.jsonl": _jsonl_text(deliveries),
    }
    batch_additions = {
        "prompts.jsonl": _jsonl_text(generation),
        "cover_prompts.jsonl": _jsonl_text([row for row in generation if row["generation_kind"] == "cover"]),
        "triptych_panel_prompts.jsonl": _jsonl_text([row for row in generation if row["generation_kind"] == "triptych_panel"]),
        "detail_prompts.jsonl": _jsonl_text([row for row in generation if row["generation_kind"] == "detail"]),
        "manifest.jsonl": _jsonl_text(_batch_manifest_rows(generation)),
        "delivery_manifest.jsonl": _jsonl_text(deliveries),
    }
    for name, addition in additions.items():
        current = old_group_bytes[name].decode("utf-8-sig")
        _atomic_text(GROUPS_DIR / name, _append_text(current, addition))
    for name, addition in batch_additions.items():
        current = old_batch_bytes[name].decode("utf-8-sig")
        _atomic_text(BATCH_DIR / name, _append_text(current, addition))
    now = datetime.now(timezone.utc).isoformat()
    all_registry_groups = list(registry.get("groups") or []) + registry_groups
    new_registry = _registry(
        first_group,
        all_registry_groups,
        created_at=str(registry.get("created_at") or now),
    )
    _atomic_json(REGISTRY_PATH, new_registry)
    total_count = existing_count + count
    _atomic_json(BATCH_DIR / "summary.json", _summary(first_group, total_count))
    history_path = GROUPS_DIR / "extension_history.jsonl"
    history = history_path.read_text(encoding="utf-8-sig") if history_path.is_file() else ""
    _atomic_text(
        history_path,
        _append_text(
            history,
            _jsonl_text(
                [
                    {
                        "operation": "extend_manifests",
                        "group_start": append_start,
                        "group_count": count,
                        "created_at": now,
                        "api_called": False,
                    }
                ]
            ),
        ),
    )
    _update_project(project, total_count, initial=False)
    for name, old in old_group_bytes.items():
        if not (GROUPS_DIR / name).read_bytes().startswith(old):
            raise TruckRescueManifestError(f"historical prefix changed: groups/{name}")
    for name, old in old_batch_bytes.items():
        if not (BATCH_DIR / name).read_bytes().startswith(old):
            raise TruckRescueManifestError(f"historical prefix changed: batch/{name}")
    return {
        "project_id": PROJECT_ID,
        "operation": "extend_manifests",
        "old_group_count": existing_count,
        "added_group_count": count,
        "new_group_start": append_start,
        "new_group_end": append_start + count - 1,
        "new_generation_units": len(generation),
        "old_prompts_sha256": _sha256_bytes(old_batch_bytes["prompts.jsonl"]),
        "new_prompts_sha256": _sha256_bytes((BATCH_DIR / "prompts.jsonl").read_bytes()),
        "historical_prefix_preserved": True,
        "api_called": False,
    }


def extend_truck_rescue_groups(count: int) -> dict[str, Any]:
    """Create the three sample groups or append approved formal groups locally."""

    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise TruckRescueManifestError("count must be a positive integer")
    _confirmed_phone_gate()
    if not CATEGORY_CONFIG_PATH.is_file() or not (PROJECT_DIR / "project.json").is_file():
        raise TruckRescueManifestError("truck_rescue static project files are incomplete")
    config = _load_json(CATEGORY_CONFIG_PATH)
    project = _load_json(PROJECT_DIR / "project.json")
    registry = _load_json(REGISTRY_PATH) if REGISTRY_PATH.is_file() else _registry(1, [])
    _structure(config)
    _confirmed_service_words_gate(project, config)
    if int(registry.get("created_groups") or 0) == 0:
        return _write_initial(project, registry, count, config)
    return _write_extension(project, registry, count, config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local truck-rescue v3 manifests")
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(extend_truck_rescue_groups(args.count), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
