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


def overlap(a, b):
    """두 이름의 단어가 겹치는 정도 (0~1, 자카드)."""
    sa, sb = {t.lower() for t in tokens(a)}, {t.lower() for t in tokens(b)}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def clean(name, max_len=100):
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    return name[:max_len].strip()


# ───────────────────────── 재조합

def recombine(original, count, taken_norms, siblings, cfg, seed, tag_words=()):
    """새 이름 count개. taken_norms(이미 쓰인 정규화 이름)·siblings(같은 원본의 다른 이름)와 겹치지 않게.

    방법: 원본 단어 중 일부를 빼고(가끔은 태그 단어를 더하고) 순서를 섞는다.
    단어가 적은 이름은 만들 수 있는 조합이 적어 count보다 적게 나올 수 있다.
    """
    words = tokens(original)
    extra = [t for t in tag_words if t.lower() not in {w.lower() for w in words}] \
        if cfg.get("recombine_use_tags") else []
    max_len = int(cfg.get("name_max_len") or 50)
    max_overlap = float(cfg.get("recombine_max_overlap") or 0.85)
    rnd = random.Random(seed)
    out, sibs = [], list(siblings)
    if len(words) < 2:
        return out
    for _ in range(count * 40):
        if len(out) >= count:
            break
        keep_n = rnd.randint(max(2, len(words) - 3), len(words))
        picked = rnd.sample(words, keep_n)
        if extra and rnd.random() < 0.6:
            picked += rnd.sample(extra, min(len(extra), rnd.randint(1, 2)))
        rnd.shuffle(picked)
        name = ""
        for w in picked:
            nxt = (name + " " + w).strip()
            if len(nxt) > max_len:
                break
            name = nxt
        n = normalize(name)
        if len(tokens(name)) < 2 or not n or n in taken_norms:
            continue
        # 같은 원본의 다른 이름(원본 포함)과 단어 구성이 거의 같거나 앞 두 단어가 같으면 버린다.
        if any(overlap(name, s) >= max_overlap or _same_start(name, s) for s in sibs):
            continue
        taken_norms.add(n)
        sibs.append(name)
        out.append(name)
    return out


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
- 띄어쓰기로 키워드를 구분하고, 특수문자와 같은 단어 반복은 쓰지 않습니다.
- 한 이름은 {max_len}자 이내로 합니다.
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
