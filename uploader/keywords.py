"""네이버 검색광고 API(연관 키워드·검색량)로 핵심 키워드를 찾고, 재조합 새 단어를 모은다.

(네이버 쇼핑 검색 API는 2026년 7월 종료되어 쓰지 않는다.)

원본마다:
  1. 핵심 키워드: 상품명 앞 5단어 중 월간 검색량이 가장 큰 단어 (속성·판촉 단어 제외).
     원본 화면에서 직접 고치면 그 단어를 기억해(core_learn) 같은 단어가 나오는 다른 원본에도 쓴다.
  2. 핵심 키워드의 연관 키워드(검색광고 키워드 도구)에서 핵심 키워드가 들어간 것만 보고,
     핵심 키워드를 뺀 나머지 말을 새 단어 후보로 쓴다.  예) 핵심 '책상' → 컴퓨터책상 → '컴퓨터', 학생책상 → '학생'
     같은 핵심 키워드의 결과는 저장해 두고 다시 쓴다 (원본이 많아도 핵심 키워드 수만큼만 묻는다).
  3. 버리는 것: 검색량이 적은 것(기본 월 30 미만), 판촉 문구, 가게 이름 꼴, 금지 단어·상표 단어,
     그리고 (기본) 국어사전에 없는 말 → 브랜드(이케아책상 → '이케아') 같은 고유명사가 들어가지 않게.
  4. 재조합 때 원본마다: 속성 단어(우드·접이식·화이트·대형 등)는 원본 상품명·옵션·상세설명에 있을 때만 쓴다.
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

SEARCHAD_API = "https://api.searchad.naver.com"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kw_query (
    query TEXT PRIMARY KEY,      -- 'rel:핵심키워드'
    data BLOB NOT NULL,          -- 연관 키워드 [(키워드, 월간 검색량)] (zlib json)
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS source_kw (
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    word TEXT NOT NULL,
    malls INTEGER NOT NULL,      -- 이 단어가 나온 연관 키워드의 월간 검색량 (클수록 먼저)
    share REAL NOT NULL,
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
CREATE TABLE IF NOT EXISTS core_learn (   -- 원본 화면에서 고친 핵심 키워드: good=1 핵심, 0 핵심 아님
    word TEXT PRIMARY KEY,
    good INTEGER NOT NULL,
    at REAL NOT NULL
);
"""

# 판촉·배송·후기 같은 말: 상품을 설명하지 않으므로 키워드로 쓰지 않음
PROMO = set("""
할인 특가 세일 초특가 최저가 대박 이벤트 사은품 증정 무료 당일 당일발송 당일출고 빠른배송 국내배송 무료배송 택배
오늘출발 오늘발송 로켓 핫딜 쿠폰 적립 인기 추천 베스트 신상 신제품 신상품 리뷰 후기 정품 인기상품 판매 판매중 재고
상품 제품 기획 한정 단독 최신 최신형 고급 프리미엄 국산 국내산 수입 해외 직구 구매 주문 배송 발송 출고 문의 선물
가격 저렴한 싼 싸게 최저 순위 랭킹 브랜드 사이트 쇼핑몰 매장 파는곳 판매처 도매 소매 대량 업체
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


def has_keys(cfg):
    return bool(cfg.get("searchad_api_key") and cfg.get("searchad_secret") and cfg.get("searchad_customer_id")) \
        or os.environ.get("UPLOADER_FAKE_API") == "1"


# ───────────────────────── 핵심 키워드

def head_tokens(name, n=5, lex=None):
    """핵심 키워드 후보: 앞 n단어 중 2글자 이상 한글이 들어간 단어 (속성·판촉 단어 제외)."""
    out = []
    for t in namegen.tokens(name)[:n]:
        w = re.sub(r"[^\w가-힣]", "", t)
        if re.search(r"[가-힣]{2,}", w) and not lexicon.is_attr(w, lex) and w not in PROMO:
            out.append(w)
    return out


def _learned(db):
    return {r["word"]: r["good"] for r in db.q("SELECT word, good FROM core_learn")}


def detect_core(name, lex=None, vols=None, learn=None, n=5):
    """앞 n단어 중 핵심 키워드. ① 직접 고쳐 기억한 단어 ② 검색량이 가장 큰 단어 ③ (검색량 모르면) 앞 3단어 중 마지막."""
    toks = head_tokens(name, n, lex)
    learn = learn or {}
    toks = [t for t in toks if learn.get(t) != 0] or toks
    if not toks:
        return (namegen.tokens(name) or [""])[0]
    good = [t for t in toks if learn.get(t) == 1]
    if good:
        return good[0]
    if vols:
        best = max(toks, key=lambda t: (vols.get(t, -1), -toks.index(t)))
        if vols.get(best, -1) > 0:
            return best
    head = toks[:3]
    return head[-1]


def learn_core(db, word, good=True, other=None):
    """원본 화면에서 핵심 키워드를 고치면: 고른 단어는 핵심(1), 원래 자동으로 잡혔던 단어는 핵심 아님(0)."""
    now = time.time()
    with db.tx() as c:
        if word:
            c.execute("INSERT OR REPLACE INTO core_learn(word, good, at) VALUES(?,1,?)", (word, now))
        if other and other != word:
            c.execute("INSERT OR IGNORE INTO core_learn(word, good, at) VALUES(?,0,?)", (other, now))


# ───────────────────────── 연관 키워드 → 새 단어

def _fake_related(core):
    import random
    rnd = random.Random(hashlib.md5(core.encode()).hexdigest())
    mods = ["사무용", "학생", "컴퓨터", "가정용", "다용도", "원목", "접이식", "화이트", "대형", "미니", "휴대용", "실내",
            "캠핑", "이케아", "한샘", "추천", "최저가", "선반", "수납", "정리", "보관", "튼튼한"]
    out = [(core, 20000)]
    for m in rnd.sample(mods, 14):
        out.append((m + core if rnd.random() < 0.7 else core + m, rnd.randint(10, 9000)))
    out.append(("모니터받침대", 5000))
    return out


def related(db, cfg, core, session=None):
    """핵심 키워드의 연관 키워드 [(키워드, 월간 검색량)]. 저장해 둔 것이 있으면 다시 씀."""
    fresh = time.time() - int(cfg.get("kw_refresh_days") or 60) * 86400
    q = "rel:" + core
    hit = db.one("SELECT data FROM kw_query WHERE query=? AND fetched_at>?", (q, fresh))
    if hit:
        return _unpack(hit["data"]), False
    if os.environ.get("UPLOADER_FAKE_API") == "1":
        rels = _fake_related(core)
    else:
        import requests
        s = session or requests.Session()
        r = s.get(SEARCHAD_API + "/keywordstool", params={"hintKeywords": core.replace(" ", ""), "showDetail": 1},
                  headers=_searchad_headers(cfg, "GET", "/keywordstool"), timeout=15)
        if r.status_code in (401, 403):
            raise RuntimeError("검색광고 API 키가 맞지 않습니다 (searchad.naver.com → 도구 → API 사용 관리).")
        r.raise_for_status()
        rels = [(k["relKeyword"], _cnt(k.get("monthlyPcQcCnt")) + _cnt(k.get("monthlyMobileQcCnt")))
                for k in r.json().get("keywordList", [])][: int(cfg.get("kw_related_max") or 200)]
        time.sleep(0.25)
    db.x("INSERT OR REPLACE INTO kw_query(query, data, fetched_at) VALUES(?,?,?)", (q, _pack(rels), time.time()))
    return rels, True


def modifiers(core, rels, name, cfg, lex=None):
    """연관 키워드 중 핵심 키워드가 들어간 것에서 핵심을 뺀 말 → [(단어, 검색량)]. 사전 검사는 따로."""
    nc = namegen.normalize(core)
    have = {namegen.normalize(t) for t in namegen.tokens(name)}
    min_v = int(cfg.get("kw_min_volume") or 0)
    best = {}
    for kw, vol in rels:
        nk = namegen.normalize(kw)
        if nk == nc or nc not in nk or vol < min_v:
            continue
        w = nk.replace(nc, "", 1)
        if not re.fullmatch(r"[가-힣]{2,10}", w) or w in have or w in PROMO or w.endswith(SHOP_SUFFIX):
            continue
        if lex and (lexicon.blocked_in(w, lex) or lex.mark_of(w)):
            continue
        best[w] = max(best.get(w, 0), vol)
    return sorted(best.items(), key=lambda x: -x[1])


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


def _dict_check(db, cfg, words, session):
    """국어사전에 있는 말인지: 유의어 묶음·속성 단어·사전 파일·우리말샘 API(키가 있으면, 결과 저장)."""
    lex = lexicon.get(db)
    known = {w for g in lex.syn.values() for w in g} | set(lex.syn) | lex.attrs
    rows = {r["word"]: r["in_dict"] for r in db.q(
        f"SELECT word, in_dict FROM word_dict WHERE word IN ({','.join('?' * len(words))})", list(words))} if words else {}
    key = (cfg.get("opendict_key") or "").strip()
    fake = os.environ.get("UPLOADER_FAKE_API") == "1"
    out = {}
    for w in words:
        if w in known or rows.get(w) == 1:
            out[w] = True
        elif w in rows:
            out[w] = bool(rows[w])
        elif fake:
            out[w] = w not in ("이케아", "한샘")
        elif key:
            try:
                ok = lexicon.in_dictionary(w, key, session)
                db.x("INSERT OR REPLACE INTO word_dict(word, in_dict, checked_at) VALUES(?,?,?)", (w, int(ok), time.time()))
                out[w] = ok
            except Exception:  # noqa: BLE001
                out[w] = None
        else:
            out[w] = None
    return out


def collect(db, cfg, ids=None, progress=None, should_stop=None):
    """원본들의 핵심 키워드와 새 단어 후보를 모은다 (검색광고 API)."""
    import requests
    if not has_keys(cfg):
        raise RuntimeError("설정 → 네이버 키워드에서 검색광고 API 키(고객 ID·액세스 라이선스·비밀키)를 먼저 넣어 주세요 "
                           "(searchad.naver.com → 도구 → API 사용 관리, 무료).")
    lex = lexicon.get(db)
    learn = _learned(db)
    limit = int(cfg.get("kw_daily_limit") or 1000)
    n_head = int(cfg.get("core_scan_words") or 5)
    dict_only = cfg.get("kw_dict_only", True)
    todo = todo_ids(db, cfg, ids)
    s = requests.Session()
    stats = {"sources": 0, "api_calls": 0, "cached": 0, "words": 0, "errors": 0, "error": "", "not_in_dict": 0,
             "dict_unknown": 0, "cores": 0}
    for i in range(0, len(todo), 200):
        if should_stop and should_stop():
            break
        chunk = todo[i:i + 200]
        srcs = db.q(f"SELECT id, name, core_kw, core_manual FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        # 1) 앞 단어들의 검색량 (모르는 것만, 5개씩)
        toks = {t for sr in srcs if not (sr["core_manual"] and sr["core_kw"]) for t in head_tokens(sr["name"], n_head, lex)}
        known = {r["word"] for r in db.q(f"SELECT word FROM kw_volume WHERE word IN ({','.join('?' * len(toks))})",
                                         list(toks))} if toks else set()
        need = [t for t in toks if t not in known]
        if need:
            try:
                fetch_volumes(db, cfg, need, should_stop=should_stop)
                stats["api_calls"] += math.ceil(len(need) / 5)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"검색량을 받지 못했습니다: {e}") if not stats["sources"] else RuntimeError(
                    f"{stats['sources']}개 모은 뒤 멈춤: {e}")
        vols = {r["word"]: r["pc"] + r["mobile"] for r in db.q(
            f"SELECT word, pc, mobile FROM kw_volume WHERE word IN ({','.join('?' * len(toks))})", list(toks))} if toks else {}
        for sr in srcs:
            if should_stop and should_stop():
                break
            core = sr["core_kw"] if sr["core_manual"] and sr["core_kw"] else detect_core(sr["name"], lex, vols, learn, n_head)
            # 2) 핵심 키워드의 연관 키워드 (핵심 키워드마다 한 번)
            try:
                if stats["api_calls"] >= limit and not db.one("SELECT 1 FROM kw_query WHERE query=?", ("rel:" + core,)):
                    break
                rels, called = related(db, cfg, core, s)
                stats["api_calls" if called else "cached"] += 1
                stats["cores"] += int(called)
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                stats["error"] = str(e)[:200]
                if "맞지 않" in str(e) or (stats["errors"] >= 5 and not stats["sources"]):
                    raise RuntimeError(str(e))
                continue
            words = modifiers(core, rels, sr["name"], cfg, lex)
            # 3) 국어사전에 있는 말만 (브랜드·고유명사 거르기)
            if dict_only and words:
                ok = _dict_check(db, cfg, [w for w, _ in words], s)
                stats["not_in_dict"] += sum(1 for w, _ in words if ok.get(w) is False)
                stats["dict_unknown"] += sum(1 for w, _ in words if ok.get(w) is None)
                words = [(w, v) for w, v in words if ok.get(w)]
            words = words[:40]
            with db.tx() as c:
                c.execute("DELETE FROM source_kw WHERE source_id=?", (sr["id"],))
                c.executemany("INSERT INTO source_kw(source_id, word, malls, share) VALUES(?,?,?,1)",
                              [(sr["id"], w, v) for w, v in words])
                c.execute("UPDATE sources SET core_kw=?, kw_at=? WHERE id=?", (core, time.time(), sr["id"]))
            stats["sources"] += 1
            stats["words"] += len(words)
        if progress:
            progress(min(i + len(chunk), len(todo)), len(todo), f"원본 {stats['sources']:,}개 · 핵심 키워드 {stats['cores']:,}개 새로 물음")
    if stats["sources"] and db.one("SELECT 1 FROM dict_syn LIMIT 1"):
        with db.tx() as c:
            lexicon._bump(c)
    return stats


# ───────────────────────── 검색량 (검색광고 API)

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
    learn = None
    out = {}
    for s in sources:
        if not s.get("core_kw") and learn is None:
            learn = _learned(db)
        core = s.get("core_kw") or detect_core(s["name"], lex, None, learn)  # 아직 안 모았으면 앞 단어로
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
