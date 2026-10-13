"""네이버 스마트스토어 목록 페이지에서 상품 찜(♡)을 페이지 단위로 클릭한다.

- 크롬 시크릿(off-the-record) 컨텍스트에서 실행, 로그인은 사람이 직접 1회
- 상품 상세 페이지에 들어가지 않고 목록(80개씩)에서 바로 클릭
- 카드의 상품 링크(/products/<ID>)로 ID를 읽어 누락·중복 없이 1회만 클릭
- 화면 좌표순으로 정렬해 한 줄 5개씩 행/열 번호를 매겨 로그에 기록

사용법:
    python zzim.py https://smartstore.naver.com/abcstore
    python zzim.py                      # 실행 후 주소 입력
    python zzim.py --file stores.txt    # 여러 스토어 연속 처리
"""

import argparse
import csv
import math
import os
import random
import re
import subprocess
import sys
import traceback

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
      .find(s => s && s !== 'NEW' && !s.includes('찜') && !/^[\d,.%원\s]+$/.test(s)) || '';
    out.push({ id: m[1], y: Math.round(r.top + scrollY), x: Math.round(r.left), name: name.slice(0, 40) });
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
    """로그인 만료, 찜 개수 초과 등 계속 진행하면 안 되는 상황."""


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
    FIELDS = ["page", "row", "col", "id", "name", "status"]

    def __init__(self, path):
        self.path = path
        self.done = set()
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as f:
                self.done = {r["id"] for r in csv.DictReader(f)
                             if r["status"] in ("clicked", "already")}

    def write(self, **row):
        new = not os.path.exists(self.path)
        with open(self.path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=self.FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
        if row["status"] in ("clicked", "already"):
            self.done.add(row["id"])


def wait_for_login(context, page, timeout_min=10):
    """네이버 로그인 쿠키(NID_AUT, NID_SES)가 생길 때까지 기다린다. Enter 입력 불필요."""
    print("열린 크롬 창에서 네이버 로그인을 해 주세요. 로그인되면 자동으로 시작합니다...")
    for _ in range(timeout_min * 60):
        names = {c["name"] for c in context.cookies("https://naver.com")}
        if {"NID_AUT", "NID_SES"} <= names:
            print("로그인 확인!")
            page.wait_for_timeout(2000)  # 로그인 후 이동하는 페이지가 다 뜰 때까지 대기
            return
        page.wait_for_timeout(1000)
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
        page.wait_for_timeout(600)
        h = page.evaluate("document.body.scrollHeight")
        if h == prev:
            break
        prev = h
    page.evaluate("window.scrollTo(0, 0)")


def read_total(page):
    """상단 '전체상품(총 1,023개)'에서 총 개수를 읽는다. 못 찾으면 None."""
    m = re.search(r"총\s*([\d,]+)\s*개", page.inner_text("body"))
    return int(m.group(1).replace(",", "")) if m else None


def scan_cards(page, expected):
    """카드를 스캔하고, 기대 개수보다 적으면 다시 스크롤해서 재스캔."""
    cards = []
    for _ in range(3):
        scroll_to_bottom(page)
        cards = page.evaluate(SCAN_JS)
        if expected is None or len(cards) >= expected:
            break
        print(f"  카드 {len(cards)}/{expected}개 → 재스캔")
    return sorted(cards, key=lambda c: (c["y"], c["x"]))


def choose_sort(page, label):
    """'최신 등록순' 같은 정렬 버튼을 눌러 진행 중 순서가 바뀌지 않게 한다."""
    if not label:
        return
    btn = page.get_by_text(label, exact=True).first
    try:
        btn.click(timeout=3000)
        page.wait_for_timeout(2500)
        print(f"정렬: {label}")
    except PlaywrightError:
        print(f"'{label}' 정렬 버튼을 못 찾아 기본 정렬로 진행합니다.")


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
    for _ in range(timeout_ms // 250):
        page.wait_for_timeout(250)
        state = btn.evaluate(STATE_JS)
        if state is not False:
            return state
    return state


def click_zzim(page, pid, delay, retries=3):
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
            page.wait_for_timeout(random.randint(*delay))
            return "clicked", toasts
        if state is None:
            return "clicked?", toasts  # 상태 판별 불가 → 로그에서 확인
        # 반영이 안 됨 = 너무 빨라서 네이버가 거절했을 가능성 → 점점 길게 쉬고 재시도
        wait = 4000 * (attempt + 1)
        print(f"    반영 안 됨{' (' + ' / '.join(toasts) + ')' if toasts else ''} → {wait // 1000}초 쉬고 재시도")
        page.wait_for_timeout(wait)
    return "fail", toasts


def run_store(page, store, args, alerts):
    name = store.rsplit("/", 1)[-1]
    log = Log(f"zzim_{name}.csv")
    open_url(page, list_url(store, 1, args.sort))
    total = read_total(page)
    if not total:
        print(f"[{name}] 상품 목록을 찾지 못했습니다. 주소를 확인하세요.")
        return
    choose_sort(page, args.sort_label)
    print(f"[{name}] 총 {total}개 / 이전 진행 {len(log.done)}개")

    pno, seen = 1, set()
    while True:
        cards = scan_cards(page, min(PAGE_SIZE, total - len(seen)))
        new = [c for c in cards if c["id"] not in seen]
        print(f"[{name}] {pno}페이지: 카드 {len(cards)}개 (새 상품 {len(new)}개)")
        if cards and not new:
            raise StopRun(f"{pno}페이지가 이전 페이지와 같습니다. 페이지 이동이 안 된 것 같습니다.")
        seen.update(c["id"] for c in cards)

        rows = [cards[i:i + COLS] for i in range(0, len(cards), COLS)]
        for r, row in enumerate(rows, 1):
            for c, it in enumerate(row, 1):
                if it["id"] in log.done:
                    continue
                toasts = []
                try:
                    status, toasts = click_zzim(page, it["id"], args.delay)
                except PlaywrightError as e:
                    status = "error"
                    print(f"  {it['id']} 클릭 실패: {e.message.splitlines()[0]}")
                for msg in alerts + toasts:
                    if re.search(r"최대|초과|제한", msg):
                        raise StopRun(f"네이버 알림: {msg}")
                alerts.clear()
                log.write(page=pno, row=r, col=c, id=it["id"], name=it["name"], status=status)
                note = f"  [알림: {' / '.join(toasts)}]" if toasts else ""
                print(f"  {pno}p {r}행 {c}열 {it['id']} {status} {it['name']}{note}")

        if len(seen) >= total or not go_to_page(page, pno + 1):
            break
        pno += 1

    missing = total - len(log.done)
    print(f"[{name}] 완료: {len(log.done)}/{total}개 처리"
          + (f" — {missing}개 누락. 다시 실행하면 누락분만 처리합니다." if missing > 0 else ""))


def main():
    ap = argparse.ArgumentParser(description="스마트스토어 목록 페이지 찜 클릭")
    ap.add_argument("store", nargs="?", help="스토어 주소 또는 스토어명")
    ap.add_argument("--file", help="스토어 주소 목록 파일(한 줄에 하나)")
    ap.add_argument("--sort", default="RECENT",
                    help="목록 정렬(st 값). 진행 중 순서가 바뀌지 않는 최신순 권장 (기본 RECENT)")
    ap.add_argument("--sort-label", default="최신 등록순",
                    help="화면에서 누를 정렬 버튼 글자. 빈 값이면 누르지 않음 (기본 '최신 등록순')")
    ap.add_argument("--delay", type=int, nargs=2, default=[1500, 2500], metavar=("MIN", "MAX"),
                    help="찜 성공 후 다음 클릭까지 대기 ms 범위 (기본 1500 2500)")
    args = ap.parse_args()

    try:
        if args.file:
            with open(args.file, encoding="utf-8") as f:
                stores = [normalize_store(l) for l in f if l.strip()]
        else:
            stores = [normalize_store(args.store or input("스토어 주소: "))]
    except ValueError as e:
        sys.exit(str(e))

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False,
                                        args=["--start-maximized"])  # PC에 설치된 크롬, 전체 화면
        except PlaywrightError:
            print("크롬을 찾지 못해 브라우저를 내려받습니다...")
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
            wait_for_login(context, page)
            for store in stores:
                run_store(page, store, args, alerts)
        except StopRun as e:
            print(f"중단: {e}")
        except KeyboardInterrupt:
            print("사용자 중단. 다시 실행하면 이어서 진행합니다.")
        finally:
            browser.close()


if __name__ == "__main__":
    # 더블클릭으로 실행해도 창이 바로 닫히지 않게 끝에서 대기
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code)
    except Exception:
        traceback.print_exc()
        print("\n오류가 났습니다. 위 내용을 캡처해서 보내주세요.")
    input("\nEnter를 누르면 창이 닫힙니다...")
