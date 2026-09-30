"""Deterministic, fictional storefront naming for truck-rescue covers."""

from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog

import json
import re
from pathlib import Path
from typing import Any

from tools.contact_numbers import contains_contact_number


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIBRARY_PATH = ROOT / "projects" / "truck_rescue" / "cover_scene_library.json"
NAMING_EPOCH_GROUP = 94

ALLOWED_INDUSTRY_SUFFIXES = {
    "货车维修救援",
    "卡车维修救援",
    "重卡维修救援",
    "大车维修救援",
    "货车救援维修",
}

# These are either real vehicle/service brands or high-collision names found
# during the naming review.  They may be discussed as examples but must not be
# selected as the fictional two-character signboard name.
FORBIDDEN_BRAND_NAMES = {
    "风驰",
    "安捷",
    "捷途",
    "途虎",
    "途安",
    "捷达",
    "东风",
    "解放",
    "欧曼",
    "重汽",
    "江淮",
    "福田",
    "陕汽",
    "潍柴",
    "红岩",
    "奥驰",
    "百援",
    "顺达",
    "速达",
    "安达",
    "迅达",
    "顺通",
    "畅通",
    "鑫达",
    "宏达",
    "安驰",
    "稳驰",
    "迅援",
    "劲途",
    "驭安",
    "擎途",
    "砺驰",
    "驰衡",
    "捷护",
}

_TWO_CHINESE_CHARACTERS = re.compile(r"[\u4e00-\u9fff]{2}")
class TruckRescueSignageError(ValueError):
    """Raised when the truck signboard naming library is unsafe or incomplete."""


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    values = payload.get(key)
    if not isinstance(values, list) or not values:
        raise TruckRescueSignageError(f"truck signage {key} must be a non-empty list")
    result = [str(value).strip() for value in values]
    if any(not value or contains_contact_number(value) for value in result):
        raise TruckRescueSignageError(f"truck signage {key} contains an empty value or phone")
    return result


def load_signage_library(path: Path = DEFAULT_LIBRARY_PATH) -> dict[str, Any]:
    payload = runtime_paths.read_json(path)
    if variable_catalog.CURRENT.get() and Path(path).resolve()==DEFAULT_LIBRARY_PATH.resolve():
        payload = variable_catalog.overlay_document("truck_rescue", payload, "projects/truck_rescue/cover_scene_library.json")
    raw_candidates = payload.get("brand_name_candidates")
    if not isinstance(raw_candidates, list) or len(raw_candidates) < 50:
        raise TruckRescueSignageError(
            "truck signage requires at least 50 fictional brand-name candidates"
        )

    candidates: list[dict[str, str]] = []
    names: set[str] = set()
    full_names: set[str] = set()
    for position, raw in enumerate(raw_candidates, 1):
        if not isinstance(raw, dict):
            raise TruckRescueSignageError(
                f"truck signage candidate {position} must be an object"
            )
        name = str(raw.get("name") or "").strip()
        meaning = str(raw.get("meaning") or "").strip()
        suffix = str(raw.get("suffix") or "").strip()
        if _TWO_CHINESE_CHARACTERS.fullmatch(name) is None:
            raise TruckRescueSignageError(
                f"truck signage candidate {position} must use exactly two Chinese characters"
            )
        if name in FORBIDDEN_BRAND_NAMES:
            raise TruckRescueSignageError(
                f"truck signage candidate {position} uses a forbidden/high-collision name: {name}"
            )
        if name in names:
            raise TruckRescueSignageError(f"duplicate truck signage name: {name}")
        if not meaning or contains_contact_number(meaning):
            raise TruckRescueSignageError(
                f"truck signage candidate {position} has an empty/unsafe meaning"
            )
        if suffix not in ALLOWED_INDUSTRY_SUFFIXES:
            raise TruckRescueSignageError(
                f"truck signage candidate {position} has an unsupported suffix: {suffix}"
            )
        full_name = name + suffix
        if full_name in full_names:
            raise TruckRescueSignageError(f"duplicate truck signage full name: {full_name}")
        names.add(name)
        full_names.add(full_name)
        candidates.append(
            {
                "brand_name": name,
                "brand_meaning": meaning,
                "industry_suffix": suffix,
                "full_store_name": full_name,
            }
        )

    return {
        "brand_name_candidates": candidates,
        "sign_information_layouts": _string_list(payload, "sign_information_layouts"),
        "sign_accent_details": _string_list(payload, "sign_accent_details"),
        "sign_installation_details": _string_list(payload, "sign_installation_details"),
    }


def signage_variant(
    group_index: int,
    path: Path = DEFAULT_LIBRARY_PATH,
) -> dict[str, str]:
    if group_index < NAMING_EPOCH_GROUP:
        raise TruckRescueSignageError(
            f"truck meaningful signage starts at group {NAMING_EPOCH_GROUP}"
        )
    library = load_signage_library(path)
    offset = group_index - NAMING_EPOCH_GROUP
    candidates = library["brand_name_candidates"]
    if offset >= len(candidates):
        last_supported = NAMING_EPOCH_GROUP + len(candidates) - 1
        raise TruckRescueSignageError(
            "truck signage candidates exhausted: "
            f"group {group_index} exceeds supported group {last_supported}"
        )
    candidate = dict(candidates[offset])
    context = variable_catalog.CURRENT.get()
    if context:
        for dimension in context['catalog']['dimensions']:
            forced = variable_catalog.FORCE.get().get(dimension['id'])
            if forced and dimension.get('binding', {}).get('path')==['brand_name_candidates']:
                name=next(o['value']['name'] for o in dimension['options'] if o['id']==forced)
                candidate=dict(next(c for c in candidates if c['brand_name']==name))
    layouts = library["sign_information_layouts"]
    accents = library["sign_accent_details"]
    installations = library["sign_installation_details"]
    if group_index >= 274:
        # New batches traverse layout/accent/installation pairs independently.
        # Preserve the original mapping for all previously prepared groups.
        future_offset = group_index - 274
        candidate.update(
            {
                "sign_information_layout": layouts[
                    (future_offset + future_offset // len(accents)) % len(layouts)
                ],
                "sign_accent_detail": accents[(future_offset * 5 + 1) % len(accents)],
                "sign_installation_detail": installations[
                    (future_offset * 5 + future_offset // len(accents) + 2)
                    % len(installations)
                ],
            }
        )
        return candidate
    candidate.update(
        {
            "sign_information_layout": layouts[(offset * 2) % len(layouts)],
            "sign_accent_detail": accents[(offset * 5 + 1) % len(accents)],
            "sign_installation_detail": installations[(offset * 5 + 2) % len(installations)],
        }
    )
    return candidate


SIGNAGE_FIELDS = (
    "brand_name",
    "brand_meaning",
    "industry_suffix",
    "full_store_name",
    "sign_information_layout",
    "sign_accent_detail",
    "sign_installation_detail",
)


def _validated_persisted_variant(raw: dict[str, Any], group_index: int) -> dict[str, str]:
    missing = [key for key in SIGNAGE_FIELDS if not str(raw.get(key) or "").strip()]
    if missing:
        raise TruckRescueSignageError(
            f"truck group {group_index} is missing persisted signage fields: {', '.join(missing)}"
        )
    result = {key: str(raw[key]).strip() for key in SIGNAGE_FIELDS}
    name = result["brand_name"]
    suffix = result["industry_suffix"]
    if _TWO_CHINESE_CHARACTERS.fullmatch(name) is None:
        raise TruckRescueSignageError(
            f"truck group {group_index} persisted brand name must use two Chinese characters"
        )
    if name in FORBIDDEN_BRAND_NAMES:
        raise TruckRescueSignageError(
            f"truck group {group_index} persisted brand name is forbidden/high-collision"
        )
    if suffix not in ALLOWED_INDUSTRY_SUFFIXES:
        raise TruckRescueSignageError(
            f"truck group {group_index} persisted industry suffix is unsupported"
        )
    if result["full_store_name"] != name + suffix:
        raise TruckRescueSignageError(
            f"truck group {group_index} persisted full store name is inconsistent"
        )
    if any(contains_contact_number(value) for value in result.values()):
        raise TruckRescueSignageError(
            f"truck group {group_index} persisted signage contains a phone"
        )
    return result


def resolve_signage_variant(
    record: dict[str, Any],
    path: Path = DEFAULT_LIBRARY_PATH,
) -> dict[str, str]:
    group_index = int(record.get("group_index") or 0)
    if group_index < NAMING_EPOCH_GROUP:
        raise TruckRescueSignageError(
            f"truck meaningful signage does not apply before group {NAMING_EPOCH_GROUP}"
        )
    cover_variant = record.get("cover_variant")
    if not isinstance(cover_variant, dict):
        scene = record.get("scene")
        cover_variant = scene if isinstance(scene, dict) else {}
    if all(str(cover_variant.get(key) or "").strip() for key in SIGNAGE_FIELDS):
        return _validated_persisted_variant(cover_variant, group_index)
    if group_index == NAMING_EPOCH_GROUP:
        return signage_variant(group_index, path)
    missing = [key for key in SIGNAGE_FIELDS if not str(cover_variant.get(key) or "").strip()]
    raise TruckRescueSignageError(
        f"truck group {group_index} must use persisted signage; missing: {', '.join(missing)}"
    )


def _balanced_hierarchy_text(variant: dict[str, str]) -> str:
    return (
        f"其中两字寓意字号“{variant['brand_name']}”与行业尾缀“{variant['industry_suffix']}”"
        "使用接近的正常实体字高（字高比例约0.95至1.05），放在同一基线、同一水平排版轴或"
        "紧密连续的同一主标题区；完整主名称应作为一个均衡整体，行业业务主题不得弱于两字字号；"
        f"字号含义为“{variant['brand_meaning']}”。"
    )


_LEGACY_LAYOUT_REPLACEMENTS = {
    "两字寓意字号位于上层或左侧且最大最醒目，行业尾缀紧随其后并次大，下层为六项服务小字，确认电话位于同一板面底部信息带":
        "完整主名称在同一水平主标题区连续排布，两字字号与行业尾缀使用接近的正常字高；下层为六项服务小字，确认电话位于同一板面底部信息带",
    "左侧约三成板面突出两字字号，右侧约七成排行业尾缀与确认电话，服务小字沿下沿横向排列，不做悬浮字幕":
        "完整主名称在同一水平主标题区连续排布，确认电话位于独立右侧联系区，服务小字沿下沿横向排列，不做悬浮字幕",
    "两字字号与行业尾缀组成上下两层完整主名称，服务小字和确认电话形成第三、第四层，文字留白自然":
        "两字字号与行业尾缀在同一水平主标题区连续组成完整主名称，服务小字和确认电话位于下层独立信息区，文字留白自然",
    "信息按建筑开间自然调整为两字字号、行业尾缀、服务项目、确认电话四层，不能排成网页按钮、广告海报或品牌VI":
        "信息按建筑开间自然调整为连续完整主名称、服务项目和确认电话三个信息层，不能拆散主名称，也不能排成网页按钮、广告海报或品牌VI",
    "转角门店正立面完整呈现两字字号加行业尾缀，侧立面只重复较小行业尾缀，两个面透视自然衔接":
        "转角门店正立面在同一水平主标题区完整连续呈现两字字号加行业尾缀，侧立面不重复第二标题，两个面透视自然衔接",
}


def normalize_signage_typography(text: str, variant: dict[str, str]) -> str:
    """Normalize legacy group prompts to the approved balanced title hierarchy."""

    old_hierarchy = (
        f"其中两字寓意字号“{variant['brand_name']}”最大或最醒目，"
        f"含义为“{variant['brand_meaning']}”，行业尾缀“{variant['industry_suffix']}”次大。"
    )
    normalized = text.replace(old_hierarchy, _balanced_hierarchy_text(variant))
    for old, new in _LEGACY_LAYOUT_REPLACEMENTS.items():
        normalized = normalized.replace(old, new)
    return normalized


def signage_override_text(variant: dict[str, str]) -> str:
    return (
        f"本组实体门头完整主名称只能清楚准确写成“{variant['full_store_name']}”，"
        f"不得出现第二店名；{_balanced_hierarchy_text(variant)}"
        f"信息排版采用：{variant['sign_information_layout']}；"
        f"克制装饰采用：{variant['sign_accent_detail']}；"
        f"真实安装细节采用：{variant['sign_installation_detail']}。"
        "任何版面变化都不得把两字字号做成巨型主视觉、独立Logo式色块或与行业尾缀左右高低错位。"
        "这是为图片批次人工合成的虚构称呼，不得把它表现为真实注册商标、连锁、授权、官方、原厂或品牌Logo。"
    )
