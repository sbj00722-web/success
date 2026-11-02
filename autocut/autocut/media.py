"""ffmpeg 호출 도우미: 경로 찾기, 영상 정보, 오디오 추출, 프레임 읽기/쓰기."""
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass

import numpy as np

_NTSC = {"23.98": "24000/1001", "23.976": "24000/1001", "29.97": "30000/1001", "59.94": "60000/1001"}


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args, **kw):
    return subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
                          check=True, **kw)


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    fps_str: str   # ffmpeg 에 넘길 정확한 표기 (예: 30000/1001)
    duration: float
    has_audio: bool


def probe(path: str) -> VideoInfo:
    # ffprobe 없이 `ffmpeg -i` 의 stderr 를 파싱 (imageio-ffmpeg 에는 ffprobe 가 없음)
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    err = p.stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if not m:
        raise RuntimeError(f"영상 정보를 읽을 수 없습니다: {path}\n{err[-800:]}")
    duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])

    vline = next((l for l in err.splitlines() if "Video:" in l), None)
    if vline is None:
        raise RuntimeError("영상 트랙이 없습니다.")
    wh = re.search(r"(\d{2,5})x(\d{2,5})", vline)
    width, height = int(wh[1]), int(wh[2])
    fm = re.search(r"(\d+(?:\.\d+)?) fps", vline) or re.search(r"(\d+(?:\.\d+)?) tbr", vline)
    fps_raw = fm[1] if fm else "30"
    fps_str = _NTSC.get(fps_raw, fps_raw)
    num, _, den = fps_str.partition("/")
    fps = float(num) / float(den or 1)

    # 휴대폰 세로 영상: ffmpeg 는 디코딩 시 자동 회전하므로 가로세로를 맞춰 줌
    rot = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", err) or re.search(r"rotate\s*:\s*(-?\d+)", err)
    if rot and abs(round(float(rot[1]))) % 180 == 90:
        width, height = height, width
    # libx264 yuv420p 는 짝수 크기 필요
    width -= width % 2
    height -= height % 2
    return VideoInfo(width, height, fps, fps_str, duration, "Audio:" in err)


def extract_audio(src: str, dst: str, rate: int, channels: int):
    run(["-i", src, "-vn", "-ac", str(channels), "-ar", str(rate), "-c:a", "pcm_s16le", dst])


def read_wav(path: str):
    """(float32 배열 [samples, channels], sample_rate)"""
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16)
    return data.reshape(-1, ch).astype(np.float32) / 32768.0, sr


def write_wav(path: str, audio: np.ndarray, sr: int):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def iter_frames(src: str, info: VideoInfo, width: int = None, height: int = None):
    """원본을 고정 프레임레이트(info.fps)로 디코딩해 BGR 프레임을 순서대로 돌려줌."""
    w, h = width or info.width, height or info.height
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", src, "-an",
           "-vf", f"fps={info.fps_str},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = w * h * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def sample_frames(src: str, every_sec: float, width: int):
    """OCR 용: every_sec 간격으로 축소된 프레임 (시각, 프레임)"""
    info = probe(src)
    height = int(round(info.height * width / info.width / 2)) * 2
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", src, "-an",
           "-vf", f"fps=1/{every_sec},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = width * height * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            # fps 필터는 각 구간의 가운데 프레임을 고름
            yield (i + 0.5) * every_sec, np.frombuffer(buf, np.uint8).reshape(height, width, 3)
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


def open_encoder(dst: str, info: VideoInfo, audio_wav: str, crf: int, preset: str):
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{info.width}x{info.height}",
           "-r", info.fps_str, "-i", "-", "-i", audio_wav,
           "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", dst]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)
