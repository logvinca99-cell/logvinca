"""고객 맞춤 상품: 고객 문의로 그 고객만을 위한 상품(대량 할인 가격·다른 출고지·주문제작 등)을 따로 올린다.

보통 복사본과 완전히 따로 둔다 (custom_products 표) — 원본당 최대 복사 수·후보상품명 칸·상품명 중복 규칙(names)·
원본 목록·최신화·일괄 가격 수정·기준 가격·일괄 수정 엑셀·눈검수·원본 반영·네이버 상품 정보 일괄 바꾸기 어디에도 들어가지 않는다.
원본·복사본에서 시작하면 그 내용을 복사해 시작하지만 원본은 바뀌지 않는다(번호만 참고로 적음).
모든 값(상품명·가격·재고·옵션·이미지·상세·카테고리·출고지·반품지·배송비·원산지·브랜드 등)을 직접 입력한다.
상품명에 무언가를 자동으로 붙이지 않는다. 자동으로 내리는 기능은 없다 (구매 이력이 남아야 상품 한도가 오름).
판매 현황 파일의 주문은 맞춤 상품에도 맞춰 판매 이력이 있으면 잠근다(내리기 막힘).
"""

import hashlib
import os
import re
import threading
import time

from . import config, convert, naver
from .db import pack, unpack

SCHEMA = """
CREATE TABLE IF NOT EXISTS custom_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id INTEGER NOT NULL,
    from_source_id INTEGER,                 -- 시작한 원본 번호 (참고만 — 원본은 안 바뀜)
    from_listing_id INTEGER,                -- 시작한 복사본 번호 (참고만)
    name TEXT NOT NULL,
    price INTEGER NOT NULL,                 -- 손님 가격 (직접 입력, 기준 가격·스토어 가격 차이 %와 상관없음)
    stock INTEGER NOT NULL DEFAULT 100,
    data BLOB NOT NULL,                     -- 올릴 내용 (원본과 같은 엑셀 줄 모양: 썸네일·상세설명·옵션상품·카테고리·배송비·원산지…)
    cat_id TEXT NOT NULL DEFAULT '',        -- 네이버 카테고리 번호 (비우면 카테고리 이름으로 찾음)
    ship_addr TEXT NOT NULL DEFAULT '',     -- 출고지 주소록 번호 (비우면 스토어 템플릿)
    return_addr TEXT NOT NULL DEFAULT '',   -- 반품지 주소록 번호 (비우면 스토어 템플릿)
    show_search INTEGER NOT NULL DEFAULT 0, -- 네이버쇼핑 검색 노출 (기본 안 함 — 스토어 페이지·링크로는 열림)
    follow_rules INTEGER NOT NULL DEFAULT 1,-- 원산지·브랜드·제조사·모델명은 설정 규칙(강제값)을 따름
    memo TEXT NOT NULL DEFAULT '',          -- 어느 고객·문의인지 (업스타 안에서만)
    status TEXT NOT NULL DEFAULT 'draft',   -- draft(아직 안 올림) / running / success(판매 중) / fail / deleted(내림)
    message TEXT NOT NULL DEFAULT '',
    seller_code TEXT NOT NULL DEFAULT '',
    origin_no TEXT NOT NULL DEFAULT '',
    channel_no TEXT NOT NULL DEFAULT '',
    registered_at REAL,
    updated_sent_at REAL,                   -- 마지막으로 네이버에 수정해서 다시 보낸 때
    deleted_at REAL,
    sold_count INTEGER NOT NULL DEFAULT 0,
    cancel_count INTEGER NOT NULL DEFAULT 0,
    last_sold_at REAL,
    locked INTEGER NOT NULL DEFAULT 0,
    lock_note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS custom_store ON custom_products(store_id, status);
"""

# 판매자센터 화면 주소 (바뀌면 여기만 고침). 마케팅 링크는 판매자센터 상품조회/수정에서 만든다:
# 상품번호(스마트스토어)로 검색 → 체크 → 일괄변경 → 마케팅 링크 생성/복사. 검색 조건은 주소에 안 들어가서
# 업스타는 상품번호를 복사해 두고 이 화면을 연다 (만든 링크는 붙여넣어 저장).
SELLER_PRODUCT_URL = "https://sell.smartstore.naver.com/#/products/edit/{origin_no}"
SELLER_MARKETING_URL = "https://sell.smartstore.naver.com/#/products/origin-list"

IMG_DIR = os.path.join(config.DATA_DIR, "custom_img")
LOCAL = naver.LOCAL_IMG          # 직접 올린 그림 주소 앞부분 (업스타 안에서만 쓰는 주소, 올릴 때 파일에서 읽음)
EDITABLE = ("draft", "fail", "success", "deleted")
_lock = threading.Lock()


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(orders)").fetchall()}
        if cols and "custom_id" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN custom_id INTEGER")
        cp = {r[1] for r in c.execute("PRAGMA table_info(custom_products)").fetchall()}
        if "marketing_link" not in cp:
            c.execute("ALTER TABLE custom_products ADD COLUMN marketing_link TEXT NOT NULL DEFAULT ''")


def seller_code(store, cid):
    return f"{store.get('code') or 'S%02d' % store['id']}-C{int(cid):06d}"


def product_url(store, channel_no):
    home = (store.get("store_url") or "").rstrip("/")
    return f"{home}/products/{channel_no}" if home and channel_no else ""


# ───────────────────────── 직접 올린 그림

def save_image(filename, data):
    """파일로 올린 그림 → 업스타 안 주소 (같은 그림은 한 번만). 그림이 아니면 ValueError."""
    from . import imgfix
    if not data:
        raise ValueError("빈 파일입니다.")
    try:
        data, ctype = imgfix.normalize(data, "", filename or "")
    except imgfix.BadImage as e:
        raise ValueError(f"그림 파일이 아닙니다: {e}") from None
    ext = imgfix.MIME.get(imgfix.sniff(data), ("jpg", ""))[0]
    name = hashlib.sha1(data).hexdigest()[:24] + "." + ext
    os.makedirs(IMG_DIR, exist_ok=True)
    p = os.path.join(IMG_DIR, name)
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(data)
    return LOCAL + name


def image_path(name):
    name = os.path.basename(str(name or ""))
    p = os.path.join(IMG_DIR, name)
    return p if name and os.path.exists(p) else None


# ───────────────────────── 시작 내용 (원본·복사본에서 / 빈 양식)

def _view(row, rec):
    """화면에 보낼 맞춤 상품 내용."""
    from . import srcedit
    thumbs = row.get("썸네일")
    thumbs = [thumbs] if isinstance(thumbs, str) else list(thumbs or [])
    return {**rec, "thumbs": [u for u in thumbs if isinstance(u, str) and u],
            "detail": str(row.get("상세설명") or ""), "options": srcedit._opt_view(row),
            "category": str(row.get("카테고리") or ""), "fee": convert.to_int(row.get("배송비")),
            "origin": str(row.get("원산지") or ""), "brand": str(row.get("브랜드") or ""),
            "maker": str(row.get("제조사") or ""), "model": str(row.get("모델명") or ""),
            "opt_stock": {"|".join(convert.option_key(c)): convert.to_int(c.get("stockQuantity"))
                          for c in ((convert.options(row) or {}).get("optionCombinations") or [])}}


def start(db, source_id=None, listing_id=None, store_id=None):
    """새 맞춤 상품 양식 (저장 안 함). 원본·복사본이면 그 내용으로 채움, 아니면 빈 양식."""
    cfg = config.load()
    row, name, price, sid = {}, "", 0, store_id
    if listing_id:
        l = db.one("SELECT store_id, source_id, name, price FROM listings WHERE id=?", (int(listing_id),))
        if not l:
            raise ValueError("복사본이 없습니다.")
        source_id, sid = l["source_id"], sid or l["store_id"]
        name, price = l["name"], l["price"]
    if source_id:
        s = db.one("SELECT name, price FROM sources WHERE id=?", (int(source_id),))
        if not s:
            raise ValueError("원본이 없습니다.")
        row = dict(db.source_row(int(source_id)) or {})
        name = name or s["name"]
        if not price:
            st = db.store(int(sid)) if sid else None
            price = convert.store_price(s["price"], cfg, st) if st else s["price"]
    st = db.store(int(sid)) if sid else None
    rec = {"id": None, "store_id": sid, "store_name": (st or {}).get("name", ""), "from_source_id": source_id,
           "from_listing_id": listing_id, "name": name, "price": int(price or 0),
           "stock": convert.to_int(cfg.get("stock_fixed"), 0) or convert.to_int(row.get("재고수"), 100) or 100,
           "cat_id": "", "ship_addr": str((st or {}).get("tpl_ship_addr") or ""), "return_addr": str((st or {}).get("tpl_return_addr") or ""),
           "show_search": 0, "follow_rules": 1, "memo": "", "status": "draft", "message": ""}
    return _view(row, rec)


def get(db, cid):
    c = db.one("""SELECT c.*, s.name AS store_name, s.store_url FROM custom_products c LEFT JOIN stores s ON s.id=c.store_id
        WHERE c.id=?""", (int(cid),))
    if not c:
        raise ValueError("맞춤 상품이 없습니다.")
    row = unpack(c.pop("data"))
    out = _view(row, c)
    out["url"] = product_url(c, c["channel_no"])
    out["seller_url"] = SELLER_PRODUCT_URL.format(origin_no=c["origin_no"]) if c["origin_no"] else ""
    out["marketing_url"] = SELLER_MARKETING_URL
    out["product_no"] = c["channel_no"] or c["origin_no"]
    return out


def clean_link(link):
    """붙여넣은 마케팅 링크 검사 → 앞뒤 공백 뺀 주소 (비우면 지움). http(s)로 시작하지 않으면 ValueError."""
    link = str(link or "").strip()
    if link and (not re.match(r"^https?://\S+$", link, re.I) or len(link) > 2000):
        raise ValueError("마케팅 링크는 http:// 또는 https://로 시작하는 주소여야 합니다 (판매자센터에서 복사한 그대로 붙여넣기).")
    return link


def set_mlink(db, cid, link):
    link = clean_link(link)
    if not db.one("SELECT 1 FROM custom_products WHERE id=?", (int(cid),)):
        raise ValueError("맞춤 상품이 없습니다.")
    db.x("UPDATE custom_products SET marketing_link=?, updated_at=? WHERE id=?", (link, time.time(), int(cid)))
    return {"marketing_link": link}


LIST_COLS = """c.id, c.store_id, c.name, c.price, c.stock, c.memo, c.status, c.message, c.seller_code, c.origin_no,
        c.channel_no, c.registered_at, c.deleted_at, c.sold_count, c.locked, c.lock_note, c.show_search, c.from_source_id,
        c.marketing_link, c.created_at, c.updated_at, s.store_url, s.name AS store_name"""


def _row_out(r):
    r["url"] = product_url(r, r["channel_no"]) if r["status"] == "success" else ""
    r["product_no"] = r["channel_no"] or r["origin_no"]
    return r


def listing_all(db, store_id=None, status="", days=None, q="", page=0, size=100):
    """모든 스토어 맞춤 상품 (맞춤 상품 화면). status: success·deleted·draft·fail(실패·보내는 중 포함) / days: 올린 지 n일 안."""
    w, a = ["c.status!='removed'"], []
    if store_id:
        w.append("c.store_id=?"); a.append(int(store_id))
    if q:
        w.append("(c.name LIKE ? OR c.memo LIKE ? OR c.seller_code LIKE ? OR c.channel_no LIKE ? OR c.origin_no LIKE ?)")
        a += [f"%{q}%"] * 5
    if days:
        w.append("c.registered_at>=?"); a.append(time.time() - float(days) * 86400)
    base = " AND ".join(w)
    counts = {r["status"]: r["n"] for r in db.q(f"SELECT c.status, COUNT(*) AS n FROM custom_products c WHERE {base} GROUP BY c.status", a)}
    if status:
        sts = ("fail", "running") if status == "fail" else (status,)
        w.append(f"c.status IN ({','.join('?' * len(sts))})"); a += list(sts)
    where = " AND ".join(w)
    total = db.one(f"SELECT COUNT(*) AS n FROM custom_products c WHERE {where}", a)["n"]
    rows = db.q(f"""SELECT {LIST_COLS} FROM custom_products c LEFT JOIN stores s ON s.id=c.store_id
        WHERE {where} ORDER BY c.id DESC LIMIT ? OFFSET ?""", (*a, int(size), int(page) * int(size)))
    return {"rows": [_row_out(r) for r in rows], "total": total, "counts": counts, "page": int(page), "size": int(size)}


def listing(db, store_id, q=""):
    w, a = ["c.store_id=?"], [int(store_id)]
    if q:
        w.append("(c.name LIKE ? OR c.memo LIKE ? OR c.seller_code LIKE ? OR c.channel_no LIKE ?)")
        a += [f"%{q}%"] * 4
    rows = db.q(f"""SELECT {LIST_COLS} FROM custom_products c LEFT JOIN stores s ON s.id=c.store_id
        WHERE {' AND '.join(w)} ORDER BY c.id DESC""", a)
    return [_row_out(r) for r in rows]


def count(db, store_id):
    return db.one("SELECT COUNT(*) AS n FROM custom_products WHERE store_id=? AND status!='removed'", (int(store_id),))["n"]


# ───────────────────────── 저장 (업스타 안에서만 — 네이버로 보내는 건 send)

def _clean_html_img(u):
    return str(u or "").strip()


def save(db, b):
    """화면 입력 → 저장 (새로면 만들고, 있으면 고침). → 맞춤 상품 번호. 상품명엔 아무것도 덧붙이지 않는다."""
    from . import srcedit
    cid = int(b.get("id") or 0) or None
    old = db.one("SELECT * FROM custom_products WHERE id=?", (cid,)) if cid else None
    if cid and not old:
        raise ValueError("맞춤 상품이 없습니다.")
    if old and old["status"] == "running":
        raise ValueError("지금 네이버로 보내는 중입니다. 끝난 뒤에 고치세요.")
    sid = int(b.get("store_id") or (old or {}).get("store_id") or 0)
    store = db.store(sid) if sid else None
    if not store:
        raise ValueError("스토어를 골라 주세요.")
    if old and old["store_id"] != sid and old["origin_no"]:
        raise ValueError("이미 올린 맞춤 상품은 스토어를 바꿀 수 없습니다 (그 스토어에 새로 만드세요).")
    name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()
    if not name:
        raise ValueError("상품명을 적어 주세요.")
    if len(name) > 100:
        raise ValueError("상품명은 100자까지입니다.")
    price = convert.to_int(b.get("price"))
    if price < 100:
        raise ValueError("손님 가격을 적어 주세요 (100원 이상).")
    stock = max(0, convert.to_int(b.get("stock"), 0))
    thumbs = [str(u).strip() for u in (b.get("thumbs") or []) if str(u or "").strip()]
    if not thumbs:
        raise ValueError("대표 이미지를 한 장 이상 넣어 주세요.")
    if len(thumbs) > 10:
        raise ValueError("대표·추가 이미지는 10장까지입니다.")
    for u in thumbs:
        if not u.startswith("http"):
            raise ValueError(f"이미지 주소가 http로 시작하지 않습니다: {u[:60]}")
    detail = str(b.get("detail") or "")
    if not detail.strip():
        raise ValueError("상세페이지가 비었습니다.")
    row = unpack(old["data"]) if old else {}
    if not old and (b.get("from_source_id") or b.get("from_listing_id")):
        src = int(b.get("from_source_id") or 0) or (db.one("SELECT source_id FROM listings WHERE id=?",
                                                          (int(b["from_listing_id"]),)) or {}).get("source_id")
        row = dict(db.source_row(int(src)) or {}) if src else {}
    row = dict(row)
    warn = []
    opts = b.get("options")
    if opts is not None:
        old_o = row.get("옵션상품") if isinstance(row.get("옵션상품"), dict) else None
        if old_o and not srcedit._opt_view(row)["editable"] and (opts.get("rows") or []):
            raise ValueError("이 상품의 옵션은 조합형이 아니라 고칠 수 없습니다 (옵션을 모두 빼면 옵션 없는 상품).")
        o, w = srcedit._build_options(old_o if srcedit._opt_view(row)["editable"] else None,
                                      opts.get("groups") or [], opts.get("rows") or [], price)
        warn += w
        if o:
            stocks = {tuple(str(r.get(f"n{i}") or "").strip() for i in (1, 2, 3)): r.get("stock") for r in (opts.get("rows") or [])}
            for c in o.get("optionCombinations") or []:
                v = stocks.get(convert.option_key(c))
                if v is not None and str(v).strip() != "":
                    c["stockQuantity"] = max(0, convert.to_int(v))
        if o:
            row["옵션상품"] = o
        else:
            row.pop("옵션상품", None)
    row.update({"상품명": name, "판매가": price, "할인가": None, "재고수": stock, "썸네일": thumbs, "상세설명": detail,
                "카테고리": str(b.get("category") or row.get("카테고리") or "").strip(),
                "배송비": max(0, convert.to_int(b.get("fee"), 0)),
                "원산지": str(b.get("origin") or ""), "브랜드": str(b.get("brand") or ""),
                "제조사": str(b.get("maker") or ""), "모델명": str(b.get("model") or ""), "판매상태": "판매중"})
    row.pop("_source_key", None)
    cat_id = str(b.get("cat_id") or "").strip()
    if not cat_id:
        cat_id, _ = convert.find_category(row.get("카테고리"), naver.cached_categories(), config.load())
        cat_id = str(cat_id or "")
    if not cat_id:
        raise ValueError(f"카테고리 '{row.get('카테고리') or '(비어 있음)'}'를 스마트스토어에서 찾지 못했습니다 — 카테고리를 찾아 고르세요.")
    vals = dict(store_id=sid, name=name, price=price, stock=stock, data=pack(row), cat_id=cat_id,
                ship_addr=str(b.get("ship_addr") or "").strip(), return_addr=str(b.get("return_addr") or "").strip(),
                show_search=int(bool(b.get("show_search"))), follow_rules=int(b.get("follow_rules", True) not in (False, 0, "0")),
                memo=str(b.get("memo") or "")[:2000], updated_at=time.time())
    for k in ("ship_addr", "return_addr"):
        if vals[k] and not vals[k].isdigit():
            raise ValueError("출고지·반품지는 주소록 번호(숫자)로 골라 주세요.")
    with db.tx() as c:
        if old:
            c.execute(f"UPDATE custom_products SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), cid))
        else:
            vals.update(from_source_id=b.get("from_source_id") or None, from_listing_id=b.get("from_listing_id") or None,
                        created_at=time.time(), status="draft")
            cid = c.execute(f"INSERT INTO custom_products({', '.join(vals)}) VALUES({', '.join('?' * len(vals))})",
                            tuple(vals.values())).lastrowid
            c.execute("UPDATE custom_products SET seller_code=? WHERE id=?", (seller_code(store, cid), cid))
    same = db.one("""SELECT COUNT(*) AS n FROM listings WHERE store_id=? AND name=? AND origin_no!='' AND status!='deleted'""",
                  (sid, name))["n"] + db.one("""SELECT COUNT(*) AS n FROM custom_products WHERE store_id=? AND name=? AND id!=?
                  AND status='success'""", (sid, name, cid))["n"]
    if same:
        warn.append(f"이 스토어에 같은 이름으로 판매 중인 상품이 이미 {same}개 있습니다 (네이버 중복 상품 주의)")
    return {"id": cid, "warnings": warn}


def remove(db, cid):
    """업스타에서만 지움 — 아직 안 올렸거나 내린 것만 (판매 중이면 먼저 내리기)."""
    c = db.one("SELECT status, origin_no FROM custom_products WHERE id=?", (int(cid),))
    if not c:
        raise ValueError("맞춤 상품이 없습니다.")
    if c["origin_no"] or c["status"] in ("running", "success"):
        raise ValueError("네이버에 올라가 있는 맞춤 상품은 먼저 [내리기]를 하세요.")
    db.x("DELETE FROM custom_products WHERE id=?", (int(cid),))
    return {"ok": True}


# ───────────────────────── 네이버로 보내기 (처음이면 등록, 올라가 있으면 수정해서 다시 보내기 = 상품번호 그대로)

class _Up:
    """엔진의 이미지·옵션표 그림 올리기를 그대로 쓰는 작은 틀 (사용량·한도·재사용 캐시도 엔진과 같음)."""

    def __init__(self, db, progress=None):
        self.db, self.lock = db, threading.Lock()
        self.state = {"images_reused": 0, "images": 0}
        self._p = progress

    def _stage(self, lid, label, msg):
        if self._p:
            self._p(0, None, msg)

    def _log(self, *a):
        pass


def _engine_bits():
    from . import engine
    _Up._images = engine.Runner._images
    _Up._option_images = engine.Runner._option_images
    return engine


def build(db, cid, client, progress=None):
    """(올릴 body, 메모들) — 이미지를 네이버에 올리고 등록 body를 만든다."""
    from . import imgfix, templates, watermark  # noqa: F401
    engine = _engine_bits()
    c = db.one("SELECT * FROM custom_products WHERE id=?", (int(cid),))
    store = db.store(c["store_id"])
    if getattr(client, "store_id", None) not in (None, c["store_id"]):   # 보험: 다른 스토어 키로 보내지 않음
        raise naver.ApiError("스토어가 맞지 않아 보내지 않았습니다.")
    row = unpack(c["data"])
    cfg = dict(config.load())
    cfg["stock_fixed"] = 0                      # 재고는 직접 넣은 값
    cfg["reupload_detail_images"] = True
    if not c["follow_rules"]:                   # 원산지·브랜드 등 직접 넣은 값으로
        cfg["info_force"] = False
        cfg["origin_force"] = False
    up = _Up(db, progress)
    if progress:
        progress(0, None, "스토어 상단·하단 이미지 준비")
    top, bottom = templates.html(db, client, store)
    st2 = {**store, "_tpl_top": top, "_tpl_bottom": bottom, "tpl_price_pct": 0,
           "tpl_ship_addr": c["ship_addr"] or store.get("tpl_ship_addr"),
           "tpl_return_addr": c["return_addr"] or store.get("tpl_return_addr")}
    from concurrent.futures import ThreadPoolExecutor
    cache = naver.image_cache(cfg)
    notes = []
    with ThreadPoolExecutor(4) as pool:
        thumbs = convert.thumbnails(row)[:10]
        wm = None
        if watermark.enabled(cfg) and thumbs:
            marked = set(thumbs if cfg.get("wm_scope") == "all" else thumbs[:1])
            wm = (marked, lambda data: watermark.apply(data, store, cfg), watermark.signature(cfg, store))
        url_map, _, _ = up._images(client, pool, cache, store["id"], thumbs, True, cid, "", None, wm=wm)
        details = convert.detail_images_to_upload(row, cfg)
        dmap, _, failed = up._images(client, pool, cache, engine.DETAIL_SCOPE, details, False, cid, "", None)
        url_map.update(dmap)
    boxes = convert.option_boxes(row, cfg, st2)
    kw = {}
    if boxes:
        kw["opt_urls"] = up._option_images(client, cache, boxes, convert.option_look(cfg, st2), cid, "", None)
    body = convert.build_body(row, cfg, c["cat_id"], url_map, name=c["name"], price=c["price"],
                              importer=convert.importer_for(store, cfg), as_phone=store.get("as_phone") or cfg.get("as_phone"),
                              seller_code=c["seller_code"] or seller_code(store, cid), store=st2, **kw)
    if failed:
        body["originProduct"]["detailContent"] = engine.drop_images(body["originProduct"]["detailContent"], failed)
        notes.append(f"상세 이미지 {len(failed)}장 빼고 올림 (못 받음·그림 아님)")
    body["originProduct"]["stockQuantity"] = int(c["stock"])
    body["originProduct"]["name"] = c["name"][:100]          # 상품명은 적은 그대로 (아무것도 붙이지 않음)
    body.setdefault("smartstoreChannelProduct", {})
    body["smartstoreChannelProduct"]["naverShoppingRegistration"] = bool(c["show_search"])   # 끄면 네이버쇼핑 검색에만 안 나옴
    body["smartstoreChannelProduct"]["channelProductDisplayStatusType"] = "ON"               # 스토어 페이지·링크로는 열림
    return body, notes


def send(db, cid, progress=None, should_stop=None):
    """맞춤 상품을 네이버로: 처음이면 등록, 이미 올라가 있으면 수정해서 다시 보내기(상품번호 그대로)."""
    from . import apiuse
    with _lock:
        c = db.one("SELECT * FROM custom_products WHERE id=?", (int(cid),))
        if not c:
            raise ValueError("맞춤 상품이 없습니다.")
        if c["status"] == "running":
            raise ValueError("지금 보내는 중입니다.")
        db.x("UPDATE custom_products SET status='running', message='' WHERE id=?", (int(cid),))
    prev = c["status"]
    store = db.store(c["store_id"], with_secret=True)
    try:
        client = naver.make_client(store)
        body, notes = build(db, cid, client, progress)
        if progress:
            progress(0, None, "네이버에 보내는 중")
        now = time.time()
        if c["origin_no"] and prev != "deleted":
            client.update_product(c["origin_no"], body)
            db.x("UPDATE custom_products SET status='success', message=?, updated_sent_at=?, updated_at=? WHERE id=?",
                 (" / ".join(notes), now, now, int(cid)))
            what = "수정해서 다시 보냄 (상품번호 그대로)"
        else:
            res = client.create_product(body)
            db.x("""UPDATE custom_products SET status='success', message=?, origin_no=?, channel_no=?, registered_at=?, deleted_at=NULL,
                updated_at=? WHERE id=?""", (" / ".join(notes), str(res.get("originProductNo", "")),
                                             str(res.get("smartstoreChannelProductNo", "")), now, now, int(cid)))
            what = "등록함"
        r = get(db, cid)
        return {"id": int(cid), "message": f"맞춤 상품 {what} · {c['name'][:40]}", "url": r["url"], "seller_url": r["seller_url"],
                "marketing_url": r["marketing_url"], "notes": notes, "store_id": r["store_id"], "product_no": r["product_no"],
                "marketing_link": r.get("marketing_link") or ""}
    except apiuse.QuotaPaused as e:
        msg = f"시간당 한도 — {apiuse.hm(e.until)} 이후 다시 보내세요"
        db.x("UPDATE custom_products SET status=?, message=? WHERE id=?", (prev if prev != "running" else "draft", msg, int(cid)))
        raise naver.ApiError(msg) from None
    except Exception as e:  # noqa: BLE001
        msg = naver.explain(e)[:900]
        back = "fail" if prev in ("draft", "fail", "deleted") else prev   # 판매 중이던 것은 판매 중 그대로 (수정만 실패)
        db.x("UPDATE custom_products SET status=?, message=? WHERE id=?", (back, msg, int(cid)))
        raise naver.ApiError(msg) from None


def drop(db, cid):
    """내리기 (직접 할 때만 — 자동으로 내리는 일은 없음). 잠김이면 막고, 판매 이력 확인이 유효 시간 안일 때만."""
    from . import orders
    c = db.one("SELECT * FROM custom_products WHERE id=?", (int(cid),))
    if not c:
        raise ValueError("맞춤 상품이 없습니다.")
    if not c["origin_no"] or c["status"] == "deleted":
        raise ValueError("네이버에 올라가 있지 않습니다.")
    if c["status"] == "running":
        raise ValueError("지금 보내는 중입니다.")
    recount(db, [c["id"]])
    c = db.one("SELECT * FROM custom_products WHERE id=?", (int(cid),))
    if c["locked"]:
        raise ValueError(f"잠금이라 내리지 않습니다 ({c['lock_note']}).")
    ok, why = orders.sales_fresh(db, c["store_id"], config.load())
    if not ok:
        raise ValueError(f"{why} — 판매 현황 파일을 넣고 다시 [내리기]")
    store = db.store(c["store_id"], with_secret=True)
    client = naver.make_client(store)
    client.delete_product(c["origin_no"])
    db.x("""UPDATE custom_products SET status='deleted', origin_no='', channel_no='', deleted_at=?, message='내림', updated_at=?
        WHERE id=?""", (time.time(), time.time(), int(cid)))
    return {"ok": True}


# ───────────────────────── 판매 이력 (판매 현황 파일의 주문을 맞춤 상품에도 맞춤)

def match(c, o, store_id=None):
    """주문 → 맞춤 상품 번호 (상품번호·원상품번호·판매자 관리코드가 정확히 같을 때만)."""
    st, sa = ("AND store_id=?", (store_id,)) if store_id else ("", ())
    for col, key in (("channel_no", "channel_no"), ("origin_no", "origin_no"), ("seller_code", "seller_code")):
        v = str(o.get(key) or "").strip()
        if v:
            r = c.execute(f"SELECT id FROM custom_products WHERE {col}=? {st}", (v, *sa)).fetchone()
            if r:
                return r[0]
    return None


def recount(db, ids=None):
    """판매 수·잠금 다시 세기 (취소·반품 뺌, 무시한 주문 뺌). ids 없으면 전부."""
    from .orders import _CANCEL_SQL
    cfg = config.load()
    lock_sold = 1 if cfg.get("lock_sold", True) else 0
    w, a = "", []
    if ids:
        ids = [int(i) for i in ids]
        w, a = f" WHERE id IN ({','.join('?' * len(ids))})", ids
    try:
        db.x(f"""UPDATE custom_products SET
            sold_count=(SELECT COALESCE(SUM(quantity),0) FROM orders o WHERE o.custom_id=custom_products.id AND o.ignored=0
                AND o.status NOT IN {_CANCEL_SQL}),
            cancel_count=(SELECT COALESCE(SUM(quantity),0) FROM orders o WHERE o.custom_id=custom_products.id AND o.ignored=0
                AND o.status IN {_CANCEL_SQL}),
            last_sold_at=(SELECT MAX(ordered_at) FROM orders o WHERE o.custom_id=custom_products.id AND o.ignored=0){w}""", a)
        db.x(f"""UPDATE custom_products SET locked=CASE WHEN ?=1 AND sold_count>0 THEN 1 ELSE 0 END,
            lock_note=CASE WHEN ?=1 AND sold_count>0 THEN '판매 이력 ' || sold_count || '개' ELSE '' END{w}""", (lock_sold, lock_sold, *a))
    except Exception:  # noqa: BLE001 - 표가 아직 없을 때(이전 DB 열기 중)
        pass


def store_counts(db):
    """스토어별 {store_id: {live, since_added(naver_count_at 뒤), since_removed}} — 남은 자리 계산용."""
    out = {}
    try:
        for r in db.q("""SELECT c.store_id, SUM(c.origin_no!='' AND c.status!='deleted') AS live,
                SUM(c.registered_at > COALESCE(s.naver_count_at, 0) AND c.origin_no!='') AS added,
                SUM(c.deleted_at > COALESCE(s.naver_count_at, 0)) AS removed
                FROM custom_products c JOIN stores s ON s.id=c.store_id GROUP BY c.store_id"""):
            out[r["store_id"]] = {"live": r["live"] or 0, "added": r["added"] or 0, "removed": r["removed"] or 0}
    except Exception:  # noqa: BLE001
        pass
    return out


# ───────────────────────── 여러 개를 한 번에 맞춤 상품으로 복사 (복사본·원본에서 고르기)

BULK_MAX = 200


def _bulk_price(price, o):
    """공통 가격 바꾸기: keep 그대로 / set 하나로 / won n원 / pct n% (up 올리기는 100원 올림, down 내리기는 100원 내림)."""
    mode, v = o.get("price_mode") or "keep", float(o.get("price_val") or 0)
    up = (o.get("price_dir") or "down") == "up"
    if mode == "set":
        return convert.round_up(int(v), 100)
    if mode not in ("won", "pct") or v <= 0:
        return int(price)
    d = v if mode == "won" else price * v / 100
    p = price + d if up else price - d
    return convert.round_up(int(p), 100) if up else int(p) // 100 * 100


def bulk_plan(db, kind, ids, o):
    """고른 복사본(kind='listing')·원본(kind='source')마다 맞춤 상품 초안 (저장 안 함). → [{from, view(저장할 값), before, after, error}]"""
    ids = [int(i) for i in ids][:BULK_MAX]
    sid_new = int(o.get("store_id") or 0) or None
    if kind == "source" and not sid_new:
        raise ValueError("원본에서 복사할 때는 스토어를 골라 주세요.")
    if sid_new and not db.store(sid_new):
        raise ValueError("스토어를 찾지 못했습니다.")
    out = []
    for i in ids:
        item = {"from_kind": kind, "from_id": i}
        try:
            v = start(db, source_id=i if kind == "source" else None, listing_id=i if kind == "listing" else None,
                      store_id=sid_new if kind == "source" else None)
            if sid_new and kind == "listing" and sid_new != v["store_id"]:
                st = db.store(sid_new)
                v.update(store_id=sid_new, store_name=st["name"], ship_addr=str(st.get("tpl_ship_addr") or ""),
                         return_addr=str(st.get("tpl_return_addr") or ""))
            before = int(v["price"] or 0)
            v["price"] = _bulk_price(before, o)
            if o.get("ship") not in (None, "", "keep"):
                v["ship_addr"] = str(o.get("ship"))
            if o.get("ret") not in (None, "", "keep"):
                v["return_addr"] = str(o.get("ret"))
            v["show_search"] = int(bool(o.get("show_search")))
            v["memo"] = str(o.get("memo") or "")[:2000]
            item.update(view=v, name=v["name"], store_id=v["store_id"], store_name=v.get("store_name", ""), before=before, after=v["price"])
            if v["price"] < 100:
                item["error"] = "가격이 100원보다 낮아짐"
        except ValueError as e:
            item["error"] = str(e)
        out.append(item)
    return out


def bulk_create(db, kind, ids, o):
    """초안대로 맞춤 상품을 만든다 (안 올림 상태로 저장). 상품명은 원래 이름 그대로. → {made:[{id,name,store_id}], failed:[{name,error}]}"""
    made, failed = [], []
    for it in bulk_plan(db, kind, ids, o):
        if it.get("error"):
            failed.append({"name": it.get("name") or f"#{it['from_id']}", "error": it["error"]})
            continue
        v = it["view"]
        b = {"store_id": v["store_id"], "name": v["name"], "price": v["price"], "stock": v["stock"], "memo": v["memo"],
             "thumbs": v["thumbs"], "detail": v["detail"], "category": v["category"], "ship_addr": v["ship_addr"],
             "return_addr": v["return_addr"], "fee": v["fee"], "follow_rules": True, "origin": v["origin"], "brand": v["brand"],
             "maker": v["maker"], "model": v["model"], "show_search": v["show_search"],
             "from_source_id": v.get("from_source_id"), "from_listing_id": v.get("from_listing_id")}
        try:
            r = save(db, b)   # 옵션은 원본 그대로 (options 안 보냄)
            made.append({"id": r["id"], "name": v["name"], "store_id": v["store_id"], "warnings": r.get("warnings") or []})
        except ValueError as e:
            failed.append({"name": v["name"], "error": str(e)})
    return {"made": made, "failed": failed}


def send_many(db, cids, progress=None, should_stop=None):
    """만든 맞춤 상품들을 차례로 올린다. 한도에 걸린 스토어는 남은 것을 보내지 않음(안 올림으로 둠)."""
    from . import apiuse
    res, paused = [], set()
    n = len(cids)
    for k, cid in enumerate(cids, 1):
        if should_stop and should_stop():
            break
        c = db.one("SELECT name, store_id FROM custom_products WHERE id=?", (int(cid),))
        if not c:
            continue
        if progress:
            progress(k - 1, n, f"맞춤 상품 올리는 중 {k}/{n} · {c['name'][:30]}")
        if c["store_id"] in paused:
            res.append({"id": cid, "name": c["name"], "ok": False, "error": "시간당 한도 — 이 스토어는 나중에 [다시 보내기]"})
            continue
        try:
            r = send(db, cid)
            res.append({"id": cid, "name": c["name"], "ok": True, "url": r.get("url"), "store_id": r.get("store_id"),
                        "product_no": r.get("product_no"), "marketing_link": r.get("marketing_link") or ""})
        except Exception as e:  # noqa: BLE001 - 이 건만 실패
            msg = str(e)
            if "시간당 한도" in msg or isinstance(e, apiuse.QuotaPaused):
                paused.add(c["store_id"])
            res.append({"id": cid, "name": c["name"], "ok": False, "error": msg[:300]})
    ok = sum(1 for r in res if r["ok"])
    return {"results": res, "message": f"맞춤 상품 {ok}/{len(res)}건 올림" + (f" · 실패 {len(res) - ok}건" if len(res) > ok else "")}
