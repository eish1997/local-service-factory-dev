"""Physical prompt contracts; offline checks do not prove image correctness."""
import copy
import unittest
from tools import variable_catalog as vc,truck_shared_variants as shared,truck_scene_diversity_v3 as scene
from tools import task_library as lib
from tools.task_groups import build_group


class TruckVehicleGeometryTests(unittest.TestCase):
    def test_engine_phases_have_one_cab_state(self):
        catalog=vc.load('truck_rescue')
        dim=next(d for d in catalog['dimensions'] if d['source']=='EVENTS.货车发动机故障')
        tilted=0
        for option in dim['options']:
            ctx=vc.CURRENT.set({'category':'truck_rescue','catalog':catalog,'seed':'1401','revision':catalog['revision']})
            force=vc.FORCE.set({dim['id']:option['id']})
            try:
                original=scene.detail_variant('货车发动机故障',374)
                row={'generation_kind':'detail','service_role':'货车发动机故障','scene':copy.deepcopy(original),
                     'positive_prompt':scene.detail_positive_prompt('货车发动机故障','engine',original,'detail'),'negative_prompt':'无品牌'}
                result=shared.enhance_rows([row],1401)[0]
            finally:vc.FORCE.reset(force);vc.CURRENT.reset(ctx)
            state=result['scene']['vehicle_geometry']['cab_state']
            prompt=result['positive_prompt']
            self.assertNotIn('发动机检修只在驾驶室翻起',prompt)
            if state=='tilted':
                tilted+=1
                self.assertIn('发动机留在原车架上',prompt)
                self.assertIn('同一刚性壳体共同旋转',prompt)
                self.assertIn('前部下方铰接点',prompt)
                self.assertNotIn('驾驶室正常落位锁止',result['scene']['vehicle'])
            else:
                self.assertIn('驾驶室正常落位锁止',result['scene']['vehicle'])
                self.assertNotIn('驾驶室翻起',result['scene']['vehicle'])
                self.assertNotIn('翻起',result['scene']['action'])
        self.assertEqual(tilted,2)

    def test_axles_are_bound_to_body_type(self):
        for vehicle,marker in [('6×4重型牵引车，连接半挂车','三轴半挂车'),
                               ('空载8×4重型自卸货车','前两轴与后两轴'),
                               ('6×4重型牵引车，未连接挂车','鞍座可见'),
                               ('重型冷藏载货车','三轴6×4平头重型载货'),
                               ('轻型厢式货车','普通两轴')]:
            prompt=shared.vehicle_geometry(vehicle,'轻型' not in vehicle,'closed')
            self.assertIn(marker,prompt)
            self.assertIn('轮毂和轮胎同心',prompt)
            self.assertIn('不能为塞进招牌和叠字区域把全车压缩变形',prompt)

    def test_other_services_do_not_request_cab_tilting(self):
        rows=build_group('truck_rescue',1401,'13800138000',vc.load('truck_rescue'),lib.business_config('truck_rescue'))
        for row in rows:
            if row['service_role']=='货车发动机故障':continue
            self.assertIn('本次不翻转驾驶室',row['prompt'])
            self.assertNotIn('发动机检修只在驾驶室翻起',row['prompt'])
        self.assertIn('驾驶室正常落位锁止',next(o['value']['action'] for d in vc.load('truck_rescue')['dimensions'] if d['source']=='COVER_EVENTS' for o in d['options'] if o['value']['id']=='cover_engine'))


if __name__=='__main__':unittest.main()
