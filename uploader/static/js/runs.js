/* 실행 기록과 불러오기 기록 */
"use strict";

App.page("runs", {
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
      <section class="card table-card"><div class="sec-head pad-x"><h2>AI 키워드 받기</h2><span class="muted small">실제 비용 = 응답 사용량 기준 (일괄은 50% 할인 단가)</span></div>
        <table class="grid"><thead><tr><th>시작</th><th>방식</th><th>모델</th><th class="w-num">원본</th><th class="w-num">요청</th>
          <th class="w-num">받음</th><th class="w-num">재시도 대기</th><th class="w-num">토큰 (입력/출력)</th><th class="w-num">실제 비용</th><th class="w-num">예상</th><th>상태</th></tr></thead>
        <tbody>${kw.length ? kw.map((r) => `<tr><td>${when(r.started_at)}</td><td>${r.mode === "batch" ? "일괄" : "즉시"}</td><td class="small">${esc(r.model)}</td>
          <td class="num">${num(r.sources)}</td><td class="num">${num(r.requests)}</td><td class="num c-ok">${num(r.ok)}</td>
          <td class="num ${r.failed ? "c-err" : ""}">${num(r.failed)}</td><td class="num">${num(r.in_tok)} / ${num(r.out_tok)}</td>
          <td class="num">${num(Math.ceil(r.cost_usd * r.rate))}원</td><td class="num muted">${num(Math.ceil(r.est_cost_usd * r.rate))}원</td>
          <td>${{ running: "진행 중", canceling: "중지 중", canceled: "중지됨", done: "끝", failed: "실패" }[r.status] || esc(r.status)}${r.note ? ` <span class="muted small">${esc(r.note)}</span>` : ""}</td></tr>`).join("")
          : `<tr class="empty-row"><td colspan="11">아직 기록이 없습니다.</td></tr>`}</tbody></table></section>
      <section class="card table-card"><div class="sec-head pad-x"><h2>불러오기</h2></div>
        <table class="grid"><thead><tr><th>시각</th><th>종류</th><th>파일</th><th class="w-num">줄</th><th class="w-num">새로</th>
          <th class="w-num">갱신</th><th>메모</th></tr></thead>
        <tbody>${imports.length ? imports.map((i) => `<tr><td>${when(i.created_at)}</td><td>${i.kind === "names" ? "상품명" : "원본"}</td>
          <td>${esc(i.file_name)}</td><td class="num">${num(i.total)}</td><td class="num">${num(i.added)}</td>
          <td class="num">${num(i.updated)}</td><td class="muted small">${esc(i.note)}</td></tr>`).join("")
          : `<tr class="empty-row"><td colspan="7">아직 기록이 없습니다.</td></tr>`}</tbody></table></section>
    </div>`;
  },
});
