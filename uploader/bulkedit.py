"""올린 상품 일괄 변경: 스토어(여러 개)를 골라 이미 네이버에 올라간 상품의 설정을 한 번에 바꾼다.

상품마다 네이버에서 원상품을 읽어(GET) 고른 항목만 고친 뒤 그대로 다시 보낸다(PUT) — 요청 2번.
바꿀 수 있는 것: 출고지·반품지(스토어 템플릿 값으로), 관부가세, 사은품, 이벤트 문구, 구매 적립금, 리뷰 적립금, 무이자할부.
'그대로'로 둔 항목은 건드리지 않는다.

- 작업(job)마다 대상 상품을 한 줄씩(bulk_item) 적어 두고 하나씩 처리 → 멈추거나 프로그램을 꺼도 '이어서'로 남은 것만.
- 먼저 '1개로 시험' → 판매자센터에서 확인 → '전체 시작'.
- 실패는 사유와 함께 남고 '실패만 다시'로 다시 보낸다.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, naver

SCHEMA = """
CREATE TABLE IF NOT EXISTS bulk_job (
    id INTEGER PRIMARY KEY,
    created_at REAL NOT NULL,
    spec TEXT NOT NULL,                   -- 바꿀 항목 (JSON)
    summary TEXT NOT NULL DEFAULT '',     -- 사람이 읽는 바꿀 항목 요약
    target TEXT NOT NULL,                 -- program: 프로그램으로 올린 상품만 / all: 스토어 전체 상품
    stores TEXT NOT NULL,                 -- [스토어 id]
    status TEXT NOT NULL DEFAULT 'ready', -- ready / tested / running / stopped / done
    tested_at REAL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS bulk_item (
    job_id INTEGER NOT NULL,
    store_id INTEGER NOT NULL,
    origin_no TEXT NOT NULL,
    listing_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending', -- pending / done / same(바꿀 게 없었음) / fail
    error TEXT NOT NULL DEFAULT '',
    changed TEXT NOT NULL DEFAULT '',
    at REAL,
    PRIMARY KEY (job_id, store_id, origin_no)
);
CREATE INDEX IF NOT EXISTS bulk_item_status ON bulk_item(job_id, status);
"""

CUSTOMS = {"NOT_APPLICABLE": "부과 대상 아님", "INCLUDED": "관부가세 포함", "EXCLUDED": "관부가세 미포함"}
SELLER_EDIT = "https://sell.smartstore.naver.com/#/products/edit/{}"


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def _int(v, name, lo=0, hi=10_000_000):
    try:
        n = int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"{name}: 숫자를 넣어 주세요.") from None
    if not lo <= n <= hi:
        raise ValueError(f"{name}: {lo:,}~{hi:,} 사이로 넣어 주세요.")
    return n


def normalize(spec):
    """화면에서 온 바꿀 항목 → 정리된 spec과 사람이 읽는 요약. 바꿀 게 하나도 없으면 오류."""
    s, lines = {}, []
    if spec.get("addr") == "template":
        s["addr"] = "template"
        lines.append("출고지·반품지 → 스토어 템플릿 값")
    c = spec.get("customs") or "keep"
    if c != "keep":
        if c != "remove" and c not in CUSTOMS:
            raise ValueError("관부가세 값을 골라 주세요.")
        s["customs"] = c
        lines.append("관부가세 → " + ("항목 빼기" if c == "remove" else CUSTOMS[c]))
    for key, label in (("gift", "사은품"), ("event", "이벤트 문구")):
        v = spec.get(key) or {}
        if v.get("mode") == "set":
            text = str(v.get("text") or "").strip()
            if not text:
                raise ValueError(f"{label} 내용을 넣어 주세요.")
            limit = 100 if key == "gift" else 200
            if len(text) > limit:
                raise ValueError(f"{label}은 {limit}자 안으로 넣어 주세요.")
            s[key] = {"mode": "set", "text": text}
            lines.append(f"{label} → '{text}'")
        elif v.get("mode") == "remove":
            s[key] = {"mode": "remove"}
            lines.append(f"{label} → 빼기")
    v = spec.get("ppoint") or {}
    if v.get("mode") == "set":
        unit = "PERCENT" if v.get("unit") == "PERCENT" else "WON"
        val = _int(v.get("value"), "구매 적립금", 1, 100 if unit == "PERCENT" else 1_000_000)
        s["ppoint"] = {"mode": "set", "value": val, "unit": unit}
        lines.append(f"구매 적립금 → {val:,}{'%' if unit == 'PERCENT' else '원'}")
    elif v.get("mode") == "remove":
        s["ppoint"] = {"mode": "remove"}
        lines.append("구매 적립금 → 빼기")
    v = spec.get("rpoint") or {}
    if v.get("mode") == "set":
        names = {"text": "텍스트 리뷰", "photo": "포토·동영상 리뷰", "after_text": "한 달 사용 텍스트 리뷰",
                 "after_photo": "한 달 사용 포토·동영상 리뷰", "member": "알림받기 동의 고객 리뷰"}
        pts = {k: _int(v.get(k) or 0, names[k], 0, 1_000_000) for k in names}
        if not any(pts.values()):
            raise ValueError("리뷰 적립금을 하나 이상 넣어 주세요.")
        s["rpoint"] = {"mode": "set", **pts}
        lines.append("리뷰 적립금 → " + " · ".join(f"{names[k]} {n:,}원" for k, n in pts.items() if n))
    elif v.get("mode") == "remove":
        s["rpoint"] = {"mode": "remove"}
        lines.append("리뷰 적립금 → 빼기")
    v = spec.get("interest") or {}
    if v.get("mode") == "set":
        m = _int(v.get("months"), "무이자할부 개월", 2, 24)
        s["interest"] = {"mode": "set", "months": m}
        lines.append(f"무이자할부 → {m}개월")
    elif v.get("mode") == "remove":
        s["interest"] = {"mode": "remove"}
        lines.append("무이자할부 → 빼기")
    if spec.get("region") in ("domestic", "overseas"):
        s["region"] = spec["region"]
        lines.append("끝난 스토어 표시 → " + ("국내(초록)" if spec["region"] == "domestic" else "해외(파랑)"))
    if not [k for k in s if k != "region"]:
        raise ValueError("바꿀 항목을 하나 이상 골라 주세요.")
    return s, lines


def applier(spec, store):
    """원상품 body를 spec대로 고치는 함수 → 바꾼 항목 이름 목록 (이미 같은 값이면 안 넣음)."""
    def apply(body):
        op = body.setdefault("originProduct", {})
        da = op.setdefault("detailAttribute", {})
        cb = op.setdefault("customerBenefit", {})
        changed = []

        def put(obj, key, val, label):
            if obj.get(key) != val:
                obj[key] = val
                changed.append(label)

        def drop(obj, key, label):
            if obj.get(key) not in (None, "", {}, []):
                obj.pop(key, None)
                changed.append(label)
            else:
                obj.pop(key, None)

        if spec.get("addr") == "template":
            claim = op.setdefault("deliveryInfo", {}).setdefault("claimDeliveryInfo", {})
            if store.get("tpl_ship_addr"):
                put(claim, "shippingAddressId", int(store["tpl_ship_addr"]), "출고지")
            if store.get("tpl_return_addr"):
                put(claim, "returnAddressId", int(store["tpl_return_addr"]), "반품지")
        c = spec.get("customs")
        if c == "remove":
            drop(da, "customsTaxType", "관부가세")
        elif c:
            put(da, "customsTaxType", c, "관부가세")
        g = spec.get("gift") or {}
        if g.get("mode") == "set":
            put(cb, "giftPolicy", {"presentContent": g["text"]}, "사은품")
        elif g.get("mode") == "remove":
            drop(cb, "giftPolicy", "사은품")
        e = spec.get("event") or {}
        if e.get("mode") == "set":
            put(da, "eventPhraseCont", e["text"], "이벤트 문구")
        elif e.get("mode") == "remove":
            drop(da, "eventPhraseCont", "이벤트 문구")
        p = spec.get("ppoint") or {}
        if p.get("mode") == "set":
            put(cb, "purchasePointPolicy", {"value": p["value"], "unitType": p["unit"]}, "구매 적립금")
        elif p.get("mode") == "remove":
            drop(cb, "purchasePointPolicy", "구매 적립금")
        r = spec.get("rpoint") or {}
        if r.get("mode") == "set":
            keys = {"text": "textReviewPoint", "photo": "photoVideoReviewPoint", "after_text": "afterUseTextReviewPoint",
                    "after_photo": "afterUsePhotoVideoReviewPoint", "member": "storeMemberReviewPoint"}
            put(cb, "reviewPointPolicy", {api: r[k] for k, api in keys.items() if r.get(k)}, "리뷰 적립금")
        elif r.get("mode") == "remove":
            drop(cb, "reviewPointPolicy", "리뷰 적립금")
        i = spec.get("interest") or {}
        if i.get("mode") == "set":
            put(cb, "freeInterestPolicy", {"value": i["months"]}, "무이자할부")
        elif i.get("mode") == "remove":
            drop(cb, "freeInterestPolicy", "무이자할부")
        if not cb:
            op.pop("customerBenefit", None)
        return changed
    return apply


# ───────────────────────── 작업 만들기·진행

def create(db, spec, store_ids, target):
    s, lines = normalize(spec)
    store_ids = sorted({int(x) for x in store_ids or []})
    if not store_ids:
        raise ValueError("스토어를 하나 이상 골라 주세요.")
    target = "all" if target == "all" else "program"
    if s.get("addr") == "template":
        stores = {x["id"]: x for x in db.stores()}
        miss = [stores[i]["name"] for i in store_ids if i in stores and not (stores[i].get("tpl_ship_addr") or stores[i].get("tpl_return_addr"))]
        if miss:
            raise ValueError("스토어 템플릿에 출고지·반품지 번호가 없습니다: " + ", ".join(miss[:5])
                             + " — 스토어 → 템플릿에서 먼저 정해 주세요.")
    jid = db.x("INSERT INTO bulk_job(created_at, spec, summary, target, stores) VALUES(?,?,?,?,?)",
               (time.time(), json.dumps(s, ensure_ascii=False), " / ".join(lines), target, json.dumps(store_ids)))
    if target == "program":
        _add_program_items(db, jid, store_ids)
    return job(db, jid)


def _add_program_items(db, jid, store_ids):
    with db.tx() as c:
        for sid in store_ids:
            c.execute("""INSERT OR IGNORE INTO bulk_item(job_id, store_id, origin_no, listing_id)
                SELECT ?, store_id, origin_no, id FROM listings WHERE store_id=? AND origin_no!='' AND status='success'""", (jid, sid))


def _fill_all_items(db, jid, sid, client, should_stop=None):
    """스토어 전체 상품: 네이버 목록을 받아 대상 줄을 만든다 (한 번만)."""
    if db.one("SELECT 1 FROM bulk_item WHERE job_id=? AND store_id=? LIMIT 1", (jid, sid)):
        return
    nos = client.origin_numbers(should_stop=should_stop)
    by_no = {r["origin_no"]: r["id"] for r in db.q("SELECT id, origin_no FROM listings WHERE store_id=? AND origin_no!=''", (sid,))}
    with db.tx() as c:
        for no in nos:
            c.execute("INSERT OR IGNORE INTO bulk_item(job_id, store_id, origin_no, listing_id) VALUES(?,?,?,?)",
                      (jid, sid, no, by_no.get(no)))


def _one(db, jid, it, client, apply):
    try:
        changed = client.edit_origin(it["origin_no"], apply)
        db.x("UPDATE bulk_item SET status=?, changed=?, error='', at=? WHERE job_id=? AND store_id=? AND origin_no=?",
             ("done" if changed else "same", ", ".join(changed), time.time(), jid, it["store_id"], it["origin_no"]))
        return True, changed
    except Exception as e:  # noqa: BLE001
        db.x("UPDATE bulk_item SET status='fail', error=?, at=? WHERE job_id=? AND store_id=? AND origin_no=?",
             (str(e)[:400], time.time(), jid, it["store_id"], it["origin_no"]))
        return False, str(e)


def run(db, jid, test=False, progress=None, should_stop=None):
    """test=True: 첫 스토어의 상품 1개만. 아니면 남은(대기) 것 전부, 스토어 여러 곳을 나란히."""
    j = db.one("SELECT * FROM bulk_job WHERE id=?", (jid,))
    if not j:
        raise ValueError("일괄 변경 작업을 찾지 못했습니다.")
    spec, sids = json.loads(j["spec"]), json.loads(j["stores"])
    stores = {s["id"]: s for s in db.stores(with_secret=True)}
    sids = [s for s in sids if s in stores]
    cfg = config.load()
    db.x("UPDATE bulk_job SET status='running' WHERE id=?", (jid,))
    st = {"done": 0, "same": 0, "failed": 0, "errors": [], "test": bool(test)}
    clients = {}

    def client(sid):
        if sid not in clients:
            clients[sid] = naver.make_client(stores[sid])
        return clients[sid]

    if test:
        for sid in sids:
            if j["target"] == "all":
                _fill_all_items(db, jid, sid, client(sid), should_stop)
            it = db.one("SELECT * FROM bulk_item WHERE job_id=? AND store_id=? AND status IN ('pending','fail') ORDER BY rowid LIMIT 1", (jid, sid))
            if not it:
                continue
            ok, res = _one(db, jid, it, client(sid), applier(spec, stores[sid]))
            st.update(store=stores[sid]["name"], origin_no=it["origin_no"], link=SELLER_EDIT.format(it["origin_no"]))
            if ok:
                st["done" if res else "same"] += 1
                st["changed"] = res
            else:
                st["failed"] += 1
                st["errors"].append(res)
            break
        else:
            st["empty"] = True
        db.x("UPDATE bulk_job SET status='tested', tested_at=? WHERE id=?", (time.time(), jid))
        return st

    total = [0]
    done = [0]

    def lane(sid):
        c = client(sid)
        if j["target"] == "all":
            try:
                _fill_all_items(db, jid, sid, c, should_stop)
            except Exception as e:  # noqa: BLE001
                st["errors"].append(f"{stores[sid]['name']}: {e}"[:200])
                return
        apply = applier(spec, stores[sid])
        items = db.q("SELECT * FROM bulk_item WHERE job_id=? AND store_id=? AND status='pending' ORDER BY rowid", (jid, sid))
        total[0] += len(items)
        for it in items:
            if should_stop and should_stop():
                return
            ok, res = _one(db, jid, it, c, apply)
            if ok:
                st["done" if res else "same"] += 1
            else:
                st["failed"] += 1
                if len(st["errors"]) < 5:
                    st["errors"].append(f"{stores[sid]['name']}: {res}"[:200])
            done[0] += 1
            if progress:
                progress(done[0], max(total[0], done[0]), f"바꿈 {st['done']:,} · 이미 같음 {st['same']:,} · 실패 {st['failed']:,}")
        if spec.get("region") and not db.one("SELECT 1 FROM bulk_item WHERE job_id=? AND store_id=? AND status IN ('pending','fail') LIMIT 1", (jid, sid)) \
                and db.one("SELECT 1 FROM bulk_item WHERE job_id=? AND store_id=? AND status IN ('done','same') LIMIT 1", (jid, sid)):
            db.x("UPDATE stores SET ship_region=? WHERE id=?", (spec["region"], sid))

    with ThreadPoolExecutor(max_workers=max(1, min(len(sids) or 1, int(cfg.get("max_parallel_stores") or 3)))) as pool:
        list(pool.map(lane, sids))
    left = db.one("SELECT COUNT(*) AS n FROM bulk_item WHERE job_id=? AND status='pending'", (jid,))["n"]
    db.x("UPDATE bulk_job SET status=? WHERE id=?", ("stopped" if left else "done", jid))
    st["left"] = left
    return st


def retry_failed(db, jid):
    n = db.one("SELECT COUNT(*) AS n FROM bulk_item WHERE job_id=? AND status='fail'", (jid,))["n"]
    db.x("UPDATE bulk_item SET status='pending', error='' WHERE job_id=? AND status='fail'", (jid,))
    db.x("UPDATE bulk_job SET status='stopped' WHERE id=? AND status='done'", (jid,))
    return {"count": n}


def job(db, jid):
    j = db.one("SELECT * FROM bulk_job WHERE id=?", (jid,))
    if not j:
        return None
    names = {s["id"]: s["name"] for s in db.stores()}
    per = db.q("""SELECT store_id, SUM(status='pending') AS pending, SUM(status='done') AS done, SUM(status='same') AS same,
        SUM(status='fail') AS fail, COUNT(*) AS total FROM bulk_item WHERE job_id=? GROUP BY store_id""", (jid,))
    by = {r["store_id"]: r for r in per}
    j["per_store"] = [{"store_id": sid, "name": names.get(sid, f"#{sid}"),
                       **{k: (by.get(sid) or {}).get(k) or 0 for k in ("pending", "done", "same", "fail", "total")}}
                      for sid in json.loads(j["stores"])]
    j["errors"] = db.q("""SELECT error, COUNT(*) AS n, MIN(origin_no) AS example FROM bulk_item WHERE job_id=? AND status='fail'
        GROUP BY error ORDER BY n DESC LIMIT 10""", (jid,))
    j["sample"] = db.q("SELECT store_id, origin_no, changed, status, at FROM bulk_item WHERE job_id=? AND status IN ('done','same') ORDER BY at DESC LIMIT 5", (jid,))
    for x in j["sample"]:
        x["link"] = SELLER_EDIT.format(x["origin_no"])
    return j


def jobs(db, limit=20):
    return [job(db, r["id"]) for r in db.q("SELECT id FROM bulk_job ORDER BY id DESC LIMIT ?", (limit,))]
