"""전체 흐름: 영상 → 대본 → 컷 계획 → 일러스트 → 개인정보 → 최종 렌더링."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from . import cuts as C
from . import illustrate, llm, media, planner, privacy, render, subtitles, transcribe
from .config import Settings


def _fmt(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def run(video: str, out_dir: str, settings: Settings = None, log=print) -> dict:
    settings = settings or Settings.from_env()
    t_start = time.time()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log("ANTHROPIC_API_KEY 가 없어서 Claude 단계(NG 컷·설명 그림·말한 개인정보)는 건너뜁니다.")
        settings = replace(settings, cut_retakes=False, illustrations=False,
                           pii_audio=False, pii_llm_check=False)
    stem = os.path.splitext(os.path.basename(video))[0]
    work = os.path.join(out_dir, f"{stem}_work")
    os.makedirs(work, exist_ok=True)

    # 1. 영상 정보, 오디오
    info = media.probe(video)
    log(f"① 영상: {info.width}x{info.height}, {info.fps:.2f}fps, {_fmt(info.duration)}")
    if not info.has_audio:
        raise RuntimeError("오디오가 없는 영상은 처리할 수 없습니다.")
    a16, a48 = os.path.join(work, "audio16k.wav"), os.path.join(work, "audio48k.wav")
    media.extract_audio(video, a16, 16000, 1)
    media.extract_audio(video, a48, 48000, 2)

    # 2. 대본
    log("② 음성 인식 중...")
    segments = transcribe.transcribe(a16, os.path.join(work, "transcript.json"),
                                     settings.whisper_model, settings.language, log,
                                     settings.whisper_device, settings.languages)
    seg_by_id = {s["id"]: s for s in segments}

    # 3. 1차 컷: 무음 + 필러
    all_cuts = []
    audio16, sr16 = media.read_wav(a16)
    if settings.cut_silence:
        # 자른 자리 앞뒤로 절반씩 남겨서 합치면 keep_silence 만큼의 쉼이 됨
        sc = C.silence_cuts(audio16, sr16, settings.silence_db, settings.min_silence, settings.keep_silence / 2)
        log(f"③ 무음 구간 {len(sc)}개 ({sum(e - s for s, e, _ in sc):.1f}초)")
        all_cuts += sc
    if settings.cut_fillers:
        fc = C.filler_cuts(segments, settings.filler_words)
        log(f"   필러워드 {len(fc)}개")
        all_cuts += fc

    # 4. Claude 편집 계획
    plan = {"retake_cuts": [], "illustrations": [], "spoken_pii": [], "summary": ""}
    if segments and (settings.cut_retakes or settings.illustrations or settings.pii_audio):
        log("④ Claude 가 대본을 읽고 편집 계획을 세우는 중...")
        try:
            plan = planner.plan(segments, settings)
            with open(os.path.join(work, "plan.json"), "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=1)
            log(f"   주제: {plan['summary']}")
        except llm.LLMError as e:
            log(f"   ⚠ {e} → NG 컷·설명 그림·말한 개인정보는 건너뜁니다.")
            settings = replace(settings, pii_llm_check=False)

    if settings.cut_retakes:
        for item in plan["retake_cuts"]:
            seg = seg_by_id.get(item["segment_id"])
            span = seg and C.locate_phrase(seg, item["phrase"])
            if span:
                all_cuts.append((span[0], span[1], f"NG: {item['reason']}"))
                log(f"   NG 컷 [{_fmt(span[0])}] \"{item['phrase']}\" - {item['reason']}")

    pii_spans = []
    if settings.pii_audio:
        for item in plan["spoken_pii"]:
            seg = seg_by_id.get(item["segment_id"])
            span = seg and C.locate_phrase(seg, item["phrase"])
            if span:
                pii_spans.append(span)
                log(f"   말한 개인정보 [{_fmt(span[0])}] {item['reason']} → 삐- 처리")

    keeps = C.keep_intervals(all_cuts, info.duration, info.fps)
    tl = C.Timeline(keeps)
    log(f"   길이 {_fmt(info.duration)} → {_fmt(tl.duration)} "
        f"({(1 - tl.duration / info.duration):.0%} 단축)")

    # 5. 설명 일러스트
    overlays = []
    if settings.illustrations and plan["illustrations"]:
        who = "OpenAI" if illustrate.engine(settings) == "openai" else "Claude"
        log(f"⑤ 설명 일러스트 {len(plan['illustrations'])}장 그리는 중 ({who})...")
        if settings.illustration_mode == "pip":
            cw, ch = 1600, 1200
        else:
            cw, ch = (1920, 1080) if info.width >= info.height else (1080, 1920)

        def job(k_item):
            k, item = k_item
            png = os.path.join(work, f"illust_{k + 1:02d}.png")
            try:
                svg = illustrate.make(item, cw, ch, png, settings, log)
                if svg:
                    with open(png[:-4] + ".svg", "w", encoding="utf-8") as f:
                        f.write(svg)
                log(f"   ✔ {k + 1}. {item['concept']}")
                return item, png
            except Exception as e:
                log(f"   ✘ {k + 1}. {item['concept']} 실패: {e}")
                return item, None

        with ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(job, enumerate(plan["illustrations"])))

        last_end = -1.0
        for item, png in sorted(((i, p) for i, p in results if p),
                                key=lambda r: seg_by_id.get(r[0]["start_segment_id"], {"start": 0})["start"]):
            s_seg, e_seg = seg_by_id.get(item["start_segment_id"]), seg_by_id.get(item["end_segment_id"])
            if not s_seg:
                continue
            start = tl.to_new(s_seg["start"])
            end = tl.to_new((e_seg or s_seg)["end"])
            end = min(max(end, start + 3.0), start + 8.0, tl.duration)
            start = max(start, last_end + 0.5)
            if end - start < 2.0:
                continue
            overlays.append({"start": start, "end": end, "png": png, "concept": item["concept"]})
            last_end = end

    # 6. 화면 속 개인정보
    boxes = []
    if settings.pii_screen:
        # 같은 영상을 같은 설정으로 다시 돌리면 OCR 결과를 재사용 (가장 오래 걸리는 단계)
        cache = os.path.join(work, "screen_pii.json")
        key = [settings.ocr_every, settings.ocr_width, settings.pii_llm_check]
        cached = json.load(open(cache, encoding="utf-8")) if os.path.exists(cache) else {}
        if cached.get("key") == key:
            boxes = [tuple(b) for b in cached["boxes"]]
            log(f"⑥ 화면 속 개인정보: 지난번 OCR 결과 재사용, 모자이크 {len(boxes)}곳")
        else:
            log("⑥ 화면 속 개인정보 찾는 중 (OCR)...")
            boxes = privacy.screen_pii(video, info, settings, log)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump({"key": key, "boxes": boxes}, f, ensure_ascii=False)
            log(f"   모자이크 {len(boxes)}곳")

    # 7. 자막 (편집본 시간 기준)
    log("⑦ 자막 만드는 중...")
    cues = subtitles.build_cues(segments, tl, pii_spans, settings)
    sub_engine = subtitles.polish(cues, work, settings, log)
    foreign = sum(c["lang"] != "ko" for c in cues)
    log(f"   자막 {len(cues)}줄 (외국어 {foreign}줄), 다듬기: {sub_engine}"
        + (", 영상에 직접 넣음" if settings.burn_subtitles else ""))
    srt_path = os.path.join(out_dir, f"{stem}_편집본.srt")
    subtitles.write_srt(srt_path, cues, "ko")
    srt_orig = None
    if foreign:
        srt_orig = os.path.join(out_dir, f"{stem}_원어자막.srt")
        subtitles.write_srt(srt_orig, cues, "text")

    # 8. 오디오 + 렌더링
    log("⑧ 최종 영상 만드는 중...")
    audio48, sr48 = media.read_wav(a48)
    if pii_spans:
        audio48 = privacy.beep(audio48, sr48, pii_spans)
    cut_wav = os.path.join(work, "audio_edited.wav")
    media.write_wav(cut_wav, render.cut_audio(audio48, sr48, keeps), sr48)
    out_video = os.path.join(out_dir, f"{stem}_편집본.mp4")
    burner = subtitles.Burner(cues, info, settings) if settings.burn_subtitles and cues else None
    render.render(video, info, tl, boxes, overlays, cut_wav, out_video, settings, log, burner)

    # 9. 편집 리포트
    report_path = os.path.join(out_dir, f"{stem}_편집리포트.md")
    sub_info = {"count": len(cues), "foreign": foreign, "engine": sub_engine,
                "burned": burner is not None,
                "langs": sorted({c["lang"] for c in cues})}
    _write_report(report_path, video, info, tl, all_cuts, overlays, boxes, pii_spans, plan, sub_info)

    log(f"완료! ({time.time() - t_start:.0f}초) → {out_video}")
    return {"video": out_video, "srt": srt_path, "srt_original": srt_orig, "report": report_path,
            "illustrations": [o["png"] for o in overlays]}


def _write_report(path, video, info, tl, all_cuts, overlays, boxes, pii_spans, plan, sub_info):
    L = [f"# 편집 리포트: {os.path.basename(video)}", "",
         f"- 원본 {_fmt(info.duration)} → 편집본 {_fmt(tl.duration)}",
         f"- 주제: {plan.get('summary', '')}", "",
         "## 잘라낸 구간 (원본 기준)", "", "| 시작 | 끝 | 길이 | 이유 |", "|---|---|---|---|"]
    for s, e, why in sorted(all_cuts):
        L.append(f"| {_fmt(s)} | {_fmt(e)} | {e - s:.2f}s | {why} |")
    L += ["", "## 자막", "",
          f"- {sub_info['count']}줄, 언어: {', '.join(sub_info['langs']) or '-'}"
          + (f" (외국어 {sub_info['foreign']}줄은 한국어로 번역)" if sub_info["foreign"] else ""),
          f"- 다듬기·번역: {sub_info['engine']}",
          f"- 영상에 직접 넣음: {'예' if sub_info['burned'] else '아니요 (srt 파일만)'}"]
    L += ["", "## 설명 일러스트 (편집본 기준)", ""]
    L += [f"- {_fmt(o['start'])} ~ {_fmt(o['end'])}: {o['concept']} (`{os.path.basename(o['png'])}`)"
          for o in overlays] or ["- 없음"]
    L += ["", "## 개인정보 처리", ""]
    L += [f"- 화면 모자이크 {_fmt(b[0])} ~ {_fmt(b[1])}: {b[6]}" for b in boxes]
    L += [f"- 음성 삐- 처리 {_fmt(s)} ~ {_fmt(e)} (원본 기준)" for s, e in pii_spans]
    if not boxes and not pii_spans:
        L.append("- 발견되지 않음")
    L += ["", "> 자동 편집 결과입니다. 업로드 전에 모자이크·컷 위치를 꼭 한 번 확인하세요."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
