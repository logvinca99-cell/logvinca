"""맥락 키워드 상품명 조립 (기준 구현 '상품명조립_기준구현.py'를 그대로 옮김, 규칙 변경 금지).

방식: [원본 앞 4단어] + [AI 맥락 키워드 최대 6개] + [원본 나머지 단어 무작위 3~6개], 최대 50자(공백 포함).
AI는 원본마다 '맥락 키워드'(쓰는 장소·사람·용도·상황) 목록만 만든다. 조립·길이·금지어·중복 처리는 전부 이 코드가 한다.
설정으로 숫자를 바꿀 수 있게 상수를 인자로 받는 것 말고는 기준 구현과 같다 (기본값 = 기준 구현 값).
"""
import random
import re

MAX_CHARS = 50        # 공백 포함 글자 수
HEAD_N = 4            # 원본 앞 단어 고정 개수
AI_PER_NAME = 6       # 이름 하나에 넣는 AI 키워드 최대 개수
AI_MIN = 3            # 길이가 모자라면 AI 키워드를 이 개수까지 줄여서 원본 단어 자리를 확보
TAIL_MIN, TAIL_MAX = 3, 6
MAX_TRIES = 30        # 복사본 이름 하나당 재시도 횟수
MAX_OVERLAP = 0.85    # 같은 원본의 복사본끼리 단어가 이 비율 이상 겹치면 버림

# 원본에서 빼는 의미 없는 단어
STOP_ORIGIN = {'기본', '표준', '색상', '목적', '장', '옆', '항목', '제작', '헬드'}
# AI 키워드로 받지 않는 막연한/검증 불가/원산지 표현 (금지어 목록과 별도로 코드에서 한 번 더 거름)
BAD_AI = {'인증', '특허', '최고', '고급', '프리미엄', '효율', '편안함', '편안', '건강', '내구성',
          '정품', '신상', '할인', '최저가', '무료배송', '국산', '중국산', '수입', '명품'}
HANGUL_WORD = re.compile(r'^[가-힣]{2,6}$')   # AI 키워드는 한글 2~6글자만 ('pc방' 같은 것 차단)


def nchars(s: str) -> int:
    return len(s)


def _is_compound(w, others):
    """w 가 다른 단어 2개 이상을 그대로 붙인 말인지 (린넨커튼 = 린넨+커튼)"""
    for i in range(1, len(w)):
        a, b = w[:i], w[i:]
        if a in others and (b in others or _is_compound(b, others)):
            return True
    return False


def clean_origin(name: str, forbidden: set, head_n=HEAD_N):
    """원본 상품명 -> (원본 토큰 목록, 앞 고정 단어, 뒤에 쓸 후보 단어)"""
    tokens = []
    for w in name.split():
        if w not in tokens and w not in forbidden:   # 금지어는 원본에서도 먼저 제거
            tokens.append(w)
    head = tokens[:head_n]
    rest = tokens[head_n:]
    pool = []
    for w in rest:
        others = [o for o in tokens if o != w]
        if _is_compound(w, others):                              # 린넨커튼 -> 버림 (린넨, 커튼 이미 있음)
            continue
        if any(w in h for h in head):                            # 조절 ⊂ 높이조절 -> 버림
            continue
        if any(w.endswith(o) for o in others):                   # 가리개커튼 -> 버림 (짧은 핵심어 커튼 유지)
            continue
        if any(w in (o + '용', o + '형') for o in others):         # 캠핑용 -> 버림 (캠핑 유지)
            continue
        if any(o != w and o.startswith(w) and len(o) - len(w) >= 2 and o not in head for o in rest):
            continue                                             # 포장 -> 버림 (포장마차 유지)
        if w in STOP_ORIGIN:
            continue
        pool.append(w)
    return name.split(), head, pool


def filter_ai_words(ai_words, origin_tokens, head, forbidden):
    """AI 키워드 거르기. 통과한 순서를 유지한다."""
    ok = []
    for w in ai_words:
        w = (w or '').strip().replace(' ', '')
        if not HANGUL_WORD.match(w):
            continue
        if w in origin_tokens or w in forbidden or w in BAD_AI or w in ok:
            continue
        if any(w in h for h in head):
            continue
        ok.append(w)
    return ok


def assemble(head, ai_pick, pool, rng, max_chars=MAX_CHARS, ai_min=AI_MIN, tail_min=TAIL_MIN, tail_max=TAIL_MAX,
             head_n=HEAD_N):
    """한 개 이름 조립. pool 은 rng 로 섞어서 앞에서부터 채운다."""
    pool = list(pool)
    rng.shuffle(pool)
    n_ai = len(ai_pick)
    while True:
        base = head + ai_pick[:n_ai]
        tail = []
        for w in pool:
            if len(tail) >= tail_max:
                break
            if nchars(' '.join(base + tail + [w])) <= max_chars:
                tail.append(w)
        if len(tail) >= tail_min or n_ai <= ai_min or len(tail) == len(pool):
            break
        n_ai -= 1
    words = base + tail
    while nchars(' '.join(words)) > max_chars and len(words) > head_n:   # 안전장치
        words.pop()
    return ' '.join(words), ai_pick[:n_ai]


def overlap(a: str, b: str) -> float:
    A, B = set(a.split()), set(b.split())
    return len(A & B) / max(len(A), len(B))


def make_names(origin_name, ai_words, forbidden, copies=1, seed=0, reject=None, opts=None):
    """
    원본 하나에 대해 복사본 이름 copies 개를 만든다. (현재 운영: copies=1, 원본당 1개 스토어)
    - ai_words: 그 원본에 저장된 AI 키워드 전체 (원본당 1번만 AI 호출해서 저장해 둔 것)
    - reject(name) -> True 이면 그 이름을 버리고 다시 만든다.
      (33개 스토어 전체 중복, 네이버에 이미 있는 이름, 85% 이상 겹침 검사 등 앱의 기존 검사를 여기에 연결)
    - 반환: [{'name', 'bytes', 'ai_used'} 또는 None(=이름 변경 필요)] 길이 copies
    """
    o = {"max_chars": MAX_CHARS, "head_n": HEAD_N, "ai_per_name": AI_PER_NAME, "ai_min": AI_MIN,
         "tail_min": TAIL_MIN, "tail_max": TAIL_MAX, **(opts or {})}   # 설정값 (기본 = 기준 구현 값)
    origin_tokens, head, pool = clean_origin(origin_name, forbidden, o["head_n"])
    ai_ok = filter_ai_words(ai_words, origin_tokens, head, forbidden)
    made, results = set(), []
    used_count = {}   # 이 원본의 앞 복사본들이 쓴 AI 키워드 횟수
    for k in range(copies):
        got = None
        for attempt in range(MAX_TRIES):
            if ai_ok:
                # 앞 복사본에서 덜 쓴 키워드부터 고른다(같은 횟수면 원래 순서).
                # 재시도 때마다 시작 위치를 한 칸씩 밀어서 조합을 바꾼다.
                start = attempt % len(ai_ok)
                rot = ai_ok[start:] + ai_ok[:start]
                ai_pick = sorted(rot, key=lambda w: used_count.get(w, 0))[:o["ai_per_name"]]
            else:
                ai_pick = []
            rng = random.Random(seed * 1000 + k * 100 + attempt)
            name, used = assemble(head, ai_pick, pool, rng, o["max_chars"], o["ai_min"], o["tail_min"], o["tail_max"],
                                  o["head_n"])
            if name == origin_name.strip() or set(name.split()) == set(origin_tokens):
                continue                      # 원본과 같은 이름 금지
            if name in made or any(overlap(name, m) >= MAX_OVERLAP for m in made) or (reject and reject(name)):
                continue
            got = {'name': name, 'chars': nchars(name), 'ai_used': used}
            made.add(name)
            for w in used:
                used_count[w] = used_count.get(w, 0) + 1
            break
        results.append(got)
    return results


# ───────────────────────── v2: keep · core · ctx 조립 (AI가 주는 세 묶음)
# [원본 앞 4단어(숫자·수량·연식만 있는 단어는 뒤로)] + [keep] + [core 전부] + [ctx] + [남은 원본 단어] + [숫자·수량·연식]
# 넣는 순서(자리가 모자라면 뒤의 것부터 빠짐): keep → core(확신 1 → 확신 2) → ctx 2개 → 남은 원본 단어 → ctx 2개 더 → 숫자·수량·연식.
# 무작위 없이 정해진 순서라 같은 입력이면 늘 같은 이름. A(1번째 복사본)·B(2번째)는 core·ctx·원본 단어 고르는 위치만 다르다.

# 숫자만, 또는 숫자 + 수량·연식 표시만 있는 단어 (1+1, 2024, 2024형, 10개, 3P, 2세트, 5개입, 2025년식 …). 크기(30cm)는 사양이라 그대로 둔다.
NUMERIC = re.compile(r'^[\d\s+\-x×*/.,~()]+(개|개입|매|입|p|P|ea|EA|세트|set|SET|팩|박스|box|BOX|롤|켤레|족|쌍|년|년형|년식|연식|형|종)?$')
AI_WORD = re.compile(r'^[가-힣A-Za-z0-9]{2,12}$')   # core·ctx 한 단어 (띄어쓰기 없이, 너무 긴 말은 50자를 잡아먹어 뺌)
# core(다른 이름)는 받은 것을 50자 안에서 전부 넣고, 맥락(ctx)은 그다음 남는 자리에 넣는다
CTX_FIRST, CTX_MORE = 2, 2


def is_numeric(w):
    return bool(NUMERIC.match(w))


def split_origin(name, forbidden, head_n=HEAD_N):
    """원본 → (원본 토큰, 앞 단어, 남은 원본 단어(정리), 숫자·수량·연식 단어)."""
    toks = []
    for w in str(name or "").split():
        if w not in toks and w not in forbidden:
            toks.append(w)
    nums = [w for w in toks if is_numeric(w)]
    words = [w for w in toks if not is_numeric(w)]
    _, head, pool = clean_origin(" ".join(words), forbidden, head_n)
    return toks, head, pool, nums


def filter_words(words, origin_tokens, head, forbidden, bad=lambda w: False, limit=None):
    """core·ctx 거르기: 원본에 이미 있는 단어·앞 단어에 들어 있는 말·금지어·막연한 말·상표(bad) 빼고, 순서 유지."""
    ok = []
    for w in words or []:
        w = str(w or "").strip().replace(" ", "")
        if not AI_WORD.match(w) or w in ok or w in origin_tokens or w in forbidden or w in BAD_AI:
            continue
        if any(w in h for h in head) or bad(w):
            continue
        ok.append(w)
    return ok[:limit] if limit else ok


def _fit(head, picks, max_chars, rep=None):
    """앞 단어 + (넣을 후보 [(묶음, 단어)] 우선순위 순) → 50자 안에 들어가는 것만 고른 뒤, 묶음 순서대로 늘어놓는다.
    rep(단어 목록)이 참이면(같은 단어가 3번 이상 — 예: 커튼·린넨커튼·가리개커튼) 그 단어는 넣지 않는다."""
    order = {"keep": 0, "core": 1, "ctx": 2, "rest": 3, "num": 4}
    chosen = []
    for kind, w in picks:
        if w in head or any(w == x for _, x in chosen):
            continue
        trial = head + [x for _, x in sorted(chosen + [(kind, w)], key=lambda p: order[p[0]])]
        if nchars(" ".join(trial)) > max_chars or (rep and rep(trial)):
            continue
        chosen.append((kind, w))
    ordered = sorted(chosen, key=lambda p: order[p[0]])   # sorted는 같은 묶음 안의 우선순위(넣은 순서)를 지킨다
    return " ".join(head + [x for _, x in ordered]), [x for k, x in ordered if k in ("core", "ctx")]


def make_names_v2(origin_name, kw, forbidden, copies=2, seed=0, reject=None, opts=None, bad=None, rep=None):
    """원본 하나 → 이름 copies개 (1번째 = A, 2번째 = B). kw = {keep:[], core:[], ctx:[]} (AI가 준 그대로).
    못 만든 자리는 None (→ 복사본 화면 '상품명 변경 필요'). reject(name)=True면 그 조합을 버리고 다음 조합."""
    o = {"max_chars": MAX_CHARS, "head_n": HEAD_N, **(opts or {})}
    bad = bad or (lambda w: False)
    toks, head, pool, nums = split_origin(origin_name, forbidden, o["head_n"])
    if rep and rep(head):
        # 원본 앞 단어끼리 이미 같은 단어가 3번 이상이면 반복을 만드는 단어는 앞에서 빼고 다음 원본 단어로 채운다
        words = [w for w in toks if not is_numeric(w)]
        new = []
        for w in words:
            if len(new) >= o["head_n"]:
                break
            if not rep(new + [w]):
                new.append(w)
        pool = [w for w in words if w not in new and (w in pool or w in head)]
        head = new
    if not head:
        return [None] * copies
    keep = [w for w in (kw.get("keep") or []) if w in toks and w not in head and not is_numeric(w)]
    core = filter_words(kw.get("core"), toks, head, forbidden, bad)
    core2 = [w for w in filter_words(kw.get("core2"), toks, head, forbidden, bad) if w not in core]   # 확신 2: 확신 1 뒤, 자리 남을 때만
    ctx = filter_words([w for w in (kw.get("ctx") or []) if w not in core and w not in core2], toks, head, forbidden, bad)
    rest = [w for w in pool if w not in keep]
    orig = " ".join(str(origin_name or "").split())
    made, results = [], []
    for k in range(copies):
        got = None
        for t in range(10):   # 같은 이름·중복이면 고르는 위치를 바꿔 최대 10번
            v = k + t
            c0 = v % len(core) if core else 0
            d0 = v % len(core2) if core2 else 0
            # A·B는 다른 이름의 순서만 다름 (A는 1번째부터, B는 2번째부터). 확신 1을 다 넣고 확신 2
            c_pick = core[c0:] + core[:c0] + core2[d0:] + core2[:d0]
            start = (v * CTX_FIRST) % len(ctx) if ctx else 0
            cx = (ctx[start:] + ctx[:start]) if ctx else []
            r0 = (v * 2) % len(rest) if rest else 0
            rs = rest[r0:] + rest[:r0]
            picks = ([("keep", w) for w in keep] + [("core", w) for w in c_pick]
                     + [("ctx", w) for w in cx[:CTX_FIRST]] + [("rest", w) for w in rs]
                     + [("ctx", w) for w in cx[CTX_FIRST:CTX_FIRST + CTX_MORE]] + [("num", w) for w in nums])
            name, used = _fit(head, picks, o["max_chars"], rep)
            if rep and rep(name.split()):
                continue   # 앞 단어만으로도 반복이면 (원본 자체 문제) 이 조합은 버림
            if name == orig or set(name.split()) == set(toks):
                continue   # 원본과 같은 이름 금지
            if name in made or (reject and reject(name)):
                continue
            got = {"name": name, "chars": nchars(name), "ai_used": used}
            made.append(name)
            break
        results.append(got)
    return results
