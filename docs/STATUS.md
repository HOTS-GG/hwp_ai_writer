# 현 상황 (2026-10-28)

어느 PC에서든 이어서 작업할 수 있게 적은 현황 기록입니다. 구조는 `docs/ARCHITECTURE.md`,
아직 손대지 않은 큰 작업은 `docs/NEXT_TASK.md`를 봅니다.

## 버전·배포

| 항목 | 상태 |
|---|---|
| 배포된 최신 | v1.1.1 (2026-10-22) — 윈도우 설치 exe(NSIS), 맥 dmg(arm64·x86_64) |
| 이 브랜치 | `feature/auto-setup` → **1.2.0** (main에 합치면 GitHub Actions가 릴리스 자동 생성) |
| 저장소 | https://github.com/HOTS-GG/hwp_ai_writer (공개) |
| 테스트 | `python -m unittest discover -s tests -t .` — 54개 통과 (4개는 HWP 예제 폴더가 있어야 실행) |
| 코드 검사 | `python -m pyflakes hanq tests` 깨끗 |

## 1.2.0에서 한 일 (feature/auto-setup)

1. **자동 업데이트** (`hanq/updater.py`, `hanq/ui/update.py`)
   - 켤 때 4초 뒤 GitHub 최신 릴리스를 조용히 확인 → 새 버전이면 알림 창
     ([지금 업데이트] / [다음에] / [이 버전 건너뛰기]), 설정 탭 '업데이트'에서 [지금 확인]·자동 확인 끄기.
   - 설치 파일을 받아 **크기와 SHA-256(릴리스 asset digest)** 확인 → 한큐를 닫고 배치(`%TEMP%\hanq_update.cmd`)가
     `start /wait 설치파일 /S /D=설치폴더` 후 새 한큐를 띄운다. 맥은 dmg를 열어 줌, 소스 실행은 릴리스 페이지만.
   - NSIS: 조용한 설치(업데이트)일 때는 바탕화면 바로가기가 원래 있었을 때만 다시 만든다.
   - 릴리스 본문에 커밋 메시지를 '## 바뀐 점'으로 넣어 알림 창에 보이게 함 (`.github/workflows/build.yml`).
2. **구독 연결 자동화** (`hanq/ai/cli_setup.py`, 설정 탭 `_CliBox`)
   - [한 번에 설정]: 설치(Claude Code 공식 스크립트 / Codex는 npm, Node 없으면 winget으로 Node.js) →
     로그인 창(`claude auth login` / `codex login`) → 로그인 끝났는지 몇 초마다 확인 → 그 방식 선택.
   - 상태 표시: `claude auth status --json`, `codex login status`로 "✓ 설치됨 · ✓ 로그인됨 (pro 구독)".
   - [명령어 복사], [고급 ▾](실행 파일 경로·모델·다른 계정으로 로그인).
   - Claude/Codex 데스크톱 앱에 들어 있는 실행 파일도 자동으로 찾는다 (`providers.find_cli`).
3. **'접근 허용' 보안 모듈 자동 탑재** (`hanq/hwp/security.py`)
   - 켤 때(윈도우) 등록 전이면: 함께 넣은 DLL(`assets/security/*.dll`, 빌드 때 포함) → 바탕화면·다운로드·문서에서
     `FilePathChecker*.dll` 또는 한컴에서 받은 zip을 찾아 꺼내 자동 등록. 설정 탭에 [자동으로 찾기]·[받는 곳 열기].
   - **결정 필요:** 한컴 예제 DLL(`FilePathCheckerModuleExample.dll`)을 공개 저장소의 `assets/security/`에 넣어
     설치 파일에 포함할지. 패키지에 재배포 조건 문서가 없어 아직 넣지 않았다.
4. **AI 연결 안내 창** (`hanq/ui/connect.py`): 키도 구독도 없을 때 경고 대신
   [Claude 구독이 있어요] / [ChatGPT 구독이 있어요] / [API 키가 있어요] → 바로 설정 진행.
   API 키를 붙여 넣으면(지금 방식이 쓸 수 없는 상태일 때) 그 제공자를 자동 선택.
5. **템플릿: AI가 채울 곳 보기** (`hanq/doc/annotate.py`, 템플릿 탭)
   - 양식 사본에 형광펜: 노랑=채울 빈칸, 파랑=고칠 수 있는 예시문, 초록=행 수까지 맞추는 표, 색 없음=그대로.
   - 왼쪽에 요약("빈칸 31곳 · 예시문 3줄 · 표 2개")과 범례. 양식을 추가하면 바로 분석하고, 채울 곳이 없으면 안내.
   - 이 과정에서 발견한 문제를 고침: 표지(첫 장 제목 앞)의 교훈·슬로건·주소가 '예시문'으로 잡혀 AI가 바꿀 수 있었음
     → 표지 문장은 예시문에서 뺌 (`Outline._in_body`).

## 아직 확인 못 한 것

- **실제 설치 파일로 업데이트 끝까지**: NSIS가 이 PC에 없고, 실제 설치 파일은 실행 중인 한큐를 닫고 기존 설치를
  지우므로 시험하지 않았다. 배치 순서(인자 전달·기다림·다시 실행, 공백 경로)는 가짜 설치 파일로 확인함.
  → 1.2.0 릴리스 후 1.2.1을 하나 더 내서 1.2.0 → 1.2.1 자동 업데이트를 실제로 확인할 것.
- **[한 번에 설정]의 실제 설치**: 이 PC에는 두 CLI가 이미 있어 설치 단계는 실행하지 않았다(로그인 상태 읽기는 확인).
  Codex의 winget Node.js 설치는 관리자 권한 창이 뜰 수 있음.
- 맥: 업데이트(dmg 열기)와 Terminal로 로그인 창 띄우기는 코드만 있고 맥에서 시험하지 않았다.

## 다음 후보

- `docs/NEXT_TASK.md`: 서식 분석 → 같은 서식으로 새 문서(build-like), 명령줄 도구·스킬.
- 템플릿 탭에서 색칠한 곳을 눌러 '고정/채우기'를 바꾸는 기능 (지금은 보기만).
- 업데이트 알림을 상태 표시줄에 작게 띄우는 방식 (창 대신) — 사용자 반응 보고 결정.
