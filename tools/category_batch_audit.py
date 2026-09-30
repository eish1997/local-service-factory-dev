"""Mock-only audit for category prompt batches; deliberately does not inspect images."""

from __future__ import annotations

import csv
import json
import random
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from tools.prompt_engine import CATEGORY_BATCH_ROOT, CategoryPromptError, load_category_config, scene_matches_legal_combination


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise CategoryPromptError(f"缺少必要文件：{path.name}")
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    except json.JSONDecodeError as error:
        raise CategoryPromptError(f"{path.name} 不是有效的 JSONL：第 {error.lineno} 行") from error


def _safe_batch_dir(category_id: str, value: str) -> Path:
    candidate = Path(value).expanduser().resolve()
    allowed_root = (CATEGORY_BATCH_ROOT / category_id).resolve()
    if candidate != allowed_root and allowed_root not in candidate.parents:
        raise CategoryPromptError("--batch-dir 必须位于 prompts/category_batches/pipe_unclogging/ 内")
    if not candidate.is_dir():
        raise CategoryPromptError(f"找不到批次目录：{candidate}")
    return candidate


def _write_simple_xlsx(path: Path, rows: list[list[str]]) -> None:
    sheet_rows = []
    for row_number, row in enumerate(rows, 1):
        cells = "".join(
            f'<c r="{chr(65 + column)}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            for column, value in enumerate(row)
        )
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="mock审核记录" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(sheet_rows) + "</sheetData></worksheet>",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, contents in files.items():
            archive.writestr(filename, contents)


def audit_batch(category_id: str, batch_dir_value: str, mode: str) -> dict[str, Any]:
    if mode != "mock":
        raise CategoryPromptError("第一阶段只支持 --mode mock；未接入真实视觉模型")
    config = load_category_config(category_id)
    batch_dir = _safe_batch_dir(category_id, batch_dir_value)
    prompts = _read_jsonl(batch_dir / "prompts.jsonl")
    manifest = _read_jsonl(batch_dir / "manifest.jsonl")
    if len(prompts) != len(manifest):
        raise CategoryPromptError("prompts.jsonl 与 manifest.jsonl 的数量不一致")
    forbidden = config["negative_prompt"]
    rows: list[dict[str, Any]] = []
    for prompt, item in zip(prompts, manifest):
        violations = [word for word in forbidden if word in prompt.get("positive_prompt", "")]
        missing = [field for field in ("index", "role", "positive_prompt", "negative_prompt", "scene") if not prompt.get(field)]
        if violations:
            status, reason = "rejected", "正向提示词出现禁止元素：" + "、".join(violations)
        elif missing:
            status, reason = "needs_review", "缺少必要字段：" + "、".join(missing)
        elif prompt.get("category_id") != category_id or item.get("category_id") != category_id:
            status, reason = "needs_review", "类目 ID 不一致"
        elif not scene_matches_legal_combination(config, prompt.get("role", ""), prompt.get("scene", {})):
            status, reason = "rejected", "地点、客户问题、管道、动作或工具不属于同一合法业务组合"
        else:
            status, reason = "approved", "mock 默认通过；未读取图片，需在真实生图后人工复核"
        rows.append({"index": prompt.get("index"), "group_index": prompt.get("group_index"), "role": prompt.get("role"), "status": status, "reason": reason, "image_path": item.get("image_path")})
    candidates = [row for row in rows if row["status"] == "approved"]
    review_count = max(1, round(len(candidates) * 0.1)) if candidates else 0
    for row in random.SystemRandom().sample(candidates, review_count):
        row["status"] = "needs_review"
        row["reason"] = "mock 随机抽检清单；无图片，人工生图后必看"
    counts = {status: sum(row["status"] == status for row in rows) for status in ("approved", "needs_review", "retry", "rejected")}
    report = {"schema_version": 1, "category_id": category_id, "mode": "mock", "image_files_inspected": 0, "image_files_created": 0, "record_count": len(rows), "status_counts": counts, "generated_at": datetime.now(timezone.utc).isoformat(), "records": rows}
    (batch_dir / "audit_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (batch_dir / "audit_report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["index", "group_index", "role", "status", "reason", "image_path"])
        writer.writeheader()
        writer.writerows(rows)
    readable = (
        "管道疏通批次 mock 审核完成\n"
        f"审核记录：{len(rows)} 条\n"
        f"approved：{counts['approved']}；needs_review：{counts['needs_review']}；retry：{counts['retry']}；rejected：{counts['rejected']}\n"
        "说明：本阶段没有真实图片，因此没有读取或伪造图片文件；needs_review 是后续真实生图后的人工抽检清单。\n"
    )
    (batch_dir / "audit_report_readable.txt").write_text(readable, encoding="utf-8", newline="\n")
    _write_simple_xlsx(batch_dir / "review_log.xlsx", [["编号", "组号", "角色", "状态", "原因", "图片路径"], *[[str(row.get(key) or "") for key in ("index", "group_index", "role", "status", "reason", "image_path")] for row in rows]])
    queue = batch_dir / "review_queue"
    queue.mkdir(exist_ok=True)
    (queue / "README.txt").write_text("此目录只放 mock 审核清单；第一阶段未生成图片，因此没有图片文件。真实生图后请把需要人工查看的图片及其清单放入此处。\n", encoding="utf-8")
    return {"batch_dir": batch_dir, "report": report}
