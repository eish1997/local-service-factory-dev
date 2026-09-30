"""Bounded catalog and real prompt integration checks. No API calls or batches."""
import copy
import json
from pathlib import Path
import random
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import uuid
import unittest
from unittest.mock import patch
from tools import variable_catalog as vc
from tools.variable_preview import real_prompt, text_of


def custom(identifier='extra', value='墙角可见一小段正常磨损的水泥踢脚线'):
    return {'id':identifier,'name':'自定义'+identifier,'description':'测试用途','kind':'custom',
            'roles':['cover','detail'],'probability':1,'min_select':1,'max_select':1,
            'schema':{'type':'string'},'options':[{'id':identifier+'_one','name':'候选甲','value':value,
            'weight':1,'enabled':True,'conditions':[]}]}


class CatalogIntegration(unittest.TestCase):
    def test_disk_roundtrip_all_catalogs(self):
        for p in vc.projects(): vc.validate(json.loads(json.dumps(vc.defaults(p['id']),ensure_ascii=False)))

    def test_business_job_snapshot_and_legacy_resume(self):
        from tools.business_ktv.scene import sample,prompt,initial_strategy
        config=vc.read_json(vc.ROOT/'configs/business_ktv/scene_library.json')
        data=vc.defaults('business_ktv');extra=custom(value='门边墙角有自然磨损痕迹');extra['roles']=['detail'];data['dimensions'].append(extra)
        config['variable_catalog_snapshot']=data
        with patch.object(vc,'load',side_effect=AssertionError('must use job snapshot')):
            scene=sample(config,initial_strategy(config),501)
            text=prompt(scene,config,initial_strategy(config))
        self.assertIn(extra['options'][0]['value'],text)
        self.assertIn('variable_catalog',scene)
        del config['variable_catalog_snapshot'];config['_catalog_legacy']=True
        with patch.object(vc,'load',side_effect=AssertionError('legacy must not load new catalog')):
            scene=sample(config,initial_strategy(config),501)
            text=prompt(scene,config,initial_strategy(config))
        self.assertNotIn(extra['options'][0]['value'],text)

    def test_road_manifest_extension_uses_custom_without_rewriting_sources(self):
        from generate_road_rescue_v3_groups import _build_payloads
        data=vc.defaults('road_rescue');data['dimensions'].append(custom())
        with patch.object(vc,'load',return_value=data): schema,batch,summary=_build_payloads(1401,1)
        records=[json.loads(line) for line in batch['prompts.jsonl'].splitlines()]
        self.assertEqual(len(records),7)
        for row in records:
            self.assertIn(custom()['options'][0]['value'],row['prompt'])
            self.assertTrue(row.get('variable_catalog') or row['scene'].get('variable_catalog'))

    def test_all_registered_categories_new_type_and_candidate_reach_prompts(self):
        choices={'road_rescue':('LAYOUTS','cover'),'lock_service':('LOCK_SERVICE_COVER_VARIANTS','cover'),
                 'home_appliance_repair':('COVER_SIGN_STYLES','cover'),
                 'pipe_unclogging':('PIPE_CAMERAS','cover'),'pet_transport':('PET_ACTIONS','cover'),
                 'truck_rescue':('LOCATIONS','detail'),'ktv':('random_variables.酒水数量','cover'),
                 'business_ktv':('variables.CAMERA_POSITION','detail')}
        self.assertEqual(set(choices),{p['id'] for p in vc.projects()})
        for category,(source,role) in choices.items():
            with self.subTest(category=category):
                data=vc.defaults(category);marker='正常的浅灰墙面边缘，测试_'+category
                extension=custom(value=marker)
                if category=='business_ktv': extension['roles']=['detail']
                data['dimensions'].append(extension)
                dim=next(d for d in data['dimensions'] if d['source'].endswith(source))
                option=copy.deepcopy(dim['options'][0]);option.update(id='test_added',name='新增候选')
                if isinstance(option['value'],dict): option['value']['facade']+='，门口有普通水泥门槛'
                elif isinstance(option['value'],list): option['value'][-1]+='，边缘有水泥门槛'
                else: option['value']+='，边缘保留普通墙面'
                dim['options'].append(option)
                result=vc.preview(category,{'catalog':data,'role':role,'force':{dim['id']:option['id']}})
                self.assertEqual(len(result),3)
                for row in result:
                    self.assertIn(marker,row['prompt']);self.assertEqual(row['prompt'].count(marker),1)
                    self.assertTrue(any(s['option_id']=='test_added' for s in row['selected']))
                    self.assertFalse(row['api_called'])
                self.assertNotIn(marker,text_of(vc.preview(category,{'role':role})[0]))

    def test_preview_preserves_default_prompt_text(self):
        # Identical seeds retain established default sampling and original text.
        for category in ('road_rescue','lock_service','home_appliance_repair','pipe_unclogging','pet_transport','truck_rescue','ktv','business_ktv'):
            data=vc.defaults(category);ctx={'category':category,'catalog':data,'seed':'374' if category=='truck_rescue' else '1401'}
            for role in ('cover','detail'):
                with self.subTest(category=category,role=role):
                    token=vc.CURRENT.set(ctx)
                    try:
                        enabled=text_of(real_prompt(category,int(ctx['seed']),role))
                        off=vc.DISABLED.set(True)
                        try: baseline=text_of(real_prompt(category,int(ctx['seed']),role))
                        finally: vc.DISABLED.reset(off)
                        self.assertEqual(enabled,baseline)
                    finally: vc.CURRENT.reset(token)

    def test_pet_prepared_prompt_is_immutable_after_catalog_change(self):
        from generate_pet_transport_groups import _record
        from tools.category_image_production import effective_prompt
        old=vc.defaults('pet_transport');old['dimensions'].append(custom(value='门口边缘保留自然接缝'))
        with patch.object(vc,'load',return_value=old):
            row=_record('test',1401,1,'cover',None,'测试排除')
            before=effective_prompt(row,'15795643941')
        changed=copy.deepcopy(old);changed['dimensions'][-1]['options'][0]['value']='不应注入旧记录的变化'
        with patch.object(vc,'load',return_value=changed): after=effective_prompt(row,'15795643941')
        self.assertEqual(before,after);self.assertIn('门口边缘保留自然接缝',after)
        self.assertNotIn('不应注入旧记录',after)

    def test_actual_home_records_and_truck_records_capture_version(self):
        from generate_home_appliance_groups import build_records
        data=vc.defaults('home_appliance_repair');data['dimensions'].append(custom())
        with patch.object(vc,'load',return_value=data): rows=build_records(1401,1,'15795643941')
        self.assertIn('variable_catalog',rows[0][0]['scene'])
        self.assertIn(custom()['options'][0]['value'],rows[0][0]['prompt'])
        from generate_truck_rescue_groups import _build_rows
        data=vc.defaults('truck_rescue');data['dimensions'].append(custom())
        config=vc.read_json(vc.ROOT/'configs/categories/truck_rescue.json')
        with patch.object(vc,'load',return_value=data): results=_build_rows(374,1,1,config)
        self.assertTrue(all('variable_catalog' in r for r in results[0]))
        self.assertTrue(all(r['prompt'].count(custom()['options'][0]['value'])==1 for r in results[0]))


class CatalogValidation(unittest.TestCase):
    def test_frequency_roles_conditions_and_weights(self):
        data=vc.defaults('road_rescue');a=custom('a');b=custom('b');b['probability']=.8
        b['options'][0]['conditions']=[{'dimension':'a','option':'a_one'}]
        data['dimensions'] += [a,b];vc.validate(data)
        selected=[vc.custom_selection(data,s,'cover')[1] for s in range(150)]
        count=sum(any(x['type_id']=='b' for x in row) for row in selected)
        self.assertGreater(count,80);self.assertLess(count,150)
        a['roles']=['detail'];b['roles']=['detail']
        self.assertEqual(vc.custom_selection(data,1,'cover')[1],[])
        b['probability']=0
        self.assertFalse(any(x['type_id']=='b' for x in vc.custom_selection(data,1,'detail')[1]))
        a['options'].append({**copy.deepcopy(a['options'][0]),'id':'a_two','name':'候选乙','weight':5})
        draws=[vc.custom_selection(data,s,'detail')[1][0]['option_id'] for s in range(150)]
        self.assertGreater(draws.count('a_two'),100)

    def test_invalid_catalogs_and_dependency_protection(self):
        data=vc.defaults('road_rescue');a=custom('a');b=custom('b');data['dimensions'] += [a,b]
        cases=[]
        x=copy.deepcopy(data);x['dimensions'][-1]['name']=a['name'];cases.append(x)
        x=copy.deepcopy(data);x['dimensions'][-1]['options']=[];cases.append(x)
        x=copy.deepcopy(data);x['dimensions'][-1]['options'][0]['conditions']=[{'dimension':'missing','option':'a'}];cases.append(x)
        x=copy.deepcopy(data);x['dimensions'][-1]['options'][0]['value']='联系电话15795643941';cases.append(x)
        x=copy.deepcopy(data);x['dimensions'][-1]['options'][0]['conditions']=[{'dimension':'a','option':'a_one'}];x['dimensions'][-2]['options'][0]['conditions']=[{'dimension':'b','option':'b_one'}];cases.append(x)
        x=copy.deepcopy(data);x['dimensions'][-1]['options'][0]['conditions']=[{'dimension':'a','option':'a_one'}];x['dimensions'][-2]['options'][0]['enabled']=False;cases.append(x)
        for x in cases:
            with self.assertRaises(ValueError): vc.validate(x)
        bk=vc.defaults('business_ktv');bk['dimensions'][0]['options'][0]['enabled']=False
        with self.assertRaisesRegex(ValueError,'商务KTV'): vc.validate(bk)

    def test_atomic_save_conflict_rollback_and_restart(self):
        category='lock_service';base=vc.defaults(category)
        with nullcontext(vc.ROOT/'.runtime'/'variable_tests'/uuid.uuid4().hex) as temp:
            directory=Path(temp);vc.atomic(directory/'project.json',vc.read_json(vc.project_dir(category)/'project.json'))
            with patch.object(vc,'project_dir',return_value=directory):
                first=vc.initialize(category);self.assertEqual(first['revision'],0)
                edited=copy.deepcopy(first);edited['dimensions'].append(custom())
                saved=vc.save(category,edited,0);self.assertEqual(saved['revision'],1)
                self.assertEqual(vc.load(category),saved)
                with self.assertRaisesRegex(ValueError,'其他窗口'): vc.save(category,first,0)
                original=vc.read_json(directory/'variable_history/000000.json')
                restored=vc.save(category,original,1);self.assertEqual(restored['revision'],2)
                self.assertEqual(restored['dimensions'],first['dimensions'])
                self.assertEqual(vc.history(category),[1,0])
                (directory/'variable_catalog.lock').write_text('locked')
                with self.assertRaisesRegex(ValueError,'正在保存'): vc.save(category,restored,2)
                (directory/'variable_catalog.lock').unlink()
                bad=copy.deepcopy(restored);bad['dimensions'][0]['options']=[]
                with self.assertRaises(ValueError): vc.save(category,bad,2)
                self.assertEqual(vc.load(category),restored)
                def attempt():
                    try: return vc.save(category,restored,2)['revision']
                    except ValueError: return 'conflict'
                with ThreadPoolExecutor(max_workers=2) as executor:
                    outcomes=list(executor.map(lambda _:attempt(),range(2)))
                self.assertEqual(sorted(map(str,outcomes)),['3','conflict'])


if __name__=='__main__': unittest.main()
