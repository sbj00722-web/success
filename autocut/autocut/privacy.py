"""개인정보 찾기: 화면 속 글자(OCR) → 모자이크 박스, 말로 나온 것 → 삐- 구간."""
import re

import numpy as np

from . import llm, media

PATTERNS = {
    "휴대폰번호": r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}",
    "전화번호": r"0\d{1,2}[-.)\s]\d{3,4}[-.\s]\d{4}",
    "주민등록번호": r"\d{6}\s?[-–]\s?[1-4][\d*]{6}",
    "이메일": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "카드번호": r"\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}",
    "계좌번호": r"\d{3,6}-\d{2,6}-\d{2,8}",
    "차량번호": r"\d{2,3}\s?[가-힣]\s?\d{4}",
    "주소": r"[가-힣0-9]+(?:로|길)\s?\d+(?:-\d+)?|\d+동\s?\d+호",
    "여권번호": r"\b[MSRO]\d{8}\b",
}
_RE = {k: re.compile(v) for k, v in PATTERNS.items()}

LLM_SYSTEM = """You check text strings that were read (by OCR) from frames of a Korean YouTube video.
Return the indices of strings that expose personal information of a private individual:
real names next to contact info or on IDs/documents/delivery labels, phone numbers, addresses,
resident registration numbers, account/card numbers, emails, license plates, login IDs/passwords,
order/tracking numbers tied to a person. Ignore UI labels, product names, public figures, brands,
and generic words. Be precise; when unsure, include it."""

LLM_SCHEMA = {
    "type": "object",
    "properties": {"pii_indices": {"type": "array", "items": {"type": "integer"}}},
    "required": ["pii_indices"],
    "additionalProperties": False,
}


def regex_type(text: str):
    compact = text.replace(" ", "")
    for name, rx in _RE.items():
        if rx.search(text) or rx.search(compact):
            return name
    return None


def screen_pii(video: str, info, settings, log):
    """원본 시간 기준 모자이크 목록 [(t0, t1, x0, y0, x1, y1, 종류)]"""
    import easyocr
    import torch

    reader = easyocr.Reader(["ko", "en"], gpu=torch.cuda.is_available(), verbose=False)
    step = 1.0 / settings.ocr_fps
    ocr_w = min(1280, info.width)
    scale = info.width / ocr_w

    hits = []   # (t, box, text)
    for t, frame in media.sample_frames(video, step, ocr_w):
        for box, text, conf in reader.readtext(frame):
            if conf < 0.2 or len(text.strip()) < 2:
                continue
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            hits.append((t, (min(xs) * scale, min(ys) * scale, max(xs) * scale, max(ys) * scale), text))
    log(f"  OCR 글자 {len(hits)}개 검사")

    flagged = {}
    for i, (_, _, text) in enumerate(hits):
        kind = regex_type(text)
        if kind:
            flagged[i] = kind

    if settings.pii_llm_check and hits:
        uniq = sorted({text for _, _, text in hits})[:1500]
        listing = "\n".join(f"{i}: {s}" for i, s in enumerate(uniq))
        try:
            res = llm.ask_json(settings.model, LLM_SYSTEM, listing, LLM_SCHEMA, effort="medium")
            bad = {uniq[i] for i in res["pii_indices"] if 0 <= i < len(uniq)}
            for i, (_, _, text) in enumerate(hits):
                if text in bad and i not in flagged:
                    flagged[i] = "개인정보(AI 판단)"
        except llm.LLMError as e:
            log(f"  AI 개인정보 검사 건너뜀: {e}")

    boxes = []
    for i, kind in flagged.items():
        t, (x0, y0, x1, y1), text = hits[i]
        px, py = (x1 - x0) * 0.12 + 6, (y1 - y0) * 0.35 + 6
        # 다음 샘플까지 화면에 남아 있을 수 있으므로 앞뒤 한 스텝씩 덮음
        boxes.append([t - step, t + step,
                      max(0, x0 - px), max(0, y0 - py),
                      min(info.width, x1 + px), min(info.height, y1 + py), kind])
        log(f"  [{t:6.1f}s] {kind} 발견 → 모자이크")
    return _merge_boxes(boxes)


def _iou(a, b):
    ix = max(0, min(a[4], b[4]) - max(a[2], b[2]))
    iy = max(0, min(a[5], b[5]) - max(a[3], b[3]))
    inter = ix * iy
    area = lambda r: (r[4] - r[2]) * (r[5] - r[3])
    return inter / (area(a) + area(b) - inter + 1e-6)


def _merge_boxes(boxes):
    """연속된 샘플에서 같은 자리에 있는 박스는 하나로 합침"""
    out = []
    for b in sorted(boxes):
        for o in out:
            if b[0] <= o[1] and _iou(o, b) > 0.3:
                o[1] = max(o[1], b[1])
                o[2], o[3] = min(o[2], b[2]), min(o[3], b[3])
                o[4], o[5] = max(o[4], b[4]), max(o[5], b[5])
                break
        else:
            out.append(list(b))
    return [tuple(o) for o in out]


def pixelate(frame: np.ndarray, x0, y0, x1, y1):
    import cv2
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    roi = frame[y0:y1, x0:x1]
    h, w = roi.shape[:2]
    if h < 2 or w < 2:
        return
    block = max(10, min(w, h) // 3)
    small = cv2.resize(roi, (max(1, w // block), max(1, h // block)), interpolation=cv2.INTER_AREA)
    frame[y0:y1, x0:x1] = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def beep(audio: np.ndarray, sr: int, spans):
    """원본 오디오의 spans 구간을 1kHz 삐- 소리로 바꿈"""
    for s, e in spans:
        a, b = int(s * sr), min(len(audio), int(e * sr))
        if b <= a:
            continue
        t = np.arange(b - a) / sr
        tone = 0.25 * np.sin(2 * np.pi * 1000 * t)
        audio[a:b] = tone[:, None] if audio.ndim == 2 else tone
    return audio
