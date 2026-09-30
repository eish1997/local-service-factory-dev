"""Restore absent batch projections from preserved v3 manifests, without APIs."""
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path


def restore(root: Path) -> dict:
    root = Path(root)
    schema = root / 'projects/road_rescue/groups/schema_v3_5'
    batch = root / 'prompts/category_batches/road_rescue/batch_v3_5_active'
    if batch.exists():
        raise RuntimeError('Batch already exists; refusing to overwrite any evidence')
    names = ['registry.json', 'generation_manifest.jsonl', 'production_manifest.jsonl', 'group_manifest.jsonl']
    originals = {name: (schema / name).read_bytes() for name in names}
    registry = json.loads(originals['registry.json'].decode('utf-8-sig'))
    rows = lambda name: [json.loads(line) for line in originals[name].decode('utf-8-sig').splitlines() if line.strip()]
    generation = rows('generation_manifest.jsonl')
    delivery = rows('production_manifest.jsonl')
    groups = rows('group_manifest.jsonl')
    first, last, count = (int(registry[k]) for k in ('first_group_index', 'last_group_index', 'created_groups'))
    version = 'road_rescue_v3_1cover_1triptych_3details'
    if registry.get('project_id') != 'road_rescue' or registry.get('structure_version') != version:
        raise RuntimeError('Not a road_rescue v3 registry')
    expected = set(range(first, last + 1))
    if count != len(expected) or {r['group_index'] for r in groups} != expected or len(groups) != count:
        raise RuntimeError('Registry and group manifest disagree')
    if Counter(r['group_index'] for r in generation) != Counter({i: 7 for i in expected}):
        raise RuntimeError('Incomplete generation manifest')
    if Counter(r['group_index'] for r in delivery) != Counter({i: 5 for i in expected}):
        raise RuntimeError('Incomplete delivery manifest')
    if len({r['generation_id'] for r in generation}) != count * 7:
        raise RuntimeError('Duplicate generation IDs')
    for i in expected:
        roles = Counter(r['generation_role'] for r in generation if r['group_index'] == i)
        if roles != Counter(cover=1, triptych_panel=3, detail=3):
            raise RuntimeError(f'Invalid roles in group {i}')
    encode = lambda data: ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in data).encode('utf-8')
    manifest = [{
        'schema_version': 3, 'structure_version': version,
        'generation_mode': 'independent_triptych_panels', 'category_id': 'road_rescue',
        **{k: r[k] for k in ('index', 'group_index', 'generation_position', 'generation_id', 'generation_kind', 'service_role', 'raw_target', 'delivery_target')},
        'role': r['generation_role'], 'status': 'prompt_ready', 'api_called': False,
    } for r in generation]
    config = json.loads((root / 'configs/categories/road_rescue.json').read_text(encoding='utf-8-sig'))
    structure = config['image_group_structure']
    summary = {
        'schema_version': 3, 'structure_version': version,
        'generation_mode': 'independent_triptych_panels', 'category_id': 'road_rescue',
        'category_name': '汽车救援', 'mode': 'active_v3_5_group_manifests',
        'group_start': first, 'group_count': count, 'generation_unit_count': len(generation),
        'cover_generation_count': count, 'triptych_panel_generation_count': count * 3,
        'detail_generation_count': count * 3, 'delivery_file_count': len(delivery),
        'delivery_structure': {'cover_count': 1, 'triptych_count': 1, 'detail_count': 3, 'total_per_group': 5},
        'height_profiles': structure['height_profiles'],
        'triptych_layouts': [{'id': r['id'], 'name': r['name']} for r in structure['triptych_layouts']],
        'api_called': False,
        'restored_from': {name: hashlib.sha256(data).hexdigest() for name, data in originals.items()},
    }
    files = {'prompts.jsonl': originals['generation_manifest.jsonl'],
             'delivery_manifest.jsonl': originals['production_manifest.jsonl'],
             'manifest.jsonl': encode(manifest),
             'summary.json': (json.dumps(summary, ensure_ascii=False, indent=2) + '\n').encode('utf-8')}
    for role, name in [('cover', 'cover_prompts.jsonl'), ('triptych_panel', 'triptych_panel_prompts.jsonl'), ('detail', 'detail_prompts.jsonl')]:
        files[name] = encode(r for r in generation if r['generation_role'] == role)
    batch.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=batch.parent) as temporary:
        staging = Path(temporary) / batch.name
        staging.mkdir()
        for name, data in files.items():
            (staging / name).write_bytes(data)
        if any((schema / name).read_bytes() != data for name, data in originals.items()):
            raise RuntimeError('Source manifests changed during restoration')
        os.rename(staging, batch)
    return {'restored': str(batch), 'groups': count, 'source_manifests_unchanged': True, 'api_called': False}
