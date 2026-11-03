"""잘라낼 구간 계산과 원본↔편집본 시간 변환."""
import bisect
import difflib
import re

import numpy as np

_STRIP = re.compile(r"[\s\.,!?…~\"'“”‘’·\-]")


def norm(s: str) -> str:
    return _STRIP.sub("", s)


# ---------------------------------------------------------------- 무음

def silence_cuts(audio: np.ndarray, sr: int, threshold_db: float, min_len: float, pad: float):
    """에너지가 threshold_db 아래인 구간 중 min_len 이상인 것을, 앞뒤 pad 만큼 남기고 자름."""
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    hop = int(sr * 0.02)
    n = len(mono) // hop
    frames = mono[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    silent = db < threshold_db

    cuts, i = [], 0
    while i < n:
        if not silent[i]:
            i += 1
            continue
        j = i
        while j < n and silent[j]:
            j += 1
        s, e = i * 0.02, j * 0.02
        if e - s >= min_len:
            # 영상 맨 앞/뒤 무음은 여유 없이 통째로 자름
            cs = s if i == 0 else s + pad
            ce = e if j == n else e - pad
            if ce - cs > 0.05:
                cuts.append((cs, ce, "무음"))
        i = j
    return cuts


# ---------------------------------------------------------------- 필러워드

def filler_cuts(segments: list, fillers: list):
    fillers = {norm(f).lower() for f in fillers}
    words = [w for seg in segments for w in seg["words"]]
    cuts = []
    for k, w in enumerate(words):
        if norm(w["word"]).lower() not in fillers:
            continue
        # Whisper 단어 경계가 겹치는 경우가 있어, 앞뒤 단어를 침범하지 않게 자름
        s = max(w["start"], words[k - 1]["end"]) if k > 0 else w["start"]
        e = min(w["end"], words[k + 1]["start"]) if k + 1 < len(words) else w["end"]
        if e - s > 0.04:
            cuts.append((s, e, f"필러 '{w['word']}'"))
    return cuts


# ---------------------------------------------------------------- 문장 일부 찾기

def locate_phrase(segment: dict, phrase: str):
    """세그먼트 안에서 phrase 가 차지하는 (시작, 끝) 시간. 못 찾으면 None."""
    target = norm(phrase)
    if not target:
        return None
    concat, owner = "", []
    for i, w in enumerate(segment["words"]):
        n = norm(w["word"])
        concat += n
        owner += [i] * len(n)
    idx, length = concat.find(target), len(target)
    if idx < 0:
        m = difflib.SequenceMatcher(None, concat, target, autojunk=False).find_longest_match(
            0, len(concat), 0, len(target))
        if m.size < max(2, 0.6 * len(target)):
            return None
        idx, length = m.a, m.size
    words = segment["words"]
    return words[owner[idx]]["start"], words[owner[idx + length - 1]]["end"]


# ---------------------------------------------------------------- 남길 구간 / 시간 변환

def merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [tuple(x) for x in out]


def keep_intervals(cuts, duration: float, fps: float, min_keep: float = 0.1):
    """잘라낼 구간들의 여집합. 오디오/영상 싱크를 위해 프레임 경계에 맞춤."""
    snap = lambda t: round(t * fps) / fps
    keeps, cur = [], 0.0
    for s, e in merge([(max(0.0, s), min(duration, e)) for s, e, *_ in cuts]):
        if s - cur >= min_keep:
            keeps.append((snap(cur), snap(s)))
        cur = max(cur, e)
    if duration - cur >= min_keep:
        keeps.append((snap(cur), snap(duration)))
    return [(s, e) for s, e in keeps if e > s]


class Timeline:
    """원본 시간 ↔ 편집본 시간"""

    def __init__(self, keeps):
        self.keeps = keeps
        self.starts = [s for s, _ in keeps]
        self.offsets, acc = [], 0.0
        for s, e in keeps:
            self.offsets.append(acc)
            acc += e - s
        self.duration = acc

    def index(self, t: float):
        i = bisect.bisect_right(self.starts, t) - 1
        return i if i >= 0 and t < self.keeps[i][1] else None

    def is_kept(self, t: float) -> bool:
        return self.index(t) is not None

    def to_new(self, t: float) -> float:
        """잘린 지점이면 그 다음 남은 구간의 시작으로 붙음"""
        i = bisect.bisect_right(self.starts, t) - 1
        if i < 0:
            return 0.0
        s, e = self.keeps[i]
        return self.offsets[i] + min(t, e) - s
