"""다른 스토어 상하단·배너 잡기: 이미지 주소를 정규화한 열쇠 + 그림 내용(지각 해시)으로 '같은 이미지'를 묶는다.

- 주소 열쇠(url_key): 스킴(http·https·//) 통일, 호스트 소문자, 쿼리(?type=w860 등)·# 제거, URL 디코드.
  → 같은 열쇠면 같은 이미지.
- 그림 해시(dHash 64비트): 이미지를 내려받아 9×8 회색으로 줄여 옆 칸 밝기 비교. 해밍 거리 HAM_MAX 이하면 같은 그림
  (주소·경로가 달라도, 크기가 달라도). 한 번 받은 해시는 img_hash 표에 남겨 다시 받지 않는다.
- 내 템플릿 이미지(스토어 템플릿 상단·하단 — 이 PC 파일, 네이버에 올린 주소, 템플릿 HTML 안 이미지)는
  고를 수 없고, 기억 규칙에 들어가지 않고, 자동 빼기에서도 절대 빼지 않는다.
- 기억한 배너(clean_rule image): 상세 정리 엑셀 올리기·판매 중 상품 연결·수집 상품 넣기(원본에서 뺌)와
  등록·최신화·다시 올리기·네이버 상세 바꾸기(보낼 HTML에서만 뺌 — 원본은 그대로) 때 뺀다. 등록 중엔 새로 내려받지 않고
  이미 받아 둔 해시만 쓴다.
"""

import base64
import io
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlsplit

HAM_MAX = 6          # 그림 해시 해밍 거리 이 이하면 같은 그림
EDGE_N = 3           # 상하단 자리: 위 3장·아래 3장
FETCH_THREADS = 20
FETCH_TIMEOUT = 5
SAVE_EVERY = 100      # 이만큼 받을 때마다 캐시에 저장 (중지해도 받은 것은 남음)
THUMB = "type=w100"   # 네이버(pstatic) 이미지는 작은 썸네일로 받음 — 그림 해시는 9×8로 줄여 비교하므로 정확도는 같음
MAX_BYTES = 8 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS img_hash (
    key TEXT PRIMARY KEY,            -- 정규화한 주소 열쇠
    hash TEXT NOT NULL DEFAULT '',   -- dHash 16자리(64비트), 못 받았으면 ''
    w INTEGER, h INTEGER,
    fail TEXT NOT NULL DEFAULT '',
    at REAL NOT NULL
);
"""

_IMG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r"""\bsrc\s*=\s*(["'])(.*?)\1""", re.I | re.S)
_PAD = r"(?:\s|<br\s*/?>|&nbsp;)*"
_EMPTY = re.compile(rf"<(div|p|center|span|a)\b[^>]*>{_PAD}</\1>", re.I)


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)
        have = {r[1] for r in c.execute("PRAGMA table_info(clean_rule)").fetchall()}
        if have:
            if "key" not in have:
                c.execute("ALTER TABLE clean_rule ADD COLUMN key TEXT NOT NULL DEFAULT ''")
            if "hash" not in have:
                c.execute("ALTER TABLE clean_rule ADD COLUMN hash TEXT NOT NULL DEFAULT ''")
            for r in c.execute("SELECT id, value FROM clean_rule WHERE key=''").fetchall():
                c.execute("UPDATE clean_rule SET key=? WHERE id=?", (url_key(r[1]), r[0]))


# ───────────────────────── 주소 열쇠

def url_key(src):
    s = str(src or "").strip().replace("&amp;", "&")
    if not s:
        return ""
    if s.startswith("data:"):
        import hashlib
        return "data:" + hashlib.md5(s.encode("utf-8", "ignore")).hexdigest()
    if s.startswith("//"):
        s = "https:" + s
    try:
        p = urlsplit(s)
    except ValueError:
        return s
    if not p.netloc:
        return unquote(s.split("?")[0].split("#")[0])
    return f"{p.netloc.lower()}{unquote(p.path)}"


def img_srcs(html):
    out = []
    for t in _IMG.findall(str(html or "")):
        m = _SRC.search(t)
        if m and m.group(2).strip():
            out.append(m.group(2).strip())
    return out


def edge_srcs(html, n=EDGE_N):
    """(위 n장, 아래 n장) — 겹치지 않게 (이미지가 적으면 위에만)."""
    srcs = img_srcs(html)
    top = srcs[:n]
    bottom = srcs[max(n, len(srcs) - n):]
    return top, bottom


def remove_where(html, pred):
    """pred(src)=True인 <img>를 상세에서 뺀다 (이미지 하나만 감싸던 칸, 비게 된 칸도 같이). (새 HTML, 뺀 수)"""
    html = str(html or "")
    n = [0]

    def wrap(m):
        s = _SRC.search(m.group(2))
        if s and pred(s.group(2).strip()):
            n[0] += 1
            return ""
        return m.group(0)

    def one(m):
        s = _SRC.search(m.group(0))
        if s and pred(s.group(2).strip()):
            n[0] += 1
            return ""
        return m.group(0)

    html = re.sub(rf"<(div|p|a|span|center)\b[^>]*>{_PAD}(<img\b[^>]*>){_PAD}</\1>", wrap, html, flags=re.I)
    html = _IMG.sub(one, html)
    if n[0]:
        for _ in range(3):
            html, k = _EMPTY.subn("", html)
            if not k:
                break
    return html, n[0]


# ───────────────────────── 그림 해시

def dhash(data):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    w, h = im.size
    if getattr(im, "is_animated", False):
        im.seek(0)
    g = im.convert("L").resize((9, 8))
    px = list(g.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if px[y * 9 + x] > px[y * 9 + x + 1] else 0)
    return f"{bits:016x}", w, h


def ham(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _download(src):
    s = str(src or "").strip().replace("&amp;", "&")
    if s.startswith("data:"):
        head, _, body = s.partition(",")
        return base64.b64decode(body) if ";base64" in head else unquote(body).encode("latin-1", "ignore")
    if s.startswith("//"):
        s = "https:" + s
    if os.path.isfile(s):
        with open(s, "rb") as f:
            return f.read()
    import requests
    host = (urlsplit(s).netloc or "").lower()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
               "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
    if "pstatic.net" in host or "naver" in host:
        headers["Referer"] = "https://smartstore.naver.com/"
    r = None
    if "pstatic.net" in host:   # 작은 썸네일 먼저 (안 되면 원래 크기)
        try:
            r = requests.get(s.split("?")[0] + "?" + THUMB, headers=headers, timeout=FETCH_TIMEOUT, stream=True)
            if r.status_code >= 400 or "image" not in (r.headers.get("Content-Type") or "image"):
                r = None
        except Exception:  # noqa: BLE001
            r = None
    if r is None:
        r = requests.get(s, headers=headers, timeout=FETCH_TIMEOUT, stream=True)
    r.raise_for_status()
    buf = io.BytesIO()
    for chunk in r.iter_content(65536):
        buf.write(chunk)
        if buf.tell() > MAX_BYTES:
            break
    return buf.getvalue()


def cached(db, keys):
    """{열쇠: 해시} — 받아 둔 것만 (못 받은 것은 빠짐)."""
    out, keys = {}, [k for k in dict.fromkeys(keys) if k]
    for i in range(0, len(keys), 500):
        ch = keys[i:i + 500]
        for r in db.q(f"SELECT key, hash FROM img_hash WHERE hash!='' AND key IN ({','.join('?' * len(ch))})", ch):
            out[r["key"]] = r["hash"]
    return out


def fetch_hashes(db, srcs, progress=None, should_stop=None):
    """주소들의 그림 해시를 받아 캐시에 넣는다 (이미 받은 것·실패한 것은 다시 받지 않음). {got, fail, cached}
    srcs 순서대로 받는다(앞에 둔 것 먼저 — 위1·아래1). SAVE_EVERY장마다 저장해 중지해도 받은 것은 남는다."""
    by_key = {}
    for s in srcs:
        k = url_key(s)
        if k and k not in by_key:
            by_key[k] = s
    done = set()
    keys = list(by_key)
    for i in range(0, len(keys), 500):
        ch = keys[i:i + 500]
        done |= {r["key"] for r in db.q(f"SELECT key FROM img_hash WHERE key IN ({','.join('?' * len(ch))})", ch)}
    todo = [(k, by_key[k]) for k in keys if k not in done]
    st = {"got": 0, "fail": 0, "cached": len(done), "total": len(keys)}
    if not todo:
        return st
    lock = threading.Lock()
    rows, unsaved = [], []

    def save():
        with lock:
            batch = list(unsaved)
            unsaved.clear()
        if batch:
            now_ = time.time()
            with db.tx() as c:
                c.executemany("INSERT OR REPLACE INTO img_hash(key, hash, w, h, fail, at) VALUES(?,?,?,?,?,?)",
                              [(k, h, w, hh, f, now_) for k, h, w, hh, f in batch])

    def one(item):
        k, s = item
        if should_stop and should_stop():
            return
        try:
            h, w, hh = dhash(_download(s))
            res = (k, h, w, hh, "")
        except Exception as e:  # noqa: BLE001 - 못 받은 그림은 주소로만 판단
            res = (k, "", None, None, str(e)[:200])
        with lock:
            rows.append(res)
            unsaved.append(res)
            st["got" if res[1] else "fail"] += 1
            n_ = len(rows)
            if progress and n_ % 10 == 0:
                progress(n_, len(todo), f"그림 비교용으로 이미지 받는 중 {n_:,}/{len(todo):,}")
        if n_ % SAVE_EVERY == 0:
            save()

    with ThreadPoolExecutor(FETCH_THREADS) as pool:
        list(pool.map(one, todo))
    save()
    return st


def edge_order(htmls):
    """상세들의 상하단 자리 이미지를 받을 순서로: 위1·아래1 먼저, 그다음 위2·아래2 …"""
    tiers = [[] for _ in range(EDGE_N)]
    for html in htmls:
        srcs = img_srcs(html)
        n = len(srcs)
        for j in range(min(EDGE_N, n)):
            tiers[j].append(srcs[j])
            if n - 1 - j > j:
                tiers[j].append(srcs[n - 1 - j])
    return [s for t in tiers for s in t]


_pre = {"lock": threading.Lock(), "q": [], "busy": False}


def prefetch_async(db, htmls):
    """넣은 직후 뒤에서 상하단 자리 그림 해시를 미리 받아 둔다 (한 번에 하나씩, 겹쳐 부르면 이어서)."""
    srcs = edge_order(list(htmls))
    if not srcs:
        return
    with _pre["lock"]:
        _pre["q"].extend(srcs)
        if _pre["busy"]:
            return
        _pre["busy"] = True

    def run():
        try:
            while True:
                with _pre["lock"]:
                    batch, _pre["q"] = _pre["q"], []
                    if not batch:
                        _pre["busy"] = False
                        return
                try:
                    fetch_hashes(db, batch)
                    refresh_rule_hashes(db)
                except Exception:  # noqa: BLE001 - 미리 받기는 실패해도 그만
                    pass
        finally:
            with _pre["lock"]:
                _pre["busy"] = False
    threading.Thread(target=run, daemon=True).start()


# ───────────────────────── 묶기

def group_keys(keys, hashes):
    """열쇠들을 같은 그림끼리 묶음 → {열쇠: 묶음 대표 열쇠}. 해시가 없는 열쇠는 혼자."""
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    hk = [(k, int(hashes[k], 16)) for k in keys if k in hashes]
    # 8칸(8비트씩)으로 나눠 한 칸이라도 같은 것끼리만 비교 (해밍 7 이하면 반드시 한 칸은 같음)
    for band in range(8):
        buckets = {}
        for k, v in hk:
            buckets.setdefault((v >> (band * 8)) & 0xFF, []).append((k, v))
        for items in buckets.values():
            if len(items) < 2 or len(items) > 400:
                if len(items) > 400:   # 너무 흔한 칸(단색 등)은 정확히 같은 해시끼리만
                    ex = {}
                    for k, v in items:
                        if v in ex:
                            union(k, ex[v])
                        else:
                            ex[v] = k
                continue
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    if bin(items[i][1] ^ items[j][1]).count("1") <= HAM_MAX:
                        union(items[i][0], items[j][0])
    return {k: find(k) for k in keys}


# ───────────────────────── 내 템플릿 이미지

def template_marks(db):
    """(열쇠 set, 해시 list) — 모든 스토어 템플릿 상단·하단 이미지(이 PC 파일·네이버에 올린 주소·템플릿 HTML 안 이미지)."""
    from . import templates
    keys, hashes = set(), []
    for s in db.q("SELECT id, tpl_top_html, tpl_bottom_html FROM stores"):
        for part in ("top", "bottom"):
            for src in img_srcs(s[f"tpl_{part}_html"]):
                keys.add(url_key(src))
            for _, p in templates.images(s["id"], part):
                try:
                    with open(p, "rb") as f:
                        hashes.append(dhash(f.read())[0])
                except Exception:  # noqa: BLE001
                    pass
    for r in db.q("SELECT naver_url FROM images WHERE src LIKE 'tpl:%'"):
        keys.add(url_key(r["naver_url"]))
    hashes += [h for h in cached(db, keys).values()]
    return keys, list(dict.fromkeys(hashes))


def is_template(key, h, marks):
    keys, hashes = marks
    if key in keys:
        return True
    return bool(h) and any(ham(h, t) <= HAM_MAX for t in hashes)


# ───────────────────────── 기억한 배너 (자동 빼기)

class Remover:
    """기억한 배너를 상세에서 빼는 함수 묶음. 주소 열쇠는 늘, 그림 해시는 캐시에 있는 것만(fetch=False면 새로 안 받음).
    내 템플릿 이미지는 절대 빼지 않는다."""

    def __init__(self, db, fetch=False):
        self.db = db
        self.fetch = fetch
        rs = db.q("SELECT key, hash, value FROM clean_rule WHERE kind='image'")
        self.marks = template_marks(db)
        self.keys = {r["key"] or url_key(r["value"]) for r in rs}
        self.hashes = [r["hash"] for r in rs if r["hash"]]
        self.keys = {k for k in self.keys if k and k not in self.marks[0]}
        self.hashes = [h for h in self.hashes if not any(ham(h, t) <= HAM_MAX for t in self.marks[1])]
        self.active = bool(self.keys or self.hashes)

    def __call__(self, html):
        if not self.active or not html:
            return str(html or ""), 0
        srcs = img_srcs(html)
        if not srcs:
            return str(html), 0
        ks = {s: url_key(s) for s in srcs}
        hs = {}
        if self.hashes:
            if self.fetch:
                fetch_hashes(self.db, srcs)
            hs = cached(self.db, ks.values())

        def pred(src):
            k = ks.get(src) or url_key(src)
            h = hs.get(k)
            if is_template(k, h, self.marks):
                return False
            if k in self.keys:
                return True
            return bool(h) and any(ham(h, r) <= HAM_MAX for r in self.hashes)
        return remove_where(html, pred)

    def strip_row(self, row):
        """row의 상세설명에서 뺀 새 row와 뺀 수 (원본 row는 안 바꿈)."""
        if not self.active or not row:
            return row, 0
        html, n = self(row.get("상세설명"))
        if not n:
            return row, 0
        return {**row, "상세설명": html}, n


def remember(db, items):
    """기억 규칙 더하기: [(대표 주소, 열쇠)] — 템플릿 이미지는 넣지 않음. 넣은 수."""
    marks = template_marks(db)
    hs = cached(db, [k for _, k in items])
    n = 0
    now = time.time()
    with db.tx() as c:
        for src, k in items:
            k = k or url_key(src)
            if not k or is_template(k, hs.get(k), marks):
                continue
            if c.execute("SELECT 1 FROM clean_rule WHERE kind='image' AND key=?", (k,)).fetchone():
                continue
            c.execute("INSERT OR IGNORE INTO clean_rule(kind, value, created_at, key, hash) VALUES('image', ?, ?, ?, ?)",
                      (src, now, k, hs.get(k, "")))
            n += 1
    return n


def refresh_rule_hashes(db):
    """해시가 비어 있는 기억 규칙에 캐시 해시를 채움."""
    with db.tx() as c:
        for r in c.execute("SELECT id, key FROM clean_rule WHERE kind='image' AND hash=''").fetchall():
            h = c.execute("SELECT hash FROM img_hash WHERE key=? AND hash!=''", (r[1],)).fetchone()
            if h:
                c.execute("UPDATE clean_rule SET hash=? WHERE id=?", (h[0], r[0]))
