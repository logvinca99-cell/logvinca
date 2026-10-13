"""Apple 계정 구독 페이지에서 YouTube Premium 갱신(Renew)을 될 때까지 반복한다.

흐름: Renew 클릭 → [Confirm Subscription] 창의 Confirm 클릭
      → "Unable to complete purchase" 창이면 Cancel 클릭 → 처음부터 반복

- 엣지 InPrivate(또는 크롬 시크릿)과 같은, 기록이 남지 않는 창에서 실행
- 로그인과 YouTube 카드 열기는 사람이 직접 1회. Renew 버튼이 보이면 자동 시작
- 고정 대기 대신 버튼이 나타나는 즉시 클릭하고, 그 사이에만 짧은 랜덤 지연
- 성공했거나 처음 보는 화면이면 즉시 멈추고 텔레그램으로 알림(이중 결제 방지)

사용법:
    python renew.py                     # 엣지로 실행
    python renew.py --browser chrome    # 크롬으로 실행
    python renew.py --dry-run           # Confirm 대신 Cancel을 눌러 버튼 인식만 시험
    python renew.py --telegram-setup    # 텔레그램 chat_id 찾기 + 시험 메시지
"""

import argparse
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:
    print("필요한 도구(playwright)를 설치합니다. 1~2분 걸립니다...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

START_URL = "https://account.apple.com/account/manage/section/subscriptions"
CONFIG_PATH = "renew_config.json"
LOG_PATH = "renew_log.csv"
SHOT_DIR = "renew_shots"

RENEW_RE = re.compile(r"^\s*Renew\b", re.I)
CONFIRM_TITLE_RE = re.compile(r"Confirm Subscription", re.I)
FAIL_RE = re.compile(r"Unable to complete", re.I)
# 이 문구가 보이면 잠시 쉬었다가 다시 시도 (1~2시간 뒤 된다는 후기 기준)
COOLDOWN_RE = re.compile(r"too many|try again later|temporarily|not available at this time", re.I)
# 이 문구가 보이면 결제 자체 문제 → 멈추고 알림
FATAL_RE = re.compile(r"declined|verify your payment|billing problem", re.I)
# 성공으로 볼 문구
SUCCESS_RE = re.compile(r"renews on|you.re all set|thank you|subscribed|purchase (is )?complete", re.I)
LOGIN_RE = re.compile(r"Sign in with (your )?Apple|Apple 계정으로 로그인", re.I)


class Stop(Exception):
    pass


# ───────────────────────── 텔레그램 ─────────────────────────

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def telegram(cfg, text, photo=None):
    """텔레그램으로 알림. 설정이 없거나 전송에 실패해도 매크로는 계속 돈다."""
    token, chat = cfg.get("bot_token"), cfg.get("chat_id")
    print(f"[알림] {text}")
    if not token or not chat:
        return
    try:
        if photo and os.path.exists(photo):
            boundary = "----renew" + str(random.randint(10**8, 10**9))
            with open(photo, "rb") as f:
                img = f.read()
            body = b"".join([
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat}\r\n".encode(),
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{text}\r\n".encode(),
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"shot.png\"\r\n"
                f"Content-Type: image/png\r\n\r\n".encode(), img, f"\r\n--{boundary}--\r\n".encode(),
            ])
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendPhoto", data=body,
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        else:
            data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"  (텔레그램 전송 실패: {e})")


def telegram_setup():
    """봇 토큰을 받아 chat_id를 찾아 renew_config.json에 저장하고 시험 메시지를 보낸다."""
    cfg = load_config()
    print("1) 텔레그램에서 @BotFather → /newbot 으로 봇을 만들고 토큰을 복사하세요.")
    token = input(f"봇 토큰 [{cfg.get('bot_token', '')}]: ").strip() or cfg.get("bot_token", "")
    print("2) 방금 만든 봇과의 대화창을 열고 아무 메시지(예: hi)를 보내세요.")
    input("   보냈으면 Enter...")
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15) as r:
        updates = json.load(r).get("result", [])
    chats = [u["message"]["chat"]["id"] for u in updates if "message" in u]
    if not chats:
        sys.exit("메시지를 찾지 못했습니다. 봇에게 메시지를 보낸 뒤 다시 실행하세요.")
    cfg.update(bot_token=token, chat_id=chats[-1])
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    telegram(cfg, "✅ 갱신 매크로 텔레그램 연결 완료")
    print(f"저장했습니다: {CONFIG_PATH}")


# ───────────────────────── 화면 조작 ─────────────────────────

def jitter(page, lo, hi):
    page.wait_for_timeout(random.randint(lo, hi))


def visible(loc):
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except PlaywrightError:
        return False


def find(page, make):
    """모든 프레임(iframe 포함)에서 make(frame)으로 만든 요소 중 보이는 첫 번째를 돌려준다."""
    for fr in page.frames:
        loc = make(fr)
        if visible(loc):
            return loc.first
    return None


def renew_btn(page):
    return find(page, lambda f: f.get_by_role("button", name=RENEW_RE))


def dialog_with(page, text_re):
    """text_re 문구가 들어 있는 대화상자. role=dialog가 없으면 페이지 전체."""
    d = find(page, lambda f: f.get_by_role("dialog").filter(has_text=text_re))
    if d:
        return d
    return find(page, lambda f: f.locator("body").filter(has_text=text_re))


def page_text(page):
    out = []
    for fr in page.frames:
        try:
            out.append(fr.locator("body").inner_text(timeout=1000))
        except PlaywrightError:
            pass
    return "\n".join(out)


def wait_for(page, check, timeout_ms, step=100):
    """check()가 참(값)을 돌려줄 때까지 짧게 반복 확인. 고정 sleep보다 빠르다."""
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        v = check()
        if v:
            return v
        page.wait_for_timeout(step)
    return None


def screenshot(page, tag):
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f"{datetime.datetime.now():%m%d_%H%M%S}_{tag}.png")
    try:
        page.screenshot(path=path)
    except PlaywrightError:
        return None
    return path


def log_row(n, result, note=""):
    new = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", encoding="utf-8-sig") as f:
        if new:
            f.write("time,try,result,note\n")
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S},{n},{result},{note.replace(',', ' ')}\n")


def wait_for_renew(page, cfg, why, args):
    """Renew 버튼이 다시 보일 때까지 기다린다. 사람이 로그인/카드 열기를 하면 자동으로 이어간다."""
    if why:
        telegram(cfg, f"⚠️ {why}\n로그인하고 YouTube 카드를 열어 Renew 버튼이 보이게 해 주세요. 보이면 자동으로 이어갑니다.",
                 screenshot(page, "wait"))
    last_try = 0
    while True:
        btn = renew_btn(page)
        # 열린 대화상자가 없을 때만 시작 (결과 창이 떠 있는 채로 다시 누르지 않도록)
        if btn and not dialog_with(page, FAIL_RE) and \
                not find(page, lambda f: f.get_by_role("button", name="Confirm", exact=True)):
            return btn
        # 로그인은 되어 있는데 카드가 닫혀 있으면 직접 열어 본다(1분에 한 번)
        if args.card_text and time.time() - last_try > 60:
            last_try = time.time()
            card = find(page, lambda f: f.get_by_text(args.card_text))
            if card:
                try:
                    card.click(timeout=3000)
                except PlaywrightError:
                    pass
        page.wait_for_timeout(1000)


def recover(page, cfg, args):
    """Renew 버튼이 안 보일 때: 열린 창 닫기 → 새로고침 → 그래도 없으면 사람을 기다림."""
    for fr in page.frames:  # 남아 있는 대화상자 닫기
        for name in ("Cancel", "Close", "OK", "Done"):
            loc = fr.get_by_role("button", name=name, exact=True)
            if visible(loc):
                try:
                    loc.first.click(timeout=2000)
                except PlaywrightError:
                    pass
    if renew_btn(page):
        return
    try:
        page.goto(START_URL, wait_until="domcontentloaded")
    except PlaywrightError:
        pass
    page.wait_for_timeout(3000)
    signed_out = "signin" in page.url or LOGIN_RE.search(page_text(page))
    why = "로그인이 풀린 것 같습니다." if signed_out else "Renew 버튼을 찾지 못했습니다."
    wait_for_renew(page, cfg, why, args)


def cycle(page, args):
    """한 번 시도. 결과: fail / success / cooldown / fatal / unknown / norenew"""
    btn = renew_btn(page)
    if not btn:
        return "norenew", ""
    btn.click()

    # 1) Confirm Subscription 창의 Confirm 버튼
    confirm = wait_for(page, lambda: find(page, lambda f: f.get_by_role("button", name="Confirm", exact=True)),
                       args.step_timeout)
    if not confirm:
        return "unknown", "Confirm 창이 뜨지 않음"
    jitter(page, *args.click_delay)
    if args.dry_run:
        dlg = dialog_with(page, CONFIRM_TITLE_RE) or page
        dlg.get_by_role("button", name="Cancel", exact=True).first.click()
        return "dry", ""
    confirm.click()

    # 2) 결과 창 판별
    def outcome():
        txt = page_text(page)
        if FAIL_RE.search(txt):
            return "fail"
        if FATAL_RE.search(txt):
            return "fatal"
        if COOLDOWN_RE.search(txt):
            return "cooldown"
        if SUCCESS_RE.search(txt):
            return "success"
        return None

    res = wait_for(page, outcome, args.result_timeout, step=150)
    if res is None:
        # 실패 문구도 성공 문구도 없음: Confirm 창이 닫히고 Renew도 사라졌으면 성공 가능성이 높다
        still_confirm = find(page, lambda f: f.get_by_role("button", name="Confirm", exact=True))
        if not still_confirm and not renew_btn(page):
            return "success", "실패 창 없이 Renew가 사라짐"
        return "unknown", "결과 창을 판별하지 못함"
    if res != "fail":
        return res, ""

    # 3) Unable to complete purchase 창의 Cancel
    jitter(page, *args.click_delay)
    dlg = dialog_with(page, FAIL_RE)
    cancel = None
    if dlg:
        loc = dlg.get_by_role("button", name="Cancel", exact=True)
        cancel = loc.first if visible(loc) else None
    cancel = cancel or find(page, lambda f: f.get_by_role("button", name="Cancel", exact=True))
    if cancel:
        cancel.click()
    # Renew 화면으로 돌아올 때까지
    wait_for(page, lambda: renew_btn(page) and not dialog_with(page, FAIL_RE), args.step_timeout)
    return "fail", ""


def run(args):
    cfg = load_config()
    channel = {"edge": "msedge", "chrome": "chrome"}[args.browser]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=channel, headless=False, args=["--start-maximized"])
        # new_context() = InPrivate/시크릿과 같은, 쿠키·기록이 남지 않는 창
        context = browser.new_context(no_viewport=True, locale="en-US")
        page = context.new_page()
        page.goto(START_URL)
        print("브라우저에서 로그인 → 구독 → YouTube Premium Family 카드를 눌러 Renew 버튼이 보이게 해 주세요.")
        print("Renew 버튼이 보이면 자동으로 시작합니다. 멈추려면 이 창에서 Ctrl+C.\n")
        wait_for_renew(page, cfg, None, args)
        telegram(cfg, "▶ 갱신 매크로 시작" + (" (시험 모드)" if args.dry_run else ""))

        n = fails = 0
        started = last_report = time.time()
        next_rest = random.randint(*args.rest_every)
        try:
            while args.max_tries <= 0 or n < args.max_tries:
                n += 1
                try:
                    res, note = cycle(page, args)
                except PlaywrightError as e:
                    res, note = "unknown", e.message.splitlines()[0]
                log_row(n, res, note)
                elapsed = int(time.time() - started)
                print(f"[{datetime.datetime.now():%H:%M:%S}] {n}회  {res}  {note}  "
                      f"(실패 {fails}, 경과 {elapsed // 3600}시간 {elapsed % 3600 // 60}분)")

                if res == "success":
                    shot = screenshot(page, "success")
                    telegram(cfg, f"🎉 갱신 성공으로 보입니다! ({n}번째 시도)\n{note}\n"
                                  "Apple 계정 페이지와 메일 영수증을 확인하세요. 매크로는 멈췄습니다.", shot)
                    print("\n성공으로 보여 멈췄습니다. 브라우저를 직접 확인하세요.")
                    input("Enter를 누르면 브라우저가 닫힙니다...")
                    return
                if res == "fatal":
                    telegram(cfg, f"⛔ 결제 문제 메시지가 나와 멈췄습니다. ({n}번째)", screenshot(page, "fatal"))
                    input("Enter를 누르면 브라우저가 닫힙니다...")
                    return
                if res == "unknown":
                    # 결제가 됐을 수도 있는 상황 → 절대 다시 누르지 않고 사람을 기다림
                    telegram(cfg, f"❓ 처음 보는 화면이라 멈췄습니다. ({n}번째, {note})\n"
                                  "확인 후 Renew 버튼이 보이는 화면으로 돌려놓으면 다시 시작합니다.",
                             screenshot(page, "unknown"))
                    wait_for_renew(page, cfg, None, args)
                    continue
                if res == "cooldown":
                    mins = random.randint(*args.cooldown)
                    telegram(cfg, f"⏳ 제한 메시지가 나와 {mins}분 쉽니다. ({n}번째)", screenshot(page, "cooldown"))
                    page.wait_for_timeout(mins * 60_000)
                    recover(page, cfg, args)
                    continue
                if res == "norenew":
                    recover(page, cfg, args)
                    continue

                fails += res == "fail"
                if args.report_min and time.time() - last_report > args.report_min * 60:
                    last_report = time.time()
                    telegram(cfg, f"⏱ 진행 중: {n}회 시도, 실패 {fails}회, {elapsed // 60}분 경과")

                # 랜덤 지연: 매 회 짧게, 몇십 회마다 길게
                if n >= next_rest:
                    rest = random.randint(*args.rest_sec)
                    print(f"  … {rest}초 휴식")
                    page.wait_for_timeout(rest * 1000)
                    next_rest = n + random.randint(*args.rest_every)
                else:
                    jitter(page, *args.cycle_delay)
            telegram(cfg, f"■ 최대 시도 횟수({args.max_tries}회)에 도달해 멈췄습니다.")
        except KeyboardInterrupt:
            telegram(cfg, f"■ 사용자가 멈췄습니다. ({n}회 시도, 실패 {fails}회)")
        finally:
            try:
                browser.close()
            except Exception:
                pass


def parse_args():
    ap = argparse.ArgumentParser(description="Apple 구독 YouTube Premium 갱신 반복")
    ap.add_argument("--browser", choices=["edge", "chrome"], default="edge")
    ap.add_argument("--dry-run", action="store_true", help="Confirm 대신 Cancel을 눌러 버튼 인식만 시험")
    ap.add_argument("--telegram-setup", action="store_true", help="텔레그램 연결 설정")
    ap.add_argument("--card-text", default="Expired 12 October",
                    help="Renew 버튼이 사라졌을 때 다시 열 카드의 글자 (기본 'Expired 12 October')")
    ap.add_argument("--click-delay", type=int, nargs=2, default=[250, 700], metavar=("MIN", "MAX"),
                    help="창이 뜬 뒤 버튼을 누르기까지 대기 ms (기본 250 700)")
    ap.add_argument("--cycle-delay", type=int, nargs=2, default=[1200, 3500], metavar=("MIN", "MAX"),
                    help="한 번 시도가 끝나고 다음 Renew까지 대기 ms (기본 1200 3500)")
    ap.add_argument("--rest-every", type=int, nargs=2, default=[40, 70], metavar=("MIN", "MAX"),
                    help="이 횟수마다 길게 휴식 (기본 40~70회)")
    ap.add_argument("--rest-sec", type=int, nargs=2, default=[60, 180], metavar=("MIN", "MAX"),
                    help="긴 휴식 시간 초 (기본 60~180초)")
    ap.add_argument("--cooldown", type=int, nargs=2, default=[60, 90], metavar=("MIN", "MAX"),
                    help="제한 메시지가 나오면 쉴 시간 분 (기본 60~90분)")
    ap.add_argument("--step-timeout", type=int, default=15000, help="창이 뜨기를 기다리는 최대 ms")
    ap.add_argument("--result-timeout", type=int, default=25000, help="Confirm 후 결과를 기다리는 최대 ms")
    ap.add_argument("--max-tries", type=int, default=0, help="최대 시도 횟수 (0 = 무제한)")
    ap.add_argument("--report-min", type=int, default=60, help="진행 상황 텔레그램 보고 간격 분 (0 = 끔)")
    return ap.parse_args()


if __name__ == "__main__":
    a = parse_args()
    if a.telegram_setup:
        telegram_setup()
    else:
        run(a)
