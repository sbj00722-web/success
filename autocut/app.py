"""웹 화면:  python app.py  →  브라우저에서 http://127.0.0.1:7860"""
import os
import queue
import threading
import traceback

import gradio as gr

from autocut import Settings, run

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


ENGINES = {"자동 (OpenAI 키가 있으면 OpenAI)": "auto", "OpenAI 그림": "openai", "Claude 그림 (SVG)": "claude"}


def process(video, silence_db, min_silence, cut_fillers, cut_retakes, illustrations, max_ill,
            mode, engine, review, pii, faces, ocr_every, whisper_model):
    if not video:
        yield "영상을 먼저 올려 주세요.", None, None
        return
    s = Settings(whisper_model=whisper_model, silence_db=silence_db, min_silence=min_silence,
                 cut_fillers=cut_fillers, cut_retakes=cut_retakes, illustrations=illustrations,
                 max_illustrations=int(max_ill), illustration_mode="pip" if mode.startswith("작은") else "full",
                 image_engine=ENGINES[engine], illustration_review=review, pii_screen=pii, pii_audio=pii,
                 blur_faces=faces, ocr_fps=1.0 / ocr_every)
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
        yield "\n".join(logs[-300:]), r["video"], [r["video"], r["srt"], r["report"], *r["illustrations"]]


with gr.Blocks(title="자동 1차 편집기") as demo:
    gr.Markdown("# 🎬 유튜브 자동 1차 편집기\n무음·필러·NG 컷 → 설명 일러스트 삽입 → 개인정보 모자이크/삐- 처리")
    with gr.Row():
        with gr.Column(scale=1):
            video = gr.Video(label="원본 영상", sources=["upload"])
            with gr.Accordion("컷 편집", open=False):
                silence_db = gr.Slider(-55, -25, value=-38, step=1, label="무음 기준 (dB, 낮을수록 덜 자름)")
                min_silence = gr.Slider(0.3, 2.0, value=0.6, step=0.1, label="이 길이 이상 무음만 자르기 (초)")
                cut_fillers = gr.Checkbox(True, label="필러워드(어, 음) 자르기")
                cut_retakes = gr.Checkbox(True, label="NG(말 더듬기·다시 말하기) 자르기")
            with gr.Accordion("설명 일러스트", open=False):
                illustrations = gr.Checkbox(True, label="일러스트 넣기")
                max_ill = gr.Slider(1, 12, value=6, step=1, label="최대 장수")
                mode = gr.Radio(["전체 화면", "작은 카드(오른쪽 위)"], value="전체 화면", label="보여주는 방식")
                engine = gr.Radio(list(ENGINES), value=next(iter(ENGINES)), label="그림 그리는 AI")
                review = gr.Checkbox(True, label="그린 뒤 AI가 한 번 더 검토 (품질↑ 비용↑)")
            with gr.Accordion("기타", open=False):
                pii = gr.Checkbox(True, label="개인정보 모자이크 / 삐- 처리")
                faces = gr.Checkbox(False, label="얼굴 모자이크 (본인 얼굴도 가려져요)")
                ocr_every = gr.Slider(0.5, 3, value=1, step=0.5, label="화면 글자 검사 간격 (초, 클수록 빠르지만 잠깐 나온 글자를 놓칠 수 있음)")
                whisper_model = gr.Dropdown(["large-v3", "medium", "small"], value="large-v3", label="음성 인식 모델")
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
