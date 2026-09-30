"""Create a clean distributable ZIP after offline validation."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DESTINATION = ROOT.parent / "road_rescue_image_factory.zip"
EXCLUDED_PARTS = {
    "__pycache__", ".git", ".DS_Store", ".runtime", ".venv", "node_modules",
    "dist", "release", "release-v2", "output",
}
EXCLUDED_NAMES = {"generation_status.jsonl", ".env"}
IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".avif", ".heic", ".heif", ".ico",
}
ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar", ".tar", ".gz"}


def main() -> None:
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "self_check.py")], check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
    destination = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_DESTINATION.resolve()
    if destination.exists():
        destination.unlink()

    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts) or path.name in EXCLUDED_NAMES:
            continue
        # The system package must not contain generated/reference images or nested archives.
        if path.suffix.lower() in IMAGE_SUFFIXES or path.suffix.lower() in ARCHIVE_SUFFIXES:
            continue
        files.append(path)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            relative = path.relative_to(ROOT)
            archive.write(path, Path(ROOT.name) / relative)
    print(f"PACKAGE_OK files={len(files)} destination={destination}")


if __name__ == "__main__":
    main()
