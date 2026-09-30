"""Batch structural planning and pixel-based comparisons, isolated per category."""
import math
from pathlib import Path
from PIL import Image, ImageOps, ImageFilter
from tools.project_inventory import image_fingerprint, hamming_hex
from .scene import sample


def plan_batch(config, strategy, count, seed, previous=()):
    # Largest remainder allocation: 8 => 4 inherit, 2 explore, 2 experiment.
    fractions = config['optimization']['allocation']
    quotas = {k: int(count*v) for k, v in fractions.items()}
    order = sorted(fractions, key=lambda k: count*fractions[k]-quotas[k], reverse=True)
    for k in order[:count-sum(quotas.values())]:
        quotas[k] += 1
    modes = [k for k, n in quotas.items() for _ in range(n)]
    import random
    random.Random(seed).shuffle(modes)
    scenes = []
    for i, mode in enumerate(modes):
        scene = sample(config, strategy, seed+i*1009, list(previous)+scenes, mode)
        scene['experiment'] = (strategy.get('focus') or ['物品密度与自然机位'])[0] if mode == 'experiment' else None
        scenes.append(scene)
    return scenes


def descriptor(path):
    # Grayscale edges intentionally ignore lighting hue and small prop changes.
    with Image.open(path) as source:
        gray = ImageOps.autocontrast(ImageOps.exif_transpose(source).convert('L').resize((128, 128)))
        edges = gray.filter(ImageFilter.FIND_EDGES).crop((3, 3, 125, 125)).resize((16, 16))
        vector = [float(x) for x in edges.tobytes()]
    norm = math.sqrt(sum(x*x for x in vector)) or 1
    return [x/norm for x in vector]


class DiversityAuditor:
    def inspect(self, path, candidates, rules):
        fp = image_fingerprint(Path(path))
        vector = descriptor(path)
        best, closest, reason = 0.0, None, ''
        compared = set()
        for candidate in candidates:
            other = Path(candidate)
            if not other.is_file():
                raise FileNotFoundError('历史对比图片缺失，不能跳过差异性审核')
            if other.resolve() == Path(path).resolve() or other.resolve() in compared:
                continue
            compared.add(other.resolve())
            other_fp = image_fingerprint(other)
            exact = fp['rgb_sha256'] == other_fp['rgb_sha256']
            phash = 1-hamming_hex(fp['scene_phash64'], other_fp['scene_phash64'])/64
            dhash = 1-hamming_hex(fp['scene_dhash256'], other_fp['scene_dhash256'])/256
            edge = sum(a*b for a, b in zip(vector, descriptor(other)))
            similarity = 100 if exact else 100*max(min(phash, dhash), edge if phash > .80 else 0)
            if closest is None or similarity > best:
                best, closest = similarity, str(other)
                reason = '像素完全重复' if exact else '灰度结构/边缘布局高度相似（忽略灯光色相）'
        rejected = best >= rules['reject_similarity'] or 100-best <= rules['min_diversity']
        return {'diversity_score': round(100-best, 2), 'similarity_score': round(best, 2),
                'closest_image': closest, 'duplicate_reason': reason if rejected else '',
                'diversity_rejected': rejected, 'compared_images': len(compared),
                'method': 'actual_pixels_phash_dhash_grayscale_edges_v1'}
