"""단어 사전: 재조합 때 새로 넣을 일반명사와, 한 상품명 안의 단어 반복 검사.

새 단어 출처 (모두 토큰·비용 없음)
    1. 유의어 묶음  - 프로그램에 기본으로 든 일반명사 묶음(SEED_GROUPS) + 화면에서 고친 것 + 우리말샘에서 받은 것
    2. 카테고리 단어 - 원본의 네이버 카테고리 이름 (네이버가 정한 일반명사)
    3. 엑셀 상품태그 - 설정으로 켰을 때만 (태그가 상품과 안 맞는 경우가 있어 기본 꺼짐)

지재권 안전장치
    - 한글로만 된 단어만 새로 넣는다 (영문·숫자는 브랜드·모델명일 수 있음)
    - 금지 단어(상표에서 온 말, '정품'·'스타일'·'호환' 같은 표현)는 절대 넣지 않는다
    - 새로 넣는 것은 사전의 일반명사뿐. 원본에 있던 단어는 그대로 둔다

반복 검사
    한 상품명 안에서 같은 단어가 max_word_repeat(기본 2)번보다 많이 나오면 안 된다.
    '테이프 / 방수테이프 / 접착테이프'처럼 다른 단어 안에 들어 있어도 같은 단어로 센다.
"""

import json
import os
import re
import threading
import time

# 한 줄에 한 묶음. 같은 줄의 단어는 서로 바꿔 쓸 수 있는 일반명사.
SEED_GROUPS = """
수리,보수,수선
보관함,수납함,정리함
수납,보관,정리
수납장,캐비닛
수납박스,정리박스,보관박스
가방,백
파우치,주머니
봉투,포장봉투
상자,박스
케이스,보관케이스
컵,잔
그릇,용기
뚜껑,덮개
덮개,커버
받침대,거치대
거치대,스탠드
선반,랙
걸이,고리
옷걸이,행거
줄,끈
끈,로프
테이프,접착테이프
접착제,본드
매트,깔개
매트,러그
러그,카펫
방석,쿠션
완충재,포장재
장갑,글러브
모자,캡
신발,슈즈
양말,삭스
수건,타월
조명,라이트,램프
전등,조명등
무드등,수면등
시계,클락
거울,미러
의자,체어
책상,데스크
테이블,탁자
소파,쇼파
침대,베드
이불,침구
베개,필로우
커튼,가림막
칸막이,파티션
청소기,클리너
솔,브러시
세정제,세제
분무기,스프레이
분무기,분사기
공구,툴
망치,해머
칼,커터
가위,재단가위
집게,클립
클램프,고정구
나사,볼트
나사,스크류
펌프,주입기
호스,관
노즐,분사구
필터,여과기
장난감,완구
화분,플랜터
씨앗,종자
비료,영양제
그물,네트
울타리,펜스
텐트,천막
옷,의류
바지,팬츠
치마,스커트
조끼,베스트
앞치마,에이프런
작업복,유니폼
안전모,헬멧
보호대,가드
선물,기프트
세트,구성
대용량,빅사이즈
소형,미니
휴대용,포터블
업소용,업무용,상업용
산업용,공업용
차량용,자동차용
캠핑,아웃도어
주방,키친
욕실,화장실
사무용,오피스
어린이,아동,키즈
유아,아기,베이비
반려동물,펫
강아지,애견
고양이,반려묘
장식,데코
인테리어,데코
액자,프레임
스티커,시트지
벽지,도배지
타일,바닥재
페인트,도료
붓,브러쉬
몰드,틀,형틀
거푸집,형틀
도자기,도예
캔들,양초
워머,온열기
히터,난방기,온풍기
선풍기,송풍기
충전기,차저
어댑터,아답터
배터리,건전지
전선,케이블
멀티탭,전원탭
저울,계량기
온도계,온도측정기
측정기,계측기
줄자,측정자
자,눈금자
노트,공책
펜,필기구
메모지,메모패드
파일,바인더
도장,스탬프
현수막,배너
라벨,스티커라벨
비닐,필름
랩,포장랩
보냉백,아이스백
아이스박스,쿨러
물병,보틀
텀블러,보온컵
보온병,보온보틀
도시락,런치박스
접시,플레이트
도마,커팅보드
채반,소쿠리
바구니,바스켓
쟁반,트레이
카트,손수레
손수레,운반차
사다리,발판
방한,보온
보온,단열
단열재,보온재
방음,차음
미끄럼방지,논슬립
"""

# 상표에서 온 말·브랜드, 짝퉁·사칭으로 보일 수 있는 표현. 새 단어로 절대 넣지 않는다.
DEFAULT_BLOCK = """
포스트잇,스카치테이프,스카치,호치키스,스티로폼,포크레인,크리넥스,대일밴드,바세린,지프,제록스,봉고,
락앤락,타파웨어,코렐,다이슨,샤오미,애플,삼성,엘지,lg,LG,나이키,아디다스,뽁뽁이,에어캡,벨크로,찍찍이,
정품,명품,가품,짝퉁,레플리카,스타일,호환,st,ST,최고,최저가,1위,특가,무료배송,할인
"""

# 일반명사라도 표시·광고 규정(효능·인증·원산지·과장)에 걸릴 수 있는 말. 근거 없이 쓰면 안 되므로 새로 넣지 않는다.
CLAIM_BLOCK = """
치료,완치,의료용,의료기기,의약,처방,통증완화,질병,예방,무독성,무해,친환경,유기농,천연,항균,살균,멸균,소독,
인증,KC인증,특허,국산,국내산,국내생산,국내제작,한국산,공식,공식판매,독점,최초,유일,살충,방역,FDA,
"""

# 속성 단어: 같은 종류 상품을 서로 다른 상품으로 가르는 말(재질·모양·색·크기 등).
# 네이버에서 모은 키워드 중 이런 말은 원본(상품명·옵션·상세설명)에 그 말이 있을 때만 쓴다.
# 이 말이 들어간 단어(원목책상 등)도 같은 규칙. 끝이 '~식·~형·~색'인 3글자 이상 단어도 속성으로 본다.
ATTR_SEED = """
원목,우드,나무,목재,원목형,철제,스틸,금속,메탈,알루미늄,스테인리스,스텐,유리,강화유리,아크릴,플라스틱,실리콘,고무,
가죽,인조가죽,패브릭,천,면,린넨,라탄,대나무,세라믹,도자기,대리석,석재,종이,골판지,비닐,
접이식,폴딩,조립식,높이조절,각도조절,회전,원형,사각,사각형,타원,코너,좌식,입식,스탠딩,이동식,벽걸이,
무선,유선,충전식,건전지,자동,수동,방수,투명,반투명,
화이트,블랙,그레이,베이지,브라운,아이보리,네이비,핑크,레드,블루,그린,옐로우,오렌지,퍼플,실버,골드,
흰색,검정,검은색,회색,갈색,빨강,파랑,초록,노랑,
대형,중형,소형,미니,특대,초대형,슬림,와이드,롱,숏,
일인용,이인용,삼인용,아동용,유아용,성인용,남성용,여성용
"""
ATTR_ENDINGS = ("식", "형", "색")

SUFFIXES = ("용", "형", "식")
_HANGUL_WORD = re.compile(r"^[가-힣]{2,10}$")   # 새로 넣을 수 있는 단어
_GROUP_WORD = re.compile(r"^[가-힣]{1,10}$")    # 묶음 안의 단어 (컵·칼처럼 한 글자도 원본 단어로는 찾게)
_lock = threading.Lock()
_cache = {"version": None, "lex": None}

SCHEMA = """
CREATE TABLE IF NOT EXISTS word_groups (
    id INTEGER PRIMARY KEY,
    words TEXT NOT NULL,           -- 쉼표로 구분한 단어 묶음
    source TEXT NOT NULL,          -- seed / user / opendict
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS word_block (word TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS word_attr (word TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS dict_syn (            -- 사전 파일의 비슷한말 (명사)
    word TEXT PRIMARY KEY,
    syns TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS word_dict (           -- 우리말샘 표제어인지 (일반명사 판정, 키프리스 확인 전에)
    word TEXT PRIMARY KEY,
    in_dict INTEGER NOT NULL,
    checked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS word_lookup (     -- 우리말샘에서 이미 찾아본 단어 (결과가 없어도 남김)
    word TEXT PRIMARY KEY,
    found TEXT NOT NULL DEFAULT '',
    looked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def ensure(db):
    with db.tx() as c:
        c.executescript(SCHEMA)
        if not c.execute("SELECT 1 FROM meta WHERE k='lexicon_seeded'").fetchone():
            for line in SEED_GROUPS.strip().splitlines():
                words = [w for w in (x.strip() for x in line.split(",")) if _GROUP_WORD.match(w)]
                if len(words) >= 2:
                    c.execute("INSERT INTO word_groups(words, source) VALUES(?, 'seed')", (",".join(words),))
            for w in DEFAULT_BLOCK.replace("\n", ",").split(","):
                if w.strip():
                    c.execute("INSERT OR IGNORE INTO word_block(word) VALUES(?)", (w.strip(),))
            c.execute("INSERT INTO meta(k, v) VALUES('lexicon_seeded', '1')")
            _bump(c)
        if not c.execute("SELECT 1 FROM meta WHERE k='block_v2'").fetchone():
            # 효능·인증·원산지·과장 표현을 금지 단어에 더한다 (이미 쓰던 db에도)
            for w in CLAIM_BLOCK.replace("\n", ",").split(","):
                if w.strip():
                    c.execute("INSERT OR IGNORE INTO word_block(word) VALUES(?)", (w.strip(),))
            c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('block_v2', '1')")
            _bump(c)
        if not c.execute("SELECT 1 FROM meta WHERE k='attr_seeded'").fetchone():
            for w in ATTR_SEED.replace("\n", ",").split(","):
                if w.strip():
                    c.execute("INSERT OR IGNORE INTO word_attr(word) VALUES(?)", (w.strip(),))
            c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('attr_seeded', '1')")
            _bump(c)


def _bump(c):
    c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('lexicon_version', ?)", (str(time.time()),))


class Lexicon:
    def __init__(self, groups, blocked, marks=None, attrs=(), dict_syn=None):
        self.blocked = {w.lower() for w in blocked}
        self.attrs = {w for w in attrs if w}
        self.dsyn = dict_syn or {}   # 사전 파일 비슷한말 (상품명에 실제로 쓰이는 말만 남긴 것)
        # 키프리스에서 상표로 확인된 단어 {단어: 등록/출원} — 단어 전체가 같을 때만 (붙여 쓴 '수납'+'함' 등은 따로 확인)
        self.marks = {w.lower(): v for w, v in (marks or {}).items()}
        self.syn = {}
        for g in groups:
            ws = [w for w in g if w and w.lower() not in self.blocked and not self.mark_of(w)]
            for w in ws:
                self.syn.setdefault(w, set()).update(x for x in ws if x != w)
        self.words = set(self.syn)

    def mark_of(self, w):
        """상표로 확인된 단어면 '등록'/'출원', 아니면 None. '수리용'은 '수리'로도 본다."""
        lw = str(w or "").lower()
        v = self.marks.get(lw)
        if not v:
            for suf in SUFFIXES:
                if lw.endswith(suf) and len(lw) > len(suf) + 1:
                    v = self.marks.get(lw[: -len(suf)])
                    if v:
                        break
        return {"registered": "등록", "pending": "출원"}.get(v) if v else None

    def ok_new_word(self, w):
        """새로 넣어도 되는 단어인가: 한글 2~10자, 금지 단어 아님 (금지 단어가 들어 있어도 안 됨), 상표 아님."""
        if not _HANGUL_WORD.match(w):
            return False
        lw = w.lower()
        return not any(b and b in lw for b in self.blocked) and not self.mark_of(w)

    def synonyms(self, token):
        """단어의 유의어. '수리용'이면 '수리'의 유의어에 '용'을 붙여 '보수용·수선용'."""
        out = list(self.syn.get(token, ())) + list(self.dsyn.get(token, ()))
        for suf in SUFFIXES:
            if token.endswith(suf) and len(token) > len(suf) + 1:
                base = token[: -len(suf)]
                out += [s + suf for s in list(self.syn.get(base, ())) + list(self.dsyn.get(base, ()))]
        return [w for w in dict.fromkeys(out) if self.ok_new_word(w)]


def blocked_in(name, lex):
    """원본 상품명에 들어 있는 금지 단어 (경고용). 영문은 단어 전체가 같을 때만."""
    if not lex:
        return []
    low = str(name or "").lower()
    words = {t.lower() for t in low.split()}
    return [b for b in sorted(lex.blocked) if (b in words if b.isascii() else (len(b) >= 2 and b in low))]


def marks_in(name, lex):
    """상품명에 들어 있는 상표 단어 [(단어, 등록/출원)]. 띄어 쓴 '효도 의자'도 '효도의자'로 본다."""
    if not lex or not lex.marks:
        return []
    toks = str(name or "").split()
    out = []
    for i, t in enumerate(toks):
        for w in (t, t + toks[i + 1] if i + 1 < len(toks) else None):
            m = w and lex.mark_of(w)
            if m:
                out.append((w if w == t else f"{t} {toks[i + 1]}", m))
    return list(dict.fromkeys(out))


def attrs_in(word, lex=None):
    """단어에 들어 있는 속성 단어들 ([] 이면 속성 아님). '원목책상' → ['원목'], '코너형' → ['코너형']."""
    w = str(word or "")
    attrs = lex.attrs if lex else set()
    found = [a for a in attrs if len(a) >= 2 and a in w] + [a for a in attrs if len(a) == 1 and a == w]
    if not found and len(w) >= 3 and w.endswith(ATTR_ENDINGS):
        found = [w]
    return sorted(set(found), key=len, reverse=True)


def is_attr(word, lex=None):
    """단어 자체가 속성인가 (속성이 들어간 '방수테이프' 같은 상품 이름은 아님)."""
    w = str(word or "")
    return w in (lex.attrs if lex else ()) or (len(w) >= 3 and w.endswith(ATTR_ENDINGS))


def category_words(category):
    """네이버 카테고리 이름에서 쓸 만한 일반명사. 가장 아래 단계만 (위 단계는 너무 넓어 상품과 안 맞음)."""
    parts = [p.strip() for p in str(category or "").split(">") if p.strip()][-1:]
    out = []
    for p in parts:
        for w in p.split("/"):
            w = re.sub(r"^기타", "", w.strip())
            if _HANGUL_WORD.match(w) and w not in ("기타", "일반", "용품", "잡화", "기타용품"):
                out.append(w)
    return list(dict.fromkeys(out))


def get(db):
    """사전을 메모리에 두고, 화면에서 고치면(버전이 바뀌면) 다시 읽는다."""
    row = db.one("SELECT v FROM meta WHERE k='lexicon_version'")
    ver = row["v"] if row else None
    with _lock:
        if _cache["lex"] is None or _cache["version"] != ver:
            groups = [r["words"].split(",") for r in db.q("SELECT words FROM word_groups WHERE enabled=1")]
            blocked = [r["word"] for r in db.q("SELECT word FROM word_block")]
            attrs = [r["word"] for r in db.q("SELECT word FROM word_attr")]
            from . import config
            verdicts = ("registered", "pending") if config.load().get("kipris_block_pending", True) else ("registered",)
            marks = {r["word"]: r["verdict"] for r in db.q(
                f"""SELECT word, verdict FROM trademark_check WHERE allowed=0 AND verdict IN ({','.join('?' * len(verdicts))})
                AND word NOT IN (SELECT word FROM word_dict WHERE in_dict=1)""", verdicts)}
            # 사전 단어(유의어 묶음·속성 단어·우리말샘 표제어)와 두 글자 이하는 일반명사로 보고 상표로 막지 않는다
            generic = {w for g in groups for w in g} | set(attrs)
            marks = {w: v for w, v in marks.items() if len(w) >= 3 and w not in generic}
            _cache.update(lex=Lexicon(groups, blocked, marks, attrs, _dict_syn(db, groups)), version=ver)
        return _cache["lex"]


def _dict_syn(db, groups):
    """사전 파일의 비슷한말 중, 원본 상품명·네이버 키워드·유의어 묶음에 실제로 나오는 말끼리만 쓴다
    (사전에는 옛말·전문어 같은 비슷한말이 많아서 상품명에 어색한 말이 들어가지 않게)."""
    rows = db.q("SELECT word, syns FROM dict_syn")
    if not rows:
        return {}
    corpus = {w for g in groups for w in g}
    for r in db.q("SELECT name FROM sources"):
        for t in r["name"].split():
            corpus.add(t)
            for suf in SUFFIXES:
                if t.endswith(suf) and len(t) > len(suf) + 1:
                    corpus.add(t[: -len(suf)])
    corpus |= {r["word"] for r in db.q("SELECT DISTINCT word FROM source_kw")} if _has_table(db, "source_kw") else set()
    out = {}
    for r in rows:
        if r["word"] not in corpus:
            continue
        syns = [x for x in r["syns"].split(",") if x in corpus and x != r["word"]]
        if syns:
            out[r["word"]] = syns
    return out


def _has_table(db, name):
    return bool(db.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def is_dict_word(word, dict_words):
    """사전 표제어인가. '수리용'처럼 용·형·식이 붙은 말은 '수리'가 있으면 사전 단어로 본다."""
    if word in dict_words:
        return True
    return any(word.endswith(suf) and len(word) > len(suf) + 1 and word[: -len(suf)] in dict_words for suf in SUFFIXES)


# ───────────────────────── 사전 파일 넣기 (우리말샘·표준국어대사전 '사전 내려받기' 파일)

_REL_TYPES = ("비슷", "동의", "유의")


def _clean_word(w):
    w = re.sub(r"[^가-힣]", "", str(w or ""))
    return w if 1 <= len(w) <= 10 else ""


def _entry_from_json(item):
    """사전 파일 JSON 항목 하나 → (단어, 명사인가, 비슷한말들, 단어 단위). 두 사전의 모양을 다 받는다."""
    info = item.get("wordinfo") or item.get("word_info") or {}
    word = info.get("word") or item.get("word") or ""
    unit = info.get("word_unit") or item.get("word_unit") or ""
    pos, rels = [], []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("pos"), str):
                pos.append(o["pos"])
            t = str(o.get("type") or o.get("relation_type") or "")
            if o.get("word") and any(k in t for k in _REL_TYPES) and o is not info:
                rels.append(o["word"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(item)
    return word, any("명사" in p for p in pos), rels, unit


def _tag(el):
    return el.tag.split("}")[-1].lower() if isinstance(el.tag, str) else ""


def _entry_from_xml(el):
    """한 항목 → (표제어, 명사인가, 비슷한말들, 단어 단위). 태그 이름이 조금 달라도(wordinfo/word_info,
    이름공간, 대소문자) 읽는다: 표제어 = '...info' 안이나 항목 바로 아래의 word, 품사 = pos, 비슷한말 = type이 비슷/동의인 묶음의 word."""
    parent = {c: p for p in el.iter() for c in p}
    word, unit, pos, rels = "", "", [], []
    for x in el.iter():
        t = _tag(x)
        if t == "word" and not word:
            pt = _tag(parent.get(x, el))
            if x in list(el) or (pt.endswith("info") and "relation" not in pt and "lexical" not in pt):
                word = (x.text or "").strip()
        elif t in ("word_unit", "unit") and not unit:
            unit = (x.text or "").strip()
        elif t == "pos" or t == "pos_name":
            pos.append((x.text or "").strip())
        if x is not el:
            kids = {_tag(c): (c.text or "").strip() for c in x}
            typ = kids.get("type") or kids.get("relation_type") or ""
            if kids.get("word") and any(k in typ for k in _REL_TYPES) and not _tag(x).endswith("wordinfo") \
                    and _tag(x) not in ("word_info",):
                rels.append(kids["word"])
    return word, any("명사" in p for p in pos), rels, unit


def _leaf_paths(el, limit=14):
    """진단용: 항목 안의 '경로=값' 몇 개."""
    out = []

    def walk(x, path):
        kids = list(x)
        if not kids:
            v = (x.text or "").strip()
            if v:
                out.append(f"{path}={v[:20]}")
        for c in kids:
            if len(out) >= limit:
                return
            walk(c, f"{path}/{_tag(c)}" if path else _tag(c))
    walk(el, "")
    return out


_diag = {}


def _iter_entries(fh, name):
    import xml.etree.ElementTree as ET
    low = name.lower()
    if low.endswith(".json"):
        data = json.load(fh)
        items = []

        def find(o):
            if isinstance(o, dict):
                if "wordinfo" in o or "word_info" in o:
                    items.append(o)
                    return
                for v in o.values():
                    find(v)
            elif isinstance(o, list):
                for v in o:
                    find(v)
        find(data)
        _diag.setdefault("records", 0)
        _diag["records"] += len(items)
        for it in items:
            yield _entry_from_json(it)
    elif low.endswith(".xml"):
        # 항목 = 맨 바깥 요소 바로 아래에서 하위 요소를 가진 요소 (item 등, 이름이 달라도 됨)
        root, depth = None, 0
        for ev, el in ET.iterparse(fh, events=("start", "end")):
            if ev == "start":
                if root is None:
                    root = el
                depth += 1
                continue
            depth -= 1
            if depth == 1 and len(el):
                _diag["records"] = _diag.get("records", 0) + 1
                _diag.setdefault("tag", _tag(el))
                if "sample" not in _diag:
                    _diag["sample"] = _leaf_paths(el)
                yield _entry_from_xml(el)
                root.clear()  # 큰 파일(수십만 항목)도 메모리가 늘지 않게
            elif depth == 0:
                _diag.setdefault("root", _tag(el))


def dict_dir():
    from . import config
    d = os.path.join(config.DATA_DIR, "사전")
    os.makedirs(d, exist_ok=True)
    return d


def dict_folder_new(db):
    """사전 폴더에 있는데 아직 안 읽은(또는 바뀐) 파일들."""
    done = json.loads((db.one("SELECT v FROM meta WHERE k='dict_folder_done'") or {"v": "{}"})["v"])
    out = []
    for n in sorted(os.listdir(dict_dir())):
        if not n.lower().endswith((".zip", ".xml", ".json")):
            continue
        p = os.path.join(dict_dir(), n)
        sig = f"{os.path.getsize(p)}:{int(os.path.getmtime(p))}"
        if done.get(n) != sig:
            out.append((n, p, sig))
    return out


def import_dict_folder(db, progress=None, should_stop=None):
    """data/사전 폴더의 사전 파일(zip 그대로 둬도 됨)을 읽는다. 다 읽은 파일은 기억해 다시 읽지 않는다."""
    files = dict_folder_new(db)
    if not files:
        raise RuntimeError(f"읽을 새 사전 파일이 없습니다. 받은 zip을 압축 풀지 말고 이 폴더에 넣으세요: {dict_dir()}")
    total = {"files": 0, "entries": 0, "nouns": 0, "syn_words": 0, "names": []}
    for name, path, sig in files:
        if should_stop and should_stop():
            break
        with open(path, "rb") as fh:
            st = import_dictionary(db, fh, name, progress=progress, should_stop=should_stop)
        done = json.loads((db.one("SELECT v FROM meta WHERE k='dict_folder_done'") or {"v": "{}"})["v"])
        done[name] = sig
        db.x("INSERT OR REPLACE INTO meta(k, v) VALUES('dict_folder_done', ?)", (json.dumps(done, ensure_ascii=False),))
        for k in ("files", "entries"):
            total[k] += st[k]
        total["nouns"], total["syn_words"] = st["nouns"], st["syn_words"]
        total["names"].append(name)
    total["nouns"] = db.one("SELECT COUNT(*) AS n FROM word_dict WHERE in_dict=1")["n"]
    total["syn_words"] = db.one("SELECT COUNT(*) AS n FROM dict_syn")["n"]
    return total


def import_dictionary(db, fh, filename, progress=None, should_stop=None):
    """사전 파일(zip 안의 xml/json 여러 개, 또는 xml/json 하나)을 넣는다.
    명사 표제어 → word_dict (일반명사 판정: 키프리스 확인에서 빼는 데 씀)
    명사의 비슷한말·동의어 → dict_syn (재조합 유의어, 상품명에 실제로 쓰이는 말만)"""
    import zipfile
    files = []
    if filename.lower().endswith(".zip"):
        z = zipfile.ZipFile(fh)
        files = [(n, (lambda n=n: z.open(n))) for n in z.namelist() if n.lower().endswith((".xml", ".json"))]
    else:
        files = [(filename, lambda: fh)]
    if not files:
        raise RuntimeError("zip 안에 xml이나 json 사전 파일이 없습니다.")
    nouns, syn = set(), {}
    _diag.clear()
    stats = {"files": 0, "entries": 0, "nouns": 0, "syn_words": 0}
    for i, (name, opener) in enumerate(files, 1):
        if should_stop and should_stop():
            break
        with opener() as f:
            for word, is_noun, rels, unit in _iter_entries(f, name):
                stats["entries"] += 1
                if unit and unit not in ("단어", "어휘"):   # 표준국어대사전 '단어', 우리말샘 '어휘' (구·관용구·속담은 뺌)
                    continue
                w = _clean_word(word)
                if not w or not is_noun:
                    continue
                nouns.add(w)
                rs = [r for r in (_clean_word(x) for x in rels) if _HANGUL_WORD.match(r) and r != w]
                if rs and _HANGUL_WORD.match(w):
                    syn.setdefault(w, set()).update(rs)
                    for r in rs:
                        syn.setdefault(r, set()).add(w)
        stats["files"] += 1
        if progress:
            progress(i, len(files), f"{name} · 명사 {len(nouns):,}개")
    if not nouns:
        d = _diag
        raise RuntimeError(
            f"명사 표제어를 찾지 못했습니다(버전 {__import__('uploader').VERSION}). 이 내용을 그대로 보내 주세요 → "
            f"파일 {len(files)}개({', '.join(n for n, _ in files[:3])}) · 항목 {d.get('records', 0):,}개"
            f"(태그 '{d.get('tag', '?')}', 맨 바깥 '{d.get('root', '?')}') · 읽은 항목 {stats['entries']:,} · "
            f"첫 항목: {' | '.join(d.get('sample') or ['없음'])}")
    now = time.time()
    with db.tx() as c:
        c.executemany("INSERT OR REPLACE INTO word_dict(word, in_dict, checked_at) VALUES(?,1,?)", [(w, now) for w in nouns])
        c.executemany("""INSERT INTO dict_syn(word, syns) VALUES(?,?)
            ON CONFLICT(word) DO UPDATE SET syns=excluded.syns""",
                      [(w, ",".join(sorted(v))[:2000]) for w, v in syn.items()])
        c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('dict_file', ?)", (json.dumps(
            {"name": filename, "at": now, "nouns": len(nouns), "syn": len(syn)}, ensure_ascii=False),))
        _bump(c)
    stats.update(nouns=len(nouns), syn_words=len(syn))
    return stats


# ───────────────────────── 반복 검사

def repeated_word(tokens, lex=None, max_repeat=2):
    """같은 단어가 max_repeat번보다 많이 나오면 그 단어를, 아니면 None.
    단어 = 상품명의 각 단어 + 그 안에 든 사전 단어·카테고리 단어(2자 이상).
    '방수테이프 테이프 접착테이프'면 '테이프'가 3번."""
    toks = [t.lower() for t in tokens]
    cands = set(toks)
    known = lex.words if lex else set()
    for t in toks:
        for i in range(len(t)):
            for j in range(i + 2, min(len(t), i + 8) + 1):
                sub = t[i:j]
                if sub in known:
                    cands.add(sub)
        for suf in SUFFIXES:
            if t.endswith(suf) and len(t) > len(suf) + 1:
                cands.add(t[: -len(suf)])
    for w in cands:
        if len(w) < 2:
            continue
        if sum(1 for t in toks if w in t) > max_repeat:
            return w
    return None


# ───────────────────────── 화면용: 사전 내용 읽기/저장

def export_text(db):
    groups = db.q("SELECT words, source FROM word_groups WHERE enabled=1 ORDER BY source, id")
    return {
        "groups": "\n".join(g["words"] for g in groups if g["source"] != "opendict"),
        "opendict": "\n".join(g["words"] for g in groups if g["source"] == "opendict"),
        "blocked": ", ".join(r["word"] for r in db.q("SELECT word FROM word_block ORDER BY word")),
        "attrs": ", ".join(r["word"] for r in db.q("SELECT word FROM word_attr ORDER BY word")),
        "stats": db.one("""SELECT (SELECT COUNT(*) FROM word_groups WHERE enabled=1) AS groups,
            (SELECT COUNT(*) FROM word_groups WHERE enabled=1 AND source='opendict') AS opendict,
            (SELECT COUNT(*) FROM word_block) AS blocked, (SELECT COUNT(*) FROM word_lookup) AS looked,
            (SELECT COUNT(*) FROM word_attr) AS attrs, (SELECT COUNT(*) FROM word_dict WHERE in_dict=1) AS dict_words,
            (SELECT COUNT(*) FROM dict_syn) AS dict_syn"""),
        "dict_file": json.loads((db.one("SELECT v FROM meta WHERE k='dict_file'") or {"v": "null"})["v"]),
        "dict_dir": dict_dir(),
        "dict_new": [n for n, _, _ in dict_folder_new(db)],
    }


def save_text(db, groups_text, blocked_text, opendict_text=None, attrs_text=None):
    """화면의 글자를 그대로 사전으로 저장 (기본 묶음도 여기서 고친 대로)."""
    lines = [l for l in (groups_text or "").splitlines() if l.strip()]
    with db.tx() as c:
        c.execute("DELETE FROM word_groups WHERE source IN ('seed','user')")
        for line in lines:
            ws = [w.strip() for w in line.replace("、", ",").split(",") if w.strip()]
            if len(ws) >= 2:
                c.execute("INSERT INTO word_groups(words, source) VALUES(?, 'user')", (",".join(dict.fromkeys(ws)),))
        if opendict_text is not None:
            c.execute("DELETE FROM word_groups WHERE source='opendict'")
            for line in opendict_text.splitlines():
                ws = [w.strip() for w in line.split(",") if w.strip()]
                if len(ws) >= 2:
                    c.execute("INSERT INTO word_groups(words, source) VALUES(?, 'opendict')", (",".join(ws),))
        c.execute("DELETE FROM word_block")
        for w in (blocked_text or "").replace("\n", ",").split(","):
            if w.strip():
                c.execute("INSERT OR IGNORE INTO word_block(word) VALUES(?)", (w.strip(),))
        if attrs_text is not None:
            c.execute("DELETE FROM word_attr")
            for w in attrs_text.replace("\n", ",").split(","):
                if w.strip():
                    c.execute("INSERT OR IGNORE INTO word_attr(word) VALUES(?)", (w.strip(),))
        _bump(c)


# ───────────────────────── 우리말샘에서 유의어 받기 (선택, 무료 키 필요)

OPENDICT = "https://opendict.korean.go.kr/api"


def _relation_words(obj):
    """응답 JSON 어디에 있든 '비슷한말·동의어' 관계 단어를 모은다 (응답 모양이 바뀌어도 견디게)."""
    out = []
    if isinstance(obj, dict):
        t = str(obj.get("type") or obj.get("relation_type") or "")
        w = obj.get("word") or obj.get("relation_word")
        if w and any(k in t for k in ("비슷", "동의", "유의")):
            out.append(str(w))
        for v in obj.values():
            out += _relation_words(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _relation_words(v)
    return out


def lookup_opendict(word, key, session):
    """단어 하나의 비슷한말 (명사만). 우리말샘 표기의 '-', '^' 같은 기호는 뺀다."""
    r = session.get(f"{OPENDICT}/search", params={
        "key": key, "q": word, "req_type": "json", "part": "word", "method": "exact",
        "advanced": "y", "pos": 1, "num": 10}, timeout=15)
    r.raise_for_status()
    data = r.json()
    codes = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("target_code"):
                codes.append(o["target_code"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    found = _relation_words(data)
    for code in codes[:3]:
        v = session.get(f"{OPENDICT}/view", params={"key": key, "method": "target_code", "q": code,
                                                    "req_type": "json"}, timeout=15)
        if v.status_code == 200:
            found += _relation_words(v.json())
    clean = []
    for w in found:
        w = re.sub(r"[\-\^\s·]", "", w)
        if _HANGUL_WORD.match(w) and w != word:
            clean.append(w)
    return list(dict.fromkeys(clean))[:8]


def in_dictionary(word, key, session):
    """우리말샘에 이 단어가 표제어로 있는가 (붙여 쓴 조어 '효도의자'는 보통 없음)."""
    r = session.get(f"{OPENDICT}/search", params={
        "key": key, "q": word, "req_type": "json", "part": "word", "method": "exact", "advanced": "y", "num": 10},
        timeout=15)
    r.raise_for_status()
    data = r.json()
    words = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("word"), str):
                words.append(o["word"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return any(re.sub(r"[\-\^\s·]", "", w) == word for w in words)


def fetch_opendict(db, cfg, progress=None, should_stop=None):
    """원본 상품명에 자주 나오는 단어부터, 아직 안 찾아본 것을 우리말샘에서 찾아 유의어 묶음으로 저장한다."""
    import collections
    import requests
    key = (cfg.get("opendict_key") or "").strip()
    if not key:
        raise RuntimeError("설정 → 단어 사전에서 우리말샘 오픈 API 키를 먼저 넣어 주세요 (opendict.korean.go.kr, 무료).")
    limit = int(cfg.get("opendict_daily_limit") or 1000)
    looked = {r["word"] for r in db.q("SELECT word FROM word_lookup")}
    counter = collections.Counter()
    for r in db.q("SELECT name FROM sources WHERE valid=1"):
        for t in set(r["name"].split()):
            base = t
            for suf in SUFFIXES:
                if t.endswith(suf) and len(t) > len(suf) + 1:
                    base = t[: -len(suf)]
            if _HANGUL_WORD.match(base) and base not in looked:
                counter[base] += 1
    todo = [w for w, n in counter.most_common() if n >= 2][:limit]
    s = requests.Session()
    stats = {"looked": 0, "found": 0, "errors": 0}
    for i, w in enumerate(todo, 1):
        if should_stop and should_stop():
            break
        try:
            syns = lookup_opendict(w, key, s)
        except Exception as e:  # noqa: BLE001
            stats["errors"] += 1
            if stats["errors"] >= 5 and not stats["looked"]:
                raise RuntimeError(f"우리말샘에 연결하지 못했습니다: {e}")
            continue
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO word_lookup(word, found, looked_at) VALUES(?,?,?)",
                      (w, ",".join(syns), time.time()))
            if syns:
                c.execute("INSERT INTO word_groups(words, source) VALUES(?, 'opendict')", (",".join([w] + syns),))
                stats["found"] += 1
                _bump(c)
        stats["looked"] += 1
        if progress:
            progress(i, len(todo), f"{w} → {', '.join(syns) or '없음'}")
        time.sleep(0.1)
    return stats
