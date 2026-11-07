/* 기존 상품 가져오기: 다른 방법으로 이미 올린 상품 → 업로드했던 셀업 엑셀 + 그 스토어 상품 목록(판매자코드로 맞춤)
   → 원본 + 그 스토어의 판매 중 복사본. 스토어에서 지운 상품은 버리고, 스토어에만 있는 상품은 목록으로 알려 줌. */
"use strict";

const ADOPT_KINDS = [["linked", "연결"], ["already", "이미 연결"], ["dropped", "스토어에 없어 뺌"], ["store_only", "스토어에만 있음"],
  ["price_diff", "엑셀≠손님 가격"], ["name_dup", "상품명 중복"], ["dup_code", "판매자코드 겹침"], ["dup_same", "연결 못 함"]];
const ymdOf = (ts) => { const d = new Date(ts * 1000); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

App.page("adopt", {
  async mount(el) {
    this.el = el;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>기존 상품 가져오기</h1>
        <div class="head-actions"><a class="btn" href="#inventory?adopted=1">가져온 원본 보기</a><a class="btn ghost" href="#inventory">원본 상품</a></div></header>
      <section class="card pad">
        <p style="margin:0 0 6px">다른 방법으로 <b>이미 스토어에 올린 상품</b>을 이 프로그램으로 가져옵니다. 그 스토어에 <b>업로드했던 셀업 엑셀</b>을 넣으면
          네이버 상품 목록과 <b>판매자코드</b>로 맞춰서:</p>
        <ul class="small" style="margin:0;padding-left:18px;line-height:1.7">
          <li>스토어에 있는 상품 → <b>원본</b>(엑셀 내용, 고른 공통 이미지(스토어 상단·하단 배너 등)는 빼고) + 그 스토어의 <b>판매 중 복사본</b>. 내리기·최신화·다른 스토어로 복사가 똑같이 됩니다.</li>
          <li><b>순서</b>: 파일 올리기 → 스토어·뺄 공통 이미지 고르기 → <b>[맞춰 보기]</b>(아무것도 안 바뀜 — 연결될 수·버릴 수·예시 확인) → <b>[이대로 가져오기]</b>. 잘못 가져왔으면 기록의 <b>[가져오기 되돌리기]</b>(이 프로그램에서만 빼기 — 네이버 상품은 그대로).</li>
          <li>새로 생기는 원본의 <b>기준 구매가 = 그 스토어의 지금 손님 가격</b>(엑셀 판매가가 아님 — 따로 건 할인까지 반영). 복사본은 <b>최신화 때도 손님 가격 그대로</b>(가격 고정 — 최신화 직전에 네이버에서 다시 읽음, 옵션 추가금도), 다른 스토어로 복사할 때는 기준 구매가 × 받는 스토어 마진율.</li>
          <li>원본에는 <b>'가져옴 · 원본 이름 없음'</b> 표시 (올라가 있던 이름이 원본 자리). 원본 기준은 원본 엑셀과 같은 <b>상품명(완전히 같음)</b>: 같은 상품명의 원본이 이미 있으면 <b>그 원본에 연결</b>하고 그 원본(원본 이름·AI 키워드·상세·<b>기준 구매가</b>)은 그대로 둡니다('가져옴' 표시만, 고른 공통 이미지는 뺌).</li>
          <li><b>상품명 중복</b>: 한 스토어에 상품명이 완전히 같은 상품이 둘 이상이면 <b>앞 상품만 연결</b>하고 나머지는 '상품명 중복' 목록으로 알려 드립니다(네이버 상품은 그대로).</li>
          <li><b>판매 이력</b>: 모든 판매 중 상품(가져온 것 포함)은 판매 이력을 확인해야 최신화·내리기를 합니다(팔린 상품을 지우지 않게). 아래 기록의 <b>[판매 이력 확인]</b> — 판매자센터 주문 파일을 넣거나 팔린 것을 직접 잠근 뒤 '판매 이력 확인 완료'. 그 뒤로는 최신화할 때마다 새 기간만 받아 잠급니다.</li>
          <li>브랜드·제조사·모델명·원산지는 '상세페이지 참조'로 바꿔 둡니다 (올릴 때 스토어에 맞게 들어감).</li>
          <li>엑셀에는 있는데 <b>스토어에서 지운 상품은 버립니다</b> — 그 원본이 다른 경로로 이미 들어와 있으면 <b>[원본까지 삭제]</b>로 지웁니다. 스토어에는 있는데 엑셀에 없는 상품은 가져오지 않고 <b>목록으로 알려 드립니다</b>(아래 기록에서 엑셀로 받기).</li>
        </ul></section>
      <section class="card pad">
        <div class="sec-head"><h2>1. 업로드했던 엑셀 올리기</h2><span class="muted small">파일 하나 = 스토어 하나</span></div>
        <label class="dropzone cl-drop"><input type="file" id="ad-file" accept=".xlsx,.xlsm,.csv" hidden><b>업로드했던 셀업 엑셀을 이 화면에 끌어다 놓기</b><span class="muted small">또는 여기를 눌러 파일 고르기</span></label>
        <div id="ad-prep"></div></section>
      <section class="card pad"><div class="sec-head"><h2>가져온 기록</h2><span class="muted small">목록은 엑셀(CSV)로 받을 수 있습니다</span></div>
        <div id="ad-runs"></div></section>
    </div>`;
    $("#ad-file").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) this.prepare(f); });
    this.onDone = (t) => {
      if (t.kind === "adopt") { this.loadRuns(); if (t.status === "done") $("#ad-prep").innerHTML = ""; }
      if (t.kind === "adopt_check" && this.d && t.result?.token === this.d.token) {
        if (t.status === "done") this.renderResult(t.result);
        else $("#ad-result").innerHTML = `<div class="notice err">맞춰 보지 못했습니다: ${esc(t.error || "")}</div>`;
      }
    };
    App.on("task-done", this.onDone);
    await this.loadRuns();
  },
  unmount() { App.off("task-done", this.onDone); },
  onFile(f) { this.prepare(f); },

  async prepare(file) {
    const box = $("#ad-prep");
    box.innerHTML = `<p class="muted"><span class="spin"></span> ${esc(file.name)} 읽는 중… (상품이 많으면 몇십 초)</p>`;
    let d;
    try {
      const fd = new FormData();
      fd.append("file", file);
      d = await App.api("/api/adopt/prepare", { method: "POST", body: fd });
    } catch (e) { box.innerHTML = `<p class="c-err">${esc(e.message)}</p>`; return; }
    this.d = d;
    this.checked = null;
    const stores = await App.loadStores();
    this.stores = stores;
    const cm = d.common || { total: 0, images: [] };
    box.innerHTML = `<div class="ad-prep">
      <p><b>${esc(d.file)}</b> · 상품 <b>${num(d.rows)}</b>개 · 판매자코드 예 <code>${esc(d.code_example)}</code>
        ${d.no_code ? ` · <span class="c-warn">판매자코드 없는 줄 ${num(d.no_code)}개 (맞출 수 없어 뺌)</span>` : ""}${d.dup_code ? ` · <span class="c-warn">판매자코드 겹침 ${num(d.dup_code)}개</span>` : ""}</p>
      <label class="field">이 파일을 올렸던 스토어 <span class="muted">(브랜드 '${esc(d.brand)}'로 짐작${d.guess_store ? "" : " — 못 찾음, 직접 고르세요"})</span>
        <select id="ad-store" class="sel"><option value="">— 스토어 고르기 —</option>${byBusiness(stores).map(([biz, ss]) => `<optgroup label="${esc(biz)}">${ss.map((x) =>
          `<option value="${x.id}" ${x.id === d.guess_store ? "selected" : ""}>${esc(x.name)}${x.has_keys ? "" : " (API 키 없음)"}</option>`).join("")}</optgroup>`).join("")}</select></label>
      <div class="sec-head" style="margin-top:12px"><h3 style="margin:0">뺄 공통 이미지 (스토어 상단·하단·안내 배너)</h3>
        <span class="muted small">상세가 있는 상품 ${num(cm.total)}개 중 ${num(10)}개 이상에 똑같이 들어 있는 이미지 <b>${num(cm.images.length)}종</b>${cm.more ? ` (더 있음 ${num(cm.more)})` : ""} — 많이 들어 있는 것은 미리 골라 둠</span></div>
      ${cm.images.length ? `<div class="cl-imgs" id="ad-imgs">${cm.images.map((x) => `<label class="cl-img"><input type="checkbox" data-src="${esc(x.src)}" ${x.pick ? "checked" : ""}>
          <img src="${esc(x.src)}" referrerpolicy="no-referrer" loading="lazy" alt="" onerror="onImgError(this)">
          <span><b>${num(x.count)}개</b> 상품 · ${esc(x.pos)}${x.remembered ? ' <span class="flag">기억함</span>' : ""}</span></label>`).join("")}</div>
        <div class="cl-row" style="margin-top:6px"><button class="btn sm" data-all-img="1">전부 선택</button><button class="btn sm" data-all-img="0">전부 해제</button>
          <span class="muted small" id="ad-imgs-n"></span></div>` : '<p class="muted small">여러 상품에 똑같이 들어 있는 이미지가 없습니다.</p>'}
      <label class="check" style="margin-top:8px"><input type="checkbox" id="ad-eye" checked><span><b>가져온 원본을 검수 완료로 표시</b> <span class="muted small">(이미 올려 둔 상품이라 — 끄면 미검수로 들어가 눈검수 대상)</span></span></label>
      <div class="cl-row" style="margin-top:10px"><button class="btn primary big" id="ad-check">맞춰 보기 (아직 안 가져옴)</button>
        <span class="muted small">네이버에서 그 스토어 상품 목록을 받아(스토어당 몇 분) 판매자코드로 맞춰 보고 결과·예시를 보여 줍니다. <b>아무것도 바꾸지 않습니다.</b> 결과를 보고 가져오기를 누르세요.</span></div>
      <div id="ad-result"></div></div>`;
    const cnt = () => { const n = $$("#ad-imgs [data-src]:checked").length; const el = $("#ad-imgs-n"); if (el) el.textContent = `고른 이미지 ${num(n)}종 — 모든 상품 상세에서 뺍니다`; };
    cnt();
    $$("[data-all-img]", box).forEach((b) => b.addEventListener("click", () => { $$("#ad-imgs [data-src]").forEach((c) => { c.checked = b.dataset.allImg === "1"; }); cnt(); this.staleResult(); }));
    $("#ad-imgs")?.addEventListener("change", () => { cnt(); this.staleResult(); });
    $("#ad-store").addEventListener("change", () => this.staleResult());
    $("#ad-eye").addEventListener("change", () => this.staleResult());
    $("#ad-check").addEventListener("click", async () => {
      const store_id = +$("#ad-store").value;
      if (!store_id) return App.toast("이 파일을 올렸던 스토어를 고르세요.", true);
      const opts = this.opts();
      $("#ad-result").innerHTML = `<p class="muted"><span class="spin"></span> 맞춰 보는 중… (네이버 상품 목록을 받는 중 — 오른쪽 아래에서 진행을 봅니다)</p>`;
      const r = await App.startTask(App.api("/api/adopt/check", { json: { token: d.token, store_id, ...opts } }));
      if (r) this.checked = { store_id, key: JSON.stringify(opts) };
      else $("#ad-result").innerHTML = "";
    });
  },

  opts() {
    return { remove_imgs: $$("#ad-imgs [data-src]:checked").map((c) => c.dataset.src), mark_eye: $("#ad-eye").checked };
  },
  staleResult() {   // 스토어·이미지·검수 설정을 바꾸면 맞춰 본 결과는 다시
    if ($("#ad-result")?.innerHTML && this.checked) {
      $("#ad-result").innerHTML = '<p class="small c-warn">설정을 바꿨습니다 — 다시 [맞춰 보기]를 누르세요.</p>';
      this.checked = null;
    }
  },

  renderResult(r) {
    const box = $("#ad-result");
    if (!box) return;
    const pct = Math.round((r.match_rate || 0) * 1000) / 10;
    const low = (r.match_rate || 0) < 0.5;
    const s = r.samples || {};
    const tile = (label, n, cls = "") => `<div class="ad-tile ${cls}"><div class="small muted">${label}</div><b>${num(n || 0)}</b></div>`;
    const stx = (x) => NAVER_STATUS[x] || x || "";
    box.innerHTML = `<div class="ad-result">
      <h3 style="margin:14px 0 6px">맞춰 본 결과 — ${esc(r.store)} · ${esc(r.file)} <span class="muted small">(아직 아무것도 안 바뀜)</span></h3>
      <div class="notice ${low ? "err" : "ok"}">${low ? `판매자코드가 스토어 상품과 맞는 줄이 <b>${pct}%</b>뿐입니다 — <b>이 스토어에 올렸던 파일이 맞는지</b> 확인하세요.`
        : `판매자코드가 스토어 상품과 맞는 줄 <b>${pct}%</b> (스토어 상품 ${num(r.store_products)}개)`}</div>
      <div class="ad-tiles">${tile("새로 연결 (원본 + 판매 중 복사본)", r.linked, "ok")}${tile("이미 연결돼 있음", r.already)}${tile("스토어에 없어 뺌", (r.dropped || 0) + (r.no_code || 0), "warn")}
        ${tile("└ 그중 원본에 있음 (가져온 뒤 원본까지 삭제 가능)", r.dropped_src, r.dropped_src ? "warn" : "")}${tile("스토어에만 있음 (안 가져옴)", r.store_only)}
        ${tile("엑셀≠손님 가격 (손님 가격으로)", r.price_diff)}${tile("상품명 중복 (앞 상품만 연결)", r.name_dup, r.name_dup ? "warn" : "")}${r.dup_same ? tile("연결 못 함 (알려 주세요)", r.dup_same, "warn") : ""}</div>
      <p class="small">공통 이미지 <b>${num(r.img_kinds)}</b>종 → 상품 <b>${num(r.img_items)}</b>개에서 <b>${num(r.img_removed)}</b>장 뺌${r.existing ? ` · 상품명이 같은 원본이 이미 있어 그 원본에 연결 ${num(r.existing)}개 (내용·기준 구매가 그대로)` : ""}
        ${r.linked ? ` · 연결될 상품 상태: ${Object.entries(r.status || {}).map(([k, v]) => `${stx(k)} ${num(v)}`).join(" · ")}` : ""}</p>
      ${s.linked?.length ? `<p class="small"><b>연결될 상품 예</b> (엑셀 상품명과 스토어 상품명이 같은 상품인지 확인)</p>
        <div class="tbl-wrap"><table class="grid small"><thead><tr><th>판매자코드</th><th>엑셀 상품명</th><th>스토어 상품명</th><th class="num">손님 가격</th><th>상태</th></tr></thead>
        <tbody>${s.linked.map((x) => `<tr><td><code>${esc(x.code)}</code></td><td>${esc(x.xl_name)}</td><td>${esc(x.name)}</td><td class="num">${num(x.final)}</td><td>${esc(stx(x.status))}</td></tr>`).join("")}</tbody></table></div>` : ""}
      ${s.name_dup?.length ? `<p class="small"><b>상품명 중복 예</b> (연결 안 함 — 네이버 상품은 그대로)</p><ul class="small">${s.name_dup.map((x) => `<li><code>${esc(x.code || "-")}</code> ${esc(x.name)} <span class="muted">— ${esc(x.why)}</span></li>`).join("")}</ul>` : ""}
      ${s.dropped?.length ? `<p class="small"><b>스토어에 없어 뺄 상품 예</b></p><ul class="small">${s.dropped.map((x) => `<li><code>${esc(x.code)}</code> ${esc(x.name)}${x.src ? ' <span class="flag warn">원본에 있음</span>' : ""}</li>`).join("")}</ul>` : ""}
      ${s.price_diff?.length ? `<p class="small"><b>엑셀 판매가 → 스토어 손님 가격 예</b></p><ul class="small">${s.price_diff.map((x) => `<li><code>${esc(x.code)}</code> ${esc(x.name)} — ${num(x.xl)}원 → <b>${num(x.final)}원</b></li>`).join("")}</ul>` : ""}
      ${s.store_only?.length ? `<p class="small"><b>스토어에만 있는 상품 예</b> (가져오지 않음)</p><ul class="small">${s.store_only.map((x) => `<li><code>${esc(x.code || "-")}</code> ${esc(x.name)} · ${esc(stx(x.status))}</li>`).join("")}</ul>` : ""}
      <div class="cl-row" style="margin-top:10px"><button class="btn primary big" id="ad-go" ${r.linked ? "" : "disabled"}>이대로 가져오기 (새로 연결 ${num(r.linked)}개)</button>
        <span class="muted small">스토어·이미지·검수 설정을 바꾸면 다시 맞춰 봐야 합니다.</span></div></div>`;
    $("#ad-go").addEventListener("click", async () => {
      const store_id = +$("#ad-store").value;
      const opts = this.opts();
      if (!this.checked || this.checked.store_id !== store_id || this.checked.key !== JSON.stringify(opts)) return this.staleResult();
      if (low && !confirm(`판매자코드가 맞는 줄이 ${pct}%뿐입니다.\n정말 '${r.store}' 스토어에 올렸던 파일이 맞나요?`)) return;
      if (!confirm(`'${r.file}' → '${r.store}'\n\n새로 연결 ${num(r.linked)}개(원본 + 판매 중 복사본), 스토어에 없는 ${num((r.dropped || 0) + (r.no_code || 0))}줄은 버립니다.\n가져올까요? (잘못 가져오면 기록의 [가져오기 되돌리기]로 이 프로그램에서만 뺄 수 있음 — 네이버 상품은 그대로)`)) return;
      const t = await App.startTask(App.api("/api/adopt/start", { json: { token: this.d.token, store_id, ...opts } }));
      if (t) { $("#ad-prep").innerHTML = `<p class="muted"><span class="spin"></span> 가져오는 중… 오른쪽 아래에서 진행을 볼 수 있습니다. 끝나면 아래 기록에 나옵니다.</p>`; }
    });
  },

  async undo(rid) {
    let pv;
    try { pv = await App.api(`/api/adopt/${rid}/undo`); } catch (e) { return App.toast(e.message, true); }
    const ok = await App.confirmDanger({
      title: `가져오기 되돌리기 — ${pv.store}`,
      body: `<p>이 가져오기로 연결한 <b>판매 중 복사본 ${num(pv.listings)}개</b>와, 이 가져오기로 새로 생긴 <b>원본 ${num(pv.sources)}개</b>를 <b>이 프로그램에서만</b> 빼서 휴지통으로 옮깁니다.</p>
        <ul><li><b>네이버 상품은 그대로</b> 둡니다 (내리지 않음).</li>
          ${pv.kept_sources ? `<li>예전부터 있던 원본 ${num(pv.kept_sources)}개는 남기고 '가져옴' 표시만 지웁니다.</li>` : ""}
          <li>파일을 고쳐서 다시 가져오면 됩니다. 휴지통에서 되살릴 수도 있습니다.</li></ul>`,
      ok: "되돌립니다",
    });
    if (!ok) return;
    try {
      const r = await App.api(`/api/adopt/${rid}/undo`, { json: {} });
      App.toast(`되돌렸습니다: 복사본 ${num(r.listings)}개 · 원본 ${num(r.sources)}개 휴지통으로 (네이버 상품은 그대로)` + (r.skipped ? ` · 처리 중이라 남긴 ${num(r.skipped)}개` : ""));
      this.loadRuns(); App.refreshState();
    } catch (e) { App.toast(e.message, true); }
  },

  async loadRuns() {
    const rs = await App.api("/api/adopt/runs");
    const box = $("#ad-runs");
    if (!box) return;
    box.onclick = async (e) => {
      const d = e.target.closest("[data-drop]");
      if (d) {   // 스토어에서 지운(문제 있어 지운) 상품의 원본 → 원본과 모든 스토어 복사본 삭제 (판매 이력·잠금은 남김)
        const r = await App.api(`/api/adopt/${d.dataset.drop}/drop_sources`);
        if (!r.ids.length) return App.toast("지울 원본이 없습니다 (이미 지웠거나, 지금 그 스토어에 판매 중).");
        return App.chemDelete({ ids: r.ids }, () => this.loadRuns());
      }
      const u = e.target.closest("[data-undo]");
      if (u) return this.undo(+u.dataset.undo);
      const sb = e.target.closest("[data-sales]");
      if (sb) return App.salesConfirm(+sb.dataset.sales, () => this.loadRuns());
      const o = e.target.closest("[data-orders]");
      if (o) {
        if (!confirm(`이 스토어 주문을 ${o.dataset.from}부터 오늘까지 받습니다.\n네이버는 하루 단위로 나눠 조회해서 기간이 길면 시간이 걸립니다(뒤에서 돌아감).\n다 받으면 가져온 상품을 최신화·내리기할 수 있습니다 (팔린 상품은 잠겨서 안 지움).`)) return;
        App.startTask(App.api("/api/orders/sync", { json: { from: o.dataset.from, store_ids: [+o.dataset.orders] } }));
      }
    };
    if (!rs.length) { box.innerHTML = '<p class="muted">아직 가져온 기록이 없습니다.</p>'; return; }
    const st = (s) => Object.entries(s.status || {}).map(([k, v]) => `${NAVER_STATUS[k] || k} ${num(v)}`).join(" · ");
    box.innerHTML = `<table class="grid"><thead><tr><th>#</th><th>시각</th><th>스토어 · 파일</th><th class="num">파일 상품</th>
      ${ADOPT_KINDS.map(([, l]) => `<th class="num">${l}</th>`).join("")}<th class="num">공통 이미지 뺀 상품</th></tr></thead><tbody>
      ${rs.map((r) => { const s = r.stats || {}; return `<tr><td>${r.id}</td><td class="nowrap">${when(r.created_at)}</td>
        <td><b>${esc(r.store_name)}</b><div class="small muted">${esc(r.file_name)}</div>
          ${r.status === "running" ? '<span class="badge s-running">가져오는 중</span>' : r.status === "error" ? `<span class="badge s-fail">오류</span> <span class="small c-err">${esc(s.error || "")}</span>`
            : r.status === "undone" ? `<span class="badge">되돌림</span> <span class="small muted">${when(s.undone_at)} · 복사본 ${num(s.undone?.listings || 0)} · 원본 ${num(s.undone?.sources || 0)} 휴지통으로 (네이버 상품은 그대로)</span>`
            : r.status === "done" ? `<button class="btn tiny ghost" data-undo="${r.id}" title="이 가져오기로 연결한 복사본과 새로 생긴 원본을 이 프로그램에서만 뺌 — 네이버 상품은 그대로">가져오기 되돌리기</button>` : ""}
          ${s.linked ? `<div class="small muted">연결된 것: ${esc(st(s))}${s.managed ? ` · 이 프로그램이 올린 상품 ${num(s.managed)}개는 그대로` : ""}</div>` : ""}
          ${s.existing ? `<div class="small muted">상품명이 같은 원본 ${num(s.existing)}개에 연결 (내용·기준 구매가 그대로)</div>` : ""}
          ${s.dropped_src ? `<div class="small"><span class="c-warn">스토어에서 지운 상품의 원본 ${num(s.dropped_src)}개</span> <button class="btn tiny danger" data-drop="${r.id}">원본까지 삭제</button></div>` : ""}
          ${r.sales && r.sales.adopted ? (r.sales.need
            ? `<div class="small"><span class="c-warn">판매 이력 확인 전 ${num(r.sales.need)}개 — 최신화·내리기 안 함</span>
              <button class="btn tiny primary" data-sales="${r.store_id}">판매 이력 확인</button></div>`
            : `<div class="small c-ok">판매 이력 확인됨 (${ymdOf(r.sales.known_from)}부터) <button class="btn tiny ghost" data-sales="${r.store_id}">보기</button></div>`) : ""}</td>
        <td class="num">${num(s.rows || 0)}</td>
        ${ADOPT_KINDS.map(([k]) => `<td class="num">${s[k] ? `<a href="/api/adopt/${r.id}/items.csv?kind=${k}" title="엑셀(CSV)로 받기">${num(s[k])} ⬇</a>` : (r.status === "done" ? "0" : "")}</td>`).join("")}
        <td class="num">${s.img_items !== undefined ? `${num(s.img_items)} (${num(s.img_removed || 0)}장)` : s.top_removed !== undefined ? `상단 ${num(s.top_removed || 0)} · 하단 ${num(s.bottom_removed || 0)}` : ""}</td></tr>`; }).join("")}
      </tbody></table>
      <p class="small muted" style="margin:8px 0 0">숫자를 누르면 그 목록을 엑셀(CSV)로 받습니다. '엑셀≠손님 가격'은 엑셀 판매가와 스토어 손님 가격이 다른 상품(스토어 손님 가격으로 넣음), '상품명 중복'은 상품명이 완전히 같은 상품이 이 스토어에 또 있어 연결하지 않은 상품(앞 상품만 연결). '스토어에만 있음'은 그 스토어에 올라가 있지만 이 파일에 없는 상품(가져오지 않음). 스토어 상품과는 판매자코드로 <b>1대1</b>로 연결하고, 원본 기준은 <b>상품명(완전히 같음)</b>입니다 — 대표 사진(이미지 주소)은 기준이 아닙니다.</p>`;
  },
});
