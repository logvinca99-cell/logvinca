"""기준 가격 (기준 가격) 고정·수정.

원칙: 모든 스토어 손님 가격 = 원본의 기준 가격 × (1 + 그 스토어 가격 차이 %), 100원 올림.
기준 가격은 처음 원본을 넣을 때(원본 파일의 판매가 − 할인가, 기존 상품 가져오기는 그 스토어 손님 가격) 정해지고,
여기 수정 기능(원본 상세 창·엑셀)으로만 바뀐다 — 역마진이라 가격을 고친 경우 등. 수정하면:
  - 아직 안 올린 복사본: 가격을 바로 다시 계산
  - 판매 중 복사본: 새 손님 가격을 계산해 네이버 가격만 바로 바꿈 (상품은 지우지 않음 → 리뷰·판매 기록 그대로)
  - 가격 고정 복사본(기존 상품 가져오기): 손님 가격 = 새 기준 가격
바꾼 기록은 base_price_log에 남는다.
"""
import io
import json
import time

from . import config, convert, excel, naver

SCHEMA = """
CREATE TABLE IF NOT EXISTS base_price_log (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    old_price INTEGER,
    new_price INTEGER,
    memo TEXT NOT NULL DEFAULT '',
    how TEXT NOT NULL DEFAULT '',       -- 상세 창 / 엑셀 파일 이름
    at REAL
);
CREATE INDEX IF NOT EXISTS ix_bpl_src ON base_price_log(source_id);
"""

COLS = ["원본 상품명", "복사본 상품명", "판매자 관리코드", "상품번호", "새 기준 가격", "메모"]


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def template_xlsx():
    """수정 양식 (찾기 열은 넷 중 하나만 채우면 됨)."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "기준 가격 수정"
    ws.append(COLS)
    ws.append(["(예) 원본 상품명을 그대로", "", "", "", 12000, "역마진 — 가격 올림"])
    ws.append(["", "(예) 스토어에 올라간 복사본 상품명", "", "", 15500, ""])
    ws.append(["", "", "(예) S01-123-2", "", 9900, ""])
    for col, w in zip("ABCDEF", (40, 40, 20, 16, 14, 30)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _match(db, row):
    """엑셀 한 줄 → (원본 번호 집합, 무엇으로 찾았나). 찾는 순서: 상품번호 → 판매자 관리코드 → 복사본 상품명 → 원본 상품명 (상품명은 완전히 같을 때만)."""
    ch = str(row.get("상품번호") or "").strip().split(".")[0]
    if ch:
        ids = {next(iter(r.values())) for r in db.q("SELECT source_id FROM listings WHERE channel_no=?", (ch,))}
        ids |= {next(iter(r.values())) for r in db.q("SELECT l.source_id FROM listing_history h JOIN listings l ON l.id=h.listing_id WHERE h.channel_no=?", (ch,))}
        return ids, "상품번호"
    code = str(row.get("판매자 관리코드") or row.get("판매자관리코드") or "").strip()
    if code:
        ids = {next(iter(r.values())) for r in db.q("SELECT source_id FROM listings WHERE seller_code=?", (code,))}
        ids |= {next(iter(r.values())) for r in db.q("SELECT l.source_id FROM listing_history h JOIN listings l ON l.id=h.listing_id WHERE h.seller_code=?", (code,))}
        return ids, "판매자 관리코드"
    cn = str(row.get("복사본 상품명") or "").strip()
    if cn:
        ids = {next(iter(r.values())) for r in db.q("SELECT source_id FROM listings WHERE name=?", (cn,))}
        ids |= {next(iter(r.values())) for r in db.q("SELECT source_id FROM names WHERE name=?", (cn,))}
        ids |= {next(iter(r.values())) for r in db.q("SELECT l.source_id FROM listing_history h JOIN listings l ON l.id=h.listing_id WHERE h.name=?", (cn,))}
        return ids, "복사본 상품명"
    on = str(row.get("원본 상품명") or "").strip()
    if on:
        return {next(iter(r.values())) for r in db.q("SELECT id FROM sources WHERE name=?", (on,))}, "원본 상품명"
    return set(), ""


def preview(db, path, filename):
    """올린 수정 엑셀 → 줄마다 찾은 원본·예전→새 기준 가격·영향 받는 복사본 (아무것도 안 바꿈)."""
    out = []
    for i, row in enumerate(excel.iter_rows(path, filename, parse=False), 2):
        if not any(str(v or "").strip() for v in row.values()):
            continue
        new = convert.to_int(row.get("새 기준 가격") if row.get("새 기준 가격") not in (None, "") else row.get("새 기준 " + "구매가"))   # 예전 양식 머리글도
        ids, how = _match(db, row)
        key = next((str(row.get(k) or "").strip() for k in COLS[:4] if str(row.get(k) or "").strip()), "")
        item = {"line": i, "key": key[:80], "how": how, "new": new, "memo": str(row.get("메모") or "")[:200]}
        if new <= 0:
            item["status"], item["why"] = "bad", "새 기준 가격이 비었거나 0"
        elif not ids:
            item["status"], item["why"] = "notfound", "못 찾음" if how else "찾을 칸(상품명·코드·상품번호)이 비었음"
        elif len(ids) > 1:
            item["status"], item["why"] = "ambiguous", f"원본 {len(ids)}개에 맞음 — 상품번호나 판매자 관리코드로 다시"
        else:
            sid = ids.pop()
            item.update(status="ok", **effect(db, sid, new))
        out.append(item)
    ok = [x for x in out if x["status"] == "ok"]
    return {"items": out, "ok": len(ok), "bad": len(out) - len(ok),
            "live": sum(x["n_live"] for x in ok), "pending": sum(x["n_pending"] for x in ok), "file": filename}


def effect(db, sid, new):
    """원본 하나의 기준 가격을 new로 바꾸면 어떻게 되나 (스토어별 새 손님 가격)."""
    cfg = config.load()
    s = db.one("SELECT id, name, price, price_src FROM sources WHERE id=?", (sid,))
    stores = {x["id"]: x for x in db.stores()}
    copies = []
    for l in db.q("""SELECT id, store_id, status, origin_no, price, price_fixed FROM listings WHERE source_id=? AND status!='deleted'""", (sid,)):
        st = stores.get(l["store_id"]) or {}
        newp = new if l["price_fixed"] else convert.store_price(new, "", cfg, st)
        copies.append({"listing_id": l["id"], "store": st.get("name", ""), "live": bool(l["origin_no"]),
                       "busy": l["status"] in ("queued", "running"), "old": l["price"], "new": newp})
    return {"source_id": sid, "source_name": s["name"], "old": s["price"], "price_src": s["price_src"] or "file",
            "copies": copies, "n_live": sum(c["live"] for c in copies), "n_pending": sum(not c["live"] for c in copies)}


def apply(db, items, how=""):
    """기준 가격 바꾸기: [{source_id, price, memo}] → 기준 가격·안 올린 복사본 가격 바꿈, 판매 중 복사본(네이버 가격 바꿀 것) 목록을 돌려줌."""
    cfg = config.load()
    stores = {x["id"]: x for x in db.stores()}
    now = time.time()
    st = {"sources": 0, "pending": 0, "live": []}
    with db.tx() as c:
        for it in items:
            sid, new = int(it["source_id"]), convert.to_int(it.get("price"))
            if new <= 0:
                continue
            s = c.execute("SELECT id, price FROM sources WHERE id=?", (sid,)).fetchone()
            if not s:
                continue
            c.execute("INSERT INTO base_price_log(source_id, old_price, new_price, memo, how, at) VALUES(?,?,?,?,?,?)",
                      (sid, s["price"], new, str(it.get("memo") or "")[:200], how[:120], now))
            c.execute("UPDATE sources SET price=?, price_src='manual', price_at=? WHERE id=?", (new, now, sid))
            st["sources"] += 1
            for l in c.execute("SELECT id, store_id, status, origin_no, price_fixed FROM listings WHERE source_id=? AND status!='deleted'", (sid,)).fetchall():
                if l["status"] in ("queued", "running"):
                    continue   # 지금 처리 중 → 다음에 올릴 때 새 기준으로 계산됨
                newp = new if l["price_fixed"] else convert.store_price(new, "", cfg, stores.get(l["store_id"]) or {})
                if l["origin_no"]:
                    st["live"].append(l["id"])
                else:
                    c.execute("UPDATE listings SET price=? WHERE id=?", (newp, l["id"]))
                    st["pending"] += 1
    return st


def push_live(db, lids, progress=None, should_stop=None):
    """판매 중 복사본의 네이버 가격만 바로 바꾸기 (상품은 지우지 않음). 새 손님 가격 = 기준 가격 × 그 스토어 가격 차이 % (가격 고정이면 기준 가격)."""
    cfg = config.load()
    unit = max(1, convert.to_int(cfg.get("price_round"), 100))
    rows = []
    for i in range(0, len(lids), 900):
        ch = lids[i:i + 900]
        rows += db.q(f"""SELECT l.id, l.store_id, l.origin_no, l.price_fixed, l.name, s.price AS base FROM listings l JOIN sources s ON s.id=l.source_id
            WHERE l.id IN ({','.join('?' * len(ch))}) AND l.origin_no!='' AND l.status NOT IN ('queued','running','deleted')""", ch)
    out = {"ok": 0, "fail": 0, "errors": []}
    clients = {}
    for n, r in enumerate(rows, 1):
        if should_stop and should_stop():
            break
        store = db.store(r["store_id"], with_secret=True)
        if r["store_id"] not in clients:
            clients[r["store_id"]] = naver.make_client(store)
        final = r["base"] if r["price_fixed"] else convert.store_price(r["base"], "", cfg, store)
        pct = convert.store_discount_pct(store, cfg)
        try:
            shown = clients[r["store_id"]].update_price(r["origin_no"], final, pct, unit)
            db.set_listing(r["id"], None, price=final, sale_shown=shown, message=f"기준 가격 수정 → 네이버 가격 바꿈 ({final:,}원)")
            out["ok"] += 1
        except Exception as e:  # noqa: BLE001
            db.set_listing(r["id"], None, price=final, message=f"네이버 가격 바꾸기 실패 — 다음 최신화 때 새 가격으로 올라감: {e}"[:600])
            out["fail"] += 1
            if len(out["errors"]) < 5:
                out["errors"].append(f"{r['name'][:30]}: {e}")
        if progress:
            progress(n, len(rows), f"네이버 가격 바꾸는 중 {n:,}/{len(rows):,}")
    out["message"] = f"네이버 가격 바꿈 {out['ok']:,}건" + (f" · 실패 {out['fail']:,}건 (다음 최신화 때 새 가격으로)" if out["fail"] else "")
    return out


def log(db, sid):
    return db.q("SELECT * FROM base_price_log WHERE source_id=? ORDER BY id DESC LIMIT 50", (int(sid),))


def items_json(items):
    return json.dumps(items, ensure_ascii=False)
