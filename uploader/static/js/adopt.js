/* 기존 상품 가져오기: 다른 방법으로 이미 올린 상품 → 업로드했던 셀업 엑셀 + 그 스토어 상품 목록(판매자코드로 맞춤)
   → 원본 + 그 스토어의 판매 중 복사본. 스토어에서 지운 상품은 버리고, 스토어에만 있는 상품은 목록으로 알려 줌. */
"use strict";

const ADOPT_KINDS = [["linked", "연결"], ["already", "이미 연결"], ["dropped", "스토어에 없어 뺌"], ["store_only", "스토어에만 있음"],
  ["dup_same", "같은 스토어 중복"], ["dup", "같은 사진 다른 스토어"], ["price_diff", "엑셀≠손님 가격"], ["mobile_disc", "모바일 할인"]];
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
          <li>스토어에 있는 상품 → <b>원본</b>(엑셀 내용, 스토어 상하단은 빼고) + 그 스토어의 <b>판매 중 복사본</b>. 내리기·최신화·다른 스토어로 복사가 똑같이 됩니다.</li>
          <li><b>원본가 = 그 스토어의 지금 손님 가격</b>(엑셀 판매가가 아님 — 따로 건 할인까지 반영). 복사본은 <b>최신화 때도 손님 가격 그대로</b>(가격 고정 — 최신화 직전에 네이버에서 다시 읽음, 옵션 추가금도), 다른 스토어로 복사할 때는 이 원본가에 받는 스토어 템플릿 적용.</li>
          <li>원본에는 <b>'가져옴 · 원본 이름 없음'</b> 표시 (올라가 있던 이름이 원본 자리). 대표 사진이 같은 원본이 이미 있으면 <b>그 원본(원본 이름·AI 키워드·상세)은 그대로</b> 두고 원본가만 바꿉니다('가져옴').</li>
          <li><b>판매 이력</b>: 가져온 상품은 판매 이력을 확인해야 최신화·내리기를 합니다(팔린 상품을 지우지 않게). 아래 기록의 <b>[판매 이력 확인]</b> — 판매자센터 주문 파일을 넣거나 팔린 것을 직접 잠근 뒤 '판매 이력 확인 완료'. 그 뒤로는 최신화할 때마다 새 기간만 받아 잠급니다.</li>
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
    this.onDone = (t) => { if (t.kind === "adopt") { this.loadRuns(); if (t.status === "done") $("#ad-prep").innerHTML = ""; } };
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
    const stores = await App.loadStores();
    const imgs = (a) => a.map((u) => `<img src="${esc(u)}" referrerpolicy="no-referrer" loading="lazy" alt="" onerror="onImgError(this)">`).join("");
    box.innerHTML = `<div class="ad-prep">
      <p><b>${esc(d.file)}</b> · 상품 <b>${num(d.rows)}</b>개 · 판매자코드 예 <code>${esc(d.code_example)}</code>
        ${d.no_code ? ` · <span class="c-warn">판매자코드 없는 줄 ${num(d.no_code)}개 (맞출 수 없어 뺌)</span>` : ""}${d.dup_code ? ` · <span class="c-warn">판매자코드 겹침 ${num(d.dup_code)}개</span>` : ""}</p>
      <label class="field">이 파일을 올렸던 스토어 <span class="muted">(브랜드 '${esc(d.brand)}'로 짐작${d.guess_store ? "" : " — 못 찾음, 직접 고르세요"})</span>
        <select id="ad-store" class="sel"><option value="">— 스토어 고르기 —</option>${byBusiness(stores).map(([biz, ss]) => `<optgroup label="${esc(biz)}">${ss.map((s) =>
          `<option value="${s.id}" ${s.id === d.guess_store ? "selected" : ""}>${esc(s.name)}${s.has_keys ? "" : " (API 키 없음)"}</option>`).join("")}</optgroup>`).join("")}</select></label>
      <div class="ad-edges">
        <div><label class="check"><input type="checkbox" id="ad-top" ${d.top ? "checked" : "disabled"}><span><b>스토어 상단 빼기</b> ${d.top ? `· ${num(d.n_top)}개 상품에 똑같이 들어 있음` : "· 똑같은 상단을 찾지 못함"}</span></label>
          <div class="ad-imgs">${imgs(d.top_imgs || [])}</div></div>
        <div><label class="check"><input type="checkbox" id="ad-bottom" ${d.bottom ? "checked" : "disabled"}><span><b>스토어 하단 빼기</b> ${d.bottom ? `· ${num(d.n_bottom)}개 상품에 똑같이 들어 있음` : "· 똑같은 하단을 찾지 못함"}</span></label>
          <div class="ad-imgs">${imgs(d.bottom_imgs || [])}</div></div>
      </div>
      <label class="check"><input type="checkbox" id="ad-eye" checked><span><b>가져온 원본을 검수 완료로 표시</b> <span class="muted small">(이미 올려 둔 상품이라 — 끄면 미검수로 들어가 눈검수 대상)</span></span></label>
      <div class="cl-row" style="margin-top:10px"><button class="btn primary big" id="ad-go">가져오기 시작</button>
        <span class="muted small">네이버에서 그 스토어 상품 목록을 받아(스토어당 몇 분) 판매자코드로 맞춥니다. 뒤에서 돌고, 오른쪽 아래에서 진행을 봅니다.</span></div></div>`;
    $("#ad-go").addEventListener("click", async () => {
      const store_id = +$("#ad-store").value;
      if (!store_id) return App.toast("이 파일을 올렸던 스토어를 고르세요.", true);
      const s = stores.find((x) => x.id === store_id);
      if (!confirm(`'${d.file}'을(를) '${s.name}' 스토어 상품과 맞춰 가져올까요?\n\n스토어에 있는 상품만 원본 + 판매 중 복사본으로 연결하고, 스토어에 없는 줄은 버립니다.`)) return;
      const r = await App.startTask(App.api("/api/adopt/start", { json: { token: d.token, store_id, strip_top: $("#ad-top").checked,
        strip_bottom: $("#ad-bottom").checked, mark_eye: $("#ad-eye").checked } }));
      if (r) { $("#ad-prep").innerHTML = `<p class="muted"><span class="spin"></span> 가져오는 중… 오른쪽 아래에서 진행을 볼 수 있습니다. 끝나면 아래 기록에 나옵니다.</p>`; }
    });
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
      ${ADOPT_KINDS.map(([, l]) => `<th class="num">${l}</th>`).join("")}<th class="num">상하단 뺀 상품</th></tr></thead><tbody>
      ${rs.map((r) => { const s = r.stats || {}; return `<tr><td>${r.id}</td><td class="nowrap">${when(r.created_at)}</td>
        <td><b>${esc(r.store_name)}</b><div class="small muted">${esc(r.file_name)}</div>
          ${r.status === "running" ? '<span class="badge s-running">가져오는 중</span>' : r.status === "error" ? `<span class="badge s-fail">오류</span> <span class="small c-err">${esc(s.error || "")}</span>` : ""}
          ${s.linked ? `<div class="small muted">연결된 것: ${esc(st(s))}${s.managed ? ` · 이 프로그램이 올린 상품 ${num(s.managed)}개는 그대로` : ""}</div>` : ""}
          ${s.existing ? `<div class="small muted">이미 있던 원본 ${num(s.existing)}개는 내용 그대로(원본가만 손님 가격으로)</div>` : ""}
          ${s.dropped_src ? `<div class="small"><span class="c-warn">스토어에서 지운 상품의 원본 ${num(s.dropped_src)}개</span> <button class="btn tiny danger" data-drop="${r.id}">원본까지 삭제</button></div>` : ""}
          ${r.sales && r.sales.adopted ? (r.sales.need
            ? `<div class="small"><span class="c-warn">판매 이력 확인 전 ${num(r.sales.need)}개 — 최신화·내리기 안 함</span>
              <button class="btn tiny primary" data-sales="${r.store_id}">판매 이력 확인</button></div>`
            : `<div class="small c-ok">판매 이력 확인됨 (${ymdOf(r.sales.known_from)}부터) <button class="btn tiny ghost" data-sales="${r.store_id}">보기</button></div>`) : ""}</td>
        <td class="num">${num(s.rows || 0)}</td>
        ${ADOPT_KINDS.map(([k]) => `<td class="num">${s[k] ? `<a href="/api/adopt/${r.id}/items.csv?kind=${k}" title="엑셀(CSV)로 받기">${num(s[k])} ⬇</a>` : (r.status === "done" ? "0" : "")}</td>`).join("")}
        <td class="num">${r.status === "done" ? `상단 ${num(s.top_removed || 0)} · 하단 ${num(s.bottom_removed || 0)}` : ""}</td></tr>`; }).join("")}
      </tbody></table>
      <p class="small muted" style="margin:8px 0 0">숫자를 누르면 그 목록을 엑셀(CSV)로 받습니다. '엑셀≠손님 가격'은 엑셀 판매가와 스토어 손님 가격이 다른 상품(스토어 손님 가격으로 넣음), '모바일 할인'은 모바일에서만 더 싼 상품(최신화하면 모바일 할인이 사라짐). '스토어에만 있음'은 그 스토어에 올라가 있지만 이 파일에 없는 상품(가져오지 않음), <b>'같은 스토어 중복'</b>은 대표 사진이 같은 상품을 그 스토어에 두 번 올린 것(먼저 것만 연결 — 나머지는 스토어에서 지우세요), '같은 사진 다른 스토어'는 대표 사진이 같은 원본이 다른 스토어에도 올라가 있는 것(한 상품은 한 스토어에만 — 하나 지우세요).</p>`;
  },
});
