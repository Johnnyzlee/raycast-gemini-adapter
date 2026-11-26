"""Audit explicit tracked/staged files and reachable history without printing secrets."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PATTERNS=[('Google API key',re.compile(rb'AIza[0-9A-Za-z_-]{30,}')),
          ('GitHub token',re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,})')),
          ('API secret',re.compile(rb'\bsk-[A-Za-z0-9_-]{24,}')),
          ('private key',re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
          ('personal absolute path',re.compile(rb'/Users/(?!YOUR_USER(?:/|\b)|YOUR_USERNAME(?:/|\b))[a-zA-Z0-9_.-]+/'))]
BLOCKED={'.env','settings.json','providers.yaml','AGENTS.md'}


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)


def audit(known=()):
    failures=[];checked=set()
    def inspect(name,data):
        for label,pattern in PATTERNS:
            if pattern.search(data):failures.append((name,label))
        for value in known:
            if len(value)>15 and value.encode() in data:failures.append((name,'configured credential'))
    names=git('ls-files','-z').decode().split('\0')
    for name in filter(None,names):
        p=Path(name)
        if p.name in BLOCKED or p.suffix in ('.sqlite','.db','.log','.mp4') or any(x in p.parts for x in ('.venv','backups','local-evidence','__pycache__')):
            failures.append((name,'private/runtime artifact'))
        data=git('show',':'+name);inspect(name,data);checked.add(name)
    # A fresh repository can have an index before its first commit.
    refs=git('rev-list','--all').strip()
    if refs:
        for line in git('rev-list','--objects','--all').decode().splitlines():
            sha,_,name=line.partition(' ')
            if git('cat-file','-t',sha).strip()==b'blob':inspect('history:'+name,git('cat-file','blob',sha))
        for sha in refs.decode().splitlines():inspect('commit:'+sha,git('show','-s','--format=%B',sha))
    if failures:
        for name,reason in sorted(set(failures)):print(name+': '+reason,file=sys.stderr)
        return False
    print('Publication audit passed:',len(checked),'indexed files and all reachable history; no matching secrets or personal paths.')
    return True


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--credentials-file',help='Optional local provider file: check actual key values without printing them');args=p.parse_args()
    values=[]
    if args.credentials_file:
        import yaml
        data=yaml.safe_load(Path(args.credentials_file).expanduser().read_text())
        values=[v for provider in data.get('providers',[]) for v in provider.get('api_keys',{}).values() if isinstance(v,str)]
    raise SystemExit(0 if audit(values) else 1)
