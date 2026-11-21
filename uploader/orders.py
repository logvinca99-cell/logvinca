"""판매 이력: 판매 현황(주문) 파일(판매자센터·아바닛 등) 넣기, 직접 확인, 복사본과 맞추기. 네이버에서 주문을 받지 않는다.

판매 이력이 있는 복사본(sold_count > 0)은 최신화·내리기로 지우지 않는다.

주문 → 복사본 맞추는 순서 (먼저 맞는 것)
    1. 상품번호(채널상품번호): 지금 회차 또는 지난 회차
    2. 판매자 관리코드: 이 프로그램이 붙인 '스토어코드-원본번호-회차'
    3. 원상품번호
    4. 상품명 (같은 스토어 안에서 정확히 같을 때만)
"""

import hashlib
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import excel, naver


# 네이버 상품주문 상태 → 화면 글자
STATUS_KO = {
    "PAYMENT_WAITING": "입금 대기", "PAYED": "결제 완료", "DELIVERING": "배송 중", "DELIVERED": "배송 완료",
    "PURCHASE_DECIDED": "구매 확정", "EXCHANGED": "교환", "CANCELED": "취소", "RETURNED": "반품",
    "CANCELED_BY_NOPAYMENT": "미입금 취소", "file": "파일",
}


def _match(c, o, store_id=None):
    st = "AND l.store_id=?" if store_id else ""
    sa = (store_id,) if store_id else ()
    if o.get("channel_no"):
        r = c.execute(f"SELECT l.id FROM listings l WHERE l.channel_no=? {st}", (o["channel_no"], *sa)).fetchone() \
            or c.execute(f"SELECT l.id FROM listing_history h JOIN listings l ON l.id=h.listing_id "
                         f"WHERE h.channel_no=? {st}", (o["channel_no"], *sa)).fetchone()
        if r:
            return r[0]
    if o.get("seller_code"):   # 같은 셀업 판매자코드를 여러 스토어에서 쓸 수 있음 → 스토어 안에서만, 모르면 하나만 맞을 때만
        ids = {x[0] for x in c.execute(f"SELECT l.id FROM listings l WHERE l.seller_code=? {st}", (o["seller_code"], *sa))}
        ids |= {x[0] for x in c.execute(f"SELECT h.listing_id FROM listing_history h JOIN listings l ON l.id=h.listing_id "
                                        f"WHERE h.seller_code=? {st}", (o["seller_code"], *sa))}
        if len(ids) == 1:
            return ids.pop()
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


def save_orders(db, orders, source, store_id=None, import_id=None):
    """주문을 저장하고 복사본과 맞춘다. (새 주문 수, 맞춘 수). import_id: 주문 파일 기록 (파일째 되돌리기용)"""
    now = time.time()
    new = matched = 0
    touched = set()
    with db.tx() as c:
        for o in orders:
            if not o.get("order_key"):
                continue
            lid = _match(c, o, o.get("store_id") or store_id)
            cur = c.execute("""INSERT OR IGNORE INTO orders(order_key, store_id, listing_id, channel_no, origin_no,
                seller_code, product_name, quantity, status, ordered_at, source, created_at, import_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (o["order_key"], o.get("store_id") or store_id or o.get("_store_hint")
                             or (c.execute("SELECT store_id FROM listings WHERE id=?", (lid,)).fetchone() or [None])[0], lid, o.get("channel_no", ""),
                             o.get("origin_no", ""), o.get("seller_code", ""), o.get("product_name", ""),
                             int(o.get("quantity") or 1), o.get("status", ""), o.get("ordered_at"), source, now, import_id))
            if cur.rowcount:
                new += 1
            else:
                # 이미 있던 주문: 상태(취소·반품·구매확정 등)를 최신으로, 못 맞췄던 복사본은 이번에 맞춤
                c.execute("""UPDATE orders SET status=COALESCE(NULLIF(?,''), status),
                    ordered_at=COALESCE(ordered_at, ?), listing_id=COALESCE(listing_id, ?) WHERE order_key=?""",
                          (o.get("status", ""), o.get("ordered_at"), lid, o["order_key"]))
            if lid:
                matched += 1
                touched.add(lid)
    recount_sold(db, touched)
    return new, matched


CANCEL_STATUSES = ("CANCELED", "RETURNED", "CANCELED_BY_NOPAYMENT")
_CANCEL_SQL = "('" + "','".join(CANCEL_STATUSES) + "')"


def recount_sold(db, listing_ids=None):
    """판매 수(취소·반품 뺌)·취소 수를 세고 잠금을 다시 정한다. listing_ids가 없으면 전체."""
    if listing_ids is None:
        _recount(db, "", ())
        return
    ids = list(listing_ids)
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        _recount(db, f" WHERE id IN ({','.join('?' * len(chunk))})", chunk)


def _recount(db, where, args):
    from . import config
    cfg = config.load()
    db.x(f"""UPDATE listings SET
        sold_count=(SELECT COALESCE(SUM(quantity),0) FROM orders o WHERE o.listing_id=listings.id AND o.ignored=0
                    AND o.status NOT IN {_CANCEL_SQL}),
        cancel_count=(SELECT COALESCE(SUM(quantity),0) FROM orders o WHERE o.listing_id=listings.id AND o.ignored=0
                      AND o.status IN {_CANCEL_SQL}),
        last_sold_at=(SELECT MAX(ordered_at) FROM orders o WHERE o.listing_id=listings.id AND o.ignored=0){where}""", args)
    lock_sold = 1 if cfg.get("lock_sold", True) else 0
    canceled_too = 1 if cfg.get("lock_canceled_too") else 0
    db.x(f"""UPDATE listings SET
        locked=CASE WHEN manual_lock=1 THEN 1
                    WHEN ?=1 AND (sold_count>0 OR (?=1 AND cancel_count>0)) THEN 1 ELSE 0 END,
        lock_note=CASE WHEN manual_lock=1 THEN '직접 잠금'
                       WHEN ?=1 AND sold_count>0 THEN '판매 이력 ' || sold_count || '개'
                       WHEN ?=1 AND ?=1 AND cancel_count>0 THEN '취소·반품 이력 ' || cancel_count || '개'
                       ELSE '' END{where}""", (lock_sold, canceled_too, lock_sold, lock_sold, canceled_too, *args))


def set_manual_lock(db, ids, on):
    """직접 잠금/풀기. 판매 이력으로 걸린 자동 잠금은 직접 풀 수 없다 (설정에서 자동 잠금을 꺼야 풀림)."""
    ids = list(ids)
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        db.x(f"UPDATE listings SET manual_lock=? WHERE id IN ({','.join('?' * len(chunk))})", (1 if on else 0, *chunk))
    recount_sold(db, ids)
    still = 0
    if not on and ids:
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            still += db.one(f"SELECT COUNT(*) AS n FROM listings WHERE locked=1 AND id IN ({','.join('?' * len(chunk))})",
                            chunk)["n"]
    return len(ids), still


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


def known_from(store):
    """이 스토어의 판매 이력을 빈틈없이 아는 처음 시각 (모르면 None)."""
    return store.get("orders_from") if store.get("orders_synced_to") else None


def sales_status(db, store_id):
    """그 스토어 판매 중 상품(가져온 것·올린 것 모두)의 판매 이력 확인 상태 — '판매 이력 확인' 창용."""
    st = db.one("SELECT id, name, orders_from, orders_synced_to FROM stores WHERE id=?", (int(store_id),))
    if not st:
        raise ValueError("스토어를 찾지 못했습니다.")
    kf = known_from(st)
    a = db.one("""SELECT COUNT(*) AS n, MIN(registered_at) AS reg_min, SUM(locked=1) AS locked, SUM(manual_lock=1) AS manual,
        SUM(? IS NULL OR registered_at IS NULL OR registered_at < ?) AS need
        FROM listings WHERE store_id=? AND origin_no!='' AND status!='deleted'""",   # 모든 판매 중 상품 (가져온 것·이 프로그램이 올린 것)
               (kf, (kf or 0) - 3600, st["id"]))
    fb = file_breakdown(db, "(o.store_id=? OR o.listing_id IN (SELECT id FROM listings WHERE store_id=?))", (st["id"], st["id"]))
    from . import config
    x = db.one("SELECT sales_checked_at FROM stores WHERE id=?", (st["id"],)) or {}
    fresh, why = sales_fresh(db, st["id"])
    return {"store_id": st["id"], "store": st["name"], "known_from": kf, "synced_to": st["orders_synced_to"],
            "adopted": a["n"] or 0, "reg_min": a["reg_min"], "need": a["need"] or 0, "locked": a["locked"] or 0, "manual": a["manual"] or 0,
            "file_orders": fb["orders"], "file_from": fb["from"], "file_to": fb["to"], "file_listings": fb["copies"],
            "file": fb, "checked_at": x.get("sales_checked_at"),
            "fresh": fresh, "fresh_why": why, "valid_hours": max(1, int(config.load().get("sales_valid_hours") or 24))}


def confirm_sales(db, store_id, from_ts):
    """판매 이력을 직접 확인함 (판매자센터 주문 파일을 넣거나 직접 잠금): 이 스토어는 from_ts부터 판매 이력을 안다.
    마지막 확인 시각(sales_checked_at)도 지금으로 — 유효 시간 안이면 최신화·내리기를 한다."""
    st = db.one("SELECT orders_from, orders_synced_to FROM stores WHERE id=?", (int(store_id),))
    if not st:
        raise ValueError("스토어를 찾지 못했습니다.")
    if not from_ts:
        raise ValueError("날짜를 넣어 주세요.")
    cur = known_from(st)
    new_from = min(from_ts, cur) if cur else from_ts
    db.x("UPDATE stores SET orders_from=?, orders_synced_to=COALESCE(orders_synced_to, ?), sales_checked_at=? WHERE id=?",
         (new_from, time.time(), time.time(), int(store_id)))
    return sales_status(db, store_id)


def sales_fresh(db, store_id, cfg=None):
    """판매 이력을 마지막으로 확인한 지(판매 현황 파일·[판매 이력 확인 완료]) 유효 시간 안인가 → (괜찮나, 이유 문구)."""
    from . import config
    cfg = cfg or config.load()
    hours = max(1, int(cfg.get("sales_valid_hours") or 24))
    st = db.one("SELECT sales_checked_at FROM stores WHERE id=?", (int(store_id),)) or {}
    at = st.get("sales_checked_at")
    if not at:
        return False, f"판매 이력을 아직 확인하지 않음 (유효 {hours}시간)"
    age = (time.time() - float(at)) / 3600
    if age > hours:
        return False, f"판매 이력을 마지막으로 확인한 지 {int(age)}시간 지남 (유효 {hours}시간)"
    return True, ""


def file_breakdown(db, where, args):
    """파일로 넣은 주문 나누기: 주문 n = 복사본에 맞춘 주문 a(복사본 b개, 그중 2건 이상 c개) + 못 맞춘 주문 d.
    where는 orders(별칭 o)에 붙는 조건 (source='file'은 여기서 붙임)."""
    w = f"o.source='file' AND {where}" if where else "o.source='file'"
    t = db.one(f"""SELECT COUNT(*) AS n, SUM(o.listing_id IS NOT NULL) AS a, COUNT(DISTINCT o.listing_id) AS b,
        SUM(o.listing_id IS NULL) AS d, MIN(o.ordered_at) AS mn, MAX(o.ordered_at) AS mx FROM orders o WHERE {w}""", args)
    c = db.one(f"""SELECT COUNT(*) AS c FROM (SELECT o.listing_id FROM orders o WHERE {w} AND o.listing_id IS NOT NULL
        GROUP BY o.listing_id HAVING COUNT(*) >= 2)""", args)["c"]
    return {"orders": t["n"] or 0, "matched": t["a"] or 0, "copies": t["b"] or 0, "multi": c or 0, "unmatched": t["d"] or 0,
            "from": t["mn"], "to": t["mx"]}


def unmatched_orders(db, import_id=None, store_id=None, limit=300):
    """못 맞춘 파일 주문 목록 (상품번호·관리코드·상품명) — 주문 파일 하나 또는 스토어."""
    if import_id:
        w, a = "o.import_id=?", (int(import_id),)
    else:
        w, a = "o.store_id=?", (int(store_id),)
    return db.q(f"""SELECT o.rowid AS id, o.channel_no, o.origin_no, o.seller_code, o.product_name, o.quantity, o.ordered_at, st.name AS store
        FROM orders o LEFT JOIN stores st ON st.id=o.store_id WHERE o.source='file' AND o.listing_id IS NULL AND {w}
        ORDER BY o.ordered_at DESC LIMIT ?""", (*a, int(limit)))


def order_where(f):
    w, a = [], []
    if f.get("store_id"):
        w.append("o.store_id=?")
        a.append(int(f["store_id"]))
    if f.get("from_ts"):
        w.append("COALESCE(o.ordered_at, o.created_at)>=?")
        a.append(float(f["from_ts"]))
    if f.get("to_ts"):
        w.append("COALESCE(o.ordered_at, o.created_at)<?")
        a.append(float(f["to_ts"]))
    if f.get("matched") == "1":
        w.append("o.listing_id IS NOT NULL")
    elif f.get("matched") == "0":
        w.append("o.listing_id IS NULL")
    if f.get("status"):
        w.append("o.status=?")
        a.append(f["status"])
    if f.get("source_id"):
        w.append("l.source_id=?")
        a.append(int(f["source_id"]))
    q = (f.get("q") or "").strip()
    if q:
        w.append("(o.product_name LIKE ? OR o.order_key LIKE ? OR o.seller_code LIKE ? OR o.channel_no=?)")
        a += [f"%{q}%"] * 3 + [q]
    return (" WHERE " + " AND ".join(w)) if w else "", a


def query_orders(db, f, page=0, size=100):
    where, args = order_where(f)
    base = "FROM orders o LEFT JOIN listings l ON l.id=o.listing_id LEFT JOIN stores t ON t.id=o.store_id"
    summary = db.one(f"""SELECT COUNT(*) AS orders, COALESCE(SUM(o.quantity),0) AS quantity,
        SUM(o.listing_id IS NOT NULL) AS matched, SUM(o.listing_id IS NULL) AS unmatched,
        COUNT(DISTINCT o.listing_id) AS copies, COUNT(DISTINCT l.source_id) AS sources,
        SUM(o.status IN ('CANCELED','RETURNED','CANCELED_BY_NOPAYMENT')) AS canceled
        {base}{where}""", args)
    rows = db.q(f"""SELECT o.*, l.name AS listing_name, l.source_id, l.price, l.status AS listing_status,
        t.name AS store_name, COALESCE(NULLIF(t.code,''), 'S'||printf('%02d', t.id)) AS store_code
        {base}{where} ORDER BY COALESCE(o.ordered_at, o.created_at) DESC LIMIT ? OFFSET ?""",
                (*args, size, page * size))
    for r in rows:
        r["status_ko"] = STATUS_KO.get(r["status"], r["status"])
    by_store = db.q(f"""SELECT t.id, t.name, COALESCE(NULLIF(t.code,''), 'S'||printf('%02d', t.id)) AS code,
        COUNT(*) AS orders, COALESCE(SUM(o.quantity),0) AS quantity
        {base}{where} GROUP BY t.id ORDER BY orders DESC""", args)
    return {"rows": rows, "total": summary["orders"], "summary": summary, "by_store": by_store}


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


def import_sales_file(db, fileobj, filename, progress=None, should_stop=None, store_id=None, from_ts=None):
    """주문 수집 웹(아바닛 등)에서 내려받은 주문 엑셀/CSV를 판매 이력으로 넣는다. 파일마다 기록을 남겨 잘못 넣었으면 파일째 되돌린다.
    store_id·from_ts(판매 이력 확인 창에서 넣을 때): 넣은 뒤 그 스토어는 from_ts부터 판매 이력 확인 완료로.
    파일에 주문이 나온 스토어(맞춘 복사본의 스토어)도 '마지막 확인'을 지금으로."""
    stores = db.stores()
    colmap, batch = None, []
    stats = {"rows": 0, "new": 0, "matched": 0, "unmatched": 0}
    iid = db.x("INSERT INTO order_imports(file, created_at) VALUES(?,?)", (str(filename or ""), time.time()))
    stats["import_id"] = iid

    def store_of(v):
        v = str(v or "").strip()
        if not v:
            return None
        for s in stores:
            if v == s["name"] or v == s["code"] or (s["store_url"] and s["store_url"].rstrip("/").endswith("/" + v)):
                return s["id"]
        return None

    def flush():
        new, matched = save_orders(db, batch, "file", import_id=iid)
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
        o["_store_hint"] = int(store_id) if store_id else None   # 못 맞춘 주문을 어느 스토어 것으로 셀지 (이 창의 스토어, 맞추기엔 안 씀)
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
    stats["columns"] = {k: v for k, v in (colmap or {}).items() if v}
    db.x("UPDATE order_imports SET rows=?, new=?, matched=? WHERE id=?", (stats["rows"], stats["new"], stats["matched"], iid))
    # 이 파일로 들어온 주문 나누기 (이미 있던 줄은 새로 안 들어감 → 줄 수 - 새 주문 = 이미 있던 주문)
    fb = file_breakdown(db, "o.import_id=?", (iid,))
    stats.update(matched=fb["matched"], copies=fb["copies"], multi=fb["multi"], unmatched=fb["unmatched"], already=stats["rows"] - stats["new"])
    now = time.time()
    seen = {r["store_id"] for r in db.q("""SELECT DISTINCT l.store_id FROM orders o JOIN listings l ON l.id=o.listing_id
        WHERE o.import_id=?""", (iid,))}
    if store_id:
        if from_ts:
            confirm_sales(db, int(store_id), from_ts)
        seen.add(int(store_id))
        stats["store_id"] = int(store_id)
    for sid in seen:
        db.x("UPDATE stores SET sales_checked_at=? WHERE id=?", (now, sid))
    return stats


# ───────────────────────── 잘못 넣은 판매 이력 바로잡기

def imports_list(db, limit=100):
    """넣은 주문 파일 목록 (되돌릴 수 있는 것: 그 파일로 새로 들어온 주문이 남아 있는 것)."""
    rows = db.q("SELECT * FROM order_imports ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        s = db.one("""SELECT COUNT(*) AS n, COUNT(DISTINCT listing_id) AS copies,
            SUM(CASE WHEN listing_id IS NOT NULL THEN 1 ELSE 0 END) AS matched FROM orders WHERE import_id=? AND source='file'""", (r["id"],))
        r["left"], r["copies"] = s["n"], s["copies"]
        r["undoable"] = bool(s["n"]) and not r["undone_at"]
        fb = file_breakdown(db, "o.import_id=?", (r["id"],))
        r["matched_n"], r["multi"], r["unmatched"] = fb["matched"], fb["multi"], fb["unmatched"]
    return rows


def undo_preview(db, import_id):
    """이 파일을 되돌리면: 지울 주문 수, 영향받는 복사본 수, 그중 잠금이 풀릴 복사본 수 (다른 판매 이력·직접 잠금이 없으면)."""
    imp = db.one("SELECT * FROM order_imports WHERE id=?", (int(import_id),))
    if not imp:
        raise ValueError("그 주문 파일 기록이 없습니다.")
    lids = [r["listing_id"] for r in db.q("SELECT DISTINCT listing_id FROM orders WHERE import_id=? AND source='file' AND listing_id IS NOT NULL",
                                          (imp["id"],))]
    n = db.one("SELECT COUNT(*) AS n FROM orders WHERE import_id=? AND source='file'", (imp["id"],))["n"]
    unlock = 0
    for i in range(0, len(lids), 900):
        ch = lids[i:i + 900]
        m = ",".join("?" * len(ch))
        unlock += db.one(f"""SELECT COUNT(*) AS n FROM listings l WHERE l.id IN ({m}) AND l.locked=1 AND l.manual_lock=0
            AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.listing_id=l.id AND o.ignored=0
                AND (o.import_id IS NULL OR o.import_id!=?) AND o.status NOT IN {_CANCEL_SQL})""", (*ch, imp["id"]))["n"]
    return {"id": imp["id"], "file": imp["file"], "orders": n, "copies": len(lids), "unlock": unlock, "guessed": bool(imp["guessed"])}


def undo_import(db, import_id):
    """주문 파일 되돌리기: 그 파일로 새로 들어온 주문(파일 주문만 — 네이버에서 받은 주문은 그대로)을 지우고 판매 수·잠금을 다시 센다."""
    pv = undo_preview(db, import_id)
    lids = [r["listing_id"] for r in db.q("SELECT DISTINCT listing_id FROM orders WHERE import_id=? AND source='file' AND listing_id IS NOT NULL",
                                          (pv["id"],))]
    with db.tx() as c:
        c.execute("DELETE FROM orders WHERE import_id=? AND source='file'", (pv["id"],))
        c.execute("UPDATE order_imports SET undone_at=? WHERE id=?", (time.time(), pv["id"]))
    recount_sold(db, lids)
    still = 0
    for i in range(0, len(lids), 900):
        ch = lids[i:i + 900]
        still += db.one(f"SELECT COUNT(*) AS n FROM listings WHERE locked=1 AND id IN ({','.join('?' * len(ch))})", ch)["n"]
    return {**pv, "removed": pv["orders"], "still_locked": still, "unlocked": max(0, len(lids) - still) if lids else 0}


def listing_orders(db, lid):
    """이 복사본에 맞춘 주문 (무시한 것 포함)."""
    rows = db.q("""SELECT order_key, product_name, quantity, status, ordered_at, source, ignored, import_id FROM orders
        WHERE listing_id=? ORDER BY COALESCE(ordered_at, created_at) DESC""", (int(lid),))
    for r in rows:
        r["status_ko"] = STATUS_KO.get(r["status"], r["status"])
    return rows


def ignore_listing_orders(db, lid, on=True):
    """복사본 단위: 맞춘 주문을 '무시'로 표시해 판매 수·잠금에서 뺌 (on=False면 무시 풀기 — 다시 판매 이력으로 셈).
    판매 이력 확인 기준(언제부터 주문을 아는지)은 바꾸지 않는다. → (바꾼 주문 수, 지금 잠김 여부, 잠금 이유)"""
    lid = int(lid)
    with db.tx() as c:
        n = c.execute("UPDATE orders SET ignored=?, ignored_at=? WHERE listing_id=? AND ignored=?",
                      (1 if on else 0, time.time() if on else None, lid, 0 if on else 1)).rowcount
    recount_sold(db, [lid])
    l = db.one("SELECT locked, lock_note FROM listings WHERE id=?", (lid,)) or {}
    return n, bool(l.get("locked")), l.get("lock_note") or ""
