#Requires AutoHotkey v2.0
#SingleInstance Force
CoordMode "Pixel", "Screen"
CoordMode "Mouse", "Screen"
SetTitleMatchMode 2
SendMode "Event"
SetKeyDelay 25, 25
SetMouseDelay 30

; ==========================================================
;  셀업(SmartSellUp) 상품 자동 수집 v18 - 스토어 전체 자동 수집판
;  ---------------------------------------------------------
;  수집(클릭) 동작은 v17 그대로입니다. 바뀐 것은 아래 네 가지입니다.
;
;  v18 변경점
;   · stores.txt 에 스토어 주소만 적으면, 목록 페이지를 넘기며
;     전체 상품 주소를 직접 모아 urls.txt 에 추가합니다
;     (셀업 크롬 창에서 목록을 열고 Ctrl+A, Ctrl+C 로 읽음)
;   · 이어하기를 번호(progress.txt) 대신 done_urls.txt 기준으로 합니다
;     이미 수집한 주소는 자동으로 건너뛰고, 실패한 주소는
;     다음 실행 때 다시 시도합니다. 시작할 때 묻지 않습니다
;   · 연속 실패 시 바로 끝내지 않고 REST_MIN 분 쉬었다가 재개합니다
;     (MAX_RESTS 번 연속으로 쉬어도 안 풀리면 그때 중단)
;   · F4 = 주소 모으기만 실행
;
;  준비물
;   - 같은 폴더 : stores.txt (스토어 주소 한 줄에 하나) 또는 urls.txt
;   - 같은 폴더 : img\capture.png , img\armed.png
;
;  실행
;   1) 셀업 크롬 창에서 상품 상세 페이지 열기 (CAPTURE 상태)
;   2) 스크립트 실행 → 크롬 창 클릭 → F1
;
;  단축키
;   F1 시작(주소 모으기 + 수집) / F2 중단 / F3 단발테스트
;   F4 주소 모으기만 / F8 구분검사 / F9 세팅점검 / F10 속도 리포트
; ==========================================================

; ---------- 경로 ----------
IMGDIR   := A_ScriptDir "\img\"
URLFILE  := A_ScriptDir "\urls.txt"
LOGFILE  := A_ScriptDir "\log.txt"
DONEFILE := A_ScriptDir "\done_urls.txt"
SPEEDLOG := A_ScriptDir "\speed.txt"
STOREFILE := A_ScriptDir "\stores.txt"
HARVFILE  := A_ScriptDir "\harvested_stores.txt"

; ---------- 스토어 주소 모으기 (v18) ----------
LIST_WAIT := 3500     ; 목록 페이지를 연 뒤 복사하기 전 대기 ms (목록이 덜 읽히면 올릴 것)
LIST_SIZE := 80       ; 목록 한 쪽당 상품 수

; ---------- 연속 실패 시 휴식 (v18) ----------
REST_MIN  := 10       ; 연속 실패(MAX_CONSEC) 시 쉬는 시간(분)
MAX_RESTS := 3        ; 쉬고 재개해도 계속 실패하면 이 횟수에서 중단

; ---------- 속도 설정 ----------
; ▼ 이 블록만 조정하면 속도가 바뀝니다
POLL_FAST   := 90     ; 이미지 탐색 폴링 간격 ms (짧을수록 반응 빠름)
LOAD_WAIT   := 20000  ; 페이지 로딩 최대 대기 ms (초과 시 1회 재시도)
ARMED_WAIT  := 2200   ; 클릭 후 결과 감시 최대 ms (ARMED/팝업 확인용)
POST_CLICK  := 250    ; 클릭 직후 최소 안정화 ms
GAP_MIN     := 700    ; 다음 상품까지 최소 간격 ms
GAP_MAX     := 1800   ; 다음 상품까지 최대 간격 ms
LOAD_RETRY  := 1      ; 로딩 실패 시 재시도 횟수 (클릭 전에만)

; 참고 - 보수적으로 돌리고 싶을 때
;   GAP_MIN 3000 / GAP_MAX 6000 / ARMED_WAIT 4000
; 참고 - 더 공격적으로
;   GAP_MIN 300  / GAP_MAX 900  / ARMED_WAIT 1500

; ---------- 탐색 영역 최적화 (저사양 PC 핵심) ----------
; ImageSearch 는 픽셀 수에 비례해 느려집니다.
; 창 전체(약 200만 픽셀)를 훑으면 저사양 PC 에서는 한 번에 수백 ms 가 걸리고,
; 그 CPU 점유가 크롬 렌더링을 방해해 페이지 로딩까지 느려집니다.
; CAPTURE 버튼은 항상 창 우측 하단 고정 위치이므로 그 주변만 봅니다.
USE_REGION  := true    ; 영역 제한 사용
REGION_PAD  := 120     ; 처음 찾은 위치 주변 여유 픽셀
; 아직 위치를 모를 때 사용할 초기 영역 (창 우측하단 비율)
REGION_X    := 0.55    ; 창 가로의 55% 지점부터 오른쪽 끝까지
REGION_Y    := 0.55    ; 창 세로의 55% 지점부터 아래 끝까지

; ---------- ARMED 확인 ----------
; ARMED 는 성공 확인용 보조 신호일 뿐입니다.
; 저사양 PC 에서는 꺼두면 상품당 최대 ARMED_WAIT 만큼 절약됩니다.
; 끄더라도 중복 팝업 처리는 그대로 동작합니다.
CHECK_ARMED := true    ; 문제 진단 중에는 켜둘 것 (성공 여부 확인용)
DUP_WAIT    := 1200    ; ARMED 를 끌 때 중복팝업만 확인하는 시간 ms

; ---------- 구간별 시간 측정 ----------
PHASE_LOG   := true    ; 로딩/감시 소요시간을 speed.txt 에 기록

; ---------- 수집 성공률 (중요) ----------
; 노란 버튼이 화면에 그려지는 시점과, 셀업이 그 페이지를 수집할
; 준비를 마치는 시점이 다릅니다. 버튼이 보이는 즉시 클릭하면
; 아무 일도 일어나지 않고 ARMED 도 뜨지 않습니다.
; v8 에는 Sleep 1200 이 있어서 이 문제가 가려져 있었습니다.
CLICK_SETTLE := 1000   ; 버튼 발견 후 클릭까지 대기 ms
                       ; 누락이 많으면 1500~2000 으로 올릴 것
                       ; 성공률이 100%에 가까우면 600 까지 내려도 됨

; ARMED 를 못 봤을 때 한 번 더 클릭합니다.
; 중복 처리가 No 이므로 이미 수집된 상품을 또 클릭해도
; 팝업이 떠서 자동으로 닫히고 넘어갑니다. 즉 재클릭이 안전합니다.
; 놓친 수집을 스스로 복구하는 장치이므로 켜두는 것을 권장합니다.
; (CHECK_ARMED 가 true 여야 동작합니다)
RETRY_CLICK  := true
RETRY_GAP    := 800   ; 재클릭 전 대기 ms

; ---------- 페이지 전환 확인 (오클릭 방지 핵심) ----------
; Enter 를 쳐도 새 페이지가 그려지기 전까지 이전 상품 페이지가
; 화면에 남아 있고 노란 버튼도 그대로 보인다.
; 그 상태에서 클릭하면 이전 페이지의 버튼을 누르게 되어
; 아무 일도 일어나지 않는다 (좌표는 정상, 수집만 안 됨).
; 버튼이 한 번 사라지는 것을 확인해 페이지 전환을 보장한다.
WAIT_VANISH := true    ; 끄면 v14 와 동일하게 동작
VANISH_WAIT := 6000    ; 버튼이 사라지기를 기다리는 최대 ms

; ---------- 포커스 처리 (F1 클릭 무반응의 핵심) ----------
; 주소창에 URL 을 넣고 Enter 를 치면 포커스가 주소창에 남는다.
; 그 상태의 첫 클릭은 버튼까지 전달되지 않는 경우가 있다.
;   "f6"        : F6 키로 포커스를 페이지로 이동 (권장, 안전)
;   "bodyclick" : 페이지 좌측 하단 여백을 한 번 클릭
;   "none"      : 아무것도 안 함 (F3 처럼 이미 본문에 포커스가 있을 때)
FOCUS_FIX   := "f6"

; ---------- 클릭 방식 ----------
; 커서를 먼저 옮겨 hover 를 발생시킨 뒤 클릭한다.
; 클릭은 나가는데 페이지가 반응하지 않을 때 HOVER_MS 를 250~400 으로 올려볼 것.
HOVER_MS    := 150     ; 커서 이동 후 클릭까지 대기 ms
CLICK_LOG   := true    ; 클릭 좌표를 log.txt 에 기록 (처음 10개 + 50개마다)

; ---------- 동작 설정 ----------
TOL         := 25      ; ImageSearch 허용오차. 못 찾으면 45~60

; ★ ARMED 전용 허용오차 (매우 엄격해야 함)
;   CAPTURE 와 ARMED 는 똑같은 노란 알약이고 글자만 다릅니다.
;   TOL 이 느슨하면 CAPTURE 를 ARMED 로 오인해
;   "항상 성공"으로 잘못 판정하고, 재클릭 복구도 발동하지 않습니다.
;   F8 로 두 이미지가 구분되는지 반드시 확인하세요.
ARMED_TOL   := 5
USE_CLICK   := true    ; true=버튼클릭 / false=Alt+C
AUTO_CENTER := true    ; PNG 크기 읽어 중앙 자동계산
CLICK_OFF_X := 45      ; 자동계산 실패 시 폴백
CLICK_OFF_Y := 20
DUP_YES     := false   ; 중복팝업 : false=No(건너뜀)
DUP_TITLE   := "기등록 상품 확인"
MAX_CONSEC  := 5       ; 연속 실패 몇 회에 중단 (캡챠/차단 대비)
; ----------------------------

browserHwnd := 0
urls := []
running := false

; 마지막으로 버튼을 찾은 위치 (탐색 영역 축소용)
lastFoundX := 0
lastFoundY := 0

; 구간별 소요시간
phLoad := 0
phWatch := 0

; 통계
statStart := 0
statDone := 0
statDup := 0
statFail := 0
statArmed := 0
statIdx := 0
statTotal := 0

TrayTip "준비 완료", "F8 구분검사 / F9 점검 / F3 테스트 / F4 주소모으기 / F1 시작"

F1:: StartRun()

F2:: {
    SpeedReport(true)
    Sleep 500
    ExitApp
}

F10:: SpeedReport(false)

F4:: HarvestOnly()

F3:: {
    global browserHwnd
    browserHwnd := WinGetID("A")

    t := A_TickCount
    pos := FindImage("capture.png")
    if !pos {
        MsgBox "CAPTURE 버튼을 못 찾았습니다.`n크롬 줌 100%, CAPTURE 상태인지 확인하세요."
        return
    }
    findMs := A_TickCount - t

    DoCapture(CenterOf(pos, "capture.png"))
    r := WatchAfterCapture(0)

    MsgBox "단발 테스트 결과`n`n"
         . "버튼 탐색 : " findMs " ms`n"
         . "결과 : " (r = 2 ? "ARMED 포착" : r = 3 ? "중복 → 건너뜀" : "클릭 실행 (ARMED 미포착)") "`n`n"
         . "셀업 목록에 들어왔으면 정상입니다.`nF1 으로 시작하세요."
}

; ---------- F8 : CAPTURE / ARMED 구분 검사 (필수) ----------
; 지금 화면이 CAPTURE 상태일 때 실행하세요.
; armed.png 가 CAPTURE 버튼에도 매칭되면 성공 판정이 전부 거짓이 됩니다.
F8:: {
    global browserHwnd, ARMED_TOL
    browserHwnd := WinGetID("A")

    c := FindImage("capture.png")
    if !c {
        MsgBox "CAPTURE 버튼을 못 찾았습니다.`n지금 CAPTURE 상태인지 확인하세요."
        return
    }

    a := FindImage("armed.png", false, false)

    if a {
        MsgBox "★ 문제 발견 ★`n`n"
             . "지금은 CAPTURE 상태인데 armed.png 도 매칭됩니다.`n"
             . "두 이미지가 구분되지 않아 성공 판정이 전부 거짓이 됩니다.`n`n"
             . "현재 ARMED_TOL = " ARMED_TOL "`n`n"
             . "해결 방법`n"
             . "1) ARMED_TOL 을 0 으로 낮춰보세요`n"
             . "2) 그래도 매칭되면 armed.png 를 다시 자르세요`n"
             . "   → 노란 배경을 최대한 빼고 ARMED 글자만`n"
             . "   → CAPTURE 와 ARMED 는 글자 길이가 달라서`n"
             . "      글자 부분만 잘라내면 확실히 구분됩니다"
    } else {
        MsgBox "정상입니다.`n`n"
             . "CAPTURE 상태에서 armed.png 는 매칭되지 않습니다.`n"
             . "(ARMED_TOL = " ARMED_TOL ")`n`n"
             . "이제 F3 으로 수집을 실행해 ARMED 가 실제로`n"
             . "포착되는지 확인한 뒤 F1 으로 시작하세요."
    }
}

; ---------- F9 : 세팅 점검 + 탐색 속도 측정 ----------
F9:: {
    global browserHwnd, lastFoundX, lastFoundY, USE_REGION
    browserHwnd := WinGetID("A")

    szC := PngSize("capture.png")
    szA := PngSize("armed.png")

    msg := "[이미지]`n"
         . "capture.png : " (szC[1] ? szC[1] " x " szC[2] : "크기 읽기 실패 → 고정 오프셋 사용") "`n"
         . "armed.png   : " (szA[1] ? szA[1] " x " szA[2] : "크기 읽기 실패") "`n`n"

    ; 전체 탐색 속도
    lastFoundX := 0, lastFoundY := 0
    t := A_TickCount
    posFull := FindImage("capture.png", true, false)
    msFull := A_TickCount - t

    if !posFull {
        msg .= "[탐색]`n실패 (" msFull " ms)`n`n"
             . "확인할 것`n"
             . "· 크롬 줌 100% (Ctrl+0)`n"
             . "· 지금 CAPTURE 상태인지 (ARMED 면 Ctrl+R)`n"
             . "· 이 PC 화면에서 새로 잘라낸 이미지인지`n"
             . "· 그래도 안 되면 TOL 을 45~60 으로"
        MsgBox msg
        return
    }

    ; 영역 제한 탐색 속도 (위치를 아는 상태)
    lastFoundX := posFull[1], lastFoundY := posFull[2]
    t := A_TickCount
    FindImage("capture.png", false, false)
    msRegion := A_TickCount - t

    c := CenterOf(posFull, "capture.png")
    MouseMove c[1], c[2], 0

    gain := msRegion > 0 ? Round(msFull / msRegion, 1) : 0

    msg .= "[탐색 속도]`n"
         . "창 전체 검색 : " msFull " ms`n"
         . "영역 제한    : " msRegion " ms"
         . (gain > 1 ? "   (약 " gain "배 빠름)" : "") "`n`n"
         . "[위치]`n"
         . "좌상단 " posFull[1] ", " posFull[2] "`n"
         . "클릭지점 " c[1] ", " c[2] "`n`n"
         . "커서가 노란 버튼 정중앙에 있나요?`n"
         . "(이 창을 옆으로 옮겨 확인)`n`n"
         . (msFull > 300
            ? "★ 전체 검색이 " msFull "ms 로 느립니다.`n"
            . "   USE_REGION := true 로 두고,`n"
            . "   CHECK_ARMED := false 를 권장합니다.`n`n"
            : "")
         . "정중앙이면 F3 → F1 순서로 진행하세요."
    MsgBox msg
}

StartRun() {
    global browserHwnd, urls, running
    global statStart, statTotal, CHECK_ARMED

    if running
        return
    running := true

    browserHwnd := WinGetID("A")
    WinGetPos &bx, &by, &bw, &bh, "ahk_id " browserHwnd

    if !FindImage("capture.png") {
        r := MsgBox("CAPTURE 버튼을 찾지 못했습니다. 강행할까요?", "확인", "YesNo")
        if (r != "Yes")
            ExitApp
    }

    ; ★ ARMED 오인 검사
    ; 지금은 CAPTURE 상태인데 armed.png 도 매칭되면
    ; 성공 판정이 전부 거짓이 되고 재클릭 복구도 발동하지 않는다
    if (CHECK_ARMED && FindImage("armed.png", false, false)) {
        r := MsgBox("★ 경고 ★`n`n"
                  . "지금 CAPTURE 상태인데 armed.png 도 매칭됩니다.`n"
                  . "두 이미지가 구분되지 않아 모든 상품이 무조건`n"
                  . "'성공'으로 기록되고, 재클릭 복구가 작동하지 않습니다.`n`n"
                  . "F8 을 눌러 자세한 해결 방법을 확인하세요.`n`n"
                  . "그래도 진행할까요?", "ARMED 구분 실패", "YesNo")
        if (r != "Yes")
            ExitApp
    }

    ; stores.txt 가 있으면 아직 안 모은 스토어의 상품 주소를 먼저 모은다
    HarvestStores()

    ; urls.txt 에서 이미 수집한 것(done_urls.txt)을 뺀 나머지만 처리
    skipped := LoadUrls()
    if (urls.Length = 0) {
        ToolTip()
        MsgBox "수집할 새 상품이 없습니다.`n`n"
             . "이미 수집한 상품 " skipped "개는 건너뛰었습니다.`n"
             . "stores.txt 또는 urls.txt 를 확인하세요."
        ExitApp
    }
    statTotal := urls.Length

    statStart := A_TickCount
    WriteLog("=== 시작 / 남은 " urls.Length "개 (이미 수집 " skipped "개 제외) / 창 "
           . bx "," by " " bw "x" bh " ===")
    RunLoop()
}

; urls.txt 를 읽어 done_urls.txt 에 없는 주소만 urls 에 담는다. 건너뛴 개수를 돌려준다
LoadUrls() {
    global urls, URLFILE, DONEFILE

    urls := []
    done := Map()
    seen := Map()
    skipped := 0

    if FileExist(DONEFILE) {
        for line in StrSplit(FileRead(DONEFILE, "UTF-8"), "`n", "`r") {
            line := Trim(line)
            if (line != "")
                done[line] := true
        }
    }

    if !FileExist(URLFILE)
        return 0

    for line in StrSplit(FileRead(URLFILE, "UTF-8"), "`n", "`r") {
        line := Trim(line)
        if !InStr(line, "/products/")
            continue
        if seen.Has(line)
            continue
        seen[line] := true
        if done.Has(line) {
            skipped++
            continue
        }
        urls.Push(line)
    }
    return skipped
}

RunLoop() {
    global urls, GAP_MIN, GAP_MAX, MAX_CONSEC, REST_MIN, MAX_RESTS
    global statDone, statDup, statFail, statArmed, statIdx

    consec := 0
    rests := 0
    i := 1

    while (i <= urls.Length) {
        statIdx := i
        ShowStatus()

        r := Collect(urls[i], i)

        if (r = 0) {
            statFail++
            consec++
            WriteLog(i " [실패] " urls[i])

            if (consec >= MAX_CONSEC) {
                rests++
                SpeedReport(true, false)

                if (rests > MAX_RESTS) {
                    ToolTip()
                    WriteLog("=== 휴식 " MAX_RESTS "회 후에도 연속 실패. 중단 ===")
                    MsgBox "쉬었다가 재개해도 계속 실패하여 중단했습니다.`n`n"
                         . "확인할 것`n"
                         . "· 캡챠나 차단 화면이 떴는지`n"
                         . "· 셀업 수집 세션이 끊겼는지`n`n"
                         . "다시 F1 을 누르면 남은 상품부터 이어서 진행합니다."
                    ExitApp
                }

                WriteLog("=== 연속 " consec "회 실패. " REST_MIN "분 쉬고 재개 (" rests "/" MAX_RESTS ") ===")
                ToolTip "연속 실패 → " REST_MIN "분 휴식 중 (" rests "/" MAX_RESTS ")`n"
                      . "캡챠·차단 화면이면 직접 풀어 주세요  (F2 중단)", 20, 20
                Sleep REST_MIN * 60000
                consec := 0
            }
        } else {
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

        ; 100개마다 속도 로그
        if (Mod(i, 100) = 0)
            SpeedReport(true, false)

        Sleep Random(GAP_MIN, GAP_MAX)
    }

    SpeedReport(true)
    ToolTip()
    WriteLog("=== 완료 : 수집 " statDone " / ARMED확인 " statArmed
           . " / 중복 " statDup " / 실패 " statFail " ===")
    MsgBox "작업 완료`n`n"
         . "수집 " statDone "개`n중복 건너뜀 " statDup "개`n실패 " statFail "개`n"
         . "ARMED 포착 " statArmed "개`n`n"
         . SpeedText() "`n`n"
         . "실패한 상품은 다시 F1 을 누르면 재시도합니다.`n"
         . "실제 수집 여부는 셀업 목록에서 확인하세요."
    ExitApp
}

; ==========================================================
;  스토어 전체 상품 주소 모으기 (v18)
;  셀업 크롬 창에서 목록 페이지(80개씩)를 열고 전체 복사한 뒤
;  클립보드 HTML 에 들어 있는 /products/<번호> 링크를 읽는다
; ==========================================================

HarvestOnly() {
    global browserHwnd, running, URLFILE, STOREFILE

    if running
        return
    running := true

    if !FileExist(STOREFILE) {
        MsgBox "stores.txt 가 없습니다.`n스토어 주소를 한 줄에 하나씩 적어 주세요."
        running := false
        return
    }

    browserHwnd := WinGetID("A")
    n := HarvestStores()
    ToolTip()
    MsgBox "주소 모으기 완료`n`n새로 추가된 상품 주소 " n "개`n"
         . "(urls.txt 에 저장됨. 자세한 내용은 log.txt)`n`nF1 으로 수집을 시작하세요."
    running := false
}

; stores.txt 의 스토어 중 아직 모으지 않은 것만 처리. 새로 추가된 주소 수를 돌려준다
HarvestStores() {
    global STOREFILE, HARVFILE, URLFILE

    if !FileExist(STOREFILE)
        return 0

    harvested := Map()
    if FileExist(HARVFILE) {
        for line in StrSplit(FileRead(HARVFILE, "UTF-8"), "`n", "`r") {
            p := StrSplit(line, "`t")
            if (p.Length >= 1 && Trim(p[1]) != "")
                harvested[Trim(p[1])] := true
        }
    }

    known := Map()
    if FileExist(URLFILE) {
        txt := FileRead(URLFILE, "UTF-8")
        for line in StrSplit(txt, "`n", "`r") {
            line := Trim(line)
            if (line != "")
                known[line] := true
        }
        ; 마지막 줄이 줄바꿈 없이 끝났으면 새 주소가 이어 붙지 않게 줄바꿈 추가
        if (txt != "" && SubStr(txt, -1) != "`n")
            FileAppend "`n", URLFILE, "UTF-8"
    }

    total := 0
    for line in StrSplit(FileRead(STOREFILE, "UTF-8"), "`n", "`r") {
        store := NormalizeStore(line)
        if (store = "" || harvested.Has(store))
            continue

        n := HarvestStore(store, known)
        if (n >= 0) {
            FileAppend store "`t" n "`t" FormatTime(A_Now, "yyyy-MM-dd HH:mm") "`n", HARVFILE, "UTF-8"
            harvested[store] := true
            total += n
        }
    }
    ToolTip()
    return total
}

; 어떤 형태의 주소든 https://smartstore.naver.com/<스토어명> 으로 정리. 인식 못 하면 ""
NormalizeStore(line) {
    if RegExMatch(line, "i)(smartstore|brand)\.naver\.com/([A-Za-z0-9_\-]+)", &m)
        return "https://" StrLower(m[1]) ".naver.com/" m[2]
    return ""
}

; 한 스토어의 목록을 끝까지 넘긴다. 새로 추가한 주소 수, 첫 쪽부터 실패하면 -1
HarvestStore(store, known) {
    global URLFILE, LIST_SIZE

    added := 0
    pages := 0
    page := 1

    loop {
        ToolTip "주소 모으는 중`n" store "`n" . page . (pages ? "/" pages : "") . "쪽 · 신규 " . added . "개`n(F2 중단)", 20, 20

        url := store "/category/ALL?st=RECENT&dt=IMAGE&page=" page "&size=" LIST_SIZE
        txt := ""
        ids := CopyListPage(url, &txt)
        if (ids.Length = 0) {
            Sleep 4000
            ids := CopyListPage(url, &txt)
        }
        if (ids.Length = 0) {
            WriteLog("[목록] " store " " page "쪽에서 상품을 찾지 못함")
            if (page = 1)
                return -1
            break
        }

        if (pages = 0 && RegExMatch(txt, "총\s*([\d,]+)\s*개", &m))
            pages := Ceil(Integer(StrReplace(m[1], ",")) / LIST_SIZE)

        fresh := 0
        buf := ""
        for id in ids {
            u := store "/products/" id
            if !known.Has(u) {
                known[u] := true
                buf .= u "`n"
                fresh++
            }
        }
        if (buf != "")
            FileAppend buf, URLFILE, "UTF-8"
        added += fresh

        WriteLog("[목록] " store " " page "/" (pages ? pages : "?") "쪽 : 상품 " ids.Length "개, 신규 " fresh "개")

        ; 총 쪽수를 알면 끝까지, 모르면 새 상품이 안 나올 때까지
        if (pages > 0 ? page >= pages : fresh = 0)
            break

        page++
        Sleep Random(800, 1500)
    }

    WriteLog("[목록] " store " 완료 : 신규 " added "개")
    return added
}

; 목록 페이지를 열어 맨 아래까지 내린 뒤 전체 복사. 상품 번호 배열을 돌려주고 txt 에 화면 글자를 담는다
CopyListPage(url, &txt) {
    global LIST_WAIT, browserHwnd

    txt := ""
    if !FocusBrowser()
        return []
    if !GotoUrl(url)
        return []
    Sleep LIST_WAIT

    loop 2 {
        ; 지연 로딩되는 상품 카드가 모두 그려지도록 맨 아래로
        loop 5 {
            Send "{End}"
            Sleep 400
        }

        A_Clipboard := ""
        Send "^a"
        Sleep 150
        Send "^c"

        if ClipWait(8) {
            Sleep 300
            txt := A_Clipboard
            ; 주소 한 줄만 복사됐다면 포커스가 주소창에 남아 있던 것
            if !(SubStr(txt, 1, 4) = "http" && !InStr(txt, "`n"))
                return ParseIds(GetClipHtml())
        }

        ; 포커스를 페이지 본문으로 옮기고 한 번 더 (창 왼쪽 가장자리 여백 클릭)
        WinGetPos &wx, &wy, &ww, &wh, "ahk_id " browserHwnd
        Click wx + 12, wy + wh // 2
        Sleep 300
    }
    return []
}

; HTML 에서 /products/<번호> 를 중복 없이 순서대로 뽑는다
ParseIds(html) {
    ids := []
    seen := Map()
    pos := 1
    while (pos := RegExMatch(html, "/products/(\d+)", &m, pos)) {
        if !seen.Has(m[1]) {
            seen[m[1]] := true
            ids.Push(m[1])
        }
        pos += m.Len
    }
    return ids
}

; 클립보드의 "HTML Format" 내용 (링크 주소가 들어 있음)
GetClipHtml() {
    static fmt := DllCall("RegisterClipboardFormat", "Str", "HTML Format", "UInt")

    if !DllCall("IsClipboardFormatAvailable", "UInt", fmt)
        return ""
    if !DllCall("OpenClipboard", "Ptr", A_ScriptHwnd)
        return ""

    html := ""
    if (h := DllCall("GetClipboardData", "UInt", fmt, "Ptr")) {
        if (p := DllCall("GlobalLock", "Ptr", h, "Ptr")) {
            html := StrGet(p, "UTF-8")
            DllCall("GlobalUnlock", "Ptr", h)
        }
    }
    DllCall("CloseClipboard")
    return html
}

; 반환값 : 0=실패 / 1=클릭함(ARMED 미포착) / 2=ARMED 포착 / 3=중복 건너뜀
Collect(url, idx) {
    global LOAD_WAIT, LOAD_RETRY, PHASE_LOG, WAIT_VANISH, VANISH_WAIT
    global CLICK_SETTLE, RETRY_CLICK, RETRY_GAP, CHECK_ARMED
    global phLoad, phWatch

    tries := LOAD_RETRY + 1

    loop tries {
        if !FocusBrowser()
            return 0

        if !GotoUrl(url)
            return 0

        tLoad := A_TickCount

        ; ★ 핵심 : 이전 페이지의 버튼을 누르지 않도록
        ;   1) 버튼이 사라질 때까지 대기 = 이전 페이지가 치워짐
        ;   2) 다시 나타날 때까지 대기 = 새 페이지 준비 완료
        ; Enter 직후에는 이전 상품 페이지가 화면에 그대로 남아 있고
        ; 노란 버튼도 같이 보이기 때문에, 곧바로 탐색하면
        ; 이전 페이지의 버튼을 찾아 클릭하게 된다 (아무 효과 없음).
        if WAIT_VANISH {
            if !WaitImageGone("capture.png", VANISH_WAIT)
                WriteLog(idx " [정보] 이전 버튼이 사라지지 않음 (그대로 진행)")
        }

        pos := WaitImagePos("capture.png", LOAD_WAIT)
        phLoad := A_TickCount - tLoad

        if !pos {
            WriteLog(idx " [경고] 로딩 대기 초과 (" phLoad "ms)")
            continue
        }

        ; ★ 버튼이 보이는 시점과 셀업이 수집 준비를 마치는 시점이 다르다.
        ;   버튼은 먼저 그려지고 핸들러는 나중에 붙기 때문에
        ;   곧바로 클릭하면 아무 일도 일어나지 않는다 (ARMED 안 뜸).
        if (CLICK_SETTLE > 0)
            Sleep CLICK_SETTLE

        ; 대기 중 버튼이 움직였을 수 있으니 위치 재확인
        pos2 := FindImage("capture.png")
        if pos2
            pos := pos2

        tWatch := A_TickCount
        DoCapture(CenterOf(pos, "capture.png"), idx)
        r := WatchAfterCapture(idx)

        ; ★ ARMED 를 못 봤으면 한 번 더 클릭한다.
        ;   중복 처리가 No 이므로, 이미 수집된 상품을 또 클릭해도
        ;   팝업이 떠서 자동으로 닫히고 넘어간다. 즉 재클릭이 안전하다.
        ;   놓친 수집을 스스로 복구하는 장치.
        if (RETRY_CLICK && CHECK_ARMED && r = 1) {
            WriteLog(idx " [재시도] ARMED 미포착 → 1회 재클릭")
            Sleep RETRY_GAP
            p3 := FindImage("capture.png")
            if p3 {
                DoCapture(CenterOf(p3, "capture.png"), idx)
                r2 := WatchAfterCapture(idx)
                if (r2 = 2 || r2 = 3)
                    r := r2
                else
                    WriteLog(idx " [정보] 재클릭 후에도 ARMED 미포착")
            }
        }

        phWatch := A_TickCount - tWatch

        if PHASE_LOG && (Mod(idx, 20) = 0)
            WritePhase(idx, phLoad, phWatch)

        return r
    }
    return 0
}

WritePhase(idx, load, watch) {
    global SPEEDLOG
    try FileAppend FormatTime(A_Now, "HH:mm:ss") "  #" idx
        . "  로딩 " load "ms  감시 " watch "ms`n", SPEEDLOG, "UTF-8"
}

; 클릭 전에 커서를 먼저 이동시켜 hover 이벤트를 발생시킨다.
; 그리고 주소창에 남은 포커스를 페이지 본문으로 옮긴다.
;
; ★ F3(수동)은 되는데 F1(자동)만 안 되던 원인
;   F3 은 직전에 사용자가 페이지를 클릭해 포커스가 본문에 있다.
;   F1 은 Ctrl+L 로 주소창에 URL 을 넣고 Enter 를 친 직후라
;   포커스가 주소창에 남아 있고, 그 상태의 첫 클릭은
;   "포커스를 페이지로 옮기는 데" 소모되어 버튼까지 전달되지 않는다.
DoCapture(c, idx := 0) {
    global USE_CLICK, HOVER_MS, CLICK_LOG, browserHwnd, FOCUS_FIX

    if !WinActive("ahk_id " browserHwnd) {
        WinActivate "ahk_id " browserHwnd
        Sleep 100
    }

    ; ---- 포커스를 페이지 본문으로 ----
    if (FOCUS_FIX = "f6") {
        Send "{F6}"
        Sleep 120
    } else if (FOCUS_FIX = "bodyclick") {
        WinGetPos &wx, &wy, &ww, &wh, "ahk_id " browserHwnd
        Click wx + 25, wy + wh - 90      ; 링크 없는 좌측 하단 여백
        Sleep 200
    }

    if USE_CLICK {
        MouseMove c[1], c[2], 2          ; 부드럽게 이동 (hover 발생)
        Sleep HOVER_MS
        Click c[1], c[2]
        Sleep 60
    } else {
        SendInput "!c"
        Sleep 60
    }

    ; ★ 두 방식 모두 기록. 처음 30개 + 이후 50개마다
    if (CLICK_LOG && (idx <= 30 || Mod(idx, 50) = 0)) {
        MouseGetPos &mx, &my
        WriteLog(idx " [실행] " (USE_CLICK ? "클릭" : "AltC")
               . "  목표 " c[1] "," c[2]
               . "  커서 " mx "," my
               . "  포커스 " FOCUS_FIX
               . "  활성창 " (WinActive("ahk_id " browserHwnd) ? "크롬" : "다름"))
    }
}

; 클릭 후 짧게만 감시. 결과가 확정되면 즉시 반환
WatchAfterCapture(idx) {
    global ARMED_WAIT, DUP_WAIT, POLL_FAST, POST_CLICK, DUP_YES, CHECK_ARMED

    Sleep POST_CLICK

    ; ARMED 확인을 끄면 중복팝업만 짧게 확인하고 바로 넘어간다
    limit := CHECK_ARMED ? ARMED_WAIT : DUP_WAIT
    endT := A_TickCount + limit

    while (A_TickCount < endT) {

        if HandleDupPopup(idx) {
            FocusBrowser()
            if !DUP_YES
                return 3
            endT := A_TickCount + 1000
            continue
        }

        if (CHECK_ARMED && FindImage("armed.png", false, false))
            return 2

        Sleep POLL_FAST
    }

    return 1
}

GotoUrl(url) {
    A_Clipboard := url
    if !ClipWait(1)
        return false
    Send "^l"
    Sleep 120
    Send "^a"
    Sleep 60
    Send "^v"
    Sleep 120
    Send "{Enter}"
    return true
}

HandleDupPopup(idx) {
    global DUP_TITLE, DUP_YES

    if !WinExist(DUP_TITLE)
        return false

    hwnd := WinExist(DUP_TITLE)
    WinActivate "ahk_id " hwnd
    Sleep 150

    btn := DUP_YES ? "Yes" : "No"
    ok := false
    try {
        ControlClick btn, "ahk_id " hwnd
        ok := true
    }
    if !ok {
        try ControlClick (DUP_YES ? "Button1" : "Button2"), "ahk_id " hwnd
    }
    Sleep 400

    if WinExist(DUP_TITLE) {
        WinGetPos &px, &py, &pw, &ph, "ahk_id " hwnd
        Click px + pw * (DUP_YES ? 0.63 : 0.85), py + ph * 0.83
        Sleep 350
    }

    WriteLog(idx " [중복] " btn)
    return true
}

; ---------- 이미지 ----------

; 찾으면 좌표 배열, 못 찾으면 0
;  forceFull    : 영역 제한을 무시하고 창 전체 검색
;  allowFallback: 좁은 영역에서 실패 시 넓은 영역 재검색 허용
;                 (ARMED 폴링처럼 "없는 게 정상" 인 검색은 false 로)
FindImage(file, forceFull := false, allowFallback := true) {
    global IMGDIR, TOL, ARMED_TOL, browserHwnd, USE_REGION, REGION_PAD
    global REGION_X, REGION_Y, lastFoundX, lastFoundY

    ; ARMED 는 CAPTURE 와 모양이 같아 엄격한 허용오차를 쓴다
    tol := InStr(file, "armed") ? ARMED_TOL : TOL

    if browserHwnd && WinExist("ahk_id " browserHwnd) {
        WinGetPos &wx, &wy, &ww, &wh, "ahk_id " browserHwnd
        fx1 := wx, fy1 := wy, fx2 := wx + ww, fy2 := wy + wh
    } else {
        fx1 := SysGet(76), fy1 := SysGet(77)
        fx2 := fx1 + SysGet(78), fy2 := fy1 + SysGet(79)
        wx := fx1, wy := fy1, ww := fx2 - fx1, wh := fy2 - fy1
    }

    x1 := fx1, y1 := fy1, x2 := fx2, y2 := fy2

    if (USE_REGION && !forceFull) {
        if (lastFoundX != 0 || lastFoundY != 0) {
            x1 := Max(fx1, lastFoundX - REGION_PAD)
            y1 := Max(fy1, lastFoundY - REGION_PAD)
            x2 := Min(fx2, lastFoundX + REGION_PAD)
            y2 := Min(fy2, lastFoundY + REGION_PAD)
        } else {
            x1 := wx + Round(ww * REGION_X)
            y1 := wy + Round(wh * REGION_Y)
        }
    }

    try {
        if ImageSearch(&rx, &ry, x1, y1, x2, y2, "*" tol " " IMGDIR file) {
            lastFoundX := rx
            lastFoundY := ry
            return [rx, ry]
        }
    } catch as e {
        MsgBox "이미지 파일 오류: " file "`n" e.Message
        ExitApp
    }

    ; 좁은 영역에서 못 찾은 경우에만, 한 번 창 전체를 훑어본다
    ; (창을 옮겼거나 크기가 바뀐 경우 대비)
    if (allowFallback && USE_REGION && !forceFull) {
        try {
            if ImageSearch(&rx, &ry, fx1, fy1, fx2, fy2, "*" tol " " IMGDIR file) {
                lastFoundX := rx
                lastFoundY := ry
                return [rx, ry]
            }
        }
    }

    return 0
}

; 나타날 때까지 대기하고 위치를 그대로 반환 (재탐색 제거)
WaitImagePos(file, timeout) {
    global POLL_FAST
    endT := A_TickCount + timeout
    while (A_TickCount < endT) {
        if (pos := FindImage(file))
            return pos
        Sleep POLL_FAST
    }
    return 0
}

; 이미지가 사라질 때까지 대기 (페이지 전환 감지용)
; 사라지면 true, 시간초과면 false
WaitImageGone(file, timeout) {
    global POLL_FAST
    endT := A_TickCount + timeout
    while (A_TickCount < endT) {
        if !FindImage(file, false, false)
            return true
        Sleep POLL_FAST
    }
    return false
}

CenterOf(pos, file) {
    global CLICK_OFF_X, CLICK_OFF_Y, AUTO_CENTER

    if AUTO_CENTER {
        sz := PngSize(file)
        if (sz[1] > 0 && sz[2] > 0)
            return [pos[1] + sz[1] // 2, pos[2] + sz[2] // 2]
    }
    return [pos[1] + CLICK_OFF_X, pos[2] + CLICK_OFF_Y]
}

; PNG 헤더에서 크기 읽기 (오프셋 16=가로, 20=세로, 빅엔디안 4바이트)
PngSize(file) {
    global IMGDIR
    path := IMGDIR file
    if !FileExist(path)
        return [0, 0]
    try {
        buf := FileRead(path, "RAW")
        if (buf.Size < 24)
            return [0, 0]
        if (NumGet(buf, 0, "UChar") != 0x89 || NumGet(buf, 1, "UChar") != 0x50)
            return [0, 0]
        w := BE32(buf, 16)
        h := BE32(buf, 20)
        if (w < 5 || w > 2000 || h < 5 || h > 2000)
            return [0, 0]
        return [w, h]
    }
    return [0, 0]
}

BE32(buf, off) {
    return (NumGet(buf, off, "UChar") << 24)
         | (NumGet(buf, off + 1, "UChar") << 16)
         | (NumGet(buf, off + 2, "UChar") << 8)
         |  NumGet(buf, off + 3, "UChar")
}

; ---------- 창 ----------
FocusBrowser() {
    global browserHwnd
    if !WinExist("ahk_id " browserHwnd) {
        SpeedReport(true)
        ToolTip()
        WriteLog("=== 크롬 창 소실. 중단 ===")
        MsgBox "크롬 창이 사라졌습니다.`n진행 위치는 저장되어 있습니다."
        ExitApp
    }
    if WinGetMinMax("ahk_id " browserHwnd) = -1
        WinRestore "ahk_id " browserHwnd
    if !WinActive("ahk_id " browserHwnd) {
        WinActivate "ahk_id " browserHwnd
        if !WinWaitActive("ahk_id " browserHwnd, , 3)
            return false
        Sleep 120
    }
    return true
}

; ---------- 속도 측정 ----------
SpeedText() {
    global statStart, statDone, statDup, statFail, statIdx, statTotal

    if !statStart
        return "측정 전"

    elapsed := (A_TickCount - statStart) / 1000
    processed := statDone + statDup + statFail
    if (processed = 0)
        return "측정 중"

    perItem := elapsed / processed
    perHour := Round(3600 / perItem)
    remain  := statTotal - statIdx
    etaMin  := Round(remain * perItem / 60)

    return "속도 : 개당 " Round(perItem, 2) "초  ·  시간당 " perHour "개`n"
         . "예상 남은 시간 : " (etaMin >= 60 ? Round(etaMin / 60, 1) "시간" : etaMin "분")
}

SpeedReport(toLog, showBox := true) {
    global SPEEDLOG
    txt := SpeedText()
    if toLog {
        try FileAppend FormatTime(A_Now, "MM-dd HH:mm:ss") "`n" txt "`n`n", SPEEDLOG, "UTF-8"
    }
    if showBox && !toLog {
        ToolTip txt, 20, 120
        SetTimer () => ToolTip(, , , 1), -5000
    }
}

; ---------- 기록 ----------
RecordDone(url) {
    global DONEFILE
    FileAppend url "`n", DONEFILE, "UTF-8"
}

WriteLog(t) {
    global LOGFILE
    FileAppend FormatTime(A_Now, "MM-dd HH:mm:ss") "  " t "`n", LOGFILE, "UTF-8"
}

ShowStatus() {
    global statIdx, statTotal, statDone, statDup, statFail, statArmed
    global statStart

    spd := ""
    if statStart {
        elapsed := (A_TickCount - statStart) / 1000
        processed := statDone + statDup + statFail
        if (processed > 0) {
            perItem := elapsed / processed
            spd := "`n개당 " Round(perItem, 1) "초  ·  시간당 " Round(3600 / perItem) "개"
        }
    }

    ToolTip statIdx "/" statTotal
          . "`n수집 " statDone " · 중복 " statDup " · 실패 " statFail
          . "`nARMED " statArmed
          . spd
          . "`n(F2 중단 / F10 속도)", 20, 20
}
