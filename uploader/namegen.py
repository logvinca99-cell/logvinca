"""상품명 만들기.

모든 상품명은 '정규화한 글자'(띄어쓰기·기호를 빼고 소문자)로 비교한다.
db의 names 표가 이 값에 UNIQUE 제약을 걸어서, 33개 스토어 전체에서 같은 이름이 두 번 나오지 않는다.

재조합: 원본 상품명의 단어를 고르고 순서를 바꿔 새 이름을 만든다. 무료·즉시.
AI:     Claude API로 원본 정보를 보고 새 이름을 여러 개 짓는다. 유료.
"""

import json
import random
import re
import threading

_NORM_RE = re.compile(r"[^0-9a-z가-힣]+")


def normalize(name):
    return _NORM_RE.sub("", str(name or "").lower())


def tokens(name):
    seen, out = set(), []
    for t in str(name or "").split():
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def bad_word(w, lex):
    """금지 단어·상표 단어인가 (원본 단어를 재조합에 쓸지 볼 때). check_name과 같은 기준."""
    if not lex:
        return False
    low = w.lower()
    for b in lex.blocked:
        if (b == low) if b.isascii() else (len(b) >= 2 and b in low):
            return True
    return bool(lex.mark_of(w))


def safe_tokens(name, lex):
    """원본 단어 중 금지·상표 단어를 뺀 것 (원본에 '포크레인' 같은 말이 있어도 새 이름은 쓸 수 있게)."""
    return [t for t in tokens(name) if not bad_word(t, lex)]


def overlap(a, b):
    """두 이름의 단어가 겹치는 정도 (0~1, 자카드)."""
    sa, sb = {t.lower() for t in tokens(a)}, {t.lower() for t in tokens(b)}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def clean(name, max_len=100):
    """공백 정리, 너무 길면 단어 단위로 자름."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if len(name) <= max_len:
        return name
    cut = name[:max_len + 1].rsplit(" ", 1)[0]
    return (cut if cut else name[:max_len]).strip()


# ───────────────────────── 재조합

def new_word_detail(original, cfg, lex=None, category="", kw_words=(), tag_words=(), ai_words=()):
    """재조합에 넣을 수 있는 새 단어 [(단어, 바꿀 수 있는 원래 단어, 우선순위, 출처)]. 출처: 묶음 / 사전 / 네이버 / 태그.
    우선순위: 1 = 앞 단어의 유의어·네이버 연관 키워드, 2 = 나머지 단어의 유의어(바꿔 넣기 가능),
              3 = 뜻이 다를 수 있는 사전 비슷한말(같은 카테고리 상품명에 안 쓰이는 말), 4 = 태그
    ai_words [(단어, 대신할 원래 단어 또는 '')]가 있으면 그것만 쓴다: AI가 이 상품을 보고 고른 말이라
    뜻을 모르고 바꾸는 사전 유의어·네이버 키워드(이미 AI에게 보여 줌)는 섞지 않는다."""
    from . import lexicon as lx
    lex = lex or cfg.get("_lex")
    words = safe_tokens(original, lex)
    fixed_n = max(0, int(cfg.get("recombine_fixed_prefix", 3) or 0))
    prefix, tail = words[:fixed_n], words[fixed_n:]
    have = {w.lower() for w in tokens(original)}
    pool = []
    if ai_words:
        for w, t in ai_words:
            if t:   # 원래 단어 대신 넣을 수 있는 말 (앞 고정 단어의 것이면 덧붙이기만)
                pool.append((w, t if t in tail else None, 1, "AI"))
            else:
                pool.append((w, None, 2, "AI"))
    elif lex:
        for w in prefix:   # 앞 단어는 고정이라 바꾸지 않고 덧붙이기만
            pool += [(x, None, 1 if r == 0 else 3, o) for x, o, r in lex.synonyms_src(w, category)]
        pool += [(w, None, 1, "네이버") for w in kw_words]
        if cfg.get("use_category_words", False):
            pool += [(x, None, 2, "카테고리") for x in lx.category_words(category)]
        for w in tail:
            pool += [(x, w, 2 if r == 0 else 3, o) for x, o, r in lex.synonyms_src(w, category)]
        if cfg.get("recombine_use_tags"):
            pool += [(t, None, 4, "태그") for t in tag_words if lex.ok_new_word(t)]
    seen, cand = set(), []
    for w, src, pr, o in sorted(pool, key=lambda x: x[2]):
        if w.lower() in have or w in seen or (lex and not lex.ok_new_word(w)):
            continue
        seen.add(w)
        cand.append((w, src, pr, o))
    return cand


def new_word_candidates(original, cfg, lex=None, category="", core="", kw_words=(), tag_words=(), ai_words=()):
    """재조합에 넣을 수 있는 새 단어 [(단어, 바꿀 수 있는 원래 단어, 우선순위)]. 이 수가 설정보다 적으면 그만큼만 들어간다."""
    return [c[:3] for c in new_word_detail(original, cfg, lex, category, kw_words, tag_words, ai_words)]


def recombine(original, count, taken_norms, siblings, cfg, seed, tag_words=(), lex=None, category="",
              core="", kw_words=(), ai_words=(), use_count=None, avoid=(), neighbors=()):
    """새 이름 count개. 토큰(비용) 없이 만든다.

    1. 원본의 앞 N단어(기본 3)는 그대로 맨 앞에 둔다.
    2. 나머지 단어 중 0~3개를 빼고 순서를 섞는다.
    3. 새 단어를 new_word_detail의 우선순위대로 고른다: 앞 단어의 유의어·네이버 연관 키워드 → 나머지 단어의
       유의어(일정 확률로 원래 단어 자리에 바꿔 넣음, 예: 수리용 → 수선용) → 뜻이 다를 수 있는 사전 비슷한말.
       새 단어는 한글 일반명사만, 금지 단어·상표 단어는 넣지 않는다.
    4. 남는 칸을 최대 글자 수(기본 50자)까지 채운다: 뺐던 원본 단어 → 그래도 남으면 우선순위 높은 새 단어.
    5. 버리는 경우: 같은 단어가 3번 이상 / 33개 스토어의 다른 이름과 같음 /
       같은 원본의 다른 이름과 (앞 N단어 뒤 부분이) 85% 이상 겹치거나 그 첫 두 단어가 같음.
    6. 원본의 금지·상표 단어(예: 포크레인)는 빼고 만든다.
    ai_words: AI가 이 원본에 준 새 단어 (있으면 사전 유의어 대신 이것만 씀).
    use_count {단어: 이 스토어에서 쓴 횟수}: 많이 쓴 단어일수록 덜 뽑는다 (내 상품끼리 같은 단어가 몰리지 않게).
    avoid: 되도록 쓰지 않을 단어 (최신화 때 지난 이름의 새 단어).
    neighbors: 같은 스토어·카테고리 내 다른 상품명들의 단어 집합 — 단어가 너무 많이 겹치면 버린다.
    core는 예전 호출과 맞추려고 남겨 둔 인자 (쓰지 않음).
    """
    from . import lexicon as lx
    lex = lex or cfg.get("_lex")
    words = safe_tokens(original, lex)
    max_len = int(cfg.get("name_max_len") or 50)
    max_overlap = float(cfg.get("recombine_max_overlap") or 0.85)
    max_repeat = int(cfg.get("max_word_repeat") or 2)
    new_min = int(cfg.get("recombine_new_min", 1) or 0)
    new_max = max(new_min, int(cfg.get("recombine_new_max", 2) or 0))
    fill = cfg.get("recombine_fill", True)
    fixed_n = max(0, int(cfg.get("recombine_fixed_prefix", 3) or 0))
    replace_ratio = float(cfg.get("recombine_replace_ratio", 0.4) or 0)

    prefix, tail = words[:fixed_n], words[fixed_n:]
    cand = new_word_candidates(original, cfg, lex, category, "", kw_words, tag_words, ai_words)
    weight = {1: 6, 2: 4, 3: 2, 4: 1}
    use_count = use_count or {}
    avoid = set(avoid or ())

    def wt(c):
        w = weight[c[2]] / (1 + use_count.get(c[0], 0))
        return w * 0.05 if c[0] in avoid else w

    rnd = random.Random(seed)
    out, sibs = [], list(siblings)
    if len(words) < 2 and not cand:
        return out

    def tail_of(name):
        return " ".join(tokens(name)[len(prefix):])

    sib_tails = [tail_of(x) for x in sibs]

    def too_close(name):
        t = tail_of(name)
        if any(overlap(t, x) >= max_overlap or _same_start(t, x) for x in sib_tails if x):
            return True
        if neighbors:
            mine = {x.lower() for x in tokens(name)}
            return any(len(mine & x) / len(mine | x) >= max_overlap for x in neighbors if x)
        return False

    def can_add(cur, w, check_overlap=False):
        if any(w.lower() == x.lower() for x in cur):
            return False
        if len(" ".join(cur + [w])) > max_len:
            return False
        if lx.repeated_word(cur + [w], lex, max_repeat):
            return False
        if check_overlap and any(overlap(" ".join((cur + [w])[len(prefix):]), x) >= max_overlap for x in sib_tails if x):
            return False
        return True

    def pick(n, exclude=()):
        """우선순위 가중치로 새 단어 n개 고르기 (같은 원래 단어의 유의어는 하나만)."""
        left = [c for c in cand if c[0] not in exclude]
        chosen, used_src = [], set()
        while left and len(chosen) < n:
            total = sum(wt(c) for c in left)
            r = rnd.uniform(0, total)
            for i, c in enumerate(left):
                r -= wt(c)
                if r <= 0:
                    break
            c = left.pop(i)
            if c[1] and c[1] in used_src:
                continue
            chosen.append(c)
            if c[1]:
                used_src.add(c[1])
        return chosen

    for _ in range(count * 40):
        if len(out) >= count:
            break
        keep_n = rnd.randint(max(0, len(tail) - 3), len(tail)) if tail else 0
        kept = rnd.sample(tail, keep_n)
        rnd.shuffle(kept)
        k = min(len(cand), rnd.randint(new_min, new_max)) if cand else 0
        news = pick(k)
        replaced = set()
        for w, src, _ in news:
            if src and src in kept and rnd.random() < replace_ratio:
                kept[kept.index(src)] = w          # 원래 단어 자리에 유의어로 바꿔 넣기
                replaced.add(src)
            else:
                kept.insert(rnd.randint(0, len(kept)), w)

        cur = []
        for w in prefix:                            # 앞 N단어는 무조건 그대로
            if not any(w.lower() == x.lower() for x in cur):
                cur.append(w)
        for w in kept:
            if can_add(cur, w):
                cur.append(w)
        new_words = {w for w, _, _ in news}
        if cand and sum(1 for w in cur if w in new_words) < min(new_min, len(cand)):
            continue
        if fill:
            # 남는 칸: 뺐던 원본 단어(바꿔 넣은 원래 단어는 제외) → 그래도 남으면 우선순위 높은 새 단어
            dropped = [w for w in tail if w not in cur and w not in replaced]
            rnd.shuffle(dropped)
            extra = [c[0] for c in sorted(cand, key=lambda c: (c[2], c[0] in avoid, use_count.get(c[0], 0), rnd.random()))
                     if c[0] not in cur]
            for w in dropped + extra:
                if len(" ".join(cur)) >= max_len - 1:
                    break
                if can_add(cur, w, check_overlap=True):
                    cur.append(w)

        name = " ".join(cur)
        n = normalize(name)
        if len(cur) < 2 or not n or n in taken_norms or too_close(name):
            continue
        taken_norms.add(n)
        sibs.append(name)
        sib_tails.append(tail_of(name))
        out.append(name)
    return out


def check_name(name, cfg, lex=None):
    """AI·가져온 이름 검사: 같은 단어 반복과 금지 단어. 문제가 없으면 None, 있으면 이유."""
    from . import lexicon as lx
    toks = tokens(name)
    w = lx.repeated_word(toks, lex, int(cfg.get("max_word_repeat") or 2))
    if w:
        return f"'{w}' 반복"
    if lex:
        low = name.lower()
        words = {t.lower() for t in toks}
        for b in lex.blocked:
            # 영문 금지 단어(st 등)는 단어 전체가 같을 때만, 한글은 단어 안에 들어 있어도
            hit = (b in words) if b.isascii() else (len(b) >= 2 and b in low)
            if hit:
                return f"금지 단어 '{b}'"
        m = lx.marks_in(name, lex)
        if m:
            return f"상표 단어 '{m[0][0]}'({m[0][1]})"
    return None


def _same_start(a, b):
    """앞 두 단어가 같으면 검색에서 거의 같은 이름으로 보인다."""
    ta, tb = [t.lower() for t in tokens(a)[:2]], [t.lower() for t in tokens(b)[:2]]
    return ta == tb


# ───────────────────────── AI (Claude API)

AI_SYSTEM = """당신은 네이버 스마트스토어 상품명을 짓는 전문가입니다.
주어진 원본 상품마다 서로 다른 새 상품명을 요청한 개수만큼 만듭니다.

규칙:
- 실제 상품과 맞는 검색 키워드로만 짓습니다. 상품과 상관없는 단어, 과장(최고, 1위, 특가 등), 브랜드 사칭은 넣지 않습니다.
- 원본 상품명과 그대로 같거나 단어 순서만 바꾼 이름은 피하고, 같은 상품의 이름끼리도 앞부분 단어와 구성이 서로 달라야 합니다.
- 띄어쓰기로 키워드를 구분하고, 특수문자는 쓰지 않습니다. 같은 단어는 한 이름 안에서 2번까지만 씁니다 (다른 단어 안에 들어간 경우도 셉니다).
- 브랜드·상표·다른 회사 제품명, '정품'·'스타일'·'호환' 같은 표현은 넣지 않고 일반명사만 씁니다.
- 한 이름은 {max_len}자를 넘지 않되 되도록 {max_len}자에 가깝게 채웁니다.
{guide}"""

AI_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "names": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "names"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


class AiNamer:
    """여러 상품을 한 번에 보내 상품마다 이름 여러 개를 받는다."""

    def __init__(self, cfg):
        import anthropic
        key = (cfg.get("anthropic_api_key") or "").strip()
        if not key:
            raise RuntimeError("설정 → AI 상품명에서 Anthropic API 키를 먼저 넣어 주세요.")
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=key, max_retries=4)
        self.cfg = cfg
        self.lock = threading.Lock()
        self.usage = {"input": 0, "output": 0, "calls": 0}
        guide = (cfg.get("ai_guide") or "").strip()
        self.system = AI_SYSTEM.format(max_len=int(cfg.get("name_max_len") or 50),
                                       guide=f"\n추가 지침:\n{guide}" if guide else "")

    def name_batch(self, items, per_product):
        """items: [{key, name, category, tags}] → {key: [이름...]}"""
        lines = [{"key": it["key"], "원본상품명": it["name"], "카테고리": it["category"],
                  "참고키워드": it.get("tags", [])[:10]} for it in items]
        prompt = (f"아래 상품마다 새 상품명을 {per_product}개씩 지어 주세요. key는 그대로 돌려주세요.\n\n"
                  + json.dumps(lines, ensure_ascii=False))
        model = self.cfg.get("ai_model") or "claude-opus-5-5"
        kwargs = dict(
            model=model,
            max_tokens=16000,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.cfg.get("ai_effort") or "low",
                           "format": {"type": "json_schema", "schema": AI_SCHEMA}},
        )
        if model in ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"):
            # 안전 분류기가 거절하면 서버가 다른 모델로 다시 시도한다.
            resp = self.client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                                    fallbacks="default", **kwargs)
        else:
            resp = self.client.messages.create(**kwargs)
        with self.lock:
            self.usage["input"] += resp.usage.input_tokens + (resp.usage.cache_read_input_tokens or 0)
            self.usage["output"] += resp.usage.output_tokens
            self.usage["calls"] += 1
        if resp.stop_reason == "refusal":
            raise RuntimeError("AI가 이 묶음의 요청을 거절했습니다.")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("AI 응답이 너무 길어 잘렸습니다. 설정에서 '한 번에 보낼 상품 수'를 줄이세요.")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(text)
        return {str(x["key"]): [n for n in x["names"] if isinstance(n, str)] for x in data.get("items", [])}


class FakeAiNamer:
    """시연 모드용: API를 부르지 않고 재조합으로 'AI' 이름을 흉내 낸다."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.usage = {"input": 0, "output": 0, "calls": 0}

    def name_batch(self, items, per_product):
        import time as _t
        _t.sleep(0.3)
        self.usage["calls"] += 1
        return {it["key"]: recombine(it["name"], per_product, set(), [it["name"]], self.cfg, seed="ai" + it["key"])
                for it in items}
