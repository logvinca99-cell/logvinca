"""기록 저장소 (data/inventory.db, SQLite).

sources   원본 상품 (인벤토리). 판매자코드로 구분하고, 다시 불러오면 내용을 갱신한다.
          엑셀 한 줄 전체는 압축해서 data에 둔다 (상품 하나 약 2~3KB).
names     상품명 후보. norm(정규화한 이름)이 표 전체에서 UNIQUE → 모든 스토어에서 이름이 겹치지 않음.
          listing_id가 있으면 그 등록에 쓰인 이름.
stores    스마트스토어 (API 키, 한도)
listings  어떤 원본을 어느 스토어에 어떤 이름·가격으로 올리는지 (스토어+원본은 한 번만)
plans     한 번에 만든 등록 묶음
runs      [등록 시작]을 누를 때마다 한 줄
images    원본 이미지 주소 → 네이버 이미지 주소. scope는 스토어 번호 (상세 이미지는 0: 모든 스토어 공용)
imports   엑셀 불러오기 기록

등록 상태(listings.status)
    planned  계획됨 (등록 대기)
    queued   이번 실행에서 차례를 기다림
    running  등록 중
    success  등록 완료
    fail     실패 (다시 시도 가능)
"""

import json
import os
import sqlite3
import threading
import time
import zlib

from . import config

DB_PATH = os.path.join(config.DATA_DIR, "inventory.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,              -- products / names
    file_name TEXT NOT NULL,
    created_at REAL NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    added INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    category TEXT NOT NULL,
    thumb TEXT NOT NULL,
    option_count INTEGER NOT NULL,
    image_count INTEGER NOT NULL,
    has_video INTEGER NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    data BLOB NOT NULL,
    errors TEXT NOT NULL DEFAULT '[]',
    warnings TEXT NOT NULL DEFAULT '[]',
    valid INTEGER NOT NULL,
    n_listings INTEGER NOT NULL DEFAULT 0,   -- 이 원본으로 만든 등록 수
    n_success INTEGER NOT NULL DEFAULT 0,
    n_free_names INTEGER NOT NULL DEFAULT 0, -- 아직 안 쓴 이름 후보 수
    import_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sources_cat ON sources(category);
CREATE INDEX IF NOT EXISTS sources_listings ON sources(n_listings);
CREATE TABLE IF NOT EXISTS names (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    norm TEXT NOT NULL UNIQUE,
    origin TEXT NOT NULL,            -- original / recombine / import / ai / manual
    listing_id INTEGER,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS names_source ON names(source_id, listing_id);
CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    client_id TEXT NOT NULL DEFAULT '',
    client_secret TEXT NOT NULL DEFAULT '',
    store_url TEXT NOT NULL DEFAULT '',
    as_phone TEXT NOT NULL DEFAULT '',
    capacity INTEGER NOT NULL DEFAULT 10000,
    naver_count INTEGER,             -- 마지막 확인 때 네이버에 있던 상품 수
    naver_count_at REAL,
    enabled INTEGER NOT NULL DEFAULT 1,
    memo TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    created_at REAL NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    name_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    origin_no TEXT NOT NULL DEFAULT '',
    channel_no TEXT NOT NULL DEFAULT '',
    seconds REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(store_id, source_id)
);
CREATE INDEX IF NOT EXISTS listings_status ON listings(status, store_id);
CREATE INDEX IF NOT EXISTS listings_plan ON listings(plan_id);
CREATE INDEX IF NOT EXISTS listings_source ON listings(source_id);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at REAL,
    total INTEGER NOT NULL,
    stores INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 0,
    fail INTEGER NOT NULL DEFAULT 0,
    images INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS images (
    scope INTEGER NOT NULL,
    src TEXT NOT NULL,
    naver_url TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(scope, src)
);
"""


def pack(row):
    return zlib.compress(json.dumps(row, ensure_ascii=False, default=str).encode(), 6)


def unpack(blob):
    return json.loads(zlib.decompress(blob).decode())


class DB:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.lock = threading.RLock()
        self.c = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("PRAGMA synchronous=NORMAL")
        self.c.execute("PRAGMA foreign_keys=ON")
        self.c.execute("PRAGMA cache_size=-65536")  # 64MB
        self.c.executescript(SCHEMA)
        # 프로그램이 등록 도중 꺼졌으면 남은 상태를 되돌린다.
        self.c.execute("UPDATE listings SET status='fail', stage='', message='프로그램이 등록 도중 종료됨' "
                       "WHERE status='running'")
        self.c.execute("UPDATE listings SET status='planned', stage='' WHERE status='queued'")
        self.c.execute("UPDATE runs SET ended_at=started_at WHERE ended_at IS NULL")
        self.c.commit()

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            self.c.commit()
            return cur.lastrowid

    def tx(self):
        """with db.tx() as c: ... 여러 줄을 한 번에 쓴다."""
        return _Tx(self)

    # ── 원본

    def source_row(self, sid):
        r = self.one("SELECT data FROM sources WHERE id=?", (sid,))
        return unpack(r["data"]) if r else None

    def recount_sources(self, ids=None):
        """n_listings / n_success / n_free_names 다시 세기. ids가 없으면 전체."""
        where, args = "", ()
        if ids is not None:
            ids = list(ids)
            if not ids:
                return
            for i in range(0, len(ids), 900):
                chunk = ids[i:i + 900]
                self._recount(f"WHERE id IN ({','.join('?' * len(chunk))})", chunk)
            return
        self._recount(where, args)

    def _recount(self, where, args):
        self.x(f"""UPDATE sources SET
            n_listings=(SELECT COUNT(*) FROM listings l WHERE l.source_id=sources.id),
            n_success=(SELECT COUNT(*) FROM listings l WHERE l.source_id=sources.id AND l.status='success'),
            n_free_names=(SELECT COUNT(*) FROM names n WHERE n.source_id=sources.id AND n.listing_id IS NULL
                          AND (n.origin!='original' OR ?))
            {where}""", (int(bool(config.load().get("use_original_name"))), *args))

    # ── 스토어

    def stores(self, with_secret=False):
        rows = self.q("""
            SELECT s.*,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.status='success') AS n_success,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.status IN ('planned','queued','running')) AS n_pending,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.status='fail') AS n_fail,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.status='success'
                 AND s.naver_count_at IS NOT NULL AND l.updated_at > s.naver_count_at) AS n_success_since
            FROM stores s ORDER BY s.id""")
        for r in rows:
            r["has_keys"] = bool(r["client_id"] and r["client_secret"])
            # 사용량 = 네이버에 있던 수(확인했다면) + 그 뒤 우리가 올린 수 + 대기 중
            base = (r["naver_count"] + r["n_success_since"]) if r["naver_count"] is not None else r["n_success"]
            r["used"] = base + r["n_pending"]
            r["free"] = max(0, r["capacity"] - r["used"])
            if not with_secret:
                r.pop("client_secret")
        return rows

    def store(self, sid, with_secret=False):
        return next((s for s in self.stores(with_secret) if s["id"] == sid), None)

    # ── 이미지

    def image_map(self, scope, srcs):
        out, srcs = {}, list(srcs)
        for i in range(0, len(srcs), 500):
            chunk = srcs[i:i + 500]
            for r in self.q(f"SELECT src, naver_url FROM images WHERE scope=? AND src IN ({','.join('?' * len(chunk))})",
                            (scope, *chunk)):
                out[r["src"]] = r["naver_url"]
        return out

    def save_images(self, scope, pairs):
        now = time.time()
        with self.lock:
            self.c.executemany("INSERT OR REPLACE INTO images(scope, src, naver_url, created_at) VALUES(?,?,?,?)",
                               [(scope, s, n, now) for s, n in pairs])
            self.c.commit()

    # ── 등록

    def set_listing(self, lid, status=None, **fields):
        if status:
            fields["status"] = status
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE listings SET {cols} WHERE id=?", (*fields.values(), lid))

    def recent_seconds(self, limit=200):
        rows = self.q("SELECT seconds FROM listings WHERE status='success' AND seconds IS NOT NULL "
                      "ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [r["seconds"] for r in rows]

    def start_run(self, total, stores, note=""):
        return self.x("INSERT INTO runs(started_at, total, stores, note) VALUES(?,?,?,?)",
                      (time.time(), total, stores, note))

    def end_run(self, rid, ok, fail, images):
        self.x("UPDATE runs SET ended_at=?, ok=?, fail=?, images=? WHERE id=?",
               (time.time(), ok, fail, images, rid))

    def stats(self):
        return self.one("""SELECT
            (SELECT COUNT(*) FROM sources) AS sources,
            (SELECT COUNT(*) FROM sources WHERE valid=1) AS sources_valid,
            (SELECT COUNT(*) FROM names) AS names,
            (SELECT COUNT(*) FROM names WHERE listing_id IS NULL) AS names_free,
            (SELECT COUNT(*) FROM listings WHERE status='success') AS registered,
            (SELECT COUNT(*) FROM listings WHERE status IN ('planned','queued','running')) AS pending,
            (SELECT COUNT(*) FROM listings WHERE status='fail') AS failed,
            (SELECT COUNT(*) FROM images) AS images,
            (SELECT COUNT(*) FROM stores) AS stores""")


class _Tx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        return self.db.c

    def __exit__(self, exc_type, *_):
        try:
            if exc_type:
                self.db.c.rollback()
            else:
                self.db.c.commit()
        finally:
            self.db.lock.release()
