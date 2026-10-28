/* 구글 메일함: 네이버가 보낸 메일(경고·제재, 주문·문의, 인증번호)을 스토어별로 */
"use strict";

const MAIL_KIND = { warn: ["경고·제재", "c-err"], order: ["주문·문의", ""], auth: ["인증번호", "c-run"], etc: ["기타", "muted"] };

App.page("mail", {
  f: { kind: "", store_id: "", q: "", handled: "", page: 0 },

  async mount(el) {
    const s = App.state.settings;
    const stores = App.stores || await App.loadStores();
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>메일함</h1>
        <div class="head-actions"><button class="btn primary" id="m-fetch">지금 가져오기</button></div></header>
      ${s.gmail_user && s.has_gmail_app_password ? `<p class="muted small" style="margin:0">${esc(s.gmail_user)} · 보낸 사람에 '${esc(s.mail_from || "naver")}'이 들어간 최근 ${num(s.mail_days || 7)}일 메일 ·
          ${+s.mail_auto_minutes ? `${num(s.mail_auto_minutes)}분마다 자동으로 가져옴` : "자동 가져오기 꺼짐"} (<a href="#settings?tab=keys">설정</a>)</p>`
        : `<div class="notice warn">지메일이 연결되지 않았습니다. <a href="#settings?tab=keys">설정 → API 키 → 구글 메일함</a>에 지메일 주소와 앱 비밀번호(16자리)를 넣으세요.</div>`}
      <div class="tiles" id="m-tiles"></div>
      <div class="filters-row">
        <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
          <input id="m-q" placeholder="제목·내용·상품번호 검색"></div>
        <select id="m-store" class="sel"><option value="">모든 스토어</option>${stores.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select>
        <select id="m-handled" class="sel"><option value="">확인 여부 전체</option><option value="0">아직 확인 안 함</option><option value="1">확인함</option></select>
        <div id="m-pager" class="pager"></div>
      </div>
      <div class="card table-card" id="m-box"></div>
    </div>`;
    const f = this.f;
    $("#m-store").value = f.store_id;
    $("#m-handled").value = f.handled;
    $("#m-q").value = f.q;
    $("#m-store").addEventListener("change", (e) => { f.store_id = e.target.value; f.page = 0; this.load(); });
    $("#m-handled").addEventListener("change", (e) => { f.handled = e.target.value; f.page = 0; this.load(); });
    let tq;
    $("#m-q").addEventListener("input", (e) => { clearTimeout(tq); tq = setTimeout(() => { f.q = e.target.value.trim(); f.page = 0; this.load(); }, 300); });
    $("#m-tiles").addEventListener("click", (e) => { const t = e.target.closest("[data-filter]"); if (t) { f.kind = t.dataset.filter; f.page = 0; this.load(); } });
    $("#m-fetch").addEventListener("click", () => App.startTask(App.api("/api/mails/fetch", { json: {} })));
    $("#m-box").addEventListener("change", async (e) => {
      const c = e.target.closest("[data-handled]");
      if (!c) return;
      try { await App.api(`/api/mails/${c.dataset.handled}/handled`, { json: { handled: c.checked } }); App.refreshState(); this.load(); }
      catch (err) { App.toast(err.message, true); }
    });
    await this.load();
    this.onDone = (t) => { if (t.kind === "mail") this.load(); };
    App.on("task-done", this.onDone);
  },
  unmount() { if (this.onDone) App.off("task-done", this.onDone); },

  async load() {
    const f = this.f, size = 100;
    const d = await App.api(`/api/mails?${new URLSearchParams({ kind: f.kind, store_id: f.store_id, q: f.q, handled: f.handled, page: f.page + 1, size })}`);
    const c = d.counts;
    $("#m-tiles").innerHTML = tilesHtml([
      { key: "", label: "전체", dot: "var(--muted)" },
      { key: "warn", label: `경고·제재${c.warn_open ? ` · 확인 안 함 ${num(c.warn_open)}` : ""}`, dot: "var(--err)" },
      { key: "order", label: "주문·문의", dot: "var(--accent)" },
      { key: "auth", label: "인증번호", dot: "var(--info)" },
      { key: "etc", label: "기타", dot: "var(--line)" },
    ], { "": Object.entries(c).filter(([k]) => k !== "warn_open").reduce((a, [, v]) => a + v, 0), ...c }, f.kind);
    const stores = Object.fromEntries((App.stores || []).map((s) => [s.id, s]));
    $("#m-box").innerHTML = `<table class="grid"><thead><tr><th class="w-when">받은 시각</th><th>종류</th><th>스토어</th><th>제목 · 내용</th><th>관련 상품</th><th>확인함</th></tr></thead>
      <tbody>${d.rows.length ? d.rows.map((m) => {
        const [kl, kc] = MAIL_KIND[m.kind] || [m.kind, ""];
        const st = stores[m.store_id];
        return `<tr class="${m.kind === "warn" && !m.handled ? "row-warn" : ""}"><td class="nowrap">${stamp(m.received_at)}</td>
          <td class="nowrap ${kc}"><b>${kl}</b>${m.code ? `<div class="mail-code">${esc(m.code)}</div>` : ""}</td>
          <td class="small">${st ? esc(st.name) : '<span class="muted">모름</span>'}</td>
          <td><b>${esc(m.subject)}</b><div class="muted small mail-snip">${esc(m.snippet)}</div></td>
          <td class="small">${m.products.map((p) => p.listing_id
            ? `<div><a href="#listings?store_id=${p.store_id}&q=${encodeURIComponent(p.origin_no)}">${esc(p.no)}</a> ${esc(p.name)}
                · ${sellerLink(stores[p.store_id], `https://sell.smartstore.naver.com/#/products/edit/${p.origin_no}`, "판매자센터")}</div>`
            : `<div class="muted">${esc(p.no)} (복사본에 없음)</div>`).join("")}</td>
          <td><input type="checkbox" data-handled="${m.id}" ${m.handled ? "checked" : ""} title="처리했으면 체크"></td></tr>`;
      }).join("") : `<tr class="empty-row"><td colspan="6">메일이 없습니다. '지금 가져오기'를 누르세요.</td></tr>`}</tbody></table>`;
    App.pager($("#m-pager"), { page: f.page, size, total: d.total, onPage: (p) => { f.page = p; this.load(); } });
  },
});
