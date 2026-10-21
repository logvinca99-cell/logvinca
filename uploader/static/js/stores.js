/* 스토어: 추가·수정, 여러 개 한 번에 추가, 연결 확인(네이버 상품 수), 사용량 */
"use strict";

App.page("stores", {
  async mount(el) {
    try { this.open = new Set(JSON.parse(localStorage.getItem("biz-open") || "[]")); } catch (e) { this.open = new Set(); }
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>스토어</h1>
        <div class="head-actions">
          <button class="btn ghost" id="s-expand">모두 펼치기</button>
          <button class="btn" id="s-test-all">모두 연결 확인</button>
          <button class="btn" id="s-bulk">여러 개 한 번에 추가</button>
          <button class="btn" id="s-biz-add">사업자 추가</button>
          <button class="btn primary" id="s-add">스토어 추가</button>
        </div></header>
      <p class="muted small" style="margin:0">사업자별로 묶여 있습니다(사업자 하나에 스토어 최대 3개). 사업자 줄을 누르면 그 안의 스토어가 펼쳐집니다.
        ▲▼로 사업자와 스토어 순서를 바꾸면 복사·복사본 화면의 스토어 순서도 같이 바뀝니다.
        스토어마다 커머스API센터에서 애플리케이션을 만들고 이 PC의 IP를 호출 허용 IP로 등록해야 합니다.</p>
      <div id="s-groups" class="biz-groups"></div>
    </div>`;
    $("#s-add").addEventListener("click", () => this.edit({ capacity: 10000, enabled: 1 }));
    $("#s-biz-add").addEventListener("click", () => this.editBiz({}));
    $("#s-bulk").addEventListener("click", () => this.bulk());
    $("#s-test-all").addEventListener("click", () => this.testAll());
    $("#s-expand").addEventListener("click", () => {
      const all = this.groups.map((g) => String(g.id));
      const allOpen = all.every((k) => this.open.has(k));
      this.open = new Set(allOpen ? [] : all);
      this.saveOpen(); this.render();
    });
    $("#s-groups").addEventListener("click", (e) => this.onClick(e));
    await this.load();
  },

  saveOpen() { try { localStorage.setItem("biz-open", JSON.stringify([...this.open])); } catch (e) { /* 무시 */ } },

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
    const sum = (g, k) => g.stores.reduce((a, s) => a + (s[k] || 0), 0);
    $("#s-expand").textContent = this.groups.length && this.groups.every((g) => this.open.has(String(g.id))) ? "모두 접기" : "모두 펼치기";
    $("#s-groups").innerHTML = this.groups.length ? this.groups.map((g, gi) => {
      const open = this.open.has(String(g.id));
      return `<section class="card biz ${open ? "open" : ""}" data-biz="${g.id}">
        <div class="biz-head" data-toggle="${g.id}">
          <span class="biz-caret">${open ? "▾" : "▸"}</span>
          <div class="biz-title"><b>${esc(g.name)}</b>${g.reg_no ? ` <span class="muted small">${esc(g.reg_no)}</span>` : ""}
            <div class="biz-chips">${g.stores.map((s) => `<span class="code">${esc(s.code)}</span>${esc(s.name)}`).join(" · ") || '<span class="muted small">스토어 없음</span>'}</div></div>
          <div class="biz-nums"><span>스토어 <b>${g.stores.length}${g.none ? "" : "/3"}</b></span><span>판매 중 <b>${num(sum(g, "n_live"))}</b></span>
            <span>대기 <b>${num(sum(g, "n_pending") + sum(g, "n_ops"))}</b></span><span class="${sum(g, "n_fail") ? "c-err" : ""}">실패 <b>${num(sum(g, "n_fail"))}</b></span>
            <span>남은 자리 <b>${num(sum(g, "free"))}</b></span></div>
          ${g.none ? "" : `<div class="biz-acts" data-stop>
            <button class="icon-btn" data-bmove="-1" data-id="${g.id}" title="위로" ${gi === 0 ? "disabled" : ""}>▲</button>
            <button class="icon-btn" data-bmove="1" data-id="${g.id}" title="아래로" ${gi >= this.biz.length - 1 ? "disabled" : ""}>▼</button>
            <button class="btn sm" data-bedit="${g.id}">수정</button>
            ${g.stores.length < 3 ? `<button class="btn sm" data-badd="${g.id}">스토어 추가</button>` : ""}</div>`}
        </div>
        ${open ? this.tableHtml(g) : ""}
      </section>`;
    }).join("") : `<div class="card pad"><p class="muted">아직 사업자·스토어가 없습니다. <b>사업자 추가</b>로 사업자를 만들고 그 안에 스토어를 추가하세요.</p></div>`;
  },

  tableHtml(g) {
    if (!g.stores.length) return `<p class="muted pad">이 사업자에 스토어가 없습니다. 오른쪽 위 <b>스토어 추가</b>를 누르세요.</p>`;
    return `<div class="table-card"><table class="grid"><thead><tr>
        <th class="w-ord"></th><th class="w-code">코드</th><th class="w-sname">스토어</th><th class="w-usage">사용량 (대기 포함)</th><th class="w-num">남은 자리</th>
        <th class="w-num">판매 중</th><th class="w-num">대기</th><th class="w-num">실패</th><th class="w-num">내림</th>
        <th class="w-num">판매 이력</th><th class="w-num">네이버 상품 수</th><th class="w-act"></th>
      </tr></thead><tbody>${g.stores.map((s, i) => `<tr class="${s.enabled ? "" : "off"}">
      <td class="nowrap" data-stop><button class="icon-btn" data-smove="-1" data-id="${s.id}" data-biz="${g.id}" ${i === 0 ? "disabled" : ""} title="위로">▲</button><button class="icon-btn" data-smove="1" data-id="${s.id}" data-biz="${g.id}" ${i === g.stores.length - 1 ? "disabled" : ""} title="아래로">▼</button></td>
      <td><b class="code">${esc(s.code)}</b></td>
      <td><b>${esc(s.name)}</b>${s.enabled ? "" : ' <span class="flag">사용 안 함</span>'}${s.has_keys ? "" : ' <span class="flag warn">키 없음</span>'}
        <div class="p-sub">${s.store_url ? `<a href="${esc(s.store_url)}" target="_blank" rel="noopener">${esc(s.store_url.replace(/^https?:\/\//, ""))}</a>` : "주소 없음"}
        ${s.memo ? ` · ${esc(s.memo)}` : ""}${s.orders_synced_to ? ` · 주문 ${when(s.orders_synced_to)}까지` : ""}</div></td>
      <td>${usageBar(s.used, s.capacity)}<div class="p-sub">${num(s.used)} / ${num(s.capacity)}</div></td>
      <td class="num ${s.free < 500 ? "c-err" : ""}">${num(s.free)}</td>
      <td class="num"><a href="#listings?store_id=${s.id}&status=live">${num(s.n_live)}</a></td>
      <td class="num">${num(s.n_pending + s.n_ops)}</td>
      <td class="num ${s.n_fail ? "c-err" : ""}">${num(s.n_fail)}</td><td class="num">${num(s.n_deleted)}</td>
      <td class="num"><a href="#listings?store_id=${s.id}&status=sold">${num(s.n_sold)}</a>${s.n_locked ? `<div class="p-sub r"><a href="#listings?store_id=${s.id}&status=locked">잠금 ${num(s.n_locked)}</a></div>` : ""}</td>
      <td class="num">${s.naver_count != null ? `${num(s.naver_count)}<div class="p-sub r">${when(s.naver_count_at)}</div>` : '<span class="muted">확인 전</span>'}</td>
      <td><div class="store-acts"><button class="btn sm" data-act="edit" data-id="${s.id}">수정</button>
        <button class="btn sm" data-act="tpl" data-id="${s.id}">템플릿</button>
        <button class="btn sm ghost" data-act="test" data-id="${s.id}">연결 확인</button>
        <button class="btn sm ghost" data-act="refresh" data-id="${s.id}" ${s.n_live ? "" : "disabled"}>최신화</button></div></td></tr>`).join("")}</tbody></table></div>`;
  },

  async onClick(e) {
    const b = e.target.closest("button");
    if (b?.dataset.act) {
      const s = this.rows.find((x) => x.id === +b.dataset.id);
      if (b.dataset.act === "edit") this.edit(s);
      if (b.dataset.act === "tpl") this.template(s);
      if (b.dataset.act === "test") this.test(s, b);
      if (b.dataset.act === "refresh") this.refresh(s);
      return;
    }
    if (b?.dataset.bmove) {
      const ids = this.biz.map((x) => x.id);
      const i = ids.indexOf(+b.dataset.id), j = i + +b.dataset.bmove;
      if (j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      await App.api("/api/businesses/order", { json: { ids } });
      return this.load();
    }
    if (b?.dataset.smove) {
      const g = this.groups.find((x) => String(x.id) === b.dataset.biz);
      const ids = g.stores.map((x) => x.id);
      const i = ids.indexOf(+b.dataset.id), j = i + +b.dataset.smove;
      if (j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      try { await App.api("/api/stores/order", { json: { ids } }); } catch (err) { return App.toast(err.message, true); }
      return this.load();
    }
    if (b?.dataset.bedit) return this.editBiz(this.biz.find((x) => x.id === +b.dataset.bedit));
    if (b?.dataset.badd) return this.edit({ capacity: 10000, enabled: 1, business_id: +b.dataset.badd });
    if (e.target.closest("[data-stop]")) return;
    const head = e.target.closest("[data-toggle]");
    if (head) {
      const k = head.dataset.toggle;
      this.open.has(k) ? this.open.delete(k) : this.open.add(k);
      this.saveOpen(); this.render();
    }
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
            this.open.add(String(r.id)); this.saveOpen();
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
          <label class="field">관부가세 코드 <span class="muted">(출고지가 해외면 필수 · 비우면 설정 공통값 '${esc(cfg.customs_tax_type || "없음")}')</span>
            <input id="t-customs" value="${esc(t.customs)}" placeholder="커머스API customsTaxType 값"></label>
          <label class="field">가격 조정 % <span class="muted">(원본가 대비, 예: 10 = 10% 올림, -5 = 5% 내림 · 그 뒤 ±${cfg.price_jitter_pct}%, 100원 올림)</span>
            <input id="t-price" type="number" step="0.5" value="${t.price_pct ?? ""}" placeholder="0"></label>
          <label class="field">표시 할인율 % <span class="muted">(예: 30이면 판매가를 올리고 30% 즉시할인으로 같은 최종가 · 비우면 할인 없이 그 가격 그대로)</span>
            <input id="t-disc" type="number" min="0" max="89" step="1" value="${t.discount_pct ?? ""}" placeholder="없음"></label>
          <label class="field">수입사·A/S 전화·워터마크 <span class="muted">스토어 '수정'에서 정합니다</span></label>
        </div>
        <p class="muted small">가격 조정은 새로 복사하는 것부터, 이미 만든 대기 복사본은 설정 → '대기 중인 복사본 가격 다시 계산'. 상단·하단·관부가세·표시 할인율은 다음 등록부터.</p>
      </div>`,
      buttons: [{ label: "닫기" }, { label: "저장", primary: true, onClick: async (b) => {
        try {
          await App.api(`/api/stores/${s.id}/template`, { json: { top_html: $("#t-top", b).value, bottom_html: $("#t-bottom", b).value,
            customs: $("#t-customs", b).value, price_pct: $("#t-price", b).value, discount_pct: $("#t-disc", b).value } });
          App.toast(`${s.name} 템플릿을 저장했습니다`);
        } catch (e) { App.toast(e.message, true); return false; }
      } }],
    });
    const body = $("#tpl-box");   // 창을 다시 그릴 때마다 새 요소라 이벤트가 겹치지 않음
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
          <label class="field">워터마크 글자 <span class="muted">(비우면 스토어 이름 · 아래 로고를 올리면 로고를 씀)</span><input name="wm_text" value="${esc(s.wm_text || "")}"></label>
          ${s.id ? `<div class="field">워터마크 로고 <span class="muted">(PNG 투명 배경 권장)</span>
            <div class="wm-store"><img id="wm-prev" src="/api/watermark/preview?store_id=${s.id}&w=1000&h=1000&_=${Date.now()}" alt="워터마크 미리보기">
              <div><label class="btn"><input type="file" id="wm-file" accept=".png,.jpg,.jpeg,.webp" hidden>로고 올리기</label>
              <button type="button" class="btn ghost" id="wm-del">로고 지우기</button></div></div></div>` : ""}
          <label class="field">상품 수 한도<input name="capacity" type="number" min="0" value="${s.capacity ?? 10000}"></label>
        </div>
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
    App.openModal({
      title: `${s.name} 최신화`,
      body: `<p class="muted small">이 스토어의 판매 중 복사본을 네이버에서 지우고 같은 내용으로 다시 올립니다. 회차가 1 오르고 관리코드 끝 숫자가 바뀝니다.
        <b>잠긴 복사본(판매 이력·직접 잠금)은 빠집니다.</b> 실행 직전에 이 스토어 주문을 한 번 더 가져와 확인합니다.</p>
        <label class="field">대상<select id="rf-days">
          <option value="30">올린 지 30일 넘은 것</option><option value="60">60일 넘은 것</option>
          <option value="90">90일 넘은 것</option><option value="7">7일 넘은 것</option><option value="">판매 중 전체</option></select></label>
        <div class="plan-sum" id="rf-sum">세는 중…</div>`,
      buttons: [{ label: "취소" }, { label: "예약하고 바로 시작", primary: true, onClick: async (b) => {
        const days = $("#rf-days", b).value;
        try {
          const r = await App.api("/api/listings/schedule", { json: { store_id: s.id, op: "refresh", ...(days ? { age_days: days } : {}) } });
          if (!r.scheduled) { App.toast("최신화할 건이 없습니다."); return; }
          if (App.run?.running) {
            App.toast(`${num(r.scheduled)}건 예약했습니다. 지금 다른 작업이 진행 중이라, 끝난 뒤 복사본 화면에서 시작하세요.`);
          } else {
            App.run = await App.api("/api/run", { json: { store_id: s.id } });
            App.toast(`${s.name}: ${num(r.scheduled)}건 최신화를 시작했습니다.`);
          }
          App.go(`#listings?store_id=${s.id}`);
        } catch (e) { App.toast(e.message, true); return false; }
      } }],
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
    btn.textContent = "확인 중…";
    try {
      const r = await App.api(`/api/stores/${s.id}/test`, { json: {} });
      App.toast(`${s.name}: 연결됨 · 네이버에 상품 ${num(r.naver_count)}개`);
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
