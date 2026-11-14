"""Deterministic, bold advertising groups with bounded layout search.

Phone centred; user permits scene overlap. Only text bounds/overlap are gated.
"""
import copy
import math
import random
import re
from PIL import Image, ImageDraw, ImageStat, ImageFilter

FAMILIES={'photo','swap','primary','split','paper','free'}
ZONES={
 'center_full':[.025,.37,.975,.67],
 'upper_full':[.025,.025,.975,.27], 'lower_full':[.025,.76,.975,.98],
 'sky_left':[.025,.025,.75,.16], 'sky_right':[.25,.025,.975,.16],
 'top_left':[.025,.025,.47,.20], 'top_right':[.53,.025,.975,.20],
 'bottom_left':[.025,.80,.58,.98], 'bottom_right':[.42,.80,.975,.98],
 'bottom_full':[.025,.87,.975,.98], 'lower_phone_left':[.025,.775,.68,.865],
 'lower_phone_right':[.32,.775,.975,.865],
 'side_left':[.025,.43,.31,.73], 'side_right':[.69,.43,.975,.73],
 'bottom_a':[.025,.80,.46,.98], 'bottom_b':[.54,.80,.975,.98],
}
for row,(top,bottom) in enumerate(((.025,.125),(.15,.25),(.75,.85),(.88,.98))):
    for column in range(3):ZONES[f'word_{row}_{column}']=[.025+column*.32,top,.025+column*.32+.30,bottom]

def production_rules(frozen,index,seed,role):
    """Only new snapshots with explicit auto_layout opt-in rotate templates."""
    if not frozen or not frozen.get('auto_layout'):return frozen
    pool=[p for p in frozen.get('presets',[]) if 'structure' in p and role in p['roles']]
    if not pool:return frozen
    families=[f for f in ('photo','swap','primary','split','paper','free') if any(p['structure']['family']==f for p in pool)]
    candidates=[p for p in pool if p['structure']['family']==families[index%len(families)]]
    result=copy.deepcopy(frozen);preset=random.Random(seed).choice(candidates)
    result.update(template=preset,preset_id=preset['id'],layout_seed=seed,layout_variant=True)
    return result

def validate_structure(s):
    if not isinstance(s,dict) or set(s)-{'family','groups','main_count','variables','design'} or not {'family','groups','main_count','variables'}<=set(s) or s['family'] not in FAMILIES:raise ValueError('模板结构无效')
    if type(s['main_count'])!=int or not 0<=s['main_count']<=2:raise ValueError('主服务数量无效')
    if not isinstance(s['groups'],list) or not 2<=len(s['groups'])<=4:raise ValueError('模板文字组数量无效')
    phone=0;parts=[]
    for g in s['groups']:
        if not isinstance(g,dict) or set(g)!={'kind','part','zones','align','board'}:raise ValueError('文字组字段无效')
        if g['kind'] not in {'phone','services','main'} or g['align'] not in {'left','right','center'} or g['board'] not in {'none','paper','soft'}:raise ValueError('文字组类型无效')
        if not isinstance(g['zones'],list) or not g['zones'] or set(g['zones'])-set(ZONES):raise ValueError('模板区域无效')
        if g['kind']=='phone':phone+=1
        else:parts.append(g['part'])
    expected={'main','rest'} if s['main_count'] else {'all'}
    if 'a' in parts or 'b' in parts:expected={'main','a','b'} if s['main_count'] else {'a','b'}
    if 'c' in parts:expected={'a','b','c'}
    if phone!=1 or set(parts)!=expected or len(parts)!=len(set(parts)):raise ValueError('服务词必须完整且只出现一次')
    v=s['variables']
    if not isinstance(v,dict) or set(v)!={'fonts','phone_lines','separators','spacing','offset'}:raise ValueError('模板小变量无效')
    if not v['fonts'] or set(v['fonts'])-{'msyh','msyh_bold','simhei'}:raise ValueError('模板字体无效')
    if not v['phone_lines'] or set(v['phone_lines'])-{1,2}:raise ValueError('电话行数无效')
    if not v['separators'] or set(v['separators'])-{' ',' · ',' | ','\n'}:raise ValueError('分隔方式无效')
    if not isinstance(v['spacing'],list) or not v['spacing'] or any(type(x) not in (int,float) or not math.isfinite(x) or not 1.15<=x<=1.6 for x in v['spacing']):raise ValueError('行距无效')
    if type(v['offset']) not in (int,float) or not 0<=v['offset']<=.015:raise ValueError('微偏移无效')
    if 'design' in s:
        d=s['design']
        if not isinstance(d,dict) or set(d)-{'palettes','effect','board_gradient','phone_scale','main_scale','service_scale','phone_center','random_boards','headline_board','rotations','group_modes','stroke_scales'} or not {'palettes','effect','board_gradient','phone_scale','main_scale','service_scale'}<=set(d):raise ValueError('设计参数无效')
        if 'headline_board' in d and d['headline_board'] not in {'none','paper','soft'}:raise ValueError('电话底板规则无效')
        for key in ('phone_center','random_boards'):
            if key in d and type(d[key])!=bool:raise ValueError('设计开关无效')
        if 'rotations' in d and (not isinstance(d['rotations'],list) or not d['rotations'] or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>6 for x in d['rotations'])):raise ValueError('文字旋转角度无效')
        if 'group_modes' in d and (not isinstance(d['group_modes'],list) or not d['group_modes'] or set(d['group_modes'])-{'template','flow','split','words'}):raise ValueError('服务分组方式无效')
        if 'stroke_scales' in d:
            ranges=d['stroke_scales']
            if not isinstance(ranges,dict) or set(ranges)!={'headline','main','services'}:raise ValueError('描边范围无效')
            for bounds in ranges.values():
                if not isinstance(bounds,list) or len(bounds)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds) or not 0<=bounds[0]<=bounds[1]<=.012:raise ValueError('描边范围无效')
        if d['effect'] not in {'clean','outline','shadow','glow'} or type(d['board_gradient'])!=bool:raise ValueError('文字效果无效')
        if not isinstance(d['palettes'],list) or not 1<=len(d['palettes'])<=4:raise ValueError('模板配色无效')
        for p in d['palettes']:
            if not isinstance(p,dict) or set(p)!={'ink','accent','paper'} or any(not isinstance(c,str) or not re.fullmatch('#[0-9a-fA-F]{6}',c) for c in p.values()):raise ValueError('模板颜色无效')
        for key,low,high in [('phone_scale',.055,.15),('main_scale',.045,.080),('service_scale',.027,.045)]:
            if type(d[key]) not in (int,float) or not math.isfinite(d[key]) or not low<=d[key]<=high:raise ValueError('字号层级无效')
    return s

def rgb(hexcolor):return tuple(int(hexcolor[i:i+2],16) for i in (1,3,5))+(255,)

def design_choices(structure,rng,variant):
    design=structure.get('design',{'palettes':[{'ink':'#202623','accent':'#aa281e','paper':'#fff5de'}],'effect':'outline','board_gradient':False,'phone_scale':.061,'main_scale':.049,'service_scale':.029})
    return {**design,'palette':rng.choice(design['palettes']) if variant else design['palettes'][0]}

def intersects(a,b,gap=0):return min(a[2],b[2])-max(a[0],b[0])>-gap and min(a[3],b[3])-max(a[1],b[1])>-gap

def wrap(words,font,width,separator,draw):
    lines=[];line=''
    for word in words:
        if separator=='\n':
            if line:lines.append(line)
            line=word;continue
        candidate=line+separator+word if line else word
        if draw.textlength(candidate,font=font)>width and line:lines.append(line);line=word
        else:line=candidate
    if line:lines.append(line)
    return lines

def arrange(photo,phone,services,structure,seed,variant=True,reserved=()):
    from tools.category_image_production import _font
    validate_structure(structure)
    if not isinstance(phone,str) or not phone.isdigit() or not 7<=len(phone)<=16:raise ValueError('需要已确认完整电话号码')
    if not isinstance(services,list) or len(set(services))!=len(services):raise ValueError('服务词列表无效或重复')
    if any(not isinstance(s,str) or not s.strip() or '\n' in s for s in services):raise ValueError('服务词无效')
    w,h=photo.size;draw=ImageDraw.Draw(photo);rng=random.Random(seed if variant else 0);v=structure['variables'];fonts={};zone_stats={}
    def cached_font(size,name):
        key=(size,name)
        if key not in fonts:fonts[key]=_font(size,name)
        return fonts[key]
    family=rng.choice(v['fonts']) if variant else v['fonts'][0]
    phone_lines=rng.choice(v['phone_lines']) if variant else v['phone_lines'][0]
    separator=rng.choice(v['separators']) if variant else v['separators'][0]
    spacing=rng.choice(v['spacing']) if variant else v['spacing'][0]
    design=design_choices(structure,rng,variant);valid=[]
    specs=copy.deepcopy(structure['groups'])
    grouping=rng.choice(design.get('group_modes',['template'])) if variant else 'template'
    if grouping not in {'template','words'}:
        mains=[s for s in specs if s['kind']=='main'];phone_specs=[s for s in specs if s['kind']=='phone']
        if grouping=='flow':
            if separator=='\n':separator=' · '
            specs=phone_specs+mains+[{'kind':'services','part':'rest' if structure['main_count'] else 'all','zones':['bottom_full','sky_left'],'align':rng.choice(['left','center','right']),'board':'none'}]
        else:
            specs=phone_specs+mains+[{'kind':'services','part':'a','zones':['bottom_a','top_left','side_left'],'align':'left','board':'none'},{'kind':'services','part':'b','zones':['bottom_b','top_right','side_right'],'align':'right','board':'none'}]
    ordered=list(services)
    if variant:rng.shuffle(ordered)
    n=max(0,min(structure['main_count'],len(ordered)-1));rest=ordered[n:];cut=(len(rest)+1)//2
    parts={'all':ordered,'main':ordered[:n],'rest':rest,'a':rest[:cut],'b':rest[cut:]}
    if grouping=='words':
        slots=[z for z in ZONES if z.startswith('word_')];rng.shuffle(slots)
        specs=[s for s in specs if s['kind']=='phone']
        for index,word in enumerate(ordered):
            part='word_'+str(index);parts[part]=[word]
            specs.append({'kind':'main' if index<n else 'services','part':part,'zones':slots[index%len(slots):]+slots[:index%len(slots)],'align':rng.choice(['left','center','right']),'board':'none'})
    if grouping=='template' and any(s['part']=='c' for s in specs):
        third=math.ceil(len(rest)/3);parts.update(a=rest[:third],b=rest[third:2*third],c=rest[2*third:])
    # User explicitly prioritised large readable advertising over photo avoidance.
    # Never modify scene pixels except inside the final overlay groups.
    # Reserve other text only. This does not claim person/vehicle detection.
    avoid=list(reserved)
    for attempt in range(8):
        simplify=attempt>=6 and not valid
        active_separator=' · ' if simplify else separator
        groups=[];boxes=list(reserved);failed=False
        active_specs=specs
        if simplify:
            # Long category terms cannot fit small per-word slots. Use the
            # last two attempts for complete natural wrapping at full width.
            active_specs=[s for s in specs if s['kind']=='phone']+[{'kind':'services','part':'all','zones':['upper_full','lower_full'],'align':'left','board':'none'}]
        for original_spec in active_specs:
            spec=copy.deepcopy(original_spec)
            centered=spec['kind']=='phone' and design.get('phone_center',False)
            if centered:spec.update(zones=['center_full'],align='center')
            elif variant:spec['zones']=rng.sample(spec['zones'],len(spec['zones']))
            if variant and design.get('random_boards'):spec['board']=rng.choice(['none','none','paper','soft'])
            # Explicit per-template policy wins over random backgrounds. Missing
            # policy preserves old frozen templates and their recorded styling.
            if spec['kind']=='phone' and 'headline_board' in design:spec['board']=design['headline_board']
            angle=rng.choice(design.get('rotations',[0])) if variant and spec['kind']!='phone' and not simplify else 0
            words=['电话：'+phone] if spec['kind']=='phone' and phone_lines==1 else ['电话：',phone] if spec['kind']=='phone' else parts[spec['part']]
            if not words:continue
            candidates=[]
            for zone in spec['zones']:
                a=ZONES[zone];rect=[round(a[i]*(w if i%2==0 else h)) for i in range(4)]
                if zone not in zone_stats:
                    patch=photo.crop(rect).convert('L');zone_stats[zone]=(ImageStat.Stat(patch).mean[0],ImageStat.Stat(patch.filter(ImageFilter.FIND_EDGES)).mean[0])
                brightness,texture=zone_stats[zone]
                candidates.append((spec['zones'].index(zone)*3+texture+(rng.random()*8 if variant or attempt else 0),zone,rect,brightness))
            for _,zone,rect,brightness in sorted(candidates):
                pad=max(6,round(w*.014));maxwidth=rect[2]-rect[0]-2*pad;maxheight=rect[3]-rect[1]-2*pad
                ratio=design[{'phone':'phone_scale','main':'main_scale','services':'service_scale'}[spec['kind']]]
                start=round(w*ratio*(rng.uniform(.97,1.03) if variant else 1));minimum=round(w*(.043 if spec['kind']=='phone' else .038 if spec['kind']=='main' else .031))
                for protected in avoid:
                    if rect[0]<protected[2] and rect[2]>protected[0] and rect[1]<protected[1]<rect[3]:maxheight=min(maxheight,protected[1]-rect[1]-2*pad-2)
                for size in range(start,minimum-1,-1):
                    group_family='msyh_bold' if spec['kind'] in {'phone','main'} else family
                    font=cached_font(size,group_family);lines=words if spec['kind']=='phone' and phone_lines==2 else wrap(words,font,maxwidth,active_separator,draw)
                    row_sizes=[max(20,round(size*.55)) if spec['kind']=='phone' and phone_lines==2 and i==0 else size for i in range(len(lines))]
                    widths=[math.ceil(draw.textlength(line,font=cached_font(rs,group_family))) for line,rs in zip(lines,row_sizes)];lineheight=math.ceil(size*spacing)+4
                    row_heights=[math.ceil(rs*spacing)+4 for rs in row_sizes]
                    tw=max(widths);th=sum(row_heights)
                    radians=math.radians(abs(angle));rotw=math.ceil((tw+2*pad)*math.cos(radians)+(th+2*pad)*math.sin(radians))+(4 if angle else 0);roth=math.ceil((th+2*pad)*math.cos(radians)+(tw+2*pad)*math.sin(radians))+(4 if angle else 0)
                    if tw<=maxwidth and th<=maxheight and rotw<=rect[2]-rect[0] and roth<=rect[3]-rect[1]:break
                else:continue
                x=rect[0]+pad if spec['align']=='left' else rect[2]-pad-tw if spec['align']=='right' else (rect[0]+rect[2]-tw)//2
                extra_x=math.ceil((rotw-tw-2*pad)/2);extra_y=math.ceil((roth-th-2*pad)/2)
                x=max(rect[0]+pad+extra_x,min(rect[2]-pad-tw-extra_x,x))
                y=(h-th)//2 if centered else rect[1]+pad+extra_y
                for occupied in boxes:
                    if x-pad<occupied[2] and x+tw+pad>occupied[0] and occupied[1]<=y+th+pad and occupied[3]>=y-pad:y=occupied[3]+round(w*.012)+pad
                if y+th+pad>rect[3]:continue
                if variant and not centered:
                    x=max(rect[0]+pad+extra_x,min(rect[2]-pad-tw-extra_x,x+round(rng.uniform(-v['offset'],v['offset'])*w)))
                    y=min(rect[3]-pad-th-extra_y,y+round(rng.random()*v['offset']*h))
                box=[x-pad-extra_x,y-pad-extra_y,x+tw+pad+extra_x,y+th+pad+extra_y]
                if box[0]<rect[0] or box[2]>rect[2] or box[1]<rect[1] or box[3]>rect[3]:continue
                local=photo.crop(box).convert('L');local_texture=ImageStat.Stat(local.filter(ImageFilter.FIND_EDGES)).mean[0]
                if any(intersects(box,b,round(w*.01)) for b in boxes) or any(intersects(box,b) for b in avoid):continue
                color=(23,25,24,255) if brightness>128 or spec['board']=='paper' else (250,250,246,255)
                palette=design['palette']
                if spec['board']=='paper':
                    color=rgb(palette['accent'] if spec['kind'] in {'phone','main'} else palette['ink'])
                elif spec['kind'] in {'phone','main'}:
                    color=(255,227,91,255) if brightness<120 else rgb(palette['accent'])
                else:color=(255,255,246,255)
                if variant:
                    color=rng.choice([rgb(palette['accent']),rgb(palette['ink'])]) if spec['board']=='paper' else rng.choice([rgb(palette['accent']),(255,255,246,255),(255,227,91,255)]) if spec['board']=='none' else color
                board=spec['board'];contrast='adaptive black/white + light outline' if board=='none' else 'local adaptive backing'
                bounds=design.get('stroke_scales',{'headline':[.006,.009],'main':[.005,.008],'services':[.003,.006]})['headline' if spec['kind']=='phone' else spec['kind']]
                stroke=round(w*(rng.uniform(*bounds) if variant else sum(bounds)/2))
                dark=sum(color[:3])<480
                outline=rng.choice([(255,255,247,255),rgb(palette['paper']),(255,239,150,255)] if dark else [(15,20,17,255),rgb(palette['ink']),rgb(palette['accent'])]) if variant else ((255,255,247,255) if dark else (15,20,17,255))
                effect=design['effect']
                if board=='none' and stroke==0:effect='shadow';color=(255,255,246,255) if brightness<100 else rgb(palette['ink'])
                group={'kind':spec['kind'],'part':spec['part'],'words':words,'lines':lines,'box':box,'zone':zone,'font_size':size,'font_family':group_family,'row_sizes':row_sizes,'row_heights':row_heights,'spacing':spacing,'align':spec['align'],'color':color,'board':board,'contrast':contrast,'line_height':lineheight,'pad':pad,'stroke':stroke,'outline_color':outline,'texture_score':round(local_texture,2),'effect':effect,'palette':palette,'board_gradient':design['board_gradient'],'angle':angle,'unrotated_size':[tw+2*pad,th+2*pad]}
                lum=((brightness/255+.055)/1.055)**2.4
                foreground=.008 if color[0]<128 else .95
                group['contrast_estimate']=round((max(lum,foreground)+.05)/(min(lum,foreground)+.05),2)
                groups.append(group);boxes.append(box);break
            else:failed=True;break
        if not failed:
            # Soft ranking never substitutes for content/boundary gates or visual review.
            coverage=sum((b[2]-b[0])*(b[3]-b[1]) for b in boxes)/(w*h)
            score=round(sum(g['font_size']/w*(2 if g['kind']=='phone' else 1) for g in groups)*100,3)
            valid.append((score,groups,{'attempts':8,'selected_attempt':attempt+1,'candidate_score':score,'text_coverage':round(coverage,4),'grouping':'flow_fit' if simplify else grouping,'fallback':False,'phone_lines':phone_lines,'separator':active_separator,'service_order':ordered,'avoid_regions':avoid,'design':design,'avoidance':'photo avoidance disabled by user; prioritise large readable type, retain text boundary and overlap checks'}))
    if valid:
        _,groups,meta=max(valid,key=lambda candidate:candidate[0]);meta['valid_candidates']=len(valid);return groups,meta
    return None,{'attempts':8,'fallback':True,'reason':'模板候选区域无法容纳全部文字或存在冲突','service_order':ordered,'avoidance':'safe appended caption; original photo unobscured'}

def theme_groups(photo,labels,structure,seed,variant,settings,occupied=()):
    """Task-bound captions, styled by the selected template, clipped per cell."""
    from tools.category_image_production import _font
    if not settings.get('enabled') or not labels:return []
    w,h=photo.size;draw=ImageDraw.Draw(photo);rng=random.Random(str(seed)+':themes' if variant else 'themes:base')
    design=design_choices(structure,rng,variant);palette=design['palette'];groups=[]
    for index,label in enumerate(labels):
        text=label['text']
        if not isinstance(text,str) or not text.strip() or '\n' in text or len(text)>60:raise ValueError('缺少有效冻结图片主题')
        cell=label['panel'];cw,ch=cell[2]-cell[0],cell[3]-cell[1];pad=max(8,round(w*.014))
        ratio=settings.get('panel_font_ratio',.038) if len(labels)>1 else settings.get('font_ratio',.048)
        font_family='msyh_bold';minimum=max(18,round(w*.024));stroke=max(2,round(w*.004))
        maxwidth=cw-4*pad;maxheight=min(ch-4*pad,round(h*.10))
        align=rng.choice(settings.get('alignments',['left','right','center'])) if variant else settings.get('alignments',['left'])[0]
        blocked=[*occupied,*[g['box'] for g in groups]];box=None
        for size in range(round(w*ratio),minimum-1,-1):
            font=_font(size,font_family);tw=math.ceil(draw.textlength(text,font=font));th=math.ceil(size*1.35)+4
            if tw+2*stroke>maxwidth or th>maxheight:continue
            gw,gh=tw+2*pad,th+2*pad
            x=cell[0]+pad if align=='left' else cell[2]-pad-gw if align=='right' else (cell[0]+cell[2]-gw)//2
            positions=[cell[1]+pad,cell[3]-pad-gh,*[cell[1]+round((ch-gh)*fraction) for fraction in (.2,.4,.6,.8)]]
            for y in positions:
                candidate=[x,y,x+gw,y+gh]
                if y<cell[1]+pad or y+gh>cell[3]-pad:continue
                if not any(intersects(candidate,b,4) for b in blocked):box=candidate;break
            if box:break
        if box is None:raise ValueError('无法同时显示完整图片主题与其他文字，保留原成品')
        board=rng.choice(settings.get('boards',['none','soft','paper'])) if variant else settings.get('boards',['none'])[0]
        color=rgb(palette['accent']) if board=='paper' else (255,255,246,255)
        outline=(255,255,247,255) if sum(color[:3])<480 else rgb(palette['ink'])
        groups.append({'kind':'theme','part':'theme_'+str(index),'text':text,'words':[text],'lines':[text],'panel_index':label.get('panel_index'),'panel':list(cell),'box':box,'font_size':size,'font_family':font_family,'row_sizes':[size],'row_heights':[th],'align':align,'pad':pad,'line_height':th,'color':color,'board':board,'stroke':stroke,'outline_color':outline,'effect':design['effect'],'palette':palette,'board_gradient':design['board_gradient'],'zone':'panel_top' if y==positions[0] else 'panel_local','angle':0})
    return groups

def render(photo,phone,services,template,seed,variant=True,themes=(),theme_settings=None):
    from tools.category_image_production import _font
    photo=photo.convert('RGB');groups,meta=arrange(photo,phone,services,template['structure'],seed,variant)
    try:captions=theme_groups(photo,themes,template['structure'],seed,variant,theme_settings or {},occupied=[g['box'] for g in groups or []])
    except ValueError:
        # One bounded re-layout reserves task captions before services. The
        # phone stays centred; fallback never drops a caption or service word.
        captions=theme_groups(photo,themes,template['structure'],seed,variant,theme_settings or {},occupied=[g['box'] for g in groups or [] if g['kind']=='phone'])
        groups,meta=arrange(photo,phone,services,template['structure'],seed,variant,reserved=[g['box'] for g in captions])
    w,h=photo.size
    if groups is None:
        # Deterministic, non-obscuring fallback outside the original photograph.
        font=_font(round(w*.037),'msyh_bold');draw=ImageDraw.Draw(photo);lines=wrap(services,font,round(w*.93),' · ',draw);pad=round(w*.025);lineheight=round(w*.052)
        footer=pad*2+round(w*.095)+lineheight*len(lines)
        result=Image.new('RGB',(w,h+footer),(246,244,237));result.paste(photo,(0,0));groups=[{'kind':'phone','part':'phone','words':['电话：'+phone],'lines':['电话：'+phone],'box':[pad,h+pad,w-pad,h+pad+round(w*.095)],'font_size':round(w*.07),'font_family':'msyh_bold','spacing':1.3,'align':'left','color':(180,40,30,255),'board':'none','line_height':round(w*.095),'pad':0,'zone':'fallback_footer'},{'kind':'services','part':'all','words':services,'lines':lines,'box':[pad,h+pad+round(w*.095),w-pad,h+footer-pad],'font_size':round(w*.037),'font_family':'msyh_bold','spacing':1.3,'align':'left','color':(23,25,24,255),'board':'none','line_height':lineheight,'pad':0,'zone':'fallback_footer'}]
        # Even fallback cannot clip an unusually long phone or service word.
        if any(ImageDraw.Draw(result).textlength(line,font=_font(g['font_size'],g['font_family']))>g['box'][2]-g['box'][0] for g in groups for line in g['lines']):raise ValueError('文字过长，保底布局不能保证可读；保留原成品')
    else:result=photo.copy()
    layer=Image.new('RGBA',result.size)
    for g in [*captions,*groups]:
        # All decorations are clipped to their already validated local group bounds.
        box=g['box'];pad=g['pad'];reserved_width=box[2]-box[0];reserved_height=box[3]-box[1];gw,gh=g.get('unrotated_size',[reserved_width,reserved_height])
        local=Image.new('RGBA',(gw,gh));draw=ImageDraw.Draw(local)
        if g['board']!='none':
            base=rgb(g.get('palette',{}).get('paper','#fff5de')) if g['board']=='paper' else ((20,23,22,255) if sum(g['color'][:3])>480 else (247,247,242,255))
            for y in range(gh):
                factor=(1-.10*y/max(1,gh-1)) if g.get('board_gradient') else 1
                draw.line((0,y,gw,y),fill=tuple(round(c*factor) for c in base[:3])+(242 if g['board']=='paper' else 208,))
            if g['board']=='paper':draw.rectangle((0,0,max(2,round(w*.004)),gh),fill=rgb(g.get('palette',{}).get('accent','#aa281e')))
        mask=Image.new('L',(gw,gh));mdraw=ImageDraw.Draw(mask);outline_mask=Image.new('L',(gw,gh));odraw=ImageDraw.Draw(outline_mask);cursor=pad
        for row,line in enumerate(g['lines']):
            font=_font(g.get('row_sizes',[g['font_size']]*len(g['lines']))[row],g['font_family'])
            width=draw.textlength(line,font=font);x=pad if g['align']=='left' else gw-pad-width if g['align']=='right' else (gw-width)/2
            mdraw.text((x,cursor),line,font=font,fill=255,anchor='lt')
            odraw.text((x,cursor),line,font=font,fill=255,stroke_width=g.get('stroke',1),stroke_fill=255,anchor='lt')
            cursor+=g.get('row_heights',[g['line_height']]*len(g['lines']))[row]
        effect=g.get('effect','clean');dark=sum(g['color'][:3])<480
        if effect in {'shadow','glow'}:
            blur=mask.filter(ImageFilter.GaussianBlur(max(1,w*.0025)))
            shadow=Image.new('RGBA',(gw,gh),(255,251,228,210) if effect=='glow' and dark else (0,0,0,170))
            shadow.putalpha(blur.point(lambda a:round(a*.65)));local.alpha_composite(shadow,(0 if effect=='glow' else 2,0 if effect=='glow' else 2))
        if g.get('stroke',0)>0 or (effect in {'outline','glow'} or (g['board']=='none' and not meta['fallback'])):
            border=Image.new('RGBA',(gw,gh),tuple(g.get('outline_color',(255,255,247,255) if dark else (15,20,17,255))));border.putalpha(outline_mask);local.alpha_composite(border)
        ink=Image.new('RGBA',(gw,gh),g['color']);ink.putalpha(mask);local.alpha_composite(ink)
        if g.get('angle'):local=local.rotate(g['angle'],resample=Image.Resampling.BICUBIC,expand=True)
        if local.width>reserved_width or local.height>reserved_height:raise ValueError('旋转文字超出预留区域，保留原成品')
        layer.alpha_composite(local,(box[0]+(reserved_width-local.width)//2,box[1]+(reserved_height-local.height)//2))
    result=Image.alpha_composite(result.convert('RGBA'),layer).convert('RGB')
    meta.update(template_id=template['id'],family=template['structure']['family'],seed=seed,variant=variant,groups=groups,theme_labels=captions,photo_size=[w,h],final_size=list(result.size),service_items=services,phone=phone)
    return result,meta

def render_delivery(photo,target,phone,services,frozen,role,category,sources,extra=None):
    from tools import task_library as lib
    template=frozen['template'];seed=frozen.get('layout_seed',0)
    extra=extra or {};themes=[]
    if role=='triptych':
        themes=[{'text':text,'panel':box,'panel_index':i+1} for i,(text,box) in enumerate(zip(extra.get('panel_service_roles',[]),extra.get('panels',[])))]
    elif role!='cover' and extra.get('service_role') and category!='business_ktv' and not (category=='diving_salvage' and extra['service_role']=='滞空入水动作预览'):
        themes=[{'text':extra['service_role'],'panel':[0,0,*photo.size]}]
    result,layout=render(photo,phone,services,template,seed,frozen.get('layout_variant',True),themes,frozen['parameters'].get('theme',{}))
    lib.io_path(target.parent).mkdir(parents=True,exist_ok=True);temporary=lib.io_path(target.with_suffix('.part.png'));result.save(temporary,format='PNG',optimize=True);temporary.replace(lib.io_path(target))
    phone_group=next(g for g in layout['groups'] if g['kind']=='phone')
    validation={**extra,'schema_version':1,'category_id':category,'role':role,'final_size':list(result.size),'status':'needs_user_review','approved':False,'expected_text':['电话：'+phone,*services,*[g['text'] for g in layout['theme_labels']],*(['联系电话：'+phone] if role=='cover' and extra.get('signboard_phone_required',True) else [])],
        'overlay_style':{'signboard_style':'preserved_source_signboard','layout_family':layout['family']},
        'postprocess_record':{'sources':[str(p) for p in sources],'rules':copy.deepcopy(frozen),'phone':{'text':'电话：'+phone,'box':phone_group['box'],'font_size':phone_group['font_size'],'font_family':phone_group['font_family'],'color':phone_group['color'],'board':phone_group['board'],'background':None if phone_group['board']=='none' else phone_group.get('palette',{}),'stroke':phone_group.get('stroke',0),'outline_color':phone_group.get('outline_color')},'services':{'items':list(services),'layout':'independent_text_groups'},'themes':layout['theme_labels'],'layout':layout,'crop':{'mode':'unchanged'}}}
    lib.write(target.with_suffix('.validation.json'),validation)
    return validation
