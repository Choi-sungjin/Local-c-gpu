#!/usr/bin/python3
"""Per-process CPU/GPU selection; never rewrite the shared agent configs."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOME = Path.home()
SETTINGS = Path(os.environ.get('LOCAL_C_GPU_SETTINGS', HOME / '.config/local-c-gpu/settings.json'))
REAL = {}
MODES = {}
CONFIG = {}


def load_settings():
    global CONFIG, REAL, MODES
    CONFIG = json.loads(SETTINGS.read_text())
    REAL = {k: Path(v) for k, v in CONFIG['executables'].items() if k in ('hermes', 'opencode')}
    MODES = {k: tuple(v) for k, v in CONFIG['modes'].items()}
    for path in REAL.values():
        if path.resolve() == Path(__file__).resolve():
            raise ValueError('Executable points back to the menu launcher; reinstall with real binary paths.')


ADMIN = {
    'hermes': {'config', 'cron', 'gateway', 'sessions', 'status', 'doctor', 'tools', 'model', 'setup', 'update', 'auth', 'backup', 'logs', 'mcp', 'skills', 'plugins', 'version', '--run-module'},
    'opencode': {'auth', 'session', 'models', 'debug', 'upgrade', 'uninstall', 'mcp', 'export', 'import', 'stats', 'completion'},
}


def choose_mode(stdin, stderr):
    if not stdin.isatty():
        print('비대화식 실행: CPU 모드 (GPU는 -gpu 명령 사용)', file=stderr)
        return 'cpu'
    print('\n1) CPU 전용 — 아이작심 사용 중\n2) GPU 가속\nq) 취소', file=stderr)
    while True:
        print('선택 [1]: ', end='', file=stderr, flush=True)
        line = stdin.readline()
        if not line:
            return None
        choice = line.strip().lower()
        if choice in ('', '1', 'cpu'):
            return 'cpu'
        if choice in ('2', 'gpu'):
            return 'gpu'
        if choice in ('q', 'quit'):
            return None
        print('1, 2 또는 q를 입력해줘.', file=stderr)


def environment(app, mode, source):
    env = copy.deepcopy(source)
    base, model, _ = MODES[mode]
    env['OLLAMA_HOST'] = base
    env['AGENT_COMPUTE_MODE'] = mode
    env['HERMES_HOME'] = CONFIG['hermes_home']
    env['LOCAL_C_GPU_SETTINGS'] = str(SETTINGS)
    env['LOCAL_C_GPU_EMBED_URL'] = base + '/api/embed'
    env['LOCAL_C_GPU_DATA'] = CONFIG['data_dir']
    if app == 'hermes':
        env['CUSTOM_BASE_URL'] = base + '/v1'
        env['LOCAL_C_GPU_BASE_URL'] = base + '/v1'
        env['HERMES_INFERENCE_MODEL'] = model
    else:
        config = json.loads(env.get('OPENCODE_CONFIG_CONTENT') or '{}')
        config.setdefault('mcp', {}).update(CONFIG.get('opencode_mcp', {}))
        config['model'] = 'ollama/' + model
        config['small_model'] = 'ollama/' + model
        provider = config.setdefault('provider', {}).setdefault('ollama', {})
        provider.update({'npm': '@ai-sdk/openai-compatible', 'name': 'Ollama ' + mode.upper()})
        provider.setdefault('options', {})['baseURL'] = base + '/v1'
        provider.setdefault('models', {})[model] = {
            'name': 'Qwen3.5 9B ' + mode.upper(), 'tools': True,
            'limit': {'context': 65536, 'output': 8192},
        }
        env['OPENCODE_CONFIG_CONTENT'] = json.dumps(config)
    return env


def command(app, mode, args):
    model = MODES[mode][1]
    if app == 'hermes':
        # Explicit model is needed by the classic interactive CLI, too.
        if args and args[0] == 'chat':
            return [str(REAL[app]), 'chat', '--model', model, '--provider', 'custom', *args[1:]]
        if args and args[0] in ADMIN[app]:
            return [str(REAL[app]), *args]
        return [str(REAL[app]), '--model', model, '--provider', 'custom', *args]
    return [str(REAL[app]), *args]


def ensure_server(mode):
    base, _, unit = MODES[mode]
    subprocess.run(['systemctl', '--user', 'start', unit], check=True, timeout=30)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + '/api/version', timeout=1) as response:
                if json.load(response).get('version'):
                    return
        except (OSError, ValueError, urllib.error.URLError):
            time.sleep(0.2)
    raise RuntimeError(f'{unit} 시작 확인 실패: {base}')


def main():
    load_settings()
    name = Path(sys.argv[0]).name
    app, sep, mode = name.partition('-')
    if app not in REAL or (sep and mode not in MODES):
        raise ValueError('지원하지 않는 실행 명령: ' + name)
    args = sys.argv[1:]
    # Management commands and help must not open menus or load models.
    if args in (['--help'], ['-h'], ['--version']) or (app == 'opencode' and args == ['-v']) or (
        not sep and args and args[0] in ADMIN[app]
    ):
        env = environment(app, mode if sep else 'cpu', dict(os.environ))
        os.execve(str(REAL[app]), [str(REAL[app]), *args], env)
    mode = mode if sep else choose_mode(sys.stdin, sys.stderr)
    if mode is None:
        return 0
    env = environment(app, mode, dict(os.environ))
    ensure_server(mode)
    print(f'[{app} {mode.upper()}] {MODES[mode][1]} · {MODES[mode][0]}', file=sys.stderr)
    os.execve(str(REAL[app]), command(app, mode, args), env)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('실행 실패: ' + str(exc), file=sys.stderr)
        sys.exit(1)
