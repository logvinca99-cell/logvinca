#Requires AutoHotkey v2.0
#SingleInstance Force
CoordMode "Pixel", "Screen"
CoordMode "Mouse", "Screen"
SetTitleMatchMode 2
SendMode "Event"
SetKeyDelay 40, 40
SetMouseDelay 60

; ==========================================================
;  셀업(SmartSellUp) 상품 자동 수집 v19  (v8 기반)
;  ---------------------------------------------------------
;  수집 동작(주소 이동 → CAPTURE 찾기 → 대기 → 고정 오프셋 클릭 →
;  중복팝업 No)은 v8 과 같은 순서, 같은 방식입니다.
;
;  v8 에서 달라진 점
;   · 조작 창 : 스토어 주소 입력, 속도 선택, 시작/일시정지/중단,
;     진행률·수집/중복/실패·시간당 속도·남은 시간 표시
;   · 스토어 주소만 넣으면  주소 모으기 → 상품 수집  까지 자동
;   · 속도 3단계 : "안전" 은 v8 과 똑같은 대기시간,
;     "보통"/"빠름" 은 상품 사이 간격과 입력 대기만 줄임
;   · 이어하기는 done_urls.txt 기준 (이미 한 상품은 건너뜀, 묻지 않음)
;   · 연속 실패 시 종료하지 않고 쉬었다가 같은 상품부터 재개
;   · 늦게 뜬 중복 팝업이 다음 상품을 막지 않도록 매 상품 전에 확인
;
;  준비물 (같은 폴더)
;   - img\capture.png , img\armed.png   (v8 에서 쓰던 그대로)
;
;  단축키
;   F1 시작 / F2 즉시 종료 / F3 단발 테스트 / F4 일시정지·계속
; ==========================================================

; ---------- 경로 ----------
IMGDIR    := A_ScriptDir "\img\"
URLFILE   := A_ScriptDir "\urls.txt"
LOGFILE   := A_ScriptDir "\log.txt"
DONEFILE  := A_ScriptDir "\done_urls.txt"
FAILFILE  := A_ScriptDir "\fail_urls.txt"
STOREFILE := A_ScriptDir "\stores.txt"
HARVFILE  := A_ScriptDir "\harvested_stores.txt"

; ---------- 수집 설정 (v8 과 같은 값) ----------
TOL       := 25       ; 이미지 허용오차. 못 찾으면 45~60
LOAD_WAIT := 30000    ; 페이지 로딩 최대 대기 ms
POLL_MS   := 120      ; ARMED 폴링 간격 ms
USE_CLICK := true     ; true=버튼 클릭 / false=Alt+C 키전송
CLICK_OFF_X := 45     ; 클릭 지점 = 이미지 좌상단에서 이만큼 이동한 곳
CLICK_OFF_Y := 20
DUP_YES   := false    ; 중복팝업 : true=등록(Yes) / false=건너뜀(No)
DUP_TITLE := "기등록 상품 확인"
MAX_CONSEC := 3       ; 연속 실패 몇 회에 쉬어갈지

; ---------- 속도 단계 ----------
; 조작 창의 "속도" 에서 고릅니다. 숫자를 바꾸면 그 단계의 속도가 바뀝니다.
;            상품간격(최소,최대)  ARMED후  감시최대  클릭전   주소입력 대기
;                                  대기              대기     (^l, ^a, ^v 뒤)
PRESETS := [
    [3000, 6000, 1500, 8000, 1200, 300, 150, 300],   ; 1 안전 = v8 그대로
    [1000, 2000, 1000, 4000, 1200, 150,  80, 150],   ; 2 보통
    [ 300,  800,  700, 2500, 1000, 120,  60, 120]    ; 3 빠름
]
GAP_MIN := 0, GAP_MAX := 0, ARMED_EXTRA := 0, WATCH_MS := 0, SETTLE := 0
NAV1 := 0, NAV2 := 0, NAV3 := 0

; ---------- 연속 실패 시 휴식 ----------
REST_MIN  := 10       ; 쉬는 시간(분)
MAX_RESTS := 3        ; 쉬고 재개해도 계속 실패하면 이 횟수에서 멈춤

; ---------- 스토어 주소 모으기 ----------
LIST_WAIT := 3500         ; 스토어 페이지를 연 뒤 스크립트를 넣기 전 대기 ms
HARVEST_MAX_MIN := 180    ; 한 스토어 주소 모으기 최대 대기(분)

; 스토어 페이지 안에서 실행되는 스크립트.
; 목록(80개씩)을 한 쪽씩 fetch 로 받아 상품 주소를 모으고, 끝나면 화면을 주소 목록으로 바꾼다.
; ※ 주소창으로 실행하므로 큰따옴표, 백틱, #, %, // 주석을 쓰면 안 됩니다
HARVEST_JS := "
(
(async () => {
  const store = location.pathname.split('/')[1];
  if (!store) { document.title = 'HARVEST_FAIL no-store'; return; }
  const MAX_PAGE = 2000;
  const SIZE = 80;
  const ids = new Set();
  const sleep = ms => new Promise(s => setTimeout(s, ms));
  window.__stop = false;
  window.stopHarvest = () => { window.__stop = true; };
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;top:10px;right:10px;z-index:999999;background:black;'
    + 'color:lime;padding:14px 18px;font:13px monospace;border-radius:8px;'
    + 'white-space:pre;line-height:1.6;max-width:380px';
  document.body.appendChild(box);
  let page = 1, empty = 0, reqCount = 0, stopReason = '';
  const t0 = Date.now();
  document.title = 'HARVEST start';
  while (page <= MAX_PAGE) {
    if (window.__stop) { stopReason = 'user-stop'; break; }
    const url = '/' + store + '/category/ALL?st=RECENT&dt=IMAGE&page=' + page + '&size=' + SIZE;
    let text = '';
    try {
      const r = await fetch(url, { credentials: 'include' });
      if (r.status === 429 || r.status === 403) {
        box.textContent = 'blocked (' + r.status + ')\nwait 60s\ntotal ' + ids.size;
        document.title = 'HARVEST wait ' + r.status + ' / ' + ids.size;
        await sleep(60000);
        continue;
      }
      if (!r.ok) { stopReason = 'HTTP ' + r.status + ' (' + page + 'p)'; break; }
      text = await r.text();
    } catch (e) {
      await sleep(3000);
      continue;
    }
    reqCount++;
    const matches = text.match(/\/products\/\d{6,}/g) || [];
    if (matches.length === 0) { stopReason = page + 'p empty (last page)'; break; }
    const before = ids.size;
    matches.forEach(m => ids.add(location.origin + '/' + store + m));
    const gain = ids.size - before;
    const mins = ((Date.now() - t0) / 60000).toFixed(1);
    box.textContent = page + 'p / max ' + MAX_PAGE + '\n+' + gain + ' (links ' + matches.length + ')\n'
      + 'total ' + ids.size + '\n' + mins + 'min, req ' + reqCount;
    document.title = 'HARVEST ' + page + 'p / ' + ids.size;
    if (gain === 0) {
      if (++empty >= 3) { stopReason = page + 'p no-new (done)'; break; }
    } else {
      empty = 0;
    }
    page++;
    await sleep(1100 + Math.random() * 700);
  }
  if (!stopReason) stopReason = 'max page ' + MAX_PAGE;
  const list = [...ids];
  const pre = document.createElement('pre');
  pre.textContent = 'HARVEST_RESULT ' + list.length + ' / ' + stopReason + '\n' + list.join('\n');
  document.body.innerHTML = '';
  document.body.appendChild(pre);
  document.title = 'HARVEST_DONE ' + list.length;
})(); void 0
)"

; ---------- 상태 ----------
browserHwnd := 0
urls := []
running := false
paused := false
stopReq := false
logLines := []

statStart := 0
statDone := 0
statDup := 0
statFail := 0
statArmed := 0

; ==========================================================
;  조작 창
; ==========================================================
ui := Gui("+AlwaysOnTop", "셀업 자동 수집 v19")
ui.SetFont("s9", "Malgun Gothic")
ui.MarginX := 10
ui.MarginY := 8

ui.Add("Text", "Section", "스토어 주소 (한 줄에 하나)")
edStores := ui.Add("Edit", "xs w340 r5 -Wrap", FileExist(STOREFILE) ? Trim(FileRead(STOREFILE, "UTF-8"), "`r`n") : "")

ui.Add("Text", "xs y+10", "속도")
ddSpeed := ui.Add("DropDownList", "x+8 yp-3 w200 Choose2", ["안전 (v8 과 동일)", "보통", "빠름"])

btnStart := ui.Add("Button", "xs y+10 w108 h30", "▶ 시작 (F1)")
btnPause := ui.Add("Button", "x+8 w108 h30", "⏸ 일시정지 (F4)")
btnStop  := ui.Add("Button", "x+8 w108 h30", "■ 중단")

ui.SetFont("s10 bold")
txtStage := ui.Add("Text", "xs y+12 w340", "대기 중")
ui.SetFont("s9 norm")
barProg  := ui.Add("Progress", "xs w340 h14")
txtCount := ui.Add("Text", "xs w340", "수집 0 · 중복 0 · 실패 0 · 남음 0")
txtSpeed := ui.Add("Text", "xs w340", "")
txtItem  := ui.Add("Text", "xs w340 cGray", "")
edLog    := ui.Add("Edit", "xs w340 r8 ReadOnly -Wrap")

btnStart.OnEvent("Click", (*) => StartRun(false))
btnPause.OnEvent("Click", (*) => TogglePause())
btnStop.OnEvent("Click", (*) => RequestStop())
ui.OnEvent("Close", (*) => ExitApp())
ui.Show("x10 y10 NoActivate")

Say("준비 완료. 셀업 크롬 창에서 네이버 로그인 후 시작을 누르세요.")

; ==========================================================
;  단축키
; ==========================================================
F1:: StartRun(true)
F2:: ExitApp
F4:: TogglePause()

F3:: {
    global browserHwnd
    browserHwnd := WinGetID("A")
    ApplyPreset(ddSpeed.Value)

    pos := FindImage("capture.png")
    if !pos {
        MsgBox("CAPTURE 버튼을 못 찾았습니다.`n크롬 줌 100%, CAPTURE 상태인지 확인하세요.", , 262144)
        return
    }
    DoCapture(CenterOf(pos, "capture.png"))
    seen := WatchArmed(4000)
    msg := seen
        ? "ARMED 포착됨. 정상입니다.`nF1 으로 시작하세요."
        : "수집은 실행했습니다.`nARMED 를 못 봤어도 셀업에 들어왔다면 정상입니다."
    MsgBox(msg, , 262144)
}

; ==========================================================
;  시작 / 일시정지 / 중단
; ==========================================================
StartRun(fromHotkey) {
    global browserHwnd, running, paused, stopReq
    global statStart, statDone, statDup, statFail, statArmed

    if running
        return

    ; 어느 크롬 창에서 수집할지 정한다
    hwnd := 0
    if fromHotkey {
        a := WinExist("A")
        if (a && a != ui.Hwnd)
            hwnd := a
    }
    if !hwnd {
        ; 조작 창 버튼으로 시작한 경우 : 가장 최근에 쓴 크롬 창
        for h in WinGetList("ahk_exe chrome.exe") {
            if (WinGetTitle("ahk_id " h) != "") {
                hwnd := h
                break
            }
        }
    }
    if !hwnd {
        MsgBox("크롬 창을 찾지 못했습니다.`n셀업 크롬 창을 클릭한 다음 F1 을 눌러 주세요.", , 262144)
        return
    }
    browserHwnd := hwnd

    ; 스토어 목록 저장
    try FileDelete STOREFILE
    FileAppend edStores.Value "`n", STOREFILE, "UTF-8"

    ApplyPreset(ddSpeed.Value)

    running := true
    paused := false
    stopReq := false
    statStart := 0
    statDone := 0, statDup := 0, statFail := 0, statArmed := 0
    btnPause.Text := "⏸ 일시정지 (F4)"

    WinGetPos &bx, &by, &bw, &bh, "ahk_id " browserHwnd
    Say("=== 시작 / 속도 " ddSpeed.Text " / 창 '" SubStr(WinGetTitle("ahk_id " browserHwnd), 1, 30) "' "
      . bx "," by " " bw "x" bh " ===")

    SetTimer RunAll, -50
}

TogglePause() {
    global paused
    if !running
        return
    paused := !paused
    btnPause.Text := paused ? "▶ 계속 (F4)" : "⏸ 일시정지 (F4)"
    Say(paused ? "일시정지 (지금 하던 상품까지 처리하고 멈춥니다)" : "계속")
}

RequestStop() {
    global stopReq, paused
    if !running
        return
    stopReq := true
    paused := false
    Say("중단 요청 (지금 하던 상품까지 처리하고 멈춥니다)")
}

ApplyPreset(n) {
    global GAP_MIN, GAP_MAX, ARMED_EXTRA, WATCH_MS, SETTLE, NAV1, NAV2, NAV3
    p := PRESETS[n]
    GAP_MIN := p[1], GAP_MAX := p[2], ARMED_EXTRA := p[3], WATCH_MS := p[4]
    SETTLE := p[5], NAV1 := p[6], NAV2 := p[7], NAV3 := p[8]
}

; 일시정지 중이면 풀릴 때까지 기다린다. 중단 요청이면 false
Gate() {
    while (paused && !stopReq)
        Sleep 150
    return !stopReq
}

; 일시정지/중단을 살피며 기다린다. 중단 요청이면 false
Wait(ms) {
    endT := A_TickCount + ms
    while (A_TickCount < endT) {
        if !Gate()
            return false
        Sleep Max(10, Min(100, endT - A_TickCount))
    }
    return !stopReq
}

; ==========================================================
;  전체 흐름 : 스토어 → 주소 모으기 → 상품 수집
; ==========================================================
RunAll() {
    global running

    try {
        stores := ParseStores(edStores.Value)
        harvested := LoadLines(HARVFILE, true)
        known := LoadLines(URLFILE, false)

        ; urls.txt 가 줄바꿈 없이 끝났으면 새 주소가 이어 붙지 않게 줄바꿈 추가
        if FileExist(URLFILE) {
            t := FileRead(URLFILE, "UTF-8")
            if (t != "" && SubStr(t, -1) != "`n")
                FileAppend "`n", URLFILE, "UTF-8"
        }

        ; 1) urls.txt 에 이미 남아 있는 상품부터
        CollectPending("남은 상품")

        ; 2) 스토어마다 : 주소 모으기 → 수집
        for store in stores {
            if !Gate()
                break
            if !harvested.Has(store) {
                n := HarvestStore(store, known)
                if (n < 0) {
                    if !stopReq
                        Say("[목록] " store " 주소 모으기 실패 → 다음 스토어로")
                    continue
                }
                FileAppend store "`t" n "`t" FormatTime(A_Now, "yyyy-MM-dd HH:mm") "`n", HARVFILE, "UTF-8"
                harvested[store] := true
            }
            CollectPending(StoreName(store))
        }
    } catch as e {
        Say("오류 : " e.Message " (줄 " e.Line ")")
    }

    running := false
    SetStage(stopReq ? "중단됨" : "완료")
    txtItem.Text := ""
    Say("=== " (stopReq ? "중단" : "완료") " : 수집 " statDone " / 중복 " statDup " / 실패 " statFail
      . " / ARMED " statArmed " ===")
    if !stopReq
        SoundBeep 880, 300
}

; urls.txt 에서 아직 안 한 상품을 모두 수집
CollectPending(label) {
    global statStart

    LoadUrls()
    if (urls.Length = 0)
        return
    if !statStart
        statStart := A_TickCount
    Say("수집 시작 (" label ") : " urls.Length "개")
    RunLoop(label)
}

; urls.txt 에서 done_urls.txt, fail_urls.txt 에 없는 주소만 urls 에 담는다
LoadUrls() {
    global urls

    urls := []
    done := LoadLines(DONEFILE, false)
    fail := LoadLines(FAILFILE, false)
    seen := Map()

    if !FileExist(URLFILE)
        return

    for line in StrSplit(FileRead(URLFILE, "UTF-8"), "`n", "`r") {
        line := Trim(line)
        if !InStr(line, "/products/")
            continue
        if (seen.Has(line) || done.Has(line) || fail.Has(line))
            continue
        seen[line] := true
        urls.Push(line)
    }
}

; 파일의 각 줄을 Map 의 키로. firstCol=true 면 탭 앞부분만 키로 쓴다
LoadLines(path, firstCol) {
    m := Map()
    if !FileExist(path)
        return m
    for line in StrSplit(FileRead(path, "UTF-8"), "`n", "`r") {
        if (Trim(line) = "")
            continue
        if firstCol
            line := StrSplit(line, "`t")[1]
        m[Trim(line)] := true
    }
    return m
}

ParseStores(text) {
    out := []
    seen := Map()
    for line in StrSplit(text, "`n", "`r") {
        s := NormalizeStore(line)
        if (s != "" && !seen.Has(s)) {
            seen[s] := true
            out.Push(s)
        }
    }
    return out
}

; 어떤 형태의 주소든 https://smartstore.naver.com/<스토어명> 으로 정리. 인식 못 하면 ""
NormalizeStore(line) {
    if RegExMatch(line, "i)(smartstore|brand)\.naver\.com/([A-Za-z0-9_\-]+)", &m)
        return "https://" StrLower(m[1]) ".naver.com/" m[2]
    return ""
}

StoreName(store) {
    return RegExReplace(store, ".*/")
}

; ==========================================================
;  상품 수집 (v8 RunLoop)
; ==========================================================
RunLoop(label) {
    global statDone, statDup, statFail, statArmed, stopReq

    consec := 0
    rests := 0
    waitingFails := []      ; 연속 실패 중인 주소 (차단인지 그 상품 문제인지 아직 모름)
    total := urls.Length
    i := 1

    while (i <= total) {
        if !Gate()
            return

        UpdateUI(label, i, total)
        r := Collect(urls[i], i)

        if (r = 0) {
            statFail++
            consec++
            waitingFails.Push(urls[i])
            Say(i " [실패] " urls[i])

            if (consec >= MAX_CONSEC) {
                rests++
                if (rests > MAX_RESTS) {
                    Say("=== 쉬고 재개해도 연속 실패. 멈춥니다 ===")
                    Say("캡챠·차단 화면, 셀업 수집 세션, 인터넷을 확인하세요")
                    SoundBeep 440, 600
                    stopReq := true
                    return
                }
                Say("=== 연속 " consec "회 실패. " REST_MIN "분 쉬고 같은 상품부터 재개 (" rests "/" MAX_RESTS ") ===")
                SetStage("연속 실패 → " REST_MIN "분 휴식 (" rests "/" MAX_RESTS ")")
                SoundBeep 440, 300
                if !Wait(REST_MIN * 60000)
                    return
                ; 차단이었을 수 있으니 실패한 상품부터 다시
                i -= consec - 1
                statFail -= consec
                consec := 0
                waitingFails := []
                continue
            }
        } else {
            ; 성공이 나왔으니 앞선 실패는 그 상품 자체의 문제 → 실패 목록에 기록
            for u in waitingFails
                FileAppend u "`n", FAILFILE, "UTF-8"
            waitingFails := []
            consec := 0
            rests := 0

            if (r = 3)
                statDup++
            else {
                statDone++
                if (r = 2)
                    statArmed++
            }
            RecordDone(urls[i])
        }

        i++
        UpdateUI(label, Min(i, total), total)
        if !Wait(Random(GAP_MIN, GAP_MAX))
            return
    }

    for u in waitingFails
        FileAppend u "`n", FAILFILE, "UTF-8"
}

; 반환값 : 0=실패 / 1=수집실행(ARMED 미확인) / 2=ARMED 확인 / 3=중복이라 건너뜀
Collect(url, idx) {
    loop 3 {
        ; 늦게 뜬 중복 팝업이 남아 있으면 먼저 닫는다 (안 닫으면 이후 수집이 전부 무시됨)
        HandleDupPopup(idx)

        if !FocusBrowser()
            return 0

        if !GotoUrl(url)
            return 0

        if !WaitImage("capture.png", LOAD_WAIT) {
            Say(idx " [경고] 로딩 확인 실패 → 재시도")
            Sleep 2000
            continue
        }
        Sleep SETTLE

        pos := FindImage("capture.png")
        if !pos {
            Say(idx " [경고] 클릭 직전 버튼 소실 → 재시도")
            continue
        }

        FocusBrowser()
        DoCapture(CenterOf(pos, "capture.png"))

        return WatchAfterCapture(idx)
    }
    return 0
}

DoCapture(c) {
    if USE_CLICK
        Click c[1], c[2]
    else
        SendInput "!c"
}

WatchAfterCapture(idx) {
    seen := false
    endT := A_TickCount + WATCH_MS

    while (A_TickCount < endT) {
        if HandleDupPopup(idx) {
            FocusBrowser()
            Sleep 300
            ; No(건너뜀) 모드면 ARMED 가 안 뜨므로 더 기다릴 필요 없음
            if !DUP_YES
                return 3
            endT := A_TickCount + 3000
            continue
        }
        if !seen && FindImage("armed.png") {
            seen := true
            endT := A_TickCount + ARMED_EXTRA
        }
        Sleep POLL_MS
    }

    if !seen
        Say(idx " [정보] ARMED 미포착")

    return seen ? 2 : 1
}

WatchArmed(ms) {
    endT := A_TickCount + ms
    while (A_TickCount < endT) {
        if FindImage("armed.png")
            return true
        Sleep POLL_MS
    }
    return false
}

GotoUrl(url) {
    A_Clipboard := url
    if !ClipWait(2)
        return false
    Send "^l"
    Sleep NAV1
    Send "^a"
    Sleep NAV2
    Send "^v"
    Sleep NAV3
    Send "{Enter}"
    return true
}

HandleDupPopup(idx) {
    if !WinExist(DUP_TITLE)
        return false

    hwnd := WinExist(DUP_TITLE)
    WinActivate "ahk_id " hwnd
    Sleep 300

    btn := DUP_YES ? "Yes" : "No"
    ok := false
    try {
        ControlClick btn, "ahk_id " hwnd
        ok := true
    }
    if !ok {
        try ControlClick (DUP_YES ? "Button1" : "Button2"), "ahk_id " hwnd
    }
    Sleep 900

    if WinExist(DUP_TITLE) {
        WinGetPos &px, &py, &pw, &ph, "ahk_id " hwnd
        Click px + pw * (DUP_YES ? 0.63 : 0.85), py + ph * 0.83
        Sleep 800
    }

    WriteLog(idx " [중복팝업] " btn)
    return true
}

; 이미지 좌상단 좌표 + 오프셋 = 클릭 지점
CenterOf(pos, file) {
    return [pos[1] + CLICK_OFF_X, pos[2] + CLICK_OFF_Y]
}

FocusBrowser() {
    global stopReq
    if !WinExist("ahk_id " browserHwnd) {
        Say("=== 크롬 창이 사라짐. 멈춥니다 (셀업 수집 세션이 끊겼을 수 있음) ===")
        SoundBeep 440, 600
        stopReq := true
        return false
    }
    if WinGetMinMax("ahk_id " browserHwnd) = -1
        WinRestore "ahk_id " browserHwnd
    if WinActive("ahk_id " browserHwnd)
        return true
    WinActivate "ahk_id " browserHwnd
    if !WinWaitActive("ahk_id " browserHwnd, , 5)
        return false
    Sleep 300
    return true
}

FindImage(file) {
    if browserHwnd && WinExist("ahk_id " browserHwnd) {
        WinGetPos &x, &y, &w, &h, "ahk_id " browserHwnd
        x1 := x, y1 := y, x2 := x + w, y2 := y + h
    } else {
        x1 := SysGet(76), y1 := SysGet(77)
        x2 := x1 + SysGet(78), y2 := y1 + SysGet(79)
    }

    try {
        if ImageSearch(&fx, &fy, x1, y1, x2, y2, "*" TOL " " IMGDIR file)
            return [fx, fy]
    } catch as e {
        MsgBox("이미지 파일 오류: " file "`n" e.Message "`n`nimg 폴더에 capture.png, armed.png 가 있는지 확인하세요.", , 262144)
        ExitApp
    }
    return 0
}

WaitImage(file, timeout) {
    endT := A_TickCount + timeout
    while (A_TickCount < endT) {
        if FindImage(file)
            return true
        Sleep 350
    }
    return false
}

; ==========================================================
;  스토어 전체 상품 주소 모으기
;   1) 스토어 페이지를 연다
;   2) 주소창에 javascript:<HARVEST_JS> 를 넣어 페이지 안에서 실행한다
;      진행 상황은 탭 제목(HARVEST 12p / 960)에 표시된다
;   3) 제목이 HARVEST_DONE 이 되면 화면이 주소 목록으로 바뀌어 있으므로
;      전체 복사해서 urls.txt 에 추가한다
;  새로 추가한 주소 수를 돌려준다. 실패하면 -1
; ==========================================================
HarvestStore(store, known) {
    SetStage("주소 모으는 중 : " StoreName(store))
    barProg.Value := 0
    Say("[목록] " store " 주소 모으기 시작")

    if !FocusBrowser()
        return -1
    if !GotoUrl(store)
        return -1
    if !Wait(LIST_WAIT)
        return -1

    ; ---- 스크립트 실행 ----
    ; 크롬은 붙여넣은 글자 맨 앞의 javascript: 를 지우므로 그 부분만 직접 입력한다
    js := RegExReplace(HARVEST_JS, "\R", " ")
    FocusBrowser()
    A_Clipboard := js
    if !ClipWait(2)
        return -1
    Send "^l"
    Sleep 300
    SendText "javascript:"
    Sleep 200
    Send "^v"
    Sleep 400
    Send "{Enter}"

    ; ---- 시작 확인 ----
    if !WaitTitle("HARVEST", 15000) {
        if stopReq
            return -1
        ; 자동 실행이 안 되면 사람이 콘솔에 붙여넣을 수 있게 한다
        A_Clipboard := js
        Say("[목록] 스크립트 자동 실행 실패")
        Say("→ 크롬에서 F12 > Console 에 Ctrl+V, Enter 를 해 주세요 (5분 대기)")
        SetStage("직접 실행 필요 : F12 > Console > Ctrl+V > Enter")
        SoundBeep 660, 400
        if !WaitTitle("HARVEST", 300000)
            return -1
        SetStage("주소 모으는 중 : " StoreName(store))
    }

    ; ---- 끝날 때까지 대기 ----
    endT := A_TickCount + HARVEST_MAX_MIN * 60000
    loop {
        if !Gate()
            return -1
        title := WinGetTitle("ahk_id " browserHwnd)
        if InStr(title, "HARVEST_DONE")
            break
        if InStr(title, "HARVEST_FAIL") {
            Say("[목록] " store " : " title)
            return -1
        }
        if (A_TickCount > endT) {
            Say("[목록] " store " : " HARVEST_MAX_MIN "분 안에 끝나지 않음")
            return -1
        }
        if RegExMatch(title, "HARVEST[^-]*", &m)
            txtItem.Text := Trim(m[0])
        Sleep 500
    }
    Sleep 500

    ; ---- 결과 복사 (화면은 주소 목록 글자뿐이라 아무 데나 눌러도 안전) ----
    txt := ""
    loop 3 {
        FocusBrowser()
        WinGetPos &wx, &wy, &ww, &wh, "ahk_id " browserHwnd
        Click wx + ww // 2, wy + wh // 2
        Sleep 300
        A_Clipboard := ""
        Send "^a"
        Sleep 200
        Send "^c"
        if (ClipWait(20) && InStr(A_Clipboard, "HARVEST_RESULT")) {
            txt := A_Clipboard
            break
        }
        Sleep 1000
    }
    if (txt = "") {
        Say("[목록] " store " : 결과 복사 실패")
        return -1
    }

    added := 0
    found := 0
    buf := ""
    for line in StrSplit(txt, "`n", "`r") {
        line := Trim(line)
        if !InStr(line, "/products/")
            continue
        found++
        if !known.Has(line) {
            known[line] := true
            buf .= line "`n"
            added++
        }
    }
    if (buf != "")
        FileAppend buf, URLFILE, "UTF-8"

    Say("[목록] " StoreName(store) " 완료 : 상품 " found "개, 신규 " added "개")
    txtItem.Text := ""
    return found ? added : -1
}

; 크롬 창 제목에 글자가 나타날 때까지 기다린다
WaitTitle(needle, ms) {
    endT := A_TickCount + ms
    while (A_TickCount < endT) {
        if stopReq
            return false
        if InStr(WinGetTitle("ahk_id " browserHwnd), needle)
            return true
        Sleep 300
    }
    return false
}

; ==========================================================
;  화면 표시 / 기록
; ==========================================================
SetStage(t) {
    txtStage.Text := t
}

UpdateUI(label, i, total) {
    SetStage("수집 중 : " label "  " i " / " total)
    barProg.Value := total ? Round(i / total * 100) : 0
    txtCount.Text := "수집 " statDone " · 중복 " statDup " · 실패 " statFail " · 남음 " (total - i)
    txtItem.Text := (i <= urls.Length) ? urls[i] : ""

    processed := statDone + statDup + statFail
    if (statStart && processed > 0) {
        perItem := (A_TickCount - statStart) / 1000 / processed
        etaMin := Round((total - i) * perItem / 60)
        txtSpeed.Text := "개당 " Round(perItem, 1) "초 · 시간당 " Round(3600 / perItem) "개 · 남은 시간 "
            . (etaMin >= 60 ? Round(etaMin / 60, 1) "시간" : etaMin "분")
    }
}

RecordDone(url) {
    FileAppend url "`n", DONEFILE, "UTF-8"
}

WriteLog(t) {
    FileAppend FormatTime(A_Now, "MM-dd HH:mm:ss") "  " t "`n", LOGFILE, "UTF-8"
}

; 파일과 조작 창에 함께 기록
Say(t) {
    WriteLog(t)
    logLines.Push(FormatTime(A_Now, "HH:mm:ss") " " t)
    while (logLines.Length > 60)
        logLines.RemoveAt(1)
    s := ""
    for line in logLines
        s .= line "`r`n"
    edLog.Value := s
    SendMessage 0x115, 7, 0, edLog      ; 맨 아래로 스크롤
}
