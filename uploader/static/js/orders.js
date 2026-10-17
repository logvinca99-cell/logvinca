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
          <label class="btn ghost" title="아바닛 등 다른 곳에서 내려받은 주문 파일"><input type="file" id="o-file" accept=".xlsx,.xlsm,.csv" hidden>주문 파일 가져오기</label>
          <button class="btn" id="o-range">기간 지정해서 가져오기…</button>
          <button class="btn primary" id="o-sync">지금 가져오기</button>
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
    </div>`;
    $("#o-store").innerHTML += App.stores.map((s) => `<option value="${s.id}">${esc(s.code)} ${esc(s.name)}</option>`).join("");
    $("#o-period").value = this.f.period;
    $("#o-store").value = this.f.store_id;
    $("#o-matched").value = this.f.matched;
    $("#o-from").value = this.f.from || dayStr(30);
    $("#o-to").value = this.f.to || dayStr(0);
    $("#o-custom").hidden = this.f.period !== "custom";
    this.bind();
    this.onDone = (t) => { if (t.kind === "orders") this.load(); };
    App.on("task-done", this.onDone);
    await this.load();
  },
  unmount() { App.off("task-done", this.onDone); },

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

    const a = res.auto;
    const synced = res.stores.filter((x) => x.synced_to).map((x) => x.synced_to);
    const never = res.stores.filter((x) => !x.synced_to && x.has_keys).length;
    $("#o-auto").innerHTML = `<div><b>${a.minutes ? `자동 가져오기 ${a.minutes}분마다` : "자동 가져오기 꺼짐"}</b>
        ${a.minutes && a.next_at ? ` · 다음 ${when(a.next_at)}` : ""} <span class="muted">(설정에서 바꿈 · 프로그램이 켜져 있을 때만)</span></div>
      <div class="muted small">판매자센터의 주문을 커머스API로 가져옵니다. ${synced.length
        ? `가장 오래 전에 가져온 스토어: ${when(Math.min(...synced))}` : "아직 가져온 적 없음"}${never ? ` · 한 번도 안 가져온 스토어 ${never}곳` : ""}
        · 판매 이력이 있는 복사본은 최신화·내리기에서 빠집니다.</div>`;

    $("#o-rows").innerHTML = res.rows.length ? res.rows.map((o) => `<tr data-lid="${o.listing_id || ""}">
      <td>${o.ordered_at ? ymd(o.ordered_at) : "-"}<div class="p-sub">${o.source === "naver" ? "네이버" : "파일"}</div></td>
      <td>${o.store_name ? `<b class="code">${esc(o.store_code)}</b> ${esc(o.store_name)}` : '<span class="muted">-</span>'}</td>
      <td><div class="p-name">${esc(o.product_name || o.listing_name || "")}</div>
        <div class="p-sub">${esc(o.order_key.replace(/^file:/, ""))}${o.seller_code ? ` · ${esc(o.seller_code)}` : ""}</div></td>
      <td class="num">${num(o.quantity)}</td>
      <td><span class="badge ${["CANCELED", "RETURNED", "CANCELED_BY_NOPAYMENT"].includes(o.status) ? "s-delete" : "s-success"}">${esc(o.status_ko || "-")}</span></td>
      <td>${o.listing_id ? `<span class="link-btn">복사본 보기</span><div class="p-sub">원본 #${o.source_id}</div>`
        : `<span class="c-err small">못 맞춤</span><div class="p-sub">이 프로그램이 올린 상품이 아닐 수 있음</div>`}</td></tr>`).join("")
      : `<tr class="empty-row"><td colspan="6">이 기간에 주문이 없습니다. 오른쪽 위 <b>지금 가져오기</b>를 누르세요.</td></tr>`;
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
    $("#o-q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { this.f.q = e.target.value.trim(); reload(); }, 300); });
    $("#o-sync").addEventListener("click", () => App.startTask(App.api("/api/orders/sync", { json: this.f.store_id ? { store_ids: [+this.f.store_id] } : {} })));
    $("#o-file").addEventListener("change", (e) => { if (e.target.files[0]) App.upload("/api/orders/import", e.target.files[0]); e.target.value = ""; });
    $("#o-range").addEventListener("click", () => App.openModal({
      title: "기간 지정해서 주문 가져오기",
      body: `<p class="muted small">고른 기간의 주문을 판매자센터(커머스API)에서 다시 가져옵니다. 이미 있는 주문은 상태만 최신으로 바뀝니다.
        네이버는 하루 단위로 나눠 조회해서 기간이 길면 시간이 걸립니다.</p>
        <div class="two"><label class="field">시작일<input type="date" id="r-from" value="${dayStr(90)}"></label>
        <label class="field">종료일<input type="date" id="r-to" value="${dayStr(0)}"></label></div>
        <label class="field">스토어<select id="r-store"><option value="">모든 스토어</option>${App.stores.map((s) =>
          `<option value="${s.id}">${esc(s.code)} ${esc(s.name)}</option>`).join("")}</select></label>`,
      buttons: [{ label: "취소" }, { label: "가져오기", primary: true, onClick: async (b) => {
        const st = $("#r-store", b).value;
        return !!(await App.startTask(App.api("/api/orders/sync", { json: {
          from: $("#r-from", b).value, to: $("#r-to", b).value, ...(st ? { store_ids: [+st] } : {}) } })));
      } }],
    }));
    $("#o-rows").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-lid]");
      if (tr?.dataset.lid) App.pages.listings.openListing(+tr.dataset.lid);
    });
  },
});
