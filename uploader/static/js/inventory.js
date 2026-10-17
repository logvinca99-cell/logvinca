/* 원본 상품 (인벤토리): 불러오기, 거르기, 고르기 → 상품명 만들기 / 등록 계획 */
"use strict";

const INV_TILES = [
  { key: "all", label: "전체", dot: "var(--text-2)", count: "all_" },
  { key: "unlisted", label: "아직 0곳", dot: "var(--info)" },
  { key: "partial", label: "1~2곳에 있음", dot: "var(--ok)" },
  { key: "full", label: "3곳 다 참", dot: "var(--dup)" },
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
          <select id="i-review" class="sel"><option value="">검수 전체</option><option value="wait">검수 대기</option><option value="pass">검수 통과</option><option value="reject">검수 제외</option></select>
        </div>
        <div class="muted small" id="i-info"></div>
      </div>
      <div class="actionbar" id="i-actions"></div>
      <div class="card table-card">
        <table class="grid"><thead><tr>
          <th class="w-check"><input type="checkbox" id="i-check-all" aria-label="이 쪽 모두 선택"></th>
          <th class="w-thumb"></th><th>원본 상품</th><th class="w-cat">카테고리</th>
          <th class="w-num">원본가</th><th class="w-small" title="아직 안 쓴 상품명 후보">이름 후보</th>
          <th class="w-copies" title="이 원본을 복사한 스토어. 원본당 최대 칸 수까지. 복사본은 원본 바로 아래 줄에 보입니다">복사</th>
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
    const mx = App.state.settings.max_copies || 3;
    let slots;
    if (!p.valid) slots = `<span class="badge s-fail">오류</span><div class="s-msg err" title="${esc(p.errors[0] || "")}">${esc(p.errors[0] || "")}</div>`;
    else {
      const cells = p.copies.map((c) => `<span class="slot s-${c.status === "planned" && c.op !== "create" ? c.op : c.status}"
        title="${esc(c.store)} · ${esc(statusLabel(c.status, c.op))} · ${c.round}회차">${esc(c.code)}</span>`);
      for (let i = p.copies.length; i < mx; i++) cells.push(`<span class="slot empty" title="빈 칸">·</span>`);
      slots = `<div class="slots">${cells.join("")}</div>`;
    }
    const flags = [
      p.review === "reject" ? `<span class="flag bad" title="눈검수에서 제외 · 등록되지 않음">검수 제외</span>`
        : p.review !== "pass" ? `<span class="flag rv-flag-wait" title="눈검수 전 · 통과해야 등록됨">검수 대기</span>` : "",
      p.warnings.length ? `<span class="flag warn" title="${esc(p.warnings.join("\n"))}">경고 ${p.warnings.length}</span>` : "",
      p.has_video ? `<span class="flag video">동영상</span>` : "",
    ].join("");
    return `<tr data-id="${p.id}" class="${this.selAll || this.sel.has(p.id) ? "sel" : ""}">
      <td class="w-check" data-stop><input type="checkbox" ${this.selAll || this.sel.has(p.id) ? "checked" : ""} ${this.selAll ? "disabled" : ""}></td>
      <td>${img(p.thumb)}</td>
      <td><div class="p-name">${esc(p.name)}</div><div class="p-sub"><span>원본 #${p.id}</span>${p.seller_code ? `<span>${esc(p.seller_code)}</span>` : ""}${flags}</div></td>
      <td class="cat-td"><div class="cat">${cat.length > 2 ? `<div class="cat-top">${esc(cat.slice(0, -2).join(" › "))}</div>` : ""}${esc(cat.slice(-2).join(" › "))}</div></td>
      <td class="num">${num(p.price)}원</td>
      <td class="num small-td ${p.valid && p.n_free_names < 3 ? "c-warn" : ""}">${num(p.n_free_names)}</td>
      <td>${slots}${p.deleted_copies ? `<div class="p-sub">내림 ${p.deleted_copies}</div>` : ""}</td></tr>`
      + p.copies.map((c) => this.copyRowHtml(c, p)).join("");
  },

  /* 원본 바로 아래에 붙는 복사본 한 줄: 어느 스토어에, 무슨 이름·가격으로, 지금 상태, 올린 날, 판매 */
  copyRowHtml(c, p) {
    const diff = p.price ? ((c.price - p.price) / p.price) * 100 : 0;
    const link = c.store_url && c.channel_no && c.status !== "deleted"
      ? ` · <a href="${esc(c.store_url.replace(/\/$/, ""))}/products/${esc(c.channel_no)}" target="_blank" rel="noopener" data-stop>스토어에서 보기</a>` : "";
    const msg = c.status === "fail" || (c.status === "success" && c.message) ? c.message : "";
    return `<tr class="copy-row" data-copy="${c.id}">
      <td></td><td class="copy-arrow">↳</td>
      <td colspan="2"><div class="copy-name"><span class="code">${esc(c.code)}</span> <span class="muted">${esc(c.store)}</span> ${esc(c.name)}</div>
        <div class="p-sub">${esc(c.seller_code || "관리코드는 등록할 때 붙음")} · ${c.round}회차${c.registered_at && c.channel_no ? ` · ${ymd(c.registered_at)} 올림 (${age(c.registered_at)})` : ""}${link}</div></td>
      <td class="num">${num(c.price)}원<div class="p-sub r">${diff ? (diff > 0 ? "+" : "") + diff.toFixed(1) + "%" : "원본가"}</div></td>
      <td class="num">${lockFlag(c)}${c.sold_count && !c.locked ? salesFlag(c) : ""}</td>
      <td>${statusBadge(c.status, c.op)}${msg ? `<div class="s-msg ${c.status === "fail" ? "err" : ""}" title="${esc(msg)}">${esc(msg)}</div>` : ""}</td></tr>`;
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
        <button class="btn" id="i-kw" ${n ? "" : "disabled"} title="고른 원본의 핵심 키워드와 다른 판매자들이 쓴 단어를 네이버에서 모읍니다">네이버 키워드 모으기</button>
        <button class="btn" id="i-names" ${n ? "" : "disabled"}>상품명 후보 만들기…</button>
        <button class="btn primary" id="i-plan" ${n ? "" : "disabled"}>다른 스토어로 복사…</button>
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
    $("#i-review").value = this.f.review || "";
    $("#i-review").addEventListener("change", (e) => { this.f.review = e.target.value; this.page = 0; this.clearSel(); this.load(); });
    $("#i-check-all").addEventListener("change", (e) => {
      this.selAll = false;
      this.rows.forEach((p) => (e.target.checked ? this.sel.add(p.id) : this.sel.delete(p.id)));
      this.load();
    });
    $("#i-rows").addEventListener("click", (e) => {
      const cr = e.target.closest("tr[data-copy]");
      if (cr) {
        if (!e.target.closest("a")) App.pages.listings.openListing(+cr.dataset.copy);
        return;
      }
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
      if (id === "i-kw") App.startTask(App.api("/api/keywords/collect", { json: { filter: this.target() } }));
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
      title: `다른 스토어로 복사 · 원본 ${num(n)}개`,
      wide: true,
      body: `<div class="plan">
        <div>
          <div class="sec-head"><h3>복사할 스토어</h3>
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
            <label><input type="radio" name="mode" value="spread" checked><div><b>원본마다 <input type="number" id="p-per" min="1" max="${App.state.settings.max_copies}" value="1" class="inline-num">곳이 되도록 골고루</b>
              <span class="muted small">고른 스토어 중 남은 자리가 많은 곳부터 나눠 담습니다. 이미 고른 스토어에 있으면 그만큼 덜 올립니다.</span></div></label>
            <label><input type="radio" name="mode" value="all"><div><b>빈 칸을 모두 채우기</b>
              <span class="muted small">원본마다 남은 칸(최대 ${App.state.settings.max_copies}곳)을 고른 스토어로 채웁니다.</span></div></label>
          </div>
          <label class="field">계획 이름 <span class="muted">(나중에 등록 화면에서 이 이름으로 거를 수 있음)</span>
            <input id="p-title" placeholder="예: 10월 3주차 공구류"></label>
          <div class="plan-sum" id="p-sum"></div>
          <p class="muted small">· 원본 하나는 최대 <b>${App.state.settings.max_copies}곳</b>까지만 올라갑니다 (내린 스토어는 세지 않음).<br>
            · 전에 내렸던 스토어에 다시 계획하면 같은 이름·가격으로 다음 회차가 됩니다.<br>
            · 상품명: 원본마다 안 쓴 후보에서 하나씩 씁니다 (가져옴 → AI → 재조합 순). 모자라면 ${App.state.settings.auto_recombine ? "재조합으로 자동으로 채웁니다" : "건너뜁니다"}.<br>
            · 가격: 스토어마다 원본가 ±${App.state.settings.price_jitter_pct}% 안에서 정하고 ${num(App.state.settings.price_round)}원 단위로 맞춥니다.<br>
            · 스토어 한도를 넘는 건은 만들지 않습니다.</p>
        </div></div>`,
      buttons: [{ label: "취소" }, {
        label: "복사 계획 만들기", primary: true, onClick: async (b) => {
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
      const mx = App.state.settings.max_copies || 3;
      const want = n * Math.min(mode === "all" ? mx : Math.min(per, mx), picked.length);
      $("#p-sum").innerHTML = `최대 <b>${num(want)}건</b> 계획 · 고른 스토어 ${picked.length}곳의 남은 자리 합계 ${num(free)}`
        + (want > free ? ` <span class="c-err">(자리가 모자라 일부만 계획됩니다)</span>` : "");
    };
    $("#p-all").addEventListener("click", () => { $$(".store-pick input").forEach((x) => (x.checked = true)); sum(); });
    $("#p-none").addEventListener("click", () => { $$(".store-pick input").forEach((x) => (x.checked = false)); sum(); });
    $$("#m-body input").forEach((x) => x.addEventListener("input", sum));
    $("#p-per").addEventListener("input", (e) => { if (+e.target.value > (App.state.settings.max_copies || 3)) e.target.value = App.state.settings.max_copies; });
    sum();
  },

  // ── 원본 상세

  async openSource(id, tab) {
    let d;
    try { d = await App.api(`/api/sources/${id}`); } catch (e) { return App.toast(e.message, true); }
    const self = this;
    App.openDrawer({
      title: d.name, sub: `원본 #${d.id}${d.seller_code ? " · " + d.seller_code : ""} · 원본가 ${num(d.price)}원`, tab,
      tabs: [
        { key: "info", label: "정보", render: (b) => self.renderInfo(b, d) },
        { key: "names", label: `상품명 후보 ${d.names.length}`, render: (b) => self.renderNames(b, d) },
        { key: "kw", label: `키워드${d.kw.core ? " · " + d.kw.core : ""}`, render: (b) => self.renderKw(b, d) },
        { key: "stores", label: `스토어 ${d.listings.filter((l) => l.status !== "deleted").length}/${d.max_copies}`, render: (b) => self.renderListings(b, d) },
        { key: "detail", label: "상세페이지", render: (b) => {
          b.innerHTML = `<iframe class="preview" sandbox referrerpolicy="no-referrer"></iframe>`;
          $("iframe", b).srcdoc = `<meta name="referrer" content="no-referrer"><style>body{margin:0}img{max-width:100%}</style>` + d.detail_html;
        } },
      ],
    });
  },

  renderInfo(b, d) {
    const notes = [];
    const RV = { wait: "검수 대기 — 눈검수를 통과해야 등록됩니다", pass: "검수 통과", reject: "검수 제외 — 등록되지 않습니다" };
    notes.push(`<div class="notice ${d.review === "reject" ? "err" : d.review === "pass" ? "ok" : "warn"} lock-box"><div><b>${RV[d.review] || RV.wait}</b>${d.reviewed_at ? ` <span class="muted small">· ${ymd(d.reviewed_at)}</span>` : ""}</div>
      <div><button class="btn" data-rv="pass" ${d.review === "pass" ? "disabled" : ""}>통과로</button> <button class="btn" data-rv="reject" ${d.review === "reject" ? "disabled" : ""}>제외로</button></div></div>`);
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
    $$("[data-rv]", b).forEach((btn) => btn.addEventListener("click", async () => {
      const rej = btn.dataset.rv === "reject";
      if (rej && !confirm("이 원본을 제외로 바꿀까요? 이미 판매 중인 복사본은 눈검수 화면의 '제외된 판매 중 상품 내리기'로 내릴 수 있습니다.")) return;
      try {
        await App.api("/api/review/set", { json: { ids: [d.id], rejected: rej ? [d.id] : [] } });
        const nd = await App.api(`/api/sources/${d.id}`); Object.assign(d, nd); this.renderInfo(b, d); this.load();
      } catch (e) { App.toast(e.message, true); }
    }));
  },

  renderKw(b, d) {
    const k = d.kw;
    const used = k.words.filter((w) => w.used);
    b.innerHTML = `<div class="kw-src">
      <h3 class="sec-title">핵심 키워드</h3>
      <div class="core-edit"><input id="core-in" value="${esc(k.core)}" placeholder="예: 책상">
        <button class="btn" id="core-save">저장</button>
        ${k.manual ? `<button class="link-btn" id="core-auto">자동으로 되돌리기</button>` : `<span class="muted small">${k.collected_at ? "네이버 검색으로 정함" : "아직 안 모음 → 앞 단어로 대충 정함"}</span>`}</div>
      <p class="muted small">재조합 때 이 단어의 유의어를 가장 먼저 넣고, 4번째 이후에 있어도 빼지 않습니다.</p>
      <h3 class="sec-title">다른 판매자들이 쓴 단어 ${k.collected_at ? `<span class="muted small">· ${ymd(k.collected_at)} 모음</span>` : ""}
        <button class="link-btn" id="kw-one">${k.collected_at ? "다시 모으기" : "지금 모으기"}</button></h3>
      ${k.words.length ? `<p class="muted small">재조합에 쓰는 단어 ${used.length}개 (초록). 회색은 쓰지 않는 단어 — 이유에 마우스를 올리세요.</p>
        <div class="kw-chips">${k.words.map((w) => `<span class="kw-chip ${w.used ? "used" : "off"}" title="${esc(w.used ? `판매자 ${w.malls}곳` : w.why)}">${esc(w.word)}${w.volume != null ? `<small>${num(w.volume)}</small>` : ""}${w.used ? "" : `<small>${esc(w.why)}</small>`}</span>`).join("")}</div>`
        : `<p class="muted small">모은 단어가 없습니다.</p>`}
    </div>`;
    const reload = async () => { const nd = await App.api(`/api/sources/${d.id}`); Object.assign(d, nd); this.renderKw(b, d); };
    const save = async (core) => {
      try { await App.api(`/api/sources/${d.id}/core`, { json: { core } }); await reload(); App.toast("핵심 키워드를 저장했습니다"); }
      catch (e) { App.toast(e.message, true); }
    };
    $("#core-save", b).addEventListener("click", () => save($("#core-in", b).value.trim()));
    $("#core-auto", b)?.addEventListener("click", () => save(""));
    $("#kw-one", b).addEventListener("click", async () => {
      const t = await App.startTask(App.api("/api/keywords/collect", { json: { source_id: d.id } }));
      if (t) App.on("task-done", async function h(x) { if (x.kind === "keywords") { App.off("task-done", h); await reload(); } });
    });
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
    const link = (l) => l.store_url && l.channel_no
      ? ` <a href="${esc(l.store_url.replace(/\/$/, ""))}/products/${esc(l.channel_no)}" target="_blank" rel="noopener">보기</a>` : "";
    const live = d.listings.filter((l) => l.status !== "deleted").length;
    b.innerHTML = `<p class="muted small" style="margin:0">이 원본은 <b>${live}/${d.max_copies}곳</b>에 있습니다. 판매자 관리코드는 '스토어코드-원본번호-회차'입니다.</p>` +
      (d.listings.length ? `<table class="opt-table"><tr><th>스토어</th><th>등록 상품명</th><th>관리코드·회차</th><th>올린 날</th><th>상태</th></tr>
      ${d.listings.map((l) => `<tr class="${l.status === "deleted" ? "off" : ""}"><td>${esc(l.store_name)}</td><td>${esc(l.name)}<div class="p-sub">${num(l.price)}원</div></td>
        <td>${esc(l.seller_code || "-")}<div class="p-sub">${l.round}회차</div></td>
        <td>${l.status === "deleted" ? `내림 ${ymd(l.deleted_at)}` : l.registered_at ? `${ymd(l.registered_at)}<div class="p-sub">${age(l.registered_at)}</div>` : "-"}</td>
        <td>${statusBadge(l.status, l.op)}${link(l)}</td></tr>`).join("")}</table>`
        : `<p class="muted">아직 어느 스토어에도 계획되지 않았습니다.</p>`) +
      (d.history.length ? `<h3 class="sec-title">지난 회차 (지운 기록)</h3><table class="opt-table"><tr><th>스토어</th><th>관리코드</th><th>상품명</th><th>올린 날</th><th>지운 날</th><th>이유</th></tr>
        ${d.history.map((h) => `<tr><td>${esc(h.store_name)}</td><td>${esc(h.seller_code)}</td><td>${esc(h.name)}</td>
        <td>${ymd(h.registered_at)}</td><td>${ymd(h.deleted_at)}</td><td>${h.reason === "refresh" ? "최신화" : "내리기"}</td></tr>`).join("")}</table>` : "");
  },
});
