"""python -m uploader  → 조작 화면을 브라우저로 연다."""

import argparse
import faulthandler
import logging
import os
import sys
import threading
import time
import webbrowser


def _setup_log():
    """오류를 data/uploader.log에 남긴다 (창이 닫혀도 원인을 볼 수 있게). 파이썬 자체가 죽어도 crash.log에."""
    from . import config
    os.makedirs(config.DATA_DIR, exist_ok=True)
    path = os.path.join(config.DATA_DIR, "uploader.log")
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()])
    faulthandler.enable(open(os.path.join(config.DATA_DIR, "crash.log"), "a", encoding="utf-8"))

    def hook(exc_type, exc, tb):
        logging.getLogger("uploader").error("처리하지 못한 오류", exc_info=(exc_type, exc, tb))
    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
    logging.getLogger("uploader").warning("시작 %s · 파이썬 %s · %s", time.strftime("%Y-%m-%d %H:%M"),
                                          sys.version.split()[0], sys.platform)


def main():
    p = argparse.ArgumentParser(description="스마트스토어 상품 등록기")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    p.add_argument("--fake-api", action="store_true", help="네이버에 접속하지 않고 등록을 흉내 냄 (시연·개발용)")
    a = p.parse_args()
    if a.fake_api:
        os.environ["UPLOADER_FAKE_API"] = "1"
    from . import config
    moved = config.migrate_legacy_data()
    _setup_log()
    if moved:
        print(f"예전 기록을 옮겨 왔습니다: {moved} → {config.DATA_DIR}")
    print(f"기록·설정 폴더: {config.DATA_DIR}")

    from .web import create_app
    app = create_app()
    url = f"http://127.0.0.1:{a.port}"
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print(f"상품 등록기: {url}")
    print("이 창을 닫으면 등록기가 꺼집니다.")
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=a.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
