"""python -m uploader  → 조작 화면을 브라우저로 연다."""

import argparse
import logging
import os
import threading
import webbrowser


def main():
    p = argparse.ArgumentParser(description="스마트스토어 상품 등록기")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    p.add_argument("--fake-api", action="store_true", help="네이버에 접속하지 않고 등록을 흉내 냄 (시연·개발용)")
    a = p.parse_args()
    if a.fake_api:
        os.environ["UPLOADER_FAKE_API"] = "1"

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
