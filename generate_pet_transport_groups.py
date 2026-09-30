from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROJECT_ID = "pet_transport"
STRUCTURE_VERSION = "pet_transport_v1_1cover_5details"
GENERATION_MODE = "independent_delivery_images"
UNIT_COUNT = 6

DETAIL_ACTIONS = {
    "接宠交接": "工作人员与客户核对宠物和随行物品，猫位于关闭运输箱内或狗佩戴合身牵引装备，交接动作自然",
    "笼具检查": "工作人员检查运输笼门锁、通风孔、固定卡扣、吸水垫和饮水器，手部与器具接触关系真实",
    "安全装车": "停稳的普通服务车旁，工作人员用双手或笼具推车平稳搬运关闭运输笼并确认车内安置位置",
    "途中照护": "车辆安全停靠后，工作人员查看笼内宠物状态、饮水器、通风和垫材，不表现行驶中操作",
    "到达交接": "普通小区或门店入口处，工作人员把关闭运输笼平稳交给接收人并共同核对宠物状态",
    "车辆通风检查": "出发前工作人员检查普通服务车厢通风口、笼位间距和空气流通，车辆保持熄火停稳",
    "笼具固定": "工作人员在停稳车辆内使用合规固定带和防滑垫固定运输笼，锁扣、受力方向和笼门朝向清楚",
    "送达核对": "到达后工作人员与接收人核对宠物、运输笼和随行物品，动作克制且有真实照护感",
    "饮水状态检查": "安全停靠状态下，工作人员查看饮水余量、饮水器固定和宠物精神状态，不打开笼门摆拍",
    "牵引装备检查": "工作人员在门店入口检查狗狗胸背带、牵引绳和安全扣松紧，宠物姿态自然且不看镜头",
}

LOCATIONS = (
    "维护良好的较新社区底商门口",
    "普通城市小区落客区旁",
    "整洁的街边宠物托运小店入口",
    "县城主干道临街底商门前",
    "社区商业街玻璃店面外",
    "普通物流园生活服务门店旁",
    "住宅区转角沿街铺面门口",
    "门店后侧安全装车区域",
    "普通服务车侧门旁",
    "安静工作日上午的小区门口",
)

PET_CONTEXTS = (
    "一只成年猫安静待在尺寸合适的关闭运输箱内",
    "一只中型犬佩戴合身胸背带并由工作人员稳妥牵引",
    "一只小型犬位于结构正常的关闭运输笼内",
    "猫咪与狗狗不同时抢占画面，只保留一个明确服务对象",
    "宠物仅作为真实业务对象，不做大头特写或广告摆拍",
)

CAMERAS = (
    "普通手机眼平轻微侧拍，保留自然透视和环境边缘",
    "工作人员视角的中近景抓拍，人物不看镜头",
    "从车辆侧后方稍远拍摄，动作与环境关系完整",
    "轻微高角度手机随手拍，避免商业摄影和绝对对称",
    "从门店入口斜向拍摄，保留玻璃反光与街道纵深",
    "普通手机两倍焦段稍远记录，细节清楚但不过度锐化",
)

LIGHTING = (
    "阴天自然漫射光",
    "普通晴天但色彩不过度鲜艳",
    "雨后白天柔和环境光",
    "傍晚营业时间的普通室内外混合光",
    "上午自然侧光与真实手机自动曝光",
)


def _load_json(path: Path) -> dict[str, Any]:
    return runtime_paths.read_json(path)


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@variable_catalog.managed('pet_transport','detail')
def _detail_prompt(group_index: int, position: int, role: str) -> str:
    offset = (group_index - 1) * 5 + position - 2
    actions = DETAIL_ACTIONS[role]
    action = actions if isinstance(actions, str) else actions[offset % len(actions)]
    location = LOCATIONS[(offset * 3) % len(LOCATIONS)]
    pet_context = PET_CONTEXTS[(offset * 2) % len(PET_CONTEXTS)]
    camera = CAMERAS[(offset * 5) % len(CAMERAS)]
    lighting = LIGHTING[(offset * 4) % len(LIGHTING)]
    return (
        "真实中国本地宠物托运详情图源图，普通手机拍摄的工作记录，不是海报、插画、动漫、CG或门店效果图。"
        f"服务角色：{role}。场景位于{location}；{action}；{pet_context}。"
        f"拍摄方式：{camera}；光线：{lighting}。人物衣服、手部、笼具、固定带、牵引装备和车辆比例真实，"
        "保留轻微手机噪点、玻璃反光、地面灰尘和正常使用痕迹，但环境整洁精致、不破败、不豪华。"
        "顶部3.5%至10.5%留出简洁背景供本地添加角色标签；中部49%至58.5%留出横向背景供本地添加电话；"
        "底部83.5%至97.5%留出简洁背景供本地添加两行十宫格宠物托运服务词。"
        "原图不要生成任何电话号码、可读文字、品牌、价格、二维码、水印、可读车牌、按钮、卡片或宫格UI。"
        "严格排除机场航空宣传、铁路物流宣传、跨城跨省承诺、全国覆盖、时效、保险、赔付、危险装载、"
        "宠物惊恐受伤、畸形手指、畸形宠物、笼具穿模、汽修工具、轮胎和道路救援业务元素。"
    )


@variable_catalog.managed('pet_transport','$role',finish_result='always')
def _record(
    active_batch: str,
    group_index: int,
    generation_position: int,
    generation_kind: str,
    service_role: str | None,
    negative_prompt: str,
) -> dict[str, Any]:
    index = (group_index - 1) * UNIT_COUNT + generation_position
    filename = "01_cover.png" if generation_kind == "cover" else f"{generation_position:02d}_detail.png"
    record: dict[str, Any] = {
        "index": index,
        "category_id": PROJECT_ID,
        "group_index": group_index,
        "generation_position": generation_position,
        "delivery_position": generation_position,
        "generation_kind": generation_kind,
        "service_role": service_role,
        "structure_version": STRUCTURE_VERSION,
        "generation_mode": GENERATION_MODE,
        "height_profile_id": "full_1536",
        "final_size": "1024x1536",
        "raw_size": "1024x1536",
        "generation_id": f"{PROJECT_ID}:v1:g{group_index:04d}:u{generation_position:02d}",
        "raw_target": f"{active_batch}/raw/group_{group_index:04d}/{filename}",
        "negative_prompt": negative_prompt,
    }
    if generation_kind == "cover":
        record.update({
            "prompt": "写实中国宠物托运门店外景全景，运行时使用已批准的汽车救援门店纪实风格库并替换为宠物托运业务元素。",
            "cover_variant_signature": f"pet_transport_v3_extended_group_{group_index:04d}",
            "cover_variant": {
                "variant_id": f"pet-extended-{group_index:04d}",
                "scene": f"第{group_index}组较新整洁中国社区宠物托运门店外景全景",
                "source": "pet_transport_v3_extended_groups",
            },
        })
        from tools.category_image_production import _pet_transport_cover_prompt
        record['prompt'] = _pet_transport_cover_prompt(record, '{已确认电话}')
        record['catalog_prepared_prompt'] = True
    else:
        record["prompt"] = _detail_prompt(group_index, generation_position, str(service_role))
    return record


@variable_catalog.managed('pet_transport',finish_result=False)
def extend_pet_transport_groups(count: int) -> dict[str, Any]:
    if count < 1:
        raise ValueError("group count must be positive")
    project_path = ROOT / "projects" / PROJECT_ID / "project.json"
    registry_path = ROOT / "projects" / PROJECT_ID / "groups" / "registry.json"
    project = _load_json(project_path)
    registry = _load_json(registry_path)
    if project.get("references", {}).get("cover", {}).get("approved_style") is not True:
        raise RuntimeError("宠物托运首图风格尚未正式登记批准，不能扩组")
    active_batch = str(project.get("prompt_sources", {}).get("active_batch") or "").strip().replace("\\", "/")
    manifest_value = str(project.get("prompt_sources", {}).get("production_manifest") or "").strip()
    if not active_batch or not manifest_value:
        raise RuntimeError("宠物托运缺少活动批次或正式生产清单")
    prompts_path = ROOT / active_batch / "prompts.jsonl"
    manifest_path = ROOT / manifest_value
    prompt_bytes = prompts_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    if prompt_bytes != manifest_bytes:
        raise RuntimeError("活动提示词与正式生产清单不一致，停止扩组")
    old_records = [
        json.loads(line)
        for line in prompt_bytes.decode("utf-8-sig").splitlines()
        if line.strip()
    ]
    created_groups = int(registry.get("created_groups") or 0)
    if len(old_records) != created_groups * UNIT_COUNT:
        raise RuntimeError("历史宠物托运清单数量与 registry 不一致")
    expected_indices = list(range(1, created_groups + 1))
    actual_indices = sorted({int(row.get("group_index") or 0) for row in old_records})
    if actual_indices != expected_indices:
        raise RuntimeError("历史宠物托运组号不连续，停止扩组")
    category = _load_json(ROOT / "configs" / "categories" / "pet_transport.json")
    role_pool = list(category["image_group_structure"]["service_role_pool"])
    if len(role_pool) < 10 or len(set(role_pool)) != len(role_pool):
        raise RuntimeError("宠物托运 service_role_pool 至少需要10个互不重复角色")
    negative_prompt = str(category.get("negative_prompt") or "").strip()
    new_records: list[dict[str, Any]] = []
    first_new_group = created_groups + 1
    final_group = created_groups + count
    for group_index in range(first_new_group, final_group + 1):
        new_records.append(_record(active_batch, group_index, 1, "cover", None, negative_prompt))
        start = ((group_index - 1) * 3) % len(role_pool)
        roles = [role_pool[(start + offset) % len(role_pool)] for offset in range(5)]
        if len(set(roles)) != 5:
            raise RuntimeError(f"第 {group_index} 组详情角色发生重复")
        for generation_position, role in enumerate(roles, start=2):
            new_records.append(
                _record(active_batch, group_index, generation_position, "detail", role, negative_prompt)
            )
    old_text = prompt_bytes.decode("utf-8-sig")
    if old_text and not old_text.endswith("\n"):
        old_text += "\n"
    appended_text = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in new_records
    )
    new_text = old_text + appended_text
    _atomic_text(prompts_path, new_text)
    _atomic_text(manifest_path, new_text)
    now = datetime.now(timezone.utc).isoformat()
    registry["created_groups"] = final_group
    registry["next_group_index"] = final_group + 1
    registry["updated_at"] = now
    groups = list(registry.get("groups") or [])
    groups.extend({
        "group_index": group_index,
        "unit_count": UNIT_COUNT,
        "delivery_count": UNIT_COUNT,
        "status": "planned",
    } for group_index in range(first_new_group, final_group + 1))
    registry["groups"] = groups
    _atomic_json(registry_path, registry)
    project["prompt_sources"]["detail_prompt_count"] = final_group * 5
    project["prompt_sources"]["available_complete_detail_sets"] = final_group
    project["status"] = "formal_batch_extended"
    _atomic_json(project_path, project)
    new_bytes = prompts_path.read_bytes()
    if manifest_path.read_bytes() != new_bytes or not new_bytes.startswith(prompt_bytes):
        raise RuntimeError("扩组后历史 JSONL 前缀校验失败")
    return {
        "project_id": PROJECT_ID,
        "old_group_count": created_groups,
        "added_group_count": count,
        "new_group_start": first_new_group,
        "new_group_end": final_group,
        "new_generation_units": len(new_records),
        "old_prompts_sha256": _sha256(prompt_bytes),
        "new_prompts_sha256": _sha256(new_bytes),
        "historical_prefix_preserved": True,
        "api_called": False,
    }

