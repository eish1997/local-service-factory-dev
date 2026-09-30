"""Show project readiness without network access or API calls."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent


def load_project_env() -> bool:
    path = ROOT / ".env"
    if not path.is_file():
        return False
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in {"OPENAI_API_KEY", "OPENAI_PROVIDER", "OPENAI_BASE_URL", "OPENAI_IMAGE_MODEL", "OPENAI_PROVIDER_DOCS_URL"}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value:
            os.environ[name] = value
    return bool(os.environ.get("OPENAI_API_KEY"))


def main() -> None:
    config_path = ROOT / "config.json"
    prompt_count = 0
    expected_count = 0
    config_ok = False
    config: dict = {}
    prompt_file = ROOT / "prompts" / "road_rescue_prompts.jsonl"
    output_dir = ROOT / "output"

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config_ok = True
        registry_path = ROOT / config.get("batch_registry", "prompts/batch_registry.json")
        if registry_path.exists():
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            expected_count = int(registry["total_prompts"])
            batch_count = len(registry["batches"])
            next_index = int(registry["next_index"])
        else:
            expected_count = int(config["prompt_count"])
            batch_count = 1
            next_index = expected_count + 1
        prompt_file = ROOT / config["prompt_file"]
        output_dir = ROOT / config["output_dir"]
    except Exception:
        batch_count = 0
        next_index = 1
        pass

    try:
        prompt_count = sum(1 for line in prompt_file.read_text(encoding="utf-8").splitlines() if line)
    except Exception:
        prompt_count = 0

    png_files = sorted(output_dir.glob("road_rescue_[0-9][0-9][0-9][0-9].png")) if output_dir.is_dir() else []
    existing_indexes: set[int] = set()
    for path in png_files:
        try:
            existing_indexes.add(int(path.stem.rsplit("_", 1)[1]))
        except ValueError:
            pass

    load_project_env()
    package_installed = importlib.util.find_spec("openai") is not None
    key_configured = bool(os.environ.get("OPENAI_API_KEY"))
    provider = os.environ.get("OPENAI_PROVIDER", "official") or "official"
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    image_model = os.environ.get("OPENAI_IMAGE_MODEL", "") or config.get("model", "")
    license_path = ROOT / ".runtime" / "execution_license.json"
    try:
        license_state = json.loads(license_path.read_text(encoding="utf-8")).get("status", "missing")
    except Exception:
        license_state = "missing"
    review_path = ROOT / "preferences" / "sample_reviews.jsonl"
    try:
        review_count = sum(1 for line in review_path.read_text(encoding="utf-8").splitlines() if line)
    except Exception:
        review_count = 0
    relay_url_valid = True
    if provider == "relay":
        parsed = urlparse(base_url)
        relay_url_valid = bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    state = {
        "offline_check_only": True,
        "api_called": False,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "python_supported": sys.version_info >= (3, 9),
        "config_ok": config_ok,
        "prompts_ready": expected_count > 0 and prompt_count == expected_count,
        "prompt_count": prompt_count,
        "expected_prompt_count": expected_count,
        "openai_package_installed": package_installed,
        "openai_api_key_configured": key_configured,
        "project_env_file_present": (ROOT / ".env").is_file(),
        "api_provider": provider,
        "api_base_url": base_url if provider == "relay" else "https://api.openai.com/v1",
        "relay_url_valid": relay_url_valid,
        "effective_image_model": image_model,
        "generated_image_count": len(existing_indexes),
        "remaining_image_count": max(expected_count - len(existing_indexes), 0),
        "batch_count": batch_count,
        "next_prompt_index": next_index,
        "codex_repo_skill_present": (ROOT / ".agents" / "skills" / "road-rescue-factory" / "SKILL.md").is_file(),
        "style_profile_present": (ROOT / "preferences" / "STYLE_PROFILE.md").is_file(),
        "sample_review_count": review_count,
        "execution_license_status": license_state,
        "batch_generation_ready": (
            sys.version_info >= (3, 9)
            and config_ok
            and prompt_count == expected_count
            and package_installed
            and key_configured
            and relay_url_valid
        ),
    }
    print("STATUS_OK api_called=false")
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
