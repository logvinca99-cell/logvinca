"""업무 타이머 알림 소리.

소리 파일 없이 프로그램이 직접 부드러운 소리를 만든다(처음 한 번, 이후 재사용).
- 풍경(싱잉볼): 일정한 3초 간격의 낮은 종소리, 긴 여운
- 오르골: 0.75초 간격의 느린 아르페지오 + 마지막 화음
둘 다 거의 무음(-45dB)에서 5~6초에 걸쳐 천천히 커지고, 음마다 '탁' 치는 소리 없이 스며들듯 시작한다.
"""

import math
import os
import shutil
import struct
import subprocess
import sys
import threading
import wave

SR = 22050  # 알림음에는 충분하고 만드는 시간이 절반으로 준다
SOUND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timer_sounds")
VERSION = 2  # 소리 모양을 바꾸면 올려서 다시 만들게 한다

BUILTIN = {"chime": "풍경 (싱잉볼)", "musicbox": "오르골"}


def _add(buf, start, s):
    i0 = int(start * SR)
    if i0 + len(s) > len(buf):
        buf.extend([0.0] * (i0 + len(s) - len(buf)))
    for i, v in enumerate(s):
        buf[i0 + i] += v


def _tone(freq, dur, partials, decay, amp=1.0, attack=0.25):
    n = int(SR * dur)
    out = [0.0] * n
    two_pi = 2 * math.pi
    for ratio, pa, pd in partials:
        w = two_pi * freq * ratio / SR
        k = math.exp(-decay * pd / SR)
        e = pa
        for i in range(n):
            out[i] += e * math.sin(w * i)
            e *= k
    na = int(SR * attack)
    for i in range(n):
        a = 0.5 - 0.5 * math.cos(math.pi * i / na) if i < na else 1.0
        out[i] *= amp * a
    return out


def _chime():
    bowl = [(1, 1.0, 1.0), (1.002, 0.5, 1.0), (2.76, 0.18, 1.8), (5.40, 0.05, 3.0)]
    buf = []
    for i, f in enumerate([392.0, 329.6, 392.0, 293.7]):
        _add(buf, i * 3.0, _tone(f, 7.0, bowl, 0.45, amp=0.55 + 0.15 * i, attack=0.35))
    return buf, 6.0


def _musicbox():
    t = [(1, 1.0, 1.0), (2, 0.15, 1.6), (3, 0.04, 2.4)]
    notes = [523.25, 659.25, 783.99, 1046.5, 783.99, 659.25, 783.99, 1046.5]
    buf = []
    for i, f in enumerate(notes):
        _add(buf, i * 0.75, _tone(f, 4.0, t, 0.9, amp=0.35 + 0.08 * i, attack=0.12))
    end = len(notes) * 0.75 + 0.3
    for f in (523.25, 659.25, 783.99):
        _add(buf, end, _tone(f, 6.0, t, 0.55, amp=0.45, attack=0.4))
    return buf, 5.0


def _finish(buf, peak, rise):
    m = max(abs(v) for v in buf) or 1.0
    n_rise, n_out = int(SR * rise), int(SR * 1.5)
    n = len(buf)
    out = []
    for i, v in enumerate(buf):
        g = 10 ** (-45 * (1 - i / n_rise) / 20) if i < n_rise else 1.0
        if i > n - n_out:
            g *= (n - i) / n_out
        out.append(v / m * peak * g)
    return out


def _save(path, buf):
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 32767)) for v in buf))
    os.replace(tmp, path)


def path_for(name, volume):
    return os.path.join(SOUND_DIR, f"{name}_v{VERSION}_vol{volume}.wav")


def build(name, volume):
    """volume 1~10. 10 이 최대(그래도 원래 샘플 정도로 작음)."""
    path = path_for(name, volume)
    if os.path.exists(path):
        return path
    os.makedirs(SOUND_DIR, exist_ok=True)
    buf, rise = {"chime": _chime, "musicbox": _musicbox}[name]()
    base_peak = {"chime": 0.22, "musicbox": 0.20}[name]
    peak = base_peak * (volume / 7) ** 1.5  # 7 이 들어보신 샘플 크기
    _save(path, _finish(buf, min(peak, 0.45), rise))
    return path


def prepare_async(names, volume):
    threading.Thread(target=lambda: [build(n, volume) for n in names], daemon=True).start()


_proc = None


def stop():
    global _proc
    if sys.platform == "win32":
        import winsound
        winsound.PlaySound(None, 0)
    elif _proc and _proc.poll() is None:
        _proc.terminate()
    _proc = None


def play(sound, volume):
    """sound: 'chime' / 'musicbox' / .wav 파일 경로 / 'none'. 백그라운드에서 재생."""
    if not sound or sound == "none":
        return

    def run():
        global _proc
        try:
            path = build(sound, volume) if sound in BUILTIN else sound
            if not os.path.exists(path):
                path = build("chime", volume)
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            else:
                for player in ("afplay", "paplay", "aplay"):
                    if shutil.which(player):
                        stop()
                        _proc = subprocess.Popen([player, path], stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.DEVNULL)
                        break
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()
