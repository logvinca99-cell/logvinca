"""복사본의 네이버 상태 (스토어처럼 판매 중·품절·판매중지·판매금지… 구분).

스토어 상품 목록(커머스API products/search, 한 번에 500개)을 끝까지 받아 판매 중 복사본마다
판매 상태·전시 상태를 적는다. 가져온 복사본(가격 고정)은 지금 손님 가격도 맞춘다
(판매자센터에서 가격을 바꿨어도 최신화 때 그 가격 그대로).
최신화 직전에 엔진이 스토어마다 한 번 하고, 복사본 화면 '네이버 상태 확인'으로 언제든 한다.
"""
import time

# 판매 상태 (statusType)
LABEL = {"SALE": "판매 중", "OUTOFSTOCK": "품절", "SUSPENSION": "판매중지", "PROHIBITION": "판매금지",
         "WAIT": "판매 대기", "CLOSE": "판매 종료", "UNADMISSION": "승인 대기", "REJECTION": "승인 거부",
         "DELETE": "스토어에 없음", "GONE": "스토어에 없음"}
# 최신화해도 되는 상태 (지우고 새로 올려도 손님이 보던 상태와 같음). 나머지는 최신화하지 않음
REFRESH_OK = ("SALE", "OUTOFSTOCK")


def label(status):
    return LABEL.get(status or "", status or "")


def product(it):
    """커머스API 상품 목록 한 개 → 필요한 값만."""
    from . import naver
    chs = it.get("channelProducts") or [{}]
    ch = next((c for c in chs if c.get("channelServiceType") in (None, "STOREFARM")), chs[0])
    sale = int(ch.get("salePrice") or 0)
    final = int(ch.get("discountedPrice") or sale or 0)
    mobile = int(ch.get("mobileDiscountedPrice") or 0)
    return {"origin_no": str(it.get("originProductNo") or ch.get("originProductNo") or ""),
            "channel_no": str(ch.get("channelProductNo") or ""),
            "code": str(ch.get("sellerManagementCode") or it.get("sellerManagementCode") or "").strip(),
            "name": str(ch.get("name") or ""),
            "status": str(ch.get("statusType") or (it.get("originProduct") or {}).get("statusType") or ""),
            "disp": str(ch.get("channelProductDisplayStatusType") or ch.get("displayStatusType") or ""),
            "reg_at": naver.parse_time(ch.get("regDate")),
            "sale": sale, "final": final,
            "mobile": mobile if 0 < mobile < final else 0}   # 모바일에서만 더 싼 값 (최신화하면 사라짐)


def check_store(db, store_id, client, on_wait=None, progress=None, should_stop=None):
    """그 스토어 판매 중 복사본의 네이버 상태를 채운다. {checked, by {상태: 수}, gone, repriced, store_products}"""
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
    rows = db.q("SELECT id, channel_no, price, price_fixed FROM listings WHERE store_id=? AND origin_no!='' AND channel_no!=''",
                (int(store_id),))
    now = time.time()
    out = {"checked": len(rows), "by": {}, "gone": 0, "repriced": 0, "store_products": n}
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
            if r["price_fixed"] and p and p["final"] > 0 and p["final"] != r["price"]:
                c.execute("UPDATE listings SET price=? WHERE id=?", (p["final"], r["id"]))   # 판매자센터에서 바꾼 손님 가격
                out["repriced"] += 1
    return out


def summary(res):
    """check_store 결과 → 한 줄."""
    by = res.get("by") or {}
    parts = [f"{label(k)} {v:,}" for k, v in sorted(by.items(), key=lambda kv: -kv[1])]
    s = f"복사본 {res.get('checked', 0):,}개 확인 — " + (", ".join(parts) or "판매 중 복사본 없음")
    if res.get("repriced"):
        s += f" · 판매자센터에서 바뀐 가격 {res['repriced']:,}개 반영(가격 고정)"
    return s
