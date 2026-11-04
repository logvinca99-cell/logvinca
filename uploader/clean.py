"""상세 정리: 셀업 엑셀을 원본 상품으로 넣기 전에 정리하는 곳 (진시크릿 상세정리 도구를 이 프로그램 안으로).

흐름: 엑셀 올리기 → 정리함(묶음) → ② 공통 이미지 ③ 전화번호 ④ 상세 편집 ⑤ 잘린·빈 상세 ⑥ 빈 칸 ⑦ 카테고리·생활화학
      → ⑧ 원본 상품으로 넣기(또는 셀업 양식 엑셀로 저장).
올릴 때 자동: 가격은 고객 결제가 한 칸(판매가 − 할인가, 할인가 비움), 상품코드 비움, 브랜드·제조사·모델명·원산지 '상세페이지 참조',
'다음에도 빼기'로 기억한 공통 이미지 빼기.
"""

import io
import json
import os
import re
import time

from . import config, convert, excel, srctags
from .db import pack, unpack

REFER = "상세페이지 참조"
INFO_COLS = ("브랜드", "제조사", "모델명", "원산지")
CODE_COLS = ("판매자코드", "상품코드")
EXCEL_CELL_MAX = 32767

SCHEMA = """
CREATE TABLE IF NOT EXISTS clean_batch (
    id INTEGER PRIMARY KEY,
    created_at REAL NOT NULL,
    file_name TEXT NOT NULL DEFAULT '',
    columns TEXT NOT NULL DEFAULT '[]',     -- 올린 엑셀의 열 순서 (엑셀로 저장할 때 그대로)
    total INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',          -- 원본으로 넣을 때 붙일 출처 태그 '|a|b|' (어디서·언제)
    store_tag INTEGER NOT NULL DEFAULT 1    -- 1이면 수집URL의 스토어도 태그로
);
CREATE TABLE IF NOT EXISTS clean_item (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,         -- 엑셀 행 번호 (제목 1행, 첫 상품 2행)
    name TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL DEFAULT 0,
    thumb TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    row BLOB,
    orig_detail BLOB,                       -- 처음 상세 (처음 고칠 때 남김 → '처음 상세로 되돌리기')
    status TEXT NOT NULL DEFAULT 'new',     -- new(정리 중) / hold(생활화학 보류) / deleted / sent(원본으로 넣음)
    chem TEXT NOT NULL DEFAULT '',          -- 생활화학 판정: tool / chemical / unclear
    chem_reason TEXT NOT NULL DEFAULT '',
    edited INTEGER NOT NULL DEFAULT 0,
    source_id INTEGER,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_clean_item ON clean_item(batch_id, status, ord);
CREATE TABLE IF NOT EXISTS clean_rule (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'image',     -- image: 다음에 올리는 엑셀에서도 이 이미지를 뺌
    value TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0
);
"""


NEW_COLUMNS = {"clean_batch": [("tags", "TEXT NOT NULL DEFAULT ''"), ("store_tag", "INTEGER NOT NULL DEFAULT 1")]}


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)
        for t, cols in NEW_COLUMNS.items():
            have = {r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()}
            for name, decl in cols:
                if name not in have:
                    c.execute(f"ALTER TABLE {t} ADD COLUMN {name} {decl}")


# ───────────────────────── 이미지·글자 다루기

_IMG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r"""\bsrc\s*=\s*(["'])(.*?)\1""", re.I | re.S)


def img_srcs(html):
    out = []
    for t in _IMG.findall(str(html or "")):
        m = _SRC.search(t)
        if m and m.group(2).strip():
            out.append(m.group(2).strip())
    return out


def remove_images(html, srcs):
    """상세에서 이 주소의 이미지를 뺀다 (이미지 하나만 감싸던 빈 칸도 같이). (새 HTML, 뺀 수)"""
    html, n = str(html or ""), 0
    for src in srcs:
        e = re.escape(src)
        img = rf"""<img\b[^>]*\bsrc\s*=\s*["']{e}["'][^>]*>"""
        pad = r"(?:\s|<br\s*/?>|&nbsp;)*"
        html, k1 = re.subn(rf"<(div|p|a|span|center)\b[^>]*>{pad}{img}{pad}</\1>", "", html, flags=re.I)
        html, k2 = re.subn(img, "", html, flags=re.I)
        n += k1 + k2
    return html, n


def _texts(html):
    """HTML을 태그와 글자로 나눔 (글자만 고치려고)."""
    return re.split(r"(<[^>]+>)", str(html or ""))


def text_of(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html or "")).replace("&nbsp;", " ")).strip()


SEP = r"(?:[-.\s]|&nbsp;)"
PHONE_RED = re.compile(rf"(?<!\d)01[016789]{SEP}?\d{{3,4}}{SEP}?\d{{4}}(?!\d)")
PHONE_YELLOW = re.compile(rf"(?<!\d)(?:0\d{{1,2}}{SEP}\d{{3,4}}{SEP}\d{{4}}|1[5-9]\d{{2}}{SEP}\d{{4}}|\d{{3}}{SEP}\d{{4}}{SEP}\d{{4}}|\d{{4}}{SEP}\d{{4}})(?!\d)")


def find_phones_in(text):
    """[(번호, 'red'|'yellow')]: red = 010형(휴대폰), yellow = 의심(일반전화·0000-0000 등, 치수·날짜일 수 있음)."""
    out, seen = [], set()
    for m in PHONE_RED.finditer(text):
        out.append((m.group(0), "red"))
        seen.add(m.span())
    for m in PHONE_YELLOW.finditer(text):
        if not any(a <= m.start() < b for a, b in seen):
            out.append((m.group(0), "yellow"))
    return out


def option_names(row):
    o = row.get("옵션상품") if isinstance(row.get("옵션상품"), dict) else {}
    for c in o.get("optionCombinations") or []:
        if isinstance(c, dict):
            for k in ("optionName1", "optionName2", "optionName3"):
                if c.get(k):
                    yield c, k
    for key in ("optionSimple", "optionCustom", "optionStandards"):
        for c in o.get(key) or []:
            if isinstance(c, dict):
                for k in ("groupName", "name", "optionName1", "optionName2"):
                    if c.get(k):
                        yield c, k


# ───────────────────────── 엑셀 → 정리함

def rules(db):
    return db.q("SELECT * FROM clean_rule ORDER BY id DESC")


def auto_fix(row, opts, rule_srcs):
    """올릴 때 자동으로 하는 정리. (고친 줄, 메모)"""
    row = dict(row)
    notes = {}
    if opts.get("price", True):   # 고객 결제가 한 칸 (표시 할인율은 스토어 템플릿에서)
        net = convert.net_price(row)
        if net and convert.to_int(row.get("할인가")):
            notes["price"] = 1
        if net:
            row["판매가"] = net
        row["할인가"] = None
    if opts.get("code", True):
        for c in CODE_COLS:
            if row.get(c) not in (None, ""):
                notes["code"] = 1
            row[c] = None
    if opts.get("info", True):
        for c in INFO_COLS:
            row[c] = REFER
    if rule_srcs:
        html, n = remove_images(row.get("상세설명"), rule_srcs)
        if n:
            row["상세설명"] = html
            notes["rule_imgs"] = n
    return row, notes


def import_excel(db, path, filename, opts=None, progress=None, should_stop=None):
    """셀업 엑셀 → 정리함 새 묶음. 원본 상품에는 아직 안 들어감."""
    opts = opts or {}
    total_hint = excel.count_rows(path, filename)
    rule_srcs = [r["value"] for r in rules(db) if r["kind"] == "image"]
    now = time.time()
    bid = db.x("INSERT INTO clean_batch(created_at, file_name, tags, store_tag) VALUES(?,?,?,?)",
               (now, filename, srctags.join(srctags.parse(opts.get("tags"))), int(opts.get("store_tag", True))))
    cols, n = [], 0
    st = {"total": 0, "price": 0, "code": 0, "rule_imgs": 0, "skipped_empty": 0}
    batch = []

    def flush():
        with db.tx() as c:
            for ord_, row in batch:
                c.execute("""INSERT INTO clean_item(batch_id, ord, name, price, thumb, category, row, updated_at)
                    VALUES(?,?,?,?,?,?,?,?)""", (bid, ord_, str(row.get("상품명") or ""), convert.to_int(row.get("판매가")),
                                                (convert.thumbnails(row) or [""])[0], str(row.get("카테고리") or ""), pack(row), now))
        batch.clear()

    for i, row in enumerate(excel.iter_rows(path, filename), 2):
        if should_stop and should_stop():
            break
        for k in row:
            if k not in cols:
                cols.append(k)
        if not any(v not in (None, "") for v in row.values()):
            st["skipped_empty"] += 1
            continue
        fixed, notes = auto_fix(row, opts, rule_srcs)
        for k in ("price", "code"):
            st[k] += notes.get(k, 0)
        st["rule_imgs"] += notes.get("rule_imgs", 0)
        batch.append((i, fixed))
        st["total"] += 1
        n += 1
        if len(batch) >= 300:
            flush()
            if progress:
                progress(n, total_hint, f"{n:,}개 읽음")
    if batch:
        flush()
    if st["rule_imgs"] and rule_srcs:
        db.x("UPDATE clean_rule SET hits=hits+1")
    note = f"가격 한 칸으로 {st['price']:,} · 상품코드 비움 {st['code']:,}" + (f" · 기억한 공통 이미지 뺌 {st['rule_imgs']:,}장" if st["rule_imgs"] else "")
    db.x("UPDATE clean_batch SET columns=?, total=?, note=? WHERE id=?", (json.dumps(cols, ensure_ascii=False), st["total"], note, bid))
    return {**st, "batch_id": bid, "file": filename}


def set_batch_tags(db, bid, tags, store_tag):
    """정리함 묶음의 출처 태그 바꾸기 (아직 원본으로 안 넣은 상품에 적용 — 넣은 것은 원본 상품 화면에서)."""
    db.x("UPDATE clean_batch SET tags=?, store_tag=? WHERE id=?", (srctags.join(srctags.parse(tags)), int(bool(store_tag)), bid))
    return batch_tags(db, bid)


def batch_tags(db, bid):
    """묶음의 출처 태그와 수집URL로 붙을 스토어 (많은 순)."""
    from collections import Counter
    b = db.one("SELECT tags, store_tag FROM clean_batch WHERE id=?", (bid,)) or {}
    stores = Counter()
    for r in db.q("SELECT row FROM clean_item WHERE batch_id=? AND status IN ('new','hold')", (bid,)):
        stores[srctags.store_of(unpack(r["row"])) or ""] += 1
    return {"tags": srctags.split(b.get("tags")), "store_tag": bool(b.get("store_tag", 1)),
            "stores": [{"store": s, "count": n} for s, n in stores.most_common()]}


# ───────────────────────── 정리함 보기

def batches(db, limit=50):
    out = []
    for b in db.q("SELECT * FROM clean_batch ORDER BY id DESC LIMIT ?", (limit,)):
        c = db.one("""SELECT SUM(status='new') AS new, SUM(status='hold') AS hold, SUM(status='deleted') AS deleted,
            SUM(status='sent') AS sent FROM clean_item WHERE batch_id=?""", (b["id"],))
        out.append({**b, **{k: c[k] or 0 for k in ("new", "hold", "deleted", "sent")}})
    return out


def counts(db, bid):
    c = db.one("""SELECT COUNT(*) AS total, SUM(status='new') AS new, SUM(status='hold') AS hold, SUM(status='deleted') AS deleted,
        SUM(status='sent') AS sent, SUM(edited=1) AS edited FROM clean_item WHERE batch_id=?""", (bid,))
    return {k: c[k] or 0 for k in ("total", "new", "hold", "deleted", "sent", "edited")}


ITEM_COLS = "id, batch_id, ord, name, price, thumb, category, status, chem, chem_reason, edited, source_id"


def items(db, bid, status="", q="", page=1, size=100):
    w, a = ["batch_id=?"], [bid]
    if status in ("new", "hold", "deleted", "sent"):
        w.append("status=?")
        a.append(status)
    else:
        w.append("status!='deleted'")
    if q:
        if q.isdigit():
            w.append("(ord=? OR name LIKE ?)")
            a += [int(q), f"%{q}%"]
        else:
            w.append("(name LIKE ? OR category LIKE ?)")
            a += [f"%{q}%"] * 2
    where = " WHERE " + " AND ".join(w)
    total = db.one(f"SELECT COUNT(*) AS n FROM clean_item{where}", a)["n"]
    rows = db.q(f"SELECT {ITEM_COLS} FROM clean_item{where} ORDER BY ord LIMIT ? OFFSET ?", (*a, size, (page - 1) * size))
    return {"rows": rows, "total": total}


def item(db, iid=None, bid=None, ord_=None):
    r = (db.one(f"SELECT {ITEM_COLS}, row, orig_detail FROM clean_item WHERE id=?", (iid,)) if iid else
         db.one(f"SELECT {ITEM_COLS}, row, orig_detail FROM clean_item WHERE batch_id=? AND ord=?", (bid, ord_)))
    if not r:
        return None
    r["row"] = unpack(r["row"])
    r["has_orig"] = r.pop("orig_detail") is not None
    nb = lambda op, o: db.one(f"SELECT ord FROM clean_item WHERE batch_id=? AND status!='deleted' AND ord{op}? ORDER BY ord {o} LIMIT 1",  # noqa: E731
                              (r["batch_id"], r["ord"]))
    r["prev"], r["next"] = (nb("<", "DESC") or {}).get("ord"), (nb(">", "") or {}).get("ord")
    return r


def _rows(db, bid, statuses=("new", "hold")):
    m = ",".join("?" * len(statuses))
    for r in db.q(f"SELECT id, ord, name, row, orig_detail FROM clean_item WHERE batch_id=? AND status IN ({m}) ORDER BY ord",
                  (bid, *statuses)):
        yield r


def _save_rows(db, changed, now=None):
    """changed: [(id, 고친 줄, 처음 상세가 없던 것이면 처음 상세)]"""
    now = now or time.time()
    with db.tx() as c:
        for iid, row, orig in changed:
            c.execute("""UPDATE clean_item SET row=?, name=?, price=?, thumb=?, category=?, edited=1, updated_at=?,
                orig_detail=COALESCE(orig_detail, ?) WHERE id=?""",
                      (pack(row), str(row.get("상품명") or ""), convert.to_int(row.get("판매가")), (convert.thumbnails(row) or [""])[0],
                       str(row.get("카테고리") or ""), now, pack(orig) if orig is not None else None, iid))


def save_detail(db, iid, html):
    """④ 상세 편집 저장 (미리보기에서 고친 것). 스크립트·이벤트 속성은 뺀다."""
    r = db.one("SELECT row FROM clean_item WHERE id=?", (iid,))
    if not r:
        raise ValueError("정리함에 없는 상품입니다.")
    row = unpack(r["row"])
    html = re.sub(r"<script\b.*?</script>", "", str(html or ""), flags=re.I | re.S)
    html = re.sub(r"""\son[a-z]+\s*=\s*(["']).*?\1""", "", html, flags=re.I | re.S)
    old = row.get("상세설명") or ""
    _save_rows(db, [(iid, {**row, "상세설명": html}, old)])
    return {"length": len(html), "images": len(img_srcs(html))}


def revert_detail(db, iid):
    r = db.one("SELECT row, orig_detail FROM clean_item WHERE id=?", (iid,))
    if not r or r["orig_detail"] is None:
        return False
    row = unpack(r["row"])
    row["상세설명"] = unpack(r["orig_detail"])
    with db.tx() as c:
        c.execute("UPDATE clean_item SET row=?, orig_detail=NULL, edited=0, updated_at=? WHERE id=?", (pack(row), time.time(), iid))
    return True


def delete_items(db, ids):
    n = 0
    with db.tx() as c:
        for i in range(0, len(ids), 900):
            chunk = [int(x) for x in ids[i:i + 900]]
            n += c.execute(f"UPDATE clean_item SET status='deleted' WHERE status IN ('new','hold') AND id IN ({','.join('?' * len(chunk))})",
                           chunk).rowcount
    return n


def restore_items(db, ids):
    n = 0
    with db.tx() as c:
        for i in range(0, len(ids), 900):
            chunk = [int(x) for x in ids[i:i + 900]]
            n += c.execute(f"""UPDATE clean_item SET status=CASE WHEN chem IN ('chemical','unclear') THEN 'hold' ELSE 'new' END
                WHERE status='deleted' AND id IN ({','.join('?' * len(chunk))})""", chunk).rowcount
    return n


# ───────────────────────── ② 공통 이미지

def common_images(db, bid, min_count=10, limit=120):
    counts, sample = {}, {}
    total = 0
    for r in _rows(db, bid):
        total += 1
        for s in set(img_srcs(unpack(r["row"]).get("상세설명"))):
            counts[s] = counts.get(s, 0) + 1
            sample.setdefault(s, []).append(r["ord"])
    known = {r["value"] for r in rules(db)}
    out = [{"src": s, "count": n, "rows": sample[s][:5], "remembered": s in known}
           for s, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= max(2, int(min_count or 2))]
    return {"total": total, "images": out[:limit], "more": max(0, len(out) - limit)}


def remove_common(db, bid, srcs, remember=False):
    srcs = [s for s in dict.fromkeys(str(x).strip() for x in srcs) if s]
    if not srcs:
        raise ValueError("지울 이미지를 골라 주세요.")
    changed, n_img = [], 0
    for r in _rows(db, bid):
        row = unpack(r["row"])
        old = row.get("상세설명") or ""
        html, n = remove_images(old, srcs)
        if n:
            n_img += n
            changed.append((r["id"], {**row, "상세설명": html}, old))
    _save_rows(db, changed)
    if remember:
        with db.tx() as c:
            for s in srcs:
                c.execute("INSERT OR IGNORE INTO clean_rule(kind, value, created_at) VALUES('image', ?, ?)", (s, time.time()))
    return {"items": len(changed), "images": n_img, "remembered": len(srcs) if remember else 0}


def delete_rules(db, ids):
    with db.tx() as c:
        return c.execute(f"DELETE FROM clean_rule WHERE id IN ({','.join('?' * len(ids))})", [int(i) for i in ids]).rowcount if ids else 0


# ───────────────────────── ③ 전화번호

def find_phones(db, bid):
    out = []
    for r in _rows(db, bid):
        row = unpack(r["row"])
        hits = []
        parts = _texts(row.get("상세설명"))
        for k, p in enumerate(parts):
            if k % 2 == 0 and p:
                hits += [{"text": t, "kind": kind, "where": "상세"} for t, kind in find_phones_in(p)]
        for c, key in option_names(row):
            hits += [{"text": t, "kind": kind, "where": "옵션"} for t, kind in find_phones_in(str(c[key]))]
        hits += [{"text": t, "kind": kind, "where": "상품명"} for t, kind in find_phones_in(str(row.get("상품명") or ""))]
        if hits:
            out.append({"id": r["id"], "ord": r["ord"], "name": r["name"], "hits": hits})
    return out


def remove_phones(db, picks):
    """picks: [{id, text}] → 상세 글자·옵션명·상품명에서 그 번호를 지움 (이미지 주소 속 숫자는 건드리지 않음)."""
    by = {}
    for p in picks or []:
        if p.get("id") and p.get("text"):
            by.setdefault(int(p["id"]), set()).add(str(p["text"]))
    changed, n = [], 0
    for iid, texts in by.items():
        r = db.one("SELECT row FROM clean_item WHERE id=?", (iid,))
        if not r:
            continue
        row = unpack(r["row"])
        old = row.get("상세설명") or ""
        parts = _texts(old)
        for k in range(0, len(parts), 2):
            for t in texts:
                if t in parts[k]:
                    n += parts[k].count(t)
                    parts[k] = parts[k].replace(t, "")
        row["상세설명"] = "".join(parts)
        for c, key in option_names(row):
            v = str(c[key])
            for t in texts:
                if t in v:
                    n += 1
                    v = re.sub(r"\s{2,}", " ", v.replace(t, "")).strip()
            c[key] = v
        name = str(row.get("상품명") or "")
        for t in texts:
            if t in name:
                n += 1
                name = re.sub(r"\s{2,}", " ", name.replace(t, "")).strip()
        row["상품명"] = name
        changed.append((iid, row, old))
    _save_rows(db, changed)
    return {"items": len(changed), "removed": n}


# ───────────────────────── ⑤ 잘린·빈 상세 · ⑥ 빈 칸

def broken_details(db, bid):
    cut, empty = [], []
    for r in _rows(db, bid):
        html = str(unpack(r["row"]).get("상세설명") or "")
        tail = html.rstrip()
        if len(html) >= EXCEL_CELL_MAX - 64 or (tail and tail.rfind("<") > tail.rfind(">")):
            cut.append({"id": r["id"], "ord": r["ord"], "name": r["name"], "length": len(html)})
        elif not img_srcs(html) and not text_of(html):
            empty.append({"id": r["id"], "ord": r["ord"], "name": r["name"], "length": len(html)})
    return {"cut": cut, "empty": empty}


MISSING_COLS = ("상품명", "판매가", "상세설명", "썸네일", "카테고리")


def missing_fields(db, bid, cols=None):
    cols = [c for c in (cols or ("상품명", "판매가", "상세설명")) if c in MISSING_COLS]
    out = []
    for r in _rows(db, bid):
        row = unpack(r["row"])
        miss = []
        for c in cols:
            v = row.get(c)
            if c == "판매가":
                bad = convert.to_int(v) <= 0
            elif c == "상세설명":
                bad = not img_srcs(v) and not text_of(v)
            elif c == "썸네일":
                bad = not convert.thumbnails(row)
            else:
                bad = v in (None, "") or not str(v).strip()
            if bad:
                miss.append(c)
        if miss:
            out.append({"id": r["id"], "ord": r["ord"], "name": r["name"], "missing": miss})
    return out


# ───────────────────────── ⑦ 카테고리·생활화학

def categories(db, bid):
    from . import chem, naver
    cats = naver.cached_categories() or {}
    cfg = config.load()
    groups = {}
    for r in db.q("SELECT id, category, status, chem FROM clean_item WHERE batch_id=? AND status IN ('new','hold')", (bid,)):
        g = groups.setdefault(r["category"], {"category": r["category"], "count": 0, "hold": 0})
        g["count"] += 1
        g["hold"] += r["status"] == "hold"
    norm_leaves = {convert.cat_norm(n) for n in cats}
    out = []
    for cat, g in groups.items():
        cid, how = convert.find_category(cat, cats, cfg)
        if not cats:
            status = "unknown"
        elif not str(cat).strip():
            status = "empty"
        elif cid:
            status = "ok" if not how else "mapped"
        elif ">" not in str(cat) and not str(cat).isdigit():
            status = "format"
        elif any(x.startswith(convert.cat_norm(cat) + ">") for x in norm_leaves):
            status = "mid"
        else:
            status = "missing"
        name = next((n for n, i in cats.items() if i == cid), "") if cid else ""
        out.append({**g, "status": status, "naver": name, "cat_id": cid, "chem": chem.is_chemical(cid) if cid else None,
                    "suggest": [] if cid else convert.category_suggestions(cat, cats, 5)})
    order = {"empty": 0, "format": 1, "missing": 2, "mid": 3, "mapped": 4, "unknown": 5, "ok": 6}
    out.sort(key=lambda g: (order.get(g["status"], 9), -(g["chem"] or 0), -g["count"]))
    return {"groups": out, "have_categories": bool(cats)}


def set_category(db, bid, to, from_cat=None, ids=None):
    """카테고리 바꾸기: 그 카테고리(from_cat)의 상품 전부 또는 고른 상품(ids). 바꾼 상품은 생활화학 판정을 지움(다시 판정)."""
    from . import naver
    to = str(to or "").strip()
    if not to or to not in (naver.cached_categories() or {}):
        raise ValueError("네이버 카테고리 목록에서 골라 주세요.")
    if ids:
        rows = db.q(f"SELECT id, row FROM clean_item WHERE id IN ({','.join('?' * len(ids))}) AND status IN ('new','hold')",
                    [int(i) for i in ids])
    else:
        rows = db.q("SELECT id, row FROM clean_item WHERE batch_id=? AND category=? AND status IN ('new','hold')", (bid, from_cat or ""))
    changed = [(r["id"], {**unpack(r["row"]), "카테고리": to}, None) for r in rows]
    _save_rows(db, changed)
    with db.tx() as c:
        for iid, _, _ in changed:
            c.execute("UPDATE clean_item SET chem='', chem_reason='', status=CASE WHEN status='hold' THEN 'new' ELSE status END WHERE id=?", (iid,))
    return len(changed)


def judge_chem(db, bid, progress=None, should_stop=None):
    """⑦ 생활화학: 상품 카테고리가 인증 대상인지 네이버에서 확인하고, 대상이면 물건·화학제품을 판정(애매하면 AI).
    화학제품·애매는 '생활화학 보류'(원본으로 넣지 않음)."""
    from . import chem, naver
    cfg = config.load()
    cats = naver.cached_categories() or {}
    rows = db.q("SELECT id, name, row FROM clean_item WHERE batch_id=? AND status IN ('new','hold')", (bid,))
    cid_of = {}
    for r in rows:
        cid_of[r["id"]] = convert.find_category(unpack(r["row"]).get("카테고리"), cats, cfg)[0]
    checked, err = chem.check_categories(db, [c for c in cid_of.values() if c], progress, should_stop)
    target = [r for r in rows if chem.is_chemical(cid_of.get(r["id"]))]
    if progress:
        progress(0, len(target), f"물건·화학제품 판정 중 {len(target):,}개 (애매한 것은 AI)")
    items_ = []
    for r in target:
        row = unpack(r["row"])
        items_.append({"id": r["id"], "name": r["name"], "category": row.get("카테고리") or "", "options": chem.option_text(row)})
    res = chem.classify(cfg, items_)
    st = {"checked_categories": checked, "target": len(target), "tool": 0, "chemical": 0, "unclear": 0, "error": err}
    with db.tx() as c:
        for it in items_:
            kind, why = res.get(str(it["id"]), ("unclear", ""))
            st[kind] += 1
            c.execute("UPDATE clean_item SET chem=?, chem_reason=?, status=? WHERE id=?",
                      (kind, why[:200], "new" if kind == "tool" else "hold", it["id"]))
        # 대상이 아닌 카테고리는 판정을 지움 (카테고리를 바꿨을 때)
        judged = {x["id"] for x in items_}
        for r in rows:
            if r["id"] not in judged and chem.is_chemical(cid_of.get(r["id"])) is False:
                c.execute("UPDATE clean_item SET chem='', chem_reason='', status=CASE WHEN status='hold' THEN 'new' ELSE status END WHERE id=?",
                          (r["id"],))
    return st


def set_chem(db, ids, kind):
    """보류 목록에서 사람이 판정을 바꿈: tool → 정리 중으로(올릴 때 '인증 대상 아님'), chemical·unclear → 보류."""
    if kind not in ("tool", "chemical", "unclear"):
        raise ValueError("판정 값이 올바르지 않습니다.")
    with db.tx() as c:
        return c.execute(f"""UPDATE clean_item SET chem=?, chem_reason='직접 정함', status=? WHERE status IN ('new','hold')
            AND id IN ({','.join('?' * len(ids))})""", (kind, "new" if kind == "tool" else "hold", *[int(i) for i in ids])).rowcount


def hold_list(db, bid):
    return db.q(f"SELECT {ITEM_COLS} FROM clean_item WHERE batch_id=? AND status='hold' ORDER BY ord", (bid,))


# ───────────────────────── ⑧ 원본으로 넣기·엑셀 저장

def to_sources(db, bid, ids=None, progress=None, should_stop=None):
    """정리 중(new)인 상품을 원본 상품으로 (보류·지운 것은 빼고). 대표 썸네일이 같은 원본이 있으면 갱신 (엑셀 불러오기와 같음).
    생활화학 판정 '물건'은 원본에도 남겨 올릴 때 '인증 대상 아님'으로."""
    from . import inventory
    if ids:
        rows = db.q(f"SELECT id, row, chem FROM clean_item WHERE status='new' AND id IN ({','.join('?' * len(ids))}) ORDER BY ord",
                    [int(i) for i in ids])
    else:
        rows = db.q("SELECT id, row, chem FROM clean_item WHERE batch_id=? AND status='new' ORDER BY ord", (bid,))
    if not rows:
        raise ValueError("원본으로 넣을 상품이 없습니다 (정리 중인 상품만 넣습니다 — 생활화학 보류는 빼고).")
    b = db.one("SELECT file_name, tags, store_tag FROM clean_batch WHERE id=?", (bid,)) or {}
    chem_of = {r["id"]: r["chem"] for r in rows}
    st = inventory.import_rows(db, ((r["id"], unpack(r["row"])) for r in rows), f"상세 정리 · {b.get('file_name') or ''}",
                               total_hint=len(rows), progress=progress, should_stop=should_stop,
                               src_tags=srctags.split(b.get("tags")), store_tag=bool(b.get("store_tag")))
    now = time.time()
    tools = 0
    with db.tx() as c:
        for iid, sid in st.pop("refs").items():
            c.execute("UPDATE clean_item SET status='sent', source_id=?, updated_at=? WHERE id=?", (sid, now, iid))
            if chem_of.get(iid) == "tool":
                tools += 1
                c.execute("UPDATE sources SET chem_judge='tool', chem_reason='상세 정리에서 판정' WHERE id=?", (sid,))
    st["chem_tool"] = tools
    return st


def export_xlsx(db, bid, statuses=("new", "hold")):
    """정리한 엑셀 (올린 엑셀과 같은 열 순서, 목록 칸은 셀업처럼 ['…'] 글자). → (바이트, 파일 이름)"""
    import openpyxl
    b = db.one("SELECT * FROM clean_batch WHERE id=?", (bid,))
    if not b:
        raise ValueError("정리함 묶음이 없습니다.")
    cols = json.loads(b["columns"] or "[]")
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Sheet")
    ws.append(cols)
    for r in _rows(db, bid, statuses):
        row = unpack(r["row"])
        out = []
        for c in cols:
            v = row.get(c)
            if isinstance(v, (list, dict)):
                v = str(v)
            out.append("" if v is None else v)
        ws.append(out)
    buf = io.BytesIO()
    wb.save(buf)
    stem = os.path.splitext(b["file_name"] or "정리")[0]
    return buf.getvalue(), f"{stem}_수정.xlsx"
