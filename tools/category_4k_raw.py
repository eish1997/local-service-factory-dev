"""Narrow, explicitly authorized 4K relay response adapter for legacy delivery.

The provider bytes are preserved, never enlarged or silently accepted as 4K.
Only portrait near-2:3 responses with a 3840/4096-pixel long edge may produce
the existing 1024x1536 working raw by default. A separately authorized exact
2352x3520 source contract is opt-in. A further explicit width-tolerance flag
accepts exactly 2336x3520 or 2352x3520, not the intervening widths. Neither
contract claims that its source is true 4K.
Ordinary production keeps its old gate.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageOps

from tools import category_image_production as production


RAW_CONTRACT = "tinysnow_4k_to_legacy_v1"
ACCEPTED_SOURCE_CONTRACT = "tinysnow_2352x3520_to_legacy_v1"
WIDTH_TOLERANCE_SOURCE_CONTRACT = "tinysnow_2336_2352x3520_to_legacy_v1"
DECODABLE_SOURCE_POLICY = "provider_decodable_size_to_legacy_v1"
HD_DELIVERY_SOURCE_POLICY = "provider_hd_delivery_to_legacy_v1"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000
MAX_SOURCE_DIMENSION = 16384


def prepare_source_size_raw(payload: bytes, *, anchor_y: float = 0.5,
                            source_size_policy: str = DECODABLE_SOURCE_POLICY) -> tuple[bytes, dict[str, Any]]:
    """Decode within safety limits; truthfully report any working-image enlargement."""
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_SOURCE_BYTES:
        raise production.RawImageContractError("源图为空或超过64MiB解码安全上限")
    if not 0.0 <= anchor_y <= 1.0:
        raise ValueError("anchor_y must be between 0 and 1")
    if source_size_policy not in {DECODABLE_SOURCE_POLICY, HD_DELIVERY_SOURCE_POLICY}:
        raise ValueError("unknown source-size policy")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            width, height = source.size
            if (not 0 < width <= MAX_SOURCE_DIMENSION or not 0 < height <= MAX_SOURCE_DIMENSION
                    or width * height > MAX_SOURCE_PIXELS):
                raise ValueError("source exceeds pixel safety limit")
            if source_size_policy == HD_DELIVERY_SOURCE_POLICY and (
                    width < 1000 or height < 1400 or not 0.6 <= width / height <= 0.75):
                raise production.RawImageContractError("源图未达到成品高清门槛：至少1000x1400且为接近2:3的竖图")
            source.load()
            image = source.convert("RGB")
            source_format = source.format
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise production.RawImageContractError("源图不完整、不可解码或超过像素安全上限") from error
    result = {
        "raw_contract": source_size_policy, "source_size_policy": source_size_policy,
        "source_returned_size": f"{width}x{height}", "source_format": source_format,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "source_is_upscaled_by_factory": False,
        "working_raw_is_upscaled": max(1024 / width, 1536 / height) > 1,
        "normalized": True, "normalization_mode": (
            "accepted_hd_delivery_lanczos_fit_legacy" if source_size_policy == HD_DELIVERY_SOURCE_POLICY
            else "accepted_decodable_lanczos_fit_legacy"),
        "normalized_to": "1024x1536", "normalization_anchor_y": anchor_y,
        "archive_status": "normalized",
    }
    # Fit through a source crop box, never scale the whole extreme-aspect source
    # first: a 1x16384 image must not allocate a multi-billion-pixel intermediate.
    image = ImageOps.fit(image, production.RAW_API_SIZE, method=Image.Resampling.LANCZOS,
                         centering=(0.5, anchor_y))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    raw_bytes = output.getvalue()
    result["saved_raw_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    return raw_bytes, result


def publish_immutable_bytes(path: Path, payload: bytes) -> None:
    """Atomic, no-overwrite publication on the same filesystem; identical is idempotent."""
    path = production._io_path(Path(path))
    if path.is_symlink():
        raise production.RawImageContractError("不可写入符号链接")
    if production._io_path(path).exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise production.RawImageContractError("已有文件不匹配，禁止覆盖")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = production._io_path(path.with_name(f".{path.name}.{uuid4().hex}.tmp"))
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Unlike replace(), link() cannot overwrite a file arriving concurrently.
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != payload:
                raise production.RawImageContractError("并发文件冲突，禁止覆盖") from None
    finally:
        temporary.unlink(missing_ok=True)


def save_4k_raw_png(
    path: Path,
    payload: bytes,
    *,
    archive_root: Path,
    generation: dict[str, Any],
    credential_epoch: str | None,
    anchor_y: float = 0.5,
    accepted_source_size: str | None = None,
    accepted_source_width_tolerance: int = 0,
    source_size_policy: str | None = None,
) -> dict[str, Any]:
    """Archive a response and downsample only the explicitly selected shape."""

    if generation.get("model") != "gpt-image-2-4k":
        raise production.RawImageContractError("4K响应适配只允许已绑定的 gpt-image-2-4k")
    if accepted_source_size not in (None, "2352x3520"):
        raise production.RawImageContractError("显式原图尺寸契约只支持2352x3520")
    if (
        type(accepted_source_width_tolerance) is not int
        or accepted_source_width_tolerance not in (0, 16)
        or (accepted_source_width_tolerance == 16 and accepted_source_size != "2352x3520")
    ):
        raise production.RawImageContractError("源图宽度容差仅支持2352x3520契约下显式指定16")
    raw_contract = (
        WIDTH_TOLERANCE_SOURCE_CONTRACT if accepted_source_width_tolerance == 16
        else ACCEPTED_SOURCE_CONTRACT if accepted_source_size else RAW_CONTRACT
    )
    if not 0.0 <= anchor_y <= 1.0:
        raise ValueError("anchor_y must be between 0 and 1")
    if production._io_path(path).exists():
        raise production.RawImageContractError("4K响应适配不能覆盖已有原图")
    if source_size_policy is not None:
        if source_size_policy not in {DECODABLE_SOURCE_POLICY, HD_DELIVERY_SOURCE_POLICY}:
            raise production.RawImageContractError("未知的任务级源尺寸接受策略")
        if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_SOURCE_BYTES:
            raise production.RawImageContractError("源图为空或超过64MiB归档安全上限")
        try:
            raw_bytes, result = prepare_source_size_raw(payload, anchor_y=anchor_y, source_size_policy=source_size_policy)
        except production.RawImageContractError:
            # A paid, byte-bounded response remains recoverable even when decode
            # or pixel safety fails. Never load unsafe pixels just to archive it.
            dimensions, source_format = (0, 0), None
            try:
                with Image.open(io.BytesIO(payload)) as header:
                    dimensions, source_format = header.size, header.format
            except (OSError, ValueError, Image.DecompressionBombError):
                pass
            archive = production._archive_provider_payload(archive_root, path, payload, source_format, dimensions)
            sidecar = archive.with_name(archive.name + "." + source_size_policy + ".rejected.json")
            rejected = {
                "raw_contract": source_size_policy, "source_size_policy": source_size_policy,
                "source_returned_size": f"{dimensions[0]}x{dimensions[1]}", "source_format": source_format,
                "source_sha256": hashlib.sha256(payload).hexdigest(), "provider_original": str(archive),
                "provider_original_metadata": str(sidecar), "archive_status": "rejected", "normalized": False,
                "model": generation["model"], "quality": generation.get("quality"), "api_size": generation.get("api_size"),
                "source_is_upscaled_by_factory": False, "rejection_reason": (
                    "source decoding, pixel safety or delivery HD limits" if source_size_policy == HD_DELIVERY_SOURCE_POLICY
                    else "source decoding or pixel safety limit"),
            }
            import json
            publish_immutable_bytes(sidecar, (json.dumps(rejected, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
            raise production.RawImageContractError("源图未通过所选尺寸/解码安全门槛，已保全原始响应", evidence=rejected) from None
        dimensions = tuple(int(value) for value in result["source_returned_size"].split("x"))
        archive = production._archive_provider_payload(archive_root, path, payload, result["source_format"], dimensions)
        original_metadata = archive.with_name(archive.name + ".json")
        sidecar = archive.with_name(archive.name + "." + source_size_policy + ".json")
        result.update(provider_original=str(archive), provider_original_metadata=str(sidecar),
                      model=generation["model"], quality=generation.get("quality"), api_size=generation.get("api_size"))
        if production._io_path(original_metadata).exists():
            result["prior_provider_original_metadata"] = str(original_metadata)
        if credential_epoch is not None:
            result["credential_epoch"] = credential_epoch
        import json
        publish_immutable_bytes(sidecar, (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        publish_immutable_bytes(path, raw_bytes)
        return result
    source_size = (0, 0)
    source_format = None
    decode_error = False
    image = None
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source_size, source_format = source.size, source.format
            # Reject before decoding unexpectedly large or non-portrait data.
            size_allowed = (
                source_size in {(2336, 3520), (2352, 3520)}
                if accepted_source_width_tolerance == 16 else
                source_size == (2352, 3520) if accepted_source_size else
                source_size[1] in {3840, 4096}
                and abs(source_size[0] / source_size[1] - 2 / 3) <= 0.005
            )
            if size_allowed:
                source.load()
                image = source.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        decode_error = True
    archive = production._archive_provider_payload(
        archive_root, path, payload, source_format, source_size,
    )
    sidecar = archive.with_name(archive.name + ".json")
    previous_sidecar = sidecar if production._io_path(sidecar).exists() else None
    if previous_sidecar is not None:
        # Recovery may accept a previously rejected source under a new bound
        # contract. Preserve its old rejection evidence instead of rewriting it.
        sidecar = archive.with_name(f"{archive.name}.{raw_contract}.{uuid4().hex}.json")
    result: dict[str, Any] = {
        "raw_contract": raw_contract,
        "source_returned_size": f"{source_size[0]}x{source_size[1]}",
        "source_format": source_format,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "provider_original": str(archive),
        "provider_original_metadata": str(sidecar),
        "normalized": False,
        "normalization_mode": "none",
        "normalized_to": "1024x1536",
        "normalization_anchor_y": anchor_y,
        "model": generation["model"],
        "quality": generation.get("quality"),
        "api_size": generation.get("api_size"),
        "source_is_upscaled_by_factory": False,
    }
    if credential_epoch is not None:
        result["credential_epoch"] = credential_epoch
    if accepted_source_size is not None:
        result["accepted_source_size"] = accepted_source_size
    if accepted_source_width_tolerance:
        result["accepted_source_width_tolerance"] = accepted_source_width_tolerance
    if previous_sidecar is not None:
        result["prior_provider_original_metadata"] = str(previous_sidecar)
    if decode_error or image is None:
        reason = (
            "provider response is not a decodable image"
            if decode_error else (
                "expected exact source pixels 2336x3520 or 2352x3520"
                if accepted_source_width_tolerance == 16 else
                "expected exact source pixels 2352x3520" if accepted_source_size else
                "expected portrait near-2:3 pixels with long edge 3840 or 4096"
            )
        )
        result.update(archive_status="rejected", rejection_reason=reason)
        production.atomic_json(sidecar, result)
        raise production.RawImageContractError(
            f"4K响应尺寸/解码不符合已绑定契约：{reason}", evidence=result,
        )
    image = production._fit_image(image, production.RAW_API_SIZE, anchor_y=anchor_y)
    production._io_path(path.parent).mkdir(parents=True, exist_ok=True)
    temporary = production._io_path(path.with_suffix(path.suffix + ".part"))
    image.save(temporary, format="PNG", optimize=True)
    temporary.replace(production._io_path(path))
    if not production.valid_png(path, production.RAW_API_SIZE):
        raise production.RawImageContractError("4K工作原图未通过PNG完整性验证", evidence=result)
    result.update(
        normalized=True,
        normalization_mode=(
            "accepted_source_lanczos_downsample_legacy" if accepted_source_size
            else "4k_lanczos_downsample_legacy"
        ),
        archive_status="normalized",
        saved_raw_sha256=production._file_sha256(path),
    )
    production.atomic_json(sidecar, result)
    return result
