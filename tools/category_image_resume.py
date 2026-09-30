"""Read-only accounting for safely resuming a frozen category-image job.

This module deliberately has no production or network imports.  It validates
the immutable license-specific artifacts, reconstructs the per-target attempt
ledger, and returns a deterministic resume plan.  It never writes files and it
never calls an API.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

from tools.contact_numbers import extract_contact_numbers, is_canonical_contact_number
from tools import category_generation_profile
from tools import category_source_size_acceptance
from tools import image_download_receipts
from tools import truck_cover_typography


SCHEMA_VERSION = 1
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z")
_SAFE_TARGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST_STATUSES = {"request_reserved", "request_failed", "generated"}
_RAMP = (4, 6, 8, 10)
PROFILE_RESUME_POLICY = "adaptive_profile_probe_ramp_v1"
RECEIPT_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "image_download_receipts"


class ResumePlanError(RuntimeError):
    """Frozen evidence is inconsistent or insufficient for safe accounting."""


def _fail(message: str) -> None:
    raise ResumePlanError(message)


def _is_balance_failure(event: dict[str, Any]) -> bool:
    """Recognize current and frozen pre-fix insufficient-balance evidence."""

    if event.get("status") != "request_failed":
        return False
    if event.get("error_kind") == "balance_exhausted":
        return True
    if event.get("error_kind") != "non_retryable":
        return False
    error_text = str(event.get("error") or "").lower()
    is_http_403 = bool(re.search(r"\berror code:\s*403\b", error_text))
    is_legacy_balance = (
        "insufficient_balance" in error_text
        and "insufficient account balance" in error_text
    )
    is_relay_billing_balance = (
        "billing_error" in error_text and "insufficient balance" in error_text
    )
    return is_http_403 and (is_legacy_balance or is_relay_billing_balance)


def _is_image_download_failure(event: dict[str, Any]) -> bool:
    """Returned URLs are paid results, even in pre-fix retryable events."""
    return event.get("status") == "request_failed" and (
        event.get("error_kind") == "image_download_failed"
        or (event.get("response_kind") == "url" and event.get("error_stage")
            in {"image_download_open", "image_download_read"})
    )


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ResumePlanError(f"无法读取{label}：{path}") from error
    if not isinstance(value, dict):
        _fail(f"{label}必须是 JSON 对象：{path}")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as error:
        raise ResumePlanError(f"无法读取{label}：{path}") from error
    result: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ResumePlanError(f"{label}第 {number} 行不是有效 JSON") from error
        if not isinstance(value, dict):
            _fail(f"{label}第 {number} 行必须是 JSON 对象")
        result.append(value)
    if not result:
        _fail(f"{label}为空：{path}")
    return result


def _resolved_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        _fail(f"{label}不存在：{path}")
    return path


def _same_path(value: Any, expected: Path, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label}缺少路径")
    if Path(value).expanduser().resolve() != expected.resolve():
        _fail(f"{label}未绑定到冻结任务文件：{value}")


def _equal(left: Any, right: Any, label: str) -> None:
    if left != right:
        _fail(f"冻结证据字段不一致：{label}")


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        _fail(f"{label}必须是整数")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ResumePlanError(f"{label}必须是整数") from error
    if result < minimum or result != value:
        _fail(f"{label}必须是不小于 {minimum} 的整数")
    return result


def _safe_identifier(value: Any, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text):
        _fail(f"{label}不是安全标识符")
    return text


def _safe_target_identifier(value: Any, label: str) -> str:
    text = str(value or "")
    if not _SAFE_TARGET_ID.fullmatch(text) or ".." in text:
        _fail(f"{label}不是安全目标标识符")
    return text


def _require_sha256(value: Any, label: str) -> str:
    text = str(value or "")
    if not _HEX_SHA256.fullmatch(text):
        _fail(f"{label}不是有效 SHA-256")
    return text


def _relative_artifact_path(batch_dir: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label}缺少路径")
    raw = Path(value)
    resolved = raw.resolve() if raw.is_absolute() else (batch_dir / raw).resolve()
    if resolved != batch_dir and batch_dir not in resolved.parents:
        # Formal delivery targets live beside the batch hierarchy.  Only raw
        # artifacts are resolved through this helper.
        _fail(f"{label}越出批次目录：{value}")
    return resolved


def _generation_target_hash(rows: list[dict[str, Any]]) -> str:
    material = [
        {
            "generation_target_id": row["generation_target_id"],
            "delivery_target_id": row["delivery_target_id"],
            "group_index": int(row["group_index"]),
            "generation_position": int(row["generation_position"]),
            "delivery_position": int(row["delivery_position"]),
            "generation_kind": str(row["generation_kind"]),
            "service_role": row.get("service_role"),
            "panel_index": row.get("panel_index"),
            "height_profile_id": row.get("height_profile_id"),
            "final_size": str(row["final_size"]),
            "triptych_layout_id": row.get("triptych_layout_id"),
            "target": str(row["target"]),
            "raw_target": str(row["raw_target"]),
        }
        for row in rows
    ]
    return _canonical_sha256(material)


def _delivery_material(rows: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for row in rows:
        grouped.setdefault(str(row["delivery_target_id"]), []).append(row)
    material: list[dict[str, Any]] = []
    for delivery_id, units in grouped.items():
        units = sorted(units, key=lambda item: int(item["generation_position"]))
        first = units[0]
        kinds = {str(item["generation_kind"]) for item in units}
        if kinds == {"triptych_panel"}:
            panels = [item.get("panel_index") for item in units]
            if len(units) != 3 or panels != [1, 2, 3]:
                _fail(f"三拼成品绑定无效：{delivery_id}")
            delivery_kind = "triptych"
        elif len(units) == 1 and len(kinds) == 1:
            delivery_kind = next(iter(kinds))
        else:
            _fail(f"成品生成单元绑定无效：{delivery_id}")
        if len({str(item["final_size"]) for item in units}) != 1:
            _fail(f"成品尺寸绑定不一致：{delivery_id}")
        material.append(
            {
                "delivery_target_id": delivery_id,
                "group_index": int(first["group_index"]),
                "delivery_position": int(first["delivery_position"]),
                "delivery_kind": delivery_kind,
                "height_profile_id": first.get("height_profile_id"),
                "final_size": str(first["final_size"]),
                "triptych_layout_id": (
                    first.get("triptych_layout_id")
                    if delivery_kind == "triptych"
                    else None
                ),
                "target": str(first["target"]),
                "generation_target_ids": [
                    str(item["generation_target_id"]) for item in units
                ],
            }
        )
    return list(grouped), material


def _validate_phone_mode(
    license_data: dict[str, Any], overlay: dict[str, Any]
) -> None:
    """Recognize the evidenced frozen road/truck storefront phone contracts."""

    mode = license_data.get("phone_sent_to_model")
    if mode is False:
        return
    if mode is not True:
        _fail("冻结许可证 phone_sent_to_model 必须为明确布尔值")
    category_id = license_data.get("category_id")
    if category_id not in {"road_rescue", "truck_rescue"}:
        _fail("模型门头电话续跑仅支持已验证的道路/货车救援类目")
    expected_license = {
        "schema_version": 3,
        "production_schema_version": 3,
        "category_id": category_id,
        "structure_version": f"{category_id}_v3_1cover_1triptych_3details",
        "generation_mode": "independent_triptych_panels",
    }
    for key, expected in expected_license.items():
        _equal(license_data.get(key), expected, f"model_phone.license.{key}")
    if license_data.get("scope") not in {"covers", "all"}:
        _fail("模型门头电话模式只接受含首图的冻结任务")
    expected_overlay = {
        "schema_version": 4,
        "production_schema_version": 3,
        "signboard_overlay_scope": "model_generated_physical_signboard_phone",
        "cover_signboard_region_mode": "source_generated_physical_signboard_phone",
        "cover_overlay_style": (
            "source-generated-signboard-phone_no-local-signboard-overlay_"
            "rotating-high-contrast-typography"
        ),
        "signboard_title": None,
        "signboard_service_items": [],
        "cover_signboard_region": None,
    }
    if "generation_profile" in license_data:
        category_generation_profile.validate_profile(license_data["generation_profile"], str(license_data["category_id"]))
        if (category_id == "truck_rescue"
                and int(license_data["group_start"]) + int(license_data["group_count"]) > truck_cover_typography.FIRST_GROUP):
            expected_overlay["cover_overlay_style"] = "truck-cover-v3-full-per-group-plan"
    for key, expected in expected_overlay.items():
        if key not in overlay:
            _fail(f"模型门头电话叠字计划缺少字段：{key}")
        _equal(overlay[key], expected, f"model_phone.overlay.{key}")
    if overlay.get("signboard_overlay_enabled") is not False:
        _fail("模型门头电话不能同时启用本地门头叠字")


def _profile_resume_bindings(license_data, job, rows, overlay, events) -> dict[str, Any]:
    """Validate the exact new profile and every complete local layout, read-only."""
    if "generation_profile" not in license_data:
        if (license_data.get("model") == "gpt-image-2-4k" or "generation_profile" in job
                or any("generation_profile" in row for row in rows)):
            _fail("新4K续跑缺少完整generation_profile")
        return {}
    profile = category_generation_profile.validate_profile(license_data["generation_profile"], str(license_data["category_id"]))
    _equal(job.get("generation_profile"), profile, "job.generation_profile")
    for key, expected in (("provider", profile["provider"]), ("base_url", profile["base_url"]),
                          ("model", profile["model"]), ("quality", profile["quality"]), ("size", profile["api_size"])):
        actual = license_data.get(key)
        if key == "base_url":
            actual = str(actual or "").rstrip("/")
        _equal(actual, expected, "profile.license." + key)
    slots = license_data.get("api_key_slots")
    workers = license_data.get("max_workers")
    if (not isinstance(slots, list) or not slots or len(slots) != len(set(slots))
            or any(type(slot) is not int or slot < 1 for slot in slots)
            or type(workers) is not int or not 1 <= workers <= min(10, len(slots))
            or license_data.get("concurrency_policy") != "adaptive_ramp_v1"
            or license_data.get("sdk_max_retries") != 0):
        _fail("新4K续跑必须继承原adaptive上限、冻结槽位及SDK零重试")
    layouts = {}
    for row in rows:
        _equal(row.get("generation_profile"), profile, "manifest.generation_profile")
        _equal(row.get("raw_api_size"), profile["working_raw_size"], "manifest.raw_api_size")
        if (license_data["category_id"] == "truck_rescue" and row["generation_kind"] == "cover"
                and int(row["group_index"]) >= truck_cover_typography.FIRST_GROUP):
            layout = json.loads(json.dumps(truck_cover_typography.cover_plan(int(row["group_index"]))))
            _equal(row.get("cover_typography_plan"), layout, "manifest.cover_typography_plan")
            layouts[str(row["group_index"])] = layout
    if layouts:
        _equal(overlay.get("cover_styles_by_group"), layouts, "overlay.cover_styles_by_group")
    quarantined = set(job.get("quarantined_api_key_slots") or [])
    quarantined.update(event["api_key_slot"] for event in events if _is_balance_failure(event) and "api_key_slot" in event)
    if any(type(slot) is not int or slot not in slots for slot in quarantined):
        _fail("新4K续跑隔离槽位不属于原许可证")
    return {"generation_profile": profile, "profile_resume_policy": PROFILE_RESUME_POLICY,
            "profile_max_workers": workers, "profile_api_key_slots": list(slots),
            "profile_quarantined_api_key_slots": sorted(quarantined)}


def _validate_model_phone_prompt(row: dict[str, Any], phone: str, index: int) -> None:
    for key, expected in (("schema_version", 3), ("overlay_schema_version", 4)):
        _equal(row.get(key), expected, f"model_phone.manifest[{index}].{key}")
    kind = row.get("generation_kind")
    if kind not in {"cover", "triptych_panel", "detail"}:
        _fail(f"模型门头电话清单第 {index} 行生成类型无效")
    _equal(row.get("role"), kind, f"model_phone.manifest[{index}].role")
    for key in ("source_positive_prompt", "negative_prompt"):
        if not isinstance(row.get(key), str):
            _fail(f"模型门头电话清单第 {index} 行缺少 {key} 字符串")
        if extract_contact_numbers(row[key]):
            _fail(f"模型门头电话清单第 {index} 行 {key} 不应包含联系电话")
    prompt = str(row["effective_prompt"])
    expected_numbers = {phone} if kind == "cover" else set()
    if set(extract_contact_numbers(prompt)) != expected_numbers:
        _fail(f"模型门头电话清单第 {index} 行只能在首图注入已确认联系电话")
    if kind == "cover":
        phone_instruction = (
            "门头联系电话必须由图像模型作为真实实体招牌排版的一部分自然生成，"
            f"号码必须清楚准确写成“{phone}”"
        )
        phone_instructions = [phone_instruction]
        if row.get("category_id") == "road_rescue":
            phone_instructions.append(
                f"门头实体板面内只使用确认号码“{phone}”，号码完整清楚地处于原图上方百分之四十以内，"
                "中部百分之五十至六十是后期电话条区域，两处不能重叠。"
            )
        if not any(instruction in prompt for instruction in phone_instructions):
            _fail(f"模型门头电话清单第 {index} 行缺少冻结实体招牌号码指令")


def _validate_manifest(
    batch_dir: Path,
    rows: list[dict[str, Any]],
    job: dict[str, Any],
    license_data: dict[str, Any],
    overlay: dict[str, Any],
) -> tuple[list[str], list[str]]:
    category_id = str(license_data["category_id"])
    batch_id = str(license_data["batch_id"])
    structure_version = str(license_data["structure_version"])
    generation_mode = str(license_data["generation_mode"])
    model = str(license_data["model"])
    quality = str(license_data["quality"])
    size = str(license_data["size"])
    phone = str(license_data["phone"])
    group_start = int(license_data["group_start"])
    group_count = int(license_data["group_count"])
    expected_groups = set(range(group_start, group_start + group_count))
    target_ids: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        required = (
            "generation_target_id",
            "delivery_target_id",
            "group_index",
            "generation_position",
            "delivery_position",
            "generation_kind",
            "final_size",
            "target",
            "raw_target",
            "effective_prompt",
            "effective_prompt_sha256",
        )
        missing = [key for key in required if key not in row]
        if missing:
            _fail(f"冻结清单第 {index} 行缺少字段：{', '.join(missing)}")
        target_id = _safe_target_identifier(row["generation_target_id"], "generation_target_id")
        if target_id in seen:
            _fail(f"冻结清单含重复生成目标：{target_id}")
        seen.add(target_id)
        target_ids.append(target_id)
        fixed = {
            "category_id": category_id,
            "batch_id": batch_id,
            "structure_version": structure_version,
            "generation_mode": generation_mode,
            "model": model,
            "quality": quality,
            "size": size,
            "confirmed_phone": phone,
        }
        for key, expected in fixed.items():
            _equal(row.get(key), expected, f"manifest[{index}].{key}")
        group_index = _integer(row["group_index"], f"manifest[{index}].group_index", minimum=1)
        if group_index not in expected_groups:
            _fail(f"冻结清单第 {index} 行越出授权组范围")
        _equal(row.get("target_id"), target_id, f"manifest[{index}].target_id")
        _safe_target_identifier(row["delivery_target_id"], "delivery_target_id")
        effective_prompt = str(row["effective_prompt"])
        _equal(
            row["effective_prompt_sha256"],
            hashlib.sha256(effective_prompt.encode("utf-8")).hexdigest(),
            f"manifest[{index}].effective_prompt_sha256",
        )
        if license_data.get("phone_sent_to_model") is False and any(
            phone in str(row.get(key) or "")
            for key in ("effective_prompt", "source_positive_prompt", "negative_prompt")
        ):
            _fail(f"冻结清单第 {index} 行违反 phone_sent_to_model=false")
        if license_data.get("phone_sent_to_model") is True:
            _validate_model_phone_prompt(row, phone, index)
            if license_data["scope"] == "covers" and row["generation_kind"] != "cover":
                _fail("首图范围的模型门头电话清单不能包含详情目标")
        _relative_artifact_path(batch_dir, row["raw_target"], f"manifest[{index}].raw_target")
    if license_data.get("phone_sent_to_model") is True and not any(
        row["generation_kind"] == "cover" for row in rows
    ):
        _fail("模型门头电话冻结任务缺少首图目标")
    actual_groups = {int(row["group_index"]) for row in rows}
    if actual_groups != expected_groups:
        _fail("冻结清单没有完整覆盖许可证组范围")

    delivery_ids, delivery_material = _delivery_material(rows)
    generation_hash = _generation_target_hash(rows)
    delivery_hash = _canonical_sha256(delivery_material)
    pending_generation_hash = _canonical_sha256(target_ids)
    pending_delivery_hash = _canonical_sha256(delivery_ids)
    manifest_binding_hash = _canonical_sha256(rows)

    expected_generation_lists = (
        (license_data, "generation_target_ids"),
        (license_data, "approved_generation_target_ids"),
        (license_data, "pending_generation_target_ids"),
        (job, "pending_generation_target_ids"),
        (overlay, "generation_target_ids"),
        (overlay, "pending_generation_target_ids"),
    )
    for source, key in expected_generation_lists:
        _equal(source.get(key), target_ids, key)
    expected_delivery_lists = (
        (license_data, "delivery_target_ids"),
        (license_data, "approved_delivery_target_ids"),
        (license_data, "pending_delivery_target_ids"),
        (job, "pending_delivery_target_ids"),
        (overlay, "delivery_target_ids"),
        (overlay, "pending_delivery_target_ids"),
    )
    for source, key in expected_delivery_lists:
        _equal(source.get(key), delivery_ids, key)

    for source, label in ((license_data, "license"), (job, "job"), (overlay, "overlay")):
        _equal(source.get("generation_targets_sha256"), generation_hash, f"{label}.generation_targets_sha256")
        _equal(source.get("delivery_targets_sha256"), delivery_hash, f"{label}.delivery_targets_sha256")
    _equal(license_data.get("manifest_sha256"), manifest_binding_hash, "license.manifest_sha256")
    _equal(
        license_data.get("pending_generation_targets_sha256"),
        pending_generation_hash,
        "license.pending_generation_targets_sha256",
    )
    _equal(
        license_data.get("pending_delivery_targets_sha256"),
        pending_delivery_hash,
        "license.pending_delivery_targets_sha256",
    )
    _equal(
        overlay.get("generation_targets_sha256"), generation_hash, "overlay.generation_targets_sha256"
    )
    _equal(overlay.get("delivery_targets_sha256"), delivery_hash, "overlay.delivery_targets_sha256")
    _equal(license_data.get("targets_sha256"), delivery_hash, "license.targets_sha256")
    for key in ("approved_targets_sha256", "pending_targets_sha256"):
        _equal(license_data.get(key), pending_delivery_hash, f"license.{key}")
    _equal(
        license_data.get("approved_targets_sha256"),
        license_data.get("pending_delivery_targets_sha256"),
        "approved/pending delivery target binding",
    )
    _equal(_canonical_sha256(license_data.get("group_recipes")), license_data.get("group_recipes_sha256"), "license.group_recipes_sha256")
    _equal(overlay.get("group_recipes"), license_data.get("group_recipes"), "overlay.group_recipes")
    _equal(overlay.get("group_recipes_sha256"), license_data.get("group_recipes_sha256"), "overlay.group_recipes_sha256")
    return target_ids, delivery_ids


def _validate_fixed_evidence(
    batch_dir: Path,
    job_path: Path,
    license_path: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    Path,
    list[dict[str, Any]],
    Path,
    dict[str, Any],
    Path,
    list[dict[str, Any]],
]:
    production = batch_dir / "production"
    if batch_dir.name.startswith("batch_") is False or not batch_dir.is_dir():
        _fail(f"无效批次目录：{batch_dir}")
    if job_path.parent != (production / "jobs").resolve():
        _fail("任务文件不在批次 production/jobs 目录")
    if license_path.parent != (production / "licenses").resolve():
        _fail("许可证文件不在批次 production/licenses 目录")
    job = _load_json(job_path, "任务文件")
    license_data = _load_json(license_path, "许可证")
    job_id = _safe_identifier(job.get("job_id"), "job_id")
    license_id = _safe_identifier(license_data.get("license_id"), "license_id")
    _equal(job_path.name, f"{job_id}.json", "job filename")
    _equal(license_path.name, f"{license_id}.json", "license filename")
    _equal(job.get("license_id"), license_id, "job.license_id")
    _equal(job.get("job_type"), "category-batch-production", "job.job_type")
    _equal(license_data.get("kind"), "category-image-production", "license.kind")
    if license_data.get("one_time") is not True or license_data.get("status") != "consumed":
        _fail("只允许核算已消费的一次性生产许可证")
    if not license_data.get("consumed_at"):
        _fail("已消费许可证缺少 consumed_at")
    _same_path(job.get("batch_dir"), batch_dir, "job.batch_dir")
    _same_path(license_data.get("batch_dir"), batch_dir, "license.batch_dir")

    fixed_keys = (
        "category_id",
        "batch_id",
        "group_start",
        "group_count",
        "scope",
        "generation_target_id",
        "plan_sha256",
        "structure_version",
        "generation_mode",
        "generation_targets_sha256",
        "delivery_targets_sha256",
        "model",
        "quality",
        "size",
        "max_attempts",
        "retry_policy",
        "concurrency_policy",
    )
    for key in fixed_keys:
        _equal(job.get(key), license_data.get(key), key)
    _equal(job.get("project_id"), license_data.get("category_id"), "job.project_id")
    _equal(job.get("batch_id"), batch_dir.name, "batch_id")
    group_start = _integer(license_data.get("group_start"), "group_start", minimum=1)
    group_count = _integer(license_data.get("group_count"), "group_count", minimum=1)
    del group_start, group_count
    plan_sha = _require_sha256(license_data.get("plan_sha256"), "plan_sha256")
    del plan_sha
    provider = str(license_data.get("provider") or "")
    if not provider:
        _fail("许可证缺少 provider")
    if provider == "relay":
        if license_data.get("third_party_confirmed") is not True:
            _fail("中转许可证缺少第三方信任确认")
        if not str(license_data.get("base_url") or "").startswith("https://"):
            _fail("中转许可证 base_url 无效")
    phone = str(license_data.get("phone") or "")
    if not is_canonical_contact_number(phone):
        _fail("许可证联系电话不是已确认的中国大陆手机或400服务号码格式")
    _equal(
        license_data.get("contact_sha256"),
        hashlib.sha256(phone.encode("utf-8")).hexdigest(),
        "contact_sha256",
    )
    manifest_path = (production / "manifests" / f"{license_id}.jsonl").resolve()
    overlay_path = (production / "overlay_plans" / f"{license_id}.json").resolve()
    events_path = (production / f"events_{job_id}.jsonl").resolve()
    _same_path(license_data.get("production_manifest"), manifest_path, "production_manifest")
    _same_path(license_data.get("overlay_plan"), overlay_path, "overlay_plan")
    if not manifest_path.is_file() or not overlay_path.is_file() or not events_path.is_file():
        _fail("冻结任务缺少专属 manifest、overlay 或 events 文件")
    rows = _load_jsonl(manifest_path, "冻结清单")
    overlay = _load_json(overlay_path, "叠字计划")
    events = _load_jsonl(events_path, "任务事件")

    overlay_fixed = (
        "category_id",
        "license_id",
        "scope",
        "plan_sha256",
        "structure_version",
        "generation_mode",
    )
    for key in overlay_fixed:
        _equal(overlay.get(key), license_data.get(key), f"overlay.{key}")
    _equal(overlay.get("phone"), phone, "overlay.phone")
    _equal(overlay.get("center_phone_text"), f"电话：{phone}", "overlay.center_phone_text")
    _equal(overlay.get("signboard_phone_text"), f"联系电话：{phone}", "overlay.signboard_phone_text")

    _validate_phone_mode(license_data, overlay)
    _validate_manifest(batch_dir, rows, job, license_data, overlay)
    _profile_resume_bindings(license_data, job, rows, overlay, events)
    return (
        job,
        license_data,
        manifest_path,
        rows,
        overlay_path,
        overlay,
        events_path,
        events,
    )


def _event_identity(event: dict[str, Any], row: dict[str, Any], number: int) -> None:
    required = (
        "delivery_target_id",
        "group_index",
        "generation_position",
        "delivery_position",
    )
    for key in required:
        _equal(event.get(key), row.get(key), f"events[{number}].{key}")
    status = event.get("status")
    if status in {"request_reserved", "generated"}:
        _equal(event.get("raw_target"), row.get("raw_target"), f"events[{number}].raw_target")
        _equal(event.get("delivery_target"), row.get("target"), f"events[{number}].delivery_target")


def _validate_stages(
    events: list[dict[str, Any]], job: dict[str, Any], target_ids: list[str]
) -> tuple[int, int]:
    event_stages = [event for event in events if event.get("status") == "concurrency_stage"]
    job_stages = job.get("concurrency_history")
    if not isinstance(job_stages, list):
        _fail("任务文件缺少 concurrency_history")
    if len(event_stages) != len(job_stages):
        _fail("任务与事件的并发阶段数量不一致")
    keys = (
        "stage",
        "phase",
        "worker_count",
        "request_count",
        "failed_count",
        "api_requests_used_total",
        "retry_count_total",
    )
    completed_targets = 0
    previous_total = 0
    for index, (event, recorded) in enumerate(zip(event_stages, job_stages), start=1):
        for key in keys:
            _equal(event.get(key), recorded.get(key), f"concurrency_history[{index}].{key}")
        _equal(event.get("stage"), index, f"concurrency stage {index}")
        count = _integer(event.get("request_count"), "stage.request_count", minimum=1)
        workers = _integer(event.get("worker_count"), "stage.worker_count", minimum=1)
        if count != workers:
            _fail("已完成并发阶段的 request_count 与 worker_count 不一致")
        completed_targets += count
        if completed_targets > len(target_ids):
            _fail("并发阶段覆盖目标数越出冻结清单")
        total = _integer(event.get("api_requests_used_total"), "stage.api_requests_used_total")
        if total < previous_total:
            _fail("并发阶段请求累计数倒退")
        previous_total = total
    return completed_targets, previous_total


def _next_legacy_stage_width(
    job: dict[str, Any], completed_stages: list[dict[str, Any]], remaining: int
) -> int:
    if remaining <= 0:
        return 0
    max_workers = _integer(job.get("max_worker_count"), "job.max_worker_count", minimum=1)
    policy = str(job.get("concurrency_policy") or "")
    if not completed_stages:
        # Every production run starts with a one-target probe.
        return 1
    first = completed_stages[0]
    if first.get("phase") != "probe" or int(first.get("request_count", 0)) != 1:
        _fail("旧事件无法确认单目标探针阶段")
    if int(first.get("failed_count", 0)):
        return 0
    if policy == "fixed_10_after_probe_v1":
        return min(max_workers, remaining)
    if policy not in {"adaptive_ramp_v1", "legacy_fixed"}:
        _fail(f"不支持推导旧事件并发策略：{policy}")
    worker_limit = max_workers
    desired = min(_RAMP[0], worker_limit)
    degraded = False
    remaining_at_stage = remaining + sum(
        int(stage.get("request_count", 0)) for stage in completed_stages[1:]
    )
    for stage in completed_stages[1:]:
        if stage.get("phase") != "adaptive":
            _fail("旧事件自适应阶段 phase 无法验证")
        expected_workers = min(desired, remaining_at_stage)
        if int(stage.get("worker_count", 0)) != expected_workers:
            _fail("旧事件并发宽度与自适应调度规则不一致")
        stage_workers = int(stage["worker_count"])
        remaining_at_stage -= stage_workers
        if int(stage.get("failed_count", 0)):
            degraded = True
            desired = min(worker_limit, 5 if stage_workers >= 6 else 2)
        elif not degraded:
            desired = worker_limit
            for candidate in _RAMP:
                if candidate > stage_workers:
                    desired = min(worker_limit, candidate)
                    break
    last = completed_stages[-1]
    if last.get("circuit_breaker_triggered") is True:
        return 0
    return min(desired, remaining)


def _provider_recovery_source(
    batch_dir: Path, rows: list[dict[str, Any]], events: list[dict[str, Any]],
    job: dict[str, Any], license_data: dict[str, Any], request_number: int,
    accepted_source_size: str, accepted_source_width_tolerance: int = 0,
) -> dict[str, Any]:
    """Read-only, narrowly scoped evidence for an accepted archived response."""

    if accepted_source_size != "2352x3520":
        _fail("本地源图恢复只接受本次明确确认的 2352x3520")
    if type(accepted_source_width_tolerance) is not int or accepted_source_width_tolerance not in (0, 16):
        _fail("本地源图恢复宽度容差只能为明确确认的0或16")
    widened = accepted_source_width_tolerance == 16
    previous_contract = "tinysnow_2352x3520_to_legacy_v1" if widened else "tinysnow_4k_to_legacy_v1"
    actual_source_size = "2336x3520" if widened else "2352x3520"
    recovery_contract = ("tinysnow_2336_2352x3520_to_legacy_v1" if widened
                         else "tinysnow_2352x3520_to_legacy_v1")
    matches = [event for event in events if event.get("status") == "request_failed"
               and event.get("request_number") == request_number]
    if len(matches) != 1:
        _fail("本地源图恢复必须绑定唯一失败请求")
    failed = matches[0]
    if (failed.get("error_kind") != "non_retryable" or failed.get("will_retry") is not False
            or failed.get("raw_contract") != previous_contract
            or failed.get("archive_status") != "rejected"
            or failed.get("source_returned_size") != actual_source_size):
        _fail("本地源图恢复只能处理已归档的本次4K尺寸契约失败")
    matching_rows = [row for row in rows
                     if row["generation_target_id"] == failed.get("generation_target_id")]
    if len(matching_rows) != 1:
        _fail("本地源图恢复目标不属于冻结清单")
    row = matching_rows[0]
    _event_identity(failed, row, request_number)
    later = [event for event in events if event.get("status") in _REQUEST_STATUSES
             and event.get("generation_target_id") == row["generation_target_id"]
             and int(event.get("attempt", 0)) > int(failed["attempt"])]
    if later:
        _fail("失败目标已经有后续请求，不能回收旧源图")
    authorization_id = _safe_identifier(failed.get("authorization_id"), "恢复授权")
    starts = [event for event in events if event.get("status") == "resume_started"]
    if not starts or starts[-1].get("authorization_id") != authorization_id:
        _fail("源图恢复必须绑定最后启动的续跑授权")
    authorization_path = batch_dir / "production" / "resume_authorizations" / f"{authorization_id}.json"
    authorization = _load_json(authorization_path, "源图原续跑授权")
    for key, expected in {
        "authorization_id": authorization_id, "job_id": job["job_id"],
        "license_id": license_data["license_id"], "category_id": license_data["category_id"],
        "batch_id": license_data["batch_id"], "status": "consumed", "one_time": True,
        "kind": "category-image-resume-authorization", "generation_migration_confirmed": True,
        "resume_plan_sha256": failed.get("resume_plan_sha256"),
    }.items():
        _equal(authorization.get(key), expected, f"source_recovery.authorization.{key}")
    migration = authorization.get("generation_migration")
    if (not isinstance(migration, dict) or not isinstance(migration.get("new_generation"), dict)
            or migration["new_generation"].get("model") != "gpt-image-2-4k"
            or not authorization.get("consumed_at")):
        _fail("源图恢复缺少已消费的4K迁移授权")
    if widened and (
        migration.get("raw_contract") != previous_contract
        or migration.get("accepted_source_size") != accepted_source_size
        or type(migration.get("accepted_source_width_tolerance", 0)) is not int
        or migration.get("accepted_source_width_tolerance", 0) != 0
    ):
        _fail("宽度恢复必须承接原精确2352尺寸迁移授权")
    source = _relative_artifact_path(batch_dir, failed.get("provider_original"), "provider_original")
    archive_root = (batch_dir / "production" / "provider_originals" / job["job_id"]).resolve()
    if archive_root not in source.parents:
        _fail("恢复源图越出当前任务归档目录")
    source_sha = _require_sha256(failed.get("source_sha256"), "source_sha256")
    if not source.is_file() or _file_sha256(source) != source_sha:
        _fail("恢复源图缺失或哈希不一致")
    metadata_path = source.with_name(source.name + ".json")
    metadata = _load_json(metadata_path, "原拒绝源图侧车")
    for key, expected in {
        "source_sha256": source_sha, "source_returned_size": actual_source_size,
        "source_format": "PNG", "archive_status": "rejected", "normalized": False,
        "raw_contract": failed["raw_contract"], "model": "gpt-image-2-4k",
        "quality": migration["new_generation"].get("quality"),
        "api_size": migration["new_generation"].get("api_size"),
        "rejection_reason": ("expected exact source pixels 2352x3520" if widened
                             else "expected portrait near-2:3 pixels with long edge 3840 or 4096"),
        "credential_epoch": migration.get("credential_epoch"),
    }.items():
        _equal(metadata.get(key), expected, f"source_recovery.metadata.{key}")
    if widened:
        _equal(metadata.get("accepted_source_size"), accepted_source_size, "source_recovery.previous_accepted_size")
        if (type(metadata.get("accepted_source_width_tolerance", 0)) is not int
                or metadata.get("accepted_source_width_tolerance", 0) != 0):
            _fail("原拒绝侧车不是零宽度容差的精确尺寸契约")
    from PIL import Image

    try:
        with Image.open(source) as image:
            expected_pixels = (2336, 3520) if widened else (2352, 3520)
            if image.format != "PNG" or image.size != expected_pixels:
                _fail("已归档响应实际像素与本次明确接受尺寸不符")
            image.verify()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ResumePlanError("恢复源图不是完整可解码PNG") from error
    return {
        "failed": failed, "row": row, "authorization": authorization,
        "authorization_path": authorization_path, "source": source,
        "metadata": metadata, "metadata_path": metadata_path,
        "recovery_contract": recovery_contract, "actual_source_size": actual_source_size,
        "accepted_source_width_tolerance": accepted_source_width_tolerance,
    }


def _validated_provider_source_recoveries(
    batch_dir: Path, rows: list[dict[str, Any]], events: list[dict[str, Any]],
    job: dict[str, Any], license_data: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    recovered: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(events):
        if event.get("status") != "provider_source_recovered":
            continue
        evidence = _provider_recovery_source(
            batch_dir, rows, events[:index], job, license_data,
            _integer(event.get("request_number"), "恢复请求编号", minimum=1),
            str(event.get("accepted_source_size") or ""),
            event.get("accepted_source_width_tolerance", 0),
        )
        failed, row = evidence["failed"], evidence["row"]
        target_id = row["generation_target_id"]
        if target_id in recovered:
            _fail("同一目标存在重复本地源图恢复事件")
        _event_identity(event, row, index + 1)
        for key, expected in {
            "job_id": job["job_id"], "license_id": license_data["license_id"],
            "generation_target_id": target_id, "authorization_id": failed["authorization_id"],
            "attempt": failed["attempt"], "failed_event_sha256": _canonical_sha256(failed),
            "original_authorization_sha256": _canonical_sha256(evidence["authorization"]),
            "provider_original_metadata_sha256": _file_sha256(evidence["metadata_path"]),
            "provider_original": failed["provider_original"], "source_sha256": failed["source_sha256"],
            "raw_target": row["raw_target"], "delivery_target": row["target"],
            "local_recovery_confirmed": True, "api_called": False, "request_delta": 0,
        }.items():
            _equal(event.get(key), expected, f"source_recovery.{key}")
        raw = _relative_artifact_path(batch_dir, row["raw_target"], "恢复工作原图")
        raw_sha = _require_sha256(event.get("saved_raw_sha256"), "恢复工作原图SHA")
        if not raw.is_file() or _file_sha256(raw) != raw_sha:
            _fail("恢复工作原图缺失或哈希不一致")
        recovery_metadata = _relative_artifact_path(batch_dir, event.get("recovery_metadata"), "恢复侧车")
        if (recovery_metadata.parent != evidence["source"].parent
                or not recovery_metadata.name.startswith(
                    evidence["source"].name + "." + evidence["recovery_contract"] + ".")
                or recovery_metadata.suffix != ".json"
                or not recovery_metadata.is_file()
                or _file_sha256(recovery_metadata) != _require_sha256(
                    event.get("recovery_metadata_sha256"), "恢复侧车SHA")):
            _fail("恢复侧车路径或哈希不一致")
        saved = _load_json(recovery_metadata, "恢复成功侧车")
        for key, expected in {
            "raw_contract": evidence["recovery_contract"],
            "accepted_source_size": "2352x3520", "source_returned_size": evidence["actual_source_size"],
            "source_sha256": failed["source_sha256"], "saved_raw_sha256": raw_sha,
            "normalized": True, "archive_status": "normalized", "normalized_to": "1024x1536",
            "source_is_upscaled_by_factory": False,
            "normalization_anchor_y": 0.0 if row.get("generation_kind") == "cover" else 0.5,
            "model": "gpt-image-2-4k",
            "credential_epoch": evidence["authorization"]["generation_migration"]["credential_epoch"],
        }.items():
            _equal(saved.get(key), expected, f"source_recovery.saved.{key}")
        if (type(saved.get("accepted_source_width_tolerance", 0)) is not int
                or saved.get("accepted_source_width_tolerance", 0) != evidence["accepted_source_width_tolerance"]):
            _fail("恢复成功侧车的明确宽度容差与恢复事件不一致")
        _same_path(saved.get("provider_original"), evidence["source"], "恢复源图绑定")
        _same_path(saved.get("prior_provider_original_metadata"), evidence["metadata_path"], "原拒绝侧车绑定")
        from PIL import Image

        try:
            with Image.open(raw) as image:
                if image.format != "PNG" or image.size != (1024, 1536):
                    _fail("恢复工作原图不是既定1024x1536 PNG")
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            raise ResumePlanError("恢复工作原图无法验证") from error
        recovered[target_id] = event
    return recovered


def _account_attempts(
    batch_dir: Path,
    rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    job: dict[str, Any],
    license_data: dict[str, Any],
    source_size_acceptance: dict[str, Any] | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
    target_ids = [str(row["generation_target_id"]) for row in rows]
    row_by_id = {str(row["generation_target_id"]): row for row in rows}
    max_attempts = _integer(license_data.get("max_attempts"), "max_attempts", minimum=1)
    if max_attempts not in {1, 2}:
        _fail("恢复账本只支持每目标最多 1 或 2 次尝试")
    reservations: dict[str, dict[int, dict[str, Any]]] = {target: {} for target in target_ids}
    terminals: dict[str, dict[int, dict[str, Any]]] = {target: {} for target in target_ids}
    legacy_terminals: dict[str, dict[int, dict[str, Any]]] = {
        target: {} for target in target_ids
    }
    request_numbers: list[int] = []
    explicit_epoch = False

    for number, event in enumerate(events, start=1):
        status = event.get("status")
        if status not in _REQUEST_STATUSES:
            continue
        target_id = str(event.get("generation_target_id") or "")
        if target_id not in row_by_id:
            _fail(f"事件第 {number} 行引用未授权目标：{target_id}")
        attempt = _integer(event.get("attempt"), f"events[{number}].attempt", minimum=1)
        prior_balance_failures = sum(
            1
            for terminal in terminals[target_id].values()
            if _is_balance_failure(terminal)
        )
        if attempt - prior_balance_failures > max_attempts:
            _fail(f"事件第 {number} 行超过每目标最大尝试次数")
        _event_identity(event, row_by_id[target_id], number)
        if status == "request_reserved":
            explicit_epoch = True
            if attempt in reservations[target_id]:
                _fail(f"目标 {target_id} 第 {attempt} 次请求重复预留")
            reservations[target_id][attempt] = event
            request_numbers.append(
                _integer(event.get("request_number"), f"events[{number}].request_number", minimum=1)
            )
        else:
            request_number_value = event.get("request_number")
            if explicit_epoch:
                if request_number_value is None:
                    _fail("显式预留时期之后出现了没有 request_number 的旧式结果事件")
                reservation = reservations[target_id].get(attempt)
                if reservation is None:
                    _fail("显式预留时期的结果事件缺少同目标同尝试的 request_reserved")
                _equal(
                    _integer(
                        request_number_value,
                        f"events[{number}].request_number",
                        minimum=1,
                    ),
                    reservation.get("request_number"),
                    f"events[{number}].request_number binding",
                )
            else:
                if request_number_value is not None:
                    _fail("首次 request_reserved 之前出现带 request_number 的结果事件")
                legacy_terminals[target_id][attempt] = event
            if attempt in terminals[target_id]:
                _fail(f"目标 {target_id} 第 {attempt} 次请求有重复结果事件")
            terminals[target_id][attempt] = event
            if status == "generated":
                raw_path = _relative_artifact_path(
                    batch_dir, row_by_id[target_id]["raw_target"], "generated.raw_target"
                )
                if not raw_path.is_file():
                    _fail(f"成功事件缺少原图文件：{raw_path}")
                saved_hash = _require_sha256(event.get("saved_raw_sha256"), "saved_raw_sha256")
                if _file_sha256(raw_path) != saved_hash:
                    _fail(f"成功原图哈希不一致：{target_id}")
            else:
                if not isinstance(event.get("will_retry"), bool):
                    _fail(f"失败事件缺少 will_retry 布尔值：{target_id}")
                if (
                    attempt - prior_balance_failures == max_attempts
                    and event.get("will_retry") is True
                ):
                    _fail(f"失败事件在最大尝试次数后仍声明重试：{target_id}")

    recovered = _validated_provider_source_recoveries(batch_dir, rows, events, job, license_data)
    accepted_recoveries = category_source_size_acceptance.validated_recoveries(
        batch_dir, rows, events, job, license_data, source_size_acceptance,
    )
    if set(recovered).intersection(accepted_recoveries):
        _fail("同一目标存在重复的源图恢复证据")
    recovered.update(accepted_recoveries)
    requests_used = _integer(license_data.get("requests_used"), "license.requests_used")
    if request_numbers:
        explicit_start = min(request_numbers)
        if sorted(request_numbers) != list(range(explicit_start, requests_used + 1)):
            _fail("显式 request_number 未从旧账本边界连续递增到 requests_used")
        legacy_requests_used = explicit_start - 1
    else:
        legacy_requests_used = requests_used

    if any(legacy_terminals[target] for target in target_ids):
        # Legacy workers wrote only terminal request events.  Completed stages
        # establish the scheduled prefix; at most the uniquely determined next
        # stage may contain interrupted requests without terminal events.
        completed_count, completed_request_total = _validate_stages(events, job, target_ids)
        completed_stages = [
            event for event in events if event.get("status") == "concurrency_stage"
        ]
        for target_id in target_ids[:completed_count]:
            attempts = legacy_terminals[target_id]
            if not attempts:
                _fail("已完成并发阶段存在无结果目标")
            last = attempts[max(attempts)]
            if last.get("status") != "generated" and last.get("will_retry") is not False and not _is_image_download_failure(last):
                _fail("已完成并发阶段存在未闭合的重试目标")
        known_completed_attempts = sum(
            len(legacy_terminals[target_id]) for target_id in target_ids[:completed_count]
        )
        if known_completed_attempts != completed_request_total:
            _fail("并发阶段累计请求数与结果事件不一致")
        remaining = len(target_ids) - completed_count
        next_width = _next_legacy_stage_width(job, completed_stages, remaining)
        candidates = target_ids[completed_count : completed_count + next_width]
        later = {
            target_id
            for target_id in target_ids[completed_count:]
            if legacy_terminals[target_id]
        }
        if not later.issubset(set(candidates)):
            _fail("旧事件在可推导的下一并发阶段之外出现请求结果")
        known_attempts = sum(len(legacy_terminals[target_id]) for target_id in target_ids)
        missing = legacy_requests_used - known_attempts
        if missing < 0:
            _fail("结果事件尝试数超过许可证 requests_used")
        eligible: list[tuple[str, int]] = []
        for target_id in candidates:
            attempts = legacy_terminals[target_id]
            if not attempts:
                eligible.append((target_id, 1))
                continue
            highest = max(attempts)
            last = attempts[highest]
            if (
                last.get("status") == "request_failed"
                and last.get("will_retry") is True
                and not _is_image_download_failure(last)
                and highest < max_attempts
            ):
                eligible.append((target_id, highest + 1))
        if missing:
            # With indistinguishable legacy requests, only an all-or-nothing
            # allocation (or one sole candidate) has a unique safe solution.
            if missing != len(eligible):
                _fail("旧事件缺失请求存在多种分配方式，拒绝推测恢复")
            for target_id, attempt in eligible:
                reservations[target_id][attempt] = {
                    "status": "conservative_unknown",
                    "attempt": attempt,
                }
        elif any(
            legacy_terminals[target_id]
            and legacy_terminals[target_id][max(legacy_terminals[target_id])].get("will_retry") is True
            for target_id in candidates
        ):
            # A recorded retryable failure without a reserved next request is a
            # known partial target, not an inferred in-flight request.
            pass
    elif legacy_requests_used:
        _fail("request_number 显示存在旧账本前缀，但没有可验证的旧式结果事件")

    _equal(job.get("requests_used"), license_data.get("requests_used"), "requests_used")

    attempts_used: dict[str, int] = {}
    attempts_remaining: dict[str, int] = {}
    classes: dict[str, str] = {}
    for target_id in target_ids:
        reserved_attempts = set(reservations[target_id])
        terminal_attempts = set(terminals[target_id])
        used_attempts = reserved_attempts | terminal_attempts
        if used_attempts:
            highest = max(used_attempts)
            if used_attempts != set(range(1, highest + 1)):
                _fail(f"目标尝试序列不连续：{target_id}")
        used = len(used_attempts)
        attempts_used[target_id] = used
        generated = [
            event for event in terminals[target_id].values() if event.get("status") == "generated"
        ]
        if target_id in recovered:
            generated.append(recovered[target_id])
        if len(generated) > 1:
            _fail(f"目标存在多个成功事件：{target_id}")
        if generated:
            success_attempt = int(generated[0]["attempt"])
            if any(attempt > success_attempt for attempt in used_attempts):
                _fail(f"目标成功后仍有请求事件：{target_id}")
            classes[target_id] = "success"
            attempts_remaining[target_id] = 0
            continue
        balance_failures = [
            event
            for event in terminals[target_id].values()
            if _is_balance_failure(event)
        ]
        effective_used = used - len(balance_failures)
        final_failures = [
            event
            for event in terminals[target_id].values()
            if event.get("status") == "request_failed"
            and event.get("will_retry") is False
            and not _is_balance_failure(event)
        ]
        if (final_failures or effective_used >= max_attempts
                or any(_is_image_download_failure(event) for event in terminals[target_id].values())):
            classes[target_id] = "exhausted"
            attempts_remaining[target_id] = 0
        elif balance_failures:
            classes[target_id] = "balance_recoverable"
            attempts_remaining[target_id] = max_attempts - effective_used
        elif used == 0:
            classes[target_id] = "unattempted"
            attempts_remaining[target_id] = max_attempts
        else:
            classes[target_id] = "unknown"
            attempts_remaining[target_id] = max_attempts - effective_used
    if sum(attempts_used.values()) != int(license_data["requests_used"]):
        _fail("逐目标尝试账本之和与 requests_used 不一致")
    return attempts_used, attempts_remaining, classes


def build_resume_plan(
    batch_dir: str | Path,
    job_path: str | Path,
    license_path: str | Path,
) -> dict[str, Any]:
    """Validate frozen evidence and return a deterministic, read-only plan."""

    batch = Path(batch_dir).expanduser().resolve()
    job_file = _resolved_file(job_path, "任务文件")
    license_file = _resolved_file(license_path, "许可证")
    (
        job,
        license_data,
        manifest_path,
        rows,
        overlay_path,
        overlay,
        events_path,
        events,
    ) = _validate_fixed_evidence(batch, job_file, license_file)
    image_download_receipts.assert_no_pending_for_job(RECEIPT_ROOT, str(job["job_id"]))
    profile_bindings = _profile_resume_bindings(license_data, job, rows, overlay, events)
    source_size_acceptance = category_source_size_acceptance.load_acceptance(
        batch, job, license_data, _file_sha256(manifest_path), _file_sha256(overlay_path),
    )
    target_ids = [str(row["generation_target_id"]) for row in rows]
    attempts_used, attempts_remaining, classes = _account_attempts(
        batch, rows, events, job, license_data, source_size_acceptance
    )
    reservations = {(event.get("generation_target_id"), event.get("attempt"))
                    for event in events if event.get("status") == "request_reserved"}
    terminal_results = {(event.get("generation_target_id"), event.get("attempt"))
                        for event in events if event.get("status") in {"request_failed", "generated"}}
    if profile_bindings and reservations - terminal_results:
        _fail("新4K任务存在已预留但结果未知的请求；禁止作为新POST自动续跑，需先核对已付费响应")
    categories = {
        name: [target_id for target_id in target_ids if classes[target_id] == name]
        for name in (
            "success",
            "exhausted",
            "balance_recoverable",
            "unknown",
            "unattempted",
        )
    }
    resumable_ids = [
        target_id
        for target_id in target_ids
        if classes[target_id] in {"balance_recoverable", "unknown", "unattempted"}
    ]
    requests_used = sum(attempts_used.values())
    remaining_max = sum(attempts_remaining.values())
    cumulative_max = requests_used + remaining_max
    balance_failure_request_count = sum(
        1
        for event in events
        if _is_balance_failure(event)
    )
    budget = _integer(license_data.get("approved_request_budget"), "approved_request_budget")
    approved_count = _integer(
        license_data.get("approved_api_request_count"), "approved_api_request_count"
    )
    max_attempts = int(license_data["max_attempts"])
    if approved_count != len(target_ids):
        _fail("approved_api_request_count 与冻结清单目标数不一致")
    if budget != approved_count * max_attempts:
        _fail("许可证预算不等于授权目标数乘每目标最大尝试次数")
    if cumulative_max > budget + balance_failure_request_count:
        _fail("恢复计划累计最大请求数超过许可证预算")
    if profile_bindings:
        if requests_used > budget:
            _fail("新4K续跑已用请求超过原预算")
        cumulative_max = min(cumulative_max, budget)
        remaining_max = cumulative_max - requests_used

    event_bytes = events_path.read_bytes()
    event_lines = [line for line in event_bytes.splitlines() if line.strip()]
    if not event_lines:
        _fail("事件文件没有可绑定的尾事件")
    hashes = {
        "frozen_manifest_sha256": _file_sha256(manifest_path),
        "frozen_overlay_sha256": _file_sha256(overlay_path),
        "events_sha256": hashlib.sha256(event_bytes).hexdigest(),
        "event_tail_sha256": hashlib.sha256(event_lines[-1]).hexdigest(),
    }
    counts = {
        "total": len(target_ids),
        "success": len(categories["success"]),
        "exhausted": len(categories["exhausted"]),
        "balance_recoverable": len(categories["balance_recoverable"]),
        "unknown": len(categories["unknown"]),
        "unattempted": len(categories["unattempted"]),
        "resumable": len(resumable_ids),
    }
    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "job_id": str(job["job_id"]),
        "license_id": str(license_data["license_id"]),
        "category_id": str(license_data["category_id"]),
        "batch_id": str(license_data["batch_id"]),
        "group_start": int(license_data["group_start"]),
        "group_count": int(license_data["group_count"]),
        "scope": str(license_data["scope"]),
        "provider": str(license_data["provider"]),
        "model": str(license_data["model"]),
        "quality": str(license_data["quality"]),
        "size": str(license_data["size"]),
        "max_attempts": max_attempts,
        "retry_policy": str(license_data["retry_policy"]),
        "budget": budget,
        "requests_used": requests_used,
        "remaining_max_requests": remaining_max,
        "cumulative_max_requests": cumulative_max,
        "balance_failure_request_count": balance_failure_request_count,
        "counts": counts,
        "success_ids": categories["success"],
        "exhausted_ids": categories["exhausted"],
        "balance_recoverable_ids": categories["balance_recoverable"],
        "unknown_ids": categories["unknown"],
        "unattempted_ids": categories["unattempted"],
        "resumable_ids": resumable_ids,
        "attempts_used": attempts_used,
        "attempts_remaining": attempts_remaining,
        **profile_bindings,
        **({"source_size_acceptance": source_size_acceptance} if source_size_acceptance is not None else {}),
        **hashes,
    }
    hash_material = dict(plan)
    plan["resume_plan_sha256"] = _canonical_sha256(hash_material)
    return plan


__all__ = ["ResumePlanError", "build_resume_plan"]
