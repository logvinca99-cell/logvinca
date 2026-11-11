"""원본 상세·옵션 직접 고치기 (원본 상세 창).

원본 엑셀을 다시 올려도 원본을 덮어쓰지 않으므로, 상세페이지(HTML)와 옵션은 여기서만 고친다.
- 상품명은 원본 기준(상품명이 완전히 같으면 같은 원본)이라 여기서 바꾸지 않는다.
- 기준 가격은 [기준 가격 수정]으로 (baseprice.py).
- 고친 내용은 아직 안 올린 복사본은 올릴 때, 판매 중 복사본은 다음 최신화·다시 올리기 때 반영된다 (네이버에 바로 보내지 않음).
- 고치기 전 내용을 source_edit_log에 남겨 [마지막 수정 되돌리기]로 돌릴 수 있다.
"""
import json
import time

from . import config, convert, naver
from .db import pack, unpack

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_edit_log (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    what TEXT NOT NULL DEFAULT '',          -- 상세 / 옵션 / 상세·옵션 / 되돌림
    before TEXT NOT NULL DEFAULT '',        -- 고치기 전 {상세설명, 옵션상품} (json)
    memo TEXT NOT NULL DEFAULT '',
    at REAL
);
CREATE INDEX IF NOT EXISTS ix_sel_src ON source_edit_log(source_id);
"""

MAX_OPT_ROWS = 500


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def _opt_view(row):
    """원본 옵션 → 고치기 화면용 {kind, groups[3], rows[{n1,n2,n3,price,usable,stock}], editable, note}."""
    o = convert.options(row) or {}
    combos = o.get("optionCombinations") or []
    g = o.get("optionCombinationGroupNames") or {}
    other = [k for k in ("optionSimple", "optionCustom", "optionStandards") if o.get(k)]
    out = {"groups": [str(g.get(f"optionGroupName{i}") or "") for i in (1, 2, 3)],
           "rows": [{"n1": str(c.get("optionName1") or ""), "n2": str(c.get("optionName2") or ""), "n3": str(c.get("optionName3") or ""),
                     "price": convert.to_int(c.get("price")), "usable": c.get("usable", True) is not False,
                     "stock": convert.to_int(c.get("stockQuantity"))} for c in combos],
           "editable": not other, "kind": "combination" if combos else ("" if not other else "other")}
    if other:
        out["note"] = "이 원본의 옵션은 조합형이 아니라(단독형·직접입력형 등) 여기서 고칠 수 없습니다."
    return out


def content(db, sid):
    s = db.one("SELECT id, name, price, data FROM sources WHERE id=?", (sid,))
    if not s:
        raise ValueError("원본이 없습니다.")
    row = unpack(s["data"])
    n_live = db.one("SELECT COUNT(*) AS n FROM listings WHERE source_id=? AND origin_no!='' AND status!='deleted'", (sid,))["n"]
    return {"id": s["id"], "name": s["name"], "price": s["price"], "detail": str(row.get("상세설명") or ""),
            "options": _opt_view(row), "n_live": n_live, "log": log(db, sid)}


def _build_options(old, groups, rows, base_price):
    """화면에서 고친 옵션 → 옵션상품 dict (없으면 None). 예전 조합의 관리코드·재고는 같은 옵션 이름이면 이어 씀."""
    rows = [r for r in rows if str(r.get("n1") or "").strip()]
    if not rows:
        return None, []
    if len(rows) > MAX_OPT_ROWS:
        raise ValueError(f"옵션은 {MAX_OPT_ROWS}개까지입니다.")
    groups = [str(x or "").strip()[:25] for x in (list(groups) + ["", "", ""])[:3]]
    depth = max(1 + bool(str(r.get("n2") or "").strip()) + bool(str(r.get("n3") or "").strip()) for r in rows)
    if not groups[0]:
        raise ValueError("첫 번째 옵션 이름(예: 색상)을 적어 주세요.")
    for i in range(1, depth):
        if not groups[i]:
            raise ValueError(f"{i + 1}번째 옵션 이름을 적어 주세요 (옵션값이 {i + 1}단계까지 있음).")
    warn, seen = [], set()
    prev = {convert.option_key(c): c for c in ((old or {}).get("optionCombinations") or [])}
    combos = []
    for r in rows:
        names = [str(r.get(f"n{i}") or "").strip()[:25] for i in (1, 2, 3)]
        for i in range(depth):
            if not names[i]:
                raise ValueError(f"옵션 '{' / '.join(x for x in names if x)}'의 {i + 1}번째 값이 비었습니다.")
        key = tuple(names)
        if key in seen:
            raise ValueError(f"같은 옵션이 두 번 있습니다: {' / '.join(x for x in names if x)}")
        seen.add(key)
        p = prev.get(key) or {}
        c = {f"optionName{i + 1}": names[i] for i in range(depth)}
        c.update({"price": convert.to_int(r.get("price")), "stockQuantity": convert.to_int(p.get("stockQuantity"), 1000) or 1000,
                  "usable": r.get("usable", True) is not False})
        if p.get("sellerManagerCode"):
            c["sellerManagerCode"] = p["sellerManagerCode"]
        combos.append(c)
    if not any(c["usable"] for c in combos):
        raise ValueError("판매하는(사용) 옵션이 하나는 있어야 합니다.")
    lo, hi = convert.option_price_range(base_price)
    bad = [c["optionName1"] for c in combos if not lo <= c["price"] <= hi]
    if bad:
        warn.append(f"옵션 추가금이 허용 범위({lo:+,}~{hi:+,}원)를 벗어남: {', '.join(bad[:3])}")
    o = dict(old or {})
    for k in ("optionSimple", "optionCustom", "optionStandards"):
        o.pop(k, None)
    o.update({"optionCombinationGroupNames": {f"optionGroupName{i + 1}": groups[i] for i in range(depth)},
              "optionCombinations": combos, "optionKind": "combination", "useStockManagement": True})
    o.setdefault("optionCombinationSortType", "CREATE")
    return o, warn


def save(db, sid, detail=None, options=None, memo=""):
    """상세(HTML)·옵션 고치기. options: {groups:[3], rows:[{n1,n2,n3,price,usable}]} (rows가 비면 옵션 없음)."""
    s = db.one("SELECT id, price, data FROM sources WHERE id=?", (sid,))
    if not s:
        raise ValueError("원본이 없습니다.")
    busy = db.one("SELECT COUNT(*) AS n FROM listings WHERE source_id=? AND status IN ('queued','running')", (sid,))["n"]
    if busy:
        raise ValueError("이 원본의 복사본이 지금 등록 중입니다. 끝난 뒤에 고치세요.")
    row = unpack(s["data"])
    before = {"상세설명": row.get("상세설명"), "옵션상품": row.get("옵션상품")}
    what, warn = [], []
    if detail is not None:
        detail = str(detail)
        if not detail.strip():
            raise ValueError("상세페이지가 비었습니다.")
        if detail != str(row.get("상세설명") or ""):
            row["상세설명"] = detail
            what.append("상세")
    if options is not None:
        old = row.get("옵션상품") if isinstance(row.get("옵션상품"), dict) else None
        if old and not _opt_view(row)["editable"]:
            raise ValueError("이 원본의 옵션은 조합형이 아니라 여기서 고칠 수 없습니다.")
        new, warn = _build_options(old, options.get("groups") or [], options.get("rows") or [], s["price"])
        if json.dumps(new, ensure_ascii=False, sort_keys=True) != json.dumps(old, ensure_ascii=False, sort_keys=True):
            row["옵션상품"] = new
            what.append("옵션")
    if not what:
        return {"changed": False, "warnings": warn}
    _write(db, sid, row, "·".join(what), before, memo)
    return {"changed": True, "what": "·".join(what), "warnings": warn}


def _write(db, sid, row, what, before, memo=""):
    cfg = config.load()
    sm = convert.summary(row, cfg)
    fix = (db.one("SELECT category_fix FROM sources WHERE id=?", (sid,)) or {}).get("category_fix") or ""
    errors, warnings = convert.validate(convert.with_category_fix(row, fix), cfg, naver.cached_categories())
    now = time.time()
    with db.tx() as c:
        c.execute("INSERT INTO source_edit_log(source_id, what, before, memo, at) VALUES(?,?,?,?,?)",
                  (sid, what, json.dumps(before, ensure_ascii=False), str(memo or "")[:200], now))
        c.execute("""UPDATE sources SET data=?, option_count=?, image_count=?, has_video=?, errors=?, warnings=?, valid=?, updated_at=?
            WHERE id=?""", (pack(row), sm["option_count"], sm["image_count"], int(sm["has_video"]),
                           json.dumps(errors, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False), int(not errors), now, sid))
        # 가져온(가격 고정) 판매 중 복사본의 옵션 가격 기억은 옵션 이름이 바뀌면 맞지 않으므로 옵션을 고치면 비움 (최신화 직전에 네이버에서 다시 읽음)
        if "옵션" in what or what == "되돌림":
            c.execute("UPDATE listings SET opt_fixed='' WHERE source_id=?", (sid,))


def undo_last(db, sid):
    """마지막 수정 되돌리기 (그 전 상세·옵션으로)."""
    r = db.one("SELECT id, before FROM source_edit_log WHERE source_id=? AND what NOT LIKE '%되돌림%' ORDER BY id DESC LIMIT 1", (sid,))
    if not r:
        raise ValueError("되돌릴 수정이 없습니다.")
    s = db.one("SELECT data FROM sources WHERE id=?", (sid,))
    if not s:
        raise ValueError("원본이 없습니다.")
    row = unpack(s["data"])
    cur = {"상세설명": row.get("상세설명"), "옵션상품": row.get("옵션상품")}
    b = json.loads(r["before"] or "{}")
    row["상세설명"], row["옵션상품"] = b.get("상세설명"), b.get("옵션상품")
    _write(db, sid, row, "되돌림", cur, f"수정 #{r['id']} 되돌림")
    db.x("UPDATE source_edit_log SET what=what||' (되돌림)' WHERE id=?", (r["id"],))
    return {"undone": r["id"]}


def log(db, sid):
    return db.q("SELECT id, what, memo, at FROM source_edit_log WHERE source_id=? ORDER BY id DESC LIMIT 20", (int(sid),))
