"""Import already-generated built-in images; never open a network connection."""
import copy
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def import_images(factory, receipt_path: Path):
    from PIL import Image
    from tools import category_image_production as production
    receipt = factory.load_json(receipt_path)
    if receipt.get('provider') != 'chatgpt_builtin_imagegen' or receipt.get('category_id') != 'road_rescue':
        raise RuntimeError('Expected a road_rescue built-in image receipt')
    group = int(receipt['group_index'])
    phone = factory._category_confirmed_phone('road_rescue', receipt['phone'])
    factory._category_sample_range('road_rescue', group, 1, scope='all')
    batch = factory.category_active_batch_dir('road_rescue')
    if (batch / 'production/generation.lock').exists():
        raise RuntimeError('An API production lock exists; refusing concurrent import')
    plan = production.plan('road_rescue', batch, group, 1, phone,
                           factory._category_effective_config(), scope='all',
                           output_root=factory._category_output_root('road_rescue'))
    records = plan['records']
    assets = receipt['assets']
    by_id = {item['generation_target_id']: item for item in assets}
    if len(assets) != 7 or len(by_id) != 7 or set(by_id) != {r['generation_target_id'] for r in records}:
        raise RuntimeError('Receipt must contain exactly the seven requested source assets')
    evidence = batch / 'builtin' / f'group_{group:04d}'
    if evidence.exists() or any(Path(d['target']).exists() for d in plan['delivery_records']):
        raise RuntimeError('Existing evidence or output found; no automatic overwrite')
    for asset in assets:
        source = Path(asset['source_path'])
        with Image.open(source) as im:
            im.load()
            if im.format != 'PNG' or im.size != (1024, 1536):
                raise RuntimeError('Built-in source must be a valid 1024x1536 PNG')
    evidence.mkdir(parents=True)
    (evidence / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    replacements = {}
    imported = []
    for record in records:
        identity = record['generation_target_id']
        source = Path(by_id[identity]['source_path'])
        target = evidence / f"u{int(record['generation_position']):02d}.png"
        shutil.copy2(source, target)
        replacements[identity] = str(target)
        imported.append({'generation_target_id': identity, 'path': str(target),
                         'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    local_plan = copy.deepcopy(plan)
    for delivery in local_plan['delivery_records']:
        for record in delivery['records']:
            record['raw_target'] = replacements[record['generation_target_id']]
    completed = production.recover_local_deliveries(local_plan, phone)
    if completed != 5:
        raise RuntimeError(f'Only {completed}/5 local deliveries materialized; inspect preserved evidence')
    now = datetime.now(timezone.utc).isoformat()
    job_id = f'road_rescue-builtin-g{group}-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}'
    job = {'job_id': job_id, 'job_type': 'builtin-image-production',
           'category_id': 'road_rescue', 'project_id': 'road_rescue',
           'batch_dir': str(batch), 'batch_id': batch.name, 'scope': 'all',
           'group_start': group, 'group_count': 1, 'requested_count': 5,
           'completed': 5, 'failed': 0, 'status': 'awaiting_review',
           'provider': 'chatgpt_builtin_imagegen', 'model': 'ChatGPT built-in imagegen',
           'size': '1024x1536', 'final_size': '1024x1408',
           'requests_used': 0, 'request_budget': 0, 'builtin_requests': receipt['builtin_request_count'],
           'api_key_slots': [], 'phone': phone, 'created_at': now, 'updated_at': now,
           'evidence': str(evidence), 'approved': False}
    job_path = factory.JOBS_DIR / f'{job_id}.json'
    factory.write_json_atomic(job_path, job)
    for delivery in local_plan['delivery_records']:
        validation_path = Path(delivery['target']).with_suffix('.validation.json')
        validation = factory.load_json(validation_path)
        validation.update(provider='chatgpt_builtin_imagegen', builtin_receipt=str(evidence / 'receipt.json'),
                          approved=False, status='needs_user_review')
        factory.write_json_atomic(validation_path, validation)
    factory.write_json_atomic(evidence / 'import_result.json', {'job': job, 'sources': imported})
    factory.activate_dashboard_session(job_path, job, target_records=local_plan['delivery_records'])
    return {'job_id': job_id, 'completed': completed, 'output': str(Path(plan['delivery_records'][0]['target']).parent),
            'api_called': False, 'status': 'awaiting_review'}
