"""명령줄 실행:  python -m autocut 영상.mp4 [-o 출력폴더] [옵션]"""
import argparse
import os

from . import Settings, run


def parser(with_videos: bool = True):
    p = argparse.ArgumentParser(prog="python -m autocut", description="유튜브 영상 자동 1차 편집")
    if with_videos:
        p.add_argument("videos", nargs="+", help="영상 파일 (여러 개 가능)")
    p.add_argument("-o", "--out", default="output")
    p.add_argument("--whisper-model", default="large-v3")
    p.add_argument("--silence-db", type=float, default=-38.0)
    p.add_argument("--min-silence", type=float, default=0.6)
    p.add_argument("--no-silence", action="store_true")
    p.add_argument("--no-fillers", action="store_true")
    p.add_argument("--no-retakes", action="store_true")
    p.add_argument("--no-illustrations", action="store_true")
    p.add_argument("--max-illustrations", type=int, default=6)
    p.add_argument("--illustration-mode", choices=["full", "pip"], default="full")
    p.add_argument("--image-engine", choices=["auto", "openai", "claude"], default="auto",
                   help="설명 그림을 그릴 AI (auto: OpenAI 키가 있으면 OpenAI)")
    p.add_argument("--no-review", action="store_true", help="일러스트 재검토 생략 (비용 절감)")
    p.add_argument("--no-pii", action="store_true", help="개인정보 처리 끄기")
    p.add_argument("--blur-faces", action="store_true", help="얼굴 모자이크")
    p.add_argument("--ocr-every", type=float, default=1.0, help="화면 글자 검사 간격(초)")
    return p


def settings_from(a) -> Settings:
    return Settings(
        whisper_model=a.whisper_model, silence_db=a.silence_db, min_silence=a.min_silence,
        cut_silence=not a.no_silence, cut_fillers=not a.no_fillers, cut_retakes=not a.no_retakes,
        illustrations=not a.no_illustrations, max_illustrations=a.max_illustrations,
        illustration_mode=a.illustration_mode, image_engine=a.image_engine,
        illustration_review=not a.no_review, pii_screen=not a.no_pii, pii_audio=not a.no_pii,
        blur_faces=a.blur_faces, ocr_fps=1.0 / a.ocr_every,
    )


def main():
    a = parser().parse_args()
    os.makedirs(a.out, exist_ok=True)
    for v in a.videos:
        run(v, a.out, settings_from(a))


if __name__ == "__main__":
    main()
