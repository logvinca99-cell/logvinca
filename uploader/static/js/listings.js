/* 등록: 계획된 건 목록, 등록 실행(여러 스토어 동시), 진행 상황 */
"use strict";

const RUN_KINDS = [["create", "등록"], ["refresh", "최신화"], ["reupload", "다시 올리기"], ["delete", "내리기"], ["fail", "실패 재시도"]];

const LST_TILES = [
  { key: "all", label: "전체", dot: "var(--text-2)", count: "all_" },
  { key: "noname", label: "상품명 변경 필요", dot: "var(--err)" },
  { key: "named", label: "올릴 준비 (이름 바꿈·안 올림)", dot: "var(--info)" },
  { key: "live", label: "판매 중", dot: "var(--ok)" },
  { key: "fail", label: "실패", dot: "var(--err)" },
  { key: "sold", label: "판매 이력 있음", dot: "var(--warn)" },
  { key: "locked", label: "잠금", dot: "var(--info)" },
  { key: "bait", label: "도둑방지 가격", dot: "var(--err)" },
  { key: "deleted", label: "내림", dot: "var(--dup)" },
];

App.page("listings", {
  async mount(el, params) {
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
          <a class="btn ghost" id="l-export">결과 CSV</a>
          <label class="btn" title="아바닛 등 주문 수집 웹에서 내려받은 주문 파일"><input type="file" id="l-sales-file" accept=".xlsx,.xlsm,.csv" hidden>판매 이력 파일 가져오기</label>
          <a class="btn" href="#orders" title="판매자센터 주문을 가져오고 기간·스토어별로 보기">판매 현황</a>
        </div></header>
      <div class="card run" id="l-run"></div>
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
          <th class="w-links">바로 가기</th><th class="w-round">관리코드 · 올린 날</th><th class="w-num">판매가</th><th class="w-status">상태</th></tr></thead><tbody id="l-rows"></tbody></table>
        <div class="pg-foot"><div class="pg" id="l-pager"></div></div>
      </div>
    </div>`;
    $("#l-store").value = String(params.store_id);
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
          ${big(s.p_create - s.noname > 0 ? s.p_create - s.noname : 0, "올릴 준비 됨", "ready")}
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
    $("#l-tiles").innerHTML = tilesHtml(LST_TILES, { ...this.counts, all: this.counts.all_ }, this.f.status);
    $("#l-rows").innerHTML = res.rows.length ? res.rows.map((l) => this.rowHtml(l)).join("")
      : `<tr class="empty-row"><td colspan="7">${this.counts.all_ ? "조건에 맞는 건이 없습니다."
        : '이 스토어에 복사본이 없습니다. <a href="#inventory">원본 상품</a>에서 원본을 고르고 <b>다른 스토어로 복사</b>를 누르세요.'}</td></tr>`;
    $("#l-export").href = `/api/listings/export.csv?${new URLSearchParams(this.query())}`;
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
        "|",
        { id: "remove", label: "삭제", danger: true, title: "아직 안 올린 복사본·내린 복사본을 휴지통으로 (네이버에 올라간 것은 먼저 내리기)" },
        ...(this.f.status === "bait" ? ["|", { id: "restore", label: "원래 가격으로", primary: true }] : []),
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
    if (id === "refresh" || id === "delete" || id === "reupload") this.schedule(id);
    if (id === "lock" || id === "unlock") this.lock(id === "lock");
    if (id === "remove") {
      const n = this.selAll ? this.total : this.sel.size;
      const ok = await App.confirmDanger({
        title: `복사본 ${num(n)}건 삭제`,
        body: `<p>고른 복사본 <b>${num(n)}건</b>을 <b>휴지통</b>으로 옮깁니다. 붙어 있던 상품명은 원본의 안 쓴 후보로 돌아갑니다.</p>
          <p class="muted small">네이버에 올라가 있거나 처리 중인 복사본은 지우지 않습니다(먼저 '내리기 예약'으로 내리세요). 휴지통에서 되살릴 수 있습니다.</p>`,
      });
      if (!ok) return;
      try {
        const r = await App.api("/api/listings/delete", { json: this.target() });
        App.toast(`복사본 ${num(r.moved)}건을 휴지통으로 옮겼습니다` + (r.skipped_live ? ` · 네이버에 올라가 있거나 처리 중이라 뺀 ${num(r.skipped_live)}건` : ""));
        this.clearSel(); this.estKey = ""; this.load(); App.refreshState();
      } catch (err) { App.toast(err.message, true); }
    }
    if (id === "restore") App.startTask(App.api("/api/bait/restore", { json: this.selAll ? { filter: this.query() } : { ids: [...this.sel] } }));
    if (id === "cancel") {
      if (!confirm("고른 건 중 대기·실패 할 일을 취소할까요?\n새 등록이면 계획을 지우고 이름을 후보로 돌립니다. 최신화·내리기면 판매 중으로 되돌립니다.")) return;
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
      + (l.name_origin ? `<span class="org org-${l.name_origin}" title="${l.name_origin === "ctx" ? "AI 키워드로 만든 이름 후보 중 이 원본의 몇 번째인지 (원본 상품 화면에서 A·B 전체를 볼 수 있음)" : ""}">${l.name_origin === "ctx" && l.ai_rank != null ? `AI 이름 ${String.fromCharCode(65 + Math.min(25, l.ai_rank))}` : ORIGIN[l.name_origin] || l.name_origin}</span>` : "") + lockFlag(l) + salesFlag(l);
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
          <label><input type="radio" name="rn" value="ctx" checked><div><b>AI 키워드 (기본)</b><span class="muted small">[원본 앞 ${num(s.ctx_head_n)}단어] + 원본 핵심 단어(keep) + 다른 이름(core) 전부 + 용도·조합(core2) 2개 + 맥락 + 남은 원본 단어 + 나머지 core2, 최대 ${num(s.name_max_len)}자. 키워드가 없는 원본은 먼저 받습니다(비용 안내 후).</span></div></label>
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
              const h = (t) => { if (t.kind === "ctxkw") { App.off("task-done", h); go(); } };
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
          <div id="l-est" class="muted small">${est.seconds && n ? `예상 <b>약 ${dur(est.seconds)}</b> · 스토어마다 ${est.workers}건씩 동시에 · ${esc(est.basis)}` : range === "sel" && !nSel ? "목록에서 복사본을 고르세요." : ""}</div></div>
      </div>`;
    $("#l-start").addEventListener("click", () => this.start());
    $("#l-one").addEventListener("click", () => this.start(1));
    $("#l-noname")?.addEventListener("click", (e) => { e.preventDefault(); this.f.status = "noname"; this.page = 0; this.clearSel(); this.load(); });
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

  async start(limit) {
    const scope = this.runScope();
    const n = limit || this.est?.count || 0;
    const what = RUN_KINDS.filter(([k]) => scope.kinds.includes(k)).map(([k, l]) => `${l} ${num(this.est?.kinds?.[k] || 0)}`).join(" · ");
    const where = { store: "이 스토어 전체", sel: "고른 복사본", visible: "지금 보이는 조건" }[this.runRange || "store"];
    if (!limit && !confirm(`${where}에서 ${num(n)}건을 처리합니다.\n(${what})\n계속할까요?`)) return;
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
        if (!confirm("등록을 중단할까요? 처리 중인 건까지만 마치고 멈춥니다. 남은 건은 대기로 돌아갑니다.")) return;
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
      if (t) { this.f.status = t.dataset.filter; this.page = 0; this.clearSel(); this.load(); }
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
          b.innerHTML = (l.status === "fail" ? `<div class="notice err"><b>${esc(statusLabel(l.status, l.op))}</b><br>${esc(l.message)}</div>` : "")
            + (l.origin_no ? `<div class="notice ok"><b>판매 중</b> · 상품번호 ${esc(l.channel_no)} · ${ymd(l.registered_at)}에 올림 (${age(l.registered_at)})<br>
                ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">스토어에서 보기</a> · ` : ""}
                <a href="https://sell.smartstore.naver.com/#/products/edit/${esc(l.origin_no)}" target="_blank" rel="noopener">스마트스토어센터에서 수정</a></div>` : "")
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
              <dt>판매가</dt><dd>손님 가격 <b>${num(l.final)}원</b> <span class="muted">(원본가 ${num(l.source_price)}원)</span>
                ${l.off ? `<br><span class="muted">네이버 판매가 ${num(l.shown)}원 · 즉시할인 ${num(l.off)}원 (${l.disc_pct}%)</span>` : ""}
                ${l.bait_state === "on" ? `<br><span class="flag bad">도둑방지 중</span> 네이버에는 <b>${num(l.price + l.bait)}원</b> <button class="btn" id="d-restore">원래 가격으로</button>` : ""}
                ${!l.origin_no && l.status !== "deleted" ? `<br><span class="muted">${l.bait_want && App.state.settings.bait_default ? `도둑방지로 올림 (+${num(App.state.settings.bait_amount)}원, 처음 등록일 때)` : "도둑방지 없이 올림"}</span>` : ""}
                ${l.bait_state === "restored" ? `<br><span class="muted">도둑방지 끝 · ${ymd(l.bait_restored_at)} 원래 가격으로 (${esc(l.bait_note)})</span>` : ""}
                ${l.bait_state === "fail" ? `<br><span class="flag bad">${esc(l.bait_note)}</span>` : ""}</dd>
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
          $("#d-rename", b)?.addEventListener("click", () => this.renameModal([id]));
          $$("[data-go]", b).forEach((x) => x.addEventListener("click", () => { App.closeDrawer(); this.goto(+x.dataset.go); }));
          $("#d-restore", b)?.addEventListener("click", async () => {
            const r = await App.startTask(App.api("/api/bait/restore", { json: { ids: [id] } }));
            if (r) App.on("task-done", function h(t) { if (t.kind === "bait") { App.off("task-done", h); App.pages.listings.openListing(id); } });
          });
          $("#d-lock", b)?.addEventListener("click", async () => {
            const r = await this.lock(!l.manual_lock, [id]);
            if (r) { if ($("#l-rows")) this.load(); this.openListing(id); }
          });
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
      try {
        App.run = await App.api("/api/run", { json: { ids: [id] } }); App.closeDrawer();
        if ($("#l-run")) this.renderRun(App.run); else App.renderSideRun();
      }
      catch (e) { App.toast(e.message, true); }
    });
  },
});
