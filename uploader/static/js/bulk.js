/* 올린 상품 일괄 변경: 스토어를 골라 이미 올라간 상품의 출고지·관부가세·사은품·이벤트 문구·적립금·무이자할부를 한 번에 */
"use strict";

const BK_MODES = `<option value="keep">그대로</option><option value="set">바꾸기</option><option value="remove">빼기</option>`;
const BK_STATUS = { ready: "만듦 (먼저 1개로 시험)", tested: "시험함", running: "진행 중", stopped: "멈춤 (남은 것 있음)", done: "끝" };

App.page("bulk", {
  async mount(el) {
    const stores = await App.api("/api/stores");
    this.stores = stores;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>올린 상품 일괄 변경</h1></header>
      <p class="muted" style="margin:0">이미 네이버에 올라간 상품의 설정을 스토어 단위로 한 번에 바꿉니다. 상품마다 네이버에서 읽어 <b>고른 항목만</b> 고친 뒤 다시 보냅니다
        (상품 하나에 요청 2번 · 1만 개 스토어 1~3시간 예상). 순서: <b>작업 만들기 → 1개로 시험 → 판매자센터에서 확인 → 전체 시작</b>. 멈춰도 '이어서'로 남은 것만 합니다.</p>
      <section class="card pad">
        <h2 class="sec-title">1. 스토어</h2>
        <div class="bk-stores">${byBusiness(stores).map(([biz, ss]) => `<div class="sp-group">${esc(biz)}
            <button type="button" class="link-btn small" data-biz-all="${esc(biz)}">모두</button></div>` + ss.map((s) => `
          <label class="sp-row ${regionCls(s)}" data-biz="${esc(biz)}"><input type="checkbox" value="${s.id}">
            <span class="sp-name"><span class="code">${esc(s.code || "")}</span> ${esc(s.name)}
              ${s.ship_region ? `<span class="region-tag">${REGION[s.ship_region]}</span>` : ""}</span>
            <span class="muted small">출고지 ${s.tpl_ship_addr ? esc(String(s.tpl_ship_addr)) : "-"} · 반품지 ${s.tpl_return_addr ? esc(String(s.tpl_return_addr)) : "-"}</span></label>`).join("")).join("")
          || '<p class="muted">스토어가 없습니다.</p>'}</div>
        <h2 class="sec-title">2. 대상 상품</h2>
        <div class="radio-cards bk-target">
          <label><input type="radio" name="bk-target" value="program" checked><div><b>프로그램으로 올린 상품만</b>
            <span class="muted small">복사본 화면에서 '판매 중'인 것</span></div></label>
          <label><input type="radio" name="bk-target" value="all"><div><b>스토어 전체 상품</b>
            <span class="muted small">판매자센터에서 직접 올린 것까지 — 시작할 때 네이버에서 상품 목록을 받아 옵니다</span></div></label>
        </div>
        <h2 class="sec-title">3. 바꿀 항목 <span class="muted small" style="font-weight:400">'그대로'는 건드리지 않습니다</span></h2>
        <div class="bk-fields">
          <div class="bk-row"><b>출고지·반품지</b><select id="bk-addr" class="sel"><option value="keep">그대로</option>
            <option value="template">스토어 템플릿 값으로 (스토어마다)</option></select>
            <span class="muted small">주소록 번호는 스토어(계정)마다 달라서 스토어 → 템플릿의 출고지·반품지 번호를 씁니다. 국내로 옮기려면 템플릿을 국내 주소로 먼저 바꾸세요.</span></div>
          <div class="bk-row"><b>관부가세</b><select id="bk-customs" class="sel"><option value="keep">그대로</option>
            <option value="NOT_APPLICABLE">부과 대상 아님</option><option value="INCLUDED">관부가세 포함</option><option value="EXCLUDED">관부가세 미포함</option>
            <option value="remove">항목 빼기</option></select><span class="muted small">출고지가 해외면 필수 · 국내 출고로 옮길 때 정리</span></div>
          <div class="bk-row"><b>사은품</b><select class="sel" data-mode="gift">${BK_MODES}</select>
            <span class="bk-set" data-for="gift"><input id="bk-gift" maxlength="100" placeholder="예) 보관 파우치 증정"></span></div>
          <div class="bk-row"><b>이벤트 문구</b><select class="sel" data-mode="event">${BK_MODES}</select>
            <span class="bk-set" data-for="event"><input id="bk-event" maxlength="200" placeholder="예) 오늘 출발 · 리뷰 이벤트 진행 중"></span></div>
          <div class="bk-row"><b>구매 적립금</b><select class="sel" data-mode="ppoint">${BK_MODES}</select>
            <span class="bk-set" data-for="ppoint"><input id="bk-pp" type="number" min="1" placeholder="금액"> <select id="bk-pp-unit" class="sel"><option value="WON">원</option><option value="PERCENT">%</option></select></span></div>
          <div class="bk-row"><b>리뷰 적립금</b><select class="sel" data-mode="rpoint">${BK_MODES}</select>
            <span class="bk-set bk-rp" data-for="rpoint">
              <label>텍스트 <input id="bk-rp-text" type="number" min="0">원</label><label>포토·동영상 <input id="bk-rp-photo" type="number" min="0">원</label>
              <label>한 달 사용 텍스트 <input id="bk-rp-after_text" type="number" min="0">원</label><label>한 달 사용 포토·동영상 <input id="bk-rp-after_photo" type="number" min="0">원</label>
              <label>알림받기 동의 고객 <input id="bk-rp-member" type="number" min="0">원</label></span></div>
          <div class="bk-row"><b>무이자할부</b><select class="sel" data-mode="interest">${BK_MODES}</select>
            <span class="bk-set" data-for="interest"><input id="bk-int" type="number" min="2" max="24" placeholder="개월"> 개월</span></div>
          <div class="bk-row"><b>끝난 스토어 표시</b><select id="bk-region" class="sel"><option value="">그대로</option>
            <option value="domestic">국내 (초록)</option><option value="overseas">해외 (파랑)</option></select>
            <span class="muted small">스토어의 모든 상품이 바뀌면 스토어 색 표시를 바꿈</span></div>
        </div>
        <div class="bk-go"><button class="btn primary" id="bk-create">작업 만들기</button>
          <span class="muted small">만들기만 하고 네이버에는 아직 보내지 않습니다.</span></div>
      </section>
      <section class="card pad"><h2 class="sec-title">작업 목록</h2><div id="bk-jobs" class="muted">불러오는 중</div></section>
    </div>`;
    const sync = () => $$("[data-mode]", el).forEach((s) => {
      const box = $(`[data-for="${s.dataset.mode}"]`, el);
      if (box) box.hidden = s.value !== "set";
    });
    $$("[data-mode]", el).forEach((s) => s.addEventListener("change", sync));
    sync();
    $$("[data-biz-all]", el).forEach((b) => b.addEventListener("click", () => {
      const boxes = $$(`label[data-biz="${CSS.escape(b.dataset.bizAll)}"] input`, el);
      const on = !boxes.every((x) => x.checked);
      boxes.forEach((x) => { x.checked = on; });
    }));
    $("#bk-create").addEventListener("click", () => this.create());
    $("#bk-jobs").addEventListener("click", (e) => this.onJobClick(e));
    await this.loadJobs();
    this.onDone = (t) => { if (t.kind === "bulkedit") this.loadJobs(); };
    App.on("task-done", this.onDone);
  },
  unmount() { if (this.onDone) App.off("task-done", this.onDone); },

  spec() {
    const mode = (k) => $(`[data-mode="${k}"]`).value;
    const n = (id) => $(id).value;
    return {
      addr: $("#bk-addr").value, customs: $("#bk-customs").value, region: $("#bk-region").value,
      gift: { mode: mode("gift"), text: n("#bk-gift") }, event: { mode: mode("event"), text: n("#bk-event") },
      ppoint: { mode: mode("ppoint"), value: n("#bk-pp"), unit: n("#bk-pp-unit") },
      rpoint: { mode: mode("rpoint"), ...Object.fromEntries(["text", "photo", "after_text", "after_photo", "member"].map((k) => [k, n(`#bk-rp-${k}`)])) },
      interest: { mode: mode("interest"), months: n("#bk-int") },
    };
  },

  async create() {
    const ids = $$(".bk-stores input:checked").map((x) => +x.value);
    if (!ids.length) return App.toast("스토어를 하나 이상 골라 주세요.", true);
    try {
      const j = await App.api("/api/bulk", { json: { spec: this.spec(), store_ids: ids, target: $("input[name=bk-target]:checked").value } });
      App.toast(`작업 #${j.id}를 만들었습니다. 아래 작업 목록에서 '1개로 시험'을 먼저 누르세요.`);
      this.loadJobs();
    } catch (e) { App.toast(e.message, true); }
  },

  async loadJobs() {
    const box = $("#bk-jobs");
    if (!box) return;
    const jobs = await App.api("/api/bulk");
    this.jobs = jobs;
    box.innerHTML = jobs.length ? jobs.map((j) => {
      const t = j.per_store.reduce((a, s) => { for (const k of ["total", "done", "same", "fail", "pending"]) a[k] = (a[k] || 0) + s[k]; return a; }, {});
      const canRun = j.status !== "ready";
      return `<div class="bk-job">
        <div class="bk-job-head"><b>#${j.id}</b> <span>${esc(j.summary)}</span>
          <span class="muted small">${when(j.created_at)} · ${j.target === "all" ? "스토어 전체 상품" : "프로그램으로 올린 상품"} · ${BK_STATUS[j.status] || esc(j.status)}</span></div>
        <table class="grid compact"><thead><tr><th>스토어</th><th class="w-num">대상</th><th class="w-num">바꿈</th><th class="w-num">이미 같음</th>
          <th class="w-num">실패</th><th class="w-num">남음</th></tr></thead><tbody>${j.per_store.map((s) => `<tr><td>${esc(s.name)}</td>
          <td class="num">${s.total ? num(s.total) : j.target === "all" ? "<span class='muted small'>시작할 때 받음</span>" : "0"}</td><td class="num c-ok">${num(s.done)}</td>
          <td class="num muted">${num(s.same)}</td><td class="num ${s.fail ? "c-err" : ""}">${num(s.fail)}</td><td class="num">${num(s.pending)}</td></tr>`).join("")}
          <tr class="sum"><td>합계</td><td class="num">${num(t.total)}</td><td class="num">${num(t.done)}</td><td class="num">${num(t.same)}</td><td class="num">${num(t.fail)}</td><td class="num">${num(t.pending)}</td></tr></tbody></table>
        ${j.sample.length ? `<p class="small" style="margin:6px 0 0">최근 바꾼 상품 (판매자센터에서 확인): ${j.sample.map((x) => `${sellerLink((App.stores || []).find((s) => s.id === x.store_id), x.link, esc(x.origin_no))}${x.changed ? ` <span class="muted">(${esc(x.changed)})</span>` : ""}`).join(" · ")}</p>` : ""}
        ${j.errors.length ? `<div class="bk-err"><b class="c-err">실패 사유</b>${j.errors.map((e) => `<div class="small">${num(e.n)}개 · ${esc(e.error)} <span class="muted">(예: ${esc(e.example)})</span></div>`).join("")}</div>` : ""}
        <div class="bk-actions">
          <button class="btn" data-bk="test" data-id="${j.id}">1개로 시험</button>
          <button class="btn primary" data-bk="run" data-id="${j.id}" ${canRun ? "" : "disabled title='먼저 1개로 시험하고 판매자센터에서 확인하세요'"}>${j.status === "stopped" ? "이어서" : "전체 시작"}</button>
          ${t.fail ? `<button class="btn" data-bk="retry" data-id="${j.id}">실패만 다시 대기로</button>` : ""}
        </div></div>`;
    }).join("") : '<p class="muted">아직 작업이 없습니다.</p>';
  },

  async onJobClick(e) {
    const b = e.target.closest("[data-bk]");
    if (!b) return;
    const id = +b.dataset.id, act = b.dataset.bk, j = (this.jobs || []).find((x) => x.id === id);
    if (act === "run") {
      const left = j.per_store.reduce((a, s) => a + s.pending, 0);
      const ok = await App.confirmDanger({ title: `일괄 변경 #${id} 전체 시작`, ok: "시작합니다",
        body: `<p><b>${esc(j.summary)}</b></p><p>${j.target === "all" ? "스토어 전체 상품 (시작할 때 목록을 받음)" : `남은 상품 <b>${num(left)}개</b>`}를 네이버에서 바꿉니다.
          상품마다 요청 2번이라 오래 걸릴 수 있고, 중간에 '중단'해도 바꾼 것은 그대로이며 '이어서'로 남은 것만 합니다.</p>
          <p class="muted small">판매자센터에서 시험한 상품을 확인하셨나요?</p>` });
      if (!ok) return;
    }
    if (act === "retry") {
      try { const r = await App.api(`/api/bulk/${id}/retry`, { method: "POST" }); App.toast(`실패 ${num(r.count)}개를 다시 대기로 돌렸습니다. '이어서'를 누르세요.`); this.loadJobs(); }
      catch (err) { App.toast(err.message, true); }
      return;
    }
    await App.startTask(App.api(`/api/bulk/${id}/${act}`, { method: "POST" }));
  },
});
