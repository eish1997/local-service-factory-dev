"""Create road-rescue v3 manifests: 1 cover + 1 triptych + 3 details.

This is a local manifest builder only. It does not call an LLM, image API, OCR,
or any network service. The old road_rescue 1+8 manifests remain read-only
history; v3 uses a separate schema directory and active category batch.
"""

from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog

import argparse
import hashlib
import json
import os
import random
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from generate_group_prompts import (
    BUSINESS_PATH,
    PROJECT_DIR,
    cover_prompt,
    cover_prompt_v3,
    load,
    reject_snow_details_from_preferences,
)


ROOT = Path(__file__).resolve().parent
PROJECT_ID = "road_rescue"
CATEGORY_CONFIG_PATH = ROOT / "configs" / "categories" / "road_rescue.json"
DETAIL_PROMPTS_PATH = ROOT / "prompts" / "road_rescue_prompts.jsonl"
COVER_VISUAL_V3_PATH = PROJECT_DIR / "cover_visual_profile_v3.json"
V3_STRUCTURE_VERSION = "road_rescue_v3_1cover_1triptych_3details"
V3_GENERATION_MODE = "independent_triptych_panels"
V3_SCHEMA_DIR_NAME = "schema_v3_5"
V3_BATCH_NAME = "batch_v3_5_active"
V3_DELIVERY_FILENAMES = (
    "01_cover.png",
    "02_triptych.png",
    "03_detail.png",
    "04_detail.png",
    "05_detail.png",
)
MAX_COVER_SIGNATURE_ATTEMPTS = 1000
PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


class RoadRescueV3ManifestError(ValueError):
    """Raised when a v3 manifest operation would make project history unsafe."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_sha256(record: dict[str, Any]) -> str:
    material = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(material)


def _load_json(path: Path) -> dict[str, Any]:
    return runtime_paths.read_json(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RoadRescueV3ManifestError(f"JSONL parse failed: {path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise RoadRescueV3ManifestError(f"JSONL row must be an object: {path}:{line_number}")
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


def _portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _legacy_next_group_index() -> int:
    registry_path = PROJECT_DIR / "groups" / "registry.json"
    if not registry_path.is_file():
        return 1
    registry = _load_json(registry_path)
    next_index = int(registry.get("next_group_index") or 1)
    if next_index < 1:
        raise RoadRescueV3ManifestError("legacy registry.next_group_index must be positive")
    return next_index


def _validate_structure(config: dict[str, Any]) -> dict[str, Any]:
    structure = config.get("image_group_structure")
    if not isinstance(structure, dict):
        raise RoadRescueV3ManifestError("road_rescue category config is missing image_group_structure")
    if structure.get("structure_version") != V3_STRUCTURE_VERSION:
        raise RoadRescueV3ManifestError("road_rescue structure_version does not match the v3 builder")
    if structure.get("generation_mode") != V3_GENERATION_MODE:
        raise RoadRescueV3ManifestError("road_rescue v3 must use independent triptych panels")
    expected = {
        "cover_count": 1,
        "triptych_count": 1,
        "triptych_panel_count": 3,
        "detail_count": 3,
        "total_per_group": 5,
        "generation_unit_count": 7,
        "service_roles_per_group": 6,
    }
    for key, value in expected.items():
        if int(structure.get(key, -1)) != value:
            raise RoadRescueV3ManifestError(f"road_rescue v3 {key} must be {value}")
    if structure.get("delivery_roles") != ["cover", "triptych", "detail", "detail", "detail"]:
        raise RoadRescueV3ManifestError("road_rescue v3 delivery_roles must be cover, triptych, detail, detail, detail")
    role_pool = structure.get("service_role_pool")
    if not isinstance(role_pool, list) or len(role_pool) != 8 or len(set(role_pool)) != 8:
        raise RoadRescueV3ManifestError("road_rescue v3 service_role_pool must contain eight unique rescue roles")
    heights = structure.get("height_profiles")
    if (
        not isinstance(heights, list)
        or [int(item.get("height", 0)) for item in heights if isinstance(item, dict)] != [1408, 1472, 1536]
        or any(int(item.get("width", 0)) != 1024 for item in heights if isinstance(item, dict))
    ):
        raise RoadRescueV3ManifestError("road_rescue v3 height profiles must be 1024x1408, 1024x1472, 1024x1536")
    layouts = structure.get("triptych_layouts")
    if not isinstance(layouts, list) or len(layouts) != 3:
        raise RoadRescueV3ManifestError("road_rescue v3 must define three triptych layouts")
    for layout in layouts:
        panels = layout.get("panels") if isinstance(layout, dict) else None
        if not isinstance(panels, list) or [panel.get("panel_index") for panel in panels] != [1, 2, 3]:
            raise RoadRescueV3ManifestError("each triptych layout must define panels 1, 2, 3")
    return structure


def _sanitize_cover_prompt(prompt: str) -> str:
    prompt = PHONE_PATTERN.sub("本地后处理添加的已确认联系电话", prompt)
    prompt += (
        "\n道路救援 v6 补充规则：门头联系电话会在生产时注入当前已确认号码，并由模型作为实体招牌排版自然生成；"
        "原始生图不要生成其他电话号码、二维码、水印、价格、可读车牌、中心电话条或底部十宫格服务词。"
    )
    if PHONE_PATTERN.search(prompt):
        raise RoadRescueV3ManifestError("sanitized cover prompt still contains a phone number")
    return prompt


def _detail_role(record: dict[str, Any]) -> str:
    scene = record.get("scene")
    if not isinstance(scene, dict) or not scene.get("rescue_job"):
        raise RoadRescueV3ManifestError("road_rescue detail prompt is missing scene.rescue_job")
    return str(scene["rescue_job"])


def _eligible_detail_records(role_pool: list[str]) -> dict[str, list[dict[str, Any]]]:
    reject_snow = reject_snow_details_from_preferences()
    rows = _load_jsonl(DETAIL_PROMPTS_PATH)
    by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("visual_style_version") != "realistic_mobile_documentary_v2":
            continue
        role = _detail_role(row)
        if role not in role_pool:
            continue
        if reject_snow and role == "雪地救援":
            continue
        by_role[role].append(row)
    missing = [role for role in role_pool if role not in by_role and not (reject_snow and role == "雪地救援")]
    if missing:
        raise RoadRescueV3ManifestError(f"missing v2 road_rescue detail prompts for roles: {missing}")
    for role, records in by_role.items():
        records.sort(key=lambda row: int(row["index"]))
    return by_role


def _assignment(role_pool: list[str], group_index: int) -> list[str]:
    rng = random.Random(f"{PROJECT_ID}:v3:group:{group_index}:service-role-assignment")
    return rng.sample(role_pool, 6)


def _height_and_layout(structure: dict[str, Any], group_index: int) -> tuple[dict[str, Any], dict[str, Any], int]:
    height = dict(structure["height_profiles"][(group_index - 1) % 3])
    layout = dict(structure["triptych_layouts"][((group_index - 1) // 3) % 3])
    cycle_index = ((group_index - 1) % 9) + 1
    return height, layout, cycle_index


def _generation_id(group_index: int, generation_position: int) -> str:
    return f"{PROJECT_ID}:v3:g{group_index:04d}:u{generation_position:02d}"


def _delivery_id(group_index: int, delivery_position: int) -> str:
    return f"{PROJECT_ID}:v3:g{group_index:04d}:d{delivery_position:02d}"


def _delivery_target(group_index: int, delivery_position: int) -> str:
    filename = V3_DELIVERY_FILENAMES[delivery_position - 1]
    return f"output/{PROJECT_ID}/group_{group_index:04d}/{filename}"


def _raw_target(group_index: int, generation_position: int, generation_role: str) -> str:
    if generation_role == "cover":
        filename = "u01_cover.png"
    elif generation_role == "triptych_panel":
        filename = f"u{generation_position:02d}_triptych_panel_{generation_position - 1}.png"
    else:
        filename = f"u{generation_position:02d}_detail_{generation_position - 4}.png"
    return f"prompts/category_batches/{PROJECT_ID}/{V3_BATCH_NAME}/raw/group_{group_index:04d}/{filename}"


def _source_lineage(kind: str, seed: str, source_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "structure_version": V3_STRUCTURE_VERSION,
        "seed": seed,
        "source_index": int(source_record.get("index", 0) or 0),
        "source_role": source_record.get("role") or _detail_role(source_record) if kind == "existing_detail_prompt" else "cover",
        "record_sha256": _record_sha256(source_record),
    }


def _cover_record(
    group_index: int,
    global_index: int,
    height: dict[str, Any],
    layout: dict[str, Any],
    cycle_index: int,
    phones: list[str],
    library: dict[str, Any],
    used_cover_signatures: set[str],
) -> tuple[dict[str, Any], str]:
    visual_profile = load(COVER_VISUAL_V3_PATH)
    use_visual_v3 = group_index >= int(visual_profile["first_group_index"])
    for attempt in range(MAX_COVER_SIGNATURE_ATTEMPTS):
        if use_visual_v3:
            prompt, scene = cover_prompt_v3(group_index, library, visual_profile, phones, variant=attempt)
        else:
            prompt, scene = cover_prompt(group_index, library, phones, variant=attempt)
        signature = str(scene["composition_signature"])
        if signature in used_cover_signatures:
            continue
        prompt = _sanitize_cover_prompt(prompt)
        generation_id = _generation_id(group_index, 1)
        final_size = f"{int(height['width'])}x{int(height['height'])}"
        source_record = {
            "index": global_index,
            "group_index": group_index,
            "scene": scene,
            "prompt": prompt,
        }
        return {
            "schema_version": 3,
            "structure_version": V3_STRUCTURE_VERSION,
            "generation_mode": V3_GENERATION_MODE,
            "project_id": PROJECT_ID,
            "category_id": PROJECT_ID,
            "category_name": "汽车救援",
            "index": global_index,
            "group_index": group_index,
            "generation_position": 1,
            "generation_id": generation_id,
            "role": "cover",
            "generation_kind": "cover",
            "generation_role": "cover",
            "service_role": None,
            "prompt_role": "cover",
            "delivery_position": 1,
            "delivery_filename": V3_DELIVERY_FILENAMES[0],
            "delivery_target": _delivery_target(group_index, 1),
            "raw_target": _raw_target(group_index, 1, "cover"),
            "raw_size": "1024x1536",
            "expected_size": final_size,
            "final_size": final_size,
            "height_profile_id": height["id"],
            "triptych_layout_id": layout["id"],
            "variation_cycle_index": cycle_index,
            "scene": scene,
            "source_positive_prompt": prompt,
            "negative_prompt": "",
            "positive_prompt": prompt,
            "prompt": prompt,
            "prompt_sha256": _sha256_text(prompt),
            "cover_variant_id": f"road-v3-{signature[:12]}",
            "cover_variant_signature": signature,
            "composition_signature": signature,
            "cover_template_version": scene.get("cover_template_version"),
            "source_lineage": _source_lineage("road_cover_prompt", f"{PROJECT_ID}:v3:group:{group_index}:cover:attempt:{attempt}", source_record),
            "visual_style_version": "realistic_mobile_documentary_v2",
            "category_config_version": "road_rescue_category_content_v1",
            "status": "prompt_ready",
            "api_called": False,
        }, signature
    raise RoadRescueV3ManifestError(f"group {group_index} has no unique cover signature")


@variable_catalog.managed('road_rescue','detail',finish_result='always')
def _service_record(
    source_record: dict[str, Any],
    group_index: int,
    global_index: int,
    generation_position: int,
    generation_role: str,
    delivery_position: int,
    height: dict[str, Any],
    layout: dict[str, Any],
    cycle_index: int,
) -> dict[str, Any]:
    service_role = _detail_role(source_record)
    # Preserve the curated default detail strategy; rebuild only when a native
    # detail candidate pool has actually changed. Custom text is applied below.
    current = variable_catalog.CURRENT.get()['catalog']
    original = {d['id']:d for d in variable_catalog.defaults('road_rescue')['dimensions']}
    changed = any(d['kind']=='builtin' and 'detail' in d['roles'] and d['options']!=original[d['id']]['options'] for d in current['dimensions'])
    if changed:
        from generate_prompts import generate_records
        library = variable_catalog.overlay_document('road_rescue', _load_json(ROOT / 'scene_library.json'), 'scene_library.json')
        library['rescue_jobs'] = [j for j in library['rescue_jobs'] if j['name']==service_role]
        if not library['rescue_jobs']:
            raise RoadRescueV3ManifestError(f'变量目录没有启用服务事件：{service_role}')
        fresh = generate_records.__wrapped__(_load_json(ROOT / 'config.json'), library, 1, seed=group_index*100+generation_position)[0]
        source_record = {**source_record, 'prompt':fresh['prompt'], 'scene':fresh['scene']}
    prompt = str(source_record.get("prompt") or source_record.get("positive_prompt") or "").strip()
    if not prompt:
        raise RoadRescueV3ManifestError(f"detail prompt {source_record.get('index')} is empty")
    if PHONE_PATTERN.search(prompt):
        raise RoadRescueV3ManifestError(f"detail prompt {source_record.get('index')} contains a phone number")
    panel_index: int | None = None
    panel_box: dict[str, Any] | None = None
    if generation_role == "triptych_panel":
        panel_index = generation_position - 1
        panel_box = dict(layout["panels"][panel_index - 1])
        prompt += (
            f" 本图是道路救援三拼图第{panel_index}个独立实景面板，最终使用“{layout['name']}”布局；"
            "只生成一个真实道路救援现场，不生成拼图边框、电话、标题、图标或服务面板。"
        )
    generation_id = _generation_id(group_index, generation_position)
    final_size = f"{int(height['width'])}x{int(height['height'])}"
    return {
        "schema_version": 3,
        "structure_version": V3_STRUCTURE_VERSION,
        "generation_mode": V3_GENERATION_MODE,
        "project_id": PROJECT_ID,
        "category_id": PROJECT_ID,
        "category_name": "汽车救援",
        "index": global_index,
        "source_detail_index": int(source_record["index"]),
        "group_index": group_index,
        "generation_position": generation_position,
        "generation_id": generation_id,
        "role": generation_role,
        "generation_kind": generation_role,
        "generation_role": generation_role,
        "service_role": service_role,
        "prompt_role": service_role,
        "delivery_position": delivery_position,
        "delivery_filename": V3_DELIVERY_FILENAMES[delivery_position - 1],
        "delivery_target": _delivery_target(group_index, delivery_position),
        "raw_target": _raw_target(group_index, generation_position, generation_role),
        "raw_size": "1024x1536",
        "expected_size": final_size,
        "final_size": final_size,
        "height_profile_id": height["id"],
        "triptych_layout_id": layout["id"],
        "variation_cycle_index": cycle_index,
        "triptych_panel_index": panel_index,
        "triptych_panel_box": panel_box,
        "scene": source_record["scene"],
        "source_positive_prompt": str(source_record.get("prompt") or ""),
        "negative_prompt": "",
        "positive_prompt": prompt,
        "prompt": prompt,
        "prompt_sha256": _sha256_text(prompt),
        "source_lineage": _source_lineage("existing_detail_prompt", f"{PROJECT_ID}:v3:group:{group_index}:unit:{generation_position}:{service_role}", source_record),
        "visual_style_version": "realistic_mobile_documentary_v2",
        "category_config_version": "road_rescue_category_content_v1",
        "status": "prompt_ready",
        "api_called": False,
    }


def _delivery_row(
    group_index: int,
    delivery_position: int,
    role: str,
    height: dict[str, Any],
    layout: dict[str, Any],
    cycle_index: int,
    source_generation_ids: list[str],
    service_roles: list[str],
) -> dict[str, Any]:
    final_size = f"{int(height['width'])}x{int(height['height'])}"
    validation = {
        "status": "pending",
        "required_size": final_size,
        "requires_visual_review": True,
        "requires_no_garbled_text": True,
        "requires_no_watermark_or_qr": True,
        "requires_no_readable_license_plate": True,
        "requires_history_deduplication": True,
    }
    if role == "cover":
        validation.update({"requires_confirmed_signboard_phone": True, "requires_confirmed_center_phone": True, "requires_ten_service_grid": True})
        generation_policy = "generate_then_local_cover_overlay_and_crop"
    elif role == "triptych":
        validation.update({"requires_three_visible_panels": True, "requires_three_distinct_rescue_roles": True})
        generation_policy = "compose_three_independent_panels_then_local_overlay"
    else:
        generation_policy = "generate_then_local_detail_overlay_and_crop"
    return {
        "schema_version": 3,
        "structure_version": V3_STRUCTURE_VERSION,
        "generation_mode": V3_GENERATION_MODE,
        "project_id": PROJECT_ID,
        "category_id": PROJECT_ID,
        "group_index": group_index,
        "position": delivery_position,
        "delivery_position": delivery_position,
        "delivery_id": _delivery_id(group_index, delivery_position),
        "role": role,
        "filename": V3_DELIVERY_FILENAMES[delivery_position - 1],
        "target": _delivery_target(group_index, delivery_position),
        "source": None,
        "source_generation_ids": source_generation_ids,
        "service_roles": service_roles,
        "raw_size": "1024x1536",
        "expected_size": final_size,
        "final_size": final_size,
        "height_profile_id": height["id"],
        "triptych_layout_id": layout["id"] if role == "triptych" else None,
        "triptych_layout": layout if role == "triptych" else None,
        "triptych_gutter_px": 8 if role == "triptych" else None,
        "variation_cycle_index": cycle_index,
        "generation_policy": generation_policy,
        "validation_status": "pending",
        "validation": validation,
        "status": "prompt_ready",
        "api_called": False,
    }


@variable_catalog.managed('road_rescue',finish_result=False)
def _build_payloads(
    start_group: int,
    count: int,
    *,
    initial_role_offsets: dict[str, int] | None = None,
    initial_cover_signatures: set[str] | None = None,
    global_index_start: int = 1,
) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    config = _load_json(CATEGORY_CONFIG_PATH)
    structure = _validate_structure(config)
    role_pool = [str(value) for value in structure["service_role_pool"]]
    by_role = _eligible_detail_records(role_pool)
    active_role_pool = [role for role in role_pool if role in by_role]
    if len(active_role_pool) < int(structure["service_roles_per_group"]):
        raise RoadRescueV3ManifestError(
            "not enough active road_rescue roles after applying preferences"
        )
    role_offsets = {
        role: int((initial_role_offsets or {}).get(role, 0))
        for role in by_role
    }
    library = load(PROJECT_DIR / "cover_scene_library.json")
    business = load(BUSINESS_PATH) if BUSINESS_PATH.is_file() else {}
    phones = [str(value) for value in business.get("contact_phones") or []]
    if not business.get("user_confirmed") or not phones:
        raise RoadRescueV3ManifestError("CONTACT_CONFIRMATION_REQUIRED: road_rescue phone must be confirmed before v3 manifests")
    if business.get("placeholder_only"):
        raise RoadRescueV3ManifestError("FORMAL_CONTACT_REQUIRED: placeholder phone cannot be used for v3 manifests")

    generation_rows: list[dict[str, Any]] = []
    delivery_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    registry_groups: list[dict[str, Any]] = []
    used_cover_signatures = set(initial_cover_signatures or set())

    for group_index in range(start_group, start_group + count):
        height, layout, cycle_index = _height_and_layout(structure, group_index)
        assigned_roles = _assignment(active_role_pool, group_index)
        selected_details: list[dict[str, Any]] = []
        for role in assigned_roles:
            records = by_role.get(role) or []
            offset = role_offsets.get(role, 0)
            if offset >= len(records):
                raise RoadRescueV3ManifestError(f"not enough v2 detail prompts for role {role}")
            selected_details.append(records[offset])
            role_offsets[role] = offset + 1
        first_global_index = global_index_start + (group_index - start_group) * 7
        cover, cover_signature = _cover_record(
            group_index,
            first_global_index,
            height,
            layout,
            cycle_index,
            phones,
            library,
            used_cover_signatures,
        )
        used_cover_signatures.add(cover_signature)
        group_generation = [cover]
        for relative_index, source_record in enumerate(selected_details, start=1):
            generation_position = relative_index + 1
            generation_role = "triptych_panel" if relative_index <= 3 else "detail"
            delivery_position = 2 if generation_role == "triptych_panel" else relative_index - 1
            group_generation.append(
                _service_record(
                    source_record,
                    group_index,
                    first_global_index + relative_index,
                    generation_position,
                    generation_role,
                    delivery_position,
                    height,
                    layout,
                    cycle_index,
                )
            )
        service_roles = [str(row["service_role"]) for row in group_generation[1:]]
        if len(set(service_roles)) != 6:
            raise RoadRescueV3ManifestError(f"group {group_index} does not have six distinct rescue roles")
        group_deliveries = [
            _delivery_row(group_index, 1, "cover", height, layout, cycle_index, [group_generation[0]["generation_id"]], []),
            _delivery_row(group_index, 2, "triptych", height, layout, cycle_index, [row["generation_id"] for row in group_generation[1:4]], service_roles[:3]),
        ]
        for detail_offset, generation_record in enumerate(group_generation[4:], start=3):
            group_deliveries.append(
                _delivery_row(
                    group_index,
                    detail_offset,
                    "detail",
                    height,
                    layout,
                    cycle_index,
                    [generation_record["generation_id"]],
                    [str(generation_record["service_role"])],
                )
            )
        signature_material = {
            "cover_variant_signature": cover_signature,
            "height_profile_id": height["id"],
            "triptych_layout_id": layout["id"],
            "service_roles": service_roles,
            "source_detail_indices": [row.get("source_detail_index") for row in group_generation[1:]],
        }
        composition_signature = _sha256_text(json.dumps(signature_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        group_rows.append({
            "schema_version": 3,
            "structure_version": V3_STRUCTURE_VERSION,
            "generation_mode": V3_GENERATION_MODE,
            "project_id": PROJECT_ID,
            "group_index": group_index,
            "total_images": 5,
            "generation_unit_count": 7,
            "cover": {"delivery_id": group_deliveries[0]["delivery_id"], "generation_id": group_generation[0]["generation_id"], "filename": V3_DELIVERY_FILENAMES[0], "prompt_sha256": group_generation[0]["prompt_sha256"]},
            "triptych": {"delivery_id": group_deliveries[1]["delivery_id"], "filename": V3_DELIVERY_FILENAMES[1], "layout_id": layout["id"], "panel_generation_ids": [row["generation_id"] for row in group_generation[1:4]], "service_roles": service_roles[:3]},
            "details": [
                {"delivery_id": delivery["delivery_id"], "generation_id": generation["generation_id"], "filename": delivery["filename"], "service_role": generation["service_role"], "source_detail_index": generation["source_detail_index"], "prompt_sha256": generation["prompt_sha256"]}
                for delivery, generation in zip(group_deliveries[2:], group_generation[4:])
            ],
            "generation_units": [row["generation_id"] for row in group_generation],
            "delivery_files": [row["delivery_id"] for row in group_deliveries],
            "service_roles": service_roles,
            "height_profile": height,
            "final_size": group_deliveries[0]["final_size"],
            "triptych_layout": layout,
            "variation_cycle_index": cycle_index,
            "cover_variant_signature": cover_signature,
            "composition_signature": composition_signature,
            "anti_homogeneity_axes": ["final_height", "triptych_layout", "six_distinct_rescue_roles", "storefront_variant", "road_location", "weather", "camera_view", "vehicle_policy"],
            "status": "prompt_ready",
            "api_called": False,
        })
        registry_groups.append({
            "group_index": group_index,
            "structure_version": V3_STRUCTURE_VERSION,
            "generation_mode": V3_GENERATION_MODE,
            "group_size": 5,
            "generation_unit_count": 7,
            "final_size": group_deliveries[0]["final_size"],
            "height_profile_id": height["id"],
            "triptych_layout_id": layout["id"],
            "variation_cycle_index": cycle_index,
            "service_roles": service_roles,
            "cover_variant_signature": cover_signature,
            "composition_signature": composition_signature,
            "status": "prompt_ready",
        })
        generation_rows.extend(group_generation)
        delivery_rows.extend(group_deliveries)

    created_at = datetime.now(timezone.utc).isoformat()
    registry = {
        "schema_version": 3,
        "structure_version": V3_STRUCTURE_VERSION,
        "generation_mode": V3_GENERATION_MODE,
        "project_id": PROJECT_ID,
        "group_size": 5,
        "generation_unit_count": 7,
        "cover_count": 1,
        "triptych_count": 1,
        "triptych_panel_count": 3,
        "detail_count": 3,
        "created_groups": count,
        "first_group_index": start_group,
        "last_group_index": start_group + count - 1,
        "next_group_index": start_group + count,
        "active_batch": f"prompts/category_batches/{PROJECT_ID}/{V3_BATCH_NAME}",
        "groups": registry_groups,
        "created_at": created_at,
        "api_called": False,
    }
    batch_manifest_rows = [
        {
            "schema_version": 3,
            "structure_version": V3_STRUCTURE_VERSION,
            "generation_mode": V3_GENERATION_MODE,
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
    summary = {
        "schema_version": 3,
        "structure_version": V3_STRUCTURE_VERSION,
        "generation_mode": V3_GENERATION_MODE,
        "category_id": PROJECT_ID,
        "category_name": "汽车救援",
        "mode": "active_v3_5_group_manifests",
        "group_start": start_group,
        "group_count": count,
        "generation_unit_count": len(generation_rows),
        "cover_generation_count": count,
        "triptych_panel_generation_count": count * 3,
        "detail_generation_count": count * 3,
        "delivery_file_count": len(delivery_rows),
        "delivery_structure": {"cover_count": 1, "triptych_count": 1, "detail_count": 3, "total_per_group": 5},
        "height_profiles": structure["height_profiles"],
        "triptych_layouts": [{"id": item["id"], "name": item["name"]} for item in structure["triptych_layouts"]],
        "created_at": created_at,
        "api_called": False,
    }
    schema_files = {
        "registry.json": json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        "group_manifest.jsonl": _jsonl_text(group_rows),
        "generation_manifest.jsonl": _jsonl_text(generation_rows),
        "production_manifest.jsonl": _jsonl_text(delivery_rows),
    }
    batch_files = {
        "prompts.jsonl": _jsonl_text(generation_rows),
        "cover_prompts.jsonl": _jsonl_text([row for row in generation_rows if row["generation_role"] == "cover"]),
        "triptych_panel_prompts.jsonl": _jsonl_text([row for row in generation_rows if row["generation_role"] == "triptych_panel"]),
        "detail_prompts.jsonl": _jsonl_text([row for row in generation_rows if row["generation_role"] == "detail"]),
        "manifest.jsonl": _jsonl_text(batch_manifest_rows),
        "delivery_manifest.jsonl": _jsonl_text(delivery_rows),
        "summary.json": json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        "README_THIS_BATCH.txt": (
            "汽车救援 v3 活动清单\n\n"
            "每组交付 5 张：1 首图、1 三拼图、3 单张详情图。\n"
            "每组三拼图使用 3 个独立道路救援现场面板；加上首图和 3 张详情图，共 7 个生成单元。\n"
            "同组 6 个救援现场使用 6 个不同救援角色。\n"
            "本批次只创建本地提示词与清单，没有调用图片接口，也没有生成图片。\n"
        ),
        "summary_readable.txt": (
            f"已创建汽车救援 v3 清单：{count} 组，组号 {start_group}-{start_group + count - 1}。\n"
            f"生成单元：{len(generation_rows)} 个。\n"
            f"交付文件位：{len(delivery_rows)} 个。\n"
            "图片接口调用：0。\n"
        ),
    }
    return schema_files, batch_files, summary


def _update_project_definition(count: int, start_group: int, summary: dict[str, Any]) -> None:
    definition_path = PROJECT_DIR / "project.json"
    definition = _load_json(definition_path)
    prompt_sources = dict(definition.get("prompt_sources", {}))
    prompt_sources.setdefault(
        "legacy_manifest_set",
        {
            "group_registry": "projects/road_rescue/groups/registry.json",
            "group_manifest": "projects/road_rescue/groups/group_manifest.jsonl",
            "cover_manifest": "projects/road_rescue/prompts/cover_prompts.jsonl",
            "detail_manifest": "prompts/road_rescue_prompts.jsonl",
            "production_manifest": "projects/road_rescue/groups/production_manifest.jsonl",
            "group_schema": "legacy_1_cover_8_details",
            "read_only": True,
        },
    )
    prompt_sources.update(
        {
            "category_config": "configs/categories/road_rescue.json",
            "category_content_profile": "projects/road_rescue/category_content_profile.json",
            "category_config_version": "road_rescue_category_content_v1",
            "visual_style": "configs/visual_styles/realistic_mobile_documentary_v2.json",
            "visual_style_version": "realistic_mobile_documentary_v2",
            "active_batch": f"prompts/category_batches/{PROJECT_ID}/{V3_BATCH_NAME}",
            "cover_manifest": f"prompts/category_batches/{PROJECT_ID}/{V3_BATCH_NAME}/cover_prompts.jsonl",
            "triptych_panel_manifest": f"prompts/category_batches/{PROJECT_ID}/{V3_BATCH_NAME}/triptych_panel_prompts.jsonl",
            "detail_manifest": f"prompts/category_batches/{PROJECT_ID}/{V3_BATCH_NAME}/detail_prompts.jsonl",
            "generation_manifest": f"projects/{PROJECT_ID}/groups/{V3_SCHEMA_DIR_NAME}/generation_manifest.jsonl",
            "production_manifest": f"projects/{PROJECT_ID}/groups/{V3_SCHEMA_DIR_NAME}/production_manifest.jsonl",
            "cover_prompt_count": count,
            "triptych_panel_prompt_count": count * 3,
            "detail_prompt_count": count * 3,
            "service_prompt_count": count * 6,
            "generation_unit_count": int(summary["generation_unit_count"]),
            "delivery_file_count": int(summary["delivery_file_count"]),
            "available_complete_groups": count,
        }
    )
    definition.update(
        {
            "schema_version": 2,
            "status": "active",
            "content_group": {
                "group_schema": V3_STRUCTURE_VERSION,
                "structure_version": V3_STRUCTURE_VERSION,
                "generation_mode": V3_GENERATION_MODE,
                "cover_count": 1,
                "triptych_count": 1,
                "triptych_panel_count": 3,
                "detail_count": 3,
                "total_images": 5,
                "generation_unit_count": 7,
                "service_roles_per_group": 6,
                "cover_role": "真实中国街边汽车救援门店首图",
                "triptych_role": "三个不同道路救援现场组成的一张三拼详情图",
                "detail_role": "三张互不重复救援角色的真实道路救援详情图",
                "height_rule": "同组五张交付图高度一致；组间按 1408、1472、1536 像素轮换",
            },
            "prompt_sources": prompt_sources,
            "group_registry": f"projects/{PROJECT_ID}/groups/{V3_SCHEMA_DIR_NAME}/registry.json",
            "inventory_ledger": f"projects/{PROJECT_ID}/groups/inventory_history.jsonl",
            "inventory_history": f"projects/{PROJECT_ID}/groups/inventory_history.jsonl",
            "inventory_snapshot": f"projects/{PROJECT_ID}/groups/inventory.json",
            "inventory_policy": {
                "target_available_groups": 30,
                "sample_gate_groups": 3,
                "deduplicate_within_project_history": True,
                "cross_category_deduplication_required": False,
                "delete_delivered_images_keep_history": True,
            },
            "output_dir": "output/road_rescue",
        }
    )
    _atomic_json(definition_path, definition)


def create_v3_5_groups(count: int, *, replace_existing: bool = False) -> dict[str, Any]:
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise RoadRescueV3ManifestError("count must be a positive integer")
    schema_dir = PROJECT_DIR / "groups" / V3_SCHEMA_DIR_NAME
    batch_dir = ROOT / "prompts" / "category_batches" / PROJECT_ID / V3_BATCH_NAME
    if schema_dir.exists() or batch_dir.exists():
        if not replace_existing:
            existing = schema_dir if schema_dir.exists() else batch_dir
            raise RoadRescueV3ManifestError(f"road_rescue v3 manifests already exist; refusing to overwrite: {existing}")
        registry_path = schema_dir / "registry.json"
        summary_path = batch_dir / "summary.json"
        if not registry_path.is_file() or not summary_path.is_file():
            raise RoadRescueV3ManifestError("can only refresh a complete road_rescue v3 manifest set")
        marker = _load_json(registry_path)
        if marker.get("project_id") != PROJECT_ID or marker.get("structure_version") != V3_STRUCTURE_VERSION:
            raise RoadRescueV3ManifestError("existing schema directory is not a road_rescue v3 manifest set")
        start_group = int(marker.get("first_group_index") or marker.get("groups", [{}])[0].get("group_index") or _legacy_next_group_index())
    else:
        start_group = _legacy_next_group_index()
    schema_files, batch_files, summary = _build_payloads(start_group, count)
    schema_dir.mkdir(parents=True, exist_ok=replace_existing)
    batch_dir.mkdir(parents=True, exist_ok=replace_existing)
    for relative_name, content in schema_files.items():
        _atomic_text(schema_dir / relative_name, content)
    for relative_name, content in batch_files.items():
        _atomic_text(batch_dir / relative_name, content)
    _update_project_definition(count, start_group, summary)
    return {
        "project_id": PROJECT_ID,
        "operation": "refresh_v3_5_groups" if replace_existing else "create_v3_5_groups",
        "structure_version": V3_STRUCTURE_VERSION,
        "generation_mode": V3_GENERATION_MODE,
        "group_start": start_group,
        "group_count": count,
        "generation_unit_count": int(summary["generation_unit_count"]),
        "delivery_file_count": int(summary["delivery_file_count"]),
        "schema_dir": _portable_path(schema_dir),
        "batch_dir": _portable_path(batch_dir),
        "api_called": False,
    }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _append_jsonl_text(existing: str, addition: str) -> str:
    if existing and not existing.endswith("\n"):
        existing += "\n"
    return existing + addition


def extend_v3_5_groups(count: int) -> dict[str, Any]:
    """Append new v3 groups while preserving every existing JSONL byte as a prefix."""
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise RoadRescueV3ManifestError("count must be a positive integer")

    schema_dir = PROJECT_DIR / "groups" / V3_SCHEMA_DIR_NAME
    batch_dir = ROOT / "prompts" / "category_batches" / PROJECT_ID / V3_BATCH_NAME
    registry_path = schema_dir / "registry.json"
    summary_path = batch_dir / "summary.json"
    if not registry_path.is_file() or not summary_path.is_file():
        raise RoadRescueV3ManifestError("road_rescue v3 manifest set is incomplete; cannot extend")

    registry = _load_json(registry_path)
    summary = _load_json(summary_path)
    if registry.get("structure_version") != V3_STRUCTURE_VERSION:
        raise RoadRescueV3ManifestError("road_rescue registry structure version does not match v3")
    existing_group_count = int(registry.get("created_groups") or 0)
    first_group = int(registry.get("first_group_index") or 0)
    last_group = int(registry.get("last_group_index") or 0)
    if existing_group_count < 1 or first_group < 1 or last_group != first_group + existing_group_count - 1:
        raise RoadRescueV3ManifestError("road_rescue registry range is inconsistent")
    if int(summary.get("group_start") or 0) != first_group or int(summary.get("group_count") or 0) != existing_group_count:
        raise RoadRescueV3ManifestError("road_rescue summary and registry ranges do not match")

    schema_jsonl_names = ("group_manifest.jsonl", "generation_manifest.jsonl", "production_manifest.jsonl")
    batch_jsonl_names = (
        "prompts.jsonl",
        "cover_prompts.jsonl",
        "triptych_panel_prompts.jsonl",
        "detail_prompts.jsonl",
        "manifest.jsonl",
        "delivery_manifest.jsonl",
    )
    existing_schema_text = {
        name: (schema_dir / name).read_text(encoding="utf-8-sig")
        for name in schema_jsonl_names
    }
    existing_batch_text = {
        name: (batch_dir / name).read_text(encoding="utf-8-sig")
        for name in batch_jsonl_names
    }
    existing_generation_rows = _load_jsonl(schema_dir / "generation_manifest.jsonl")
    existing_group_rows = _load_jsonl(schema_dir / "group_manifest.jsonl")
    existing_delivery_rows = _load_jsonl(schema_dir / "production_manifest.jsonl")
    if len(existing_group_rows) != existing_group_count:
        raise RoadRescueV3ManifestError("road_rescue group manifest count is inconsistent")
    if len(existing_generation_rows) != existing_group_count * 7:
        raise RoadRescueV3ManifestError("road_rescue generation manifest count is inconsistent")
    if len(existing_delivery_rows) != existing_group_count * 5:
        raise RoadRescueV3ManifestError("road_rescue production manifest count is inconsistent")

    role_offsets = Counter(
        str(row["service_role"])
        for row in existing_generation_rows
        if row.get("generation_role") != "cover" and row.get("service_role")
    )
    cover_signatures = {
        str(row["cover_variant_signature"])
        for row in existing_group_rows
        if row.get("cover_variant_signature")
    }
    generation_indices = [int(row.get("index") or 0) for row in existing_generation_rows]
    if not generation_indices or len(set(generation_indices)) != len(generation_indices):
        raise RoadRescueV3ManifestError("road_rescue generation indices are missing or duplicated")

    append_start = last_group + 1
    schema_additions, batch_additions, addition_summary = _build_payloads(
        append_start,
        count,
        initial_role_offsets=dict(role_offsets),
        initial_cover_signatures=cover_signatures,
        global_index_start=max(generation_indices) + 1,
    )
    addition_registry = json.loads(schema_additions["registry.json"])
    merged_registry = dict(registry)
    merged_registry.update(
        {
            "created_groups": existing_group_count + count,
            "last_group_index": append_start + count - 1,
            "next_group_index": append_start + count,
            "groups": list(registry.get("groups") or []) + list(addition_registry.get("groups") or []),
            "updated_at": addition_summary["created_at"],
            "api_called": False,
        }
    )
    merged_summary = dict(summary)
    merged_summary.update(
        {
            "group_count": existing_group_count + count,
            "generation_unit_count": (existing_group_count + count) * 7,
            "cover_generation_count": existing_group_count + count,
            "triptych_panel_generation_count": (existing_group_count + count) * 3,
            "detail_generation_count": (existing_group_count + count) * 3,
            "delivery_file_count": (existing_group_count + count) * 5,
            "updated_at": addition_summary["created_at"],
            "api_called": False,
        }
    )

    merged_schema_text = {
        name: _append_jsonl_text(existing_schema_text[name], schema_additions[name])
        for name in schema_jsonl_names
    }
    merged_batch_text = {
        name: _append_jsonl_text(existing_batch_text[name], batch_additions[name])
        for name in batch_jsonl_names
    }
    for name, old_text in existing_schema_text.items():
        if not merged_schema_text[name].startswith(old_text):
            raise RoadRescueV3ManifestError(f"history prefix changed before write: {name}")
    for name, old_text in existing_batch_text.items():
        if not merged_batch_text[name].startswith(old_text):
            raise RoadRescueV3ManifestError(f"history prefix changed before write: {name}")

    old_prefix_hashes = {
        f"schema/{name}": _sha256_bytes(text.encode("utf-8"))
        for name, text in existing_schema_text.items()
    }
    old_prefix_hashes.update(
        {
            f"batch/{name}": _sha256_bytes(text.encode("utf-8"))
            for name, text in existing_batch_text.items()
        }
    )

    for name, content in merged_schema_text.items():
        _atomic_text(schema_dir / name, content)
    for name, content in merged_batch_text.items():
        _atomic_text(batch_dir / name, content)
    _atomic_json(registry_path, merged_registry)
    _atomic_json(summary_path, merged_summary)
    _atomic_text(
        batch_dir / "summary_readable.txt",
        (
            f"已创建汽车救援 v3 清单：{existing_group_count + count} 组，"
            f"组号 {first_group}-{append_start + count - 1}。\n"
            f"生成单元：{(existing_group_count + count) * 7} 个。\n"
            f"交付文件位：{(existing_group_count + count) * 5} 个。\n"
            "图片接口调用：0。\n"
        ),
    )
    _update_project_definition(existing_group_count + count, first_group, merged_summary)

    # Re-read every file and prove that all historical JSONL bytes remain unchanged.
    for name, old_text in existing_schema_text.items():
        if not (schema_dir / name).read_text(encoding="utf-8-sig").startswith(old_text):
            raise RoadRescueV3ManifestError(f"history prefix verification failed after write: {name}")
    for name, old_text in existing_batch_text.items():
        if not (batch_dir / name).read_text(encoding="utf-8-sig").startswith(old_text):
            raise RoadRescueV3ManifestError(f"history prefix verification failed after write: {name}")

    history_path = schema_dir / "extension_history.jsonl"
    history_rows = _load_jsonl(history_path)
    history_rows.append(
        {
            "schema_version": 1,
            "operation": "append_v3_5_groups",
            "previous_group_start": first_group,
            "previous_group_count": existing_group_count,
            "appended_group_start": append_start,
            "appended_group_count": count,
            "new_group_count": existing_group_count + count,
            "old_prefix_sha256": old_prefix_hashes,
            "verified_history_prefix_unchanged": True,
            "created_at": addition_summary["created_at"],
            "api_called": False,
        }
    )
    _atomic_text(history_path, _jsonl_text(history_rows))
    return {
        "project_id": PROJECT_ID,
        "operation": "append_v3_5_groups",
        "group_start": append_start,
        "group_count": count,
        "new_last_group_index": append_start + count - 1,
        "total_group_count": existing_group_count + count,
        "generation_unit_count": count * 7,
        "delivery_file_count": count * 5,
        "verified_history_prefix_unchanged": True,
        "api_called": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create road_rescue v3 5-image group manifests locally.")
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args(argv)
    result = create_v3_5_groups(args.count, replace_existing=args.replace_existing)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
