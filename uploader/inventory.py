"""인벤토리: 원본 상품 불러오기, 상품명 후보, 등록 계획.

흐름
    1. 엑셀 불러오기 → sources (판매자코드가 같으면 갱신)
    2. 상품명 후보 만들기 → names (재조합 / AI / 외부 파일 가져오기)
    3. 계획 만들기 → listings (원본 × 스토어마다 안 쓴 이름 하나, 스토어별 가격)
    4. 등록 실행 (engine)
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, convert, excel, namegen, naver
from .db import pack, unpack

CHUNK = 500
NAME_ORIGIN_ORDER = {"manual": 0, "import": 1, "ai": 2, "recombine": 3, "original": 4}
ORIGIN_LABEL = {"original": "원본", "recombine": "재조합", "import": "가져옴", "ai": "AI", "manual": "직접"}


def source_key(row):
    for k in ("판매자코드", "상품코드", "사이트상품코드"):
        v = str(row.get(k) or "").strip()
        if v:
            return v
    if row.get("id") not in (None, ""):
        return f"id:{row['id']}"
    return "name:" + namegen.normalize(row.get("상품명"))


def add_names(c, source_id, names, origin, now=None):
    """이름 후보를 넣는다. 모든 스토어 통틀어 정규화 이름이 같은 것은 버린다. (넣은 수, 버린 수)"""
    now = now or time.time()
    added = dup = 0
    for n in names:
        n = namegen.clean(n)
        norm = namegen.normalize(n)
        if not norm:
            continue
        cur = c.execute("INSERT OR IGNORE INTO names(source_id, name, norm, origin, created_at) VALUES(?,?,?,?,?)",
                        (source_id, n, norm, origin, now))
        if cur.rowcount:
            added += 1
        else:
            dup += 1
    return added, dup


# ───────────────────────── 1. 원본 불러오기

def import_products(db, fileobj, filename, progress=None, should_stop=None):
    cfg = config.load()
    categories = naver.cached_categories()
    total_hint = excel.count_rows(fileobj, filename)
    now = time.time()
    iid = db.x("INSERT INTO imports(kind, file_name, created_at) VALUES('products', ?, ?)", (filename, now))
    stats = {"total": 0, "added": 0, "updated": 0, "invalid": 0, "name_dup": 0}
    touched = []
    batch = []

    def flush():
        with db.tx() as c:
            for row in batch:
                key = source_key(row)
                s = convert.summary(row, cfg)
                errors, warnings = convert.validate(row, cfg, categories)
                tags = ",".join(convert.tags(row))
                vals = (s["name"], s["price"], s["category"], s["thumb"], s["option_count"], s["image_count"],
                        int(s["has_video"]), tags, pack(row), json.dumps(errors, ensure_ascii=False),
                        json.dumps(warnings, ensure_ascii=False), int(not errors), iid, now)
                old = c.execute("SELECT id FROM sources WHERE source_key=?", (key,)).fetchone()
                if old:
                    c.execute("""UPDATE sources SET name=?, price=?, category=?, thumb=?, option_count=?,
                        image_count=?, has_video=?, tags=?, data=?, errors=?, warnings=?, valid=?, import_id=?,
                        updated_at=? WHERE id=?""", (*vals, old["id"]))
                    sid = old["id"]
                    stats["updated"] += 1
                else:
                    sid = c.execute("""INSERT INTO sources(name, price, category, thumb, option_count, image_count,
                        has_video, tags, data, errors, warnings, valid, import_id, updated_at, source_key, created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (*vals, key, now)).lastrowid
                    stats["added"] += 1
                if errors:
                    stats["invalid"] += 1
                _, dup = add_names(c, sid, [s["name"]], "original", now)
                if not old:
                    stats["name_dup"] += dup  # 다른 원본과 상품명이 같음
                touched.append(sid)
        batch.clear()

    for row in excel.iter_rows(fileobj, filename):
        if should_stop and should_stop():
            break
        if not row.get("상품명"):
            continue
        batch.append(row)
        stats["total"] += 1
        if len(batch) >= CHUNK:
            flush()
            if progress:
                progress(stats["total"], total_hint, f"{stats['total']:,}개 읽음")
    if batch:
        flush()
    db.recount_sources(touched)
    db.x("UPDATE imports SET total=?, added=?, updated=?, skipped=?, note=? WHERE id=?",
         (stats["total"], stats["added"], stats["updated"], stats["invalid"],
          f"원본 상품명 중복 {stats['name_dup']}개", iid))
    stats["import_id"] = iid
    return stats


def revalidate(db, progress=None):
    """카테고리 목록이나 설정이 바뀐 뒤 전체 원본을 다시 검사한다."""
    cfg = config.load()
    categories = naver.cached_categories()
    ids = [r["id"] for r in db.q("SELECT id FROM sources")]
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        rows = db.q(f"SELECT id, data FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        with db.tx() as c:
            for r in rows:
                row = unpack(r["data"])
                errors, warnings = convert.validate(row, cfg, categories)
                c.execute("UPDATE sources SET errors=?, warnings=?, valid=?, image_count=? WHERE id=?",
                          (json.dumps(errors, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False),
                           int(not errors), len(convert.images_to_upload(row, cfg)), r["id"]))
        if progress:
            progress(min(i + CHUNK, len(ids)), len(ids), "다시 검사 중")
    db.recount_sources()
    return {"total": len(ids)}


# ───────────────────────── 원본 찾기 (화면 목록, 계획 대상)

def source_where(f):
    """화면의 거르기 조건 → SQL WHERE."""
    w, a = [], []
    q = (f.get("q") or "").strip()
    if q:
        w.append("(name LIKE ? OR source_key LIKE ? OR category LIKE ?)")
        a += [f"%{q}%"] * 3
    st = f.get("status") or "all"
    if st == "valid":
        w.append("valid=1")
    elif st == "invalid":
        w.append("valid=0")
    elif st == "unlisted":
        w.append("valid=1 AND n_listings=0")
    elif st == "listed":
        w.append("n_listings>0")
    elif st == "names_short":
        w.append("valid=1 AND n_free_names < ?")
        a.append(int(f.get("min_names") or 3))
    elif st == "warn":
        w.append("valid=1 AND warnings!='[]'")
    if f.get("category"):
        w.append("category LIKE ?")
        a.append(f"{f['category']}%")
    if f.get("store_missing"):
        w.append("id NOT IN (SELECT source_id FROM listings WHERE store_id=?)")
        a.append(int(f["store_missing"]))
    if f.get("store_has"):
        w.append("id IN (SELECT source_id FROM listings WHERE store_id=?)")
        a.append(int(f["store_has"]))
    if f.get("import_id"):
        w.append("import_id=?")
        a.append(int(f["import_id"]))
    if f.get("max_listings") not in (None, ""):
        w.append("n_listings<=?")
        a.append(int(f["max_listings"]))
    if f.get("ids"):
        ids = [int(i) for i in f["ids"]]
        w.append(f"id IN ({','.join('?' * len(ids))})")
        a += ids
    return (" WHERE " + " AND ".join(w)) if w else "", a


LIST_COLS = ("id, source_key, name, price, category, thumb, option_count, image_count, has_video, errors, "
             "warnings, valid, n_listings, n_success, n_free_names, updated_at")


def query_sources(db, f, page=0, size=100):
    where, args = source_where(f)
    total = db.one(f"SELECT COUNT(*) AS n FROM sources{where}", args)["n"]
    rows = db.q(f"SELECT {LIST_COLS} FROM sources{where} ORDER BY id LIMIT ? OFFSET ?",
                (*args, size, page * size))
    for r in rows:
        r["errors"], r["warnings"] = json.loads(r["errors"]), json.loads(r["warnings"])
    return {"rows": rows, "total": total}


def source_ids(db, f):
    where, args = source_where(f)
    return [r["id"] for r in db.q(f"SELECT id FROM sources{where} ORDER BY id", args)]


def source_counts(db):
    return db.one("""SELECT COUNT(*) AS all_, SUM(valid=1) AS valid, SUM(valid=0) AS invalid,
        SUM(valid=1 AND n_listings=0) AS unlisted, SUM(n_listings>0) AS listed,
        SUM(valid=1 AND n_free_names<3) AS names_short, SUM(valid=1 AND warnings!='[]') AS warn
        FROM sources""")


# ───────────────────────── 2. 상품명 후보

def _siblings(c, sid):
    return [r["name"] for r in c.execute("SELECT name FROM names WHERE source_id=?", (sid,))]


def generate_recombine(db, ids, per_source, progress=None, should_stop=None):
    """원본마다 안 쓴 이름 후보가 per_source개가 되도록 재조합으로 채운다."""
    cfg = config.load()
    use_orig = int(bool(cfg.get("use_original_name")))
    stats = {"sources": 0, "added": 0, "short": 0}
    for i in range(0, len(ids), CHUNK):
        if should_stop and should_stop():
            break
        chunk = ids[i:i + CHUNK]
        rows = db.q(f"SELECT id, name, tags, n_free_names FROM sources WHERE id IN ({','.join('?' * len(chunk))})",
                    chunk)
        with db.tx() as c:
            for r in rows:
                free = c.execute("SELECT COUNT(*) FROM names WHERE source_id=? AND listing_id IS NULL "
                                 "AND (origin!='original' OR ?)", (r["id"], use_orig)).fetchone()[0]
                need = per_source - free
                stats["sources"] += 1
                if need <= 0:
                    continue
                got = 0
                for attempt in range(3):
                    sibs = _siblings(c, r["id"])
                    cands = namegen.recombine(r["name"], need - got, set(), sibs, cfg,
                                              seed=f"{r['id']}:{len(sibs)}:{attempt}",
                                              tag_words=[t for t in r["tags"].split(",") if t])
                    if not cands:
                        break
                    added, _ = add_names(c, r["id"], cands, "recombine")
                    got += added
                    if got >= need:
                        break
                stats["added"] += got
                if got < need:
                    stats["short"] += 1
        db.recount_sources(chunk)
        if progress:
            progress(min(i + CHUNK, len(ids)), len(ids), f"새 이름 {stats['added']:,}개")
    return stats


def generate_ai(db, ids, per_source, progress=None, should_stop=None):
    """AI로 원본마다 이름 per_source개를 더 만든다."""
    cfg = config.load()
    namer = namegen.FakeAiNamer(cfg) if os.environ.get("UPLOADER_FAKE_API") == "1" else namegen.AiNamer(cfg)
    per_call = max(1, min(int(cfg.get("ai_products_per_call") or 20), 50))
    workers = max(1, min(int(cfg.get("ai_workers") or 4), 16))
    stats = {"sources": 0, "added": 0, "dup": 0, "failed": 0, "errors": []}
    groups = [ids[i:i + per_call] for i in range(0, len(ids), per_call)]

    def work(group):
        rows = db.q(f"SELECT id, name, category, tags FROM sources WHERE id IN ({','.join('?' * len(group))})", group)
        items = [{"key": str(r["id"]), "name": r["name"], "category": r["category"],
                  "tags": [t for t in r["tags"].split(",") if t]} for r in rows]
        return namer.name_batch(items, per_source)

    done = 0
    with ThreadPoolExecutor(workers) as pool:
        futs = {}
        it = iter(groups)
        for g in it:
            futs[pool.submit(work, g)] = g
            if len(futs) >= workers * 2:
                break
        while futs:
            fut = next(as_completed(futs))
            g = futs.pop(fut)
            try:
                result = fut.result()
                with db.tx() as c:
                    for sid in g:
                        added, dup = add_names(c, sid, result.get(str(sid), []), "ai")
                        stats["added"] += added
                        stats["dup"] += dup
                db.recount_sources(g)
            except Exception as e:  # noqa: BLE001 - 한 묶음 실패는 기록하고 계속
                if type(e).__name__ in ("AuthenticationError", "PermissionDeniedError"):
                    raise RuntimeError("Anthropic API 키가 올바르지 않거나 권한이 없습니다. 설정에서 키를 확인하세요.")
                stats["failed"] += len(g)
                if len(stats["errors"]) < 5:
                    stats["errors"].append(str(e)[:300])
            done += len(g)
            stats["sources"] = done
            if progress:
                u = namer.usage
                progress(done, len(ids), f"새 이름 {stats['added']:,}개 · 입력 {u['input']:,} / 출력 {u['output']:,} 토큰")
            if not (should_stop and should_stop()):
                nxt = next(it, None)
                if nxt:
                    futs[pool.submit(work, nxt)] = nxt
    stats["usage"] = namer.usage
    return stats


NAME_KEY_COLS = ("판매자코드", "상품코드", "원본코드", "sellerCode", "id")


def import_names(db, fileobj, filename, progress=None, should_stop=None):
    """외부 AI 도구 등에서 만든 상품명 파일을 이름 후보로 넣는다.

    원본을 찾는 열: 판매자코드 / 상품코드 / 원본코드 / id 중 있는 것, 없으면 '원본상품명'.
    이름 열: 열 이름에 '상품명'이 들어간 열 (원본·기존 상품명 열은 제외). 여러 열이면 모두 후보로.
    한 칸에 여러 이름을 줄바꿈이나 | 로 넣어도 된다.
    """
    now = time.time()
    iid = db.x("INSERT INTO imports(kind, file_name, created_at) VALUES('names', ?, ?)", (filename, now))
    stats = {"rows": 0, "added": 0, "dup": 0, "not_found": 0, "same_as_original": 0}
    key_col = name_cols = None
    by_name = False
    batch = []

    def flush():
        with db.tx() as c:
            for key, names in batch:
                if by_name:
                    src = c.execute("SELECT id, name FROM sources WHERE id IN (SELECT source_id FROM names "
                                    "WHERE norm=? AND origin='original')", (namegen.normalize(key),)).fetchone()
                else:
                    src = c.execute("SELECT id, name FROM sources WHERE source_key=? OR source_key=?",
                                    (key, f"id:{key}")).fetchone()
                if not src:
                    stats["not_found"] += 1
                    continue
                orig = namegen.normalize(src["name"])
                fresh = [n for n in names if namegen.normalize(n) != orig]
                stats["same_as_original"] += len(names) - len(fresh)
                added, dup = add_names(c, src["id"], fresh, "import", now)
                stats["added"] += added
                stats["dup"] += dup
        batch.clear()

    for row in excel.iter_rows(fileobj, filename, parse=False):
        if key_col is None:
            cols = list(row.keys())
            key_col = next((k for k in NAME_KEY_COLS if k in cols), None)
            name_cols = [k for k in cols if "상품명" in k and not any(x in k for x in ("원본", "기존", "원래"))]
            if not key_col and "원본상품명" in cols:
                key_col, by_name = "원본상품명", True
            if not key_col or not name_cols:
                raise ValueError(f"원본을 찾을 열(판매자코드 등)이나 새 상품명 열을 찾지 못했습니다. 이 파일의 열: {', '.join(cols)}")
        key = str(row.get(key_col) or "").strip()
        names = []
        for col in name_cols:
            for part in str(row.get(col) or "").replace("|", "\n").splitlines():
                if part.strip():
                    names.append(part.strip())
        if key and names:
            batch.append((key, names))
            stats["rows"] += 1
        if len(batch) >= CHUNK:
            flush()
            if progress:
                progress(stats["rows"], None, f"{stats['rows']:,}줄 · 새 이름 {stats['added']:,}개")
        if should_stop and should_stop():
            break
    if batch:
        flush()
    db.recount_sources()
    db.x("UPDATE imports SET total=?, added=?, skipped=?, note=? WHERE id=?",
         (stats["rows"], stats["added"], stats["dup"] + stats["not_found"],
          f"원본 못 찾음 {stats['not_found']} · 다른 이름과 중복 {stats['dup']}", iid))
    stats["key_col"], stats["name_cols"] = key_col, name_cols
    return stats


def source_detail(db, sid):
    s = db.one("SELECT * FROM sources WHERE id=?", (sid,))
    if not s:
        return None
    row = unpack(s.pop("data"))
    s["errors"], s["warnings"] = json.loads(s["errors"]), json.loads(s["warnings"])
    s["row"] = row
    s["names"] = db.q("""SELECT n.id, n.name, n.origin, n.listing_id, st.name AS store_name, l.status
        FROM names n LEFT JOIN listings l ON l.id=n.listing_id LEFT JOIN stores st ON st.id=l.store_id
        WHERE n.source_id=? ORDER BY n.listing_id IS NULL, n.id""", (sid,))
    s["listings"] = db.q("""SELECT l.id, l.name, l.price, l.status, l.message, l.channel_no, l.origin_no,
        st.name AS store_name, st.store_url FROM listings l JOIN stores st ON st.id=l.store_id
        WHERE l.source_id=? ORDER BY st.id""", (sid,))
    return s


# ───────────────────────── 3. 등록 계획

def create_plan(db, ids, store_ids, mode="all", per_product=1, title="", progress=None, should_stop=None):
    """원본 × 스토어마다 등록 한 건(planned)을 만든다.

    mode="all":    고른 스토어 모두에 (이미 있는 스토어는 건너뜀)
    mode="spread": 원본마다 per_product개 스토어에. 남은 자리가 많은 스토어부터 골고루.
    이름은 그 원본의 안 쓴 후보 중 가져옴 > AI > 재조합 순으로 쓰고, 모자라면 재조합으로 채운다.
    가격은 스토어마다 원본가 ±price_jitter_pct%.
    """
    cfg = config.load()
    use_orig = bool(cfg.get("use_original_name"))
    stores = {s["id"]: s for s in db.stores() if s["id"] in set(store_ids) and s["enabled"]}
    if not stores:
        raise ValueError("등록할 스토어를 골라 주세요. (사용 중지된 스토어는 제외)")
    free = {sid: s["free"] for sid, s in stores.items()}
    now = time.time()
    pid = db.x("INSERT INTO plans(title, created_at) VALUES(?, ?)",
               (title or time.strftime("%m/%d %H:%M 계획"), now))
    st = {"created": 0, "exists": 0, "no_name": 0, "capacity": 0, "invalid": 0, "sources": 0}
    rot = 0

    for i in range(0, len(ids), CHUNK):
        if should_stop and should_stop():
            break
        chunk = ids[i:i + CHUNK]
        marks = ",".join("?" * len(chunk))
        srcs = db.q(f"SELECT id, source_key, name, price, tags, valid FROM sources WHERE id IN ({marks})", chunk)
        have = {}
        for r in db.q(f"SELECT source_id, store_id FROM listings WHERE source_id IN ({marks})", chunk):
            have.setdefault(r["source_id"], set()).add(r["store_id"])
        touched = []
        with db.tx() as c:
            for s in srcs:
                st["sources"] += 1
                if not s["valid"]:
                    st["invalid"] += 1
                    continue
                missing = [sid for sid in stores if sid not in have.get(s["id"], set())]
                st["exists"] += len(stores) - len(missing)
                if mode == "spread":
                    want = max(0, per_product - len(have.get(s["id"], set()) & set(stores)))
                    rot += 1
                    missing.sort(key=lambda sid: (-free[sid], (sid + rot) % len(stores)))
                    targets = [sid for sid in missing if free[sid] > 0][:want]
                else:
                    targets = missing
                if not targets:
                    continue
                pool = [dict(r) for r in c.execute(
                    "SELECT id, name, origin FROM names WHERE source_id=? AND listing_id IS NULL AND (origin!='original' OR ?)",
                    (s["id"], int(use_orig)))]
                if len(pool) < len(targets) and cfg.get("auto_recombine", True):
                    sibs = _siblings(c, s["id"])
                    cands = namegen.recombine(s["name"], len(targets) - len(pool), set(), sibs, cfg,
                                              seed=f"{s['id']}:{len(sibs)}:plan",
                                              tag_words=[t for t in s["tags"].split(",") if t])
                    add_names(c, s["id"], cands, "recombine", now)
                    pool = [dict(r) for r in c.execute(
                        "SELECT id, name, origin FROM names WHERE source_id=? AND listing_id IS NULL AND (origin!='original' OR ?)",
                        (s["id"], int(use_orig)))]
                pool.sort(key=lambda n: (NAME_ORIGIN_ORDER.get(n["origin"], 9), n["id"]))
                for sid in targets:
                    if free[sid] <= 0:
                        st["capacity"] += 1
                        continue
                    if not pool:
                        st["no_name"] += 1
                        continue
                    nm = pool.pop(0)
                    price = convert.adjusted_price(s["price"], f"{s['source_key']}|{sid}", cfg)
                    lid = c.execute("""INSERT INTO listings(store_id, source_id, plan_id, name_id, name, price, status,
                        created_at, updated_at) VALUES(?,?,?,?,?,?,'planned',?,?)""",
                                    (sid, s["id"], pid, nm["id"], nm["name"], price, now, now)).lastrowid
                    c.execute("UPDATE names SET listing_id=? WHERE id=?", (lid, nm["id"]))
                    free[sid] -= 1
                    st["created"] += 1
                touched.append(s["id"])
        db.recount_sources(touched)
        if progress:
            progress(min(i + CHUNK, len(ids)), len(ids), f"등록 {st['created']:,}건 계획")
    db.x("UPDATE plans SET note=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
    if not st["created"]:
        db.x("DELETE FROM plans WHERE id=?", (pid,))
        pid = None
    st["plan_id"] = pid
    return st


def cancel_listings(db, where_sql, args):
    """아직 등록 안 된(계획·실패) 건을 지우고 이름을 되돌린다."""
    rows = db.q(f"SELECT id, source_id FROM listings WHERE status IN ('planned','fail') AND ({where_sql})", args)
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    with db.tx() as c:
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            m = ",".join("?" * len(chunk))
            c.execute(f"UPDATE names SET listing_id=NULL WHERE listing_id IN ({m})", chunk)
            c.execute(f"DELETE FROM listings WHERE id IN ({m})", chunk)
    db.recount_sources({r["source_id"] for r in rows})
    db.x("DELETE FROM plans WHERE id NOT IN (SELECT DISTINCT plan_id FROM listings WHERE plan_id IS NOT NULL)")
    return len(ids)


# ───────────────────────── 등록 목록 (화면)

def listing_where(f):
    w, a = [], []
    if f.get("store_id"):
        w.append("l.store_id=?")
        a.append(int(f["store_id"]))
    if f.get("plan_id"):
        w.append("l.plan_id=?")
        a.append(int(f["plan_id"]))
    st = f.get("status") or "all"
    if st == "pending":
        w.append("l.status IN ('planned','queued','running')")
    elif st != "all":
        w.append("l.status=?")
        a.append(st)
    q = (f.get("q") or "").strip()
    if q:
        w.append("(l.name LIKE ? OR s.source_key LIKE ?)")
        a += [f"%{q}%"] * 2
    if f.get("ids"):
        ids = [int(i) for i in f["ids"]]
        w.append(f"l.id IN ({','.join('?' * len(ids))})")
        a += ids
    return (" WHERE " + " AND ".join(w)) if w else "", a


def query_listings(db, f, page=0, size=100):
    where, args = listing_where(f)
    base = "FROM listings l JOIN sources s ON s.id=l.source_id JOIN stores t ON t.id=l.store_id"
    total = db.one(f"SELECT COUNT(*) AS n {base}{where}", args)["n"]
    rows = db.q(f"""SELECT l.id, l.name, l.price, l.status, l.stage, l.message, l.origin_no, l.channel_no,
        l.seconds, l.plan_id, l.updated_at, s.id AS source_id, s.source_key, s.name AS source_name,
        s.price AS source_price, s.thumb, s.category, t.id AS store_id, t.name AS store_name, t.store_url
        {base}{where} ORDER BY l.id LIMIT ? OFFSET ?""", (*args, size, page * size))
    return {"rows": rows, "total": total}


def listing_counts(db, store_id=None, plan_id=None):
    w, a = [], []
    if store_id:
        w.append("store_id=?")
        a.append(int(store_id))
    if plan_id:
        w.append("plan_id=?")
        a.append(int(plan_id))
    where = (" WHERE " + " AND ".join(w)) if w else ""
    return db.one(f"""SELECT COUNT(*) AS all_, SUM(status IN ('planned','queued','running')) AS pending,
        SUM(status='success') AS success, SUM(status='fail') AS fail FROM listings{where}""", a)
