"""눈검수: 판매 불가 상품을 내 눈으로 걸러내고, 통과하지 않은 원본은 어떤 길로도 등록되지 않게 막는다.

원본마다 review: wait(검수 대기) / pass(통과) / reject(제외).
  - 새로 불러온 원본은 wait. 같은 원본을 다시 불러왔는데 상품명·카테고리·썸네일 목록이 바뀌었으면 다시 wait.
  - 등록 계획(create_plan)과 실제 등록 직전(engine)에서 두 번 확인 → pass가 아니면 등록하지 않음.

검수 화면: wait 원본을 카테고리 순으로 그리드에 깔고, 수상한 것만 클릭해 제외 → Space로 나머지 통과.
함정 카드: 이미 제외한 원본을 약 50장에 1장꼴로 몰래 섞는다. 놓치면 그 페이지를 다시 보게 한다(저장하지 않음).
미탐 방지가 목적이라 함정의 원래 판정(reject)은 절대 바꾸지 않는다.
"""

import hashlib
import json
import random
import threading
import time
import uuid

from . import config, convert

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_sessions (
    id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at REAL,
    seen INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    traps INTEGER NOT NULL DEFAULT 0,
    trap_hits INTEGER NOT NULL DEFAULT 0,
    missed_pages INTEGER NOT NULL DEFAULT 0,
    seconds REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sources_review ON sources(review, category);
"""

DEFAULT_CAUTIONS = """낚시: 투망·통발·작살·전기 어구 등 어획 어구
공구: 타정총·네일건
호신: 전기충격기·가스총
완구: 캐릭터·브랜드 로고
의류: 캐릭터·브랜드 로고
잡화: 캐릭터·브랜드 로고"""

_pages = {}          # 페이지 번호 → {ids, traps, session}: 함정이 어느 카드인지는 화면에 보내지 않는다
_lock = threading.Lock()


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def signature(row):
    """검수할 때 본 것: 상품명 + 카테고리 + 썸네일 목록. 다시 불러왔을 때 이게 바뀌면 다시 검수."""
    s = json.dumps([str(row.get("상품명") or "").strip(), str(row.get("카테고리") or "").strip(),
                    convert.thumbnails(row)], ensure_ascii=False)
    return hashlib.md5(s.encode()).hexdigest()


def cautions(cfg):
    """설정의 '카테고리 단어: 주의 문구' 줄들 → [(단어, 문구)]."""
    out = []
    for line in str(cfg.get("review_cautions") or DEFAULT_CAUTIONS).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip():
                out.append((k.strip(), v.strip()))
    return out


def is_risky(category, cfg):
    words = [w.strip() for w in str(cfg.get("review_risk_cats") or "").split(",") if w.strip()]
    return any(w in category for w in words)


def _leaf(category):
    parts = [p.strip() for p in str(category or "").split(">") if p.strip()]
    return parts[-1] if parts else ""


def _card(r):
    return {"id": r["id"], "thumb": r["thumb"], "leaf": _leaf(r["category"]), "head": r["name"][:4],
            "name": r["name"], "category": r["category"]}


def start_session(db):
    return db.x("INSERT INTO review_sessions(started_at) VALUES(?)", (time.time(),))


def counts(db):
    r = db.one("""SELECT SUM(review='wait') AS wait, SUM(review='pass') AS pass_, SUM(review='reject') AS reject
        FROM sources""")
    live_reject = db.one("""SELECT COUNT(*) AS n FROM listings l JOIN sources s ON s.id=l.source_id
        WHERE s.review='reject' AND l.origin_no!='' AND l.status NOT IN ('deleted')""")["n"]
    last = db.one("""SELECT SUM(traps) AS t, SUM(trap_hits) AS h FROM (SELECT traps, trap_hits FROM review_sessions
        WHERE traps>0 ORDER BY id DESC LIMIT 10)""")
    return {"wait": r["wait"] or 0, "pass": r["pass_"] or 0, "reject": r["reject"] or 0, "live_reject": live_reject,
            "trap_rate": (last["h"] / last["t"]) if last and last["t"] else None, "trap_total": (last or {}).get("t") or 0}


def next_page(db, session_id, exclude=()):
    """검수 대기 원본을 카테고리 순으로 한 페이지. 위험 카테고리면 적게(카드 크게), 아니면 많이."""
    cfg = config.load()
    risk_n = max(4, int(cfg.get("review_risk_size") or 12))
    norm_n = max(4, int(cfg.get("review_normal_size") or 24))
    ex = list(exclude)
    rows = db.q(f"""SELECT id, name, category, thumb FROM sources WHERE review='wait'
        {"AND id NOT IN (" + ",".join("?" * len(ex)) + ")" if ex else ""}
        ORDER BY category, id LIMIT ?""", (*ex, norm_n * 2))
    if not rows:
        return None
    risky = is_risky(rows[0]["category"], cfg)
    size = risk_n if risky else norm_n
    page = []
    for r in rows:
        if len(page) >= size or is_risky(r["category"], cfg) != risky:
            break
        page.append(r)
    nxt = rows[len(page):len(page) + size]
    # 함정 카드: 이미 제외한 원본 중에서 약 rate장에 1장꼴
    rate = max(0, int(cfg.get("review_trap_rate") or 50))
    traps = []
    has_rejects = bool(db.one("SELECT 1 FROM sources WHERE review='reject' LIMIT 1"))
    if rate and has_rejects:
        n = sum(1 for _ in page if random.random() < 1 / rate)
        if n:
            traps = db.q("SELECT id, name, category, thumb FROM sources WHERE review='reject' ORDER BY RANDOM() LIMIT ?",
                         (n,))
    cards = [_card(r) for r in page]
    for t in traps:
        cards.insert(random.randint(0, len(cards)), _card(t))
    pid = uuid.uuid4().hex
    with _lock:
        _pages[pid] = {"ids": [c["id"] for c in cards], "traps": {t["id"] for t in traps}, "session": session_id,
                       "real": [r["id"] for r in page], "at": time.time()}
        if len(_pages) > 200:
            for k in sorted(_pages, key=lambda k: _pages[k]["at"])[:100]:
                _pages.pop(k, None)
    cats = {r["category"] for r in page}
    notes = [f"{k} → {v}" for k, v in cautions(cfg) if any(k in c for c in cats)]
    return {"page_id": pid, "cards": cards, "risky": risky, "cautions": notes, "has_traps": has_rejects and rate > 0,
            "prefetch": [r["thumb"] for r in nxt if r["thumb"]],
            "remaining": db.one("SELECT COUNT(*) AS n FROM sources WHERE review='wait'")["n"]}


def _save(db, ids, rejected):
    """판정 저장 (그때의 내용 서명도 같이)."""
    now = time.time()
    rows = db.q(f"SELECT id, data FROM sources WHERE id IN ({','.join('?' * len(ids))})", ids) if ids else []
    from .db import unpack
    with db.tx() as c:
        for r in rows:
            c.execute("UPDATE sources SET review=?, reviewed_at=?, review_sig=? WHERE id=?",
                      ("reject" if r["id"] in rejected else "pass", now, signature(unpack(r["data"])), r["id"]))


def submit(db, page_id, rejected):
    """페이지 판정. 함정을 놓쳤으면 아무것도 저장하지 않고 missed를 돌려준다(같은 페이지를 다시 검수)."""
    with _lock:
        p = _pages.get(page_id)
    if not p:
        raise ValueError("페이지 정보가 없습니다 (프로그램을 다시 켰다면 이 페이지를 다시 받으세요).")
    rejected = {int(i) for i in rejected} & set(p["ids"])
    missed = [t for t in p["traps"] if t not in rejected]
    sess = p["session"]
    if missed:
        if sess:
            db.x("UPDATE review_sessions SET missed_pages=missed_pages+1 WHERE id=?", (sess,))
        return {"ok": False, "missed": len(missed)}
    real = p["real"]
    rej_real = rejected - p["traps"]
    _save(db, real, rej_real)
    if sess:
        db.x("""UPDATE review_sessions SET seen=seen+?, passed=passed+?, rejected=rejected+?, traps=traps+?,
            trap_hits=trap_hits+?, ended_at=?, seconds=?-started_at WHERE id=?""",
             (len(real), len(real) - len(rej_real), len(rej_real), len(p["traps"]), len(p["traps"]),
              time.time(), time.time(), sess))
    with _lock:
        _pages.pop(page_id, None)
    return {"ok": True, "passed": len(real) - len(rej_real), "rejected": len(rej_real), "ids": real}


def cards(db, ids):
    """되돌리기(Z)·제외 다시 보기: 이미 판정한 원본들을 지금 판정과 함께."""
    if not ids:
        return []
    rows = db.q(f"SELECT id, name, category, thumb, review FROM sources WHERE id IN ({','.join('?' * len(ids))})", ids)
    by = {r["id"]: r for r in rows}
    return [{**_card(by[i]), "review": by[i]["review"]} for i in ids if i in by]


def set_review(db, ids, rejected):
    """다시 본 페이지나 원본 화면에서 직접 바꾼 판정 저장 (함정 없음)."""
    _save(db, [int(i) for i in ids], {int(i) for i in rejected})


def session(db, sid):
    return db.one("SELECT * FROM review_sessions WHERE id=?", (sid,))
