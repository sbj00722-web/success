"""최종 영상 만들기: 컷 적용 + 모자이크 + 설명 일러스트 + 오디오 이어붙이기."""
import bisect

import cv2
import numpy as np

from . import media
from .privacy import FaceBlur, pixelate

FADE = 0.3  # 일러스트 페이드 인/아웃(초)


def cut_audio(audio: np.ndarray, sr: int, keeps):
    """남길 구간들을 이어붙임. 이음새마다 8ms 페이드로 '틱' 소리 방지."""
    fade = int(sr * 0.008)
    ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    parts = []
    for s, e in keeps:
        a, b = int(round(s * sr)), int(round(e * sr))
        chunk = audio[a:b].copy()
        if len(chunk) < b - a:  # 오디오가 영상보다 짧은 파일: 모자란 만큼 무음으로 채워 싱크 유지
            chunk = np.concatenate([chunk, np.zeros((b - a - len(chunk), audio.shape[1]), audio.dtype)])
        if len(chunk) > 2 * fade:
            chunk[:fade] *= ramp
            chunk[-fade:] *= ramp[::-1]
        parts.append(chunk)
    return np.concatenate(parts) if parts else audio[:0]


def _load_overlay(png: str, info, mode: str):
    img = cv2.imread(png, cv2.IMREAD_COLOR)
    if mode == "pip":
        w = int(info.width * 0.4)
        h = int(img.shape[0] * w / img.shape[1])
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
        cv2.rectangle(img, (0, 0), (w - 1, h - 1), (43, 43, 43), max(3, w // 160))
        return img
    return cv2.resize(img, (info.width, info.height), interpolation=cv2.INTER_AREA)


def render(video, info, timeline, boxes, overlays, audio_wav, out_path, settings, log):
    """
    boxes: 원본 시간 기준 [(t0, t1, x0, y0, x1, y1, kind)]
    overlays: 편집본 시간 기준 [{"start", "end", "png"}]
    """
    for ov in overlays:
        ov["img"] = _load_overlay(ov["png"], info, settings.illustration_mode)
    margin = int(info.width * 0.03)
    faces = FaceBlur(info) if settings.blur_faces else None

    box_starts = [b[0] for b in boxes]
    total = int(timeline.duration * info.fps)
    codec = media.pick_codec(settings)
    log(f"  인코딩: {codec}" + (" (그래픽카드 사용)" if codec == "h264_nvenc" else ""))
    enc = media.open_encoder(out_path, info, audio_wav, settings)
    written = 0
    try:
        for i, frame in enumerate(media.iter_frames(video, info)):
            t = i / info.fps
            if not timeline.is_kept(t):
                continue
            frame = frame.copy()

            # 모자이크 (원본 시간 기준)
            for b in boxes[: bisect.bisect_right(box_starts, t)]:
                if b[0] <= t <= b[1]:
                    pixelate(frame, *b[2:6])
            if faces:
                faces(frame)

            # 설명 일러스트 (편집본 시간 기준)
            nt = written / info.fps
            for ov in overlays:
                if ov["start"] <= nt < ov["end"]:
                    a = min(1.0, (nt - ov["start"]) / FADE, (ov["end"] - nt) / FADE)
                    img = ov["img"]
                    if settings.illustration_mode == "pip":
                        h, w = img.shape[:2]
                        y0, x0 = margin, info.width - w - margin
                        dst = frame[y0:y0 + h, x0:x0 + w]
                        frame[y0:y0 + h, x0:x0 + w] = cv2.addWeighted(img, a, dst, 1 - a, 0)
                    else:
                        frame = cv2.addWeighted(img, a, frame, 1 - a, 0)

            enc.stdin.write(frame.tobytes())
            written += 1
            if written % int(info.fps * 30) == 0:
                log(f"  렌더링 {written / max(1, total):.0%}")
    finally:
        enc.stdin.close()
        enc.wait()
    if enc.returncode:
        raise RuntimeError("ffmpeg 인코딩 실패")
    log("  렌더링 100%")
