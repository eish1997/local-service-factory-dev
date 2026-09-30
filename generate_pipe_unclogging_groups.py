"""Build formal pipe-unclogging project manifests without calling an image API.

The module has two deliberately local operations:

* import an immutable legacy category batch into the project-level manifests;
* append legacy 1-cover + 8-detail prompt groups from the category prompt engine;
* create the active v2 manifest set with 1 cover, 1 triptych and 3 details.

Neither operation creates image output directories or performs network work.
"""

from __future__ import annotations
from tools import runtime_paths

import argparse
import hashlib
import json
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.category_image_production import (
    COVER_STYLE_VERSION,
    cover_variant_signature,
    effective_prompt,
    select_cover_variant,
    target_review_status,
    valid_png,
)
from tools.prompt_engine import (
    build_prompt_record,
    load_category_config,
    scene_matches_legal_combination,
)


ROOT = Path(__file__).resolve().parent
PROJECT_ID = "pipe_unclogging"
PROJECT_DIR = ROOT / "projects" / PROJECT_ID
EXPECTED_IMAGE_SIZE = (1024, 1536)
MAX_SIGNATURE_ATTEMPTS = 1000
V2_STRUCTURE_VERSION = "pipe_unclogging_v2_1cover_1triptych_3details"
V2_GENERATION_MODE = "independent_triptych_panels"
V2_SCHEMA_DIR_NAME = "schema_v2_5"
V2_BATCH_NAME = "batch_v2_5_active"
V2_DELIVERY_FILENAMES = (
    "01_cover.png",
    "02_triptych.png",
    "03_detail.png",
    "04_detail.png",
    "05_detail.png",
)


class PipeProjectManifestError(ValueError):
    """Raised when a manifest operation would make project history unsafe."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_sha256(record: dict[str, Any]) -> str:
    material = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(material)


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
            raise PipeProjectManifestError(f"JSONL 解析失败：{path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise PipeProjectManifestError(f"JSONL 记录必须是对象：{path}:{line_number}")
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


def _manifest_paths(project_dir: Path) -> dict[str, Path]:
    return {
        "cover": project_dir / "prompts" / "cover_prompts.jsonl",
        "detail": project_dir / "prompts" / "detail_prompts.jsonl",
        "group": project_dir / "groups" / "group_manifest.jsonl",
        "production": project_dir / "groups" / "production_manifest.jsonl",
        "registry": project_dir / "groups" / "registry.json",
    }


def _default_registry() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "group_size": 9,
        "cover_count": 1,
        "detail_count": 8,
        "created_groups": 0,
        "next_group_index": 1,
        "groups": [],
    }


def _load_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _default_registry()
    try:
        registry = runtime_paths.read_json(path)
    except json.JSONDecodeError as exc:
        raise PipeProjectManifestError(f"registry.json 解析失败：{path}") from exc
    if not isinstance(registry, dict):
        raise PipeProjectManifestError("registry.json 顶层必须是对象")
    if registry.get("project_id") not in {None, PROJECT_ID}:
        raise PipeProjectManifestError("registry.json 属于其他项目")
    groups = registry.get("groups", [])
    if not isinstance(groups, list) or any(not isinstance(item, dict) for item in groups):
        raise PipeProjectManifestError("registry.json 的 groups 必须是对象数组")
    result = _default_registry()
    result.update(registry)
    result["project_id"] = PROJECT_ID
    result["groups"] = [dict(item) for item in groups]
    return result


def _load_state(project_dir: Path) -> dict[str, Any]:
    paths = _manifest_paths(project_dir)
    state = {
        "paths": paths,
        "covers": _load_jsonl(paths["cover"]),
        "details": _load_jsonl(paths["detail"]),
        "groups": _load_jsonl(paths["group"]),
        "production": _load_jsonl(paths["production"]),
        "registry": _load_registry(paths["registry"]),
    }
    registry_indexes = [int(item["group_index"]) for item in state["registry"]["groups"]]
    if len(registry_indexes) != len(set(registry_indexes)):
        raise PipeProjectManifestError("registry.json 存在重复 group_index")
    signatures = _existing_cover_signatures(state)
    if len(signatures) != len(set(signatures)):
        raise PipeProjectManifestError("现有项目历史包含重复 cover_variant_signature，已停止续组")
    return state


def _existing_group_indexes(state: dict[str, Any]) -> set[int]:
    indexes: set[int] = set()
    for key in ("covers", "details", "groups", "production"):
        for row in state[key]:
            if row.get("group_index") is not None:
                indexes.add(int(row["group_index"]))
    for row in state["registry"]["groups"]:
        if row.get("group_index") is not None:
            indexes.add(int(row["group_index"]))
    return indexes


def _signature_from_cover(row: dict[str, Any]) -> str | None:
    value = row.get("cover_variant_signature") or row.get("composition_signature")
    if value:
        return str(value)
    if isinstance(row.get("scene"), dict):
        variant = row.get("cover_variant")
        if not isinstance(variant, dict):
            variant = select_cover_variant(row)
        return cover_variant_signature(row, variant)
    return None


def _existing_cover_signatures(state: dict[str, Any]) -> list[str]:
    by_group: dict[int, str] = {}
    sources = [
        *state["covers"],
        *state["groups"],
        *[
            row
            for row in state["production"]
            if row.get("role") == "cover" or int(row.get("position", 0)) == 1
        ],
        *state["registry"]["groups"],
    ]
    for row in sources:
        if row.get("group_index") is None:
            continue
        signature = _signature_from_cover(row)
        if not signature:
            continue
        group_index = int(row["group_index"])
        current = by_group.get(group_index)
        if current and current != signature:
            raise PipeProjectManifestError(f"第 {group_index} 组的封面签名在 manifest 与 registry 中不一致")
        by_group[group_index] = signature
    return list(by_group.values())


def _next_detail_index(state: dict[str, Any]) -> int:
    indexes = [int(row["index"]) for row in state["details"] if row.get("index") is not None]
    return max(indexes, default=0) + 1


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _output_filename(position: int) -> str:
    return "01_cover.png" if position == 1 else f"{position:02d}_detail.png"


def _target_path(group_index: int, position: int) -> str:
    return f"output/{PROJECT_ID}/group_{group_index:04d}/{_output_filename(position)}"


def _legacy_source_info(batch_dir: Path, legacy_group_index: int, position: int) -> dict[str, Any]:
    filename = _output_filename(position)
    image_path = batch_dir / "images" / f"group_{legacy_group_index:04d}" / filename
    raw_path = batch_dir / "raw" / f"group_{legacy_group_index:04d}" / filename
    review_status = target_review_status(image_path)
    blocked = review_status in {"needs_fix", "rejected"}
    source_path: Path | None = None
    if not blocked and valid_png(image_path, EXPECTED_IMAGE_SIZE):
        source_path = image_path
    elif not blocked and valid_png(raw_path, EXPECTED_IMAGE_SIZE):
        source_path = raw_path
    return {
        "source": _portable_path(source_path) if source_path else None,
        "legacy_image_path": _portable_path(image_path),
        "legacy_raw_path": _portable_path(raw_path),
        "source_review_status": review_status,
        "source_reuse_eligible": source_path is not None,
    }


def _legacy_lineage(batch_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    positive = str(record.get("positive_prompt", ""))
    negative = str(record.get("negative_prompt", ""))
    return {
        "kind": "legacy_category_batch",
        "batch_id": batch_dir.name,
        "batch_dir": _portable_path(batch_dir),
        "group_index": int(record["group_index"]),
        "source_index": int(record["index"]),
        "record_sha256": _record_sha256(record),
        "prompt_sha256": _sha256_text(positive + "\n" + negative),
    }


def _prompt_engine_lineage(seed: str, attempt: int, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "prompt_engine",
        "generator": "tools.prompt_engine.build_prompt_record",
        "category_config": "configs/categories/pipe_unclogging.json",
        "seed": seed,
        "attempt": attempt,
        "source_index": int(record["index"]),
        "record_sha256": _record_sha256(record),
    }


def _lineage_fields(lineage: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"source_lineage": lineage}
    if lineage.get("kind") == "legacy_category_batch":
        result.update(
            {
                "legacy_batch_id": lineage["batch_id"],
                "legacy_batch_dir": lineage["batch_dir"],
                "legacy_group_index": lineage["group_index"],
                "legacy_source_index": lineage["source_index"],
                "legacy_record_sha256": lineage["record_sha256"],
                "legacy_prompt_sha256": lineage["prompt_sha256"],
            }
        )
    return result


def _materialize_group(
    records: list[dict[str, Any]],
    group_index: int,
    detail_index_start: int,
    source_kind: str,
    lineages: list[dict[str, Any]],
    batch_dir: Path | None = None,
) -> dict[str, Any]:
    if len(records) != 9 or len(lineages) != 9:
        raise PipeProjectManifestError("每组必须恰好包含 1 张封面与 8 张详情记录")
    config = load_category_config(PROJECT_ID)
    expected_roles = ["cover", *config["image_group_structure"]["detail_roles"]]
    actual_roles = [str(record.get("role")) for record in records]
    if actual_roles != expected_roles:
        raise PipeProjectManifestError(f"第 {group_index} 组角色顺序不符合固定的 1+8 结构")

    cover_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    production_rows: list[dict[str, Any]] = []
    detail_refs: list[dict[str, Any]] = []
    cover_signature = ""
    cover_variant: dict[str, str] = {}
    cover_prompt_sha256 = ""

    for offset, (source_record, lineage) in enumerate(zip(records, lineages), start=1):
        record = dict(source_record)
        record["group_index"] = group_index
        role_name = str(record["role"])
        # The preserved v1 manifests use the concrete service name in ``role``.
        # The active v2 producer separates the generation kind from that service
        # role, so adapt only in memory when re-reading/importing legacy history.
        # This keeps the immutable 1+8 source files readable without allowing
        # them back into the active v2 production entry point.
        effective_record = {
            **record,
            "generation_kind": "cover" if offset == 1 else "detail",
            "service_role": None if offset == 1 else role_name,
        }
        prompt = effective_prompt(effective_record, "")
        prompt_sha256 = _sha256_text(prompt)
        lineage_fields = _lineage_fields(lineage)
        common_prompt = {
            "schema_version": 1,
            "project_id": PROJECT_ID,
            "category_id": PROJECT_ID,
            "group_index": group_index,
            "position": offset,
            "scene": record.get("scene"),
            "source_positive_prompt": record.get("positive_prompt"),
            "negative_prompt": record.get("negative_prompt"),
            "prompt": prompt,
            "prompt_sha256": prompt_sha256,
            "source_kind": source_kind,
            "api_called": False,
            **lineage_fields,
        }
        if offset == 1:
            cover_variant = select_cover_variant(record, config)
            cover_signature = cover_variant_signature(record, cover_variant)
            cover_prompt_sha256 = prompt_sha256
            cover_rows.append(
                {
                    **common_prompt,
                    "role": "cover",
                    "cover_style_version": COVER_STYLE_VERSION,
                    "cover_variant_id": f"cover-v{COVER_STYLE_VERSION}-{cover_signature[:12]}",
                    "cover_variant_signature": cover_signature,
                    "composition_signature": cover_signature,
                    "cover_variant": cover_variant,
                }
            )
        else:
            detail_index = detail_index_start + offset - 2
            detail_rows.append(
                {
                    **common_prompt,
                    "index": detail_index,
                    "role": "detail",
                    "title": role_name,
                }
            )
            detail_refs.append(
                {
                    "index": detail_index,
                    "position": offset,
                    "title": role_name,
                    "prompt_sha256": prompt_sha256,
                }
            )

        source_info = (
            _legacy_source_info(batch_dir, int(source_record["group_index"]), offset)
            if batch_dir is not None
            else {
                "source": None,
                "source_review_status": None,
                "source_reuse_eligible": False,
            }
        )
        production_row = {
            "schema_version": 1,
            "project_id": PROJECT_ID,
            "group_index": group_index,
            "position": offset,
            "role": "cover" if offset == 1 else "detail",
            "filename": _output_filename(offset),
            "target": _target_path(group_index, offset),
            "prompt": prompt,
            "prompt_sha256": prompt_sha256,
            "source": source_info["source"],
            "expected_text": [],
            "source_kind": source_kind,
            "source_review_status": source_info.get("source_review_status"),
            "source_reuse_eligible": source_info["source_reuse_eligible"],
            "generation_policy": "reuse_or_generate",
            "api_called": False,
            **lineage_fields,
        }
        if offset > 1:
            production_row["detail_index"] = detail_index_start + offset - 2
            production_row["local_label"] = role_name
        if batch_dir is not None:
            production_row["legacy_image_path"] = source_info["legacy_image_path"]
            production_row["legacy_raw_path"] = source_info["legacy_raw_path"]
        if offset == 1:
            production_row.update(
                {
                    "cover_style_version": COVER_STYLE_VERSION,
                    "cover_variant_id": f"cover-v{COVER_STYLE_VERSION}-{cover_signature[:12]}",
                    "cover_variant_signature": cover_signature,
                    "composition_signature": cover_signature,
                    "cover_variant": cover_variant,
                }
            )
        production_rows.append(production_row)

    first_lineage = lineages[0]
    group_row: dict[str, Any] = {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "group_index": group_index,
        "cover": {
            "group_index": group_index,
            "position": 1,
            "prompt_sha256": cover_prompt_sha256,
        },
        "details": detail_refs,
        "total_images": 9,
        "source_kind": source_kind,
        "cover_style_version": COVER_STYLE_VERSION,
        "cover_variant_signature": cover_signature,
        "composition_signature": cover_signature,
        "api_called": False,
    }
    registry_row: dict[str, Any] = {
        "group_index": group_index,
        "source_kind": source_kind,
        "cover_style_version": COVER_STYLE_VERSION,
        "cover_variant_signature": cover_signature,
        "composition_signature": cover_signature,
    }
    if first_lineage.get("kind") == "legacy_category_batch":
        legacy_group_fields = {
            "legacy_batch_id": first_lineage["batch_id"],
            "legacy_batch_dir": first_lineage["batch_dir"],
            "legacy_group_index": first_lineage["group_index"],
        }
        group_row.update(legacy_group_fields)
        registry_row.update(legacy_group_fields)
    return {
        "covers": cover_rows,
        "details": detail_rows,
        "groups": [group_row],
        "production": production_rows,
        "registry": registry_row,
        "signature": cover_signature,
    }


def _commit_state(state: dict[str, Any]) -> None:
    paths = state["paths"]
    _atomic_text(paths["cover"], _jsonl_text(state["covers"]))
    _atomic_text(paths["detail"], _jsonl_text(state["details"]))
    _atomic_text(paths["group"], _jsonl_text(state["groups"]))
    _atomic_text(paths["production"], _jsonl_text(state["production"]))
    _atomic_json(paths["registry"], state["registry"])


def _extend_state(state: dict[str, Any], additions: list[dict[str, Any]]) -> None:
    for addition in additions:
        state["covers"].extend(addition["covers"])
        state["details"].extend(addition["details"])
        state["groups"].extend(addition["groups"])
        state["production"].extend(addition["production"])
        state["registry"]["groups"].append(addition["registry"])
    registry_groups = state["registry"]["groups"]
    group_indexes = [int(row["group_index"]) for row in registry_groups]
    state["registry"]["created_groups"] = len(registry_groups)
    state["registry"]["next_group_index"] = max(
        int(state["registry"].get("next_group_index", 1)),
        max(group_indexes, default=0) + 1,
    )


def _read_legacy_groups(batch_dir: Path) -> list[tuple[int, list[dict[str, Any]]]]:
    prompts_path = batch_dir / "prompts.jsonl"
    records = _load_jsonl(prompts_path)
    if not records:
        raise PipeProjectManifestError(f"旧批次缺少有效 prompts.jsonl：{prompts_path}")
    if any(record.get("category_id") not in {None, PROJECT_ID} for record in records):
        raise PipeProjectManifestError("旧批次混入了其他类目的提示词")
    grouped: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("group_index") is None or record.get("index") is None:
            raise PipeProjectManifestError("旧批次记录缺少 group_index 或 index")
        grouped.setdefault(int(record["group_index"]), []).append(record)
    indexes = sorted(grouped)
    if indexes != list(range(indexes[0], indexes[-1] + 1)):
        raise PipeProjectManifestError("旧批次 group_index 不连续")
    config = load_category_config(PROJECT_ID)
    expected_roles = ["cover", *config["image_group_structure"]["detail_roles"]]
    result: list[tuple[int, list[dict[str, Any]]]] = []
    for group_index in indexes:
        group = sorted(grouped[group_index], key=lambda row: int(row["index"]))
        if [str(row.get("role")) for row in group] != expected_roles:
            raise PipeProjectManifestError(f"旧批次第 {group_index} 组不符合固定的 1+8 角色顺序")
        result.append((group_index, group))
    return result


def import_legacy_batch(
    project_dir: str | Path,
    batch_dir: str | Path,
    project_group_start: int = 1,
) -> dict[str, Any]:
    """Import a legacy batch by reference while leaving the source tree untouched."""
    if int(project_group_start) < 1:
        raise PipeProjectManifestError("project_group_start 必须是正整数")
    current_project_dir = Path(project_dir).expanduser().resolve()
    current_batch_dir = Path(batch_dir).expanduser().resolve()
    if not current_batch_dir.is_dir():
        raise PipeProjectManifestError(f"旧批次目录不存在：{current_batch_dir}")
    legacy_groups = _read_legacy_groups(current_batch_dir)
    state = _load_state(current_project_dir)
    existing_indexes = _existing_group_indexes(state)
    target_indexes = set(range(project_group_start, project_group_start + len(legacy_groups)))
    overlap = sorted(existing_indexes & target_indexes)
    if overlap:
        raise PipeProjectManifestError(f"导入范围与现有组重叠：{overlap}")
    if any(
        row.get("legacy_batch_id") == current_batch_dir.name
        for row in state["registry"]["groups"]
    ):
        raise PipeProjectManifestError(f"旧批次已经导入：{current_batch_dir.name}")

    used_signatures = set(_existing_cover_signatures(state))
    next_detail_index = _next_detail_index(state)
    additions: list[dict[str, Any]] = []
    reused_sources = 0
    for offset, (_, records) in enumerate(legacy_groups):
        group_index = project_group_start + offset
        lineages = [_legacy_lineage(current_batch_dir, record) for record in records]
        addition = _materialize_group(
            records,
            group_index,
            next_detail_index,
            "legacy_category_batch",
            lineages,
            batch_dir=current_batch_dir,
        )
        if addition["signature"] in used_signatures:
            raise PipeProjectManifestError(
                f"旧批次第 {records[0]['group_index']} 组与完整项目历史的封面签名重复"
            )
        used_signatures.add(addition["signature"])
        reused_sources += sum(bool(row.get("source")) for row in addition["production"])
        additions.append(addition)
        next_detail_index += 8

    _extend_state(state, additions)
    _commit_state(state)
    return {
        "project_id": PROJECT_ID,
        "operation": "import_legacy_batch",
        "legacy_batch_id": current_batch_dir.name,
        "group_start": project_group_start,
        "group_count": len(additions),
        "image_count": len(additions) * 9,
        "reusable_sources": reused_sources,
        "next_group_index": state["registry"]["next_group_index"],
        "api_called": False,
    }


def _generated_group_records(
    config: dict[str, Any], group_index: int, used_signatures: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roles = ["cover", *config["image_group_structure"]["detail_roles"]]
    cover_record: dict[str, Any] | None = None
    cover_lineage: dict[str, Any] | None = None
    for attempt in range(MAX_SIGNATURE_ATTEMPTS):
        seed = f"{PROJECT_ID}:group:{group_index}:cover:attempt:{attempt}"
        record = build_prompt_record(
            config,
            "cover",
            (group_index - 1) * 9 + 1,
            random.Random(seed),
            group_index,
        )
        if not scene_matches_legal_combination(config, "cover", record["scene"]):
            raise PipeProjectManifestError(f"提示词引擎为第 {group_index} 组返回了非法封面组合")
        signature = cover_variant_signature(record, select_cover_variant(record, config))
        if signature not in used_signatures:
            cover_record = record
            cover_lineage = _prompt_engine_lineage(seed, attempt, record)
            break
    if cover_record is None or cover_lineage is None:
        raise PipeProjectManifestError(
            f"第 {group_index} 组在 {MAX_SIGNATURE_ATTEMPTS} 次尝试后仍无法生成唯一封面签名"
        )

    records = [cover_record]
    lineages = [cover_lineage]
    for position, role in enumerate(roles[1:], start=2):
        seed = f"{PROJECT_ID}:group:{group_index}:detail:{position}:{role}"
        record = build_prompt_record(
            config,
            role,
            (group_index - 1) * 9 + position,
            random.Random(seed),
            group_index,
        )
        if not scene_matches_legal_combination(config, role, record["scene"]):
            raise PipeProjectManifestError(f"提示词引擎为第 {group_index} 组第 {position} 位返回了非法组合")
        records.append(record)
        lineages.append(_prompt_engine_lineage(seed, 0, record))
    return records, lineages


def append_groups(count: int, project_dir: str | Path = PROJECT_DIR) -> dict[str, Any]:
    """Append locally generated formal groups from registry.next_group_index."""
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise PipeProjectManifestError("count 必须是正整数")
    current_project_dir = Path(project_dir).expanduser().resolve()
    state = _load_state(current_project_dir)
    next_group_index = int(state["registry"].get("next_group_index", 1))
    if next_group_index < 1:
        raise PipeProjectManifestError("registry.next_group_index 必须是正整数")
    existing_indexes = _existing_group_indexes(state)
    requested_indexes = set(range(next_group_index, next_group_index + count))
    overlap = sorted(existing_indexes & requested_indexes)
    if overlap:
        raise PipeProjectManifestError(f"registry.next_group_index 与现有历史重叠：{overlap}")

    config = load_category_config(PROJECT_ID)
    used_signatures = set(_existing_cover_signatures(state))
    next_detail_index = _next_detail_index(state)
    additions: list[dict[str, Any]] = []
    for group_index in range(next_group_index, next_group_index + count):
        records, lineages = _generated_group_records(config, group_index, used_signatures)
        addition = _materialize_group(
            records,
            group_index,
            next_detail_index,
            "prompt_engine",
            lineages,
        )
        if addition["signature"] in used_signatures:
            raise PipeProjectManifestError(f"第 {group_index} 组封面签名与完整项目历史重复")
        used_signatures.add(addition["signature"])
        additions.append(addition)
        next_detail_index += 8

    _extend_state(state, additions)
    _commit_state(state)
    return {
        "project_id": PROJECT_ID,
        "operation": "append_groups",
        "group_start": next_group_index,
        "group_count": count,
        "image_count": count * 9,
        "next_group_index": state["registry"]["next_group_index"],
        "api_called": False,
    }


def _v2_validate_config(config: dict[str, Any]) -> dict[str, Any]:
    structure = config.get("image_group_structure")
    if not isinstance(structure, dict):
        raise PipeProjectManifestError("类目配置缺少 image_group_structure")
    if structure.get("structure_version") != V2_STRUCTURE_VERSION:
        raise PipeProjectManifestError("类目配置的 structure_version 与 v2 生成器不一致")
    if structure.get("generation_mode") != V2_GENERATION_MODE:
        raise PipeProjectManifestError("类目配置必须使用独立三拼面板生成模式")
    expected_counts = {
        "cover_count": 1,
        "triptych_count": 1,
        "triptych_panel_count": 3,
        "detail_count": 3,
        "total_per_group": 5,
        "generation_unit_count": 7,
        "service_roles_per_group": 6,
    }
    for key, expected in expected_counts.items():
        if int(structure.get(key, -1)) != expected:
            raise PipeProjectManifestError(f"类目配置 {key} 必须为 {expected}")
    role_pool = structure.get("service_role_pool") or structure.get("detail_roles")
    if not isinstance(role_pool, list) or len(role_pool) != 8 or len(set(role_pool)) != 8:
        raise PipeProjectManifestError("v2 服务角色池必须恰好保留八个不重复角色")
    if any(role not in config.get("scene_types", {}) for role in role_pool):
        raise PipeProjectManifestError("v2 服务角色池包含没有合法场景配置的角色")
    height_profiles = structure.get("height_profiles")
    if not isinstance(height_profiles, list) or len(height_profiles) != 3:
        raise PipeProjectManifestError("v2 必须配置三个高度档")
    expected_heights = [1408, 1472, 1536]
    actual_heights = [int(item.get("height", 0)) for item in height_profiles if isinstance(item, dict)]
    if actual_heights != expected_heights or any(int(item.get("width", 0)) != 1024 for item in height_profiles):
        raise PipeProjectManifestError("v2 高度档必须依次为 1024x1408、1024x1472、1024x1536")
    layouts = structure.get("triptych_layouts")
    if not isinstance(layouts, list) or len(layouts) != 3:
        raise PipeProjectManifestError("v2 必须配置三种三拼布局")
    layout_ids = [str(item.get("id", "")) for item in layouts if isinstance(item, dict)]
    if len(layout_ids) != 3 or len(set(layout_ids)) != 3:
        raise PipeProjectManifestError("三种三拼布局必须具有不同 id")
    for layout in layouts:
        panels = layout.get("panels") if isinstance(layout, dict) else None
        if not isinstance(panels, list) or [item.get("panel_index") for item in panels] != [1, 2, 3]:
            raise PipeProjectManifestError("每种三拼布局必须按顺序定义三个面板")
    return structure


def _v2_generation_id(group_index: int, generation_position: int) -> str:
    return f"{PROJECT_ID}:v2:g{group_index:04d}:u{generation_position:02d}"


def _v2_delivery_id(group_index: int, delivery_position: int) -> str:
    return f"{PROJECT_ID}:v2:g{group_index:04d}:d{delivery_position:02d}"


def _v2_delivery_target(group_index: int, delivery_position: int) -> str:
    filename = V2_DELIVERY_FILENAMES[delivery_position - 1]
    return f"output/{PROJECT_ID}/group_{group_index:04d}/{filename}"


def _v2_raw_target(group_index: int, generation_position: int, generation_role: str) -> str:
    if generation_role == "cover":
        filename = "u01_cover.png"
    elif generation_role == "triptych_panel":
        filename = f"u{generation_position:02d}_triptych_panel_{generation_position - 1}.png"
    else:
        filename = f"u{generation_position:02d}_detail_{generation_position - 4}.png"
    return (
        f"prompts/category_batches/{PROJECT_ID}/{V2_BATCH_NAME}/raw/"
        f"group_{group_index:04d}/{filename}"
    )


def _v2_role_assignment(role_pool: list[str], group_index: int) -> list[str]:
    rng = random.Random(f"{PROJECT_ID}:v2:group:{group_index}:service-role-assignment")
    return rng.sample(role_pool, 6)


def _v2_height_and_layout(
    structure: dict[str, Any], group_index: int
) -> tuple[dict[str, Any], dict[str, Any], int]:
    height_profiles = structure["height_profiles"]
    layouts = structure["triptych_layouts"]
    height = dict(height_profiles[(group_index - 1) % 3])
    layout = dict(layouts[((group_index - 1) // 3) % 3])
    cycle_index = ((group_index - 1) % 9) + 1
    return height, layout, cycle_index


def _v2_prompt_lineage(seed: str, source_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "prompt_engine",
        "generator": "tools.prompt_engine.build_prompt_record",
        "category_config": "configs/categories/pipe_unclogging.json",
        "structure_version": V2_STRUCTURE_VERSION,
        "seed": seed,
        "source_index": int(source_record["index"]),
        "source_role": str(source_record["role"]),
        "record_sha256": _record_sha256(source_record),
    }


def _v2_cover_record(
    config: dict[str, Any],
    group_index: int,
    global_index: int,
    height: dict[str, Any],
    layout: dict[str, Any],
    cycle_index: int,
    used_cover_signatures: set[str],
) -> tuple[dict[str, Any], str]:
    for attempt in range(MAX_SIGNATURE_ATTEMPTS):
        seed = f"{PROJECT_ID}:v2:group:{group_index}:cover:attempt:{attempt}"
        source_record = build_prompt_record(
            config,
            "cover",
            global_index,
            random.Random(seed),
            group_index,
        )
        if not scene_matches_legal_combination(config, "cover", source_record["scene"]):
            raise PipeProjectManifestError(f"v2 第 {group_index} 组封面使用了非法场景组合")
        variant = select_cover_variant(source_record, config)
        signature = cover_variant_signature(source_record, variant)
        if signature in used_cover_signatures:
            continue
        prompt = effective_prompt(
            {**source_record, "generation_kind": "cover", "service_role": None},
            "",
        )
        generation_id = _v2_generation_id(group_index, 1)
        final_size = f"{int(height['width'])}x{int(height['height'])}"
        record = {
            "schema_version": 2,
            "structure_version": V2_STRUCTURE_VERSION,
            "generation_mode": V2_GENERATION_MODE,
            "project_id": PROJECT_ID,
            "category_id": PROJECT_ID,
            "category_name": config["category_name"],
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
            "delivery_filename": V2_DELIVERY_FILENAMES[0],
            "delivery_target": _v2_delivery_target(group_index, 1),
            "raw_target": _v2_raw_target(group_index, 1, "cover"),
            "raw_size": "1024x1536",
            "expected_size": final_size,
            "final_size": final_size,
            "height_profile_id": height["id"],
            "triptych_layout_id": layout["id"],
            "variation_cycle_index": cycle_index,
            "scene": source_record["scene"],
            "source_positive_prompt": source_record["positive_prompt"],
            "negative_prompt": source_record["negative_prompt"],
            "positive_prompt": prompt,
            "prompt": prompt,
            "prompt_sha256": _sha256_text(prompt),
            "cover_style_version": COVER_STYLE_VERSION,
            "cover_variant_id": f"cover-v{COVER_STYLE_VERSION}-{signature[:12]}",
            "cover_variant_signature": signature,
            "cover_variant": variant,
            "source_lineage": _v2_prompt_lineage(seed, source_record),
            "status": "prompt_ready",
            "api_called": False,
        }
        return record, signature
    raise PipeProjectManifestError(
        f"v2 第 {group_index} 组在 {MAX_SIGNATURE_ATTEMPTS} 次尝试后仍没有唯一封面签名"
    )


def _v2_service_record(
    config: dict[str, Any],
    group_index: int,
    global_index: int,
    generation_position: int,
    generation_role: str,
    service_role: str,
    delivery_position: int,
    height: dict[str, Any],
    layout: dict[str, Any],
    cycle_index: int,
) -> dict[str, Any]:
    if generation_role not in {"triptych_panel", "detail"}:
        raise PipeProjectManifestError(f"不支持的 v2 施工生成角色：{generation_role}")
    seed = (
        f"{PROJECT_ID}:v2:group:{group_index}:unit:{generation_position}:"
        f"{generation_role}:{service_role}"
    )
    source_record = build_prompt_record(
        config,
        service_role,
        global_index,
        random.Random(seed),
        group_index,
    )
    if not scene_matches_legal_combination(config, service_role, source_record["scene"]):
        raise PipeProjectManifestError(
            f"v2 第 {group_index} 组生成单元 {generation_position} 使用了非法场景组合"
        )
    prompt = effective_prompt(
        {
            **source_record,
            "generation_kind": generation_role,
            "service_role": service_role,
        },
        "",
    )
    panel_index: int | None = None
    panel_box: dict[str, Any] | None = None
    if generation_role == "triptych_panel":
        panel_index = generation_position - 1
        panel_box = dict(layout["panels"][panel_index - 1])
        prompt += (
            f" 这是三拼图的第{panel_index}个独立原始面板，最终采用“{layout['name']}”布局；"
            "只生成一个真实施工现场，不生成拼图边框、文字、电话号码、图标或其他面板；"
            "人物、工具和实际管口必须处在本面板裁切后仍清楚可见的安全区域。"
        )
    generation_id = _v2_generation_id(group_index, generation_position)
    final_size = f"{int(height['width'])}x{int(height['height'])}"
    record = {
        "schema_version": 2,
        "structure_version": V2_STRUCTURE_VERSION,
        "generation_mode": V2_GENERATION_MODE,
        "project_id": PROJECT_ID,
        "category_id": PROJECT_ID,
        "category_name": config["category_name"],
        "index": global_index,
        "group_index": group_index,
        "generation_position": generation_position,
        "generation_id": generation_id,
        "role": generation_role,
        "generation_kind": generation_role,
        "generation_role": generation_role,
        "service_role": service_role,
        "prompt_role": service_role,
        "delivery_position": delivery_position,
        "delivery_filename": V2_DELIVERY_FILENAMES[delivery_position - 1],
        "delivery_target": _v2_delivery_target(group_index, delivery_position),
        "raw_target": _v2_raw_target(group_index, generation_position, generation_role),
        "raw_size": "1024x1536",
        "expected_size": final_size,
        "final_size": final_size,
        "height_profile_id": height["id"],
        "triptych_layout_id": layout["id"],
        "variation_cycle_index": cycle_index,
        "triptych_panel_index": panel_index,
        "triptych_panel_box": panel_box,
        "scene": source_record["scene"],
        "source_positive_prompt": source_record["positive_prompt"],
        "negative_prompt": source_record["negative_prompt"],
        "positive_prompt": prompt,
        "prompt": prompt,
        "prompt_sha256": _sha256_text(prompt),
        "source_lineage": _v2_prompt_lineage(seed, source_record),
        "status": "prompt_ready",
        "api_called": False,
    }
    return record


def _v2_delivery_row(
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
        "requires_history_deduplication": True,
    }
    if role == "cover":
        validation.update(
            {
                "requires_confirmed_signboard_phone": True,
                "requires_confirmed_center_phone": True,
            }
        )
        generation_policy = "generate_then_local_cover_overlay_and_crop"
    elif role == "triptych":
        validation.update(
            {
                "requires_three_visible_panels": True,
                "requires_three_distinct_service_roles": True,
            }
        )
        generation_policy = "compose_three_independent_panels_then_local_overlay"
    else:
        generation_policy = "generate_then_local_detail_overlay_and_crop"
    return {
        "schema_version": 2,
        "structure_version": V2_STRUCTURE_VERSION,
        "generation_mode": V2_GENERATION_MODE,
        "project_id": PROJECT_ID,
        "category_id": PROJECT_ID,
        "group_index": group_index,
        "position": delivery_position,
        "delivery_position": delivery_position,
        "delivery_id": _v2_delivery_id(group_index, delivery_position),
        "role": role,
        "filename": V2_DELIVERY_FILENAMES[delivery_position - 1],
        "target": _v2_delivery_target(group_index, delivery_position),
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


def _v2_manifest_payloads(
    config: dict[str, Any], count: int
) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    structure = _v2_validate_config(config)
    role_pool = [str(value) for value in structure["service_role_pool"]]
    generation_rows: list[dict[str, Any]] = []
    delivery_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    registry_groups: list[dict[str, Any]] = []
    used_cover_signatures: set[str] = set()

    for group_index in range(1, count + 1):
        height, layout, cycle_index = _v2_height_and_layout(structure, group_index)
        assigned_roles = _v2_role_assignment(role_pool, group_index)
        if len(set(assigned_roles)) != 6:
            raise PipeProjectManifestError(f"v2 第 {group_index} 组没有分配六个不同服务角色")
        first_global_index = (group_index - 1) * 7 + 1
        cover, cover_signature = _v2_cover_record(
            config,
            group_index,
            first_global_index,
            height,
            layout,
            cycle_index,
            used_cover_signatures,
        )
        used_cover_signatures.add(cover_signature)
        group_generation = [cover]
        for relative_index, service_role in enumerate(assigned_roles, start=1):
            generation_position = relative_index + 1
            generation_role = "triptych_panel" if relative_index <= 3 else "detail"
            delivery_position = 2 if generation_role == "triptych_panel" else relative_index - 1
            group_generation.append(
                _v2_service_record(
                    config,
                    group_index,
                    first_global_index + relative_index,
                    generation_position,
                    generation_role,
                    service_role,
                    delivery_position,
                    height,
                    layout,
                    cycle_index,
                )
            )
        if [row["generation_role"] for row in group_generation] != [
            "cover",
            "triptych_panel",
            "triptych_panel",
            "triptych_panel",
            "detail",
            "detail",
            "detail",
        ]:
            raise PipeProjectManifestError(f"v2 第 {group_index} 组生成单元顺序错误")

        group_deliveries = [
            _v2_delivery_row(
                group_index,
                1,
                "cover",
                height,
                layout,
                cycle_index,
                [group_generation[0]["generation_id"]],
                [],
            ),
            _v2_delivery_row(
                group_index,
                2,
                "triptych",
                height,
                layout,
                cycle_index,
                [row["generation_id"] for row in group_generation[1:4]],
                assigned_roles[:3],
            ),
        ]
        for detail_offset, generation_record in enumerate(group_generation[4:], start=3):
            group_deliveries.append(
                _v2_delivery_row(
                    group_index,
                    detail_offset,
                    "detail",
                    height,
                    layout,
                    cycle_index,
                    [generation_record["generation_id"]],
                    [generation_record["service_role"]],
                )
            )
        if [row["filename"] for row in group_deliveries] != list(V2_DELIVERY_FILENAMES):
            raise PipeProjectManifestError(f"v2 第 {group_index} 组交付文件名顺序错误")

        signature_material = {
            "cover_variant_signature": cover_signature,
            "height_profile_id": height["id"],
            "triptych_layout_id": layout["id"],
            "service_roles": assigned_roles,
            "scenes": [row["scene"] for row in group_generation],
        }
        composition_signature = _sha256_text(
            json.dumps(signature_material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        group_row = {
            "schema_version": 2,
            "structure_version": V2_STRUCTURE_VERSION,
            "generation_mode": V2_GENERATION_MODE,
            "project_id": PROJECT_ID,
            "group_index": group_index,
            "total_images": 5,
            "generation_unit_count": 7,
            "cover": {
                "delivery_id": group_deliveries[0]["delivery_id"],
                "generation_id": group_generation[0]["generation_id"],
                "filename": V2_DELIVERY_FILENAMES[0],
                "prompt_sha256": group_generation[0]["prompt_sha256"],
            },
            "triptych": {
                "delivery_id": group_deliveries[1]["delivery_id"],
                "filename": V2_DELIVERY_FILENAMES[1],
                "layout_id": layout["id"],
                "panel_generation_ids": [
                    row["generation_id"] for row in group_generation[1:4]
                ],
                "service_roles": assigned_roles[:3],
            },
            "details": [
                {
                    "delivery_id": delivery["delivery_id"],
                    "generation_id": generation["generation_id"],
                    "filename": delivery["filename"],
                    "service_role": generation["service_role"],
                    "prompt_sha256": generation["prompt_sha256"],
                }
                for delivery, generation in zip(group_deliveries[2:], group_generation[4:])
            ],
            "generation_units": [row["generation_id"] for row in group_generation],
            "delivery_files": [row["delivery_id"] for row in group_deliveries],
            "service_roles": assigned_roles,
            "height_profile": height,
            "final_size": group_deliveries[0]["final_size"],
            "triptych_layout": layout,
            "variation_cycle_index": cycle_index,
            "cover_variant_signature": cover_signature,
            "composition_signature": composition_signature,
            "anti_homogeneity_axes": [
                "final_height",
                "triptych_layout",
                "six_distinct_service_roles",
                "storefront_variant",
                "camera_and_distance",
                "worker_action_and_tool",
            ],
            "status": "prompt_ready",
            "api_called": False,
        }
        registry_row = {
            "group_index": group_index,
            "structure_version": V2_STRUCTURE_VERSION,
            "generation_mode": V2_GENERATION_MODE,
            "group_size": 5,
            "generation_unit_count": 7,
            "final_size": group_deliveries[0]["final_size"],
            "height_profile_id": height["id"],
            "triptych_layout_id": layout["id"],
            "variation_cycle_index": cycle_index,
            "service_roles": assigned_roles,
            "cover_variant_signature": cover_signature,
            "composition_signature": composition_signature,
            "status": "prompt_ready",
        }
        generation_rows.extend(group_generation)
        delivery_rows.extend(group_deliveries)
        group_rows.append(group_row)
        registry_groups.append(registry_row)

    first_nine_pairs = {
        (row["height_profile_id"], row["triptych_layout_id"])
        for row in registry_groups[:9]
    }
    if count >= 9 and len(first_nine_pairs) != 9:
        raise PipeProjectManifestError("前九组没有覆盖三种高度乘三种三拼布局的九种组合")
    created_at = datetime.now(timezone.utc).isoformat()
    registry = {
        "schema_version": 2,
        "structure_version": V2_STRUCTURE_VERSION,
        "generation_mode": V2_GENERATION_MODE,
        "project_id": PROJECT_ID,
        "group_size": 5,
        "generation_unit_count": 7,
        "cover_count": 1,
        "triptych_count": 1,
        "triptych_panel_count": 3,
        "detail_count": 3,
        "created_groups": count,
        "next_group_index": count + 1,
        "active_batch": f"prompts/category_batches/{PROJECT_ID}/{V2_BATCH_NAME}",
        "groups": registry_groups,
        "created_at": created_at,
        "api_called": False,
    }
    batch_manifest_rows = [
        {
            "schema_version": 2,
            "structure_version": V2_STRUCTURE_VERSION,
            "generation_mode": V2_GENERATION_MODE,
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
        "schema_version": 2,
        "structure_version": V2_STRUCTURE_VERSION,
        "generation_mode": V2_GENERATION_MODE,
        "category_id": PROJECT_ID,
        "category_name": config["category_name"],
        "mode": "active_v2_5_group_manifests",
        "group_count": count,
        "generation_unit_count": len(generation_rows),
        "cover_generation_count": count,
        "triptych_panel_generation_count": count * 3,
        "detail_generation_count": count * 3,
        "delivery_file_count": len(delivery_rows),
        "delivery_structure": {
            "cover_count": 1,
            "triptych_count": 1,
            "detail_count": 3,
            "total_per_group": 5,
        },
        "height_profiles": structure["height_profiles"],
        "triptych_layouts": [
            {"id": item["id"], "name": item["name"]} for item in structure["triptych_layouts"]
        ],
        "first_nine_height_layout_combinations": [
            {
                "group_index": row["group_index"],
                "height_profile_id": row["height_profile_id"],
                "triptych_layout_id": row["triptych_layout_id"],
            }
            for row in registry_groups[:9]
        ],
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
        "cover_prompts.jsonl": _jsonl_text(
            [row for row in generation_rows if row["generation_role"] == "cover"]
        ),
        "triptych_panel_prompts.jsonl": _jsonl_text(
            [row for row in generation_rows if row["generation_role"] == "triptych_panel"]
        ),
        "detail_prompts.jsonl": _jsonl_text(
            [row for row in generation_rows if row["generation_role"] == "detail"]
        ),
        "manifest.jsonl": _jsonl_text(batch_manifest_rows),
        "delivery_manifest.jsonl": _jsonl_text(delivery_rows),
        "summary.json": json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        "README_THIS_BATCH.txt": (
            "管道疏通活动 v2 本地清单\n\n"
            "每组交付 5 张：1 张门店首图、1 张三拼图、3 张单张详情图。\n"
            "每组三拼图使用 3 个独立生成面板；加上首图和 3 张详情，共 7 个生成单元。\n"
            "同组 6 个施工场景使用 6 个不同服务角色。\n"
            "同组五张交付图尺寸一致，组间按 1024x1408、1024x1472、1024x1536 轮换。\n"
            "三种三拼布局按每三组一个区块轮换，前九组覆盖九种高度与布局组合。\n"
            "本批次只创建本地提示词与清单，没有调用图片接口，也没有生成图片。\n"
        ),
        "summary_readable.txt": (
            f"已创建 {count} 组活动清单。\n"
            f"生成单元：{len(generation_rows)} 个。\n"
            f"交付文件位：{len(delivery_rows)} 个。\n"
            "图片接口调用：0。\n"
        ),
    }
    return schema_files, batch_files, summary


def create_v2_5_groups(
    count: int,
    project_dir: str | Path = PROJECT_DIR,
    batch_dir: str | Path | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Create the active v2 manifest set once; no image or network work occurs."""
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise PipeProjectManifestError("v2 count 必须是正整数")
    current_project_dir = Path(project_dir).expanduser().resolve()
    schema_dir = current_project_dir / "groups" / V2_SCHEMA_DIR_NAME
    current_batch_dir = (
        Path(batch_dir).expanduser().resolve()
        if batch_dir is not None
        else ROOT / "prompts" / "category_batches" / PROJECT_ID / V2_BATCH_NAME
    )
    if schema_dir.exists() or current_batch_dir.exists():
        if not replace_existing:
            existing = schema_dir if schema_dir.exists() else current_batch_dir
            raise PipeProjectManifestError(f"v2 活动清单已存在，禁止隐式覆盖：{existing}")
        registry_path = schema_dir / "registry.json"
        summary_path = current_batch_dir / "summary.json"
        if not registry_path.is_file() or not summary_path.is_file():
            raise PipeProjectManifestError("只能刷新由本生成器完整创建的 v2 活动清单")
        registry_marker = json.loads(registry_path.read_text(encoding="utf-8-sig"))
        summary_marker = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        for marker in (registry_marker, summary_marker):
            if (
                marker.get("project_id", marker.get("category_id")) != PROJECT_ID
                or marker.get("structure_version") != V2_STRUCTURE_VERSION
                or marker.get("generation_mode") != V2_GENERATION_MODE
            ):
                raise PipeProjectManifestError("现有目录不是当前 v2 结构，禁止刷新")
    config = load_category_config(PROJECT_ID)
    schema_files, batch_files, summary = _v2_manifest_payloads(config, count)
    schema_dir.mkdir(parents=True, exist_ok=replace_existing)
    current_batch_dir.mkdir(parents=True, exist_ok=replace_existing)
    for relative_name, content in schema_files.items():
        _atomic_text(schema_dir / relative_name, content)
    for relative_name, content in batch_files.items():
        _atomic_text(current_batch_dir / relative_name, content)
    return {
        "project_id": PROJECT_ID,
        "operation": "refresh_v2_5_groups" if replace_existing else "create_v2_5_groups",
        "structure_version": V2_STRUCTURE_VERSION,
        "generation_mode": V2_GENERATION_MODE,
        "group_count": count,
        "generation_unit_count": int(summary["generation_unit_count"]),
        "delivery_file_count": int(summary["delivery_file_count"]),
        "schema_dir": _portable_path(schema_dir),
        "batch_dir": _portable_path(current_batch_dir),
        "api_called": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="导入或续写管道疏通正式组图清单；仅做本地 manifest 工作，不调用生图 API。"
    )
    parser.add_argument("--project-dir", default=str(PROJECT_DIR))
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--import-batch", help="只读导入旧 category batch 目录")
    actions.add_argument("--count", type=int, help="从 registry.next_group_index 续写的组数")
    actions.add_argument(
        "--create-v2-5",
        type=int,
        metavar="GROUP_COUNT",
        help="一次性创建活动 v2 的 5 张交付/7 生成单元清单",
    )
    actions.add_argument(
        "--refresh-v2-5",
        type=int,
        metavar="GROUP_COUNT",
        help="仅刷新由本脚本创建且结构标记匹配的活动 v2 清单",
    )
    parser.add_argument("--project-group-start", type=int, default=1)
    args = parser.parse_args(argv)
    if args.import_batch:
        result = import_legacy_batch(args.project_dir, args.import_batch, args.project_group_start)
    elif args.create_v2_5 is not None:
        result = create_v2_5_groups(args.create_v2_5, args.project_dir)
    elif args.refresh_v2_5 is not None:
        result = create_v2_5_groups(
            args.refresh_v2_5,
            args.project_dir,
            replace_existing=True,
        )
    else:
        result = append_groups(args.count, args.project_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
