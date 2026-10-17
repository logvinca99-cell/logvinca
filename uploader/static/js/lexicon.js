/* 단어 사전: 재조합 때 넣을 새 단어(유의어 묶음·카테고리 단어)와 금지 단어, 미리보기 */
"use strict";

App.page("lexicon", {
  async mount(el) {
    const d = await App.api("/api/lexicon");
    const s = App.state.settings;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>단어 사전</h1>
        <div class="head-actions"><span class="muted" id="lx-msg"></span>
          <button class="btn" id="lx-fetch" title="원본 상품명에 자주 나오는 단어의 비슷한말을 국립국어원 우리말샘에서 받아 묶음으로 저장">우리말샘에서 유의어 받기</button>
          <button class="btn primary" id="lx-save">저장</button></div></header>

      <section class="card pad">
        <div class="sec-head"><h2>재조합 미리보기</h2><span class="muted small">저장하지 않고 만들어만 봅니다</span></div>
        <div class="lx-form">
          <input id="lx-name" placeholder="상품명 또는 원본 번호(#12)" class="lx-input">
          <input id="lx-cat" placeholder="카테고리 (예: 생활/건강>문구/사무용품>테이프>방수테이프)" class="lx-input">
          <button class="btn primary" id="lx-try">만들어 보기</button>
        </div>
        <div id="lx-out"></div>
      </section>

      <section class="card pad lx-rules">
        <h2>재조합 규칙</h2>
        <ol class="muted">
          <li>원본의 <b>앞 ${s.recombine_fixed_prefix}단어는 그대로 맨 앞에 고정</b>합니다.</li>
          <li>나머지 단어 중 0~3개를 빼고 순서를 섞습니다.</li>
          <li>새 단어 ${s.recombine_new_min}~${s.recombine_new_max}개를 <b>핵심 키워드 유의어부터</b> 고릅니다: ① 앞 ${s.recombine_fixed_prefix}단어의 유의어 → ② 카테고리 맨 아래 단계 이름 → ③ 카테고리와 겹치는 단어의 유의어 → ④ 나머지 단어의 유의어${s.recombine_use_tags ? " → ⑤ 엑셀 태그" : ""}.
            ${Math.round(s.recombine_replace_ratio * 100)}% 확률로 덧붙이지 않고 원래 단어 자리에 바꿔 넣습니다(예: 수리용 → 수선용).
            새 단어는 <b>한글 일반명사만</b>, 아래 <b>금지 단어</b>가 들어간 말은 넣지 않습니다.</li>
          <li>${s.recombine_fill ? `남는 칸을 ${s.name_max_len}자까지 채웁니다: 뺐던 원본 단어 → 그래도 남으면 우선순위 높은 새 단어.` : "빈칸 채우기는 꺼져 있습니다."}</li>
          <li>버리는 이름: 같은 단어가 ${s.max_word_repeat + 1}번 이상(다른 단어 안에 든 것도 셈) · 다른 스토어 이름과 같음 · 같은 원본 다른 이름과 (고정한 앞부분 뒤가) 너무 비슷함.</li>
          <li>AI·가져온 이름도 같은 단어 반복과 금지 단어로 검사해 걸리면 버립니다.</li>
        </ol>
        <p class="muted small">숫자들은 <a href="#settings">설정 → 상품명</a>에서 바꿉니다.</p>
      </section>

      <div class="lx-grid">
        <section class="card pad">
          <div class="sec-head"><h2>유의어 묶음</h2><span class="muted small">한 줄에 한 묶음 · 쉼표로 구분 · 같은 줄의 단어끼리 서로 바꿔 씀</span></div>
          <textarea id="lx-groups" rows="18" spellcheck="false">${esc(d.groups)}</textarea>
          <div class="sec-head" style="margin-top:14px"><h2>우리말샘에서 받은 묶음</h2><span class="muted small">${num(d.stats.opendict)}묶음 · 찾아본 단어 ${num(d.stats.looked)}개 · 이상한 건 지우고 저장</span></div>
          <textarea id="lx-opendict" rows="6" spellcheck="false">${esc(d.opendict)}</textarea>
        </section>
        <section class="card pad">
          <div class="sec-head"><h2>금지 단어</h2><span class="muted small">쉼표로 구분 · 이 말이 들어간 단어는 새로 넣지 않고, AI·가져온 이름도 버림</span></div>
          <textarea id="lx-block" rows="10" spellcheck="false">${esc(d.blocked)}</textarea>
          <p class="muted small">상표에서 온 말(포스트잇·스티로폼·호치키스 등), 브랜드, '정품·명품·스타일·호환' 같은 사칭 표현,
            근거 없이 쓰면 안 되는 효능·인증·원산지 표현(치료·무독성·항균·KC인증·국산 등)이 기본으로 들어 있습니다.
            원본 상품명에 이 단어가 있으면 원본 상품 화면에 경고로 표시됩니다(바꾼 뒤 '다시 검사').
            원본 상품명에 이미 있던 단어는 그대로 두므로, 원본 자체에 문제 단어가 있으면 원본 엑셀을 고치세요.</p>
        </section>
      </div>
    </div>`;
    $("#lx-save").addEventListener("click", () => this.save());
    $("#lx-try").addEventListener("click", () => this.preview());
    $("#lx-name").addEventListener("keydown", (e) => { if (e.key === "Enter") this.preview(); });
    $("#lx-fetch").addEventListener("click", () => App.startTask(App.api("/api/lexicon/fetch", { json: {} })));
    this.onDone = async (t) => { if (t.kind === "lexicon") { App.route(); } };
    App.on("task-done", this.onDone);
  },
  unmount() { App.off("task-done", this.onDone); },

  async save() {
    try {
      const d = await App.api("/api/lexicon", { json: { groups: $("#lx-groups").value, blocked: $("#lx-block").value, opendict: $("#lx-opendict").value } });
      $("#lx-msg").textContent = `저장했습니다 ✓ 묶음 ${num(d.stats.groups)}개 · 금지 단어 ${num(d.stats.blocked)}개`;
    } catch (e) { App.toast(e.message, true); }
  },

  async preview() {
    const v = $("#lx-name").value.trim();
    const m = v.match(/^#?(\d+)$/);
    try {
      const r = await App.api("/api/lexicon/preview", { json: m ? { source_id: +m[1] } : { name: v, category: $("#lx-cat").value.trim() } });
      if (m) $("#lx-cat").value = r.category;
      const max = App.state.settings.name_max_len;
      const hl = (n) => n.name.split(" ").map((w) => n.new.includes(w) ? `<mark>${esc(w)}</mark>` : esc(w)).join(" ");
      $("#lx-out").innerHTML = `<div class="lx-orig"><span class="muted">원본</span> ${esc(r.original)} <span class="muted">(${r.original_len}자)</span>
          ${r.original_repeat ? `<span class="flag warn">원본에 '${esc(r.original_repeat)}' 반복</span>` : ""}</div>
        <ul class="lx-names">${r.names.map((n) => `<li><span>${hl(n)}</span>
          <span class="lx-len ${n.len >= max - 4 ? "full" : ""}">${n.len}/${max}자</span><span class="muted small">새 단어 ${n.new.length}</span></li>`).join("")
          || `<li class="muted">만들 수 있는 이름이 없습니다. 단어가 적고 넣을 새 단어도 없을 때 그렇습니다 (유의어 묶음을 더하거나 AI를 쓰세요).</li>`}</ul>
        <p class="muted small">넣을 수 있던 새 단어 — 유의어: ${r.pool.synonyms.map(esc).join(", ") || "없음"} · 카테고리: ${r.pool.category.map(esc).join(", ") || "없음"}</p>`;
    } catch (e) { App.toast(e.message, true); }
  },
});
