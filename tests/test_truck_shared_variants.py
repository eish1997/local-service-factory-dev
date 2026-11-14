"""Offline checks for new truck tasks; no API calls or production files."""
import copy
import unittest
from tools import task_library as lib, variable_catalog as vc
from tools.task_groups import build_group
from tools import truck_shared_variants as variants


class TruckSharedVariantsTests(unittest.TestCase):
    def catalog(self):
        data=copy.deepcopy(vc.load('truck_rescue'))
        ids={d['id'] for d in data['dimensions']}
        data['dimensions'] += [d for d in vc.defaults('truck_rescue')['dimensions'] if d['id'] not in ids]
        return data

    def test_heavy_share_and_body_coverage(self):
        token=vc.CURRENT.set({'category':'truck_rescue','catalog':self.catalog(),'seed':'1401','revision':1})
        try:
            choices=[variants.choose(i,1,True) for i in range(1400,1450)]
        finally: vc.CURRENT.reset(token)
        self.assertEqual(sum(c['heavy'] for c in choices),40)
        pool=next(d for d in self.catalog()['dimensions'] if d['source']=='HEAVY_VEHICLES')
        self.assertEqual({c['vehicle'] for c in choices if c['heavy']},{o['value'] for o in pool['options'] if o['enabled']})

    def test_shared_prompts_freeze_capture_and_safe_events(self):
        catalog=self.catalog();config=lib.business_config('truck_rescue')
        for seed in range(1400,1405):
            rows=build_group('truck_rescue',seed,'13800138000',catalog,config)
            self.assertEqual(rows,build_group('truck_rescue',seed,'13800138000',catalog,config))
            self.assertEqual(len(rows),7)
            for row in rows:
                prompt=row['prompt']
                if '本次指定摄影设备：' in prompt:
                    self.assertNotIn('手机成像：',prompt)
                    self.assertNotIn('随手拍与拍摄失误变量：',prompt)
                else:
                    self.assertIn('手机成像：',prompt)
                    self.assertIn('背景生活元素：',prompt)
                    self.assertIn('随手拍与拍摄失误变量：',prompt)
                    self.assertIn('本张最终照片后期变量：',prompt)
                if row['kind']=='cover': self.assertIn('13800138000',prompt)
                else: self.assertNotIn('13800138000',prompt)
                if '车辆：' in prompt and '重型' in prompt.split('车辆：',1)[1].split('；地点',1)[0]:
                    if row['service_role']=='货车刹车故障':
                        self.assertNotIn('检查液位',prompt)
                        self.assertNotIn('检查轮端制动软管',prompt)

    def test_old_catalog_does_not_enable_new_variables(self):
        old=copy.deepcopy(vc.load('truck_rescue'))
        old['dimensions']=[d for d in old['dimensions'] if d.get('binding',{}).get('module')!='tools.truck_shared_variants']
        rows=build_group('truck_rescue',1401,'13800138000',old,lib.business_config('truck_rescue'))
        self.assertFalse(any('手机成像：' in r['prompt'] for r in rows))


if __name__=='__main__': unittest.main()
