"""내 전용 업무 타이머.

- 항상 맨 위에 떠 있는 작은 창: 날짜·요일·시각, 남은 시간, ⛵ 항해 진행바, 오늘 도착한 섬 수, 메모
- 50분 업무 → 풍경 소리 + 화면 전체를 덮는 휴식 창(천천히 숨 쉬듯 색이 변함) 10분
- 휴식이 끝나면 오르골 소리 → '다시 집중 시작'을 눌러야 다음 업무 시작
- 사이클마다 '할 일'(시작할 때)과 '한 일'(휴식 때)을 한 줄씩 기록, 날짜별로 모아 보기
"""

import csv
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

import timer_sound

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "timer_settings.json")
MEMO_FILE = os.path.join(HERE, "timer_memo.txt")
LOG_FILE = os.path.join(HERE, "timer_log.csv")

FONT = "맑은 고딕"
EMOJI_FONT = "Segoe UI Emoji"
WEEKDAYS = "월화수목금토일"

DEFAULTS = {
    "work_min": 50,
    "break_min": 10,
    "work_end_sound": "chime",      # 업무 끝 → 풍경
    "break_end_sound": "musicbox",  # 휴식 끝 → 오르골
    "volume": 7,
    "geometry": "",
}

LOG_FIELDS = ["날짜", "시작", "끝", "집중(분)", "할 일", "한 일", "휴식"]

TIPS = [
    "자리에서 일어나 기지개를 한 번 켜 보세요",
    "물 한 잔 천천히 마셔 보세요",
    "창밖 먼 곳을 20초 동안 바라보세요",
    "어깨와 목을 천천히 돌려 보세요",
    "눈을 감고 숨을 크게 다섯 번 쉬어 보세요",
    "잠깐 걸으면서 몸을 풀어 보세요",
]

# 색
SEA = "#d6ecfa"
WAKE = "#93cbee"
REST_TRACK = "#dcefe2"
REST_FILL = "#a9d9b8"
BREATH = {
    "break": ("#e4f4e8", "#b9e0c6"),       # 휴식 중: 부드러운 초록
    "break_done": ("#fdeee2", "#f5cfb0"),  # 휴식 끝: 따뜻한 살구색
}


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


def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def open_file(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
    except Exception as e:
        messagebox.showerror("열기 실패", str(e))


# ───────────────────────── 메인 창

class App:
    def __init__(self, root):
        self.root = root
        self.s = load_settings()
        self.rows = load_rows()
        self.rows_dirty = False

        self.phase = "idle"       # idle / work / break / break_done
        self.paused = False
        self.end_at = 0.0         # 진행 중일 때 끝나는 시각(monotonic)
        self.remain = self.s["work_min"] * 60.0
        self.total = self.remain  # 이번 단계 전체 길이(초)
        self.cur = None           # 이번 사이클 기록(dict, self.rows 안의 같은 객체)
        self.overlay = None
        self.compact = False
        self.memo_job = None

        timer_sound.prepare_async(["chime", "musicbox"], self.s["volume"])

        root.title("업무 타이머")
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.configure(bg="white")
        if self.s.get("geometry"):
            try:
                root.geometry(self.s["geometry"])
            except tk.TclError:
                pass
        else:
            sw = root.winfo_screenwidth()
            root.geometry(f"330x640+{sw - 350}+20")
        root.minsize(250, 120)

        style = ttk.Style()
        style.configure(".", font=(FONT, 10))
        style.configure("Big.TButton", font=(FONT, 11, "bold"), padding=5)

        self.build()
        self.load_memo()
        self.refresh_stats()
        self.tick()

    # ── 화면 구성
    def build(self):
        r = self.root
        bg = "white"
        self.layout = []  # (위젯, pack 옵션, 접힌 모드에서도 보이는지)

        def place(w, compact=False, **opts):
            self.layout.append((w, opts, compact))

        top = tk.Frame(r, bg=bg)
        self.date_lbl = tk.Label(top, font=(FONT, 11), bg=bg, fg="#333")
        self.date_lbl.pack(side="left")
        self.clock_lbl = tk.Label(top, font=(FONT, 11, "bold"), bg=bg, fg="#333")
        self.clock_lbl.pack(side="right")
        place(top, fill="x", padx=12, pady=(10, 0))

        self.status_lbl = tk.Label(r, font=(FONT, 11, "bold"), bg=bg)
        place(self.status_lbl, pady=(8, 0))

        self.time_lbl = tk.Label(r, font=(FONT, 34, "bold"), bg=bg, fg="#1f3b57")
        place(self.time_lbl, compact=True, pady=(0, 2))

        self.bar = tk.Canvas(r, height=40, bg=bg, highlightthickness=0)
        self.bar.bind("<Configure>", lambda e: self.draw_bar())
        place(self.bar, compact=True, fill="x", padx=12)

        self.expand_btn = ttk.Button(r, text="▢ 펼치기", command=self.toggle_compact)
        self.layout.append((self.expand_btn, {"pady": (4, 6)}, "only"))

        pf = tk.Frame(r, bg=bg)
        tk.Label(pf, text="이번 항해에서 할 일", font=(FONT, 9), bg=bg, fg="#666").pack(anchor="w")
        self.plan_var = tk.StringVar()
        ttk.Entry(pf, textvariable=self.plan_var, font=(FONT, 10)).pack(fill="x")
        place(pf, fill="x", padx=12, pady=(10, 0))

        bf = tk.Frame(r, bg=bg)
        self.btn_main = ttk.Button(bf, text="▶ 시작", style="Big.TButton", command=self.on_main_button)
        self.btn_reset = ttk.Button(bf, text="↺ 리셋", command=self.reset)
        self.btn_fold = ttk.Button(bf, text="▁ 접기", command=self.toggle_compact)
        self.btn_main.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self.btn_reset.pack(side="left", padx=3)
        self.btn_fold.pack(side="left", padx=(3, 0))
        place(bf, fill="x", padx=12, pady=8)

        self.stats_lbl = tk.Label(r, font=(FONT, 10), bg=bg, fg="#333")
        place(self.stats_lbl)

        mf = tk.Frame(r, bg=bg)
        tk.Label(mf, text="메모 (자동 저장)", font=(FONT, 9), bg=bg, fg="#666").pack(anchor="w")
        self.memo = tk.Text(mf, height=8, font=(FONT, 10), wrap="word", relief="solid", bd=1,
                            undo=True)
        self.memo.pack(fill="both", expand=True)
        self.memo.bind("<<Modified>>", self.on_memo_change)
        place(mf, fill="both", expand=True, padx=12, pady=(8, 0))

        lf = tk.Frame(r, bg=bg)
        ttk.Button(lf, text="📒 기록 보기", command=self.open_log).pack(side="left", expand=True, fill="x",
                                                                     padx=(0, 3))
        ttk.Button(lf, text="⚙ 설정", command=self.open_settings).pack(side="left", expand=True, fill="x",
                                                                    padx=(3, 0))
        place(lf, fill="x", padx=12, pady=10)

        self.apply_layout()

    def apply_layout(self):
        for w, _, _ in self.layout:
            w.pack_forget()
        for w, opts, compact in self.layout:
            show = (compact in (True, "only")) if self.compact else (compact != "only")
            if show:
                w.pack(**opts)

    def toggle_compact(self):
        if not self.compact:
            self.full_geometry = self.root.geometry()
        self.compact = not self.compact
        self.apply_layout()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if self.compact:
            self.time_lbl.configure(font=(FONT, 22, "bold"))
            self.root.geometry(f"240x150+{x}+{y}")
        else:
            self.time_lbl.configure(font=(FONT, 34, "bold"))
            size = getattr(self, "full_geometry", "330x640").split("+")[0]
            self.root.geometry(f"{size}+{x}+{y}")

    # ── 타이머
    def remaining(self):
        if self.phase in ("work", "break") and not self.paused:
            return max(0.0, self.end_at - time.monotonic())
        return self.remain

    def tick(self):
        now = dt.datetime.now()
        self.date_lbl.configure(text=f"{now:%Y.%m.%d} ({WEEKDAYS[now.weekday()]})")
        self.clock_lbl.configure(text=f"{now:%H:%M:%S}")
        if getattr(self, "_today", None) != now.date():
            self._today = now.date()
            self.refresh_stats()

        if self.phase == "work" and not self.paused and self.remaining() <= 0:
            self.finish_work()
        elif self.phase == "break" and self.remaining() <= 0:
            self.finish_break()

        rem = self.remaining()
        self.time_lbl.configure(text=fmt_clock(rem))
        self.update_status()
        self.draw_bar()
        if self.overlay:
            self.overlay.update_time(rem)
        if self.rows_dirty:
            self.flush_rows()
        self.root.after(200, self.tick)

    def update_status(self):
        if self.phase == "idle":
            text, color = "대기 중 · 출항 준비", "#666"
        elif self.phase == "work":
            text, color = ("⏸ 일시정지", "#b35900") if self.paused else ("⛵ 항해 중 (집중)", "#0969da")
        elif self.phase == "break":
            text, color = "⚓ 섬에서 휴식 중", "#1a7f37"
        else:
            text, color = "🌅 휴식 끝 · 출항 대기", "#b35900"
        self.status_lbl.configure(text=text, fg=color)
        self.root.title(f"{fmt_clock(self.remaining())} · {text.split(' ', 1)[-1]}"
                        if self.phase != "idle" else "업무 타이머")

    def draw_bar(self):
        c = self.bar
        c.delete("all")
        w, h = c.winfo_width(), int(c["height"])
        if w < 40:
            return
        resting = self.phase in ("break", "break_done")
        frac = 0.0 if not self.total else 1 - self.remaining() / self.total
        frac = max(0.0, min(1.0, frac))
        x0, x1 = 4, w - 34  # 오른쪽 끝에 섬 자리
        y0, y1 = 9, h - 9
        r = (y1 - y0) / 2
        track, fill = (REST_TRACK, REST_FILL) if resting else (SEA, WAKE)

        def pill(xa, xb, color):
            if xb - xa < 2 * r:
                xb = xa + 2 * r
            c.create_oval(xa, y0, xa + 2 * r, y1, fill=color, outline=color)
            c.create_oval(xb - 2 * r, y0, xb, y1, fill=color, outline=color)
            c.create_rectangle(xa + r, y0, xb - r, y1, fill=color, outline=color)

        pill(x0, x1, track)
        bx = x0 + (x1 - x0) * frac
        if frac > 0:
            pill(x0, max(bx, x0 + 2 * r), fill)
        c.create_text(w - 16, h / 2, text="🏝", font=(EMOJI_FONT, 17))
        if resting:
            c.create_text(x1 - 12, h / 2, text="⚓", font=(EMOJI_FONT, 15))
        else:
            c.create_text(min(max(bx, x0 + 12), x1 - 12), h / 2 - 2, text="⛵", font=(EMOJI_FONT, 17))

    def on_main_button(self):
        if self.phase == "idle":
            self.start_work()
        elif self.phase == "work":
            self.toggle_pause()
        elif self.phase == "break_done":
            self.start_work()

    def start_work(self):
        mins = float(self.s["work_min"])
        now = dt.datetime.now()
        self.cur = {"날짜": now.strftime("%Y-%m-%d"), "시작": now.strftime("%H:%M"), "끝": "",
                    "집중(분)": "", "할 일": self.plan_var.get().strip(), "한 일": "", "휴식": ""}
        self.cur_minutes = mins
        self.phase, self.paused = "work", False
        self.total = mins * 60.0
        self.end_at = time.monotonic() + self.total
        self.btn_main.configure(text="⏸ 일시정지", state="normal")
        self.btn_reset.configure(state="normal")

    def toggle_pause(self):
        if self.phase != "work":
            return
        if self.paused:
            self.end_at = time.monotonic() + self.remain
            self.paused = False
            self.btn_main.configure(text="⏸ 일시정지")
        else:
            self.remain = self.remaining()
            self.paused = True
            self.btn_main.configure(text="▶ 계속")

    def reset(self):
        if self.phase == "work":
            done = self.total - self.remaining()
            if done > 60 and not messagebox.askyesno(
                    "리셋", "진행 중인 항해를 처음부터 다시 할까요?\n(이번 사이클은 기록되지 않습니다)",
                    parent=self.root):
                return
        self.phase, self.paused, self.cur = "idle", False, None
        self.total = self.remain = self.s["work_min"] * 60.0
        self.btn_main.configure(text="▶ 시작", state="normal")

    def finish_work(self):
        now = dt.datetime.now()
        self.cur["할 일"] = self.plan_var.get().strip() or self.cur["할 일"]
        self.cur.update({"끝": now.strftime("%H:%M"), "집중(분)": str(round(self.cur_minutes)), "휴식": "휴식 중"})
        self.rows.append(self.cur)
        self.rows_dirty = True
        self.refresh_stats()

        self.phase = "break"
        self.total = self.s["break_min"] * 60.0
        self.end_at = time.monotonic() + self.total
        self.btn_main.configure(text="⚓ 휴식 중", state="disabled")
        self.btn_reset.configure(state="disabled")
        timer_sound.play(self.s["work_end_sound"], self.s["volume"])
        self.overlay = BreakOverlay(self)

    def finish_break(self):
        self.phase = "break_done"
        self.remain = 0.0
        if self.cur and self.cur["휴식"] == "휴식 중":
            self.cur["휴식"] = "완료"
            self.rows_dirty = True
        timer_sound.play(self.s["break_end_sound"], self.s["volume"])
        self.btn_main.configure(text="⛵ 다시 집중 시작", state="normal")
        if self.overlay:
            self.overlay.show_done()

    def skip_break(self):
        """휴식을 끝까지 하지 않고 바로 다음 항해로 (기록에 남는다)."""
        left = max(1, round(self.remaining() / 60))
        if self.cur:
            self.cur["휴식"] = f"건너뜀 ({left}분 남기고)"
            self.rows_dirty = True
        self.close_overlay()
        self.plan_var.set("")
        self.start_work()

    def resume_from_overlay(self, next_plan):
        self.close_overlay()
        self.plan_var.set(next_plan)
        self.start_work()

    def close_overlay(self):
        if self.overlay:
            if self.cur:
                self.cur["한 일"] = self.overlay.result_var.get().strip()
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
        text = f"오늘 도착한 섬 🏝×{n}  ·  집중 {fmt_minutes(mins)}"
        if skipped:
            text += f"\n휴식 건너뜀 {skipped}회"
        self.stats_lbl.configure(text=text, fg="#b35900" if skipped else "#333")

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
        if self.memo_job:
            self.root.after_cancel(self.memo_job)
        self.memo_job = self.root.after(800, self.save_memo)

    def save_memo(self):
        self.memo_job = None
        try:
            with open(MEMO_FILE, "w", encoding="utf-8") as f:
                f.write(self.memo.get("1.0", "end-1c"))
        except OSError:
            pass

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
        if self.phase == "work":
            self.cur = None  # 다 못 채운 사이클은 기록하지 않음
        self.save_memo()
        self.flush_rows()
        if not self.compact:
            self.s["geometry"] = self.root.geometry()
        save_settings(self.s)
        timer_sound.stop()
        self.root.destroy()


# ───────────────────────── 휴식 화면 (전체 화면)

class BreakOverlay:
    PERIOD = 6.0  # 숨 한 번(밝아졌다 어두워지는) 길이, 초

    def __init__(self, app):
        self.app = app
        self.mode = "break"
        self.t0 = time.monotonic()
        w = self.win = tk.Toplevel(app.root)
        w.title("쉬는 시간")
        w.geometry(f"{w.winfo_screenwidth()}x{w.winfo_screenheight()}+0+0")
        w.attributes("-fullscreen", True)
        w.attributes("-topmost", True)
        w.protocol("WM_DELETE_WINDOW", lambda: None)  # 닫기·Alt+F4 무시
        self.colored = []

        def lbl(parent, **kw):
            x = tk.Label(parent, **kw)
            self.colored.append(x)
            return x

        box = tk.Frame(w)
        box.place(relx=0.5, rely=0.45, anchor="center")
        self.colored += [w, box]

        self.title = lbl(box, font=(FONT, 30, "bold"), fg="#24452f")
        self.title.pack(pady=(0, 6))
        self.sub = lbl(box, font=(FONT, 15), fg="#3d5c47")
        self.sub.pack()
        self.time = lbl(box, font=(FONT, 72, "bold"), fg="#24452f")
        self.time.pack(pady=10)
        self.tip = lbl(box, text="☕ " + random.choice(TIPS), font=(FONT, 15), fg="#3d5c47")
        self.tip.pack(pady=(0, 24))

        self.form = tk.Frame(box)
        self.colored.append(self.form)
        self.form.pack(fill="x")
        plan = app.cur["할 일"] if app.cur else ""
        self.plan_lbl = lbl(self.form, text=f"계획했던 일: {plan}" if plan else "",
                            font=(FONT, 12), fg="#555")
        self.plan_lbl.pack(anchor="w")
        lbl(self.form, text="이번 항해에서 한 일 (한 줄, 비워도 돼요)", font=(FONT, 12), fg="#333"
            ).pack(anchor="w", pady=(4, 2))
        self.result_var = tk.StringVar()
        self.result_entry = tk.Entry(self.form, textvariable=self.result_var, font=(FONT, 14), width=46,
                                     relief="solid", bd=1)
        self.result_entry.pack(fill="x", ipady=4)

        self.next_frame = tk.Frame(box)
        self.colored.append(self.next_frame)
        lbl(self.next_frame, text="다음 항해에서 할 일 (비워도 돼요)", font=(FONT, 12), fg="#333"
            ).pack(anchor="w", pady=(16, 2))
        self.next_var = tk.StringVar()
        self.next_entry = tk.Entry(self.next_frame, textvariable=self.next_var, font=(FONT, 14),
                                   relief="solid", bd=1)
        self.next_entry.pack(fill="x", ipady=4)
        self.next_entry.bind("<Return>", lambda e: self.resume())
        self.go_btn = tk.Button(self.next_frame, text="⛵  다시 집중 시작", font=(FONT, 18, "bold"),
                                bg="#2f6f9f", fg="white", activebackground="#24577e",
                                activeforeground="white", relief="flat", padx=30, pady=10,
                                command=self.resume)
        self.go_btn.pack(pady=(18, 0))

        self.skip_btn = tk.Button(w, text="급하게 계속하기…", font=(FONT, 10), fg="#777", relief="flat",
                                  bd=0, command=self.ask_skip)
        self.skip_btn.place(relx=0.5, rely=0.94, anchor="center")

        n, mins, _ = app.today_stats()
        self.set_texts("⚓ 섬에 도착했어요", f"오늘 {n}번째 항해 완료 · 집중 {fmt_minutes(mins)}")
        self.breathe()
        self.keep_on_top()
        w.after(300, lambda: (w.focus_force(), self.result_entry.focus_set()))

    def set_texts(self, title, sub):
        self.title.configure(text=title)
        self.sub.configure(text=sub)

    def update_time(self, rem):
        if self.mode == "break":
            self.time.configure(text=fmt_clock(rem))

    def show_done(self):
        self.mode = "break_done"
        self.set_texts("🌅 다시 출항할 시간이에요", "충분히 쉬었다면 천천히 시작해요")
        self.time.configure(text="")
        self.tip.configure(text="")
        self.skip_btn.place_forget()
        self.next_frame.pack(fill="x")
        self.next_entry.focus_set()

    def breathe(self):
        if not self.win.winfo_exists():
            return
        a, b = BREATH[self.mode]
        t = (1 - math.cos(2 * math.pi * (time.monotonic() - self.t0) / self.PERIOD)) / 2
        color = mix(a, b, t)
        for x in self.colored:
            x.configure(bg=color)
        self.skip_btn.configure(bg=color, activebackground=color)
        self.win.after(60, self.breathe)

    def keep_on_top(self):
        """다른 창을 띄워도 휴식 화면이 다시 맨 위로 온다."""
        if not self.win.winfo_exists():
            return
        if not getattr(self, "asking", False):
            self.win.attributes("-topmost", True)
            self.win.lift()
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
            self.app.resume_from_overlay(self.next_var.get().strip())

    def destroy(self):
        if self.win.winfo_exists():
            self.win.destroy()


# ───────────────────────── 설정

class SettingsWindow:
    def __init__(self, app):
        self.app = app
        s = app.s
        w = self.win = tk.Toplevel(app.root)
        w.title("설정")
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.transient(app.root)
        w.grab_set()
        f = ttk.Frame(w, padding=16)
        f.pack(fill="both")

        self.work = tk.IntVar(value=s["work_min"])
        self.brk = tk.IntVar(value=s["break_min"])
        self.vol = tk.IntVar(value=s["volume"])
        self.sounds = {"work_end_sound": s["work_end_sound"], "break_end_sound": s["break_end_sound"]}

        ttk.Label(f, text="업무 시간(분)").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Spinbox(f, from_=1, to=180, textvariable=self.work, width=6).grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="휴식 시간(분)").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Spinbox(f, from_=1, to=60, textvariable=self.brk, width=6).grid(row=1, column=1, sticky="w")

        self.combos = {}
        for i, (key, label) in enumerate([("work_end_sound", "업무 끝 소리"),
                                          ("break_end_sound", "휴식 끝 소리")]):
            row = 2 + i
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=4)
            cb = ttk.Combobox(f, state="readonly", width=18)
            cb.grid(row=row, column=1, sticky="w")
            cb.bind("<<ComboboxSelected>>", lambda e, k=key: self.on_pick(k))
            self.combos[key] = cb
            self.fill_combo(key)
            ttk.Button(f, text="▶ 들어보기", command=lambda k=key: self.preview(k)).grid(
                row=row, column=2, padx=(6, 0))

        ttk.Label(f, text="소리 크기").grid(row=4, column=0, sticky="w", pady=4)
        vf = ttk.Frame(f)
        vf.grid(row=4, column=1, columnspan=2, sticky="w")
        ttk.Scale(vf, from_=1, to=10, variable=self.vol, length=150,
                  command=lambda v: self.vol.set(round(float(v)))).pack(side="left")
        ttk.Label(vf, textvariable=self.vol, width=3).pack(side="left", padx=4)
        ttk.Label(f, text="7 = 처음 들어보신 크기. 소리는 늘 아주 작게 시작해 천천히 커집니다.",
                  foreground="#777").grid(row=5, column=0, columnspan=3, sticky="w", pady=(0, 8))

        bf = ttk.Frame(f)
        bf.grid(row=6, column=0, columnspan=3, sticky="e")
        ttk.Button(bf, text="취소", command=self.close).pack(side="right")
        ttk.Button(bf, text="저장", command=self.save).pack(side="right", padx=6)
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
            work, brk = int(self.work.get()), int(self.brk.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("설정", "시간은 숫자로 넣어 주세요.", parent=self.win)
            return
        app = self.app
        app.s.update({"work_min": max(1, work), "break_min": max(1, brk), "volume": self.vol.get(),
                      **self.sounds})
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
    COLS = [("날짜", 90), ("시작", 55), ("끝", 55), ("집중(분)", 60), ("할 일", 220), ("한 일", 220),
            ("휴식", 130)]

    def __init__(self, app):
        self.app = app
        w = self.win = tk.Toplevel(app.root)
        w.title("항해 기록")
        w.attributes("-topmost", True)
        w.geometry("880x480")
        f = ttk.Frame(w, padding=10)
        f.pack(fill="both", expand=True)

        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="날짜").pack(side="left")
        self.day = ttk.Combobox(top, state="readonly", width=14)
        self.day.pack(side="left", padx=6)
        self.day.bind("<<ComboboxSelected>>", lambda e: self.fill())
        self.summary = ttk.Label(top)
        self.summary.pack(side="left", padx=12)
        ttk.Button(top, text="엑셀로 열기", command=self.open_csv).pack(side="right")

        tf = ttk.Frame(f)
        tf.pack(fill="both", expand=True, pady=8)
        self.tree = ttk.Treeview(tf, columns=[c for c, _ in self.COLS], show="headings")
        for c, width in self.COLS:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=width, anchor="w" if c in ("할 일", "한 일", "휴식") else "center")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit())
        ttk.Label(f, text="줄을 두 번 누르면 '할 일 / 한 일'을 고칠 수 있어요.", foreground="#777").pack(anchor="w")

        days = sorted({r["날짜"] for r in app.rows}, reverse=True)
        self.day["values"] = ["전체"] + days
        today = dt.date.today().strftime("%Y-%m-%d")
        self.day.set(today if today in days else (days[0] if days else "전체"))
        self.fill()

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        d = self.day.get()
        self.shown = [r for r in self.app.rows if d == "전체" or r["날짜"] == d]
        for i, r in enumerate(reversed(self.shown)):
            self.tree.insert("", "end", iid=str(len(self.shown) - 1 - i), values=[r[c] for c, _ in self.COLS])
        done = [r for r in self.shown if r["집중(분)"]]
        mins = sum(int(r["집중(분)"] or 0) for r in done)
        skipped = sum(1 for r in done if r["휴식"].startswith("건너뜀"))
        self.summary.configure(text=f"도착한 섬 {len(done)}개 · 집중 {fmt_minutes(mins)} · "
                                    f"휴식 건너뜀 {skipped}회")

    def edit(self):
        sel = self.tree.selection()
        if not sel:
            return
        row = self.shown[int(sel[0])]
        d = tk.Toplevel(self.win)
        d.title("기록 고치기")
        d.attributes("-topmost", True)
        d.transient(self.win)
        d.grab_set()
        f = ttk.Frame(d, padding=14)
        f.pack(fill="both")
        ttk.Label(f, text=f"{row['날짜']} {row['시작']}~{row['끝']}").pack(anchor="w")
        vals = {}
        for k in ("할 일", "한 일"):
            ttk.Label(f, text=k).pack(anchor="w", pady=(8, 0))
            vals[k] = tk.StringVar(value=row[k])
            ttk.Entry(f, textvariable=vals[k], width=60).pack(fill="x")

        def ok():
            for k, v in vals.items():
                row[k] = v.get().strip()
            self.app.rows_dirty = True
            self.app.flush_rows()
            d.destroy()
            self.fill()

        ttk.Button(f, text="저장", command=ok).pack(anchor="e", pady=(12, 0))

    def open_csv(self):
        self.app.flush_rows()
        if not os.path.exists(LOG_FILE):
            messagebox.showinfo("기록", "아직 기록이 없어요.", parent=self.win)
            return
        open_file(LOG_FILE)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
