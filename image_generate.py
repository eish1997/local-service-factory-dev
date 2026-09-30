"""Generate images from the JSONL prompt manifest. Dry-run is the default."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urljoin, urlparse

from tools import image_download_receipts
from tools.image_download_receipts import ReturnedImageDownloadError, is_returned_image_download_error


ROOT = Path(__file__).resolve().parent
ACTIVE_JOB_PATH: Path | None = None


def update_job(path: Path | None, **changes: Any) -> None:
    if path is None:
        return
    current = load_json(path) if path.is_file() else {}
    current.update(changes)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_project_env() -> bool:
    from tools.runtime_paths import data_root
    path = (data_root() if os.environ.get('FACTORY_DATA_HOME') else ROOT) / ".env"
    if not path.is_file():
        return False
    source=path.read_text(encoding="utf-8-sig")
    if 'FACTORY_KEY_POOL_MANAGED=1' in source:
        for name in list(os.environ):
            if name in {'OPENAI_API_KEYS','OPENAI_PROVIDER','OPENAI_BASE_URL','OPENAI_IMAGE_MODEL'} or re.fullmatch(r'OPENAI_API_KEY(?:_\d+)?',name):os.environ.pop(name,None)
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in {"OPENAI_PROVIDER", "OPENAI_BASE_URL", "OPENAI_IMAGE_MODEL", "OPENAI_API_KEYS"} and not re.fullmatch(r"OPENAI_API_KEY(?:_\d+)?", name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value:
            os.environ[name] = value
    return bool(os.environ.get("OPENAI_API_KEY"))


def configured_api_keys() -> list[str]:
    load_project_env()
    keys: list[str] = []
    primary = os.environ.get("OPENAI_API_KEY", "").strip()
    if primary:
        keys.append(primary)
    numbered: list[tuple[int, str]] = []
    for name, value in os.environ.items():
        match = re.fullmatch(r"OPENAI_API_KEY_(\d+)", name)
        if match and value.strip():
            numbered.append((int(match.group(1)), value.strip()))
    for _, value in sorted(numbered):
        if value and value not in keys:
            keys.append(value)
    for value in re.split(r"[\s,;]+", os.environ.get("OPENAI_API_KEYS", "")):
        value = value.strip()
        if value and value not in keys:
            keys.append(value)
    return keys


def apply_provider_config(config: dict[str, Any]) -> dict[str, Any]:
    load_project_env()
    result = dict(config)
    if os.environ.get("OPENAI_IMAGE_MODEL"):
        result["model"] = os.environ["OPENAI_IMAGE_MODEL"]
    result["provider"] = os.environ.get("OPENAI_PROVIDER", "official").strip() or "official"
    if result["provider"] == "relay":
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Relay OPENAI_BASE_URL must be a credential-free https:// URL")
        result["base_url"] = base_url.rstrip("/")
    elif result["provider"] == "official":
        result["base_url"] = ""
    else:
        raise ValueError("OPENAI_PROVIDER must be official or relay")
    return result


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_prompts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Prompt file does not exist: {path}. Run generate_prompts.py first.")
    with path.open("r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    if not records:
        raise ValueError("Prompt file is empty")
    return records


def project_style_suffix() -> str:
    parts: list[str] = []
    for relative in ["preferences/STYLE_PROFILE.md", "preferences/REJECTED_PATTERNS.md"]:
        path = ROOT / relative
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
    if not parts:
        return ""
    return "\n\n以下是用户根据历史样片确认的项目风格要求，优先遵守：\n" + "\n".join(parts)


def append_status(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def consume_execution_license(
    path: Path, pending_count: int, config: dict[str, Any], start: int, end: int
) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError("Execution license does not exist")
    license_data = load_json(path)
    if license_data.get("status") != "active" or not license_data.get("one_time"):
        raise RuntimeError("Execution license is not active")
    if pending_count > int(license_data.get("approved_count", 0)):
        raise RuntimeError(
            f"Pending image count {pending_count} exceeds licensed count {license_data.get('approved_count')}"
        )
    expected = {
        "approved_model": config["model"],
        "approved_quality": config["quality"],
        "approved_size": config["api_size"],
        "approved_base_url": config.get("base_url", ""),
        "approved_provider": config.get("provider", "official"),
    }
    for field, value in expected.items():
        if license_data.get(field) != value:
            raise RuntimeError(f"Execution license {field} does not match current config")
    approved_start = license_data.get("start_index")
    approved_end = license_data.get("end_index")
    if approved_start is not None and start < int(approved_start):
        raise RuntimeError("Requested start is outside the licensed range")
    if approved_end is not None and end > int(approved_end):
        raise RuntimeError("Requested end is outside the licensed range")

    license_data["status"] = "consumed"
    license_data["consumed_for_pending_count"] = pending_count
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(license_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return license_data


_IMAGE_ERROR_STAGES = frozenset({
    "api_generate", "image_decode", "image_download_open", "image_download_read",
    "image_download_checkpoint",
})
_IMAGE_RESPONSE_KINDS = frozenset({"unknown", "base64", "url"})


def safe_stage_metadata(error: Exception) -> dict[str, Any]:
    """Return only bounded diagnostic values, never exception text or URLs."""

    try:
        stage = getattr(error, "error_stage", None)
        elapsed = getattr(error, "elapsed_seconds", None)
        response_kind = getattr(error, "response_kind", None)
        receipt_id = getattr(error, "receipt_id", None)
    except Exception:
        return {}
    if type(stage) is not str or stage not in _IMAGE_ERROR_STAGES:
        return {}
    result: dict[str, Any] = {"error_stage": stage}
    if (type(elapsed) in (int, float) and 0 <= elapsed <= 86400
            and math.isfinite(elapsed)):
        result["elapsed_seconds"] = round(float(elapsed), 3)
    if type(response_kind) is str and response_kind in _IMAGE_RESPONSE_KINDS:
        result["response_kind"] = response_kind
    if type(receipt_id) is str and re.fullmatch(r"[a-f0-9]{64}", receipt_id):
        result["receipt_id"] = receipt_id
    return result


def _mark_stage_error(
    error: Exception, stage: str, started: float, response_kind: str,
) -> None:
    # Keep the original exception class/message/traceback and retry classifier.
    # Diagnostics must never replace the request's real failure.
    try:
        error.error_stage = stage
        error.elapsed_seconds = max(0.0, time.monotonic() - started)
        error.response_kind = response_kind
    except Exception:
        pass


def _uses_extended_image_download_timeout(config: dict[str, Any]) -> bool:
    profile = config.get("generation_profile")
    if not isinstance(profile, dict) or profile.get("id") != "tinysnow-4k-dual-source-v1":
        return False
    from tools.category_generation_profile import config_profile

    try:
        return config_profile(config, "truck_rescue") is not None
    except ValueError:
        return False


def generate_one(client: Any, config: dict[str, Any], prompt: str) -> bytes:
    receipt_context = config.get("_image_download_context")
    if receipt_context is not None:
        image_download_receipts.preflight_context(receipt_context)
        expected = {"model": config["model"], "quality": config["quality"], "api_size": config["api_size"],
                    "effective_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
        if any(receipt_context.get(key) != value for key, value in expected.items()):
            raise ReturnedImageDownloadError() from None
    request: dict[str, Any] = {
        "model": config["model"],
        "prompt": prompt,
        "n": 1,
        "size": config["api_size"],
        "quality": config["quality"],
    }
    # TinySnow's documented OpenAI-compatible endpoint defaults to b64_json and
    # does not document the official SDK's output_format request parameter.
    if config.get("provider") != "relay":
        request["output_format"] = config["output_format"]
    started = time.monotonic()
    try:
        response = client.images.generate(**request)
    except Exception as error:
        _mark_stage_error(error, "api_generate", started, "unknown")
        raise
    started = time.monotonic()
    response_kind = "unknown"
    try:
        image = response.data[0]
        encoded = getattr(image, "b64_json", None)
        if encoded:
            response_kind = "base64"
            return base64.b64decode(encoded)
        image_url = getattr(image, "url", None)
        if not image_url:
            raise RuntimeError("API response did not contain base64 image data or image URL")
    except Exception as error:
        _mark_stage_error(error, "image_decode", started, response_kind)
        raise
    receipt_id = None
    if receipt_context is not None:
        receipt_id = image_download_receipts.save_returned_url(receipt_context, image_url)
    failure = None
    try:
        if _uses_extended_image_download_timeout(config):
            return download_image_url(image_url, timeout=180)
        return download_image_url(image_url)
    except Exception as error:
        # Never retain an underlying URL-bearing exception or chain. A URL
        # response means generation returned: another POST is not a download retry.
        metadata = safe_stage_metadata(error)
        failure = ReturnedImageDownloadError(metadata.get("error_stage", "image_download_open"), receipt_id=receipt_id)
        if "elapsed_seconds" in metadata:
            failure.elapsed_seconds = metadata["elapsed_seconds"]
    raise failure from None


MAX_IMAGE_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_IMAGE_REDIRECTS = 5


class _NoImageRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Returning None causes HTTPError without reading the redirect body.
        return None


def _image_download_opener():
    # Inherit the task's HTTP(S) proxy environment. No auth/cookie handlers are
    # installed and default certificate/hostname verification remains enabled.
    return build_opener(_NoImageRedirects())


def download_image_url(image_url: str, *, timeout: int = 60) -> bytes:
    stage = "image_download_open"
    started = time.monotonic()
    deadline = started + timeout if type(timeout) in (int, float) else started
    failure = None
    try:
        if type(timeout) not in (int, float) or not 0 < timeout <= 180:
            raise ValueError("invalid download wait")
        current_url = image_download_receipts.validate_image_url(image_url)
        opener = _image_download_opener()
        for hop in range(MAX_IMAGE_REDIRECTS + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("download deadline reached")
            request = Request(current_url, method="GET", headers={"User-Agent": "road-rescue-factory/1.0"})
            try:
                response = opener.open(request, timeout=timeout if hop == 0 else min(timeout, remaining))
            except HTTPError as error:
                if error.code not in {301, 302, 303, 307, 308}:
                    error.close()
                    raise
                response = error
            try:
                status = response.getcode()
                if status in {301, 302, 303, 307, 308}:
                    if hop >= MAX_IMAGE_REDIRECTS:
                        raise ValueError("image redirect limit reached")
                    location = response.headers.get("Location", "")
                    current_url = image_download_receipts.validate_image_url(urljoin(current_url, location))
                    if not location:
                        raise ValueError("image redirect has no destination")
                    continue
                if status != 200:
                    raise ValueError("image response is not successful")
                content_type = response.headers.get("Content-Type", "")
                if not content_type.lower().startswith("image/"):
                    raise ValueError("image response has an invalid media type")
                content_length = response.headers.get("Content-Length")
                if content_length is not None and (not str(content_length).isdigit() or int(content_length) > MAX_IMAGE_DOWNLOAD_BYTES):
                    raise ValueError("image response length is invalid")
                stage = "image_download_read"
                started = time.monotonic()
                payload = bytearray()
                reader = getattr(response, "read1", None) or response.read
                while True:
                    if time.monotonic() >= deadline:
                        raise ValueError("download deadline reached")
                    chunk = reader(min(65536, MAX_IMAGE_DOWNLOAD_BYTES + 1 - len(payload)))
                    if not isinstance(chunk, bytes):
                        raise ValueError("invalid image response bytes")
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > MAX_IMAGE_DOWNLOAD_BYTES:
                        raise ValueError("image response exceeds byte limit")
                if not payload:
                    raise ValueError("empty image response")
                if content_length is not None and len(payload) != int(content_length):
                    raise ValueError("incomplete image response")
                return bytes(payload)
            finally:
                response.close()
        raise ValueError("image redirect limit reached")
    except Exception:
        failure = ReturnedImageDownloadError(stage)
        failure.elapsed_seconds = max(0.0, time.monotonic() - started)
    raise failure from None


def main() -> None:
    global ACTIVE_JOB_PATH
    parser = argparse.ArgumentParser(description="Batch-generate road-rescue images with resume support.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually call the API. Without this flag, only print a dry-run plan.",
    )
    parser.add_argument("--start", type=int, help="First prompt index, inclusive")
    parser.add_argument("--end", type=int, help="Last prompt index, inclusive")
    parser.add_argument("--limit", type=int, help="Maximum number of selected prompts (useful for a paid test)")
    parser.add_argument("--license", help="Path to a one-time execution license; required with --execute")
    parser.add_argument("--job-file", help="Background-job progress JSON maintained by this worker")
    args = parser.parse_args()
    ACTIVE_JOB_PATH = Path(args.job_file).resolve() if args.job_file else None
    update_job(ACTIVE_JOB_PATH, status="running", worker_pid=os.getpid())

    config = apply_provider_config(load_json(ROOT / "config.json"))
    prompt_path = ROOT / config["prompt_file"]
    records = load_prompts(prompt_path)
    start = args.start or int(config["start_index"])
    end = args.end or int(config.get("end_index") or records[-1]["index"])
    if start < 1 or end < start:
        raise ValueError("Invalid --start/--end range")
    selected = [record for record in records if start <= int(record["index"]) <= end]
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        selected = selected[: args.limit]

    output_dir = ROOT / config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    overwrite = bool(config.get("overwrite", False))
    pending = [r for r in selected if overwrite or not (output_dir / r["filename"]).exists()]
    print(f"Selected: {len(selected)}; pending: {len(pending)}; already present: {len(selected) - len(pending)}")
    print(f"Model={config['model']} size={config['api_size']} quality={config['quality']} format={config['output_format']}")

    if not args.execute:
        print("DRY RUN: no API request was made. Add --execute to spend credits and generate files.")
        if pending:
            print(f"First pending file: {pending[0]['filename']}")
        return

    if not pending:
        print("Nothing pending. No API request was made and no execution license was consumed.")
        update_job(ACTIVE_JOB_PATH, status="completed", completed=0, failed=0, current_index=None)
        return

    load_project_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY is missing. Run: python factory.py setup-api")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Missing dependency. Run: python -m pip install -r requirements.txt") from exc

    if not args.license:
        raise RuntimeError("Paid execution requires a one-time license created by factory.py authorize")
    license_data = consume_execution_license(Path(args.license).resolve(), len(pending), config, start, end)
    print(f"LICENSE_CONSUMED id={license_data['license_id']} approved={license_data['approved_count']}")

    client_kwargs: dict[str, Any] = {}
    if config.get("base_url"):
        client_kwargs["base_url"] = config["base_url"]
    client = OpenAI(**client_kwargs)
    status_path = output_dir / "generation_status.jsonl"
    style_suffix = project_style_suffix()
    completed = 0
    failed = 0
    for position, record in enumerate(pending, start=1):
        target = output_dir / record["filename"]
        update_job(ACTIVE_JOB_PATH, status="waiting_for_api", current_index=record["index"])
        for attempt in range(1, int(config["max_retries"]) + 1):
            try:
                effective_prompt = record["prompt"] + style_suffix
                image_bytes = generate_one(client, config, effective_prompt)
                temporary = target.with_suffix(target.suffix + ".part")
                temporary.write_bytes(image_bytes)
                temporary.replace(target)
                append_status(
                    status_path,
                    {
                        "index": record["index"],
                        "filename": record["filename"],
                        "status": "ok",
                        "effective_prompt_sha256": hashlib.sha256(effective_prompt.encode("utf-8")).hexdigest(),
                        "license_id": license_data["license_id"],
                    },
                )
                completed += 1
                update_job(
                    ACTIVE_JOB_PATH,
                    status="running",
                    completed=completed,
                    failed=failed,
                    current_index=None,
                    last_saved=str(target),
                )
                print(f"[{position}/{len(pending)}] saved {record['filename']}")
                break
            except Exception as exc:  # API errors vary by SDK version; retry conservatively.
                if attempt >= int(config["max_retries"]):
                    failed += 1
                    update_job(
                        ACTIVE_JOB_PATH,
                        status="running",
                        completed=completed,
                        failed=failed,
                        current_index=None,
                        last_error=str(exc),
                    )
                    append_status(
                        status_path,
                        {"index": record["index"], "filename": record["filename"], "status": "failed", "error": str(exc)},
                    )
                    print(f"[{position}/{len(pending)}] FAILED {record['filename']}: {exc}")
                    break
                delay = float(config["retry_base_seconds"]) * (2 ** (attempt - 1)) + random.random()
                print(f"Retry {record['filename']} in {delay:.1f}s: {exc}")
                time.sleep(delay)
        if position < len(pending):
            time.sleep(float(config["request_interval_seconds"]))

    print(f"Finished. completed={completed}, failed={failed}, skipped={len(selected) - len(pending)}")
    update_job(
        ACTIVE_JOB_PATH,
        status="completed" if failed == 0 else "completed_with_errors",
        completed=completed,
        failed=failed,
        current_index=None,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        update_job(
            ACTIVE_JOB_PATH,
            status="failed",
            current_index=None,
            last_error=str(exc),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        raise
