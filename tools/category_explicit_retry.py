"""Pure, narrow planning for explicitly requested original-prompt retries.

This does not reclassify HTTP 451 as transient, change automatic resume rules,
grant authority, read credentials, or call a provider. Callers must validate
the original frozen ledger first and rebuild this amendment under its lock.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from tools import category_image_resume as ledger
from tools.category_resume_migration import (
    TOLERANT_SOURCE_RAW_CONTRACT, _continuation_quarantine, _validate_spec,
)


RETRY_POLICY = "serial_probe_policy_circuit_v1"
_IDENTITY = ("license_id", "category_id", "batch_id", "group_start", "group_count", "scope",
             "provider", "model", "quality", "size", "max_attempts", "retry_policy")


def _fail(message: str) -> None:
    raise ledger.ResumePlanError(message)


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{label}必须为不小于{minimum}的整数")
    return value


def _digest(value: Any) -> str:
    return ledger._canonical_sha256(value)


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail(f"{label}必须为SHA-256校验码")
    return value


def _validate_base(plan: dict[str, Any], license_data: dict[str, Any]) -> None:
    if any(key in plan for key in ("schedule_amendment", "generation_migration", "explicit_retry", "explicit_retry_ids")):
        _fail("显式重试必须从未经修订的原账本计划建立")
    material = deepcopy(plan)
    stored_hash = material.pop("resume_plan_sha256", None)
    if _require_digest(stored_hash, "原恢复计划") != _digest(material):
        _fail("原恢复计划校验码不一致")
    for key in _IDENTITY:
        if key not in plan or key not in license_data or plan[key] != license_data[key]:
            _fail(f"原恢复计划与许可证身份不一致：{key}")
    if (
        license_data.get("status") != "consumed" or license_data.get("one_time") is not True
        or license_data.get("provider") != "relay"
        or str(license_data.get("base_url", "")).rstrip("/") != "https://tinysnow.one/v1"
        or license_data.get("third_party_confirmed") is not True
        or plan.get("category_id") != "truck_rescue" or plan.get("scope") != "all"
        or type(plan.get("max_attempts")) is not int or plan["max_attempts"] != 2
        or ("job_id" in license_data and license_data["job_id"] != plan.get("job_id"))
    ):
        _fail("显式重试只适用于原已消费的货车整批两次上限任务")
    used = _integer(plan.get("requests_used"), "累计请求数")
    budget = _integer(plan.get("budget"), "原累计预算")
    if (used != license_data.get("requests_used")
            or budget != license_data.get("approved_request_budget") or used > budget):
        _fail("原累计请求数或预算不一致")
    counts = plan.get("counts")
    used_map, remaining_map = plan.get("attempts_used"), plan.get("attempts_remaining")
    if not all(isinstance(value, dict) for value in (counts, used_map, remaining_map)):
        _fail("原计划缺少逐目标账本及分区计数")
    if set(used_map) != set(remaining_map) or sum(_integer(value, "目标已用次数") for value in used_map.values()) != used:
        _fail("原逐目标请求次数与累计账本不一致")
    classified: list[str] = []
    for name in ("success", "exhausted", "balance_recoverable", "unknown", "unattempted"):
        values = plan.get(f"{name}_ids")
        if (not isinstance(values, list) or any(not isinstance(value, str) for value in values)
                or len(values) != len(set(values)) or counts.get(name) != len(values)):
            _fail("原计划目标分区与计数不一致")
        classified.extend(values)
    if len(classified) != len(set(classified)) or set(classified) != set(used_map) or counts.get("total") != len(classified):
        _fail("原计划目标分区未完整且唯一覆盖冻结范围")
    if (plan.get("resumable_ids") != [] or counts.get("resumable") != 0
            or any(plan[f"{name}_ids"] for name in ("balance_recoverable", "unknown", "unattempted"))
            or any(_integer(value, "原剩余次数") != 0 for value in remaining_map.values())
            or plan.get("remaining_max_requests") != 0 or plan.get("cumulative_max_requests") != used):
        _fail("显式尾部重试不能混入尚待执行的自动续跑目标")


def _validate_previous(
    plan: dict[str, Any], license_data: dict[str, Any], events: list[dict[str, Any]], previous: dict[str, Any],
) -> tuple[int, dict[str, Any], list[int], list[int], int]:
    if (
        previous.get("kind") != "category-image-resume-authorization"
        or previous.get("status") != "consumed" or previous.get("one_time") is not True
        or not isinstance(previous.get("consumed_at"), str) or not previous["consumed_at"]
        or "explicit_retry" in previous
        or previous.get("generation_migration_confirmed") is not True
        or previous.get("schedule_amendment_confirmed") is not True
    ):
        _fail("显式重试必须承接已消费的原十路迁移授权，不能循环叠加人工重试")
    previous_id = previous.get("authorization_id")
    if not isinstance(previous_id, str) or not re.fullmatch(r"resume-[0-9a-f]{24}", previous_id):
        _fail("前序授权标识无效")
    for key in ("job_id", "license_id", "category_id", "batch_id", "provider", "model", "quality", "size",
                "frozen_manifest_sha256", "frozen_overlay_sha256"):
        if key not in previous or previous[key] != plan.get(key):
            _fail(f"前序授权与原任务绑定不一致：{key}")
    if (
        str(previous.get("base_url", "")).rstrip("/") != str(license_data["base_url"]).rstrip("/")
        or previous.get("original_plan_sha256") != _require_digest(license_data.get("plan_sha256"), "原许可计划")
    ):
        _fail("前序授权原计划或中转路线发生变化")
    _require_digest(previous.get("resume_plan_sha256"), "前序恢复计划")
    previous_cap = _integer(previous.get("approved_cumulative_request_budget"), "前序累计上限")
    previous_used = _integer(previous.get("requests_used"), "前序起始请求数")
    previous_remaining = _integer(previous.get("approved_remaining_request_budget"), "前序授权剩余请求数")
    if (
        previous_used + previous_remaining != previous_cap
        or not previous_used <= plan["requests_used"] <= previous_cap <= plan["budget"]
        or previous.get("original_approved_request_budget") != plan["budget"]
    ):
        _fail("前序累计授权预算链不一致")
    slots = previous.get("api_key_slots")
    schedule = previous.get("schedule_amendment")
    if (
        previous.get("max_workers") != 10 or previous.get("resume_policy") != "fixed_10_probe_policy_circuit_v1"
        or not isinstance(slots, list) or len(slots) != 10
        or any(type(slot) is not int or slot < 1 for slot in slots) or len(set(slots)) != 10
        or not isinstance(schedule, dict) or schedule.get("api_key_slots") != slots
        or schedule.get("strict_original_request_budget") != plan["budget"]
    ):
        _fail("前序授权没有绑定原十路配置及严格累计预算")
    start_indices = [index for index, event in enumerate(events) if event.get("status") == "resume_started"]
    matching_starts = [index for index in start_indices if events[index].get("authorization_id") == previous_id]
    if not start_indices or matching_starts != [start_indices[-1]]:
        _fail("前序授权必须是原账本最后且唯一启动的迁移授权")
    start_index = start_indices[-1]
    start = events[start_index]
    if (start.get("max_workers") != 10 or start.get("api_key_slots") != slots
            or start.get("resume_policy") != previous["resume_policy"]):
        _fail("前序启动事件没有绑定原调度及槽位")
    migration = previous.get("generation_migration")
    if not isinstance(migration, dict) or (
        migration.get("new_generation") != {"model": "gpt-image-2-4k", "quality": "medium", "api_size": "2560x3840"}
        or migration.get("raw_contract") != TOLERANT_SOURCE_RAW_CONTRACT
        or migration.get("accepted_source_size") != "2352x3520"
        or type(migration.get("accepted_source_width_tolerance")) is not int
        or migration["accepted_source_width_tolerance"] != 16
    ):
        _fail("显式重试必须原样承接已确认的4K双尺寸生成契约")
    spec = {**migration["new_generation"], "credential_epoch": migration.get("credential_epoch"),
            "rotated_slots": [], "accepted_source_size": "2352x3520", "accepted_source_width_tolerance": 16}
    _validate_spec(spec, slots, continuation=True)
    quarantine = _continuation_quarantine(previous, migration, spec, plan, slots, events, start_index)
    return previous_cap, migration, slots, quarantine, start_index


def apply_explicit_retry(
    plan: dict[str, Any], license_data: dict[str, Any], events: list[dict[str, Any]],
    previous_authorization: dict[str, Any], target_ids: list[str],
) -> dict[str, Any]:
    """Plan at most two final, same-slot/same-prompt attempts without mutation."""

    if not all(isinstance(value, dict) for value in (plan, license_data, previous_authorization)):
        _fail("显式重试缺少原账本、许可证或前序授权")
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        _fail("显式重试必须绑定原事件对象列表")
    if (not isinstance(target_ids, list) or not 1 <= len(target_ids) <= 2
            or any(not isinstance(target, str) for target in target_ids) or len(set(target_ids)) != len(target_ids)):
        _fail("用户必须明确选定一至两个不同的原失败详情目标")
    _validate_base(plan, license_data)
    previous = previous_authorization
    prior_cap, migration, prior_slots, quarantine, start_index = _validate_previous(plan, license_data, events, previous)
    if plan["requests_used"] + len(target_ids) > min(plan["budget"], prior_cap):
        _fail("原累计预算不足以执行所选目标的唯一剩余尝试")
    selected: list[dict[str, Any]] = []
    selected_slots: list[int] = []
    for target in target_ids:
        match = re.fullmatch(r"truck_rescue:v3:g([0-9]{4}):u(0[567])", target)
        if not match or target not in plan["exhausted_ids"] or plan["attempts_used"].get(target) != 1:
            _fail("显式重试只允许原冻结范围内已失败且仅用一次的独立详情")
        group, position = int(match[1]), int(match[2])
        if not plan["group_start"] <= group < plan["group_start"] + plan["group_count"]:
            _fail("所选详情越出原任务组号范围")
        relevant = [(index, event) for index, event in enumerate(events) if event.get("generation_target_id") == target]
        reservations = [(index, event) for index, event in relevant if event.get("status") == "request_reserved"]
        failures = [(index, event) for index, event in relevant if event.get("status") == "request_failed"]
        if len(reservations) != 1 or len(failures) != 1 or any(event.get("status") in {"generated", "provider_source_recovered"} for _, event in relevant):
            _fail("显式重试目标必须有唯一原预约和失败结果，不能已有成功或额外尝试")
        reserve_index, reservation = reservations[0]
        failure_index, failed = failures[0]
        if not start_index < reserve_index < failure_index:
            _fail("目标预约/失败不属于前序已启动授权的正确事件顺序")
        summary = failed.get("error")
        if (
            failed.get("error_kind") != "non_retryable" or failed.get("will_retry") is not False
            or failed.get("api_key_failover_eligible") is not False
            or not isinstance(summary, str)
            or not re.fullmatch(r"error_type=[A-Za-z_][A-Za-z0-9_]{0,79}; error_kind=non_retryable; http_status=451", summary)
            or any(key in failed for key in ("provider_original", "source_sha256", "raw_contract"))
        ):
            _fail("本次显式重试仅限原HTTP451终止失败，不能重分类或忽略其他限制")
        request_number = _integer(failed.get("request_number"), "原请求编号", 1)
        slot = _integer(failed.get("api_key_slot"), "原失败槽位", 1)
        expected = {
            "authorization_id": previous["authorization_id"], "resume_plan_sha256": previous["resume_plan_sha256"],
            "generation_target_id": target, "request_number": request_number, "attempt": 1,
            "api_key_slot": slot, "group_index": group, "generation_position": position,
            "retry_prompt_variant": "original", "credential_epoch": migration["credential_epoch"],
            **migration["new_generation"],
        }
        for event in (reservation, failed):
            if any(event.get(key) != value for key, value in expected.items()):
                _fail("原预约和失败未绑定相同的目标、参数、凭据、原词及原槽位")
        if (not previous["requests_used"] < request_number <= plan["requests_used"]
                or slot not in prior_slots or slot in quarantine):
            _fail("原失败请求越出授权区间或原槽位当前不可用；禁止换槽")
        for key in ("delivery_target_id", "delivery_position"):
            if key not in reservation or reservation[key] != failed.get(key):
                _fail("原预约与失败的交付目标不一致")
        prompt_sha = _require_digest(reservation.get("effective_prompt_sha256"), "原提示词")
        selected.append({
            "generation_target_id": target, "source_request_number": request_number,
            "source_attempt": 1, "next_attempt": 2, "api_key_slot": slot,
            "failed_event_sha256": _digest(failed), "reservation_event_sha256": _digest(reservation),
            "effective_prompt_sha256": prompt_sha,
        })
        if slot not in selected_slots:
            selected_slots.append(slot)
    amended = deepcopy(plan)
    amended["exhausted_ids"] = [target for target in plan["exhausted_ids"] if target not in target_ids]
    amended["explicit_retry_ids"] = list(target_ids)
    amended["resumable_ids"] = list(target_ids)
    for target in target_ids:
        amended["attempts_remaining"][target] = 1
    amended["counts"].update(exhausted=len(amended["exhausted_ids"]), explicit_retry=len(target_ids), resumable=len(target_ids))
    amended["remaining_max_requests"] = len(target_ids)
    amended["cumulative_max_requests"] = plan["requests_used"] + len(target_ids)
    amended["generation_migration"] = deepcopy(migration)
    amended["explicit_retry"] = {
        "schema_version": 1, "kind": "category-explicit-target-retry",
        "base_resume_plan_sha256": plan["resume_plan_sha256"],
        "previous_authorization_id": previous["authorization_id"],
        "previous_authorization_sha256": _digest(previous),
        "previous_resume_plan_sha256": previous["resume_plan_sha256"],
        "prior_cumulative_request_cap": prior_cap,
        "max_workers": 1, "resume_policy": RETRY_POLICY,
        "retry_prompt_variant": "original", "stop_on_any_failure": True,
        "allow_key_failover": False, "api_key_slots": selected_slots,
        "effective_quarantined_api_key_slots": quarantine, "targets": selected,
    }
    amended.pop("resume_plan_sha256")
    amended["resume_plan_sha256"] = _digest(amended)
    return amended


__all__ = ["RETRY_POLICY", "apply_explicit_retry"]
