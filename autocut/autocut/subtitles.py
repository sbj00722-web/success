"""자막: 대본 → 읽기 좋은 자막 줄 나누기 → AI 다듬기·번역 → srt 저장 / 영상에 직접 넣기.

- 시간은 편집본 기준 (컷 반영 후).
- 다듬기·번역은 Claude → OpenAI 순으로 시도, 둘 다 안 되면 PC 안의 번역 모델(NLLB)로 번역만 함.
- 한국어가 아닌 말은 한국어 번역을 크게, 원래 말을 그 위에 작게 넣음."""
import bisect
import hashlib
import json
import os
import re

import numpy as np

from . import llm

_SENT_END = re.compile(r"[.?!。？！]$")
_COMMA_END = re.compile(r"[,，、]$")

# NLLB 언어 코드
_NLLB = {"en": "eng_Latn", "ja": "jpn_Jpan", "zh": "zho_Hans", "es": "spa_Latn", "fr": "fra_Latn",
         "de": "deu_Latn", "ar": "arb_Arab", "vi": "vie_Latn", "th": "tha_Thai", "ru": "rus_Cyrl",
         "id": "ind_Latn", "pt": "por_Latn", "it": "ita_Latn", "tr": "tur_Latn", "hi": "hin_Deva"}


# ---------------------------------------------------------------- 1. 줄 나누기

def build_cues(segments, tl, pii_spans, settings):
    """[{start, end, lang, text}] (편집본 시간). 문장 끝·쉼·길이 기준으로 끊음."""
    def is_pii(w):
        mid = (w["start"] + w["end"]) / 2
        return any(s <= mid <= e for s, e in pii_spans)

    def kept(w):  # 단어 일부라도 편집본에 남으면 자막에 둠 (단어 앞 짧은 무음이 잘린 경우)
        dur = max(0.01, w["end"] - w["start"])
        over = sum(max(0.0, min(e, w["end"]) - max(s, w["start"])) for s, e in tl.keeps)
        return over >= min(0.1, dur * 0.4)

    words = []
    for seg in segments:
        for w in seg["words"]:
            if kept(w):
                words.append({"start": tl.to_new(w["start"]), "end": tl.to_new(w["end"]),
                              "word": "***" if is_pii(w) else w["word"], "lang": seg.get("lang", "ko")})

    # 1) 문장 단위로 묶기 (번역도 문장 단위): 언어가 바뀌거나, 1.5초 넘게 쉬거나, 문장이 끝나면 새 문장
    sents, cur = [], []
    for w in words:
        if cur and (w["lang"] != cur[-1]["lang"] or w["start"] - cur[-1]["end"] > 1.5
                    or _SENT_END.search(cur[-1]["word"])):
            sents.append(cur)
            cur = []
        cur.append(w)
    if cur:
        sents.append(cur)

    # 2) 화면용으로 나누기: 0.6초 넘게 쉰 곳은 꼭 끊고, 긴 것은 쉼표·접속사 자리에서 길이가 비슷하게
    cues = []
    for sid, sent in enumerate(sents):
        lang = sent[0]["lang"]
        limit = settings.subtitle_max_chars if lang == "ko" else settings.subtitle_max_chars * 3
        runs = [[sent[0]]]
        for w in sent[1:]:
            if w["start"] - runs[-1][-1]["end"] > 0.6:
                runs.append([])
            runs[-1].append(w)
        for run in runs:
            for part in _split(run, limit, 6.0):
                cues.append({"start": part[0]["start"], "end": part[-1]["end"], "lang": lang,
                             "text": " ".join(w["word"] for w in part), "sent": sid})

    # 너무 짧게 깜빡이지 않도록 시간 다듬기
    for k, c in enumerate(cues):
        nxt = cues[k + 1]["start"] if k + 1 < len(cues) else tl.duration
        end = max(c["end"] + 0.25, c["start"] + 1.0)  # 말이 끝나도 0.25초 더, 최소 1초
        if nxt - end < 0.3:
            end = nxt  # 다음 자막과 틈이 아주 짧으면 붙여서 깜빡임 방지
        c["end"] = round(min(end, nxt - 0.02, tl.duration), 3)
        c["start"] = round(c["start"], 3)
    return [c for c in cues if c["end"] - c["start"] >= 0.2 and c["text"].strip()]


_JOIN_BEFORE = {"but", "and", "so", "because", "since", "which", "when", "if", "or", "that", "then",
                "그리고", "그래서", "그런데", "근데", "하지만", "그러니까", "왜냐하면"}
_KO_CLAUSE_END = re.compile(r"(고|서|데|지만|면|니까|는데|도|며)[,]?$")


def _length(ws):
    return sum(len(w["word"]) for w in ws) + len(ws) - 1


def _split(ws, limit, max_dur):
    """단어 목록을 limit 글자 / max_dur 초 안으로 나눔. 가장 자연스러운 끊는 자리를 골라 반씩."""
    if len(ws) < 2 or (_length(ws) <= limit and ws[-1]["end"] - ws[0]["start"] <= max_dur):
        return [ws]
    total, best = _length(ws), None
    for k in range(1, len(ws)):
        left = _length(ws[:k])
        cost = abs(left - (total - left - 1)) / total  # 0 이면 정확히 반
        prev, nxt = ws[k - 1]["word"], ws[k]["word"]
        if _COMMA_END.search(prev) or _SENT_END.search(prev):
            cost -= 0.35
        elif nxt.lower().strip(",") in _JOIN_BEFORE or _KO_CLAUSE_END.search(prev):
            cost -= 0.25
        if k == 1 or k == len(ws) - 1:
            cost += 0.5  # 한 단어만 따로 떨어지지 않게
        cost += min(0.3, max(0.0, ws[k]["start"] - ws[k - 1]["end"])) * -1  # 잠깐 쉰 자리
        if best is None or cost < best[0]:
            best = (cost, k)
    k = best[1]
    return _split(ws[:k], limit, max_dur) + _split(ws[k:], limit, max_dur)


# ---------------------------------------------------------------- 2. 다듬기 + 번역

POLISH = """당신은 유튜브 자막 편집자입니다. 음성 인식으로 만든 자막 줄 목록을 받습니다.
각 줄마다:
- text: 원래 말한 언어 그대로, 음성 인식 오류(잘못 들은 단어, 띄어쓰기, 맞춤법, 문장부호)를 앞뒤 맥락으로 고침.
  뜻을 바꾸거나 말하지 않은 내용을 더하지 말 것. "um", "uh", "어", "음" 같은 군말은 지움.
- ko: 한국어 자막. 한국어 줄이면 고친 text 와 같게. 다른 언어면 말투(반말/존댓말, 분위기)를 살린
  자연스럽고 짧은 한국어 구어체 번역.
- 한국어 자막 관례대로 문장 끝 마침표는 붙이지 않음 (물음표·느낌표는 둠).
- "***" 는 가린 개인정보이므로 그대로 둠.
- 같은 sentence 번호의 줄들은 한 문장이 화면 때문에 나뉜 것. 문장 전체를 자연스럽게 번역한 뒤
  줄 순서대로 나눠 담을 것 (각 줄은 그 시간에 들리는 말과 최대한 맞게).
- 말 더듬기("they, they, they")·같은 말 되풀이는 한 번으로 정리.
- 줄을 합치거나 나누지 말고, 받은 id 를 모두 그대로 돌려줄 것."""

SCHEMA = {
    "type": "object",
    "properties": {"cues": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "text": {"type": "string"}, "ko": {"type": "string"}},
        "required": ["id", "text", "ko"], "additionalProperties": False}}},
    "required": ["cues"], "additionalProperties": False,
}


def polish(cues, work, settings, log):
    """각 cue 에 text(고침), ko(한국어) 를 채움. 쓴 방법 이름을 돌려줌."""
    for c in cues:
        c.setdefault("orig", c["text"])
        c["ko"] = c["text"] if c["lang"] == "ko" else ""
    if not cues:
        return "없음"
    cache = os.path.join(work, "subtitles.json")
    key = hashlib.sha1(json.dumps([[c["lang"], c["orig"]] for c in cues], ensure_ascii=False)
                       .encode()).hexdigest()
    old = json.load(open(cache, encoding="utf-8")) if os.path.exists(cache) else {}
    if old.get("key") != key:
        old = {}
    if old.get("engine") in ("Claude", "OpenAI"):
        _apply(cues, old["cues"])
        log(f"   지난번 다듬은 자막 재사용 ({old['engine']})")
        return old["engine"]

    engine = None
    if settings.subtitle_polish:
        try:
            got = []
            for i in range(0, len(cues), 120):  # 긴 영상은 나눠서
                part = [{"id": k, "sentence": c.get("sent"), "lang": c["lang"], "text": c["orig"]}
                        for k, c in enumerate(cues[i:i + 120], start=i)]
                res, engine = llm.ask_json_any(settings, POLISH, json.dumps(part, ensure_ascii=False), SCHEMA)
                got += res["cues"]
            _apply(cues, got)
        except llm.LLMError as e:
            log(f"   ⚠ 자막 AI 다듬기 못 함: {e}")
            engine = None

    if engine is None:
        if old.get("engine") == "PC 번역":
            _apply(cues, old["cues"])
            engine = "PC 번역"
        else:
            foreign = [c for c in cues if c["lang"] != "ko" and c["lang"] in _NLLB]
            if foreign and settings.local_translate:
                log(f"   PC 번역 모델로 한국어 번역 중 ({len(foreign)}줄)...")
                try:
                    _local_translate(foreign, settings.local_translate_model, log,
                                     settings.subtitle_max_chars)
                    engine = "PC 번역"
                except Exception as e:  # 모델 다운로드 실패 등: 번역 없이 원어 자막만
                    log(f"   ⚠ PC 번역 실패: {e}")
            first = set()
            for c in cues:
                c["text"] = _tidy(c["text"], ko=c["lang"] == "ko")
                if c["lang"] != "ko" and c.get("sent") not in first:  # 문장 첫 글자는 대문자
                    c["text"] = c["text"][:1].upper() + c["text"][1:]
                first.add(c.get("sent"))
                c["ko"] = _tidy(c["ko"], ko=True)
            engine = engine or "다듬기 없음"
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"key": key, "engine": engine,
                   "cues": [{"id": k, "text": c["text"], "ko": c["ko"]} for k, c in enumerate(cues)]},
                  f, ensure_ascii=False, indent=1)
    return engine


def _apply(cues, items):
    for it in items:
        k = it.get("id")
        if isinstance(k, int) and 0 <= k < len(cues):
            if it.get("text", "").strip():
                cues[k]["text"] = it["text"].strip()
            if it.get("ko", "").strip():
                cues[k]["ko"] = it["ko"].strip()
    for c in cues:
        c["ko"] = _tidy(c["ko"] or (c["text"] if c["lang"] == "ko" else ""), ko=True)


_FILLER = re.compile(r"(?i)(^|\s)(um+|uh+|uhm|erm)[,.]?(?=\s|$)")


_KEEP_REPEAT = {"no", "yes", "yeah", "okay", "ok", "oh", "아니", "네", "예"}


def _dedupe(s: str) -> str:
    """말 더듬기 정리: "they, they, they tried to, tried to" → "they tried to" ("no, no" 같은 건 두 번까지)."""
    for n in (3, 2):  # 여러 단어 반복 ("tried to, tried to")
        pat = re.compile(r"(?i)\b(\w+(?:\s+\w+){%d}),?\s+\1\b" % (n - 1))
        while pat.search(s):
            s = pat.sub(r"\1", s)

    def one(m):
        w = m.group(1)
        return f"{w}, {w.lower()}" if w.lower() in _KEEP_REPEAT else w
    return re.sub(r"(?i)\b(\w+)(?:,?\s+\1\b)+", one, s)


def _tidy(s: str, ko: bool = False) -> str:
    s = _FILLER.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.?!%])", r"\1", s)
    if not ko:
        s = _dedupe(s)
        s = re.sub(r",\s*,", ",", s).strip(" ,")
    if ko:
        s = re.sub(r"(?<![.])\.$", "", s)  # 마침표 없애기 (말줄임표는 둠)
    return s


def _local_translate(cues, model_name, log, max_chars=28):
    """문장 전체를 번역한 뒤, 그 문장이 나뉜 자막 줄들에 길이 비율대로 나눠 담음."""
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    cuda = torch.cuda.is_available()
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(
        model_name, dtype=torch.float16 if cuda else torch.float32)
    model = (model.cuda() if cuda else model).eval()
    ko_id = tok.convert_tokens_to_ids("kor_Hang")
    # 번역 단위: 같은 문장 안에서, 쉼표·문장 끝에서 끊되 너무 짧은 조각(50자 미만)은 다음 줄과 합침
    units = []
    for c in cues:
        u = units[-1] if units else None
        if (u and u[0]["sent"] == c.get("sent") and u[0]["lang"] == c["lang"] and not u[-1].get("_close")):
            u.append(c)
        else:
            units.append([c])
            u = units[-1]
        n = sum(len(x["text"]) for x in u)
        if _SENT_END.search(c["text"]) or (_COMMA_END.search(c["text"]) and n >= 50) or n >= 140:
            c["_close"] = True
    try:
        by_lang = {}
        for group in units:
            for c in group:
                c.pop("_close", None)
            by_lang.setdefault(group[0]["lang"], []).append(group)
        for lang, groups in by_lang.items():
            tok.src_lang = _NLLB[lang]
            for i in range(0, len(groups), 12):
                batch = groups[i:i + 12]
                src = [_tidy(" ".join(c["text"] for c in g)) for g in batch]
                enc = tok(src, return_tensors="pt", padding=True).to(model.device)
                with torch.no_grad():
                    out = model.generate(**enc, forced_bos_token_id=ko_id, num_beams=5,
                                         max_new_tokens=256)
                for g, t in zip(batch, tok.batch_decode(out, skip_special_tokens=True)):
                    t = _dedupe(t)  # 번역 모델이 "괜찮아, 괜찮아" 처럼 되풀이하는 버릇
                    if len(t) <= max_chars * 2:
                        # 한국어는 어순이 달라 쪼개면 뜻이 꼬임 → 문장 번역을 그 문장 내내 보여 줌
                        for c in g:
                            c["ko"] = t
                    else:  # 너무 긴 문장만 비율대로 나눔
                        for c, piece in zip(g, _distribute(t, [len(c["text"]) for c in g])):
                            c["ko"] = piece
    finally:
        del model
        if cuda:
            torch.cuda.empty_cache()


def _distribute(text, weights):
    """번역문을 weights 비율대로 단어 경계에서 나눔 (빈 조각은 앞 조각과 같은 문장으로 둠)."""
    words = text.split()
    if len(weights) == 1 or not words:
        return [text] + [""] * (len(weights) - 1)
    total, out, k = sum(weights), [], 0
    acc = 0
    for i, w in enumerate(weights):
        acc += w
        if i == len(weights) - 1:
            out.append(" ".join(words[k:]))
            break
        target = acc / total * len(text)
        j, pos = k, len(" ".join(words[:k]))
        while j < len(words) - (len(weights) - 1 - i) and pos + len(words[j]) / 2 < target:
            pos += len(words[j]) + 1
            j += 1
        j = max(j, k + 1) if k < len(words) - (len(weights) - 1 - i) else j
        out.append(" ".join(words[k:j]))
        k = j
    return out


# ---------------------------------------------------------------- 3. srt

def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(path, cues, field="ko"):
    items = []  # 이어지는 줄에 같은 문장이면 하나로 합침
    for c in cues:
        text = c.get(field) or ""
        if not text:
            continue
        if items and items[-1][2] == text and c["start"] - items[-1][1] < 0.5:
            items[-1][1] = c["end"]
        else:
            items.append([c["start"], c["end"], text])
    lines = []
    for n, (s, e, text) in enumerate(items, start=1):
        lines += [str(n), f"{_srt_time(s)} --> {_srt_time(e)}", text, ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------- 4. 영상에 직접 넣기

def _font_path(name: str) -> str:
    for p in (name, os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)):
        if os.path.exists(p):
            return p
    return "arial.ttf"


class Burner:
    """프레임에 자막을 그림. 자막마다 그림을 한 번만 만들어 두고 섞기만 함."""

    def __init__(self, cues, info, settings):
        self.cues = [c for c in cues if c.get("ko") or c.get("text")]
        self.starts = [c["start"] for c in self.cues]
        self.info, self.settings = info, settings
        self.size = max(18, int(min(info.width, info.height) * settings.subtitle_size))
        self.font = _font_path(settings.subtitle_font)
        self.cache = {}

    def __call__(self, frame, t):
        i = bisect.bisect_right(self.starts, t) - 1
        if i < 0 or t >= self.cues[i]["end"]:
            return
        if i not in self.cache:
            self.cache = {i: self._draw(self.cues[i])}  # 지난 자막 그림은 버림 (메모리)
        x0, y0, rgb, alpha = self.cache[i]
        h, w = alpha.shape[:2]
        roi = frame[y0:y0 + h, x0:x0 + w].astype(np.float32)
        frame[y0:y0 + h, x0:x0 + w] = (roi * (1 - alpha) + rgb).astype(np.uint8)

    def _draw(self, cue):
        from PIL import Image, ImageDraw, ImageFont
        W, H = self.info.width, self.info.height
        max_w = int(W * 0.88)
        blocks = []  # (줄들, 폰트, 색)
        main = cue.get("ko") or cue["text"]
        show_orig = self.settings.subtitle_show_original and cue["lang"] != "ko" and cue.get("ko")
        if show_orig:
            f2 = ImageFont.truetype(self.font, int(self.size * 0.62))
            blocks.append((_wrap(cue["text"], f2, max_w), f2, (235, 235, 235)))
        f1 = ImageFont.truetype(self.font, self.size)
        lines = _wrap(main, f1, max_w)
        while len(lines) > 2 and f1.size > self.size * 0.7:  # 3줄 넘으면 조금 작게
            f1 = ImageFont.truetype(self.font, int(f1.size * 0.9))
            lines = _wrap(main, f1, max_w)
        blocks.append((lines, f1, (255, 255, 255)))

        stroke = max(2, int(self.size * 0.09))
        gap = int(self.size * 0.18)
        heights = [f.getbbox("가Ag")[3] + stroke * 2 for _, f, _ in blocks]
        total_h = sum(h * len(ls) + gap * (len(ls) - 1) for (ls, _, _), h in zip(blocks, heights))
        total_h += gap * (len(blocks) - 1)
        img_w = min(W, max(int(f.getlength(l)) for ls, f, _ in blocks for l in ls) + stroke * 4)
        img = Image.new("RGBA", (img_w, total_h + stroke * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y = stroke
        for (ls, f, color), h in zip(blocks, heights):
            for line in ls:
                d.text((img_w / 2, y), line, font=f, fill=color + (255,), anchor="ma",
                       stroke_width=stroke if f is f1 else max(2, stroke * 2 // 3),
                       stroke_fill=(0, 0, 0, 255))
                y += h + gap
        arr = np.asarray(img).astype(np.float32)
        alpha = arr[:, :, 3:4] / 255.0
        rgb = arr[:, :, 2::-1] * alpha  # RGBA → BGR (OpenCV 프레임 순서), 미리 곱해 둠
        x0 = (W - img_w) // 2
        y0 = max(0, H - int(H * self.settings.subtitle_bottom) - img.height)
        return x0, y0, rgb, alpha


def _wrap(text, font, max_w):
    """폭에 맞게 줄바꿈. 두 줄이면 위아래 길이를 비슷하게."""
    words = text.split()
    if not words or font.getlength(text) <= max_w:
        return [text]
    best = None
    for k in range(1, len(words)):  # 두 줄로 나눌 수 있으면 가장 균형 잡힌 곳에서
        a, b = " ".join(words[:k]), " ".join(words[k:])
        wmax = max(font.getlength(a), font.getlength(b))
        if wmax <= max_w and (best is None or wmax < best[0]):
            best = (wmax, [a, b])
    if best:
        return best[1]
    lines, cur = [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if cur and font.getlength(t) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = t
    return lines + [cur]
