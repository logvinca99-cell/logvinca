"""구글 메일함 연결: 네이버가 보낸 메일(판매금지·경고·제재, 주문·문의 알림, 인증번호)을 지메일에서 읽어 스토어별로 모아 본다.

- 지메일 IMAP + 앱 비밀번호 (구글 계정 2단계 인증을 켠 뒤 '앱 비밀번호'에서 만든 16자리). 읽기만 한다
  (읽음 표시도 바꾸지 않음 · BODY.PEEK).
- 스토어 구분: 받는 주소(스토어마다 '받는 메일 주소'를 정해 두면, 예: me+redcoco@gmail.com) → 메일 안의 스토어 이름·주소.
- 메일 안의 10자리 상품번호를 복사본(원상품·채널 번호)과 맞춰 어느 복사본 얘기인지 붙인다.
"""

import email
import html
import imaplib
import json
import os
import random
import re
import time
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS mails (
    id INTEGER PRIMARY KEY,
    msgid TEXT NOT NULL UNIQUE,
    received_at REAL NOT NULL,
    from_addr TEXT NOT NULL DEFAULT '',
    to_addr TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'etc',     -- warn 경고·제재 / order 주문·문의 / auth 인증번호 / etc
    code TEXT NOT NULL DEFAULT '',        -- 인증번호 (auth)
    store_id INTEGER,
    products TEXT NOT NULL DEFAULT '[]',  -- [{no, listing_id, name}]
    handled INTEGER NOT NULL DEFAULT 0,   -- 확인함 표시 (경고 메일 처리했는지)
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS mails_received ON mails(received_at);
"""

KIND_RULES = [
    ("auth", re.compile(r"인증\s*번호|인증\s*코드|본인\s*확인|verification code", re.I)),
    ("warn", re.compile(r"판매\s*금지|판매\s*중지|제재|경고|위반|소명|지식\s*재산|권리\s*침해|허위|가품|위조|불량|패널티|페널티|이용\s*제한|노출\s*제한|삭제\s*처리|부적합|신고")),
    ("order", re.compile(r"주문|문의|발송|배송|취소|반품|교환|구매\s*확정|정산")),
]
KIND_LABEL = {"warn": "경고·제재", "order": "주문·문의", "auth": "인증번호", "etc": "기타"}
PRODUCT_NO = re.compile(r"(?<!\d)(\d{10,11})(?!\d)")
AUTH_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def _dec(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:  # noqa: BLE001
        return str(v or "")


def _text(msg):
    """본문 글자: text/plain과 html(태그 뺌) 중 내용이 긴 쪽 (네이버 메일은 plain이 짧은 안내뿐인 경우가 많음)."""
    plain, rich = [], []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ct = part.get_content_type()
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            data = part.get_payload(decode=True) or b""
            s = data.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        (plain if ct == "text/plain" else rich if ct == "text/html" else []).append(s)
    s = "\n".join(rich)
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = re.sub(r"[ \t]+", " ", html.unescape(s))
    p = "\n".join(plain)
    return p if len(p.strip()) >= len(s.strip()) else s


def classify(subject, body):
    text = f"{subject}\n{body[:3000]}"
    for kind, rx in KIND_RULES:
        if rx.search(subject):
            return kind
    for kind, rx in KIND_RULES:
        if rx.search(text):
            return kind
    return "etc"


def match_store(stores, to_addr, subject, body):
    to = to_addr.lower()
    for s in stores:
        alias = str(s.get("mail_to") or "").strip().lower()
        if alias and alias in to:
            return s["id"]
    text = f"{subject}\n{body[:5000]}"
    for s in sorted(stores, key=lambda s: -len(s.get("name") or "")):
        slug = str(s.get("store_url") or "").rstrip("/").rsplit("/", 1)[-1]
        if (s.get("name") and s["name"] in text) or (slug and len(slug) >= 3 and slug in text):
            return s["id"]
    return None


def match_products(db, store_id, text):
    nos = list(dict.fromkeys(PRODUCT_NO.findall(text)))[:20]
    if not nos:
        return []
    marks = ",".join("?" * len(nos))
    rows = db.q(f"""SELECT id, store_id, origin_no, channel_no, name FROM listings
        WHERE origin_no IN ({marks}) OR channel_no IN ({marks})""", (*nos, *nos))
    by = {}
    for r in rows:
        for k in ("origin_no", "channel_no"):
            if r[k]:
                by.setdefault(str(r[k]), r)
    out = []
    for n in nos:
        r = by.get(n)
        if r or len(out) < 5:
            out.append({"no": n, "listing_id": r["id"] if r else None, "store_id": r["store_id"] if r else None,
                        "origin_no": r["origin_no"] if r else "", "name": (r["name"] if r else "")[:60]})
    return out


def _save(db, stores, msgid, received, frm, to, subject, body):
    kind = classify(subject, body)
    code = ""
    if kind == "auth":
        m = AUTH_CODE.search(f"{subject}\n{body}")
        code = m.group(1) if m else ""
    sid = match_store(stores, to, subject, body)
    prods = match_products(db, sid, f"{subject}\n{body}")
    if not sid:
        sid = next((p["store_id"] for p in prods if p.get("store_id")), None)
    snippet = re.sub(r"\s+", " ", body).strip()[:400]
    db.x("""INSERT OR IGNORE INTO mails(msgid, received_at, from_addr, to_addr, subject, snippet, kind, code, store_id, products, fetched_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (msgid, received, frm[:200], to[:300], subject[:300], snippet, kind, code, sid,
                                           json.dumps(prods, ensure_ascii=False), time.time()))
    return kind


def fetch(db, cfg, days=None, progress=None, should_stop=None):
    """지메일에서 최근 메일을 읽어 저장 (이미 받은 메일은 건너뜀)."""
    days = int(days or cfg.get("mail_days") or 7)
    stores = db.stores()
    st = {"checked": 0, "new": 0, "warn": 0, "order": 0, "auth": 0, "etc": 0}
    if os.environ.get("UPLOADER_FAKE_API") == "1":
        return _fake(db, stores, st)
    user, pw = str(cfg.get("gmail_user") or "").strip(), str(cfg.get("gmail_app_password") or "").replace(" ", "")
    if not user or not pw:
        raise RuntimeError("설정 → API 키 → 구글 메일함에 지메일 주소와 앱 비밀번호를 넣어 주세요.")
    frm = str(cfg.get("mail_from") or "naver").strip()
    try:
        im = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=60)
    except TypeError:   # 예전 파이썬
        im = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        try:
            im.login(user, pw)
        except imaplib.IMAP4.error as e:
            raise RuntimeError(f"지메일 로그인 실패: {e} — 앱 비밀번호(16자리)가 맞는지, 지메일 설정에서 IMAP이 켜져 있는지 확인하세요.") from None
        im.select("INBOX", readonly=True)
        typ, data = im.search(None, "X-GM-RAW", f'"from:{frm} newer_than:{days}d"')
        if typ != "OK":
            since = time.strftime("%d-%b-%Y", time.gmtime(time.time() - days * 86400))
            typ, data = im.search(None, f'(SINCE {since} FROM "{frm}")')
        ids = (data[0] or b"").split() if typ == "OK" else []
        have = {r["msgid"] for r in db.q("SELECT msgid FROM mails WHERE received_at>=?", (time.time() - (days + 2) * 86400,))}
        for i, num in enumerate(reversed(ids), 1):
            if should_stop and should_stop():
                break
            typ, hd = im.fetch(num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            mid = ""
            if typ == "OK" and hd and isinstance(hd[0], tuple):
                mid = email.message_from_bytes(hd[0][1]).get("Message-ID", "").strip()
            mid = mid or f"uid:{num.decode()}"
            st["checked"] += 1
            if mid in have:
                continue
            typ, md = im.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not md or not isinstance(md[0], tuple):
                continue
            msg = email.message_from_bytes(md[0][1])
            try:
                received = parsedate_to_datetime(msg.get("Date")).timestamp()
            except Exception:  # noqa: BLE001
                received = time.time()
            to = ", ".join(a for _, a in getaddresses(msg.get_all("To", []) + msg.get_all("Delivered-To", [])))
            kind = _save(db, stores, mid, received, _dec(msg.get("From")), to, _dec(msg.get("Subject")), _text(msg))
            st["new"] += 1
            st[kind] += 1
            if progress:
                progress(i, len(ids), f"새 메일 {st['new']:,}통 (경고·제재 {st['warn']:,})")
    finally:
        try:
            im.logout()
        except Exception:  # noqa: BLE001
            pass
    return st


def _fake(db, stores, st):
    """시연 모드: 네이버 메일처럼 생긴 메일 몇 통."""
    lst = db.q("SELECT store_id, origin_no, channel_no, name FROM listings WHERE origin_no!='' LIMIT 5")
    samples = []
    for i, l in enumerate(lst[:3]):
        s = next((x for x in stores if x["id"] == l["store_id"]), {"name": ""})
        samples.append((f"[네이버 스마트스토어] 상품 판매금지 안내 ({s['name']})",
                        f"안녕하세요. {s['name']} 판매자님, 아래 상품이 지식재산권 침해 신고로 판매금지 처리되었습니다. 상품번호 {l['origin_no']} · {l['name']} · 7일 안에 소명해 주세요."))
    samples += [("[네이버] 인증번호 안내", f"인증번호 [{random.randint(100000, 999999)}]를 입력해 주세요."),
                (f"[스마트스토어] 새 주문이 들어왔습니다 ({stores[0]['name'] if stores else ''})", "결제 완료 주문 1건이 있습니다. 발송 처리를 해 주세요.")]
    for i, (subj, body) in enumerate(samples):
        mid = f"<fake-{int(time.time() // 3600)}-{i}@naver.com>"
        if db.one("SELECT 1 FROM mails WHERE msgid=?", (mid,)):
            continue
        kind = _save(db, stores, mid, time.time() - i * 600, "스마트스토어 <noreply@navercorp.com>", "me@gmail.com", subj, body)
        st["new"] += 1
        st[kind] += 1
        st["checked"] += 1
    return st


def query(db, kind="", store_id=None, q="", handled=None, page=1, size=100):
    w, a = [], []
    if kind:
        w.append("kind=?")
        a.append(kind)
    if store_id:
        w.append("store_id=?")
        a.append(int(store_id))
    if q:
        w.append("(subject LIKE ? OR snippet LIKE ? OR products LIKE ?)")
        a += [f"%{q}%"] * 3
    if handled in ("0", "1"):
        w.append("handled=?")
        a.append(int(handled))
    where = (" WHERE " + " AND ".join(w)) if w else ""
    rows = db.q(f"SELECT * FROM mails{where} ORDER BY received_at DESC LIMIT ? OFFSET ?", (*a, size, (max(1, page) - 1) * size))
    for r in rows:
        r["products"] = json.loads(r["products"] or "[]")
    counts = {r["kind"]: r["n"] for r in db.q("SELECT kind, COUNT(*) AS n FROM mails GROUP BY kind")}
    counts["warn_open"] = db.one("SELECT COUNT(*) AS n FROM mails WHERE kind='warn' AND handled=0")["n"]
    total = db.one(f"SELECT COUNT(*) AS n FROM mails{where}", a)["n"]
    return {"rows": rows, "total": total, "counts": counts}
