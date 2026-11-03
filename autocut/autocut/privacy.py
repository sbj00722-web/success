"""개인정보 찾기: 화면 속 글자(OCR) → 모자이크 박스, 말로 나온 것 → 삐- 구간."""
import re
import time

import cv2
import numpy as np

from . import llm, media

PATTERNS = {
    "휴대폰번호": r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}",
    "전화번호": r"0\d{1,2}[-.)\s]\d{3,4}[-.\s]\d{4}",
    "주민등록번호": r"\d{6}\s?[-–]\s?[1-4][\d*]{6}",
    "이메일": r"[\w.+-]+@[\w-]{3,}",  # OCR 이 '.' 을 자주 빠뜨려서(gmailcom) 점은 요구하지 않음
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
    ocr_w = min(settings.ocr_width, info.width)
    scale = info.width / ocr_w
    total = max(1, int(info.duration / step))

    hits = []   # (t, box, text)
    started = time.time()
    for i, (t, items) in enumerate(_ocr_frames(reader, media.sample_frames(video, step, ocr_w))):
        for (x0, y0, x1, y1), _, text, conf in items:
            if conf >= 0.2 and len(text.strip()) >= 2:
                hits.append((t, (x0 * scale, y0 * scale, x1 * scale, y1 * scale), text))
        if (i + 1) % 60 == 0:
            spent = time.time() - started
            log(f"  OCR {i + 1}/{total} 프레임, 남은 시간 약 {spent / (i + 1) * (total - i - 1):.0f}초")
    log(f"  OCR 글자 {len(hits)}개 검사 ({time.time() - started:.0f}초)")

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


def _crop(gray, box):
    x0, y0, x1, y1 = (int(v) for v in box)
    return gray[y0:y1, x0:x1].astype(np.int16)


def _unchanged(a, b) -> bool:
    """두 이미지가 같은 내용인지. 평균 대신 '뚜렷하게 바뀐 점 개수'로 봐야
    자막에서 숫자 한 글자만 바뀌거나 작은 글자가 새로 나타난 것도 잡힘."""
    return a.shape == b.shape and np.count_nonzero(np.abs(a - b) > 40) < 4


def _box_iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / (union + 1e-6)


def _ocr_frames(reader, frames):
    """프레임마다 [(상자, 상자 속 이미지, 글자, 신뢰도)].
    영상 대부분은 앞 프레임과 거의 같으므로, 화면이 그대로면 통째로 건너뛰고
    글자 상자 속이 그대로면 예전에 읽은 글자를 재사용해서 바뀐 글자만 새로 읽음."""
    prev_gray, prev = None, []
    for t, frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        g16 = gray.astype(np.int16)
        if prev_gray is not None and _unchanged(g16, prev_gray):
            yield t, prev
            continue
        prev_gray = g16

        horizontal, free = reader.detect(frame)
        items, new_boxes = [], []
        for x0, x1, y0, y1 in horizontal[0]:
            box = (max(0, x0), max(0, y0), x1, y1)
            # 예전 상자 자리를 지금 화면에서 잘라 비교 (검출 상자가 1px 흔들려도 재사용 가능)
            old = next((p for p in prev if _box_iou(p[0], box) > 0.6
                        and _unchanged(_crop(gray, p[0]), p[1])), None)
            if old:
                items.append(old)
            else:
                new_boxes.append([box[0], box[2], box[1], box[3]])
        # 상자를 하나도 안 넘기면 easyocr 가 화면 전체를 읽으므로 새 상자가 있을 때만 호출
        if new_boxes or free[0]:
            for pts, text, conf in reader.recognize(gray, horizontal_list=new_boxes, free_list=free[0]):
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                box = (max(0, min(xs)), max(0, min(ys)), max(xs), max(ys))
                items.append((box, _crop(gray, box), text, conf))
        prev = items
        yield t, items


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
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    roi = frame[y0:y1, x0:x1]
    h, w = roi.shape[:2]
    if h < 2 or w < 2:
        return
    block = max(10, min(w, h) // 3)
    small = cv2.resize(roi, (max(1, w // block), max(1, h // block)), interpolation=cv2.INTER_AREA)
    frame[y0:y1, x0:x1] = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


_FACE_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")


class FaceBlur:
    """얼굴 모자이크. 몇 프레임마다 한 번만 찾고 사이 프레임은 같은 자리를 가림."""

    def __init__(self, info, every: int = 3, width: int = 640):
        import os
        import urllib.request

        from . import ROOT
        path = os.path.join(ROOT, "models", os.path.basename(_FACE_URL))
        if not os.path.exists(path):  # 첫 사용 때 한 번 내려받음 (230KB)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            urllib.request.urlretrieve(_FACE_URL, path)
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)  # 무해한 DNN 경고 숨김
        self.scale = width / info.width
        self.size = (width, int(info.height * self.scale))
        self.det = cv2.FaceDetectorYN.create(path, "", self.size, score_threshold=0.75)
        self.every, self.n, self.boxes = every, 0, []

    def __call__(self, frame):
        if self.n % self.every == 0:
            _, faces = self.det.detect(cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA))
            self.boxes = []
            for x, y, w, h in (faces[:, :4] if faces is not None else []):
                px, py = w * 0.25, h * 0.3  # 머리카락·턱까지 넉넉히
                self.boxes.append([(x - px) / self.scale, (y - py) / self.scale,
                                   (x + w + px) / self.scale, (y + h + py) / self.scale])
        self.n += 1
        H, W = frame.shape[:2]
        for x0, y0, x1, y1 in self.boxes:
            pixelate(frame, max(0, x0), max(0, y0), min(W, x1), min(H, y1))


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
