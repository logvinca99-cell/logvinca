"""도둑방지: 처음 올릴 때 가격을 일부러 높여 두었다가(기본 +30,000원) 원래 가격으로 되돌린다.

내 상품을 그대로 베껴 몇천 원 싸게 올리는 판매자가 있으면, 그 사람은 '높여 둔 가격'을 기준으로 내리게 된다.
나중에 내가 원래 가격으로 되돌리면 그쪽보다 싸진다.

되돌리는 때 (먼저 오는 것)
  1. 베낀 상품을 찾았을 때: 내 상품명 그대로 네이버 쇼핑을 검색해, 내 스토어가 아닌 곳에서
     상품명이 거의 같고(기본 80% 이상) 내 높인 가격보다 싼 상품이 보이면 → 바로 되돌림
  2. 정해 둔 날(기본 7일)이 지났을 때
찾은 베낀 상품은 copycats 표에 남겨, 올린 뒤 며칠 만에 베끼는지 도둑방지 화면에서 본다.
"""

import os
import time

from . import keywords, namegen, naver

SCHEMA = """
CREATE TABLE IF NOT EXISTS copycats (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    round INTEGER NOT NULL,
    mall TEXT NOT NULL,
    title TEXT NOT NULL,
    price INTEGER NOT NULL,
    my_price INTEGER NOT NULL,        -- 그때 내 가격 (높여 둔 가격)
    similarity REAL NOT NULL,
    link TEXT NOT NULL,
    image TEXT NOT NULL DEFAULT '',
    product_id TEXT NOT NULL DEFAULT '',
    registered_at REAL,               -- 내 상품을 올린 때 (며칠 만에 베꼈는지)
    found_at REAL NOT NULL,
    UNIQUE(listing_id, product_id, link)
);
CREATE INDEX IF NOT EXISTS copycats_listing ON copycats(listing_id);
"""


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def applies(cfg, t, op):
    """이번 등록에 높인 가격을 쓸까: 처음 올리는 것만(기본), 설정하면 최신화 때도."""
    if not cfg.get("bait_enabled"):
        return 0
    first = op == "create" and int(t.get("round") or 1) == 1
    if not first and not cfg.get("bait_on_refresh"):
        return 0
    return max(0, int(cfg.get("bait_amount") or 0))


def due(db, now=None):
    now = now or time.time()
    return db.q("""SELECT id FROM listings WHERE bait_state='on' AND bait_until<=? AND status='success'
        AND origin_no!=''""", (now,))


def restore(db, ids, reason="", progress=None, should_stop=None):
    """원래 가격으로 되돌린다 (스토어별로). 네이버에 가격만 바꿔 다시 보냄."""
    if not ids:
        return {"restored": 0, "failed": 0, "errors": []}
    rows = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        rows += db.q(f"""SELECT id, store_id, origin_no, price, bait FROM listings
            WHERE id IN ({','.join('?' * len(chunk))}) AND bait_state IN ('on','fail') AND origin_no!=''""", chunk)
    stores = {s["id"]: s for s in db.stores(with_secret=True)}
    clients = {}
    stats = {"restored": 0, "failed": 0, "errors": []}
    for i, r in enumerate(rows, 1):
        if should_stop and should_stop():
            break
        try:
            if r["store_id"] not in clients:
                clients[r["store_id"]] = naver.make_client(stores[r["store_id"]])
            clients[r["store_id"]].update_sale_price(r["origin_no"], r["price"])
            db.x("""UPDATE listings SET bait_state='restored', bait=0, bait_note=?, bait_restored_at=?, updated_at=?
                WHERE id=?""", (reason, time.time(), time.time(), r["id"]))
            stats["restored"] += 1
        except Exception as e:  # noqa: BLE001
            db.x("UPDATE listings SET bait_state='fail', bait_note=? WHERE id=?", (f"되돌리기 실패: {e}"[:300], r["id"]))
            stats["failed"] += 1
            if len(stats["errors"]) < 3:
                stats["errors"].append(str(e)[:200])
        if progress:
            progress(i, len(rows), f"원래 가격으로 {stats['restored']}건")
    return stats


# ───────────────────────── 베낀 상품 찾기

def _fake_copies(name, my_price):
    import hashlib
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    if h % 3:
        return []
    return [{"t": name, "m": "베끼기상회", "p": my_price - 3000 - (h % 5) * 1000, "l": f"https://smartstore.naver.com/copy/{h}",
             "i": "", "id": str(h)}]


def watch(db, cfg, ids=None, progress=None, should_stop=None):
    """높인 가격으로 올라가 있는 복사본마다 내 상품명 그대로 검색해 베낀 상품을 찾는다."""
    import requests
    fake = os.environ.get("UPLOADER_FAKE_API") == "1"
    cid, secret = (cfg.get("naver_client_id") or "").strip(), (cfg.get("naver_client_secret") or "").strip()
    if not (cid and secret) and not fake:
        raise RuntimeError("베낀 상품 찾기에는 네이버 검색 API 키가 필요합니다 (설정 → 네이버 키워드).")
    match = float(cfg.get("bait_copy_match") or 0.8)
    limit = int(cfg.get("bait_watch_limit") or 500)
    sql = """SELECT l.id, l.name, l.price, l.bait, l.round, l.registered_at, l.store_id FROM listings l
        WHERE l.bait_state='on' AND l.status='success' AND l.origin_no!=''"""
    args = []
    if ids:
        sql += f" AND l.id IN ({','.join('?' * len(ids))})"
        args = list(ids)
    rows = db.q(sql + " ORDER BY l.bait_checked_at IS NOT NULL, l.bait_checked_at LIMIT ?", args + [limit])
    mine = {namegen.normalize(s["name"]) for s in db.stores()} | {
        namegen.normalize(s.get("mall_name") or "") for s in db.stores()} - {""}
    s = requests.Session()
    stats = {"checked": 0, "found": 0, "listings": 0, "restored": 0, "errors": 0, "error": ""}
    hit_ids = []
    for i, r in enumerate(rows, 1):
        if should_stop and should_stop():
            break
        my_price = r["price"] + r["bait"]
        try:
            items = _fake_copies(r["name"], my_price) if fake else keywords.search_shop(r["name"], cid, secret, s, 40)
        except Exception as e:  # noqa: BLE001
            stats["errors"] += 1
            stats["error"] = str(e)[:200]
            if "한도" in str(e) or "맞지 않" in str(e):
                break
            continue
        target = namegen.normalize(r["name"])
        found = 0
        for it in items:
            mall = it.get("m") or ""
            if namegen.normalize(mall) in mine:
                continue
            title = it.get("t") or ""
            nt = namegen.normalize(title)
            sim = 1.0 if nt == target else namegen.overlap(title, r["name"])
            if sim < match or not it.get("p") or it["p"] >= my_price:
                continue
            db.x("""INSERT OR IGNORE INTO copycats(listing_id, round, mall, title, price, my_price, similarity, link, image,
                product_id, registered_at, found_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (r["id"], r["round"], mall, title, it["p"], my_price, round(sim, 3), it.get("l") or "", it.get("i") or "",
                  it.get("id") or "", r["registered_at"], time.time()))
            found += 1
        db.x("UPDATE listings SET bait_checked_at=? WHERE id=?", (time.time(), r["id"]))
        stats["checked"] += 1
        if found:
            stats["found"] += found
            stats["listings"] += 1
            hit_ids.append(r["id"])
        if progress:
            progress(i, len(rows), f"베낀 상품 {stats['found']}개")
        if not fake:
            time.sleep(0.1)
    if hit_ids and cfg.get("bait_restore_on_copy", True):
        stats["restored"] = restore(db, hit_ids, "베낀 상품 발견")["restored"]
    return stats


def run_auto(db, cfg, progress=None, should_stop=None):
    """자동: 베낀 상품 찾기(설정 시) → 찾은 것과 기한 지난 것 되돌리기."""
    out = {}
    if cfg.get("bait_watch", True):
        try:
            out = watch(db, cfg, progress=progress, should_stop=should_stop)
        except RuntimeError as e:
            out = {"watch_error": str(e)}
    r = restore(db, [x["id"] for x in due(db)], f"{cfg.get('bait_days')}일 지남", should_stop=should_stop)
    out["restored_due"] = r["restored"]
    out["restore_failed"] = r["failed"]
    return out


def stats(db):
    st = db.one("""SELECT SUM(bait_state='on') AS on_, SUM(bait_state='restored') AS restored,
        SUM(bait_state='fail') AS failed FROM listings""")
    cp = db.q("""SELECT c.listing_id, MIN(c.found_at - c.registered_at) AS delay FROM copycats c
        WHERE c.registered_at IS NOT NULL GROUP BY c.listing_id, c.round""")
    days = [max(0, d["delay"]) / 86400 for d in cp if d["delay"] is not None]
    hist = {}
    for d in days:
        k = min(14, int(d))
        hist[k] = hist.get(k, 0) + 1
    return {"on": st["on_"] or 0, "restored": st["restored"] or 0, "failed": st["failed"] or 0,
            "copied_listings": len(cp), "copycats": db.one("SELECT COUNT(*) AS n FROM copycats")["n"],
            "median_days": sorted(days)[len(days) // 2] if days else None,
            "hist": [{"day": k, "n": hist.get(k, 0)} for k in range(15)]}
