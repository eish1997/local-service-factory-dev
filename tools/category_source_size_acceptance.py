"""Explicit job-scoped source-size acceptance and zero-API archived-source recovery.

The immutable acceptance binds the original evidence and ledger prefix. Recovery
adds a non-request event; it never rewrites licenses, request failures or budgets.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from tools import category_image_production as production
from tools import image_download_receipts as receipts
from tools.category_4k_raw import (
    DECODABLE_SOURCE_POLICY, HD_DELIVERY_SOURCE_POLICY, MAX_SOURCE_BYTES, prepare_source_size_raw, publish_immutable_bytes,
)
from tools.category_process_identity import recorded_job_pid_is_running

POLICY_ID = DECODABLE_SOURCE_POLICY
POLICY_IDS = frozenset({POLICY_ID, HD_DELIVERY_SOURCE_POLICY})
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
_STOPPED = {"paused_api_errors", "paused_image_download", "paused_probe_failed", "paused_resume_probe_failed"}


def _ledger():
    # Keep the shared ledger's optional acceptance import acyclic.
    from tools import category_image_resume
    return category_image_resume


def _fail(message: str) -> None:
    raise _ledger().ResumePlanError(message)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: Any) -> str:
    return _ledger()._canonical_sha256(value)


def _bytes(path: Path, limit: int = MAX_EVIDENCE_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        _fail("源尺寸接受证据缺失、链接或超过安全上限")
    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        _fail("源尺寸接受证据读取超过安全上限")
    return payload


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _path(batch: Path, job_id: str) -> Path:
    _ledger()._safe_identifier(job_id, "source-size job_id")
    directory = batch / "production" / "source_size_acceptances"
    path = directory / f"{job_id}.json"
    if path.is_symlink() or directory.resolve().parent != (batch / "production").resolve():
        _fail("任务源尺寸接受路径越界")
    return path


def _binding(job, license_data, manifest_sha256, overlay_sha256) -> dict[str, Any]:
    from tools.category_generation_profile import validate_profile
    profile = validate_profile(license_data.get("generation_profile"), str(license_data.get("category_id")))
    if job.get("generation_profile") != profile or job.get("license_id") != license_data.get("license_id"):
        _fail("源尺寸接受只能绑定原完整profile和任务许可证")
    if job.get("requests_used") != license_data.get("requests_used"):
        _fail("源尺寸接受账本计数不一致")
    budget = license_data.get("approved_request_budget")
    count = license_data.get("approved_api_request_count")
    if type(budget) is not int or type(count) is not int or budget != count * license_data.get("max_attempts", 0):
        _fail("源尺寸接受不得改变原请求预算")
    fields = ("category_id", "phone", "group_start", "group_count", "scope")
    result = {key: license_data[key] for key in fields}
    for key in ("category_id", "group_start", "group_count", "scope", "plan_sha256"):
        if job.get(key) != license_data.get(key):
            _fail("源尺寸接受任务身份与原许可证不符")
    result.update(job_id=job["job_id"], license_id=license_data["license_id"],
                  original_plan_sha256=license_data["plan_sha256"], manifest_sha256=manifest_sha256,
                  overlay_sha256=overlay_sha256, generation_profile_sha256=_canonical(profile),
                  approved_request_budget=budget)
    return result


def load_acceptance(batch: str | Path, job: dict[str, Any], license_data: dict[str, Any],
                    manifest_sha256: str, overlay_sha256: str) -> dict[str, Any] | None:
    """Read-only validation; absence leaves all original size rules unchanged."""
    batch = Path(batch).resolve()
    path = _path(batch, str(job.get("job_id") or ""))
    if not path.exists():
        return None
    value = json.loads(_bytes(path))
    binding = _binding(job, license_data, manifest_sha256, overlay_sha256)
    expected_keys = set(binding) | {"schema_version", "kind", "policy_id", "confirmed", "created_at",
                                   "acceptance_sha256", "requests_used_at_acceptance", "events_prefix_size",
                                   "events_prefix_sha256", "recovery_sources"}
    if not isinstance(value, dict) or set(value) != expected_keys:
        _fail("源尺寸接受侧车字段不完整或有未知字段")
    if value.get("policy_id") not in POLICY_IDS:
        _fail("未知的任务级源尺寸接受策略")
    for key, expected in {**binding, "schema_version": 1, "kind": "category-source-size-acceptance",
                          "confirmed": True}.items():
        if value.get(key) != expected or (key == "confirmed" and value[key] is not True):
            _fail("源尺寸接受侧车与冻结任务不匹配：" + key)
    signed = {key: item for key, item in value.items() if key != "acceptance_sha256"}
    if value["acceptance_sha256"] != _canonical(signed):
        _fail("源尺寸接受侧车摘要不一致")
    used = value["requests_used_at_acceptance"]
    if type(used) is not int or not 0 <= used <= license_data["requests_used"] <= value["approved_request_budget"]:
        _fail("源尺寸接受创建时请求账本无效")
    events_path = batch / "production" / f"events_{job['job_id']}.jsonl"
    events_bytes = _bytes(events_path)
    length = value["events_prefix_size"]
    if type(length) is not int or not 0 < length <= len(events_bytes):
        _fail("源尺寸接受事件前缀长度无效")
    prefix = events_bytes[:length]
    if not prefix.endswith(b"\n") or _sha(prefix) != value["events_prefix_sha256"]:
        _fail("源尺寸接受创建时事件前缀已变化")
    events = [json.loads(line) for line in prefix.splitlines() if line.strip()]
    numbers = [event.get("request_number") for event in events if event.get("status") == "request_reserved"]
    if sorted(numbers) != list(range(1, used + 1)):
        _fail("源尺寸接受创建时必须是连续且唯一的请求账本")
    sources = value["recovery_sources"]
    if not isinstance(sources, list) or len(sources) > used:
        _fail("源尺寸接受恢复源清单无效")
    if len({item.get("generation_target_id") for item in sources}) != len(sources):
        _fail("源尺寸接受恢复目标重复")
    return value


def _artifact(batch: Path, reference: Any, root: Path) -> Path:
    path = _ledger()._relative_artifact_path(batch, reference, "source-size artifact")
    if root.resolve() not in path.parents or path.is_symlink():
        _fail("源尺寸恢复文件越出原任务目录")
    return path


def _is_archived_size_rejection(event):
    if event.get("status") != "request_failed" or event.get("will_retry") is not False:
        return False
    if event.get("error_kind") == "raw_contract_rejected":
        return event.get("archive_status") == "rejected"
    # Older workers labeled a local size rejection as a download failure.
    # The archive, decoded pixels and signed metadata are still checked below.
    return (event.get("error_kind") == "image_download_failed"
            and "error_type=RawImageContractError;" in str(event.get("error") or "")
            and all(event.get(key) for key in ("provider_original", "provider_original_metadata",
                                               "source_sha256", "source_returned_size", "raw_contract")))


def _source_evidence(batch, rows, events, job, license_data, request_number, policy_id=POLICY_ID):
    failures = [event for event in events if event.get("status") == "request_failed"
                and event.get("request_number") == request_number]
    reservations = [event for event in events if event.get("status") == "request_reserved"
                    and event.get("request_number") == request_number]
    if len(failures) != 1 or len(reservations) != 1:
        _fail("本地恢复必须绑定唯一预留和失败请求")
    failed, reserved = failures[0], reservations[0]
    if (not _is_archived_size_rejection(failed)
            or failed.get("raw_contract") != license_data["generation_profile"]["raw_contract"]):
        _fail("本地尺寸恢复只允许已归档的原profile尺寸拒绝")
    matches = [row for row in rows if row["generation_target_id"] == failed.get("generation_target_id")]
    if len(matches) != 1:
        _fail("本地尺寸恢复目标不在冻结清单")
    row = matches[0]
    _ledger()._event_identity(failed, row, request_number)
    _ledger()._event_identity(reserved, row, request_number)
    for key in ("generation_target_id", "attempt", "api_key_slot", "authorization_id"):
        if failed.get(key) != reserved.get(key):
            _fail("本地尺寸恢复请求绑定不一致")
    if any(event.get("generation_target_id") == row["generation_target_id"]
           and event.get("status") in {"request_reserved", "generated", "request_failed"}
           and event.get("attempt", 0) > failed["attempt"] for event in events):
        _fail("该源图失败之后已有后续请求，禁止恢复旧源")
    archive_root = batch / "production" / "provider_originals" / job["job_id"]
    source = _artifact(batch, failed.get("provider_original"), archive_root)
    metadata_path = _artifact(batch, failed.get("provider_original_metadata"), archive_root)
    if metadata_path != source.with_name(source.name + ".json"):
        _fail("原拒绝侧车路径不匹配")
    payload = _bytes(source, MAX_SOURCE_BYTES)
    metadata = json.loads(_bytes(metadata_path))
    for key, expected in {
        "source_sha256": _sha(payload), "source_returned_size": failed.get("source_returned_size"),
        "raw_contract": failed.get("raw_contract"), "archive_status": "rejected", "normalized": False,
        "model": license_data["model"], "quality": license_data["quality"], "api_size": license_data["size"],
    }.items():
        if metadata.get(key) != expected:
            _fail("原拒绝源图证据不一致：" + key)
    if failed.get("source_sha256") != _sha(payload) or Path(metadata.get("provider_original", "")).resolve() != source:
        _fail("原拒绝源图哈希或路径不一致")
    raw_bytes, decoded = prepare_source_size_raw(payload, anchor_y=0.0 if row["generation_kind"] == "cover" else 0.5,
                                                source_size_policy=policy_id)
    if (decoded["source_returned_size"] != failed.get("source_returned_size")
            or decoded["source_format"] != metadata.get("source_format")):
        _fail("原拒绝源图实际尺寸不一致")
    context = {
        "root": str(production.ROOT / ".runtime" / "image_download_receipts"),
        "job_id": job["job_id"], "license_id": license_data["license_id"],
        "generation_target_id": row["generation_target_id"], "request_number": request_number,
        "attempt": failed["attempt"], "model": license_data["model"], "quality": license_data["quality"],
        "api_size": license_data["size"], "effective_prompt_sha256": reserved["effective_prompt_sha256"],
        "original_plan_sha256": license_data["plan_sha256"],
    }
    receipt_path = receipts._path(context)
    if receipt_path.exists():
        document, _ = receipts._load_document(receipt_path, receipts._binding(context))
        if document["state"] == "materialized" and document["raw_sha256"] != decoded["saved_raw_sha256"]:
            _fail("已完成的图片回执与恢复工作图哈希不符")
    elif receipt_path.with_suffix(".claim").exists():
        _fail("已返回图片回执尚未完整保存，禁止恢复")
    frozen = {
        "request_number": request_number, "generation_target_id": row["generation_target_id"],
        "failed_event_sha256": _canonical(failed), "reserved_event_sha256": _canonical(reserved),
        "provider_original": failed["provider_original"], "source_sha256": _sha(payload),
        "provider_original_metadata": failed["provider_original_metadata"],
        "provider_original_metadata_sha256": _sha(_bytes(metadata_path)),
        "receipt_id": receipts.receipt_id_for_context(context) if receipt_path.exists() else None,
    }
    return dict(frozen=frozen, row=row, failed=failed, reserved=reserved, context=context,
                source=source, metadata_path=metadata_path, raw_bytes=raw_bytes, decoded=decoded)


def _recovery_files(batch, acceptance, evidence):
    row, source = evidence["row"], evidence["source"]
    raw = _artifact(batch, row["raw_target"], batch / "raw")
    metadata_path = source.with_name(source.name + ".source-size-" + acceptance["acceptance_sha256"] + ".json")
    data = {**evidence["decoded"], "acceptance_sha256": acceptance["acceptance_sha256"],
            "provider_original": str(source), "provider_original_metadata": str(metadata_path),
            "prior_provider_original_metadata": str(evidence["metadata_path"]),
            "raw_target": row["raw_target"], "model": evidence["context"]["model"],
            "quality": evidence["context"]["quality"], "api_size": evidence["context"]["api_size"]}
    return raw, metadata_path, data


def _recovery_event(batch, acceptance, evidence):
    raw, metadata_path, metadata = _recovery_files(batch, acceptance, evidence)
    row, failed = evidence["row"], evidence["failed"]
    event = {
        "status": "source_size_recovered", "job_id": acceptance["job_id"], "license_id": acceptance["license_id"],
        "policy_id": acceptance["policy_id"], "acceptance_sha256": acceptance["acceptance_sha256"],
        "request_number": failed["request_number"], "attempt": failed["attempt"],
        "raw_target": row["raw_target"], "delivery_target": row["target"],
        "failed_event_sha256": evidence["frozen"]["failed_event_sha256"],
        "source_sha256": evidence["decoded"]["source_sha256"],
        "source_returned_size": evidence["decoded"]["source_returned_size"],
        "working_raw_is_upscaled": evidence["decoded"]["working_raw_is_upscaled"],
        "saved_raw_sha256": evidence["decoded"]["saved_raw_sha256"],
        "recovery_metadata": production._artifact_reference(metadata_path, batch),
        "recovery_metadata_sha256": _sha(_json_bytes(metadata)),
        "local_recovery_confirmed": True, "api_called": False, "request_delta": 0,
    }
    for key in ("generation_target_id", "delivery_target_id", "group_index", "generation_position", "delivery_position"):
        event[key] = row[key]
    return event


def validated_recoveries(batch: str | Path, rows, events, job, license_data, acceptance) -> dict[str, dict[str, Any]]:
    """Recognize only exact non-request recovery evidence, never rewrite history."""
    batch = Path(batch).resolve()
    recovered = {}
    recovery_events = [event for event in events if event.get("status") == "source_size_recovered"]
    if not acceptance:
        if recovery_events:
            _fail("存在无任务级尺寸接受授权的恢复事件")
        return recovered
    allowed = {item["request_number"]: item for item in acceptance["recovery_sources"]}
    for event in recovery_events:
        number = event.get("request_number")
        if number not in allowed:
            _fail("恢复事件不在尺寸接受冻结范围")
        evidence = _source_evidence(batch, rows, events, job, license_data, number, acceptance["policy_id"])
        if evidence["frozen"] != allowed[number]:
            _fail("尺寸恢复的原请求或源证据变化")
        expected = _recovery_event(batch, acceptance, evidence)
        if {key: value for key, value in event.items() if key != "at"} != expected:
            _fail("尺寸恢复事件与独立证据不匹配")
        raw, metadata_path, metadata = _recovery_files(batch, acceptance, evidence)
        if (_sha(_bytes(raw)) != expected["saved_raw_sha256"]
                or _bytes(metadata_path) != _json_bytes(metadata)
                or not production.valid_png(raw, production.RAW_API_SIZE)):
            _fail("尺寸恢复工作图或独立侧车不匹配")
        target = event["generation_target_id"]
        if target in recovered:
            _fail("同一目标重复尺寸恢复")
        recovered[target] = event
    return recovered


def _context(batch, job_file, license_file, policy_id=POLICY_ID):
    ledger = _ledger()
    job, license_data, manifest, rows, overlay, _, events_path, events = ledger._validate_fixed_evidence(batch, job_file, license_file)
    if job.get("status") not in _STOPPED:
        _fail("源尺寸接受仅允许已安全暂停的任务")
    for key in ("pid", "worker_pid"):
        pid = int(job.get(key, 0) or 0)
        if pid and recorded_job_pid_is_running(pid, job):
            _fail("原生产进程仍运行，禁止修改源尺寸接受状态")
    if job.get("resume_authorization_id"):
        session_path = batch / "production" / "resume_sessions" / f"{ledger._safe_identifier(job['resume_authorization_id'], 'resume id')}.json"
        session = ledger._load_json(session_path, "源尺寸接受暂停会话")
        for key, expected in (("job_id", job["job_id"]), ("license_id", license_data["license_id"]),
                              ("status", job["status"]), ("requests_used_end", license_data["requests_used"])):
            if session.get(key) != expected:
                _fail("源尺寸接受暂停会话未与原任务排空状态一致")
        if session.get("pid") is not None:
            _fail("源尺寸接受暂停会话尚未确认进程排空")
    acceptance = load_acceptance(batch, job, license_data, ledger._file_sha256(manifest), ledger._file_sha256(overlay))
    if acceptance and acceptance["policy_id"] != policy_id:
        _fail("已有任务级接受策略不同，不允许覆盖")
    ledger._account_attempts(batch, rows, events, job, license_data, acceptance)
    if acceptance:
        numbers = [item["request_number"] for item in acceptance["recovery_sources"]]
    else:
        numbers = [event["request_number"] for event in events if _is_archived_size_rejection(event)]
    evidence = [_source_evidence(batch, rows, events, job, license_data, number, policy_id) for number in numbers]
    snapshots = {str(path): ledger._file_sha256(path) for path in (job_file, license_file, manifest, overlay, events_path)}
    for item in evidence:
        for path in (item["source"], item["metadata_path"], receipts._path(item["context"])):
            if path.exists():
                snapshots[str(path)] = ledger._file_sha256(path)
    if acceptance:
        snapshots[str(_path(batch, job["job_id"]))] = ledger._file_sha256(_path(batch, job["job_id"]))
    if job.get("resume_authorization_id"):
        snapshots[str(session_path)] = ledger._file_sha256(session_path)
    if acceptance:
        if [item["frozen"] for item in evidence] != acceptance["recovery_sources"]:
            _fail("冻结恢复源证据已变化")
    return dict(job=job, license=license_data, rows=rows, events=events, events_path=events_path,
                manifest=manifest, overlay=overlay, acceptance=acceptance, evidence=evidence, snapshots=snapshots)


def _append_recovery(path: Path, event: dict[str, Any]) -> None:
    # The production lock excludes writers. A short final write can be retried
    # conservatively only after inspection; never truncate original evidence.
    with path.open("ab") as handle:
        handle.write((json.dumps({"at": production.now_iso(), **event}, ensure_ascii=False) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def accept_source_sizes(batch_dir: str | Path, job_path: str | Path, license_path: str | Path, *, confirm: bool,
                        policy_id: str = POLICY_ID) -> dict[str, Any]:
    """Explicit local-only command. Preserve job/license bytes and all request counts."""
    if confirm is not True:
        _fail("任务级源尺寸接受需要用户明确指令")
    if policy_id not in POLICY_IDS:
        _fail("未知的任务级源尺寸接受策略")
    batch, job_file, license_file = (Path(value).resolve() for value in (batch_dir, job_path, license_path))
    context = _context(batch, job_file, license_file, policy_id)
    from tools.category_source_recovery import _acquire_recovery_lock
    lock = batch / "production" / "generation.lock"
    owned_lock = _acquire_recovery_lock(lock, context["job"]["job_id"])
    try:
        current = _context(batch, job_file, license_file, policy_id)
        if context["snapshots"] != current["snapshots"]:
            _fail("取得生产锁后源尺寸接受证据已变化")
        context = current
        job, license_data = context["job"], context["license"]
        acceptance = context["acceptance"]
        if acceptance is None:
            prefix = _bytes(context["events_path"])
            if not prefix.endswith(b"\n"):
                _fail("原事件文件结尾不完整，禁止接受源尺寸")
            acceptance = {
                **_binding(job, license_data, _sha(_bytes(context["manifest"])), _sha(_bytes(context["overlay"]))),
                "schema_version": 1, "kind": "category-source-size-acceptance", "policy_id": policy_id,
                "confirmed": True, "created_at": production.now_iso(),
                "requests_used_at_acceptance": license_data["requests_used"],
                "events_prefix_size": len(prefix), "events_prefix_sha256": _sha(prefix),
                "recovery_sources": [item["frozen"] for item in context["evidence"]],
            }
            acceptance["acceptance_sha256"] = _canonical(acceptance)
            publish_immutable_bytes(_path(batch, job["job_id"]), _json_bytes(acceptance))
            context["snapshots"][str(_path(batch, job["job_id"]))] = _sha(_json_bytes(acceptance))
        recovered = validated_recoveries(batch, context["rows"], context["events"], job, license_data, acceptance)
        for evidence in context["evidence"]:
            raw, metadata_path, metadata = _recovery_files(batch, acceptance, evidence)
            # The deterministic metadata is published before raw. Both operations
            # are no-overwrite and replayable even if the process stops between them.
            publish_immutable_bytes(metadata_path, _json_bytes(metadata))
            publish_immutable_bytes(raw, evidence["raw_bytes"])
            event = _recovery_event(batch, acceptance, evidence)
            if event["generation_target_id"] not in recovered:
                validated_recoveries(batch, context["rows"], context["events"] + [event], job, license_data, acceptance)
                for filename, expected in context["snapshots"].items():
                    if _sha(_bytes(Path(filename))) != expected:
                        _fail("本地保存期间原证据发生变化，保留新图但禁止追加恢复事件")
                _append_recovery(context["events_path"], event)
                context["events"].append(event)
                context["snapshots"][str(context["events_path"])] = _sha(_bytes(context["events_path"]))
            # An event-durable/receipt-pending interruption is safe to replay.
            receipts.mark_materialized(evidence["context"], evidence["decoded"]["saved_raw_sha256"])
            receipt_path = receipts._path(evidence["context"])
            if receipt_path.exists():
                context["snapshots"][str(receipt_path)] = _sha(_bytes(receipt_path))
        return {"status": "source_size_accepted", "api_called": False, "request_delta": 0,
                "requests_used": license_data["requests_used"], "approved_request_budget": acceptance["approved_request_budget"],
                "acceptance_path": str(_path(batch, job["job_id"])), "policy_id": policy_id,
                "acceptance_sha256": acceptance["acceptance_sha256"],
                "recovered_count": len(context["evidence"]),
                "recovered_generation_target_ids": [item["row"]["generation_target_id"] for item in context["evidence"]]}
    finally:
        if lock.is_file() and lock.read_bytes() == owned_lock:
            lock.unlink()


__all__ = ["POLICY_ID", "accept_source_sizes", "load_acceptance", "validated_recoveries"]
