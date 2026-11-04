/* 눈검수: 복사본 화면에서 썸네일만 그리드로 (인스타그램처럼) 보며 빠르게 걸러 냄.
   클릭 = 고르기 (Shift+클릭 = 범위) · 마우스 올리기 = 크게 · 우클릭 = 상품명 · ←/→ = 쪽 이동
   다음 쪽으로 넘어가면 지금 쪽은 '눈검수 완료'(원본 기준 — 다른 스토어 복사본도 본 것으로). 고른 것은 삭제 (기본: 원본까지 같이). */
"use strict";

const EYE_SIZES = [[24, 4, "크게"], [48, 6, "보통"], [96, 8, "작게"], [150, 10, "아주 작게"], [240, 12, "한눈에"]];

/* 그리드용 작은 썸네일 주소 (네이버 이미지는 크기 지정, 안 되면 원래 주소로) */
function eyeThumb(url, cols) {
  if (!/^https?:\/\/[^/]*pstatic\.net\//i.test(url || "") || url.includes("?")) return url;
  return `${url}?type=${cols <= 6 ? "m510" : "f300"}`;
}

const Eye = {
  open({ storeId, storeName, filter, after }) {
    this.storeId = storeId;
    this.storeName = storeName;
    this.baseFilter = { ...filter };
    this.after = after;
    this.page = 0;
    this.sel = new Map();      // 복사본 번호 → 줄 (쪽을 넘겨도 남음)
    this.last = null;          // Shift+클릭 범위 시작
    this.deleted = 0;
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem("eye") || "{}"); } catch (e) { /* 무시 */ }
    this.size = EYE_SIZES.some((s) => s[0] === saved.size) ? saved.size : 48;
    this.todo = !!saved.todo;
    this.scope = "store";
    this.render();
    this.load();
  },

  save() { try { localStorage.setItem("eye", JSON.stringify({ size: this.size, todo: this.todo })); } catch (e) { /* 무시 */ } },
  cols() { return (EYE_SIZES.find((s) => s[0] === this.size) || EYE_SIZES[1])[1]; },

  filter() {
    const f = this.scope === "filter" ? { ...this.baseFilter } : { store_id: this.storeId, status: "active" };
    if (!f.status || f.status === "all") f.status = "active";   // 내린 복사본은 볼 필요 없음
    if (this.todo) f.eye = "todo";
    f.store_id = this.storeId;
    return f;
  },

  render() {
    document.body.classList.add("eye-open");
    let el = $("#eye");
    if (!el) { el = document.createElement("div"); el.id = "eye"; el.className = "eye"; document.body.appendChild(el); }
    el.hidden = false;
    const scoped = Object.keys(this.baseFilter).some((k) => !["store_id", "status", "page", "size"].includes(k) && this.baseFilter[k] !== "")
      || (this.baseFilter.status && !["all", "active"].includes(this.baseFilter.status));
    el.innerHTML = `
      <div class="eye-top">
        <div class="eye-title"><b>눈검수</b> <span class="muted">${esc(this.storeName || "")}</span></div>
        <select id="eye-scope" class="sel" title="볼 범위">
          <option value="store">이 스토어 복사본 전체 (내림 제외)</option>
          ${scoped ? '<option value="filter">복사본 화면에서 거른 조건만</option>' : ""}</select>
        <label class="check small"><input type="checkbox" id="eye-todo" ${this.todo ? "checked" : ""}><span>눈검수 안 한 것만</span></label>
        <select id="eye-size" class="sel" title="한 쪽에 몇 장씩">${EYE_SIZES.map(([n, c, l]) => `<option value="${n}" ${n === this.size ? "selected" : ""}>${l} · ${n}장 (${c}열)</option>`).join("")}</select>
        <div class="eye-pg"><button class="btn sm" id="eye-prev" title="이전 쪽 (←)">‹ 이전</button>
          <span id="eye-pno" class="nowrap"></span>
          <button class="btn sm primary" id="eye-next" title="이 쪽을 눈검수 완료로 하고 다음 쪽 (→)">다음 ›</button></div>
        <div class="eye-acts"><span id="eye-seln" class="nowrap"></span>
          <button class="btn sm" id="eye-pageall" title="이 쪽 전부 고르기/빼기">이 쪽 전부</button>
          <button class="btn sm" id="eye-clear">고른 것 비우기</button>
          <button class="btn sm danger" id="eye-del">고른 것 삭제</button>
          <button class="btn sm ghost" id="eye-close" title="닫기 (Esc)">✕ 닫기</button></div>
      </div>
      <div class="eye-strip" id="eye-strip"></div>
      <div class="eye-body"><div id="eye-banner"></div><div class="eye-grid" id="eye-grid"></div>
        <div class="eye-bottom"><span class="muted small">클릭: 고르기 · Shift+클릭: 범위로 고르기 · 마우스 올리기: 크게 · 우클릭: 상품명 · ← →: 쪽 이동 · Esc: 닫기</span>
          <button class="btn primary" id="eye-next2">이 쪽 눈검수 완료 · 다음 ›</button></div></div>
      <div class="eye-zoom" id="eye-zoom" hidden><img alt="" referrerpolicy="no-referrer"></div>
      <div class="eye-card" id="eye-card" hidden></div>`;
    $("#eye-scope").value = this.scope;
    $("#eye-scope").addEventListener("change", (e) => { this.scope = e.target.value; this.page = 0; this.load(); });
    $("#eye-todo").addEventListener("change", (e) => { this.todo = e.target.checked; this.save(); this.page = 0; this.load(); });
    $("#eye-size").addEventListener("change", (e) => {
      const first = this.page * this.size;   // 보던 자리 근처로
      this.size = +e.target.value; this.save(); this.page = Math.floor(first / this.size); this.load();
    });
    $("#eye-prev").addEventListener("click", () => this.go(this.page - 1));
    $("#eye-next").addEventListener("click", () => this.next());
    $("#eye-next2").addEventListener("click", () => this.next());
    $("#eye-close").addEventListener("click", () => this.close());
    $("#eye-clear").addEventListener("click", () => { this.sel.clear(); this.paintSel(); });
    $("#eye-pageall").addEventListener("click", () => {
      const all = this.rows.every((l) => this.sel.has(l.id));
      this.rows.forEach((l) => (all ? this.sel.delete(l.id) : this.sel.set(l.id, l)));
      this.paintSel();
    });
    $("#eye-del").addEventListener("click", () => this.remove());
    $("#eye-strip").addEventListener("click", (e) => { const b = e.target.closest("[data-pg]"); if (b) this.go(+b.dataset.pg); });
    const grid = $("#eye-grid");
    grid.addEventListener("click", (e) => {
      const t = e.target.closest("[data-i]");
      if (!t) return;
      this.hideCard();
      const i = +t.dataset.i;
      if (e.shiftKey && this.last != null) {
        const [a, b] = [Math.min(this.last, i), Math.max(this.last, i)];
        const on = !this.sel.has(this.rows[i].id);
        for (let k = a; k <= b; k++) on ? this.sel.set(this.rows[k].id, this.rows[k]) : this.sel.delete(this.rows[k].id);
      } else {
        const l = this.rows[i];
        this.sel.has(l.id) ? this.sel.delete(l.id) : this.sel.set(l.id, l);
      }
      this.last = i;
      this.paintSel();
    });
    grid.addEventListener("contextmenu", (e) => {
      const t = e.target.closest("[data-i]");
      if (!t) return;
      e.preventDefault();
      this.showCard(this.rows[+t.dataset.i], e.clientX, e.clientY);
    });
    grid.addEventListener("mouseover", (e) => {
      const t = e.target.closest("[data-i]");
      clearTimeout(this._zt);
      if (!t) return;
      this._zt = setTimeout(() => this.zoom(t), 140);
    });
    grid.addEventListener("mouseleave", () => { clearTimeout(this._zt); $("#eye-zoom").hidden = true; });
    $(".eye-body").addEventListener("scroll", () => { $("#eye-zoom").hidden = true; this.hideCard(); }, { passive: true });
    this._key = (e) => {
      if (!$("#modal-bg").hidden) return;   // 삭제 확인 창이 떠 있으면 그쪽
      if (e.target.matches?.("input, select, textarea")) return;
      if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); if (!$("#eye-card").hidden) this.hideCard(); else this.close(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); this.next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); this.go(this.page - 1); }
    };
    document.addEventListener("keydown", this._key, true);
    this._out = (e) => { if (!e.target.closest?.("#eye-card")) this.hideCard(); };
    document.addEventListener("mousedown", this._out, true);
  },

  async load() {
    const f = this.filter();
    const qs = new URLSearchParams({ ...f, page: this.page, size: this.size });
    let res, pg;
    try {
      [res, pg] = await Promise.all([App.api(`/api/listings?${qs}`), App.api(`/api/eye/pages?${new URLSearchParams({ ...f, size: this.size })}`)]);
    } catch (e) { return App.toast(e.message, true); }
    this.pages = pg.pages;
    const last = Math.max(0, pg.pages.length - 1);
    if (this.page > last) { this.page = last; return this.load(); }
    this.rows = res.rows;
    this.total = res.total;
    this.reviewed = pg.reviewed;
    this.last = null;
    const cols = this.cols();
    const grid = $("#eye-grid");
    grid.style.setProperty("--cols", cols);
    grid.className = `eye-grid c${cols}`;
    grid.innerHTML = this.rows.length ? this.rows.map((l, i) => {
      const gone = l.op === "delete" && ["planned", "queued", "running"].includes(l.status);
      return `<div class="eye-tile ${gone || l.drop_pending ? "gone" : ""}" data-i="${i}" data-id="${l.id}">
        <img loading="lazy" referrerpolicy="no-referrer" src="${esc(eyeThumb(l.thumb, cols))}" data-full="${esc(l.thumb)}" alt=""
          onerror="if(this.dataset.full&&this.src!==this.dataset.full){this.src=this.dataset.full}else{this.classList.add('broken')}">
        ${l.eye_at ? '<span class="eye-seen" title="눈검수 한 원본">✓</span>' : ""}
        ${gone || l.drop_pending ? '<span class="eye-tag">내리는 중</span>' : l.origin_no ? "" : '<span class="eye-tag off">안 올림</span>'}
        <span class="eye-check">✓</span></div>`;
    }).join("") : `<p class="muted pad">${this.todo ? "눈검수 안 한 복사본이 없습니다. 다 봤습니다." : "복사본이 없습니다."}</p>`;
    this.paintSel();
    this.paintPages();
    $(".eye-body").scrollTop = 0;
  },

  paintPages() {
    const n = this.pages.length;
    const done = this.pages.filter((p) => p === 2).length;
    $("#eye-pno").innerHTML = n ? `<b>${num(this.page + 1)}</b> / ${num(n)}쪽` : "0쪽";
    $("#eye-prev").disabled = this.page <= 0;
    const lastPage = this.page >= n - 1;
    $("#eye-next").textContent = lastPage ? "이 쪽 완료" : "다음 ›";
    $("#eye-next2").textContent = lastPage ? "이 쪽 눈검수 완료" : "이 쪽 눈검수 완료 · 다음 ›";
    $("#eye-next").disabled = $("#eye-next2").disabled = !this.rows.length;
    $("#eye-strip").innerHTML = `<span class="small">눈검수 완료 <b>${num(done)}</b> / ${num(n)}쪽 · 복사본 ${num(this.reviewed)} / ${num(this.total)}건${this.todo ? " (안 한 것만 보는 중)" : ""}</span>
      <div class="eye-pages">${this.pages.map((p, i) => `<button class="eye-pgdot s${p} ${i === this.page ? "on" : ""}" data-pg="${i}" title="${i + 1}쪽 · ${["안 봄", "일부 봄", "눈검수 완료"][p]}">${n <= 60 ? i + 1 : ""}</button>`).join("")}</div>`;
    const cur = this.pages[this.page];
    $("#eye-banner").innerHTML = cur === 2 && !this.todo ? `<div class="eye-done">✓ 이 쪽은 눈검수 완료</div>` : "";
  },

  paintSel() {
    $$("#eye-grid .eye-tile").forEach((t) => t.classList.toggle("on", this.sel.has(+t.dataset.id)));
    const n = this.sel.size;
    $("#eye-seln").innerHTML = n ? `고름 <b>${num(n)}</b>개` : '<span class="muted">고른 것 없음</span>';
    $("#eye-del").disabled = !n;
    $("#eye-clear").disabled = !n;
  },

  async mark() {
    const ids = this.rows.map((l) => l.id);
    if (!ids.length) return;
    try { await App.api("/api/eye/mark", { json: { ids } }); } catch (e) { App.toast(e.message, true); }
  },

  /* 다음 쪽: 지금 쪽을 눈검수 완료로. '안 한 것만'이면 본 것이 빠지므로 같은 자리에서 다시 */
  async next() {
    if (!this.rows?.length) return;
    await this.mark();
    const lastPage = this.page >= this.pages.length - 1;
    if (!this.todo && !lastPage) this.page += 1;
    if (lastPage && !this.todo) App.toast("마지막 쪽까지 눈검수 완료했습니다");
    this.load();
  },

  go(p) {
    if (p < 0 || p >= this.pages.length || p === this.page) return;
    if (p > this.page && !this.todo) { this.mark().then(() => { this.page = p; this.load(); }); return; }   // 앞으로 건너뛰면 지금 쪽은 완료
    this.page = p;
    this.load();
  },

  zoom(t) {
    const im = $("img", t);
    if (!im || im.classList.contains("broken") || !$("#eye-card").hidden) return;   // 상품명 카드가 떠 있으면 확대 안 함
    const z = $("#eye-zoom");
    $("img", z).src = im.dataset.full || im.src;
    const r = t.getBoundingClientRect();
    const W = Math.min(480, innerWidth - 24, innerHeight - 24);
    z.style.width = z.style.height = `${W}px`;
    const left = r.right + 10 + W < innerWidth ? r.right + 10 : r.left - W - 10 > 0 ? r.left - W - 10 : Math.max(8, innerWidth - W - 8);
    z.style.left = `${left}px`;
    z.style.top = `${Math.max(8, Math.min(innerHeight - W - 8, r.top + r.height / 2 - W / 2))}px`;
    z.hidden = false;
  },

  showCard(l, x, y) {
    $("#eye-zoom").hidden = true;
    const c = $("#eye-card");
    const named = !!l.name_id || !!l.origin_no;
    c.innerHTML = `<div class="eye-card-name">${esc(l.name)}</div>
      ${named && l.source_name && l.source_name !== l.name ? `<div class="small muted">원본: ${esc(l.source_name)}</div>` : ""}
      ${!named ? '<div class="small c-err">상품명 변경 전 (원본 이름 그대로)</div>' : ""}
      <div class="small" style="margin-top:6px">${statusBadge(l.status, l.op)} ${esc(l.seller_code || "")} · 원본 #${l.source_id} · ${num(l.final ?? l.price)}원</div>
      <div class="cl-row" style="margin-top:8px">
        <button class="btn sm ${this.sel.has(l.id) ? "" : "primary"}" data-card-sel>${this.sel.has(l.id) ? "고른 것에서 빼기" : "고르기"}</button>
        ${l.origin_no && l.channel_no ? goLinks({ storeUrl: l.store_url, channelNo: l.channel_no }) : ""}
        <a class="btn sm" href="/api/sources/${l.source_id}/origin" target="_blank" rel="noopener noreferrer" title="엑셀 수집URL">수집한 곳 ↗</a>
        <button class="btn sm ghost" data-card-copy title="상품명 복사">복사</button></div>`;
    c.hidden = false;
    const w = c.offsetWidth, h = c.offsetHeight;
    c.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, x + 4))}px`;
    c.style.top = `${Math.max(8, Math.min(innerHeight - h - 8, y + 4))}px`;
    $("[data-card-sel]", c).addEventListener("click", () => { this.sel.has(l.id) ? this.sel.delete(l.id) : this.sel.set(l.id, l); this.paintSel(); this.hideCard(); });
    $("[data-card-copy]", c).addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(l.name); App.toast("상품명을 복사했습니다"); } catch (e) { App.toast("복사하지 못했습니다", true); }
    });
  },
  hideCard() { const c = $("#eye-card"); if (c) c.hidden = true; },

  async remove() {
    const ids = [...this.sel.keys()];
    if (!ids.length) return;
    const r = await App.deleteCopies({ ids }, null, `눈검수로 고른 ${num(ids.length)}개`);
    if (!r) return;
    this.deleted += ids.length;
    this.sel.clear();
    this.load();
  },

  close() {
    clearTimeout(this._zt);
    document.removeEventListener("keydown", this._key, true);
    document.removeEventListener("mousedown", this._out, true);
    document.body.classList.remove("eye-open");
    const el = $("#eye");
    if (el) { el.hidden = true; el.innerHTML = ""; }
    if (this.after) this.after({ deleted: this.deleted });
  },
};
