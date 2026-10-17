"""키프리스(KIPRIS Plus) 상표 확인.

사전에 있는 일반명사(의자·행거·수납함)는 상표로 등록돼 있어도 그 상품의 보통 명칭이라 막지 않는다.
위험한 건 일반명사를 붙여 만든 조어('효도의자', '왕자행거')라서, 확인 대상은
3글자 이상 한글 단어 중 유의어 묶음·속성 단어에 없고, 우리말샘 표제어도 아닌 것(키가 있으면 먼저 사전 확인).

단어 하나를 상표명으로 검색해서, 상표명이 그 단어와 정확히 같은(띄어쓰기·기호 무시) 상표가
    등록  → registered  (새 단어로 쓰지 않음)
    출원·공고 중 → pending (설정 kipris_block_pending이면 쓰지 않음, 기본 켜짐)
    없음(또는 거절·소멸·취하·포기뿐) → clear
결과는 db의 trademark_check 표에 남겨 다시 묻지 않는다 (180일 지나면 다시 확인).

키: plus.kipris.or.kr 회원가입 → 상표 검색 API 신청 → 발급된 키(ServiceKey).
"""

import hashlib
import os
import re
import time
import xml.etree.ElementTree as ET

from . import namegen

API = "http://plus.kipris.or.kr/kipo-api/kipi/trademarkInfoSearchService/getAdvancedSearch"
RECHECK_DAYS = 180

SCHEMA = """
CREATE TABLE IF NOT EXISTS trademark_check (
    word TEXT PRIMARY KEY,
    verdict TEXT NOT NULL,            -- registered / pending / clear / error
    allowed INTEGER NOT NULL DEFAULT 0, -- 사람이 '괜찮음'으로 허용
    marks INTEGER NOT NULL DEFAULT 0, -- 정확히 같은 이름의 등록·출원 상표 수
    classes TEXT NOT NULL DEFAULT '', -- 상품 분류 (예: 16, 21)
    titles TEXT NOT NULL DEFAULT '',  -- 출원인 등 참고
    message TEXT NOT NULL DEFAULT '',
    checked_at REAL NOT NULL
);
"""


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)


def _text(el, tag):
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def parse(xml_text, word):
    """응답 XML → (verdict, marks, classes, notes)."""
    root = ET.fromstring(xml_text)
    code = root.findtext(".//resultCode") or root.findtext(".//successYN") or ""
    msg = root.findtext(".//resultMsg") or ""
    if code and code not in ("00", "Y", "0", "000"):
        raise RuntimeError(f"키프리스 오류 {code} {msg}".strip())
    target = namegen.normalize(word)
    registered = pending = 0
    classes, notes = set(), []
    for it in root.iter("item"):
        title = _text(it, "title")
        if namegen.normalize(title) != target:
            continue  # 단어가 들어간 긴 상표(예: '보온마스터')는 세지 않음 — 정확히 같은 이름만
        st = _text(it, "applicationStatus")
        if "등록" in st:
            registered += 1
        elif any(k in st for k in ("출원", "공고", "심사")):
            pending += 1
        else:
            continue  # 거절·소멸·취하·포기·무효
        for cc in re.split(r"[|,\s]+", _text(it, "classificationCode")):
            if cc.strip():
                classes.add(cc.strip())
        who = _text(it, "applicantName")
        if who and len(notes) < 3:
            notes.append(f"{title}({st}, {who})")
    verdict = "registered" if registered else "pending" if pending else "clear"
    return verdict, registered + pending, sorted(classes, key=lambda x: (len(x), x)), notes


def check_word(word, key, session):
    params = {
        "trademarkName": word, "ServiceKey": key, "numOfRows": 100, "pageNo": 1,
        # 상태: 살아 있는 권리만 (출원·공고·등록)
        "application": "true", "registration": "true", "publication": "true",
        "refused": "false", "expiration": "false", "withdrawal": "false", "cancel": "false", "abandonment": "false",
        # 상표 종류
        "trademark": "true", "serviceMark": "true", "trademarkServiceMark": "true", "businessEmblem": "true",
        "collectiveMark": "true", "geoOrgMark": "true", "internationalMark": "true", "certMark": "true",
        "geoCertMark": "true",
        # 상표 모양: 문자가 들어간 것
        "character": "true", "compositionCharacter": "true", "figureComposition": "true", "figure": "false",
        "sound": "false", "fragrance": "false", "color": "false", "dimension": "false", "colorMixed": "false",
        "hologram": "false", "motion": "false", "visual": "false", "invisible": "false",
    }
    r = session.get(API, params=params, timeout=20)
    r.raise_for_status()
    return parse(r.text, word)


def _fake_dict(word):
    """시연 모드: 조어 예시는 사전에 없고, 나머지는 대부분 있다고 본다."""
    if word in ("효도의자", "왕자행거"):
        return False
    return int(hashlib.md5(word.encode()).hexdigest()[:4], 16) % 4 != 0


def _fake(word):
    """시연 모드: 네이버 접속 없이 그럴듯한 결과 (단어마다 항상 같은 결과)."""
    h = int(hashlib.md5(word.encode()).hexdigest()[:6], 16)
    if word in ("효도의자", "왕자행거") or h % 13 == 0:
        return "registered", 1, ["21"], [f"{word}(등록, 예시상사)"]
    if h % 17 == 0:
        return "pending", 1, ["16"], [f"{word}(출원, 예시상사)"]
    return "clear", 0, [], []


def _generic(db):
    """일반명사로 보는 단어: 유의어 묶음·속성 단어·우리말샘 표제어. 키프리스에 묻지 않는다."""
    out = {w for r in db.q("SELECT words FROM word_groups WHERE enabled=1") for w in r["words"].split(",")}
    out |= {r["word"] for r in db.q("SELECT word FROM word_attr")}
    out |= {r["word"] for r in db.q("SELECT word FROM word_dict WHERE in_dict=1")}
    return out


def candidates(db, scope):
    """상표인지 확인할 단어 후보: 붙여 쓴 조어처럼 보이는 3글자 이상 한글 단어 (자주 나오는 순).
    scope: original(원본 상품명) / keywords(네이버에서 모은 단어) / names(AI·가져온 이름) / all"""
    import collections
    cnt = collections.Counter()
    if scope in ("original", "all"):
        for r in db.q("SELECT name FROM sources WHERE valid=1"):
            cnt.update(set(r["name"].split()))
    if scope in ("keywords", "all"):
        for r in db.q("SELECT word, COUNT(*) AS n FROM source_kw GROUP BY word"):
            cnt[r["word"]] += r["n"]
    if scope in ("names", "all"):
        for r in db.q("SELECT name FROM names WHERE listing_id IS NULL AND origin IN ('ai','import')"):
            cnt.update(set(r["name"].split()))
    generic = _generic(db)
    return [w for w, _ in cnt.most_common() if re.fullmatch(r"[가-힣]{3,10}", w) and w not in generic]


def words_to_check(db, scope, limit):
    """아직 확인 안 한 후보 (180일 지나면 다시)."""
    fresh = time.time() - RECHECK_DAYS * 86400
    done = {r["word"] for r in db.q("SELECT word FROM trademark_check WHERE checked_at>? AND verdict!='error'", (fresh,))}
    return [w for w in candidates(db, scope) if w not in done][:limit]


def check_words(db, cfg, scope="all", progress=None, should_stop=None):
    """단어들을 키프리스에서 확인해 trademark_check에 저장한다."""
    import requests
    from . import lexicon
    fake = os.environ.get("UPLOADER_FAKE_API") == "1"
    key = (cfg.get("kipris_key") or "").strip()
    if not key and not fake:
        raise RuntimeError("설정 → 상표 확인에서 키프리스(KIPRIS Plus) 키를 먼저 넣어 주세요 (plus.kipris.or.kr).")
    todo = words_to_check(db, scope, int(cfg.get("kipris_limit") or 500))
    s = requests.Session()
    stats = {"checked": 0, "registered": 0, "pending": 0, "errors": 0, "examples": [], "in_dict": 0}
    od_key = (cfg.get("opendict_key") or "").strip()
    for i, w in enumerate(todo, 1):
        if should_stop and should_stop():
            break
        # 먼저 우리말샘: 표제어로 있으면 일반명사 → 키프리스에 묻지 않음 (예: '수납함'). 붙여 만든 조어만 남는다.
        if od_key or fake:
            known = db.one("SELECT in_dict FROM word_dict WHERE word=?", (w,))
            if known is None:
                try:
                    in_dict = _fake_dict(w) if fake else lexicon.in_dictionary(w, od_key, s)
                    db.x("INSERT OR REPLACE INTO word_dict(word, in_dict, checked_at) VALUES(?,?,?)",
                         (w, int(in_dict), time.time()))
                except Exception:  # noqa: BLE001 - 사전을 못 보면 키프리스로 확인
                    in_dict = False
            else:
                in_dict = bool(known["in_dict"])
            if in_dict:
                stats["in_dict"] += 1
                if progress:
                    progress(i, len(todo), f"{w} → 사전 단어")
                continue
        try:
            verdict, marks, classes, notes = _fake(w) if fake else check_word(w, key, s)
            msg = ""
        except Exception as e:  # noqa: BLE001
            stats["errors"] += 1
            if stats["errors"] >= 5 and not stats["checked"]:
                raise RuntimeError(f"키프리스에 연결하지 못했습니다: {e}")
            verdict, marks, classes, notes, msg = "error", 0, [], [], str(e)[:300]
        db.x("""INSERT INTO trademark_check(word, verdict, marks, classes, titles, message, checked_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(word) DO UPDATE SET verdict=excluded.verdict, marks=excluded.marks,
            classes=excluded.classes, titles=excluded.titles, message=excluded.message, checked_at=excluded.checked_at""",
             (w, verdict, marks, ",".join(classes), " / ".join(notes), msg, time.time()))
        if verdict in ("registered", "pending"):
            stats[verdict] += 1
            if len(stats["examples"]) < 5:
                stats["examples"].append(f"{w}({'등록' if verdict == 'registered' else '출원'})")
        stats["checked"] += 1
        if progress:
            progress(i, len(todo), f"{w} → {verdict}")
        if not fake:
            time.sleep(0.15)
    with db.tx() as c:
        lexicon._bump(c)  # 단어 사전 다시 읽게
    return stats
