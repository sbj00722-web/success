"""inbox 폴더 지켜보기: 영상을 넣으면 자동으로 편집해서 output 에 저장하고, 원본은 inbox/done 으로 옮김.
옵션은 python -m autocut 과 같음 (예: python watch_inbox.py --blur-faces)."""
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(HERE, "inbox")
DONE = os.path.join(INBOX, "done")
FAILED = os.path.join(INBOX, "failed")
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}


def ready(path) -> bool:
    """복사가 끝났는지: 크기가 2초 동안 그대로이고, 파일을 열 수 있으면 끝난 것."""
    try:
        size = os.path.getsize(path)
        time.sleep(2)
        if size == 0 or size != os.path.getsize(path):
            return False
        with open(path, "rb+"):
            return True
    except OSError:
        return False


def move(path, folder):
    os.makedirs(folder, exist_ok=True)
    name, ext = os.path.splitext(os.path.basename(path))
    dst, k = os.path.join(folder, name + ext), 1
    while os.path.exists(dst):
        k += 1
        dst = os.path.join(folder, f"{name} ({k}){ext}")
    shutil.move(path, dst)


def main():
    sys.path.insert(0, HERE)
    from autocut import run
    from autocut.__main__ import parser, settings_from

    args = parser(with_videos=False).parse_args()  # 영상은 inbox 에서 가져옴
    out = os.path.join(HERE, args.out)
    os.makedirs(INBOX, exist_ok=True)

    print(f"inbox 폴더를 지켜보는 중이에요: {INBOX}")
    print("여기에 영상을 넣으면 자동으로 편집해요. 끝내려면 이 창을 닫으세요.")
    while True:
        videos = sorted((os.path.join(INBOX, f) for f in os.listdir(INBOX)
                         if os.path.splitext(f)[1].lower() in VIDEO_EXT),
                        key=os.path.getmtime)
        for v in videos:
            if not ready(v):
                continue  # 아직 복사 중, 다음 바퀴에 다시 확인
            print(f"\n=== {os.path.basename(v)} 편집 시작 ===")
            try:
                run(v, out, settings_from(args))
                move(v, DONE)
                print(f"=== 끝! 결과는 {out} 폴더, 원본은 inbox/done 으로 옮겼어요 ===")
            except Exception:
                traceback.print_exc()
                move(v, FAILED)
                print("=== 실패해서 원본을 inbox/failed 로 옮겼어요 ===")
        time.sleep(3)


if __name__ == "__main__":
    main()
