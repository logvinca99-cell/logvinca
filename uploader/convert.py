"""엑셀 한 줄(상품 사전) → 검사 결과 / 등록 요청 본문.

엑셀 열 이름이 바뀌면 이 파일만 고치면 된다.
"""

import copy
import hashlib
import math
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
    html = row.get("상세설명") or ""
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
    if any(o.get(k) for k in ("optionCombinations", "optionSimple", "optionCustom", "optionStandards")):
        return o
    return None


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
    return [u for u in detail_images(row) if u not in thumbs and not (keep and is_naver_image(u))]


def images_to_upload(row, cfg):
    """네이버 서버에 올릴 원본 이미지 주소 목록 (썸네일 앞, 중복 없음)."""
    return thumbnails(row)[:10] + detail_images_to_upload(row, cfg)


def net_price(row):
    """원본가 = 엑셀 판매가(R열) - 할인가(S열). 할인가는 '할인 금액'이다 (할인된 가격이 아님).
    할인가가 없거나 판매가보다 크면 판매가 그대로. 프로그램은 이 금액만 원본가로 쓴다."""
    price, off = to_int(row.get("판매가")), to_int(row.get("할인가"))
    return price - off if 0 < off < price else price


def summary(row, cfg):
    """목록 화면에 보여줄 값."""
    cat = str(row.get("카테고리") or "").strip()
    th = thumbnails(row)
    return {
        "row_key": str(row.get("id") or ""),
        "source_key": source_fingerprint(row),
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
    if d and layout_left(naver_safe_layout(d)):
        warnings.append("상세에 2열 표로 바꾸지 못한 옵션 사진 묶음이 있습니다 (네이버에서 한 줄에 하나씩 보일 수 있음) — 이 원본을 알려 주세요")
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


def _clean_img(tag):
    tag = re.sub(r"""\s(?:style|width|height)\s*=\s*(["']).*?\1""", "", tag, flags=re.S)
    return tag.replace("<img", '<img width="100%" style="width:100%;height:auto;display:block;margin:0 auto;"', 1)


def _cards(inner):
    """묶음 안의 칸들 → [(사진 HTML, 이름)]. 칸이 div가 아니면 사진 하나씩 한 칸."""
    out = []
    for c in _children(inner):
        imgs = "".join(_clean_img(t) for t in _IMG_TAG.findall(c))
        cap = _text(_IMG_TAG.sub("", c))
        if imgs or cap:
            out.append((imgs, cap))
    return out or [(_clean_img(t), "") for t in _IMG_TAG.findall(inner)]


def _cards_table(cards, strong, color):
    """칸들 → 늘 2열 표 (휴대폰에서도 2열). 사진 줄과 이름 줄을 나눠 사진 크기가 달라도 이름이 나란히 맞고,
    사진·이름 칸은 테두리로 한 덩어리. 칸이 홀수면 마지막 줄 오른쪽은 비움."""
    if strong:
        bw, bc, bg = 2, color, "#F5F6F8"
        cap_css = "padding:12px 6px;margin:0;font-size:16px;font-weight:700;color:#111111;line-height:1.4;"
    else:   # 원본 모양 (얇은 회색 테두리, 보통 굵기)
        bw, bc, bg = 1, "#EAECF0", "#FFFFFF"
        cap_css = "padding:8px;margin:0;font-weight:500;color:#111111;line-height:1.4;"
    line = f"{bw}px solid {bc}"

    def td(css, inner, valign):
        return (f'<td width="48%" align="center" valign="{valign}" bgcolor="{bg}" style="width:48%;{css}background-color:{bg};'
                f'padding:0;text-align:center;vertical-align:{valign};">{inner}</td>')
    gap = '<td width="4%" style="width:4%;padding:0;"></td>'
    blank = '<td width="48%" style="width:48%;padding:0;"></td>'
    rows = []
    for r in range(0, len(cards), 2):
        if r:
            rows.append('<tr><td colspan="3" height="16" style="height:16px;padding:0;"></td></tr>')
        pair = cards[r:r + 2]
        tops = [td(f"border-top:{line};border-left:{line};border-right:{line};", imgs, "middle") for imgs, _ in pair]
        bots = [td(f"border-bottom:{line};border-left:{line};border-right:{line};",
                   f'<p style="{cap_css}">{cap or "&nbsp;"}</p>', "top") for _, cap in pair]
        if len(pair) == 1:
            tops.append(blank)
            bots.append(blank)
        rows.append("<tr>" + gap.join(tops) + "</tr>")
        rows.append("<tr>" + gap.join(bots) + "</tr>")
    return ('<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="width:100%;border-collapse:collapse;table-layout:fixed;margin:12px 0;">' + "".join(rows) + "</table>")


def naver_safe_layout(html, style="basic", color=None):
    """네이버 상세 편집기가 지우는 CSS(grid, flex-wrap, flex-direction)로 짠 옵션 사진 묶음을 늘 2열 표로 바꾼다.
    그대로 올리면 옵션 사진이 한 줄에 하나씩 쌓이고 '옵션 설명' 제목이 왼쪽으로 밀린다.
    style='strong': 바로 위 제목(h1~h4)을 color 띠로, 옵션 이름을 굵고 크게, 칸 테두리를 color로.
    그 밖(basic)은 원본과 같은 얇은 테두리·글씨. 네이버가 지우지 않는 표·글자색·배경색·테두리만 쓰고
    색·너비는 bgcolor·width 속성으로도 같이 넣는다."""
    strong = style == "strong"
    color = color if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(color or "")) else OPTION_COLOR
    out, i = [], 0
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
        before = html[i:m.start()]
        h = _HEAD_BEFORE.search(before) if strong else None
        if h and _text(h.group(2)):   # 바로 위 제목 → 색 띠 (옵션 제목이면 칸 수도)
            title = _text(h.group(2))
            count = f'<span style="font-size:14px;color:#FFFFFF;"> &nbsp;총 {len(cards)}종</span>' if "옵션" in title else ""
            before = before[:h.start()] + (
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;">'
                f'<tr><td bgcolor="{color}" align="center" style="background-color:{color};padding:14px 8px;text-align:center;">'
                f'<span style="font-size:20px;font-weight:700;color:#FFFFFF;">{title}</span>{count}</td></tr></table>')
        out.append(before)
        out.append(_cards_table(cards, strong, color))
        i = end
    html = "".join(out) + html[i:]
    # 세로로 쌓던 flex 묶음(제목 + 옵션표) → 그냥 가운데 정렬 블록 (flex-direction이 지워지면 가로로 붙어 버림)
    return _FLEX_COL.sub(lambda m: f'style={m.group(1)}text-align:center;{m.group(1)}', html)


def layout_left(html):
    """naver_safe_layout 뒤에도 남은 옵션 사진 묶음 수 (사진 둘 이상인 grid·줄바꿈 flex) — 0이 아니면 경고."""
    n = 0
    for m in _DIV_STYLED.finditer(html):
        if _card_box(m.group(2)):
            end = _div_end(html, m.start())
            if len(_IMG_TAG.findall(html[m.end():end if end > 0 else len(html)])) >= 2:
                n += 1
    return n


OPTION_STYLES = ("strong", "basic")   # 예전 'original'(원본 그대로)은 basic(원본 모양 2열 표)으로


def detail_html(row, cfg, url_map, top="", bottom="", opt_style="", opt_color=""):
    """상세설명 (이미지 주소를 네이버 주소로). top/bottom: 스토어 템플릿 상단·하단 HTML을 앞뒤에 붙인다.
    옵션표처럼 네이버가 지우는 CSS(grid·flex 세로 쌓기)로 짠 부분은 표로 바꿔 올린다.
    opt_style·opt_color: 스토어 템플릿의 옵션표 모양(strong 강조 / basic 원본 모양)·색 (비우면 설정 공통값)."""
    html = row.get("상세설명") or f"<p>{row.get('상품명') or ''}</p>"
    if cfg.get("detail_video") == "remove":
        html = VIDEO_RE.sub("", html)
    # 옵션 사진 묶음은 어떤 모양이든 늘 2열 표로 (그대로 두면 네이버에서 한 줄에 하나씩 쌓임)
    html = naver_safe_layout(html, opt_style or cfg.get("option_table_style") or "strong",
                             opt_color or cfg.get("option_table_color"))

    def repl(m):
        src = m.group(3).strip()
        key = "https:" + src if src.startswith("//") else src
        return f"{m.group(1)}{m.group(2)}{url_map.get(key, src)}{m.group(2)}"
    return (top or "") + IMG_SRC_RE.sub(repl, html) + (bottom or "")


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


def adjusted_price(price, key, cfg, store_pct=0, jitter=None):
    """스토어에 올릴 최종 가격 (할인 뒤 손님이 내는 값). 100원 단위 올림.
    1) 원본가(판매가 - 할인가) × (1 + 스토어 가격 조정 %)
    2) 스토어 템플릿의 흔들기 범위(jitter=(최소%, 최대%), 예: (-3, 3)) 안에서 상품마다 다르게. key(상품+스토어)가 같으면 늘 같은 값.
       흔들기를 넣은 스토어는 원본가와 똑같은 가격이 나오지 않게 한 단위(100원) 비킨다."""
    unit = max(1, to_int(cfg.get("price_round"), 100))
    if price <= 0:
        return price
    lo, hi = (jitter or (0, 0))
    lo, hi = float(lo or 0), float(hi or 0)
    if lo > hi:
        lo, hi = hi, lo
    h = int(hashlib.sha1(str(key).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF  # 0~1
    p = price * (1 + float(store_pct or 0) / 100) * (1 + (lo + (hi - lo) * h) / 100)
    out = max(unit, round_up(math.ceil(p), unit))
    if (lo or hi) and out == round_up(price, unit):
        out = out - unit if hi <= 0 and out - unit > 0 else out + unit
    return out


def stock_qty(row, cfg):
    """등록 재고: 설정 stock_fixed(기본 1,000)가 있으면 늘 그 수, 0이면 엑셀 재고수."""
    fixed = to_int(cfg.get("stock_fixed"), 0)
    return fixed if fixed > 0 else to_int(row.get("재고수"), 999)


def display_prices(final, pct, unit=100):
    """표시 할인율: 손님이 내는 값이 final 이상이고, 할인율이 정확히 pct%가 되는 (판매가, 할인 금액, 최종가).
    판매가·할인 금액 모두 unit(100원) 단위. 30%면 판매가가 1,000원 단위가 되어 최종가가 final보다 조금(최대 수백 원) 높을 수 있다."""
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


def store_price(net, key, cfg, store):
    """원본가 → 이 스토어에 올릴 최종 가격 (스토어 템플릿의 가격 조정 %·흔들기 범위, 비우면 설정 기본 범위)."""
    store = store or {}
    lo = store.get("tpl_jitter_min")
    hi = store.get("tpl_jitter_max")
    lo = cfg.get("price_jitter_min", -3) if lo is None else lo
    hi = cfg.get("price_jitter_max", 3) if hi is None else hi
    return adjusted_price(net, key, cfg, store.get("tpl_price_pct"), (lo, hi))


def store_discount_pct(store, cfg):
    """스토어 표시 할인율: 템플릿에 넣었으면 그 값(0이면 할인 없음), 비우면 설정 기본값(30)."""
    v = (store or {}).get("tpl_discount_pct")
    return float(cfg.get("display_discount_pct", 30) if v is None else v or 0)


def build_body(row, cfg, category_id, url_map=None, name=None, price=None, as_phone=None, seller_code=None, bait=0,
               importer=None, store=None):
    """url_map: 원본 이미지 주소 → 네이버 이미지 주소. 없는 주소는 원본 그대로 쓴다.
    name / price / as_phone / seller_code: 스토어별로 바꿔 쓸 값 (없으면 엑셀 값).
    bait: 도둑방지로 판매가에 더할 금액. 할인 금액·옵션가는 도둑방지 전 가격(price) 기준으로 정한다.
    store: 스토어 템플릿 (tpl_top_html·tpl_bottom_html·tpl_customs·tpl_discount_pct). 상단·하단 이미지는
           엔진이 네이버 주소로 바꾼 HTML을 store['_tpl_top']·['_tpl_bottom']에 넣어 준다."""
    store = store or {}
    url_map = url_map or {}
    errors, _ = validate(row, cfg)
    if errors:
        raise ConvertError(" / ".join(errors))

    base_price = net_price(row)   # 판매가 - 할인가 (엑셀 할인가는 이미 빼서 원본가로 씀)
    name = str(name or row["상품명"]).strip()
    unit = to_int(cfg.get("price_round"), 100) or 100
    sale_price = round_up(price or base_price, unit)   # 도둑방지 전 가격 (할인·옵션 계산 기준)
    images = [url_map.get(u, u) for u in thumbnails(row)[:10]]

    fee = to_int(row.get("배송비"))
    delivery_fee = {"deliveryFeeType": "FREE"} if fee == 0 else {
        "deliveryFeeType": "PAID", "baseFee": fee, "deliveryFeePayType": "PREPAID"}

    model = row.get("모델명") or REF
    brand = row.get("브랜드") or ""
    maker = row.get("제조사") or brand or REF
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
    o = options(row)
    if o:
        o = copy.deepcopy(o)
        for c in o.get("optionCombinations") or []:
            if c.get("price"):
                c["price"] = round_up(to_int(c["price"]), unit)   # 옵션 추가금도 100원 단위 올림
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
    if excl:
        detail["certificationTargetExcludeContent"] = excl

    origin = {
        "statusType": "SALE" if (row.get("판매상태") or "판매중") == "판매중" else "SUSPENSION",
        "saleType": "NEW",
        "leafCategoryId": category_id,
        "name": name[:100],
        "detailContent": detail_html(row, cfg, url_map, store.get("_tpl_top", store.get("tpl_top_html", "")),
                                     store.get("_tpl_bottom", store.get("tpl_bottom_html", "")),
                                     store.get("tpl_opt_style") or "", store.get("tpl_opt_color") or ""),
        "images": {"representativeImage": {"url": images[0]}},
        "salePrice": sale_price + round_up(bait or 0, unit),
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

    # 엑셀 할인가는 원본가(net_price)에 이미 빼서 반영했으므로 엑셀 할인가로는 즉시할인을 걸지 않는다.
    # 표시 할인율(기본 30%, 스토어 템플릿에서 바꿈): 할인율이 정확히 그 %가 되도록 판매가를 올리고 그만큼 '금액으로' 즉시할인.
    # 도둑방지는 판매가에만 더한다 → 할인 금액은 그대로라, 원래 가격으로 되돌리면 정확히 그 %.
    shown, off, _ = display_prices(sale_price, store_discount_pct(store, cfg), unit)
    if off > 0:
        origin["salePrice"] = shown + round_up(bait or 0, unit)
        origin["customerBenefit"] = {"immediateDiscountPolicy": {
            "discountMethod": {"value": off, "unitType": "WON"}}}

    body = {
        "originProduct": origin,
        "smartstoreChannelProduct": {"naverShoppingRegistration": True,
                                     "channelProductDisplayStatusType": "ON"},
    }
    return deep_merge(body, copy.deepcopy(cfg.get("extra") or {}))
