import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from tools import business_ktv as plugin
from tools.business_ktv.auditor import CHECKS, SCORES, MockAuditor, evaluate
from tools.business_ktv.diversity import DiversityAuditor, plan_batch
from tools.business_ktv.scene import initial_strategy, improve, STRUCTURAL
from tools.iteration_engine import IterationEngine, MockGenerator

ROOT = Path(__file__).resolve().parents[1]


class BusinessKtvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = json.loads((ROOT/'configs/business_ktv/scene_library.json').read_text(encoding='utf-8'))

    def engine(self, generator=None, auditor=None):
        return IterationEngine(self.root, copy.deepcopy(self.config), plugin, generator, auditor)

    def test_end_to_end(self):
        e = self.engine(); e.create(16); s = e.run()
        self.assertEqual(s['status'], 'completed')
        self.assertEqual(s['request_count'], 16)
        self.assertEqual(s['generated_images'], 16)
        self.assertEqual(s['strategy_version'], 3)
        self.assertEqual(len(s['rounds']), 2)
        self.assertGreater(s['success_count'], 0)
        self.assertGreater(s['failure_count'], 0)
        self.assertTrue(list((self.root/'output/business_ktv/mock/best').glob('*/*.png')))
        self.assertTrue((e.base/'records.sqlite3').exists())
        for row in s['records']:
            self.assertEqual(set(row['audit']['checks']), set(CHECKS))
            self.assertFalse(row['audit']['production_approved'])
            for field in ('diversity_score','similarity_score','closest_image','duplicate_reason'):
                self.assertIn(field, row['audit'])

    def test_resume_without_duplicate_generation(self):
        e=self.engine(); e.create(8); s=e.run(max_completed=3)
        paths={r['path']:Path(r['path']).read_bytes() for r in s['records'][:3]}
        e=self.engine(); e.resume(); s=e.run()
        self.assertEqual(s['request_count'], 8)
        self.assertEqual(s['status'], 'completed')
        for path, data in paths.items(): self.assertEqual(Path(path).read_bytes(), data)

    def test_completed_continue_does_not_generate(self):
        e=self.engine(); e.create(1); e.run()
        e=self.engine(); e.resume()
        with patch.object(e.generator, 'generate', side_effect=AssertionError('must not generate')):
            self.assertEqual(e.run()['status'],'completed')

    def test_retry_limit_and_key_rotation(self):
        class Flaky(MockGenerator):
            def generate(self, row, slot):
                if row['index']==1 and row['attempts']<3: raise TimeoutError('timeout')
                return super().generate(row,slot)
        e=self.engine(Flaky());e.create(3);s=e.run()
        self.assertEqual(s['request_count'],5)
        self.assertEqual(s['records'][0]['attempts'],3)
        self.assertEqual(s['key_stats']['mock-slot-2']['requests'],1)

    def test_total_budget_hard_stop(self):
        class Fail(MockGenerator):
            def generate(self,row,slot): raise TimeoutError('timeout')
        e=self.engine(Fail());e.create(1);s=e.run()
        self.assertEqual(s['status'],'budget_exhausted')
        self.assertEqual(s['request_count'],2)
        e=self.engine(Fail());e.resume();s=e.run()
        self.assertEqual(s['request_count'],2)

    def test_consecutive_errors_checkpoint(self):
        class Fail(MockGenerator):
            def generate(self,row,slot): raise TimeoutError('timeout')
        e=self.engine(Fail());e.create(8);s=e.run()
        self.assertEqual(s['status'],'circuit_open')
        self.assertEqual(s['request_count'],3)
        self.assertTrue(e._checkpoint().exists())

    def test_local_error_skips_image(self):
        class FailOne(MockGenerator):
            def generate(self,row,slot):
                if row['index']==1: raise ValueError('bad image')
                return super().generate(row,slot)
        e=self.engine(FailOne());e.create(3);s=e.run()
        self.assertEqual(s['status'],'completed')
        self.assertEqual(s['generated_images'],2)

    def test_audit_failure_resumes_without_api(self):
        class Broken(MockAuditor):
            def review(self,*args): raise ValueError('invalid audit')
        e=self.engine(auditor=Broken());e.create(2);s=e.run()
        self.assertEqual(s['status'],'audit_blocked')
        e=self.engine();e.resume();s=e.run()
        self.assertEqual(s['request_count'],2)

    def test_unknown_outcome_is_not_reissued(self):
        e=self.engine();e.create(2);e._plan_round()
        e.state['records'][0].update(status='requesting',attempts=1)
        e.state['request_count']=1;e._save()
        e=self.engine();e.resume();s=e.run()
        self.assertEqual(s['request_count'],2)
        self.assertEqual(s['records'][0]['status'],'failed')

    def test_safe_stop_and_lock(self):
        e=self.engine();e.create(2);(e.base/'STOP').write_text('stop')
        self.assertEqual(e.run()['status'],'stopped')
        self.assertEqual(e.state['request_count'],0)
        self.assertFalse((e.base/'production/generation.lock').exists())

    def test_no_overwrite_unfinished_task(self):
        e=self.engine();e.create(8)
        with self.assertRaises(ValueError): self.engine().create(8)

    def test_real_api_is_blocked(self):
        self.config['backend']='api'
        with self.assertRaisesRegex(ValueError,'视觉模型'): self.engine()

    def test_invalid_count(self):
        with self.assertRaises(ValueError): self.engine().create(0)

    def test_frozen_config_on_resume(self):
        e=self.engine();e.create(2);e.run(max_completed=1)
        self.config['variables']['ROOM_STYLE']=['changed']
        e=self.engine();e.resume()
        self.assertNotEqual(e.config['variables']['ROOM_STYLE'],['changed'])

    def test_batch_structural_differences_and_allocation(self):
        scenes=plan_batch(self.config,initial_strategy(self.config),8,42)
        self.assertEqual([s['mode'] for s in scenes].count('inherit'),4)
        self.assertEqual([s['mode'] for s in scenes].count('explore'),2)
        self.assertEqual([s['mode'] for s in scenes].count('experiment'),2)
        for i,s in enumerate(scenes):
            self.assertTrue(2<=len(s['imperfections'])<=4)
            for t in scenes[:i]: self.assertGreaterEqual(sum(s[k]!=t[k] for k in STRUCTURAL),3)
        self.assertEqual(scenes,plan_batch(self.config,initial_strategy(self.config),8,42))

    def test_public_area_constraints(self):
        scenes=plan_batch(self.config,initial_strategy(self.config),80,19)
        public=[s for s in scenes if s['ROOM_TYPE'] in ('KTV大厅','KTV走廊')]
        self.assertTrue(public)
        for s in public:
            self.assertEqual(s['TABLE_STATE'],'不适用')
            self.assertEqual(s['TABLE'],'无酒水茶几')

    def evidence(self):
        return {**{k:95 for k in SCORES},'ai_artifact_score':5,'source':'mock','image_sha256':'fixture',
                'checks':{k:'pass' for k in CHECKS},'failure_reasons':[],'success_reasons':['真实规律']}

    def test_severe_errors_reject_high_total(self):
        evidence=self.evidence();evidence['checks']['手']='severe'
        self.assertEqual(evaluate(evidence,self.config['audit'])['decision'],'rejected')

    def test_realism_hard_gate(self):
        evidence=self.evidence();evidence['realism_score']=80
        audit=evaluate(evidence,self.config['audit'])
        self.assertGreater(audit['total_score'],85)
        self.assertEqual(audit['decision'],'rejected')

    def test_score_validation(self):
        for value in (float('nan'),101,-1,True):
            evidence=self.evidence();evidence['realism_score']=value
            with self.assertRaises(ValueError):evaluate(evidence,self.config['audit'])
        evidence=self.evidence();evidence['checks'].pop('手')
        with self.assertRaises(ValueError):evaluate(evidence,self.config['audit'])

    def test_actual_pixels_exact_and_recolored_duplicate(self):
        e=self.engine();e.create(1);s=e.run();path=Path(s['records'][0]['path'])
        copy_path=self.root/'copy.png';copy_path.write_bytes(path.read_bytes())
        result=DiversityAuditor().inspect(copy_path,[path],self.config['diversity'])
        self.assertTrue(result['diversity_rejected']);self.assertEqual(result['similarity_score'],100)
        with Image.open(path) as image:
            image.convert('L').convert('RGB').save(copy_path)
        self.assertTrue(DiversityAuditor().inspect(copy_path,[path],self.config['diversity'])['diversity_rejected'])

    def test_duplicate_rejects_and_no_extra_requests(self):
        class Duplicate(MockGenerator):
            def generate(self,row,slot):
                stable=copy.deepcopy(row);stable['scene']['seed']=42
                return super().generate(stable,slot)
        e=self.engine(Duplicate());e.create(3);s=e.run()
        self.assertEqual(s['request_count'],3)
        self.assertEqual(s['records'][1]['status'],'rejected')
        self.assertTrue(s['records'][1]['replan_required'])
        self.assertEqual(s['records'][2]['replanned_from'],2)
        self.assertTrue(s['records'][2]['replan_history'])

    def test_active_lock_blocks_resume_and_create(self):
        from tools.category_image_production import acquire_lock
        e=self.engine();e.create(2)
        lock=acquire_lock(e.base,'running')
        try:
            with self.assertRaises(RuntimeError):self.engine().resume()
            with self.assertRaises(RuntimeError):self.engine().create(2)
        finally:lock.unlink()

    def test_missing_history_does_not_pass_diversity(self):
        e=self.engine();e.create(1);s=e.run()
        with self.assertRaises(FileNotFoundError):
            DiversityAuditor().inspect(Path(s['records'][0]['path']),[self.root/'missing.png'],self.config['diversity'])

    def test_api_cli_no_network(self):
        from tools.business_ktv.cli import command
        from argparse import Namespace
        with patch('tools.business_ktv.cli.ROOT',ROOT):
            self.assertEqual(command(Namespace(backend='api')),2)

    def test_compare_historical_accepted_and_best(self):
        e=self.engine();e.create(2);s=e.run()
        old=s['records'][0]['path']
        class DuplicateHistory(MockGenerator):
            def generate(self,row,slot):return Path(old).read_bytes()
        e=self.engine(DuplicateHistory());e.create(1,seed=81);s=e.run()
        self.assertEqual(s['records'][0]['status'],'rejected')
        self.assertGreaterEqual(s['records'][0]['audit']['compared_images'],1)

    def test_five_round_diagnosis_no_scene_cloning(self):
        e=self.engine();e.create(8);s=e.run();rows=s['records']
        strategy=initial_strategy(self.config);strategy['best_realism']=100
        for _ in range(5):strategy,_,diagnosis=improve(strategy,rows,self.config,[rows]*4)
        self.assertIsNotNone(diagnosis)
        self.assertEqual(strategy['diagnosis_count'],1)
        for key in ('ROOM_TYPE','LAYOUT','SOFA','TABLE','CAMERA_POSITION'):
            self.assertEqual(set(strategy['weights'][key].values()),{1.0})
        self.assertTrue(all(.3<=v<=3 for w in strategy['weights'].values() for v in w.values()))

    def test_new_task_retains_verified_rules(self):
        e=self.engine();e.create(2);s=e.run();previous=copy.deepcopy(s['strategy'])
        e=self.engine();s=e.create(2,seed=29)
        self.assertEqual(s['strategy'],previous)

    def test_continue_frozen_key_slot_counts(self):
        e=self.engine();e.create(2);e._plan_round()
        row=e.state['records'][0]
        row.update(status='requesting',attempts=1,key_slot='mock-slot-1')
        e.state['request_count']=1
        e.state['key_stats']={'mock-slot-1':{'requests':1,'success':0,'failed':0}}
        e._save()
        e=self.engine();e.resume();s=e.run()
        self.assertEqual(s['key_stats']['mock-slot-1']['failed'],1)
        self.assertEqual(s['failure_count'],1)


if __name__=='__main__': unittest.main()
