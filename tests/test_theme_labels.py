"""Frozen task captions must survive template rendering and local revisions."""
import copy
import hashlib
from collections import Counter
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4
from PIL import Image,ImageChops
from tools import task_library as lib,task_worker as worker,postprocess_rules as rules
from tools import graphic_templates as graphic,category_image_production as images
from tools import postprocess_workspace as workspace,postprocess_actions as actions
from tools.rule_updates import PROJECTS

class ThemeLabels(unittest.TestCase):
 def setUp(self):
  self.root=lib.ROOT/'.runtime'/('theme-test-'+uuid4().hex);self.root.mkdir()
  override=patch.object(lib,'ROOT',self.root);override.start();self.addCleanup(override.stop)
  self.phone='13800138000'
 def batch(self,category):
  data=lib.assemble({'category':category,'count':1,'phone':self.phone,'seed':1421})
  path=lib.batch_dir(category,data['id']);snapshot=lib.read(path/'snapshot.json');row=lib.read(path/'groups/0001.json')
  originals={}
  for unit in row['units']:
   raw=lib.unit_raw(category,data['id'],1,unit);raw.parent.mkdir(parents=True,exist_ok=True)
   Image.new('RGB',(1024,1536),(85+unit['position']*9,109,138)).save(raw);originals[raw]=raw.read_bytes()
   lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':unit['prompt_sha256'],'raw_sha256':hashlib.sha256(originals[raw]).hexdigest()})
  worker.materialize(category,data['id'],data,[row],snapshot)
  return data,snapshot,row,originals
 def check(self,validation,texts):
  pp=validation['postprocess_record'];layout=pp['layout'];captions=pp['themes']
  self.assertEqual([x['text'] for x in captions],texts);self.assertFalse(layout['fallback'])
  self.assertEqual(layout['phone'],self.phone)
  self.assertEqual(Counter(w for g in layout['groups'] if g['kind']!='phone' for w in g['words']),Counter(layout['service_items']))
  boxes=[g['box'] for g in layout['groups']]+[g['box'] for g in captions]
  for i,box in enumerate(boxes):
   self.assertFalse(any(graphic.intersects(box,other) for other in boxes[i+1:]))
   self.assertTrue(0<=box[0]<box[2]<=layout['photo_size'][0] and 0<=box[1]<box[3]<=layout['photo_size'][1])
  for g in captions:
   self.assertIn(g['text'],validation['expected_text']);self.assertGreaterEqual(g['font_size'],24)
   a,b=g['panel'],g['box'];self.assertTrue(a[0]<=b[0]<b[2]<=a[2] and a[1]<=b[1]<b[3]<=a[3])
 def test_eight_projects_worker_keeps_frozen_themes_and_sources(self):
  for category in PROJECTS:
   with self.subTest(category=category):
    data,snapshot,row,originals=self.batch(category)
    self.assertTrue(snapshot['postprocess']['auto_layout']);families=[]
    for position in sorted({u['delivery_position'] for u in row['units']}):
     units=[u for u in row['units'] if u['delivery_position']==position];kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
     target=lib.delivery_path(category,data['id'],1,position,kind);validation=lib.read(target.with_suffix('.validation.json'))
     expected=[] if category=='business_ktv' or kind=='cover' else [u['service_role'] for u in sorted(units,key=lambda u:u.get('panel_index') or 0)]
     self.check(validation,expected);families.append(validation['postprocess_record']['layout']['family'])
    self.assertTrue(all(a!=b for a,b in zip(families,families[1:])))
    self.assertTrue(all(p.read_bytes()==value for p,value in originals.items()))
 def test_old_batch_preview_and_right_click_keep_frozen_theme(self):
  for category in ('pet_transport','home_appliance_repair','lock_service'):
   data,snapshot,row,originals=self.batch(category)
   unit=next(u for u in row['units'] if u['kind']=='detail');request={'category':category,'batch':data['id'],'group':1,'position':unit['delivery_position']}
   # Simulate a pre-feature snapshot. Explicit restyling takes new design only.
   path=lib.batch_dir(category,data['id']);snapshot['postprocess']['parameters'].pop('theme');snapshot['postprocess']['auto_layout']=False
   lib.write(path/'snapshot.json',snapshot);data['snapshot_sha256']=lib.digest(snapshot);lib.write(path/'batch.json',data)
   session=workspace.create(request);preview=workspace.preview({'category':category,'session':session['session'],'preset':'a_sky','seed':35,'variant':True})
   candidate=Path(preview['path']);validation=lib.read(candidate.with_suffix('.validation.json'));self.check(validation,[unit['service_role']])
   with patch.object(actions.secrets,'randbelow',return_value=3595286609751326):
    actions.apply({**request,'preset':'d_left','request_id':'theme-local-'+category})
   target=lib.delivery_path(category,data['id'],1,unit['delivery_position'],'detail');self.check(lib.read(target.with_suffix('.validation.json')),[unit['service_role']])
   self.assertTrue(all(p.read_bytes()==value for p,value in originals.items()))
 def test_seeded_themes_photo_preservation_cover_and_missing_metadata(self):
  frozen=rules.load('truck_rescue');template=next(p for p in frozen['presets'] if p['id']=='a_sky')
  photo=Image.new('RGB',(1024,1536),'#757d87');words=['货车换胎','货车维修','发动机检修','搭电启动']
  labels=[{'text':'发动机检修','panel':[0,0,1024,1536]}]
  one,meta=graphic.render(photo,self.phone,words,template,358,True,labels,frozen['parameters']['theme'])
  two,again=graphic.render(photo,self.phone,words,template,358,True,labels,frozen['parameters']['theme'])
  self.assertEqual(one.tobytes(),two.tobytes());self.assertEqual(meta,again)
  diff=ImageChops.difference(one,photo)
  for group in meta['groups']+meta['theme_labels']:diff.paste((0,0,0),tuple(group['box']))
  self.assertIsNone(diff.getbbox())
  for themes in ([],labels):
   _,old=graphic.render(photo,self.phone,words,template,358,True,themes,{})
   self.assertEqual(old['theme_labels'],[])
  with self.assertRaises(ValueError):rules.validate_sections({'theme':{'boards':['arbitrary']}})
  with self.assertRaises(ValueError):graphic.render(photo,self.phone,words,template,358,True,[{'text':'错\n词','panel':[0,0,1024,1536]}],frozen['parameters']['theme'])

if __name__=='__main__':unittest.main()
