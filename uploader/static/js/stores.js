/* 스토어: 추가·수정, 여러 개 한 번에 추가, 연결 확인(네이버 상품 수), 사용량 */
"use strict";

const ADDR_TYPE = { RELEASE: "출고지", REFUND_OR_EXCHANGE: "반품·교환지", GENERAL: "일반" };

App.page("stores", {
  async mount(el) {
    try { this.closed = new Set(JSON.parse(localStorage.getItem("biz-closed") || "[]")); } catch (e) { this.closed = new Set(); }
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>스토어</h1>
        <div class="head-actions">
          <button class="btn" id="s-test-all">모두 연결 확인</button>
          <button class="btn" id="s-bulk">여러 개 한 번에 추가</button>
          <button class="btn" id="s-biz-add">사업자 추가</button>
          <button class="btn primary" id="s-add">스토어 추가</button>
        </div></header>
      <div class="st-summary" id="s-sum"></div>
      <p class="muted small" style="margin:0">⠿ 손잡이를 꾹 눌러 끌면 사업자·스토어 순서를 바꿉니다. 스토어를 다른 사업자 칸으로 끌어 옮길 수도 있습니다(사업자 하나에 최대 3개).
        이 순서가 복사·복사본 화면에도 그대로 쓰입니다. 사업자 이름을 누르면 접고 펼칩니다.</p>
      <div id="s-groups" class="biz-groups"></div>
    </div>`;
    $("#s-add").addEventListener("click", () => this.edit({ capacity: 10000, enabled: 1 }));
    $("#s-biz-add").addEventListener("click", () => this.editBiz({}));
    $("#s-bulk").addEventListener("click", () => this.bulk());
    $("#s-test-all").addEventListener("click", () => this.testAll());
    const box = $("#s-groups");
    box.addEventListener("click", (e) => this.onClick(e));
    this.bindDrag(box);
    await this.load();
  },

  saveClosed() { try { localStorage.setItem("biz-closed", JSON.stringify([...this.closed])); } catch (e) { /* 무시 */ } },

  async load() {
    const [stores, biz] = await Promise.all([App.loadStores(), App.api("/api/businesses")]);
    this.rows = stores;
    this.biz = biz;
    this.groups = [...biz.map((b) => ({ ...b, stores: stores.filter((s) => s.business_id === b.id) })),
      { id: "none", name: "사업자 없음", none: true, stores: stores.filter((s) => !s.business_id || !biz.some((b) => b.id === s.business_id)) }]
      .filter((g) => !g.none || g.stores.length);
    this.render();
  },

  render() {
    const all = this.rows;
    const tot = (k) => all.reduce((a, s) => a + (s[k] || 0), 0);
    $("#s-sum").innerHTML = `<div><span>사업자</span><b>${num(this.biz.length)}</b></div><div><span>스토어</span><b>${num(all.length)}</b></div>
      <div><span>판매 중·고구마 포함 사용량</span><b>${num(tot("used"))}</b></div><div><span>남은 자리 합계</span><b>${num(tot("free"))}</b></div>
      <div><span>실패</span><b class="${tot("n_fail") ? "c-err" : ""}">${num(tot("n_fail"))}</b></div>`;
    $("#s-groups").innerHTML = this.groups.length ? this.groups.map((g) => {
      const open = !this.closed.has(String(g.id));
      const used = g.stores.reduce((a, s) => a + s.used, 0), cap = g.stores.reduce((a, s) => a + s.capacity, 0);
      return `<section class="biz ${open ? "open" : ""}" data-biz="${g.id}" ${g.none ? "" : `data-drag="biz"`}>
        <div class="biz-head">
          ${g.none ? `<span class="grip off"></span>` : `<span class="grip" title="끌어서 순서 바꾸기">⠿</span>`}
          <button class="biz-name" data-toggle="${g.id}"><span class="biz-caret">${open ? "▾" : "▸"}</span>${esc(g.name)}</button>
          ${g.reg_no ? `<span class="muted small">${esc(g.reg_no)}</span>` : ""}
          <span class="pill ${g.stores.length >= 3 ? "full" : ""}">스토어 ${g.stores.length}${g.none ? "" : " / 3"}</span>
          <span class="biz-use">${cap ? `사용 ${num(used)} / ${num(cap)}` : ""}</span>
          <span class="spacer"></span>
          ${g.none ? "" : `${g.stores.length < 3 ? `<button class="btn sm" data-badd="${g.id}">+ 스토어</button>` : ""}<button class="btn sm ghost" data-bedit="${g.id}">사업자 수정</button>`}
        </div>
        ${open ? `<div class="biz-body" data-drop="${g.id}">${g.stores.map((s) => this.rowHtml(s)).join("")
          || `<div class="st-empty">스토어를 여기로 끌어 오거나 '+ 스토어'를 누르세요.</div>`}</div>` : ""}
      </section>`;
    }).join("") : `<div class="card pad"><p class="muted">아직 사업자·스토어가 없습니다. <b>사업자 추가</b>로 사업자를 만들고 그 안에 스토어를 추가하세요.</p></div>`;
  },

  rowHtml(s) {
    const line = naverStatusLine(s);
    return `<div class="st-card ${s.enabled ? "" : "off"} ${regionCls(s)}" data-store="${s.id}" data-drag="store">
      <div class="st-card-head"><span class="grip" title="끌어서 순서 바꾸기·다른 사업자로 옮기기">⠿</span>
        <span class="code">${esc(s.code)}</span><b>${esc(s.name)}</b>
        ${s.enabled ? "" : '<span class="flag">사용 안 함</span>'}${s.has_keys ? "" : '<span class="flag warn">키 없음</span>'}
        <span class="region-pick" title="지금 이 스토어 출고 형태 (표시만, 누른 것을 다시 누르면 지움)">${Object.entries(REGION).map(([k, l]) =>
          `<button class="${s.ship_region === k ? "on" : ""}" data-act="region" data-v="${k}" data-id="${s.id}">${l}</button>`).join("")}</span></div>
      ${storeUsage(s, true)}
      <div class="st-meta">${s.naver_count_at ? `연결 확인 ${when(s.naver_count_at)}${line ? `<br>${esc(line)}` : ""}` : '<span class="c-warn">연결 확인 전 (사용량이 정확하지 않음)</span>'}</div>
      <div class="st-meta">실패 <b class="${s.n_fail ? "c-err" : ""}">${num(s.n_fail)}</b> · 판매 이력 <b>${num(s.n_sold)}</b> · 내림 ${num(s.n_deleted)}${s.n_locked ? ` · 잠금 ${num(s.n_locked)}` : ""}
        · <a href="#listings?store_id=${s.id}">복사본 보기</a></div>
      ${storeLinks(s)}
      <div class="store-acts"><button class="btn sm" data-act="edit" data-id="${s.id}">수정</button>
        <button class="btn sm" data-act="tpl" data-id="${s.id}">템플릿</button>
        <button class="btn sm" data-act="test" data-id="${s.id}">연결 확인</button>
        <button class="btn sm" data-act="refresh" data-id="${s.id}" ${s.n_live ? "" : "disabled"}>최신화</button></div>
    </div>`;
  },

  async onClick(e) {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.act) {
      const s = this.rows.find((x) => x.id === +b.dataset.id);
      if (b.dataset.act === "edit") this.edit(s);
      if (b.dataset.act === "tpl") this.template(s);
      if (b.dataset.act === "test") this.test(s, b);
      if (b.dataset.act === "refresh") this.refresh(s);
      if (b.dataset.act === "region") {
        try {
          const v = s.ship_region === b.dataset.v ? "" : b.dataset.v;
          Object.assign(s, await App.api(`/api/stores/${s.id}/region`, { json: { region: v } }));
          b.closest(".st-card").outerHTML = this.rowHtml(s);
          App.loadStores();
        } catch (err) { App.toast(err.message, true); }
      }
      return;
    }
    if (b.dataset.goguma) return this.goguma(this.rows.find((x) => x.id === +b.dataset.goguma));
    if (b.dataset.bedit) return this.editBiz(this.biz.find((x) => x.id === +b.dataset.bedit));
    if (b.dataset.badd) return this.edit({ capacity: 10000, enabled: 1, business_id: +b.dataset.badd });
    if (b.dataset.toggle) {
      const k = b.dataset.toggle;
      this.closed.has(k) ? this.closed.delete(k) : this.closed.add(k);
      this.saveClosed(); this.render();
    }
  },

  /* 고구마(전시중지) 상품 수: 직접 넣거나, 비우면 연결 확인 때 받은 수 */
  goguma(s) {
    App.openModal({
      title: `${s.name} · 고구마 상품 수`,
      body: `<div class="form"><p class="muted small" style="margin:0">전시중지한 상품(고구마)도 스토어 한도를 차지합니다. 연결 확인 때 네이버에서
          전시중지 상품 수를 받아 자동으로 넣습니다${s.naver_suspended != null ? ` (지난 확인: <b>${num(s.naver_suspended)}개</b>, 그 외 ${num(s.naver_sale)}개)` : " (아직 확인 전)"}.
          다르면 직접 넣으세요. 비우면 자동 값으로 돌아갑니다.</p>${(() => { let st = {}; try { st = JSON.parse(s.naver_status || "{}"); } catch (e) { /* 없음 */ }
          return st._keys ? `<p class="c-warn small" style="margin:0">지난 연결 확인에서 네이버가 전시 상태를 보내지 않았습니다. 아래 줄을 그대로 보내 주시면 고치겠습니다.<br>
            <code class="keys">${esc(st._keys.join(", "))}</code></p>` : ""; })()}
        <label class="field">고구마 상품 수<input type="number" id="g-n" min="0" value="${s.goguma_manual ?? ""}" placeholder="자동 (${num(s.naver_suspended || 0)})" autofocus></label></div>`,
      buttons: [{ label: "취소" }, { label: "저장", primary: true, onClick: async (m) => {
        try { await App.api(`/api/stores/${s.id}/goguma`, { json: { count: $("#g-n", m).value } }); await this.load(); App.refreshState(); }
        catch (err) { App.toast(err.message, true); return false; }
      } }],
    });
  },

  /* 끌어서 옮기기: ⠿를 눌렀을 때만 끌 수 있음. 사업자끼리 / 스토어끼리(다른 사업자 칸으로도) */
  bindDrag(box) {
    let drag = null;
    box.addEventListener("mousedown", (e) => {
      const g = e.target.closest(".grip");
      if (!g || g.classList.contains("off")) return;
      const item = g.closest("[data-drag]");
      if (item) item.draggable = true;
    });
    box.addEventListener("dragstart", (e) => {
      const item = e.target.closest?.("[data-drag]");
      if (!item || !item.draggable) return;
      drag = { type: item.dataset.drag, el: item, id: item.dataset.drag === "biz" ? +item.dataset.biz : +item.dataset.store };
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(drag.id));
      setTimeout(() => item.classList.add("dragging"), 0);
    });
    const clearMarks = () => $$(".drop-before,.drop-after,.drop-into", box).forEach((x) => x.classList.remove("drop-before", "drop-after", "drop-into"));
    box.addEventListener("dragend", () => {
      $$("[data-drag]", box).forEach((x) => { x.draggable = false; x.classList.remove("dragging"); });
      clearMarks(); drag = null;
    });
    const target = (e) => {
      if (!drag) return null;
      if (drag.type === "biz") {
        const t = e.target.closest("[data-drag=biz]");
        if (!t || t === drag.el) return null;
        const r = t.getBoundingClientRect();
        return { el: t, pos: e.clientY < r.top + r.height / 2 ? "before" : "after" };
      }
      const row = e.target.closest("[data-drag=store]");
      if (row && row !== drag.el) {
        const r = row.getBoundingClientRect();
        return { el: row, pos: e.clientX < r.left + r.width / 2 ? "before" : "after" };   // 카드가 가로로 놓임
      }
      const sec = e.target.closest("[data-biz]");
      return sec && !row ? { el: sec, pos: "into" } : null;
    };
    box.addEventListener("dragover", (e) => {
      const t = target(e);
      if (!t) return;
      e.preventDefault();
      clearMarks();
      t.el.classList.add(`drop-${t.pos}`);
    });
    box.addEventListener("drop", async (e) => {
      const t = target(e);
      if (!t) return;
      e.preventDefault();
      clearMarks();
      try {
        if (drag.type === "biz") {
          const ids = this.biz.map((x) => x.id).filter((x) => x !== drag.id);
          const at = ids.indexOf(+t.el.dataset.biz) + (t.pos === "after" ? 1 : 0);
          ids.splice(at, 0, drag.id);
          await App.api("/api/businesses/order", { json: { ids } });
        } else {
          const sec = t.el.closest("[data-biz]");
          const g = this.groups.find((x) => String(x.id) === sec.dataset.biz);
          const ids = g.stores.map((x) => x.id).filter((x) => x !== drag.id);
          const at = t.pos === "into" ? ids.length : ids.indexOf(+t.el.dataset.store) + (t.pos === "after" ? 1 : 0);
          ids.splice(at, 0, drag.id);
          await App.api("/api/stores/order", { json: { ids, business_id: g.none ? "" : g.id } });
        }
      } catch (err) { App.toast(err.message, true); }
      drag = null;
      await this.load();
    });
  },

  editBiz(b) {
    const isNew = !b.id;
    App.openModal({
      title: isNew ? "사업자 추가" : `${b.name} 수정`,
      body: `<div class="form">
        <label class="field">사업자 이름 (상호)<input id="b-name" value="${esc(b.name || "")}" autofocus></label>
        <label class="field">사업자등록번호 <span class="muted">(메모용, 비워도 됨)</span><input id="b-reg" value="${esc(b.reg_no || "")}"></label>
        <label class="field">메모<input id="b-memo" value="${esc(b.memo || "")}"></label>
        <p class="muted small">스토어는 스토어 '수정'에서 사업자를 고르거나, 이 사업자 줄의 '스토어 추가'로 넣습니다. 사업자 하나에 최대 3개.</p></div>`,
      buttons: [
        ...(isNew ? [] : [{ label: "삭제", danger: true, onClick: async () => {
          const ok = await App.confirmDanger({ title: `${b.name} 삭제`, body: `<p>사업자 <b>${esc(b.name)}</b>를 지웁니다. 안의 스토어는 지우지 않고 '사업자 없음'으로 옮깁니다.</p>` });
          if (!ok) return false;
          await App.api(`/api/businesses/${b.id}`, { method: "DELETE" }); await this.load();
        } }]),
        { label: "취소" },
        { label: "저장", primary: true, onClick: async (m) => {
          try {
            const r = await App.api("/api/businesses", { json: { id: b.id, name: $("#b-name", m).value, reg_no: $("#b-reg", m).value, memo: $("#b-memo", m).value } });
            this.closed.delete(String(r.id)); this.saveClosed();
            await this.load();
          } catch (e) { App.toast(e.message, true); return false; }
        } },
      ],
    });
  },

  /* 스토어 템플릿: 상세 상단·하단(이미지 + HTML), 관부가세 코드, 가격 조정 %, 표시 할인율 % */
  async template(s) {
    let t;
    try { t = await App.api(`/api/stores/${s.id}/template`); } catch (e) { return App.toast(e.message, true); }
    const cfg = App.state.settings;
    const imgs = (part) => `<div class="tpl-imgs">${t[part].map((f) => `<figure><img src="/api/stores/${s.id}/template/image/${encodeURIComponent(f)}" alt="">
        <button type="button" data-del="${esc(f)}" title="지우기">✕</button></figure>`).join("") || '<span class="muted small">이미지 없음</span>'}</div>
      <label class="btn sm"><input type="file" data-up="${part}" accept=".jpg,.jpeg,.png,.gif,.webp" multiple hidden>이미지 추가</label>`;
    App.openModal({
      title: `${s.name} · 스토어 템플릿`,
      wide: true,
      body: `<div class="form" id="tpl-box">
        <p class="muted small" style="margin:0">원본 상품에는 스토어 상단·하단이 없습니다. 이 스토어에 올릴 때 상세페이지 <b>맨 위에 상단</b>, <b>맨 아래에 하단</b>을 붙입니다.
          이미지는 올린 순서대로 들어가고, 처음 등록할 때 이 스토어 이름으로 네이버에 한 번 올려 두고 다시 씁니다. 비워 둔 칸은 설정의 공통값을 씁니다.</p>
        <div class="tpl-grid">
          <div><h3 class="sec-title">상세 상단</h3>${imgs("top")}
            <label class="field">상단 HTML <span class="muted">(이미지 아래에 붙음, 비워도 됨)</span><textarea id="t-top" rows="4" spellcheck="false">${esc(t.top_html)}</textarea></label></div>
          <div><h3 class="sec-title">상세 하단</h3>${imgs("bottom")}
            <label class="field">하단 HTML <span class="muted">(이미지 위에 붙음, 비워도 됨)</span><textarea id="t-bottom" rows="4" spellcheck="false">${esc(t.bottom_html)}</textarea></label></div>
        </div>
        <div class="two">
          <label class="field">관부가세 코드 <span class="muted">(출고지가 해외면 필수 · 공통값: ${esc((CUSTOMS_OPTS.find(([v]) => v === cfg.customs_tax_type) || [, "없음"])[1])})</span>
            <select id="t-customs">${CUSTOMS_OPTS.map(([v, l]) => `<option value="${v}" ${v === (t.customs || "") ? "selected" : ""}>${esc(v ? l : `설정 공통값 따름`)}</option>`).join("")}</select></label>
          <label class="field">수입사·A/S 전화 <span class="muted">스토어 '수정'에서 정합니다</span></label>
        </div>
        <h3 class="sec-title">가격</h3>
        <p class="muted small" style="margin:0">손님 가격 = (판매가 - 할인가) × (1 + 가격 조정 %) × 흔들기(범위 안에서 상품마다 다르게, 원본가와 같은 값은 안 나옴), 100원 올림.
          표시 할인율은 금액으로 걸어 <b>정확히 그 %</b>가 되게 판매가를 정합니다. 칸을 비우면 설정의 기본값입니다.</p>
        <div class="four">
          <label class="field">가격 조정 % <span class="muted">(마진, 예: 10)</span>
            <input id="t-price" type="number" step="0.5" value="${t.price_pct ?? ""}" placeholder="0"></label>
          <label class="field">흔들기 최소 % <span class="muted">(예: -3)</span><input id="t-jlo" type="number" step="0.5" value="${t.jitter_min ?? ""}" placeholder="기본 ${cfg.price_jitter_min ?? -3}"></label>
          <label class="field">흔들기 최대 % <span class="muted">(예: 3)</span><input id="t-jhi" type="number" step="0.5" value="${t.jitter_max ?? ""}" placeholder="기본 ${cfg.price_jitter_max ?? 3}"></label>
          <label class="field">표시 할인율 % <span class="muted">(0 = 할인 없음)</span>
            <input id="t-disc" type="number" min="0" max="89" step="1" value="${t.discount_pct ?? ""}" placeholder="기본 ${cfg.display_discount_pct ?? 30}"></label>
        </div>
        <div class="muted small" id="t-price-ex"></div>
        <h3 class="sec-title">워터마크</h3>
        <div class="two">
          <label class="field">워터마크 글자 <span class="muted">(비우면 스토어 이름 · 아래 로고를 올리면 로고를 씀)</span><input id="t-wm" value="${esc(t.wm_text || "")}" placeholder="${esc(s.name)}"></label>
          <div class="field">워터마크 로고 <span class="muted">(PNG 투명 배경 권장)</span>
            <div class="wm-store"><img id="wm-prev" src="/api/watermark/preview?store_id=${s.id}&w=1000&h=1000&_=${Date.now()}" alt="워터마크 미리보기">
              <div><label class="btn"><input type="file" id="wm-file" accept=".png,.jpg,.jpeg,.webp" hidden>로고 올리기</label>
              <button type="button" class="btn ghost" id="wm-del">로고 지우기</button></div></div></div>
        </div>
        <h3 class="sec-title">상세 옵션표</h3>
        <p class="muted small" style="margin:0">원본 상세의 옵션표(사진 + 옵션 이름)를 <b>2열 그림</b>으로 만들어 네이버에 올립니다 — 표·CSS를 쓰지 않아 휴대폰에서도 선명하고 늘 2열입니다. 고르지 않으면 설정의 공통값을 씁니다.</p>
        <div class="two">
          <div class="form" style="gap:8px">
            <label class="field">모양 <select id="t-optstyle"><option value="">설정 공통값 따름 (지금: ${esc(((OPT_STYLES.find(([v]) => v === cfg.option_table_style) || OPT_STYLES[0])[1]).split(":")[0].split(" (")[0])})</option>
              ${OPT_STYLES.map(([v, l]) => `<option value="${v}" ${v === t.opt_style ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
            <div class="field">강조색 <span class="muted" id="t-optcolor-l"></span>
              <div class="opt-sw" id="t-optsw"><button type="button" class="opt-sw-common" data-c="">공통 색</button>
                ${OPT_COLORS.map(([c, n]) => `<button type="button" data-c="${c}" title="${n}" style="background:${c}"></button>`).join("")}
                <label class="opt-sw-pick" title="직접 고르기"><input type="color" id="t-optpick" value="${esc(t.opt_color || cfg.option_table_color || "#1F2937")}">직접</label></div></div>
          </div>
          <div class="field">미리보기 <span class="muted">(사진은 회색 칸)</span><div class="opt-prev" id="t-optprev"></div></div>
        </div>
        <h3 class="sec-title">출고지 · 반품지</h3>
        <p class="muted small">판매자센터 주소록에 등록한 주소의 번호입니다. 비우면 판매자센터의 기본 출고지·반품지로 올라갑니다. 해외 출고지는 판매자센터 주소록에 먼저 등록해 두세요.</p>
        <div class="two">
          <label class="field">출고지 번호 <input id="t-ship" type="number" value="${t.ship_addr ?? ""}" placeholder="기본 출고지"></label>
          <label class="field">반품·교환지 번호 <input id="t-ret" type="number" value="${t.return_addr ?? ""}" placeholder="기본 반품지"></label>
        </div>
        <button type="button" class="btn sm" id="t-addr-load" style="align-self:flex-start">네이버 주소록 불러오기</button>
        <div id="t-addr" class="addr-list"></div>
        <p class="muted small">가격 조정은 새로 복사하는 것부터, 이미 만든 대기 복사본은 설정 → '대기 중인 복사본 가격 다시 계산'. 상단·하단·관부가세·표시 할인율·옵션표는 다음 등록(최신화·다시 올리기 포함)부터.</p>
      </div>`,
      buttons: [{ label: "닫기" }, { label: "저장", primary: true, onClick: async (b) => {
        try {
          const r = await App.api(`/api/stores/${s.id}/template`, { json: { top_html: $("#t-top", b).value, bottom_html: $("#t-bottom", b).value,
            customs: $("#t-customs", b).value, jitter_min: $("#t-jlo", b).value, jitter_max: $("#t-jhi", b).value, wm_text: $("#t-wm", b).value, ship_addr: $("#t-ship", b).value, return_addr: $("#t-ret", b).value, price_pct: $("#t-price", b).value, discount_pct: $("#t-disc", b).value,
            opt_style: $("#t-optstyle", b).value, opt_color: optColor } });
          App.toast(`${s.name} 템플릿을 저장했습니다` + (r.repriced ? ` · 아직 안 올린 복사본 ${num(r.repriced)}건 가격을 다시 정했습니다` : ""));
        } catch (e) { App.toast(e.message, true); return false; }
      } }],
    });
    const body = $("#tpl-box");   // 창을 다시 그릴 때마다 새 요소라 이벤트가 겹치지 않음
    const prev = () => { const im = $("#wm-prev"); if (im) im.src = `/api/watermark/preview?store_id=${s.id}&w=1000&h=1000&_=${Date.now()}`; };
    $("#wm-file")?.addEventListener("change", async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const fd = new FormData(); fd.append("file", f);
      try { await App.api(`/api/stores/${s.id}/watermark`, { method: "POST", body: fd }); prev(); App.toast("로고를 올렸습니다"); }
      catch (err) { App.toast(err.message, true); }
      e.target.value = "";
    });
    $("#wm-del")?.addEventListener("click", async () => {
      try { await App.api(`/api/stores/${s.id}/watermark`, { method: "DELETE" }); prev(); } catch (err) { App.toast(err.message, true); }
    });
    // 가격 예시 (원본가 50,000원 기준)
    const ex = () => {
      const pct = (id, d) => { const v = $(id).value; return v === "" ? +d : +v; };
      const m = pct("#t-price", 0), lo = pct("#t-jlo", cfg.price_jitter_min ?? -3), hi = pct("#t-jhi", cfg.price_jitter_max ?? 3), dp = pct("#t-disc", cfg.display_discount_pct ?? 30);
      const r100 = (x) => Math.ceil(x / 100) * 100;
      const a = r100(50000 * (1 + m / 100) * (1 + lo / 100)), z = r100(50000 * (1 + m / 100) * (1 + hi / 100));
      let shown = "";
      if (dp > 0 && dp < 90) { const sh = Math.ceil(a / (1 - dp / 100) / 1000) * 1000; shown = ` · 표시 예: 판매가 ${num(sh)}원 → ${dp}% 할인 (${num(Math.round(sh * dp / 100))}원)`; }
      $("#t-price-ex").textContent = `예) 원본가 50,000원 → 손님 가격 ${num(a)}~${num(z)}원${shown}`;
    };
    ["#t-price", "#t-jlo", "#t-jhi", "#t-disc"].forEach((id) => $(id).addEventListener("input", ex));
    ex();
    // 옵션표 모양·색 (optColor ''면 설정 공통 색)
    let optColor = t.opt_color || "";
    const optDraw = () => {
      const base = cfg.option_table_color || "#1F2937";
      const style = $("#t-optstyle").value || cfg.option_table_style || "strong";
      const color = optColor || base;
      $$("#t-optsw button").forEach((x) => x.classList.toggle("on", (x.dataset.c || "") === optColor));
      const named = (c) => (OPT_COLORS.find(([v]) => v.toUpperCase() === c.toUpperCase()) || [, c])[1];
      $("#t-optcolor-l").textContent = optColor ? `이 스토어: ${named(optColor)}` : `공통 색 (${named(base)})`;
      $("#t-optsw").style.opacity = style === "strong" ? "" : ".45";
      $("#t-optprev").innerHTML = optTablePreview(style, color);
    };
    $("#t-optsw").addEventListener("click", (e) => {
      const x = e.target.closest("button[data-c]");
      if (!x) return;
      optColor = x.dataset.c;
      if (optColor) $("#t-optpick").value = optColor;
      optDraw();
    });
    $("#t-optpick").addEventListener("input", (e) => { optColor = e.target.value.toUpperCase(); optDraw(); });
    $("#t-optstyle").addEventListener("change", optDraw);
    optDraw();
    body.addEventListener("click", async (e) => {
      if (e.target.id === "t-addr-load") {
        e.target.disabled = true; e.target.textContent = "불러오는 중";
        try {
          const list = await App.api(`/api/stores/${s.id}/addresses`);
          $("#t-addr", body).innerHTML = list.length ? list.map((a) => `<div class="addr-row">
              <span class="code">${a.id}</span><b>${esc(a.name || "이름 없음")}</b>${a.overseas ? '<span class="flag warn">해외</span>' : ""}
              <span class="muted small">${esc(ADDR_TYPE[a.type] || a.type)} · ${esc(a.address)}</span>
              <span class="addr-use"><button type="button" class="btn sm" data-addr="t-ship" data-id="${a.id}">출고지로</button>
              <button type="button" class="btn sm" data-addr="t-ret" data-id="${a.id}">반품지로</button></span></div>`).join("")
            : '<p class="muted">주소록이 비어 있습니다. 판매자센터 → 판매자 정보 → 주소록에서 먼저 등록하세요.</p>';
        } catch (err) {
          $("#t-addr", body).innerHTML = `<p class="c-err small">${esc(err.message)}<br>불러오지 못하면 판매자센터 주소록의 번호를 직접 넣어도 됩니다.</p>`;
        }
        e.target.disabled = false; e.target.textContent = "네이버 주소록 불러오기";
      }
      const pick = e.target.closest("[data-addr]");
      if (pick) { $(`#${pick.dataset.addr}`, body).value = pick.dataset.id; App.toast(`${pick.textContent.replace("로", "")}: ${pick.dataset.id}번 (저장을 눌러야 적용)`); }
    });
    body.addEventListener("change", async (e) => {
      const inp = e.target.closest("[data-up]");
      if (!inp) return;
      for (const f of inp.files) {
        const fd = new FormData(); fd.append("file", f); fd.append("part", inp.dataset.up);
        try { await App.api(`/api/stores/${s.id}/template/image`, { method: "POST", body: fd }); }
        catch (err) { App.toast(err.message, true); }
      }
      this.template(s);
    });
    body.addEventListener("click", async (e) => {
      const d = e.target.closest("[data-del]");
      if (!d) return;
      await App.api(`/api/stores/${s.id}/template/image/${encodeURIComponent(d.dataset.del)}`, { method: "DELETE" });
      this.template(s);
    });
  },

  edit(s) {
    const isNew = !s.id;
    App.openModal({
      title: isNew ? "스토어 추가" : `${s.name} 수정`,
      body: `<div class="form">
        <div class="two">
          <label class="field">스토어 이름<input name="name" value="${esc(s.name || "")}" autofocus></label>
          <label class="field">코드 <span class="muted">(판매자 관리코드 앞자리, 예: S07)</span><input name="code" value="${esc(s.id ? s.code : "")}" placeholder="비우면 S+번호"></label>
        </div>
        <label class="field">사업자 <span class="muted">(사업자 하나에 스토어 최대 3개)</span><select name="business_id"><option value="">사업자 없음</option>
          ${(this.biz || []).map((b) => `<option value="${b.id}" ${b.id === s.business_id ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select></label>
        <label class="field">스토어 주소<input name="store_url" value="${esc(s.store_url || "")}" placeholder="https://smartstore.naver.com/mystore"></label>
        <div class="two">
          <label class="field">애플리케이션 ID<input name="client_id" value="${esc(s.client_id || "")}"></label>
          <label class="field">애플리케이션 시크릿<input name="client_secret" type="password" placeholder="${s.has_keys ? "저장됨 · 바꿀 때만 입력" : ""}"></label>
        </div>
        <div class="two">
          <label class="field">A/S 전화번호 <span class="muted">(비우면 설정의 기본값)</span><input name="as_phone" value="${esc(s.as_phone || "")}"></label>
          <label class="field">수입사 <span class="muted">(원산지 수입사 칸 · 비우면 설정의 틀, 기본 '${esc(App.state.settings.importer_template || "")}')</span><input name="importer" value="${esc(s.importer || "")}" placeholder="${esc((App.state.settings.importer_template || "").replace("{store}", s.name || "스토어"))}"></label>
          <label class="field">워터마크 <span class="muted">스토어 '템플릿'에서 정합니다</span></label>
          <label class="field">상품 수 한도<input name="capacity" type="number" min="0" value="${s.capacity ?? 10000}"></label>
        </div>
        <label class="field">판매자센터 크롬 프로필 <span class="muted">(그 프로필에 이 스토어 계정으로 로그인해 두면 '판매자센터' 버튼이 이 계정으로 바로 열림)</span>
          <span class="cp-row"><select name="chrome_profile" id="s-cp"><option value="">정하지 않음 (지금 브라우저로 열기)</option>
            ${s.chrome_profile ? `<option value="${esc(s.chrome_profile)}" selected>${esc(s.chrome_profile)}</option>` : ""}</select>
            <span class="muted small" id="s-cp-note">크롬 프로필 불러오는 중…</span></span></label>
        <label class="field">받는 메일 주소 <span class="muted">(메일함에서 이 스토어 메일을 구분 · 예: me+redcoco@gmail.com · 비우면 메일 안의 스토어 이름으로)</span><input name="mail_to" value="${esc(s.mail_to || "")}"></label>
        <label class="field">메모<input name="memo" value="${esc(s.memo || "")}"></label>
        <label class="check"><input type="checkbox" name="enabled" ${s.enabled ? "checked" : ""}> 사용 (끄면 새 계획에서 빠짐)</label>
      </div>`,
      buttons: [
        ...(isNew ? [] : [{ label: "삭제", danger: true, onClick: async () => {
          if (!confirm(`'${s.name}' 스토어를 지울까요?`)) return false;
          try { await App.api(`/api/stores/${s.id}`, { method: "DELETE" }); await this.load(); }
          catch (e) { App.toast(e.message, true); return false; }
        } }]),
        { label: "취소" },
        { label: "저장", primary: true, onClick: async (b) => {
          const v = { id: s.id };
          $$("input, select", b).forEach((x) => { if (x.name) v[x.name] = x.type === "checkbox" ? x.checked : x.value; });
          try { await App.api("/api/stores", { json: v }); await this.load(); App.refreshState(); }
          catch (e) { App.toast(e.message, true); return false; }
        } },
      ],
    });
    App.api("/api/chrome/profiles").then((r) => {
      const sel = $("#s-cp"), note = $("#s-cp-note");
      if (!sel) return;
      const have = new Set([...sel.options].map((o) => o.value));
      for (const p of r.profiles) {
        if (have.has(p.dir)) { sel.querySelector(`option[value="${CSS.escape(p.dir)}"]`).textContent = `${p.name}${p.email ? " · " + p.email : ""} (${p.dir})`; continue; }
        sel.insertAdjacentHTML("beforeend", `<option value="${esc(p.dir)}">${esc(p.name)}${p.email ? " · " + esc(p.email) : ""} (${esc(p.dir)})</option>`);
      }
      note.textContent = !r.chrome ? "크롬을 찾지 못함 (설정 → API 키 → 크롬 위치)" : r.profiles.length ? `프로필 ${r.profiles.length}개` : "크롬 프로필이 없습니다 — 크롬에서 프로필을 먼저 추가하세요";
    }).catch(() => { const n = $("#s-cp-note"); if (n) n.textContent = ""; });
  },

  /* 스토어 하나 최신화: 올린 지 N일 넘은 판매 중 복사본(잠금 제외)을 지우고 다시 올린다 */
  refresh(s) {
    const count = async (days) => {
      const base = { store_id: s.id, status: "live", size: 1, ...(days ? { age_days: days } : {}) };
      const [all, open] = await Promise.all([
        App.api(`/api/listings?${new URLSearchParams(base)}`),
        App.api(`/api/listings?${new URLSearchParams({ ...base, locked: 0 })}`),
      ]);
      return { all: all.total, open: open.total };
    };
    const go = async (b, now) => {
      const days = $("#rf-days", b).value;
      try {
        const r = await App.api("/api/listings/schedule", { json: { store_id: s.id, op: "refresh", now, ...(days ? { age_days: days } : {}) } });
        if (!r.scheduled) { App.toast("최신화할 건이 없습니다."); return; }
        if (r.started) { App.run = await App.api("/api/run"); App.toast(`${s.name}: ${num(r.scheduled)}건 최신화를 시작했습니다 (이 건들만).`); }
        else if (r.busy) App.toast(`${num(r.scheduled)}건을 대기에 넣었습니다. 지금 다른 작업이 진행 중이라, 끝난 뒤 복사본 화면에서 시작하세요.`);
        else App.toast(`${num(r.scheduled)}건을 대기에 넣었습니다. 복사본 화면 시작에서 '최신화'를 골라 처리하세요.`);
        App.go(`#listings?store_id=${s.id}`);
      } catch (e) { App.toast(e.message, true); return false; }
    };
    App.openModal({
      title: `${s.name} 최신화`,
      body: `<p class="muted small">이 스토어의 판매 중 복사본을 네이버에서 지우고 같은 내용으로 다시 올립니다. 회차가 1 오르고 관리코드 끝 숫자가 바뀝니다.
        <b>잠긴 복사본(판매 이력·직접 잠금)은 빠집니다.</b> 실행 직전에 이 스토어 주문을 한 번 더 가져와 확인합니다.</p>
        <label class="field">대상<select id="rf-days">
          <option value="30">올린 지 30일 넘은 것</option><option value="60">60일 넘은 것</option>
          <option value="90">90일 넘은 것</option><option value="7">7일 넘은 것</option><option value="">판매 중 전체</option></select></label>
        <div class="plan-sum" id="rf-sum">세는 중…</div>`,
      buttons: [{ label: "취소" }, { label: "대기에 넣기", onClick: (b) => go(b, false) }, { label: "바로 하기", primary: true, onClick: (b) => go(b, true) }],
    });
    const upd = async () => {
      const days = $("#rf-days").value;
      const c = await count(days);
      $("#rf-sum").innerHTML = `최신화 <b>${num(c.open)}건</b>` + (c.all - c.open ? ` · 잠금으로 빠지는 것 ${num(c.all - c.open)}건` : "");
    };
    $("#rf-days").addEventListener("change", upd);
    upd();
  },

  bulk() {
    App.openModal({
      title: "여러 스토어 한 번에 추가",
      wide: true,
      body: `<p class="muted small">한 줄에 스토어 하나. <b>이름, 애플리케이션 ID, 시크릿, 스토어 주소, A/S 전화, 코드</b> 순서로 쉼표나 탭으로 구분합니다.
        엑셀에서 여섯 칸을 복사해 붙여 넣어도 됩니다. 같은 이름의 스토어가 있으면 채운 값만 바꿉니다.</p>
        <textarea id="bulk" rows="12" autofocus spellcheck="false" placeholder="제1스토어, abcd1234, $2a$04$xxxx, https://smartstore.naver.com/store1, 010-1234-5678"></textarea>`,
      buttons: [{ label: "취소" }, { label: "추가", primary: true, onClick: async (b) => {
        try {
          const r = await App.api("/api/stores/bulk", { json: { text: $("#bulk", b).value } });
          App.toast(`새로 ${r.added}곳, 바꾼 곳 ${r.updated}곳`);
          await this.load(); App.refreshState();
        } catch (e) { App.toast(e.message, true); return false; }
      } }],
    });
  },

  async test(s, btn) {
    btn.disabled = true;
    btn.textContent = "확인 중… (상품을 다 세느라 몇십 초)";
    try {
      const r = await App.api(`/api/stores/${s.id}/test`, { json: {} });
      App.toast(`${s.name}: 연결됨 · 네이버 상품 ${num(r.naver_count)}개 (전시중지(고구마) ${num(r.suspended)}` +
        Object.entries(r.status || {}).filter(([k, v]) => !k.startsWith("_") && v).map(([k, v]) => ` · ${NAVER_STATUS[k] || k} ${num(v)}`).join("") + ")");
      await this.load(); App.refreshState();
    } catch (e) { App.toast(`${s.name}: ${e.message}`, true); btn.disabled = false; btn.textContent = "연결 확인"; }
  },

  async testAll() {
    let ok = 0, bad = [];
    for (const s of this.rows.filter((x) => x.enabled)) {
      try { await App.api(`/api/stores/${s.id}/test`, { json: {} }); ok++; } catch (e) { bad.push(`${s.name}: ${e.message}`); }
    }
    await this.load(); App.refreshState();
    if (bad.length) App.openModal({ title: "연결 확인 결과", body: `<p>연결됨 ${ok}곳 · 실패 ${bad.length}곳</p><ul>${bad.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`, buttons: [{ label: "닫기" }] });
    else App.toast(`${ok}곳 모두 연결됨`);
  },
});
