"""작업 기록 (data/uploader.db, SQLite).

batches   불러온 엑셀 하나 = 작업 하나
products  엑셀 한 줄 = 상품 하나. 상태와 등록 결과를 담는다
runs      [등록 시작]을 누를 때마다 한 줄. 걸린 시간·성공/실패 수
images    원본 이미지 주소 → 네이버 이미지 주소 (같은 이미지는 다시 올리지 않음)

상품 상태(status)
    ready     검사 통과, 등록 대기
    invalid   검사 오류 (등록 안 함)
    duplicate 같은 판매자코드가 이미 등록됨
    queued    이번 실행에서 등록 차례를 기다림
    running   등록 중
    success   등록 완료
    fail      등록 실패 (다시 시도 가능)
"""

import json
import os
import sqlite3
import threading
import time

from . import config

DB_PATH = os.path.join(config.DATA_DIR, "uploader.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    row_key TEXT, seller_code TEXT, name TEXT, price INTEGER, category TEXT, thumb TEXT,
    option_count INTEGER, image_count INTEGER, has_video INTEGER,
    data TEXT NOT NULL,
    errors TEXT NOT NULL DEFAULT '[]',
    warnings TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    origin_no TEXT NOT NULL DEFAULT '',
    channel_no TEXT NOT NULL DEFAULT '',
    seconds REAL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS products_batch ON products(batch_id, idx);
CREATE INDEX IF NOT EXISTS products_code ON products(seller_code, status);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    started_at REAL NOT NULL,
    ended_at REAL,
    total INTEGER NOT NULL,
    ok INTEGER NOT NULL DEFAULT 0,
    fail INTEGER NOT NULL DEFAULT 0,
    images INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS images (
    src TEXT PRIMARY KEY,
    naver_url TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

PRODUCT_LIST_COLS = ("id, idx, row_key, seller_code, name, price, category, thumb, option_count, "
                     "image_count, has_video, errors, warnings, status, stage, message, origin_no, "
                     "channel_no, seconds, updated_at")


class DB:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.lock = threading.RLock()
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("PRAGMA foreign_keys=ON")
        self.c.executescript(SCHEMA)
        # 프로그램이 등록 도중 꺼졌으면 '등록 중'으로 남은 상품을 실패로 돌린다.
        self.c.execute("UPDATE products SET status='fail', stage='', message='프로그램이 등록 도중 종료됨' "
                       "WHERE status IN ('running')")
        self.c.execute("UPDATE products SET status='ready', stage='' WHERE status='queued'")
        self.c.execute("UPDATE runs SET ended_at=started_at WHERE ended_at IS NULL")
        self.c.commit()

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def x(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            self.c.commit()
            return cur.lastrowid

    # ── 작업

    def add_batch(self, name, items):
        """items: [(summary, row, errors, warnings, status, message)]"""
        now = time.time()
        with self.lock:
            bid = self.c.execute("INSERT INTO batches(name, created_at) VALUES(?, ?)", (name, now)).lastrowid
            self.c.executemany(
                "INSERT INTO products(batch_id, idx, row_key, seller_code, name, price, category, thumb, "
                "option_count, image_count, has_video, data, errors, warnings, status, message, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(bid, i, s["row_key"], s["seller_code"], s["name"], s["price"], s["category"], s["thumb"],
                  s["option_count"], s["image_count"], int(s["has_video"]),
                  json.dumps(row, ensure_ascii=False, default=str),
                  json.dumps(err, ensure_ascii=False), json.dumps(warn, ensure_ascii=False), status, msg, now)
                 for i, (s, row, err, warn, status, msg) in enumerate(items)])
            self.c.commit()
        return bid

    def batches(self):
        return self.q("""
            SELECT b.id, b.name, b.created_at, COUNT(p.id) AS total,
                   SUM(p.status='success') AS success, SUM(p.status='fail') AS fail,
                   SUM(p.status='invalid') AS invalid, SUM(p.status IN ('ready','queued','running')) AS ready,
                   SUM(p.status='duplicate') AS duplicate,
                   (SELECT MAX(started_at) FROM runs r WHERE r.batch_id=b.id) AS last_run
            FROM batches b LEFT JOIN products p ON p.batch_id=b.id
            GROUP BY b.id ORDER BY b.id DESC""")

    def delete_batch(self, bid):
        self.x("DELETE FROM batches WHERE id=?", (bid,))

    # ── 상품

    def products(self, bid):
        rows = self.q(f"SELECT {PRODUCT_LIST_COLS} FROM products WHERE batch_id=? ORDER BY idx", (bid,))
        for r in rows:
            r["errors"], r["warnings"] = json.loads(r["errors"]), json.loads(r["warnings"])
        return rows

    def product(self, pid):
        rows = self.q("SELECT * FROM products WHERE id=?", (pid,))
        if not rows:
            return None
        r = rows[0]
        for k in ("data", "errors", "warnings"):
            r[k] = json.loads(r[k])
        return r

    def set_status(self, pid, status, **fields):
        fields = {"status": status, "updated_at": time.time(), **fields}
        cols = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE products SET {cols} WHERE id=?", (*fields.values(), pid))

    def set_stage(self, pid, stage):
        self.x("UPDATE products SET stage=? WHERE id=?", (stage, pid))

    def registered_codes(self, exclude_batch=None):
        rows = self.q("SELECT DISTINCT seller_code FROM products WHERE status='success' AND seller_code!='' "
                      "AND batch_id IS NOT ?", (exclude_batch,))
        return {r["seller_code"] for r in rows}

    def recent_seconds(self, limit=50):
        """최근 등록에 걸린 시간 (예상 시간 계산용)."""
        rows = self.q("SELECT seconds FROM products WHERE status='success' AND seconds IS NOT NULL "
                      "ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [r["seconds"] for r in rows]

    # ── 실행 기록

    def start_run(self, bid, total, note=""):
        return self.x("INSERT INTO runs(batch_id, started_at, total, note) VALUES(?,?,?,?)",
                      (bid, time.time(), total, note))

    def end_run(self, rid, ok, fail, images):
        self.x("UPDATE runs SET ended_at=?, ok=?, fail=?, images=? WHERE id=?",
               (time.time(), ok, fail, images, rid))

    def runs(self, limit=100):
        return self.q("SELECT r.*, b.name AS batch_name FROM runs r JOIN batches b ON b.id=r.batch_id "
                      "ORDER BY r.id DESC LIMIT ?", (limit,))

    # ── 이미지

    def image_map(self, srcs):
        if not srcs:
            return {}
        out = {}
        srcs = list(srcs)
        for i in range(0, len(srcs), 500):
            chunk = srcs[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self.q(f"SELECT src, naver_url FROM images WHERE src IN ({marks})", chunk):
                out[r["src"]] = r["naver_url"]
        return out

    def save_images(self, pairs):
        now = time.time()
        with self.lock:
            self.c.executemany("INSERT OR REPLACE INTO images(src, naver_url, created_at) VALUES(?,?,?)",
                               [(s, n, now) for s, n in pairs])
            self.c.commit()

    def stats(self):
        r = self.q("SELECT COUNT(*) AS n FROM images")[0]
        p = self.q("SELECT COUNT(*) AS n FROM products WHERE status='success'")[0]
        return {"images": r["n"], "registered": p["n"]}
