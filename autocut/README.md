# 유튜브 자동 1차 편집기 (autocut)

영상을 올리면 다음을 자동으로 합니다.

1. **컷 편집 1차**
   - 무음 구간 자르기 (말 앞뒤로 0.15초 여유를 남겨 자연스럽게)
   - 필러워드("어", "음" 등) 자르기
   - NG 구간 자르기: Claude가 대본을 읽고 다시 말한 문장, 말 더듬기, 촬영 중 혼잣말만 골라냄 (이해에 필요한 내용은 남김)
2. **설명 일러스트 넣기**: 말만으로 이해하기 어려운 부분에 '플랫 벡터 + 핸드드로잉 카툰' 스타일 그림을 글자 최소로 그려서, 그 말이 나오는 동안 화면에 보여 줌
3. **개인정보 처리**
   - 화면 속 글자(OCR): 전화번호·주민번호·계좌·카드·이메일·주소·차량번호 등을 모자이크
   - 말로 나온 개인정보: 삐- 소리로 가림
4. 결과물: `편집본.mp4`, 편집본 기준 자막 `.srt`, 무엇을 왜 잘랐는지 적은 `편집리포트.md`, 일러스트 PNG/SVG

## 처음 한 번 설정

PowerShell에서:

```powershell
cd D:\success\autocut
.\.venv\Scripts\Activate.ps1
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # https://console.anthropic.com 에서 발급
```

키를 계속 쓰려면 Windows 환경 변수에 `ANTHROPIC_API_KEY` 를 등록하세요.

## 실행

웹 화면 (영상 끌어다 놓기):

```powershell
python app.py
```

명령줄:

```powershell
python cli.py "D:\영상\촬영본.mp4" -o output
python cli.py 촬영본.mp4 --illustration-mode pip --max-illustrations 4
python cli.py 촬영본.mp4 --silence-db -45 --no-review
```

결과는 `output\` 폴더에 생깁니다. 중간 파일(대본, 편집 계획, 일러스트)은 `output\<영상이름>_work\` 에 있고, 같은 영상을 다시 돌리면 음성 인식 결과를 재사용합니다.

## 조절 팁

| 증상 | 조절 |
|---|---|
| 말소리 끝이 잘림 | 무음 기준을 더 낮게 (`--silence-db -45`) |
| 무음이 덜 잘림 | 무음 기준을 높게 (`-33`) 또는 `--min-silence 0.4` |
| 일러스트가 말과 안 맞음 | `<영상>_work\plan.json` 확인 후 리포트를 보고 판단 |
| 비용을 줄이고 싶음 | `--no-review`, `--max-illustrations 3` |

## 비용과 한계

- Claude API(claude-opus-5-5): 10분 영상 기준 편집 계획 1회 + 일러스트 장당 1~2회 호출.
- Whisper는 "어/음"을 대본에서 빼먹는 경우가 있어 필러가 일부 남을 수 있습니다. 무음 컷이 상당 부분 보완합니다.
- 얼굴은 모자이크하지 않습니다 (유튜버 본인 얼굴까지 가려지므로). 화면 속 글자와 음성만 처리합니다.
- 자동 편집이므로 **업로드 전 편집리포트를 보고 모자이크·컷 위치를 꼭 확인**하세요.
