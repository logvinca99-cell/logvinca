/* 등록: 계획된 건 목록, 등록 실행(여러 스토어 동시), 진행 상황 */
"use strict";

const LST_TILES = [
  { key: "all", label: "전체", dot: "var(--text-2)", count: "all_" },
  { key: "live", label: "판매 중", dot: "var(--ok)" },
  { key: "pending", label: "할 일 대기", dot: "var(--idle)" },
  { key: "fail", label: "실패", dot: "var(--err)" },
  { key: "sold", label: "판매 이력 있음", dot: "var(--warn)" },
  { key: "locked", label: "잠금", dot: "var(--info)" },
  { key: "deleted", label: "내림", dot: "var(--dup)" },
];

App.page("listings", {
  size: 100,

  async mount(el, params) {
    this.f = { status: "all", store_id: "", plan_id: "", q: "", age_days: "", ...params };
    this.page = 0;
    this.sel = new Set();
    this.selAll = false;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>복사본</h1>
        <div class="head-actions">
          <a class="btn ghost" id="l-export">결과 CSV</a>
          <label class="btn" title="아바닛 등 주문 수집 웹에서 내려받은 주문 파일"><input type="file" id="l-sales-file" accept=".xlsx,.xlsm,.csv" hidden>판매 이력 파일 가져오기</label>
          <a class="btn" href="#orders" title="판매자센터 주문을 가져오고 기간·스토어별로 보기">판매 현황</a>
        </div></header>
      <div class="card run" id="l-run"></div>
      <div class="toolbar"><div class="filters">
        <select id="l-store" class="sel"><option value="">모든 스토어</option></select>
        <select id="l-plan" class="sel"><option value="">모든 계획</option></select>
        <select id="l-age" class="sel"><option value="">올린 날 전체</option><option value="7">올린 지 7일 넘음</option>
          <option value="30">30일 넘음</option><option value="60">60일 넘음</option><option value="90">90일 넘음</option></select>
        <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
          <input id="l-q" placeholder="상품명·관리코드·상품번호"></div>
      </div></div>
      <div class="tiles" id="l-tiles"></div>
      <div class="actionbar" id="l-actions"></div>
      <div class="card table-card">
        <table class="grid"><thead><tr><th class="w-check"><input type="checkbox" id="l-check-all" aria-label="이 쪽 모두 선택"></th>
          <th class="w-thumb"></th><th>등록 상품명</th><th class="w-store">스토어</th>
          <th class="w-round">관리코드 · 올린 날</th><th class="w-num">판매가</th><th class="w-status">상태</th></tr></thead><tbody id="l-rows"></tbody></table>
        <div class="pager" id="l-pager"></div>
      </div>
    </div>`;
    $("#l-store").innerHTML += App.stores.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
    const plans = await App.api("/api/plans");
    $("#l-plan").innerHTML += plans.map((p) => `<option value="${p.id}">${esc(p.title)} · ${num(p.total)}건</option>`).join("");
    $("#l-store").value = this.f.store_id || "";
    $("#l-plan").value = this.f.plan_id || "";
    $("#l-age").value = this.f.age_days || "";
    this.bind();
    this.onRun = (r) => this.renderRun(r);
    this.onDone = () => { this.estKey = ""; this.load(); };
    App.on("run", this.onRun);
    App.on("run-done", this.onDone);
    App.on("task-done", this.onDone);
    await this.load();
    this.renderRun(App.run);
  },
  unmount() {
    App.off("run", this.onRun); App.off("run-done", this.onDone); App.off("task-done", this.onDone);
    clearInterval(this.timer);
  },

  /* 시작·예상 시간은 스토어·계획 범위만 따른다 (상태·올린 날·검색어 거르기와 무관하게 대기·실패 건 전부) */
  runScope() {
    const f = {};
    if (this.f.store_id) f.store_id = this.f.store_id;
    if (this.f.plan_id) f.plan_id = this.f.plan_id;
    return f;
  },

  query() {
    const f = { ...this.f };
    Object.keys(f).forEach((k) => (f[k] === "" || f[k] == null) && delete f[k]);
    if (f.status === "all") delete f.status;
    return f;
  },

  async load() {
    const qs = new URLSearchParams({ ...this.query(), page: this.page, size: this.size });
    const res = await App.api(`/api/listings?${qs}`);
    this.counts = res.counts || {};
    this.rows = res.rows;
    this.total = res.total;
    $("#l-tiles").innerHTML = tilesHtml(LST_TILES, { ...this.counts, all: this.counts.all_ }, this.f.status);
    $("#l-rows").innerHTML = res.rows.length ? res.rows.map((l) => this.rowHtml(l)).join("")
      : `<tr class="empty-row"><td colspan="7">${this.counts.all_ ? "조건에 맞는 건이 없습니다."
        : '아직 등록 계획이 없습니다. <a href="#inventory">원본 상품</a>에서 상품을 고르고 <b>스토어에 올리기 계획</b>을 만드세요.'}</td></tr>`;
    App.pager($("#l-pager"), { page: this.page, size: this.size, total: res.total, onPage: (p) => { this.page = p; this.load(); } });
    $("#l-export").href = `/api/listings/export.csv?${new URLSearchParams(this.query())}`;
    $("#l-check-all").checked = res.rows.length > 0 && res.rows.every((l) => this.sel.has(l.id));
    this.renderActions();
    if (!App.run?.running) this.renderIdle();
  },

  rowHtml(l) {
    const diff = l.source_price ? ((l.price - l.source_price) / l.source_price) * 100 : 0;
    let msg = "", cls = "";
    if (l.status === "fail") { msg = l.message; cls = "err"; }
    else if (l.status === "success") msg = `상품번호 ${l.channel_no}`;
    else if (l.status === "running") msg = l.stage;
    else if (l.status === "deleted") msg = `${ymd(l.deleted_at)}에 내림`;
    const on = this.selAll || this.sel.has(l.id);
    const others = (l.source_copies > 1 ? `<span class="flag" title="같은 원본이 다른 스토어에도 있음">같은 원본 ${l.source_copies}곳</span>` : "")
      + lockFlag(l) + salesFlag(l);
    return `<tr data-id="${l.id}" class="${on ? "sel" : ""} ${l.status === "deleted" ? "off" : ""}">
      <td class="w-check" data-stop><input type="checkbox" ${on ? "checked" : ""} ${this.selAll ? "disabled" : ""}></td>
      <td>${img(l.thumb)}</td>
      <td><div class="p-name">${esc(l.name)}</div><div class="p-sub"><span>원본 #${l.source_id}</span>${others}</div></td>
      <td><b class="code">${esc(l.store_code)}</b> ${esc(l.store_name)}</td>
      <td>${esc(l.seller_code || "-")}<div class="p-sub">${l.round}회차${l.registered_at && l.origin_no ? ` · ${ymd(l.registered_at)} (${age(l.registered_at)})` : ""}</div></td>
      <td class="num">${num(l.price)}원<div class="p-sub r">${diff ? (diff > 0 ? "+" : "") + diff.toFixed(1) + "%" : "원본가"}</div></td>
      <td>${statusBadge(l.status, l.op)}${msg ? `<div class="s-msg ${cls}" title="${esc(msg)}">${esc(msg)}</div>` : ""}</td></tr>`;
  },

  renderActions() {
    const n = this.selAll ? this.total : this.sel.size;
    const target = this.selAll ? `조건에 맞는 <b>${num(this.total)}건 전체</b>` : n ? `<b>${num(n)}건</b> 선택` : "";
    $("#l-actions").innerHTML = `<div class="ab-left">
        ${target ? `<span>${target}</span><button class="link-btn" id="la-clear">선택 해제</button>` : `<span class="muted">건을 고르거나</span>`}
        ${!this.selAll && this.total ? `<button class="link-btn" id="la-all">조건에 맞는 ${num(this.total)}건 모두 고르기</button>` : ""}
      </div>
      <div class="ab-right">
        <button class="btn" id="la-refresh" ${n ? "" : "disabled"} title="판매 중인 건을 네이버에서 지우고 같은 내용으로 다시 올림 (회차 +1)">최신화 예약</button>
        <button class="btn" id="la-delete" ${n ? "" : "disabled"} title="판매 중인 건을 네이버에서 지움. 원본의 빈 칸이 생겨 다른 스토어에 올릴 수 있음">내리기 예약</button>
        <button class="btn ghost danger-text" id="la-cancel" ${n ? "" : "disabled"} title="아직 처리 안 된 대기·실패 할 일을 취소">대기·실패 취소</button>
        <span class="ab-sep"></span>
        <button class="btn" id="la-lock" ${n ? "" : "disabled"} title="판매 이력과 상관없이 지우지 못하게 잠금">잠금</button>
        <button class="btn ghost" id="la-unlock" ${n ? "" : "disabled"} title="직접 건 잠금을 풂 (판매 이력으로 걸린 잠금은 그대로)">잠금 풀기</button>
      </div>`;
  },

  target() {
    if (this.selAll) { const f = this.query(); return f; }
    return { ids: [...this.sel] };
  },

  async lock(on, ids) {
    try {
      const r = await App.api("/api/listings/lock", { json: { ...(ids ? { ids } : this.target()), lock: on } });
      App.toast(on ? `${num(r.count)}건을 잠갔습니다. 최신화·내리기로 지우지 않습니다.`
        : `${num(r.count)}건의 직접 잠금을 풀었습니다.` + (r.still_locked ? ` ${num(r.still_locked)}건은 판매 이력이 있어 잠금이 유지됩니다.` : ""));
      if (!ids) { this.clearSel(); this.load(); }
      return r;
    } catch (e) { App.toast(e.message, true); }
  },

  async schedule(op) {
    const label = op === "refresh" ? "최신화(지우고 다시 올리기)" : "내리기(네이버에서 지우기)";
    if (!confirm(`고른 건 중 판매 중인 건에 ${label}를 예약할까요?\n잠긴 건(판매 이력·직접 잠금)은 빠집니다. 시작할 때 주문을 한 번 더 확인합니다.\n예약만 하고, 위의 [시작]을 눌러야 실제로 처리합니다.`)) return;
    try {
      const r = await App.api("/api/listings/schedule", { json: { ...this.target(), op } });
      App.toast(`${num(r.scheduled)}건 예약했습니다.` + (r.skipped_sold ? ` 잠긴 ${num(r.skipped_sold)}건(판매 이력·직접 잠금)은 뺐습니다.` : "") + " 위에서 시작을 누르세요.");
      this.sel.clear(); this.selAll = false; this.estKey = "";
      this.load();
    } catch (e) { App.toast(e.message, true); }
  },

  // ── 실행 패널

  renderIdle() {
    const box = $("#l-run");
    const c = this.counts;
    const n = (c.pending || 0) + (c.fail || 0);
    const scope = [this.f.store_id && $("#l-store").selectedOptions[0]?.text, this.f.plan_id && $("#l-plan").selectedOptions[0]?.text.split(" · ")[0]]
      .filter(Boolean).join(" · ");
    box.innerHTML = `<div class="run-idle">
        <div class="run-actions">
          <button class="btn primary big" id="l-start" ${n ? "" : "disabled"}>▶ 시작 · ${num(n)}건</button>
          <button class="btn big" id="l-one" ${n ? "" : "disabled"}>1건만 시험</button>
        </div>
        <div class="run-est"><div>${scope ? `<b>${esc(scope)}</b>의 ` : "모든 스토어의 "}대기·실패 건을 처리합니다:
          등록 ${num(c.pending_create)} · 최신화 ${num(c.pending_refresh)} · 내리기 ${num(c.pending_delete)} · 실패 재시도 ${num(c.fail)}</div>
          <div id="l-est" class="muted small"></div></div>
      </div>`;
    $("#l-start").addEventListener("click", () => this.start());
    $("#l-one").addEventListener("click", () => this.start(1));
    if (!n) return;
    const key = JSON.stringify(this.runScope()) + n;
    if (key === this.estKey) { $("#l-est").innerHTML = this.estHtml || ""; return; }
    this.estKey = key;
    App.api("/api/run/estimate", { json: this.runScope() }).then((e) => {
      this.estHtml = `예상 <b>약 ${dur(e.seconds)}</b> · 스토어 ${e.stores}곳을 ${e.parallel}곳씩 나란히, 스토어마다 ${e.workers}건씩 동시에 · ${esc(e.basis)}`;
      const el = $("#l-est");
      if (el) el.innerHTML = this.estHtml;
    }).catch(() => {});
  },

  async start(limit) {
    const n = limit || (this.counts.pending || 0) + (this.counts.fail || 0);
    if (!limit && !confirm(`${num(n)}건을 처리합니다 (등록·최신화·내리기). 계속할까요?`)) return;
    try {
      App.run = await App.api("/api/run", { json: { ...this.runScope(), limit: limit || null } });
      this.renderRun(App.run);
      App.renderSideRun();
    } catch (e) { App.toast(e.message, true); }
  },

  renderRun(r) {
    if (!r?.running) {
      if (this._live) { this._live = false; this.renderIdle(); }
      this.renderLog(r);
      return;
    }
    const box = $("#l-run");
    if (!this._live) {
      this._live = true;
      box.innerHTML = `<div class="run-top">
          <div class="run-count"><b id="r-done">0</b><span> / <span id="r-total">0</span></span></div>
          <div class="run-meta">
            <div><span class="muted">성공</span><b class="c-ok" id="r-ok">0</b></div>
            <div><span class="muted">실패</span><b class="c-err" id="r-fail">0</b></div>
            <div><span class="muted">잠금으로 건너뜀</span><b id="r-skip">0</b></div>
            <div><span class="muted">속도</span><b id="r-rate">-</b></div>
            <div><span class="muted">남은 시간</span><b id="r-eta">-</b></div>
            <div><span class="muted">새로 올린 이미지</span><b id="r-img">0</b></div>
          </div>
          <div class="run-ctl"><button class="btn" id="r-pause">일시정지</button><button class="btn danger" id="r-stop">중단</button></div>
        </div>
        <div class="bar"><div class="bar-ok" id="r-bar-ok"></div><div class="bar-err" id="r-bar-err"></div></div>
        <div class="run-state" id="r-state"></div>
        <div class="store-chips" id="r-stores"></div>
        <ul class="current" id="r-current"></ul>
        <details class="log" open><summary>작업 기록 <span class="muted" id="r-logn"></span></summary><ol id="r-log"></ol></details>`;
      $("#r-pause").addEventListener("click", async () => {
        App.run = await App.api(`/api/run/${App.run?.paused ? "resume" : "pause"}`, { method: "POST" }); this.renderRun(App.run);
      });
      $("#r-stop").addEventListener("click", async () => {
        if (!confirm("등록을 중단할까요? 처리 중인 건까지만 마치고 멈춥니다. 남은 건은 대기로 돌아갑니다.")) return;
        App.run = await App.api("/api/run/stop", { method: "POST" }); this.renderRun(App.run);
      });
      clearInterval(this.timer);
      this.timer = setInterval(() => { if (App.run?.running) this.load(); }, 4000);
    }
    $("#r-done").textContent = num(r.done);
    $("#r-total").textContent = num(r.total);
    $("#r-ok").textContent = num(r.ok);
    $("#r-fail").textContent = num(r.fail);
    $("#r-skip").textContent = num(r.skipped || 0);
    $("#r-rate").textContent = r.rate_per_min ? `분당 ${num(Math.round(r.rate_per_min))}건` : "재는 중";
    $("#r-eta").textContent = r.paused ? "일시정지" : r.eta != null ? dur(r.eta) : "재는 중";
    $("#r-img").textContent = num(r.images) + (r.images_reused ? ` (+${num(r.images_reused)} 재사용)` : "");
    $("#r-bar-ok").style.width = (r.total ? (r.ok / r.total) * 100 : 0) + "%";
    $("#r-bar-err").style.width = (r.total ? (r.fail / r.total) * 100 : 0) + "%";
    $("#r-pause").textContent = r.paused ? "▶ 계속" : "일시정지";
    $("#r-pause").disabled = $("#r-stop").disabled = r.stopping;
    $("#r-state").textContent = r.stopping ? "중단하는 중… 처리 중인 건까지만 마칩니다."
      : r.paused ? "일시정지됨" : `등록 중 · ${dur(r.elapsed)} 지남`;
    $("#r-stores").innerHTML = r.stores.map((s) => {
      const p = s.total ? (s.done / s.total) * 100 : 0;
      return `<div class="chip-store ${s.status === "등록 중" ? "on" : s.status === "끝" ? "done" : ""}" title="${esc(s.name)}: ${s.status}">
        <div class="cs-top"><span>${esc(s.name)}</span><span>${num(s.done)}/${num(s.total)}</span></div>
        <div class="bar thin"><div class="bar-ok" style="width:${s.total ? (s.ok / s.total) * 100 : 0}%"></div>
        <div class="bar-err" style="width:${s.total ? (s.fail / s.total) * 100 : 0}%"></div></div></div>`;
    }).join("");
    $("#r-current").innerHTML = r.current.slice(0, 8).map((c) =>
      `<li><span class="spin"></span><span class="c-name">${esc(c.name)}</span><span class="c-stage">${esc(c.stage)}</span></li>`).join("")
      + (r.current.length > 8 ? `<li class="muted small">외 ${r.current.length - 8}건 처리 중</li>` : "");
    this.renderLog(r);
  },

  renderLog(r) {
    const ol = $("#r-log");
    if (!ol || !r) return;
    $("#r-logn").textContent = r.log.length ? `(${r.log.length})` : "";
    ol.innerHTML = r.log.slice().reverse().map((l) => `<li class="l-${l.level}"><time>${new Date(l.t * 1000)
      .toLocaleTimeString("ko-KR", { hour12: false })}</time>${l.store ? `<span class="muted">${esc(l.store)}</span>` : ""}<span>${esc(l.msg)}</span></li>`).join("");
  },

  clearSel() { this.sel.clear(); this.selAll = false; },

  bind() {
    $("#l-sales-file").addEventListener("change", (e) => { if (e.target.files[0]) App.upload("/api/orders/import", e.target.files[0]); e.target.value = ""; });

    $("#l-tiles").addEventListener("click", (e) => {
      const t = e.target.closest("[data-filter]");
      if (t) { this.f.status = t.dataset.filter; this.page = 0; this.clearSel(); this.load(); }
    });
    $("#l-store").addEventListener("change", (e) => { this.f.store_id = e.target.value; this.page = 0; this.clearSel(); this.load(); });
    $("#l-plan").addEventListener("change", (e) => { this.f.plan_id = e.target.value; this.page = 0; this.clearSel(); this.load(); });
    let timer;
    $("#l-q").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { this.f.q = e.target.value.trim(); this.page = 0; this.load(); }, 300);
    });
    $("#l-age").addEventListener("change", (e) => { this.f.age_days = e.target.value; this.page = 0; this.clearSel(); this.load(); });
    $("#l-check-all").addEventListener("change", (e) => {
      this.selAll = false;
      this.rows.forEach((l) => (e.target.checked ? this.sel.add(l.id) : this.sel.delete(l.id)));
      this.load();
    });
    $("#l-actions").addEventListener("click", async (e) => {
      const id = e.target.closest("button")?.id;
      if (id === "la-clear") { this.clearSel(); this.load(); }
      if (id === "la-all") { this.selAll = true; this.sel.clear(); this.load(); }
      if (id === "la-refresh") this.schedule("refresh");
      if (id === "la-lock" || id === "la-unlock") this.lock(id === "la-lock");
      if (id === "la-delete") this.schedule("delete");
      if (id === "la-cancel") {
        if (!confirm("고른 건 중 대기·실패 할 일을 취소할까요?\n새 등록이면 계획을 지우고 이름을 후보로 돌립니다. 최신화·내리기면 판매 중으로 되돌립니다.")) return;
        try {
          const r = await App.api("/api/listings/cancel", { json: this.target() });
          App.toast(`${num(r.cancelled)}건을 취소했습니다.`);
          this.clearSel(); this.estKey = ""; this.load();
        } catch (err) { App.toast(err.message, true); }
      }
    });
    $("#l-rows").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (!tr) return;
      const id = +tr.dataset.id;
      if (e.target.closest("[data-stop]")) {
        if (this.selAll) return;
        this.sel.has(id) ? this.sel.delete(id) : this.sel.add(id);
        tr.classList.toggle("sel", this.sel.has(id));
        $("input", tr).checked = this.sel.has(id);
        this.renderActions();
        return;
      }
      this.openListing(id);
    });
  },

  async openListing(id) {
    let l;
    try { l = await App.api(`/api/listings/${id}`); } catch (e) { return App.toast(e.message, true); }
    const url = l.store_url && l.channel_no ? `${l.store_url.replace(/\/$/, "")}/products/${l.channel_no}` : "";
    App.openDrawer({
      title: l.name, sub: `${l.store_name} · ${statusLabel(l.status, l.op)} · ${l.round}회차`,
      tabs: [
        { key: "info", label: "정보", render: (b) => {
          b.innerHTML = (l.status === "fail" ? `<div class="notice err"><b>${esc(statusLabel(l.status, l.op))}</b><br>${esc(l.message)}</div>` : "")
            + (l.origin_no ? `<div class="notice ok"><b>판매 중</b> · 상품번호 ${esc(l.channel_no)} · ${ymd(l.registered_at)}에 올림 (${age(l.registered_at)})<br>
                ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">스토어에서 보기</a> · ` : ""}
                <a href="https://sell.smartstore.naver.com/#/products/edit/${esc(l.origin_no)}" target="_blank" rel="noopener">스마트스토어센터에서 수정</a></div>` : "")
            + `<div class="gallery">${img(l.thumb, "g-main")}</div>
              <dl class="kv"><dt>스토어</dt><dd>${esc(l.store_name)}</dd><dt>등록 상품명</dt><dd>${esc(l.name)}</dd>
              <dt>판매자 관리코드</dt><dd>${esc(l.seller_code || l.next_seller_code)} <span class="muted">(${l.round}회차${l.seller_code ? "" : ", 등록하면 붙음"})</span></dd>
              <dt>원본</dt><dd>#${l.source_id} ${esc(l.source_name)}</dd>
              <dt>판매가</dt><dd>${num(l.price)}원 <span class="muted">(원본가 ${num(l.source_price)}원)</span></dd>
              <dt>같은 원본</dt><dd>${l.siblings.length ? l.siblings.map((x) => `${esc(x.store_name)} · ${esc(x.name)} <span class="muted">(${STATUS[x.status] || x.status})</span>`).join("<br>") : "다른 스토어에는 없음"}</dd></dl>`
            + `<div class="notice ${l.locked ? "info" : ""} lock-box"><div><b>${l.locked ? "잠금" : "잠금 아님"}</b>${l.locked ? ` · ${esc(l.lock_note)} · 최신화·내리기로 지우지 않습니다` : " · 최신화·내리기 가능"}
                ${l.cancel_count ? `<br><span class="muted">취소·반품 ${num(l.cancel_count)}개는 판매로 세지 않음 (설정에서 바꿈)</span>` : ""}</div>
                <button class="btn" id="d-lock">${l.manual_lock ? "직접 잠금 풀기" : "직접 잠금"}</button></div>`
            + (l.orders.length ? `<div><h3 class="sec-title">주문 (판매 ${num(l.sold_count)}개${l.cancel_count ? ` · 취소·반품 ${num(l.cancel_count)}개` : ""})</h3><table class="opt-table"><tr><th>주문</th><th>수량</th><th>결제일</th><th>가져온 곳</th></tr>
              ${l.orders.map((o) => `<tr><td>${esc(o.order_key.replace(/^file:/, ""))}<div class="p-sub">${esc(o.status)}</div></td><td>${num(o.quantity)}</td><td>${ymd(o.ordered_at)}</td>
              <td>${o.source === "naver" ? "네이버 주문" : "주문 파일"}</td></tr>`).join("")}</table></div>` : "")
            + (l.history.length ? `<div><h3 class="sec-title">지난 회차</h3><table class="opt-table"><tr><th>회차</th><th>관리코드</th><th>상품번호</th><th>올린 날</th><th>지운 날</th></tr>
              ${l.history.map((h) => `<tr><td>${h.round}</td><td>${esc(h.seller_code)}</td><td>${esc(h.channel_no)}</td><td>${ymd(h.registered_at)}</td>
              <td>${ymd(h.deleted_at)} <span class="muted">${h.reason === "refresh" ? "최신화" : "내리기"}</span></td></tr>`).join("")}</table></div>` : "");
          $("#d-lock", b)?.addEventListener("click", async () => {
            const r = await this.lock(!l.manual_lock, [id]);
            if (r) { if ($("#l-rows")) this.load(); this.openListing(id); }
          });
        } },
        { key: "json", label: "보낼 데이터", render: (b) => {
          const body = JSON.parse(JSON.stringify(l.body));
          const dc = body?.originProduct?.detailContent;
          if (typeof dc === "string" && dc.length > 400) body.originProduct.detailContent = dc.slice(0, 400) + ` …(총 ${num(dc.length)}자)`;
          b.innerHTML = `<p class="muted small" style="margin:0">네이버 커머스API에 보낼 내용입니다. 아직 올리지 않은 이미지는 원본 주소로 보입니다.</p>
            <pre class="json">${esc(JSON.stringify(body, null, 2))}</pre>`;
        } },
      ],
      foot: ["planned", "fail"].includes(l.status) && !App.run?.running
        ? `<span class="muted"></span><button class="btn primary" id="d-run">이 건만 지금 처리</button>` : "",
    });
    $("#d-run")?.addEventListener("click", async () => {
      try {
        App.run = await App.api("/api/run", { json: { ids: [id] } }); App.closeDrawer();
        if ($("#l-run")) this.renderRun(App.run); else App.renderSideRun();
      }
      catch (e) { App.toast(e.message, true); }
    });
  },
});
