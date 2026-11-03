"""구글 드라이브 '내 드라이브/claude_success' 폴더 지켜보기.

영상을 넣으면 자동으로 편집해서 claude_success/output 에 결과물(편집본 mp4, 자막 srt, 리포트 md)을
올리고, 원본은 claude_success/done 으로 옮김.
- 구글 드라이브 PC 앱(Google Drive for desktop)이 G:\\내 드라이브 처럼 연결돼 있어야 함 (자동으로 찾음)
- 편집은 PC 안(autocut/output)에서 하고, 다 만든 결과물만 드라이브로 복사 (업로드가 덜 꼬임)
- 폴더는 .env 의 IN_DIR / OUT_DIR / GDRIVE_DIR 또는 --in / -o 로 바꿀 수 있음
옵션은 python -m autocut 과 같음 (예: python watch_inbox.py --blur-faces)."""
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
DRIVE_NAMES = ("내 드라이브", "My Drive")


def find_google_drive():
    """구글 드라이브 PC 앱이 연결한 '내 드라이브' 폴더 찾기. 못 찾으면 None."""
    given = os.environ.get("GDRIVE_DIR", "").strip()
    if given:
        return given
    homes = [f"{c}:\\" for c in "GHIJKLMNOPQRSTUVWXYZDEF"] if os.name == "nt" else []
    homes += [os.path.expanduser("~/Google Drive"), os.path.expanduser("~")]
    for home in homes:
        for name in DRIVE_NAMES:
            path = os.path.join(home, name)
            if os.path.isdir(path):
                return path
    return None


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

    p = parser(with_videos=False)  # 영상은 넣는 폴더에서 가져옴
    p.add_argument("--in", dest="in_dir", default=os.environ.get("IN_DIR"),
                   help="영상을 넣는 폴더 (기본: 구글 드라이브 '내 드라이브/claude_success')")
    p.set_defaults(out=os.environ.get("OUT_DIR"))
    args = p.parse_args()

    if args.in_dir:
        inbox = os.path.join(HERE, args.in_dir)  # 절대 경로(G:\\...)를 주면 그대로 사용
    else:
        drive = find_google_drive()
        if drive is None:
            print("구글 드라이브의 '내 드라이브' 폴더를 찾지 못했어요.")
            print("1) 구글 드라이브 PC 앱(Google Drive for desktop)을 설치하고 로그인하세요.")
            print("2) 그래도 안 되면 .env 에 GDRIVE_DIR=G:\\내 드라이브 처럼 위치를 적어 주세요.")
            input("엔터를 누르면 닫혀요...")
            return
        inbox = os.path.join(drive, "claude_success")
    out = os.path.join(HERE, args.out) if args.out else os.path.join(inbox, "output")
    work_out = os.path.join(HERE, "output")  # 편집 작업은 PC 안에서 (중간 파일이 드라이브에 안 올라가게)
    done, failed = os.path.join(inbox, "done"), os.path.join(inbox, "failed")
    for d in (inbox, out, work_out):
        os.makedirs(d, exist_ok=True)

    print(f"영상 넣는 폴더: {inbox}")
    print(f"결과물 폴더:   {out}")
    print("영상을 넣으면 자동으로 편집해요. 끝내려면 이 창을 닫으세요.")
    while True:
        videos = sorted((os.path.join(inbox, f) for f in os.listdir(inbox)
                         if os.path.splitext(f)[1].lower() in VIDEO_EXT),
                        key=os.path.getmtime)
        for v in videos:
            if not ready(v):
                continue  # 아직 복사(업로드/다운로드) 중, 다음 바퀴에 다시 확인
            print(f"\n=== {os.path.basename(v)} 편집 시작 ===")
            local = os.path.join(work_out, "_원본", os.path.basename(v))
            try:
                print("원본을 PC 로 가져오는 중...")
                os.makedirs(os.path.dirname(local), exist_ok=True)
                shutil.copy2(v, local)  # 드라이브에서 여러 번 읽지 않도록 한 번만 받아 둠
                result = run(local, work_out, settings_from(args))
                if os.path.abspath(out) != os.path.abspath(work_out):
                    print("결과물을 올리는 중...")
                    for key in ("video", "srt", "srt_original", "report"):
                        if result.get(key):
                            shutil.copy2(result[key], os.path.join(out, os.path.basename(result[key])))
                move(v, done)
                print(f"=== 끝! 결과는 {out} 폴더, 원본은 done 폴더로 옮겼어요 ===")
            except Exception:
                traceback.print_exc()
                move(v, failed)
                print("=== 실패해서 원본을 failed 폴더로 옮겼어요 ===")
            finally:
                if os.path.exists(local):
                    os.remove(local)
        time.sleep(3)


if __name__ == "__main__":
    main()
