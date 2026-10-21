# 다음 작업: 서식 분석 → 같은 서식 새 문서 + 명령줄 도구·스킬

어느 컴퓨터에서든 이 저장소만 받으면 이어서 할 수 있게 적은 작업 지시서입니다.
(Claude Code에게: "docs/NEXT_TASK.md대로 진행해". 답은 한국어로.)

## 시작 전 준비

```bash
git clone https://github.com/HOTS-GG/hwp_ai_writer.git
cd hwp_ai_writer
pip install -r requirements.txt
python tools/fetch_rhwp.py          # 한글 없이 미리보기·HWP 변환 (rhwp, MIT)
python -m unittest discover -s tests -t .
```

- 구조는 `docs/ARCHITECTURE.md`를 먼저 읽는다.
- 예제 양식은 저장소의 `forms/*.hwpx`만 쓴다. (집 PC의 범정부오피스 양식은 저장소에 없음.
  필요하면 `HANQ_HWP_SAMPLES` 환경변수로 HWP 예제 폴더를 지정하면 관련 테스트가 돈다)
- 윈도우 셸 heredoc은 백슬래시를 바꿔 버리므로 파일 편집은 편집 도구로 한다.

## 1) 서식 분석 → 같은 서식의 새 문서

지금 '자유 작성'은 기본 학교 양식 하나(`forms/01_…`)만 복제하는 `DocumentBuilder`라,
사용자가 고른 아무 양식의 서식으로 새 문서를 쓰지 못한다.

- 새 모듈 `hanq/doc/styleset.py`
  - 본문 문단을 역할(장 제목 상자, 소제목, 글머리 기호별 줄, 본문, 표, 글상자)로 나누고,
    모양(`paraPrIDRef` + 주 `charPrIDRef` + 줄 기호 `marker_of`)이 같은 것끼리 **서식 종류**(H1, B1, T1 …)로 묶는다.
  - 종류마다 본보기 문단(복제용)과 예시 글을 가진다.
  - AI용 뼈대: 서식 종류 목록 + 원본 순서의 뼈대 글(각 줄 앞에 `{B2}` 표시).
- AI 응답: `{"title": …, "blocks": [{"style": "B2", "text": "…"}, {"style": "T1", "columns": […], "rows": […]}]}`
- 조립: 표지·머리 부분은 남기고, 본문은 종류별 본보기를 복제해 채운다
  (`hanq/doc/xml.py`의 `clone_line`, `build_table_paragraph`). 장 번호는 다시 매긴다(`Editor._renumber_headings` 참고).
- 서비스: `hanq/services/generate.py`에 `build_like(job, form_path, out, request, refs, info, ai)`.
  `_LiveBuilder`처럼 blocks를 받는 대로 붙여 `Job.frame`으로 실시간 화면을 보낸다.
  프롬프트는 `hanq/ai/prompts.py`에 `STYLE_BUILD_SYSTEM`.
- UI: 문서 생성 탭에 '양식 채우기 / 같은 서식으로 새로 쓰기' 선택 (`hanq/ui/generate_tab.py`).
- 참고(방식만, 코드 복사 아님): https://github.com/ZZombie04/hwpx_new (MIT) — analyze → 서식 종류 → 뼈대 → 원본 요소 복제.

## 2) 명령줄 도구와 스킬

- `python -m hanq` (`hanq/__main__.py`, `hanq/cli.py`)
  - `analyze <양식>` 서식 종류·개요 출력
  - `fill <양식> -r 요청 [-f 참고자료 …] -o 출력.hwpx`
  - `build-like <양식> -r 요청 … -o 출력.hwpx`
  - `edit <문서> -m 지시 -o 출력.hwpx`
  - `read <파일>` 참고 자료 글 (표는 `| 칸 |`)
  - `preview <파일> -o 폴더` rhwp 쪽 이미지
  - `convert <hwp> -o <hwpx>`
  - AI 설정은 `hanq.config.load()`(settings.json)을 쓰고 `--provider/--model`로 덮어쓰기.
    서비스 계층(`hanq/services`)은 UI와 분리돼 있으니 얇게 붙인다.
- Claude Code 스킬: `skills/hanq/SKILL.md` (언제 쓰는지, 명령 예시)

## 완료 기준

- `python -m unittest discover -s tests -t .` 통과 — 가짜 AI로 `build_like`·CLI 테스트 추가
  (`tests/test_services.py`의 `fake_complete` 패턴)
- `python -m pyflakes hanq tests` 깨끗
- `docs/ARCHITECTURE.md` 갱신, 이 파일은 완료 후 지운다
- 새 브랜치에 커밋하고, push·PR은 사용자에게 물어본다
  (`main`에 합치면 `hanq/config.py`의 `APP_VERSION`으로 릴리스가 자동 생성되니 버전도 올린다)
