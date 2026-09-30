"""Reusable bounded iteration orchestration built on the existing factory primitives.

API details remain in existing factory functions; adapters supply licensed calls.
Checkpoint is authoritative; SQLite, JSONL events and reports are derived evidence.
"""
from __future__ import annotations
import copy
from tools import variable_catalog
import hashlib
import io
import json
import random
import shutil
import sqlite3
import threading
import uuid
from contextlib import closing
from functools import wraps
from pathlib import Path

from PIL import Image, ImageDraw
from group_production import save_generated_image
from tools.category_image_production import (atomic_json, load_json, acquire_lock, append_event,
                                             reserve_request, classify_request_error, now_iso)
from tools.project_inventory import image_fingerprint
from tools.business_ktv.auditor import VisionPending


def locked_state(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        lock = acquire_lock(self.base, 'checkpoint-control')
        try:
            return method(self, *args, **kwargs)
        finally:
            lock.unlink(missing_ok=True)
    return guarded


class MockGenerator:
    backend = 'mock'
    model = 'mock-geometric-fixture-v1'
    key_slots = ['mock-slot-1', 'mock-slot-2']

    def generate(self, record, key_slot):
        rng = random.Random(record['scene']['seed'])
        image = Image.new('RGB', (192, 288), (25, 30, 35))
        draw = ImageDraw.Draw(image)
        for _ in range(25):
            x, y = rng.randrange(180), rng.randrange(275)
            draw.rectangle((x, y, min(191, x+rng.randrange(8, 70)), min(287, y+rng.randrange(8, 85))),
                           fill=tuple(rng.randrange(30, 240) for _ in range(3)))
        draw.text((5, 5), 'MOCK - NOT KTV PHOTO', fill='white')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()


class IterationEngine:
    def __init__(self, root, config, plugin, generator=None, auditor=None):
        self.root = Path(root).resolve()
        self.config = config
        self.plugin = plugin
        self.generator = generator or MockGenerator()
        self.auditor = auditor or plugin.MockAuditor()
        self.category = config['category_id']
        if not self.category.replace('_', '').isalnum():
            raise ValueError('非法类目标识')
        self.backend = config['backend']
        if self.backend not in ('mock','api') or self.generator.backend != self.backend:
            raise ValueError('正式生产被阻塞：须先接入并验证真实视觉模型审核及现有付费生产适配器。')
        if self.backend == 'api' and getattr(self.auditor,'capability',None) != 'actual_image_vision':
            raise ValueError('正式生产必须配备实际图像视觉模型审核')
        self.base = self.root / 'database' / self.category / self.backend
        self.base.mkdir(parents=True, exist_ok=True)
        self.event_lock = threading.Lock()
        self.state = None

    def _checkpoint(self):
        return self.base / 'runs' / self.state['job_id'] / 'checkpoint.json'

    def _save(self):
        self.state['updated_at'] = now_iso()
        atomic_json(self._checkpoint(), self.state)
        atomic_json(self.base / 'checkpoint.json', {'job_id': self.state['job_id'], 'path': str(self._checkpoint())})
        self._index()

    def _index(self):
        with closing(sqlite3.connect(self.base / 'records.sqlite3')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS images (job TEXT, idx INTEGER, status TEXT, path TEXT, payload TEXT, PRIMARY KEY(job,idx))')
            db.executemany('INSERT OR REPLACE INTO images VALUES (?,?,?,?,?)',
                          [(self.state['job_id'], r['index'], r['status'], r['path'], json.dumps(r, ensure_ascii=False)) for r in self.state['records']])

    def _event(self, kind, **extra):
        append_event(self._checkpoint().parent / 'events.jsonl', {
            'event': kind, 'job_id': self.state['job_id'], 'model': self.generator.model,
            'request_count': self.state['request_count'], 'success_requests': self.state['success_requests'],
            'failed_requests': self.state['failed_requests'], 'generated_images': self.state['generated_images'],
            **extra}, self.event_lock)

    def _history(self):
        database = self.base / 'records.sqlite3'
        if not database.exists():
            return []
        with closing(sqlite3.connect(database)) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM images WHERE status='accepted' AND job != ?", (self.state['job_id'],))]

    @locked_state
    def create(self, count, batch_size=8, seed=19, continuous=False):
        if not isinstance(count, int) or count <= 0 or batch_size <= 0:
            raise ValueError('张数、每轮张数必须为正整数')
        if self.backend == 'api' and (count > 15 or continuous):
            raise ValueError('当前Codex视觉接力仅开放最多15张有界图片；无人值守API批量尚未验收')
        latest = self.base / 'checkpoint.json'
        if self.category == 'business_ktv':
            self.config = copy.deepcopy(self.config)
            self.config['variable_catalog_snapshot'] = variable_catalog.load(self.category)
        strategy = self.plugin.initial_strategy(self.config)
        if latest.exists():
            previous = load_json(Path(load_json(latest)['path']))
            if previous['status'] not in ('completed', 'budget_exhausted'):
                raise ValueError('已有未完成任务，请使用 continue 恢复，不覆盖checkpoint。')
            if previous['config']['variables'] == self.config['variables']:
                strategy = previous['strategy']
        job = now_iso().replace(':', '').replace('+', '') + '-' + uuid.uuid4().hex[:8]
        safety = self.config['safety']
        if not 0 <= safety['max_retries'] <= 2 or safety['request_multiplier'] != 2:
            raise ValueError('安全边界不允许超过2次重试或改变2倍请求上限')
        self.state = {'schema_version': 1, 'category_id': self.category, 'backend': self.backend, 'job_id': job,
                      'status': 'ready', 'planned_images': count, 'max_requests': count*2,
                      'batch_size': batch_size, 'seed': seed, 'continuous': continuous,
                      'current_round': 0, 'current_image': 0, 'success_count': 0, 'failure_count': 0,
                      'request_count': 0, 'success_requests': 0, 'failed_requests': 0, 'generated_images': 0,
                      'consecutive_errors': 0, 'best_score': 0, 'recent_error': None,
                      'strategy': strategy, 'strategy_version': strategy['version'],
                      'rounds': [], 'records': [], 'config': self.config,
                      'authorization': {'source': 'explicit_production_command' if self.backend == 'api' else 'explicit_mock_command',
                                        'paid': self.backend == 'api', 'count': count},
                      'model': self.generator.model, 'key_slots': self.generator.key_slots, 'key_stats': {}}
        self._save()
        if self.backend == 'api':
            self.generator.bind(self.state, self._checkpoint().parent, create=True)
        self._event('created')
        return self.state

    @locked_state
    def resume(self):
        latest = self.base / 'checkpoint.json'
        if not latest.exists():
            raise ValueError('没有可继续的任务')
        path = Path(load_json(latest)['path']).resolve()
        if not path.is_relative_to(self.base / 'runs'):
            raise ValueError('checkpoint路径越界')
        self.state = load_json(path)
        if self.state['backend'] != self.backend or self.state['category_id'] != self.category:
            raise ValueError('checkpoint类目或后端不匹配')
        self.config = copy.deepcopy(self.state['config'])  # Freeze prompts/policy for resumption.
        if self.category == 'business_ktv' and 'variable_catalog_snapshot' not in self.config:
            self.config['_catalog_legacy'] = True
        if self.state['model'] != self.generator.model:
            raise ValueError('恢复不能静默更换模型')
        if self.backend == 'api':
            self.generator.bind(self.state, self._checkpoint().parent)
            if self.auditor.session != self.config['vision_session']:
                raise ValueError('恢复必须使用任务绑定的视觉审核会话')
        for row in self.state['records']:
            if row['status'] == 'requesting':
                if Path(row['path']).is_file():
                    row['status'] = 'generated'
                    self.state['generated_images'] += 1
                    self.state['success_requests'] += 1
                    counter = 'success'
                else:
                    # Unknown network outcome cannot safely be replayed.
                    row['status'] = 'failed'
                    row['error'] = '请求结果不确定，保留已占预算，不自动重发'
                    self.state['failed_requests'] += 1
                    counter = 'failed'
                if row.get('key_slot') in self.state['key_stats']:
                    self.state['key_stats'][row['key_slot']][counter] += 1
                self._event('recovered_uncertain_request', index=row['index'])
        self.state['consecutive_errors'] = 0
        self._save()
        return self.state

    def _plan_round(self):
        state = self.state
        start = len(state['records'])
        count = min(state['batch_size'], state['planned_images']-start)
        number = len(state['rounds'])+1
        previous = [r['scene'] for r in self._history()] + [r['scene'] for r in state['records']]
        scenes = self.plugin.plan_batch(self.config, state['strategy'], count, state['seed']+number*100003, previous)
        rows = []
        for i, scene in enumerate(scenes, start+1):
            text = self.plugin.prompt(scene, self.config, state['strategy'])
            path = self.root / 'output' / self.category / self.backend / state['job_id'] / 'raw' / f'{i:06d}.png'
            rows.append({'index': i, 'round': number, 'scene': scene, 'prompt': text,
                         'prompt_sha256': hashlib.sha256(text.encode()).hexdigest(), 'strategy_version': state['strategy']['version'],
                         'status': 'pending', 'attempts': 0, 'path': str(path), 'audit': None})
        state['records'].extend(rows)
        state['rounds'].append({'number': number, 'status': 'planned', 'indices': [r['index'] for r in rows]})
        state['current_round'] = number
        atomic_json(self.root / 'prompts' / self.category / state['job_id'] / f'round_{number:04d}.json',
                    {'backend': self.backend, 'strategy': state['strategy'], 'records': rows})
        self._save()

    def _generate(self, row):
        state = self.state
        while row['attempts'] < 1+self.config['safety']['max_retries']:
            if state['request_count'] >= state['max_requests']:
                state['status'] = 'budget_exhausted'
                return False
            slots = [s for s in self.generator.key_slots if s not in state.get('disabled_slots', [])]
            if not slots:
                state['status'] = 'circuit_open'
                return False
            slot = slots[(row['index']-1+row['attempts']) % len(slots)] if self.backend == 'api' else slots[row['attempts'] % len(slots)]
            stats = state['key_stats'].setdefault(slot, {'requests': 0, 'success': 0, 'failed': 0})
            state['request_count'] = reserve_request(state['request_count'], state['max_requests'])
            stats['requests'] += 1
            row['attempts'] += 1
            row['key_slot'] = slot  # Slot ID only; never store key material.
            row['status'] = 'requesting'
            self._save()  # Reserve durably before any external side effect.
            if self.backend == 'api':
                self.generator.prepare_request(state, row, slot)
            self._event('request_started', index=row['index'], key_slot=slot, attempt=row['attempts'])
            try:
                data = self.generator.generate(row, slot)
                save_generated_image(Path(row['path']), data)
                row['fingerprint'] = image_fingerprint(Path(row['path']))
                row['status'] = 'generated'
                stats['success'] += 1
                state['success_requests'] += 1
                state['generated_images'] += 1
                state['consecutive_errors'] = 0
                self._save()
                self._event('request_succeeded', index=row['index'], key_slot=slot)
                return True
            except Exception as error:
                # Exception types/classifications are safe to log; raw API messages may contain credentials.
                classification = classify_request_error(error)
                if classification == 'balance_exhausted':
                    state.setdefault('disabled_slots', []).append(slot)
                row['error'] = f'{type(error).__name__}:{classification or "local_error"}'
                row['status'] = 'pending' if classification in ('transient', 'balance_exhausted') and row['attempts'] < 3 else 'failed'
                state['recent_error'] = row['error']
                state['failed_requests'] += 1
                stats['failed'] += 1
                state['consecutive_errors'] += 1
                self._save()
                self._event('request_failed', index=row['index'], key_slot=slot, error=row['error'])
                if state['consecutive_errors'] >= self.config['safety']['consecutive_error_limit']:
                    state['status'] = 'circuit_open'
                    return False
                if row['status'] == 'failed':
                    return True
        row['status'] = 'failed'
        return True

    def _review(self, row):
        fp = image_fingerprint(Path(row['path']))
        evidence = self.auditor.review(Path(row['path']), row, fp)
        if evidence.get('image_sha256') != fp['file_sha256']:
            raise ValueError('审核证据与实际图片SHA不匹配')
        expected_source = 'mock' if self.backend == 'mock' else 'vision'
        if evidence.get('source') != expected_source:
            raise ValueError('审核来源与生成后端不匹配')
        audit = self.plugin.evaluate(evidence, self.config['audit'])
        history = self._history()
        current = [r for r in self.state['records'] if r['index'] != row['index'] and r.get('fingerprint')]
        candidates = [r['path'] for r in history+current]
        # Explicitly include historical best copies, including ones no longer in accepted index.
        candidates += [str(p) for p in (self.root/'output'/self.category/self.backend/'best').glob('*/*.png')]
        if self.backend == 'api':
            comparisons = evidence['visual_comparisons']
            compared = {x.get('image_sha256') for x in comparisons}
            required = {image_fingerprint(Path(p))['file_sha256'] for p in candidates}
            if not required.issubset(compared):
                raise ValueError('真实视觉审核缺少本批或历史图片结构对照')
            if any(not isinstance(x.get('similarity_score'),(int,float)) or not 0 <= x['similarity_score'] <= 100
                   or not x.get('reason') for x in comparisons):
                raise ValueError('视觉结构相似度证据不完整')
        diversity = self.plugin.DiversityAuditor().inspect(Path(row['path']), candidates, self.config['diversity'])
        audit.update(diversity)
        if self.backend == 'api' and evidence['visual_comparisons']:
            closest = max(evidence['visual_comparisons'], key=lambda x: x['similarity_score'])
            audit['visual_similarity_score'] = closest['similarity_score']
            if closest['similarity_score'] > diversity['similarity_score']:
                diversity['similarity_score'] = closest['similarity_score']
                diversity['diversity_score'] = 100-closest['similarity_score']
                diversity['closest_image'] = next((p for p in candidates if image_fingerprint(Path(p))['file_sha256']==closest['image_sha256']), None)
                audit.update(diversity)
            if closest['similarity_score'] >= self.config['diversity']['reject_similarity']:
                diversity['diversity_rejected'] = True
                diversity['duplicate_reason'] = '视觉结构高度相似：'+closest['reason']
                audit.update(diversity)
        if diversity['diversity_rejected']:
            audit['decision'] = 'rejected'
            audit['failure_reasons'].append(diversity['duplicate_reason'])
            row['replan_required'] = True
        audit['production_approved'] = self.backend == 'api' and audit['decision'] == 'approved'
        row['audit'] = audit
        row['fingerprint'] = fp
        row['status'] = 'accepted' if audit['decision'] == 'approved' else 'rejected'
        directory = Path(row['path']).parent.parent / row['status']
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row['path'], directory / Path(row['path']).name)
        atomic_json(Path(row['path']).with_suffix('.validation.json'), audit)
        if row.get('replan_required'):
            self._replan_next(row)

    def _replan_next(self, rejected):
        target = next((r for r in self.state['records'] if r['index'] > rejected['index'] and r['status'] == 'pending'), None)
        if target is None:
            rejected['replan_status'] = 'next_planned_round_or_next_explicit_task_only'
            return
        prior = [r['scene'] for r in self._history()+self.state['records']]
        old = {k: target[k] for k in ('scene', 'prompt', 'prompt_sha256')}
        seed = target['scene']['seed'] + 10000019 + rejected['index']
        scene = self.plugin.plan_batch(self.config, self.state['strategy'], 1, seed, prior)[0]
        scene['mode'] = 'explore'
        scene['exploration'] = True
        text = self.plugin.prompt(scene, self.config, self.state['strategy'])
        target.setdefault('replan_history', []).append(old)
        target.update(scene=scene, prompt=text, prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                      replanned_from=rejected['index'])
        rejected['replan_status'] = f"replanned_existing_slot_{target['index']}"
        atomic_json(self.root/'prompts'/self.category/self.state['job_id']/'replans'/f"{rejected['index']:06d}.json",
                    {'reason': rejected['audit']['duplicate_reason'], 'target': target})

    def _finish_round(self, batch, rows):
        past = [[r for r in self.state['records'] if r['round'] == b['number']] for b in self.state['rounds'][:-1]]
        strategy, winners, diagnosis = self.plugin.improve(self.state['strategy'], rows, self.config, past)
        for row in winners:
            target = self.root/'output'/self.category/self.backend/'best'/self.state['job_id']/Path(row['path']).name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(row['path'], target)
        batch.update(status='completed', winner_indices=[r['index'] for r in winners], diagnosis=diagnosis,
                     next_strategy=strategy, rejected=[r['index'] for r in rows if r['status'] == 'rejected'])
        self.state['strategy'] = strategy
        self.state['strategy_version'] = strategy['version']
        self.state['best_score'] = max(self.state['best_score'], max((r['audit']['realism_score'] for r in winners), default=0))
        self._save()
        atomic_json(self.root/'projects'/self.category/'preferences'/'history'/self.state['job_id']/f"round_{batch['number']:04d}.json", batch)
        self._event('round_completed', round=batch['number'], winners=batch['winner_indices'], diagnosis=diagnosis)

    def run(self, max_completed=None):
        if self.state is None:
            raise ValueError('先创建或恢复任务')
        lock = acquire_lock(self.base, self.state['job_id'])
        done = 0
        try:
            self.state = load_json(self._checkpoint())
            if self.state['status'] == 'completed':
                return self.state
            if self.backend == 'api':
                self.generator.bind(self.state, self._checkpoint().parent)
            self.state['status'] = 'running'
            while True:
                if (self.base/'STOP').exists():
                    self.state['status'] = 'stopped'
                    break
                if not self.state['rounds'] or self.state['rounds'][-1]['status'] == 'completed':
                    if len(self.state['records']) >= self.state['planned_images']:
                        self.state['status'] = 'completed'
                        break
                    self._plan_round()
                batch = self.state['rounds'][-1]
                rows = [r for r in self.state['records'] if r['round'] == batch['number']]
                for row in rows:
                    if row['status'] in ('accepted', 'rejected', 'failed'):
                        continue
                    if (self.base/'STOP').exists():
                        self.state['status'] = 'stopped'
                        return self.state
                    self.state['current_image'] = row['index']
                    if row['status'] == 'pending' and not self._generate(row):
                        return self.state
                    if row['status'] in ('generated', 'audit_error', 'awaiting_vision'):
                        try:
                            self._review(row)
                        except VisionPending:
                            row['status'] = 'awaiting_vision'
                            self._save()
                            continue
                        except Exception as error:
                            row['status'] = 'audit_error'
                            self.state['status'] = 'audit_blocked'
                            self.state['recent_error'] = type(error).__name__ + ':审核失败，恢复时仅重新审核'
                            self._event('audit_failed', index=row['index'], error=type(error).__name__)
                            return self.state
                    self.state['success_count'] = sum(r['status'] == 'accepted' for r in self.state['records'])
                    self.state['failure_count'] = sum(r['status'] in ('failed', 'rejected') for r in self.state['records'])
                    self._save()
                    self._event('image_completed', index=row['index'], status=row['status'])
                    done += 1
                    if max_completed is not None and done >= max_completed:
                        self.state['status'] = 'paused'
                        return self.state
                if any(r['status'] == 'awaiting_vision' for r in rows):
                    self.state['status'] = 'awaiting_vision'
                    return self.state
                self._finish_round(batch, rows)
        except KeyboardInterrupt:
            self.state['status'] = 'stopped'
            self.state['recent_error'] = '用户安全停止'
        except Exception as error:
            self.state['status'] = 'error'
            self.state['recent_error'] = type(error).__name__
            self._event('program_error', error=type(error).__name__)
            raise
        finally:
            try:
                self.state['success_count'] = sum(r['status'] == 'accepted' for r in self.state['records'])
                self.state['failure_count'] = sum(r['status'] in ('failed', 'rejected') for r in self.state['records'])
                self._save()
                self._report()
                if self.backend == 'api':
                    self.generator.finish(self.state)
            finally:
                lock.unlink(missing_ok=True)
        return self.state

    def _report(self):
        state = self.state
        atomic_json(self.root/'reports'/self.category/f"{state['job_id']}.json", {
            k: state[k] for k in ('job_id','backend','status','planned_images','max_requests','request_count',
                                  'success_requests','failed_requests','generated_images','success_count','failure_count',
                                  'best_score','strategy_version','key_stats','rounds','recent_error')})
