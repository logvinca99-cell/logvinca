"""생활화학제품·살생물제 인증 판정.

네이버는 생활화학/살생물제 인증 대상 카테고리(카테고리 조회의 exceptionalCategories에 CHEMICAL_CERTIFICATION)의 상품에
인증 정보(신고번호)나 '인증 대상 아님'(certificationTargetExcludeContent.chemicalCertifiedProductExclusionYn=true)을 받는다.
'인증 대상 아님'은 법에서 정한 화학제품이 아닐 때만 쓸 수 있다(판매자 책임).

그래서 그 카테고리 상품을 셋으로 나눈다
  tool      화학제품이 아닌 물건(분무기·공병·디스펜서·기계 …) → 카테고리 그대로 + '인증 대상 아님'
  chemical  화학제품 자체(세제·방향제 오일·살충제·코팅제·접착제·양초 …) → 등록 보류 (검수 후 정리)
  unclear   단어만으로 못 정함 → AI가 판단, 그래도 애매하면 사람이 정함
"""

import json
import os
import re
import threading
import time

from . import config

CACHE_PATH = os.path.join(config.DATA_DIR, "chem_categories.json")   # {카테고리 번호: 인증 대상이면 true}
_lock = threading.Lock()
_cache = {"mtime": None, "map": {}}

KINDS = {"tool": "물건 (인증 대상 아님)", "chemical": "화학제품 (등록 보류)", "unclear": "애매 (사람이 정함)"}

# 화학제품 자체·화학제품이 들어 있는 것
CHEM_WORDS = ("원액", "리필액", "액상", "세제", "세정제", "세척제", "클리너액", "방향제", "디퓨저오일", "아로마오일", "향오일",
              "탈취제", "섬유탈취", "살충", "살균", "소독", "기피제", "방충제", "제충", "코팅제", "광택제", "왁스", "발수제",
              "접착제", "본드", "순간접착", "실란트", "윤활제", "구리스", "방청제", "녹제거", "양초", "캔들", "습기제거제",
              "제습제", "표백제", "유연제", "김서림방지", "워셔액", "부동액", "잉크", "페인트", "락카", "도료", "염색약", "곰팡이제거")
# 물건 (화학제품이 아닌 도구·용기·기계)
TOOL_WORDS = ("분무기", "디스펜서", "용기", "공병", "빈병", "케이스", "홀더", "거치대", "브러시", "브러쉬", "솔", "기계", "펌프",
              "노즐", "스펀지", "걸레", "리드스틱", "퇴치기", "포충기", "가습기", "분사기", "스프레이건", "건", "워머", "보관함",
              "정리함", "트레이", "커버", "받침", "클립", "전기", "충전식", "USB", "LED", "모터", "청소기", "공구", "장갑", "마스크")


def _load():
    try:
        mt = os.path.getmtime(CACHE_PATH)
    except OSError:
        return {}
    if _cache["mtime"] != mt:
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                _cache["map"] = {str(k): bool(v) for k, v in json.load(f).items()}
        except (OSError, ValueError):
            _cache["map"] = {}
        _cache["mtime"] = mt
    return _cache["map"]


def is_chemical(cat_id):
    """인증 대상 카테고리면 True, 아니면 False, 아직 모르면 None."""
    return _load().get(str(cat_id)) if cat_id else None


def remember(cat_id, flag=True):
    if not cat_id:
        return
    with _lock:
        m = dict(_load())
        if m.get(str(cat_id)) == bool(flag):
            return
        m[str(cat_id)] = bool(flag)
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f)


def is_chem_error(text):
    """네이버가 생활화학/살생물제 인증으로 거절한 오류인지."""
    t = str(text or "")
    return "productCertificationInfos" in t and ("생활화학" in t or "살생물" in t)


def check_categories(db, cat_ids, progress=None, should_stop=None):
    """아직 모르는 카테고리를 네이버 카테고리 조회로 확인해 기억한다. (확인한 수, 실패 사유)"""
    from . import naver
    todo = [c for c in dict.fromkeys(str(x) for x in cat_ids if x) if is_chemical(c) is None]
    if not todo:
        return 0, ""
    client, err = None, ""
    for s in db.q("SELECT id FROM stores ORDER BY sort, id"):
        try:
            client = naver.make_client(db.store(s["id"], with_secret=True))
            break
        except naver.ApiError as e:
            err = str(e)
    if client is None:
        return 0, err or "API 키가 있는 스토어가 없어 카테고리를 확인하지 못했습니다."
    n = 0
    for i, cid in enumerate(todo, 1):
        if should_stop and should_stop():
            break
        try:
            info = client.category_info(cid)
            remember(cid, "CHEMICAL_CERTIFICATION" in (info.get("exceptionalCategories") or []))
            n += 1
        except Exception as e:  # noqa: BLE001 - 하나 실패해도 나머지는 계속
            err = str(e)[:200]
        if progress:
            progress(i, len(todo), f"생활화학 인증 대상 카테고리 확인 {i}/{len(todo)}")
    return n, err


def rule(name, options=""):
    """단어로 먼저 판정: (tool / chemical / unclear, 이유)."""
    t = re.sub(r"\s+", "", f"{name} {options}")
    chem = [w for w in CHEM_WORDS if w in t]
    tool = [w for w in TOOL_WORDS if w in t]
    if chem and not tool:
        return "chemical", f"화학제품 단어: {', '.join(chem[:3])}"
    if tool and not chem:
        return "tool", f"물건 단어: {', '.join(tool[:3])}"
    if chem and tool:
        return "unclear", f"둘 다 있음 — 화학 {', '.join(chem[:2])} / 물건 {', '.join(tool[:2])}"
    return "unclear", "판정할 단어 없음"


SYSTEM = """너는 한국 온라인 쇼핑몰 상품이 「생활화학제품 및 살생물제의 안전관리에 관한 법률」의 안전확인·승인 대상 화학제품인지 판정한다.
상품마다 판매하는 물건 자체가 아래 중 무엇인지 고른다.
- chemical: 판매 물건이 화학제품이거나 화학제품이 들어 있다 (세정제·세탁세제·섬유유연제·표백제·방향제(액·젤·고체·향 카트리지 포함)·탈취제·
  살충제·기피제·살균제·소독제·코팅제·광택제·왁스·접착제·윤활제·방청제·양초·습기제거제·김서림방지제·워셔액·페인트 등). 리필액·향 카트리지가
  함께 들어 있는 세트도 chemical.
- tool: 화학제품이 전혀 들어 있지 않은 도구·용기·기계·액세서리 (빈 분무기·공병·디스펜서·브러시·청소도구·전기 모기 퇴치기·가습기·캔들워머·
  디퓨저 빈 병·리드스틱만 등).
- unclear: 상품명·옵션만으로 들어 있는지 알 수 없다.
확실하지 않으면 chemical이나 unclear를 고른다 (tool은 화학제품이 없다는 것이 분명할 때만).
reason은 한국어 20자 안팎으로."""

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "kind": {"type": "string", "enum": ["tool", "chemical", "unclear"]},
                                     "reason": {"type": "string"}}, "required": ["id", "kind", "reason"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}


def _ai(cfg, items):
    """items: [{id, name, category, options}] → {id: (kind, reason)}. 키가 없거나 실패하면 빈 사전."""
    from . import ctxkw
    if ctxkw.fake():
        out = {}
        for it in items:
            k = "chemical" if re.search(r"향|오일|액|리필", it["name"]) else "tool"
            out[str(it["id"])] = (k, "시연 모드 판정")
        return out
    if not (cfg.get("anthropic_api_key") or "").strip():
        return {}
    model = ctxkw.model_of(cfg)
    client = ctxkw._client(cfg)
    out = {}
    for i in range(0, len(items), 20):
        group = items[i:i + 20]
        rows = [{"id": str(x["id"]), "name": x["name"], "category": x.get("category") or "", "options": x.get("options") or ""}
                for x in group]
        try:
            resp = client.messages.create(
                model=model, max_tokens=2500, system=SYSTEM,
                messages=[{"role": "user", "content": json.dumps({"products": rows}, ensure_ascii=False)}],
                thinking={"type": "disabled"} if "haiku" in model else {"type": "between_tools"},
                extra_body={"output_config": {"format": {"type": "json_schema", "schema": SCHEMA}}})
            text = "".join(getattr(b, "text", "") for b in resp.content)
            data = json.loads(text[text.find("{"):text.rfind("}") + 1])
            for x in data.get("items") or []:
                if x.get("kind") in KINDS:
                    out[str(x.get("id"))] = (x["kind"], "AI: " + str(x.get("reason") or "")[:60])
        except Exception:  # noqa: BLE001 - AI가 안 되면 그 묶음은 애매로 남김
            continue
    return out


def classify(cfg, items, use_ai=True):
    """items: [{id, name, category, options}] → {id: (kind, reason)}. 단어로 먼저, 애매한 것만 AI."""
    out = {}
    unclear = []
    for it in items:
        kind, why = rule(it["name"], it.get("options") or "")
        out[str(it["id"])] = (kind, why)
        if kind == "unclear":
            unclear.append(it)
    if unclear and use_ai:
        out.update(_ai(cfg, unclear))
    return out


def option_text(row):
    """옵션 이름들 (판정 참고)."""
    o = row.get("옵션상품") if isinstance(row.get("옵션상품"), dict) else {}
    names = []
    for c in (o.get("optionCombinations") or [])[:20]:
        if isinstance(c, dict):
            names += [str(c.get(k)) for k in ("optionName1", "optionName2", "optionName3") if c.get(k)]
    return " ".join(dict.fromkeys(names))[:300]


# ───────────────────────── 원본 상품 쪽 (이미 불러온 원본·실패한 복사본)

def judge_sources(db, sids, progress=None, should_stop=None):
    """원본들을 판정해 원본에 저장. 물건이면 그 원본의 생활화학 오류로 실패한 복사본을 다시 '등록 대기'로."""
    from . import convert, naver
    from .db import unpack
    cfg = config.load()
    cats = naver.cached_categories() or {}
    rows = []
    for i in range(0, len(sids), 500):
        chunk = list(sids)[i:i + 500]
        rows += db.q(f"SELECT id, name, data, category_fix FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk)
    items, catids = [], {}
    for r in rows:
        row = convert.with_category_fix(unpack(r["data"]), r["category_fix"])
        cid, _ = convert.find_category(row.get("카테고리"), cats, cfg)
        catids[r["id"]] = cid
        items.append({"id": r["id"], "name": r["name"], "category": row.get("카테고리") or "", "options": option_text(row)})
    if progress:
        progress(0, len(items), "인증 대상 카테고리 확인 중")
    check_categories(db, [c for c in catids.values() if c], progress, should_stop)
    if progress:
        progress(0, len(items), "물건·화학제품 판정 중 (애매한 것은 AI)")
    res = classify(cfg, items)
    st = {"total": len(items), "tool": 0, "chemical": 0, "unclear": 0, "requeued": 0, "not_target": 0}
    now = time.time()
    with db.tx() as c:
        for it in items:
            kind, why = res.get(str(it["id"]), ("unclear", ""))
            st[kind] += 1
            if is_chemical(catids.get(it["id"])) is False:
                st["not_target"] += 1   # 지금 카테고리는 인증 대상이 아님 (판정은 남겨 둠)
            c.execute("UPDATE sources SET chem_judge=?, chem_reason=?, updated_at=? WHERE id=?", (kind, why[:200], now, it["id"]))
            if kind == "tool":
                st["requeued"] += c.execute("""UPDATE listings SET status='planned', message='' WHERE source_id=? AND status='fail'
                    AND (message LIKE '%productCertificationInfos%' OR message LIKE '%생활화학%')""", (it["id"],)).rowcount
    return st


def set_judge(db, sids, kind):
    """사람이 판정을 바꿈 (tool / chemical / unclear / '' 지움)."""
    if kind not in ("tool", "chemical", "unclear", ""):
        raise ValueError("판정 값이 올바르지 않습니다.")
    n = 0
    with db.tx() as c:
        for i in range(0, len(sids), 900):
            chunk = list(sids)[i:i + 900]
            m = ",".join("?" * len(chunk))
            n += c.execute(f"UPDATE sources SET chem_judge=?, chem_reason=? WHERE id IN ({m})",
                           (kind, "직접 정함" if kind else "", *chunk)).rowcount
            if kind == "tool":
                c.execute(f"""UPDATE listings SET status='planned', message='' WHERE source_id IN ({m}) AND status='fail'
                    AND (message LIKE '%productCertificationInfos%' OR message LIKE '%생활화학%')""", chunk)
    return n


def delete_sources_everywhere(db, sids):
    """원본과 그 원본의 모든 복사본 삭제. 네이버에 올라가 판매 중인 복사본은 내리기를 걸고(판매 이력·잠금은 보호),
    다 내려가면 원본을 자동으로 휴지통으로. (바로 지운 원본 수, 내리기 건 복사본 번호들, 판매 이력으로 남긴 원본 수)"""
    from . import inventory, trash
    sids = [int(s) for s in sids]
    live = {}
    for i in range(0, len(sids), 900):
        chunk = sids[i:i + 900]
        for r in db.q(f"""SELECT id, source_id, locked FROM listings WHERE source_id IN ({','.join('?' * len(chunk))})
                AND status!='deleted' AND origin_no!=''""", chunk):
            live.setdefault(r["source_id"], []).append(r)
    kept = {sid for sid, ls in live.items() if any(x["locked"] for x in ls)}   # 판매 이력·직접 잠금이 있는 원본은 남김
    later = [sid for sid in live if sid not in kept]
    now = [sid for sid in sids if sid not in live]
    st = trash.trash_sources(db, now) if now else {"moved": 0, "skipped_live": 0}
    ids = []
    if later:
        n, _, ids = inventory.schedule_op(db, {"ids": [x["id"] for sid in later for x in live[sid]]}, "delete")
        with db.tx() as c:
            for sid in later:
                c.execute("UPDATE sources SET drop_pending=1 WHERE id=?", (sid,))
        # 아직 안 올린 복사본은 지금 휴지통으로 (올라가 있는 것은 내린 뒤 원본과 함께)
        pending = [r["id"] for r in db.q(f"""SELECT id FROM listings WHERE source_id IN ({','.join('?' * len(later))})
            AND origin_no='' AND status NOT IN ('queued','running')""", later)]
        if pending:
            trash.trash_listings(db, pending)
    return {"trashed": st["moved"], "drop_scheduled": ids, "drop_sources": len(later), "kept_sold": len(kept)}


def after_drop(db, source_id):
    """내리기가 끝난 복사본의 원본이 '다 내리면 지우기'였고 올라가 있는 복사본이 더 없으면 휴지통으로."""
    from . import trash
    s = db.one("SELECT drop_pending FROM sources WHERE id=?", (source_id,))
    if not s or not s["drop_pending"]:
        return False
    left = db.one("""SELECT COUNT(*) AS n FROM listings WHERE source_id=? AND status!='deleted'
        AND (origin_no!='' OR status IN ('queued','running'))""", (source_id,))["n"]
    if left:
        return False
    return trash.trash_sources(db, [source_id])["moved"] > 0
