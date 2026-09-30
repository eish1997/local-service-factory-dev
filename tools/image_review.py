"""On-demand local review. Tool results never grant visual approval."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from tools import project_inventory as inventory


class ReviewSession:
    def __init__(self, records, output_root, report_root, approve_cover=None):
        self.root = Path(output_root).resolve()
        self.directory = Path(report_root) / (time.strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(4))
        self.directory.mkdir(parents=True, exist_ok=False)
        self.records = []
        self.approve_cover = approve_cover
        self.lock = threading.Lock()
        self.tool_state = {'status': 'not_run'}
        self.token = secrets.token_urlsafe(32)
        for record in records:
            path = Path(record['target']).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError('图片路径超出项目 output 目录')
            self.records.append({
                'id': len(self.records), 'path': path,
                'group': int(record['group_index']),
                'role': record['delivery_kind'], 'size': record['final_size'],
                'name': f"第{record['group_index']}组 / {path.name}",
                'viewed_sha256': None,
            })
        if not self.records:
            raise ValueError('所选范围没有交付目标')
        if len(self.records) > 1000:
            raise ValueError('单次验收最多1000张，请拆分范围')

    def state(self):
        rows = []
        for record in self.records:
            validation_path = record['path'].with_suffix('.validation.json')
            try:
                validation = inventory.load_json(validation_path)
                status = validation.get('status', 'needs_user_review')
            except (OSError, ValueError):
                status = 'missing_validation'
            rows.append({key: record[key] for key in ('id', 'group', 'role', 'name')} |
                        {'status': status, 'exists': record['path'].is_file()})
        return {'images': rows, 'tool': self.tool_state,
                'report_directory': str(self.directory)}

    def image_bytes(self, index):
        record = self.records[index]
        data = record['path'].read_bytes()
        record['viewed_sha256'] = hashlib.sha256(data).hexdigest()
        return data

    def run_tool(self):
        with self.lock:
            if self.tool_state['status'] == 'running':
                return
            self.tool_state = {'status': 'running', 'completed': 0, 'total': len(self.records)}
        started = time.monotonic()
        results, fingerprints, pairs = [], [], []
        try:
            for record in self.records:
                problems = []
                fp = None
                path = record['path']
                try:
                    fp = inventory.image_fingerprint(path, record['role'])
                    if f"{fp['width']}x{fp['height']}" != record['size']:
                        problems.append('尺寸与生产清单不一致')
                    validation = inventory.load_json(path.with_suffix('.validation.json'))
                    if validation.get('image_sha256') != fp['file_sha256']:
                        problems.append('图片与验收记录指纹不一致')
                    if not validation.get('postprocessed_locally'):
                        problems.append('缺少本地叠字完成记录')
                    fingerprints.append((record, fp))
                except (OSError, ValueError, inventory.InventoryError) as exc:
                    problems.append('缺图、损坏或缺少有效验收记录：' + str(exc))
                results.append({'id': record['id'], 'name': record['name'], 'problems': problems,
                                'fingerprint': fp})
                self.tool_state['completed'] = len(results)
            pair_count = 0
            for i, (left, a) in enumerate(fingerprints):
                for right, b in fingerprints[i + 1:]:
                    exact = a['rgb_sha256'] == b['rgb_sha256']
                    if not exact and left['role'] != right['role']:
                        continue
                    matched, phash, dhash = inventory._near_match({'fingerprint': a}, {'fingerprint': b})
                    if exact or matched:
                        pair_count += 1
                        if len(pairs) < 300:
                            pairs.append({'left': left['id'], 'right': right['id'],
                                          'kind': 'exact_duplicate' if exact else 'similar_candidate',
                                          'phash_distance': phash, 'dhash_distance': dhash})
            report = {
                'status': 'completed', 'completed': len(results), 'total': len(results),
                'elapsed_seconds': round(time.monotonic() - started, 2),
                'algorithm': 'existing_scene_phash64_dhash256_v1',
                'comparison_scope': '仅本次所选范围；同角色场景相似度，所有角色精确重复',
                'checks': results, 'pairs': pairs, 'pair_count': pair_count,
                'pairs_truncated': pair_count > len(pairs),
                'result': 'needs_attention' if pair_count or any(r['problems'] for r in results) else 'technical_checks_passed',
                'not_checked': ['中文错字及电话号码像素识别（未接入OCR）', '维修动作及物理合理性',
                                '未选范围及历史图库', '整体风格同质化的语义判断'],
                'visual_approval': False, 'api_called': False,
            }
            inventory.atomic_json(self.directory / f'tool_{time.time_ns()}.json', report)
            self.tool_state = report
        except Exception as exc:
            self.tool_state = {'status': 'failed', 'error': str(exc)}

    def decide(self, index, decision, note, viewed_sha256):
        if decision not in ('approved', 'needs_fix', 'rejected'):
            raise ValueError('不支持的验收结果')
        if not isinstance(note, str) or not note.strip() or len(note) > 2000:
            raise ValueError('请填写本次人工验收说明（最多2000字）')
        with self.lock:
            record = self.records[index]
            path = record['path']
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != record['viewed_sha256'] or actual != viewed_sha256:
                raise ValueError('图片尚未打开或已变更，请重新打开再验收')
            expected_size = tuple(map(int, record['size'].split('x')))
            if not inventory.valid_image(path, expected_size):
                raise ValueError('图片损坏或尺寸不符，不能登记人工结论')
            validation_path = path.with_suffix('.validation.json')
            previous = inventory.load_json(validation_path)
            if actual != previous.get('image_sha256'):
                raise ValueError('图片与原验收记录不一致，请先查明变更来源')
            if decision == 'approved' and not previous.get('postprocessed_locally'):
                raise ValueError('缺少本地叠字完成记录')
            event = {'image': str(path), 'image_sha256': actual, 'decision': decision,
                     'note': note, 'source': 'human', 'at': inventory.now_iso(), 'previous_validation': previous}
            event_path = self.directory / f'manual_{index}_{time.time_ns()}.json'
            inventory.atomic_json(event_path, event | {'applied': False})
            if decision == 'approved' and record['role'] == 'cover':
                if self.approve_cover is None:
                    raise ValueError('首图批准入口未配置')
                self.approve_cover(record, previous, note)
            else:
                updated = dict(previous)
                updated.update(status=decision, approved=decision == 'approved',
                               manual_visual_approval=decision == 'approved',
                               approval_note=note, reviewed_at=inventory.now_iso())
                if decision == 'approved':
                    updated['approved_at'] = inventory.now_iso()
                else:
                    updated.pop('approved_at', None)
                inventory.atomic_json(validation_path, updated)
            inventory.atomic_json(event_path, event | {'applied': True})


def serve(session, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            if content_type == 'image/png':
                self.send_header('X-Image-SHA256', hashlib.sha256(body).hexdigest())
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            return (self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}' and
                    parse_qs(urlparse(self.path).query).get('token') == [session.token])

        def do_GET(self):
            if not self.authorized():
                return self.send(403, {'error': '仅允许本地验收会话访问'})
            route = urlparse(self.path).path
            try:
                if route == '/':
                    page = Path(__file__).with_name('image_review.html').read_bytes()
                    return self.send(200, page, 'text/html; charset=utf-8')
                if route == '/state':
                    return self.send(200, session.state())
                if route.startswith('/image/'):
                    index = int(route.split('/')[-1])
                    if not 0 <= index < len(session.records):
                        raise ValueError('图片编号无效')
                    return self.send(200, session.image_bytes(index), 'image/png')
                return self.send(404, {'error': '未找到入口'})
            except (ValueError, OSError) as exc:
                return self.send(400, {'error': str(exc)})

        def do_POST(self):
            if not self.authorized() or self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                return self.send(403, {'error': '验收请求来源不符'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16000:
                    raise ValueError('请求大小无效')
                payload = json.loads(self.rfile.read(size))
                route = urlparse(self.path).path
                if route == '/tool':
                    threading.Thread(target=session.run_tool, daemon=True).start()
                    return self.send(202, {'started': True})
                if route == '/decision':
                    index = int(payload['id'])
                    if not 0 <= index < len(session.records) or payload.get('confirmed') is not True:
                        raise ValueError('请勾选人工检查确认')
                    session.decide(index, payload['decision'], payload['note'], payload.get('viewed_sha256'))
                    return self.send(200, {'saved': True})
                return self.send(404, {'error': '未找到入口'})
            except Exception as exc:
                return self.send(400, {'error': str(exc)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    return server
