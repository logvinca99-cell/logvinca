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
  { key: "custom", label: "맞춤 상품", dot: "var(--accent)", title: "고객 맞춤 상품 — 복사본과 따로 (복사 수·일괄 작업에 안 들어감, 자동으로 내리지 않음)" },
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
    if (!params.store_id) return this.pickStore(el);
    try { localStorage.setItem("last-store", String(params.store_id)); } catch (e) { /* 기억 못 해도 됨 */ }
    this.f = { status: "all", store_id: params.store_id, q: "", age_days: "", ...params };
    delete this.f.open;
    this.page = 0;
    this.size = App.pageSize("listings");
    this.sel = new Set();
    this.selAll = false;
    const store = App.stores.find((s) => s.id === +params.store_id);
    el.innerHTML = `<div class="page">
      <header class="page-head">
        <div class="store-head"><div class="sh-title"><div class="muted small">복사본${store?.business_name ? ` · ${esc(store.business_name)}` : ""}</div>
            <h1>${esc(store?.name || "스토어 없음")}</h1><div class="small" id="l-api"></div></div>
          ${store ? `<a class="btn ghost sm" href="#stores?store_id=${store.id}" title="이 스토어의 키·템플릿·연결 확인·메모 (스토어 화면)">스토어 설정 ↗</a>${storeLinks(store)}` : ""}</div>
        <div class="head-actions">
          <button class="btn primary" id="l-eye" title="썸네일만 그리드로 보며 이상한 상품을 골라 지우기">눈검수</button>
          <button class="btn" id="l-bulk" title="이 스토어 복사본의 손님 가격·상품명을 엑셀로 한꺼번에 고치기 (판매 중이면 지우지 않고 네이버 값만 바꿈)">일괄 수정 (엑셀)</button>
          <button class="btn" id="l-nv" title="네이버 상품 목록을 받아 판매 중 복사본마다 판매 중·품절·판매중지·판매금지·스토어에 없음을 표시 (최신화 직전에도 자동으로 확인)">네이버 상태 확인</button>
          <button class="btn" id="l-sales" title="이 스토어 판매 이력 확인: 판매 현황 파일 넣기 · 파일 없이 직접 잠그고 확인 완료">판매 이력 확인</button>
          <a class="btn" href="#orders" title="넣은 판매 이력(주문)을 기간·스토어별로 보기">판매 현황</a>
          <button class="btn" id="l-custom-new" title="고객 문의용 맞춤 상품(대량 할인·다른 출고지·주문제작)을 이 스토어에 새로 만들기 — 복사 수에 안 들어감">맞춤 상품 새로 만들기</button>
        </div></header>
      <div class="card run" id="l-run"><div id="l-run-main"></div></div>
      <div class="run-others" id="l-run-others" hidden></div>
      <div id="l-sales-warn"></div>
      <div id="l-push"></div>
      <div id="l-pchk"></div>
      <div class="tiles" id="l-tiles"></div>
      <div class="filters-row">
        <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
          <input id="l-q" placeholder="상품명·관리코드·상품번호 검색"></div>
        <select id="l-age" class="sel"><option value="">올린 날 전체</option><option value="7">올린 지 7일 넘음</option>
          <option value="30">30일 넘음</option><option value="60">60일 넘음</option><option value="90">90일 넘음</option></select>
      </div>
      <div id="l-custom" hidden></div>
      <div class="listbar" id="l-bar"></div>
      <div class="card table-card" id="l-table">
        <table class="grid"><thead><tr><th class="w-check"></th>
          <th class="w-thumb"></th><th>등록 상품명 <span class="muted small" style="font-weight:400">(원본과 비교)</span>${ND_LEGEND}</th>
          <th class="w-links">바로 가기</th><th class="w-round">관리코드 · 올린 날</th><th class="w-num">손님 가격</th><th class="w-status">상태</th></tr></thead><tbody id="l-rows"></tbody></table>
        <div class="pg-foot"><div class="pg" id="l-pager"></div></div>
      </div>
    </div>`;
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

  /* 스토어 없이 들어오면: 마지막으로 본 스토어(없으면 첫 스토어)로. 스토어는 왼쪽 메뉴에서 고른다 */
  pickStore(el) {
    const ss = App.stores || [];
    let last = null;
    try { last = +localStorage.getItem("last-store"); } catch (e) { /* 없음 */ }
    const s = ss.find((x) => x.id === last) || ss.find((x) => x.enabled) || ss[0];
    if (s) { location.replace(`#listings?store_id=${s.id}`); return; }
    el.innerHTML = `<div class="page"><header class="page-head"><h1>복사본</h1></header>
      <p class="muted">스토어가 없습니다. <a href="#stores">스토어</a>에서 먼저 추가하세요.</p></div>`;
  },

  /* (예전) 복사본 첫 화면의 스토어 카드 — 스토어는 이제 왼쪽 메뉴에서 고름 */
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
    if (f.status === "all" || f.status === "custom") delete f.status;
    return f;
  },

  async load() {
    const qs = new URLSearchParams({ ...this.query(), page: this.page, size: this.size });
    const res = await App.api(`/api/listings?${qs}`);
    this.counts = res.counts || {};
    this.rows = res.rows;
    this.total = res.total;
    if (setHtml($("#l-sales-warn"), this.counts.need_sales ? `<div class="notice warn" style="margin-bottom:10px">판매 중 상품 <b>${num(this.counts.need_sales)}</b>개는
      <b>판매 이력 확인 전</b>이라 최신화·내리기를 하지 않습니다 (팔린 상품을 지우지 않게). <button class="btn tiny primary" id="l-sales-go">판매 이력 확인</button></div>` : "")) $("#l-sales-go")?.addEventListener("click", () => App.salesConfirm(+this.f.store_id, () => this.load()));
    if (!this._apiAt || Date.now() - this._apiAt > 15000) {   // 이 스토어 네이버 API 사용량 (이번 시간대) · 한도 멈춤
      this._apiAt = Date.now();
      App.api("/api/apiuse").then((u) => {
        const a = (u.stores || {})[String(this.f.store_id)];
        const box = $("#l-api");
        if (box && a) setHtml(box, apiUseLine(a, a.quota_until));
      }).catch(() => {});
    }
    App.api(`/api/listings/push_pending?store_id=${this.f.store_id}`).then((p) => {   // 네이버 반영 대기 (가격·상품명 바꾸기를 못 보낸 것)
      const box = $("#l-push");
      if (!box) return;
      const n = (p.price || 0) + (p.name || 0) + (p.detail || 0);
      if (!setHtml(box, n ? `<div class="notice warn" style="margin-bottom:10px">네이버 반영 대기 <b>${num(n)}</b>건 (가격 ${num(p.price)} · 상품명 ${num(p.name)} · 상세 ${num(p.detail || 0)}) —
        실패했거나 아직 못 보낸 가격·상품명·상세 바꾸기입니다(상품은 지우지 않음). <b>자동으로 다시 보내지 않습니다</b> — 필요할 때 <button class="btn tiny primary" id="l-push-go">네이버 반영 다시 시도</button></div>` : "")) return;
      $("#l-push-go")?.addEventListener("click", async () => {
        if (!await App.yes("네이버 반영 다시 시도", `대기 중인 ${num(n)}건의 네이버 가격·상품명·상세를 다시 보냅니다 (상품은 지우지 않음).`, { label: "다시 보내기" })) return;
        App.startTask(App.api("/api/listings/push_retry", { json: { store_id: +this.f.store_id } }));
      });
    }).catch(() => {});
    App.api(`/api/listings/price_check?store_id=${this.f.store_id}`).then((p) => {   // 네이버 가격 ≠ 업스타 가격
      const box = $("#l-pchk");
      if (!box) return;
      if (!setHtml(box, p.total ? `<div class="notice warn" style="margin-bottom:10px">가격 확인 필요 <b>${num(p.total)}</b>건 —
        네이버 가격이 업스타 가격(기준 가격 × 스토어 가격 차이 %)과 다릅니다. <button class="btn tiny primary" id="l-pchk-go">확인하고 맞추기</button></div>` : "")) return;
      $("#l-pchk-go")?.addEventListener("click", () => this.priceCheck(p));
    }).catch(() => {});
    // 목록을 다시 그려도 보고 있던 줄이 화면에서 튀지 않게: 화면 맨 위에 보이던 줄 위치를 기억했다가 되돌림
    let anchor = null;
    if (window.scrollY > 0) {
      const tr = [...document.querySelectorAll("#l-rows tr[data-id]")].find((x) => x.getBoundingClientRect().top >= 0);
      if (tr) anchor = { id: tr.dataset.id, top: tr.getBoundingClientRect().top };
    }
    const active = this.f.eye ? `eye_${this.f.eye}` : this.f.nv === "bad" ? "nv_bad" : this.f.status;
    setHtml($("#l-tiles"), tilesHtml(LST_TILES.filter((t) => !t.only || this.counts[t.key] || active === t.key), { ...this.counts, all: this.counts.all_ }, active));
    // 맞춤 상품 칸: 복사본 목록 대신 이 스토어 맞춤 상품 목록 (들어올 때 한 번 그림 — 주기 갱신으로 다시 그리지 않음)
    const cust = this.f.status === "custom";
    for (const id of ["#l-bar", "#l-table"]) { const x = $(id); if (x) x.hidden = cust; }
    const cbox = $("#l-custom");
    if (cbox) {
      cbox.hidden = !cust;
      if (cust && !this._custOn) { this._custOn = true; Custom.render(cbox, +this.f.store_id, this.f.q || ""); }
      if (!cust) this._custOn = false;
    }
    if (cust) { this.renderOthers(App.run); return; }
    // 목록은 통째로 다시 그리지 않고 바뀐 줄만 바꿈 (같은 줄들이면) — 주기 갱신에 화면·스크롤·선택이 흔들리지 않게
    if (res.rows.length) patchRows($("#l-rows"), res.rows.map((l) => [String(l.id), this.rowHtml(l)]));
    else setHtml($("#l-rows"), `<tr class="empty-row"><td colspan="7">${this.counts.all_ ? "조건에 맞는 건이 없습니다."
        : '이 스토어에 복사본이 없습니다. <a href="#inventory">원본 상품</a>에서 원본을 고르고 <b>다른 스토어로 복사</b>를 누르세요.'}</td></tr>`);
    this.renderBar();
    if (!this._mine(App.run)) this.renderIdle();
    if (anchor) {
      const tr = document.querySelector(`#l-rows tr[data-id="${anchor.id}"]`);
      if (tr) { const d = tr.getBoundingClientRect().top - anchor.top; if (Math.abs(d) > 1) window.scrollBy(0, d); }
    }
    this.renderOthers(App.run);
  },

  /* 가격 확인 필요: 네이버 가격 ≠ 업스타 가격인 판매 중 복사본을 골라 (가) 업스타 가격으로 / (나) 네이버 가격을 새 기준 가격으로 */
  priceCheck(p) {
    const rows = p.rows || [];
    const sel = new Set(rows.map((r) => r.id));
    const srcN = {};
    rows.forEach((r) => { srcN[r.source_id] = (srcN[r.source_id] || 0) + 1; });
    const go = async (mode) => {
      const ids = rows.filter((r) => sel.has(r.id)).map((r) => r.id);
      const res = await App.api("/api/listings/price_check/fix", { json: { ids, mode } });
      App.toast(`${num(res.count)}건 맞춤 · 네이버 가격 바꾸기 ${num(res.live)}건` + (res.sources ? ` · 기준 가격 바꾼 원본 ${num(res.sources)}개` : "")
        + (res.queued ? " (도는 작업이 끝나면 이어서)" : ""));
      if (res.task) App.startTask(Promise.resolve({ task: res.task }));
      this.load();
    };
    App.openModal({
      title: `가격 확인 필요 ${num(p.total)}건`, wide: true,
      body: (b) => {
        b.innerHTML = `<p class="small muted" style="margin:0 0 8px">연결 확인 때 읽은 <b>네이버 가격</b>이 <b>업스타 가격</b>(기준 가격 × 그 스토어 가격 차이 %)과 다른 판매 중 상품입니다.
          업스타는 판매자센터 가격을 따르지 않으니, 고른 것을 둘 중 하나로 맞추세요.</p>
          ${p.total > rows.length ? `<p class="small c-err">앞 ${num(rows.length)}건만 보입니다 — 맞춘 뒤 다시 여세요.</p>` : ""}
          <div class="tbl-wrap" style="max-height:420px"><table class="grid small"><thead><tr><th><input type="checkbox" id="pc-all" checked aria-label="모두 고르기"></th>
            <th>스토어</th><th>업스타 기준상품명</th><th class="r">업스타 가격</th><th class="r">네이버 가격</th><th class="r">차이</th></tr></thead><tbody>
            ${rows.map((r) => `<tr><td><input type="checkbox" data-pc="${r.id}" checked aria-label="고르기"></td><td>${esc(r.store_name)}</td>
              <td>${esc(r.source_name)}${srcN[r.source_id] > 1 ? ' <span class="flag warn" title="이 원본은 여러 스토어에서 네이버 가격이 다릅니다 — \'네이버 가격을 기준 가격으로\'는 한 스토어만 고르세요">여러 스토어</span>' : ""}${r.locked ? ' <span class="flag">잠김</span>' : ""}</td>
              <td class="r">${num(r.upstar)}원</td><td class="r">${num(r.nv_price)}원</td><td class="r ${r.diff > 0 ? "c-ok" : "c-err"}">${r.diff > 0 ? "+" : ""}${num(r.diff)}</td></tr>`).join("")}
            </tbody></table></div>`;
        $("#pc-all", b).addEventListener("change", (e) => { $$("[data-pc]", b).forEach((x) => { x.checked = e.target.checked; if (x.checked) sel.add(+x.dataset.pc); else sel.delete(+x.dataset.pc); }); });
        $$("[data-pc]", b).forEach((x) => x.addEventListener("change", () => { if (x.checked) sel.add(+x.dataset.pc); else sel.delete(+x.dataset.pc); }));
      },
      buttons: [{ label: "닫기" },
        { label: "네이버 가격을 새 기준 가격으로", noPicks: true, validate: () => (!sel.size ? "고른 것이 없습니다." : ""),
          confirm: "고른 상품의 지금 네이버 가격을 거꾸로 계산해 원본의 새 기준 가격으로 정합니다. 그 원본의 다른 스토어 판매 중 복사본도 새 가격으로 바뀝니다 (한 원본은 한 스토어만).",
          onClick: () => go("naver") },
        { label: "업스타 가격으로 맞추기", primary: true, noPicks: true, validate: () => (!sel.size ? "고른 것이 없습니다." : ""),
          confirm: "고른 상품의 네이버 가격을 업스타 가격(기준 가격 × 스토어 가격 차이 %)으로 바로 바꿉니다 (상품은 지우지 않음).",
          onClick: () => go("upstar") }],
    });
  },

  pagerOpts() {
    return { page: this.page, size: this.size, total: this.total, unit: "건",
      onPage: (p) => { this.page = p; this.load(); },
      onSize: (n) => { this.size = n; App.savePageSize("listings", n); this.page = 0; this.load(); } };
  },

  renderBar() {
    const n = this.selAll ? this.total : this.sel.size;
    App.listBar($("#l-bar"), {
      ...this.pagerOpts(), count: n, selAll: this.selAll, what: "복사본",
      pageChecked: this.rows.length > 0 && this.rows.every((l) => this.sel.has(l.id)),
      actions: [
        { id: "rename", label: "상품명 바꾸기", primary: true, title: "아직 안 올린 복사본의 상품명을 AI 키워드·AI로 짓기·셔플로 바꿈" },
        "|등록",
        { id: "refresh", label: "최신화", title: "판매 중인 건을 네이버에서 지우고 같은 내용으로 다시 올림 (회차 +1) · 누르면 바로 시작 (다른 스토어가 돌고 있어도 함께)" },
        { id: "reupload", label: "다시 올리기", title: "문제가 있어 지우고 같은 내용(같은 상품명)으로 다시 올림 · 판매 중인 건은 지우고 다시, 내린 건은 그냥 다시 · 최신화와 따로 기록" },
        { id: "delete", label: "내리기", title: "판매 중인 건을 네이버에서 지움 · 누르면 바로 시작 (다른 스토어가 돌고 있어도 함께)" },
        { id: "cancel", label: "대기·실패 취소", danger: true, title: "아직 처리 안 된 대기·실패 할 일을 취소" },
        "|수정",
        { id: "price", label: "가격 수정", title: "고른 복사본 원본의 기준 가격을 직접 입력 / n원 / n% 올리기·내리기 → 모든 스토어 복사본이 같이 바뀌고(각 스토어 가격 차이 % 반영), 판매 중은 네이버 가격만 바로" },
        { id: "category", label: "카테고리 바꾸기", title: "고른 복사본의 원본 카테고리를 직접 정함 (인증 때문에 안 올라가는 카테고리 등) — 그 원본의 다른 스토어 복사본도 같이" },
        { id: "chem", label: "생활화학 판정", title: "고른 복사본의 원본을 판정: 물건이면 '인증 대상 아님'으로 다시 등록 대기, 화학제품이면 보류 (애매하면 AI)" },
        { id: "infopush", label: "네이버 상품 정보 바꾸기", title: "고른 판매 중 복사본의 상세·브랜드·제조사·모델명을 지금 원본·설정 기준으로 네이버에서 바꿈 (지우지 않음 → 상품번호·리뷰 그대로, 잠긴 것 포함)" },
        { id: "clean", label: "상세 정리로 보내기", title: "고른 복사본의 원본 상세를 상세 정리에서 정리 → [원본에 반영]하면 원본 상세가 바뀌고 판매 중 복사본은 네이버 상세만 바꿈 (지우지 않음)" },
        { id: "resetround", label: "회차 초기화", title: "지난 회차 기록을 지우고 1회차로 (다시 다 올릴 때) · 판매 중·내린 건은 다음에 다시 올릴 때 1회차로" },
        "|보호",
        { id: "lock", label: "잠금", title: "판매 이력과 상관없이 지우지 못하게 잠금" },
        { id: "unlock", label: "잠금 풀기" },
        "|이동",
        { id: "move", label: "다른 스토어로 보내기", title: "아직 안 올린·내린 복사본을 다른 스토어로 옮김 (이 스토어에서는 사라짐) — 받는 스토어 남은 자리만큼" },
        { id: "revert", label: "원본으로 되돌리기", title: "아직 안 올린·내린 복사본을 이 스토어에서 없앰 → 원본의 복사 자리가 비고 상품명은 후보로 (A였으면 다음 복사에 다시 A)" },
        "|검수",
        { id: "eyeon", label: "검수 완료로 표시", title: "고른 복사본의 원본을 검수 완료로 (새로 올릴 수 있게) — 원본 기준이라 다른 스토어 복사본도 같이" },
        { id: "eyeoff", label: "검수 완료 풀기" },
        "|",
        { id: "remove", label: "삭제", danger: true, title: "기본: 원본까지 같이 삭제 (그 원본의 모든 스토어 복사본, 판매 중인 것은 내린 뒤) · 끄면 고른 복사본만 휴지통" },
        "|",
        { id: "export", always: true, label: n && !this.selAll ? `⬇ 엑셀 받기 — 고른 ${num(n)}건` : `⬇ 엑셀 받기 — ${this.selAll ? "조건에 맞는" : "지금 보이는 조건"} ${num(this.total)}건`,
          title: "복사본 목록을 엑셀로 받습니다: 스토어·판매자 관리코드·회차·등록 상품명·원본 번호·원본 판매자코드·업스타 기준상품명·손님 가격·네이버 판매가·기준 가격·상태·할 일·잠금·올린 날·원상품번호·채널상품번호·메시지" },
      ],
      onPageCheck: (on) => { this.selAll = false; this.rows.forEach((l) => (on ? this.sel.add(l.id) : this.sel.delete(l.id))); this.load(); },
      onAll: () => { this.selAll = true; this.sel.clear(); this.load(); },
      onClear: () => { this.clearSel(); this.load(); },
      onAction: (id) => this.action(id),
    });
    App.pagerBar($("#l-pager"), this.pagerOpts());
    if (this.runRange === "sel" && !this._mine(App.run) && $("#l-run")) this.renderIdle();   // 고른 수가 바뀌면 시작 범위도
  },

  async action(id) {
    if (id === "rename") this.renameModal();
    if (id === "infopush") this.infoPush();
    if (id === "price") App.priceEdit({ level: "listing", target: this.target(), n: this.selAll ? this.total : this.sel.size, after: () => { this.estKey = ""; this.load(); } });
    if (id === "clean") App.sendToClean({ listing_filter: this.target() }, `고른 복사본 ${num(this.selAll ? this.total : this.sel.size)}건의 원본`);
    if (id === "export") {   // 고른 것이 있으면 그것만, 없으면 지금 보이는 조건 전체
      const q = this.sel.size && !this.selAll ? { store_id: this.f.store_id, ids: [...this.sel].join(",") } : this.query();
      window.location.href = `/api/listings/export.xlsx?${new URLSearchParams(q)}`;
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
    const flags = (noname ? `<span class="flag bad" title="후보상품명이 없어 올리지 않습니다 (타스토어 원본 상품명 그대로는 올리지 않음)">이름 변경 필요</span>` : "")
      + (l.rep_word ? `<span class="flag warn" title="'${esc(l.rep_word)}'가 3번 이상 나옵니다 — 상품명 바꾸기로 다시 만드세요">반복: ${esc(l.rep_word)}</span>` : "")
      + (l.name_origin ? `<span class="org org-${l.name_origin}" title="${l.name_origin === "ctx" ? "ai상품명 양식 (A = 첫 복사용, B = 양식이 조금 다른 두 번째) — 원본 상품 화면에서 후보상품명 칸 전체를 볼 수 있음" : ""}">${l.name_origin === "ctx" && l.ai_label ? `ai상품명${esc(l.ai_label)}` : ORIGIN[l.name_origin] || l.name_origin}</span>` : "") + lockFlag(l) + salesFlag(l) + eyeFlag(l)
      + (l.adopted ? '<span class="flag adopted" title="판매 중 상품 연결로 들어온 원본">연결함</span>' : "")
      + (l.nv_diff ? `<span class="flag warn" title="연결 확인 때 읽은 네이버 가격 ${num(l.nv_diff.nv)}원 ≠ 업스타 가격 ${num(l.nv_diff.upstar)}원 (위 '가격 확인 필요'에서 맞춤)">가격 다름</span>` : "")
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

  /* 잘못 넣은 판매 이력: 이 복사본에 맞춘 주문을 무시해 판매 수·잠금에서 뺌 (on=false면 무시 풀기 — 다시 셈) */
  async ignoreOrders(id, on, l) {
    let rows = [];
    try { rows = await App.api(`/api/listings/${id}/orders`); } catch (e) { return App.toast(e.message, true); }
    const tgt = rows.filter((o) => (on ? !o.ignored : o.ignored));
    if (!tgt.length) return App.toast(on ? "무시할 주문이 없습니다." : "무시한 주문이 없습니다.", true);
    App.openModal({
      title: on ? "판매 이력 무시하고 잠금 풀기" : "판매 이력 무시 풀기",
      body: `<div class="notice ${on ? "warn" : ""}">${on
          ? `이 복사본(${esc(l.store_name || "")} · ${esc((l.name || "").slice(0, 30))})에 맞춘 주문 <b>${num(tgt.length)}건</b>을 <b>무시</b>합니다. 판매 수·잠금에서 빠져 <b>최신화·내리기로 네이버에서 지울 수 있게</b> 됩니다.
             <br><b>정말 팔린 상품이면 리뷰·판매 기록이 사라질 수 있으니</b>, 잘못 넣은 판매 이력이 확실할 때만 하세요. (판매 현황 화면에서 파일째 되돌리기도 있습니다)`
          : `무시했던 주문 <b>${num(tgt.length)}건</b>을 다시 판매 이력으로 셉니다 — 잠금이 다시 걸립니다.`}</div>
        <div class="tbl-wrap" style="max-height:260px"><table class="opt-table"><tr><th>주문</th><th>상태</th><th>수량</th><th>결제일</th><th>가져온 곳</th></tr>
          ${tgt.map((o) => `<tr><td>${esc(String(o.order_key).replace(/^file:/, ""))}<div class="p-sub">${esc((o.product_name || "").slice(0, 40))}</div></td>
            <td>${esc(o.status_ko || o.status || "")}</td><td>${num(o.quantity)}</td><td>${o.ordered_at ? ymd(o.ordered_at) : "-"}</td>
            <td>${o.source === "naver" ? "네이버 주문" : "주문 파일"}</td></tr>`).join("")}</table></div>`,
      buttons: [{ label: "취소" }, { label: on ? "무시하고 잠금 풀기" : "무시 풀기", danger: on, primary: !on,
        confirm: on ? `주문 ${num(tgt.length)}건을 무시해 이 복사본의 잠금을 풉니다 (판매 이력 확인 기준은 그대로).` : `주문 ${num(tgt.length)}건을 다시 판매 이력으로 셉니다.`,
        onClick: async () => {
          const r = await App.api(`/api/listings/${id}/ignore_orders`, { json: { on } });
          App.toast(on ? (r.locked ? `주문 ${num(r.count)}건을 무시했지만 아직 잠겨 있습니다 (${r.lock_note})` : `주문 ${num(r.count)}건을 무시하고 잠금을 풀었습니다.`)
            : `무시를 풀었습니다 — ${r.locked ? `다시 잠김 (${r.lock_note})` : "잠금 없음"}.`, on && r.locked);
          if ($("#l-rows")) this.load();
          this.openListing(id);
        } }],
    });
  },

  async lock(on, ids) {
    if (!on && !await App.yes("직접 잠금 풀기", `${ids ? `복사본 ${num(ids.length)}건` : "고른 복사본"}의 직접 잠금을 풉니다. 풀면 최신화·내리기로 네이버에서 지울 수 있게 됩니다 (판매 이력이 있는 것은 잠금 유지).`, { label: "잠금 풀기", danger: true })) return;
    try {
      const r = await App.api("/api/listings/lock", { json: { ...(ids ? { ids } : this.target()), lock: on } });
      App.toast(on ? `${num(r.count)}건을 잠갔습니다. 최신화·내리기로 지우지 않습니다.`
        : `${num(r.count)}건의 직접 잠금을 풀었습니다.` + (r.still_locked ? ` ${num(r.still_locked)}건은 판매 이력이 있어 잠금이 유지됩니다 — 잘못 넣은 판매 이력이면 판매 현황의 [이 파일 되돌리기] 또는 복사본 상세의 [판매 이력 무시하고 잠금 풀기]` : ""));
      if (!ids) { this.clearSel(); this.load(); }
      return r;
    } catch (e) { App.toast(e.message, true); }
  },

  /* 상품명 바꾸기 창 — 한 창 안에서 끝까지: 방식 고르기 → (상표 단어가 있으면) 상표 단계 → (키워드가 필요하면) 비용 단계
     → 진행 → 결과. 못 만든 것은 원본별 까닭(실제 값)과 처리 버튼을 같은 창에 보여 주고 거기서 바로 처리한다.
     ids를 주면 그 건만 */
  renameModal(ids) {
    const s = App.state.settings;
    const target = ids ? { ids } : this.target();
    const n = ids ? ids.length : this.selAll ? this.total : this.sel.size;
    const keyOk = s.has_anthropic_api_key || App.state.fake_api;
    this._rn = { title: `상품명 바꾸기 · 복사본 ${num(n)}건`, target, n, opt: {} };
    App.openModal({
      title: this._rn.title,
      body: `<div class="form"><div class="radio-cards">
          <label><input type="radio" name="rn" value="ctx" checked><div><b>AI 키워드 (기본)</b><span class="muted small">[원본 앞 ${num(s.ctx_head_n)}단어] + 원본 핵심 단어(keep) + 다른 이름(core) + 용도·조합(core2) + 맥락 + 남은 원본 단어 (A·B는 보라·맥락을 나눠 쓰고, B는 앞 3단어만 두고 섞음), 최대 ${num(s.name_max_len)}자. 키워드가 없는 원본은 먼저 받습니다(이 창에서 비용 안내).</span></div></label>
          <label><input type="radio" name="rn" value="ai"><div><b>AI로 짓기</b><span class="muted small">AI(${esc(s.ai_model)})가 원본을 보고 이름 전체를 새로 짓습니다 (비용 듦).</span></div></label>
          <label><input type="radio" name="rn" value="shuffle"><div><b>셔플 (AI 안 씀)</b><span class="muted small">앞 단어를 고정하고 나머지 단어 순서를 섞습니다. 넣을 단어를 적으면 그 단어도 고정 단어 뒤에서 함께 섞입니다.</span>
            <div class="shuffle-opts" style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
              <label class="field" style="margin:0">앞에서 고정할 단어 수 <input type="number" id="rn-fixed" min="0" max="10" value="${num(s.shuffle_fixed || 3)}" style="width:80px"></label>
              <label class="field" style="margin:0;flex:1;min-width:220px">넣을 단어 (띄어쓰기·쉼표로 구분, 비워도 됨) <input id="rn-extra" placeholder="예: 업소용 카페"></label>
            </div></div></label>
        </div>
        <label class="check"><input type="checkbox" id="rn-redo"> 이미 이름이 붙은 복사본도 새 이름으로 바꾸기 <span class="muted small">(끄면 '이름 변경 필요'인 것만 — 기본)</span></label>
        <label class="check"><input type="checkbox" id="rn-again"> AI 키워드를 새로 받기 <span class="muted small">(AI 키워드 방식 · 이미 받은 원본도 — 비용 듦, 이 창에서 즉시·일괄과 비용 안내)</span></label>
        ${keyOk ? "" : '<p class="c-err small">AI 키워드·AI로 짓기는 설정 → API 키에서 Anthropic 키를 먼저 넣어야 합니다.</p>'}
        <p class="muted small">이미 올라간 복사본은 바꾸지 않습니다(최신화로 다시 올릴 때 바뀜). 모든 이름은 금지어·상표·전체 스토어 중복을 검사합니다.
          못 만든 것은 이 창에서 까닭과 함께 보여 주고 바로 처리할 수 있습니다.</p></div>`,
      buttons: [{ label: "취소" }, { label: "바꾸기", primary: true, noConfirm: true, onClick: (b) => {
        const R = this._rn;
        R.opt = { method: $("input[name=rn]:checked", b).value, redo: $("#rn-redo", b).checked, again: $("#rn-again", b).checked,
          fixed_n: +$("#rn-fixed", b).value, extra: $("#rn-extra", b).value };
        this._rnStart();
        return false;   // 창은 닫지 않음 — 같은 창에서 다음 단계
      } }],
    });
  },

  /* 같은 창의 다음 화면 (제목은 그대로). ✕로 닫으면 기다리던 단계는 취소, 진행 중인 작업은 뒤에서 계속 */
  _rnView(body, buttons = []) {
    this._rnOnClose = this._rnOnClose || (() => this._rnClosed());   // 같은 함수 — 화면을 바꿀 때 '닫힘'으로 치지 않게
    App.openModal({ title: this._rn.title, body, buttons, wide: true, onClose: this._rnOnClose });
  },
  _rnClosed() {
    const R = this._rn;
    if (!R) return;
    if (R.pend) { const f = R.pend; R.pend = null; f(null); }
    if (R.task && !R.bg) this._rnBackground();
    R.closed = true;
    if (App.current === this && $("#l-rows")) this.load();
    App.refreshState();
  },
  _rnAsk(body, buttons) {   // 버튼으로 값을 고르는 화면 → Promise(값 | null)
    return new Promise((resolve) => {
      this._rn.pend = resolve;
      this._rnView(body, buttons.map((x) => ({ ...x, noConfirm: true, onClick: x.value === undefined ? undefined : (b) => {
        const v = typeof x.value === "function" ? x.value(b) : x.value;
        const f = this._rn.pend; this._rn.pend = null;
        if (f) f(v);
        return false;
      } })));
    });
  },

  async _rnStart() {
    const R = this._rn, { target, opt } = R;
    this._rnView('<p><span class="spin"></span> 상표 단어 확인 중…</p>');
    try {
      if (opt.method !== "ai") {
        const mc = await App.api("/api/names/mark_check", { json: { listing_filter: target } });
        if (mc.sources || mc.kw_sources) {
          const mm = await this._rnMarkStep(mc);
          if (mm === null || R.closed) return;
          opt.mark_mode = mm;
        }
      }
      if (opt.method === "ctx") {
        const t = { listing_filter: target, again: opt.again, mark_mode: opt.mark_mode || undefined };
        const est = await App.api("/api/ctx/estimate", { json: t });
        if (est.sources) {
          const mode = await this._rnCostStep(t, est, "키워드가 없는(또는 새로 받을) 원본");
          if (mode === null || R.closed) return;
          if (mode !== "skip" && !(await this._rnKeywords(t, mode))) return;
        }
      }
      await this._rnRename(target, opt);
    } catch (e) { this._rnErr(e); }
  },
  _rnErr(e) {
    this._rnView(`<div class="notice err">${esc(e.message || String(e))}</div>`, [{ label: "닫기" }]);
  },

  _rnMarkTable(ws) {
    return `<div class="tbl-wrap" style="max-height:180px"><table class="grid small"><thead><tr><th>상표 단어</th><th>구분</th><th class="w-num">원본</th><th>예시</th></tr></thead>
      <tbody>${ws.map((w) => `<tr><td><b>${esc(w.word)}</b></td><td>${esc(w.verdict)}</td><td class="num">${num(w.n)}</td>
        <td class="muted">${w.examples.map((x) => `#${x.id} ${esc(x.name.slice(0, 40))}`).join("<br>")}</td></tr>`).join("")}</tbody></table></div>`;
  },
  _rnMarkStep(mc) {
    return this._rnAsk(`<div class="form">
        <div class="notice warn"><b>상표 단어가 들어 있는 원본 ${num(Math.max(mc.sources, mc.kw_sources))}개</b> — 어떻게 만들지 고르세요.</div>
        ${mc.sources ? `<p class="small"><b>업스타 기준상품명</b>에 든 상표 단어 — 원본 ${num(mc.sources)}개 (그대로면 이 원본은 이름을 못 만듦)</p>${this._rnMarkTable(mc.words)}` : ""}
        ${mc.kw_sources ? `<p class="small" style="margin-top:8px"><b>AI 키워드</b>에 든 상표 단어 — 원본 ${num(mc.kw_sources)}개</p>${this._rnMarkTable(mc.kw_words)}` : ""}
        <div class="radio-cards" style="margin-top:8px">
          <label><input type="radio" name="mk" value="drop" checked><div><b>상표 단어 빼고 만들기</b><span class="muted small">그 단어를 빼고 다음 원본 단어로 채워 만듭니다 (추천)</span></div></label>
          <label><input type="radio" name="mk" value="allow"><div><b>상표 단어 무시하고 그대로 넣어 만들기</b><span class="muted small">위 표의 상표 단어는 그대로 씁니다 (표에 없는 상표 단어는 계속 막음)</span></div></label>
          <label><input type="radio" name="mk" value="skip"><div><b>이 원본들은 건너뛰기</b><span class="muted small">'이름 변경 필요'로 둡니다</span></div></label>
        </div></div>`,
    [{ label: "취소" }, { label: "이대로 진행", primary: true, value: (b) => $("input[name=mk]:checked", b).value }]);
  },

  /* AI 키워드 비용 단계 (이 창 안): → "instant" | "batch" | "skip"(키워드 없이 진행) | null */
  async _rnCostStep(t, est, what) {
    const [eb, ei] = await Promise.all([App.api("/api/ctx/estimate", { json: { ...t, mode: "batch" } }), App.api("/api/ctx/estimate", { json: { ...t, mode: "instant" } })]);
    const inst = (App.state.settings.ctx_mode || "instant") === "instant";
    return this._rnAsk(`<div class="form">
        <div class="notice">${esc(what)} <b>${num(est.sources)}개</b>는 AI 키워드를 받아야 이름을 만들 수 있습니다 (비용 듦).</div>
        ${est.has_key ? "" : '<p class="c-err small">설정 → AI 상품명에 Anthropic API 키를 먼저 넣어야 합니다.</p>'}
        <div class="radio-cards">
          <label><input type="radio" name="rc" value="instant" ${inst ? "checked" : ""}><div><b>즉시</b> 약 <b>${num(ei.krw)}원</b><span class="muted small">1~2분 안에 받고, 이 창에서 바로 이름을 붙입니다.</span></div></label>
          <label><input type="radio" name="rc" value="batch" ${inst ? "" : "checked"}><div><b>일괄 (50% 할인)</b> 약 <b>${num(eb.krw)}원</b><span class="muted small">몇 분~몇 시간 뒤 받으면 자동으로 이름이 붙습니다. 키워드가 있는 원본은 지금 바로 바꿉니다.</span></div></label>
        </div></div>`,
    [{ label: "취소" }, { label: "키워드 없이 진행", value: "skip" }, { label: "키워드 받고 진행", primary: true, value: (b) => $("input[name=rc]:checked", b).value }]);
  },
  /* 키워드 받기: 즉시면 이 창에서 받을 때까지 기다림, 일괄이면 보내고 계속 → 성공 여부 */
  async _rnKeywords(t, mode) {
    const r = await App.api("/api/ctx/start", { json: { ...t, mode } });
    if (mode !== "instant") {
      this._rn.note = r.started ? `AI 키워드를 일괄로 보냈습니다 (원본 ${num(r.sources)}개, 예상 약 ${num(r.est_krw)}원) — 받으면 그 원본 복사본에 이름이 자동으로 붙습니다.` : r.message;
      return true;
    }
    if (!r.task) { this._rn.note = r.message || ""; return true; }
    const k = await this._rnWait(r.task, "AI 키워드 받는 중", false);
    if (!k) return false;
    if (k.status !== "done") { this._rnErr(new Error(`AI 키워드를 받지 못했습니다: ${k.error || k.status}`)); return false; }
    return true;
  },

  /* 작업 진행을 같은 창에 표시 → 끝난 작업 | null(창을 닫아 뒤에서 계속) */
  _rnWait(tid, label, bgOk) {
    const R = this._rn;
    R.task = tid; R.bg = false;
    App._rnQuiet = App._rnQuiet || new Set(); App._rnQuiet.add(tid);
    this._rnView(`<div class="form"><p><span class="spin"></span> <b>${esc(label)}</b></p>
        <div class="bar"><div class="bar-ok" id="rn-bar" style="width:0%"></div></div><p class="small muted" id="rn-prog">시작하는 중…</p>
        ${bgOk ? '<p class="small muted">오래 걸리면 창을 닫아도 됩니다 — 뒤에서 계속하고, 끝나면 알림에서 못 만든 것을 열어 처리합니다.</p>' : ""}</div>`,
    bgOk ? [{ label: "창 닫고 뒤에서 계속", noConfirm: true, onClick: () => { this._rnBackground(); App.closeModal(); return false; } }] : []);
    return this._rnPoll(tid);
  },
  async _rnPoll(tid, onTick) {
    const R = this._rn;
    for (;;) {
      if (R.bg || R.closed) return null;
      let t;
      try { t = (await App.api("/api/tasks")).find((x) => x.id === tid); } catch (e) { t = null; }
      if (R.bg || R.closed) return null;
      if (t) {
        const p = t.total ? Math.round((t.done / t.total) * 100) : null;
        const bar = $("#rn-bar"), pr = $("#rn-prog");
        if (bar && p != null) bar.style.width = `${p}%`;
        if (pr) pr.textContent = t.total ? `${num(t.done)} / ${num(t.total)} ${t.message || ""}` : (t.message || "진행 중…");
        if (onTick) onTick(t);
        if (t.status !== "running") { R.task = null; return t; }
      }
      await new Promise((ok) => setTimeout(ok, 700));
    }
  },
  _rnBackground() {
    const R = this._rn;
    if (!R || !R.task) return;
    R.bg = true;
    App._rnQuiet?.delete(R.task);
    App._rnBg = App._rnBg || new Map(); App._rnBg.set(R.task, { title: R.title, opt: { ...R.opt } });
    App.taskSeen[R.task] = "running";   // 끝나면 알림 (못 만든 것 — 열어서 처리)
    App.toast("상품명 바꾸기를 뒤에서 계속합니다. 끝나면 알림이 뜹니다.");
  },

  async _rnRename(target, opt) {
    const r = await App.api("/api/listings/rename", { json: { ...target, method: opt.method, redo: opt.redo, fixed_n: opt.fixed_n, extra: opt.extra,
      mark_mode: opt.mark_mode || undefined } });
    const t = await this._rnWait(r.task, "상품명 바꾸는 중", true);
    if (!t) return;
    if (t.status === "error") return this._rnErr(new Error(t.error || "상품명 바꾸기 실패"));
    this._rnResult(t.result || {});
  },

  /* 결과 화면: 바꾼 수 · 못 만든 것(원본별 까닭과 처리 버튼) */
  _rnResult(res) {
    const R = this._rn;
    R.res = res;
    R.rows = new Map();
    for (const s of res.fail?.sources || []) R.rows.set(s.source_id, { ...s, state: "open", made: [], note: "" });
    R.more = res.fail?.more || 0;
    R.renamed = res.renamed || 0;
    this._rnRender();
  },
  _rnRender() {
    const R = this._rn, res = R.res, rows = [...R.rows.values()];
    const open = rows.filter((x) => x.state === "open");
    const fixed = rows.reduce((a, x) => a + x.made.length, 0);
    const head = `<b>${num(R.renamed + fixed)}건 바꿈</b>` + (open.length ? ` · <span class="c-err">못 만든 ${num(open.reduce((a, x) => a + x.listings.length, 0))}건 (원본 ${num(open.length)}개)</span>` : "")
      + (res.live ? ` · 이미 올라간 ${num(res.live)}건은 건너뜀` : "") + (res.kept ? ` · 이미 이름이 붙은 ${num(res.kept)}건은 그대로` : "");
    const has = (f) => open.some(f);
    const markish = (x) => x.marks.length || x.kw_marks.length;
    const kwish = (x) => ["same_origin", "dup", "no_kw", "retry", "mark", "no_head", "repeat"].includes(x.key);
    const bulk = open.length > 1 ? `<div class="rn-bulk"><span class="small muted">못 만든 것 전부:</span>
        ${has(markish) ? '<button class="btn sm" data-all="allow">상표 무시하고 만들기</button>' : ""}
        ${has(kwish) ? '<button class="btn sm" data-all="again">AI 키워드 새로 받기</button>' : ""}
        <button class="btn sm" data-all="shuffle">셔플로 만들기</button><button class="btn sm" data-all="ai">AI로 짓기</button>
        <button class="btn sm ghost" data-all="skip">전부 건너뛰기</button></div>` : "";
    const row = (x) => {
      const st = x.state, stores = [...new Set(x.listings.map((l) => l.store))].join(", ");
      const acts = st !== "open" ? "" : `<div class="rn-acts">
          ${markish(x) ? `<button class="btn sm primary" data-act="allow">상표 무시하고 만들기</button><button class="btn sm" data-act="drop">상표 빼고 만들기</button>` : ""}
          ${x.key === "retry" ? '<button class="btn sm primary" data-act="retry">다시 만들기</button>' : ""}
          ${kwish(x) ? `<button class="btn sm ${markish(x) || x.key === "retry" ? "" : "primary"}" data-act="again">AI 키워드 새로 받기</button>` : ""}
          <button class="btn sm" data-act="shuffle">셔플로 만들기</button><button class="btn sm" data-act="ai">AI로 짓기</button>
          <button class="btn sm" data-act="manual">직접 입력</button><button class="btn sm ghost" data-act="skip">건너뛰기</button></div>
        <div class="rn-manual" hidden>${x.listings.map((l) => `<div class="cl-row"><span class="small muted" style="min-width:80px">${esc(l.store)}</span>
          <input class="rn-in" data-lid="${l.id}" value="${esc(l.name)}" style="flex:1;min-width:0"><button class="btn sm" data-save="${l.id}">저장</button></div>`).join("")}</div>`;
      const badge = st === "done" ? '<span class="flag eye-ok">바꿈</span>' : st === "skip" ? '<span class="flag">건너뜀</span>'
        : st === "wait" ? '<span class="flag">키워드 받는 중</span>' : st === "busy" ? '<span class="spin"></span>' : "";
      return `<div class="rn-src ${st}" data-sid="${x.source_id}">
        <div class="rn-h">${badge} <b>#${x.source_id}</b> ${esc(x.name)} <span class="muted small">· 복사본 ${num(x.listings.length)} · ${esc(stores)}</span></div>
        ${st === "open" || st === "busy" ? `<div class="small c-err rn-why">${esc(x.why)}</div>` : ""}
        ${x.made.length ? `<div class="small c-ok">→ ${x.made.map((m) => esc(m)).join(" / ")}</div>` : ""}
        ${x.note ? `<div class="small muted">${esc(x.note)}</div>` : ""}${acts}</div>`;
    };
    const allDone = !open.length;
    this._rnView(`<div class="form rn-res">
        <div class="notice ${allDone ? "ok" : "warn"}">${allDone ? "✓ " : ""}${head}${allDone && rows.length ? " — 모두 처리했습니다" : allDone ? " — 모두 바꿨습니다" : ""}</div>
        ${R.note ? `<p class="small muted">${esc(R.note)}</p>` : ""}
        <div id="rn-busy" class="small" hidden></div><div id="rn-cost"></div>
        ${bulk}
        ${rows.length ? `<div class="rn-list">${rows.map(row).join("")}</div>` : ""}
        ${R.more ? `<p class="small muted">못 만든 원본 ${num(R.more)}개는 목록에서 뺐습니다 — 처리한 뒤 다시 [상품명 바꾸기]를 누르면 이어서 보입니다.</p>` : ""}</div>`,
    [{ label: "닫기", noConfirm: true }]);
    const m = $("#m-body");
    $$("[data-act]", m).forEach((el) => el.addEventListener("click", () => this._rnAct([+el.closest(".rn-src").dataset.sid], el.dataset.act, el)));
    $$("[data-all]", m).forEach((el) => el.addEventListener("click", () => this._rnAct(open.map((x) => x.source_id), el.dataset.all, el)));
    $$("[data-save]", m).forEach((el) => el.addEventListener("click", () => this._rnSave(+el.dataset.save, el)));
  },

  async _rnAct(sids, act, btn) {
    const R = this._rn;
    const rows = sids.map((s) => R.rows.get(s)).filter((x) => x && x.state === "open");
    if (!rows.length) return;
    if (act === "skip") { rows.forEach((x) => { x.state = "skip"; }); return this._rnRender(); }
    if (act === "manual") { const box = $(".rn-manual", btn.closest(".rn-src")); box.hidden = !box.hidden; return; }
    if (act === "ai" && !btn.dataset.sure) {   // 비용 드는 것만 한 번 더
      btn.dataset.sure = "1"; btn.textContent = "AI 비용이 듭니다 — 한 번 더 눌러 실행"; btn.classList.add("danger"); return;
    }
    const lids = rows.flatMap((x) => x.listings.map((l) => l.id));
    if (act === "again") return this._rnAgain(rows, lids);
    const body = act === "allow" || act === "drop" || act === "retry" ? { method: "ctx", redo: false, mark_mode: act === "retry" ? undefined : act }
      : act === "shuffle" ? { method: "shuffle", fixed_n: +(App.state.settings.shuffle_fixed || 3), extra: "" } : { method: "ai" };
    await this._rnRun(rows, lids, body);
  },
  /* 고른 원본 복사본만 다시 이름 만들기 → 같은 창에서 결과 갱신 */
  async _rnRun(rows, lids, body) {
    const R = this._rn;
    rows.forEach((x) => { x.state = "busy"; });
    this._rnRender();
    const busy = $("#rn-busy");
    if (busy) { busy.hidden = false; busy.innerHTML = '<span class="spin"></span> 만드는 중… <span id="rn-prog"></span>'; }
    let t;
    try {
      const r = await App.api("/api/listings/rename", { json: { ids: lids, ...body } });
      R.task = r.task; R.bg = false;
      App._rnQuiet = App._rnQuiet || new Set(); App._rnQuiet.add(r.task);
      t = await this._rnPoll(r.task);
    } catch (e) { rows.forEach((x) => { x.state = "open"; }); App.toast(e.message, true); return this._rnRender(); }
    if (!t) return;
    if (t.status === "error") { rows.forEach((x) => { x.state = "open"; x.note = t.error; }); return this._rnRender(); }
    await this._rnRefresh(rows, lids, body.method);
  },
  /* 처리한 복사본의 지금 상태를 다시 읽어 줄마다: 이름이 붙었으면 '바꿈', 아니면 새 까닭 */
  async _rnRefresh(rows, lids, method) {
    const R = this._rn;
    let f;
    try { f = await App.api("/api/names/fail_list", { json: { ids: lids, method: method || "ctx" } }); } catch (e) { App.toast(e.message, true); return this._rnRender(); }
    const still = new Map((f.sources || []).map((s) => [s.source_id, s]));
    for (const x of rows) {
      const got = (f.done || []).filter((d) => d.source_id === x.source_id).map((d) => d.name);
      const s = still.get(x.source_id);
      x.made.push(...got.filter((n) => !x.made.includes(n)));
      if (s) { Object.assign(x, { why: s.why, key: s.key, marks: s.marks, kw_marks: s.kw_marks, listings: s.listings }); x.state = x.state === "wait" ? "wait" : "open"; }
      else if (x.state !== "wait") x.state = "done";
    }
    this._rnRender();
  },
  /* AI 키워드 새로 받기 (이 원본들만): 같은 창에 비용 안내 → 즉시면 받은 뒤 이름 붙이고 갱신, 일괄이면 받는 대로 자동 */
  async _rnAgain(rows, lids) {
    const box = $("#rn-cost");
    const t = { listing_filter: { ids: lids }, again: true };
    let eb, ei;
    try {
      [eb, ei] = await Promise.all([App.api("/api/ctx/estimate", { json: { ...t, mode: "batch" } }), App.api("/api/ctx/estimate", { json: { ...t, mode: "instant" } })]);
    } catch (e) { return App.toast(e.message, true); }
    box.innerHTML = `<div class="notice"><b>AI 키워드 새로 받기</b> — 원본 ${num(ei.sources)}개 (비용 듦)
        <div class="cl-row" style="margin-top:6px"><button class="btn sm primary" data-k="instant">즉시 받기 · 약 ${num(ei.krw)}원</button>
        <button class="btn sm" data-k="batch">일괄 받기 · 약 ${num(eb.krw)}원 (받으면 자동으로 붙음)</button><button class="btn sm ghost" data-k="no">취소</button></div></div>`;
    box.scrollIntoView({ block: "nearest" });
    $$("[data-k]", box).forEach((el) => el.addEventListener("click", async () => {
      const mode = el.dataset.k;
      if (mode === "no") { box.innerHTML = ""; return; }
      const R = this._rn;
      rows.forEach((x) => { x.state = "busy"; });
      this._rnRender();
      const busy = $("#rn-busy");
      if (busy) { busy.hidden = false; busy.innerHTML = `<span class="spin"></span> AI 키워드 ${mode === "instant" ? "받는 중" : "보내는 중"}… <span id="rn-prog"></span>`; }
      try {
        const r = await App.api("/api/ctx/start", { json: { ...t, mode } });
        if (mode === "instant" && r.task) {
          R.task = r.task; R.bg = false;
          App._rnQuiet = App._rnQuiet || new Set(); App._rnQuiet.add(r.task);
          const k = await this._rnPoll(r.task);
          if (!k) return;
          if (k.status !== "done") { rows.forEach((x) => { x.state = "open"; x.note = `AI 키워드를 받지 못함: ${k.error || k.status}`; }); return this._rnRender(); }
          return this._rnRun(rows, lids, { method: "ctx", redo: false });   // 새 키워드로 이름 붙이기
        }
        // 일괄: 보낸 뒤 이 복사본들은 키워드가 오면 자동으로 이름을 바꾸도록 걸어 둠
        const w = await App.api("/api/listings/rename", { json: { ids: lids, method: "ctx", redo: false } });
        R.task = w.task; App._rnQuiet = App._rnQuiet || new Set(); App._rnQuiet.add(w.task);
        await this._rnPoll(w.task);
        rows.forEach((x) => { x.state = "wait"; x.note = r.started ? "AI 키워드를 일괄로 보냄 — 받으면 이름이 자동으로 붙습니다" : (r.message || ""); });
        this._rnRender();
      } catch (e) { rows.forEach((x) => { x.state = "open"; }); App.toast(e.message, true); this._rnRender(); }
    }));
  },
  async _rnSave(lid, btn) {
    const R = this._rn;
    const inp = $(`.rn-in[data-lid="${lid}"]`);
    try {
      const r = await App.api(`/api/listings/${lid}/name`, { json: { name: inp.value } });
      const x = [...R.rows.values()].find((v) => v.listings.some((l) => l.id === lid));
      x.made.push(r.name);
      x.listings = x.listings.filter((l) => l.id !== lid);
      if (!x.listings.length) x.state = "done";
      this._rnRender();
    } catch (e) { App.toast(e.message, true); btn.disabled = false; }
  },
  /* 뒤에서 끝난 상품명 바꾸기의 알림에서: 같은 결과 창 다시 열기 */
  renameReopen(t, meta) {
    this._rn = { title: meta?.title || "상품명 바꾸기 · 결과", target: {}, n: 0, opt: meta?.opt || { method: "ctx" } };
    this._rnResult(t.result || {});
  },

  /* 네이버 상품 정보 바꾸기: 판매 중 복사본의 상세·브랜드·제조사·모델명만 (지우지 않음) */
  async infoPush() {
    const target = this.target();
    let p;
    try { p = await App.api("/api/listings/info_preview", { json: target }); } catch (e) { return App.toast(e.message, true); }
    if (!p.live) return App.toast("바꿀 판매 중 복사본이 없습니다 (아직 안 올린 것·내린 것·지금 등록 중인 것은 빠짐).", true);
    const rule = p.info_force ? "브랜드·제조사·모델명은 '상세페이지 참조'" : "브랜드·제조사·모델명은 원본 엑셀 값";
    App.ask({
      title: "네이버 상품 정보 바꾸기",
      body: `판매 중 복사본 <b>${num(p.live)}건</b>${p.locked ? ` (잠긴 ${num(p.locked)}건 포함 — 지우지 않으니까)` : ""}의 <b>상세·브랜드·제조사·모델명</b>을 지금 원본·설정 기준으로 네이버에서 바꿉니다 (${rule}).
        <br>지우지 않으므로 <b>상품번호·리뷰·판매 기록은 그대로</b>입니다. 실패한 것은 '네이버 반영 대기'로 남아 [네이버 반영 다시 시도]로 다시 보냅니다.`
        + (p.busy || p.other ? `<br><span class="muted small">빠짐: ${p.busy ? `지금 등록 중 ${num(p.busy)}건` : ""}${p.busy && p.other ? " · " : ""}${p.other ? `안 올린·내린 ${num(p.other)}건` : ""}</span>` : ""),
      label: "바꾸기", confirm: `판매 중 ${num(p.live)}건의 상세·브랜드·제조사·모델명을 네이버에서 바꿉니다 (상품번호 그대로).`,
      run: async () => {
        try {
          const r = await App.api("/api/listings/info_push", { json: target });
          if (r.detail_task) App.toast(`네이버 상품 정보 바꾸기 ${num(r.count)}건을 시작했습니다 (오른쪽 아래 진행).`);
          else App.toast(`${num(r.count)}건 — 지금 다른 네이버 반영이 돌고 있어 끝나는 대로 이어서 보냅니다.`);
          this.sel.clear(); this.selAll = false; this.load();
        } catch (e) { App.toast(e.message, true); return false; }
      },
    });
  },

  /* 최신화·내리기·다시 올리기: 늘 바로 — 다른 스토어가 돌고 있으면 함께, 이 스토어가 돌고 있으면 그 차례 뒤에 붙음 */
  schedule(op) {
    const name = OP[op];
    const label = {
      refresh: "<b>최신화</b>: 올린 지 오래된 판매 중 상품을 네이버에서 지우고 같은 이름으로 다시 올립니다",
      reupload: "<b>다시 올리기</b>: 문제가 있는 상품을 네이버에서 지우고 <b>같은 상품명·지금 가격</b>으로 다시 올립니다. <b>이미 내린(내림) 건은 지우는 단계 없이 다시 올립니다.</b> 스토어에서 이미 지운 상품이어도 됩니다",
      delete: "<b>내리기</b>: 판매 중인 상품을 네이버에서 지웁니다",
    }[op];
    const n = this.selAll ? this.total : this.sel.size;
    const go = async () => {
      try {
        const r = await App.api("/api/listings/schedule", { json: { ...this.target(), op } });
        const skip = r.skipped_sold ? ` 잠긴 ${num(r.skipped_sold)}건(판매 이력·직접 잠금)은 뺐습니다.` : "";
        if (!r.scheduled) App.toast((op === "reupload" ? "네이버에 올라가 있거나 내린 건이 없어 걸 일이 없습니다." : `네이버에 올라가 있는 건(판매 중·실패·대기)이 없어 걸 일이 없습니다.${op === "refresh" ? " 내린 건은 '다시 올리기'를 쓰세요." : ""}`) + skip, true);
        else if (r.started) {
          App.toast(`${num(r.scheduled)}건 ${name}를 시작했습니다` + (r.behind ? " — 이 스토어가 처리 중이라 그 차례 뒤에 붙였습니다." : r.joined ? " — 다른 스토어와 함께 처리합니다." : ".") + skip);
          App.run = await App.api("/api/run"); this.renderRun(App.run); App.renderSideRun();
        }
        else if (r.error) App.toast(`시작하지 못했습니다 (복사본에는 ${name} 할 일로 남음 — 다시 누르면 다시 시도): ${r.error}`, true);
        this.sel.clear(); this.selAll = false; this.estKey = "";
        this.load();
      } catch (e) { App.toast(e.message, true); }
    };
    App.openModal({
      title: `${num(n)}건 ${name}`,
      body: `<p>${label}.</p>
        <p class="muted small">잠긴 건(판매 이력·직접 잠금)은 빠지고, 판매 이력 확인(판매 현황 파일·확인 완료)이 유효 시간 안일 때만 지웁니다. 지난 회차 기록에 '${name}'로 남습니다.
          누르면 바로 시작합니다 — 다른 스토어가 등록 중이면 함께, 이 스토어가 처리 중이면 그 차례 뒤에 붙습니다.</p>
        ${op === "delete" ? "" : '<div class="notice" id="sch-nv">네이버 상태 확인 기록을 보는 중…</div>'}`,
      buttons: [{ label: "취소" }, { label: `${name} 시작`, primary: true, confirm: () => $("#sch-nv")?.innerText || "", onClick: () => go() }],
    });
    if (op !== "delete") App.nvNote($("#sch-nv"), this.target());
  },

  // ── 실행 패널

  /* 지금 보는 스토어가 실행에서 처리 중인가 (스토어를 안 골랐으면 실행 전체) */
  _mine(r) {
    if (!r?.running) return null;
    const sid = +this.f.store_id;
    if (!sid) return { all: true };
    return (r.stores || []).find((s) => s.id === sid && !["끝", "중단"].includes(s.status)) || null;
  },

  /* 다른 스토어 진행: 작은 한 줄 (누르면 그 스토어 화면) + 모든 스토어 일시정지·중단 */
  renderOthers(r) {
    const el = $("#l-run-others");
    if (!el) return;
    const sid = +this.f.store_id;
    const others = r?.running && sid ? (r.stores || []).filter((s) => s.id !== sid && !["끝", "중단"].includes(s.status)) : [];
    // 줄은 늘 같은 자리·같은 높이 (나타났다 사라지며 화면이 흔들리지 않게)
    el.hidden = !sid;
    if (!others.length) { el.innerHTML = '<span class="muted small">다른 스토어: 처리 중인 곳 없음</span>'; return; }
    el.innerHTML = `<span class="muted small">다른 스토어:</span> ${others.map((s) => `<button type="button" class="ro-chip" data-goto="${s.id}" title="${esc(s.name)} 화면으로">
        ${esc(s.name)} <b>${num(s.done)}/${num(s.total)}</b>${s.paused ? " · 일시정지" : s.status !== "처리 중" ? ` · ${esc(s.status)}` : ""}</button>`).join("")}
      <span class="ro-all"><button type="button" class="link-btn small" data-all="${r.paused ? "resume" : "pause"}">${r.paused ? "모든 스토어 계속" : "모든 스토어 일시정지"}</button>
      <button type="button" class="link-btn small c-err" data-all="stop">모든 스토어 중단</button></span>`;
    $$("[data-goto]", el).forEach((b) => b.addEventListener("click", () => App.go(`#listings?store_id=${b.dataset.goto}`)));
    $$("[data-all]", el).forEach((b) => b.addEventListener("click", async () => {
      const a = b.dataset.all;
      if (a === "stop" && !await App.yes("모든 스토어 중단", "모든 스토어의 등록·최신화·내리기를 중단합니다. 처리 중인 건까지만 마치고, 남은 건은 원래 상태(등록 대기·실패)로 돌아갑니다.", { label: "모두 중단", danger: true })) return;
      App.run = await App.api(`/api/run/${a}`, { json: {} }); this.renderRun(App.run); App.renderSideRun();
    }));
  },

  renderIdle() {
    const box = $("#l-run-main");
    if (!box) return;
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
      if (!this._mine(App.run) && $("#l-run")) this.renderIdle();
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
      if (App.run.behind) App.toast("이 스토어가 처리 중이라 그 차례 뒤에 붙였습니다.");
      else if (App.run.joined) App.toast("다른 스토어가 처리 중이라 함께 시작했습니다.");
      this.renderRun(App.run);
      App.renderSideRun();
    } catch (e) { App.toast(e.message, true); }
  },

  renderRun(r) {
    this.renderOthers(r);
    const mine = this._mine(r);
    if (!mine) {   // 이 스토어는 쉬는 중 → 시작 창 (시작이 곧 합류)
      if (this._live) { this._live = false; this.renderIdle(); }
      return;
    }
    const all = !!mine.all;
    const box = $("#l-run-main");
    if (!box) return;
    if (this._live !== (all ? "all" : mine.id)) {
      this._live = all ? "all" : mine.id;
      box.innerHTML = `<div class="run-top">
          <div class="run-count"><b id="r-done">0</b><span> / <span id="r-total">0</span></span></div>
          <div class="run-meta">
            <div><span class="muted">성공</span><b class="c-ok" id="r-ok">0</b></div>
            <div><span class="muted">실패</span><b class="c-err" id="r-fail">0</b></div>
            <div><span class="muted">잠금으로 건너뜀</span><b id="r-skip">0</b></div>
            ${all ? `<div><span class="muted">속도</span><b id="r-rate">-</b></div><div><span class="muted">남은 시간</span><b id="r-eta">-</b></div>` : ""}
          </div>
          <div class="run-ctl"><button class="btn" id="r-pause">일시정지</button><button class="btn danger" id="r-stop">중단</button></div>
        </div>
        <div class="bar"><div class="bar-ok" id="r-bar-ok"></div><div class="bar-err" id="r-bar-err"></div></div>
        <div class="run-state" id="r-state"></div>
        ${all ? '<div class="store-chips" id="r-stores"></div>' : ""}
        <ul class="current" id="r-current"></ul>
        <div class="run-foot"><button type="button" class="link-btn small" id="r-logbtn">자세히 · 작업 기록 보기 <span class="muted" id="r-logn"></span></button></div>`;
      // 작업 기록은 창으로 (상자 안에서 펼치면 높이가 바뀌어 화면이 흔들림)
      $("#r-logbtn").addEventListener("click", () => {
        const m = this._mine(App.run);
        App.openModal({ title: `작업 기록${m && !m.all ? ` · ${m.name}` : ""}`, wide: true,
          body: '<div class="log"><ol id="r-log"></ol></div>', buttons: [{ label: "닫기" }] });
        this.renderLog(App.run, m && !m.all ? m.name : null);
      });
      const body = () => (this._mine(App.run)?.all ? {} : { store_id: +this.f.store_id });
      $("#r-pause").addEventListener("click", async () => {
        const m = this._mine(App.run);
        const paused = m?.all ? App.run?.paused : m?.paused;
        App.run = await App.api(`/api/run/${paused ? "resume" : "pause"}`, { json: body() }); this.renderRun(App.run); App.renderSideRun();
      });
      $("#r-stop").addEventListener("click", async () => {
        const m = this._mine(App.run);
        const what = m?.all ? "모든 스토어" : `이 스토어(${m?.name || ""})`;
        if (!await App.yes(`${what} 중단`, `${what}의 등록·최신화·내리기를 중단할까요? 처리 중인 건까지만 마치고 멈춥니다. 남은 건은 원래 상태(등록 대기·실패)로 돌아갑니다.${m?.all ? "" : " 다른 스토어는 계속합니다."}`, { label: "중단", danger: true })) return;
        App.run = await App.api("/api/run/stop", { json: body() }); this.renderRun(App.run); App.renderSideRun();
      });
      clearInterval(this.timer);
      this.timer = setInterval(() => { if (App.run?.running && !App.userBusy()) this.load(); }, 4000);
    }
    const m = all ? r : mine;
    const paused = all ? r.paused : mine.paused || r.paused;
    const stopping = all ? r.stopping : mine.stopping || r.stopping;
    $("#r-done").textContent = num(m.done);
    $("#r-total").textContent = num(m.total);
    $("#r-ok").textContent = num(m.ok);
    $("#r-fail").textContent = num(m.fail);
    $("#r-skip").textContent = num(m.skipped || 0);
    if (all) {
      $("#r-rate").textContent = r.rate_per_min ? `분당 ${num(Math.round(r.rate_per_min))}건` : "재는 중";
      $("#r-eta").textContent = r.paused ? "일시정지" : r.eta != null ? dur(r.eta) : "재는 중";
    }
    $("#r-bar-ok").style.width = (m.total ? (m.ok / m.total) * 100 : 0) + "%";
    $("#r-bar-err").style.width = (m.total ? (m.fail / m.total) * 100 : 0) + "%";
    $("#r-pause").textContent = paused ? "▶ 계속" : all ? "모두 일시정지" : "이 스토어 일시정지";
    $("#r-stop").textContent = all ? "모두 중단" : "이 스토어 중단";
    $("#r-pause").disabled = $("#r-stop").disabled = !!stopping;
    $("#r-state").textContent = stopping ? "중단하는 중… 처리 중인 건까지만 마칩니다."
      : paused ? "일시정지됨" : all ? `처리 중 · ${dur(r.elapsed)} 지남` : `이 스토어: ${mine.status}`;
    if (all) {
      $("#r-stores").innerHTML = r.stores.map((s) => `<div class="chip-store ${s.status === "처리 중" ? "on" : s.status === "끝" ? "done" : ""}" title="${esc(s.name)}: ${s.status}">
        <div class="cs-top"><span>${esc(s.name)}</span><span>${num(s.done)}/${num(s.total)}</span></div>
        <div class="bar thin"><div class="bar-ok" style="width:${s.total ? (s.ok / s.total) * 100 : 0}%"></div>
        <div class="bar-err" style="width:${s.total ? (s.fail / s.total) * 100 : 0}%"></div></div></div>`).join("");
    }
    const pre = all ? "" : `[${mine.name}]`;
    const cur = r.current.filter((c) => !pre || String(c.name).startsWith(pre));
    $("#r-current").innerHTML = cur.slice(0, 8).map((c) =>
      `<li><span class="spin"></span><span class="c-name">${esc(all ? c.name : String(c.name).slice(pre.length).trim())}</span><span class="c-stage">${esc(c.stage)}</span></li>`).join("")
      + (cur.length > 8 ? `<li class="muted small">외 ${cur.length - 8}건 처리 중</li>` : "");
    this.renderLog(r, all ? null : mine.name);
  },

  renderLog(r, store) {
    if (!r) return;
    const log = store ? r.log.filter((l) => !l.store || l.store === store) : r.log;
    const n = $("#r-logn");
    if (n) n.textContent = log.length ? `(${log.length})` : "";
    const ol = $("#r-log");
    if (!ol) return;
    ol.innerHTML = log.slice().reverse().map((l) => `<li class="l-${l.level}"><time>${new Date(l.t * 1000)
      .toLocaleTimeString("ko-KR", { hour12: false })}</time>${l.store ? `<span class="muted">${esc(l.store)}</span>` : ""}<span>${esc(l.msg)}</span></li>`).join("");
  },

  clearSel() { this.sel.clear(); this.selAll = false; },

  bind() {
    $("#l-sales")?.addEventListener("click", () => { if (this.f.store_id) App.salesConfirm(+this.f.store_id, () => this.load()); });
    $("#l-custom-new")?.addEventListener("click", () => App.customEdit({ storeId: +this.f.store_id }, () => { this._custOn = false; this.load(); }));
    $("#l-tiles").addEventListener("click", (e) => {
      const t = e.target.closest("[data-filter]");
      if (!t) return;
      const k = t.dataset.filter;
      this.f.nv = "";
      if (k.startsWith("eye_")) { this.f.eye = k.slice(4); this.f.status = "all"; }
      else if (k === "nv_bad") { this.f.nv = "bad"; this.f.status = "all"; this.f.eye = ""; }
      else { this.f.status = k; this.f.eye = ""; }
      this._custOn = false;
      this.page = 0; this.clearSel(); this.load();
    });
    onTyped($("#l-q"), (v) => { if (v.trim() === (this.f.q || "")) return; this.f.q = v.trim(); this.page = 0; this.clearSel(); this.load(); });
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
                <div><b>${l.name_id ? "바꾼 상품명" : "이름 변경 필요 — 후보상품명이 없어 올리지 않습니다"}</b></div>
                <div class="add-name"><input id="d-name" value="${esc(l.name)}" maxlength="100"><button class="btn primary" id="d-name-save">이 이름으로</button></div>
                <span class="muted small">직접 고쳐 저장하거나 <button class="link-btn" id="d-rename">상품명 바꾸기</button>(AI 키워드·AI로 짓기·셔플). 금지어·상표·33개 스토어 중복을 검사합니다.</span></div>` : ""}
              <dl class="kv"><dt>스토어</dt><dd>${esc(l.store_name)}</dd>
              <dt>등록 상품명</dt><dd>${l.name_id ? nameDiff(l.nd) + ND_LEGEND : `${esc(l.name)} <span class="flag bad">후보상품명 없음</span>`}</dd>
              <dt>업스타 기준상품명</dt><dd>${esc(l.source_name)} <button class="btn sm" id="d-src">원본 보기</button></dd>
              <dt>판매자 관리코드</dt><dd>${esc(l.seller_code || l.next_seller_code)} <span class="muted">(${l.round}회차${l.seller_code ? "" : ", 등록하면 붙음"})</span></dd>
              <dt>원본 번호</dt><dd>#${l.source_id}</dd>
              <dt>카테고리</dt><dd>${esc(l.category)}${l.category_fixed ? ` <span class="flag">직접 정함</span> <span class="muted small">(엑셀: ${esc(l.category_excel)})</span>` : ""}
                <button class="btn sm d-cat">바꾸기</button></dd>
              <dt>손님 가격</dt><dd>손님 가격 <b>${num(l.final)}원</b> <span class="muted">(기준 가격 ${num(l.source_price)}원)</span> <button class="btn sm" id="d-price" type="button">가격 수정</button>
                <button class="btn sm" id="d-custom" type="button" title="이 복사본 내용으로 고객 맞춤 상품(대량 할인·다른 출고지 등)을 따로 만들기 — 복사 수에 안 들어감">고객 맞춤 상품 만들기</button>
                ${l.off ? `<br><span class="muted">네이버 판매가 ${num(l.shown)}원 · 즉시할인 ${num(l.off)}원 (할인율 ${(l.off / l.shown * 100).toFixed(1)}% — 손님 가격을 그대로 두고 ${l.disc_pct}%에 가깝게)</span>` : ""}
</dd>
              <dt>다른 스토어</dt><dd>${l.siblings.length ? l.siblings.map((x) => `<div><button class="go-store" data-go="${x.id}">→ ${esc(x.store_name)}</button> ${esc(x.name)} <span class="muted">(${STATUS[x.status] || x.status})</span></div>`).join("") : "같은 원본이 다른 스토어에는 없음"}</dd></dl>`
            + `<div class="notice ${l.locked ? "info" : ""} lock-box"><div><b>${l.locked ? "잠금" : "잠금 아님"}</b>${l.locked ? ` · ${esc(l.lock_note)} · 최신화·내리기로 지우지 않습니다` : " · 최신화·내리기 가능"}
                ${l.cancel_count ? `<br><span class="muted">취소·반품 ${num(l.cancel_count)}개는 판매로 세지 않음 (설정에서 바꿈)</span>` : ""}</div>
                <div class="cl-row"><button class="btn" id="d-lock">${l.manual_lock ? "직접 잠금 풀기" : "직접 잠금"}</button>
                ${l.orders.some((o) => !o.ignored) && (l.sold_count || l.cancel_count) ? '<button class="btn danger" id="d-ignore" title="잘못 넣은 판매 이력이면: 이 복사본에 맞춘 주문을 무시해 판매 수·잠금에서 뺌 (되돌릴 수 있음)">판매 이력 무시하고 잠금 풀기</button>' : ""}
                ${l.orders.some((o) => o.ignored) ? '<button class="btn" id="d-unignore" title="무시한 주문을 다시 판매 이력으로 셈">판매 이력 무시 풀기</button>' : ""}</div></div>`
            + (l.orders.length ? `<div><h3 class="sec-title">주문 (판매 ${num(l.sold_count)}개${l.cancel_count ? ` · 취소·반품 ${num(l.cancel_count)}개` : ""})</h3><table class="opt-table"><tr><th>주문</th><th>수량</th><th>결제일</th><th>가져온 곳</th></tr>
              ${l.orders.map((o) => `<tr${o.ignored ? ' style="opacity:.55"' : ""}><td>${esc(o.order_key.replace(/^file:/, ""))}<div class="p-sub">${esc(o.status)}${o.ignored ? " · 무시함" : ""}</div></td><td>${num(o.quantity)}</td><td>${ymd(o.ordered_at)}</td>
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
          $("#d-custom", b)?.addEventListener("click", () => { App.closeDrawer(); App.customEdit({ listingId: id, storeId: l.store_id }, () => { this._custOn = false; if ($("#l-rows")) this.load(); }); });
          $("#d-price", b)?.addEventListener("click", () => App.priceEdit({ level: "listing", target: { ids: [id] }, n: 1, what: `이 복사본 (${l.store_name || ""})`,
            after: () => { if ($("#l-rows")) this.load(); this.openListing(id); } }));
          $("#d-lock", b)?.addEventListener("click", async () => {
            const r = await this.lock(!l.manual_lock, [id]);
            if (r) { if ($("#l-rows")) this.load(); this.openListing(id); }
          });
          $("#d-ignore", b)?.addEventListener("click", () => this.ignoreOrders(id, true, l));
          $("#d-unignore", b)?.addEventListener("click", () => this.ignoreOrders(id, false, l));
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
      foot: ["planned", "fail"].includes(l.status)
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
