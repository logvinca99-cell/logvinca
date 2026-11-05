/* 눈검수: 복사본 화면에서 썸네일만 그리드로 (인스타그램처럼) 보며 빠르게 걸러 냄.
   한 쪽이 화면에 꽉 차게(내리지 않아도 다 보임), 사진 밑에 상품명 앞 키워드 4개(띄어쓰기 기준, 금지어·상표 단어는 빨강·주황).
   클릭 = 고르기 (Shift+클릭 = 범위, 끌기 = 네모 안 여러 장) · 마우스 올리기 = 크게 · 우클릭 = 상품명 전체 · ←/→ = 쪽 이동
   [이 쪽 눈검수 완료 · 다음 쪽]을 누르면 지금 쪽은 완료(원본 기준 — 다른 스토어 복사본도 본 것으로)이고 그 자리를 기억해
   다음에 열면 이어서 시작. 오른쪽 칸에 메모(스토어마다 따로, 자동 저장)·오늘 본·지운 수·남은 쪽과 예상 시간.
   고른 것을 지워도 그 칸은 '삭제됨'으로 자리를 지킴. 판매 중인 것의 네이버 내리기는 '이 쪽 완료·다음'이나 닫을 때 시작해서
   그 전에 [되돌리기]를 누르면 완전히 원래대로. */
"use strict";

const EYE_SIZES = [[24, "크게"], [40, "보통"], [60, "작게"], [96, "아주 작게"], [150, "한눈에"]];
const EYE_LABEL = 0.38;   // 사진 아래 상품명 칸 높이 (사진 한 변 대비, 두 줄)

/* 그리드용 작은 썸네일 주소 (네이버 이미지는 크기 지정, 안 되면 원래 주소로) */
function eyeThumb(url, px) {
  if (!/^https?:\/\/[^/]*pstatic\.net\//i.test(url || "") || url.includes("?")) return url;
  return `${url}?type=${px > 220 ? "m510" : "f300"}`;
}
const eyeWords = (s) => String(s || "").trim().split(/\s+/).filter(Boolean).slice(0, 4);   // 앞 키워드 4개 (띄어쓰기 기준)
/* 키워드 4개가 칸 폭에 두 줄 안으로 꽉 차는 글자 크기 (사진 한 변 대비). 한글 1, 영문·숫자 0.6, 띄어쓰기 0.35로 셈 */
function eyeFont(words) {
  const w = (t) => Array.from(t).reduce((a, ch) => a + (/[ᄀ-ᇿ㄰-㆏가-힣一-鿿]/.test(ch) ? 1 : 0.6), 0);
  const total = words.reduce((a, t) => a + w(t), 0) + 0.35 * Math.max(0, words.length - 1);
  const longest = Math.max(1, ...words.map(w));
  return Math.max(0.06, Math.min(0.15, 1.5 / Math.max(1, total), 0.9 / longest));
}
/* 그래도 두 줄을 넘는 이름(줄바꿈 자리 때문에)만 글자를 조금씩 줄여 맞춤 */
function eyeFit(root) {
  root.querySelectorAll(".eye-nm").forEach((el) => {
    const s = el.firstElementChild;
    let fs = parseFloat(el.style.getPropertyValue("--fs")) || 0.12;
    for (let k = 0; k < 8 && s && (s.scrollHeight > s.clientHeight + 1 || s.scrollWidth > s.clientWidth + 1) && fs > 0.05; k++) {
      fs *= 0.9;
      el.style.setProperty("--fs", fs.toFixed(3));
    }
  });
}
const EYE_KW = { blocked: ["kw-b", "금지 단어"], mark: ["kw-m", "상표로 등록·출원된 단어"] };
function eyeTime(sec) {
  if (sec == null || !isFinite(sec)) return "";
  if (sec < 60) return "1분 안";
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return h ? `약 ${h}시간 ${m}분` : `약 ${m}분`;
}

const Eye = {
  async open({ storeId, storeName, filter, after }) {
    this.storeId = storeId;
    this.storeName = storeName;
    this.baseFilter = { ...filter };
    this.after = after;
    this.sel = new Map();      // 복사본 번호 → 줄 (쪽을 넘겨도 남음)
    this.dead = new Map();     // 지운 복사본 번호 → 표시 ('삭제됨' 등) — 그 칸은 자리를 지킴
    this.undos = [];           // 되돌리기: [{sids, lids, since, n, drops, gone}] (마지막 것부터)
    this.drops = new Set();    // 미뤄 둔 네이버 내리기 (복사본 번호) — '이 쪽 완료·다음'이나 닫을 때 시작
    this.last = null;          // Shift+클릭 범위 시작
    this.deleted = 0;
    this.rows = [];
    this.scope = "store";
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem("eye") || "{}"); } catch (e) { /* 무시 */ }
    let st = {};
    try { st = await App.api(`/api/eye/state?store_id=${storeId}`); } catch (e) { /* 처음부터 */ }
    this.state = st;
    const size = st.last_at && st.size ? st.size : saved.size;
    this.size = EYE_SIZES.some((s) => s[0] === size) ? size : 40;
    this.todo = st.last_at ? !!st.todo : !!saved.todo;
    this.render();
    if (st.last_id) {
      this.resume = { at: st.last_at };
      await this.load({ from_id: st.last_id + 1 });
      if (!this.res?.has_next && this.rows.length && this.rows[this.rows.length - 1].id <= st.last_id) this.resume.end = true;
      this.paintResume();
    } else await this.load({ from_id: 0 });
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
        <div class="eye-side-head"><div><b>눈검수</b> <span class="muted small">${esc(this.storeName || "")}</span></div>
          <button class="btn sm ghost" id="eye-close" title="닫기 (Esc) — 메모·멈춘 자리는 저장됨">✕ 닫기</button></div>
        <div class="eye-pno"><b id="eye-pg">-</b><span> / <span id="eye-pgs">-</span>쪽</span></div>
        <div class="eye-resume small" id="eye-resume" hidden></div>
        <div class="eye-pstat small muted" id="eye-pstat"></div>
        <button class="eye-big eye-next" id="eye-next" title="이 쪽을 눈검수 완료로 하고 다음 쪽 (→)"></button>
        <button class="eye-big2" id="eye-prev" title="이전 쪽 (←)">‹ 이전 쪽</button>
        <div class="eye-sep"></div>
        <div class="eye-seln" id="eye-seln"></div>
        <button class="eye-big eye-del" id="eye-del">고른 것 삭제</button>
        <button class="eye-undo" id="eye-undo" hidden></button>
        <div class="eye-row"><button class="btn sm" id="eye-pageall" title="이 쪽 전부 고르기/빼기">이 쪽 전부</button>
          <button class="btn sm" id="eye-clear">고른 것 비우기</button></div>
        <div class="eye-sep"></div>
        <div class="eye-stats small" id="eye-stats"></div>
        <div class="eye-memo"><div class="eye-memo-head small"><b>메모</b> <span class="muted">이 스토어만 · 자동 저장</span><span class="muted" id="eye-memo-st"></span></div>
          <textarea id="eye-memo" placeholder="예) 52쪽까지 봄 · 브랜드 의심 상품 다시 보기"></textarea></div>
        <div class="eye-opts">
          <label class="eye-field">한 쪽에 <select id="eye-size" class="sel">${EYE_SIZES.map(([n, l]) => `<option value="${n}" ${n === this.size ? "selected" : ""}>${n}장 · ${l}</option>`).join("")}</select></label>
          ${scoped ? `<select id="eye-scope" class="sel" title="볼 범위"><option value="store">이 스토어 전체 (내림 제외)</option>
            <option value="filter">복사본 화면에서 거른 조건만</option></select>` : ""}
          <label class="check small"><input type="checkbox" id="eye-todo" ${this.todo ? "checked" : ""}><span>눈검수 안 한 것만</span></label></div>
        <p class="eye-hint">클릭 고르기 · 끌기 여러 장 · Shift+클릭 범위 · 우클릭 상품명 · ← → 쪽 · Esc 닫기</p>
      </aside>
      <div class="eye-zoom" id="eye-zoom" hidden><img alt="" referrerpolicy="no-referrer"></div>
      <div class="eye-card" id="eye-card" hidden></div>
      <div class="eye-rect" id="eye-rect" hidden></div>`;
    $("#eye-memo").value = this.state?.memo || "";
    if (this.state?.memo_at) $("#eye-memo-st").textContent = ` · ${when(this.state.memo_at)} 저장`;
    $("#eye-memo").addEventListener("input", () => { clearTimeout(this._mt); $("#eye-memo-st").textContent = " · 적는 중…"; this._mt = setTimeout(() => this.saveMemo(), 700); });
    $("#eye-memo").addEventListener("blur", () => { if (this._mt) { clearTimeout(this._mt); this.saveMemo(); } });
    $("#eye-scope")?.addEventListener("change", (e) => { this.scope = e.target.value; this.load({ from_id: 0 }); });
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
    $("#eye-undo").addEventListener("click", () => this.undo());
    $("#eye-resume").addEventListener("click", (e) => { if (e.target.closest("[data-restart]")) this.restart(); });
    const grid = $("#eye-grid");
    grid.addEventListener("click", (e) => {
      if (this._dragged) return;
      const t = e.target.closest("[data-i]");
      if (!t) return;
      this.hideCard();
      const i = +t.dataset.i;
      if (e.shiftKey && this.last != null) {
        const [a, b] = [Math.min(this.last, i), Math.max(this.last, i)];
        const on = !this.sel.has(this.rows[i].id);
        for (let k = a; k <= b; k++) this.pick(this.rows[k], on);
      } else this.pick(this.rows[i], !this.sel.has(this.rows[i].id));
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
      if (!t || this._drag?.active) return;
      this._zt = setTimeout(() => this.zoom(t), 200);
    });
    grid.addEventListener("mouseleave", () => { clearTimeout(this._zt); $("#eye-zoom").hidden = true; });
    this.bindDrag();
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
    this.paintStats();
  },

  pick(l, on) { if (!l || this.dead.has(l.id)) return; on ? this.sel.set(l.id, l) : this.sel.delete(l.id); },

  /* 끌어서 여러 장 고르기: 빈 곳이나 사진에서 누른 채 끌면 네모 안의 사진을 고름 (고른 사진에서 시작하면 빼기) */
  bindDrag() {
    const main = $("#eye-main");
    main.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.shiftKey) return;
      const t = e.target.closest("[data-i]");
      this._drag = { x: e.clientX, y: e.clientY, on: !(t && this.sel.has(+t.dataset.id)), base: new Map(this.sel), active: false };
    });
    this._dmove = (e) => {
      const d = this._drag;
      if (!d) return;
      if (!d.active) {
        if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 8) return;
        d.active = true;
        clearTimeout(this._zt);
        $("#eye-zoom").hidden = true;
        this.hideCard();
      }
      e.preventDefault();
      const x1 = Math.min(d.x, e.clientX), x2 = Math.max(d.x, e.clientX), y1 = Math.min(d.y, e.clientY), y2 = Math.max(d.y, e.clientY);
      const r = $("#eye-rect");
      Object.assign(r.style, { left: `${x1}px`, top: `${y1}px`, width: `${x2 - x1}px`, height: `${y2 - y1}px` });
      r.hidden = false;
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => {
        this._raf = null;
        $$("#eye-grid .eye-tile").forEach((t) => {
          const b = t.getBoundingClientRect();
          const l = this.rows[+t.dataset.i];
          const hit = b.right >= x1 && b.left <= x2 && b.bottom >= y1 && b.top <= y2;
          if (hit) this.pick(l, d.on);
          else if (d.base.has(l.id)) this.sel.set(l.id, d.base.get(l.id));
          else this.sel.delete(l.id);
        });
        this.paintSel();
      });
    };
    this._dup = () => {
      const d = this._drag;
      this._drag = null;
      if (!d?.active) return;
      $("#eye-rect").hidden = true;
      this._dragged = true;               // 끌기를 끝낸 자리의 클릭은 무시
      setTimeout(() => { this._dragged = false; }, 0);
    };
    window.addEventListener("pointermove", this._dmove);
    window.addEventListener("pointerup", this._dup);
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
    eyeFit(grid);
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

  nameHtml(l) {
    const kw = l.kw || eyeWords(l.name).map((w) => [w, ""]);
    return kw.map(([w, why]) => (EYE_KW[why] ? `<em class="${EYE_KW[why][0]}" title="${EYE_KW[why][1]}">${esc(w)}</em>` : esc(w))).join(" ");
  },

  paintGrid() {
    const grid = $("#eye-grid");
    grid.innerHTML = this.rows.length ? this.rows.map((l, i) => {
      const dead = this.dead.get(l.id);
      const going = !dead && l.op === "delete" && ["planned", "queued", "running"].includes(l.status);
      const words = (l.kw || []).map((x) => x[0]);
      return `<div class="eye-tile ${dead ? `dead ${dead.cls}` : ""} ${going || (!dead && l.drop_pending) ? "going" : ""}" data-i="${i}" data-id="${l.id}">
        <div class="eye-ph"><img loading="lazy" referrerpolicy="no-referrer" src="${esc(eyeThumb(l.thumb, this.tile))}" data-full="${esc(l.thumb)}" alt=""
          onerror="if(this.dataset.full&&this.src!==this.dataset.full){this.src=this.dataset.full}else{this.classList.add('broken')}">
          ${l.eye_at && !dead ? '<span class="eye-seen" title="눈검수 한 원본">✓</span>' : ""}
          ${dead ? `<div class="eye-dead"><b>${esc(dead.label)}</b>${dead.sub ? `<span>${esc(dead.sub)}</span>` : ""}</div>`
            : going || l.drop_pending ? '<span class="eye-tag">내리는 중</span>' : ""}
          <span class="eye-check">✓</span></div>
        <div class="eye-nm" title="${esc(l.name)}" style="--fs:${eyeFont(words.length ? words : eyeWords(l.name)).toFixed(3)}"><span>${this.nameHtml(l)}</span></div></div>`;
    }).join("") : `<p class="muted pad">${this.todo ? "눈검수 안 한 복사본이 없습니다. 다 봤습니다." : "복사본이 없습니다."}</p>`;
    eyeFit(grid);
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
    this.paintStats();
  },

  paintResume() {
    const box = $("#eye-resume");
    if (!this.resume) { box.hidden = true; return; }
    box.innerHTML = (this.resume.end ? `지난번(${when(this.resume.at)})에 끝까지 봤습니다` : `지난번 이어서 · ${when(this.resume.at)}에 멈춘 다음 쪽`)
      + ' <button class="link-btn" data-restart>처음부터</button>';
    box.hidden = false;
  },

  /* 오늘 본·지운 수, 남은 쪽과 예상 시간 */
  paintStats() {
    const box = $("#eye-stats");
    if (!box) return;
    const s = this.state || {}, r = this.res || {};
    const left = (r.after || 0) + (this.rows?.length || 0);   // 이 쪽 포함 남은 복사본
    const pagesLeft = r.pages ? Math.max(0, r.pages - r.page + 1) : 0;
    const est = s.sec_per_item ? eyeTime(left * s.sec_per_item) : "";
    box.innerHTML = `<div>오늘 본 것 <b>${num(s.today_seen || 0)}</b>개 · 지운 것 <b class="c-err">${num(s.today_deleted || 0)}</b>개</div>
      <div>남은 쪽 <b>${num(pagesLeft)}</b>쪽 (${num(left)}건)${est ? ` · <b>${est}</b>` : ""}</div>
      ${s.sec_per_item ? `<div class="muted">한 장에 ${s.sec_per_item.toFixed(1)}초 · 오늘 속도 기준</div>` : '<div class="muted">예상 시간은 쪽을 두 번 넘기면 나옵니다</div>'}`;
  },

  paintSel() {
    $$("#eye-grid .eye-tile").forEach((t) => t.classList.toggle("on", this.sel.has(+t.dataset.id)));
    const n = this.sel.size;
    $("#eye-seln").innerHTML = n ? `고른 것 <b>${num(n)}</b>개` : '<span class="muted">고른 것 없음 · 사진을 눌러 고르기</span>';
    $("#eye-del").disabled = !n;
    $("#eye-clear").disabled = !n;
    const u = this.undos[this.undos.length - 1];
    const ub = $("#eye-undo");
    ub.hidden = !u;
    if (u) ub.innerHTML = `↶ 되돌리기 <span>방금 지운 ${num(u.n)}개${this.undos.length > 1 ? ` (${this.undos.length}번 남음)` : ""}</span>`;
  },

  async saveMemo() {
    this._mt = null;
    try {
      const r = await App.api("/api/eye/memo", { json: { store_id: this.storeId, memo: $("#eye-memo")?.value ?? "" } });
      const st = $("#eye-memo-st");
      if (st) st.textContent = ` · ${when(r.memo_at)} 저장됨`;
    } catch (e) { App.toast(`메모를 저장하지 못했습니다: ${e.message}`, true); }
  },

  async mark() {
    const ids = this.rows.map((l) => l.id);
    if (!ids.length) return false;
    try {
      const r = await App.api("/api/eye/mark", { json: { ids, store_id: this.storeId, last_id: ids[ids.length - 1], size: this.size, todo: this.todo } });
      Object.assign(this.state, { today_seen: r.today_seen, today_deleted: r.today_deleted, sec_per_item: r.sec_per_item });
      return true;
    } catch (e) { App.toast(e.message, true); return false; }
  },

  /* 미뤄 둔 네이버 내리기 시작 (이 쪽 완료·다음, 닫기) */
  async commit() {
    if (!this.drops.size) return;
    const ids = [...this.drops];
    this.drops.clear();
    try {
      const r = await App.api("/api/eye/commit", { json: { ids } });
      if (r.started) App.toast(`판매 중이던 ${num(r.count)}건을 네이버에서 내리는 중입니다 (다 내리면 원본도 휴지통으로)`);
      else if (r.queued) App.toast(`판매 중이던 ${num(r.count)}건은 내리기 대기에 있습니다 (지금 등록이 도는 중 — 끝난 뒤 시작에서 '내리기')`);
      else if (r.error) App.toast(r.error, true);
    } catch (e) { App.toast(e.message, true); }
  },

  /* 이 쪽 눈검수 완료 → 다음 쪽 (복사본 번호로 이어서 — 이 쪽에서 지운 것이 있어도 밀리지 않음) */
  async next() {
    if (!this.rows.length || this._busy) return;
    this._busy = true;
    try {
      if (!(await this.mark())) return;
      await this.commit();
      this.resume = null;
      this.paintResume();
      const lastId = this.rows[this.rows.length - 1].id;
      if (this.res.has_next) await this.load({ from_id: lastId + 1 });
      else { App.toast("마지막 쪽까지 눈검수 완료했습니다"); await this.load({ from_id: this.rows[0].id }); }
    } finally { this._busy = false; }
  },

  prev() {
    if (!this.res?.has_prev || !this.rows.length) return;
    this.load({ before_id: this.rows[0].id });
  },

  async restart() {
    try { await App.api("/api/eye/reset", { json: { store_id: this.storeId } }); } catch (e) { /* 화면만 */ }
    this.resume = null;
    this.paintResume();
    this.load({ from_id: 0 });
  },

  zoom(t) {
    const im = $("img", t);
    if (!im || im.classList.contains("broken") || !$("#eye-card").hidden || t.classList.contains("dead") || this._drag?.active) return;
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
    const flagged = (l.kw || []).filter(([, why]) => EYE_KW[why]);
    c.innerHTML = `<div class="eye-card-name">${esc(l.name)}</div>
      ${named && l.source_name && l.source_name !== l.name ? `<div class="small muted">원본: ${esc(l.source_name)}</div>` : ""}
      ${!named ? '<div class="small c-err">상품명 변경 전 (원본 이름 그대로)</div>' : ""}
      ${flagged.length ? `<div class="small" style="margin-top:4px">${flagged.map(([w, why]) => `<em class="${EYE_KW[why][0]}">${esc(w)}</em> ${EYE_KW[why][1]}`).join(" · ")}</div>` : ""}
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

  /* 고른 것 삭제 → 쪽을 다시 불러오지 않고 그 칸에 결과 표시 (자리는 그대로). 판매 중인 것의 네이버 내리기는 미룸 */
  async remove() {
    const picked = [...this.sel.values()];
    const ids = picked.map((l) => l.id);
    if (!ids.length) return;
    const since = Date.now() / 1000;
    const r = await App.deleteCopies({ ids }, null, `눈검수로 고른 ${num(ids.length)}개`, { now: false });
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
      else if (x.op === "delete" && ["planned", "queued", "running"].includes(x.status)) this.dead.set(id, { label: "삭제됨", sub: "네이버에서 내릴 예정", cls: "gone" });
      else this.dead.set(id, { label: "안 지워짐", sub: x.locked ? "판매 이력·잠금" : x.origin_no ? "올라가 있음" : "", cls: "kept" });
    }
    const gone = ids.filter((id) => this.dead.get(id)?.cls === "gone").length;
    const drops = r.drop_ids || [];
    drops.forEach((id) => this.drops.add(id));
    this.undos.push({ sids: [...new Set(picked.map((l) => l.source_id))], lids: ids, since, n: ids.length, drops, gone });
    this.deleted += gone;
    this.sel.clear();
    this.rows = this.rows.map((l) => now[l.id] ? { ...l, ...now[l.id] } : l);
    this.paintGrid();
    try {
      const s = await App.api("/api/eye/deleted", { json: { store_id: this.storeId, n: gone } });
      Object.assign(this.state, s);
      this.paintStats();
    } catch (e) { /* 통계만 */ }
  },

  /* 방금 지운 것 되돌리기 (마지막 것부터) */
  async undo() {
    const u = this.undos.pop();
    if (!u) return;
    let r;
    try {
      r = await App.api("/api/eye/undo", { json: { store_id: this.storeId, source_ids: u.sids, since: u.since, n: u.gone } });
    } catch (e) { this.undos.push(u); return App.toast(e.message, true); }
    u.lids.forEach((id) => this.dead.delete(id));
    u.drops.forEach((id) => this.drops.delete(id));
    this.deleted -= u.gone;
    Object.assign(this.state, { today_seen: r.today_seen, today_deleted: r.today_deleted, sec_per_item: r.sec_per_item });
    App.toast(`되돌렸습니다: 휴지통에서 ${num(r.restored)}개 되살림` + (r.cancelled ? ` · 네이버 내리기 ${num(r.cancelled)}건 취소 (판매 중 그대로)` : "")
      + (r.dropped ? ` · 이미 네이버에서 내려간 ${num(r.dropped)}건은 '내림'으로 남음 (복사본 화면에서 다시 올리기)` : "")
      + (r.busy ? ` · 지금 내리는 중인 ${num(r.busy)}건은 못 멈춤` : "") + (r.skipped ? ` · 못 되살린 ${num(r.skipped)}개 (휴지통에서 확인)` : ""), !!(r.dropped || r.busy || r.skipped));
    App.refreshState();
    await this.load({ from_id: this.rows[0]?.id || 0 });
  },

  async close() {
    clearTimeout(this._zt);
    if (this._mt) { clearTimeout(this._mt); await this.saveMemo(); }
    await this.commit();
    document.removeEventListener("keydown", this._key, true);
    document.removeEventListener("mousedown", this._out, true);
    window.removeEventListener("resize", this._resize);
    window.removeEventListener("pointermove", this._dmove);
    window.removeEventListener("pointerup", this._dup);
    document.body.classList.remove("eye-open");
    const el = $("#eye");
    if (el) { el.hidden = true; el.innerHTML = ""; }
    if (this.after) this.after({ deleted: this.deleted });
  },
};
