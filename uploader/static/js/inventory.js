/* 원본 상품 (인벤토리): 가지고 있는 원본 DB 전체. 원본은 바꾸지 않고, 걸러서 골라 → 다른 스토어로 복사 */
"use strict";

const INV_TILES = [
  { key: "all", label: "전체", dot: "var(--text-2)", count: "all_" },
  { key: "c0", label: "미복사", dot: "var(--info)" },
  { key: "c1", label: "1회 복사", dot: "var(--ok)" },
  { key: "c2", label: "2회 복사", dot: "var(--dup)" },
  { key: "warn", label: "경고 있음", dot: "var(--warn)" },
  { key: "invalid", label: "오류 (고쳐야 함)", dot: "var(--err)" },
];

/* 원본 줄 아래: AI 이름 후보 A·B… — 어느 스토어 복사본에 쓰였는지, 남았는지 (남은 이름은 다른 스토어로 복사하면 바로 붙음) */
function aiNamesLine(p) {
  const KW = { pending: "AI 키워드 받는 중", retry: "AI 키워드 실패", invalid: "원본 이름이 바뀌어 다시 받아야 함" };
  if (!p.ai_names?.length) return p.kw_status && KW[p.kw_status] ? `<div class="ai-names muted small">${KW[p.kw_status]}</div>` : "";
  return `<div class="ai-names">${p.ai_names.map((n) => `<div class="ai-name ${n.code ? "used" : "free"}" title="${esc(n.name)}">
    <b>${esc(n.label)}</b><span class="an-text">${esc(n.name)}</span>
    <span class="an-st">${n.code ? `${esc(n.code)} ${n.live ? "판매 중" : "올릴 준비"}` : "남음"}</span></div>`).join("")}</div>`;
}

App.page("inventory", {
  async mount(el, params) {
    this.f = { status: "", copies: "", q: "", price_min: "", price_max: "", store_missing: "", ...params };
    this.tile = this.f.copies !== "" ? "c" + this.f.copies : this.f.status || "all";
    this.page = 0;
    this.size = App.pageSize("inventory");
    this.sel = new Set();
    this.selAll = false;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>원본 상품</h1>
        <div class="head-actions">
          <button class="btn" id="i-catmap" title="엑셀 카테고리를 스마트스토어 카테고리에 맞추기">카테고리 맞추기</button>
          <button class="btn ghost" id="i-revalidate" title="설정이나 카테고리가 바뀐 뒤 전체를 다시 검사">다시 검사</button>
          <label class="btn primary"><input type="file" id="i-file" accept=".xlsx,.xlsm,.csv" hidden>
            <svg viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M5 20h14"/></svg>원본 엑셀 불러오기</label>
        </div></header>
      <div class="tiles" id="i-tiles"></div>
      <div class="filters-row">
        <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
          <input id="i-q" placeholder="상품명·판매자코드·카테고리 검색"></div>
        <span class="price-range" title="원본가 구간">원본가 <input id="i-pmin" type="number" min="0" step="1000" placeholder="최소">원 ~
          <input id="i-pmax" type="number" min="0" step="1000" placeholder="최대">원</span>
        <select id="i-missing" class="sel"><option value="">스토어 조건 없음</option></select>
        <select id="i-ai" class="sel" title="AI 키워드·AI 이름 후보(A·B)">
          <option value="">AI 이름 전체</option><option value="free">안 쓴 AI 이름 남음</option><option value="used">AI 이름 다 씀</option>
          <option value="none">AI 키워드 안 받음</option><option value="pending">AI 키워드 받는 중</option><option value="failed">AI 키워드 실패</option></select>
        <button class="btn ghost" id="i-reset">조건 지우기</button>
      </div>
      <div class="listbar" id="i-bar"></div>
      <div class="card table-card">
        <table class="grid"><thead><tr>
          <th class="w-check"></th>
          <th class="w-thumb"></th><th>원본 상품</th><th class="w-links">바로 가기</th><th class="w-cat">카테고리</th>
          <th class="w-num">원본가</th>
          <th class="w-copies" title="이 원본을 복사한 스토어 (원본당 최대 ${App.state.settings.max_copies}곳). 복사본은 원본 바로 아래 줄에 보입니다">복사</th>
        </tr></thead><tbody id="i-rows"></tbody></table>
        <div class="pg-foot"><div class="pg" id="i-pager"></div></div>
      </div>
    </div>`;
    $("#i-missing").innerHTML += App.stores.map((s) => `<option value="${s.id}">${esc(s.name)}에 없는 것만</option>`).join("");
    $("#i-missing").value = this.f.store_missing || "";
    $("#i-ai").value = this.f.ai || "";
    $("#i-q").value = this.f.q || "";
    this.bind();
    this.onDone = (t) => { if (["import", "plan", "revalidate", "ctxkw"].includes(t.kind)) this.load(); };
    App.on("task-done", this.onDone);
    await this.load();
  },
  unmount() { App.off("task-done", this.onDone); },

  query() {
    const f = { ...this.f };
    Object.keys(f).forEach((k) => (f[k] === "" || f[k] == null) && delete f[k]);
    return f;
  },

  async load() {
    const qs = new URLSearchParams({ ...this.query(), page: this.page, size: this.size });
    const res = await App.api(`/api/sources?${qs}`);
    this.rows = res.rows;
    this.total = res.total;
    const c = res.counts || {};
    $("#i-tiles").innerHTML = tilesHtml(INV_TILES, { ...c, all: c.all_ }, this.tile);
    $("#i-rows").innerHTML = res.rows.length ? res.rows.map((p) => this.rowHtml(p)).join("")
      : `<tr class="empty-row"><td colspan="7">${c.all_ ? "조건에 맞는 상품이 없습니다." :
        "아직 원본 상품이 없습니다. 오른쪽 위 <b>원본 엑셀 불러오기</b>를 누르거나 엑셀을 끌어다 놓으세요."}</td></tr>`;
    this.renderBar();
  },

  pagerOpts() {
    return { page: this.page, size: this.size, total: this.total,
      onPage: (p) => { this.page = p; this.load(); window.scrollTo(0, 0); },
      onSize: (n) => { this.size = n; App.savePageSize("inventory", n); this.page = 0; this.load(); } };
  },

  renderBar() {
    const n = this.selAll ? this.total : this.sel.size;
    App.listBar($("#i-bar"), {
      ...this.pagerOpts(), count: n, selAll: this.selAll, what: "원본",
      pageChecked: this.rows.length > 0 && this.rows.every((p) => this.sel.has(p.id)),
      actions: [
        { id: "ctx", label: "AI 키워드 받기", title: "고른 원본마다 AI에게 키워드(keep·다른 이름·맥락)를 한 번 받아 이름 후보 A·B를 만들어 둡니다 (실행 전에 비용 안내)" },
        { id: "copy", label: "다른 스토어로 복사", primary: true },
        "|",
        { id: "edit", label: "일괄 수정", title: "판매자코드 비우기, 재고수(상품·옵션 모두) 바꾸기" },
        { id: "delete", label: "삭제", danger: true, title: "휴지통으로 옮김 (휴지통에서 되살리거나 완전히 지울 수 있음)" },
      ],
      onPageCheck: (on) => { this.selAll = false; this.rows.forEach((p) => (on ? this.sel.add(p.id) : this.sel.delete(p.id))); this.load(); },
      onAll: () => { this.selAll = true; this.sel.clear(); this.load(); },
      onClear: () => { this.clearSel(); this.load(); },
      onAction: (id) => { if (id === "ctx") App.ctxConfirm(this.target()); if (id === "copy") this.copyModal(); if (id === "delete") this.remove(); if (id === "edit") this.editModal(); },
    });
    App.pagerBar($("#i-pager"), this.pagerOpts());
  },

  rowHtml(p) {
    const cat = (p.category || "").split(">");
    const mx = App.state.settings.max_copies || 2;
    let slots;
    if (!p.valid) slots = `<span class="badge s-fail">오류</span><div class="s-msg err" title="${esc(p.errors[0] || "")}">${esc(p.errors[0] || "")}</div>`;
    else {
      const cells = p.copies.map((c) => `<span class="slot s-${c.status === "planned" && c.op !== "create" ? c.op : c.status}"
        title="${esc(c.store)} · ${esc(statusLabel(c.status, c.op))} · ${c.round}회차">${esc(c.code)}</span>`);
      for (let i = p.copies.length; i < mx; i++) cells.push(`<span class="slot empty" title="빈 칸">·</span>`);
      slots = `<div class="slots">${cells.join("")}</div>`;
    }
    const rep = p.warnings.filter((w) => w.startsWith("반복:"));   // 같은 단어 3번 이상
    const warn = p.warnings.filter((w) => !w.startsWith("반복:"));   // 금지 키워드·상표 등
    const flags = [
      warn.length ? `<span class="flag warn" title="${esc(warn.join("\n"))}">경고 ${warn.length}</span>` : "",
      rep.length ? `<span class="flag rep" title="${esc(rep.join("\n"))}">반복</span>` : "",
      p.has_video ? `<span class="flag video" title="상세설명에 동영상 있음 (경고 아님)">동영상</span>` : "",
    ].join("");
    const on = this.selAll || this.sel.has(p.id);
    return `<tr data-id="${p.id}" class="${on ? "sel" : ""}">
      <td class="w-check" data-stop><input type="checkbox" ${on ? "checked" : ""} ${this.selAll ? "disabled" : ""} aria-label="고르기"></td>
      <td>${img(p.thumb)}</td>
      <td><div class="p-name">${esc(p.name)}</div><div class="p-sub"><span>원본 #${p.id}</span>${p.seller_code ? `<span>${esc(p.seller_code)}</span>` : ""}${flags}</div>
        ${aiNamesLine(p)}</td>
      <td class="w-links">${goLinks({ sourceId: p.id })}</td>
      <td class="cat-td"><div class="cat">${cat.length > 2 ? `<div class="cat-top">${esc(cat.slice(0, -2).join(" › "))}</div>` : ""}${esc(cat.slice(-2).join(" › "))}</div></td>
      <td class="num">${num(p.price)}원</td>
      <td>${slots}${p.deleted_copies ? `<div class="p-sub">내림 ${p.deleted_copies}</div>` : ""}</td></tr>`
      + p.copies.map((c) => this.copyRowHtml(c, p)).join("");
  },

  /* 원본 바로 아래에 붙는 복사본 한 줄 (누르면 그 스토어 복사본으로) */
  copyRowHtml(c, p) {
    const msg = c.status === "fail" || (c.status === "success" && c.message) ? c.message : "";
    return `<tr class="copy-row" data-copy="${c.id}" title="이 스토어의 복사본으로 가기">
      <td></td><td class="copy-arrow">↳</td>
      <td colspan="3"><div class="copy-name"><span class="code">${esc(c.code)}</span> <span class="muted">${esc(c.store)}</span> ${esc(c.name)}</div>
        <div class="p-sub">${esc(c.seller_code || "관리코드는 등록할 때 붙음")} · ${c.round}회차${c.registered_at && c.channel_no ? ` · ${ymd(c.registered_at)} 올림 (${age(c.registered_at)})` : ""}</div></td>
      ${priceCell(c, p.price)}
      <td>${statusBadge(c.status, c.op)}${lockFlag(c)}${msg ? `<div class="s-msg ${c.status === "fail" ? "err" : ""}" title="${esc(msg)}">${esc(msg)}</div>` : ""}</td></tr>`;
  },

  target() { return this.selAll ? this.query() : { ids: [...this.sel] }; },
  targetCount() { return this.selAll ? this.total : this.sel.size; },
  clearSel() { this.sel.clear(); this.selAll = false; },

  setFilter(patch) { Object.assign(this.f, patch); this.page = 0; this.clearSel(); this.load(); },

  bind() {
    $("#i-file").addEventListener("change", (e) => { if (e.target.files[0]) App.upload("/api/sources/import", e.target.files[0]); e.target.value = ""; });
    $("#i-catmap").addEventListener("click", () => this.catMap());
    $("#i-revalidate").addEventListener("click", () => App.startTask(App.api("/api/sources/revalidate", { json: {} })));
    $("#i-tiles").addEventListener("click", (e) => {
      const t = e.target.closest("[data-filter]");
      if (!t) return;
      this.tile = t.dataset.filter;
      const k = this.tile;
      this.setFilter({ copies: /^c\d$/.test(k) ? k.slice(1) : "", status: ["warn", "invalid"].includes(k) ? k : "" });
    });
    let timer;
    const later = (patch) => { clearTimeout(timer); timer = setTimeout(() => this.setFilter(patch), 350); };
    $("#i-q").addEventListener("input", (e) => later({ q: e.target.value.trim() }));
    $("#i-pmin").addEventListener("input", (e) => later({ price_min: e.target.value }));
    $("#i-pmax").addEventListener("input", (e) => later({ price_max: e.target.value }));
    $("#i-missing").addEventListener("change", (e) => this.setFilter({ store_missing: e.target.value }));
    $("#i-ai").addEventListener("change", (e) => this.setFilter({ ai: e.target.value }));
    $("#i-reset").addEventListener("click", () => {
      $("#i-q").value = $("#i-pmin").value = $("#i-pmax").value = ""; $("#i-missing").value = ""; $("#i-ai").value = "";
      this.tile = "all";
      this.setFilter({ status: "", copies: "", q: "", price_min: "", price_max: "", store_missing: "", ai: "" });
    });
    $("#i-rows").addEventListener("click", (e) => {
      const cr = e.target.closest("tr[data-copy]");
      if (cr) { App.pages.listings.goto(+cr.dataset.copy); return; }
      const tr = e.target.closest("tr[data-id]");
      if (!tr || e.target.closest("a")) return;   // '원본 ↗' 링크는 그대로 새 창
      const id = +tr.dataset.id;
      if (e.target.closest("[data-stop]")) {
        if (this.selAll) return;
        this.sel.has(id) ? this.sel.delete(id) : this.sel.add(id);
        tr.classList.toggle("sel", this.sel.has(id));
        $("input", tr).checked = this.sel.has(id);
        this.renderBar();
        return;
      }
      this.openSource(id);
    });
  },

  editModal() {
    const n = this.targetCount();
    App.openModal({
      title: `원본 일괄 수정 · ${num(n)}개`,
      body: `<div class="form">
        <label class="check"><input type="checkbox" id="e-code" checked><span><b>판매자코드 비우기</b> <span class="muted small">(나중에 일괄로 채울 때. 등록할 때는 프로그램이 스토어별 관리코드를 따로 붙입니다)</span></span></label>
        <label class="check"><input type="checkbox" id="e-stock-on" checked><span><b>재고수 바꾸기</b> · 상품 재고와 <b>옵션 재고 모두</b>
          <input type="number" id="e-stock" min="0" value="1000" class="inline-num" style="width:90px">개로</span></label>
        <p class="muted small">원본 엑셀을 다시 불러오면 그 파일의 값으로 돌아갑니다. 이미 네이버에 올라간 복사본은 바뀌지 않고, 앞으로 올리는 것부터 적용됩니다.</p></div>`,
      buttons: [{ label: "취소" }, { label: "바꾸기", primary: true, onClick: async (b) => {
        const body = { ...this.target(), clear_seller_code: $("#e-code", b).checked, stock: $("#e-stock-on", b).checked ? $("#e-stock", b).value : "" };
        try {
          const r = await App.api("/api/sources/bulk_edit", { json: body });
          App.toast(`원본 ${num(r.edited)}개를 바꿨습니다`);
          this.load();
        } catch (e) { App.toast(e.message, true); return false; }
      } }],
    });
  },

  async remove() {
    const n = this.targetCount();
    const ok = await App.confirmDanger({
      title: `원본 ${num(n)}개 삭제`,
      body: `<p>고른 원본 <b>${num(n)}개</b>를 <b>휴지통</b>으로 옮깁니다. 그 원본의 복사본(아직 안 올린 것·내린 것)과 이름 후보도 함께 옮겨집니다.</p>
        <p class="muted small">네이버에 올라가 있거나 처리 중인 복사본이 있는 원본은 지우지 않습니다(먼저 복사본에서 '내리기').
          휴지통에서 되살리거나 완전히 지울 수 있습니다.</p>`,
    });
    if (!ok) return;
    try {
      const r = await App.api("/api/sources/delete", { json: this.target() });
      App.toast(`원본 ${num(r.moved)}개를 휴지통으로 옮겼습니다` + (r.skipped_live ? ` · 네이버에 올라가 있는 복사본이 있어 뺀 원본 ${num(r.skipped_live)}개` : ""));
      this.clearSel(); this.load(); App.refreshState();
    } catch (e) { App.toast(e.message, true); }
  },

  // ── 다른 스토어로 복사: 고른 원본을 고른 스토어(1~2곳)에 그대로 복사

  async copyModal() {
    const stores = (await App.loadStores()).filter((s) => s.enabled);
    const n = this.targetCount();
    const mx = App.state.settings.max_copies || 2;
    App.openModal({
      title: `다른 스토어로 복사 · 원본 ${num(n)}개`,
      wide: true,
      body: `<div class="form">
        <p class="muted small" style="margin:0">고른 원본을 <b>고른 스토어에 그대로</b> 복사합니다. 스토어는 ${mx}곳까지 고를 수 있습니다.
          원본 하나는 최대 ${mx}곳(내린 스토어는 세지 않음)이라, 이미 그 스토어에 있거나 ${mx}회를 넘는 원본은 빼고 몇 개 뺐는지 알려 드립니다.</p>
        <div class="store-pick">${byBusiness(stores).map(([biz, ss]) => `<div class="sp-group">${esc(biz)}</div>` + ss.map((s) => `
          <label class="sp-row"><input type="checkbox" value="${s.id}">
            <span class="sp-name"><span class="code">${esc(s.code)}</span> ${esc(s.name)}${s.has_keys ? "" : ' <span class="flag warn">키 없음</span>'}</span>
            ${usageBar(s.used, s.capacity)}<span class="sp-free ${s.free < 100 ? "c-err" : "muted"}">남은 자리 ${num(s.free)}</span></label>`).join("")).join("")
          || '<p class="muted">스토어가 없습니다. 스토어 화면에서 먼저 추가하세요.</p>'}</div>
        ${App.state.settings.bait_default ? `<label class="check bait-check"><input type="checkbox" id="p-bait" checked>
          <span><b>도둑방지로 올리기</b> · 새로 올릴 때마다(등록·최신화·다시 올리기) 판매가 +${num(App.state.settings.bait_amount)}원 (원래 가격으로는 직접 되돌림)</span></label>` : ""}
        <div class="plan-sum" id="p-sum"></div>
        <p class="muted small">상품명: AI 키워드로 만들어 둔 이름 후보가 있으면 바로 붙고, 없으면 복사본 화면에서 '이름 변경 필요'로 보입니다.
          가격은 스토어 템플릿의 가격 조정과 ±${App.state.settings.price_jitter_pct}%, 100원 단위 올림.</p></div>`,
      buttons: [{ label: "취소" }, {
        label: "복사하기", primary: true, onClick: async (b) => {
          const store_ids = $$(".store-pick input:checked", b).map((x) => +x.value);
          if (!store_ids.length) { App.toast("스토어를 하나 이상 고르세요.", true); return false; }
          const r = await App.startTask(App.api("/api/plans", {
            json: { ...this.target(), store_ids, mode: "all", bait: $("#p-bait", b)?.checked ?? true },
          }));
          if (r) this.clearSel();
          return !!r;
        },
      }],
    });
    const sum = () => {
      const picked = $$(".store-pick input:checked");
      $$(".store-pick input").forEach((x) => { x.disabled = !x.checked && picked.length >= mx; });
      const names = picked.map((x) => stores.find((s) => s.id === +x.value)?.name).filter(Boolean);
      $("#p-sum").innerHTML = picked.length
        ? `원본 <b>${num(n)}개</b> → <b>${names.map(esc).join(", ")}</b> · 최대 <b>${num(n * picked.length)}건</b> 복사`
        : `복사할 스토어를 고르세요 (최대 ${mx}곳).`;
    };
    $$(".store-pick input").forEach((x) => x.addEventListener("change", sum));
    sum();
  },

  // ── 원본 상세

  async openSource(id, tab) {
    let d;
    try { d = await App.api(`/api/sources/${id}`); } catch (e) { return App.toast(e.message, true); }
    const self = this;
    App.openDrawer({
      title: d.name, sub: `원본 #${d.id}${d.seller_code ? " · " + d.seller_code : ""} · 원본가 ${num(d.price)}원`, tab,
      foot: d.source_url ? `<a class="btn" href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">원본 상품 페이지 ↗</a>` : "",
      tabs: [
        { key: "info", label: "정보", render: (b) => self.renderInfo(b, d) },
        { key: "stores", label: `복사본 ${d.listings.filter((l) => l.status !== "deleted").length}/${d.max_copies}`, render: (b) => self.renderListings(b, d) },
        { key: "ctx", label: `AI 키워드 ${d.ctx.usable.length}`, render: (b) => self.renderCtx(b, d) },
        { key: "names", label: `상품명 후보 ${d.names.filter((n) => n.listing_id !== -1).length}`, render: (b) => self.renderNames(b, d) },
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

  renderCtx(b, d) {
    const k = d.ctx;
    const st = { ok: "받음", pending: "일괄 처리 중", retry: "재시도 대기", invalid: "원본 상품명이 바뀌어 다시 받아야 함" }[k.status] || "아직 안 받음";
    const group = (key, label, help) => {
      const all = k.kw?.[key] || [], use = k.use?.[key] || [];
      return `<div class="kw-grp"><h3 class="sec-title">${label} <span class="muted small" style="font-weight:400">${help}</span></h3>
        ${all.length ? `<div class="kw-chips">${all.map((w) => `<span class="kw-chip ${use.includes(w) ? "used" : "off"}"
          title="${use.includes(w) ? "이름에 쓰는 단어" : "안 씀 (앞 단어에 이미 있음·원본에 없음·금지어·상표·직접 차단 등)"}">${esc(w)}</span>`).join("")}</div>` : '<span class="muted small">없음</span>'}</div>`;
    };
    b.innerHTML = `<div class="kw-src">
      <p class="muted small">이름 = [원본 앞 ${esc((k.head || []).length)}단어${k.nums?.length ? ` · ${esc(k.nums.join(" "))}는 뒤로` : ""}] + keep + 다른 이름 전부 + 맥락(남는 자리) + 남은 원본 단어.
        상태: <b>${st}</b>${k.at ? ` · ${ymd(k.at)}` : ""}${k.error ? ` · <span class="c-err">${esc(k.error)}</span>` : ""}</p>
      ${k.status === "ok" ? group("keep", "keep", "원본에서 지킬 핵심 단어") + group("core", "다른 이름 (core)", "같은 물건을 부르는 다른 이름 · 이름 하나에 1개") + group("ctx", "맥락 (ctx)", "쓰는 장소·사람·용도·상황")
        : `<button class="btn" id="ctx-one">이 원본 AI 키워드 받기</button>`}
    </div>`;
    $("#ctx-one", b)?.addEventListener("click", () => App.ctxConfirm({ ids: [d.id] }));
  },

  renderNames(b, d) {
    const names = d.names.filter((n) => n.listing_id !== -1);   // 바꿔 버린 이름(-1)은 숨김
    b.innerHTML = `<p class="muted small" style="margin:0">이 원본으로 만든 이름입니다. <b>AI 이름 A·B…</b>는 AI 키워드로 만든 후보로, 1번째·2번째 스토어 복사본에 차례로 붙습니다.
        <b>남음</b>인 이름은 이 원본을 다른 스토어로 복사하면 바로 붙습니다. 모든 이름은 33개 스토어 전체에서 겹치지 않습니다.</p>
      <ul class="name-list">${names.map((n) => `<li>
        ${n.origin === "ctx" ? `<span class="org org-ctx">AI 이름 ${esc(n.label || "")}</span>` : `<span class="org org-${n.origin}">${ORIGIN[n.origin] || n.origin}</span>`}
        <span class="nm">${esc(n.name)}</span>
        ${n.listing_id ? `<span class="muted small">${esc(n.store_name)} · ${STATUS[n.status] || ""}</span>`
          : n.origin === "original" ? `<span class="muted small">원본</span>`
          : `<span class="c-ok small"><b>남음</b></span> <button class="link-btn danger-text" data-del="${n.id}">지우기</button>`}</li>`).join("")}</ul>`;
    const reload = async () => { const nd = await App.api(`/api/sources/${d.id}`); Object.assign(d, nd); this.renderNames(b, d); this.load(); };
    $(".name-list", b).addEventListener("click", async (e) => {
      const id = e.target.dataset.del;
      if (!id) return;
      try { await App.api(`/api/names/${id}`, { method: "DELETE" }); await reload(); } catch (err) { App.toast(err.message, true); }
    });
  },

  renderListings(b, d) {
    const live = d.listings.filter((l) => l.status !== "deleted").length;
    b.innerHTML = `<p class="muted small" style="margin:0">이 원본은 <b>${live}/${d.max_copies}곳</b>에 있습니다. 줄을 누르면 그 스토어 복사본으로 갑니다.</p>` +
      (d.listings.length ? `<table class="opt-table"><tr><th>스토어</th><th>등록 상품명</th><th>관리코드·회차</th><th>올린 날</th><th>상태</th></tr>
      ${d.listings.map((l) => `<tr class="${l.status === "deleted" ? "off" : "clickable"}" data-go="${l.id}"><td>${esc(l.store_name)}</td>
        <td>${nameDiff(l.nd)}<div class="p-sub">${num(l.price)}원</div></td>
        <td>${esc(l.seller_code || "-")}<div class="p-sub">${l.round}회차</div></td>
        <td>${l.status === "deleted" ? `내림 ${ymd(l.deleted_at)}` : l.registered_at ? `${ymd(l.registered_at)}<div class="p-sub">${age(l.registered_at)}</div>` : "-"}</td>
        <td>${statusBadge(l.status, l.op)}</td></tr>`).join("")}</table>${ND_LEGEND}`
        : `<p class="muted">아직 어느 스토어에도 복사하지 않았습니다.</p>`) +
      (d.history.length ? `<h3 class="sec-title">지난 회차 (지운 기록)</h3><table class="opt-table"><tr><th>스토어</th><th>관리코드</th><th>상품명</th><th>올린 날</th><th>지운 날</th><th>이유</th></tr>
        ${d.history.map((h) => `<tr><td>${esc(h.store_name)}</td><td>${esc(h.seller_code)}</td><td>${esc(h.name)}</td>
        <td>${ymd(h.registered_at)}</td><td>${h.deleted_at ? ymd(h.deleted_at) : "스토어에서 이미 지움"}</td><td>${OP[h.reason] || "내리기"}</td></tr>`).join("")}</table>` : "");
    $$("tr[data-go]", b).forEach((tr) => tr.addEventListener("click", () => { App.closeDrawer(); App.pages.listings.goto(+tr.dataset.go); }));
  },

  /* 카테고리 맞추기: 스마트스토어에서 못 찾은 엑셀 카테고리를 네이버 카테고리에 하나씩 맞춘다 */
  async catMap() {
    let d;
    try { d = await App.api("/api/categories/unmatched"); } catch (e) { return App.toast(e.message, true); }
    const miss = d.items.filter((x) => !x.how);
    const row = (x, i) => `<div class="cm-row" data-i="${i}">
        <div class="cm-src"><b>${esc(x.category)}</b> <span class="muted small">원본 ${num(x.count)}개</span></div>
        <div class="cm-pick"><select class="sel cm-sel"><option value="">— 고르기 —</option>${x.suggest.map((s) => `<option ${s === x.guess ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
          ${x.guess ? `<span class="muted small">이름이 거의 같은 카테고리를 미리 골라 두었습니다. 맞으면 그대로 저장하세요.</span>` : ""}
          <input class="cm-q" placeholder="검색해서 고르기 (예: 모자 사파리)"><div class="cm-hits"></div></div></div>`;
    App.openModal({
      title: "카테고리 맞추기", wide: true,
      body: `<div id="cm-box">
        <p class="muted small">스마트스토어 카테고리 ${num(d.cached)}개${d.cached_at ? ` · ${when(d.cached_at)}에 받음` : ""}
          <button type="button" class="btn sm" id="cm-refresh">카테고리 목록 다시 받기</button></p>
        ${!d.cached ? '<p class="c-err">카테고리 목록이 아직 없습니다. 위 버튼으로 먼저 받아 주세요 (API 키가 있는 스토어 필요).</p>'
          : miss.length ? `<p>못 찾은 카테고리 <b>${num(miss.length)}</b>가지 · 원본 <b>${num(miss.reduce((a, x) => a + x.count, 0))}</b>개. 비슷한 것을 고르거나 검색해서 고른 뒤 저장하세요. 같은 엑셀 카테고리는 다음 파일에도 그대로 맞춰집니다.</p>
            <div class="cm-list">${miss.map(row).join("")}</div>` : '<p>못 찾은 카테고리가 없습니다.</p>'}
      </div>`,
      buttons: [{ label: "닫기" }, { label: "저장하고 다시 검사", primary: true, onClick: async (b) => {
        const items = $$(".cm-row", b).map((r) => ({ from: miss[+r.dataset.i].category, to: $(".cm-sel", r).value })).filter((x) => x.to);
        if (!items.length) { App.toast("고른 카테고리가 없습니다.", true); return false; }
        try {
          await App.api("/api/categories/map", { json: { items } });
          App.toast(`카테고리 ${num(items.length)}가지를 맞췄습니다. 전체 원본을 다시 검사합니다.`);
        } catch (e) { App.toast(e.message, true); return false; }
      } }],
    });
    const box = $("#cm-box");
    $("#cm-refresh", box).addEventListener("click", async () => {
      try {
        const r = await App.startTask(App.api("/api/categories/refresh", { json: {} }));
        if (r) { App.toast(`카테고리 ${num(r.categories)}개를 받았습니다. 다시 검사 뒤 이 창을 다시 열어 보세요.`); App.closeModal(); }
      } catch (e) { App.toast(e.message, true); }
    });
    let timer;
    box.addEventListener("input", (e) => {
      const q = e.target.closest(".cm-q");
      if (!q) return;
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const hits = q.value.trim() ? await App.api(`/api/categories/search?q=${encodeURIComponent(q.value.trim())}`) : [];
        q.nextElementSibling.innerHTML = hits.map((h) => `<button type="button" class="cm-hit">${esc(h)}</button>`).join("")
          || (q.value.trim() ? '<span class="muted small">없음</span>' : "");
      }, 250);
    });
    box.addEventListener("click", (e) => {
      const h = e.target.closest(".cm-hit");
      if (!h) return;
      const sel = $(".cm-sel", h.closest(".cm-row"));
      if (![...sel.options].some((o) => o.value === h.textContent)) sel.add(new Option(h.textContent, h.textContent));
      sel.value = h.textContent;
      h.parentElement.innerHTML = "";
    });
  },
});
