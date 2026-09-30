"""Controlled continuation of one consumed category-image production job.

The worker never creates or reactivates a production license.  It binds a
single-use resume authorization to a read-only ``build_resume_plan`` snapshot,
continues the original request ledger, and appends to the original event log.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import image_generate
from tools import category_image_production as production
from tools import category_image_resume
from tools import category_generation_profile
from tools import image_download_receipts


AUTHORIZATION_KIND = "category-image-resume-authorization"
AUTHORIZATION_SCHEMA_VERSION = 1
PARALLEL_RESUME_POLICY = "probe_then_2_then_4_policy_circuit_v1"
SERIAL_RESUME_POLICY = "serial_probe_policy_circuit_v1"
FIXED_TEN_RESUME_POLICY = "fixed_10_probe_policy_circuit_v1"
RESUME_POLICY = PARALLEL_RESUME_POLICY
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z")
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BALANCE_AUTHORIZATION_FIELDS = (
    "approved_balance_recoverable_count",
    "approved_balance_recoverable_ids_sha256",
    "approved_balance_failure_request_count",
    "approved_additional_recovery_request_budget",
)


class ResumeExecutionError(RuntimeError):
    """The continuation cannot proceed without violating frozen authority."""


class _BalanceCircuitOpen(ResumeExecutionError):
    """A worker reached the reservation gate for a quarantined API key slot."""


class _RequestBudgetExhausted(ResumeExecutionError):
    """The amended run drained its exact cumulative request allowance."""


class _RawContractCircuitOpen(ResumeExecutionError):
    """The new profile rejected a source; do not dispatch another request."""


class _ImageDownloadCircuitOpen(ResumeExecutionError):
    """A paid URL needs download recovery; no new POST is permitted."""


_PROFILE_FIELDS = ("generation_profile", "profile_resume_policy", "profile_max_workers",
                   "profile_api_key_slots", "profile_quarantined_api_key_slots")


def _fail(message: str) -> None:
    raise ResumeExecutionError(message)


def _resume_policy_for_max_workers(max_workers: int) -> str:
    policies = {
        1: SERIAL_RESUME_POLICY,
        4: PARALLEL_RESUME_POLICY,
        10: FIXED_TEN_RESUME_POLICY,
    }
    try:
        return policies[max_workers]
    except KeyError as error:
        raise ResumeExecutionError(
            "续跑授权 max_workers 只允许保守单路1、既有上限4或显式固定10路"
        ) from error


def _is_legacy_parallel_authorization(
    authorization: dict[str, Any], plan: dict[str, Any]
) -> bool:
    """Recognize only the historical pre-policy, pre-balance 4-way schema."""

    return (
        authorization.get("max_workers") == 4
        and "resume_policy" not in authorization
        and all(key not in authorization for key in _BALANCE_AUTHORIZATION_FIELDS)
        and int(plan["counts"].get("balance_recoverable", 0)) == 0
        and not plan.get("balance_recoverable_ids")
        and int(plan.get("balance_failure_request_count", 0)) == 0
        and max(
            0,
            int(plan["cumulative_max_requests"]) - int(plan["budget"]),
        )
        == 0
    )


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ResumeExecutionError(f"无法读取{label}：{path}") from error
    if not isinstance(value, dict):
        _fail(f"{label}必须是 JSON 对象")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as error:
        raise ResumeExecutionError(f"无法读取{label}：{path}") from error
    result: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ResumeExecutionError(f"{label}第 {number} 行不是有效 JSON") from error
        if not isinstance(value, dict):
            _fail(f"{label}第 {number} 行必须是 JSON 对象")
        result.append(value)
    if not result:
        _fail(f"{label}为空")
    return result


def _canonical_sha256(value: Any) -> str:
    material = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_path(base: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label}缺少路径")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _safe_authorization_path(batch_dir: Path, value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    expected_parent = (batch_dir / "production" / "resume_authorizations").resolve()
    if path.parent != expected_parent or path.suffix.lower() != ".json" or not path.is_file():
        _fail(f"续跑授权必须位于固定目录：{expected_parent}")
    return path


def _safe_session_path(
    batch_dir: Path, value: str | Path, authorization_id: str
) -> Path:
    path = Path(value).expanduser().resolve()
    expected_parent = (batch_dir / "production" / "resume_sessions").resolve()
    if (
        path.parent != expected_parent
        or path.name != f"{authorization_id}.json"
        or not path.is_file()
    ):
        _fail(f"续跑会话必须位于固定目录：{expected_parent}")
    return path


def _initial_session_state_allowed(
    status: Any,
    pid: Any,
    *,
    current_pid: int,
    parent_pid: int,
    allow_parent_pid: bool,
) -> bool:
    if status == "queued":
        return pid is None
    if status != "starting" or isinstance(pid, bool) or not isinstance(pid, int):
        return False
    if pid <= 0:
        return False
    if pid == current_pid:
        return True
    # On Windows a venv ``python.exe`` may be a redirector process. Popen
    # returns that launcher's PID while Python runs as its direct child. Bind
    # only that exact parent; never accept an unrelated live process.
    return allow_parent_pid and pid == parent_pid


def _validate_session(
    path: Path,
    authorization_id: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    session = _load_json(path, "续跑会话")
    expected = {
        "schema_version": 1,
        "kind": "category-image-resume-session",
        "authorization_id": authorization_id,
        "job_id": plan["job_id"],
        "license_id": plan["license_id"],
        "resume_plan_sha256": plan["resume_plan_sha256"],
    }
    for key, value in expected.items():
        if session.get(key) != value:
            _fail(f"续跑会话与冻结任务不一致：{key}")
    if (session.get("source_size_acceptance") != plan.get("source_size_acceptance")
            or ("source_size_acceptance" in session) != ("source_size_acceptance" in plan)):
        _fail("续跑会话与任务级源尺寸授权不一致")
    if "generation_profile" in plan:
        for key in _PROFILE_FIELDS:
            if session.get(key) != plan[key]:
                _fail(f"新4K续跑会话profile绑定不一致：{key}")
        for key, value in (("max_workers", plan["profile_max_workers"]),
                           ("resume_policy", plan["profile_resume_policy"]),
                           ("category_id", plan["category_id"]), ("batch_id", plan["batch_id"])):
            if session.get(key) != value:
                _fail(f"新4K续跑会话调度/身份绑定不一致：{key}")
    if not session.get("created_at"):
        _fail("续跑会话缺少 created_at")
    if not _initial_session_state_allowed(
        session.get("status"),
        session.get("pid"),
        current_pid=os.getpid(),
        parent_pid=os.getppid(),
        allow_parent_pid=os.name == "nt",
    ):
        _fail(
            "续跑会话初态必须是 queued+空PID，或 starting+当前worker PID/Windows直接launcher PID"
        )
    return session


def _validate_config(
    config: dict[str, Any], license_data: dict[str, Any],
    generation_migration: dict[str, Any] | None = None,
) -> None:
    expected = {
        "provider": license_data.get("provider"),
        "base_url": license_data.get("base_url", ""),
        "model": license_data.get("model"),
        "quality": license_data.get("quality"),
        "api_size": license_data.get("size"),
    }
    if generation_migration is not None:
        expected.update(generation_migration["new_generation"])
    for key, value in expected.items():
        actual = config.get(key)
        if key == "base_url":
            actual = str(actual or "").rstrip("/")
            value = str(value or "").rstrip("/")
        if actual != value:
            _fail(f"当前 API 配置与冻结许可证不一致：{key}")


def _rebuild_generation_migration(
    batch: Path, plan: dict[str, Any], license_data: dict[str, Any],
    events: list[dict[str, Any]], authorization: dict[str, Any],
) -> tuple[dict[str, Any], Path | None]:
    """Reconstruct migration only from the precise consumed prior authority."""

    migration = authorization.get("generation_migration")
    if migration is None and "generation_migration" not in authorization:
        return plan, None
    if not isinstance(migration, dict) or authorization.get("generation_migration_confirmed") is not True:
        _fail("生成参数迁移缺少明确的一次性授权确认")
    previous_id = str(migration.get("previous_authorization_id") or "")
    if not _SAFE_ID.fullmatch(previous_id) or previous_id == authorization.get("authorization_id"):
        _fail("生成参数迁移的前序授权标识无效")
    previous_path = _safe_authorization_path(
        batch, batch / "production" / "resume_authorizations" / f"{previous_id}.json",
    )
    previous = _load_json(previous_path, "前序已消费续跑授权")
    new_generation = migration.get("new_generation")
    if not isinstance(new_generation, dict) or set(new_generation) != {"model", "quality", "api_size"}:
        _fail("生成参数迁移的新参数结构无效")
    from tools.category_resume_migration import apply_generation_migration

    rebuilt = apply_generation_migration(
        plan, license_data, events, previous,
        {**new_generation, "credential_epoch": migration.get("credential_epoch"),
         "rotated_slots": migration.get("rotated_slots"),
         **({"accepted_source_size": migration["accepted_source_size"]}
            if "accepted_source_size" in migration else {}),
         **({"accepted_source_width_tolerance": migration["accepted_source_width_tolerance"]}
            if "accepted_source_width_tolerance" in migration else {})},
    )
    if _canonical_sha256(rebuilt.get("generation_migration")) != _canonical_sha256(migration):
        _fail("生成参数迁移授权与原始账本重建结果不一致")
    return rebuilt, previous_path


def _rebuild_explicit_retry(
    batch: Path, plan: dict[str, Any], license_data: dict[str, Any],
    events: list[dict[str, Any]], authorization: dict[str, Any], job: dict[str, Any],
) -> tuple[dict[str, Any], Path, Path]:
    sidecar = authorization.get("explicit_retry")
    if not isinstance(sidecar, dict) or authorization.get("explicit_retry_confirmed") is not True:
        _fail("指定目标手动再试缺少明确授权")
    if "schedule_amendment" in authorization:
        _fail("指定目标手动再试不得同时变更调度")
    previous_id = str(sidecar.get("previous_authorization_id") or "")
    if not _SAFE_ID.fullmatch(previous_id) or previous_id == authorization.get("authorization_id"):
        _fail("指定目标手动再试前序授权标识无效")
    previous_path = _safe_authorization_path(
        batch, batch / "production" / "resume_authorizations" / f"{previous_id}.json",
    )
    previous = _load_json(previous_path, "前序已消费授权")
    targets = sidecar.get("targets")
    if not isinstance(targets, list) or any(not isinstance(target, dict) for target in targets):
        _fail("指定目标手动再试目标映射无效")
    from tools.category_explicit_retry import apply_explicit_retry

    rebuilt = apply_explicit_retry(
        plan, license_data, events, previous,
        [target.get("generation_target_id") for target in targets],
    )
    if _canonical_sha256(rebuilt.get("explicit_retry")) != _canonical_sha256(sidecar):
        _fail("指定目标手动再试侧车与原账本重建不一致")
    previous_session_path = _safe_session_path(
        batch, batch / "production" / "resume_sessions" / f"{previous_id}.json", previous_id,
    )
    previous_session = _load_json(previous_session_path, "前序已结束续跑会话")
    expected_session = {
        "schema_version": 1, "kind": "category-image-resume-session", "authorization_id": previous_id,
        "job_id": plan["job_id"], "license_id": plan["license_id"],
        "resume_plan_sha256": previous.get("resume_plan_sha256"),
        "status": "completed_with_errors", "pid": None,
    }
    if (
        any(previous_session.get(key) != value for key, value in expected_session.items())
        or job.get("resume_authorization_id") != previous_id
        or job.get("status") != "completed_with_errors"
        or not _HEX_SHA256.fullmatch(str(authorization.get("previous_resume_session_sha256") or ""))
        or _file_sha256(previous_session_path) != authorization["previous_resume_session_sha256"]
    ):
        _fail("指定目标手动再试前序会话不是精确绑定的已结束最新会话")
    return rebuilt, previous_path, previous_session_path


def _validate_explicit_retry_network(authorization: dict[str, Any], job: dict[str, Any]) -> None:
    mode = authorization.get("explicit_retry_network_mode")
    if (not isinstance(mode, str) or not mode.startswith("proxy:")
            or mode != job.get("network_mode") or mode != os.environ.get("PIPE_CATEGORY_NETWORK_MODE")):
        _fail("指定目标手动再试不得变更原网络线路")
    proxy = mode[len("proxy:"):]
    for name in ("HTTP_PROXY", "HTTPS_PROXY"):
        if os.environ.get(name) != proxy:
            _fail("指定目标手动再试代理环境与原线路不一致")
    for name in ("ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        if os.environ.get(name) and os.environ[name] != proxy:
            _fail("指定目标手动再试存在不同的代理环境")
    from urllib.parse import urlsplit

    hostname = str(urlsplit(str(authorization.get("base_url") or "")).hostname or "").lower()
    if not hostname:
        _fail("指定目标手动再试缺少明确服务端地址")
    for name in ("NO_PROXY", "no_proxy"):
        for value in os.environ.get(name, "").split(","):
            domain = value.strip().lower().lstrip(".").split(":", 1)[0]
            if domain == "*" or (domain and (hostname == domain or hostname.endswith("." + domain))):
                _fail("指定目标手动再试代理绕过配置覆盖服务端地址")


def _validate_authorization(
    path: Path,
    plan: dict[str, Any],
    license_data: dict[str, Any],
    requested_plan_sha256: str,
    *,
    license_path: Path,
    job_path: Path,
) -> dict[str, Any]:
    authorization = _load_json(path, "一次性续跑授权")
    authorization_id = str(authorization.get("authorization_id") or "")
    if not _SAFE_ID.fullmatch(authorization_id):
        _fail("续跑授权缺少安全 authorization_id")
    if path.name != f"{authorization_id}.json":
        _fail("续跑授权文件名与 authorization_id 不一致")
    if authorization.get("schema_version") != AUTHORIZATION_SCHEMA_VERSION:
        _fail("不支持的续跑授权 schema_version")
    if (
        authorization.get("kind") != AUTHORIZATION_KIND
        or authorization.get("status") != "active"
        or authorization.get("one_time") is not True
    ):
        _fail("续跑授权不是有效的 active 一次性授权")
    if not _HEX_SHA256.fullmatch(requested_plan_sha256):
        _fail("调用参数 resume_plan_sha256 无效")
    if requested_plan_sha256 != plan.get("resume_plan_sha256"):
        _fail("调用参数与当前冻结恢复计划哈希不一致")
    if (authorization.get("source_size_acceptance") != plan.get("source_size_acceptance")
            or ("source_size_acceptance" in authorization) != ("source_size_acceptance" in plan)):
        _fail("续跑授权与任务级源尺寸授权不一致")
    max_workers = authorization.get("max_workers")
    if isinstance(max_workers, bool) or not isinstance(max_workers, int):
        _fail("续跑授权 max_workers 必须是整数")
    profile = plan.get("generation_profile")
    if profile is not None:
        category_generation_profile.validate_profile(profile, str(plan["category_id"]))
        if (max_workers != plan["profile_max_workers"] or not 1 <= max_workers <= 10
                or any(key in authorization for key in ("generation_migration", "schedule_amendment", "explicit_retry"))):
            _fail("新4K续跑必须继承原adaptive上限，不能混用迁移/调度变更/显式重试")
        expected_resume_policy = category_image_resume.PROFILE_RESUME_POLICY
        for key in _PROFILE_FIELDS:
            if authorization.get(key) != plan[key]:
                _fail(f"新4K续跑授权profile绑定不一致：{key}")
    else:
        if "generation_profile" in authorization:
            _fail("旧续跑授权不能注入未绑定的generation_profile")
        expected_resume_policy = _resume_policy_for_max_workers(max_workers)
    legacy_parallel_authorization = _is_legacy_parallel_authorization(
        authorization, plan
    )
    license_slots = license_data.get("api_key_slots")
    if not isinstance(license_slots, list):
        _fail("原许可证缺少 api_key_slots")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in license_slots
    ) or len(license_slots) != len(set(license_slots)):
        _fail("原许可证 api_key_slots 必须是唯一正整数列表")
    schedule_amendment = plan.get("schedule_amendment")
    explicit_retry = plan.get("explicit_retry")
    if explicit_retry is not None or "explicit_retry" in authorization:
        if (
            not isinstance(explicit_retry, dict)
            or authorization.get("explicit_retry_confirmed") is not True
            or _canonical_sha256(authorization.get("explicit_retry")) != _canonical_sha256(explicit_retry)
            or max_workers != 1 or schedule_amendment is not None
            or expected_resume_policy != explicit_retry.get("resume_policy")
        ):
            _fail("指定目标手动再试授权必须精确绑定单路原槽位策略")
    if schedule_amendment is not None or "schedule_amendment" in authorization:
        if (
            not isinstance(schedule_amendment, dict)
            or authorization.get("schedule_amendment_confirmed") is not True
            or _canonical_sha256(authorization.get("schedule_amendment"))
            != _canonical_sha256(schedule_amendment)
        ):
            _fail("调度变更授权与原始账本重建结果不一致")
        if max_workers != schedule_amendment["max_workers"]:
            _fail("调度变更并发上限与授权不一致")
        if expected_resume_policy != schedule_amendment["resume_policy"]:
            _fail("调度变更策略与授权不一致")
        expected_api_key_slots = list(schedule_amendment["api_key_slots"])
    elif explicit_retry is not None:
        expected_api_key_slots = list(explicit_retry["api_key_slots"])
    elif profile is not None:
        expected_api_key_slots = list(plan["profile_api_key_slots"])
    else:
        expected_api_key_slots = list(license_slots[:max_workers])
    generation_migration = plan.get("generation_migration")
    if generation_migration is not None or "generation_migration" in authorization:
        if (
            not isinstance(generation_migration, dict)
            or authorization.get("generation_migration_confirmed") is not True
            or _canonical_sha256(authorization.get("generation_migration"))
            != _canonical_sha256(generation_migration)
        ):
            _fail("生成参数迁移与授权不一致")
    approved_api_key_slots = authorization.get("api_key_slots")
    if explicit_retry is not None and approved_api_key_slots != expected_api_key_slots:
        _fail("指定目标手动再试授权缺少精确原槽位列表")
    if profile is not None:
        if approved_api_key_slots != expected_api_key_slots:
            _fail("新4K续跑授权必须绑定全部原冻结槽位")
    elif max_workers == 10:
        if len(expected_api_key_slots) != 10:
            _fail("固定10路续跑要求原许可证至少绑定10个 API Key 槽位")
        if approved_api_key_slots != expected_api_key_slots:
            _fail("固定10路续跑授权未精确绑定原许可证前10个 API Key 槽位")
    elif (
        approved_api_key_slots is not None
        and approved_api_key_slots != expected_api_key_slots
    ):
        _fail("续跑授权 api_key_slots 与原许可证槽位不一致")
    exact = {
        "job_id": plan["job_id"],
        "license_id": plan["license_id"],
        "category_id": plan["category_id"],
        "batch_id": plan["batch_id"],
        "resume_plan_sha256": requested_plan_sha256,
        "frozen_manifest_sha256": plan["frozen_manifest_sha256"],
        "frozen_overlay_sha256": plan["frozen_overlay_sha256"],
        "events_sha256": plan["events_sha256"],
        "event_tail_sha256": plan["event_tail_sha256"],
        "requests_used": plan["requests_used"],
        "approved_remaining_request_budget": plan["remaining_max_requests"],
        "approved_cumulative_request_budget": plan["cumulative_max_requests"],
        "approved_resumable_count": plan["counts"]["resumable"],
        "approved_resumable_ids_sha256": _canonical_sha256(plan["resumable_ids"]),
        "original_plan_sha256": license_data.get("plan_sha256"),
        "original_license_sha256": _file_sha256(license_path),
        "original_job_sha256": _file_sha256(job_path),
        "original_approved_request_budget": plan["budget"],
        "approved_exhausted_count": plan["counts"]["exhausted"],
        "approved_exhausted_ids_sha256": _canonical_sha256(plan["exhausted_ids"]),
        "attempts_used_sha256": _canonical_sha256(plan["attempts_used"]),
        "attempts_remaining_sha256": _canonical_sha256(plan["attempts_remaining"]),
        "per_target_attempts_sha256": _canonical_sha256(
            {
                "used": plan["attempts_used"],
                "remaining": plan["attempts_remaining"],
            }
        ),
        "max_attempts": plan["max_attempts"],
        "retry_policy": plan["retry_policy"],
        "provider": plan["provider"],
        "base_url": str(license_data.get("base_url") or "").rstrip("/"),
        "model": plan["model"],
        "quality": plan["quality"],
        "size": plan["size"],
        "resume_confirmed": True,
        "paid_confirmed": True,
        "third_party_confirmed": True,
    }
    if not legacy_parallel_authorization:
        exact.update(
            {
                "approved_balance_recoverable_count": plan["counts"][
                    "balance_recoverable"
                ],
                "approved_balance_recoverable_ids_sha256": _canonical_sha256(
                    plan["balance_recoverable_ids"]
                ),
                "approved_balance_failure_request_count": plan[
                    "balance_failure_request_count"
                ],
                "approved_additional_recovery_request_budget": max(
                    0,
                    int(plan["cumulative_max_requests"]) - int(plan["budget"]),
                ),
                "resume_policy": expected_resume_policy,
            }
        )
    for key, expected in exact.items():
        if authorization.get(key) != expected:
            _fail(f"续跑授权与冻结计划不一致：{key}")
    if not authorization.get("created_at"):
        _fail("续跑授权缺少 created_at")
    if int(license_data.get("approved_request_budget", -1)) != int(plan["budget"]):
        _fail("原许可证预算与恢复计划不一致")
    if license_data.get("provider") == "relay" and authorization.get("third_party_confirmed") is not True:
        _fail("第三方中转续跑授权缺少信任确认")
    additional_recovery_budget = max(
        0, int(plan["cumulative_max_requests"]) - int(plan["budget"])
    )
    if (schedule_amendment is not None or explicit_retry is not None or profile is not None) and (
        additional_recovery_budget != 0
        or int(plan["cumulative_max_requests"]) > int(plan["budget"])
        or authorization.get("approved_additional_recovery_request_budget") != 0
    ):
        _fail("调度变更不得增加原许可证请求预算")
    if additional_recovery_budget > int(plan["balance_failure_request_count"]):
        _fail("冻结恢复计划超过原许可证预算")
    return authorization


def _load_runtime_records(
    batch_dir: Path,
    manifest_path: Path,
    category_id: str,
    expected_manifest_sha256: str,
) -> list[dict[str, Any]]:
    records = production.load_frozen_manifest_runtime_records(
        batch_dir,
        manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if any(str(record.get("category_id")) != category_id for record in records):
        _fail("冻结运行记录混入其他类目")
    return records


def _consume_authorization(path: Path, authorization: dict[str, Any]) -> dict[str, Any]:
    current = _load_json(path, "一次性续跑授权")
    if current != authorization or current.get("status") != "active":
        _fail("续跑授权在执行前发生变化或已经消费")
    consumed = dict(current)
    consumed.update({"status": "consumed", "consumed_at": production.now_iso()})
    production.atomic_json(path, consumed)
    return consumed


def _append_event(path: Path, lock: threading.Lock, payload: dict[str, Any]) -> None:
    production.append_event(path, payload, lock)


def _materialize_ready_deliveries(
    delivery_records: list[dict[str, Any]],
    successful_ids: set[str],
    phone: str,
    service_items: list[str],
) -> int:
    completed = 0
    for delivery in delivery_records:
        ids = set(str(value) for value in delivery["generation_target_ids"])
        if ids.issubset(successful_ids):
            production._materialize_delivery(
                delivery,
                phone,
                service_items,
                allow_rejected_replacement=True,
            )
        if production.reusable_target(
            Path(delivery["target"]), production.parse_size(str(delivery["final_size"]))
        ):
            completed += 1
    return completed


def _materialize_explicit_deliveries(
    delivery_records: list[dict[str, Any]], successful_ids: set[str],
    selected_ids: set[str], phone: str, service_items: list[str],
) -> int:
    """Only the newly selected independent details may be materialized."""
    completed = 0
    for delivery in delivery_records:
        ids = set(str(value) for value in delivery["generation_target_ids"])
        target = Path(delivery["target"])
        reusable = production.reusable_target(target, production.parse_size(str(delivery["final_size"])))
        if not ids.intersection(selected_ids):
            if not reusable:
                _fail("指定目标再试发现非本次成品不可复用；禁止修改历史成品")
        else:
            if len(ids) != 1 or not ids.issubset(selected_ids):
                _fail("指定目标再试仅支持独立详情成品")
            if ids.issubset(successful_ids) and not reusable:
                if target.exists():
                    _fail("指定目标再试不得覆盖既有成品")
                production._materialize_delivery(delivery, phone, service_items, allow_rejected_replacement=False)
                reusable = production.reusable_target(target, production.parse_size(str(delivery["final_size"])))
        completed += int(reusable)
    return completed


def _acquire_explicit_retry_lock(batch: Path, job_id: str) -> tuple[Path, bytes]:
    """Never remove any pre-existing lock, even a dead or malformed one."""
    path = batch / "production" / "generation.lock"
    payload = json.dumps({"pid": os.getpid(), "job_id": job_id,
                          "created_at": production.now_iso()}, ensure_ascii=False).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ResumeExecutionError("指定目标再试发现既有生产锁；不会删除或归档") from error
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
    return path, payload


def _write_terminal_evidence(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ResumeExecutionError(f"不可覆盖的续跑终态证据已存在：{path}") from error
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def resume_category_images(
    batch_dir: str | Path,
    job_path: str | Path,
    license_path: str | Path,
    authorization_path: str | Path,
    resume_plan_sha256: str,
    *,
    session_path: str | Path | None = None,
    clients: list[tuple[int, Any]] | None = None,
    generate_one: Callable[[Any, dict[str, Any], str], bytes] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Continue one frozen job within its original per-target and total caps."""

    batch = Path(batch_dir).expanduser().resolve()
    job_file = Path(job_path).expanduser().resolve()
    license_file = Path(license_path).expanduser().resolve()
    if not batch.is_dir() or not job_file.is_file() or not license_file.is_file():
        _fail("批次、任务文件或许可证不存在")
    authorization_file = _safe_authorization_path(batch, authorization_path)
    authorization_preview = _load_json(authorization_file, "一次性续跑授权")
    if "schedule_amendment" in authorization_preview and (
        not isinstance(authorization_preview["schedule_amendment"], dict)
        or authorization_preview.get("schedule_amendment_confirmed") is not True
    ):
        _fail("调度变更必须有明确的一次性授权确认")
    plan = category_image_resume.build_resume_plan(batch, job_file, license_file)
    base_resume_plan = plan
    license_data = _load_json(license_file, "原生产许可证")
    job = _load_json(job_file, "原生产任务")
    source_events: list[dict[str, Any]] = []
    previous_session_path: Path | None = None
    if any(key in authorization_preview for key in (
        "schedule_amendment", "explicit_retry", "source_size_acceptance",
    )):
        source_events_path = batch / "production" / f"events_{plan['job_id']}.jsonl"
        source_events_hash = _file_sha256(source_events_path)
        source_events = _load_jsonl(
            source_events_path, "原请求事件",
        )
        if (
            source_events_hash != plan["events_sha256"]
            or _file_sha256(source_events_path) != source_events_hash
        ):
            _fail("原请求事件在调度变更核算期间发生变化")
    if "explicit_retry" in authorization_preview:
        plan, previous_authorization_path, previous_session_path = _rebuild_explicit_retry(
            batch, plan, license_data, source_events, authorization_preview, job,
        )
    elif "schedule_amendment" in authorization_preview:
        from tools.category_resume_schedule import apply_schedule_amendment

        plan = apply_schedule_amendment(
            plan, license_data, source_events,
            authorization_preview["schedule_amendment"].get("api_key_slots"),
        )
        plan, previous_authorization_path = _rebuild_generation_migration(
            batch, plan, license_data, source_events, authorization_preview,
        )
    else:
        plan, previous_authorization_path = _rebuild_generation_migration(
            batch, plan, license_data, source_events, authorization_preview,
        )
    if license_data.get("status") != "consumed" or license_data.get("one_time") is not True:
        _fail("续跑必须保持原一次性许可证为 consumed")
    if job.get("job_id") != plan["job_id"] or job.get("license_id") != plan["license_id"]:
        _fail("任务与冻结恢复计划身份不一致")
    from tools.category_process_identity import recorded_job_pid_is_running

    for pid_key in ("pid", "worker_pid"):
        pid = int(job.get(pid_key, 0) or 0)
        if pid and pid != os.getpid() and recorded_job_pid_is_running(pid, job):
            _fail(f"原生产进程仍在运行：{pid_key}={pid}")
    authorization = _validate_authorization(
        authorization_file,
        plan,
        license_data,
        resume_plan_sha256,
        license_path=license_file,
        job_path=job_file,
    )
    schedule_amendment = plan.get("schedule_amendment")
    generation_migration = plan.get("generation_migration")
    profile = plan.get("generation_profile")
    explicit_retry = plan.get("explicit_retry")
    source_size_acceptance = plan.get("source_size_acceptance")
    authorized_max_workers = int(authorization["max_workers"])
    if explicit_retry is not None:
        _validate_explicit_retry_network(authorization, job)
    resume_policy = (category_image_resume.PROFILE_RESUME_POLICY if profile is not None
                     else _resume_policy_for_max_workers(authorized_max_workers))
    session_file: Path | None = None
    session: dict[str, Any] | None = None
    if session_path is not None:
        session_file = _safe_session_path(
            batch, session_path, str(authorization["authorization_id"])
        )
        session = _validate_session(
            session_file, str(authorization["authorization_id"]), plan
        )
    manifest_path = Path(str(license_data["production_manifest"])).resolve()
    records = _load_runtime_records(
        batch,
        manifest_path,
        str(plan["category_id"]),
        str(license_data["manifest_sha256"]),
    )
    record_by_id = {str(record["generation_target_id"]): record for record in records}
    if list(record_by_id) != list(plan["attempts_used"]):
        _fail("冻结清单顺序与恢复账本不一致")
    if set(plan["resumable_ids"]) != set(
        plan["balance_recoverable_ids"]
        + plan["unknown_ids"]
        + plan["unattempted_ids"]
        + plan.get("explicit_retry_ids", [])
    ):
        _fail("恢复计划 resumable 分区无效")
    if set(plan["success_ids"] + plan["exhausted_ids"]) & set(plan["resumable_ids"]):
        _fail("成功或耗尽目标错误进入可续跑集合")
    explicit_targets = {
        target["generation_target_id"]: target for target in explicit_retry["targets"]
    } if explicit_retry is not None else {}

    def verify_explicit_target(record: dict[str, Any]) -> None:
        target_id = str(record["generation_target_id"])
        target = explicit_targets[target_id]
        if hashlib.sha256(str(record["frozen_effective_prompt"]).encode("utf-8")).hexdigest() != target["effective_prompt_sha256"]:
            _fail("指定目标手动再试的冻结原提示词与原请求不同")
        if any(Path(str(record[key])).exists() for key in ("raw_target", "target", "legacy_target") if record.get(key)):
            _fail("指定目标手动再试不得覆盖已有原图或成品")

    for target_id in explicit_targets:
        verify_explicit_target(record_by_id[target_id])

    current_config = config
    if current_config is None:
        current_config = image_generate.apply_provider_config(
            image_generate.load_json(production.ROOT / "config.json")
        )
    current_config = dict(current_config)
    if profile is not None:
        current_config = category_generation_profile.from_license(current_config, str(plan["category_id"]), license_data)
    if generation_migration is not None:
        # The original model remains bound in old evidence. Only this task's
        # request copy receives the explicitly authorized migration parameters.
        current_config.update(generation_migration["new_generation"])
    _validate_config(current_config, license_data, generation_migration)
    generation_event_fields = {
        "model": current_config.get("model"),
        "quality": current_config.get("quality"),
        "api_size": current_config.get("api_size"),
    }
    if profile is not None:
        generation_event_fields.update(category_generation_profile.event_metadata(current_config, str(plan["category_id"])))
    if source_size_acceptance is not None:
        generation_event_fields.update({
            "source_size_acceptance_sha256": source_size_acceptance["acceptance_sha256"],
            "source_size_policy": source_size_acceptance["policy_id"],
            "raw_contract": source_size_acceptance["policy_id"],
        })
    if generation_migration is not None:
        generation_event_fields["credential_epoch"] = generation_migration["credential_epoch"]
    if clients is None:
        slots = [int(value) for value in license_data.get("api_key_slots") or []]
        if authorized_max_workers == 10 or explicit_retry is not None or profile is not None:
            slots = [int(value) for value in authorization["api_key_slots"]]
        if len(slots) < authorized_max_workers:
            _fail("续跑客户端槽位少于授权并发上限")
        clients = production.openai_clients_by_slot(
            current_config, slots if explicit_retry is not None or profile is not None else slots[:authorized_max_workers]
        )
    required_clients = min(
        authorized_max_workers, max(1, len(plan["resumable_ids"]) - 1)
    )
    if not clients or len(clients) < required_clients:
        _fail("续跑客户端数量不足以执行授权调度")
    slots = [int(item[0]) for item in clients]
    if len(slots) != len(set(slots)):
        _fail("续跑客户端槽位必须唯一")
    if authorized_max_workers == 10 or profile is not None:
        approved_slots = [int(value) for value in authorization["api_key_slots"]]
        if slots != approved_slots:
            _fail("固定10路续跑客户端必须按授权顺序精确使用10个 API Key 槽位")
    if explicit_retry is not None and slots != explicit_retry["api_key_slots"]:
        _fail("指定目标手动再试客户端必须精确绑定原失败槽位")
    allowed_slots = {
        int(value) for value in (
            explicit_retry["api_key_slots"] if explicit_retry is not None else
            schedule_amendment["api_key_slots"] if schedule_amendment is not None
            else license_data.get("api_key_slots") or []
        )
    }
    if allowed_slots and not set(slots).issubset(allowed_slots):
        _fail("续跑客户端使用了原许可证之外的 API Key 槽位")
    generator = generate_one or image_generate.generate_one

    delivery_records = production._delivery_records(records)
    service_items = list(records[0].get("service_items") or [])
    phone = str(license_data["phone"])
    successful_ids = set(str(value) for value in plan["success_ids"])

    def materialize_current() -> int:
        if explicit_retry is not None:
            return _materialize_explicit_deliveries(
                delivery_records, successful_ids, set(explicit_targets), phone, service_items,
            )
        return _materialize_ready_deliveries(delivery_records, successful_ids, phone, service_items)

    if explicit_retry is not None:
        # No selected target has succeeded yet: this pass only checks history.
        materialize_current()

    unattempted = set(str(value) for value in plan["unattempted_ids"])
    balance_recoverable = set(
        str(value) for value in plan.get("balance_recoverable_ids", [])
    )
    probe_id = next(
        (target_id for target_id in plan["resumable_ids"] if target_id in unattempted),
        None,
    )
    if explicit_retry is not None:
        probe_id = plan["explicit_retry_ids"][0]
    if probe_id is None:
        probe_id = next(
            (
                target_id
                for target_id in plan["resumable_ids"]
                if target_id in balance_recoverable
            ),
            None,
        )
    if probe_id is None:
        _fail("安全续跑必须先选择一个未尝试目标作为单探针")
    ordered_ids = [probe_id] + [
        str(value) for value in plan["resumable_ids"] if str(value) != probe_id
    ]
    budget = int(plan["budget"])
    requests_used = int(plan["requests_used"])
    requests_start = requests_used
    attempts_used = {key: int(value) for key, value in plan["attempts_used"].items()}
    attempts_remaining = {
        key: int(value) for key, value in plan["attempts_remaining"].items()
    }
    if requests_used != int(license_data.get("requests_used", -1)):
        _fail("原许可证 requests_used 与恢复账本不一致")
    authorization_id = str(authorization["authorization_id"])
    events_path = batch / "production" / f"events_{plan['job_id']}.jsonl"
    terminal_path = (
        batch / "production" / "resume_summaries" / f"{authorization_id}.json"
    )
    state_lock = threading.Lock()
    event_lock = threading.Lock()
    generated_this_run: list[str] = []
    failed_this_run: list[str] = []
    retry_count = int(job.get("retry_count", 0) or 0)
    failed_request_attempts = int(job.get("failed_request_attempts", 0) or 0)
    # A validated local source recovery resolves a target, not its historical
    # failed request. Reconcile target failures without refunding API attempts.
    has_local_source_recovery = any(event.get("status") in {"provider_source_recovered", "source_size_recovered"} for event in source_events)
    unresolved_explicit = set(explicit_targets)
    cumulative_failed = (
        len(plan["exhausted_ids"]) + len(unresolved_explicit) if explicit_retry is not None else
        len(plan["exhausted_ids"]) if has_local_source_recovery else int(job.get("failed", 0) or 0)
    )
    normalized_responses = int(job.get("relay_normalized_responses", 0) or 0)
    resume_history: list[dict[str, Any]] = []
    lock_path: Path | None = None
    explicit_lock_payload: bytes | None = None
    raw_contract_stop = threading.Event()
    image_download_stop = threading.Event()
    image_download_target_ids: set[str] = set()
    quarantined_api_key_slots: set[int] = set(
        explicit_retry["effective_quarantined_api_key_slots"]
        if explicit_retry is not None else
        generation_migration["effective_quarantined_api_key_slots"]
        if generation_migration is not None else
        schedule_amendment["inherited_quarantined_api_key_slots"]
        if schedule_amendment is not None else
        plan["profile_quarantined_api_key_slots"] if profile is not None else []
    )
    balance_failure_target_ids: list[str] = []

    def update_job(**changes: Any) -> None:
        production.update_job(job_file, state_lock, **changes)

    def reserve(record: dict[str, Any], attempt: int, prompt: str, variant: str, slot: int) -> int:
        nonlocal requests_used, license_data, retry_count
        with state_lock:
            if image_download_stop.is_set():
                raise _ImageDownloadCircuitOpen("已返回图片URL但下载未完成，禁止新生图请求")
            target_id = str(record["generation_target_id"])
            try:
                image_download_receipts.assert_no_pending_for_target(
                    production.ROOT / ".runtime" / "image_download_receipts", str(plan["job_id"]), target_id,
                )
            except Exception as error:
                image_download_stop.set()
                image_download_target_ids.add(target_id)
                raise _ImageDownloadCircuitOpen("目标存在未闭合的已付费图片回执") from error
            if profile is not None and raw_contract_stop.is_set():
                raise _RawContractCircuitOpen("新4K源图契约已拒绝，停止后续请求")
            if explicit_retry is not None:
                verify_explicit_target(record)
                target = explicit_targets[str(record["generation_target_id"])]
                if (attempt != target["next_attempt"] or attempt != 2 or variant != "original"
                        or slot != target["api_key_slot"] or prompt != record["frozen_effective_prompt"]):
                    _fail("指定目标手动再试只能原槽位、原提示词执行原第2次尝试")
            if int(slot) in quarantined_api_key_slots:
                raise _BalanceCircuitOpen("余额不足的 API Key 槽位已隔离")
            next_request = requests_used + 1
            recovery_budget = budget if schedule_amendment is not None or explicit_retry is not None or profile is not None else budget + int(
                authorization.get("approved_additional_recovery_request_budget", 0)
            )
            if (schedule_amendment is not None or explicit_retry is not None or profile is not None) and next_request > min(
                recovery_budget, int(authorization["approved_cumulative_request_budget"]),
            ):
                raise _RequestBudgetExhausted("原累计请求上限已用尽")
            if next_request > recovery_budget:
                _fail("续跑请求将超过原许可证总预算")
            if next_request > int(authorization["approved_cumulative_request_budget"]):
                _fail("续跑请求将超过本次一次性授权累计上限")
            target_id = str(record["generation_target_id"])
            download_context = production.image_download_context(
                batch, str(plan["job_id"]), license_data, target_id, next_request, attempt, current_config, prompt,
            )
            try:
                image_download_receipts.preflight_context(download_context)
            except Exception as error:
                image_download_stop.set()
                image_download_target_ids.add(target_id)
                raise _ImageDownloadCircuitOpen("图片下载回执预检失败，未预留新请求") from error
            _append_event(
                events_path,
                event_lock,
                {
                    "status": "request_reserved",
                    **generation_event_fields,
                    "resume": True,
                    "authorization_id": authorization_id,
                    "resume_plan_sha256": resume_plan_sha256,
                    "raw_target": production._artifact_reference(record["raw_target"], batch),
                    "delivery_target": production._artifact_reference(record["target"], batch),
                    "generation_target_id": target_id,
                    "delivery_target_id": record["delivery_target_id"],
                    "group_index": record["group_index"],
                    "generation_position": record["generation_position"],
                    "delivery_position": record["delivery_position"],
                    "api_key_slot": slot,
                    "attempt": attempt,
                    "retry_prompt_variant": variant,
                    "effective_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "request_number": next_request,
                },
            )
            # Required ordering: durable reservation event, then durable license
            # counter, and only then the paid API call made by the caller.
            requests_used = next_request
            license_data = dict(license_data)
            license_data["requests_used"] = requests_used
            production.atomic_json(license_file, license_data)
            if attempt > 1:
                retry_count += 1
            production.update_job(
                job_file,
                None,
                status="resume_waiting_for_api",
                requests_used=requests_used,
                retry_count=retry_count,
                current_group=record["group_index"],
                current_position=record["generation_position"],
                resume_authorization_id=authorization_id,
                resume_plan_sha256=resume_plan_sha256,
            )
            return next_request

    def run_target(slot: int, client: Any, target_id: str) -> production.RequestBatchResult:
        nonlocal failed_request_attempts, cumulative_failed, normalized_responses
        record = record_by_id[target_id]
        used_before = attempts_used[target_id]
        remaining = attempts_remaining[target_id]
        if remaining < 1 or target_id in successful_ids or target_id in set(plan["exhausted_ids"]):
            _fail(f"禁止请求成功、耗尽或无剩余次数的目标：{target_id}")
        if explicit_retry is not None and (remaining != 1 or used_before != 1):
            _fail("指定目标手动再试只允许原剩余的一次尝试")
        content_policy_rejections = 0
        # Legacy unknown targets have one conservatively-accounted original
        # attempt with no terminal result.  Their sole remaining attempt stays
        # original because no content-policy result exists to authorize a
        # semantic retry.  During this continuation, only an immediately
        # preceding content-policy failure selects safe_v2; transient retries
        # retain the immutable original prompt.
        next_variant = "original"
        attempt_limit = used_before + remaining
        for attempt in range(used_before + 1, attempt_limit + 1):
            if next_variant == "original":
                prompt = str(record["frozen_effective_prompt"])
                variant = "original"
            else:
                prompt, variant = production.content_policy_retry_for_record(
                    record, str(record["frozen_effective_prompt"])
                )
                expected_variant = {
                    "cover": "content_policy_safe_v1",
                    "detail": "content_policy_safe_v2_truck",
                    "triptych_panel": "content_policy_safe_v2_truck",
                }.get(str(record.get("generation_kind")))
                if expected_variant is None or variant != expected_variant:
                    _fail(f"货车续跑第2次尝试没有使用匹配图种的安全表述：{target_id}")
            try:
                request_number = reserve(record, attempt, prompt, variant, slot)
            except _BalanceCircuitOpen:
                # Another request in this already-dispatched stage reported an
                # exhausted balance. Do not reserve or call again; return a
                # scheduler result so the executor can drain requests already
                # in flight and pause before the next stage.
                return production.RequestBatchResult(
                    False,
                    final_error_kind="balance_exhausted",
                    attempt_count=attempts_used[target_id],
                    content_policy_rejection_count=content_policy_rejections,
                )
            except _RequestBudgetExhausted:
                return production.RequestBatchResult(
                    False, final_error_kind="request_budget_exhausted",
                    attempt_count=attempts_used[target_id],
                )
            except _RawContractCircuitOpen:
                return production.RequestBatchResult(False, final_error_kind="raw_contract_rejected", attempt_count=attempts_used[target_id])
            except _ImageDownloadCircuitOpen:
                return production.RequestBatchResult(False, final_error_kind="image_download_failed", attempt_count=attempts_used[target_id])
            payload_received = False
            try:
                download_context = production.image_download_context(
                    batch, str(plan["job_id"]), license_data, target_id, request_number, attempt, current_config, prompt,
                )
                payload = generator(client, {**current_config, "_image_download_context": download_context}, prompt)
                payload_received = True
                archive_root = batch / "production" / "provider_originals" / str(plan["job_id"])
                anchor_y = 0.0 if str(record["generation_kind"]) == "cover" else 0.5
                if profile is not None:
                    from tools.category_4k_raw import save_4k_raw_png
                    save = save_4k_raw_png(
                        Path(record["raw_target"]), payload, archive_root=archive_root,
                        generation=current_config, credential_epoch=None, anchor_y=anchor_y,
                        accepted_source_size=profile["accepted_source_size"],
                        accepted_source_width_tolerance=profile["accepted_source_width_tolerance"],
                        **({"source_size_policy": source_size_acceptance["policy_id"]}
                           if source_size_acceptance is not None else {}),
                    )
                elif generation_migration is not None:
                    from tools.category_4k_raw import (
                        ACCEPTED_SOURCE_CONTRACT, RAW_CONTRACT,
                        WIDTH_TOLERANCE_SOURCE_CONTRACT, save_4k_raw_png,
                    )

                    accepted_source_size = generation_migration.get("accepted_source_size")
                    source_width_tolerance = generation_migration.get("accepted_source_width_tolerance", 0)
                    expected_contract = ACCEPTED_SOURCE_CONTRACT if accepted_source_size is not None else RAW_CONTRACT
                    if source_width_tolerance == 16 and accepted_source_size == "2352x3520":
                        expected_contract = WIDTH_TOLERANCE_SOURCE_CONTRACT
                    if generation_migration.get("raw_contract") != expected_contract:
                        _fail("生成参数迁移的原图尺寸契约不受支持")
                    save = save_4k_raw_png(
                        Path(record["raw_target"]), payload,
                        archive_root=archive_root,
                        generation=generation_migration["new_generation"],
                        credential_epoch=generation_migration["credential_epoch"],
                        anchor_y=anchor_y,
                        **({"accepted_source_size": accepted_source_size}
                           if accepted_source_size is not None else {}),
                        **({"accepted_source_width_tolerance": source_width_tolerance}
                           if source_width_tolerance else {}),
                    )
                else:
                    save = production.save_raw_png(
                        Path(record["raw_target"]), payload, production.RAW_API_SIZE,
                        provider=str(current_config.get("provider") or ""),
                        archive_root=archive_root, anchor_y=anchor_y,
                    )
                with state_lock:
                    successful_ids.add(target_id)
                    generated_this_run.append(target_id)
                    attempts_used[target_id] = attempt
                    attempts_remaining[target_id] = 0
                    if explicit_retry is not None:
                        unresolved_explicit.discard(target_id)
                        cumulative_failed = len(plan["exhausted_ids"]) + len(unresolved_explicit)
                    if save.get("normalized") is True:
                        normalized_responses += 1
                event = {
                    "status": "generated",
                    **generation_event_fields,
                    "resume": True,
                    "authorization_id": authorization_id,
                    "resume_plan_sha256": resume_plan_sha256,
                    "request_number": request_number,
                    "raw_target": production._artifact_reference(record["raw_target"], batch),
                    "delivery_target": production._artifact_reference(record["target"], batch),
                    "generation_target_id": target_id,
                    "delivery_target_id": record["delivery_target_id"],
                    "group_index": record["group_index"],
                    "generation_position": record["generation_position"],
                    "delivery_position": record["delivery_position"],
                    "api_key_slot": slot,
                    "attempt": attempt,
                    "retry_prompt_variant": variant,
                    "source_returned_size": save.get("source_returned_size"),
                    "source_sha256": save.get("source_sha256"),
                    "saved_raw_sha256": save.get("saved_raw_sha256"),
                    "normalized": save.get("normalized", False),
                    "normalization_mode": save.get("normalization_mode", "none"),
                    "normalized_to": save.get("normalized_to"),
                    **({"source_size_policy": source_size_acceptance["policy_id"],
                        "working_raw_is_upscaled": save.get("working_raw_is_upscaled")}
                       if source_size_acceptance is not None else {}),
                }
                if save.get("provider_original"):
                    event["provider_original"] = production._artifact_reference(
                        save["provider_original"], batch
                    )
                if profile is not None and save.get("provider_original_metadata"):
                    event["provider_original_metadata"] = production._artifact_reference(save["provider_original_metadata"], batch)
                _append_event(events_path, event_lock, event)
                try:
                    image_download_receipts.mark_materialized(download_context, save.get("saved_raw_sha256"))
                except Exception:
                    with state_lock:
                        image_download_stop.set()
                        image_download_target_ids.add(target_id)
                    return production.RequestBatchResult(False, final_error_kind="image_download_failed", attempt_count=attempt)
                update_job(
                    status="resume_running",
                    **({"failed": cumulative_failed} if explicit_retry is not None else {}),
                    generated_api_units=len(successful_ids),
                    relay_normalized_responses=normalized_responses,
                    current_group=None,
                    current_position=None,
                    last_saved=str(record["raw_target"]),
                )
                return production.RequestBatchResult(True, attempt_count=attempt)
            except Exception as error:
                error_kind = production.classify_request_error(error)
                try:
                    image_download_receipts.assert_no_pending_for_target(
                        production.ROOT / ".runtime" / "image_download_receipts", str(plan["job_id"]), target_id,
                    )
                except Exception:
                    error_kind = "image_download_failed"
                if payload_received and not isinstance(error, production.RawImageContractError):
                    error_kind = "image_download_failed"
                if profile is not None and isinstance(error, production.RawImageContractError):
                    error_kind = "raw_contract_rejected"
                if error_kind == "image_download_failed":
                    with state_lock:
                        image_download_stop.set()
                        image_download_target_ids.add(target_id)
                raw_evidence: dict[str, Any] = {}
                if isinstance(error, production.RawImageContractError):
                    if profile is not None:
                        error_kind = "raw_contract_rejected"
                        raw_contract_stop.set()
                    evidence = error.evidence or {}
                    raw_evidence = {key: evidence[key] for key in (
                        "source_returned_size", "source_sha256", "raw_contract", "archive_status",
                    ) if key in evidence}
                    if evidence.get("provider_original"):
                        raw_evidence["provider_original"] = production._artifact_reference(
                            evidence["provider_original"], batch,
                        )
                    if profile is not None and evidence.get("provider_original_metadata"):
                        raw_evidence["provider_original_metadata"] = production._artifact_reference(evidence["provider_original_metadata"], batch)
                if error_kind == "content_policy":
                    content_policy_rejections += 1
                will_retry = (
                    explicit_retry is None
                    and
                    attempt < attempt_limit
                    and error_kind in {"content_policy", "transient"}
                )
                if will_retry:
                    next_variant = (
                        (
                            "content_policy_safe_v1"
                            if record.get("generation_kind") == "cover"
                            else "content_policy_safe_v2_truck"
                        )
                        if error_kind == "content_policy"
                        else "original"
                    )
                with state_lock:
                    attempts_used[target_id] = attempt
                    attempts_remaining[target_id] = (
                        0 if explicit_retry is not None else
                        max(0, attempt_limit - attempt + 1)
                        if error_kind == "balance_exhausted"
                        else max(0, attempt_limit - attempt)
                    )
                    failed_request_attempts += 1
                    if error_kind == "balance_exhausted":
                        balance_failure_target_ids.append(target_id)
                        quarantined_api_key_slots.add(int(slot))
                        if explicit_retry is not None:
                            failed_this_run.append(target_id)
                    elif not will_retry:
                        if explicit_retry is None:
                            cumulative_failed += 1
                        failed_this_run.append(target_id)
                        attempts_remaining[target_id] = 0
                _append_event(
                    events_path,
                    event_lock,
                    {
                        "status": "request_failed",
                        **generation_event_fields,
                        **raw_evidence,
                        "resume": True,
                        "authorization_id": authorization_id,
                        "resume_plan_sha256": resume_plan_sha256,
                        "request_number": request_number,
                        "generation_target_id": target_id,
                        "delivery_target_id": record["delivery_target_id"],
                        "group_index": record["group_index"],
                        "generation_position": record["generation_position"],
                        "delivery_position": record["delivery_position"],
                        "api_key_slot": slot,
                        "attempt": attempt,
                        "error_kind": error_kind or "non_retryable",
                        "will_retry": will_retry,
                        "api_key_failover_eligible": explicit_retry is None and error_kind == "balance_exhausted",
                        "retry_prompt_variant": variant,
                        "error": production.safe_request_error_summary(error, error_kind),
                        **image_generate.safe_stage_metadata(error),
                    },
                )
                update_job(
                    status="resume_running",
                    failed=cumulative_failed,
                    failed_request_attempts=failed_request_attempts,
                    retry_count=retry_count,
                    current_group=None,
                    current_position=None,
                    last_error=production.safe_request_error_summary(error, error_kind),
                )
                if not will_retry:
                    return production.RequestBatchResult(
                        False,
                        final_error_kind=error_kind,
                        attempt_count=attempt,
                        content_policy_rejection_count=content_policy_rejections,
                    )
        return production.RequestBatchResult(False)

    def pause_for_safety(status: str, reason: str, completed: int) -> dict[str, Any]:
        """Save a drained checkpoint without renewing targets or request budgets."""

        finished_at = production.now_iso()
        checkpoint = {
            "reason": reason,
            **({"generation_resubmit_allowed": False,
                "image_download_target_ids": sorted(image_download_target_ids)}
               if reason == "image_download_failed" else {}),
            "in_flight_drained": True,
            "requests_used": requests_used,
            "remaining_request_budget": max(
                0, min(budget, int(authorization["approved_cumulative_request_budget"])) - requests_used,
            ),
            "attempts_used": dict(attempts_used),
            "attempts_remaining": dict(attempts_remaining),
            "unfinished_generation_target_ids": [
                target_id for target_id in ordered_ids if target_id not in successful_ids
            ],
            "quarantined_api_key_slots": sorted(quarantined_api_key_slots),
            "created_at": finished_at,
        }
        update_job(
            status=status, stop_reason=reason, completed=completed,
            requests_used=requests_used, checkpoint=checkpoint,
            worker_pid=None, worker_count=0, current_worker_count=0,
            current_group=None, current_position=None, finished_at=finished_at,
            quarantined_api_key_slots=sorted(quarantined_api_key_slots),
        )
        if session_file is not None and session is not None:
            current_session = _load_json(session_file, "续跑会话")
            current_session.update({
                "status": status, "pid": None, "stop_reason": reason,
                "requests_used_end": requests_used, "checkpoint": checkpoint,
                "finished_at": finished_at,
            })
            production.atomic_json(session_file, current_session)
        _append_event(events_path, event_lock, {
            "status": status, "resume": True, "authorization_id": authorization_id,
            "resume_plan_sha256": resume_plan_sha256, "stop_reason": reason,
            "requests_used": requests_used, "in_flight_drained": True,
        })
        return {
            "status": status, "authorization_id": authorization_id,
            "requests_used_start": requests_start, "requests_used_end": requests_used,
            "generated_ids": generated_this_run, "failed_ids": failed_this_run,
            "terminal_evidence": None,
        }

    def pause_for_balance() -> dict[str, Any]:
        if profile is not None:
            return pause_for_safety("paused_balance_exhausted", "all_licensed_slots_quarantined", completed)
        status = "paused_balance_exhausted"
        finished_at = production.now_iso()
        last_stage = resume_history[-1] if resume_history else {}
        update_job(
            status=status,
            requests_used=requests_used,
            quarantined_api_key_slots=sorted(quarantined_api_key_slots),
            balance_all_keys_exhausted=True,
            worker_pid=None,
            worker_count=0,
            current_worker_count=0,
            current_group=None,
            current_position=None,
            finished_at=finished_at,
        )
        if session_file is not None and session is not None:
            current_session = dict(session)
            current_session.update(
                {
                    "status": status,
                    "pid": None,
                    "requests_used_end": requests_used,
                    "quarantined_api_key_slots": sorted(
                        quarantined_api_key_slots
                    ),
                    "finished_at": finished_at,
                }
            )
            production.atomic_json(session_file, current_session)
        _append_event(
            events_path,
            event_lock,
            {
                "status": status,
                "authorization_id": authorization_id,
                "resume_plan_sha256": resume_plan_sha256,
                "requests_used": requests_used,
                "stage": last_stage.get("stage"),
                "stage_requests_used": last_stage.get("stage_requests_used", 0),
                "dispatched_target_count": last_stage.get(
                    "dispatched_target_count", 0
                ),
                "drained_result_count": last_stage.get("drained_result_count", 0),
                "in_flight_drained": last_stage.get("in_flight_drained", False),
                "balance_failure_count": last_stage.get(
                    "balance_failure_count", 0
                ),
                "quarantined_api_key_slots": sorted(
                    quarantined_api_key_slots
                ),
            },
        )
        return {
            "status": status,
            "authorization_id": authorization_id,
            "requests_used_start": requests_start,
            "requests_used_end": requests_used,
            "generated_ids": generated_this_run,
            "failed_ids": failed_this_run,
            "terminal_evidence": None,
        }

    try:
        if explicit_retry is not None or profile is not None:
            lock_path, explicit_lock_payload = _acquire_explicit_retry_lock(batch, str(plan["job_id"]))
        else:
            lock_path = production.acquire_lock(batch, str(plan["job_id"]))
        if schedule_amendment is not None or explicit_retry is not None or profile is not None:
            bound_files = {
                "original_license_sha256": license_file,
                "original_job_sha256": job_file,
                "events_sha256": events_path,
                "frozen_manifest_sha256": manifest_path,
                "frozen_overlay_sha256": _artifact_path(
                    batch, license_data.get("overlay_plan"), "冻结叠字清单",
                ),
            }
            for binding, bound_path in bound_files.items():
                if not bound_path.is_file() or _file_sha256(bound_path) != authorization[binding]:
                    _fail(f"取得生产锁后原账本或冻结证据已变化：{binding}")
        if profile is not None:
            locked_plan = category_image_resume.build_resume_plan(batch, job_file, license_file)
            if locked_plan != plan:
                _fail("取得生产锁后新4K续跑profile/账本/叠字计划变化")
            if session_file is not None:
                # The launcher may legitimately publish starting/PID after Popen.
                # Recheck frozen identity/profile and exact worker/launcher PID,
                # then retain the latest validated mutable launch state.
                session = _validate_session(session_file, authorization_id, plan)
        if explicit_retry is not None:
            _validate_explicit_retry_network(authorization, _load_json(job_file, "原生产任务"))
            if _file_sha256(previous_session_path) != authorization["previous_resume_session_sha256"]:
                _fail("取得生产锁后前序再试会话证据已变化")
            locked_plan, _, _ = _rebuild_explicit_retry(
                batch, base_resume_plan, license_data, source_events, authorization,
                _load_json(job_file, "原生产任务"),
            )
            if locked_plan["resume_plan_sha256"] != plan["resume_plan_sha256"]:
                _fail("取得生产锁后指定目标手动再试计划已变化")
        elif generation_migration is not None:
            previous_now = _load_json(previous_authorization_path, "前序已消费续跑授权")
            if _canonical_sha256(previous_now) != generation_migration["previous_authorization_sha256"]:
                _fail("取得生产锁后前序迁移授权已变化")
        image_download_receipts.preflight_receipt_support()
        image_download_receipts.assert_no_pending_for_job(production.ROOT / ".runtime" / "image_download_receipts", str(plan["job_id"]))
        _consume_authorization(authorization_file, authorization)
        completed = materialize_current()
        if session_file is not None and session is not None:
            session = dict(session)
            session.update(
                {
                    "status": "running",
                    "pid": os.getpid(),
                    "started_at": production.now_iso(),
                    "requests_used_start": requests_start,
                }
            )
            production.atomic_json(session_file, session)
        _append_event(
            events_path,
            event_lock,
            {
                "status": "resume_started",
                **generation_event_fields,
                "authorization_id": authorization_id,
                "resume_plan_sha256": resume_plan_sha256,
                "requests_used_start": requests_start,
                "remaining_max_requests": plan["remaining_max_requests"],
                "cumulative_max_requests": plan["cumulative_max_requests"],
                "resume_policy": resume_policy,
                "max_workers": authorized_max_workers,
                "api_key_slots": slots,
            },
        )
        update_job(
            status="resume_running",
            effective_generation=generation_event_fields,
            failed=cumulative_failed,
            generated_api_units=len(successful_ids),
            resume_authorization_id=authorization_id,
            resume_plan_sha256=resume_plan_sha256,
            resume_policy=resume_policy,
            resume_max_workers=authorized_max_workers,
            resume_api_key_slots=slots,
            resume_requests_used_start=requests_start,
            resume_concurrency_history=[],
            current_group=None,
            current_position=None,
            worker_pid=os.getpid(),
            quarantined_api_key_slots=sorted(quarantined_api_key_slots),
        )

        probe_result = production.RequestBatchResult(False)
        while True:
            available_clients = [
                pair
                for pair in clients
                if int(pair[0]) not in quarantined_api_key_slots
            ]
            if not available_clients:
                return pause_for_balance()
            probe_slot, probe_client = available_clients[0]
            if explicit_retry is not None:
                required_slot = explicit_targets[probe_id]["api_key_slot"]
                matches = [pair for pair in available_clients if pair[0] == required_slot]
                if not matches:
                    return pause_for_safety("paused_api_errors", "explicit_retry_original_slot_unavailable", completed)
                probe_slot, probe_client = matches[0]
            probe_requests_start = requests_used
            probe_balance_failures_start = len(balance_failure_target_ids)
            update_job(worker_count=1, current_worker_count=1)
            probe_result = run_target(probe_slot, probe_client, probe_id)
            completed = materialize_current()
            probe_summary = production._request_stage_result([probe_result], 1)
            probe_balance_failure = (
                not probe_result.success
                and probe_result.final_error_kind == "balance_exhausted"
            )
            if probe_balance_failure:
                probe_summary["balance_circuit_breaker_triggered"] = not any(
                    int(pair[0]) not in quarantined_api_key_slots
                    for pair in clients
                )
            probe_double_policy = (
                not probe_result.success
                and probe_result.final_error_kind == "content_policy"
                and probe_result.content_policy_rejection_count >= 2
            )
            serial_probe_double_policy = (
                authorized_max_workers == 1 and probe_double_policy
            )
            fixed_ten_probe_double_policy = (
                profile is None and authorized_max_workers == 10 and probe_double_policy
            )
            if serial_probe_double_policy or fixed_ten_probe_double_policy:
                probe_summary["circuit_breaker_triggered"] = True
            probe_stage = {
                "stage": len(resume_history) + 1,
                "phase": "resume_probe",
                "worker_count": 1,
                "request_count": 1,
                **probe_summary,
                "serial_target_double_policy_failure": serial_probe_double_policy,
                "fixed_ten_any_double_policy_failure": fixed_ten_probe_double_policy,
                "stage_requests_used": requests_used - probe_requests_start,
                "dispatched_target_count": 1,
                "drained_result_count": 1,
                "in_flight_drained": True,
                "balance_failure_count": (
                    len(balance_failure_target_ids) - probe_balance_failures_start
                ),
                "quarantined_api_key_slots": sorted(quarantined_api_key_slots),
                "remaining_api_key_slot_count": sum(
                    int(pair[0]) not in quarantined_api_key_slots
                    for pair in clients
                ),
                "requests_used_total": requests_used,
                "recorded_at": production.now_iso(),
            }
            resume_history.append(probe_stage)
            _append_event(
                events_path,
                event_lock,
                {"status": "resume_concurrency_stage", **probe_stage},
            )
            update_job(
                resume_concurrency_history=list(resume_history),
                quarantined_api_key_slots=sorted(quarantined_api_key_slots),
            )
            if image_download_stop.is_set():
                return pause_for_safety("paused_image_download", "image_download_failed", completed)
            if explicit_retry is not None and not probe_result:
                return pause_for_safety("paused_api_errors", "explicit_retry_failed", completed)
            if probe_balance_failure:
                continue
            if probe_result:
                break
            if (schedule_amendment is not None or profile is not None) and probe_result.final_error_kind == "request_budget_exhausted":
                return pause_for_safety("paused_request_budget", "original_request_budget_exhausted", completed)
            status = (
                "paused_policy_circuit"
                if probe_stage["circuit_breaker_triggered"]
                else "paused_resume_probe_failed"
            )
            if schedule_amendment is not None or profile is not None:
                reason = "raw_contract_rejected" if probe_result.final_error_kind == "raw_contract_rejected" else status
                return pause_for_safety(status, reason, completed)
            update_job(
                status=status,
                worker_pid=None,
                worker_count=0,
                current_worker_count=0,
                current_group=None,
                current_position=None,
            )
            if session_file is not None and session is not None:
                session = dict(session)
                session.update(
                    {
                        "status": status,
                        "pid": None,
                        "requests_used_end": requests_used,
                        "finished_at": production.now_iso(),
                    }
                )
                production.atomic_json(session_file, session)
            _append_event(
                events_path,
                event_lock,
                {
                    "status": status,
                    "authorization_id": authorization_id,
                    "resume_plan_sha256": resume_plan_sha256,
                    "requests_used": requests_used,
                },
            )
            return {
                "status": status,
                "authorization_id": authorization_id,
                "requests_used_start": requests_start,
                "requests_used_end": requests_used,
                "generated_ids": generated_this_run,
                "failed_ids": failed_this_run,
                "terminal_evidence": None,
            }

        remaining_ids = ordered_ids[1:]
        stage_width = min(4, authorized_max_workers) if profile is not None else (
            1 if authorized_max_workers == 1 else (10 if authorized_max_workers == 10 else 2)
        )
        profile_degraded = False
        circuit_triggered = False
        consecutive_api_failures = 0
        while remaining_ids:
            if (schedule_amendment is not None or explicit_retry is not None or profile is not None) and requests_used >= min(
                budget, int(authorization["approved_cumulative_request_budget"]),
            ):
                return pause_for_safety("paused_request_budget", "original_request_budget_exhausted", completed)
            available_clients = [
                pair
                for pair in clients
                if int(pair[0]) not in quarantined_api_key_slots
            ]
            if not available_clients:
                return pause_for_balance()
            width = min(stage_width, len(remaining_ids), len(available_clients))
            stage_ids = remaining_ids[:width]
            del remaining_ids[:width]
            stage_clients = available_clients[:width]
            if explicit_retry is not None:
                required_slot = explicit_targets[stage_ids[0]]["api_key_slot"]
                stage_clients = [pair for pair in available_clients if pair[0] == required_slot]
                if len(stage_clients) != 1 or width != 1:
                    return pause_for_safety("paused_api_errors", "explicit_retry_original_slot_unavailable", completed)
            stage_requests_start = requests_used
            stage_balance_failures_start = len(balance_failure_target_ids)
            update_job(worker_count=width, current_worker_count=width)
            if authorized_max_workers == 1:
                results = [
                    run_target(
                        stage_clients[0][0], stage_clients[0][1], stage_ids[0]
                    )
                ]
            else:
                with ThreadPoolExecutor(max_workers=width) as executor:
                    futures = [
                        executor.submit(
                            run_target,
                            stage_clients[index][0],
                            stage_clients[index][1],
                            target_id,
                        )
                        for index, target_id in enumerate(stage_ids)
                    ]
                    results = [future.result() for future in futures]
            balance_retry_ids = [] if explicit_retry is not None else [
                target_id
                for target_id, item in zip(stage_ids, results)
                if (
                    isinstance(item, production.RequestBatchResult)
                    and not item.success
                    and item.final_error_kind == "balance_exhausted"
                )
            ]
            if balance_retry_ids:
                remaining_ids = balance_retry_ids + remaining_ids
            completed = materialize_current()
            result = production._request_stage_result(results, len(stage_ids))
            if schedule_amendment is not None or profile is not None:
                result.update(production._consecutive_api_error_stage_result(
                    results, consecutive_api_failures,
                ))
                consecutive_api_failures = int(result["consecutive_api_failure_count"])
            serial_double_policy = (
                authorized_max_workers == 1
                and isinstance(results[0], production.RequestBatchResult)
                and not results[0].success
                and results[0].final_error_kind == "content_policy"
                and results[0].content_policy_rejection_count >= 2
            )
            if serial_double_policy:
                result["circuit_breaker_triggered"] = True
            fixed_ten_any_double_policy = (
                profile is None and authorized_max_workers == 10
                and result["content_policy_double_failure_count"] >= 1
            )
            if fixed_ten_any_double_policy:
                result["circuit_breaker_triggered"] = True
            stage = {
                "stage": len(resume_history) + 1,
                "phase": (
                    "resume_adaptive" if profile is not None else "resume_serial"
                    if authorized_max_workers == 1
                    else (
                        "resume_fixed_10"
                        if authorized_max_workers == 10
                        else ("resume_ramp_2" if stage_width == 2 else "resume_fixed_4")
                    )
                ),
                "worker_count": width,
                "request_count": len(stage_ids),
                **result,
                "serial_target_double_policy_failure": serial_double_policy,
                "fixed_ten_any_double_policy_failure": fixed_ten_any_double_policy,
                "stage_requests_used": requests_used - stage_requests_start,
                "dispatched_target_count": len(stage_ids),
                "drained_result_count": len(results),
                "in_flight_drained": len(results) == len(stage_ids),
                "balance_failure_count": (
                    len(balance_failure_target_ids) - stage_balance_failures_start
                ),
                "balance_failover_target_count": len(balance_retry_ids),
                "quarantined_api_key_slots": sorted(quarantined_api_key_slots),
                "remaining_api_key_slot_count": sum(
                    int(pair[0]) not in quarantined_api_key_slots
                    for pair in clients
                ),
                "requests_used_total": requests_used,
                "recorded_at": production.now_iso(),
            }
            resume_history.append(stage)
            _append_event(events_path, event_lock, {"status": "resume_concurrency_stage", **stage})
            update_job(
                resume_concurrency_history=list(resume_history),
                quarantined_api_key_slots=sorted(quarantined_api_key_slots),
                api_key_failover_count=(
                    int(job.get("api_key_failover_count", 0) or 0)
                    if explicit_retry is not None else len(balance_failure_target_ids)
                ),
            )
            if explicit_retry is not None and any(not result for result in results):
                if image_download_stop.is_set():
                    return pause_for_safety("paused_image_download", "image_download_failed", completed)
                return pause_for_safety("paused_api_errors", "explicit_retry_failed", completed)
            if image_download_stop.is_set():
                return pause_for_safety("paused_image_download", "image_download_failed", completed)
            if schedule_amendment is not None or profile is not None:
                if profile is not None and raw_contract_stop.is_set():
                    return pause_for_safety("paused_api_errors", "raw_contract_rejected", completed)
                if any(item.final_error_kind == "request_budget_exhausted" for item in results):
                    return pause_for_safety("paused_request_budget", "original_request_budget_exhausted", completed)
                if stage.get("api_error_circuit_breaker_triggered"):
                    update_job(
                        api_error_circuit_breaker_triggered=True,
                        api_error_circuit_breaker_failure_count=stage["consecutive_api_failure_peak"],
                        api_error_circuit_breaker_stage=stage["stage"],
                    )
                    return pause_for_safety(
                        "paused_api_errors", str(stage.get("api_error_circuit_breaker_reason") or "consecutive_non_balance_api_failures"), completed,
                    )
            if balance_retry_ids and not any(
                int(pair[0]) not in quarantined_api_key_slots
                for pair in clients
            ):
                return pause_for_balance()
            if stage["circuit_breaker_triggered"]:
                if profile is not None:
                    return pause_for_safety("paused_policy_circuit", "content_policy_circuit", completed)
                circuit_triggered = True
                _append_event(
                    events_path,
                    event_lock,
                    {
                        "status": "policy_circuit_breaker",
                        "resume": True,
                        "authorization_id": authorization_id,
                        "resume_plan_sha256": resume_plan_sha256,
                        "stage": stage["stage"],
                        "content_policy_double_failure_count": stage[
                            "content_policy_double_failure_count"
                        ],
                        "content_policy_double_failure_rate": stage[
                            "content_policy_double_failure_rate"
                        ],
                        "stage_requests_used": stage["stage_requests_used"],
                        "dispatched_target_count": stage[
                            "dispatched_target_count"
                        ],
                        "drained_result_count": stage["drained_result_count"],
                        "in_flight_drained": stage["in_flight_drained"],
                    },
                )
                break
            if profile is not None:
                failures = int(result["failed_count"]) - len(balance_retry_ids)
                if failures:
                    profile_degraded = True
                    stage_width = min(authorized_max_workers, 5 if width >= 6 else 2)
                elif not profile_degraded:
                    stage_width = min(authorized_max_workers, next((n for n in (4, 6, 8, 10) if n > width), authorized_max_workers))
            else:
                stage_width = (1 if authorized_max_workers == 1 else (10 if authorized_max_workers == 10 else 4))

        if circuit_triggered:
            update_job(
                status="paused_policy_circuit",
                completed=completed,
                requests_used=requests_used,
                worker_pid=None,
                worker_count=0,
                current_worker_count=0,
                current_group=None,
                current_position=None,
                content_policy_circuit_breaker_triggered=True,
            )
            if session_file is not None and session is not None:
                session = dict(session)
                session.update(
                    {
                        "status": "paused_policy_circuit",
                        "pid": None,
                        "requests_used_end": requests_used,
                        "finished_at": production.now_iso(),
                    }
                )
                production.atomic_json(session_file, session)
            return {
                "status": "paused_policy_circuit",
                "authorization_id": authorization_id,
                "requests_used_start": requests_start,
                "requests_used_end": requests_used,
                "generated_ids": generated_this_run,
                "failed_ids": failed_this_run,
                "terminal_evidence": None,
            }

        completed = materialize_current()
        if explicit_retry is not None and completed != len(delivery_records):
            return pause_for_safety("paused_api_errors", "explicit_retry_delivery_incomplete", completed)
        status = "completed_with_errors" if plan["exhausted_ids"] or failed_this_run else "awaiting_review"
        _append_event(
            events_path,
            event_lock,
            {
                "status": "resume_completed",
                "authorization_id": authorization_id,
                "resume_plan_sha256": resume_plan_sha256,
                "final_status": status,
                "requests_used": requests_used,
                "generated_count": len(generated_this_run),
                "failed_count": len(failed_this_run),
            },
        )
        event_bytes = events_path.read_bytes()
        event_lines = [line for line in event_bytes.splitlines() if line.strip()]
        terminal = {
            "schema_version": 1,
            "kind": "category-image-resume-terminal-evidence",
            "authorization_id": authorization_id,
            "job_id": plan["job_id"],
            "license_id": plan["license_id"],
            "category_id": plan["category_id"],
            "resume_plan_sha256": resume_plan_sha256,
            "resume_policy": resume_policy,
            "max_workers": authorized_max_workers,
            "api_key_slots": slots,
            "status": status,
            "requests_used_start": requests_start,
            "requests_used_end": requests_used,
            "requests_used_resume": requests_used - requests_start,
            "license_budget": budget,
            "generated_ids": generated_this_run,
            "failed_ids": failed_this_run,
            "preexisting_exhausted_ids": list(plan["exhausted_ids"]),
            "completed_delivery_count": completed,
            "events_sha256": hashlib.sha256(event_bytes).hexdigest(),
            "event_tail_sha256": hashlib.sha256(event_lines[-1]).hexdigest(),
            "finished_at": production.now_iso(),
        }
        terminal["evidence_sha256"] = _canonical_sha256(terminal)
        _write_terminal_evidence(terminal_path, terminal)
        update_job(
            status=status,
            completed=completed,
            failed=cumulative_failed,
            failed_request_attempts=failed_request_attempts,
            retry_count=retry_count,
            requests_used=requests_used,
            generated_api_units=len(successful_ids),
            worker_pid=None,
            worker_count=0,
            current_worker_count=0,
            current_group=None,
            current_position=None,
            finished_at=terminal["finished_at"],
            resume_terminal_evidence=str(terminal_path),
        )
        if session_file is not None and session is not None:
            session = dict(session)
            session.update(
                {
                    "status": status,
                    "pid": None,
                    "requests_used_end": requests_used,
                    "terminal_evidence": str(terminal_path),
                    "finished_at": terminal["finished_at"],
                }
            )
            production.atomic_json(session_file, session)
        return {
            "status": status,
            "authorization_id": authorization_id,
            "requests_used_start": requests_start,
            "requests_used_end": requests_used,
            "generated_ids": generated_this_run,
            "failed_ids": failed_this_run,
            "terminal_evidence": str(terminal_path),
        }
    except Exception as error:
        if session_file is not None and session is not None:
            try:
                current_session = _load_json(session_file, "续跑会话")
                if current_session.get("status") == "running":
                    current_session.update(
                        {
                            "status": "failed",
                            "pid": None,
                            "requests_used_end": requests_used,
                            "last_error": production.safe_request_error_summary(
                                error, production.classify_request_error(error),
                            ),
                            "finished_at": production.now_iso(),
                        }
                    )
                    production.atomic_json(session_file, current_session)
            except Exception:
                pass
        raise
    finally:
        if lock_path is not None and lock_path.is_file():
            if explicit_lock_payload is not None:
                if lock_path.read_bytes() == explicit_lock_payload:
                    lock_path.unlink()
            else:
                try:
                    lock_data = _load_json(lock_path, "生产锁")
                except ResumeExecutionError:
                    lock_data = {}
                if int(lock_data.get("pid", 0) or 0) == os.getpid() and lock_data.get("job_id") == plan["job_id"]:
                    lock_path.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resume one frozen category-image job")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--batch-dir", required=True)
    run.add_argument("--job-file", required=True)
    run.add_argument("--license", required=True)
    run.add_argument("--resume-authorization", required=True)
    run.add_argument("--session-file", required=True)
    run.add_argument("--resume-plan-sha256", required=True)
    return parser


def _mark_cli_session_failed(
    batch_dir: str | Path,
    job_path: str | Path,
    license_path: str | Path,
    session_path: str | Path,
    resume_plan_sha256: str,
    error: Exception,
) -> None:
    """Best-effort CLI preflight failure record, scoped to this worker identity."""

    try:
        batch = Path(batch_dir).expanduser().resolve()
        session_file = Path(session_path).expanduser().resolve()
        expected_parent = (batch / "production" / "resume_sessions").resolve()
        if session_file.parent != expected_parent or not session_file.is_file():
            return
        session = _load_json(session_file, "resume session")
        authorization_id = str(session.get("authorization_id") or "")
        expected = {
            "schema_version": 1,
            "kind": "category-image-resume-session",
            "job_id": Path(job_path).stem,
            "license_id": Path(license_path).stem,
            "resume_plan_sha256": resume_plan_sha256,
        }
        if (
            not _SAFE_ID.fullmatch(authorization_id)
            or session_file.name != f"{authorization_id}.json"
            or any(session.get(key) != value for key, value in expected.items())
        ):
            return
        state = (session.get("status"), session.get("pid"))
        initial_state_allowed = _initial_session_state_allowed(
            state[0],
            state[1],
            current_pid=os.getpid(),
            parent_pid=os.getppid(),
            allow_parent_pid=os.name == "nt",
        )
        if not initial_state_allowed and state != ("running", os.getpid()):
            return
        session.update(
            {
                "status": "failed",
                "pid": None,
                "last_error": production.safe_request_error_summary(
                    error, production.classify_request_error(error),
                ),
                "finished_at": production.now_iso(),
            }
        )
        production.atomic_json(session_file, session)
    except Exception:
        # This error path must never mask the original fail-closed exception.
        return


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "run":
        raise SystemExit(2)
    try:
        result = resume_category_images(
            args.batch_dir,
            args.job_file,
            args.license,
            args.resume_authorization,
            args.resume_plan_sha256,
            session_path=args.session_file,
        )
    except Exception as error:
        _mark_cli_session_failed(
            args.batch_dir,
            args.job_file,
            args.license,
            args.session_file,
            args.resume_plan_sha256,
            error,
        )
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["ResumeExecutionError", "resume_category_images"]
