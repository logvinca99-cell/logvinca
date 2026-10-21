"""엑셀 한 줄(상품 사전) → 검사 결과 / 등록 요청 본문.

엑셀 열 이름이 바뀌면 이 파일만 고치면 된다.
"""

import copy
import hashlib
import math
import re

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


def summary(row, cfg):
    """목록 화면에 보여줄 값."""
    cat = str(row.get("카테고리") or "").strip()
    th = thumbnails(row)
    return {
        "row_key": str(row.get("id") or ""),
        "source_key": source_fingerprint(row),
        "seller_code": str(row.get("판매자코드") or ""),
        "name": str(row.get("상품명") or "").strip(),
        "price": to_int(row.get("판매가")),
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
    price = to_int(row.get("판매가"))
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
    elif categories is not None and cat not in categories:
        errors.append(f"카테고리 '{cat}'를 스마트스토어에서 찾지 못했습니다.")
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
    if "<video" in (row.get("상세설명") or "").lower():
        warnings.append("상세설명에 동영상이 있습니다. 동영상은 네이버 서버에 올릴 수 없어 원래 주소 그대로 둡니다"
                        if cfg.get("detail_video") != "remove" else "상세설명의 동영상은 지우고 등록합니다.")
    if len(thumbnails(row)) > 10:
        warnings.append("썸네일이 10장을 넘어 앞 10장만 등록됩니다.")
    return errors, warnings


# ───────────────────────── 등록 요청

def detail_html(row, cfg, url_map, top="", bottom=""):
    """상세설명 (이미지 주소를 네이버 주소로). top/bottom: 스토어 템플릿 상단·하단 HTML을 앞뒤에 붙인다."""
    html = row.get("상세설명") or f"<p>{row.get('상품명') or ''}</p>"
    if cfg.get("detail_video") == "remove":
        html = VIDEO_RE.sub("", html)

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


def adjusted_price(price, key, cfg, store_pct=0):
    """원본가를 ±price_jitter_pct% 안에서 바꾼다. key(상품+스토어)가 같으면 항상 같은 값. 100원 단위 올림.
    store_pct: 스토어 템플릿의 가격 조정 % (예: 10이면 원본가의 110% 기준)."""
    pct = float(cfg.get("price_jitter_pct") or 0)
    unit = max(1, to_int(cfg.get("price_round"), 100))
    if price <= 0:
        return price
    h = int(hashlib.sha1(str(key).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF  # 0~1
    p = price * (1 + float(store_pct or 0) / 100) * (1 + (h * 2 - 1) * pct / 100)
    return max(unit, round_up(math.ceil(p), unit))


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

    base_price = to_int(row.get("판매가"))
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
    customs = str(store.get("tpl_customs") or cfg.get("customs_tax_type") or "").strip()
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
                                     store.get("_tpl_bottom", store.get("tpl_bottom_html", ""))),
        "images": {"representativeImage": {"url": images[0]}},
        "salePrice": sale_price + round_up(bait or 0, unit),
        "stockQuantity": to_int(row.get("재고수"), 999),
        "deliveryInfo": {
            "deliveryType": "DELIVERY",
            "deliveryAttributeType": "NORMAL",
            "deliveryCompany": cfg.get("delivery_company") or "CJGLS",
            "deliveryFee": delivery_fee,
            "claimDeliveryInfo": {"returnDeliveryFee": to_int(cfg.get("return_fee"), 5000),
                                  "exchangeDeliveryFee": to_int(cfg.get("exchange_fee"), 10000)},
        },
        "detailAttribute": detail,
    }
    if images[1:]:
        origin["images"]["optionalImages"] = [{"url": u} for u in images[1:]]

    discount = to_int(row.get("할인가"))
    disc_pct = float(store.get("tpl_discount_pct") or 0)
    if 0 < disc_pct < 90:
        # 스토어 표시 할인율: 지금 가격(price)이 할인된 최종가가 되도록 판매가를 올리고 그만큼 즉시할인 (100원 단위)
        shown = round_up(math.ceil(sale_price / (1 - disc_pct / 100)), unit)
        off = shown - sale_price
        if off > 0:
            origin["salePrice"] = shown + round_up(bait or 0, unit)
            origin["customerBenefit"] = {"immediateDiscountPolicy": {
                "discountMethod": {"value": off, "unitType": "WON"}}}
    elif 0 < discount < base_price:
        # 엑셀의 할인가는 '할인된 판매가'로 본다. 가격을 바꿨으면 할인율이 같도록, 도둑방지 전 가격 기준으로.
        # 할인된 가격도 100원 단위 올림 → 할인 금액도 100원 단위.
        final = round_up(math.ceil(sale_price * discount / base_price), unit)
        off = sale_price - final
        if 0 < off < sale_price:
            origin["customerBenefit"] = {"immediateDiscountPolicy": {
                "discountMethod": {"value": off, "unitType": "WON"}}}

    body = {
        "originProduct": origin,
        "smartstoreChannelProduct": {"naverShoppingRegistration": True,
                                     "channelProductDisplayStatusType": "ON"},
    }
    return deep_merge(body, copy.deepcopy(cfg.get("extra") or {}))
