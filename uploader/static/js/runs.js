/* 실행 기록과 불러오기 기록 */
"use strict";

const ACT_STATUS = { running: ["진행 중", "c-run"], done: ["끝", "c-ok"], stopped: ["중단됨", "c-warn"], error: ["오류", "c-err"], lost: ["끝 확인 못 함", "c-warn"] };

/* 설정 키 → 설정 화면의 이름 */
function settingLabel(k) {
  for (const s of (typeof SETTING_SECTIONS !== "undefined" ? SETTING_SECTIONS : [])) {
    const f = (s.fields || []).find((x) => x[0] === k);
    if (f) return f[1];
  }
  return k;
}

/* 작업 기록 한 줄의 결과 문장 */
function actResult(r) {
  if (r.error) return `<span class="c-err">${esc(r.error)}</span>`;
  let d = null;
  try { d = r.detail ? JSON.parse(r.detail) : null; } catch { d = null; }
  if (Array.isArray(d)) {   // 설정·템플릿 변경 목록
    return `<ul class="act-diff">${d.map((x) => `<li><b>${esc(x.label || settingLabel(x.key))}</b> ${x.old !== "" ? `<s>${esc(x.old)}</s> → ` : ""}${esc(x.new || "(비움)")}</li>`).join("")}</ul>`;
  }
  if (d && r.status !== "running") {
    try { return esc(App.taskMsg({ kind: r.kind, title: r.title, result: d, status: r.status })) + (r.result ? ` · ${esc(r.result)}` : ""); } catch { /* 아래로 */ }
  }
  return esc(r.result || (r.status === "running" ? "진행 중…" : ""));
}

App.page("runs", {
  af: { grp: "", days: "", q: "", page: 0 },

  async loadActivity() {
    const box = $("#act-box");
    if (!box) return;
    const f = this.af, size = 100;
    const qs = new URLSearchParams({ grp: f.grp, days: f.days, q: f.q, page: f.page + 1, size });
    let d;
    try { d = await App.api(`/api/activity?${qs}`); } catch (e) { box.innerHTML = `<p class="c-err pad-x">${esc(e.message)}</p>`; return; }
    const g = $("#act-grp");
    if (g && g.options.length - 1 !== d.groups.length) {
      g.innerHTML = `<option value="">모든 작업</option>` + d.groups.map((x) => `<option ${x === f.grp ? "selected" : ""}>${esc(x)}</option>`).join("");
    }
    box.innerHTML = `<table class="grid act-table"><thead><tr><th class="w-when">시작</th><th class="w-when">끝</th><th class="w-num">걸린 시간</th>
        <th>묶음</th><th>작업</th><th>스토어</th><th class="w-num">대상</th><th>결과</th><th>상태</th></tr></thead>
      <tbody>${d.rows.length ? d.rows.map((r) => {
        const [st, cls] = ACT_STATUS[r.status] || [r.status, ""];
        const sec = r.ended_at ? r.ended_at - r.started_at : r.status === "running" ? Date.now() / 1000 - r.started_at : null;
        return `<tr><td class="nowrap">${stamp(r.started_at)}</td><td class="nowrap muted">${r.ended_at && r.ended_at - r.started_at >= 1 ? stamp(r.ended_at) : r.ended_at ? "바로" : "-"}</td>
          <td class="num">${sec != null && sec >= 1 ? dur(sec) : "-"}</td><td class="small">${esc(r.grp)}</td><td>${esc(r.title)}</td>
          <td class="small">${esc(r.store || "")}</td><td class="num">${r.count != null ? num(r.count) : ""}</td>
          <td class="small act-res">${actResult(r)}</td><td class="nowrap ${cls}">${st}</td></tr>`;
      }).join("") : `<tr class="empty-row"><td colspan="9">기록이 없습니다.</td></tr>`}</tbody></table>`;
    App.pager($("#act-pager"), { page: f.page, size, total: d.total, onPage: (p) => { this.af.page = p; this.loadActivity(); } });
  },

  async mount(el) {
    const [runs, imports, plans, kw] = await Promise.all([App.api("/api/runs"), App.api("/api/imports"), App.api("/api/plans"),
      App.api("/api/ctx/runs")]);
    const done = runs.filter((r) => r.ended_at && r.ok + r.fail);
    const items = done.reduce((a, r) => a + r.ok + r.fail, 0);
    const per = items ? done.reduce((a, r) => a + (r.ended_at - r.started_at), 0) / items : null;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>실행 기록</h1></header>
      <div class="tiles">${[
        ["등록 실행", num(runs.length) + "번"], ["처리한 건", num(items) + "건"],
        ["1건당 실제 걸린 시간", per ? per.toFixed(2) + "초" : "-"], ["1만 건 예상", per ? dur(per * 10000) : "-"],
      ].map(([l, v]) => `<div class="tile static"><div class="t-label">${l}</div><div class="t-num">${v}</div></div>`).join("")}</div>
      <p class="muted small" style="margin:0">1건당 시간은 여러 스토어를 나란히 돌린 실제 벽시계 시간 기준입니다.</p>
      <section class="card table-card" id="act-sec"><div class="sec-head pad-x"><h2>작업 기록</h2>
        <span class="muted small">프로그램에서 실행한 모든 작업과 설정 변경 (껐다 켜도 남음)</span></div>
        <div class="act-filter pad-x">
          <select id="act-grp" class="sel"><option value="">모든 작업</option></select>
          <select id="act-days" class="sel"><option value="">전체 기간</option><option value="1">오늘·어제 (24시간)</option><option value="7">7일</option><option value="30">30일</option></select>
          <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
            <input id="act-q" placeholder="작업·결과·스토어 검색"></div>
          <div id="act-pager" class="pager"></div>
        </div>
        <div id="act-box" class="muted pad-x">불러오는 중</div></section>
      <section class="card table-card"><div class="sec-head pad-x"><h2>등록 실행</h2></div>
        <table class="grid"><thead><tr><th>시작</th><th>메모</th><th class="w-num">대상</th><th class="w-num">성공</th>
          <th class="w-num">실패</th><th class="w-num">걸린 시간</th><th class="w-num">분당</th><th class="w-num">새 이미지</th></tr></thead>
        <tbody>${runs.length ? runs.map((r) => {
          const sec = r.ended_at ? r.ended_at - r.started_at : null, n = r.ok + r.fail;
          return `<tr><td>${when(r.started_at)}</td><td>${esc(r.note)}</td><td class="num">${num(r.total)}</td>
            <td class="num c-ok">${num(r.ok)}</td><td class="num ${r.fail ? "c-err" : ""}">${num(r.fail)}</td>
            <td class="num">${r.ended_at ? dur(sec) : "진행 중"}</td><td class="num">${n && sec ? num(Math.round((n / sec) * 60)) : "-"}</td>
            <td class="num">${num(r.images)}</td></tr>`;
        }).join("") : `<tr class="empty-row"><td colspan="8">아직 기록이 없습니다.</td></tr>`}</tbody></table></section>
      <section class="card table-card"><div class="sec-head pad-x"><h2>등록 계획</h2></div>
        <table class="grid"><thead><tr><th>만든 때</th><th>이름</th><th class="w-num">스토어</th><th class="w-num">전체</th>
          <th class="w-num">완료</th><th class="w-num">대기</th><th class="w-num">실패</th><th class="w-act"></th></tr></thead>
        <tbody>${plans.length ? plans.map((p) => `<tr><td>${when(p.created_at)}</td><td>${esc(p.title)}</td>
          <td class="num">${num(p.stores)}</td><td class="num">${num(p.total)}</td><td class="num c-ok">${num(p.success)}</td>
          <td class="num">${num(p.pending)}</td><td class="num ${p.fail ? "c-err" : ""}">${num(p.fail)}</td>
          <td class="r"><a href="#listings?plan_id=${p.id}">보기</a></td></tr>`).join("")
          : `<tr class="empty-row"><td colspan="8">아직 계획이 없습니다.</td></tr>`}</tbody></table></section>
      <section class="card table-card"><div class="sec-head pad-x"><h2>AI 키워드 받기</h2><span class="muted small">실제 비용 = 응답 사용량 기준 (일괄 50% 할인 · 캐시로 읽은 지시문 0.1배 반영)</span></div>
        <table class="grid"><thead><tr><th>시작</th><th>방식</th><th>모델</th><th class="w-num">원본</th><th class="w-num">요청</th>
          <th class="w-num">받음</th><th class="w-num">재시도 대기</th><th class="w-num">토큰 (입력/출력)</th><th class="w-num" title="입력 중 캐시로 읽은 토큰 (지시문을 다시 쓴 양, 요금 0.1배)">캐시로 읽음</th><th class="w-num">실제 비용</th><th class="w-num">예상</th><th>상태</th></tr></thead>
        <tbody>${kw.length ? kw.map((r) => `<tr><td>${when(r.started_at)}</td><td>${r.mode === "batch" ? "일괄" : "즉시"}</td><td class="small">${esc(r.model)}</td>
          <td class="num">${num(r.sources)}</td><td class="num">${num(r.requests)}</td><td class="num c-ok">${num(r.ok)}</td>
          <td class="num ${r.failed ? "c-err" : ""}">${num(r.failed)}</td><td class="num">${num(r.in_tok)} / ${num(r.out_tok)}</td>
          <td class="num">${r.in_tok ? `${num(r.cache_tok || 0)} <span class="muted small">(${Math.round(((r.cache_tok || 0) / r.in_tok) * 100)}%)</span>` : "-"}</td>
          <td class="num">${num(Math.ceil(r.cost_usd * r.rate))}원</td><td class="num muted">${num(Math.ceil(r.est_cost_usd * r.rate))}원</td>
          <td>${{ running: "진행 중", canceling: "중지 중", canceled: "중지됨", done: "끝", failed: "실패" }[r.status] || esc(r.status)}${r.note ? ` <span class="muted small">${esc(r.note)}</span>` : ""}</td></tr>`).join("")
          : `<tr class="empty-row"><td colspan="12">아직 기록이 없습니다.</td></tr>`}</tbody></table></section>
      <section class="card table-card"><div class="sec-head pad-x"><h2>불러오기</h2></div>
        <table class="grid"><thead><tr><th>시각</th><th>종류</th><th>파일</th><th class="w-num">줄</th><th class="w-num">새로</th>
          <th class="w-num">갱신</th><th>메모</th></tr></thead>
        <tbody>${imports.length ? imports.map((i) => `<tr><td>${when(i.created_at)}</td><td>${i.kind === "names" ? "상품명" : "원본"}</td>
          <td>${esc(i.file_name)}</td><td class="num">${num(i.total)}</td><td class="num">${num(i.added)}</td>
          <td class="num">${num(i.updated)}</td><td class="muted small">${esc(i.note)}</td></tr>`).join("")
          : `<tr class="empty-row"><td colspan="7">아직 기록이 없습니다.</td></tr>`}</tbody></table></section>
    </div>`;
    const f = this.af;
    $("#act-grp").addEventListener("change", (e) => { f.grp = e.target.value; f.page = 0; this.loadActivity(); });
    $("#act-days").addEventListener("change", (e) => { f.days = e.target.value; f.page = 0; this.loadActivity(); });
    let tq;
    $("#act-q").addEventListener("input", (e) => { clearTimeout(tq); tq = setTimeout(() => { f.q = e.target.value.trim(); f.page = 0; this.loadActivity(); }, 300); });
    $("#act-days").value = f.days;
    $("#act-q").value = f.q;
    await this.loadActivity();
    this.onDone = () => this.loadActivity();
    App.on("task-done", this.onDone);
  },
  unmount() { if (this.onDone) App.off("task-done", this.onDone); },
});
