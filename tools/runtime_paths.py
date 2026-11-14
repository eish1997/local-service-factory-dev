"""Installed code, mutable user data and a process-pinned rules snapshot."""
import contextlib
import contextvars
import json
import os
from functools import lru_cache
from pathlib import Path

CODE_ROOT=Path(__file__).resolve().parent.parent
OVERRIDE=contextvars.ContextVar('rules_snapshot',default=None)

def data_root():
    return Path(os.environ.get('FACTORY_DATA_HOME') or CODE_ROOT).resolve()

def config():
    return json.loads((CODE_ROOT/'distribution/update-config.json').read_text(encoding='utf-8-sig'))

@lru_cache(maxsize=1)
def installed_rules():
    if not os.environ.get('FACTORY_DATA_HOME'):return None
    file=data_root()/'.runtime/updates/active_rules.json'
    if not file.exists():return None
    active=json.loads(file.read_text(encoding='utf-8'))
    version=active['version']
    if not isinstance(version,str) or not version.isdigit():raise ValueError('规则版本指针无效')
    root=data_root()/'.runtime/rules'/version
    if not (root/'manifest.json').is_file():raise ValueError('规则版本不完整')
    return root

def rule_root():return OVERRIDE.get() or installed_rules()

def rule_file(path):
    path=Path(path)
    root=rule_root()
    if root is None:return path
    try:relative=path.resolve().relative_to(CODE_ROOT)
    except ValueError:return path
    from tools.task_library import io_path
    candidate=io_path(root/relative)
    if candidate.suffix not in {'.json','.md'}:return path
    return candidate if candidate.is_file() else path

def read_json(path):
    from tools.task_library import io_path
    return json.loads(io_path(rule_file(path)).read_text(encoding='utf-8-sig'))

def version():
    root=rule_root()
    return json.loads((root/'manifest.json').read_text(encoding='utf-8'))['version'] if root else 'workspace'

@contextlib.contextmanager
def use_rules(root):
    token=OVERRIDE.set(Path(root))
    try:yield
    finally:OVERRIDE.reset(token)

def hidden_projects():
    if OVERRIDE.get() is not None:return []
    file=data_root()/'.runtime/hidden_projects.json'
    return json.loads(file.read_text(encoding='utf-8')).get('projects',[]) if file.exists() else []
