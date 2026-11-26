"""셀업 캡처 브라우저에서 스토어 전체 상품을 자동으로 열고 CAPTURE(Alt+C)를 누른다.

흐름
  1) stores.txt 의 스토어마다 별도 크롬으로 목록 페이지를 넘기며 상품 주소를 전부 모은다 (sellup.db 에 저장)
  2) 셀업 캡처 브라우저 창에서  Ctrl+L → 주소 붙여넣기 → Enter → 로딩 대기 → Alt+C  를 반복한다
  3) 캡처할 때마다 셀업 본체에 '중복' 팝업이 떴는지 확인해 '아니오'를 누른다
  이미 처리한 상품은 sellup.db 에 기록되어 다시 들어가지 않고, 껐다 켜도 이어서 진행한다.

사용법
    python sellup.py run            # 수집 시작 (stores.txt 사용)
    python sellup.py harvest        # 상품 주소만 미리 모으기
    python sellup.py status         # 스토어별 진행 현황
    python sellup.py inspect        # 셀업 창의 버튼 이름 덤프 (중복 팝업 인식 조정용)
    python sellup.py retry          # 실패(fail) 상품을 다시 대기 상태로

조작 키 (수집 중 아무 창에서나):  F9 일시정지/계속,  F10 종료
"""

import argparse
import ctypes
import json
import math
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "sellup.db")
SETTINGS_PATH = os.path.join(HERE, "sellup_settings.json")
LOG_PATH = os.path.join(HERE, "sellup_log.txt")
NO_BUTTON_IMG = os.path.join(HERE, "no_button.png")
PAGE_SIZE = 80

DEFAULTS = {
    # --- 속도 (초). 줄일수록 빠르지만 캡처 누락·네이버 차단 가능성이 커진다 ---
    "load_timeout": 8.0,        # 상품 페이지 제목이 뜰 때까지 최대 대기
    "settle": 1.0,              # 제목이 뜬 뒤 CAPTURE 버튼이 준비될 때까지 추가 대기
    "after_capture": 2.0,       # Alt+C 뒤 셀업이 상품을 받아 적을 때까지 대기
    # --- 창 찾기 ---
    "sellup_title": "셀업",      # 셀업 본체 창 제목에 들어 있는 글자
    # --- 중복 팝업 ---
    "popup_no_names": ["아니오", "아니요", "No", "NO", "no"],   # 누를 버튼 이름(정확히 일치)
    # --- 오류/차단 대응 ---
    "error_titles": ["에러", "오류", "찾을 수 없", "접속이 불가", "존재하지 않"],
    "pause_titles": ["로그인", "보안 확인", "captcha", "Captcha"],
    "max_consecutive_errors": 3,   # 연속 오류가 이만큼이면 차단으로 보고 쉰다
    "block_rest": 300,             # 차단 의심 시 쉬는 시간(초)
}


def load_settings():
    cfg = dict(DEFAULTS)
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, ensure_ascii=False, indent=2)
    return cfg


def log(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ───────────────────────── 기록 (SQLite) ─────────────────────────

def open_db(path=DB_PATH):
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS products(
        store TEXT, pid TEXT, url TEXT, status TEXT DEFAULT 'pending', ts TEXT,
        PRIMARY KEY(store, pid))""")
    db.execute("CREATE TABLE IF NOT EXISTS stores(store TEXT PRIMARY KEY, harvested_at TEXT, total INTEGER)")
    db.commit()
    return db


def set_status(db, store, pid, status):
    db.execute("UPDATE products SET status=?, ts=? WHERE store=? AND pid=?",
               (status, time.strftime("%Y-%m-%d %H:%M:%S"), store, pid))
    db.commit()


def normalize_store(raw):
    raw = raw.strip()
    m = re.search(r"(smartstore|brand)\.naver\.com/([A-Za-z0-9_\-]+)", raw)
    if m:
        return f"https://{m.group(1)}.naver.com/{m.group(2)}"
    if re.fullmatch(r"[A-Za-z0-9_\-]+", raw):
        return f"https://smartstore.naver.com/{raw}"
    raise ValueError(f"스토어 주소를 인식할 수 없음: {raw}")


def read_stores(path):
    if not os.path.exists(path):
        sys.exit(f"{path} 파일이 없습니다. 스토어 주소를 한 줄에 하나씩 적어 주세요.")
    stores = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            try:
                s = normalize_store(line)
            except ValueError as e:
                log(f"건너뜀: {e}")
                continue
            if s not in stores:
                stores.append(s)
    return stores


# ───────────────────────── 1단계: 상품 주소 모으기 ─────────────────────────

IDS_JS = r"""
() => [...new Set([...document.querySelectorAll('a[href*="/products/"]')]
        .map(a => ((a.getAttribute('href') || '').match(/\/products\/(\d+)/) || [])[1])
        .filter(Boolean))]
"""


def harvest_store(page, store, db):
    """목록 페이지를 끝까지 넘기며 상품 번호를 모아 DB에 넣는다. 새로 넣은 개수를 돌려준다."""
    added, total, pages, n, empty_streak = 0, None, None, 1, 0
    while True:
        url = f"{store}/category/ALL?st=RECENT&dt=IMAGE&page={n}&size={PAGE_SIZE}"
        ids = []
        for attempt in range(3):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector('a[href*="/products/"]', timeout=10000)
            except Exception:
                pass
            prev = -1
            for _ in range(30):                      # 지연 로딩 카드가 다 그려질 때까지 스크롤
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(250)
                h = page.evaluate("document.body.scrollHeight")
                if h == prev:
                    break
                prev = h
            ids = page.evaluate(IDS_JS)
            if ids:
                break
            log(f"  {n}쪽에서 상품을 못 찾음. 20초 뒤 다시 시도 ({attempt + 1}/3) "
                f"- 보안 확인 화면이 떠 있으면 직접 풀어 주세요")
            page.wait_for_timeout(20000)
        if total is None:
            m = re.search(r"총\s*([\d,]+)\s*개", page.inner_text("body"))
            if m:
                total = int(m.group(1).replace(",", ""))
                pages = math.ceil(total / PAGE_SIZE)
        before = db.total_changes
        db.executemany("INSERT OR IGNORE INTO products(store, pid, url) VALUES(?,?,?)",
                       [(store, i, f"{store}/products/{i}") for i in ids])
        db.commit()
        new = db.total_changes - before
        added += new
        log(f"  목록 {n}/{pages or '?'}쪽: 상품 {len(ids)}개, 신규 {new}개")
        empty_streak = 0 if new else empty_streak + 1
        if pages is not None and n >= pages:
            break
        if pages is None and empty_streak >= 1:      # 총 개수를 못 읽었으면 새 상품이 없을 때 끝
            break
        if not ids:
            break
        n += 1
    db.execute("INSERT OR REPLACE INTO stores VALUES(?,?,?)",
               (store, time.strftime("%Y-%m-%d %H:%M:%S"), total))
    db.commit()
    return added


def harvest(stores, db, force=False):
    todo = [s for s in stores
            if force or not db.execute("SELECT 1 FROM stores WHERE store=?", (s,)).fetchone()]
    if not todo:
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False)
        except Exception:
            browser = p.chromium.launch(headless=False)
        page = browser.new_context(locale="ko-KR", viewport={"width": 1400, "height": 900}).new_page()
        for s in todo:
            log(f"상품 주소 모으는 중: {s}")
            try:
                log(f"  → 신규 {harvest_store(page, s, db)}개")
            except Exception as e:
                log(f"  → 실패, 다음 실행 때 다시 시도: {e}")
        browser.close()


# ───────────────────────── 윈도우 창 다루기 ─────────────────────────

VK_F9, VK_F10 = 0x78, 0x79


class StopRun(Exception):
    pass


class Win:
    """ctypes 로 감싼 최소한의 창 조작."""

    def __init__(self):
        self.u = ctypes.windll.user32

    def title(self, hwnd):
        buf = ctypes.create_unicode_buffer(512)
        self.u.GetWindowTextW(hwnd, buf, 512)
        return buf.value

    def pid(self, hwnd):
        pid = ctypes.c_ulong()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def windows(self, pid=None, title_part=None):
        """보이는 최상위 창 목록. pid 또는 제목 일부로 거른다."""
        out = []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def cb(hwnd, _):
            if self.u.IsWindowVisible(hwnd):
                if (pid is None or self.pid(hwnd) == pid) and \
                        (title_part is None or title_part in self.title(hwnd)):
                    out.append(hwnd)
            return True

        self.u.EnumWindows(proto(cb), 0)
        return out

    def focus(self, hwnd):
        if self.u.GetForegroundWindow() == hwnd:
            return
        from pywinauto.controls.hwndwrapper import HwndWrapper
        HwndWrapper(hwnd).set_focus()
        time.sleep(0.15)

    def pressed(self, vk):
        return bool(self.u.GetAsyncKeyState(vk) & 1)

    def pick(self, what):
        """사용자가 클릭한 창을 잡는다."""
        print(f"\n▶ 5초 안에 [{what}] 창을 한 번 클릭해 두세요...", flush=True)
        for i in range(5, 0, -1):
            print(f"   {i}", end=" ", flush=True)
            time.sleep(1)
        hwnd = self.u.GetForegroundWindow()
        print(f"\n   선택됨: {self.title(hwnd)!r}")
        return hwnd


class Popup:
    """셀업 본체의 중복 팝업에서 '아니오' 버튼을 찾아 누른다."""

    def __init__(self, win, sellup_pid, names):
        import pyautogui
        from pywinauto.uia_defines import IUIA
        self.win, self.pid, self.gui = win, sellup_pid, pyautogui
        ui = IUIA()
        self.iuia = ui.iuia
        self.scope = ui.UIA_dll.TreeScope_Descendants
        cond = None
        for n in names:
            c = self.iuia.CreatePropertyCondition(ui.UIA_dll.UIA_NamePropertyId, n)
            cond = c if cond is None else self.iuia.CreateOrCondition(cond, c)
        self.cond = cond
        self.use_img = os.path.exists(NO_BUTTON_IMG)

    def find(self):
        """'아니오' 버튼의 화면 좌표 (x, y). 없으면 None."""
        for hwnd in self.win.windows(pid=self.pid):
            try:
                el = self.iuia.ElementFromHandle(hwnd).FindFirst(self.scope, self.cond)
                if el and not el.CurrentIsOffscreen:
                    r = el.CurrentBoundingRectangle
                    if r.right > r.left and r.bottom > r.top:
                        return (r.left + r.right) // 2, (r.top + r.bottom) // 2
            except Exception:
                pass
        if self.use_img:
            try:
                pt = self.gui.locateCenterOnScreen(NO_BUTTON_IMG)
                if pt:
                    return pt.x, pt.y
            except Exception:
                pass
        return None

    def dismiss(self):
        pt = self.find()
        if not pt:
            return False
        self.gui.click(*pt)
        time.sleep(0.3)
        return True


# ───────────────────────── 2단계: 캡처 반복 ─────────────────────────

class Capturer:
    def __init__(self, cfg, db):
        import pyautogui
        import pyperclip
        pyautogui.PAUSE = 0.05
        pyautogui.FAILSAFE = True          # 마우스를 화면 왼쪽 위 구석으로 던지면 즉시 멈춤
        self.gui, self.clip = pyautogui, pyperclip
        self.cfg, self.db, self.win = cfg, db, Win()
        self.err_streak = 0
        self.count = {"done": 0, "dup": 0, "fail": 0}
        self.t0 = time.time()

        self.browser = self.win.pick("셀업 캡처 브라우저(크롬)")
        found = [h for h in self.win.windows(title_part=cfg["sellup_title"]) if h != self.browser]
        self.sellup = found[0] if found else self.win.pick("셀업 본체")
        log(f"캡처 브라우저: {self.win.title(self.browser)!r}")
        log(f"셀업 본체: {self.win.title(self.sellup)!r}")
        self.popup = Popup(self.win, self.win.pid(self.sellup), cfg["popup_no_names"])
        if self.popup.dismiss():
            log("시작 전에 떠 있던 중복 팝업을 닫았습니다.")

    # 조작 키를 확인하면서 기다린다
    def sleep(self, sec):
        end = time.time() + sec
        while True:
            if self.win.pressed(VK_F10):
                raise StopRun("F10 종료")
            if self.win.pressed(VK_F9):
                self.pause("F9 일시정지")
            left = end - time.time()
            if left <= 0:
                return
            time.sleep(min(0.05, left))

    def pause(self, why):
        log(f"⏸ {why} — 계속하려면 F9, 끝내려면 F10")
        ctypes.windll.user32.MessageBeep(0x30)
        while True:
            if self.win.pressed(VK_F10):
                raise StopRun("F10 종료")
            if self.win.pressed(VK_F9):
                log("▶ 계속")
                return
            time.sleep(0.1)

    def open(self, url):
        """캡처 브라우저의 주소창으로 이동하고, 페이지 제목이 뜰 때까지 기다린다. 제목을 돌려준다."""
        if not self.win.u.IsWindow(self.browser):
            raise StopRun("캡처 브라우저 창이 닫혔습니다.")
        self.win.focus(self.browser)
        before = self.win.title(self.browser)
        self.clip.copy(url)
        self.gui.hotkey("ctrl", "l")
        self.gui.hotkey("ctrl", "v")
        self.gui.press("enter")
        end = time.time() + self.cfg["load_timeout"]
        while time.time() < end:
            self.sleep(0.1)
            t = self.win.title(self.browser)
            # 로딩 중에는 제목이 주소(naver.com/...)로 보인다
            if t != before and "naver.com/" not in t and not t.startswith("제목 없음"):
                return t
        return None

    def one(self, store, pid, url):
        title = self.open(url)
        if title and any(k in title for k in self.cfg["pause_titles"]):
            self.pause(f"로그인/보안 확인 화면으로 보입니다: {title!r}. 직접 처리한 뒤")
            title = self.open(url)
        if title is None or any(k in title for k in self.cfg["error_titles"]):
            self.err_streak += 1
            return "fail"
        self.err_streak = 0
        self.sleep(self.cfg["settle"])
        self.win.focus(self.browser)
        self.gui.hotkey("alt", "c")
        self.sleep(self.cfg["after_capture"])
        if self.popup.dismiss():
            return "dup"
        return "done"

    def run_store(self, store):
        rows = self.db.execute(
            "SELECT pid, url FROM products WHERE store=? AND status='pending'", (store,)).fetchall()
        log(f"=== {store}: 남은 상품 {len(rows)}개 ===")
        for i, (pid, url) in enumerate(rows, 1):
            st = self.one(store, pid, url)
            set_status(self.db, store, pid, st)
            self.count[st] += 1
            if st != "done" or i % 20 == 0:
                n = sum(self.count.values())
                rate = n / max(time.time() - self.t0, 1) * 3600
                log(f"{i}/{len(rows)} {pid} {st} | 수집 {self.count['done']} 중복 {self.count['dup']} "
                    f"실패 {self.count['fail']} | 시간당 {rate:.0f}개")
            if self.err_streak >= self.cfg["max_consecutive_errors"]:
                log(f"연속 {self.err_streak}번 오류 — 차단 가능성. {self.cfg['block_rest']}초 쉽니다.")
                self.sleep(self.cfg["block_rest"])
                self.err_streak = 0


# ───────────────────────── 명령 ─────────────────────────

def cmd_run(args, cfg, db):
    if sys.platform != "win32":
        sys.exit("run 은 윈도우에서만 동작합니다.")
    stores = read_stores(args.file)
    cap = Capturer(cfg, db)
    log("수집 시작. F9 일시정지, F10 종료. 수집 중에는 키보드·마우스를 건드리지 마세요.")
    try:
        for s in stores:
            harvest([s], db, force=args.reharvest)
            cap.run_store(s)
        log("모든 스토어를 마쳤습니다.")
    except StopRun as e:
        log(f"중단: {e}")
    except KeyboardInterrupt:
        log("중단: Ctrl+C")
    c = cap.count
    log(f"이번 실행: 수집 {c['done']} / 중복 {c['dup']} / 실패 {c['fail']}")


def cmd_status(db):
    rows = db.execute("""SELECT store, COUNT(*), SUM(status='done'), SUM(status='dup'),
                                SUM(status='fail'), SUM(status='pending')
                         FROM products GROUP BY store""").fetchall()
    print(f"{'스토어':50} {'전체':>7} {'수집':>7} {'중복':>6} {'실패':>6} {'남음':>7}")
    for r in rows:
        print(f"{r[0]:50} {r[1]:>7} {r[2]:>7} {r[3]:>6} {r[4]:>6} {r[5]:>7}")
    t = [sum(r[i] for r in rows) for i in range(1, 6)]
    print(f"{'합계':50} {t[0]:>7} {t[1]:>7} {t[2]:>6} {t[3]:>6} {t[4]:>7}")


def cmd_inspect(cfg):
    """셀업 창 안의 모든 요소 이름을 파일로 뽑는다. 중복 팝업을 띄워 둔 채 실행할 것."""
    from pywinauto import Desktop
    win = Win()
    found = win.windows(title_part=cfg["sellup_title"])
    hwnd = found[0] if found else win.pick("셀업 본체")
    pid = win.pid(hwnd)
    out = os.path.join(HERE, "sellup_inspect.txt")
    t0 = time.time()
    with open(out, "w", encoding="utf-8") as f:
        for w in Desktop(backend="uia").windows(process=pid):
            f.write(f"### 창: {w.window_text()!r}\n")
            for d in w.descendants():
                name = d.window_text()
                if name:
                    f.write(f"{d.element_info.control_type}\t{name!r}\t{d.rectangle()}\n")
    print(f"{out} 에 저장했습니다 ({time.time() - t0:.1f}초).")
    pt = Popup(win, pid, cfg["popup_no_names"]).find()
    print(f"'아니오' 버튼 인식: {'성공 ' + str(pt) if pt else '실패 — 파일에서 버튼 이름을 찾아 sellup_settings.json 의 popup_no_names 에 추가하세요'}")


def main():
    ap = argparse.ArgumentParser(description="셀업 자동 수집")
    ap.add_argument("cmd", nargs="?", default="run",
                    choices=["run", "harvest", "status", "inspect", "retry"])
    ap.add_argument("--file", default=os.path.join(HERE, "stores.txt"), help="스토어 주소 목록")
    ap.add_argument("--reharvest", action="store_true", help="이미 모은 스토어도 목록을 다시 훑어 신상품 추가")
    args = ap.parse_args()
    cfg = load_settings()
    db = open_db()
    if args.cmd == "run":
        cmd_run(args, cfg, db)
    elif args.cmd == "harvest":
        harvest(read_stores(args.file), db, force=args.reharvest)
        cmd_status(db)
    elif args.cmd == "status":
        cmd_status(db)
    elif args.cmd == "inspect":
        cmd_inspect(cfg)
    elif args.cmd == "retry":
        n = db.execute("UPDATE products SET status='pending' WHERE status='fail'").rowcount
        db.commit()
        print(f"실패 {n}개를 다시 대기 상태로 돌렸습니다.")


if __name__ == "__main__":
    main()
