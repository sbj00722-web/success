"""웹 화면:  python app.py  →  브라우저에서 http://127.0.0.1:7860"""
import os
import queue
import threading
import traceback

import gradio as gr

from autocut import Settings, run

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get("OUT_DIR") or "output")

ENGINES = {"자동 (OpenAI 키가 있으면 OpenAI)": "auto", "OpenAI 그림": "openai", "Claude 그림 (SVG)": "claude"}
MODES = {"전체 화면": "full", "작은 카드(오른쪽 위)": "pip"}
D = Settings.from_env()  # 화면의 처음 값은 .env 설정을 따름


def _label(table, value):
    return next(k for k, v in table.items() if v == value)


def process(video, silence_db, min_silence, cut_fillers, cut_retakes, illustrations, max_ill,
            mode, engine, review, pii, faces, ocr_every, whisper_model):
    if not video:
        yield "영상을 먼저 올려 주세요.", None, None
        return
    s = Settings.from_env(whisper_model=whisper_model, silence_db=silence_db, min_silence=min_silence,
                          cut_fillers=cut_fillers, cut_retakes=cut_retakes, illustrations=illustrations,
                          max_illustrations=int(max_ill), illustration_mode=MODES[mode],
                          image_engine=ENGINES[engine], illustration_review=review, pii_screen=pii,
                          pii_audio=pii and D.pii_audio, blur_faces=faces, ocr_every=ocr_every)
    os.makedirs(OUT_DIR, exist_ok=True)

    q, box, logs = queue.Queue(), {}, []

    def worker():
        try:
            box["result"] = run(video, OUT_DIR, s, log=q.put)
        except Exception as e:
            q.put(f"오류: {e}\n{traceback.format_exc()}")
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while (msg := q.get()) is not None:
        logs.append(msg)
        yield "\n".join(logs[-300:]), None, None

    r = box.get("result")
    if r:
        yield "\n".join(logs[-300:]), r["video"], [p for p in (r["video"], r["srt"], r.get("srt_original"), r["report"], *r["illustrations"]) if p]


with gr.Blocks(title="자동 1차 편집기") as demo:
    gr.Markdown("# 🎬 유튜브 자동 1차 편집기\n무음·필러·NG 컷 → 설명 일러스트 삽입 → 개인정보 모자이크/삐- 처리")
    with gr.Row():
        with gr.Column(scale=1):
            video = gr.Video(label="원본 영상", sources=["upload"])
            with gr.Accordion("컷 편집", open=False):
                silence_db = gr.Slider(min(-55, D.silence_db), max(-25, D.silence_db), value=D.silence_db, step=1,
                                       label="무음 기준 (dB, 낮을수록 덜 자름)")
                min_silence = gr.Slider(0.1, max(2.0, D.min_silence), value=D.min_silence, step=0.1,
                                        label="이 길이 이상 무음만 자르기 (초)")
                cut_fillers = gr.Checkbox(D.cut_fillers, label="필러워드(어, 음) 자르기")
                cut_retakes = gr.Checkbox(D.cut_retakes, label="NG(말 더듬기·다시 말하기) 자르기")
            with gr.Accordion("설명 일러스트", open=False):
                illustrations = gr.Checkbox(D.illustrations, label="일러스트 넣기")
                max_ill = gr.Slider(1, max(12, D.max_illustrations), value=D.max_illustrations, step=1, label="최대 장수")
                mode = gr.Radio(list(MODES), value=_label(MODES, D.illustration_mode), label="보여주는 방식")
                engine = gr.Radio(list(ENGINES), value=_label(ENGINES, D.image_engine), label="그림 그리는 AI")
                review = gr.Checkbox(D.illustration_review, label="그린 뒤 AI가 한 번 더 검토 (품질↑ 비용↑)")
            with gr.Accordion("기타", open=False):
                pii = gr.Checkbox(D.pii_screen, label="개인정보 모자이크 / 삐- 처리")
                faces = gr.Checkbox(D.blur_faces, label="얼굴 모자이크 (본인 얼굴도 가려져요)")
                ocr_every = gr.Slider(0.5, max(3, D.ocr_every), value=D.ocr_every, step=0.5,
                                      label="화면 글자 검사 간격 (초, 클수록 빠르지만 잠깐 나온 글자를 놓칠 수 있음)")
                whisper_model = gr.Dropdown(list(dict.fromkeys([D.whisper_model, "large-v3", "medium", "small"])),
                                            value=D.whisper_model, label="음성 인식 모델")
            btn = gr.Button("편집 시작", variant="primary")
        with gr.Column(scale=1):
            out_video = gr.Video(label="편집본")
            files = gr.File(label="결과 파일 (영상·자막·리포트·일러스트)", file_count="multiple")
            log = gr.Textbox(label="진행 상황", lines=18, max_lines=18, autoscroll=True)

    btn.click(process, [video, silence_db, min_silence, cut_fillers, cut_retakes, illustrations,
                        max_ill, mode, engine, review, pii, faces, ocr_every, whisper_model],
                [log, out_video, files])

if __name__ == "__main__":
    demo.queue().launch(inbrowser=True)
