"""셔플: 원본 앞 N단어는 그대로 두고, 나머지 단어(+ 직접 넣은 단어)를 무작위로 섞어 새 이름을 만든다. AI를 쓰지 않는다.

- 직접 넣은 단어도 고정 단어 뒤에서 나머지 단어와 함께 섞인다.
- 최대 글자 수(공백 포함)를 넘으면 직접 넣은 단어는 남기고 원본 단어를 뒤에서부터 뺀다.
- 금지어는 원본·넣은 단어 모두에서 단어 단위로 뺀다. 원본과 같은 이름, 33개 스토어에서 쓰는 이름(reject)은 버리고 다시 섞는다.
"""

import random


def make(original, fixed_n=3, extra=(), forbidden=(), seed=0, reject=None, max_chars=50, tries=30):
    """이름 하나 (못 만들면 None)."""
    forbidden = set(forbidden)
    toks = []
    for w in str(original or "").split():
        if w not in toks and w not in forbidden:
            toks.append(w)
    head, rest = toks[:max(0, int(fixed_n))], toks[max(0, int(fixed_n)):]
    adds = []
    for w in extra or ():
        w = str(w).strip()
        if w and w not in toks and w not in adds and w not in forbidden:
            adds.append(w)
    pool = rest + adds
    orig = " ".join(str(original or "").split())
    for attempt in range(tries):
        rng = random.Random(f"{seed}:{attempt}")
        body = list(pool)
        rng.shuffle(body)
        words = head + body
        while len(" ".join(words)) > max_chars:
            drop = next((i for i in range(len(words) - 1, len(head) - 1, -1) if words[i] not in adds), None)
            if drop is None:
                drop = len(words) - 1 if len(words) > len(head) else None
            if drop is None:
                break
            words.pop(drop)
        name = " ".join(words)
        if not name or name == orig or len(name) > max_chars:
            continue
        if reject and reject(name):
            continue
        return name
    return None
