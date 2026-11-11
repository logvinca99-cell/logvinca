"""복사본 일괄 수정 (한 스토어): 양식 엑셀을 받아 '새 손님 가격'·'새 상품명'을 적어 올리면 미리보기 → 적용.

- 줄 찾기: 복사본 번호 + 상품번호(올라간 것) 또는 판매자 관리코드(관리코드만 있는 것) 또는 원본 상품명(안 올린 것)이 둘 다 맞아야 함.
  다른 스토어 양식이면 거절 (양식에 스토어 번호가 들어 있음).
- 새 손님 가격: 역마진 등으로 가격을 고치는 것 → 그 스토어 가격 차이 %로 거꾸로 계산한 값이 원본의 새 기준 가격.
  그 원본의 모든 스토어 복사본이 따라 바뀜 (baseprice.apply — 판매 중이면 지우지 않고 네이버 가격만).
- 새 상품명: 그 스토어 복사본만. 직접 고치기와 같은 검사(금지 단어·상표·반복·모든 스토어 통틀어 같은 이름 금지).
  안 올린 복사본은 바로, 판매 중이면 지우지 않고 네이버 상품명만 바꿈 (name_push 대기 → 성공하면 이름 바뀜).
- 잠긴(판매 이력) 상품도 가격·상품명은 바꿈 (지우지 않으므로 리뷰·판매 기록 그대로). 지금 등록 중인 것만 뺌.
"""
import io
import time

from . import baseprice, config, convert, excel, lexicon, namegen, naver

COLS = ["복사본 번호", "상품번호", "판매자 관리코드", "상태", "잠금", "원본 상품명", "지금 상품명", "새 상품명",
        "지금 손님 가격", "새 손님 가격", "네이버 판매가 (참고)", "메모"]
STATUS = {"planned": "등록 대기", "queued": "처리 중", "running": "처리 중", "success": "판매 중", "fail": "실패", "deleted": "내림"}


def template_xlsx(db, store_id):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    st = db.store(int(store_id))
    if not st:
        raise ValueError("스토어가 없습니다.")
    wb = Workbook()
    ws = wb.active
    ws.title = "복사본 일괄 수정"
    ws.append([f"스토어 #{st['id']} {st['name']}", "", "", "", "", "", "", "← 새 상품명·새 손님 가격 칸만 채우세요 (빈 칸은 그대로). 다른 스토어 양식은 받지 않습니다."])
    ws.append(COLS)
    rows = db.q("""SELECT l.id, l.channel_no, l.seller_code, l.status, l.op, l.locked, l.name, l.price, l.sale_shown, s.name AS src
        FROM listings l JOIN sources s ON s.id=l.source_id WHERE l.store_id=? ORDER BY l.status='deleted', l.id""", (st["id"],))
    for r in rows:
        ws.append([r["id"], r["channel_no"], r["seller_code"], STATUS.get(r["status"], r["status"]), "잠김" if r["locked"] else "",
                   r["src"], r["name"], "", r["price"], "", r["sale_shown"] or "", ""])
    hdr = ws[2]
    for c in hdr:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F8F4E")
        c.alignment = Alignment(horizontal="center", vertical="center")
    for c in (ws["H2"], ws["J2"]):
        c.fill = PatternFill("solid", fgColor="E8A317")
    ws["A1"].font = Font(bold=True)
    ws.freeze_panes = "A3"
    for col, w in zip("ABCDEFGHIJKL", (10, 16, 18, 10, 6, 44, 44, 44, 12, 12, 14, 24)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=3, min_col=2, max_col=3):
        for c in row:
            c.number_format = "@"
    for row in ws.iter_rows(min_row=3, min_col=9, max_col=11):
        for c in row:
            c.number_format = "#,##0"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), st["name"]


def _rows(path, filename):
    """양식 → (스토어 번호, 줄들). 1행은 스토어 표시, 2행이 머리글."""
    from openpyxl import load_workbook
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise ValueError("이 프로그램에서 받은 양식(xlsx)을 올려 주세요.")
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    first = next(it, None) or ()
    head = [str(x or "").strip() for x in (next(it, None) or ())]
    if "복사본 번호" not in head or "새 손님 가격" not in head:
        raise ValueError("양식의 머리글이 다릅니다. 복사본 화면 [일괄 수정 양식 받기]로 받은 파일을 올려 주세요.")
    m = str(first[0] or "") if first else ""
    try:
        sid = int(m.split("#", 1)[1].split()[0]) if "#" in m else 0
    except ValueError:
        sid = 0
    out = []
    for n, vals in enumerate(it, 3):
        row = {head[i]: vals[i] for i in range(min(len(head), len(vals))) if head[i]}
        if any(str(v or "").strip() for v in row.values()):
            out.append((n, row))
    wb.close()
    return sid, out


def _s(v):
    s = str(v if v is not None else "").strip()
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s


def preview(db, path, filename, store_id):
    store_id = int(store_id)
    fsid, rows = _rows(path, filename)
    if fsid and fsid != store_id:
        other = (db.store(fsid) or {}).get("name", f"#{fsid}")
        raise ValueError(f"'{other}' 스토어 양식입니다. 지금 화면의 스토어 양식을 올려 주세요.")
    cfg = {**config.load(), "_lex": lexicon.get(db)}
    store = db.store(store_id) or {}
    from . import ctxname
    items, seen_names, price_by_src = [], {}, {}
    for line, r in rows:
        try:
            lid = int(float(_s(r.get("복사본 번호")) or 0))
        except ValueError:
            lid = 0
        new_name = namegen.clean(_s(r.get("새 상품명")), 100) if _s(r.get("새 상품명")) else ""
        target = convert.to_int(_s(r.get("새 손님 가격")).replace(",", "").replace("원", ""))
        if not new_name and not target:
            continue
        it = {"line": line, "listing_id": lid, "name_new": new_name, "target": target, "memo": _s(r.get("메모"))[:200], "why": []}
        l = db.one("""SELECT l.id, l.store_id, l.source_id, l.channel_no, l.seller_code, l.origin_no, l.status, l.locked, l.name, l.price,
            s.name AS src FROM listings l JOIN sources s ON s.id=l.source_id WHERE l.id=?""", (lid,)) if lid else None
        if not l or l["store_id"] != store_id:
            it.update(status="notfound", why=["이 스토어에 그 복사본 번호가 없음"])
            items.append(it)
            continue
        ch, code, src = _s(r.get("상품번호")), _s(r.get("판매자 관리코드")), _s(r.get("원본 상품명"))
        same = (ch == l["channel_no"]) if l["channel_no"] else (code == l["seller_code"]) if l["seller_code"] else (src == l["src"])
        if not same:
            it.update(status="mismatch", why=["복사본 번호와 상품번호(또는 관리코드·원본 상품명)가 서로 안 맞음 — 양식을 새로 받으세요"])
            items.append(it)
            continue
        it.update(name_old=l["name"], price_old=l["price"], source_id=l["source_id"], live=bool(l["origin_no"]) and l["status"] != "deleted",
                  locked=bool(l["locked"]))
        if l["status"] in ("queued", "running"):
            it.update(status="busy", why=["지금 등록 중 — 끝난 뒤 다시"])
            items.append(it)
            continue
        if new_name and new_name != l["name"]:
            norm = namegen.normalize(new_name)
            why = namegen.check_name(new_name, cfg, cfg["_lex"])
            src_words = set(l["src"].split())
            claims = [w for w in new_name.split() if w not in src_words and ctxname.claim_word(w)]
            if namegen.normalize(l["src"]) == norm:
                it["why"].append("원본 상품명 그대로는 올리지 않음")
            elif why:
                it["why"].append(f"상품명: {why}")
            elif claims:
                it["why"].append(f"상품명: 쓸 수 없는 표현 '{claims[0]}'")
            elif db.one("SELECT 1 FROM names WHERE norm=? AND NOT (source_id=? AND (listing_id IS NULL OR listing_id=?))",
                        (norm, l["source_id"], lid)):
                it["why"].append("상품명: 다른 상품·스토어에서 쓰는(썼던) 이름")
            elif norm in seen_names:
                it["why"].append(f"상품명: 이 파일 {seen_names[norm]}행과 같은 이름")
            else:
                seen_names[norm] = line
                it["name_ok"] = True
        if target and target != l["price"]:
            if target < 100:
                it["why"].append("새 손님 가격이 너무 작음")
            else:
                base = convert.base_for(target, cfg, store)
                prev = price_by_src.get(l["source_id"])
                if prev and prev[0] != base:
                    it["why"].append("같은 원본을 다른 가격으로 고친 줄이 또 있음")
                else:
                    price_by_src[l["source_id"]] = (base, line)
                    eff = baseprice.effect(db, l["source_id"], base)
                    it.update(price_ok=True, base=base, price_new=convert.store_price(base, cfg, store),
                              others=sum(1 for c in eff["copies"] if c["listing_id"] != lid))
        if it["why"]:
            it["status"] = "bad"
        elif it.get("name_ok") or it.get("price_ok"):
            it["status"] = "ok"
        else:
            it["status"] = "same"
        items.append(it)
    ok = [x for x in items if x["status"] == "ok"]
    return {"store_id": store_id, "store": store.get("name", ""), "file": filename, "items": items,
            "ok": len(ok), "bad": sum(1 for x in items if x["status"] in ("bad", "mismatch", "notfound", "busy")),
            "same": sum(1 for x in items if x["status"] == "same"),
            "n_price": sum(1 for x in ok if x.get("price_ok")), "n_name": sum(1 for x in ok if x.get("name_ok")),
            "n_live": sum(1 for x in ok if x.get("live")), "n_locked": sum(1 for x in ok if x.get("locked")),
            "others": sum(x.get("others", 0) for x in ok if x.get("price_ok"))}


def apply(db, pv, how=""):
    """미리보기 결과(ok 줄)를 적용 → 가격은 기준 가격 수정으로, 상품명은 안 올린 것 바로·판매 중은 네이버 대기.
    → {'prices': 원본 수, 'names': 바로 바꾼 수, 'name_live': 네이버 대기, 'price_live': [네이버 가격 대기 복사본]}"""
    cfg = {**config.load(), "_lex": lexicon.get(db)}
    ok = [x for x in pv["items"] if x["status"] == "ok"]
    prices = [{"source_id": x["source_id"], "price": x["base"], "memo": x.get("memo") or "복사본 일괄 수정"} for x in ok if x.get("price_ok")]
    st = baseprice.apply(db, prices, how or f"복사본 일괄 수정 · {pv.get('store', '')}") if prices else {"sources": 0, "pending": 0, "live": []}
    out = {"prices": st["sources"], "price_pending": st["pending"], "price_live": st["live"], "names": 0, "name_live": 0, "name_skip": []}
    from .inventory import add_names, release_name
    now = time.time()
    with db.tx() as c:
        for x in ok:
            if not x.get("name_ok"):
                continue
            l = c.execute("SELECT id, source_id, name_id, origin_no, status FROM listings WHERE id=?", (x["listing_id"],)).fetchone()
            if not l or l["status"] in ("queued", "running"):
                out["name_skip"].append(f"{x['line']}행: 그새 등록 중")
                continue
            rej = []
            added, _ = add_names(c, l["source_id"], [x["name_new"]], "manual", now, cfg, rej)
            nid = c.execute("SELECT id, name, listing_id FROM names WHERE source_id=? AND norm=?",
                            (l["source_id"], namegen.normalize(x["name_new"]))).fetchone()
            if not nid or (nid["listing_id"] not in (None, l["id"])):
                out["name_skip"].append(f"{x['line']}행: {rej[0] if rej else '그새 다른 곳에서 쓰는 이름'}")
                continue
            c.execute("UPDATE names SET listing_id=? WHERE id=?", (l["id"], nid["id"]))   # 이 복사본 몫으로 잡아 둠
            if l["origin_no"] and l["status"] != "deleted":   # 판매 중 → 네이버 상품명만 바꾸기 대기 (성공하면 이름이 바뀜)
                c.execute("UPDATE listings SET name_push=? WHERE id=?", (nid["id"], l["id"]))
                out["name_live"] += 1
            else:
                if l["name_id"] and l["name_id"] != nid["id"]:
                    release_name(c, l["id"], l["name_id"], ("original", "adopt"))
                c.execute("UPDATE listings SET name_id=?, name=?, ctx_wait=0, updated_at=? WHERE id=?", (nid["id"], nid["name"], now, l["id"]))
                out["names"] += 1
    return out


def name_pending_count(db, store_id=None):
    w, a = "name_push IS NOT NULL AND origin_no!='' AND status!='deleted'", []
    if store_id:
        w += " AND store_id=?"
        a.append(int(store_id))
    return db.one(f"SELECT COUNT(*) AS n FROM listings WHERE {w}", a)["n"]


def push_names(db, store_id=None, progress=None, should_stop=None):
    """판매 중 복사본의 네이버 상품명만 바꾸기 (지우지 않음). 성공하면 이 프로그램의 이름도 바꾸고 예전 이름은 '다 쓴 이름'으로."""
    from .inventory import release_name
    w, a = "l.name_push IS NOT NULL AND l.origin_no!='' AND l.status NOT IN ('queued','running','deleted')", []
    if store_id:
        w += " AND l.store_id=?"
        a.append(int(store_id))
    rows = db.q(f"SELECT l.id, l.store_id, l.origin_no, l.name_push FROM listings l WHERE {w} ORDER BY l.id", a)
    out = {"ok": 0, "fail": 0, "errors": []}
    clients = {}
    for n, r in enumerate(rows, 1):
        if should_stop and should_stop():
            break
        nm = db.one("SELECT id, name FROM names WHERE id=?", (r["name_push"],))
        if not nm:
            db.set_listing(r["id"], None, name_push=None)
            continue
        try:
            if r["store_id"] not in clients:
                clients[r["store_id"]] = naver.make_client(db.store(r["store_id"], with_secret=True))
            clients[r["store_id"]].update_name(r["origin_no"], nm["name"])
            with db.tx() as c:
                cur = c.execute("SELECT name_id FROM listings WHERE id=?", (r["id"],)).fetchone()
                if cur and cur["name_id"] and cur["name_id"] != nm["id"]:
                    release_name(c, r["id"], cur["name_id"])   # 판매 중이던 이름 → 다 쓴 이름
                c.execute("UPDATE listings SET name_id=?, name=?, name_push=NULL, ctx_wait=0, message=?, updated_at=? WHERE id=?",
                          (nm["id"], nm["name"], "일괄 수정 → 네이버 상품명 바꿈", time.time(), r["id"]))
            out["ok"] += 1
        except Exception as e:  # noqa: BLE001
            db.set_listing(r["id"], None, message=f"네이버 상품명 바꾸기 실패 — 복사본 화면 [네이버 반영 다시 시도]로 다시: {e}"[:600])
            out["fail"] += 1
            if len(out["errors"]) < 5:
                out["errors"].append(str(e)[:80])
        if progress:
            progress(n, len(rows), f"네이버 상품명 바꾸는 중 {n:,}/{len(rows):,}")
    return out


def push_all(db, price_ids=None, store_id=None, progress=None, should_stop=None):
    """네이버 반영 대기(가격·상품명)를 모두 보냄."""
    a = baseprice.push_live(db, price_ids, store_id=store_id, progress=progress, should_stop=should_stop)
    b = push_names(db, store_id, progress=progress, should_stop=should_stop)
    left = baseprice.pending_count(db, store_id) + name_pending_count(db, store_id)
    msg = f"네이버 가격 바꿈 {a['ok']:,}건 · 상품명 바꿈 {b['ok']:,}건"
    if a["fail"] or b["fail"]:
        msg += f" · 실패 {a['fail'] + b['fail']:,}건"
    if left:
        msg += f" · 아직 대기 {left:,}건 ([네이버 반영 다시 시도])"
    return {"price_ok": a["ok"], "name_ok": b["ok"], "fail": a["fail"] + b["fail"], "left": left, "errors": (a["errors"] + b["errors"])[:5], "message": msg}
