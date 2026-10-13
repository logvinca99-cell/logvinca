"""찜 클릭기 조작 창.

크롬보다 항상 위에 떠 있는 작은 창에서 스토어 주소 입력, 시작/일시정지/종료,
진행률과 성공·실패 개수, 지금 누르는 상품, 기록을 보여준다.
브라우저 작업은 별도 스레드에서 돌고, 화면과는 큐로만 주고받는다.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import zzim

FONT = "맑은 고딕"
COLORS = {"ok": "#1a7f37", "info": "#444444", "warn": "#b35900", "err": "#cf222e"}
STATUS_COLORS = {"대기": "#666666", "로그인 대기": "#b35900", "스토어 여는 중": "#0969da",
                 "진행 중": "#1a7f37", "일시정지": "#b35900", "완료": "#0969da",
                 "중단": "#b35900", "오류": "#cf222e"}


def fmt_time(sec):
    if sec is None:
        return "-"
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}시간 {m:02d}분" if h else f"{m}분 {s:02d}초"


class App:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.q = queue.Queue()
        self.ctl = None
        self.worker = None
        self.closing = False

        root.title("스마트스토어 찜 클릭기")
        sw = root.winfo_screenwidth()
        root.geometry(f"440x700+{sw - 460}+30")  # 화면 오른쪽 위
        root.minsize(400, 560)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        style = ttk.Style()
        style.configure(".", font=(FONT, 10))
        style.configure("Big.TButton", font=(FONT, 11, "bold"), padding=6)
        style.configure("green.Horizontal.TProgressbar", thickness=22)

        pad = {"padx": 12}

        # ── 스토어 주소
        ttk.Label(root, text="스토어 주소 (여러 개면 한 줄에 하나)").pack(anchor="w", pady=(12, 2), **pad)
        self.store_box = tk.Text(root, height=3, font=(FONT, 10), relief="solid", bd=1)
        self.store_box.pack(fill="x", **pad)
        if args.store:
            self.store_box.insert("1.0", args.store)

        # ── 버튼
        bf = ttk.Frame(root)
        bf.pack(fill="x", pady=10, **pad)
        self.btn_start = ttk.Button(bf, text="▶ 시작", style="Big.TButton", command=self.start)
        self.btn_pause = ttk.Button(bf, text="⏸ 일시정지", style="Big.TButton",
                                    command=self.toggle_pause, state="disabled")
        self.btn_stop = ttk.Button(bf, text="■ 종료", style="Big.TButton",
                                   command=self.stop, state="disabled")
        for b in (self.btn_start, self.btn_pause, self.btn_stop):
            b.pack(side="left", expand=True, fill="x", padx=2)

        # ── 상태
        self.status_var = tk.StringVar(value="대기")
        self.status_lbl = tk.Label(root, textvariable=self.status_var, font=(FONT, 14, "bold"),
                                   fg=STATUS_COLORS["대기"])
        self.status_lbl.pack(anchor="w", **pad)

        # ── 진행률
        self.progress_var = tk.StringVar(value="0 / 0  (0%)")
        tk.Label(root, textvariable=self.progress_var, font=(FONT, 20, "bold")).pack(anchor="w", **pad)
        self.bar = ttk.Progressbar(root, style="green.Horizontal.TProgressbar", maximum=100)
        self.bar.pack(fill="x", pady=(2, 8), **pad)

        # ── 숫자 칸
        grid = ttk.Frame(root)
        grid.pack(fill="x", **pad)
        self.nums = {}
        for i, (key, label, color) in enumerate([
            ("clicked", "성공", COLORS["ok"]), ("already", "이미 찜", COLORS["info"]),
            ("failed", "실패", COLORS["err"]), ("remain", "남음", "#0969da"),
        ]):
            cell = tk.Frame(grid, bd=1, relief="solid", bg="white")
            cell.grid(row=0, column=i, sticky="nsew", padx=2)
            grid.columnconfigure(i, weight=1)
            tk.Label(cell, text=label, bg="white", fg="#666", font=(FONT, 9)).pack(pady=(4, 0))
            v = tk.StringVar(value="0")
            tk.Label(cell, textvariable=v, bg="white", fg=color, font=(FONT, 16, "bold")).pack(pady=(0, 4))
            self.nums[key] = v

        # ── 현재 상품 / 시간
        info = ttk.Frame(root)
        info.pack(fill="x", pady=8, **pad)
        self.pos_var = tk.StringVar(value="지금: -")
        self.name_var = tk.StringVar(value="")
        self.time_var = tk.StringVar(value="경과 -   ·   남은 시간 약 -")
        ttk.Label(info, textvariable=self.pos_var, font=(FONT, 10, "bold")).pack(anchor="w")
        ttk.Label(info, textvariable=self.name_var, foreground="#444").pack(anchor="w")
        ttk.Label(info, textvariable=self.time_var, foreground="#666").pack(anchor="w", pady=(4, 0))

        # ── 기록
        lf = ttk.Frame(root)
        lf.pack(fill="both", expand=True, **pad)
        ttk.Label(lf, text="기록").pack(anchor="w")
        self.logbox = tk.Text(lf, height=10, font=(FONT, 9), state="disabled", wrap="none",
                              relief="solid", bd=1)
        sb = ttk.Scrollbar(lf, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logbox.pack(fill="both", expand=True)
        for k, c in COLORS.items():
            self.logbox.tag_configure(k, foreground=c)

        # ── 아래쪽
        ff = ttk.Frame(root)
        ff.pack(fill="x", pady=10, **pad)
        ttk.Button(ff, text="📁 결과 폴더 열기", command=self.open_folder).pack(side="left")
        self.topmost_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(ff, text="항상 위에", variable=self.topmost_var,
                        command=lambda: root.attributes("-topmost", self.topmost_var.get())
                        ).pack(side="right")

        self.root.after(100, self.poll)

    # ── 버튼 동작
    def start(self):
        raw = [l for l in self.store_box.get("1.0", "end").splitlines() if l.strip()]
        if not raw:
            messagebox.showwarning("주소 입력", "스토어 주소를 입력해 주세요.", parent=self.root)
            return
        try:
            stores = [zzim.normalize_store(l) for l in raw]
        except ValueError as e:
            messagebox.showerror("주소 오류", str(e), parent=self.root)
            return
        self.ctl = zzim.Controller(lambda kind, data: self.q.put((kind, data)))
        self.worker = threading.Thread(target=zzim.run_all, args=(stores, self.args, self.ctl),
                                       daemon=True)
        self.worker.start()
        self.store_box.configure(state="disabled")
        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="⏸ 일시정지")
        self.btn_stop.configure(state="normal")
        self.set_status("크롬 여는 중")

    def toggle_pause(self):
        if not self.ctl:
            return
        if self.ctl.paused.is_set():
            self.ctl.paused.clear()
            self.btn_pause.configure(text="⏸ 일시정지")
            self.set_status("진행 중")
        else:
            self.ctl.paused.set()
            self.btn_pause.configure(text="▶ 계속")
            self.set_status("일시정지 대기")  # 지금 누르는 상품이 끝나면 멈춤
            self.add_log("지금 상품까지 처리하고 멈춥니다.", "warn")

    def stop(self):
        if not self.ctl:
            return
        if not messagebox.askyesno("종료", "작업을 끝낼까요?\n지금까지 한 것은 저장되고,\n"
                                         "다시 시작하면 남은 것부터 이어서 합니다.", parent=self.root):
            return
        self.ctl.stopped.set()
        self.btn_pause.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self.set_status("종료 중")

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("닫기", "작업 중입니다. 끝내고 창을 닫을까요?", parent=self.root):
                return
            self.ctl.stopped.set()
            self.closing = True
            self.set_status("종료 중")
            return  # 작업 스레드가 브라우저를 닫고 끝나면 poll에서 창을 닫음
        self.root.destroy()

    def open_folder(self):
        folder = os.getcwd()
        try:
            os.startfile(folder)  # 윈도우
        except AttributeError:
            messagebox.showinfo("결과 폴더", folder, parent=self.root)

    # ── 화면 갱신
    def set_status(self, text):
        self.status_var.set(text)
        self.status_lbl.configure(fg=STATUS_COLORS.get(text, "#333"))

    def add_log(self, text, level="info"):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n", level)
        if int(self.logbox.index("end-1c").split(".")[0]) > 2000:
            self.logbox.delete("1.0", "500.0")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def show_stats(self, s):
        pct = s["done"] / s["total"] * 100 if s["total"] else 0
        self.progress_var.set(f"{s['done']:,} / {s['total']:,}  ({pct:.0f}%)")
        self.bar["value"] = pct
        for k in ("clicked", "already", "failed", "remain"):
            self.nums[k].set(f"{s[k]:,}")
        self.pos_var.set(f"지금: [{s['store']}] {s['pos'] or '-'}")
        self.name_var.set(s["name"])
        pace = f"   ·   간격 {s['pace_ms'] / 1000:.1f}초" if s.get("pace_ms") else ""
        self.time_var.set(f"경과 {fmt_time(s['elapsed'])}   ·   남은 시간 약 {fmt_time(s['eta'])}{pace}")

    def poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.add_log(*data)
                elif kind == "status":
                    self.set_status(data)
                elif kind == "stats":
                    self.show_stats(data)
                elif kind == "finished":
                    self.on_finished(data)
        except queue.Empty:
            pass
        if self.closing and not (self.worker and self.worker.is_alive()):
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def on_finished(self, result):
        self.store_box.configure(state="normal")
        self.btn_start.configure(state="normal", text="▶ 다시 시작")
        self.btn_pause.configure(state="disabled", text="⏸ 일시정지")
        self.btn_stop.configure(state="disabled")
        if not self.closing:
            self.root.bell()


def run(args):
    root = tk.Tk()
    App(root, args)
    root.mainloop()
