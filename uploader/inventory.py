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

import random

from . import aiwords, config, convert, ctxkw, excel, keywords, lexicon, namegen, naver, nvstate, srctags
from .db import pack, unpack

CHUNK = 500
NAME_ORIGIN_ORDER = {"manual": 0, "import": 1, "ctx": 2, "ai": 3, "shuffle": 4, "recombine": 5, "original": 6, "adopt": 7}
ORIGIN_LABEL = {"original": "원본", "adopt": "올라가 있던 이름", "ctx": "AI 맥락", "shuffle": "셔플", "recombine": "재조합", "import": "가져옴", "ai": "AI", "manual": "직접"}


def source_key(row):
    """원본 구분값: 상품명이 완전히 같으면 같은 원본 (convert.name_key). 대표 이미지 주소는 기준이 아니다.
    기존 상품 가져오기는 스토어 상품과 1대1이 되도록 겹치면 '_source_key'(상품명#판매자코드)를 넣어 준다."""
    return row.get("_source_key") or convert.name_key(row.get("상품명"))


class DupChecker:
    """상품명 중복 판정 (원본 기준 = 상품명이 '완전히' 같음): 이미 있는 원본(휴지통 제외)이나 이 파일 앞줄과 상품명이 같으면 중복.
    중복 줄은 원본으로 넣지 않는다 (덮어쓰지 않음 — 고칠 것은 원본 상세 창·기준 가격 수정으로)."""

    def __init__(self, db):
        self.known = {}
        for r in db.q("SELECT id, name, source_key FROM sources"):
            self.known.setdefault(r["source_key"], r["id"])
            self.known.setdefault("=" + str(r["name"] or "").strip(), r["id"])
        self.seen = {}

    def where(self, row):
        """중복이면 어디와 겹치는지 글, 아니면 None (기록은 안 함 — 넣기로 한 줄만 add)."""
        name = str(row.get("상품명") or "").strip()
        if not name:
            return None
        k = row.get("_source_key") or convert.name_key(name)
        sid = self.known.get(k) or (None if row.get("_source_key") else self.known.get("=" + name))
        if sid:
            return f"이미 있는 원본 #{sid}"
        if k in self.seen:
            return f"이 파일 {self.seen[k]}행" if self.seen[k] else "이 파일 앞줄"
        return None

    def add(self, row, line=None):
        name = str(row.get("상품명") or "").strip()
        if name:
            self.seen.setdefault(row.get("_source_key") or convert.name_key(name), line)


def upload_scan(db, rows, limit=8):
    """원본 엑셀 올리기 전 확인 (한 번 읽기): 상품명 중복(넣지 않음) + 가격 칸 + 대표 이미지 주소 겹침.
    중복 = 상품명이 완전히 같은 원본이 이미 있거나 이 파일 앞줄에 있음 → 넣지 않음 (가격·이미지 확인에서도 뺌).
    이미지 겹침 = 상품명이 다른데 대표 이미지 주소가 같은 줄 (파일 안의 앞줄 또는 이미 있는 원본과)."""
    price = {"n": 0, "total": 0, "by": {}, "labels": convert.PRICE_FLAG, "examples": []}
    img = {"n": 0, "in_file": 0, "with_sources": 0, "examples": []}
    dup = {"n": 0, "in_file": 0, "with_sources": 0, "examples": [], "rows": []}
    known = {}
    for r in db.q("SELECT id, img_key, name FROM sources WHERE img_key!=''"):
        known.setdefault(r["img_key"], (r["id"], r["name"]))
    seen = {}
    dc = DupChecker(db)
    for i, row in enumerate(rows, 2):
        name = str(row.get("상품명") or "").strip()
        if not name:
            continue
        w = dc.where(row)
        if w:
            dup["n"] += 1
            dup["in_file" if w.startswith("이 파일") else "with_sources"] += 1
            if len(dup["examples"]) < limit:
                dup["examples"].append({"line": i, "name": name[:80], "where": w})
            if len(dup["rows"]) < 5000:
                dup["rows"].append([i, name, w])
            continue
        dc.add(row, i)
        price["total"] += 1
        k = convert.price_flag(row)
        if k:
            price["n"] += 1
            price["by"][k] = price["by"].get(k, 0) + 1
            if len(price["examples"]) < limit:
                price["examples"].append({"line": i, "name": name[:60], "price": convert.to_int(row.get("판매가")),
                                          "off": convert.to_int(row.get("할인가")), "cost": convert.to_int(row.get("원가")),
                                          "final": convert.net_price(row), "why": k})
        if not convert.thumbnails(row):
            continue
        ik = convert.source_fingerprint(row)
        other = None
        if ik in seen:   # 상품명 중복은 위에서 뺐으므로 여기 걸리면 상품명이 다른 것
            other, img_where = seen[ik][1], f"이 파일 {seen[ik][0]}행"
            img["in_file"] += 1
        elif ik in known:
            other, img_where = known[ik][1], f"이미 있는 원본 #{known[ik][0]}"
            img["with_sources"] += 1
        if other is not None:
            img["n"] += 1
            if len(img["examples"]) < limit:
                img["examples"].append({"line": i, "name": name[:60], "other": str(other)[:60], "where": img_where,
                                        "thumb": (convert.thumbnails(row) or [""])[0]})
        else:
            seen[ik] = (i, name)
    return {"price": price, "img": img, "dup": dup}


def img_skipper(db):
    """이미지 겹침 버리기: 대표 이미지 주소가 이미 있는 원본(또는 앞서 넣은 줄)과 같으면 True → 그 줄은 안 넣음.
    (상품명 중복 줄은 그 전에 빠지므로 여기 오는 줄은 상품명이 다름)"""
    known = {r["img_key"] for r in db.q("SELECT img_key FROM sources WHERE img_key!=''")}

    def skip(row):
        if not convert.thumbnails(row):
            return False
        ik = convert.source_fingerprint(row)
        if ik in known:
            return True
        known.add(ik)
        return False
    return skip


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

def import_products(db, fileobj, filename, progress=None, should_stop=None, src_tags=None, store_tag=False, skip_img_dup=False):
    """원본 엑셀(셀업 양식) 불러오기. 상품명이 완전히 같은 원본이 이미 있으면(또는 파일 안에 또 나오면) '상품명 중복'으로 넣지 않는다
    (덮어쓰지 않음). src_tags: 모든 원본에 붙일 출처 태그. skip_img_dup: 대표 이미지 주소가 겹치는(상품명은 다른) 줄은 버림 (올릴 때 창에서 고름)."""
    st = import_rows(db, ((i, r) for i, r in enumerate(excel.iter_rows(fileobj, filename), 2)), filename,
                     total_hint=excel.count_rows(fileobj, filename), progress=progress, should_stop=should_stop,
                     src_tags=src_tags, store_tag=store_tag, skip_img=img_skipper(db) if skip_img_dup else None, line_refs=True)
    st.pop("refs", None)
    return st


def import_rows(db, rows, file_name, total_hint=0, progress=None, should_stop=None, src_tags=None, store_tag=False, skip_img=None, line_refs=False, price_src="file"):
    """원본 줄들을 새 원본 상품으로 (엑셀 불러오기·상세 정리·기존 상품 가져오기 공용). rows: (참조, 엑셀 줄 사전) 반복자.
    상품명이 완전히 같은 원본이 이미 있거나 앞줄에 있으면 '상품명 중복'으로 넣지 않는다 (덮어쓰지 않음 — 원본 기준은 처음 넣은 것).
    src_tags: 모든 줄에 붙일 출처 태그, store_tag: 수집URL의 스토어도 태그로. line_refs: 참조가 엑셀 줄 번호.
    돌려주는 refs: {참조: 원본 번호} (새로 넣은 것만), dup_rows: [[줄, 상품명, 겹치는 곳]] (앞 5000개)."""
    src_tags = srctags.parse(src_tags)
    cfg = config.load()
    lex = lexicon.get(db)
    categories = naver.cached_categories()
    now = time.time()
    iid = db.x("INSERT INTO imports(kind, file_name, created_at) VALUES('products', ?, ?)", (file_name, now))
    stats = {"total": 0, "added": 0, "invalid": 0, "dup": 0, "dup_rows": [], "img_skipped": 0}
    refs = {}
    touched = []
    batch = []
    dc = DupChecker(db)

    def dup_row(ref, row, where):
        stats["dup"] += 1
        if len(stats["dup_rows"]) < 5000:
            stats["dup_rows"].append([ref if line_refs else None, str(row.get("상품명") or "")[:200], where])

    def flush():
        with db.tx() as c:
            for ref, row in batch:
                key = source_key(row)
                row.pop("_source_key", None)   # 열쇠는 원본 칸에만 (엑셀 내용에는 안 남김)
                if c.execute("SELECT 1 FROM sources WHERE source_key=?", (key,)).fetchone():   # (생기면 안 됨 — 위에서 걸렀음) 덮어쓰지 않음
                    dup_row(ref, row, "이미 있는 원본")
                    continue
                s = convert.summary(row, cfg)
                errors, warnings = convert.validate(row, cfg, categories)
                warnings += _name_warnings(s["name"], lex)
                tags = ",".join(convert.tags(row))
                vals = (s["name"], s["price"], s["category"], s["thumb"], s["option_count"], s["image_count"],
                        int(s["has_video"]), tags, pack(row), json.dumps(errors, ensure_ascii=False),
                        json.dumps(warnings, ensure_ascii=False), int(not errors), s["seller_code"], iid, now)
                # 기준 가격 = 이 파일의 손님 가격 (판매가 - 할인가), 처음 넣을 때 고정
                sid = c.execute("""INSERT INTO sources(name, price, category, thumb, option_count, image_count,
                    has_video, tags, data, errors, warnings, valid, seller_code, import_id, updated_at, source_key,
                    created_at, price_seed, price_src, price_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*vals, key, now, key, price_src, now)).lastrowid
                stats["added"] += 1
                c.execute("UPDATE sources SET img_key=? WHERE id=?", (s["img_key"], sid))
                tg = srctags.for_row(row, src_tags, store_tag)
                if tg:
                    c.execute("UPDATE sources SET src_tags=? WHERE id=?", (srctags.merge("", tg), sid))
                if errors:
                    stats["invalid"] += 1
                add_names(c, sid, [s["name"]], "original", now)
                touched.append(sid)
                if ref is not None:
                    refs[ref] = sid
        batch.clear()

    for ref, row in rows:
        if should_stop and should_stop():
            break
        if not row.get("상품명"):
            continue
        w = dc.where(row)
        if w:   # 상품명 중복 → 넣지 않음
            dup_row(ref, row, w)
            continue
        if skip_img and skip_img(row):   # 대표 이미지 주소 겹침 → 버리기로 고름
            stats["img_skipped"] += 1
            continue
        dc.add(row, ref if line_refs else None)
        batch.append((ref, row))
        stats["total"] += 1
        if len(batch) >= CHUNK:
            flush()
            if progress:
                progress(stats["total"], total_hint, f"{stats['total']:,}개 읽음")
    if batch:
        flush()
    db.recount_sources(touched)
    db.x("UPDATE imports SET total=?, added=?, updated=0, skipped=?, note=? WHERE id=?",
         (stats["total"], stats["added"], stats["invalid"],
          f"상품명 중복이라 안 넣음 {stats['dup']}개" + (f" · 대표 이미지 겹쳐서 버림 {stats['img_skipped']}개" if stats["img_skipped"] else ""), iid))
    stats["import_id"] = iid
    stats["refs"] = refs
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
        out.append(f"반복: 원본 상품명에 '{rep}'가 3번 이상 나옵니다")
    return out


def set_category_fix(db, sids, path):
    """원본들의 네이버 카테고리를 직접 정함 (path = 네이버 카테고리 전체 이름, ''면 엑셀 카테고리로 되돌림).
    그 원본으로 만든 복사본도 다음에 올릴 때 이 카테고리로. 바꾼 원본 수."""
    path = str(path or "").strip()
    cats = naver.cached_categories() or {}
    if path and path not in cats:
        raise ValueError(f"네이버 카테고리 '{path}'가 목록에 없습니다. 목록에서 골라 주세요.")
    cfg = config.load()
    n = 0
    for i in range(0, len(sids), 900):
        chunk = list(sids)[i:i + 900]
        m = ",".join("?" * len(chunk))
        rows = db.q(f"SELECT id, data FROM sources WHERE id IN ({m})", chunk)
        with db.tx() as c:
            for r in rows:
                row = convert.with_category_fix(unpack(r["data"]), path)
                errors, warnings = convert.validate(row, cfg, cats)
                c.execute("UPDATE sources SET category_fix=?, errors=?, valid=? WHERE id=?",
                          (path, json.dumps(errors, ensure_ascii=False), int(not errors), r["id"]))
                n += 1
    db.recount_sources(sids)
    return n


def revalidate(db, progress=None, should_stop=None):
    """카테고리 목록이나 설정·단어 사전이 바뀐 뒤 전체 원본을 다시 검사한다."""
    cfg = config.load()
    lex = lexicon.get(db)
    categories = naver.cached_categories()
    ids = [r["id"] for r in db.q("SELECT id FROM sources")]
    invalid = 0
    for i in range(0, len(ids), CHUNK):
        if should_stop and should_stop():
            break
        chunk = ids[i:i + CHUNK]
        rows = db.q(f"SELECT id, data, category_fix FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        with db.tx() as c:
            for r in rows:
                row = convert.with_category_fix(unpack(r["data"]), r["category_fix"])
                errors, warnings = convert.validate(row, cfg, categories)
                invalid += bool(errors)
                warnings += _name_warnings(str(row.get("상품명") or ""), lex)
                c.execute("UPDATE sources SET errors=?, warnings=?, valid=?, image_count=? WHERE id=?",
                          (json.dumps(errors, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False),
                           int(not errors), len(convert.images_to_upload(row, cfg)), r["id"]))
        if progress:
            progress(min(i + CHUNK, len(ids)), len(ids), "다시 검사 중")
    db.recount_sources()
    return {"total": len(ids), "invalid": invalid}


# ───────────────────────── 원본 찾기 (화면 목록, 계획 대상)

def source_where(f):
    """화면의 거르기 조건 → SQL WHERE."""
    w, a = [], []
    q = (f.get("q") or "").strip()
    if q:
        w.append("(name LIKE ? OR seller_code LIKE ? OR category LIKE ? OR src_tags LIKE ? OR id=?)")
        a += [f"%{q}%"] * 4 + [int(q) if q.isdigit() else -1]
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
        a.append(int(config.load().get("max_copies") or 2))
    elif st == "full":
        w.append("n_listings>=?")
        a.append(int(config.load().get("max_copies") or 2))
    elif st == "names_short":
        w.append("valid=1 AND n_free_names < ?")
        a.append(int(f.get("min_names") or config.load().get("max_copies") or 2))
    elif st == "warn":
        w.append("valid=1 AND warnings!='[]'")
    if f.get("category"):
        w.append("category LIKE ?")
        a.append(f"{f['category']}%")
    if f.get("price_min") not in (None, ""):
        w.append("price>=?")
        a.append(int(f["price_min"]))
    if f.get("price_max") not in (None, ""):
        w.append("price<=?")
        a.append(int(f["price_max"]))
    if f.get("copies") not in (None, ""):   # 복사 횟수: 0 = 미복사, 1 = 1회, 2 = 2회 이상 (내린 것 제외)
        c = int(f["copies"])
        w.append("n_listings>=?" if c >= 2 else "n_listings=?")
        a.append(c)
    ai = f.get("ai") or ""
    if ai == "none":        # AI 키워드를 아직 안 받음
        w.append("id NOT IN (SELECT source_id FROM ctx_kw WHERE status IN ('ok','pending'))")
    elif ai == "pending":   # 받는 중 (일괄 처리)
        w.append("id IN (SELECT source_id FROM ctx_kw WHERE status='pending')")
    elif ai == "old":       # 예전 지시(버전)로 받음 — 다시 받을지 직접 고름
        w.append("id IN (SELECT source_id FROM ctx_kw WHERE status='ok' AND ver!=?)")
        a.append(ctxkw.PROMPT_VER)
    elif ai == "failed":    # 실패
        w.append("id IN (SELECT source_id FROM ctx_kw WHERE status='retry')")
    elif ai == "free":      # 안 쓴 AI 이름 후보가 남음 (다른 스토어로 복사하면 바로 붙음)
        w.append("id IN (SELECT source_id FROM names WHERE origin='ctx' AND listing_id IS NULL)")
    elif ai == "used":      # 받았지만 후보를 다 씀
        w.append("id IN (SELECT source_id FROM ctx_kw WHERE status='ok') AND id NOT IN (SELECT source_id FROM names WHERE origin='ctx' AND listing_id IS NULL)")
    if f.get("adopted") in ("1", 1, True):     # 기존 상품 가져오기로 들어온 원본 (1 원본 이름 없음 · 2 원본 이름 있음)
        w.append("adopted>0")
    elif f.get("adopted") == "noname":
        w.append("adopted=1")
    elif f.get("adopted") in ("0", 0):
        w.append("adopted=0")
    if f.get("eye") == "done":                  # 눈검수 완료한 원본
        w.append("eye_at IS NOT NULL")
    elif f.get("eye") == "todo":                # 아직 눈검수 안 한 원본
        w.append("eye_at IS NULL")
    tg = f.get("src_tag") or ""
    if tg == "__none__":                        # 출처 태그 없는 원본
        w.append("src_tags=''")
    elif tg:
        w.append("instr(src_tags, ?)>0")
        a.append(f"|{tg}|")
    ch = f.get("chem") or ""
    if ch in ("tool", "chemical", "unclear"):   # 생활화학 판정
        w.append("chem_judge=?")
        a.append(ch)
    elif ch == "hold":                          # 보류 = 화학제품 + 애매
        w.append("chem_judge IN ('chemical','unclear')")
    elif ch == "drop":                          # 원본·복사본 모두 삭제 중 (판매 중 복사본을 내리는 중)
        w.append("drop_pending=1")
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
             "warnings, valid, n_listings, n_success, n_free_names, updated_at, chem_judge, chem_reason, drop_pending, src_tags, eye_at, adopted")


def query_sources(db, f, page=0, size=100):
    where, args = source_where(f)
    total = db.one(f"SELECT COUNT(*) AS n FROM sources{where}", args)["n"]
    rows = db.q(f"SELECT {LIST_COLS} FROM sources{where} ORDER BY id LIMIT ? OFFSET ?", (*args, size, page * size))
    for r in rows:
        r["errors"], r["warnings"] = json.loads(r["errors"]), json.loads(r["warnings"])
        r["src_tags"] = srctags.split(r["src_tags"])
        r["copies"], r["deleted_copies"] = [], 0
    # 이 쪽에 보이는 원본들의 복사본을 한 번에 가져와 원본 아래에 붙인다.
    by_id = {r["id"]: r for r in rows}
    if by_id:
        pv = price_viewer(db)
        for c in db.q(f"""SELECT l.id, l.source_id, l.store_id, l.name, l.price, l.sale_shown, l.status, l.op, l.round, l.seller_code,
                l.channel_no, l.registered_at, l.deleted_at, l.sold_count, l.cancel_count, l.locked, l.lock_note,
                l.message, t.name AS store,
                t.store_url, COALESCE(NULLIF(t.code,''), 'S'||printf('%02d', t.id)) AS code
                FROM listings l JOIN stores t ON t.id=l.store_id
                WHERE l.source_id IN ({','.join('?' * len(by_id))}) ORDER BY l.status='deleted', l.id""", list(by_id)):
            c.update(pv(c["price"], c["store_id"], bool(c["channel_no"]), c.get("sale_shown")))
            if c["status"] == "deleted":   # 내림도 원본당 자리를 차지하므로 칸에 같이 보인다
                by_id[c["source_id"]]["deleted_copies"] += 1
            by_id[c["source_id"]]["copies"].append(c)
        attach_ai_names(db, by_id)
    return {"rows": rows, "total": total}


def attach_ai_names(db, by_id):
    """원본마다 AI 키워드 상태와 AI 이름 후보(A·B…: 어느 스토어 복사본에 쓰였는지 / 남았는지)를 붙인다."""
    ids = list(by_id)
    for r in by_id.values():
        r["kw_status"], r["ai_names"] = "", []
    if not ids:
        return
    marks = ",".join("?" * len(ids))
    for k in db.q(f"SELECT source_id, status FROM ctx_kw WHERE source_id IN ({marks})", ids):
        by_id[k["source_id"]]["kw_status"] = k["status"]
    labels = ai_variants(db, ids)
    for n in db.q(f"""SELECT n.id, n.source_id, n.name, n.listing_id, l.status, l.origin_no,
            CASE WHEN t.id IS NULL THEN '' ELSE COALESCE(NULLIF(t.code,''), 'S'||printf('%02d', t.id)) END AS code, t.name AS store
            FROM names n LEFT JOIN listings l ON l.id=n.listing_id LEFT JOIN stores t ON t.id=l.store_id
            WHERE n.origin='ctx' AND n.source_id IN ({marks})
            ORDER BY n.listing_id IS NULL, CASE WHEN n.listing_id>0 THEN n.listing_id END, n.id""", ids):
        # 글자: A = 1번째 복사본에 붙은 이름, B = 2번째 복사본(없으면 안 쓴 이름)… 다시 바꿔도 그 복사본 이름은 같은 글자.
        # 바꿔서 안 쓰는 이름은 안 보이고 개수만
        r = by_id[n["source_id"]]
        if n["listing_id"] == -1:
            r["ai_retired"] = r.get("ai_retired", 0) + 1
            continue
        r["ai_names"].append({"label": labels.get(n["id"], _ai_label(len(r["ai_names"]))), "name": n["name"], "code": n["code"] or "",
                              "store": n["store"] or "", "live": bool(n["origin_no"]), "status": n["status"] or ""})


def _ai_label(i):
    return chr(65 + i) if i < 26 else str(i + 1)


def ai_variants(db, sids):
    """원본마다 AI 이름 번호 → 'A'/'B' (만들 때 정한 양식, 없으면 만든 순서의 짝·홀). 같은 양식이 또 있으면 A2·B2…"""
    out = {}
    sids = list(sids)
    for i in range(0, len(sids), 900):
        ch = sids[i:i + 900]
        seen = {}
        for n in db.q(f"""SELECT id, source_id, variant FROM names WHERE origin='ctx' AND source_id IN ({','.join('?' * len(ch))})
                ORDER BY source_id, id""", ch):
            k = seen.setdefault(n["source_id"], {"i": 0, "A": 0, "B": 0})
            v = n["variant"] if n["variant"] in ("A", "B") else "AB"[k["i"] % 2]
            k["i"] += 1
            k[v] += 1
            out[n["id"]] = v + (str(k[v]) if k[v] > 1 else "")
    return out


def source_ids(db, f):
    where, args = source_where(f)
    return [r["id"] for r in db.q(f"SELECT id FROM sources{where} ORDER BY id", args)]


def source_counts(db):
    return db.one("""SELECT COUNT(*) AS all_, SUM(valid=1) AS valid, SUM(valid=0) AS invalid,
        SUM(n_listings=0) AS c0, SUM(n_listings=1) AS c1, SUM(n_listings>=2) AS c2,
        SUM(valid=1 AND warnings!='[]') AS warn, SUM(eye_at IS NOT NULL) AS eye_done, SUM(eye_at IS NULL) AS eye_todo FROM sources""")


# ───────────────────────── 2. 상품명 후보

def _siblings(c, sid):
    return [r["name"] for r in c.execute("SELECT name FROM names WHERE source_id=?", (sid,))]


def generate_recombine(db, ids, per_source, progress=None, should_stop=None):
    """원본마다 안 쓴 이름 후보가 per_source개가 되도록 재조합으로 채운다."""
    cfg = config.load()
    cfg["_lex"] = lexicon.get(db)
    use_orig = 0   # 원본 이름은 복사본 이름 후보가 아님
    stats = {"sources": 0, "added": 0, "short": 0, "few_words": 0}
    new_min = int(cfg.get("recombine_new_min") or 0)
    if progress:
        progress(0, len(ids), "네이버 연관 키워드 받는 중 (아직 안 모은 원본)")
    stats["kw_error"], stats["kw_new"] = keywords.ensure_collected(db, cfg, ids, should_stop)
    cfg["_lex"] = lexicon.get(db)
    stats["ai"] = aiwords.ensure_words(db, cfg, ids, progress, should_stop)
    for i in range(0, len(ids), CHUNK):
        if should_stop and should_stop():
            break
        chunk = ids[i:i + CHUNK]
        rows = db.q(f"SELECT id, name, tags, category, n_free_names, core_kw, data FROM sources WHERE id IN ({','.join('?' * len(chunk))})",
                    chunk)
        _attach_words(db, cfg, rows)
        with db.tx() as c:
            for r in rows:
                free = c.execute("SELECT COUNT(*) FROM names WHERE source_id=? AND listing_id IS NULL "
                                 "AND (origin NOT IN ('original','adopt') OR ?)", (r["id"], use_orig)).fetchone()[0]
                need = per_source - free
                stats["sources"] += 1
                if len(namegen.new_word_candidates(r["name"], cfg, cfg["_lex"], r["category"], **_kw_args(r))) < new_min:
                    stats["few_words"] += 1
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
    stats = {"rows": 0, "added": 0, "dup": 0, "not_found": 0, "ambiguous": 0, "same_as_original": 0}
    key_col = name_cols = None
    by_name = by_thumb = False
    batch = []

    def flush():
        with db.tx() as c:
            for key, names in batch:
                if by_name:   # 원본 상품명이 완전히 같은 원본
                    found = c.execute("SELECT id, name FROM sources WHERE name=?", (key,)).fetchall()
                elif by_thumb:
                    found = c.execute("SELECT id, name FROM sources WHERE img_key=? LIMIT 2", (key,)).fetchall()
                else:
                    found = c.execute("SELECT id, name FROM sources WHERE seller_code=? OR source_key=? LIMIT 2",
                                      (key, key)).fetchall()
                if len(found) > 1:   # 여러 원본에 맞음 → 아무 데나 붙이지 않음
                    stats["ambiguous"] += 1
                    continue
                src = found[0] if found else None
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
            orig_col = next((k for k in ("원본상품명", "원본 상품명") if k in cols), None)
            if orig_col:
                key_col, by_name = orig_col, True   # 원본 기준은 상품명(완전히 같음) → 가장 정확
            elif "썸네일" in cols and not key_col:
                key_col, by_thumb = "썸네일", True  # 원본 엑셀 형식 그대로면 썸네일로 (여러 원본에 맞으면 건너뜀)
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
          f"원본 못 찾음 {stats['not_found']} · 여러 원본에 맞아 건너뜀 {stats['ambiguous']} · 다른 이름과 중복 {stats['dup']}", iid))
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
    s["src_tags"] = srctags.split(s.get("src_tags"))
    s["row"] = row
    s["names"] = db.q("""SELECT n.id, n.name, n.origin, n.listing_id, st.name AS store_name, l.status
        FROM names n LEFT JOIN listings l ON l.id=n.listing_id LEFT JOIN stores st ON st.id=l.store_id
        WHERE n.source_id=? ORDER BY n.listing_id IS NULL, n.id""", (sid,))
    ai = sorted((n for n in s["names"] if n["origin"] == "ctx" and n["listing_id"] != -1),
                key=lambda n: (n["listing_id"] is None, n["listing_id"] or 0, n["id"]))
    labels = ai_variants(db, [sid])
    for i, n in enumerate(ai):   # AI 이름 A·B: 만들 때 정한 양식 (원본 목록 줄·복사본 화면과 같은 글자)
        n["label"] = labels.get(n["id"], _ai_label(i))
    s["listings"] = db.q("""SELECT l.id, l.name, l.price, l.status, l.op, l.round, l.message, l.channel_no, l.sold_count,
        l.origin_no, l.seller_code, l.registered_at, l.deleted_at, l.store_id, st.name AS store_name, st.store_url,
        n.origin AS name_origin
        FROM listings l JOIN stores st ON st.id=l.store_id LEFT JOIN names n ON n.id=l.name_id
        WHERE l.source_id=? ORDER BY l.status='deleted', st.id""",
                         (sid,))
    k = db.one("SELECT words FROM ctx_kw WHERE source_id=?", (sid,))
    kw = ctxkw.kw_of(k["words"]) if k and k["words"] else {}
    for l in s["listings"]:
        l["nd"] = ctxkw.name_parts(l["name"], s["name"], kw, l["name_origin"])
    s["history"] = db.q("""SELECT h.*, st.name AS store_name FROM listing_history h
        JOIN listings l ON l.id=h.listing_id JOIN stores st ON st.id=l.store_id
        WHERE l.source_id=? ORDER BY h.deleted_at DESC""", (sid,))
    s["max_copies"] = int(config.load().get("max_copies") or 2)
    return s


# ───────────────────────── 3. 등록 계획

def assign_ctx_names(db, sids, only=None, newest=False):
    """이 원본들의 아직 안 올린·이름 없는 복사본에 맥락 키워드로 만든 안 쓴 이름 후보를 하나씩 배정한다. 배정한 수.
    only: 이 복사본들에만. newest: 가장 최근에 만든 후보부터 (이름 다시 바꾸기 — 다른 스토어 몫 B를 남겨 둠)."""
    only = set(only) if only is not None else None
    n = 0
    now = time.time()
    for i in range(0, len(sids), 500):
        chunk = list(sids)[i:i + 500]
        marks = ",".join("?" * len(chunk))
        with db.tx() as c:
            free = {}
            for r in c.execute(f"""SELECT id, source_id, name, variant FROM names WHERE origin='ctx' AND listing_id IS NULL
                    AND source_id IN ({marks}) ORDER BY id {'DESC' if newest else ''}""", chunk):
                free.setdefault(r["source_id"], []).append(dict(r))
            if not newest:   # 첫 복사에는 늘 A 양식부터 (A를 쓴 복사본을 되돌리면 다음 복사에 다시 A)
                for pool in free.values():
                    pool.sort(key=lambda n: (n["variant"] == "B", n["id"]))
            # 고른 복사본(only)이면 내린 것도 (다시 올리기 전 이름 바꾸기), 아니면 지금 있는 것만
            for l in c.execute(f"""SELECT id, source_id FROM listings WHERE name_id IS NULL AND origin_no=''
                    AND status NOT IN ('queued','running')
                    AND (status!='deleted' OR ?) AND source_id IN ({marks}) ORDER BY id""", (int(only is not None), *chunk)).fetchall():
                if only is not None and l["id"] not in only:
                    continue
                pool = free.get(l["source_id"])
                if not pool:
                    continue
                nm = pool.pop(0)
                c.execute("UPDATE listings SET name_id=?, name=?, updated_at=? WHERE id=?", (nm["id"], nm["name"], now, l["id"]))
                c.execute("UPDATE names SET listing_id=? WHERE id=?", (l["id"], nm["id"]))
                n += 1
        db.recount_sources(chunk)
    return n


def _free_names(c, sid, use_orig):
    rows = [dict(r) for r in c.execute(
        "SELECT id, name, origin FROM names WHERE source_id=? AND listing_id IS NULL AND (origin NOT IN ('original','adopt') OR ?)",
        (sid, int(use_orig)))]
    rows.sort(key=lambda n: (NAME_ORIGIN_ORDER.get(n["origin"], 9), n["id"]))
    return rows


def _kw_args(s):
    _, kw = s.get("_kw") or ("", [])
    return {"kw_words": kw, "ai_words": s.get("_ai") or ()}


def _attach_words(db, cfg, rows):
    """재조합 전에 원본 행에 네이버 키워드(_kw)·AI 단어(_ai)를 붙이고 무거운 data는 뗀다."""
    kws = keywords.words_for(db, rows, cfg, cfg["_lex"])
    ais = aiwords.words_for(db, rows, cfg, cfg["_lex"])
    for r in rows:
        r["_kw"] = kws.get(r["id"])
        r["_ai"] = ais.get(r["id"]) or ()
        r.pop("data", None)


class StoreContext:
    """스토어마다: 새 단어를 쓴 횟수, 이미 쓴 상품명(카테고리·첫 단어별 단어 집합).
    재조합 때 많이 쓴 단어는 덜 뽑고, 같은 스토어 내 다른 상품명과 너무 비슷한 이름은 버리는 데 쓴다."""

    def __init__(self, db, store_ids):
        self.use = aiwords.use_counts(db, store_ids)
        self.idx = {sid: {} for sid in store_ids}
        if store_ids:
            for r in db.q(f"""SELECT l.store_id, l.name, s.category FROM listings l JOIN sources s ON s.id=l.source_id
                    WHERE l.name_id IS NOT NULL AND l.status!='deleted' AND l.store_id IN ({','.join('?' * len(store_ids))})""",
                          list(store_ids)):
                self.add(r["store_id"], r["category"], r["name"])

    @staticmethod
    def _key(category, name):
        t = namegen.tokens(name)
        return (lexicon.cat_key(category or ""), t[0].lower() if t else "")

    def add(self, store_id, category, name):
        self.idx.setdefault(store_id, {}).setdefault(self._key(category, name), []).append(
            {x.lower() for x in namegen.tokens(name)})

    def neighbors(self, store_id, category, original, lex):
        first = namegen.safe_tokens(original, lex)
        return self.idx.get(store_id, {}).get(self._key(category, " ".join(first)), [])


def _new_words(original, name):
    orig = {t.lower() for t in namegen.tokens(original)}
    return [t for t in namegen.tokens(name) if t.lower() not in orig]


def name_for_listing(c, s, store_id, cfg, now, ctx, avoid=()):
    """한 복사본(스토어)에 맞춘 재조합 이름을 하나 만들어 후보에 넣고 돌려준다 ({id, name} 또는 None)."""
    lex = cfg["_lex"]
    for attempt in range(3):
        sibs = _siblings(c, s["id"])
        cands = namegen.recombine(s["name"], 1, set(), sibs, cfg, seed=f"{s['id']}:{store_id}:{len(sibs)}:{attempt}",
                                  tag_words=[t for t in (s.get("tags") or "").split(",") if t],
                                  category=s.get("category") or "", lex=lex,
                                  use_count=ctx.use.get(store_id), avoid=avoid,
                                  neighbors=ctx.neighbors(store_id, s.get("category"), s["name"], lex), **_kw_args(s))
        if not cands:
            continue
        add_names(c, s["id"], cands, "recombine", now)
        r = c.execute("SELECT id, name FROM names WHERE source_id=? AND norm=? AND listing_id IS NULL",
                      (s["id"], namegen.normalize(cands[0]))).fetchone()
        if r:
            return dict(r)
    return None


def assign_name(c, lid, store_id, s, nm, now, ctx):
    c.execute("UPDATE listings SET name_id=?, name=?, updated_at=? WHERE id=?", (nm["id"], nm["name"], now, lid))
    c.execute("UPDATE names SET listing_id=? WHERE id=?", (lid, nm["id"]))
    aiwords.count_use(c, store_id, s["name"], nm["name"])
    for w in _new_words(s["name"], nm["name"]):
        ctx.use.setdefault(store_id, {})[w] = ctx.use.get(store_id, {}).get(w, 0) + 1
    ctx.add(store_id, s.get("category"), nm["name"])


def _fill_names(c, s, need, cfg, now):
    """이름 후보가 need개보다 적으면 재조합으로 채우고, 안 쓴 후보 목록을 돌려준다."""
    use_orig = False
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


def release_name(c, lid, name_id=None, drop_origins=None):
    """복사본에서 이름을 뗄 때: 네이버에 올라갔던(올린 적 있는) 복사본이면 그 이름은 '다 쓴 이름'(-1)으로 남겨
    다른 복사본이 다시 쓰지 않게 하고, 한 번도 안 올린 복사본이면 지금처럼 후보로 돌린다(drop_origins 출처면 지움)."""
    ids = [name_id] if name_id else [r[0] for r in c.execute("SELECT id FROM names WHERE listing_id=?", (lid,)).fetchall()]
    if not ids:
        return
    used = c.execute("""SELECT 1 FROM listings WHERE id=? AND (registered_at IS NOT NULL OR origin_no!='')
        UNION SELECT 1 FROM listing_history WHERE listing_id=?""", (lid, lid)).fetchone()
    for nid in ids:
        if used:
            c.execute("UPDATE names SET listing_id=-1 WHERE id=?", (nid,))
            continue
        if drop_origins:
            c.execute(f"DELETE FROM names WHERE id=? AND origin NOT IN ({','.join('?' * len(drop_origins))})", (nid, *drop_origins))
        c.execute("UPDATE names SET listing_id=NULL WHERE id=?", (nid,))


def _pair(a, b):
    return (a, b) if a < b else (b, a)


def plan_spread(db, ids, store_ids, per_product, seed=None):
    """'원본마다 N곳이 되도록 골고루': 원본을 무작위 순서로 하나씩, 스토어를 한 곳씩 고른다.
    점수 = 그 스토어에 이미 배정된 수 + 3 × (이 원본에 이미 고른(있는) 스토어들과 지금까지 같이 묶인 횟수의 합)
    점수가 가장 낮은 곳, 동점이면 무작위. 스토어 한도·원본당 최대 max_copies곳(내린 스토어 제외)·이미 있는 스토어 제외.
    '같이 묶인 횟수'는 이미 있는 복사본(등록된 것·이전 계획)과 이번 계획을 모두 센다.
    → ({원본 id: [스토어 id…]}, 미리보기 통계)"""
    cfg = config.load()
    max_copies = max(1, int(cfg.get("max_copies") or 2))
    stores = {s["id"]: s for s in db.stores() if s["id"] in set(store_ids) and s["enabled"]}
    if not stores:
        raise ValueError("등록할 스토어를 골라 주세요. (사용 중지된 스토어는 제외)")
    free = {sid: s["free"] for sid, s in stores.items()}
    assigned = {sid: 0 for sid in stores}
    pair = {}
    have = {}
    gone = {}
    for r in db.q("SELECT source_id, store_id, status FROM listings"):
        if r["status"] == "deleted":   # 내림: 자리는 차지(원본당 최대 수에 셈), 다시 고르면 그 줄을 되살림
            gone.setdefault(r["source_id"], set()).add(r["store_id"])
            continue
        have.setdefault(r["source_id"], set()).add(r["store_id"])
        if r["store_id"] in assigned:
            assigned[r["store_id"]] += 1
    for ss in have.values():
        ss = sorted(ss)
        for i, a in enumerate(ss):
            for b in ss[i + 1:]:
                pair[(a, b)] = pair.get((a, b), 0) + 1
    valid = set()
    for i in range(0, len(ids), 900):
        chunk = list(ids)[i:i + 900]
        valid |= {r["id"] for r in db.q(f"SELECT id FROM sources WHERE valid=1 AND id IN ({','.join('?' * len(chunk))})", chunk)}
    rnd = random.Random(seed)
    order = [i for i in ids if i in valid]
    rnd.shuffle(order)
    out = {}
    before = dict(assigned)
    for sid in order:
        mine = set(have.get(sid, ()))
        dead = gone.get(sid, set()) - mine
        fresh_left = max_copies - len(mine | dead)
        want = max(0, per_product - len(mine & set(stores)))
        picks = []
        for _ in range(want):
            cand = [s for s in stores if s not in mine and free[s] > 0 and (s in dead or fresh_left > 0)]
            if not cand:
                break
            score = {s: assigned[s] + 3 * sum(pair.get(_pair(s, t), 0) for t in mine) for s in cand}
            low = min(score.values())
            pick = rnd.choice([s for s in cand if score[s] == low])
            for t in mine:
                k = _pair(pick, t)
                pair[k] = pair.get(k, 0) + 1
            mine.add(pick)
            if pick not in dead:
                fresh_left -= 1
            picks.append(pick)
            assigned[pick] += 1
            free[pick] -= 1
        if picks:
            out[sid] = picks
            have[sid] = mine
    added = {s: assigned[s] - before[s] for s in stores}
    shares = []
    for (a, b), n in pair.items():
        if a in stores and b in stores and n:
            shares.append((n / max(1, min(assigned[a], assigned[b])), a, b, n))
    shares.sort(reverse=True)
    names = {s: stores[s]["name"] for s in stores}
    vals = list(added.values())
    avg = sum(vals) / len(vals) if vals else 0
    preview = {
        "sources": len(order), "copies": sum(vals), "seed": seed,
        "per_store": [{"store_id": s, "name": names[s], "added": added[s], "total": assigned[s]} for s in stores],
        "spread_pct": round(100 * (max(vals) - min(vals)) / avg, 2) if avg else 0,
        "max_share_pct": round(100 * shares[0][0], 2) if shares else 0,
        "top_pairs": [{"a": names[a], "b": names[b], "shared": n, "pct": round(100 * r, 2)} for r, a, b, n in shares[:3]],
    }
    return out, preview


def create_plan(db, ids, store_ids, mode="all", per_product=1, title="", progress=None, should_stop=None, seed=None):
    """원본 × 스토어마다 등록 한 건(planned)을 만든다.

    원본 하나는 최대 max_copies곳(기본 3)까지만. 내린(deleted) 스토어는 세지 않는다.
    mode="all":    고른 스토어에 (원본마다 남은 칸만큼, 남은 자리가 많은 스토어부터)
    mode="spread": 원본마다 per_product곳이 되도록 (이미 고른 스토어에 있는 것 포함)
    복사본은 원본 상품명 그대로 만든다. 복사본 화면에서 상품명을 바꿔야(rename_listings) 등록된다.
    전에 내렸던 스토어에 다시 계획하면 같은 줄을 다음 회차로 살린다 (이름·가격 그대로, 설정으로 다시 바꾸게).
    """
    cfg = config.load()
    cfg["_lex"] = lexicon.get(db)
    max_copies = max(1, int(cfg.get("max_copies") or 2))
    stores = {s["id"]: s for s in db.stores() if s["id"] in set(store_ids) and s["enabled"]}
    if not stores:
        raise ValueError("등록할 스토어를 골라 주세요. (사용 중지된 스토어는 제외)")
    free = {sid: s["free"] for sid, s in stores.items()}
    now = time.time()
    pid = db.x("INSERT INTO plans(title, created_at) VALUES(?, ?)",
               (title or time.strftime("%m/%d %H:%M 계획"), now))
    st = {"created": 0, "revived": 0, "exists": 0, "full": 0, "no_name": 0, "capacity": 0, "invalid": 0, "sources": 0}
    rot = 0
    spread = plan_spread(db, ids, store_ids, per_product, seed)[0] if mode == "spread" else None
    new_ids = []

    for i in range(0, len(ids), CHUNK):
        if should_stop and should_stop():
            break
        chunk = ids[i:i + CHUNK]
        marks = ",".join("?" * len(chunk))
        srcs = db.q(f"SELECT id, COALESCE(NULLIF(price_seed,''), source_key) AS source_key, name, price, tags, category, valid FROM sources WHERE id IN ({marks})", chunk)
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
                gone = dead.get(s["id"], {})
                # 내린(내림) 복사본도 그 스토어 자리를 차지한다 → 원본당 최대 max_copies곳은 내림까지 센다.
                # 내림이 있는 스토어로 다시 복사하면 그 줄을 다음 회차로 되살리므로 새 자리를 쓰지 않는다.
                slots = max_copies - len(set(act) | set(gone))
                cand = [sid for sid in stores if sid not in act]
                st["exists"] += len(stores) - len(cand)
                revive = [sid for sid in cand if sid in gone]
                fresh = [sid for sid in cand if sid not in gone]
                if slots <= 0 and not revive:
                    st["full"] += 1
                    continue
                rot += 1
                fresh.sort(key=lambda sid: (-free[sid], (sid + rot) % len(stores)))
                fresh = [sid for sid in fresh if free[sid] > 0] or fresh
                if mode == "spread":
                    pick = spread.get(s["id"], [])   # 점수 규칙으로 미리 고른 스토어 (plan_spread)
                    targets = [x for x in pick if x in gone] + [x for x in pick if x not in gone][:max(0, slots)]
                else:
                    targets = revive + fresh[:max(0, slots)]
                if mode == "all" and len(fresh) > max(0, slots):
                    st["full"] += 1  # 고른 스토어가 남은 칸보다 많아 일부만
                if not targets:
                    continue
                for sid in targets:
                    if free[sid] <= 0:
                        st["capacity"] += 1
                        continue
                    old = dead.get(s["id"], {}).get(sid)
                    price = convert.store_price(s["price"], cfg, stores[sid])
                    if old:
                        # 전에 내렸던 스토어: 같은 줄을 다음 회차로 (이름 그대로, 설정하면 원본 상품명으로 돌려 다시 바꾸게)
                        if cfg.get("refresh_new_name"):
                            release_name(c, old["id"], drop_origins=("original", "adopt"))
                            c.execute("UPDATE listings SET name_id=NULL, name=? WHERE id=?", (s["name"], old["id"]))
                        c.execute("""UPDATE listings SET status='planned', op='create',
                            round=CASE WHEN round_reset=1 THEN 1 ELSE round+1 END, round_reset=0, plan_id=?,
                            message='', stage='', updated_at=? WHERE id=?""", (pid, now, old["id"]))
                        st["revived"] += 1
                    else:
                        # 복사본은 원본 상품명 그대로 만든다 → 복사본 화면에서 상품명을 바꿔야 등록됨
                        c.execute("""INSERT INTO listings(store_id, source_id, plan_id, name_id, name, price,
                            status, created_at, updated_at) VALUES(?,?,?,NULL,?,?,'planned',?,?)""",
                                  (sid, s["id"], pid, s["name"], price, now, now))
                        st["created"] += 1
                        new_ids.append(s["id"])
                    free[sid] -= 1
                touched.append(s["id"])
        db.recount_sources(touched)
        if progress:
            progress(min(i + CHUNK, len(ids)), len(ids), f"등록 {st['created'] + st['revived']:,}건 계획")
    # 맥락 키워드로 만들어 둔 이름 후보가 있으면 스토어가 정해진 복사본에 하나씩 배정 (없으면 '이름 변경 필요')
    st["named"] = assign_ctx_names(db, sorted(set(new_ids))) if new_ids else 0
    db.x("UPDATE plans SET note=? WHERE id=?", (json.dumps(st, ensure_ascii=False), pid))
    if not st["created"] and not st["revived"]:
        db.x("DELETE FROM plans WHERE id=?", (pid,))
        pid = None
    st["plan_id"] = pid
    return st


def rename_shuffle(db, ids, fixed_n=3, extra=(), progress=None, should_stop=None):
    """셔플: 앞 fixed_n단어 고정, 나머지 단어와 직접 넣은 단어를 함께 섞어 복사본마다 새 이름 (AI 안 씀).
    이미 바꾼 이름이 있으면 버리고 새로 만든다. 33개 스토어 중복·원본과 같은 이름·금지어는 거른다."""
    from . import ctxname, shuffle
    cfg = config.load()
    lex = lexicon.get(db)
    forb = set(lex.blocked)
    max_chars = int(cfg.get("name_max_len") or 50)
    # 넣을 단어도 AI 단어와 같은 기준으로 거름: 금지어·상표·직접 차단한 단어, 판매 조건·과장 표현(무료배송·최저가 …)
    bad = ctxkw.word_filter(cfg, lex)
    dropped = [w for w in extra if w in forb or bad(w) or ctxname.claim_word(w)]
    extra = [w for w in extra if w not in dropped]
    set_ctx_wait(db, ids, 0)   # 셔플로 바꿨으면 AI 키워드가 와도 덮어쓰지 않음
    rows = []
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        rows += db.q(f"""SELECT l.id, l.source_id, l.name_id, l.origin_no, l.status, s.name AS orig FROM listings l
            JOIN sources s ON s.id=l.source_id WHERE l.id IN ({','.join('?' * len(chunk))})""", chunk)
    # 안 올린 것·내린 것(다시 올리기 전 이름 바꾸기). 지금 등록 중(queued·running)인 것은 빼기 — 네이버에 예전 이름이 올라가고 이름이 풀리지 않게
    todo = [r for r in rows if not r["origin_no"] and r["status"] not in ("queued", "running")]
    st = {"listings": len(rows), "live": len(rows) - len(todo), "renamed": 0, "short": 0, "method": "shuffle",
          "dropped_extra": dropped}
    now = time.time()
    for i in range(0, len(todo), 500):
        if should_stop and should_stop():
            break
        part = todo[i:i + 500]
        with db.tx() as c:
            reject = ctxkw.make_rejecter(c, cfg, lex)
            for r in part:
                if r["name_id"]:
                    release_name(c, r["id"], r["name_id"], ("original", "manual", "import", "adopt"))
                name = shuffle.make(r["orig"], fixed_n, extra, forb, seed=f"{r['id']}:{now}", reject=reject, max_chars=max_chars,
                                    rep=ctxkw.repeat_check(cfg, lex))
                if not name:
                    c.execute("UPDATE listings SET name_id=NULL, name=?, updated_at=? WHERE id=?", (r["orig"], now, r["id"]))
                    st["short"] += 1
                    continue
                add_names(c, r["source_id"], [name], "shuffle", now)
                nid = c.execute("SELECT id FROM names WHERE norm=?", (namegen.normalize(name),)).fetchone()["id"]
                c.execute("UPDATE listings SET name_id=?, name=?, updated_at=? WHERE id=?", (nid, name, now, r["id"]))
                c.execute("UPDATE names SET listing_id=? WHERE id=?", (r["id"], nid))
                st["renamed"] += 1
        db.recount_sources(sorted({r["source_id"] for r in part}))
        if progress:
            progress(min(i + 500, len(todo)), len(todo), f"셔플 {st['renamed']:,}건")
    return st


def refresh_name(c, src, store_id, cfg, now):
    """최신화 때 새 이름: 안 쓴 AI 맥락 후보가 있으면 그것, 없으면 셔플 (설정의 고정 단어 수)."""
    from . import shuffle
    r = c.execute("""SELECT id, name FROM names WHERE source_id=? AND origin='ctx' AND listing_id IS NULL
        ORDER BY variant='B', id LIMIT 1""", (src["id"],)).fetchone()
    if r:
        return dict(r)
    lex = cfg["_lex"]
    name = shuffle.make(src["name"], int(cfg.get("shuffle_fixed") or 3), (), set(lex.blocked), seed=f"{src['id']}:{store_id}:{now}",
                        reject=ctxkw.make_rejecter(c, cfg, lex), max_chars=int(cfg.get("name_max_len") or 50))
    if not name:
        return None
    add_names(c, src["id"], [name], "shuffle", now)
    return dict(c.execute("SELECT id, name FROM names WHERE norm=?", (namegen.normalize(name),)).fetchone())


def set_ctx_wait(db, ids, value):
    """AI 키워드를 기다리는 복사본 표시: 1 = 오면 이름 바꿈(있던 이름도), 2 = 이름 없는 것만, 0 = 지움.
    다른 방식으로 이름을 바꾸거나 직접 고치면 지운다."""
    for i in range(0, len(ids), 900):
        chunk = list(ids)[i:i + 900]
        db.x(f"UPDATE listings SET ctx_wait=? WHERE id IN ({','.join('?' * len(chunk))})", (int(value), *chunk))


def ctx_waiting(db, sids):
    """이 원본들의 복사본 중 AI 키워드를 기다리던(이름 바꾸기를 눌러 둔) 아직 안 올린 것 → {1: [...], 2: [...]}."""
    out = {1: [], 2: []}
    for i in range(0, len(sids), 900):
        chunk = list(sids)[i:i + 900]
        for r in db.q(f"""SELECT id, ctx_wait FROM listings WHERE ctx_wait IN (1, 2) AND origin_no=''
                AND source_id IN ({','.join('?' * len(chunk))})""", chunk):
            out[r["ctx_wait"]].append(r["id"])
    return out


def rename_ctx(db, ids, fallback=False, progress=None, should_stop=None, redo=True):
    """AI 키워드 방식(기본): 키워드를 받은 원본은 이름 후보(A·B)를 만들어 고른 복사본에 붙인다.
    redo면 이미 이름이 있는 복사본(AI 키워드·셔플·AI로 짓기 이름 등)도 새 이름으로 바꾼다 — 바꾸기를 눌렀는데
    그대로면 안 되므로, 후보(A·B)를 다 썼으면 다른 조합으로 새 후보를 그 자리에서 만든다 (AI는 다시 부르지 않음).
    키워드가 없는 원본은 '상품명 변경 필요'로 두고, 키워드를 받으면 자동으로 붙는다."""
    rows = []
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        rows += db.q(f"""SELECT l.id, l.source_id, l.name_id, l.origin_no, l.status, n.origin FROM listings l
            LEFT JOIN names n ON n.id=l.name_id WHERE l.id IN ({','.join('?' * len(chunk))})""", chunk)
    # 안 올린 것·내린 것(다시 올리기 전 이름 바꾸기). 지금 등록 중(queued·running)인 것은 빼기 — 네이버에 예전 이름이 올라가고 이름이 풀리지 않게
    todo = [r for r in rows if not r["origin_no"] and r["status"] not in ("queued", "running")]
    set_ctx_wait(db, [r["id"] for r in todo], 0)
    st = {"listings": len(rows), "live": len(rows) - len(todo), "renamed": 0, "kept": 0, "short": 0, "no_kw": 0,
          "fallback": 0, "method": "ctx"}
    src = sorted({r["source_id"] for r in todo})
    ok = set()
    for i in range(0, len(src), 900):
        chunk = src[i:i + 900]
        ok |= {r["source_id"] for r in db.q(f"""SELECT source_id FROM ctx_kw WHERE status='ok'
            AND source_id IN ({','.join('?' * len(chunk))})""", chunk)}
    mine = [r for r in todo if r["source_id"] in ok]
    rest = [r for r in todo if r["source_id"] not in ok]
    if progress:
        progress(0, len(todo), "맥락 키워드로 이름 후보 만드는 중")
    st["names"] = ctxkw.build_names(db, sorted(ok))
    if progress:
        progress(len(mine) // 2, max(1, len(todo)), "이름 후보를 복사본에 붙이는 중")
    avoid = {}   # 떼어 낸 이름은 다시 붙이지 않음
    redone = []  # 이름을 다시 바꾸는 복사본 → A·B가 아니라 새 조합으로 (안 쓴 B는 다음 스토어 몫으로 남김)
    with db.tx() as c:
        for r in mine:
            if not r["name_id"]:
                continue
            if not redo:
                st["kept"] += 1
                continue
            redone.append(r)
            old = c.execute("SELECT name, origin FROM names WHERE id=?", (r["name_id"],)).fetchone()
            if old:
                avoid.setdefault(r["source_id"], set()).add(old["name"])
            if old and old["origin"] in ("original", "manual", "import", "adopt"):
                c.execute("UPDATE names SET listing_id=NULL WHERE id=?", (r["name_id"],))   # 직접 넣은 이름은 후보로 돌림
            else:
                # 바꿔 버린 이름은 '다 쓴 이름'(listing_id=-1)으로 남겨, 다시 바꿀 때 같은 이름이 돌아오지 않게 한다
                c.execute("UPDATE names SET listing_id=-1 WHERE id=?", (r["name_id"],))
            c.execute("UPDATE listings SET name_id=NULL, name=(SELECT name FROM sources WHERE id=?) WHERE id=?",
                      (r["source_id"], r["id"]))
    srcs = sorted({r["source_id"] for r in mine})
    redone_ids = {r["id"] for r in redone}
    # 처음 이름을 붙이는 복사본: 만들어 둔 A·B 순서대로
    st["renamed"] = assign_ctx_names(db, srcs, only=[r["id"] for r in mine if r["id"] not in redone_ids])
    # 다시 바꾸는 복사본: 새 조합을 만들어 그것을 붙임 (A·B 중 안 쓴 것은 다른 스토어 몫으로 남음)
    if redone:
        need = {}
        for r in redone:
            need[r["source_id"]] = need.get(r["source_id"], 0) + 1
        st["extra_made"] = ctxkw.make_more(db, need, avoid)
        st["renamed"] += assign_ctx_names(db, sorted(need), only=redone_ids, newest=True)
        need = {}
    # 후보(A·B)를 다 써서 아직 이름이 없는 복사본 → 그 원본 키워드로 다른 조합을 더 만든다
    need = {}
    for r in db.q(f"""SELECT source_id, COUNT(*) AS n FROM listings WHERE name_id IS NULL AND origin_no=''
            AND id IN ({','.join('?' * len(mine))}) GROUP BY source_id""", [r["id"] for r in mine]) if mine else []:
        need[r["source_id"]] = r["n"]
    if need:
        st["extra_made"] = st.get("extra_made", 0) + ctxkw.make_more(db, need, avoid)
        st["renamed"] += assign_ctx_names(db, sorted(need), only=[r["id"] for r in mine])
    left = db.q(f"""SELECT COUNT(*) AS n FROM listings WHERE name_id IS NULL AND origin_no=''
        AND id IN ({','.join('?' * len(mine))})""", [r["id"] for r in mine])[0]["n"] if mine else 0
    st["short"] = left
    if progress:
        progress(len(todo), max(1, len(todo)), "끝")
    if rest:
        if fallback:
            fb = rename_listings(db, [r["id"] for r in rest], "recombine", progress, should_stop)
            st["fallback"] = fb.get("renamed", 0)
            st["short"] += fb.get("short", 0)
            st["ai"] = fb.get("ai")
        else:
            st["no_kw"] = len({r["source_id"] for r in rest})
            st["no_kw_listings"] = len(rest)
            rs = sorted({r["source_id"] for r in rest})
            kst = {}
            for i in range(0, len(rs), 900):
                for r in db.q(f"SELECT status, COUNT(*) AS n FROM ctx_kw WHERE source_id IN ({','.join('?' * len(rs[i:i + 900]))}) GROUP BY status",
                              rs[i:i + 900]):
                    kst[r["status"]] = kst.get(r["status"], 0) + r["n"]
            st["kw_pending"], st["kw_failed"] = kst.get("pending", 0), kst.get("retry", 0)
            st["kw_none"] = st["no_kw"] - st["kw_pending"] - st["kw_failed"]
            # 키워드를 받는 중·재시도 대기인 원본의 복사본: 키워드가 오면 이 복사본 이름을 바꿈
            # (이미 이름이 있는 것·내린 것도 — 바꾸기를 눌렀으니까)
            waiting = set()
            for i in range(0, len(rs), 900):
                waiting |= {r["source_id"] for r in db.q(f"""SELECT source_id FROM ctx_kw WHERE status IN ('pending','retry')
                    AND source_id IN ({','.join('?' * len(rs[i:i + 900]))})""", rs[i:i + 900])}
            set_ctx_wait(db, [r["id"] for r in rest if r["source_id"] in waiting], 1 if redo else 2)
            st["kw_wait_listings"] = sum(1 for r in rest if r["source_id"] in waiting)
    return st


def rename_listings(db, ids, method="recombine", progress=None, should_stop=None):
    """복사본 상품명 바꾸기 (아직 안 올린 복사본만).
    method: recombine(재조합: AI가 준 새 단어로 스토어마다 따로 조립) / ai(Claude가 이름 전체를 지음, 모자라면 재조합)
            / pool(만들어 둔 후보만)
    재조합은 원본마다 처음 한 번 AI에게 새 단어를 받아 저장하고(단어 은행에 충분하면 AI 없이), 그 단어로 조립한다.
    이미 바꾼 이름이 있으면 그 이름은 버리고 새로 고르며, 지난 이름에 넣었던 새 단어는 되도록 피한다."""
    cfg = config.load()
    cfg["_lex"] = lexicon.get(db)
    set_ctx_wait(db, ids, 0)
    rows = []
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        rows += db.q(f"""SELECT id, store_id, source_id, name_id, name, origin_no, status FROM listings
            WHERE id IN ({','.join('?' * len(chunk))})""", chunk)
    st = {"renamed": 0, "short": 0, "live": 0, "listings": len(rows), "few_words": 0}
    new_min = int(cfg.get("recombine_new_min") or 0)
    # 안 올린 것·내린 것(다시 올리기 전 이름 바꾸기). 지금 등록 중(queued·running)인 것은 빼기 — 네이버에 예전 이름이 올라가고 이름이 풀리지 않게
    todo = [r for r in rows if not r["origin_no"] and r["status"] not in ("queued", "running")]
    st["live"] = len(rows) - len(todo)
    by_src = {}
    for r in todo:
        by_src.setdefault(r["source_id"], []).append(r)
    src_ids = list(by_src)
    if method == "recombine" and src_ids:
        if progress:
            progress(0, len(todo), "네이버 연관 키워드 받는 중 (아직 안 모은 원본)")
        st["kw_error"], st["kw_new"] = keywords.ensure_collected(db, cfg, src_ids, should_stop)
        cfg["_lex"] = lexicon.get(db)
    if method == "recombine" and src_ids:
        if progress:
            progress(0, len(todo), "새 단어 받는 중 (단어 은행 → AI)")
        st["ai"] = aiwords.ensure_words(db, cfg, src_ids, progress, should_stop)
    if method == "ai" and src_ids:
        # 원본마다 필요한 수만큼 AI로 더 짓는다 (원본별로 개수가 달라도 넉넉히 최대값으로)
        generate_ai(db, src_ids, max(len(v) for v in by_src.values()), should_stop=should_stop)
    ctx = StoreContext(db, sorted({r["store_id"] for r in todo})) if method == "recombine" else None
    now = time.time()
    done = 0
    for i in range(0, len(src_ids), CHUNK):
        if should_stop and should_stop():
            break
        chunk = src_ids[i:i + CHUNK]
        srcs = db.q(f"""SELECT id, name, tags, category, core_kw, data FROM sources
            WHERE id IN ({','.join('?' * len(chunk))})""", chunk)
        _attach_words(db, cfg, srcs)
        with db.tx() as c:
            for s in srcs:
                ls = by_src[s["id"]]
                old = {}
                for l in ls:
                    if l["name_id"]:
                        old[l["id"]] = _new_words(s["name"], l["name"])
                        release_name(c, l["id"], l["name_id"], ("original", "adopt"))
                if method != "pool" and len(namegen.new_word_candidates(
                        s["name"], cfg, cfg["_lex"], s.get("category") or "", **_kw_args(s))) < new_min:
                    st["few_words"] += 1
                if method == "pool":
                    pool = _free_names(c, s["id"], False)
                elif method == "ai":
                    pool = _fill_names(c, s, len(ls), {**cfg, "auto_recombine": False}, now)   # AI 이름만 (모자라면 그대로)
                else:
                    pool = None
                for l in ls:
                    nm = None
                    if pool is None:
                        nm = name_for_listing(c, s, l["store_id"], cfg, now, ctx, avoid=old.get(l["id"], ()))
                        if not nm:   # 스토어에 맞춘 이름을 못 만들면 만들어 둔 후보라도
                            free = _free_names(c, s["id"], False)
                            nm = free[0] if free else None
                    elif pool:
                        nm = pool.pop(0)
                    if not nm:
                        c.execute("UPDATE listings SET name_id=NULL, name=?, updated_at=? WHERE id=?", (s["name"], now, l["id"]))
                        st["short"] += 1
                        continue
                    if ctx:
                        assign_name(c, l["id"], l["store_id"], s, nm, now, ctx)
                    else:
                        c.execute("UPDATE listings SET name_id=?, name=?, updated_at=? WHERE id=?", (nm["id"], nm["name"], now, l["id"]))
                        c.execute("UPDATE names SET listing_id=? WHERE id=?", (l["id"], nm["id"]))
                    st["renamed"] += 1
                done += len(ls)
        db.recount_sources(chunk)
        if progress:
            progress(done, len(todo), f"상품명 바꿈 {st['renamed']:,}건")
    return st


def set_listing_name(db, lid, name):
    """복사본 상품명 직접 입력. 금지 단어·상표·반복 검사와 33개 스토어 중복 검사를 거친다."""
    cfg = {**config.load(), "_lex": lexicon.get(db)}
    l = db.one("SELECT id, source_id, name_id, origin_no, status FROM listings WHERE id=?", (lid,))
    if not l:
        raise ValueError("복사본이 없습니다.")
    if l["origin_no"]:
        raise ValueError("이미 올라간 복사본입니다. 최신화로 다시 올릴 때 이름을 바꾸세요.")
    if l["status"] in ("queued", "running"):
        raise ValueError("지금 등록 중인 복사본입니다. 등록이 끝난 뒤에 이름을 바꾸세요.")
    from . import ctxname
    src_words = set((db.one("SELECT name FROM sources WHERE id=?", (l["source_id"],)) or {}).get("name", "").split())
    claims = [w for w in str(name or "").split() if w not in src_words and ctxname.claim_word(w)]
    if claims:   # 원본에 없던 판매 조건·과장 표현은 직접 넣을 수 없음
        raise ValueError(f"쓸 수 없는 표현입니다: '{claims[0]}' ({ctxname.claim_word(claims[0])}) — 판매 조건·품질 주장·원산지 표현은 상품명에 넣지 않습니다.")
    rejected = []
    now = time.time()
    with db.tx() as c:
        added, dup = add_names(c, l["source_id"], [name], "manual", now, cfg, rejected)
        if not added:
            if rejected:
                raise ValueError(f"쓸 수 없는 이름입니다: {rejected[0]}")
            raise ValueError("원본 상품명이거나, 다른 상품·스토어에서 쓰는(또는 후보에 있는) 이름입니다." if dup else "이름을 넣어 주세요.")
        nid = c.execute("SELECT id, name FROM names WHERE source_id=? AND norm=?",
                        (l["source_id"], namegen.normalize(namegen.clean(name, 100)))).fetchone()
        if l["name_id"]:
            release_name(c, lid, l["name_id"], ("original", "adopt"))
        # 직접 고친 이름은 AI 키워드가 와도 덮어쓰지 않음 (ctx_wait=0)
        c.execute("UPDATE listings SET name_id=?, name=?, updated_at=?, ctx_wait=0 WHERE id=?", (nid["id"], nid["name"], now, lid))
        c.execute("UPDATE names SET listing_id=? WHERE id=?", (lid, nid["id"]))
    db.recount_sources([l["source_id"]])
    return nid["name"]


def reset_rounds(db, ids):
    """회차 초기화: 지난 회차 기록을 지우고 회차를 1로. 판매 중·내린 건은 다음에 다시 올릴 때(최신화·다시 올리기)
    +1 하지 않고 1회차로 올라가게 표시. 아직 안 올린 건은 바로 1회차. 바꾼 수."""
    n = 0
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        m = ",".join("?" * len(chunk))
        with db.tx() as c:
            c.execute(f"DELETE FROM listing_history WHERE listing_id IN ({m})", chunk)
            c.execute(f"""UPDATE listings SET round=1, round_reset=CASE WHEN origin_no!='' OR status='deleted' THEN 1 ELSE 0 END,
                updated_at=? WHERE id IN ({m})""", (time.time(), *chunk))
            n += c.execute("SELECT changes()").fetchone()[0]
    return n


def schedule_op(db, f, op):
    """올라가 있는 건에 할 일을 건다. op: refresh(최신화: 오래된 상품 지우고 다시, 설정에 따라 새 이름)
    / reupload(다시 올리기: 문제가 있어 지우고 같은 내용으로 다시, 내린 것도) / delete(내리기).
    판매 이력이 있는 건은 건너뛴다. (예약한 수, 판매 이력으로 건너뛴 수, 예약한 복사본 번호들)"""
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
    # 다시 올리기: 내린(내림) 복사본은 다음 회차 새 등록으로 (이름 그대로, 가격은 지금 기준).
    # 직접 고른 것이거나 '내림'으로 거른 때만 (전체 고르기로 내림까지 되살아나지 않게)
    if op == "reupload" and (f.get("ids") or f.get("status") == "deleted"):
        rev = relist(db, f)
        ids += rev
    return len(ids), skipped, ids


def relist(db, f):
    """내린(내림) 복사본을 다시 올릴 대기로 되돌린다: 다음 회차·같은 이름, 가격은 지금 스토어 기준으로 다시. 스토어 남은 자리만큼만."""
    cfg = config.load()
    where, args = listing_where({**f, "status": "deleted"})
    rows = db.q(f"""SELECT l.id, l.store_id, l.price AS cur, l.price_fixed, s.price, COALESCE(NULLIF(s.price_seed,''), s.source_key) AS source_key FROM listings l JOIN sources s ON s.id=l.source_id{where}
        ORDER BY l.id""", args)
    if not rows:
        return []
    stores = {s["id"]: s for s in db.stores()}
    free = {sid: s["free"] for sid, s in stores.items()}
    now, out = time.time(), []
    with db.tx() as c:
        for r in rows:
            st = stores.get(r["store_id"])
            if not st or free.get(r["store_id"], 0) <= 0:
                continue
            free[r["store_id"]] -= 1
            price = r["cur"] if r["price_fixed"] else convert.store_price(r["price"], cfg, st)
            c.execute("""UPDATE listings SET status='planned', op='reupload', round=CASE WHEN round_reset=1 THEN 1 ELSE round+1 END,
                round_reset=0, price=?, message='', stage='',
                sale_shown=NULL, updated_at=? WHERE id=?""", (price, now, r["id"]))
            out.append(r["id"])
    db.recount_sources([r["id"] for r in db.q(f"SELECT DISTINCT source_id AS id FROM listings WHERE id IN ({','.join('?' * len(out))})", out)] if out else [])
    return out


def _movable(r):
    """원본으로 되돌리기·다른 스토어로 보내기가 되는 복사본: 아직 안 올린 것(대기·실패)과 내린 것. 판매 이력·잠금은 뺌."""
    if r["status"] in ("queued", "running") or (r["origin_no"] and r["status"] != "deleted"):
        return "live"
    if r["locked"]:
        return "locked"
    return ""


def revert_listings(db, ids):
    """복사본 → 원본으로 되돌리기: 그 스토어에서 복사본을 없앰 (휴지통에 기록). 원본은 그대로, 복사 자리가 비고
    붙어 있던 상품명은 원본의 안 쓴 후보로 (A를 쓴 것이면 다음 복사에 다시 A)."""
    from . import trash
    st = {"reverted": 0, "live": 0, "locked": 0}
    go = []
    for i in range(0, len(ids), 900):
        ch = ids[i:i + 900]
        for r in db.q(f"SELECT id, status, origin_no, locked FROM listings WHERE id IN ({','.join('?' * len(ch))})", ch):
            why = _movable(r)
            if why:
                st[why] += 1
            else:
                go.append(r["id"])
    if go:
        st["reverted"] = trash.trash_listings(db, go)["moved"]
    return st


def move_listings(db, ids, to_store):
    """복사본을 다른 스토어로 보내기 (지금 스토어에서는 사라짐): 받는 스토어의 남은 자리만큼, 그 스토어에 같은 원본이
    이미 있으면(내린 것 포함) 뺌. 상품명(A·B)은 그대로, 가격은 받는 스토어 템플릿 기준으로 다시, 1회차 새 등록 대기.
    내린 복사본은 받는 스토어에 새로 만들고 원래 것(지난 회차 기록)은 휴지통으로."""
    from . import trash
    cfg = config.load()
    stores = {s["id"]: s for s in db.stores()}
    to = stores.get(int(to_store or 0))
    if not to:
        raise ValueError("보낼 스토어를 골라 주세요.")
    free = max(0, int(to.get("free") or 0))
    st = {"moved": 0, "same": 0, "exists": 0, "full": 0, "live": 0, "locked": 0, "store": to["name"], "free_before": free}
    have = {r["source_id"] for r in db.q("SELECT source_id FROM listings WHERE store_id=?", (to["id"],))}
    rows = []
    for i in range(0, len(ids), 900):
        ch = ids[i:i + 900]
        rows += db.q(f"""SELECT l.id, l.store_id, l.source_id, l.name, l.name_id, l.status, l.origin_no, l.locked, l.registered_at, l.sold_count,
            EXISTS(SELECT 1 FROM listing_history h WHERE h.listing_id=l.id) AS has_hist,
            s.price AS src_price, COALESCE(NULLIF(s.price_seed,''), s.source_key) AS source_key
            FROM listings l JOIN sources s ON s.id=l.source_id WHERE l.id IN ({','.join('?' * len(ch))}) ORDER BY l.id""", ch)
    old_trash, touched = [], set()
    now = time.time()
    with db.tx() as c:
        for r in rows:
            if r["store_id"] == to["id"]:
                st["same"] += 1
                continue
            why = _movable(r)
            if why:
                st[why] += 1
                continue
            if r["source_id"] in have:
                st["exists"] += 1
                continue
            if free <= 0:
                st["full"] += 1
                continue
            price = convert.store_price(r["src_price"], cfg, to)
            if r["status"] == "deleted" or r["registered_at"] or r["sold_count"] or r["has_hist"]:   # 예전 스토어 기록은 그 줄에 남겨 휴지통으로
                new = c.execute("""INSERT INTO listings(store_id, source_id, plan_id, name, price, status, op, round, created_at, updated_at)
                    VALUES(?,?,NULL,?,?,'planned','create',1,?,?)""", (to["id"], r["source_id"], r["name"], price, now, now)).lastrowid
                if r["name_id"]:
                    c.execute("UPDATE listings SET name_id=NULL WHERE id=?", (r["id"],))
                    c.execute("UPDATE listings SET name_id=? WHERE id=?", (r["name_id"], new))
                    c.execute("UPDATE names SET listing_id=? WHERE id=?", (new, r["name_id"]))
                old_trash.append(r["id"])
            else:
                c.execute("""UPDATE listings SET store_id=?, price=?, status='planned', op='create', round=1, round_reset=0, seller_code='',
                    message='', stage='', sale_shown=NULL, price_fixed=0, opt_fixed='', registered_at=NULL, nv_status='', nv_disp='',
                    updated_at=? WHERE id=?""", (to["id"], price, now, r["id"]))
            have.add(r["source_id"])
            touched.add(r["source_id"])
            free -= 1
            st["moved"] += 1
    if old_trash:
        trash.trash_listings(db, old_trash)
    db.recount_sources(touched)
    return st


def cancel_listings(db, where_sql, args):
    """아직 처리 안 된(대기·실패) 할 일을 취소한다.
    새 등록이면 줄을 지우고 이름을 후보로 돌린다 (다시 살린 줄이면 '내림'으로 되돌림).
    최신화·내리기면 할 일만 지우고 '판매 중'으로 되돌린다."""
    rows = db.q(f"SELECT id, source_id, op, round, origin_no, registered_at, locked, manual_lock, sold_count, "
                f"(SELECT COUNT(*) FROM listing_history h WHERE h.listing_id=listings.id) AS hist FROM listings "
                f"WHERE status IN ('planned','fail') AND ({where_sql})", args)
    if not rows:
        return 0
    with db.tx() as c:
        for r in rows:
            if r["origin_no"]:
                c.execute("UPDATE listings SET status='success', op='create', message='' WHERE id=?", (r["id"],))
            elif r["registered_at"] or r["hist"] or r["locked"] or r["manual_lock"] or r["sold_count"]:
                # 예전에 네이버에 올렸던 줄(지운 뒤 실패·내린 것 다시 올리기·회차 초기화 등)이나 잠긴 줄은 절대 지우지 않고 '내림'으로
                c.execute("UPDATE listings SET status='deleted', op='create', round=MAX(1, round-1), message='' WHERE id=?",
                          (r["id"],))
            elif r["round"] > 1:
                c.execute("UPDATE listings SET status='deleted', op='create', round=round-1, message='' WHERE id=?",
                          (r["id"],))
            else:
                c.execute("UPDATE names SET listing_id=NULL WHERE listing_id=?", (r["id"],))  # 바꾼 이름은 후보로 돌아감
                c.execute("DELETE FROM listings WHERE id=?", (r["id"],))
    db.recount_sources({r["source_id"] for r in rows})
    # 내리기 대기를 취소했으면 '원본까지 삭제' 예약도 풀기 (남은 내리기 대기가 없는 원본만) — 나중 내리기 한 번에 원본이 통째로 지워지지 않게
    sids = sorted({r["source_id"] for r in rows if r["op"] == "delete"})
    for i in range(0, len(sids), 900):
        ch = sids[i:i + 900]
        db.x(f"""UPDATE sources SET drop_pending=0 WHERE drop_pending=1 AND id IN ({','.join('?' * len(ch))})
            AND id NOT IN (SELECT source_id FROM listings WHERE op='delete' AND status IN ('planned','queued','running'))""", ch)
    db.x("DELETE FROM plans WHERE id NOT IN (SELECT DISTINCT plan_id FROM listings WHERE plan_id IS NOT NULL)")
    return len(rows)


# ───────────────────────── 원본 일괄 수정

def bulk_edit_sources(db, ids, clear_seller_code=False, stock=None):
    """판매자코드 비우기(나중에 일괄로 채움), 재고수를 상품·옵션 모두 stock개로.
    엑셀 원본을 다시 불러오면 그 파일 값으로 돌아간다."""
    n = 0
    for i in range(0, len(ids), 500):
        chunk = list(ids)[i:i + 500]
        with db.tx() as c:
            for r in c.execute(f"SELECT id, data FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk).fetchall():
                row = unpack(r["data"])
                if clear_seller_code:
                    row["판매자코드"] = ""
                if stock is not None:
                    row["재고수"] = stock
                    o = row.get("옵션상품")
                    if isinstance(o, dict):
                        for key in ("optionCombinations", "optionStandards"):
                            for x in o.get(key) or []:
                                if isinstance(x, dict):
                                    x["stockQuantity"] = stock
                sets, args = ["data=?", "updated_at=?"], [pack(row), time.time()]
                if clear_seller_code:
                    sets.append("seller_code=''")
                c.execute(f"UPDATE sources SET {', '.join(sets)} WHERE id=?", (*args, r["id"]))
                n += 1
    return {"edited": n}


def reprice_net(db):
    """기준 가격을 '판매가 - 할인가'로 다시 계산하고, 아직 안 올린 복사본 가격도 다시 정한다 (한 번만)."""
    cfg = config.load()
    with db.tx() as c:
        for r in c.execute("SELECT id, data FROM sources").fetchall():
            c.execute("UPDATE sources SET price=? WHERE id=?", (convert.net_price(unpack(r["data"])), r["id"]))
        for r in c.execute("""SELECT l.id, l.store_id, s.price, COALESCE(NULLIF(s.price_seed,''), s.source_key) AS source_key, st.tpl_price_pct, st.tpl_jitter_min, st.tpl_jitter_max FROM listings l
                JOIN sources s ON s.id=l.source_id JOIN stores st ON st.id=l.store_id
                WHERE l.origin_no='' AND l.status IN ('planned','fail')""").fetchall():
            c.execute("UPDATE listings SET price=? WHERE id=?",
                      (convert.store_price(r["price"], cfg, dict(r)), r["id"]))


def reprice_pending(db, store_id=None):
    """아직 안 올린(대기·실패) 복사본 가격을 지금 스토어 템플릿 기준으로 다시 정한다. 바꾼 수."""
    cfg = config.load()
    rows = db.q("""SELECT l.id, l.store_id, l.price AS cur, s.price, COALESCE(NULLIF(s.price_seed,''), s.source_key) AS source_key, st.tpl_price_pct, st.tpl_jitter_min, st.tpl_jitter_max
        FROM listings l JOIN sources s ON s.id=l.source_id JOIN stores st ON st.id=l.store_id
        WHERE l.origin_no='' AND l.status IN ('planned','fail') AND l.price_fixed=0""" + (" AND l.store_id=?" if store_id else ""),
                (int(store_id),) if store_id else ())
    n = 0
    with db.tx() as c:
        for r in rows:
            p = convert.store_price(r["price"], cfg, r)
            if p != r["cur"]:
                c.execute("UPDATE listings SET price=? WHERE id=?", (p, r["id"]))
                n += 1
    return n


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
    elif st == "noname":
        w.append("l.name_id IS NULL AND l.status!='deleted' AND l.origin_no=''")
    elif st == "named":   # 올릴 준비: 상품명을 바꿨고 + 검수 완료 + 아직 네이버에 안 올렸고 등록 대기 (실패·처리 중·판매 중·내림 제외)
        w.append("l.name_id IS NOT NULL AND l.origin_no='' AND l.status='planned' AND l.op IN ('create','reupload') AND s.eye_at IS NOT NULL")
    elif st != "all":
        w.append("l.status=?")
        a.append(st)
    if f.get("op"):
        w.append("l.op=?")
        a.append(f["op"])
    nv = f.get("nv") or ""
    if nv == "bad":                 # 최신화하지 않는 네이버 상태 (판매중지·판매금지·스토어에 없음 …)
        w.append(f"l.origin_no!='' AND l.status!='deleted' AND l.nv_status!='' AND l.nv_status NOT IN ({','.join(repr(x) for x in nvstate.REFRESH_OK)})")
    elif nv == "unknown":           # 아직 확인 안 함
        w.append("l.origin_no!='' AND l.status!='deleted' AND l.nv_status=''")
    elif nv:
        w.append("l.origin_no!='' AND l.status!='deleted' AND l.nv_status=?")
        a.append(nv)
    if f.get("eye") == "todo":      # 눈검수 안 한 원본의 복사본
        w.append("s.eye_at IS NULL")
    elif f.get("eye") == "done":
        w.append("s.eye_at IS NOT NULL")
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
        w.append("(l.name LIKE ? OR l.seller_code LIKE ? OR s.seller_code LIKE ? OR l.channel_no=? OR l.origin_no=?)")
        a += [f"%{q}%"] * 3 + [q, q]
    if f.get("ids"):
        ids = [int(i) for i in f["ids"]]
        w.append(f"l.id IN ({','.join('?' * len(ids))})")
        a += ids
    return (" WHERE " + " AND ".join(w)) if w else "", a


def query_listings(db, f, page=0, size=100):
    where, args = listing_where(f)
    base = "FROM listings l JOIN sources s ON s.id=l.source_id JOIN stores t ON t.id=l.store_id"
    total = db.one(f"SELECT COUNT(*) AS n {base}{where}", args)["n"]
    rows = db.q(f"""SELECT l.id, l.name, l.name_id, l.price, l.sale_shown, l.status, l.op, l.round, l.stage, l.message, l.origin_no, l.sold_count,
        l.cancel_count, l.locked, l.lock_note, l.manual_lock,
        l.channel_no, l.seller_code, l.registered_at, l.deleted_at, l.seconds, l.plan_id, l.updated_at,
        s.id AS source_id, s.source_key, s.seller_code AS source_code, s.name AS source_name,
        s.price AS source_price, s.thumb, s.category, s.n_listings AS source_copies, s.eye_at, s.drop_pending, s.adopted, l.price_fixed,
        l.nv_status, l.nv_disp, l.nv_at,
        t.id AS store_id, t.name AS store_name, t.store_url,
        COALESCE(NULLIF(t.code,''), 'S'||printf('%02d', t.id)) AS store_code,
        n.origin AS name_origin, n.id AS name_no, k.words AS ctx_words
        {base} LEFT JOIN names n ON n.id=l.name_id LEFT JOIN ctx_kw k ON k.source_id=l.source_id
        {where} ORDER BY l.id LIMIT ? OFFSET ?""", (*args, size, page * size))
    # 같은 원본의 다른 스토어 복사본 (바로 가기 버튼용)
    sids = sorted({r["source_id"] for r in rows})
    sib = {}
    if sids:
        for c in db.q(f"""SELECT l.id, l.source_id, l.store_id, l.status, t.name AS store_name,
                COALESCE(NULLIF(t.code,''), 'S'||printf('%02d', t.id)) AS store_code
                FROM listings l JOIN stores t ON t.id=l.store_id
                WHERE l.status!='deleted' AND l.source_id IN ({','.join('?' * len(sids))})""", sids):
            sib.setdefault(c["source_id"], []).append(c)
    pv = price_viewer(db)
    lex = lexicon.get(db)
    rep_n = int(config.load().get("max_word_repeat") or 2)
    labels = ai_variants(db, sids) if any(r["name_origin"] == "ctx" for r in rows) else {}
    for r in rows:
        r["ai_label"] = labels.get(r["name_no"]) if r["name_origin"] == "ctx" else None
        # 같은 단어 3번 이상인 이름 (예전에 만든 이름 등) → 목록에 '반복' 표시해 다시 바꾸게
        r["rep_word"] = lexicon.repeated_word(str(r["name"] or "").split(), lex, rep_n) if r["name_id"] else None
        kw = ctxkw.kw_of(r["ctx_words"]) if r["ctx_words"] else {"core": [], "ctx": []}
        r["ctx_words"], r["core_words"] = kw["ctx"], kw["core"]
        r["nd"] = ctxkw.name_parts(r["name"], r["source_name"], kw, r["name_origin"])
        r["others"] = [c for c in sib.get(r["source_id"], []) if c["id"] != r["id"]]
        r.update(pv(r["price"], r["store_id"], bool(r["origin_no"]), r.get("sale_shown")))
    return {"rows": rows, "total": total}


def price_viewer(db):
    """복사본 가격(목표가) → 화면용 {final 손님 가격, shown 네이버 판매가, off 즉시할인, disc_pct}. 스토어 표시 할인율 기준."""
    cfg = config.load()
    unit = max(1, convert.to_int(cfg.get("price_round"), 100))
    pct = {r["id"]: convert.store_discount_pct(r, cfg) for r in db.q("SELECT id, tpl_discount_pct FROM stores")}

    def view(price, store_id, live=False, sale_shown=None):
        p = pct.get(store_id, 0)
        shown, off, final = convert.display_prices(price or 0, p, unit)
        if live and shown != sale_shown:
            s2, o2, f2 = convert.display_prices_exact(price or 0, p, unit)
            if s2 == sale_shown:   # 할인율을 정확히 맞추던 예전 계산으로 올라간 상품 (손님 가격이 조금 높음 — 다음 최신화 때 맞춰짐)
                return {"final": f2, "shown": s2, "off": o2, "disc_pct": p}
            # 이미 올라간 상품인데 지금 기준과 판매가가 다르면(예전 규칙으로 올림 등) 계산값을 보이지 않는다
            return {"final": price, "shown": sale_shown or 0, "off": 0, "disc_pct": 0, "old_rule": True}
        return {"final": final, "shown": shown, "off": off, "disc_pct": p}
    return view


def store_summaries(db):
    """복사본 첫 화면: 스토어마다 복사본 수·이름 변경 필요·대기·판매 중·실패."""
    rows = {r["store_id"]: r for r in db.q("""SELECT store_id, COUNT(*) AS all_,
        SUM(name_id IS NULL AND status!='deleted' AND origin_no='') AS noname,
        SUM(name_id IS NOT NULL AND origin_no='' AND status='planned' AND op IN ('create','reupload') AND source_id IN (SELECT id FROM sources WHERE eye_at IS NOT NULL)) AS named,
        SUM(status IN ('planned','queued','running')) AS pending,
        SUM(status IN ('planned','queued','running') AND op='create') AS p_create,
        SUM(status IN ('planned','queued','running') AND op='refresh') AS p_refresh,
        SUM(status IN ('planned','queued','running') AND op='reupload') AS p_reupload,
        SUM(status IN ('planned','queued','running') AND op='delete') AS p_delete,
        SUM(origin_no!='' AND status='success') AS live, SUM(status='fail') AS fail,
        MAX(updated_at) AS last_at
        FROM listings WHERE status!='deleted' GROUP BY store_id""")}
    out = []
    for s in db.stores():
        r = rows.get(s["id"], {})
        out.append({"id": s["id"], "name": s["name"], "code": s["code"], "enabled": s["enabled"], "capacity": s["capacity"],
                    "business_name": s.get("business_name"), "store_url": s.get("store_url") or "", "ship_region": s.get("ship_region") or "",
                    "used": s["used"], "last_at": r.get("last_at"),
                    "free": s["free"], **{k: r.get(k) or 0 for k in ("all_", "noname", "named", "pending", "p_create", "p_refresh", "p_reupload", "p_delete", "live", "fail")}})
    return out


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
    out = db.one(f"""SELECT COUNT(*) AS all_,
        SUM(status IN ('planned','queued','running')) AS pending,
        SUM(status IN ('planned','queued','running') AND op='create') AS pending_create,
        SUM(status IN ('planned','queued','running') AND op='refresh') AS pending_refresh,
        SUM(status IN ('planned','queued','running') AND op='reupload') AS pending_reupload,
        SUM(status IN ('planned','queued','running') AND op='delete') AS pending_delete,
        SUM(origin_no!='' AND status='success') AS live, SUM(status='fail') AS fail, SUM(status='deleted') AS deleted,
        SUM(sold_count>0) AS sold, SUM(locked=1 AND status!='deleted') AS locked,
        SUM(name_id IS NULL AND status!='deleted' AND origin_no='') AS noname,
        SUM(name_id IS NOT NULL AND origin_no='' AND status='planned' AND op IN ('create','reupload') AND source_id IN (SELECT id FROM sources WHERE eye_at IS NOT NULL)) AS named,
        SUM(origin_no!='' AND registered_at<=?) AS age30, SUM(origin_no!='' AND registered_at<=?) AS age60,
        SUM(origin_no!='' AND registered_at<=?) AS age90
        FROM listings{where}""", (now - 30 * day, now - 60 * day, now - 90 * day, *a))
    # 눈검수: 원본 기준 (내린 것은 빼고)
    e = db.one(f"""SELECT SUM(s.eye_at IS NOT NULL) AS eye_done, SUM(s.eye_at IS NULL) AS eye_todo
        FROM listings l JOIN sources s ON s.id=l.source_id WHERE l.status!='deleted'{''.join(' AND l.' + x for x in w)}""", a)
    # 네이버 상태 (판매 중 복사본): 최신화하지 않는 상태 수
    nvw = ''.join(' AND ' + x for x in w)
    ok = ",".join(repr(x) for x in nvstate.REFRESH_OK)
    nvc = db.one(f"""SELECT SUM(nv_status!='' AND nv_status NOT IN ({ok})) AS nv_bad, SUM(nv_status='') AS nv_unknown,
        SUM(nv_status='GONE') AS nv_gone
        FROM listings WHERE origin_no!='' AND status!='deleted'{nvw}""", a)
    need = db.one(f"""SELECT COUNT(*) AS n FROM listings l JOIN stores t ON t.id=l.store_id
        WHERE l.origin_no!='' AND l.status!='deleted'
        AND (t.orders_from IS NULL OR t.orders_synced_to IS NULL OR l.registered_at < t.orders_from - 3600){''.join(' AND l.' + x for x in w)}""", a)
    out = {**out, "need_sales": need["n"] or 0}
    return {**out, "eye_done": e["eye_done"] or 0, "eye_todo": e["eye_todo"] or 0,
            "nv_bad": nvc["nv_bad"] or 0, "nv_unknown": nvc["nv_unknown"] or 0, "nv_gone": nvc["nv_gone"] or 0}
