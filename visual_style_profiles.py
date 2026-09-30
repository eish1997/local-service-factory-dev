from __future__ import annotations

from tools import variable_catalog, runtime_paths

import json
import random
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_VISUAL_STYLE = ROOT / "configs" / "visual_styles" / "realistic_mobile_documentary_v2.json"


@variable_catalog.document_loader
def load_json(path: Path) -> dict[str, Any]:
    return runtime_paths.read_json(path)


def project_definition(project_id: str) -> dict[str, Any]:
    registry = load_json(ROOT / "projects" / "registry.json")
    entry = next((item for item in registry["projects"] if item["id"] == project_id), None)
    if not entry:
        raise ValueError(f"unknown project: {project_id}")
    return load_json(ROOT / entry["definition"])


def visual_style_path(project_id: str) -> Path:
    definition = project_definition(project_id)
    configured = definition.get("prompt_sources", {}).get("visual_style")
    if configured:
        return ROOT / str(configured)
    return DEFAULT_VISUAL_STYLE


def load_visual_style(project_id: str) -> dict[str, Any]:
    return load_json(visual_style_path(project_id))


def visual_style_version(project_id: str) -> str:
    return str(load_visual_style(project_id)["version"])


def category_config_version(project_id: str) -> str:
    definition = project_definition(project_id)
    return str(definition.get("category_config_version") or f"{project_id}_category_content_v1")


def target_mode_suffix(project_id: str) -> str:
    """Return the shared future-only realism and de-homogenization rules."""
    style = load_visual_style(project_id)
    target_mode = style.get("target_mode", {})
    if not isinstance(target_mode, dict) or target_mode.get("enabled") is not True:
        return ""
    version = str(target_mode.get("version") or "target_mode")
    positive = list(target_mode.get("positive_rules", []))
    negative = list(target_mode.get("negative_rules", []))
    rules = [
        *(f"保持：{rule}" for rule in positive),
        *(f"严格避免：{rule}" for rule in negative),
    ]
    if not rules:
        return ""
    return f"\n\n目标模式 {version}：\n" + "\n".join(f"- {rule}" for rule in rules)


def ensure_target_mode(prompt: str, project_id: str) -> str:
    """Append target-mode rules once when a legacy source prompt lacks them."""
    style = load_visual_style(project_id)
    target_mode = style.get("target_mode", {})
    if not isinstance(target_mode, dict) or target_mode.get("enabled") is not True:
        return prompt
    version = str(target_mode.get("version") or "target_mode")
    marker = f"目标模式 {version}："
    return prompt if marker in prompt else prompt + target_mode_suffix(project_id)


def target_mode_metadata(project_id: str) -> dict[str, Any]:
    style = load_visual_style(project_id)
    target_mode = style.get("target_mode", {})
    if not isinstance(target_mode, dict):
        return {"enabled": False}
    return {
        "enabled": target_mode.get("enabled") is True,
        "version": str(target_mode.get("version") or ""),
    }


def prompt_suffix(project_id: str, section: str) -> str:
    style = load_visual_style(project_id)
    shared = list(style.get("shared_positive_rules", []))
    negative = list(style.get("shared_negative_rules", []))
    section_rules = list(style.get("section_rules", {}).get(section, []))
    lines = [*shared, *section_rules, *negative]
    if not lines:
        return ""
    rendered = "\n".join(f"- {line}" for line in lines)
    return f"\n\n视觉风格预设 {style['version']}：\n{rendered}" + target_mode_suffix(project_id)


def choose_lens(
    project_id: str,
    rng: random.Random,
    *,
    location_group: str | None = None,
    job_name: str | None = None,
    section: str = "road_rescue_detail",
) -> dict[str, Any]:
    style = load_visual_style(project_id)
    lenses = list(style.get("lens_presets", {}).get(section, []))
    if not lenses:
        return {"id": "default", "prompt": "普通手机随手拍视角，构图自然不过分规整"}

    compatible: list[dict[str, Any]] = []
    for lens in lenses:
        locations = set(lens.get("location_groups", []))
        jobs = set(lens.get("jobs", []))
        location_ok = not locations or location_group in locations
        job_ok = not jobs or job_name in jobs
        if location_ok and job_ok:
            compatible.append(lens)
    pool = compatible or lenses
    return rng.choice(pool)
