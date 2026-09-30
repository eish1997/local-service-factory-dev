"""Private, task-bound returned-image URL receipts. No network or credentials.

``root`` is the receipt directory itself (production uses
ROOT/.runtime/image_download_receipts). URLs are never written in plaintext.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import ipaddress
import json
import os
import re
import threading
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_FIELDS = (
    "job_id", "license_id", "generation_target_id", "request_number", "attempt",
    "model", "quality", "api_size", "effective_prompt_sha256", "original_plan_sha256",
)
_STAGES = frozenset({
    "image_download_checkpoint", "image_download_open", "image_download_read",
})
MAX_URL_LENGTH = 16384
MAX_RECEIPT_BYTES = 131072
_RECEIPT_LOCK = threading.RLock()


def _receipt_operation(function):
    @wraps(function)
    def locked(*args, **kwargs):
        # API/GET work is outside this lock. It only prevents other threads in
        # the same licensed worker observing half-written exclusive claims.
        with _RECEIPT_LOCK:
            return function(*args, **kwargs)
    return locked


class ReturnedImageDownloadError(RuntimeError):
    """A returned image must never cause another paid generation attempt."""

    error_kind = "image_download_failed"
    retry_forbidden = True
    response_kind = "url"

    def __init__(self, stage: str = "image_download_checkpoint", *, receipt_id: str | None = None):
        super().__init__("Returned image requires local download recovery; do not repeat image generation")
        self.error_stage = stage if stage in _STAGES else "image_download_checkpoint"
        if type(receipt_id) is str and _SHA.fullmatch(receipt_id):
            self.receipt_id = receipt_id


def is_returned_image_download_error(error: Exception) -> bool:
    return isinstance(error, ReturnedImageDownloadError)


def validate_image_url(value: Any) -> str:
    """Validate each hop without including the value in any exception."""
    valid = False
    try:
        if type(value) is str and 0 < len(value) <= MAX_URL_LENGTH and not any(ord(c) <= 32 or ord(c) == 127 for c in value):
            parsed = urlparse(value)
            hostname = parsed.hostname or ""
            valid = (parsed.scheme == "https" and bool(hostname) and not parsed.username
                     and not parsed.password and not parsed.fragment and "\\" not in value
                     and (parsed.port is None or 1 <= parsed.port <= 65535))
            if valid:
                ascii_host = hostname.encode("idna").decode("ascii").lower().rstrip(".")
                try:
                    valid = ipaddress.ip_address(ascii_host).is_global
                except ValueError:
                    valid = (ascii_host != "localhost" and not ascii_host.endswith(".localhost")
                             and len(ascii_host) <= 253
                             and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                     for label in ascii_host.split(".")))
    except Exception:
        valid = False
    if not valid:
        raise ReturnedImageDownloadError("image_download_open") from None
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _binding(context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(context, dict) or set(context) != {"root", *_FIELDS}:
        raise ValueError("invalid receipt context")
    binding = {key: context[key] for key in _FIELDS}
    for key in ("job_id", "license_id"):
        if type(binding[key]) is not str or not _ID.fullmatch(binding[key]):
            raise ValueError("invalid receipt identity")
    for key in ("effective_prompt_sha256", "original_plan_sha256"):
        if type(binding[key]) is not str or not _SHA.fullmatch(binding[key]):
            raise ValueError("invalid receipt hash")
    if type(binding["generation_target_id"]) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_:.-]{0,199}", binding["generation_target_id"]):
        raise ValueError("invalid receipt target")
    for key in ("model", "quality", "api_size"):
        if type(binding[key]) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}", binding[key]):
            raise ValueError("invalid receipt generation")
    if type(binding["request_number"]) is not int or not 1 <= binding["request_number"] <= 999999999:
        raise ValueError("invalid receipt request number")
    if type(binding["attempt"]) is not int or not 1 <= binding["attempt"] <= 1000000:
        raise ValueError("invalid receipt attempt")
    return binding


def _job_dir(root: str | Path, job_id: str) -> Path:
    if type(job_id) is not str or not _ID.fullmatch(job_id):
        raise ValueError("invalid receipt job")
    base = Path(root)
    if not base.is_absolute():
        raise ValueError("receipt root must be absolute")
    base = base.resolve()
    directory = (base / job_id).resolve()
    if directory.parent != base:
        raise ValueError("receipt directory escapes root")
    return directory


def _path(context: dict[str, Any]) -> Path:
    binding = _binding(context)
    directory = _job_dir(context["root"], binding["job_id"])
    path = directory / f"{binding['request_number']:08d}.json"
    if path.resolve().parent != directory or path.is_symlink():
        raise ValueError("invalid receipt path")
    return path


def receipt_id_for_context(context: dict[str, Any]) -> str:
    failed = False
    try:
        return hashlib.sha256(_canonical(_binding(context))).hexdigest()
    except Exception:
        failed = True
    if failed:
        raise ReturnedImageDownloadError() from None


def _dpapi(data: bytes, entropy: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("Windows CurrentUser DPAPI unavailable")
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(value):
        buffer = ctypes.create_string_buffer(value)
        return DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    source, source_buffer = blob(data)
    extra, entropy_buffer = blob(entropy)
    output = DATA_BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    # UI_FORBIDDEN=1; deliberately omit LOCAL_MACHINE=4 (CurrentUser scope).
    if not operation(ctypes.byref(source), None, ctypes.byref(extra), None, None, 1, ctypes.byref(output)):
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def preflight_receipt_support() -> None:
    """In-memory current-user encryption round trip; no filesystem/network."""
    failed = False
    try:
        marker, entropy = b"image-download-receipt-preflight-v1", b"image-download-receipts"
        if _dpapi(_dpapi(marker, entropy, decrypt=False), entropy, decrypt=True) != marker:
            raise ValueError("receipt encryption round trip failed")
    except Exception:
        failed = True
    if failed:
        raise ReturnedImageDownloadError() from None


def preflight_context(context: dict[str, Any]) -> None:
    """Validate one future request and create only its private job directory."""
    preflight_receipt_support()
    failed = False
    try:
        path = _path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.with_suffix(".claim").exists():
            raise ValueError("receipt request already exists")
        assert_no_pending_for_target(context["root"], context["job_id"], context["generation_target_id"])
    except Exception:
        failed = True
    if failed:
        raise ReturnedImageDownloadError() from None


def _document(binding: dict[str, Any], url: str, state: str, raw_sha256: str | None = None) -> dict[str, Any]:
    receipt_id = hashlib.sha256(_canonical(binding)).hexdigest()
    payload = {"binding": binding, "image_url": url, "state": state, "raw_sha256": raw_sha256}
    encrypted = _dpapi(_canonical(payload), bytes.fromhex(receipt_id), decrypt=False)
    return {"schema_version": 1, "receipt_id": receipt_id, "binding": binding, "state": state,
            "raw_sha256": raw_sha256, "protected_payload": base64.b64encode(encrypted).decode("ascii")}


def _load_document(path: Path, expected_binding: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= MAX_RECEIPT_BYTES:
        raise ValueError("invalid receipt file")
    document = json.loads(path.read_bytes())
    if set(document) != {"schema_version", "receipt_id", "binding", "state", "raw_sha256", "protected_payload"} or document["schema_version"] != 1:
        raise ValueError("invalid receipt schema")
    binding = _binding({"root": str(path.parent.parent), **document["binding"]})
    receipt_id = hashlib.sha256(_canonical(binding)).hexdigest()
    if document["receipt_id"] != receipt_id or (expected_binding is not None and binding != expected_binding):
        raise ValueError("receipt binding mismatch")
    if path.name != f"{binding['request_number']:08d}.json" or path.parent.name != binding["job_id"]:
        raise ValueError("receipt file binding mismatch")
    decoded = _dpapi(base64.b64decode(document["protected_payload"], validate=True), bytes.fromhex(receipt_id), decrypt=True)
    payload = json.loads(decoded)
    if (set(payload) != {"binding", "image_url", "state", "raw_sha256"}
            or payload["binding"] != binding or payload["state"] != document["state"]
            or payload["raw_sha256"] != document["raw_sha256"]
            or document["state"] not in {"pending", "materialized"}):
        raise ValueError("receipt protected metadata mismatch")
    if document["state"] == "pending" and document["raw_sha256"] is not None:
        raise ValueError("pending receipt contains materialization evidence")
    if document["state"] == "materialized" and (type(document["raw_sha256"]) is not str or not _SHA.fullmatch(document["raw_sha256"])):
        raise ValueError("materialized receipt lacks raw hash")
    return document, validate_image_url(payload["image_url"])


def _claim(path: Path, binding: dict[str, Any]) -> Path:
    claim = path.with_suffix(".claim")
    with os.fdopen(os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as handle:
        handle.write(_canonical({"schema_version": 1, "binding": binding}) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return claim


def _write_atomic(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as handle:
        handle.write(_canonical(document) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@_receipt_operation
def save_returned_url(context: dict[str, Any], image_url: str) -> str:
    """Persist encrypted URL before the first GET; never overwrite a receipt."""
    failed = False
    receipt_id = None
    try:
        preflight_context(context)
        binding = _binding(context)
        receipt_id = hashlib.sha256(_canonical(binding)).hexdigest()
        path = _path(context)
        claim = _claim(path, binding)
        if path.exists():
            raise ValueError("receipt collision")
        url = validate_image_url(image_url)
        _write_atomic(path, _document(binding, url, "pending"))
        claim.unlink()
        return receipt_id
    except Exception:
        # Preserve an incomplete claim on failure so another job cannot POST.
        failed = True
    if failed:
        raise ReturnedImageDownloadError(receipt_id=receipt_id) from None


def load_pending_url(context: dict[str, Any]) -> str:
    """Explicit local recovery only; this function never performs a GET/POST."""
    failed = False
    try:
        document, url = _load_document(_path(context), _binding(context))
        if document["state"] != "pending":
            raise ValueError("receipt is not pending")
        return url
    except Exception:
        failed = True
    if failed:
        raise ReturnedImageDownloadError() from None


@_receipt_operation
def mark_materialized(context: dict[str, Any], raw_sha256: str) -> bool:
    """Only call after raw preservation and generated evidence are durable."""
    failed = False
    try:
        path = _path(context)
        if not path.exists() and not path.with_suffix(".claim").exists():
            return False  # Base64/mock responses have no URL receipt.
        if type(raw_sha256) is not str or not _SHA.fullmatch(raw_sha256):
            raise ValueError("invalid materialized raw hash")
        document, url = _load_document(path, _binding(context))
        if document["state"] == "materialized":
            if document["raw_sha256"] != raw_sha256:
                raise ValueError("materialized hash mismatch")
            return True
        claim = _claim(path, document["binding"])
        _write_atomic(path, _document(document["binding"], url, "materialized", raw_sha256))
        claim.unlink()
        return True
    except Exception:
        failed = True
    if failed:
        raise ReturnedImageDownloadError() from None


@_receipt_operation
def assert_no_pending_for_job(root: str | Path, job_id: str) -> None:
    """Read-only gate: pending, corrupt and interrupted checkpoints all block."""
    failed = False
    try:
        directory = _job_dir(root, job_id)
        if not directory.exists():
            return
        for path in directory.iterdir():
            if path.suffix != ".json":
                raise ValueError("incomplete receipt checkpoint")
            document, _ = _load_document(path)
            if document["state"] != "materialized":
                raise ValueError("pending returned image")
        return
    except Exception:
        failed = True
    if failed:
        raise ReturnedImageDownloadError() from None


@_receipt_operation
def assert_no_pending_for_target(root: str | Path, job_id: str, generation_target_id: str) -> None:
    """Block a duplicate POST without blocking unrelated concurrent targets."""
    failed = False
    try:
        if type(generation_target_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_:.-]{0,199}", generation_target_id):
            raise ValueError("invalid receipt target")
        directory = _job_dir(root, job_id)
        if not directory.exists():
            return
        for path in directory.iterdir():
            if path.suffix == ".json":
                document, _ = _load_document(path)
                if document["state"] == "materialized":
                    continue
                binding = document["binding"]
            else:
                # Interrupted atomic writes retain a safe, URL-free binding in
                # their exclusive claim. Unknown/corrupt artifacts fail closed.
                stem = path.name.split(".", 1)[0]
                if not re.fullmatch(r"[0-9]{8,9}", stem) or path.suffix not in {".claim", ".tmp"}:
                    raise ValueError("unrecognized receipt checkpoint")
                claim = directory / (stem + ".claim")
                try:
                    if claim.is_symlink():
                        raise ValueError("invalid receipt claim")
                    with claim.open("rb") as handle:
                        claim_bytes = handle.read(MAX_RECEIPT_BYTES + 1)
                except FileNotFoundError:
                    # A concurrent request can atomically publish its JSON and
                    # remove its claim after iterdir yielded a stale path. Check
                    # that exact final receipt once, including DPAPI integrity;
                    # never ignore a disappeared/unknown artifact without proof.
                    document, _ = _load_document(directory / (stem + ".json"))
                    if document["state"] == "materialized":
                        continue
                    if document["binding"]["generation_target_id"] == generation_target_id:
                        raise ValueError("target has an unresolved returned image")
                    continue
                if not 0 < len(claim_bytes) <= MAX_RECEIPT_BYTES:
                    raise ValueError("invalid receipt claim")
                value = json.loads(claim_bytes)
                if set(value) != {"schema_version", "binding"} or value["schema_version"] != 1:
                    raise ValueError("invalid receipt claim schema")
                binding = _binding({"root": str(root), **value["binding"]})
                if binding["job_id"] != job_id or f"{binding['request_number']:08d}" != stem:
                    raise ValueError("receipt claim identity mismatch")
            if binding["generation_target_id"] == generation_target_id:
                raise ValueError("target has an unresolved returned image")
        return
    except Exception:
        failed = True
    if failed:
        raise ReturnedImageDownloadError() from None
