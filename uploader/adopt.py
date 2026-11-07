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
              "dup_same": "연결 못 함", "dup": "같은 대표 사진이 다른 스토어에도 (예전 기록)",
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


# ───────────────────────── 공통 이미지 (스토어 상단·하단·안내 배너)
# 상세 정리 '② 공통 이미지'와 같은 방식: 이미지마다 몇 개 상품 상세에 들어 있는지 세서 많은 순으로 모두 보여 주고, 고른 것을 뺀다.
# (맨 앞·맨 뒤 덩어리가 글자까지 똑같아야 빼던 예전 방식은 상단이 조금 다른 상품 수백 개를 놓쳤음)

COMMON_MIN = 10        # 이 수 이상 상품에 들어 있는 이미지만 보여 줌
PRESELECT_RATIO = 0.05  # 상품 5% 넘게 들어 있으면 미리 골라 둠 (스토어 상단·하단은 거의 모든 상품에 있음)


def common_images(rows, rule_srcs=(), min_count=COMMON_MIN, limit=300):
    """엑셀 줄들 → {total 상세 있는 상품 수, images [{src, count, pos 상단·하단·가운데, pick 미리 고름, remembered}], more}."""
    counts, pos_sum = Counter(), {}
    total = 0
    for r in rows:
        srcs = clean.img_srcs(r.get("상세설명"))
        if not srcs:
            continue
        total += 1
        last = max(1, len(srcs) - 1)
        for j, src in enumerate(srcs):
            if src in pos_sum and counts[src] and pos_sum[src][1] == total:
                continue   # 한 상품 안에서 같은 이미지는 한 번만
            counts[src] += 1
            ps = pos_sum.get(src, (0.0, 0))
            pos_sum[src] = (ps[0] + (j / last if len(srcs) > 1 else 0.0), total)
    known = set(rule_srcs or ())
    out = []
    for src, n in counts.most_common():
        if n < max(2, int(min_count or 2)) and src not in known:
            break
        avg = pos_sum[src][0] / n
        out.append({"src": src, "count": n, "pos": "상단" if avg < 0.3 else "하단" if avg > 0.7 else "가운데",
                    "pick": n >= total * PRESELECT_RATIO or src in known, "remembered": src in known})
    return {"total": total, "images": out[:limit], "more": max(0, len(out) - limit)}


_PAD = r"(?:\s|<br\s*/?>|&nbsp;)*"
_EMPTY = re.compile(rf"<(div|p|center|span|a)\b[^>]*>{_PAD}</\1>", re.I)


def image_remover(srcs):
    """고른 이미지 주소들 → 상세에서 한 번에 빼는 함수 (html → (새 html, 뺀 수)). 이미지만 감싸던 칸, 비게 된 칸도 같이 뺀다."""
    srcs = [x for x in dict.fromkeys(str(v).strip() for v in (srcs or [])) if x]
    if not srcs:
        return lambda html: (str(html or ""), 0)
    alt = "|".join(re.escape(x) for x in sorted(srcs, key=len, reverse=True))
    img = rf"""<img\b[^>]*\bsrc\s*=\s*["'](?:{alt})["'][^>]*>"""
    wrap = re.compile(rf"<(div|p|a|span|center)\b[^>]*>{_PAD}{img}{_PAD}</\1>", re.I)
    one = re.compile(img, re.I)

    def fn(html):
        html = str(html or "")
        html, k1 = wrap.subn("", html)
        html, k2 = one.subn("", html)
        if k1 or k2:
            for _ in range(3):   # 이미지를 빼서 비게 된 칸 (여러 장을 감싸던 상단·하단 칸)
                html, k = _EMPTY.subn("", html)
                if not k:
                    break
        return html.strip(), k1 + k2
    return fn


# ───────────────────────── 1. 파일 미리 보기

def prepare(db, path, filename):
    """올린 파일을 읽어 미리 보기: 상품 수, 판매자코드, 스토어 짐작(브랜드), 공통 이미지(상단·하단 배너 등) 전부."""
    rows = [r for r in excel.iter_rows(path, filename) if r.get("상품명")]
    codes = [str(r.get("판매자코드") or "").strip() for r in rows]
    rule_srcs = [r["value"] for r in clean.rules(db) if r["kind"] == "image"]
    brand = Counter(str(r.get("브랜드") or "").strip() for r in rows).most_common(1)
    brand = brand[0][0] if brand else ""
    guess = None
    for st in db.stores():
        nm = str(st["name"] or "")
        if brand and (brand in nm or nm in brand or brand.lower() in nm.lower()):
            guess = st["id"]
            break
    prefix = Counter(re.sub(r"\d+$", "", c) for c in codes if c).most_common(1)
    return {"rows": len(rows), "no_code": codes.count(""), "dup_code": len(codes) - len(set(codes)),
            "code_prefix": prefix[0][0] if prefix else "", "code_example": next((c for c in codes if c), ""),
            "brand": brand, "guess_store": guess, "common": common_images(rows, rule_srcs)}


# ───────────────────────── 2. 가져오기

_product = nvstate.product   # 커머스API 상품 목록 한 개 → 필요한 값만 (판매·전시 상태, 손님 가격, 모바일 할인)


def fetch_products(db, store_id, progress=None, should_stop=None):
    """그 스토어 네이버 상품 목록 (지운 것 빼고, 필요한 값만)."""
    store = db.store(int(store_id), with_secret=True)
    if not store:
        raise ValueError("스토어를 찾지 못했습니다.")
    client = naver.make_client(store)
    if progress:
        progress(0, None, f"'{store['name']}' 네이버 상품 목록 받는 중…")
    out = []
    for it in client.iter_products(on_page=lambda n, total: progress and progress(n, total, f"'{store['name']}' 네이버 상품 목록 {n:,}/{total:,}")):
        p = _product(it)
        if p["status"] != "DELETE":
            out.append(p)
        if should_stop and should_stop():
            raise RuntimeError("중단했습니다.")
    return out


def run(db, run_id, store_id, path, filename, opts, progress=None, should_stop=None, dry=False, products=None):
    """가져오기 한 번. opts: remove_imgs(뺄 공통 이미지 주소들), mark_eye(기본 켬).
    dry=True면 맞춰 보기만 (아무것도 바꾸지 않고 결과·예시만). products: 맞춰 볼 때 받은 스토어 상품 목록 (다시 받지 않게)."""
    st = {"rows": 0, "linked": 0, "already": 0, "dropped": 0, "store_only": 0, "dup": 0, "dup_same": 0, "no_code": 0,
          "img_items": 0, "img_removed": 0, "img_kinds": len(opts.get("remove_imgs") or []), "store_products": 0, "status": {}, "managed": 0,
          "price_diff": 0, "mobile_disc": 0, "dropped_src": 0, "existing": 0, "code_changed": 0}
    samples = {"linked": [], "dropped": [], "store_only": [], "price_diff": []}

    def sample(kind, **kw):
        if dry and len(samples[kind]) < 8:
            samples[kind].append(kw)
    store = db.store(int(store_id), with_secret=True)
    if not store:
        raise ValueError("스토어를 찾지 못했습니다.")
    items = []

    def add_item(kind, **kw):
        items.append((run_id, kind, kw.get("code", ""), kw.get("name", "")[:300], kw.get("channel_no", ""), kw.get("status", ""),
                      kw.get("reg_at"), kw.get("source_id"), kw.get("note", "")))

    # ① 스토어 상품 목록 (목록만 받아 빠름 — 맞춰 볼 때 받은 것이 있으면 그대로)
    if products is None:
        products = fetch_products(db, store["id"], progress, should_stop)
    st["store_products"] = len(products)
    by_code = {}
    for p in products:
        if p["code"] and p["code"] not in by_code:
            by_code[p["code"]] = p
    managed = {r["channel_no"] for r in db.q("SELECT channel_no FROM listings WHERE store_id=? AND channel_no!=''", (store["id"],))}

    # ② 파일 읽기
    if progress:
        progress(0, None, "파일 읽는 중…")
    rows = [r for r in excel.iter_rows(path, filename) if r.get("상품명")]
    st["rows"] = len(rows)
    strip = image_remover(opts.get("remove_imgs"))

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
        d, k = strip(r.get("상세설명"))
        r["상세설명"] = d
        st["img_items"] += bool(k)
        st["img_removed"] += k
        xl = convert.net_price(r)
        r, _ = clean.auto_fix(r, {"price": True, "code": False, "info": True}, [])
        final = p["final"] or p["sale"]
        if final > 0:
            if xl != final and p["channel_no"] not in managed:
                st["price_diff"] += 1
                add_item("price_diff", code=p["code"], name=p["name"], channel_no=p["channel_no"], status=p["status"], reg_at=p["reg_at"],
                         note=f"엑셀 {xl:,}원 → 스토어 손님 가격 {final:,}원")
                sample("price_diff", code=p["code"], name=p["name"], xl=xl, final=final)
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
            sample("store_only", code=p["code"], name=p["name"], status=p["status"], final=p["final"])
    if dry:
        return _dry_rest(db, store, st, samples, rows, keep, matched, managed, unmatched)

    # ④ 원본으로 넣기. 대표 사진이 같은 원본이 이미 있으면 덮어쓰지 않는다 (원래 원본 이름·AI 키워드·상세를 지킴):
    #    예전에 불러온 원본이면 원본가만 이 스토어 손님 가격으로 바꾸고 '가져옴 · 원본 이름 있음'(2), 이미 가져온 원본이면 그대로.
    #    파일 안에서 대표 사진이 같은 줄은 첫 줄만 원본으로 (나머지는 같은 원본 — 아래에서 '같은 스토어 중복')
    if progress:
        progress(0, len(keep), f"원본으로 넣는 중 {len(keep):,}개")
    tags = ["가져옴", store["name"]]
    keys = _assign_keys(db, store["id"], keep, matched)   # 1대1: 대표 사진이 같아도 스토어 상품마다 원본 하나
    for i, r in keep:
        if keys[i] != inventory.source_key(r):
            r["_source_key"] = keys[i]
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
            d = unpack(x["data"])
            html, k = strip(d.get("상세설명"))   # 고른 공통 이미지(스토어 배너)는 이미 있던 원본 상세에서도 뺀다 (나머지 내용은 그대로)
            if k:
                d["상세설명"] = html
            if not x["adopted"]:   # 예전에 불러온 원본 → 원본가만 이 스토어 손님 가격으로
                final = matched[i]["final"] or matched[i]["sale"]
                if final > 0:
                    d["판매가"], d["할인가"] = final, None
                c.execute("UPDATE sources SET adopted=2, price=?, data=?, src_tags=?, updated_at=? WHERE id=?",
                          (convert.net_price(d), pack(d), new_tags, now, x["id"]))
            elif k or new_tags != x["src_tags"]:
                c.execute("UPDATE sources SET data=?, src_tags=?, updated_at=? WHERE id=?", (pack(d), new_tags, now, x["id"]))
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
            if cur and cur["origin_no"]:   # (생기면 안 됨 — 1대1 열쇠라서) 이 원본이 이미 다른 상품번호로 연결돼 있음 → 건드리지 않고 알림
                st["dup_same"] += 1
                add_item("dup_same", code=p["code"], name=p["name"], channel_no=p["channel_no"], status=p["status"], reg_at=p["reg_at"],
                         source_id=sid, note=f"연결 못 함: 이 원본은 상품번호 {cur['channel_no']}와 연결돼 있음")
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
    hist = _history_codes(db, store["id"])
    drop_src = set()
    for code, name, k in unmatched:
        if code in hist:   # 최신화 등으로 판매자코드만 바뀐 같은 상품 (예전 코드로 1대1)
            st["already"] += 1
            st["code_changed"] += 1
            add_item("already", code=code, name=name, source_id=hist[code], note="이 스토어에 판매 중 (최신화로 판매자코드가 바뀜)")
            continue
        sid = _unmatched_source(db, k, code)
        st["dropped"] += 1
        if sid:
            drop_src.add(sid)
        add_item("dropped", code=code, name=name, source_id=sid,
                 note="스토어에 없음 · 원본에 있음 → 원본까지 삭제 대상" if sid else "스토어에 없음")
    st["dropped_src"] = len(drop_src)

    with db.tx() as c:
        c.executemany("""INSERT INTO adopt_item(run_id, kind, code, name, channel_no, status, reg_at, source_id, note)
            VALUES(?,?,?,?,?,?,?,?,?)""", items)
    # 판매 이력: 받아 둔 주문을 가져온 복사본과 다시 맞추고, 가져온 상품이 올라간 날부터 주문을 알고 있는지
    st["orders_matched"] = orders.rematch(db)
    reg = [x[6] for x in items if x[1] == "linked" and x[6]]
    st["reg_min"] = min(reg) if reg else None
    st["orders_from"] = orders.known_from(db.store(store["id"]) or {})
    st["need_orders"] = bool(st["reg_min"] and (not st["orders_from"] or st["orders_from"] > st["reg_min"] + 3600))
    return st


def _assign_keys(db, store_id, keep, matched):
    """스토어 상품 하나 = 원본 하나 (1대1). 대표 사진이 같은 상품이 여럿이어도 다른 상품으로 본다:
    사진이 같은 원본이 없거나 그 원본이 바로 이 스토어 상품이면 사진 열쇠, 아니면 '사진#판매자코드' 열쇠로 따로 원본을 만든다
    (다시 가져와도 같은 열쇠 → 같은 원본)."""
    base = {i: inventory.source_key(r) for i, r in keep}
    bks = sorted(set(base.values()))
    sid_of, live = {}, {}
    for j in range(0, len(bks), 900):
        ch = bks[j:j + 900]
        for x in db.q(f"SELECT id, source_key FROM sources WHERE source_key IN ({','.join('?' * len(ch))})", ch):
            sid_of[x["source_key"]] = x["id"]
    sids = sorted(sid_of.values())
    for j in range(0, len(sids), 900):
        ch = sids[j:j + 900]
        for x in db.q(f"""SELECT source_id, channel_no FROM listings WHERE store_id=? AND origin_no!='' AND status!='deleted'
                AND source_id IN ({','.join('?' * len(ch))})""", (int(store_id), *ch)):
            live.setdefault(x["source_id"], set()).add(x["channel_no"])
    # 사진 열쇠를 이미 가진 스토어 상품을 먼저 (파일 순서와 상관없이 그 상품이 사진 열쇠를 지킴)
    order = sorted((i for i, _ in keep), key=lambda i: 0 if matched[i]["channel_no"] in live.get(sid_of.get(base[i]), ()) else 1)
    used, out = set(), {}
    for i in order:
        k, p = base[i], matched[i]
        sid = sid_of.get(k)
        taken = k in used or bool(sid and live.get(sid) and p["channel_no"] not in live[sid])
        key = f"{k}#{p['code']}" if taken and p["code"] else k
        used.add(key)
        out[i] = key
    return out


def _history_codes(db, store_id):
    """이 스토어에서 최신화 등으로 판매자코드가 바뀐 판매 중 상품의 예전 판매자코드 → 원본 번호 (1대1로 '이미 연결' 판정)."""
    out = {}
    for x in db.q("""SELECT h.seller_code, l.source_id FROM listing_history h JOIN listings l ON l.id=h.listing_id
            WHERE l.store_id=? AND l.origin_no!='' AND l.status!='deleted' AND h.seller_code!=''""", (int(store_id),)):
        out[x["seller_code"]] = x["source_id"]
    return out


def _unmatched_source(db, k, code):
    """스토어에 없는 줄의 원본: 이 가져오기가 만든 '사진#판매자코드' 원본이 있으면 그것, 없으면 사진이 같은 원본."""
    for key in ((f"{k}#{code}" if k and code else None), k):
        if key:
            r = db.one("SELECT id FROM sources WHERE source_key=?", (key,))
            if r:
                return r["id"]
    return None


def _dry_rest(db, store, st, samples, rows, keep, matched, managed, unmatched):
    """맞춰 보기: 원본·복사본을 만들지 않고 연결될 수·버릴 수·예시만 센다 (가져오기와 같은 판정)."""
    keys = _assign_keys(db, store["id"], keep, matched)
    ks = sorted(set(keys.values()))
    exist = {}
    for j in range(0, len(ks), 900):
        ch = ks[j:j + 900]
        for x in db.q(f"SELECT id, source_key, adopted FROM sources WHERE source_key IN ({','.join('?' * len(ch))})", ch):
            exist[x["source_key"]] = x
    sids = sorted({x["id"] for x in exist.values()})
    live_here = set()
    for j in range(0, len(sids), 900):
        ch = sids[j:j + 900]
        live_here |= {x["source_id"] for x in db.q(f"""SELECT source_id FROM listings WHERE store_id=? AND origin_no!='' AND status!='deleted'
            AND source_id IN ({','.join('?' * len(ch))})""", (store["id"], *ch))}
    seen = set()
    rows_by_i = dict(keep)
    for i, r in keep:
        p, k = matched[i], keys[i]
        x = exist.get(k)
        if k not in seen and x:
            st["existing"] += 1
        if p["channel_no"] in managed or k in seen:
            st["already"] += 1
        else:
            st["linked"] += 1
            st["status"][p["status"]] = st["status"].get(p["status"], 0) + 1
            if len(samples["linked"]) < 8:
                samples["linked"].append({"code": p["code"], "xl_name": str(rows_by_i[i].get("상품명") or "")[:80], "name": p["name"][:80],
                                          "final": p["final"] or p["sale"], "status": p["status"]})
        seen.add(k)
    hist = _history_codes(db, store["id"])
    drop_src = set()
    for code, name, k in unmatched:
        if code in hist:
            st["already"] += 1
            st["code_changed"] += 1
            continue
        sid = _unmatched_source(db, k, code)
        st["dropped"] += 1
        if sid:
            drop_src.add(sid)
        if len(samples["dropped"]) < 8:
            samples["dropped"].append({"code": code, "name": name[:80], "src": bool(sid)})
    st["dropped_src"] = len(drop_src)
    with_code = st["rows"] - st["no_code"]
    st["match_rate"] = round(len(keep) / with_code, 4) if with_code else 0
    st["samples"] = samples
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


CHECK_VALID_SEC = 3 * 3600    # 맞춰 본 결과로 가져올 수 있는 시간
SNAPSHOT_REUSE_SEC = 1800     # 맞춰 볼 때 받은 스토어 상품 목록을 다시 쓰는 시간 (넘으면 다시 받음)


def _opts_of(o):
    return {"remove_imgs": [str(x) for x in (o.get("remove_imgs") or []) if str(x).strip()][:500],
            "mark_eye": bool(o.get("mark_eye", True))}


def check(db, tasks, token, store_id, opts):
    """가져오기 전에 맞춰 보기 (아무것도 바꾸지 않음) → 작업 번호. 결과는 작업 결과와 파일 기록에 남는다."""
    meta = _token_meta(token)
    store = db.store(int(store_id or 0))
    if not store:
        raise ValueError("이 파일을 올렸던 스토어를 골라 주세요.")
    opts = _opts_of(opts)

    def job(progress=None, should_stop=None):
        products = fetch_products(db, store["id"], progress, should_stop)
        out = run(db, None, store["id"], meta["path"], meta["file"], opts, progress, should_stop, dry=True, products=products)
        now = time.time()
        with open(_snap_path(token), "w", encoding="utf-8") as f:
            json.dump({"store_id": store["id"], "at": now, "products": products}, f, ensure_ascii=False)
        _save_meta(token, {**_token_meta(token), "checked": {"store_id": store["id"], "at": now, "result": out}})
        return {**out, "store": store["name"], "store_id": store["id"], "file": meta["file"], "token": token}
    return tasks.start("adopt_check", f"가져오기 맞춰 보기 · {store['name']} · {meta['file']}", job)


def start(db, tasks, token, store_id, opts):
    """맞춰 본 파일로 가져오기 작업을 시작 → 작업 번호. 맞춰 보기를 안 했거나 다른 스토어로 맞춰 봤으면 시작하지 않는다."""
    meta = _token_meta(token)
    store = db.store(int(store_id or 0))
    if not store:
        raise ValueError("가져올 스토어를 골라 주세요.")
    ck = meta.get("checked") or {}
    if ck.get("store_id") != store["id"] or time.time() - float(ck.get("at") or 0) > CHECK_VALID_SEC:
        raise ValueError("먼저 [맞춰 보기]로 이 스토어와 맞춰 본 결과를 확인하세요.")
    opts = _opts_of(opts)
    rid = db.x("INSERT INTO adopt_run(created_at, store_id, store_name, file_name) VALUES(?,?,?,?)",
               (time.time(), store["id"], store["name"], meta["file"]))

    def job(progress=None, should_stop=None):
        try:
            products = None
            try:
                snap = json.load(open(_snap_path(token), encoding="utf-8"))
                if snap.get("store_id") == store["id"] and time.time() - float(snap.get("at") or 0) < SNAPSHOT_REUSE_SEC:
                    products = snap["products"]
            except (OSError, ValueError):
                pass
            out = run(db, rid, store["id"], meta["path"], meta["file"], opts, progress, should_stop, products=products)
            db.x("UPDATE adopt_run SET stats=?, status='done', finished_at=? WHERE id=?", (json.dumps(out, ensure_ascii=False), time.time(), rid))
            return {**out, "run_id": rid, "store": store["name"], "file": meta["file"]}
        except Exception as e:  # noqa: BLE001
            db.x("UPDATE adopt_run SET status='error', stats=?, finished_at=? WHERE id=?", (json.dumps({"error": str(e)}, ensure_ascii=False), time.time(), rid))
            raise
        finally:
            _drop_token(token)
    return tasks.start("adopt", f"기존 상품 가져오기 · {store['name']} · {meta['file']}", job)


def _snap_path(token):
    return os.path.join(upload_dir(), token + ".products.json")


def _save_meta(token, meta):
    p = os.path.join(upload_dir(), "")
    for fn in os.listdir(p):
        if fn.startswith(token) and fn.endswith(".json") and not fn.endswith(".products.json"):
            with open(os.path.join(p, fn), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
            return


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
        if fn.startswith(token) and fn.endswith(".json") and not fn.endswith(".products.json"):
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


def undo_preview(db, run_id):
    """이 가져오기로 연결한 복사본·새로 생긴 원본 수 (되돌리기 확인용)."""
    run = db.one("SELECT * FROM adopt_run WHERE id=?", (int(run_id),))
    if not run:
        raise ValueError("가져온 기록을 찾지 못했습니다.")
    lids, new_src, kept = _undo_targets(db, run)
    return {"run_id": run["id"], "store": run["store_name"], "listings": len(lids), "sources": len(new_src), "kept_sources": len(kept),
            "status": run["status"]}


def _undo_targets(db, run):
    sids = [r["source_id"] for r in db.q("SELECT DISTINCT source_id FROM adopt_item WHERE run_id=? AND kind='linked' AND source_id IS NOT NULL",
                                         (run["id"],))]
    lids, new_src, kept = [], [], []
    for j in range(0, len(sids), 900):
        ch = sids[j:j + 900]
        m = ",".join("?" * len(ch))
        lids += [r["id"] for r in db.q(f"""SELECT id FROM listings WHERE store_id=? AND price_fixed=1 AND source_id IN ({m})""",
                                       (run["store_id"], *ch))]
        for r in db.q(f"""SELECT s.id, s.adopted, (SELECT COUNT(*) FROM listings l WHERE l.source_id=s.id
                AND NOT (l.store_id=? AND l.price_fixed=1)) AS others FROM sources s WHERE s.id IN ({m})""", (run["store_id"], *ch)):
            (new_src if r["adopted"] == 1 and not r["others"] else kept).append(r["id"])
    return lids, new_src, kept


def undo_run(db, run_id):
    """가져오기 되돌리기: 이 가져오기로 연결한 복사본과, 이 가져오기로 새로 생긴 원본(다른 복사본이 없는 것)을 휴지통으로.
    네이버 상품은 그대로 둔다 (내리지 않음). 예전부터 있던 원본은 남기고 '가져옴' 표시만 지운다."""
    from . import trash
    run = db.one("SELECT * FROM adopt_run WHERE id=?", (int(run_id),))
    if not run:
        raise ValueError("가져온 기록을 찾지 못했습니다.")
    if run["status"] == "running":
        raise ValueError("가져오는 중입니다. 끝난 뒤에 되돌리세요.")
    lids, new_src, kept = _undo_targets(db, run)
    a = trash.trash_listings(db, lids, keep_naver=True)
    b = trash.trash_sources(db, new_src, keep_naver=True)
    for j in range(0, len(kept), 900):
        ch = kept[j:j + 900]
        db.x(f"UPDATE sources SET adopted=0 WHERE adopted>0 AND id IN ({','.join('?' * len(ch))}) AND id NOT IN (SELECT source_id FROM listings WHERE price_fixed=1)", ch)
    stats = json.loads(run["stats"] or "{}")
    stats["undone_at"] = time.time()
    stats["undone"] = {"listings": a["moved"], "sources": b["moved"], "kept_sources": len(kept)}
    db.x("UPDATE adopt_run SET status='undone', stats=? WHERE id=?", (json.dumps(stats, ensure_ascii=False), run["id"]))
    return {"listings": a["moved"], "sources": b["moved"], "kept_sources": len(kept), "skipped": a["skipped_live"] + b["skipped_live"]}


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
