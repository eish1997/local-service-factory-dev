"""Offline package and prompt-manifest validation. Never calls an API."""

from __future__ import annotations

import json
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = [
    "agent.md",
    "AGENTS.md",
    "CLAUDE.md",
    "START_HERE.md",
    "HELP.md",
    "README.md",
    ".env.example",
    ".gitignore",
    "factory.py",
    "config.json",
    "scene_library.json",
    "generate_prompts.py",
    "generate_group_prompts.py",
    "group_production.py",
    "image_generate.py",
    "tools/audit_prompts.py",
    "tools/status.py",
    "tools/validate_cover_text.py",
    ".agents/skills/road-rescue-factory/SKILL.md",
    ".agents/skills/road-rescue-factory/agents/openai.yaml",
    ".agents/skills/road-rescue-factory/references/capabilities.md",
    ".agents/skills/road-rescue-factory/references/api-setup.md",
    ".agents/skills/road-rescue-factory/references/relay-setup.md",
    ".agents/skills/road-rescue-factory/references/quality.md",
    ".agents/skills/road-rescue-factory/references/multi-project.md",
    "preferences/STYLE_PROFILE.md",
    "preferences/REJECTED_PATTERNS.md",
    "preferences/sample_reviews.jsonl",
    "requirements.txt",
    "MULTI_PROJECT_ARCHITECTURE.md",
    "projects/registry.json",
    "projects/road_rescue/project.json",
    "projects/road_rescue/cover_scene_library.json",
    "projects/road_rescue/cover_style_profile.md",
    "projects/road_rescue/groups/registry.json",
    "projects/road_rescue/preferences/STYLE_PROFILE.md",
    "projects/road_rescue/preferences/REJECTED_PATTERNS.md",
    "projects/road_rescue/preferences/prompt_versions.json",
    "projects/road_rescue/preferences/prompt_tuning_rules.jsonl",
    "dashboard/package.json",
    "dashboard/main.js",
    "dashboard/preload.js",
    "dashboard/session.js",
    "dashboard/renderer/index.html",
    "dashboard/renderer/styles.css",
    "dashboard/renderer/compact-overrides.css",
    "dashboard/renderer/app.js",
    "dashboard/renderer/viewer.html",
    "dashboard/renderer/viewer.css",
    "dashboard/renderer/viewer.js",
    "dashboard/RoadRescueDashboard.exe",
    "providers/registry.json",
    "providers/openai-official.md",
    "providers/tinysnow.md",
]
REQUIRED_DIRS = ["prompts", "output", "tools", "providers", "projects", "projects/road_rescue", "dashboard", "dashboard/renderer"]


def main() -> None:
    errors: list[str] = []
    for name in REQUIRED_FILES:
        path = ROOT / name
        if not path.is_file():
            errors.append(f"missing file: {name}")
        elif path.stat().st_size == 0:
            errors.append(f"empty file: {name}")
    for name in REQUIRED_DIRS:
        if not (ROOT / name).is_dir():
            errors.append(f"missing directory: {name}")

    try:
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        json.loads((ROOT / "scene_library.json").read_text(encoding="utf-8"))
        provider_registry = json.loads((ROOT / "providers/registry.json").read_text(encoding="utf-8"))
        project_registry = json.loads((ROOT / "projects/registry.json").read_text(encoding="utf-8"))
        road_project = json.loads((ROOT / "projects/road_rescue/project.json").read_text(encoding="utf-8"))
        if provider_registry.get("schema_version") != 1 or not provider_registry.get("providers"):
            errors.append("invalid provider registry schema")
        provider_ids = [item["id"] for item in provider_registry.get("providers", [])]
        if len(provider_ids) != len(set(provider_ids)):
            errors.append("duplicate provider ids")
        if project_registry.get("schema_version") != 1 or not project_registry.get("projects"):
            errors.append("invalid project registry schema")
        group = road_project.get("content_group", {})
        expected_group = {
            "cover_count": 1,
            "triptych_count": 1,
            "triptych_panel_count": 3,
            "detail_count": 3,
            "total_images": 5,
            "generation_unit_count": 7,
        }
        if any(group.get(key) != value for key, value in expected_group.items()):
            errors.append("road-rescue v3 content group must deliver 1 cover + 1 triptych + 3 details from 7 generation units")
    except Exception as exc:
        errors.append(f"invalid JSON: {exc}")
        config = {}

    for name in ["factory.py", "generate_prompts.py", "generate_group_prompts.py", "group_production.py", "image_generate.py", "tools/audit_prompts.py", "tools/status.py", "tools/validate_cover_text.py"]:
        try:
            py_compile.compile(str(ROOT / name), doraise=True)
        except Exception as exc:
            errors.append(f"invalid Python {name}: {exc}")

    prompt_path = ROOT / config.get("prompt_file", "prompts/road_rescue_prompts.jsonl")
    try:
        records = [json.loads(line) for line in prompt_path.read_text(encoding="utf-8").splitlines() if line]
        registry_path = ROOT / config.get("batch_registry", "prompts/batch_registry.json")
        if registry_path.exists():
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            expected = int(registry["total_prompts"])
        else:
            expected = int(config["prompt_count"])
        if len(records) != expected:
            errors.append(f"prompt count: expected {expected}, found {len(records)}")
        if [r["index"] for r in records] != list(range(1, expected + 1)):
            errors.append("prompt indexes are not continuous")
        if len({r["filename"] for r in records}) != len(records):
            errors.append("duplicate filenames")
        if len({r["prompt"] for r in records}) != len(records):
            errors.append("duplicate prompts")
        if len({r["prompt_sha256"] for r in records}) != len(records):
            errors.append("duplicate prompt hashes")
    except Exception as exc:
        errors.append(f"invalid prompt manifest: {exc}")

    if errors:
        print("SELF_CHECK_FAILED")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"SELF_CHECK_OK prompts={len(records)} api_called=false")


if __name__ == "__main__":
    main()
