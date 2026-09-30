"""Validate generated storefront text with local OCR when available; otherwise require manual approval."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def validation_path(image: Path) -> Path:
    return image.with_suffix(".validation.json")


def normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text).lower()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def ocr_engine() -> str | None:
    engine = shutil.which("tesseract")
    if engine:
        return engine
    for candidate in [
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
    ]:
        if candidate.is_file():
            return str(candidate)
    return None


def hidden_subprocess_options() -> dict[str, Any]:
    if not hasattr(subprocess, "STARTUPINFO"):
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def run_ocr(engine: str, image: Path, args: list[str]) -> tuple[str, str]:
    result = subprocess.run(
        [engine, str(image), "stdout", *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
        timeout=60, **hidden_subprocess_options(),
    )
    if result.returncode:
        return "", result.stderr.strip() or "OCR failed"
    return result.stdout.strip(), ""


def fallback_ocr_text(engine: str, image: Path) -> str:
    try:
        from PIL import Image, ImageOps
    except Exception:
        return ""

    source = Image.open(image).convert("RGB")
    width, height = source.size
    with tempfile.TemporaryDirectory(prefix="cover_ocr_") as temporary:
        work_dir = Path(temporary)

        sign = source.crop((0, 0, width, int(height * 0.42)))
        sign_path = work_dir / "sign.png"
        sign.save(sign_path)
        sign_text, _ = run_ocr(engine, sign_path, ["-l", "chi_sim+eng", "--psm", "6"])

        bar = source.crop((0, int(height * 0.43), width, int(height * 0.62)))
        mask = Image.new("L", bar.size, 0)
        pixels = bar.load()
        mask_pixels = mask.load()
        for y in range(bar.height):
            for x in range(bar.width):
                r, g, b = pixels[x, y]
                if g > 120 and g > r * 1.25 and g > b * 1.25:
                    mask_pixels[x, y] = 255
        phone_path = work_dir / "phone_mask.png"
        mask.resize((bar.width * 3, bar.height * 3)).save(phone_path)
        phone_text, _ = run_ocr(
            engine, phone_path,
            ["-l", "eng", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789"],
        )

        gray_path = work_dir / "bar_gray.png"
        ImageOps.grayscale(bar).resize((bar.width * 2, bar.height * 2)).save(gray_path)
        bar_text, _ = run_ocr(engine, gray_path, ["-l", "chi_sim+eng", "--psm", "7"])

    return "\n".join(part for part in [sign_text, phone_text, bar_text] if part)


def validate(image: Path, expected: list[str]) -> dict[str, Any]:
    if not image.is_file():
        raise FileNotFoundError(image)
    payload: dict[str, Any] = {
        "image": str(image), "expected": expected, "checked_at": datetime.now(timezone.utc).isoformat(),
        "method": "manual-required", "approved": False,
        "status": "manual_required", "reason": "OCR disabled",
    }
    atomic_json(validation_path(image), payload)
    return payload


def manual_approve(image: Path, expected: list[str], note: str) -> dict[str, Any]:
    if not image.is_file():
        raise FileNotFoundError(image)
    payload = {
        "image": str(image), "expected": expected, "status": "manual_approved", "approved": True,
        "method": "human", "note": note.strip(), "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(validation_path(image), payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--expected", action="append", default=[])
    parser.add_argument("--manual-approve", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    image = Path(args.image).resolve()
    if args.manual_approve:
        if not args.confirm:
            raise RuntimeError("manual approval requires --confirm")
        payload = manual_approve(image, args.expected, args.note)
    else:
        payload = validate(image, args.expected)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
