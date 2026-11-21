/* 판매 현황: 판매자센터 주문(커머스API)을 가져와 기간·스토어별로 보고, 어느 복사본의 판매인지 보여준다 */
"use strict";

const PERIODS = [["1", "오늘"], ["7", "최근 7일"], ["30", "최근 30일"], ["90", "최근 90일"], ["all", "전체"], ["custom", "직접 고르기"]];

function dayStr(offsetDays = 0) {
  const d = new Date(Date.now() - offsetDays * 86400000), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

App.page("orders", {
  size: 100,

  async mount(el, params) {
    this.f = { period: "30", store_id: "", matched: "", q: "", from: "", to: "", ...params };
    this.page = 0;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>판매 현황</h1>
        <div class="head-actions">
          <label class="btn primary" title="판매자센터 등에서 내려받은 판매 현황(주문) 파일"><input type="file" id="o-file" accept=".xlsx,.xlsm,.csv" hidden>판매 현황 파일 넣기</label>
        </div></header>
      <div class="sync-info card" id="o-auto"></div>
      <div class="toolbar"><div class="filters">
        <select id="o-period" class="sel">${PERIODS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
        <span id="o-custom" hidden><input type="date" id="o-from" class="sel"> ~ <input type="date" id="o-to" class="sel"></span>
        <select id="o-store" class="sel"><option value="">모든 스토어</option></select>
        <select id="o-matched" class="sel"><option value="">모든 주문</option><option value="1">복사본과 맞춘 주문</option><option value="0">못 맞춘 주문</option></select>
        <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
          <input id="o-q" placeholder="상품명·주문번호·관리코드"></div>
      </div></div>
      <div class="tiles" id="o-tiles"></div>
      <div class="order-grid">
        <div class="card table-card">
          <table class="grid"><thead><tr><th class="w-date">결제일</th><th class="w-store">스토어</th><th>주문 상품</th>
            <th class="w-small">수량</th><th class="w-small2">상태</th><th class="w-copy">복사본 · 원본</th></tr></thead><tbody id="o-rows"></tbody></table>
          <div class="pager" id="o-pager"></div>
        </div>
        <div class="card pad"><div class="sec-head"><h2>스토어별</h2><span class="muted small">이 기간·조건</span></div>
          <table class="opt-table" id="o-by-store"></table></div>
      </div>
      <div class="card table-card" style="margin-top:12px"><div class="sec-head pad-x"><h2>넣은 주문 파일</h2>
        <span class="muted small">잘못 넣었으면 파일째 되돌리기 — 그 파일로 들어온 주문만 지우고 판매 수·잠금을 다시 셈 (네이버에서 받은 주문은 그대로)</span></div>
        <table class="grid"><thead><tr><th class="w-date">넣은 때</th><th>파일</th><th class="num">줄</th><th class="num">새 주문</th><th class="num">남은 주문</th><th>맞춘 주문 (복사본 · 2건 이상)</th><th class="num">못 맞춘 주문</th><th></th></tr></thead>
          <tbody id="o-imports"></tbody></table></div>
    </div>`;
    $("#o-store").innerHTML += App.stores.map((s) => `<option value="${s.id}">${esc(s.code)} ${esc(s.name)}</option>`).join("");
    $("#o-period").value = this.f.period;
    $("#o-store").value = this.f.store_id;
    $("#o-matched").value = this.f.matched;
    $("#o-from").value = this.f.from || dayStr(30);
    $("#o-to").value = this.f.to || dayStr(0);
    $("#o-custom").hidden = this.f.period !== "custom";
    this.bind();
    this.onDone = (t) => { if (t.kind === "orders") { this.load(); this.loadImports(); } };
    App.on("task-done", this.onDone);
    await this.load();
    this.loadImports();
  },
  unmount() { App.off("task-done", this.onDone); },

  /* 넣은 주문 파일 목록 + [이 파일 되돌리기] */
  async loadImports() {
    const box = $("#o-imports");
    if (!box) return;
    let rows = [];
    try { rows = await App.api("/api/orders/imports"); } catch (e) { return; }
    box.innerHTML = rows.length ? rows.map((r) => `<tr>
        <td>${when(r.created_at)}</td>
        <td>${esc(r.file)}${r.guessed ? ' <span class="muted small">(넣은 때로 묶음)</span>' : ""}</td>
        <td class="num">${num(r.rows)}</td><td class="num">${num(r.new)}</td><td class="num">${num(r.left)}</td>
        <td>${num(r.matched_n)}건 <span class="muted small">(복사본 ${num(r.copies)}개${r.multi ? ` · 2건 이상 ${num(r.multi)}개` : ""})</span></td>
        <td class="num">${r.unmatched ? `<button class="link-btn c-err" data-unm="${r.id}">${num(r.unmatched)}건</button>` : "0"}</td>
        <td>${r.undone_at ? `<span class="muted small">되돌림 ${when(r.undone_at)}</span>` : r.undoable
          ? `<button class="btn sm danger" data-undo="${r.id}">이 파일 되돌리기</button>` : '<span class="muted small">남은 주문 없음</span>'}</td></tr>`).join("")
      : '<tr class="empty-row"><td colspan="8">넣은 주문 파일이 없습니다.</td></tr>';
    $$("[data-undo]", box).forEach((b) => b.addEventListener("click", () => this.undoImport(+b.dataset.undo)));
    $$("[data-unm]", box).forEach((b) => b.addEventListener("click", async () => {
      let L = [];
      try { L = await App.api(`/api/orders/unmatched?import_id=${b.dataset.unm}`); } catch (e) { return App.toast(e.message, true); }
      App.openModal({ title: `못 맞춘 주문 ${num(L.length)}건`, wide: true,
        body: `<p class="small muted">업스타 복사본의 상품번호·관리코드·상품명과 맞는 게 없는 주문 — 어느 복사본도 잠그지 않습니다 (다른 프로그램으로 올린 상품·이미 지운 상품 등).</p>
          <div class="tbl-wrap" style="max-height:60vh"><table class="tbl small"><thead><tr><th>주문일</th><th>스토어</th><th>상품번호</th><th>관리코드</th><th>상품명</th><th class="r">수량</th></tr></thead><tbody>${L.map((o) =>
            `<tr><td>${when(o.ordered_at)}</td><td>${esc(o.store || "")}</td><td>${esc(o.channel_no || o.origin_no || "")}</td><td>${esc(o.seller_code || "")}</td><td>${esc((o.product_name || "").slice(0, 50))}</td><td class="r">${num(o.quantity)}</td></tr>`).join("")}</tbody></table></div>`,
        buttons: [{ label: "닫기" }] });
    }));
  },

  async undoImport(id) {
    let pv;
    try { pv = await App.api(`/api/orders/imports/${id}/undo_preview`); } catch (e) { return App.toast(e.message, true); }
    App.openModal({
      title: "주문 파일 되돌리기",
      body: `<div class="notice warn"><b>${esc(pv.file)}</b>로 들어온 주문 <b>${num(pv.orders)}건</b>을 지웁니다.</div>
        <ul class="small"><li>이 주문이 맞춰진 복사본 <b>${num(pv.copies)}건</b>의 판매 수·잠금을 다시 셉니다 — 다른 판매 이력·직접 잠금이 없는 <b>${num(pv.unlock)}건</b>은 잠금이 풀립니다.</li>
          <li>네이버에서 받은 주문·다른 파일로 넣은 주문은 그대로입니다.</li>
          ${pv.guessed ? "<li>이 기록은 예전에 넣은 주문을 넣은 때(10분 안쪽)로 묶은 것입니다 — 같은 때 넣은 다른 파일 주문이 섞였을 수 있습니다.</li>" : ""}
          <li>되돌린 뒤 잘못 풀렸으면 맞는 주문 파일을 다시 넣으면 됩니다.</li></ul>`,
      buttons: [{ label: "취소" }, { label: "되돌리기", danger: true,
        confirm: `주문 ${num(pv.orders)}건을 지우고 복사본 ${num(pv.copies)}건의 판매 수·잠금을 다시 셉니다 (잠금 풀림 ${num(pv.unlock)}건).`,
        onClick: async () => {
          const r = await App.api(`/api/orders/imports/${id}/undo`, { json: {} });
          App.toast(`주문 ${num(r.removed)}건 지움 · 잠금 풀림 ${num(r.unlocked)}건` + (r.still_locked ? ` · 다른 판매 이력·직접 잠금으로 아직 잠김 ${num(r.still_locked)}건` : ""));
          this.load(); this.loadImports();
        } }],
    });
  },

  query() {
    const q = {};
    if (this.f.store_id) q.store_id = this.f.store_id;
    if (this.f.matched) q.matched = this.f.matched;
    if (this.f.q) q.q = this.f.q;
    if (this.f.period === "custom") { q.from = $("#o-from").value; q.to = $("#o-to").value; }
    else if (this.f.period !== "all") q.from = dayStr(+this.f.period - 1);
    return q;
  },

  async load() {
    const res = await App.api(`/api/orders/list?${new URLSearchParams({ ...this.query(), page: this.page, size: this.size })}`);
    const s = res.summary;
    $("#o-tiles").innerHTML = [
      ["주문", s.orders, "var(--text-2)"], ["판매 수량", s.quantity, "var(--ok)"],
      ["판매된 복사본", s.copies, "var(--info)"], ["판매된 원본", s.sources, "var(--info)"],
      ["취소·반품", s.canceled, "var(--warn)"], ["못 맞춘 주문", s.unmatched, "var(--err)"],
    ].map(([l, n, c]) => `<div class="tile static" style="--dot:${c}"><div class="t-label">${l}</div><div class="t-num">${num(n)}</div></div>`).join("");

    const chk = res.stores.filter((x) => x.checked_at).map((x) => x.checked_at);
    const never = res.stores.filter((x) => !x.checked_at).length;
    $("#o-auto").innerHTML = `<div><b>판매 이력은 판매 현황 파일·[판매 이력 확인 완료]로만 확인합니다</b> <span class="muted">(네이버에서 주문을 받지 않음)</span></div>
      <div class="muted small">${chk.length ? `가장 오래 전에 확인한 스토어: ${when(Math.min(...chk))}` : "아직 확인한 스토어 없음"}${never ? ` · 한 번도 확인 안 한 스토어 ${never}곳` : ""}
        · 판매 이력이 있는 복사본은 최신화·내리기에서 빠집니다.</div>`;

    $("#o-rows").innerHTML = res.rows.length ? res.rows.map((o) => `<tr data-lid="${o.listing_id || ""}"${o.ignored ? ' style="opacity:.55"' : ""}>
      <td>${o.ordered_at ? ymd(o.ordered_at) : "-"}<div class="p-sub">${o.source === "naver" ? "네이버" : "파일"}</div></td>
      <td>${o.store_name ? `<b class="code">${esc(o.store_code)}</b> ${esc(o.store_name)}` : '<span class="muted">-</span>'}</td>
      <td><div class="p-name">${esc(o.product_name || o.listing_name || "")}</div>
        <div class="p-sub">${esc(o.order_key.replace(/^file:/, ""))}${o.seller_code ? ` · ${esc(o.seller_code)}` : ""}</div></td>
      <td class="num">${num(o.quantity)}</td>
      <td><span class="badge ${["CANCELED", "RETURNED", "CANCELED_BY_NOPAYMENT"].includes(o.status) ? "s-delete" : "s-success"}">${esc(o.status_ko || "-")}</span>${o.ignored ? ' <span class="badge" style="opacity:.6" title="이 복사본에서 판매 이력 무시 — 판매 수·잠금에서 뺌">무시함</span>' : ""}</td>
      <td>${o.listing_id ? `<span class="link-btn">복사본 보기</span><div class="p-sub">원본 #${o.source_id}</div>`
        : `<span class="c-err small">못 맞춤</span><div class="p-sub">이 프로그램이 올린 상품이 아닐 수 있음</div>`}</td></tr>`).join("")
      : `<tr class="empty-row"><td colspan="6">이 기간에 주문이 없습니다. 오른쪽 위 <b>판매 현황 파일 넣기</b>로 넣으세요.</td></tr>`;
    App.pager($("#o-pager"), { page: this.page, size: this.size, total: res.total, onPage: (p) => { this.page = p; this.load(); } });

    const max = Math.max(1, ...res.by_store.map((x) => x.orders));
    $("#o-by-store").innerHTML = res.by_store.length ? `<tr><th>스토어</th><th class="r">주문</th><th class="r">수량</th></tr>` +
      res.by_store.map((x) => `<tr><td>${x.id ? `<b class="code">${esc(x.code)}</b> ${esc(x.name)}` : "알 수 없음"}
        <div class="usage thin-usage"><div style="width:${(x.orders / max) * 100}%"></div></div></td>
        <td class="r">${num(x.orders)}</td><td class="r">${num(x.quantity)}</td></tr>`).join("")
      : `<tr><td class="muted">없음</td></tr>`;
  },

  bind() {
    const reload = () => { this.page = 0; this.load(); };
    $("#o-period").addEventListener("change", (e) => { this.f.period = e.target.value; $("#o-custom").hidden = this.f.period !== "custom"; reload(); });
    $("#o-from").addEventListener("change", reload);
    $("#o-to").addEventListener("change", reload);
    $("#o-store").addEventListener("change", (e) => { this.f.store_id = e.target.value; reload(); });
    $("#o-matched").addEventListener("change", (e) => { this.f.matched = e.target.value; reload(); });
    let t;
    onTyped($("#o-q"), (v) => { this.f.q = v.trim(); reload(); });
    $("#o-file").addEventListener("change", (e) => { if (e.target.files[0]) App.upload("/api/orders/import", e.target.files[0]); e.target.value = ""; });
    $("#o-rows").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-lid]");
      if (tr?.dataset.lid) App.pages.listings.openListing(+tr.dataset.lid);
    });
  },
});
