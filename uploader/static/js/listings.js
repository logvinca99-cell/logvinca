/* 등록: 계획된 건 목록, 등록 실행(여러 스토어 동시), 진행 상황 */
"use strict";

const RUN_KINDS = [["create", "등록"], ["refresh", "최신화"], ["reupload", "다시 올리기"], ["delete", "내리기"], ["fail", "실패 재시도"]];

const LST_TILES = [
  { key: "all", label: "전체", dot: "var(--text-2)", count: "all_" },
  { key: "noname", label: "상품명 변경 필요", dot: "var(--err)" },
  { key: "named", label: "올릴 준비", dot: "var(--info)", title: "상품명을 바꿨고 + 검수 완료 + 아직 안 올린 등록 대기" },
  { key: "live", label: "판매 중", dot: "var(--ok)" },
  { key: "fail", label: "실패", dot: "var(--err)" },
  { key: "sold", label: "판매 이력 있음", dot: "var(--warn)" },
  { key: "locked", label: "잠금", dot: "var(--info)" },
  { key: "deleted", label: "내림", dot: "var(--dup)" },
  { key: "eye_done", label: "검수 완료", dot: "var(--ok)" },
  { key: "eye_todo", label: "미검수", dot: "var(--muted)", title: "눈검수 안 한 원본의 복사본 — 새로 못 올림" },
  { key: "nv_bad", label: "판매중지·금지", dot: "var(--err)", title: "판매중지·판매금지·스토어에 없음 등 — 최신화하지 않음" },
];
// 네이버 상태 (스토어처럼): 판매 중은 표시 안 함, 품절은 노랑, 판매중지·판매금지·스토어에 없음 등은 빨강
const NV_LABEL = { SALE: "판매 중", OUTOFSTOCK: "품절", SUSPENSION: "판매중지", PROHIBITION: "판매금지", WAIT: "판매 대기", CLOSE: "판매 종료",
  UNADMISSION: "승인 대기", REJECTION: "승인 거부", DELETE: "스토어에 없음", GONE: "스토어에 없음" };
function nvFlag(l) {
  if (!l.origin_no || l.status === "deleted") return "";
  const at = l.nv_at ? ` · ${when(l.nv_at)} 확인` : "";
  if (!l.nv_status) return "";
  let out = "";
  if (l.nv_status !== "SALE") {
    const warn = l.nv_status === "OUTOFSTOCK";
    out += `<span class="flag ${warn ? "warn" : "bad"}" title="네이버 판매 상태${at}${warn ? "" : " — 최신화하지 않습니다 (지우고 다시 올리면 다시 판매되므로)"}">${esc(NV_LABEL[l.nv_status] || l.nv_status)}</span>`;
  }
  if (l.nv_disp === "SUSPENSION") out += `<span class="flag warn" title="네이버 전시 상태: 전시중지(고구마)${at}">전시중지</span>`;
  return out;
}

App.page("listings", {
  async mount(el, params) {
    this._live = false;   // 다른 화면에 다녀오면 진행 창 틀을 다시 그림 ([중단]·[일시정지] 버튼이 사라지지 않게)
    this.el = el;
    if (!params.store_id) return this.renderStores(el);
    this.f = { status: "all", store_id: params.store_id, q: "", age_days: "", ...params };
    delete this.f.open;
    this.page = 0;
    this.size = App.pageSize("listings");
    this.sel = new Set();
    this.selAll = false;
    const store = App.stores.find((s) => s.id === +params.store_id);
    el.innerHTML = `<div class="page">
      <header class="page-head">
        <div class="store-head"><h1>복사본</h1>
          <select id="l-store" class="sel" title="다른 스토어로 바꾸기">${byBusiness(App.stores).map(([biz, ss]) => `<optgroup label="${esc(biz)}">${ss.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</optgroup>`).join("")}</select>
          <a class="btn ghost sm" href="#listings">스토어 목록</a>${store ? storeLinks(store) : ""}</div>
        <div class="head-actions">
          <button class="btn primary" id="l-eye" title="썸네일만 그리드로 보며 이상한 상품을 골라 지우기">눈검수</button>
          <button class="btn" id="l-bulk" title="이 스토어 복사본의 손님 가격·상품명을 엑셀로 한꺼번에 고치기 (판매 중이면 지우지 않고 네이버 값만 바꿈)">일괄 수정 (엑셀)</button>
          <button class="btn" id="l-nv" title="네이버 상품 목록을 받아 판매 중 복사본마다 판매 중·품절·판매중지·판매금지·스토어에 없음을 표시 (최신화 직전에도 자동으로 확인)">네이버 상태 확인</button>
          <label class="btn" title="아바닛 등 주문 수집 웹에서 내려받은 주문 파일"><input type="file" id="l-sales-file" accept=".xlsx,.xlsm,.csv" hidden>판매 이력 파일 가져오기</label>
          <a class="btn" href="#orders" title="판매자센터 주문을 가져오고 기간·스토어별로 보기">판매 현황</a>
        </div></header>
      <div class="card run" id="l-run"></div>
      <div id="l-sales"></div>
      <div id="l-push"></div>
      <div class="tiles" id="l-tiles"></div>
      <div class="filters-row">
        <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
          <input id="l-q" placeholder="상품명·관리코드·상품번호 검색"></div>
        <select id="l-age" class="sel"><option value="">올린 날 전체</option><option value="7">올린 지 7일 넘음</option>
          <option value="30">30일 넘음</option><option value="60">60일 넘음</option><option value="90">90일 넘음</option></select>
      </div>
      <div class="listbar" id="l-bar"></div>
      <div class="card table-card">
        <table class="grid"><thead><tr><th class="w-check"></th>
          <th class="w-thumb"></th><th>등록 상품명 <span class="muted small" style="font-weight:400">(원본과 비교)</span>${ND_LEGEND}</th>
          <th class="w-links">바로 가기</th><th class="w-round">관리코드 · 올린 날</th><th class="w-num">손님 가격</th><th class="w-status">상태</th></tr></thead><tbody id="l-rows"></tbody></table>
        <div class="pg-foot"><div class="pg" id="l-pager"></div></div>
      </div>
    </div>`;
    $("#l-store").value = String(params.store_id);
    $("#l-eye").addEventListener("click", () => Eye.open({ storeId: +this.f.store_id, storeName: store?.name || "", filter: this.query(),
      after: (r) => { if (r.deleted) this.clearSel(); this.estKey = ""; this.load(); } }));
    $("#l-nv").addEventListener("click", () => App.startTask(App.api("/api/listings/nvcheck", { json: { store_id: +this.f.store_id } })));
    $("#l-bulk").addEventListener("click", () => this.bulkEdit(store));
    if (!store) App.toast("스토어를 찾지 못했습니다.", true);
    $("#l-age").value = this.f.age_days || "";
    this.bind();
    this.onRun = (r) => this.renderRun(r);
    this.onDone = () => { this.estKey = ""; this.load(); };
    App.on("run", this.onRun);
    App.on("run-done", this.onDone);
    App.on("task-done", this.onDone);
    await this.load();
    this.renderRun(App.run);
    if (params.open) this.openListing(+params.open);
  },
  unmount() {
    App.off("run", this.onRun); App.off("run-done", this.onDone); App.off("task-done", this.onDone);
    clearInterval(this.timer);
  },

  /* 복사본 첫 화면: 스토어를 먼저 고른다 (한 번에 다 보이면 어느 스토어인지 헷갈려 실수하기 쉬움) */
  async renderStores(el) {
    const ss = await App.api("/api/listings/stores");
    const run = App.run?.running ? App.run : null;
    const runSt = Object.fromEntries((run?.stores || []).map((x) => [x.id, x]));
    const big = (n, label, cls = "") => `<div class="sc-big ${n ? cls : "zero"}"><b>${num(n)}</b><span>${label}</span></div>`;
    const card = (s) => {
      const r = runSt[s.id];
      return `<div class="store-card sc2 ${s.enabled ? "" : "off"} ${regionCls(s)} ${r ? "running" : ""}" data-sid="${s.id}" role="button" tabindex="0">
        <div class="sc-head"><span class="code">${esc(s.code)}</span><b class="sc-name">${esc(s.name)}</b>
          ${s.ship_region ? `<span class="region-tag">${REGION[s.ship_region]}</span>` : ""}${s.enabled ? "" : '<span class="flag">사용 중지</span>'}</div>
        ${r ? `<div class="sc-run">● 지금 처리 중 · ${num(r.done || 0)} / ${num(r.total || 0)}${r.status ? ` · ${esc(r.status)}` : ""}</div>` : ""}
        <div class="sc-bigs">
          ${big(s.noname, "상품명 변경 필요", "bad")}
          ${big(s.named || 0, "올릴 준비 됨 (이름·검수 완료)", "ready")}
          ${big(s.live, "판매 중", "live")}
        </div>
        <div class="sc-small">
          ${s.p_refresh ? `<span class="pill-s">최신화 대기 <b>${num(s.p_refresh)}</b></span>` : ""}
          ${s.p_delete ? `<span class="pill-s">내리기 대기 <b>${num(s.p_delete)}</b></span>` : ""}
          ${s.fail ? `<span class="pill-s bad">실패 <b>${num(s.fail)}</b></span>` : ""}
          <span class="muted">복사본 ${num(s.all_)} · 남은 자리 ${num(s.free)}${s.last_at ? ` · 마지막 작업 ${age(s.last_at)}` : ""}</span>
        </div>
        ${storeLinks(s)}
      </div>`;
    };
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>복사본 · 스토어 고르기</h1></header>
      <p class="muted" style="margin:0">작업할 스토어를 먼저 고르세요. 그 스토어의 복사본만 보입니다. 빨간 숫자(상품명 변경 필요)가 먼저 할 일입니다.</p>
      ${run ? `<div class="notice info"><b>지금 처리 중</b> · ${num(run.done)} / ${num(run.total)}건 — 파랗게 표시된 스토어</div>` : ""}
      <div class="sc-groups">${byBusiness(ss).map(([biz, list]) => `<section class="sc-group"><h2 class="sc-group-title">${esc(biz)} <span class="muted small">스토어 ${list.length}</span></h2>
        <div class="store-cards">${list.map(card).join("")}</div></section>`).join("")
        || '<p class="muted">스토어가 없습니다. <a href="#stores">스토어</a>에서 먼저 추가하세요.</p>'}</div>
    </div>`;
    $$(".store-card", el).forEach((b) => b.addEventListener("click", (e) => { if (!e.target.closest("a")) App.go(`#listings?store_id=${b.dataset.sid}`); }));
  },

  /* 다른 화면에서 복사본 하나로: 그 스토어 복사본 화면을 열고 그 건을 띄운다 */
  async goto(id) {
    try {
      const l = await App.api(`/api/listings/${id}`);
      App.go(`#listings?store_id=${l.store_id}&open=${id}`);
    } catch (e) { App.toast(e.message, true); }
  },

  /* 시작 범위: 이 스토어 전체 / 고른 것만 / 지금 보이는 조건만 + 종류(등록·최신화·내리기·실패 재시도) */
  runScope() {
    const base = { store_id: this.f.store_id, kinds: [...(this.runKinds ||= new Set(RUN_KINDS.map((k) => k[0])))] };
    const range = this.runRange || "store";
    if (range === "sel") return this.selAll ? { ...this.query(), visible: true, kinds: base.kinds } : { ...base, ids: [...this.sel] };
    if (range === "visible") return { ...this.query(), visible: true, kinds: base.kinds };
    return base;
  },

  query() {
    const f = { ...this.f };
    Object.keys(f).forEach((k) => (f[k] === "" || f[k] == null) && delete f[k]);
    if (f.status === "all") delete f.status;
    return f;
  },

  async load() {
    const qs = new URLSearchParams({ ...this.query(), page: this.page, size: this.size });
    const res = await App.api(`/api/listings?${qs}`);
    this.counts = res.counts || {};
    this.rows = res.rows;
    this.total = res.total;
    $("#l-sales").innerHTML = this.counts.need_sales ? `<div class="notice warn" style="margin-bottom:10px">판매 중 상품 <b>${num(this.counts.need_sales)}</b>개는
      <b>판매 이력 확인 전</b>이라 최신화·내리기를 하지 않습니다 (팔린 상품을 지우지 않게). <button class="btn tiny primary" id="l-sales-go">판매 이력 확인</button></div>` : "";
    $("#l-sales-go")?.addEventListener("click", () => App.salesConfirm(+this.f.store_id, () => this.load()));
    App.api(`/api/listings/push_pending?store_id=${this.f.store_id}`).then((p) => {   // 네이버 반영 대기 (가격·상품명 바꾸기를 못 보낸 것)
      const box = $("#l-push");
      if (!box) return;
      const n = (p.price || 0) + (p.name || 0);
      box.innerHTML = n ? `<div class="notice warn" style="margin-bottom:10px">네이버 반영 대기 <b>${num(n)}</b>건 (가격 ${num(p.price)} · 상품명 ${num(p.name)}) —
        실패했거나 아직 못 보낸 가격·상품명 바꾸기입니다. <button class="btn tiny primary" id="l-push-go">네이버 반영 다시 시도</button></div>` : "";
      $("#l-push-go")?.addEventListener("click", async () => {
        if (!await App.yes("네이버 반영 다시 시도", `대기 중인 ${num(n)}건의 네이버 가격·상품명을 다시 보냅니다 (상품은 지우지 않음).`, { label: "다시 보내기" })) return;
        App.startTask(App.api("/api/listings/push_retry", { json: { store_id: +this.f.store_id } }));
      });
    }).catch(() => {});
    const active = this.f.eye ? `eye_${this.f.eye}` : this.f.nv === "bad" ? "nv_bad" : this.f.status;
    $("#l-tiles").innerHTML = tilesHtml(LST_TILES.filter((t) => !t.only || this.counts[t.key] || active === t.key), { ...this.counts, all: this.counts.all_ }, active);
    $("#l-rows").innerHTML = res.rows.length ? res.rows.map((l) => this.rowHtml(l)).join("")
      : `<tr class="empty-row"><td colspan="7">${this.counts.all_ ? "조건에 맞는 건이 없습니다."
        : '이 스토어에 복사본이 없습니다. <a href="#inventory">원본 상품</a>에서 원본을 고르고 <b>다른 스토어로 복사</b>를 누르세요.'}</td></tr>`;
    this.renderBar();
    if (!App.run?.running) this.renderIdle();
  },

  pagerOpts() {
    return { page: this.page, size: this.size, total: this.total, unit: "건",
      onPage: (p) => { this.page = p; this.load(); window.scrollTo(0, 0); },
      onSize: (n) => { this.size = n; App.savePageSize("listings", n); this.page = 0; this.load(); } };
  },

  renderBar() {
    const n = this.selAll ? this.total : this.sel.size;
    App.listBar($("#l-bar"), {
      ...this.pagerOpts(), count: n, selAll: this.selAll, what: "복사본",
      pageChecked: this.rows.length > 0 && this.rows.every((l) => this.sel.has(l.id)),
      actions: [
        { id: "rename", label: "상품명 바꾸기", primary: true, title: "아직 안 올린 복사본의 상품명을 AI 키워드·AI로 짓기·셔플로 바꿈" },
        "|",
        { id: "refresh", label: "최신화", title: "판매 중인 건을 네이버에서 지우고 같은 내용으로 다시 올림 (회차 +1) · 바로 하기 또는 대기에 넣기" },
        { id: "reupload", label: "다시 올리기", title: "문제가 있어 지우고 같은 내용(같은 상품명)으로 다시 올림 · 판매 중인 건은 지우고 다시, 내린 건은 그냥 다시 · 최신화와 따로 기록" },
        { id: "delete", label: "내리기", title: "판매 중인 건을 네이버에서 지움 · 바로 하기 또는 대기에 넣기" },
        { id: "cancel", label: "대기·실패 취소", danger: true, title: "아직 처리 안 된 대기·실패 할 일을 취소" },
        "|",
        { id: "lock", label: "잠금", title: "판매 이력과 상관없이 지우지 못하게 잠금" },
        { id: "unlock", label: "잠금 풀기" },
        { id: "category", label: "카테고리 바꾸기", title: "고른 복사본의 원본 카테고리를 직접 정함 (인증 때문에 안 올라가는 카테고리 등) — 그 원본의 다른 스토어 복사본도 같이" },
        { id: "chem", label: "생활화학 판정", title: "고른 복사본의 원본을 판정: 물건이면 '인증 대상 아님'으로 다시 등록 대기, 화학제품이면 보류 (애매하면 AI)" },
        { id: "resetround", label: "회차 초기화", title: "지난 회차 기록을 지우고 1회차로 (다시 다 올릴 때) · 판매 중·내린 건은 다음에 다시 올릴 때 1회차로" },
        "|",
        { id: "move", label: "다른 스토어로 보내기", title: "아직 안 올린·내린 복사본을 다른 스토어로 옮김 (이 스토어에서는 사라짐) — 받는 스토어 남은 자리만큼" },
        { id: "revert", label: "원본으로 되돌리기", title: "아직 안 올린·내린 복사본을 이 스토어에서 없앰 → 원본의 복사 자리가 비고 상품명은 후보로 (A였으면 다음 복사에 다시 A)" },
        "|",
        { id: "eyeon", label: "검수 완료로 표시", title: "고른 복사본의 원본을 검수 완료로 (새로 올릴 수 있게) — 원본 기준이라 다른 스토어 복사본도 같이" },
        { id: "eyeoff", label: "검수 완료 풀기" },
        "|",
        { id: "remove", label: "삭제", danger: true, title: "기본: 원본까지 같이 삭제 (그 원본의 모든 스토어 복사본, 판매 중인 것은 내린 뒤) · 끄면 고른 복사본만 휴지통" },
        "|",
        { id: "export", always: true, label: n && !this.selAll ? `⬇ 엑셀(CSV) 받기 — 고른 ${num(n)}건` : `⬇ 엑셀(CSV) 받기 — ${this.selAll ? "조건에 맞는" : "지금 보이는 조건"} ${num(this.total)}건`,
          title: "복사본 목록을 엑셀(CSV)로 받습니다: 스토어·판매자 관리코드·회차·등록 상품명·원본 번호·원본 판매자코드·원본 상품명·판매가·기준 가격·상태·할 일·올린 날·원상품번호·채널상품번호·메시지" },
      ],
      onPageCheck: (on) => { this.selAll = false; this.rows.forEach((l) => (on ? this.sel.add(l.id) : this.sel.delete(l.id))); this.load(); },
      onAll: () => { this.selAll = true; this.sel.clear(); this.load(); },
      onClear: () => { this.clearSel(); this.load(); },
      onAction: (id) => this.action(id),
    });
    App.pagerBar($("#l-pager"), this.pagerOpts());
    if (this.runRange === "sel" && !App.run?.running && $("#l-run")) this.renderIdle();   // 고른 수가 바뀌면 시작 범위도
  },

  async action(id) {
    if (id === "rename") this.renameModal();
    if (id === "export") {   // 고른 것이 있으면 그것만, 없으면 지금 보이는 조건 전체
      const q = this.sel.size && !this.selAll ? { store_id: this.f.store_id, ids: [...this.sel].join(",") } : this.query();
      window.location.href = `/api/listings/export.csv?${new URLSearchParams(q)}`;
    }
    if (id === "refresh" || id === "delete" || id === "reupload") this.schedule(id);
    if (id === "lock" || id === "unlock") this.lock(id === "lock");
    if (id === "remove") App.deleteCopies(this.target(), () => { this.clearSel(); this.estKey = ""; this.load(); });
    if (id === "resetround") this.resetRound();
    if (id === "move") this.moveModal();
    if (id === "revert") {
      const n = this.selAll ? this.total : this.sel.size;
      if (!await App.yes("원본으로 되돌리기", `고른 복사본 ${num(n)}건을 원본으로 되돌릴까요?\n\n이 스토어에서 복사본이 없어지고(휴지통에 기록), 원본은 그대로 남아 다른 스토어로 다시 복사할 수 있습니다.\n붙어 있던 상품명은 원본의 후보로 돌아갑니다.\n네이버에 올라가 있거나 처리 중인 것·판매 이력(잠금)이 있는 것은 빼고 합니다.`, { label: "되돌리기", danger: true })) return;
      try {
        const r = await App.api("/api/listings/revert", { json: this.target() });
        App.toast(`복사본 ${num(r.reverted)}건을 원본으로 되돌렸습니다` + (r.live ? ` · 올라가 있거나 처리 중이라 뺀 ${num(r.live)}건` : "") + (r.locked ? ` · 판매 이력·잠금으로 뺀 ${num(r.locked)}건` : ""));
        this.clearSel(); this.estKey = ""; this.load(); App.refreshState();
      } catch (err) { App.toast(err.message, true); }
    }
    if (id === "eyeon" || id === "eyeoff") App.eyeSet({ listing_filter: this.target() }, id === "eyeon", `고른 복사본 ${num(this.selAll ? this.total : this.sel.size)}건의 원본`, () => this.load());
    if (id === "chem" && await App.yes("생활화학 판정", CHEM_JUDGE_TXT, { label: "판정 시작" })) App.startTask(App.api("/api/chem/judge", { json: { listing_filter: this.target() } }));
    if (id === "category") {
      const n = this.selAll ? this.total : this.sel.size;
      App.pickCategory({ target: { listing_filter: this.target() }, what: `고른 복사본 ${num(n)}건의 원본`, after: () => this.load() });
    }
    if (id === "cancel") {
      if (!await App.yes("대기·실패 취소", "고른 건 중 대기·실패 할 일을 취소할까요?\n새 등록이면 계획을 지우고 이름을 후보로 돌립니다. 최신화·내리기면 판매 중으로 되돌립니다.", { label: "할 일 취소", danger: true })) return;
      try {
        const r = await App.api("/api/listings/cancel", { json: this.target() });
        App.toast(`${num(r.cancelled)}건을 취소했습니다.`);
        this.clearSel(); this.estKey = ""; this.load();
      } catch (err) { App.toast(err.message, true); }
    }
  },

  rowHtml(l) {
    let msg = "", cls = "";
    if (l.status === "fail") { msg = l.message; cls = "err"; }
    else if (l.status === "success") msg = `상품번호 ${l.channel_no}`;
    else if (l.status === "running") msg = l.stage;
    else if (l.status === "deleted") msg = `${ymd(l.deleted_at)}에 내림`;
    const on = this.selAll || this.sel.has(l.id);
    const live = !!l.origin_no;
    const noname = !l.name_id && !live && l.status !== "deleted";
    const flags = (noname ? `<span class="flag bad" title="원본 상품명 그대로라 올리지 않습니다">상품명 변경 필요</span>` : "")
      + (l.rep_word ? `<span class="flag warn" title="'${esc(l.rep_word)}'가 3번 이상 나옵니다 — 상품명 바꾸기로 다시 만드세요">반복: ${esc(l.rep_word)}</span>` : "")
      + (l.name_origin ? `<span class="org org-${l.name_origin}" title="${l.name_origin === "ctx" ? "AI 키워드 이름의 양식 (A = 첫 복사용, B = 양식이 조금 다른 두 번째) — 원본 상품 화면에서 A·B 전체를 볼 수 있음" : ""}">${l.name_origin === "ctx" && l.ai_label ? `AI 이름 ${esc(l.ai_label)}` : ORIGIN[l.name_origin] || l.name_origin}</span>` : "") + lockFlag(l) + salesFlag(l) + eyeFlag(l)
      + (l.adopted ? '<span class="flag adopted" title="기존 상품 가져오기로 들어온 원본">가져옴</span>' : "")
      + (l.price_fixed ? '<span class="flag" title="가져온 복사본: 최신화·다시 올리기 때 손님 가격 그대로 (최신화 직전에 네이버에서 다시 읽음 — 판매자센터에서 바꾼 가격·옵션 추가금도)">가격 고정</span>' : "")
      + nvFlag(l);
    return `<tr data-id="${l.id}" class="${on ? "sel" : ""} ${l.status === "deleted" ? "off" : ""}">
      <td class="w-check" data-stop><input type="checkbox" ${on ? "checked" : ""} ${this.selAll ? "disabled" : ""} aria-label="고르기"></td>
      <td>${img(l.thumb)}</td>
      <td>${noname ? `<div class="p-name">${esc(l.name)}</div>` : nameDiff(l.nd)}
        ${!noname ? `<div class="orig-name">원본: ${esc(l.source_name)}</div>` : ""}
        <div class="p-sub"><span>원본 #${l.source_id}</span>${flags}</div>
        <div class="row-acts" data-stop>
          ${!live && l.status !== "deleted" ? `<button class="btn ${noname ? "primary" : ""}" data-rename="${l.id}">상품명 바꾸기</button>` : ""}
          ${l.others.map((o) => `<button class="go-store" data-go="${o.id}" title="같은 원본이 있는 다른 스토어로">→ ${esc(o.store_name)}</button>`).join("")}
        </div></td>
      <td class="w-links" data-stop>${goLinks({ storeUrl: l.store_url, channelNo: l.origin_no ? l.channel_no : "", sourceId: l.source_id })}
        <button class="btn sm" data-src="${l.source_id}" title="원본 상품 정보 (이 프로그램)">원본 정보</button></td>
      <td>${esc(l.seller_code || "-")}<div class="p-sub">${l.round}회차${l.registered_at && l.origin_no ? ` · ${ymd(l.registered_at)} (${age(l.registered_at)})` : ""}</div></td>
      ${priceCell(l, l.source_price)}
      <td>${statusBadge(l.status, l.op)}${msg ? `<div class="s-msg ${cls}" title="${esc(msg)}">${esc(msg)}</div>` : ""}</td></tr>`;
  },

  target() {
    if (this.selAll) return this.query();
    return { ids: [...this.sel] };
  },

  /* 다른 스토어로 보내기: 아직 안 올린·내린 복사본을 다른 스토어로 (이 스토어에서는 사라짐), 받는 스토어 남은 자리만큼 */
  async moveModal() {
    const n = this.selAll ? this.total : this.sel.size;
    const stores = (await App.loadStores()).filter((s) => s.id !== +this.f.store_id);
    const cur = App.stores.find((s) => s.id === +this.f.store_id);
    App.openModal({
      title: `다른 스토어로 보내기 · 복사본 ${num(n)}건`, wide: true,
      body: `<div class="form">
        <p class="small" style="margin:0"><b>${esc(cur?.name || "이 스토어")}</b>에서 고른 복사본을 받는 스토어로 옮깁니다. 이 스토어에서는 사라집니다.</p>
        <ul class="small muted" style="margin:0;padding-left:18px">
          <li>아직 안 올린 것(대기·실패)과 <b>내린 것</b>만 옮깁니다. 네이버에 올라가 있거나 처리 중인 것·판매 이력(잠금)이 있는 것은 뺍니다.</li>
          <li>받는 스토어의 <b>남은 자리만큼만</b> 옮기고, 그 스토어에 같은 원본이 이미 있으면(내린 것 포함) 뺍니다.</li>
          <li>상품명(A·B)은 그대로, 가격은 받는 스토어 템플릿 기준으로 다시 정하고, 1회차 새 등록 대기가 됩니다.</li></ul>
        <div class="store-pick">${byBusiness(stores).map(([biz, ss]) => `<div class="sp-group">${esc(biz)}</div>` + ss.map((s) => `
          <label class="sp-row"><input type="radio" name="mv-to" value="${s.id}" ${s.free > 0 ? "" : "disabled"}>
            <span class="sp-name"><span class="code">${esc(s.code)}</span> ${esc(s.name)}</span>
            ${usageBar(s.used, s.capacity)}<span class="sp-free ${s.free < 100 ? "c-err" : "muted"}">남은 자리 ${num(s.free)}</span></label>`).join("")).join("")}</div>
        <div class="plan-sum" id="mv-sum">받을 스토어를 고르세요.</div></div>`,
      buttons: [{ label: "취소" }, { label: "보내기", primary: true, validate: (b) => ($("input[name=mv-to]:checked", b) ? "" : "받을 스토어를 고르세요."), onClick: async (b) => {
        const to = +($("input[name=mv-to]:checked", b)?.value || 0);
        if (!to) { App.toast("받을 스토어를 고르세요.", true); return false; }
        try {
          const r = await App.api("/api/listings/move", { json: { ...this.target(), to_store: to } });
          App.toast(`${r.store}(으)로 ${num(r.moved)}건을 보냈습니다` + (r.exists ? ` · 그 스토어에 같은 원본이 있어 뺀 ${num(r.exists)}건` : "")
            + (r.full ? ` · 남은 자리가 모자라 못 보낸 ${num(r.full)}건` : "") + (r.live ? ` · 올라가 있거나 처리 중이라 뺀 ${num(r.live)}건` : "")
            + (r.locked ? ` · 판매 이력·잠금으로 뺀 ${num(r.locked)}건` : ""), !r.moved);
          this.clearSel(); this.estKey = ""; this.load(); App.refreshState();
        } catch (err) { App.toast(err.message, true); return false; }
      } }],
    });
    $$("input[name=mv-to]").forEach((x) => x.addEventListener("change", () => {
      const s = stores.find((t) => t.id === +x.value);
      $("#mv-sum").innerHTML = `복사본 <b>${num(n)}건</b> → <b>${esc(s.name)}</b> · 남은 자리 ${num(s.free)}${n > s.free ? ` (넘는 ${num(n - s.free)}건은 남김)` : ""}`;
    }));
  },

  /* 회차 초기화: 지난 회차 기록을 지우고 1회차로 (다시 다 올릴 때) */
  resetRound() {
    const n = this.selAll ? this.total : this.sel.size;
    App.openModal({
      title: "회차 초기화 (1회차로)",
      body: `<div class="form">
        <p>지난 회차 기록을 지우고 <b>1회차</b>로 되돌립니다. 판매자 관리코드 끝 번호도 다음에 올릴 때 <b>-1</b>로 붙습니다.</p>
        <ul class="small" style="margin:0;padding-left:18px">
          <li>아직 안 올린 복사본: 바로 1회차</li>
          <li>판매 중·내린 복사본: 지금 상태는 그대로, <b>최신화·다시 올리기로 다시 올릴 때 1회차</b>로 올라감 (+1 하지 않음)</li>
          <li>네이버의 상품은 건드리지 않습니다.</li></ul>
        <div class="radio-cards">
          ${n ? `<label><input type="radio" name="rr" value="sel" checked><div><b>고른 복사본 ${num(n)}건</b></div></label>` : ""}
          <label><input type="radio" name="rr" value="store" ${n ? "" : "checked"}><div><b>이 스토어 복사본 전체</b></div></label>
          <label><input type="radio" name="rr" value="all"><div><b>모든 스토어 복사본 전체</b> <span class="muted small">다시 다 올릴 때</span></div></label>
        </div></div>`,
      buttons: [{ label: "취소" }, { label: "1회차로 되돌리기", danger: true, primary: true, onClick: async (b) => {
        const v = $("input[name=rr]:checked", b).value;
        const body = v === "all" ? { all: true } : v === "store" ? { store_id: this.f.store_id, status: "all" } : this.target();
        try {
          const r = await App.api("/api/listings/reset_round", { json: body });
          App.toast(`복사본 ${num(r.count)}건을 1회차로 되돌렸습니다. 판매 중·내린 건은 다음에 다시 올릴 때 1회차로 올라갑니다.`);
          this.load();
        } catch (e) { App.toast(e.message, true); return false; }
      } }],
    });
  },

  async lock(on, ids) {
    try {
      const r = await App.api("/api/listings/lock", { json: { ...(ids ? { ids } : this.target()), lock: on } });
      App.toast(on ? `${num(r.count)}건을 잠갔습니다. 최신화·내리기로 지우지 않습니다.`
        : `${num(r.count)}건의 직접 잠금을 풀었습니다.` + (r.still_locked ? ` ${num(r.still_locked)}건은 판매 이력이 있어 잠금이 유지됩니다.` : ""));
      if (!ids) { this.clearSel(); this.load(); }
      return r;
    } catch (e) { App.toast(e.message, true); }
  },

  /* 상품명 바꾸기: AI 키워드(기본) / AI로 짓기 / 셔플. ids를 주면 그 건만 */
  renameModal(ids) {
    const s = App.state.settings;
    const target = ids ? { ids } : this.target();
    const n = ids ? ids.length : this.selAll ? this.total : this.sel.size;
    const keyOk = s.has_anthropic_api_key || App.state.fake_api;
    App.openModal({
      title: `상품명 바꾸기 · 복사본 ${num(n)}건`,
      body: `<div class="form"><div class="radio-cards">
          <label><input type="radio" name="rn" value="ctx" checked><div><b>AI 키워드 (기본)</b><span class="muted small">[원본 앞 ${num(s.ctx_head_n)}단어] + 원본 핵심 단어(keep) + 다른 이름(core) + 용도·조합(core2) + 맥락 + 남은 원본 단어 (A·B는 보라·맥락을 나눠 쓰고, B는 앞 3단어만 두고 섞음), 최대 ${num(s.name_max_len)}자. 키워드가 없는 원본은 먼저 받습니다(비용 안내 후).</span></div></label>
          <label><input type="radio" name="rn" value="ai"><div><b>AI로 짓기</b><span class="muted small">AI(${esc(s.ai_model)})가 원본을 보고 이름 전체를 새로 짓습니다.</span></div></label>
          <label><input type="radio" name="rn" value="shuffle"><div><b>셔플 (AI 안 씀)</b><span class="muted small">앞 단어를 고정하고 나머지 단어 순서를 섞습니다. 넣을 단어를 적으면 그 단어도 고정 단어 뒤에서 함께 섞입니다.</span>
            <div class="shuffle-opts" style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
              <label class="field" style="margin:0">앞에서 고정할 단어 수 <input type="number" id="rn-fixed" min="0" max="10" value="${num(s.shuffle_fixed || 3)}" style="width:80px"></label>
              <label class="field" style="margin:0;flex:1;min-width:220px">넣을 단어 (띄어쓰기·쉼표로 구분, 비워도 됨) <input id="rn-extra" placeholder="예: 업소용 카페"></label>
            </div></div></label>
        </div>
        <label class="check"><input type="checkbox" id="rn-redo" checked> 이미 이름이 붙은 복사본도 새 이름으로 바꾸기 <span class="muted small">(끄면 '상품명 변경 필요'인 것만)</span></label>
        ${keyOk ? "" : '<p class="c-err small">AI 키워드·AI로 짓기는 설정 → API 키에서 Anthropic 키를 먼저 넣어야 합니다.</p>'}
        <p class="muted small">이미 올라간 복사본은 바꾸지 않습니다(최신화로 다시 올릴 때 바뀜). 판매자 관리코드는 그대로입니다.
          모든 이름은 금지어·상표와 33개 스토어 중복을 검사합니다. 한 건씩은 복사본을 눌러 직접 입력할 수도 있습니다.</p></div>`,
      buttons: [{ label: "취소" }, { label: "바꾸기", primary: true, onClick: async (b) => {
        const method = $("input[name=rn]:checked", b).value;
        if (method === "shuffle") {
          return !!(await App.startTask(App.api("/api/listings/rename", { json: { ...target, method,
            fixed_n: +$("#rn-fixed", b).value, extra: $("#rn-extra", b).value } })));
        }
        if (method === "ctx") {
          const redo = $("#rn-redo", b).checked;
          const go = () => App.startTask(App.api("/api/listings/rename", { json: { ...target, method, redo } }));
          const est = await App.api("/api/ctx/estimate", { json: { listing_filter: target } });
          if (est.sources) {
            // 키워드 없는 원본: 비용 안내 후 받기 → 키워드 있는 원본은 지금 붙이고, 나머지는 받는 대로 자동으로 붙음
            App.closeModal();
            // 즉시면 키워드를 다 받은 뒤 이름을 붙이고, 일괄이면 키워드 있는 원본만 지금 붙인다 (나머지는 끝나면 자동)
            App.ctxConfirm({ listing_filter: target }, (ok, mode) => {
              if (!ok) return;
              if (mode !== "instant") return go();
              const h = (t) => {
                if (t.kind !== "ctxkw") return;
                App.off("task-done", h);
                if (t.status === "done") go();   // 키워드를 못 받았으면 이름을 바꾸지 않음
                else App.toast("AI 키워드를 받지 못해 상품명은 바꾸지 않았습니다. 다시 시도하세요.", true);
              };
              App.on("task-done", h);
            });
            return false;
          }
          return !!(await go());
        }
        return !!(await App.startTask(App.api("/api/listings/rename", { json: { ...target, method } })));
      } }],
    });
  },

  /* 최신화·내리기: 바로 하기(방금 고른 것만 지금 처리) 또는 대기에 넣기(나중에 시작에서 처리) */
  schedule(op) {
    const name = OP[op];
    const label = {
      refresh: "<b>최신화</b>: 올린 지 오래된 판매 중 상품을 네이버에서 지우고 다시 올립니다 (설정에 따라 새 상품명)",
      reupload: "<b>다시 올리기</b>: 문제가 있는 상품을 네이버에서 지우고 <b>같은 상품명·지금 가격</b>으로 다시 올립니다. <b>이미 내린(내림) 건은 지우는 단계 없이 다시 올립니다.</b> 스토어에서 이미 지운 상품이어도 됩니다",
      delete: "<b>내리기</b>: 판매 중인 상품을 네이버에서 지웁니다",
    }[op];
    const n = this.selAll ? this.total : this.sel.size;
    const go = async (now) => {
      try {
        const r = await App.api("/api/listings/schedule", { json: { ...this.target(), op, now } });
        const skip = r.skipped_sold ? ` 잠긴 ${num(r.skipped_sold)}건(판매 이력·직접 잠금)은 뺐습니다.` : "";
        if (!r.scheduled) App.toast((op === "reupload" ? "판매 중이거나 내린 건이 없어 걸 일이 없습니다." : `판매 중인 건이 없어 걸 일이 없습니다.${op === "refresh" ? " 내린 건은 '다시 올리기'를 쓰세요." : ""}`) + skip, true);
        else if (r.started) { App.toast(`${num(r.scheduled)}건 ${name}를 시작했습니다.` + skip); App.run = await App.api("/api/run"); this.renderRun(App.run); App.renderSideRun(); }
        else if (r.busy) App.toast(`${num(r.scheduled)}건을 대기에 넣었습니다. 지금 다른 작업이 돌고 있어, 끝난 뒤 시작하세요.` + skip);
        else if (r.error) App.toast(`대기에 넣었지만 시작하지 못했습니다: ${r.error}`, true);
        else App.toast(`${num(r.scheduled)}건을 대기에 넣었습니다. 위 시작에서 '${name}'를 골라 처리하세요.` + skip);
        this.sel.clear(); this.selAll = false; this.estKey = "";
        this.load();
      } catch (e) { App.toast(e.message, true); }
    };
    App.openModal({
      title: `${num(n)}건 ${name}`,
      body: `<p>${label}.</p>
        <p class="muted small">잠긴 건(판매 이력·직접 잠금)은 빠지고, 지우기 직전에 이 스토어 주문을 한 번 더 확인합니다. 지난 회차 기록에 '${name}'로 남습니다.</p>
        <ul class="muted small"><li><b>바로 하기</b>: 방금 고른 것만 지금 처리합니다 (다른 대기 건은 건드리지 않음).</li>
        <li><b>대기에 넣기</b>: 걸어만 두고, 나중에 위 시작에서 '${name}'를 골라 처리합니다.</li></ul>`,
      buttons: [{ label: "취소" }, { label: "대기에 넣기", onClick: () => go(false) }, { label: "바로 하기", primary: true, onClick: () => go(true) }],
    });
  },

  // ── 실행 패널

  renderIdle() {
    const box = $("#l-run");
    const c = this.counts;
    const range = this.runRange || "store";
    const kinds = this.runKinds ||= new Set(RUN_KINDS.map((k) => k[0]));
    const nSel = this.selAll ? this.total : this.sel.size;
    const est = this.est || {};
    const n = est.count ?? 0;
    box.innerHTML = `<div class="run-idle">
        <div class="run-pick">
          <div class="seg" role="group" aria-label="처리 범위">${[["store", "이 스토어 전체"], ["sel", `고른 것만 (${num(nSel)})`], ["visible", "지금 보이는 조건만"]].map(([k, l]) =>
            `<button type="button" class="${range === k ? "on" : ""}" data-range="${k}">${l}</button>`).join("")}</div>
          <div class="run-kinds">${RUN_KINDS.map(([k, l]) => `<label class="kind ${kinds.has(k) ? "on" : ""}"><input type="checkbox" data-kind="${k}" ${kinds.has(k) ? "checked" : ""}>
            ${l} <b>${est.kinds ? num(est.kinds[k] || 0) : "…"}</b></label>`).join("")}</div>
        </div>
        <div class="run-actions">
          <button class="btn primary big" id="l-start" ${n ? "" : "disabled"}>▶ 시작 · ${est.count == null ? "세는 중" : num(n) + "건"}</button>
          <button class="btn big" id="l-one" ${n ? "" : "disabled"}>1건만 시험</button>
        </div>
        <div class="run-est">
          ${est.noname ? `<div class="c-err small">이 범위에서 상품명을 안 바꾼 복사본 <b>${num(est.noname)}건</b>은 올리지 않습니다 — <a href="#" id="l-noname">상품명 변경 필요 보기</a></div>` : ""}
          ${est.unreviewed ? `<div class="c-err small">눈검수 안 한 원본이라 새로 올리지 않는 복사본 <b>${num(est.unreviewed)}건</b> — <a href="#" id="l-unrev">미검수 보기</a> (눈검수하거나 '검수 완료로 표시')</div>` : ""}
          <div id="l-est" class="muted small">${est.seconds && n ? `예상 <b>약 ${dur(est.seconds)}</b> · 스토어마다 ${est.workers}건씩 동시에 · ${esc(est.basis)}` : range === "sel" && !nSel ? "목록에서 복사본을 고르세요." : ""}</div></div>
      </div>`;
    $("#l-start").addEventListener("click", () => this.start());
    $("#l-one").addEventListener("click", () => this.start(1));
    $("#l-noname")?.addEventListener("click", (e) => { e.preventDefault(); this.f.status = "noname"; this.f.eye = ""; this.page = 0; this.clearSel(); this.load(); });
    $("#l-unrev")?.addEventListener("click", (e) => { e.preventDefault(); this.f.status = "all"; this.f.eye = "todo"; this.page = 0; this.clearSel(); this.load(); });
    $$("[data-range]", box).forEach((x) => x.addEventListener("click", () => { this.runRange = x.dataset.range; this.renderIdle(); }));
    $$("[data-kind]", box).forEach((x) => x.addEventListener("change", () => {
      x.checked ? kinds.add(x.dataset.kind) : kinds.delete(x.dataset.kind); this.renderIdle();
    }));
    const key = JSON.stringify(this.runScope()) + JSON.stringify(c);
    if (key === this.estKey) return;
    this.estKey = key;
    App.api("/api/run/estimate", { json: this.runScope() }).then((e) => {
      this.est = e;
      if (!App.run?.running && $("#l-run")) this.renderIdle();
    }).catch(() => {});
  },

  /* 복사본 일괄 수정: 이 스토어 양식(엑셀)에 '새 손님 가격'·'새 상품명'을 적어 올림 → 미리보기 → 2차 확인 → 적용 */
  bulkEdit(store) {
    const sid = +this.f.store_id;
    let pv = null;
    const ST = { ok: '<span class="c-ok">바꿈</span>', same: '<span class="muted">그대로</span>' };
    const render = (d) => {
      const rows = d.items.filter((x) => x.status !== "same");
      $("#be-out").innerHTML = `<div class="notice ${d.ok ? "info" : "warn"}" style="margin:10px 0">바꿀 복사본 <b>${num(d.ok)}</b>개
          (손님 가격 ${num(d.n_price)} · 상품명 ${num(d.n_name)})${d.bad ? ` · 못 바꾸는 줄 <b>${num(d.bad)}</b>개(아래 빨간 글씨)` : ""}${d.same ? ` · 바뀐 게 없는 줄 ${num(d.same)}개` : ""}<br>
          ${d.n_price ? `손님 가격을 고친 원본은 <b>기준 가격이 바뀌어 다른 스토어 복사본 ${num(d.others)}건도 같이</b> 바뀝니다. ` : ""}
          ${d.n_live ? `판매 중 ${num(d.n_live)}건${d.n_locked ? `(잠긴 ${num(d.n_locked)}건 포함)` : ""}은 <b>지우지 않고 네이버 값만</b> 바꿉니다 (리뷰·판매 기록 그대로).` : ""}</div>
        ${rows.length ? `<div class="tbl-wrap" style="max-height:360px"><table class="tbl small"><thead><tr><th>줄</th><th>복사본</th><th>상품명 (지금 → 새)</th><th class="r">손님 가격 (지금 → 새)</th><th>결과</th></tr></thead><tbody>
          ${rows.map((x) => `<tr><td>${x.line}</td><td>#${x.listing_id}${x.live ? " · 판매 중" : ""}${x.locked ? " 🔒" : ""}</td>
            <td>${x.name_new ? `${esc((x.name_old || "").slice(0, 40))}<br>→ <b>${esc(x.name_new)}</b>` : '<span class="muted">그대로</span>'}</td>
            <td class="r nowrap">${x.target ? `${num(x.price_old || 0)} → <b>${num(x.price_new || x.target)}</b>${x.others ? `<div class="muted small">다른 스토어 ${num(x.others)}건도</div>` : ""}` : '<span class="muted">그대로</span>'}</td>
            <td class="small">${ST[x.status] || `<span class="c-err">${esc((x.why || []).join(" · "))}</span>`}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
    };
    App.openModal({
      title: `일괄 수정 (엑셀) — ${store?.name || ""}`, wide: true,
      body: `<ol class="small" style="margin:0 0 8px;padding-left:18px;line-height:1.7">
          <li><a href="/api/listings/bulk_template.xlsx?store_id=${sid}">⬇ 이 스토어 양식 받기</a> — 복사본마다 번호·상품번호·지금 상품명·지금 손님 가격이 들어 있습니다.</li>
          <li>바꿀 줄에만 <b>새 상품명</b>·<b>새 손님 가격</b>(손님이 실제로 내는 금액)을 적습니다. 빈 칸은 그대로. 네이버 판매가·할인은 표시 할인율로 알아서 계산합니다.</li>
          <li>올리면 미리보기가 나오고, 확인하면 바꿉니다. <b>손님 가격을 고치면 원본의 기준 가격이 바뀌어 다른 스토어 복사본도 같이</b> 바뀝니다(역마진 수정).</li></ol>
        <p class="small muted" style="margin:0 0 8px">판매 중 상품(잠긴 것 포함)은 지우지 않고 네이버의 가격·상품명만 바꿉니다. 상품명은 직접 고치기와 같은 검사(금지 단어·상표·반복·모든 스토어 통틀어 같은 이름 금지)를 거칩니다. 다른 스토어 양식은 받지 않습니다.</p>
        <label class="btn"><input type="file" id="be-file" accept=".xlsx,.xlsm" hidden>고친 양식 올리기 (미리보기)</label><div id="be-out"></div>`,
      buttons: [{ label: "닫기" }, { label: "바꾸기", primary: true,
        get confirm() { return pv ? `복사본 ${num(pv.ok)}개를 바꿉니다 (손님 가격 ${num(pv.n_price)} · 상품명 ${num(pv.n_name)})${pv.others ? ` — 손님 가격을 고친 원본의 다른 스토어 복사본 ${num(pv.others)}건도 같이 바뀜` : ""}. 판매 중 ${num(pv.n_live)}건은 지우지 않고 네이버 값만 바꿉니다.` : ""; },
        validate: () => (!pv ? "먼저 고친 양식을 올려 미리보기를 확인하세요." : !pv.ok ? "바꿀 줄이 없습니다." : ""),
        onClick: async () => {
          const r = await App.api("/api/listings/bulk_apply", { json: { token: pv.token } });
          App.toast(`일괄 수정: 가격 바꾼 원본 ${num(r.prices)} · 상품명 ${num(r.names)}` + (r.price_live || r.name_live ? ` · 네이버 반영 ${r.queued ? "대기" : "중"} (가격 ${num(r.price_live)} · 상품명 ${num(r.name_live)})` : "")
            + (r.name_skip?.length ? ` · 못 바꾼 상품명 ${num(r.name_skip.length)} (${r.name_skip[0]})` : ""), !!r.name_skip?.length);
          if (r.task) { App.taskSeen[r.task] = "running"; App.refreshState(); }
          this.load();
        } }],
    });
    $("#be-file").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      e.target.value = "";
      if (!f) return;
      const fd = new FormData();
      fd.append("file", f);
      fd.append("store_id", sid);
      pv = null;
      $("#be-out").innerHTML = '<p class="muted"><span class="spin"></span> 읽는 중…</p>';
      try { pv = await App.api("/api/listings/bulk_preview", { method: "POST", body: fd }); render(pv); }
      catch (err) { $("#be-out").innerHTML = `<div class="notice err" style="margin-top:8px">${esc(err.message)}</div>`; }
    });
  },

  async start(limit) {
    const scope = this.runScope();
    const n = limit || this.est?.count || 0;
    const what = RUN_KINDS.filter(([k]) => scope.kinds.includes(k)).map(([k, l]) => `${l} ${num(this.est?.kinds?.[k] || 0)}`).join(" · ");
    const where = { store: "이 스토어 전체", sel: "고른 복사본", visible: "지금 보이는 조건" }[this.runRange || "store"];
    if (!await App.yes(limit ? "1건만 시험" : "시작", `${where}에서 ${num(n)}건을 처리합니다.\n(${what})` + (limit ? "\n\n고른 종류에 '내리기'가 있으면 그 1건은 네이버에서 내려갑니다." : ""), { label: limit ? "1건 처리" : "시작" })) return;
    try {
      App.run = await App.api("/api/run", { json: { ...scope, limit: limit || null } });
      this.renderRun(App.run);
      App.renderSideRun();
    } catch (e) { App.toast(e.message, true); }
  },

  renderRun(r) {
    if (!r?.running) {
      if (this._live) { this._live = false; this.renderIdle(); }
      this.renderLog(r);
      return;
    }
    const box = $("#l-run");
    if (!this._live) {
      this._live = true;
      box.innerHTML = `<div class="run-top">
          <div class="run-count"><b id="r-done">0</b><span> / <span id="r-total">0</span></span></div>
          <div class="run-meta">
            <div><span class="muted">성공</span><b class="c-ok" id="r-ok">0</b></div>
            <div><span class="muted">실패</span><b class="c-err" id="r-fail">0</b></div>
            <div><span class="muted">잠금으로 건너뜀</span><b id="r-skip">0</b></div>
            <div><span class="muted">속도</span><b id="r-rate">-</b></div>
            <div><span class="muted">남은 시간</span><b id="r-eta">-</b></div>
            <div><span class="muted">새로 올린 이미지</span><b id="r-img">0</b></div>
          </div>
          <div class="run-ctl"><button class="btn" id="r-pause">일시정지</button><button class="btn danger" id="r-stop">중단</button></div>
        </div>
        <div class="bar"><div class="bar-ok" id="r-bar-ok"></div><div class="bar-err" id="r-bar-err"></div></div>
        <div class="run-state" id="r-state"></div>
        <div class="store-chips" id="r-stores"></div>
        <ul class="current" id="r-current"></ul>
        <details class="log" open><summary>작업 기록 <span class="muted" id="r-logn"></span></summary><ol id="r-log"></ol></details>`;
      $("#r-pause").addEventListener("click", async () => {
        App.run = await App.api(`/api/run/${App.run?.paused ? "resume" : "pause"}`, { method: "POST" }); this.renderRun(App.run);
      });
      $("#r-stop").addEventListener("click", async () => {
        if (!await App.yes("등록 중단", "등록을 중단할까요? 처리 중인 건까지만 마치고 멈춥니다. 남은 건은 대기로 돌아갑니다.", { label: "중단", danger: true })) return;
        App.run = await App.api("/api/run/stop", { method: "POST" }); this.renderRun(App.run);
      });
      clearInterval(this.timer);
      this.timer = setInterval(() => { if (App.run?.running) this.load(); }, 4000);
    }
    $("#r-done").textContent = num(r.done);
    $("#r-total").textContent = num(r.total);
    $("#r-ok").textContent = num(r.ok);
    $("#r-fail").textContent = num(r.fail);
    $("#r-skip").textContent = num(r.skipped || 0);
    $("#r-rate").textContent = r.rate_per_min ? `분당 ${num(Math.round(r.rate_per_min))}건` : "재는 중";
    $("#r-eta").textContent = r.paused ? "일시정지" : r.eta != null ? dur(r.eta) : "재는 중";
    $("#r-img").textContent = num(r.images) + (r.images_reused ? ` (+${num(r.images_reused)} 재사용)` : "");
    $("#r-bar-ok").style.width = (r.total ? (r.ok / r.total) * 100 : 0) + "%";
    $("#r-bar-err").style.width = (r.total ? (r.fail / r.total) * 100 : 0) + "%";
    $("#r-pause").textContent = r.paused ? "▶ 계속" : "일시정지";
    $("#r-pause").disabled = $("#r-stop").disabled = r.stopping;
    $("#r-state").textContent = r.stopping ? "중단하는 중… 처리 중인 건까지만 마칩니다."
      : r.paused ? "일시정지됨" : `등록 중 · ${dur(r.elapsed)} 지남`;
    $("#r-stores").innerHTML = r.stores.map((s) => {
      const p = s.total ? (s.done / s.total) * 100 : 0;
      return `<div class="chip-store ${s.status === "등록 중" ? "on" : s.status === "끝" ? "done" : ""}" title="${esc(s.name)}: ${s.status}">
        <div class="cs-top"><span>${esc(s.name)}</span><span>${num(s.done)}/${num(s.total)}</span></div>
        <div class="bar thin"><div class="bar-ok" style="width:${s.total ? (s.ok / s.total) * 100 : 0}%"></div>
        <div class="bar-err" style="width:${s.total ? (s.fail / s.total) * 100 : 0}%"></div></div></div>`;
    }).join("");
    $("#r-current").innerHTML = r.current.slice(0, 8).map((c) =>
      `<li><span class="spin"></span><span class="c-name">${esc(c.name)}</span><span class="c-stage">${esc(c.stage)}</span></li>`).join("")
      + (r.current.length > 8 ? `<li class="muted small">외 ${r.current.length - 8}건 처리 중</li>` : "");
    this.renderLog(r);
  },

  renderLog(r) {
    const ol = $("#r-log");
    if (!ol || !r) return;
    $("#r-logn").textContent = r.log.length ? `(${r.log.length})` : "";
    ol.innerHTML = r.log.slice().reverse().map((l) => `<li class="l-${l.level}"><time>${new Date(l.t * 1000)
      .toLocaleTimeString("ko-KR", { hour12: false })}</time>${l.store ? `<span class="muted">${esc(l.store)}</span>` : ""}<span>${esc(l.msg)}</span></li>`).join("");
  },

  clearSel() { this.sel.clear(); this.selAll = false; },

  bind() {
    $("#l-sales-file").addEventListener("change", (e) => { if (e.target.files[0]) App.upload("/api/orders/import", e.target.files[0]); e.target.value = ""; });
    $("#l-store").addEventListener("change", (e) => App.go(`#listings?store_id=${e.target.value}`));
    $("#l-tiles").addEventListener("click", (e) => {
      const t = e.target.closest("[data-filter]");
      if (!t) return;
      const k = t.dataset.filter;
      this.f.nv = "";
      if (k.startsWith("eye_")) { this.f.eye = k.slice(4); this.f.status = "all"; }
      else if (k === "nv_bad") { this.f.nv = "bad"; this.f.status = "all"; this.f.eye = ""; }
      else { this.f.status = k; this.f.eye = ""; }
      this.page = 0; this.clearSel(); this.load();
    });
    let timer;
    $("#l-q").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { this.f.q = e.target.value.trim(); this.page = 0; this.clearSel(); this.load(); }, 300);
    });
    $("#l-age").addEventListener("change", (e) => { this.f.age_days = e.target.value; this.page = 0; this.clearSel(); this.load(); });
    $("#l-rows").addEventListener("click", (e) => {
      if (e.target.closest("a")) return;   // 새 상품 ↗ · 원본 ↗ 는 새 창
      const rn = e.target.closest("[data-rename]");
      if (rn) return this.renameModal([+rn.dataset.rename]);
      const src = e.target.closest("[data-src]");
      if (src) return App.pages.inventory.openSource(+src.dataset.src);
      const go = e.target.closest("[data-go]");
      if (go) return this.goto(+go.dataset.go);
      const tr = e.target.closest("tr[data-id]");
      if (!tr) return;
      const id = +tr.dataset.id;
      if (e.target.closest("[data-stop]")) {
        if (this.selAll || !e.target.closest(".w-check")) return;
        this.sel.has(id) ? this.sel.delete(id) : this.sel.add(id);
        tr.classList.toggle("sel", this.sel.has(id));
        $("input", tr).checked = this.sel.has(id);
        this.renderBar();
        return;
      }
      this.openListing(id);
    });
  },

  async openListing(id) {
    let l;
    try { l = await App.api(`/api/listings/${id}`); } catch (e) { return App.toast(e.message, true); }
    const url = l.store_url && l.channel_no ? `${l.store_url.replace(/\/$/, "")}/products/${l.channel_no}` : "";
    App.openDrawer({
      title: l.name, sub: `${l.store_name} · ${statusLabel(l.status, l.op)} · ${l.round}회차`,
      tabs: [
        { key: "info", label: "정보", render: (b) => {
          b.innerHTML = (l.status === "fail" ? `<div class="notice err"><b>${esc(statusLabel(l.status, l.op))}</b><br>${esc(l.message)}
              ${/생활화학|살생물|productCertificationInfos/.test(l.message || "") ? `<br><button class="btn sm primary d-chem">생활화학 판정</button> <span class="small">물건이면 카테고리 그대로 '인증 대상 아님'으로 올리고, 화학제품이면 보류합니다 (애매하면 AI)</span>`
                : /카테고리|인증|category|certif/i.test(l.message || "") ? `<br><button class="btn sm d-cat">카테고리 바꾸기</button> <span class="small">원본에 저장되어 다른 스토어 복사본도 같이 바뀝니다</span>` : ""}</div>` : "")
            + (l.origin_no ? `<div class="notice ok"><b>판매 중</b> · 상품번호 ${esc(l.channel_no)} · ${ymd(l.registered_at)}에 올림 (${age(l.registered_at)})<br>
                ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">스토어에서 보기</a> · ` : ""}
                ${sellerLink((App.stores || []).find((s) => s.id === l.store_id), `https://sell.smartstore.naver.com/#/products/edit/${l.origin_no}`, "스마트스토어센터에서 수정")}</div>` : "")
            + `<div class="gallery">${img(l.thumb, "g-main")}</div>
              ${!l.origin_no && l.status !== "deleted" ? `<div class="notice ${l.name_id ? "" : "err"} name-edit">
                <div><b>${l.name_id ? "바꾼 상품명" : "이름 변경 필요 — 원본 상품명 그대로라 올리지 않습니다"}</b></div>
                <div class="add-name"><input id="d-name" value="${esc(l.name)}" maxlength="100"><button class="btn primary" id="d-name-save">이 이름으로</button></div>
                <span class="muted small">직접 고쳐 저장하거나 <button class="link-btn" id="d-rename">상품명 바꾸기</button>(AI 키워드·AI로 짓기·셔플). 금지어·상표·33개 스토어 중복을 검사합니다.</span></div>` : ""}
              <dl class="kv"><dt>스토어</dt><dd>${esc(l.store_name)}</dd>
              <dt>등록 상품명</dt><dd>${l.name_id ? nameDiff(l.nd) + ND_LEGEND : `${esc(l.name)} <span class="flag bad">원본 상품명 그대로</span>`}</dd>
              <dt>원본 상품명</dt><dd>${esc(l.source_name)} <button class="btn sm" id="d-src">원본 보기</button></dd>
              <dt>판매자 관리코드</dt><dd>${esc(l.seller_code || l.next_seller_code)} <span class="muted">(${l.round}회차${l.seller_code ? "" : ", 등록하면 붙음"})</span></dd>
              <dt>원본 번호</dt><dd>#${l.source_id}</dd>
              <dt>카테고리</dt><dd>${esc(l.category)}${l.category_fixed ? ` <span class="flag">직접 정함</span> <span class="muted small">(엑셀: ${esc(l.category_excel)})</span>` : ""}
                <button class="btn sm d-cat">바꾸기</button></dd>
              <dt>판매가</dt><dd>손님 가격 <b>${num(l.final)}원</b> <span class="muted">(기준 가격 ${num(l.source_price)}원)</span>
                ${l.off ? `<br><span class="muted">네이버 판매가 ${num(l.shown)}원 · 즉시할인 ${num(l.off)}원 (할인율 ${(l.off / l.shown * 100).toFixed(1)}% — 손님 가격을 그대로 두고 ${l.disc_pct}%에 가깝게)</span>` : ""}
</dd>
              <dt>다른 스토어</dt><dd>${l.siblings.length ? l.siblings.map((x) => `<div><button class="go-store" data-go="${x.id}">→ ${esc(x.store_name)}</button> ${esc(x.name)} <span class="muted">(${STATUS[x.status] || x.status})</span></div>`).join("") : "같은 원본이 다른 스토어에는 없음"}</dd></dl>`
            + `<div class="notice ${l.locked ? "info" : ""} lock-box"><div><b>${l.locked ? "잠금" : "잠금 아님"}</b>${l.locked ? ` · ${esc(l.lock_note)} · 최신화·내리기로 지우지 않습니다` : " · 최신화·내리기 가능"}
                ${l.cancel_count ? `<br><span class="muted">취소·반품 ${num(l.cancel_count)}개는 판매로 세지 않음 (설정에서 바꿈)</span>` : ""}</div>
                <button class="btn" id="d-lock">${l.manual_lock ? "직접 잠금 풀기" : "직접 잠금"}</button></div>`
            + (l.orders.length ? `<div><h3 class="sec-title">주문 (판매 ${num(l.sold_count)}개${l.cancel_count ? ` · 취소·반품 ${num(l.cancel_count)}개` : ""})</h3><table class="opt-table"><tr><th>주문</th><th>수량</th><th>결제일</th><th>가져온 곳</th></tr>
              ${l.orders.map((o) => `<tr><td>${esc(o.order_key.replace(/^file:/, ""))}<div class="p-sub">${esc(o.status)}</div></td><td>${num(o.quantity)}</td><td>${ymd(o.ordered_at)}</td>
              <td>${o.source === "naver" ? "네이버 주문" : "주문 파일"}</td></tr>`).join("")}</table></div>` : "")
            + (l.history.length ? `<div><h3 class="sec-title">지난 회차</h3><table class="opt-table"><tr><th>회차</th><th>관리코드</th><th>상품번호</th><th>올린 날</th><th>지운 날</th></tr>
              ${l.history.map((h) => `<tr><td>${h.round}</td><td>${esc(h.seller_code)}</td><td>${esc(h.channel_no)}</td><td>${ymd(h.registered_at)}</td>
              <td>${h.deleted_at ? ymd(h.deleted_at) : "스토어에서 이미 지움"} <span class="muted">${OP[h.reason] || "내리기"}</span></td></tr>`).join("")}</table></div>` : "");
          $("#d-name-save", b)?.addEventListener("click", async () => {
            try {
              const r = await App.api(`/api/listings/${id}/name`, { json: { name: $("#d-name", b).value } });
              App.toast(`상품명을 바꿨습니다: ${r.name}`);
              if ($("#l-rows")) this.load();
              this.openListing(id);
            } catch (err) { App.toast(err.message, true); }
          });
          $("#d-src", b)?.addEventListener("click", () => App.pages.inventory.openSource(l.source_id));
          $$(".d-cat", b).forEach((x) => x.addEventListener("click", () => App.pickCategory({
            target: { ids: [l.source_id] }, current: l.category, excel: l.category_excel, what: `원본 #${l.source_id}`,
            after: () => { this.openListing(id); if ($("#l-rows")) this.load(); } })));
          $("#d-rename", b)?.addEventListener("click", () => this.renameModal([id]));
          $(".d-chem", b)?.addEventListener("click", async () => { if (await App.yes("생활화학 판정", CHEM_JUDGE_TXT, { label: "판정 시작" })) App.startTask(App.api("/api/chem/judge", { json: { ids: [l.source_id] } })); });
          $$("[data-go]", b).forEach((x) => x.addEventListener("click", () => { App.closeDrawer(); this.goto(+x.dataset.go); }));
          $("#d-lock", b)?.addEventListener("click", async () => {
            const r = await this.lock(!l.manual_lock, [id]);
            if (r) { if ($("#l-rows")) this.load(); this.openListing(id); }
          });
        } },
        { key: "mobile", label: "휴대폰 미리보기", render: (b) => {
          const dc = l.body?.originProduct?.detailContent;
          if (typeof dc !== "string") { b.innerHTML = `<p class="muted">${esc(l.body?.["검사 오류"] || "상세를 만들지 못했습니다.")}</p>`; return; }
          const iss = l.mobile_issues || [];
          b.innerHTML = `${iss.length
              ? `<p class="mob-warn">⚠ 네이버 모바일에서 <b>흐린 캡처</b>로 보일 수 있습니다: ${esc(iss.join(", "))} — 스토어 템플릿 상단·하단 HTML도 확인하세요.</p>`
              : '<p class="mob-ok">✓ 표·링크·네이버 밖 이미지가 없어 네이버 모바일에서 캡처가 아닌 그대로(선명하게) 보입니다.</p>'}
            <p class="muted small" style="margin:0">휴대폰 너비(390px)로 보낼 상세를 그대로 그렸습니다. 옵션표는 올릴 때 이 그림을 네이버에 올려 씁니다.</p>
            <div class="mob-frame"><iframe sandbox="allow-same-origin" title="휴대폰 미리보기"></iframe></div>`;
          $("iframe", b).srcdoc = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
            <style>body{margin:0;padding:0 12px;font:15px/1.5 sans-serif;color:#111}img{max-width:100%;height:auto}</style>${dc}`;
        } },
        { key: "json", label: "보낼 데이터", render: (b) => {
          const body = JSON.parse(JSON.stringify(l.body));
          const dc = body?.originProduct?.detailContent;
          if (typeof dc === "string" && dc.length > 400) body.originProduct.detailContent = dc.slice(0, 400) + ` …(총 ${num(dc.length)}자)`;
          b.innerHTML = `<p class="muted small" style="margin:0">네이버 커머스API에 보낼 내용입니다. 아직 올리지 않은 이미지는 원본 주소로 보입니다.</p>
            <pre class="json">${esc(JSON.stringify(body, null, 2))}</pre>`;
        } },
      ],
      foot: ["planned", "fail"].includes(l.status) && !App.run?.running
        ? `<span class="muted"></span><button class="btn primary" id="d-run">이 건만 지금 처리</button>` : "",
    });
    $("#d-run")?.addEventListener("click", async () => {
      if (!await App.yes("이 건만 지금 처리", `이 복사본 한 건의 할 일(${$("#d-run").dataset.op || "대기 중인 일"})을 지금 바로 처리합니다. 내리기면 네이버에서 내려가고, 최신화면 지우고 다시 올립니다.`, { label: "지금 처리" })) return;
      try {
        App.run = await App.api("/api/run", { json: { ids: [id] } }); App.closeDrawer();
        if ($("#l-run")) this.renderRun(App.run); else App.renderSideRun();
      }
      catch (e) { App.toast(e.message, true); }
    });
  },
});
