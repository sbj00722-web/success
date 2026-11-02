# CLAUDE.md

이 저장소에서 일하는 Claude Code 용 안내서입니다.

## 프로젝트

`autocut/` — 유튜브 영상 자동 1차 편집기. 영상을 넣으면:
1. faster-whisper 로 단어 단위 대본 생성
2. 무음 · 필러워드("어", "음") · NG(다시 말하기) 구간 컷
3. 이해가 어려운 대목에 '플랫 벡터 + 핸드드로잉 카툰' 설명 일러스트(Claude 가 SVG 로 그림) 삽입
4. 화면 속 개인정보(OCR) 모자이크, 말로 나온 개인정보 삐- 처리
5. 편집본 mp4 + 자막 srt + 편집 리포트 md 출력

사용자는 초보자입니다. 설명은 한국어로, 쉬운 말로 합니다.

## 실행

- 환경: Windows 11, Python 3.12 가상환경 `autocut/.venv`, GPU RTX 3070 (CUDA torch)
- 사용자용 실행: `autocut/실행.bat` 더블클릭 → `launch.py` 가 API 키 확인 후 Gradio 화면(`app.py`) 실행
- 명령줄: `autocut/.venv/Scripts/python.exe autocut/cli.py 영상.mp4 -o output`
- 의존성 설치: `autocut/requirements.txt` (torch 는 cu126 인덱스로 먼저 설치)
- Claude 단계가 없는 부분만 시험하려면 `Settings(cut_retakes=False, illustrations=False, pii_audio=False, pii_llm_check=False)`

## 코드 구조 (`autocut/autocut/`)

| 파일 | 역할 |
|---|---|
| `config.py` | 모든 설정값(`Settings`) |
| `media.py` | ffmpeg 호출 (imageio-ffmpeg 내장 바이너리, ffprobe 없이 `ffmpeg -i` 파싱) |
| `transcribe.py` | faster-whisper, 결과를 `transcript.json` 에 캐시 |
| `cuts.py` | 무음/필러 컷, 문장 위치 찾기, 원본↔편집본 시간 변환(`Timeline`) |
| `llm.py` | Claude API 공통 호출 (스트리밍 + 구조화 출력 + 서버 측 fallback) |
| `planner.py` | 대본 → NG 컷 / 일러스트 위치 / 말한 개인정보 계획 |
| `illustrate.py` | Claude SVG 생성 → 손그림 필터 래핑 → resvg 로 PNG, 렌더 결과를 Claude 가 재검토 |
| `privacy.py` | EasyOCR + 정규식(+Claude) 개인정보 탐지, 모자이크, 삐- 소리 |
| `render.py` | 프레임 단위 합성(컷·모자이크·일러스트) 후 libx264 인코딩 |
| `pipeline.py` | 전체 순서 조립, srt·리포트 작성 |

## 규칙

- Claude 모델은 `claude-opus-5-5` (설정에서 변경 가능). 사용자가 바꾸라고 하기 전에는 그대로 둡니다.
- 시간은 모두 **원본 기준**으로 계산하고, 화면에 넣을 때만 `Timeline.to_new()` 로 편집본 시간으로 바꿉니다.
- 컷 구간은 프레임 경계에 맞춰야 오디오/영상 싱크가 맞습니다 (`keep_intervals`).
- `.bat` 파일에 한글을 넣지 않습니다 (cmd 가 UTF-8 을 깨뜨림). 한글 안내는 `launch.py` 에서 출력합니다.
- 비밀 정보(`api_key.txt`, `.env`)는 절대 커밋하지 않습니다.
- 모델 다운로드 SSL 오류 대비로 `autocut/__init__.py` 에서 `truststore` 를 주입합니다.
