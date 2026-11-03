"""faster-whisper 로 단어 단위 타임스탬프가 있는 대본 만들기."""
import json
import os

from .media import read_wav

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# Whisper 는 "어", "음" 같은 소리를 대본에서 지워 버리는 경향이 있음.
# 필러가 들어간 예시 문장을 프롬프트로 주면 들리는 그대로 받아 적는 쪽으로 기움.
_VERBATIM_PROMPT = "음, 어... 그러니까 음 이제 어, 시작해 볼게요. 음... 어 그게,"


def _load_model(name: str, log, device: str = "auto"):
    from faster_whisper import WhisperModel
    if device != "cpu":
        try:
            # torch 를 먼저 import 하면 torch 에 들어 있는 cuBLAS/cuDNN DLL 을 ctranslate2 가 찾을 수 있음
            import torch
            if torch.cuda.is_available() or device == "cuda":
                model = WhisperModel(name, device="cuda", compute_type="float16")
                log(f"음성 인식 모델 {name} (GPU) 로드")
                return model
        except Exception as e:  # GPU 초기화 실패 시 CPU 로 (cuda 를 직접 고른 경우는 오류)
            if device == "cuda":
                raise
            log(f"GPU 사용 실패, CPU 로 진행합니다: {e}")
    model = WhisperModel(name, device="cpu", compute_type="int8")
    log(f"음성 인식 모델 {name} (CPU) 로드 - 시간이 오래 걸릴 수 있어요")
    return model


def transcribe(audio_path: str, cache_path: str, model_name: str, language: str, log,
               device: str = "auto") -> list:
    """[{id, start, end, text, words:[{start, end, word}]}]"""
    if os.path.exists(cache_path):
        log("이전 음성 인식 결과를 재사용합니다")
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)

    model = _load_model(model_name, log, device)
    # 파일 경로 대신 배열을 넘김 (faster-whisper 내부 PyAV 디코더의 버전 호환 문제 회피)
    audio, _ = read_wav(audio_path)
    segments, info = model.transcribe(
        audio[:, 0],
        language=language,
        word_timestamps=True,
        initial_prompt=_VERBATIM_PROMPT,
        condition_on_previous_text=False,  # 같은 문장 무한 반복 환각 방지
        vad_filter=False,                  # 무음은 우리가 직접 판단
        beam_size=5,
    )
    out = []
    for seg in segments:
        words = [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
                 for w in (seg.words or []) if w.word.strip()]
        if not words:
            continue
        out.append({"id": len(out), "start": words[0]["start"], "end": words[-1]["end"],
                    "text": seg.text.strip(), "words": words})
        log(f"  [{_ts(seg.start)}] {seg.text.strip()}")

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def _ts(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"
