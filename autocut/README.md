# 유튜브 자동 1차 편집기 (autocut)

영상을 넣으면 다음을 자동으로 합니다.

1. **컷 편집 1차**
   - 무음 구간 자르기 (말 앞뒤로 0.15초 여유를 남겨 자연스럽게)
   - 필러워드("어", "음" 등) 자르기
   - NG 구간 자르기: Claude가 대본을 읽고 다시 말한 문장, 말 더듬기, 촬영 중 혼잣말만 골라냄 (이해에 필요한 내용은 남김)
2. **설명 그림 넣기**: 말만으로 이해하기 어려운 부분에 '플랫 벡터 + 핸드드로잉 카툰' 스타일 그림을 글자 최소로 넣음
   - OpenAI 키가 있으면 OpenAI 이미지 모델(`gpt-image-2`)이 그리고, 한글 라벨은 프로그램이 직접 씀
   - 없으면 Claude가 SVG로 직접 그림
3. **개인정보 처리**
   - 화면 속 글자(OCR): 전화번호·주민번호·계좌·카드·이메일·주소·차량번호 등을 모자이크
   - 말로 나온 개인정보: 삐- 소리로 가림
   - 얼굴 모자이크(선택): `--blur-faces`
4. 결과물: `편집본.mp4`, 편집본 기준 자막 `.srt`, 무엇을 왜 잘랐는지 적은 `편집리포트.md`, 설명 그림 PNG

## 폴더 구성

| 이름 | 하는 일 |
|---|---|
| `claude_success/` | 여기에 영상을 넣으면 `watch.bat` 이 자동 처리. 끝난 원본은 `claude_success/done/`, 실패하면 `claude_success/failed/` (`.env` 의 `IN_DIR` 로 다른 폴더 지정 가능) |
| `output/` | 결과물. 중간 파일(대본, 편집 계획, 그림, OCR 결과)은 `output/<영상이름>_work/` |
| `samples/` | 시험용 영상 (`test_video.mp4`) |
| `autocut/` | 프로그램 본체 |
| `.env.example` | API 키 적는 양식 → `.env` 로 복사해서 사용 |
| `run.bat` | 영상을 끌어다 놓으면 편집. 그냥 더블클릭하면 편집기 화면 |
| `watch.bat` | `claude_success/` 지켜보기 시작 |
| `실행.bat` | 편집기 화면 열기 |

## 처음 한 번 설정: API 키

`.env.example` 을 복사해서 이름을 `.env` 로 바꾸고, 키를 붙여넣으세요.

| 키 | 없으면 |
|---|---|
| `ANTHROPIC_API_KEY` | NG 컷 · 설명 그림 · 말한 개인정보 단계를 건너뜀 (나머지는 정상) |
| `OPENAI_API_KEY` | 설명 그림을 Claude가 SVG로 그림 |

키가 있어도 **크레딧(충전 금액)이 0원이면** 해당 단계는 건너뛰고 나머지는 계속 진행합니다.

## 설정 바꾸기 (.env)

`.env` 아래쪽 "선택 설정"에 모든 설정이 기본값과 함께 적혀 있습니다.
바꾸고 싶은 줄만 맨 앞 `#` 을 지우고 값을 고치면 됩니다. 예:

```
SILENCE_DB=-45        # 말소리 끝이 잘리면 더 낮게
BLUR_FACES=true       # 얼굴 모자이크 켜기
VIDEO_CODEC=libx264   # 그래픽카드 인코딩 끄기
```

편집기 화면의 처음 값도 `.env` 를 따릅니다. 명령줄 옵션을 주면 그 값이 `.env` 보다 우선입니다.

## 실행 방법 3가지

1. **폴더 자동 처리**: `watch.bat` 을 켜 두고 영상을 `claude_success/` 에 넣기 → 결과는 `output/`
2. **끌어다 놓기**: 영상 파일을 `run.bat` 위에 끌어다 놓기 (여러 개 가능)
3. **명령줄**:

```powershell
cd D:\success\autocut
.\.venv\Scripts\python.exe -m autocut samples\test_video.mp4
.\.venv\Scripts\python.exe -m autocut 촬영본.mp4 --illustration-mode pip --max-illustrations 4
.\.venv\Scripts\python.exe -m autocut 촬영본.mp4 --silence-db -45 --no-review --blur-faces
```

같은 영상을 다시 돌리면 음성 인식과 OCR 결과를 재사용해서 빠르게 끝납니다.

## 조절 팁

| 증상 | 조절 |
|---|---|
| 말소리 끝이 잘림 | 무음 기준을 더 낮게 (`--silence-db -45`) |
| 무음이 덜 잘림 | 무음 기준을 높게 (`-33`) 또는 `--min-silence 0.4` |
| 그림이 말과 안 맞음 | `<영상>_work\plan.json` 확인 후 리포트를 보고 판단 |
| 비용을 줄이고 싶음 | `--no-review`, `--max-illustrations 3` |
| Claude 그림을 쓰고 싶음 | `--image-engine claude` |

## 비용과 한계

- Claude(claude-opus-5-5): 10분 영상 기준 편집 계획 1회 + 그림 검토 장당 1회.
- OpenAI(gpt-image-2, 보통 품질): 그림 장당 1장 (검토에서 문제가 있으면 1장 더).
- Whisper는 "어/음"을 대본에서 빼먹는 경우가 있어 필러가 일부 남을 수 있습니다. 무음 컷이 상당 부분 보완합니다.
- 얼굴은 기본으로 가리지 않습니다 (본인 얼굴도 가려지므로). 필요하면 `--blur-faces`.
- 자동 편집이므로 **업로드 전 편집리포트를 보고 모자이크·컷 위치를 꼭 확인**하세요.
