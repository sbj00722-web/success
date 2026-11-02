"""명령줄 실행:  python cli.py 영상.mp4 [-o 출력폴더] [옵션]"""
import argparse
import os

from autocut import Settings, run


def main():
    p = argparse.ArgumentParser(description="유튜브 영상 자동 1차 편집")
    p.add_argument("video")
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
    p.add_argument("--no-review", action="store_true", help="일러스트 재검토 생략 (비용 절감)")
    p.add_argument("--no-pii", action="store_true", help="개인정보 처리 끄기")
    a = p.parse_args()

    s = Settings(
        whisper_model=a.whisper_model, silence_db=a.silence_db, min_silence=a.min_silence,
        cut_silence=not a.no_silence, cut_fillers=not a.no_fillers, cut_retakes=not a.no_retakes,
        illustrations=not a.no_illustrations, max_illustrations=a.max_illustrations,
        illustration_mode=a.illustration_mode, illustration_review=not a.no_review,
        pii_screen=not a.no_pii, pii_audio=not a.no_pii,
    )
    os.makedirs(a.out, exist_ok=True)
    run(a.video, a.out, s)


if __name__ == "__main__":
    main()
