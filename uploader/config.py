"""설정. data/config.json에 저장하고, 없는 항목은 DEFAULTS로 채운다."""

import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("UPLOADER_DATA_DIR") or os.path.join(ROOT, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULTS = {
    # 커머스API센터에서 받은 값
    "client_id": "",
    "client_secret": "",
    # 등록 후 '스토어에서 보기' 링크용. 예: https://smartstore.naver.com/mystore
    "store_url": "",

    "as_phone": "",
    "as_guide": "상세페이지 참조",
    "importer": "상세페이지 참조",
    "origin_default": "중국",
    "origin_codes": {"중국": "0200037"},

    "delivery_company": "CJGLS",
    "return_fee": 5000,
    "exchange_fee": 10000,

    # 이미지를 네이버 서버에 다시 올림. 대표/추가 이미지는 API가 요구하므로 항상 올린다.
    "reupload_detail_images": True,
    # 상세설명의 <video> 태그 처리: keep(그대로) / remove(지움)
    "detail_video": "keep",
    # 동시에 등록할 상품 수. 429(호출 초과)가 잦으면 줄인다.
    "workers": 2,
    # 상품 하나 등록 후 쉬는 시간(초)
    "delay_sec": 0.5,
    # 같은 판매자코드가 이미 등록돼 있으면 건너뜀
    "skip_registered_code": True,

    # 모든 상품에 덧붙일 API 필드
    "extra": {},
}

SECRET_KEYS = ("client_secret",)
_lock = threading.Lock()


def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save(values):
    """빈 시크릿은 기존 값을 유지한다 (화면에는 시크릿을 보내지 않으므로)."""
    with _lock:
        cfg = load()
        for k, v in values.items():
            if k not in DEFAULTS:
                continue
            if k in SECRET_KEYS and not v:
                continue
            cfg[k] = v
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
        return cfg


def public(cfg):
    """화면에 보낼 설정. 시크릿은 있는지 여부만 알린다."""
    out = {k: v for k, v in cfg.items() if k not in SECRET_KEYS}
    out["has_secret"] = bool(cfg.get("client_secret"))
    return out


def has_keys(cfg):
    return bool(cfg.get("client_id", "").strip() and cfg.get("client_secret", "").strip())
