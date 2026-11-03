"""대본을 읽고 Claude 가 편집 계획(NG 컷, 설명 일러스트 위치, 말로 나온 개인정보)을 세움."""
from . import llm

SYSTEM = """당신은 한국 유튜브 영상의 숙련된 편집자입니다.
타임스탬프가 붙은 대본을 읽고 편집 계획을 JSON 으로 냅니다.

## 1. retake_cuts: 실수(NG) 구간
다음만 자릅니다.
- 말을 시작했다가 끊고 처음부터 다시 말한 경우 → 실패한 앞부분만 (뒤의 완성된 문장은 남김)
- 같은 문장을 여러 번 시도한 경우 → 마지막 완성본만 남기고 앞의 시도들
- "아 잠깐만", "다시 할게요", "이거 편집해 주세요" 처럼 시청자에게 의미 없는 촬영 중 혼잣말
- 단어를 더듬어 반복한 부분 (예: "그 그 그래서" → 앞의 "그 그")

절대 지키세요:
- 이해에 필요한 내용은 자르지 않습니다. 애매하면 남깁니다. 강조를 위한 의도적 반복도 남깁니다.
- phrase 는 해당 세그먼트 text 안에 실제로 있는 글자를 그대로 복사합니다. 세그먼트 전체를 자를 때는 text 전체를 넣습니다.
- 한 phrase 는 한 세그먼트 안에 있어야 합니다. 여러 세그먼트에 걸치면 항목을 나눕니다.

## 2. illustrations: 이해를 돕는 설명 화면
말만으로는 머릿속에 그리기 어려운 개념·과정·비교·숫자·구조가 나오는 지점을 골라, 그 말이 나오는 동안 보여 줄 그림을 계획합니다.
- 최대 {max_ill} 개. 꼭 도움이 되는 곳만 고르고, 서로 최소 20초 이상 떨어뜨립니다.
- start_segment_id ~ end_segment_id 동안 화면에 나옵니다 (보통 1~2개 세그먼트, 3~8초 분량).
- label: 그림에 들어갈 글자. 한국어 0~8자. 글자 없이 그림만으로 충분하면 빈 문자열.
- scene: 일러스트레이터에게 줄 장면 설명(영어). 등장 사물, 배치, 화살표/흐름, 강조할 점을 구체적으로.
  스타일은 따로 정해져 있으니 장면 내용만 씁니다. 글자는 label 외에 넣지 말라고 적습니다.
- 실존 인물·브랜드 로고를 그리게 하지 않습니다.

## 3. spoken_pii: 말로 나온 개인정보 (소리를 삐- 처리)
전화번호, 주민등록번호, 계좌·카드번호, 상세 주소(동·호수·번지), 이메일, 차량번호, 비밀번호,
그리고 일반인(유튜버 본인·공인 제외)의 실명이 나오면 표시합니다.
phrase 는 개인정보 부분만, 세그먼트 text 그대로 복사합니다.

없으면 빈 배열로 둡니다."""

_ITEM_PHRASE = {
    "type": "object",
    "properties": {
        "segment_id": {"type": "integer"},
        "phrase": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["segment_id", "phrase", "reason"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "retake_cuts": {"type": "array", "items": _ITEM_PHRASE},
        "illustrations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_segment_id": {"type": "integer"},
                    "end_segment_id": {"type": "integer"},
                    "concept": {"type": "string"},
                    "label": {"type": "string"},
                    "scene": {"type": "string"},
                },
                "required": ["start_segment_id", "end_segment_id", "concept", "label", "scene"],
                "additionalProperties": False,
            },
        },
        "spoken_pii": {"type": "array", "items": _ITEM_PHRASE},
        "summary": {"type": "string"},
    },
    "required": ["retake_cuts", "illustrations", "spoken_pii", "summary"],
    "additionalProperties": False,
}


def plan(segments: list, settings) -> dict:
    lines = [f"[{s['id']}] ({s['start']:.1f}-{s['end']:.1f}s) {s['text']}" for s in segments]
    content = ("다음은 영상 대본입니다. 각 줄은 [세그먼트 id] (시작-끝 초) 텍스트 입니다.\n\n"
               + "\n".join(lines)
               + "\n\nsummary 에는 영상 주제를 한두 문장으로 씁니다.")
    max_ill = settings.max_illustrations if settings.illustrations else 0
    return llm.ask_json(settings.claude_model, SYSTEM.replace("{max_ill}", str(max_ill)), content,
                        SCHEMA, effort=settings.claude_effort)
