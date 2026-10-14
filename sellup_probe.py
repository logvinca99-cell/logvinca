"""셀업 자동 수집기 v2 — Phase 0 진단 도구.

전용 프로필 크롬을 원격 디버깅 포트로 띄우고, 상품 페이지에서
셀업의 노란 CAPTURE 버튼이 페이지 안에 어떤 모습으로 들어 있는지 조사한다.
결과는 probe_report.txt 에 저장된다. (설계: docs/sellup_design.md 13절)

사용법:
    python sellup_probe.py              # 상품 URL을 물어봄
    python sellup_probe.py <상품URL> ... # 여러 개를 차례로 검사
"""

import ctypes
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:
    print("필요한 도구(playwright)를 설치합니다. 1~2분 걸립니다...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 9222
PROFILE = os.path.join(HERE, "chrome_profile")
REPORT = os.path.join(HERE, "probe_report.txt")
LABELS = ["CAPTURE", "ARMED"]
DUP_TITLE = "기등록 상품 확인"
LOAD_WAIT = 20000
CLICK_SETTLE = 1000
WATCH_MS = 4000
GONE_WORDS = ["판매중지", "판매 중지", "삭제된", "존재하지 않", "판매가 종료", "판매종료", "구매할 수 없"]

# 문서 전체(열린 shadow root 포함)에서 글자가 정확히 CAPTURE/ARMED 인 요소를 찾는다.
# 찾은 요소는 window.__probeEls 에 보관해 두고 나중에 감시한다.
FIND_JS = r"""
labels => {
  const desc = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
    (typeof e.className === 'string' && e.className.trim()
      ? '.' + e.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
  const ownText = e => {
    let t = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('');
    if (!t.trim() && (e.tagName === 'INPUT' || e.tagName === 'BUTTON')) t = e.value || '';
    return t.trim().toUpperCase();
  };
  const out = [];
  window.__probeEls = [];
  const walk = (root, chain) => {
    for (const e of root.querySelectorAll('*')) {
      if (e.shadowRoot) walk(e.shadowRoot, chain.concat(desc(e)));
      const t = ownText(e);
      const aria = (e.getAttribute('aria-label') || '').trim().toUpperCase();
      const hit = labels.find(l => t === l || aria === l);
      if (!hit) continue;
      const r = e.getBoundingClientRect();
      const st = getComputedStyle(e);
      window.__probeEls.push(e);
      out.push({
        idx: window.__probeEls.length - 1, label: hit, el: desc(e), shadow: chain,
        rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
        bg: st.backgroundColor, color: st.color, cursor: st.cursor,
        path: (() => { const p = []; for (let x = e; x && p.length < 6; x = x.parentElement) p.unshift(desc(x)); return p.join(' > '); })(),
        outer: e.outerHTML.slice(0, 300),
      });
    }
  };
  walk(document, []);
  return out;
}
"""

# 버튼을 못 찾았을 때의 단서: 오른쪽 아래의 고정 위치 요소, 닫힌 shadow root 로 의심되는 사용자 정의 태그.
HINT_JS = r"""
() => {
  const W = innerWidth, H = innerHeight, out = [];
  for (const e of document.querySelectorAll('body *')) {
    const st = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    const custom = e.tagName.includes('-');
    const corner = st.position === 'fixed' && r.width > 0 && r.left > W * 0.5 && r.top > H * 0.5;
    if (!custom && !corner) continue;
    out.push({ tag: e.tagName.toLowerCase(), id: e.id, cls: String(e.className).slice(0, 60),
      fixed: st.position === 'fixed', openShadow: !!e.shadowRoot,
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      text: (e.innerText || '').trim().slice(0, 40) });
    if (out.length >= 30) break;
  }
  return out;
}
"""

# 찾은 버튼의 글자 변화를 기록. 20ms 간격 + DOM 변화 즉시 기록, 요소가 교체되면 다시 찾는다.
WATCH_JS = r"""
([idx, labels]) => {
  let el = window.__probeEls[idx];
  const log = window.__probeLog = [];
  const t0 = performance.now();
  let last = null;
  const deepLabels = () => {
    const found = [];
    const walk = root => { for (const e of root.querySelectorAll('*')) {
      if (e.shadowRoot) walk(e.shadowRoot);
      const t = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim().toUpperCase();
      if (labels.includes(t)) found.push(t);
    } };
    walk(document);
    return found.join(',');
  };
  const tick = () => {
    const own = el && el.isConnected ? (el.textContent || el.value || '').trim() : '<교체됨>';
    const s = `버튼="${own}" | 화면의 라벨=[${deepLabels()}]`;
    if (s !== last) { log.push([Math.round(performance.now() - t0), s]); last = s; }
  };
  tick();
  window.__probeTimer = setInterval(tick, 20);
  window.__probeObs = new MutationObserver(tick);
  window.__probeObs.observe(el.getRootNode(), { subtree: true, childList: true, characterData: true, attributes: true });
}
"""

UNWATCH_JS = r"""
() => { clearInterval(window.__probeTimer); window.__probeObs && window.__probeObs.disconnect(); return window.__probeLog || []; }
"""


class Report:
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8")

    def __call__(self, text=""):
        print(text)
        self.f.write(text + "\n")
        self.f.flush()


# ── 윈도우 창(셀업 본체 팝업) 다루기 ───────────────────────────
IS_WIN = sys.platform == "win32"
if IS_WIN:
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def win_text(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(h, buf, 256)
    return buf.value


def win_class(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def find_dup_popup():
    if not IS_WIN:
        return None
    return user32.FindWindowW(None, DUP_TITLE) or None


def press_no(hwnd):
    """팝업의 자식 컨트롤 목록을 돌려주고, No/아니오 버튼이 있으면 누른다."""
    children = []

    def cb(h, _):
        children.append((h, win_class(h), win_text(h)))
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    pressed = None
    for h, cls, text in children:
        if text.replace("&", "").strip().lower() in ("no", "아니오", "아니요", "아니오(n)", "no(n)"):
            user32.PostMessageW(h, 0x00F5, 0, 0)  # BM_CLICK
            pressed = text
            break
    return children, pressed


# ── 크롬 ─────────────────────────────────────────────────────
def find_chrome():
    cands = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    return next((c for c in cands if os.path.exists(c)), None)


def cdp_alive():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1) as r:
            return json.load(r)
    except OSError:
        return None


def ensure_chrome():
    info = cdp_alive()
    if info:
        return info, False
    chrome = find_chrome()
    if not chrome:
        sys.exit("크롬(chrome.exe)을 찾지 못했습니다. 크롬을 설치해 주세요.")
    first = not os.path.exists(PROFILE)
    subprocess.Popen([chrome, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
                      "--no-first-run", "--no-default-browser-check", "--start-maximized"])
    for _ in range(60):
        time.sleep(0.5)
        info = cdp_alive()
        if info:
            return info, first
    sys.exit("크롬은 떴지만 디버깅 포트에 접속하지 못했습니다. 크롬을 모두 닫고 다시 실행해 주세요.")


# ── 진단 ─────────────────────────────────────────────────────
def find_button(page, deadline):
    """모든 프레임에서 버튼을 찾는다. 돌려주는 값: (frame, 찾은 목록)"""
    while time.time() < deadline:
        for fr in page.frames:
            try:
                hits = fr.evaluate(FIND_JS, LABELS)
            except PlaywrightError:
                continue
            if hits:
                return fr, hits
        page.wait_for_timeout(100)
    return None, []


def frame_offset(page, fr):
    if fr == page.main_frame:
        return 0, 0
    box = fr.frame_element().bounding_box() or {"x": 0, "y": 0}
    return box["x"], box["y"]


def probe(page, url, rep, n):
    rep(f"\n========== [{n}] {time.strftime('%Y-%m-%d %H:%M:%S')} ==========")
    rep(f"URL: {url}")
    t0 = time.time()
    try:
        page.goto(url, wait_until="commit", timeout=LOAD_WAIT)
    except PlaywrightError as e:
        rep(f"이동 실패: {e.message.splitlines()[0]}")
        return
    rep(f"이동(commit): {int((time.time() - t0) * 1000)}ms  현재 주소: {page.url}")
    rep(f"navigator.webdriver = {page.evaluate('navigator.webdriver')}")

    fr, hits = find_button(page, t0 + LOAD_WAIT / 1000)
    load_ms = int((time.time() - t0) * 1000)
    try:
        body = page.inner_text("body", timeout=3000)
    except PlaywrightError:
        body = ""
    gone = [w for w in GONE_WORDS if w in body]
    rep(f"페이지 제목: {page.title()}")
    if gone:
        rep(f"판매중지/삭제 의심 문구: {gone}")
        i = body.find(gone[0])
        rep(f"  주변 글자: {body[max(0, i - 60):i + 80]!r}")

    if not hits:
        rep(f"결과: 버튼 글자 CAPTURE/ARMED 를 DOM에서 찾지 못함 ({load_ms}ms 대기)")
        rep("  → 셀업 확장이 이 크롬 프로필에서 동작하는지, 화면에 노란 버튼이 보이는지 확인하세요.")
        rep("  → 화면에 버튼이 보이는데 여기서 못 찾았다면 닫힌 shadow root 등 → 엔진 B 후보")
        rep("단서(오른쪽 아래 고정 요소 / 사용자 정의 태그):")
        for fr2 in page.frames:
            try:
                for h in fr2.evaluate(HINT_JS):
                    rep(f"  [{fr2.url[:50]}] {json.dumps(h, ensure_ascii=False)}")
            except PlaywrightError:
                pass
        return

    where = "메인 페이지" if fr == page.main_frame else f"iframe {fr.url[:80]}"
    rep(f"결과: 버튼 발견 {load_ms}ms / 위치: {where} / {len(hits)}개")
    for h in hits:
        rep("  " + json.dumps(h, ensure_ascii=False))
    target = next((h for h in hits if h["label"] == "CAPTURE" and h["rect"]["w"] > 0), None)
    if not target:
        rep("CAPTURE 상태의 보이는 버튼이 없어 클릭 시험은 건너뜀")
        return

    ans = input("\n클릭 시험을 할까요? (Enter=예, n=아니오) ").strip().lower()
    if ans == "n":
        return

    fr.evaluate(WATCH_JS, [target["idx"], LABELS])
    page.wait_for_timeout(CLICK_SETTLE)  # 셀업 핸들러가 붙을 때까지 (v1 5-4)
    ox, oy = frame_offset(page, fr)
    r = target["rect"]
    cx, cy = ox + r["x"] + r["w"] / 2, oy + r["y"] + r["h"] / 2
    page.mouse.move(cx, cy)
    page.wait_for_timeout(150)
    page.mouse.click(cx, cy)
    t_click = time.time()
    rep(f"클릭: 페이지 좌표 ({cx:.0f}, {cy:.0f})  [CDP 마우스 입력]")

    popup = None
    while time.time() - t_click < WATCH_MS / 1000:
        h = find_dup_popup()
        if h and not popup:
            popup = int((time.time() - t_click) * 1000)
            children, pressed = press_no(h)
            rep(f"중복 팝업 '{DUP_TITLE}' 감지: 클릭 후 {popup}ms")
            for _, cls, text in children:
                rep(f"  컨트롤: class={cls!r} text={text!r}")
            rep(f"  누른 버튼: {pressed!r}" if pressed else "  No 버튼을 찾지 못함 — 위 컨트롤 목록을 보내주세요")
        time.sleep(0.05)

    timeline = fr.evaluate(UNWATCH_JS)
    rep("글자 변화 타임라인 (감시 시작 기준 ms, 클릭은 약 " + str(CLICK_SETTLE + 150) + "ms):")
    for ms, s in timeline:
        rep(f"  {ms:>6}  {s}")
    armed = any("ARMED" in s for _, s in timeline)
    rep(f"판정: ARMED {'포착' if armed else '미포착'} / 중복팝업 {'있음' if popup is not None else '없음'}"
        + ("" if IS_WIN else "  (윈도우가 아니라 팝업 검사 안 함)"))


def main():
    rep = Report(REPORT)
    info, first = ensure_chrome()
    rep(f"\n##### 셀업 진단 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} / {info.get('Browser')} / 포트 {PORT}")
    if first:
        print("\n전용 크롬 프로필을 새로 만들었습니다.")
        print("  1) 방금 뜬 크롬에서 셀업 확장을 설치하고 셀업에 로그인하세요.")
        print("  2) 네이버 스마트스토어 상품 페이지 하나를 열어 노란 CAPTURE 버튼이 보이는지 확인하세요.")
        input("준비되면 Enter... ")

    urls = sys.argv[1:]
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.bring_to_front()
        n = 0
        while True:
            if urls:
                url = urls.pop(0)
            else:
                print("\n추천 순서: ① 새 상품 ② 이미 수집한 상품(중복) ③ 판매중지 상품"
                      "\n          ④ 크롬 창을 다른 창으로 가린 채 새 상품")
                url = input("검사할 상품 URL (Enter만 누르면 끝): ").strip()
            if not url:
                break
            n += 1
            try:
                probe(page, url, rep, n)
            except Exception:
                rep("오류:\n" + traceback.format_exc())
    rep(f"\n결과가 {REPORT} 에 저장되었습니다. 이 파일을 보내주세요.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code)
    except Exception:
        traceback.print_exc()
        print("\n오류가 났습니다. 위 내용을 캡처해서 보내주세요.")
    input("\nEnter를 누르면 창이 닫힙니다...")
