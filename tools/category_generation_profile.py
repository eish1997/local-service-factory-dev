"""Explicit task-bound generation profiles; no credentials, I/O or networking."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


TINYSNOW_4K_DUAL_SOURCE = "tinysnow-4k-dual-source-v1"
PROFILE_IDS = (TINYSNOW_4K_DUAL_SOURCE,)
_SUPPORTED_CATEGORIES = frozenset({"truck_rescue", "road_rescue"})
_PROFILE = {
    "schema_version": 1,
    "id": TINYSNOW_4K_DUAL_SOURCE,
    "category_id": "truck_rescue",
    "provider": "relay",
    "base_url": "https://tinysnow.one/v1",
    "model": "gpt-image-2-4k",
    "quality": "medium",
    "api_size": "2560x3840",
    "working_raw_size": "1024x1536",
    "raw_contract": "tinysnow_2336_2352x3520_to_legacy_v1",
    "accepted_source_size": "2352x3520",
    "accepted_source_width_tolerance": 16,
    "accepted_source_sizes": ["2336x3520", "2352x3520"],
}


def validate_profile(value: Any, category_id: str) -> dict[str, Any]:
    expected = {**_PROFILE, "category_id": category_id}
    if (category_id not in _SUPPORTED_CATEGORIES
            or not isinstance(value, dict) or value != expected
            or type(value.get("schema_version")) is not int
            or type(value.get("accepted_source_width_tolerance")) is not int):
        raise ValueError("新任务生成profile无效、被篡改或与当前类目不匹配")
    return deepcopy(expected)


def select_profile(config: dict[str, Any], category_id: str, profile_id: str | None) -> dict[str, Any]:
    """Keep global config unchanged; override only an explicitly selected task."""
    if profile_id is None:
        if "generation_profile" in config or config.get("model") == _PROFILE["model"]:
            raise ValueError("新4K任务必须显式绑定generation-profile，不能隐式继承")
        return dict(config)
    if profile_id != TINYSNOW_4K_DUAL_SOURCE or category_id not in _SUPPORTED_CATEGORIES:
        raise ValueError("该generation-profile只支持已确认的TinySnow货车或道路救援任务")
    if (config.get("provider") != _PROFILE["provider"]
            or str(config.get("base_url", "")).rstrip("/") != _PROFILE["base_url"]):
        raise ValueError("新4K任务必须使用当前已配置的TinySnow线路，不允许隐式切换中转")
    result = dict(config)
    result.update({key: _PROFILE[key] for key in ("model", "quality", "api_size")})
    result["generation_profile"] = deepcopy(_PROFILE)
    result["generation_profile"]["category_id"] = category_id
    return result


def config_profile(config: dict[str, Any], category_id: str) -> dict[str, Any] | None:
    """Validate effective request parameters as well as the full frozen contract."""
    if "generation_profile" not in config:
        if config.get("model") == _PROFILE["model"]:
            raise ValueError("新4K任务缺少明确的generation-profile")
        return None
    profile = validate_profile(config["generation_profile"], category_id)
    if (any(config.get(key) != profile[key] for key in ("provider", "model", "quality", "api_size"))
            or str(config.get("base_url", "")).rstrip("/") != profile["base_url"]):
        raise ValueError("新4K任务有效模型、质量、尺寸或线路与profile不一致")
    return profile


def bindings(config: dict[str, Any], category_id: str) -> dict[str, Any]:
    profile = config_profile(config, category_id)
    return {"generation_profile": profile} if profile is not None else {}


def from_license(config: dict[str, Any], category_id: str, license_data: dict[str, Any]) -> dict[str, Any]:
    """Restore only the license-bound profile, never defaults from another job."""
    if "generation_profile" not in license_data:
        if license_data.get("model") == _PROFILE["model"]:
            raise ValueError("新4K许可证缺少generation-profile")
        return select_profile(config, category_id, None)
    profile = validate_profile(license_data["generation_profile"], category_id)
    result = select_profile(config, category_id, profile["id"])
    expected = {
        "category_id": category_id,
        "provider": result["provider"],
        "base_url": result.get("base_url", ""),
        "model": result["model"],
        "quality": result["quality"],
        "size": result["api_size"],
    }
    if any(license_data.get(key) != value for key, value in expected.items()):
        raise ValueError("新4K许可证与所绑定的有效生成参数不一致")
    return result


def event_metadata(config: dict[str, Any], category_id: str) -> dict[str, Any]:
    profile = config_profile(config, category_id)
    if profile is None:
        return {}
    return {
        "generation_profile_id": profile["id"],
        "model": profile["model"],
        "quality": profile["quality"],
        "api_size": profile["api_size"],
        "raw_api_size": profile["working_raw_size"],
        "raw_contract": profile["raw_contract"],
    }
