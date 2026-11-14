import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image
import test_image_versions as fixture
from tools import task_library as lib,postprocess_workspace as workspace,image_versions as versions,postprocess_rules as rules

class Workspace(unittest.TestCase):
    setUp=fixture.ImageVersions.setUp
    seed=fixture.ImageVersions.seed
    target=fixture.ImageVersions.target

    def test_preview_reproducible_and_apply_exact_version(self):
        before=self.target().read_bytes();session=workspace.create(self.req);request={'category':'road_rescue','session':session['session'],'preset':'blue_white','variant':True,'seed':101}
        first=workspace.preview(request);second=workspace.preview(request)
        self.assertEqual(first['sha256'],second['sha256']);self.assertEqual(first['parameters'],second['parameters'])
        self.assertEqual(self.target().read_bytes(),before)
        self.assertEqual(first['validation']['services']['items'],session['services'])
        workspace.apply({**request,'preview':first['id']})
        self.assertEqual(self.target().read_bytes(),Path(first['path']).read_bytes())
        self.assertEqual(len(versions.history(self.req)['versions']),2)
        with self.assertRaisesRegex(ValueError,'过期'):workspace.preview(request)

    def test_import_orientation_phone_export_and_boundary(self):
        source=self.root/'import.jpg';image=Image.new('RGB',(40,20),'gray');exif=image.getexif();exif[274]=6;image.save(source,exif=exif)
        session=workspace.create({**self.req,'image_path':str(source),'kind':'detail'})
        self.assertEqual(session['phone'],self.batch['phone'])
        with Image.open(session['sources'][0]['path']) as normalized:self.assertEqual(normalized.size,(20,40))
        request={'category':'road_rescue','session':session['session'],'preset':'paper_light'};preview=workspace.preview(request)
        destination=self.root/'export.png';before=self.target().read_bytes()
        workspace.apply({**request,'preview':preview['id'],'destination':str(destination)})
        self.assertEqual(destination.read_bytes(),Path(preview['path']).read_bytes());self.assertEqual(self.target().read_bytes(),before)
        with self.assertRaises(ValueError):workspace.apply({**request,'preview':preview['id'],'destination':str(self.target())})
        with self.assertRaises(ValueError):workspace.load({'category':'road_rescue','session':'../../private'})

    def test_triptych_input_stale_and_failed_render_preserved(self):
        request={**self.req,'position':2};session=workspace.create(request);before=self.target(2,'triptych').read_bytes()
        req={'category':'road_rescue','session':session['session'],'preset':'red_white','variant':True,'seed':23}
        first=workspace.preview(req);self.assertEqual(len(session['sources']),3)
        with patch.object(workspace,'render',side_effect=RuntimeError('render failed')):
            with self.assertRaises(RuntimeError):workspace.preview(req)
        self.assertEqual(self.target(2,'triptych').read_bytes(),before)
        path,c=workspace.load(req);Image.new('RGB',(1024,1536),'red').save(c['inputs'][0]['path'])
        with self.assertRaisesRegex(ValueError,'过期'):workspace.apply({**req,'preview':first['id']})
        self.assertEqual(self.target(2,'triptych').read_bytes(),before)

    def test_manual_text_changes_only_the_preview(self):
        session=workspace.create(self.req);request={'category':'road_rescue','session':session['session']}
        before=lib.read(lib.batch_dir(self.batch['category'],self.batch['id'])/'batch.json')['phone']
        stale=workspace.preview({**request,'preset':'blue_white','variant':False,'seed':11})
        updated=workspace.update_text({**request,'phone':'13900139000','services':['夜间拖车','补胎']})
        self.assertEqual((updated['phone'],updated['services'],updated['custom']),('13900139000',['夜间拖车','补胎'],True))
        self.assertEqual(lib.read(lib.batch_dir(self.batch['category'],self.batch['id'])/'batch.json')['phone'],before)
        self.assertEqual(lib.business_config('road_rescue')['service_items'],['夜间拖车','补胎'])
        self.assertEqual(workspace.context(self.req)['services'],['夜间拖车','补胎'])
        nxt=lib.assemble({'category':'road_rescue','count':1,'seed':1402,'phone':'13800138000'})
        self.assertEqual(nxt['phone'],'13800138000')
        self.assertEqual(lib.read(lib.batch_dir('road_rescue',nxt['id'])/'snapshot.json')['business']['service_items'],['夜间拖车','补胎'])
        self.assertEqual(lib.read(lib.batch_dir('road_rescue',self.batch['id'])/'snapshot.json')['business']['service_items'],session['services'])
        from tools.task_actions import prepare_replacement
        child=prepare_replacement({'category':'road_rescue','batch':self.batch['id'],'group':1,'position':1,'request_id':'text-revision'})
        self.assertEqual(lib.read(lib.batch_dir('road_rescue',child['id'])/'snapshot.json')['business']['service_items'],['夜间拖车','补胎'])
        self.assertEqual(lib.read(lib.batch_dir('road_rescue',self.batch['id'])/'snapshot.json')['business']['service_items'],session['services'])
        with self.assertRaisesRegex(ValueError,'结构模板'):workspace.preview({**request,'preset':'blue_white','variant':False,'seed':11})
        preview=workspace.preview({**request,'preset':'e_words','variant':False,'seed':12})
        self.assertEqual(preview['validation']['services']['items'],['夜间拖车','补胎'])
        self.assertIn('13900139000',preview['validation']['phone']['text'])
        with self.assertRaisesRegex(ValueError,'预览不存在'):workspace.apply({**request,'preview':stale['id']})
        restored=workspace.update_text({**request,'reset':True})
        self.assertEqual((restored['phone'],restored['services'],restored['custom']),(session['phone'],session['services'],False))
        self.assertIsNone(lib.saved_service_items('road_rescue'))
        self.assertEqual(lib.business_config('road_rescue')['service_items'],session['services'])
        with self.assertRaisesRegex(ValueError,'11位手机号'):workspace.update_text({**request,'phone':'123','services':['补胎']})
        with self.assertRaisesRegex(ValueError,'不能重复'):workspace.update_text({**request,'phone':'13900139000','services':['补胎','补胎']})

    def test_create_dialog_lines_freeze_batch_and_next_default(self):
        shown=lib.overlay_text({'category':'road_rescue'})
        self.assertEqual(shown['services'],lib.base_service_items('road_rescue'))
        old=lib.read(lib.batch_dir('road_rescue',self.batch['id'])/'snapshot.json')['business']['service_items']
        req={'category':'road_rescue','count':1,'seed':1403,'phone':'13800138000','request_id':'watermark-lines','services':[' 夜间拖车 ','','补胎']}
        made=lib.assemble(req)
        self.assertEqual(lib.assemble(req)['id'],made['id'])
        self.assertEqual(lib.read(lib.batch_dir('road_rescue',made['id'])/'snapshot.json')['business']['service_items'],['夜间拖车','补胎'])
        self.assertEqual(lib.overlay_text({'category':'road_rescue'})['services'],['夜间拖车','补胎'])
        self.assertEqual(lib.read(lib.batch_dir('road_rescue',self.batch['id'])/'snapshot.json')['business']['service_items'],old)
        with self.assertRaisesRegex(ValueError,'同一请求标识'):lib.assemble({**req,'services':['补胎']})
        with self.assertRaisesRegex(ValueError,'不能重复'):lib.assemble({**req,'request_id':'watermark-duplicate','services':['补胎','补胎']})

    def test_restyle_uses_saved_service_lines(self):
        session=workspace.create(self.req)
        workspace.update_text({'category':'road_rescue','session':session['session'],'phone':self.batch['phone'],'services':['夜间拖车','补胎']})
        from tools import postprocess_actions
        postprocess_actions.apply({**self.req,'scope':'image','preset':'e_words','request_id':'text-restyle'})
        self.assertEqual(lib.read(self.target().with_suffix('.validation.json'))['postprocess_record']['services']['items'],['夜间拖车','补胎'])
        self.assertEqual(lib.read(lib.batch_dir('road_rescue',self.batch['id'])/'snapshot.json')['business']['service_items'],session['services'])

    def test_structural_preview_apply_and_batch_rotation(self):
        import json,copy
        catalog=copy.deepcopy(rules.load('road_rescue'))
        doc=json.loads((lib.runtime_paths.CODE_ROOT/'configs/postprocess.json').read_text(encoding='utf-8'))
        catalog['presets']=doc['presets']
        with patch.object(rules,'load',return_value=catalog):
            sessions=[workspace.create(self.req)['session'] for _ in range(6)]
            result=workspace.sequence({'category':'road_rescue','sessions':sessions,'seed':1717})
            families=[p['validation']['layout']['family'] for p in result['previews']]
            self.assertTrue(all(a!=b for a,b in zip(families,families[1:])))
            first=result['previews'][0]
            workspace.apply({'category':'road_rescue','session':sessions[0],'preview':first['id']})
            self.assertEqual(self.target().read_bytes(),Path(first['path']).read_bytes())
            self.assertEqual(lib.read(self.target().with_suffix('.validation.json'))['overlay_style']['signboard_style'],'preserved_source_signboard')

    def test_variation_whitelist_and_safe_layout(self):
        import json,copy
        doc=json.loads((lib.runtime_paths.CODE_ROOT/'configs/postprocess.json').read_text(encoding='utf-8'))
        rules.validate(doc);bad=copy.deepcopy(doc);bad['presets'][0]['variations']['cover'][0]['phone']='123'
        with self.assertRaises(ValueError):rules.validate(bad)
        bad=copy.deepcopy(doc);bad['presets'][0]['variations']['cover'][0]['phone_region']=[0,.8,1,.95]
        with self.assertRaises(ValueError):rules.validate(bad)

    def test_structural_triptych_and_import_keep_confirmed_content(self):
        import copy
        from collections import Counter
        for request in ({**self.req,'position':2},{**self.req,'image_path':str(self.root/'input.webp'),'kind':'detail'}):
            if request.get('image_path'):Image.new('RGB',(800,1200),'#597158').save(request['image_path'])
            session=workspace.create(request);before=self.target(2,'triptych').read_bytes()
            preview=workspace.preview({'category':'road_rescue','session':session['session'],'preset':'e_words','seed':42,'variant':True})
            layout=preview['validation']['layout']
            self.assertEqual(layout['phone'],self.batch['phone'])
            self.assertEqual(Counter(w for group in layout['groups'] if group['kind']!='phone' for w in group['words']),Counter(session['services']))
            self.assertEqual(self.target(2,'triptych').read_bytes(),before)
            if not request.get('image_path'):
                self.assertEqual(len(preview['validation']['sources']),3)
                workspace.apply({'category':'road_rescue','session':session['session'],'preview':preview['id']})
                self.assertEqual(self.target(2,'triptych').read_bytes(),Path(preview['path']).read_bytes())

    def test_triptych_structural_fills_canvas_and_legacy_keeps_footer(self):
        from tools import graphic_templates
        session=workspace.create({**self.req,'position':2})
        request={'category':'road_rescue','session':session['session'],'preset':'e_words','seed':42,'variant':True}
        _,content=workspace.load(request)
        colors=['#aa3333','#338833','#3344aa']
        for source,color in zip(content['sources'],colors):
            Image.new('RGB',(1024,1536),color).save(source)
        # Capture the composed photograph before text to distinguish an
        # empty reserved footer from a legitimate service background.
        canvases=[];render=graphic_templates.render_delivery
        def capture(photo,*args,**kwargs):
            canvases.append(photo.copy());return render(photo,*args,**kwargs)
        with patch.object(graphic_templates,'render_delivery',side_effect=capture):
            preview=workspace.preview(request)
        validation=lib.read(Path(preview['path']).with_suffix('.validation.json'))
        canvas=canvases[0];width,height=canvas.size
        for box,color in zip(validation['panels'],[(170,51,51),(51,136,51),(51,68,170)]):
            self.assertEqual(canvas.getpixel(((box[0]+box[2])//2,box[3]-2)),color)
        self.assertEqual(validation['triptych_recipe']['content_height_ratio'],1.0)
        self.assertGreaterEqual(max(b[3] for b in validation['panels']),height-8)
        self.assertIsNone(validation['postprocess_record']['phone']['background'])
        self.assertEqual(validation['sources'],content['sources'])
        legacy=workspace.preview({**request,'preset':'blue_white','variant':False})
        old=lib.read(Path(legacy['path']).with_suffix('.validation.json'))
        self.assertEqual(old['triptych_recipe']['content_height_ratio'],.82)
        self.assertLess(max(b[3] for b in old['postprocess_record']['panels']),height*.83)

if __name__=='__main__':unittest.main()
