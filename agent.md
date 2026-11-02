# agent.md

다른 AI 코딩 도구(Codex, Cursor, Gemini 등)를 위한 안내서입니다. 자세한 설명은 `CLAUDE.md` 와 같습니다.

## 한 줄 요약
`autocut/` 은 유튜브 영상을 자동으로 1차 편집하는 파이썬 프로그램입니다
(무음·필러·NG 컷 → 설명 일러스트 삽입 → 개인정보 모자이크/삐- 처리).

## 작업 전에 읽을 것
1. `autocut/README.md` — 사용법
2. `CLAUDE.md` — 코드 구조와 규칙
3. `autocut/autocut/pipeline.py` — 전체 흐름

## 단계별 작업 방식
1. 바꿀 파일을 먼저 읽고, 주변 코드의 이름 짓기·주석 스타일을 따릅니다.
2. 한 번에 한 가지만 고치고, 고친 뒤 바로 실행해서 확인합니다.
3. API 키 없이 확인할 수 있는 부분은 Claude 단계를 끄고 시험합니다
   (`Settings(cut_retakes=False, illustrations=False, pii_audio=False, pii_llm_check=False)`).
4. 결과를 사용자에게 쉬운 한국어로 설명합니다. 사용자는 초보자입니다.

## 코드 규칙
- Python 3.12, 가상환경 `autocut/.venv`
- 시간 계산은 원본 기준, 화면 합성 때만 편집본 시간으로 변환
- `.bat` 파일에는 한글을 쓰지 않음
- 새 라이브러리를 추가하면 `autocut/requirements.txt` 에도 적기

## 금지 사항
- `api_key.txt`, `.env` 등 비밀 정보 커밋 금지
- 영상·오디오 파일, `output/`, `.venv/` 커밋 금지
- 사용자 확인 없이 파일 대량 삭제, 강제 푸시(`git push --force`) 금지
