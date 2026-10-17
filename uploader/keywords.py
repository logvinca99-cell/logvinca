"""네이버에서 다른 판매자들이 쓴 키워드 모으기 → 재조합 새 단어로 쓴다.

원본마다:
  1. 상품명 앞 5단어로 네이버 쇼핑을 검색한다 (쇼핑 검색 API, 무료 하루 25,000회).
     같은 검색어 결과는 저장해 두고 다시 쓴다.
  2. 핵심 키워드: 앞 5단어 중 검색 결과 상품명에 가장 많이 나오는 단어 (결과의 네이버 카테고리 이름과
     겹치면 가산점). 원본 화면에서 직접 바꿀 수도 있다.
  3. 결과 상품명에서 단어를 뽑는다. 버리는 것:
       - 브랜드·제조사·쇼핑몰 이름(이 들어간 단어), '~몰·~샵·~스토어' 같은 가게 이름 꼴
       - 판매자 여러 곳(기본 3곳)이 함께 쓰지 않은 단어 · 결과의 일정 비율(기본 8%) 미만인 단어
       - 할인·당일발송 같은 판촉 문구, 한글이 아닌 것(숫자·영문·규격)
  4. 재조합 때 쓸 단어를 고를 때 (원본마다):
       - 속성 단어(우드·접이식·화이트·대형 등, 단어 사전의 '속성 단어')는 원본 상품명·옵션·상세설명에
         그 말이 있을 때만 쓴다 → '철제 책상'에 '우드'가 들어가지 않게.
       - 금지 단어·상표 단어·키워드 화면에서 끈 단어는 쓰지 않는다.
       - 많은 판매자가 쓴 순서(검색량을 받았으면 검색량도 반영).

검색량(선택): 네이버 검색광고 API 키를 넣으면 단어별 월간 검색량을 받아 순서에 반영한다.
"""

import base64
import hashlib
import hmac
import json
import math
import os
import re
import time
import zlib

from . import convert, lexicon, namegen

SHOP_API = "https://openapi.naver.com/v1/search/shop.json"
SEARCHAD_API = "https://api.searchad.naver.com"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kw_query (
    query TEXT PRIMARY KEY,
    data BLOB NOT NULL,          -- 검색 결과 (상품명·몰·브랜드·카테고리만, zlib json)
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS source_kw (
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    word TEXT NOT NULL,
    malls INTEGER NOT NULL,      -- 이 단어를 쓴 판매자 수
    share REAL NOT NULL,         -- 검색 결과 중 이 단어가 들어간 비율
    PRIMARY KEY (source_id, word)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS source_kw_word ON source_kw(word);
CREATE INDEX IF NOT EXISTS sources_core ON sources(core_kw);
CREATE TABLE IF NOT EXISTS kw_off (
    core TEXT NOT NULL,          -- '' 이면 모든 핵심 키워드에서 끔
    word TEXT NOT NULL,
    PRIMARY KEY (core, word)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS kw_volume (
    word TEXT PRIMARY KEY,
    pc INTEGER NOT NULL,
    mobile INTEGER NOT NULL,
    at REAL NOT NULL
);
"""

# 판촉·배송·후기 같은 말: 상품을 설명하지 않으므로 키워드로 쓰지 않음
PROMO = set("""
할인 특가 세일 초특가 최저가 대박 이벤트 사은품 증정 무료 당일 당일발송 당일출고 빠른배송 국내배송 무료배송 택배
오늘출발 오늘발송 로켓 핫딜 쿠폰 적립 인기 추천 베스트 신상 신제품 신상품 리뷰 후기 정품 인기상품 판매 판매중 재고
상품 제품 기획 한정 단독 최신 최신형 고급 프리미엄 국산 국내산 수입 해외 직구 구매 주문 배송 발송 출고 문의 선물
""".split())
SHOP_SUFFIX = ("몰", "샵", "스토어", "마켓", "상회", "상사", "컴퍼니", "공방", "닷컴", "코리아")


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def _pack(o):
    return zlib.compress(json.dumps(o, ensure_ascii=False).encode())


def _unpack(b):
    return json.loads(zlib.decompress(b))


_TAG = re.compile(r"<[^>]+>")


def query_for(name, n=5):
    toks = [re.sub(r"[^\w가-힣]", "", t) for t in namegen.tokens(name)]
    return " ".join([t for t in toks if t][:n])


# ───────────────────────── 네이버 쇼핑 검색

def search_shop(query, cid, secret, session, n=100):
    r = session.get(SHOP_API, params={"query": query, "display": min(100, n), "start": 1, "sort": "sim"},
                    headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret}, timeout=15)
    if r.status_code == 401:
        raise RuntimeError("네이버 검색 API 키가 맞지 않습니다 (developers.naver.com 애플리케이션의 Client ID/Secret).")
    if r.status_code == 429:
        raise RuntimeError("네이버 검색 API 하루 호출 한도를 넘었습니다. 내일 이어서 하세요.")
    r.raise_for_status()
    out = []
    for it in r.json().get("items", []):
        out.append({
            "t": _TAG.sub("", it.get("title") or ""),
            "m": it.get("mallName") or "",
            "b": it.get("brand") or "",
            "k": it.get("maker") or "",
            "c": [it.get(f"category{i}") or "" for i in (3, 4)],
        })
    return out


_FAKE_WORDS = ["사무용", "학생", "공부", "컴퓨터", "서재", "가정용", "다용도", "실내", "튼튼한", "간편", "원목", "우드",
               "접이식", "화이트", "블랙", "대형", "미니", "철제", "수납", "정리", "보관", "선반", "세트", "인테리어",
               "거실", "주방", "욕실", "캠핑", "휴대용", "효도의자", "왕자행거", "당일발송", "무료배송"]
_FAKE_MALLS = ["가나스토어", "다라몰", "마바샵", "사아마켓", "자차상회", "카타리빙", "파하홈", "리빙플러스", "하루공방",
               "모던하우스몰", "베스트리빙"]


def _fake_items(query):
    """시연 모드: 검색어마다 항상 같은 그럴듯한 결과."""
    import random
    rnd = random.Random(hashlib.md5(query.encode()).hexdigest())
    toks = query.split()
    core = toks[min(2, len(toks) - 1)] if toks else "상품"
    out = []
    for i in range(60):
        ws = [core] + rnd.sample(toks, min(len(toks), rnd.randint(1, 3))) + rnd.sample(_FAKE_WORDS, rnd.randint(2, 5))
        mall = rnd.choice(_FAKE_MALLS)
        if rnd.random() < 0.2:
            ws.insert(0, "한빛")  # 브랜드
        rnd.shuffle(ws)
        out.append({"t": " ".join(dict.fromkeys(ws)), "m": mall, "b": "한빛" if "한빛" in ws else "", "k": "",
                    "c": ["", core[-3:]]})
    return out


# ───────────────────────── 핵심 키워드, 단어 뽑기

def detect_core(name, items, lex=None, n=5):
    """앞 n단어 중 검색 결과 상품명에 가장 많이 나오는 단어. 결과가 없으면 앞 3단어 중 속성이 아닌 마지막 한글 단어."""
    toks = [t for t in namegen.tokens(name)[:n] if re.search(r"[가-힣]{2,}", t)]
    if not toks:
        return (namegen.tokens(name) or [""])[0]
    if items:
        titles = [namegen.normalize(it["t"]) for it in items]
        cats = [namegen.normalize(c) for it in items for c in it.get("c") or [] if c]
        best, score = toks[0], -1.0
        for i, t in enumerate(toks):
            nt = namegen.normalize(t)
            if len(nt) < 2 or lexicon.is_attr(t, lex) or t in PROMO:
                continue
            s = sum(1 for x in titles if nt in x) / len(titles)
            if cats and sum(1 for c in cats if c and (c in nt or nt in c)) >= len(cats) * 0.3:
                s += 0.5  # 네이버 카테고리 이름과 겹침 → 상품 자체를 가리키는 말일 가능성이 큼
            s -= i * 0.01  # 비슷하면 앞 단어
            if s > score:
                best, score = t, s
        return best
    head = [t for t in toks[:3] if not lexicon.is_attr(t, lex) and t not in PROMO]
    return head[-1] if head else toks[0]


def _brand_names(items):
    out = set()
    for it in items:
        for k in ("m", "b", "k"):
            v = namegen.normalize(it.get(k))
            if len(v) >= 2:
                out.add(v)
    return out


def extract(items, name, cfg, lex=None):
    """검색 결과 상품명에서 다른 판매자들이 공통으로 쓴 단어 [(단어, 판매자 수, 비율)]."""
    if not items:
        return []
    min_malls = int(cfg.get("kw_min_malls") or 3)
    min_share = float(cfg.get("kw_min_share") or 0.08)
    brands = _brand_names(items)
    have = {namegen.normalize(t) for t in namegen.tokens(name)}
    malls, hits = {}, {}
    for it in items:
        seen = set()
        for raw in re.split(r"[\s/,\[\]()+|·]+", it["t"]):
            w = re.sub(r"[^가-힣]", "", raw) if re.fullmatch(r"[가-힣]+[^\w]*", raw) else ""
            if not (2 <= len(w) <= 10) or w in seen:
                continue
            seen.add(w)
            hits[w] = hits.get(w, 0) + 1
            malls.setdefault(w, set()).add(it.get("m") or it["t"])
    out = []
    for w, n in hits.items():
        nw = namegen.normalize(w)
        if nw in have or w in PROMO or w.endswith(SHOP_SUFFIX):
            continue
        if any(b in nw or nw in b for b in brands if len(b) >= 2):
            continue
        share = n / len(items)
        if len(malls[w]) < min_malls or share < min_share:
            continue
        if lex and lexicon.blocked_in(w, lex):
            continue
        out.append((w, len(malls[w]), round(share, 3)))
    out.sort(key=lambda x: (-x[1], -x[2]))
    return out[:40]


def original_text(name, row):
    """속성 확인용: 원본 상품명 + 옵션 + 상세설명 글자 + 태그."""
    parts = [name]
    o = convert.options(row)
    if o:
        parts.append(json.dumps(o, ensure_ascii=False))
    d = str(row.get("상세설명") or "")
    parts.append(_TAG.sub(" ", d)[:5000])
    parts.append(str(row.get("상품태그") or ""))
    return " ".join(parts)


# ───────────────────────── 모으기 (작업)

def _volume_score(v):
    if not v:
        return 1.0
    return 1.0 + math.log10(1 + (v["pc"] + v["mobile"])) / 3


def todo_ids(db, cfg, ids=None, limit=None):
    fresh = time.time() - int(cfg.get("kw_refresh_days") or 60) * 86400
    if ids:
        return list(ids)[: limit or None]
    rows = db.q("""SELECT id FROM sources WHERE valid=1 AND (kw_at IS NULL OR kw_at<?)
        ORDER BY (kw_at IS NOT NULL), n_listings < 3 DESC, id LIMIT ?""", (fresh, limit or 10 ** 9))
    return [r["id"] for r in rows]


def collect(db, cfg, ids=None, progress=None, should_stop=None):
    """원본들의 키워드를 모은다 (같은 검색어는 저장해 둔 결과를 다시 씀)."""
    import requests
    fake = os.environ.get("UPLOADER_FAKE_API") == "1"
    cid, secret = (cfg.get("naver_client_id") or "").strip(), (cfg.get("naver_client_secret") or "").strip()
    if not (cid and secret) and not fake:
        raise RuntimeError("설정 → 네이버 키워드에서 네이버 검색 API 키(Client ID/Secret)를 먼저 넣어 주세요 (developers.naver.com).")
    lex = lexicon.get(db)
    limit = int(cfg.get("kw_daily_limit") or 1000)
    todo = todo_ids(db, cfg, ids)
    fresh = time.time() - int(cfg.get("kw_refresh_days") or 60) * 86400
    s = requests.Session()
    stats = {"sources": 0, "api_calls": 0, "cached": 0, "words": 0, "errors": 0, "error": ""}
    for i, sid in enumerate(todo, 1):
        if should_stop and should_stop():
            break
        src = db.one("SELECT id, name, core_kw, core_manual FROM sources WHERE id=?", (sid,))
        if not src:
            continue
        q = query_for(src["name"], int(cfg.get("core_scan_words") or 5))
        cached = db.one("SELECT data FROM kw_query WHERE query=? AND fetched_at>?", (q, fresh))
        if cached:
            items = _unpack(cached["data"])
            stats["cached"] += 1
        else:
            if stats["api_calls"] >= limit:
                break
            try:
                items = _fake_items(q) if fake else search_shop(q, cid, secret, s, int(cfg.get("kw_results") or 100))
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                stats["error"] = str(e)[:200]
                if "한도" in str(e) or "맞지 않" in str(e) or (stats["errors"] >= 5 and not stats["sources"]):
                    raise RuntimeError(str(e)) if not stats["sources"] else RuntimeError(
                        f"{stats['sources']}개 모은 뒤 멈춤: {e}")
                continue
            stats["api_calls"] += 1
            db.x("INSERT OR REPLACE INTO kw_query(query, data, fetched_at) VALUES(?,?,?)", (q, _pack(items), time.time()))
            if not fake:
                time.sleep(0.1)
        core = src["core_kw"] if src["core_manual"] and src["core_kw"] else detect_core(src["name"], items, lex)
        words = extract(items, src["name"], cfg, lex)
        with db.tx() as c:
            c.execute("DELETE FROM source_kw WHERE source_id=?", (sid,))
            c.executemany("INSERT INTO source_kw(source_id, word, malls, share) VALUES(?,?,?,?)",
                          [(sid, w, m, sh) for w, m, sh in words])
            c.execute("UPDATE sources SET core_kw=?, kw_at=? WHERE id=?", (core, time.time(), sid))
        stats["sources"] += 1
        stats["words"] += len(words)
        if progress:
            progress(i, len(todo), f"{src['name'][:20]} → 핵심 '{core}', 단어 {len(words)}개")
    if (cfg.get("searchad_api_key") and cfg.get("searchad_secret") and cfg.get("searchad_customer_id")) or fake:
        try:
            stats["volumes"] = fetch_volumes(db, cfg, should_stop=should_stop)
        except Exception as e:  # noqa: BLE001
            stats["volume_error"] = str(e)[:200]
    return stats


# ───────────────────────── 검색량 (검색광고 API, 선택)

def _searchad_headers(cfg, method, uri):
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(cfg["searchad_secret"].encode(), f"{ts}.{method}.{uri}".encode(),
                                    hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": cfg["searchad_api_key"], "X-Customer": str(cfg["searchad_customer_id"]),
            "X-Signature": sig}


def _cnt(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 5  # '< 10'


def fetch_volumes(db, cfg, words=None, should_stop=None, limit=2000):
    """검색량을 모르는 단어(핵심 키워드 포함)의 월간 검색량을 받는다. 한 번에 5단어."""
    import requests
    fake = os.environ.get("UPLOADER_FAKE_API") == "1"
    if words is None:
        words = [r["w"] for r in db.q("""SELECT DISTINCT word AS w FROM source_kw WHERE word NOT IN (SELECT word FROM kw_volume)
            UNION SELECT DISTINCT core_kw FROM sources WHERE core_kw!='' AND core_kw NOT IN (SELECT word FROM kw_volume)
            LIMIT ?""", (limit,))]
    s = requests.Session()
    got = 0
    for i in range(0, len(words), 5):
        if should_stop and should_stop():
            break
        chunk = [w.replace(" ", "") for w in words[i:i + 5] if w]
        if fake:
            res = {w: (int(hashlib.md5(w.encode()).hexdigest()[:4], 16) % 3000,
                       int(hashlib.md5(w.encode()).hexdigest()[4:8], 16) % 20000) for w in chunk}
        else:
            r = s.get(SEARCHAD_API + "/keywordstool", params={"hintKeywords": ",".join(chunk), "showDetail": 1},
                      headers=_searchad_headers(cfg, "GET", "/keywordstool"), timeout=15)
            if r.status_code in (401, 403):
                raise RuntimeError("검색광고 API 키가 맞지 않습니다 (searchad.naver.com → 도구 → API 사용 관리).")
            r.raise_for_status()
            res = {}
            for k in r.json().get("keywordList", []):
                if k.get("relKeyword") in chunk:
                    res[k["relKeyword"]] = (_cnt(k.get("monthlyPcQcCnt")), _cnt(k.get("monthlyMobileQcCnt")))
            time.sleep(0.25)
        with db.tx() as c:
            for w in chunk:
                pc, mo = res.get(w, (0, 0))
                c.execute("INSERT OR REPLACE INTO kw_volume(word, pc, mobile, at) VALUES(?,?,?,?)", (w, pc, mo, time.time()))
                got += 1
    return got


# ───────────────────────── 재조합에 넘길 단어

def words_for(db, sources, cfg, lex=None):
    """{source_id: (핵심 키워드, [새 단어 후보…])}. sources: id, name, core_kw(선택), data(선택) 가 있는 행들."""
    if not sources:
        return {}
    lex = lex or lexicon.get(db)
    ids = [s["id"] for s in sources] if cfg.get("use_naver_keywords", True) else []
    rows = {}
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        for r in db.q(f"""SELECT k.source_id, k.word, k.malls, k.share, v.pc, v.mobile FROM source_kw k
                LEFT JOIN kw_volume v ON v.word=k.word WHERE k.source_id IN ({','.join('?' * len(chunk))})""", chunk):
            rows.setdefault(r["source_id"], []).append(r)
    off = {}
    for r in db.q("SELECT core, word FROM kw_off"):
        off.setdefault(r["core"], set()).add(r["word"])
    max_n = int(cfg.get("kw_max_words") or 15)
    out = {}
    for s in sources:
        core = s.get("core_kw") or detect_core(s["name"], None, lex)  # 아직 안 모았으면 앞 단어로 대충
        cand = rows.get(s["id"], [])
        if not cand:
            out[s["id"]] = (core, [])
            continue
        text = None
        dead = off.get("", set()) | off.get(core, set())
        picked = []
        for r in sorted(cand, key=lambda r: -(r["malls"] * _volume_score(
                {"pc": r["pc"], "mobile": r["mobile"]} if r["pc"] is not None else None))):
            w = r["word"]
            if w in dead or not lex.ok_new_word(w):
                continue
            attrs = lexicon.attrs_in(w, lex)
            if attrs:
                if text is None:
                    text = namegen.normalize(original_text(s["name"], _row(db, s)))
                if not all(namegen.normalize(a) in text for a in attrs):
                    continue  # 원본에 없는 속성 (예: 철제 책상에 '우드')
            picked.append(w)
            if len(picked) >= max_n:
                break
        out[s["id"]] = (core, picked)
    return out


def _row(db, s):
    if s.get("_row") is not None:
        return s["_row"]
    if s.get("data") is not None:
        from .db import unpack
        return unpack(s["data"])
    r = db.one("SELECT data FROM sources WHERE id=?", (s["id"],))
    from .db import unpack
    return unpack(r["data"]) if r else {}
