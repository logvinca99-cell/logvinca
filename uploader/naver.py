"""네이버 커머스API 클라이언트.

여러 스레드가 같이 쓴다. 토큰은 잠금으로 한 번만 발급하고, HTTP 세션은 스레드마다 따로 둔다.
환경변수 UPLOADER_FAKE_API=1이면 네이버에 접속하지 않는 FakeClient를 쓴다 (화면 개발·시연용).
"""

import base64
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


class Client:
    def __init__(self, client_id, client_secret):
        if not client_id or not client_secret:
            raise ApiError("설정에서 애플리케이션 ID / 시크릿을 먼저 넣어 주세요.")
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

    def download(self, url):
        r = self.s.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or not r.content:
            raise ApiError(f"이미지 내려받기 실패({r.status_code}): {url}")
        return r.content, r.headers.get("Content-Type", "")

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


class FakeClient:
    """네이버에 접속하지 않고 그럴듯한 지연과 가끔의 실패를 흉내 낸다."""

    def __init__(self, *_):
        self._n = 0
        self._lock = threading.Lock()

    def test(self):
        return True

    def categories(self, refresh=False):
        return _load_category_cache() or {}

    def download(self, url):
        time.sleep(random.uniform(0.05, 0.2))
        return b"fake", "image/jpeg"

    def upload_images(self, items, on_wait=None):
        time.sleep(random.uniform(0.3, 0.8))
        return [f"https://shop-phinf.pstatic.net/fake/{abs(hash(u)) % 10**9}.jpg" for u, _, _ in items]

    def create_product(self, body, on_wait=None):
        time.sleep(random.uniform(0.4, 1.0))
        if random.random() < 0.08:
            raise ApiError("상품 등록 실패: 400 BAD_REQUEST 입력값이 올바르지 않습니다. / "
                           "originProduct.detailAttribute.optionInfo: 옵션가는 판매가의 -50%~+50% 범위여야 합니다")
        with self._lock:
            self._n += 1
            return {"originProductNo": 9000000000 + self._n, "smartstoreChannelProductNo": 8000000000 + self._n}


def make_client(cfg):
    if os.environ.get("UPLOADER_FAKE_API") == "1":
        return FakeClient()
    return Client(cfg.get("client_id", ""), cfg.get("client_secret", ""))
