"""상품 수집: 다른 스마트스토어의 판매 중 상품을 크롬으로 열어 셀업 양식(45열) 그대로 가져와 '수집함'에 모은다.
수집함 → (상세 정리) → 원본 상품으로 넣기 / 셀업 양식 엑셀로 저장.

흐름 (스토어 주소마다)
  ① URL 모으기: 그 스토어 페이지 안에서 전체상품 목록(/category/ALL?st=RECENT&size=80&page=N)을 차례로 받아
     상품 번호를 모은다. 쪽 사이 1.1~1.8초, 429·403이면 60초 쉬고 다시. 상품이 없는 쪽이 나오거나
     새 상품이 3쪽 연속 안 나오면 끝. (사장님이 F12로 쓰던 방식 그대로)
  ② 상품 수집: 상품마다 페이지를 열어(기본 4~6초 간격) 페이지 속 상품 데이터(__PRELOADED_STATE__)와
     상세 HTML을 읽는다. 전체 품절·판매중지는 받지 않고(옵션 일부 품절이면 그 옵션만 뺌), 상품명이 원본·수집함과
     같으면(띄어쓰기만 다른 것 포함) 받지 않는다. 가격은 고객 결제가(판매가 - 즉시할인) 한 칸.

크롬은 마우스·키보드가 아니라 안에서 조종하므로 그동안 컴퓨터를 써도 된다 (수집용 크롬 창만 닫지 않으면).
캡차·로그인·차단 화면이 나오면 멈추고 알린다 — 자동으로 풀거나 우회하지 않는다.
못 읽은 상품과 처음 몇 개는 진단 파일(collect_debug)로 남겨 화면 구조가 바뀌어도 바로 고칠 수 있게 한다.
"""

import collections
import datetime
import hashlib
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import traceback

from . import config
from .db import pack, unpack

# 셀업 엑셀과 같은 45열 (순서 그대로)
COLUMNS = ["id", "등록날자", "수정날자", "분류", "마켓명", "마켓ID", "수집URL", "상태", "상품코드", "처리결과", "배송코드",
           "판매자코드", "모델명", "상품명", "재고수", "판매상태", "노출가기준", "판매가", "할인가", "추가판매가", "원가", "노출가",
           "오픈마켓등록가", "배송비", "썸네일", "상세설명", "카테고리", "옵션상품", "추가상품", "상품속성", "상품태그", "브랜드",
           "제조사", "원산지", "주문코드", "제조일자", "인증", "가격비교코드", "비고", "단위가격", "그룹키", "그룹대표상품코드",
           "그룹원상품번호", "그룹옵션정보", "사이트상품코드"]
REFER = "상세페이지 참조"

PROFILE_DIR = os.path.join(config.DATA_DIR, "collect_chrome")   # 수집 전용 크롬 프로필 (네이버 로그인을 기억)
DEBUG_DIR = os.path.join(config.DATA_DIR, "collect_debug")
LOGIN_URL = "https://nid.naver.com/nidlogin.login"
SORTS = {"all": "RECENT", "recent": "RECENT", "popular": "POPULAR"}
SCOPES = {"all": "전체 상품", "recent": "최신 N개", "popular": "인기 N개"}
LIST_SIZE, MAX_PAGE = 80, 2000
SOLDOUT_STATUS = {"OUTOFSTOCK", "SUSPENSION", "CLOSE", "PROHIBITION", "SOLD_OUT", "SOLDOUT", "DELETE", "WAIT",
                  "UNADMISSION", "REJECTION"}
BLOCK_WORDS = ("보안 확인", "자동입력 방지", "자동 입력 방지", "로봇이 아닙니다", "비정상적인 접근", "접속이 일시적으로 제한",
               "현재 서비스 접속이 불가", "잠시 후 다시 이용")
GONE_WORDS = ("판매가 종료", "존재하지 않는 상품", "삭제된 상품", "판매 중지된 상품", "상품이 존재하지 않습니다")

SCHEMA = """
CREATE TABLE IF NOT EXISTS collect_job (
    id INTEGER PRIMARY KEY,
    created_at REAL NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'all',      -- all / recent / popular
    limit_n INTEGER NOT NULL DEFAULT 0,     -- 최신·인기 N개 (스토어마다)
    status TEXT NOT NULL DEFAULT 'ready',   -- ready / running / paused / stopped / done
    started_at REAL, ended_at REAL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS collect_store (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    input TEXT NOT NULL DEFAULT '',
    host TEXT NOT NULL DEFAULT 'smartstore.naver.com',
    slug TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',      -- 스토어 카테고리 번호 (비우면 전체)
    kind TEXT NOT NULL DEFAULT 'store',     -- store / urls (상품 주소를 직접 넣은 것)
    phase TEXT NOT NULL DEFAULT 'urls',     -- urls / products / done / failed
    pages INTEGER NOT NULL DEFAULT 0,
    found INTEGER NOT NULL DEFAULT 0,
    started_at REAL, ended_at REAL,
    error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS collect_url (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    store_id INTEGER NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    product_no TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending / done / soldout / dup / fail
    error TEXT NOT NULL DEFAULT '',
    item_id INTEGER,
    at REAL,
    UNIQUE(store_id, product_no)
);
CREATE INDEX IF NOT EXISTS ix_collect_url ON collect_url(store_id, status, ord);
CREATE INDEX IF NOT EXISTS ix_collect_url_at ON collect_url(at);
CREATE TABLE IF NOT EXISTS collect_item (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    store_slug TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    product_no TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    norm TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL DEFAULT 0,
    thumb TEXT NOT NULL DEFAULT '',
    option_count INTEGER NOT NULL DEFAULT 0,
    image_count INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    row BLOB,
    detail_from TEXT NOT NULL DEFAULT '',   -- 상세를 어디서 읽었나 (데이터 / 상세 요청 / 화면)
    status TEXT NOT NULL DEFAULT 'new',     -- new(정리 전) / sent(원본으로 넣음) / deleted
    source_id INTEGER,
    created_at REAL NOT NULL,
    sent_at REAL
);
CREATE INDEX IF NOT EXISTS ix_collect_item ON collect_item(job_id, status);
CREATE INDEX IF NOT EXISTS ix_collect_item_norm ON collect_item(norm);
CREATE INDEX IF NOT EXISTS ix_collect_item_url ON collect_item(url);
CREATE TABLE IF NOT EXISTS collect_log (
    id INTEGER PRIMARY KEY,
    at REAL NOT NULL,
    job_id INTEGER,
    level TEXT NOT NULL DEFAULT 'info',
    store TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT ''
);
"""


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)
        # 수집하던 중 프로그램이 꺼졌으면 '일시정지'로 (이어서 누르면 남은 것부터)
        c.execute("UPDATE collect_job SET status='paused' WHERE status='running'")
        c.execute("DELETE FROM collect_log WHERE at < ?", (time.time() - 30 * 86400,))   # 실시간 기록은 30일만


def fake():
    return os.environ.get("UPLOADER_FAKE_API") == "1"


def norm_name(name):
    """중복 판정용 상품명: 띄어쓰기만 다른 것은 같은 이름."""
    return " ".join(str(name or "").split())


def name_key(row):
    """수집한 상품의 원본 구분값: 상품명 기준 (사진·옵션이 같아도 이름이 다르면 다른 원본)."""
    return "n:" + hashlib.md5(norm_name(row.get("상품명")).encode()).hexdigest()


# ───────────────────────── 입력 (스토어·카테고리·상품 주소)

_PRODUCT_RE = re.compile(r"(?:https?://)?(?:m\.)?(smartstore\.naver\.com|brand\.naver\.com)/([^/?#\s]+)/products/(\d{5,})", re.I)
_STORE_RE = re.compile(r"(?:https?://)?(?:m\.)?(smartstore\.naver\.com|brand\.naver\.com)/([^/?#\s]+)(?:/category/([^/?#\s]+))?", re.I)


def parse_targets(text):
    """입력 글 → [{kind:'store', host, slug, category} | {kind:'product', host, slug, product_no}].
    한 줄에 하나: 스토어 주소, 스토어 카테고리 주소, 상품 주소, 또는 스토어 이름만."""
    out, seen, bad = [], set(), []
    for line in str(text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m = _PRODUCT_RE.search(s)
        if m:
            t = {"kind": "product", "host": m.group(1).lower(), "slug": m.group(2), "product_no": m.group(3), "input": s}
            key = ("p", t["host"], t["product_no"])
        else:
            m = _STORE_RE.search(s)
            if m:
                cat = m.group(3) or ""
                t = {"kind": "store", "host": m.group(1).lower(), "slug": m.group(2),
                     "category": "" if cat.upper() == "ALL" else cat, "input": s}
            elif re.fullmatch(r"[A-Za-z0-9_\-]{2,}", s):
                t = {"kind": "store", "host": "smartstore.naver.com", "slug": s, "category": "", "input": s}
            else:
                bad.append(s)
                continue
            key = ("s", t["host"], t["slug"], t["category"])
        if key not in seen:
            seen.add(key)
            out.append(t)
    if bad:
        raise ValueError("알아보지 못한 주소: " + ", ".join(bad[:3]) + (" …" if len(bad) > 3 else ""))
    return out


def list_path(slug, category, sort, page):
    return f"/{slug}/category/{category or 'ALL'}?st={sort}&dt=IMAGE&page={page}&size={LIST_SIZE}"


def product_url(host, slug, pid):
    return f"https://{host}/{slug}/products/{pid}"


def product_ids(text):
    """목록 페이지 글에서 상품 번호 (나온 순서대로, 겹치지 않게)."""
    out, seen = [], set()
    for pid in re.findall(r"/products/(\d{6,})", text or ""):
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


# ───────────────────────── 페이지 데이터 → 셀업 양식 한 줄

def _walk(o, depth=0):
    if depth > 9:
        return
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v, depth + 1)
    elif isinstance(o, list):
        for v in o[:300]:
            yield from _walk(v, depth + 1)


def _int(v, default=0):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return default


def find_product(state, pid):
    """페이지 데이터 안에서 이 상품 객체를 찾는다 (이름·가격·사진·옵션이 있고 번호가 맞는 것)."""
    best, score = None, 0
    for o in _walk(state):
        if not isinstance(o.get("name"), str) or not o.get("name").strip():
            continue
        s = 0
        if "salePrice" in o:
            s += 3
        if "productImages" in o or "representImage" in o:
            s += 3
        if "optionCombinations" in o or "options" in o:
            s += 1
        if "category" in o or "wholeCategoryName" in o:
            s += 1
        if str(pid) in {str(o.get(k)) for k in ("id", "productNo", "channelProductNo", "productId", "originProductNo")}:
            s += 5
        if s > score:
            best, score = o, s
    return best if score >= 6 else None


def _html_like(s):
    return isinstance(s, str) and len(s) > 40 and "<" in s and re.search(r"<(img|div|p|table|span|video)\b", s, re.I)


def find_detail(obj):
    """데이터 안의 상세 HTML: 이름에 detail·render·content가 들어간 칸 중 그림이 가장 많은 것."""
    best, score = "", -1
    for o in _walk(obj):
        for k, v in o.items():
            kl = str(k).lower()
            if not any(w in kl for w in ("detail", "render", "content")) or not _html_like(v):
                continue
            sc = len(re.findall(r"<img\b", v, re.I)) * 1000 + len(v) / 1000 + (500 if "detail" in kl or "render" in kl else 0)
            if sc > score:
                best, score = v, sc
    return best


def soldout_reason(o):
    st = str(o.get("productStatusType") or o.get("statusType") or o.get("saleStatus") or "").upper()
    if st in SOLDOUT_STATUS:
        return f"판매 상태 {st}"
    for k in ("soldout", "soldOut", "isSoldOut", "outOfStock"):
        if o.get(k) is True:
            return "품절"
    return ""


def _alive(x):
    """옵션·추가상품 하나가 팔 수 있는 것인지 (사용함, 재고가 있으면 0보다 큼)."""
    if not isinstance(x, dict) or x.get("usable") is False:
        return False
    if "stockQuantity" in x and x.get("stockQuantity") is not None:
        return _int(x.get("stockQuantity")) > 0
    return True


def options_of(o):
    """페이지 데이터의 옵션 → 셀업(커머스API) 양식 옵션상품. (옵션 사전, 원래 조합 수, 남은 조합 수)"""
    combos = [c for c in (o.get("optionCombinations") or []) if isinstance(c, dict)]
    live = [c for c in combos if _alive(c)]
    gn = o.get("optionCombinationGroupNames")
    if not isinstance(gn, dict) or not any(gn.values()):
        groups = [g for g in (o.get("options") or []) if isinstance(g, dict)
                  and str(g.get("optionType") or "COMBINATION").upper() in ("COMBINATION", "")]
        gn = {f"optionGroupName{i + 1}": str(g.get("groupName") or g.get("name") or "") for i, g in enumerate(groups[:3])}
    out_c = []
    for c in live:
        x = {k: c.get(k) for k in ("optionName1", "optionName2", "optionName3") if c.get(k) not in (None, "")}
        x.update({"stockQuantity": _int(c.get("stockQuantity"), 999) if c.get("stockQuantity") is not None else 999,
                  "price": _int(c.get("price")), "sellerManagerCode": str(c.get("sellerManagerCode") or ""), "usable": True})
        out_c.append(x)
    simple = [s for s in (o.get("optionSimple") or []) if _alive(s)]
    custom = [s for s in (o.get("optionCustom") or []) if isinstance(s, dict)]
    standards = [s for s in (o.get("optionStandards") or []) if _alive(s)]
    kind = "combination" if out_c else "simple" if simple else "standard" if standards else ""
    opt = {"simpleOptionSortType": "CREATE", "optionSimple": simple, "optionCustom": custom,
           "optionCombinationSortType": "CREATE", "optionCombinationGroupNames": gn if out_c else {},
           "optionCombinations": out_c, "standardOptionGroups": o.get("standardOptionGroups") or [],
           "optionStandards": standards, "useStockManagement": True, "optionDeliveryAttributes": []}
    if kind:
        opt["optionKind"] = kind
    return opt, len(combos), len(live)


def supplements_of(o):
    out = []
    for s in o.get("supplementProducts") or []:
        if not _alive(s):
            continue
        out.append({"groupName": str(s.get("groupName") or ""), "name": str(s.get("name") or ""),
                    "price": _int(s.get("price")), "stockQuantity": _int(s.get("stockQuantity"), 999) if s.get("stockQuantity") is not None else 999,
                    "sellerManagementCode": str(s.get("sellerManagementCode") or ""), "usable": True})
    return {"sortType": "CREATE", "supplementProducts": out}


def images_of(o):
    imgs = [i for i in (o.get("productImages") or []) if isinstance(i, dict) and i.get("url")]
    imgs.sort(key=lambda i: (0 if str(i.get("imageType") or "").upper().startswith("REPRESENT") else 1, _int(i.get("order"), 99)))
    urls = [i["url"] for i in imgs]
    if not urls and isinstance(o.get("representImage"), dict) and o["representImage"].get("url"):
        urls = [o["representImage"]["url"]] + [x.get("url") for x in o.get("optionalImages") or [] if isinstance(x, dict) and x.get("url")]
    out = []
    for u in urls:
        u = "https:" + u if u.startswith("//") else u
        if u not in out:
            out.append(u)
    return out[:10]


def customer_price(o):
    """고객 결제가: 즉시할인을 뺀 판매가 (쿠폰·적립 제외)."""
    bv = o.get("benefitsView") or {}
    for k in ("discountedSalePrice", "mobileDiscountedSalePrice"):
        v = _int(bv.get(k))
        if v > 0:
            return v
    sale = _int(o.get("salePrice"))
    disc = _int(bv.get("sellerImmediateDiscountAmount") or bv.get("immediateDiscountAmount") or bv.get("discountAmount"))
    return sale - disc if 0 < disc < sale else sale


def category_of(o):
    c = o.get("category") if isinstance(o.get("category"), dict) else {}
    whole = c.get("wholeCategoryName") or o.get("wholeCategoryName")
    if not whole:
        for x in _walk(o):
            if isinstance(x.get("wholeCategoryName"), str):
                whole = x["wholeCategoryName"]
                break
    return str(whole or "").replace(" > ", ">")


def delivery_fee(o):
    d = o.get("productDeliveryInfo") or o.get("deliveryInfo") or {}
    fee = d.get("deliveryFee") if isinstance(d.get("deliveryFee"), dict) else d
    if str(fee.get("deliveryFeeType") or "").upper() == "FREE":
        return 0
    return _int(fee.get("baseFee"))


def tags_of(o):
    seo = o.get("seoInfo") or {}
    out = []
    for t in seo.get("sellerTags") or []:
        text = t.get("text") if isinstance(t, dict) else t
        if isinstance(text, str) and text.strip():
            out.append({"text": text.strip()})
    return out


def build_row(o, detail, url):
    """상품 객체 + 상세 HTML → 셀업 양식 한 줄 (사전). 브랜드·제조사·모델명·원산지는 '상세페이지 참조', 상품코드는 비움."""
    opt, _, _ = options_of(o)
    stock = _int(o.get("stockQuantity"), 0) or sum(c.get("stockQuantity") or 0 for c in opt["optionCombinations"]) or 999
    row = {c: None for c in COLUMNS}
    row.update({"수정날자": datetime.date.today().isoformat(), "분류": "전체선택", "마켓명": "원본상품", "마켓ID": "마스터상품",
                "수집URL": url, "판매자코드": None, "모델명": REFER, "상품명": norm_name(o.get("name")),
                "재고수": stock, "판매상태": "판매중", "노출가기준": "Yes", "판매가": customer_price(o), "할인가": None,
                "추가판매가": 0, "원가": 0, "노출가": 0, "오픈마켓등록가": 0, "배송비": delivery_fee(o),
                "썸네일": images_of(o), "상세설명": detail, "카테고리": category_of(o), "옵션상품": opt,
                "추가상품": supplements_of(o), "상품태그": tags_of(o), "브랜드": REFER, "제조사": REFER, "원산지": REFER})
    return row


# ───────────────────────── 브라우저

_FETCH_JS = """async (u) => {
  try { const r = await fetch(u, {credentials: 'include'}); return [r.status, r.ok ? await r.text() : '']; }
  catch (e) { return [-1, String(e)]; }
}"""
_STATE_JS = "() => { try { return window.__PRELOADED_STATE__ ? JSON.stringify(window.__PRELOADED_STATE__) : null } catch (e) { return null } }"
_DOM_DETAIL_JS = """() => {
  const sels = ['.se-main-container', '#INTRODUCE', '[class*="detail_content"]', '[class*="DetailContent"]',
                '[class*="productDetail"]', '[data-shp-area*="detail"]'];
  let best = null, bi = 0;
  for (const s of sels) for (const el of document.querySelectorAll(s)) {
    const n = el.querySelectorAll('img').length; if (n > bi) { best = el; bi = n; } }
  return best ? best.innerHTML : '';
}"""
_SCROLL_JS = """async () => { for (let i = 1; i <= 8; i++) { window.scrollTo(0, document.body.scrollHeight * i / 8);
  await new Promise(r => setTimeout(r, 250)); } }"""
CHROME_ARGS = ["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
               "--disable-backgrounding-occluded-windows"]   # 최소화·가려져도 느려지지 않게


class RealBrowser:
    """수집 전용 크롬 (PC에 깔린 크롬, 없으면 플레이라이트 크로미엄). 프로필을 저장해 네이버 로그인을 기억한다.
    플레이라이트는 만든 스레드에서만 써야 하므로 수집 스레드 안에서만 다룬다."""

    def __init__(self, log):
        from playwright.sync_api import sync_playwright
        os.makedirs(PROFILE_DIR, exist_ok=True)
        self._pw = sync_playwright().start()
        kw = dict(headless=os.environ.get("UPLOADER_COLLECT_HEADLESS") == "1",   # 창 없이 (개발 시험용)
                  args=CHROME_ARGS, no_viewport=True, locale="ko-KR")
        exe = str(config.load().get("chrome_path") or "").strip()   # 설정의 크롬 위치 (못 찾을 때만 넣는 칸)
        try:
            if exe and os.path.exists(exe):
                self.ctx = self._pw.chromium.launch_persistent_context(PROFILE_DIR, executable_path=exe, **kw)
            else:
                self.ctx = self._pw.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", **kw)
        except Exception:  # noqa: BLE001 - 크롬이 없으면 크로미엄
            try:
                self.ctx = self._pw.chromium.launch_persistent_context(PROFILE_DIR, **kw)
            except Exception:  # noqa: BLE001
                log("warn", "크롬을 찾지 못해 브라우저를 내려받습니다 (한 번만, 몇 분 걸림)")
                subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
                self.ctx = self._pw.chromium.launch_persistent_context(PROFILE_DIR, **kw)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.reqs = []
        self.ctx.on("request", self._on_req)

    def _on_req(self, r):
        if len(self.reqs) < 400:
            self.reqs.append(r.url)

    def alive(self):
        try:
            return not self.page.is_closed()
        except Exception:  # noqa: BLE001
            return False

    def logged_in(self):
        try:
            names = {c["name"] for c in self.ctx.cookies(["https://naver.com", "https://nid.naver.com"])}
        except Exception:  # noqa: BLE001
            return False
        return {"NID_AUT", "NID_SES"} <= names

    def goto(self, url):
        self.reqs = []
        r = self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        return r.status if r else 0

    def fetch(self, path):
        st, text = self.page.evaluate(_FETCH_JS, path)
        return int(st), text or ""

    def state(self, wait=12):
        try:
            self.page.wait_for_function("() => !!window.__PRELOADED_STATE__", timeout=wait * 1000)
        except Exception:  # noqa: BLE001
            pass
        s = self.page.evaluate(_STATE_JS)
        return json.loads(s) if s else None

    def text(self):
        try:
            return self.page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 5000)")
        except Exception:  # noqa: BLE001
            return ""

    def url(self):
        try:
            return self.page.url
        except Exception:  # noqa: BLE001
            return ""

    def more(self):
        """상세가 늦게 뜨는 페이지: 아래로 내리고 '상세정보 펼쳐보기'를 누른다."""
        try:
            self.page.evaluate(_SCROLL_JS)
            btn = self.page.get_by_text("상세정보 펼쳐보기").first
            if btn.count():
                btn.click(timeout=2000)
            self.page.wait_for_timeout(1500)
        except Exception:  # noqa: BLE001
            pass

    def fetch_json(self, url):
        st, text = self.fetch(url)
        if st != 200:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return None

    def dom_detail(self):
        try:
            return self.page.evaluate(_DOM_DETAIL_JS) or ""
        except Exception:  # noqa: BLE001
            return ""

    def front(self):
        try:
            self.page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass

    def open_login(self):
        self.goto(LOGIN_URL)

    def close(self):
        for f in (lambda: self.ctx.close(), lambda: self._pw.stop()):
            try:
                f()
            except Exception:  # noqa: BLE001
                pass


class FakeBrowser:
    """시연 모드: 원본 상품으로 가짜 스토어를 만든다 (네이버에 접속하지 않음). 7번째마다 품절, 5번째마다 원본과 같은 이름,
    13번째마다 상세를 따로 받는 상품, 처음 한 번은 429."""

    def __init__(self, db, log):
        self.reqs, self._url, self._blocked_once = [], "", False
        rows = [unpack(r["data"]) for r in db.q("SELECT data FROM sources ORDER BY id LIMIT 300")]
        self.rows = rows or [{"상품명": "시연 상품", "판매가": 10000, "썸네일": [], "상세설명": "<p>상세</p>", "카테고리": ""}]
        self._login = False

    def alive(self):
        return True

    def logged_in(self):
        return self._login

    def open_login(self):
        self._login = True   # 시연: 로그인 창을 열면 바로 로그인된 것으로

    def _row(self, pid):
        return self.rows[int(pid) % len(self.rows)]

    def goto(self, url):
        self.reqs, self._url = [], url
        if "/products/" in url and not self._blocked_once:
            self._blocked_once = True
            return 429
        if "/products/" in url and int(url.rsplit("/", 1)[1]) % 13 == 0:
            self.reqs = [url.replace("/products/", "/i/v1/products/") + "/contents/PC"]
        return 200

    def fetch(self, path):
        m = re.search(r"/([^/]+)/category/[^?]+\?.*page=(\d+)", path)
        if not m:
            return 404, ""
        slug, page = m.group(1), int(m.group(2))
        n = 37 + sum(map(ord, slug)) % 60   # 스토어마다 상품 수
        start = (page - 1) * LIST_SIZE
        ids = [str(1000000 + sum(map(ord, slug)) * 1000 + i) for i in range(start, min(n, start + LIST_SIZE))]
        return 200, "".join(f'<a href="/{slug}/products/{p}">상품</a>' for p in ids)

    def _product(self, pid):
        r, i = self._row(pid), int(pid)
        opt = r.get("옵션상품") if isinstance(r.get("옵션상품"), dict) else {}
        combos = [dict(c) for c in opt.get("optionCombinations") or []]
        if combos and i % 3 == 0:
            combos[0]["stockQuantity"] = 0   # 옵션 일부 품절
        names = opt.get("optionCombinationGroupNames") or {}
        price = _int(r.get("판매가")) or 10000
        name = r.get("상품명") or "시연 상품"
        o = {"id": i, "productNo": i + 7, "name": name if i % 5 == 0 else f"{name} {i % 97}호",
             "salePrice": price, "benefitsView": {"discountedSalePrice": price - _int(r.get("할인가"))},
             "stockQuantity": 0 if i % 7 == 0 else 100, "productStatusType": "OUTOFSTOCK" if i % 7 == 0 else "SALE",
             "productImages": [{"url": u, "imageType": "REPRESENTATIVE" if k == 0 else "OPTIONAL", "order": k}
                               for k, u in enumerate(r.get("썸네일") or [])],
             "category": {"wholeCategoryName": r.get("카테고리") or ""},
             "options": [{"groupName": v, "optionType": "COMBINATION"} for v in names.values()],
             "optionCombinations": combos, "supplementProducts": [],
             "seoInfo": {"sellerTags": [{"code": 1, "text": t.get("text")} for t in r.get("상품태그") or [] if isinstance(t, dict)]},
             "productDeliveryInfo": {"deliveryFeeType": "FREE", "baseFee": 0}}
        if i % 13:
            o["detailContents"] = {"detailContentText": r.get("상세설명") or "<p>상세</p>"}
        return o

    def state(self, wait=12):
        if "/products/" not in self._url:
            return {"smartStoreV2": {"channel": {}}}
        pid = self._url.rsplit("/", 1)[1]
        return {"product": {"A": self._product(pid)}, "simpleProductForDetailPage": {"A": {}}}

    def text(self):
        return ""

    def url(self):
        return self._url

    def more(self):
        pass

    def fetch_json(self, url):
        pid = re.search(r"/products/(\d+)", url).group(1)
        return {"renderContent": self._row(pid).get("상세설명") or "<p>상세</p>"}

    def dom_detail(self):
        return ""

    def front(self):
        pass

    def close(self):
        pass


def _keep_awake(on):
    """수집 중에는 윈도가 절전 모드로 들어가지 않게 (이 스레드에서 켜고 끔)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))
    except Exception:  # noqa: BLE001
        pass


def _dump(name, data):
    """진단 파일 (최근 300개만 남김)."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with open(os.path.join(DEBUG_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        files = sorted((os.path.join(DEBUG_DIR, x) for x in os.listdir(DEBUG_DIR)), key=os.path.getmtime)
        for p in files[:-300]:
            os.remove(p)
    except OSError:
        pass


# ───────────────────────── 수집 실행

class Stop(Exception):
    pass


def _today_start():
    d = datetime.datetime.now()
    return datetime.datetime(d.year, d.month, d.day).timestamp()


class Collector:
    """수집 작업을 하나씩 돌린다. 화면은 live()로 지금 상태(단계·지금 상품·남은 초·경고·기록)를 본다."""

    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.thread = None
        self.cmd = {"pause": False, "stop": False, "front": False, "retry": False}
        self.logs = collections.deque(maxlen=300)
        self.cur = {"running": False, "job_id": None, "phase": "", "msg": "", "store": "", "store_no": 0, "stores": 0,
                    "n": 0, "total": 0, "url": "", "name": "", "until": 0, "until_what": "", "alert": "", "since": 0}
        self.speed = 0.04 if fake() else 1.0   # 시연 모드는 기다림을 줄임

    # ── 상태·기록

    def _set(self, **kw):
        with self.lock:
            self.cur.update(kw)

    def log(self, level, text, store=None):
        store = self.cur.get("store") if store is None else store
        e = {"at": time.time(), "level": level, "store": store or "", "text": text}
        self.logs.appendleft(e)
        try:
            self.db.x("INSERT INTO collect_log(at, job_id, level, store, text) VALUES(?,?,?,?,?)",
                      (e["at"], self.cur.get("job_id"), level, e["store"], text[:500]))
        except Exception:  # noqa: BLE001
            pass

    def live(self):
        with self.lock:
            cur = dict(self.cur)
        cur["now"] = time.time()
        cur["logs"] = list(self.logs)[:80]
        return cur

    # ── 조작 (화면에서)

    def start(self, job_id):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("이미 수집 중입니다. 지금 것을 중지한 뒤 시작하세요.")
        for k in self.cmd:
            self.cmd[k] = False
        self.logs.clear()
        self.thread = threading.Thread(target=self._run, args=(job_id,), daemon=True, name="collect")
        self.thread.start()

    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def pause(self, on=True):
        self.cmd["pause"] = bool(on)

    def stop(self):
        self.cmd["stop"] = True

    def front(self):
        self.cmd["front"] = True

    def retry(self):
        self.cmd["retry"] = True

    # ── 기다리기 (조작을 보면서)

    def _check(self, br=None):
        if self.cmd["front"] and br:
            self.cmd["front"] = False
            br.front()
        if self.cmd["stop"]:
            raise Stop()
        if self.cmd["pause"]:
            prev = dict(self.cur)
            self._set(phase="paused", msg="일시정지 — '이어서'를 누르면 계속합니다", until=0)
            self.db.x("UPDATE collect_job SET status='paused' WHERE id=?", (self.cur["job_id"],))
            self.log("warn", "일시정지")
            while self.cmd["pause"]:
                if self.cmd["stop"]:
                    raise Stop()
                if self.cmd["front"] and br:
                    self.cmd["front"] = False
                    br.front()
                time.sleep(0.3)
            self.db.x("UPDATE collect_job SET status='running' WHERE id=?", (self.cur["job_id"],))
            self._set(phase=prev["phase"], msg=prev["msg"])
            self.log("info", "이어서 계속")

    def _wait(self, sec, what, br=None, phase=None):
        sec = sec * self.speed
        end = time.time() + sec
        self._set(until=end, until_what=what, **({"phase": phase} if phase else {}))
        while time.time() < end:
            self._check(br)
            time.sleep(min(0.2, max(0.01, end - time.time())))
        self._set(until=0, until_what="")

    # ── 실행

    def _run(self, job_id):
        db = self.db
        cfg = config.load()
        job = db.one("SELECT * FROM collect_job WHERE id=?", (job_id,))
        stores = db.q("SELECT * FROM collect_store WHERE job_id=? ORDER BY ord", (job_id,))
        self._set(running=True, job_id=job_id, phase="starting", msg="수집용 크롬 여는 중", alert="", since=time.time(),
                  stores=len(stores), store_no=0, n=0, total=0, url="", name="", store="")
        db.x("UPDATE collect_job SET status='running', started_at=COALESCE(started_at, ?) WHERE id=?", (time.time(), job_id))
        self.log("info", f"수집 시작 · {len(stores)}곳 · 범위 {SCOPES.get(job['scope'], job['scope'])}"
                 + (f" {job['limit_n']:,}개" if job["limit_n"] else ""), store="")
        try:
            from . import activity
            activity.add(db, "수집", "collect", f"상품 수집 시작: {job['title']}", count=len(stores), status="done")
        except Exception:  # noqa: BLE001
            pass
        _keep_awake(True)
        br, result = None, "done"
        try:
            br = FakeBrowser(db, self.log) if fake() else RealBrowser(self.log)
            if cfg.get("collect_login", True):
                self._login(br)
            names = self._known_names()
            for i, st in enumerate(stores, 1):
                st = db.one("SELECT * FROM collect_store WHERE id=?", (st["id"],))
                if st["phase"] in ("done", "failed"):
                    continue
                label = st["slug"] + (f" (카테고리 {st['category']})" if st["category"] else "")
                self._set(store=label, store_no=i)
                if not st["started_at"]:
                    db.x("UPDATE collect_store SET started_at=? WHERE id=?", (time.time(), st["id"]))
                if st["phase"] == "urls":
                    self._harvest(br, job, st, cfg)
                st = db.one("SELECT * FROM collect_store WHERE id=?", (st["id"],))
                if st["phase"] == "products":
                    self._products(br, job, st, cfg, names)
        except Stop:
            result = "stopped"
            self.log("warn", "중지함 — 다시 '이어서'를 누르면 남은 것부터 합니다", store="")
        except Exception as e:  # noqa: BLE001
            result = "paused"
            self._set(alert=f"오류로 멈춤: {e}")
            self.log("err", f"오류로 멈춤: {e}", store="")
            self.log("err", traceback.format_exc()[-1500:], store="")
        finally:
            if br:
                br.close()
            _keep_awake(False)
            left = db.one("SELECT COUNT(*) AS n FROM collect_store WHERE job_id=? AND phase NOT IN ('done','failed')", (job_id,))["n"]
            if result == "done" and left:
                result = "paused"
            db.x("UPDATE collect_job SET status=?, ended_at=? WHERE id=?",
                 (result, time.time() if result == "done" else None, job_id))
            sums = job_counts(db, job_id)
            text = (f"수집 {sums['done']:,} · 품절 {sums['soldout']:,} · 이름 중복 {sums['dup']:,} · 실패 {sums['fail']:,}"
                    + (f" · 남음 {sums['pending']:,}" if sums["pending"] else ""))
            self.log("ok" if result == "done" else "warn", ("끝 · " if result == "done" else "멈춤 · ") + text, store="")
            try:
                from . import activity
                activity.add(db, "수집", "collect", f"상품 수집 {'끝' if result == 'done' else '멈춤'}: {job['title']}",
                             count=sums["done"], result=text, status="done" if result == "done" else "stopped")
            except Exception:  # noqa: BLE001
                pass
            self._set(running=False, phase=result, until=0,
                      msg={"done": "끝났습니다", "stopped": "중지함", "paused": "멈춤 — '이어서'로 계속"}.get(result, result))

    def _login(self, br):
        if br.logged_in():
            return
        br.open_login()
        br.front()
        self._set(phase="login", msg="네이버 로그인 대기 — 열린 크롬 창에서 로그인해 주세요 (한 번만, 다음부터 기억)",
                  alert="네이버 로그인이 필요합니다. 수집용 크롬 창에서 로그인해 주세요.")
        self.log("warn", "네이버 로그인 대기 — 수집용 크롬 창에서 로그인해 주세요", store="")
        while not br.logged_in():
            self._check(br)
            time.sleep(1)
        self._set(alert="")
        self.log("ok", "네이버 로그인 확인", store="")

    def _known_names(self):
        names = {norm_name(r["name"]) for r in self.db.q("SELECT name FROM sources")}
        names |= {r["norm"] for r in self.db.q("SELECT norm FROM collect_item WHERE status!='deleted'")}
        return names

    def _human(self, br, kind):
        """캡차·로그인·차단 화면: 사람이 풀 때까지 기다린다 (자동으로 풀지 않음)."""
        msg = {"captcha": "캡차(보안 확인)가 나왔습니다. 수집용 크롬 창에서 풀어 주세요 — 풀리면 자동으로 이어갑니다.",
               "login": "네이버 로그인이 풀렸습니다. 수집용 크롬 창에서 다시 로그인해 주세요."}[kind]
        br.front()
        self._set(phase="captcha" if kind == "captcha" else "login", msg=msg, alert=msg, until=0)
        self.log("err", msg)
        self.cmd["retry"] = False
        while True:
            self._check(br)
            if self.cmd["retry"]:
                break
            if kind == "login" and br.logged_in():
                break
            if kind == "captcha" and not page_problem(200, br.url(), br.text()):
                break
            time.sleep(2)
        self.cmd["retry"] = False
        self._set(alert="")
        self.log("ok", "확인됨 — 이어서 합니다")

    def _blocked(self, br, n, cfg):
        wait = int(cfg.get("collect_block_wait") or 60)
        self.log("warn", f"차단 감지(429·403) → {wait}초 쉬고 다시 ({n}번째)")
        if n >= 10:
            self._set(alert="차단이 10번 연속 나왔습니다. 잠시(30분 이상) 쉬었다가 '이어서'를 누르세요.")
            self.cmd["pause"] = True
            self._check(br)
            self._set(alert="")
            return
        self._wait(wait, "차단 대기", br, phase="blocked")

    def _harvest(self, br, job, st, cfg):
        """① URL 모으기: 스토어 페이지 안에서 전체상품 목록을 80개씩 받아 상품 번호를 모은다."""
        db = self.db
        label = self.cur["store"]
        if st["kind"] == "urls":
            db.x("UPDATE collect_store SET phase='products' WHERE id=?", (st["id"],))
            return
        self._set(phase="urls", msg=f"[{label}] 스토어 여는 중", n=0, total=0, url="", name="")
        home = f"https://{st['host']}/{st['slug']}"
        blocks = 0
        while True:
            self._check(br)
            status = br.goto(home)
            prob = page_problem(status, br.url(), br.text())
            if prob == "blocked":
                blocks += 1
                self._blocked(br, blocks, cfg)
                continue
            if prob in ("captcha", "login"):
                self._human(br, prob)
                continue
            break
        sort = SORTS.get(job["scope"], "RECENT")
        limit = int(job["limit_n"] or 0) if job["scope"] in ("recent", "popular") else 0
        page, empty, blocks, errs, reason = 1, 0, 0, 0, ""
        ord_ = db.one("SELECT COALESCE(MAX(ord), 0) AS n FROM collect_url WHERE store_id=?", (st["id"],))["n"]
        self.log("info", f"URL 모으기 시작 ({SCOPES.get(job['scope'])}{f' {limit:,}개' if limit else ''})")
        while page <= MAX_PAGE:
            self._check(br)
            found = db.one("SELECT COUNT(*) AS n FROM collect_url WHERE store_id=?", (st["id"],))["n"]
            self._set(phase="urls", msg=f"[{label}] URL 모으는 중 · {page}쪽 · 지금까지 {found:,}개")
            status, text = br.fetch(list_path(st["slug"], st["category"], sort, page))
            if status in (429, 403):
                blocks += 1
                self._blocked(br, blocks, cfg)
                continue
            if status <= 0:
                errs += 1
                if errs >= 5:
                    reason = f"목록 요청이 계속 실패 ({text[:80]})"
                    break
                self._wait(3, "다시 요청", br)
                continue
            if status != 200:
                reason = f"HTTP {status} ({page}쪽)"
                break
            blocks = errs = 0
            ids = product_ids(text)
            if not ids:
                reason = f"{page}쪽에 상품 없음 (마지막)"
                break
            gain = 0
            with db.tx() as c:
                for pid in ids:
                    if limit and found + gain >= limit:
                        break
                    ord_ += 1
                    cur = c.execute("INSERT OR IGNORE INTO collect_url(job_id, store_id, ord, product_no, url) VALUES(?,?,?,?,?)",
                                    (job["id"], st["id"], ord_, pid, product_url(st["host"], st["slug"], pid)))
                    gain += cur.rowcount
                c.execute("UPDATE collect_store SET pages=?, found=(SELECT COUNT(*) FROM collect_url WHERE store_id=?) WHERE id=?",
                          (page, st["id"], st["id"]))
            found += gain
            if page % 5 == 0 or page == 1:
                self.log("info", f"URL {page}쪽 · +{gain} · 누적 {found:,}개")
            if limit and found >= limit:
                reason = f"{limit:,}개 채움"
                break
            if gain == 0:
                empty += 1
                if empty >= 3:
                    reason = f"{page}쪽까지 새 상품 없음 (끝)"
                    break
            else:
                empty = 0
            page += 1
            self._wait(random.uniform(1.1, 1.8), "다음 쪽", br)
        else:
            reason = f"쪽 한도 {MAX_PAGE} 도달 (더 있을 수 있음)"
        found = db.one("SELECT COUNT(*) AS n FROM collect_url WHERE store_id=?", (st["id"],))["n"]
        if found:
            db.x("UPDATE collect_store SET phase='products', found=? WHERE id=?", (found, st["id"]))
            self.log("ok", f"URL 모으기 끝 · {found:,}개 · {reason}")
        else:
            db.x("UPDATE collect_store SET phase='failed', error=?, ended_at=? WHERE id=?", (reason or "상품 없음", time.time(), st["id"]))
            self.log("err", f"상품 주소를 하나도 못 모음 · {reason}")

    def _products(self, br, job, st, cfg, names):
        """② 상품 수집: 상품 페이지를 하나씩 열어 읽는다."""
        db = self.db
        label = self.cur["store"]
        total = db.one("SELECT COUNT(*) AS n FROM collect_url WHERE store_id=?", (st["id"],))["n"]
        dmin = float(cfg.get("collect_delay_min") or 4)
        dmax = max(dmin, float(cfg.get("collect_delay_max") or 6))
        limit = int(cfg.get("collect_daily_limit") or 0)
        dumped = db.one("SELECT COUNT(*) AS n FROM collect_item WHERE job_id=?", (job["id"],))["n"]
        while True:
            self._check(br)
            u = db.one("SELECT * FROM collect_url WHERE store_id=? AND status='pending' ORDER BY ord LIMIT 1", (st["id"],))
            if not u:
                break
            if limit:
                today = db.one("SELECT COUNT(*) AS n FROM collect_url WHERE at>=? AND status!='pending'", (_today_start(),))["n"]
                if today >= limit:
                    left = _today_start() + 86400 - time.time() + 60
                    self.log("warn", f"하루 한도 {limit:,}개 → 내일 0시에 이어서 (설정에서 바꿈)")
                    self._wait(left, "하루 한도 — 내일 이어서", br, phase="limit")
                    continue
            done = db.one("SELECT COUNT(*) AS n FROM collect_url WHERE store_id=? AND status!='pending'", (st["id"],))["n"]
            self._set(phase="products", n=done + 1, total=total, url=u["url"], name="",
                      msg=f"[{label}] 상품 수집 중 · {done + 1:,} / {total:,}번째")
            status, info, item_id = self._one(br, job, st, u, cfg, names, dump=dumped < 3)
            if status == "done":
                dumped += 1
            db.x("UPDATE collect_url SET status=?, error=?, item_id=?, at=? WHERE id=?",
                 (status, info if status != "done" else "", item_id, time.time(), u["id"]))
            self.log({"done": "ok", "fail": "err"}.get(status, "info"),
                     {"done": f"수집 · {info}", "soldout": f"품절이라 건너뜀 · {info}", "dup": f"이름 중복 건너뜀 · {info}",
                      "fail": f"실패 · {info}"}[status] + f" · {u['product_no']}")
            self._wait(random.uniform(dmin, dmax), "다음 상품", br)
        db.x("UPDATE collect_store SET phase='done', ended_at=? WHERE id=?", (time.time(), st["id"]))
        c = store_counts(db, st["id"])
        self.log("ok", f"스토어 끝 · 수집 {c['done']:,} · 품절 {c['soldout']:,} · 이름 중복 {c['dup']:,} · 실패 {c['fail']:,}")

    def _one(self, br, job, st, u, cfg, names, dump=False):
        """상품 하나 → (상태, 설명, 수집함 번호). 상태: done / soldout / dup / fail."""
        pid, url = u["product_no"], u["url"]
        blocks = 0
        for attempt in range(1, 6):
            self._check(br)
            try:
                status = br.goto(url)
            except Exception as e:  # noqa: BLE001 - 페이지가 안 열림 (네트워크 등)
                if not br.alive():
                    raise RuntimeError("수집용 크롬 창이 닫혔습니다") from None
                if attempt >= 3:
                    return "fail", f"페이지를 열지 못함 ({str(e)[:80]})", None
                self._wait(5, "다시 열기", br)
                continue
            prob = page_problem(status, br.url(), br.text())
            if prob == "blocked":
                blocks += 1
                self._blocked(br, blocks, cfg)
                continue
            if prob in ("captcha", "login"):
                self._human(br, prob)
                continue
            state = br.state()
            o = find_product(state, pid) if state else None
            if not o:
                text = br.text()
                if any(w in text for w in GONE_WORDS) or status == 404:
                    return "soldout", "판매 종료·삭제된 상품", None
                if attempt < 3:
                    self._wait(4, "다시 읽기", br)
                    continue
                _dump(f"fail_{pid}", {"url": url, "status": status, "page_url": br.url(), "text": text[:2000],
                                       "state_keys": list(state.keys()) if isinstance(state, dict) else None, "state": state})
                return "fail", "페이지에서 상품 정보를 못 찾음 (진단 파일 남김)", None
            name = norm_name(o.get("name"))
            self._set(name=name)
            why = soldout_reason(o)
            opt, n_all, n_live = options_of(o)
            if not why and n_all and not n_live:
                why = "모든 옵션 품절"
            if not why and not n_all and o.get("stockQuantity") is not None and _int(o.get("stockQuantity")) <= 0:
                why = "재고 0"
            if why:
                return "soldout", f"{why} · {name[:30]}", None
            nm = norm_name(name)
            if nm in names:
                return "dup", name[:40], None
            detail, src = find_detail(o), "데이터"
            if not detail:
                detail, src = find_detail({k: v for k, v in (state or {}).items() if "product" in str(k).lower()}), "데이터"
            if not detail:
                br.more()
                for r in list(br.reqs):
                    if re.search(r"/i/v\d+/.*(contents|detail)", r, re.I):
                        data = br.fetch_json(r)
                        detail = find_detail(data) if data else ""
                        if detail:
                            src = "상세 요청"
                            break
            if not detail:
                detail, src = br.dom_detail(), "화면"
            if not detail:
                _dump(f"nodetail_{pid}", {"url": url, "product": o, "requests": br.reqs[:200]})
                return "fail", f"상세를 못 찾음 (진단 파일 남김) · {name[:30]}", None
            row = build_row(o, detail, url)
            item_id = self.db.x("""INSERT INTO collect_item(job_id, store_slug, url, product_no, name, norm, price, thumb,
                option_count, image_count, category, row, detail_from, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (job["id"], st["slug"], url, pid, name, nm, row["판매가"] or 0, (row["썸네일"] or [""])[0],
                                 len(row["옵션상품"]["optionCombinations"]), len(row["썸네일"]) + len(re.findall(r"<img\b", detail, re.I)),
                                 row["카테고리"] or "", pack(row), src, time.time()))
            self.db.x("UPDATE collect_item SET row=? WHERE id=?", (pack({**row, "id": item_id}), item_id))
            names.add(nm)
            if dump:
                _dump(f"ok_{pid}", {"url": url, "product": o, "detail_from": src, "row": row})
            extra = f"옵션 {len(row['옵션상품']['optionCombinations'])}" + (f"(품절 {n_all - n_live} 뺌)" if n_all > n_live else "")
            return "done", f"{name[:40]} · {row['판매가']:,}원 · {extra} · 사진 {len(row['썸네일'])} · 상세 {src}", item_id
        return "fail", "여러 번 시도해도 열리지 않음", None


def page_problem(status, url, text):
    """'' / blocked(429·403·접속 제한) / captcha(보안 확인) / login(로그인 페이지로 감)."""
    if status in (429, 403) or "현재 서비스 접속이 불가" in (text or ""):
        return "blocked"
    u = (url or "").lower()
    if "captcha" in u or any(w in (text or "") for w in BLOCK_WORDS):
        return "captcha"
    if "nid.naver.com" in u:
        return "login"
    return ""


# ───────────────────────── 작업·수집함

def create_job(db, targets, scope="all", limit_n=0, title=""):
    if not targets:
        raise ValueError("스토어 주소를 넣어 주세요.")
    if scope not in SCOPES:
        scope = "all"
    stores = [t for t in targets if t["kind"] == "store"]
    prods = [t for t in targets if t["kind"] == "product"]
    title = title or (", ".join(t["slug"] for t in stores[:3]) + (f" 외 {len(stores) - 3}곳" if len(stores) > 3 else "")
                      if stores else f"상품 주소 {len(prods):,}개")
    now = time.time()
    with db.tx() as c:
        jid = c.execute("INSERT INTO collect_job(created_at, title, scope, limit_n) VALUES(?,?,?,?)",
                        (now, title, scope, int(limit_n or 0) if scope != "all" else 0)).lastrowid
        for i, t in enumerate(stores, 1):
            c.execute("INSERT INTO collect_store(job_id, ord, input, host, slug, category) VALUES(?,?,?,?,?,?)",
                      (jid, i, t["input"], t["host"], t["slug"], t["category"]))
        if prods:   # 상품 주소를 직접 넣은 것: 스토어별로 묶어 바로 상품 수집
            by = collections.OrderedDict()
            for t in prods:
                by.setdefault((t["host"], t["slug"]), []).append(t)
            for j, ((host, slug), ts) in enumerate(by.items(), len(stores) + 1):
                sid = c.execute("""INSERT INTO collect_store(job_id, ord, input, host, slug, kind, phase, found)
                    VALUES(?,?,?,?,?,'urls','products',?)""", (jid, j, f"상품 주소 {len(ts)}개", host, slug, len(ts))).lastrowid
                for k, t in enumerate(ts, 1):
                    c.execute("INSERT OR IGNORE INTO collect_url(job_id, store_id, ord, product_no, url) VALUES(?,?,?,?,?)",
                              (jid, sid, k, t["product_no"], product_url(host, slug, t["product_no"])))
    return jid


def store_counts(db, store_id):
    r = db.one("""SELECT COUNT(*) AS total, SUM(status='done') AS done, SUM(status='soldout') AS soldout, SUM(status='dup') AS dup,
        SUM(status='fail') AS fail, SUM(status='pending') AS pending FROM collect_url WHERE store_id=?""", (store_id,))
    return {k: r[k] or 0 for k in ("total", "done", "soldout", "dup", "fail", "pending")}


def job_counts(db, job_id):
    r = db.one("""SELECT COUNT(*) AS total, SUM(status='done') AS done, SUM(status='soldout') AS soldout, SUM(status='dup') AS dup,
        SUM(status='fail') AS fail, SUM(status='pending') AS pending FROM collect_url WHERE job_id=?""", (job_id,))
    return {k: r[k] or 0 for k in ("total", "done", "soldout", "dup", "fail", "pending")}


def overview(db, collector, cfg):
    """'상품 수집' 화면: 지금 상태 + 작업(스토어별 숫자) + 속도·남은 시간·오늘 수."""
    live = collector.live()
    jid = live.get("job_id") or (db.one("SELECT id FROM collect_job ORDER BY id DESC LIMIT 1") or {}).get("id")
    job, stores = None, []
    if jid:
        job = db.one("SELECT * FROM collect_job WHERE id=?", (jid,))
        for s in db.q("SELECT * FROM collect_store WHERE job_id=? ORDER BY ord", (jid,)):
            stores.append({**s, **store_counts(db, s["id"])})
    now = time.time()
    recent = db.one("SELECT COUNT(*) AS n, MIN(at) AS t0 FROM collect_url WHERE at>=? AND status!='pending'", (now - 900,))
    per_min = 0.0
    if recent["n"] and recent["t0"]:
        per_min = recent["n"] / max(1.0, (now - recent["t0"]) / 60)
    counts = job_counts(db, jid) if jid else None
    eta = (counts["pending"] / per_min * 60) if counts and per_min > 0 and counts["pending"] else None
    today = db.one("SELECT COUNT(*) AS n FROM collect_url WHERE at>=? AND status!='pending'", (_today_start(),))["n"]
    if not live.get("running") and not live.get("logs") and jid:   # 프로그램을 다시 켠 뒤: 기록에서 최근 것
        live["logs"] = [dict(r) for r in db.q("SELECT at, level, store, text FROM collect_log WHERE job_id=? ORDER BY id DESC LIMIT 80", (jid,))]
    return {"live": live, "job": job, "stores": stores, "counts": counts, "per_min": round(per_min, 1), "eta": eta,
            "today": today, "daily_limit": int(cfg.get("collect_daily_limit") or 0), "debug_dir": DEBUG_DIR,
            "profile_dir": PROFILE_DIR}


def summary(db, collector):
    """오른쪽 아래 현황용 (짧게)."""
    live = collector.live()
    if not live.get("running"):
        paused = db.one("SELECT id, title FROM collect_job WHERE status='paused' ORDER BY id DESC LIMIT 1")
        return {"running": False, "paused": paused}
    jid = live.get("job_id")
    c = job_counts(db, jid) if jid else {}
    return {"running": True, "phase": live["phase"], "msg": live["msg"], "alert": live["alert"], "until": live["until"],
            "until_what": live["until_what"], "now": live["now"], "counts": c}


def jobs(db, limit=50):
    out = []
    for j in db.q("SELECT * FROM collect_job ORDER BY id DESC LIMIT ?", (limit,)):
        it = db.one("""SELECT SUM(status='new') AS new, SUM(status='sent') AS sent FROM collect_item WHERE job_id=?""", (j["id"],))
        out.append({**j, **job_counts(db, j["id"]), "items_new": it["new"] or 0, "items_sent": it["sent"] or 0,
                    "stores": db.one("SELECT COUNT(*) AS n FROM collect_store WHERE job_id=?", (j["id"],))["n"]})
    return out


ITEM_COLS = ("id, job_id, store_slug, url, product_no, name, price, thumb, option_count, image_count, category, detail_from, "
             "status, source_id, created_at, sent_at")


def items(db, job_id=None, status="new", q="", page=1, size=100):
    w, a = ["status!='deleted'"], []
    if job_id:
        w.append("job_id=?")
        a.append(int(job_id))
    if status in ("new", "sent"):
        w.append("status=?")
        a.append(status)
    if q:
        w.append("(name LIKE ? OR url LIKE ? OR store_slug LIKE ? OR category LIKE ?)")
        a += [f"%{q}%"] * 4
    where = " WHERE " + " AND ".join(w)
    total = db.one(f"SELECT COUNT(*) AS n FROM collect_item{where}", a)["n"]
    rows = db.q(f"SELECT {ITEM_COLS} FROM collect_item{where} ORDER BY id DESC LIMIT ? OFFSET ?", (*a, size, (page - 1) * size))
    counts = db.one("SELECT SUM(status='new') AS new, SUM(status='sent') AS sent FROM collect_item WHERE status!='deleted'"
                    + (" AND job_id=?" if job_id else ""), (int(job_id),) if job_id else ())
    return {"rows": rows, "total": total, "counts": {"new": counts["new"] or 0, "sent": counts["sent"] or 0}}


def item(db, iid):
    r = db.one(f"SELECT {ITEM_COLS}, row FROM collect_item WHERE id=?", (iid,))
    if not r:
        return None
    r["row"] = unpack(r["row"])
    return r


def item_ids(db, b):
    """화면에서 고른 것: ids 또는 job_id(+status) 전체."""
    if b.get("ids"):
        return [int(i) for i in b["ids"]]
    w, a = ["status!='deleted'"], []
    if b.get("job_id"):
        w.append("job_id=?")
        a.append(int(b["job_id"]))
    if b.get("status") in ("new", "sent"):
        w.append("status=?")
        a.append(b["status"])
    return [r["id"] for r in db.q(f"SELECT id FROM collect_item WHERE {' AND '.join(w)} ORDER BY id", a)]


def delete_items(db, ids):
    """수집함에서 지움 (원본으로 넣은 것은 그대로)."""
    n = 0
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        with db.tx() as c:
            n += c.execute(f"UPDATE collect_item SET status='deleted' WHERE status='new' AND id IN ({','.join('?' * len(chunk))})",
                           chunk).rowcount
    return n


def _rows_of(db, ids):
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in db.q(f"SELECT id, row FROM collect_item WHERE id IN ({','.join('?' * len(chunk))}) ORDER BY id", chunk):
            yield r["id"], unpack(r["row"])


def to_sources(db, ids, progress=None, should_stop=None):
    """수집함 → 원본 상품. 원본 구분은 상품명 (같은 이름의 원본이 이미 있으면 넣지 않음)."""
    from . import inventory
    rows = [(iid, row) for iid, row in _rows_of(db, [i for i in ids])]
    rows = [(iid, row) for iid, row in rows if row.get("상품명")]
    if not rows:
        raise ValueError("넣을 상품이 없습니다.")
    st = inventory.import_rows(db, rows, f"상품 수집 {len(rows):,}개", key_fn=name_key, skip_same_name=True,
                               total_hint=len(rows), progress=progress, should_stop=should_stop)
    now = time.time()
    with db.tx() as c:
        for iid, sid in st.pop("refs").items():
            c.execute("UPDATE collect_item SET status='sent', source_id=?, sent_at=? WHERE id=?", (sid, now, iid))
    return st


EXCEL_CELL_MAX = 32767


def export_xlsx(db, ids):
    """셀업 양식(45열) 엑셀. 목록·사전 칸은 셀업처럼 파이썬 글자(['…'], {'…'})로. → (바이트, 상세가 엑셀 칸 한도를 넘은 수)"""
    import openpyxl
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Sheet")
    ws.append(COLUMNS)
    over = 0
    for iid, row in _rows_of(db, ids):
        vals = []
        for c in COLUMNS:
            v = row.get(c)
            if c == "id":
                v = iid
            if isinstance(v, (list, dict)):
                v = str(v)
            if isinstance(v, str) and len(v) > EXCEL_CELL_MAX:
                over += 1
            vals.append("" if v is None else v)   # 빈 칸도 써서 줄마다 45칸 (셀업처럼)
        ws.append(vals)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), over


def _img_srcs(html):
    return re.findall(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)", str(html or ""), re.I)


def compare(db, rows):
    """셀업 엑셀(사전 목록)과 수집함을 수집URL로 맞춰 칸마다 비교 → 보고서. 아직 안 받은 URL도 알려 줌."""
    from . import convert
    fields = ["상품명", "판매가(고객 결제가)", "썸네일", "카테고리", "옵션", "추가상품", "상품태그", "상세 사진"]
    stat = {f: {"same": 0, "diff": 0, "examples": []} for f in fields}
    missing, matched = [], 0

    def opt_key(o):
        o = o if isinstance(o, dict) else {}
        return sorted((str(c.get("optionName1")), str(c.get("optionName2") or ""), _int(c.get("price")))
                      for c in o.get("optionCombinations") or [] if isinstance(c, dict))

    def sup_key(s):
        s = s if isinstance(s, dict) else {}
        return sorted((str(x.get("name")), _int(x.get("price"))) for x in s.get("supplementProducts") or [] if isinstance(x, dict))

    def tag_key(t):
        return sorted(str(x.get("text") if isinstance(x, dict) else x) for x in (t or []))

    for r in rows:
        url = str(r.get("수집URL") or "").strip()
        if not url:
            continue
        mine = db.one("SELECT row FROM collect_item WHERE url=? AND status!='deleted' ORDER BY id DESC LIMIT 1", (url,))
        if not mine:
            missing.append(url)
            continue
        matched += 1
        m = unpack(mine["row"])
        pairs = {
            "상품명": (norm_name(r.get("상품명")), norm_name(m.get("상품명"))),
            "판매가(고객 결제가)": (convert.net_price(r), _int(m.get("판매가"))),
            "썸네일": (list(r.get("썸네일") or []), list(m.get("썸네일") or [])),
            "카테고리": (str(r.get("카테고리") or ""), str(m.get("카테고리") or "")),
            "옵션": (opt_key(r.get("옵션상품")), opt_key(m.get("옵션상품"))),
            "추가상품": (sup_key(r.get("추가상품")), sup_key(m.get("추가상품"))),
            "상품태그": (tag_key(r.get("상품태그")), tag_key(m.get("상품태그"))),
            "상세 사진": (_img_srcs(r.get("상세설명")), _img_srcs(m.get("상세설명"))),
        }
        for f, (a, b) in pairs.items():
            if a == b:
                stat[f]["same"] += 1
            else:
                stat[f]["diff"] += 1
                if len(stat[f]["examples"]) < 5:
                    stat[f]["examples"].append({"url": url, "excel": str(a)[:300], "mine": str(b)[:300]})
    return {"rows": len(rows), "matched": matched, "missing": missing, "fields": stat}
