/* 상세 정리: 셀업 엑셀 → 정리함 → 단계별 정리 → 원본 상품으로 넣기 (진시크릿 상세정리 도구를 이 프로그램 안으로).
   위에서 아래로 단계 카드: ① 올리기 ② 공통 이미지 ③ 전화번호 ④ 상세 편집 ⑤ 잘린·빈 상세 ⑥ 빈 칸 ⑦ 카테고리·생활화학 ⑧ 마무리 */
"use strict";

const CAT_STATUS = {
  ok: ["정상", "s-success"], mapped: ["맞춰 둔 것", "s-success"], mid: ["중간 분류 (최하단 아님)", "s-fail"], missing: ["목록에 없음 (폐지·오타)", "s-fail"],
  format: ["형식 이상", "s-fail"], empty: ["빈 칸", "s-fail"], unknown: ["카테고리 목록 없음", "s-planned"],
};

function cleanSafe(html) {   // 미리보기에 넣기 전: 스크립트·이벤트 속성 빼기
  return String(html || "").replace(/<script\b[\s\S]*?<\/script>/gi, "").replace(/\son[a-z]+\s*=\s*(["']).*?\1/gi, "");
}

App.page("clean", {
  bid: null,

  async mount(el) {
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>상세 정리</h1>
        <div class="head-actions"><select id="cl-batch" class="sel" title="정리함 묶음 (올린 엑셀마다 하나)"></select></div></header>
      <p class="muted small" style="margin:0">셀업 엑셀을 올려 정리한 뒤 <b>원본 상품으로 넣기</b>를 누르면 원본이 됩니다 → 이어서 상품명 변경 → 복사·등록.
        정리하는 동안은 원본에 들어가지 않습니다. 방문 알림·http 동영상 빼기, PC 폭 맞추기, 옵션표 2열 그림은 올릴 때 자동으로 합니다.</p>
      <section class="card pad cl-step"><div class="sec-head"><h2><span class="cl-n">1</span> 엑셀 올리기</h2></div>
        <label class="dropzone cl-drop"><input type="file" id="cl-file" accept=".xlsx,.xls,.csv" hidden><b>셀업 엑셀(.xlsx)을 이 화면에 끌어다 놓기</b><span class="muted small">또는 여기를 눌러 파일 고르기</span></label>
        <div class="cl-row small" style="margin-top:8px">올릴 때 자동으로:
          <label class="check"><input type="checkbox" id="cl-o-price" checked><span>가격을 <b>고객 결제가 한 칸</b>으로 (판매가 − 할인가, 할인가 비움)</span></label>
          <label class="check"><input type="checkbox" id="cl-o-code" checked><span>상품코드(판매자코드) 비우기</span></label>
          <label class="check"><input type="checkbox" id="cl-o-info" checked><span>브랜드·제조사·모델명·원산지 '상세페이지 참조'</span></label></div>
        <div class="small" style="margin-top:8px">${App.tagFields("cl", { value: ymdToday() })}</div>
        <div class="tiles" id="cl-sum" style="margin-top:12px"></div>
        <div id="cl-btags" class="cl-btags small"></div></section>
      <div id="cl-steps"></div>
    </div>`;
    $("#cl-file").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) this.upload(f); });
    App.bindTagFields("cl");
    $("#cl-batch").addEventListener("change", (e) => { this.bid = +e.target.value || null; this.renderSteps(); this.refresh(); });
    $("#cl-sum").addEventListener("click", (e) => { if (e.target.closest("[data-filter=deleted]")) this.showDeleted(); });
    this.onDone = (t) => {
      if (t.kind === "clean_import" && t.result?.batch_id) { this.bid = t.result.batch_id; this.loadBatches().then(() => { this.renderSteps(); this.refresh(); }); }
      if (t.kind === "clean_chem") { this.refresh(); this.loadHold(); this.checkCats(); }
      if (t.kind === "clean_send") this.refresh();
    };
    App.on("task-done", this.onDone);
    await this.loadBatches();
    this.renderSteps();
    await this.refresh();
  },
  unmount() { if (this.onDone) App.off("task-done", this.onDone); },
  onFile(f) { this.upload(f); },   // 이 화면에서 끌어다 놓은 파일은 정리함으로 (다른 화면은 '무엇으로 불러올까요?')

  async loadBatches() {
    const bs = await App.api("/api/clean/batches");
    if (!this.bid && bs.length) this.bid = bs[0].id;
    $("#cl-batch").innerHTML = bs.length ? bs.map((b) => `<option value="${b.id}" ${b.id === this.bid ? "selected" : ""}>#${b.id} ${esc(b.file_name)} · ${when(b.created_at)} · 정리 중 ${num(b.new)}</option>`).join("")
      : '<option value="">정리함이 비었습니다 — 엑셀을 올리세요</option>';
  },

  async upload(file) {
    const extra = {};
    for (const k of ["price", "code", "info"]) extra[k] = $(`#cl-o-${k}`).checked ? "1" : "0";
    Object.assign(extra, App.tagValues("cl"));
    const fd = new FormData();
    fd.append("file", file);
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
    await App.sendChecked("/api/clean/import", fd, extra);   // 가격 칸이 이상하면 경고 → 확인하면 진행
  },

  async refresh() {
    if (!this.bid) { $("#cl-sum").innerHTML = ""; return; }
    const b = await App.api(`/api/clean/${this.bid}`);
    this.counts = b.counts;
    $("#cl-sum").innerHTML = tilesHtml([
      { key: "new", label: "정리 중 (원본으로 넣을 것)", dot: "var(--info)" }, { key: "hold", label: "생활화학 보류", dot: "var(--err)" },
      { key: "edited", label: "고친 상품", dot: "var(--accent)" }, { key: "deleted", label: "지움 (눌러서 되살리기)", dot: "var(--muted)" },
      { key: "sent", label: "원본으로 넣음", dot: "var(--ok)" },
    ], b.counts, "") + `<div class="small muted" style="grid-column:1/-1">${esc(b.file_name)} · ${esc(b.note || "")}</div>`;
    const s = $("#cl-send-n");
    if (s) s.textContent = num(b.counts.new);
  },

  /* 이 묶음의 출처 태그 (원본으로 넣을 때 붙음) */
  async loadTags() {
    const box = $("#cl-btags");
    if (!this.bid) { box.innerHTML = ""; return; }
    const t = await App.api(`/api/clean/${this.bid}/tags`);
    const st = t.stores.filter((s) => s.store);
    const noUrl = t.stores.find((s) => !s.store)?.count || 0;
    box.innerHTML = `<b>이 묶음의 출처 태그</b> <span class="muted">(원본으로 넣을 때 붙음)</span>: ${srcTagChips(t.tags) || '<span class="muted">없음</span>'}
      ${t.store_tag ? ` + 수집 스토어 ${st.length ? st.slice(0, 6).map((s) => `${srcTagChips([s.store])}<span class="muted">${num(s.count)}개</span>`).join(" ") + (st.length > 6 ? ` 외 ${num(st.length - 6)}곳` : "") : '<span class="muted">(수집URL 없음)</span>'}${noUrl && st.length ? ` <span class="muted">· 수집URL 없는 상품 ${num(noUrl)}개</span>` : ""}` : ' <span class="muted">· 수집 스토어 태그 안 붙임</span>'}
      <button class="btn sm" id="cl-btags-edit">바꾸기</button>`;
    $("#cl-btags-edit").addEventListener("click", () => {
      App.openModal({
        title: "이 묶음의 출처 태그",
        body: `<p class="small muted" style="margin:0 0 6px">아직 원본으로 넣지 않은 상품에 적용됩니다. 이미 넣은 원본은 원본 상품 화면의 '출처 태그 달기·빼기'로 바꾸세요.</p>
          ${App.tagFields("ct", { value: t.tags.join(", "), store: t.store_tag })}`,
        buttons: [{ label: "취소" }, { label: "저장", primary: true, onClick: async (b) => {
          const v = App.tagValues("ct", b);
          await App.api(`/api/clean/${this.bid}/tags`, { json: { tags: v.tags, store_tag: v.store_tag === "1" } });
          App.toast("출처 태그를 저장했습니다");
          this.loadTags();
        } }],
      });
      App.bindTagFields("ct");
    });
  },

  renderSteps() {
    this.loadTags();
    const box = $("#cl-steps");
    if (!this.bid) { box.innerHTML = '<p class="muted pad">엑셀을 먼저 올리세요.</p>'; return; }
    const step = (n, title, inner, note = "") => `<section class="card pad cl-step"><div class="sec-head"><h2><span class="cl-n">${n}</span> ${title}</h2>
      ${note ? `<span class="muted small">${note}</span>` : ""}</div>${inner}</section>`;
    box.innerHTML = [
      step(2, "공통 이미지 찾기·제거", `<div class="cl-row">몇 개 이상 상품에 공통이면 보여 줄까요? <input id="cl-min" type="number" min="2" value="10" style="width:80px">
        <button class="btn" id="cl-common-go">공통 이미지 찾기</button></div><div id="cl-common"></div>
        <details class="small" id="cl-rules-box"><summary>다음에도 자동으로 빼는 이미지 (기억한 것)</summary><div id="cl-rules"></div></details>`,
        "여러 상품에 똑같이 들어간 이미지(상단·하단 공지 배너 등)"),
      step(3, "전화번호 찾기·제거", `<div class="cl-row"><button class="btn" id="cl-phone-go">전화번호 찾기</button>
        <span class="small muted">상세 글자·옵션명·상품명에서 찾음 (이미지 주소 속 숫자는 빼고, <b>사진 속 번호는 못 찾음</b>) · <span class="ph red">빨강</span> = 010형(기본 선택) · <span class="ph yellow">노랑</span> = 의심(치수·날짜일 수 있어 직접 확인)</span></div>
        <div id="cl-phone"></div>`),
      step(4, "상세 미리보기 · 이미지/글자 편집", `<div class="cl-row">행 번호 <input id="cl-ord" type="number" min="2" value="2" style="width:90px" title="제목=1행, 첫 상품=2행">
        <button class="btn" id="cl-ed-go">미리보기</button><button class="btn sm" id="cl-ed-prev">‹ 이전</button><button class="btn sm" id="cl-ed-next">다음 ›</button>
        <span id="cl-ed-info" class="small"></span></div>
        <p class="small muted" style="margin:4px 0">이미지: <b>클릭 → 선택(빨간 테두리) → Delete·Backspace로 삭제</b> · 글자: <b>클릭해서 바로 고치기</b> · 되돌리기 <b>Ctrl+Z</b> · 다 고쳤으면 [이 상품에 반영]</p>
        <div class="cl-editor"><iframe id="cl-frame" sandbox="allow-same-origin" title="상세 편집"></iframe></div>
        <div class="cl-row" style="margin-top:8px"><button class="btn primary" id="cl-ed-save">이 상품에 반영</button>
          <button class="btn" id="cl-ed-revert">처음 상세로 되돌리기</button><button class="btn danger" id="cl-ed-del">이 상품 지우기</button></div>`),
      step(5, "잘린·빈 상세 확인·삭제", `<div class="cl-row"><button class="btn" id="cl-broken-go">찾기</button>
        <span class="small muted">① 엑셀 칸 글자수 한도(32,767자)에 걸려 중간에 잘린 상세 ② 완전히 빈 상세</span></div><div id="cl-broken"></div>`),
      step(6, "빈 칸 상품 확인·삭제", `<div class="cl-row">검사할 칸:
        ${["상품명", "판매가", "상세설명", "썸네일", "카테고리"].map((c, i) => `<label class="check"><input type="checkbox" data-mcol="${c}" ${i < 3 ? "checked" : ""}><span>${c}</span></label>`).join("")}
        <button class="btn" id="cl-miss-go">찾기</button></div><div id="cl-miss"></div>`),
      step(7, "카테고리 검사·수정 · 생활화학 판정", `<div class="cl-row"><button class="btn" id="cl-cat-go">카테고리 검사</button>
        <button class="btn primary" id="cl-chem-go">생활화학 판정</button>
        <span class="small muted">최신 네이버 카테고리 목록과 대조 (형식 이상·폐지/오타·중간 분류) · 생활화학/살생물제 인증 대상 카테고리면 물건→'인증 대상 아님', 화학제품·애매→보류 (애매하면 AI)</span></div>
        <div id="cl-cat"></div><div id="cl-hold"></div>`),
      step(8, "원본 상품으로 넣기 · 새 엑셀로 저장", `<div class="cl-row"><button class="btn primary big" id="cl-send">원본 상품으로 넣기 (정리 중 <span id="cl-send-n">-</span>개)</button>
        <a class="btn" id="cl-export" href="/api/clean/${this.bid}/export" title="이 묶음의 정리 중·보류 상품을 올린 엑셀과 같은 열로 받습니다 (지운 상품 제외)">⬇ 엑셀 받기 — 이 묶음의 정리 중·보류 상품 (원래이름_수정.xlsx)</a></div>
        <p class="small muted" style="margin:6px 0 0">생활화학 보류·지운 상품은 넣지 않습니다. 상품명이 완전히 같은 원본이 이미 있으면 내용을 갱신하고 출처 태그는 더합니다(엑셀 불러오기와 같음). 넣은 뒤 원본 상품 화면에서 상품명 변경 → 복사로 이어 가세요.</p>`),
    ].join("");
    this.bind();
    this.loadRules();
    this.loadHold();
  },

  bind() {
    $("#cl-common-go").addEventListener("click", () => this.findCommon());
    $("#cl-phone-go").addEventListener("click", () => this.findPhones());
    $("#cl-ed-go").addEventListener("click", () => this.openEditor(+$("#cl-ord").value || 2));
    $("#cl-ed-prev").addEventListener("click", () => this.ed?.prev && this.openEditor(this.ed.prev));
    $("#cl-ed-next").addEventListener("click", () => this.ed?.next && this.openEditor(this.ed.next));
    $("#cl-ord").addEventListener("keydown", (e) => { if (e.key === "Enter") this.openEditor(+e.target.value || 2); });
    $("#cl-ed-save").addEventListener("click", () => this.saveEditor());
    $("#cl-ed-revert").addEventListener("click", () => this.revertEditor());
    $("#cl-ed-del").addEventListener("click", async () => { if (this.ed && await App.yes("정리함에서 지우기", "이 상품을 정리함에서 지울까요? (위 '지움'에서 되살릴 수 있음)", { label: "지우기", danger: true })) { await this.del([this.ed.id]); this.ed.next ? this.openEditor(this.ed.next) : null; } });
    $("#cl-broken-go").addEventListener("click", () => this.findBroken());
    $("#cl-miss-go").addEventListener("click", () => this.findMissing());
    $("#cl-cat-go").addEventListener("click", () => this.checkCats());
    $("#cl-chem-go").addEventListener("click", async () => { if (await App.yes("생활화학 판정", CHEM_JUDGE_TXT, { label: "판정 시작" })) App.startTask(App.api(`/api/clean/${this.bid}/chem`, { json: {} })); });
    $("#cl-send").addEventListener("click", async () => {
      if (!this.counts?.new) return App.toast("정리 중인 상품이 없습니다.", true);
      if (!await App.yes("원본 상품으로 넣기", `정리 중인 ${num(this.counts.new)}개를 원본 상품으로 넣을까요?${this.counts.hold ? `\n생활화학 보류 ${num(this.counts.hold)}개는 넣지 않습니다.` : ""}`, { label: "넣기" })) return;
      await App.startTask(App.api(`/api/clean/${this.bid}/send`, { json: {} }));
    });
    // 결과 목록 안의 '행' 누르면 편집으로
    $("#cl-steps").addEventListener("click", (e) => {
      const o = e.target.closest("[data-ord]");
      if (o && !e.target.closest("input")) { e.preventDefault(); this.openEditor(+o.dataset.ord); $("#cl-frame").scrollIntoView({ behavior: "smooth", block: "center" }); }
    });
  },

  async del(ids) {
    try {
      const r = await App.api("/api/clean/items/delete", { json: { ids } });
      App.toast(`${num(r.count)}개를 지웠습니다 (위 '지움'에서 되살릴 수 있음)`);
      this.refresh();
      return r.count;
    } catch (e) { App.toast(e.message, true); return 0; }
  },

  async showDeleted() {
    const d = await App.api(`/api/clean/${this.bid}/items?status=deleted&size=500`);
    App.openModal({
      title: `지운 상품 ${num(d.total)}개`, wide: true,
      body: d.rows.length ? `<div class="cl-list">${d.rows.map((r) => `<label class="check"><input type="checkbox" data-rs="${r.id}"><span>${r.ord}행 · ${esc(r.name)}</span></label>`).join("")}</div>` : '<p class="muted">없음</p>',
      buttons: [{ label: "닫기" }, { label: "고른 것 되살리기", primary: true, onClick: async () => {
        const ids = $$("[data-rs]:checked").map((x) => +x.dataset.rs);
        if (!ids.length) return true;
        const r = await App.api("/api/clean/items/restore", { json: { ids } });
        App.toast(`${num(r.count)}개를 되살렸습니다`);
        this.refresh();
        return true;
      } }],
    });
  },

  // ② 공통 이미지
  async findCommon() {
    const d = await App.api(`/api/clean/${this.bid}/common`, { json: { min: +$("#cl-min").value || 10 } });
    const box = $("#cl-common");
    if (!d.images.length) { box.innerHTML = `<p class="muted small">상품 ${num(d.total)}개 중 ${num(+$("#cl-min").value || 10)}개 이상에 공통인 이미지가 없습니다.</p>`; return; }
    box.innerHTML = `<p class="small">상품 ${num(d.total)}개 중 공통 이미지 ${num(d.images.length)}종${d.more ? ` (더 있음 ${num(d.more)})` : ""} — 지울 것을 고르세요.</p>
      <div class="cl-imgs">${d.images.map((x) => `<label class="cl-img"><input type="checkbox" data-src="${esc(x.src)}">
        <img src="${esc(x.src)}" loading="lazy" onerror="onImgError(this)"><span><b>${num(x.count)}개</b> 상품 · ${x.rows.map((o) => `<a href="#" data-ord="${o}">${o}행</a>`).join(" ")}${x.remembered ? ' <span class="flag">기억함</span>' : ""}</span></label>`).join("")}</div>
      <div class="cl-row" style="margin-top:8px"><button class="btn sm" data-all-img="1">전부 선택</button><button class="btn sm" data-all-img="0">전부 해제</button>
        <label class="check"><input type="checkbox" id="cl-remember" checked><span>다음에 올리는 엑셀에서도 자동으로 빼기</span></label>
        <button class="btn primary" id="cl-common-del">고른 이미지 지우기</button></div>`;
    $$("[data-all-img]", box).forEach((b) => b.addEventListener("click", () => $$("[data-src]", box).forEach((c) => { c.checked = b.dataset.allImg === "1"; })));
    $("#cl-common-del").addEventListener("click", async () => {
      const srcs = $$("[data-src]:checked", box).map((c) => c.dataset.src);
      if (!srcs.length) return App.toast("지울 이미지를 골라 주세요.", true);
      if (!await App.yes("공통 이미지 지우기", `고른 이미지 ${num(srcs.length)}종을 정리함 상품 상세에서 지웁니다.` + ($("#cl-remember").checked ? "\n다음에 올리는 엑셀에서도 자동으로 뺍니다." : ""), { label: "지우기", danger: true })) return;
      try {
        const r = await App.api(`/api/clean/${this.bid}/common/remove`, { json: { srcs, remember: $("#cl-remember").checked } });
        App.toast(`상품 ${num(r.items)}개에서 이미지 ${num(r.images)}장을 지웠습니다` + (r.remembered ? ` · ${num(r.remembered)}종은 다음에도 자동으로 뺌` : ""));
        this.refresh(); this.findCommon(); this.loadRules();
      } catch (e) { App.toast(e.message, true); }
    });
  },

  async loadRules() {
    const rs = await App.api("/api/clean/rules");
    const box = $("#cl-rules");
    if (!box) return;
    box.innerHTML = rs.length ? `<div class="cl-imgs">${rs.map((r) => `<div class="cl-img"><img src="${esc(r.value)}" loading="lazy" onerror="onImgError(this)">
      <span>${when(r.created_at)} · <button class="link-btn" data-rule="${r.id}">그만 빼기</button></span></div>`).join("")}</div>` : '<p class="muted small">기억한 이미지가 없습니다.</p>';
    $$("[data-rule]", box).forEach((b) => b.addEventListener("click", async () => { if (!await App.yes("기억한 이미지 그만 빼기", "이 이미지를 다음에 올리는 엑셀에서 더는 자동으로 빼지 않습니다 (이미 뺀 상품은 그대로).", { label: "그만 빼기" })) return; await App.api("/api/clean/rules/delete", { json: { ids: [+b.dataset.rule] } }); this.loadRules(); }));
  },

  // ③ 전화번호
  async findPhones() {
    const rows = await App.api(`/api/clean/${this.bid}/phones`, { json: {} });
    const box = $("#cl-phone");
    if (!rows.length) { box.innerHTML = '<p class="muted small">찾은 전화번호가 없습니다.</p>'; return; }
    const n = rows.reduce((a, r) => a + r.hits.length, 0);
    box.innerHTML = `<p class="small">상품 ${num(rows.length)}개에서 ${num(n)}개 찾음</p>
      <table class="grid"><thead><tr><th class="w-num">행</th><th>상품명</th><th>찾은 번호</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td class="num"><a href="#" data-ord="${r.ord}">${r.ord}</a></td><td class="small">${esc(r.name)}</td>
        <td>${r.hits.map((h) => `<label class="ph ${h.kind}"><input type="checkbox" data-ph="${r.id}" data-t="${esc(h.text)}" ${h.kind === "red" ? "checked" : ""}> ${esc(h.text)} <span class="muted">${esc(h.where)}</span></label>`).join(" ")}</td></tr>`).join("")}
      </tbody></table>
      <div class="cl-row" style="margin-top:8px"><button class="btn sm" data-phsel="red">빨강만 선택</button><button class="btn sm" data-phsel="all">전부 선택</button><button class="btn sm" data-phsel="none">전부 해제</button>
        <button class="btn primary" id="cl-phone-del">고른 번호 지우기</button></div>`;
    $$("[data-phsel]", box).forEach((b) => b.addEventListener("click", () => $$("[data-ph]", box).forEach((c) => {
      c.checked = b.dataset.phsel === "all" || (b.dataset.phsel === "red" && c.closest(".ph").classList.contains("red"));
    })));
    $("#cl-phone-del").addEventListener("click", async () => {
      const picks = $$("[data-ph]:checked", box).map((c) => ({ id: +c.dataset.ph, text: c.dataset.t }));
      if (!picks.length) return App.toast("지울 번호를 골라 주세요.", true);
      if (!await App.yes("전화번호 지우기", `고른 번호 ${num(picks.length)}개를 정리함 상품 상세에서 지웁니다.`, { label: "지우기", danger: true })) return;
      const r = await App.api("/api/clean/phones/remove", { json: { picks } });
      App.toast(`상품 ${num(r.items)}개에서 번호 ${num(r.removed)}개를 지웠습니다`);
      this.refresh(); this.findPhones();
    });
  },

  // ④ 상세 편집
  async openEditor(ord) {
    let it;
    try { it = await App.api(`/api/clean/item?batch_id=${this.bid}&ord=${ord}`); } catch (e) { return App.toast(e.message, true); }
    this.ed = it;
    $("#cl-ord").value = it.ord;
    const r = it.row;
    $("#cl-ed-info").innerHTML = `<b>${it.ord}행</b> · ${esc(it.name)} · ${num(it.price)}원 · <span class="badge ${{ new: "s-planned", hold: "s-fail", deleted: "s-deleted", sent: "s-success" }[it.status]}">${{ new: "정리 중", hold: "생활화학 보류", deleted: "지움", sent: "원본으로 넣음" }[it.status]}</span>${it.edited ? ' <span class="flag">고침</span>' : ""}`;
    $("#cl-ed-revert").disabled = !it.has_orig;
    const fr = $("#cl-frame");
    fr.onload = () => this.armEditor(fr);
    fr.srcdoc = `<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer"><style>
      body{margin:0;padding:8px 12px;font:15px/1.5 sans-serif;color:#111;max-width:860px} img{max-width:100%;height:auto;cursor:pointer;min-width:48px;min-height:32px;background:#f3f4f6}
      img:hover{outline:3px dashed #f59e0b} img.cl-sel{outline:4px solid #ef4444}</style><body>${cleanSafe(r["상세설명"])}</body>`;
  },

  armEditor(fr) {
    const doc = fr.contentDocument;
    if (!doc) return;
    doc.designMode = "on";
    const unsel = () => doc.querySelectorAll("img.cl-sel").forEach((x) => x.classList.remove("cl-sel"));
    doc.addEventListener("click", (e) => {
      unsel();
      if (e.target.tagName === "IMG") {
        e.preventDefault();
        e.target.classList.add("cl-sel");
        const rg = doc.createRange();
        rg.selectNode(e.target);
        const s = doc.getSelection();
        s.removeAllRanges();
        s.addRange(rg);
      }
    });
    doc.addEventListener("keydown", (e) => {
      const sel = doc.querySelector("img.cl-sel");
      if (sel && (e.key === "Delete" || e.key === "Backspace")) {
        e.preventDefault();
        const rg = doc.createRange();
        rg.selectNode(sel);
        const s = doc.getSelection();
        s.removeAllRanges();
        s.addRange(rg);
        doc.execCommand("delete");   // 브라우저 되돌리기(Ctrl+Z)에 남도록
      }
    });
  },

  async saveEditor() {
    if (!this.ed) return;
    const doc = $("#cl-frame").contentDocument;
    doc.querySelectorAll("img.cl-sel").forEach((x) => x.classList.remove("cl-sel"));
    doc.querySelectorAll("[class='']").forEach((x) => x.removeAttribute("class"));
    try {
      const r = await App.api(`/api/clean/item/${this.ed.id}/detail`, { json: { html: doc.body.innerHTML } });
      App.toast(`${this.ed.ord}행 상세를 반영했습니다 (이미지 ${num(r.images)}장)`);
      this.refresh();
      this.openEditor(this.ed.ord);
    } catch (e) { App.toast(e.message, true); }
  },

  async revertEditor() {
    if (!this.ed || !await App.yes("처음 상세로 되돌리기", "이 상품의 상세를 처음(엑셀에서 올린 그대로)으로 되돌릴까요?", { label: "되돌리기", danger: true })) return;
    await App.api(`/api/clean/item/${this.ed.id}/revert`, { json: {} });
    App.toast("처음 상세로 되돌렸습니다");
    this.refresh();
    this.openEditor(this.ed.ord);
  },

  // ⑤ 잘린·빈 상세 · ⑥ 빈 칸
  listHtml(rows, what, extra) {
    return rows.length ? `<div class="cl-list">${rows.map((r) => `<label class="check"><input type="checkbox" data-pick="${r.id}" checked>
      <span><a href="#" data-ord="${r.ord}">${r.ord}행</a> · ${esc(r.name)} ${extra ? `<span class="muted small">${extra(r)}</span>` : ""}</span></label>`).join("")}</div>`
      : `<p class="muted small">${what} 없음</p>`;
  },

  async findBroken() {
    const d = await App.api(`/api/clean/${this.bid}/broken`, { json: {} });
    const box = $("#cl-broken");
    box.innerHTML = `<h3 class="sec-title">① 글자수 한도로 잘린 상세 ${num(d.cut.length)}개</h3>${this.listHtml(d.cut, "잘린 상세", (r) => `${num(r.length)}자`)}
      <h3 class="sec-title">② 빈 상세 ${num(d.empty.length)}개</h3>${this.listHtml(d.empty, "빈 상세")}
      ${d.cut.length + d.empty.length ? '<div class="cl-row" style="margin-top:8px"><button class="btn danger" data-del-picked>고른 상품 지우기</button></div>' : ""}`;
    this.bindPickedDelete(box, () => this.findBroken());
  },

  async findMissing() {
    const cols = $$("[data-mcol]:checked").map((c) => c.dataset.mcol);
    const rows = await App.api(`/api/clean/${this.bid}/missing`, { json: { cols } });
    const box = $("#cl-miss");
    box.innerHTML = `<p class="small">${num(rows.length)}개</p>${this.listHtml(rows, "빈 칸 상품", (r) => `비어 있음: ${r.missing.join(", ")}`)}
      ${rows.length ? '<div class="cl-row" style="margin-top:8px"><button class="btn danger" data-del-picked>고른 상품 지우기</button></div>' : ""}`;
    this.bindPickedDelete(box, () => this.findMissing());
  },

  bindPickedDelete(box, again) {
    $("[data-del-picked]", box)?.addEventListener("click", async () => {
      const ids = $$("[data-pick]:checked", box).map((c) => +c.dataset.pick);
      if (!ids.length) return App.toast("고른 상품이 없습니다.", true);
      if (!await App.yes("정리함에서 지우기", `${num(ids.length)}개를 정리함에서 지울까요?`, { label: "지우기", danger: true })) return;
      await this.del(ids);
      again();
    });
  },

  // ⑦ 카테고리·생활화학
  async checkCats() {
    const box = $("#cl-cat");
    if (!box) return;
    const d = await App.api(`/api/clean/${this.bid}/categories`, { json: {} });
    if (!d.have_categories) { box.innerHTML = '<div class="notice warn">네이버 카테고리 목록이 아직 없습니다. 원본 상품 → 카테고리 맞추기에서 목록을 받아 주세요.</div>'; return; }
    const bad = d.groups.filter((g) => !["ok", "mapped"].includes(g.status));
    this.catAll = this.catAll || false;
    const show = this.catAll ? d.groups : bad;
    box.innerHTML = `<p class="small">카테고리 ${num(d.groups.length)}종 · 문제 ${num(bad.length)}종 (${num(bad.reduce((a, g) => a + g.count, 0))}개 상품) ·
        <a href="#" id="cl-cat-all">${this.catAll ? "문제 있는 것만 보기" : "전부 보기"}</a></p>
      ${show.length ? `<table class="grid"><thead><tr><th>엑셀 카테고리</th><th class="w-num">상품</th><th>상태</th><th>생활화학 인증 대상</th><th></th></tr></thead><tbody>
      ${show.map((g, i) => { const [l, c] = CAT_STATUS[g.status] || [g.status, ""]; return `<tr><td class="small">${esc(g.category || "(빈 칸)")}${g.naver && g.naver !== g.category ? `<div class="muted">→ ${esc(g.naver)}</div>` : ""}</td>
        <td class="num">${num(g.count)}${g.hold ? ` <span class="muted small">(보류 ${num(g.hold)})</span>` : ""}</td><td><span class="badge ${c}">${esc(l)}</span></td>
        <td class="small">${g.chem === true ? '<b class="c-err">대상</b>' : g.chem === false ? "아님" : '<span class="muted">모름 (생활화학 판정 때 확인)</span>'}</td>
        <td><button class="btn sm" data-cat-i="${i}">바꾸기</button></td></tr>`; }).join("")}</tbody></table>` : '<p class="muted small">문제 있는 카테고리가 없습니다.</p>'}`;
    $("#cl-cat-all").addEventListener("click", (e) => { e.preventDefault(); this.catAll = !this.catAll; this.checkCats(); });
    $$("[data-cat-i]", box).forEach((b) => b.addEventListener("click", () => {
      const g = show[+b.dataset.catI];
      App.pickCategory({ current: g.naver || g.category, what: `정리함의 '${g.category || "빈 칸"}' 상품 ${num(g.count)}개`, suggest: g.suggest,
        note: "정리함에서 이 카테고리인 상품을 모두 고른 카테고리로 바꿉니다 (생활화학 판정은 다시 해야 함).",
        save: async (to) => { const r = await App.api(`/api/clean/${this.bid}/category`, { json: { from: g.category, to } }); App.toast(`${num(r.count)}개를 '${to}'(으)로 바꿨습니다`); },
        after: () => { this.checkCats(); this.loadHold(); this.refresh(); } });
    }));
  },

  async loadHold() {
    const box = $("#cl-hold");
    if (!box || !this.bid) return;
    const rows = await App.api(`/api/clean/${this.bid}/hold`);
    if (!rows.length) { box.innerHTML = ""; return; }
    box.innerHTML = `<h3 class="sec-title c-err" style="margin-top:14px">생활화학 보류 ${num(rows.length)}개 — 검수해 주세요</h3>
      <p class="small muted" style="margin:0 0 6px">화학제품(세제·방향제·살충제·코팅제·접착제·양초 등)은 신고번호 없이 올리면 안 됩니다. 다른 카테고리로 옮겨 올리면 네이버 카테고리 회피 제재·화학제품안전법 위반 위험이 있습니다.
        화학제품이 아닌 물건이면 '물건으로' → 카테고리 그대로 '인증 대상 아님'으로 올라갑니다.</p>
      <table class="grid"><thead><tr><th class="w-check"><input type="checkbox" id="cl-hold-all"></th><th class="w-thumb"></th><th>상품</th><th>카테고리</th><th>판정</th><th></th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td class="w-check"><input type="checkbox" data-hold="${r.id}"></td><td>${img(r.thumb)}</td>
        <td><a href="#" data-ord="${r.ord}">${r.ord}행</a> · ${esc(r.name)}</td><td class="small">${esc(r.category)}</td>
        <td><span class="badge s-fail">${esc(CHEM_LABEL[r.chem] || r.chem)}</span><div class="small muted">${esc(r.chem_reason)}</div></td>
        <td class="nowrap"><button class="btn sm" data-hk="tool" data-id="${r.id}">물건으로</button> <button class="btn sm" data-hcat="${r.id}">카테고리 바꾸기</button></td></tr>`).join("")}
      </tbody></table>
      <div class="cl-row" style="margin-top:8px"><span class="small">고른 것:</span><button class="btn sm" data-hbulk="tool">물건으로</button>
        <button class="btn sm" data-hbulk="chemical">화학제품으로</button><button class="btn sm danger" data-hbulk="delete">지우기</button></div>`;
    const picked = () => $$("[data-hold]:checked", box).map((c) => +c.dataset.hold);
    $("#cl-hold-all").addEventListener("change", (e) => $$("[data-hold]", box).forEach((c) => { c.checked = e.target.checked; }));
    const setKind = async (ids, kind) => {
      if (!ids.length) return App.toast("고른 상품이 없습니다.", true);
      if (!await App.yes(kind === "tool" ? "물건으로 판정" : "화학제품으로 판정", `보류 상품 ${num(ids.length)}개를 ${kind === "tool" ? "'물건'으로 바꿉니다 — 카테고리 그대로 '인증 대상 아님'으로 올라갑니다" : "'화학제품'으로 둡니다 — 올리지 않습니다"}.`, { label: "바꾸기" })) return;
      if (!ids.length) return App.toast("고른 상품이 없습니다.", true);
      const r = await App.api("/api/clean/items/chem", { json: { ids, kind } });
      App.toast(`${num(r.count)}개를 '${CHEM_LABEL[kind]}'(으)로 정했습니다`);
      this.loadHold(); this.refresh();
    };
    $$("[data-hk]", box).forEach((b) => b.addEventListener("click", () => setKind([+b.dataset.id], b.dataset.hk)));
    $$("[data-hbulk]", box).forEach((b) => b.addEventListener("click", async () => {
      const ids = picked();
      if (b.dataset.hbulk === "delete") {
        if (!ids.length) return App.toast("고른 상품이 없습니다.", true);
        if (!await App.yes("보류 상품 지우기", `보류 상품 ${num(ids.length)}개를 정리함에서 지울까요? (아직 원본이 아니라 정리함에서만 지움)`, { label: "지우기", danger: true })) return;
        await this.del(ids); this.loadHold();
      } else setKind(ids, b.dataset.hbulk);
    }));
    $$("[data-hcat]", box).forEach((b) => b.addEventListener("click", () => {
      const r = rows.find((x) => x.id === +b.dataset.hcat);
      App.pickCategory({ current: r.category, what: `${r.ord}행 · ${r.name}`,
        note: "이 상품의 카테고리를 바꿉니다. 바꾼 뒤 '생활화학 판정'을 다시 누르면 새 카테고리 기준으로 판정합니다. <b>화학제품을 인증이 필요 없는 카테고리로 옮겨 올리는 것은 위험합니다.</b>",
        save: async (to) => { await App.api(`/api/clean/${this.bid}/category`, { json: { to, ids: [r.id] } }); App.toast(`'${to}'(으)로 바꿨습니다 — 생활화학 판정을 다시 눌러 주세요`); },
        after: () => { this.loadHold(); this.refresh(); this.checkCats(); } });
    }));
  },
});
