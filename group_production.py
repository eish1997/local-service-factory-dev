"""Safe grouped-image production with reuse, locks, budgets, resume, and delivery audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import image_generate
from tools.validate_cover_text import validate as validate_cover


ROOT = Path(__file__).resolve().parent
PROJECT_DIR = ROOT / "projects" / "road_rescue"
LOCK_PATH = ROOT / ".runtime" / "group_production.lock"
LOCK_DIR = ROOT / ".runtime" / "group_locks"
API_KEY_QUARANTINE_PATH = ROOT / ".runtime" / "api_key_slot_quarantine.json"
PIPE_DELIVERY_ROLES = ["cover", "triptych", "detail", "detail", "detail"]


def category_delivery_structure(project_id: str) -> tuple[bool, list[str] | None]:
    definition = project_definition(project_id)
    content_group = definition.get("content_group", {})
    is_independent_triptych = (
        content_group.get("generation_mode") == "independent_triptych_panels"
    )
    structure = definition.get("image_group_structure", {})
    if not isinstance(structure, dict) or not structure:
        category_config_value = definition.get("prompt_sources", {}).get("category_config")
        if isinstance(category_config_value, str) and category_config_value:
            category_config_path = as_path(category_config_value)
            if category_config_path.is_file():
                category_config = load_json(category_config_path)
                structure = category_config.get("image_group_structure", {})
    delivery_roles = (
        [str(role) for role in structure.get("delivery_roles", [])]
        if isinstance(structure, dict)
        else []
    )
    return is_independent_triptych, delivery_roles or None

HOME_APPLIANCE_SERVICE_GRID = [
    "\u5bb6\u7535\u7ef4\u4fee",
    "\u7a7a\u8c03\u7ef4\u4fee",
    "\u51b0\u7bb1\u7ef4\u4fee",
    "\u6d17\u8863\u673a\u7ef4\u4fee",
    "\u70ed\u6c34\u5668\u7ef4\u4fee",
    "\u6cb9\u70df\u673a\u7ef4\u4fee",
    "\u71c3\u6c14\u7076\u7ef4\u4fee",
    "\u7535\u89c6\u7ef4\u4fee",
    "\u5bb6\u7535\u6e05\u6d17",
    "\u5bb6\u7535\u552e\u540e",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def project_definition(project_id: str) -> dict[str, Any]:
    registry = load_json(ROOT / "projects" / "registry.json")
    entry = next((item for item in registry["projects"] if item["id"] == project_id), None)
    if not entry:
        raise ValueError(f"unknown project: {project_id}")
    return load_json(ROOT / entry["definition"])


def project_dir(project_id: str) -> Path:
    registry = load_json(ROOT / "projects" / "registry.json")
    entry = next((item for item in registry["projects"] if item["id"] == project_id), None)
    if not entry:
        raise ValueError(f"unknown project: {project_id}")
    return (ROOT / entry["definition"]).parent


def as_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _record_position(record: dict[str, Any]) -> int:
    return int(record.get("delivery_position") or record.get("position") or 0)


def _record_expected_size(record: dict[str, Any]) -> tuple[int, int] | None:
    value = record.get("expected_size") or record.get("final_size")
    if value is None:
        return None
    if isinstance(value, str):
        match = re.fullmatch(r"(\d+)x(\d+)", value)
        if match:
            return int(match.group(1)), int(match.group(2))
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(item, int) and item > 0 for item in value)
    ):
        return int(value[0]), int(value[1])
    raise RuntimeError(
        f"invalid expected_size for group {record.get('group_index')} "
        f"position {_record_position(record)}"
    )


def image_file_is_valid(path: Path, expected_size: tuple[int, int] | None = None) -> bool:
    """Return true only for a non-empty, fully decodable PNG image."""
    if not path.is_file():
        return False
    try:
        if path.stat().st_size <= 0:
            return False
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            image_format = image.format
        return (
            image_format == "PNG"
            and width > 0
            and height > 0
            and (expected_size is None or (width, height) == expected_size)
        )
    except Exception:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pipe_cover_has_both_phone_texts(validation: dict[str, Any]) -> bool:
    values = {str(value) for value in validation.get("expected_text", [])}
    center_numbers: set[str] = set()
    signboard_numbers: set[str] = set()
    for value in values:
        digits = re.sub(r"\D", "", value)
        if not re.fullmatch(r"1[3-9]\d{9}", digits):
            continue
        if value.startswith("??") or value.startswith("???"):
            center_numbers.add(digits)
        if value.startswith("????") or value.startswith("??????"):
            signboard_numbers.add(digits)
    return bool(center_numbers & signboard_numbers)

def _pipe_validation_status(
    item: dict[str, Any],
    target: Path,
    category_id: str = "pipe_unclogging",
) -> tuple[bool, str]:
    validation_file = target.with_suffix(".validation.json")
    if not validation_file.is_file():
        return False, "not_checked"
    try:
        validation = load_json(validation_file)
    except (OSError, ValueError, TypeError):
        return False, "invalid_validation"
    expected_size = _record_expected_size(item)
    checks = {
        "status": validation.get("status") == "approved",
        "approved": validation.get("approved") is True,
        "manual_visual_approval": validation.get("manual_visual_approval") is True,
        "category_id": validation.get("category_id") == category_id,
        "group_index": int(validation.get("group_index", 0) or 0)
        == int(item["group_index"]),
        "position": int(
            validation.get("delivery_position")
            or validation.get("position")
            or 0
        )
        == _record_position(item),
        "role": validation.get("role") == item.get("role"),
        "postprocessed_locally": validation.get("postprocessed_locally") is True,
        "image_sha256": validation.get("image_sha256") == _sha256_file(target),
    }
    recorded_size = validation.get("expected_size") or validation.get("final_size")
    if expected_size is not None and recorded_size is not None:
        try:
            if isinstance(recorded_size, str):
                size_match = re.fullmatch(r"(\d+)x(\d+)", recorded_size)
                parsed_size = (
                    (int(size_match.group(1)), int(size_match.group(2)))
                    if size_match
                    else None
                )
            else:
                parsed_size = tuple(int(value) for value in recorded_size)
        except (TypeError, ValueError):
            parsed_size = None
        checks["expected_size"] = parsed_size == expected_size
    if item.get("role") == "cover":
        checks["cover_double_phone"] = _pipe_cover_has_both_phone_texts(validation)
    failed = [name for name, passed in checks.items() if not passed]
    return not failed, "approved" if not failed else "failed:" + ",".join(failed)


def project_style_suffix(role: str, project_id: str = "road_rescue") -> str:
    current_project_dir = project_dir(project_id)
    paths = [
        current_project_dir / "preferences" / "STYLE_PROFILE.md",
        current_project_dir / "preferences" / "REJECTED_PATTERNS.md",
    ]
    if role == "cover" and project_id == "road_rescue":
        paths.insert(0, current_project_dir / "cover_style_profile.md")
    else:
        paths.extend([ROOT / "preferences" / "STYLE_PROFILE.md", ROOT / "preferences" / "REJECTED_PATTERNS.md"])
    content = [path.read_text(encoding="utf-8").strip() for path in paths if path.is_file()]
    return "\n\n项目专属风格与拒绝规则：\n" + "\n".join(content) if content else ""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    last_error: PermissionError | None = None
    for attempt in range(8):
        temporary = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
        )
        try:
            temporary.write_text(data, encoding="utf-8")
            temporary.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
    if last_error is not None:
        raise last_error


def production_records(group_start: int, group_count: int, project_id: str = "road_rescue") -> list[dict[str, Any]]:
    current_project_dir = project_dir(project_id)
    definition = project_definition(project_id)
    manifest_value = definition.get("prompt_sources", {}).get("production_manifest")
    generic_manifest = (
        as_path(str(manifest_value)).resolve()
        if manifest_value
        else (current_project_dir / "groups" / "production_manifest.jsonl").resolve()
    )
    if current_project_dir.resolve() not in generic_manifest.parents:
        raise RuntimeError(f"project {project_id} production manifest escapes the project directory")
    if generic_manifest.is_file():
        selected = []
        for item in load_jsonl(generic_manifest):
            group_index = int(item["group_index"])
            if group_start <= group_index < group_start + group_count:
                selected.append(item)
        prepared = {int(item["group_index"]) for item in selected}
        missing = [index for index in range(group_start, group_start + group_count) if index not in prepared]
        if missing:
            raise RuntimeError(f"groups are not prepared: {missing}")
        return sorted(
            selected,
            key=lambda item: (int(item["group_index"]), _record_position(item)),
        )
    if project_id != "road_rescue":
        raise RuntimeError(f"project {project_id} has no production manifest")
    groups = {item["group_index"]: item for item in load_jsonl(PROJECT_DIR / "groups" / "group_manifest.jsonl")}
    covers = {item["group_index"]: item for item in load_jsonl(PROJECT_DIR / "prompts" / "cover_prompts.jsonl")}
    details = {item["index"]: item for item in load_jsonl(ROOT / "prompts" / "road_rescue_prompts.jsonl")}
    records: list[dict[str, Any]] = []
    for group_index in range(group_start, group_start + group_count):
        if group_index not in groups or group_index not in covers:
            raise RuntimeError(f"group {group_index} is not prepared")
        group_dir = ROOT / "output" / "road_rescue" / f"group_{group_index:04d}"
        cover = covers[group_index]
        records.append({
            "project_id": "road_rescue", "group_index": group_index, "position": 1, "role": "cover",
            "filename": "01_cover.png", "target": str(group_dir / "01_cover.png"),
            "prompt": cover["prompt"], "prompt_sha256": cover["prompt_sha256"], "source": None,
            "phone_bar_text": cover["scene"].get("phone_bar_text") or " / ".join(cover["scene"].get("phones", [])),
            "expected_text": [
                cover["scene"]["store_name"], *cover["scene"]["phones"],
                *[item.strip() for item in re.split(r"[·|]", cover["scene"]["business_lines"]) if item.strip()],
            ],
        })
        for position, detail_ref in enumerate(groups[group_index]["details"], start=2):
            detail = details[detail_ref["index"]]
            target = group_dir / f"{position:02d}_detail_{detail['index']:04d}.png"
            legacy = ROOT / "output" / detail["filename"]
            records.append({
                "project_id": "road_rescue", "group_index": group_index, "position": position, "role": "detail",
                "detail_index": detail["index"], "filename": target.name, "target": str(target),
                "prompt": detail["prompt"], "prompt_sha256": detail["prompt_sha256"],
                "source": str(legacy) if legacy.is_file() else None, "expected_text": [],
            })
    return records


def plan(group_start: int, group_count: int, project_id: str = "road_rescue") -> dict[str, Any]:
    records = production_records(group_start, group_count, project_id)
    states: list[tuple[dict[str, Any], Path, bool, bool]] = []
    for item in records:
        target = as_path(item["target"])
        source = item.get("source")
        expected_size = _record_expected_size(item)
        states.append((
            item,
            target,
            image_file_is_valid(target, expected_size),
            bool(source and image_file_is_valid(as_path(source), expected_size)),
        ))
    existing = [item for item, _, target_valid, _ in states if target_valid]
    reusable = [item for item, _, target_valid, source_valid in states if not target_valid and source_valid]
    pending = [item for item, _, target_valid, source_valid in states if not target_valid and not source_valid]
    invalid_existing = [item for item, target, target_valid, _ in states if target.is_file() and not target_valid]
    manifest_material = "\n".join(
        str(item.get("prompt_sha256") or json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ))
        for item in records
    )
    manifest_hash = hashlib.sha256(manifest_material.encode("utf-8")).hexdigest()
    return {
        "project_id": project_id, "group_start": group_start, "group_count": group_count,
        "total_images": len(records), "existing": len(existing), "reusable_without_api": len(reusable),
        "reusable_images": len(existing) + len(reusable), "invalid_existing": len(invalid_existing),
        "pending_api_images": len(pending), "manifest_sha256": manifest_hash,
    }


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, SystemError):
        return False


def range_lock_path(project_id: str, group_start: int, group_count: int) -> Path:
    return LOCK_DIR / project_id / f"group_{group_start:04d}_{group_count:04d}.lock"


def acquire_lock(job_id: str, project_id: str = "road_rescue", group_start: int | None = None, group_count: int | None = None) -> Path:
    path = range_lock_path(project_id, group_start, group_count) if group_start is not None and group_count is not None else LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if process_alive(int(current.get("pid", 0))):
            raise RuntimeError(f"another group task is active: {current.get('job_id')}")
        path.unlink()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"job_id": job_id, "pid": os.getpid(), "created_at": datetime.now(timezone.utc).isoformat()}, handle)
    return path


def consume_license(path: Path, run_plan: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    license_data = json.loads(path.read_text(encoding="utf-8"))
    if license_data.get("status") != "active" or license_data.get("kind") != "group-production":
        raise RuntimeError("group execution license is not active")
    expected = {
        "project_id": run_plan["project_id"], "group_start": run_plan["group_start"],
        "group_count": run_plan["group_count"], "manifest_sha256": run_plan["manifest_sha256"],
        "provider": config["provider"], "base_url": config.get("base_url", ""), "model": config["model"],
    }
    for key, value in expected.items():
        if license_data.get(key) != value:
            raise RuntimeError(f"group license mismatch: {key}")
    if run_plan["pending_api_images"] > int(license_data["approved_image_count"]):
        raise RuntimeError("pending image count exceeds approved image count")
    license_data["status"] = "consumed"
    license_data["consumed_at"] = datetime.now(timezone.utc).isoformat()
    license_data["requests_used"] = 0
    atomic_json(path, license_data)
    return license_data


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def api_key_slot_hard_failure(error: str) -> bool:
    normalized = error.lower()
    hard_markers = [
        "model_not_found",
        "not supported by any configured account",
        "insufficient_balance",
        "insufficient balance",
        "invalid_api_key",
        "incorrect api key",
        "unauthorized",
        "401",
    ]
    return any(marker in normalized for marker in hard_markers)


def quarantine_match(entry: dict[str, Any], config: dict[str, Any]) -> bool:
    return (
        str(entry.get("provider", "")) == str(config.get("provider", ""))
        and str(entry.get("base_url", "")) == str(config.get("base_url", ""))
        and str(entry.get("model", "")) == str(config.get("model", ""))
    )


def quarantined_api_key_slots(config: dict[str, Any]) -> set[int]:
    if not API_KEY_QUARANTINE_PATH.is_file():
        return set()
    try:
        data = load_json(API_KEY_QUARANTINE_PATH)
    except Exception:
        return set()
    slots: set[int] = set()
    for entry in data.get("slots", []):
        if entry.get("status", "active") == "active" and quarantine_match(entry, config):
            slots.add(int(entry["api_key_slot"]))
    return slots


def quarantine_api_key_slot(slot: int, config: dict[str, Any], reason: str, job_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if API_KEY_QUARANTINE_PATH.is_file():
        try:
            data = load_json(API_KEY_QUARANTINE_PATH)
        except Exception:
            data = {"version": 1, "slots": []}
    else:
        data = {"version": 1, "slots": []}
    slots = data.setdefault("slots", [])
    for entry in slots:
        if int(entry.get("api_key_slot", 0) or 0) == slot and quarantine_match(entry, config):
            entry.update({
                "status": "active",
                "reason": reason,
                "last_job_id": job_id,
                "updated_at": now,
            })
            atomic_json(API_KEY_QUARANTINE_PATH, data)
            return
    slots.append({
        "api_key_slot": slot,
        "provider": config.get("provider", ""),
        "base_url": config.get("base_url", ""),
        "model": config.get("model", ""),
        "status": "active",
        "reason": reason,
        "last_job_id": job_id,
        "disabled_at": now,
        "updated_at": now,
    })
    atomic_json(API_KEY_QUARANTINE_PATH, data)


def openai_clients(config: dict[str, Any], api_key_slots: list[int] | None = None) -> list[Any]:
    image_generate.load_project_env()
    from openai import OpenAI

    keys = image_generate.configured_api_keys()
    if api_key_slots:
        keys = [keys[slot - 1] for slot in api_key_slots]
    if not keys:
        keys = [""]
    clients = []
    for key in keys:
        kwargs: dict[str, Any] = {}
        if key:
            kwargs["api_key"] = key
        if config.get("base_url"):
            kwargs["base_url"] = config["base_url"]
        clients.append(OpenAI(**kwargs))
    return clients


def openai_clients_by_slot(config: dict[str, Any], api_key_slots: list[int] | None = None) -> list[tuple[int, Any]]:
    image_generate.load_project_env()
    from openai import OpenAI

    keys = image_generate.configured_api_keys()
    if not keys:
        keys = [""]
    selected_slots = api_key_slots or list(range(1, len(keys) + 1))
    clients = []
    for slot in selected_slots:
        if slot < 1 or slot > len(keys):
            raise RuntimeError("configured API key count is below requested api key slot")
        key = keys[slot - 1]
        kwargs: dict[str, Any] = {}
        if key:
            kwargs["api_key"] = key
        if config.get("base_url"):
            kwargs["base_url"] = config["base_url"]
        clients.append((slot, OpenAI(**kwargs)))
    return clients


def assigned_slots(job_file: Path, fallback_slots: list[int], key_count: int) -> set[int]:
    try:
        job = json.loads(job_file.read_text(encoding="utf-8"))
    except Exception:
        return set(fallback_slots)
    slots = [int(slot) for slot in job.get("api_key_slots") or fallback_slots]
    if not slots and key_count <= 1:
        return {1}
    return set(slots)


def save_generated_image(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.write_bytes(payload)
    temporary.replace(target)


def home_font(size: int) -> Any:
    from PIL import ImageFont

    font_candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyhbd.ttc",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "simhei.ttf",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf",
    ]
    for candidate in font_candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def draw_home_cover_info(image_path: Path, phone_text: str, group_index: int, backup_dir: Path) -> None:
    from PIL import Image, ImageDraw

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"group_{group_index:04d}_01_cover.png"
    if not backup_path.is_file():
        shutil.copy2(image_path, backup_path)

    image = Image.open(backup_path).convert("RGBA")
    width, height = image.size
    phone = f"\u7535\u8bdd{phone_text}"
    palette = [
        ((255, 232, 38, 255), (50, 22, 0, 255), (0, 0, 0, 178), (255, 168, 40, 230)),
        ((255, 255, 255, 255), (0, 58, 74, 255), (0, 0, 0, 178), (55, 190, 230, 220)),
        ((120, 255, 65, 255), (8, 42, 0, 255), (0, 0, 0, 174), (80, 225, 120, 215)),
        ((255, 116, 213, 255), (64, 0, 48, 255), (0, 0, 0, 174), (230, 120, 255, 215)),
    ]
    fill, stroke, background, accent = palette[(group_index - 1) % len(palette)]
    draw = ImageDraw.Draw(image)
    font_size = int(width * 0.13)
    font = home_font(font_size)
    stroke_width = max(5, int(width * 0.011))
    max_width = int(width * 0.96)
    while font_size > 28:
        bbox = draw.textbbox((0, 0), phone, font=font, stroke_width=stroke_width)
        if bbox[2] - bbox[0] <= max_width:
            break
        font_size -= 2
        font = home_font(font_size)
    bbox = draw.textbbox((0, 0), phone, font=font, stroke_width=stroke_width)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) // 2 - bbox[0]
    y = int(height * 0.50) - th // 2 - bbox[1]
    pad_x = int(width * 0.035)
    pad_y = int(height * 0.015)
    rect = [max(0, x + bbox[0] - pad_x), max(0, y + bbox[1] - pad_y), min(width, x + bbox[2] + pad_x), min(height, y + bbox[3] + pad_y)]
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(rect, radius=max(8, int(width * 0.018)), fill=background, outline=(accent[0], accent[1], accent[2], 150), width=max(2, int(width * 0.004)))
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)
    draw.text((x, y), phone, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke)

    margin_x = int(width * 0.04)
    gap = max(5, int(width * 0.008))
    cell_w = (width - margin_x * 2 - gap * 4) // 5
    cell_h = int(height * 0.052)
    grid_h = cell_h * 2 + gap
    y0 = height - int(height * 0.035) - grid_h
    grid_overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid_overlay)
    grid_draw.rounded_rectangle(
        [margin_x - gap, y0 - gap, width - margin_x + gap, y0 + grid_h + gap],
        radius=max(8, int(width * 0.015)),
        fill=(0, 0, 0, 112),
        outline=(accent[0], accent[1], accent[2], 125),
        width=max(1, int(width * 0.002)),
    )
    label_font_size = int(width * 0.034)
    label_font = home_font(label_font_size)
    label_stroke = max(2, int(width * 0.004))
    scratch = ImageDraw.Draw(grid_overlay)
    while label_font_size > 18:
        if all((scratch.textbbox((0, 0), label, font=label_font, stroke_width=label_stroke)[2] <= cell_w * 0.82) for label in HOME_APPLIANCE_SERVICE_GRID):
            break
        label_font_size -= 1
        label_font = home_font(label_font_size)
    for index, label in enumerate(HOME_APPLIANCE_SERVICE_GRID):
        row, col = divmod(index, 5)
        x1 = margin_x + col * (cell_w + gap)
        y1 = y0 + row * (cell_h + gap)
        x2, y2 = x1 + cell_w, y1 + cell_h
        grid_draw.rounded_rectangle([x1, y1, x2, y2], radius=max(6, int(width * 0.012)), fill=(accent[0], accent[1], accent[2], 135), outline=accent, width=max(1, int(width * 0.002)))
        tb = scratch.textbbox((0, 0), label, font=label_font, stroke_width=label_stroke)
        tx = x1 + (cell_w - (tb[2] - tb[0])) // 2 - tb[0]
        ty = y1 + (cell_h - (tb[3] - tb[1])) // 2 - tb[1]
        grid_draw.text((tx, ty), label, font=label_font, fill=(255, 255, 255, 255), stroke_width=label_stroke, stroke_fill=(0, 0, 0, 210))
    image = Image.alpha_composite(image, grid_overlay)
    image.convert("RGB").save(image_path, quality=96)


def draw_home_detail_label(image_path: Path, label: str, group_index: int, backup_dir: Path) -> None:
    from PIL import Image, ImageDraw

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"group_{group_index:04d}_{image_path.name}"
    if not backup_path.is_file():
        shutil.copy2(image_path, backup_path)
    image = Image.open(backup_path).convert("RGBA")
    width, height = image.size
    palettes = [
        ((18, 74, 92, 156), (96, 238, 255, 230)),
        ((78, 48, 12, 156), (255, 190, 72, 230)),
        ((45, 28, 90, 156), (175, 145, 255, 230)),
        ((12, 78, 46, 156), (120, 245, 155, 230)),
    ]
    bg, accent = palettes[(group_index - 1) % len(palettes)]
    font_size = int(width * 0.07)
    font = home_font(font_size)
    stroke = max(3, int(width * 0.006))
    draw = ImageDraw.Draw(image)
    while font_size > 24:
        bbox = draw.textbbox((0, 0), label, font=font, stroke_width=stroke)
        if bbox[2] - bbox[0] <= width * 0.72:
            break
        font_size -= 2
        font = home_font(font_size)
    bbox = draw.textbbox((0, 0), label, font=font, stroke_width=stroke)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    rect_w = int(max(tw + width * 0.13, width * 0.48))
    rect_h = int(th + height * 0.035)
    x1 = (width - rect_w) // 2
    y1 = int(height * 0.18)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([x1, y1, x1 + rect_w, y1 + rect_h], radius=max(8, int(width * 0.018)), fill=bg, outline=accent, width=max(2, int(width * 0.003)))
    tx = x1 + (rect_w - tw) // 2 - bbox[0]
    ty = y1 + (rect_h - th) // 2 - bbox[1]
    od.text((tx, ty), label, font=font, fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 210))
    image = Image.alpha_composite(image, overlay)
    image.convert("RGB").save(image_path, quality=96)


def finalize_cover(item: dict[str, Any], target: Path, project_id: str) -> None:
    phone_text = item.get("phone_bar_text")
    if project_id == "home_appliance_repair" and phone_text:
        backup_dir = ROOT / ".runtime" / "projects" / project_id / "cover_phone_bar_backups"
        draw_home_cover_info(target, str(phone_text), int(item["group_index"]), backup_dir)
        validate_cover(target, item.get("expected_text", []))
        return
    if phone_text:
        import factory

        backup_dir = ROOT / ".runtime" / "projects" / project_id / "cover_phone_bar_backups"
        service_grid = factory.ROAD_RESCUE_SERVICE_GRID if project_id == "road_rescue" else None
        factory.draw_cover_phone_bar(target, str(phone_text), int(item["group_index"]), backup_dir, service_grid_items=service_grid)
    validate_cover(target, item.get("expected_text", []))


def finalize_detail(item: dict[str, Any], target: Path, project_id: str) -> None:
    label = item.get("local_label")
    if project_id == "home_appliance_repair" and label:
        backup_dir = ROOT / ".runtime" / "projects" / project_id / "detail_label_backups"
        draw_home_detail_label(target, str(label), int(item["group_index"]), backup_dir)


def run(args: argparse.Namespace) -> int:
    job_file = Path(args.job_file).resolve()
    job = json.loads(job_file.read_text(encoding="utf-8"))
    project_id = args.project_id
    lock_path = acquire_lock(job["job_id"], project_id, args.group_start, args.group_count)
    try:
        config = image_generate.apply_provider_config(image_generate.load_json(ROOT / "config.json"))
        run_plan = plan(args.group_start, args.group_count, project_id)
        license_path = Path(args.license).resolve()
        license_data = consume_license(license_path, run_plan, config)
        request_budget = int(license_data["approved_request_budget"])
        records = production_records(args.group_start, args.group_count, project_id)
        api_key_slots = args.api_key_slot or license_data.get("api_key_slots", [])
        api_key_policy = license_data.get("api_key_policy", "fixed" if api_key_slots else "fair-share")
        key_count = len(image_generate.configured_api_keys())
        if api_key_slots and max(api_key_slots) > key_count:
            raise RuntimeError("configured API key count is below requested api key slot")
        client_slots = api_key_slots if api_key_policy == "fixed" else []
        clients = openai_clients_by_slot(config, client_slots)
        completed = reused = failed = requests_used = 0
        event_path = job_file.with_suffix(".events.jsonl")
        pending: list[dict[str, Any]] = []
        image_generate.update_job(
            job_file, status="running", total_images=len(records), completed=0, failed=0,
            worker_count=len(assigned_slots(job_file, api_key_slots, key_count)),
        )
        for item in records:
            target = as_path(item["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if image_file_is_valid(target):
                if item["role"] == "cover" and not target.with_suffix(".validation.json").is_file():
                    finalize_cover(item, target, project_id)
                completed += 1
                continue
            source = item.get("source")
            if source and image_file_is_valid(as_path(source)):
                shutil.copy2(as_path(source), target)
                if item["role"] == "cover":
                    finalize_cover(item, target, project_id)
                elif item["role"] == "detail":
                    finalize_detail(item, target, project_id)
                completed += 1
                reused += 1
                append_event(event_path, {"status": "reused", "target": str(target), "group_index": item["group_index"]})
                image_generate.update_job(job_file, completed=completed, reused=reused, current_index=None, last_saved=str(target))
                continue
            pending.append(item)

        state_lock = threading.Lock()
        stop_event = threading.Event()
        pending_queue = deque(pending)
        disabled_slots = quarantined_api_key_slots(config)
        last_error = None

        def worker(slot: int, client: Any) -> None:
            nonlocal completed, failed, requests_used, last_error
            while not stop_event.is_set():
                if api_key_policy == "fair-share" and slot not in assigned_slots(job_file, api_key_slots, key_count):
                    time.sleep(0.75)
                    continue
                with state_lock:
                    if slot in disabled_slots:
                        return
                    if requests_used >= request_budget:
                        stop_event.set()
                        return
                    try:
                        item = pending_queue.popleft()
                    except IndexError:
                        stop_event.set()
                        return
                target = as_path(item["target"])
                success = False
                item_error = None
                slot_hard_failure = False
                for attempt in range(1, args.max_attempts + 1):
                    with state_lock:
                        if requests_used >= request_budget or stop_event.is_set():
                            return
                        requests_used += 1
                        license_data["requests_used"] = requests_used
                        atomic_json(license_path, license_data)
                        image_generate.update_job(
                            job_file, status="waiting_for_api", current_group=item["group_index"],
                            current_position=item["position"], requests_used=requests_used,
                            worker_count=len(assigned_slots(job_file, api_key_slots, key_count)),
                        )
                    try:
                        payload = image_generate.generate_one(client, config, item["prompt"] + project_style_suffix(item["role"], project_id))
                        save_generated_image(target, payload)
                        success = True
                        break
                    except Exception as exc:
                        item_error = str(exc)
                        slot_hard_failure = api_key_slot_hard_failure(item_error)
                        with state_lock:
                            append_event(
                                event_path,
                                {
                                    "status": "request_failed", "target": str(target), "attempt": attempt,
                                    "api_key_slot": slot, "slot_hard_failure": slot_hard_failure,
                                    "error": item_error,
                                },
                            )
                            if slot_hard_failure:
                                disabled_slots.add(slot)
                                quarantine_api_key_slot(slot, config, item_error, str(job["job_id"]))
                                append_event(
                                    event_path,
                                    {
                                        "status": "api_key_disabled", "api_key_slot": slot,
                                        "reason": item_error,
                                    },
                                )
                                image_generate.update_job(
                                    job_file,
                                    last_error=item_error,
                                    disabled_api_key_slots=sorted(disabled_slots),
                                    current_group=None,
                                )
                        if slot_hard_failure:
                            break
                        if attempt < args.max_attempts:
                            time.sleep(min(8, 2 ** attempt))
                if success:
                    if item["role"] == "cover":
                        finalize_cover(item, target, project_id)
                    elif item["role"] == "detail":
                        finalize_detail(item, target, project_id)
                    with state_lock:
                        completed += 1
                        append_event(
                            event_path,
                            {
                                "status": "generated", "target": str(target),
                                "group_index": item["group_index"], "api_key_slot": slot,
                            },
                        )
                        image_generate.update_job(
                            job_file, status="running", completed=completed,
                            last_saved=str(target), current_group=None,
                        )
                else:
                    with state_lock:
                        if slot_hard_failure and requests_used < request_budget and not image_file_is_valid(target):
                            pending_queue.append(item)
                            return
                        failed += 1
                        last_error = item_error or "request budget exhausted"
                        image_generate.update_job(
                            job_file, failed=failed, last_error=last_error, current_group=None,
                            disabled_api_key_slots=sorted(disabled_slots),
                        )
                        if failed >= args.max_failures or requests_used >= request_budget:
                            stop_event.set()

        if pending:
            max_workers = min(len(clients), len(pending), max(1, request_budget - requests_used))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(worker, slot, client) for slot, client in clients[:max_workers]]
                for future in futures:
                    future.result()

        final = audit_groups(args.group_start, args.group_count, project_id)
        state = "completed" if failed == 0 and final["complete_groups"] == args.group_count else "completed_with_errors"
        image_generate.update_job(
            job_file, status=state, completed=completed, reused=reused, failed=failed,
            requests_used=requests_used, complete_groups=final["complete_groups"],
            incomplete_groups=final["incomplete_groups"], finished_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            import factory

            factory.rebalance_active_api_key_slots()
        except Exception:
            pass
        return 0 if state == "completed" else 1
    finally:
        if lock_path.exists():
            lock_path.unlink()


def audit_groups(group_start: int, group_count: int, project_id: str = "road_rescue") -> dict[str, Any]:
    is_independent_triptych, configured_roles = category_delivery_structure(project_id)
    records = production_records(group_start, group_count, project_id)
    groups: dict[int, list[dict[str, Any]]] = {}
    for item in records:
        groups.setdefault(item["group_index"], []).append(item)
    details = []
    for group_index in range(group_start, group_start + group_count):
        items = sorted(
            groups.get(group_index, []),
            key=_record_position,
        )
        roles = [str(item.get("role") or "") for item in items]
        expected_roles = configured_roles if is_independent_triptych else None
        roles_valid = expected_roles is None or roles == expected_roles
        positions = [_record_position(item) for item in items]
        positions_valid = positions == list(range(1, len(items) + 1))
        missing = [item["filename"] for item in items if not as_path(item["target"]).is_file()]
        invalid = [
            item["filename"]
            for item in items
            if as_path(item["target"]).is_file()
            and not image_file_is_valid(
                as_path(item["target"]),
                _record_expected_size(item),
            )
        ]
        size_contract_missing = [
            item["filename"]
            for item in items
            if is_independent_triptych and _record_expected_size(item) is None
        ]
        validation_statuses: list[dict[str, Any]] = []
        if is_independent_triptych:
            for item in items:
                target = as_path(item["target"])
                if not target.is_file() or not image_file_is_valid(
                    target, _record_expected_size(item)
                ):
                    approved, status = False, "image_not_ready"
                else:
                    approved, status = _pipe_validation_status(item, target, project_id)
                validation_statuses.append({
                    "position": _record_position(item),
                    "role": str(item.get("role") or ""),
                    "approved": approved,
                    "status": status,
                })
            validations_approved = (
                len(validation_statuses) == len(expected_roles or [])
                and all(item["approved"] for item in validation_statuses)
            )
            text_approved = bool(
                validation_statuses
                and validation_statuses[0]["role"] == "cover"
                and validation_statuses[0]["approved"]
            )
        else:
            cover = next((item for item in items if item.get("role") == "cover"), None)
            validation_file = (
                as_path(cover["target"]).with_suffix(".validation.json")
                if cover
                else None
            )
            validation = (
                json.loads(validation_file.read_text(encoding="utf-8"))
                if validation_file and validation_file.is_file()
                else None
            )
            text_approved = bool(validation and validation.get("approved"))
            validations_approved = text_approved
            validation_statuses = [{
                "position": 1,
                "role": "cover",
                "approved": text_approved,
                "status": validation.get("status") if validation else "not_checked",
            }]
        image_complete = (
            bool(items)
            and not missing
            and not invalid
            and not size_contract_missing
            and roles_valid
            and positions_valid
        )
        details.append({
            "group_index": group_index,
            "image_complete": image_complete,
            "text_approved": text_approved,
            "all_validations_approved": validations_approved,
            "delivery_ready": image_complete and validations_approved,
            "missing": missing,
            "invalid": invalid,
            "missing_expected_size": size_contract_missing,
            "roles": roles,
            "expected_roles": expected_roles,
            "roles_valid": roles_valid,
            "positions_valid": positions_valid,
            "validations": validation_statuses,
            "text_validation_status": validation_statuses[0]["status"]
            if validation_statuses
            else "not_checked",
        })
    return {
        "project_id": project_id, "group_start": group_start, "group_count": group_count,
        "complete_groups": sum(item["image_complete"] for item in details),
        "incomplete_groups": sum(not item["image_complete"] for item in details),
        "delivery_ready_groups": sum(item["delivery_ready"] for item in details), "groups": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan")
    audit_parser = sub.add_parser("audit")
    run_parser = sub.add_parser("run")
    for item in [plan_parser, audit_parser, run_parser]:
        item.add_argument("--project-id", default="road_rescue")
        item.add_argument("--group-start", type=int, required=True)
        item.add_argument("--group-count", type=int, required=True)
    run_parser.add_argument("--license", required=True)
    run_parser.add_argument("--job-file", required=True)
    run_parser.add_argument("--max-attempts", type=int, default=1)
    run_parser.add_argument("--max-failures", type=int, default=1)
    run_parser.add_argument("--api-key-slot", type=int, action="append")
    args = parser.parse_args()
    if args.group_start < 1 or args.group_count < 1:
        raise ValueError("invalid group range")
    if args.command == "plan":
        print(json.dumps(plan(args.group_start, args.group_count, args.project_id), ensure_ascii=False, indent=2))
    elif args.command == "audit":
        print(json.dumps(audit_groups(args.group_start, args.group_count, args.project_id), ensure_ascii=False, indent=2))
    else:
        try:
            code = run(args)
        except BaseException as exc:
            job_file = Path(args.job_file).resolve()
            if job_file.is_file():
                image_generate.update_job(
                    job_file, status="failed", last_error=str(exc),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
            try:
                import factory

                factory.rebalance_active_api_key_slots()
            except Exception:
                pass
            raise
        raise SystemExit(code)


if __name__ == "__main__":
    main()
