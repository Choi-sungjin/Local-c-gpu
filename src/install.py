#!/usr/bin/env python3
"""Install only this project's files; upstream programs are installed separately."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def executable(value, candidates, name):
    paths = [value] if value else candidates
    for p in paths:
        if p and Path(p).is_file() and os.access(p, os.X_OK):
            p = Path(p).absolute()
            # Never adopt this or the older per-host menu launcher as a backend.
            target = p.resolve()
            if (target.parent.name, target.name) in {('agent-launcher','launch.py'), ('local-c-gpu','launcher.py')}:
                continue
            return str(p.resolve())
    raise ValueError(f'{name} executable not found. See docs/install.md; supply --{name}-bin PATH.')


def unit_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def write(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def service(ollama, models, port, mode):
    env = {
        'OLLAMA_HOST': f'127.0.0.1:{port}', 'OLLAMA_MODELS': str(models),
        'OLLAMA_CONTEXT_LENGTH': '65536', 'OLLAMA_NUM_PARALLEL': '1',
        'OLLAMA_MAX_LOADED_MODELS': '2', 'OLLAMA_KEEP_ALIVE': '2m',
        'OLLAMA_FLASH_ATTENTION': '1', 'OLLAMA_KV_CACHE_TYPE': 'q8_0',
    }
    if mode == 'cpu':
        env.update(CUDA_VISIBLE_DEVICES='-1', ROCR_VISIBLE_DEVICES='-1',
                   GGML_VK_VISIBLE_DEVICES='-1', OLLAMA_VULKAN='0')
    lines = ['[Unit]', f'Description=Local C GPU {mode.upper()} model server',
             'After=network-online.target', '[Service]', 'Type=simple',
             'ExecStartPre=/usr/bin/python3 -c ' + unit_quote("import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('127.0.0.1',"+str(port)+")); s.listen(1); s.close()"),
             'ExecStart=' + unit_quote(ollama) + ' serve']
    lines += ['Environment=' + unit_quote(k+'='+v) for k,v in env.items()]
    if mode == 'cpu':
        lines += ['CPUQuota=400%', 'CPUWeight=10', 'Nice=10']
    else:
        lines += ['UnsetEnvironment=CUDA_VISIBLE_DEVICES ROCR_VISIBLE_DEVICES GGML_VK_VISIBLE_DEVICES OLLAMA_VULKAN']
    return '\n'.join(lines + ['Restart=on-failure', 'RestartSec=3', '[Install]', 'WantedBy=default.target', ''])


def install(args):
    if sys.platform != 'linux':
        raise ValueError('This release supports Linux only.')
    home = Path.home()
    prefix = home / '.local/share/local-c-gpu'
    settings = home / '.config/local-c-gpu/settings.json'
    bindir = home / '.local/bin'
    units = home / '.config/systemd/user'
    if not 1024 <= args.cpu_port <= 65535 or not 1024 <= args.gpu_port <= 65535 or args.cpu_port == args.gpu_port:
        raise ValueError('Ports must be distinct integers in 1024..65535.')
    if args.pull and args.no_start:
        raise ValueError('--pull cannot be combined with --no-start.')
    old = json.loads(settings.read_text()) if settings.exists() else {}
    executables = {}
    for name, candidates in {
        'ollama': [shutil.which('ollama')],
        'opencode': [home/'.opencode/bin/opencode.real', home/'.opencode/bin/opencode', shutil.which('opencode')],
        'hermes': [home/'.hermes/hermes-agent/.hermes/bin/hermes', shutil.which('hermes')],
    }.items():
        value = getattr(args, name+'_bin') or old.get('executables', {}).get(name)
        executables[name] = executable(value, candidates, name)
    if args.rea_bin:
        rea = executable(args.rea_bin, [], 'rea')
    else:
        rea = old.get('rea_bin')
    commands = [app+suffix for app in ('hermes','opencode') for suffix in ('','-cpu','-gpu')]
    launcher = prefix/'launcher.py'
    conflicts = [bindir/n for n in commands if (bindir/n).exists() or (bindir/n).is_symlink()]
    conflicts = [p for p in conflicts if not (p.is_symlink() and p.resolve() == launcher)]
    if conflicts and not args.replace_commands:
        raise ValueError('Existing commands left untouched: ' + ', '.join(map(str,conflicts)) + '. Use --replace-commands to back up and replace these six commands only.')
    for p in conflicts:
        backup = p.with_name(p.name+'.before-local-c-gpu')
        if backup.exists() or backup.is_symlink():
            raise ValueError(f'Backup already exists; refusing to overwrite: {backup}')
    if not args.no_start:
        subprocess.run(['systemctl','--user','show-environment'], check=True, stdout=subprocess.DEVNULL)
    # Preserve prior configuration and data on repeated installs.
    cfg = old or {
        'hermes_home': str(prefix/'hermes'), 'data_dir': str(prefix/'data'),
        'modes': {'cpu':[f'http://127.0.0.1:{args.cpu_port}','qwen3.5-9b-cpu','local-c-gpu-cpu.service'],
                  'gpu':[f'http://127.0.0.1:{args.gpu_port}','qwen3.5-9b-64k','local-c-gpu-gpu.service']},
        'opencode_mcp': {},
    }
    # Reinstalling with changed ports needs coordinated config migration, not silent partial changes.
    if old and [args.cpu_port,args.gpu_port] != [int(old['modes'][x][0].rsplit(':',1)[1]) for x in ('cpu','gpu')]:
        raise ValueError('Existing ports differ. Reuse the original --cpu-port/--gpu-port values.')
    # A regular upstream wrapper can itself occupy a public command we replace.
    # Keep invoking its same-directory backup after the public name becomes our menu.
    for name, path in executables.items():
        if Path(path) in conflicts:
            executables[name] = str(Path(path).with_name(Path(path).name+'.before-local-c-gpu'))
    cfg['executables'] = executables
    cfg['rea_bin'] = rea
    prefix.mkdir(parents=True, exist_ok=True)
    prefix.chmod(0o700)
    for f in ('launcher.py','rag.py'):
        shutil.copy2(ROOT/'src'/f, prefix/f)
        (prefix/f).chmod(0o755)
    if args.with_rag:
        subprocess.run([sys.executable,'-m','venv',str(prefix/'venv')],check=True)
        subprocess.run([str(prefix/'venv/bin/python'),'-m','pip','install','-r',str(ROOT/'requirements-rag.txt')],check=True)
        cfg['rag_enabled'] = True
    hermes_mcp = {}
    if cfg.get('rag_enabled'):
        cmd = [str(prefix/'venv/bin/python'),str(prefix/'rag.py'),'serve']
        cfg['opencode_mcp'].setdefault('local-docs', {'type':'local','command':cmd,'enabled':True})
        hermes_mcp['local-docs'] = {'command':cmd[0],'args':cmd[1:],
            'tools':{'prompts':False,'resources':False,'include':['search_documents','read_document']}, 'env':{
            'LOCAL_C_GPU_EMBED_URL':'${LOCAL_C_GPU_EMBED_URL}', 'LOCAL_C_GPU_DATA':cfg['data_dir']}}
    if rea:
        cfg['opencode_mcp'].setdefault('rea', {'type':'local','command':[rea,'mcp'],'enabled':True})
        hermes_mcp['rea'] = {'command':rea,'args':['mcp']}
    hh = Path(cfg['hermes_home'])
    hh.mkdir(parents=True,exist_ok=True)
    hh.chmod(0o700)
    hc = hh/'config.yaml'
    # JSON is a YAML subset; no YAML parser needed for generation.
    if not hc.exists():
        write(hc,json.dumps({'model':{'default':'qwen3.5-9b-cpu','provider':'custom',
            'base_url':cfg['modes']['cpu'][0]+'/v1', 'ollama_num_ctx':65536},
            'agent':{'reasoning_effort':'none'},
            'tools':{'tool_search':{'enabled':'off'}},
            'mcp_servers':hermes_mcp},indent=2)+'\n')
    elif hermes_mcp:
        print('Existing Hermes config preserved. Optional MCP template: mcp-servers.example.json')
    write(hh/'mcp-servers.example.json',json.dumps({'mcp_servers':hermes_mcp},indent=2)+'\n')
    if not (hh/'.env').exists():
        write(hh/'.env','CUSTOM_BASE_URL=${LOCAL_C_GPU_BASE_URL:-'+cfg['modes']['cpu'][0]+'/v1}\nCUSTOM_API_KEY=ollama\n')
    Path(cfg['data_dir']).mkdir(parents=True,exist_ok=True)
    write(settings,json.dumps(cfg,indent=2)+'\n')
    bindir.mkdir(parents=True,exist_ok=True)
    for p in conflicts:
        backup = p.with_name(p.name+'.before-local-c-gpu')
        if backup.exists() or backup.is_symlink():
            raise ValueError(f'Backup already exists; refusing to overwrite: {backup}')
        p.rename(backup)
    for name in commands:
        p=bindir/name
        if p.is_symlink():p.unlink()
        p.symlink_to(launcher)
    for mode,port in [('cpu',args.cpu_port),('gpu',args.gpu_port)]:
        write(units/f'local-c-gpu-{mode}.service',service(executables['ollama'],home/'.ollama/models',port,mode),0o644)
    gateway='\n'.join(['[Unit]','Description=Local C GPU Hermes scheduler (CPU)',
        'After=network-online.target','[Service]','Type=simple',
        'ExecStart='+unit_quote(bindir/'hermes-cpu')+' gateway run',
        'Restart=on-failure','RestartSec=5','[Install]','WantedBy=default.target',''])
    write(units/'local-c-gpu-hermes.service',gateway,0o644)
    # This activation directory wins over older ~/.opencode/bin PATH entries.
    activate=prefix/'activate.sh'
    write(activate,'export PATH="'+str(bindir).replace('"','\\"').replace('$','\\$').replace('`','\\`')+':$PATH"\nhash -r 2>/dev/null || true\n',0o644)
    if not args.no_start:
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','start','local-c-gpu-cpu.service'],check=True)
    if args.pull:
        if args.no_start:raise ValueError('--pull requires the service to start; remove --no-start.')
        for attempt in range(30):
            try:
                with urllib.request.urlopen(cfg['modes']['cpu'][0]+'/api/version',timeout=1):break
            except OSError:
                if attempt==29:raise RuntimeError('CPU server is not responding.')
                time.sleep(1)
        env={**os.environ,'OLLAMA_HOST':cfg['modes']['cpu'][0]}
        for model in ['qwen3.5:9b'] + (['bge-m3'] if cfg.get('rag_enabled') else []):
            subprocess.run([executables['ollama'],'pull',model],env=env,check=True)
        for mode,name in [('cpu','qwen3.5-9b-cpu'),('gpu','qwen3.5-9b-64k')]:
            mf=prefix/f'Modelfile.{mode}'
            write(mf,'FROM qwen3.5:9b\nPARAMETER num_ctx 65536\n'+('PARAMETER num_gpu 0\nPARAMETER num_thread 4\n' if mode=='cpu' else ''))
            subprocess.run([executables['ollama'],'create',name,'-f',str(mf)],env=env,check=True)
    print('Installed. Activate in each terminal: source "'+str(activate)+'"')
    print('Models: rerun with --pull if not yet prepared. Existing agent histories stay in their original homes.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('ollama','hermes','opencode','rea'):p.add_argument('--'+name+'-bin')
    p.add_argument('--cpu-port',type=int,default=12434)
    p.add_argument('--gpu-port',type=int,default=12435)
    p.add_argument('--with-rag',action='store_true')
    p.add_argument('--pull',action='store_true')
    p.add_argument('--replace-commands',action='store_true')
    p.add_argument('--no-start',action='store_true',help='Stage files only; useful for isolated tests. Does not prove runtime operation.')
    try:install(p.parse_args())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print('Install failed: '+str(exc),file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
