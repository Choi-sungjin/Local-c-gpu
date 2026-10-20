# Ubuntu 설치·복구

## 필수 프로그램

일반 사용자로 설치하세요. 이 프로젝트의 `install.sh`를 sudo로 실행하지 마세요.

```bash
sudo apt update
sudo apt install -y git curl python3 python3-venv
```

업스트림 공식 설치 안내:

- [Ollama Linux](https://docs.ollama.com/linux)
- [Hermes 설치](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
- [OpenCode 설치](https://opencode.ai/docs/)

설치 스크립트를 확인한 뒤 실행하는 예시입니다. 설치 시점의 업스트림 코드가 실행되며,
이 프로젝트가 해당 다운로드 전체를 고정하거나 검증하는 것은 아닙니다.

```bash
curl -fsSL https://ollama.com/install.sh -o /tmp/ollama-install.sh
less /tmp/ollama-install.sh
sh /tmp/ollama-install.sh

curl -fsSL https://hermes-agent.nousresearch.com/install.sh -o /tmp/hermes-install.sh
less /tmp/hermes-install.sh
bash /tmp/hermes-install.sh

curl -fsSL https://opencode.ai/install -o /tmp/opencode-install.sh
less /tmp/opencode-install.sh
bash /tmp/opencode-install.sh
```

호스트에서 사용한 버전: Ollama 0.32.5, Hermes 0.22.2, OpenCode 1.19.3.
새 버전에서는 옵션·설정 형식이 달라질 수 있습니다. 완전한 버전 잠금 배포가 아닙니다.

## 이 프로젝트 설치

```bash
./install.sh --with-rag --pull --replace-commands
source "$HOME/.local/share/local-c-gpu/activate.sh"
hermes config check
```

Hermes는 새 데이터 폴더에 처음 접근할 때 별도의 의존성 환경을 준비할 수 있습니다.
이전에 설치된 프로그램을 재사용하더라도 `hermes config check`에 추가 다운로드 시간이 걸릴 수 있습니다.
준비 전 `hermes --version`만 실행하면 의존성 환경이 없다는 메시지가 나올 수 있습니다.

설치기는 업스트림 실행 파일을 찾지 못하면 설치 위치를 알려달라고 표시합니다.
그 경우 `--hermes-bin`, `--opencode-bin`, `--ollama-bin`에 실제 실행 파일 절대 경로를 지정하세요.
CPU/GPU 선택 메뉴 파일을 실제 실행 파일로 다시 지정하면 안 됩니다.

`--no-start`는 서비스 시작 없이 파일만 배치하는 검사 옵션입니다. 모델 준비 또는 실제 설치 성공의 증거가 아닙니다.
`--cpu-port 12434 --gpu-port 12435`로 처음 설치할 때 포트를 지정할 수 있습니다.
재설치할 때도 같은 값을 사용하세요. 해당 포트가 이미 사용 중이면 먼저 충돌을 해소하세요.

Bash를 새로 열 때도 적용하려면 `~/.bashrc` **맨 마지막**에 다음 한 줄을 직접 추가합니다.

```bash
source "$HOME/.local/share/local-c-gpu/activate.sh"
```

다른 설치기가 뒤에서 PATH를 바꾸면 메뉴를 건너뛸 수 있습니다.
`type -a hermes opencode`로 첫 경로가 `~/.local/bin`인지 확인하세요.
`hermes-cpu`, `opencode-gpu` 등 모드 지정 명령에는 메뉴가 나오지 않습니다.
도움말·버전·관리 명령도 메뉴를 생략하며, 입력 터미널이 없는 실행은 CPU를 선택합니다.

## 업데이트

업스트림 프로그램의 업데이트는 해당 공식 방법을 사용하세요.
설치 위치가 바뀌면 이 설치기를 실제 실행 파일 경로와 함께 다시 실행합니다.
업데이트 뒤 `source`와 `type -a`로 메뉴가 유지되는지 확인하세요.
이 설치기는 기존 개인 에이전트 설정을 읽거나 업로드하지 않지만, OpenCode 자체는
자신의 전역/프로젝트 설정을 추가로 읽으므로 기존 외부 제공자·도구 설정도 적용될 수 있습니다.
선택한 CPU/GPU 연결은 이 배포판의 기본 Ollama 모델과 문서 검색에 적용됩니다.
임의 외부 도구나 사용자가 별도로 지정한 모델의 하드웨어까지 제한하지 않습니다.

## 제거

먼저 이 배포판 서비스만 중지합니다.

```bash
systemctl --user disable --now local-c-gpu-hermes.service
systemctl --user stop local-c-gpu-cpu.service local-c-gpu-gpu.service
```

`~/.local/bin`의 6개 명령이 이 프로젝트를 가리키는지 확인한 뒤 해당 링크만 제거하고,
있다면 `.before-local-c-gpu` 백업을 원래 이름으로 복원합니다.
`~/.bashrc`에서 추가한 source 줄을 제거합니다.
`~/.config/systemd/user/local-c-gpu-*.service` 세 파일을 제거한 뒤
`systemctl --user daemon-reload`를 실행합니다.

`~/.local/share/local-c-gpu`에는 대화·문서 검색 데이터가 있으므로 필요한 데이터를 먼저 백업하세요.
`~/.ollama/models`는 다른 Ollama 설치와 공유하므로 이 프로젝트 제거만을 위해 삭제하지 마세요.
