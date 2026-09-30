"""Fail-closed visual audit contract. Mock evidence is never real approval."""
import math
from dataclasses import dataclass, asdict
from typing import Protocol
import json
from pathlib import Path

CHECKS = ('空间结构', '家具结构', '桌椅比例', '酒瓶', '杯子', '水果', '冰桶', '人物', '手', '脸',
          '镜子', '玻璃', '反射', '灯光', '文字', '透视', '重复物体', '融合物体', '悬浮物体', '材质', '构图', '真实手机摄影感')
SCORES = ('realism_score', 'ai_artifact_score', 'scene_score', 'physics_score', 'camera_score', 'lighting_score', 'detail_score')


class ImageAuditor(Protocol):
    def review(self, path, record, fingerprint) -> dict: ...


@dataclass
class Scores:
    realism_score: float
    ai_artifact_score: float  # 0=no artifacts, 100=severe artifacts
    scene_score: float
    physics_score: float
    camera_score: float
    lighting_score: float
    detail_score: float

    def total(self):
        values = asdict(self)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100 for v in values.values()):
            raise ValueError('审核分数必须是0—100有限数值')
        return round(self.realism_score*.30 + (100-self.ai_artifact_score)*.20 + self.scene_score*.10
                     + self.physics_score*.15 + self.camera_score*.10 + self.lighting_score*.075 + self.detail_score*.075, 2)


def evaluate(evidence, rules):
    if set(evidence['checks']) != set(CHECKS):
        raise ValueError('审核必须覆盖全部检查项，未出现物体标记not_applicable')
    if any(v not in ('pass', 'fail', 'severe', 'not_applicable', 'unknown') for v in evidence['checks'].values()):
        raise ValueError('不支持的审核检查结果')
    if evidence.get('source') not in ('mock', 'human', 'vision') or not evidence.get('image_sha256'):
        raise ValueError('缺少审核来源或图片SHA绑定')
    scores = Scores(**{k: evidence[k] for k in SCORES})
    total = scores.total()
    severe = [k for k, v in evidence['checks'].items() if v == 'severe']
    reasons = list(evidence.get('failure_reasons', []))
    if severe:
        reasons += ['严重错误：' + '、'.join(severe)]
    decision = 'approved'
    if (severe or total < rules['reject_below'] or scores.ai_artifact_score > rules['max_artifact_score']
            or scores.realism_score < rules['min_realism'] or scores.physics_score < rules['min_physics']):
        decision = 'rejected'
    elif total < rules['approve_at'] or 'unknown' in evidence['checks'].values() or 'fail' in evidence['checks'].values():
        decision = 'rejected'
    return {**evidence, 'total_score': total, 'decision': decision, 'failure_reasons': reasons,
            'success_reasons': list(evidence.get('success_reasons', [])),
            'production_approved': decision == 'approved' and evidence['source'] == 'vision'}


class VisionPending(RuntimeError):
    """The active Codex vision reviewer must read pixels and supply bound evidence."""


class CodexVisionAuditor:
    capability = 'actual_image_vision'

    def __init__(self, session):
        if not session or len(session) < 8:
            raise ValueError('缺少本次实际看图审核会话，不能启用API')
        self.session = session

    def review(self, path, record, fingerprint):
        inbox = Path(path).parent.parent/'vision'
        inbox.mkdir(parents=True, exist_ok=True)
        from tools.category_image_production import atomic_json
        request = {'image_path': str(path), 'image_sha256': fingerprint['file_sha256'], 'index': record['index'],
                   'job_id': Path(path).parent.parent.name, 'vision_session': self.session,
                   'required_checks': list(CHECKS), 'require_actual_pixels': True,
                   'instruction': 'Codex视觉模型必须读取该图片及本批对照图，填写逐项可见证据，不根据prompt或参数估分。'}
        atomic_json(inbox/f"{record['index']:06d}.request.json", request)
        result = inbox/f"{record['index']:06d}.review.json"
        if not result.exists():
            raise VisionPending('等待当前Codex视觉模型读取实际图片')
        evidence = json.loads(result.read_text(encoding='utf-8'))
        if any(evidence.get(k) != request[k] for k in ('job_id','vision_session','image_sha256','index')):
            raise ValueError('视觉证据不属于当前任务/图片/审核会话')
        if (evidence.get('source') != 'vision' or evidence.get('pixels_read') is not True
                or not evidence.get('reviewer_model') or not evidence.get('reviewed_at')):
            raise ValueError('必须是真实视觉模型看图证据')
        observations = evidence.get('observations', {})
        if set(observations) != set(CHECKS) or any(not isinstance(v,str) or len(v.strip()) < 3 for v in observations.values()):
            raise ValueError('必须逐项给出图像观察证据')
        if not evidence.get('structural_description') or not isinstance(evidence.get('visual_comparisons'), list):
            raise ValueError('缺少实际空间结构和图像对比记录')
        for key in ('空间结构','家具结构','透视','灯光','材质','构图','真实手机摄影感'):
            if evidence.get('checks', {}).get(key) == 'not_applicable':
                raise ValueError('核心场景检查不得标记不适用')
        return evidence


class MockAuditor:
    def review(self, path, record, fingerprint):
        number = record['index']
        score = 72 if number % 5 == 0 else 86 + number % 9
        checks = {k: 'pass' for k in CHECKS}
        for key in ('人物', '手', '脸'):
            checks[key] = 'not_applicable'
        if record['scene']['ROOM_TYPE'] in ('KTV大厅', 'KTV走廊'):
            for key in ('桌椅比例', '酒瓶', '杯子', '水果', '冰桶'):
                checks[key] = 'not_applicable'
        severe = number % 7 == 0
        if severe:
            checks['融合物体'] = 'severe'
        return {**{k: score for k in SCORES}, 'ai_artifact_score': 100-score,
                'source': 'mock', 'image_sha256': fingerprint['file_sha256'], 'checks': checks,
                'failure_reasons': ['模拟物体融合'] if severe else (['模拟材质与手机感不足'] if score < 80 else []),
                'success_reasons': ['模拟空间与手机机位合理'] if score >= 80 and not severe else []}
