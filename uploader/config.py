"""공통 설정. data/config.json에 저장하고, 없는 항목은 DEFAULTS로 채운다.

스토어별 값(API 키, 스토어 주소, A/S 전화)은 설정이 아니라 db의 stores 표에 있다.
"""

import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 기록·설정은 프로그램 폴더가 아니라 사용자 폴더에 둔다 → 새 버전을 다른 폴더에 받아도 그대로 이어서 씀
#   (Windows: C:\Users\이름\상품등록기_data)
LEGACY_DATA_DIR = os.path.join(ROOT, "data")
DATA_DIR = os.environ.get("UPLOADER_DATA_DIR") or os.path.join(os.path.expanduser("~"), "상품등록기_data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULTS = {
    # ── 상품 기본값 (스토어에 A/S 전화가 없으면 이 값)
    "as_phone": "",
    "as_guide": "상세페이지 참조",
    "importer": "상세페이지 참조",
    # 원산지: 기본은 엑셀 값과 상관없이 일괄로 origin_country(중국)로 등록, 수입사는 스토어별 '{store}협력사'
    "origin_force": True,
    "origin_country": "중국",
    "importer_template": "{store}협력사",
    "origin_default": "중국",          # origin_force를 끄고 엑셀 원산지가 비었을 때
    "origin_codes": {"중국": "0200037", "상세페이지 참조": "03"},
    "delivery_company": "CJGLS",
    "return_fee": 5000,
    "exchange_fee": 10000,

    # ── 복사·구분
    # 원본 하나를 올릴 수 있는 최대 스토어 수 (내린 것은 세지 않음)
    "max_copies": 3,
    # 스토어에 등록하는 판매자 관리코드. {store}=스토어 코드, {source}=원본 번호, {round}=회차
    "seller_code_format": "{store}-{source:07d}-{round}",
    # 최신화(지우고 다시 올리기)·다시 올리기 때 상품명을 새 후보로 바꿀지 (끄면 같은 이름)
    "refresh_new_name": False,

    # ── 주문(판매 이력): 판매자센터 주문을 커머스API로 가져온다
    # 프로그램이 켜져 있는 동안 이 간격(분)마다 모든 스토어 주문을 가져옴 (0이면 끔)
    "orders_auto_sync_minutes": 60,
    # 처음 가져올 때 며칠 전부터
    "orders_initial_days": 30,
    # 판매 이력이 있는 복사본은 자동으로 잠금 (최신화·내리기로 지우지 않음)
    "lock_sold": True,
    # 취소·반품만 있는 복사본도 잠글지 (끄면 실제 판매가 1건이라도 있어야 잠금)
    "lock_canceled_too": False,

    # ── 가격: 스토어마다 원본가에서 ±price_jitter_pct% 안에서 정하고 price_round(100원) 단위로 올림. 가격은 항상 100원 단위 올림.
    #    같은 상품·같은 스토어는 언제 계획해도 같은 가격이 나온다.
    "price_jitter_pct": 3.0,
    "price_round": 100,

    # ── 상품명
    # 원본 상품명을 그대로 쓰는 것도 허용할지 (원본 스토어와 이름이 같아짐)
    "use_original_name": False,
    # 재조합: 이름 후보가 모자라면 계획 만들 때 자동으로 만든다
    "auto_recombine": True,
    "name_max_len": 50,
    # 재조합에 상품태그 단어를 섞을지 (엑셀 태그가 상품과 안 맞는 경우가 있어 기본 꺼짐)
    "recombine_use_tags": False,
    # 재조합: 원본의 앞 몇 단어를 그대로 맨 앞에 고정할지
    "recombine_fixed_prefix": 3,
    # 재조합: 유의어를 덧붙이지 않고 원래 단어 자리에 바꿔 넣는 비율 (0~1)
    "recombine_replace_ratio": 0.4,
    # 재조합 때 새로 넣을 단어 수 (단어 사전의 유의어·카테고리 단어, 한글 일반명사만)
    "recombine_new_min": 1,
    "recombine_new_max": 2,
    # 남는 칸을 최대 글자 수까지 채움 (노출에 유리)
    "recombine_fill": True,
    # 카테고리 이름의 단어를 새 단어로 쓸지
    "use_category_words": False,
    # 한 상품명 안에서 같은 단어를 몇 번까지 허용할지 (다른 단어 안에 들어간 것도 셈)
    "max_word_repeat": 2,
    # 우리말샘 오픈 API 키 (opendict.korean.go.kr, 무료) — 단어 사전에서 유의어 받기
    "opendict_key": "",
    "opendict_daily_limit": 1000,
    # 같은 원본의 다른 이름과 단어가 이만큼 이상 겹치면 너무 비슷하다고 보고 버림 (0~1)
    "recombine_max_overlap": 0.85,
    # 네이버 키워드 (검색광고 API, searchad.naver.com → 도구 → API 사용 관리, 무료)
    #   핵심 키워드 = 앞 5단어 중 검색량이 가장 큰 단어, 새 단어 = 핵심 키워드 연관 키워드에서 핵심을 뺀 말
    "use_naver_keywords": True,
    "searchad_customer_id": "",
    "searchad_api_key": "",
    "searchad_secret": "",
    "kw_daily_limit": 1000,          # 한 번에 부를 API 횟수 (같은 핵심 키워드는 저장한 결과 재사용)
    "kw_min_volume": 30,             # 연관 키워드 월간 검색량이 이만큼 이상인 것만
    "kw_dict_only": True,            # 국어사전에 있는 말만 (브랜드·고유명사 거르기, 우리말샘 API·사전 파일)
    "kw_related_max": 200,           # 핵심 키워드마다 볼 연관 키워드 수
    "kw_refresh_days": 60,           # 이만큼 지나면 다시 모음
    "kw_max_words": 15,              # 원본 하나에 넘길 단어 수
    "core_scan_words": 5,            # 핵심 키워드를 찾을 앞 단어 수
    # 키프리스(KIPRIS Plus) 상표 확인 키 (plus.kipris.or.kr) — 상표로 등록된 단어는 새 단어로 쓰지 않음
    "kipris_key": "",
    # 출원·공고 중(아직 등록 전)인 상표 단어도 쓰지 않을지
    "kipris_block_pending": True,
    # 한 번에 확인할 단어 수
    "kipris_limit": 500,

    # ── 도둑방지
    # 처음 올릴 때 판매가에 bait_amount를 더해 올리고, 원래 가격으로는 직접 되돌림 (복사본·도둑방지 화면의 버튼)
    # 등록 계획 창의 '도둑방지로 올리기' 기본값. 할인 금액은 도둑방지 전 가격으로 계산.
    "bait_default": True,
    "bait_amount": 30000,
    "bait_on_refresh": False,        # 최신화(다시 등록) 때도 높여서 올릴지
    # 대표 이미지 워터마크 (스토어마다: 스토어 화면에서 로고 PNG 또는 글자)
    "wm_enabled": False,
    "wm_scope": "main",              # main(대표 이미지만) / all(대표+추가 이미지)
    "wm_position": "bottom-right",   # top-left / top-right / bottom-left / bottom-right / top-center / bottom-center
    "wm_size_pct": 22,               # 워터마크 너비 (정사각형 한 변의 %)
    "wm_opacity": 0.85,
    "wm_margin_pct": 3,
    "wm_square": "safe",             # safe(가운데 정사각형 안쪽) / pad(흰 여백으로 정사각형) / full(이미지 전체 기준)
    "wm_font": "",                   # 글자 워터마크 글꼴 파일 (비우면 맑은 고딕 등)

    # ── 재조합 새 단어 (AI): 원본마다 처음 한 번 AI에게 '넣어도 되는 단어'를 받아 저장, 이름 조립은 재조합이 함
    "ai_words_enabled": True,
    "ai_words_model": "claude-sonnet-5-5",
    "ai_words_effort": "low",
    "ai_words_per_call": 20,         # 한 번에 보낼 원본 수
    "ai_words_max": 15,              # 원본 하나에 받을 단어 수 (대략)
    "ai_bank_min": 8,                # 단어 은행에서 이만큼 찾으면 AI를 부르지 않음 (0이면 은행 안 씀)

    # ── AI 상품명 (Claude API)
    "anthropic_api_key": "",
    "ai_model": "claude-opus-5-5",
    "ai_effort": "low",
    "ai_names_per_product": 5,
    "ai_products_per_call": 20,
    "ai_workers": 4,
    "ai_guide": "",

    # ── 이미지
    # 상세페이지 이미지를 네이버 서버에 올릴지
    "reupload_detail_images": True,
    # 상세 이미지 주소가 이미 네이버 이미지 서버(pstatic.net)면 그대로 둠 (시간·용량 크게 절약)
    "keep_pstatic_detail_images": True,
    "detail_video": "keep",
    # 내려받은 이미지를 디스크에 보관해 여러 스토어에 올릴 때 다시 받지 않음 (GB)
    "image_cache_gb": 5,

    # ── 속도
    "workers_per_store": 2,
    "max_parallel_stores": 33,
    "delay_sec": 0.3,

    "extra": {},
}

SECRET_KEYS = ("anthropic_api_key", "opendict_key", "kipris_key", "searchad_secret")
_lock = threading.Lock()


def migrate_legacy_data():
    """예전 버전은 프로그램 폴더의 data에 저장했다. 사용자 폴더에 아직 기록이 없고 프로그램 폴더 data에
    원본이 들어 있는 기록이 있으면 한 번 복사해 온다 (이미지 캐시는 빼고, 원래 폴더는 그대로 둠)."""
    import shutil
    import sqlite3
    if os.environ.get("UPLOADER_DATA_DIR"):
        return None
    new_db, old_db = os.path.join(DATA_DIR, "inventory.db"), os.path.join(LEGACY_DATA_DIR, "inventory.db")
    if os.path.exists(new_db) or not os.path.exists(old_db):
        return None
    try:
        con = sqlite3.connect(f"file:{old_db}?mode=ro", uri=True)
        n = con.execute("SELECT (SELECT COUNT(*) FROM sources) + (SELECT COUNT(*) FROM stores)").fetchone()[0]
        con.close()
    except sqlite3.Error:
        n = 0
    if not n:
        return None
    shutil.copytree(LEGACY_DATA_DIR, DATA_DIR, dirs_exist_ok=True, ignore=shutil.ignore_patterns("imgcache", "*.tmp"))
    return LEGACY_DATA_DIR


def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        if "kipris_block_pending" not in saved:
            saved.pop("use_category_words", None)  # 이 버전부터 상품명에 카테고리를 쓰지 않음 (예전 설정도 끔)
        cfg.update(saved)
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
    out = {k: v for k, v in cfg.items() if k not in SECRET_KEYS}
    for k in SECRET_KEYS:
        out["has_" + k] = bool(cfg.get(k))
    return out
