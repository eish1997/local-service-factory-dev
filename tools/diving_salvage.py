"""Offline diving-salvage content drafts. No provider or production imports."""
import argparse
import copy
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def load_config():
    from tools.runtime_paths import read_json
    config=read_json(ROOT/'configs/categories/diving_salvage.json')
    from tools.diving_salvage_branches import resolve_pipe_sources
    return resolve_pipe_sources(config, lambda path: read_json(ROOT/path))

def plan_check(config, plan):
    expected=[[s['id']] for s in config['stages']]
    if len(expected) not in [5,6] or plan!=expected:
        raise ValueError('潜水打捞详情必须按本任务类型的完整阶段逐张生成，禁止增减或重复')


def freeze(config, seed, object_id=None, site_id=None):
    rng=random.Random(seed)
    objects=[o for o in config['objects'] if object_id is None or o['id']==object_id]
    if not objects: raise ValueError('未知目标')
    obj=copy.deepcopy(rng.choice(objects));obj['color']=rng.choice(obj.pop('colors'));obj['count']=1
    sites=[s for s in config['sites'] if s['id'] in config['entry_sites'] and obj['size'] in s['sizes'] and (site_id is None or s['id']==site_id)]
    if not sites: raise ValueError('对象体量与场地不兼容')
    return {'seed':seed,'object':obj,'site':copy.deepcopy(rng.choice(sites)),
            'team':copy.deepcopy(rng.choice(config['teams'])), 'lighting':rng.choice(config['lighting']),
            'water':rng.choice(config['water']),'bottom':rng.choice(config['bottom']),
            'recovery':config['recovery'][obj['size']]}

def assemble_objects(config, seed, plan, cover_type=None, object_id=None, site_id=None, storefront_name=False):
    plan=[[s['id']] for s in config['stages']] if plan is None else plan
    plan_check(config,plan)
    from tools.diving_salvage_visual import freeze_visual, finalize
    anchor=freeze_visual(config,freeze(config,seed,object_id,site_id))
    rng=random.Random(seed+991)
    covers=[c for c in config['covers'] if c['id']=='underwater_discovery' and (cover_type is None or c['id']==cover_type)]
    if not covers: raise ValueError('未知首图类型')
    cover=rng.choice(covers); stages={s['id']:s for s in config['stages']+config.get('cover_only_stages',[])}
    a=anchor;o=a['object'];t=a['team']
    anchor_text=(f"本组固定且仅一件目标：{o['color']}{o['name']}，材质{o['material']}，形状{o['shape']}，识别特征{o['feature']}。"
       f"固定地点：{a['site']['name']}，{a['site']['detail']}；固定光线：{a['lighting']}；固定水体：{a['water']}；水底：{a['bottom']}。"
       f"主潜水员：{t['diver']}；接应人员：{t['assistants']}；同套装备：{t['equipment']}。回收方式：{a['recovery']}。"
       '以上为同一案例锚点，未出现在当前画面的元素不强制画出；人员特征在被装备遮挡时不强行显示。')
    shots=[{'kind':'cover','type':cover['id'],'stages':cover['stages'],'action':cover['action']}]
    shots += [{'kind':'detail','type':'timeline','stages':p,'action':stages[p[-1]]['action']} for p in plan]
    for i,shot in enumerate(shots):
        seq=shot['stages']
        state=stages[seq[-1]]['state'] if seq else '门店画面独立，不呈现打捞对象或伪造客户案例；本组案例地点不作为门店背景'
        # Do not ask for object close-ups before discovery, or underwater views from shore.
        cameras=config['cameras'] if seq and seq[-1] in ['discover','recover','handover'] else config['cameras'][:3]
        camera=cameras[i%len(cameras)]
        if shot['type']=='result': camera='物品近景，关注湿润泥痕与固定识别特征'
        if shot['type']=='underwater_search': camera='水下人物中景，关注手电探照与搜寻动作'
        if shot['type']=='storefront': camera=['门店正面自然视角','门店侧面斜拍','装备入口自然近景'][seed%3]
        label=next((c['name'] for c in config['covers'] if c['id']==shot['type']), '详情：'+'→'.join(stages[s]['name'] for s in seq))
        boundary='合并阶段用单一连续作业瞬间表达，画面状态以本张最后阶段为准，禁止拼贴时间矛盾。' if len(seq)>1 else ''
        text_rule='默认不生成任何文字。'
        if shot['type']=='storefront' and storefront_name:
            text_rule='唯一允许的门头文字为“潜水打捞”，不出现任何联系方式或其他文字。'
        shot.update(position=i+1,state=state,camera=camera,anchor_sha256=digest(anchor))
        shot['prompt']='\n'.join([config['fixed_prompt'],anchor_text,label,shot['action'],state,boundary,camera,config['negative_prompt'],text_rule])
        shot['prompt_sha256']=digest(shot['prompt'])
    return finalize(config,{'seed':seed,'anchor':anchor,'anchor_sha256':digest(anchor),'selected_cover':cover['id'],'shot_plan':copy.deepcopy(plan),'shots':shots})

def assemble(config, seed, plan=None, cover_type=None, object_id=None, site_id=None, storefront_name=False, branch='objects', operation=None, pipe_category=None):
    if branch=='objects':
        if operation is not None or pipe_category is not None: raise ValueError('物品打捞不能混入其他分支作业')
        return assemble_objects(config,seed,plan,cover_type,object_id,site_id,storefront_name)
    if object_id is not None: raise ValueError('人员和施工分支不能使用物品对象池')
    from tools.diving_salvage_branches import assemble as assemble_branch
    return assemble_branch(config,seed,plan,branch,operation,pipe_category,cover_type,site_id,storefront_name)

def validate(config):
    assert config['image_group_structure']['confirmed'] is True
    assert [config['image_group_structure'][k] for k in ['cover_count','detail_count','total_images']]==[1,5,6]
    assert {c['id'] for c in config['covers']}=={'underwater_discovery','storefront'}
    assert not config['approval']['style'] and not config['approval']['production']
    ids=[s['id'] for s in config['stages']]
    plans=[[[s] for s in ids]]
    checked=0
    for obj in config['objects']:
        for cover in [c for c in config['covers'] if c['id']=='underwater_discovery']:
            for plan in plans:
                group=assemble(config,20261029,plan,cover['id'],obj['id'])
                assert group==assemble(config,20261029,plan,cover['id'],obj['id'])
                assert len({s['anchor_sha256'] for s in group['shots']})==1
                assert group['anchor']['object']['size'] in group['anchor']['site']['sizes']
                assert all(group['anchor']['object']['feature'] in s['prompt'] for s in group['shots'] if not s.get('equipment_only'))
                assert group['shots'][-1]['state']==config['stages'][-1]['state']
                if obj['size']=='small': assert '不出现吊车' in group['anchor']['recovery']
                for s in group['shots']:
                    if s['stages'] and s['stages'][-1] in ['confirm','prepare','search']:
                        assert '物品特写' not in s['camera']
                checked+=1
    rejected=0
    for bad in [None,[],[['search']],[[s] for s in reversed(ids)],[['unknown']]]:
        try: plan_check(config,bad)
        except ValueError: rejected+=1
        else: raise AssertionError('invalid plan accepted')
    for obj in ['boat','large_machine','car']:
        try: freeze(config,1,obj,'pool')
        except ValueError: rejected+=1
        else: raise AssertionError('heavy object in landscape pool')
    return {'ok':True,'api_called':False,'combinations_checked':checked,'invalid_inputs_rejected':rejected,'objects':len(config['objects']),'active_underwater_cover_types':1,'detail_plans_tested':[5],'formal_count':None,'style_approved':False}

def command(args):
    config=load_config()
    if args.salvage_action=='validate':
        from tools.diving_salvage_validation import validate_all
        result=validate_all(config)
    else:
        stages=config['stages'] if args.branch=='objects' else config['branch_stages'][args.branch]
        plan=json.loads(Path(args.shot_plan).read_text(encoding='utf-8-sig')) if args.shot_plan else None
        if not 1<=args.groups<=100: raise ValueError('草稿组数须为1至100')
        from tools.diving_salvage_variation import assemble_batch
        groups,batch_stats=assemble_batch(lambda seed: assemble(config,seed,plan,args.cover_type,object_id=args.object_id,site_id=args.site_id,storefront_name=args.storefront_name,branch=args.branch,operation=args.operation,pipe_category=args.pipe_category),args.seed,args.groups)
        result={'schema_version':1,'category':'diving_salvage','status':'content_draft_only','api_called':False,
                'production_authorized':False,'formal_count':None,'config_snapshot':config,'config_sha256':digest(config),'batch_variation':batch_stats,'group_image_counts':[len(g['shots']) for g in groups],'groups':groups}
        path=Path(args.output)
        # Never replace an existing draft or production artifact.
        with path.open('x',encoding='utf-8') as out: json.dump(result,out,ensure_ascii=False,indent=2)
        result={'ok':True,'api_called':False,'groups':len(groups),'draft_path':str(path.resolve()),'formal_count':None}
    print(json.dumps(result,ensure_ascii=False))
    return 0

def add_arguments(parser):
    subs=parser.add_subparsers(dest='salvage_action',required=True)
    subs.add_parser('validate').set_defaults(handler=command)
    build=subs.add_parser('assemble');build.set_defaults(handler=command)
    build.add_argument('--seed',type=int,required=True)
    build.add_argument('--groups',type=int,required=True)
    build.add_argument('--shot-plan',help='可省略：默认使用本分支固定五阶段；显式输入必须与五阶段一致')
    build.add_argument('--output',required=True)
    build.add_argument('--cover-type',choices=['storefront','underwater_discovery'])
    build.add_argument('--storefront-name',action='store_true')
    build.add_argument('--branch',choices=['objects','live_rescue','deceased_recovery','underwater_work','pipeline'],default='objects')
    build.add_argument('--operation')
    build.add_argument('--pipe-category',choices=['municipal','industrial','domestic'])
    build.add_argument('--object-id')
    build.add_argument('--site-id')
