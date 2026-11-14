"""Private, project-scoped original stock and explicit adoption provenance."""
import hashlib
import math
import re
from pathlib import Path
from PIL import Image
from tools import task_library as lib


def file_hash(path):
    h=hashlib.sha256()
    with lib.io_path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def confined(path):
    from tools.task_actions import confined as check
    return check(path)


def source_category(raw):
    from tools.task_assets import roots
    path=Path(raw).absolute()
    for root in sorted(roots()|{lib.ROOT/'.runtime/image-work'},key=lambda r:len(r.parts),reverse=True):
        try:category=path.relative_to(root).parts[0]
        except (ValueError,IndexError):continue
        lib.category_dir(category);return category
    raise ValueError('原图不属于登记的项目资产位置')


def proof_file(raw,suffix,category=None):
    from tools.postprocess_view import confined as category_confined
    return category_confined(Path(raw).with_suffix(suffix),category or source_category(raw))


def folder(request):
    from tools.task_assets import settings,roots
    category=request['category'];lib.category_dir(category)
    current=Path(settings()['path']).resolve()
    choices=[{'id':lib.digest(str(root)),'path':str(root/'原图库'/category),'current':root==current} for root in sorted(roots(),key=str)]
    selected=next((v for v in choices if v['id']==request.get('root_id')),None) if request.get('root_id') else next(v for v in choices if v['current'])
    if selected is None:raise ValueError('图库根目录未登记')
    target=confined(Path(selected['path']))
    if selected['current']:
        lib.io_path(target).mkdir(parents=True,exist_ok=True)
        for name in ('门头','详情'):lib.io_path(confined(target/name)).mkdir(exist_ok=True)
    elif not lib.io_path(target).is_dir():raise ValueError('该旧资产根尚无原图库目录')
    return {'path':str(target.resolve()),'roots':choices,'root_id':selected['id']}


def index_file(category,asset):
    lib.category_dir(category)
    if not isinstance(asset,str) or not re.fullmatch(r'[a-f0-9]{64}',asset):raise ValueError('素材登记标识无效')
    return lib.ROOT/'.runtime/raw_library'/category/(asset+'.json')


def load(category,asset):
    file=index_file(category,asset)
    if lib.io_path(file).stat().st_size>1024*1024:raise ValueError('原图库登记记录超过读取上限')
    value=lib.read(file)
    if not isinstance(value,dict) or value.get('id')!=asset or value.get('category')!=category:raise ValueError('原图库素材身份不一致')
    if (value.get('kind') not in {'cover','detail'} or not isinstance(value.get('theme'),str) or
        value.get('eligibility') not in {'eligible','rejected','unconfirmed'} or not isinstance(value.get('created_at'),str) or
        not isinstance(value.get('source'),dict)):
        raise ValueError('原图库登记信息缺失或无效')
    legacy=value['source'].get('kind')=='legacy'
    if value['kind']=='cover' and not (legacy and value.get('phone') is None) and (not isinstance(value.get('phone'),str) or not re.fullmatch(r'1\d{10}',value['phone'])):
        raise ValueError('门头素材缺少已确认手机号')
    source=value['source']
    if (not isinstance(source.get('batch'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',source['batch']) or
        type(source.get('group')) is not int or source['group']<1 or not isinstance(source.get('unit'),str) or
        not (legacy and source.get('prompt_sha256') is None) and (not isinstance(source.get('prompt_sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',source['prompt_sha256']))):
        raise ValueError('原图库来源身份无效')
    if legacy and (source.get('batch')!='legacy' or not isinstance(source.get('registration'),dict) or not isinstance(value.get('missing_information'),list)):
        raise ValueError('历史原图库登记依据缺失')
    for key in ('path','original_path','receipt_path','thumbnail'):
        if legacy and key=='receipt_path' and value.get(key) is None:continue
        if not isinstance(value.get(key),str):raise ValueError('原图库文件登记缺失')
        confined(value[key])
    for key in ('raw_sha256','original_sha256','receipt_sha256'):
        if legacy and key=='receipt_sha256' and value.get('receipt_path') is None and value.get(key) is None:continue
        if not isinstance(value.get(key),str) or not re.fullmatch(r'[a-f0-9]{64}',value[key]):raise ValueError('原图库素材摘要无效')
    return value


def records(category):
    """One bad record must not hide good inventory or become a candidate."""
    for file in lib.io_glob(lib.ROOT/'.runtime/raw_library'/category,'*.json'):
        try:yield load(category,file.stem)
        except (OSError,ValueError,KeyError,TypeError):
            yield {'id':file.stem,'category':category,'kind':'unknown','theme':'','eligibility':'invalid',
                'created_at':'','technical_valid':False,'invalid_reason':'登记损坏或路径无效，原记录已保留'}


def valid(value):
    try:
        for key in ('path','original_path','receipt_path'):
            if value.get(key) is not None:confined(value[key])
        return (file_hash(value['path'])==value['raw_sha256'] and
            file_hash(value['original_path'])==value['original_sha256'] and
            (value.get('source',{}).get('kind')=='legacy' and value.get('receipt_path') is None and value.get('receipt_sha256') is None or
             file_hash(value['receipt_path'])==value['receipt_sha256']))
    except (OSError,ValueError,KeyError,TypeError):return False


def ensure_thumbnail(value):
    path=confined(value['thumbnail'])
    try:
        with Image.open(lib.io_path(path)) as im:im.verify()
        return
    except (OSError,ValueError):pass
    with Image.open(lib.io_path(confined(value['path']))) as im:
        im=im.convert('RGB');im.thumbnail((240,360));output=path.with_suffix('.jpg.part')
        im.save(lib.io_path(output),'JPEG',quality=80);lib.io_path(output).replace(lib.io_path(path))


def register(category,batch,group,unit):
    from tools.task_worker import raw_evidence_valid
    from tools.postprocess_view import confined as category_confined
    raw=category_confined(lib.unit_raw(category,batch,group,unit),category)
    for suffix in ('.receipt.json','.adoption.json','.inherited.json'):
        category_confined(raw.with_suffix(suffix),category)
    if not raw_evidence_valid(raw,unit):raise ValueError('原图缺少有效来源凭据，不能入库')
    if lib.io_path(raw.with_suffix('.adoption.json')).exists():return load(category,lib.read(raw.with_suffix('.adoption.json'))['asset'])
    inherited=unit.get('inherited_raw')
    if inherited and inherited.get('asset'):return load(category,inherited['asset'])
    receipt=lib.read(raw.with_suffix('.receipt.json'))
    if receipt.get('adoption'):return load(category,receipt['adoption']['asset'])
    source_info=receipt.get('source',{})
    if not isinstance(source_info,dict):raise ValueError('原图来源收据无效')
    source=category_confined(source_info.get('provider_original') or raw,category)
    if not lib.io_path(source).is_file():raise ValueError('最高分辨率源图缺失，保留工作图等待本地恢复')
    if lib.io_path(source).stat().st_size>64*1024*1024:raise ValueError('源图超过安全归档上限')
    original_hash=file_hash(source);raw_hash=file_hash(raw)
    if source_info.get('provider_original') and source_info.get('source_sha256')!=original_hash:
        raise ValueError('最高分辨率原图与来源收据摘要不一致，不能入库')
    original_status='provider_original' if source_info.get('provider_original') else 'working_only'
    # Old standard-size records may contain only a re-encoded working PNG.
    # Its hash is not the provider payload hash; never fabricate that equivalence.
    if not source_info.get('provider_original') and source_info.get('saved_raw_sha256') and source_info['saved_raw_sha256']!=raw_hash:
        raise ValueError('工作图与来源收据摘要不一致，不能入库')
    with Image.open(lib.io_path(source)) as im:
        width,height=im.size
        if not 0<width<=16384 or not 0<height<=16384 or width*height>40000000:raise ValueError('源图超过像素安全上限')
        im.load()
    if source_info.get('source_returned_size') and source_info['source_returned_size']!=f'{width}x{height}':
        raise ValueError('原图尺寸与来源收据不一致')
    _,data=lib.load_batch(category,batch)
    kind='cover' if unit['kind']=='cover' else 'detail';theme=unit.get('service_role') or ''
    asset=lib.digest({'category':category,'original':original_hash,'kind':kind,'theme':theme,'phone':data['phone'] if kind=='cover' else None})
    file=index_file(category,asset)
    with lib.lock(file.with_suffix('.lock'),wait_seconds=10):
        if lib.io_path(file).exists():
            try:old=load(category,asset)
            except (OSError,ValueError,KeyError,TypeError):old=None
            if old and valid(old):
                if receipt.get('mock') is True:
                    old['missing_information']=sorted(set([*old.get('missing_information',[]),'模拟素材不能自动复用']));old['eligibility']='unconfirmed';lib.write(file,old)
                ensure_thumbnail(old);return old
            # Do not replace damaged registration/evidence while repairing an archive.
            raise ValueError('已有素材登记或归档失效，保留记录等待本地修复')
        base=Path(folder({'category':category})['path'])/('门头' if kind=='cover' else '详情')
        if kind=='detail':base=base/re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',theme or '未标注主题')[:70].rstrip('. ')
        base=confined(base/asset)
        from tools.category_4k_raw import publish_immutable_bytes
        path=base/'work.png';original=base/('original'+source.suffix.lower());proof=base/'receipt.json';thumb=base/'thumbnail.jpg'
        publish_immutable_bytes(path,lib.io_path(raw).read_bytes())
        publish_immutable_bytes(original,lib.io_path(source).read_bytes())
        publish_immutable_bytes(proof,lib.io_path(raw.with_suffix('.receipt.json')).read_bytes())
        if not lib.io_path(thumb).exists():
            with Image.open(lib.io_path(path)) as im:
                im=im.convert('RGB');im.thumbnail((240,360));im.save(lib.io_path(thumb),'JPEG',quality=80)
        result={'id':asset,'category':category,'kind':kind,'theme':theme,'phone':data['phone'] if kind=='cover' else None,
            'path':str(path),'original_path':str(original),'thumbnail':str(thumb),'receipt_path':str(proof),
            'raw_sha256':raw_hash,'original_sha256':original_hash,'receipt_sha256':file_hash(proof),
            'source':inherited['source'] if inherited else {'batch':batch,'group':group,'unit':unit['id'],'prompt_sha256':unit['prompt_sha256']},
            'original_size':[width,height],'working_size':[1024,1536],'original_status':original_status,
            'review':{'decision':'unreviewed','basis':None},'uses':[],
            'eligibility':'unconfirmed','qualification':None,'created_at':lib.now(),
            'missing_information':['模拟素材不能自动复用'] if receipt.get('mock') is True else []}
        lib.write(file,result);return result


def view(request):
    category=request['category'];lib.category_dir(category)
    if request.get('selection') not in (None,'pending'):raise ValueError('原图库选择范围错误')
    offset=request.get('offset',0);limit=request.get('limit',40)
    if type(offset)!=int or offset<0 or type(limit)!=int or not 1<=limit<=100:raise ValueError('分页参数错误')
    entries=[]
    for value in records(category):
        if request.get('kind') and value['kind']!=request['kind']:continue
        if request.get('theme') and value['theme']!=request['theme']:continue
        entries.append(value)
    entries.sort(key=lambda v:v['created_at'],reverse=True)
    checked=[{**v,'technical_valid':valid(v)} for v in entries]
    counts={'total':len(entries),'eligible':sum(v['eligibility']=='eligible' and v['technical_valid'] and content_ready(v) for v in checked),
        'invalid':sum(not v['technical_valid'] for v in checked)}
    if request.get('selection')=='pending':
        ids=[v['id'] for v in checked if v['eligibility']=='unconfirmed' and v['technical_valid'] and content_ready(v)]
        return {'entries':[],'selected_ids':ids,'counts':counts,'offset':0,'has_more':False}
    return {'entries':[{**v,'can_qualify':v['technical_valid'] and content_ready(v)} for v in checked[offset:offset+limit]],'counts':counts,'offset':offset,'has_more':offset+limit<len(entries)}


def content_ready(value):
    """Unknown content/provenance cannot become an automatic reuse candidate."""
    source=value.get('source',{})
    return (value.get('kind') in {'cover','detail'} and not value.get('missing_information') and
        isinstance(source.get('prompt_sha256'),str) and bool(re.fullmatch(r'[a-f0-9]{64}',source['prompt_sha256'])) and
        bool(value.get('receipt_path')) and bool(value.get('receipt_sha256')) and
        (value['kind']=='cover' and isinstance(value.get('phone'),str) and bool(re.fullmatch(r'1\d{10}',value['phone'])) or
         value['kind']=='detail' and isinstance(value.get('theme'),str) and bool(value['theme'].strip())))


def qualify(request):
    category=request['category'];eligible=request.get('eligible');lib.category_dir(category)
    if type(eligible)!=bool or request.get('authorization')!='confirm_raw_reuse':raise ValueError('需要对素材内容及可复用资格的明确确认')
    if 'assets' not in request:return qualify_one(category,request['asset'],eligible,request.get('source','agent'))
    assets=request['assets']
    if 'asset' in request or not isinstance(assets,list) or not 1<=len(assets)<=100 or len(set(a for a in assets if isinstance(a,str)))!=len(assets):
        raise ValueError('批量复用确认须提供1–100个不重复的登记标识')
    # Validate the whole identifier list before writing any registration.
    for asset in assets:index_file(category,asset)
    result={'requested':len(assets),'updated':0,'unchanged':0,'succeeded':[],'failed':[]}
    for asset in assets:
        try:
            value,changed=qualify_one(category,asset,eligible,request.get('source','agent'),with_change=True)
            result['updated' if changed else 'unchanged']+=1;result['succeeded'].append(value['id'])
        except (OSError,ValueError,KeyError,TypeError):
            result['failed'].append({'asset':asset,'reason':'invalid_or_unavailable','message':'素材记录、文件或内容依据不可用，请单张核对'})
    return result


def qualify_one(category,asset,eligible,source,with_change=False):
    file=index_file(category,asset)
    with lib.lock(file.with_suffix('.lock'),wait_seconds=10):
        value=load(category,asset)
        if eligible and not valid(value):raise ValueError('素材或来源凭据已改变，不能确认复用')
        if eligible and not content_ready(value):raise ValueError('素材缺少主题、确认号码或原始来源依据，不能确认复用')
        target='eligible' if eligible else 'rejected'
        changed=value['eligibility']!=target
        if changed:
            value.update(eligibility=target,qualification={'kind':'explicit_content_review','confirmed_at':lib.now(),'source':source,'original_sha256':value['original_sha256'],'raw_sha256':value['raw_sha256']})
            lib.write(file,value)
        return (value,changed) if with_change else value


def reuse_rate(value):
    if value in (None,''):return 0
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100:raise ValueError('原图复用率须为 0–100 的数字')
    return value


def choose(category,data,rows,rate):
    units=[(r['group'],u) for r in rows for u in r['units']];target=math.floor(len(units)*rate/100)
    if not target:return {'rate':rate,'target':0,'actual':0,'shortfall':0,'bindings':[]}
    entries=list(records(category))
    eligible=sorted((v for v in entries if v['eligibility']=='eligible' and content_ready(v) and valid(v)),key=lambda v:v['id'])
    bindings=[];used=set()
    for group,unit in units:
        if len(bindings)>=target:break
        kind='cover' if unit['kind']=='cover' else 'detail';theme=unit.get('service_role') or ''
        match=next((v for v in eligible if v['original_sha256'] not in used and v['kind']==kind and (kind=='cover' and v['phone']==data['phone'] or kind=='detail' and v['theme']==theme)),None)
        if match:
            used.add(match['original_sha256']);bindings.append({'unit':unit['id'],'group':group,'asset':match['id'],'raw_sha256':match['raw_sha256'],'original_sha256':match['original_sha256'],'receipt_sha256':match['receipt_sha256']})
    return {'rate':rate,'target':target,'actual':len(bindings),'shortfall':target-len(bindings),'bindings':bindings}


def selection(data):
    path=lib.batch_dir(data['category'],data['id'])/'raw-reuse.json'
    if not data.get('raw_reuse_sha256'):return {'rate':0,'target':0,'actual':0,'shortfall':0,'bindings':[]}
    value=lib.read(path)
    if lib.digest(value)!=data['raw_reuse_sha256']:raise ValueError('冻结复用清单已改变')
    return value


def validate_binding(category,data,unit,binding):
    value=load(category,binding['asset'])
    if value['eligibility']!='eligible' or not content_ready(value) or not valid(value):raise ValueError('复用素材资格或文件已改变，请重新核对批次选图和额度')
    kind='cover' if unit['kind']=='cover' else 'detail'
    if value['kind']!=kind or (kind=='cover' and value['phone']!=data['phone']) or (kind=='detail' and value['theme']!=(unit.get('service_role') or '')):raise ValueError('复用素材项目、主题或门头电话不匹配')
    if any(value[k]!=binding[k] for k in ('raw_sha256','original_sha256','receipt_sha256')):raise ValueError('复用素材指纹已改变')
    return value


def adopt(category,data,rows):
    bindings={b['unit']:b for b in selection(data)['bindings']}
    targets=[(r['group'],u,bindings[u['id']]) for r in rows for u in r['units'] if u['id'] in bindings]
    # Verify the entire frozen selection before writing any adoption.
    checked=[(g,u,b,validate_binding(category,data,u,b)) for g,u,b in targets]
    from tools.category_4k_raw import publish_immutable_bytes
    for group,unit,binding,value in checked:
        raw=confined(lib.unit_raw(category,data['id'],group,unit))
        publish_immutable_bytes(raw,lib.io_path(value['path']).read_bytes())
        proof={'category':category,'batch':data['id'],'unit':unit['id'],'asset':value['id'],
            'source':value['source'],'source_receipt_sha256':value['receipt_sha256'],
            'raw_sha256':value['raw_sha256'],'target_snapshot_sha256':data['snapshot_sha256'],'adopted_at':lib.now()}
        receipt=raw.with_suffix('.receipt.json')
        if not lib.io_path(receipt).exists():publish_immutable_bytes(receipt,lib.io_path(value['receipt_path']).read_bytes())
        lib.write(raw.with_suffix('.adoption.json'),proof)
        record_use(category,value['id'],data,group,unit)


def record_use(category,asset,data,group,unit):
    file=index_file(category,asset)
    use={'batch':data['id'],'group':group,'unit':unit['id'],'snapshot_sha256':data['snapshot_sha256']}
    with lib.lock(file.with_suffix('.lock'),wait_seconds=10):
        value=load(category,asset);uses=value.setdefault('uses',[])
        if not isinstance(uses,list):raise ValueError('图库使用记录损坏，保留素材等待修复')
        key=lib.digest(use)
        if not any(isinstance(item,dict) and item.get('id')==key for item in uses):
            uses.append({**use,'id':key,'at':lib.now()});lib.write(file,value)


def adoption_valid(raw,unit):
    try:
        proof=lib.read(proof_file(raw,'.adoption.json'))
        if proof['category']!=source_category(raw):return False
        path,data=lib.load_batch(proof['category'],proof['batch'])
        binding=next(b for b in selection(data)['bindings'] if b['unit']==unit['id'] and b['asset']==proof['asset'])
        expected=lib.unit_raw(proof['category'],proof['batch'],binding['group'],unit)
        return (expected.resolve()==raw.resolve() and proof['unit']==unit['id'] and
            proof['target_snapshot_sha256']==data['snapshot_sha256'] and
            proof['raw_sha256']==binding['raw_sha256']==file_hash(raw) and
            proof['source_receipt_sha256']==binding['receipt_sha256']==file_hash(raw.with_suffix('.receipt.json')))
    except (OSError,ValueError,KeyError,TypeError,StopIteration):return False


def inheritance_valid(raw,unit):
    """The frozen manifest binds inherited bytes, without rewriting a source receipt."""
    try:
        proof=lib.read(proof_file(raw,'.inherited.json'))
        if proof['category']!=source_category(raw):return False
        path,data=lib.load_batch(proof['category'],proof['batch'])
        frozen=next(u for r in lib.selected(path,data,[1]) for u in r['units'] if u['id']==unit['id'])
        binding=frozen['inherited_raw']
        return (unit==frozen and proof['unit']==unit['id'] and proof['binding_sha256']==lib.digest(binding) and
            proof['snapshot_sha256']==data['snapshot_sha256'] and
            raw.resolve()==lib.unit_raw(proof['category'],proof['batch'],1,unit).resolve() and
            file_hash(raw)==binding['raw_sha256'] and file_hash(raw.with_suffix('.receipt.json'))==binding['receipt_sha256'])
    except (OSError,ValueError,KeyError,TypeError,StopIteration):return False


def reindex(request):
    from tools.raw_library_history import reindex as history_index
    return history_index(request)
