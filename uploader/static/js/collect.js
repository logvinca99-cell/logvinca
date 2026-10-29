/* 상품 수집: 다른 스마트스토어의 판매 중 상품 → 수집함 (→ 상세 정리 → 원본 상품).
   진행 상황은 늘 이 화면 위쪽(지금 하는 일·남은 초·스토어별 숫자·속도·남은 시간·실시간 기록)과 오른쪽 아래에 보인다. */
"use strict";

const COLLECT_PHASE = {
  starting: ["준비 중", "s-running"], login: ["로그인 대기", "s-fail"], urls: ["URL 모으는 중", "s-running"],
  products: ["상품 수집 중", "s-running"], blocked: ["차단 대기", "s-delete"], captcha: ["캡차 확인 필요", "s-fail"],
  paused: ["일시정지", "s-delete"], limit: ["하루 한도 — 내일 이어서", "s-delete"], done: ["끝", "s-success"],
  stopped: ["중지함", "s-deleted"], ready: ["대기", "s-planned"],
};
const STORE_PHASE = { urls: "URL 모으는 중", products: "상품 수집", done: "끝", failed: "실패" };
const LOG_CLS = { ok: "c-ok", err: "c-err", warn: "c-warn", info: "" };

App.page("collect", {
  f: { job_id: "", status: "new", q: "", page: 0 },
  sel: new Set(),

  async mount(el) {
    this.sel = new Set();
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>상품 수집</h1>
        <div class="head-actions"><a class="btn" href="#settings?tab=collect">수집 설정</a></div></header>
      <section class="card pad">
        <div class="sec-head"><h2>수집 시작</h2><span class="muted small">스토어 주소만 넣으면 URL 모으기부터 상품 수집까지 자동</span></div>
        <div class="form">
          <textarea id="c-text" rows="4" spellcheck="false" placeholder="스토어 주소를 한 줄에 하나씩 — 예) https://smartstore.naver.com/스토어이름&#10;스토어 카테고리 주소(…/category/번호), 상품 주소(…/products/번호)도 됩니다"></textarea>
          <div class="c-row">
            <label class="field inline">범위 <select id="c-scope"><option value="all">전체 상품</option><option value="recent">최신 N개</option><option value="popular">인기 N개</option></select></label>
            <label class="field inline" id="c-n-box" hidden>N <input id="c-n" type="number" min="1" value="100" style="width:110px"> 개 (스토어마다)</label>
            <button class="btn primary" id="c-go">수집 시작</button>
          </div>
          <p class="muted small" style="margin:0">품절·판매중지 상품은 받지 않음(옵션 일부 품절이면 그 옵션만 뺌) · 상품명이 원본·수집함에 있는 것과 같으면 건너뜀(띄어쓰기만 다른 것 포함) ·
            가격은 고객 결제가(판매가 − 즉시할인) 한 칸 · 브랜드·제조사·모델명·원산지는 '상세페이지 참조', 상품코드는 비움.
            수집 중에도 컴퓨터를 써도 됩니다 — <b>수집용 크롬 창만 닫지 마세요</b> (최소화는 괜찮음).</p>
          <details class="c-test"><summary>셀업 엑셀로 맞춰 보기</summary>
            <p class="small muted">셀업으로 받은 엑셀을 올리면 ① 그 엑셀의 수집URL(상품 주소)만 이 프로그램으로 다시 받고, ② 끝난 뒤 칸마다(상품명·가격·썸네일·카테고리·옵션·추가상품·태그·상세 사진) 비교합니다.</p>
            <div class="c-row"><label class="btn"><input type="file" id="c-test-file" accept=".xlsx,.xls,.csv" hidden>① 엑셀의 URL로 시험 수집</label>
              <label class="btn"><input type="file" id="c-cmp-file" accept=".xlsx,.xls,.csv" hidden>② 셀업 엑셀과 비교</label></div>
          </details>
        </div>
      </section>
      <section class="card pad" id="c-live"></section>
      <section class="card table-card" id="c-box">
        <div class="pad-x"><div class="sec-head"><h2>수집함</h2>
          <span class="muted small">다음 단계: 상세 정리(공통 이미지·전화번호·상세 편집 — 곧 추가) → 원본 상품으로 넣기</span></div>
          <div class="tiles" id="c-tiles"></div>
          <div class="filters-row">
            <select id="c-job" class="sel"><option value="">모든 수집 작업</option></select>
            <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
              <input id="c-q" placeholder="상품명·주소·스토어·카테고리 검색"></div>
            <div id="c-pager" class="pager"></div>
          </div>
          <div class="bulkbar" id="c-bulk"></div>
        </div>
        <div id="c-items"></div>
      </section>
    </div>`;
    $("#c-scope").addEventListener("change", (e) => { $("#c-n-box").hidden = e.target.value === "all"; });
    $("#c-go").addEventListener("click", () => this.start());
    $("#c-test-file").addEventListener("change", (e) => this.upload(e, "/api/collect/from_excel"));
    $("#c-cmp-file").addEventListener("change", (e) => this.upload(e, "/api/collect/compare"));
    $("#c-live").addEventListener("click", (e) => this.liveClick(e));
    const f = this.f;
    $("#c-job").addEventListener("change", (e) => { f.job_id = e.target.value; f.page = 0; this.sel.clear(); this.load(); });
    let tq;
    $("#c-q").addEventListener("input", (e) => { clearTimeout(tq); tq = setTimeout(() => { f.q = e.target.value.trim(); f.page = 0; this.load(); }, 300); });
    $("#c-tiles").addEventListener("click", (e) => { const t = e.target.closest("[data-filter]"); if (t) { f.status = t.dataset.filter; f.page = 0; this.sel.clear(); this.load(); } });
    $("#c-items").addEventListener("click", (e) => this.itemsClick(e));
    $("#c-items").addEventListener("change", (e) => this.itemsChange(e));
    $("#c-bulk").addEventListener("click", (e) => this.bulkClick(e));
    this.alive = true;
    this.tick = setInterval(() => this.countdown(), 500);
    this.onDone = (t) => { if (t.kind === "collect_import") { this.sel.clear(); this.load(); } };
    App.on("task-done", this.onDone);
    await Promise.all([this.poll(), this.loadJobs(), this.load()]);
  },
  unmount() {
    this.alive = false;
    clearInterval(this.tick);
    clearTimeout(this.pollT);
    if (this.onDone) App.off("task-done", this.onDone);
  },

  async start() {
    const text = $("#c-text").value.trim();
    if (!text) return App.toast("스토어 주소를 넣어 주세요.", true);
    try {
      await App.api("/api/collect/start", { json: { text, scope: $("#c-scope").value, n: +$("#c-n").value || 0 } });
      App.toast("수집을 시작했습니다. 수집용 크롬 창이 열립니다 — 처음이면 그 창에서 네이버 로그인을 해 주세요.");
      $("#c-text").value = "";
      this.poll();
      this.loadJobs();
    } catch (e) { App.toast(e.message, true); }
  },

  async upload(e, url) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await App.api(url, { method: "POST", body: fd });
      if (url.endsWith("from_excel")) {
        App.toast(`엑셀의 상품 주소 ${num(r.count)}개로 시험 수집을 시작했습니다. 끝나면 '② 셀업 엑셀과 비교'를 누르세요.`);
        this.poll();
        this.loadJobs();
      } else this.showCompare(r);
    } catch (err) { App.toast(err.message, true); }
  },

  showCompare(r) {
    const rows = Object.entries(r.fields).map(([k, v]) => {
      const n = v.same + v.diff;
      return `<tr><td>${esc(k)}</td><td class="num c-ok">${num(v.same)}</td><td class="num ${v.diff ? "c-err" : ""}">${num(v.diff)}</td>
        <td class="num">${n ? Math.round((v.same / n) * 100) : 0}%</td></tr>
        ${v.examples.map((x) => `<tr class="cmp-ex"><td colspan="4"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.url)}</a>
          <div><b>셀업</b> ${esc(x.excel)}</div><div><b>이 프로그램</b> ${esc(x.mine)}</div></td></tr>`).join("")}`;
    }).join("");
    App.openModal({
      title: "셀업 엑셀과 비교", wide: true,
      body: `<p class="small" style="margin:0">엑셀 ${num(r.rows)}줄 중 수집함에서 같은 주소를 찾은 것 <b>${num(r.matched)}개</b>로 비교했습니다.
        ${r.missing.length ? ` 아직 이 프로그램으로 안 받은 주소 <b>${num(r.missing.length)}개</b> — '① 엑셀의 URL로 시험 수집'을 먼저 하세요.` : ""}
        다른 칸은 예시(최대 5개)를 보여 줍니다. 가격은 셀업의 '판매가 − 할인가'와 비교합니다.</p>
        <table class="grid cmp"><thead><tr><th>칸</th><th class="w-num">같음</th><th class="w-num">다름</th><th class="w-num">일치</th></tr></thead><tbody>${rows}</tbody></table>`,
      buttons: [{ label: "닫기", primary: true }],
    });
  },

  // ── 진행 상황

  async poll() {
    clearTimeout(this.pollT);
    if (!this.alive) return;
    try {
      this.o = await App.api("/api/collect");
      this.offset = this.o.live.now - Date.now() / 1000;
      this.renderLive();
    } catch (e) { /* 다음에 다시 */ }
    const running = this.o?.live?.running;
    if (this.wasRunning && !running) { this.load(); this.loadJobs(); }
    else if (running && this.o?.counts && this.lastDone !== this.o.counts.done) { this.lastDone = this.o.counts.done; this.loadSoft(); }
    this.wasRunning = running;
    this.pollT = setTimeout(() => this.poll(), running ? 1500 : 6000);
  },

  countdown() {
    const lv = this.o?.live;
    const el = $("#c-until");
    if (!lv || !el) return;
    const now = Date.now() / 1000 + (this.offset || 0);
    el.textContent = lv.until && lv.until > now + 0.5 ? `${lv.until_what || "다음"}까지 ${dur(lv.until - now)}` : "";
    const ago = $("#c-since");
    if (ago && lv.since && lv.running) ago.textContent = `시작한 지 ${dur(now - lv.since)}`;
  },

  renderLive() {
    const o = this.o, lv = o.live, job = o.job, c = o.counts;
    const box = $("#c-live");
    if (!box) return;
    if (!job) { box.innerHTML = '<p class="muted" style="margin:0">아직 수집한 적이 없습니다. 위에 스토어 주소를 넣고 시작하세요.</p>'; return; }
    const phase = lv.running ? lv.phase : job.status;
    const [plabel, pcls] = COLLECT_PHASE[phase] || [phase, "s-planned"];
    const stores = o.stores || [];
    const cur = stores.find((s) => ["urls", "products"].includes(s.phase)) || stores[stores.length - 1];
    const tot = c ? c.total : 0, fin = c ? c.total - c.pending : 0;
    const pct = (a, b) => (b ? Math.min(100, (a / b) * 100) : 0);
    const resumable = !lv.running && ["paused", "stopped", "ready"].includes(job.status);
    box.innerHTML = `
      <div class="sec-head"><h2>진행 상황 <span class="muted small">· ${esc(job.title)} (작업 #${job.id})</span></h2>
        <span class="c-ctl">${lv.running
          ? `${lv.phase === "paused" ? '<button class="btn sm primary" data-c="resume">이어서</button>' : '<button class="btn sm" data-c="pause">일시정지</button>'}
             <button class="btn sm" data-c="stop">중지</button> <button class="btn sm" data-c="front">크롬 창 앞으로</button>`
          : resumable ? `<button class="btn sm primary" data-c="resume" data-job="${job.id}">이어서 (남은 것부터)</button>` : ""}</span></div>
      ${lv.alert ? `<div class="notice err c-alert"><b>⚠ ${esc(lv.alert)}</b>
        ${["captcha", "login"].includes(lv.phase) ? ' <button class="btn sm" data-c="front">크롬 창 앞으로</button> <button class="btn sm" data-c="retry">풀었어요 — 다시 시도</button>' : ""}</div>` : ""}
      <div class="c-now"><span class="badge ${pcls}">${esc(plabel)}</span>
        <b>${esc(lv.running ? lv.msg : ({ done: "끝났습니다", paused: "멈춤 — '이어서'로 남은 것부터 계속합니다", stopped: "중지함 — '이어서'로 남은 것부터 계속합니다", ready: "시작 전" }[job.status] || ""))}</b>
        <span class="c-until" id="c-until"></span></div>
      ${lv.running && lv.phase !== "urls" && lv.url ? `<div class="c-cur small">지금 상품: ${lv.name ? `<b>${esc(lv.name)}</b> · ` : ""}<a href="${esc(lv.url)}" target="_blank" rel="noopener">${esc(lv.url)}</a></div>` : ""}
      <div class="c-bars">
        <div><div class="small muted">${cur ? `이번 스토어 [${esc(cur.slug)}] ${num(cur.total - cur.pending)} / ${num(cur.total)}` : ""}</div>
          <div class="bar"><div class="bar-ok" style="width:${cur ? pct(cur.total - cur.pending, cur.total) : 0}%"></div></div></div>
        <div><div class="small muted">전체 ${num(fin)} / ${num(tot)} · 스토어 ${num(lv.running ? lv.store_no : stores.filter((s) => ["done", "failed"].includes(s.phase)).length)} / ${num(stores.length)}</div>
          <div class="bar"><div class="bar-ok" style="width:${pct(fin, tot)}%"></div></div></div>
      </div>
      <div class="c-nums">
        <span>수집 <b class="c-ok">${num(c?.done)}</b></span><span>품절 건너뜀 <b>${num(c?.soldout)}</b></span>
        <span>이름 중복 건너뜀 <b>${num(c?.dup)}</b></span><span>실패 <b class="${c?.fail ? "c-err" : ""}">${num(c?.fail)}</b></span>
        <span>남음 <b>${num(c?.pending)}</b></span>
        <span>속도 <b>분당 ${o.per_min}개</b></span>
        <span>예상 남은 시간 <b>${o.eta ? dur(o.eta) : "-"}</b>${o.eta ? ` (끝 ${when(Date.now() / 1000 + o.eta)})` : ""}</span>
        <span>오늘 <b>${num(o.today)}</b>${o.daily_limit ? ` / 한도 ${num(o.daily_limit)}` : ""}</span>
        <span class="muted" id="c-since"></span>
      </div>
      <table class="grid c-stores"><thead><tr><th>스토어</th><th>단계</th><th class="w-num">쪽</th><th class="w-num">URL</th><th class="w-num">수집</th>
        <th class="w-num">품절</th><th class="w-num">중복</th><th class="w-num">실패</th><th class="w-num">남음</th><th>시작 · 걸린 시간</th></tr></thead>
        <tbody>${stores.map((s) => `<tr class="${cur && s.id === cur.id && lv.running ? "c-curow" : ""}">
          <td><a href="https://${esc(s.host)}/${esc(s.slug)}" target="_blank" rel="noopener">${esc(s.slug)}</a>${s.category ? ` <span class="muted small">카테고리 ${esc(s.category)}</span>` : ""}${s.kind === "urls" ? ' <span class="muted small">(상품 주소)</span>' : ""}</td>
          <td>${esc(!s.started_at && s.phase !== "failed" ? "대기" : STORE_PHASE[s.phase] || s.phase)}${s.error ? ` <span class="c-err small">${esc(s.error)}</span>` : ""}</td>
          <td class="num">${num(s.pages)}</td><td class="num">${num(s.total)}</td><td class="num c-ok">${num(s.done)}</td><td class="num">${num(s.soldout)}</td>
          <td class="num">${num(s.dup)}</td><td class="num ${s.fail ? "c-err" : ""}">${num(s.fail)}</td><td class="num">${num(s.pending)}</td>
          <td class="small">${s.started_at ? when(s.started_at) : "-"}${s.started_at ? ` · ${dur((s.ended_at || Date.now() / 1000 + (this.offset || 0)) - s.started_at)}` : ""}</td></tr>`).join("")}</tbody></table>
      <h3 class="sec-title" style="margin:14px 0 6px">실시간 기록 <span class="muted small">(최근 것이 위)</span></h3>
      <div class="c-log">${(lv.logs || []).map((l) => `<div class="${LOG_CLS[l.level] || ""}"><span class="muted">${stamp(l.at).slice(11)}</span>${l.store ? ` <b>[${esc(l.store)}]</b>` : ""} ${esc(l.text)}</div>`).join("") || '<span class="muted">기록 없음</span>'}</div>
      <p class="muted small" style="margin:8px 0 0">못 읽은 상품과 처음 몇 개는 진단 파일로 남습니다: <code>${esc(o.debug_dir)}</code> — 수집이 이상하면 이 폴더를 압축해 보내 주세요.</p>`;
    this.countdown();
  },

  async liveClick(e) {
    const b = e.target.closest("[data-c]");
    if (!b) return;
    const act = b.dataset.c;
    try {
      if (act === "pause") await App.api("/api/collect/pause", { json: { on: true } });
      if (act === "resume") await App.api("/api/collect/resume", { json: { job_id: +(b.dataset.job || this.o?.job?.id || 0) } });
      if (act === "stop") {
        if (!confirm("수집을 중지할까요? 지금 상품까지 저장하고 멈춥니다. 나중에 '이어서'로 남은 것부터 계속할 수 있습니다.")) return;
        await App.api("/api/collect/stop", { json: {} });
      }
      if (act === "front") await App.api("/api/collect/front", { json: {} });
      if (act === "retry") await App.api("/api/collect/retry", { json: {} });
      setTimeout(() => this.poll(), 400);
    } catch (err) { App.toast(err.message, true); }
  },

  // ── 수집함

  async loadJobs() {
    try {
      const js = await App.api("/api/collect/jobs");
      const sel = $("#c-job");
      if (!sel) return;
      sel.innerHTML = '<option value="">모든 수집 작업</option>' + js.map((j) =>
        `<option value="${j.id}">#${j.id} ${esc(j.title)} · ${when(j.created_at)} · 수집 ${num(j.done)}</option>`).join("");
      sel.value = this.f.job_id;
    } catch (e) { /* 무시 */ }
  },

  loadSoft() { if (!this.sel.size) this.load(); },   // 수집 중엔 고른 게 없을 때만 목록을 새로

  async load() {
    const f = this.f;
    const size = App.pageSize("collect");
    const d = await App.api(`/api/collect/items?${new URLSearchParams({ job_id: f.job_id, status: f.status, q: f.q, page: f.page + 1, size })}`);
    this.rows = d.rows;
    this.total = d.total;
    $("#c-tiles").innerHTML = tilesHtml([
      { key: "new", label: "정리 전 (원본으로 넣기 전)", dot: "var(--info)" },
      { key: "sent", label: "원본으로 넣음", dot: "var(--ok)" },
    ], d.counts, f.status);
    App.pagerBar($("#c-pager"), { page: f.page, size, total: d.total, onPage: (p) => { f.page = p; this.load(); },
      onSize: (n) => { App.savePageSize("collect", n); f.page = 0; this.load(); } });
    $("#c-items").innerHTML = d.rows.length ? `<table class="grid"><thead><tr>
        <th class="w-check"><input type="checkbox" data-all ${d.rows.every((r) => this.sel.has(r.id)) ? "checked" : ""}></th>
        <th class="w-thumb"></th><th>상품명</th><th class="w-num">가격(고객 결제가)</th><th class="w-num">옵션</th><th class="w-num">사진</th>
        <th>카테고리</th><th>스토어</th><th>상세</th><th>수집</th><th>상태</th></tr></thead><tbody>
        ${d.rows.map((r) => `<tr data-id="${r.id}">
          <td class="w-check"><input type="checkbox" data-sel="${r.id}" ${this.sel.has(r.id) ? "checked" : ""}></td>
          <td class="w-thumb">${img(r.thumb)}</td>
          <td><a href="#" data-open="${r.id}">${esc(r.name)}</a> <a class="muted small" href="${esc(r.url)}" target="_blank" rel="noopener">원래 상품 ↗</a></td>
          <td class="num">${num(r.price)}원</td><td class="num">${num(r.option_count)}</td><td class="num">${num(r.image_count)}</td>
          <td class="small">${esc(r.category)}</td><td class="small">${esc(r.store_slug)}</td><td class="small muted">${esc(r.detail_from)}</td>
          <td class="small">${when(r.created_at)}</td>
          <td>${r.status === "sent" ? `<a class="badge s-success" href="#inventory" data-src="${r.source_id}">원본 #${r.source_id}</a>` : '<span class="badge s-planned">정리 전</span>'}</td></tr>`).join("")}
      </tbody></table>` : '<p class="muted pad-x" style="padding-bottom:14px">수집한 상품이 없습니다.</p>';
    this.renderBulk();
  },

  renderBulk() {
    const n = this.sel.size;
    const what = n ? `고른 ${num(n)}개` : `${this.f.job_id ? "이 작업" : "모든 작업"}의 ${this.f.status === "sent" ? "원본으로 넣은" : "정리 전"} ${num(this.total || 0)}개 전체`;
    $("#c-bulk").innerHTML = `<span class="small">${esc(what)}</span>
      ${this.f.status === "new" ? '<button class="btn sm primary" data-b="send">원본 상품으로 넣기</button>' : ""}
      <button class="btn sm" data-b="excel">엑셀로 저장 (셀업 양식)</button>
      ${this.f.status === "new" ? '<button class="btn sm danger" data-b="delete">수집함에서 지우기</button>' : ""}
      ${n ? '<button class="btn sm ghost" data-b="clear">고른 것 풀기</button>' : ""}`;
  },

  target() {
    return this.sel.size ? { ids: [...this.sel] } : { job_id: this.f.job_id || undefined, status: this.f.status };
  },

  async bulkClick(e) {
    const b = e.target.closest("[data-b]");
    if (!b) return;
    const act = b.dataset.b, t = this.target(), n = this.sel.size || this.total || 0;
    if (act === "clear") { this.sel.clear(); this.load(); return; }
    if (!n) return App.toast("대상이 없습니다.", true);
    if (act === "excel") {
      const q = new URLSearchParams(t.ids ? { ids: t.ids.join(",") } : { job_id: t.job_id || "", status: t.status });
      window.location.href = `/api/collect/export?${q}`;
      return;
    }
    if (act === "send") {
      if (!confirm(`${num(n)}개를 원본 상품으로 넣을까요?\n같은 상품명(띄어쓰기 무시)의 원본이 이미 있으면 넣지 않습니다. 넣은 뒤에는 원래 하던 대로 상품명 변경 → 복사로 이어 가면 됩니다.`)) return;
      await App.startTask(App.api("/api/collect/to_sources", { json: t }));
      return;
    }
    if (act === "delete") {
      if (!confirm(`${num(n)}개를 수집함에서 지울까요? (원본으로 넣은 것은 그대로)`)) return;
      try {
        const r = await App.api("/api/collect/items/delete", { json: t });
        App.toast(`${num(r.count)}개를 지웠습니다.`);
        this.sel.clear();
        this.load();
      } catch (err) { App.toast(err.message, true); }
    }
  },

  itemsChange(e) {
    if (e.target.matches("[data-all]")) {
      for (const r of this.rows) e.target.checked ? this.sel.add(r.id) : this.sel.delete(r.id);
      $$("[data-sel]", $("#c-items")).forEach((x) => { x.checked = e.target.checked; });
    } else if (e.target.matches("[data-sel]")) {
      const id = +e.target.dataset.sel;
      e.target.checked ? this.sel.add(id) : this.sel.delete(id);
    }
    this.renderBulk();
  },

  itemsClick(e) {
    const a = e.target.closest("[data-open]");
    if (a) { e.preventDefault(); this.openItem(+a.dataset.open); }
    const s = e.target.closest("[data-src]");
    if (s) { e.preventDefault(); location.hash = "#inventory"; setTimeout(() => App.pages.inventory?.openSource?.(+s.dataset.src), 600); }
  },

  async openItem(id) {
    let it;
    try { it = await App.api(`/api/collect/items/${id}`); } catch (e) { return App.toast(e.message, true); }
    const r = it.row, opt = r["옵션상품"] || {}, combos = opt.optionCombinations || [];
    const gn = Object.values(opt.optionCombinationGroupNames || {}).filter(Boolean);
    const sup = (r["추가상품"] || {}).supplementProducts || [];
    App.openDrawer({
      title: r["상품명"], sub: `수집함 #${id} · ${it.store_slug} · ${when(it.created_at)}`,
      tabs: [
        { key: "info", label: "정보", render: (b) => {
          b.innerHTML = `<div class="tpl-imgs">${(r["썸네일"] || []).map((u) => img(u)).join("")}</div>
            <dl class="kv">
              <dt>원래 상품</dt><dd><a href="${esc(r["수집URL"])}" target="_blank" rel="noopener">${esc(r["수집URL"])}</a></dd>
              <dt>가격</dt><dd>${num(r["판매가"])}원 <span class="muted small">(고객 결제가 · 할인가 칸은 비움)</span></dd>
              <dt>카테고리</dt><dd>${esc(r["카테고리"] || "-")}</dd>
              <dt>배송비</dt><dd>${r["배송비"] ? num(r["배송비"]) + "원" : "무료"}</dd>
              <dt>태그</dt><dd>${(r["상품태그"] || []).map((t) => `<span class="pill">${esc(t.text)}</span>`).join(" ") || "-"}</dd>
              <dt>브랜드·제조사·모델명·원산지</dt><dd>${esc(r["브랜드"])} · ${esc(r["제조사"])} · ${esc(r["모델명"])} · ${esc(r["원산지"])}</dd>
              <dt>상세</dt><dd>${esc(it.detail_from)}에서 읽음</dd>
            </dl>
            <h3 class="sec-title">옵션 ${num(combos.length)}개${gn.length ? ` <span class="muted small">(${esc(gn.join(" / "))})</span>` : ""}</h3>
            ${combos.length ? `<table class="grid"><thead><tr><th>옵션</th><th class="w-num">추가금</th><th class="w-num">재고</th></tr></thead><tbody>
              ${combos.map((x) => `<tr><td>${esc([x.optionName1, x.optionName2, x.optionName3].filter(Boolean).join(" / "))}</td>
                <td class="num">${num(x.price)}원</td><td class="num">${num(x.stockQuantity)}</td></tr>`).join("")}</tbody></table>` : '<p class="muted small">옵션 없음</p>'}
            ${sup.length ? `<h3 class="sec-title">추가상품 ${num(sup.length)}개</h3><ul class="small">${sup.map((x) => `<li>${esc(x.groupName)} · ${esc(x.name)} · ${num(x.price)}원</li>`).join("")}</ul>` : ""}`;
        } },
        { key: "detail", label: "상세 (휴대폰)", render: (b) => {
          b.innerHTML = `<p class="muted small" style="margin:0">받은 상세를 휴대폰 너비로 그대로 그렸습니다. 원본으로 넣은 뒤 올릴 때 옵션표 그림·방문 알림 지우기 등이 적용됩니다.</p>
            <div class="mob-frame"><iframe sandbox="allow-same-origin" title="상세"></iframe></div>`;
          $("iframe", b).srcdoc = `<!doctype html><meta charset="utf-8"><style>body{margin:0;padding:0 12px;font:15px/1.5 sans-serif}img{max-width:100%;height:auto}</style>${r["상세설명"] || ""}`;
        } },
      ],
    });
  },
});
