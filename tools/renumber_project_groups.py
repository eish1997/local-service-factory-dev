#!/usr/bin/env python3
"""Drop an initial group range and compact one project's group numbering safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
GROUP_PATTERN = re.compile(r"^group_(\d{4})$")
BACKUP_PATTERN = re.compile(r"^group_(\d{4})(_.+)$")
DETAILS = [
    ("washing_machine_repair", "洗衣机维修"),
    ("ac_refrigerant", "空调加氟"),
    ("ac_installation", "空调移机安装"),
    ("range_hood_repair", "油烟机维修"),
    ("water_heater_repair", "热水器维修"),
    ("gas_stove_repair", "燃气灶维修"),
    ("phone_repair", "手机维修"),
    ("computer_repair", "电脑维修"),
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_text(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def replace_group_path(value: Any, old_group: int, new_group: int) -> Any:
    if not isinstance(value, str):
        return value
    return value.replace(f"group_{old_group:04d}", f"group_{new_group:04d}")


def legacy_rows(project_id: str, group_index: int, phone: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    group_dir = Path("output") / project_id / f"group_{group_index:04d}"
    cover_prompt = (
        f"Reuse-only preserved legacy cover for {project_id} group {group_index}; "
        "the existing final PNG or local raw source must be reused."
    )
    cover = {
        "project_id": project_id,
        "group_index": group_index,
        "role": "cover",
        "prompt": cover_prompt,
        "prompt_sha256": prompt_hash(cover_prompt),
        "phone_bar": True,
        "phones": [phone],
        "generation_policy": "reuse_only",
    }
    details: list[dict[str, Any]] = []
    production: list[dict[str, Any]] = [{
        "project_id": project_id,
        "group_index": group_index,
        "position": 1,
        "role": "cover",
        "filename": "01_cover.png",
        "target": str(group_dir / "01_cover.png"),
        "prompt": cover_prompt,
        "prompt_sha256": cover["prompt_sha256"],
        "source": str(group_dir / "raw" / "cover_raw.png"),
        "expected_text": [phone],
        "phone_bar_text": phone,
        "generation_policy": "reuse_only",
    }]
    group_details = []
    for offset, (slug, title) in enumerate(DETAILS, start=1):
        index = (group_index - 1) * 8 + offset
        position = offset + 1
        prompt = (
            f"Reuse-only preserved legacy {title} image for {project_id} group {group_index}; "
            "the existing final PNG or local raw source must be reused."
        )
        digest = prompt_hash(prompt)
        details.append({
            "project_id": project_id,
            "index": index,
            "group_index": group_index,
            "position": position,
            "role": "detail",
            "title": title,
            "slug": slug,
            "prompt": prompt,
            "prompt_sha256": digest,
            "generation_policy": "reuse_only",
        })
        filename = f"{position:02d}_detail_{slug}.png"
        production.append({
            "project_id": project_id,
            "group_index": group_index,
            "position": position,
            "role": "detail",
            "detail_index": index,
            "filename": filename,
            "target": str(group_dir / filename),
            "prompt": prompt,
            "prompt_sha256": digest,
            "source": str(group_dir / "raw" / f"{slug}_raw.png"),
            "expected_text": [],
            "local_label": title,
            "generation_policy": "reuse_only",
        })
        group_details.append({"index": index, "position": position, "title": title, "slug": slug})
    group = {
        "project_id": project_id,
        "group_index": group_index,
        "cover": {"group_index": group_index, "position": 1},
        "details": group_details,
        "total_images": 9,
        "generation_policy": "reuse_only",
    }
    return group, cover, details, production


def assert_within(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    root = parent.resolve()
    if resolved == root or root not in resolved.parents:
        raise RuntimeError(f"unsafe path outside intended root: {resolved}")


def preflight(project_id: str, drop_count: int) -> dict[str, Any]:
    import sys

    sys.path.insert(0, str(ROOT))
    import factory

    active = [job["job_id"] for job in factory.active_group_jobs() if job.get("project_id") == project_id]
    if active:
        raise RuntimeError(f"active production jobs exist: {active}")
    project_dir = ROOT / "projects" / project_id
    output_dir = ROOT / "output" / project_id
    runtime_dir = ROOT / ".runtime" / "projects" / project_id
    for path, parent in [(project_dir, ROOT / "projects"), (output_dir, ROOT / "output"), (runtime_dir, ROOT / ".runtime" / "projects")]:
        assert_within(path, parent)
    registry = load_json(project_dir / "groups" / "registry.json")
    final_old_group = int(registry["created_groups"])
    expected = list(range(1, final_old_group + 1))
    registry_groups = [int(item["group_index"]) for item in registry["groups"]]
    disk_groups = sorted(
        int(match.group(1))
        for path in output_dir.iterdir()
        if path.is_dir() and (match := GROUP_PATTERN.match(path.name))
    )
    if registry_groups != expected or disk_groups != expected:
        raise RuntimeError("registry or output groups are not a contiguous 1..N range")
    if not 0 < drop_count < final_old_group:
        raise ValueError("drop_count must leave at least one group")
    manifest_groups = {
        int(row["group_index"])
        for row in load_jsonl(project_dir / "groups" / "production_manifest.jsonl")
    }
    if min(manifest_groups) != 16 or max(manifest_groups) != final_old_group:
        raise RuntimeError(f"unexpected production manifest range: {min(manifest_groups)}..{max(manifest_groups)}")
    return {
        "project_dir": project_dir,
        "output_dir": output_dir,
        "runtime_dir": runtime_dir,
        "registry": registry,
        "final_old_group": final_old_group,
        "final_new_group": final_old_group - drop_count,
    }


def transform_metadata(state: dict[str, Any], project_id: str, drop_count: int, phone: str) -> None:
    project_dir: Path = state["project_dir"]
    final_old_group = state["final_old_group"]
    final_new_group = state["final_new_group"]
    index_shift = drop_count * 8

    old_group_manifest = load_jsonl(project_dir / "groups" / "group_manifest.jsonl")
    old_covers = load_jsonl(project_dir / "prompts" / "cover_prompts.jsonl")
    old_details = load_jsonl(project_dir / "prompts" / "detail_prompts.jsonl")
    old_production = load_jsonl(project_dir / "groups" / "production_manifest.jsonl")
    groups: list[dict[str, Any]] = []
    covers: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    production: list[dict[str, Any]] = []
    for group_index in (1, 2):
        group, cover, detail_rows, production_rows = legacy_rows(project_id, group_index, phone)
        groups.append(group)
        covers.append(cover)
        details.extend(detail_rows)
        production.extend(production_rows)
    for row in old_group_manifest:
        old_group = int(row["group_index"])
        if old_group <= drop_count:
            continue
        new_group = old_group - drop_count
        row["group_index"] = new_group
        row["cover"]["group_index"] = new_group
        for item in row["details"]:
            item["index"] = int(item["index"]) - index_shift
        groups.append(row)
    for row in old_covers:
        old_group = int(row["group_index"])
        if old_group > drop_count:
            row["group_index"] = old_group - drop_count
            covers.append(row)
    for row in old_details:
        old_group = int(row["group_index"])
        if old_group > drop_count:
            row["group_index"] = old_group - drop_count
            row["index"] = int(row["index"]) - index_shift
            details.append(row)
    for row in old_production:
        old_group = int(row["group_index"])
        if old_group <= drop_count:
            continue
        new_group = old_group - drop_count
        row["group_index"] = new_group
        if "detail_index" in row:
            row["detail_index"] = int(row["detail_index"]) - index_shift
        for key in ("target", "source"):
            row[key] = replace_group_path(row.get(key), old_group, new_group)
        production.append(row)

    groups.sort(key=lambda row: int(row["group_index"]))
    covers.sort(key=lambda row: int(row["group_index"]))
    details.sort(key=lambda row: int(row["index"]))
    production.sort(key=lambda row: (int(row["group_index"]), int(row["position"])))
    write_jsonl(project_dir / "groups" / "group_manifest.jsonl", groups)
    write_jsonl(project_dir / "prompts" / "cover_prompts.jsonl", covers)
    write_jsonl(project_dir / "prompts" / "detail_prompts.jsonl", details)
    write_jsonl(project_dir / "groups" / "production_manifest.jsonl", production)
    registry = state["registry"]
    registry["created_groups"] = final_new_group
    registry["next_group_index"] = final_new_group + 1
    registry["groups"] = [{"group_index": index} for index in range(1, final_new_group + 1)]
    write_json(project_dir / "groups" / "registry.json", registry)
    project = load_json(project_dir / "project.json")
    project["prompt_sources"]["detail_prompt_count"] = len(details)
    project["prompt_sources"]["available_complete_detail_sets"] = final_new_group
    write_json(project_dir / "project.json", project)


def move_output_groups(state: dict[str, Any], migration_dir: Path, drop_count: int) -> None:
    output_dir: Path = state["output_dir"]
    final_old_group = state["final_old_group"]
    deleted_dir = migration_dir / "deleted_groups"
    deleted_dir.mkdir(parents=True, exist_ok=False)
    for old_group in range(1, drop_count + 1):
        source = output_dir / f"group_{old_group:04d}"
        assert_within(source, output_dir)
        shutil.move(str(source), str(deleted_dir / source.name))
    for old_group in range(drop_count + 1, final_old_group + 1):
        source = output_dir / f"group_{old_group:04d}"
        temporary = output_dir / f".renumber_tmp_{old_group:04d}"
        assert_within(source, output_dir)
        assert_within(temporary, output_dir)
        source.rename(temporary)
    for old_group in range(drop_count + 1, final_old_group + 1):
        temporary = output_dir / f".renumber_tmp_{old_group:04d}"
        target = output_dir / f"group_{old_group - drop_count:04d}"
        temporary.rename(target)
        for validation in target.rglob("*.json"):
            try:
                payload = load_json(validation)
            except Exception:
                continue
            changed = False
            if isinstance(payload, dict) and isinstance(payload.get("image"), str):
                new_image = replace_group_path(payload["image"], old_group, old_group - drop_count)
                changed = new_image != payload["image"]
                payload["image"] = new_image
            if isinstance(payload, dict) and payload.get("group_index") == old_group:
                payload["group_index"] = old_group - drop_count
                changed = True
            if changed:
                write_json(validation, payload)


def rename_runtime_backups(state: dict[str, Any], migration_dir: Path, drop_count: int) -> None:
    runtime_dir: Path = state["runtime_dir"]
    if not runtime_dir.exists():
        return
    deleted = migration_dir / "deleted_runtime_backups"
    for directory_name in ("cover_phone_bar_backups", "detail_label_backups"):
        directory = runtime_dir / directory_name
        if not directory.is_dir():
            continue
        staged: list[tuple[Path, Path, int]] = []
        for source in directory.iterdir():
            match = BACKUP_PATTERN.match(source.name)
            if not source.is_file() or not match:
                continue
            old_group = int(match.group(1))
            if old_group <= drop_count:
                target_dir = deleted / directory_name
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target_dir / source.name))
                continue
            temporary = directory / f".renumber_tmp_{old_group:04d}{match.group(2)}"
            source.rename(temporary)
            staged.append((temporary, directory / f"group_{old_group - drop_count:04d}{match.group(2)}", old_group))
        for temporary, target, _ in staged:
            temporary.rename(target)


def verify(state: dict[str, Any], project_id: str) -> dict[str, Any]:
    project_dir: Path = state["project_dir"]
    output_dir: Path = state["output_dir"]
    final_new_group = state["final_new_group"]
    expected_groups = set(range(1, final_new_group + 1))
    disk_groups = {
        int(match.group(1))
        for path in output_dir.iterdir()
        if path.is_dir() and (match := GROUP_PATTERN.match(path.name))
    }
    files = {
        "group_manifest": project_dir / "groups" / "group_manifest.jsonl",
        "cover_prompts": project_dir / "prompts" / "cover_prompts.jsonl",
        "detail_prompts": project_dir / "prompts" / "detail_prompts.jsonl",
        "production_manifest": project_dir / "groups" / "production_manifest.jsonl",
    }
    rows = {name: load_jsonl(path) for name, path in files.items()}
    if disk_groups != expected_groups:
        raise RuntimeError("renumbered output groups are not contiguous")
    for name in ("group_manifest", "cover_prompts", "detail_prompts", "production_manifest"):
        groups = {int(row["group_index"]) for row in rows[name]}
        if groups != expected_groups:
            raise RuntimeError(f"{name} does not cover groups 1..{final_new_group}")
    if len(rows["group_manifest"]) != final_new_group:
        raise RuntimeError("group manifest row count mismatch")
    if len(rows["cover_prompts"]) != final_new_group:
        raise RuntimeError("cover prompt row count mismatch")
    if len(rows["detail_prompts"]) != final_new_group * 8:
        raise RuntimeError("detail prompt row count mismatch")
    if len(rows["production_manifest"]) != final_new_group * 9:
        raise RuntimeError("production manifest row count mismatch")
    missing_targets = [row["target"] for row in rows["production_manifest"] if not (ROOT / row["target"]).is_file()]
    if missing_targets:
        raise RuntimeError(f"production targets missing after renumber: {missing_targets[:3]}")
    registry = load_json(project_dir / "groups" / "registry.json")
    if registry["created_groups"] != final_new_group or registry["next_group_index"] != final_new_group + 1:
        raise RuntimeError("registry counts mismatch")
    return {
        "project_id": project_id,
        "groups": final_new_group,
        "images": len(rows["production_manifest"]),
        "missing_targets": 0,
        "metadata_groups": [1, final_new_group],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--drop-count", type=int, required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    state = preflight(args.project_id, args.drop_count)
    summary = {
        "project_id": args.project_id,
        "drop_groups": [1, args.drop_count],
        "move_groups": [args.drop_count + 1, state["final_old_group"]],
        "new_groups": [1, state["final_new_group"]],
        "new_image_slots": state["final_new_group"] * 9,
        "api_called": False,
    }
    if not args.apply:
        print(json.dumps({"dry_run": True, **summary}, ensure_ascii=False, indent=2))
        return 0
    migration_id = datetime.now(timezone.utc).strftime(f"{args.project_id}-drop-0001-{args.drop_count:04d}-%Y%m%dT%H%M%SZ")
    migration_dir = ROOT / ".runtime" / "migrations" / migration_id
    migration_dir.mkdir(parents=True, exist_ok=False)
    metadata_backup = migration_dir / "metadata_before"
    metadata_backup.mkdir()
    for relative in (
        "project.json",
        "groups/registry.json",
        "groups/group_manifest.jsonl",
        "groups/production_manifest.jsonl",
        "prompts/cover_prompts.jsonl",
        "prompts/detail_prompts.jsonl",
    ):
        source = state["project_dir"] / relative
        target = metadata_backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    write_json(migration_dir / "plan.json", summary)
    move_output_groups(state, migration_dir, args.drop_count)
    rename_runtime_backups(state, migration_dir, args.drop_count)
    transform_metadata(state, args.project_id, args.drop_count, args.phone)
    result = verify(state, args.project_id)
    write_json(migration_dir / "result.json", result)
    print(json.dumps({"dry_run": False, "migration_dir": str(migration_dir), **summary, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
