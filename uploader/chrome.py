"""판매자센터를 그 스토어 계정으로 바로 열기: 스토어마다 크롬 프로필을 정해 두고(그 프로필에 그 스토어 계정으로
로그인해 둠) 버튼을 누르면 그 프로필로 크롬을 연다. 아이디·비밀번호는 넣지 않는다 (네이버 캡차·2단계 인증)."""

import json
import os
import shutil
import subprocess
import sys

from . import config


def _candidates():
    if sys.platform.startswith("win"):
        out = []
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                out.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        return out
    if sys.platform == "darwin":
        return ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return [p for p in (shutil.which("google-chrome"), shutil.which("google-chrome-stable"), shutil.which("chromium")) if p]


def find_chrome(cfg=None):
    cfg = cfg or config.load()
    p = str(cfg.get("chrome_path") or "").strip().strip('"')
    if p and os.path.isfile(p):
        return p
    return next((c for c in _candidates() if c and os.path.isfile(c)), "")


def user_data_dir():
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    return os.path.expanduser("~/.config/google-chrome")


def profiles():
    """크롬 프로필 목록 [{dir, name, email}] — 크롬 'Local State' 파일에서 읽음 (크롬이 없으면 빈 목록)."""
    path = os.path.join(user_data_dir(), "Local State")
    try:
        with open(path, encoding="utf-8") as f:
            cache = (json.load(f).get("profile") or {}).get("info_cache") or {}
    except (OSError, ValueError):
        return []
    out = [{"dir": d, "name": v.get("name") or d, "email": v.get("user_name") or ""} for d, v in cache.items()]
    return sorted(out, key=lambda x: (x["dir"] != "Default", x["dir"]))


def open_url(url, profile, cfg=None):
    """그 프로필로 크롬을 열어 url로. {opened, reason}."""
    if os.environ.get("UPLOADER_FAKE_API") == "1":
        return {"opened": False, "reason": "시연 모드라 크롬을 열지 않습니다."}
    exe = find_chrome(cfg)
    if not exe:
        return {"opened": False, "reason": "크롬을 찾지 못했습니다. 설정 → 스토어 공통의 '크롬 위치'에 chrome.exe 경로를 넣어 주세요."}
    args = [exe, f"--profile-directory={profile}", url] if profile else [exe, url]
    try:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(args, close_fds=True, creationflags=flags) if flags else subprocess.Popen(args, close_fds=True, start_new_session=True)
    except OSError as e:
        return {"opened": False, "reason": f"크롬을 열지 못했습니다: {e}"}
    return {"opened": True}
