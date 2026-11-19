"""내 전용 업무 타이머.

- 항상 맨 위에 떠 있는 위젯: 날짜·요일·시각, 남은 시간, ⛵ 항해 진행바, 오늘 도착한 섬 수, 메모
- 50분 업무 → 풍경 소리 + 화면 전체를 덮는 휴식 창(천천히 숨 쉬듯 색이 변함) 10분
- 휴식이 끝나면 오르골 소리 → '다시 집중 시작'을 눌러야 다음 업무 시작
- 사이클마다 '할 일'(시작할 때)과 '한 일'(휴식 때)을 한 줄씩 기록, 날짜별로 모아 보기
"""

import csv
import ctypes
import datetime as dt
import json
import math
import os
import random
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import timer_sound

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "timer_settings.json")
MEMO_FILE = os.path.join(HERE, "timer_memo.txt")
LOG_FILE = os.path.join(HERE, "timer_log.csv")
WIN = sys.platform == "win32"

WEEKDAYS = "월화수목금토일"
LOG_FIELDS = ["날짜", "시작", "끝", "집중(분)", "할 일", "한 일", "휴식"]
DEFAULTS = {
    "work_min": 50,
    "break_min": 10,
    "work_end_sound": "chime",      # 업무 끝 → 풍경
    "break_end_sound": "musicbox",  # 휴식 끝 → 오르골
    "volume": 7,
    "pos": None,
    "memo_open": True,
    "wave_anim": True,
}
TIPS = [
    "자리에서 일어나 기지개를 한 번 켜 보세요",
    "물 한 잔 천천히 마셔 보세요",
    "창밖 먼 곳을 20초 동안 바라보세요",
    "어깨와 목을 천천히 돌려 보세요",
    "눈을 감고 숨을 크게 다섯 번 쉬어 보세요",
    "잠깐 걸으면서 몸을 풀어 보세요",
]


class C:
    """색. 흰 바탕 + 회색 단계 + 파랑 포인트 하나."""
    bg = "#ffffff"
    line = "#e8ebf0"
    surface = "#f4f6f9"
    surface_hover = "#eaedf2"
    text = "#1d2533"
    sub = "#8b95a5"
    hint = "#b3bac6"
    accent = "#3b82f6"
    accent_hover = "#2f6fdf"
    accent_soft = "#eaf2fe"
    sea = "#e9eef5"
    rest = "#1f9d6a"
    rest_soft = "#e6f6ee"
    rest_track = "#e3efe8"
    warn = "#d97706"
    warn_soft = "#fdf3e4"
    island = "#2c9f6f"
    # 휴식 화면이 숨 쉬듯 오가는 두 색
    breath = {"break": ("#eef8f1", "#cdeAd8"), "break_done": ("#fdf3ea", "#f6d9c0")}
    rest_text = "#1e4634"
    done_text = "#5b3a1e"


# ───────────────────────── 화면 배율·글꼴

SCALE = 1.0


def S(v):
    return int(round(v * SCALE))


def enable_dpi_awareness():
    """윈도우 고해상도 화면에서 글자가 흐릿하게 늘어나지 않게 한다."""
    if not WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class F:
    ui = "TkDefaultFont"
    num = "TkDefaultFont"

    @classmethod
    def pick(cls, root):
        fams = set(tkfont.families(root))

        def first(*names):
            return next((n for n in names if n in fams), None)

        cls.ui = first("Pretendard", "Pretendard Variable", "맑은 고딕", "Malgun Gothic",
                       "Apple SD Gothic Neo", "Noto Sans CJK KR", "Noto Sans KR") or "TkDefaultFont"
        cls.num = first("Segoe UI Light", "Pretendard Light", "Helvetica Neue", "Noto Sans CJK KR Light",
                        "Noto Sans Light") or cls.ui
        cls.num_regular = first("Segoe UI", "Pretendard", "Helvetica Neue") or cls.ui
        cls.num_bold = first("Segoe UI", "Pretendard", "Helvetica Neue", "Noto Sans CJK KR") or cls.ui


# ───────────────────────── 저장소

def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_rows():
    try:
        with open(LOG_FILE, encoding="utf-8-sig", newline="") as f:
            return [{k: (r.get(k) or "") for k in LOG_FIELDS} for r in csv.DictReader(f)]
    except OSError:
        return []


def save_rows(rows):
    """엑셀에서 파일을 열어 두면 쓰기가 막힌다. 그때는 False 를 돌려주고 다음에 다시 쓴다."""
    try:
        tmp = LOG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, LOG_FILE)
        return True
    except OSError:
        return False


def fmt_clock(sec):
    sec = max(0, int(math.ceil(sec)))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_minutes(total):
    h, m = divmod(int(total), 60)
    return f"{h}시간 {m}분" if h else f"{m}분"


def sound_label(v):
    if v in timer_sound.BUILTIN:
        return timer_sound.BUILTIN[v]
    if v == "none":
        return "소리 없음"
    return os.path.basename(v)


def rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def mix(c1, c2, t):
    a, b = rgb(c1), rgb(c2)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def open_file(path):
    try:
        if WIN:
            os.startfile(path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
    except Exception as e:
        messagebox.showerror("열기 실패", str(e))


# ───────────────────────── 둥근 모양 (계단 없이 부드러운 가장자리)

_img_cache = {}


def rounded(w, h, r, fill, bg, border=None):
    """둥근 사각형 그림. 가장자리를 바탕색과 섞어 부드럽게 만든다(외부 라이브러리 없이)."""
    w, h = max(1, int(w)), max(1, int(h))
    key = (w, h, r, fill, bg, border)
    img = _img_cache.get(key)
    if img is not None:
        return img
    if len(_img_cache) > 600:
        _img_cache.clear()
    r = min(r, w / 2, h / 2)
    Fc, Bc = rgb(fill), rgb(bg)
    Ec = rgb(border) if border else None
    bw = 1.0
    hw, hh = w / 2, h / 2

    def blend(a, b, t):
        return tuple(round(x + (y - x) * t) for x, y in zip(a, b))

    rows, row_cache = [], {}
    for y in range(h):
        py = abs(y + 0.5 - hh) - (hh - r)
        key_py = round(py, 3) if py > -1.5 else "mid"
        cached = row_cache.get(key_py)
        if cached is None:
            px_list = []
            for x in range(w):
                px = abs(x + 0.5 - hw) - (hw - r)
                d = math.hypot(max(px, 0), max(py, 0)) + min(max(px, py), 0) - r
                cov = min(1.0, max(0.0, 0.5 - d))
                if Ec:
                    inner = min(1.0, max(0.0, 0.5 - (d + bw)))
                    col = blend(Ec, Fc, inner)
                else:
                    col = Fc
                px_list.append("#%02x%02x%02x" % blend(Bc, col, cov))
            cached = "{" + " ".join(px_list) + "}"
            row_cache[key_py] = cached
        rows.append(cached)
    img = tk.PhotoImage(width=w, height=h)
    img.put(" ".join(rows))
    _img_cache[key] = img
    return img


class PillButton(tk.Canvas):
    """둥근 버튼. kind: primary / soft / rest / ghost"""
    KINDS = {
        "primary": (C.accent, C.accent_hover, "#ffffff"),
        "soft": (C.surface, C.surface_hover, C.text),
        "rest": (C.rest, "#18855a", "#ffffff"),
        "ghost": (None, C.surface, C.sub),
    }

    def __init__(self, master, text, command=None, kind="primary", width=None, height=40, bg=C.bg,
                 font=None, radius=12):
        super().__init__(master, width=S(width) if width else S(40), height=S(height), bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2" if command else "")
        self.text, self.command, self.kind = text, command, kind
        self.font = font or (F.ui, 11, "bold")
        self.radius = S(radius)
        self.enabled, self.hover = True, False
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonRelease-1>", self._click)

    def _hover(self, v):
        self.hover = v
        self.draw()

    def _click(self, e):
        if self.enabled and self.command and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def set(self, text=None, kind=None, enabled=None):
        if text is not None:
            self.text = text
        if kind is not None:
            self.kind = kind
        if enabled is not None:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled and self.command else "")
        self.draw()

    def set_bg(self, color):
        self.configure(bg=color)
        self.draw()

    def draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        fill, hover, fg = self.KINDS[self.kind]
        bg = self["bg"]
        if not self.enabled:
            fill, fg = C.surface, C.hint
        elif self.hover:
            fill = hover
        self.delete("all")
        if fill:
            self._img = rounded(w, h, self.radius, fill, bg)
            self.create_image(0, 0, anchor="nw", image=self._img)
        self.create_text(w / 2, h / 2, text=self.text, font=self.font, fill=fg)


class RoundPanel(tk.Canvas):
    """둥근 바탕 위에 입력칸·메모칸 같은 위젯 하나를 올려 둔다."""

    def __init__(self, master, fill=C.surface, bg=C.bg, radius=12, pad=(12, 9), height=None, border=None):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, height=S(height) if height else 10)
        self.fill, self.radius, self.pad, self.border = fill, S(radius), (S(pad[0]), S(pad[1])), border
        self.win = None
        self.bind("<Configure>", lambda e: self.redraw())

    def hold(self, widget):
        self.win = self.create_window(*self.pad, anchor="nw", window=widget)
        self.redraw()
        return widget

    def set_bg(self, color):
        self.configure(bg=color)

    def redraw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        self.delete("bgimg")
        self._img = rounded(w, h, self.radius, self.fill, self["bg"], self.border)
        self.create_image(0, 0, anchor="nw", image=self._img, tags="bgimg")
        self.tag_lower("bgimg")
        if self.win:
            self.coords(self.win, *self.pad)
            self.itemconfigure(self.win, width=w - 2 * self.pad[0], height=h - 2 * self.pad[1])


class HintEntry(tk.Entry):
    """비어 있으면 흐린 안내 글씨가 보이는 입력칸."""

    def __init__(self, master, hint, bg=C.surface, size=11, **kw):
        super().__init__(master, bd=0, relief="flat", bg=bg, fg=C.text, insertbackground=C.text,
                         highlightthickness=0, font=(F.ui, size), **kw)
        self.hint, self.showing = hint, False
        self.bind("<FocusIn>", self._in)
        self.bind("<FocusOut>", self._out)
        self._out()

    def _in(self, _=None):
        if self.showing:
            self.delete(0, "end")
            self.configure(fg=C.text)
            self.showing = False

    def _out(self, _=None):
        if not self.get():
            self.insert(0, self.hint)
            self.configure(fg=C.hint)
            self.showing = True

    def value(self):
        return "" if self.showing else self.get().strip()

    def set_value(self, v):
        self.delete(0, "end")
        self.showing = False
        self.configure(fg=C.text)
        if v:
            self.insert(0, v)
        elif self.focus_get() is not self:
            self._out()


def icon_label(master, text, command, size=12, bg=C.bg):
    lbl = tk.Label(master, text=text, font=(F.ui, size), bg=bg, fg=C.sub, cursor="hand2", padx=S(4))
    lbl.bind("<Enter>", lambda e: lbl.configure(fg=C.text))
    lbl.bind("<Leave>", lambda e: lbl.configure(fg=C.sub))
    lbl.bind("<ButtonRelease-1>", lambda e: command())
    return lbl


def style_window_win(win, taskbar=False):
    """윈도우: 제목줄 없는 창도 작업 표시줄에 보이게 하고, 윈도우 11 이면 모서리를 둥글게."""
    if not WIN:
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if taskbar:
            GWL_EXSTYLE, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = -20, 0x00040000, 0x00000080
            st = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (st & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
        if taskbar:
            win.withdraw()
            win.after(10, win.deiconify)
    except Exception:
        pass


# ───────────────────────── 모니터

def monitors():
    """[(x, y, w, h, 주모니터여부)]. 윈도우가 아니면 화면 하나로 본다."""
    if WIN:
        try:
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            res = []
            proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                       ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

            def cb(hmon, hdc, rect, data):
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
                r = mi.rcMonitor
                res.append((r.left, r.top, r.right - r.left, r.bottom - r.top, bool(mi.dwFlags & 1)))
                return True

            user32.EnumDisplayMonitors(None, None, proto(cb), 0)
            if res:
                return res
        except Exception:
            pass
    return None


def all_monitors(root):
    return monitors() or [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight(), True)]


def monitor_of(win):
    mons = all_monitors(win)
    cx = win.winfo_rootx() + win.winfo_width() // 2
    cy = win.winfo_rooty() + win.winfo_height() // 2
    for m in mons:
        if m[0] <= cx < m[0] + m[2] and m[1] <= cy < m[1] + m[3]:
            return m
    return next((m for m in mons if m[4]), mons[0])


# ───────────────────────── 바다 장면

SKY_TOP, SKY_BOTTOM = "#f3f8ff", "#e1edfd"
WAVE_BACK = "#bcd8fb"
WAVE_FRONT = ("#86baf8", "#3b82f6")
SCENE_TEXT = "#1b3556"
FRAMES = 36            # 물결 한 바퀴 그림 수
FRAME_MS = 125         # 한 칸 넘어가는 간격(ms) → 한 바퀴 4.5초


def gradient_image(w, h, top, bottom):
    img = tk.PhotoImage(width=w, height=h)
    for y in range(h):
        img.put(mix(top, bottom, y / max(1, h - 1)), to=(0, y, w, y + 1))
    return img


class WaveFrames:
    """앞·뒤 두 겹 물결이 흐르는 그림들. 가장자리를 부드럽게 섞어 미리 그려 두고 돌려 쓴다.

    처음 한 장만 바로 그리고 나머지는 조금씩 나눠 그려서 시작할 때 멈칫하지 않게 한다.
    """

    def __init__(self, widget, w, h, sky_rows, wavelen, amp_f, amp_b, base_f, base_b):
        self.w, self.h = w, h
        self.len_f, self.len_b = wavelen, wavelen * 1.35
        self.amp_f, self.amp_b, self.base_f, self.base_b = amp_f, amp_b, base_f, base_b
        self.rows = []
        for y in range(h):
            sky, back = sky_rows[y], WAVE_BACK
            front = mix(WAVE_FRONT[0], WAVE_FRONT[1], max(0.0, (y - base_f + amp_f) / max(1, h - base_f + amp_f)))
            lv = [i / 8 for i in range(9)]
            self.rows.append((sky, back, front,
                              [mix(sky, back, t) for t in lv],
                              [mix(sky, front, t) for t in lv],
                              [mix(back, front, t) for t in lv]))
        self.frames = [None] * FRAMES
        self.frames[0] = self.make(0)
        self.widget = widget
        self.next = 1
        widget.after(200, self._more)

    def _more(self):
        if self.next < FRAMES:
            try:
                self.frames[self.next] = self.make(self.next)
            except tk.TclError:
                return
            self.next += 1
            self.widget.after(20, self._more)

    def y_front(self, x, k):
        return self.base_f + self.amp_f * math.sin(2 * math.pi * (x / self.len_f + k / FRAMES))

    def make(self, k):
        W, H = self.w, self.h
        p = k / FRAMES
        two_pi = 2 * math.pi
        YF = [self.base_f + self.amp_f * math.sin(two_pi * (x / self.len_f + p)) for x in range(W)]
        YB = [self.base_b + self.amp_b * math.sin(two_pi * (x / self.len_b - p) + 1.7) for x in range(W)]
        top = min(min(YF), min(YB)) - 1
        bottom = max(YF) + 1
        rows = []
        for y in range(H):
            sky, back, front, sb, sf, bf = self.rows[y]
            yc = y + 0.5
            if yc <= top:
                rows.append("{" + " ".join([sky] * W) + "}")
                continue
            if yc >= bottom:
                rows.append("{" + " ".join([front] * W) + "}")
                continue
            out = []
            ap = out.append
            for x in range(W):
                cf = yc - YF[x]
                if cf >= 1:
                    ap(front)
                    continue
                cb = yc - YB[x]
                if cf <= 0:
                    if cb >= 1:
                        ap(back)
                    elif cb <= 0:
                        ap(sky)
                    else:
                        ap(sb[int(cb * 8 + 0.5)])
                else:
                    q = int(cf * 8 + 0.5)
                    ap(bf[q] if cb >= 1 else sf[q])
            rows.append("{" + " ".join(out) + "}")
        img = tk.PhotoImage(width=W, height=H)
        img.put(" ".join(rows))
        return img

    def get(self, k):
        return self.frames[k] or self.frames[0]


class Scene(tk.Canvas):
    """위쪽 하늘·바다 장면: 날짜, 현재 시각, 상태, 큰 타이머, 흐르는 물결 위의 배와 섬."""

    def __init__(self, app, master, mini=False):
        self.app, self.mini = app, mini
        W = S(App.W)
        H = S(96) if mini else S(262)
        super().__init__(master, width=W, height=H, highlightthickness=0, bd=0, bg=SKY_BOTTOM)
        self.W, self.H = W, H
        self.Hw = S(40) if mini else S(66)
        self._bg = gradient_image(W, H, SKY_TOP, SKY_BOTTOM)
        self.create_image(0, 0, anchor="nw", image=self._bg)
        sky_rows = [mix(SKY_TOP, SKY_BOTTOM, (H - self.Hw + y) / max(1, H - 1)) for y in range(self.Hw)]
        if mini:
            self.waves = WaveFrames(self, W, self.Hw, sky_rows, S(42), S(3.2), S(2.6), S(22), S(15))
        else:
            self.waves = WaveFrames(self, W, self.Hw, sky_rows, S(58), S(5), S(4), S(32), S(21))
        self.wave = self.create_image(0, H - self.Hw, anchor="nw", image=self.waves.get(0))
        self.frame = 0

        self.island_x = W - (S(22) if mini else S(32))
        self.create_text(self.island_x, H - self.Hw + self.waves.base_f + S(5), anchor="s", text="🏝",
                         font=(F.ui, -S(20 if mini else 30)), fill="#2c8a5f")
        self.boat = self.create_text(0, 0, anchor="s", text="⛵", font=(F.ui, -S(20 if mini else 30)),
                                     fill=SCENE_TEXT)
        self.bx = S(22)

        if mini:
            self.timer = self.create_text(S(18), S(32), anchor="w", font=(F.num_bold, -S(40), "bold"),
                                          fill=SCENE_TEXT)
            self.clock = self.create_text(W - S(40), S(32), anchor="e", font=(F.num_bold, -S(17), "bold"),
                                          fill="#4b5565")
            self.icon("⤢", W - S(18), S(32), app.toggle_compact, 14)
        else:
            self.date = self.create_text(S(22), S(32), anchor="w", font=(F.ui, -S(15), "bold"), fill="#4b5565")
            self.clock = self.create_text(S(21), S(68), anchor="w", font=(F.num_bold, -S(34), "bold"),
                                          fill=C.text)
            self.icon("✕", W - S(18), S(22), app.on_close, 13)
            self.icon("—", W - S(44), S(22), app.toggle_compact, 12)
            self.icon("⛶", W - S(72), S(22), app.open_big, 13)
            self.chip_img = self.create_image(W - S(22), S(68), anchor="e")
            self.chip_txt = self.create_text(0, S(68), anchor="center", font=(F.ui, -S(13), "bold"))
            self.timer = self.create_text(W / 2, S(142), anchor="center", font=(F.num_bold, -S(80), "bold"),
                                          fill=SCENE_TEXT)
        self._shown = {}
        self.place_boat()

    def icon(self, text, x, y, command, size):
        t = self.create_text(x, y, text=text, font=(F.ui, -S(size)), fill=C.sub)
        self.tag_bind(t, "<Enter>", lambda e: (self.itemconfigure(t, fill=C.text), self.configure(cursor="hand2")))
        self.tag_bind(t, "<Leave>", lambda e: (self.itemconfigure(t, fill=C.sub), self.configure(cursor="")))
        self.tag_bind(t, "<ButtonRelease-1>", lambda e: command())

    def set_text(self, item, key, text):
        if self._shown.get(key) != text:
            self._shown[key] = text
            self.itemconfigure(item, text=text)

    def set_chip(self, text, color):
        if self.mini or self._shown.get("chip") == (text, color):
            return
        self._shown["chip"] = (text, color)
        f = tkfont.Font(family=F.ui, size=-S(13), weight="bold")
        w, h = f.measure(text) + S(28), S(30)
        bg = mix(SKY_TOP, SKY_BOTTOM, S(68) / self.H)
        self._chip = rounded(w, h, h // 2, "#ffffff", bg)
        self.itemconfigure(self.chip_img, image=self._chip)
        self.coords(self.chip_txt, self.W - S(22) - w / 2, S(68))
        self.itemconfigure(self.chip_txt, text=text, fill=color)

    def set_progress(self, frac, docked):
        x0, x1 = S(20 if self.mini else 26), self.island_x - S(30 if self.mini else 42)
        bx = x1 + S(10) if docked else x0 + (x1 - x0) * frac
        if abs(bx - self.bx) >= 0.5:
            self.bx = bx
            self.place_boat()

    def place_boat(self):
        k = self.frame
        y = self.waves.y_front(self.bx, k)
        slope = (self.waves.y_front(self.bx + 3, k) - self.waves.y_front(self.bx - 3, k)) / 6
        self.coords(self.boat, self.bx, self.H - self.Hw + y + S(4))
        try:
            self.itemconfigure(self.boat, angle=-math.degrees(math.atan(slope)) * 0.45)
        except tk.TclError:
            pass

    def step(self):
        self.frame = (self.frame + 1) % FRAMES
        self.itemconfigure(self.wave, image=self.waves.get(self.frame))
        self.place_boat()


class BigView:
    """위젯을 모니터 한 대에 크게 띄우는 모드. 멀리서도 보이는 시계처럼 쓴다."""

    def __init__(self, app):
        self.app = app
        x, y, w, h, _ = monitor_of(app.root)
        self.w, self.h = w, h
        win = self.win = tk.Toplevel(app.root)
        win.overrideredirect(True)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.configure(bg=SKY_BOTTOM)
        c = self.c = tk.Canvas(win, width=w, height=h, highlightthickness=0, bd=0, bg=SKY_BOTTOM)
        c.pack(fill="both", expand=True)
        self._bg = gradient_image(w, h, SKY_TOP, SKY_BOTTOM)
        c.create_image(0, 0, anchor="nw", image=self._bg)

        u = h / 100  # 화면 높이의 1%
        self.date = c.create_text(w * 0.05, u * 9, anchor="w", font=(F.ui, -int(u * 3.6), "bold"), fill="#4b5565")
        self.clock = c.create_text(w * 0.05, u * 16, anchor="w", font=(F.num_bold, -int(u * 8), "bold"),
                                   fill=C.text)
        self.state = c.create_text(w * 0.95, u * 9, anchor="e", font=(F.ui, -int(u * 3.2), "bold"),
                                   fill=C.accent)
        self.timer = c.create_text(w / 2, u * 46, anchor="center", font=(F.num_bold, -int(u * 30), "bold"),
                                   fill=SCENE_TEXT)
        self.plan = c.create_text(w / 2, u * 66, anchor="center", font=(F.ui, -int(u * 3), "bold"),
                                  fill="#4b5565")

        self.wave_h, self.wave_top = u * 16, h - u * 16
        self.back = c.create_polygon(0, 0, 0, 0, fill=WAVE_BACK, outline="", smooth=True)
        self.front = c.create_polygon(0, 0, 0, 0, fill="#5b9cf6", outline="", smooth=True)
        self.len_f, self.amp = w / 7, u * 1.6
        self.island_x = w - w * 0.06
        c.create_text(self.island_x, self.wave_top + u * 5, anchor="s", text="🏝",
                      font=(F.ui, -int(u * 8)), fill="#2c8a5f")
        self.boat = c.create_text(0, 0, anchor="s", text="⛵", font=(F.ui, -int(u * 8)), fill=SCENE_TEXT)
        self.bx = w * 0.05
        self.frame = 0

        bw = int(max(110, u * 14) / SCALE)
        self.btn = PillButton(c, "일시정지", app.on_main_button, "soft", width=bw, height=int(u * 5.4 / SCALE),
                              bg=mix(SKY_TOP, SKY_BOTTOM, 0.25), font=(F.ui, -int(u * 2.2), "bold"))
        small = PillButton(c, "작게 보기", app.close_big, "soft", width=bw, height=int(u * 5.4 / SCALE),
                           bg=mix(SKY_TOP, SKY_BOTTOM, 0.25), font=(F.ui, -int(u * 2.2), "bold"))
        c.create_window(w * 0.95, u * 22, anchor="ne", window=small)
        c.create_window(w * 0.95 - S(bw) - S(10), u * 22, anchor="ne", window=self.btn)
        win.bind("<Escape>", lambda e: app.close_big())
        c.bind("<Double-Button-1>", lambda e: app.close_big())
        self.draw_waves()

    def wy(self, x, k, back=False):
        if back:
            return self.wave_top + self.amp * math.sin(2 * math.pi * (x / (self.len_f * 1.35) - k / FRAMES) + 1.7)
        return self.wave_top + self.amp * 2.2 + self.amp * math.sin(2 * math.pi * (x / self.len_f + k / FRAMES))

    def draw_waves(self):
        k, w, h = self.frame, self.w, self.h
        step = max(8, w // 90)
        for item, back in ((self.back, True), (self.front, False)):
            pts = []
            for x in range(-step, w + 2 * step, step):
                pts += [x, self.wy(x, k, back)]
            pts += [w + step, h + 10, w + step, h + 10, -step, h + 10, -step, h + 10]
            self.c.coords(item, *pts)
        y = self.wy(self.bx, k)
        slope = (self.wy(self.bx + 4, k) - self.wy(self.bx - 4, k)) / 8
        self.c.coords(self.boat, self.bx, y + self.h * 0.012)
        try:
            self.c.itemconfigure(self.boat, angle=-math.degrees(math.atan(slope)) * 0.45)
        except tk.TclError:
            pass

    def step(self):
        self.frame = (self.frame + 1) % FRAMES
        self.draw_waves()

    def update(self, now, timer_text, state_text, state_color, frac, docked, plan, btn_text, btn_enabled):
        c = self.c
        c.itemconfigure(self.date, text=f"{now.month}월 {now.day}일 {WEEKDAYS[now.weekday()]}요일")
        c.itemconfigure(self.clock, text=f"{now:%H:%M}")
        c.itemconfigure(self.timer, text=timer_text)
        c.itemconfigure(self.state, text=state_text, fill=state_color)
        c.itemconfigure(self.plan, text=plan)
        if self.btn.text != btn_text or self.btn.enabled != btn_enabled:
            self.btn.set(text=btn_text, enabled=btn_enabled)
        x0, x1 = self.w * 0.05, self.island_x - self.w * 0.06
        bx = x1 + self.w * 0.015 if docked else x0 + (x1 - x0) * frac
        if abs(bx - self.bx) >= 1:
            self.bx = bx
            self.draw_waves()

    def destroy(self):
        if self.win.winfo_exists():
            self.win.destroy()


# ───────────────────────── 메인 위젯

class App:
    W = 330

    def __init__(self, root):
        self.root = root
        self.s = load_settings()
        self.s.setdefault("memo_open", True)
        self.s.setdefault("wave_anim", True)
        self.rows = load_rows()
        self.rows_dirty = False

        self.phase = "idle"       # idle / work / break / break_done
        self.paused = False
        self.end_at = 0.0
        self.remain = self.s["work_min"] * 60.0
        self.total = self.remain
        self.cur = None
        self.cur_minutes = 0
        self.overlay = None
        self.big = None
        self.compact = False
        self.memo_job = None
        self._shown = {}

        timer_sound.prepare_async(["chime", "musicbox"], self.s["volume"])

        root.title("업무 타이머")
        root.configure(bg=C.line)
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        self.card = tk.Frame(root, bg=C.bg)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)
        self.build_full()
        self.build_mini()
        self.full.pack(fill="x")

        self.load_memo()
        self.refresh_stats()
        self.apply_memo()
        self.place_window()
        root.after(20, lambda: style_window_win(root, taskbar=True))
        self.tick()
        self.animate()

    # ── 창 위치·크기
    def place_window(self):
        self.root.update_idletasks()
        w, h = S(self.W) + 2, self.card.winfo_reqheight() + 2
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        pos = self.s.get("pos")
        if pos and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
        else:
            x, y = sw - w - S(24), S(24)
        vx, vy = self.root.winfo_vrootx(), self.root.winfo_vrooty()
        vw = max(sw, self.root.winfo_vrootwidth())
        vh = max(sh, self.root.winfo_vrootheight())
        x = min(max(vx, x), vx + vw - S(80))
        y = min(max(vy, y), vy + vh - S(60))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def fit_height(self):
        self.root.update_idletasks()
        w, h = S(self.W) + 2, self.card.winfo_reqheight() + 2
        self.root.geometry(f"{w}x{h}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def draggable(self, *widgets):
        for w in widgets:
            w.bind("<ButtonPress-1>", self._drag_start, add="+")
            w.bind("<B1-Motion>", self._drag_move, add="+")

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    # ── 큰 화면
    def build_full(self):
        f = self.full = tk.Frame(self.card, bg=C.bg)
        px = S(22)
        self.scene = Scene(self, f)
        self.scene.pack(fill="x")

        plan = RoundPanel(f, height=46, pad=(16, 12))
        plan.pack(fill="x", padx=px, pady=(S(16), 0))
        self.plan = plan.hold(HintEntry(plan, "이번 항해에서 할 일 (선택)", size=11))

        btns = tk.Frame(f, bg=C.bg)
        btns.pack(fill="x", padx=px, pady=(S(10), 0))
        self.btn_main = PillButton(btns, "시작", self.on_main_button, "primary", height=48,
                                   font=(F.ui, 12, "bold"), radius=14)
        self.btn_main.pack(side="left", fill="x", expand=True)
        self.btn_reset = PillButton(btns, "↺", self.reset, "soft", width=48, height=48,
                                    font=(F.ui, 15), radius=14)
        self.btn_reset.pack(side="left", padx=(S(8), 0))

        self.stats_lbl = tk.Label(f, font=(F.ui, 10), bg=C.bg, fg=C.sub)
        self.stats_lbl.pack(pady=(S(14), 0))
        tk.Frame(f, bg=C.line, height=1).pack(fill="x", padx=px, pady=(S(14), S(10)))

        mh = tk.Frame(f, bg=C.bg, cursor="hand2")
        mh.pack(fill="x", padx=px)
        self.memo_title = tk.Label(mh, text="메모", font=(F.ui, 10, "bold"), bg=C.bg, fg=C.sub, cursor="hand2")
        self.memo_title.pack(side="left")
        self.memo_toggle = tk.Label(mh, font=(F.ui, 10, "bold"), bg=C.bg, fg=C.sub, cursor="hand2")
        self.memo_toggle.pack(side="right")
        self.saved_lbl = tk.Label(mh, text="", font=(F.ui, 8), bg=C.bg, fg=C.hint)
        self.saved_lbl.pack(side="right", padx=S(8))
        for x in (mh, self.memo_title, self.memo_toggle):
            x.bind("<ButtonRelease-1>", lambda e: self.toggle_memo())
            x.bind("<Enter>", lambda e: self.memo_toggle.configure(fg=C.text))
            x.bind("<Leave>", lambda e: self.memo_toggle.configure(fg=C.sub))

        self.memo_panel = RoundPanel(f, pad=(14, 12), height=140)
        self.memo = self.memo_panel.hold(tk.Text(self.memo_panel, font=(F.ui, 11), wrap="word", bd=0,
                                                 relief="flat", bg=C.surface, fg=C.text,
                                                 insertbackground=C.text, highlightthickness=0, undo=True,
                                                 spacing1=S(2), spacing3=S(2)))
        self.memo.bind("<<Modified>>", self.on_memo_change)

        self.foot = tk.Frame(f, bg=C.bg)
        self.foot.pack(fill="x", padx=px, pady=(S(12), S(14)))
        icon_label(self.foot, "기록 보기", self.open_log, 10).pack(side="left")
        icon_label(self.foot, "설정", self.open_settings, 10).pack(side="right")

        self.draggable(self.scene, f, btns, self.foot, self.stats_lbl)

    def apply_memo(self):
        if self.s["memo_open"]:
            self.memo_panel.pack(fill="x", padx=S(22), pady=(S(8), 0), before=self.foot)
            self.memo_toggle.configure(text="▾ 접기")
            self.memo_title.configure(text="메모")
        else:
            self.memo_panel.pack_forget()
            self.memo_toggle.configure(text="▸ 펼치기")
            lines = [l for l in self.memo.get("1.0", "end-1c").splitlines() if l.strip()]
            self.memo_title.configure(text=f"메모 · {len(lines)}줄" if lines else "메모")

    def toggle_memo(self):
        self.s["memo_open"] = not self.s["memo_open"]
        self.apply_memo()
        save_settings(self.s)
        self.fit_height()

    # ── 접힌 화면
    def build_mini(self):
        self.mini = tk.Frame(self.card, bg=C.bg)
        self.mini_scene = Scene(self, self.mini, mini=True)
        self.mini_scene.pack(fill="x")
        self.draggable(self.mini_scene)

    def toggle_compact(self):
        self.compact = not self.compact
        if self.compact:
            self.full.pack_forget()
            self.mini.pack(fill="x")
        else:
            self.mini.pack_forget()
            self.full.pack(fill="x")
        self.fit_height()

    # ── 크게 보기
    def open_big(self):
        if self.big:
            return
        self.big = BigView(self)
        self.root.withdraw()

    def close_big(self):
        if self.big:
            self.big.destroy()
            self.big = None
            self.root.deiconify()
            self.root.attributes("-topmost", True)

    # ── 타이머
    def remaining(self):
        if self.phase in ("work", "break") and not self.paused:
            return max(0.0, self.end_at - time.monotonic())
        return self.remain

    def tick(self):
        now = dt.datetime.now()
        if getattr(self, "_today", None) != now.date():
            self._today = now.date()
            self.refresh_stats()

        if self.phase == "work" and not self.paused and self.remaining() <= 0:
            self.finish_work()
        elif self.phase == "break" and self.remaining() <= 0:
            self.finish_break()

        rem = self.remaining()
        t = fmt_clock(rem)
        state, color = self.status()
        frac = 0.0 if not self.total else max(0.0, min(1.0, 1 - rem / self.total))
        docked = self.phase in ("break", "break_done")
        sc = self.mini_scene if self.compact else self.scene
        sc.set_text(sc.timer, "timer", t)
        sc.set_text(sc.clock, "clock", f"{now:%H:%M}")
        if not self.compact:
            sc.set_text(sc.date, "date", f"{now.month}월 {now.day}일 {WEEKDAYS[now.weekday()]}요일")
            sc.set_chip(state, color)
        sc.set_progress(frac, docked)
        if self.big:
            btn = {"idle": "시작", "work": "계속" if self.paused else "일시정지", "break": "휴식 중",
                   "break_done": "다시 시작"}[self.phase]
            plan = self.plan.value() if self.phase == "work" else ""
            self.big.update(now, t, state, color, frac, docked, plan, btn, self.phase != "break")
        if self.overlay:
            self.overlay.update_time(rem)
        if self._shown.get("title") != (t, state):
            self._shown["title"] = (t, state)
            self.root.title(f"{t} {state}" if self.phase != "idle" else "업무 타이머")
        if self.rows_dirty:
            self.flush_rows()
        self.root.after(250, self.tick)

    def animate(self):
        """업무 중에만 물결이 흐른다(설정에서 끌 수 있음)."""
        on = self.s.get("wave_anim", True) and self.phase == "work" and not self.paused
        if on:
            if self.big:
                self.big.step()
            elif self.compact:
                self.mini_scene.step()
            else:
                self.scene.step()
        self.root.after(FRAME_MS if on else 500, self.animate)

    def status(self):
        if self.phase == "idle":
            return "출항 준비", C.sub
        if self.phase == "work":
            return ("잠시 멈춤", C.warn) if self.paused else ("⛵ 항해 중", C.accent)
        if self.phase == "break":
            return "⚓ 섬에서 휴식", C.rest
        return "출항 대기", C.warn

    def on_main_button(self):
        if self.phase in ("idle", "break_done"):
            if self.overlay:
                self.overlay.resume()
            else:
                self.start_work()
        elif self.phase == "work":
            self.toggle_pause()

    def start_work(self):
        mins = float(self.s["work_min"])
        now = dt.datetime.now()
        self.cur = {"날짜": now.strftime("%Y-%m-%d"), "시작": now.strftime("%H:%M"), "끝": "",
                    "집중(분)": "", "할 일": self.plan.value(), "한 일": "", "휴식": ""}
        self.cur_minutes = mins
        self.phase, self.paused = "work", False
        self.total = mins * 60.0
        self.end_at = time.monotonic() + self.total
        self.btn_main.set(text="일시정지", kind="soft", enabled=True)
        self.btn_reset.set(enabled=True)

    def toggle_pause(self):
        if self.phase != "work":
            return
        if self.paused:
            self.end_at = time.monotonic() + self.remain
            self.paused = False
            self.btn_main.set(text="일시정지", kind="soft")
        else:
            self.remain = self.remaining()
            self.paused = True
            self.btn_main.set(text="계속", kind="primary")

    def reset(self):
        if self.phase in ("break", "break_done"):
            return
        if self.phase == "work":
            done = self.total - self.remaining()
            if done > 60 and not messagebox.askyesno(
                    "리셋", "진행 중인 항해를 처음부터 다시 할까요?\n(이번 사이클은 기록되지 않습니다)",
                    parent=self.root):
                return
        self.phase, self.paused, self.cur = "idle", False, None
        self.total = self.remain = self.s["work_min"] * 60.0
        self.btn_main.set(text="시작", kind="primary", enabled=True)

    def finish_work(self):
        now = dt.datetime.now()
        self.cur["할 일"] = self.plan.value() or self.cur["할 일"]
        self.cur.update({"끝": now.strftime("%H:%M"), "집중(분)": str(round(self.cur_minutes)),
                         "휴식": "휴식 중"})
        self.rows.append(self.cur)
        self.rows_dirty = True
        self.refresh_stats()

        self.phase = "break"
        self.total = self.s["break_min"] * 60.0
        self.end_at = time.monotonic() + self.total
        self.btn_main.set(text="휴식 중", kind="soft", enabled=False)
        self.btn_reset.set(enabled=False)
        timer_sound.play(self.s["work_end_sound"], self.s["volume"])
        self.overlay = BreakOverlay(self)

    def finish_break(self):
        self.phase = "break_done"
        self.remain = 0.0
        if self.cur and self.cur["휴식"] == "휴식 중":
            self.cur["휴식"] = "완료"
            self.rows_dirty = True
        timer_sound.play(self.s["break_end_sound"], self.s["volume"])
        self.btn_main.set(text="다시 집중 시작", kind="primary", enabled=True)
        if self.overlay:
            self.overlay.show_done()

    def skip_break(self):
        left = max(1, round(self.remaining() / 60))
        if self.cur:
            self.cur["휴식"] = f"건너뜀 ({left}분 남기고)"
            self.rows_dirty = True
        self.close_overlay()
        self.plan.set_value("")
        self.start_work()

    def resume_from_overlay(self, next_plan):
        self.close_overlay()
        self.plan.set_value(next_plan)
        self.start_work()

    def close_overlay(self):
        if self.overlay:
            if self.cur:
                self.cur["한 일"] = self.overlay.result.value()
                self.rows_dirty = True
            self.overlay.destroy()
            self.overlay = None
        timer_sound.stop()
        self.refresh_stats()

    def flush_rows(self):
        if save_rows(self.rows):
            self.rows_dirty = False

    def today_stats(self):
        today = dt.date.today().strftime("%Y-%m-%d")
        rows = [r for r in self.rows if r["날짜"] == today and r["집중(분)"]]
        mins = sum(int(r["집중(분)"] or 0) for r in rows)
        skipped = sum(1 for r in rows if r["휴식"].startswith("건너뜀"))
        return len(rows), mins, skipped

    def refresh_stats(self):
        n, mins, skipped = self.today_stats()
        text = f"오늘 도착한 섬 {n}개  ·  집중 {fmt_minutes(mins)}"
        if skipped:
            text += f"  ·  휴식 건너뜀 {skipped}"
        self.stats_lbl.configure(text=text, fg=C.warn if skipped else C.sub)

    # ── 메모
    def load_memo(self):
        try:
            with open(MEMO_FILE, encoding="utf-8") as f:
                self.memo.insert("1.0", f.read().rstrip("\n"))
        except OSError:
            pass
        self.memo.edit_modified(False)
        self.memo.edit_reset()

    def on_memo_change(self, _=None):
        if not self.memo.edit_modified():
            return
        self.memo.edit_modified(False)
        self.saved_lbl.configure(text="")
        if self.memo_job:
            self.root.after_cancel(self.memo_job)
        self.memo_job = self.root.after(800, self.save_memo)

    def save_memo(self):
        self.memo_job = None
        try:
            with open(MEMO_FILE, "w", encoding="utf-8") as f:
                f.write(self.memo.get("1.0", "end-1c"))
            self.saved_lbl.configure(text="저장됨")
        except OSError:
            self.saved_lbl.configure(text="저장 실패")

    # ── 창
    def open_log(self):
        LogWindow(self)

    def open_settings(self):
        SettingsWindow(self)

    def on_close(self):
        if self.phase in ("work", "break") and not messagebox.askyesno(
                "종료", "타이머가 진행 중입니다. 종료할까요?", parent=self.root):
            return
        if self.overlay:
            self.close_overlay()
        self.close_big()
        self.save_memo()
        self.flush_rows()
        self.s["pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_settings(self.s)
        timer_sound.stop()
        self.root.destroy()


# ───────────────────────── 휴식 화면 (모든 모니터)

class BreakOverlay:
    """주 모니터: 남은 시간 + 한 일/할 일 입력. 다른 모니터: 아주 큰 남은 시간만."""
    PERIOD = 6.0  # 숨 한 번 길이(초)

    def __init__(self, app):
        self.app = app
        self.mode = "break"
        self.t0 = time.monotonic()
        self.asking = False
        a, b = C.breath["break"]
        self.mid = mix(a, b, 0.5)
        self.plain, self.canvases, self.wins, self.times, self.extras = [], [], [], [], []

        mons = all_monitors(app.root)
        primary = next((m for m in mons if m[4]), mons[0])
        for m in mons:
            if m is not primary:
                self.build_side(m)
        self.build_main(primary)

        n, mins, _ = app.today_stats()
        self.title.configure(text="⚓  섬에 도착했어요")
        self.sub.configure(text=f"오늘 {n}번째 항해 완료  ·  집중 {fmt_minutes(mins)}")
        self.breathe()
        self.keep_on_top()
        self.win.after(300, lambda: (self.win.focus_force(), self.result.focus_set()))

    def new_window(self, m, focusable):
        x, y, w, h, _ = m
        win = tk.Toplevel(self.app.root)
        win.title("쉬는 시간")
        win.configure(bg=self.mid)
        if focusable:
            win.geometry(f"{w}x{h}+{x}+{y}")
            win.attributes("-fullscreen", True)
        else:
            win.overrideredirect(True)
            win.geometry(f"{w}x{h}+{x}+{y}")
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: None)  # 닫기·Alt+F4 무시
        self.wins.append(win)
        self.plain.append(win)
        return win

    def L(self, parent, **kw):
        x = tk.Label(parent, bg=self.mid, **kw)
        self.plain.append(x)
        return x

    def Fr(self, parent):
        x = tk.Frame(parent, bg=self.mid)
        self.plain.append(x)
        return x

    def build_side(self, m):
        win = self.new_window(m, False)
        h = m[3]
        box = self.Fr(win)
        box.place(relx=0.5, rely=0.5, anchor="center")
        t = self.L(box, font=(F.num_bold, -int(h * 0.30), "bold"), fg=C.rest_text)
        t.pack()
        msg = self.L(box, text="쉬는 시간이에요", font=(F.ui, -int(h * 0.035), "bold"), fg=C.rest_text)
        msg.pack(pady=(int(h * 0.01), 0))
        self.times.append(t)
        self.extras.append((t, msg))

    def build_main(self, m):
        app = self.app
        h = m[3]
        w = self.win = self.new_window(m, True)
        box = self.Fr(w)
        box.place(relx=0.5, rely=0.47, anchor="center")
        self.title = self.L(box, font=(F.ui, -int(h * 0.032), "bold"), fg=C.rest_text)
        self.title.pack()
        self.sub = self.L(box, font=(F.ui, -int(h * 0.017)), fg=C.rest_text)
        self.sub.pack(pady=(S(6), 0))
        self.time = self.L(box, font=(F.num_bold, -int(h * 0.22), "bold"), fg=C.rest_text)
        self.time.pack()
        self.times.append(self.time)
        self.tip = self.L(box, text=random.choice(TIPS), font=(F.ui, -int(h * 0.019)), fg=C.rest_text)
        self.tip.pack(pady=(0, S(30)))

        form = self.Fr(box)
        form.pack(fill="x")
        plan = app.cur["할 일"] if app.cur else ""
        if plan:
            self.L(form, text=f"계획했던 일  ·  {plan}", font=(F.ui, 11), fg=C.rest_text).pack(anchor="w")
        self.L(form, text="이번 항해에서 한 일", font=(F.ui, 11, "bold"), fg=C.rest_text).pack(
            anchor="w", pady=(S(6), S(6)))
        p1 = RoundPanel(form, fill="#ffffff", bg=self.mid, radius=14, pad=(16, 12), height=50)
        p1.configure(width=S(520))
        p1.pack(fill="x")
        self.canvases.append(p1)
        self.result = p1.hold(HintEntry(p1, "한 줄로 적어 두세요 (비워도 돼요)", bg="#ffffff", size=13))

        self.next_box = self.Fr(box)
        self.L(self.next_box, text="다음 항해에서 할 일", font=(F.ui, 11, "bold"), fg=C.done_text).pack(
            anchor="w", pady=(S(18), S(6)))
        p2 = RoundPanel(self.next_box, fill="#ffffff", bg=self.mid, radius=14, pad=(16, 12), height=50)
        p2.pack(fill="x")
        self.canvases.append(p2)
        self.next = p2.hold(HintEntry(p2, "비워도 돼요", bg="#ffffff", size=13))
        self.next.bind("<Return>", lambda e: self.resume())
        self.go = PillButton(self.next_box, "⛵  다시 집중 시작", self.resume, "primary", height=56,
                             bg=self.mid, font=(F.ui, 14, "bold"), radius=16)
        self.go.pack(fill="x", pady=(S(22), 0))
        self.canvases.append(self.go)

        self.skip = tk.Label(w, text="급하게 계속하기", font=(F.ui, 10), bg=self.mid, fg=C.sub, cursor="hand2")
        self.skip.bind("<ButtonRelease-1>", lambda e: self.ask_skip())
        self.skip.place(relx=0.5, rely=0.95, anchor="center")
        self.plain.append(self.skip)

    def update_time(self, rem):
        if self.mode == "break":
            t = fmt_clock(rem)
            for lbl in self.times:
                if lbl.cget("text") != t:
                    lbl.configure(text=t)

    def show_done(self):
        self.mode = "break_done"
        a, b = C.breath["break_done"]
        self.mid = mix(a, b, 0.5)
        for c in self.canvases:
            c.set_bg(self.mid)
        for x in self.plain:
            if isinstance(x, tk.Label) and x is not self.skip:
                x.configure(fg=C.done_text)
        for t, msg in self.extras:
            h = t.winfo_toplevel().winfo_height()
            t.configure(text="다시 출항할 시간이에요", font=(F.ui, -int(h * 0.07), "bold"))
            msg.configure(text="주 모니터에서 ‘다시 집중 시작’을 눌러 주세요", font=(F.ui, -int(h * 0.028)))
        self.title.configure(text="다시 출항할 시간이에요")
        self.sub.configure(text="충분히 쉬었다면 천천히 시작해요")
        self.time.pack_forget()
        self.tip.pack_forget()
        self.sub.pack_configure(pady=(S(6), S(36)))
        self.skip.place_forget()
        self.next_box.pack(fill="x")
        self.next.focus_set()

    def breathe(self):
        if not self.win.winfo_exists():
            return
        a, b = C.breath[self.mode]
        t = (1 - math.cos(2 * math.pi * (time.monotonic() - self.t0) / self.PERIOD)) / 2
        color = mix(a, b, t)
        for x in self.plain:
            x.configure(bg=color)
        for c in self.canvases:
            c.configure(bg=color)
        self.win.after(80, self.breathe)

    def keep_on_top(self):
        if not self.win.winfo_exists():
            return
        if not self.asking:
            for w in self.wins:
                w.attributes("-topmost", True)
                w.lift()
        self.win.after(1000, self.keep_on_top)

    def ask_skip(self):
        left = max(1, round(self.app.remaining() / 60))
        self.asking = True
        ok = messagebox.askyesno(
            "정말 쉬지 않을까요?",
            f"아직 휴식이 {left}분 남았어요.\n\n지금 쉬지 않으면 다음 항해가 더 힘들어져요.\n"
            "그래도 쉬지 않고 바로 계속할까요?\n\n(건너뛴 기록이 남습니다)",
            icon="warning", default="no", parent=self.win)
        self.asking = False
        if ok:
            self.app.skip_break()

    def resume(self):
        if self.mode == "break_done":
            self.app.resume_from_overlay(self.next.value())

    def destroy(self):
        for w in self.wins:
            if w.winfo_exists():
                w.destroy()


# ───────────────────────── 작은 창 공통

def styled_toplevel(app, title, w, h=None):
    win = tk.Toplevel(app.root)
    win.title(title)
    win.configure(bg=C.bg)
    win.attributes("-topmost", True)
    x = max(0, app.root.winfo_x() - S(w) - S(12))
    size = f"{S(w)}x{S(h)}" if h else ""
    win.geometry(f"{size}+{x}+{app.root.winfo_y()}")
    win.after(20, lambda: style_window_win(win))
    return win


def setup_ttk(root):
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", font=(F.ui, 10), background=C.bg)
    st.configure("TFrame", background=C.bg)
    st.configure("TLabel", background=C.bg, foreground=C.text, font=(F.ui, 10))
    st.configure("Sub.TLabel", background=C.bg, foreground=C.sub, font=(F.ui, 9))
    st.configure("Head.TLabel", background=C.bg, foreground=C.text, font=(F.ui, 13, "bold"))
    st.configure("TCombobox", fieldbackground=C.surface, background=C.surface, bordercolor=C.line,
                 lightcolor=C.surface, darkcolor=C.surface, arrowcolor=C.sub, padding=S(5))
    st.map("TCombobox", fieldbackground=[("readonly", C.surface)])
    st.configure("TSpinbox", fieldbackground=C.surface, background=C.surface, bordercolor=C.line,
                 lightcolor=C.surface, darkcolor=C.surface, arrowcolor=C.sub, padding=S(5))
    st.configure("TCheckbutton", background=C.bg, foreground=C.text, font=(F.ui, 10),
                 indicatorbackground=C.surface, indicatorforeground=C.accent)
    st.map("TCheckbutton", background=[("active", C.bg)])
    st.configure("Horizontal.TScale", background=C.accent, troughcolor=C.sea, bordercolor=C.bg,
                 lightcolor=C.accent, darkcolor=C.accent)
    st.configure("Treeview", background=C.bg, fieldbackground=C.bg, foreground=C.text, borderwidth=0,
                 bordercolor=C.bg, lightcolor=C.bg, darkcolor=C.bg,
                 rowheight=S(32), font=(F.ui, 10))
    st.configure("Treeview.Heading", background=C.bg, foreground=C.sub, borderwidth=0, relief="flat",
                 font=(F.ui, 9, "bold"), padding=(S(4), S(8)))
    st.map("Treeview", background=[("selected", C.accent_soft)], foreground=[("selected", C.text)])
    st.map("Treeview.Heading", background=[("active", C.bg)])
    st.configure("Vertical.TScrollbar", background=C.surface, troughcolor=C.bg, bordercolor=C.bg,
                 arrowcolor=C.sub, lightcolor=C.surface, darkcolor=C.surface)


# ───────────────────────── 설정

class SettingsWindow:
    def __init__(self, app):
        self.app = app
        s = app.s
        w = self.win = styled_toplevel(app, "설정", 380)
        w.resizable(False, False)
        w.grab_set()
        f = ttk.Frame(w, padding=(S(24), S(20)))
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="설정", style="Head.TLabel").grid(row=0, column=0, columnspan=3, sticky="w",
                                                         pady=(0, S(14)))
        self.work = tk.StringVar(value=str(s["work_min"]))
        self.brk = tk.StringVar(value=str(s["break_min"]))
        self.vol = tk.IntVar(value=s["volume"])
        self.sounds = {"work_end_sound": s["work_end_sound"], "break_end_sound": s["break_end_sound"]}

        def row_label(r, text):
            ttk.Label(f, text=text).grid(row=r, column=0, sticky="w", pady=S(7), padx=(0, S(14)))

        row_label(1, "업무 시간")
        ttk.Spinbox(f, from_=1, to=180, textvariable=self.work, width=6).grid(row=1, column=1, sticky="w")
        row_label(2, "휴식 시간")
        ttk.Spinbox(f, from_=1, to=60, textvariable=self.brk, width=6).grid(row=2, column=1, sticky="w")
        ttk.Label(f, text="분 단위", style="Sub.TLabel").grid(row=1, column=2, sticky="e")

        self.combos = {}
        for i, (key, label) in enumerate([("work_end_sound", "업무 끝 소리"),
                                          ("break_end_sound", "휴식 끝 소리")]):
            r = 3 + i
            row_label(r, label)
            cb = ttk.Combobox(f, state="readonly", width=16)
            cb.grid(row=r, column=1, sticky="we")
            cb.bind("<<ComboboxSelected>>", lambda e, k=key: self.on_pick(k))
            self.combos[key] = cb
            self.fill_combo(key)
            PillButton(f, "▶", lambda k=key: self.preview(k), "soft", width=34, height=30,
                       font=(F.ui, 9), radius=10).grid(row=r, column=2, sticky="e", padx=(S(8), 0))

        row_label(5, "소리 크기")
        vf = ttk.Frame(f)
        vf.grid(row=5, column=1, columnspan=2, sticky="we")
        ttk.Scale(vf, from_=1, to=10, variable=self.vol,
                  command=lambda v: self.vol.set(round(float(v)))).pack(side="left", fill="x", expand=True)
        ttk.Label(vf, textvariable=self.vol, width=3, anchor="e").pack(side="left")
        ttk.Label(f, text="7 = 처음 들어보신 크기. 늘 아주 작게 시작해 천천히 커집니다.",
                  style="Sub.TLabel", wraplength=S(320)).grid(row=6, column=0, columnspan=3, sticky="w",
                                                              pady=(S(4), 0))

        self.anim = tk.BooleanVar(value=s.get("wave_anim", True))
        ttk.Checkbutton(f, text="업무 중 물결이 천천히 흐르기", variable=self.anim).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(S(14), 0))

        bf = ttk.Frame(f)
        bf.grid(row=8, column=0, columnspan=3, sticky="we", pady=(S(26), 0))
        PillButton(bf, "저장", self.save, "primary", height=40).pack(side="right", fill="x", expand=True,
                                                                  padx=(S(4), 0))
        PillButton(bf, "취소", self.close, "soft", height=40).pack(side="right", fill="x", expand=True,
                                                                padx=(0, S(4)))
        w.protocol("WM_DELETE_WINDOW", self.close)

    def fill_combo(self, key):
        cur = self.sounds[key]
        opts = list(timer_sound.BUILTIN.values()) + ["내 소리 파일 고르기…", "소리 없음"]
        if cur not in timer_sound.BUILTIN and cur != "none":
            opts.insert(2, sound_label(cur))
        self.combos[key]["values"] = opts
        self.combos[key].set(sound_label(cur))

    def on_pick(self, key):
        v = self.combos[key].get()
        rev = {lbl: k for k, lbl in timer_sound.BUILTIN.items()}
        if v in rev:
            self.sounds[key] = rev[v]
        elif v == "소리 없음":
            self.sounds[key] = "none"
        elif v == "내 소리 파일 고르기…":
            path = filedialog.askopenfilename(parent=self.win, title="소리 파일 (.wav)",
                                              filetypes=[("WAV 소리", "*.wav")])
            if path:
                self.sounds[key] = path
        self.fill_combo(key)

    def preview(self, key):
        timer_sound.stop()
        timer_sound.play(self.sounds[key], self.vol.get())

    def save(self):
        try:
            work, brk = float(self.work.get()), float(self.brk.get())
        except ValueError:
            messagebox.showerror("설정", "시간은 숫자로 넣어 주세요.", parent=self.win)
            return
        work = int(work) if work >= 1 else work
        brk = int(brk) if brk >= 1 else brk
        app = self.app
        app.s.update({"work_min": max(0.05, work), "break_min": max(0.05, brk), "volume": self.vol.get(),
                      "wave_anim": bool(self.anim.get()), **self.sounds})
        save_settings(app.s)
        timer_sound.prepare_async(["chime", "musicbox"], app.s["volume"])
        if app.phase == "idle":
            app.total = app.remain = app.s["work_min"] * 60.0
        self.close()

    def close(self):
        timer_sound.stop()
        self.win.grab_release()
        self.win.destroy()


# ───────────────────────── 기록 보기

class LogWindow:
    COLS = [("시작", 64), ("끝", 64), ("집중", 56), ("할 일", 210), ("한 일", 210), ("휴식", 130)]

    def __init__(self, app):
        self.app = app
        w = self.win = styled_toplevel(app, "항해 기록", 820, 520)
        f = ttk.Frame(w, padding=(S(24), S(20)))
        f.pack(fill="both", expand=True)

        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="항해 기록", style="Head.TLabel").pack(side="left")
        PillButton(top, "엑셀로 열기", self.open_csv, "soft", width=104, height=34,
                   font=(F.ui, 9, "bold"), radius=10).pack(side="right")
        self.day = ttk.Combobox(top, state="readonly", width=13)
        self.day.pack(side="right", padx=S(10))
        self.day.bind("<<ComboboxSelected>>", lambda e: self.fill())

        self.summary = ttk.Label(f, style="Sub.TLabel")
        self.summary.pack(anchor="w", pady=(S(6), S(12)))
        tk.Frame(f, bg=C.line, height=1).pack(fill="x")

        tf = ttk.Frame(f)
        tf.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tf, columns=[c for c, _ in self.COLS], show="headings")
        for c, width in self.COLS:
            self.tree.heading(c, text=c, anchor="w")
            self.tree.column(c, width=S(width), anchor="w", stretch=c in ("할 일", "한 일"))
        self.tree.tag_configure("odd", background="#fafbfc")
        self.tree.tag_configure("skip", foreground=C.warn)
        self.tree.tag_configure("day", background=C.bg, foreground=C.sub, font=(F.ui, 9, "bold"))
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit())
        ttk.Label(f, text="줄을 두 번 누르면 할 일 · 한 일을 고칠 수 있어요", style="Sub.TLabel").pack(
            anchor="w", pady=(S(10), 0))

        days = sorted({r["날짜"] for r in app.rows}, reverse=True)
        self.day["values"] = ["전체 보기"] + days
        today = dt.date.today().strftime("%Y-%m-%d")
        self.day.set(today if today in days else (days[0] if days else "전체 보기"))
        self.fill()

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        d = self.day.get()
        idx = [i for i, r in enumerate(self.app.rows) if d == "전체 보기" or r["날짜"] == d]
        last_day = None
        for n, i in enumerate(reversed(idx)):
            r = self.app.rows[i]
            if d == "전체 보기" and r["날짜"] != last_day:
                last_day = r["날짜"]
                y, m, dd = last_day.split("-")
                wd = WEEKDAYS[dt.date(int(y), int(m), int(dd)).weekday()]
                self.tree.insert("", "end", values=[f"{int(m)}월 {int(dd)}일 ({wd})", "", "", "", "", ""],
                                 tags=("day",))
            tags = ["odd"] if n % 2 else []
            if r["휴식"].startswith("건너뜀"):
                tags.append("skip")
            mins = f"{r['집중(분)']}분" if r["집중(분)"] else ""
            self.tree.insert("", "end", iid=str(i), tags=tags,
                             values=[r["시작"], r["끝"], mins, r["할 일"], r["한 일"], r["휴식"]])
        done = [self.app.rows[i] for i in idx if self.app.rows[i]["집중(분)"]]
        mins = sum(int(r["집중(분)"] or 0) for r in done)
        skipped = sum(1 for r in done if r["휴식"].startswith("건너뜀"))
        self.summary.configure(text=f"도착한 섬 {len(done)}개   ·   집중 {fmt_minutes(mins)}   ·   "
                                    f"휴식 건너뜀 {skipped}회")

    def edit(self):
        sel = self.tree.selection()
        if not sel or not sel[0].isdigit():
            return
        row = self.app.rows[int(sel[0])]
        d = styled_toplevel(self.app, "기록 고치기", 420)
        d.transient(self.win)
        d.grab_set()
        f = ttk.Frame(d, padding=(S(22), S(18)))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"{row['날짜']}  {row['시작']} ~ {row['끝']}", style="Sub.TLabel").pack(anchor="w")
        entries = {}
        for k in ("할 일", "한 일"):
            ttk.Label(f, text=k).pack(anchor="w", pady=(S(12), S(4)))
            p = RoundPanel(f, height=40, pad=(12, 10))
            p.pack(fill="x")
            e = p.hold(HintEntry(p, "비어 있음"))
            e.set_value(row[k])
            entries[k] = e

        def ok():
            for k, e in entries.items():
                row[k] = e.value()
            self.app.rows_dirty = True
            self.app.flush_rows()
            d.destroy()
            self.fill()

        PillButton(f, "저장", ok, "primary", height=38).pack(fill="x", pady=(S(18), 0))

    def open_csv(self):
        self.app.flush_rows()
        if not os.path.exists(LOG_FILE):
            messagebox.showinfo("기록", "아직 기록이 없어요.", parent=self.win)
            return
        open_file(LOG_FILE)


def main():
    global SCALE
    enable_dpi_awareness()
    root = tk.Tk()
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96)
    F.pick(root)
    setup_ttk(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
