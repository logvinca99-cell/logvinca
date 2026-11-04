/* 눈검수: 복사본 화면에서 썸네일만 그리드로 (인스타그램처럼) 보며 빠르게 걸러 냄.
   한 쪽이 화면에 꽉 차게(내리지 않아도 다 보임), 사진 밑에 상품명 앞 4자.
   클릭 = 고르기 (Shift+클릭 = 범위) · 마우스 올리기 = 크게 · 우클릭 = 상품명 전체 · ←/→ = 쪽 이동
   [이 쪽 눈검수 완료 · 다음 쪽]을 누르면 지금 쪽은 완료(원본 기준 — 다른 스토어 복사본도 본 것으로).
   고른 것을 지워도 그 칸은 '삭제됨'으로 자리를 지킴 (새 상품이 밀려 들어오지 않음 — 쪽은 복사본 번호로 넘김). */
"use strict";

const EYE_SIZES = [[24, "크게"], [40, "보통"], [60, "작게"], [96, "아주 작게"], [150, "한눈에"]];
const EYE_LABEL = 0.3;   // 사진 아래 상품명 칸 높이 (사진 한 변 대비)

/* 그리드용 작은 썸네일 주소 (네이버 이미지는 크기 지정, 안 되면 원래 주소로) */
function eyeThumb(url, px) {
  if (!/^https?:\/\/[^/]*pstatic\.net\//i.test(url || "") || url.includes("?")) return url;
  return `${url}?type=${px > 220 ? "m510" : "f300"}`;
}
const eyeName4 = (s) => Array.from(String(s || "").replace(/\s+/g, "")).slice(0, 4).join("");

const Eye = {
  open({ storeId, storeName, filter, after }) {
    this.storeId = storeId;
    this.storeName = storeName;
    this.baseFilter = { ...filter };
    this.after = after;
    this.sel = new Map();      // 복사본 번호 → 줄 (쪽을 넘겨도 남음)
    this.dead = new Map();     // 지운 복사본 번호 → 표시 ('삭제됨' 등) — 그 칸은 자리를 지킴
    this.last = null;          // Shift+클릭 범위 시작
    this.deleted = 0;
    this.rows = [];
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem("eye") || "{}"); } catch (e) { /* 무시 */ }
    this.size = EYE_SIZES.some((s) => s[0] === saved.size) ? saved.size : 40;
    this.todo = !!saved.todo;
    this.scope = "store";
    this.render();
    this.load({ from_id: 0 });
  },

  save() { try { localStorage.setItem("eye", JSON.stringify({ size: this.size, todo: this.todo })); } catch (e) { /* 무시 */ } },

  filter() {
    const f = this.scope === "filter" ? { ...this.baseFilter } : { store_id: this.storeId, status: "active" };
    if (!f.status || f.status === "all") f.status = "active";   // 내린 복사본은 볼 필요 없음
    if (this.todo) f.eye = "todo";
    f.store_id = this.storeId;
    delete f.page; delete f.size;
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
      <div class="eye-main" id="eye-main"><div class="eye-grid" id="eye-grid"></div></div>
      <aside class="eye-side">
        <div class="eye-side-head"><div><b>눈검수</b><div class="muted small">${esc(this.storeName || "")}</div></div>
          <button class="btn sm ghost" id="eye-close" title="닫기 (Esc)">✕ 닫기</button></div>
        <div class="eye-pno"><b id="eye-pg">-</b><span> / <span id="eye-pgs">-</span>쪽</span></div>
        <div class="eye-pstat small muted" id="eye-pstat"></div>
        <button class="eye-big eye-next" id="eye-next" title="이 쪽을 눈검수 완료로 하고 다음 쪽 (→)"></button>
        <button class="eye-big2" id="eye-prev" title="이전 쪽 (←)">‹ 이전 쪽</button>
        <div class="eye-sep"></div>
        <div class="eye-seln" id="eye-seln"></div>
        <button class="eye-big eye-del" id="eye-del">고른 것 삭제</button>
        <div class="eye-row"><button class="btn sm" id="eye-pageall" title="이 쪽 전부 고르기/빼기">이 쪽 전부</button>
          <button class="btn sm" id="eye-clear">고른 것 비우기</button></div>
        <div class="eye-sep"></div>
        <label class="eye-field">한 쪽에 <select id="eye-size" class="sel">${EYE_SIZES.map(([n, l]) => `<option value="${n}" ${n === this.size ? "selected" : ""}>${n}장 · ${l}</option>`).join("")}</select></label>
        <select id="eye-scope" class="sel" title="볼 범위"><option value="store">이 스토어 전체 (내림 제외)</option>
          ${scoped ? '<option value="filter">복사본 화면에서 거른 조건만</option>' : ""}</select>
        <label class="check small"><input type="checkbox" id="eye-todo" ${this.todo ? "checked" : ""}><span>눈검수 안 한 것만</span></label>
        <p class="eye-hint">클릭 고르기 · Shift+클릭 범위 · 마우스 올리기 크게 · 우클릭 상품명 전체 · ← → 쪽 · Esc 닫기</p>
      </aside>
      <div class="eye-zoom" id="eye-zoom" hidden><img alt="" referrerpolicy="no-referrer"></div>
      <div class="eye-card" id="eye-card" hidden></div>`;
    $("#eye-scope").value = this.scope;
    $("#eye-scope").addEventListener("change", (e) => { this.scope = e.target.value; this.load({ from_id: 0 }); });
    $("#eye-todo").addEventListener("change", (e) => { this.todo = e.target.checked; this.save(); this.load({ from_id: 0 }); });
    $("#eye-size").addEventListener("change", (e) => { this.size = +e.target.value; this.save(); this.load({ from_id: this.rows[0]?.id || 0 }); });
    $("#eye-prev").addEventListener("click", () => this.prev());
    $("#eye-next").addEventListener("click", () => this.next());
    $("#eye-close").addEventListener("click", () => this.close());
    $("#eye-clear").addEventListener("click", () => { this.sel.clear(); this.paintSel(); });
    $("#eye-pageall").addEventListener("click", () => {
      const live = this.rows.filter((l) => !this.dead.has(l.id));
      const all = live.length && live.every((l) => this.sel.has(l.id));
      live.forEach((l) => (all ? this.sel.delete(l.id) : this.sel.set(l.id, l)));
      this.paintSel();
    });
    $("#eye-del").addEventListener("click", () => this.remove());
    const grid = $("#eye-grid");
    grid.addEventListener("click", (e) => {
      const t = e.target.closest("[data-i]");
      if (!t) return;
      this.hideCard();
      const i = +t.dataset.i;
      const pick = (l, on) => { if (this.dead.has(l.id)) return; on ? this.sel.set(l.id, l) : this.sel.delete(l.id); };
      if (e.shiftKey && this.last != null) {
        const [a, b] = [Math.min(this.last, i), Math.max(this.last, i)];
        const on = !this.sel.has(this.rows[i].id);
        for (let k = a; k <= b; k++) pick(this.rows[k], on);
      } else pick(this.rows[i], !this.sel.has(this.rows[i].id));
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
      this._zt = setTimeout(() => this.zoom(t), 200);
    });
    grid.addEventListener("mouseleave", () => { clearTimeout(this._zt); $("#eye-zoom").hidden = true; });
    this._key = (e) => {
      if (!$("#modal-bg").hidden) return;   // 삭제 확인 창이 떠 있으면 그쪽
      if (e.target.matches?.("input, select, textarea")) return;
      if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); if (!$("#eye-card").hidden) this.hideCard(); else this.close(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); this.next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); this.prev(); }
    };
    document.addEventListener("keydown", this._key, true);
    this._out = (e) => { if (!e.target.closest?.("#eye-card")) this.hideCard(); };
    document.addEventListener("mousedown", this._out, true);
    this._resize = () => { clearTimeout(this._rt); this._rt = setTimeout(() => this.layout(), 80); };
    window.addEventListener("resize", this._resize);
  },

  /* 화면(그리드 칸)에 한 쪽이 꽉 차도록 열 수·사진 크기를 정함 — 내리지 않아도 다 보이게 */
  layout() {
    const box = $("#eye-main"), grid = $("#eye-grid");
    if (!box || !grid) return;
    const W = box.clientWidth - 16, H = box.clientHeight - 16, gap = 4;
    const n = this.size;
    let best = { t: 0, c: 1 };
    for (let c = 1; c <= n; c++) {
      const r = Math.ceil(n / c);
      const t = Math.min((W - gap * (c - 1)) / c, (H - gap * (r - 1)) / (r * (1 + EYE_LABEL)));
      if (t > best.t) best = { t, c };
    }
    this.tile = Math.max(40, Math.floor(best.t));
    grid.style.setProperty("--cols", best.c);
    grid.style.setProperty("--tile", `${this.tile}px`);
  },

  async load(at) {
    const f = this.filter();
    let res;
    try { res = await App.api(`/api/eye/page?${new URLSearchParams({ ...f, size: this.size, ...at })}`); } catch (e) { return App.toast(e.message, true); }
    this.res = res;
    this.rows = res.rows;
    this.last = null;
    this.layout();
    this.paintGrid();
    this.paintPage();
  },

  paintGrid() {
    const grid = $("#eye-grid");
    grid.innerHTML = this.rows.length ? this.rows.map((l, i) => {
      const dead = this.dead.get(l.id);
      const going = !dead && l.op === "delete" && ["planned", "queued", "running"].includes(l.status);
      return `<div class="eye-tile ${dead ? `dead ${dead.cls}` : ""} ${going || (!dead && l.drop_pending) ? "going" : ""}" data-i="${i}" data-id="${l.id}">
        <div class="eye-ph"><img loading="lazy" referrerpolicy="no-referrer" src="${esc(eyeThumb(l.thumb, this.tile))}" data-full="${esc(l.thumb)}" alt=""
          onerror="if(this.dataset.full&&this.src!==this.dataset.full){this.src=this.dataset.full}else{this.classList.add('broken')}">
          ${l.eye_at && !dead ? '<span class="eye-seen" title="눈검수 한 원본">✓</span>' : ""}
          ${dead ? `<div class="eye-dead"><b>${esc(dead.label)}</b>${dead.sub ? `<span>${esc(dead.sub)}</span>` : ""}</div>`
            : going || l.drop_pending ? '<span class="eye-tag">내리는 중</span>' : ""}
          <span class="eye-check">✓</span></div>
        <div class="eye-nm" title="${esc(l.name)}">${esc(eyeName4(l.name))}</div></div>`;
    }).join("") : `<p class="muted pad">${this.todo ? "눈검수 안 한 복사본이 없습니다. 다 봤습니다." : "복사본이 없습니다."}</p>`;
    this.paintSel();
  },

  paintPage() {
    const r = this.res || {};
    $("#eye-pg").textContent = this.rows.length ? num(r.page) : "0";
    $("#eye-pgs").textContent = num(r.pages || 0);
    $("#eye-pstat").innerHTML = `복사본 ${num(r.total || 0)}건${this.todo ? " (안 한 것만)" : ""}` + (r.done ? ' · <b class="c-ok">✓ 이 쪽은 눈검수 완료</b>' : "");
    $("#eye-prev").disabled = !r.has_prev;
    $("#eye-next").innerHTML = r.has_next ? "✓ 이 쪽 눈검수 완료<small>다음 쪽 →</small>" : "✓ 이 쪽 눈검수 완료<small>마지막 쪽</small>";
    $("#eye-next").disabled = !this.rows.length;
  },

  paintSel() {
    $$("#eye-grid .eye-tile").forEach((t) => t.classList.toggle("on", this.sel.has(+t.dataset.id)));
    const n = this.sel.size;
    $("#eye-seln").innerHTML = n ? `고른 것 <b>${num(n)}</b>개` : '<span class="muted">고른 것 없음 · 사진을 눌러 고르기</span>';
    $("#eye-del").disabled = !n;
    $("#eye-clear").disabled = !n;
  },

  async mark() {
    const ids = this.rows.map((l) => l.id);
    if (!ids.length) return false;
    try { await App.api("/api/eye/mark", { json: { ids } }); return true; } catch (e) { App.toast(e.message, true); return false; }
  },

  /* 이 쪽 눈검수 완료 → 다음 쪽 (복사본 번호로 이어서 — 이 쪽에서 지운 것이 있어도 밀리지 않음) */
  async next() {
    if (!this.rows.length || this._busy) return;
    this._busy = true;
    try {
      if (!(await this.mark())) return;
      const lastId = this.rows[this.rows.length - 1].id;
      if (this.res.has_next) await this.load({ from_id: lastId + 1 });
      else { App.toast("마지막 쪽까지 눈검수 완료했습니다"); await this.load({ from_id: this.rows[0].id }); }
    } finally { this._busy = false; }
  },

  prev() {
    if (!this.res?.has_prev || !this.rows.length) return;
    this.load({ before_id: this.rows[0].id });
  },

  zoom(t) {
    const im = $("img", t);
    if (!im || im.classList.contains("broken") || !$("#eye-card").hidden || t.classList.contains("dead")) return;
    const z = $("#eye-zoom");
    $("img", z).src = im.dataset.full || im.src;
    const r = t.getBoundingClientRect();
    const right = $("#eye-main").getBoundingClientRect().right;   // 오른쪽 버튼 칸은 가리지 않게
    const W = Math.min(480, right - 24, innerHeight - 24);
    z.style.width = z.style.height = `${W}px`;
    const left = r.right + 10 + W < right ? r.right + 10 : r.left - W - 10 > 0 ? r.left - W - 10 : Math.max(8, right - W - 8);
    z.style.left = `${left}px`;
    z.style.top = `${Math.max(8, Math.min(innerHeight - W - 8, r.top + r.height / 2 - W / 2))}px`;
    z.hidden = false;
  },

  showCard(l, x, y) {
    $("#eye-zoom").hidden = true;
    const c = $("#eye-card");
    const named = !!l.name_id || !!l.origin_no;
    const dead = this.dead.get(l.id);
    c.innerHTML = `<div class="eye-card-name">${esc(l.name)}</div>
      ${named && l.source_name && l.source_name !== l.name ? `<div class="small muted">원본: ${esc(l.source_name)}</div>` : ""}
      ${!named ? '<div class="small c-err">상품명 변경 전 (원본 이름 그대로)</div>' : ""}
      <div class="small" style="margin-top:6px">${dead ? `<b class="c-err">${esc(dead.label)}</b>` : statusBadge(l.status, l.op)} ${esc(l.seller_code || "")} · 원본 #${l.source_id} · ${num(l.final ?? l.price)}원</div>
      <div class="cl-row" style="margin-top:8px">
        ${dead ? "" : `<button class="btn sm ${this.sel.has(l.id) ? "" : "primary"}" data-card-sel>${this.sel.has(l.id) ? "고른 것에서 빼기" : "고르기"}</button>`}
        ${l.origin_no && l.channel_no ? goLinks({ storeUrl: l.store_url, channelNo: l.channel_no }) : ""}
        <a class="btn sm" href="/api/sources/${l.source_id}/origin" target="_blank" rel="noopener noreferrer" title="엑셀 수집URL">수집한 곳 ↗</a>
        <button class="btn sm ghost" data-card-copy title="상품명 복사">복사</button></div>`;
    c.hidden = false;
    const w = c.offsetWidth, h = c.offsetHeight;
    c.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, x + 4))}px`;
    c.style.top = `${Math.max(8, Math.min(innerHeight - h - 8, y + 4))}px`;
    $("[data-card-sel]", c)?.addEventListener("click", () => { this.sel.has(l.id) ? this.sel.delete(l.id) : this.sel.set(l.id, l); this.paintSel(); this.hideCard(); });
    $("[data-card-copy]", c).addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(l.name); App.toast("상품명을 복사했습니다"); } catch (e) { App.toast("복사하지 못했습니다", true); }
    });
  },
  hideCard() { const c = $("#eye-card"); if (c) c.hidden = true; },

  /* 고른 것 삭제 → 쪽을 다시 불러오지 않고 그 칸에 결과 표시 (자리는 그대로) */
  async remove() {
    const ids = [...this.sel.keys()];
    if (!ids.length) return;
    const r = await App.deleteCopies({ ids }, null, `눈검수로 고른 ${num(ids.length)}개`);
    if (!r) return;
    const now = {};
    try {
      for (let i = 0; i < ids.length; i += 400) {
        const part = ids.slice(i, i + 400);
        const d = await App.api(`/api/listings?${new URLSearchParams({ ids: part.join(","), size: 500 })}`);
        d.rows.forEach((x) => { now[x.id] = x; });
      }
    } catch (e) { /* 표시만 못 함 */ }
    for (const id of ids) {
      const x = now[id];
      if (!x) this.dead.set(id, { label: "삭제됨", cls: "gone" });
      else if (x.op === "delete" && ["planned", "queued", "running"].includes(x.status)) this.dead.set(id, { label: "삭제됨", sub: "네이버에서 내리는 중", cls: "gone" });
      else this.dead.set(id, { label: "안 지워짐", sub: x.locked ? "판매 이력·잠금" : x.origin_no ? "올라가 있음" : "", cls: "kept" });
    }
    const gone = ids.filter((id) => this.dead.get(id)?.cls === "gone").length;
    this.deleted += gone;
    this.sel.clear();
    this.rows = this.rows.map((l) => now[l.id] ? { ...l, ...now[l.id] } : l);
    this.paintGrid();
  },

  close() {
    clearTimeout(this._zt);
    document.removeEventListener("keydown", this._key, true);
    document.removeEventListener("mousedown", this._out, true);
    window.removeEventListener("resize", this._resize);
    document.body.classList.remove("eye-open");
    const el = $("#eye");
    if (el) { el.hidden = true; el.innerHTML = ""; }
    if (this.after) this.after({ deleted: this.deleted });
  },
};
