"""Local-only recovery of one explicitly accepted, already-paid source image.

No provider client is created. Original jobs, licenses, request failures and
rejected source metadata remain byte-for-byte unchanged; only new artifacts
and one non-request recovery event are appended.
"""

from __future__ import annotations

import os
import json
import threading
from pathlib import Path
from typing import Any

from tools import category_image_production as production
from tools import category_image_resume as ledger
from tools.category_4k_raw import save_4k_raw_png
from tools.category_process_identity import recorded_job_pid_is_running


def _fail(message: str) -> None:
    raise ledger.ResumePlanError(message)


def _acquire_recovery_lock(path: Path, job_id: str) -> bytes:
    """Never clear a stale lock, including one arriving after preflight."""

    payload = json.dumps({"pid": os.getpid(), "job_id": job_id,
                          "created_at": production.now_iso()}, ensure_ascii=False).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ledger.ResumePlanError("批次已出现生产锁，本地恢复不会删除旧锁") from error
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    return payload


def _context(batch: Path, job_file: Path, license_file: Path, request_number: int,
             accepted_source_size: str, accepted_source_width_tolerance: int = 0) -> dict[str, Any]:
    plan = ledger.build_resume_plan(batch, job_file, license_file)
    job, license_data, manifest, rows, overlay, _, events_path, events = (
        ledger._validate_fixed_evidence(batch, job_file, license_file)
    )
    allowed_statuses = {"paused_resume_probe_failed"}
    if type(accepted_source_width_tolerance) is int and accepted_source_width_tolerance == 16:
        allowed_statuses.add("paused_api_errors")
    if job.get("status") not in allowed_statuses:
        _fail("本地源图恢复仅适用于已授权尺寸契约失败后安全暂停的任务")
    for key in ("pid", "worker_pid"):
        pid = int(job.get(key, 0) or 0)
        if pid and recorded_job_pid_is_running(pid, job):
            _fail("原生产任务进程仍在运行，禁止恢复源图")
    evidence = ledger._provider_recovery_source(
        batch, rows, events, job, license_data, request_number, accepted_source_size,
        accepted_source_width_tolerance,
    )
    authorization = evidence["authorization"]
    if job.get("resume_authorization_id") != authorization["authorization_id"]:
        _fail("当前job不再属于待恢复源图的原续跑授权")
    session_path = batch / "production" / "resume_sessions" / f"{authorization['authorization_id']}.json"
    session = ledger._load_json(session_path, "待恢复源图的暂停会话")
    for key, expected in {
        "job_id": job["job_id"], "license_id": license_data["license_id"],
        "authorization_id": authorization["authorization_id"],
        "resume_plan_sha256": authorization["resume_plan_sha256"],
        "status": job["status"], "requests_used_end": plan["requests_used"],
    }.items():
        ledger._equal(session.get(key), expected, f"source_recovery.session.{key}")
    if session.get("pid") is not None:
        _fail("源图恢复会话尚未确认进程排空")
    snapshots = {
        str(path): ledger._file_sha256(path)
        for path in (job_file, license_file, manifest, overlay, events_path,
                     evidence["authorization_path"], evidence["source"],
                     evidence["metadata_path"], session_path)
    }
    return dict(plan=plan, job=job, license=license_data, rows=rows, events=events,
                events_path=events_path, snapshots=snapshots, **evidence)


def _existing_normalization(evidence: dict[str, Any], raw: Path) -> dict[str, Any]:
    """Recover a local save/append interruption only with its exact new sidecar."""

    source = evidence["source"]
    candidates = list(source.parent.glob(f"{source.name}.{evidence['recovery_contract']}.*.json"))
    if len(candidates) != 1:
        _fail("已有工作原图但缺少唯一已接受尺寸的成功侧车，禁止覆盖")
    sidecar = candidates[0]
    data = ledger._load_json(sidecar, "已保存工作原图的恢复侧车")
    for key, expected in {
        "raw_contract": evidence["recovery_contract"], "accepted_source_size": "2352x3520",
        "source_sha256": evidence["failed"]["source_sha256"], "source_returned_size": evidence["actual_source_size"],
        "archive_status": "normalized", "normalized": True,
        "normalized_to": "1024x1536", "source_is_upscaled_by_factory": False,
        "credential_epoch": evidence["authorization"]["generation_migration"]["credential_epoch"],
    }.items():
        ledger._equal(data.get(key), expected, f"source_recovery.saved.{key}")
    if (type(data.get("accepted_source_width_tolerance", 0)) is not int
            or data.get("accepted_source_width_tolerance", 0) != evidence["accepted_source_width_tolerance"]):
        _fail("已有工作原图恢复侧车与明确宽度容差不符")
    if (Path(str(data.get("provider_original"))).resolve() != source
            or Path(str(data.get("prior_provider_original_metadata"))).resolve() != evidence["metadata_path"]):
        _fail("恢复侧车未绑定原始归档及旧拒绝侧车")
    if not production.valid_png(raw, production.RAW_API_SIZE):
        _fail("已有恢复工作原图未通过PNG尺寸校验")
    if ledger._file_sha256(raw) != data.get("saved_raw_sha256"):
        _fail("已有恢复工作原图SHA不符，禁止覆盖")
    data["provider_original_metadata"] = str(sidecar)
    return data


def recover_provider_source(
    batch_dir: str | Path, job_path: str | Path, license_path: str | Path, *,
    request_number: int, accepted_source_size: str, confirm: bool,
    accepted_source_width_tolerance: int = 0,
) -> dict[str, Any]:
    """Normalize one archived source and append a strict non-request receipt."""

    if confirm is not True:
        _fail("本地恢复需要明确的实际源图尺寸接受指令")
    if type(request_number) is not int or request_number < 1:
        _fail("恢复请求编号必须为正整数")
    batch, job_file, license_file = (
        Path(value).expanduser().resolve() for value in (batch_dir, job_path, license_path)
    )
    context = _context(batch, job_file, license_file, request_number, accepted_source_size,
                       accepted_source_width_tolerance)
    target_id = context["row"]["generation_target_id"]
    if any(event.get("status") == "provider_source_recovered"
           and event.get("request_number") == request_number for event in context["events"]):
        return {"status": "already_recovered", "api_called": False,
                "requests_used": context["plan"]["requests_used"],
                "generation_target_id": target_id, "counts": context["plan"]["counts"]}
    lock_path = batch / "production" / "generation.lock"
    if lock_path.exists():
        _fail("批次存在生产锁；本地恢复不会移除或覆盖任何旧锁")
    lock = lock_path
    owned_lock = _acquire_recovery_lock(lock, context["job"]["job_id"])
    try:
        current = _context(batch, job_file, license_file, request_number, accepted_source_size,
                           accepted_source_width_tolerance)
        if current["snapshots"] != context["snapshots"]:
            _fail("取得生产锁后恢复证据已变化，禁止写入")
        context = current
        row, failed = context["row"], context["failed"]
        raw = ledger._relative_artifact_path(batch, row["raw_target"], "恢复工作原图")
        raw_root = (batch / "raw").resolve()
        if raw_root not in raw.parents:
            _fail("恢复工作原图不属于冻结批次raw目录")
        if raw.exists():
            save = _existing_normalization(context, raw)
        else:
            migration = context["authorization"]["generation_migration"]
            save = save_4k_raw_png(
                raw, context["source"].read_bytes(),
                archive_root=batch / "production" / "provider_originals" / context["job"]["job_id"],
                generation=migration["new_generation"], credential_epoch=migration["credential_epoch"],
                anchor_y=0.0 if row.get("generation_kind") == "cover" else 0.5,
                accepted_source_size=accepted_source_size,
                accepted_source_width_tolerance=accepted_source_width_tolerance,
            )
        event = {
            "status": "provider_source_recovered", "job_id": context["job"]["job_id"],
            "license_id": context["license"]["license_id"], "authorization_id": failed["authorization_id"],
            "request_number": request_number, "generation_target_id": target_id,
            "delivery_target_id": row["delivery_target_id"], "group_index": row["group_index"],
            "generation_position": row["generation_position"], "delivery_position": row["delivery_position"],
            "attempt": failed["attempt"], "raw_target": row["raw_target"], "delivery_target": row["target"],
            "failed_event_sha256": ledger._canonical_sha256(failed),
            "original_authorization_sha256": ledger._canonical_sha256(context["authorization"]),
            "provider_original_metadata_sha256": ledger._file_sha256(context["metadata_path"]),
            "provider_original": failed["provider_original"], "source_sha256": failed["source_sha256"],
            "saved_raw_sha256": save["saved_raw_sha256"], "accepted_source_size": accepted_source_size,
            "recovery_metadata": production._artifact_reference(save["provider_original_metadata"], batch),
            "recovery_metadata_sha256": ledger._file_sha256(Path(save["provider_original_metadata"])),
            "local_recovery_confirmed": True, "api_called": False, "request_delta": 0,
        }
        if accepted_source_width_tolerance:
            event["accepted_source_width_tolerance"] = accepted_source_width_tolerance
        # Validate before the sole ledger write; a local crash can reuse the new
        # normalized raw plus its independent sidecar without another API call.
        ledger._account_attempts(batch, context["rows"], context["events"] + [event],
                                 context["job"], context["license"])
        for filename, expected in context["snapshots"].items():
            if ledger._file_sha256(Path(filename)) != expected:
                _fail("本地保存期间原证据已变化；保留新图但禁止追加恢复事件")
        production.append_event(context["events_path"], event, threading.Lock())
        plan = ledger.build_resume_plan(batch, job_file, license_file)
        return {"status": "provider_source_recovered", "api_called": False,
                "requests_used": plan["requests_used"], "generation_target_id": target_id,
                "raw_target": str(raw), "saved_raw_sha256": save["saved_raw_sha256"],
                "counts": plan["counts"], "resume_plan_sha256": plan["resume_plan_sha256"]}
    finally:
        if lock.is_file() and lock.read_bytes() == owned_lock:
            data = ledger._load_json(lock, "本地恢复生产锁")
            if data.get("pid") == os.getpid() and data.get("job_id") == context["job"]["job_id"]:
                lock.unlink()


__all__ = ["recover_provider_source"]
