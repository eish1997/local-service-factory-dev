"""Persistent dashboard delivery queue and category image packaging."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
DEFAULT_MAX_ARCHIVE_BYTES = 1_000_000_000
ARCHIVE_HEADROOM_RATIO = 0.97


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso(),
        "projects": {},
        "package_history": [],
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return empty_state()
    state = json.loads(path.read_text(encoding="utf-8-sig"))
    if state.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("看板待交付清单版本不受支持")
    if not isinstance(state.get("projects"), dict):
        raise RuntimeError("看板待交付清单缺少 projects")
    if not isinstance(state.get("package_history"), list):
        state["package_history"] = []
    return state


def write_state(path: Path, state: dict[str, Any]) -> None:
    state = dict(state)
    state["schema_version"] = SCHEMA_VERSION
    state["updated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _project_state(state: dict[str, Any], project_id: str) -> dict[str, Any]:
    projects = state.setdefault("projects", {})
    project = projects.setdefault(project_id, {"pending_groups": {}})
    if not isinstance(project.get("pending_groups"), dict):
        project["pending_groups"] = {}
    return project


def _serialized_state(fn):
    from functools import wraps
    @wraps(fn)
    def guarded(state_path,*args,**kwargs):
        from tools.task_library import lock
        with lock(Path(state_path).with_suffix('.lock')):
            return fn(state_path,*args,**kwargs)
    return guarded

@_serialized_state

def register_pending_groups(
    state_path: Path,
    project_id: str,
    group_indices: Iterable[int],
    *,
    expected_image_count: int,
    job_id: str | None = None,
) -> dict[str, Any]:
    if expected_image_count < 1:
        raise RuntimeError("看板每组预期图片数必须大于0")
    state = load_state(state_path)
    project = _project_state(state, project_id)
    pending = project["pending_groups"]
    registered: list[int] = []
    for raw_index in sorted(set(group_indices)):
        group_index = int(raw_index)
        if group_index < 1:
            raise RuntimeError("看板组号必须为正整数")
        key = str(group_index)
        previous = pending.get(key) if isinstance(pending.get(key), dict) else {}
        pending[key] = {
            "group_index": group_index,
            "expected_image_count": expected_image_count,
            "first_added_at": previous.get("first_added_at") or now_iso(),
            "updated_at": now_iso(),
            "last_job_id": job_id or previous.get("last_job_id"),
        }
        registered.append(group_index)
    write_state(state_path, state)
    return {"project_id": project_id, "registered_groups": registered}


def pending_group_entries(state: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    project = state.get("projects", {}).get(project_id, {})
    pending = project.get("pending_groups", {})
    if not isinstance(pending, dict):
        return []
    return sorted(
        (dict(item) for item in pending.values() if isinstance(item, dict)),
        key=lambda item: int(item.get("group_index", 0)),
    )


@_serialized_state
def mark_groups_packaged(
    state_path: Path,
    project_id: str,
    group_indices: Iterable[int],
    archives: Iterable[Path],
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    groups = sorted(set(int(value) for value in group_indices))
    state = load_state(state_path)
    project = _project_state(state, project_id)
    pending = project["pending_groups"]
    missing = [group for group in groups if str(group) not in pending]
    if missing:
        raise RuntimeError(
            "以下组不在看板待打包清单中：" + ", ".join(str(value) for value in missing)
        )
    for group in groups:
        pending.pop(str(group), None)
    record = {
        "project_id": project_id,
        "groups": groups,
        "archives": [str(path.resolve()) for path in archives],
        "manifest": str(manifest_path.resolve()) if manifest_path else None,
        "packaged_at": now_iso(),
    }
    state.setdefault("package_history", []).append(record)
    write_state(state_path, state)
    return record


def desktop_directory() -> Path:
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(260)
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer)
        if result == 0 and buffer.value:
            return Path(buffer.value).resolve()
    return (Path.home() / "Desktop").resolve()


def _group_files(
    output_root: Path,
    group_index: int,
    expected_image_count: int,
) -> list[Path]:
    group_dir = output_root / f"group_{group_index:04d}"
    if not group_dir.is_dir():
        raise RuntimeError(f"待打包组目录不存在：{group_dir}")
    files = sorted(path for path in group_dir.glob("*.png") if path.is_file())
    if len(files) != expected_image_count:
        raise RuntimeError(
            f"第 {group_index} 组应有 {expected_image_count} 张 PNG，实际 {len(files)} 张，禁止打包归档"
        )
    return files


def _partition_groups(
    groups: list[tuple[int, list[Path]]], max_archive_bytes: int
) -> list[list[tuple[int, list[Path]]]]:
    safe_limit = int(max_archive_bytes * ARCHIVE_HEADROOM_RATIO)
    parts: list[list[tuple[int, list[Path]]]] = []
    current: list[tuple[int, list[Path]]] = []
    current_size = 0
    for group in groups:
        group_size = sum(path.stat().st_size for path in group[1])
        if group_size > safe_limit:
            raise RuntimeError(f"第 {group[0]} 组单组大小已超过压缩包限制")
        if current and current_size + group_size > safe_limit:
            parts.append(current)
            current = []
            current_size = 0
        current.append(group)
        current_size += group_size
    if current:
        parts.append(current)
    return parts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_pending_groups(
    project_root: Path,
    state_path: Path,
    project_id: str,
    group_start: int,
    group_count: int,
    destination_dir: Path | None = None,
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    manifest_dir: Path | None = None,
) -> dict[str, Any]:
    if group_start < 1 or group_count < 1:
        raise RuntimeError("group_start 和 group_count 必须为正整数")
    if max_archive_bytes < 1_000_000:
        raise RuntimeError("压缩包大小上限过小")
    state = load_state(state_path)
    entries = {
        int(item["group_index"]): item
        for item in pending_group_entries(state, project_id)
    }
    group_indices = list(range(group_start, group_start + group_count))
    missing = [group for group in group_indices if group not in entries]
    if missing:
        raise RuntimeError(
            "以下组不在看板待打包清单中：" + ", ".join(str(value) for value in missing)
        )
    output_root = (project_root / "output" / project_id).resolve()
    groups = [
        (
            group,
            _group_files(
                output_root,
                group,
                int(entries[group].get("expected_image_count", 0)),
            ),
        )
        for group in group_indices
    ]
    parts = _partition_groups(groups, max_archive_bytes)
    destination = (destination_dir or desktop_directory()).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    created: list[Path] = []
    try:
        for part_index, part in enumerate(parts, start=1):
            first_group = part[0][0]
            last_group = part[-1][0]
            name = (
                f"{project_id}_groups_{first_group:04d}-{last_group:04d}_"
                f"part{part_index:02d}_{timestamp}.zip"
            )
            target = destination / name
            temporary = target.with_suffix(target.suffix + ".part")
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                for group_index, files in part:
                    for path in files:
                        archive.write(path, f"group_{group_index:04d}/{path.name}")
            if temporary.stat().st_size > max_archive_bytes:
                raise RuntimeError(f"压缩包超过大小上限：{temporary}")
            temporary.replace(target)
            created.append(target)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        for path in destination.glob(f"{project_id}_groups_*_{timestamp}.zip.part"):
            path.unlink(missing_ok=True)
        raise

    manifest_root = (manifest_dir or (project_root / ".runtime" / "package_manifests")).resolve()
    manifest_root.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_root / (
        f"{project_id}_groups_{group_start:04d}-{group_start + group_count - 1:04d}_{timestamp}.json"
    )
    manifest = {
        "schema_version": 1,
        "project_id": project_id,
        "group_start": group_start,
        "group_count": group_count,
        "groups": group_indices,
        "images_only": True,
        "max_archive_bytes": max_archive_bytes,
        "archives": [
            {"path": str(path), "size": path.stat().st_size, "sha256": _sha256(path)}
            for path in created
        ],
        "created_at": now_iso(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    mark_groups_packaged(
        state_path,
        project_id,
        group_indices,
        created,
        manifest_path=manifest_path,
    )
    return {**manifest, "manifest_path": str(manifest_path)}
