"""상품 등록기 조작 창.

엑셀 파일을 고르고 [검사] 또는 [등록]을 누른다. 등록은 별도 스레드에서 돌고,
화면과는 큐로만 주고받는다.
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import smartstore_upload as su

FONT = "맑은 고딕"


class App:
    def __init__(self, root, excel=None):
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        self.stop_flag = threading.Event()

        root.title("스마트스토어 상품 등록기")
        root.geometry("560x620")
        root.minsize(480, 480)
        ttk.Style().configure(".", font=(FONT, 10))
        ttk.Style().configure("Big.TButton", font=(FONT, 11, "bold"), padding=6)
        pad = {"padx": 12}

        # ── 엑셀 파일
        ttk.Label(root, text="상품 엑셀 파일").pack(anchor="w", pady=(12, 2), **pad)
        ff = ttk.Frame(root)
        ff.pack(fill="x", **pad)
        self.excel_var = tk.StringVar(value=excel or "")
        ttk.Entry(ff, textvariable=self.excel_var).pack(side="left", fill="x", expand=True)
        ttk.Button(ff, text="찾기", command=self.pick).pack(side="left", padx=(4, 0))
        ttk.Button(ff, text="설정 열기", command=self.open_config).pack(side="left", padx=(4, 0))

        self.one_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(root, text="1개만 시험 등록 (처음에는 켜 두세요)",
                        variable=self.one_var).pack(anchor="w", pady=(8, 0), **pad)

        # ── 버튼
        bf = ttk.Frame(root)
        bf.pack(fill="x", pady=10, **pad)
        self.btn_check = ttk.Button(bf, text="검사 (등록 안 함)", style="Big.TButton",
                                    command=lambda: self.start(check=True))
        self.btn_run = ttk.Button(bf, text="▶ 등록", style="Big.TButton",
                                  command=lambda: self.start(check=False))
        self.btn_stop = ttk.Button(bf, text="■ 중단", style="Big.TButton",
                                   command=self.stop_flag.set, state="disabled")
        for b in (self.btn_check, self.btn_run, self.btn_stop):
            b.pack(side="left", expand=True, fill="x", padx=2)

        # ── 진행
        self.progress_var = tk.StringVar(value="대기")
        tk.Label(root, textvariable=self.progress_var, font=(FONT, 14, "bold")).pack(anchor="w", **pad)
        self.bar = ttk.Progressbar(root, maximum=100)
        self.bar.pack(fill="x", pady=(4, 8), **pad)

        # ── 기록
        lf = ttk.Frame(root)
        lf.pack(fill="both", expand=True, pady=(0, 12), **pad)
        self.log_box = tk.Text(lf, font=(FONT, 9), relief="solid", bd=1, state="disabled")
        sb = ttk.Scrollbar(lf, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

        self.root.after(100, self.poll)

    def pick(self):
        p = filedialog.askopenfilename(filetypes=[("엑셀", "*.xlsx *.xlsm"), ("모든 파일", "*.*")])
        if p:
            self.excel_var.set(p)

    def open_config(self):
        if not os.path.exists(su.CONFIG_PATH):
            shutil.copy(su.CONFIG_EXAMPLE, su.CONFIG_PATH)
            messagebox.showinfo("설정", "설정 파일을 만들었습니다. API 키와 A/S 전화번호 등을 채우고 저장하세요.")
        if sys.platform.startswith("win"):
            os.startfile(su.CONFIG_PATH)
        else:
            subprocess.Popen(["xdg-open", su.CONFIG_PATH])

    def log(self, msg):
        self.q.put(("log", msg))

    def start(self, check):
        excel = self.excel_var.get().strip()
        if not os.path.exists(excel):
            messagebox.showwarning("엑셀", "엑셀 파일을 먼저 골라 주세요.")
            return
        try:
            cfg = su.load_config()
        except su.UploadError as e:
            messagebox.showwarning("설정", str(e))
            return
        if not check and not self.one_var.get():
            if not messagebox.askyesno("확인", "엑셀의 상품을 전부 스마트스토어에 등록합니다. 계속할까요?"):
                return
        self.stop_flag.clear()
        for b in (self.btn_check, self.btn_run):
            b.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_var.set("검사 중" if check else "등록 중")
        limit = 1 if (self.one_var.get() and not check) else None

        def work():
            try:
                su.run(excel, check=check, limit=limit, cfg=cfg, log=self.log,
                       progress=lambda i, n, ok, fail: self.q.put(("prog", (i, n, ok, fail))),
                       should_stop=self.stop_flag.is_set)
            except Exception as e:  # noqa: BLE001 - 창에 그대로 보여준다
                self.log(f"[!] {e}")
            self.q.put(("done", None))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", val + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "prog":
                    i, n, ok, fail = val
                    self.bar["value"] = i * 100 / max(n, 1)
                    self.progress_var.set(f"{i} / {n}   성공 {ok}  실패 {fail}")
                elif kind == "done":
                    for b in (self.btn_check, self.btn_run):
                        b.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def main(excel=None):
    root = tk.Tk()
    App(root, excel)
    root.mainloop()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
