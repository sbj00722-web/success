"""명령줄 실행:  python -m autocut 영상.mp4 [-o 출력폴더] [옵션]
옵션을 안 주면 .env 값(없으면 기본값)을 씀."""
import argparse
import os
from dataclasses import fields

from . import Settings, run


def parser(with_videos: bool = True):
    p = argparse.ArgumentParser(prog="python -m autocut", description="유튜브 영상 자동 1차 편집")
    if with_videos:
        p.add_argument("videos", nargs="+", help="영상 파일 (여러 개 가능)")
    p.add_argument("-o", "--out", default=os.environ.get("OUT_DIR") or "output")
    # dest 를 Settings 이름과 같게 두고, 준 옵션만 덮어씀 (default=None)
    p.add_argument("--whisper-model", dest="whisper_model")
    p.add_argument("--silence-db", dest="silence_db", type=float)
    p.add_argument("--min-silence", dest="min_silence", type=float)
    off = lambda flag, dest, help=None: p.add_argument(flag, dest=dest, action="store_const", const=False, help=help)
    off("--no-silence", "cut_silence")
    off("--no-fillers", "cut_fillers")
    off("--no-retakes", "cut_retakes")
    off("--no-illustrations", "illustrations")
    off("--no-review", "illustration_review", "일러스트 재검토 생략 (비용 절감)")
    off("--no-pii", "pii_screen", "개인정보 처리 끄기")
    p.add_argument("--max-illustrations", dest="max_illustrations", type=int)
    p.add_argument("--illustration-mode", dest="illustration_mode", choices=["full", "pip"])
    p.add_argument("--image-engine", dest="image_engine", choices=["auto", "openai", "claude"],
                   help="설명 그림을 그릴 AI (auto: OpenAI 키가 있으면 OpenAI)")
    p.add_argument("--blur-faces", dest="blur_faces", action="store_const", const=True, help="얼굴 모자이크")
    p.add_argument("--ocr-every", dest="ocr_every", type=float, help="화면 글자 검사 간격(초)")
    p.add_argument("--language", dest="language", help="auto(언어 자동, 기본) 또는 ko, en 등으로 고정")
    off("--no-burn-subtitles", "burn_subtitles", "영상에 자막 넣지 않기 (srt 파일만)")
    off("--no-subtitle-polish", "subtitle_polish", "AI 자막 다듬기·번역 끄기")
    return p


def settings_from(a) -> Settings:
    names = {f.name for f in fields(Settings)}
    given = {k: v for k, v in vars(a).items() if k in names and v is not None}
    if given.get("pii_screen") is False:
        given["pii_audio"] = False
    return Settings.from_env(**given)


def main():
    a = parser().parse_args()
    os.makedirs(a.out, exist_ok=True)
    for v in a.videos:
        run(v, a.out, settings_from(a))


if __name__ == "__main__":
    main()
