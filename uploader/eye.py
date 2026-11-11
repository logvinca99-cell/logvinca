"""눈검수 기록: 스토어마다 메모·이어서 시작할 자리, 오늘 본·지운 수와 속도, 방금 지운 것 되돌리기.

이어서 시작: '이 쪽 눈검수 완료'를 누를 때마다 그 쪽의 마지막 복사본 번호를 남겨, 다음에 열면 그 뒤부터.
되돌리기: 눈검수에서 지울 때 판매 중인 복사본의 네이버 내리기는 대기에만 넣고('이 쪽 완료·다음'이나 닫을 때 시작),
그 전에 되돌리면 내리기를 취소하고 휴지통으로 간 원본·복사본을 되살린다 — 완전히 원래대로.
지울 때마다 '이번에 지운 것'(휴지통 항목·내리기 건 복사본·원본)을 eye_undo에 남겨, 되돌리기는 그것만 되살린다
(다른 화면·다른 스토어에서 따로 건 내리기나 따로 지운 것은 건드리지 않음).
"""

import statistics
import time

from . import trash
from .db import pack, unpack

SCHEMA = """
CREATE TABLE IF NOT EXISTS eye_state (
    store_id INTEGER PRIMARY KEY,
    memo TEXT NOT NULL DEFAULT '',
    memo_at REAL,
    last_id INTEGER,                    -- 마지막으로 '이 쪽 눈검수 완료'를 누른 쪽의 마지막 복사본 번호 (다음에 그 뒤부터)
    last_at REAL,
    size INTEGER,
    todo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS eye_log (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL,
    at REAL NOT NULL,
    kind TEXT NOT NULL,                 -- page(쪽 완료) / deleted(지움) / undo(되돌림)
    n INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_eye_log ON eye_log(store_id, at);
CREATE TABLE IF NOT EXISTS eye_dead (       -- 눈검수에서 지운 것: 눈검수 쪽에 '삭제됨'으로 그 자리에 계속 (목록이 당겨지지 않게)
    kind TEXT NOT NULL,                     -- listing(복사본) / source(원본)
    ref_id INTEGER NOT NULL,                -- 복사본 번호 또는 원본 번호
    store_id INTEGER NOT NULL DEFAULT 0,    -- 복사본이면 그 스토어, 원본이면 0
    source_id INTEGER,
    name TEXT NOT NULL DEFAULT '',
    thumb TEXT NOT NULL DEFAULT '',
    at REAL NOT NULL,
    PRIMARY KEY (kind, ref_id)
);
CREATE INDEX IF NOT EXISTS ix_eye_dead ON eye_dead(kind, store_id, ref_id);
CREATE INDEX IF NOT EXISTS ix_eye_dead_src ON eye_dead(source_id);
CREATE TABLE IF NOT EXISTS eye_undo (       -- 눈검수에서 한 번 지운 것: 되돌리기는 이 안의 것만
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id INTEGER NOT NULL DEFAULT 0,
    at REAL NOT NULL,
    data BLOB NOT NULL                      -- {sids, trash, drops, drop_sids}
);
"""

KEEP_DAYS = 30

MAX_GAP = 300   # 쪽 사이 5분 넘게 쉰 것은 속도 계산에서 뺌


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)
        if "ticket" not in {r[1] for r in c.execute("PRAGMA table_info(eye_dead)").fetchall()}:
            c.execute("ALTER TABLE eye_dead ADD COLUMN ticket INTEGER")
        c.execute("DELETE FROM eye_undo WHERE at<?", (time.time() - KEEP_DAYS * 86400,))


def _today():
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def _upsert(db, store_id, **kw):
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO eye_state(store_id) VALUES(?)", (store_id,))
        c.execute(f"UPDATE eye_state SET {', '.join(f'{k}=?' for k in kw)} WHERE store_id=?", (*kw.values(), store_id))


def log(db, store_id, kind, n):
    db.x("INSERT INTO eye_log(store_id, at, kind, n) VALUES(?,?,?,?)", (store_id, time.time(), kind, int(n)))


def stats(db, store_id):
    """오늘 이 스토어에서 본 복사본 수(원본 기준 눈검수 표시가 오늘인 것), 지운 수, 한 장에 걸리는 초. store_id=0이면 원본."""
    start = _today()
    if store_id:
        seen = db.one("""SELECT COUNT(*) AS n FROM listings l JOIN sources s ON s.id=l.source_id
            WHERE l.store_id=? AND l.status!='deleted' AND s.eye_at>=?""", (store_id, start))["n"]
    else:
        seen = db.one("SELECT COUNT(*) AS n FROM sources WHERE eye_at>=?", (start,))["n"]
    rows = db.q("SELECT at, kind, n FROM eye_log WHERE store_id=? AND at>=? ORDER BY at", (store_id, start))
    deleted = max(0, sum(r["n"] for r in rows if r["kind"] == "deleted") - sum(r["n"] for r in rows if r["kind"] == "undo"))
    pages = [r for r in rows if r["kind"] == "page" and r["n"]]
    per = [(b["at"] - a["at"]) / b["n"] for a, b in zip(pages, pages[1:]) if 0 < b["at"] - a["at"] <= MAX_GAP]
    return {"today_seen": seen, "today_deleted": deleted, "today_pages": len(pages),
            "sec_per_item": round(statistics.median(per[-20:]), 2) if per else None}


def state(db, store_id):
    s = db.one("SELECT * FROM eye_state WHERE store_id=?", (store_id,)) or {"store_id": store_id, "memo": "", "memo_at": None,
                                                                          "last_id": None, "last_at": None, "size": None, "todo": 0}
    return {**s, "todo": bool(s["todo"]), **stats(db, store_id)}


def save_memo(db, store_id, memo):
    now = time.time()
    _upsert(db, store_id, memo=str(memo or "")[:20000], memo_at=now)
    return {"memo_at": now}


def page_done(db, store_id, last_id, n, size=None, todo=False):
    """쪽 완료: 이어서 시작할 자리와 오늘 기록."""
    _upsert(db, store_id, last_id=int(last_id), last_at=time.time(), size=int(size) if size else None, todo=int(bool(todo)))
    log(db, store_id, "page", n)


def reset_pos(db, store_id):
    _upsert(db, store_id, last_id=None, last_at=None)


def make_ticket(db, store_id, sids, trash_from=None, trash_to=None, drop_ids=()):
    """방금 지운 것 표: 그 요청이 휴지통에 넣은 항목(번호 범위 안에서 고른 원본의 것만)·내리기 건 복사본·내리고 지울 원본."""
    sids = sorted({int(s) for s in sids if s})
    want = set(sids)
    tids = []
    if trash_from is not None and trash_to is not None and want:
        for t in db.q("SELECT id, kind, ref_id, data FROM trash WHERE id>? AND id<=?", (int(trash_from), int(trash_to))):
            src = t["ref_id"] if t["kind"] == "source" else (unpack(t["data"]).get("listing") or {}).get("source_id")
            if src in want:
                tids.append(t["id"])
    drops = [int(i) for i in drop_ids or []]
    drop_sids = [r["id"] for i in range(0, len(sids), 900) for r in db.q(
        f"SELECT id FROM sources WHERE id IN ({','.join('?' * len(sids[i:i + 900]))}) AND drop_pending=1", sids[i:i + 900])]
    if not (tids or drops or drop_sids):
        return None
    with db.tx() as c:
        return c.execute("INSERT INTO eye_undo(store_id, at, data) VALUES(?,?,?)",
                         (int(store_id), time.time(), pack({"sids": sids, "trash": tids, "drops": drops, "drop_sids": drop_sids}))).lastrowid


def add_dead(db, kind, store_id, rows, ticket=None):
    now = time.time()
    with db.tx() as c:
        for r in rows:
            c.execute("""INSERT OR REPLACE INTO eye_dead(kind, ref_id, store_id, source_id, name, thumb, at, ticket) VALUES(?,?,?,?,?,?,?,?)""",
                      (kind, int(r["id"]), int(store_id), int(r.get("source_id") or r["id"]), str(r.get("name") or "")[:300],
                       str(r.get("thumb") or ""), now, ticket))


def dead_map(db, kind, store_id, since=0):
    return {r["ref_id"]: r for r in db.q("SELECT * FROM eye_dead WHERE kind=? AND store_id=? AND at>=?", (kind, store_id, since))}


def drop_dead(db, kind, ids):
    for i in range(0, len(ids), 900):
        ch = ids[i:i + 900]
        db.x(f"DELETE FROM eye_dead WHERE kind=? AND ref_id IN ({','.join('?' * len(ch))})", (kind, *ch))


def undo(db, store_id, ticket, source_ids=None, n=0):
    """눈검수에서 지운 것 되돌리기 — 그때 지운 것(ticket)만. source_ids를 주면 그중 그 원본 것만 (칸 하나 되살리기).
    ① 아직 시작 안 한 그 내리기만 취소 → 판매 중으로 ② 그때 휴지통으로 간 원본·복사본 되살리기
    (복사본만 간 것도: 원본이 있고, 그 스토어에 같은 원본 복사본이 없고, 원본당 최대 복사 수 안이고, 같은 상품번호가 다른 복사본에 없을 때)
    — 내리기가 끝나 나중에 휴지통으로 간 그 원본도 되살림 ③ 이미 네이버에서 내려간 복사본 수('내림'으로 남음 — 다시 올리기로 올림)."""
    st = {"cancelled": 0, "restored": 0, "skipped": 0, "busy": 0, "dropped": 0, "reasons": []}
    t = db.one("SELECT * FROM eye_undo WHERE id=?", (int(ticket or 0),))
    if not t:
        st["skipped"] = 1
        st["reasons"] = ["되돌릴 기록이 없습니다 (30일이 지났거나 예전 버전에서 지운 것) — 휴지통에서 원본을 되살리세요"]
        return st
    d = unpack(t["data"])
    want = {int(x) for x in (source_ids or d["sids"])} & set(d["sids"])
    if not want:
        return st
    drop_sids = sorted(set(d.get("drop_sids") or []) & want)
    drops = d.get("drops") or []
    with db.tx() as c:
        for i in range(0, len(drops), 400):
            ch = drops[i:i + 400]
            m = ",".join("?" * len(ch))
            sm = ",".join("?" * len(want))
            st["cancelled"] += c.execute(f"""UPDATE listings SET status='success', op='create', message=''
                WHERE id IN ({m}) AND source_id IN ({sm}) AND op='delete' AND status IN ('planned','fail') AND origin_no!=''""",
                                         (*ch, *want)).rowcount
            st["busy"] += c.execute(f"""SELECT COUNT(*) FROM listings WHERE id IN ({m}) AND source_id IN ({sm})
                AND op='delete' AND status IN ('queued','running')""", (*ch, *want)).fetchone()[0]
    # 그때 넣은 휴지통 항목 + 내리기가 끝나 뒤에 휴지통으로 간 그 원본(·남은 복사본)
    tids = set()
    for x in db.q(f"SELECT id, kind, ref_id, data FROM trash WHERE id IN ({','.join('?' * len(d['trash'])) or 'NULL'})", d["trash"]):
        src = x["ref_id"] if x["kind"] == "source" else (unpack(x["data"]).get("listing") or {}).get("source_id")
        if src in want:
            tids.add(x["id"])
    if drop_sids:
        for x in db.q("SELECT id, kind, ref_id, data FROM trash WHERE deleted_at>=?", (t["at"] - 1,)):
            src = x["ref_id"] if x["kind"] == "source" else (unpack(x["data"]).get("listing") or {}).get("source_id")
            if src in drop_sids:
                tids.add(x["id"])
    if tids:
        r = trash.restore(db, sorted(tids), allow_listing=True)
        st["restored"], st["skipped"], st["reasons"] = r["restored"], r["skipped"], r["reasons"]
    wl = sorted(want)
    m = ",".join("?" * len(wl))
    if drop_sids:
        dm = ",".join("?" * len(drop_sids))
        # 그 원본에 아직 내리는 중인 것이 없을 때만 '내리고 지우기'를 풂 (내리는 중이면 끝난 뒤 원래대로 정리)
        db.x(f"""UPDATE sources SET drop_pending=0 WHERE id IN ({dm}) AND NOT EXISTS (SELECT 1 FROM listings l
            WHERE l.source_id=sources.id AND l.op='delete' AND l.status IN ('queued','running'))""", drop_sids)
    db.x(f"DELETE FROM eye_dead WHERE source_id IN ({m}) AND ticket=?", (*wl, t["id"]))   # 되살린 것은 '삭제됨' 칸에서 뺌
    if drops:
        st["dropped"] = db.one(f"""SELECT COUNT(*) AS n FROM listings WHERE id IN ({','.join('?' * len(drops))})
            AND source_id IN ({m}) AND status='deleted'""", (*drops, *wl))["n"]
    db.recount_sources(wl)
    log(db, store_id, "undo", n or len(wl))
    return st
