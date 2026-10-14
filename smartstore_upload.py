"""엑셀 상품 목록을 네이버 커머스API로 스마트스토어에 등록한다.

엑셀 한 줄이 상품 하나다. 열 이름(상품명, 판매가, 썸네일, 상세설명, 카테고리, 옵션상품 ...)을
커머스API 상품 등록(POST /external/v2/products) 형식으로 바꿔 보낸다.

    python smartstore_upload.py 상품.xlsx --check     # 변환만 하고 등록하지 않음
    python smartstore_upload.py 상품.xlsx --limit 1   # 한 개만 시험 등록
    python smartstore_upload.py 상품.xlsx             # 전체 등록

결과는 upload_result_<엑셀이름>.csv에 남고, 다시 실행하면 등록에 성공한 줄은 건너뛴다.
"""

import argparse
import ast
import base64
import copy
import csv
import json
import os
import re
import sys
import time

import openpyxl
import requests

API = "https://api.commerce.naver.com/external"
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "upload_config.json")
CONFIG_EXAMPLE = os.path.join(HERE, "upload_config.example.json")
CATEGORY_CACHE = os.path.join(HERE, "category_cache.json")
RESULT_FIELDS = ["id", "판매자코드", "상품명", "status", "originProductNo", "channelProductNo", "message", "time"]

# 원산지 글자 → 원산지 코드. 없는 나라는 upload_config.json의 origin_codes에 추가한다.
ORIGIN_CODES = {"중국": "0200037"}


class UploadError(Exception):
    pass


# ───────────────────────── 설정 / 엑셀

def load_config(path=CONFIG_PATH):
    if not os.path.exists(path):
        raise UploadError(f"설정 파일이 없습니다: {path}\n"
                          f"upload_config.example.json을 복사해 이름을 upload_config.json으로 바꾸고 채워 주세요.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_value(v):
    """엑셀 칸의 "['a', 'b']" / "{'k': True}" 같은 글자를 파이썬 값으로 바꾼다."""
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    s = v.strip()
    if not s:
        return None
    if s[0] in "[{":
        for loader in (json.loads, ast.literal_eval):
            try:
                return loader(s)
            except (ValueError, SyntaxError):
                pass
    return s


def read_excel(path):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    out = []
    for r in rows:
        if all(v is None or str(v).strip() == "" for v in r):
            continue
        out.append({h: parse_value(v) for h, v in zip(header, r) if h})
    wb.close()
    return out


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


def strip_empty(d):
    """옵션 정보에서 빈 목록/빈 사전은 빼고 보낸다."""
    return {k: v for k, v in d.items() if v not in ([], {}, None, "")}


# ───────────────────────── API

class Client:
    def __init__(self, client_id, client_secret, log=print):
        if not client_id or not client_secret or "여기에" in client_id:
            raise UploadError("upload_config.json에 client_id / client_secret을 넣어 주세요.")
        self.client_id, self.client_secret, self.log = client_id, client_secret, log
        self.token, self.token_until = None, 0
        self.s = requests.Session()

    def _issue_token(self):
        import bcrypt
        ts = str(int(time.time() * 1000))
        hashed = bcrypt.hashpw(f"{self.client_id}_{ts}".encode(), self.client_secret.encode())
        r = self.s.post(f"{API}/v1/oauth2/token", data={
            "client_id": self.client_id,
            "timestamp": ts,
            "client_secret_sign": base64.b64encode(hashed).decode(),
            "grant_type": "client_credentials",
            "type": "SELF",
        }, timeout=20)
        if r.status_code != 200:
            raise UploadError(f"토큰 발급 실패 ({r.status_code}): {r.text[:300]}\n"
                              f"→ 애플리케이션 ID/시크릿과, 커머스API센터에 이 PC의 IP가 등록됐는지 확인하세요.")
        j = r.json()
        self.token = j["access_token"]
        self.token_until = time.time() + int(j.get("expires_in", 10800)) - 300

    def request(self, method, path, **kw):
        for attempt in range(5):
            if not self.token or time.time() > self.token_until:
                self._issue_token()
            headers = kw.pop("headers", {}) | {"Authorization": f"Bearer {self.token}"}
            r = self.s.request(method, f"{API}{path}", headers=headers, timeout=60, **kw)
            if r.status_code == 401:
                self.token = None
                continue
            if r.status_code == 429 or r.status_code >= 500:
                wait = 2 * (attempt + 1)
                self.log(f"  서버가 잠시 거절함({r.status_code}), {wait}초 후 다시 시도")
                time.sleep(wait)
                continue
            return r
        return r

    def categories(self):
        if os.path.exists(CATEGORY_CACHE) and time.time() - os.path.getmtime(CATEGORY_CACHE) < 7 * 86400:
            with open(CATEGORY_CACHE, encoding="utf-8") as f:
                return json.load(f)
        self.log("카테고리 목록을 받아오는 중...")
        r = self.request("GET", "/v1/categories", params={"last": "true"})
        if r.status_code != 200:
            raise UploadError(f"카테고리 조회 실패 ({r.status_code}): {r.text[:300]}")
        table = {c["wholeCategoryName"]: str(c["id"]) for c in r.json() if c.get("last", True)}
        with open(CATEGORY_CACHE, "w", encoding="utf-8") as f:
            json.dump(table, f, ensure_ascii=False)
        return table

    def upload_images(self, urls):
        """외부 이미지 주소를 내려받아 네이버 이미지 서버에 올리고 새 주소를 돌려준다."""
        files = []
        for i, u in enumerate(urls):
            r = self.s.get(u, timeout=30)
            if r.status_code != 200:
                raise UploadError(f"이미지 내려받기 실패 ({r.status_code}): {u}")
            ext = (re.search(r"\.(jpe?g|png|gif|bmp)(?:\?|$)", u, re.I) or [None, "jpg"])[1].lower()
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            files.append(("imageFiles", (f"img{i}.{ext}", r.content, mime)))
        r = self.request("POST", "/v1/product-images/upload", files=files)
        if r.status_code != 200:
            raise UploadError(f"이미지 업로드 실패 ({r.status_code}): {r.text[:300]}")
        return [im["url"] for im in r.json()["images"]]

    def create_product(self, body):
        r = self.request("POST", "/v2/products", json=body)
        if r.status_code != 200:
            raise UploadError(explain_error(r))
        return r.json()


def explain_error(r):
    try:
        j = r.json()
    except ValueError:
        return f"{r.status_code}: {r.text[:300]}"
    msg = j.get("message", "")
    bad = [f"{x.get('name')}: {x.get('message')}" for x in j.get("invalidInputs", [])]
    return f"{r.status_code} {j.get('code', '')} {msg} " + " / ".join(bad)


# ───────────────────────── 엑셀 한 줄 → 등록 요청

def origin_info(text, cfg):
    text = text or cfg.get("origin_default", "중국")
    country = re.split(r"[(\s]", text)[0]
    codes = ORIGIN_CODES | cfg.get("origin_codes", {})
    if country not in codes:
        raise UploadError(f"원산지 '{text}'의 코드를 모릅니다. upload_config.json의 origin_codes에 추가하세요.")
    info = {"originAreaCode": codes[country], "importer": cfg.get("importer") or "상세페이지 참조"}
    return info


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


def build_body(row, cfg, category_id, images):
    name = str(row.get("상품명") or "").strip()
    if not name:
        raise UploadError("상품명이 비어 있습니다.")
    if not images:
        raise UploadError("썸네일(대표 이미지)이 없습니다.")
    sale_price = to_int(row.get("판매가"))
    if sale_price <= 0:
        raise UploadError("판매가가 0입니다.")

    fee = to_int(row.get("배송비"))
    delivery_fee = {"deliveryFeeType": "FREE"} if fee == 0 else {
        "deliveryFeeType": "PAID", "baseFee": fee, "deliveryFeePayType": "PREPAID"}

    model = row.get("모델명") or "상세페이지 참조"
    brand = row.get("브랜드") or ""
    maker = row.get("제조사") or brand or "상세페이지 참조"
    phone = cfg["as_phone"]
    ref = "상세페이지 참조"

    detail = {
        "naverShoppingSearchInfo": strip_empty({"modelName": model, "brandName": brand,
                                                "manufacturerName": maker}),
        "afterServiceInfo": {"afterServiceTelephoneNumber": phone,
                             "afterServiceGuideContent": cfg.get("as_guide") or ref},
        "originAreaInfo": origin_info(row.get("원산지"), cfg),
        "minorPurchasable": True,
        "productInfoProvidedNotice": {
            "productInfoProvidedNoticeType": "ETC",
            "etc": {"returnCostReason": ref, "noRefundReason": ref, "qualityAssuranceStandard": ref,
                    "compensationProcedure": ref, "troubleShootingContents": ref,
                    "itemName": name[:50], "modelName": model, "manufacturer": maker,
                    "customerServicePhoneNumber": phone},
        },
    }
    if row.get("판매자코드"):
        detail["sellerCodeInfo"] = {"sellerManagementCode": str(row["판매자코드"])}

    opt = row.get("옵션상품")
    if isinstance(opt, dict) and (opt.get("optionCombinations") or opt.get("optionSimple")
                                  or opt.get("optionCustom") or opt.get("optionStandards")):
        detail["optionInfo"] = strip_empty(opt)

    tags = row.get("상품태그")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if tags:
        detail["seoInfo"] = {"sellerTags": [{"text": t} for t in tags[:10]]}

    excl = certification_exclude(row.get("인증"))
    if excl:
        detail["certificationTargetExcludeContent"] = excl

    origin = {
        "statusType": "SALE" if (row.get("판매상태") or "판매중") == "판매중" else "SUSPENSION",
        "saleType": "NEW",
        "leafCategoryId": category_id,
        "name": name[:100],
        "detailContent": row.get("상세설명") or f"<p>{name}</p>",
        "images": {"representativeImage": {"url": images[0]},
                   "optionalImages": [{"url": u} for u in images[1:10]]},
        "salePrice": sale_price,
        "stockQuantity": to_int(row.get("재고수"), 999),
        "deliveryInfo": {
            "deliveryType": "DELIVERY",
            "deliveryAttributeType": "NORMAL",
            "deliveryCompany": cfg.get("delivery_company", "CJGLS"),
            "deliveryFee": delivery_fee,
            "claimDeliveryInfo": {"returnDeliveryFee": to_int(cfg.get("return_fee"), 5000),
                                  "exchangeDeliveryFee": to_int(cfg.get("exchange_fee"), 10000)},
        },
        "detailAttribute": detail,
    }
    if not origin["images"]["optionalImages"]:
        del origin["images"]["optionalImages"]

    discount = to_int(row.get("할인가"))
    if 0 < discount < sale_price:
        # 엑셀의 할인가는 '할인된 판매가'로 본다.
        origin["customerBenefit"] = {"immediateDiscountPolicy": {
            "discountMethod": {"value": sale_price - discount, "unitType": "WON"}}}

    body = {
        "originProduct": origin,
        "smartstoreChannelProduct": {"naverShoppingRegistration": True,
                                     "channelProductDisplayStatusType": "ON"},
    }
    return deep_merge(body, copy.deepcopy(cfg.get("extra", {})))


def thumbnails(row):
    t = row.get("썸네일")
    if isinstance(t, str):
        t = [t]
    return [u for u in (t or []) if isinstance(u, str) and u.startswith("http")]


# ───────────────────────── 결과 기록

def result_path(excel_path):
    base = os.path.splitext(os.path.basename(excel_path))[0]
    return os.path.join(os.path.dirname(os.path.abspath(excel_path)), f"upload_result_{base}.csv")


def load_done(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8-sig") as f:
        return {r["id"] for r in csv.DictReader(f) if r.get("status") == "success"}


def append_result(path, rec):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: rec.get(k, "") for k in RESULT_FIELDS})


# ───────────────────────── 실행

def run(excel_path, check=False, limit=None, cfg=None, log=print, progress=None, should_stop=None):
    """progress(i, total, ok, fail), should_stop() -> bool 은 조작 창에서 넘겨준다."""
    cfg = cfg or load_config()
    rows = read_excel(excel_path)
    log(f"엑셀에서 상품 {len(rows)}개를 읽었습니다.")

    cid = cfg.get("client_id", "").strip()
    has_keys = bool(cid) and "여기에" not in cid
    client = None
    if has_keys or not check:
        client = Client(cfg.get("client_id", "").strip(), cfg.get("client_secret", "").strip(), log)
    categories = client.categories() if client else {}
    if check and not client:
        log("※ 설정에 API 키가 없어 카테고리 번호는 확인하지 않습니다.")

    res_path = result_path(excel_path)
    done = set() if check else load_done(res_path)
    todo = [r for r in rows if str(r.get("id", "")) not in done]
    if done:
        log(f"이미 등록한 {len(rows) - len(todo)}개는 건너뜁니다.")
    if limit:
        todo = todo[:limit]

    out_dir = os.path.join(os.path.dirname(os.path.abspath(excel_path)), "upload_check")
    if check:
        os.makedirs(out_dir, exist_ok=True)

    ok = fail = 0
    for i, row in enumerate(todo, 1):
        if should_stop and should_stop():
            log("중단했습니다.")
            break
        rid = str(row.get("id", i))
        name = str(row.get("상품명") or "")
        log(f"[{i}/{len(todo)}] {name[:40]}")
        rec = {"id": rid, "판매자코드": row.get("판매자코드") or "", "상품명": name,
               "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            cat_name = str(row.get("카테고리") or "").strip()
            cat_id = categories.get(cat_name)
            if client and not cat_id:
                raise UploadError(f"카테고리 '{cat_name}'를 스마트스토어에서 찾지 못했습니다.")
            imgs = thumbnails(row)
            if check:
                body = build_body(row, cfg, cat_id or f"(확인 필요) {cat_name}", imgs)
                with open(os.path.join(out_dir, f"{rid}.json"), "w", encoding="utf-8") as f:
                    json.dump(body, f, ensure_ascii=False, indent=2)
                log("  변환 OK")
            else:
                build_body(row, cfg, cat_id, imgs)  # 이미지 올리기 전에 빠진 값부터 확인
                if cfg.get("reupload_images", True):
                    imgs = client.upload_images(imgs[:10])
                res = client.create_product(build_body(row, cfg, cat_id, imgs))
                rec |= {"status": "success", "originProductNo": res.get("originProductNo", ""),
                        "channelProductNo": res.get("smartstoreChannelProductNo", "")}
                log(f"  등록 완료 (상품번호 {rec['channelProductNo']})")
                time.sleep(float(cfg.get("delay_sec", 1.0)))
            ok += 1
        except (UploadError, requests.RequestException) as e:
            fail += 1
            rec |= {"status": "fail", "message": str(e)}
            log(f"  실패: {e}")
        if not check:
            append_result(res_path, rec)
        if progress:
            progress(i, len(todo), ok, fail)

    log(f"끝: 성공 {ok}개, 실패 {fail}개")
    if check:
        log(f"변환 결과: {out_dir}")
    else:
        log(f"결과 기록: {res_path}")
    return ok, fail


def main():
    p = argparse.ArgumentParser(description="엑셀 상품을 스마트스토어에 등록")
    p.add_argument("excel", nargs="?", help="상품 엑셀 파일")
    p.add_argument("--check", action="store_true", help="변환만 하고 등록하지 않음 (upload_check 폴더에 저장)")
    p.add_argument("--limit", type=int, help="앞에서부터 N개만 처리")
    p.add_argument("--console", action="store_true", help="조작 창 없이 실행")
    a = p.parse_args()

    if not a.console or not a.excel:
        import smartstore_upload_gui
        smartstore_upload_gui.main(a.excel)
        return
    try:
        run(a.excel, check=a.check, limit=a.limit)
    except UploadError as e:
        print(f"[!] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
