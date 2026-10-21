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
    """이번 등록에 더할 금액. 새로 올라가는 모든 경우(처음 등록·최신화·다시 올리기)에 붙인다
    — 새 상품번호로 올라가면 다시 베껴 가기 쉬우므로. 설정에서 도둑방지를 끄면 하나도 안 붙고,
    복사할 때 '도둑방지로 올리기'를 끈 복사본도 안 붙는다."""
    if not cfg.get("bait_default", True) or not t.get("bait_want"):
        return 0
    if op not in ("create", "refresh", "reupload"):
        return 0
    return max(0, int(cfg.get("bait_amount") or 0))


def restore(db, ids, reason="직접 되돌림", progress=None, should_stop=None):
    """원래 가격으로 되돌린다 (네이버에 판매가만 바꿔 다시 보냄)."""
    if not ids:
        return {"restored": 0, "failed": 0, "errors": []}
    rows = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        rows += db.q(f"""SELECT id, store_id, origin_no, price, bait, sale_shown FROM listings
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
            # 판매가에서 도둑방지 금액만 뺀다 (즉시할인 금액은 그대로 → 표시 할인율이 처음 계산 그대로)
            clients[r["store_id"]].restore_price(r["origin_no"], shown=r["sale_shown"], minus=r["bait"])
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


def fix_restored(db, progress=None, should_stop=None):
    """예전 버그 바로잡기: 표시 할인이 있는 상품을 '원래 가격으로' 되돌릴 때 판매가를 할인 뒤 가격으로 넣어
    할인이 두 번 빠진 것(예: 30% → 42%)을 '판매가 - 즉시할인 = 복사본 가격'이 되게 고친다."""
    rows = db.q("""SELECT id, store_id, origin_no, price FROM listings
        WHERE bait_state='restored' AND origin_no!='' AND status='success' AND sale_shown IS NULL""")
    stores = {s["id"]: s for s in db.stores(with_secret=True)}
    clients = {}
    st = {"checked": 0, "fixed": 0, "failed": 0, "errors": []}
    for i, r in enumerate(rows, 1):
        if should_stop and should_stop():
            break
        try:
            if r["store_id"] not in clients:
                clients[r["store_id"]] = naver.make_client(stores[r["store_id"]])
            if clients[r["store_id"]].fix_final_price(r["origin_no"], r["price"]):
                st["fixed"] += 1
            st["checked"] += 1
        except Exception as e:  # noqa: BLE001
            st["failed"] += 1
            if len(st["errors"]) < 3:
                st["errors"].append(str(e)[:200])
        if progress:
            progress(i, len(rows), f"확인 {st['checked']}건 · 고침 {st['fixed']}건")
    return st


def stats(db):
    st = db.one("""SELECT SUM(bait_state='on' AND origin_no!='') AS on_, SUM(bait_state='restored') AS restored,
        SUM(bait_state='fail' AND origin_no!='') AS failed FROM listings""")
    return {"on": st["on_"] or 0, "restored": st["restored"] or 0, "failed": st["failed"] or 0}
