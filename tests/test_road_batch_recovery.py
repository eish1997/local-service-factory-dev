import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import factory
from tools.restore_road_batch import restore


class RoadBatchRecoveryTests(unittest.TestCase):
    def test_whole_group_needs_complete_manifest_not_old_photos(self):
        records = [{'group_index': 1240} for _ in range(5)]
        with patch.object(factory, '_category_sample_gate_range', return_value=(316, 3)), patch.object(factory, '_category_production_records', return_value=records), patch.object(factory, 'project_definition', return_value={'content_group': {'total_images': 5}}), patch.object(factory, '_category_require_registered_cover_approval', side_effect=RuntimeError('missing photos')):
            factory._category_sample_range('road_rescue', 1240, 1, scope='all')
            with self.assertRaises(RuntimeError):
                factory._category_sample_range('road_rescue', 1240, 1, scope='details')
            records.pop()
            with self.assertRaisesRegex(RuntimeError, '完整范围'):
                factory._category_sample_range('road_rescue', 1240, 1, scope='all')

    def test_restore_preserves_prompt_bytes_and_refuses_overwrite(self):
        source = factory.ROOT / 'projects/road_rescue/groups/schema_v3_5'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            schema = root / 'projects/road_rescue/groups/schema_v3_5'
            schema.mkdir(parents=True)
            registry = json.loads((source / 'registry.json').read_text(encoding='utf-8-sig'))
            first = registry['first_group_index']
            registry.update(created_groups=1, last_group_index=first)
            (schema / 'registry.json').write_text(json.dumps(registry), encoding='utf-8')
            for name in ('generation_manifest.jsonl', 'production_manifest.jsonl', 'group_manifest.jsonl'):
                with (source / name).open(encoding='utf-8-sig') as stream:
                    selected = []
                    for line in stream:
                        if json.loads(line)['group_index'] != first:
                            break
                        selected.append(line)
                (schema / name).write_text(''.join(selected), encoding='utf-8')
            config = root / 'configs/categories/road_rescue.json'
            config.parent.mkdir(parents=True)
            config.write_bytes((factory.ROOT / 'configs/categories/road_rescue.json').read_bytes())
            before = {p.name: p.read_bytes() for p in schema.iterdir()}
            result = restore(root)
            batch = Path(result['restored'])
            self.assertEqual((batch / 'prompts.jsonl').read_bytes(), before['generation_manifest.jsonl'])
            self.assertEqual(before, {p.name: p.read_bytes() for p in schema.iterdir()})
            with self.assertRaisesRegex(RuntimeError, 'overwrite'):
                restore(root)


if __name__ == '__main__':
    unittest.main()
