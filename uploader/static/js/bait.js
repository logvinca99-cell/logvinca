/* 도둑방지: 높인 가격으로 올라가 있는 복사본 → 직접 골라 원래 가격으로. 워터마크 미리보기 */
"use strict";

App.page("bait", {
  async mount(el) {
    this.el = el;
    this.sel = new Set();
    this.onDone = (t) => { if (t.kind === "bait") this.load(); };
    App.on("task-done", this.onDone);
    await this.load();
  },
  unmount() { App.off("task-done", this.onDone); },

  async load() {
    const d = await App.api("/api/bait");
    const s = App.state.settings, st = d.stats;
    this.rows = d.on;
    this.sel = new Set([...this.sel].filter((id) => d.on.some((l) => l.id === id)));
    this.el.innerHTML = `<div class="page">
      <header class="page-head"><h1>도둑방지</h1>
        <div class="head-actions">
          <button class="btn" id="b-sel" disabled>고른 것 원래 가격으로</button>
          <button class="btn primary" id="b-all" ${d.on.length ? "" : "disabled"}>전부 원래 가격으로 (${num(d.on.length)})</button></div></header>

      <section class="card pad">
        <div class="kw-stats">
          <div><b>${num(st.on)}</b><span>지금 높인 가격</span></div>
          <div><b>${num(st.restored)}</b><span>원래 가격으로 되돌림</span></div>
          <div><b class="${st.failed ? "c-err" : ""}">${num(st.failed)}</b><span>되돌리기 실패</span></div>
        </div>
        <ul class="muted small bait-how">
          <li>등록 계획(다른 스토어로 복사) 창의 <b>'도둑방지로 올리기'</b>가 기본으로 켜져 있습니다. 켜면 처음 올릴 때 판매가에 <b>+${num(s.bait_amount)}원</b>을 더해 올립니다${s.bait_on_refresh ? " (최신화 때도)" : " (최신화 때는 원래 가격)"}.</li>
          <li>할인 금액은 도둑방지 전 가격으로 계산합니다. 원래 가격으로 되돌리면 할인·마진이 처음 정한 그대로가 됩니다. 가격은 모두 100원 단위 올림.</li>
          <li>원래 가격으로는 여기나 복사본 화면('도둑방지 가격' 칸)에서 직접 되돌립니다.</li>
        </ul>
      </section>

      <section class="card">
        ${d.on.length ? `<table class="grid"><thead><tr><th class="w-check"><input type="checkbox" id="b-check-all"></th><th>스토어</th><th>상품명</th>
          <th class="num">네이버 가격</th><th class="num">원래 가격</th><th>올린 날</th><th class="num">판매</th></tr></thead><tbody>
          ${d.on.map((l) => `<tr data-id="${l.id}" class="${this.sel.has(l.id) ? "sel" : ""}"><td class="w-check" data-stop><input type="checkbox" ${this.sel.has(l.id) ? "checked" : ""}></td>
            <td>${esc(l.store_name)}</td><td><div class="p-name">${esc(l.name)}</div>${l.bait_state === "fail" ? `<div class="s-msg err">${esc(l.bait_note)}</div>` : ""}</td>
            <td class="num">${num(l.price + l.bait)}원</td><td class="num">${num(l.price)}원</td><td>${ymd(l.registered_at)} <span class="muted small">(${age(l.registered_at)})</span></td>
            <td class="num">${l.sold_count ? num(l.sold_count) : ""}</td></tr>`).join("")}
        </tbody></table>` : `<p class="muted pad">높인 가격으로 올라가 있는 복사본이 없습니다.</p>`}
      </section>

      <section class="card pad">
        <div class="sec-head"><h2>대표 이미지 워터마크</h2><span class="muted small">${s.wm_enabled ? "켜짐" : "꺼짐"} · 스토어마다 로고나 글자는 <a href="#stores">스토어</a> 화면에서 · 위치·크기는 <a href="#settings">설정 → 워터마크</a></span></div>
        <div class="wm-previews">
          ${[[1000, 1000, "정사각형"], [1000, 1400, "세로로 긴 이미지"], [1400, 1000, "가로로 긴 이미지"]].map(([w, h, t]) =>
            `<figure><img src="/api/watermark/preview?w=${w}&h=${h}&_=${Date.now()}" alt="${t} 워터마크 미리보기"><figcaption>${t} ${w}×${h}</figcaption></figure>`).join("")}
        </div>
        <p class="muted small">초록 테두리 = 네이버 목록에서 잘려 보이는 가운데 정사각형. 직사각형도 이 안쪽 모서리에 넣으므로 잘려도 워터마크가 보입니다
          ('흰 여백으로 정사각형 만들기'를 고르면 상품이 잘리지 않게 여백을 붙인 뒤 넣음). 워터마크를 넣은 이미지는 스토어마다 따로 올라갑니다.</p>
      </section>
    </div>`;
    const upd = () => { $("#b-sel").disabled = !this.sel.size; $("#b-sel").textContent = `고른 것 원래 가격으로${this.sel.size ? ` (${num(this.sel.size)})` : ""}`; };
    upd();
    $("#b-all").addEventListener("click", () => {
      if (confirm(`높인 가격으로 올라가 있는 ${d.on.length}건을 모두 원래 가격으로 되돌릴까요?`))
        App.startTask(App.api("/api/bait/restore", { json: { all: true } }));
    });
    $("#b-sel").addEventListener("click", () => App.startTask(App.api("/api/bait/restore", { json: { ids: [...this.sel] } })));
    $("#b-check-all")?.addEventListener("change", (e) => {
      d.on.forEach((l) => (e.target.checked ? this.sel.add(l.id) : this.sel.delete(l.id)));
      $$("tbody tr", this.el).forEach((tr) => { tr.classList.toggle("sel", e.target.checked); $("input", tr).checked = e.target.checked; });
      upd();
    });
    $("tbody", this.el)?.addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (!tr) return;
      const id = +tr.dataset.id;
      if (e.target.closest("[data-stop]")) {
        this.sel.has(id) ? this.sel.delete(id) : this.sel.add(id);
        tr.classList.toggle("sel", this.sel.has(id));
        $("input", tr).checked = this.sel.has(id);
        upd();
        return;
      }
      App.pages.listings.openListing(id);
    });
  },
});
