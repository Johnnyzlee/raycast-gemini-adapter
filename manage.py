"""Manage one installation; preserve unrelated providers and running checkouts."""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen

import yaml
from adapter import ROOT, MODELS, configured_key, AdapterError
from configuration import load_settings

ORIGINAL_BASE='https://generativelanguage.googleapis.com/v1beta/openai'


def configure(path=None):
    global SETTINGS, SETTINGS_PATH, PROVIDERS, DATA, BASE, LABEL, PLIST, DOMAIN, INSTALL
    SETTINGS_PATH=Path(path).expanduser().resolve() if path else ROOT/'settings.json'
    SETTINGS=load_settings(path)
    PROVIDERS=Path(SETTINGS['providers_file']).expanduser()
    DATA=Path(SETTINGS['state_dir']).expanduser()
    BASE='http://127.0.0.1:'+str(SETTINGS['port'])
    LABEL=SETTINGS['service_label'];DOMAIN='gui/'+str(os.getuid())
    PLIST=Path(SETTINGS.get('launchagents_dir','~/Library/LaunchAgents')).expanduser()/(LABEL+'.plist')
    INSTALL=DATA/'installation.json'


configure()


def health():
    try:
        with urlopen(BASE+'/health',timeout=2) as r:
            data=json.load(r)
            return data.get('service')=='gemini-raycast-adapter'
    except (OSError,ValueError):return False


def edit_endpoint(text,source,target,provider_id='gemini'):
    before=yaml.safe_load(text)
    matches=[p for p in before['providers'] if p['id']==provider_id]
    if len(matches)!=1 or matches[0].get('base_url','').rstrip('/')!=source.rstrip('/'):
        raise ValueError('Expected one '+provider_id+' provider using '+source)
    match=re.search(r'(?m)^  - id: '+re.escape(provider_id)+r'[ \t]*$',text)
    if not match:raise ValueError('Use the provider indentation shown in examples/providers.example.yaml')
    end=re.search(r'(?m)^  - id:|^\S',text[match.end():]);end=match.end()+end.start() if end else len(text)
    block,n=re.subn(r'(?m)^    base_url:.*$','    base_url: '+target,text[match.start():end])
    if n!=1:raise ValueError('Expected one base_url in the selected provider')
    updated=text[:match.start()]+block+text[end:]
    expected=yaml.safe_load(text)
    next(p for p in expected['providers'] if p['id']==provider_id)['base_url']=target
    if yaml.safe_load(updated)!=expected:raise ValueError('Provider verification failed')
    return updated


def write_atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def launch(*args,check=True):
    return subprocess.run(['launchctl',*args],check=check,capture_output=True,text=True)


def owned_service():
    if not PLIST.exists():raise ValueError('No installed service; run install first')
    args=plistlib.loads(PLIST.read_bytes()).get('ProgramArguments',[])
    if str(ROOT/'adapter.py') not in args:
        raise ValueError('This service belongs to another checkout. Manage it from its installed directory.')


def validate_provider(original):
    configured_key(SETTINGS)
    provider=next(p for p in yaml.safe_load(original)['providers'] if p['id']==SETTINGS['provider_id'])
    models=provider.get('models',[])
    if not models or any(m.get('id') not in MODELS for m in models):raise ValueError('Configure only supported Gemini 4 models in this provider')
    for model in models:
        if not all(model.get('abilities',{}).get(k,{}).get('supported') is True for k in ('tools','vision')):
            raise ValueError('Enable tools and vision for each model, as in the provider example')
    if not (ROOT/'.venv/bin/python').exists():raise ValueError('Create .venv and install requirements first')


def install(dry_run=False):
    original=PROVIDERS.read_bytes();validate_provider(original)
    updated=edit_endpoint(original.decode(),ORIGINAL_BASE,BASE,SETTINGS['provider_id']).encode()
    if PLIST.exists() or INSTALL.exists():raise ValueError('Installation already exists; use its installed checkout to manage it')
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',SETTINGS['port']))
        except OSError:raise ValueError('Port is occupied; choose a free port before installation') from None
    if not SETTINGS_PATH.is_file():raise ValueError('Copy settings.example.json to settings.json and review it first')
    if dry_run:
        print('Validated. Would install',LABEL,'and set the selected provider URL to',BASE)
        print('No files changed, service started or API calls made.');return
    DATA.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(DATA,0o700)
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup=DATA/'backups'/stamp/'providers.yaml';write_atomic(backup,original)
    plist={'Label':LABEL,'ProgramArguments':[str(ROOT/'.venv/bin/python'),'-u',str(ROOT/'adapter.py'),'--settings',str(SETTINGS_PATH)],
           'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,'ProcessType':'Background','ThrottleInterval':10,
           'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},
           'StandardOutPath':str(DATA/'service.log'),'StandardErrorPath':str(DATA/'service.log')}
    write_atomic(PLIST,plistlib.dumps(plist));switched=False
    try:
        launch('bootstrap',DOMAIN,str(PLIST))
        for _ in range(40):
            if health():break
            time.sleep(.25)
        else:raise ValueError('Service did not become healthy; inspect the private service.log')
        if PROVIDERS.read_bytes()!=original:raise ValueError('Provider configuration changed during installation; preserving that edit')
        write_atomic(PROVIDERS,updated);switched=True
        write_atomic(INSTALL,json.dumps({'backup':str(backup),'original_base':ORIGINAL_BASE,'installed_base':BASE,'provider_id':SETTINGS['provider_id'],'checkout':str(ROOT)}).encode())
    except Exception:
        launch('bootout',DOMAIN+'/'+LABEL,check=False);PLIST.unlink(missing_ok=True)
        if switched and PROVIDERS.read_bytes()==updated:write_atomic(PROVIDERS,original)
        raise
    print('Installed:',BASE,'— provider keys and unrelated entries preserved.')


def rollback():
    owned_service()
    info=json.loads(INSTALL.read_text())
    original=PROVIDERS.read_bytes()
    updated=edit_endpoint(original.decode(),info.get('installed_base',BASE),info.get('original_base',ORIGINAL_BASE),info.get('provider_id',SETTINGS['provider_id'])).encode()
    if PROVIDERS.read_bytes()!=original:raise ValueError('Concurrent provider edit; retry after reviewing it')
    write_atomic(PROVIDERS,updated)
    launch('bootout',DOMAIN+'/'+LABEL,check=False);PLIST.unlink(missing_ok=True);INSTALL.unlink(missing_ok=True)
    print('Restored the official Google endpoint and removed login startup. Other providers and local state preserved.')


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['install','status','start','stop','restart','rollback','uninstall','cleanup-video-files','clear-history'])
    parser.add_argument('--settings',help='Settings JSON; defaults to settings.json in this checkout')
    parser.add_argument('--dry-run',action='store_true',help='Validate install without changes or API calls')
    args=parser.parse_args();configure(args.settings)
    if args.dry_run and args.command!='install':parser.error('--dry-run is for install only')
    try:
        if args.command=='install':install(args.dry_run)
        elif args.command in ('rollback','uninstall'):rollback()
        elif args.command in ('start','stop','restart'):
            owned_service()
            if args.command=='start':launch('bootstrap',DOMAIN,str(PLIST))
            elif args.command=='stop':launch('bootout',DOMAIN+'/'+LABEL)
            else:launch('kickstart','-k',DOMAIN+'/'+LABEL)
            print(args.command.capitalize()+' requested.')
        elif args.command=='status':
            print('Service healthy:',health());print('Endpoint:',BASE);print('Provider ID:',SETTINGS['provider_id'])
            print('ffprobe:',shutil.which(SETTINGS['ffprobe']) or 'not found (needed for local videos)')
            if PLIST.exists():owned_service();print('Installed checkout:',ROOT)
        else:
            from adapter import State
            from video_tools import VideoTools
            state=State(DATA)
            try:
                if args.command=='cleanup-video-files':print(json.dumps(VideoTools(SETTINGS,state,configured_key(SETTINGS)).cleanup(True)))
                else:
                    with state.lock:
                        for table in ('histories','history_metadata','pending_aliases','presentations','recovery_checkpoints'):state.db.execute('DELETE FROM '+table)
                        state.db.commit()
                    print('Conversation checkpoints and source pages cleared. Video-upload records preserved.')
            finally:state.db.close()
    except (AdapterError,ValueError,OSError,KeyError,StopIteration,subprocess.CalledProcessError) as e:
        # Do not print raw YAML or subprocess environments containing credentials.
        raise SystemExit('Management failed: '+str(e)[:500]) from None


if __name__=='__main__':main()
