"""Pure, hash-bound scheduling amendments for an existing resume ledger.

Callers must first validate the original frozen evidence with
``build_resume_plan`` and supply that job's exact event records.  This module
does not grant production authority, write state, or import a network client.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools import category_image_resume


_IDENTITY_FIELDS = (
    "license_id",
    "category_id",
    "batch_id",
    "group_start",
    "group_count",
    "scope",
    "provider",
    "model",
    "quality",
    "size",
    "max_attempts",
    "retry_policy",
)


def _fail(message: str) -> None:
    raise category_image_resume.ResumePlanError(message)


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{label}必须是不小于 {minimum} 的整数")
    return value


def _slots(value: Any, label: str, *, allow_empty: bool = False) -> list[int]:
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail(f"{label}必须是 Key 槽位列表")
    slots = [_integer(slot, label, minimum=1) for slot in value]
    if len(set(slots)) != len(slots):
        _fail(f"{label}不能包含重复槽位")
    return slots


def _inherited_quarantine(events: list[dict[str, Any]], selected: list[int]) -> list[int]:
    if not isinstance(events, list):
        _fail("调度变更必须使用原任务事件列表")
    quarantined: set[int] = set()
    for event in events:
        if not isinstance(event, dict):
            _fail("原任务事件必须是 JSON 对象")
        if category_image_resume._is_balance_failure(event):
            quarantined.add(_integer(event.get("api_key_slot"), "余额失败槽位", minimum=1))
        if "quarantined_api_key_slots" in event:
            quarantined.update(
                _slots(
                    event["quarantined_api_key_slots"],
                    "事件隔离槽位",
                    allow_empty=True,
                )
            )
    # Later empty snapshots or successful requests never undo a prior
    # quarantine. Raw provider errors are only classified, never copied out.
    return sorted(quarantined.intersection(selected))


def apply_schedule_amendment(
    plan: dict[str, Any],
    license_data: dict[str, Any],
    events: list[dict[str, Any]],
    api_key_slots: list[int],
) -> dict[str, Any]:
    """Bind fixed-ten scheduling without altering scope or original budgets.

    The returned plan is an independent copy. Per-target allowances remain
    unchanged, but their total is capped by the original license's remaining
    request budget, including every historical insufficient-balance request.
    The caller must separately obtain and enforce the scoped schedule-change
    authorization; changing this plan never edits the consumed license.
    """

    if not isinstance(plan, dict) or not isinstance(license_data, dict):
        _fail("调度变更需要原恢复计划和许可证对象")
    if "schedule_amendment" in plan:
        _fail("调度变更必须基于未经修订的原恢复计划")
    for key in _IDENTITY_FIELDS:
        if key not in plan or key not in license_data or plan[key] != license_data[key]:
            _fail(f"恢复计划与原许可证字段不一致：{key}")
    if "job_id" in license_data and license_data["job_id"] != plan.get("job_id"):
        _fail("恢复计划与原许可证字段不一致：job_id")

    selected = _slots(api_key_slots, "api_key_slots")
    original = _slots(license_data.get("api_key_slots"), "原许可证 api_key_slots")
    if len(selected) != 10:
        _fail("固定10路调度变更必须明确选择10个不同 Key 槽位")
    if not set(original).issubset(selected):
        _fail("调度变更必须保留原许可证的全部 Key 槽位")

    budget = _integer(license_data.get("approved_request_budget"), "原请求预算")
    requests_used = _integer(plan.get("requests_used"), "已使用请求数")
    if _integer(plan.get("budget"), "恢复计划预算") != budget:
        _fail("恢复计划预算与原许可证不一致")
    if _integer(license_data.get("requests_used"), "许可证已使用请求数") != requests_used:
        _fail("恢复计划与原许可证已使用请求数不一致")
    if requests_used > budget:
        _fail("已使用请求数超过原许可证预算，不能继续")

    counts = plan.get("counts")
    resumable_ids = plan.get("resumable_ids")
    if not isinstance(counts, dict) or not isinstance(resumable_ids, list):
        _fail("恢复计划缺少可续跑目标账本")
    if _integer(counts.get("resumable"), "可续跑目标数") != len(resumable_ids):
        _fail("恢复计划可续跑目标数量不一致")
    if len(resumable_ids) < 10:
        _fail("固定10路调度变更至少需要10个可续跑目标")
    allowances = plan.get("attempts_remaining")
    if not isinstance(allowances, dict):
        _fail("恢复计划缺少原目标剩余次数")
    remaining = sum(_integer(value, "目标剩余次数") for value in allowances.values())

    amended = deepcopy(plan)
    amended["remaining_max_requests"] = min(remaining, budget - requests_used)
    amended["cumulative_max_requests"] = requests_used + amended["remaining_max_requests"]
    amended["schedule_amendment"] = {
        "schema_version": 1,
        "kind": "category-resume-schedule-amendment",
        "api_key_slots": selected,
        "original_api_key_slots": original,
        "max_workers": 10,
        "resume_policy": "fixed_10_probe_policy_circuit_v1",
        "inherited_quarantined_api_key_slots": _inherited_quarantine(events, selected),
        "strict_original_request_budget": budget,
    }
    amended.pop("resume_plan_sha256", None)
    amended["resume_plan_sha256"] = category_image_resume._canonical_sha256(amended)
    return amended


__all__ = ["apply_schedule_amendment"]
