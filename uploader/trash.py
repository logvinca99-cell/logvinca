"""휴지통: 원본·복사본을 지우면 바로 없애지 않고 여기로 옮긴다. 되살리거나 완전히 지울 수 있다.

지울 때 그 줄(원본이면 원본·복사본·이름·지난 회차·AI 키워드)을 통째로 묶어 trash에 넣고 원래 표에서는 뺀다.
그래서 다른 화면·등록은 휴지통에 있는 것을 전혀 보지 않는다.
네이버에 올라가 있거나 처리 중인 복사본은 지우지 않는다 (먼저 '내리기').
"""

import base64
import time

from .db import pack, unpack

SCHEMA = """
CREATE TABLE IF NOT EXISTS trash (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,          -- source(원본) / listing(복사본)
    ref_id INTEGER NOT NULL,     -- 원래 번호
    title TEXT NOT NULL,
    store TEXT NOT NULL DEFAULT '',
    extra TEXT NOT NULL DEFAULT '',
    deleted_at REAL NOT NULL,
    data BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS trash_kind ON trash(kind, deleted_at);
"""


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)
        c.executescript(KEPT_SCHEMA)


KEPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS kept_live (          -- '이 프로그램에서만 빼기'로 뺀, 네이버에서는 판매 중인 상품
    store_id INTEGER NOT NULL,
    channel_no TEXT NOT NULL,
    origin_no TEXT NOT NULL DEFAULT '',
    codes TEXT NOT NULL DEFAULT '[]',            -- 지금·예전 판매자코드들 (다시 가져올 때 엑셀 코드로 이 상품을 찾음)
    manual_lock INTEGER NOT NULL DEFAULT 0,      -- 직접 잠금이었나 (다시 가져오면 되살림)
    at REAL,
    PRIMARY KEY (store_id, channel_no)
);
"""


def remember_live(c, lids):
    """판매 중 복사본을 이 프로그램에서만 뺄 때: 스토어·상품번호·판매자코드·직접 잠금을 남겨 둔다."""
    import json as _json
    for lid in lids:
        l = c.execute("SELECT id, store_id, channel_no, origin_no, seller_code, manual_lock FROM listings WHERE id=?", (lid,)).fetchone()
        if not l or not l["channel_no"]:
            continue
        codes = [l["seller_code"]] + [x[0] for x in c.execute("SELECT seller_code FROM listing_history WHERE listing_id=? AND seller_code!=''", (lid,))]
        c.execute("""INSERT OR REPLACE INTO kept_live(store_id, channel_no, origin_no, codes, manual_lock, at) VALUES(?,?,?,?,?,?)""",
                  (l["store_id"], l["channel_no"], l["origin_no"] or "", _json.dumps([x for x in dict.fromkeys(codes) if x], ensure_ascii=False),
                   int(l["manual_lock"] or 0), time.time()))


def _rows(c, sql, args):
    out = []
    for r in c.execute(sql, args).fetchall():
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, (bytes, bytearray)):
                d[k] = {"__b64": base64.b64encode(v).decode()}
        out.append(d)
    return out


def _val(v):
    return base64.b64decode(v["__b64"]) if isinstance(v, dict) and "__b64" in v else v


def _insert(c, table, row, ignore=True):
    cols = list(row)
    cur = c.execute(f"INSERT {'OR IGNORE ' if ignore else ''}INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                    [_val(row[k]) for k in cols])
    return cur.rowcount


def _chunks(ids, n=400):
    ids = list(ids)
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _busy_listing(r):
    return (r["origin_no"] and r["status"] != "deleted") or r["status"] in ("queued", "running")


# ───────────────────────── 휴지통으로

def trash_sources(db, ids, keep_naver=False):
    """원본을 휴지통으로 (그 원본의 복사본·이름 후보·지난 회차·AI 키워드도 함께).
    네이버에 올라가 있거나 처리 중인 복사본이 있는 원본은 빼고 그 수를 돌려준다.
    keep_naver=True: 네이버에 올라가 있는 복사본이 있어도 이 프로그램에서만 뺀다 (네이버 상품은 그대로 — 내리지 않음). 처리 중인 것은 뺌."""
    st = {"moved": 0, "skipped_live": 0, "skipped_locked": 0}
    now = time.time()
    live_cond = "status IN ('queued','running')" if keep_naver else "(origin_no!='' OR status IN ('queued','running'))"
    for chunk in _chunks(ids):
        m = ",".join("?" * len(chunk))
        locked = {r["source_id"] for r in db.q(f"SELECT DISTINCT source_id FROM listings WHERE source_id IN ({m}) AND locked=1", chunk)}
        busy = {r["source_id"] for r in db.q(f"""SELECT DISTINCT source_id FROM listings WHERE source_id IN ({m})
            AND status!='deleted' AND {live_cond}""", chunk)} - locked
        go = [i for i in chunk if i not in busy and i not in locked]
        st["skipped_live"] += len(busy)
        st["skipped_locked"] += len(locked)   # 판매 이력·직접 잠금이 있는 원본은 지우지 않음 (리뷰·판매 기록 보호)
        with db.tx() as c:
            for sid in go:
                src = _rows(c, "SELECT * FROM sources WHERE id=?", (sid,))
                if not src:
                    continue
                lids = [r["id"] for r in c.execute("SELECT id FROM listings WHERE source_id=?", (sid,)).fetchall()]
                lm = ",".join("?" * len(lids)) or "NULL"
                if keep_naver:
                    remember_live(c, [r["id"] for r in c.execute(f"SELECT id FROM listings WHERE id IN ({lm}) AND origin_no!='' AND status!='deleted'", lids)])
                snap = {"source": src[0],
                        "listings": _rows(c, "SELECT * FROM listings WHERE source_id=?", (sid,)),
                        "names": _rows(c, "SELECT * FROM names WHERE source_id=?", (sid,)),
                        "history": _rows(c, f"SELECT * FROM listing_history WHERE listing_id IN ({lm})", lids),
                        "ctx_kw": _rows(c, "SELECT * FROM ctx_kw WHERE source_id=?", (sid,)),
                        "edit_log": _rows(c, "SELECT * FROM source_edit_log WHERE source_id=?", (sid,)),
                        "price_log": _rows(c, "SELECT * FROM base_price_log WHERE source_id=?", (sid,))}
                stores = [r["name"] for r in c.execute(f"""SELECT t.name FROM listings l JOIN stores t ON t.id=l.store_id
                    WHERE l.id IN ({lm})""", lids).fetchall()]
                extra = f"기준 가격 {src[0]['price']:,}원 · 복사본 {len(lids)}개 함께" + (f" ({', '.join(stores)})" if stores else "")
                n_live = sum(1 for x in snap["listings"] if x["origin_no"] and x["status"] != "deleted")
                if n_live:
                    extra += f" · 판매 중 {n_live}건은 네이버에 그대로 (이 프로그램에서만 뺌)"
                c.execute("INSERT INTO trash(kind, ref_id, title, extra, deleted_at, data) VALUES('source',?,?,?,?,?)",
                          (sid, src[0]["name"], extra, now, pack(snap)))
                # 주문 연결(orders.listing_id)은 그대로 둔다 — 번호를 다시 쓰지 않으므로 되살리면 같은 번호로 다시 이어짐
                c.execute(f"DELETE FROM listing_history WHERE listing_id IN ({lm})", lids)
                for t in ("listings", "names", "ctx_kw", "ai_words", "ai_asked", "source_kw", "source_edit_log", "base_price_log"):
                    c.execute(f"DELETE FROM {t} WHERE source_id=?", (sid,))
                c.execute("DELETE FROM sources WHERE id=?", (sid,))
                st["moved"] += 1
    db.x("DELETE FROM plans WHERE id NOT IN (SELECT DISTINCT plan_id FROM listings WHERE plan_id IS NOT NULL)")
    return st


def trash_listings(db, ids, keep_naver=False):
    """복사본을 휴지통으로 (아직 안 올린 것·내린 것만). 붙어 있던 이름은 원본의 안 쓴 후보로 돌아간다.
    keep_naver=True: 네이버에 올라가 있는 것도 이 프로그램에서만 뺀다 (네이버 상품은 그대로 — 내리지 않음). 처리 중인 것은 뺌."""
    from .inventory import release_name
    st = {"moved": 0, "skipped_live": 0, "skipped_locked": 0}
    now = time.time()
    touched = set()
    for chunk in _chunks(ids):
        m = ",".join("?" * len(chunk))
        rows = db.q(f"""SELECT l.id, l.source_id, l.origin_no, l.status, l.name, l.name_id, l.price, l.round, l.seller_code,
            l.registered_at, l.deleted_at, l.locked, t.name AS store, s.name AS source_name
            FROM listings l JOIN stores t ON t.id=l.store_id JOIN sources s ON s.id=l.source_id WHERE l.id IN ({m})""", chunk)
        st["skipped_locked"] += sum(1 for r in rows if r["locked"])   # 판매 이력·직접 잠금은 지우지 않음
        rows = [r for r in rows if not r["locked"]]
        go = [r for r in rows if not (r["status"] in ("queued", "running") if keep_naver else _busy_listing(r))]
        st["skipped_live"] += len(rows) - len(go)
        with db.tx() as c:
            for r in go:
                if keep_naver and r["origin_no"] and r["status"] != "deleted":
                    remember_live(c, [r["id"]])
                snap = {"listing": _rows(c, "SELECT * FROM listings WHERE id=?", (r["id"],))[0],
                        "history": _rows(c, "SELECT * FROM listing_history WHERE listing_id=?", (r["id"],))}
                snap["source_name"] = r["source_name"]
                day = (lambda t: time.strftime("%Y-%m-%d", time.localtime(t)) if t else "")
                state = (f"내림 {day(r['deleted_at'])}" if r["status"] == "deleted"
                         else "판매 중 — 네이버에 그대로 (이 프로그램에서만 뺌)" if r["origin_no"]
                         else "실패" if r["status"] == "fail" else "등록 대기")
                extra = " · ".join(x for x in (
                    f"원본 #{r['source_id']}", r["seller_code"] or "관리코드 없음(안 올림)", f"{r['round']}회차", state,
                    f"올린 날 {day(r['registered_at'])}" if r["registered_at"] else "", f"{r['price']:,}원",
                    f"지난 회차 {len(snap['history'])}개" if snap["history"] else "") if x)
                c.execute("INSERT INTO trash(kind, ref_id, title, store, extra, deleted_at, data) VALUES('listing',?,?,?,?,?,?)",
                          (r["id"], r["name"], r["store"], extra, now, pack(snap)))
                release_name(c, r["id"])   # 네이버에 올렸던 이름은 다시 쓰지 않게, 안 올린 이름은 후보로
                c.execute("DELETE FROM listing_history WHERE listing_id=?", (r["id"],))
                c.execute("DELETE FROM listings WHERE id=?", (r["id"],))
                st["moved"] += 1
                touched.add(r["source_id"])
    db.recount_sources(touched)
    db.x("DELETE FROM plans WHERE id NOT IN (SELECT DISTINCT plan_id FROM listings WHERE plan_id IS NOT NULL)")
    return st


# ───────────────────────── 되살리기·완전히 지우기

def _cols(c, table):
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def _insert_new(c, table, row, ignore=True):
    """지금 표에 있는 칸만 넣기 (번호가 그새 다른 줄에 쓰였으면 새 번호로). → 새 번호 또는 None(무시됨)"""
    have = _cols(c, table)
    row = {k: v for k, v in row.items() if k in have}
    if "id" in row and c.execute(f"SELECT 1 FROM {table} WHERE id=?", (row["id"],)).fetchone():
        row.pop("id")
    cols = list(row)
    cur = c.execute(f"INSERT {'OR IGNORE ' if ignore else ''}INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                    [_val(row[k]) for k in cols])
    return (row.get("id") or cur.lastrowid) if cur.rowcount else None


def _restore_listing(c, l, history):
    """복사본 한 줄 되살리기 → None(됨) 또는 못 되살린 이유."""
    if not c.execute("SELECT 1 FROM stores WHERE id=?", (l["store_id"],)).fetchone():
        return "그 스토어가 없어짐"
    if not c.execute("SELECT 1 FROM sources WHERE id=?", (l["source_id"],)).fetchone():
        return "원본이 없음 (원본을 먼저 되살리세요)"
    if c.execute("SELECT 1 FROM listings WHERE source_id=? AND store_id=?", (l["source_id"], l["store_id"])).fetchone():
        return "그 스토어에 같은 원본의 복사본(내린 것 포함)이 이미 있음"
    l = dict(l)
    if l.get("plan_id") and not c.execute("SELECT 1 FROM plans WHERE id=?", (l["plan_id"],)).fetchone():
        l["plan_id"] = None   # 그새 없어진 복사 계획
    nid = l.get("name_id")
    if nid and not c.execute("SELECT 1 FROM names WHERE id=? AND source_id=? AND listing_id IS NULL", (nid, l["source_id"])).fetchone():
        # 그 이름을 그새 다른 복사본이 썼거나 지워졌으면(번호가 다른 원본 이름에 쓰였어도) '이름 변경 필요'로 되살린다
        l["name_id"] = None
        src = c.execute("SELECT name FROM sources WHERE id=?", (l["source_id"],)).fetchone()
        l["name"] = src["name"] if src else l["name"]
    new_id = _insert_new(c, "listings", l, ignore=False)
    if not new_id:
        return "넣지 못함"
    if l.get("name_id"):
        c.execute("UPDATE names SET listing_id=? WHERE id=?", (new_id, l["name_id"]))
    for h in history:
        h = {**h, "listing_id": new_id}
        h.pop("id", None)
        _insert_new(c, "listing_history", h)
    return None


def _restore_source(c, d, max_copies):
    """원본(과 그 복사본·이름 후보·AI 키워드·수정 기록) 되살리기 → (원본 번호, None, [못 되살린 복사본 이유]) 또는 (None, 이유, []).
    원본 기준은 상품명(완전히 같음): 그새 같은 상품명의 원본이 들어왔으면 원본째 되살리지 않는다.
    복사본은 원본당 최대 복사 수 안에서만, 그 스토어에 같은 상품번호가 이미 다른 복사본에 연결돼 있으면 빼고 되살린다."""
    from . import convert
    s = dict(d["source"])
    name = str(s.get("name") or "").strip()
    key = s.get("source_key") or ""
    if not key.startswith("n:"):   # 예전 버전의 대표 이미지 열쇠 → 지금 기준(상품명)
        s["source_key"] = key = convert.name_key(name)
    if c.execute("SELECT 1 FROM sources WHERE source_key=? OR name=?", (key, name)).fetchone():
        return None, "상품명이 완전히 같은 원본이 이미 있음 (그새 다시 불러옴)", []
    s["drop_pending"] = 0   # '원본·복사본 모두 삭제'로 왔어도 되살리면 보통 원본
    sid = _insert_new(c, "sources", s, ignore=False)
    name_map = {}
    for n in d["names"]:
        old = n.get("id")
        nid = _insert_new(c, "names", {**n, "listing_id": None if (n.get("listing_id") or 0) > 0 else n.get("listing_id"), "source_id": sid})
        if nid:
            name_map[old] = nid
    hist = {}
    for h in d["history"]:
        hist.setdefault(h["listing_id"], []).append(h)
    skipped, n_ok = [], 0
    for l in sorted(d["listings"], key=lambda x: (not x.get("locked"), not x.get("origin_no"), x["id"])):   # 잠긴·판매 중인 것부터
        if n_ok >= max_copies:
            skipped.append(f"{str(l.get('name') or '')[:20]}: 원본당 최대 복사 수({max_copies})를 넘음")
            continue
        if l.get("channel_no") and c.execute("SELECT 1 FROM listings WHERE store_id=? AND channel_no=? AND status!='deleted'",
                                             (l["store_id"], l["channel_no"])).fetchone():
            skipped.append(f"{str(l.get('name') or '')[:20]}: 이 상품번호는 그 스토어의 다른 복사본에 이미 연결됨")
            continue
        why = _restore_listing(c, {**l, "source_id": sid, "name_id": name_map.get(l.get("name_id"))}, hist.get(l["id"], []))
        if why:
            skipped.append(f"{str(l.get('name') or '')[:20]}: {why}")
            continue
        n_ok += 1
        if l.get("channel_no"):   # '이 프로그램에서만 빼기'로 기억해 둔 것은 다시 관리하므로 지움
            c.execute("DELETE FROM kept_live WHERE store_id=? AND channel_no=?", (l["store_id"], l["channel_no"]))
    for k in d.get("ctx_kw", []):
        _insert_new(c, "ctx_kw", {**k, "source_id": sid})
    for row in d.get("edit_log", []):
        _insert_new(c, "source_edit_log", {**row, "source_id": sid})
    for row in d.get("price_log", []):
        _insert_new(c, "base_price_log", {**row, "source_id": sid})
    return sid, None, skipped


def _restore_one_listing(c, d, max_copies):
    """복사본 한 줄만 되살리기 (눈검수 되돌리기에서만) → None(됨) 또는 이유."""
    l = dict(d["listing"])
    n = c.execute("SELECT COUNT(*) FROM listings WHERE source_id=?", (l["source_id"],)).fetchone()[0]
    if n >= max_copies:
        return f"원본당 최대 복사 수({max_copies})를 넘음 — 그새 다른 스토어로 복사됨"
    if l.get("channel_no") and l.get("status") != "deleted" and c.execute(
            "SELECT 1 FROM listings WHERE store_id=? AND channel_no=? AND status!='deleted'", (l["store_id"], l["channel_no"])).fetchone():
        return "이 상품번호는 그 스토어의 다른 복사본에 이미 연결됨"
    why = _restore_listing(c, l, d.get("history") or [])
    if not why and l.get("channel_no"):
        c.execute("DELETE FROM kept_live WHERE store_id=? AND channel_no=?", (l["store_id"], l["channel_no"]))
    return why


def restore(db, trash_ids, allow_listing=False):
    """휴지통 되살리기 — 원본만 (그 원본의 복사본도 함께 검사해서). 복사본만 따로 되살리기는 없앴다
    (원본당 최대 복사 수를 넘거나, 같은 상품번호가 둘 붙거나, 다른 원본 밑으로 붙는 일이 생겨서):
    안 올린 복사본은 원본에서 다시 복사, 판매 중이던 것은 기존 상품 가져오기로 다시 연결."""
    from . import config, orders
    max_copies = max(1, int(config.load().get("max_copies") or 2))
    st = {"restored": 0, "skipped": 0, "reasons": [], "copy_skipped": 0}
    touched = set()
    items = []
    for chunk in _chunks(trash_ids):
        items += db.q(f"SELECT id, kind, data FROM trash WHERE id IN ({','.join('?' * len(chunk))})", chunk)
    # 원본 먼저 (그 밑에 붙을 복사본이 있으면 원본이 있어야 함)
    for t in sorted(items, key=lambda x: (x["kind"] != "source", x["id"])):
        if t["kind"] != "source" and allow_listing:
            d = unpack(t["data"])
            try:
                with db.tx() as c:
                    why = _restore_one_listing(c, d, max_copies)
                    if why:
                        st["skipped"] += 1
                        st["reasons"].append(f"복사본 '{str(d['listing'].get('name') or '')[:20]}': {why} — 되살리지 않음")
                        continue
                    c.execute("DELETE FROM trash WHERE id=?", (t["id"],))
                    touched.add(d["listing"]["source_id"])
                    st["restored"] += 1
            except Exception as e:  # noqa: BLE001 - 이 항목만 건너뜀
                st["skipped"] += 1
                st["reasons"].append(f"#{t['id']}: 되살리다 오류 — {e}")
            continue
        if t["kind"] != "source":
            st["skipped"] += 1
            st["reasons"].append("복사본만 되살리기는 하지 않습니다 — 원본에서 다시 복사하거나, 판매 중이던 것은 기존 상품 가져오기로 다시 연결하세요")
            continue
        d = unpack(t["data"])
        try:
            with db.tx() as c:   # 한 항목씩 (하나가 막혀도 나머지는 되살림)
                sid, why, skipped = _restore_source(c, d, max_copies)
                if why:
                    st["skipped"] += 1
                    st["reasons"].append(f"원본 '{str(d['source'].get('name') or '')[:30]}': {why} — 되살리지 않음")
                    continue
                touched.add(sid)
                if skipped:
                    st["copy_skipped"] += len(skipped)
                    st["reasons"] += [f"원본 '{str(d['source'].get('name') or '')[:20]}'의 복사본 {x}" for x in skipped]
                c.execute("DELETE FROM trash WHERE id=?", (t["id"],))
                st["restored"] += 1
        except Exception as e:  # noqa: BLE001 - 이 항목만 건너뜀
            st["skipped"] += 1
            st["reasons"].append(f"#{t['id']}: 되살리다 오류 — {e}")
    db.recount_sources(touched)
    if touched:   # 되살린 복사본의 주문(판매 이력)을 다시 맞추고 판매 수·잠금을 다시 셈
        orders.rematch(db)
        lids = [r["id"] for r in db.q(f"SELECT id FROM listings WHERE source_id IN ({','.join('?' * len(touched))})", sorted(touched))]
        if lids:
            orders.recount_sold(db, lids)
    st["reasons"] = st["reasons"][:6]
    return st


def purge(db, trash_ids=None):
    """완전히 지우기 (trash_ids가 없으면 휴지통 비우기)."""
    if trash_ids is None:
        n = db.one("SELECT COUNT(*) AS n FROM trash")["n"]
        db.x("DELETE FROM trash")
        return {"purged": n}
    n = 0
    for chunk in _chunks(trash_ids):
        with db.tx() as c:
            n += c.execute(f"DELETE FROM trash WHERE id IN ({','.join('?' * len(chunk))})", chunk).rowcount
    return {"purged": n}


def listing(db, kind, q="", page=0, size=100):
    w, a = ["kind=?"], [kind]
    if q:
        w.append("(title LIKE ? OR store LIKE ? OR ref_id=?)")
        a += [f"%{q}%", f"%{q}%", int(q) if q.isdigit() else -1]
    where = " WHERE " + " AND ".join(w)
    total = db.one(f"SELECT COUNT(*) AS n FROM trash{where}", a)["n"]
    rows = db.q(f"SELECT id, kind, ref_id, title, store, extra, deleted_at FROM trash{where} ORDER BY deleted_at DESC, id DESC LIMIT ? OFFSET ?",
                (*a, size, page * size))
    return {"rows": rows, "total": total, "counts": counts(db)}


def ids(db, kind, q=""):
    w, a = ["kind=?"], [kind]
    if q:
        w.append("(title LIKE ? OR store LIKE ? OR ref_id=?)")
        a += [f"%{q}%", f"%{q}%", int(q) if q.isdigit() else -1]
    return [r["id"] for r in db.q(f"SELECT id FROM trash WHERE {' AND '.join(w)}", a)]


def detail(db, tid):
    """휴지통 한 항목의 내용 (지운 때의 기록 그대로)."""
    t = db.one("SELECT * FROM trash WHERE id=?", (tid,))
    if not t:
        return None
    d = unpack(t.pop("data"))
    keep = ("id", "store_id", "name", "price", "status", "round", "seller_code", "origin_no", "channel_no",
            "registered_at", "deleted_at", "sold_count")
    if t["kind"] == "source":
        src = {k: d["source"].get(k) for k in ("id", "name", "price", "category", "seller_code")}
        ls = [{k: l.get(k) for k in keep} for l in d["listings"]]
        names = {s["id"]: s["name"] for s in db.q("SELECT id, name FROM stores")}
        for l in ls:
            l["store"] = names.get(l["store_id"], f"스토어 #{l['store_id']}")
        return {**t, "source": src, "listings": ls, "history": d["history"], "names": [n["name"] for n in d["names"]]}
    l = {k: d["listing"].get(k) for k in keep}
    return {**t, "listing": l, "source_name": d.get("source_name", ""), "history": d.get("history", [])}


def counts(db):
    r = db.one("SELECT SUM(kind='source') AS source, SUM(kind='listing') AS listing FROM trash")
    return {"source": r["source"] or 0, "listing": r["listing"] or 0}
