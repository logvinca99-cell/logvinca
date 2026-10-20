"""맥락 키워드: AI(Claude)에게 원본마다 '맥락 키워드'(쓰는 장소·사람·용도·상황) 목록만 받아 저장한다.
상품명은 ctxname(기준 구현)이 이 키워드로 조립한다. 원본마다 한 번만 받고, 받은 원본은 다시 묻지 않는다.

- 기본은 일괄 처리(Message Batches, 요금 50% 할인). 소량 시험은 즉시 모드(일반 요청, 동시 3건).
- 요청 하나에 원본 10개. 응답 배열 길이가 보낸 원본 수와 다르거나 파싱이 실패하면 그 요청 전체를 실패로 둔다.
- 진행 중인 일괄 처리는 디스크(db)에 적어 두고, 프로그램을 다시 켜면 이어서 확인한다.
- 원본 상품명이 바뀌면 그 원본의 키워드와 아직 안 쓴 이름 후보를 무효로 한다.
"""

import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, ctxname, lexicon, namegen

SCHEMA = """
CREATE TABLE IF NOT EXISTS ctx_kw (
    source_id INTEGER PRIMARY KEY,
    words TEXT NOT NULL DEFAULT '[]',     -- AI가 준 키워드 (거르기 전 그대로)
    name TEXT NOT NULL DEFAULT '',        -- 받을 때의 원본 상품명 (바뀌면 무효)
    status TEXT NOT NULL,                 -- ok / pending(일괄 처리 중) / retry(재시도 대기) / invalid(원본 이름 바뀜)
    batch_id TEXT NOT NULL DEFAULT '',
    run_id INTEGER,
    in_tok INTEGER NOT NULL DEFAULT 0,    -- 이 원본 몫 토큰 (요청 토큰을 원본 수로 나눔)
    out_tok INTEGER NOT NULL DEFAULT 0,
    names_made INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ctx_run (
    id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at REAL,
    mode TEXT NOT NULL,                   -- batch / instant
    model TEXT NOT NULL,
    sources INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 0,        -- 키워드를 저장한 원본
    failed INTEGER NOT NULL DEFAULT 0,    -- 재시도 대기로 둔 원본
    in_tok INTEGER NOT NULL DEFAULT 0,
    out_tok INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    est_cost_usd REAL NOT NULL DEFAULT 0,
    rate REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',  -- running / done / canceled / failed
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ctx_batch (
    id TEXT PRIMARY KEY,                  -- Anthropic 배치 id (만드는 중이면 'local:…')
    run_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    status TEXT NOT NULL,                 -- creating / processing / ended / canceling
    requests TEXT NOT NULL,               -- {custom_id: [원본 id…]}
    checked_at REAL,
    ended_at REAL
);
"""

SYSTEM = """너는 네이버 스마트스토어 상품명 검색 키워드 작성자다. 각 상품마다 원본 상품명에 덧붙여 검색 노출을 넓힐 '맥락 키워드' {n}개를 만든다.
규칙:
- 사용 장소, 사용하는 사람(대상), 용도, 사용 상황 중심. 실제 소비자가 네이버에서 검색할 법한 명사.
- 한 단어 2~5글자, 띄어쓰기 없음, 한글만.
- 원본 상품명에 이미 있는 단어, 또는 그 단어를 살짝 바꾼 말 금지.
- 브랜드, 상표, 회사·서비스명, 캐릭터, 명품, 연예인, 지역명 금지.
- 인증, 특허, 최고, 고급, 프리미엄, 효율, 편안함, 건강, 내구성처럼 막연하거나 검증 불가한 표현 금지.
- 상품과 직접 관련 있는 것만. 애매하면 빼고 확실한 것으로 채운다. {n}개끼리 중복 금지.
출력: 설명 없이 JSON 배열만. 형식: [{{"i":1,"kw":["단어1","단어2", ...]}}]"""

# 백만 토큰당 달러 (입력, 출력). 일괄 처리는 절반.
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50), "claude-opus-5-5": (4.0, 20.0)}
EST_IN, EST_OUT = 125, 85            # 원본당 예상 토큰 (실측: 입력 125, 출력 12개 기준 85)
BATCH_MAX_REQUESTS = 5000            # 배치 하나에 넣을 요청 수 (원본 5만 개)
_CUSTOM_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_lock = threading.Lock()


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def fake():
    return os.environ.get("UPLOADER_FAKE_API") == "1"


def has_key(cfg):
    return bool((cfg.get("anthropic_api_key") or "").strip()) or fake()


# ───────────────────────── 요청 만들기·응답 읽기

def model_of(cfg):
    return cfg.get("ctx_model") or "claude-sonnet-5-5"


def params(cfg, items):
    """요청 본문 (즉시·일괄 같음). items: [{name, category}] — 순서대로 1번부터."""
    model = model_of(cfg)
    lines = []
    for i, it in enumerate(items, 1):
        cat = ">".join(str(it.get("category") or "").split(">")[-2:])   # 카테고리는 마지막 2단계만
        lines.append(f"{i}. {it['name']} (카테고리: {cat})")
    p = {
        "model": model,
        "max_tokens": 3000,
        "system": SYSTEM.format(n=int(cfg.get("ctx_kw_count") or 12)),
        "messages": [{"role": "user", "content": "\n".join(lines)}],
        # 생각 끄기: 안 끄면 생각이 max_tokens를 다 써서 빈 답이 오고 요금은 나간다. temperature는 보내지 않는다(400 오류).
        "thinking": {"type": "disabled"} if "haiku" in model else {"type": "between_tools"},
    }
    return p


def parse(text, n):
    """text 블록에서 JSON 배열을 꺼내 [[키워드…] × n] (보낸 순서). 길이가 다르거나 형식이 틀리면 ValueError."""
    s, e = text.find("["), text.rfind("]")
    if s < 0 or e <= s:
        raise ValueError("응답에 JSON 배열이 없습니다.")
    arr = json.loads(text[s:e + 1])
    if not isinstance(arr, list) or len(arr) != n:
        raise ValueError(f"응답 개수가 다릅니다 (보냄 {n}개, 받음 {len(arr) if isinstance(arr, list) else '?'}개).")
    out = {}
    for x in arr:
        if not isinstance(x, dict) or not isinstance(x.get("kw"), list):
            raise ValueError("응답 형식이 다릅니다.")
        try:
            i = int(x.get("i"))
        except (TypeError, ValueError):
            raise ValueError("응답 번호(i)가 없습니다.") from None
        out[i] = [str(w) for w in x["kw"] if isinstance(w, str)]
    if sorted(out) != list(range(1, n + 1)):
        raise ValueError("응답 번호(i)가 보낸 순서와 맞지 않습니다.")
    return [out[i] for i in range(1, n + 1)]


def _text_of(content):
    return "".join(b.get("text", "") if isinstance(b, dict) else (getattr(b, "text", "") or "")
                   for b in content if (b.get("type") if isinstance(b, dict) else getattr(b, "type", "")) == "text")


def cost(model, in_tok, out_tok, batch):
    pin, pout = PRICES.get(model, PRICES["claude-sonnet-5-5"])
    usd = (in_tok * pin + out_tok * pout) / 1e6
    return usd / 2 if batch else usd


# ───────────────────────── 대상·예상 비용

def targets(db, ids):
    """키워드를 받아야 할 원본 (받은 것·일괄 처리 중인 것 제외, 무효·재시도 대기는 포함)."""
    out = []
    for i in range(0, len(ids), 900):
        chunk = list(ids)[i:i + 900]
        out += [r["id"] for r in db.q(f"""SELECT s.id FROM sources s LEFT JOIN ctx_kw k ON k.source_id=s.id
            WHERE s.id IN ({','.join('?' * len(chunk))}) AND (k.status IS NULL OR k.status IN ('retry','invalid'))
            ORDER BY s.id""", chunk)]
    return out


def estimate(db, cfg, ids, mode=None):
    mode = mode or cfg.get("ctx_mode") or "batch"
    need = targets(db, ids)
    per = max(1, int(cfg.get("ctx_per_request") or 10))
    n = len(need)
    kw = int(cfg.get("ctx_kw_count") or 12)
    in_tok, out_tok = EST_IN * n, round(EST_OUT * kw / 12 * n)
    rate = float(cfg.get("krw_rate") or 1330)
    usd = cost(model_of(cfg), in_tok, out_tok, mode == "batch")
    pending = db.one("SELECT COUNT(*) AS n FROM ctx_kw WHERE status='pending'")["n"]
    return {"sources": n, "selected": len(ids), "have": len(ids) - n, "requests": math.ceil(n / per) if n else 0,
            "in_tok": in_tok, "out_tok": out_tok, "usd": round(usd, 4), "krw": math.ceil(usd * rate), "rate": rate,
            "mode": mode, "model": model_of(cfg), "pending": pending, "has_key": has_key(cfg)}


# ───────────────────────── 저장 → 이름 후보 만들기

def _new_run(db, cfg, mode, n_src, n_req, est):
    return db.x("""INSERT INTO ctx_run(started_at, mode, model, sources, requests, est_cost_usd, rate)
        VALUES(?,?,?,?,?,?,?)""", (time.time(), mode, model_of(cfg), n_src, n_req, est, float(cfg.get("krw_rate") or 1330)))


def _save_ok(c, sids, names, kws, in_tok, out_tok, run_id):
    per_in, per_out = in_tok // max(1, len(sids)), out_tok // max(1, len(sids))
    now = time.time()
    for sid, nm, kw in zip(sids, names, kws):
        c.execute("""INSERT INTO ctx_kw(source_id, words, name, status, batch_id, run_id, in_tok, out_tok, names_made, error, at)
            VALUES(?,?,?,'ok','',?,?,?,0,'',?) ON CONFLICT(source_id) DO UPDATE SET words=excluded.words, name=excluded.name,
            status='ok', batch_id='', run_id=excluded.run_id, in_tok=excluded.in_tok, out_tok=excluded.out_tok,
            names_made=0, error='', at=excluded.at""", (sid, json.dumps(kw, ensure_ascii=False), nm, run_id, per_in, per_out, now))


def _save_fail(c, sids, err, run_id):
    now = time.time()
    for sid in sids:
        c.execute("""INSERT INTO ctx_kw(source_id, status, run_id, error, at) VALUES(?, 'retry', ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET status='retry', batch_id='', run_id=excluded.run_id, error=excluded.error,
            at=excluded.at""", (sid, run_id, str(err)[:300], now))


def _run_add(db, run_id, ok=0, failed=0, in_tok=0, out_tok=0, usd=0.0):
    db.x("""UPDATE ctx_run SET ok=ok+?, failed=failed+?, in_tok=in_tok+?, out_tok=out_tok+?, cost_usd=cost_usd+? WHERE id=?""",
         (ok, failed, in_tok, out_tok, usd, run_id))


def forbidden(db):
    """조립 때 원본·AI 키워드에서 빼는 금지어 = 앱의 금지 단어 목록 (금지어_721 가져오기 포함)."""
    return set(lexicon.get(db).blocked)


def opts(cfg):
    return {"max_chars": int(cfg.get("name_max_len") or 50), "head_n": int(cfg.get("ctx_head_n") or 4),
            "ai_per_name": int(cfg.get("ctx_ai_per_name") or 6), "tail_min": int(cfg.get("ctx_tail_min") or 3),
            "tail_max": int(cfg.get("ctx_tail_max") or 6)}


def make_rejecter(c, cfg, lex):
    """앱의 기존 검사를 make_names의 reject로: 33개 스토어 전체에서 쓰는(또는 후보에 있는) 이름과 같음(등록된 이름 포함),
    키프리스로 확인된 상표 단어. 85% 겹침·원본과 같은 이름은 make_names가, 금지어는 clean_origin·filter_ai_words가
    기준 구현대로 단어 단위로 본다 (금지어 목록에 '높이' 같은 짧은 말이 있어 글자 단위로 보면 '높이조절'까지 막힘)."""

    def reject(name):
        if c.execute("SELECT 1 FROM names WHERE norm=?", (namegen.normalize(name),)).fetchone():
            return True
        return bool(lexicon.marks_in(name, lex))
    return reject


def build_names(db, sids, cfg=None):
    """키워드를 받은 원본마다 이름 후보 N개(기본 2)를 한 번에 만들어 저장한다. 이미 만든 원본은 건너뜀.
    {made: 만든 이름 수, none: 못 만든 수(이름 변경 필요로 남음)}"""
    from .inventory import add_names
    cfg = cfg or config.load()
    lex = lexicon.get(db)
    forb = set(lex.blocked)
    copies = max(1, int(cfg.get("ctx_names_per_source") or 2))
    st = {"made": 0, "none": 0}
    o = opts(cfg)
    for i in range(0, len(sids), 500):
        chunk = list(sids)[i:i + 500]
        rows = db.q(f"""SELECT s.id, s.name, k.words FROM sources s JOIN ctx_kw k ON k.source_id=s.id
            WHERE k.status='ok' AND k.names_made=0 AND s.id IN ({','.join('?' * len(chunk))})""", chunk)
        with db.tx() as c:
            reject = make_rejecter(c, cfg, lex)
            now = time.time()
            for r in rows:
                res = ctxname.make_names(r["name"], json.loads(r["words"]), forb, copies=copies, seed=r["id"],
                                         reject=reject, opts=o)
                for x in res:
                    if x is None:
                        st["none"] += 1
                        continue
                    added, _ = add_names(c, r["id"], [x["name"]], "ctx", now)
                    st["made"] += added
                c.execute("UPDATE ctx_kw SET names_made=1 WHERE source_id=?", (r["id"],))
        db.recount_sources(chunk)
    return st


def after_saved(db, sids):
    """키워드를 저장한 뒤: 이름 후보를 만들고, 그 원본의 아직 이름 없는 복사본에 배정한다."""
    from . import inventory
    if not sids:
        return {}
    st = build_names(db, sids)
    st["assigned"] = inventory.assign_ctx_names(db, sids)
    return st


def invalidate(c, sid):
    """원본 상품명이 바뀌었을 때: 키워드를 무효로 하고 아직 안 쓴 맥락 이름 후보를 지운다."""
    c.execute("UPDATE ctx_kw SET status='invalid', names_made=0 WHERE source_id=? AND status IN ('ok','retry')", (sid,))
    c.execute("DELETE FROM names WHERE source_id=? AND origin='ctx' AND listing_id IS NULL", (sid,))


# ───────────────────────── 즉시 모드

class _FakeResp:
    def __init__(self, items, kw_n):
        words = ["카페", "사무실", "원룸", "자취방", "매장", "가정", "학교", "펜션", "캠핑", "공장", "창고", "식당", "병원",
                 "교회", "학원", "선물", "집들이", "이사", "개업", "행사", "학생", "주부", "어린이"]
        arr = [{"i": i, "kw": [words[(i * 3 + k) % len(words)] for k in range(kw_n)]} for i in range(1, len(items) + 1)]
        self.content = [{"type": "text", "text": json.dumps(arr, ensure_ascii=False)}]
        self.stop_reason = "end_turn"
        self.usage = type("U", (), {"input_tokens": EST_IN * len(items), "output_tokens": 85 * len(items)})()


def _client(cfg):
    import anthropic
    return anthropic.Anthropic(api_key=(cfg.get("anthropic_api_key") or "").strip(), max_retries=4)


def run_instant(db, ids, progress=None, should_stop=None):
    """즉시 모드: 요청 10개 원본씩, 동시 3건. 실패한 요청의 원본은 재시도 대기."""
    cfg = config.load()
    need = targets(db, ids)
    per = max(1, int(cfg.get("ctx_per_request") or 10))
    est = estimate(db, cfg, ids, "instant")
    st = {"sources": len(need), "requests": 0, "ok": 0, "failed": 0, "empty": 0, "errors": [], "cost_usd": 0.0, "names": {}}
    if not need:
        return {**st, "run_id": None}
    if not has_key(cfg):
        raise RuntimeError("설정 → AI 상품명에서 Anthropic API 키를 먼저 넣어 주세요.")
    groups = [need[i:i + per] for i in range(0, len(need), per)]
    run_id = _new_run(db, cfg, "instant", len(need), len(groups), est["usd"])
    client = None if fake() else _client(cfg)
    model = model_of(cfg)
    kw_n = int(cfg.get("ctx_kw_count") or 12)

    def one(sids):
        rows = {r["id"]: r for r in db.q(f"SELECT id, name, category FROM sources WHERE id IN ({','.join('?' * len(sids))})", sids)}
        items = [rows[s] for s in sids]
        p = params(cfg, items)
        resp = _FakeResp(items, kw_n) if client is None else client.messages.create(**p)
        u = resp.usage
        in_tok = (getattr(u, "input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) \
            + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        out_tok = getattr(u, "output_tokens", 0) or 0
        return sids, items, _text_of(resp.content), in_tok, out_tok

    done = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = []
        for g in groups:
            if should_stop and should_stop():
                break
            futs.append(pool.submit(one, g))
        for f in futs:
            sids = None
            try:
                sids, items, text, in_tok, out_tok = f.result()
                usd = cost(model, in_tok, out_tok, False)
                st["cost_usd"] += usd
                if not text.strip():
                    st["empty"] += 1
                    raise ValueError("빈 답")
                kws = parse(text, len(sids))
                with db.tx() as c:
                    _save_ok(c, sids, [it["name"] for it in items], kws, in_tok, out_tok, run_id)
                _run_add(db, run_id, ok=len(sids), in_tok=in_tok, out_tok=out_tok, usd=usd)
                st["ok"] += len(sids)
            except Exception as e:  # noqa: BLE001 - 요청 하나가 실패해도 나머지는 계속
                failed = sids or groups[futs.index(f)]
                with db.tx() as c:
                    _save_fail(c, failed, e, run_id)
                _run_add(db, run_id, failed=len(failed))
                st["failed"] += len(failed)
                if len(st["errors"]) < 3:
                    st["errors"].append(str(e)[:200])
            st["requests"] += 1
            done += 1
            if progress:
                progress(done, len(groups), f"맥락 키워드 {st['ok']:,}개 원본 받음")
    db.x("UPDATE ctx_run SET ended_at=?, status='done' WHERE id=?", (time.time(), run_id))
    st["names"] = after_saved(db, [s for g in groups for s in g])
    st["run_id"] = run_id
    st["cost_usd"] = round(st["cost_usd"], 5)
    st["krw"] = math.ceil(st["cost_usd"] * float(cfg.get("krw_rate") or 1330))
    st["est_krw"] = est["krw"]
    return st


# ───────────────────────── 일괄 모드

class FakeBatches:
    """시연 모드용 일괄 처리 흉내. 디스크에 적어 두므로 프로그램을 껐다 켜도 이어진다 (만든 지 몇 초 뒤 끝난 것으로 봄)."""

    def _path(self):
        return os.path.join(config.DATA_DIR, "fake_batches.json")

    def _load(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, d):
        with open(self._path(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def create(self, requests):
        d = self._load()
        bid = f"msgbatch_fake{int(time.time() * 1000)}{len(d)}"
        d[bid] = {"at": time.time(), "requests": requests, "canceled": False}
        self._save(d)
        return type("B", (), {"id": bid, "processing_status": "in_progress"})()

    def retrieve(self, bid):
        b = self._load().get(bid)
        ended = b is None or b["canceled"] or time.time() - b["at"] > float(os.environ.get("UPLOADER_FAKE_BATCH_SEC", "3"))
        return type("B", (), {"id": bid, "processing_status": "ended" if ended else "in_progress"})()

    def results(self, bid):
        b = self._load().get(bid) or {"requests": [], "canceled": False}
        for r in b["requests"]:
            if b["canceled"]:
                yield {"custom_id": r["custom_id"], "result": {"type": "canceled"}}
                continue
            n = r["params"]["messages"][0]["content"].count("\n") + 1
            resp = _FakeResp(range(n), 12)
            yield {"custom_id": r["custom_id"], "result": {"type": "succeeded", "message": {
                "content": resp.content, "usage": {"input_tokens": EST_IN * n, "output_tokens": 85 * n}}}}

    def cancel(self, bid):
        d = self._load()
        if bid in d:
            d[bid]["canceled"] = True
            self._save(d)


def _batches(cfg):
    return FakeBatches() if fake() else _client(cfg).messages.batches


def start_batch(db, ids):
    """일괄 처리 시작: 요청을 만들어 보내고 배치 id·요청↔원본 연결을 저장한다. 결과는 poll()이 받는다."""
    cfg = config.load()
    with _lock:
        need = targets(db, ids)
        if not need:
            return {"sources": 0, "requests": 0, "batches": 0, "run_id": None}
        if not has_key(cfg):
            raise RuntimeError("설정 → AI 상품명에서 Anthropic API 키를 먼저 넣어 주세요.")
        per = max(1, int(cfg.get("ctx_per_request") or 10))
        groups = [need[i:i + per] for i in range(0, len(need), per)]
        est = estimate(db, cfg, ids, "batch")
        run_id = _new_run(db, cfg, "batch", len(need), len(groups), est["usd"])
        api = _batches(cfg)
        n_batches = 0
        for b0 in range(0, len(groups), BATCH_MAX_REQUESTS):
            part = groups[b0:b0 + BATCH_MAX_REQUESTS]
            mapping, reqs = {}, []
            for k, sids in enumerate(part, b0 + 1):
                cid = f"kw_{run_id}_{k}"
                assert _CUSTOM_ID.match(cid)
                rows = {r["id"]: r for r in db.q(f"SELECT id, name, category FROM sources WHERE id IN ({','.join('?' * len(sids))})", sids)}
                items = [rows[s] for s in sids]
                mapping[cid] = {"sids": sids, "names": [it["name"] for it in items]}
                reqs.append({"custom_id": cid, "params": params(cfg, items)})
            local = f"local:{run_id}:{b0}"
            # 보내기 전에 먼저 적어 둔다 (보내는 도중 꺼져도 이 원본들이 '처리 중'으로 남아 다시 보내지 않음)
            with db.tx() as c:
                c.execute("INSERT INTO ctx_batch(id, run_id, created_at, status, requests) VALUES(?,?,?,'creating',?)",
                          (local, run_id, time.time(), json.dumps(mapping, ensure_ascii=False)))
                for m in mapping.values():
                    for sid in m["sids"]:
                        c.execute("""INSERT INTO ctx_kw(source_id, status, batch_id, run_id, at) VALUES(?, 'pending', ?, ?, ?)
                            ON CONFLICT(source_id) DO UPDATE SET status='pending', batch_id=excluded.batch_id,
                            run_id=excluded.run_id, at=excluded.at""", (sid, local, run_id, time.time()))
            try:
                b = api.create(requests=reqs)
            except Exception as e:  # noqa: BLE001
                with db.tx() as c:
                    c.execute("DELETE FROM ctx_batch WHERE id=?", (local,))
                    for m in mapping.values():
                        _save_fail(c, m["sids"], f"일괄 처리 만들기 실패: {e}", run_id)
                db.x("UPDATE ctx_run SET status='failed', ended_at=?, note=? WHERE id=?", (time.time(), str(e)[:300], run_id))
                raise RuntimeError(f"일괄 처리를 만들지 못했습니다: {e}") from e
            with db.tx() as c:
                c.execute("UPDATE ctx_batch SET id=?, status='processing' WHERE id=?", (b.id, local))
                c.execute("UPDATE ctx_kw SET batch_id=? WHERE batch_id=?", (b.id, local))
            n_batches += 1
        return {"sources": len(need), "requests": len(groups), "batches": n_batches, "run_id": run_id,
                "est_krw": est["krw"]}


def _usage(u):
    g = (lambda k: (u.get(k) if isinstance(u, dict) else getattr(u, k, 0)) or 0)
    return g("input_tokens") + g("cache_read_input_tokens") + g("cache_creation_input_tokens"), g("output_tokens")


def _get(o, k, default=None):
    return o.get(k, default) if isinstance(o, dict) else getattr(o, k, default)


def poll(db):
    """진행 중인 배치를 확인하고, 끝난 것은 결과를 저장한다. 프로그램을 다시 켜도 db에 적힌 배치를 이어서 본다."""
    cfg = config.load()
    rows = db.q("SELECT * FROM ctx_batch WHERE status IN ('processing','canceling','creating')")
    if not rows:
        return {"checked": 0}
    api = _batches(cfg)
    model_by_run = {r["id"]: r["model"] for r in db.q("SELECT id, model FROM ctx_run")}
    st = {"checked": 0, "ended": 0, "ok": 0, "failed": 0}
    for b in rows:
        if b["status"] == "creating":
            # 보내는 도중 꺼진 배치: 실제로 만들어졌는지 알 수 없으므로 원본을 재시도 대기로 돌린다
            if time.time() - b["created_at"] > 600:
                mapping = json.loads(b["requests"])
                with db.tx() as c:
                    for m in mapping.values():
                        _save_fail(c, m["sids"], "일괄 처리를 보내는 도중 프로그램이 꺼짐", b["run_id"])
                    c.execute("DELETE FROM ctx_batch WHERE id=?", (b["id"],))
            continue
        st["checked"] += 1
        try:
            info = api.retrieve(b["id"])
        except Exception:  # noqa: BLE001 - 네트워크 오류면 다음에 다시 확인
            continue
        db.x("UPDATE ctx_batch SET checked_at=? WHERE id=?", (time.time(), b["id"]))
        if _get(info, "processing_status") != "ended":
            continue
        mapping = json.loads(b["requests"])
        seen, saved = set(), []
        model = model_by_run.get(b["run_id"], model_of(cfg))
        for line in api.results(b["id"]):
            cid = _get(line, "custom_id")
            m = mapping.get(cid)
            if not m or cid in seen:
                continue
            seen.add(cid)
            res = _get(line, "result")
            kind = _get(res, "type")
            if kind == "succeeded":
                msg = _get(res, "message")
                in_tok, out_tok = _usage(_get(msg, "usage") or {})
                usd = cost(model, in_tok, out_tok, True)
                try:
                    text = _text_of(_get(msg, "content") or [])
                    if not text.strip():
                        raise ValueError("빈 답")
                    kws = parse(text, len(m["sids"]))
                except Exception as e:  # noqa: BLE001
                    with db.tx() as c:
                        _save_fail(c, m["sids"], e, b["run_id"])
                    _run_add(db, b["run_id"], failed=len(m["sids"]), in_tok=in_tok, out_tok=out_tok, usd=usd)
                    st["failed"] += len(m["sids"])
                    continue
                with db.tx() as c:
                    _save_ok(c, m["sids"], m["names"], kws, in_tok, out_tok, b["run_id"])
                _run_add(db, b["run_id"], ok=len(m["sids"]), in_tok=in_tok, out_tok=out_tok, usd=usd)
                st["ok"] += len(m["sids"])
                saved += m["sids"]
            else:   # errored / expired / canceled → 재시도 대기 (과금 없음)
                with db.tx() as c:
                    _save_fail(c, m["sids"], f"일괄 처리 결과: {kind}", b["run_id"])
                _run_add(db, b["run_id"], failed=len(m["sids"]))
                st["failed"] += len(m["sids"])
        missing = [cid for cid in mapping if cid not in seen]   # 결과에 없는 요청도 재시도 대기 (빠뜨리지 않게)
        if missing:
            with db.tx() as c:
                for cid in missing:
                    _save_fail(c, mapping[cid]["sids"], "일괄 처리 결과에 없음", b["run_id"])
            _run_add(db, b["run_id"], failed=sum(len(mapping[cid]["sids"]) for cid in missing))
        with db.tx() as c:
            c.execute("UPDATE ctx_batch SET status='ended', ended_at=? WHERE id=?", (time.time(), b["id"]))
            if not c.execute("SELECT 1 FROM ctx_batch WHERE run_id=? AND status!='ended'", (b["run_id"],)).fetchone():
                c.execute("UPDATE ctx_run SET ended_at=?, status=CASE WHEN status='canceling' THEN 'canceled' ELSE 'done' END WHERE id=?",
                          (time.time(), b["run_id"]))
        st["ended"] += 1
        after_saved(db, saved)
    return st


def cancel(db):
    """진행 중인 일괄 처리 취소. 이미 끝난 요청의 결과는 poll()이 저장한다."""
    cfg = config.load()
    api = _batches(cfg)
    n = 0
    for b in db.q("SELECT id, run_id FROM ctx_batch WHERE status='processing'"):
        try:
            api.cancel(b["id"])
        except Exception:  # noqa: BLE001
            continue
        db.x("UPDATE ctx_batch SET status='canceling' WHERE id=?", (b["id"],))
        db.x("UPDATE ctx_run SET status='canceling' WHERE id=?", (b["run_id"],))
        n += 1
    return {"canceled": n}


def status(db):
    rows = db.q("SELECT id, run_id, created_at, status, checked_at, requests FROM ctx_batch WHERE status!='ended' ORDER BY created_at")
    out = []
    for r in rows:
        m = json.loads(r["requests"])
        out.append({"id": r["id"], "run_id": r["run_id"], "created_at": r["created_at"], "status": r["status"],
                    "checked_at": r["checked_at"], "requests": len(m), "sources": sum(len(x["sids"]) for x in m.values())})
    st = db.one("""SELECT SUM(status='ok') AS ok, SUM(status='pending') AS pending, SUM(status='retry') AS retry,
        SUM(status='invalid') AS invalid FROM ctx_kw""")
    return {"batches": out, **{k: st[k] or 0 for k in ("ok", "pending", "retry", "invalid")}}


def runs(db, limit=100):
    return db.q("SELECT * FROM ctx_run ORDER BY id DESC LIMIT ?", (limit,))


def poll_loop(db, interval=60):
    """프로그램이 켜져 있는 동안 1분마다 배치를 확인한다 (켜자마자 한 번)."""
    def loop():
        while True:
            try:
                poll(db)
            except Exception:  # noqa: BLE001 - 다음 확인 때 다시
                pass
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True, name="ctx-batch-poll").start()


def source_info(db, sid):
    r = db.one("SELECT * FROM ctx_kw WHERE source_id=?", (sid,))
    if not r:
        return {"status": "", "words": [], "usable": []}
    src = db.one("SELECT name FROM sources WHERE id=?", (sid,))
    words = json.loads(r["words"] or "[]")
    toks, head, _ = ctxname.clean_origin(src["name"], forbidden(db), int(config.load().get("ctx_head_n") or 4))
    usable = ctxname.filter_ai_words(words, toks, head, forbidden(db))
    return {"status": r["status"], "words": words, "usable": usable, "at": r["at"], "error": r["error"],
            "in_tok": r["in_tok"], "out_tok": r["out_tok"]}
