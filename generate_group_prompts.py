"""Create deterministic 1-cover + 8-detail content-group manifests without an LLM or image API."""

from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import visual_style_profiles


ROOT = Path(__file__).resolve().parent
PROJECT_DIR = ROOT / "projects" / "road_rescue"
BUSINESS_PATH = ROOT / ".runtime" / "projects" / "road_rescue" / "business.json"
TUNING_RULES_PATH = PROJECT_DIR / "preferences" / "prompt_tuning_rules.jsonl"
TUNING_DRAFTS_PATH = ROOT / ".runtime" / "projects" / "road_rescue" / "prompt_tuning_drafts.jsonl"


@variable_catalog.document_loader
def load(path: Path) -> Any:
    return runtime_paths.read_json(path)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def reject_snow_details_from_preferences() -> bool:
    path = PROJECT_DIR / "preferences" / "REJECTED_PATTERNS.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return any(marker in text for marker in ["不要雪地", "排除小雪", "排除雪地", "雪地场景"])


def detail_has_snow_scene(record: dict[str, Any]) -> bool:
    scene = record.get("scene", {})
    haystack = json.dumps(scene, ensure_ascii=False) + "\n" + str(record.get("prompt", ""))
    return any(marker in haystack for marker in ["小雪", "大雪", "积雪", "雪地救援", "车轮积雪", "雪铲"])


def select_detail_chunks(
    detail_records: list[dict[str, Any]],
    used_indices: set[int],
    group_count: int,
    reject_snow: bool,
    desired_visual_style: str | None = None,
) -> list[list[int]]:
    selected: list[int] = []
    for record in sorted(detail_records, key=lambda item: int(item["index"])):
        index = int(record["index"])
        if index in used_indices:
            continue
        if desired_visual_style and record.get("visual_style_version") != desired_visual_style:
            continue
        if reject_snow and detail_has_snow_scene(record):
            continue
        selected.append(index)
        if len(selected) == group_count * 8:
            break
    if len(selected) < group_count * 8:
        raise RuntimeError(
            f"Not enough existing detail prompts after filters: need {group_count * 8}, found {len(selected)}"
        )
    return [selected[position:position + 8] for position in range(0, len(selected), 8)]


def used_detail_indices() -> set[int]:
    used: set[int] = set()
    for group in load_jsonl(PROJECT_DIR / "groups" / "group_manifest.jsonl"):
        for detail in group.get("details", []):
            used.add(int(detail["index"]))
    return used


def tuning_suffix(include_drafts: bool) -> str:
    records: list[dict[str, Any]] = []
    for path in [TUNING_RULES_PATH, *([TUNING_DRAFTS_PATH] if include_drafts else [])]:
        if path.is_file():
            records.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    active = [item for item in records if item.get("status", "active") == "active"]
    if not active:
        return ""
    action_labels = {"strengthen": "加强", "weaken": "减弱", "add": "新增", "remove": "删除", "keep": "保持"}
    lines = [f"- {action_labels.get(item['action'], item['action'])}【{item['dimension']}】：{item['note']}" for item in active]
    return "\n\n用户确认或正在试验的提示词调优规则：\n" + "\n".join(lines)


def cover_prompt(group_index: int, library: dict[str, Any], phones: list[str], variant: int = 0, era_profile_id: str | None = None) -> tuple[str, dict[str, Any]]:
    rng = random.Random(2026070400 + group_index + variant * 99991)
    visual_version = visual_style_profiles.visual_style_version("road_rescue")
    category_version = visual_style_profiles.category_config_version("road_rescue")
    cover_template_version = str(
        library.get("template_version") or "road_rescue_storefront_legacy"
    )
    store_name = rng.choice(library["store_name_prefixes"]) + rng.choice(library["store_name_suffixes"])
    main_business_word = rng.choice(["汽车救援", "道路救援", "拖车服务"])
    selected_phones = rng.sample(phones, k=min(len(phones), rng.choice([1, 2])))
    phone_text = " / ".join(selected_phones)
    choices = {key: rng.choice(library[key]) for key in [
        "sign_color_schemes", "business_lines", "sign_conditions", "locations", "tow_trucks",
        "support_vehicles", "workers", "street_details", "lighting", "camera_styles",
        "facade_archetypes", "storefront_layouts", "sign_shapes", "vehicle_layouts",
        "camera_compositions", "shop_states", "weather_atmospheres",
        "business_modes", "workshop_activities", "street_activity_levels", "foreground_elements",
        "rescue_vehicle_prominence", "sign_surface_styles", "sign_information_layouts",
        "sign_accent_details", "sign_installation_details",
    ]}
    era_population = library["era_profiles"]
    if era_profile_id:
        era_profile = next((item for item in era_population if item["id"] == era_profile_id), None)
        if not era_profile:
            raise ValueError(f"unknown era profile: {era_profile_id}")
    else:
        era_profile = rng.choices(era_population, weights=[item["weight"] for item in era_population], k=1)[0]
    era_facade = rng.choice(era_profile["facades"])
    era_vehicle = rng.choice(era_profile["vehicles"])
    era_sign = rng.choice(era_profile["signs"])
    signature = " | ".join(choices[key] for key in [
        "facade_archetypes", "storefront_layouts", "sign_shapes", "vehicle_layouts",
        "camera_compositions", "shop_states", "weather_atmospheres",
        "business_modes", "workshop_activities", "street_activity_levels", "foreground_elements",
        "rescue_vehicle_prominence", "sign_surface_styles", "sign_information_layouts",
        "sign_accent_details", "sign_installation_details",
    ])
    signature += " | " + " | ".join([
        cover_template_version,
        main_business_word,
        era_profile["id"],
        era_facade,
        era_vehicle,
        era_sign,
    ])
    signboard_realism = "；".join(str(value) for value in library["signboard_realism_rules"])
    signboard_framing = "；".join(str(value) for value in library["signboard_framing_rules"])
    keyword_hierarchy = "；".join(str(value) for value in library["keyword_hierarchy_rules"])
    prompt = (
        f"一张完全依靠文字描述生成、不使用任何参考图片的写实中国汽车救援门店照片。"
        f"门头模板版本：{cover_template_version}。"
        f"年代基准：{era_profile['period']}，整体属于“{era_profile['label']}”；{era_profile['scene_cues']}。"
        f"经营形态：{choices['business_modes']}。地点是{choices['locations']}，建筑是{era_facade}；{choices['storefront_layouts']}，"
        f"{choices['shop_states']}。天气氛围：{choices['weather_atmospheres']}；{choices['lighting']}，"
        "整体接地气、有真实生活气息，并与其他批次采用明显不同的空间构图。"
        f"门头招牌结构是{choices['sign_shapes']}，使用{choices['sign_color_schemes']}，配色协调，符合国内真实街边店铺习惯。"
        f"实体与镜头硬规则：{signboard_realism}；{signboard_framing}。"
        f"门头上层较小店名为“{store_name}”，中部最大主业务词必须清楚写“{main_business_word}”，"
        f"下层业务小字为“{choices['business_lines']}”；店名不得比“{main_business_word}”更大或更醒目。"
        "以上文字必须属于照片中的真实实体招牌，"
        "板面材质、文字透视和建筑角度一致；不要在实体招牌上方覆盖任何后期文字、彩色半透明板或发光叠加板。"
        f"关键词层级硬规则：{keyword_hierarchy}。"
        f"门头信息层级：{choices['sign_information_layouts']}；装饰细节：{choices['sign_accent_details']}；"
        f"安装细节：{choices['sign_installation_details']}。门头至少包含主标题、业务信息和真实结构细节三个层级，"
        "避免只有一行大字的空门头，也避免堆满文字、图标或按钮。"
        f"门头主招牌板面内部必须把联系电话自然排版成实体招牌内容，号码清楚准确写成“{phone_text}”。"
        "参考真实中国汽车救援门店，从上到下可形成店名、汽车救援主业务词、服务小字、联系电话四层信息，"
        "联系电话优先放在主招牌底部或右侧联系信息区，字号清楚但不抢过店名，文字材质、透视、阴影和环境光必须与实体招牌一致。"
        "不要生成联系电话占位符、错误号码、额外号码、悬浮字幕、后期贴纸、内外边框或 UI 面板；"
        "本地图像处理程序不会再向门头添加任何文字或底板。"
        "画面中部偏下和底部只保留连续真实的玻璃门、卷帘门、门店开口、车身、街景或地面，"
        "避开人物脸、核心作业动作、车轮关键结构和门头主文字；"
        "不得生成电话图标、电话胶囊、横幅、色条、服务列表、蓝色服务方格、十宫格、按钮、卡片、海报或 UI。"
        f"招牌表面与排版：{choices['sign_surface_styles']}；基础材质：{era_sign}。"
        f"维修作业：{choices['workshop_activities']}。救援车辆在画面中的权重：{choices['rescue_vehicle_prominence']}。"
        f"若出现清障车，其细节为{era_vehicle}，车身可以清楚写“道路救援”四个字；辅助车辆为{choices['support_vehicles']}。"
        "若门店前车辆、清障车或辅助车辆露出车头/车尾，车上可以有真实车牌位置，但车牌必须做马赛克或模糊隐私处理，任何号码和字母都不可读。"
        f"{choices['workers']}，工服胸口或背部可以清楚写“汽车救援”四个字；{choices['street_details']}。街道状态：{choices['street_activity_levels']}。"
        "人物只作为真实营业与维修状态中的工作人员出现，面部、手部、手套、衣服褶皱和站姿要自然清楚，不要抽象人形、塑料皮肤或广告模特感。"
        f"前景关系：{choices['foreground_elements']}。拍摄方式：{choices['camera_styles']}，"
        f"镜头构图：{choices['camera_compositions']}。竖屏9:16，门头完整、文字区域清楚，高清细节，"
        "真实街景摄影但不像广告效果图；门头店名、业务小字和联系电话都必须属于原图实体招牌，"
        "门头号码由模型原生生成并人工验收；画面中部和底部必须保持未排版的连续真实场景；"
        "不要复刻任何固定参考图的建筑、车辆位置或机位。"
        f"严格排除：{library['negative']}。"
    )
    prompt += visual_style_profiles.prompt_suffix("road_rescue", "storefront_cover")
    return prompt, {"store_name": store_name, "main_business_word": main_business_word,
        "cover_template_version": cover_template_version,
        "phones": selected_phones, "phone_bar_text": phone_text, "composition_signature": signature,
        "era_profile": era_profile, "era_facade": era_facade, "era_vehicle": era_vehicle, "era_sign": era_sign,
        "visual_style_version": visual_version, "category_config_version": category_version, **choices}


@variable_catalog.managed('road_rescue', 'cover', finish_result='always', documents=(('library','projects/road_rescue/cover_scene_library.json'),('visual_profile','projects/road_rescue/cover_visual_profile_v3.json')))
def cover_prompt_v3(
    group_index: int,
    library: dict[str, Any],
    visual_profile: dict[str, Any],
    phones: list[str],
    variant: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Build one coherent future-only storefront shot from business and visual inputs."""
    if group_index < int(visual_profile["first_group_index"]) or not phones:
        raise ValueError("v3 cover needs a future group and a confirmed phone")
    offset = group_index - int(visual_profile["first_group_index"])

    def cycle(values: list[Any], phase: int = 0, *, secondary: bool = False) -> Any:
        if not values:
            raise ValueError("v3 cover visual profile has an empty selection pool")
        size = len(values)
        selection_offset = offset + (variant * 31 if secondary else 0)
        return values[((selection_offset % size) * (size - 1) + 2 * (selection_offset // size) + phase) % size]

    shot = dict(cycle(visual_profile["shot_presets"]))
    from tools.road_composition_variants import choose_composition
    composition = choose_composition(group_index, variant, int(visual_profile['first_group_index']))
    from tools.road_environment_variants import choose_environment, adapt_composition
    environment = choose_environment(group_index, variant, int(visual_profile['first_group_index']))
    from tools.road_postprocess_variants import choose_postprocess, postprocess_instruction
    postprocess = choose_postprocess(group_index, variant, int(visual_profile['first_group_index']))
    from tools.road_snapshot_variants import choose_snapshot, snapshot_instruction
    snapshot = choose_snapshot(group_index, variant, environment, postprocess)
    composition = adapt_composition(composition, environment)
    shot['bays'] = environment['bays']
    shot['facade'] = environment['facade']
    shot['corner'] = False
    shot['camera'] = composition['camera']
    light = cycle(visual_profile["light_presets"], 1)
    device_pool = visual_profile.get("capture_devices", [])
    eligible_devices = [item for item in device_pool
                        if item["id"] != "work_phone_dusk" or light["id"] in {"late_daylight", "shop_light_dusk"}]
    if "两倍" not in shot["camera"]:
        eligible_devices = [item for item in eligible_devices if item["id"] != "phone_two_x"]
    device = cycle(eligible_devices, 3, secondary=True) if eligible_devices else None
    worker = cycle(visual_profile["worker_presentations"], 2)
    target_mode = visual_profile.get("target_mode", {})
    target_enabled = isinstance(target_mode, dict) and target_mode.get("enabled") is True
    reality_anchors = target_mode.get("reality_anchors", []) if target_enabled else []
    if target_enabled and not isinstance(reality_anchors, list):
        raise ValueError("v3 target mode reality_anchors must be a list")
    reality_anchor = cycle(reality_anchors, 4, secondary=True) if reality_anchors else None
    if reality_anchor is not None and not isinstance(reality_anchor, dict):
        raise ValueError("v3 target mode reality_anchor must be an object")
    era_pool = [item for item in library["era_profiles"] for _ in range(int(item["weight"]))]
    era = cycle(era_pool, 3)
    vehicle_presence = cycle(library["rescue_vehicle_prominence"], 1)
    vehicle_index = library["rescue_vehicle_prominence"].index(vehicle_presence)
    sign_color = cycle(library["sign_color_schemes"], 2, secondary=True)
    multiple_bays = int(shot.get("bays", 1)) >= 2
    shape_indices = list(range(4 if multiple_bays else 3))
    if shot.get("corner"):
        shape_indices.append(4)
    sign_shape = cycle([library["sign_shapes"][i] for i in shape_indices], 1, secondary=True)
    mode_indices = [1]
    if vehicle_index != 3:
        mode_indices.append(0)
    if vehicle_index != 0:
        mode_indices.append(2)
    if multiple_bays:
        mode_indices.append(3)
    business_mode = cycle([library["business_modes"][i] for i in mode_indices], 2, secondary=True)
    business_line = cycle(library["business_lines"], 1)
    main_business_word = cycle(["汽车救援", "道路救援", "拖车服务"])
    phone = cycle(phones)
    rng = random.Random(f"road_rescue:cover_v3:{group_index}:{variant}")
    store_name = rng.choice(library["store_name_prefixes"]) + rng.choice(library["store_name_suffixes"])
    worker_index = visual_profile["worker_presentations"].index(worker)
    from tools.road_signboard_variants import choose_signboard
    signboard = choose_signboard(group_index, variant, narrow=not multiple_bays)
    main_business_word = signboard["title"]
    business_line = signboard["business_line"]
    sign_color = signboard["palette"]
    sign_shape = ("按两开间实际门楣与雨棚宽度制作的普通横向招牌，边框与建筑连接可信"
                  if multiple_bays else "按单开间门面宽度制作的普通门头，文字密度适应窄门面")
    # User authorized realistic-style synthetic shop names, independent of contact input.
    store_name = signboard["store_name"]
    activity_indices = (0, 2, 3) if worker_index in (2, 4) else (1, 4)
    activity_indices = [i for i in activity_indices if multiple_bays or i != 0]
    activity = cycle([library["workshop_activities"][i] for i in activity_indices], secondary=True)
    vehicle_layout = None if vehicle_index == 3 else library["vehicle_layouts"][vehicle_index]
    location = library["locations"][int(shot["location_index"])]
    street_indices = [1]
    if light["id"] == "clear_morning":
        street_indices.extend((0, 3))
    elif light["id"] == "ordinary_afternoon" and shot["location_index"] == 1:
        street_indices.append(2)
    street = cycle([library["street_activity_levels"][i] for i in street_indices], 2)
    foreground_indices = list(range(4))
    if multiple_bays and vehicle_index == 3:
        foreground_indices.append(4)
    foreground = cycle([library["foreground_elements"][i] for i in foreground_indices], 3, secondary=True)
    visual_rules = "；".join(str(rule) for rule in visual_profile["visual_rules"])
    target_rules = "；".join(str(rule) for rule in target_mode.get("rules", [])) if target_enabled else ""
    vehicle_instruction = (
        "本组不出现完整清障车，不用黄色车头填充前景；只通过店内真实救援设备暗示业务。"
        if vehicle_layout is None
        else f"救援车位置：{vehicle_layout}；{vehicle_presence}。车轮、平板和绞盘结构必须可信。"
    )
    # Bind action, subject placement and foreground to the same layout, avoiding
    # contradictory legacy right/left vehicle positions and extra repair events.
    activity = composition['activity']
    foreground = composition['foreground']
    vehicle_instruction = ('本图不出现清障车。' if vehicle_index == 3 else composition['vehicle'] + '。')
    reality_anchor = None
    location = environment['setting']
    business_mode = environment['business']
    street = environment['activity']
    prompt = (
        "中国街边正在营业的道路救援门店，普通人用手机随手拍下的单张竖幅真实照片。"
        f"本组只拍一种现场：{location}；建筑外观为{shot['facade']}。"
        f"门面环境整套约束：地面与道路为{environment['ground']}；周边为{environment['neighbours']}；可见边缘为{environment['edge']}。"
        "建筑、门型、地面和邻接环境必须属于同一地点，不把所有场景画成居民楼底层卷帘门；树木、骑车人和车流按本组随机生活元素选择出现，允许没有，不能变成每张固定前景。"
        f"拍摄机位：{shot['camera']}。光线与干湿状态：{light['description']}。"
        f"本图构图约束：{composition['scale']}；{composition['subject']}。"
        "招牌、店铺进深和作业形成同一真实空间；人物面部、双手和关键操作避开中部电话叠字位置，不能用大块空地预留字版。"
        f"门店与车辆维护程度：{era['label']}；经营形态：{business_mode}；店内正在发生：{activity}。"
        f"人物呈现：{worker}。街道状态：{street}；前景：{foreground}。"
        f"{vehicle_instruction}"
        f"实体招牌：{sign_shape}；板面和字色：{sign_color}；有真实包边、安装接缝和自然投影。"
        f"本次招牌的完整店名主标题为“{store_name}”，服务内容为“{business_line}”。"
        "店名字号必须保留，不能省略成只有汽车救援或道路救援等类目词；完整店名作为主标题，不另设更大的固定业务标题。"
        f"制作方式：{signboard['material']}；排版：{signboard['layout']}；使用状态：{signboard['condition']}。"
        "像当地广告制作店按门面尺寸制作的实用招牌，采用普通粗体、紧凑字距和明确的信息层级，"
        "不做大留白简约品牌板，也不把所有招牌做成同一种四层结构；文字可按本次布局合理分行，"
        "店名按用户授权随机组装为普通本地小店命名风格，不代表核实存在的商户；不同批次店名、服务子集、顺序、材质与布局允许变化，禁止自行替换店名或加入地区、连锁品牌、价格、时效或承诺。"
        "门头电话仅使用用户输入并确认的号码，完整保留所有数字，不随机生成或改号，具体数字在生产时注入。"
        "门头文字、号码与招牌板面具有同一透视和光线；完整主招牌及联系电话放在原图上方百分之四十以内，"
        "号码不得靠近画面中部的后期电话条区域，不得落到侧墙、车身或店门上。"
        f"视觉硬规则：{visual_rules}。"
        "不要为了展示所有元素而摆成正面居中的广告照；镜头只按本组机位拍，不切换到其他建筑或天气。"
        f"严格排除：{library['negative']}。"
    )
    if reality_anchor:
        prompt += f"现实锚点：{reality_anchor['description']}。"
    if device:
        prompt += f"拍摄设备与成像特征：{device['description']}。设备只影响成像和与机位匹配的取景，不强行改变营业现场，不显示相机型号、水印或拍摄参数。"
    if target_rules:
        prompt += f"目标模式规则：{target_rules}。"
    prompt += visual_style_profiles.prompt_suffix("road_rescue", "storefront_cover")
    # Legacy category/style text must not override the selected shop name or camera.
    prompt = prompt.replace('不要把泛化店名做得大于汽车救援、道路救援或拖车服务主业务词；', '')
    if '两倍' in shot['camera']:
        prompt = prompt.replace('使用普通手机主摄观感，轻微广角透视', '使用本组指定的手机两倍取景，透视服从实际拍摄距离')
    # Device color is a capture baseline; final grading is explicitly selected below.
    prompt += '\n' + postprocess_instruction(postprocess)
    prompt += '\n' + snapshot_instruction(snapshot)
    signature_fields = (
        shot["id"], light["id"], era["id"], vehicle_index,
        sign_color, sign_shape, worker_index, business_mode, activity, foreground,
        reality_anchor.get("id") if reality_anchor else None,
        device["id"] if device else None,
        signboard,
        composition,
        environment,
        postprocess,
        snapshot,
    )
    signature = hashlib.sha256(
        json.dumps(signature_fields, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return prompt, {
        "store_name": store_name,
        "main_business_word": main_business_word,
        "cover_template_version": visual_profile["version"],
        "phones": [phone],
        "phone_bar_text": phone,
        "composition_signature": signature,
        "visual_shot_id": shot["id"],
        "composition_family": composition['id'],
        "composition_plan": composition,
        "environment_family": environment['id'],
        "environment_plan": environment,
        "postprocess_id": postprocess['id'],
        "postprocess_plan": postprocess,
        "snapshot_plan": snapshot,
        "camera_instruction": shot['camera'],
        "capture_device_id": device["id"] if device else None,
        "capture_device_name": device["name"] if device else None,
        "visual_light_id": light["id"],
        "visual_vehicle_presence": vehicle_index,
        "visual_worker_presentation": worker_index,
        "target_mode": str(target_mode.get("version") or "") if target_enabled else None,
        "visual_reality_anchor_id": str(reality_anchor.get("id") or "") if reality_anchor else None,
        "era_profile": era,
        "location": location,
        "business_mode": business_mode,
        "business_line": business_line,
        "sign_color_scheme": sign_color,
        "sign_shape": sign_shape,
        "signboard_variant": signboard,
        "workshop_activity": activity,
        "foreground": foreground,
        "street_activity": street,
        "visual_style_version": visual_style_profiles.visual_style_version("road_rescue"),
        "category_config_version": visual_style_profiles.category_config_version("road_rescue"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--random", action="store_true")
    parser.add_argument("--era-profile", choices=["maintained_2014_2018", "balanced_2019_2022", "current_2023_2026"])
    args = parser.parse_args()
    if args.count < 1:
        raise ValueError("count must be positive")
    if not BUSINESS_PATH.is_file():
        raise RuntimeError("CONTACT_CONFIRMATION_REQUIRED: confirm telephone numbers before creating cover prompts")
    business = load(BUSINESS_PATH)
    phones = business.get("contact_phones", [])
    if not business.get("user_confirmed") or not phones:
        raise RuntimeError("CONTACT_CONFIRMATION_REQUIRED: telephone numbers are not confirmed")

    library = load(PROJECT_DIR / "cover_scene_library.json")
    if args.sample:
        samples = []
        previous_signature = None
        source_indices = (
            random.SystemRandom().sample(range(1001, 100001), args.count)
            if args.random else list(range(1, args.count + 1))
        )
        for sample_index, source_index in enumerate(source_indices, start=1):
            variant = 0
            while True:
                prompt, scene = cover_prompt(source_index, library, phones, variant, args.era_profile)
                if scene["composition_signature"] != previous_signature:
                    break
                variant += 1
            previous_signature = scene["composition_signature"]
            prompt += tuning_suffix(include_drafts=True)
            samples.append({
                "sample_index": sample_index, "source_index": source_index,
                "project_id": "road_rescue", "role": "cover",
                "prompt": prompt, "scene": scene,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            })
        sample_path = ROOT / ".runtime" / "projects" / "road_rescue" / "cover_samples.json"
        atomic_json(sample_path, {"project_id": "road_rescue", "samples": samples})
        print(f"COVER_SAMPLES_READY count={args.count} api_called=false llm_called=false file={sample_path}")
        return
    if business.get("placeholder_only"):
        raise RuntimeError("FORMAL_CONTACT_REQUIRED: placeholder telephone numbers may be used only for samples")
    registry_path = PROJECT_DIR / "groups" / "registry.json"
    registry = load(registry_path)
    next_group = int(registry["next_group_index"])
    final_group = next_group + args.count - 1
    detail_chunks = select_detail_chunks(
        load_jsonl(ROOT / "prompts" / "road_rescue_prompts.jsonl"),
        used_detail_indices(),
        args.count,
        reject_snow_details_from_preferences(),
        desired_visual_style=visual_style_profiles.visual_style_version("road_rescue"),
    )

    cover_records: list[dict[str, Any]] = []
    group_records: list[dict[str, Any]] = []
    previous_signature = registry["groups"][-1].get("composition_signature") if registry["groups"] else None
    for offset, group_index in enumerate(range(next_group, final_group + 1)):
        variant = 0
        while True:
            prompt, scene = cover_prompt(group_index, library, phones, variant)
            if scene["composition_signature"] != previous_signature:
                break
            variant += 1
        previous_signature = scene["composition_signature"]
        details = detail_chunks[offset]
        cover_filename = f"road_rescue_group_{group_index:04d}_cover.png"
        prompt += tuning_suffix(include_drafts=False)
        cover = {
            "project_id": "road_rescue", "group_index": group_index, "role": "cover",
            "filename": cover_filename, "scene": scene, "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "visual_style_version": scene["visual_style_version"],
            "category_config_version": scene["category_config_version"],
        }
        group = {
            "project_id": "road_rescue", "group_index": group_index,
            "cover": {"filename": cover_filename, "prompt_sha256": cover["prompt_sha256"]},
            "details": [{"index": i, "filename": f"road_rescue_{i:04d}.png"} for i in details],
            "total_images": 9,
            "visual_style_version": scene["visual_style_version"],
            "category_config_version": scene["category_config_version"],
        }
        cover_records.append(cover)
        group_records.append(group)

    append_jsonl(PROJECT_DIR / "prompts" / "cover_prompts.jsonl", cover_records)
    append_jsonl(PROJECT_DIR / "groups" / "group_manifest.jsonl", group_records)
    registry["groups"].extend({
        "group_index": item["group_index"], "cover": item["cover"]["filename"],
        "detail_start": item["details"][0]["index"], "detail_end": item["details"][-1]["index"],
        "composition_signature": cover_records[position]["scene"]["composition_signature"],
    } for position, item in enumerate(group_records))
    registry["created_groups"] = int(registry["created_groups"]) + args.count
    registry["next_group_index"] = final_group + 1
    atomic_json(registry_path, registry)
    print(f"CONTENT_GROUPS_READY project=road_rescue groups={args.count} images={args.count * 9} api_called=false llm_called=false")


if __name__ == "__main__":
    main()
