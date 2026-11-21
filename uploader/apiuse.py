"""스토어별 네이버 API 사용량·시간당 한도 멈춤.

- 네이버로 가는 요청마다 (스토어, 종류, 결과)를 시간 단위로 센다 (api_usage, 7일 보관).
  종류: 등록 · 지우기 · 이미지 · 상품 목록(네이버 상태 확인·연결 확인) · 반영(읽기·고치기 — 가격·상품명·상세·정보) · 기타 · 토큰.
- 한도(429 GW.QUOTA_LIMIT)에 걸리면 그 스토어는 한도가 풀릴 때까지(기본 60분) 어떤 요청도 보내지 않는다 (QuotaPaused).
  다른 스토어는 그대로. 풀리면 엔진이 그때 남은 그 스토어 작업을 한 번 이어서 한다 (설정 quota_auto_resume).
"""

import threading
import time

PAUSE_SEC = 3600            # 한도에 걸리면 이만큼 그 스토어로 보내지 않음
KEEP_DAYS = 7
KINDS = ("등록", "지우기", "이미지", "상품 목록", "반영", "기타", "토큰")

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_usage (
    store_id INTEGER NOT NULL,
    hour INTEGER NOT NULL,          -- 시각(초) // 3600
    kind TEXT NOT NULL,
    n INTEGER NOT NULL DEFAULT 0,   -- 보낸 요청 수
    quota INTEGER NOT NULL DEFAULT 0,   -- 그중 한도 거절(429 QUOTA)
    PRIMARY KEY (store_id, hour, kind)
);
"""

_db = None
_lock = threading.Lock()
_quota = {}          # 스토어 번호 → 한도가 풀리는 시각


class QuotaPaused(Exception):
    """이 스토어는 시간당 한도에 걸려 잠시 멈춤 (요청을 보내지 않음)."""

    def __init__(self, store_id, until):
        self.store_id, self.until = store_id, until
        super().__init__(f"이 스토어 API 애플리케이션의 시간당 요청 한도를 다 씀 — {hm(until)} 이후 자동으로 이어서 "
                         f"(그때까지 이 스토어로는 네이버에 요청을 보내지 않음)")


def hm(ts):
    return time.strftime("%H:%M", time.localtime(ts or 0))


def ensure(db):
    global _db
    _db = db
    with db.tx() as c:
        c.executescript(SCHEMA)
        c.execute("DELETE FROM api_usage WHERE hour < ?", (int(time.time() // 3600) - KEEP_DAYS * 24,))
    try:
        for r in db.q("SELECT id, quota_until FROM stores WHERE quota_until IS NOT NULL"):
            if r["quota_until"] and r["quota_until"] > time.time():
                _quota[r["id"]] = r["quota_until"]
    except Exception:  # noqa: BLE001 - 칸이 아직 없을 때
        pass


def kind_of(method, path):
    m, p = (method or "").upper(), path or ""
    if "/oauth2/token" in p:
        return "토큰"
    if "/product-images/upload" in p:
        return "이미지"
    if p.startswith("/v2/products") and m == "POST":
        return "등록"
    if "/origin-products/" in p and m == "DELETE":
        return "지우기"
    if "/products/search" in p:
        return "상품 목록"
    if "/origin-products/" in p:
        return "반영"
    return "기타"


def until(store_id):
    """한도가 풀리는 시각 (안 걸렸으면 None)."""
    u = _quota.get(store_id)
    if u and u > time.time():
        return u
    return None


def check(store_id):
    """보내기 전: 한도로 멈춘 스토어면 QuotaPaused."""
    if store_id is None:
        return
    u = until(store_id)
    if u:
        raise QuotaPaused(store_id, u)


def hit_quota(store_id, sec=PAUSE_SEC):
    """한도에 걸림 → 그 스토어 멈춤 (DB에도 남김 — 껐다 켜도 이어서)."""
    if store_id is None:
        return None
    u = time.time() + sec
    with _lock:
        _quota[store_id] = max(_quota.get(store_id) or 0, u)
        u = _quota[store_id]
    if _db is not None:
        try:
            _db.x("UPDATE stores SET quota_until=? WHERE id=?", (u, store_id))
        except Exception:  # noqa: BLE001
            pass
    return u


def clear(store_id):
    with _lock:
        _quota.pop(store_id, None)
    if _db is not None:
        try:
            _db.x("UPDATE stores SET quota_until=NULL WHERE id=?", (store_id,))
        except Exception:  # noqa: BLE001
            pass


def record(store_id, kind, status=200):
    """요청 하나를 센다 (보낸 뒤)."""
    if store_id is None or _db is None:
        return
    q = 1 if status == 429 else 0
    try:
        _db.x("""INSERT INTO api_usage(store_id, hour, kind, n, quota) VALUES(?,?,?,1,?)
            ON CONFLICT(store_id, hour, kind) DO UPDATE SET n=n+1, quota=quota+excluded.quota""",
              (int(store_id), int(time.time() // 3600), kind, q))
    except Exception:  # noqa: BLE001 - 세기 실패는 무시
        pass


def recent(db, store_id=None, hours=1):
    """최근 hours시간(지금 시간대 포함 — 1이면 지금과 바로 앞 시간대 중 60분 안쪽이 아니라, 지금 시간대와 앞 시간대 합)
    → {store_id: {"total", "quota", "by": {종류: n}}}. 토큰은 total에서 뺌(따로 by에만)."""
    h0 = int(time.time() // 3600) - max(1, int(hours)) + 1
    w, a = "hour >= ?", [h0]
    if store_id:
        w += " AND store_id=?"
        a.append(int(store_id))
    out = {}
    for r in db.q(f"SELECT store_id, kind, SUM(n) AS n, SUM(quota) AS q FROM api_usage WHERE {w} GROUP BY store_id, kind", a):
        s = out.setdefault(r["store_id"], {"total": 0, "quota": 0, "by": {}})
        s["by"][r["kind"]] = r["n"]
        if r["kind"] != "토큰":
            s["total"] += r["n"]
        s["quota"] += r["q"] or 0
    for sid, s in out.items():
        u = until(sid)
        s["quota_until"] = u
    return out


def hourly(db, store_id, hours=24):
    """그 스토어 시간대별 사용량 (최근 hours시간) → [{hour, label, total, quota, by}]"""
    h1 = int(time.time() // 3600)
    h0 = h1 - hours + 1
    rows = db.q("SELECT hour, kind, n, quota FROM api_usage WHERE store_id=? AND hour>=? ORDER BY hour", (int(store_id), h0))
    by = {}
    for r in rows:
        d = by.setdefault(r["hour"], {"hour": r["hour"], "label": time.strftime("%m/%d %H시", time.localtime(r["hour"] * 3600)),
                                      "total": 0, "quota": 0, "by": {}})
        d["by"][r["kind"]] = r["n"]
        if r["kind"] != "토큰":
            d["total"] += r["n"]
        d["quota"] += r["quota"] or 0
    return [by[h] for h in sorted(by, reverse=True)]
