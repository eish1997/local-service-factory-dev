"""Audit every prompt for coverage, uniqueness, and scene compatibility. Offline only."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    library = json.loads((ROOT / "scene_library.json").read_text(encoding="utf-8"))
    prompt_path = ROOT / config["prompt_file"]
    records = [json.loads(line) for line in prompt_path.read_text(encoding="utf-8").splitlines() if line]
    errors: list[str] = []
    registry_path = ROOT / config.get("batch_registry", "prompts/batch_registry.json")
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else None
    expected_count = int(registry["total_prompts"]) if registry else int(config["prompt_count"])

    if len(records) != expected_count:
        errors.append(f"count expected={expected_count} actual={len(records)}")
    if len({r["prompt"] for r in records}) != len(records):
        errors.append("duplicate complete prompts")
    if len({r["prompt_sha256"] for r in records}) != len(records):
        errors.append("duplicate prompt hashes across history")

    if registry:
        registered_count = sum(int(batch["count"]) for batch in registry["batches"])
        if registered_count != expected_count:
            errors.append(f"batch registry count mismatch: batches={registered_count}, total={expected_count}")
        for batch in registry["batches"]:
            batch_path = ROOT / batch["file"]
            batch_records = [json.loads(line) for line in batch_path.read_text(encoding="utf-8").splitlines() if line]
            if len(batch_records) != int(batch["count"]):
                errors.append(f"batch {batch['batch']} file count mismatch")
            indexes = [record["index"] for record in batch_records]
            if indexes and (indexes[0] != int(batch["start_index"]) or indexes[-1] != int(batch["end_index"])):
                errors.append(f"batch {batch['batch']} index range mismatch")

    for expected_index, record in enumerate(records, start=1):
        scene = record["scene"]
        job = scene["rescue_job"]
        location_group = scene["location_group"]
        weather_group = scene["weather_group"]
        rule = library["job_rules"][job]
        prefix = f"#{record['index']:04d}"

        if record["index"] != expected_index:
            errors.append(f"{prefix} non-continuous index")
        expected_filename = config["filename_pattern"].format(index=record["index"])
        if record["filename"] != expected_filename:
            errors.append(f"{prefix} invalid filename")
        actual_hash = hashlib.sha256(record["prompt"].encode("utf-8")).hexdigest()
        if record["prompt_sha256"] != actual_hash:
            errors.append(f"{prefix} invalid prompt hash")
        if location_group not in rule["location_groups"]:
            errors.append(f"{prefix} job/location conflict: {job}/{location_group}")
        if location_group != "garage" and weather_group not in rule["weather_groups"]:
            errors.append(f"{prefix} job/weather conflict: {job}/{weather_group}")
        if scene["location"] not in library["location_groups"][location_group]:
            errors.append(f"{prefix} location/group mismatch")
        if location_group == "garage" and "地下车库内不受室外天气影响" not in scene["weather"]:
            errors.append(f"{prefix} garage has outdoor weather")
        if location_group != "garage" and "地下车库内" in scene["weather"]:
            errors.append(f"{prefix} outdoor location has garage weather")
        if location_group == "winter" and weather_group != "winter":
            errors.append(f"{prefix} winter location has non-winter weather")
        if job == "雪地救援" and (weather_group != "winter" or "雪" not in scene["weather"]):
            errors.append(f"{prefix} snow rescue without snow")
        if job == "泥巴脱困" and scene["location"] not in {"泥泞的乡村土路", "乡村碎石土路", "山区盘山公路安全路肩"}:
            errors.append(f"{prefix} mud rescue on implausible surface")
        if job == "地下车库救援" and location_group != "garage":
            errors.append(f"{prefix} garage rescue outside garage")
        if weather_group == "heavy_rain" and "防水雨衣" not in record["prompt"]:
            errors.append(f"{prefix} heavy rain without rainwear")
        if weather_group == "hot" and (location_group == "winter" or "积雪" in record["prompt"]):
            errors.append(f"{prefix} hot/snow conflict")

        allowed_details = set(library["context_details"]["general"])
        allowed_details.update(library["context_details"][location_group])
        if weather_group in library["context_details"]:
            allowed_details.update(library["context_details"][weather_group])
        if weather_group == "winter":
            allowed_details.update(library["context_details"]["snow"])
        if any(token in scene["time"] for token in ["深夜", "凌晨", "路灯"]):
            allowed_details.update(library["context_details"]["night"])
        for detail in scene["details"]:
            if detail not in allowed_details:
                errors.append(f"{prefix} context detail conflict: {detail}")

    if errors:
        print(f"AUDIT_FAILED errors={len(errors)}")
        for error in errors[:50]:
            print(f"- {error}")
        raise SystemExit(1)

    job_counts = Counter(r["scene"]["rescue_job"] for r in records)
    location_counts = Counter(r["scene"]["location_group"] for r in records)
    weather_counts = Counter(r["scene"]["weather_group"] for r in records)
    print(
        f"AUDIT_OK prompts={len(records)} unique={len({r['prompt'] for r in records})} "
        f"batches={len(registry['batches']) if registry else 1} api_called=false"
    )
    print("jobs=" + json.dumps(job_counts, ensure_ascii=False, sort_keys=True))
    print("locations=" + json.dumps(location_counts, ensure_ascii=False, sort_keys=True))
    print("weather=" + json.dumps(weather_counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
