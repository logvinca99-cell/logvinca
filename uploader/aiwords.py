"""재조합에 넣을 새 단어를 AI(Claude)에게 받는다. 이름은 AI가 짓지 않고, 조립은 지금처럼 재조합이 한다.

- 원본마다 처음 한 번만 묻고 저장한다 (ai_words). 복사본·최신화 때는 저장한 단어를 다시 쓴다 (비용 없음).
- 단어 은행 (ai_bank): AI가 '이 단어 대신 쓸 수 있는 말'로 준 것을 카테고리(앞 2단계)·단어별로 모은다.
  새 원본의 앞 단어들이 은행에 충분히 있으면 AI를 부르지 않는다 → 원본이 쌓일수록 비용이 준다.
- AI에게는 원본 상품명·카테고리·옵션 이름과 그 원본의 네이버 연관 키워드를 함께 보낸다.
  AI는 그중 이 상품에 맞고 안전한 말만 고르고, 모자라면 직접 더한다.
- 받은 단어도 재조합 때 금지 단어·상표·속성(원본에 없는 색·재질 등) 검사를 다시 거친다.
"""

import json
import os
import re
import threading
import time

from . import lexicon, namegen

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_words (
    source_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    for_token TEXT NOT NULL DEFAULT '',   -- 이 단어 대신 쓸 수 있는 말이면 그 원래 단어, 덧붙이는 말이면 ''
    off INTEGER NOT NULL DEFAULT 0,       -- 이 원본에서 끔
    PRIMARY KEY (source_id, word)
);
CREATE TABLE IF NOT EXISTS ai_asked (
    source_id INTEGER PRIMARY KEY,
    at REAL NOT NULL,
    via TEXT NOT NULL                     -- ai(AI에게 물음) / bank(단어 은행에서 채움)
);
CREATE TABLE IF NOT EXISTS ai_bank (
    cat TEXT NOT NULL,                    -- 카테고리 앞 2단계
    token TEXT NOT NULL,                  -- 원본 상품명 속 단어
    word TEXT NOT NULL,                   -- 그 대신 쓸 수 있는 말
    n INTEGER NOT NULL DEFAULT 1,         -- AI가 이 짝을 준 횟수
    PRIMARY KEY (cat, token, word)
);
CREATE TABLE IF NOT EXISTS word_use (
    store_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    n INTEGER NOT NULL DEFAULT 0,         -- 이 스토어 상품명에 새 단어로 넣은 횟수
    PRIMARY KEY (store_id, word)
);
"""

SYSTEM = """당신은 네이버 스마트스토어 상품명에 넣을 '단어'를 고르는 도우미입니다. 상품명을 짓지는 않습니다.
상품마다 원본 상품명에 덧붙이거나 원래 단어 대신 넣어도 되는 한국어 일반명사를 고릅니다.

규칙:
- 이 상품을 찾는 사람이 실제로 검색할 만하고, 이 상품과 뜻이 맞는 말만 고릅니다. 동음이의어로 뜻이 달라지는 말은 넣지 않습니다.
- 브랜드·상표·회사명·모델명, 과장·효능·인증 표현(최고, 1위, 특가, 정품, 국산, 의료용, 살균, 친환경 등)은 넣지 않습니다.
- 원본에 없는 속성은 넣지 않습니다: 색, 재질, 크기(대형·소형·미니), 형태, 방식(무선·접이식·자동 등), 수량, 대상(남성·아동 등).
  원본 상품명·옵션에 있는 속성은 써도 됩니다.
- 띄어쓰기 없는 한글 2~10자 한 단어로 씁니다. 원본 상품명에 이미 있는 단어는 다시 주지 않습니다.
- swaps: 원본 상품명 속 단어마다 그 자리에 대신 넣어도 뜻이 같은 말 (예: 포그머신 → 연무기, 스모크머신).
  adds: 상품명에 덧붙여도 되는 용도·장소·분류 말 (예: 공연용, 무대장비).
- 참고 키워드는 네이버에서 실제로 검색되는 말입니다. 이 상품에 맞고 규칙에 맞는 것을 먼저 고르고, 모자라면 직접 더합니다.
- 상품마다 모두 합쳐 {max_words}개 안팎으로 고릅니다. 맞는 말이 적으면 적게 줘도 됩니다."""

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "swaps": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"for": {"type": "string"}, "words": {"type": "array", "items": {"type": "string"}}},
                        "required": ["for", "words"], "additionalProperties": False}},
                    "adds": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "swaps", "adds"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

# 백만 토큰당 달러 (입력, 출력) — 작업 결과에 대략의 비용을 보여 주는 데만 쓴다
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
_HANGUL = re.compile(r"^[가-힣]{2,10}$")


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def enabled(cfg):
    return bool(cfg.get("ai_words_enabled", True))


def has_key(cfg):
    return bool((cfg.get("anthropic_api_key") or "").strip()) or os.environ.get("UPLOADER_FAKE_API") == "1"


def heads(name, lex):
    """단어 은행·swaps에 쓰는 원본 앞 단어들."""
    from . import keywords
    return keywords.head_tokens(name, 6, lex)


# ───────────────────────── AI 호출

class Supplier:
    """여러 원본을 한 번에 보내 원본마다 단어 목록을 받는다."""

    def __init__(self, cfg):
        import anthropic
        key = (cfg.get("anthropic_api_key") or "").strip()
        if not key:
            raise RuntimeError("설정 → AI (Claude API)에서 Anthropic API 키를 먼저 넣어 주세요.")
        self.client = anthropic.Anthropic(api_key=key, max_retries=4)
        self.cfg = cfg
        self.model = cfg.get("ai_words_model") or "claude-sonnet-5-5"
        self.lock = threading.Lock()
        self.usage = {"input": 0, "output": 0, "calls": 0}
        self.system = SYSTEM.format(max_words=int(cfg.get("ai_words_max") or 15))

    def words_batch(self, items):
        """items: [{key, name, category, options, keywords}] → {key: {"swaps": {token: [..]}, "adds": [..]}}"""
        lines = [{"key": it["key"], "원본상품명": it["name"], "카테고리": it["category"],
                  "옵션": it.get("options", [])[:10], "참고키워드": it.get("keywords", [])[:40]} for it in items]
        prompt = "아래 상품마다 단어를 골라 주세요. key는 그대로 돌려주세요.\n\n" + json.dumps(lines, ensure_ascii=False)
        kwargs = dict(
            model=self.model,
            max_tokens=8000,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.cfg.get("ai_words_effort") or "low",
                           "format": {"type": "json_schema", "schema": ITEM_SCHEMA}},
        )
        if self.model in ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"):
            resp = self.client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                                    fallbacks="default", **kwargs)
        else:
            resp = self.client.messages.create(**kwargs)
        with self.lock:
            self.usage["input"] += resp.usage.input_tokens + (resp.usage.cache_read_input_tokens or 0)
            self.usage["output"] += resp.usage.output_tokens
            self.usage["calls"] += 1
        if resp.stop_reason == "refusal":
            raise RuntimeError("AI가 이 묶음의 요청을 거절했습니다.")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("AI 응답이 너무 길어 잘렸습니다. 설정에서 'AI 단어: 한 번에 보낼 원본 수'를 줄이세요.")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return _parse(json.loads(text))

    def cost_usd(self):
        pin, pout = PRICES.get(self.model, (0, 0))
        return (self.usage["input"] * pin + self.usage["output"] * pout) / 1e6


class FakeSupplier:
    """시연 모드용: API를 부르지 않고 단어 사전의 유의어로 흉내 낸다."""

    def __init__(self, cfg, lex):
        self.cfg, self.lex = cfg, lex
        self.model = "fake"
        self.usage = {"input": 0, "output": 0, "calls": 0}

    def words_batch(self, items):
        self.usage["calls"] += 1
        out = {}
        for it in items:
            swaps = {t: [w for w, _, _ in self.lex.synonyms_src(t, it["category"])][:4] for t in heads(it["name"], self.lex)}
            out[it["key"]] = {"swaps": {t: ws for t, ws in swaps.items() if ws}, "adds": list(it.get("keywords", []))[:3]}
        return out

    def cost_usd(self):
        return 0.0


def _parse(data):
    out = {}
    for x in data.get("items", []):
        swaps = {}
        for s in x.get("swaps", []):
            t = str(s.get("for") or "").strip()
            ws = [w.strip() for w in s.get("words", []) if isinstance(w, str)]
            if t and ws:
                swaps.setdefault(t, []).extend(ws)
        out[str(x.get("key"))] = {"swaps": swaps, "adds": [w.strip() for w in x.get("adds", []) if isinstance(w, str)]}
    return out


def make_supplier(cfg, lex):
    if os.environ.get("UPLOADER_FAKE_API") == "1":
        return FakeSupplier(cfg, lex)
    return Supplier(cfg)


# ───────────────────────── 원본마다 단어 받기

def _clean(w):
    w = re.sub(r"\s+", "", str(w or ""))
    return w if _HANGUL.match(w) else ""


def _save(c, sid, name, cat, res, lex, via):
    """받은 단어를 원본에 저장하고 (AI가 준 것이면) 단어 은행에 쌓는다."""
    have = {t.lower() for t in namegen.tokens(name)}
    hs = set(heads(name, lex))
    rows = []
    for t, ws in res.get("swaps", {}).items():
        for w in ws:
            w = _clean(w)
            if w and w.lower() not in have:
                rows.append((w, t))
                if via == "ai" and t in hs:
                    c.execute("""INSERT INTO ai_bank(cat, token, word) VALUES(?,?,?)
                        ON CONFLICT(cat, token, word) DO UPDATE SET n=n+1""", (cat, t, w))
    for w in res.get("adds", []):
        w = _clean(w)
        if w and w.lower() not in have:
            rows.append((w, ""))
    for w, t in rows:
        c.execute("INSERT OR IGNORE INTO ai_words(source_id, word, for_token) VALUES(?,?,?)", (sid, w, t))
    c.execute("INSERT OR REPLACE INTO ai_asked(source_id, at, via) VALUES(?,?,?)", (sid, time.time(), via))
    return len(rows)


def _from_bank(c, name, cat, lex, need):
    """단어 은행에서 이 원본의 앞 단어들 대신 쓸 말을 찾는다. need개 이상이면 그 결과, 아니면 None."""
    swaps = {}
    for t in heads(name, lex):
        ws = [r[0] for r in c.execute("SELECT word FROM ai_bank WHERE cat=? AND token=? ORDER BY n DESC LIMIT 8", (cat, t))]
        if ws:
            swaps[t] = ws
    total = len({w for ws in swaps.values() for w in ws})
    return {"swaps": swaps, "adds": []} if need and total >= need else None


def _options(row):
    from . import convert
    try:
        o = convert.options(row) or {}
    except Exception:  # noqa: BLE001 - 옵션 형식이 이상해도 단어는 받는다
        return []
    names = set()
    for key in ("optionCombinations", "optionSimple", "optionStandards"):
        for x in o.get(key) or []:
            if isinstance(x, dict):
                names.update(str(v)[:30] for k, v in x.items() if (k.startswith("optionName") or k == "name") and v)
    return sorted(names)[:10]


def ensure_words(db, cfg, ids, progress=None, should_stop=None):
    """아직 단어를 안 받은 원본만 받는다 (단어 은행 → 모자라면 AI). 결과 통계를 돌려준다."""
    st = {"asked": 0, "bank": 0, "calls": 0, "cost_usd": 0.0, "error": None}
    if not enabled(cfg) or not ids:
        return st
    need_ids = []
    for i in range(0, len(ids), 900):
        chunk = list(ids)[i:i + 900]
        need_ids += [r["id"] for r in db.q(f"""SELECT id FROM sources WHERE id IN ({','.join('?' * len(chunk))})
            AND id NOT IN (SELECT source_id FROM ai_asked)""", chunk)]
    if not need_ids:
        return st
    lex = lexicon.get(db)
    bank_min = int(cfg.get("ai_bank_min") or 0)
    ask = []
    with db.tx() as c:
        for i in range(0, len(need_ids), 900):
            chunk = need_ids[i:i + 900]
            for r in c.execute(f"SELECT id, name, category FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                cat = lexicon.cat_key(r["category"] or "")
                got = _from_bank(c, r["name"], cat, lex, bank_min)
                if got:
                    _save(c, r["id"], r["name"], cat, got, lex, "bank")
                    st["bank"] += 1
                else:
                    ask.append(r["id"])
    if not ask:
        return st
    if not has_key(cfg):
        st["error"] = "Anthropic API 키가 없어 AI 단어를 받지 못했습니다 (사전·네이버 키워드로 재조합)."
        return st
    try:
        sup = make_supplier(cfg, lex)
    except Exception as e:  # noqa: BLE001
        st["error"] = str(e)
        return st
    from . import keywords
    per = max(1, int(cfg.get("ai_words_per_call") or 20))
    for i in range(0, len(ask), per):
        if should_stop and should_stop():
            break
        chunk = ask[i:i + per]
        rows = db.q(f"SELECT id, name, category, data FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        kw = {}
        for r in db.q(f"""SELECT source_id, word FROM source_kw WHERE source_id IN ({','.join('?' * len(chunk))})
                ORDER BY malls DESC""", chunk):
            kw.setdefault(r["source_id"], []).append(r["word"])
        items = []
        for r in rows:
            items.append({"key": str(r["id"]), "name": r["name"], "category": r["category"] or "",
                          "options": _options(keywords._row(db, r)), "keywords": kw.get(r["id"], [])})
        try:
            res = sup.words_batch(items)
        except Exception as e:  # noqa: BLE001 - 한 묶음이 실패해도 나머지는 재조합을 계속한다
            st["error"] = f"AI 단어 받기 실패: {e}"[:300]
            break
        with db.tx() as c:
            for r in rows:
                got = res.get(str(r["id"]))
                if got is not None:
                    _save(c, r["id"], r["name"], lexicon.cat_key(r["category"] or ""), got, lex, "ai")
                    st["asked"] += 1
        if progress:
            progress(min(i + per, len(ask)), len(ask), f"AI에게 새 단어 받는 중 {st['asked']:,}/{len(ask):,}")
    st["calls"] = sup.usage["calls"]
    st["cost_usd"] = round(sup.cost_usd(), 4)
    return st


def words_for(db, sources, cfg, lex=None):
    """{source_id: [(단어, 대신할 원래 단어 또는 '')]} — 끈 단어·금지·상표·원본에 없는 속성은 뺌."""
    from . import keywords
    if not enabled(cfg) or not sources:
        return {}
    lex = lex or lexicon.get(db)
    ids = [s["id"] for s in sources]
    rows = {}
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        for r in db.q(f"""SELECT source_id, word, for_token FROM ai_words WHERE off=0
                AND source_id IN ({','.join('?' * len(chunk))})""", chunk):
            rows.setdefault(r["source_id"], []).append((r["word"], r["for_token"]))
    dead = {r["word"] for r in db.q("SELECT word FROM kw_off WHERE core=''")}
    out = {}
    for s in sources:
        text = None
        picked = []
        for w, t in rows.get(s["id"], []):
            if w in dead or not lex.ok_new_word(w):
                continue
            attrs = lexicon.attrs_in(w, lex)
            if attrs:
                if text is None:
                    text = namegen.normalize(keywords.original_text(s["name"], keywords._row(db, s)))
                if not all(namegen.normalize(a) in text for a in attrs):
                    continue
            picked.append((w, t))
        out[s["id"]] = picked
    return out


def source_words(db, sid):
    """원본 화면용: 받은 단어 전부 (끈 것 포함)."""
    asked = db.one("SELECT at, via FROM ai_asked WHERE source_id=?", (sid,))
    rows = db.q("SELECT word, for_token, off FROM ai_words WHERE source_id=? ORDER BY for_token='', for_token, word", (sid,))
    dead = {r["word"] for r in db.q("SELECT word FROM kw_off WHERE core=''")}
    return {"asked_at": asked["at"] if asked else None, "via": asked["via"] if asked else "",
            "words": [{**r, "all_off": r["word"] in dead} for r in rows]}


def set_off(db, sid, word, off, everywhere=False):
    if everywhere:
        if off:
            db.x("INSERT OR IGNORE INTO kw_off(core, word) VALUES('', ?)", (word,))
        else:
            db.x("DELETE FROM kw_off WHERE core='' AND word=?", (word,))
    db.x("UPDATE ai_words SET off=? WHERE source_id=? AND word=?", (int(bool(off)), sid, word))


def forget(db, sid):
    """다시 받기: 이 원본의 단어를 지운다 (다음 재조합 때 다시 받음)."""
    with db.tx() as c:
        c.execute("DELETE FROM ai_words WHERE source_id=?", (sid,))
        c.execute("DELETE FROM ai_asked WHERE source_id=?", (sid,))


def use_counts(db, store_ids):
    """{store_id: {단어: 횟수}}"""
    out = {s: {} for s in store_ids}
    if not store_ids:
        return out
    for r in db.q(f"SELECT store_id, word, n FROM word_use WHERE store_id IN ({','.join('?' * len(store_ids))})",
                  list(store_ids)):
        out[r["store_id"]][r["word"]] = r["n"]
    return out


def count_use(c, store_id, original, name):
    """이름에 새로 들어간 단어를 그 스토어 사용 횟수에 더한다."""
    orig = {t.lower() for t in namegen.tokens(original)}
    for w in {t for t in namegen.tokens(name) if t.lower() not in orig}:
        c.execute("""INSERT INTO word_use(store_id, word, n) VALUES(?,?,1)
            ON CONFLICT(store_id, word) DO UPDATE SET n=n+1""", (store_id, w))


def stats(db):
    r = db.one("""SELECT (SELECT COUNT(*) FROM ai_asked WHERE via='ai') AS ai, (SELECT COUNT(*) FROM ai_asked WHERE via='bank') AS bank,
        (SELECT COUNT(*) FROM ai_bank) AS bank_pairs, (SELECT COUNT(DISTINCT cat || ':' || token) FROM ai_bank) AS bank_tokens""")
    return dict(r)

