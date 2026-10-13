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
import sys

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

COLS = 5
PAGE_SIZE = 80
LOGIN_URL = "https://nid.naver.com/nidlogin.login"

# 카드 하나 = 상품 링크 + 찜 버튼이 함께 들어 있는 <li>.
# 페이지 전체를 한 번에 스캔해 [ID, 위치, 찜 여부]를 돌려주고 카드에 data-pid 꼬리표를 붙인다.
SCAN_JS = r"""
() => {
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
      .find(s => s && s !== 'NEW' && !s.includes('찜')) || '';
    out.push({ id: m[1], y: Math.round(r.top + scrollY), x: Math.round(r.left), name: name.slice(0, 40) });
  });
  return out;
}
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


def click_zzim(page, pid, delay):
    btn = page.locator(f'li[data-pid="{pid}"] button', has_text="찜").first
    btn.scroll_into_view_if_needed()
    before = btn.evaluate(STATE_JS)
    if before is True:
        return "already"
    btn.click()
    page.wait_for_timeout(random.randint(*delay))
    if "nid.naver.com" in page.url:
        raise StopRun("로그인이 풀렸습니다. 다시 로그인 후 실행하세요.")
    after = btn.evaluate(STATE_JS)
    if after is True:
        return "clicked"
    if after is None:
        return "clicked?"  # 상태 판별 불가 → 로그에서 확인
    return "fail"


def run_store(page, store, args, alerts):
    name = store.rsplit("/", 1)[-1]
    log = Log(f"zzim_{name}.csv")
    page.goto(list_url(store, 1, args.sort))
    page.wait_for_load_state("networkidle")
    total = read_total(page)
    if not total:
        print(f"[{name}] 상품 목록을 찾지 못했습니다. 주소를 확인하세요.")
        return
    pages = math.ceil(total / PAGE_SIZE)
    print(f"[{name}] 총 {total}개 / {pages}페이지 / 이전 진행 {len(log.done)}개")

    for pno in range(1, pages + 1):
        if pno > 1:
            page.goto(list_url(store, pno, args.sort))
            page.wait_for_load_state("networkidle")
        expected = min(PAGE_SIZE, total - PAGE_SIZE * (pno - 1))
        cards = scan_cards(page, expected)
        print(f"[{name}] {pno}/{pages}페이지: 카드 {len(cards)}개")

        rows = [cards[i:i + COLS] for i in range(0, len(cards), COLS)]
        for r, row in enumerate(rows, 1):
            for c, it in enumerate(row, 1):
                if it["id"] in log.done:
                    continue
                try:
                    status = click_zzim(page, it["id"], args.delay)
                except PlaywrightError as e:
                    status = "error"
                    print(f"  {it['id']} 클릭 실패: {e.message.splitlines()[0]}")
                if alerts:
                    msg = alerts.pop()
                    if re.search(r"최대|초과|제한", msg):
                        raise StopRun(f"네이버 알림: {msg}")
                log.write(page=pno, row=r, col=c, id=it["id"], name=it["name"], status=status)
                print(f"  {pno}p {r}행 {c}열 {it['id']} {status} {it['name']}")

    missing = total - len(log.done)
    print(f"[{name}] 완료: {len(log.done)}/{total}개 처리"
          + (f" — {missing}개 누락. 다시 실행하면 누락분만 처리합니다." if missing > 0 else ""))


def main():
    ap = argparse.ArgumentParser(description="스마트스토어 목록 페이지 찜 클릭")
    ap.add_argument("store", nargs="?", help="스토어 주소 또는 스토어명")
    ap.add_argument("--file", help="스토어 주소 목록 파일(한 줄에 하나)")
    ap.add_argument("--sort", default="RECENT",
                    help="목록 정렬(st 값). 진행 중 순서가 바뀌지 않는 최신순 권장 (기본 RECENT)")
    ap.add_argument("--delay", type=int, nargs=2, default=[700, 1500], metavar=("MIN", "MAX"),
                    help="클릭 후 대기 ms 범위 (기본 700 1500)")
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
            browser = p.chromium.launch(channel="chrome", headless=False)
        except PlaywrightError:
            browser = p.chromium.launch(headless=False)  # 크롬 미설치 시 크로미움
        # new_context()는 쿠키·기록을 남기지 않는 시크릿(off-the-record) 컨텍스트
        context = browser.new_context(viewport={"width": 1680, "height": 1000}, locale="ko-KR")
        page = context.new_page()

        alerts = []
        def on_dialog(d):
            alerts.append(d.message)
            d.accept()
        page.on("dialog", on_dialog)

        page.goto(LOGIN_URL)
        input("브라우저에서 네이버 로그인을 마친 뒤 Enter를 누르세요...")

        try:
            for store in stores:
                run_store(page, store, args, alerts)
        except StopRun as e:
            print(f"중단: {e}")
        except KeyboardInterrupt:
            print("사용자 중단. 다시 실행하면 이어서 진행합니다.")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
