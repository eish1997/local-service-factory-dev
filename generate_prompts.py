"""Generate a deterministic, balanced set of unique road-rescue prompts."""

from __future__ import annotations

from tools import variable_catalog

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import visual_style_profiles


ROOT = Path(__file__).resolve().parent
PROJECT_ID = "road_rescue"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def balanced_values(values: list[Any], count: int, rng: random.Random) -> list[Any]:
    """Repeat shuffled cycles so every category receives near-equal coverage."""
    result: list[Any] = []
    while len(result) < count:
        cycle = list(values)
        rng.shuffle(cycle)
        result.extend(cycle)
    return result[:count]


def build_prompt(parts: dict[str, Any], negative_constraints: list[str]) -> str:
    negatives = "；".join(negative_constraints)
    prompt = (
        "一张发生在中国的真实道路救援现场照片。"
        f"时间与天气：{parts['time']}，{parts['weather']}。"
        f"地点：{parts['location']}。"
        f"被救援车辆：{parts['vehicle']}。"
        f"现场人员：{parts['worker']}。"
        f"救援任务：{parts['job_name']}，{parts['action']}。"
        f"现场可见且使用方式正确的工具：{'、'.join(parts['tools'])}。"
        f"救援车辆：{parts['rescue_vehicle']}，车身可以清楚写“道路救援”四个字。"
        "救援人员工服胸口或背部可以清楚写“汽车救援”四个字，像真实工服印字，不要悬浮字幕。"
        "若画面露出车辆车头或车尾，车上可以有真实车牌位置，但车牌必须做马赛克或模糊隐私处理，任何号码和字母都不可读。"
        f"拍摄方式：{parts['camera_style']}，{parts['camera_angle']}。"
        f"镜头选择：{parts['visual_lens_prompt']}。"
        f"构图：{parts['composition']}。"
        f"现场细节：{parts['detail_a']}；{parts['detail_b']}。"
        "整体像救援同事临时用普通手机拍下的真实工作记录，不像宣传照；人物不看镜头，动作自然。"
        "人物面部、手部、手套、袖口和工作姿态必须符合真实手机照片，五官自然，皮肤纹理克制，手指数量和关节结构正确，避免抽象人形或蜡像感。"
        "车辆比例、道路安全措施、工具形状、受力方向和操作方式可信，色彩平淡自然。"
        f"严格排除：{negatives}。"
    )
    prompt += visual_style_profiles.prompt_suffix(PROJECT_ID, "road_rescue_detail")
    return prompt


def worker_description(raw_worker: str, weather_group: str) -> str:
    identity = raw_worker.split("，", 1)[0]
    if weather_group == "heavy_rain":
        outfit = "穿带反光条的防水雨衣、防水工作裤和防滑手套"
    elif weather_group == "winter":
        outfit = "穿保暖反光工作服、防水手套和防滑工装鞋"
    elif weather_group == "hot":
        outfit = "穿短袖反光工作服、安全手套和工装鞋"
    else:
        outfit = "穿有正常使用痕迹的反光工作服、安全手套和工装鞋"
    return f"{identity}，{outfit}"


def pick_context_details(
    library: dict[str, Any], location_group: str, weather_group: str, time_text: str, rng: random.Random
) -> tuple[str, str]:
    pools = [library["context_details"]["general"], library["context_details"][location_group]]
    if weather_group in library["context_details"]:
        pools.append(library["context_details"][weather_group])
    if weather_group == "winter":
        pools.append(library["context_details"]["snow"])
    if "深夜" in time_text or "凌晨" in time_text or "路灯" in time_text:
        pools.append(library["context_details"]["night"])
    first = rng.choice(pools[1])
    other_candidates = [item for pool in pools for item in pool if item != first]
    return first, rng.choice(other_candidates)


@variable_catalog.managed('road_rescue','detail',documents=(('library','scene_library.json'),))
def generate_records(
    config: dict[str, Any], library: dict[str, Any], count: int, seed: int | None = None
) -> list[dict[str, Any]]:
    rng = random.Random(config["random_seed"] if seed is None else seed)
    jobs = balanced_values(library["rescue_jobs"], count, rng)
    fields = {
        "time": balanced_values(library["times"], count, rng),
        "job": jobs,
        "vehicle": balanced_values(library["vehicle_types"], count, rng),
        "worker": balanced_values(library["rescue_workers"], count, rng),
        "camera_style": balanced_values(library["camera_styles"], count, rng),
        "camera_angle": balanced_values(library["camera_angles"], count, rng),
        "composition": balanced_values(library["compositions"], count, rng),
    }

    records: list[dict[str, Any]] = []
    prompt_hashes: set[str] = set()
    for offset in range(count):
        index = offset + 1
        job = fields["job"][offset]
        rule = library["job_rules"][job["name"]]
        location_group = rng.choice(rule["location_groups"])
        if job["name"] == "泥巴脱困":
            mud_locations = ["泥泞的乡村土路", "乡村碎石土路", "山区盘山公路安全路肩"]
            allowed_locations = [x for x in library["location_groups"][location_group] if x in mud_locations]
            if not allowed_locations:
                location_group = "rural"
                allowed_locations = ["泥泞的乡村土路", "乡村碎石土路"]
            location = rng.choice(allowed_locations)
        else:
            location = rng.choice(library["location_groups"][location_group])

        if location_group == "garage":
            weather_group = "dry"
            weather = "地下车库内不受室外天气影响"
            time_text = rng.choice(["白天，地下车库普通顶灯照明", "夜间，地下车库普通顶灯照明"])
        else:
            allowed_weather_groups = [g for g in rule["weather_groups"] if not (location_group == "winter" and g != "winter")]
            if location_group == "winter":
                weather_group = "winter"
            else:
                weather_group = rng.choice(allowed_weather_groups)
            weather_choices = list(library["weather_groups"][weather_group])
            if job["name"] == "雪地救援":
                weather_choices = [x for x in weather_choices if "雪" in x]
            weather = rng.choice(weather_choices)
            time_text = fields["time"][offset]

        detail_a, detail_b = pick_context_details(library, location_group, weather_group, time_text, rng)
        visual_lens = visual_style_profiles.choose_lens(
            PROJECT_ID,
            rng,
            location_group=location_group,
            job_name=job["name"],
            section="road_rescue_detail",
        )
        rescue_vehicle = rng.choice(library["rescue_vehicles_by_policy"][rule["vehicle_policy"]])
        chosen_tools = list(job["tools"])
        rng.shuffle(chosen_tools)
        chosen_tools = chosen_tools[: min(4, len(chosen_tools))]
        parts = {
            "time": time_text,
            "weather": weather,
            "weather_group": weather_group,
            "location": location,
            "location_group": location_group,
            "job_name": job["name"],
            "action": job["action"],
            "tools": chosen_tools,
            "vehicle": fields["vehicle"][offset],
            "worker": worker_description(fields["worker"][offset], weather_group),
            "rescue_vehicle": rescue_vehicle,
            "camera_style": fields["camera_style"][offset],
            "camera_angle": fields["camera_angle"][offset],
            "visual_lens_id": visual_lens["id"],
            "visual_lens_prompt": visual_lens["prompt"],
            "composition": fields["composition"][offset],
            "detail_a": detail_a,
            "detail_b": detail_b,
        }
        prompt = build_prompt(parts, library["negative_constraints"])
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if digest in prompt_hashes:
            raise RuntimeError(f"Duplicate prompt produced at index {index}")
        prompt_hashes.add(digest)
        records.append(
            {
                "index": index,
                "filename": config["filename_pattern"].format(index=index),
                "scene": {
                    "time": parts["time"],
                    "weather": parts["weather"],
                    "weather_group": parts["weather_group"],
                    "location": parts["location"],
                    "location_group": parts["location_group"],
                    "rescue_job": parts["job_name"],
                    "vehicle": parts["vehicle"],
                    "tools": parts["tools"],
                    "vehicle_policy": rule["vehicle_policy"],
                    "details": [parts["detail_a"], parts["detail_b"]],
                    "visual_lens": parts["visual_lens_id"],
                    "visual_style_version": visual_style_profiles.visual_style_version(PROJECT_ID),
                    "category_config_version": visual_style_profiles.category_config_version(PROJECT_ID),
                },
                "visual_style_version": visual_style_profiles.visual_style_version(PROJECT_ID),
                "category_config_version": visual_style_profiles.category_config_version(PROJECT_ID),
                "prompt_sha256": digest,
                "prompt": prompt,
            }
        )
    return records


def validate_coverage(records: list[dict[str, Any]], library: dict[str, Any]) -> None:
    expected_values = {
        "time": set(library["times"]),
        "weather": {item for values in library["weather_groups"].values() for item in values},
        "location": {item for values in library["location_groups"].values() for item in values},
        "rescue_job": {item["name"] for item in library["rescue_jobs"]},
        "vehicle": set(library["vehicle_types"]),
    }
    for key, expected in expected_values.items():
        actual = {record["scene"][key] for record in records}
        missing = expected - actual
        if missing:
            raise RuntimeError(f"Coverage failed for {key}; missing: {sorted(missing)}")


def validate_compatibility(records: list[dict[str, Any]], library: dict[str, Any]) -> None:
    for record in records:
        scene = record["scene"]
        job_name = scene["rescue_job"]
        rule = library["job_rules"][job_name]
        location_group = scene["location_group"]
        weather_group = scene["weather_group"]
        if location_group not in rule["location_groups"]:
            raise RuntimeError(f"#{record['index']} incompatible location for {job_name}: {location_group}")
        if location_group != "garage" and weather_group not in rule["weather_groups"]:
            raise RuntimeError(f"#{record['index']} incompatible weather for {job_name}: {weather_group}")
        if location_group == "garage" and scene["location"] not in library["location_groups"]["garage"]:
            raise RuntimeError(f"#{record['index']} invalid garage location")
        if location_group == "winter" and weather_group != "winter":
            raise RuntimeError(f"#{record['index']} winter location without winter weather")
        if job_name == "雪地救援" and "雪" not in scene["weather"]:
            raise RuntimeError(f"#{record['index']} snow rescue without snow")
        if job_name == "泥巴脱困" and location_group not in {"rural", "mountain"}:
            raise RuntimeError(f"#{record['index']} mud rescue outside rural/mountain location")
        if weather_group == "heavy_rain" and "防水雨衣" not in record["prompt"]:
            raise RuntimeError(f"#{record['index']} heavy rain without rainwear")


def initialize_batch_registry(config: dict[str, Any]) -> dict[str, Any]:
    master_path = ROOT / config["prompt_file"]
    records = load_jsonl(master_path)
    initial_count = int(config["prompt_count"])
    if len(records) != initial_count:
        raise RuntimeError(f"Cannot initialize batches: expected {initial_count} existing prompts, found {len(records)}")
    batch_dir = ROOT / config["batch_dir"]
    batch_path = batch_dir / "batch_001.jsonl"
    registry_path = ROOT / config["batch_registry"]
    if registry_path.exists():
        return load_json(registry_path)
    write_jsonl_atomic(batch_path, records)
    registry = {
        "version": 1,
        "total_prompts": len(records),
        "next_index": len(records) + 1,
        "batches": [
            {
                "batch": 1,
                "start_index": 1,
                "end_index": len(records),
                "count": len(records),
                "file": str(batch_path.relative_to(ROOT)).replace("\\", "/"),
            }
        ],
    }
    write_json_atomic(registry_path, registry)
    return registry


def create_new_batch(
    config: dict[str, Any], library: dict[str, Any], count: int
) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    registry_path = ROOT / config["batch_registry"]
    registry = load_json(registry_path) if registry_path.exists() else initialize_batch_registry(config)
    master_path = ROOT / config["prompt_file"]
    history = load_jsonl(master_path)
    if len(history) != int(registry["total_prompts"]):
        raise RuntimeError("Master prompt count does not match batch registry; run the audit before continuing")

    batch_number = len(registry["batches"]) + 1
    start_index = int(registry["next_index"])
    history_hashes = {record["prompt_sha256"] for record in history}
    batch: list[dict[str, Any]] | None = None
    base_seed = int(config["random_seed"]) + batch_number * 1_000_003
    for nonce in range(100):
        candidate = generate_records(config, library, count, seed=base_seed + nonce)
        if not ({record["prompt_sha256"] for record in candidate} & history_hashes):
            batch = candidate
            break
    if batch is None:
        raise RuntimeError("Could not create a history-unique batch after 100 deterministic attempts")

    for offset, record in enumerate(batch):
        global_index = start_index + offset
        record["index"] = global_index
        record["filename"] = config["filename_pattern"].format(index=global_index)

    batch_path = ROOT / config["batch_dir"] / f"batch_{batch_number:03d}.jsonl"
    write_jsonl_atomic(batch_path, batch)
    write_jsonl_atomic(master_path, history + batch)
    registry["batches"].append(
        {
            "batch": batch_number,
            "start_index": start_index,
            "end_index": start_index + count - 1,
            "count": count,
            "file": str(batch_path.relative_to(ROOT)).replace("\\", "/"),
        }
    )
    registry["total_prompts"] = len(history) + count
    registry["next_index"] = start_index + count
    write_json_atomic(registry_path, registry)
    return batch, registry, batch_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate unique road-rescue prompts.")
    parser.add_argument("--count", type=int, help="Number of prompts in a new batch")
    parser.add_argument("--new-batch", action="store_true", help="Append a history-unique batch with continuous numbering")
    parser.add_argument("--initialize-batches", action="store_true", help="Register the existing 1-1000 prompts as batch 1")
    args = parser.parse_args()

    config = load_json(ROOT / "config.json")
    library = load_json(ROOT / "scene_library.json")
    count = args.count or int(config.get("batch_size", config["prompt_count"]))
    if count < 1 or count > 9999:
        raise ValueError("count must be between 1 and 9999")

    if args.initialize_batches:
        registry = initialize_batch_registry(config)
        print(f"Batch registry ready: batches={len(registry['batches'])} total={registry['total_prompts']} api_called=false")
        return

    if args.new_batch:
        batch, registry, batch_path = create_new_batch(config, library, count)
        validate_compatibility(batch, library)
        print(
            f"Created batch {len(registry['batches']):03d}: {batch[0]['index']}-{batch[-1]['index']} "
            f"({len(batch)} prompts) -> {batch_path}"
        )
        print(f"Total prompts: {registry['total_prompts']}; API called: false")
        return

    registry_path = ROOT / config["batch_registry"]
    if registry_path.exists():
        registry = load_json(registry_path)
        print(
            f"Existing batch system detected: batches={len(registry['batches'])}, total={registry['total_prompts']}. "
            "Use --new-batch to append without changing history."
        )
        return

    records = generate_records(config, library, int(config["prompt_count"]))
    validate_coverage(records, library)
    validate_compatibility(records, library)
    output_path = ROOT / config["prompt_file"]
    write_jsonl_atomic(output_path, records)
    registry = initialize_batch_registry(config)

    job_counts = Counter(record["scene"]["rescue_job"] for record in records)
    print(f"Generated {len(records)} unique prompts and initialized batch 001: {output_path}")
    print("Rescue-job coverage: " + ", ".join(f"{k}={v}" for k, v in sorted(job_counts.items())))


if __name__ == "__main__":
    main()
