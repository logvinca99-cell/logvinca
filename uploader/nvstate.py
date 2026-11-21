"""복사본의 네이버 상태 (스토어처럼 판매 중·품절·판매중지·판매금지… 구분).

스토어 상품 목록(커머스API products/search, 한 번에 500개)을 끝까지 받아 판매 중 복사본마다
판매 상태·전시 상태를 적는다. 네이버 손님 가격은 nv_price에만 적고 업스타 가격은 바꾸지 않는다
(가격은 업스타 [기준 가격 수정]으로만 — 다르면 복사본 화면 '가격 확인 필요'로 알림).
사장님이 복사본 화면·스토어 카드의 [네이버 상태 확인]을 누를 때만 한다 — [최신화]·[다시 올리기]를 누르면 마지막 확인이 재사용 시간(기본 6시간)보다 오래된 스토어만 한 번 자동으로 하고,
그 안이면 적어 둔 상태를 쓴다 (실패해도 막지 않고 마지막 확인 결과로 진행). 판매중지·판매금지 상품은 빼고 내리기는 확인하지 않는다.
"""
import time

# 판매 상태 (statusType)
LABEL = {"SALE": "판매 중", "OUTOFSTOCK": "품절", "SUSPENSION": "판매중지", "PROHIBITION": "판매금지",
         "WAIT": "판매 대기", "CLOSE": "판매 종료", "UNADMISSION": "승인 대기", "REJECTION": "승인 거부",
         "DELETE": "스토어에 없음", "GONE": "스토어에 없음"}
# 최신화해도 되는 상태 (지우고 새로 올려도 손님이 보던 상태와 같음). 나머지는 최신화하지 않음
REFRESH_OK = ("SALE", "OUTOFSTOCK")


def ago(ts):
    """마지막 상태 확인이 얼마 전인지 (없으면 '확인 안 함')."""
    if not ts:
        return "확인 안 함"
    h = (time.time() - float(ts)) / 3600
    return f"{int(h * 60)}분 전" if h < 1 else f"{int(h)}시간 전" if h < 48 else f"{int(h // 24)}일 전"


def label(status):
    return LABEL.get(status or "", status or "")


def product(it):
    """커머스API 상품 목록 한 개 → 필요한 값만."""
    from . import naver
    chs = it.get("channelProducts") or [{}]
    ch = next((c for c in chs if c.get("channelServiceType") in (None, "STOREFARM")), chs[0])
    sale = int(ch.get("salePrice") or 0)
    final = int(ch.get("discountedPrice") or sale or 0)
    return {"origin_no": str(it.get("originProductNo") or ch.get("originProductNo") or ""),
            "channel_no": str(ch.get("channelProductNo") or ""),
            "code": str(ch.get("sellerManagementCode") or it.get("sellerManagementCode") or "").strip(),
            "name": str(ch.get("name") or ""),
            "status": str(ch.get("statusType") or (it.get("originProduct") or {}).get("statusType") or ""),
            "disp": str(ch.get("channelProductDisplayStatusType") or ch.get("displayStatusType") or ""),
            "reg_at": naver.parse_time(ch.get("regDate")),
            "sale": sale, "final": final}


def check_store(db, store_id, client, on_wait=None, progress=None, should_stop=None):
    """그 스토어 판매 중 복사본의 네이버 상태·네이버 가격을 채운다. {checked, by {상태: 수}, gone, price_diff, store_products}"""
    items = {}
    n = 0
    for it in client.iter_products(on_wait=on_wait, on_page=lambda k, total: progress and progress(k, total, f"네이버 상품 목록 {k:,}/{total:,}")):
        p = product(it)
        if p["channel_no"]:
            items[p["channel_no"]] = p
        n += 1
        if should_stop and should_stop():
            raise RuntimeError("중단했습니다.")
    fake = getattr(client, "fake", False)
    rows = db.q("SELECT id, channel_no FROM listings WHERE store_id=? AND origin_no!='' AND channel_no!=''",
                (int(store_id),))
    now = time.time()
    out = {"checked": len(rows), "by": {}, "gone": 0, "price_diff": 0, "store_products": n}
    with db.tx() as c:
        for r in rows:
            p = items.get(r["channel_no"])
            if p is None:
                st, disp = ("SALE", "ON") if fake else ("GONE", "")   # 시연: 목록에 없는 건 판매 중으로
            else:
                st, disp = ("GONE", "") if p["status"] == "DELETE" else (p["status"], p["disp"])
            c.execute("UPDATE listings SET nv_status=?, nv_disp=?, nv_at=? WHERE id=?", (st, disp, now, r["id"]))
            out["by"][st] = out["by"].get(st, 0) + 1
            out["gone"] += st == "GONE"
            if p and p["final"] > 0:
                c.execute("UPDATE listings SET nv_price=? WHERE id=?", (p["final"], r["id"]))   # 네이버 손님 가격 (업스타 가격은 그대로)
    db.x("UPDATE stores SET nv_checked_at=?, nv_check_err='' WHERE id=?", (now, int(store_id)))
    from . import baseprice
    out["price_diff"] = len(baseprice.price_checks(db, store_id))
    return out


def due(db, store_id, cfg):
    """[최신화]·[다시 올리기] 전 자동 확인이 필요한가 (마지막 확인이 재사용 시간보다 오래됨) → (필요한가, 마지막 확인 시각, 시간)."""
    hours = max(0.0, float(cfg.get("nv_reuse_hours") if cfg.get("nv_reuse_hours") is not None else 6))
    st = db.one("SELECT nv_checked_at FROM stores WHERE id=?", (int(store_id),)) or {}
    at = st.get("nv_checked_at")
    return (not at or time.time() - float(at) > hours * 3600), at, hours


def summary(res):
    """check_store 결과 → 한 줄."""
    by = res.get("by") or {}
    parts = [f"{label(k)} {v:,}" for k, v in sorted(by.items(), key=lambda kv: -kv[1])]
    s = f"복사본 {res.get('checked', 0):,}개 확인 — " + (", ".join(parts) or "판매 중 복사본 없음")
    if res.get("price_diff"):
        s += f" · 네이버 가격이 업스타와 다른 것 {res['price_diff']:,}개 (복사본 화면 '가격 확인 필요')"
    return s
