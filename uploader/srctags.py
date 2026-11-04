"""출처 태그: 원본을 어디서·언제 가져왔는지 (셀업으로 여러 루트에서 모으므로).

원본(sources.src_tags)에 '|태그1|태그2|' 모양으로 저장한다. 엑셀의 '상품태그'(네이버 검색 태그)와는 다른 것.
- 불러올 때(원본 엑셀 불러오기·상세 정리 → 원본으로 넣기) 적은 태그를 그 파일의 모든 원본에 붙인다.
- '수집 스토어 태그'를 켜면 엑셀 '수집URL'의 스토어 주소 이름(smartstore.naver.com/<이것>)도 붙인다.
- 같은 원본을 다른 루트로 또 불러오면 태그가 더해진다(지우지 않음).
"""

import re
import time
from collections import Counter
from urllib.parse import urlparse

from .db import unpack

MAX_LEN = 40
_BAD = re.compile(r"[|,\n\r\t]+")
_STORE = re.compile(r"^https?://(?:m\.)?(?:smartstore|brand)\.naver\.com/(?:main/)?([^/?#]+)", re.I)
_SKIP_SLUG = {"products", "category", "search", "profile", "main"}


def clean(t):
    t = _BAD.sub(" ", str(t or ""))
    return re.sub(r"\s+", " ", t).strip()[:MAX_LEN]


def parse(v):
    """'a, b' 글자나 목록 → 겹치지 않는 태그 목록 (적은 순서)."""
    items = v if isinstance(v, (list, tuple)) else re.split(r"[,\n]", str(v or ""))
    out = []
    for t in items:
        t = clean(t)
        if t and t not in out:
            out.append(t)
    return out


def split(s):
    return [t for t in str(s or "").split("|") if t]


def join(tags):
    tags = [t for t in tags if t]
    return "|" + "|".join(tags) + "|" if tags else ""


def merge(old, add=(), remove=()):
    cur = [t for t in split(old) if t not in set(remove)]
    for t in add:
        if t and t not in cur:
            cur.append(t)
    return join(cur)


def store_of(row):
    """엑셀 '수집URL'로 수집한 스토어: 스마트스토어·브랜드스토어는 주소 이름(예: zenith77), 다른 곳은 사이트 주소(예: coupang.com)."""
    u = str((row or {}).get("수집URL") or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        return ""
    m = _STORE.match(u)
    if m:
        slug = m.group(1).strip()
        return clean(slug) if slug.lower() not in _SKIP_SLUG else ""
    host = urlparse(u).netloc.lower().split(":")[0]
    host = re.sub(r"^(www|m|item|detail|shop)\.", "", host)
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "or", "go", "ne", "com", "net"):
        host = ".".join(parts[-3:])
    elif len(parts) >= 2:
        host = ".".join(parts[-2:])
    return clean(host)


def for_row(row, tags, with_store):
    out = list(tags or [])
    if with_store:
        s = store_of(row)
        if s and s not in out:
            out.append(s)
    return out


def today():
    return time.strftime("%Y-%m-%d")


# ───────────────────────── 원본에 달기·빼기·목록

def counts(db):
    """모든 태그와 원본 수 (많은 순). 날짜 모양(2026-11-04)은 kind='date', 나머지는 'tag'."""
    c = Counter()
    for r in db.q("SELECT src_tags FROM sources WHERE src_tags!=''"):
        c.update(split(r["src_tags"]))
    none = db.one("SELECT COUNT(*) AS n FROM sources WHERE src_tags=''")["n"]
    rows = [{"tag": t, "count": n, "kind": "date" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t) else "tag"} for t, n in c.items()]
    rows.sort(key=lambda r: (r["kind"] == "date", -r["count"] if r["kind"] == "tag" else 0, r["tag"] if r["kind"] == "tag" else ""))
    dates = sorted((r for r in rows if r["kind"] == "date"), key=lambda r: r["tag"], reverse=True)
    return {"tags": [r for r in rows if r["kind"] == "tag"] + dates, "none": none}


def apply(db, ids, add=(), remove=()):
    """고른 원본에 태그 달기(add)·빼기(remove). 바뀐 원본 수."""
    add, remove = parse(add), parse(remove)
    if not add and not remove:
        raise ValueError("달거나 뺄 태그를 적어 주세요.")
    changed = 0
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        rows = db.q(f"SELECT id, src_tags FROM sources WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        with db.tx() as c:
            for r in rows:
                new = merge(r["src_tags"], add, remove)
                if new != r["src_tags"]:
                    c.execute("UPDATE sources SET src_tags=? WHERE id=?", (new, r["id"]))
                    changed += 1
    return changed


def rename(db, old, new):
    """태그 이름 바꾸기 (모든 원본). 새 이름을 비우면 그 태그를 지움."""
    old, new = clean(old), clean(new)
    if not old:
        raise ValueError("바꿀 태그가 없습니다.")
    rows = db.q("SELECT id, src_tags FROM sources WHERE instr(src_tags, ?)>0", (f"|{old}|",))
    with db.tx() as c:
        for r in rows:
            c.execute("UPDATE sources SET src_tags=? WHERE id=?", (merge(r["src_tags"], [new] if new else [], [old]), r["id"]))
    return len(rows)


def backfill(db, with_store=True, with_date=True, progress=None, should_stop=None):
    """예전에 불러온 원본에도 태그 채우기: 수집URL의 스토어, 처음 불러온 날(YYYY-MM-DD). 이미 있는 태그는 그대로."""
    total = db.one("SELECT COUNT(*) AS n FROM sources")["n"]
    st = {"total": total, "changed": 0, "store": 0, "date": 0}
    last, done = 0, 0
    while True:
        if should_stop and should_stop():
            break
        rows = db.q("SELECT id, src_tags, created_at, data FROM sources WHERE id>? ORDER BY id LIMIT 500", (last,))
        if not rows:
            break
        with db.tx() as c:
            for r in rows:
                add = []
                if with_store:
                    s = store_of(unpack(r["data"]))
                    if s and f"|{s}|" not in r["src_tags"]:
                        add.append(s)
                        st["store"] += 1
                if with_date and r["created_at"]:
                    d = time.strftime("%Y-%m-%d", time.localtime(r["created_at"]))
                    if f"|{d}|" not in r["src_tags"]:
                        add.append(d)
                        st["date"] += 1
                if add:
                    c.execute("UPDATE sources SET src_tags=? WHERE id=?", (merge(r["src_tags"], add), r["id"]))
                    st["changed"] += 1
        last = rows[-1]["id"]
        done += len(rows)
        if progress:
            progress(done, total, f"{done:,}개 확인")
    return st
