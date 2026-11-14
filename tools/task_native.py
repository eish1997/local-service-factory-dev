"""Explicit native-tool workflow. Never invokes a generator or imports API clients."""
import secrets
import contextlib
import hashlib
import os
import re
import sys
from pathlib import Path
from tools import task_library as lib, runtime_paths


OPERATIONS = {'native-plan', 'native-instance', 'native-discover', 'native-authorize', 'native-claim',
              'native-reserve', 'native-outcome', 'native-status', 'native-cancel',
              'native-register', 'native-ingest', 'native-materialize', 'native-recover'}


def instance():
    """Read-only identity: moving a data root requires an explicit new binding."""
    from tools.task_assets import settings
    root = str(lib.ROOT.resolve())
    config = runtime_paths.config()
    install = os.environ.get('FACTORY_INSTALL_HOME')
    if not install and runtime_paths.CODE_ROOT.name == 'engine' and runtime_paths.CODE_ROOT.parent.name == 'resources':
        inferred = runtime_paths.CODE_ROOT.parent.parent
        if Path(sys.executable).resolve().parent == (inferred/'resources/python').resolve():
            install = str(inferred)
    installed = bool(install and (Path(install)/'resources/engine').resolve() == runtime_paths.CODE_ROOT.resolve())
    if installed and not os.environ.get('FACTORY_DATA_HOME'):
        raise ValueError('安装版入口必须显式绑定已核对的 FACTORY_DATA_HOME，不能把引擎目录当资料目录')
    return {'instance_id': lib.digest({'data_root': os.path.normcase(root)}), 'data_root': root,
            'engine_root': str(runtime_paths.CODE_ROOT.resolve()),
            'asset_root': settings()['path'], 'app_version': config.get('app_version'),
            'execution_kind': 'installed' if installed else 'development',
            'native_protocol': 1,
            'installing': (lib.ROOT/'.runtime/updates/installing.json').exists()}


def discover(request):
    """Bounded read-only inspection; never launches an installer or chooses a data root."""
    roots = request.get('install_roots', [])
    if not isinstance(roots, list) or len(roots) > 10 or any(not isinstance(p, str) or not Path(p).is_absolute() for p in roots):
        raise ValueError('安装根须为最多 10 个明确绝对路径')
    candidates = {str(Path(p).resolve()): 'explicit' for p in roots}
    if os.name == 'nt':
        import winreg
        key_path = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
        for hive, label in ((winreg.HKEY_LOCAL_MACHINE, 'machine'), (winreg.HKEY_CURRENT_USER, 'user')):
            try:
                with winreg.OpenKey(hive, key_path) as parent:
                    for index in range(winreg.QueryInfoKey(parent)[0]):
                        try:
                            with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as item:
                                name = winreg.QueryValueEx(item, 'DisplayName')[0]
                                if not any(word in str(name).lower() for word in ('道路救援图片看板', 'localservicefactory', 'road-rescue-dashboard')):continue
                                uninstall = winreg.QueryValueEx(item, 'UninstallString')[0]
                                match = re.match(r'^"?(.+?\.exe)(?:"|\s|$)', str(uninstall), re.I)
                                if match:candidates[str(Path(match[1]).resolve().parent)] = label
                        except OSError:continue
            except OSError:pass
    data_roots = request.get('data_roots', [])
    if not isinstance(data_roots, list) or len(data_roots) > 10 or any(not isinstance(p, str) or not Path(p).is_absolute() for p in data_roots):
        raise ValueError('资料根须为最多 10 个明确绝对路径')
    if os.environ.get('APPDATA'):
        data_roots = [*data_roots, str(Path(os.environ['APPDATA'])/'road-rescue-dashboard/workspace')]
    descriptors = []
    for root in dict.fromkeys(data_roots):
        file = Path(root)/'.runtime/native-instance.json'
        if not file.is_file() or file.stat().st_size > 65536:continue
        try:
            value = lib.read(file)
            if Path(value['data_root']).resolve() == Path(root).resolve():descriptors.append(value)
        except (OSError, ValueError, TypeError, KeyError):continue
    result = []
    for root, source in candidates.items():
        engine = Path(root)/'resources/engine'
        file = engine/'distribution/update-config.json'
        if not file.is_file():continue
        config = lib.read(file)
        result.append({'install_root': root, 'discovered_by': source,
                       'engine_root': str(engine), 'app_version': config.get('app_version'),
                       'python': str(Path(root)/'resources/python/python.exe'),
                       'python_exists': (Path(root)/'resources/python/python.exe').is_file(),
                       'native_interface_present': (engine/'tools/task_native.py').is_file(),
                       'data_instances': [d for d in descriptors if Path(d.get('engine_root', '')).resolve() == engine.resolve()],
                       'data_root': None, 'requires_instance_check': True})
    return {'installations': result, 'selected': None,
            'note': '安装路径不证明数据实例。多个候选必须询问；用所选安装的公共入口核对真实资料根，旧版不支持时停止，不替换为开发引擎。'}


def context(request):
    path, data = lib.load_batch(request['category'], request['batch'])
    if lib.generation_route(data) != 'codex_native':
        raise ValueError('现有 API 批次不能转换为 Codex 内置任务')
    identity = instance()
    if request.get('instance_id') != identity['instance_id']:
        raise ValueError('数据实例不匹配，请先核对 native-instance')
    if identity['installing']:
        raise ValueError('软件正在安装更新')
    return path, data, identity


def load_state(path):
    file = path/'native-execution.json'
    return lib.read(file) if lib.io_path(file).exists() else {
        'schema_version': 1, 'provider': 'codex_native', 'scopes': {}, 'units': {}, 'cancelled': False}


def plan(request):
    category, batch = request['category'], request['batch']
    path, data, identity = context(request)
    rows = lib.scoped_rows(path, data, request.get('groups'), request.get('unit_ids'))
    snapshot = lib.read(path/'snapshot.json')
    lib.validate_batch_phone(category, data, snapshot)
    units = [{**unit, 'group': row['group']} for row in rows for unit in row['units']]
    state = load_state(path)
    from tools.task_worker import raw_evidence_valid
    pending, ready, blocked, allowances = [], [], [], {}
    for unit in units:
        uid = unit['id']; record = state['units'].get(uid, {})
        status = record.get('status', 'pending')
        raw = lib.unit_raw(category, batch, unit['group'], unit)
        if status in {'raw_saved', 'rendering', 'completed'} and raw_evidence_valid(raw, unit):continue
        pending.append(uid)
        remaining = max(0, 2-len(record.get('attempts', [])))
        scope_id = record.get('scope')
        scope = state['scopes'].get(scope_id)
        cap = max(0, scope['binding']['max_tool_calls']-scope['calls_used']) if scope else remaining
        if state['cancelled'] or status not in {'pending', 'failed', 'claimed'} or not remaining or not cap:
            blocked.append({'unit': uid, 'reason': 'cancelled' if state['cancelled'] else
                            'raw_evidence_missing' if status in {'raw_saved', 'rendering', 'completed'} else
                            'exhausted' if not remaining or not cap else status})
            continue
        ready.append(uid)
        key = scope_id or 'unlicensed:'+uid
        allowances[key] = min(cap, allowances.get(key, 0)+remaining)
    result = {
        'instance_id': identity['instance_id'],
        'category': category, 'batch': batch, 'generation_route': 'codex_native',
        'snapshot_sha256': data['snapshot_sha256'], 'manifest_sha256': data['manifest_sha256'],
        'groups': [row['group'] for row in rows], 'units': units,
        'raw_count': len(units),
        'delivery_count': len({(u['group'], u['delivery_position']) for u in units}),
        'pending_units': pending,
        'ready_units': ready, 'blocked_units': blocked,
        'max_tool_calls': sum(allowances.values()),
        'api_called': False,
        'authorization': None, 'status': 'cancelled' if state['cancelled'] else 'awaiting_codex',
    }
    result['plan_sha256'] = lib.digest(result)
    return result


def authorize(request):
    path, data, _ = context(request)
    if request.get('authorization') != 'execute_native_selected_units':
        raise ValueError('缺少本次内置工具执行范围授权')
    planned = plan(request)
    state = load_state(path)
    if state['cancelled']:
        raise ValueError('内置任务已取消，不能重新授权')
    scope = lib.identifier(request['scope'])
    cap = request.get('max_tool_calls')
    if type(cap) is not int or not 0 <= cap <= 2*planned['raw_count']:
        raise ValueError('调用上限必须在本次剩余范围内')
    binding = {'instance_id': planned['instance_id'], 'category': data['category'], 'batch': data['id'],
               'generation_route': 'codex_native', 'snapshot_sha256': data['snapshot_sha256'],
               'manifest_sha256': data['manifest_sha256'], 'unit_ids': sorted(u['id'] for u in planned['units']),
               'max_tool_calls': cap}
    if scope in state['scopes']:
        if state['scopes'][scope]['binding'] != binding:
            raise ValueError('已有范围不能更改或重置调用上限')
        return state['scopes'][scope]
    if cap > planned['max_tool_calls']:
        raise ValueError('调用上限超过剩余额度')
    if request.get('plan_sha256') != planned['plan_sha256']:
        raise ValueError('内置计划已变化，请重新读取')
    # One unit belongs to one persistent scope, so new scope names cannot reset a lower cap.
    if any(set(s['binding']['unit_ids']) & set(binding['unit_ids']) for s in state['scopes'].values()):
        raise ValueError('单元已有执行范围，请恢复原范围，不创建新额度')
    state['scopes'][scope] = {'id': scope, 'binding': binding, 'calls_used': 0, 'created_at': lib.now()}
    for unit in planned['units']:
        state['units'][unit['id']] = {'scope': scope, 'group': unit['group'],
                                     'prompt_sha256': unit['prompt_sha256'], 'status': 'pending', 'attempts': []}
    lib.write(path/'native-execution.json', state)
    return state['scopes'][scope]


def bound_unit(request):
    path, data, identity = context(request)
    state = load_state(path)
    if state['cancelled']:
        raise ValueError('内置任务已取消')
    uid = lib.identifier(request['unit'])
    record = state['units'].get(uid)
    if not record or record['scope'] != request.get('scope'):
        raise ValueError('单元不在已授权范围')
    binding = state['scopes'][record['scope']]['binding']
    if any(binding.get(k) != v for k, v in {'instance_id': identity['instance_id'],
           'category': data['category'], 'batch': data['id'], 'generation_route': 'codex_native',
           'snapshot_sha256': data['snapshot_sha256'], 'manifest_sha256': data['manifest_sha256']}.items()):
        raise ValueError('内置执行绑定已改变')
    rows = lib.scoped_rows(path, data, [record['group']], [uid])
    unit = rows[0]['units'][0]
    if unit['prompt_sha256'] != record['prompt_sha256']:
        raise ValueError('提示词指纹不一致')
    return path, data, state, record, unit


def claim(request):
    path, _, state, record, unit = bound_unit(request)
    scope = state['scopes'][record['scope']]
    if record['status'] not in {'pending', 'failed'}:
        raise ValueError('单元已领取或结果待核对；不能重新生成')
    if len(record['attempts']) >= 2 or scope['calls_used'] >= scope['binding']['max_tool_calls']:
        raise ValueError('内置调用额度已耗尽，缺失项仍未完成')
    record.update(status='claimed', claim=secrets.token_hex(24))
    lib.write(path/'native-execution.json', state)
    return {'unit': unit, 'claim': record['claim'], 'status': record['status']}


def require_claim(request, record):
    if not request.get('claim') or request['claim'] != record.get('claim'):
        raise ValueError('领取标识不匹配或已失效')


def reserve(request):
    path, _, state, record, _ = bound_unit(request)
    require_claim(request, record)
    if record['status'] in {'awaiting_result', 'uncertain'}:
        return {'attempt': record['attempts'][-1], 'new_reservation': False}
    if record['status'] != 'claimed':
        raise ValueError('仅已领取单元可预留调用')
    scope = state['scopes'][record['scope']]
    if len(record['attempts']) >= 2 or scope['calls_used'] >= scope['binding']['max_tool_calls']:
        raise ValueError('内置调用额度已耗尽')
    attempt = {'id': secrets.token_hex(16), 'reserved_at': lib.now(), 'status': 'unknown'}
    record['attempts'].append(attempt)
    record['status'] = 'awaiting_result'
    scope['calls_used'] += 1
    lib.write(path/'native-execution.json', state)
    return {'attempt': attempt, 'new_reservation': True}


def outcome(request):
    path, _, state, record, _ = bound_unit(request)
    require_claim(request, record)
    if record['status'] not in {'awaiting_result', 'uncertain'}:
        raise ValueError('单元不处于待核对调用状态')
    if record.get('result'):
        raise ValueError('已有返回文件，必须先恢复回填，不能改为失败重生')
    value = request.get('outcome')
    if value not in {'uncertain', 'confirmed_failure'}:
        raise ValueError('只能登记未知结果或已确认无返回图片的失败')
    if not isinstance(request.get('evidence'), str) or not request['evidence'].strip():
        raise ValueError('必须登记结果核对依据，不保存凭据')
    record['attempts'][-1].update(status=value, evidence=request['evidence'][:2000])
    record['status'] = 'failed' if value == 'confirmed_failure' else 'uncertain'
    lib.write(path/'native-execution.json', state)
    return record


def source_bytes(file, expected_hash):
    file = lib.io_path(file)
    if not file.is_file() or not 0 < file.stat().st_size <= 64*1024*1024:
        raise ValueError('返回图片不存在或超过 64MB')
    with file.open('rb') as stream:payload = stream.read(64*1024*1024+1)
    if len(payload) > 64*1024*1024:raise ValueError('返回图片超过 64MB')
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        raise ValueError('返回图片摘要不一致')
    from PIL import Image
    import io
    with Image.open(io.BytesIO(payload)) as image:
        w, h = image.size
        if not 0 < w <= 16384 or not 0 < h <= 16384 or w*h > 40000000:
            raise ValueError('返回图片尺寸超出安全上限')
        image.load()
    return payload


def receipt_valid(receipt, unit):
    binding = receipt.get('native_binding', {})
    path, data = lib.load_batch(binding['category'], binding['batch'])
    if lib.generation_route(data) != 'codex_native':return False
    if binding.get('instance_id') != instance()['instance_id']:return False
    if binding.get('snapshot_sha256') != data['snapshot_sha256']:return False
    if binding.get('unit') != unit['id'] or binding.get('prompt_sha256') != unit['prompt_sha256']:return False
    record = load_state(path)['units'].get(unit['id'], {})
    return record.get('result') == binding and record.get('claim') == binding.get('claim')


def register(request):
    path, data, state, record, unit = bound_unit(request)
    require_claim(request, record)
    source = request.get('source_kind')
    if source not in {'tool_return', 'manual_saved', 'synthetic_test'}:
        raise ValueError('必须明确工具返回、手动保存或合成测试来源')
    if not isinstance(request.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', request['sha256']):
        raise ValueError('必须提供返回文件的 SHA256 摘要')
    tool_id = request.get('tool_result_id')
    if tool_id is not None and (not isinstance(tool_id, str) or not 0 < len(tool_id) <= 500):
        raise ValueError('工具结果 ID 必须为实际返回的短字符串，缺失时省略')
    file = Path(request['file'])
    if not file.is_absolute():
        raise ValueError('必须提供明确的绝对文件路径，不猜测缓存')
    result = {'file': str(file.resolve()), 'sha256': request['sha256'], 'source_kind': source,
              'tool_result_id': request.get('tool_result_id'), 'synthetic': request.get('synthetic') is True, 'provider': 'codex_native',
              'instance_id': request['instance_id'], 'category': data['category'], 'batch': data['id'],
              'unit': unit['id'], 'group': record['group'], 'claim': record['claim'],
              'snapshot_sha256': data['snapshot_sha256'], 'prompt_sha256': unit['prompt_sha256']}
    if record.get('result'):
        if {**result, 'file': record['result']['file']} != record['result']:
            raise ValueError('已有返回结果绑定，不能覆盖不同文件或摘要')
        if result['file'] != record['result']['file'] and record['status'] not in {'raw_saved', 'rendering', 'completed'}:
            source_bytes(file, result['sha256'])
            record['recovery_file'] = str(file.resolve())
            lib.write(path/'native-execution.json', state)
        if request.get('handoff') == 'manual_saved':
            record['manual_recovery'] = {'kind': 'manual_saved', 'file': str(file.resolve())}
            lib.write(path/'native-execution.json', state)
        return record
    if record['status'] not in {'awaiting_result', 'uncertain'}:
        raise ValueError('没有待回填的已预留调用')
    record['result'] = result
    record['status'] = 'uncertain'  # Returned but not saved: blocked from all new calls.
    record['attempts'][-1]['status'] = 'returned'
    lib.write(path/'native-execution.json', state)
    # Keep the returned-source binding even when validation/download/save fails.
    source_bytes(file, result['sha256'])
    return record


def save_native_raw(path, payload, kind):
    """Preserve exact tool bytes and adapt only the shared renderer's working PNG."""
    import io
    from PIL import Image
    from tools import category_image_production as images
    from tools.category_4k_raw import publish_immutable_bytes
    with Image.open(io.BytesIO(payload)) as source:
        source.load();size=source.size;fmt=source.format;image=source.convert('RGB')
    if min(size)<512 or not 0.5<=size[0]/size[1]<=1:
        raise ValueError('内置返回图片须为至少512像素的竖图或方图；保留返回绑定待核对')
    original=images._archive_provider_payload(path.parent/'originals',path,payload,fmt,size)
    anchor=0.0 if kind=='cover' else 0.5
    working=images._fit_image(image,(1024,1536),anchor_y=anchor) if size!=(1024,1536) else image
    buffer=io.BytesIO();working.save(buffer,format='PNG',optimize=True)
    publish_immutable_bytes(path,buffer.getvalue())
    return {'source_returned_size':f'{size[0]}x{size[1]}','source_format':fmt,
            'source_sha256':hashlib.sha256(payload).hexdigest(),'provider_original':str(original),
            'archive_status':'preserved','normalized':size!=(1024,1536),
            'normalization_mode':'lanczos_cover_crop' if size!=(1024,1536) else 'none',
            'normalization_anchor_y':anchor,'normalized_to':'1024x1536',
            'saved_raw_sha256':hashlib.sha256(buffer.getvalue()).hexdigest()}


def ingest(request):
    path, data, state, record, unit = bound_unit(request)
    require_claim(request, record)
    result = record.get('result')
    if not result:
        raise ValueError('必须先登记明确返回文件')
    from tools.task_worker import raw_evidence_valid
    from tools.raw_library import register as register_library
    from tools.category_4k_raw import publish_immutable_bytes
    raw = lib.unit_raw(data['category'], data['id'], record['group'], unit)
    from tools.postprocess_view import confined
    confined(raw, data['category'])
    stage = raw.parent/'.native-stage'/unit['id']/record['claim']
    prepared = stage/'prepared.json'
    if lib.io_path(prepared).exists():
        receipt = lib.read(prepared)
        if receipt.get('native_binding') != result:
            raise ValueError('原图暂存绑定不一致')
    else:
        payload = source_bytes(record.get('recovery_file') or result['file'], result['sha256'])
        lib.io_path(stage).mkdir(parents=True, exist_ok=True)
        source = save_native_raw(stage/'raw.png', payload, unit['kind'])
        receipt = {'schema_version': 1, 'provider': 'codex_native', 'native_binding': result,
                   'prompt_sha256': unit['prompt_sha256'],
                   'raw_sha256': hashlib.sha256(lib.io_path(stage/'raw.png').read_bytes()).hexdigest(),
                   'source': source, 'mock': result['source_kind'] == 'synthetic_test' or result.get('synthetic') is True,
                   'handoff': record.get('manual_recovery'),
                   'review': 'unreviewed'}
        lib.write(prepared, receipt)
    payload = lib.io_path(stage/'raw.png').read_bytes()
    if hashlib.sha256(payload).hexdigest() != receipt['raw_sha256']:
        raise ValueError('暂存原图摘要不一致')
    # An immutable publish and retained prepared receipt recover a crash between file and metadata.
    publish_immutable_bytes(raw, payload)
    proof = raw.with_suffix('.receipt.json')
    if lib.io_path(proof).exists() and lib.read(proof) != receipt:
        raise ValueError('已有原图收据不同，禁止覆盖')
    lib.write(proof, receipt)
    if not raw_evidence_valid(raw, unit):
        raise ValueError('保存的原图证据校验失败')
    asset = register_library(data['category'], data['id'], record['group'], unit)
    record.update(asset=asset['id'], raw_sha256=receipt['raw_sha256'])
    if record['status'] != 'completed':record['status'] = 'raw_saved'
    lib.write(path/'native-execution.json', state)
    return record


def scoped_execution_rows(request, path, data, scope):
    allowed = set(scope['binding']['unit_ids'])
    explicit = request.get('unit_ids')
    if explicit is None and request.get('unit'):explicit = [request['unit']]
    ids = explicit if explicit is not None else sorted(allowed)
    if request.get('groups') is not None:
        groups = request['groups']
        lib.selected(path, data, groups)
        scope_groups = {int(uid[1:5]) for uid in allowed}
        if not set(groups) <= scope_groups:raise ValueError('所选组超出原授权范围')
        if explicit is not None and any(int(uid[1:5]) not in groups for uid in ids):
            raise ValueError('所选单元与组范围不一致')
        ids = [uid for uid in ids if int(uid[1:5]) in groups]
    rows = lib.scoped_rows(path, data, None, ids)
    if not set(ids) <= allowed:raise ValueError('所选单元超出原授权范围')
    if not rows:raise ValueError('没有选中原授权范围内的单元')
    return rows


@contextlib.contextmanager
def write_guard():
    """Atomically admit a writer against installer admission; retain it outside admin lock.

    Process-owned leases outlive batch deletion/cancellation, but dead processes do
    not block an update. They never expire by time or refund a tool reservation.
    """
    with contextlib.ExitStack() as lifetime:
        with lib.lock(lib.ROOT/'.runtime/task-admin.lock', wait_seconds=10):
            if (lib.ROOT/'.runtime/updates/installing.json').exists():
                raise ValueError('软件正在安装更新')
            lifetime.enter_context(lib.lock(lib.ROOT/'.runtime/native-writes'/f'{secrets.token_hex(24)}.lock'))
        yield


def materialize(request):
    with write_guard():
        return _materialize(request)


def _materialize(request):
    path, data, _ = context(request)
    with lib.lock(path/'native-render.lock', wait_seconds=10):
        with lib.lock(lib.ROOT/'.runtime/task-admin.lock', wait_seconds=10):
            state = load_state(path)
            if state['cancelled']:raise ValueError('内置任务已取消')
            scope = state['scopes'].get(request.get('scope'))
            if not scope:raise ValueError('没有对应的内置执行范围')
            if any(scope['binding'].get(key) != value for key, value in {
                    'category': data['category'], 'batch': data['id'], 'generation_route': 'codex_native',
                    'instance_id': request['instance_id'], 'snapshot_sha256': data['snapshot_sha256'],
                    'manifest_sha256': data['manifest_sha256']}.items()):
                raise ValueError('内置排版的冻结绑定已改变')
            rows = scoped_execution_rows(request, path, data, scope)
            from tools.task_worker import delivery_valid, raw_evidence_valid
            def finished(row, unit):
                kind = 'triptych' if unit['kind'] == 'triptych_panel' else unit['kind']
                target = lib.delivery_path(data['category'], data['id'], row['group'], unit['delivery_position'], kind)
                raw = lib.unit_raw(data['category'], data['id'], row['group'], unit)
                return (state['units'][unit['id']]['status'] == 'completed' and
                        raw_evidence_valid(raw, unit) and delivery_valid(target, unit))
            # A completed, already packaged group must not be re-enqueued by a read/recovery.
            if all(finished(row, unit) for row in rows for unit in row['units']):
                return {'state': state, 'render_failures': []}
            for row in rows:
                for unit in row['units']:
                    record = state['units'][unit['id']]
                    if record['status'] == 'raw_saved':record['status'] = 'rendering'
            lib.write(path/'native-execution.json', state)
        # Reuse complete delivery positions (including all three frozen panels), never a partial triptych.
        groups = [row['group'] for row in rows]
        positions = {(r['group'], u['delivery_position']) for r in rows for u in r['units']}
        def complete_positions():
            return [{**r, 'units': [u for u in r['units'] if (r['group'], u['delivery_position']) in positions]}
                    for r in lib.selected(path, data, groups)]
        complete_rows = complete_positions()
        from tools.task_worker import materialize as render, delivery_valid, raw_evidence_valid
        snapshot = lib.read(path/'snapshot.json')
        version = snapshot.get('rules_version', 'workspace')
        if version != 'workspace':
            from tools.rule_updates import valid_version
            rule_root = lib.ROOT/'.runtime/rules'/valid_version(version)
            if not lib.io_path(rule_root/'manifest.json').is_file():
                raise ValueError('冻结规则缺失，不能改用其他版本排版')
            with runtime_paths.use_rules(rule_root):
                failures = render(data['category'], data['id'], data, complete_rows, snapshot)
        else:
            failures = render(data['category'], data['id'], data, complete_rows, snapshot)
        with lib.lock(lib.ROOT/'.runtime/task-admin.lock', wait_seconds=10):
            # Deletion may have happened during rendering. Never resurrect a missing batch/state.
            path, data, _ = context(request)
            complete_rows = complete_positions()
            state = load_state(path)
            if state['cancelled']:raise ValueError('内置任务已取消，保留先前原图与结果')
            if any(scope['binding'][key] != data[key] for key in ('snapshot_sha256', 'manifest_sha256')):
                raise ValueError('内置排版的冻结绑定已改变')
            from tools.dashboard_delivery import load_state as queue_state
            queue = queue_state(lib.ROOT/'.runtime/dashboard_delivery_state.json')
            pool = queue.get('projects', {}).get(data['category'], {}).get('pending_library_groups', {})
            for row in complete_rows:
                for unit in row['units']:
                    record = state['units'].get(unit['id'])
                    if not record:continue
                    if record['status'] not in {'raw_saved', 'rendering', 'completed'}:continue
                    kind = 'triptych' if unit['kind'] == 'triptych_panel' else unit['kind']
                    target = lib.delivery_path(data['category'], data['id'], row['group'], unit['delivery_position'], kind)
                    raw = lib.unit_raw(data['category'], data['id'], row['group'], unit)
                    queued = str(target.resolve()) in pool.get(f"{data['id']}:{row['group']}", {}).get('paths', [])
                    record['status'] = 'completed' if (raw_evidence_valid(raw, unit) and
                        delivery_valid(target, unit) and queued) else 'raw_saved'
            lib.write(path/'native-execution.json', state)
            return {'state': state, 'render_failures': failures}


def recover(request):
    with write_guard():
        return _recover(request)


def _recover(request):
    path, data, _ = context(request)
    state = load_state(path)
    scope = state['scopes'].get(request.get('scope'))
    if not scope:raise ValueError('没有对应的内置执行范围')
    rows = scoped_execution_rows(request, path, data, scope)
    for uid in [u['id'] for r in rows for u in r['units']]:
        record = state['units'][uid]
        if record.get('result') and record['status'] != 'cancelled':
            bound = {**request, 'unit': uid, 'claim': record['claim']}
            _, data, _, _, unit = bound_unit(bound)
            from tools.task_worker import raw_evidence_valid
            raw = lib.unit_raw(data['category'], data['id'], record['group'], unit)
            if record['status'] != 'completed' or not raw_evidence_valid(raw, unit):
                dispatch('native-ingest', bound)
    return materialize(request)


def dispatch(operation, request):
    if operation == 'native-discover':return discover(request)
    if operation == 'native-instance':
        return instance()
    if operation == 'native-plan':
        return plan(request)
    if operation == 'native-status':
        path, _, _ = context(request)
        return load_state(path)
    if operation == 'native-materialize':return materialize(request)
    if operation == 'native-recover':return recover(request)
    # Serializes claims/reservations with deletion and assembly, with no calls outside this process.
    with lib.lock(lib.ROOT/'.runtime/task-admin.lock', wait_seconds=10):
        if operation == 'native-cancel':
            path, _, _ = context(request)
            if request.get('authorization') != 'cancel_native_batch':
                raise ValueError('缺少取消本批内置任务的指令')
            state = load_state(path)
            state['cancelled'] = True
            for record in state['units'].values():
                if record['status'] != 'completed':record['status'] = 'cancelled'
            lib.write(path/'native-execution.json', state)
            return state
        return {'native-authorize': authorize, 'native-claim': claim,
                'native-reserve': reserve, 'native-outcome': outcome,
                'native-register': register, 'native-ingest': ingest}[operation](request)
