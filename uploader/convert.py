"""엑셀 한 줄(상품 사전) → 검사 결과 / 등록 요청 본문.

엑셀 열 이름이 바뀌면 이 파일만 고치면 된다.
"""

import copy
import hashlib
import json
import math
import os
import re

from . import config

REF = "상세페이지 참조"
ORIGIN_CODES = {"중국": "0200037"}
IMG_SRC_RE = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
VIDEO_RE = re.compile(r"<video\b.*?(?:</video>|/>)", re.I | re.S)


class ConvertError(Exception):
    pass


def to_int(v, default=0):
    if v in (None, ""):
        return default
    try:
        return int(float(str(v).replace(",", "")))
    except ValueError:
        return default


def deep_merge(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _strip_empty(d):
    return {k: v for k, v in d.items() if v not in ([], {}, None, "")}


# ───────────────────────── 엑셀 값 읽기

def thumbnails(row):
    t = row.get("썸네일")
    if isinstance(t, str):
        t = [t]
    return [u for u in (t or []) if isinstance(u, str) and u.startswith("http")]


def detail_images(row):
    html = strip_trackers(row.get("상세설명") or "")
    seen, out = set(), []
    for m in IMG_SRC_RE.finditer(html):
        u = m.group(3).strip()
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("http") and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _norm_url(u):
    """https·쿼리·크기 옵션을 빼고 호스트+경로만 (같은 이미지를 다른 주소 형태로 받아도 같게)."""
    u = re.sub(r"^https?:", "", u.strip()).lstrip("/")
    return u.split("?")[0].split("#")[0].lower()


def name_key(name):
    """원본 구분값: 상품명이 '완전히' 같아야 같은 원본 (띄어쓰기·기호·순서까지 똑같아야 함, 앞뒤 공백만 무시).
    대표 이미지 주소가 같아도 상품명이 다르면 다른 원본이다."""
    return "n:" + hashlib.sha1(str(name or "").strip().encode()).hexdigest()[:24]


def source_fingerprint(row):
    """원본 상품을 구분하는 값. 스토어마다 바뀌는 판매자코드 대신 바뀌지 않는 대표 썸네일 주소를 쓴다.
    썸네일이 없으면 상세 이미지(모든 상품 공통 배너는 거르기 어려워 앞 5장 묶음), 그것도 없으면 상품명."""
    th = thumbnails(row)
    if th:
        basis = "img:" + _norm_url(th[0])
    else:
        det = detail_images(row)
        from .namegen import normalize
        basis = ("det:" + "|".join(_norm_url(u) for u in det[:5])) if det else "name:" + normalize(row.get("상품명"))
    return hashlib.sha1(basis.encode()).hexdigest()[:24]


def tags(row):
    t = row.get("상품태그")
    if isinstance(t, str):
        t = [x.strip() for x in t.split(",")]
    return [x for x in (t or []) if isinstance(x, str) and x]


def options(row):
    o = row.get("옵션상품")
    if not isinstance(o, dict):
        return None
    o = dict(o)
    for k in ("optionCombinations", "optionSimple", "optionCustom", "optionStandards"):
        v = o.get(k)
        if v is not None and not isinstance(v, list):
            o[k] = []
        elif isinstance(v, list):
            o[k] = [c for c in v if isinstance(c, dict)]
    if any(o.get(k) for k in ("optionCombinations", "optionSimple", "optionCustom", "optionStandards")):
        return o
    return None


def option_key(c):
    """옵션 조합을 맞춰 보는 열쇠 (옵션명1·2·3, 앞뒤 공백 무시)."""
    return tuple(str(c.get(f"optionName{i}") or "").strip() for i in (1, 2, 3))


def live_prices(body):
    """네이버 원상품(GET 그대로) → {final 손님 가격, opts {옵션 열쇠: 손님이 내는 옵션 추가금}}.
    즉시할인이 %면 옵션 추가금에도 같은 %가 빠지므로 그만큼 뺀 값을 손님 가격으로 본다 (10원 단위 반올림)."""
    o = (body or {}).get("originProduct") or {}
    sale = to_int(o.get("salePrice"))
    dm = (((o.get("customerBenefit") or {}).get("immediateDiscountPolicy") or {}).get("discountMethod") or {})
    v, unit = to_float(dm.get("value")), str(dm.get("unitType") or "")
    pct = v / 100 if unit == "PERCENT" and 0 < v < 100 else 0.0
    off = int(sale * pct) // 10 * 10 if pct else (int(v) if unit == "WON" and 0 < v < sale else 0)
    opts = {}
    for c in (((o.get("detailAttribute") or {}).get("optionInfo") or {}).get("optionCombinations") or []):
        p = to_int(c.get("price"))
        opts[option_key(c)] = int(round(p * (1 - pct) / 10.0)) * 10 if pct else p
    return {"final": sale - off, "opts": opts}


def to_float(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


# 엑셀 가격 칸 확인 (할인가는 '할인 금액'이 규칙 — 다른 뜻으로 적은 파일을 미리 잡는다)
PRICE_FLAG = {"pct": "할인가가 100원 미만 — 퍼센트(%)를 적은 것 같음",
              "half": "할인가가 판매가의 절반 넘음 — '할인된 가격'을 적은 것 같음",
              "over": "할인가가 판매가 이상 — 할인을 안 한 것으로 처리됨",
              "cost": "원가가 손님 가격(판매가 - 할인가)보다 큼"}


def price_flag(row):
    """이상한 가격 칸이면 PRICE_FLAG 열쇠, 아니면 ''."""
    price, off, cost = to_int(row.get("판매가")), to_int(row.get("할인가")), to_int(row.get("원가"))
    if off > 0 and price > 0:
        if off < 100:
            return "pct"
        if off >= price:
            return "over"
        if off * 2 > price:
            return "half"
    if cost > 0 and cost > net_price(row) > 0:
        return "cost"
    return ""


def price_scan(rows, limit=8):
    """엑셀 줄들 → {n 이상한 줄 수, total, by {열쇠: 수}, labels, examples [{line, name, 판매가, 할인가, 원가, 손님가격, why}]}."""
    out = {"n": 0, "total": 0, "by": {}, "labels": PRICE_FLAG, "examples": []}
    for i, row in enumerate(rows, 2):
        if not row.get("상품명"):
            continue
        out["total"] += 1
        k = price_flag(row)
        if not k:
            continue
        out["n"] += 1
        out["by"][k] = out["by"].get(k, 0) + 1
        if len(out["examples"]) < limit:
            out["examples"].append({"line": i, "name": str(row.get("상품명") or "")[:60], "price": to_int(row.get("판매가")),
                                    "off": to_int(row.get("할인가")), "cost": to_int(row.get("원가")),
                                    "final": net_price(row), "why": k})
    return out


def option_count(row):
    o = options(row) or {}
    return len(o.get("optionCombinations") or []) + len(o.get("optionSimple") or []) \
        + len(o.get("optionStandards") or [])


def is_naver_image(url):
    return "pstatic.net/" in url


def detail_images_to_upload(row, cfg):
    """네이버 서버에 올릴 상세 이미지. 이미 네이버 이미지 서버 주소면 설정에 따라 그대로 둔다."""
    if not cfg.get("reupload_detail_images", True):
        return []
    keep = cfg.get("keep_pstatic_detail_images", True)
    thumbs = set(thumbnails(row)[:10])
    # 보낼 상세에 실제로 남는 사진만 (옵션표 그림으로 들어가는 옵션 사진·추적 그림은 올리지 않음 — 요청 수 아낌)
    sent = _layout(detail_source(row, cfg), "basic", OPTION_COLOR, None)[0]
    seen, out = set(), []
    for m in IMG_SRC_RE.finditer(sent):
        u = m.group(3).strip()
        u = "https:" + u if u.startswith("//") else u
        if u.startswith("http") and u not in seen and u not in thumbs and not (keep and is_naver_image(u)):
            seen.add(u)
            out.append(u)
    return out


def images_to_upload(row, cfg):
    """네이버 서버에 올릴 원본 이미지 주소 목록 (썸네일 앞, 중복 없음)."""
    return thumbnails(row)[:10] + detail_images_to_upload(row, cfg)


def net_price(row):
    """기준 가격 = 엑셀 판매가(R열) - 할인가(S열). 할인가는 '할인 금액'이다 (할인된 가격이 아님).
    할인가가 없거나 판매가보다 크면 판매가 그대로. 프로그램은 이 금액만 기준 가격으로 쓴다."""
    price, off = to_int(row.get("판매가")), to_int(row.get("할인가"))
    return price - off if 0 < off < price else price


def summary(row, cfg):
    """목록 화면에 보여줄 값."""
    cat = str(row.get("카테고리") or "").strip()
    th = thumbnails(row)
    return {
        "row_key": str(row.get("id") or ""),
        "source_key": name_key(row.get("상품명")),
        "img_key": source_fingerprint(row),   # 대표 이미지 주소 (원본 파일 올릴 때 겹침 확인용 — 원본 구분에는 안 씀)
        "seller_code": str(row.get("판매자코드") or ""),
        "name": str(row.get("상품명") or "").strip(),
        "price": net_price(row),
        "category": cat,
        "thumb": th[0] if th else "",
        "option_count": option_count(row),
        "image_count": len(images_to_upload(row, cfg)),
        "has_video": "<video" in (row.get("상세설명") or "").lower(),
    }


# ───────────────────────── 검사

def option_price_range(price):
    """스마트스토어 옵션가 허용 범위 (판매가 기준)."""
    if price < 2000:
        return 0, price
    if price < 10000:
        return -price // 2, price
    return -price // 2, price // 2


def importer_for(store, cfg):
    """수입사 칸: 스토어에 따로 정했으면 그것, 아니면 설정 틀(기본 '{store}협력사')에 스토어 이름을 넣은 것."""
    if store and str(store.get("importer") or "").strip():
        return str(store["importer"]).strip()
    tpl = str(cfg.get("importer_template") or "").strip()
    if tpl:
        return tpl.replace("{store}", str((store or {}).get("name") or "")).strip() or REF
    return cfg.get("importer") or REF


def info_fields(row, cfg):
    """(모델명, 브랜드, 제조사). info_force(기본 켬)면 엑셀 값과 상관없이 셋 다 '상세페이지 참조'
    (상세 정리·판매 중 상품 연결이 원본에 넣는 값과 같은 결과). 끄면 엑셀 값 (비면 모델명·제조사는 '상세페이지 참조')."""
    if cfg.get("info_force", True):
        return REF, REF, REF
    brand = row.get("브랜드") or ""
    return row.get("모델명") or REF, brand, row.get("제조사") or brand or REF


def origin_info(text, cfg, importer=None):
    """원산지 → 네이버 원산지 정보.
    origin_force(기본 켬)면 엑셀 값과 상관없이 설정의 원산지(기본 중국)로 등록한다.
    아니면 엑셀 값 전체로 먼저 찾고(띄어쓰기 무시, 예: '상세페이지 참조'), 없으면 앞 단어로 찾는다(예: '중국(광동)')."""
    if cfg.get("origin_force", True):
        text = cfg.get("origin_country") or "중국"
    else:
        text = text or cfg.get("origin_default") or "중국"
    codes = {re.sub(r"\s+", "", str(k)): v for k, v in (ORIGIN_CODES | (cfg.get("origin_codes") or {})).items()}
    whole = re.sub(r"\s+", "", str(text))
    first = re.sub(r"\s+", "", re.split(r"[(\s]", str(text).strip())[0])
    code = codes.get(whole) or codes.get(first)
    if not code:
        raise ConvertError(f"원산지 '{text}'의 코드가 설정에 없습니다 (설정 → 상품 기본값 → 원산지 코드).")
    return {"originAreaCode": code, "importer": importer or cfg.get("importer") or REF}


def validate(row, cfg, categories=None):
    """(오류 목록, 경고 목록). 오류가 있으면 등록하지 않는다.

    categories가 None이면(아직 API 연결 전) 카테고리 존재 여부는 등록할 때 확인한다.
    """
    errors, warnings = [], []
    name = str(row.get("상품명") or "").strip()
    price = net_price(row)
    if not name:
        errors.append("상품명이 비어 있습니다.")
    elif len(name) > 100:
        warnings.append(f"상품명이 {len(name)}자입니다. 앞 100자만 등록됩니다.")
    if price <= 0:
        errors.append("판매가가 0입니다.")
    if not thumbnails(row):
        errors.append("썸네일(대표 이미지)이 없습니다.")
    cat = str(row.get("카테고리") or "").strip()
    if not cat:
        errors.append("카테고리가 비어 있습니다.")
    elif categories is not None:
        cid, _ = find_category(cat, categories, cfg)
        if not cid:
            g, gname = find_category(cat, categories, cfg, guess=True)
            errors.append(f"카테고리 '{cat}'를 스마트스토어에서 찾지 못했습니다."
                          + (f" '{gname}'로 보입니다 —" if g else "")
                          + " 원본 상품 → '카테고리 맞추기'에서 확인해 주세요.")
    try:
        origin_info(row.get("원산지"), cfg)
    except ConvertError as e:
        errors.append(str(e))

    o = options(row)
    if o and price > 0:
        lo, hi = option_price_range(price)
        bad = [c.get("optionName1", "?") for c in o.get("optionCombinations") or []
               if not lo <= to_int(c.get("price")) <= hi]
        if bad:
            warnings.append(f"옵션 추가금이 허용 범위({lo:+,}~{hi:+,}원)를 벗어남: {', '.join(bad[:3])}"
                            + (f" 외 {len(bad) - 3}개" if len(bad) > 3 else ""))
    if len(tags(row)) > 10:
        warnings.append(f"태그 {len(tags(row))}개 중 앞 10개만 등록됩니다.")
    if len(thumbnails(row)) > 10:
        warnings.append("썸네일이 10장을 넘어 앞 10장만 등록됩니다.")
    d = str(row.get("상세설명") or "")
    if d:
        d = naver_safe_layout(strip_trackers(d))
        if layout_left(d):
            warnings.append("상세에 2열로 바꾸지 못한 옵션 사진 묶음이 있습니다 (네이버에서 한 줄에 하나씩 보일 수 있음) — 이 원본을 알려 주세요")
        iss = mobile_issues(d)
        if iss:
            warnings.append(f"상세에 {', '.join(iss)}이(가) 있어 네이버 모바일에서 흐린 캡처로 보일 수 있습니다")
    return errors, warnings


# ───────────────────────── 등록 요청

# ───────────────────────── 카테고리 찾기

_CAT_SEP = re.compile(r"\s*(?:>|＞|›|»)\s*")   # '/'는 네이버 이름 안에도 있음 (가구/인테리어)
_cat_index = {"src": None}


def cat_norm(s):
    """'패션잡화 > 모자 > 사파리 모자' → '패션잡화>모자>사파리모자' (띄어쓰기·구분자 차이 무시)"""
    return ">".join(re.sub(r"\s+", "", p) for p in _CAT_SEP.split(str(s or "").strip()) if p.strip())


def _index(categories):
    if _cat_index["src"] is not categories:
        norm, leaf, ids = {}, {}, set()
        for name, cid in categories.items():
            n = cat_norm(name)
            norm[n] = cid
            leaf.setdefault(n.rsplit(">", 1)[-1], []).append(name)
            ids.add(str(cid))
        _cat_index.update(src=categories, norm=norm, leaf=leaf, ids=ids)
    return _cat_index


def with_category_fix(row, fix):
    """직접 고른 네이버 카테고리가 있으면 '카테고리'를 그것으로 바꾼 복사본 (엑셀 값은 '엑셀카테고리'에 남김)."""
    fix = str(fix or "").strip()
    if not fix or not row:
        return row
    return {**row, "카테고리": fix, "엑셀카테고리": row.get("카테고리")}


def find_category(cat, categories, cfg=None, guess=False):
    """엑셀 카테고리 → (네이버 카테고리 번호, 맞춘 방법). 못 찾으면 (None, '').
    순서: 그대로 → 직접 맞춰 둔 것(설정 category_map) → 띄어쓰기·구분자 무시 → 카테고리 번호.
    guess=True면 대분류·마지막 이름이 같은 것이 하나뿐일 때 그것도 돌려준다 (추천용 — 등록에는 '카테고리 맞추기'에서 확인한 것만 씀)."""
    cat = str(cat or "").strip()
    if not cat or not categories:
        return None, ""
    if cat in categories:
        return categories[cat], ""
    ix = _index(categories)
    mapped = ((cfg or {}).get("category_map") or {}).get(cat) or ((cfg or {}).get("category_map") or {}).get(cat_norm(cat))
    if mapped:
        mapped = str(mapped).strip()
        if mapped in ix["ids"]:
            return mapped, "직접 맞춤"
        hit = categories.get(mapped) or ix["norm"].get(cat_norm(mapped))
        if hit:
            return hit, "직접 맞춤"
    n = cat_norm(cat)
    if n in ix["norm"]:
        return ix["norm"][n], ""
    if cat.isdigit() and cat in ix["ids"]:
        return cat, ""
    parts = n.split(">")
    # 마지막 이름과 첫 단계(대분류)가 같은 네이버 카테고리가 딱 하나면 그것 (중간 단계 이름이 바뀐 경우)
    same = [x for x in ix["leaf"].get(parts[-1], []) if cat_norm(x).split(">")[0] == parts[0]]
    if guess and len(same) == 1:
        return categories[same[0]], same[0]
    return None, ""


def category_suggestions(cat, categories, limit=6):
    """못 찾은 카테고리와 비슷한 네이버 카테고리 이름 (고르기용)."""
    import difflib
    n = cat_norm(cat)
    parts = n.split(">")
    leaf = parts[-1]
    scored = []
    for name in categories:
        m = cat_norm(name)
        mp = m.split(">")
        s = difflib.SequenceMatcher(None, leaf, mp[-1]).ratio() * 2
        s += sum(1 for p in parts[:-1] if p in mp) * 0.4
        if leaf and (leaf in m or mp[-1] in leaf):
            s += 0.8
        scored.append((s, name))
    scored.sort(reverse=True)
    return [x for _, x in scored[:limit]]


_DIV_TAG = re.compile(r"<(/?)div\b[^>]*>", re.I)
_DIV_STYLED = re.compile(r"""<div\b[^>]*?\bstyle\s*=\s*(["'])((?:(?!\1).)*)\1[^>]*>""", re.I | re.S)   # style 값 = group 2
_FLEX_COL = re.compile(r"""style\s*=\s*(["'])((?:(?!\1).)*flex-direction\s*:\s*column(?:(?!\1).)*)\1""", re.I | re.S)
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_HEAD_BEFORE = re.compile(r"<(h[1-4])\b[^>]*>(.*?)</\1>\s*$", re.I | re.S)
OPTION_COLOR = "#1F2937"
SPACER = "<p><br></p>"   # 빈 줄 하나 (네이버가 지우지 않는 가장 단순한 간격)


def _div_end(html, start):
    """start 자리의 <div …>와 짝이 되는 </div> 바로 뒤 위치 (못 찾으면 -1)."""
    depth = 0
    for m in _DIV_TAG.finditer(html, start):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.end()
    return -1


def _children(inner):
    """inner 안의 맨 바깥 <div>…</div> 들."""
    out, i = [], 0
    while True:
        m = re.search(r"<div\b", inner[i:], re.I)
        if not m:
            return out
        s = i + m.start()
        e = _div_end(inner, s)
        if e < 0:
            return out
        out.append(inner[s:e])
        i = e


def _card_box(style):
    """옵션 사진을 여러 칸으로 늘어놓는 묶음인지 (grid, 줄바꿈하는 flex) — 네이버가 둘 다 지워 한 줄에 하나씩 쌓인다."""
    s = re.sub(r"\s+", "", style.lower())
    return ("display:grid" in s or "display:inline-grid" in s
            or (("display:flex" in s or "display:inline-flex" in s) and "flex-wrap:wrap" in s))


def _text(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()


_SRC = re.compile(r"""\ssrc\s*=\s*(["'])(.*?)\1""", re.I | re.S)
# 수집 프로그램이 넣어 둔 방문 알림(보이지 않는 줄의 배경 그림 = 손님이 볼 때마다 그쪽 서버로 알림) 같은
# 내용 없는 요소의 네이버 밖 배경 그림
_BG_EMPTY = re.compile(r"""<(p|div|span)\b[^>]*\bstyle\s*=\s*(["'])(?:(?!\2).)*url\(\s*['"]?([^)'"]+)['"]?\s*\)(?:(?!\2).)*\2[^>]*>\s*</\1>""",
                       re.I | re.S)


# 수집·대량 등록 프로그램이 상세에 숨겨 넣는 추적 그림 주소 (손님이 볼 때마다, 또는 내려받을 때 그쪽에 기록이 남음)
TRACKER_HOSTS = ("p.tcdn.co.kr",)
_TINY_BOX = re.compile(r"""<(div|p|span|section)\b[^>]*\bstyle\s*=\s*(["'])(?:(?!\2).)*?\bmax-width\s*:\s*[0-2]px(?:(?!\2).)*\2[^>]*>""",
                       re.I | re.S)


def _img_src(tag):
    m = _SRC.search(tag)
    u = m.group(2).strip() if m else ""
    return "https:" + u if u.startswith("//") else u


def is_tracker_img(tag):
    """추적 그림인지: 알려진 추적 주소, 주소가 사이트 첫 화면뿐(그림이 아님), 1~2px 크기로 숨긴 그림."""
    u = _img_src(tag)
    if not u or u.startswith("#") or u.startswith("data:"):
        return False
    host = u.split("/")[2].lower() if "//" in u else ""
    if host in TRACKER_HOSTS or any(host.endswith("." + h) for h in TRACKER_HOSTS):
        return True
    if re.fullmatch(r"https?://[^/?#]+/?", u, re.I):
        return True
    w = re.search(r"""\bwidth\s*=\s*["']?\s*([0-9.]+)\s*(?:px)?["']?""", tag, re.I)
    h = re.search(r"""\bheight\s*=\s*["']?\s*([0-9.]+)\s*(?:px)?["']?""", tag, re.I)
    if w and h and float(w.group(1)) <= 2 and float(h.group(1)) <= 2:
        return True
    st = re.search(r"""\bstyle\s*=\s*(["'])(.*?)\1""", tag, re.I | re.S)
    if st and (re.search(r"(?<![-\w])width\s*:\s*[0-2]px", st.group(2), re.I) or re.search(r"(?<![-\w])height\s*:\s*[0-2]px", st.group(2), re.I)):
        return True
    return False


def strip_trackers_count(html):
    """보이지 않는 방문 알림·추적 그림을 지운다 → (HTML, 지운 수).
    ① 네이버 밖 배경 그림만 있는 빈 요소(픽투셀 등) ② 알려진 추적 주소·사이트 주소뿐인 그림·1~2px 그림(퍼센티 등)
    ③ 폭을 1~2px로 줄인 칸 안의 그림. 빈 칸은 공백 정리(tighten)가 치운다."""
    html = str(html or "")
    n = 0

    def bg(m):
        nonlocal n
        if "pstatic.net" in m.group(3):
            return m.group(0)
        n += 1
        return ""
    html = _BG_EMPTY.sub(bg, html)
    # ③ max-width:0~2px 칸 안의 그림
    out, i = [], 0
    for m in _TINY_BOX.finditer(html):
        if m.start() < i:
            continue
        tag = m.group(1).lower()
        if tag == "div":
            end = _div_end(html, m.start())
        else:
            e = re.search(rf"</{tag}\s*>", html[m.end():], re.I)
            end = m.end() + e.end() if e else -1
        if end < 0:
            continue
        inner = html[m.start():end]
        k = len(_IMG_TAG.findall(inner))
        if k:
            n += k
            out.append(html[i:m.start()])
            out.append(_IMG_TAG.sub("", inner))
            i = end
    html = "".join(out) + html[i:]

    def img(m):
        nonlocal n
        if is_tracker_img(m.group(0)):
            n += 1
            return ""
        return m.group(0)
    return _IMG_TAG.sub(img, html), n


def strip_trackers(html):
    """보이지 않는 방문 알림·추적 그림을 지운다."""
    return strip_trackers_count(html)[0]


# 2) 상세 공백 정리 — 사진 사이 빈 줄(빈 문단·보이지 않는 글자 하나만 든 문단·줄바꿈)과 사진 아래 틈을 없앤다
_INVIS = "(?:\\s|&nbsp;|&#160;|&#8203;|&#x200b;|\u200b|\u00a0|\ufeff)"
_EMPTY_INLINE = rf"(?:<(?:span|b|strong|i|em|font|u)\b[^>]*>{_INVIS}*</(?:span|b|strong|i|em|font|u)>)"
_EMPTY_P = re.compile(rf"<p\b[^>]*>(?:{_INVIS}|<br\s*/?>|{_EMPTY_INLINE})*</p>", re.I)
_EMPTY_BOX = re.compile(rf"<(div|span|a|section|center)\b[^>]*>{_INVIS}*</\1>", re.I)
_BR_NEAR_IMG = re.compile(r"(<img\b[^>]*>(?:\s*</a>)?)(?:\s*<br\s*/?>)+|(?:<br\s*/?>\s*)+(?=(?:<a\b[^>]*>\s*)?<img\b)", re.I)
IMG_BLOCK = "display:block;margin:0 auto;"


def _img_block(tag):
    """사진 아래 글자 줄 틈(인라인 그림의 기준선 여백)이 생기지 않게 display:block + 가운데."""
    if tag.startswith("<img") and re.search(r"display\s*:\s*block", tag, re.I):
        return tag
    m = re.search(r"""\bstyle\s*=\s*(["'])(.*?)\1""", tag, re.I | re.S)
    if m:
        st = m.group(2).strip()
        st = (st.rstrip("; ") + ";" if st else "") + IMG_BLOCK
        return tag[:m.start()] + f'style={m.group(1)}{st}{m.group(1)}' + tag[m.end():]
    return re.sub(r"^<img\b", f'<img style="{IMG_BLOCK}"', tag, flags=re.I)


def tighten(html):
    """상세의 사진 사이 공백 정리. 글자가 있는 문단·표·동영상은 그대로.
    빈 줄(빈 문단·보이지 않는 글자 하나만 든 문단·빈 감싸개·줄바꿈)이 사진과 사진 사이에 있으면 없애고,
    글자와 글자(또는 글자와 사진) 사이의 빈 줄 여러 개는 한 줄로. 사진은 아래 틈이 없게 display:block.
    (원본 상세는 그대로 두고 보낼 상세·미리보기에만)"""
    html = str(html or "")
    box = re.compile(rf"<(div|span|a|section|center|p)\b[^>]*>((?:{_INVIS}|{re.escape(_GAP)})*)</\1>", re.I)
    for _ in range(6):   # 빈 감싸개 안의 빈 문단 → 비게 된 감싸개 … (몇 겹) — 빈 문단은 표시만 남김
        new = box.sub(lambda m: _GAP if _GAP in m.group(2) else "", _EMPTY_P.sub(_GAP, html))
        if new == html:
            break
        html = new
    # 빈 줄 묶음(표시·줄바꿈·공백) 하나하나: 양쪽이 사진이면 없앰, 아니면 빈 줄 하나로
    def run(m):
        before, after = html[max(0, m.start() - 2000):m.start()], html[m.end():m.end() + 2000]
        prev_img = re.search(r"<img\b[^>]*>\s*(?:</(?:a|span|p|div|center)>\s*)*$", before, re.I)
        next_img = re.match(r"\s*(?:<(?:a|span|p|div|center)\b[^>]*>\s*)*<img\b", after, re.I)
        if prev_img and next_img:
            return ""
        return SPACER if _GAP in m.group(0) else m.group(0)
    html = re.sub(rf"(?:{re.escape(_GAP)}|<br\s*/?>|\s)*{re.escape(_GAP)}(?:{re.escape(_GAP)}|<br\s*/?>|\s)*", run, html)
    html = html.replace(_GAP, "")
    html = _BR_NEAR_IMG.sub(lambda m: m.group(1) or "", html)
    return _IMG_TAG.sub(lambda m: _img_block(m.group(0)), html)


_GAP = "\u0000GAP\u0000"   # 빈 문단 자리 표시 (tighten 안에서만)


# 3) 스마트에디터 표(table)로 만든 옵션표 → 옵션 사진 묶음(grid)으로 바꿔 두면 아래 _layout이 옵션표 그림으로 바꾼다
_TABLE_OPEN = re.compile(r"<table\b[^>]*>", re.I)
_TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
_TD = re.compile(r"<t([dh])\b[^>]*>(.*?)</t\1>", re.I | re.S)
_SE_TABLE = re.compile(r"""<div\b[^>]*\bclass\s*=\s*(["'])[^"']*\bse-component\b[^"']*\bse-table\b[^"']*\1[^>]*>""", re.I)
_SE_TEXT = re.compile(r"""<div\b[^>]*\bclass\s*=\s*(["'])[^"']*\bse-component\b[^"']*\bse-text\b[^"']*\1[^>]*>""", re.I)
OPTION_TITLE = re.compile(r"^(?:옵션|옵션(?:설명|안내|선택|정보|구성|종류|보기)|option|options)[:：]?$", re.I)


def _is_option_title(t):
    """'옵션'·'옵 션'·'옵션 설명'·'OPTION' 같은 짧은 제목인지 (띄어쓰기 무시)."""
    return bool(OPTION_TITLE.match(re.sub(r"\s+", "", t or "")))


def _table_end(html, start):
    depth = 0
    for m in re.finditer(r"<(/?)table\b[^>]*>", html[start:], re.I):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return start + m.end()
    return -1


def _vis(h):
    """보이는 글자만 (보이지 않는 글자·&nbsp; 뺌)."""
    t = _text(h).replace("&nbsp;", " ").replace("\u200b", "").replace("\xa0", " ").replace("\ufeff", "")
    return re.sub(r"\s+", " ", t).strip()


def _imgs_of(h):
    return [u for u in (_img_src(t) for t in _IMG_TAG.findall(h)) if u and not u.startswith("#")]


def table_cards(table):
    """표 하나 → 옵션 카드 [[사진들], 이름] 또는 None(옵션표 아님: 사진 없는 표·사진만 있는 표·글자 덩어리 표).
    모양: ① 사진 칸 아래 줄에 이름 칸(옵션마다 표 하나·한 줄에 여러 칸) ② 한 칸에 사진+이름 ③ 사진 칸 오른쪽에 이름 칸."""
    rows = []
    for tr in _TR.findall(table):
        cells = [(_imgs_of(c), _vis(_IMG_TAG.sub("", c))) for _, c in _TD.findall(tr)]
        if cells:
            rows.append(cells)
    if not rows or not any(im for r in rows for im, _ in r):
        return None
    if any(len(t) > 80 for r in rows for _, t in r):   # 긴 글(설명 표)은 옵션표가 아님
        return None
    cards, used = [], set()
    for ri, r in enumerate(rows):
        for ci, (im, t) in enumerate(r):
            if (ri, ci) in used or not im:
                continue
            used.add((ri, ci))
            name = t
            if not name and ri + 1 < len(rows) and ci < len(rows[ri + 1]):
                im2, t2 = rows[ri + 1][ci]
                if not im2 and t2:
                    name = t2
                    used.add((ri + 1, ci))
            if not name and ci + 1 < len(r):
                im2, t2 = r[ci + 1]
                if not im2 and t2:
                    name = t2
                    used.add((ri, ci + 1))
            cards.append([im, name])
    leftover = [t for ri, r in enumerate(rows) for ci, (im, t) in enumerate(r) if (ri, ci) not in used and t]
    if leftover or not any(name for _, name in cards):   # 짝 없는 글자가 있거나 이름이 하나도 없으면 옵션표로 보지 않음
        return None
    return cards


def _grid_html(cards):
    cells = "".join(f'<div>{"".join(f"<img src={chr(34)}{u}{chr(34)}>" for u in im)}<div>{name}</div></div>' for im, name in cards)
    return f'<div style="display:grid;grid-template-columns:1fr 1fr;">{cells}</div>'


def se_option_tables(html):
    """이어진 표 옵션표(스마트에디터 se-table 또는 일반 table, 사이에 빈 문단만)를 옵션 사진 묶음 하나로.
    바로 앞의 '옵션'·'옵션 설명' 같은 짧은 제목 문단은 제목(<h3>)으로. 옵션표가 아닌 표는 그대로."""
    html = str(html or "")
    spans, flats = [], []   # (시작, 끝, 카드들) · (시작, 끝, 사진들)
    i = 0
    while True:
        se = _SE_TABLE.search(html, i)
        tb = _TABLE_OPEN.search(html, i)
        if not se and not tb:
            break
        if se and (not tb or se.start() <= tb.start()):
            start, end = se.start(), _div_end(html, se.start())
            t = _TABLE_OPEN.search(html, start)
            if end < 0 or not t:   # 엑셀 칸 글자 수 제한으로 상세가 표 중간에서 잘림 → 남은 부분은 사진만
                end = len(html)
            tend = _table_end(html, t.start()) if t and t.start() < end else -1
            table = html[t.start():tend] if tend > 0 else (html[t.start():end] if t else "")
        else:
            start, end = tb.start(), _table_end(html, tb.start())
            if end < 0:
                end = len(html)
            table = html[start:end]
        if not table:
            i = (se or tb).end()
            continue
        cards = table_cards(table) if _table_end(table, 0) > 0 else None
        if cards:
            spans.append((start, end, cards))
        else:
            rows_txt = [_vis(_IMG_TAG.sub("", c)) for _, c in _TD.findall(table)] or [_vis(_IMG_TAG.sub("", table))]
            ims = _imgs_of(table)
            if ims and not any(rows_txt):   # 사진만 든 표(또는 잘린 표) → 사진을 위아래로 (모바일 흐린 캡처 방지)
                flats.append((start, end, ims))
            elif end == len(html) and _table_end(table, 0) < 0 and not ims and not _vis(re.sub(r"<[^>]*$", "", table)):
                flats.append((start, end, []))   # 잘려서 사진·글자 없이 남은 표 꼬리 → 뺌
        i = end
    if flats:
        out, j = [], 0
        for st, en, ims in flats:
            out.append(html[j:st])
            out.append("".join(f'<p style="text-align:center;margin:0;"><img src="{u}" style="width:100%;"></p>' for u in ims))
            j = en
        html = "".join(out) + html[j:]
        return se_option_tables(html) if spans else html
    if not spans:
        return html
    # 사이에 빈 것만 있는 이어진 표들 → 한 묶음
    groups = []
    for st, en, cards in spans:
        gap = html[groups[-1][1]:st] if groups else ""
        if groups and not _vis(gap) and not _IMG_TAG.search(gap) and not re.search(r"<(video|iframe|table)\b", gap, re.I):
            groups[-1] = (groups[-1][0], en, groups[-1][2] + cards)
        else:
            groups.append((st, en, cards))
    out, i = [], 0
    for st, en, cards in groups:
        before = html[i:st]
        title = ""
        # 바로 앞 제목 문단(스마트에디터 글자 칸 또는 짧은 문단) — 글자가 '옵션'류면 제목으로
        tail = tighten(before)
        ms = list(_SE_TEXT.finditer(before))
        if ms:
            m = ms[-1]
            e = _div_end(before, m.start())
            if e > 0 and not _vis(before[e:]) and not _IMG_TAG.search(before[e:]) and _is_option_title(_vis(before[m.start():e])):
                title = _vis(before[m.start():e])
                before = before[:m.start()]
        if not title:
            mp = re.search(r"<(p|h[1-6]|div)\b[^>]*>((?:(?!<\1\b).)*?)</\1>\s*$", tail, re.I | re.S)
            if mp and not _IMG_TAG.search(mp.group(2)) and _is_option_title(_vis(mp.group(2))):
                title = _vis(mp.group(2))
                k = before.rfind(mp.group(0)) if mp.group(0) in before else -1
                before = before[:k] if k >= 0 else before
        out.append(before)
        out.append((f"<h3>{title}</h3>" if title else "") + _grid_html(cards))
        i = en
    return "".join(out) + html[i:]


def _cards(inner):
    """묶음 안의 칸들 → [[사진 주소들], 이름]. 칸이 div가 아니면 사진 하나씩 한 칸."""
    def srcs(h):
        out = []
        for t in _IMG_TAG.findall(h):
            m = _SRC.search(t)
            if m and m.group(2).strip():
                u = m.group(2).strip()
                out.append("https:" + u if u.startswith("//") else u)
        return out
    out = []
    for c in _children(inner):
        imgs, cap = srcs(c), _text(_IMG_TAG.sub("", c))
        if imgs or cap:
            out.append([imgs, cap])
    return out or [[[u], ""] for u in srcs(inner)]


def option_look(cfg, store=None):
    """(옵션표 모양, 강조색, 그림에 넣을 스토어 이름): 스토어 템플릿 값, 없으면 설정 공통값.
    모양: strong·basic(예전 두 가지) / a~e(시안 A~E — 그 스토어 이름이 그림에 들어감, 다른 모양은 이름 '')."""
    from . import optimage
    store = store or {}
    style = store.get("tpl_opt_style") or cfg.get("option_table_style") or "strong"
    style = style if style in OPTION_STYLES else "strong"
    color = store.get("tpl_opt_color") or cfg.get("option_table_color")
    color = color if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(color or "")) else OPTION_COLOR
    return style, color, (str(store.get("name") or "") if style in optimage.NEW_STYLES else "")


def _layout(html, style, color, opt_urls):
    """옵션 사진 묶음(grid·줄바꿈 flex)을 2열 그림(<img>)으로 바꾼 HTML과 묶음 목록.
    opt_urls[k] = k번째 묶음의 그림 주소들 (없으면 '#옵션표그림…' 자리표시 — 올릴 때 엔진이 그려서 채움).
    strong이면 바로 위 제목(h1~h4)은 그림의 색 띠로 들어가므로 HTML에서 뺀다."""
    from . import optimage
    out, boxes, i = [], [], 0
    for m in _DIV_STYLED.finditer(html):
        if m.start() < i or not _card_box(m.group(2)):
            continue
        end = _div_end(html, m.start())
        if end < 0:
            continue
        cards = _cards(html[m.end():end - len("</div>")])
        grid = "grid" in m.group(2).lower()
        if not cards or (not grid and sum(1 for x, _ in cards if x) < 2):   # 줄바꿈 flex는 사진 칸이 둘 이상일 때만
            continue
        before, title = html[i:m.start()], ""
        h = _HEAD_BEFORE.search(before)
        h = h if h and _text(h.group(2)) else None
        cut = h.start() if h else len(before)   # 옵션표(제목 포함)가 시작하는 자리
        # 앞에 동영상·사진·글이 있으면 한 줄 띄움 (맨 앞이면 스토어 상단과의 간격은 detail_html이 띄움)
        prev = "".join(out) + before[:cut]
        gap = SPACER if re.search(r"<(img|video|iframe)\b", prev, re.I) or _text(prev.replace("&nbsp;", " ")) else ""
        if h and style not in ("basic",):   # 제목은 그림의 색 띠(위 머리)로
            title, before = _text(h.group(2)), before[:cut] + gap
        else:
            before = before[:cut] + gap + before[cut:]
        k = len(boxes)
        boxes.append({"title": title, "cards": cards})
        urls = (opt_urls[k] if opt_urls and k < len(opt_urls) else
                [f"#옵션표그림{k + 1}-{j + 1}" for j in range(optimage.count(len(cards)))])
        out.append(before)
        out.append("".join(f'<p style="text-align:center;margin:0;"><img src="{u}" width="100%" style="width:100%;{IMG_BLOCK}"></p>'
                           for u in urls))
        i = end
    html = "".join(out) + html[i:]
    # 세로로 쌓던 flex 묶음(제목 + 옵션표) → 그냥 가운데 정렬 블록 (flex-direction이 지워지면 가로로 붙어 버림)
    return _FLEX_COL.sub(lambda m: f'style={m.group(1)}text-align:center;{m.group(1)}', html), boxes


def naver_safe_layout(html, style="basic", color=None, opt_urls=None):
    """네이버가 지우는 배치 CSS(grid, flex)로 짠 옵션 사진 묶음 → 2열 그림 (표·CSS를 쓰지 않음, optimage 참고)."""
    return _layout(html, style, color or OPTION_COLOR, opt_urls)[0]


def layout_left(html):
    """naver_safe_layout 뒤에도 남은 옵션 사진 묶음 수 (사진 둘 이상인 grid·줄바꿈 flex, 옵션표 모양인데 못 바꾼 표) — 0이 아니면 경고."""
    n = 0
    for m in _TABLE_OPEN.finditer(html):
        e = _table_end(html, m.start())
        if e > 0 and _IMG_TAG.search(html[m.start():e]):
            n += 1
    for m in _DIV_STYLED.finditer(html):
        if _card_box(m.group(2)):
            end = _div_end(html, m.start())
            if len(_IMG_TAG.findall(html[m.end():end if end > 0 else len(html)])) >= 2:
                n += 1
    return n


def mobile_issues(html):
    """네이버 모바일이 HTML 대신 PC 화면 캡처(흐림, '원본보기'를 눌러야 선명)로 보여 주게 만드는 것들."""
    out = []
    for tag, label in (("table", "표(table)"), ("a", "링크(a)"), ("iframe", "iframe")):
        n = len(re.findall(rf"<{tag}\b", html, re.I))
        if n:
            out.append(f"{label} {n}개")
    ext = [u for u in (m.group(2).strip() for t in _IMG_TAG.findall(html) for m in [_SRC.search(t)] if m)
           if u and not u.startswith(("#", "/api/optimg/")) and "pstatic.net" not in u.split("/")[2 if "//" in u else 0]]
    if ext:
        out.append(f"네이버 밖 이미지 {len(ext)}장")
    bg = [u for u in re.findall(r"url\(\s*['\"]?([^)'\"]+)", html) if "pstatic.net" not in u]
    if bg:
        out.append(f"네이버 밖 배경 그림 {len(bg)}개")
    return out


OPTION_STYLES = ("strong", "basic", "a", "b", "c", "d", "e")   # 예전 'original'(원본 그대로)은 basic(원본 모양)으로 · a~e = 시안 A~E


PC_WIDTH = 860   # 네이버 PC 상세 폭 (스토어 상단·하단 그림도 이 폭)
_DIV_OPEN = re.compile(r"<div\b[^>]*>", re.I)


def fit_width(html):
    """원본이 상세 폭을 780px 등으로 줄여 둔 묶음 → 네이버 PC 상세 폭(860px)에 꽉 차게, 가운데로.
    그대로 두면 PC에서 스토어 상단(860px)보다 좁고 왼쪽에 붙어 보인다 (휴대폰은 화면이 더 좁아 상관없음)."""
    def tag(m):
        def mw(x):
            return f"max-width: {PC_WIDTH}px; margin: 0 auto" if 600 <= int(x.group(1)) < PC_WIDTH else x.group(0)
        return re.sub(r"max-width\s*:\s*(\d+)px", mw, m.group(0), flags=re.I)
    return _DIV_OPEN.sub(tag, html)


UNIT_PRICE_PATH = os.path.join(config.DATA_DIR, "unit_price_categories.json")
_unit_price = {"mtime": None, "ids": set()}


def unit_price_categories():
    """가격표시제(단위가격) 대상으로 확인된 네이버 카테고리 번호들 (등록·수정 때 네이버가 알려 준 것)."""
    try:
        mt = os.path.getmtime(UNIT_PRICE_PATH)
    except OSError:
        return set()
    if _unit_price["mtime"] != mt:
        try:
            with open(UNIT_PRICE_PATH, encoding="utf-8") as f:
                _unit_price["ids"] = {str(x) for x in json.load(f)}
        except (OSError, ValueError):
            _unit_price["ids"] = set()
        _unit_price["mtime"] = mt
    return _unit_price["ids"]


def remember_unit_price(category_id):
    if not category_id or str(category_id) in unit_price_categories():
        return
    ids = sorted(unit_price_categories() | {str(category_id)})
    os.makedirs(os.path.dirname(UNIT_PRICE_PATH), exist_ok=True)
    with open(UNIT_PRICE_PATH, "w", encoding="utf-8") as f:
        json.dump(ids, f)


def set_no_unit_price(body):
    """가격표시제 대상 카테고리: '단위가격 사용 안 함'으로 (엑셀에 총 용량이 없어 단위가격을 계산할 수 없음).
    이미 값이 있으면 그대로 두고 False."""
    da = body.setdefault("originProduct", {}).setdefault("detailAttribute", {})
    if (da.get("unitCapacity") or {}).get("unitPriceYn") is not None:
        return False
    da["unitCapacity"] = {"unitPriceYn": False}
    return True


def detail_source(row, cfg):
    """올릴 상세의 출발점: 엑셀 상세 − 방문 알림·추적 그림 − http(보안 아님) 동영상 − (설정이면) 동영상 전부, 폭은 PC 860px에 맞춤,
    표로 만든 옵션표는 옵션 사진 묶음으로(→ 옵션표 그림), 사진 사이 빈 줄은 정리."""
    html = row.get("상세설명") or f"<p>{row.get('상품명') or ''}</p>"
    html = re.sub(r"<[^>]*$", "", html)   # 엑셀 칸 글자 수 제한으로 태그 중간에서 잘린 꼬리
    html = fit_width(strip_trackers(html))
    html = tighten(se_option_tables(html))   # 표로 만든 옵션표도 옵션표로 · 사진 사이 빈 줄 정리
    if cfg.get("detail_video") == "remove":
        html = VIDEO_RE.sub("", html)
    else:   # 네이버(https) 화면에서 http 동영상은 막히거나 안 열림
        html = VIDEO_RE.sub(lambda m: "" if re.search(r"""src\s*=\s*["']?http://""", m.group(0), re.I) else m.group(0), html)
    return html


def option_boxes(row, cfg, store=None):
    """올릴 때 그림으로 만들 옵션 사진 묶음들 (detail_html과 같은 순서)."""
    style, color, _ = option_look(cfg, store)
    return _layout(detail_source(row, cfg), style, color, None)[1]


MEDIA_RE = re.compile(r"<(video|iframe)\b[^>]*?(?:/>|>.*?</\1\s*>)", re.I | re.S)
_CENTER_OPEN = re.compile(r"<(p|div|center)\b([^>]*)>\s*$", re.I)
_CENTER_CLOSE = re.compile(r"^\s*</(p|div|center)\s*>", re.I)
MEDIA_STYLE = "display:block;margin:0 auto;max-width:100%;"


def _media_style(tag):
    """동영상 태그 자체도 가운데로 (display:block + margin auto, 폭은 화면 안)."""
    head_end = tag.find(">")
    head = tag[:head_end]
    m = re.search(r"""\bstyle\s*=\s*(["'])(.*?)\1""", head, re.I | re.S)
    if m:
        st = m.group(2)
        if re.search(r"margin\s*:\s*0\s+auto", st, re.I) and re.search(r"display\s*:\s*block", st, re.I):
            return tag
        st = (st.rstrip("; ") + ";" if st.strip() else "") + MEDIA_STYLE
        head = head[:m.start()] + f'style={m.group(1)}{st}{m.group(1)}' + head[m.end():]
    else:
        head = re.sub(r"^<(video|iframe)\b", lambda x: f'<{x.group(1)} style="{MEDIA_STYLE}"', head, flags=re.I)
    return head + tag[head_end:]


def center_media(html):
    """상세의 동영상(video·iframe)을 가운데로: 이미 가운데 정렬 블록 하나만 감싸고 있으면 그대로(태그만 가운데),
    아니면 이미지처럼 <p style="text-align:center"> 로 감싼다 — 네이버가 남기는 text-align·margin auto만 씀."""
    html = str(html or "")
    out, i = [], 0
    for m in MEDIA_RE.finditer(html):
        before = html[i:m.start()]
        tag = _media_style(m.group(0))
        o = _CENTER_OPEN.search(before)
        c = _CENTER_CLOSE.search(html[m.end():])
        centered = bool(o and c and o.group(1).lower() == c.group(1).lower()
                        and (o.group(1).lower() == "center" or re.search(r"text-align\s*:\s*center", o.group(2), re.I)))
        out.append(before)
        out.append(tag if centered else f'<p style="text-align:center;margin:0;">{tag}</p>')
        i = m.end()
    return "".join(out) + html[i:]


def detail_html(row, cfg, url_map, top="", bottom="", store=None, opt_urls=None):
    """상세설명 (이미지 주소를 네이버 주소로). top/bottom: 스토어 템플릿 상단·하단 HTML을 앞뒤에 붙인다.
    방문 알림은 지우고, 옵션 사진 묶음은 어떤 경우에도 2열 그림으로 (opt_urls: 엔진이 그려 올린 주소).
    store: 스토어 템플릿의 옵션표 모양·색 (비우면 설정 공통값)."""
    style, color, _ = option_look(cfg, store)
    html = center_media(_layout(detail_source(row, cfg), style, color, opt_urls)[0])   # 동영상도 이미지처럼 가운데

    def repl(m):
        src = m.group(3).strip()
        key = "https:" + src if src.startswith("//") else src
        return f"{m.group(1)}{m.group(2)}{url_map.get(key, src)}{m.group(2)}"
    # 스토어 상단·하단과 상세 사이 한 줄 (붙어 보이지 않게)
    return (top + SPACER if top else "") + IMG_SRC_RE.sub(repl, html) + (SPACER + bottom if bottom else "")


def certification_exclude(certs):
    out = {}
    for c in certs or []:
        if not isinstance(c, dict):
            continue
        if c.get("kcCertifiedProductExclusionType"):
            out["kcCertifiedProductExclusionYn"] = c["kcCertifiedProductExclusionType"]
        if c.get("kcExemptionType"):
            out["kcExemptionType"] = c["kcExemptionType"]
        for k in ("childCertifiedProductExclusionYn", "greenCertifiedProductExclusionYn"):
            if k in c:
                out[k] = c[k]
    return out


def round_up(price, unit=100):
    """가격은 항상 100원(unit) 단위로 올림. 음수(옵션 할인)는 0 쪽으로 (예: -1,550 → -1,500)."""
    unit = max(1, int(unit or 100))
    return -((-int(price)) // unit) * unit


def adjusted_price(price, cfg, store_pct=0):
    """손님 가격 = 기준 가격 × (1 + 스토어 가격 차이 %), 100원 단위 올림."""
    unit = max(1, to_int(cfg.get("price_round"), 100))
    if price <= 0:
        return price
    p = price * (1 + float(store_pct or 0) / 100)
    return max(unit, round_up(math.ceil(p - 1e-9), unit))


def base_for(target, cfg, store):
    """그 스토어 손님 가격을 target으로 받고 싶을 때의 기준 가격 (스토어 가격 차이 %로 거꾸로 계산).
    가격 차이 0%면 기준 가격 = 손님 가격. 결과로 그 스토어 손님 가격이 정확히 target(100원 단위 올림)이 되는 값."""
    unit = max(1, to_int(cfg.get("price_round"), 100))
    target = round_up(int(target or 0), unit)
    pct = float((store or {}).get("tpl_price_pct") or 0)
    if target <= 0 or not pct:
        return target
    base = int(target / (1 + pct / 100))
    for b in (base, base + 1, base - 1, base + 2):   # 반올림 차이 보정
        if b > 0 and adjusted_price(b, cfg, pct) == target:
            return b
    return max(1, base)


def stock_qty(row, cfg):
    """등록 재고: 설정 stock_fixed(기본 1,000)가 있으면 늘 그 수, 0이면 엑셀 재고수."""
    fixed = to_int(cfg.get("stock_fixed"), 0)
    return fixed if fixed > 0 else to_int(row.get("재고수"), 999)


def display_prices(final, pct, unit=100):
    """표시 할인율: (네이버 판매가, 할인 금액, 손님 가격). 손님 가격은 늘 final 그대로(1원도 안 바꿈).
    판매가 = final ÷ (1 - pct%)를 unit(100원) 단위로 올린 값, 할인 금액 = 판매가 - final → 할인율은 pct%에 아주 가깝게(조금 위).
    final이 10원 단위가 아니면 10원 단위로 올린다(네이버 판매가 규칙)."""
    p = float(pct or 0) / 100
    final = int(final or 0)
    if final <= 0:
        return final, 0, final
    final = round_up(final, 10)
    if not 0 < p < 1:
        return final, 0, final
    shown = round_up(math.ceil(final / (1 - p) - 1e-9), unit)
    if shown <= final:
        return final, 0, final
    return shown, shown - final, final


def display_prices_exact(final, pct, unit=100):
    """(예전 규칙) 할인율을 정확히 pct%로 맞추느라 손님 가격이 final보다 최대 수백 원 높아지던 계산. 예전에 올린 상품 화면 표시용."""
    from fractions import Fraction
    p = Fraction(str(pct or 0)) / 100
    if final <= 0 or not 0 < p < 1:
        return final, 0, final
    shown = round_up(math.ceil(Fraction(final) / (1 - p)), unit)
    for _ in range(10000):
        off = shown * p
        if off.denominator == 1 and off % unit == 0:
            return shown, int(off), shown - int(off)
        shown += unit
    off = round_up(math.ceil(shown * p), unit)   # 못 맞추면 할인 금액만 올림 (거의 없음)
    return shown, off, shown - off


def store_price(base, cfg, store):
    """기준 가격 → 이 스토어 손님 가격 = 기준 가격 × (1 + 스토어 가격 차이 %), 100원 올림."""
    return adjusted_price(base, cfg, (store or {}).get("tpl_price_pct"))


def option_add_price(add, cfg, store):
    """옵션 추가금(원본 값) → 이 스토어 옵션 추가금 = 추가금 × (1 + 스토어 가격 차이 %), 100원 단위 (+는 올림, -는 0 쪽으로).
    허용 범위를 넘어도 깎지 않는다 (역마진 방지 — 범위 검사는 원본 검사·네이버 오류로 알림)."""
    unit = max(1, to_int(cfg.get("price_round"), 100))
    add = to_int(add)
    if not add:
        return 0
    p = add * (1 + float((store or {}).get("tpl_price_pct") or 0) / 100)
    return round_up(math.ceil(p - 1e-9) if p > 0 else int(p), unit)


def store_discount_pct(store, cfg):
    """스토어 표시 할인율: 템플릿에 넣었으면 그 값(0이면 할인 없음), 비우면 설정 기본값(30)."""
    v = (store or {}).get("tpl_discount_pct")
    return float(cfg.get("display_discount_pct", 30) if v is None else v or 0)


def build_body(row, cfg, category_id, url_map=None, name=None, price=None, as_phone=None, seller_code=None,
               importer=None, store=None, opt_urls=None):
    """url_map: 원본 이미지 주소 → 네이버 이미지 주소. 없는 주소는 원본 그대로 쓴다.
    name / price / as_phone / seller_code: 스토어별로 바꿔 쓸 값 (없으면 엑셀 값).
    store: 스토어 템플릿 (tpl_top_html·tpl_bottom_html·tpl_customs·tpl_discount_pct). 상단·하단 이미지는
           엔진이 네이버 주소로 바꾼 HTML을 store['_tpl_top']·['_tpl_bottom']에 넣어 준다."""
    store = store or {}
    url_map = url_map or {}
    errors, _ = validate(row, cfg)
    if errors:
        raise ConvertError(" / ".join(errors))

    base_price = net_price(row)   # 판매가 - 할인가 (엑셀 할인가는 이미 빼서 기준 가격으로 씀)
    name = str(name or row["상품명"]).strip()
    unit = to_int(cfg.get("price_round"), 100) or 100
    # 손님 가격 (할인·옵션 계산 기준). 정해 준 가격(기준 가격 × 스토어 가격 차이 %)은 그대로(10원 단위만 맞춤)
    sale_price = round_up(price, 10) if price else round_up(base_price, unit)
    images = [url_map.get(u, u) for u in thumbnails(row)[:10]]

    fee = to_int(row.get("배송비"))
    delivery_fee = {"deliveryFeeType": "FREE"} if fee == 0 else {
        "deliveryFeeType": "PAID", "baseFee": fee, "deliveryFeePayType": "PREPAID"}

    model, brand, maker = info_fields(row, cfg)
    phone = as_phone or cfg.get("as_phone") or ""

    detail = {
        "naverShoppingSearchInfo": _strip_empty({"modelName": model, "brandName": brand,
                                                 "manufacturerName": maker}),
        "afterServiceInfo": {"afterServiceTelephoneNumber": phone,
                             "afterServiceGuideContent": cfg.get("as_guide") or REF},
        "originAreaInfo": origin_info(row.get("원산지"), cfg, importer),
        "minorPurchasable": True,
        "productInfoProvidedNotice": {
            "productInfoProvidedNoticeType": "ETC",
            "etc": {"returnCostReason": REF, "noRefundReason": REF, "qualityAssuranceStandard": REF,
                    "compensationProcedure": REF, "troubleShootingContents": REF,
                    "itemName": name[:50], "modelName": model, "manufacturer": maker,
                    "customerServicePhoneNumber": phone},
        },
    }
    claim = {"returnDeliveryFee": to_int(cfg.get("return_fee"), 5000),
             "exchangeDeliveryFee": to_int(cfg.get("exchange_fee"), 10000)}
    if store.get("tpl_ship_addr"):     # 출고지 (판매자센터 주소록 번호, 없으면 판매자센터 기본 출고지)
        claim["shippingAddressId"] = int(store["tpl_ship_addr"])
    if store.get("tpl_return_addr"):   # 반품·교환지
        claim["returnAddressId"] = int(store["tpl_return_addr"])
    customs = config.customs_code(store.get("tpl_customs") or cfg.get("customs_tax_type"))
    if customs:   # 해외 출고지 상품은 관부가세 항목이 필수
        detail["customsTaxType"] = customs
    code = seller_code or row.get("판매자코드")
    if code:
        detail["sellerCodeInfo"] = {"sellerManagementCode": str(code)}
    if str(category_id) in unit_price_categories():   # 가격표시제 대상 카테고리 (한 번 확인된 것)
        detail["unitCapacity"] = {"unitPriceYn": False}
    o = options(row)
    if o:
        o = copy.deepcopy(o)
        for c in o.get("optionCombinations") or []:
            if c.get("price"):   # 옵션 추가금에도 스토어 가격 차이 % (100원 단위)
                c["price"] = option_add_price(c["price"], cfg, store)
        fixed = to_int(cfg.get("stock_fixed"), 0)
        if fixed > 0:   # 재고는 상품·옵션 모두 늘 같은 수 (엑셀 값과 상관없이)
            for key in ("optionCombinations", "optionStandards"):
                for x in o.get(key) or []:
                    if isinstance(x, dict):
                        x["stockQuantity"] = fixed
        detail["optionInfo"] = _strip_empty(o)
    t = tags(row)
    if t:
        detail["seoInfo"] = {"sellerTags": [{"text": x} for x in t[:10]]}
    excl = certification_exclude(row.get("인증"))
    if row.get("_chem") == "tool":   # 생활화학 판정 '물건' → 생활화학/살생물제 인증 대상 아님
        excl["chemicalCertifiedProductExclusionYn"] = True
    if excl:
        detail["certificationTargetExcludeContent"] = excl

    origin = {
        "statusType": "SALE" if (row.get("판매상태") or "판매중") == "판매중" else "SUSPENSION",
        "saleType": "NEW",
        "leafCategoryId": category_id,
        "name": name[:100],
        "detailContent": detail_html(row, cfg, url_map, store.get("_tpl_top", store.get("tpl_top_html", "")),
                                     store.get("_tpl_bottom", store.get("tpl_bottom_html", "")), store, opt_urls),
        "images": {"representativeImage": {"url": images[0]}},
        "salePrice": sale_price,
        "stockQuantity": stock_qty(row, cfg),
        "deliveryInfo": {
            "deliveryType": "DELIVERY",
            "deliveryAttributeType": "NORMAL",
            "deliveryCompany": cfg.get("delivery_company") or "CJGLS",
            "deliveryFee": delivery_fee,
            "claimDeliveryInfo": claim,
        },
        "detailAttribute": detail,
    }
    if images[1:]:
        origin["images"]["optionalImages"] = [{"url": u} for u in images[1:]]

    # 엑셀 할인가는 기준 가격(net_price)에 이미 빼서 반영했으므로 엑셀 할인가로는 즉시할인을 걸지 않는다.
    # 표시 할인율(기본 30%, 스토어 템플릿에서 바꿈): 할인율이 정확히 그 %가 되도록 판매가를 올리고 그만큼 '금액으로' 즉시할인.
    shown, off, _ = display_prices(sale_price, store_discount_pct(store, cfg), unit)
    if off > 0:
        origin["salePrice"] = shown
        origin["customerBenefit"] = {"immediateDiscountPolicy": {
            "discountMethod": {"value": off, "unitType": "WON"}}}

    body = {
        "originProduct": origin,
        "smartstoreChannelProduct": {"naverShoppingRegistration": True,
                                     "channelProductDisplayStatusType": "ON"},
    }
    return deep_merge(body, copy.deepcopy(cfg.get("extra") or {}))
