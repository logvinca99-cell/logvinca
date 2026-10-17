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

from . import config, convert, excel, keywords, lexicon, namegen, naver
from .db import pack, unpack

CHUNK = 500
NAME_ORIGIN_ORDER = {"manual": 0, "import": 1, "ai": 2, "recombine": 3, "original": 4}
ORIGIN_LABEL = {"original": "원본", "recombine": "재조합", "import": "가져옴", "ai": "AI", "manual": "직접"}


def source_key(row):
    """원본 구분값: 대표 썸네일 주소 기준 (판매자코드는 스토어마다 바뀌므로 쓰지 않는다)."""
    return convert.source_fingerprint(row)


def add_names(c, source_id, names, origin, now=None, cfg=None, rejected=None):
    """이름 후보를 넣는다. 모든 스토어 통틀어 정규화 이름이 같은 것은 버린다. (넣은 수, 버린 수)
    cfg를 주면 AI·가져온 이름도 검사해서(같은 단어 3번 이상, 금지 단어) 걸리면 버리고 rejected에 이유를 담는다."""
    now = now or time.time()
    added = dup = 0
    for n in names:
        n = namegen.clean(n, int((cfg or {}).get("name_max_len") or 100) if origin == "ai" else 100)
        norm = namegen.normalize(n)
        if not norm:
            continue
        if cfg is not None and origin in ("ai", "import", "manual"):
            why = namegen.check_name(n, cfg, cfg.get("_lex"))
            if why:
                if rejected is not None:
                    rejected.append(f"{n} ({why})")
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
    lex = lexicon.get(db)
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
                warnings += _name_warnings(s["name"], lex)
                tags = ",".join(convert.tags(row))
                vals = (s["name"], s["price"], s["category"], s["thumb"], s["option_count"], s["image_count"],
                        int(s["has_video"]), tags, pack(row), json.dumps(errors, ensure_ascii=False),
                        json.dumps(warnings, ensure_ascii=False), int(not errors), s["seller_code"], iid, now)
                old = c.execute("SELECT id FROM sources WHERE source_key=?", (key,)).fetchone()
                if old:
                    c.execute("""UPDATE sources SET name=?, price=?, category=?, thumb=?, option_count=?,
                        image_count=?, has_video=?, tags=?, data=?, errors=?, warnings=?, valid=?, seller_code=?,
                        import_id=?, updated_at=? WHERE id=?""", (*vals, old["id"]))
                    sid = old["id"]
                    stats["updated"] += 1
                else:
                    sid = c.execute("""INSERT INTO sources(name, price, category, thumb, option_count, image_count,
                        has_video, tags, data, errors, warnings, valid, seller_code, import_id, updated_at, source_key,
                        created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (*vals, key, now)).lastrowid
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
    if db.one("SELECT 1 FROM dict_syn LIMIT 1"):
        with db.tx() as c:
            lexicon._bump(c)  # 사전 비슷한말은 원본 상품명에 나오는 말만 쓰므로 다시 읽게
    return stats


def _name_warnings(name, lex):
    """원본 상품명 자체의 문제 (원본 단어는 재조합해도 그대로 남으므로 미리 알린다)."""
    out = []
    bad = lexicon.blocked_in(name, lex)
    if bad:
        out.append(f"원본 상품명에 금지 단어가 있습니다: {', '.join(bad[:5])} (상표·효능·인증·원산지 표현인지 확인하세요)")
    tm = lexicon.marks_in(name, lex)
    if tm:
        out.append("원본 상품명에 상표로 등록·출원된 단어가 있습니다: " + ", ".join(f"{w}({v})" for w, v in tm[:5])
                   + " (일반 명칭으로 쓴 것인지 확인하세요)")
    rep = lexicon.repeated_word(namegen.tokens(name), lex, 2)
    if rep:
        out.append(f"원본 상품명에 '{rep}'가 3번 이상 나옵니다")
    return out


def revalidate(db, progress=None):
    """카테고리 목록이나 설정·단어 사전이 바뀐 뒤 전체 원본을 다시 검사한다."""
    cfg = config.load()
    lex = lexicon.get(db)
    categories = naver.cached_categories()
    ids = [r["id"] for r in db.q("SELECT id FROM sources")]
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        rows = db.q(f"SELECT id, data FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        with db.tx() as c:
            for r in rows:
                row = unpack(r["data"])
                errors, warnings = convert.validate(row, cfg, categories)
                warnings += _name_warnings(str(row.get("상품명") or ""), lex)
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
        w.append("(name LIKE ? OR seller_code LIKE ? OR category LIKE ? OR id=?)")
        a += [f"%{q}%"] * 3 + [int(q) if q.isdigit() else -1]
    st = f.get("status") or "all"
    if st == "valid":
        w.append("valid=1")
    elif st == "invalid":
        w.append("valid=0")
    elif st == "unlisted":
        w.append("valid=1 AND n_listings=0")
    elif st == "listed":
        w.append("n_listings>0")
    elif st == "partial":
        w.append("valid=1 AND n_listings>0 AND n_listings<?")
        a.append(int(config.load().get("max_copies") or 3))
    elif st == "full":
        w.append("n_listings>=?")
        a.append(int(config.load().get("max_copies") or 3))
    elif st == "names_short":
        w.append("valid=1 AND n_free_names < ?")
        a.append(int(f.get("min_names") or 3))
    elif st == "warn":
        w.append("valid=1 AND warnings!='[]'")
    if f.get("category"):
        w.append("category LIKE ?")
        a.append(f"{f['category']}%")
    if f.get("store_missing"):
        w.append("id NOT IN (SELECT source_id FROM listings WHERE store_id=? AND status!='deleted')")
        a.append(int(f["store_missing"]))
    if f.get("store_has"):
        w.append("id IN (SELECT source_id FROM listings WHERE store_id=? AND status!='deleted')")
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


LIST_COLS = ("id, source_key, seller_code, name, price, category, thumb, option_count, image_count, has_video, errors, "
             "warnings, valid, n_listings, n_success, n_free_names, updated_at")


def query_sources(db, f, page=0, size=100):
    where, args = source_where(f)
    total = db.one(f"SELECT COUNT(*) AS n FROM sources{where}", args)["n"]
    rows = db.q(f"SELECT {LIST_COLS} FROM sources{where} ORDER BY id LIMIT ? OFFSET ?", (*args, size, page * size))
    for r in rows:
        r["errors"], r["warnings"] = json.loads(r["errors"]), json.loads(r["warnings"])
        r["copies"], r["deleted_copies"] = [], 0
    # 이 쪽에 보이는 원본들의 복사본을 한 번에 가져와 원본 아래에 붙인다.
    by_id = {r["id"]: r for r in rows}
    if by_id:
        for c in db.q(f"""SELECT l.id, l.source_id, l.name, l.price, l.status, l.op, l.round, l.seller_code,
                l.channel_no, l.registered_at, l.deleted_at, l.sold_count, l.cancel_count, l.locked, l.lock_note,
                l.message, t.name AS store,
                t.store_url, COALESCE(NULLIF(t.code,''), 'S'||printf('%02d', t.id)) AS code
                FROM listings l JOIN stores t ON t.id=l.store_id
                WHERE l.source_id IN ({','.join('?' * len(by_id))}) ORDER BY l.status='deleted', l.id""", list(by_id)):
            if c["status"] == "deleted":
                by_id[c["source_id"]]["deleted_copies"] += 1
            else:
                by_id[c["source_id"]]["copies"].append(c)
    return {"rows": rows, "total": total}


def source_ids(db, f):
    where, args = source_where(f)
    return [r["id"] for r in db.q(f"SELECT id FROM sources{where} ORDER BY id", args)]


def source_counts(db):
    mx = int(config.load().get("max_copies") or 3)
    return db.one("""SELECT COUNT(*) AS all_, SUM(valid=1) AS valid, SUM(valid=0) AS invalid,
        SUM(valid=1 AND n_listings=0) AS unlisted, SUM(n_listings>0) AS listed,
        SUM(valid=1 AND n_listings>0 AND n_listings<?) AS partial, SUM(n_listings>=?) AS full,
        SUM(valid=1 AND n_free_names<3) AS names_short, SUM(valid=1 AND warnings!='[]') AS warn
        FROM sources""", (mx, mx))


# ───────────────────────── 2. 상품명 후보

def _siblings(c, sid):
    return [r["name"] for r in c.execute("SELECT name FROM names WHERE source_id=?", (sid,))]


def generate_recombine(db, ids, per_source, progress=None, should_stop=None):
    """원본마다 안 쓴 이름 후보가 per_source개가 되도록 재조합으로 채운다."""
    cfg = config.load()
    cfg["_lex"] = lexicon.get(db)
    use_orig = int(bool(cfg.get("use_original_name")))
    stats = {"sources": 0, "added": 0, "short": 0}
    for i in range(0, len(ids), CHUNK):
        if should_stop and should_stop():
            break
        chunk = ids[i:i + CHUNK]
        rows = db.q(f"SELECT id, name, tags, category, n_free_names, core_kw, data FROM sources WHERE id IN ({','.join('?' * len(chunk))})",
                    chunk)
        kws = keywords.words_for(db, rows, cfg, cfg["_lex"])
        for r in rows:
            r["_kw"] = kws.get(r["id"])
            r.pop("data", None)
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
                                              tag_words=[t for t in r["tags"].split(",") if t], category=r["category"],
                                              **_kw_args(r))
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
    cfg["_lex"] = lexicon.get(db)
    rejected = []
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
                        added, dup = add_names(c, sid, result.get(str(sid), []), "ai", cfg=cfg, rejected=rejected)
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
    stats["rejected"] = len(rejected)
    stats["rejected_examples"] = rejected[:5]
    return stats


NAME_KEY_COLS = ("판매자코드", "상품코드", "원본코드", "sellerCode")


def import_names(db, fileobj, filename, progress=None, should_stop=None):
    """외부 AI 도구 등에서 만든 상품명 파일을 이름 후보로 넣는다.

    원본을 찾는 열: 판매자코드 / 상품코드 / 원본코드 / id 중 있는 것, 없으면 '원본상품명'.
    이름 열: 열 이름에 '상품명'이 들어간 열 (원본·기존 상품명 열은 제외). 여러 열이면 모두 후보로.
    한 칸에 여러 이름을 줄바꿈이나 | 로 넣어도 된다.
    """
    now = time.time()
    cfg = config.load()
    cfg["_lex"] = lexicon.get(db)
    rejected = []
    iid = db.x("INSERT INTO imports(kind, file_name, created_at) VALUES('names', ?, ?)", (filename, now))
    stats = {"rows": 0, "added": 0, "dup": 0, "not_found": 0, "same_as_original": 0}
    key_col = name_cols = None
    by_name = by_thumb = False
    batch = []

    def flush():
        with db.tx() as c:
            for key, names in batch:
                if by_name:
                    src = c.execute("SELECT id, name FROM sources WHERE id IN (SELECT source_id FROM names "
                                    "WHERE norm=? AND origin='original')", (namegen.normalize(key),)).fetchone()
                elif by_thumb:
                    src = c.execute("SELECT id, name FROM sources WHERE source_key=?", (key,)).fetchone()
                else:
                    src = c.execute("SELECT id, name FROM sources WHERE seller_code=? OR source_key=?",
                                    (key, key)).fetchone()
                if not src:
                    stats["not_found"] += 1
                    continue
                orig = namegen.normalize(src["name"])
                fresh = [n for n in names if namegen.normalize(n) != orig]
                stats["same_as_original"] += len(names) - len(fresh)
                added, dup = add_names(c, src["id"], fresh, "import", now, cfg=cfg, rejected=rejected)
                stats["added"] += added
                stats["dup"] += dup
        batch.clear()

    for row in excel.iter_rows(fileobj, filename, parse=False):
        if key_col is None:
            cols = list(row.keys())
            key_col = next((k for k in NAME_KEY_COLS if k in cols), None)
            name_cols = [k for k in cols if "상품명" in k and not any(x in k for x in ("원본", "기존", "원래"))]
            if "썸네일" in cols:
                key_col, by_thumb = "썸네일", True  # 원본 엑셀 형식 그대로면 썸네일로 찾는 게 가장 정확
            if not key_col and "원본상품명" in cols:
                key_col, by_name = "원본상품명", True
            if not key_col or not name_cols:
                raise ValueError(f"원본을 찾을 열(판매자코드 등)이나 새 상품명 열을 찾지 못했습니다. 이 파일의 열: {', '.join(cols)}")
        key = str(row.get(key_col) or "").strip()
        if by_thumb:
            key = convert.source_fingerprint({"썸네일": excel.parse_value(row.get(key_col))})
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
    stats["rejected"] = len(rejected)
    stats["rejected_examples"] = rejected[:5]
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
    s["listings"] = db.q("""SELECT l.id, l.name, l.price, l.status, l.op, l.round, l.message, l.channel_no, l.sold_count,
        l.origin_no, l.seller_code, l.registered_at, l.deleted_at, st.name AS store_name, st.store_url
        FROM listings l JOIN stores st ON st.id=l.store_id WHERE l.source_id=? ORDER BY l.status='deleted', st.id""",
                         (sid,))
    s["history"] = db.q("""SELECT h.*, st.name AS store_name FROM listing_history h
        JOIN listings l ON l.id=h.listing_id JOIN stores st ON st.id=l.store_id
        WHERE l.source_id=? ORDER BY h.deleted_at DESC""", (sid,))
    s["max_copies"] = int(config.load().get("max_copies") or 3)
    return s


# ───────────────────────── 3. 등록 계획

def _free_names(c, sid, use_orig):
    rows = [dict(r) for r in c.execute(
        "SELECT id, name, origin FROM names WHERE source_id=? AND listing_id IS NULL AND (origin!='original' OR ?)",
        (sid, int(use_orig)))]
    rows.sort(key=lambda n: (NAME_ORIGIN_ORDER.get(n["origin"], 9), n["id"]))
    return rows


def _kw_args(s):
    core, kw = s.get("_kw") or (s.get("core_kw") or "", [])
    return {"core": core, "kw_words": kw}


def _fill_names(c, s, need, cfg, now):
    """이름 후보가 need개보다 적으면 재조합으로 채우고, 안 쓴 후보 목록을 돌려준다."""
    use_orig = bool(cfg.get("use_original_name"))
    pool = _free_names(c, s["id"], use_orig)
    if len(pool) < need and cfg.get("auto_recombine", True):
        sibs = _siblings(c, s["id"])
        cands = namegen.recombine(s["name"], need - len(pool), set(), sibs, cfg,
                                  seed=f"{s['id']}:{len(sibs)}:plan",
                                  tag_words=[t for t in (s.get("tags") or "").split(",") if t],
                                  category=s.get("category") or "", **_kw_args(s))
        add_names(c, s["id"], cands, "recombine", now)
        pool = _free_names(c, s["id"], use_orig)
    return pool


def create_plan(db, ids, store_ids, mode="all", per_product=1, title="", progress=None, should_stop=None):
    """원본 × 스토어마다 등록 한 건(planned)을 만든다.

    원본 하나는 최대 max_copies곳(기본 3)까지만. 내린(deleted) 스토어는 세지 않는다.
    mode="all":    고른 스토어에 (원본마다 남은 칸만큼, 남은 자리가 많은 스토어부터)
    mode="spread": 원본마다 per_product곳이 되도록 (이미 고른 스토어에 있는 것 포함)
    전에 내렸던 스토어에 다시 계획하면 같은 줄을 다음 회차로 살린다 (이름·가격 그대로, 설정으로 새 이름).
    """
    cfg = config.load()
    cfg["_lex"] = lexicon.get(db)
    max_copies = max(1, int(cfg.get("max_copies") or 3))
    stores = {s["id"]: s for s in db.stores() if s["id"] in set(store_ids) and s["enabled"]}
    if not stores:
        raise ValueError("등록할 스토어를 골라 주세요. (사용 중지된 스토어는 제외)")
    free = {sid: s["free"] for sid, s in stores.items()}
    now = time.time()
    pid = db.x("INSERT INTO plans(title, created_at) VALUES(?, ?)",
               (title or time.strftime("%m/%d %H:%M 계획"), now))
    st = {"created": 0, "revived": 0, "exists": 0, "full": 0, "no_name": 0, "capacity": 0, "invalid": 0, "sources": 0}
    rot = 0

    for i in range(0, len(ids), CHUNK):
        if should_stop and should_stop():
            break
        chunk = ids[i:i + CHUNK]
        marks = ",".join("?" * len(chunk))
        srcs = db.q(f"SELECT id, source_key, name, price, tags, category, valid, core_kw, data FROM sources WHERE id IN ({marks})",
                    chunk)
        kws = keywords.words_for(db, srcs, cfg, cfg["_lex"])
        for s in srcs:
            s["_kw"] = kws.get(s["id"])
            s.pop("data", None)
        active, dead = {}, {}
        for r in db.q(f"SELECT id, source_id, store_id, status, name_id, round FROM listings WHERE source_id IN ({marks})",
                      chunk):
            (dead if r["status"] == "deleted" else active).setdefault(r["source_id"], {})[r["store_id"]] = r
        touched = []
        with db.tx() as c:
            for s in srcs:
                st["sources"] += 1
                if not s["valid"]:
                    st["invalid"] += 1
                    continue
                act = active.get(s["id"], {})
                slots = max_copies - len(act)
                cand = [sid for sid in stores if sid not in act]
                st["exists"] += len(stores) - len(cand)
                if slots <= 0:
                    st["full"] += 1
                    continue
                rot += 1
                cand.sort(key=lambda sid: (-free[sid], (sid + rot) % len(stores)))
                cand = [sid for sid in cand if free[sid] > 0] or cand
                if mode == "spread":
                    want = min(slots, max(0, per_product - len(set(act) & set(stores))))
                else:
                    want = slots
                targets = cand[:want]
                if mode == "all" and len(cand) > slots:
                    st["full"] += 1  # 고른 스토어가 남은 칸보다 많아 일부만
                if not targets:
                    continue
                need_names = sum(1 for sid in targets if sid not in dead.get(s["id"], {}) or cfg.get("refresh_new_name"))
                pool = _fill_names(c, s, need_names, cfg, now) if need_names else []
                for sid in targets:
                    if free[sid] <= 0:
                        st["capacity"] += 1
                        continue
                    old = dead.get(s["id"], {}).get(sid)
                    price = convert.adjusted_price(s["price"], f"{s['source_key']}|{sid}", cfg)
                    if old and not cfg.get("refresh_new_name"):
                        c.execute("""UPDATE listings SET status='planned', op='create', round=round+1, plan_id=?,
                            message='', stage='', updated_at=? WHERE id=?""", (pid, now, old["id"]))
                        st["revived"] += 1
                    else:
                        if not pool:
                            st["no_name"] += 1
                            continue
                        nm = pool.pop(0)
                        if old:
                            c.execute("""UPDATE listings SET status='planned', op='create', round=round+1, plan_id=?,
                                name_id=?, name=?, message='', stage='', updated_at=? WHERE id=?""",
                                      (pid, nm["id"], nm["name"], now, old["id"]))
                            c.execute("UPDATE names SET listing_id=? WHERE id=?", (old["id"], nm["id"]))
                            st["revived"] += 1
                        else:
                            lid = c.execute("""INSERT INTO listings(store_id, source_id, plan_id, name_id, name, price,
                                status, created_at, updated_at) VALUES(?,?,?,?,?,?,'planned',?,?)""",
                                            (sid, s["id"], pid, nm["id"], nm["name"], price, now, now)).lastrowid
                            c.execute("UPDATE names SET listing_id=? WHERE id=?", (lid, nm["id"]))
                            st["created"] += 1
                    free[sid] -= 1
                touched.append(s["id"])
        db.recount_sources(touched)
        if progress:
            progress(min(i + CHUNK, len(ids)), len(ids), f"등록 {st['created'] + st['revived']:,}건 계획")
    db.x("UPDATE plans SET note=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
    if not st["created"] and not st["revived"]:
        db.x("DELETE FROM plans WHERE id=?", (pid,))
        pid = None
    st["plan_id"] = pid
    return st


def schedule_op(db, f, op):
    """올라가 있는 건에 할 일을 건다. op: refresh(지우고 다시 올리기) / delete(내리기).
    판매 이력이 있는 건은 건너뛴다. (예약한 수, 판매 이력으로 건너뛴 수)"""
    where, args = listing_where({**f, "status": "live"})
    rows = db.q(f"SELECT l.id, l.source_id, l.locked FROM listings l JOIN sources s ON s.id=l.source_id{where}", args)
    # 잠긴 복사본(판매 이력 또는 직접 잠금)은 지우지 않는다.
    ids = [r["id"] for r in rows if not r["locked"]]
    skipped = len(rows) - len(ids)
    now = time.time()
    with db.tx() as c:
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            c.execute(f"UPDATE listings SET status='planned', op=?, message='', updated_at=? "
                      f"WHERE id IN ({','.join('?' * len(chunk))})", (op, now, *chunk))
    return len(ids), skipped


def cancel_listings(db, where_sql, args):
    """아직 처리 안 된(대기·실패) 할 일을 취소한다.
    새 등록이면 줄을 지우고 이름을 후보로 돌린다 (다시 살린 줄이면 '내림'으로 되돌림).
    최신화·내리기면 할 일만 지우고 '판매 중'으로 되돌린다."""
    rows = db.q(f"SELECT id, source_id, op, round, origin_no FROM listings "
                f"WHERE status IN ('planned','fail') AND ({where_sql})", args)
    if not rows:
        return 0
    with db.tx() as c:
        for r in rows:
            if r["origin_no"]:
                c.execute("UPDATE listings SET status='success', op='create', message='' WHERE id=?", (r["id"],))
            elif r["round"] > 1:
                c.execute("UPDATE listings SET status='deleted', op='create', round=round-1, message='' WHERE id=?",
                          (r["id"],))
            else:
                c.execute("UPDATE names SET listing_id=NULL WHERE listing_id=?", (r["id"],))
                c.execute("DELETE FROM listings WHERE id=?", (r["id"],))
    db.recount_sources({r["source_id"] for r in rows})
    db.x("DELETE FROM plans WHERE id NOT IN (SELECT DISTINCT plan_id FROM listings WHERE plan_id IS NOT NULL)")
    return len(rows)


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
    elif st == "live":
        w.append("l.origin_no!='' AND l.status='success'")
    elif st == "active":
        w.append("l.status!='deleted'")
    elif st == "sold":
        w.append("l.sold_count>0")
    elif st == "locked":
        w.append("l.locked=1 AND l.status!='deleted'")
    elif st == "bait":
        w.append("l.bait_state IN ('on','fail') AND l.origin_no!=''")
    elif st != "all":
        w.append("l.status=?")
        a.append(st)
    if f.get("op"):
        w.append("l.op=?")
        a.append(f["op"])
    if f.get("locked") in ("0", "1", 0, 1):
        w.append("l.locked=?")
        a.append(int(f["locked"]))
    if f.get("sold") == "1":
        w.append("l.sold_count>0")
    elif f.get("sold") == "0":
        w.append("l.sold_count=0")
    if f.get("age_days") not in (None, ""):
        w.append("l.origin_no!='' AND l.registered_at<=?")
        a.append(time.time() - float(f["age_days"]) * 86400)
    q = (f.get("q") or "").strip()
    if q:
        w.append("(l.name LIKE ? OR l.seller_code LIKE ? OR s.seller_code LIKE ? OR l.channel_no=?)")
        a += [f"%{q}%"] * 3 + [q]
    if f.get("ids"):
        ids = [int(i) for i in f["ids"]]
        w.append(f"l.id IN ({','.join('?' * len(ids))})")
        a += ids
    return (" WHERE " + " AND ".join(w)) if w else "", a


def query_listings(db, f, page=0, size=100):
    where, args = listing_where(f)
    base = "FROM listings l JOIN sources s ON s.id=l.source_id JOIN stores t ON t.id=l.store_id"
    total = db.one(f"SELECT COUNT(*) AS n {base}{where}", args)["n"]
    rows = db.q(f"""SELECT l.id, l.name, l.price, l.status, l.op, l.round, l.stage, l.message, l.origin_no, l.sold_count,
        l.cancel_count, l.locked, l.lock_note, l.manual_lock,
        l.channel_no, l.seller_code, l.registered_at, l.deleted_at, l.seconds, l.plan_id, l.updated_at,
        s.id AS source_id, s.source_key, s.seller_code AS source_code, s.name AS source_name,
        s.price AS source_price, s.thumb, s.category, s.n_listings AS source_copies,
        t.id AS store_id, t.name AS store_name, t.store_url,
        COALESCE(NULLIF(t.code,''), 'S'||printf('%02d', t.id)) AS store_code
        {base}{where} ORDER BY l.id LIMIT ? OFFSET ?""", (*args, size, page * size))
    return {"rows": rows, "total": total}


def listing_ids(db, f):
    where, args = listing_where(f)
    return [r["id"] for r in db.q(f"SELECT l.id FROM listings l JOIN sources s ON s.id=l.source_id{where}", args)]


def listing_counts(db, store_id=None, plan_id=None):
    w, a = [], []
    if store_id:
        w.append("store_id=?")
        a.append(int(store_id))
    if plan_id:
        w.append("plan_id=?")
        a.append(int(plan_id))
    where = (" WHERE " + " AND ".join(w)) if w else ""
    day = 86400
    now = time.time()
    return db.one(f"""SELECT COUNT(*) AS all_,
        SUM(status IN ('planned','queued','running')) AS pending,
        SUM(status IN ('planned','queued','running') AND op='create') AS pending_create,
        SUM(status IN ('planned','queued','running') AND op='refresh') AS pending_refresh,
        SUM(status IN ('planned','queued','running') AND op='delete') AS pending_delete,
        SUM(origin_no!='' AND status='success') AS live, SUM(status='fail') AS fail, SUM(status='deleted') AS deleted,
        SUM(sold_count>0) AS sold, SUM(locked=1 AND status!='deleted') AS locked,
        SUM(bait_state IN ('on','fail') AND origin_no!='') AS bait,
        SUM(origin_no!='' AND registered_at<=?) AS age30, SUM(origin_no!='' AND registered_at<=?) AS age60,
        SUM(origin_no!='' AND registered_at<=?) AS age90
        FROM listings{where}""", (now - 30 * day, now - 60 * day, now - 90 * day, *a))
