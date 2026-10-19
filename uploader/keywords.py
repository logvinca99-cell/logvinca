"""네이버 검색광고 API(연관 키워드)로 재조합 새 단어를 모은다. (네이버 쇼핑 검색 API는 2026년 7월 종료)

원본마다 상품명 앞 몇 단어(기본 5, 속성·판촉 단어 제외)를 하나씩 검색광고 키워드 도구에 넣어 연관 키워드를 받는다.
같은 단어는 한 번만 묻고 저장해 다시 쓴다 (커튼·거실처럼 자주 나오는 단어는 수천 개 원본이 같이 씀).
  - 연관 키워드에 그 단어가 들어 있으면 그 단어를 뺀 나머지:   커튼 → 암막커튼 → '암막'
  - 연관 키워드 자체가 국어사전에 있는 명사면 그대로:          포그머신 → '연무기'
버리는 것: 월 검색량이 적은 것(기본 30 미만), 판촉 문구, 가게 이름 꼴, 금지·상표 단어,
          (기본) 국어사전에 없는 말 → 브랜드(이케아커튼 → '이케아') 같은 고유명사가 들어가지 않게.
재조합 때 원본마다: 속성 단어(우드·접이식·화이트·대형 등)는 원본 상품명·옵션·상세설명에 있을 때만 쓴다.
키가 있으면 재조합·미리보기 때 아직 안 모은 원본은 자동으로 모은다.
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
    core TEXT NOT NULL,          -- 이 단어(상품명 속 단어)에서 온 새 단어를 끔. '' 이면 모든 단어에서
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


# ───────────────────────── 검색할 단어

def head_tokens(name, n=5, lex=None):
    """연관 키워드를 받을 단어: 앞 n단어 중 2글자 이상 한글이 들어간 단어 (속성·판촉 단어 제외)."""
    out = []
    for t in namegen.tokens(name)[:n]:
        w = re.sub(r"[^\w가-힣]", "", t)
        if re.search(r"[가-힣]{2,}", w) and not lexicon.is_attr(w, lex) and w not in PROMO and w not in out:
            out.append(w)
    return out


def _learned(db):  # 예전 핵심 키워드 기능 (호환용)
    return {}


def detect_core(name, lex=None, vols=None, learn=None, n=5):  # 예전 호출 호환용: 재조합은 핵심 키워드를 쓰지 않음
    toks = head_tokens(name, n, lex)
    return toks[0] if toks else ""


def learn_core(db, word, good=True, other=None):  # 호환용
    return None


# ───────────────────────── 연관 키워드 → 새 단어

def _fake_related(token):
    import random
    rnd = random.Random(hashlib.md5(token.encode()).hexdigest())
    mods = ["사무용", "학생", "컴퓨터", "가정용", "다용도", "원목", "접이식", "화이트", "대형", "미니", "휴대용", "실내",
            "캠핑", "이케아", "한샘", "추천", "최저가", "선반", "수납", "정리", "보관", "튼튼한", "암막", "방풍"]
    out = [(token, 20000)]
    for m in rnd.sample(mods, 12):
        out.append((m + token if rnd.random() < 0.7 else token + m, rnd.randint(10, 9000)))
    out += [("연무기", 3000), ("가림막", 800), ("모니터받침대", 5000)]
    return out


def related(db, cfg, token, session=None):
    """단어의 연관 키워드 [(키워드, 월간 검색량)]. 저장해 둔 것이 있으면 다시 씀. (결과, API를 불렀는지)"""
    fresh = time.time() - int(cfg.get("kw_refresh_days") or 60) * 86400
    q = "rel:" + token
    hit = db.one("SELECT data FROM kw_query WHERE query=? AND fetched_at>?", (q, fresh))
    if hit:
        return _unpack(hit["data"]), False
    if os.environ.get("UPLOADER_FAKE_API") == "1":
        rels = _fake_related(token)
    else:
        import requests
        s = session or requests.Session()
        r = s.get(SEARCHAD_API + "/keywordstool", params={"hintKeywords": token.replace(" ", ""), "showDetail": 1},
                  headers=_searchad_headers(cfg, "GET", "/keywordstool"), timeout=15)
        if r.status_code in (401, 403):
            raise RuntimeError("검색광고 API 키가 맞지 않습니다 (searchad.naver.com → 도구 → API 사용 관리에서 "
                               "고객 ID·액세스 라이선스·비밀키를 다시 확인).")
        if r.status_code == 400:
            rels = []  # 검색광고에 없는 말 (특수문자 등)
        else:
            r.raise_for_status()
            rels = [(k["relKeyword"], _cnt(k.get("monthlyPcQcCnt")) + _cnt(k.get("monthlyMobileQcCnt")))
                    for k in r.json().get("keywordList", [])][: int(cfg.get("kw_related_max") or 200)]
        time.sleep(0.2)
    db.x("INSERT OR REPLACE INTO kw_query(query, data, fetched_at) VALUES(?,?,?)", (q, _pack(rels), time.time()))
    return rels, True


def token_words(token, rels, cfg, lex=None, have=()):
    """한 단어의 연관 키워드 → 새 단어 후보 {단어: (검색량, 종류)}. 종류: 'mod'(단어를 뺀 나머지) / 'rel'(연관 키워드 그대로).
    사전 검사는 따로(_dict_check)."""
    nt = namegen.normalize(token)
    min_v = int(cfg.get("kw_min_volume") or 0)
    out = {}
    for kw, vol in rels:
        nk = namegen.normalize(kw)
        if nk == nt or vol < min_v:
            continue
        if nt in nk:
            w, kind = nk.replace(nt, "", 1), "mod"
        else:
            w, kind = nk, "rel"
        if not re.fullmatch(r"[가-힣]{2,10}", w) or w in have or w in PROMO or w.endswith(SHOP_SUFFIX):
            continue
        if lex and (lexicon.blocked_in(w, lex) or lex.mark_of(w)):
            continue
        if w not in out or out[w][0] < vol:
            out[w] = (vol, kind)
    return out


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
    """원본들의 새 단어 후보를 모은다 (검색광고 API, 단어마다 한 번)."""
    import requests
    if not has_keys(cfg):
        raise RuntimeError("설정 → 네이버 키워드에서 검색광고 API 키(고객 ID·액세스 라이선스·비밀키)를 먼저 넣어 주세요 "
                           "(searchad.naver.com → 도구 → API 사용 관리, 무료).")
    lex = lexicon.get(db)
    limit = int(cfg.get("kw_daily_limit") or 1000)
    n_head = int(cfg.get("core_scan_words") or 5)
    dict_only = cfg.get("kw_dict_only", True)
    todo = todo_ids(db, cfg, ids)
    s = requests.Session()
    stats = {"sources": 0, "api_calls": 0, "cached": 0, "words": 0, "errors": 0, "error": "", "not_in_dict": 0,
             "dict_unknown": 0, "tokens": 0}
    rel_cache = {}
    for i in range(0, len(todo), 200):
        if should_stop and should_stop():
            break
        chunk = todo[i:i + 200]
        srcs = db.q(f"SELECT id, name FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        stop = False
        for sr in srcs:
            if should_stop and should_stop():
                stop = True
                break
            toks = head_tokens(sr["name"], n_head, lex)
            have = {namegen.normalize(t) for t in namegen.tokens(sr["name"])}
            merged = {}
            for t in toks:
                if t not in rel_cache:
                    if stats["api_calls"] >= limit and not db.one("SELECT 1 FROM kw_query WHERE query=?", ("rel:" + t,)):
                        stop = True
                        break
                    try:
                        rel_cache[t], called = related(db, cfg, t, s)
                    except Exception as e:  # noqa: BLE001
                        stats["errors"] += 1
                        stats["error"] = str(e)[:200]
                        if "맞지 않" in str(e) or (stats["errors"] >= 5 and not stats["sources"]):
                            raise RuntimeError(str(e))
                        rel_cache[t], called = [], False
                    stats["api_calls" if called else "cached"] += 1
                    stats["tokens"] += int(called)
                for w, (v, kind) in token_words(t, rel_cache[t], cfg, lex, have).items():
                    if w not in merged or merged[w][0] < v:
                        merged[w] = (v, kind)
            if stop:
                break
            words = sorted(merged.items(), key=lambda x: -x[1][0])
            if dict_only and words:
                ok = _dict_check(db, cfg, [w for w, _ in words], s)
                stats["not_in_dict"] += sum(1 for w, _ in words if ok.get(w) is False)
                stats["dict_unknown"] += sum(1 for w, _ in words if ok.get(w) is None)
                words = [(w, x) for w, x in words if ok.get(w)]
            words = words[:40]
            with db.tx() as c:
                c.execute("DELETE FROM source_kw WHERE source_id=?", (sr["id"],))
                c.executemany("INSERT INTO source_kw(source_id, word, malls, share) VALUES(?,?,?,1)",
                              [(sr["id"], w, x[0]) for w, x in words])
                c.execute("UPDATE sources SET kw_at=? WHERE id=?", (time.time(), sr["id"]))
            stats["sources"] += 1
            stats["words"] += len(words)
        if progress:
            progress(min(i + len(chunk), len(todo)), len(todo), f"원본 {stats['sources']:,}개 · 새로 물은 단어 {stats['tokens']:,}개")
        if stop:
            break
    if stats["sources"] and db.one("SELECT 1 FROM dict_syn LIMIT 1"):
        with db.tx() as c:
            lexicon._bump(c)
    return stats


def words_for_name(db, cfg, name, lex=None):
    """원본 없이 상품명만으로 새 단어 후보 (미리보기용). 속성 단어는 상품명에 있을 때만."""
    import requests
    lex = lex or lexicon.get(db)
    s = requests.Session()
    have = {namegen.normalize(t) for t in namegen.tokens(name)}
    merged = {}
    for t in head_tokens(name, int(cfg.get("core_scan_words") or 5), lex):
        rels, _ = related(db, cfg, t, s)
        for w, (v, kind) in token_words(t, rels, cfg, lex, have).items():
            if w not in merged or merged[w][0] < v:
                merged[w] = (v, kind)
    words = [w for w, _ in sorted(merged.items(), key=lambda x: -x[1][0])]
    if cfg.get("kw_dict_only", True) and words:
        ok = _dict_check(db, cfg, words, s)
        words = [w for w in words if ok.get(w)]
    text = namegen.normalize(name)
    out = []
    for w in words:
        attrs = lexicon.attrs_in(w, lex)
        if attrs and not all(namegen.normalize(a) in text for a in attrs):
            continue
        if lex.ok_new_word(w):
            out.append(w)
    return out[: int(cfg.get("kw_max_words") or 15)]


def ensure_collected(db, cfg, ids, should_stop=None):
    """키가 있으면 아직 안 모은 원본의 새 단어를 모은다 (재조합·미리보기 전에 자동으로). 오류는 문구로 돌려줌."""
    if not cfg.get("use_naver_keywords", True) or not has_keys(cfg) or not ids:
        return None, 0
    need = []
    for i in range(0, len(ids), 900):
        chunk = list(ids)[i:i + 900]
        need += [r["id"] for r in db.q(f"SELECT id FROM sources WHERE kw_at IS NULL AND id IN ({','.join('?' * len(chunk))})",
                                       chunk)]
    if not need:
        return None, 0
    try:
        st = collect(db, cfg, need, should_stop=should_stop)
        return (st.get("error") or None), st["sources"]
    except Exception as e:  # noqa: BLE001
        return str(e)[:300], 0


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
        core = ""  # 재조합은 핵심 키워드를 쓰지 않는다
        cand = rows.get(s["id"], [])
        if not cand:
            out[s["id"]] = (core, [])
            continue
        text = None
        dead = set(off.get("", set()))
        for t in head_tokens(s["name"], 10, lex):
            dead |= off.get(t, set())
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
