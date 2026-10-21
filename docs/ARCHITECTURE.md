# 한큐(HanQ) 구조

한큐는 HWPX 양식의 빈칸을 AI로 채우거나, 기본 서식으로 새 문서를 조립하거나, 완성된 문서를
대화로 고친다. 서식은 원본 XML을 그대로 두고 글자·문단만 바꾼다.

## 계층

```
main.py                     진입점 (.env 읽기, 앱 ID, App 실행)
hanq/
  config.py                 버전, 설정 파일(settings.json) 읽기/쓰기, 경로
  system.py                 윈도우/맥 차이 (글꼴, 파일 열기, 휠, CLI 환경변수)

  doc/                      ── HWPX 문서 엔진 (UI·AI를 모름) ──
    xml.py                  네임스페이스, 태그, 글자·문단·칸 도우미, 줄 기호 판별
    document.py             HwpxDocument: 열기/저장/바이트, 섹션, header 모양 복제
    outline.py              Outline: 문서를 AI용 번호(S·E·T·H·B·I)와 개요 글로 정리
    editor.py               Editor: 번호를 기준으로 채우기·끼워 넣기·지우기·옮기기·모양 바꾸기
    builder.py              DocumentBuilder: 기본 양식의 문단을 복제해 새 문서 조립
    render.py               간이 렌더러: 한글 없이 쪽 이미지를 그림 (실시간 미리보기용)

  readers/                  ── 참고 자료 읽기 ──
    __init__.py             read_reference(path) → 텍스트 (표는 '| 칸 | 칸 |' 줄로)
    hwp.py                  HWP 5.0 바이너리(OLE) 직접 읽기
    hwpx.py, pdf.py, docx.py, text.py

  ai/                       ── AI 호출 ──
    providers.py            Claude/GPT/Gemini/OpenRouter API, Claude Code/Codex CLI (스트리밍)
    jsonstream.py           받는 중인 JSON에서 완성된 항목·쓰는 중인 글자를 꺼냄
    jsonutil.py             JSON 추출·흔한 실수 고치기
    prompts.py              시스템 프롬프트

  services/                 ── 작업 흐름 (UI 없이 실행 가능) ──
    job.py                  Job: 상태 알림, 실시간 화면(프레임), 중단
    context.py              요청·기본 정보·참고 자료를 AI 입력으로 묶음
    generate.py             양식 채우기 / 새 문서 조립 (받는 대로 문서에 반영)
    edit.py                 대화 수정
    live.py                 LiveView: 바뀐 문서를 간이 렌더러로 그려 화면에 보냄

  hwp/                      ── 윈도우용 한글 COM ──
    worker.py               HwpWorker: 한글 하나를 전용 스레드에서 사용 (쪽 이미지, 쪽 위치, HWP→HWPX)
    security.py             보안 승인 모듈 등록

  ui/                       ── tkinter 화면 ──
    theme.py                색·글꼴·버튼·카드
    preview.py              PreviewPane: 쪽 이미지(파일·메모리), 확대, 강조 위치로 이동
    app.py                  App: 창, 탭, 상태 표시줄, 설정 저장, 공용 작업 실행
    generate_tab.py         문서 생성 탭 (양식, 요청, 참고 자료, 생성/정지)
    chat.py                 AI 수정 대화
    forms_tab.py            양식(템플릿) 탭
    settings_tab.py         설정 탭
    ime_font.py             한글 조합 글자 크기 맞추기 (윈도우)
```

의존 방향은 `ui → services → (doc, ai, readers, hwp) → config/system` 한쪽뿐이다.
`doc`, `readers`, `ai`는 tkinter를 import하지 않으므로 테스트(`tests/`)에서 그대로 돌릴 수 있다.

## 핵심 개념

### 줄 단위 번호
`Outline`은 **문단(줄) 하나를 S번호 하나**로 내놓는다. 한 줄 안에 글자 모양이 여러 개(`□ ` + `목 적`)
있어도 번호는 하나다. `Editor`가 줄 글자를 바꿀 때는 앞쪽 조각 중 새 글자의 앞부분과 같은 조각
(기호 `□ ` 등)은 모양째 남기고, 나머지 글자를 다음 조각에 넣은 뒤 남은 조각을 비운다.
→ 줄을 지우거나 바꿔도 조각이 남지 않는다.

### 실시간 생성 화면
1. AI 응답을 스트리밍으로 받는다 (`providers.complete(on_text=…)`).
2. `jsonstream.scan()`이 받은 글자에서 완성된 `slots`/`tables`/`blocks` 항목과 **쓰는 중인 글자**를 꺼낸다.
3. `Editor`가 그 줄에 바로 반영하고, `LiveView`가 문서를 메모리에서 저장해 아래 엔진 순서로 그린다.
   방금 쓴 줄은 노란 음영으로 표시하고 그 위치로 화면을 옮긴다.
4. 끝나면 결과 파일을 저장하고, 한글이 있으면 한글로 정확한 쪽 이미지를 다시 그린다.
스트리밍이 안 되는 경우(Codex)는 응답을 받은 뒤 같은 방식으로 한 줄씩 채워 보여준다.

### 미리보기 엔진 (빠른 것 → 정확한 것)
1. **한글(COM)** — 이번 실행에서 한글 미리보기가 한 번 성공했으면(보안 모듈 또는 [모두 허용]) 실시간 화면까지 한글이 그린다. 가장 정확.
2. **rhwp** (`hanq/hwp/rhwp.py`, https://github.com/edwardkim/rhwp, MIT) — 한글 없이 거의 같은 모양. HWP→HWPX 변환도 맡는다.
   빌드 때 `tools/fetch_rhwp.py`가 공식 릴리스를 받아 SHA256 확인 후 설치 파일에 넣는다.
3. 간이 렌더러(`doc/render.py`).

원본 파일(참고 자료·양식)은 1쪽에 파일 안의 한글 저장 그림(PrvImage)을 쓰고, 참고 자료는 별도 창에서 본다.
저장할 때는 글자·모양이 바뀐 문단만 줄 배치 정보(linesegarray)를 지운다 (도형 위치 보존).

### 참고 자료
모든 형식을 `readers.read_reference()` 하나로 읽는다. 표는 행 단위 `| 칸 | 칸 |`로 남겨 구조를 보존하고,
글자 수 한도는 자료 수로 나눠 한 자료가 다 차지하지 않게 한다. 읽은 내용은 화면에서 바로 확인할 수 있다.

### 한글 COM
`HwpWorker` 하나만 한글을 띄운다(미리보기·쪽 위치·HWP 변환 공용). 작업마다 제한 시간이 있어,
보안 승인 모듈이 없어 '접근 허용' 창에서 멈춰도 프로그램은 간이 미리보기로 계속 동작하고 안내를 띄운다.
