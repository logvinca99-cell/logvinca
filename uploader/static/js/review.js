/* 눈검수: 검수 대기 원본을 그리드로 깔고, 수상한 것만 클릭해 제외 → Space로 나머지 통과.
   Z: 방금 넘긴 페이지로 돌아가 고치기. 함정 카드(이미 제외한 원본)를 놓치면 그 페이지를 다시 본다. */
"use strict";

App.page("review", {
  async mount(el) {
    this.el = el;
    this.history = [];
    this.busy = false;
    this.onKey = (e) => this.key(e);
    document.addEventListener("keydown", this.onKey);
    const r = await App.api("/api/review/start", { json: {} });
    this.session = r.session;
    this.startedAt = Date.now();
    await this.next();
  },
  unmount() {
    document.removeEventListener("keydown", this.onKey);
    $("#rv-zoom")?.remove();
  },

  async next() {
    const d = await App.api(`/api/review/page?session=${this.session}`);
    this.counts = d.counts;
    this.sess = d.session;
    if (!d.page) return this.finish();
    this.mode = "new";
    this.page = d.page;
    this.cards = d.page.cards;
    this.marks = new Set();
    this.noimg = new Map();   // 이미지 못 불러온 카드: id → 'pass' | 'reject' | undefined(아직)
    this.render();
    d.page.prefetch.forEach((u) => { const im = new Image(); im.referrerPolicy = "no-referrer"; im.src = u; });
  },

  render(note) {
    this.zoom(null);
    const p = this.page, c = this.counts, s = this.sess || {};
    const revisit = this.mode === "revisit";
    this.el.innerHTML = `<div class="page rv-page">
      <header class="page-head"><h1>눈검수</h1>
        <div class="head-actions rv-stat">
          <span>대기 <b>${num(c.wait)}</b></span><span>통과 ${num(c.pass)}</span><span>제외 ${num(c.reject)}</span>
          <span class="muted">이번에 ${num(s.seen || 0)}개 봄</span>
          <span class="muted">${p.has_traps ? "함정 카드 섞임" : "함정 카드 없음 (제외한 원본이 아직 없음)"}</span>
        </div></header>
      ${revisit ? `<div class="notice info"><b>방금 넘긴 페이지를 다시 보는 중</b> · 고친 뒤 Space(또는 아래 버튼)로 저장하면 이어서 검수합니다.</div>` : ""}
      ${note ? `<div class="notice err rv-missed"><b>${note}</b></div>` : ""}
      ${p.cautions?.length ? `<div class="notice warn rv-caution"><b>이 페이지에서 볼 것</b> · ${p.cautions.map(esc).join(" / ")}</div>` : ""}
      <div class="rv-grid ${p.risky ? "big" : ""}">${this.cards.map((x) => this.card(x)).join("")}</div>
      <div class="rv-foot">
        <span class="muted small">클릭: 제외 표시/취소 · <b>Space</b>: 표시 안 한 카드 모두 통과하고 다음 · <b>Z</b>: 방금 넘긴 페이지로 · 마우스를 올리면 크게</span>
        <span><button class="btn" id="rv-back" ${this.history.length && !revisit ? "" : "disabled"}>← 되돌리기 (Z)</button>
        <button class="btn primary" id="rv-next">${revisit ? "고친 판정 저장 (Space)" : `통과 ${this.cards.length - this.marks.size}개 · 제외 ${this.marks.size}개로 다음 (Space)`}</button></span>
      </div>
    </div>`;
    $(".rv-grid", this.el).addEventListener("click", (e) => this.click(e));
    $(".rv-grid", this.el).addEventListener("mouseover", (e) => this.zoom(e));
    $(".rv-grid", this.el).addEventListener("mouseleave", () => this.zoom(null));
    $$(".rv-card img", this.el).forEach((im) => im.addEventListener("error", () => this.imgFail(+im.closest(".rv-card").dataset.id)));
    $("#rv-next").addEventListener("click", () => this.submit());
    $("#rv-back").addEventListener("click", () => this.back());
  },

  card(x) {
    const rej = this.marks.has(x.id);
    const ni = this.noimg.has(x.id);
    return `<div class="rv-card ${rej ? "rej" : ""} ${ni ? "noimg" : ""}" data-id="${x.id}">
      ${ni ? `<div class="rv-noimg"><b>이미지 없음</b><span>${esc(x.name)}</span>
          <div class="rv-pick"><button class="btn ${this.noimg.get(x.id) === "pass" ? "primary" : ""}" data-pick="pass">통과</button>
          <button class="btn ${this.noimg.get(x.id) === "reject" ? "danger" : ""}" data-pick="reject">제외</button></div></div>`
        : `<img src="${esc(x.thumb)}" alt="" referrerpolicy="no-referrer" loading="eager">`}
      <div class="rv-cap"><span class="rv-leaf">${esc(x.leaf)}</span><b>${esc(x.head)}</b></div>
    </div>`;
  },

  imgFail(id) {
    if (this.noimg.has(id)) return;
    this.noimg.set(id, this.marks.has(id) ? "reject" : undefined);
    const el = $(`.rv-card[data-id="${id}"]`, this.el);
    if (el) el.outerHTML = this.card(this.cards.find((c) => c.id === id));
  },

  click(e) {
    const el = e.target.closest(".rv-card");
    if (!el) return;
    const id = +el.dataset.id;
    const pick = e.target.closest("[data-pick]")?.dataset.pick;
    if (this.noimg.has(id)) {
      if (!pick) return;
      this.noimg.set(id, pick);
      pick === "reject" ? this.marks.add(id) : this.marks.delete(id);
    } else {
      this.marks.has(id) ? this.marks.delete(id) : this.marks.add(id);
    }
    el.outerHTML = this.card(this.cards.find((c) => c.id === id));
    $("#rv-next").textContent = this.mode === "revisit" ? "고친 판정 저장 (Space)"
      : `통과 ${this.cards.length - this.marks.size}개 · 제외 ${this.marks.size}개로 다음 (Space)`;
  },

  zoom(e) {
    let z = $("#rv-zoom");
    const el = e && e.target.closest(".rv-card");
    if (!el || el.classList.contains("noimg")) { if (z) z.hidden = true; return; }
    const x = this.cards.find((c) => c.id === +el.dataset.id);
    if (!z) { z = document.createElement("div"); z.id = "rv-zoom"; document.body.appendChild(z); }
    z.innerHTML = `<img src="${esc(x.thumb)}" alt="" referrerpolicy="no-referrer"><p>${esc(x.name)}</p><p class="muted small">${esc(x.category)}</p>`;
    const r = el.getBoundingClientRect();
    z.classList.toggle("left", r.left + r.width / 2 > window.innerWidth / 2);
    z.hidden = false;
  },

  key(e) {
    if (e.target.closest?.("input, textarea, select") || !$("#modal-bg").hidden) return;
    if (e.code === "Space") { e.preventDefault(); this.submit(); }
    if (e.key === "z" || e.key === "Z" || e.key === "ㅋ") { e.preventDefault(); this.back(); }
  },

  async submit() {
    if (this.busy || !this.cards) return;
    const undecided = [...this.noimg].filter(([, v]) => !v).length;
    if (undecided) return App.toast(`이미지 없는 카드 ${undecided}개는 직접 통과/제외를 눌러 주세요`, true);
    this.busy = true;
    this.zoom(null);
    try {
      const rejected = [...this.marks];
      if (this.mode === "revisit") {
        await App.api("/api/review/set", { json: { ids: this.cards.map((c) => c.id), rejected } });
        this.history.pop();
        App.toast("고친 판정을 저장했습니다");
        await this.next();
        return;
      }
      const r = await App.api("/api/review/submit", { json: { page_id: this.page.page_id, rejected } });
      if (!r.ok) {
        // 함정을 놓침 → 저장하지 않고 같은 페이지를 처음부터 다시
        this.marks = new Set();
        this.noimg = new Map();
        this.render(`놓친 상품이 있습니다 (${r.missed}개). 이 페이지의 판정은 저장하지 않았습니다 — 처음부터 다시 봐 주세요.`);
        window.scrollTo(0, 0);
        return;
      }
      this.history.push({ ids: r.ids });  // 함정 카드는 빼고 (되돌린 화면에서 함정 판정이 바뀌지 않게)
      if (this.history.length > 20) this.history.shift();
      window.scrollTo(0, 0);
      await this.next();
    } catch (err) { App.toast(err.message, true); }
    finally { this.busy = false; }
  },

  async back() {
    if (this.busy || this.mode === "revisit" || !this.history.length) return;
    const h = this.history[this.history.length - 1];
    const cards = await App.api("/api/review/cards", { json: { ids: h.ids } });
    this.mode = "revisit";
    this.cards = cards;
    this.marks = new Set(cards.filter((c) => c.review === "reject").map((c) => c.id));
    this.noimg = new Map();
    this.page = { ...this.page, cautions: [], page_id: null };
    this.render();
  },

  async finish() {
    const s = this.sess || {};
    this.cards = null;
    const live = await App.api("/api/review/live-reject");
    this.el.innerHTML = `<div class="page">
      <header class="page-head"><h1>눈검수</h1></header>
      <section class="card pad">
        <h2>검수 대기 원본이 없습니다 ✓</h2>
        <div class="kw-stats">
          <div><b>${num(s.seen || 0)}</b><span>이번에 본 원본</span></div>
          <div><b>${num(s.passed || 0)}</b><span>통과</span></div>
          <div><b>${num(s.rejected || 0)}</b><span>제외</span></div>
          <div><b>${s.traps ? `${num(s.trap_hits)} / ${num(s.traps)}` : "—"}</b><span>함정 카드 잡음${s.missed_pages ? ` · 놓쳐서 다시 본 페이지 ${s.missed_pages}` : ""}</span></div>
          <div><b>${fmtDur(s.seconds || 0)}</b><span>걸린 시간</span></div>
        </div>
        <p class="muted small">전체: 통과 ${num(this.counts.pass)} · 제외 ${num(this.counts.reject)}. 통과한 원본만 다른 스토어로 복사·등록할 수 있습니다.</p>
        <button class="btn" id="rv-rejected">제외한 상품 다시 보기</button>
      </section>
      ${live.length ? `<section class="card pad"><div class="sec-head"><h2>제외됐는데 판매 중인 복사본 ${num(live.length)}개</h2>
          <button class="btn primary" id="rv-takedown">제외된 판매 중 상품 내리기</button></div>
        <p class="muted small">내리기 예약 뒤 복사본 화면에서 실행합니다. 판매 이력이 있어 잠긴 것(${num(live.filter((l) => l.locked).length)}개)은 내리지 않으니 직접 확인하세요.</p>
        <div class="tm-wrap"><table class="opt-table"><tr><th>스토어</th><th>상품명</th><th>상태</th></tr>
        ${live.map((l) => `<tr><td>${esc(l.store_name)}</td><td>${esc(l.name)}</td><td>${l.locked ? `<span class="flag lock">잠금</span> ${esc(l.lock_note)}` : STATUS[l.status] || l.status}</td></tr>`).join("")}</table></div></section>` : ""}
      <div id="rv-rej"></div>
    </div>`;
    $("#rv-rejected").addEventListener("click", () => this.rejected(0));
    $("#rv-takedown")?.addEventListener("click", async () => {
      try {
        const r = await App.api("/api/review/live-reject/delete", { json: {} });
        App.toast(`내리기 예약 ${num(r.count)}건${r.skipped ? ` · 잠금이라 뺀 것 ${num(r.skipped)}건` : ""} · 복사본 화면에서 실행하세요`);
      } catch (e) { App.toast(e.message, true); }
    });
  },

  /* 제외한 상품 다시 보기: 실수로 제외한 것을 클릭해 통과로 되살림 (오탐 복구) */
  async rejected(page) {
    const d = await App.api(`/api/review/rejected?page=${page}`);
    const back = new Set();
    const box = $("#rv-rej");
    box.innerHTML = `<section class="card pad"><div class="sec-head"><h2>제외한 상품 ${num(d.total)}개</h2>
        <span><span class="muted small">통과로 되살릴 것을 클릭 → 저장</span> <button class="btn primary" id="rv-restore">저장</button></span></div>
      <div class="rv-grid">${d.cards.map((x) => `<div class="rv-card rej" data-id="${x.id}"><img src="${esc(x.thumb)}" alt="" referrerpolicy="no-referrer">
        <div class="rv-cap"><span class="rv-leaf">${esc(x.leaf)}</span><b>${esc(x.head)}</b></div></div>`).join("")}</div>
      <div id="rv-rej-pager"></div></section>`;
    $(".rv-grid", box).addEventListener("click", (e) => {
      const el = e.target.closest(".rv-card");
      if (!el) return;
      const id = +el.dataset.id;
      back.has(id) ? back.delete(id) : back.add(id);
      el.classList.toggle("rej", !back.has(id));
      el.classList.toggle("revived", back.has(id));
    });
    $("#rv-restore", box).addEventListener("click", async () => {
      if (!back.size) return App.toast("되살릴 상품을 클릭해 주세요");
      await App.api("/api/review/set", { json: { ids: [...back], rejected: [] } });
      App.toast(`${back.size}개를 통과로 되살렸습니다`);
      this.rejected(page);
    });
    App.pager($("#rv-rej-pager"), { page, size: 48, total: d.total, onPage: (p) => this.rejected(p) });
  },
});

function fmtDur(sec) {
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}시간 ${m}분` : m ? `${m}분 ${s}초` : `${s}초`;
}
