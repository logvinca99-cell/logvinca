"""네이버 스마트스토어 목록 페이지에서 상품 찜(♡)을 페이지 단위로 클릭한다.

- 크롬 시크릿(off-the-record) 컨텍스트에서 실행, 로그인은 사람이 직접 1회
- 상품 상세 페이지에 들어가지 않고 목록(80개씩)에서 바로 클릭
- 카드의 상품 링크(/products/<ID>)로 ID를 읽어 누락·중복 없이 1회만 클릭
- 화면 좌표순으로 정렬해 한 줄 5개씩 행/열 번호를 매겨 로그에 기록

사용법:
    python zzim.py                      # 조작 창(GUI)으로 실행
    python zzim.py --console https://smartstore.naver.com/abcstore   # 검은 창 모드
    python zzim.py --console --file stores.txt                       # 여러 스토어 연속 처리
"""

import argparse
import csv
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:
    # 처음 실행이면 플레이라이트를 자동 설치
    print("필요한 도구(playwright)를 설치합니다. 1~2분 걸립니다...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

COLS = 5
PAGE_SIZE = 80
LOGIN_URL = "https://nid.naver.com/nidlogin.login"

# 카드 하나 = 상품 링크 + 찜 버튼이 함께 들어 있는 <li>.
# 페이지 전체를 한 번에 스캔해 [ID, 위치, 찜 여부]를 돌려주고 카드에 data-pid 꼬리표를 붙인다.
SCAN_JS = r"""
() => {
  // 페이지가 바뀌면 카드(li)가 재사용될 수 있으므로 이전 꼬리표를 모두 지움
  document.querySelectorAll('li[data-pid]').forEach(e => delete e.dataset.pid);
  const seen = new Set();
  const out = [];
  document.querySelectorAll('a[href*="/products/"]').forEach(a => {
    const m = (a.getAttribute('href') || '').match(/\/products\/(\d+)/);
    const card = a.closest('li');
    if (!m || !card || seen.has(m[1])) return;
    const btn = [...card.querySelectorAll('button')].find(b => b.innerText.includes('찜'));
    if (!btn) return;
    seen.add(m[1]);
    card.dataset.pid = m[1];
    const r = card.getBoundingClientRect();
    const name = (card.innerText || '').split('\n').map(s => s.trim())
      .find(s => s && s !== 'NEW' && s !== '상품 상세보기' && !s.includes('찜') && !/^[\d,.%원\s]+$/.test(s)) || '';
    // 찜 상태: true(찜함) / false(안 함) / null(판별 불가) — STATE_JS와 같은 기준
    const p = btn.getAttribute('aria-pressed'), t = btn.innerText || '';
    const zz = p !== null ? p === 'true' : (t.includes('취소') ? true : (t.includes('찜하기') ? false : null));
    out.push({ id: m[1], y: Math.round(r.top + scrollY), x: Math.round(r.left), name: name.slice(0, 40), zz });
  });
  return out;
}
"""

# 화면 위에 잠깐 떴다 사라지는 안내 문구(토스트)를 기록한다.
TOAST_INIT_JS = r"""
(() => {
  window.__toasts = [];
  const start = () => new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) {
      if (n.nodeType !== 1 || n.closest('li')) continue;
      const t = (n.innerText || '').trim();
      if (!t || t.length > 80) continue;
      for (let e = n, i = 0; e && i < 6; e = e.parentElement, i++) {
        const st = getComputedStyle(e);
        if (st.position === 'fixed' || ['alert', 'status', 'dialog'].includes(e.getAttribute('role'))) {
          window.__toasts.push(t.replace(/\s+/g, ' '));
          break;
        }
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
  if (document.documentElement) start(); else document.addEventListener('DOMContentLoaded', start);
})();
"""

# 화면 맨 아래 페이지 번호(n)를 누른다. 없으면 '다음' 버튼. 누른 것을 돌려준다.
PAGER_JS = r"""
n => {
  const visible = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const cands = [...document.querySelectorAll('a, button')]
    .filter(e => !e.closest('li[data-pid]') && visible(e));
  const lowest = list => list.sort((a, b) =>
    b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0];
  let el = lowest(cands.filter(e => e.innerText.trim() === String(n)));
  if (el) { el.click(); return 'num'; }
  el = lowest(cands.filter(e => e.innerText.trim() === '다음' || e.getAttribute('aria-label') === '다음'));
  if (el && el.getAttribute('aria-disabled') !== 'true' && !el.disabled) { el.click(); return 'next'; }
  return null;
}
"""

# 현재 화면의 상품 ID 목록(꼬리표 없이 빠르게)
IDS_JS = r"""
() => [...new Set([...document.querySelectorAll('a[href*="/products/"]')]
  .map(a => ((a.getAttribute('href') || '').match(/\/products\/(\d+)/) || [])[1]).filter(Boolean))]
"""

# 찜 상태 판별: true(찜함) / false(안 함) / null(판별 불가)
STATE_JS = r"""
btn => {
  const p = btn.getAttribute('aria-pressed');
  if (p !== null) return p === 'true';
  const t = btn.innerText || '';
  if (t.includes('취소')) return true;
  if (t.includes('찜하기')) return false;
  return null;
}
"""


class StopRun(Exception):
    """로그인 만료, 찜 개수 초과, 사용자 종료 등 계속 진행하면 안 되는 상황."""


SETTINGS_FILE = "zzim_settings.json"
REPORT_FILE = "zzim_report.csv"
REPORT_FIELDS = ["시작", "종료", "소요(분)", "네이버ID", "스토어", "전체 상품", "이번 성공", "이미 찜",
                 "실패", "반영 안 됨", "누적 완료", "남은 개수", "진행률(%)", "결과", "사유"]


def append_report(row):
    """실행 결과 한 줄을 보고서에 덧붙인다. 엑셀에서 열려 있어 못 쓰면 예비 파일에 쓴다."""
    for path in (REPORT_FILE, "zzim_report_미기록.csv"):
        try:
            new = not os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
                if new:
                    w.writeheader()
                w.writerow(row)
            return path
        except PermissionError:
            continue
    return None


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_telegram(token, chat_id, text):
    """텔레그램 봇으로 메시지 전송. 성공하면 None, 실패하면 오류 문구."""
    if not token or not chat_id:
        return "텔레그램 토큰/채팅 ID가 비어 있습니다."
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage",
                                    data=data, timeout=10) as r:
            body = json.load(r)
        return None if body.get("ok") else str(body)
    except Exception as e:
        return str(e)


class Controller:
    """작업 스레드와 화면(GUI 또는 검은 창) 사이의 연결.

    emit(kind, data)로 화면에 알리고, pause/stop 이벤트로 화면의 버튼 입력을 받는다.
    """

    def __init__(self, emit=None):
        self._emit = emit or self._print
        self.paused = threading.Event()
        self.stopped = threading.Event()
        self.last_stats = None

    def emit(self, kind, data):
        if kind == "stats":
            self.last_stats = data
        self._emit(kind, data)

    @staticmethod
    def _print(kind, data):
        if kind == "log":
            print(data[0])
        elif kind == "status":
            print(f"[상태] {data}")

    def log(self, text, level="info"):
        self.emit("log", (text, level))

    def status(self, text):
        self.emit("status", text)

    def check(self):
        """클릭 사이마다 호출: 일시정지면 대기, 종료면 중단."""
        if self.paused.is_set() and not self.stopped.is_set():
            self.status("일시정지")
            while self.paused.is_set() and not self.stopped.is_set():
                time.sleep(0.2)
            if not self.stopped.is_set():
                self.status("진행 중")
        if self.stopped.is_set():
            raise StopRun("사용자가 종료했습니다.")

    def wait(self, page, ms):
        """종료 버튼에 바로 반응하도록 잘게 나눠 대기."""
        end = time.time() + ms / 1000
        while time.time() < end:
            if self.stopped.is_set():
                raise StopRun("사용자가 종료했습니다.")
            page.wait_for_timeout(min(250, max(1, int((end - time.time()) * 1000))))


class Stats:
    def __init__(self, store, total):
        self.store, self.total = store, total
        self.done = 0                   # 이번 실행에서 화면으로 찜 상태를 확인한 개수(성공+이미 찜)
        self.clicked = self.already = self.failed = 0
        self.page, self.pos, self.name = 0, "", ""
        self.started = time.time()
        self.processed = 0              # 이번 실행에서 처리한 개수(속도 계산용)
        self.pace_ms = 0
        self.rejects = 0

    def snapshot(self):
        elapsed = time.time() - self.started
        remain = max(0, self.total - self.done)
        eta = elapsed / self.processed * remain if self.processed else None
        return dict(store=self.store, total=self.total, done=self.done, clicked=self.clicked,
                    already=self.already, failed=self.failed, page=self.page, pos=self.pos,
                    name=self.name, elapsed=elapsed, eta=eta, remain=remain, pace_ms=self.pace_ms,
                    rejects=self.rejects)


class Pacer:
    """클릭 간격 자동 조절.

    네이버가 거절하지 않는 동안은 조금씩 빠르게, 거절하면 바로 크게 늦춘다.
    간격은 floor(최소)~ceiling(최대) 사이에서만 움직인다.
    """

    def __init__(self, floor_ms, ceiling_ms, start_ms=1200, max_rejects=3):
        self.floor, self.ceiling = floor_ms, ceiling_ms
        self.ms = min(max(start_ms, floor_ms), ceiling_ms)
        self.streak = 0
        self.rejects = 0                # 이번 실행에서 '반영 안 됨' 누적 횟수
        self.max_rejects = max_rejects

    def next_wait(self):
        return int(self.ms * random.uniform(0.8, 1.2))  # 사람처럼 매번 조금씩 다르게

    def on_success(self):
        self.streak += 1
        if self.streak >= 15:          # 15번 연속 성공하면 10% 빠르게
            self.ms = max(self.floor, int(self.ms * 0.9))
            self.streak = 0

    def on_reject(self):
        self.ms = min(self.ceiling, int(self.ms * 1.5) + 500)
        self.streak = 0
        self.rejects += 1
        if self.max_rejects and self.rejects >= self.max_rejects:
            raise StopRun(f"'반영 안 됨'이 {self.rejects}번 나와서 멈췄습니다. "
                          "계정 보호를 위해 몇 시간 이상 쉰 뒤 다시 실행하세요.")


def normalize_store(raw: str) -> str:
    """어떤 형태의 주소든 'https://smartstore.naver.com/<스토어명>'으로 정규화."""
    raw = raw.strip()
    m = re.search(r"(smartstore|brand)\.naver\.com/([A-Za-z0-9_\-]+)", raw)
    if m:
        return f"https://{m.group(1)}.naver.com/{m.group(2)}"
    if re.fullmatch(r"[A-Za-z0-9_\-]+", raw):
        return f"https://smartstore.naver.com/{raw}"
    raise ValueError(f"스토어 주소를 인식할 수 없음: {raw}")


def list_url(store, page_no, sort):
    return (f"{store}/category/ALL"
            f"?st={sort}&dt=IMAGE&page={page_no}&size={PAGE_SIZE}")


class Log:
    """상품별 기록. 기록만 하고, 건너뛸지 여부는 항상 실제 화면의 찜 상태로 정한다."""
    FIELDS = ["page", "row", "col", "id", "name", "status"]

    def __init__(self, path):
        self.path = path

    def write(self, **row):
        new = not os.path.exists(self.path)
        with open(self.path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=self.FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)


def wait_for_login(context, page, ctl, timeout_min=10):
    """네이버 로그인 쿠키(NID_AUT, NID_SES)가 생길 때까지 기다린다."""
    ctl.status("로그인 대기")
    ctl.log("크롬 창에서 네이버 로그인을 해 주세요. 로그인되면 자동으로 시작합니다.", "warn")
    typed_id = ""
    for _ in range(timeout_min * 60):
        try:  # 로그인 화면의 아이디 칸 값만 기억(보고서용)
            v = page.evaluate("(document.querySelector('#id') || {}).value || ''")
            typed_id = v.strip() or typed_id
        except PlaywrightError:
            pass
        names = {c["name"] for c in context.cookies("https://naver.com")}
        if {"NID_AUT", "NID_SES"} <= names:
            ctl.log("로그인 확인!" + (f" ({typed_id})" if typed_id else ""), "ok")
            ctl.wait(page, 2000)  # 로그인 후 이동하는 페이지가 다 뜰 때까지 대기
            return typed_id
        ctl.wait(page, 1000)
    raise StopRun(f"{timeout_min}분 안에 로그인이 확인되지 않았습니다.")


def open_url(page, url):
    """다른 페이지 이동과 겹쳐 끊기면 잠시 뒤 다시 시도."""
    for attempt in range(3):
        try:
            page.goto(url)
            break
        except PlaywrightError as e:
            if "interrupted" not in e.message or attempt == 2:
                raise
            page.wait_for_timeout(2000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightError:
        pass  # 광고 등 계속 통신하는 요소가 있어도 진행
    if "nid.naver.com" in page.url:
        raise StopRun("로그인 페이지로 이동했습니다. 다시 실행해서 로그인해 주세요.")


def scroll_to_bottom(page):
    """지연 로딩된 카드가 모두 그려질 때까지 스크롤."""
    prev = -1
    for _ in range(40):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(350)
        h = page.evaluate("document.body.scrollHeight")
        if h == prev:
            break
        prev = h
    page.evaluate("window.scrollTo(0, 0)")


def read_total(page):
    """상단 '전체상품(총 1,023개)'에서 총 개수를 읽는다. 못 찾으면 None."""
    m = re.search(r"총\s*([\d,]+)\s*개", page.inner_text("body"))
    return int(m.group(1).replace(",", "")) if m else None


def scan_cards(page, expected, ctl):
    """카드를 스캔하고, 기대 개수보다 적으면 다시 스크롤해서 재스캔."""
    cards = []
    for _ in range(3):
        scroll_to_bottom(page)
        cards = page.evaluate(SCAN_JS)
        if expected is None or len(cards) >= expected:
            break
        ctl.log(f"카드 {len(cards)}/{expected}개 → 재스캔", "warn")
    return sorted(cards, key=lambda c: (c["y"], c["x"]))


def choose_sort(page, label, ctl):
    """'최신 등록순' 같은 정렬 버튼을 눌러 진행 중 순서가 바뀌지 않게 한다."""
    if not label:
        return
    btn = page.get_by_text(label, exact=True).first
    try:
        btn.click(timeout=3000)
        page.wait_for_timeout(2500)
        ctl.log(f"정렬: {label}")
    except PlaywrightError:
        ctl.log(f"'{label}' 정렬 버튼을 못 찾아 기본 정렬로 진행합니다.", "warn")


def go_to_page(page, n):
    """하단 페이지 번호를 눌러 n페이지로 이동. 상품 목록이 실제로 바뀌었는지 확인한다."""
    before = page.evaluate(IDS_JS)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(800)
    how = page.evaluate(PAGER_JS, n)
    if not how:
        return False  # 다음 페이지 없음 = 마지막 페이지
    for _ in range(40):  # 최대 20초 대기
        page.wait_for_timeout(500)
        now = page.evaluate(IDS_JS)
        if now and now[:5] != before[:5]:
            page.wait_for_timeout(1000)
            return True
    raise StopRun(f"{n}페이지로 넘어가지 않습니다. 화면 아래 페이지 번호를 확인해 주세요.")


def read_toasts(page):
    try:
        return page.evaluate("(window.__toasts || []).splice(0)")
    except PlaywrightError:
        return []


def wait_state(btn, page, timeout_ms=4000):
    """찜 상태가 true가 될 때까지 최대 timeout_ms 기다린다."""
    state = None
    for _ in range(timeout_ms // 100):
        page.wait_for_timeout(100)
        state = btn.evaluate(STATE_JS)
        if state is not False:
            return state
    return state


def click_zzim(page, pid, pacer, ctl, retries=3):
    btn = page.locator(f'li[data-pid="{pid}"] button', has_text="찜").first
    btn.scroll_into_view_if_needed()
    if btn.evaluate(STATE_JS) is True:
        return "already", []
    toasts = []
    for attempt in range(retries):
        read_toasts(page)
        btn.click()
        state = wait_state(btn, page)
        toasts += read_toasts(page)
        if "nid.naver.com" in page.url:
            raise StopRun("로그인이 풀렸습니다. 다시 로그인 후 실행하세요.")
        if state is True:
            pacer.on_success()
            ctl.wait(page, pacer.next_wait())
            return "clicked", toasts
        if state is None:
            return "clicked?", toasts  # 상태 판별 불가 → 로그에서 확인
        # 반영이 안 됨 = 너무 빨라서 네이버가 거절했을 가능성 → 간격을 늘리고, 점점 길게 쉬고 재시도
        why = f" ({' / '.join(toasts)})" if toasts else ""
        ctl.log(f"  반영 안 됨{why}  [누적 {pacer.rejects + 1}/{pacer.max_rejects or '∞'}]", "warn")
        pacer.on_reject()  # 누적 한도에 닿으면 여기서 StopRun
        wait = 4000 * (attempt + 1)
        ctl.log(f"  → {wait // 1000}초 쉬고 재시도", "warn")
        ctl.wait(page, wait)
    return "fail", toasts


def run_store(page, store, args, alerts, ctl, pacer=None, account=""):
    name = store.rsplit("/", 1)[-1]
    log = Log(f"zzim_{name}.csv")
    pacer = pacer or Pacer(*args.delay, max_rejects=args.max_rejects)
    ctl.status("스토어 여는 중")
    open_url(page, list_url(store, 1, args.sort))
    total = read_total(page)
    if not total:
        ctl.log(f"[{name}] 상품 목록을 찾지 못했습니다. 주소를 확인하세요.", "err")
        return
    choose_sort(page, args.sort_label, ctl)
    st = Stats(name, total)
    ctl.emit("stats", st.snapshot())
    ctl.log(f"[{name}] 총 {total}개 — 이전 기록과 상관없이 화면의 찜 상태로 판단합니다")
    ctl.status("진행 중")

    rejects_before = pacer.rejects
    started = time.strftime("%Y-%m-%d %H:%M:%S")

    def report(result, reason=""):
        s_ = st.snapshot()
        done, tot = st.done, total
        path = append_report({
            "시작": started, "종료": time.strftime("%Y-%m-%d %H:%M:%S"),
            "소요(분)": round(s_["elapsed"] / 60, 1), "네이버ID": account or "(알 수 없음)",
            "스토어": name, "전체 상품": tot, "이번 성공": st.clicked, "이미 찜": st.already,
            "실패": st.failed, "반영 안 됨": pacer.rejects - rejects_before, "누적 완료": done,
            "남은 개수": max(0, tot - done), "진행률(%)": round(done / tot * 100, 1) if tot else 0,
            "결과": result, "사유": reason,
        })
        if path:
            ctl.log(f"보고서 기록: {path}")
        else:
            ctl.log("보고서 파일이 열려 있어 기록하지 못했습니다. 엑셀을 닫아 주세요.", "err")

    try:
        pno, seen = 1, set()
        while True:
            cards = scan_cards(page, min(PAGE_SIZE, total - len(seen)), ctl)
            new = [c for c in cards if c["id"] not in seen]
            ctl.log(f"── {pno}페이지: 카드 {len(cards)}개 (새 상품 {len(new)}개)")
            if cards and not new:
                raise StopRun(f"{pno}페이지가 이전 페이지와 같습니다. 페이지 이동이 안 된 것 같습니다.")
            seen.update(c["id"] for c in cards)
            st.page = pno

            rows = [cards[i:i + COLS] for i in range(0, len(cards), COLS)]
            for r, row in enumerate(rows, 1):
                for c, it in enumerate(row, 1):
                    if it["zz"] is True:  # 화면에 이미 찜으로 표시됨 → 누르지 않음
                        st.already += 1
                        st.done += 1
                        log.write(page=pno, row=r, col=c, id=it["id"], name=it["name"], status="already")
                        ctl.emit("stats", st.snapshot())
                        continue
                    ctl.check()
                    st.pos, st.name = f"{pno}페이지 {r}행 {c}열", it["name"]
                    ctl.emit("stats", st.snapshot())
                    toasts = []
                    try:
                        status, toasts = click_zzim(page, it["id"], pacer, ctl)
                    except PlaywrightError as e:
                        if "has been closed" in e.message:
                            raise StopRun("크롬 창이 닫혔습니다.")
                        status = "error"
                        ctl.log(f"  {it['id']} 클릭 오류: {e.message.splitlines()[0]}", "err")
                    for msg in alerts + toasts:
                        if re.search(r"최대|초과|제한", msg):
                            raise StopRun(f"네이버 알림: {msg}")
                    alerts.clear()
                    log.write(page=pno, row=r, col=c, id=it["id"], name=it["name"], status=status)

                    st.processed += 1
                    if status in ("clicked", "clicked?"):
                        st.clicked += 1
                    elif status == "already":
                        st.already += 1
                    else:
                        st.failed += 1
                    if status in ("clicked", "already"):
                        st.done += 1
                    st.pace_ms, st.rejects = pacer.ms, pacer.rejects
                    ctl.emit("stats", st.snapshot())
                    level = {"clicked": "ok", "already": "info", "clicked?": "warn"}.get(status, "err")
                    label = {"clicked": "성공", "already": "이미 찜", "clicked?": "확인 필요"}.get(status, "실패")
                    ctl.log(f"{pno}p {r}행 {c}열  {label}  {it['name']}", level)
                    if status == "fail":
                        # 세 번 쉬어 가며 눌러도 안 되면 네이버가 찜을 막은 상태.
                        # 계속 누르면 계정 보호조치로 이어지므로 바로 멈춘다.
                        raise StopRun("네이버가 찜을 계속 거절합니다(차단 신호). 계정 보호를 위해 멈췄습니다. "
                                      "몇 시간 이상 쉰 뒤 다시 실행하세요.")

            if len(seen) >= total or not go_to_page(page, pno + 1):
                break
            pno += 1

        missing = total - st.done
        ctl.log(f"[{name}] 화면 확인 결과 찜 {st.done}/{total}개 (이번 성공 {st.clicked} · 이미 찜 {st.already})"
                + (f" — {missing}개 남음. 다시 실행하면 남은 것만 처리합니다." if missing > 0 else ""),
                "ok" if missing <= 0 else "warn")
    except StopRun as e:
        report("중단", str(e))
        raise
    except Exception as e:
        report("오류", f"{type(e).__name__}: {e}".splitlines()[0])
        raise
    else:
        report("완료" if missing <= 0 else "완료(남음)")


def run_all(stores, args, ctl):
    """브라우저를 열고 로그인 후 스토어를 차례로 처리. 작업 스레드에서 실행된다."""
    result, reason = "완료", ""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False,
                                        args=["--start-maximized"])  # PC에 설치된 크롬, 전체 화면
        except PlaywrightError:
            ctl.log("크롬을 찾지 못해 브라우저를 내려받습니다...", "warn")
            subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        # new_context()는 쿠키·기록을 남기지 않는 시크릿(off-the-record) 컨텍스트
        # no_viewport=True → 창 크기를 고정하지 않고 최대화된 창 크기를 그대로 사용
        context = browser.new_context(no_viewport=True, locale="ko-KR")
        context.add_init_script(TOAST_INIT_JS)
        page = context.new_page()

        alerts = []
        def on_dialog(d):
            alerts.append(d.message)
            d.accept()
        page.on("dialog", on_dialog)

        try:
            page.goto(LOGIN_URL)
            typed_id = wait_for_login(context, page, ctl)
            account = (getattr(args, "account", "") or "").strip() or typed_id
            pacer = Pacer(*args.delay, max_rejects=args.max_rejects)  # 스토어가 바뀌어도 익힌 속도를 이어서 사용
            for store in stores:
                run_store(page, store, args, alerts, ctl, pacer, account)
        except StopRun as e:
            result, reason = "중단", str(e)
            ctl.log(f"중단: {e}", "warn")
        except KeyboardInterrupt:
            result = "중단"
            ctl.log("사용자 중단. 다시 실행하면 이어서 진행합니다.", "warn")
        except Exception as e:
            result, reason = "오류", f"{type(e).__name__}: {e}".splitlines()[0]
            ctl.log("오류: " + "".join(traceback.format_exception_only(type(e), e)).strip(), "err")
            ctl.log(traceback.format_exc(), "err")
        finally:
            try:
                browser.close()
            except Exception:
                pass
    ctl.status(result)
    notify_end(args, ctl, result, reason)
    ctl.emit("finished", result)
    return result


def notify_end(args, ctl, result, reason):
    token, chat = getattr(args, "tg_token", ""), getattr(args, "tg_chat", "")
    if not (token and chat):
        return
    s = ctl.last_stats or {}
    lines = [f"[찜 클릭기] {result}"]
    if reason:
        lines.append(f"사유: {reason}")
    if s:
        lines.append(f"스토어: {s['store']}  진행 {s['done']:,}/{s['total']:,}")
        lines.append(f"이번 실행: 성공 {s['clicked']:,} · 이미 찜 {s['already']:,} · 실패 {s['failed']:,}")
    err = send_telegram(token, chat, "\n".join(lines))
    ctl.log("텔레그램 알림 전송" + (f" 실패: {err}" if err else " 완료"), "warn" if err else "info")


def parse_args():
    ap = argparse.ArgumentParser(description="스마트스토어 목록 페이지 찜 클릭")
    ap.add_argument("store", nargs="?", help="스토어 주소 또는 스토어명")
    ap.add_argument("--file", help="스토어 주소 목록 파일(한 줄에 하나)")
    ap.add_argument("--console", action="store_true", help="조작 창 없이 검은 창에서 실행")
    ap.add_argument("--sort", default="RECENT",
                    help="목록 주소의 st 값 (기본 RECENT)")
    ap.add_argument("--sort-label", default="최신 등록순",
                    help="화면에서 누를 정렬 버튼 글자. 빈 값이면 누르지 않음 (기본 '최신 등록순')")
    ap.add_argument("--account", default="", help="보고서에 적을 네이버 아이디(비우면 로그인 화면에서 자동)")
    ap.add_argument("--max-rejects", type=int, default=3,
                    help="'반영 안 됨'이 이 횟수만큼 누적되면 멈추고 알림 (0이면 끔, 기본 3)")
    ap.add_argument("--delay", type=int, nargs=2, default=[600, 6000], metavar=("MIN", "MAX"),
                    help="클릭 간격 자동 조절 범위 ms. 1.2초에서 시작해 이 범위 안에서 조절 (기본 600 6000)")
    return ap.parse_args()


def main_console(args):
    try:
        if args.file:
            with open(args.file, encoding="utf-8") as f:
                stores = [normalize_store(l) for l in f if l.strip()]
        else:
            stores = [normalize_store(args.store or input("스토어 주소: "))]
    except ValueError as e:
        sys.exit(str(e))
    st = load_settings()
    args.tg_token, args.tg_chat = st.get("tg_token", ""), st.get("tg_chat", "")
    run_all(stores, args, Controller())


def main():
    args = parse_args()
    if not args.console:
        try:
            import zzim_gui
        except ImportError as e:  # tkinter가 없는 파이썬이면 검은 창 모드로
            print(f"조작 창을 열 수 없어 검은 창 모드로 실행합니다. ({e})")
        else:
            zzim_gui.run(args)
            return
    main_console(args)
    input("\nEnter를 누르면 창이 닫힙니다...")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code)
            input("\nEnter를 누르면 창이 닫힙니다...")
    except Exception:
        traceback.print_exc()
        print("\n오류가 났습니다. 위 내용을 캡처해서 보내주세요.")
        input("\nEnter를 누르면 창이 닫힙니다...")
