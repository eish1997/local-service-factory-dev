"""Append-only project inventory and permanent visual fingerprint history.

The image folders in ``output/<category>/group_xxxx`` are working stock.  A
user may delete a group after it has been consumed, so the files themselves
cannot be the duplicate-detection database.  ``inventory_history.jsonl`` is
therefore the source of truth: state changes are appended and never rewritten.
``inventory.json`` is only a rebuildable, beginner-friendly snapshot.

This module is intentionally local-only.  It does not generate, copy, move, or
delete production images and it never calls a network API.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
PROJECT_REGISTRY_PATH = ROOT / "projects" / "registry.json"
OUTPUT_ROOT = (ROOT / "output").resolve()
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PIPE_DELIVERY_ROLES = ["cover", "triptych", "detail", "detail", "detail"]
DEDUP_FAMILY_BY_ROLE = {
    "cover": "storefront",
    "triptych": "collage",
    "triptych_panel": "work_scene",
    "detail": "work_scene",
}

HISTORY_FILENAME = "inventory_history.jsonl"
DEFAULT_SNAPSHOT_FILENAME = "inventory.json"
EVENT_SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 2


class InventoryError(RuntimeError):
    """Base error for inventory operations."""


class GroupNotDeliveryReadyError(InventoryError):
    """Raised when a group has not passed the normal delivery audit."""


class ExactDuplicateError(InventoryError):
    """Raised when an image exactly matches permanent project history."""


class NearDuplicateError(InventoryError):
    """Raised when a visually similar image needs human review."""


class InventoryStateError(InventoryError):
    """Raised for an invalid inventory state transition."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path: Path, payload: Any) -> None:
    """Write a rebuildable snapshot atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InventoryError(f"账本第 {line_number} 行损坏，已停止，避免覆盖历史。") from exc
        if not isinstance(value, dict):
            raise InventoryError(f"账本第 {line_number} 行不是对象，已停止。")
        rows.append(value)
    return rows


def _append_events(path: Path, events: Iterable[dict[str, Any]]) -> None:
    """Append complete JSON lines without ever rewriting existing history."""

    rows = list(events)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        for event in rows
    )
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _history_lock(history_path: Path, timeout_seconds: float = 10.0) -> Iterable[None]:
    """Serialize history checks and appends across local processes."""

    history_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = history_path.with_suffix(history_path.suffix + ".lock")
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"pid={os.getpid()} time={now_iso()}\n".encode("utf-8"))
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > 300
            except FileNotFoundError:
                continue
            if stale:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise InventoryError("库存账本正被另一个任务使用，请稍后重试。")
            time.sleep(0.05)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def project_definition(project_id: str) -> tuple[dict[str, Any], Path]:
    if not project_id or any(char in project_id for char in ("/", "\\", "..")):
        raise ValueError(f"invalid project id: {project_id!r}")
    registry = load_json(PROJECT_REGISTRY_PATH)
    entry = next(
        (item for item in registry.get("projects", []) if item.get("id") == project_id),
        None,
    )
    if entry is None:
        raise ValueError(f"unknown project: {project_id}")
    path = (ROOT / str(entry["definition"])).resolve()
    projects_root = (ROOT / "projects").resolve()
    if projects_root not in path.parents or not path.is_file():
        raise ValueError(f"invalid project definition path: {path}")
    definition = load_json(path)
    if str(definition.get("id")) != project_id:
        raise ValueError(f"project definition id mismatch: {path}")
    return definition, path


def safe_project_output(definition: dict[str, Any]) -> Path:
    value = str(definition.get("output_dir") or "")
    if not value:
        raise ValueError("project output_dir is missing")
    candidate = Path(value)
    output = candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()
    if output == OUTPUT_ROOT or OUTPUT_ROOT not in output.parents:
        raise ValueError(f"project output must be a category folder below {OUTPUT_ROOT}")
    return output


def as_project_path(value: str | Path) -> Path:
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _project_files(
    project_id: str,
) -> tuple[dict[str, Any], Path, Path, Path, Path]:
    definition, definition_path = project_definition(project_id)
    project_dir = definition_path.parent.resolve()
    history_value = definition.get("inventory_history")
    history_path = (
        as_project_path(str(history_value))
        if history_value
        else (project_dir / "groups" / HISTORY_FILENAME).resolve()
    )
    inventory_value = definition.get("inventory_snapshot") or definition.get("inventory_ledger")
    snapshot_path = (
        as_project_path(str(inventory_value))
        if inventory_value
        else (project_dir / "groups" / DEFAULT_SNAPSHOT_FILENAME).resolve()
    )
    production_value = definition.get("prompt_sources", {}).get("production_manifest")
    production_path = (
        as_project_path(str(production_value))
        if production_value
        else (project_dir / "groups" / "production_manifest.jsonl").resolve()
    )
    for label, path in (
        ("history", history_path),
        ("snapshot", snapshot_path),
        ("production manifest", production_path),
    ):
        if project_dir not in path.parents:
            raise ValueError(f"project {label} path escapes project directory: {path}")
    return definition, definition_path, history_path, snapshot_path, production_path


def _expected_size(record: dict[str, Any]) -> tuple[int, int] | None:
    value = record.get("expected_size") or record.get("final_size")
    if value is None:
        return None
    if isinstance(value, str):
        import re

        match = re.fullmatch(r"(\d+)x(\d+)", value)
        if match:
            return int(match.group(1)), int(match.group(2))
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(item, int) and item > 0 for item in value)
    ):
        return int(value[0]), int(value[1])
    raise GroupNotDeliveryReadyError(
        f"第 {record.get('group_index')} 组第 {record.get('position')} 张 expected_size 无效。"
    )


def _delivery_position(record: dict[str, Any]) -> int:
    return int(record.get("delivery_position") or record.get("position") or 0)


def _dedup_family(role: str | None, stored: str | None = None) -> str:
    if stored:
        return str(stored)
    normalized = str(role or "detail")
    return DEDUP_FAMILY_BY_ROLE.get(normalized, normalized)


def valid_image(path: Path, expected_size: tuple[int, int] | None = None) -> bool:
    if (
        path.suffix.lower() not in IMAGE_SUFFIXES
        or not path.is_file()
        or path.stat().st_size <= 0
    ):
        return False
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            return (
                image.width > 0
                and image.height > 0
                and (expected_size is None or image.size == expected_size)
            )
    except Exception:
        return False


def _hex_bits(bits: Iterable[bool], digits: int) -> str:
    value = 0
    count = 0
    for bit in bits:
        value = (value << 1) | int(bool(bit))
        count += 1
    if count != digits * 4:
        raise ValueError(f"expected {digits * 4} bits, got {count}")
    return f"{value:0{digits}x}"


def _scene_only_image(image: Any, role: str | None = None) -> Any:
    """Keep scene bands while excluding deterministic local text overlays."""

    from PIL import Image, ImageOps

    rgb = ImageOps.exif_transpose(image).convert("RGB")
    width, height = rgb.size
    if width < 1 or height < 3:
        return rgb.resize((256, 256), getattr(Image, "Resampling", Image).LANCZOS)
    if role == "cover":
        # Exclude the 5.5%-30.5% signboard, 43%-53.5% phone text and
        # 70%-96.5% service words used by the pipe cover overlay.
        bands = ((0.305, 0.43), (0.535, 0.70))
    elif role == "triptych":
        # Keep the three-panel scene area and avoid the local phone/service footer.
        bands = ((0.02, 0.40), (0.40, 0.78))
    elif role == "detail":
        # Exclude the detail label, 49%-58.5% phone bar and 83.5%-97.5% grid.
        bands = ((0.11, 0.49), (0.585, 0.835))
    else:
        bands = ((0.20, 0.43), (0.585, 0.78))
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    crops = []
    for start_ratio, end_ratio in bands:
        start = min(height - 1, max(0, int(round(height * start_ratio))))
        end = min(height, max(start + 1, int(round(height * end_ratio))))
        crops.append(rgb.crop((0, start, width, end)).resize((256, 128), resampling))
    scene = Image.new("RGB", (256, 256))
    scene.paste(crops[0], (0, 0))
    scene.paste(crops[1], (0, 128))
    return scene


def _phash64(scene: Any) -> str:
    """Compute a dependency-free 64-bit DCT perceptual hash."""

    from PIL import Image

    resampling = getattr(Image, "Resampling", Image).LANCZOS
    resized = scene.convert("L").resize((32, 32), resampling)
    pixels = list(
        resized.get_flattened_data()
        if hasattr(resized, "get_flattened_data")
        else resized.getdata()
    )
    cosine = [
        [math.cos((2 * coordinate + 1) * frequency * math.pi / 64.0) for coordinate in range(32)]
        for frequency in range(8)
    ]
    coefficients: list[float] = []
    for vertical_frequency in range(8):
        vertical_cosine = cosine[vertical_frequency]
        for horizontal_frequency in range(8):
            horizontal_cosine = cosine[horizontal_frequency]
            total = 0.0
            for y in range(32):
                row_offset = y * 32
                row_total = 0.0
                for x in range(32):
                    row_total += pixels[row_offset + x] * horizontal_cosine[x]
                total += row_total * vertical_cosine[y]
            coefficients.append(total)
    threshold = statistics.median(coefficients[1:])
    return _hex_bits((value >= threshold for value in coefficients), 16)


def _dhash256(scene: Any) -> str:
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image).LANCZOS
    resized = scene.convert("L").resize((17, 16), resampling)
    pixels = list(
        resized.get_flattened_data()
        if hasattr(resized, "get_flattened_data")
        else resized.getdata()
    )
    bits = (
        pixels[row * 17 + column] > pixels[row * 17 + column + 1]
        for row in range(16)
        for column in range(16)
    )
    return _hex_bits(bits, 64)


def image_fingerprint(path: Path, role: str | None = None) -> dict[str, Any]:
    """Return exact file/pixel hashes and overlay-resistant scene hashes."""

    from PIL import Image, ImageOps

    if not valid_image(path):
        raise InventoryError(f"图片不存在或已损坏：{path}")
    file_bytes = path.read_bytes()
    with Image.open(path) as source:
        canonical = ImageOps.exif_transpose(source).convert("RGB")
        canonical.load()
        width, height = canonical.size
        pixel_digest = hashlib.sha256()
        pixel_digest.update(width.to_bytes(8, "big", signed=False))
        pixel_digest.update(height.to_bytes(8, "big", signed=False))
        pixel_digest.update(canonical.tobytes())
        scene = _scene_only_image(canonical, role)
        scene_phash64 = _phash64(scene)
        scene_dhash256 = _dhash256(scene)
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()
    rgb_sha256 = pixel_digest.hexdigest()
    return {
        "file_sha256": file_sha256,
        "rgb_sha256": rgb_sha256,
        "scene_phash64": scene_phash64,
        "scene_dhash256": scene_dhash256,
        "width": width,
        "height": height,
        "bytes": len(file_bytes),
        # Compatibility alias for the first draft and simple external readers.
        "sha256": file_sha256,
    }


def hamming_hex(left: str, right: str) -> int:
    if len(left) != len(right):
        raise ValueError("hash widths differ")
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _history_state(
    events: list[dict[str, Any]], project_id: str, category: str
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    latest: dict[int, dict[str, Any]] = {}
    available_events: list[dict[str, Any]] = []
    for event in events:
        if event.get("project_id") != project_id or event.get("category") != category:
            raise InventoryError("账本中混入了其他项目或类目的记录，已停止。")
        event_type = event.get("event_type")
        group_index = int(event.get("group_index", 0))
        if group_index < 1:
            raise InventoryError("账本中存在无效组号，已停止。")
        if event_type == "available":
            if not isinstance(event.get("images"), list) or not event["images"]:
                raise InventoryError("账本中的 available 记录缺少图片指纹，已停止。")
            available_events.append(event)
            latest[group_index] = event
        elif event_type == "consumed":
            previous = latest.get(group_index)
            if previous is None:
                raise InventoryError(f"第 {group_index} 组没有入库记录却被标记已用。")
            latest[group_index] = event
        else:
            raise InventoryError(f"未知库存事件：{event_type!r}")
    return latest, available_events


def _available_event_for_group(
    events: list[dict[str, Any]], group_index: int
) -> dict[str, Any] | None:
    for event in reversed(events):
        if int(event.get("group_index", 0)) == group_index and event.get("event_type") == "available":
            return event
    return None


def _production_records(production_path: Path, start: int, count: int) -> list[dict[str, Any]]:
    if not production_path.is_file():
        raise InventoryError(f"生产清单不存在：{production_path}")
    end = start + count
    selected = [
        row
        for row in load_jsonl(production_path)
        if start <= int(row.get("group_index", 0)) < end
    ]
    prepared = {int(row["group_index"]) for row in selected}
    missing = [index for index in range(start, end) if index not in prepared]
    if missing:
        raise InventoryError(f"这些组还没有生产清单：{missing}")
    return selected


def _group_images(
    records: list[dict[str, Any]],
    expected_images: int,
    expected_roles: list[str] | None = None,
    *,
    require_expected_size: bool = False,
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in records:
        grouped.setdefault(int(row["group_index"]), []).append(row)
    prepared: dict[int, list[dict[str, Any]]] = {}
    for group_index, rows in grouped.items():
        rows = sorted(rows, key=_delivery_position)
        if len(rows) != expected_images:
            raise GroupNotDeliveryReadyError(
                f"第 {group_index} 组应有 {expected_images} 张，清单中实际 {len(rows)} 张。"
            )
        positions = [_delivery_position(row) for row in rows]
        if positions != list(range(1, expected_images + 1)):
            raise GroupNotDeliveryReadyError(f"第 {group_index} 组图片位置不完整。")
        roles = [str(row.get("role") or "") for row in rows]
        if expected_roles is not None and roles != expected_roles:
            raise GroupNotDeliveryReadyError(
                f"第 {group_index} 组角色顺序应为 {expected_roles}，实际为 {roles}。"
            )
        if require_expected_size:
            missing_size = [
                _delivery_position(row)
                for row in rows
                if _expected_size(row) is None
            ]
            if missing_size:
                raise GroupNotDeliveryReadyError(
                    f"第 {group_index} 组这些位置缺少 expected_size：{missing_size}。"
                )
        prepared[group_index] = rows
    return prepared


def _fingerprinted_group(
    group_index: int,
    records: list[dict[str, Any]],
    output_root: Path,
) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    expected_group_dir = (output_root / f"group_{group_index:04d}").resolve()
    for record in records:
        target = as_project_path(str(record["target"]))
        if target.parent.resolve() != expected_group_dir:
            raise GroupNotDeliveryReadyError(
                f"第 {group_index} 组图片不在规定目录 {expected_group_dir}，不能入库。"
            )
        expected_size = _expected_size(record)
        if not valid_image(target, expected_size):
            raise GroupNotDeliveryReadyError(
                f"第 {group_index} 组的 {record.get('filename') or target.name} "
                "缺失、损坏或尺寸不符合 expected_size，不能入库。"
            )
        role = str(record.get("role") or "detail")
        image_entry = {
            "position": _delivery_position(record),
            "role": role,
            "dedup_family": _dedup_family(role),
            "filename": str(record.get("filename") or target.name),
            "path": _relative(target),
            "prompt_sha256": str(record.get("prompt_sha256") or ""),
            "expected_size": list(expected_size) if expected_size else None,
            "fingerprint": image_fingerprint(target, role),
        }
        if role == "triptych":
            validation_path = target.with_suffix(".validation.json")
            if not validation_path.is_file():
                raise GroupNotDeliveryReadyError(
                    f"第 {group_index} 组三拼图缺少组件指纹验收记录。"
                )
            validation = load_json(validation_path)
            panel_rows = validation.get("panel_fingerprints")
            if not isinstance(panel_rows, list) or len(panel_rows) != 3:
                raise GroupNotDeliveryReadyError(
                    f"第 {group_index} 组三拼图必须保存3个面板指纹。"
                )
            components: list[dict[str, Any]] = []
            required_fingerprint_fields = {
                "file_sha256",
                "rgb_sha256",
                "scene_phash64",
                "scene_dhash256",
                "width",
                "height",
            }
            for expected_panel_index, panel in enumerate(panel_rows, start=1):
                if not isinstance(panel, dict):
                    raise GroupNotDeliveryReadyError(
                        f"第 {group_index} 组三拼图面板指纹格式无效。"
                    )
                fingerprint = panel.get("fingerprint")
                panel_index = int(panel.get("panel_index", 0) or 0)
                if (
                    panel_index != expected_panel_index
                    or not isinstance(fingerprint, dict)
                    or not required_fingerprint_fields.issubset(fingerprint)
                ):
                    raise GroupNotDeliveryReadyError(
                        f"第 {group_index} 组三拼图第 {expected_panel_index} 个面板指纹不完整。"
                    )
                components.append(
                    {
                        "position": f"2.panel{panel_index}",
                        "parent_position": 2,
                        "component_position": panel_index,
                        "role": "triptych_panel",
                        "dedup_family": "work_scene",
                        "generation_target_id": str(
                            panel.get("generation_target_id") or ""
                        ),
                        "service_role": str(panel.get("service_role") or ""),
                        "fingerprint": fingerprint,
                    }
                )
            image_entry["components"] = components
        images.append(image_entry)
    return images


def _comparison_images(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Include triptych panels in duplicate checks without counting them as deliveries."""

    result: list[dict[str, Any]] = []
    for image in images:
        result.append(image)
        components = image.get("components", [])
        if isinstance(components, list):
            result.extend(
                component for component in components if isinstance(component, dict)
            )
    return result


def _group_visual_signature(images: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(images, key=lambda value: int(value["position"])):
        digest.update(str(item["position"]).encode("ascii"))
        digest.update(item["fingerprint"]["rgb_sha256"].encode("ascii"))
        for component in item.get("components", []):
            digest.update(str(component.get("position", "")).encode("utf-8"))
            digest.update(
                str(component["fingerprint"]["rgb_sha256"]).encode("ascii")
            )
    return digest.hexdigest()


def _near_match(left: dict[str, Any], right: dict[str, Any]) -> tuple[bool, int, int]:
    left_fp = left["fingerprint"]
    right_fp = right["fingerprint"]
    phash_distance = hamming_hex(left_fp["scene_phash64"], right_fp["scene_phash64"])
    dhash_distance = hamming_hex(left_fp["scene_dhash256"], right_fp["scene_dhash256"])
    # This only creates a human-review candidate, so favour recall over silently
    # missing a crop, brightness change, or recompressed historical image.
    matched = (
        phash_distance <= 10
        or dhash_distance <= 64
        or (phash_distance <= 16 and dhash_distance <= 100)
    )
    return matched, phash_distance, dhash_distance


def _duplicate_candidates(
    candidate_group: int,
    candidate_images: list[dict[str, Any]],
    historical_images: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exact: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []
    for candidate in candidate_images:
        for historical in historical_images:
            historical_group = int(historical["group_index"])
            if historical_group == candidate_group:
                continue
            candidate_fp = candidate["fingerprint"]
            historical_fp = historical["fingerprint"]
            if candidate_fp["rgb_sha256"] == historical_fp["rgb_sha256"]:
                exact.append(
                    {
                        "candidate": [candidate_group, candidate["position"]],
                        "historical": [historical_group, historical["position"]],
                        "rgb_sha256": candidate_fp["rgb_sha256"],
                    }
                )
                continue
            candidate_family = _dedup_family(
                candidate.get("role"), candidate.get("dedup_family")
            )
            historical_family = _dedup_family(
                historical.get("role"), historical.get("dedup_family")
            )
            if candidate_family != historical_family:
                continue
            matched, phash_distance, dhash_distance = _near_match(candidate, historical)
            if matched:
                near.append(
                    {
                        "candidate": [candidate_group, candidate["position"]],
                        "historical": [historical_group, historical["position"]],
                        "scene_phash_distance": phash_distance,
                        "scene_dhash_distance": dhash_distance,
                    }
                )
    return exact, near


def _within_group_duplicate_candidates(
    group_index: int,
    images: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Detect accidental copies inside one delivery group."""

    exact: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []
    for left_index, left in enumerate(images):
        for right in images[left_index + 1:]:
            left_fp = left["fingerprint"]
            right_fp = right["fingerprint"]
            if left_fp["rgb_sha256"] == right_fp["rgb_sha256"]:
                exact.append(
                    {
                        "candidate": [group_index, left["position"]],
                        "historical": [group_index, right["position"]],
                        "rgb_sha256": left_fp["rgb_sha256"],
                        "within_group": True,
                    }
                )
                continue
            left_family = _dedup_family(left.get("role"), left.get("dedup_family"))
            right_family = _dedup_family(right.get("role"), right.get("dedup_family"))
            if left_family != right_family:
                continue
            matched, phash_distance, dhash_distance = _near_match(left, right)
            if matched:
                near.append(
                    {
                        "candidate": [group_index, left["position"]],
                        "historical": [group_index, right["position"]],
                        "scene_phash_distance": phash_distance,
                        "scene_dhash_distance": dhash_distance,
                        "within_group": True,
                    }
                )
    return exact, near


def register_groups(
    project_id: str,
    start: int,
    count: int,
    allow_near_duplicates: bool = False,
) -> dict[str, Any]:
    """Register only delivery-ready groups after permanent-history checks.

    Exact visual duplicates can never be overridden.  Near matches are blocked
    by default and may be accepted only after a human review explicitly passes
    ``allow_near_duplicates=True``.  The whole requested range is preflighted
    before any event is appended.
    """

    if start < 1 or count < 1:
        raise ValueError("start and count must be positive")
    definition, _, history_path, _, production_path = _project_files(project_id)
    category = str(definition.get("category") or project_id)
    output_root = safe_project_output(definition)

    # This is the same delivery gate used by the public group workflow.
    import group_production

    audit = group_production.audit_groups(start, count, project_id)
    audit_by_group = {int(row["group_index"]): row for row in audit.get("groups", [])}
    not_ready = [
        index
        for index in range(start, start + count)
        if not bool(audit_by_group.get(index, {}).get("delivery_ready"))
    ]
    if not_ready:
        raise GroupNotDeliveryReadyError(
            f"这些组还没通过成品检查，不能入库：{not_ready}。"
            "先补齐全部成品，并逐张完成人工验收。"
        )

    records = _production_records(production_path, start, count)
    total_images_value = definition.get("content_group", {}).get("total_images")
    if total_images_value is None:
        raise InventoryError(
            "项目 content_group.total_images 未登记，已停止；库存不能再默认按9张推断。"
        )
    expected_images = int(total_images_value)
    structure = definition.get("image_group_structure", {})
    if not isinstance(structure, dict) or not structure:
        category_config_value = definition.get("prompt_sources", {}).get("category_config")
        if category_config_value:
            category_config_path = as_project_path(str(category_config_value))
            if category_config_path.is_file():
                category_config = load_json(category_config_path)
                structure = category_config.get("image_group_structure", {})
    expected_roles_value = (
        structure.get("delivery_roles") if isinstance(structure, dict) else None
    )
    expected_roles = (
        [str(role) for role in expected_roles_value]
        if isinstance(expected_roles_value, list)
        else None
    )
    is_independent_triptych = (
        definition.get("content_group", {}).get("generation_mode")
        == "independent_triptych_panels"
    )
    if is_independent_triptych:
        required_roles = ["cover", "triptych", "detail"] if project_id == "ktv" else PIPE_DELIVERY_ROLES
        if expected_images != len(required_roles):
            raise InventoryError("????????????????5????")
        if expected_roles != required_roles:
            raise InventoryError(
                f"????? delivery_roles ??? {PIPE_DELIVERY_ROLES}?"
            )
    grouped = _group_images(
        records,
        expected_images,
        expected_roles,
        require_expected_size=is_independent_triptych,
    )
    # Fingerprinting may take a moment.  Do it before the lock, then re-read the
    # append-only history while locked so two parallel registrations cannot race.
    fingerprinted = {
        group_index: _fingerprinted_group(group_index, grouped[group_index], output_root)
        for group_index in range(start, start + count)
    }
    with _history_lock(history_path):
        events = load_jsonl(history_path)
        latest, available_history = _history_state(events, project_id, category)

        historical_images: list[dict[str, Any]] = []
        for event in available_history:
            for image in _comparison_images(event["images"]):
                historical_images.append({**image, "group_index": int(event["group_index"])})

        pending: list[tuple[int, list[dict[str, Any]], list[dict[str, Any]]]] = []
        unchanged: list[dict[str, Any]] = []
        for group_index in range(start, start + count):
            images = fingerprinted[group_index]
            signature = _group_visual_signature(images)
            previous_available = _available_event_for_group(events, group_index)
            current = latest.get(group_index)
            if previous_available is not None:
                old_signature = str(previous_available.get("group_visual_signature") or "")
                if not old_signature:
                    old_signature = _group_visual_signature(previous_available["images"])
                if signature == old_signature:
                    unchanged.append(
                        {
                            "group_index": group_index,
                            "state": str(current.get("event_type")) if current else "available",
                        }
                    )
                    continue
                raise InventoryStateError(
                    f"第 {group_index} 组入库后图片发生变化。为保护永久历史，请使用新的组号。"
                )

            comparison_images = _comparison_images(images)
            within_exact, within_near = _within_group_duplicate_candidates(
                group_index, comparison_images
            )
            exact, near = _duplicate_candidates(
                group_index, comparison_images, historical_images
            )
            exact = [*within_exact, *exact]
            near = [*within_near, *near]
            if exact:
                raise ExactDuplicateError(
                    f"第 {group_index} 组发现 {len(exact)} 张历史完全重复图，已阻止入库：{exact[:3]}"
                )
            if near and not allow_near_duplicates:
                raise NearDuplicateError(
                    f"第 {group_index} 组发现 {len(near)} 个近似候选，需人工查看后再决定：{near[:3]}"
                )
            pending.append((group_index, images, near))
            # Also compare later groups in this same request with earlier candidates.
            historical_images.extend(
                {**image, "group_index": group_index}
                for image in comparison_images
            )

        recorded_at = now_iso()
        new_events: list[dict[str, Any]] = []
        for group_index, images, near in pending:
            new_events.append(
                {
                    "schema_version": EVENT_SCHEMA_VERSION,
                    "event_id": uuid.uuid4().hex,
                    "event_type": "available",
                    "recorded_at": recorded_at,
                    "project_id": project_id,
                    "category": category,
                    "group_index": group_index,
                    "group_visual_signature": _group_visual_signature(images),
                    "images": images,
                    "near_duplicate_review_override": bool(near and allow_near_duplicates),
                    "near_duplicate_candidates": near,
                }
            )
        _append_events(history_path, new_events)
    snapshot = sync_inventory(project_id, write=True, create_contact_sheet=False)
    return {
        "project_id": project_id,
        "requested_groups": count,
        "registered_groups": [event["group_index"] for event in new_events],
        "already_registered": unchanged,
        "near_duplicate_override_used": any(
            event["near_duplicate_review_override"] for event in new_events
        ),
        "api_called": False,
        "summary": snapshot["summary"],
    }


def mark_used(project_id: str, group_index: int, confirm: bool) -> dict[str, Any]:
    """Append a consumed event; never delete files or historical fingerprints."""

    if confirm is not True:
        raise ValueError("必须明确 confirm=True 才能把一组标记为已使用。")
    if group_index < 1:
        raise ValueError("group_index must be positive")
    definition, _, history_path, _, _ = _project_files(project_id)
    category = str(definition.get("category") or project_id)
    already_marked = False
    with _history_lock(history_path):
        events = load_jsonl(history_path)
        latest, _ = _history_state(events, project_id, category)
        current = latest.get(group_index)
        if current is None:
            raise InventoryStateError(f"第 {group_index} 组还没有入库，不能标记已使用。")
        if current.get("event_type") == "consumed":
            already_marked = True
        else:
            available = _available_event_for_group(events, group_index)
            event = {
                "schema_version": EVENT_SCHEMA_VERSION,
                "event_id": uuid.uuid4().hex,
                "event_type": "consumed",
                "recorded_at": now_iso(),
                "project_id": project_id,
                "category": category,
                "group_index": group_index,
                "available_event_id": available.get("event_id") if available else None,
            }
            _append_events(history_path, [event])
    snapshot = sync_inventory(project_id, write=True, create_contact_sheet=False)
    return {
        "project_id": project_id,
        "group_index": group_index,
        "state": "consumed",
        "already_marked": already_marked,
        "files_deleted": False,
        "summary": snapshot["summary"],
    }


def _disk_state(available_event: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    missing_or_invalid: list[str] = []
    changed: list[str] = []
    for image in available_event["images"]:
        path = as_project_path(str(image["path"]))
        if not path.is_file():
            missing_or_invalid.append(str(image["path"]))
            continue
        size_value = image.get("expected_size")
        expected_size = (
            (int(size_value[0]), int(size_value[1]))
            if isinstance(size_value, list) and len(size_value) == 2
            else None
        )
        if not valid_image(path, expected_size):
            changed.append(str(image["path"]))
            continue
        current = image_fingerprint(path, str(image.get("role") or "detail"))
        if current["rgb_sha256"] != image["fingerprint"]["rgb_sha256"]:
            changed.append(str(image["path"]))
    if changed:
        return "unexpected_changed", missing_or_invalid, changed
    if missing_or_invalid:
        return "unexpected_missing", missing_or_invalid, changed
    return "healthy", missing_or_invalid, changed


def _registry_group_indexes(definition: dict[str, Any]) -> list[int]:
    value = definition.get("group_registry")
    if not value:
        return []
    path = as_project_path(str(value))
    if not path.is_file():
        return []
    registry = load_json(path)
    return sorted(
        int(row["group_index"])
        for row in registry.get("groups", [])
        if int(row.get("group_index", 0)) > 0
    )


def sync_inventory(
    project_id: str,
    *,
    write: bool = True,
    create_contact_sheet: bool = False,
) -> dict[str, Any]:
    """Rebuild the current snapshot solely from append-only history + disk."""

    definition, _, history_path, snapshot_path, _ = _project_files(project_id)
    category = str(definition.get("category") or project_id)
    output_root = safe_project_output(definition)
    events = load_jsonl(history_path)
    latest, available_history = _history_state(events, project_id, category)
    all_indexes = set(_registry_group_indexes(definition)) | set(latest)
    groups: list[dict[str, Any]] = []
    healthy_available_events: list[dict[str, Any]] = []
    for group_index in sorted(all_indexes):
        current = latest.get(group_index)
        if current is None:
            groups.append(
                {
                    "group_index": group_index,
                    "inventory_state": "planned",
                    "disk_state": "not_registered",
                    "unexpected": False,
                    "missing_or_invalid": [],
                    "changed": [],
                }
            )
            continue
        available = _available_event_for_group(events, group_index)
        disk_state, missing, changed = _disk_state(available)
        consumed = current.get("event_type") == "consumed"
        if consumed:
            # Missing files are expected after use; the available event still
            # permanently retains every fingerprint.
            if disk_state == "healthy":
                reported_disk_state = "consumed_files_present"
                unexpected = False
            elif disk_state == "unexpected_missing":
                reported_disk_state = "consumed_files_missing_expected"
                unexpected = False
            else:
                reported_disk_state = "consumed_files_changed_unexpected"
                unexpected = True
        else:
            reported_disk_state = disk_state
            unexpected = disk_state != "healthy"
            if not unexpected:
                healthy_available_events.append(available)
        groups.append(
            {
                "group_index": group_index,
                "inventory_state": "consumed" if consumed else "available",
                "disk_state": reported_disk_state,
                "unexpected": unexpected,
                "missing_or_invalid": missing,
                "changed": changed,
                "available_event_id": available.get("event_id"),
                "last_event_id": current.get("event_id"),
            }
        )

    target = int(definition.get("inventory_policy", {}).get("target_available_groups", 30))
    available_count = len(healthy_available_events)
    registered_available = sum(row["inventory_state"] == "available" for row in groups)
    consumed_count = sum(row["inventory_state"] == "consumed" for row in groups)
    unexpected_count = sum(bool(row["unexpected"]) for row in groups)
    unique_history = {
        image["fingerprint"]["rgb_sha256"]
        for event in available_history
        for image in event["images"]
    }
    contact_sheet: Path | None = None
    if create_contact_sheet:
        contact_sheet = build_available_cover_contact_sheet(
            healthy_available_events,
            output_root,
        )
    missing_to_target = max(0, target - available_count)
    if unexpected_count:
        message = (
            f"现在有 {available_count} 组可正常使用，另有 {unexpected_count} 组图片异常；"
            f"目标 {target} 组，还差 {missing_to_target} 组。"
        )
    else:
        message = f"现在有 {available_count} 组可正常使用；目标 {target} 组，还差 {missing_to_target} 组。"
    summary = {
        "target_available_groups": target,
        "available_groups": available_count,
        "registered_available_groups": registered_available,
        "consumed_groups": consumed_count,
        "unexpected_groups": unexpected_count,
        "missing_to_target": missing_to_target,
        "historical_available_events": len(available_history),
        "historical_unique_images": len(unique_history),
        "contact_sheet": _relative(contact_sheet) if contact_sheet else None,
        "message": message,
    }
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "project_id": project_id,
        "category": category,
        "source_of_truth": _relative(history_path),
        "snapshot_rebuildable": True,
        "last_scanned_at": now_iso(),
        "groups": groups,
        "summary": summary,
        "claim_boundary": (
            "该账本能拦截完全重复图并筛出明显近似候选；"
            "不能保证抖音未公开算法永远不会判定同质化。"
        ),
    }
    if write:
        atomic_json(snapshot_path, payload)
    return payload


def build_available_cover_contact_sheet(
    available_events: list[dict[str, Any]], output_root: Path
) -> Path | None:
    """Build a fixed 6x5 sheet for at most 30 currently usable covers."""

    from PIL import Image, ImageDraw, ImageFont, ImageOps

    covers: list[tuple[int, Path]] = []
    for event in sorted(available_events, key=lambda row: int(row["group_index"])):
        cover = next((image for image in event["images"] if image.get("role") == "cover"), None)
        if cover is None:
            continue
        path = as_project_path(str(cover["path"]))
        if valid_image(path):
            covers.append((int(event["group_index"]), path))
        if len(covers) == 30:
            break
    if not covers:
        return None

    columns, rows = 6, 5
    thumb_width, thumb_height, label_height, gap = 180, 260, 28, 10
    sheet = Image.new(
        "RGB",
        (
            gap + columns * (thumb_width + gap),
            gap + rows * (thumb_height + label_height + gap),
        ),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    for index, (group_index, path) in enumerate(covers):
        row, column = divmod(index, columns)
        x = gap + column * (thumb_width + gap)
        y = gap + row * (thumb_height + label_height + gap)
        with Image.open(path) as source:
            thumb = ImageOps.exif_transpose(source).convert("RGB")
            thumb = ImageOps.fit(thumb, (thumb_width, thumb_height), method=resampling)
        sheet.paste(thumb, (x, y))
        draw.text(
            (x + 4, y + thumb_height + 6),
            f"group_{group_index:04d}",
            fill="black",
            font=font,
        )
    preview_dir = output_root / "_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    target = preview_dir / "available_cover_contact_sheet.jpg"
    sheet.save(target, format="JPEG", quality=90, optimize=True)
    return target


def build_cover_contact_sheet(
    project_id: str,
    production: list[dict[str, Any]] | None = None,
    output_root: Path | None = None,
) -> Path | None:
    """Compatibility wrapper for the first inventory draft.

    ``production`` is intentionally ignored: only registered, healthy available
    groups may appear in the stock contact sheet.
    """

    del production
    definition, _, history_path, _, _ = _project_files(project_id)
    category = str(definition.get("category") or project_id)
    events = load_jsonl(history_path)
    latest, _ = _history_state(events, project_id, category)
    healthy: list[dict[str, Any]] = []
    for group_index, current in latest.items():
        if current.get("event_type") != "available":
            continue
        available = _available_event_for_group(events, group_index)
        if available is not None and _disk_state(available)[0] == "healthy":
            healthy.append(available)
    destination = output_root.resolve() if output_root else safe_project_output(definition)
    safe_root = safe_project_output(definition)
    if destination != safe_root:
        raise ValueError("contact sheet must stay inside the configured category output folder")
    return build_available_cover_contact_sheet(healthy, destination)
