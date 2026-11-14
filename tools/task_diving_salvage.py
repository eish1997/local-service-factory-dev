"""Diving task types and adapters; no network or production authorization."""
import copy
import random


def task_types(config):
    result=[{'id':b,'name':config['branches'][b]['name'],'selection':{'branch':b}}
            for b in ('objects','live_rescue','deceased_recovery')]
    result += [{'id':'underwater_work:'+j['id'],'name':j['name'],
                'selection':{'branch':'underwater_work','operation':j['id']}}
               for j in config['underwater_jobs']]
    jobs={j['id']:j for j in config['pipe_jobs']}
    result += [{'id':'pipeline:'+cat+':'+op,'name':v['name']+' · '+jobs[op]['name'],
                'selection':{'branch':'pipeline','pipe_category':cat,'operation':op}}
               for cat,v in config['pipe_categories'].items() for op in v['jobs']]
    return result


def select(config, task_type):
    for item in task_types(config):
        if item['id']==task_type:return copy.deepcopy(item)
    raise ValueError('请选择有效的潜水打捞任务类型')


def rows(seed,phone,config):
    from tools.diving_salvage import assemble
    from tools.diving_salvage_branches import resolve_pipe_sources
    from tools import runtime_paths
    frozen=copy.deepcopy(config)
    if 'resolved_pipe_sources' not in frozen:
        frozen=resolve_pipe_sources(frozen,lambda p:runtime_paths.read_json(runtime_paths.CODE_ROOT/p))
    task_type=frozen.get('task_type','objects')
    if task_type=='random':
        selection=random.Random(seed).choice(task_types(frozen))
    else:
        selection=select(frozen,task_type)
    group=assemble(frozen,seed,**selection['selection'])
    result=[]
    branch=selection['selection']['branch']
    stages=frozen['stages'] if branch=='objects' else frozen['branch_stages'][branch]
    names={s['id']:s['name'] for s in [*stages,frozen['land_survey_stage'],frozen['entry_stage']]}
    for shot in group['shots']:
        prompt=shot['prompt']
        if shot['type']=='storefront':
            prompt=prompt.replace('不生成任何文字。','').replace('禁止广告电话、','禁止未确认的广告电话、')
            prompt+='\n门头主招牌内写“潜水打捞”，同一招牌面板内写联系电话：'+phone+'；不得把号码放在墙、柱、门下横幅或车辆上。其他文字与中央电话由本地后处理添加。'
        result.append({'role':shot['kind'],'prompt':prompt,
            'service_role':None if shot['kind']=='cover' else names[shot['stages'][-1]],
            'final_size':shot['final_size'],'structure_version':config['image_group_structure']['structure_version'],
            'salvage_context':{'task_type':selection['id'],'anchor':group['anchor'],
                'anchor_sha256':group['anchor_sha256'],'shot':shot,'selection':selection['selection']}})
    return result
