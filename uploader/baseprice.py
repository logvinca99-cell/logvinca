"""기준 가격 고정·수정.

가격 이름: 기준 가격(원본에 저장된 손님 가격, 모든 스토어의 출발점) · 스토어 가격 차이 %(그 스토어만 더하거나 빼는 %)
· 손님 가격(= 기준 가격 × (1 + 스토어 가격 차이 %), 100원 올림) · 네이버 판매가·즉시할인(표시 할인율로 자동).
기준 가격은 처음 원본을 넣을 때 정해지고 여기 수정 기능으로만 바뀐다(역마진 등). 사장님은 늘 '손님 가격'을 적는다:
  - 복사본(그 스토어)으로 찾은 줄: 그 스토어 가격 차이 %로 거꾸로 계산한 값이 새 기준 가격
  - 원본 상품명으로 찾은 줄: 적은 값이 새 기준 가격 (가격 차이 0%인 스토어의 손님 가격)
바꾸면 그 원본의 모든 스토어 복사본이 따라 바뀐다:
  - 아직 안 올린·내린 복사본: 가격을 바로 다시 계산
  - 판매 중 복사본(잠긴 것 포함): 지우지 않고 네이버 가격만 바꿈 → 바꾸기 대기(price_push)에 넣고 작업으로 보냄,
    실패하거나 못 보낸 것은 대기에 남아 [가격 바꾸기 다시 시도]로 다시 보냄
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

COLS = ["원본 상품명", "복사본 상품명", "판매자 관리코드", "상품번호", "새 손님 가격", "메모"]
PRICE_COLS = ("새 손님 가격", "새 기준 가격", "새 기준 구매가")   # 예전 양식 머리글도 읽음


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def _style(ws, widths):
    from openpyxl.styles import Alignment, Font, PatternFill
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F8F4E")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w


def template_xlsx():
    """수정 양식: 찾기 칸(원본 상품명·복사본 상품명·판매자 관리코드·상품번호) 중 하나만 채우고 '새 손님 가격'을 적음."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "기준 가격 수정"
    ws.append(COLS)
    ws.append(["(예) 원본 상품명을 그대로 — 이 값이 새 기준 가격", "", "", "", 12000, "(예)로 시작하는 줄은 읽지 않음"])
    ws.append(["", "(예) 스토어에 올라간 복사본 상품명", "", "", 15500, "그 스토어에서 받을 손님 가격"])
    ws.append(["", "", "(예) S01-123-2", "", 9900, ""])
    _style(ws, (44, 40, 20, 18, 14, 34))
    for row in ws.iter_rows(min_row=2, max_col=4):
        for c in row:
            c.number_format = "@"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _match(db, row):
    """엑셀 한 줄 → ({(원본 번호, 스토어 번호 또는 None)}, 무엇으로 찾았나). 찾는 순서: 상품번호 → 판매자 관리코드 → 복사본 상품명 → 원본 상품명.
    복사본으로 찾으면 그 스토어 손님 가격으로, 원본 상품명으로 찾으면 기준 가격으로 본다."""
    def pairs(sql, a):
        return {(r["source_id"], r["store_id"]) for r in db.q(sql, a)}
    ch = str(row.get("상품번호") or "").strip().split(".")[0]
    if ch:
        return (pairs("SELECT source_id, store_id FROM listings WHERE channel_no=?", (ch,))
                | pairs("SELECT l.source_id, l.store_id FROM listing_history h JOIN listings l ON l.id=h.listing_id WHERE h.channel_no=?", (ch,))), "상품번호"
    code = str(row.get("판매자 관리코드") or row.get("판매자관리코드") or "").strip()
    if code:
        return (pairs("SELECT source_id, store_id FROM listings WHERE seller_code=?", (code,))
                | pairs("SELECT l.source_id, l.store_id FROM listing_history h JOIN listings l ON l.id=h.listing_id WHERE h.seller_code=?", (code,))), "판매자 관리코드"
    cn = str(row.get("복사본 상품명") or "").strip()
    if cn:
        return (pairs("SELECT source_id, store_id FROM listings WHERE name=?", (cn,))
                | pairs("SELECT l.source_id, l.store_id FROM listing_history h JOIN listings l ON l.id=h.listing_id WHERE h.name=?", (cn,))), "복사본 상품명"
    on = str(row.get("원본 상품명") or "").strip()
    if on:
        return {(r["id"], None) for r in db.q("SELECT id FROM sources WHERE name=?", (on,))}, "원본 상품명"
    return set(), ""


def preview(db, path, filename):
    """올린 수정 엑셀 → 줄마다 찾은 원본·예전→새 기준 가격·스토어별 새 손님 가격 (아무것도 안 바꿈)."""
    cfg = config.load()
    stores = {x["id"]: x for x in db.stores()}
    out = []
    for i, row in enumerate(excel.iter_rows(path, filename, parse=False), 2):
        vals = [str(v or "").strip() for v in row.values()]
        if not any(vals) or any(v.startswith("(예)") for v in vals[:4]):
            continue
        raw = next((row.get(k) for k in PRICE_COLS if row.get(k) not in (None, "")), None)
        target = convert.to_int(str(raw or "").replace("원", "").replace(",", ""))
        found, how = _match(db, row)
        key = next((str(row.get(k) or "").strip() for k in COLS[:4] if str(row.get(k) or "").strip()), "")
        item = {"line": i, "key": key[:80], "how": how, "target": target, "memo": str(row.get("메모") or "")[:200]}
        sids = {sid for sid, _ in found}
        if target <= 0:
            item["status"], item["why"] = "bad", "새 손님 가격이 비었거나 숫자가 아님"
        elif not found:
            item["status"], item["why"] = "notfound", "못 찾음" if how else "찾을 칸(상품명·코드·상품번호)이 비었음"
        elif len(sids) > 1 or len(found) > 1:
            item["status"], item["why"] = "ambiguous", f"여러 상품에 맞음 ({len(found)}개) — 상품번호나 판매자 관리코드로 다시"
        else:
            sid, stid = next(iter(found))
            new = convert.base_for(target, cfg, stores.get(stid)) if stid else target
            item.update(status="ok", store=(stores.get(stid) or {}).get("name", ""), new=new, **effect(db, sid, new))
        out.append(item)
    seen = {}
    for x in out:   # 같은 원본을 두 줄이 다른 값으로 고치면 둘 다 막음
        if x["status"] == "ok":
            seen.setdefault(x["source_id"], set()).add(x["new"])
    for x in out:
        if x["status"] == "ok" and len(seen[x["source_id"]]) > 1:
            x["status"], x["why"] = "conflict", "같은 원본을 다른 값으로 고친 줄이 또 있음"
    ok = [x for x in out if x["status"] == "ok"]
    uniq = {x["source_id"]: x for x in ok}
    return {"items": out, "ok": len(uniq), "bad": len(out) - len(ok),
            "live": sum(x["n_live"] for x in uniq.values()), "pending": sum(x["n_pending"] for x in uniq.values()), "file": filename}


def effect(db, sid, new):
    """원본 하나의 기준 가격을 new로 바꾸면 어떻게 되나 (스토어별 새 손님 가격, 내린 것·잠긴 것 포함)."""
    cfg = config.load()
    s = db.one("SELECT id, name, price, price_src FROM sources WHERE id=?", (sid,))
    stores = {x["id"]: x for x in db.stores()}
    copies = []
    for l in db.q("""SELECT id, store_id, status, origin_no, price, locked FROM listings WHERE source_id=?""", (sid,)):
        st = stores.get(l["store_id"]) or {}
        live = bool(l["origin_no"]) and l["status"] != "deleted"
        copies.append({"listing_id": l["id"], "store": st.get("name", ""), "live": live, "locked": bool(l["locked"]),
                       "deleted": l["status"] == "deleted", "busy": l["status"] in ("queued", "running"),
                       "old": l["price"], "new": convert.store_price(new, cfg, st)})
    return {"source_id": sid, "source_name": s["name"], "old": s["price"], "price_src": s["price_src"] or "file",
            "copies": copies, "n_live": sum(c["live"] for c in copies), "n_pending": sum(not c["live"] for c in copies)}


def apply(db, items, how=""):
    """기준 가격 바꾸기: [{source_id, price(새 기준 가격), memo}] → 기준 가격·안 올린(내린) 복사본 가격을 바로 바꾸고,
    판매 중 복사본은 네이버 가격 바꾸기 대기(price_push)에 넣는다. → 대기에 넣은 복사본 번호들"""
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
            for l in c.execute("SELECT id, store_id, status, origin_no FROM listings WHERE source_id=?", (sid,)).fetchall():
                newp = convert.store_price(new, cfg, stores.get(l["store_id"]) or {})
                if l["origin_no"] and l["status"] != "deleted":   # 판매 중 (잠긴 것 포함) → 네이버 가격 바꾸기 대기
                    c.execute("UPDATE listings SET price_push=? WHERE id=?", (newp, l["id"]))
                    if l["status"] not in ("queued", "running"):   # 처리 중인 것은 엔진이 올릴 때 새 가격으로
                        st["live"].append(l["id"])
                elif l["status"] not in ("queued", "running"):
                    c.execute("UPDATE listings SET price=? WHERE id=?", (newp, l["id"]))
                    st["pending"] += 1
    return st


def pending_count(db, store_id=None):
    w, a = "price_push IS NOT NULL AND origin_no!='' AND status!='deleted'", []
    if store_id:
        w += " AND store_id=?"
        a.append(int(store_id))
    return db.one(f"SELECT COUNT(*) AS n FROM listings WHERE {w}", a)["n"]


def push_live(db, lids=None, store_id=None, progress=None, should_stop=None):
    """판매 중 복사본의 네이버 가격만 바꾸기 (지우지 않음). 대기(price_push)에 있는 것을 보냄 — lids를 주면 그것 먼저,
    끝나면 그새 대기에 들어온 것도 이어서. 성공하면 손님 가격을 바꾸고 대기를 지움, 실패하면 대기에 남김."""
    cfg = config.load()
    unit = max(1, convert.to_int(cfg.get("price_round"), 100))
    out = {"ok": 0, "fail": 0, "errors": []}
    tried, clients, bad_store = set(), {}, {}

    def pending():
        w, a = "price_push IS NOT NULL AND origin_no!='' AND status NOT IN ('queued','running','deleted')", []
        if store_id:
            w += " AND store_id=?"
            a.append(int(store_id))
        ids = [r["id"] for r in db.q(f"SELECT id FROM listings WHERE {w} ORDER BY id", a) if r["id"] not in tried]
        first = [i for i in (lids or []) if i in set(ids)]
        return first + [i for i in ids if i not in set(first)]

    total = 0
    for rnd in range(3):   # 다 보낸 뒤 그새 들어온 대기도 (최대 세 번 훑음)
        todo = pending()
        if not todo:
            if rnd < 2:
                time.sleep(1)
                continue
            break
        total += len(todo)
        for lid in todo:
            if should_stop and should_stop():
                break
            tried.add(lid)
            r = db.one("""SELECT id, store_id, origin_no, name, status, price_push FROM listings WHERE id=?""", (lid,))
            if not r or not r["price_push"] or not r["origin_no"] or r["status"] in ("queued", "running", "deleted"):
                continue   # 그새 처리 중·내림이 됨 → 엔진이 새 가격으로 올림
            sid = r["store_id"]
            try:
                if sid in bad_store:
                    raise naver.ApiError(bad_store[sid])
                store = db.store(sid, with_secret=True)
                if not store:
                    raise naver.ApiError("스토어가 없음")
                if sid not in clients:
                    try:
                        clients[sid] = (naver.make_client(store), convert.store_discount_pct(store, cfg))
                    except Exception as e:  # noqa: BLE001
                        bad_store[sid] = f"스토어 연결 실패: {e}"
                        raise
                client, pct = clients[sid]
                final = int(r["price_push"])
                shown = client.update_price(r["origin_no"], final, pct, unit)
                db.set_listing(lid, None, price=final, sale_shown=shown, price_push=None,
                               message=f"기준 가격 수정 → 네이버 가격 바꿈 (손님 가격 {final:,}원)")
                out["ok"] += 1
            except Exception as e:  # noqa: BLE001
                db.set_listing(lid, None, message=f"네이버 가격 바꾸기 실패 — 복사본 화면 [가격 바꾸기 다시 시도]로 다시: {e}"[:600])
                out["fail"] += 1
                if len(out["errors"]) < 5:
                    out["errors"].append(f"{r['name'][:30]}: {e}")
            if progress:
                progress(out["ok"] + out["fail"], total, f"네이버 가격 바꾸는 중 {out['ok'] + out['fail']:,}/{total:,}")
        if should_stop and should_stop():
            break
    left = pending_count(db, store_id)
    out["left"] = left
    out["message"] = f"네이버 가격 바꿈 {out['ok']:,}건" + (f" · 실패 {out['fail']:,}건" if out["fail"] else "") \
        + (f" · 아직 대기 {left:,}건 ([가격 바꾸기 다시 시도])" if left else "")
    return out


def log(db, sid):
    return db.q("SELECT * FROM base_price_log WHERE source_id=? ORDER BY id DESC LIMIT 50", (int(sid),))


def items_json(items):
    return json.dumps(items, ensure_ascii=False)
