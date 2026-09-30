"""Export a clean, portable development checkout; no uploads or private runtime data."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import rule_updates, stage_distribution

TEXT = {'.md', '.txt', '.yaml', '.yml', '.js', '.css', '.html', '.svg', '.cs', '.lock', '.toml'}
EXCLUDED = {'node_modules', 'dist', 'backups', 'releases', 'release', 'release-v2', '__pycache__', '.git'}
SECRET = re.compile(r'(?i)\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})')


def clean_text(text):
    text = SECRET.sub('[credential omitted]', text)
    text = rule_updates.PHONE.sub('{已确认电话}', text)
    text = text.replace(str(ROOT).replace('\\', '/'), '<project-root>').replace(str(ROOT), '<project-root>')
    text = text.replace('C:/Users/15128/.codex/skills/', '.agents/skills/')
    text = re.sub(r'(?i)[A-Z]:[\\/](?:[^\s`"<>\n\r]| [^\s`"<>\n\r])*', '<local-path>', text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    target = args.destination.resolve()
    if target.exists() or target == ROOT:
        raise ValueError('Choose a new checkout directory; never overwrite a working tree')
    stage_distribution.stage_engine(target)
    # Development is the maintainer route, unlike a shipped consumer engine.
    cfg = json.loads((target/'distribution/update-config.json').read_text(encoding='utf-8'))
    cfg['maintainer_mode'] = True
    (target/'distribution/update-config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

    def copy(file):
        rel = file.relative_to(ROOT)
        if any(part in EXCLUDED for part in rel.parts) or file.suffix in {'.log', '.exe', '.zip', '.jsonl', '.pyc'}:
            return
        out = target/rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if rel.as_posix() in {'dashboard/package-lock.json', 'distribution/requirements-runtime.lock', 'distribution/python-runtime.json'}:
            # Dependency integrity hashes may contain phone-like digit runs.
            # These public metadata files must remain byte-identical.
            out.write_bytes(file.read_bytes())
        elif file.suffix == '.py':
            # Tests have synthetic input variations; don't collapse their phone fixtures.
            text = file.read_text(encoding='utf-8-sig') if rel.parts[0] == 'tests' else stage_distribution.source_text(file)
            out.write_text(SECRET.sub('[credential omitted]', text), encoding='utf-8')
        elif file.suffix == '.json':
            value = json.loads(file.read_text(encoding='utf-8-sig'))
            out.write_text(json.dumps(rule_updates.scrub(value), ensure_ascii=False, indent=2), encoding='utf-8')
        elif file.suffix in TEXT or file.name in {'.gitignore', '.rgignore', '.env.example'}:
            out.write_text(clean_text(file.read_text(encoding='utf-8-sig')), encoding='utf-8')

    for name in ['AGENTS.md', 'agent.md', 'CLAUDE.md', 'HELP.md', 'TASK_WORKFLOW.md',
                 'PRODUCTION_AUTHORIZATION.md', 'MULTI_PROJECT_ARCHITECTURE.md', 'START_HERE.md',
                 'requirements.txt', '.rgignore', '.env.example', 'visual_style_profiles.py']:
        if (ROOT/name).is_file():
            copy(ROOT/name)
    for dirname in ['dashboard', 'tests', 'assets/branding', 'distribution', 'providers', 'development']:
        for directory, folders, filenames in os.walk(ROOT/dirname):
            folders[:] = [name for name in folders if name not in EXCLUDED
                          and not (dirname == 'dashboard' and name.startswith(('dist', 'release', 'backup')))]
            for name in filenames:
                copy(Path(directory)/name)
    # Additional data-only business libraries, never prompts/groups/references/history.
    for file in (ROOT/'configs').rglob('*.json'):
        copy(file)
    for project in rule_updates.PROJECTS:
        for file in (ROOT/'projects'/project).glob('*.md'):
            if 'quality' in file.name or 'style' in file.name:
                copy(file)
    for file in (ROOT/'.agents/skills').rglob('*'):
        if file.is_file():
            copy(file)
    for name in ['factory-release-installer', 'factory-release-rules']:
        skill = Path.home()/'.codex/skills'/name
        if not skill.is_dir():
            skill = ROOT/'.agents/skills'/name
        for file in skill.rglob('*'):
            if not file.is_file() or '__pycache__' in file.parts:
                continue
            out = target/'.agents/skills'/name/file.relative_to(skill)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(clean_text(file.read_text(encoding='utf-8-sig')), encoding='utf-8')
    memory = target/'agent_memory/current_state.md'
    memory.parent.mkdir(exist_ok=True)
    memory.write_text('''# 开发仓库当前入口

这是可迁移的开发源码与 Agent 指引，不含原电脑生产状态、客户资料或私钥。
先读 AGENTS.md、HELP.md、TASK_WORKFLOW.md、development/README.md。
项目 skills 位于 .agents/skills/，包括主工厂、安装包发布和规则发布三个独立技能。
本地规则/代码版本以配置为准，远端版本发布前核对；旧电脑运行记录不能作为新任务授权。
新任务要求本批次的明确组数与手机号，密钥仅在本机配置。
发布软件与规则分别使用对应 skill；开发源码 git push 不等于发布软件或规则。
私钥不在仓库，新电脑缺发布私钥时不得生成新密钥冒充旧签名。
''', encoding='utf-8')
    (target/'.gitignore').write_text('''# Private and generated local state
.env
.env.*
!.env.example
.runtime/
__pycache__/
*.py[cod]
.venv/
venv/
*.pem
*.key
*.pfx
*.p12
*.log
output/
outputs/
approved/
needs_fix/
rejected/
recovered_images/
reference_good/
reference_bad/
database/
reports/
prompts/
agent_memory/archive/
agent_memory/context.md
agent_memory/progress.md
agent_memory/bugs.md
projects/*/groups/
projects/*/prompts/
projects/*/references/
projects/*/variable_history/
dashboard/node_modules/
dashboard/dist/
dashboard/dist*/
dashboard/releases/
dashboard/backups/
dashboard/release*/
*.zip
*.exe
''', encoding='utf-8')
    (target/'README.md').write_text('''# 本地生活服务图片工厂｜开发源码

本仓库用于跨电脑开发；软件安装包、规则数据分别在各自分发仓库。
先读 [Agent入口](AGENTS.md)、[当前帮助](HELP.md)、[新电脑开发指南](development/README.md)。
三个项目skill位于 `.agents/skills/`，源码推送不自动触发生图或分发发布。
凭证、客户资料、生成图片、任务历史与发布私钥不进入此仓库。
''', encoding='utf-8')
    # Never export current customer phones/keys/history; final credential scan is fail-closed.
    files = [p for p in target.rglob('*') if p.is_file()]
    for file in files:
        if SECRET.search(file.read_text(encoding='utf-8')):
            raise ValueError('Credential-like text in export: '+str(file.relative_to(target)))
    print(json.dumps({'directory': str(target), 'files': len(files), 'private_state_excluded': True}))


if __name__ == '__main__':
    main()
