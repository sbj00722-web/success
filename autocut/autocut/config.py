"""편집 파이프라인 전체 설정값.
각 값은 autocut/.env 에서 대문자 이름으로 바꿀 수 있음 (예: SILENCE_DB=-45). 목록은 .env.example."""
import os
from dataclasses import dataclass, field, fields, asdict, replace


DEFAULT_FILLERS = ["어", "어어", "음", "음음", "으음", "으", "엄", "흠", "에", "에에", "어음", "음어",
                   "um", "umm", "uh", "uhh", "uhm", "erm"]


@dataclass
class Settings:
    # 음성 인식 (faster-whisper)
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"     # auto | cuda | cpu
    language: str = "auto"           # auto: 말소리 덩어리마다 언어를 알아냄 (한국어+영어 섞인 영상) / ko, en 등으로 고정
    languages: list = field(default_factory=lambda: ["ko", "en"])  # auto 일 때 고를 언어 (비우면 전부)

    # 자막
    burn_subtitles: bool = True      # 영상에 자막을 직접 넣음 (끄면 srt 파일만)
    subtitle_polish: bool = True     # AI(Claude → OpenAI)로 오타 고치기 + 외국어 한국어 번역
    local_translate: bool = True     # AI 를 못 쓸 때 PC 안의 번역 모델로 외국어 → 한국어 (처음 한 번 약 5GB 다운로드)
    local_translate_model: str = "facebook/nllb-200-distilled-1.3B"
    subtitle_show_original: bool = True  # 외국어 자막에 원래 말도 작게 같이 표시
    subtitle_max_chars: int = 28     # 한국어 자막 한 덩어리 최대 글자 수 (외국어는 2배)
    subtitle_size: float = 0.05      # 글자 크기 (영상 짧은 변 대비 비율)
    subtitle_bottom: float = 0.07    # 화면 아래에서 띄우는 거리 (비율)
    subtitle_font: str = "malgunbd.ttf"

    # 1차 컷: 무음
    cut_silence: bool = True
    silence_db: float = -38.0        # 이 dBFS 아래를 무음으로 판단
    min_silence: float = 0.6         # 이 길이(초) 이상 무음만 자름
    keep_silence: float = 0.3        # 자른 자리에 남길 무음(초) - 너무 빡빡하면 부자연스러움

    # 1차 컷: 필러워드 / 실수(NG) 구간
    cut_fillers: bool = True
    filler_words: list = field(default_factory=lambda: list(DEFAULT_FILLERS))
    cut_retakes: bool = True         # Claude가 판단한 말 더듬기·다시 말하기 구간

    # 설명 일러스트
    illustrations: bool = True
    max_illustrations: int = 6
    illustration_mode: str = "full"  # full: 전체 화면 / pip: 오른쪽 위 카드
    illustration_review: bool = True # 그린 결과를 Claude가 한 번 더 보고 고침
    font_family: str = "Malgun Gothic"
    image_engine: str = "auto"       # auto: OPENAI_API_KEY 있으면 openai, 없으면 claude(SVG)
    image_model: str = "gpt-image-2"
    image_quality: str = "medium"    # low / medium / high (높을수록 비쌈)

    # 개인정보
    pii_screen: bool = True          # 화면 속 글자(OCR) 모자이크
    pii_audio: bool = True           # 말로 나온 개인정보 삐- 처리
    pii_llm_check: bool = True       # 정규식 외에 Claude가 OCR 글자를 한 번 더 검사
    blur_faces: bool = False         # 얼굴 모자이크 (본인 얼굴도 가려지므로 기본은 끔)
    ocr_every: float = 1.0           # 몇 초마다 화면 글자를 검사할지 (짧을수록 정확, 느림)
    ocr_width: int = 960             # OCR 할 때 줄이는 가로 크기 (클수록 작은 글자도 읽지만 느림)

    # Claude
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "high"      # low / medium / high
    openai_text_model: str = "gpt-5.5"  # Claude 를 못 쓸 때 자막 다듬기·번역에 쓸 OpenAI 모델

    # 출력 인코딩
    video_codec: str = "auto"        # auto(NVIDIA 그래픽카드면 h264_nvenc) | h264_nvenc | libx264
    video_quality: int = 20          # 낮을수록 고화질 (파일 커짐)
    video_preset: str = "medium"     # libx264 속도 (ultrafast ~ veryslow)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        """기본값 ← .env(환경변수) ← overrides 순으로 덮어씀."""
        s = cls()
        for f in fields(cls):
            raw = os.environ.get(f.name.upper(), "").strip()
            if raw:
                try:
                    setattr(s, f.name, _parse(raw, getattr(s, f.name)))
                except ValueError:
                    raise ValueError(f".env 의 {f.name.upper()}={raw} 값을 읽을 수 없어요") from None
        return replace(s, **overrides)


def _parse(raw: str, default):
    if isinstance(default, bool):
        if raw.lower() in ("1", "true", "yes", "on"):
            return True
        if raw.lower() in ("0", "false", "no", "off"):
            return False
        raise ValueError(raw)
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, list):
        return [w.strip() for w in raw.split(",") if w.strip()]
    return raw
