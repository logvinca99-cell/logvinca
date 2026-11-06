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

from . import clean, config, convert, excel, inventory, namegen, naver, nvstate, orders, srctags
from .db import pack, unpack

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
              "dup_same": "같은 스토어에 같은 상품 두 번", "dup": "같은 대표 사진이 다른 스토어에도",
              "price_diff": "엑셀 판매가와 스토어 손님 가격이 다름 (스토어 손님 가격으로 넣음)",
              "mobile_disc": "모바일 할인이 따로 있음 (최신화하면 사라짐)"}
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

_product = nvstate.product   # 커머스API 상품 목록 한 개 → 필요한 값만 (판매·전시 상태, 손님 가격, 모바일 할인)


def run(db, run_id, store_id, path, filename, opts, progress=None, should_stop=None):
    """가져오기 한 번. opts: strip_top, strip_bottom, mark_eye (기본 모두 켬)."""
    st = {"rows": 0, "linked": 0, "already": 0, "dropped": 0, "store_only": 0, "dup": 0, "dup_same": 0, "no_code": 0,
          "top_removed": 0, "bottom_removed": 0, "store_products": 0, "status": {}, "managed": 0,
          "price_diff": 0, "mobile_disc": 0, "dropped_src": 0, "existing": 0, "code_changed": 0}
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
    #    원본가 = 그 스토어의 지금 손님 가격 (엑셀 판매가가 아님 — 셀업·판매자센터에서 따로 건 할인까지 반영된 값)
    keep, matched, file_codes, unmatched = [], {}, set(), []
    for i, r in enumerate(rows):
        code = str(r.get("판매자코드") or "").strip()
        if code:
            file_codes.add(code)
        p = by_code.get(code) if code else None
        if not p:
            if not code:
                st["no_code"] += 1
                add_item("dropped", code=code, name=str(r.get("상품명") or ""), note="판매자코드 없음")
            else:
                unmatched.append((code, str(r.get("상품명") or ""), inventory.source_key(r)))   # 아래 ⑦에서 판정
            continue
        r = dict(r)
        d, t, b = strip_edges(r.get("상세설명"), top, bottom)
        r["상세설명"] = d
        st["top_removed"] += t
        st["bottom_removed"] += b
        xl = convert.net_price(r)
        r, _ = clean.auto_fix(r, {"price": True, "code": False, "info": True}, [])
        final = p["final"] or p["sale"]
        if final > 0:
            if xl != final and p["channel_no"] not in managed:
                st["price_diff"] += 1
                add_item("price_diff", code=p["code"], name=p["name"], channel_no=p["channel_no"], status=p["status"], reg_at=p["reg_at"],
                         note=f"엑셀 {xl:,}원 → 스토어 손님 가격 {final:,}원")
            r["판매가"], r["할인가"] = final, None
        if p.get("mobile") and p["channel_no"] not in managed:
            st["mobile_disc"] += 1
            add_item("mobile_disc", code=p["code"], name=p["name"], channel_no=p["channel_no"], status=p["status"], reg_at=p["reg_at"],
                     note=f"PC {final:,}원 / 모바일 {p['mobile']:,}원")
        keep.append((i, r))
        matched[i] = p
    for p in products:   # 스토어에만 있는 것 (이 프로그램이 이미 관리하는 것은 빼고)
        if p["channel_no"] in managed:
            st["managed"] += 1
        elif not p["code"] or p["code"] not in file_codes:
            st["store_only"] += 1
            add_item("store_only", code=p["code"], name=p["name"], channel_no=p["channel_no"], status=p["status"], reg_at=p["reg_at"])

    # ④ 원본으로 넣기. 대표 사진이 같은 원본이 이미 있으면 덮어쓰지 않는다 (원래 원본 이름·AI 키워드·상세를 지킴):
    #    예전에 불러온 원본이면 원본가만 이 스토어 손님 가격으로 바꾸고 '가져옴 · 원본 이름 있음'(2), 이미 가져온 원본이면 그대로.
    #    파일 안에서 대표 사진이 같은 줄은 첫 줄만 원본으로 (나머지는 같은 원본 — 아래에서 '같은 스토어 중복')
    if progress:
        progress(0, len(keep), f"원본으로 넣는 중 {len(keep):,}개")
    tags = ["가져옴", store["name"]]
    keys = {i: inventory.source_key(r) for i, r in keep}
    first, refs = {}, {}
    for i, r in keep:
        k = keys[i]
        if k in first:
            continue
        first[k] = i
    exist = {}
    ks = list(first)
    for j in range(0, len(ks), 900):
        ch = ks[j:j + 900]
        for x in db.q(f"SELECT id, source_key, adopted, data, src_tags FROM sources WHERE source_key IN ({','.join('?' * len(ch))})", ch):
            exist[x["source_key"]] = x
    now = time.time()
    with db.tx() as c:
        for k, i in first.items():
            x = exist.get(k)
            if not x:
                continue
            st["existing"] += 1
            refs[i] = x["id"]
            new_tags = srctags.merge(x["src_tags"], tags)
            if not x["adopted"]:   # 예전에 불러온 원본 → 원본가만 이 스토어 손님 가격으로
                final = matched[i]["final"] or matched[i]["sale"]
                d = unpack(x["data"])
                if final > 0:
                    d["판매가"], d["할인가"] = final, None
                c.execute("UPDATE sources SET adopted=2, price=?, data=?, src_tags=?, updated_at=? WHERE id=?",
                          (convert.net_price(d), pack(d), new_tags, now, x["id"]))
            elif new_tags != x["src_tags"]:
                c.execute("UPDATE sources SET src_tags=? WHERE id=?", (new_tags, x["id"]))
    rows_by_i = dict(keep)
    new_rows = [(i, rows_by_i[i]) for k, i in first.items() if k not in exist]
    if new_rows:
        imp = inventory.import_rows(db, iter(new_rows), f"기존 상품 가져오기 · {store['name']} · {filename}", total_hint=len(new_rows),
                                    progress=progress, should_stop=should_stop, src_tags=tags, store_tag=False)
        refs.update(imp.get("refs") or {})
    if exist:
        inventory.reprice_pending(db)   # 원본가가 바뀐 예전 원본의 아직 안 올린 복사본 가격도 다시
    for i, r in keep:   # 파일 안에서 대표 사진이 같은 뒷줄 → 첫 줄의 원본
        if i not in refs and first.get(keys[i]) in refs:
            refs[i] = refs[first[keys[i]]]

    # ⑤ 그 스토어의 판매 중 복사본으로 연결 (가격 고정, 이름 = 올라가 있는 이름)
    now = time.time()
    sids = set()
    with db.tx() as c:
        for i, sid in refs.items():
            p = matched[i]
            sids.add(sid)
            c.execute("UPDATE sources SET adopted=CASE WHEN adopted=0 THEN 1 ELSE adopted END"
                      + (", eye_at=COALESCE(eye_at, ?)" if opts.get("mark_eye", True) else "") + " WHERE id=?",
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
                        price_fixed=1, message="", stage="", updated_at=now, nv_status=p["status"], nv_disp=p["disp"], nv_at=now)
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

    # ⑦ 엑셀에는 있는데 스토어에 없는 상품. 대표 사진이 같은 상품이 이 스토어에 판매 중이면(최신화로 판매자코드가 바뀐 것 등) '이미 연결',
    #    아니면 스토어에서 지운 상품 → 버림. 그 원본이 다른 경로로 이미 들어와 있으면 '원본까지 삭제' 대상으로 표시
    ukeys = sorted({k for _, _, k in unmatched if k})
    src_by_key, live_here = {}, set()
    for j in range(0, len(ukeys), 900):
        ch = ukeys[j:j + 900]
        for x in db.q(f"SELECT id, source_key FROM sources WHERE source_key IN ({','.join('?' * len(ch))})", ch):
            src_by_key[x["source_key"]] = x["id"]
    ids = sorted(set(src_by_key.values()))
    for j in range(0, len(ids), 900):
        ch = ids[j:j + 900]
        live_here |= {x["source_id"] for x in db.q(f"""SELECT source_id FROM listings WHERE store_id=? AND origin_no!='' AND status!='deleted'
            AND source_id IN ({','.join('?' * len(ch))})""", (store["id"], *ch))}
    drop_src = set()
    for code, name, k in unmatched:
        sid = src_by_key.get(k)
        if sid and sid in live_here:
            st["already"] += 1
            st["code_changed"] += 1
            add_item("already", code=code, name=name, source_id=sid, note="같은 상품이 이 스토어에 판매 중 (판매자코드가 바뀜 — 최신화 등)")
            continue
        st["dropped"] += 1
        if sid:
            drop_src.add(sid)
        add_item("dropped", code=code, name=name, source_id=sid,
                 note="스토어에 없음 · 원본에 있음 → 원본까지 삭제 대상" if sid else "스토어에 없음")
    st["dropped_src"] = len(drop_src)

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
    # 판매 이력: 받아 둔 주문을 가져온 복사본과 다시 맞추고, 가져온 상품이 올라간 날부터 주문을 알고 있는지
    st["orders_matched"] = orders.rematch(db)
    reg = [x[6] for x in items if x[1] == "linked" and x[6]]
    st["reg_min"] = min(reg) if reg else None
    st["orders_from"] = orders.known_from(db.store(store["id"]) or {})
    st["need_orders"] = bool(st["reg_min"] and (not st["orders_from"] or st["orders_from"] > st["reg_min"] + 3600))
    return st


def drop_source_ids(db, run_id):
    """'스토어에 없어서 뺌' 중 원본에 있는 것 → 원본까지 삭제할 원본 번호들 (지금 그 스토어에 판매 중인 것은 뺌)."""
    run = db.one("SELECT store_id FROM adopt_run WHERE id=?", (int(run_id),))
    if not run:
        return []
    ids = [r["source_id"] for r in db.q("""SELECT DISTINCT i.source_id FROM adopt_item i JOIN sources s ON s.id=i.source_id
        WHERE i.run_id=? AND i.kind='dropped' AND i.source_id IS NOT NULL""", (int(run_id),))]
    if not ids:
        return []
    live = set()
    for j in range(0, len(ids), 900):
        ch = ids[j:j + 900]
        live |= {x["source_id"] for x in db.q(f"""SELECT source_id FROM listings WHERE store_id=? AND origin_no!='' AND status!='deleted'
            AND source_id IN ({','.join('?' * len(ch))})""", (run["store_id"], *ch))}
    return [i for i in ids if i not in live]


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
    out, sales = [], {}
    for r in db.q("SELECT * FROM adopt_run ORDER BY id DESC LIMIT ?", (limit,)):
        r["stats"] = json.loads(r["stats"] or "{}")
        if r["store_id"] not in sales:
            try:
                sales[r["store_id"]] = orders.sales_status(db, r["store_id"])
            except ValueError:
                sales[r["store_id"]] = None
        r["sales"] = sales[r["store_id"]]   # 지금 판매 이력 상태 (확인 전 남은 가져온 상품 수 등)
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
