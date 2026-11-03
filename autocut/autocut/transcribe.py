"""faster-whisper 로 단어 단위 타임스탬프가 있는 대본 만들기.

language="auto" 면 말소리 덩어리마다 언어를 따로 알아냄 (한국어 + 영어 인터뷰처럼 섞인 영상용).
영상 전체를 한 언어로 정해 버리면, 다른 언어 부분은 엉뚱하게 번역되거나 통째로 빠짐."""
import json
import os

from .media import read_wav

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

SR = 16000

# Whisper 는 "어", "음" 같은 소리를 대본에서 지워 버리는 경향이 있음.
# 필러가 들어간 예시 문장을 프롬프트로 주면 들리는 그대로 받아 적는 쪽으로 기움.
_VERBATIM_PROMPT = {
    "ko": "음, 어... 그러니까 음 이제 어, 시작해 볼게요. 음... 어 그게,",
    "en": "Um, uh... so, like, um, let's get started. Uh, you know,",
}


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
               device: str = "auto", languages=None) -> list:
    """[{id, start, end, text, lang, words:[{start, end, word}]}]"""
    languages = [l for l in (languages or []) if l]
    key = [model_name, language, sorted(languages) if language == "auto" else []]
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
        if isinstance(cached, dict) and cached.get("key") == key:
            log("이전 음성 인식 결과를 재사용합니다")
            return cached["segments"]

    model = _load_model(model_name, log, device)
    # 파일 경로 대신 배열을 넘김 (faster-whisper 내부 PyAV 디코더의 버전 호환 문제 회피)
    audio = read_wav(audio_path)[0][:, 0]
    if language == "auto":
        groups = _language_groups(model, audio, languages, log)
    else:
        groups = [(0.0, len(audio) / SR, language)]

    out = []
    for g_start, g_end, lang in groups:
        a, b = int(max(0.0, g_start - 0.2) * SR), int(min(len(audio) / SR, g_end + 0.2) * SR)
        offset = a / SR
        segments, _ = model.transcribe(
            audio[a:b],
            language=lang,
            word_timestamps=True,
            initial_prompt=_VERBATIM_PROMPT.get(lang),
            condition_on_previous_text=False,  # 같은 문장 무한 반복 환각 방지
            vad_filter=False,                  # 무음은 우리가 직접 판단
            beam_size=5,
        )
        for seg in segments:
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
                continue  # 말소리가 아닌데 지어낸 문장 (환각)
            words = [{"start": round(w.start + offset, 3), "end": round(w.end + offset, 3),
                      "word": w.word.strip()}
                     for w in (seg.words or []) if w.word.strip()
                     # 앞뒤 여유(0.2초)에 걸친 옆 묶음의 단어가 두 번 나오지 않게
                     and g_start - 0.1 <= (w.start + w.end) / 2 + offset <= g_end + 0.1]
            if not words:
                continue
            out.append({"id": len(out), "start": words[0]["start"], "end": words[-1]["end"],
                        "text": seg.text.strip(), "lang": lang, "words": words})
            log(f"  [{_ts(words[0]['start'])}] ({lang}) {seg.text.strip()}")
    del model

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"key": key, "segments": out}, f, ensure_ascii=False, indent=1)
    return out


def _language_groups(model, audio, allowed, log):
    """말소리 덩어리(VAD)마다 언어를 알아낸 뒤, 같은 언어끼리 이어 붙여 [(시작, 끝, 언어)]."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    opts = VadOptions(threshold=0.35, min_silence_duration_ms=400, speech_pad_ms=150)
    units = [[t["start"] / SR, t["end"] / SR, None, 0.0]
             for t in get_speech_timestamps(audio, opts)]
    if not units:
        return []

    for u in units:
        clip = audio[int(u[0] * SR):int(u[1] * SR)]
        _, _, probs = model.detect_language(clip)
        if allowed:
            probs = [p for p in probs if p[0] in allowed] or probs
        u[2], u[3] = probs[0]
        if u[1] - u[0] < 1.2:
            u[3] = min(u[3], 0.5)  # 너무 짧은 소리는 언어 판단을 믿기 어려움

    # 확신이 낮은 덩어리는 가까운 확실한 덩어리의 언어를 따름
    sure = [k for k, u in enumerate(units) if u[3] >= 0.6]
    if not sure:  # 전부 애매하면 가장 많이 나온 언어로
        top = max({u[2] for u in units}, key=lambda l: sum(u[1] - u[0] for u in units if u[2] == l))
        for u in units:
            u[2] = top
    else:
        for k, u in enumerate(units):
            if u[3] < 0.6:
                near = min(sure, key=lambda j: min(abs(units[j][0] - u[1]), abs(u[0] - units[j][1])))
                u[2] = units[near][2]

    # 같은 언어끼리 최대 28초 묶음으로 (Whisper 한 번에 30초까지 봄), 3초 넘게 쉬면 끊음
    groups = []
    for s, e, lang, _ in units:
        if groups and groups[-1][2] == lang and e - groups[-1][0] <= 28 and s - groups[-1][1] <= 3:
            groups[-1][1] = e
        else:
            groups.append([s, e, lang])
    langs = {}
    for s, e, lang in groups:
        langs[lang] = langs.get(lang, 0) + e - s
    log("   언어: " + ", ".join(f"{l} {t:.0f}초" for l, t in sorted(langs.items(), key=lambda x: -x[1])))
    return [tuple(g) for g in groups]


def _ts(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"
