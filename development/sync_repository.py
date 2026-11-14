"""Fetch and fast-forward only; never stash, reset, overwrite an index, or push."""
import argparse,subprocess
from pathlib import Path

def synchronize(repository):
    repository=Path(repository).resolve()
    def git(*args):
        return subprocess.check_output(['git','-C',str(repository),*args],text=True,stderr=subprocess.PIPE).strip()
    git('fetch','origin')
    upstream=git('rev-parse','--abbrev-ref','@{upstream}')
    before=git('rev-parse','HEAD')
    dirty=bool(git('status','--porcelain','--untracked-files=normal'))
    ahead,behind=map(int,git('rev-list','--left-right','--count','HEAD...'+upstream).split())
    if dirty or (ahead and behind):
        return {'state':'review_required','dirty':dirty,'ahead':ahead,'behind':behind,'head':before,
                'next':'保留修改，审阅并提交明确归属的本地改动，再合并远端；不得覆盖 release-index.json'}
    if behind:git('merge','--ff-only',upstream)
    return {'state':'fast_forwarded' if behind else 'current','head':git('rev-parse','HEAD'),'ahead':ahead}

if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('repository',type=Path)
    print(json.dumps(synchronize(parser.parse_args().repository),ensure_ascii=False))
