/* 눈검수: 복사본 화면에서 썸네일만 그리드로 (인스타그램처럼) 보며 빠르게 걸러 냄.
   한 쪽이 화면에 꽉 차게(내리지 않아도 다 보임), 사진 밑 남색 칸에 상품명 앞 키워드 4개(띄어쓰기 기준, 금지어·상표 단어 표시).
   클릭 = 삭제 예정으로 고르기, 한 번 더 = 풀기 (Shift+클릭 = 범위, 끌기 = 네모 안 여러 장) · 우클릭 = 큰 사진과 상품명 · ←/→ = 쪽 이동
   [✓ 고른 N개 삭제하고 다음 쪽]: 고른 것을 확인 창 없이 지우고(원본까지) 이 쪽을 완료로 하고 다음 쪽으로. 그 자리를 기억해
   다음에 열면 이어서 시작. 오른쪽 칸에 메모(스토어마다 따로, 자동 저장)·오늘 본·지운 수·남은 쪽과 예상 시간.
   지운 칸은 '삭제됨'으로 자리를 지키고, 그 칸을 다시 누르면 그 하나만 되살아남.
   판매 중인 것의 네이버 내리기는 한 쪽 늦게(그다음 쪽을 완료하거나 닫을 때) 시작 → 다음 쪽에서도 [되돌리기]로 완전히 원래대로.
   이 화면에서만 커서가 크고 형광색. */
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
  /* kind: listing(복사본 화면, 그 스토어) / source(원본 상품 화면) */
  async open({ kind = "listing", storeId, storeName, filter, after }) {
    this.kind = kind === "source" ? "source" : "listing";
    this.storeId = this.kind === "source" ? 0 : storeId;   // 메모·이어서 시작 자리: 스토어마다, 원본은 0
    this.since0 = Date.now() / 1000;                       // '안 한 것만'일 때도 이번에 지운 칸은 남김
    this.storeName = storeName;
    this.baseFilter = { ...filter };
    this.after = after;
    this.sel = new Map();      // 삭제 예정으로 고른 복사본 번호 → 줄 (쪽을 넘겨도 남음)
    this.dead = new Map();     // 지운 복사본 번호 → 표시 ('삭제됨' 등) — 그 칸은 자리를 지킴
    this.undos = [];           // 되돌리기: [{sids, lids, since, n, gone}] (마지막 것부터)
    this.dropsCur = new Set(); // 이 쪽에서 미룬 네이버 내리기 (복사본 번호)
    this.dropsPrev = new Set();// 앞 쪽에서 미룬 것 — 이 쪽을 완료하거나 닫을 때 시작 (한 쪽 늦게 → 다음 쪽에서도 되돌리기)
    this.last = null;          // Shift+클릭 범위 시작
    this.deleted = 0;
    this.rows = [];
    this.scope = "store";
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem("eye") || "{}"); } catch (e) { /* 무시 */ }
    let st = {};
    try { st = await App.api(`/api/eye/state?store_id=${this.storeId}`); } catch (e) { /* 처음부터 */ }
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
    if (this.kind === "source") {
      const f = this.scope === "filter" ? { ...this.baseFilter } : {};
      delete f.page; delete f.size; delete f.eye;
      if (this.todo) f.eye = "todo";
      return f;
    }
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
    const scoped = Object.keys(this.baseFilter).some((k) => !["store_id", "status", "page", "size", "all_"].includes(k) && this.baseFilter[k] !== "")
      || (this.baseFilter.status && !["all", "active"].includes(this.baseFilter.status));
    el.innerHTML = `
      <div class="eye-main" id="eye-main"><div class="eye-grid" id="eye-grid"></div></div>
      <aside class="eye-side">
        <div class="eye-side-head"><div><b>눈검수</b> <span class="muted small">${esc(this.storeName || "")}</span></div>
          <button class="btn sm ghost" id="eye-close" title="닫기 (Esc) — 메모·멈춘 자리는 저장됨">✕ 닫기</button></div>
        <div class="eye-pno"><b id="eye-pg">-</b><span> / <span id="eye-pgs">-</span>쪽</span></div>
        <div class="eye-resume small" id="eye-resume" hidden></div>
        <div class="eye-pstat small muted" id="eye-pstat"></div>
        <button class="eye-big eye-next" id="eye-next" title="고른 것이 있으면 지우고, 이 쪽을 눈검수 완료로 하고 다음 쪽 (→)"></button>
        <button class="eye-big2" id="eye-prev" title="이전 쪽 (←)">‹ 이전 쪽</button>
        <div class="eye-sep"></div>
        <div class="eye-seln" id="eye-seln"></div>
        <button class="eye-undo" id="eye-undo" hidden></button>
        <div class="eye-row"><button class="btn sm" id="eye-pageall" title="이 쪽 전부 고르기/풀기">이 쪽 전부</button>
          <button class="btn sm" id="eye-clear" title="고른 것 모두 풀기">모두 풀기</button>
          <button class="btn sm danger" id="eye-del" title="쪽을 넘기기 전에 지금 지우기 (확인 창에서 '원본까지' 끌 수 있음)">지금 삭제</button></div>
        <div class="eye-sep"></div>
        <div class="eye-stats small" id="eye-stats"></div>
        <div class="eye-memo"><div class="eye-memo-head small"><b>메모</b> <span class="muted">이 스토어만 · 자동 저장</span><span class="muted" id="eye-memo-st"></span></div>
          <textarea id="eye-memo" placeholder="예) 52쪽까지 봄 · 브랜드 의심 상품 다시 보기"></textarea></div>
        <div class="eye-opts">
          <label class="eye-field">한 쪽에 <select id="eye-size" class="sel">${EYE_SIZES.map(([n, l]) => `<option value="${n}" ${n === this.size ? "selected" : ""}>${n}장 · ${l}</option>`).join("")}</select></label>
          ${scoped ? `<select id="eye-scope" class="sel" title="볼 범위"><option value="store">${this.kind === "source" ? "원본 전체" : "이 스토어 전체 (내림 제외)"}</option>
            <option value="filter">${this.kind === "source" ? "원본 화면" : "복사본 화면"}에서 거른 조건만</option></select>` : ""}
          <label class="check small"><input type="checkbox" id="eye-todo" ${this.todo ? "checked" : ""}><span>눈검수 안 한 것만</span></label></div>
        <p class="eye-hint">클릭 삭제 예정·다시 누르면 풀기 · 끌기 여러 장 · Shift+클릭 범위 · 우클릭 크게 · ← → 쪽 · Esc 닫기</p>
      </aside>
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
      const live = this.rows.filter((l) => !this.dead.has(l.id) && !l.dead);
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
      const l = this.rows[i];
      const dead = this.dead.get(l.id) || l.dead;
      if (dead?.cls === "gone") return this.restoreOne(l);            // 지운 칸을 다시 누르면 그 하나만 되살림
      if (dead) { this.dead.delete(l.id); this.paintGrid(); }          // '안 지워짐' 표시는 지우고 다시 고를 수 있게
      if (e.shiftKey && this.last != null) {
        const [a, b] = [Math.min(this.last, i), Math.max(this.last, i)];
        const on = !this.sel.has(l.id);
        for (let k = a; k <= b; k++) this.pick(this.rows[k], on);
      } else this.pick(l, !this.sel.has(l.id));
      this.last = i;
      this.paintSel();
    });
    grid.addEventListener("contextmenu", (e) => {
      const t = e.target.closest("[data-i]");
      if (!t) return;
      e.preventDefault();
      this.showCard(this.rows[+t.dataset.i], e.clientX, e.clientY);
    });
    this.bindDrag();
    this._key = (e) => {
      if (!$("#modal-bg").hidden) return;   // 확인 창이 떠 있으면 그쪽
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

  pick(l, on) { if (!l || this.dead.has(l.id) || l.dead) return; on ? this.sel.set(l.id, l) : this.sel.delete(l.id); },

  /* 끌어서 여러 장 고르기: 빈 곳이나 사진에서 누른 채 끌면 네모 안의 사진을 고름 (고른 사진에서 시작하면 풀기) */
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
    try { res = await App.api(`/api/eye/page?${new URLSearchParams({ ...f, size: this.size, kind: this.kind, dead_since: this.since0, ...at })}`); }
    catch (e) { return App.toast(e.message, true); }
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
      const dead = this.dead.get(l.id) || l.dead;
      const going = !dead && l.op === "delete" && ["planned", "queued", "running"].includes(l.status);
      const words = (l.kw || []).map((x) => x[0]);
      return `<div class="eye-tile ${dead ? `dead ${dead.cls}` : ""} ${going || (!dead && l.drop_pending) ? "going" : ""}" data-i="${i}" data-id="${l.id}"
          ${dead?.cls === "gone" ? 'title="다시 누르면 되살림"' : ""}>
        <div class="eye-ph"><img loading="lazy" referrerpolicy="no-referrer" src="${esc(eyeThumb(l.thumb, this.tile))}" data-full="${esc(l.thumb)}" alt=""
          onerror="if(this.dataset.full&&this.src!==this.dataset.full){this.src=this.dataset.full}else{this.classList.add('broken')}">
          ${l.eye_at && !dead ? '<span class="eye-seen" title="눈검수 한 원본">✓</span>' : ""}
          ${dead ? `<div class="eye-dead"><b>${esc(dead.label)}</b>${dead.sub ? `<span>${esc(dead.sub)}</span>` : ""}</div>`
            : going || l.drop_pending ? '<span class="eye-tag">내리는 중</span>' : ""}
          <span class="eye-check">삭제 예정</span></div>
        <div class="eye-nm" title="${esc(l.name)}" style="--fs:${eyeFont(words.length ? words : eyeWords(l.name)).toFixed(3)}"><span>${this.nameHtml(l)}</span></div></div>`;
    }).join("") : `<p class="muted pad">${this.todo ? "눈검수 안 한 복사본이 없습니다. 다 봤습니다." : "복사본이 없습니다."}</p>`;
    eyeFit(grid);
    this.paintSel();
  },

  paintPage() {
    const r = this.res || {};
    $("#eye-pg").textContent = this.rows.length ? num(r.page) : "0";
    $("#eye-pgs").textContent = num(r.pages || 0);
    $("#eye-pstat").innerHTML = `${this.kind === "source" ? "원본" : "복사본"} ${num(r.total || 0)}건${this.todo ? " (안 한 것만)" : ""}` + (r.done ? ' · <b class="c-ok">✓ 이 쪽은 눈검수 완료</b>' : "");
    $("#eye-prev").disabled = !r.has_prev;
    this.paintNext();
    this.paintStats();
  },

  /* 완료 버튼: 고른 게 있으면 '고른 N개 삭제하고 다음 쪽'(빨강) */
  paintNext() {
    const b = $("#eye-next");
    if (!b) return;
    const n = this.sel.size, more = this.res?.has_next;
    b.classList.toggle("del", n > 0);
    b.innerHTML = n ? `✓ 고른 ${num(n)}개 삭제하고<br>${more ? "다음 쪽 →" : "이 쪽 완료"}<small>${this.kind === "source" ? "원본·복사본 모두" : "원본까지"} · 되돌리기 가능</small>`
      : `✓ 이 쪽 눈검수 완료<small>${more ? "다음 쪽 →" : "마지막 쪽"}</small>`;
    b.disabled = !this.rows.length;
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
    $("#eye-seln").innerHTML = n ? `삭제 예정 <b>${num(n)}</b>개 <span class="muted small">(다시 누르면 풀림)</span>` : '<span class="muted">지울 사진을 눌러 고르세요</span>';
    $("#eye-del").disabled = !n;
    $("#eye-clear").disabled = !n;
    const u = this.undos[this.undos.length - 1];
    const ub = $("#eye-undo");
    ub.hidden = !u;
    if (u) ub.innerHTML = `↶ 되돌리기 <span>방금 지운 ${num(u.n)}개${this.undos.length > 1 ? ` (${this.undos.length}번 남음)` : ""}</span>`;
    this.paintNext();
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
      const r = await App.api("/api/eye/mark", { json: { ids, kind: this.kind, store_id: this.storeId, last_id: ids[ids.length - 1], size: this.size, todo: this.todo } });
      Object.assign(this.state, { today_seen: r.today_seen, today_deleted: r.today_deleted, sec_per_item: r.sec_per_item });
      return true;
    } catch (e) { App.toast(e.message, true); return false; }
  },

  /* 미뤄 둔 네이버 내리기 시작 → 알릴 말 (없으면 "") */
  async commit(set) {
    if (!set.size) return "";
    const ids = [...set];
    set.clear();
    try {
      const r = await App.api("/api/eye/commit", { json: { ids } });
      if (r.started) return `앞에서 지운 판매 중 ${num(r.count)}건을 네이버에서 내리는 중`;
      if (r.queued) return `판매 중 ${num(r.count)}건은 내리기 대기 (지금 등록이 도는 중 — 끝난 뒤 시작에서 '내리기')`;
      if (r.error) return r.error;
    } catch (e) { return e.message; }
    return "";
  },

  /* 지운 뒤: 칸에 결과 표시(자리는 그대로)·되돌리기 기록·통계. 판매 중인 것의 내리기는 이 쪽 몫으로 미룸 */
  async afterDelete(picked, since, r) {
    const ids = picked.map((l) => l.id);
    const now = {};
    const src = this.kind === "source";
    try {
      for (let i = 0; i < ids.length; i += 400) {
        const d = await App.api(`/api/${src ? "sources" : "listings"}?${new URLSearchParams({ ids: ids.slice(i, i + 400).join(","), size: 500 })}`);
        d.rows.forEach((x) => { now[x.id] = x; });
      }
    } catch (e) { /* 표시만 못 함 */ }
    for (const id of ids) {
      const x = now[id];
      if (!x) this.dead.set(id, { label: "삭제됨", cls: "gone" });
      else if (src ? x.drop_pending : x.op === "delete" && ["planned", "queued", "running"].includes(x.status)) this.dead.set(id, { label: "삭제됨", sub: "네이버에서 내릴 예정", cls: "gone" });
      else this.dead.set(id, { label: "안 지워짐", sub: src ? "판매 이력·잠금" : x.locked ? "판매 이력·잠금" : x.origin_no ? "올라가 있음" : "", cls: "kept" });
    }
    const gone = ids.filter((id) => this.dead.get(id)?.cls === "gone");
    // 눈검수 쪽에 '삭제됨'으로 계속 남기기 (다시 열어도·이전 쪽으로 가도 그 자리)
    const goneRows = picked.filter((l) => this.dead.get(l.id)?.cls === "gone").map((l) => ({ id: l.id, source_id: l.source_id, name: l.name, thumb: l.thumb }));
    if (goneRows.length) { try { await App.api("/api/eye/dead", { json: { kind: this.kind, store_id: this.storeId, rows: goneRows } }); } catch (e) { /* 표시만 */ } }
    (r.drop_ids || []).forEach((id) => this.dropsCur.add(id));
    const goneSet = new Set(gone);
    if (gone.length) this.undos.push({ sids: [...new Set(picked.filter((l) => goneSet.has(l.id)).map((l) => l.source_id))], lids: gone, since, n: gone.length, gone: gone.length });
    this.deleted += gone.length;
    this.sel.clear();
    this.rows = this.rows.map((l) => (now[l.id] ? { ...l, ...now[l.id] } : l));
    try {
      const s = await App.api("/api/eye/deleted", { json: { store_id: this.storeId, n: gone.length } });
      Object.assign(this.state, s);
    } catch (e) { /* 통계만 */ }
    return { gone: gone.length, kept: ids.length - gone.length };
  },

  /* 이 쪽 완료 → (고른 게 있으면 확인 없이 원본까지 지우고) 다음 쪽. 복사본 번호로 이어서 — 지운 것이 있어도 밀리지 않음 */
  async next() {
    if (!this.rows.length || this._busy) return;
    this._busy = true;
    const msgs = [];
    try {
      if (this.sel.size) {
        const picked = [...this.sel.values()];
        const since = Date.now() / 1000;
        let r;
        const ids = picked.map((l) => l.id);
        try { r = await App.api("/api/chem/delete", { json: { ...(this.kind === "source" ? { ids } : { listing_filter: { ids } }), now: false } }); }
        catch (e) { App.toast(e.message, true); return; }
        const d = await this.afterDelete(picked, since, r);
        msgs.push(`${num(d.gone)}개 삭제` + (d.kept ? ` · 판매 이력·잠금으로 남긴 ${num(d.kept)}개` : "") + (d.gone ? " (↶ 되돌리기 가능)" : ""));
        App.refreshState();
      }
      if (!(await this.mark())) return;
      const c = await this.commit(this.dropsPrev);   // 앞 쪽에서 지운 판매 중인 것은 이제 내림 (한 쪽 늦게)
      if (c) msgs.push(c);
      this.dropsPrev = this.dropsCur;
      this.dropsCur = new Set();
      this.resume = null;
      this.paintResume();
      const lastId = this.rows[this.rows.length - 1].id;
      if (this.res.has_next) await this.load({ from_id: lastId + 1 });
      else { msgs.push("마지막 쪽까지 눈검수 완료"); await this.load({ from_id: this.rows[0].id }); }
      if (msgs.length) App.toast(msgs.join(" · "));
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

  /* 우클릭: 큰 사진 + 상품명 전체 + 버튼 */
  showCard(l, x, y) {
    const c = $("#eye-card");
    const named = !!l.name_id || !!l.origin_no;
    const dead = this.dead.get(l.id) || l.dead;
    const flagged = (l.kw || []).filter(([, why]) => EYE_KW[why]);
    const main = $("#eye-main").getBoundingClientRect();
    const W = Math.max(280, Math.min(520, main.width - 24, innerHeight - 230));
    c.style.width = `${W + 28}px`;
    c.innerHTML = `<div class="eye-card-img" style="height:${W}px"><img referrerpolicy="no-referrer" src="${esc(l.thumb)}" alt=""></div>
      <div class="eye-card-name">${esc(l.name)}</div>
      ${this.kind === "listing" && named && l.source_name && l.source_name !== l.name ? `<div class="small muted">원본: ${esc(l.source_name)}</div>` : ""}
      ${this.kind === "listing" && !named && !dead ? '<div class="small c-err">상품명 변경 전 (원본 이름 그대로)</div>' : ""}
      ${flagged.length ? `<div class="small eye-card-flags">${flagged.map(([w, why]) => `<em class="${EYE_KW[why][0]}">${esc(w)}</em> ${EYE_KW[why][1]}`).join(" · ")}</div>` : ""}
      <div class="small" style="margin-top:6px">${dead ? `<b class="c-err">${esc(dead.label)}</b> ` : ""}${this.kind === "source"
        ? `원본 #${l.id} · 원본가 ${num(l.price)}원 · 복사 ${num(l.n_listings || 0)}곳 ${l.eye_at ? '<span class="flag eye-ok">검수 완료</span>' : ""}<div class="muted">${esc(l.category || "")}</div>`
        : `${dead ? "" : statusBadge(l.status, l.op)} ${esc(l.seller_code || "")} · 원본 #${l.source_id} · ${num(l.final ?? l.price)}원`}</div>
      <div class="cl-row" style="margin-top:8px">
        ${dead?.cls === "gone" ? '<button class="btn sm primary" data-card-back>되살리기</button>'
          : dead ? "" : `<button class="btn sm ${this.sel.has(l.id) ? "" : "danger"}" data-card-sel>${this.sel.has(l.id) ? "삭제 예정 풀기" : "삭제 예정으로"}</button>`}
        ${l.origin_no && l.channel_no ? goLinks({ storeUrl: l.store_url, channelNo: l.channel_no }) : ""}
        <a class="btn sm" href="/api/sources/${l.source_id}/origin" target="_blank" rel="noopener noreferrer" title="엑셀 수집URL">수집한 곳 ↗</a>
        <button class="btn sm ghost" data-card-copy title="상품명 복사">상품명 복사</button></div>`;
    c.hidden = false;
    const w = c.offsetWidth, h = c.offsetHeight;
    const right = main.right;
    const left = x + 16 + w < right ? x + 16 : x - 16 - w > main.left ? x - 16 - w : Math.max(8, right - w - 8);
    c.style.left = `${left}px`;
    c.style.top = `${Math.max(8, Math.min(innerHeight - h - 8, y - h / 2))}px`;
    $("[data-card-sel]", c)?.addEventListener("click", () => { this.sel.has(l.id) ? this.sel.delete(l.id) : this.sel.set(l.id, l); this.paintSel(); this.hideCard(); });
    $("[data-card-back]", c)?.addEventListener("click", () => { this.hideCard(); this.restoreOne(l); });
    $("[data-card-copy]", c).addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(l.name); App.toast("상품명을 복사했습니다"); } catch (e) { App.toast("복사하지 못했습니다", true); }
    });
  },
  hideCard() { const c = $("#eye-card"); if (c) c.hidden = true; },

  /* 쪽을 넘기기 전에 지금 지우기 (확인 창 — '원본까지'를 끌 수 있음) */
  async remove() {
    const picked = [...this.sel.values()];
    if (!picked.length) return;
    const since = Date.now() / 1000;
    const ids = picked.map((l) => l.id);
    const r = this.kind === "source" ? await App.chemDelete({ ids }, null, { now: false })
      : await App.deleteCopies({ ids }, null, `눈검수로 고른 ${num(picked.length)}개`, { now: false });
    if (!r) return;
    await this.afterDelete(picked, since, r);
    this.paintGrid();
    this.paintStats();
  },

  /* 지운 칸 하나 되살리기 (그 칸을 다시 누름) */
  async restoreOne(l) {
    const u = this.undos.find((x) => x.lids.includes(l.id));
    const since = u ? u.since : l.dead?.at;
    if (!since) return App.toast("이 상품은 여기서 되살릴 수 없습니다 (휴지통에서 되살리세요).", true);
    let r;
    try { r = await App.api("/api/eye/undo", { json: { store_id: this.storeId, source_ids: [l.source_id], since, n: 1 } }); }
    catch (e) { return App.toast(e.message, true); }
    if (u) {
      u.lids = u.lids.filter((id) => id !== l.id);
      u.sids = u.sids.filter((x) => x !== l.source_id);
      u.n -= 1; u.gone -= 1;
      if (!u.lids.length) this.undos = this.undos.filter((x) => x !== u);
      this.deleted -= 1;
    }
    this.dead.delete(l.id);
    if (!r.restored && !r.cancelled) return App.toast("휴지통에 없어 되살리지 못했습니다 (이미 비웠거나 다시 불러온 원본).", true);
    Object.assign(this.state, { today_seen: r.today_seen, today_deleted: r.today_deleted, sec_per_item: r.sec_per_item });
    App.toast(r.dropped ? "원본은 되살렸지만 이미 네이버에서 내려가 '내림'으로 남았습니다 (복사본 화면에서 다시 올리기)" : "되살렸습니다", !!r.dropped);
    App.refreshState();
    await this.load({ from_id: this.rows[0]?.id || 0 });
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
    this.deleted -= u.gone;
    Object.assign(this.state, { today_seen: r.today_seen, today_deleted: r.today_deleted, sec_per_item: r.sec_per_item });
    App.toast(`되돌렸습니다: 휴지통에서 ${num(r.restored)}개 되살림` + (r.cancelled ? ` · 네이버 내리기 ${num(r.cancelled)}건 취소 (판매 중 그대로)` : "")
      + (r.dropped ? ` · 이미 네이버에서 내려간 ${num(r.dropped)}건은 '내림'으로 남음 (복사본 화면에서 다시 올리기)` : "")
      + (r.busy ? ` · 지금 내리는 중인 ${num(r.busy)}건은 못 멈춤` : "") + (r.skipped ? ` · 못 되살린 ${num(r.skipped)}개 (휴지통에서 확인)` : ""), !!(r.dropped || r.busy || r.skipped));
    App.refreshState();
    await this.load({ from_id: this.rows[0]?.id || 0 });
  },

  async close() {
    if (this._mt) { clearTimeout(this._mt); await this.saveMemo(); }
    const all = new Set([...this.dropsPrev, ...this.dropsCur]);
    this.dropsPrev.clear(); this.dropsCur.clear();
    const c = await this.commit(all);
    if (c) App.toast(c);
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
