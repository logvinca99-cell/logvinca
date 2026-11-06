"""기존 상품 가져오기: 다른 방법으로 이미 스토어에 올린 상품을 이 프로그램으로.

업로드했던 셀업 엑셀 + 그 스토어의 상품 목록(커머스API)을 판매자코드로 맞춰서
  - 스토어에 있는 상품 → 원본(엑셀 내용, 스토어 상하단 빼고) + 그 스토어의 판매 중 복사본으로 연결
  - 엑셀에는 있는데 스토어에 없는 상품(직접 지운 것) → 버림
  - 스토어에는 있는데 엑셀에 없는 상품 → 가져오지 않고 목록으로 알려 줌
가져온 원본은 '가져옴 · 원본 이름 없음'(올라가 있던 이름이 원본 자리), 가져온 복사본은 최신화 때 지금 가격 그대로(가격 고정).
"""

import csv
import io
import json
import os
import re
import time
import uuid
from collections import Counter

from . import clean, config, excel, inventory, namegen, naver

SCHEMA = """
CREATE TABLE IF NOT EXISTS adopt_run (
    id INTEGER PRIMARY KEY,
    created_at REAL NOT NULL,
    finished_at REAL,
    store_id INTEGER,
    store_name TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    stats TEXT NOT NULL DEFAULT '{}',       -- 연결·이미 연결·버림·스토어에만·같은 사진·상하단 뺀 수 등
    status TEXT NOT NULL DEFAULT 'running'  -- running / done / error / stopped
);
CREATE TABLE IF NOT EXISTS adopt_item (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                     -- linked(연결) / already(이미 연결) / dropped(스토어에 없어 뺌) / store_only(스토어에만)
                                            -- dup_same(같은 스토어에 같은 상품 두 번) / dup(같은 사진 다른 스토어)
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    channel_no TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    reg_at REAL,
    source_id INTEGER,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_adopt_item ON adopt_item(run_id, kind);
"""

KIND_LABEL = {"linked": "연결", "already": "이미 연결돼 있음", "dropped": "스토어에 없어서 뺌", "store_only": "스토어에만 있음 (파일에 없음)",
              "dup_same": "같은 스토어에 같은 상품 두 번", "dup": "같은 대표 사진이 다른 스토어에도"}
NAVER_STATUS = {"SALE": "판매 중", "OUTOFSTOCK": "품절", "SUSPENSION": "판매중지", "WAIT": "판매 대기", "CLOSE": "판매 종료",
                "PROHIBITION": "판매 금지", "UNADMISSION": "승인 대기", "REJECTION": "승인 거부"}


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def upload_dir():
    d = os.path.join(config.DATA_DIR, "adopt_files")
    os.makedirs(d, exist_ok=True)
    return d


# ───────────────────────── 스토어 상하단 찾기

_OPEN = re.compile(r"<div\b", re.I)
_CLOSE = re.compile(r"</div\s*>", re.I)


def _balanced(s):
    return len(_OPEN.findall(s)) == len(_CLOSE.findall(s))


def _common_prefix(strs):
    a, b = min(strs), max(strs)   # 정렬했을 때 양 끝의 공통 앞부분 = 전체의 공통 앞부분
    i = 0
    n = min(len(a), len(b))
    while i < n and a[i] == b[i]:
        i += 1
    return a[:i]


def detect_edges(details):
    """스토어가 모든 상품에 똑같이 넣은 상세 맨 앞(상단)·맨 뒤(하단) 덩어리를 찾는다 → (상단 HTML, 하단 HTML).
    맨 앞 300자(맨 뒤 300자)가 같은 상품이 30% 넘으면 그 상품들의 공통 부분을 <div> 짝이 맞는 곳까지 잘라 씀."""
    ds = [d.strip() for d in details if d and d.strip()]
    if len(ds) < 5:
        return "", ""
    top = bottom = ""
    head, n = Counter(d[:300] for d in ds).most_common(1)[0]
    if n >= len(ds) * 0.3 and len(head) >= 300:
        cp = _common_prefix([d for d in ds if d.startswith(head)])
        for m in reversed(list(_CLOSE.finditer(cp))):
            cand = cp[:m.end()]
            if _balanced(cand) and re.search(r"<img\b", cand, re.I):
                top = cand
                break
    tail, n = Counter(d[-300:] for d in ds).most_common(1)[0]
    if n >= len(ds) * 0.3 and len(tail) >= 300:
        cs = _common_prefix([d[::-1] for d in ds if d.endswith(tail)])[::-1]
        for m in _OPEN.finditer(cs):
            cand = cs[m.start():]
            if _balanced(cand) and re.search(r"<img\b", cand, re.I):
                bottom = cand
                break
    return top, bottom


def strip_edges(html, top, bottom):
    """상세에서 상단·하단 덩어리를 뺀다 → (새 상세, 상단 뺐나, 하단 뺐나)."""
    d = str(html or "").strip()
    t = b = False
    if top and d.startswith(top):
        d, t = d[len(top):].lstrip(), True
    if bottom and d.endswith(bottom):
        d, b = d[:-len(bottom)].rstrip(), True
    return d, t, b


# ───────────────────────── 1. 파일 미리 보기

def prepare(db, path, filename):
    """올린 파일을 읽어 미리 보기: 상품 수, 판매자코드, 스토어 짐작(브랜드·판매자코드 머리), 찾은 상단·하단."""
    rows = [r for r in excel.iter_rows(path, filename) if r.get("상품명")]
    codes = [str(r.get("판매자코드") or "").strip() for r in rows]
    top, bottom = detect_edges([r.get("상세설명") for r in rows])
    n_top = n_bot = 0
    for r in rows:
        _, t, b = strip_edges(r.get("상세설명"), top, bottom)
        n_top += t
        n_bot += b
    brand = Counter(str(r.get("브랜드") or "").strip() for r in rows).most_common(1)
    brand = brand[0][0] if brand else ""
    guess = None
    for s in db.stores():
        nm = str(s["name"] or "")
        if brand and (brand in nm or nm in brand or brand.lower() in nm.lower()):
            guess = s["id"]
            break
    prefix = Counter(re.sub(r"\d+$", "", c) for c in codes if c).most_common(1)
    return {"rows": len(rows), "no_code": codes.count(""), "dup_code": len(codes) - len(set(codes)),
            "code_prefix": prefix[0][0] if prefix else "", "code_example": next((c for c in codes if c), ""),
            "brand": brand, "guess_store": guess,
            "top": top, "bottom": bottom, "top_imgs": clean.img_srcs(top)[:6], "bottom_imgs": clean.img_srcs(bottom)[:8],
            "n_top": n_top, "n_bottom": n_bot}


# ───────────────────────── 2. 가져오기

def _product(it):
    """커머스API 상품 목록 한 개 → 필요한 값만."""
    chs = it.get("channelProducts") or [{}]
    ch = next((c for c in chs if c.get("channelServiceType") in (None, "STOREFARM")), chs[0])
    return {"origin_no": str(it.get("originProductNo") or ch.get("originProductNo") or ""),
            "channel_no": str(ch.get("channelProductNo") or ""),
            "code": str(ch.get("sellerManagementCode") or it.get("sellerManagementCode") or "").strip(),
            "name": str(ch.get("name") or ""),
            "status": str(ch.get("statusType") or (it.get("originProduct") or {}).get("statusType") or ""),
            "reg_at": naver.parse_time(ch.get("regDate")),
            "sale": int(ch.get("salePrice") or 0),
            "final": int(ch.get("discountedPrice") or ch.get("mobileDiscountedPrice") or ch.get("salePrice") or 0)}


def run(db, run_id, store_id, path, filename, opts, progress=None, should_stop=None):
    """가져오기 한 번. opts: strip_top, strip_bottom, mark_eye (기본 모두 켬)."""
    st = {"rows": 0, "linked": 0, "already": 0, "dropped": 0, "store_only": 0, "dup": 0, "dup_same": 0, "no_code": 0,
          "top_removed": 0, "bottom_removed": 0, "store_products": 0, "status": {}, "managed": 0}
    store = db.store(int(store_id), with_secret=True)
    if not store:
        raise ValueError("스토어를 찾지 못했습니다.")
    client = naver.make_client(store)
    items = []

    def add_item(kind, **kw):
        items.append((run_id, kind, kw.get("code", ""), kw.get("name", "")[:300], kw.get("channel_no", ""), kw.get("status", ""),
                      kw.get("reg_at"), kw.get("source_id"), kw.get("note", "")))

    # ① 스토어 상품 목록 (목록만 받아 빠름)
    if progress:
        progress(0, None, f"'{store['name']}' 네이버 상품 목록 받는 중…")
    products = []
    for it in client.iter_products(on_page=lambda n, total: progress and progress(n, total, f"'{store['name']}' 네이버 상품 목록 {n:,}/{total:,}")):
        p = _product(it)
        if p["status"] != "DELETE":
            products.append(p)
        if should_stop and should_stop():
            raise RuntimeError("중단했습니다.")
    st["store_products"] = len(products)
    by_code = {}
    for p in products:
        if p["code"] and p["code"] not in by_code:
            by_code[p["code"]] = p
    managed = {r["channel_no"] for r in db.q("SELECT channel_no FROM listings WHERE store_id=? AND channel_no!=''", (store["id"],))}

    # ② 파일 읽기 + 상하단 찾기
    if progress:
        progress(0, None, "파일 읽는 중…")
    rows = [r for r in excel.iter_rows(path, filename) if r.get("상품명")]
    st["rows"] = len(rows)
    top, bottom = detect_edges([r.get("상세설명") for r in rows]) if (opts.get("strip_top", True) or opts.get("strip_bottom", True)) else ("", "")
    if not opts.get("strip_top", True):
        top = ""
    if not opts.get("strip_bottom", True):
        bottom = ""

    # ③ 판매자코드로 맞추기: 스토어에 있는 것만 원본으로 (정리: 상하단 빼기, 브랜드·제조사·모델명·원산지 '상세페이지 참조')
    keep, matched, file_codes = [], {}, set()
    for i, r in enumerate(rows):
        code = str(r.get("판매자코드") or "").strip()
        if code:
            file_codes.add(code)
        p = by_code.get(code) if code else None
        if not p:
            st["no_code" if not code else "dropped"] += 1
            add_item("dropped", code=code, name=str(r.get("상품명") or ""), note="판매자코드 없음" if not code else "스토어에 없음")
            continue
        r = dict(r)
        d, t, b = strip_edges(r.get("상세설명"), top, bottom)
        r["상세설명"] = d
        st["top_removed"] += t
        st["bottom_removed"] += b
        r, _ = clean.auto_fix(r, {"price": True, "code": False, "info": True}, [])
        keep.append((i, r))
        matched[i] = p
    for p in products:   # 스토어에만 있는 것 (이 프로그램이 이미 관리하는 것은 빼고)
        if p["channel_no"] in managed:
            st["managed"] += 1
        elif not p["code"] or p["code"] not in file_codes:
            st["store_only"] += 1
            add_item("store_only", code=p["code"], name=p["name"], channel_no=p["channel_no"], status=p["status"], reg_at=p["reg_at"])

    # ④ 원본으로 넣기 (대표 사진이 같은 원본이 있으면 내용 갱신 — 엑셀 불러오기와 같음)
    if progress:
        progress(0, len(keep), f"원본으로 넣는 중 {len(keep):,}개")
    imp = inventory.import_rows(db, iter(keep), f"기존 상품 가져오기 · {store['name']} · {filename}", total_hint=len(keep),
                                progress=progress, should_stop=should_stop, src_tags=["가져옴", store["name"]], store_tag=False)
    refs = imp.get("refs") or {}

    # ⑤ 그 스토어의 판매 중 복사본으로 연결 (가격 고정, 이름 = 올라가 있는 이름)
    now = time.time()
    sids = set()
    with db.tx() as c:
        for i, sid in refs.items():
            p = matched[i]
            sids.add(sid)
            c.execute("UPDATE sources SET adopted=1" + (", eye_at=COALESCE(eye_at, ?)" if opts.get("mark_eye", True) else "") + " WHERE id=?",
                      ((now, sid) if opts.get("mark_eye", True) else (sid,)))
            if p["channel_no"] in managed:
                st["already"] += 1
                add_item("already", code=p["code"], name=p["name"], channel_no=p["channel_no"], status=p["status"], reg_at=p["reg_at"], source_id=sid)
                continue
            cur = c.execute("""SELECT id, name_id, origin_no, channel_no FROM listings WHERE source_id=? AND store_id=? AND status!='deleted'""",
                            (sid, store["id"])).fetchone()
            if cur and cur["origin_no"]:   # 대표 사진이 같은 상품이 이 스토어에 이미 연결됨 → 같은 상품을 두 번 올린 것 (먼저 것만 연결)
                st["dup_same"] += 1
                add_item("dup_same", code=p["code"], name=p["name"], channel_no=p["channel_no"], status=p["status"], reg_at=p["reg_at"],
                         source_id=sid, note=f"같은 원본으로 이미 연결된 상품번호 {cur['channel_no']}")
                continue
            vals = dict(name=p["name"], price=p["final"] or p["sale"], status="success", op="create", round=1, seller_code=p["code"],
                        origin_no=p["origin_no"], channel_no=p["channel_no"], registered_at=p["reg_at"] or now, sale_shown=p["sale"] or None,
                        price_fixed=1, message="", stage="", updated_at=now)
            if cur:   # 이 스토어에 아직 안 올린 복사본이 있었으면 그 줄을 올라가 있는 상품으로
                if cur["name_id"]:
                    c.execute("UPDATE names SET listing_id=NULL WHERE id=?", (cur["name_id"],))
                c.execute(f"UPDATE listings SET {', '.join(k + '=?' for k in vals)}, name_id=NULL WHERE id=?", (*vals.values(), cur["id"]))
                lid = cur["id"]
            else:
                cols = ["store_id", "source_id", *vals, "created_at"]
                lid = c.execute(f"INSERT INTO listings({', '.join(cols)}) VALUES({','.join('?' * len(cols))})",
                                (store["id"], sid, *vals.values(), now)).lastrowid
            # 올라가 있던 이름이 이 복사본의 정식 이름 (원본 이름과 같으면 그 이름 줄을 이 복사본 것으로 — 안 그러면 '상품명 변경 필요'로 잘못 보임)
            nm = namegen.clean(p["name"], 200)
            norm = namegen.normalize(nm)
            if norm:
                cur_n = c.execute("INSERT OR IGNORE INTO names(source_id, name, norm, origin, listing_id, created_at) VALUES(?,?,?,?,?,?)",
                                  (sid, nm, norm, "adopt", lid, now))
                name_id = cur_n.lastrowid if cur_n.rowcount else None
                if not name_id:
                    ex = c.execute("SELECT id, source_id, listing_id FROM names WHERE norm=?", (norm,)).fetchone()
                    if ex and ex["source_id"] == sid and ex["listing_id"] in (None, lid):
                        c.execute("UPDATE names SET listing_id=?, origin='adopt' WHERE id=?", (lid, ex["id"]))
                        name_id = ex["id"]
                    else:
                        st["name_taken"] = st.get("name_taken", 0) + 1   # 다른 원본이 같은 이름을 씀 → 최신화 때 새 이름 필요
                if name_id:
                    c.execute("UPDATE listings SET name_id=? WHERE id=?", (name_id, lid))
            managed.add(p["channel_no"])
            st["linked"] += 1
            st["status"][p["status"]] = st["status"].get(p["status"], 0) + 1
            add_item("linked", code=p["code"], name=p["name"], channel_no=p["channel_no"], status=p["status"], reg_at=p["reg_at"], source_id=sid)
    db.recount_sources(sorted(sids))

    # ⑥ 같은 대표 사진이 다른 스토어에도 올라가 있는 원본 (한 상품은 한 스토어에만 → 하나 지우세요)
    for i in range(0, len(sids), 900):
        ch = sorted(sids)[i:i + 900]
        for r in db.q(f"""SELECT s.id, s.name, GROUP_CONCAT(t.name, ', ') AS stores, COUNT(*) AS n FROM listings l JOIN sources s ON s.id=l.source_id
                JOIN stores t ON t.id=l.store_id WHERE l.source_id IN ({','.join('?' * len(ch))}) AND l.status!='deleted' AND l.origin_no!=''
                GROUP BY s.id HAVING n>1""", ch):
            st["dup"] += 1
            add_item("dup", name=r["name"], source_id=r["id"], note=r["stores"])
    with db.tx() as c:
        c.executemany("""INSERT INTO adopt_item(run_id, kind, code, name, channel_no, status, reg_at, source_id, note)
            VALUES(?,?,?,?,?,?,?,?,?)""", items)
    st["top"], st["bottom"] = clean.img_srcs(top)[:6], clean.img_srcs(bottom)[:8]
    return st


def start(db, tasks, token, store_id, opts):
    """미리 본 파일로 가져오기 작업을 시작 → 작업 번호."""
    meta = _token_meta(token)
    store = db.store(int(store_id or 0))
    if not store:
        raise ValueError("가져올 스토어를 골라 주세요.")
    rid = db.x("INSERT INTO adopt_run(created_at, store_id, store_name, file_name) VALUES(?,?,?,?)",
               (time.time(), store["id"], store["name"], meta["file"]))

    def job(progress=None, should_stop=None):
        try:
            out = run(db, rid, store["id"], meta["path"], meta["file"], opts, progress, should_stop)
            db.x("UPDATE adopt_run SET stats=?, status='done', finished_at=? WHERE id=?", (json.dumps(out, ensure_ascii=False), time.time(), rid))
            return {**out, "run_id": rid, "store": store["name"], "file": meta["file"]}
        except Exception as e:  # noqa: BLE001
            db.x("UPDATE adopt_run SET status='error', stats=?, finished_at=? WHERE id=?", (json.dumps({"error": str(e)}, ensure_ascii=False), time.time(), rid))
            raise
        finally:
            _drop_token(token)
    return tasks.start("adopt", f"기존 상품 가져오기 · {store['name']} · {meta['file']}", job)


def save_upload(fileobj, filename):
    token = uuid.uuid4().hex
    ext = os.path.splitext(filename or "")[1].lower() or ".xlsx"
    path = os.path.join(upload_dir(), token + ext)
    fileobj.save(path)
    with open(path + ".json", "w", encoding="utf-8") as f:
        json.dump({"file": filename, "path": path}, f, ensure_ascii=False)
    return token, path


def _token_meta(token):
    if not re.fullmatch(r"[0-9a-f]{32}", str(token or "")):
        raise ValueError("파일을 다시 올려 주세요.")
    p = os.path.join(upload_dir(), "")
    for fn in os.listdir(p):
        if fn.startswith(token) and fn.endswith(".json"):
            with open(os.path.join(p, fn), encoding="utf-8") as f:
                return json.load(f)
    raise ValueError("올린 파일이 없습니다. 파일을 다시 올려 주세요.")


def _drop_token(token):
    p = upload_dir()
    for fn in os.listdir(p):
        if fn.startswith(token):
            try:
                os.remove(os.path.join(p, fn))
            except OSError:
                pass


def runs(db, limit=30):
    out = []
    for r in db.q("SELECT * FROM adopt_run ORDER BY id DESC LIMIT ?", (limit,)):
        r["stats"] = json.loads(r["stats"] or "{}")
        out.append(r)
    return out


def items_csv(db, run_id, kind):
    r = db.one("SELECT * FROM adopt_run WHERE id=?", (run_id,))
    if not r:
        raise ValueError("가져오기 기록이 없습니다.")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["구분", "판매자코드", "상품명", "상품번호", "네이버 상태", "등록일", "원본 번호", "메모"])
    for it in db.q("SELECT * FROM adopt_item WHERE run_id=? AND kind=? ORDER BY id", (run_id, kind)):
        w.writerow([KIND_LABEL.get(it["kind"], it["kind"]), it["code"], it["name"], it["channel_no"],
                    NAVER_STATUS.get(it["status"], it["status"]),
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(it["reg_at"])) if it["reg_at"] else "", it["source_id"] or "", it["note"]])
    name = f"가져오기{run_id}_{r['store_name']}_{KIND_LABEL.get(kind, kind)}.csv"
    return ("﻿" + buf.getvalue()).encode("utf-8"), name
