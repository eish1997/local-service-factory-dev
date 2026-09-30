"""Prepare an isolated NSIS resource tree only after explicit build authorization."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tokenize
import zipfile
from tools import rule_updates, runtime_paths

ROOT=runtime_paths.CODE_ROOT

def source_text(file):
    # Legacy source contains old example/contact literals. Do not ship customer numbers.
    tokens=[]
    for token in tokenize.generate_tokens(io.StringIO(file.read_text(encoding='utf-8-sig')).readline):
        if token.type in {tokenize.STRING,tokenize.COMMENT}:
            token=token._replace(string=rule_updates.PHONE.sub('00000000000',token.string))
        tokens.append(token)
    return tokenize.untokenize(tokens)

def stage_engine(target):
    target=Path(target)
    if target.exists():raise ValueError('暂存目录已存在；请使用新的构建目录')
    target.mkdir(parents=True)
    for file in [*ROOT.glob('*.py'),*(ROOT/'tools').rglob('*.py')]:
        if '__pycache__' in file.parts:continue
        relative=file.relative_to(ROOT);out=target/relative;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(source_text(file),encoding='utf-8')
    for relative,data in rule_updates.export_documents().items():
        out=target/relative;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
    baseline=target/'distribution/baseline-rules.json';baseline.parent.mkdir(exist_ok=True)
    baseline.write_text(json.dumps({'version':'1','files':sorted(rule_updates.allowed_files())}),encoding='utf-8')
    for name in ('update-config.json','rules-fields.json'):
        out=target/'distribution'/name;out.parent.mkdir(exist_ok=True)
        value=json.loads((ROOT/'distribution'/name).read_text(encoding='utf-8'))
        if name=='update-config.json':value['maintainer_mode']=False
        out.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    cfg=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
    # Only application defaults, never private environment or historical records.
    (target/'config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    provider=target/'providers';provider.mkdir(exist_ok=True)
    registry=json.loads((ROOT/'providers/registry.json').read_text(encoding='utf-8-sig'))
    (provider/'registry.json').write_text(json.dumps(rule_updates.scrub(registry),ensure_ascii=False),encoding='utf-8')
    return target

def main():
    if sys.version_info < (3,11):
        raise ValueError('构建需要 Python 3.11 或更新版本，请使用 py -3.11 -m tools.stage_distribution')
    parser=argparse.ArgumentParser()
    parser.add_argument('--confirm-build',action='store_true');parser.add_argument('--python-zip',type=Path,required=True)
    parser.add_argument('--python-sha256',required=True);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    if not args.confirm_build:raise ValueError('仅在用户明确要求构建安装包后执行')
    if not re.fullmatch(r'[0-9a-f]{64}',args.python_sha256) or hashlib.sha256(args.python_zip.read_bytes()).hexdigest()!=args.python_sha256:raise ValueError('Python 嵌入包摘要不匹配')
    dest=args.destination.resolve()
    stage_engine(dest/'engine');runtime=dest/'python';runtime.mkdir()
    with zipfile.ZipFile(args.python_zip) as z:
        if sum(i.file_size for i in z.infolist())>150*1024*1024:raise ValueError('Python 嵌入包异常')
        for info in z.infolist():
            relative=Path(info.filename)
            if relative.is_absolute() or '..' in relative.parts or '\\' in info.filename:raise ValueError('Python 压缩包路径无效')
        z.extractall(runtime)
    if not (runtime/'python311.dll').exists():raise ValueError('需要官方 Windows x64 Python 3.11 嵌入包')
    (runtime/'python311._pth').write_text('python311.zip\n.\nLib/site-packages\n../engine\nimport site\n',encoding='utf-8')
    # The lock enumerates every target-runtime dependency. Do not evaluate
    # dependency markers against the maintainer's (possibly 3.10) interpreter.
    subprocess.run([sys.executable,'-m','pip','install','--no-deps','--only-binary=:all:','--platform','win_amd64','--python-version','3.11',
                    '--target',str(runtime/'Lib/site-packages'),'--require-hashes','-r',str(ROOT/'distribution/requirements-runtime.lock')],check=True)
    # Offline smoke check uses the embedded interpreter, never the system Python.
    check_home=dest/'smoke-workspace';check_home.mkdir();(check_home/'output').mkdir()
    result=subprocess.run([str(runtime/'python.exe'),'-X','utf8',str(dest/'engine/factory.py'),'tasks','projects'],input='{}',text=True,encoding='utf-8',capture_output=True,
                          env={**os.environ,'FACTORY_DATA_HOME':str(check_home),'PATH':str(runtime),'PYTHONIOENCODING':'utf-8'},cwd=check_home)
    if result.returncode or len(json.loads(result.stdout)['data'])!=8:raise ValueError('独立运行环境检查失败')
    print(json.dumps({'engine':str(dest/'engine'),'python':str(runtime),'verified':True}))

if __name__=='__main__':main()
