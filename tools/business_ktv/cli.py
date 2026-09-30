"""Thin business category CLI; all scheduling uses the shared iteration engine."""
import argparse
import json
from pathlib import Path
from tools.iteration_engine import IterationEngine
from tools import business_ktv

ROOT = Path(__file__).resolve().parents[2]


def add_arguments(parser):
    parser.add_argument('action', choices=('generate', 'optimize', 'continue', 'best', 'status', 'stop', 'overlay'))
    parser.add_argument('--job-id', help='本地叠字的已完成任务编号；省略则读取最新API任务')
    parser.add_argument('--count', type=int)
    parser.add_argument('--rounds', type=int)
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--continuous', action='store_true')
    parser.add_argument('--max-images', type=int)
    parser.add_argument('--seed', type=int, default=19)
    parser.add_argument('--backend', choices=('mock', 'api'), default='mock')
    parser.add_argument('--key-slots', help='正式样片使用的既有Key槽位，逗号分隔')
    parser.add_argument('--vision-session', help='当前Codex实际看图审核会话标识')
    parser.set_defaults(handler=command)


def command(args):
    try:
        if args.action == 'overlay':
            from tools.business_ktv.overlay import render_job
            result = render_job(ROOT, getattr(args, 'job_id', None))
            print(f"本地叠字完成：{len(result['images'])}张；0次API；状态={result['status']}；目录={result['directory']}")
            return 0
        if getattr(args, 'job_id', None):
            raise ValueError('--job-id仅用于本地overlay，不改变生产任务')
        config = json.loads((ROOT/'configs/business_ktv/scene_library.json').read_text(encoding='utf-8'))
        config['backend'] = args.backend
        base = ROOT/'database/business_ktv'/args.backend
        if getattr(args,'action','generate') in ('status','best','stop'):
            if args.action == 'stop':
                base.mkdir(parents=True,exist_ok=True)
                (base/'STOP').write_text('stop',encoding='utf-8')
                print('已请求安全停止。')
                return 0
            pointer = base/'checkpoint.json'
            if not pointer.exists():
                print('尚无任务。')
                return 0
            state = json.loads(Path(json.loads(pointer.read_text(encoding='utf-8'))['path']).read_text(encoding='utf-8'))
            if args.action == 'best':
                print('Winner目录：', ROOT/'output/business_ktv'/args.backend/'best')
            else:
                show(state)
            return 0
        generator = auditor = None
        if args.backend == 'api':
            from tools.business_ktv.api_adapter import ApiGenerator
            from tools.business_ktv.auditor import CodexVisionAuditor
            if not getattr(args,'vision_session',None):
                raise ValueError('真实视觉模型尚未启用：需要当前Codex看图审核会话；不得降级为mock')
            import factory
            slots = [int(v) for v in (getattr(args,'key_slots',None) or '').split(',') if v]
            config['vision_session'] = args.vision_session
            generator = ApiGenerator(factory._category_effective_config(), slots)
            auditor = CodexVisionAuditor(args.vision_session)
        engine = IterationEngine(ROOT, config, business_ktv, generator, auditor)
        if args.batch_size <= 0 or (args.rounds is not None and args.rounds <= 0):
            raise ValueError('每轮张数、轮数必须大于0')
        if args.action == 'continue':
            engine.resume()
            (engine.base/'STOP').unlink(missing_ok=True)
        else:
            if args.action == 'generate':
                if args.count is None or args.rounds is not None or args.continuous:
                    raise ValueError('generate必须指定--count，不能同时指定轮数或continuous')
                count = args.count
            elif args.continuous:
                if args.rounds is not None or args.count is not None:
                    raise ValueError('continuous不能同时指定rounds/count')
                count = args.max_images if args.max_images is not None else config['safety']['continuous_max_images']
                count = min(count, config['safety']['continuous_max_rounds']*args.batch_size)
            else:
                if args.count is not None or args.max_images is not None:
                    raise ValueError('optimize请使用--rounds及--batch-size')
                count = (args.rounds if args.rounds is not None else 10)*args.batch_size
            (engine.base/'STOP').unlink(missing_ok=True)
            engine.create(count, args.batch_size, args.seed, args.continuous)
        state = engine.run()
        show(state)
        if args.backend == 'api' and state['status'] == 'completed' and (ROOT/'configs/business_ktv/local_overlay.json').is_file():
            from tools.business_ktv.overlay import render_job
            result = render_job(ROOT, state['job_id'])
            print(f"已本地添加电话和底部服务词，待实际看图核对：{result['directory']}")
        return 0 if state['status'] in ('completed', 'stopped', 'awaiting_vision') else 2
    except (ValueError, RuntimeError, OSError) as error:
        print('任务未启动或已安全停止：', error)
        return 2


def show(state):
    label = 'MOCK模拟' if state['backend']=='mock' else 'API真实样片'
    print(f"[{label}] 状态={state['status']}；生成={state['generated_images']}/{state['planned_images']}；"
          f"请求={state['request_count']}/{state['max_requests']}；通过={state['success_count']}；"
          f"淘汰/失败={state['failure_count']}；策略版本={state['strategy_version']}")


def main():
    parser = argparse.ArgumentParser(description='现有批量生图项目 business_ktv 类目（第一阶段仅mock）')
    add_arguments(parser)
    raise SystemExit(command(parser.parse_args()))
