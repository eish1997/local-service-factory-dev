"""Shared asset location and image-only archive operations. No generation."""
import os
from pathlib import Path
import secrets
import zipfile
from tools import task_library as lib


def settings():
    file=lib.ROOT/'.runtime/asset_settings.json'
    return lib.read(file) if file.exists() else {'path':str((lib.ROOT/'output').resolve()),'previous_paths':[]}


def roots():
    value=settings()
    return {Path(p).resolve() for p in [str(lib.ROOT/'output'),value['path'],*value.get('previous_paths',[])]}


def save(request):
    value=request.get('path')
    if not isinstance(value,str) or not Path(value).is_absolute():raise ValueError('请选择绝对目录路径')
    target=Path(value).resolve()
    install=os.environ.get('FACTORY_INSTALL_HOME')
    if install and (target==Path(install).resolve() or Path(install).resolve() in target.parents):raise ValueError('资产路径不能位于软件安装目录内，请选择独立的图片目录')
    if not target.is_dir():raise ValueError('资产目录不存在')
    if target==Path(target.anchor) or target==lib.ROOT.resolve():raise ValueError('请选择专用资产目录，不能使用磁盘根目录或代码根目录')
    for name in ('projects','prompts','configs','.runtime','.agents','dashboard'):
        protected=(lib.ROOT/name).resolve()
        if target==protected or protected in target.parents:raise ValueError('不能将资产写入配置或程序目录')
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
        # Existing batches stay bound to their old roots; running tasks are unaffected.
        probe=target/('.asset-write-'+secrets.token_hex(8))
        try:probe.write_bytes(b'')
        finally:
            if probe.exists():probe.unlink()
        old=settings();previous=sorted({old['path'],*old.get('previous_paths',[])}-{str(target)})
        result={'path':str(target),'previous_paths':previous,'updated_at':lib.now()}
        lib.write(lib.ROOT/'.runtime/asset_settings.json',result)
        return result


def batch_root(data):
    root=Path(data.get('asset_root') or lib.ROOT/'output').resolve()
    if root not in roots():raise ValueError('批次资产根目录未登记')
    return root


def folder(request):
    category=lib.identifier(request['category']);lib.category_dir(category)
    scope=request.get('scope','batch');batch=request.get('batch','legacy')
    if scope not in {'project','batch','group','image'}:raise ValueError('目录范围无效')
    if scope=='project':return Path(settings()['path'])/category
    if batch=='legacy':
        from tools.task_actions import legacy_entries
        entries=legacy_entries(category)
        target=lib.ROOT/'output'/category
        if scope in {'group','image'} and not any(r['group_index']==request.get('group') for r in entries.values()):raise ValueError('历史组不存在')
    else:
        _,data=lib.load_batch(category,batch);target=lib.output_dir(category,batch)
        if scope in {'group','image'}:
            rows=lib.selected(lib.batch_dir(category,batch),data,[request.get('group')])
            if scope=='image' and request.get('position') not in {u['delivery_position'] for u in rows[0]['units']}:raise ValueError('图片占位不存在')
    if scope in {'group','image'}:target=target/f'group_{request["group"]:04d}'
    return target


def open_folder(request):
    from tools.task_actions import confined
    target=confined(folder(request));target.mkdir(parents=True,exist_ok=True)
    return {'path':str(target.resolve())}


def package(request):
    from tools.task_actions import ensure_idle, legacy_entries, confined
    destination=request.get('destination')
    if not isinstance(destination,str) or not Path(destination).is_absolute() or not Path(destination).is_dir():raise ValueError('请选择有效的压缩包保存目录')
    category=lib.identifier(request['category']);lib.category_dir(category)
    batch=lib.identifier(request['batch']);groups=request.get('groups')
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock'):
        ensure_idle(category)
        files=[]
        if batch=='legacy':
            entries={r['group_index']:r for r in legacy_entries(category).values()}
            groups=sorted(entries) if groups is None else groups
            if not isinstance(groups,list) or not groups or any(type(g)!=int or g not in entries for g in groups) or len(set(groups))!=len(groups):raise ValueError('请选择有效且不重复的组')
            for group in groups:
                source=confined(lib.ROOT/'output'/category/f'group_{group:04d}')
                images=sorted(source.glob('[0-9][0-9]_*.png'))
                if len(images)!=entries[group]['expected_image_count']:raise ValueError(f'第 {group} 组图片未齐，不能打包')
                files.extend((confined(p),f'{category}/{batch}/group_{group:04d}/{p.name}') for p in images)
        else:
            path,data=lib.load_batch(category,batch)
            groups=[g for g in range(1,data['count']+1) if g not in data.get('deleted_groups',[])] if groups is None else groups
            for row in lib.selected(path,data,groups):
                images={}
                for unit in row['units']:
                    kind='triptych' if unit['kind']=='triptych_panel' else unit['kind']
                    p=confined(lib.delivery_path(category,batch,row['group'],unit['delivery_position'],kind))
                    if not p.is_file():raise ValueError(f'第 {row["group"]} 组图片未齐，不能打包')
                    images[p.name]=p
                files.extend((p,f'{category}/{batch}/group_{row["group"]:04d}/{p.name}') for p in images.values())
        if not files:raise ValueError('没有可打包的图片')
        from tools.dashboard_delivery import DEFAULT_MAX_ARCHIVE_BYTES
        chunks=[];chunk=[];size=65536
        for source,name in files:
            required=source.stat().st_size+1024
            if required+65536>=DEFAULT_MAX_ARCHIVE_BYTES:raise ValueError('单张图片超过压缩包大小上限')
            if chunk and size+required>=DEFAULT_MAX_ARCHIVE_BYTES:
                chunks.append(chunk);chunk=[];size=65536
            chunk.append((source,name));size+=required
        if chunk:chunks.append(chunk)
        prefix=f'{category}_{batch}_{len(groups)}组_{secrets.token_hex(5)}'
        archives=[];temps=[]
        try:
            for index,chunk in enumerate(chunks,1):
                suffix=f'_part{index:03d}' if len(chunks)>1 else ''
                archive=Path(destination)/f'{prefix}{suffix}.zip'
                temp=archive.with_suffix('.zip.partial');temps.append(temp)
                with zipfile.ZipFile(temp,'x',compression=zipfile.ZIP_STORED) as z:
                    for source,name in chunk:z.write(source,name)
                with zipfile.ZipFile(temp) as z:
                    if z.testzip() or len(z.infolist())!=len(chunk):raise ValueError('压缩包校验失败')
                if temp.stat().st_size>=DEFAULT_MAX_ARCHIVE_BYTES:raise ValueError('压缩包超过大小上限')
                # Windows rename is atomic and refuses an existing destination.
                if os.name=='nt':os.rename(temp,archive)
                else:os.link(temp,archive)
                archives.append(archive)
            result={'path':str(archives[0]),'paths':[str(p) for p in archives],'groups':sorted(groups),'images':len(files),
                    'bytes':sum(p.stat().st_size for p in archives),'review_unchanged':True}
            lib.write(lib.ROOT/'.runtime/asset_exports'/f'{secrets.token_hex(12)}.json',{**result,'category':category,'batch':batch,'created_at':lib.now()})
            return result
        except Exception:
            for archive in archives:archive.unlink(missing_ok=True)
            raise
        finally:
            for temp in temps:
                if temp.exists():temp.unlink()
