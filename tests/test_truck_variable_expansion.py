"""Exercise actual vehicle/action/tool phases, without API or batch writes."""
import copy
import unittest
from tools import variable_catalog as vc
from tools import truck_shared_variants as shared
from tools import truck_scene_diversity_v3 as scene


class TruckVariableExpansionTests(unittest.TestCase):
    def test_active_pool_counts_and_uniqueness(self):
        active=[d for d in vc.load('truck_rescue')['dimensions'] if d.get('status')=='active']
        below=[d['source'] for d in active if len(d['options'])<10]
        self.assertEqual(below,['HANDHELD_ROLL'])
        for d in active:
            values=[vc.uid(o['value']) for o in d['options']]
            self.assertEqual(len(values),len(set(values)),d['source'])

    def test_each_action_phase_preserves_vehicle_compatibility(self):
        catalog=vc.load('truck_rescue')
        for d in catalog['dimensions']:
            if d.get('binding',{}).get('name')!='EVENTS':continue
            role=d['binding']['dictkey']
            for option in d['options']:
                ctx=vc.CURRENT.set({'category':'truck_rescue','catalog':catalog,'seed':'1401','revision':catalog['revision']})
                forced=vc.FORCE.set({d['id']:option['id']})
                try:
                    original=scene.detail_variant(role,374)
                    prompt=scene.detail_positive_prompt(role,role,original,'detail')
                    row={'generation_kind':'detail','service_role':role,'scene':copy.deepcopy(original),
                         'positive_prompt':prompt,'negative_prompt':'无品牌和可读车牌'}
                    actual=shared.enhance_rows([row],1401)[0]
                finally:
                    vc.FORCE.reset(forced);vc.CURRENT.reset(ctx)
                event=option['value'];s=actual['scene'];p=actual['prompt']
                self.assertIn(event[4],p)
                self.assertIn(event[5],p)
                self.assertEqual(s['brake_system'],event[3])
                self.assertEqual(s['event_id'],event[0])
                if '挂车' in event[4]:self.assertIn('半挂',s['vehicle'])
                if '未连接挂车' in event[1]:self.assertIn('未连接挂车',s['vehicle'])
                if '自卸' in event[1]:self.assertIn('自卸',s['vehicle'])
                if role=='货车刹车故障' and s['shared_variants']['heavy']:
                    self.assertEqual(s['brake_system'],'air')
                    self.assertNotIn('液压制动系统',s['vehicle'])


if __name__=='__main__':unittest.main()
