# Local C GPU

Ubuntu에서 **Hermes + OpenCode + Ollama Qwen3.5 9B**를 CPU/GPU 선택 메뉴로 실행하는 설치 도구.

```text
hermes / opencode
  1) CPU 전용
  2) GPU 가속
  q) 취소
```

```bash
hermes-cpu     # GPU를 쓰지 않는 전용 모델 서버
hermes-gpu     # GPU 사용을 허용하는 모델 서버
hermes         # 매 실행 시 선택
opencode-cpu
opencode-gpu
opencode
```

GPU 모드는 GPU 사용 가능 여부와 메모리에 따라 일부 또는 전체가 CPU로 돌아갈 수 있습니다.
CPU 모드도 CPU/RAM을 사용하므로 다른 프로그램에 영향이 전혀 없다는 뜻은 아닙니다.
이미 실행 중인 GPU 작업은 CPU 명령을 실행해도 중지되지 않습니다.

## 설치

대상: Ubuntu 24.04, Python 3.10 이상, Bash, 로그인한 사용자의 systemd 서비스.
Windows/macOS는 이 릴리스의 지원 대상이 아닙니다.

먼저 [필수 프로그램 설치](docs/install.md)에 따라 Ollama, Hermes, OpenCode를 설치합니다.
이 저장소는 해당 프로그램·모델 바이너리를 재배포하지 않습니다.

```bash
git clone https://github.com/Choi-sungjin/Local-c-gpu.git
cd Local-c-gpu
./install.sh --with-rag --pull --replace-commands
source "$HOME/.local/share/local-c-gpu/activate.sh"
hermes config check   # 새 데이터 폴더의 의존성 준비 및 설정 확인
hermes
```

`--replace-commands`는 `~/.local/bin`의 동일 이름 명령 6개만 `.before-local-c-gpu`로 백업하고 교체합니다.
기존 백업이 있으면 덮어쓰지 않습니다. 기존 Hermes/OpenCode 개인 설정은 복사하지 않습니다.
명령 인식이 달라지면 위 `source` 명령을 다시 실행하세요. 영구 적용은 [설치 안내](docs/install.md)를 참고하세요.

`--pull`은 Qwen3.5 9B와 검색용 bge-m3를 내려받으므로 저장 공간과 네트워크가 필요합니다.
이미 같은 사용자 모델 저장소에 있는 파일은 재사용합니다.
새 PC에서는 메모리와 드라이버를 확인한 후 GPU 모드를 선택하세요.

## 문서 검색 (RAG)

RAG는 모델이 답하기 전에 내 문서를 찾아 참고하게 하는 기능입니다.
개인 강의·노트·검색 데이터는 이 저장소에 포함하지 않습니다.
**선택한 폴더의 Markdown과 텍스트만** 직접 등록합니다.

```bash
systemctl --user start local-c-gpu-cpu
"$HOME/.local/share/local-c-gpu/venv/bin/python" \
  "$HOME/.local/share/local-c-gpu/rag.py" build "$HOME/my-documents"
"$HOME/.local/share/local-c-gpu/venv/bin/python" \
  "$HOME/.local/share/local-c-gpu/rag.py" search '찾고 싶은 내용'
hermes-cpu
```

에이전트에 `search_documents로 문서를 검색한 뒤 출처를 붙여 답해줘`라고 요청할 수 있습니다.
검색과 문서 읽기 도구는 두 에이전트에 연결됩니다. CPU 선택 시 검색 임베딩도 CPU 서버를 사용합니다.
작은 모델이 도구 탐색 단계를 건너뛰지 않도록 Hermes에는 두 검색 도구의 설명을 처음부터 제공합니다.
그래도 모델이 도구를 항상 정확히 선택한다는 보장은 없습니다.
PDF/이미지/OCR, 기존 개인 강의 일정 계산 기능은 포함하지 않습니다.
`build`는 기존 검색 인덱스를 새 폴더 내용으로 교체합니다. 원본 문서는 수정하지 않습니다.
숨김 경로·심볼릭 링크·1MB 초과 파일은 제외하며, 하위 폴더를 포함합니다.
민감한 문서가 섞이지 않은 전용 폴더를 지정하세요.

## 대화 이어가기·REA·예약 실행

- 같은 배포판의 CPU/GPU 명령은 같은 Hermes 데이터 폴더를 사용합니다.
  `hermes-cpu --resume SESSION_ID`처럼 기존 옵션을 그대로 전달합니다.
- 기존 `~/.hermes`의 대화 기록은 자동 복사하지 않습니다. `hermes sessions --help`로 새 환경의 세션을 확인하세요.
- REA는 별도 설치한 실행 파일을 `./install.sh --rea-bin /absolute/path/to/rea`로 지정합니다.
  처음 설치할 때 함께 지정하는 것을 권장합니다. REA 프로그램·인증·개인 스킬은 포함하지 않습니다.
- Hermes 예약 작업은 `hermes cron --help`로 관리합니다. 상시 실행은 아래 서비스로 켭니다.

```bash
systemctl --user enable --now local-c-gpu-hermes
systemctl --user status local-c-gpu-hermes
```

예약 실행 서비스는 CPU 모드를 사용합니다. 로그아웃 이후에도 유지하려면 관리자가
`sudo loginctl enable-linger "$USER"`를 설정해야 합니다. PC가 꺼져 있거나 절전 상태이면 실행되지 않습니다.
기존 다른 Hermes gateway와 새 서비스에 같은 외부 메시징 계정을 중복 연결하지 마세요.

## 설정과 복구

| 항목 | 위치 / 기본값 |
|---|---|
| 배포판 설정 | `~/.config/local-c-gpu/settings.json` |
| Hermes 전용 설정·대화 | `~/.local/share/local-c-gpu/hermes` |
| 문서 검색 데이터 | `~/.local/share/local-c-gpu/data` |
| CPU / GPU 서버 | `127.0.0.1:12434` / `127.0.0.1:12435` |
| 모델 저장소 | `~/.ollama/models` |

CPU/GPU 서비스는 요청 시 시작하며 기본 설치에서 GPU 모델을 미리 로드하지 않습니다.
GPU 메모리를 바로 돌려주려면 `systemctl --user stop local-c-gpu-gpu`를 실행하세요.
다른 Ollama 서버가 사용하는 메모리까지 해제하지는 않습니다.
재설치 시 기존 Hermes 설정을 보존합니다. 이후 RAG/REA를 추가하면 출력되는
`mcp-servers.example.json`을 참고해 Hermes의 `config.yaml`에 `mcp_servers`를 병합해야 합니다.

[설치·업데이트·제거](docs/install.md) · [검증 범위](docs/validation.md)

## 개발 검사

```bash
python3 -m unittest discover -s tests -v
```

이 검사는 임시 홈·가짜 실행 파일로 설치/명령 전달을 검사하고, 실제 가상 터미널로 메뉴를 검사합니다.
외부 프로그램 다운로드, GPU 드라이버, 실제 모델 품질 검사를 대신하지 않습니다.
