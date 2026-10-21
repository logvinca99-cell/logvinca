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

def trash_sources(db, ids):
    """원본을 휴지통으로 (그 원본의 복사본·이름 후보·지난 회차·AI 키워드도 함께).
    네이버에 올라가 있거나 처리 중인 복사본이 있는 원본은 빼고 그 수를 돌려준다."""
    st = {"moved": 0, "skipped_live": 0}
    now = time.time()
    for chunk in _chunks(ids):
        m = ",".join("?" * len(chunk))
        busy = {r["source_id"] for r in db.q(f"""SELECT DISTINCT source_id FROM listings WHERE source_id IN ({m})
            AND status!='deleted' AND (origin_no!='' OR status IN ('queued','running'))""", chunk)}
        go = [i for i in chunk if i not in busy]
        st["skipped_live"] += len(busy)
        with db.tx() as c:
            for sid in go:
                src = _rows(c, "SELECT * FROM sources WHERE id=?", (sid,))
                if not src:
                    continue
                lids = [r["id"] for r in c.execute("SELECT id FROM listings WHERE source_id=?", (sid,)).fetchall()]
                lm = ",".join("?" * len(lids)) or "NULL"
                snap = {"source": src[0],
                        "listings": _rows(c, "SELECT * FROM listings WHERE source_id=?", (sid,)),
                        "names": _rows(c, "SELECT * FROM names WHERE source_id=?", (sid,)),
                        "history": _rows(c, f"SELECT * FROM listing_history WHERE listing_id IN ({lm})", lids),
                        "ctx_kw": _rows(c, "SELECT * FROM ctx_kw WHERE source_id=?", (sid,))}
                c.execute("INSERT INTO trash(kind, ref_id, title, extra, deleted_at, data) VALUES('source',?,?,?,?,?)",
                          (sid, src[0]["name"], f"복사본 {len(lids)}개 함께", now, pack(snap)))
                c.execute(f"UPDATE orders SET listing_id=NULL WHERE listing_id IN ({lm})", lids)
                c.execute(f"DELETE FROM listing_history WHERE listing_id IN ({lm})", lids)
                for t in ("listings", "names", "ctx_kw", "ai_words", "ai_asked", "source_kw"):
                    c.execute(f"DELETE FROM {t} WHERE source_id=?", (sid,))
                c.execute("DELETE FROM sources WHERE id=?", (sid,))
                st["moved"] += 1
    db.x("DELETE FROM plans WHERE id NOT IN (SELECT DISTINCT plan_id FROM listings WHERE plan_id IS NOT NULL)")
    return st


def trash_listings(db, ids):
    """복사본을 휴지통으로 (아직 안 올린 것·내린 것만). 붙어 있던 이름은 원본의 안 쓴 후보로 돌아간다."""
    st = {"moved": 0, "skipped_live": 0}
    now = time.time()
    touched = set()
    for chunk in _chunks(ids):
        m = ",".join("?" * len(chunk))
        rows = db.q(f"""SELECT l.id, l.source_id, l.origin_no, l.status, l.name, t.name AS store
            FROM listings l JOIN stores t ON t.id=l.store_id WHERE l.id IN ({m})""", chunk)
        go = [r for r in rows if not _busy_listing(r)]
        st["skipped_live"] += len(rows) - len(go)
        with db.tx() as c:
            for r in go:
                snap = {"listing": _rows(c, "SELECT * FROM listings WHERE id=?", (r["id"],))[0],
                        "history": _rows(c, "SELECT * FROM listing_history WHERE listing_id=?", (r["id"],))}
                c.execute("INSERT INTO trash(kind, ref_id, title, store, extra, deleted_at, data) VALUES('listing',?,?,?,?,?,?)",
                          (r["id"], r["name"], r["store"], f"원본 #{r['source_id']}", now, pack(snap)))
                c.execute("UPDATE names SET listing_id=NULL WHERE listing_id=?", (r["id"],))
                c.execute("UPDATE orders SET listing_id=NULL WHERE listing_id=?", (r["id"],))
                c.execute("DELETE FROM listing_history WHERE listing_id=?", (r["id"],))
                c.execute("DELETE FROM listings WHERE id=?", (r["id"],))
                st["moved"] += 1
                touched.add(r["source_id"])
    db.recount_sources(touched)
    db.x("DELETE FROM plans WHERE id NOT IN (SELECT DISTINCT plan_id FROM listings WHERE plan_id IS NOT NULL)")
    return st


# ───────────────────────── 되살리기·완전히 지우기

def _restore_listing(c, l, history):
    """복사본 한 줄 되살리기. 스토어가 없어졌거나 같은 원본이 이미 그 스토어에 있으면 False."""
    if not c.execute("SELECT 1 FROM stores WHERE id=?", (l["store_id"],)).fetchone():
        return False
    if not c.execute("SELECT 1 FROM sources WHERE id=?", (l["source_id"],)).fetchone():
        return False
    if c.execute("SELECT 1 FROM listings WHERE source_id=? AND store_id=? AND status!='deleted'",
                 (l["source_id"], l["store_id"])).fetchone():
        return False
    l = dict(l)
    nid = l.get("name_id")
    if nid and not c.execute("SELECT 1 FROM names WHERE id=? AND listing_id IS NULL", (nid,)).fetchone():
        # 그 이름을 그새 다른 복사본이 썼거나 지워졌으면 '이름 변경 필요'로 되살린다
        l["name_id"] = None
        src = c.execute("SELECT name FROM sources WHERE id=?", (l["source_id"],)).fetchone()
        l["name"] = src["name"] if src else l["name"]
    if c.execute("SELECT 1 FROM listings WHERE id=?", (l["id"],)).fetchone():
        l.pop("id")
    if not _insert(c, "listings", l, ignore=False):
        return False
    new_id = l.get("id") or c.execute("SELECT last_insert_rowid()").fetchone()[0]
    if l.get("name_id"):
        c.execute("UPDATE names SET listing_id=? WHERE id=?", (new_id, l["name_id"]))
    for h in history:
        h = {**h, "listing_id": new_id}
        h.pop("id", None)
        _insert(c, "listing_history", h)
    return True


def restore(db, trash_ids):
    st = {"restored": 0, "skipped": 0, "reasons": []}
    touched = set()
    for chunk in _chunks(trash_ids):
        m = ",".join("?" * len(chunk))
        items = db.q(f"SELECT id, kind, data FROM trash WHERE id IN ({m}) ORDER BY kind DESC, id", chunk)  # 원본 먼저
        with db.tx() as c:
            for t in items:
                d = unpack(t["data"])
                if t["kind"] == "source":
                    s = d["source"]
                    if c.execute("SELECT 1 FROM sources WHERE id=? OR source_key=?", (s["id"], s["source_key"])).fetchone():
                        st["skipped"] += 1
                        st["reasons"].append(f"원본 #{s['id']}: 같은 원본을 그새 다시 불러와서 되살리지 않음")
                        continue
                    _insert(c, "sources", s, ignore=False)
                    for n in d["names"]:
                        n = {**n, "listing_id": None}
                        _insert(c, "names", n)   # 같은 이름을 그새 다른 곳에서 쓰면 건너뜀
                    hist = {}
                    for h in d["history"]:
                        hist.setdefault(h["listing_id"], []).append(h)
                    for l in d["listings"]:
                        _restore_listing(c, l, hist.get(l["id"], []))
                    for k in d.get("ctx_kw", []):
                        _insert(c, "ctx_kw", k)
                    touched.add(s["id"])
                else:
                    l = d["listing"]
                    if not _restore_listing(c, l, d.get("history", [])):
                        st["skipped"] += 1
                        st["reasons"].append(f"복사본 #{l['id']}: 원본·스토어가 없거나 그 스토어에 같은 원본이 이미 있음")
                        continue
                    touched.add(l["source_id"])
                c.execute("DELETE FROM trash WHERE id=?", (t["id"],))
                st["restored"] += 1
    db.recount_sources(touched)
    st["reasons"] = st["reasons"][:5]
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


def counts(db):
    r = db.one("SELECT SUM(kind='source') AS source, SUM(kind='listing') AS listing FROM trash")
    return {"source": r["source"] or 0, "listing": r["listing"] or 0}
