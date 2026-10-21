/* 휴지통: 지운 원본·복사본. 되살리거나 완전히 지운다 */
"use strict";

App.page("trash", {
  async mount(el, params) {
    this.kind = params.kind === "listing" ? "listing" : "source";
    this.q = "";
    this.page = 0;
    this.size = App.pageSize("trash");
    this.sel = new Set();
    this.selAll = false;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>휴지통</h1>
        <div class="head-actions"><button class="btn danger" id="t-empty">휴지통 비우기</button></div></header>
      <p class="muted" style="margin:0">지운 원본·복사본이 여기 모입니다. <b>되살리기</b>를 누르면 원래 자리로 돌아가고, <b>완전히 삭제</b>하면 되돌릴 수 없습니다.</p>
      <div class="tiles" id="t-tiles"></div>
      <div class="filters-row"><div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
        <input id="t-q" placeholder="상품명·스토어·번호 검색"></div></div>
      <div class="listbar" id="t-bar"></div>
      <div class="card table-card"><table class="grid"><thead><tr><th class="w-check"></th><th>상품명</th><th class="w-store">스토어</th>
        <th class="w-round">내용</th><th class="w-round">지운 때</th></tr></thead><tbody id="t-rows"></tbody></table>
        <div class="pg-foot"><div class="pg" id="t-pager"></div></div></div>
    </div>`;
    $("#t-tiles").addEventListener("click", (e) => {
      const t = e.target.closest("[data-filter]");
      if (t) { this.kind = t.dataset.filter; this.page = 0; this.clear(); this.load(); }
    });
    let timer;
    $("#t-q").addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => { this.q = e.target.value.trim(); this.page = 0; this.clear(); this.load(); }, 300); });
    $("#t-rows").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (!tr || this.selAll) return;
      const id = +tr.dataset.id;
      this.sel.has(id) ? this.sel.delete(id) : this.sel.add(id);
      tr.classList.toggle("sel", this.sel.has(id));
      $("input", tr).checked = this.sel.has(id);
      this.renderBar();
    });
    $("#t-empty").addEventListener("click", async () => {
      const c = this.counts || {};
      const ok = await App.confirmDanger({ title: "휴지통 비우기",
        body: `<p>휴지통의 원본 <b>${num(c.source)}개</b>와 복사본 <b>${num(c.listing)}건</b>을 <b>완전히 삭제</b>합니다. 되돌릴 수 없습니다.</p>` });
      if (!ok) return;
      const r = await App.api("/api/trash/purge", { json: { empty: true } });
      App.toast(`${num(r.purged)}개를 완전히 삭제했습니다`);
      this.clear(); this.load(); App.refreshState();
    });
    await this.load();
  },

  clear() { this.sel.clear(); this.selAll = false; },
  target() { return this.selAll ? { all: true, kind: this.kind, q: this.q } : { ids: [...this.sel] }; },

  async load() {
    const qs = new URLSearchParams({ kind: this.kind, q: this.q, page: this.page, size: this.size });
    const r = await App.api(`/api/trash?${qs}`);
    this.rows = r.rows; this.total = r.total; this.counts = r.counts;
    $("#t-tiles").innerHTML = tilesHtml([{ key: "source", label: "원본", dot: "var(--info)" }, { key: "listing", label: "복사본", dot: "var(--ok)" }],
      r.counts, this.kind);
    $("#t-rows").innerHTML = r.rows.length ? r.rows.map((x) => {
      const on = this.selAll || this.sel.has(x.id);
      return `<tr data-id="${x.id}" class="${on ? "sel" : ""}"><td class="w-check"><input type="checkbox" ${on ? "checked" : ""} ${this.selAll ? "disabled" : ""}></td>
        <td><div class="p-name">${esc(x.title)}</div><div class="p-sub">${x.kind === "source" ? "원본" : "복사본"} #${x.ref_id}</div></td>
        <td>${esc(x.store || "-")}</td><td class="muted small">${esc(x.extra)}</td><td>${when(x.deleted_at)}</td></tr>`;
    }).join("") : `<tr class="empty-row"><td colspan="5">휴지통이 비어 있습니다.</td></tr>`;
    this.renderBar();
  },

  renderBar() {
    const n = this.selAll ? this.total : this.sel.size;
    const unit = this.kind === "source" ? "개" : "건";
    const opts = { page: this.page, size: this.size, total: this.total, unit,
      onPage: (p) => { this.page = p; this.load(); }, onSize: (s) => { this.size = s; App.savePageSize("trash", s); this.page = 0; this.load(); } };
    App.listBar($("#t-bar"), {
      ...opts, count: n, selAll: this.selAll, what: "항목",
      pageChecked: this.rows.length > 0 && this.rows.every((x) => this.sel.has(x.id)),
      actions: [{ id: "restore", label: "되살리기", primary: true }, "|", { id: "purge", label: "완전히 삭제", danger: true }],
      onPageCheck: (on) => { this.selAll = false; this.rows.forEach((x) => (on ? this.sel.add(x.id) : this.sel.delete(x.id))); this.load(); },
      onAll: () => { this.selAll = true; this.sel.clear(); this.load(); },
      onClear: () => { this.clear(); this.load(); },
      onAction: async (id) => {
        if (id === "restore") {
          try {
            const r = await App.api("/api/trash/restore", { json: this.target() });
            App.toast(`${num(r.restored)}개를 되살렸습니다` + (r.skipped ? ` · 되살리지 못한 ${num(r.skipped)}개 (${r.reasons[0] || ""})` : ""));
          } catch (e) { return App.toast(e.message, true); }
        }
        if (id === "purge") {
          const ok = await App.confirmDanger({ title: `${num(n)}${unit} 완전히 삭제`,
            body: `<p>고른 <b>${num(n)}${unit}</b>를 <b>완전히 삭제</b>합니다. 되돌릴 수 없습니다.</p>` });
          if (!ok) return;
          const r = await App.api("/api/trash/purge", { json: this.target() });
          App.toast(`${num(r.purged)}개를 완전히 삭제했습니다`);
        }
        this.clear(); this.load(); App.refreshState();
      },
    });
    App.pagerBar($("#t-pager"), opts);
  },
});
