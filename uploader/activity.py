"""작업 기록: 프로그램에서 실행한 일을 언제·무엇을·몇 건·결과로 남긴다 (프로그램을 껐다 켜도 남음).

- 오래 걸리는 작업(tasks): 시작할 때 '진행 중'으로 넣고 끝나면 결과·걸린 시간을 채운다.
- 바로 끝나는 작업(복사본 삭제, 대기에 넣기, 카테고리 맞추기 저장 …): 요청이 성공하면 한 줄.
- 설정·스토어 템플릿 변경: 무엇이 무엇에서 무엇으로 바뀌었는지 (키·비밀번호 값은 남기지 않음).
"""

import json
import re
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    grp TEXT NOT NULL,                    -- 걸러 보기용 묶음: 상품명 / AI 키워드 / 복사·등록 / 복사본 / 원본 / 스토어 / 설정 / 기타
    kind TEXT NOT NULL,                   -- 작업 종류 (task kind 또는 요청 이름)
    title TEXT NOT NULL,
    store TEXT NOT NULL DEFAULT '',
    count INTEGER,                        -- 대상 수 (알 수 있을 때)
    started_at REAL NOT NULL,
    ended_at REAL,
    status TEXT NOT NULL DEFAULT 'done',  -- running / done / stopped / error / lost(프로그램이 꺼져 끝을 못 봄)
    result TEXT NOT NULL DEFAULT '',      -- 한 줄 결과
    detail TEXT NOT NULL DEFAULT '',      -- 작업 결과 JSON (화면이 진행 카드와 같은 문장으로 보여 줌) · 설정 변경 목록
    error TEXT NOT NULL DEFAULT '',
    task_id INTEGER
);
CREATE INDEX IF NOT EXISTS activity_started ON activity(started_at);
"""

# 오래 걸리는 작업 종류 → 묶음
TASK_GROUP = {"mail": "메일함", "bulkedit": "올린 상품 일괄 변경", "rename": "상품명", "names": "상품명", "ctxkw": "AI 키워드", "plan": "복사·등록", "import": "원본",
              "revalidate": "원본", "bait": "복사본", "orders": "주문", "keywords": "상품명", "kipris": "금지어·사전",
              "lexicon": "금지어·사전", "dictfile": "금지어·사전"}

SECRET = re.compile(r"key|secret|password|token|license|client_id", re.I)


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)
        # 지난번에 프로그램이 꺼질 때 진행 중이던 작업 → 끝을 못 봄
        c.execute("UPDATE activity SET status='lost', ended_at=COALESCE(ended_at, started_at), "
                  "error=CASE WHEN error='' THEN '프로그램이 꺼져 끝을 확인하지 못함' ELSE error END WHERE status='running'")


def add(db, grp, kind, title, count=None, result="", detail=None, status="done", error="", store="",
        started=None, ended=None, task_id=None):
    now = time.time()
    return db.x("""INSERT INTO activity(grp, kind, title, store, count, started_at, ended_at, status, result, detail, error, task_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (grp, kind, str(title)[:300], str(store or "")[:100], count, started or now,
                 ended if ended is not None else (None if status == "running" else now), status, str(result or "")[:500],
                 _dump(detail), str(error or "")[:500], task_id))


def _dump(v):
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        return v[:20000]
    try:
        s = json.dumps(v, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return ""
    if len(s) <= 20000:
        return s
    # 너무 크면 숫자·짧은 글자·짧은 목록만 남긴다 (진행 카드 문장에 쓰는 값은 이것뿐)
    if isinstance(v, dict):
        small = {k: x for k, x in v.items() if isinstance(x, (int, float, bool)) or (isinstance(x, str) and len(x) < 300)
                 or (isinstance(x, list) and len(json.dumps(x, ensure_ascii=False, default=str)) < 1000)}
        return json.dumps(small, ensure_ascii=False, default=str)[:20000]
    return ""


# ───────────────────────── 오래 걸리는 작업

def task_hooks(db):
    """Tasks에 붙이는 (시작, 끝) 함수."""
    def on_start(t):
        try:
            t["_act"] = add(db, TASK_GROUP.get(t["kind"], "기타"), t["kind"], t["title"], status="running",
                            started=t["started_at"], task_id=t["id"])
        except Exception:  # noqa: BLE001 - 기록 실패로 작업을 막지 않는다
            t["_act"] = None

    def on_end(t):
        aid = t.get("_act")
        if not aid:
            return
        r = t.get("result")
        try:
            db.x("UPDATE activity SET ended_at=?, status=?, detail=?, error=?, count=COALESCE(count, ?) WHERE id=?",
                 (t["ended_at"] or time.time(), t["status"], _dump(r), str(t.get("error") or "")[:500], t.get("total"), aid))
        except Exception:  # noqa: BLE001
            pass
    return on_start, on_end


# ───────────────────────── 바로 끝나는 작업 (요청 하나)

def _n(b, *keys):
    for k in keys:
        v = b.get(k)
        if isinstance(v, list):
            return len(v)
    return None


def _ids_note(b):
    """요청이 고른 대상: ids 목록이면 개수, 아니면 '조건에 맞는 전체'."""
    n = _n(b, "ids", "listing_ids", "source_ids")
    return n, ("" if n is not None else ("조건에 맞는 전체" if any(k in b for k in ("q", "status", "store_id", "filter", "all")) else ""))


OP = {"refresh": "최신화", "delete": "내리기", "reupload": "다시 올리기", "unschedule": "대기 빼기", "cancel": "대기 빼기"}


def _schedule(b, r):
    op = OP.get(b.get("op"), b.get("op") or "")
    n = r.get("count", r.get("scheduled"))
    if n is None and isinstance(r.get("ids"), list):
        n = len(r["ids"])
    return f"{op} {'바로 하기' if b.get('now') else '대기에 넣기'}", n, r.get("message") or ""


def _count_of(r, *keys):
    for k in keys:
        if isinstance(r.get(k), (int, float)):
            return int(r[k])
        if isinstance(r.get(k), list):
            return len(r[k])
    return None


# 요청 이름 → (묶음, 제목 또는 함수(body, resp) → (제목, 대상 수, 결과))
ACTIONS = {
    "schedule": ("복사본", _schedule),
    "listings_delete": ("복사본", lambda b, r: ("복사본 삭제 (휴지통으로)" + (" + 원본도" if b.get("with_source") else ""),
                                              _count_of(r, "count", "moved", "trashed", "ids"),
                                              f"원본 {r.get('sources_moved', 0)}개도 휴지통으로" + (f" · 다른 스토어에 올라가 있어 원본은 남긴 {r['sources_skipped_live']}개" if r.get("sources_skipped_live") else "")
                                              if b.get("with_source") else "")),
    "listings_reset_round": ("복사본", lambda b, r: ("회차 초기화 (1회차로)" + (" · 모든 스토어 전체" if b.get("all") else ""), r.get("count"), "")),
    "sources_delete": ("원본", lambda b, r: ("원본 삭제 (휴지통으로)", _count_of(r, "count", "moved", "trashed", "ids"), "")),
    "trash_restore": ("휴지통", lambda b, r: ("휴지통에서 되살림", _count_of(r, "count", "restored", "ids"), "")),
    "trash_purge": ("휴지통", lambda b, r: ("휴지통 비우기" if b.get("empty") else "휴지통에서 완전히 삭제", _count_of(r, "count", "purged", "deleted"), "")),
    "listing_set_name": ("상품명", lambda b, r: ("상품명 직접 고침", 1, str(r.get("name") or "")[:120])),
    "lock": ("복사본", lambda b, r: ("잠금" if b.get("lock") else "잠금 풀기", r.get("count"), f"아직 잠긴 것 {r['still_locked']}건" if r.get("still_locked") else "")),
    "cancel": ("복사본", lambda b, r: ("대기 취소", r.get("cancelled"), "")),
    "sources_bulk_edit": ("원본", lambda b, r: ("원본 일괄 수정" + (" · 판매자코드 비우기" if b.get("clear_seller_code") else "")
                                               + (f" · 재고 {b.get('stock')}" if b.get("stock") not in (None, "") else ""), _count_of(r, "count", "updated"), "")),
    "categories_map": ("원본", lambda b, r: ("카테고리 맞추기 저장", r.get("count"), "")),
    "collect_pause": ("수집", lambda b, r: ("상품 수집 일시정지" if b.get("on", True) else "상품 수집 이어서", None, "")),
    "collect_stop": ("수집", lambda b, r: ("상품 수집 중지", None, "")),
    "collect_items_delete": ("수집", lambda b, r: ("수집함에서 지움", r.get("count"), "")),
    "sources_category": ("원본", lambda b, r: (("카테고리 직접 정함: " + str(b.get("set_category"))) if b.get("set_category") else "카테고리를 엑셀 값으로 되돌림",
                                              r.get("count"), "")),
    "refresh_categories": ("원본", "네이버 카테고리 목록 받기"),
    "source_core": ("원본", lambda b, r: ("핵심 단어 직접 지정", 1, str(b.get("core") or ""))),
    "add_name": ("상품명", lambda b, r: ("상품명 후보 직접 추가", 1, "")),
    "delete_name": ("상품명", "상품명 후보 삭제"),
    "ctx_block": ("상품명", lambda b, r: (f"AI 단어 {'차단' if b.get('block', True) else '차단 풀기'}: {b.get('word')}", r.get("sources"),
                                            f"새 이름 {r['renamed']}건" if r.get("renamed") else "")),
    "ctx_cancel": ("AI 키워드", "AI 키워드 일괄 처리 중지"),
    "lexicon_blocked_save": ("금지어·사전", lambda b, r: ("금지어 저장", r.get("count"), "")),
    "lexicon_blocked_import": ("금지어·사전", lambda b, r: ("금지어 파일 가져오기", r.get("count"), "")),
    "lexicon_save": ("금지어·사전", "사전 저장"),
    "trademark_allow": ("금지어·사전", lambda b, r: (f"상표 단어 허용: {b.get('word', '')}", None, "")),
    "keywords_off": ("상품명", lambda b, r: (f"네이버 키워드 {'끄기' if b.get('off') else '켜기'}: {b.get('word', '')}", None, "")),
    "source_aiwords": ("상품명", "원본 AI 단어 끄기·켜기"),
    "save_store": ("스토어", lambda b, r: (("스토어 수정" if b.get("id") else "스토어 추가") + f": {b.get('name', '')}", None, "")),
    "bulk_stores": ("스토어", lambda b, r: ("스토어 여러 개 추가", _count_of(r, "added", "count"), "")),
    "delete_store": ("스토어", "스토어 삭제"),
    "test_store": ("스토어", lambda b, r: ("스토어 연결 확인", None, str(r.get("message") or r.get("result") or "")[:200])),
    "store_goguma": ("스토어", lambda b, r: (f"고구마 개수: {b.get('count')}", None, "")),
    "store_region": ("스토어", lambda b, r: (f"출고 형태: {({'overseas': '해외', 'domestic': '국내'}).get(b.get('region'), '표시 없음')}", None, "")),
    "save_business": ("스토어", lambda b, r: (f"사업자 저장: {b.get('name', '')}", None, "")),
    "delete_business": ("스토어", "사업자 삭제"),
    "order_businesses": ("스토어", "사업자 순서 바꿈"),
    "order_stores": ("스토어", "스토어 순서 바꿈"),
    "store_template_image": ("스토어", "상하단 이미지 올림"),
    "store_template_image_del": ("스토어", "상하단 이미지 지움"),
    "store_watermark": ("스토어", "워터마크 로고 올림"),
    "store_watermark_del": ("스토어", "워터마크 로고 지움"),
    "order_rematch": ("주문", lambda b, r: ("주문 다시 맞추기", r.get("matched"), "")),
    "ctx_start": ("AI 키워드", lambda b, r: ("AI 키워드 받기(일괄) 보냄", r.get("sources"),
                                            f"요청 {r.get('requests')}건 · 예상 약 {r.get('est_krw')}원 · 결과가 오면 '일괄 결과 도착' 줄이 남음"
                                            if r.get("started") else str(r.get("message") or ""))),
    "run_control": ("복사·등록", None),   # 제목은 action으로
    "settings_reapply": ("설정", "설정을 기존 상품에 다시 적용"),
    "names_import": ("상품명", "상품명 파일 가져오기"),
    "mail_handled": ("메일함", lambda b, r: ("메일 확인함 표시" if b.get("handled", True) else "메일 확인함 풀기", 1, "")),
    "bulk_create": ("올린 상품 일괄 변경", lambda b, r: (f"일괄 변경 작업 만듦 #{r.get('id')}", sum(x.get("total", 0) for x in r.get("per_store") or []) or None,
                                                       str(r.get("summary") or ""))),
    "bulk_action": ("올린 상품 일괄 변경", lambda b, r: ("일괄 변경 실패만 다시 대기로", r.get("count"), "")),
}
SKIP = {"save_settings", "store_template_save", "task_stop"}   # 따로 기록하거나 기록할 필요 없음


def from_request(db, endpoint, view_args, b, resp, store_name=""):
    """성공한 POST 요청 하나를 기록. 작업(task)을 시작한 요청은 task 쪽에서 남기므로 건너뜀."""
    if endpoint in SKIP or endpoint not in ACTIONS:
        return
    if isinstance(resp, dict) and resp.get("task"):
        return
    grp, spec = ACTIONS[endpoint]
    r = resp if isinstance(resp, dict) else {}
    count, result = _ids_note(b)[0], ""
    if endpoint == "run_control":
        title = {"pause": "네이버 등록 일시정지", "resume": "네이버 등록 계속", "stop": "네이버 등록 중지"}.get(
            (view_args or {}).get("action"), f"네이버 등록 {(view_args or {}).get('action', '')}")
    elif callable(spec):
        title, c, result = spec(b, r)
        count = c if c is not None else count
    else:
        title = spec or endpoint
    add(db, grp, endpoint, title, count=count, result=result, store=store_name)


# ───────────────────────── 설정·템플릿 변경

def _show(k, v):
    if SECRET.search(k):
        return "(바뀜)" if v else "(비움)"
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False)
    else:
        s = "" if v is None else str(v)
    return s if len(s) <= 120 else s[:117] + "…"


def diff(before, after, keys=None):
    """바뀐 값 목록 [{key, old, new}] (비밀값은 값 없이)."""
    out = []
    for k in (keys or sorted(set(before) | set(after))):
        if k.startswith("_"):
            continue
        a, b = before.get(k), after.get(k)
        if a == b or (a in (None, "") and b in (None, "")):
            continue
        out.append({"key": k, "old": _show(k, a), "new": _show(k, b)})
    return out


def settings_changed(db, before, after):
    ch = diff(before, after)
    if ch:
        add(db, "설정", "settings", f"설정 변경 {len(ch)}개", count=len(ch), detail=ch)


TEMPLATE_KEYS = {"tpl_price_pct": "가격 조정 %", "tpl_discount_pct": "표시 할인율 %", "tpl_jitter_min": "가격 흔들기 최소 %",
                 "tpl_jitter_max": "가격 흔들기 최대 %", "tpl_customs": "관부가세", "tpl_ship_addr": "출고지 번호",
                 "tpl_return_addr": "반품지 번호", "wm_text": "워터마크 글자", "tpl_top_html": "상단", "tpl_bottom_html": "하단",
                 "tpl_opt_style": "옵션표 모양", "tpl_opt_color": "옵션표 색"}


def template_changed(db, store, before, after):
    ch = diff(before, after, list(TEMPLATE_KEYS))
    for x in ch:
        x["label"] = TEMPLATE_KEYS[x["key"]]
        if x["key"] in ("tpl_top_html", "tpl_bottom_html"):
            x["old"], x["new"] = "", "(바뀜)"
    if ch:
        add(db, "스토어", "store_template", f"스토어 템플릿 변경 {len(ch)}개", count=len(ch), detail=ch,
            store=(store or {}).get("name") or "")


def query(db, grp="", q="", days=None, page=1, size=100):
    w, a = [], []
    if grp:
        w.append("grp=?")
        a.append(grp)
    if q:
        w.append("(title LIKE ? OR result LIKE ? OR store LIKE ? OR detail LIKE ?)")
        a += [f"%{q}%"] * 4
    if days:
        w.append("started_at>=?")
        a.append(time.time() - float(days) * 86400)
    where = (" WHERE " + " AND ".join(w)) if w else ""
    total = db.one(f"SELECT COUNT(*) AS n FROM activity{where}", a)["n"]
    rows = db.q(f"SELECT * FROM activity{where} ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
                (*a, size, (max(1, page) - 1) * size))
    groups = [r["grp"] for r in db.q("SELECT grp FROM activity GROUP BY grp ORDER BY MIN(id)")]
    return {"rows": rows, "total": total, "groups": groups}
