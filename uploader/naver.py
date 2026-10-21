"""네이버 커머스API 클라이언트.

여러 스레드가 같이 쓴다. 토큰은 잠금으로 한 번만 발급하고, HTTP 세션은 스레드마다 따로 둔다.
환경변수 UPLOADER_FAKE_API=1이면 네이버에 접속하지 않는 FakeClient를 쓴다 (화면 개발·시연용).
"""

import base64
import hashlib
import json
import os
import random
import re
import threading
import time

import requests

from . import config

API = "https://api.commerce.naver.com/external"
CATEGORY_CACHE = os.path.join(config.DATA_DIR, "category_cache.json")
CATEGORY_TTL = 7 * 86400
IMAGES_PER_CALL = 10


class ApiError(Exception):
    pass


def explain_error(r):
    try:
        j = r.json()
    except ValueError:
        return f"{r.status_code}: {r.text[:300]}"
    bad = [f"{x.get('name')}: {x.get('message')}" for x in j.get("invalidInputs") or []]
    msg = f"{r.status_code} {j.get('code', '')} {j.get('message', '')}".strip()
    return msg + (" / " + " / ".join(bad) if bad else "")


def _guess_mime(url, content_type):
    if content_type and content_type.startswith("image/"):
        ct = content_type.split(";")[0].strip()
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/bmp": "bmp"}.get(ct)
        if ext:
            return ext, ct
    m = re.search(r"\.(jpe?g|png|gif|bmp)(?:\?|$)", url, re.I)
    ext = (m.group(1).lower() if m else "jpg").replace("jpeg", "jpg")
    return ext, "image/jpeg" if ext == "jpg" else f"image/{ext}"


def _load_category_cache():
    if os.path.exists(CATEGORY_CACHE) and time.time() - os.path.getmtime(CATEGORY_CACHE) < CATEGORY_TTL:
        with open(CATEGORY_CACHE, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_category_cache(table):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(CATEGORY_CACHE, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False)


def cached_categories():
    """API 호출 없이 저장된 카테고리 목록만 돌려준다 (없으면 None)."""
    return _load_category_cache()


def kst_iso(ts):
    """네이버 API용 시각 (한국 시간, 예: 2026-10-17T09:00:00.000+09:00)"""
    import datetime
    kst = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.fromtimestamp(ts, kst).strftime("%Y-%m-%dT%H:%M:%S.000+09:00")


def parse_time(v):
    if not v:
        return None
    import datetime
    try:
        return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class ImageCache:
    """내려받은 이미지를 디스크에 보관한다. 같은 이미지를 여러 스토어에 올릴 때 다시 받지 않는다.
    용량이 max_gb를 넘으면 오래된 것부터 지운다."""

    def __init__(self, max_gb):
        self.dir = os.path.join(config.DATA_DIR, "imgcache")
        self.max_bytes = int(float(max_gb or 0) * 1024 ** 3)
        self.lock = threading.Lock()
        self.size = None
        self.writes = 0

    def _path(self, url):
        h = hashlib.sha1(url.encode()).hexdigest()
        return os.path.join(self.dir, h[:2], h)

    def get(self, url):
        if not self.max_bytes:
            return None
        p = self._path(url)
        try:
            with open(p + ".type", encoding="utf-8") as f:
                ctype = f.read()
            with open(p, "rb") as f:
                data = f.read()
            os.utime(p)
            return data, ctype
        except OSError:
            return None

    def put(self, url, data, ctype):
        if not self.max_bytes:
            return
        p = self._path(url)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        with open(p + ".type", "w", encoding="utf-8") as f:
            f.write(ctype or "")
        with self.lock:
            if self.size is not None:
                self.size += len(data)
            self.writes += 1
            if self.writes % 200 == 0:
                self._trim()

    def _trim(self):
        files = []
        for root, _, names in os.walk(self.dir):
            for n in names:
                if not n.endswith(".type"):
                    fp = os.path.join(root, n)
                    try:
                        st = os.stat(fp)
                        files.append((st.st_mtime, st.st_size, fp))
                    except OSError:
                        pass
        self.size = sum(f[1] for f in files)
        if self.size <= self.max_bytes:
            return
        files.sort()
        for _, sz, fp in files:
            if self.size <= self.max_bytes * 0.8:
                break
            for x in (fp, fp + ".type"):
                try:
                    os.remove(x)
                except OSError:
                    pass
            self.size -= sz


_image_cache = None


def image_cache(cfg):
    global _image_cache
    if _image_cache is None or _image_cache.max_bytes != int(float(cfg.get("image_cache_gb") or 0) * 1024 ** 3):
        _image_cache = ImageCache(cfg.get("image_cache_gb"))
    return _image_cache


_dl_local = threading.local()


def download(url, cache=None):
    """이미지 내려받기 (디스크 캐시 먼저)."""
    if cache:
        hit = cache.get(url)
        if hit:
            return hit
    if not hasattr(_dl_local, "s"):
        _dl_local.s = requests.Session()
    r = _dl_local.s.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200 or not r.content:
        raise ApiError(f"이미지 내려받기 실패({r.status_code}): {url}")
    ctype = r.headers.get("Content-Type", "")
    if cache:
        cache.put(url, r.content, ctype)
    return r.content, ctype


class Client:
    def __init__(self, client_id, client_secret):
        if not client_id or not client_secret:
            raise ApiError("애플리케이션 ID / 시크릿이 없습니다.")
        self.client_id, self.client_secret = client_id.strip(), client_secret.strip()
        self._token, self._token_until = None, 0
        self._token_lock = threading.Lock()
        self._local = threading.local()

    @property
    def s(self):
        if not hasattr(self._local, "s"):
            self._local.s = requests.Session()
        return self._local.s

    # ── 토큰

    def _token_now(self, force=False):
        with self._token_lock:
            if force or not self._token or time.time() > self._token_until:
                self._issue_token()
            return self._token

    def _issue_token(self):
        import bcrypt
        ts = str(int(time.time() * 1000))
        try:
            hashed = bcrypt.hashpw(f"{self.client_id}_{ts}".encode(), self.client_secret.encode())
        except ValueError:
            raise ApiError("애플리케이션 시크릿 형식이 올바르지 않습니다. 커머스API센터에서 복사한 값을 그대로 넣어 주세요.")
        r = self.s.post(f"{API}/v1/oauth2/token", data={
            "client_id": self.client_id,
            "timestamp": ts,
            "client_secret_sign": base64.b64encode(hashed).decode(),
            "grant_type": "client_credentials",
            "type": "SELF",
        }, timeout=20)
        if r.status_code != 200:
            hint = " → 커머스API센터에 이 PC의 IP를 등록했는지 확인하세요." if "IP" in r.text else \
                " → 애플리케이션 ID/시크릿을 확인하세요."
            raise ApiError(f"토큰 발급 실패: {explain_error(r)}{hint}")
        j = r.json()
        self._token = j["access_token"]
        self._token_until = time.time() + int(j.get("expires_in", 10800)) - 300

    def request(self, method, path, on_wait=None, **kw):
        r, refresh = None, False
        for attempt in range(6):
            headers = {"Authorization": f"Bearer {self._token_now(force=refresh)}"}
            r = self.s.request(method, f"{API}{path}", headers=headers, timeout=60, **kw)
            refresh = r.status_code == 401
            if refresh:
                continue
            if r.status_code == 429 or r.status_code >= 500:
                wait = min(2 ** attempt, 30) + random.random()
                if on_wait:
                    on_wait(f"네이버가 잠시 거절함({r.status_code}), {wait:.0f}초 뒤 다시 시도")
                time.sleep(wait)
                continue
            return r
        return r

    # ── 기능

    def test(self):
        self._token_now(force=True)
        return True

    def categories(self, refresh=False):
        """카테고리 전체 이름 → 번호. 7일간 data/category_cache.json에 저장."""
        if not refresh:
            cached = _load_category_cache()
            if cached:
                return cached
        r = self.request("GET", "/v1/categories", params={"last": "true"})
        if r.status_code != 200:
            raise ApiError(f"카테고리 조회 실패: {explain_error(r)}")
        table = {c["wholeCategoryName"]: str(c["id"]) for c in r.json() if c.get("last", True)}
        _save_category_cache(table)
        return table

    def address_books(self):
        """판매자센터 주소록 (출고지·반품지 고르기용). [{id, name, type, address}]"""
        r = self.request("GET", "/v1/seller/addressbooks-for-page", params={"page": 1, "size": 100})
        if r.status_code != 200:
            raise ApiError(f"주소록 조회 실패: {explain_error(r)}")
        return parse_address_books(r.json())

    def product_count(self):
        """이 스토어에 등록된 상품 수 (판매중·중지 등 모두)."""
        r = self.request("POST", "/v1/products/search", json={"page": 1, "size": 1})
        if r.status_code != 200:
            raise ApiError(f"상품 수 조회 실패: {explain_error(r)}")
        return int(r.json().get("totalElements", 0))

    def status_counts(self, on_wait=None):
        """상품 목록을 끝까지 받아 상태별로 센다 {SALE: n, SUSPENSION: n(고구마), OUTOFSTOCK: n, …, _total: n}.
        상태로 걸러 묻는 방식은 판매 중·판매중지를 못 가르는 경우가 있어, 받은 상품마다 상태를 직접 본다."""
        out, page, total = {}, 1, 0
        while True:
            r = self.request("POST", "/v1/products/search", json={"page": page, "size": 500}, on_wait=on_wait)
            if r.status_code != 200:
                raise ApiError(f"상품 목록 조회 실패: {explain_error(r)}")
            j = r.json()
            items = j.get("contents") or []
            for it in items:
                st = None
                for ch in it.get("channelProducts") or []:
                    st = ch.get("statusType") or st
                    if st:
                        break
                st = st or (it.get("originProduct") or {}).get("statusType") or it.get("statusType") or "UNKNOWN"
                out[st] = out.get(st, 0) + 1
                total += 1
            pages = int(j.get("totalPages") or 0)
            if not items or page >= pages or page >= 200:
                break
            page += 1
        out["_total"] = total
        return out

    def upload_images(self, items, on_wait=None):
        """items: [(원본주소, 바이트, content-type)] 최대 10개 → 네이버 이미지 주소 목록."""
        files = []
        for i, (url, data, ctype) in enumerate(items):
            ext, mime = _guess_mime(url, ctype)
            files.append(("imageFiles", (f"img{i}.{ext}", data, mime)))
        r = self.request("POST", "/v1/product-images/upload", files=files, on_wait=on_wait)
        if r.status_code != 200:
            raise ApiError(f"이미지 업로드 실패: {explain_error(r)}")
        return [im["url"] for im in r.json()["images"]]

    def create_product(self, body, on_wait=None):
        r = self.request("POST", "/v2/products", json=body, on_wait=on_wait)
        if r.status_code != 200:
            raise ApiError(f"상품 등록 실패: {explain_error(r)}")
        return r.json()

    def update_sale_price(self, origin_no, price, on_wait=None):
        """판매가만 바꾼다: 원상품을 읽어 salePrice만 고쳐 그대로 다시 보냄 (도둑방지 원래 가격으로)."""
        r = self.request("GET", f"/v2/products/origin-products/{origin_no}", on_wait=on_wait)
        if r.status_code != 200:
            raise ApiError(f"상품 읽기 실패: {explain_error(r)}")
        body = r.json()
        body["originProduct"]["salePrice"] = int(price)
        body = {k: v for k, v in body.items() if k in ("originProduct", "smartstoreChannelProduct")}
        r = self.request("PUT", f"/v2/products/origin-products/{origin_no}", json=body, on_wait=on_wait)
        if r.status_code != 200:
            raise ApiError(f"가격 바꾸기 실패: {explain_error(r)}")
        return True

    # ── 주문 (판매 이력)

    def changed_product_order_ids(self, since_ts, until_ts, change_type=None, on_progress=None):
        """since~until 사이에 상태가 바뀐(결제·발송·취소·반품·구매확정 등) 상품주문번호들.
        change_type을 주면 그 변경만 (예: PAYED). 네이버는 한 번에 24시간까지만 조회된다."""
        ids, t = [], since_ts
        while t < until_ts:
            end = min(t + 86400 - 1, until_ts)
            params = {"lastChangedFrom": kst_iso(t), "lastChangedTo": kst_iso(end)}
            if change_type:
                params["lastChangedType"] = change_type
            while True:
                r = self.request("GET", "/v1/pay-order/seller/product-orders/last-changed-statuses", params=params)
                if r.status_code != 200:
                    raise ApiError(f"주문 조회 실패: {explain_error(r)}")
                data = (r.json() or {}).get("data") or {}
                ids += [x["productOrderId"] for x in data.get("lastChangeStatuses") or [] if x.get("productOrderId")]
                more = data.get("more") or {}
                if not more.get("moreFrom"):
                    break
                params = {**params, "lastChangedFrom": more["moreFrom"], "moreSequence": more.get("moreSequence")}
            t = end + 1
            if on_progress:
                on_progress(t)
        return list(dict.fromkeys(ids))

    def product_order_details(self, ids):
        """상품주문번호 → [{order_key, channel_no, origin_no, seller_code, product_name, quantity, status, ordered_at}]"""
        out = []
        for i in range(0, len(ids), 300):
            r = self.request("POST", "/v1/pay-order/seller/product-orders/query", json={"productOrderIds": ids[i:i + 300]})
            if r.status_code != 200:
                raise ApiError(f"주문 상세 조회 실패: {explain_error(r)}")
            for d in (r.json() or {}).get("data") or []:
                po, od = d.get("productOrder") or d, d.get("order") or {}
                out.append({
                    "order_key": str(po.get("productOrderId") or ""),
                    "channel_no": str(po.get("productId") or po.get("channelProductNo") or ""),
                    "origin_no": str(po.get("originalProductId") or po.get("originProductNo") or ""),
                    "seller_code": str(po.get("sellerProductCode") or po.get("sellerManagementCode") or ""),
                    "product_name": str(po.get("productName") or ""),
                    "quantity": int(po.get("quantity") or 1),
                    "status": str(po.get("productOrderStatus") or ""),
                    "ordered_at": parse_time(od.get("paymentDate") or od.get("orderDate")),
                })
        return out

    def delete_product(self, origin_no, on_wait=None):
        """원상품 삭제. 이미 없는 상품(404)이면 지운 것으로 본다."""
        r = self.request("DELETE", f"/v2/products/origin-products/{origin_no}", on_wait=on_wait)
        if r.status_code not in (200, 204, 404):
            raise ApiError(f"상품 삭제 실패: {explain_error(r)}")
        return True


def parse_address_books(data):
    """주소록 응답에서 주소 목록을 꺼낸다. 응답 모양이 조금 달라도 첫 번째 주소 목록을 찾아 쓴다."""
    def find(v):
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
        if isinstance(v, dict):
            for x in v.values():
                got = find(x)
                if got:
                    return got
        return None
    out = []
    for a in find(data) or []:
        aid = a.get("addressBookNo") or a.get("addressId") or a.get("id")
        if not aid:
            continue
        addr = " ".join(str(a.get(k)) for k in ("baseAddress", "roadNameAddress", "address", "detailAddress") if a.get(k))
        out.append({"id": int(aid), "name": a.get("name") or a.get("addressName") or "",
                    "type": a.get("addressType") or a.get("type") or "", "address": addr,
                    "overseas": bool(a.get("overseas") or a.get("isOverseas") or a.get("overseasAddress"))})
    return out


class FakeClient:
    """네이버에 접속하지 않고 그럴듯한 지연과 가끔의 실패를 흉내 낸다. 이미지 내려받기도 흉내 낸다."""

    fake = True
    _seq = 0
    _class_lock = threading.Lock()

    def __init__(self, *_):
        self._n = 0
        self._lock = threading.Lock()

    def test(self):
        return True

    def categories(self, refresh=False):
        return _load_category_cache() or {}

    def address_books(self):
        return parse_address_books({"addressBooks": [
            {"addressBookNo": 100001, "name": "국내 사무실", "addressType": "RELEASE", "baseAddress": "서울시 중구 세종대로 1"},
            {"addressBookNo": 100002, "name": "중국 창고", "addressType": "RELEASE", "baseAddress": "广东省 广州市 白云区 1号", "overseas": True},
            {"addressBookNo": 100003, "name": "반품 센터", "addressType": "REFUND_OR_EXCHANGE", "baseAddress": "경기도 김포시 1"}]})

    def product_count(self):
        return random.randint(0, 300)

    def status_counts(self, on_wait=None):
        sale, sus, oos = random.randint(0, 250), random.randint(0, 60), random.randint(0, 20)
        return {"SALE": sale, "SUSPENSION": sus, "OUTOFSTOCK": oos, "_total": sale + sus + oos}

    def delete_product(self, origin_no, on_wait=None):
        time.sleep(random.uniform(0.2, 0.5))
        return True

    def update_sale_price(self, origin_no, price, on_wait=None):
        time.sleep(random.uniform(0.1, 0.3))
        return True

    def upload_images(self, items, on_wait=None):
        time.sleep(random.uniform(0.3, 0.8))
        return [f"https://shop-phinf.pstatic.net/fake/{abs(hash(u)) % 10**9}.jpg" for u, _, _ in items]

    def create_product(self, body, on_wait=None):
        time.sleep(random.uniform(0.4, 1.0))
        if random.random() < 0.08:
            raise ApiError("상품 등록 실패: 400 BAD_REQUEST 입력값이 올바르지 않습니다. / "
                           "originProduct.detailAttribute.optionInfo: 옵션가는 판매가의 -50%~+50% 범위여야 합니다")
        with FakeClient._class_lock:
            # 실제 네이버처럼 모든 스토어에서 겹치지 않는 번호
            FakeClient._seq = max(FakeClient._seq + 1, int(time.time() * 1000) % 10**9)
            n = FakeClient._seq
        return {"originProductNo": 9000000000 + n, "smartstoreChannelProductNo": 8000000000 + n}


def make_client(store):
    """store: db.store(..., with_secret=True)"""
    if os.environ.get("UPLOADER_FAKE_API") == "1":
        return FakeClient()
    if not store.get("client_id") or not store.get("client_secret"):
        raise ApiError(f"'{store.get('name')}' 스토어의 API 키가 없습니다. 스토어 화면에서 넣어 주세요.")
    return Client(store["client_id"], store["client_secret"])


def fake_download(url, cache=None):
    time.sleep(random.uniform(0.05, 0.2))
    return b"fake", "image/jpeg"


def downloader():
    return fake_download if os.environ.get("UPLOADER_FAKE_API") == "1" else download
