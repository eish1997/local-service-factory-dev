"""Pure, hash-bound TinySnow generation migration for a frozen truck job.

The caller first validates the original evidence with ``build_resume_plan``
and applies ``apply_schedule_amendment``. This module never reads credentials,
edits production evidence, grants authority, or opens a network connection.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from tools import category_image_resume
from tools.category_resume_schedule import _inherited_quarantine, apply_schedule_amendment


RAW_CONTRACT = "tinysnow_4k_to_legacy_v1"
ACCEPTED_SOURCE_RAW_CONTRACT = "tinysnow_2352x3520_to_legacy_v1"
TOLERANT_SOURCE_RAW_CONTRACT = "tinysnow_2336_2352x3520_to_legacy_v1"
ACCEPTED_SOURCE_SIZE = "2352x3520"
_SPEC_FIELDS = frozenset({"model", "quality", "api_size", "credential_epoch", "rotated_slots"})
_OPTIONAL_SPEC_FIELDS = frozenset({"accepted_source_size", "accepted_source_width_tolerance"})
_QUALITY = frozenset({"auto", "low", "medium", "high"})


def _fail(message: str) -> None:
    raise category_image_resume.ResumePlanError(message)


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        _fail(f"{label}必须为非负整数")
    return value


def _sha(value: Any) -> str:
    return category_image_resume._canonical_sha256(value)


def _validate_spec(spec: Any, selected: list[int], *, continuation: bool = False) -> None:
    if (not isinstance(spec, dict) or not _SPEC_FIELDS.issubset(spec)
            or not set(spec).issubset(_SPEC_FIELDS | _OPTIONAL_SPEC_FIELDS)):
        _fail("生成迁移参数必须精确包含模型、质量、尺寸、凭据代次及轮换槽位")
    if "accepted_source_size" in spec and spec["accepted_source_size"] != ACCEPTED_SOURCE_SIZE:
        _fail("本次实际源尺寸授权只接受明确的 2352x3520")
    if continuation and spec.get("accepted_source_size") != ACCEPTED_SOURCE_SIZE:
        _fail("同凭据代次的迁移续跑必须明确绑定已接受的实际源尺寸")
    tolerance = spec.get("accepted_source_width_tolerance", 0)
    if type(tolerance) is not int or tolerance not in {0, 16}:
        _fail("实际源图宽度接受值只能为明确的 0 或 16")
    if tolerance == 16 and spec.get("accepted_source_size") != ACCEPTED_SOURCE_SIZE:
        _fail("宽度16接受值必须绑定2352x3520基准，仅允许2336或2352两种宽度")
    if spec["model"] != "gpt-image-2-4k":
        _fail("本迁移只支持已明确指定的 TinySnow 4K 模型")
    if not isinstance(spec["quality"], str) or spec["quality"] not in _QUALITY:
        _fail("迁移质量参数必须为显式支持的质量标识")
    size = spec["api_size"]
    if not isinstance(size, str) or (
        size != "auto" and not re.fullmatch(r"[1-9][0-9]{2,4}x[1-9][0-9]{2,4}", size)
    ):
        _fail("迁移 API 尺寸必须显式指定为 auto 或 WxH")
    if size != "auto" and any(int(part) > 16384 for part in size.split("x")):
        _fail("迁移 API 尺寸超出本地安全边界")
    if not isinstance(spec["credential_epoch"], str) or not re.fullmatch(
        r"credential-[0-9a-f]{32}", spec["credential_epoch"]
    ):
        _fail("凭据代次必须为随机 credential-UUID 标识，不得传入凭据")
    rotated = spec["rotated_slots"]
    if (
        not isinstance(rotated, list)
        or (not rotated and not continuation)
        or any(type(slot) is not int or slot < 1 for slot in rotated)
        or len(set(rotated)) != len(rotated)
        or not set(rotated).issubset(selected)
    ):
        _fail("轮换槽位必须为本次调度中明确选择的不同槽位")


def _continuation_quarantine(
    previous: dict[str, Any], migration: dict[str, Any], spec: dict[str, Any],
    plan: dict[str, Any], selected: list[int], events: list[dict[str, Any]],
    start_index: int,
) -> list[int]:
    """Carry this credential epoch forward without undoing new quarantines."""

    expected_old = {"model": plan["model"], "quality": plan["quality"], "api_size": plan["size"]}
    expected_new = {key: spec[key] for key in ("model", "quality", "api_size")}
    if (
        previous.get("generation_migration_confirmed") is not True
        or migration.get("schema_version") != 1
        or migration.get("kind") != "category-resume-generation-migration"
        or migration.get("old_generation") != expected_old
        or migration.get("new_generation") != expected_new
        or migration.get("credential_epoch") != spec["credential_epoch"]
        or spec["rotated_slots"] != []
        or migration.get("raw_contract") not in {RAW_CONTRACT, ACCEPTED_SOURCE_RAW_CONTRACT, TOLERANT_SOURCE_RAW_CONTRACT}
    ):
        _fail("源尺寸继续授权只能承接同一生成配置和凭据代次，不能再次解禁或轮换槽位")
    accepted = migration.get("accepted_source_size")
    tolerance = migration.get("accepted_source_width_tolerance", 0)
    if (
        type(tolerance) is not int or tolerance not in {0, 16}
        or migration["raw_contract"] == ACCEPTED_SOURCE_RAW_CONTRACT and (accepted != ACCEPTED_SOURCE_SIZE or tolerance != 0)
        or migration["raw_contract"] == TOLERANT_SOURCE_RAW_CONTRACT and (accepted != ACCEPTED_SOURCE_SIZE or tolerance != 16)
        or migration["raw_contract"] == RAW_CONTRACT and ("accepted_source_size" in migration or tolerance != 0)
    ):
        _fail("前序迁移的源尺寸与尺寸契约不一致")
    prior_id = migration.get("previous_authorization_id")
    prior_sha = migration.get("previous_authorization_sha256")
    if (
        not isinstance(prior_id, str) or not re.fullmatch(r"resume-[0-9a-f]{24}", prior_id)
        or prior_id == previous["authorization_id"]
        or not isinstance(prior_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", prior_sha)
    ):
        _fail("前序迁移缺少安全的授权链身份及校验码")
    earlier_cap = _integer(migration.get("prior_cumulative_request_cap"), "前序迁移继承上限")
    if not previous["approved_cumulative_request_budget"] <= earlier_cap <= plan["budget"]:
        _fail("前序迁移预算链不能扩大已经生效的累计上限")
    for key in ("rotated_slots", "inherited_quarantined_api_key_slots", "effective_quarantined_api_key_slots"):
        values = migration.get(key)
        if (
            not isinstance(values, list)
            or any(type(slot) is not int or slot not in selected for slot in values)
            or len(values) != len(set(values))
        ):
            _fail("前序迁移缺少可验证的凭据轮换及隔离槽位")
    expected_effective = [slot for slot in migration["inherited_quarantined_api_key_slots"]
                          if slot not in migration["rotated_slots"]]
    if migration["effective_quarantined_api_key_slots"] != expected_effective:
        _fail("前序迁移的有效隔离与明确轮换历史不一致")
    start = events[start_index]
    start_expected = {
        **expected_new,
        "credential_epoch": spec["credential_epoch"],
        "resume_plan_sha256": previous.get("resume_plan_sha256"),
        "requests_used_start": previous["requests_used"],
        "cumulative_max_requests": previous["approved_cumulative_request_budget"],
    }
    if (
        not isinstance(start_expected["resume_plan_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", start_expected["resume_plan_sha256"])
        or any(start.get(key) != value for key, value in start_expected.items())
    ):
        _fail("前序迁移启动事件未绑定同一凭据代次、配置及累计预算")
    tail = events[start_index + 1:]
    for event in tail:
        if event.get("status") in {"request_reserved", "request_failed", "generated"}:
            if (event.get("authorization_id") != previous["authorization_id"]
                    or event.get("credential_epoch") != spec["credential_epoch"]):
                _fail("前序迁移之后的请求事件不属于同一授权和凭据代次")
    return sorted(set(expected_effective).union(_inherited_quarantine(tail, selected)))


def apply_generation_migration(
    plan: dict[str, Any],
    license_data: dict[str, Any],
    events: list[dict[str, Any]],
    previous_authorization: dict[str, Any],
    migration_spec: dict[str, Any],
) -> dict[str, Any]:
    """Bind a new generation profile without resetting the original ledger.

    The top-level frozen model/quality/size and schedule quarantine remain
    unchanged. Only the explicit migration's effective quarantine removes
    rotated slots. ``previous_authorization_sha256`` is the canonical JSON
    object digest, not a file-byte digest. API parameter syntax validation is
    not evidence that the relay supports those parameters.
    """

    if not all(isinstance(value, dict) for value in (plan, license_data, previous_authorization)):
        _fail("生成迁移必须基于恢复计划、原许可证和前序续跑授权")
    if "generation_migration" in plan:
        _fail("禁止重复应用本次生成迁移")
    previous_migration = previous_authorization.get("generation_migration")
    if "generation_migration" in previous_authorization and not isinstance(previous_migration, dict):
        _fail("前序生成迁移侧车结构无效")
    material = deepcopy(plan)
    stored_hash = material.pop("resume_plan_sha256", None)
    if not isinstance(stored_hash, str) or stored_hash != _sha(material):
        _fail("生成迁移输入计划校验码不一致")
    amendment = material.pop("schedule_amendment", None)
    if not isinstance(amendment, dict):
        _fail("生成迁移必须先明确应用固定十路调度变更")
    selected = amendment.get("api_key_slots")
    rebuilt = apply_schedule_amendment(material, license_data, events, selected)
    if rebuilt != plan:
        _fail("生成迁移输入调度、隔离或预算与原事件账本不一致")
    _validate_spec(migration_spec, selected, continuation=previous_migration is not None)
    if (
        license_data.get("provider") != "relay"
        or str(license_data.get("base_url", "")).rstrip("/") != "https://tinysnow.one/v1"
        or license_data.get("third_party_confirmed") is not True
        or license_data.get("category_id") != "truck_rescue"
        or license_data.get("model") != "gpt-image-2.5-flare"
        or license_data.get("size") != "1024x1536"
        or license_data.get("status") != "consumed"
        or license_data.get("one_time") is not True
    ):
        _fail("原任务不属于本次已确认的 TinySnow 货车生成迁移范围")

    previous = previous_authorization
    if (
        previous.get("kind") != "category-image-resume-authorization"
        or previous.get("status") != "consumed"
        or previous.get("one_time") is not True
        or not isinstance(previous.get("consumed_at"), str)
        or not previous["consumed_at"]
        or previous.get("schedule_amendment_confirmed") is not True
    ):
        _fail("生成迁移必须承接已消费的一次性调度续跑授权")
    previous_id = previous.get("authorization_id")
    if not isinstance(previous_id, str) or not re.fullmatch(r"resume-[0-9a-f]{24}", previous_id):
        _fail("前序续跑授权标识无效")
    for key in ("job_id", "license_id", "category_id", "batch_id", "model", "quality", "size",
                "frozen_manifest_sha256", "frozen_overlay_sha256"):
        if key not in previous or previous[key] != plan.get(key):
            _fail(f"前序续跑授权与冻结任务不一致：{key}")
    if (
        not isinstance(license_data.get("plan_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", license_data["plan_sha256"])
        or previous.get("original_plan_sha256") != license_data["plan_sha256"]
        or previous.get("max_workers") != 10
        or previous.get("api_key_slots") != selected
        or not isinstance(previous.get("schedule_amendment"), dict)
        or previous["schedule_amendment"].get("api_key_slots") != selected
    ):
        _fail("前序续跑授权未绑定本次原计划和十路槽位")
    start_indices = [index for index, event in enumerate(events) if event.get("status") == "resume_started"]
    if not start_indices or events[start_indices[-1]].get("authorization_id") != previous_id:
        _fail("前序授权必须是原事件账本中最后启动的续跑授权")
    if previous_migration is not None and sum(events[index].get("authorization_id") == previous_id for index in start_indices) != 1:
        _fail("前序迁移只能有一个可核验的启动事件")

    used = _integer(plan.get("requests_used"), "累计请求数")
    budget = _integer(license_data.get("approved_request_budget"), "原请求预算")
    prior_cap = _integer(previous.get("approved_cumulative_request_budget"), "前序累计请求上限")
    prior_used = _integer(previous.get("requests_used"), "前序起始请求数")
    prior_remaining = _integer(previous.get("approved_remaining_request_budget"), "前序剩余请求上限")
    if (
        type(previous.get("original_approved_request_budget")) is not int
        or previous["original_approved_request_budget"] != budget
        or prior_used + prior_remaining != prior_cap
        or prior_used > used
        or used > prior_cap
        or prior_cap > budget
    ):
        _fail("前序预算链不一致或累计请求已超过生效上限")
    attempts_used = plan.get("attempts_used")
    allowances = plan.get("attempts_remaining")
    if not isinstance(attempts_used, dict) or not isinstance(allowances, dict) or set(attempts_used) != set(allowances):
        _fail("生成迁移缺少完整逐目标请求账本")
    if sum(_integer(value, "目标已用请求数") for value in attempts_used.values()) != used:
        _fail("逐目标已用请求数与累计请求数不一致")
    remaining = sum(_integer(value, "目标剩余请求数") for value in allowances.values())
    if {target for target, value in allowances.items() if value > 0} != set(plan["resumable_ids"]):
        _fail("逐目标剩余次数与可续跑目标不一致")
    if set(plan.get("success_ids", [])) & set(plan["resumable_ids"]):
        _fail("成功目标不得重新进入迁移续跑集合")

    amended = deepcopy(plan)
    cumulative = min(budget, prior_cap, used + remaining)
    amended["cumulative_max_requests"] = cumulative
    amended["remaining_max_requests"] = cumulative - used
    inherited = (
        _continuation_quarantine(previous, previous_migration, migration_spec, plan, selected, events, start_indices[-1])
        if previous_migration is not None else list(amendment["inherited_quarantined_api_key_slots"])
    )
    rotated = list(migration_spec["rotated_slots"])
    amended["generation_migration"] = {
        "schema_version": 1,
        "kind": "category-resume-generation-migration",
        "old_generation": {"model": plan["model"], "quality": plan["quality"], "api_size": plan["size"]},
        "new_generation": {key: migration_spec[key] for key in ("model", "quality", "api_size")},
        "raw_contract": (
            TOLERANT_SOURCE_RAW_CONTRACT if migration_spec.get("accepted_source_width_tolerance", 0) == 16
            else ACCEPTED_SOURCE_RAW_CONTRACT if "accepted_source_size" in migration_spec else RAW_CONTRACT
        ),
        "credential_epoch": migration_spec["credential_epoch"],
        "rotated_slots": rotated,
        "previous_authorization_id": previous_id,
        "previous_authorization_sha256": _sha(previous),
        "prior_cumulative_request_cap": prior_cap,
        "inherited_quarantined_api_key_slots": inherited,
        "effective_quarantined_api_key_slots": [slot for slot in inherited if slot not in rotated],
    }
    if "accepted_source_size" in migration_spec:
        amended["generation_migration"]["accepted_source_size"] = migration_spec["accepted_source_size"]
    if migration_spec.get("accepted_source_width_tolerance", 0) == 16:
        amended["generation_migration"]["accepted_source_width_tolerance"] = 16
    amended.pop("resume_plan_sha256")
    amended["resume_plan_sha256"] = _sha(amended)
    return amended


__all__ = ["RAW_CONTRACT", "ACCEPTED_SOURCE_RAW_CONTRACT", "TOLERANT_SOURCE_RAW_CONTRACT",
           "ACCEPTED_SOURCE_SIZE", "apply_generation_migration"]
