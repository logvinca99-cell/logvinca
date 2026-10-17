/* 도둑방지: 높여 둔 가격 → 원래 가격, 베낀 상품, 며칠 만에 베끼는지, 워터마크 미리보기 */
"use strict";

App.page("bait", {
  async mount(el) {
    this.el = el;
    this.onDone = (t) => { if (t.kind === "bait") this.load(); };
    App.on("task-done", this.onDone);
    await this.load();
  },
  unmount() { App.off("task-done", this.onDone); },

  async load() {
    const d = await App.api("/api/bait");
    const s = App.state.settings, st = d.stats;
    const max = Math.max(1, ...st.hist.map((h) => h.n));
    this.el.innerHTML = `<div class="page">
      <header class="page-head"><h1>도둑방지</h1>
        <div class="head-actions">
          <button class="btn" id="b-watch" ${d.has_search_key ? "" : "disabled"} title="높인 가격으로 올라가 있는 복사본마다 내 상품명 그대로 네이버 쇼핑을 검색">지금 베낀 상품 찾기</button>
          <button class="btn primary" id="b-due" title="기한이 지난 것을 원래 가격으로">기한 지난 것 원래 가격으로</button></div></header>

      ${s.bait_enabled ? "" : `<div class="notice warn"><b>도둑방지 가격이 꺼져 있습니다.</b> <a href="#settings">설정 → 도둑방지</a>에서 켜면 이후 처음 올리는 상품부터 적용됩니다.</div>`}
      ${d.has_search_key ? "" : `<div class="notice warn">베낀 상품 찾기에는 네이버 검색 API 키가 필요합니다 (<a href="#settings">설정 → 네이버 키워드</a>). 키가 없으면 기한(${s.bait_days}일)이 지나야 되돌립니다.</div>`}

      <section class="card pad">
        <div class="kw-stats">
          <div><b>${num(st.on)}</b><span>지금 높인 가격</span></div>
          <div><b>${num(st.restored)}</b><span>원래 가격으로 되돌림</span></div>
          <div><b class="${st.failed ? "c-err" : ""}">${num(st.failed)}</b><span>되돌리기 실패</span></div>
          <div><b>${num(st.copied_listings)}</b><span>베낀 상품이 나온 복사본</span></div>
          <div><b>${st.median_days == null ? "—" : st.median_days.toFixed(1) + "일"}</b><span>올리고 베낄 때까지 (중앙값)</span></div>
        </div>
        <ol class="muted small bait-how">
          <li>처음 올릴 때 가격을 <b>+${num(s.bait_amount)}원</b> 높여 올립니다${s.bait_on_refresh ? " (최신화 때도)" : " (최신화 때는 원래 가격)"}.</li>
          <li>${s.bait_watch ? `${s.bait_watch_hours}시간마다 내 상품명 그대로 네이버 쇼핑을 검색해, 내 스토어가 아닌 곳에서 상품명이 ${Math.round(s.bait_copy_match * 100)}% 이상 같고 더 싼 상품을 찾습니다.` : "베낀 상품 자동 찾기는 꺼져 있습니다."}
            ${s.bait_restore_on_copy ? "찾으면 바로 원래 가격으로 되돌립니다." : "찾아도 기한까지 기다립니다."}</li>
          <li>못 찾아도 <b>${s.bait_days}일</b>이 지나면 원래 가격으로 되돌립니다. 프로그램이 켜져 있을 때 10분마다 확인합니다.</li>
          <li>내 스토어 구분은 스토어 이름과 스토어 화면의 '쇼핑 노출 이름'으로 합니다.</li>
        </ol>
      </section>

      <section class="card pad">
        <div class="sec-head"><h2>올린 뒤 며칠 만에 베꼈나</h2><span class="muted small">복사본별 처음 찾은 날 기준 · 찾아보는 간격(${s.bait_watch_hours}시간)만큼 늦게 잡힐 수 있음</span></div>
        ${st.copied_listings ? `<div class="hist" role="img" aria-label="올린 뒤 베낄 때까지 걸린 날 분포">
          ${st.hist.map((h) => `<div class="hist-col" title="${h.day === 14 ? "14일 이상" : h.day + "일째"}: ${num(h.n)}건">
            <span class="hist-n">${h.n ? num(h.n) : ""}</span>
            <div class="hist-bar" style="height:${(h.n / max) * 100}%"></div>
            <span class="hist-x">${h.day === 14 ? "14+" : h.day}</span></div>`).join("")}
        </div><p class="muted small">가로: 올린 뒤 지난 날 수 · 세로: 그때 처음 베낀 상품이 보인 복사본 수. 대부분이 며칠째에 몰리는지 보고 '되돌리는 날'(지금 ${s.bait_days}일)을 정하세요.</p>`
        : `<p class="muted">아직 찾은 베낀 상품이 없습니다.</p>`}
      </section>

      <section class="card pad">
        <div class="sec-head"><h2>베낀 것으로 보이는 상품</h2><span class="muted small">최근 ${num(d.copycats.length)}개</span></div>
        ${d.copycats.length ? `<div class="tm-wrap"><table class="opt-table"><thead><tr><th>찾은 때</th><th>그쪽 스토어</th><th>그쪽 상품명</th><th class="r">그쪽 가격</th><th class="r">내 가격</th><th>내 복사본</th></tr></thead><tbody>
          ${d.copycats.map((c) => `<tr><td>${ymd(c.found_at)}${c.registered_at ? `<div class="p-sub">올리고 ${((c.found_at - c.registered_at) / 86400).toFixed(1)}일</div>` : ""}</td>
            <td>${esc(c.mall)}</td><td><a href="${esc(c.link)}" target="_blank" rel="noopener">${esc(c.title)}</a> <span class="muted small">${Math.round(c.similarity * 100)}%</span></td>
            <td class="r">${num(c.price)}원</td><td class="r">${num(c.my_price)}원<div class="p-sub">원래 ${num(c.my_base)}원${c.bait_state === "restored" ? " · 되돌림" : ""}</div></td>
            <td><a href="#" data-listing="${c.listing_id}">${esc(c.store_name)}</a></td></tr>`).join("")}
        </tbody></table></div>` : `<p class="muted">없음</p>`}
      </section>

      <section class="card pad">
        <div class="sec-head"><h2>높인 가격으로 올라가 있는 것</h2><span class="muted small">${num(d.on.length)}개 (되돌릴 날 순)</span></div>
        ${d.on.length ? `<div class="tm-wrap"><table class="opt-table"><thead><tr><th>스토어</th><th>상품명</th><th class="r">네이버 가격</th><th class="r">원래 가격</th><th>되돌릴 날</th><th>마지막 확인</th></tr></thead><tbody>
          ${d.on.map((l) => `<tr><td>${esc(l.store_name)}</td><td><a href="#" data-listing="${l.id}">${esc(l.name)}</a></td>
            <td class="r">${num(l.price + l.bait)}원</td><td class="r">${num(l.price)}원</td><td>${ymd(l.bait_until)}</td>
            <td>${l.bait_checked_at ? ymd(l.bait_checked_at) : "아직"}</td></tr>`).join("")}
        </tbody></table></div>` : `<p class="muted">없음</p>`}
      </section>

      <section class="card pad">
        <div class="sec-head"><h2>대표 이미지 워터마크</h2><span class="muted small">${s.wm_enabled ? "켜짐" : "꺼짐"} · 스토어마다 로고나 글자는 <a href="#stores">스토어</a> 화면에서 · 위치·크기는 <a href="#settings">설정 → 워터마크</a></span></div>
        <div class="wm-previews">
          ${[[1000, 1000, "정사각형"], [1000, 1400, "세로로 긴 이미지"], [1400, 1000, "가로로 긴 이미지"]].map(([w, h, t]) =>
            `<figure><img src="/api/watermark/preview?w=${w}&h=${h}&_=${Date.now()}" alt="${t} 워터마크 미리보기"><figcaption>${t} ${w}×${h}</figcaption></figure>`).join("")}
        </div>
        <p class="muted small">초록 테두리 = 네이버 목록에서 잘려 보이는 가운데 정사각형. 직사각형도 이 안쪽 모서리에 넣으므로 잘려도 워터마크가 보입니다
          ('흰 여백으로 정사각형 만들기'를 고르면 상품이 잘리지 않게 여백을 붙인 뒤 넣음). 워터마크를 넣은 이미지는 스토어마다 따로 올라갑니다.</p>
      </section>
    </div>`;
    $("#b-watch").addEventListener("click", () => App.startTask(App.api("/api/bait/watch", { json: {} })));
    $("#b-due").addEventListener("click", () => App.startTask(App.api("/api/bait/restore", { json: { due: true } })));
    this.el.addEventListener("click", (e) => {
      const a = e.target.closest("[data-listing]");
      if (a) { e.preventDefault(); App.pages.listings.openListing(+a.dataset.listing); }
    });
  },
});
