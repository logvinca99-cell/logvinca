/* 스토어: 추가·수정, 여러 개 한 번에 추가, 연결 확인(네이버 상품 수), 사용량 */
"use strict";

App.page("stores", {
  async mount(el) {
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>스토어</h1>
        <div class="head-actions">
          <button class="btn" id="s-test-all">모두 연결 확인</button>
          <button class="btn" id="s-bulk">여러 개 한 번에 추가</button>
          <button class="btn primary" id="s-add">스토어 추가</button>
        </div></header>
      <p class="muted small" style="margin:0">스토어마다 커머스API센터에서 애플리케이션을 만들고, 이 PC의 IP를 호출 허용 IP로 등록해야 합니다.
        <b>연결 확인</b>을 누르면 네이버에 이미 있는 상품 수를 받아 와서 남은 자리를 정확히 계산합니다.</p>
      <div class="card table-card"><table class="grid"><thead><tr>
        <th class="w-code">코드</th><th>스토어</th><th class="w-usage">사용량 (대기 포함)</th><th class="w-num">남은 자리</th>
        <th class="w-num">판매 중</th><th class="w-num">대기</th><th class="w-num">실패</th><th class="w-num">내림</th>
        <th class="w-num">판매 이력</th><th class="w-num">가장 오래된 것</th><th class="w-num">네이버 상품 수</th><th class="w-num">주문 가져온 때</th><th class="w-act"></th>
      </tr></thead><tbody id="s-rows"></tbody></table></div>
    </div>`;
    $("#s-add").addEventListener("click", () => this.edit({ capacity: 10000, enabled: 1 }));
    $("#s-bulk").addEventListener("click", () => this.bulk());
    $("#s-test-all").addEventListener("click", () => this.testAll());
    $("#s-rows").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-act]");
      if (!b) return;
      const s = this.rows.find((x) => x.id === +b.dataset.id);
      if (b.dataset.act === "edit") this.edit(s);
      if (b.dataset.act === "test") this.test(s, b);
    });
    await this.load();
  },

  async load() {
    this.rows = await App.loadStores();
    $("#s-rows").innerHTML = this.rows.length ? this.rows.map((s) => `<tr class="${s.enabled ? "" : "off"}">
      <td><b class="code">${esc(s.code)}</b></td>
      <td><b>${esc(s.name)}</b>${s.enabled ? "" : ' <span class="flag">사용 안 함</span>'}${s.has_keys ? "" : ' <span class="flag warn">키 없음</span>'}
        <div class="p-sub">${s.store_url ? `<a href="${esc(s.store_url)}" target="_blank" rel="noopener">${esc(s.store_url.replace(/^https?:\/\//, ""))}</a>` : "주소 없음"}
        ${s.memo ? ` · ${esc(s.memo)}` : ""}</div></td>
      <td>${usageBar(s.used, s.capacity)}<div class="p-sub">${num(s.used)} / ${num(s.capacity)}</div></td>
      <td class="num ${s.free < 500 ? "c-err" : ""}">${num(s.free)}</td>
      <td class="num"><a href="#listings?store_id=${s.id}&status=live">${num(s.n_live)}</a></td>
      <td class="num">${num(s.n_pending + s.n_ops)}</td>
      <td class="num ${s.n_fail ? "c-err" : ""}">${num(s.n_fail)}</td><td class="num">${num(s.n_deleted)}</td>
      <td class="num"><a href="#listings?store_id=${s.id}&status=sold">${num(s.n_sold)}</a>${s.n_locked ? `<div class="p-sub r"><a href="#listings?store_id=${s.id}&status=locked">잠금 ${num(s.n_locked)}</a></div>` : ""}</td>
      <td class="num">${s.oldest_at ? age(s.oldest_at) : "-"}</td>
      <td class="num">${s.naver_count != null ? `${num(s.naver_count)}<div class="p-sub r">${when(s.naver_count_at)}</div>` : '<span class="muted">확인 전</span>'}</td>
      <td class="num">${s.orders_synced_to ? when(s.orders_synced_to) : '<span class="muted">-</span>'}</td>
      <td class="r nowrap"><button class="link-btn" data-act="test" data-id="${s.id}">연결 확인</button> ·
        <button class="link-btn" data-act="edit" data-id="${s.id}">수정</button></td></tr>`).join("")
      : `<tr class="empty-row"><td colspan="13">아직 스토어가 없습니다. <b>스토어 추가</b> 또는 <b>여러 개 한 번에 추가</b>를 누르세요.</td></tr>`;
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
        <label class="field">스토어 주소<input name="store_url" value="${esc(s.store_url || "")}" placeholder="https://smartstore.naver.com/mystore"></label>
        <div class="two">
          <label class="field">애플리케이션 ID<input name="client_id" value="${esc(s.client_id || "")}"></label>
          <label class="field">애플리케이션 시크릿<input name="client_secret" type="password" placeholder="${s.has_keys ? "저장됨 · 바꿀 때만 입력" : ""}"></label>
        </div>
        <div class="two">
          <label class="field">A/S 전화번호 <span class="muted">(비우면 설정의 기본값)</span><input name="as_phone" value="${esc(s.as_phone || "")}"></label>
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
          $$("input", b).forEach((x) => (v[x.name] = x.type === "checkbox" ? x.checked : x.value));
          try { await App.api("/api/stores", { json: v }); await this.load(); App.refreshState(); }
          catch (e) { App.toast(e.message, true); return false; }
        } },
      ],
    });
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
