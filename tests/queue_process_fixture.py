"""Private subprocess harness: real shared Worker, deterministic local payloads only."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from tools import task_library as lib, task_worker as worker


def main():
    home, category, batch, task, mode = sys.argv[1:]
    lib.ROOT = Path(home)
    spec = lib.read(lib.ROOT / 'process-specs.json')[task]
    lib.business_config = lambda c: lib.read(lib.ROOT / 'fixture-catalog.json')[c]
    lib.api_config = lambda: spec['config']
    lib.readiness = lambda *args: ([], [1])
    lib.launch = lambda *args: os.getpid()
    target = {'category': category, 'batch': batch, 'task': task}
    taskfile = lib.batch_dir(category, batch) / 'tasks' / task / 'task.json'
    journal = lib.ROOT / 'process-journal.jsonl'
    check = lib.ROOT / ('checkpoint-' + task)

    def record(kind, **values):
        with lib.lock(journal.with_suffix('.lock'), wait_seconds=10):
            with journal.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'kind': kind, 'task': task, 'pid': os.getpid(),
                                         'at': time.monotonic_ns(), **values}) + '\n')

    def hold():
        check.write_text(mode, encoding='utf-8')
        while True:
            time.sleep(.1)

    encoded = io.BytesIO()
    Image.new('RGB', (1024, 1536), spec['color']).save(encoded, format='PNG')
    payload = encoded.getvalue()

    calls=[]
    def generate(client, config, prompt):
        if config != spec['config']:
            raise AssertionError('crossed frozen API configuration')
        digest = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        if digest not in spec['prompts']:
            raise AssertionError('crossed frozen prompt')
        record('post', prompt=digest, model=config['model'])
        calls.append(prompt)
        if mode=='crash_child_returned' and len(calls)<=2:raise TimeoutError('timed out')
        if mode == 'crash_unknown':
            hold()
        if mode == 'resume':
            raise AssertionError('recovery must not POST again')
        time.sleep(.2)
        record('return', prompt=digest)
        return payload

    if mode in ('crash_returned','crash_child_returned'):
        from tools import task_auto_recovery as recovery
        original = recovery.save_returned

        def save_returned(state, unit, number, data):
            original(state, unit, number, data)
            record('spooled', unit=unit['id'])
            hold()

        recovery.save_returned = save_returned

    if mode == 'crash_budget_reserved':
        from tools import task_budget as budget
        original_reserve=budget.reserve
        def reserve(state,unit,number,attempt):
            result=original_reserve(state,unit,number,attempt)
            record('budget_reserved',unit=unit)
            hold()
            return result
        budget.reserve=reserve

    if mode == 'resume':
        def no_api_setup():
            raise AssertionError('local recovery must not require API setup')
        lib.api_config = no_api_setup
        lib.readiness = lambda *args: (_ for _ in ()).throw(AssertionError('local recovery must not require keys'))
        from tools import task_auto_recovery as recovery
        original_finish=recovery.finish
        def finish(*args,**kwargs):
            try:return original_finish(*args,**kwargs)
            except Exception:
                import traceback
                lib.write(lib.ROOT/('process-recovery-error-'+task+'.json'),{'traceback':traceback.format_exc()[-3000:]})
                raise
        recovery.finish=finish
        try:
            lib.resume(target)
        except ValueError:
            lib.write(lib.ROOT / ('process-result-' + task + '.json'),
                      {'resume_blocked': True, 'state': lib.read(taskfile)['status']})
            return
    else:
        (lib.ROOT / ('ready-' + task)).write_text(str(os.getpid()), encoding='utf-8')
        deadline = time.monotonic() + 25
        while not (lib.ROOT / 'process-go').exists():
            if time.monotonic() > deadline:
                raise RuntimeError('fixture launch barrier timed out')
            time.sleep(.05)

    code = worker.run(category, batch, task, generate=generate, clients=[(1, object())])
    lib.write(lib.ROOT / ('process-result-' + task + '.json'),
              {'code': code, 'state': lib.read(taskfile)['status'], 'pid': os.getpid()})
    raise SystemExit(code)


if __name__ == '__main__':
    main()
