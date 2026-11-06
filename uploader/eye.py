"""눈검수 기록: 스토어마다 메모·이어서 시작할 자리, 오늘 본·지운 수와 속도, 방금 지운 것 되돌리기.

이어서 시작: '이 쪽 눈검수 완료'를 누를 때마다 그 쪽의 마지막 복사본 번호를 남겨, 다음에 열면 그 뒤부터.
되돌리기: 눈검수에서 지울 때 판매 중인 복사본의 네이버 내리기는 대기에만 넣고('이 쪽 완료·다음'이나 닫을 때 시작),
그 전에 되돌리면 내리기를 취소하고 휴지통으로 간 원본·복사본을 되살린다 — 완전히 원래대로.
"""

import statistics
import time

from . import trash
from .db import unpack

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
"""

MAX_GAP = 300   # 쪽 사이 5분 넘게 쉰 것은 속도 계산에서 뺌


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


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


def add_dead(db, kind, store_id, rows):
    now = time.time()
    with db.tx() as c:
        for r in rows:
            c.execute("""INSERT OR REPLACE INTO eye_dead(kind, ref_id, store_id, source_id, name, thumb, at) VALUES(?,?,?,?,?,?,?)""",
                      (kind, int(r["id"]), int(store_id), int(r.get("source_id") or r["id"]), str(r.get("name") or "")[:300],
                       str(r.get("thumb") or ""), now))


def dead_map(db, kind, store_id, since=0):
    return {r["ref_id"]: r for r in db.q("SELECT * FROM eye_dead WHERE kind=? AND store_id=? AND at>=?", (kind, store_id, since))}


def drop_dead(db, kind, ids):
    for i in range(0, len(ids), 900):
        ch = ids[i:i + 900]
        db.x(f"DELETE FROM eye_dead WHERE kind=? AND ref_id IN ({','.join('?' * len(ch))})", (kind, *ch))


def undo(db, store_id, source_ids, since, n=0):
    """방금 지운 것 되돌리기. source_ids: 지운 복사본들의 원본, since: 지운 때(초).
    ① 아직 시작 안 한 네이버 내리기 취소 → 판매 중으로 ② 그 뒤 휴지통으로 간 원본·복사본 되살리기
    ③ 이미 네이버에서 내려간 복사본 수(되살린 원본에 '내림'으로 남음 — 다시 올리기로 올림)."""
    sids = sorted({int(s) for s in source_ids})
    st = {"cancelled": 0, "restored": 0, "skipped": 0, "busy": 0, "dropped": 0}
    if not sids:
        return st
    since = float(since) - 2
    for i in range(0, len(sids), 400):
        chunk = sids[i:i + 400]
        m = ",".join("?" * len(chunk))
        with db.tx() as c:
            st["cancelled"] += c.execute(f"""UPDATE listings SET status='success', op='create', message=''
                WHERE source_id IN ({m}) AND op='delete' AND status IN ('planned','fail') AND origin_no!=''""", chunk).rowcount
        st["busy"] += db.one(f"""SELECT COUNT(*) AS n FROM listings WHERE source_id IN ({m}) AND op='delete'
            AND status IN ('queued','running')""", chunk)["n"]
    want = set(sids)
    tids = []
    for t in db.q("SELECT id, kind, ref_id, data FROM trash WHERE deleted_at>=? ORDER BY id", (since,)):
        if t["kind"] == "source":
            if t["ref_id"] in want:
                tids.append(t["id"])
        elif (unpack(t["data"]).get("listing") or {}).get("source_id") in want:
            tids.append(t["id"])
    if tids:
        r = trash.restore(db, tids)
        st["restored"], st["skipped"] = r["restored"], r["skipped"]
    for i in range(0, len(sids), 400):
        chunk = sids[i:i + 400]
        m = ",".join("?" * len(chunk))
        db.x(f"UPDATE sources SET drop_pending=0 WHERE id IN ({m})", chunk)
        db.x(f"DELETE FROM eye_dead WHERE source_id IN ({m})", chunk)   # 되살린 것은 '삭제됨' 칸에서 뺌
        st["dropped"] += db.one(f"""SELECT COUNT(*) AS n FROM listings WHERE source_id IN ({m}) AND status='deleted'
            AND deleted_at>=?""", (*chunk, since))["n"]
    db.recount_sources(sids)
    log(db, store_id, "undo", n or len(sids))
    return st
