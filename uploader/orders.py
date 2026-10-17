"""판매 이력: 네이버 주문 가져오기, 주문 파일(아바닛 등) 가져오기, 복사본과 맞추기.

판매 이력이 있는 복사본(sold_count > 0)은 새로고침·내리기로 지우지 않는다.

주문 → 복사본 맞추는 순서 (먼저 맞는 것)
    1. 상품번호(채널상품번호): 지금 회차 또는 지난 회차
    2. 판매자 관리코드: 이 프로그램이 붙인 '스토어코드-원본번호-회차'
    3. 원상품번호
    4. 상품명 (같은 스토어 안에서 정확히 같을 때만)
"""

import hashlib
import os
import random
import time

from . import excel, naver

INITIAL_DAYS = 30


def _match(c, o, store_id=None):
    st = "AND l.store_id=?" if store_id else ""
    sa = (store_id,) if store_id else ()
    if o.get("channel_no"):
        r = c.execute(f"SELECT l.id FROM listings l WHERE l.channel_no=? {st}", (o["channel_no"], *sa)).fetchone() \
            or c.execute(f"SELECT l.id FROM listing_history h JOIN listings l ON l.id=h.listing_id "
                         f"WHERE h.channel_no=? {st}", (o["channel_no"], *sa)).fetchone()
        if r:
            return r[0]
    if o.get("seller_code"):
        r = c.execute("SELECT id FROM listings WHERE seller_code=?", (o["seller_code"],)).fetchone() \
            or c.execute("SELECT listing_id FROM listing_history WHERE seller_code=?", (o["seller_code"],)).fetchone()
        if r:
            return r[0]
    if o.get("origin_no"):
        r = c.execute(f"SELECT l.id FROM listings l WHERE l.origin_no=? {st}", (o["origin_no"], *sa)).fetchone() \
            or c.execute(f"SELECT l.id FROM listing_history h JOIN listings l ON l.id=h.listing_id "
                         f"WHERE h.origin_no=? {st}", (o["origin_no"], *sa)).fetchone()
        if r:
            return r[0]
    if o.get("product_name"):
        rows = c.execute(f"SELECT l.id FROM listings l WHERE l.name=? {st}", (o["product_name"], *sa)).fetchall()
        if len(rows) == 1:
            return rows[0][0]
    return None


def save_orders(db, orders, source, store_id=None):
    """주문을 저장하고 복사본과 맞춘다. (새 주문 수, 맞춘 수)"""
    now = time.time()
    new = matched = 0
    touched = set()
    with db.tx() as c:
        for o in orders:
            if not o.get("order_key"):
                continue
            lid = _match(c, o, o.get("store_id") or store_id)
            cur = c.execute("""INSERT OR IGNORE INTO orders(order_key, store_id, listing_id, channel_no, origin_no,
                seller_code, product_name, quantity, status, ordered_at, source, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (o["order_key"], o.get("store_id") or store_id, lid, o.get("channel_no", ""),
                             o.get("origin_no", ""), o.get("seller_code", ""), o.get("product_name", ""),
                             int(o.get("quantity") or 1), o.get("status", ""), o.get("ordered_at"), source, now))
            if cur.rowcount:
                new += 1
            elif lid:
                c.execute("UPDATE orders SET listing_id=? WHERE order_key=? AND listing_id IS NULL", (lid, o["order_key"]))
            if lid:
                matched += 1
                touched.add(lid)
    recount_sold(db, touched)
    return new, matched


def recount_sold(db, listing_ids=None):
    where, args = "", ()
    if listing_ids is not None:
        ids = list(listing_ids)
        if not ids:
            return
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            db.x(f"""UPDATE listings SET
                sold_count=(SELECT COALESCE(SUM(quantity),0) FROM orders o WHERE o.listing_id=listings.id),
                last_sold_at=(SELECT MAX(ordered_at) FROM orders o WHERE o.listing_id=listings.id)
                WHERE id IN ({','.join('?' * len(chunk))})""", chunk)
        return
    db.x(f"""UPDATE listings SET
        sold_count=(SELECT COALESCE(SUM(quantity),0) FROM orders o WHERE o.listing_id=listings.id),
        last_sold_at=(SELECT MAX(ordered_at) FROM orders o WHERE o.listing_id=listings.id){where}""", args)


def rematch(db):
    """아직 복사본을 못 찾은 주문을 다시 맞춘다 (복사본이 나중에 생긴 경우 등)."""
    rows = db.q("SELECT * FROM orders WHERE listing_id IS NULL")
    touched = set()
    with db.tx() as c:
        for o in rows:
            lid = _match(c, o, o.get("store_id"))
            if lid:
                c.execute("UPDATE orders SET listing_id=? WHERE order_key=?", (lid, o["order_key"]))
                touched.add(lid)
    recount_sold(db, touched)
    return len(touched)


# ───────────────────────── 네이버 주문 가져오기

def sync_store(db, store, client, days=None):
    """스토어 하나의 결제된 주문을 마지막으로 가져온 때부터 지금까지 가져온다."""
    now = time.time()
    since = store.get("orders_synced_to") or (now - (days or INITIAL_DAYS) * 86400)
    if os.environ.get("UPLOADER_FAKE_API") == "1":
        orders = _fake_orders(db, store)
    else:
        ids = client.paid_product_order_ids(since, now)
        orders = client.product_order_details(ids) if ids else []
    for o in orders:
        o["store_id"] = store["id"]
    new, matched = save_orders(db, orders, "naver", store["id"])
    db.x("UPDATE stores SET orders_synced_to=? WHERE id=?", (now, store["id"]))
    return {"orders": len(orders), "new": new, "matched": matched}


def sync_stores(db, stores_with_clients, progress=None, should_stop=None, days=None):
    total = {"stores": 0, "orders": 0, "new": 0, "matched": 0, "errors": []}
    for i, (store, client) in enumerate(stores_with_clients, 1):
        if should_stop and should_stop():
            break
        try:
            r = sync_store(db, store, client, days)
            for k in ("orders", "new", "matched"):
                total[k] += r[k]
        except Exception as e:  # noqa: BLE001 - 스토어 하나 실패는 기록하고 계속
            total["errors"].append(f"{store['name']}: {e}")
        total["stores"] += 1
        if progress:
            progress(i, len(stores_with_clients), f"{store['name']} · 새 주문 {total['new']:,}건")
    return total


def _fake_orders(db, store):
    """시연 모드: 판매 중인 복사본 몇 개에 주문이 들어온 것처럼 만든다."""
    rows = db.q("SELECT channel_no, name FROM listings WHERE store_id=? AND origin_no!=''", (store["id"],))
    rnd = random.Random()
    out = []
    for r in rnd.sample(rows, min(len(rows), max(1, len(rows) // 10))) if rows else []:
        out.append({"order_key": f"fake-{store['id']}-{r['channel_no']}-{rnd.randint(1, 10**9)}",
                    "channel_no": r["channel_no"], "product_name": r["name"], "quantity": rnd.randint(1, 3),
                    "status": "PAYED", "ordered_at": time.time() - rnd.randint(0, 20) * 86400})
    return out


# ───────────────────────── 주문 파일 가져오기 (아바닛 등)

COLS = {
    "order_key": ("상품주문번호", "주문상품번호", "주문번호", "주문 번호"),
    "channel_no": ("상품번호", "채널상품번호", "마켓상품번호", "쇼핑몰상품번호"),
    "origin_no": ("원상품번호",),
    "seller_code": ("판매자관리코드", "판매자 관리코드", "판매자상품코드", "자체상품코드", "관리코드", "업체상품코드"),
    "product_name": ("상품명", "주문상품명"),
    "quantity": ("수량", "주문수량"),
    "store": ("스토어", "쇼핑몰", "판매처", "마켓", "몰명", "쇼핑몰명"),
    "ordered_at": ("결제일", "결제일시", "주문일", "주문일시"),
}


def _pick(cols, names):
    for n in names:
        for c in cols:
            if c.replace(" ", "") == n.replace(" ", ""):
                return c
    return None


def import_sales_file(db, fileobj, filename, progress=None, should_stop=None):
    """주문 수집 웹(아바닛 등)에서 내려받은 주문 엑셀/CSV를 판매 이력으로 넣는다."""
    stores = db.stores()
    colmap, batch = None, []
    stats = {"rows": 0, "new": 0, "matched": 0, "unmatched": 0}

    def store_of(v):
        v = str(v or "").strip()
        if not v:
            return None
        for s in stores:
            if v == s["name"] or v == s["code"] or (s["store_url"] and s["store_url"].rstrip("/").endswith("/" + v)):
                return s["id"]
        return None

    def flush():
        new, matched = save_orders(db, batch, "file")
        stats["new"] += new
        stats["matched"] += matched
        batch.clear()

    for row in excel.iter_rows(fileobj, filename, parse=False):
        if colmap is None:
            cols = list(row.keys())
            colmap = {k: _pick(cols, v) for k, v in COLS.items()}
            if not any(colmap[k] for k in ("channel_no", "seller_code", "origin_no", "product_name")):
                raise ValueError("상품번호·판매자관리코드·상품명 중 하나는 있어야 합니다. 이 파일의 열: " + ", ".join(cols))
        g = lambda k: str(row.get(colmap[k]) or "").strip() if colmap[k] else ""  # noqa: E731
        o = {k: g(k) for k in ("channel_no", "origin_no", "seller_code", "product_name")}
        o["channel_no"] = o["channel_no"].split(".")[0]  # 엑셀 숫자 1234.0 → 1234
        o["quantity"] = int(float(g("quantity") or 1)) if g("quantity").replace(".", "").isdigit() else 1
        o["store_id"] = store_of(g("store"))
        o["ordered_at"] = naver.parse_time(g("ordered_at").replace(" ", "T")) if g("ordered_at") else None
        key = g("order_key")
        o["order_key"] = f"file:{key}" if key else "file:" + hashlib.sha1(repr(sorted(row.items())).encode()).hexdigest()[:20]
        o["status"] = "file"
        batch.append(o)
        stats["rows"] += 1
        if len(batch) >= 500:
            flush()
            if progress:
                progress(stats["rows"], None, f"{stats['rows']:,}줄 · 맞춘 주문 {stats['matched']:,}")
        if should_stop and should_stop():
            break
    if batch:
        flush()
    stats["unmatched"] = stats["rows"] - stats["matched"]
    stats["columns"] = {k: v for k, v in (colmap or {}).items() if v}
    return stats
