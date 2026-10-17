/* 원본 상품 (인벤토리): 불러오기, 거르기, 고르기 → 상품명 만들기 / 등록 계획 */
"use strict";

const INV_TILES = [
  { key: "all", label: "전체", dot: "var(--text-2)", count: "all_" },
  { key: "valid", label: "등록 가능", dot: "var(--idle)" },
  { key: "unlisted", label: "아직 어디에도 안 올림", dot: "var(--info)" },
  { key: "names_short", label: "이름 후보 3개 미만", dot: "var(--warn)" },
  { key: "warn", label: "경고 있음", dot: "var(--warn)" },
  { key: "invalid", label: "오류 (고쳐야 함)", dot: "var(--err)" },
];

App.page("inventory", {
  size: 100,

  async mount(el, params) {
    this.f = { status: params.status || "all", q: "", store_missing: "", ...params };
    this.page = 0;
    this.sel = new Set();
    this.selAll = false;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>원본 상품</h1>
        <div class="head-actions">
          <button class="btn ghost" id="i-revalidate" title="설정이나 카테고리가 바뀐 뒤 전체를 다시 검사">다시 검사</button>
          <label class="btn"><input type="file" id="i-names-file" accept=".xlsx,.xlsm,.csv" hidden>상품명 파일 가져오기</label>
          <label class="btn primary"><input type="file" id="i-file" accept=".xlsx,.xlsm,.csv" hidden>
            <svg viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M5 20h14"/></svg>원본 엑셀 불러오기</label>
        </div></header>
      <div class="tiles" id="i-tiles"></div>
      <div class="toolbar">
        <div class="filters">
          <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
            <input id="i-q" placeholder="상품명·판매자코드·카테고리"></div>
          <select id="i-missing" class="sel"><option value="">스토어 조건 없음</option></select>
        </div>
        <div class="muted small" id="i-info"></div>
      </div>
      <div class="actionbar" id="i-actions"></div>
      <div class="card table-card">
        <table class="grid"><thead><tr>
          <th class="w-check"><input type="checkbox" id="i-check-all" aria-label="이 쪽 모두 선택"></th>
          <th class="w-thumb"></th><th>원본 상품</th><th class="w-cat">카테고리</th>
          <th class="w-num">원본가</th><th class="w-small" title="아직 안 쓴 상품명 후보">이름 후보</th>
          <th class="w-small" title="등록 완료 / 계획된 스토어">스토어</th><th class="w-status">상태</th>
        </tr></thead><tbody id="i-rows"></tbody></table>
        <div class="pager" id="i-pager"></div>
      </div>
    </div>`;
    $("#i-missing").innerHTML += App.stores.map((s) =>
      `<option value="${s.id}">${esc(s.name)}에 없는 것만</option>`).join("");
    $("#i-missing").value = this.f.store_missing || "";
    this.bind();
    this.onDone = (t) => { if (["import", "names", "plan", "revalidate"].includes(t.kind)) this.load(); };
    App.on("task-done", this.onDone);
    await this.load();
  },
  unmount() { App.off("task-done", this.onDone); },

  query() {
    const f = { ...this.f };
    Object.keys(f).forEach((k) => (f[k] === "" || f[k] == null) && delete f[k]);
    if (f.status === "all") delete f.status;
    return f;
  },

  async load() {
    const qs = new URLSearchParams({ ...this.query(), page: this.page, size: this.size });
    const res = await App.api(`/api/sources?${qs}`);
    this.rows = res.rows;
    this.total = res.total;
    const c = res.counts || {};
    $("#i-tiles").innerHTML = tilesHtml(INV_TILES.map((t) => ({ ...t })), { ...c, all: c.all_ }, this.f.status);
    $("#i-rows").innerHTML = res.rows.length ? res.rows.map((p) => this.rowHtml(p)).join("")
      : `<tr class="empty-row"><td colspan="8">${c.all_ ? "조건에 맞는 상품이 없습니다." :
        "아직 원본 상품이 없습니다. 오른쪽 위 <b>원본 엑셀 불러오기</b>를 누르거나 엑셀을 끌어다 놓으세요."}</td></tr>`;
    $("#i-check-all").checked = res.rows.length > 0 && res.rows.every((p) => this.sel.has(p.id));
    App.pager($("#i-pager"), { page: this.page, size: this.size, total: res.total, onPage: (p) => { this.page = p; this.load(); } });
    this.renderActions();
  },

  rowHtml(p) {
    const cat = (p.category || "").split(">");
    let badge, msg = "";
    if (!p.valid) { badge = `<span class="badge s-fail">오류</span>`; msg = p.errors[0] || ""; }
    else if (p.n_success) badge = `<span class="badge s-success">${p.n_success}곳 등록</span>`;
    else if (p.n_listings) badge = `<span class="badge s-running">${p.n_listings}곳 계획</span>`;
    else badge = `<span class="badge s-planned">등록 가능</span>`;
    const flags = [
      p.warnings.length ? `<span class="flag warn" title="${esc(p.warnings.join("\n"))}">경고 ${p.warnings.length}</span>` : "",
      p.has_video ? `<span class="flag video">동영상</span>` : "",
    ].join("");
    return `<tr data-id="${p.id}" class="${this.selAll || this.sel.has(p.id) ? "sel" : ""}">
      <td class="w-check" data-stop><input type="checkbox" ${this.selAll || this.sel.has(p.id) ? "checked" : ""} ${this.selAll ? "disabled" : ""}></td>
      <td>${img(p.thumb)}</td>
      <td><div class="p-name">${esc(p.name)}</div><div class="p-sub"><span>${esc(p.source_key)}</span>${flags}</div></td>
      <td class="cat-td"><div class="cat">${cat.length > 2 ? `<div class="cat-top">${esc(cat.slice(0, -2).join(" › "))}</div>` : ""}${esc(cat.slice(-2).join(" › "))}</div></td>
      <td class="num">${num(p.price)}원</td>
      <td class="num small-td ${p.valid && p.n_free_names < 3 ? "c-warn" : ""}">${num(p.n_free_names)}</td>
      <td class="num small-td">${p.n_success}/${p.n_listings}</td>
      <td>${badge}${msg ? `<div class="s-msg err" title="${esc(msg)}">${esc(msg)}</div>` : ""}</td></tr>`;
  },

  renderActions() {
    const n = this.selAll ? this.total : this.sel.size;
    const target = this.selAll ? `조건에 맞는 <b>${num(this.total)}개 전체</b>` : n ? `<b>${num(n)}개</b> 선택` : "";
    $("#i-actions").innerHTML = `<div class="ab-left">
        ${target ? `<span>${target}</span><button class="link-btn" id="i-clear">선택 해제</button>`
          : `<span class="muted">상품을 고르거나</span>`}
        ${!this.selAll && this.total ? `<button class="link-btn" id="i-all">조건에 맞는 ${num(this.total)}개 모두 고르기</button>` : ""}
      </div>
      <div class="ab-right">
        <button class="btn" id="i-names" ${n ? "" : "disabled"}>상품명 후보 만들기…</button>
        <button class="btn primary" id="i-plan" ${n ? "" : "disabled"}>스토어에 올리기 계획…</button>
      </div>`;
    $("#i-info").textContent = this.total ? `${num(this.total)}개` : "";
  },

  target() {
    return this.selAll ? this.query() : { ids: [...this.sel] };
  },

  targetCount() { return this.selAll ? this.total : this.sel.size; },

  bind() {
    $("#i-file").addEventListener("change", (e) => { if (e.target.files[0]) App.upload("/api/sources/import", e.target.files[0]); e.target.value = ""; });
    $("#i-names-file").addEventListener("change", (e) => { if (e.target.files[0]) App.upload("/api/names/import", e.target.files[0]); e.target.value = ""; });
    $("#i-revalidate").addEventListener("click", () => App.startTask(App.api("/api/sources/revalidate", { json: {} })));
    $("#i-tiles").addEventListener("click", (e) => {
      const t = e.target.closest("[data-filter]");
      if (t) { this.f.status = t.dataset.filter; this.page = 0; this.clearSel(); this.load(); }
    });
    let timer;
    $("#i-q").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { this.f.q = e.target.value.trim(); this.page = 0; this.clearSel(); this.load(); }, 300);
    });
    $("#i-missing").addEventListener("change", (e) => { this.f.store_missing = e.target.value; this.page = 0; this.clearSel(); this.load(); });
    $("#i-check-all").addEventListener("change", (e) => {
      this.selAll = false;
      this.rows.forEach((p) => (e.target.checked ? this.sel.add(p.id) : this.sel.delete(p.id)));
      this.load();
    });
    $("#i-rows").addEventListener("click", (e) => {
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
      this.openSource(id);
    });
    $("#i-actions").addEventListener("click", (e) => {
      const id = e.target.closest("button")?.id;
      if (id === "i-clear") { this.clearSel(); this.load(); }
      if (id === "i-all") { this.selAll = true; this.sel.clear(); this.load(); }
      if (id === "i-names") this.namesModal();
      if (id === "i-plan") this.planModal();
    });
  },

  clearSel() { this.sel.clear(); this.selAll = false; },

  // ── 상품명 후보 만들기

  namesModal() {
    const s = App.state.settings;
    const n = this.targetCount();
    const PRICE = { "claude-opus-5-5": [4, 20], "claude-sonnet-5-5": [2, 10], "claude-haiku-5-5": [0.1, 0.5], "claude-fable-5-1": [10, 50] };
    App.openModal({
      title: `상품명 후보 만들기 · 상품 ${num(n)}개`,
      body: `<div class="radio-cards">
          <label><input type="radio" name="method" value="recombine" checked>
            <div><b>재조합</b><span class="muted small">원본 상품명의 단어를 고르고 순서를 바꿔 만듭니다. 무료·즉시.
            단어가 적은 상품은 다 못 채울 수 있습니다.</span></div></label>
          <label><input type="radio" name="method" value="ai">
            <div><b>AI로 짓기</b><span class="muted small">Claude(${esc(s.ai_model)})가 원본을 보고 새로 짓습니다. 유료.
            ${s.has_anthropic_api_key || App.state.fake_api ? "" : '<br><span class="c-err">설정에서 API 키를 먼저 넣어야 합니다.</span>'}</span></div></label>
        </div>
        <label class="field" id="per-label">원본마다 안 쓴 후보가 몇 개가 되도록 채울까요?
          <input type="number" id="per" min="1" max="100" value="5"></label>
        <p class="muted small" id="cost"></p>
        <p class="muted small">모든 이름은 33개 스토어 전체에서 겹치지 않게 저장됩니다. 이미 있는 이름과 같으면 버립니다.</p>`,
      buttons: [{ label: "취소" }, {
        label: "만들기", primary: true, onClick: async (b) => {
          const method = $("input[name=method]:checked", b).value;
          const r = await App.startTask(App.api("/api/names/generate", {
            json: { ...this.target(), method, per_source: +$("#per", b).value },
          }));
          return !!r;
        },
      }],
    });
    const upd = () => {
      const ai = $("input[name=method]:checked").value === "ai";
      $("#per-label").firstChild.textContent = ai ? "원본마다 새 이름을 몇 개 지을까요? " : "원본마다 안 쓴 후보가 몇 개가 되도록 채울까요? ";
      const per = +$("#per").value || 1;
      const [pin, pout] = PRICE[s.ai_model] || [4, 20];
      const tokIn = n * 90 + Math.ceil(n / (s.ai_products_per_call || 20)) * 400;
      const tokOut = n * per * 35 * 1.3;
      const usd = (tokIn * pin + tokOut * pout) / 1e6;
      $("#cost").innerHTML = ai ? `예상 비용 약 <b>$${usd < 1 ? usd.toFixed(2) : num(Math.round(usd))}</b> (어림값, 실제와 다를 수 있음) · 모델은 설정에서 바꿀 수 있습니다.` : "";
    };
    $$("#m-body input").forEach((x) => x.addEventListener("input", upd));
    upd();
  },

  // ── 등록 계획

  async planModal() {
    const stores = await App.loadStores();
    const n = this.targetCount();
    App.openModal({
      title: `스토어에 올리기 계획 · 원본 ${num(n)}개`,
      wide: true,
      body: `<div class="plan">
        <div>
          <div class="sec-head"><h3>올릴 스토어</h3>
            <span><button class="link-btn" id="p-all">모두</button> · <button class="link-btn" id="p-none">해제</button></span></div>
          <div class="store-pick">${stores.filter((s) => s.enabled).map((s) => `
            <label class="sp-row"><input type="checkbox" value="${s.id}" ${s.free > 0 ? "checked" : ""}>
              <span class="sp-name">${esc(s.name)}${s.has_keys ? "" : ' <span class="flag warn">키 없음</span>'}</span>
              ${usageBar(s.used, s.capacity)}<span class="sp-free ${s.free < 100 ? "c-err" : "muted"}">남은 ${num(s.free)}</span></label>`).join("")
            || '<p class="muted">스토어가 없습니다. 스토어 화면에서 먼저 추가하세요.</p>'}</div>
        </div>
        <div class="plan-opts">
          <h3>나누는 방법</h3>
          <div class="radio-cards">
            <label><input type="radio" name="mode" value="all" checked><div><b>고른 스토어 모두에</b>
              <span class="muted small">원본 하나를 고른 스토어마다 하나씩 올립니다. 이미 올린 스토어는 건너뜁니다.</span></div></label>
            <label><input type="radio" name="mode" value="spread"><div><b>상품마다 <input type="number" id="p-per" min="1" value="1" class="inline-num">개 스토어에 골고루</b>
              <span class="muted small">남은 자리가 많은 스토어부터 나눠 담습니다. 1이면 원본마다 한 스토어에만.</span></div></label>
          </div>
          <label class="field">계획 이름 <span class="muted">(나중에 등록 화면에서 이 이름으로 거를 수 있음)</span>
            <input id="p-title" placeholder="예: 10월 3주차 공구류"></label>
          <div class="plan-sum" id="p-sum"></div>
          <p class="muted small">· 상품명: 원본마다 안 쓴 후보에서 하나씩 씁니다 (가져옴 → AI → 재조합 순). 모자라면 ${App.state.settings.auto_recombine ? "재조합으로 자동으로 채웁니다" : "건너뜁니다"}.<br>
            · 가격: 스토어마다 원본가 ±${App.state.settings.price_jitter_pct}% 안에서 정하고 ${num(App.state.settings.price_round)}원 단위로 맞춥니다.<br>
            · 스토어 한도를 넘는 건은 만들지 않습니다.</p>
        </div></div>`,
      buttons: [{ label: "취소" }, {
        label: "계획 만들기", primary: true, onClick: async (b) => {
          const store_ids = $$(".store-pick input:checked", b).map((x) => +x.value);
          if (!store_ids.length) { App.toast("스토어를 하나 이상 고르세요.", true); return false; }
          const r = await App.startTask(App.api("/api/plans", {
            json: { ...this.target(), store_ids, mode: $("input[name=mode]:checked", b).value,
                    per_product: +$("#p-per", b).value || 1, title: $("#p-title", b).value.trim() },
          }));
          if (r) { this.clearSel(); }
          return !!r;
        },
      }],
    });
    const sum = () => {
      const picked = $$(".store-pick input:checked");
      const free = picked.reduce((a, x) => a + (stores.find((s) => s.id === +x.value)?.free || 0), 0);
      const mode = $("input[name=mode]:checked").value;
      const per = +$("#p-per").value || 1;
      const want = mode === "all" ? n * picked.length : n * Math.min(per, picked.length);
      $("#p-sum").innerHTML = `최대 <b>${num(want)}건</b> 계획 · 고른 스토어 ${picked.length}곳의 남은 자리 합계 ${num(free)}`
        + (want > free ? ` <span class="c-err">(자리가 모자라 일부만 계획됩니다)</span>` : "");
    };
    $("#p-all").addEventListener("click", () => { $$(".store-pick input").forEach((x) => (x.checked = true)); sum(); });
    $("#p-none").addEventListener("click", () => { $$(".store-pick input").forEach((x) => (x.checked = false)); sum(); });
    $$("#m-body input").forEach((x) => x.addEventListener("input", sum));
    $("#p-per").addEventListener("focus", () => { $("input[name=mode][value=spread]").checked = true; sum(); });
    sum();
  },

  // ── 원본 상세

  async openSource(id, tab) {
    let d;
    try { d = await App.api(`/api/sources/${id}`); } catch (e) { return App.toast(e.message, true); }
    const self = this;
    App.openDrawer({
      title: d.name, sub: `${d.source_key} · 원본가 ${num(d.price)}원`, tab,
      tabs: [
        { key: "info", label: "정보", render: (b) => self.renderInfo(b, d) },
        { key: "names", label: `상품명 후보 ${d.names.length}`, render: (b) => self.renderNames(b, d) },
        { key: "stores", label: `스토어 ${d.listings.length}`, render: (b) => self.renderListings(b, d) },
        { key: "detail", label: "상세페이지", render: (b) => {
          b.innerHTML = `<iframe class="preview" sandbox referrerpolicy="no-referrer"></iframe>`;
          $("iframe", b).srcdoc = `<meta name="referrer" content="no-referrer"><style>body{margin:0}img{max-width:100%}</style>` + d.detail_html;
        } },
      ],
    });
  },

  renderInfo(b, d) {
    const notes = [];
    if (d.errors.length) notes.push(`<div class="notice err"><b>고쳐야 등록할 수 있어요</b><ul>${d.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>`);
    if (d.warnings.length) notes.push(`<div class="notice warn"><b>확인해 보세요</b><ul>${d.warnings.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>`);
    const kv = [["카테고리", esc(d.category)], ...Object.entries(d.fields).map(([k, v]) => [esc(k), esc(v)]),
      ["이미지", `대표·추가 ${Math.min(10, d.thumbnails.length)}장 · 상세 ${d.detail_images.length}장`]];
    b.innerHTML = notes.join("") +
      (d.thumbnails.length ? `<div class="gallery">${d.thumbnails.map((u, i) => img(u, i === 0 ? "g-main" : "")).join("")}</div>` : "") +
      `<dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>` +
      (d.options.length ? `<div><h3 class="sec-title">옵션 · ${esc(d.option_group)} (${d.options.length}개)</h3>
        <table class="opt-table"><tr><th>옵션</th><th class="r">추가금</th><th class="r">재고</th></tr>
        ${d.options.map((o) => `<tr><td>${esc(o.optionName1)}${o.optionName2 ? " / " + esc(o.optionName2) : ""}</td>
          <td class="r">${o.price ? (o.price > 0 ? "+" : "") + num(o.price) + "원" : "-"}</td><td class="r">${num(o.stockQuantity)}</td></tr>`).join("")}
        </table></div>` : "") +
      (d.tags_list.length ? `<div><h3 class="sec-title">엑셀 태그</h3><div class="tags">${d.tags_list.map((t) => `<span>${esc(t)}</span>`).join("")}</div></div>` : "");
  },

  renderNames(b, d) {
    const free = d.names.filter((n) => !n.listing_id && (n.origin !== "original" || App.state.settings.use_original_name)).length;
    b.innerHTML = `<p class="muted small" style="margin:0">안 쓴 후보 <b>${free}개</b>. 등록 계획을 만들 때 스토어마다 하나씩 씁니다.
      모든 이름은 33개 스토어 전체에서 겹치지 않습니다.</p>
      <div class="add-name"><input id="n-new" placeholder="직접 이름 추가"><button class="btn" id="n-add">추가</button></div>
      <ul class="name-list">${d.names.map((n) => `<li>
        <span class="org org-${n.origin}">${ORIGIN[n.origin] || n.origin}</span>
        <span class="nm">${esc(n.name)}</span>
        ${n.listing_id ? `<span class="muted small">${esc(n.store_name)} · ${STATUS[n.status] || ""}</span>`
          : n.origin === "original" && !App.state.settings.use_original_name ? `<span class="muted small">원본 (사용 안 함)</span>`
          : `<button class="link-btn danger-text" data-del="${n.id}">지우기</button>`}</li>`).join("")}</ul>`;
    const reload = async () => { const nd = await App.api(`/api/sources/${d.id}`); Object.assign(d, nd); this.renderNames(b, d); this.load(); };
    $("#n-add", b).addEventListener("click", async () => {
      try { await App.api("/api/names", { json: { source_id: d.id, name: $("#n-new", b).value } }); await reload(); }
      catch (e) { App.toast(e.message, true); }
    });
    $(".name-list", b).addEventListener("click", async (e) => {
      const id = e.target.dataset.del;
      if (!id) return;
      try { await App.api(`/api/names/${id}`, { method: "DELETE" }); await reload(); } catch (err) { App.toast(err.message, true); }
    });
  },

  renderListings(b, d) {
    b.innerHTML = d.listings.length ? `<table class="opt-table"><tr><th>스토어</th><th>등록 상품명</th><th class="r">가격</th><th>상태</th></tr>
      ${d.listings.map((l) => `<tr><td>${esc(l.store_name)}</td><td>${esc(l.name)}</td><td class="r">${num(l.price)}</td>
        <td><span class="badge s-${l.status}">${STATUS[l.status]}</span>${l.status === "success" && l.store_url && l.channel_no
          ? ` <a href="${esc(l.store_url.replace(/\/$/, ""))}/products/${esc(l.channel_no)}" target="_blank" rel="noopener">보기</a>` : ""}</td></tr>`).join("")}</table>`
      : `<p class="muted">아직 어느 스토어에도 계획되지 않았습니다.</p>`;
  },
});
