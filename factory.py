"""Single command surface for the road-rescue image factory."""

from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog, lock_prompt_builder

import argparse
import json
import secrets
import subprocess
import sys
import re
import os
import shutil
import hashlib
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tools import (
    category_batch_audit,
    category_generation_profile,
    category_image_production,
    dashboard_delivery,
    prompt_engine,
)
from tools.contact_numbers import (
    extract_contact_numbers,
    is_placeholder_contact_number,
    normalize_contact_number,
)


ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = ROOT / ".runtime"
LICENSE_PATH = RUNTIME_DIR / "execution_license.json"
PREVIEW_PATH = RUNTIME_DIR / "preview_selection.json"
JOBS_DIR = RUNTIME_DIR / "jobs"
DASHBOARD_SESSION_PATH = RUNTIME_DIR / "dashboard_session.json"
DASHBOARD_SESSION_ARCHIVE_DIR = RUNTIME_DIR / "dashboard_archive" / "sessions"
DASHBOARD_DELIVERY_STATE_PATH = RUNTIME_DIR / "dashboard_delivery_state.json"
PACKAGED_DASHBOARD_EXE = ROOT / "dashboard" / "dist" / "win-unpacked" / "道路救援图片看板.exe"
PORTABLE_DASHBOARD_EXE = ROOT / "dashboard" / "dist" / "RoadRescueDashboard-1.2.0-portable.exe"
LEGACY_DASHBOARD_EXE = ROOT / "dashboard" / "RoadRescueDashboard.exe"
DASHBOARD_EXE = next(
    (path for path in (PACKAGED_DASHBOARD_EXE, PORTABLE_DASHBOARD_EXE, LEGACY_DASHBOARD_EXE) if path.is_file()),
    LEGACY_DASHBOARD_EXE,
)
GROUP_LICENSE_PATH = RUNTIME_DIR / "group_execution_license.json"
GROUP_LICENSE_DIR = RUNTIME_DIR / "group_execution_licenses"
PIPE_PROJECT_ID = "pipe_unclogging"
ROAD_PROJECT_ID = "road_rescue"
PET_PROJECT_ID = "pet_transport"
TRUCK_PROJECT_ID = "truck_rescue"
CATEGORY_IMAGE_PROJECT_IDS = {
    "ktv",
    PIPE_PROJECT_ID,
    ROAD_PROJECT_ID,
    PET_PROJECT_ID,
    TRUCK_PROJECT_ID,
}
PIPE_SAMPLE_GROUP_START = 1
PIPE_SAMPLE_GROUP_COUNT = 3
PIPE_OUTPUT_ROOT = ROOT / "output" / PIPE_PROJECT_ID
ENV_PATH = runtime_paths.data_root() / ".env"
PROVIDER_REGISTRY_PATH = ROOT / "providers" / "registry.json"
PROJECT_REGISTRY_PATH = ROOT / "projects" / "registry.json"
ENV_FIELDS = (
    "OPENAI_API_KEY",
    "OPENAI_API_KEY_2",
    "OPENAI_API_KEY_3",
    "OPENAI_API_KEY_4",
    "OPENAI_API_KEY_5",
    "OPENAI_API_KEY_6",
    "OPENAI_API_KEY_7",
    "OPENAI_API_KEY_8",
    "OPENAI_API_KEY_9",
    "OPENAI_API_KEY_10",
    "OPENAI_API_KEYS",
    "OPENAI_PROVIDER",
    "OPENAI_BASE_URL",
    "OPENAI_IMAGE_MODEL",
    "OPENAI_PROVIDER_DOCS_URL",
)
CATEGORY_RESUME_SERIAL_POLICY = "serial_probe_policy_circuit_v1"
CATEGORY_RESUME_FIXED_TEN_POLICY = "fixed_10_probe_policy_circuit_v1"
CATEGORY_RESUME_BALANCE_AUTHORIZATION_FIELDS = (
    "approved_balance_recoverable_count",
    "approved_balance_recoverable_ids_sha256",
    "approved_balance_failure_request_count",
    "approved_additional_recovery_request_budget",
)


def load_json(path: Path) -> dict[str, Any]:
    return runtime_paths.read_json(path)


def load_provider_registry() -> dict[str, Any]:
    registry = load_json(PROVIDER_REGISTRY_PATH)
    if registry.get("schema_version") != 1 or not isinstance(registry.get("providers"), list):
        raise ValueError("invalid provider registry")
    return registry


def provider_status_label(status: str) -> str:
    return {
        "verified": "已验证",
        "config_compatible": "配置兼容",
        "partial": "部分兼容",
        "unavailable": "不可用",
        "retired": "已停用",
    }.get(status, f"未知状态({status})")


def current_provider_id(registry: dict[str, Any]) -> str:
    values = parse_env_file(ENV_PATH)
    if (values.get("OPENAI_PROVIDER") or "official") == "official":
        return "openai-official"
    base_url = (values.get("OPENAI_BASE_URL") or "").rstrip("/")
    for provider in registry["providers"]:
        if (provider.get("base_url") or "").rstrip("/") == base_url:
            return provider["id"]
    return "custom-relay"


def print_provider_summary() -> None:
    registry = load_provider_registry()
    current = current_provider_id(registry)
    print("\n当前与已登记的图片服务：")
    for provider in registry["providers"]:
        marker = "（当前）" if provider["id"] == current else ""
        print(f"- {provider['name']}：{provider_status_label(provider['status'])}{marker}")
    if current == "custom-relay":
        print("- 自定义中转站：未登记（当前）")
    print("查看详情：python factory.py providers")


def load_project_registry() -> dict[str, Any]:
    registry = load_json(PROJECT_REGISTRY_PATH)
    if registry.get("schema_version") != 1 or not isinstance(registry.get("projects"), list):
        raise ValueError("invalid project registry")
    return registry


def project_definition(project_id: str) -> dict[str, Any]:
    registry = load_project_registry()
    entry = next((item for item in registry["projects"] if item["id"] == project_id), None)
    if not entry:
        raise ValueError(f"unknown project: {project_id}")
    return load_json(ROOT / entry["definition"])


def project_definition_path(project_id: str) -> Path:
    registry = load_project_registry()
    entry = next((item for item in registry["projects"] if item["id"] == project_id), None)
    if not entry:
        raise ValueError(f"unknown project: {project_id}")
    return ROOT / entry["definition"]


def ensure_env_file() -> Path:
    if not ENV_PATH.exists():
        example = ROOT / ".env.example"
        content = example.read_text(encoding="utf-8") if example.exists() else "OPENAI_API_KEY=\n"
        ENV_PATH.write_text(content, encoding="utf-8")
    existing = ENV_PATH.read_text(encoding="utf-8-sig")
    present = {
        line.split("=", 1)[0].strip()
        for line in existing.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    defaults = {
        "OPENAI_API_KEY": "",
        "OPENAI_API_KEY_2": "",
        "OPENAI_API_KEY_3": "",
        "OPENAI_API_KEY_4": "",
        "OPENAI_API_KEY_5": "",
        "OPENAI_API_KEY_6": "",
        "OPENAI_API_KEY_7": "",
        "OPENAI_API_KEY_8": "",
        "OPENAI_API_KEY_9": "",
        "OPENAI_API_KEY_10": "",
        "OPENAI_API_KEYS": "",
        "OPENAI_PROVIDER": "official",
        "OPENAI_BASE_URL": "",
        "OPENAI_IMAGE_MODEL": "",
        "OPENAI_PROVIDER_DOCS_URL": "",
    }
    missing = [name for name in ENV_FIELDS if name not in present]
    if missing:
        suffix = "" if existing.endswith("\n") else "\n"
        suffix += "".join(f"{name}={defaults[name]}\n" for name in missing)
        ENV_PATH.write_text(existing + suffix, encoding="utf-8")
    return ENV_PATH


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in ENV_FIELDS and not re.fullmatch(r"OPENAI_API_KEY(?:_\d+)?", name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def load_project_env(path: Path = ENV_PATH) -> bool:
    """Load supported project settings without printing secrets."""
    import os

    values = parse_env_file(path)
    for name, value in values.items():
        if value:
            os.environ[name] = value
        elif not re.fullmatch(r"OPENAI_API_KEY(?:_\d+)?", name):
            os.environ.pop(name, None)
    return bool(values.get("OPENAI_API_KEY"))


def write_env_values(updates: dict[str, str], path: Path = ENV_PATH) -> None:
    if not path.exists():
        path.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    replaced: set[str] = set()
    output: list[str] = []
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            name = line.split("=", 1)[0].strip()
            if name in updates:
                output.append(f"{name}={updates[name]}")
                replaced.add(name)
                continue
        output.append(line)
    for name, value in updates.items():
        if name not in replaced:
            output.append(f"{name}={value}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_public_https_url(value: str, label: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{label} must be a complete https:// URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{label} must not contain credentials, query parameters, or fragments")
    return value.strip().rstrip("/")


def effective_api_config(config: dict[str, Any]) -> dict[str, Any]:
    import os

    load_project_env(ensure_env_file())
    result = dict(config)
    if os.environ.get("OPENAI_IMAGE_MODEL"):
        result["model"] = os.environ["OPENAI_IMAGE_MODEL"]
    result["provider"] = os.environ.get("OPENAI_PROVIDER", "official").strip() or "official"
    if result["provider"] == "relay":
        result["base_url"] = validate_public_https_url(os.environ.get("OPENAI_BASE_URL", ""), "base URL")
    elif result["provider"] == "official":
        result["base_url"] = ""
    else:
        raise ValueError("OPENAI_PROVIDER must be official or relay")
    return result


def run_python(relative_script: str, *arguments: str) -> int:
    command = [sys.executable, str(ROOT / relative_script), *arguments]
    child_env = dict(os.environ)
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    child_env.setdefault("PYTHONUTF8", "1")
    return subprocess.run(command, cwd=ROOT, check=False, env=child_env).returncode


def command_help(_: argparse.Namespace) -> int:
    run_python("tools/status.py")
    print_provider_summary()
    road_rescue = project_definition("road_rescue")
    business_path = RUNTIME_DIR / "projects" / "road_rescue" / "business.json"
    business = load_json(business_path) if business_path.is_file() else {}
    contact_ready = bool(business.get("user_confirmed") and business.get("contact_phones") and not business.get("placeholder_only"))
    cover_ready = bool(road_rescue["references"]["cover"]["approved_style"])
    if cover_ready and not contact_ready:
        next_step = "当前建议：首图风格已确认。下一步请提供正式联系电话；确认后才能生成正式首图提示词和九图组。"
    elif not cover_ready:
        next_step = "当前建议：先生成并确认首图测试效果，再填写正式联系电话。"
    else:
        next_step = "当前建议：首图风格与联系电话已就绪，可以规划正式九图组。"
    print(
        f"""
图片内容工厂｜请选择下一步：
{next_step}

1. 填写或更换正式联系电话（只保存在本机，不进入交付包）
2. 继续当前汽车救援项目（每组1张首图+8张详情图）
3. 创建新的图片项目，例如宠物托运、开锁换锁
4. 根据参考图提取风格并生成1-2张测试图
5. 调优提示词：逐项调整年代感、门头、电话、车辆、人物、镜头或真实感
6. 免费检查、抽查或追加提示词（本地生成，不调用LLM和图片API）
7. 配置官方API、接入中转站或添加新的API Key；密钥只填写到项目.env
8. 制定九图组生图计划并显示需要付费生成的准确数量
9. 查询后台任务进度与号池状态（只读本地记录，不发送新的图片请求）
10. 打开本地图片看板或图片目录
11. 验收内容组：检查9张是否齐全以及首图文字是否正确
12. 打包不含密钥、缓存和付费图片的交付压缩包

当前能力与完整新手流程请阅读 HELP.md。开始付费任务后，本地图片看板会自动以置顶精简模式打开。
你可以直接回复数字或自然语言，不必亲自输入命令。
""".strip()
    )
    return 0


def command_projects(_: argparse.Namespace) -> int:
    registry = load_project_registry()
    print("CONTENT_PROJECTS")
    for item in registry["projects"]:
        definition = load_json(ROOT / item["definition"])
        group = definition["content_group"]
        marker = " current=true" if item["id"] == registry.get("active_project") else ""
        print(f"- {item['name']} ({item['id']}) status={item['status']}{marker}")
        if int(group.get("triptych_count", 0) or 0):
            print(
                f"  每组：{group['cover_count']}张首图 + "
                f"{group['triptych_count']}张三拼图 + "
                f"{group['detail_count']}张详情图 = {group['total_images']}张成品"
            )
        else:
            print(f"  每组：{group['cover_count']}张首图 + {group['detail_count']}张场景图 = {group['total_images']}张")
    print("新增项目引导：python factory.py new-project-guide")
    return 0


def command_project_status(args: argparse.Namespace) -> int:
    definition = project_definition(args.project_id)
    business_path = RUNTIME_DIR / "projects" / args.project_id / "business.json"
    business = load_json(business_path) if business_path.is_file() else {}
    registry = load_json(ROOT / definition["group_registry"])
    content_group = definition.get("content_group", {})
    cover_count = content_group.get("cover_count", 1)
    detail_count = content_group.get("detail_count", 8)
    total_images = content_group.get("total_images", cover_count + detail_count)
    prompt_sources = definition.get("prompt_sources", {})
    detail_prompt_count = prompt_sources.get("detail_prompt_count", 0)
    available_detail_sets = prompt_sources.get(
        "available_complete_detail_sets",
        detail_prompt_count // detail_count if detail_count else 0,
    )
    phones_ready = bool(business.get("user_confirmed") and business.get("contact_phones"))
    phone_status = "placeholder only; formal number required before batch" if business.get("placeholder_only") else ("ready" if phones_ready else "required before cover prompts")
    print(f"PROJECT_STATUS id={args.project_id} name={definition['name']}")
    triptych_count = int(content_group.get("triptych_count", 0) or 0)
    if triptych_count:
        print(
            f"Content group: {cover_count} cover + {triptych_count} triptych + "
            f"{detail_count} details = {total_images} delivery images"
        )
        print(
            f"Generation units per group: "
            f"{int(content_group.get('generation_unit_count', total_images))}"
        )
    else:
        print(f"Content group: {cover_count} cover + {detail_count} details = {total_images} images")
    print(f"Telephone confirmation: {phone_status}")
    print(f"Detail prompts: {detail_prompt_count}")
    print(f"Complete detail sets available: {available_detail_sets}")
    print(f"Groups created: {registry['created_groups']}")
    print(f"Cover reference approval: {definition['references']['cover']['approved_style']}")
    if args.project_id == PIPE_PROJECT_ID:
        inventory_policy = definition.get("inventory_policy", {})
        inventory_path = ROOT / str(
            definition.get("inventory_snapshot")
            or definition.get("inventory_ledger")
            or f"projects/{PIPE_PROJECT_ID}/groups/inventory.json"
        )
        inventory = load_json(inventory_path) if inventory_path.is_file() else {}
        summary = inventory.get("summary", {})
        print("\n小白版说明：")
        print("- 这个类目现在已经是正式项目，不会再报 unknown project。")
        print("- 每组最终5张：1张门面首图、1张三拼图、3张单独详情图。")
        print("- 从零制作每组需要7次图片请求；三拼图1张成品由3个独立现场画面本地拼合。")
        print("- 同组5张高度一致；不同组轮换高度和三拼布局，并继续变化门店、机位、人物、工具与现场。")
        print(f"- 正式生产只读取活动批次：{prompt_sources.get('active_batch', '未登记')}。")
        print(f"- 成品只放到：{PIPE_OUTPUT_ROOT}")
        print(
            f"- 库存目标：{int(inventory_policy.get('target_available_groups', 30))} 组；"
            f"当前可用：{int(summary.get('available_groups', 0))} 组。"
        )
        print(
            f"- 新风格先验收：{int(inventory_policy.get('sample_gate_groups', 3))} 组；"
            f"当前首图风格是否已确认：{bool(definition['references']['cover']['approved_style'])}。"
        )
        print("- 本命令只读取本地记录，不生成图片、不调用 API、不收费。")
    return 0


def command_new_project_guide(_: argparse.Namespace) -> int:
    print(
        """
新项目引导（AI应逐项询问，不要一次要求用户填写配置）：
1. 你要生产什么类型的图片？例如：宠物托运、开锁换锁、家电维修。
2. 一组内容由几张首图和几张场景图组成？默认建议1+8。
3. 请提供首图和场景图的参考图片；AI先分析构图、真实感、人物、环境、文字和禁用风格。
4. 哪些文字、电话、价格或品牌必须由你确认？未确认的信息不得猜测。
5. AI先反推提示词并各生成1-2张样片，用户明确确认风格后才进入批量阶段。
6. 用户选择生成10组、50组、100组或自定义组数；提示词可本地组合时不调用LLM。
7. 每组提示词、图片、审核状态和失败记录独立保存，再进入已有的一次性付费许可与后台生图流程。

对AI说：我要创建新项目，类型是……，这是首图/场景图参考。
""".strip()
    )
    return 0


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def command_create_project(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,39}", args.project_id):
        raise ValueError("project id must be 2-40 lowercase letters, digits, underscores, or hyphens")
    if args.cover_count < 1 or args.detail_count < 1:
        raise ValueError("cover and detail counts must be positive")
    registry = load_project_registry()
    if any(item["id"] == args.project_id for item in registry["projects"]):
        raise ValueError(f"project already exists: {args.project_id}")
    project_dir = ROOT / "projects" / args.project_id
    definition = {
        "schema_version": 1, "id": args.project_id, "name": args.name.strip(),
        "category": args.category.strip(), "status": "onboarding",
        "content_group": {
            "cover_count": args.cover_count, "detail_count": args.detail_count,
            "total_images": args.cover_count + args.detail_count,
            "cover_role": "等待参考图分析", "detail_role": "等待参考图分析",
        },
        "required_fields": {
            "contact_phones": {
                "required_for": [
                    "cover_prompt_generation",
                    "cover_image_generation",
                    "cover_phone_bar_postprocess",
                ],
                "confirmed": False,
                "values": [],
                "rule": "必须由用户本轮明确确认，不得从示例、历史聊天或参考图中猜测；首图中间电话条由本地后处理叠加，不能只依赖模型生成文字",
            }
        },
        "references": {
            "cover": {"status": "pending", "files": [], "approved_style": False},
            "detail": {"status": "pending", "files": [], "approved_style": False},
        },
        "prompt_sources": {
            "cover_library": f"projects/{args.project_id}/cover_scene_library.json",
            "detail_prompt_count": 0,
            "available_complete_detail_sets": 0,
        },
        "group_registry": f"projects/{args.project_id}/groups/registry.json",
        "output_dir": f"output/{args.project_id}",
    }
    write_json_atomic(project_dir / "project.json", definition)
    write_json_atomic(project_dir / "cover_scene_library.json", {"status": "pending_reference_analysis"})
    write_json_atomic(project_dir / "groups" / "registry.json", {
        "schema_version": 1, "project_id": args.project_id,
        "group_size": args.cover_count + args.detail_count,
        "cover_count": args.cover_count, "detail_count": args.detail_count,
        "created_groups": 0, "next_group_index": 1, "groups": [],
    })
    for name in ["references", "prompts", "preferences"]:
        folder = project_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".gitkeep").touch(exist_ok=True)
    (project_dir / "preferences" / "STYLE_PROFILE.md").write_text(
        f"# {args.name.strip()}项目风格\n\n"
        "等待样片反馈。\n\n"
        "## 通用首图电话规则\n\n"
        "- 涉及本地服务、门店、车辆、托运、维修等带联系方式的首图，必须先由用户确认联系电话。\n"
        "- 首图中间位置默认预留本地电话条区域，电话条文本使用已确认号码，例如“电话00000000000”。\n"
        "- 生成原图时不要把关键人脸、核心商品、主要服务文字放在画面正中电话条覆盖区域。\n"
        "- 门头、车辆、门口立牌、玻璃贴字等真实场景里可以自然出现已确认联系电话，但最终准确性以本地电话条和人工/OCR验收为准。\n",
        encoding="utf-8",
    )
    (project_dir / "preferences" / "REJECTED_PATTERNS.md").write_text(
        f"# {args.name.strip()}拒绝模式\n\n"
        "- 不要只依赖模型把电话号码画进图片；电话号码必须由本地电话条后处理保障准确。\n"
        "- 不要从参考图、示例或历史项目推断电话、价格、品牌名、门店名。\n",
        encoding="utf-8",
    )
    write_json_atomic(project_dir / "preferences" / "prompt_versions.json", {
        "schema_version": 1, "project_id": args.project_id, "versions": [],
    })
    (project_dir / "preferences" / "prompt_tuning_rules.jsonl").touch(exist_ok=True)
    registry["projects"].append({
        "id": args.project_id, "name": args.name.strip(), "status": "onboarding",
        "definition": f"projects/{args.project_id}/project.json",
    })
    write_json_atomic(PROJECT_REGISTRY_PATH, registry)
    print(f"PROJECT_CREATED id={args.project_id} status=onboarding api_called=false")
    print("Next: provide cover and detail reference images. No batch prompts should be created before style approval.")
    return 0


def command_register_reference(args: argparse.Namespace) -> int:
    definition = project_definition(args.project_id)
    source = Path(args.file).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("reference must be an existing PNG, JPG, JPEG, or WEBP image")
    destination_dir = ROOT / "projects" / args.project_id / "references" / args.role
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if not destination.exists():
        shutil.copy2(source, destination)
    relative = destination.relative_to(ROOT).as_posix()
    reference = definition["references"][args.role]
    if relative not in reference["files"]:
        reference["files"].append(relative)
    reference["status"] = "supplied_pending_analysis"
    reference["approved_style"] = False
    registry = load_project_registry()
    entry = next(item for item in registry["projects"] if item["id"] == args.project_id)
    write_json_atomic(ROOT / entry["definition"], definition)
    print(f"REFERENCE_REGISTERED project={args.project_id} role={args.role} file={relative} api_called=false")
    print("AI must inspect the image, reverse-engineer the prompt, generate samples, and obtain user approval.")
    return 0


def command_approve_style(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise RuntimeError("Style approval requires explicit user confirmation via --confirm")
    definition = project_definition(args.project_id)
    reference = definition["references"][args.role]
    if not reference["files"]:
        raise RuntimeError("No reference image is registered for this role")
    reference["status"] = "approved"
    reference["approved_style"] = True
    registry = load_project_registry()
    entry = next(item for item in registry["projects"] if item["id"] == args.project_id)
    write_json_atomic(ROOT / entry["definition"], definition)
    project_dir = (ROOT / entry["definition"]).parent
    tracked = [project_dir / "cover_scene_library.json", project_dir / "preferences" / "STYLE_PROFILE.md", project_dir / "preferences" / "REJECTED_PATTERNS.md"]
    digest = hashlib.sha256()
    for path in tracked:
        if path.is_file():
            digest.update(path.read_bytes())
    version_path = project_dir / "preferences" / "prompt_versions.json"
    versions = load_json(version_path) if version_path.is_file() else {"schema_version": 1, "project_id": args.project_id, "versions": []}
    versions["versions"].append({
        "role": args.role, "version": len(versions["versions"]) + 1,
        "sha256": digest.hexdigest(), "approved_at": datetime.now(timezone.utc).isoformat(),
    })
    write_json_atomic(version_path, versions)
    print(f"STYLE_APPROVED project={args.project_id} role={args.role} api_called=false")
    return 0


def command_project_feedback(args: argparse.Namespace) -> int:
    definition = project_definition(args.project_id)
    registry = load_project_registry()
    entry = next(item for item in registry["projects"] if item["id"] == args.project_id)
    project_dir = (ROOT / entry["definition"]).parent
    payload = {
        "project_id": args.project_id, "role": args.role, "rating": args.rating,
        "image": args.image, "note": args.note.strip(), "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    path = project_dir / "preferences" / "feedback.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(f"PROJECT_FEEDBACK_RECORDED project={args.project_id} role={args.role} rating={args.rating} api_called=false")
    print("AI should update only this project's STYLE_PROFILE.md or REJECTED_PATTERNS.md when the feedback is reusable.")
    return 0


TUNING_DIMENSIONS = [
    "年代感", "门店类型", "建筑与开间", "门头配色", "店名与业务文字", "电话大小与位置",
    "清障车占比", "维修作业", "人物与街道人流", "工具与杂乱程度", "镜头距离与角度", "天气与光线", "真实感",
]


def tuning_paths(project_id: str) -> tuple[Path, Path]:
    registry = load_project_registry()
    entry = next((item for item in registry["projects"] if item["id"] == project_id), None)
    if not entry:
        raise ValueError(f"unknown project: {project_id}")
    project_dir = (ROOT / entry["definition"]).parent
    return (
        project_dir / "preferences" / "prompt_tuning_rules.jsonl",
        RUNTIME_DIR / "projects" / project_id / "prompt_tuning_drafts.jsonl",
    )


def command_tune_prompt_guide(args: argparse.Namespace) -> int:
    project_definition(args.project_id)
    print("PROMPT_TUNING_GUIDE")
    print("先说最想改变的一件事，每轮只改1个主要维度：")
    for index, dimension in enumerate(TUNING_DIMENSIONS, start=1):
        print(f"{index}. {dimension}")
    print("然后选择动作：加强 / 减弱 / 新增 / 删除 / 保持，并描述你希望看到的具体变化。")
    print("AI先记录为本轮试验，只生成1张样片；满意后再批准为项目长期规则，不满意可直接丢弃。")
    print("示例：年代感→减弱→不要太新，主要呈现2019–2022年的普通社区汽修店。")
    return 0


def command_tune_prompt(args: argparse.Namespace) -> int:
    if args.dimension not in TUNING_DIMENSIONS:
        raise ValueError(f"unsupported dimension; choose one of: {', '.join(TUNING_DIMENSIONS)}")
    note = args.note.strip()
    if not note or len(note) > 500:
        raise ValueError("tuning note must contain 1-500 characters")
    _, draft_path = tuning_paths(args.project_id)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_id": args.project_id, "role": args.role, "dimension": args.dimension,
        "action": args.action, "note": note, "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(), "scope": "sample-draft",
    }
    with draft_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(f"TUNING_DRAFT_RECORDED project={args.project_id} dimension={args.dimension} api_called=false")
    print("Next: prepare and generate exactly 1 sample. Do not use this draft for a paid batch before approval.")
    return 0


def command_approve_prompt_tuning(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise RuntimeError("prompt tuning approval requires --confirm")
    rules_path, draft_path = tuning_paths(args.project_id)
    if not draft_path.is_file():
        raise RuntimeError("no prompt tuning drafts to approve")
    drafts = [json.loads(line) for line in draft_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not drafts:
        raise RuntimeError("no prompt tuning drafts to approve")
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    with rules_path.open("a", encoding="utf-8", newline="\n") as handle:
        for item in drafts:
            item.update({"scope": "project", "approved_at": datetime.now(timezone.utc).isoformat()})
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    draft_path.unlink()
    print(f"TUNING_APPROVED project={args.project_id} rules={len(drafts)} api_called=false")
    return 0


def command_discard_prompt_tuning(args: argparse.Namespace) -> int:
    _, draft_path = tuning_paths(args.project_id)
    if draft_path.exists():
        draft_path.unlink()
    print(f"TUNING_DRAFTS_DISCARDED project={args.project_id} api_called=false")
    return 0


def command_tuning_status(args: argparse.Namespace) -> int:
    rules_path, draft_path = tuning_paths(args.project_id)
    rules = [json.loads(line) for line in rules_path.read_text(encoding="utf-8").splitlines() if line.strip()] if rules_path.is_file() else []
    drafts = [json.loads(line) for line in draft_path.read_text(encoding="utf-8").splitlines() if line.strip()] if draft_path.is_file() else []
    print(f"TUNING_STATUS project={args.project_id} approved={len(rules)} drafts={len(drafts)}")
    for item in [*rules, *drafts]:
        print(f"- [{item['scope']}] {item['dimension']} / {item['action']}: {item['note']}")
    return 0


LOCK_SERVICE_COVER_VARIANTS = [
    {"palette": "蓝底白字主招牌，白色服务条，侧边深蓝服务牌", "facade": "一开间老小区底商，玻璃双开门，墙面略旧但整洁", "angle": "正面略仰拍，门头和店内展示完整入画", "services": ["开汽车锁", "开保险柜", "配汽车钥匙", "换锁芯"]},
    {"palette": "白底红黑大字招牌，深绿色副服务条", "facade": "老街临街门店，旁边有半开的卷帘门和旧墙面", "angle": "从人行道略侧面拍摄，玻璃门半开", "services": ["开汽车锁", "换指纹锁", "安装智能锁", "配遥控器"]},
    {"palette": "黄底黑字招牌，红色小灯箱和白色玻璃贴字", "facade": "窄门脸锁匠铺，门口有钥匙展示板和小立牌", "angle": "正面中景，稍微保留街边地面和门口杂物", "services": ["开保险柜", "配汽车钥匙", "门锁维修", "配钥匙"]},
    {"palette": "绿色招牌配白色粗字，灰色墙面和蓝色侧边牌", "facade": "居民区楼下普通门面，店内钥匙板密集", "angle": "略低机位正面拍摄，室内柜台可见", "services": ["开汽车锁", "换锁芯", "安装智能锁", "门锁维修"]},
    {"palette": "黑底发光字招牌，暖色店内灯光", "facade": "傍晚街边小店，玻璃门反光真实，门口有工具箱", "angle": "傍晚手机随手拍，门头和入口完整", "services": ["配汽车钥匙", "开保险柜", "换指纹锁", "配遥控器"]},
    {"palette": "红底白字横幅作为其中一种变化，黄色副条克制使用", "facade": "两层招牌门店，上方横幅布招牌，下方灯箱字", "angle": "正面广角，避免复制参考图布局", "services": ["开汽车锁", "开保险柜", "换锁芯", "配钥匙"]},
    {"palette": "灰白灯箱招牌，红色主字，黑色副字", "facade": "双开间锁具店，左侧配钥匙柜台，右侧智能锁展示", "angle": "侧前方拍摄，展示门口和店内纵深", "services": ["安装智能锁", "门锁维修", "配汽车钥匙", "换指纹锁"]},
    {"palette": "橙白招牌，深灰服务立牌，玻璃门白色贴字", "facade": "社区商业街小店，门口停普通电动车", "angle": "稍远距离拍摄，周边街景自然进入画面", "services": ["开汽车锁", "开保险柜", "配遥控器", "换锁芯"]},
    {"palette": "蓝绿拼色招牌，白色大字，侧边图标服务牌", "facade": "老小区底商，瓷砖柱子和空调外机可见", "angle": "竖版正面，店内钥匙板和锁具柜清楚", "services": ["配汽车钥匙", "安装智能锁", "配钥匙", "门锁维修"]},
    {"palette": "白底蓝字招牌，红色重点服务词，门口红色小立牌", "facade": "街边一开间锁匠铺，玻璃柜台摆满锁芯和钥匙壳", "angle": "轻微侧拍，人物不看镜头，真实营业状态", "services": ["开汽车锁", "开保险柜", "配汽车钥匙", "安装智能锁"]},
]


LOCK_SERVICE_DETAIL_VARIANTS = [
    ("上门更换锁芯", "真实中国居民楼入户门口，授权上门换锁芯服务场景，普通防盗门打开，师傅穿日常工作服正在拆装门锁面板和新锁芯，地上有工具箱、螺丝、包装盒，客户在旁边等待，走廊瓷砖墙和鞋柜细节自然，手机实拍质感，竖版9:16，不出现品牌、价格、电话，不展示开锁技巧或强行进入。"),
    ("智能锁安装", "普通小区住宅门口，师傅正在为防盗门安装智能指纹锁，门处于打开状态，能看到新智能锁、螺丝刀、电钻、说明书和配件盒，画面专业可靠但不精致摆拍，真实室内走廊光线，竖版9:16，不出现品牌名，不表现破解、撬锁或绕锁动作。"),
    ("店内配汽车钥匙", "真实街边锁匠店内，玻璃柜台上摆放汽车钥匙外壳、遥控器、电池、钥匙胚和小型检测设备，师傅在柜台前为客户整理汽车钥匙配件，背景有钥匙板和锁芯展示柜，手机实拍风格，画面清楚但不过度商业摄影，不出现汽车品牌标识、价格或电话号码。"),
    ("保险柜锁维修咨询", "家庭或小办公室环境，用户授权的保险柜锁具检查和维修咨询场景，师傅蹲在保险柜前检查锁面和合页，旁边放普通工具箱和服务单，客户在一旁，画面强调专业、谨慎、合法服务，不展示开保险柜方法、工具细节教程或破坏痕迹，真实照片质感，竖版9:16。"),
    ("门锁维修与调试", "老式居民楼门口，师傅正在对已打开的防盗门进行门锁维修和调试，门边能看到旧锁体、新锁芯、螺丝盒和工具包，墙面略旧但环境可信，人物动作自然，手机抓拍感，不要卡通或广告海报效果，不出现价格、电话和品牌，不展示非法进入。"),
    ("店内钥匙与锁具展示", "开锁换锁门店内部详情图，墙上挂满钥匙胚，玻璃柜里陈列锁芯、门锁、智能锁样品、汽车钥匙壳和遥控器，柜台上有工具箱和小票夹，店面真实接地气，灯光普通，竖版9:16，适合作为服务能力展示图，不出现未确认品牌、电话或价格。"),
    ("师傅出发上门服务", "街边开锁换锁店门口，师傅拎着工具箱准备外出上门安装门锁，背景能看到店内钥匙板、锁具柜和醒目的门店招牌，门口有普通电动车或小工具包，真实本地生活服务照片，竖版9:16，不展示开锁动作，不出现价格或品牌，整体可信、自然。"),
    ("门口服务项目展示", "真实锁匠店门口近景，玻璃门和立牌上写着“开锁 换锁 配钥匙”“开汽车锁 开保险柜 配汽车钥匙”“安装智能锁 换锁芯”，旁边展示锁芯、钥匙胚、智能锁样品和工具箱，画面像真实门店随手拍，不固定红黄配色，文字醒目但不要悬浮大字贴满屏，不出现价格和未确认品牌。"),
]


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


@variable_catalog.managed('lock_service','cover',finish_result=False)
def create_lock_service_groups(project_id: str, count: int) -> None:
    if count < 1:
        raise ValueError("group count must be positive")
    definition_path = project_definition_path(project_id)
    definition = load_json(definition_path)
    phones = load_confirmed_project_phones(project_id)
    detail_ref = definition["references"]["detail"]
    if not detail_ref.get("approved_style"):
        detail_ref["status"] = "approved_from_samples"
        detail_ref["approved_style"] = True
    detail_count = int(definition["content_group"]["detail_count"])
    project_dir = definition_path.parent
    prompts_dir = project_dir / "prompts"
    groups_dir = project_dir / "groups"
    cover_records: list[dict[str, Any]] = []
    detail_records: list[dict[str, Any]] = []
    production_records: list[dict[str, Any]] = []
    group_records: list[dict[str, Any]] = []
    for group_index in range(1, count + 1):
        variant = dict(LOCK_SERVICE_COVER_VARIANTS[(group_index - 1) % len(LOCK_SERVICE_COVER_VARIANTS)])
        services = list(variant["services"])
        rng = random.Random(f"{project_id}:{group_index}:services")
        rng.shuffle(services)
        service_text = " ".join(services[:4])
        cover_prompt = lock_prompt_builder.cover_prompt(variant, services, phones)
        cover_prompt, cover_scene = variable_catalog.finish((cover_prompt, variant), {**variable_catalog.CURRENT.get(), "seed":str(group_index)}, "cover")
        cover_sha = prompt_hash(cover_prompt)
        cover_records.append({
            "project_id": project_id, "group_index": group_index, "role": "cover",
            "scene": cover_scene, "phone_bar": True, "phones": phones,
            "prompt": cover_prompt, "prompt_sha256": cover_sha, "variable_catalog":cover_scene["variable_catalog"],
        })
        output_group = Path(definition["output_dir"]) / f"group_{group_index:04d}"
        production_records.append({
            "project_id": project_id, "group_index": group_index, "position": 1, "role": "cover",
            "filename": "01_cover.png", "target": str(output_group / "01_cover.png"),
            "prompt": cover_prompt, "prompt_sha256": cover_sha, "variable_catalog":cover_scene["variable_catalog"],
            "source": None, "expected_text": [phones[0]], "phone_bar_text": phones[0],
        })
        detail_refs = []
        for position in range(1, detail_count + 1):
            detail_index = (group_index - 1) * detail_count + position
            title, base_prompt = LOCK_SERVICE_DETAIL_VARIANTS[(position - 1) % len(LOCK_SERVICE_DETAIL_VARIANTS)]
            detail_prompt = lock_prompt_builder.detail_prompt(base_prompt, group_index, position)
            detail_prompt, detail_scene = variable_catalog.finish((detail_prompt, {}), {**variable_catalog.CURRENT.get(), "seed":f"{group_index}:{position}"}, "detail")
            detail_sha = prompt_hash(detail_prompt)
            detail_records.append({
                "project_id": project_id, "index": detail_index, "group_index": group_index,
                "position": position + 1, "role": "detail", "title": title,
                "prompt": detail_prompt, "prompt_sha256": detail_sha, "variable_catalog":detail_scene["variable_catalog"],
            })
            filename = f"{position + 1:02d}_detail_{detail_index:04d}.png"
            production_records.append({
                "project_id": project_id, "group_index": group_index, "position": position + 1,
                "role": "detail", "detail_index": detail_index, "filename": filename,
                "target": str(output_group / filename), "prompt": detail_prompt,
                "prompt_sha256": detail_sha, "variable_catalog":detail_scene["variable_catalog"], "source": None, "expected_text": [],
            })
            detail_refs.append({"index": detail_index, "position": position + 1, "title": title})
        group_records.append({
            "project_id": project_id, "group_index": group_index,
            "cover": {"group_index": group_index, "position": 1}, "details": detail_refs,
        })
    cover_path = prompts_dir / "cover_prompts.jsonl"
    detail_path = prompts_dir / "detail_prompts.jsonl"
    production_path = groups_dir / "production_manifest.jsonl"
    group_manifest_path = groups_dir / "group_manifest.jsonl"
    write_jsonl(cover_path, cover_records)
    write_jsonl(detail_path, detail_records)
    write_jsonl(production_path, production_records)
    write_jsonl(group_manifest_path, group_records)
    write_json_atomic(groups_dir / "registry.json", {
        "schema_version": 1, "project_id": project_id,
        "group_size": 1 + detail_count, "cover_count": 1, "detail_count": detail_count,
        "created_groups": count, "next_group_index": count + 1,
        "groups": [{"group_index": item["group_index"]} for item in group_records],
    })
    definition["status"] = "active"
    definition["prompt_sources"].update({
        "cover_manifest": str(cover_path.relative_to(ROOT)).replace("\\", "/"),
        "detail_manifest": str(detail_path.relative_to(ROOT)).replace("\\", "/"),
        "production_manifest": str(production_path.relative_to(ROOT)).replace("\\", "/"),
        "detail_prompt_count": len(detail_records),
        "available_complete_detail_sets": count,
    })
    write_json_atomic(definition_path, definition)
    print(
        f"GROUPS_CREATED project={project_id} groups={count} images={len(production_records)} "
        f"cover_prompts={len(cover_records)} detail_prompts={len(detail_records)} api_called=false"
    )


def command_confirm_contact(args: argparse.Namespace) -> int:
    project_definition(args.project_id)
    phones = []
    allow_placeholder = bool(getattr(args, "allow_placeholder", False))
    for raw in args.phone:
        try:
            value = normalize_contact_number(raw, allow_placeholder=allow_placeholder)
        except ValueError as error:
            raise ValueError(
                f"invalid mainland China mobile or 400 service number: {raw}"
            ) from error
        if value not in phones:
            phones.append(value)
    if not args.confirm:
        raise RuntimeError("Contact numbers require explicit user confirmation via --confirm")
    path = RUNTIME_DIR / "projects" / args.project_id / "business.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_id": args.project_id,
        "contact_phones": phones,
        "user_confirmed": True,
        "placeholder_only": bool(phones) and all(
            is_placeholder_contact_number(value) for value in phones
        ),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(f"CONTACT_CONFIRMED project={args.project_id} phone_count={len(phones)} api_called=false")
    print("Numbers are stored only in excluded local .runtime state and are not included in delivery packages.")
    return 0



def uses_category_image_flow(project_id: str) -> bool:
    try:
        definition = project_definition(project_id)
    except Exception:
        return False
    content_group = definition.get("content_group", {})
    return content_group.get("generation_mode") == "independent_triptych_panels"

def command_create_groups(args: argparse.Namespace) -> int:
    definition = project_definition(args.project_id)
    if uses_category_image_flow(args.project_id):
        registry = load_json(ROOT / str(definition["group_registry"]))
        prepared = int(registry.get("created_groups", 0) or 0)
        raise RuntimeError(
            f"{args.project_id} ??? 1??+1???+3????????????? {prepared} ??"
            "? create-groups ??????????? 1+8 ?????????"
            "??? category-image-plan / authorize-category-images / start-category-images?"
        )
    if not definition["references"]["cover"]["approved_style"]:
        raise RuntimeError("COVER_STYLE_APPROVAL_REQUIRED: generate cover samples and obtain explicit user approval first")
    if args.project_id == "road_rescue":
        return run_python("generate_group_prompts.py", "--count", str(args.count))
    if args.project_id == "home_appliance_repair":
        return run_python("generate_home_appliance_groups.py", "--count", str(args.count))
    if args.project_id != "lock_service":
        raise RuntimeError("This project's group generator is not installed yet; finish reference approval first")
    create_lock_service_groups(args.project_id, args.count)
    return 0


def command_restore_category_batch(args: argparse.Namespace) -> int:
    from tools.restore_road_batch import restore
    print(json.dumps(restore(ROOT), ensure_ascii=False, indent=2))
    return 0


def command_import_builtin_images(args: argparse.Namespace) -> int:
    from tools.import_builtin_images import import_images
    print(json.dumps(import_images(sys.modules[__name__], Path(args.receipt)), ensure_ascii=False, indent=2))
    return 0


def command_extend_category_groups(args: argparse.Namespace) -> int:
    if args.category == "ktv":
        from tools.ktv_project import extend_groups

        result = extend_groups(args.count)
    elif args.category == ROAD_PROJECT_ID:
        from generate_road_rescue_v3_groups import extend_v3_5_groups

        result = extend_v3_5_groups(args.count)
    elif args.category == PET_PROJECT_ID:
        from generate_pet_transport_groups import extend_pet_transport_groups

        result = extend_pet_transport_groups(args.count)
    elif args.category == TRUCK_PROJECT_ID:
        from generate_truck_rescue_groups import extend_truck_rescue_groups

        result = extend_truck_rescue_groups(args.count)
    else:
        raise RuntimeError(f"当前不支持追加 {args.category} 的正式组清单")
    print("CATEGORY_GROUPS_EXTENDED api_called=false")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("历史提示词 JSONL 前缀已校验保持不变；本命令未创建许可证、未调用图片 API。")
    return 0


def command_group_plan(args: argparse.Namespace) -> int:
    if uses_category_image_flow(args.project_id):
        raise RuntimeError(
            f"{args.project_id} ?????? group-plan?"
            "??? category-image-plan ?????????? API ????"
        )
    return run_python(
        "group_production.py", "plan", "--project-id", args.project_id,
        "--group-start", str(args.group_start), "--group-count", str(args.group_count)
    )


def command_group_audit(args: argparse.Namespace) -> int:
    return run_python(
        "group_production.py", "audit", "--project-id", args.project_id,
        "--group-start", str(args.group_start), "--group-count", str(args.group_count)
    )


def pipe_legacy_batch_dir(value: str | None = None) -> Path:
    if value:
        return category_image_production.safe_batch_dir(PIPE_PROJECT_ID, value)
    definition = project_definition(PIPE_PROJECT_ID)
    batches = definition.get("prompt_sources", {}).get("legacy_batches", [])
    if not batches or not batches[0].get("batch_dir"):
        raise RuntimeError("管道疏通项目没有登记可接续的旧批次")
    return category_image_production.safe_batch_dir(
        PIPE_PROJECT_ID,
        ROOT / str(batches[0]["batch_dir"]),
    )


def pipe_active_batch_dir(value: str | None = None) -> Path:
    """Resolve the pipe v2 batch and reject attempts to fall back to legacy 1+8 data."""

    definition = project_definition(PIPE_PROJECT_ID)
    active_value = definition.get("prompt_sources", {}).get("active_batch")
    if isinstance(active_value, dict):
        active_value = active_value.get("batch_dir") or active_value.get("path")
    if not isinstance(active_value, str) or not active_value.strip():
        raise RuntimeError("管道疏通正式项目没有登记 active_batch，已停止，避免误用旧的1+8批次")
    active = category_image_production.safe_batch_dir(
        PIPE_PROJECT_ID,
        ROOT / active_value,
    )
    if value:
        requested = category_image_production.safe_batch_dir(PIPE_PROJECT_ID, value)
        if requested.resolve() != active.resolve():
            raise RuntimeError(
                "管道疏通生产入口只允许使用 project.json 登记的 active_batch；"
                "旧的1+8批次只保留作历史，不能再授权或启动"
            )
    return active


def command_sync_project_manifests(args: argparse.Namespace) -> int:
    """Locally attach the preserved pipe batch to the formal project."""
    if args.project_id != PIPE_PROJECT_ID:
        raise RuntimeError("当前只有管道疏通需要执行旧批次接入")
    batch_dir = pipe_legacy_batch_dir(args.batch_dir)
    registry_path = ROOT / "projects" / PIPE_PROJECT_ID / "groups" / "registry.json"
    registry = load_json(registry_path)
    already_imported = any(
        item.get("legacy_batch_id") == batch_dir.name
        for item in registry.get("groups", [])
    )
    if already_imported:
        print(
            f"PROJECT_MANIFESTS_ALREADY_SYNCED project={PIPE_PROJECT_ID} "
            f"groups={registry.get('created_groups', 0)} api_called=false"
        )
        print("旧批次没有被移动或删除；重复执行不会覆盖历史。")
        return 0
    from generate_pipe_unclogging_groups import import_legacy_batch

    result = import_legacy_batch(
        ROOT / "projects" / PIPE_PROJECT_ID,
        batch_dir,
        args.project_group_start,
    )
    print(
        f"PROJECT_MANIFESTS_SYNCED project={PIPE_PROJECT_ID} "
        f"groups={result['group_count']} images={result['image_count']} "
        f"reusable={result['reusable_sources']} api_called=false"
    )
    print("旧批次只被登记为历史来源，没有移动、删除或重新生成图片。")
    return 0


def command_inventory_audit(args: argparse.Namespace) -> int:
    from tools import project_inventory

    snapshot = project_inventory.sync_inventory(
        args.project_id,
        write=True,
        create_contact_sheet=bool(args.refresh_contact_sheet),
    )
    summary = snapshot["summary"]
    print(f"库存检查完成：{summary['message']}")
    print(f"历史永久指纹：{summary['historical_unique_images']} 张")
    print(f"异常组：{summary['unexpected_groups']} 组")
    if summary.get("contact_sheet"):
        print(f"30组首图联系表：{ROOT / summary['contact_sheet']}")
    else:
        print("当前没有已入库且完整的首图，因此未生成联系表。")
    print("本命令只检查本地文件，不生成图片、不调用 API、不收费。")
    return 0


def command_inventory_register(args: argparse.Namespace) -> int:
    if not args.confirm_reviewed:
        raise RuntimeError("请先人工查看整组全部成品；确认后加 --confirm-reviewed 才能登记为可用库存")
    if args.project_id == PIPE_PROJECT_ID:
        _approve_pipe_delivery_range(args.group_start, args.group_count)
    from tools import project_inventory

    result = project_inventory.register_groups(
        args.project_id,
        args.group_start,
        args.group_count,
        allow_near_duplicates=bool(args.confirm_near_duplicates),
    )
    print(
        f"库存登记完成：新登记 {len(result['registered_groups'])} 组；"
        f"重复执行未新增 {len(result['already_registered'])} 组。"
    )
    print(result["summary"]["message"])
    if result.get("near_duplicate_override_used"):
        print("注意：本次包含人工确认过的近似候选，确认记录已永久保留。")
    print("图片仍在原成品目录；本命令不会移动、删除图片，也不会调用 API。")
    return 0


def command_inventory_mark_used(args: argparse.Namespace) -> int:
    from tools import project_inventory

    result = project_inventory.mark_used(args.project_id, args.group_index, args.confirm)
    if result["already_marked"]:
        print(f"第 {args.group_index} 组之前已经标记为已使用，无需重复登记。")
    else:
        print(f"第 {args.group_index} 组已标记为已使用。")
    print("永久视觉指纹已经保留；现在你可以自行删除该组成品图片。")
    print("本命令不会替你删除任何文件，也不会调用 API。")
    return 0


def load_confirmed_project_phones(project_id: str) -> list[str]:
    path = RUNTIME_DIR / "projects" / project_id / "business.json"
    if not path.is_file():
        raise RuntimeError("CONTACT_CONFIRMATION_REQUIRED: confirm telephone numbers first")
    business = load_json(path)
    phones = business.get("contact_phones") or []
    if not business.get("user_confirmed") or not phones:
        raise RuntimeError("CONTACT_CONFIRMATION_REQUIRED: telephone numbers are not confirmed")
    return [str(phone) for phone in phones]


def cover_phone_font(size: int) -> Any:
    from PIL import ImageFont

    font_candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyhbd.ttc",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "simhei.ttf",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf",
    ]
    for path in font_candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


ROAD_RESCUE_SERVICE_GRID = [
    "汽车救援", "搭电救援", "拖车服务", "补胎换胎", "送油救援",
    "困境救援", "地库救援", "车辆救援", "高速救援", "城市路救援",
]


def draw_cover_service_grid(image: Any, items: list[str], group_index: int) -> Any:
    from PIL import Image, ImageDraw

    width, height = image.size
    labels = items[:10]
    if len(labels) != 10:
        return image

    palettes = [
        ((8, 42, 86, 148), (72, 174, 255, 210), (245, 252, 255, 255), (0, 25, 55, 235)),
        ((24, 70, 82, 150), (93, 229, 218, 210), (255, 255, 255, 255), (0, 42, 48, 235)),
        ((48, 42, 92, 148), (153, 135, 255, 210), (255, 252, 245, 255), (28, 18, 62, 235)),
        ((72, 47, 20, 146), (255, 177, 74, 215), (255, 252, 242, 255), (50, 22, 0, 235)),
    ]
    cell_fill, border, text_fill, stroke = palettes[(group_index - 1) % len(palettes)]
    panel_fill = (0, 14, 34, 104)
    margin_x = int(width * 0.04)
    bottom_margin = int(height * 0.035)
    gap = max(5, int(width * 0.008))
    cell_w = (width - margin_x * 2 - gap * 4) // 5
    cell_h = int(height * 0.055)
    grid_h = cell_h * 2 + gap
    y0 = height - bottom_margin - grid_h
    radius = max(6, int(width * 0.012))

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    panel_rect = [
        margin_x - gap,
        y0 - gap,
        width - margin_x + gap,
        y0 + grid_h + gap,
    ]
    draw.rounded_rectangle(panel_rect, radius=radius + 4, fill=panel_fill, outline=(border[0], border[1], border[2], 90), width=max(1, int(width * 0.002)))

    font_size = int(width * 0.035)
    font = cover_phone_font(font_size)
    stroke_width = max(2, int(width * 0.004))
    scratch = ImageDraw.Draw(overlay)
    while font_size > 18:
        fits = True
        for label in labels:
            bbox = scratch.textbbox((0, 0), label, font=font, stroke_width=stroke_width)
            if bbox[2] - bbox[0] > cell_w * 0.82 or bbox[3] - bbox[1] > cell_h * 0.68:
                fits = False
                break
        if fits:
            break
        font_size -= 1
        font = cover_phone_font(font_size)

    for index, label in enumerate(labels):
        row = index // 5
        col = index % 5
        x1 = margin_x + col * (cell_w + gap)
        y1 = y0 + row * (cell_h + gap)
        x2 = x1 + cell_w
        y2 = y1 + cell_h
        alpha_boost = 18 if (index + group_index) % 2 == 0 else 0
        fill = (cell_fill[0], cell_fill[1], cell_fill[2], min(190, cell_fill[3] + alpha_boost))
        draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill, outline=border, width=max(1, int(width * 0.0025)))
        bbox = scratch.textbbox((0, 0), label, font=font, stroke_width=stroke_width)
        tx = x1 + (cell_w - (bbox[2] - bbox[0])) // 2 - bbox[0]
        ty = y1 + (cell_h - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text(
            (tx + 1, ty + 1), label, font=font, fill=(0, 0, 0, 135),
            stroke_width=stroke_width, stroke_fill=(0, 0, 0, 145),
        )
        draw.text((tx, ty), label, font=font, fill=text_fill, stroke_width=stroke_width, stroke_fill=stroke)

    return Image.alpha_composite(image, overlay)


def red_banner_box(image: Any) -> tuple[int, int, int, int] | None:
    width, height = image.size
    pixels = image.convert("RGB").load()
    y_start = int(height * 0.32)
    y_end = int(height * 0.78)
    row_hits: list[tuple[int, int]] = []
    for y in range(y_start, y_end):
        hits = 0
        for x in range(int(width * 0.03), int(width * 0.97), 2):
            r, g, b = pixels[x, y]
            if r > 115 and r > g * 1.35 and r > b * 1.35:
                hits += 1
        if hits > width * 0.025:
            row_hits.append((y, hits))
    if not row_hits:
        return None

    bands: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] = []
    previous_y = -10
    for item in row_hits:
        y, _ = item
        if current and y > previous_y + 2:
            bands.append(current)
            current = []
        current.append(item)
        previous_y = y
    if current:
        bands.append(current)
    bands = [band for band in bands if band[-1][0] - band[0][0] >= height * 0.012]
    if not bands:
        return None

    band = max(bands, key=lambda items: sum(hit for _, hit in items))
    y1 = max(0, band[0][0] - int(height * 0.035))
    y2 = min(height, band[-1][0] + int(height * 0.045))
    xs: list[int] = []
    for y in range(band[0][0], band[-1][0] + 1, 2):
        for x in range(int(width * 0.03), int(width * 0.97), 2):
            r, g, b = pixels[x, y]
            if r > 115 and r > g * 1.35 and r > b * 1.35:
                xs.append(x)
    if xs:
        x1 = max(0, min(xs) - int(width * 0.05))
        x2 = min(width, max(xs) + int(width * 0.05))
    else:
        x1 = int(width * 0.03)
        x2 = int(width * 0.97)
    min_width = int(width * 0.62)
    if x2 - x1 < min_width:
        center = (x1 + x2) // 2
        x1 = max(0, center - min_width // 2)
        x2 = min(width, center + min_width // 2)
    return x1, y1, x2, y2


def draw_cover_phone_bar(
    image_path: Path,
    phone_text: str,
    group_index: int,
    backup_dir: Path,
    remove_red_banner: bool = False,
    service_grid_items: list[str] | None = None,
) -> bool:
    from PIL import Image, ImageDraw

    if not image_path.is_file():
        return False
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"group_{group_index:04d}_01_cover.png"
    if not backup_path.is_file():
        shutil.copy2(image_path, backup_path)
    source_path = backup_path

    image = Image.open(source_path).convert("RGBA")
    width, height = image.size
    text = f"电话{phone_text}"
    if remove_red_banner:
        bright_palette = [
            ((43, 226, 255, 255), (0, 48, 58, 255)),
            ((108, 255, 45, 255), (7, 48, 0, 255)),
            ((255, 235, 52, 255), (58, 42, 0, 255)),
            ((255, 132, 38, 255), (66, 21, 0, 255)),
            ((255, 74, 213, 255), (62, 0, 47, 255)),
            ((180, 112, 255, 255), (31, 0, 70, 255)),
            ((255, 255, 255, 255), (0, 57, 79, 255)),
        ]
        fill, stroke = bright_palette[(group_index - 1) % len(bright_palette)]
        background = (0, 0, 0, 122)
    else:
        palette = [
            ((255, 128, 30, 255), (38, 7, 0, 255), (0, 0, 0, 176)),
            ((112, 255, 48, 255), (6, 38, 0, 255), (0, 0, 0, 174)),
            ((255, 232, 38, 255), (43, 26, 0, 255), (0, 32, 45, 180)),
            ((255, 255, 255, 255), (0, 58, 74, 255), (0, 0, 0, 178)),
            ((60, 240, 255, 255), (0, 37, 54, 255), (13, 31, 67, 178)),
            ((255, 74, 213, 255), (62, 0, 47, 255), (0, 0, 0, 174)),
        ]
        fill, stroke, background = palette[(group_index - 1) % len(palette)]
    existing_box = red_banner_box(image) if remove_red_banner else None

    max_width = int(width * (0.985 if remove_red_banner else 0.97))
    font_size = int(width * (0.155 if remove_red_banner else 0.145))
    font = cover_phone_font(font_size)
    scratch = ImageDraw.Draw(image)
    stroke_width = max(5, int(width * (0.014 if remove_red_banner else 0.011)))
    while font_size > 28:
        bbox = scratch.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        if bbox[2] - bbox[0] <= max_width:
            break
        font_size -= 2
        font = cover_phone_font(font_size)

    bbox = scratch.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (width - text_width) // 2 - bbox[0]
    center_y = ((existing_box[1] + existing_box[3]) // 2) if existing_box else int(height * 0.51)
    y = center_y - text_height // 2 - bbox[1]
    padding_x = int(width * 0.03)
    padding_y = int(height * (0.014 if remove_red_banner else 0.016))
    rect = [
        max(0, x + bbox[0] - padding_x),
        max(0, y + bbox[1] - padding_y),
        min(width, x + bbox[2] + padding_x),
        min(height, y + bbox[3] + padding_y),
    ]
    if remove_red_banner:
        fallback_box = [
            0,
            max(0, center_y - text_height // 2 - padding_y * 2),
            width,
            min(height, center_y + text_height // 2 + padding_y * 3),
        ]
        rect = [
            min(rect[0], fallback_box[0], existing_box[0] if existing_box else fallback_box[0]),
            min(rect[1], fallback_box[1], existing_box[1] if existing_box else fallback_box[1]),
            max(rect[2], fallback_box[2], existing_box[2] if existing_box else fallback_box[2]),
            max(rect[3], fallback_box[3], existing_box[3] if existing_box else fallback_box[3]),
        ]

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if remove_red_banner:
        draw.rectangle(rect, fill=background)
    else:
        radius = max(8, int(width * 0.018))
        draw.rounded_rectangle(rect, radius=radius, fill=background)
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)
    if remove_red_banner:
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        for glow_width, alpha in [
            (stroke_width + max(12, int(width * 0.024)), 72),
            (stroke_width + max(7, int(width * 0.014)), 112),
        ]:
            glow_draw.text(
                (x, y), text, font=font, fill=(fill[0], fill[1], fill[2], alpha),
                stroke_width=glow_width, stroke_fill=(0, 0, 0, alpha),
            )
        image = Image.alpha_composite(image, glow)
        draw = ImageDraw.Draw(image)
        draw.text(
            (x + max(2, int(width * 0.004)), y + max(2, int(height * 0.003))),
            text, font=font, fill=(0, 0, 0, 180),
            stroke_width=stroke_width, stroke_fill=(0, 0, 0, 180),
        )
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke)
    if service_grid_items:
        image = draw_cover_service_grid(image, service_grid_items, group_index)
    image.convert("RGB").save(image_path, quality=96)
    return True


def command_add_cover_phone_bars(args: argparse.Namespace) -> int:
    definition = project_definition(args.project_id)
    phones = load_confirmed_project_phones(args.project_id)
    phone_text = args.phone or phones[0]
    phone_text = normalize_contact_number(phone_text)
    if phone_text not in phones:
        raise ValueError("phone must be one of the confirmed project phone numbers")
    if args.group_count < 1:
        raise ValueError("group count must be positive")
    backup_dir = RUNTIME_DIR / "projects" / args.project_id / "cover_phone_bar_backups"
    output_dir = ROOT / definition.get("output_dir", f"output/{args.project_id}")
    changed = 0
    missing: list[int] = []
    for group_index in range(args.group_start, args.group_start + args.group_count):
        image_path = output_dir / f"group_{group_index:04d}" / "01_cover.png"
        service_grid = ROAD_RESCUE_SERVICE_GRID if args.project_id == "road_rescue" else None
        if draw_cover_phone_bar(image_path, phone_text, group_index, backup_dir, args.remove_red_banner, service_grid):
            changed += 1
        else:
            missing.append(group_index)
    print(
        f"COVER_PHONE_BARS_ADDED project={args.project_id} groups={changed} "
        f"phone={phone_text} backup_dir={backup_dir} api_called=false"
    )
    if missing:
        print(f"MISSING_COVERS groups={','.join(str(item) for item in missing)}")
    return 0


def group_license_path(project_id: str, group_start: int, group_count: int) -> Path:
    return GROUP_LICENSE_DIR / project_id / f"group_{group_start:04d}_{group_count:04d}.json"


def selected_key_slots(args: argparse.Namespace) -> list[int]:
    slots = sorted(set(args.api_key_slot or []))
    if any(slot < 1 for slot in slots):
        raise ValueError("api key slots are 1-based and must be positive")
    if slots:
        key_count = configured_key_count()
        if not key_count:
            raise RuntimeError("No configured API keys")
        if max(slots) > key_count:
            raise ValueError(f"api key slot {max(slots)} is not configured; configured key count is {key_count}")
    return slots


def configured_key_count() -> int:
    import image_generate

    return len(image_generate.configured_api_keys())


def active_group_jobs() -> list[dict[str, Any]]:
    return [job for _, job in active_group_job_entries()]


def group_job_process_alive(job: dict[str, Any]) -> bool:
    """Treat an active status as real only while its launcher or worker exists."""
    import group_production

    lock_path = group_production.range_lock_path(
        str(job.get("project_id") or "road_rescue"),
        int(job.get("group_start", 0) or 0),
        int(job.get("group_count", 0) or 0),
    )
    if lock_path.is_file():
        lock = load_json(lock_path)
        if str(lock.get("job_id") or "") == str(job.get("job_id") or ""):
            return group_production.process_alive(int(lock.get("pid", 0) or 0))
    pid = int(job.get("pid", 0) or 0)
    if pid:
        return group_production.process_alive(pid)
    # The newly written queued job has no PID until Popen returns. Old fixtures
    # without timestamps retain the previous behavior for compatibility.
    return job.get("status") in {"queued", "starting"} or not job.get("created_at")


def active_group_job_entries() -> list[tuple[Path, dict[str, Any]]]:
    if not JOBS_DIR.exists():
        return []
    entries: list[tuple[Path, dict[str, Any]]] = []
    for path in JOBS_DIR.glob("*.json"):
        job = load_json(path)
        if (
            job.get("job_type") == "group-production"
            and job.get("status") in {"queued", "starting", "running", "waiting_for_api"}
            and group_job_process_alive(job)
        ):
            entries.append((path, job))
    return entries


def license_for_job(job: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        group_license_path(str(job.get("project_id", "road_rescue")), int(job.get("group_start", 0)), int(job.get("group_count", 0))),
        GROUP_LICENSE_PATH,
    ]
    for path in candidates:
        if not path.is_file():
            continue
        license_data = load_json(path)
        if (
            license_data.get("project_id") == job.get("project_id")
            and license_data.get("group_start") == job.get("group_start")
            and license_data.get("group_count") == job.get("group_count")
        ):
            return license_data
    return None


def active_api_key_slots() -> set[int]:
    active: set[int] = set()
    for job in active_group_jobs():
        slots = job.get("api_key_slots") or []
        if not slots:
            license_data = license_for_job(job) or {}
            slots = license_data.get("api_key_slots") or []
        if slots:
            active.update(int(slot) for slot in slots)
        else:
            active.add(1)
    return active


def split_slots_evenly(slots: list[int], bucket_ids: list[str]) -> dict[str, list[int]]:
    buckets = list(dict.fromkeys(bucket_ids))
    if not buckets:
        return {}
    result: dict[str, list[int]] = {bucket: [] for bucket in buckets}
    base, extra = divmod(len(slots), len(buckets))
    cursor = 0
    for index, bucket in enumerate(buckets):
        size = base + (1 if index < extra else 0)
        result[bucket] = slots[cursor: cursor + size]
        cursor += size
    return result


def rebalance_active_api_key_slots() -> dict[str, list[int]]:
    key_count = configured_key_count()
    if key_count <= 0:
        raise RuntimeError("No configured API keys")
    import group_production

    config = effective_api_config(load_json(ROOT / "config.json"))
    quarantined_slots = group_production.quarantined_api_key_slots(config)
    entries = active_group_job_entries()
    if not entries:
        return {}
    all_slots = [slot for slot in range(1, key_count + 1) if slot not in quarantined_slots]
    fixed_slots: set[int] = set()
    fixed_owners: dict[int, str] = {}
    fair_entries: list[tuple[Path, dict[str, Any]]] = []
    for path, job in entries:
        policy = job.get("api_key_policy") or ("fixed" if job.get("api_key_slots") else "fair-share")
        if policy == "fair-share":
            fair_entries.append((path, job))
            continue
        for slot in [int(item) for item in job.get("api_key_slots") or [1]]:
            if slot < 1 or slot > key_count:
                raise RuntimeError(f"Fixed API key slot {slot} is not configured")
            if slot in fixed_owners:
                raise RuntimeError(
                    f"API key slot {slot} is fixed for both {fixed_owners[slot]} and {job['job_id']}"
                )
            fixed_owners[slot] = str(job["job_id"])
            fixed_slots.add(slot)
    available = [slot for slot in all_slots if slot not in fixed_slots]
    if not fair_entries:
        return {job["job_id"]: [int(slot) for slot in job.get("api_key_slots") or [1]] for _, job in entries}
    projects: list[str] = []
    for _, job in fair_entries:
        project_id = str(job.get("project_id") or "road_rescue")
        if project_id not in projects:
            projects.append(project_id)
    if len(available) < len(projects):
        raise RuntimeError(
            f"Not enough unreserved API keys for fair-share jobs: projects={len(projects)} keys={len(available)}"
        )
    project_slots = split_slots_evenly(available, projects)
    assignments: dict[str, list[int]] = {}
    for project_id, slots in project_slots.items():
        project_jobs = [(path, job) for path, job in fair_entries if str(job.get("project_id") or "road_rescue") == project_id]
        job_ids = [str(job["job_id"]) for _, job in project_jobs]
        per_job = split_slots_evenly(slots, job_ids)
        for path, job in project_jobs:
            job_id = str(job["job_id"])
            assigned = per_job[job_id]
            if not assigned:
                raise RuntimeError(f"No API key slot available for job {job_id}")
            job["api_key_policy"] = "fair-share"
            job["api_key_slots"] = assigned
            job["api_key_assignment_updated_at"] = datetime.now(timezone.utc).isoformat()
            write_json_atomic(path, job)
            assignments[job_id] = assigned
    for _, job in entries:
        assignments.setdefault(str(job["job_id"]), [int(slot) for slot in job.get("api_key_slots") or [1]])
    return assignments


def auto_key_slots(args: argparse.Namespace) -> list[int]:
    explicit = selected_key_slots(args)
    if explicit:
        return explicit
    key_count = configured_key_count()
    if key_count <= 1:
        return []
    import group_production

    config = effective_api_config(load_json(ROOT / "config.json"))
    quarantined_slots = group_production.quarantined_api_key_slots(config)
    available = [
        slot for slot in range(1, key_count + 1)
        if slot not in active_api_key_slots() and slot not in quarantined_slots
    ]
    if not available:
        raise RuntimeError("All configured API keys are already assigned to active group tasks")
    return available


def command_authorize_groups(args: argparse.Namespace) -> int:
    if args.project_id == PIPE_PROJECT_ID:
        raise RuntimeError(
            "管道疏通必须先走3组样板安全入口；请先运行 category-image-plan，"
            "不要使用通用 authorize-groups。"
        )
    if not args.confirm_paid:
        raise RuntimeError("Group authorization requires explicit --confirm-paid")
    import group_production

    run_plan = group_production.plan(args.group_start, args.group_count, args.project_id)
    pending = int(run_plan["pending_api_images"])
    if args.max_requests < pending:
        raise ValueError(f"max requests {args.max_requests} is below pending images {pending}")
    if args.max_requests > pending * args.max_attempts:
        raise ValueError("max requests exceeds pending images × max attempts")
    config = effective_api_config(load_json(ROOT / "config.json"))
    api_key_slots = selected_key_slots(args)
    api_key_policy = "fixed" if api_key_slots else "fair-share"
    payload = {
        "version": 1, "kind": "group-production", "license_id": secrets.token_hex(12), "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(), "project_id": args.project_id,
        "group_start": args.group_start, "group_count": args.group_count,
        "approved_image_count": pending, "approved_request_budget": args.max_requests,
        "max_attempts": args.max_attempts, "manifest_sha256": run_plan["manifest_sha256"],
        "provider": config["provider"], "base_url": config.get("base_url", ""), "model": config["model"],
        "quality": config["quality"], "size": config["api_size"], "one_time": True,
        "api_key_policy": api_key_policy,
    }
    if api_key_slots:
        payload["api_key_slots"] = api_key_slots
    license_path = group_license_path(args.project_id, args.group_start, args.group_count)
    write_json_atomic(license_path, payload)
    print(
        f"GROUP_LICENSE_READY id={payload['license_id']} groups={args.group_count} "
        f"pending_images={pending} request_budget={args.max_requests} "
        f"api_key_policy={api_key_policy} api_key_slots={api_key_slots or 'fair-share'} api_called=false"
    )
    return 0


def _dashboard_relative_path(value: str | Path) -> str:
    resolved = Path(value).resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as error:
        raise RuntimeError(f"看板文件必须位于项目目录内：{resolved}") from error


def _archive_dashboard_session_snapshot() -> Path | None:
    if not DASHBOARD_SESSION_PATH.is_file():
        return None
    current = load_json(DASHBOARD_SESSION_PATH)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    job_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(current.get("job_id") or "waiting"))
    DASHBOARD_SESSION_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    target = DASHBOARD_SESSION_ARCHIVE_DIR / f"{timestamp}_{job_id}.json"
    shutil.copy2(DASHBOARD_SESSION_PATH, target)
    return target


def _dashboard_target_descriptors(records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []
    output_root = (ROOT / "output").resolve()
    for record in records or []:
        target = Path(str(record.get("target") or "")).resolve()
        if output_root not in target.parents:
            raise RuntimeError(f"看板目标不在正式 output 目录内：{target}")
        descriptors.append({
            "path": _dashboard_relative_path(target),
            "group_index": int(record.get("group_index") or 0),
            "position": int(record.get("delivery_position") or record.get("position") or 0),
            "role": str(record.get("delivery_kind") or record.get("role") or "detail"),
        })
    return descriptors


def activate_dashboard_session(
    job_path: Path,
    job: dict[str, Any],
    *,
    target_records: list[dict[str, Any]] | None = None,
) -> None:
    _archive_dashboard_session_snapshot()
    descriptors = _dashboard_target_descriptors(target_records)
    group_indices = sorted(
        {
            int(item["group_index"])
            for item in descriptors
            if int(item.get("group_index", 0)) > 0
        }
    )
    if not group_indices:
        group_start = int(job.get("group_start", 0) or 0)
        group_count = int(job.get("group_count", 0) or 0)
        if group_start > 0 and group_count > 0:
            group_indices = list(range(group_start, group_start + group_count))
    if group_indices:
        expected_image_count = (
            5 if job.get("job_type") in {"category-batch-production", "builtin-image-production"} else 9
        )
        if str(job.get("project_id") or job.get("category_id")) == "ktv":
            expected_image_count = 3
        dashboard_delivery.register_pending_groups(
            DASHBOARD_DELIVERY_STATE_PATH,
            str(job.get("project_id") or job.get("category_id") or "unassigned"),
            group_indices,
            expected_image_count=expected_image_count,
            job_id=str(job["job_id"]),
        )
    payload = {
        "schema_version": 1,
        "mode": "job",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": str(job["job_id"]),
        "job_file": _dashboard_relative_path(job_path),
        "project_id": str(job.get("project_id") or job.get("category_id") or "unassigned"),
        "batch_id": job.get("batch_id"),
        "scope": job.get("scope"),
        "group_start": job.get("group_start"),
        "group_count": job.get("group_count"),
        "expected_targets": descriptors,
    }
    write_json_atomic(DASHBOARD_SESSION_PATH, payload)


def archive_dashboard_session(reason: str) -> Path | None:
    archived = _archive_dashboard_session_snapshot()
    write_json_atomic(DASHBOARD_SESSION_PATH, {
        "schema_version": 1,
        "mode": "waiting",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": None,
        "job_file": None,
        "project_id": ROAD_PROJECT_ID,
        "reason": reason,
        "expected_targets": [],
    })
    return archived


def command_dashboard_archive(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise RuntimeError("归档当前看板会话需要 --confirm；该操作不会删除或移动正式成品")
    archived = archive_dashboard_session("用户归档旧展示，等待下一次工作")
    print("DASHBOARD_SESSION_ARCHIVED api_called=false")
    print(f"旧会话记录：{archived if archived else '没有旧会话记录'}")
    print("正式图片仍保留在 output/；任务监控会话已归档，未打包组仍继续显示。")
    return 0


def command_package_category_groups(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise RuntimeError("压缩并从看板归档对应组需要 --confirm")
    destination = Path(args.destination).expanduser() if args.destination else None
    result = dashboard_delivery.package_pending_groups(
        ROOT,
        DASHBOARD_DELIVERY_STATE_PATH,
        args.category,
        args.group_start,
        args.group_count,
        destination,
        max_archive_bytes=args.max_archive_bytes,
        manifest_dir=RUNTIME_DIR / "package_manifests",
    )
    print(
        f"CATEGORY_GROUPS_PACKAGED project={args.category} "
        f"groups={args.group_count} archives={len(result['archives'])} api_called=false"
    )
    for archive in result["archives"]:
        print(f"- {archive['path']}；{archive['size']} bytes")
    print(f"打包清单：{result['manifest_path']}")
    print("以上组已从本地看板待交付列表移除；output 原图未删除。")
    return 0


def launch_dashboard_compact() -> bool:
    if not DASHBOARD_EXE.is_file() or os.name != "nt":
        return False
    dashboard_env = dict(os.environ)
    dashboard_env["ROAD_RESCUE_FACTORY_HOME"] = str(ROOT)
    dashboard_env["ROAD_RESCUE_DASHBOARD_COMPACT"] = "1"
    subprocess.Popen(
        [str(DASHBOARD_EXE), "--compact"], cwd=ROOT, env=dashboard_env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )
    return True


def hidden_independent_worker_flags() -> int:
    """Windows flags for a worker that has no console and outlives its launcher."""
    if os.name != "nt":
        return 0
    return (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NO_WINDOW
        | subprocess.CREATE_BREAKAWAY_FROM_JOB
    )


def _independent_python_executable() -> str:
    """Use the real Windows interpreter, not a short-lived venv redirector."""

    if os.name == "nt":
        candidate = str(getattr(sys, "_base_executable", "") or "").strip()
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return sys.executable


def _independent_python_environment(env: dict[str, str]) -> dict[str, str]:
    """Keep the current venv packages importable under the real interpreter."""

    result = dict(env)
    if Path(_independent_python_executable()).resolve() == Path(sys.executable).resolve():
        return result
    import sysconfig

    venv_paths: list[str] = []
    for key in ("purelib", "platlib"):
        value = str(sysconfig.get_path(key) or "").strip()
        if value and Path(value).is_dir() and value not in venv_paths:
            venv_paths.append(value)
    existing = str(result.get("PYTHONPATH") or "").strip()
    if existing:
        venv_paths.append(existing)
    if not venv_paths:
        raise RuntimeError("真实 Python 解释器缺少当前虚拟环境的 site-packages 路径")
    result["PYTHONPATH"] = os.pathsep.join(venv_paths)
    result["VIRTUAL_ENV"] = sys.prefix
    return result


def command_start_groups(args: argparse.Namespace) -> int:
    if args.project_id == PIPE_PROJECT_ID:
        raise RuntimeError(
            "管道疏通必须使用带范围和一次性许可证编号的 start-category-images，"
            "不能使用通用 start-groups。"
        )
    license_path = group_license_path(args.project_id, args.group_start, args.group_count)
    if not license_path.is_file():
        license_path = GROUP_LICENSE_PATH
    if not license_path.is_file() or load_json(license_path).get("status") != "active":
        raise RuntimeError("No active group license; authorize the exact group range and request budget first")
    license_data = load_json(license_path)
    if args.group_start != license_data["group_start"] or args.group_count != license_data["group_count"]:
        raise RuntimeError("requested group range does not match active license")
    if args.project_id != license_data.get("project_id"):
        raise RuntimeError("requested project does not match active license")
    max_failures = args.max_failures
    if max_failures is None:
        # Long relay batches often see transient connection failures. Keep going
        # within the already-approved request budget instead of stopping after
        # the first failed image.
        max_failures = max(1, int(license_data.get("approved_image_count", 1)))
    explicit_slots = selected_key_slots(args)
    license_slots = license_data.get("api_key_slots", [])
    api_key_policy = "fixed" if explicit_slots or license_slots else license_data.get("api_key_policy", "fair-share")
    api_key_slots = explicit_slots or license_slots or []
    if license_slots and api_key_slots != license_slots:
        raise RuntimeError("requested api key slots do not match active license")
    job_id = datetime.now(timezone.utc).strftime("group-%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_path = JOBS_DIR / f"{job_id}.json"
    log_path = JOBS_DIR / f"{job_id}.log"
    now = datetime.now(timezone.utc).isoformat()
    write_json_atomic(job_path, {
        "job_id": job_id, "job_type": "group-production", "project_id": args.project_id, "status": "queued",
        "group_start": args.group_start, "group_count": args.group_count,
        "requested_count": args.group_count * 9, "completed": 0, "failed": 0,
        "api_key_policy": api_key_policy, "api_key_slots": api_key_slots,
        "created_at": now, "updated_at": now, "log_file": str(log_path),
    })
    try:
        assignments = rebalance_active_api_key_slots()
        api_key_slots = assignments.get(job_id, api_key_slots)
    except Exception:
        if job_path.exists():
            job_path.unlink()
        raise
    activate_dashboard_session(job_path, load_json(job_path))
    command = [
        sys.executable, str(ROOT / "group_production.py"), "run",
        "--project-id", args.project_id, "--group-start", str(args.group_start), "--group-count", str(args.group_count),
        "--license", str(license_path), "--job-file", str(job_path),
        "--max-attempts", str(license_data["max_attempts"]), "--max-failures", str(max_failures),
    ]
    for slot in api_key_slots:
        command.extend(["--api-key-slot", str(slot)])
    popen_kwargs: dict[str, Any] = {"cwd": ROOT, "close_fds": True}
    if os.name == "nt":
        popen_kwargs["creationflags"] = hidden_independent_worker_flags()
    else:
        popen_kwargs["start_new_session"] = True
    with log_path.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, **popen_kwargs)
    job = load_json(job_path)
    job.update({
        "pid": process.pid,
        "status": "starting",
        "launch_mode": "hidden-independent" if os.name == "nt" else "detached-session",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    write_json_atomic(job_path, job)
    dashboard = launch_dashboard_compact()
    print(
        f"GROUP_JOB_STARTED id={job_id} pid={process.pid} dashboard={dashboard} "
        f"api_key_policy={api_key_policy} api_key_slots={api_key_slots or 'fair-share'} api_may_be_called=true"
    )
    print(f"Progress: python factory.py job-status {job_id}")
    return 0


def group_cover_expectations(group_index: int) -> tuple[Path, list[str]]:
    path = ROOT / "projects" / "road_rescue" / "prompts" / "cover_prompts.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    cover = next((item for item in records if item["group_index"] == group_index), None)
    if not cover:
        raise ValueError(f"cover prompt not found for group {group_index}")
    image = ROOT / "output" / "road_rescue" / f"group_{group_index:04d}" / "01_cover.png"
    expected = [
        cover["scene"]["store_name"], *cover["scene"]["phones"],
        *[item.strip() for item in re.split(r"[·|]", cover["scene"]["business_lines"]) if item.strip()],
    ]
    return image, expected


def command_validate_cover(args: argparse.Namespace) -> int:
    image, expected = group_cover_expectations(args.group_index)
    command = ["--image", str(image)]
    for item in expected:
        command.extend(["--expected", item])
    return run_python("tools/validate_cover_text.py", *command)


def command_approve_cover_manual(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise RuntimeError("manual cover approval requires --confirm")
    image, expected = group_cover_expectations(args.group_index)
    command = ["--image", str(image), "--manual-approve", "--confirm", "--note", args.note]
    for item in expected:
        command.extend(["--expected", item])
    return run_python("tools/validate_cover_text.py", *command)


def command_prepare_cover_samples(args: argparse.Namespace) -> int:
    if args.project_id != "road_rescue":
        raise RuntimeError("This project's cover-sample generator is not installed yet")
    if args.count < 1 or args.count > 3:
        raise ValueError("cover sample count must be between 1 and 3")
    command = ["--count", str(args.count), "--sample", "--random"]
    if args.era_profile:
        command.extend(["--era-profile", args.era_profile])
    return run_python("generate_group_prompts.py", *command)


def command_providers(_: argparse.Namespace) -> int:
    registry = load_provider_registry()
    current = current_provider_id(registry)
    print("SUPPORTED_IMAGE_PROVIDERS")
    for provider in registry["providers"]:
        marker = " current=true" if provider["id"] == current else ""
        print(f"\n{provider['name']} [{provider_status_label(provider['status'])}]{marker}")
        print(f"  ID: {provider['id']}")
        print(f"  模型: {', '.join(provider['image_models'])}")
        print(f"  已确认: {'；'.join(provider['verified_features'])}")
        if provider["known_limitations"]:
            print(f"  限制: {'；'.join(provider['known_limitations'])}")
        print(f"  最后核对: {provider['last_verified']}（{provider['verification_method']}）")
        print(f"  详情: python factory.py provider-info {provider['id']}")
    print("\n说明：已登记不等于平台背书；第三方服务的Key、提示词和图片由其运营方处理。")
    return 0


def command_provider_info(args: argparse.Namespace) -> int:
    registry = load_provider_registry()
    provider = next((item for item in registry["providers"] if item["id"] == args.provider_id), None)
    if provider is None:
        raise ValueError(f"unknown provider: {args.provider_id}")
    print(f"{provider['name']} [{provider_status_label(provider['status'])}]")
    print(f"官网: {provider['website']}")
    print(f"文档: {provider['docs_url']}")
    print(f"Base URL: {provider['base_url']}")
    print(f"图片模型: {', '.join(provider['image_models'])}")
    print(f"认证: {provider['authentication']}")
    print(f"说明文件: {ROOT / provider['details_file']}")
    return 0


def command_status(_: argparse.Namespace) -> int:
    return run_python("tools/status.py")


def command_setup_api(args: argparse.Namespace) -> int:
    import importlib.util
    import os

    env_path = ensure_env_file()
    load_project_env(env_path)
    provider = os.environ.get("OPENAI_PROVIDER", "official") or "official"
    sdk_ready = importlib.util.find_spec("openai") is not None
    import image_generate

    key_count = len(image_generate.configured_api_keys())
    key_ready = key_count > 0
    print("API_SETUP_STATUS")
    print(f"OpenAI Python SDK: {'ready' if sdk_ready else 'missing'}")
    print(f"Project .env key: {'configured' if key_ready else 'missing'} (value is never displayed)")
    print(f"Configured key count: {key_count}")
    print(f"Provider: {provider}")
    if sdk_ready and key_ready:
        print("API environment is ready. No API request was made by this check.")
        print("Next recommended step: authorize and generate only 3 paid sample images.")
        return 0
    if args.check:
        print("Setup is incomplete. Run `python factory.py setup-api` for guided instructions.")
        return 1

    if provider == "relay":
        docs_url = os.environ.get("OPENAI_PROVIDER_DOCS_URL", "")
        print(
            f"""

中转站Key配置：
1. 当前中转站文档：{docs_url or '未配置'}
2. 请从该中转站自己的控制台创建Key，不要使用或泄露其他平台的Key。
3. 打开项目内这个文件：{env_path}
4. 找到 OPENAI_API_KEY=，把中转站Key粘贴到等号后面并保存。
5. 如需第二个账号并发，把第二个Key粘贴到 OPENAI_API_KEY_2= 后面。
6. Key、提示词和图片会发送给中转站运营方，请先确认其条款和数据政策。
""".rstrip()
        )
    else:
        print(
            """

安全配置步骤：
1. 打开官方密钥页面并登录：https://platform.openai.com/api-keys
2. 创建一个仅用于本项目的Project API Key。不要把Key发到聊天中。
3. 建议先在平台设置用量/预算提醒：https://platform.openai.com/settings/organization/limits
4. 打开项目内这个文件：{env_path}
5. 找到 OPENAI_API_KEY=，把Key粘贴到等号后面并保存。不要加中文说明。
6. 如需第二个账号并发，把第二个Key粘贴到 OPENAI_API_KEY_2= 后面。
7. .env是本机私密文件，已被Git和交付打包器排除；不要截图、分享或上传。
""".rstrip()
            .format(env_path=env_path)
        )
    if not sdk_ready:
        print("用户确认安装后运行：python -m pip install -r requirements.txt")
    else:
        print("OpenAI Python SDK已经安装，无需重复安装。")
    print("保存.env后直接运行：python factory.py setup-api --check（无需重启）")
    print("检查通过后仍不会自动出图；必须再次确认准确付费张数并创建一次性许可证。")
    return 0


def command_setup_relay(_: argparse.Namespace) -> int:
    ensure_env_file()
    print(
        """
中转站接入向导：
1. 请把中转站官网或公开文档网址发给Codex；不要发送Key。
2. Codex会阅读公开文档，确认是否兼容OpenAI Python SDK、/v1/images/generations和base64图片返回。
3. Codex会先展示提取到的Base URL、图片模型、认证方式和限制。
4. 只有你确认信任该第三方后，Codex才会写入非敏感配置。
5. 然后你亲自打开项目.env，把中转站Key填在OPENAI_API_KEY=后面。

注意：Key、提示词和生成内容会发送给中转站运营方，受其条款和数据政策约束。
""".strip()
    )
    return 0


def command_configure_relay(args: argparse.Namespace) -> int:
    if not args.confirm_third_party:
        raise RuntimeError("Relay configuration requires --confirm-third-party after the user accepts the risk")
    base_url = validate_public_https_url(args.base_url, "base URL")
    docs_url = validate_public_https_url(args.docs_url, "docs URL")
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", args.model):
        raise ValueError("model contains unsupported characters")
    env_path = ensure_env_file()
    write_env_values(
        {
            "OPENAI_PROVIDER": "relay",
            "OPENAI_BASE_URL": base_url,
            "OPENAI_IMAGE_MODEL": args.model,
            "OPENAI_PROVIDER_DOCS_URL": docs_url,
        },
        env_path,
    )
    print("RELAY_CONFIGURED api_called=false")
    print(f"Base URL: {base_url}")
    print(f"Image model: {args.model}")
    print(f"Docs: {docs_url}")
    print(f"Now open {env_path} and fill OPENAI_API_KEY yourself. The key was not requested or displayed.")
    return 0


def command_reset_provider(_: argparse.Namespace) -> int:
    env_path = ensure_env_file()
    write_env_values(
        {
            "OPENAI_PROVIDER": "official",
            "OPENAI_BASE_URL": "",
            "OPENAI_IMAGE_MODEL": "",
            "OPENAI_PROVIDER_DOCS_URL": "",
        },
        env_path,
    )
    print("PROVIDER_RESET provider=official api_called=false key_unchanged=true")
    return 0


def command_test_relay(args: argparse.Namespace) -> int:
    import importlib.util
    import os

    if not args.confirm_network:
        raise RuntimeError("Relay test sends the configured key to a third party; use --confirm-network after user approval")
    config = effective_api_config(load_json(ROOT / "config.json"))
    if config["provider"] != "relay" or not config["base_url"]:
        raise RuntimeError("No relay is configured")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Relay key is missing from project .env")
    if importlib.util.find_spec("openai") is None:
        raise RuntimeError("OpenAI Python SDK is missing. Install requirements.txt after user approval")
    from openai import OpenAI

    client = OpenAI(base_url=config["base_url"], max_retries=0, timeout=30)
    try:
        models = client.models.list()
    except Exception as error:
        print("RELAY_CONNECTION_FAILED network_called=true image_api_called=false")
        print(f"error_type={type(error).__name__}; http_status={getattr(error, 'status_code', None)}")
        return 2
    model_ids = {item.id for item in models.data}
    print("RELAY_CONNECTION_OK network_called=true image_api_called=false")
    print(f"Models returned: {len(model_ids)}")
    selected_model = getattr(args, "model", None) or config["model"]
    print(f"Checked image model: {selected_model}; listed: {selected_model in model_ids}")
    return 0 if selected_model in model_ids else 2


def command_audit(_: argparse.Namespace) -> int:
    return run_python("tools/audit_prompts.py")


def command_plan(_: argparse.Namespace) -> int:
    return run_python("image_generate.py")


def command_new_batch(args: argparse.Namespace) -> int:
    if run_python("tools/audit_prompts.py") != 0:
        return 1
    code = run_python("generate_prompts.py", "--new-batch", "--count", str(args.count))
    if code != 0:
        return code
    return run_python("tools/audit_prompts.py")


def style_suffix() -> str:
    parts: list[str] = []
    for relative in ["preferences/STYLE_PROFILE.md", "preferences/REJECTED_PATTERNS.md"]:
        path = ROOT / relative
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
    if not parts:
        return ""
    return "\n\n以下是用户根据历史样片确认的项目风格要求，优先遵守：\n" + "\n".join(parts)


def command_preview(args: argparse.Namespace) -> int:
    import random

    config = load_json(ROOT / "config.json")
    prompt_path = ROOT / config["prompt_file"]
    records = [json.loads(line) for line in prompt_path.read_text(encoding="utf-8").splitlines() if line]
    if args.count < 1 or args.count > min(10, len(records)):
        raise ValueError("preview count must be between 1 and 10")
    chosen = random.SystemRandom().sample(records, args.count)
    suffix = style_suffix()
    payload = []
    for record in chosen:
        item = dict(record)
        item["effective_prompt"] = record["prompt"] + suffix
        payload.append(item)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PREVIEW_READY count={len(payload)} api_called=false file={PREVIEW_PATH}")
    for item in payload:
        print(f"#{item['index']:04d} {item['scene']['rescue_job']} | {item['scene']['location']} | {item['scene']['weather']}")
    print("If the host has image generation, Codex may generate these previews from effective_prompt.")
    return 0


def command_feedback(args: argparse.Namespace) -> int:
    if args.index < 1:
        raise ValueError("index must be positive")
    payload = {
        "index": args.index,
        "rating": args.rating,
        "note": args.note.strip(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    path = ROOT / "preferences" / "sample_reviews.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(f"FEEDBACK_RECORDED index={args.index} rating={args.rating} api_called=false")
    print("Codex should now update STYLE_PROFILE.md or REJECTED_PATTERNS.md when the feedback is reusable.")
    return 0


def command_authorize(args: argparse.Namespace) -> int:
    if not args.confirm_paid:
        raise RuntimeError("Paid authorization requires --confirm-paid attesting the explicit production instruction; no second user confirmation")
    if args.count < 1 or args.count > 1000:
        raise ValueError("authorized count must be between 1 and 1000")
    if (args.start is None) != (args.end is None):
        raise ValueError("--start and --end must be supplied together")
    if args.start is not None and (args.start < 1 or args.end < args.start):
        raise ValueError("invalid authorized range")
    if args.start is not None and args.count > args.end - args.start + 1:
        raise ValueError("authorized count exceeds the authorized range")
    config = effective_api_config(load_json(ROOT / "config.json"))
    license_data = {
        "version": 1,
        "license_id": secrets.token_hex(12),
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "approved_count": args.count,
        "approved_model": config["model"],
        "approved_quality": config["quality"],
        "approved_size": config["api_size"],
        "approved_base_url": config.get("base_url", ""),
        "approved_provider": config.get("provider", "official"),
        "start_index": args.start,
        "end_index": args.end,
        "one_time": True,
    }
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    temporary = LICENSE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(license_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(LICENSE_PATH)
    print(
        f"LICENSE_READY id={license_data['license_id']} count={args.count} model={config['model']} "
        f"quality={config['quality']} one_time=true api_called=false"
    )
    print("This license permits at most one run and is excluded from delivery packages.")
    return 0



def command_run(args: argparse.Namespace) -> int:
    if not LICENSE_PATH.exists():
        raise RuntimeError("No active execution license. Explicitly confirm paid generation, then run factory.py authorize")
    command = ["--execute", "--license", str(LICENSE_PATH), "--limit", str(args.count)]
    if args.start is not None:
        command.extend(["--start", str(args.start)])
    if args.end is not None:
        command.extend(["--end", str(args.end)])
    return run_python("image_generate.py", *command)


def command_start(args: argparse.Namespace) -> int:
    """Launch generation independently from the current chat or terminal."""
    if args.count < 1:
        raise ValueError("count must be positive")
    if not LICENSE_PATH.exists():
        raise RuntimeError("No active execution license. Explicitly confirm paid generation, then run factory.py authorize")
    license_data = load_json(LICENSE_PATH)
    if license_data.get("status") != "active":
        raise RuntimeError("Execution license is not active; create a new exact-count license after explicit confirmation")
    job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_path = JOBS_DIR / f"{job_id}.json"
    log_path = JOBS_DIR / f"{job_id}.log"
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "job_id": job_id, "status": "queued", "requested_count": args.count,
        "completed": 0, "failed": 0, "current_index": None,
        "created_at": now, "updated_at": now,
        "output_dir": str(ROOT / "output"), "log_file": str(log_path),
    }
    job_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    activate_dashboard_session(job_path, payload)
    command = [sys.executable, str(ROOT / "image_generate.py"), "--execute", "--license", str(LICENSE_PATH),
               "--limit", str(args.count), "--job-file", str(job_path)]
    if args.start is not None:
        command.extend(["--start", str(args.start)])
    if args.end is not None:
        command.extend(["--end", str(args.end)])
    popen_kwargs: dict[str, Any] = {"cwd": ROOT, "close_fds": True}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True
    with log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(command, stdout=log_handle, stderr=subprocess.STDOUT, **popen_kwargs)
    payload = load_json(job_path)
    payload["pid"] = process.pid
    if payload.get("status") == "queued":
        payload["status"] = "starting"
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    job_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dashboard_started = False
    if DASHBOARD_EXE.is_file() and os.name == "nt":
        dashboard_env = dict(os.environ)
        dashboard_env["ROAD_RESCUE_FACTORY_HOME"] = str(ROOT)
        dashboard_env["ROAD_RESCUE_DASHBOARD_COMPACT"] = "1"
        subprocess.Popen(
            [str(DASHBOARD_EXE), "--compact"],
            cwd=ROOT,
            env=dashboard_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        )
        dashboard_started = True
    print(f"BACKGROUND_JOB_STARTED id={job_id} pid={process.pid} api_may_be_called=true")
    print(f"Progress: python factory.py job-status {job_id}")
    print(f"Images will be saved to: {ROOT / 'output'}")
    print(f"Dashboard: {'started in compact mode' if dashboard_started else 'not available'}")
    return 0


def command_job_status(args: argparse.Namespace) -> int:
    if not JOBS_DIR.exists():
        print("NO_BACKGROUND_JOBS")
        return 0
    paths = sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if args.job_id:
        paths = [JOBS_DIR / f"{args.job_id}.json"]
    if not paths or not paths[0].is_file():
        raise ValueError("job not found")
    if not args.job_id:
        jobs = [load_json(path) for path in paths if path.is_file()]
        active = [job for job in jobs if job.get("status") in {"queued", "starting", "running", "waiting_for_api"}]
        if active:
            completed = sum(int(job.get("completed", 0) or 0) for job in active)
            failed = sum(int(job.get("failed", 0) or 0) for job in active)
            requested = sum(int(job.get("requested_count", 0) or 0) for job in active)
            print(f"MERGED_ACTIVE jobs={len(active)} completed={completed} failed={failed} requested={requested}")
    for path in paths[: args.limit]:
        job = load_json(path)
        print(f"JOB id={job['job_id']} status={job['status']} completed={job.get('completed', 0)} "
              f"failed={job.get('failed', 0)} requested={job.get('requested_count')} "
              f"current={job.get('current_index')} updated={job.get('updated_at')}")
        if job.get("last_error"):
            print(f"  last_error={job['last_error']}")
        if job.get("last_saved"):
            print(f"  last_saved={job['last_saved']}")
    return 0


def command_package(_: argparse.Namespace) -> int:
    return run_python("tools/pack.py")


def _category_error(error: Exception) -> int:
    print("生成失败")
    print(f"问题：{error}")
    print("原因：输入参数、类目配置或批次目录不符合第一阶段要求。")
    print("建议怎么处理：运行 python factory.py category-help 查看可用命令，再按示例重新执行。")
    return 2


def _category_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def command_category_help(_: argparse.Namespace) -> int:
    _category_utf8_console()
    print("管道疏通｜小白操作顺序")
    print("1. 查看正式项目是否接好（免费）：")
    print("   python factory.py project-status pipe_unclogging")
    print("2. 核算前3组完整内容，准确显示需要付费几张（免费）：")
    print("   python factory.py category-image-plan --scope all")
    print("3. 你明确确认精确张数后，才创建一次性许可证；系统不会替你自动确认。")
    print("4. 同一批次一次生成首图、三拼素材和详情图，不在首图阶段暂停。")
    print("5. 全部成品完成后统一审核：每组1张首图+1张三拼图+3张单独详情图。")
    print("6. 每组最终5张全部人工验收后登记入库存；库存目标是30组。")
    print("注意：三拼图是1张成品，但由3个独立现场画面生成；核算会分开显示成品数和API请求数。")
    print(f"成品固定放在：{PIPE_OUTPUT_ROOT}")
    print("提示词、历史指纹、许可证和审核记录留在项目内部，不与成品混放。")
    print("任何带 authorize/start 的步骤都必须另行明确确认；只看状态和核算不会收费。")
    return 0


def command_audit_category_batch(args: argparse.Namespace) -> int:
    _category_utf8_console()
    try:
        result = category_batch_audit.audit_batch(args.category, args.batch_dir, args.mode)
        batch_dir = result["batch_dir"]
        counts = result["report"]["status_counts"]
        print("mock 审核成功")
        print(f"审核数量：{result['report']['record_count']} 条")
        print(f"审核结果：approved {counts['approved']}；needs_review {counts['needs_review']}；retry {counts['retry']}；rejected {counts['rejected']}")
        print(f"audit_report.json：{batch_dir / 'audit_report.json'}")
        print(f"audit_report.csv：{batch_dir / 'audit_report.csv'}")
        print(f"audit_report_readable.txt：{batch_dir / 'audit_report_readable.txt'}")
        print(f"review_log.xlsx：{batch_dir / 'review_log.xlsx'}")
        print("未读取、生成或伪造图片文件。下一步：人工查看 needs_review 清单，确认提示词后再进入后续生图阶段。")
        return 0
    except (prompt_engine.CategoryPromptError, OSError, ValueError) as error:
        return _category_error(error)


def _category_image_error(error: Exception) -> int:
    print("执行失败")
    print(f"问题：{error}")
    print("原因：付费样片的批次、手机号、模型、许可证、Key 槽位或本地代理未通过安全检查。")
    print("建议怎么处理：不要重复启动或手工修改许可证；先检查上面的具体问题，再重新执行同一条命令。")
    return 2


def _pipe_effective_config() -> dict[str, Any]:
    config = effective_api_config(load_json(ROOT / "config.json"))
    expected = {"model": "gpt-image-2", "quality": "medium", "api_size": "1024x1536"}
    for key, value in expected.items():
        if config.get(key) != value:
            raise RuntimeError(
                f"当前 {key}={config.get(key)!r}，与用户确认的付费参数 {value!r} 不一致"
            )
    return config


def _pipe_sample_range(group_start: int, group_count: int) -> None:
    if group_start != PIPE_SAMPLE_GROUP_START or group_count != PIPE_SAMPLE_GROUP_COUNT:
        raise RuntimeError(
            "当前是新风格样板阶段，只允许先做第1至第3组。"
            "样板通过后，才会开放补足30组的批量入口。"
        )


def _pipe_confirmed_phone(value: str | None = None) -> str:
    phones = load_confirmed_project_phones(PIPE_PROJECT_ID)
    if value:
        normalized = normalize_contact_number(value)
        if normalized not in phones:
            raise RuntimeError("输入手机号与本机已确认的管道疏通号码不一致")
        return normalized
    if len(phones) != 1:
        raise RuntimeError("本机登记了多个号码，请明确指定本次使用哪一个")
    return phones[0]


def _category_output_root(category_id: str) -> Path:
    if category_id not in CATEGORY_IMAGE_PROJECT_IDS:
        raise RuntimeError(f"Unsupported category image project: {category_id}")
    return ROOT / "output" / category_id


def _category_effective_config() -> dict[str, Any]:
    config = effective_api_config(load_json(ROOT / "config.json"))
    if config.get("model") not in {"gpt-image-2", "gpt-image-2.5-flare"}:
        raise RuntimeError("当前模型不在已确认的类目生图模型范围内")
    expected = {"quality": "medium", "api_size": "1024x1536"}
    for key, value in expected.items():
        if config.get(key) != value:
            raise RuntimeError(
                f"当前 {key}={config.get(key)!r}，与已确认的付费参数 {value!r} 不一致"
            )
    return config


def _category_task_config(category_id: str, profile_id: str | None = None) -> dict[str, Any]:
    return category_generation_profile.select_profile(
        _category_effective_config(), category_id, profile_id,
    )


def category_active_batch_dir(category_id: str, value: str | None = None) -> Path:
    if category_id not in CATEGORY_IMAGE_PROJECT_IDS:
        raise RuntimeError(f"Unsupported category image project: {category_id}")
    definition = project_definition(category_id)
    active_value = definition.get("prompt_sources", {}).get("active_batch")
    if isinstance(active_value, dict):
        active_value = active_value.get("batch_dir") or active_value.get("path")
    if not isinstance(active_value, str) or not active_value.strip():
        raise RuntimeError(f"{category_id} 没有登记 active_batch，不能授权生成")
    active = category_image_production.safe_batch_dir(category_id, ROOT / active_value)
    if value:
        requested = category_image_production.safe_batch_dir(category_id, value)
        if requested.resolve() != active.resolve():
            raise RuntimeError(
                f"{category_id} 只能使用 project.json 当前登记的 active_batch，"
                "旧批次只保留为历史，不能继续授权或启动。"
            )
    return active


def _category_confirmed_phone(category_id: str, value: str | None = None) -> str:
    phones = load_confirmed_project_phones(category_id)
    if value:
        normalized = normalize_contact_number(value)
        if normalized not in phones:
            raise RuntimeError(f"输入手机号与本机已确认的 {category_id} 号码不一致")
        return normalized
    if len(phones) != 1:
        raise RuntimeError(f"{category_id} 登记了多个号码，请用 --phone 明确指定")
    return phones[0]


def _category_production_records(
    category_id: str,
    group_start: int,
    group_count: int,
) -> list[dict[str, Any]]:
    definition_path = project_definition_path(category_id).resolve()
    definition = load_json(definition_path)
    manifest_value = definition.get("prompt_sources", {}).get("production_manifest")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise RuntimeError(f"{category_id} 没有登记 production_manifest")
    manifest_path = (ROOT / manifest_value).resolve()
    if definition_path.parent not in manifest_path.parents:
        raise RuntimeError(f"{category_id} production_manifest 路径越出项目目录")
    if not manifest_path.is_file():
        raise RuntimeError(f"{category_id} production_manifest 不存在：{manifest_path}")
    end = group_start + group_count
    return [
        record
        for record in (
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        )
        if group_start <= int(record.get("group_index", 0) or 0) < end
    ]


def _category_sample_gate_range(category_id: str) -> tuple[int, int]:
    definition = project_definition(category_id)
    policy = definition.get("inventory_policy", {})
    gate_groups = int(policy.get("sample_gate_groups") or PIPE_SAMPLE_GROUP_COUNT)
    registry_value = definition.get("group_registry")
    first_group = PIPE_SAMPLE_GROUP_START
    if isinstance(registry_value, str) and registry_value:
        registry_path = (ROOT / registry_value).resolve()
        if registry_path.is_file():
            registry = load_json(registry_path)
            groups = registry.get("groups", [])
            indices = [
                int(item.get("group_index") or item.get("index") or 0)
                for item in groups
                if int(item.get("group_index") or item.get("index") or 0) > 0
            ]
            if indices:
                first_group = min(indices)
    return first_group, gate_groups


def _category_sample_range(category_id: str, group_start: int, group_count: int, *, scope: str | None = None) -> None:
    if group_start < 1 or group_count < 1:
        raise RuntimeError("组号和组数必须为正整数")
    first_group, gate_groups = _category_sample_gate_range(category_id)
    if group_start == first_group and group_count == gate_groups:
        return
    if (
        category_id in {PET_PROJECT_ID, "ktv"}
        and group_start >= first_group
        and group_start + group_count - 1 <= first_group + gate_groups - 1
    ):
        return
    # Whole road-rescue groups are reviewed after generation. Historical sample
    # image files are not a prerequisite for a new, complete, licensed group.
    # This does not approve any image or relax detail-only approval checks.
    if not (category_id == ROAD_PROJECT_ID and scope == "all"):
        try:
            _category_require_registered_cover_approval(category_id)
        except RuntimeError as error:
            raise RuntimeError(
                f"{category_id} 当前是新结构样板阶段，只允许先做第 "
                f"{first_group} 至第 {first_group + gate_groups - 1} 组。"
            ) from error
    records = _category_production_records(category_id, group_start, group_count)
    definition = project_definition(category_id)
    delivery_files_per_group = int(
        definition.get("content_group", {}).get("total_images") or 0
    )
    expected_count = group_count * delivery_files_per_group
    actual_groups = {int(record.get("group_index") or 0) for record in records}
    expected_groups = set(range(group_start, group_start + group_count))
    if (
        delivery_files_per_group <= 0
        or len(records) != expected_count
        or actual_groups != expected_groups
    ):
        raise RuntimeError(
            f"{category_id} 第 {group_start} 至第 {group_start + group_count - 1} 组"
            "不在当前活动清单的完整范围内"
        )


def _category_record_size(record: dict[str, Any]) -> tuple[int, int]:
    value = record.get("expected_size") or record.get("final_size")
    if isinstance(value, str):
        return category_image_production.parse_size(value)
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(item, int) and item > 0 for item in value)
    ):
        return int(value[0]), int(value[1])
    raise RuntimeError(
        f"第 {record.get('group_index')} 组 {record.get('role')} 没有有效 expected_size"
    )


def _category_cover_expected_size(category_id: str, group_index: int) -> tuple[int, int]:
    covers = [
        record
        for record in _category_production_records(category_id, group_index, 1)
        if str(record.get("role") or record.get("generation_kind")) == "cover"
    ]
    if len(covers) != 1:
        raise RuntimeError(f"第 {group_index} 组正式清单必须有且只有1张首图")
    return _category_record_size(covers[0])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    material = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _pipe_production_records(group_start: int, group_count: int) -> list[dict[str, Any]]:
    definition_path = project_definition_path(PIPE_PROJECT_ID).resolve()
    definition = load_json(definition_path)
    manifest_value = definition.get("prompt_sources", {}).get("production_manifest")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise RuntimeError("管道疏通正式项目没有登记 production_manifest")
    manifest_path = (ROOT / manifest_value).resolve()
    if definition_path.parent not in manifest_path.parents:
        raise RuntimeError("管道疏通 production_manifest 路径越出了正式项目目录")
    if not manifest_path.is_file():
        raise RuntimeError(f"管道疏通 production_manifest 不存在：{manifest_path}")
    end = group_start + group_count
    records = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    selected = [
        record
        for record in records
        if group_start <= int(record.get("group_index", 0) or 0) < end
    ]
    return selected


def _pipe_record_size(record: dict[str, Any]) -> tuple[int, int]:
    value = record.get("expected_size") or record.get("final_size")
    if isinstance(value, str):
        return category_image_production.parse_size(value)
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(item, int) and item > 0 for item in value)
    ):
        return int(value[0]), int(value[1])
    raise RuntimeError(
        f"第 {record.get('group_index')} 组 {record.get('role')} 没有有效的 expected_size"
    )


def _pipe_cover_expected_size(group_index: int) -> tuple[int, int]:
    covers = [
        record
        for record in _pipe_production_records(group_index, 1)
        if str(record.get("role")) == "cover"
    ]
    if len(covers) != 1:
        raise RuntimeError(f"第 {group_index} 组正式清单必须恰好有1张首图")
    return _pipe_record_size(covers[0])


def _approve_pipe_delivery_range(group_start: int, group_count: int) -> None:
    """Record the user's explicit whole-group review before inventory audit."""

    phone = _pipe_confirmed_phone()
    # Whole-group approval must not be used to bypass the earlier three-cover
    # style gate or the cover's two independently rendered phone locations.
    cover_evidence = _pipe_cover_approval_evidence(group_start, group_count)
    _pipe_require_registered_cover_approval(cover_evidence)
    expected_roles = ["cover", "triptych", "detail", "detail", "detail"]
    records = _pipe_production_records(group_start, group_count)
    prepared: list[tuple[Path, Path, dict[str, Any], dict[str, Any]]] = []
    for group_index in range(group_start, group_start + group_count):
        group = sorted(
            [
                record
                for record in records
                if int(record.get("group_index", 0) or 0) == group_index
            ],
            key=lambda record: int(
                record.get("delivery_position") or record.get("position") or 0
            ),
        )
        roles = [str(record.get("role") or "") for record in group]
        positions = [
            int(record.get("delivery_position") or record.get("position") or 0)
            for record in group
        ]
        if roles != expected_roles or positions != [1, 2, 3, 4, 5]:
            raise RuntimeError(
                f"第 {group_index} 组正式清单不是1首图+1三拼图+3详情图的固定顺序"
            )
        for record in group:
            expected_size = _pipe_record_size(record)
            target = Path(str(record["target"]))
            if not target.is_absolute():
                target = ROOT / target
            if not category_image_production.valid_png(target, expected_size):
                raise RuntimeError(
                    f"第 {group_index} 组 {record.get('filename')} 缺失、损坏或尺寸不对"
                )
            validation_path = target.with_suffix(".validation.json")
            if not validation_path.is_file():
                raise RuntimeError(
                    f"第 {group_index} 组 {record.get('filename')} 缺少验收记录"
                )
            validation = load_json(validation_path)
            position = int(
                record.get("delivery_position") or record.get("position") or 0
            )
            checks = {
                "category_id": validation.get("category_id") == PIPE_PROJECT_ID,
                "group_index": int(validation.get("group_index", 0) or 0)
                == group_index,
                "position": int(
                    validation.get("delivery_position")
                    or validation.get("position")
                    or 0
                )
                == position,
                "role": validation.get("role") == record.get("role"),
                "postprocessed_locally": validation.get("postprocessed_locally") is True,
                "center_phone": f"电话：{phone}"
                in {str(value) for value in validation.get("expected_text", [])},
            }
            if record.get("role") == "cover":
                _validate_pipe_cover_record(
                    validation,
                    group_index,
                    phone,
                    expected_size,
                    require_approved=False,
                )
            recorded_size = validation.get("expected_size") or validation.get("final_size")
            if recorded_size is not None:
                try:
                    parsed_size = (
                        category_image_production.parse_size(recorded_size)
                        if isinstance(recorded_size, str)
                        else tuple(int(value) for value in recorded_size)
                    )
                except (TypeError, ValueError):
                    parsed_size = ()
                checks["expected_size"] = parsed_size == expected_size
            failed = [name for name, passed in checks.items() if not passed]
            if failed:
                raise RuntimeError(
                    f"第 {group_index} 组 {record.get('filename')} 验收记录不匹配："
                    + ", ".join(failed)
                )
            # The cover was already approved by the dedicated three-cover gate.
            # Keep that sidecar byte-for-byte stable so its registered evidence
            # remains reusable and idempotent.
            if record.get("role") != "cover":
                already_approved = (
                    validation.get("status") == "approved"
                    and validation.get("approved") is True
                    and validation.get("manual_visual_approval") is True
                    and validation.get("image_sha256") == _sha256_file(target)
                )
                if not already_approved:
                    prepared.append(
                        (target, validation_path, validation, dict(validation))
                    )
    approved_at = datetime.now(timezone.utc).isoformat()
    written: list[tuple[Path, dict[str, Any]]] = []
    try:
        for target, validation_path, validation, original in prepared:
            validation.update({
                "status": "approved",
                "approved": True,
                "manual_visual_approval": True,
                "approved_at": approved_at,
                "approval_note": "用户通过 inventory-register --confirm-reviewed 确认已逐张查看整组成品",
                "image_sha256": _sha256_file(target),
            })
            write_json_atomic(validation_path, validation)
            written.append((validation_path, original))
    except Exception:
        for validation_path, original in reversed(written):
            write_json_atomic(validation_path, original)
        raise


def _pipe_v2_plan_bindings(run_plan: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable v2 structure/count/hash fields used by a paid license."""

    required = (
        "production_schema_version",
        "structure_version",
        "generation_mode",
        "generation_unit_count",
        "delivery_count",
        "total_generation_targets",
        "total_delivery_targets",
        "generation_target_ids",
        "generation_targets_sha256",
        "delivery_target_ids",
        "delivery_targets_sha256",
        "pending_generation_target_ids",
        "pending_generation_targets_sha256",
        "pending_delivery_target_ids",
        "pending_delivery_targets_sha256",
        "pending_api_requests",
        "pending_delivery_count",
        "group_recipes",
    )
    missing = [key for key in required if key not in run_plan]
    if missing:
        raise RuntimeError(f"管道疏通v2计划缺少安全字段：{', '.join(missing)}")
    supported_structures = {
        "ktv_v1_1cover_1triptych_1detail",
        "pipe_unclogging_v2_1cover_1triptych_3details",
        "road_rescue_v3_1cover_1triptych_3details",
        "truck_rescue_v3_1cover_1triptych_3details",
        "pet_transport_v1_1cover_5details",
    }
    if run_plan["structure_version"] not in supported_structures:
        raise RuntimeError("?????????? 1??+1???+3?????")
    supported_modes = {"independent_triptych_panels", "independent_delivery_images"}
    if run_plan["generation_mode"] not in supported_modes:
        raise RuntimeError("unsupported category image generation mode")
    recipes = run_plan["group_recipes"]
    if not isinstance(recipes, list) or not recipes:
        raise RuntimeError("管道疏通v2计划缺少逐组高度与三拼图配方")
    height_bindings = [
        {
            "group_index": recipe.get("group_index"),
            "height_profile_id": recipe.get("height_profile_id"),
            "final_sizes": recipe.get("final_sizes"),
        }
        for recipe in recipes
    ]
    triptych_bindings = [
        {
            "group_index": recipe.get("group_index"),
            "triptych_layout_id": recipe.get("triptych_layout_id"),
            "triptych_recipe": recipe.get("triptych_recipe"),
        }
        for recipe in recipes
    ]
    final_sizes = sorted({
        str(size)
        for recipe in recipes
        for size in (recipe.get("final_sizes") or [])
    })
    height_profile_ids = sorted({
        str(recipe.get("height_profile_id"))
        for recipe in recipes
        if recipe.get("height_profile_id")
    })
    triptych_layout_ids = sorted({
        str(recipe.get("triptych_layout_id"))
        for recipe in recipes
        if recipe.get("triptych_layout_id")
    })
    return {
        "production_schema_version": int(run_plan["production_schema_version"]),
        "structure_version": str(run_plan["structure_version"]),
        "generation_mode": str(run_plan["generation_mode"]),
        "generation_unit_count": int(run_plan["generation_unit_count"]),
        "delivery_count": int(run_plan["delivery_count"]),
        "total_generation_targets": int(run_plan["total_generation_targets"]),
        "total_delivery_targets": int(run_plan["total_delivery_targets"]),
        "generation_target_ids": list(run_plan["generation_target_ids"]),
        "generation_targets_sha256": str(run_plan["generation_targets_sha256"]),
        "delivery_target_ids": list(run_plan["delivery_target_ids"]),
        "delivery_targets_sha256": str(run_plan["delivery_targets_sha256"]),
        "pending_generation_target_ids": list(run_plan["pending_generation_target_ids"]),
        "pending_generation_targets_sha256": str(
            run_plan["pending_generation_targets_sha256"]
        ),
        "pending_delivery_target_ids": list(run_plan["pending_delivery_target_ids"]),
        "pending_delivery_targets_sha256": str(
            run_plan["pending_delivery_targets_sha256"]
        ),
        "pending_api_requests": int(run_plan["pending_api_requests"]),
        "pending_delivery_count": int(run_plan["pending_delivery_count"]),
        "group_recipes": recipes,
        "group_recipes_sha256": _json_sha256(recipes),
        "final_sizes": final_sizes,
        "height_profile_ids": height_profile_ids,
        "triptych_layout_ids": triptych_layout_ids,
        "height_bindings_sha256": _json_sha256(height_bindings),
        "triptych_bindings_sha256": _json_sha256(triptych_bindings),
    }


def _validate_pipe_cover_record(
    validation: dict[str, Any],
    group_index: int,
    phone: str,
    expected_size: tuple[int, int],
    *,
    require_approved: bool,
) -> None:
    expected_phone_texts = {f"电话：{phone}", f"联系电话：{phone}"}
    expected_text = {str(value) for value in validation.get("expected_text", [])}
    checks = {
        "category_id": validation.get("category_id") == PIPE_PROJECT_ID,
        "group_index": int(validation.get("group_index", 0) or 0) == group_index,
        "position": int(validation.get("position", 0) or 0) == 1,
        "role": validation.get("role") == "cover",
        "postprocessed_locally": validation.get("postprocessed_locally") is True,
        "confirmed_phone_texts": expected_phone_texts.issubset(expected_text),
    }
    recorded_size = validation.get("expected_size") or validation.get("final_size")
    if recorded_size is not None:
        try:
            if isinstance(recorded_size, str):
                parsed_size = category_image_production.parse_size(recorded_size)
            else:
                parsed_size = tuple(int(value) for value in recorded_size)
        except (TypeError, ValueError):
            parsed_size = ()
        checks["expected_size"] = parsed_size == expected_size
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"第 {group_index} 组首图验收记录与正式项目不一致：{', '.join(failed)}"
        )
    if require_approved and (
        validation.get("status") != "approved"
        or validation.get("approved") is not True
        or validation.get("manual_visual_approval") is not True
    ):
        raise RuntimeError(f"第 {group_index} 组首图尚未人工确认")


def _validate_category_cover_record(
    category_id: str,
    validation: dict[str, Any],
    group_index: int,
    phone: str,
    expected_size: tuple[int, int],
    *,
    require_approved: bool,
) -> None:
    expected_phone_texts = {f"电话：{phone}"} if category_id == "ktv" else {f"电话：{phone}", f"联系电话：{phone}"}
    expected_text = {str(value) for value in validation.get("expected_text", [])}
    checks = {
        "category_id": validation.get("category_id") == category_id,
        "group_index": int(validation.get("group_index", 0) or 0) == group_index,
        "position": int(
            validation.get("delivery_position")
            or validation.get("position")
            or 0
        )
        == 1,
        "role": validation.get("role") == "cover",
        "postprocessed_locally": validation.get("postprocessed_locally") is True,
        "confirmed_phone_texts": expected_phone_texts.issubset(expected_text),
    }
    recorded_size = validation.get("expected_size") or validation.get("final_size")
    if recorded_size is not None:
        try:
            if isinstance(recorded_size, str):
                parsed_size = category_image_production.parse_size(recorded_size)
            else:
                parsed_size = tuple(int(value) for value in recorded_size)
        except (TypeError, ValueError):
            parsed_size = ()
        checks["expected_size"] = parsed_size == expected_size
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"第 {group_index} 组首图验收记录与 {category_id} 正式项目不一致："
            + ", ".join(failed)
        )
    if require_approved and (
        validation.get("status") != "approved"
        or validation.get("approved") is not True
        or validation.get("manual_visual_approval") is not True
    ):
        raise RuntimeError(f"第 {group_index} 组首图尚未人工确认")


def _category_validation_phone(validation: dict[str, Any], group_index: int) -> str:
    phones: set[str] = set()
    for value in validation.get("expected_text", []):
        match = re.fullmatch(r"(?:联系电话|电话)[：:]\s*(.+?)\s*", str(value).strip())
        if not match:
            continue
        candidate = match.group(1).strip()
        extracted = extract_contact_numbers(candidate)
        if len(extracted) == 1 and candidate in {
            extracted[0],
            extracted[0].replace("-", ""),
        }:
            phones.add(extracted[0])
    if len(phones) != 1:
        raise RuntimeError(f"第 {group_index} 组历史首图验收记录没有唯一已批准手机号")
    return next(iter(phones))


def _category_cover_approval_evidence(
    category_id: str,
    group_start: int,
    group_count: int,
    *,
    expected_phone: str | None = None,
    use_recorded_phone: bool = False,
) -> dict[str, Any]:
    if use_recorded_phone and expected_phone is not None:
        raise RuntimeError("历史首图号码回读与显式号码校验不能同时启用")
    confirmed_phone = (
        None
        if use_recorded_phone
        else _category_confirmed_phone(category_id, expected_phone)
    )
    output_root = _category_output_root(category_id)
    rows: list[dict[str, Any]] = []
    for group_index in range(group_start, group_start + group_count):
        expected_size = _category_cover_expected_size(category_id, group_index)
        image = output_root / f"group_{group_index:04d}" / "01_cover.png"
        validation_path = image.with_suffix(".validation.json")
        if not category_image_production.valid_png(image, expected_size):
            raise RuntimeError(f"第 {group_index} 组首图不存在或文件损坏，不能继续生成详情图")
        if not validation_path.is_file():
            raise RuntimeError(f"第 {group_index} 组首图没有人工验收记录")
        validation = load_json(validation_path)
        recorded_phone = _category_validation_phone(validation, group_index)
        if use_recorded_phone:
            phone = recorded_phone
        else:
            phone = str(confirmed_phone)
            if recorded_phone != phone:
                raise RuntimeError(
                    f"第 {group_index} 组首图批准号码 {recorded_phone} "
                    f"与本次指定号码 {phone} 不一致"
                )
        _validate_category_cover_record(
            category_id,
            validation,
            group_index,
            phone,
            expected_size,
            require_approved=True,
        )
        image_sha256 = _sha256_file(image)
        if validation.get("image_sha256") != image_sha256:
            raise RuntimeError(f"第 {group_index} 组首图在确认后发生变化，必须重新查看并确认")
        rows.append({
            "group_index": group_index,
            "image": str(image),
            "image_sha256": image_sha256,
            "expected_size": list(expected_size),
            "validation": str(validation_path),
            "validation_sha256": _sha256_file(validation_path),
        })
    material = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "groups": rows,
        "sha256": hashlib.sha256(material.encode("utf-8")).hexdigest(),
    }


def _category_require_registered_cover_approval(
    category_id: str,
    evidence: dict[str, Any] | None = None,
) -> None:
    if evidence is not None:
        groups = evidence.get("groups") or []
        if not groups:
            raise RuntimeError("当前范围没有可绑定的首图验收证据")
        group_indices = sorted(int(row.get("group_index") or 0) for row in groups)
        group_start = group_indices[0]
        group_count = len(group_indices)
        expected_indices = list(range(group_start, group_start + group_count))
        approvals_dir = ROOT / "projects" / category_id / "groups" / "cover_approvals"
        if group_indices == expected_indices and approvals_dir.is_dir():
            pattern = f"group_{group_start:04d}_{group_count:04d}_*.json"
            for approval_path in approvals_dir.glob(pattern):
                registered = load_json(approval_path)
                if (
                    registered.get("project_id") == category_id
                    and int(registered.get("group_start") or 0) == group_start
                    and int(registered.get("group_count") or 0) == group_count
                    and registered.get("sha256") == evidence.get("sha256")
                ):
                    return
    definition = project_definition(category_id)
    cover_state = definition.get("references", {}).get("cover", {})
    evidence_value = cover_state.get("sample_approval_evidence")
    if cover_state.get("approved_style") is not True or not evidence_value:
        raise RuntimeError("3张首图的正式风格批准证据尚未登记")
    evidence_path = (ROOT / str(evidence_value)).resolve()
    project_root = project_definition_path(category_id).resolve().parent
    if project_root not in evidence_path.parents or not evidence_path.is_file():
        raise RuntimeError("3张首图的正式风格批准证据文件不存在或路径不安全")
    registered = load_json(evidence_path)
    sample_start = int(registered.get("group_start") or 0)
    sample_count = int(registered.get("group_count") or 0)
    first_group, gate_groups = _category_sample_gate_range(category_id)
    if sample_start != first_group or sample_count != gate_groups:
        raise RuntimeError("正式样板批准证据的组范围不正确")
    current_sample = _category_cover_approval_evidence(
        category_id,
        sample_start,
        sample_count,
        use_recorded_phone=True,
    )
    if registered.get("sha256") != current_sample.get("sha256"):
        raise RuntimeError("3张首图当前验收证据与正式登记不一致，必须重新人工确认")


def _pipe_cover_approval_evidence(group_start: int, group_count: int) -> dict[str, Any]:
    phone = _pipe_confirmed_phone()
    rows: list[dict[str, Any]] = []
    for group_index in range(group_start, group_start + group_count):
        expected_size = _pipe_cover_expected_size(group_index)
        image = PIPE_OUTPUT_ROOT / f"group_{group_index:04d}" / "01_cover.png"
        validation_path = image.with_suffix(".validation.json")
        if not category_image_production.valid_png(image, expected_size):
            raise RuntimeError(f"第 {group_index} 组首图不存在或文件损坏，不能继续生成详情图")
        if not validation_path.is_file():
            raise RuntimeError(f"第 {group_index} 组首图没有人工验收记录")
        validation = load_json(validation_path)
        _validate_pipe_cover_record(
            validation, group_index, phone, expected_size, require_approved=True
        )
        image_sha256 = _sha256_file(image)
        if validation.get("image_sha256") != image_sha256:
            raise RuntimeError(f"第 {group_index} 组首图在确认后发生了变化，必须重新查看并确认")
        rows.append({
            "group_index": group_index,
            "image": str(image),
            "image_sha256": image_sha256,
            "expected_size": list(expected_size),
            "validation": str(validation_path),
            "validation_sha256": _sha256_file(validation_path),
        })
    material = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "groups": rows,
        "sha256": hashlib.sha256(material.encode("utf-8")).hexdigest(),
    }


def _pipe_require_registered_cover_approval(evidence: dict[str, Any]) -> None:
    definition = project_definition(PIPE_PROJECT_ID)
    cover_state = definition.get("references", {}).get("cover", {})
    evidence_value = cover_state.get("sample_approval_evidence")
    if cover_state.get("approved_style") is not True or not evidence_value:
        raise RuntimeError("3张首图的正式风格批准证据尚未登记")
    evidence_path = (ROOT / str(evidence_value)).resolve()
    project_root = project_definition_path(PIPE_PROJECT_ID).resolve().parent
    if project_root not in evidence_path.parents or not evidence_path.is_file():
        raise RuntimeError("3张首图的正式风格批准证据文件不存在或路径不安全")
    registered = load_json(evidence_path)
    if registered.get("sha256") != evidence.get("sha256"):
        raise RuntimeError("3张首图当前验收证据与正式登记不一致，必须重新人工确认")


def command_category_image_plan(args: argparse.Namespace) -> int:
    """Show the exact local sample plan without creating a paid license."""
    _category_utf8_console()
    try:
        category_id = args.category
        _category_sample_range(category_id, args.group_start, args.group_count, scope=args.scope)
        config = _category_task_config(category_id, getattr(args, "generation_profile", None))
        batch_dir = category_active_batch_dir(category_id, args.batch_dir)
        phone = _category_confirmed_phone(category_id, args.phone)
        output_root = _category_output_root(category_id)
        run_plan = category_image_production.plan(
            category_id,
            batch_dir,
            args.group_start,
            args.group_count,
            phone,
            config,
            scope=args.scope,
            output_root=output_root,
            generation_target_id=args.generation_target_id,
        )
        if getattr(args, "review_after_batch", False):
            _category_require_executable_scope(
                args.scope, str(run_plan.get("generation_mode") or ""),
                category_id=category_id, review_after_batch=True,
            )
        bindings = _pipe_v2_plan_bindings(run_plan)
        auto_retry_limit = int(getattr(args, "auto_retry_limit", 0) or 0)
        max_request_budget = bindings["pending_api_requests"] * (
            1 + auto_retry_limit
        )
        print(f"{category_id} 图片生产计划")
        print(
            f"范围：{args.scope}；第 {args.group_start} 至 "
            f"{args.group_start + args.group_count - 1} 组"
        )
        print(f"本次绑定手机号：{phone}")
        print(
            f"最终要交付 {bindings['delivery_count']} 张成品；"
            f"成品已有 {run_plan['existing_images']} 张；"
            f"可本地恢复 {run_plan['recoverable_images']} 张；"
            f"还缺 {bindings['pending_delivery_count']} 张成品。"
        )
        if run_plan["generation_mode"] == "independent_delivery_images":
            print(
                f"本次仍需 {bindings['pending_api_requests']} 次付费图片请求。"
                "本结构每张成品对应1次独立图片生成请求。"
            )
        else:
            print(
                f"本次仍需 {bindings['pending_api_requests']} 次付费图片请求。"
                "三拼图是1张成品，但由3个独立现场画面生成后在本地拼合，"
                "所以“成品张数”和“API请求次数”不相同。"
            )
        if auto_retry_limit:
            print(
                f"受控自动重试：每个失败目标最多重试 {auto_retry_limit} 次；"
                f"基础请求 {bindings['pending_api_requests']} 次，"
                f"含重试的最大付费请求预算 {max_request_budget} 次。"
            )
        print(
            f"模型：{config['model']}；质量：{config['quality']}；"
            f"原始API尺寸：{config['api_size']}；"
            f"本次最终成品尺寸：{', '.join(bindings['final_sizes'])}"
        )
        if config.get("generation_profile"):
            print("原图契约：仅接受2336x3520或2352x3520；原响应保全，工作原图归一化1024x1536，不宣称原生3840长边。")
        if run_plan["generation_mode"] == "independent_delivery_images":
            print(
                f"每组最终{run_plan['delivery_unit_count']}张：1张门面首图 + "
                f"{run_plan['delivery_unit_count'] - 1}张单独详情图。"
            )
            print("同一组不使用三拼合成；首图和详情图都是独立成品。")
        elif category_id == "ktv":
            print("每组最终3张：1张包厢首图 + 1张三拼图 + 1张单图详情；5个独立生成单元。")
            print("同组共享包厢设定；成品统一864x1536（9:16），三拼采用上中下布局。")
        else:
            print("每组最终5张：1张门面首图 + 1张三拼图 + 3张单独详情图。")
            print("同一组5张保持同一最终高度；不同组轮换高度与三拼布局，降低同质化风险。")
        print(f"正式输出目录：{output_root}")
        print(f"计划校验码：{run_plan['plan_sha256']}")
        if run_plan.get("generation_target_id"):
            print(f"单图探针目标：{run_plan['generation_target_id']}")
        print("待付费生成的独立画面：")
        for target_id in bindings["pending_generation_target_ids"]:
            print(f"- {target_id}")
        if args.scope == "covers":
            print(
                "下一步：用户明确生产指令即授权本任务费用，无需二次确认；"
                "才能创建一次性许可证。"
            )
        elif args.scope == "details":
            try:
                evidence = _category_cover_approval_evidence(
                    category_id,
                    args.group_start,
                    args.group_count,
                    expected_phone=phone,
                )
                _category_require_registered_cover_approval(category_id, evidence)
                print(
                    f"所选 {args.group_count} 组首图均已确认，可以在你明确同意"
                    f"{bindings['pending_delivery_count']}张剩余成品和"
                    f"最多{max_request_budget}次API请求后创建许可证。"
                )
            except RuntimeError as error:
                print(f"当前还不能授权详情图：{error}")
        else:
            print("all 表示本批首图、三拼素材和详情一起纳入同一个精确付费计划。")
            print("所有成品完成后再统一审核；不会在首图阶段暂停等待确认。")
        print("本命令未创建许可证、未调用 API、未产生费用。")
        return 0
    except Exception as error:
        return _category_image_error(error)


def command_rebuild_category_covers(args: argparse.Namespace) -> int:
    """Reapply local cover text to preserved raw images without API access."""
    _category_utf8_console()
    try:
        if not args.confirm_rejected:
            raise RuntimeError("只有用户明确拒绝当前首图后，才能加 --confirm-rejected 本地重做")
        category_id = args.category
        _category_sample_range(category_id, args.group_start, args.group_count)
        config = _category_effective_config()
        batch_dir = category_active_batch_dir(category_id, args.batch_dir)
        phone = _category_confirmed_phone(category_id, args.phone)
        output_root = _category_output_root(category_id)
        result = category_image_production.rebuild_cover_overlays(
            category_id,
            batch_dir,
            args.group_start,
            args.group_count,
            phone,
            config,
            output_root,
            args.reason,
        )
        print(
            f"CATEGORY_COVERS_REBUILT_LOCAL project={category_id} "
            f"groups={len(result['results'])} api_called=false paid_requests=0"
        )
        print(f"旧版拒绝样片已归档：{result['archive_root']}")
        for item in result["results"]:
            print(
                f"- 第 {item['group_index']} 组：{item['rebuilt_image']}；"
                f"门头识别={item['signboard_detection']}"
            )
        print("新首图仍是 needs_user_review，程序没有替用户批准。")
        return 0
    except Exception as error:
        return _category_image_error(error)


def command_prepare_category_cover_regeneration(args: argparse.Namespace) -> int:
    """Archive rejected covers and mark them for a new paid generation plan."""
    _category_utf8_console()
    try:
        if not args.confirm_rejected:
            raise RuntimeError("只有用户明确拒绝当前首图后，才能准备重新付费生图")
        category_id = args.category
        _category_sample_range(category_id, args.group_start, args.group_count)
        config = _category_effective_config()
        batch_dir = category_active_batch_dir(category_id, args.batch_dir)
        phone = _category_confirmed_phone(category_id, args.phone)
        output_root = _category_output_root(category_id)
        result = category_image_production.prepare_cover_regeneration(
            category_id,
            batch_dir,
            args.group_start,
            args.group_count,
            phone,
            config,
            output_root,
            args.reason,
        )
        print(
            f"CATEGORY_COVER_REGENERATION_PREPARED project={category_id} "
            f"groups={len(result['results'])} api_called=false paid_requests=0"
        )
        print(f"旧成品、验收文件和付费原图已归档：{result['archive_root']}")
        for item in result["results"]:
            print(f"- 第 {item['group_index']} 组：已标记 rejected，旧 raw 已保留")
        print("下一步重新运行 category-image-plan 免费核算；本命令没有创建许可证或调用 API。")
        return 0
    except Exception as error:
        return _category_image_error(error)


def command_prepare_category_detail_regeneration(args: argparse.Namespace) -> int:
    """Preserve one rejected detail before separately authorizing regeneration."""
    _category_utf8_console()
    try:
        if not args.confirm_rejected:
            raise RuntimeError("只有用户明确要求替换当前详情后，才能准备重新付费生图")
        if args.group_count != 1 or not str(args.generation_target_id).strip():
            raise RuntimeError("详情替换准备只允许一组中的一个明确独立详情目标")
        category_id = args.category
        _category_sample_range(category_id, args.group_start, args.group_count)
        result = category_image_production.prepare_detail_regeneration(
            category_id,
            category_active_batch_dir(category_id, args.batch_dir),
            args.group_start,
            args.group_count,
            _category_confirmed_phone(category_id, args.phone),
            _category_effective_config(),
            _category_output_root(category_id),
            args.reason,
            args.generation_target_id,
        )
        print(
            f"CATEGORY_DETAIL_REGENERATION_PREPARED project={category_id} "
            f"target={args.generation_target_id} api_called=false paid_requests=0"
        )
        print(f"旧成品、验收文件和付费原图已归档并核验：{result['archive_root']}")
        print("仅所选详情标记为 rejected；原图片和 raw 保留，未批准或重生成其他图片。")
        print("下一步运行 category-image-plan 核算该目标，取得新的精确付费确认后再启动。")
        return 0
    except Exception as error:
        return _category_image_error(error)


def command_approve_pipe_sample_covers(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise RuntimeError("只有在你亲眼看过3张首图后，才能加 --confirm 确认")
    _pipe_sample_range(args.group_start, args.group_count)
    _pipe_effective_config()
    phone = _pipe_confirmed_phone()
    approved_at = datetime.now(timezone.utc).isoformat()
    prepared: list[tuple[Path, Path, dict[str, Any]]] = []
    for group_index in range(args.group_start, args.group_start + args.group_count):
        expected_size = _pipe_cover_expected_size(group_index)
        image = PIPE_OUTPUT_ROOT / f"group_{group_index:04d}" / "01_cover.png"
        validation_path = image.with_suffix(".validation.json")
        if not category_image_production.valid_png(image, expected_size):
            raise RuntimeError(f"第 {group_index} 组首图不存在或损坏")
        if not validation_path.is_file():
            raise RuntimeError(f"第 {group_index} 组首图缺少本地叠字验收记录")
        validation = load_json(validation_path)
        _validate_pipe_cover_record(
            validation, group_index, phone, expected_size, require_approved=False
        )
        prepared.append((image, validation_path, validation))
    for image, validation_path, validation in prepared:
        validation.update({
            "status": "approved",
            "approved": True,
            "manual_visual_approval": True,
            "approved_at": approved_at,
            "approval_note": args.note,
            "image_sha256": _sha256_file(image),
        })
        write_json_atomic(validation_path, validation)
    evidence = _pipe_cover_approval_evidence(args.group_start, args.group_count)
    evidence_path = ROOT / "projects" / PIPE_PROJECT_ID / "groups" / "sample_cover_approval.json"
    write_json_atomic(evidence_path, {
        "schema_version": 1,
        "project_id": PIPE_PROJECT_ID,
        "group_start": args.group_start,
        "group_count": args.group_count,
        "approved_at": approved_at,
        "approval_note": args.note,
        **evidence,
    })
    definition_path = project_definition_path(PIPE_PROJECT_ID)
    definition = load_json(definition_path)
    definition["references"]["cover"].update({
        "status": "approved_from_three_generated_samples",
        "approved_style": True,
        "sample_approval_evidence": str(evidence_path.relative_to(ROOT)).replace("\\", "/"),
    })
    write_json_atomic(definition_path, definition)
    print("PIPE_SAMPLE_COVERS_APPROVED groups=3 api_called=false")
    print("首图风格门槛已通过；现在可以先核算详情图，但不会自动付费或自动生成。")
    return 0


def command_approve_category_sample_covers(args: argparse.Namespace) -> int:
    _category_utf8_console()
    if not args.confirm:
        raise RuntimeError("只有你亲眼看过所选首图后，才能加 --confirm 确认")
    category_id = args.category
    _category_sample_range(category_id, args.group_start, args.group_count)
    _category_effective_config()
    phone = _category_confirmed_phone(category_id, args.phone)
    output_root = _category_output_root(category_id)
    approved_at = datetime.now(timezone.utc).isoformat()
    prepared: list[tuple[Path, Path, dict[str, Any]]] = []
    for group_index in range(args.group_start, args.group_start + args.group_count):
        expected_size = _category_cover_expected_size(category_id, group_index)
        image = output_root / f"group_{group_index:04d}" / "01_cover.png"
        validation_path = image.with_suffix(".validation.json")
        if not category_image_production.valid_png(image, expected_size):
            raise RuntimeError(f"第 {group_index} 组首图不存在或损坏")
        if not validation_path.is_file():
            raise RuntimeError(f"第 {group_index} 组首图缺少本地叠字验收记录")
        validation = load_json(validation_path)
        _validate_category_cover_record(
            category_id,
            validation,
            group_index,
            phone,
            expected_size,
            require_approved=False,
        )
        prepared.append((image, validation_path, validation))
    for image, validation_path, validation in prepared:
        validation.update({
            "status": "approved",
            "approved": True,
            "manual_visual_approval": True,
            "approved_at": approved_at,
            "approval_note": args.note,
            "image_sha256": _sha256_file(image),
        })
        write_json_atomic(validation_path, validation)
    evidence = _category_cover_approval_evidence(
        category_id,
        args.group_start,
        args.group_count,
        expected_phone=phone,
    )
    first_group, gate_groups = _category_sample_gate_range(category_id)
    is_sample_gate = args.group_start == first_group and args.group_count == gate_groups
    if is_sample_gate:
        evidence_path = ROOT / "projects" / category_id / "groups" / "sample_cover_approval.json"
    else:
        approvals_dir = ROOT / "projects" / category_id / "groups" / "cover_approvals"
        evidence_path = approvals_dir / (
            f"group_{args.group_start:04d}_{args.group_count:04d}_{evidence['sha256'][:12]}.json"
        )
    write_json_atomic(evidence_path, {
        "schema_version": 1,
        "project_id": category_id,
        "group_start": args.group_start,
        "group_count": args.group_count,
        "approved_at": approved_at,
        "approval_note": args.note,
        **evidence,
    })
    if is_sample_gate:
        definition_path = project_definition_path(category_id)
        definition = load_json(definition_path)
        definition.setdefault("references", {}).setdefault("cover", {}).update({
            "status": "approved_from_three_generated_samples",
            "approved_style": True,
            "sample_approval_evidence": str(evidence_path.relative_to(ROOT)).replace("\\", "/"),
        })
        write_json_atomic(definition_path, definition)
        label = "CATEGORY_SAMPLE_COVERS_APPROVED"
    else:
        label = "CATEGORY_COVERS_APPROVED"
    print(
        f"{label} project={category_id} groups={args.group_count} "
        f"range={args.group_start}-{args.group_start + args.group_count - 1} api_called=false"
    )
    print("所选首图已确认；现在可以核算并授权详情图，但不会自动付费或自动生成。")
    return 0


def command_test_image(args: argparse.Namespace) -> int:
    from tools import single_image_test

    config = effective_api_config(load_json(ROOT / "config.json"))
    result = single_image_test.run(
        config, args.prompt, args.api_key_slot, RUNTIME_DIR,
        Path("E:/Downloads/image_model_tests"),
        confirm_paid=args.confirm_paid,
        confirm_third_party=args.confirm_third_party,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 2


def _category_max_workers(
    requested_worker_cap: int | None,
    slots: list[int],
    pending_requests: int,
) -> int:
    worker_cap = 10 if requested_worker_cap is None else int(requested_worker_cap)
    if worker_cap < 1 or worker_cap > 10:
        raise RuntimeError("--max-workers 必须在 1 到 10 之间")
    return min(worker_cap, len(slots), pending_requests)


def _category_scope_requires_cover_approval(scope: str) -> bool:
    return scope == "details"


def _category_require_executable_scope(
    scope: str, generation_mode: str, *, category_id: str | None = None,
    review_after_batch: bool = False,
) -> None:
    if review_after_batch and scope != "all":
        raise RuntimeError(
            "--review-after-batch 仅兼容旧命令；它只能与 --scope all 一起使用"
        )


def command_authorize_category_images(args: argparse.Namespace) -> int:
    _category_utf8_console()
    try:
        category_id = args.category
        _category_sample_range(category_id, args.group_start, args.group_count, scope=args.scope)
        if args.scope not in {"covers", "details", "all"}:
            raise RuntimeError("授权范围必须是 covers、details 或 all")
        if not args.confirm_paid:
            raise RuntimeError("缺少 --confirm-paid 机器授权声明；用户明确生产指令已是本任务授权，无需二次确认")
        config = _category_task_config(category_id, getattr(args, "generation_profile", None))
        if config.get("provider") == "relay" and not args.confirm_third_party:
            raise RuntimeError("当前使用第三方中转站，缺少 --confirm-third-party 信任确认")
        batch_dir = category_active_batch_dir(category_id, args.batch_dir)
        phone = _category_confirmed_phone(category_id, args.phone)
        output_root = _category_output_root(category_id)
        slots = selected_key_slots(args)
        if not slots:
            slots = list(range(1, configured_key_count() + 1))
        if not slots:
            raise RuntimeError("没有找到已配置的 API Key")
        run_plan = category_image_production.plan(
            category_id,
            batch_dir,
            args.group_start,
            args.group_count,
            phone,
            config,
            scope=args.scope,
            output_root=output_root,
            generation_target_id=args.generation_target_id,
        )
        _category_require_executable_scope(
            args.scope,
            str(run_plan.get("generation_mode") or ""),
            category_id=category_id,
            review_after_batch=bool(getattr(args, "review_after_batch", False)),
        )
        bindings = _pipe_v2_plan_bindings(run_plan)
        pending_requests = bindings["pending_api_requests"]
        pending_delivery = bindings["pending_delivery_count"]
        auto_retry_limit = int(getattr(args, "auto_retry_limit", 0) or 0)
        if auto_retry_limit not in {0, 1}:
            raise RuntimeError("受控自动重试次数只能是 0 或 1")
        max_attempts = 1 + auto_retry_limit
        expected_request_budget = pending_requests * max_attempts
        if pending_requests <= 0:
            raise RuntimeError("所选组图已经有完整有效图片，不需要创建新的付费许可证")
        if args.max_requests != expected_request_budget:
            raise RuntimeError(
                f"本次有 {pending_requests} 个待生成目标，每个目标最多尝试 "
                f"{max_attempts} 次；--max-requests 必须精确填写 "
                f"{expected_request_budget}，不能多也不能少"
            )
        if args.plan_sha256 != run_plan["plan_sha256"]:
            raise RuntimeError("计划校验码不一致；请重新运行 category-image-plan，再确认最新精确张数")
        if _category_scope_requires_cover_approval(args.scope):
            cover_evidence = _category_cover_approval_evidence(
                category_id,
                args.group_start,
                args.group_count,
                expected_phone=phone,
            )
            _category_require_registered_cover_approval(category_id, cover_evidence)
        else:
            cover_evidence = None
        max_workers = _category_max_workers(
            args.max_workers, slots, pending_requests
        )
        requested_policy = getattr(args, "concurrency_policy", "adaptive")
        if config.get("generation_profile") and requested_policy != "adaptive":
            raise RuntimeError("本新4K profile仅支持已验证的adaptive并发，最多10路")
        if requested_policy == "fixed-10":
            if max_workers != 10 or len(slots) < 10:
                raise RuntimeError("固定10路模式需要10个已配置且已选择的 API Key")
            concurrency_policy = category_image_production.FIXED_TEN_CONCURRENCY_POLICY
        else:
            concurrency_policy = category_image_production.ADAPTIVE_CONCURRENCY_POLICY
        old_license = category_image_production.license_path(
            category_id, batch_dir, args.group_start, args.group_count
        )
        if old_license.is_file() and load_json(old_license).get("status") == "active":
            raise RuntimeError(f"旧入口仍有 active 一次性许可证，必须先人工处理：{old_license}")
        licenses_dir = category_image_production.production_dir(batch_dir) / "licenses"
        for existing_path in licenses_dir.glob("*.json") if licenses_dir.is_dir() else []:
            existing = load_json(existing_path)
            if (
                existing.get("status") == "active"
                and existing.get("scope") == args.scope
                and int(existing.get("group_start", 0)) == args.group_start
                and int(existing.get("group_count", 0)) == args.group_count
            ):
                raise RuntimeError(f"同一范围已有 active 一次性许可证：{existing_path}")
        license_id = (
            datetime.now(timezone.utc).strftime(f"{category_id}-%Y%m%dT%H%M%SZ-")
            + secrets.token_hex(6)
        )
        manifest_file, overlay_file = category_image_production.write_production_files(
            run_plan, phone, license_id
        )
        target = category_image_production.license_path(
            category_id, batch_dir, args.group_start, args.group_count, license_id
        )
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema_version": 3,
            "kind": "category-image-production",
            "license_id": license_id,
            "status": "active",
            "one_time": True,
            "created_at": now,
            "category_id": category_id,
            "batch_id": batch_dir.name,
            "batch_dir": str(batch_dir),
            "group_start": args.group_start,
            "group_count": args.group_count,
            "scope": args.scope,
            "generation_target_id": run_plan.get("generation_target_id"),
            "output_root": run_plan["output_root"],
            "phone": phone,
            "contact_sha256": hashlib.sha256(phone.encode("utf-8")).hexdigest(),
            "manifest_sha256": run_plan["manifest_sha256"],
            "plan_sha256": run_plan["plan_sha256"],
            **bindings,
            "targets_sha256": bindings["delivery_targets_sha256"],
            "pending_target_ids": bindings["pending_delivery_target_ids"],
            "pending_targets_sha256": bindings["pending_delivery_targets_sha256"],
            "approved_target_ids": bindings["pending_delivery_target_ids"],
            "approved_targets_sha256": bindings["pending_delivery_targets_sha256"],
            "approved_generation_target_ids": bindings["pending_generation_target_ids"],
            "approved_delivery_target_ids": bindings["pending_delivery_target_ids"],
            "approved_api_request_count": pending_requests,
            "approved_delivery_count": pending_delivery,
            "production_manifest": str(manifest_file),
            "overlay_plan": str(overlay_file),
            "provider": config["provider"],
            "base_url": config.get("base_url", ""),
            "model": config["model"],
            "quality": config["quality"],
            "size": config["api_size"],
            "approved_image_count": pending_delivery,
            **category_generation_profile.bindings(config, category_id),
            "approved_request_budget": args.max_requests,
            "max_attempts": max_attempts,
            "retry_policy": (
                category_image_production.CLASSIFIED_RETRY_POLICY
                if auto_retry_limit
                else category_image_production.NO_RETRY_POLICY
            ),
            "retry_backoff_seconds": (
                category_image_production.RETRY_BACKOFF_SECONDS
                if auto_retry_limit
                else 0
            ),
            "sdk_max_retries": 0,
            "max_workers": max_workers,
            "concurrency_policy": concurrency_policy,
            "api_key_policy": "fixed",
            "api_key_slots": slots,
            "third_party_confirmed": bool(args.confirm_third_party),
            "cover_approval_sha256": cover_evidence["sha256"] if cover_evidence else None,
            "cover_approval_groups": cover_evidence["groups"] if cover_evidence else [],
            "review_after_batch": bool(getattr(args, "review_after_batch", False)),
            "phone_sent_to_model": (
                category_id in category_image_production.MODEL_GENERATED_SIGNBOARD_CATEGORIES
                and args.scope in {"covers", "all"}
            ),
            "requests_used": 0,
        }
        category_image_production.write_new_license(target, payload)
        args.created_license_id = license_id
        print(f"{category_id} 付费样片授权成功")
        print(
            f"授权范围：{args.scope}；待交付成品：{pending_delivery} 张；"
            f"最多 API 请求：{args.max_requests} 次"
        )
        print("成品数和API请求数分开计算：三拼图1张成品需要3个独立画面。")
        if concurrency_policy == category_image_production.FIXED_TEN_CONCURRENCY_POLICY:
            print(
                "并发策略：单请求探针成功后固定10路；异常不降档；"
                f"每目标自动重试上限：{auto_retry_limit}；SDK重试：0"
            )
        else:
            print(
                f"并发策略：单请求探针后按 4→6→8→10 自适应升档；"
                f"本次上限 {max_workers}；异常自动降档；"
                f"每目标自动重试上限：{auto_retry_limit}；SDK重试：0"
            )
        print(
            f"模型：{config['model']}；质量：{config['quality']}；"
            f"原始API尺寸：{config['api_size']}；"
            f"最终成品尺寸：{', '.join(bindings['final_sizes'])}"
        )
        print(f"API Key 槽位：{', '.join(str(slot) for slot in slots)}")
        print(f"正式活动批次：{batch_dir}")
        print(f"生产提示词清单：{manifest_file}")
        print(f"本地叠字方案：{overlay_file}")
        print(f"一次性许可证：{target}")
        if payload["phone_sent_to_model"]:
            print("已确认手机号会发送给生图模型，用于自然生成实体门头联系电话；中部电话和底部服务词仍由本地叠加。")
        else:
            print("手机号只用于本地确定性叠字，不发送给生图模型。")
        print(
            "下一步运行：python factory.py start-category-images "
            f"--category {category_id} --batch-dir \"{batch_dir}\" "
            f"--group-start {args.group_start} --group-count {args.group_count} "
            f"--scope {args.scope} --license-id {license_id}"
        )
        return 0
    except (Exception,) as error:
        return _category_image_error(error)


def _category_endpoint_reachable(url: str, proxy: str | None) -> bool:
    import urllib.error
    import urllib.request

    handler = urllib.request.ProxyHandler(
        {"http": proxy, "https": proxy} if proxy else {}
    )
    opener = urllib.request.build_opener(handler)
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "local-service-image-factory-preflight/1.0"},
    )
    try:
        with opener.open(request, timeout=8):
            return True
    except urllib.error.HTTPError:
        # 401/403/404/405 still proves that the HTTPS endpoint is reachable.
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _category_proxy_environment(config: dict[str, Any]) -> dict[str, str]:
    import socket

    env = dict(os.environ)
    probe_url = str(config.get("base_url", "")).rstrip("/") + "/models"
    candidates = [("127.0.0.1", 10808), ("127.0.0.1", 7897)]
    for host, port in candidates:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                pass
        except OSError:
            continue
        proxy = f"http://{host}:{port}"
        if not _category_endpoint_reachable(probe_url, proxy):
            continue
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env[key] = proxy
        env["NO_PROXY"] = "localhost,127.0.0.1"
        env["no_proxy"] = "localhost,127.0.0.1"
        env["PIPE_CATEGORY_NETWORK_MODE"] = f"proxy:{proxy}"
        return env

    if _category_endpoint_reachable(probe_url, None):
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(key, None)
        env["NO_PROXY"] = "localhost,127.0.0.1"
        env["no_proxy"] = "localhost,127.0.0.1"
        env["PIPE_CATEGORY_NETWORK_MODE"] = "direct"
        return env

    raise RuntimeError(
        "本地 AI 代理 127.0.0.1:10808/7897 均不可用，且 TinySnow 直连检查失败；未启动付费任务"
    )


def _recent_job_update(job: dict[str, Any], seconds: int = 120) -> bool:
    value = job.get("updated_at") or job.get("created_at")
    if not value:
        return False
    try:
        updated = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()
        return 0 <= age <= seconds
    except (TypeError, ValueError, OverflowError):
        return False


def _category_explicit_retry_environment(config: dict[str, Any], job: dict[str, Any]) -> dict[str, str]:
    """Keep the prior network path; an explicit retry never selects a new route."""
    mode = str(job.get("network_mode") or "")
    match = re.fullmatch(r"proxy:(http://127\.0\.0\.1:(?:7897|10808))", mode)
    if match is None:
        raise RuntimeError("显式单次重试缺少可核验的原本地代理路径，禁止更换线路")
    proxy = match.group(1)
    endpoint = str(config.get("base_url") or "").rstrip("/") + "/models"
    if not _category_endpoint_reachable(endpoint, proxy):
        raise RuntimeError("原代理路径不可用，显式单次重试不切换代理或直连")
    env = dict(os.environ)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = proxy
    env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1"
    env["PIPE_CATEGORY_NETWORK_MODE"] = mode
    return env


def _category_job_process_alive(job: dict[str, Any]) -> bool:
    from tools.category_process_identity import recorded_job_pid_is_running

    for key in ("pid", "worker_pid"):
        try:
            pid = int(job.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
        if pid > 0 and recorded_job_pid_is_running(pid, job):
            return True
    return False


def _safe_category_resume_identifier(value: str, label: str) -> str:
    identifier = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", identifier):
        raise RuntimeError(f"{label} 只能包含字母、数字、下划线和连字符")
    return identifier


def _validated_category_resume_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if the read-only resume core returns an inconsistent ledger."""

    list_aliases = {
        "success_target_ids": ("success_target_ids", "success_ids"),
        "exhausted_target_ids": ("exhausted_target_ids", "exhausted_ids"),
        "balance_recoverable_target_ids": (
            "balance_recoverable_target_ids",
            "balance_recoverable_ids",
        ),
        "unknown_target_ids": ("unknown_target_ids", "unknown_ids"),
        "unattempted_target_ids": ("unattempted_target_ids", "unattempted_ids"),
        "resumable_target_ids": ("resumable_target_ids", "resumable_ids"),
        "explicit_retry_target_ids": ("explicit_retry_target_ids", "explicit_retry_ids"),
    }
    map_aliases = {
        "attempts_used_by_target": ("attempts_used_by_target", "attempts_used"),
        "attempts_remaining_by_target": (
            "attempts_remaining_by_target",
            "attempts_remaining",
        ),
    }
    scalar_fields = (
        "requests_used",
        "remaining_max_requests",
        "cumulative_max_requests",
        "resume_plan_sha256",
        "frozen_manifest_sha256",
        "frozen_overlay_sha256",
        "events_sha256",
        "event_tail_sha256",
    )
    list_sources = {
        canonical: next((key for key in aliases if key in plan), None)
        for canonical, aliases in list_aliases.items()
    }
    map_sources = {
        canonical: next((key for key in aliases if key in plan), None)
        for canonical, aliases in map_aliases.items()
    }
    # ``balance_recoverable`` was added after the first resume ledger format.
    # Accept an old core plan as an empty class, while requiring every other
    # safety field.  New plans always emit the explicit list and bind it into
    # their resume-plan hash.
    optional_list_fields = {"balance_recoverable_target_ids", "explicit_retry_target_ids"}
    missing = [
        key
        for key, source in {**list_sources, **map_sources}.items()
        if source is None and key not in optional_list_fields
    ]
    missing.extend(key for key in scalar_fields if key not in plan)
    budget_key = next(
        (
            key
            for key in ("approved_request_budget", "request_budget", "budget")
            if key in plan
        ),
        None,
    )
    if budget_key is None:
        missing.append("approved_request_budget/request_budget")
    if missing:
        raise RuntimeError("续跑核心计划缺少安全字段：" + ", ".join(missing))

    normalized_lists: dict[str, list[str]] = {}
    for key, source in list_sources.items():
        if source is None:
            normalized_lists[key] = []
            continue
        values = plan[str(source)]
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or not value for value in values)
            or len(values) != len(set(values))
        ):
            raise RuntimeError(f"续跑核心计划字段 {key} 不是唯一目标编号列表")
        normalized_lists[key] = list(values)

    classification_fields = (
        "success_target_ids",
        "exhausted_target_ids",
        "balance_recoverable_target_ids",
        "unknown_target_ids",
        "unattempted_target_ids",
        "explicit_retry_target_ids",
    )
    classifications = [set(normalized_lists[key]) for key in classification_fields]
    for index, left in enumerate(classifications):
        for right in classifications[index + 1 :]:
            if left & right:
                raise RuntimeError("续跑目标分类存在重叠，已停止核算")
    classified_ids = set().union(*classifications)
    resumable_ids = set(normalized_lists["resumable_target_ids"])
    expected_resumable = (
        set(normalized_lists["balance_recoverable_target_ids"])
        | set(normalized_lists["unknown_target_ids"])
        | set(normalized_lists["unattempted_target_ids"])
        | set(normalized_lists["explicit_retry_target_ids"])
    )
    if resumable_ids != expected_resumable:
        raise RuntimeError(
            "可续跑目标必须恰好等于余额可恢复、未知目标与未尝试目标的并集"
        )

    normalized_maps: dict[str, dict[str, int]] = {}
    for key, source in map_sources.items():
        values = plan[str(source)]
        if not isinstance(values, dict) or set(values) != classified_ids:
            raise RuntimeError(f"续跑核心计划字段 {key} 与目标分类不一致")
        normalized: dict[str, int] = {}
        for target_id, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RuntimeError(f"续跑核心计划字段 {key} 包含无效次数")
            normalized[str(target_id)] = value
        normalized_maps[key] = normalized

    attempts_used = normalized_maps["attempts_used_by_target"]
    attempts_remaining = normalized_maps["attempts_remaining_by_target"]
    explicit_ids = normalized_lists["explicit_retry_target_ids"]
    if explicit_ids or "explicit_retry" in plan:
        retry = plan.get("explicit_retry")
        if (
            not isinstance(retry, dict)
            or not 1 <= len(explicit_ids) <= 2
            or set(explicit_ids) != resumable_ids
            or retry.get("max_workers") != 1
            or retry.get("stop_on_any_failure") is not True
            or retry.get("allow_key_failover") is not False
            or retry.get("retry_prompt_variant") != "original"
            or [row.get("generation_target_id") for row in retry.get("targets", [])] != explicit_ids
            or any(attempts_remaining[target] != 1 or attempts_used[target] != 1 for target in explicit_ids)
            or plan.get("max_attempts") != 2
        ):
            raise RuntimeError("显式单次重试未精确绑定原尝试、目标及串行停止边界")
    if any(attempts_remaining[target_id] != 0 for target_id in (
        set(normalized_lists["success_target_ids"])
        | set(normalized_lists["exhausted_target_ids"])
    )):
        raise RuntimeError("成功或已耗尽目标仍带有剩余尝试次数")
    if any(attempts_remaining[target_id] <= 0 for target_id in resumable_ids):
        raise RuntimeError("可续跑目标没有剩余尝试次数")
    if any(
        attempts_used[target_id] <= 0
        for target_id in (
            set(normalized_lists["balance_recoverable_target_ids"])
            | set(normalized_lists["unknown_target_ids"])
        )
    ):
        raise RuntimeError("余额可恢复或未知目标缺少历史请求证据")
    if any(
        attempts_used[target_id] != 0
        for target_id in normalized_lists["unattempted_target_ids"]
    ):
        raise RuntimeError("未尝试目标却带有历史请求次数")

    def nonnegative_integer(key: str) -> int:
        value = plan[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"续跑核心计划字段 {key} 必须是非负整数")
        return value

    requests_used = nonnegative_integer("requests_used")
    remaining_max = nonnegative_integer("remaining_max_requests")
    cumulative_max = nonnegative_integer("cumulative_max_requests")
    approved_budget = nonnegative_integer(str(budget_key))
    balance_failure_count_value = plan.get("balance_failure_request_count")
    if balance_failure_count_value is None:
        if list_sources["balance_recoverable_target_ids"] is not None:
            raise RuntimeError("余额恢复计划缺少 balance_failure_request_count")
        balance_failure_count = 0
    else:
        if (
            isinstance(balance_failure_count_value, bool)
            or not isinstance(balance_failure_count_value, int)
            or balance_failure_count_value < 0
        ):
            raise RuntimeError("balance_failure_request_count 必须是非负整数")
        balance_failure_count = balance_failure_count_value
    if balance_failure_count < len(
        normalized_lists["balance_recoverable_target_ids"]
    ):
        raise RuntimeError("余额失败请求数少于余额可恢复目标数")
    if requests_used != sum(attempts_used.values()):
        raise RuntimeError("已用请求数与逐目标尝试账本不一致")
    expected_remaining_max = sum(attempts_remaining.values())
    if "generation_profile" in plan:
        category_generation_profile.validate_profile(plan["generation_profile"], str(plan["category_id"]))
        if requests_used > approved_budget:
            raise RuntimeError("新4K续跑已用请求超过原预算")
        expected_remaining_max = min(expected_remaining_max, approved_budget - requests_used)
    if plan.get("schedule_amendment") is not None:
        amendment = plan["schedule_amendment"]
        if (
            not isinstance(amendment, dict)
            or amendment.get("strict_original_request_budget") != approved_budget
            or requests_used > approved_budget
        ):
            raise RuntimeError("调度变更没有绑定严格原始预算")
        expected_remaining_max = min(expected_remaining_max, approved_budget - requests_used)
    if plan.get("generation_migration") is not None:
        migration = plan["generation_migration"]
        cap = migration.get("prior_cumulative_request_cap") if isinstance(migration, dict) else None
        if type(cap) is not int or cap < requests_used or cap > approved_budget:
            raise RuntimeError("生成配置迁移缺少有效的前序累计上限")
        expected_remaining_max = min(expected_remaining_max, cap - requests_used)
    if plan.get("explicit_retry") is not None:
        cap = plan["explicit_retry"].get("prior_cumulative_request_cap")
        if type(cap) is not int or not requests_used <= cap <= approved_budget:
            raise RuntimeError("显式单次重试缺少前序累计请求上限")
        expected_remaining_max = min(expected_remaining_max, cap - requests_used)
        if expected_remaining_max != len(explicit_ids):
            raise RuntimeError("显式单次重试预算不足，禁止部分授权")
    if remaining_max != expected_remaining_max:
        raise RuntimeError("续跑最大请求数与逐目标剩余次数不一致")
    if cumulative_max != requests_used + remaining_max:
        raise RuntimeError("累计最大请求数不等于已用请求数加续跑最大请求数")
    additional_recovery_budget = max(0, cumulative_max - approved_budget)
    if additional_recovery_budget > balance_failure_count:
        raise RuntimeError("续跑累计上限超过原预算及可核验的余额失败请求抵扣")

    counts = plan.get("counts")
    if counts is not None:
        expected_counts = {
            "total": len(classified_ids),
            "success": len(normalized_lists["success_target_ids"]),
            "exhausted": len(normalized_lists["exhausted_target_ids"]),
            "balance_recoverable": len(
                normalized_lists["balance_recoverable_target_ids"]
            ),
            "unknown": len(normalized_lists["unknown_target_ids"]),
            "unattempted": len(normalized_lists["unattempted_target_ids"]),
            "resumable": len(normalized_lists["resumable_target_ids"]),
        }
        if explicit_ids or "explicit_retry" in plan:
            expected_counts["explicit_retry"] = len(explicit_ids)
        if not isinstance(counts, dict):
            raise RuntimeError("续跑核心计划 counts 与目标分类不一致")
        for key, value in expected_counts.items():
            if (
                key == "balance_recoverable"
                and list_sources["balance_recoverable_target_ids"] is None
                and key not in counts
            ):
                continue
            if counts.get(key) != value:
                raise RuntimeError("续跑核心计划 counts 与目标分类不一致")

    for key in (
        "resume_plan_sha256",
        "frozen_manifest_sha256",
        "frozen_overlay_sha256",
        "events_sha256",
        "event_tail_sha256",
    ):
        value = plan[key]
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise RuntimeError(f"续跑核心计划字段 {key} 不是有效 SHA-256")

    return {
        **plan,
        **normalized_lists,
        **normalized_maps,
        "approved_request_budget": approved_budget,
        "balance_failure_request_count": balance_failure_count,
        "additional_recovery_request_budget": additional_recovery_budget,
    }


def _build_category_image_resume_plan(
    batch_dir: Path,
    job_path: Path,
    license_path: Path,
) -> dict[str, Any]:
    """Delay-load the resume core so unrelated factory commands remain usable."""

    from tools.category_image_resume import build_resume_plan

    return build_resume_plan(batch_dir, job_path, license_path)


def _category_image_resume_context(
    category_id: str,
    job_id_value: str,
    batch_value: str | None,
    *,
    schedule_amendment_slots: list[int] | None = None,
    generation_migration_spec: dict[str, Any] | None = None,
    previous_authorization_id: str | None = None,
    explicit_retry_target_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve and revalidate every immutable input shared by resume commands."""

    job_id = _safe_category_resume_identifier(job_id_value, "job-id")
    batch_dir = category_active_batch_dir(category_id, batch_value)
    jobs_dir = category_image_production.jobs_dir(batch_dir).resolve()
    job_path = (jobs_dir / f"{job_id}.json").resolve()
    if job_path.parent != jobs_dir or not job_path.is_file():
        raise RuntimeError(f"找不到该活动批次的任务记录：{job_id}")
    job = load_json(job_path)
    if job.get("job_id") != job_id:
        raise RuntimeError("任务文件中的 job_id 与文件名不一致")
    if job.get("category_id") != category_id or job.get("project_id") != category_id:
        raise RuntimeError("任务记录与指定类目不一致")
    recorded_batch = Path(str(job.get("batch_dir") or "")).expanduser().resolve()
    if recorded_batch != batch_dir.resolve() or job.get("batch_id") != batch_dir.name:
        raise RuntimeError("任务记录与当前活动批次不一致")
    if _category_job_process_alive(job):
        raise RuntimeError("该任务进程仍在运行，不能核算或启动续跑")

    lock_path = category_image_production.production_dir(batch_dir) / "generation.lock"
    if lock_path.is_file():
        try:
            lock = load_json(lock_path)
            lock_pid = int(lock.get("pid", 0) or 0)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"生产锁文件无法安全识别：{lock_path}") from error
        if lock_pid > 0 and category_image_production.pid_is_running(lock_pid):
            raise RuntimeError(
                f"该批次仍有活动生产锁：{lock.get('job_id') or 'unknown'}"
            )

    license_id = _safe_category_resume_identifier(
        str(job.get("license_id") or ""), "任务中的 license-id"
    )
    production = category_image_production.production_dir(batch_dir).resolve()
    licenses_dir = (production / "licenses").resolve()
    license_path = (licenses_dir / f"{license_id}.json").resolve()
    if license_path.parent != licenses_dir or not license_path.is_file():
        raise RuntimeError("找不到该任务绑定的一次性许可证")
    license_data = load_json(license_path)
    if license_data.get("license_id") != license_id:
        raise RuntimeError("许可证内容与任务绑定的 license-id 不一致")
    if license_data.get("status") != "consumed" or license_data.get("one_time") is not True:
        raise RuntimeError("安全续跑只接受已消费的一次性原许可证")

    raw_plan = _build_category_image_resume_plan(batch_dir, job_path, license_path)
    if "generation_profile" in raw_plan and (
        schedule_amendment_slots is not None or generation_migration_spec is not None
        or explicit_retry_target_ids is not None or previous_authorization_id is not None
    ):
        raise RuntimeError("新4K续跑只继承原profile/adaptive/槽位，不使用旧迁移或显式重试侧车")
    retry_context: dict[str, Any] = {}
    if explicit_retry_target_ids is not None:
        from tools.category_explicit_retry import apply_explicit_retry

        if schedule_amendment_slots is not None or generation_migration_spec is not None:
            raise RuntimeError("显式原样单次重试不能同时改变调度、模型或凭据")
        if lock_path.exists() or job.get("status") != "completed_with_errors":
            raise RuntimeError("显式单次重试要求前任务失败终态且生产锁已释放")
        previous_id = _safe_category_resume_identifier(previous_authorization_id or "", "previous-authorization-id")
        if job.get("resume_authorization_id") != previous_id:
            raise RuntimeError("显式单次重试必须绑定当前最后一次续跑授权")
        previous_path = production / "resume_authorizations" / f"{previous_id}.json"
        previous_session_path = production / "resume_sessions" / f"{previous_id}.json"
        previous = load_json(previous_path)
        previous_session = load_json(previous_session_path)
        if (
            previous_session.get("status") != "completed_with_errors"
            or previous_session.get("pid") is not None
            or previous_session.get("authorization_id") != previous_id
            or previous_session.get("job_id") != job_id
            or previous_session.get("license_id") != license_id
            or previous_session.get("resume_plan_sha256") != previous.get("resume_plan_sha256")
        ):
            raise RuntimeError("前序会话身份、终态或退出状态不一致")
        events_path = production / f"events_{job_id}.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        if _sha256_file(events_path) != raw_plan["events_sha256"]:
            raise RuntimeError("显式单次重试核算期间事件账本变化")
        raw_plan = apply_explicit_retry(raw_plan, license_data, events, previous, explicit_retry_target_ids)
        retry_context = {
            "previous_session_path": previous_session_path,
            "previous_resume_session_sha256": _sha256_file(previous_session_path),
        }
    if schedule_amendment_slots is not None:
        from tools.category_resume_schedule import apply_schedule_amendment

        events_path = production / f"events_{job_id}.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        if _sha256_file(events_path) != raw_plan["events_sha256"]:
            raise RuntimeError("调度变更期间事件账本已变化")
        raw_plan = apply_schedule_amendment(raw_plan, license_data, events, schedule_amendment_slots)
    if generation_migration_spec is not None:
        from tools.category_resume_migration import apply_generation_migration

        if schedule_amendment_slots is None:
            raise RuntimeError("生成配置迁移必须显式绑定固定10路调度")
        previous_id = _safe_category_resume_identifier(previous_authorization_id or "", "previous-authorization-id")
        if job.get("resume_authorization_id") != previous_id:
            raise RuntimeError("生成配置迁移必须衔接当前任务的最后一次续跑授权")
        previous_path = production / "resume_authorizations" / f"{previous_id}.json"
        previous = load_json(previous_path)
        raw_plan = apply_generation_migration(raw_plan, license_data, events, previous, generation_migration_spec)
    resume_plan = _validated_category_resume_plan(raw_plan)
    identity = {
        "job_id": job_id,
        "license_id": license_id,
        "category_id": category_id,
        "batch_id": batch_dir.name,
    }
    for key, expected in identity.items():
        if key in resume_plan and resume_plan.get(key) != expected:
            raise RuntimeError(f"续跑核心计划与冻结任务身份不一致：{key}")
    return {
        "category_id": category_id,
        "job_id": job_id,
        "license_id": license_id,
        "batch_dir": batch_dir,
        "production_dir": production,
        "job_path": job_path,
        "job": job,
        "license_path": license_path,
        "license": license_data,
        "resume_plan": resume_plan,
        **retry_context,
    }


def _category_resume_context_for_args(args: argparse.Namespace) -> dict[str, Any]:
    """Only an explicit, plan-bound amendment may expand the original key set."""
    amendment = bool(getattr(args, "amend_concurrency", False))
    selected_slots = getattr(args, "api_key_slot", None)
    explicit_targets = getattr(args, "explicit_retry_target_id", None)
    if explicit_targets is not None:
        incompatible = (
            "migrate_model", "migrate_quality", "migrate_size", "credential_epoch",
            "rotate_key_slot", "accepted_source_size", "accepted_source_width_tolerance",
            "archive_stale_consumed_session",
        )
        if (
            amendment or selected_slots or (getattr(args, "max_workers", 1) or 1) != 1
            or any(getattr(args, name, None) for name in incompatible)
            or not getattr(args, "previous_authorization_id", None)
        ):
            raise RuntimeError("显式单次重试仅允许原样单路，并必须绑定前序授权；不能迁移/换槽/归档")
        return _category_image_resume_context(
            args.category, args.job_id, args.batch_dir,
            explicit_retry_target_ids=explicit_targets,
            previous_authorization_id=args.previous_authorization_id,
        )
    migration_values = {
        "model": getattr(args, "migrate_model", None),
        "quality": getattr(args, "migrate_quality", None),
        "api_size": getattr(args, "migrate_size", None),
        "credential_epoch": getattr(args, "credential_epoch", None),
        "rotated_slots": getattr(args, "rotate_key_slot", None),
    }
    previous_id = getattr(args, "previous_authorization_id", None)
    accepted_source_size = getattr(args, "accepted_source_size", None)
    source_width_tolerance = getattr(args, "accepted_source_width_tolerance", 0)
    if source_width_tolerance:
        if accepted_source_size != "2352x3520":
            raise RuntimeError("源宽度容差需要显式绑定 --accepted-source-size 2352x3520")
        migration_values["accepted_source_width_tolerance"] = source_width_tolerance
    has_migration = any(value is not None for value in migration_values.values()) or previous_id is not None or accepted_source_size is not None
    if accepted_source_size is not None:
        migration_values["accepted_source_size"] = accepted_source_size
        if migration_values["rotated_slots"] is None:
            migration_values["rotated_slots"] = []
    required_migration = ("model", "quality", "api_size", "credential_epoch")
    if has_migration and (
        not amendment or not previous_id
        or not all(migration_values[key] for key in required_migration)
        or (accepted_source_size is None and not migration_values["rotated_slots"])
    ):
        raise RuntimeError("迁移需要完整的模型/质量/尺寸/凭据版本/轮换槽位/前序授权及 --amend-concurrency")
    if not amendment:
        if selected_slots:
            raise RuntimeError("改变续跑槽位必须显式传入 --amend-concurrency")
        return _category_image_resume_context(args.category, args.job_id, args.batch_dir)
    if getattr(args, "max_workers", 1) != 10 or not selected_slots:
        raise RuntimeError("调度变更需要 --max-workers 10 和10个显式 --api-key-slot")
    migration_options = (
        {"generation_migration_spec": migration_values, "previous_authorization_id": previous_id}
        if has_migration else {}
    )
    return _category_image_resume_context(
        args.category, args.job_id, args.batch_dir,
        schedule_amendment_slots=selected_slots, **migration_options,
    )


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    """Create one JSON artifact with O_EXCL; never overwrite existing evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"续跑授权证据已存在，禁止覆盖：{path}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _write_bytes_exclusive_or_verify(path: Path, payload: bytes) -> None:
    """Create immutable byte evidence, or verify an identical interrupted copy."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise RuntimeError(f"现有崩溃归档副本与原证据字节不一致：{path}")
        return
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _category_resume_authorization_id(job_id: str, resume_plan_sha256: str) -> str:
    binding = _json_sha256(
        {"job_id": job_id, "resume_plan_sha256": resume_plan_sha256}
    )
    return f"resume-{binding[:24]}"


def _category_resume_requested_max_workers(
    args: argparse.Namespace,
    plan: dict[str, Any],
) -> int:
    """Accept only the two explicitly supported resume schedules."""

    requested = getattr(args, "max_workers", 1)
    if "generation_profile" in plan:
        frozen = plan["profile_max_workers"]
        if requested is not None and requested != frozen:
            raise RuntimeError("新4K续跑必须沿用原adaptive并发上限；省略--max-workers或填写原值")
        return int(frozen)
    if requested is None:
        requested = 1
    if isinstance(requested, bool) or requested not in {1, 10}:
        raise RuntimeError("续跑 --max-workers 只允许 1 或 10")
    max_workers = int(requested)
    if max_workers == 10 and len(plan["resumable_target_ids"]) < 10:
        raise RuntimeError("固定10路续跑至少需要10个可续跑目标")
    return max_workers


def _category_resume_policy(max_workers: int, plan: dict[str, Any] | None = None) -> str:
    if plan is not None and "generation_profile" in plan:
        return str(plan["profile_resume_policy"])
    if max_workers == 1:
        return CATEGORY_RESUME_SERIAL_POLICY
    if max_workers == 10:
        return CATEGORY_RESUME_FIXED_TEN_POLICY
    raise RuntimeError("续跑并发上限没有对应的冻结调度策略")


def _is_legacy_category_resume_parallel_authorization(
    authorization: dict[str, Any], plan: dict[str, Any]
) -> bool:
    """Recognize only the historical pre-policy, pre-balance 4-way schema."""

    return (
        authorization.get("max_workers") == 4
        and "resume_policy" not in authorization
        and all(
            key not in authorization
            for key in CATEGORY_RESUME_BALANCE_AUTHORIZATION_FIELDS
        )
        and not plan["balance_recoverable_target_ids"]
        and int(plan["balance_failure_request_count"]) == 0
        and int(plan["additional_recovery_request_budget"]) == 0
    )


def _category_resume_frozen_fixed_ten_slots(
    license_data: dict[str, Any],
) -> list[int]:
    """Select the exact ten slots already frozen by the original license."""

    raw_slots = license_data.get("api_key_slots")
    if not isinstance(raw_slots, list):
        raise RuntimeError("固定10路续跑要求原许可证冻结至少10个 API Key 槽位")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in raw_slots):
        raise RuntimeError("原许可证的 API Key 槽位格式无效")
    slots = [int(value) for value in raw_slots]
    if len(slots) != len(set(slots)) or any(value < 1 for value in slots):
        raise RuntimeError("原许可证的 API Key 槽位必须是唯一的正整数")
    selected_slots = slots[:10]
    if len(selected_slots) != 10:
        raise RuntimeError("固定10路续跑要求原许可证冻结至少10个 API Key 槽位")
    return selected_slots


def _category_resume_fixed_ten_slots(
    license_data: dict[str, Any],
    config: dict[str, Any],
) -> list[int]:
    """Validate ten frozen client slots locally without exposing credentials."""

    selected_slots = _category_resume_frozen_fixed_ten_slots(license_data)
    clients = category_image_production.openai_clients_by_slot(config, selected_slots)
    client_slots = [int(item[0]) for item in clients]
    if client_slots != selected_slots or len(clients) != 10:
        raise RuntimeError("固定10路续跑的10个客户端未全部就绪")
    return selected_slots


def _valid_stale_resume_archive(
    production: Path,
    session_path: Path,
    session: dict[str, Any],
    authorization_path: Path,
    authorization: dict[str, Any],
) -> bool:
    """Validate the immutable crash sidecar that permits ignoring one dead session."""

    authorization_id = str(authorization.get("authorization_id") or "")
    archive_root = (production / "resume_crash_archives").resolve()
    candidates = list(
        archive_root.glob(f"{authorization_id}_*/archive.json")
        if archive_root.is_dir()
        else []
    )
    if len(candidates) != 1:
        return False
    archive_path = candidates[0].resolve()
    if archive_root not in archive_path.parents:
        return False
    try:
        archive = load_json(archive_path)
        session_pid = int(session.get("pid", 0) or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    expected = {
        "schema_version": 1,
        "kind": "stale-consumed-resume-crash-archive",
        "authorization_id": authorization_id,
        "job_id": session.get("job_id"),
        "license_id": session.get("license_id"),
        "category_id": session.get("category_id"),
        "batch_id": session.get("batch_id"),
        "authorization_file": str(authorization_path),
        "authorization_sha256": _sha256_file(authorization_path),
        "session_file": str(session_path),
        "session_sha256": _sha256_file(session_path),
        "dead_worker_pid": session_pid,
    }
    if any(archive.get(key) != value for key, value in expected.items()):
        return False
    if (
        authorization.get("status") != "consumed"
        or authorization.get("one_time") is not True
        or session_pid <= 0
        or category_image_production.pid_is_running(session_pid)
    ):
        return False
    copies = archive.get("immutable_copies")
    if not isinstance(copies, dict):
        return False
    archive_dir = archive_path.parent
    required_labels = ("authorization", "session", "events", "job", "license", "log")
    expected_copy_names = {
        "authorization": "authorization.json",
        "session": "session.json",
        "events": "events.jsonl",
        "job": "job.json",
        "license": "license.json",
        "log": "worker.log",
    }
    for label in required_labels:
        row = copies.get(label)
        if not isinstance(row, dict):
            return False
        if row.get("name") != expected_copy_names[label]:
            return False
        copy_path = (archive_dir / str(row.get("name") or "")).resolve()
        if copy_path.parent != archive_dir or not copy_path.is_file():
            return False
        if row.get("source") != archive.get(f"{label}_file"):
            return False
        if row.get("size") != copy_path.stat().st_size:
            return False
        digest = _sha256_file(copy_path)
        if digest != row.get("sha256"):
            return False
        if archive.get(f"{label}_sha256") != digest:
            return False
    event_copy = (archive_dir / str(copies["events"]["name"])).resolve()
    event_lines = [line for line in event_copy.read_bytes().splitlines() if line.strip()]
    if (
        not event_lines
        or archive.get("detected_events_sha256") != archive.get("events_sha256")
        or archive.get("detected_event_tail_sha256")
        != hashlib.sha256(event_lines[-1]).hexdigest()
    ):
        return False
    try:
        cap = int(archive.get("authorization_cumulative_request_cap", -1))
        detected_requests = int(archive.get("detected_requests_used", -1))
    except (TypeError, ValueError):
        return False
    if cap != int(authorization.get("approved_cumulative_request_budget", -2)):
        return False
    if detected_requests < int(authorization.get("requests_used", -1)) or detected_requests > cap:
        return False
    if not isinstance(archive.get("open_reserved_requests"), list):
        return False
    event_rows: list[dict[str, Any]] = []
    try:
        event_rows = [
            json.loads(line)
            for line in event_copy.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    reserved: dict[int, dict[str, Any]] = {}
    terminal_numbers: set[int] = set()
    for event in event_rows:
        if event.get("authorization_id") != authorization_id:
            continue
        number = event.get("request_number")
        if isinstance(number, bool) or not isinstance(number, int):
            continue
        if event.get("status") == "request_reserved":
            reserved[number] = {
                "request_number": number,
                "generation_target_id": event.get("generation_target_id"),
                "attempt": event.get("attempt"),
                "api_key_slot": event.get("api_key_slot"),
            }
        elif event.get("status") in {"generated", "request_failed"}:
            terminal_numbers.add(number)
    expected_open = [
        reserved[number] for number in sorted(set(reserved) - terminal_numbers)
    ]
    if archive.get("open_reserved_requests") != expected_open:
        return False
    lock_row = copies.get("lock")
    if lock_row is not None:
        if not isinstance(lock_row, dict):
            return False
        if lock_row.get("name") != "generation.lock.json":
            return False
        lock_copy = (archive_dir / str(lock_row.get("name") or "")).resolve()
        if lock_copy.parent != archive_dir or not lock_copy.is_file():
            return False
        if lock_row.get("source") != archive.get("lock_file"):
            return False
        if lock_row.get("size") != lock_copy.stat().st_size:
            return False
        lock_digest = _sha256_file(lock_copy)
        if lock_digest != lock_row.get("sha256") or archive.get("lock_sha256") != lock_digest:
            return False
    return True


def _require_no_active_resume_session(
    authorization_dir: Path,
    session_dir: Path,
    job_id: str,
    license_id: str,
) -> None:
    for path in authorization_dir.glob("*.json") if authorization_dir.is_dir() else []:
        try:
            payload = load_json(path)
        except Exception as error:
            raise RuntimeError(f"已有续跑授权证据无法识别：{path}") from error
        if (
            payload.get("job_id") == job_id
            and payload.get("license_id") == license_id
            and payload.get("status") == "active"
        ):
            raise RuntimeError(
                f"该任务已有未消费的续跑授权，禁止重复启动：{path}"
            )
    active_statuses = {
        "queued",
        "starting",
        "running",
        "waiting_for_api",
        "resume_running",
        "resume_waiting_for_api",
    }
    for path in session_dir.glob("*.json") if session_dir.is_dir() else []:
        try:
            payload = load_json(path)
        except Exception as error:
            raise RuntimeError(f"已有续跑会话无法识别：{path}") from error
        if (
            payload.get("job_id") == job_id
            and payload.get("license_id") == license_id
            and payload.get("status") in active_statuses
        ):
            authorization_id = _safe_category_resume_identifier(
                str(payload.get("authorization_id") or ""),
                "活动会话 authorization_id",
            )
            authorization_path = (
                authorization_dir / f"{authorization_id}.json"
            ).resolve()
            if authorization_path.parent != authorization_dir or not authorization_path.is_file():
                raise RuntimeError("活动续跑会话缺少固定授权文件")
            authorization = load_json(authorization_path)
            production = authorization_dir.parent.resolve()
            if _valid_stale_resume_archive(
                production,
                path.resolve(),
                payload,
                authorization_path,
                authorization,
            ):
                continue
            raise RuntimeError(f"该任务已有续跑会话，禁止启动第二个 worker：{path}")


def _stale_consumed_resume_session(
    context: dict[str, Any],
) -> dict[str, Any] | None:
    """Find one dead worker whose one-time resume authorization was consumed."""

    production = Path(context["production_dir"])
    session_dir = (production / "resume_sessions").resolve()
    authorization_dir = (production / "resume_authorizations").resolve()
    active_statuses = {
        "starting",
        "running",
        "waiting_for_api",
        "resume_running",
        "resume_waiting_for_api",
    }
    matches: list[dict[str, Any]] = []
    for session_path in session_dir.glob("*.json") if session_dir.is_dir() else []:
        session = load_json(session_path)
        if (
            session.get("job_id") != context["job_id"]
            or session.get("license_id") != context["license_id"]
            or session.get("status") not in active_statuses
        ):
            continue
        authorization_id = _safe_category_resume_identifier(
            str(session.get("authorization_id") or ""),
            "残留会话 authorization_id",
        )
        authorization_path = (
            authorization_dir / f"{authorization_id}.json"
        ).resolve()
        if (
            authorization_path.parent != authorization_dir
            or not authorization_path.is_file()
            or session_path.resolve()
            != (session_dir / f"{authorization_id}.json").resolve()
        ):
            raise RuntimeError("残留续跑会话没有绑定固定授权/会话路径")
        authorization = load_json(authorization_path)
        expected = {
            "schema_version": 1,
            "kind": "category-image-resume-authorization",
            "authorization_id": authorization_id,
            "status": "consumed",
            "one_time": True,
            "job_id": context["job_id"],
            "license_id": context["license_id"],
            "category_id": context["category_id"],
            "batch_id": context["batch_dir"].name,
        }
        mismatches = [
            key for key, value in expected.items() if authorization.get(key) != value
        ]
        if mismatches:
            raise RuntimeError(
                "活动状续跑会话没有匹配的已消费授权：" + ", ".join(mismatches)
            )
        if session.get("resume_plan_sha256") != authorization.get(
            "resume_plan_sha256"
        ):
            raise RuntimeError("残留会话与已消费授权的续跑计划不一致")
        if session.get("authorization_file") != str(authorization_path):
            raise RuntimeError("残留会话 authorization_file 与固定路径不一致")
        if _valid_stale_resume_archive(
            production,
            session_path.resolve(),
            session,
            authorization_path,
            authorization,
        ):
            # A fully archived old generation may be ignored only after its
            # operational stale lock has also been removed.  If the archive
            # write succeeded but the process died before CAS-unlink, return
            # it for idempotent reconciliation instead of silently skipping.
            lock_path = production / "generation.lock"
            if not lock_path.is_file():
                continue
            try:
                archived_lock = load_json(lock_path)
                archived_lock_pid = int(archived_lock.get("pid", 0) or 0)
                archived_session_pid = int(session.get("pid", 0) or 0)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                raise RuntimeError("现存生产锁无法与已归档续跑会话安全核对") from error
            if archived_lock_pid != archived_session_pid:
                # The lock belongs to a later generation.  The immutable old
                # session remains evidence, but must not be counted again.
                continue
        try:
            session_pid = int(session.get("pid", 0) or 0)
        except (TypeError, ValueError) as error:
            raise RuntimeError("残留续跑会话 PID 无效") from error
        if session_pid <= 0 or category_image_production.pid_is_running(session_pid):
            raise RuntimeError("续跑会话仍有活动 worker 或 PID 无效，禁止归档")
        for key in ("worker_pid",):
            try:
                worker_pid = int(context["job"].get(key, 0) or 0)
            except (TypeError, ValueError) as error:
                raise RuntimeError(f"原任务 {key} 无效") from error
            if worker_pid > 0 and category_image_production.pid_is_running(worker_pid):
                raise RuntimeError(f"原任务 {key} 仍在运行，禁止归档残留会话")
        terminal_path = (
            production / "resume_summaries" / f"{authorization_id}.json"
        ).resolve()
        if terminal_path.is_file():
            raise RuntimeError("续跑会话已有终态证据，不能标记为外部中断")
        if int(context["resume_plan"]["requests_used"]) < int(
            authorization.get("requests_used", -1)
        ):
            raise RuntimeError("当前请求账本早于已消费续跑授权，禁止归档")
        cumulative_cap = int(
            authorization.get("approved_cumulative_request_budget", -1)
        )
        current_requests = int(context["resume_plan"]["requests_used"])
        if cumulative_cap < 0 or current_requests > cumulative_cap:
            raise RuntimeError("当前请求账本超过已消费续跑授权累计上限")
        events_path = (
            production / f"events_{context['job_id']}.jsonl"
        ).resolve()
        if not events_path.is_file():
            raise RuntimeError("残留续跑会话缺少原事件账本")
        if _sha256_file(events_path) != context["resume_plan"]["events_sha256"]:
            raise RuntimeError("事件账本与当前冻结续跑计划哈希不一致")
        log_path = Path(str(session.get("log_file") or "")).expanduser().resolve()
        expected_log = (production / "logs" / f"{authorization_id}.log").resolve()
        if log_path != expected_log or not log_path.is_file():
            raise RuntimeError("残留续跑会话没有绑定固定日志")
        try:
            event_rows = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError("残留续跑事件账本无法安全解析") from error
        reserved: dict[int, dict[str, Any]] = {}
        terminal_request_numbers: set[int] = set()
        for event in event_rows:
            if event.get("authorization_id") != authorization_id:
                continue
            request_number = event.get("request_number")
            if isinstance(request_number, bool) or not isinstance(request_number, int):
                if event.get("status") in {"request_reserved", "generated", "request_failed"}:
                    raise RuntimeError("续跑请求事件缺少有效 request_number")
                continue
            if event.get("status") == "request_reserved":
                if request_number in reserved:
                    raise RuntimeError("续跑事件含重复 request_reserved 编号")
                reserved[request_number] = {
                    "request_number": request_number,
                    "generation_target_id": event.get("generation_target_id"),
                    "attempt": event.get("attempt"),
                    "api_key_slot": event.get("api_key_slot"),
                }
            elif event.get("status") in {"generated", "request_failed"}:
                terminal_request_numbers.add(request_number)
        open_reservations = [
            reserved[number]
            for number in sorted(set(reserved) - terminal_request_numbers)
        ]
        matches.append(
            {
                "authorization_id": authorization_id,
                "authorization_path": authorization_path,
                "authorization": authorization,
                "session_path": session_path.resolve(),
                "session": session,
                "session_pid": session_pid,
                "events_path": events_path,
                "log_path": log_path,
                "open_reservations": open_reservations,
                "cumulative_cap": cumulative_cap,
            }
        )
    if len(matches) > 1:
        raise RuntimeError("同一任务存在多个活动状残留续跑会话，禁止自动归档")
    if not matches:
        return None

    lock_path = production / "generation.lock"
    lock_payload: dict[str, Any] | None = None
    if lock_path.is_file():
        try:
            lock_payload = load_json(lock_path)
            lock_pid = int(lock_payload.get("pid", 0) or 0)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("残留生产锁无法安全识别") from error
        if lock_payload.get("job_id") != context["job_id"]:
            raise RuntimeError("残留生产锁属于其他任务，禁止归档续跑会话")
        if lock_pid != int(matches[0]["session_pid"]):
            raise RuntimeError("残留生产锁 PID 与死亡续跑会话不一致")
        if lock_pid > 0 and category_image_production.pid_is_running(lock_pid):
            raise RuntimeError("残留生产锁 PID 仍在运行，禁止归档续跑会话")
    matches[0]["lock_path"] = lock_path.resolve()
    matches[0]["lock_payload"] = lock_payload
    matches[0]["stale_session_kind"] = "resume"
    return matches[0]


def _stale_consumed_original_session(
    context: dict[str, Any],
) -> dict[str, Any] | None:
    """Recognize one dead original worker whose one-time license was consumed."""

    production = Path(context["production_dir"])
    lock_path = (production / "generation.lock").resolve()
    if not lock_path.is_file():
        return None
    try:
        lock_payload = load_json(lock_path)
        lock_pid = int(lock_payload.get("pid", 0) or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("现存死亡生产锁无法安全识别") from error
    if lock_payload.get("job_id") != context["job_id"]:
        raise RuntimeError("现存死亡生产锁属于其他任务，禁止继续")
    if lock_pid <= 0 or category_image_production.pid_is_running(lock_pid):
        raise RuntimeError("原生产锁 PID 无效或仍在运行，禁止归档")

    job = context["job"]
    active_statuses = {
        "starting",
        "running",
        "waiting_for_api",
    }
    if job.get("status") not in active_statuses:
        raise RuntimeError("现存死亡生产锁对应的原任务不是可归档活动状态")
    try:
        worker_pid = int(job.get("worker_pid", 0) or 0)
    except (TypeError, ValueError) as error:
        raise RuntimeError("原任务 worker_pid 无效") from error
    if worker_pid != lock_pid:
        raise RuntimeError("现存死亡生产锁 PID 与原任务 worker_pid 不一致")
    for key in ("pid", "worker_pid", "launcher_pid"):
        try:
            process_pid = int(job.get(key, 0) or 0)
        except (TypeError, ValueError) as error:
            raise RuntimeError(f"原任务 {key} 无效") from error
        if process_pid > 0 and category_image_production.pid_is_running(process_pid):
            raise RuntimeError(f"原任务 {key} 仍在运行，禁止归档")

    summary_path = (production / "summaries" / f"{context['job_id']}.json").resolve()
    if summary_path.is_file():
        raise RuntimeError("原任务已经存在终态摘要，不能标记为外部中断")
    events_path = (production / f"events_{context['job_id']}.jsonl").resolve()
    if not events_path.is_file():
        raise RuntimeError("死亡原任务缺少事件账本")
    plan = context["resume_plan"]
    if _sha256_file(events_path) != plan["events_sha256"]:
        raise RuntimeError("死亡原任务事件账本与当前冻结续跑计划不一致")
    log_path = Path(str(job.get("log_file") or "")).expanduser().resolve()
    expected_log = (production / "logs" / f"{context['job_id']}.log").resolve()
    if log_path != expected_log or not log_path.is_file():
        raise RuntimeError("死亡原任务没有绑定固定日志")
    current_requests = int(plan["requests_used"])
    if int(job.get("requests_used", -1)) != current_requests or int(
        context["license"].get("requests_used", -1)
    ) != current_requests:
        raise RuntimeError("死亡原任务、许可证与续跑请求账本不一致")

    try:
        event_rows = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("死亡原任务事件账本无法安全解析") from error
    reserved: dict[int, dict[str, Any]] = {}
    terminal_request_numbers: set[int] = set()
    for event in event_rows:
        request_number = event.get("request_number")
        if isinstance(request_number, bool) or not isinstance(request_number, int):
            if event.get("status") in {"request_reserved", "generated", "request_failed"}:
                raise RuntimeError("死亡原任务请求事件缺少有效 request_number")
            continue
        if event.get("status") == "request_reserved":
            if request_number in reserved:
                raise RuntimeError("死亡原任务事件含重复 request_reserved 编号")
            reserved[request_number] = {
                "request_number": request_number,
                "generation_target_id": event.get("generation_target_id"),
                "attempt": event.get("attempt"),
                "api_key_slot": event.get("api_key_slot"),
            }
        elif event.get("status") in {"generated", "request_failed"}:
            terminal_request_numbers.add(request_number)
    open_reservations = [
        reserved[number]
        for number in sorted(set(reserved) - terminal_request_numbers)
    ]
    return {
        "stale_session_kind": "original",
        "events_path": events_path,
        "log_path": log_path,
        "lock_path": lock_path,
        "lock_payload": lock_payload,
        "session_pid": lock_pid,
        "open_reservations": open_reservations,
    }


def _archive_stale_consumed_original_session(
    context: dict[str, Any],
    stale: dict[str, Any],
) -> Path:
    """Archive a dead original worker before removing its operational lock."""

    production = Path(context["production_dir"])
    plan = context["resume_plan"]
    archive_root = (production / "resume_crash_archives").resolve()
    archive_key = _json_sha256(
        {"kind": "original", "job_id": context["job_id"]}
    )[:24]
    archive_dir = (
        archive_root / f"original-{archive_key}_{str(plan['resume_plan_sha256'])[:16]}"
    ).resolve()
    archive_path = (archive_dir / "archive.json").resolve()
    if archive_dir.parent != archive_root or archive_path.parent != archive_dir:
        raise RuntimeError("死亡原任务崩溃归档路径越界")

    source_paths = {
        "job": Path(context["job_path"]),
        "license": Path(context["license_path"]),
        "events": Path(stale["events_path"]),
        "log": Path(stale["log_path"]),
        "lock": Path(stale["lock_path"]),
    }
    copy_names = {
        "job": "job.json",
        "license": "license.json",
        "events": "events.jsonl",
        "log": "worker.log",
        "lock": "generation.lock.json",
    }
    source_bytes: dict[str, bytes] = {}
    immutable_copies: dict[str, dict[str, Any]] = {}
    for label, source in source_paths.items():
        if not source.is_file():
            raise RuntimeError(f"死亡原任务崩溃归档缺少原文件：{source}")
        payload = source.read_bytes()
        source_bytes[label] = payload
        digest = hashlib.sha256(payload).hexdigest()
        copy_path = (archive_dir / copy_names[label]).resolve()
        if copy_path.parent != archive_dir:
            raise RuntimeError("死亡原任务崩溃证据副本路径越界")
        _write_bytes_exclusive_or_verify(copy_path, payload)
        immutable_copies[label] = {
            "source": str(source.resolve()),
            "name": copy_names[label],
            "sha256": digest,
            "size": len(payload),
        }

    archive_binding = {
        "schema_version": 1,
        "kind": "stale-consumed-original-crash-archive",
        "job_id": context["job_id"],
        "license_id": context["license_id"],
        "category_id": context["category_id"],
        "batch_id": context["batch_dir"].name,
        "reason": "worker_disappeared_after_consuming_original_license",
        "detected_resume_plan_sha256": plan["resume_plan_sha256"],
        "detected_requests_used": int(plan["requests_used"]),
        "detected_events_sha256": plan["events_sha256"],
        "detected_event_tail_sha256": plan["event_tail_sha256"],
        "job_file": str(Path(context["job_path"]).resolve()),
        "job_sha256": immutable_copies["job"]["sha256"],
        "license_file": str(Path(context["license_path"]).resolve()),
        "license_sha256": immutable_copies["license"]["sha256"],
        "events_file": str(Path(stale["events_path"]).resolve()),
        "events_sha256": immutable_copies["events"]["sha256"],
        "log_file": str(Path(stale["log_path"]).resolve()),
        "log_sha256": immutable_copies["log"]["sha256"],
        "lock_file": str(Path(stale["lock_path"]).resolve()),
        "lock_sha256": immutable_copies["lock"]["sha256"],
        "lock_before": stale["lock_payload"],
        "dead_worker_pid": int(stale["session_pid"]),
        "open_reserved_requests": list(stale["open_reservations"]),
        "immutable_copies": immutable_copies,
    }
    if archive_path.is_file():
        existing = load_json(archive_path)
        for key, expected in archive_binding.items():
            if existing.get(key) != expected:
                raise RuntimeError("现有死亡原任务崩溃归档与当前冻结证据不一致")
    else:
        payload = dict(archive_binding)
        payload["archived_at"] = datetime.now(timezone.utc).isoformat()
        _write_json_exclusive(archive_path, payload)

    lock_path = Path(stale["lock_path"])
    if not lock_path.is_file() or lock_path.read_bytes() != source_bytes["lock"]:
        raise RuntimeError("死亡原任务锁在归档过程中发生变化，禁止移除")
    current_lock = load_json(lock_path)
    lock_pid = int(current_lock.get("pid", 0) or 0)
    if (
        current_lock != stale["lock_payload"]
        or lock_pid != int(stale["session_pid"])
        or category_image_production.pid_is_running(lock_pid)
    ):
        raise RuntimeError("死亡原任务锁 CAS 核验失败，禁止移除")
    lock_path.unlink()
    return archive_path


def _archive_stale_consumed_resume_session(
    context: dict[str, Any],
    stale: dict[str, Any],
) -> Path:
    """Copy all crash evidence immutably; never rewrite the old auth/session/events."""

    production = Path(context["production_dir"])
    plan = context["resume_plan"]
    authorization_id = str(stale["authorization_id"])
    archive_root = (production / "resume_crash_archives").resolve()
    archive_dir = (
        archive_root
        / f"{authorization_id}_{str(plan['resume_plan_sha256'])[:16]}"
    ).resolve()
    archive_path = (archive_dir / "archive.json").resolve()
    if archive_dir.parent != archive_root or archive_path.parent != archive_dir:
        raise RuntimeError("残留续跑崩溃归档路径越界")

    # If a prior attempt already wrote and validated the immutable archive,
    # and then crashed after its CAS lock removal but before creating the new
    # authorization, simply reuse that archive.  This closes the only
    # destructive-operation idempotency window.
    if archive_path.is_file() and _valid_stale_resume_archive(
        production,
        Path(stale["session_path"]),
        stale["session"],
        Path(stale["authorization_path"]),
        stale["authorization"],
    ):
        lock_path = Path(stale["lock_path"])
        if not lock_path.exists():
            return archive_path

    source_paths: dict[str, Path] = {
        "authorization": Path(stale["authorization_path"]),
        "session": Path(stale["session_path"]),
        "events": Path(stale["events_path"]),
        "job": Path(context["job_path"]),
        "license": Path(context["license_path"]),
        "log": Path(stale["log_path"]),
    }
    copy_names = {
        "authorization": "authorization.json",
        "session": "session.json",
        "events": "events.jsonl",
        "job": "job.json",
        "license": "license.json",
        "log": "worker.log",
    }
    if stale.get("lock_payload") is not None:
        source_paths["lock"] = Path(stale["lock_path"])
        copy_names["lock"] = "generation.lock.json"

    source_bytes: dict[str, bytes] = {}
    immutable_copies: dict[str, dict[str, Any]] = {}
    for label, source in source_paths.items():
        if not source.is_file():
            raise RuntimeError(f"残留续跑崩溃归档缺少原文件：{source}")
        payload = source.read_bytes()
        source_bytes[label] = payload
        digest = hashlib.sha256(payload).hexdigest()
        copy_path = (archive_dir / copy_names[label]).resolve()
        if copy_path.parent != archive_dir:
            raise RuntimeError("残留续跑崩溃证据副本路径越界")
        _write_bytes_exclusive_or_verify(copy_path, payload)
        immutable_copies[label] = {
            "source": str(source.resolve()),
            "name": copy_names[label],
            "sha256": digest,
            "size": len(payload),
        }

    archive_binding = {
        "schema_version": 1,
        "kind": "stale-consumed-resume-crash-archive",
        "authorization_id": authorization_id,
        "job_id": context["job_id"],
        "license_id": context["license_id"],
        "category_id": context["category_id"],
        "batch_id": context["batch_dir"].name,
        "reason": "worker_disappeared_after_consuming_resume_authorization",
        "detected_resume_plan_sha256": plan["resume_plan_sha256"],
        "detected_requests_used": int(plan["requests_used"]),
        "detected_events_sha256": plan["events_sha256"],
        "detected_event_tail_sha256": plan["event_tail_sha256"],
        "authorization_file": str(Path(stale["authorization_path"]).resolve()),
        "authorization_sha256": immutable_copies["authorization"]["sha256"],
        "authorization_cumulative_request_cap": int(stale["cumulative_cap"]),
        "session_file": str(Path(stale["session_path"]).resolve()),
        "session_sha256": immutable_copies["session"]["sha256"],
        "events_file": str(Path(stale["events_path"]).resolve()),
        "events_sha256": immutable_copies["events"]["sha256"],
        "job_file": str(Path(context["job_path"]).resolve()),
        "job_sha256": immutable_copies["job"]["sha256"],
        "license_file": str(Path(context["license_path"]).resolve()),
        "license_sha256": immutable_copies["license"]["sha256"],
        "log_file": str(Path(stale["log_path"]).resolve()),
        "log_sha256": immutable_copies["log"]["sha256"],
        "dead_worker_pid": int(stale["session_pid"]),
        "open_reserved_requests": list(stale["open_reservations"]),
        "immutable_copies": immutable_copies,
        "lock_file": (
            str(Path(stale["lock_path"]).resolve())
            if stale.get("lock_payload") is not None
            else None
        ),
        "lock_sha256": (
            immutable_copies["lock"]["sha256"]
            if "lock" in immutable_copies
            else None
        ),
        "lock_before": stale.get("lock_payload"),
    }
    if archive_path.is_file():
        existing = load_json(archive_path)
        for key, expected in archive_binding.items():
            if existing.get(key) != expected:
                raise RuntimeError("现有残留续跑崩溃归档与当前冻结证据不一致")
    else:
        payload = dict(archive_binding)
        payload["archived_at"] = datetime.now(timezone.utc).isoformat()
        _write_json_exclusive(archive_path, payload)

    # Only the operational stale lock may be removed. Revalidate its exact
    # bytes and dead PID after the immutable sidecar exists (CAS-like unlink).
    if stale.get("lock_payload") is not None:
        lock_path = Path(stale["lock_path"])
        if not lock_path.is_file() or lock_path.read_bytes() != source_bytes["lock"]:
            raise RuntimeError("残留生产锁在归档过程中发生变化，禁止移除")
        current_lock = load_json(lock_path)
        lock_pid = int(current_lock.get("pid", 0) or 0)
        if (
            current_lock != stale["lock_payload"]
            or lock_pid != int(stale["session_pid"])
            or category_image_production.pid_is_running(lock_pid)
        ):
            raise RuntimeError("残留生产锁CAS核验失败，禁止移除")
        lock_path.unlink()
    return archive_path


def command_resume_category_images(args: argparse.Namespace) -> int:
    """Authorize once and start only the dedicated cumulative-ledger worker."""

    _category_utf8_console()
    try:
        if not args.confirm_resume:
            raise RuntimeError("续跑必须由用户明确传入 --confirm-resume")
        if not args.confirm_paid:
            raise RuntimeError("续跑可能继续产生费用，必须明确传入 --confirm-paid")
        if not args.confirm_third_party:
            raise RuntimeError("继续使用第三方中转必须明确传入 --confirm-third-party")
        supplied_hash = str(args.resume_plan_sha256 or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", supplied_hash):
            raise RuntimeError("resume-plan-sha256 必须是64位小写 SHA-256")

        context = _category_resume_context_for_args(args)
        plan = context["resume_plan"]
        license_data = context["license"]
        if supplied_hash != plan["resume_plan_sha256"]:
            raise RuntimeError(
                "续跑计划校验码已变化；请重新运行 category-image-resume-plan 后再确认"
            )
        if plan.get("provider") == "relay" and (
            license_data.get("third_party_confirmed") is not True
        ):
            raise RuntimeError("原许可证没有绑定第三方中转信任确认，禁止续跑")
        if not plan["resumable_target_ids"]:
            raise RuntimeError("当前冻结任务没有可续跑目标")
        max_workers = _category_resume_requested_max_workers(args, plan)
        resume_policy = _category_resume_policy(max_workers, plan)

        original_plan_sha256 = str(license_data.get("plan_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", original_plan_sha256):
            raise RuntimeError("原许可证缺少有效 plan_sha256")
        original_budget = int(license_data.get("approved_request_budget", -1))
        if original_budget != int(plan["approved_request_budget"]):
            raise RuntimeError("原许可证预算与续跑账本不一致")

        production = Path(context["production_dir"])
        authorization_dir = (production / "resume_authorizations").resolve()
        session_dir = (production / "resume_sessions").resolve()
        authorization_id = _category_resume_authorization_id(
            context["job_id"], supplied_hash
        )
        authorization_path = (
            authorization_dir / f"{authorization_id}.json"
        ).resolve()
        session_path = (session_dir / f"{authorization_id}.json").resolve()
        if authorization_path.parent != authorization_dir or session_path.parent != session_dir:
            raise RuntimeError("续跑授权或会话路径越出固定目录")
        if authorization_path.exists():
            existing = load_json(authorization_path)
            if (
                existing.get("resume_plan_sha256") == supplied_hash
                and existing.get("status") == "active"
            ):
                raise RuntimeError(
                    f"同一续跑计划已有未消费授权，禁止覆盖：{authorization_path}"
                )
            raise RuntimeError(f"同一续跑计划的授权证据已存在：{authorization_path}")
        if session_path.exists():
            raise RuntimeError(f"同一续跑计划的会话证据已存在：{session_path}")
        stale = _stale_consumed_resume_session(context)
        if stale is None:
            stale = _stale_consumed_original_session(context)
        confirm_stale = bool(
            getattr(args, "archive_stale_consumed_session", False)
        )
        if stale is not None and not confirm_stale:
            if stale.get("stale_session_kind") == "original":
                raise RuntimeError(
                    "检测到已消费原许可证对应的死亡生产会话；重新核算后如需续跑，"
                    "必须明确传入 --archive-stale-consumed-session"
                )
            raise RuntimeError(
                "检测到已消费授权对应的死亡续跑会话；重新核算后如需新授权，"
                "必须明确传入 --archive-stale-consumed-session"
            )
        if stale is None and confirm_stale:
            raise RuntimeError("没有可归档的已消费授权残留会话")
        config = _category_effective_config()
        profile = plan.get("generation_profile")
        if profile is not None:
            config = category_generation_profile.from_license(config, context["category_id"], license_data)
        generation_migration = plan.get("generation_migration")
        if generation_migration is not None:
            config = dict(config)
            config.update(generation_migration["new_generation"])
        config_bindings = {
            "provider": config.get("provider"),
            "model": config.get("model"),
            "quality": config.get("quality"),
            "size": config.get("api_size"),
        }
        for key, current in config_bindings.items():
            frozen = plan.get(key) or license_data.get(key)
            if generation_migration is not None and key in {"model", "quality", "size"}:
                frozen = generation_migration["new_generation"]["api_size" if key == "size" else key]
            if current != frozen:
                raise RuntimeError(
                    f"当前图片配置 {key}={current!r} 与冻结许可证 {frozen!r} 不一致"
                )
        current_base_url = str(config.get("base_url") or "").rstrip("/")
        frozen_base_url = str(license_data.get("base_url") or "").rstrip("/")
        if current_base_url != frozen_base_url:
            raise RuntimeError("当前中转地址与冻结许可证不一致")
        amendment = plan.get("schedule_amendment")
        explicit_retry = plan.get("explicit_retry")
        if profile is not None:
            fixed_ten_slots = list(plan["profile_api_key_slots"])
        elif explicit_retry is not None:
            fixed_ten_slots = list(dict.fromkeys(row["api_key_slot"] for row in explicit_retry["targets"]))
            clients = category_image_production.openai_clients_by_slot(config, fixed_ten_slots)
            if [int(pair[0]) for pair in clients] != fixed_ten_slots:
                raise RuntimeError("显式单次重试的原失败槽位客户端未全部就绪")
        elif amendment is not None:
            fixed_ten_slots = list(amendment["api_key_slots"])
            clients = category_image_production.openai_clients_by_slot(config, fixed_ten_slots)
            if [int(pair[0]) for pair in clients] != fixed_ten_slots:
                raise RuntimeError("调度变更冻结槽位的客户端未全部就绪")
        else:
            fixed_ten_slots = (
                _category_resume_fixed_ten_slots(license_data, config)
                if max_workers == 10 else None
            )
        worker_env = (
            _category_explicit_retry_environment(config, context["job"])
            if explicit_retry is not None else _category_proxy_environment(config)
        )
        network_mode = str(worker_env.get("PIPE_CATEGORY_NETWORK_MODE") or "unknown")
        if stale is None:
            stale_archive = None
        elif stale.get("stale_session_kind") == "original":
            stale_archive = _archive_stale_consumed_original_session(context, stale)
        else:
            stale_archive = _archive_stale_consumed_resume_session(context, stale)
        _require_no_active_resume_session(
            authorization_dir,
            session_dir,
            context["job_id"],
            context["license_id"],
        )
        now = datetime.now(timezone.utc).isoformat()
        attempts_used = plan["attempts_used_by_target"]
        attempts_remaining = plan["attempts_remaining_by_target"]
        resumable_ids = plan["resumable_target_ids"]
        exhausted_ids = plan["exhausted_target_ids"]
        balance_recoverable_ids = plan["balance_recoverable_target_ids"]
        authorization = {
            "schema_version": 1,
            "kind": "category-image-resume-authorization",
            "authorization_id": authorization_id,
            "status": "active",
            "one_time": True,
            "job_id": context["job_id"],
            "license_id": context["license_id"],
            "category_id": context["category_id"],
            "batch_id": context["batch_dir"].name,
            "original_plan_sha256": original_plan_sha256,
            "resume_plan_sha256": supplied_hash,
            "frozen_manifest_sha256": plan["frozen_manifest_sha256"],
            "frozen_overlay_sha256": plan["frozen_overlay_sha256"],
            "events_sha256": plan["events_sha256"],
            "event_tail_sha256": plan["event_tail_sha256"],
            "original_license_sha256": _sha256_file(context["license_path"]),
            "original_job_sha256": _sha256_file(context["job_path"]),
            "requests_used": int(plan["requests_used"]),
            "approved_remaining_request_budget": int(
                plan["remaining_max_requests"]
            ),
            "approved_cumulative_request_budget": int(
                plan["cumulative_max_requests"]
            ),
            "original_approved_request_budget": original_budget,
            "approved_resumable_count": len(resumable_ids),
            "approved_resumable_ids_sha256": _json_sha256(resumable_ids),
            "approved_exhausted_count": len(exhausted_ids),
            "approved_exhausted_ids_sha256": _json_sha256(exhausted_ids),
            "approved_balance_recoverable_count": len(balance_recoverable_ids),
            "approved_balance_recoverable_ids_sha256": _json_sha256(
                balance_recoverable_ids
            ),
            "approved_balance_failure_request_count": int(
                plan["balance_failure_request_count"]
            ),
            "approved_additional_recovery_request_budget": int(
                plan["additional_recovery_request_budget"]
            ),
            "attempts_used_sha256": _json_sha256(attempts_used),
            "attempts_remaining_sha256": _json_sha256(attempts_remaining),
            "per_target_attempts_sha256": _json_sha256(
                {"used": attempts_used, "remaining": attempts_remaining}
            ),
            "max_attempts": int(plan.get("max_attempts") or license_data["max_attempts"]),
            "retry_policy": str(
                plan.get("retry_policy") or license_data["retry_policy"]
            ),
            "provider": str(plan.get("provider") or license_data.get("provider") or ""),
            "base_url": frozen_base_url,
            "model": str(plan.get("model") or license_data.get("model") or ""),
            "quality": str(plan.get("quality") or license_data.get("quality") or ""),
            "size": str(plan.get("size") or license_data.get("size") or ""),
            "max_workers": max_workers,
            "resume_policy": resume_policy,
            "resume_confirmed": True,
            "paid_confirmed": True,
            "third_party_confirmed": True,
            "created_at": now,
        }
        if profile is not None:
            for key in ("generation_profile", "profile_resume_policy", "profile_max_workers", "profile_api_key_slots", "profile_quarantined_api_key_slots"):
                authorization[key] = plan[key]
        if "source_size_acceptance" in plan:
            authorization["source_size_acceptance"] = plan["source_size_acceptance"]
        if fixed_ten_slots is not None:
            authorization["api_key_slots"] = fixed_ten_slots
        if amendment is not None:
            authorization["schedule_amendment"] = amendment
            authorization["schedule_amendment_confirmed"] = True
        if generation_migration is not None:
            authorization["generation_migration"] = generation_migration
            authorization["generation_migration_confirmed"] = True
        if explicit_retry is not None:
            refreshed = _category_resume_context_for_args(args)
            if (
                refreshed["resume_plan"]["resume_plan_sha256"] != supplied_hash
                or refreshed["previous_resume_session_sha256"] != context["previous_resume_session_sha256"]
                or _sha256_file(context["job_path"]) != authorization["original_job_sha256"]
                or _sha256_file(context["license_path"]) != authorization["original_license_sha256"]
            ):
                raise RuntimeError("显式重试授权创建前证据已变化，未创建授权")
            authorization["explicit_retry"] = explicit_retry
            authorization["explicit_retry_confirmed"] = True
            authorization["previous_resume_session_sha256"] = context["previous_resume_session_sha256"]
            authorization["explicit_retry_network_mode"] = network_mode
        _write_json_exclusive(authorization_path, authorization)

        log_dir = production / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = (log_dir / f"{authorization_id}.log").resolve()
        session = {
            "schema_version": 1,
            "kind": "category-image-resume-session",
            "authorization_id": authorization_id,
            "job_id": context["job_id"],
            "license_id": context["license_id"],
            "category_id": context["category_id"],
            "batch_id": context["batch_dir"].name,
            "resume_plan_sha256": supplied_hash,
            "max_workers": max_workers,
            "resume_policy": resume_policy,
            "status": "queued",
            "pid": None,
            "created_at": now,
            "updated_at": now,
            "authorization_file": str(authorization_path),
            "log_file": str(log_path),
        }
        if profile is not None:
            for key in ("generation_profile", "profile_resume_policy", "profile_max_workers", "profile_api_key_slots", "profile_quarantined_api_key_slots"):
                session[key] = plan[key]
        if "source_size_acceptance" in plan:
            session["source_size_acceptance"] = plan["source_size_acceptance"]
        write_json_atomic(session_path, session)

        worker_env = _independent_python_environment(worker_env)
        command = [
            _independent_python_executable(),
            "-m",
            "tools.category_image_resume_worker",
            "run",
            "--batch-dir",
            str(context["batch_dir"]),
            "--job-file",
            str(context["job_path"]),
            "--license",
            str(context["license_path"]),
            "--resume-authorization",
            str(authorization_path),
            "--session-file",
            str(session_path),
            "--resume-plan-sha256",
            supplied_hash,
        ]
        popen_kwargs: dict[str, Any] = {
            "cwd": ROOT,
            "env": worker_env,
            "close_fds": True,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = hidden_independent_worker_flags()
        else:
            popen_kwargs["start_new_session"] = True
        try:
            with log_path.open("a", encoding="utf-8") as log_handle:
                process = subprocess.Popen(
                    command,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    **popen_kwargs,
                )
        except Exception as error:
            failed_session = load_json(session_path)
            failed_session.update(
                {
                    "status": "launch_failed",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": f"{type(error).__name__}: worker process was not started",
                }
            )
            write_json_atomic(session_path, failed_session)
            raise

        started_session = load_json(session_path)
        if started_session.get("status") == "queued":
            started_session.update(
                {
                    "status": "starting",
                    "pid": process.pid,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "launch_mode": (
                        "hidden-independent" if os.name == "nt" else "detached-session"
                    ),
                }
            )
            write_json_atomic(session_path, started_session)

        print("续跑授权已创建，专用后台 worker 已启动。")
        print(
            f"可续跑目标：{len(resumable_ids)}；"
            f"本次最多请求：{plan['remaining_max_requests']}；"
            f"累计最多请求：{plan['cumulative_max_requests']} / {original_budget}。"
        )
        print(
            f"已耗尽目标：{len(exhausted_ids)}；这些目标不会在本次续跑中再次请求。"
        )
        if balance_recoverable_ids:
            print(
                f"余额不足可恢复目标：{len(balance_recoverable_ids)}；"
                "这些目标仅在本次新计划与新授权下重新获得有效生成尝试。"
            )
        if plan["additional_recovery_request_budget"]:
            print(
                "余额失败请求抵扣后的追加累计额度："
                f"{plan['additional_recovery_request_budget']}；"
                "该额度已绑定本次新计划，不继承为通用许可。"
            )
        if explicit_retry is not None:
            print("显式单次重试：仅指定目标各原样一次、原失败槽位、固定单路；任一失败立即停止，不自动重试或换槽。")
        elif profile is not None:
            print(f"续跑调度：继承原adaptive上限{max_workers}，单探针后4→6→8→10；异常降档/熔断，原预算与槽隔离保留。")
        elif max_workers == 10:
            print(
                "续跑调度：单请求探针成功后固定10路；异常不降档；"
                "保留内容政策熔断；单个Key余额不足时隔离该槽位并切换其余"
                "授权Key，全部授权槽位余额不足时才暂停。"
            )
        else:
            print(
                "续跑调度：固定单路串行；探针后仍保持1个worker；"
                "保留内容政策熔断，并在再次出现余额不足时立即暂停。"
            )
        print(f"授权侧车：{authorization_path}")
        print(f"续跑会话：{session_path}")
        print(f"续跑日志：{log_path}")
        if stale_archive is not None:
            if stale is not None and stale.get("stale_session_kind") == "original":
                print(f"上一死亡原生产会话已保全归档：{stale_archive}")
            else:
                print(f"上一死亡续跑会话已保全归档：{stale_archive}")
        print(f"网络路径：{network_mode}（仅续跑 worker 环境，不修改系统代理）")
        print(f"worker PID：{process.pid}；付费 API 请求可能开始。")
        return 0
    except Exception as error:
        print("续跑授权或启动失败")
        print(f"问题：{error}")
        print("未通过全部校验时不会启动专用续跑 worker。")
        return 2


def _validate_zero_request_resume_relaunch(
    context: dict[str, Any],
    supplied_hash: str,
) -> dict[str, Any]:
    """Bind a relaunch to an active authorization that made zero resume requests."""

    plan = context["resume_plan"]
    license_data = context["license"]
    if supplied_hash != plan["resume_plan_sha256"]:
        raise RuntimeError(
            "续跑计划校验码已变化；零请求失败后的重新启动必须重新核对"
        )
    production = Path(context["production_dir"])
    authorization_id = _category_resume_authorization_id(
        context["job_id"], supplied_hash
    )
    authorization_dir = (production / "resume_authorizations").resolve()
    session_dir = (production / "resume_sessions").resolve()
    authorization_path = (
        authorization_dir / f"{authorization_id}.json"
    ).resolve()
    session_path = (session_dir / f"{authorization_id}.json").resolve()
    if authorization_path.parent != authorization_dir or session_path.parent != session_dir:
        raise RuntimeError("续跑授权或会话路径越出固定目录")
    if not authorization_path.is_file() or not session_path.is_file():
        raise RuntimeError("找不到可复用的续跑授权或零请求失败会话")

    authorization = load_json(authorization_path)
    authorized_max_workers = authorization.get("max_workers")
    if isinstance(authorized_max_workers, bool) or authorized_max_workers not in {1, 4, 10}:
        raise RuntimeError("现有续跑授权 max_workers 不是允许的1、4或10")
    expected_resume_policy = {
        1: CATEGORY_RESUME_SERIAL_POLICY,
        4: "probe_then_2_then_4_policy_circuit_v1",
        10: CATEGORY_RESUME_FIXED_TEN_POLICY,
    }[authorized_max_workers]
    legacy_parallel_authorization = (
        _is_legacy_category_resume_parallel_authorization(authorization, plan)
    )
    recorded_resume_policy = authorization.get("resume_policy")
    if (
        not legacy_parallel_authorization
        and recorded_resume_policy != expected_resume_policy
    ):
        raise RuntimeError("现有续跑授权的并发上限与 resume_policy 不一致")
    expected_authorization = {
        "schema_version": 1,
        "kind": "category-image-resume-authorization",
        "authorization_id": authorization_id,
        "status": "active",
        "one_time": True,
        "job_id": context["job_id"],
        "license_id": context["license_id"],
        "category_id": context["category_id"],
        "batch_id": context["batch_dir"].name,
        "original_plan_sha256": str(license_data.get("plan_sha256") or ""),
        "resume_plan_sha256": supplied_hash,
        "frozen_manifest_sha256": plan["frozen_manifest_sha256"],
        "frozen_overlay_sha256": plan["frozen_overlay_sha256"],
        "events_sha256": plan["events_sha256"],
        "event_tail_sha256": plan["event_tail_sha256"],
        "requests_used": int(plan["requests_used"]),
        "approved_remaining_request_budget": int(plan["remaining_max_requests"]),
        "approved_cumulative_request_budget": int(
            plan["cumulative_max_requests"]
        ),
        "original_approved_request_budget": int(plan["approved_request_budget"]),
        "approved_resumable_count": len(plan["resumable_target_ids"]),
        "approved_resumable_ids_sha256": _json_sha256(
            plan["resumable_target_ids"]
        ),
        "approved_exhausted_count": len(plan["exhausted_target_ids"]),
        "approved_exhausted_ids_sha256": _json_sha256(
            plan["exhausted_target_ids"]
        ),
        "attempts_used_sha256": _json_sha256(plan["attempts_used_by_target"]),
        "attempts_remaining_sha256": _json_sha256(
            plan["attempts_remaining_by_target"]
        ),
        "per_target_attempts_sha256": _json_sha256(
            {
                "used": plan["attempts_used_by_target"],
                "remaining": plan["attempts_remaining_by_target"],
            }
        ),
        "max_attempts": int(plan.get("max_attempts") or license_data["max_attempts"]),
        "retry_policy": str(
            plan.get("retry_policy") or license_data["retry_policy"]
        ),
        "provider": str(plan.get("provider") or license_data.get("provider") or ""),
        "base_url": str(license_data.get("base_url") or "").rstrip("/"),
        "model": str(plan.get("model") or license_data.get("model") or ""),
        "quality": str(plan.get("quality") or license_data.get("quality") or ""),
        "size": str(plan.get("size") or license_data.get("size") or ""),
        "max_workers": authorized_max_workers,
        "resume_confirmed": True,
        "paid_confirmed": True,
        "third_party_confirmed": True,
    }
    if not legacy_parallel_authorization:
        expected_authorization["resume_policy"] = expected_resume_policy
    if authorized_max_workers == 10:
        expected_authorization["api_key_slots"] = (
            _category_resume_frozen_fixed_ten_slots(license_data)
        )
    if not legacy_parallel_authorization:
        expected_authorization.update(
            {
                "approved_balance_recoverable_count": len(
                    plan["balance_recoverable_target_ids"]
                ),
                "approved_balance_recoverable_ids_sha256": _json_sha256(
                    plan["balance_recoverable_target_ids"]
                ),
                "approved_balance_failure_request_count": int(
                    plan["balance_failure_request_count"]
                ),
                "approved_additional_recovery_request_budget": int(
                    plan["additional_recovery_request_budget"]
                ),
            }
        )
    mismatches = [
        key
        for key, expected in expected_authorization.items()
        if authorization.get(key) != expected
    ]
    if mismatches:
        raise RuntimeError(
            "现有续跑授权不再与零请求冻结计划一致：" + ", ".join(mismatches)
        )
    if not authorization.get("created_at"):
        raise RuntimeError("现有续跑授权缺少 created_at")
    if authorization.get("original_license_sha256") != _sha256_file(
        context["license_path"]
    ):
        raise RuntimeError("原许可证在续跑授权后发生变化，不能按零请求失败重启")
    if authorization.get("original_job_sha256") != _sha256_file(
        context["job_path"]
    ):
        raise RuntimeError("原任务文件在续跑授权后发生变化，不能按零请求失败重启")
    events_path = (
        production / f"events_{context['job_id']}.jsonl"
    ).resolve()
    if not events_path.is_file() or authorization.get("events_sha256") != _sha256_file(
        events_path
    ):
        raise RuntimeError("原事件账本在续跑授权后发生变化，不能按零请求失败重启")
    event_lines = [
        line for line in events_path.read_bytes().splitlines() if line.strip()
    ]
    if not event_lines or authorization.get("event_tail_sha256") != hashlib.sha256(
        event_lines[-1]
    ).hexdigest():
        raise RuntimeError("原事件账本尾部在续跑授权后发生变化，不能按零请求失败重启")
    if int(license_data.get("requests_used", -1)) != int(authorization["requests_used"]):
        raise RuntimeError("原许可证已有续跑请求增量，禁止使用零请求重启入口")
    if int(context["job"].get("requests_used", -1)) != int(
        authorization["requests_used"]
    ):
        raise RuntimeError("原任务已有续跑请求增量，禁止使用零请求重启入口")

    terminal_path = (
        production / "resume_summaries" / f"{authorization_id}.json"
    ).resolve()
    if terminal_path.is_file():
        raise RuntimeError("该续跑授权已经存在终态证据，禁止重新启动")

    for path in authorization_dir.glob("*.json"):
        if path.resolve() == authorization_path:
            continue
        payload = load_json(path)
        if (
            payload.get("job_id") == context["job_id"]
            and payload.get("license_id") == context["license_id"]
            and payload.get("status") == "active"
        ):
            raise RuntimeError(f"该任务另有活动续跑授权，禁止重启：{path}")
    for path in session_dir.glob("*.json"):
        if path.resolve() == session_path:
            continue
        payload = load_json(path)
        if (
            payload.get("job_id") == context["job_id"]
            and payload.get("license_id") == context["license_id"]
            and payload.get("status")
            in {
                "queued",
                "starting",
                "running",
                "waiting_for_api",
                "resume_running",
                "resume_waiting_for_api",
            }
        ):
            raise RuntimeError(f"该任务另有活动续跑会话，禁止重启：{path}")

    generation_lock = (production / "generation.lock").resolve()
    if generation_lock.is_file():
        raise RuntimeError("零请求失败重启要求不存在 generation.lock")

    session = load_json(session_path)
    expected_session = {
        "schema_version": 1,
        "kind": "category-image-resume-session",
        "authorization_id": authorization_id,
        "job_id": context["job_id"],
        "license_id": context["license_id"],
        "category_id": context["category_id"],
        "batch_id": context["batch_dir"].name,
        "resume_plan_sha256": supplied_hash,
        "authorization_file": str(authorization_path),
    }
    session_mismatches = [
        key
        for key, expected in expected_session.items()
        if session.get(key) != expected
    ]
    if session_mismatches:
        raise RuntimeError(
            "续跑会话与可安全复用的零请求启动证据不一致："
            + ", ".join(session_mismatches)
        )
    session_status = session.get("status")
    if session_status == "starting":
        try:
            failed_launcher_pid = int(session.get("pid", 0) or 0)
        except (TypeError, ValueError) as error:
            raise RuntimeError("零请求失败会话没有有效 launcher PID") from error
        if failed_launcher_pid <= 0:
            raise RuntimeError("零请求失败会话没有有效 launcher PID")
        if category_image_production.pid_is_running(failed_launcher_pid):
            raise RuntimeError(
                f"上一次续跑 launcher PID={failed_launcher_pid} 仍在运行，禁止重启"
            )
    elif session_status == "launch_failed":
        if session.get("pid") is not None:
            raise RuntimeError("launch_failed 续跑会话不得绑定 launcher PID")
        last_error = session.get("last_error")
        if not isinstance(last_error, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*: worker process was not started",
            last_error,
        ):
            raise RuntimeError("launch_failed 续跑会话缺少可信的启动失败证据")
        if not session.get("finished_at"):
            raise RuntimeError("launch_failed 续跑会话缺少 finished_at")
        failed_launcher_pid = 0
    else:
        raise RuntimeError("续跑会话不是可安全复用的 starting 或 launch_failed 状态")
    log_path = Path(str(session.get("log_file") or "")).expanduser().resolve()
    expected_log = (production / "logs" / f"{authorization_id}.log").resolve()
    if log_path != expected_log or not log_path.is_file():
        raise RuntimeError("零请求失败会话没有绑定固定启动日志")

    return {
        "authorization_id": authorization_id,
        "authorization_path": authorization_path,
        "authorization": authorization,
        "session_path": session_path,
        "session": session,
        "log_path": log_path,
        "failed_launcher_pid": failed_launcher_pid,
    }


def command_restart_resume_category_images(args: argparse.Namespace) -> int:
    """Relaunch one active authorization only after a proven zero-request failure."""

    _category_utf8_console()
    try:
        if not args.confirm_resume:
            raise RuntimeError("重新启动续跑必须明确传入 --confirm-resume")
        if not args.confirm_paid:
            raise RuntimeError("重新启动可能继续产生费用，必须明确传入 --confirm-paid")
        if not args.confirm_third_party:
            raise RuntimeError("继续使用第三方中转必须明确传入 --confirm-third-party")
        supplied_hash = str(args.resume_plan_sha256 or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", supplied_hash):
            raise RuntimeError("resume-plan-sha256 必须是64位小写 SHA-256")

        context = _category_image_resume_context(
            args.category, args.job_id, args.batch_dir
        )
        relaunch = _validate_zero_request_resume_relaunch(context, supplied_hash)
        plan = context["resume_plan"]
        license_data = context["license"]

        config = _category_effective_config()
        config_bindings = {
            "provider": config.get("provider"),
            "model": config.get("model"),
            "quality": config.get("quality"),
            "size": config.get("api_size"),
        }
        for key, current in config_bindings.items():
            frozen = plan.get(key) or license_data.get(key)
            if current != frozen:
                raise RuntimeError(
                    f"当前图片配置 {key}={current!r} 与冻结许可证 {frozen!r} 不一致"
                )
        current_base_url = str(config.get("base_url") or "").rstrip("/")
        frozen_base_url = str(license_data.get("base_url") or "").rstrip("/")
        if current_base_url != frozen_base_url:
            raise RuntimeError("当前中转地址与冻结许可证不一致")
        if int(relaunch["authorization"]["max_workers"]) == 10:
            _category_resume_fixed_ten_slots(license_data, config)
        worker_env = _category_proxy_environment(config)
        network_mode = str(worker_env.get("PIPE_CATEGORY_NETWORK_MODE") or "unknown")

        session_path = Path(relaunch["session_path"])
        original_session = dict(relaunch["session"])
        now = datetime.now(timezone.utc).isoformat()
        queued_session = dict(original_session)
        queued_session.update(
            {
                "status": "queued",
                "pid": None,
                "updated_at": now,
                "restart_count": int(original_session.get("restart_count", 0) or 0)
                + 1,
                "restart_confirmed_at": now,
                "previous_launcher_pid": relaunch["failed_launcher_pid"],
                "restart_reason": "zero_request_startup_failure",
            }
        )
        write_json_atomic(session_path, queued_session)

        worker_env = _independent_python_environment(worker_env)
        command = [
            _independent_python_executable(),
            "-m",
            "tools.category_image_resume_worker",
            "run",
            "--batch-dir",
            str(context["batch_dir"]),
            "--job-file",
            str(context["job_path"]),
            "--license",
            str(context["license_path"]),
            "--resume-authorization",
            str(relaunch["authorization_path"]),
            "--session-file",
            str(session_path),
            "--resume-plan-sha256",
            supplied_hash,
        ]
        popen_kwargs: dict[str, Any] = {
            "cwd": ROOT,
            "env": worker_env,
            "close_fds": True,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = hidden_independent_worker_flags()
        else:
            popen_kwargs["start_new_session"] = True
        try:
            with Path(relaunch["log_path"]).open("a", encoding="utf-8") as log_handle:
                process = subprocess.Popen(
                    command,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    **popen_kwargs,
                )
        except Exception as error:
            restored = dict(original_session)
            restored.update(
                {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "restart_count": queued_session["restart_count"],
                    "last_restart_launch_error": (
                        f"{type(error).__name__}: worker process was not started"
                    ),
                }
            )
            write_json_atomic(session_path, restored)
            raise

        started_session = load_json(session_path)
        if started_session.get("status") == "queued":
            started_session.update(
                {
                    "status": "starting",
                    "pid": process.pid,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "launch_mode": (
                        "hidden-independent" if os.name == "nt" else "detached-session"
                    ),
                }
            )
            write_json_atomic(session_path, started_session)

        print("零请求失败的续跑会话已使用原授权重新启动。")
        print(
            f"复用授权：{relaunch['authorization_id']}；"
            f"可续跑目标：{len(plan['resumable_target_ids'])}；"
            f"本次最多请求：{plan['remaining_max_requests']}；"
            f"累计最多请求：{plan['cumulative_max_requests']} / "
            f"{plan['approved_request_budget']}。"
        )
        print(
            f"已耗尽目标：{len(plan['exhausted_target_ids'])}；"
            "这些目标仍不会再次请求。"
        )
        if plan["balance_recoverable_target_ids"]:
            print(
                "余额不足可恢复目标："
                f"{len(plan['balance_recoverable_target_ids'])}；"
                "仍绑定原事件证据与本次续跑计划校验码。"
            )
        if plan["additional_recovery_request_budget"]:
            print(
                "余额失败请求抵扣后的追加累计额度："
                f"{plan['additional_recovery_request_budget']}。"
            )
        print(f"续跑会话：{session_path}")
        print(f"续跑日志：{relaunch['log_path']}")
        print(f"网络路径：{network_mode}（仅续跑 worker 环境，不修改系统代理）")
        print(f"worker launcher PID：{process.pid}；付费 API 请求可能开始。")
        return 0
    except Exception as error:
        print("零请求失败后的续跑重新启动失败")
        print(f"问题：{error}")
        print("未通过全部冻结证据校验时不会启动 worker，也不会创建新授权。")
        return 2


def command_accept_category_source_sizes(args: argparse.Namespace) -> int:
    """Bind relaxed source sizes to one existing job and reuse paid sources locally."""
    _category_utf8_console()
    try:
        if args.confirm is not True:
            raise RuntimeError("仅在用户明确接受本任务实际源图尺寸后使用 --confirm")
        from tools.category_source_size_acceptance import accept_source_sizes
        from tools.category_4k_raw import DECODABLE_SOURCE_POLICY, HD_DELIVERY_SOURCE_POLICY

        job_id = _safe_category_resume_identifier(args.job_id, "job-id")
        batch = category_active_batch_dir(args.category, args.batch_dir).resolve()
        production = category_image_production.production_dir(batch).resolve()
        job_path = (production / "jobs" / f"{job_id}.json").resolve()
        if job_path.parent != production / "jobs" or not job_path.is_file():
            raise RuntimeError("找不到该活动批次的任务记录")
        job = load_json(job_path)
        if job.get("job_id") != job_id or job.get("category_id") != args.category:
            raise RuntimeError("接受源尺寸的任务身份与指定类目不一致")
        license_id = _safe_category_resume_identifier(str(job.get("license_id") or ""), "license-id")
        license_path = (production / "licenses" / f"{license_id}.json").resolve()
        if license_path.parent != production / "licenses" or not license_path.is_file():
            raise RuntimeError("找不到任务绑定的原许可证")
        policy_id = (HD_DELIVERY_SOURCE_POLICY if getattr(args, "source_policy", "decodable") == "hd-delivery"
                     else DECODABLE_SOURCE_POLICY)
        result = accept_source_sizes(batch, job_path, license_path, confirm=True, policy_id=policy_id)
        print("已仅为该任务接受平台实际源图尺寸，保留源文件与原交付尺寸。")
        print("已保存的拒绝源按冻结证据本地恢复；无 API 调用，不退计次、不重置预算、不启动任务。")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        print("任务级源尺寸接受未完成")
        print(f"问题：{error}")
        return 2


def command_recover_category_provider_source(args: argparse.Namespace) -> int:
    """Accept one preserved response locally without sending another request."""
    _category_utf8_console()
    try:
        from tools.category_source_recovery import recover_provider_source

        job_id = _safe_category_resume_identifier(args.job_id, "job-id")
        batch = category_active_batch_dir(args.category, args.batch_dir).resolve()
        production = category_image_production.production_dir(batch).resolve()
        job_path = (production / "jobs" / f"{job_id}.json").resolve()
        if job_path.parent != production / "jobs" or not job_path.is_file():
            raise RuntimeError("找不到该活动批次的任务记录")
        job = load_json(job_path)
        if job.get("job_id") != job_id or job.get("category_id") != args.category:
            raise RuntimeError("恢复源图的任务身份与指定类目不一致")
        license_id = _safe_category_resume_identifier(str(job.get("license_id") or ""), "license-id")
        license_path = (production / "licenses" / f"{license_id}.json").resolve()
        if license_path.parent != production / "licenses" or not license_path.is_file():
            raise RuntimeError("找不到恢复源图绑定的原许可证")
        result = recover_provider_source(
            batch, job_path, license_path, request_number=args.request_number,
            accepted_source_size=args.accepted_source_size, confirm=args.confirm,
            **({"accepted_source_width_tolerance": args.accepted_source_width_tolerance}
               if getattr(args, "accepted_source_width_tolerance", 0) else {}),
        )
        print("已本地恢复保存的源图；无 API 调用，不增加请求或重置重试次数。")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        print("本地源图恢复未完成")
        print(f"问题：{error}")
        return 2


def command_category_image_resume_plan(args: argparse.Namespace) -> int:
    """Print a strictly read-only plan for continuing one interrupted paid job."""

    _category_utf8_console()
    try:
        context = _category_resume_context_for_args(args)
        category_id = context["category_id"]
        job_id = context["job_id"]
        license_id = context["license_id"]
        batch_dir = context["batch_dir"]
        resume_plan = context["resume_plan"]
        max_workers = _category_resume_requested_max_workers(args, resume_plan)
        if max_workers == 10 and not resume_plan.get("schedule_amendment") and not resume_plan.get("generation_profile"):
            _category_resume_frozen_fixed_ten_slots(context["license"])

        print(f"{category_id} 图片续跑只读计划")
        print(f"任务：{job_id}；批次：{batch_dir.name}；许可证：{license_id}")
        balance_classification = (
            "余额不足可恢复 "
            f"{len(resume_plan['balance_recoverable_target_ids'])}；"
            if resume_plan["balance_recoverable_target_ids"]
            else ""
        )
        print(
            "目标分类："
            f"成功 {len(resume_plan['success_target_ids'])}；"
            f"已耗尽 {len(resume_plan['exhausted_target_ids'])}；"
            f"{balance_classification}"
            f"中断保守计次 {len(resume_plan['unknown_target_ids'])}；"
            f"未尝试 {len(resume_plan['unattempted_target_ids'])}；"
            f"可续跑 {len(resume_plan['resumable_target_ids'])}。"
        )
        print(f"已使用 API 请求：{resume_plan['requests_used']} 次。")
        print(f"续跑最多 API 请求：{resume_plan['remaining_max_requests']} 次。")
        print(
            f"累计最多 API 请求：{resume_plan['cumulative_max_requests']} / "
            f"{resume_plan['approved_request_budget']} 次。"
        )
        if resume_plan["balance_failure_request_count"]:
            print(
                "已核验余额不足失败请求："
                f"{resume_plan['balance_failure_request_count']} 次；"
                "余额失败请求抵扣后的追加累计额度："
                f"{resume_plan['additional_recovery_request_budget']} 次。"
            )
        print(f"resume_plan_sha256：{resume_plan['resume_plan_sha256']}")
        print(f"frozen_manifest_sha256：{resume_plan['frozen_manifest_sha256']}")
        print(f"frozen_overlay_sha256：{resume_plan['frozen_overlay_sha256']}")
        print(f"events_sha256：{resume_plan['events_sha256']}")
        print(f"event_tail_sha256：{resume_plan['event_tail_sha256']}")
        if resume_plan.get("source_size_acceptance"):
            print("已绑定本任务实际源尺寸接受：保全原始响应，解码安全边界不变，工作raw与成品保持原尺寸；不宣称原生4K。")
            print("已记录失败且仍有有效尝试的目标沿用原额度；实际预留后缺结果的未知请求仍禁止重发。")
        if resume_plan.get("schedule_amendment"):
            amendment = resume_plan["schedule_amendment"]
            print(f"调度变更冻结槽位：{amendment['api_key_slots']}；继承隔离：{amendment['inherited_quarantined_api_key_slots']}。")
            print("总预算严格沿用原许可证，余额失败不追加预算；原许可调度字段保持不变。")
        if resume_plan.get("generation_migration"):
            migration = resume_plan["generation_migration"]
            print(f"任务级生成配置：{migration['new_generation']}；保全源响应，原交付尺寸不变。")
            if migration.get("accepted_source_size"):
                print(f"用户已接受平台实际返回尺寸：{migration['accepted_source_size']}；不放大冒充3840长边4K。")
            if migration.get("accepted_source_width_tolerance") == 16:
                print("源图精确接受2336x3520或2352x3520；其它宽度或高度仍拒绝，交付尺寸不变。")
            print(f"新凭据版本轮换槽：{migration['rotated_slots']}；剩余隔离：{migration['effective_quarantined_api_key_slots']}。")
            print(f"沿用前序累计上限：{migration['prior_cumulative_request_cap']}；不会重置历史尝试。")
        if resume_plan.get("explicit_retry"):
            retry = resume_plan["explicit_retry"]
            print(f"用户显式单次重试目标：{resume_plan['explicit_retry_target_ids']}；原失败记录和计次保留。")
            print(f"仅原提示词/原失败槽位/原网络路径，每目标1次；任一失败立即停止。前序累计上限：{retry['prior_cumulative_request_cap']}。")
        if resume_plan.get("generation_profile"):
            print(f"冻结生成profile：{resume_plan['generation_profile']['id']}；API尺寸{resume_plan['size']}，工作raw{resume_plan['generation_profile']['working_raw_size']}。")
            print(f"拟议续跑调度：继承原adaptive上限{max_workers}与冻结槽位，不改成固定10路；余额失败不追加总预算。")
        elif max_workers == 10:
            print(
                "拟议续跑调度：单请求探针成功后固定10路；启动时必须继续显式传入 "
                "--max-workers 10，并重新校验10个冻结客户端槽位。"
            )
        else:
            print("拟议续跑调度：固定单路串行（默认 --max-workers 1）。")
        if resume_plan["balance_recoverable_target_ids"]:
            print(
                "余额不足失败不消耗目标的有效生成尝试；充值后启动仍必须使用"
                "本次新 resume_plan_sha256 重新进行精确付费授权。"
            )
        print("本命令只读取本地证据；未写文件、未创建许可证、未启动进程、未调用 API。")
        return 0
    except Exception as error:
        print("续跑计划核算失败")
        print(f"问题：{error}")
        print("本命令未写文件、未创建许可证、未启动进程、未调用 API。")
        return 2


def command_start_category_images(args: argparse.Namespace) -> int:
    _category_utf8_console()
    try:
        category_id = args.category
        _category_sample_range(category_id, args.group_start, args.group_count, scope=args.scope)
        config = _category_effective_config()
        batch_dir = category_active_batch_dir(category_id, args.batch_dir)
        target_license = category_image_production.license_path(
            category_id,
            batch_dir,
            args.group_start,
            args.group_count,
            args.license_id,
        )
        if not target_license.is_file():
            raise RuntimeError("找不到这个一次性许可证编号；请复制授权命令输出的 license-id")
        license_data = load_json(target_license)
        if license_data.get("status") != "active":
            raise RuntimeError("一次性许可证已经被消费或不是 active 状态；不能重复付费启动")
        if args.scope != license_data.get("scope"):
            raise RuntimeError("启动范围与一次性许可证不一致")
        config = category_generation_profile.from_license(config, category_id, license_data)
        run_plan = category_image_production.plan(
            category_id,
            batch_dir,
            args.group_start,
            args.group_count,
            str(license_data.get("phone", "")),
            config,
            scope=args.scope,
            output_root=_category_output_root(category_id),
            generation_target_id=license_data.get("generation_target_id"),
        )
        _category_require_executable_scope(
            args.scope,
            str(run_plan.get("generation_mode") or ""),
            category_id=category_id,
            review_after_batch=license_data.get("review_after_batch") is True,
        )
        bindings = _pipe_v2_plan_bindings(run_plan)
        for key, expected in bindings.items():
            if license_data.get(key) != expected:
                raise RuntimeError(f"一次性许可证与最新v2计划不一致：{key}")
        slots = [int(slot) for slot in license_data.get("api_key_slots") or []]
        max_workers = int(license_data.get("max_workers", 0) or 0)
        if args.scope == "details":
            evidence = _category_cover_approval_evidence(
                category_id,
                args.group_start,
                args.group_count,
                expected_phone=str(license_data.get("phone", "")),
            )
            _category_require_registered_cover_approval(category_id, evidence)
            if evidence["sha256"] != license_data.get("cover_approval_sha256"):
                raise RuntimeError("首图验收证据与授权时不一致；必须重新核算并重新授权")
        category_image_production.validate_license(
            target_license, run_plan, config, slots, max_workers
        )
        category_image_production.validate_frozen_cover_typography(run_plan, license_data)
        active_statuses = {"queued", "starting", "running", "waiting_for_api"}
        category_jobs_dir = category_image_production.jobs_dir(batch_dir)
        category_jobs_dir.mkdir(parents=True, exist_ok=True)
        generation_lock = category_image_production.production_dir(batch_dir) / "generation.lock"
        if generation_lock.is_file():
            try:
                lock_payload = load_json(generation_lock)
            except Exception:
                lock_payload = {}
            if category_image_production.pid_is_running(int(lock_payload.get("pid", 0) or 0)):
                raise RuntimeError(
                    f"该批次已有运行中的生产任务：{lock_payload.get('job_id') or 'unknown'}"
                )
        for path in category_jobs_dir.glob("*.json"):
            try:
                existing = load_json(path)
            except Exception:
                continue
            looks_active = (
                existing.get("job_id")
                and int(existing.get("requested_count", 0) or 0) > 0
                and existing.get("status") in active_statuses
            )
            if not looks_active:
                continue
            if _category_job_process_alive(existing) or _recent_job_update(existing):
                raise RuntimeError(f"该批次已有运行中的生产任务：{existing['job_id']}")
            existing.update({
                "status": "failed_before_start_stale",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "last_error": "检测到残留任务状态，但对应进程和生产锁均已失效。",
            })
            write_json_atomic(path, existing)
        worker_env = _category_proxy_environment(config)
        network_mode = worker_env.get("PIPE_CATEGORY_NETWORK_MODE", "unknown")
        job_id = datetime.now(timezone.utc).strftime(f"{category_id}-%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
        job_path = category_jobs_dir / f"{job_id}.json"
        log_dir = category_image_production.production_dir(batch_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{job_id}.log"
        now = datetime.now(timezone.utc).isoformat()
        write_json_atomic(job_path, {
            "schema_version": 2,
            "job_id": job_id,
            "license_id": args.license_id,
            "job_type": "category-batch-production",
            "category_id": category_id,
            "project_id": category_id,
            "batch_id": batch_dir.name,
            "batch_dir": str(batch_dir),
            "status": "queued",
            "group_start": args.group_start,
            "group_count": args.group_count,
            "scope": args.scope,
            "generation_target_id": run_plan.get("generation_target_id"),
            "plan_sha256": run_plan["plan_sha256"],
            "structure_version": bindings["structure_version"],
            "generation_mode": bindings["generation_mode"],
            "generation_targets_sha256": bindings["generation_targets_sha256"],
            "delivery_targets_sha256": bindings["delivery_targets_sha256"],
            "pending_generation_target_ids": bindings["pending_generation_target_ids"],
            "pending_delivery_target_ids": bindings["pending_delivery_target_ids"],
            "pending_target_ids": bindings["pending_delivery_target_ids"],
            "requested_count": int(license_data["approved_request_budget"]),
            "generation_target_count": bindings["pending_api_requests"],
            "pending_delivery_count": bindings["pending_delivery_count"],
            "total_images": bindings["delivery_count"],
            "completed": run_plan["existing_images"],
            "failed": 0,
            "requests_used": 0,
            "max_attempts": int(license_data.get("max_attempts", 1) or 1),
            "retry_policy": license_data.get(
                "retry_policy", category_image_production.NO_RETRY_POLICY
            ),
            "retry_request_budget": (
                int(license_data["approved_request_budget"])
                - bindings["pending_api_requests"]
            ),
            "retry_count": 0,
            "failed_request_attempts": 0,
            "api_key_policy": "fixed",
            "api_key_slots": slots,
            "worker_count": 0,
            "current_worker_count": 0,
            "max_worker_count": min(max_workers, len(slots), bindings["pending_api_requests"]),
            "concurrency_policy": license_data.get(
                "concurrency_policy",
                category_image_production.ADAPTIVE_CONCURRENCY_POLICY,
            ),
            "concurrency_history": [],
            "model": config["model"],
            "quality": config["quality"],
            "size": config["api_size"],
            "final_sizes": bindings["final_sizes"],
            **category_generation_profile.bindings(config, category_id),
            "height_profile_ids": bindings["height_profile_ids"],
            "triptych_layout_ids": bindings["triptych_layout_ids"],
            "created_at": now,
            "updated_at": now,
            "output_dir": str(_category_output_root(category_id)),
            "raw_dir": str(batch_dir / "raw"),
            "log_file": str(log_path),
            "visual_approval": "needs_user_review",
            "network_mode": network_mode,
            "review_after_batch": license_data.get("review_after_batch") is True,
        })
        activate_dashboard_session(
            job_path,
            load_json(job_path),
            target_records=list(run_plan["pending_delivery_records"]),
        )
        command = [
            sys.executable,
            "-m",
            "tools.category_image_production",
            "run",
            "--category", category_id,
            "--batch-dir", str(batch_dir),
            "--group-start", str(args.group_start),
            "--group-count", str(args.group_count),
            "--license", str(target_license),
            "--job-file", str(job_path),
            "--scope", args.scope,
            "--output-root", str(_category_output_root(category_id)),
            "--license-id", args.license_id,
            "--max-workers", str(max_workers),
        ]
        popen_kwargs: dict[str, Any] = {
            "cwd": ROOT,
            "env": worker_env,
            "close_fds": True,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True
        with log_path.open("a", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )
        job = load_json(job_path)
        job.update({"pid": process.pid, "status": "starting", "updated_at": datetime.now(timezone.utc).isoformat()})
        write_json_atomic(job_path, job)
        dashboard_started = launch_dashboard_compact()
        print(f"{category_id} 付费样片任务启动成功")
        print(f"任务编号：{job_id}")
        print(f"任务范围：{args.scope}；一次性许可证：{args.license_id}")
        print(
            f"本次待交付成品：{bindings['pending_delivery_count']} 张；"
            f"基础生成目标：{bindings['pending_api_requests']} 个；"
            f"最多API请求：{license_data['approved_request_budget']} 次"
        )
        auto_retry_limit = int(license_data.get("max_attempts", 1) or 1) - 1
        if auto_retry_limit:
            print(
                "失败处理：可重试错误每个目标最多自动重试1次；"
                "内容策略错误改用安全表述，网络/限流/服务器错误保持原提示词；"
                "SDK重试为0。"
            )
        else:
            print("失败处理：不自动重试；SDK重试为0。")
        print("三拼图按1张成品交付，但它的3个现场画面分别生成，因此两种数量不同。")
        fixed_ten = (
            license_data.get("concurrency_policy")
            == category_image_production.FIXED_TEN_CONCURRENCY_POLICY
        )
        execution_label = (
            "先用 Key 1 做单请求探针，成功后固定10路并发且异常不降档"
            if fixed_ten
            else "先用 Key 1 做单请求探针，再自适应升档"
        )
        if args.scope == "covers":
            print(
                f"执行方式：{execution_label}，"
                f"并发上限 {max_workers}；生成后必须先由你查看确认。"
            )
        elif args.scope == "all":
            print(
                f"执行方式：首图和详情图一起生成；{execution_label}，"
                f"并发上限 {max_workers}；所有成品生成后保持待用户直审。"
            )
        else:
            print(
                f"执行方式：只补详情图；{execution_label}，"
                f"并发上限 {max_workers}；不会改动已确认首图。"
            )
        print(f"网络路径：{network_mode}（仅本次任务环境，不修改系统代理）")
        print(f"成品输出目录：{_category_output_root(category_id)}")
        print(f"原始图片：{batch_dir / 'raw'}")
        print(f"任务状态：{job_path}")
        print(f"任务日志：{log_path}")
        print(f"本地看板：{'已启动' if dashboard_started else '启动失败，请手动运行 python factory.py dashboard'}")
        print("下一步：等待任务结束后人工查看图片；本程序不会自动生成下一阶段。")
        return 0
    except (Exception,) as error:
        return _category_image_error(error)


def command_confirm_start_category_images(args: argparse.Namespace) -> int:
    """Create the exact one-time license and immediately start the same plan."""

    result = command_authorize_category_images(args)
    if result != 0:
        return result
    license_id = getattr(args, "created_license_id", None)
    if not license_id:
        return _category_image_error(RuntimeError("授权成功但未返回一次性许可证编号"))
    start_args = argparse.Namespace(
        category=args.category,
        batch_dir=args.batch_dir,
        group_start=args.group_start,
        group_count=args.group_count,
        scope=args.scope,
        license_id=license_id,
    )
    return command_start_category_images(start_args)


def command_review_category_images(args: argparse.Namespace) -> int:
    """Open an optional post-production review; never starts image generation."""
    from tools import image_review
    import threading

    _category_utf8_console()
    if args.group_count < 1 or args.group_count > 200 or args.group_start < 1:
        raise RuntimeError("验收范围必须为正数，单次最多200组")
    if args.report_only and args.mode != "tool":
        raise RuntimeError("--report-only 仅用于工具模式；人工模式请打开验收页面")
    batch_dir = category_active_batch_dir(args.category)
    records = category_image_production.selected_records(
        batch_dir, args.group_start, args.group_count, args.category,
    )
    records = category_image_production.record_targets(
        batch_dir, records, _category_output_root(args.category), args.category,
    )
    deliveries = category_image_production._delivery_records(
        category_image_production._records_for_scope(records, args.scope),
    )

    def approve_cover(record, validation, note):
        phone_lines = [value for value in validation.get("expected_text", [])
                       if isinstance(value, str) and value.startswith("电话：")]
        if len(phone_lines) != 1:
            raise RuntimeError("首图缺少唯一的已确认电话记录")
        command_approve_category_sample_covers(argparse.Namespace(
            category=args.category, group_start=record["group"], group_count=1,
            phone=phone_lines[0].removeprefix("电话："), note=note, confirm=True,
        ))

    session = image_review.ReviewSession(
        deliveries, _category_output_root(args.category),
        RUNTIME_DIR / "image_reviews" / args.category, approve_cover,
    )
    if args.report_only:
        session.run_tool()
        print(json.dumps({"report_directory": str(session.directory),
                          "status": session.tool_state["status"],
                          "result": session.tool_state.get("result"),
                          "elapsed_seconds": session.tool_state.get("elapsed_seconds"),
                          "api_called": False}, ensure_ascii=False))
        return 1 if session.tool_state["status"] == "failed" else 0
    server = image_review.serve(session, args.port)
    url = f"http://127.0.0.1:{server.server_port}/?token={session.token}&mode={args.mode}"
    print(f"验收页面：{url}", flush=True)
    print(f"审核记录：{session.directory}；按 Ctrl+C 关闭。api_called=false", flush=True)
    if args.mode == "tool":
        threading.Thread(target=session.run_tool, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Road-rescue image factory")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    from tools.business_ktv.cli import add_arguments as add_business_ktv_arguments
    add_business_ktv_arguments(subparsers.add_parser('business-ktv', help='商务KTV独立类目；第一阶段mock闭环'))

    from tools.pinned_triptych import add_arguments as add_pinned_triptych_arguments
    add_pinned_triptych_arguments(subparsers.add_parser('pinned-triptych', help='连续全景三联屏任务与本地切图，不调用API'))

    review = subparsers.add_parser("review-category-images", help="人工或本地工具辅助验收，不调用生图API")
    review.add_argument("--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS))
    review.add_argument("--group-start", type=int, required=True)
    review.add_argument("--group-count", type=int, required=True)
    review.add_argument("--scope", choices=("all", "covers", "details"), default="all")
    review.add_argument("--mode", choices=("manual", "tool"), default="manual")
    review.add_argument("--report-only", action="store_true")
    review.add_argument("--port", type=int, default=0)
    review.set_defaults(handler=command_review_category_images)

    for name, handler in [
        ("help", command_help),
        ("status", command_status),
        ("audit", command_audit),
        ("plan", command_plan),
        ("package", command_package),
        ("providers", command_providers),
        ("projects", command_projects),
        ("new-project-guide", command_new_project_guide),
        ("category-help", command_category_help),
    ]:
        sub = subparsers.add_parser(name)
        sub.set_defaults(handler=handler)

    dashboard_archive = subparsers.add_parser("dashboard-archive")
    dashboard_archive.add_argument("--confirm", action="store_true")
    dashboard_archive.set_defaults(handler=command_dashboard_archive)

    package_category_groups = subparsers.add_parser("package-category-groups")
    package_category_groups.add_argument(
        "--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS)
    )
    package_category_groups.add_argument("--group-start", type=int, required=True)
    package_category_groups.add_argument("--group-count", type=int, required=True)
    package_category_groups.add_argument("--destination")
    package_category_groups.add_argument(
        "--max-archive-bytes",
        type=int,
        default=dashboard_delivery.DEFAULT_MAX_ARCHIVE_BYTES,
    )
    package_category_groups.add_argument("--confirm", action="store_true")
    package_category_groups.set_defaults(handler=command_package_category_groups)

    audit_category = subparsers.add_parser("audit-category-batch")
    audit_category.add_argument("--category", required=True)
    audit_category.add_argument("--batch-dir", required=True)
    audit_category.add_argument("--mode", required=True, choices=["mock"])
    audit_category.set_defaults(handler=command_audit_category_batch)

    category_image_plan = subparsers.add_parser("category-image-plan")
    category_image_plan.add_argument("--category", default=PIPE_PROJECT_ID, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS))
    category_image_plan.add_argument("--batch-dir")
    category_image_plan.add_argument("--group-start", type=int, default=PIPE_SAMPLE_GROUP_START)
    category_image_plan.add_argument("--group-count", type=int, default=PIPE_SAMPLE_GROUP_COUNT)
    category_image_plan.add_argument("--scope", choices=["covers", "details", "all"], default="all")
    category_image_plan.add_argument("--phone")
    category_image_plan.add_argument("--generation-target-id")
    category_image_plan.add_argument("--generation-profile", choices=category_generation_profile.PROFILE_IDS)
    category_image_plan.add_argument(
        "--review-after-batch",
        action="store_true",
        help="兼容旧命令；--scope all 现在默认在全部生成后统一审核。",
    )
    category_image_plan.add_argument(
        "--auto-retry-limit", type=int, choices=[0, 1], default=0
    )
    category_image_plan.set_defaults(handler=command_category_image_plan)

    accept_category_source_sizes = subparsers.add_parser("accept-category-source-sizes")
    accept_category_source_sizes.add_argument("--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS))
    accept_category_source_sizes.add_argument("--job-id", required=True)
    accept_category_source_sizes.add_argument("--batch-dir")
    accept_category_source_sizes.add_argument("--source-policy", choices=("decodable", "hd-delivery"), default="decodable")
    accept_category_source_sizes.add_argument("--confirm", action="store_true")
    accept_category_source_sizes.set_defaults(handler=command_accept_category_source_sizes)

    recover_category_source = subparsers.add_parser("recover-category-provider-source")
    recover_category_source.add_argument("--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS))
    recover_category_source.add_argument("--job-id", required=True)
    recover_category_source.add_argument("--batch-dir")
    recover_category_source.add_argument("--request-number", type=int, required=True)
    recover_category_source.add_argument("--accepted-source-size", choices=["2352x3520"], required=True)
    recover_category_source.add_argument("--accepted-source-width-tolerance", type=int, choices=[0, 16], default=0)
    recover_category_source.add_argument("--confirm", action="store_true")
    recover_category_source.set_defaults(handler=command_recover_category_provider_source)

    category_image_resume_plan = subparsers.add_parser("category-image-resume-plan")
    category_image_resume_plan.add_argument(
        "--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS)
    )
    category_image_resume_plan.add_argument("--job-id", required=True)
    category_image_resume_plan.add_argument("--batch-dir")
    category_image_resume_plan.add_argument(
        "--max-workers", type=int, choices=[1, 10], default=None
    )
    category_image_resume_plan.add_argument("--amend-concurrency", action="store_true")
    category_image_resume_plan.add_argument("--api-key-slot", type=int, action="append")
    category_image_resume_plan.add_argument("--migrate-model")
    category_image_resume_plan.add_argument("--migrate-quality")
    category_image_resume_plan.add_argument("--migrate-size")
    category_image_resume_plan.add_argument("--accepted-source-size", choices=["2352x3520"])
    category_image_resume_plan.add_argument("--accepted-source-width-tolerance", type=int, choices=[0, 16], default=0)
    category_image_resume_plan.add_argument("--credential-epoch")
    category_image_resume_plan.add_argument("--rotate-key-slot", type=int, action="append")
    category_image_resume_plan.add_argument("--previous-authorization-id")
    category_image_resume_plan.add_argument("--explicit-retry-target-id", action="append")
    category_image_resume_plan.set_defaults(handler=command_category_image_resume_plan)

    resume_category_images = subparsers.add_parser("resume-category-images")
    resume_category_images.add_argument(
        "--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS)
    )
    resume_category_images.add_argument("--job-id", required=True)
    resume_category_images.add_argument("--batch-dir")
    resume_category_images.add_argument("--resume-plan-sha256", required=True)
    resume_category_images.add_argument(
        "--max-workers", type=int, choices=[1, 10], default=None
    )
    resume_category_images.add_argument("--amend-concurrency", action="store_true")
    resume_category_images.add_argument("--api-key-slot", type=int, action="append")
    resume_category_images.add_argument("--migrate-model")
    resume_category_images.add_argument("--migrate-quality")
    resume_category_images.add_argument("--migrate-size")
    resume_category_images.add_argument("--accepted-source-size", choices=["2352x3520"])
    resume_category_images.add_argument("--accepted-source-width-tolerance", type=int, choices=[0, 16], default=0)
    resume_category_images.add_argument("--credential-epoch")
    resume_category_images.add_argument("--rotate-key-slot", type=int, action="append")
    resume_category_images.add_argument("--previous-authorization-id")
    resume_category_images.add_argument("--explicit-retry-target-id", action="append")
    resume_category_images.add_argument("--confirm-resume", action="store_true")
    resume_category_images.add_argument("--confirm-paid", action="store_true")
    resume_category_images.add_argument("--confirm-third-party", action="store_true")
    resume_category_images.add_argument(
        "--archive-stale-consumed-session", action="store_true"
    )
    resume_category_images.set_defaults(handler=command_resume_category_images)

    restart_resume_category_images = subparsers.add_parser(
        "restart-resume-category-images"
    )
    restart_resume_category_images.add_argument(
        "--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS)
    )
    restart_resume_category_images.add_argument("--job-id", required=True)
    restart_resume_category_images.add_argument("--batch-dir")
    restart_resume_category_images.add_argument("--resume-plan-sha256", required=True)
    restart_resume_category_images.add_argument("--confirm-resume", action="store_true")
    restart_resume_category_images.add_argument("--confirm-paid", action="store_true")
    restart_resume_category_images.add_argument(
        "--confirm-third-party", action="store_true"
    )
    restart_resume_category_images.set_defaults(
        handler=command_restart_resume_category_images
    )

    rebuild_category_covers = subparsers.add_parser("rebuild-category-covers")
    rebuild_category_covers.add_argument(
        "--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS)
    )
    rebuild_category_covers.add_argument("--batch-dir")
    rebuild_category_covers.add_argument("--group-start", type=int, default=PIPE_SAMPLE_GROUP_START)
    rebuild_category_covers.add_argument("--group-count", type=int, default=PIPE_SAMPLE_GROUP_COUNT)
    rebuild_category_covers.add_argument("--phone")
    rebuild_category_covers.add_argument("--reason", required=True)
    rebuild_category_covers.add_argument("--confirm-rejected", action="store_true")
    rebuild_category_covers.set_defaults(handler=command_rebuild_category_covers)

    prepare_category_cover_regeneration = subparsers.add_parser("prepare-category-cover-regeneration")
    prepare_category_cover_regeneration.add_argument(
        "--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS)
    )
    prepare_category_cover_regeneration.add_argument("--batch-dir")
    prepare_category_cover_regeneration.add_argument(
        "--group-start", type=int, default=PIPE_SAMPLE_GROUP_START
    )
    prepare_category_cover_regeneration.add_argument(
        "--group-count", type=int, default=PIPE_SAMPLE_GROUP_COUNT
    )
    prepare_category_cover_regeneration.add_argument("--phone")
    prepare_category_cover_regeneration.add_argument("--reason", required=True)
    prepare_category_cover_regeneration.add_argument("--confirm-rejected", action="store_true")
    prepare_category_cover_regeneration.set_defaults(
        handler=command_prepare_category_cover_regeneration
    )

    prepare_category_detail_regeneration = subparsers.add_parser("prepare-category-detail-regeneration")
    prepare_category_detail_regeneration.add_argument(
        "--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS)
    )
    prepare_category_detail_regeneration.add_argument("--batch-dir")
    prepare_category_detail_regeneration.add_argument("--group-start", type=int, required=True)
    prepare_category_detail_regeneration.add_argument("--group-count", type=int, default=1)
    prepare_category_detail_regeneration.add_argument("--generation-target-id", required=True)
    prepare_category_detail_regeneration.add_argument("--phone")
    prepare_category_detail_regeneration.add_argument("--reason", required=True)
    prepare_category_detail_regeneration.add_argument("--confirm-rejected", action="store_true")
    prepare_category_detail_regeneration.set_defaults(
        handler=command_prepare_category_detail_regeneration
    )

    authorize_category_images = subparsers.add_parser("authorize-category-images")
    authorize_category_images.add_argument("--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS))
    authorize_category_images.add_argument("--batch-dir")
    authorize_category_images.add_argument("--group-start", type=int, default=PIPE_SAMPLE_GROUP_START)
    authorize_category_images.add_argument("--group-count", type=int, default=PIPE_SAMPLE_GROUP_COUNT)
    authorize_category_images.add_argument("--scope", required=True, choices=["covers", "details", "all"])
    authorize_category_images.add_argument("--phone")
    authorize_category_images.add_argument("--generation-target-id")
    authorize_category_images.add_argument("--generation-profile", choices=category_generation_profile.PROFILE_IDS)
    authorize_category_images.add_argument("--plan-sha256", required=True)
    authorize_category_images.add_argument("--max-requests", type=int, required=True)
    authorize_category_images.add_argument(
        "--auto-retry-limit", type=int, choices=[0, 1], default=0
    )
    authorize_category_images.add_argument("--max-workers", type=int)
    authorize_category_images.add_argument(
        "--concurrency-policy",
        choices=["adaptive", "fixed-10"],
        default="adaptive",
    )
    authorize_category_images.add_argument("--api-key-slot", action="append", type=int)
    authorize_category_images.add_argument("--confirm-paid", action="store_true")
    authorize_category_images.add_argument("--confirm-third-party", action="store_true")
    authorize_category_images.add_argument(
        "--review-after-batch",
        action="store_true",
        help="兼容旧命令；--scope all 现在默认在全部生成后统一审核。",
    )
    authorize_category_images.set_defaults(handler=command_authorize_category_images)

    start_category_images = subparsers.add_parser("start-category-images")
    start_category_images.add_argument("--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS))
    start_category_images.add_argument("--batch-dir")
    start_category_images.add_argument("--group-start", type=int, default=PIPE_SAMPLE_GROUP_START)
    start_category_images.add_argument("--group-count", type=int, default=PIPE_SAMPLE_GROUP_COUNT)
    start_category_images.add_argument("--scope", required=True, choices=["covers", "details", "all"])
    start_category_images.add_argument("--license-id", required=True)
    start_category_images.set_defaults(handler=command_start_category_images)

    confirm_start_category_images = subparsers.add_parser("confirm-start-category-images")
    confirm_start_category_images.add_argument(
        "--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS)
    )
    confirm_start_category_images.add_argument("--batch-dir")
    confirm_start_category_images.add_argument(
        "--group-start", type=int, default=PIPE_SAMPLE_GROUP_START
    )
    confirm_start_category_images.add_argument(
        "--group-count", type=int, default=PIPE_SAMPLE_GROUP_COUNT
    )
    confirm_start_category_images.add_argument(
        "--scope", required=True, choices=["covers", "details", "all"]
    )
    confirm_start_category_images.add_argument("--phone")
    confirm_start_category_images.add_argument("--generation-target-id")
    confirm_start_category_images.add_argument("--generation-profile", choices=category_generation_profile.PROFILE_IDS)
    confirm_start_category_images.add_argument("--plan-sha256", required=True)
    confirm_start_category_images.add_argument("--max-requests", type=int, required=True)
    confirm_start_category_images.add_argument(
        "--auto-retry-limit", type=int, choices=[0, 1], default=0
    )
    confirm_start_category_images.add_argument("--max-workers", type=int)
    confirm_start_category_images.add_argument(
        "--concurrency-policy",
        choices=["adaptive", "fixed-10"],
        default="adaptive",
    )
    confirm_start_category_images.add_argument("--api-key-slot", action="append", type=int)
    confirm_start_category_images.add_argument("--confirm-paid", action="store_true")
    confirm_start_category_images.add_argument("--confirm-third-party", action="store_true")
    confirm_start_category_images.add_argument(
        "--review-after-batch",
        action="store_true",
        help="兼容旧命令；--scope all 现在默认在全部生成后统一审核。",
    )
    confirm_start_category_images.set_defaults(
        handler=command_confirm_start_category_images
    )

    provider_info = subparsers.add_parser("provider-info")
    provider_info.add_argument("provider_id")
    provider_info.set_defaults(handler=command_provider_info)

    project_status = subparsers.add_parser("project-status")
    project_status.add_argument("project_id", nargs="?", default="road_rescue")
    project_status.set_defaults(handler=command_project_status)

    confirm_contact = subparsers.add_parser("confirm-contact")
    confirm_contact.add_argument("--project-id", default="road_rescue")
    confirm_contact.add_argument("--phone", action="append", required=True)
    confirm_contact.add_argument("--confirm", action="store_true")
    confirm_contact.add_argument("--allow-placeholder", action="store_true")
    confirm_contact.set_defaults(handler=command_confirm_contact)

    create_groups = subparsers.add_parser("create-groups")
    create_groups.add_argument("--project-id", default="road_rescue")
    create_groups.add_argument("--count", type=int, required=True)
    create_groups.set_defaults(handler=command_create_groups)

    builtin_import = subparsers.add_parser("import-builtin-images")
    builtin_import.add_argument("--receipt", required=True)
    builtin_import.set_defaults(handler=command_import_builtin_images)

    restore_batch = subparsers.add_parser("restore-category-batch")
    restore_batch.add_argument("--category", choices=[ROAD_PROJECT_ID], required=True)
    restore_batch.set_defaults(handler=command_restore_category_batch)

    extend_category_groups = subparsers.add_parser("extend-category-groups")
    extend_category_groups.add_argument(
        "--category",
        default=ROAD_PROJECT_ID,
        choices=[ROAD_PROJECT_ID, PET_PROJECT_ID, TRUCK_PROJECT_ID, "ktv"],
    )
    extend_category_groups.add_argument("--count", type=int, required=True)
    extend_category_groups.set_defaults(handler=command_extend_category_groups)

    sync_project = subparsers.add_parser("sync-project-manifests")
    sync_project.add_argument("--project-id", default=PIPE_PROJECT_ID, choices=[PIPE_PROJECT_ID])
    sync_project.add_argument("--batch-dir")
    sync_project.add_argument("--project-group-start", type=int, default=1)
    sync_project.set_defaults(handler=command_sync_project_manifests)

    inventory_audit = subparsers.add_parser("inventory-audit")
    inventory_audit.add_argument("--project-id", default=PIPE_PROJECT_ID)
    inventory_audit.add_argument("--refresh-contact-sheet", action="store_true")
    inventory_audit.set_defaults(handler=command_inventory_audit)

    inventory_register = subparsers.add_parser("inventory-register")
    inventory_register.add_argument("--project-id", default=PIPE_PROJECT_ID)
    inventory_register.add_argument("--group-start", type=int, required=True)
    inventory_register.add_argument("--group-count", type=int, required=True)
    inventory_register.add_argument("--confirm-reviewed", action="store_true")
    inventory_register.add_argument("--confirm-near-duplicates", action="store_true")
    inventory_register.set_defaults(handler=command_inventory_register)

    inventory_used = subparsers.add_parser("inventory-mark-used")
    inventory_used.add_argument("--project-id", default=PIPE_PROJECT_ID)
    inventory_used.add_argument("--group-index", type=int, required=True)
    inventory_used.add_argument("--confirm", action="store_true")
    inventory_used.set_defaults(handler=command_inventory_mark_used)

    approve_pipe_covers = subparsers.add_parser("approve-pipe-sample-covers")
    approve_pipe_covers.add_argument("--group-start", type=int, default=PIPE_SAMPLE_GROUP_START)
    approve_pipe_covers.add_argument("--group-count", type=int, default=PIPE_SAMPLE_GROUP_COUNT)
    approve_pipe_covers.add_argument("--note", required=True)
    approve_pipe_covers.add_argument("--confirm", action="store_true")
    approve_pipe_covers.set_defaults(handler=command_approve_pipe_sample_covers)

    approve_category_covers = subparsers.add_parser("approve-category-sample-covers")
    approve_category_covers.add_argument("--category", required=True, choices=sorted(CATEGORY_IMAGE_PROJECT_IDS))
    approve_category_covers.add_argument("--group-start", type=int, default=PIPE_SAMPLE_GROUP_START)
    approve_category_covers.add_argument("--group-count", type=int, default=PIPE_SAMPLE_GROUP_COUNT)
    approve_category_covers.add_argument("--phone")
    approve_category_covers.add_argument("--note", required=True)
    approve_category_covers.add_argument("--confirm", action="store_true")
    approve_category_covers.set_defaults(handler=command_approve_category_sample_covers)

    for command_name, handler in [("group-plan", command_group_plan), ("group-audit", command_group_audit)]:
        command_parser = subparsers.add_parser(command_name)
        command_parser.add_argument("--project-id", default="road_rescue")
        command_parser.add_argument("--group-start", type=int, required=True)
        command_parser.add_argument("--group-count", type=int, required=True)
        command_parser.set_defaults(handler=handler)

    add_phone_bars = subparsers.add_parser("add-cover-phone-bars")
    add_phone_bars.add_argument("--project-id", default="road_rescue")
    add_phone_bars.add_argument("--group-start", type=int, required=True)
    add_phone_bars.add_argument("--group-count", type=int, required=True)
    add_phone_bars.add_argument("--phone")
    add_phone_bars.add_argument("--remove-red-banner", action="store_true")
    add_phone_bars.set_defaults(handler=command_add_cover_phone_bars)

    authorize_groups = subparsers.add_parser("authorize-groups")
    authorize_groups.add_argument("--project-id", default="road_rescue")
    authorize_groups.add_argument("--group-start", type=int, required=True)
    authorize_groups.add_argument("--group-count", type=int, required=True)
    authorize_groups.add_argument("--max-requests", type=int, required=True)
    authorize_groups.add_argument("--max-attempts", type=int, default=1)
    authorize_groups.add_argument("--api-key-slot", type=int, action="append")
    authorize_groups.add_argument("--confirm-paid", action="store_true")
    authorize_groups.set_defaults(handler=command_authorize_groups)

    start_groups = subparsers.add_parser("start-groups")
    start_groups.add_argument("--project-id", default="road_rescue")
    start_groups.add_argument("--group-start", type=int, required=True)
    start_groups.add_argument("--group-count", type=int, required=True)
    start_groups.add_argument("--max-failures", type=int)
    start_groups.add_argument("--api-key-slot", type=int, action="append")
    start_groups.set_defaults(handler=command_start_groups)

    validate_cover = subparsers.add_parser("validate-cover")
    validate_cover.add_argument("--group-index", type=int, required=True)
    validate_cover.set_defaults(handler=command_validate_cover)

    approve_cover = subparsers.add_parser("approve-cover-manual")
    approve_cover.add_argument("--group-index", type=int, required=True)
    approve_cover.add_argument("--note", required=True)
    approve_cover.add_argument("--confirm", action="store_true")
    approve_cover.set_defaults(handler=command_approve_cover_manual)

    cover_samples = subparsers.add_parser("prepare-cover-samples")
    cover_samples.add_argument("--project-id", default="road_rescue")
    cover_samples.add_argument("--count", type=int, default=2)
    cover_samples.add_argument("--era-profile", choices=["maintained_2014_2018", "balanced_2019_2022", "current_2023_2026"])
    cover_samples.set_defaults(handler=command_prepare_cover_samples)

    create_project = subparsers.add_parser("create-project")
    create_project.add_argument("--project-id", required=True)
    create_project.add_argument("--name", required=True)
    create_project.add_argument("--category", required=True)
    create_project.add_argument("--cover-count", type=int, default=1)
    create_project.add_argument("--detail-count", type=int, default=8)
    create_project.set_defaults(handler=command_create_project)

    register_reference = subparsers.add_parser("register-reference")
    register_reference.add_argument("--project-id", required=True)
    register_reference.add_argument("--role", choices=["cover", "detail"], required=True)
    register_reference.add_argument("--file", required=True)
    register_reference.set_defaults(handler=command_register_reference)

    approve_style = subparsers.add_parser("approve-style")
    approve_style.add_argument("--project-id", required=True)
    approve_style.add_argument("--role", choices=["cover", "detail"], required=True)
    approve_style.add_argument("--confirm", action="store_true")
    approve_style.set_defaults(handler=command_approve_style)

    project_feedback = subparsers.add_parser("project-feedback")
    project_feedback.add_argument("--project-id", required=True)
    project_feedback.add_argument("--role", choices=["cover", "detail"], required=True)
    project_feedback.add_argument("--rating", choices=["like", "dislike"], required=True)
    project_feedback.add_argument("--image", required=True)
    project_feedback.add_argument("--note", required=True)
    project_feedback.set_defaults(handler=command_project_feedback)

    tune_guide = subparsers.add_parser("tune-prompt-guide")
    tune_guide.add_argument("--project-id", default="road_rescue")
    tune_guide.set_defaults(handler=command_tune_prompt_guide)

    tune_prompt = subparsers.add_parser("tune-prompt")
    tune_prompt.add_argument("--project-id", default="road_rescue")
    tune_prompt.add_argument("--role", choices=["cover", "detail"], default="cover")
    tune_prompt.add_argument("--dimension", required=True)
    tune_prompt.add_argument("--action", choices=["strengthen", "weaken", "add", "remove", "keep"], required=True)
    tune_prompt.add_argument("--note", required=True)
    tune_prompt.set_defaults(handler=command_tune_prompt)

    approve_tuning = subparsers.add_parser("approve-prompt-tuning")
    approve_tuning.add_argument("--project-id", default="road_rescue")
    approve_tuning.add_argument("--confirm", action="store_true")
    approve_tuning.set_defaults(handler=command_approve_prompt_tuning)

    discard_tuning = subparsers.add_parser("discard-prompt-tuning")
    discard_tuning.add_argument("--project-id", default="road_rescue")
    discard_tuning.set_defaults(handler=command_discard_prompt_tuning)

    tuning_status = subparsers.add_parser("tuning-status")
    tuning_status.add_argument("--project-id", default="road_rescue")
    tuning_status.set_defaults(handler=command_tuning_status)

    setup_api = subparsers.add_parser("setup-api")
    setup_api.add_argument("--check", action="store_true", help="Only check SDK and environment-variable readiness")
    setup_api.set_defaults(handler=command_setup_api)

    setup_relay = subparsers.add_parser("setup-relay")
    setup_relay.set_defaults(handler=command_setup_relay)

    configure_relay = subparsers.add_parser("configure-relay")
    configure_relay.add_argument("--docs-url", required=True)
    configure_relay.add_argument("--base-url", required=True)
    configure_relay.add_argument("--model", required=True)
    configure_relay.add_argument("--confirm-third-party", action="store_true")
    configure_relay.set_defaults(handler=command_configure_relay)

    reset_provider = subparsers.add_parser("reset-provider")
    reset_provider.set_defaults(handler=command_reset_provider)

    test_relay = subparsers.add_parser("test-relay")
    test_relay.add_argument("--confirm-network", action="store_true")
    test_relay.add_argument("--model", help="Only check model-list availability; does not generate or change config")
    test_relay.set_defaults(handler=command_test_relay)

    test_image = subparsers.add_parser("test-image")
    test_image.add_argument("--prompt", required=True)
    test_image.add_argument("--api-key-slot", type=int, required=True)
    test_image.add_argument("--confirm-paid", action="store_true")
    test_image.add_argument("--confirm-third-party", action="store_true")
    test_image.set_defaults(handler=command_test_image)

    new_batch = subparsers.add_parser("new-batch")
    new_batch.add_argument("--count", type=int, default=1000)
    new_batch.set_defaults(handler=command_new_batch)

    preview = subparsers.add_parser("preview")
    preview.add_argument("--count", type=int, default=2)
    preview.set_defaults(handler=command_preview)

    feedback = subparsers.add_parser("feedback")
    feedback.add_argument("--index", type=int, required=True)
    feedback.add_argument("--rating", choices=["like", "dislike"], required=True)
    feedback.add_argument("--note", required=True)
    feedback.set_defaults(handler=command_feedback)

    authorize = subparsers.add_parser("authorize")
    authorize.add_argument("--count", type=int, required=True)
    authorize.add_argument("--start", type=int)
    authorize.add_argument("--end", type=int)
    authorize.add_argument("--confirm-paid", action="store_true")
    authorize.set_defaults(handler=command_authorize)

    run = subparsers.add_parser("run")
    run.add_argument("--count", type=int, required=True)
    run.add_argument("--start", type=int)
    run.add_argument("--end", type=int)
    run.set_defaults(handler=command_run)

    start = subparsers.add_parser("start")
    start.add_argument("--count", type=int, required=True)
    start.add_argument("--start", type=int)
    start.add_argument("--end", type=int)
    start.set_defaults(handler=command_start)

    job_status = subparsers.add_parser("job-status")
    job_status.add_argument("job_id", nargs="?")
    job_status.add_argument("--limit", type=int, default=5)
    job_status.set_defaults(handler=command_job_status)

    resume = subparsers.add_parser("resume")
    resume.add_argument("--count", type=int, required=True)
    resume.add_argument("--start", type=int)
    resume.add_argument("--end", type=int)
    resume.set_defaults(handler=command_run)
    variable_catalog.add_arguments(subparsers)
    from tools import task_library
    task_library.add_arguments(subparsers)
    from tools import rule_updates
    rule_updates.add_arguments(subparsers)
    return parser


def main() -> None:
    _category_utf8_console()
    args = build_parser().parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
