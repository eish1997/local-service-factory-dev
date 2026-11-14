import json
from pathlib import Path
from collections import Counter
import unittest
from PIL import Image,ImageChops
from tools import graphic_templates as g,postprocess_rules as rules,runtime_paths

class GraphicTemplates(unittest.TestCase):
 def setUp(self):
  self.doc=json.loads((runtime_paths.CODE_ROOT/'configs/postprocess.json').read_text(encoding='utf-8'))
  self.templates=[p for p in self.doc['presets'] if 'structure' in p]
  self.photo=Image.new('RGB',(1024,1536),(177,187,179));self.phone='13800138000';self.words=['汽车救援','搭电救援','拖车服务','补胎换胎','送油救援','困境救援','地库救援','车辆救援','高速救援','城市路救援']
 def test_eighteen_structures_content_bounds_and_photo_preservation(self):
  rules.validate(self.doc);self.assertGreaterEqual(len(self.templates),16);self.assertEqual({p['structure']['family'] for p in self.templates},g.FAMILIES)
  signatures=set()
  for template in self.templates:
   result,meta=g.render(self.photo,self.phone,self.words,template,101,False)
   groups=meta['groups'];self.assertEqual(Counter(w for group in groups if group['kind']!='phone' for w in group['words']),Counter(self.words))
   self.assertEqual(''.join(next(group for group in groups if group['kind']=='phone')['words']),'电话：'+self.phone)
   telephone=next(group for group in groups if group['kind']=='phone');pb=telephone['box']
   self.assertEqual(telephone['board'],'none')
   self.assertLessEqual(abs((pb[0]+pb[2])/2-512),1);self.assertLessEqual(abs((pb[1]+pb[3])/2-768),1)
   self.assertGreaterEqual(telephone['font_size'],70)
   boxes=[group['box'] for group in groups]
   for i,box in enumerate(boxes):
    self.assertTrue(0<=box[0]<box[2]<=result.width and 0<=box[1]<box[3]<=result.height)
    self.assertFalse(any(g.intersects(box,other) for other in boxes[i+1:]))
   self.assertEqual(meta.get('avoid_regions',[]),[])
   diff=ImageChops.difference(result.crop((0,0,1024,1536)),self.photo)
   for box in boxes:diff.paste((0,0,0),tuple(box))
   self.assertIsNone(diff.getbbox())
   signatures.add(tuple((group['kind'],group['zone'],group['board']) for group in groups))
  self.assertGreaterEqual(len(signatures),16)
 def test_small_variables_reproduce_and_change_visuals(self):
  hashes=set();template=self.templates[0];boards=set();angles=set();modes=set()
  for seed in range(8):
   first,a=g.render(self.photo,self.phone,self.words,template,seed,True);second,b=g.render(self.photo,self.phone,self.words,template,seed,True)
   self.assertEqual(first.tobytes(),second.tobytes());self.assertEqual(a,b);hashes.add(first.tobytes())
   boards.update(x['board'] for x in a['groups']);angles.update(x.get('angle',0) for x in a['groups']);modes.add(a.get('grouping'))
  self.assertGreaterEqual(len(hashes),6)
  self.assertGreaterEqual(len(boards),2);self.assertGreaterEqual(len(angles),2);self.assertGreaterEqual(len(modes),2)
  first,_=g.render(self.photo,self.phone,self.words,template,1,False);second,_=g.render(self.photo,self.phone,self.words,template,99,False);self.assertEqual(first.tobytes(),second.tobytes())
 def test_new_snapshot_rotation_and_old_snapshot_unchanged(self):
  old={'parameters':{}};self.assertIs(g.production_rules(old,0,2,'cover'),old)
  frozen={'auto_layout':True,'presets':self.templates,'parameters':{}};families=[]
  for index in range(18):families.append(g.production_rules(frozen,index,2,'cover')['template']['structure']['family'])
  self.assertTrue(all(a!=b for a,b in zip(families,families[1:])))
 def test_design_validation_scope_and_bounded_effects(self):
  import copy
  self.assertEqual(set(self.doc['layout_categories']),set(__import__('tools.rule_updates',fromlist=['PROJECTS']).PROJECTS))
  self.assertEqual(set(self.doc['auto_layout_categories']),set(__import__('tools.rule_updates',fromlist=['PROJECTS']).PROJECTS))
  self.assertTrue(rules.load('road_rescue')['auto_layout'])
  self.assertTrue(rules.load('truck_rescue')['auto_layout'])
  self.assertTrue(rules.load('pet_transport')['auto_layout'])
  for key,value in [('phone_scale',float('nan')),('effect','arbitrary'),('palettes',[{'ink':'#123456','accent':'untrusted','paper':'#ffffff'}])]:
   s=copy.deepcopy(self.templates[0]['structure']);s['design'][key]=value
   with self.assertRaises(ValueError):g.validate_structure(s)
  for template in self.templates[::3]:
   result,meta=g.render(self.photo,self.phone,self.words,template,8,True)
   if meta['fallback']:continue
   self.assertLessEqual(meta['attempts'],8);self.assertGreater(meta['valid_candidates'],0)
   for group in meta['groups']:
    if group['kind'] in {'phone','main'}:self.assertEqual(group['font_family'],'msyh_bold')
   # Every changed pixel, including shadows and glow, stays inside validated groups.
   diff=ImageChops.difference(result,self.photo)
   for group in meta['groups']:diff.paste((0,0,0),tuple(group['box']))
   self.assertIsNone(diff.getbbox())
 def test_individual_words_and_coloured_heavy_outlines(self):
  import copy
  template=copy.deepcopy(self.templates[0]);template['structure']['design']['group_modes']=['words']
  result,meta=g.render(self.photo,self.phone,self.words,template,82,True)
  self.assertFalse(meta['fallback']);self.assertEqual(meta['grouping'],'words')
  body=[x for x in meta['groups'] if x['kind']!='phone']
  self.assertEqual(len(body),len(self.words));self.assertTrue(all(len(x['words'])==1 for x in body))
  self.assertEqual(Counter(x['words'][0] for x in body),Counter(self.words))
  self.assertGreater(len({tuple(x['color']) for x in body}),1)
  self.assertGreater(len({tuple(x['outline_color']) for x in body}),1)
  self.assertTrue(all(x['stroke']>=3 for x in body))
  self.assertGreaterEqual(next(x for x in meta['groups'] if x['kind']=='phone')['stroke'],6)
  for i,one in enumerate(meta['groups']):self.assertFalse(any(g.intersects(one['box'],two['box']) for two in meta['groups'][i+1:]))
 def test_phone_background_policy_beats_random_and_preserves_old_frozen_policy(self):
  import copy
  backgrounds=set()
  for template in self.templates:
   for seed in (0,875):
    result,meta=g.render(self.photo,self.phone,self.words,template,seed,True)
    telephone=next(x for x in meta['groups'] if x['kind']=='phone')
    self.assertEqual(telephone['board'],'none');self.assertGreaterEqual(telephone['stroke'],6)
    x,y,_,_=telephone['box'];self.assertEqual(result.getpixel((x,y)),self.photo.getpixel((x,y)))
    backgrounds.update(x['board'] for x in meta['groups'] if x['kind']!='phone')
  self.assertGreaterEqual(len(backgrounds),2)
  old=copy.deepcopy(self.templates[0]);old['structure']['design'].pop('headline_board');old['structure']['design']['random_boards']=False
  next(x for x in old['structure']['groups'] if x['kind']=='phone')['board']='paper'
  _,meta=g.render(self.photo,self.phone,self.words,old,1,False)
  self.assertEqual(next(x for x in meta['groups'] if x['kind']=='phone')['board'],'paper')
  bad=copy.deepcopy(self.templates[0]['structure']);bad['design']['headline_board']='random_unknown'
  with self.assertRaises(ValueError):g.validate_structure(bad)
 def test_forced_failure_safe_footer_and_invalid_content(self):
  from unittest.mock import patch
  with patch.object(g,'arrange',return_value=(None,{'fallback':True,'attempts':8,'avoidance':'safe footer'})):
   result,meta=g.render(self.photo,self.phone,self.words,self.templates[0],1)
  self.assertEqual(result.crop((0,0,1024,1536)).tobytes(),self.photo.tobytes());self.assertTrue(meta['fallback'])
  with self.assertRaises(ValueError):g.render(self.photo,self.phone,self.words+[self.words[0]],self.templates[0],1)

if __name__=='__main__':unittest.main()
