"""기록 저장소 (data/inventory.db, SQLite).

sources   원본 상품 (인벤토리). 대표 썸네일 주소로 구분하고(source_key), 다시 불러오면 내용을 갱신한다.
          엑셀의 판매자코드는 seller_code에 참고로만 둔다 (스토어마다 바뀌므로 구분에 쓰지 않음).
          엑셀 한 줄 전체는 압축해서 data에 둔다 (상품 하나 약 2~3KB).
names     상품명 후보. norm(정규화한 이름)이 표 전체에서 UNIQUE → 모든 스토어에서 이름이 겹치지 않음.
          listing_id가 있으면 그 등록에 쓰인 이름.
stores    스마트스토어 (API 키, 한도, 짧은 코드)
listings  어떤 원본을 어느 스토어에 어떤 이름·가격으로 올리는지 (스토어+원본은 한 줄)
          내렸다가 다시 올리면 같은 줄의 회차(round)가 올라가고, 지난 회차는 listing_history에 남는다.
          스토어에 등록하는 판매자 관리코드는 '스토어코드-원본번호-회차' (예: S07-0012345-2)
plans     한 번에 만든 등록 묶음
runs      [등록 시작]을 누를 때마다 한 줄
images    원본 이미지 주소 → 네이버 이미지 주소. scope는 스토어 번호 (상세 이미지는 0: 모든 스토어 공용)
imports   엑셀 불러오기 기록
orders    판매 이력 (네이버 주문 가져오기 / 주문 파일 가져오기). 복사본(listing)과 맞춰 sold_count를 센다.
잠금      listings.locked=1이면 최신화·내리기로 지우지 않는다.
          locked = 직접 잠금(manual_lock) 또는 (설정 lock_sold이고 실제 판매 > 0)
          실제 판매 = 취소·반품을 뺀 주문 (설정 lock_canceled_too면 취소·반품만 있어도 잠금)
          판매 이력이 있는 복사본은 최신화·내리기로 지우지 않는다.

등록 상태(listings.status)            할 일(listings.op, planned·fail일 때 의미)
    planned  할 일이 있음 (대기)          create   새로 등록
    queued   이번 실행에서 차례를 기다림    refresh  네이버에서 지우고 같은 내용으로 다시 등록 (최신화)
    running  처리 중                      delete   네이버에서 지움 (내리기)
    success  네이버에 올라가 있음 (판매 중)
    fail     실패 (다시 시도 가능)
    deleted  내림 (네이버에서 지움). 다시 계획하면 같은 줄이 다음 회차로 살아난다.
"""

import json
import os
import re
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
    seller_code TEXT NOT NULL DEFAULT '',
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
    n_listings INTEGER NOT NULL DEFAULT 0,   -- 이 원본이 차지한 스토어 수 (내림 포함)
    n_success INTEGER NOT NULL DEFAULT 0,    -- 그중 네이버에 올라가 있는 수
    n_free_names INTEGER NOT NULL DEFAULT 0, -- 아직 안 쓴 이름 후보 수
    core_kw TEXT NOT NULL DEFAULT '',        -- 핵심 키워드 (네이버 검색으로 찾거나 직접 정함)
    core_manual INTEGER NOT NULL DEFAULT 0,  -- 직접 정했으면 1 (다시 모아도 안 바꿈)
    kw_at REAL,                              -- 네이버 키워드를 모은 때
    import_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sources_cat ON sources(category);
CREATE INDEX IF NOT EXISTS sources_listings ON sources(n_listings);
CREATE INDEX IF NOT EXISTS sources_price ON sources(price);
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
    code TEXT NOT NULL DEFAULT '',          -- 판매자 관리코드 앞자리 (비우면 S + 번호)
    client_id TEXT NOT NULL DEFAULT '',
    client_secret TEXT NOT NULL DEFAULT '',
    store_url TEXT NOT NULL DEFAULT '',
    as_phone TEXT NOT NULL DEFAULT '',
    capacity INTEGER NOT NULL DEFAULT 10000,
    naver_count INTEGER,             -- 마지막 확인 때 네이버에 있던 상품 수
    naver_count_at REAL,
    orders_synced_to REAL,               -- 네이버 주문을 여기까지 가져왔음
    enabled INTEGER NOT NULL DEFAULT 1,
    memo TEXT NOT NULL DEFAULT '',
    importer TEXT NOT NULL DEFAULT '',      -- 원산지 수입사 (비우면 설정 틀 '{store}협력사')
    tpl_top_html TEXT NOT NULL DEFAULT '',  -- 상세페이지 상단 (HTML)
    tpl_bottom_html TEXT NOT NULL DEFAULT '',
    tpl_customs TEXT NOT NULL DEFAULT '',   -- 관부가세 코드 (비우면 설정값)
    tpl_price_pct REAL,                     -- 가격 조정 % (원본가 대비, 비우면 0)
    tpl_discount_pct REAL,                  -- 표시 할인율 % (비우면 할인 없이 원본가 그대로)
    wm_text TEXT NOT NULL DEFAULT '',       -- 워터마크 글자 (비우면 스토어 이름, 로고 PNG가 있으면 로고)
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                     -- 사업자 이름 (상호)
    reg_no TEXT NOT NULL DEFAULT '',        -- 사업자등록번호 (메모용)
    memo TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
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
    name_id INTEGER UNIQUE,                 -- 바꾼 상품명 (names). 비어 있으면 아직 원본 상품명 → '이름 변경 필요', 등록 안 함
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    status TEXT NOT NULL,
    op TEXT NOT NULL DEFAULT 'create',
    round INTEGER NOT NULL DEFAULT 1,
    seller_code TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    origin_no TEXT NOT NULL DEFAULT '',     -- 비어 있지 않으면 지금 네이버에 올라가 있음
    channel_no TEXT NOT NULL DEFAULT '',
    registered_at REAL,                     -- 이번 회차를 올린 때
    deleted_at REAL,
    sold_count INTEGER NOT NULL DEFAULT 0,  -- 판매 수량 (취소·반품 뺀 실제 판매, 모든 회차 합)
    cancel_count INTEGER NOT NULL DEFAULT 0, -- 취소·반품 수량
    last_sold_at REAL,
    manual_lock INTEGER NOT NULL DEFAULT 0, -- 직접 잠금
    locked INTEGER NOT NULL DEFAULT 0,      -- 지금 잠김 (직접 잠금 또는 판매 이력으로 자동 잠금) → 지우지 않음
    lock_note TEXT NOT NULL DEFAULT '',
    bait_want INTEGER NOT NULL DEFAULT 1,   -- 도둑방지로 올릴지 (등록 계획 때 정함, 기본 켬)
    bait INTEGER NOT NULL DEFAULT 0,        -- 도둑방지로 지금 네이버 가격에 더해 둔 금액
    bait_state TEXT NOT NULL DEFAULT '',    -- on(높여 둠) / restored(원래 가격) / fail
    bait_note TEXT NOT NULL DEFAULT '',
    bait_restored_at REAL,
    seconds REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(store_id, source_id)
);
CREATE INDEX IF NOT EXISTS listings_status ON listings(status, store_id);
CREATE INDEX IF NOT EXISTS listings_plan ON listings(plan_id);
CREATE INDEX IF NOT EXISTS listings_source ON listings(source_id);
CREATE TABLE IF NOT EXISTS listing_history (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    round INTEGER NOT NULL,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    seller_code TEXT NOT NULL,
    origin_no TEXT NOT NULL,
    channel_no TEXT NOT NULL,
    registered_at REAL,
    deleted_at REAL NOT NULL,
    reason TEXT NOT NULL            -- refresh / delete
);
CREATE INDEX IF NOT EXISTS history_listing ON listing_history(listing_id);
CREATE INDEX IF NOT EXISTS history_channel ON listing_history(channel_no);
CREATE TABLE IF NOT EXISTS orders (
    order_key TEXT PRIMARY KEY,          -- 상품주문번호 (파일이면 파일 기준으로 만든 값)
    store_id INTEGER,
    listing_id INTEGER,
    channel_no TEXT NOT NULL DEFAULT '',
    origin_no TEXT NOT NULL DEFAULT '',
    seller_code TEXT NOT NULL DEFAULT '',
    product_name TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT '',
    ordered_at REAL,
    source TEXT NOT NULL,                -- naver / file
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_listing ON orders(listing_id);
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
        self._migrate_columns()
        self.c.executescript(SCHEMA)
        self._migrate_columns()   # 새로 만든 db: SCHEMA에 없는 나중에 더한 열도 붙인다
        self._migrate_data()
        from . import activity, aiwords, bulkedit, ctxkw, keywords, kipris, lexicon, mail, trash
        lexicon.ensure(self)
        kipris.ensure(self)
        keywords.ensure(self)
        aiwords.ensure(self)
        ctxkw.ensure(self)
        activity.ensure(self)
        bulkedit.ensure(self)
        mail.ensure(self)
        trash.ensure(self)
        # 프로그램이 등록 도중 꺼졌으면 남은 상태를 되돌린다.
        self.c.execute("UPDATE listings SET status='fail', stage='', message='프로그램이 등록 도중 종료됨' "
                       "WHERE status='running'")
        self.c.execute("UPDATE listings SET status='planned', stage='' WHERE status='queued'")
        self.c.execute("UPDATE runs SET ended_at=started_at WHERE ended_at IS NULL")
        self.c.commit()

    # 예전 버전의 db에 새 열을 더한다 (SCHEMA의 CREATE는 이미 있는 표를 바꾸지 않으므로).
    NEW_COLUMNS = {
        "sources": [("seller_code", "TEXT NOT NULL DEFAULT ''"), ("core_kw", "TEXT NOT NULL DEFAULT ''"),
                    ("core_manual", "INTEGER NOT NULL DEFAULT 0"), ("kw_at", "REAL"),
                    # 직접 고른 네이버 카테고리 (인증 때문에 안 올라가는 카테고리 등) — 엑셀 카테고리 대신 이것으로 검사·등록.
                    # 엑셀을 다시 불러와도 남음
                    ("category_fix", "TEXT NOT NULL DEFAULT ''")],
        "stores": [("code", "TEXT NOT NULL DEFAULT ''"), ("orders_synced_to", "REAL"),
                   ("wm_text", "TEXT NOT NULL DEFAULT ''"), ("importer", "TEXT NOT NULL DEFAULT ''"),
                   # 스토어 템플릿: 상세 상단·하단(HTML), 관부가세 코드, 가격 조정 %, 표시 할인율 % (비우면 설정 공통값)
                   ("tpl_top_html", "TEXT NOT NULL DEFAULT ''"), ("tpl_bottom_html", "TEXT NOT NULL DEFAULT ''"),
                   ("tpl_customs", "TEXT NOT NULL DEFAULT ''"), ("tpl_price_pct", "REAL"), ("tpl_discount_pct", "REAL"),
                   # 출고지·반품지 (네이버 판매자센터 주소록 번호, 비우면 판매자센터 기본 주소)
                   ("tpl_ship_addr", "INTEGER"), ("tpl_return_addr", "INTEGER"),
                   # 가격 흔들기 범위 % (비우면 설정 기본 -3~+3), 흔들면 원본가와 같은 가격은 안 나옴
                   ("tpl_jitter_min", "REAL"), ("tpl_jitter_max", "REAL"),
                   # 사업자 묶음과 순서 (사업자 하나에 스토어 최대 3개)
                   ("business_id", "INTEGER"), ("sort", "INTEGER NOT NULL DEFAULT 0"),
                   # 연결 확인 때 받은 전시중지(고구마)를 뺀 수·전시중지 수, 고구마 수를 직접 넣으면 그 값
                   ("naver_sale", "INTEGER"), ("naver_suspended", "INTEGER"), ("goguma_manual", "INTEGER"),
                   ("naver_status", "TEXT NOT NULL DEFAULT ''"),   # 연결 확인 때 센 상태별 수 (JSON)
                   # 지금 출고 형태 표시: '' 아직 안 정함 · overseas 해외(파란색) · domestic 국내(초록색). 표시만 하고 등록 내용은 바꾸지 않음
                   ("ship_region", "TEXT NOT NULL DEFAULT ''"),
                   ("chrome_profile", "TEXT NOT NULL DEFAULT ''"),
                   ("mail_to", "TEXT NOT NULL DEFAULT ''")],   # 이 스토어 메일을 받는 주소 (예: me+redcoco@gmail.com) — 메일함 스토어 구분용   # 판매자센터를 열 크롬 프로필 폴더 이름 (예: Profile 3)
        "listings": [("sale_shown", "INTEGER"),   # 네이버에 넣은 판매가(도둑방지 뺀 값, 표시 할인 전). 원래 가격으로 되돌릴 때 씀
                     ("sold_count", "INTEGER NOT NULL DEFAULT 0"), ("last_sold_at", "REAL"),
                     ("cancel_count", "INTEGER NOT NULL DEFAULT 0"), ("manual_lock", "INTEGER NOT NULL DEFAULT 0"),
                     ("locked", "INTEGER NOT NULL DEFAULT 0"), ("lock_note", "TEXT NOT NULL DEFAULT ''"),("op", "TEXT NOT NULL DEFAULT 'create'"), ("round", "INTEGER NOT NULL DEFAULT 1"),
                     ("seller_code", "TEXT NOT NULL DEFAULT ''"), ("registered_at", "REAL"), ("deleted_at", "REAL"),
                     ("bait_want", "INTEGER NOT NULL DEFAULT 1"),
                     ("bait", "INTEGER NOT NULL DEFAULT 0"), ("bait_state", "TEXT NOT NULL DEFAULT ''"),
                     ("bait_note", "TEXT NOT NULL DEFAULT ''"), ("bait_restored_at", "REAL"),
                     # 회차 초기화: 판매 중·내린 건을 다음에 다시 올릴 때 회차를 +1 하지 않고 1회차로
                     ("round_reset", "INTEGER NOT NULL DEFAULT 0")],
    }

    def _migrate_columns(self):
        for table, cols in self.NEW_COLUMNS.items():
            have = {r[1] for r in self.c.execute(f"PRAGMA table_info({table})")}
            if not have:
                continue
            for name, decl in cols:
                if name not in have:
                    self.c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def _migrate_data(self):
        ver = self.c.execute("PRAGMA user_version").fetchone()[0]
        if ver < 2:
            # 원본 구분을 판매자코드 → 대표 썸네일로 바꾼다.
            from .convert import source_fingerprint
            rows = self.c.execute("SELECT id, source_key, data FROM sources").fetchall()
            seen = set()
            for r in rows:
                row = unpack(r["data"])
                key = source_fingerprint(row)
                if key in seen:
                    key = f"{key}#{r['id']}"  # 같은 썸네일이 둘이면 따로 둔다
                seen.add(key)
                self.c.execute("UPDATE sources SET source_key=?, seller_code=? WHERE id=?",
                               (key, str(row.get("판매자코드") or ""), r["id"]))
            self.c.execute("UPDATE listings SET registered_at=updated_at WHERE status='success' AND registered_at IS NULL")
            self.c.execute("PRAGMA user_version=2")
        if ver < 3:
            self._v3 = True  # 잠금 열이 새로 생김 → 웹 시작 때 판매 수·잠금을 다시 계산
        self.c.commit()
        self._listing_name_nullable()

    def _listing_name_nullable(self):
        """복사본은 원본 상품명 그대로 만들고 나중에 이름을 바꾸므로 name_id가 비어 있을 수 있게 표를 바꾼다."""
        info = {r[1]: r for r in self.c.execute("PRAGMA table_info(listings)")}
        if "name_id" not in info or not info["name_id"][3]:  # notnull
            return
        sql = self.c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='listings'").fetchone()[0]
        new = re.sub(r"name_id\s+INTEGER\s+NOT\s+NULL\s+UNIQUE", "name_id INTEGER UNIQUE", sql, count=1)
        new = re.sub(r"CREATE TABLE\s+(IF NOT EXISTS\s+)?\"?listings\"?", "CREATE TABLE listings_new", new, count=1)
        self.c.commit()
        self.c.execute("PRAGMA foreign_keys=OFF")
        try:
            self.c.execute("BEGIN")
            self.c.execute(new)
            self.c.execute("INSERT INTO listings_new SELECT * FROM listings")
            self.c.execute("DROP TABLE listings")
            self.c.execute("ALTER TABLE listings_new RENAME TO listings")
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        finally:
            self.c.execute("PRAGMA foreign_keys=ON")
        self.c.executescript(SCHEMA)  # 색인 다시

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
        """원본 엑셀 줄 (직접 고른 카테고리가 있으면 '카테고리'를 그것으로)."""
        from .convert import with_category_fix
        r = self.one("SELECT data, category_fix FROM sources WHERE id=?", (sid,))
        return with_category_fix(unpack(r["data"]), r["category_fix"]) if r else None

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
            n_listings=(SELECT COUNT(*) FROM listings l WHERE l.source_id=sources.id),   -- 내림도 자리를 차지 (원본당 최대 수에 셈)
            n_success=(SELECT COUNT(*) FROM listings l WHERE l.source_id=sources.id AND l.origin_no!=''),
            n_free_names=(SELECT COUNT(*) FROM names n WHERE n.source_id=sources.id AND n.listing_id IS NULL
                          AND (n.origin!='original' OR ?))
            {where}""", (int(bool(config.load().get("use_original_name"))), *args))

    # ── 스토어

    def stores(self, with_secret=False):
        rows = self.q("""
            SELECT s.*,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.origin_no!='') AS n_live,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.origin_no=''
                 AND l.status IN ('planned','queued','running')) AS n_pending,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.origin_no!=''
                 AND l.status IN ('planned','queued','running')) AS n_ops,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.status='fail') AS n_fail,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.status='deleted') AS n_deleted,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.registered_at > s.naver_count_at) AS n_added_since,
              (SELECT COUNT(*) FROM listing_history h JOIN listings l ON l.id=h.listing_id
                 WHERE l.store_id=s.id AND h.deleted_at > s.naver_count_at) AS n_removed_since,
              (SELECT MIN(l.registered_at) FROM listings l WHERE l.store_id=s.id AND l.origin_no!='') AS oldest_at,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.sold_count>0) AS n_sold,
              (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.locked=1 AND l.status!='deleted') AS n_locked,
              b.name AS business_name
            FROM stores s LEFT JOIN businesses b ON b.id=s.business_id
            ORDER BY s.business_id IS NULL, b.sort, b.id, s.sort, s.id""")
        for r in rows:
            r["has_keys"] = bool(r["client_id"] and r["client_secret"])
            r["code"] = r["code"] or f"S{r['id']:02d}"
            r["n_success"] = r["n_live"]
            # 사용량 = 네이버에 있는 수 + 새로 올릴 대기 수
            #   네이버 수를 확인했다면: 확인 때 수 + 그 뒤 올린 수 - 그 뒤 지운 수 (다른 데서 올린 상품 포함)
            #   고구마(전시중지) 상품도 한도를 차지한다: 직접 넣은 수가 있으면 그 수, 없으면 연결 확인 때 받은 수
            r["goguma"] = r["goguma_manual"] if r["goguma_manual"] is not None else (r["naver_suspended"] or 0)
            if r["naver_count"] is not None:
                base = r["naver_count"]
                if r["naver_sale"] is not None:   # 전체 조회 수에 전시중지가 빠져 있어도 맞게
                    base = max(base, r["naver_sale"] + r["goguma"])
                elif r["goguma_manual"] is not None:
                    base = base + r["goguma_manual"]
                live = max(0, base + r["n_added_since"] - r["n_removed_since"])
            else:
                live = r["n_live"] + r["goguma"]
            r["used"] = live + r["n_pending"]
            r["on_naver"] = live
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
            (SELECT COUNT(*) FROM ctx_kw WHERE status='pending') AS ctx_pending,
            (SELECT COUNT(*) FROM trash) AS trash,
            (SELECT COUNT(*) FROM listings WHERE origin_no!='') AS registered,
            (SELECT COUNT(*) FROM listings WHERE status IN ('planned','queued','running')) AS pending,
            (SELECT COUNT(*) FROM listings WHERE status='deleted') AS deleted,
            (SELECT COUNT(*) FROM listings WHERE sold_count>0) AS sold,
            (SELECT COUNT(*) FROM listings WHERE locked=1 AND status!='deleted') AS locked,
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
