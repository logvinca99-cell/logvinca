/* 한눈에 보기: 전체 숫자, 시작 순서, 스토어별 사용량 */
"use strict";

App.page("home", {
  async mount(el) {
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>한눈에 보기</h1>
        <div class="head-actions"><a class="btn" href="#inventory">원본 상품</a><a class="btn primary" href="#listings">등록하러 가기</a></div></header>
      <div class="tiles" id="h-tiles"></div>
      <div id="h-steps"></div>
      <section class="card pad">
        <div class="sec-head"><h2>스토어별 사용량</h2><span class="muted small">사업자별 · 네이버 상품·고구마(전시중지)·등록 대기 포함 · 누르면 그 스토어 복사본</span></div>
        <div id="h-stores" class="h-stores"></div>
      </section>
    </div>`;
    this.el = el;
    this.onDone = () => this.load();
    App.on("task-done", this.onDone);
    App.on("run-done", this.onDone);
    await this.load();
  },
  unmount() { App.off("task-done", this.onDone); App.off("run-done", this.onDone); },

  async load() {
    const [st, stores] = await Promise.all([App.refreshState(), App.loadStores()]);
    const s = st.stats;
    $("#h-tiles").innerHTML = [
      ["원본 상품", s.sources, "var(--text-2)"], ["등록 가능 원본", s.sources_valid, "var(--idle)"],
      ["안 쓴 이름 후보", s.names_free, "var(--info)"], ["판매 중", s.registered, "var(--ok)"],
      ["할 일 대기", s.pending, "var(--warn)"], ["판매 이력 있는 복사본", s.sold, "var(--warn)"], ["잠금", s.locked, "var(--info)"], ["실패", s.failed, "var(--err)"],
    ].map(([l, n, c]) => `<div class="tile static" style="--dot:${c}"><div class="t-label">${l}</div><div class="t-num">${num(n)}</div></div>`).join("");

    const steps = [
      [s.stores > 0, "스토어 추가", "스토어마다 커머스API 키를 넣습니다. 여러 개는 한 번에 붙여 넣을 수 있습니다.", "#stores"],
      [st.categories > 0, "카테고리 받기", "스토어 화면의 '연결 확인'이나 설정 화면에서 받습니다.", "#stores"],
      [s.sources > 0, "원본 엑셀 불러오기", "화면 어디에나 엑셀을 끌어다 놓아도 됩니다.", "#inventory"],
      [s.pending + s.registered > 0, "다른 스토어로 복사", "원본 상품에서 원본을 걸러 고르고 보낼 스토어(1~2곳)를 고릅니다.", "#inventory"],
      [s.names > s.sources, "상품명 바꾸기", "복사본에서 스토어를 고르고 '이름 변경 필요'를 AI 키워드·AI로 짓기·셔플로 바꿉니다.", "#listings"],
      [s.registered > 0, "등록 시작", "복사본 화면에서 스토어를 고르고 시작합니다.", "#listings"],
    ];
    $("#h-steps").innerHTML = steps.every((x) => x[0]) ? "" : `<section class="card pad steps">
      <h2>시작 순서</h2><ol>${steps.map(([done, t, d, href]) =>
        `<li class="${done ? "done" : ""}"><a href="${href}"><b>${t}</b><span class="muted small">${d}</span></a></li>`).join("")}</ol></section>`;

    $("#h-stores").onclick = (e) => { const c = e.target.closest("[data-go]"); if (c && !e.target.closest("a")) App.go(c.dataset.go); };
    $("#h-stores").innerHTML = stores.length ? byBusiness(stores).map(([biz, ss]) => `<div class="h-biz">
        <div class="h-biz-title">${esc(biz)} <span class="muted small">스토어 ${ss.length}</span></div>
        <div class="h-biz-cards">${ss.map((x) => `<div class="h-store ${x.enabled ? "" : "off"} ${regionCls(x)}" data-go="#listings?store_id=${x.id}" title="누르면 이 스토어 복사본">
          <div class="st-card-head"><span class="code">${esc(x.code)}</span><b>${esc(x.name)}</b>${x.has_keys ? "" : '<span class="flag warn">키 없음</span>'}${x.ship_region ? `<span class="region-tag">${REGION[x.ship_region]}</span>` : ""}</div>
          ${storeUsage(x)}
          <div class="st-meta">대기 ${num(x.n_pending + x.n_ops)}${x.n_fail ? ` · <span class="c-err">실패 ${num(x.n_fail)}</span>` : ""}${x.n_sold ? ` · 판매됨 ${num(x.n_sold)}` : ""}${x.oldest_at ? ` · 가장 오래된 것 ${age(x.oldest_at)}` : ""}</div>
          ${storeLinks(x)}
        </div>`).join("")}</div></div>`).join("") : `<p class="muted">아직 스토어가 없습니다. <a href="#stores">스토어 추가</a></p>`;
  },
});
