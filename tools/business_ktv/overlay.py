"""Category policy around the shared deterministic overlay renderer; no API calls."""
import hashlib
import json
import re
from pathlib import Path

from tools.category_image_production import apply_overlays, atomic_json, load_json


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_job(root, job_id=None):
    root = Path(root).resolve()
    policy = load_json(root / 'configs/business_ktv/local_overlay.json')
    if policy.get('category_id') != 'business_ktv' or not policy.get('enabled'):
        raise ValueError('商务KTV本地叠字规则尚未启用')
    contact_path = (root / policy['phone_source']).resolve()
    if not contact_path.is_relative_to(root / '.runtime/projects/business_ktv'):
        raise ValueError('电话必须来自本类目独立确认文件')
    contact = load_json(contact_path)
    phones = contact.get('contact_phones', [])
    if (contact.get('project_id') != 'business_ktv' or contact.get('user_confirmed') is not True
            or len(phones) != 1 or not re.fullmatch(r'1[3-9]\d{9}', str(phones[0]))):
        raise ValueError('缺少已确认的商务KTV手机号')
    words = policy['service_words']
    if len(words) != 8 or len(set(words)) != 8 or any(not isinstance(w, str) or not w.strip() for w in words):
        raise ValueError('底部服务词必须为已确认的8个不同词语')
    base = root / 'database/business_ktv/api'
    if job_id is None:
        job_id = load_json(base / 'checkpoint.json')['job_id']
    if job_id in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9_.-]+', job_id):
        raise ValueError('非法任务编号')
    state = load_json(base / 'runs' / job_id / 'checkpoint.json')
    if state.get('job_id') != job_id:
        raise ValueError('任务目录与checkpoint编号不匹配')
    if state['category_id'] != 'business_ktv' or state['backend'] != 'api' or state['status'] != 'completed':
        raise ValueError('仅处理已完成实际图片审核的商务KTV任务')
    image_root = root / 'output/business_ktv/api' / job_id
    source_rows = [r for r in state['records'] if r['status'] in ('accepted', 'rejected')]
    if not source_rows:
        raise ValueError('没有已审核原图可供本地叠字')
    for row in source_rows:
        source = Path(row['path']).resolve()
        if not source.is_relative_to(image_root / 'raw') or sha(source) != row['audit']['image_sha256']:
            raise ValueError('原图路径或审核SHA不匹配')
    binding = {'policy': policy, 'phone': phones[0], 'sources': [
        [r['index'], r['audit']['image_sha256'], r['status']] for r in source_rows]}
    binding_sha = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    destination = image_root / ('local_text_' + binding_sha[:12])
    manifest_path = destination / 'manifest.json'
    if manifest_path.exists():
        existing = load_json(manifest_path)
        if existing['binding_sha256'] != binding_sha:
            raise ValueError('已有叠字版本绑定不一致')
        if all(Path(x['path']).exists() and sha(x['path']) == x['image_sha256'] for x in existing['images']):
            return existing
        raise ValueError('已有叠字版本文件缺失或变化，保留证据并停止，不能静默覆盖')
    result = {'job_id': job_id, 'category_id': 'business_ktv', 'binding_sha256': binding_sha,
              'directory': str(destination), 'status': 'awaiting_vision_text', 'api_requests': 0,
              'phone': phones[0], 'service_words': words, 'policy': policy, 'images': []}
    for row in source_rows:
        index = row['index']; group, position = (index-1)//3+1, (index-1)%3+1
        target = destination / f'group_{group:02}' / f'{position:02}.png'
        validation = apply_overlays(Path(row['path']), target, phones[0], 'cover', group, position, words,
            category_id='business_ktv', overlay_profile=policy['profile'],
            structure_version='business_ktv_independent_photos_v1', generation_mode='local_text_from_audited_raw',
            generation_target_id=f'{job_id}:{index}', delivery_target_id=f'{job_id}:text:{index}')
        validation.update(status='awaiting_vision_text', approved=False, manual_visual_approval=False,
            production_approved=False, source_status=row['status'], source_path=row['path'],
            source_image_sha256=row['audit']['image_sha256'], source_audit=row['audit'],
            note='本地叠字后仍须视觉模型实际核对文字与遮挡；原图淘汰结论不能因叠字被撤销。')
        atomic_json(target.with_suffix('.validation.json'), validation)
        result['images'].append({'index': index, 'group': group, 'position': position, 'path': str(target),
            'image_sha256': validation['image_sha256'], 'source_image_sha256': row['audit']['image_sha256'],
            'source_status': row['status'], 'status': 'awaiting_vision_text', 'approved': False})
    atomic_json(manifest_path, result)
    atomic_json(base / 'runs' / job_id / 'local_text_latest.json', {'path': str(manifest_path)})
    return result
