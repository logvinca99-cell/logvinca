/* 등록: 계획된 건 목록, 등록 실행(여러 스토어 동시), 진행 상황 */
"use strict";

const LST_TILES = [
  { key: "all", label: "전체", dot: "var(--text-2)", count: "all_" },
  { key: "pending", label: "등록 대기", dot: "var(--idle)" },
  { key: "success", label: "등록 완료", dot: "var(--ok)" },
  { key: "fail", label: "실패", dot: "var(--err)" },
];

App.page("listings", {
  size: 100,

  async mount(el, params) {
    this.f = { status: "all", store_id: "", plan_id: "", q: "", ...params };
    this.page = 0;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>등록</h1>
        <div class="head-actions">
          <a class="btn ghost" id="l-export">결과 CSV</a>
          <button class="btn ghost danger-text" id="l-cancel">대기·실패 건 계획 취소</button>
        </div></header>
      <div class="card run" id="l-run"></div>
      <div class="toolbar"><div class="filters">
        <select id="l-store" class="sel"><option value="">모든 스토어</option></select>
        <select id="l-plan" class="sel"><option value="">모든 계획</option></select>
        <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
          <input id="l-q" placeholder="등록 상품명·판매자코드"></div>
      </div></div>
      <div class="tiles" id="l-tiles"></div>
      <div class="card table-card">
        <table class="grid"><thead><tr><th class="w-thumb"></th><th>등록 상품명</th><th class="w-store">스토어</th>
          <th class="w-num">판매가</th><th class="w-status">상태</th></tr></thead><tbody id="l-rows"></tbody></table>
        <div class="pager" id="l-pager"></div>
      </div>
    </div>`;
    $("#l-store").innerHTML += App.stores.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
    const plans = await App.api("/api/plans");
    $("#l-plan").innerHTML += plans.map((p) => `<option value="${p.id}">${esc(p.title)} · ${num(p.total)}건</option>`).join("");
    $("#l-store").value = this.f.store_id || "";
    $("#l-plan").value = this.f.plan_id || "";
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
    $("#l-tiles").innerHTML = tilesHtml(LST_TILES, { ...this.counts, all: this.counts.all_ }, this.f.status);
    $("#l-rows").innerHTML = res.rows.length ? res.rows.map((l) => this.rowHtml(l)).join("")
      : `<tr class="empty-row"><td colspan="5">${this.counts.all_ ? "조건에 맞는 건이 없습니다."
        : '아직 등록 계획이 없습니다. <a href="#inventory">원본 상품</a>에서 상품을 고르고 <b>스토어에 올리기 계획</b>을 만드세요.'}</td></tr>`;
    App.pager($("#l-pager"), { page: this.page, size: this.size, total: res.total, onPage: (p) => { this.page = p; this.load(); } });
    $("#l-export").href = `/api/listings/export.csv?${new URLSearchParams(this.query())}`;
    if (!App.run?.running) this.renderIdle();
  },

  rowHtml(l) {
    const diff = l.source_price ? ((l.price - l.source_price) / l.source_price) * 100 : 0;
    let msg = "", cls = "";
    if (l.status === "fail") { msg = l.message; cls = "err"; }
    else if (l.status === "success") msg = `상품번호 ${l.channel_no}${l.seconds ? ` · ${l.seconds.toFixed(1)}초` : ""}`;
    else if (l.status === "running") msg = l.stage;
    return `<tr data-id="${l.id}">
      <td>${img(l.thumb)}</td>
      <td><div class="p-name">${esc(l.name)}</div><div class="p-sub"><span>원본: ${esc(l.source_name)}</span></div></td>
      <td>${esc(l.store_name)}</td>
      <td class="num">${num(l.price)}원<div class="p-sub r">${diff ? (diff > 0 ? "+" : "") + diff.toFixed(1) + "%" : "원본가"}</div></td>
      <td><span class="badge s-${l.status}">${STATUS[l.status]}</span>${msg ? `<div class="s-msg ${cls}" title="${esc(msg)}">${esc(msg)}</div>` : ""}</td></tr>`;
  },

  // ── 실행 패널

  renderIdle() {
    const box = $("#l-run");
    const n = (this.counts.pending || 0) + (this.counts.fail || 0);
    const scope = [this.f.store_id && $("#l-store").selectedOptions[0]?.text, this.f.plan_id && $("#l-plan").selectedOptions[0]?.text.split(" · ")[0]]
      .filter(Boolean).join(" · ");
    box.innerHTML = `<div class="run-idle">
        <div class="run-actions">
          <button class="btn primary big" id="l-start" ${n ? "" : "disabled"}>▶ 등록 시작 · ${num(n)}건</button>
          <button class="btn big" id="l-one" ${n ? "" : "disabled"}>1건만 시험</button>
        </div>
        <div class="run-est"><div>${scope ? `<b>${esc(scope)}</b>의 ` : "모든 스토어의 "}대기·실패 건을 등록합니다.</div><div id="l-est" class="muted small"></div></div>
      </div>`;
    $("#l-start").addEventListener("click", () => this.start());
    $("#l-one").addEventListener("click", () => this.start(1));
    if (!n) return;
    const key = JSON.stringify(this.query()) + n;
    if (key === this.estKey) { $("#l-est").innerHTML = this.estHtml || ""; return; }
    this.estKey = key;
    App.api("/api/run/estimate", { json: { ...this.query(), status: undefined } }).then((e) => {
      this.estHtml = `예상 <b>약 ${dur(e.seconds)}</b> · 스토어 ${e.stores}곳을 ${e.parallel}곳씩 나란히, 스토어마다 ${e.workers}건씩 동시에 · ${esc(e.basis)}`;
      const el = $("#l-est");
      if (el) el.innerHTML = this.estHtml;
    }).catch(() => {});
  },

  async start(limit) {
    const n = limit || (this.counts.pending || 0) + (this.counts.fail || 0);
    if (!limit && !confirm(`${num(n)}건을 스마트스토어에 등록합니다. 계속할까요?`)) return;
    const f = this.query();
    delete f.status;
    try {
      App.run = await App.api("/api/run", { json: { ...f, limit: limit || null } });
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

  bind() {
    $("#l-tiles").addEventListener("click", (e) => {
      const t = e.target.closest("[data-filter]");
      if (t) { this.f.status = t.dataset.filter; this.page = 0; this.load(); }
    });
    $("#l-store").addEventListener("change", (e) => { this.f.store_id = e.target.value; this.page = 0; this.load(); });
    $("#l-plan").addEventListener("change", (e) => { this.f.plan_id = e.target.value; this.page = 0; this.load(); });
    let timer;
    $("#l-q").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { this.f.q = e.target.value.trim(); this.page = 0; this.load(); }, 300);
    });
    $("#l-cancel").addEventListener("click", async () => {
      const f = this.query();
      delete f.status;
      delete f.q;
      const scope = f.store_id || f.plan_id ? "지금 고른 스토어·계획의" : "모든";
      if (!confirm(`${scope} 등록 대기·실패 건의 계획을 취소할까요?\n쓰던 상품명은 다시 후보로 돌아갑니다. 등록 완료된 건은 그대로입니다.`)) return;
      try {
        const r = await App.api("/api/listings/cancel", { json: f });
        App.toast(`${num(r.cancelled)}건을 취소했습니다.`);
        this.load();
      } catch (e) { App.toast(e.message, true); }
    });
    $("#l-rows").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (tr) this.openListing(+tr.dataset.id);
    });
  },

  async openListing(id) {
    let l;
    try { l = await App.api(`/api/listings/${id}`); } catch (e) { return App.toast(e.message, true); }
    const url = l.store_url && l.channel_no ? `${l.store_url.replace(/\/$/, "")}/products/${l.channel_no}` : "";
    App.openDrawer({
      title: l.name, sub: `${l.store_name} · ${STATUS[l.status]}`,
      tabs: [
        { key: "info", label: "정보", render: (b) => {
          b.innerHTML = (l.status === "fail" ? `<div class="notice err"><b>등록 실패</b><br>${esc(l.message)}</div>` : "")
            + (l.status === "success" ? `<div class="notice ok"><b>등록 완료</b> · 상품번호 ${esc(l.channel_no)}<br>
                ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">스토어에서 보기</a> · ` : ""}
                <a href="https://sell.smartstore.naver.com/#/products/edit/${esc(l.origin_no)}" target="_blank" rel="noopener">스마트스토어센터에서 수정</a></div>` : "")
            + `<div class="gallery">${img(l.thumb, "g-main")}</div>
              <dl class="kv"><dt>스토어</dt><dd>${esc(l.store_name)}</dd><dt>등록 상품명</dt><dd>${esc(l.name)}</dd>
              <dt>원본 상품명</dt><dd>${esc(l.source_name)}</dd><dt>판매가</dt><dd>${num(l.price)}원 <span class="muted">(원본가 ${num(l.source_price)}원)</span></dd></dl>`;
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
        ? `<span class="muted"></span><button class="btn primary" id="d-run">이 건만 등록</button>` : "",
    });
    $("#d-run")?.addEventListener("click", async () => {
      try { App.run = await App.api("/api/run", { json: { ids: [id] } }); App.closeDrawer(); this.renderRun(App.run); }
      catch (e) { App.toast(e.message, true); }
    });
  },
});
