#Requires AutoHotkey v2.0
#SingleInstance Force
CoordMode "Pixel", "Screen"
CoordMode "Mouse", "Screen"
SetTitleMatchMode 2
SendMode "Event"
SetKeyDelay 40, 40
SetMouseDelay 60

; ==========================================================
;  셀업(SmartSellUp) 상품 자동 수집 v21  (v8 기반)
;  ---------------------------------------------------------
;  수집 동작(주소 이동 → CAPTURE 찾기 → 대기 → 고정 오프셋 클릭 →
;  중복팝업 No)은 v8 과 같은 순서, 같은 방식입니다.
;
;  조작 창
;   · 스토어 목록 : 스토어별 모은 주소 / 완료 / 실패 / 남음 / 상태
;     체크한 스토어만 작업합니다
;   · 수집 시작   : 주소가 없는 스토어만 주소를 모으고, 남은 상품을 수집
;                   (이미 모은 스토어는 다시 모으지 않고 바로 이어서 수집)
;   · 주소만 모으기 : 수집 없이 주소만 모음
;   · "이미 모은 스토어도 주소 다시 모으기" 를 켜면 신상품을 추가로 모음
;   · 속도 4단계 : "안전" 은 v8 과 똑같은 대기시간, "최고속" 은 ARMED 확인 생략
;   · 속도 줄 끝의 [이동 · 대기 · 클릭후] 는 상품 하나에서 각 구간에 걸린 평균 초
;
;  파일 (같은 폴더)
;   - img\capture.png , img\armed.png   (v8 에서 쓰던 그대로)
;   - stores.txt            스토어 목록과 체크 상태
;   - urls.txt              모은 상품 주소 전체
;   - done_urls.txt         수집했거나 중복으로 건너뛴 주소 (다시 안 들어감)
;   - fail_urls.txt         실패한 주소 (다시 시도하려면 이 파일을 지움)
;   - harvested_stores.txt  스토어별 주소 모은 기록
;
;  단축키
;   F1 수집 시작 / F2 즉시 종료 / F3 단발 테스트 / F4 일시정지·계속
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
;   1,2 상품간격(최소,최대)   3 ARMED 본 뒤 대기   4 클릭 후 감시 최대
;   5 클릭 전 대기            6,7,8 주소 입력 대기 (^l, ^a, ^v 뒤)
;   9 키 입력 간격            10 ARMED 이미지 확인 (1=함, 0=안 함)
; ARMED 확인을 끄면 클릭 후 4번 시간만큼 중복 팝업만 살피고 바로 넘어갑니다.
PRESETS := [
    [3000, 6000, 1500, 8000, 1200, 300, 150, 300, 40, 1],   ; 1 안전 = v8 그대로
    [1000, 2000, 1000, 4000, 1200, 150,  80, 150, 40, 1],   ; 2 보통
    [ 300,  800,  700, 2500, 1000, 120,  60, 120, 25, 1],   ; 3 빠름
    [   0,  200,  600,  700,  900,  60,  30,  60, 10, 0]    ; 4 최고속
]
GAP_MIN := 0, GAP_MAX := 0, ARMED_EXTRA := 0, WATCH_MS := 0, SETTLE := 0
NAV1 := 0, NAV2 := 0, NAV3 := 0, KEYD := 40, USE_ARMED := 1

; ---------- 이미지 탐색 범위 ----------
; 버튼을 한 번 찾은 뒤에는 그 주변만 찾습니다 (창 전체를 훑는 것보다 훨씬 빠름).
; 주변에서 못 찾으면 창 전체를 다시 찾습니다.
USE_REGION := true
REGION_PAD := 160
lastX := 0
lastY := 0

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
jobStores := []     ; 이번에 작업할 스토어
jobMode := "run"    ; "run" = 주소 모으기 + 수집 / "harvest" = 주소만
stats := Map()      ; 스토어 → {total, done, fail}  (urls.txt / done_urls.txt / fail_urls.txt 에서 계산)
harv := Map()       ; 스토어 → {n, date, state}     (harvested_stores.txt)
note := Map()       ; 스토어 → 지금 진행 중인 작업 표시

statStart := 0
statDone := 0
statDup := 0
statFail := 0
statArmed := 0
phN := 0, phNav := 0, phLoad := 0, phWatch := 0   ; 구간별 소요시간 합계 (속도 진단용)

; ==========================================================
;  조작 창
; ==========================================================
ui := Gui("+AlwaysOnTop", "셀업 자동 수집 v21")
ui.SetFont("s9", "Malgun Gothic")
ui.MarginX := 10
ui.MarginY := 8

ui.Add("Text", "Section", "스토어 목록  (체크한 스토어만 작업합니다)")
lv := ui.Add("ListView", "xs w570 r9 Checked Grid", ["스토어", "모은 주소", "완료", "실패", "남음", "상태"])
lv.ModifyCol(1, 185)
lv.ModifyCol(2, "62 Integer")
lv.ModifyCol(3, "55 Integer")
lv.ModifyCol(4, "45 Integer")
lv.ModifyCol(5, "55 Integer")
lv.ModifyCol(6, 145)

ui.Add("Text", "xs y+8", "스토어 추가 (주소를 붙여넣기, 여러 줄 가능)")
edAdd  := ui.Add("Edit", "xs w330 r2 -Wrap")
btnAdd := ui.Add("Button", "x+6 w74 h38", "추가")
btnDel := ui.Add("Button", "x+6 w74 h38", "선택 삭제")
btnAll := ui.Add("Button", "x+6 w74 h38", "전체 체크")

ui.Add("Text", "xs y+10", "속도")
ddSpeed := ui.Add("DropDownList", "x+8 yp-3 w150 Choose3", ["안전 (v8 과 동일)", "보통", "빠름", "최고속"])
chkRe   := ui.Add("Checkbox", "x+14 yp+3", "이미 모은 스토어도 주소 다시 모으기 (신상품 추가)")

btnStart := ui.Add("Button", "xs y+10 w150 h32", "▶ 수집 시작 (F1)")
btnHarv  := ui.Add("Button", "x+6 w130 h32", "주소만 모으기")
btnPause := ui.Add("Button", "x+6 w136 h32", "⏸ 일시정지 (F4)")
btnStop  := ui.Add("Button", "x+6 w136 h32", "■ 중단")

ui.SetFont("s10 bold")
txtStage := ui.Add("Text", "xs y+12 w570", "대기 중")
ui.SetFont("s9 norm")
barProg  := ui.Add("Progress", "xs w570 h14")
txtCount := ui.Add("Text", "xs w570", "")
txtSpeed := ui.Add("Text", "xs w570", "")
txtItem  := ui.Add("Text", "xs w570 cGray", "")
edLog    := ui.Add("Edit", "xs w570 r7 ReadOnly -Wrap")

btnStart.OnEvent("Click", (*) => StartRun(false, "run"))
btnHarv.OnEvent("Click", (*) => StartRun(false, "harvest"))
btnPause.OnEvent("Click", (*) => TogglePause())
btnStop.OnEvent("Click", (*) => RequestStop())
btnAdd.OnEvent("Click", (*) => AddStores())
btnDel.OnEvent("Click", (*) => DelStores())
btnAll.OnEvent("Click", (*) => ToggleAll())
ui.OnEvent("Close", (*) => ExitApp())
OnExit((*) => SaveStores())

InitStores()
ui.Show("x10 y10 NoActivate")
Say("준비 완료. 셀업 크롬 창에서 네이버 로그인 후 스토어를 체크하고 시작하세요.")

; ==========================================================
;  단축키
; ==========================================================
F1:: StartRun(true, "run")
F2:: ExitApp
F4:: TogglePause()

F3:: {
    global browserHwnd
    browserHwnd := WinGetID("A")
    ApplyPreset(ddSpeed.Value)
    SetKeyDelay KEYD, KEYD

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
;  스토어 목록 관리
; ==========================================================

; 시작할 때 : stores.txt, harvested_stores.txt, urls.txt 를 읽어 목록을 채운다
InitStores() {
    global harv

    ; 주소 모은 기록  (스토어 TAB 개수 TAB 날짜 TAB done|partial)
    harv := Map()
    if FileExist(HARVFILE) {
        for line in StrSplit(FileRead(HARVFILE, "UTF-8"), "`n", "`r") {
            p := StrSplit(line, "`t")
            if (p.Length < 1 || Trim(p[1]) = "")
                continue
            h := {n: "", date: "", state: "done"}
            if (p.Length >= 2)
                h.n := p[2]
            if (p.Length >= 3)
                h.date := p[3]
            if (p.Length >= 4 && Trim(p[4]) != "")
                h.state := Trim(p[4])
            harv[Trim(p[1])] := h
        }
    }

    RefreshStats()

    lv.Opt("-Redraw")
    if FileExist(STOREFILE) {
        for line in StrSplit(FileRead(STOREFILE, "UTF-8"), "`n", "`r") {
            st := NormalizeStore(line)
            if (st = "" || RowOf(st))
                continue
            p := StrSplit(line, "`t")
            checked := !(p.Length >= 2 && Trim(p[2]) = "0")
            lv.Add(checked ? "Check" : "", StrReplace(st, "https://"))
        }
    } else {
        ; 처음 실행 : urls.txt 에 이미 들어 있는 스토어를 목록에 올린다
        for st, v in stats
            lv.Add("Check", StrReplace(st, "https://"))
    }
    lv.Opt("+Redraw")
    UpdateAllRows()
}

; urls.txt 를 스토어별로 세고, 그중 완료(done)·실패(fail) 개수를 구한다
RefreshStats() {
    global stats

    stats := Map()
    done := LoadLines(DONEFILE, false)
    fail := LoadLines(FAILFILE, false)
    seen := Map()

    if !FileExist(URLFILE)
        return

    for line in StrSplit(FileRead(URLFILE, "UTF-8"), "`n", "`r") {
        line := Trim(line)
        p := InStr(line, "/products/")
        if (!p || seen.Has(line))
            continue
        seen[line] := true
        st := SubStr(line, 1, p - 1)
        if !stats.Has(st)
            stats[st] := {total: 0, done: 0, fail: 0}
        v := stats[st]
        v.total++
        if done.Has(line)
            v.done++
        else if fail.Has(line)
            v.fail++
    }
}

StatOf(store) {
    if !stats.Has(store)
        stats[store] := {total: 0, done: 0, fail: 0}
    return stats[store]
}

RowOf(store) {
    name := StrReplace(store, "https://")
    loop lv.GetCount() {
        if (lv.GetText(A_Index, 1) = name)
            return A_Index
    }
    return 0
}

StatusText(store) {
    if (note.Has(store) && note[store] != "")
        return note[store]

    v := StatOf(store)
    left := v.total - v.done - v.fail

    if (harv.Has(store) && harv[store].state = "partial")
        return "주소 일부만 모음 (중단됨)"
    if (v.total = 0)
        return "주소 없음"
    if (left = 0)
        return "수집 완료"
    if (v.done + v.fail > 0)
        return "이어하기 가능"
    if harv.Has(store)
        return "주소 모음 " SubStr(harv[store].date, 6)
    return "주소 모음"
}

UpdateRow(store) {
    r := RowOf(store)
    if !r
        return
    v := StatOf(store)
    lv.Modify(r, "Col2", v.total, v.done, v.fail, v.total - v.done - v.fail, StatusText(store))
}

UpdateAllRows() {
    loop lv.GetCount()
        UpdateRow("https://" lv.GetText(A_Index, 1))
}

AddStores() {
    added := 0
    for st in ParseStores(edAdd.Value) {
        if RowOf(st)
            continue
        lv.Add("Check", StrReplace(st, "https://"))
        UpdateRow(st)
        added++
    }
    edAdd.Value := ""
    SaveStores()
    if !added
        Say("추가할 새 스토어 주소가 없습니다 (smartstore.naver.com/... 형태인지 확인)")
}

; 목록에서만 뺀다. 모아 둔 주소와 수집 기록 파일은 그대로 둔다
DelStores() {
    rows := []
    r := 0
    while (r := lv.GetNext(r))
        rows.Push(r)
    if (rows.Length = 0) {
        Say("삭제할 스토어 줄을 먼저 클릭해서 선택하세요")
        return
    }
    loop rows.Length
        lv.Delete(rows[rows.Length - A_Index + 1])
    SaveStores()
}

ToggleAll() {
    static on := false
    on := !on
    lv.Modify(0, on ? "Check" : "-Check")
    btnAll.Text := on ? "전체 해제" : "전체 체크"
}

CheckedStores() {
    out := []
    r := 0
    while (r := lv.GetNext(r, "Checked"))
        out.Push("https://" lv.GetText(r, 1))
    return out
}

SaveStores() {
    buf := ""
    loop lv.GetCount() {
        isChecked := (lv.GetNext(A_Index - 1, "Checked") = A_Index)
        buf .= "https://" lv.GetText(A_Index, 1) "`t" (isChecked ? 1 : 0) "`n"
    }
    try FileDelete STOREFILE
    if (buf != "")
        FileAppend buf, STOREFILE, "UTF-8"
}

SaveHarv() {
    buf := ""
    for st, h in harv
        buf .= st "`t" h.n "`t" h.date "`t" h.state "`n"
    try FileDelete HARVFILE
    if (buf != "")
        FileAppend buf, HARVFILE, "UTF-8"
}

; ==========================================================
;  시작 / 일시정지 / 중단
; ==========================================================
StartRun(fromHotkey, mode) {
    global browserHwnd, running, paused, stopReq, jobStores, jobMode
    global statStart, statDone, statDup, statFail, statArmed

    if running
        return

    jobStores := CheckedStores()
    if (jobStores.Length = 0) {
        MsgBox("작업할 스토어를 체크해 주세요.", , 262144)
        return
    }
    jobMode := mode

    ; 어느 크롬 창에서 작업할지 정한다
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

    SaveStores()
    ApplyPreset(ddSpeed.Value)

    running := true
    paused := false
    stopReq := false
    statStart := 0
    statDone := 0, statDup := 0, statFail := 0, statArmed := 0
    btnPause.Text := "⏸ 일시정지 (F4)"

    WinGetPos &bx, &by, &bw, &bh, "ahk_id " browserHwnd
    Say("=== " (mode = "run" ? "수집 시작" : "주소만 모으기") " / 스토어 " jobStores.Length "곳 / 속도 " ddSpeed.Text
      . " / 창 '" SubStr(WinGetTitle("ahk_id " browserHwnd), 1, 30) "' " bx "," by " " bw "x" bh " ===")

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
    Say("중단 요청 (지금 하던 것까지 처리하고 멈춥니다. 진행 상황은 저장됩니다)")
}

ApplyPreset(n) {
    global GAP_MIN, GAP_MAX, ARMED_EXTRA, WATCH_MS, SETTLE, NAV1, NAV2, NAV3, KEYD, USE_ARMED
    p := PRESETS[n]
    GAP_MIN := p[1], GAP_MAX := p[2], ARMED_EXTRA := p[3], WATCH_MS := p[4]
    SETTLE := p[5], NAV1 := p[6], NAV2 := p[7], NAV3 := p[8]
    KEYD := p[9], USE_ARMED := p[10]
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
;  전체 흐름 : 체크한 스토어마다  (필요하면) 주소 모으기 → 상품 수집
; ==========================================================
RunAll() {
    global running, phN, phNav, phLoad, phWatch

    SetKeyDelay KEYD, KEYD
    phN := 0, phNav := 0, phLoad := 0, phWatch := 0

    try {
        known := LoadLines(URLFILE, false)

        ; urls.txt 가 줄바꿈 없이 끝났으면 새 주소가 이어 붙지 않게 줄바꿈 추가
        if FileExist(URLFILE) {
            t := FileRead(URLFILE, "UTF-8")
            if (t != "" && SubStr(t, -1) != "`n")
                FileAppend "`n", URLFILE, "UTF-8"
        }

        for store in jobStores {
            if !Gate()
                break

            ; 주소를 모아야 하는 경우 : 아직 주소가 없음 / 지난번에 모으다 중단됨 / "다시 모으기" 체크
            v := StatOf(store)
            need := false
            if chkRe.Value
                need := true
            else if (v.total = 0)
                need := true
            else if (harv.Has(store) && harv[store].state = "partial")
                need := true

            if need {
                HarvestStore(store, known)
                note[store] := ""
                UpdateRow(store)
                if stopReq
                    break
            } else if (jobMode = "harvest") {
                Say("[목록] " StoreName(store) " : 이미 모은 주소 " v.total "개 사용 (다시 모으려면 체크박스를 켜세요)")
            }

            if (jobMode = "run")
                CollectStore(store)
        }
    } catch as e {
        Say("오류 : " e.Message " (줄 " e.Line ")")
    }

    running := false
    for st in jobStores
        note[st] := ""
    RefreshStats()
    UpdateAllRows()
    SetStage(stopReq ? "중단됨 (다시 시작하면 이어서 합니다)" : "완료")
    txtItem.Text := ""
    Say("=== " (stopReq ? "중단" : "완료") " : 수집 " statDone " / 중복 " statDup " / 실패 " statFail
      . " / ARMED " statArmed " ===")
    if !stopReq
        SoundBeep 880, 300
}

; 한 스토어에서 아직 안 한 상품을 모두 수집
CollectStore(store) {
    global statStart

    LoadUrls(store)
    if (urls.Length = 0) {
        Say(StoreName(store) " : 남은 상품 없음")
        return
    }
    if !statStart
        statStart := A_TickCount
    Say("수집 시작 (" StoreName(store) ") : 남은 " urls.Length "개")
    note[store] := "수집 중"
    UpdateRow(store)
    RunLoop(store)
    note[store] := ""
    UpdateRow(store)
}

; urls.txt 에서 이 스토어 주소 중 done_urls.txt, fail_urls.txt 에 없는 것만 urls 에 담는다
LoadUrls(store) {
    global urls

    urls := []
    done := LoadLines(DONEFILE, false)
    fail := LoadLines(FAILFILE, false)
    seen := Map()
    prefix := store "/products/"

    if !FileExist(URLFILE)
        return

    for line in StrSplit(FileRead(URLFILE, "UTF-8"), "`n", "`r") {
        line := Trim(line)
        if (SubStr(line, 1, StrLen(prefix)) != prefix)
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
RunLoop(store) {
    global statDone, statDup, statFail, statArmed, stopReq

    label := StoreName(store)
    v := StatOf(store)
    consec := 0
    rests := 0
    waitingFails := []      ; 연속 실패 중인 주소 (차단인지 그 상품 문제인지 아직 모름)
    total := urls.Length
    i := 1

    while (i <= total) {
        if !Gate()
            break

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
                note[store] := "연속 실패 → 휴식 중"
                UpdateRow(store)
                SoundBeep 440, 300
                if !Wait(REST_MIN * 60000)
                    return
                note[store] := "수집 중"
                ; 차단이었을 수 있으니 실패한 상품부터 다시
                i -= consec - 1
                statFail -= consec
                consec := 0
                waitingFails := []
                continue
            }
        } else {
            ; 성공이 나왔으니 앞선 실패는 그 상품 자체의 문제 → 실패 목록에 기록
            for u in waitingFails {
                FileAppend u "`n", FAILFILE, "UTF-8"
                v.fail++
            }
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
            v.done++
        }

        UpdateRow(store)
        i++
        UpdateUI(label, Min(i, total), total)
        if !Wait(Random(GAP_MIN, GAP_MAX))
            break
    }

    ; 끝까지 돌았을 때만 남은 실패를 확정 (중단이면 다음에 다시 시도)
    if (i > total) {
        for u in waitingFails {
            FileAppend u "`n", FAILFILE, "UTF-8"
            v.fail++
        }
    }
}

; 반환값 : 0=실패 / 1=수집실행(ARMED 미확인) / 2=ARMED 확인 / 3=중복이라 건너뜀
Collect(url, idx) {
    global phN, phNav, phLoad, phWatch

    loop 3 {
        ; 늦게 뜬 중복 팝업이 남아 있으면 먼저 닫는다 (안 닫으면 이후 수집이 전부 무시됨)
        HandleDupPopup(idx)

        if !FocusBrowser()
            return 0

        t0 := A_TickCount
        if !GotoUrl(url)
            return 0
        t1 := A_TickCount

        if !WaitImage("capture.png", LOAD_WAIT) {
            Say(idx " [경고] 로딩 확인 실패 → 재시도")
            Sleep 2000
            continue
        }
        Sleep SETTLE

        ; 앞 상품의 중복 팝업이 이제야 떴으면 닫고 진행
        if HandleDupPopup(idx)
            FocusBrowser()

        pos := FindImage("capture.png")
        if !pos {
            Say(idx " [경고] 클릭 직전 버튼 소실 → 재시도")
            continue
        }

        FocusBrowser()
        t2 := A_TickCount
        DoCapture(CenterOf(pos, "capture.png"))
        r := WatchAfterCapture(idx)

        phN++
        phNav += t1 - t0
        phLoad += t2 - t1
        phWatch += A_TickCount - t2
        return r
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
        if !USE_ARMED {
            ; ARMED 확인 안 함 : 중복 팝업만 짧게 살핀다
            Sleep 50
            continue
        }
        if !seen && FindImage("armed.png", false) {
            seen := true
            endT := A_TickCount + ARMED_EXTRA
        }
        Sleep POLL_MS
    }

    if (USE_ARMED && !seen)
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

; allowFull=false 면 주변에서 못 찾았을 때 창 전체를 다시 찾지 않는다 (ARMED 처럼 없는 게 보통인 경우)
FindImage(file, allowFull := true) {
    global lastX, lastY

    if browserHwnd && WinExist("ahk_id " browserHwnd) {
        WinGetPos &x, &y, &w, &h, "ahk_id " browserHwnd
        x1 := x, y1 := y, x2 := x + w, y2 := y + h
    } else {
        x1 := SysGet(76), y1 := SysGet(77)
        x2 := x1 + SysGet(78), y2 := y1 + SysGet(79)
    }

    try {
        ; 1) 지난번에 찾은 위치 주변
        if (USE_REGION && (lastX || lastY)) {
            rx1 := Max(x1, lastX - REGION_PAD), ry1 := Max(y1, lastY - REGION_PAD)
            rx2 := Min(x2, lastX + REGION_PAD * 2), ry2 := Min(y2, lastY + REGION_PAD)
            if ImageSearch(&fx, &fy, rx1, ry1, rx2, ry2, "*" TOL " " IMGDIR file)
                return [fx, fy]
            if !allowFull
                return 0
        }
        ; 2) 창 전체
        if ImageSearch(&fx, &fy, x1, y1, x2, y2, "*" TOL " " IMGDIR file) {
            if InStr(file, "capture") {
                lastX := fx
                lastY := fy
            }
            return [fx, fy]
        }
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
;      진행 상황은 탭 제목(HARVEST 12p / 960)에 표시되고 스토어 목록의 "상태" 칸에 보인다
;   3) 제목이 HARVEST_DONE 이 되면 화면이 주소 목록으로 바뀌어 있으므로
;      전체 복사해서 urls.txt 에 추가한다
;   · 도중에 중단을 누르면 그때까지 모은 주소를 저장하고 "일부만 모음" 으로 기록한다
;  성공하면 true
; ==========================================================
HarvestStore(store, known) {
    SetStage("주소 모으는 중 : " StoreName(store))
    barProg.Value := 0
    note[store] := "주소 모으는 중"
    UpdateRow(store)
    Say("[목록] " store " 주소 모으기 시작")

    if !FocusBrowser()
        return false
    if !GotoUrl(store)
        return false
    if !Wait(LIST_WAIT)
        return false

    ; ---- 스크립트 실행 ----
    ; 크롬은 붙여넣은 글자 맨 앞의 javascript: 를 지우므로 그 부분만 직접 입력한다
    js := RegExReplace(HARVEST_JS, "\R", " ")
    FocusBrowser()
    A_Clipboard := js
    if !ClipWait(2)
        return false
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
            return false
        ; 자동 실행이 안 되면 사람이 콘솔에 붙여넣을 수 있게 한다
        A_Clipboard := js
        Say("[목록] 스크립트 자동 실행 실패")
        Say("→ 크롬에서 F12 > Console 에 Ctrl+V, Enter 를 해 주세요 (5분 대기)")
        SetStage("직접 실행 필요 : F12 > Console > Ctrl+V > Enter")
        note[store] := "직접 실행 필요 (F12)"
        UpdateRow(store)
        SoundBeep 660, 400
        if !WaitTitle("HARVEST", 300000) {
            Say("[목록] " StoreName(store) " : 스크립트가 실행되지 않아 건너뜁니다")
            return false
        }
        SetStage("주소 모으는 중 : " StoreName(store))
    }

    ; ---- 끝날 때까지 대기 ----
    endT := A_TickCount + HARVEST_MAX_MIN * 60000
    stopSent := false
    loop {
        title := WinGetTitle("ahk_id " browserHwnd)
        if InStr(title, "HARVEST_DONE")
            break
        if InStr(title, "HARVEST_FAIL") {
            Say("[목록] " store " : " title)
            return false
        }
        if (A_TickCount > endT) {
            Say("[목록] " store " : 제한 시간 안에 끝나지 않음")
            return false
        }

        ; 중단 요청 : 페이지의 스크립트를 멈춰 그때까지 모은 주소를 받아 온다
        if (stopReq && !stopSent) {
            stopSent := true
            endT := A_TickCount + 90000
            Say("[목록] 중단 요청 → 지금까지 모은 주소를 저장합니다")
            if FocusBrowser() {
                Send "^l"
                Sleep 300
                SendText "javascript:window.stopHarvest()"
                Sleep 200
                Send "{Delete}"
                Send "{Enter}"
            }
        }

        if RegExMatch(title, "HARVEST\s+(\d+)p\s*/\s*(\d+)", &m) {
            note[store] := "모으는 중 " m[1] "쪽 · " m[2] "개"
            txtItem.Text := note[store]
            UpdateRow(store)
        }
        Sleep 500
    }
    Sleep 500

    ; ---- 결과 복사 (화면은 주소 목록 글자뿐이라 아무 데나 눌러도 안전) ----
    txt := ""
    loop 3 {
        if WinExist("ahk_id " browserHwnd)
            WinActivate "ahk_id " browserHwnd
        Sleep 300
        pt := SafePoint()
        Click pt[1], pt[2]
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
        return false
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

    partial := InStr(txt, "user-stop") ? true : false
    v := StatOf(store)
    v.total += added
    if (found > 0 || partial) {
        harv[store] := {n: found, date: FormatTime(A_Now, "yyyy-MM-dd HH:mm"), state: partial ? "partial" : "done"}
        SaveHarv()
    }

    Say("[목록] " StoreName(store) (partial ? " 중단 (일부 저장)" : " 완료") " : 상품 " found "개, 신규 " added "개")
    txtItem.Text := ""
    return found > 0
}

; 크롬 창 안에서 조작 창에 가려지지 않은 지점
SafePoint() {
    WinGetPos &wx, &wy, &ww, &wh, "ahk_id " browserHwnd
    ui.GetPos(&gx, &gy, &gw, &gh)
    for c in [[0.5, 0.5], [0.75, 0.5], [0.5, 0.8], [0.25, 0.7], [0.8, 0.3]] {
        x := wx + Round(ww * c[1])
        y := wy + Round(wh * c[2])
        if !(x >= gx && x <= gx + gw && y >= gy && y <= gy + gh)
            return [x, y]
    }
    return [wx + ww // 2, wy + wh // 2]
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
        t := "개당 " Round(perItem, 1) "초 · 시간당 " Round(3600 / perItem) "개 · 남은 시간 "
            . (etaMin >= 60 ? Round(etaMin / 60, 1) "시간" : etaMin "분")
        if (phN > 0)
            t .= "   [이동 " Round(phNav / phN / 1000, 1) " · 대기 " Round(phLoad / phN / 1000, 1)
               . " · 클릭후 " Round(phWatch / phN / 1000, 1) "]"
        txtSpeed.Text := t
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
