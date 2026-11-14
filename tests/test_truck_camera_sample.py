"""Camera binding uses isolated local tasks, not live generation."""
import copy
import unittest
import uuid
from unittest.mock import patch
from tools import task_library as lib,task_actions as actions,variable_catalog as vc


class TruckCameraSampleTests(unittest.TestCase):
    def test_professional_models_are_enabled_and_selected(self):
        from tools import truck_shared_variants as variants
        catalog=vc.load('truck_rescue')
        dimension=next(d for d in catalog['dimensions'] if d['source']=='CAPTURE_DEVICES')
        enabled=[o['value'] for o in dimension['options'] if o['enabled']]
        professional=[v for v in enabled if v['id'].startswith('professional_')]
        self.assertEqual(len(enabled),20)
        self.assertEqual(len(professional),10)
        ctx=vc.CURRENT.set({'category':'truck_rescue','catalog':catalog,'seed':'1401','revision':catalog['revision']})
        try: choices=[variants.choose(i,1,True) for i in range(1400,1420)]
        finally:vc.CURRENT.reset(ctx)
        self.assertEqual({c['device']['id'] for c in choices},{v['id'] for v in enabled})
        for choice in choices:
            if not choice['device']['id'].startswith('professional_'):continue
            instruction=variants.capture_instruction(choice)
            self.assertIn(choice['device']['name'].split(' / ')[0],instruction)
            self.assertNotIn('随手拍与拍摄失误变量：',instruction)
            self.assertIn('不宣称真实相机拍摄',instruction)

    def test_single_camera_is_frozen_without_changing_normal_pool(self):
        root=lib.ROOT/'.runtime'/('camera-test-'+uuid.uuid4().hex);root.mkdir()
        before=copy.deepcopy(vc.load('truck_rescue'))
        with patch.object(lib,'ROOT',root):
            b=lib.assemble({'category':'truck_rescue','count':1,'phone':'13800138000','seed':1401,'source':'agent'})
            request={'category':'truck_rescue','batch':b['id'],'group':1,'position':1,'request_id':'camera',
                     'variable_choices':{'CAPTURE_DEVICES':'professional_canon_r6_ii_50mm'}}
            sample=actions.prepare_replacement(request)
            snapshot=lib.read(lib.batch_dir('truck_rescue',sample['id'])/'snapshot.json')
            unit=lib.read(lib.batch_dir('truck_rescue',sample['id'])/'groups/0001.json')['units']
            self.assertEqual(len(unit),1)
            self.assertIn('EOS R6 Mark II',unit[0]['prompt'])
            self.assertNotIn('随手拍与拍摄失误变量：',unit[0]['prompt'])
            self.assertNotIn('手机成像：',unit[0]['prompt'])
            enabled=[o for d in snapshot['catalog']['dimensions'] if d['source']=='CAPTURE_DEVICES' for o in d['options'] if o['enabled']]
            self.assertEqual(len(enabled),1)
            self.assertEqual(actions.prepare_replacement(request)['id'],sample['id'])
            with self.assertRaises(ValueError):actions.prepare_replacement({**request,'variable_choices':{}})
        self.assertEqual(before,vc.load('truck_rescue'))


if __name__=='__main__':unittest.main()
