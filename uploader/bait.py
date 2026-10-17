"""도둑방지: 처음 올릴 때 가격을 일부러 높여 두었다가(기본 +30,000원) 직접 원래 가격으로 되돌린다.

내 상품을 그대로 베껴 몇천 원 싸게 올리는 판매자는 '높여 둔 가격'을 기준으로 내리게 되고,
내가 원래 가격으로 되돌리면 그쪽보다 싸진다. 되돌리는 때는 방문자 수 등을 보고 직접 정한다(버튼).

- 등록 계획 때 '도둑방지로 올리기'가 기본으로 켜져 있고, 끌 수 있다 (복사본마다 기억: listings.bait_want).
- 금액은 판매가에 그대로 더하기만 한다. 즉시할인 금액은 도둑방지 전 가격으로 계산하므로
  원래 가격으로 되돌리면 할인·마진이 처음 정한 그대로가 된다.
"""

import time

from . import naver


def applies(cfg, t, op):
    """이번 등록에 더할 금액. 계획 때 켠 복사본만, 처음 올릴 때만 (설정하면 최신화 때도)."""
    if not t.get("bait_want"):
        return 0
    first = op == "create" and int(t.get("round") or 1) == 1
    if not first and not cfg.get("bait_on_refresh"):
        return 0
    return max(0, int(cfg.get("bait_amount") or 0))


def restore(db, ids, reason="직접 되돌림", progress=None, should_stop=None):
    """원래 가격으로 되돌린다 (네이버에 판매가만 바꿔 다시 보냄)."""
    if not ids:
        return {"restored": 0, "failed": 0, "errors": []}
    rows = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        rows += db.q(f"""SELECT id, store_id, origin_no, price, bait FROM listings
            WHERE id IN ({','.join('?' * len(chunk))}) AND bait_state IN ('on','fail') AND origin_no!=''""", chunk)
    stores = {s["id"]: s for s in db.stores(with_secret=True)}
    clients = {}
    stats = {"restored": 0, "failed": 0, "errors": []}
    for i, r in enumerate(rows, 1):
        if should_stop and should_stop():
            break
        try:
            if r["store_id"] not in clients:
                clients[r["store_id"]] = naver.make_client(stores[r["store_id"]])
            clients[r["store_id"]].update_sale_price(r["origin_no"], r["price"])
            db.x("""UPDATE listings SET bait_state='restored', bait=0, bait_note=?, bait_restored_at=?, updated_at=?
                WHERE id=?""", (reason, time.time(), time.time(), r["id"]))
            stats["restored"] += 1
        except Exception as e:  # noqa: BLE001
            db.x("UPDATE listings SET bait_state='fail', bait_note=? WHERE id=?", (f"되돌리기 실패: {e}"[:300], r["id"]))
            stats["failed"] += 1
            if len(stats["errors"]) < 3:
                stats["errors"].append(str(e)[:200])
        if progress:
            progress(i, len(rows), f"원래 가격으로 {stats['restored']}건")
    return stats


def stats(db):
    st = db.one("""SELECT SUM(bait_state='on' AND origin_no!='') AS on_, SUM(bait_state='restored') AS restored,
        SUM(bait_state='fail' AND origin_no!='') AS failed FROM listings""")
    return {"on": st["on_"] or 0, "restored": st["restored"] or 0, "failed": st["failed"] or 0}
