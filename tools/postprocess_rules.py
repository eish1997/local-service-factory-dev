"""Public, data-only renderer overrides. Empty sections preserve built-in styles."""
import copy
import math
from tools import runtime_paths

SECTIONS = {
    'theme': {'enabled', 'font_ratio', 'panel_font_ratio', 'boards', 'alignments'},
    'crop': {'mode', 'cover_anchor_y', 'detail_anchor_y', 'panel_anchor_y'},
    'cover': {'font_family', 'phone_region', 'phone_color', 'phone_background', 'phone_font_ratio', 'phone_stroke', 'service_region', 'service_color', 'service_background', 'service_font_ratio', 'service_columns'},
    'detail': {'font_family', 'phone_region', 'phone_color', 'phone_background', 'phone_font_ratio', 'phone_stroke', 'service_region', 'service_color', 'service_background', 'service_font_ratio', 'service_columns'},
    'triptych': {'font_family', 'content_height_ratio', 'gutter_px', 'panels', 'phone_color', 'phone_background', 'phone_font_ratio', 'phone_stroke', 'service_color', 'service_font_ratio'}
}

def validate_sections(sections):
    if not isinstance(sections, dict) or set(sections)-set(SECTIONS): raise ValueError('后处理规则区块无效')
    for section, values in sections.items():
        if not isinstance(values, dict) or set(values)-SECTIONS[section]: raise ValueError('后处理规则出现未知参数')
        for key, value in values.items():
            if key == 'enabled':
                if type(value)!=bool: raise ValueError('主题标注开关无效')
            elif key in {'boards','alignments'}:
                allowed={'none','paper','soft'} if key=='boards' else {'left','center','right'}
                if not isinstance(value,list) or not value or len(value)>3 or set(value)-allowed: raise ValueError('主题标注样式无效')
            elif key == 'font_family':
                if value not in {'msyh_bold','msyh','simhei'}: raise ValueError('不支持的后处理字体')
            elif key == 'mode':
                if value != 'lanczos_cover_crop': raise ValueError('不支持的裁切方式')
            elif key == 'panels':
                if not isinstance(value, list) or len(value) != 3: raise ValueError('三拼需要三个布局格')
                for panel in value:
                    if not isinstance(panel, dict) or set(panel) != {'x','y','width','height'}: raise ValueError('三拼布局字段无效')
                    if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in panel.values()): raise ValueError('三拼布局比例无效')
                    if panel['width']<=0 or panel['height']<=0 or panel['x']+panel['width']>1 or panel['y']+panel['height']>1: raise ValueError('三拼布局越界')
                for i,a in enumerate(value):
                    for b in value[i+1:]:
                        if min(a['x']+a['width'],b['x']+b['width'])>max(a['x'],b['x']) and min(a['y']+a['height'],b['y']+b['height'])>max(a['y'],b['y']): raise ValueError('三拼布局不能重叠')
            elif key.endswith('_region'):
                if not isinstance(value,list) or len(value)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in value) or value[0]>=value[2] or value[1]>=value[3]: raise ValueError('叠字区域无效')
            elif key.endswith('_color') or key.endswith('_background'):
                if value is None and key=='phone_background': continue
                if not isinstance(value,list) or len(value)!=4 or any(type(v)!=int or not 0<=v<=255 for v in value): raise ValueError('后处理颜色须为 RGBA')
            else:
                if type(value) not in (int,float) or not math.isfinite(value): raise ValueError('后处理数字无效')
                low,high=(0,1) if key.endswith('anchor_y') else (.01,.15) if key.endswith('font_ratio') else (.5,.9) if key=='content_height_ratio' else (0,64) if key=='gutter_px' else (0,20) if key=='phone_stroke' else (1,10)
                if not low<=value<=high: raise ValueError('后处理参数越界：'+key)
                if key in {'gutter_px','phone_stroke','service_columns'} and type(value)!=int: raise ValueError('后处理参数须为整数')
    return sections

def validate(document):
    if not isinstance(document,dict) or set(document)-{'schema_version','engine_version','defaults','projects','presets','layout_categories','auto_layout_categories'} or not {'schema_version','engine_version','defaults','projects'}<=set(document) or document['schema_version']!=1 or document['engine_version']!=1: raise ValueError('后处理规则版本不兼容')
    validate_sections(document['defaults'])
    if not isinstance(document['projects'],dict): raise ValueError('后处理项目配置无效')
    from tools.rule_updates import PROJECTS
    if set(document['projects'])-set(PROJECTS): raise ValueError('后处理项目未知')
    for sections in document['projects'].values(): validate_sections(sections)
    presets=document.get('presets',[])
    if not isinstance(presets,list) or len(presets)>50: raise ValueError('后处理预设数量无效')
    for key in ('layout_categories','auto_layout_categories'):
        if not isinstance(document.get(key,[]),list) or set(document.get(key,[]))-set(PROJECTS):raise ValueError('自由排版适用范围无效')
    if set(document.get('auto_layout_categories',[]))-set(document.get('layout_categories',[])):raise ValueError('自动排版范围未授权')
    seen=set()
    import re
    for preset in presets:
        if not isinstance(preset,dict) or set(preset)-{'id','name','roles','parameters','variations','structure'} or not {'id','name','roles','parameters'}<=set(preset): raise ValueError('后处理预设字段无效')
        if not isinstance(preset['id'],str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',preset['id']) or preset['id'] in seen: raise ValueError('后处理预设标识无效')
        seen.add(preset['id'])
        if not isinstance(preset['name'],str) or not 1<=len(preset['name'])<=40: raise ValueError('后处理预设名称无效')
        if not isinstance(preset['roles'],list) or not preset['roles'] or set(preset['roles'])-{'cover','detail','triptych'}: raise ValueError('后处理预设类型无效')
        if 'structure' in preset:
            from tools.graphic_templates import validate_structure
            validate_structure(preset['structure'])
        validate_sections(preset['parameters'])
        variations=preset.get('variations',{})
        if not isinstance(variations,dict) or set(variations)-{'cover','detail','triptych'}:raise ValueError('变体范围无效')
        for section,choices in variations.items():
            if not isinstance(choices,list) or not 1<=len(choices)<=30:raise ValueError('变体候选数量无效')
            for choice in choices:
                validate_sections({section:choice})
                if set(choice)-{'font_family','phone_region','phone_color','phone_background','phone_font_ratio','phone_stroke','service_region','service_color','service_background','service_font_ratio','service_columns'}:raise ValueError('变体只能调整文字设计')
                merged={**preset['parameters'].get(section,{}),**choice}
                if section!='triptych':
                    phone=merged.get('phone_region',[0,.49,1,.585]);service=merged.get('service_region',[.025,.82,.975,.98])
                    if phone[1]<.38 or phone[3]>.67 or service[1]<.78 or phone[3]>=service[1]:raise ValueError('变体文字区域超出安全范围')

    return document

def load(category):
    document=validate(runtime_paths.read_json(runtime_paths.CODE_ROOT/'configs/postprocess.json'))
    result=copy.deepcopy(document['defaults'])
    for section,values in document['projects'].get(category,{}).items(): result.setdefault(section,{}).update(copy.deepcopy(values))
    return {'schema_version':1,'engine_version':1,'rules_version':runtime_paths.version(),'parameters':result,'presets':copy.deepcopy([p for p in document.get('presets',[]) if 'structure' not in p or category in document.get('layout_categories',[])]),'auto_layout':category in document.get('auto_layout_categories',[])}

def parameters(frozen):
    if frozen is None: return {}
    if frozen.get('schema_version')!=1 or frozen.get('engine_version')!=1: raise ValueError('冻结后处理规则不兼容')
    return validate_sections(frozen['parameters'])
