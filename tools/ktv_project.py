"""KTV-only deterministic scene planning and strict five-unit validation. No API."""
from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'ktv_v1_1cover_1triptych_1detail'
BATCH = 'prompts/category_batches/ktv/batch_v1_active'
KINDS = ['cover', 'triptych_panel', 'triptych_panel', 'triptych_panel', 'detail']
ROLES = ['豪华包厢', '包厢空间', '酒水桌面', '大型水果拼盘', '包厢细节']
POSITIONS = [1, 2, 2, 2, 3]


def read(path):
    return runtime_paths.read_json(path)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(value, encoding='utf-8', newline='\n')
    temp.replace(path)


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def rows_text(rows):
    return ''.join(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n' for r in rows)


@variable_catalog.managed('ktv','detail',documents=(('config','configs/categories/ktv.json'),))
def make_group(group_index, config):
    seed = 20260916 + group_index
    rng = random.Random(seed)
    variables = config['random_variables']
    # Balanced shuffled blocks cover every style while remaining reproducible.
    styles = list(variables['包厢风格'])
    random.Random(20260916 + (group_index - 1) // len(styles)).shuffle(styles)
    style = styles[(group_index - 1) % len(styles)]
    lighting = rng.choice(config['linked_randomization']['lighting_by_style'][style])
    consumption = rng.choice(config['linked_randomization']['consumption_states'])
    scene = {
        'seed': seed, '包厢风格': style, '灯光': lighting,
        '包厢大小': rng.choice(variables['包厢大小']),
        '酒水数量': rng.choice(variables['酒水数量']),
        '酒水状态': consumption['drinks'], '桌面状态': consumption['table'],
        '水果': variable_catalog.sample_unique(rng, variables['水果'], rng.randint(3, 5)),
        '人物': rng.choice(variables['人物']),
        '沙发布局': rng.choice(variables['沙发布局']),
        '桌型': rng.choice(variables['桌型']),
        '事件状态': consumption['event'],
        '状态成因': consumption['cause'],
    }
    cameras = variable_catalog.sample_unique(rng, variables['拍摄位置'], 5)
    scene_text = '；'.join(f'{key}：{value}' for key, value in scene.items() if key != 'seed')
    signature = hashlib.sha256(dump(scene).encode()).hexdigest()
    rows = []
    for unit, (kind, role, position) in enumerate(zip(KINDS, ROLES, POSITIONS), 1):
        panel = unit - 1 if kind == 'triptych_panel' else None
        filename = '01_cover.png' if kind == 'cover' else ('02_triptych.png' if panel else '03_detail.png')
        raw_name = f'02_panel_{panel}.png' if panel else filename
        crop = config['composition_rules'][kind]
        focus = config['role_prompts'][role]
        prompt = (f"{config['core_prompt']}\n{config['camera_scenarios'][cameras[unit-1]]}\n"
                  f"房间是{scene['包厢大小']}，{scene['沙发布局']}、{scene['桌型']}。{config['style_prompts'][style]}\n"
                  f"此时{consumption['event']}：{consumption['cause']}"
                  f"酒水{scene['酒水数量']}，{consumption['drinks']}；{consumption['table']}。"
                  f"大型果盘包含{'、'.join(scene['水果'])}。\n"
                  f"{config['environment_prompt']}本组照明：{lighting}。\n"
                  f"这张照片主要拍到：{focus}\n{crop}\n"
                  + '\n'.join(config['physical_rules']) + '\n严格排除：' + '、'.join(config['negative_prompt']))
        rows.append(dict(index=(group_index-1)*5+unit, category_id='ktv', group_index=group_index,
            generation_position=unit, delivery_position=position, generation_kind=kind,
            service_role=role, panel_index=panel, structure_version=VERSION,
            generation_mode='independent_triptych_panels', height_profile_id='portrait_9_16',
            final_size='864x1536', raw_size='1024x1536',
            generation_id=f'ktv:v1:g{group_index:04d}:u{unit:02d}',
            raw_target=f'{BATCH}/raw/group_{group_index:04d}/{raw_name}',
            delivery_target=f'output/ktv/group_{group_index:04d}/{filename}',
            triptych_layout_id='stacked_equal' if panel else None,
            scene_seed=seed, scene=scene, scene_signature=signature,
            cover_variant_signature=signature if kind == 'cover' else None,
            cover_variant={'scene': scene_text, 'camera': cameras[unit-1]} if kind == 'cover' else None,
            prompt=prompt, negative_prompt='、'.join(config['negative_prompt'])))
    deliveries = []
    for position, role in enumerate(['cover', 'triptych', 'detail'], 1):
        sources = [r for r in rows if r['delivery_position'] == position]
        target = sources[0]['delivery_target']
        deliveries.append(dict(schema_version=1, project_id='ktv', category_id='ktv',
            structure_version=VERSION, generation_mode='independent_triptych_panels',
            group_index=group_index, delivery_position=position, role=role, delivery_role=role,
            delivery_id=f'ktv:v1:g{group_index:04d}:d{position:02d}', target=target,
            filename=Path(target).name, source_generation_ids=[r['generation_id'] for r in sources],
            service_roles=[r['service_role'] for r in sources], expected_size='864x1536',
            final_size='864x1536', height_profile_id='portrait_9_16',
            triptych_layout_id='stacked_equal' if role == 'triptych' else None,
            validation_status='pending', status='prompt_ready'))
    return rows, deliveries


def validate_rows(rows, structure, start, count):
    from tools.prompt_engine import CategoryPromptError
    if (structure.get('structure_version') != VERSION or
        structure.get('generation_unit_count') != 5 or structure.get('delivery_unit_count') != 3 or
        structure.get('delivery_roles') != ['cover', 'triptych', 'detail'] or
        structure.get('height_profiles') != [{'id': 'portrait_9_16', 'width': 864, 'height': 1536}]):
        raise CategoryPromptError('KTV必须采用5生成单元/3成品和864x1536结构')
    if len(rows) != count * 5:
        raise CategoryPromptError('KTV所选范围必须每组恰好5个生成单元')
    result = []
    for group_index in range(start, start + count):
        group = sorted([r for r in rows if r.get('group_index') == group_index], key=lambda r: r['index'])
        if [r.get('generation_kind') for r in group] != KINDS:
            raise CategoryPromptError('KTV角色顺序必须是首图、三面板、单图')
        signatures = set()
        for unit, row in enumerate(group, 1):
            expected = dict(category_id='ktv', structure_version=VERSION,
                generation_mode='independent_triptych_panels', generation_position=unit,
                index=(group_index-1)*5+unit, delivery_position=POSITIONS[unit-1],
                service_role=ROLES[unit-1], panel_index=unit-1 if 2 <= unit <= 4 else None,
                final_size='864x1536', height_profile_id='portrait_9_16',
                triptych_layout_id='stacked_equal' if 2 <= unit <= 4 else None)
            if any(row.get(k) != v for k, v in expected.items()):
                raise CategoryPromptError('KTV清单结构/角色/尺寸不匹配')
            scene = row.get('scene')
            signature = hashlib.sha256(dump(scene).encode()).hexdigest()
            if not isinstance(scene, dict) or row.get('scene_signature') != signature or row.get('scene_seed') != scene.get('seed'):
                raise CategoryPromptError('KTV场景设定摘要不匹配')
            signatures.add(signature)
        if len(signatures) != 1:
            raise CategoryPromptError('KTV同组必须共享包厢设定')
        result.extend(group)
    return result


def extend_groups(count):
    if count < 1:
        raise ValueError('组数必须大于0')
    project_path = ROOT / 'projects/ktv/project.json'
    registry_path = ROOT / 'projects/ktv/groups/registry.json'
    project, registry = read(project_path), read(registry_path)
    old_count = int(registry.get('created_groups', 0))
    sample_groups = int(project.get('inventory_policy', {}).get('sample_gate_groups', 1))
    if sample_groups < 1:
        raise RuntimeError('KTV样片组数必须为正整数')
    if old_count + count > sample_groups and not all(project['references'][role]['approved_style'] for role in ('cover', 'detail')):
        raise RuntimeError(f'KTV首图和详情样片风格批准前，只允许准备前{sample_groups}组')
    config = read(ROOT / 'configs/categories/ktv.json')
    prompt_path = ROOT / BATCH / 'prompts.jsonl'
    generation_path = ROOT / 'projects/ktv/groups/generation_manifest.jsonl'
    delivery_path = ROOT / 'projects/ktv/groups/production_manifest.jsonl'
    old = prompt_path.read_bytes() if prompt_path.exists() else b''
    old_gen = generation_path.read_bytes() if generation_path.exists() else b''
    old_delivery = delivery_path.read_bytes() if delivery_path.exists() else b''
    old_rows = [json.loads(line) for line in old.decode('utf-8').splitlines() if line]
    old_deliveries = [json.loads(line) for line in old_delivery.decode('utf-8').splitlines() if line]
    if old != old_gen or len(old_rows) != old_count * 5 or len(old_deliveries) != old_count * 3:
        raise RuntimeError('KTV历史清单与registry不一致，拒绝覆盖')
    if old_count:
        validate_rows(old_rows, config['image_group_structure'], 1, old_count)
    added, deliveries = [], []
    for group in range(old_count + 1, old_count + count + 1):
        units, outputs = make_group(group, config)
        added.extend(units); deliveries.extend(outputs)
    validate_rows(added, config['image_group_structure'], old_count + 1, count)
    for path, prefix, suffix in [(prompt_path, old, rows_text(added)),
                                 (generation_path, old_gen, rows_text(added)),
                                 (delivery_path, old_delivery, rows_text(deliveries))]:
        if prefix and not prefix.endswith(b'\n'):
            raise RuntimeError('KTV历史清单缺少结尾换行，拒绝隐式改写')
        write(path, prefix.decode('utf-8') + suffix)
        if not path.read_bytes().startswith(prefix):
            raise RuntimeError('KTV历史前缀校验失败')
    registry.update(created_groups=old_count+count, next_group_index=old_count+count+1)
    registry['groups'].extend(dict(group_index=g, unit_count=5, delivery_count=3) for g in range(old_count+1, old_count+count+1))
    project['prompt_sources'].update(active_batch=BATCH,
        generation_manifest='projects/ktv/groups/generation_manifest.jsonl',
        production_manifest='projects/ktv/groups/production_manifest.jsonl', available_complete_groups=old_count+count)
    project['production_readiness'] = 'sample_plan_ready_pending_generation_and_visual_approval'
    write(registry_path, dump(registry)); write(project_path, dump(project))
    return dict(project_id='ktv', added_group_count=count, new_generation_units=len(added),
                new_delivery_count=len(deliveries), historical_prefix_preserved=True, api_called=False)
