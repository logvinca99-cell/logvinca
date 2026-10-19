/* 단어 사전: 재조합 때 넣을 새 단어(유의어 묶음)와 금지 단어, 키프리스 상표 확인, 미리보기 */
"use strict";

App.page("lexicon", {
  async mount(el) {
    const [d, tm] = await Promise.all([App.api("/api/lexicon"), App.api("/api/trademark")]);
    const s = App.state.settings;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>단어 사전</h1>
        <div class="head-actions"><span class="muted" id="lx-msg"></span>
          <label class="btn" title="우리말샘·표준국어대사전 '사전 내려받기' 파일(zip/xml/json). API 키 없이 사전 단어 확인과 비슷한말에 씀"><input type="file" id="lx-dictfile" accept=".zip,.xml,.json" hidden>사전 파일 넣기</label>
          ${s.has_opendict_key ? `<button class="btn" id="lx-fetch" title="원본 상품명에 자주 나오는 단어의 비슷한말을 국립국어원 우리말샘 API에서 받아 묶음으로 저장">우리말샘 API로 유의어 받기</button>` : ""}
          <button class="btn primary" id="lx-save">저장</button></div></header>

      <section class="card pad">
        <div class="sec-head"><h2>재조합 미리보기</h2><span class="muted small">저장하지 않고 만들어만 봅니다</span></div>
        <div class="lx-form">
          <input id="lx-name" placeholder="상품명 또는 원본 번호(#12)" class="lx-input">
          ${s.use_category_words ? `<input id="lx-cat" placeholder="카테고리 (예: 생활/건강>문구/사무용품>테이프>방수테이프)" class="lx-input">` : ""}
          <button class="btn primary" id="lx-try">만들어 보기</button>
        </div>
        <div id="lx-out"></div>
      </section>

      <section class="card pad lx-dict">
        <div class="sec-head"><h2>국어사전</h2>
          <span class="muted small">${d.stats.dict_words ? `명사 ${num(d.stats.dict_words)}개 · 비슷한말 있는 단어 ${num(d.stats.dict_syn)}개${d.dict_file ? ` · ${esc(d.dict_file.name)} (${ymd(d.dict_file.at)})` : ""}` : "아직 안 넣음"}</span></div>
        <div class="dict-folder"><span>사전 폴더: <code>${esc(d.dict_dir)}</code></span>
          ${d.dict_new.length ? `<span class="flag warn">새 파일 ${d.dict_new.length}개: ${d.dict_new.map(esc).join(", ")}</span>` : ""}
          <button class="btn" id="lx-dictfolder">폴더에서 사전 읽기</button></div>
        <p class="muted small">우리말샘(opendict.korean.go.kr) 또는 표준국어대사전에 로그인 → <b>사전 내려받기</b>로 받은 zip을 <b>압축 풀지 말고 위 폴더에 그대로</b> 넣으세요.
          프로그램을 켤 때 새 파일이 있으면 자동으로 읽고, '폴더에서 사전 읽기'로 바로 읽을 수도 있습니다(용량이 커서 몇 분 걸림). 다 읽은 뒤엔 zip을 지워도 됩니다. 작은 파일은 위의 '사전 파일 넣기'로 올려도 됩니다.
          ① 사전에 있는 명사는 일반명사로 보고 키프리스 확인에서 뺍니다(조어만 확인). ② 명사의 비슷한말을 재조합 유의어로 씁니다 — 단, 원본 상품명·네이버 키워드에 실제로 나오는 말끼리만(옛말·전문어가 들어가지 않게).</p>
      </section>

      <section class="card pad lx-rules">
        <h2>재조합 규칙</h2>
        <ol class="muted">
          <li>원본의 <b>앞 ${s.recombine_fixed_prefix}단어는 그대로 맨 앞에 고정</b>합니다.</li>
          <li>나머지 단어 중 0~3개를 빼고 순서를 섞습니다.</li>
          <li>새 단어 ${s.recombine_new_min}~${s.recombine_new_max}개를 우선순위대로 고릅니다: ① 앞 ${s.recombine_fixed_prefix}단어의 유의어와 <b>네이버 연관 키워드</b>(원본에 없는 속성은 뺌) → ② 나머지 단어의 유의어 → ③ 뜻이 다를 수 있는 사전 비슷한말${s.recombine_use_tags ? " → ④ 엑셀 태그" : ""}.
            유의어는 유의어 묶음과 국어사전(사전 파일) 비슷한말을 함께 씁니다. 검색광고 API 키가 있으면 아직 안 받은 원본은 재조합할 때 자동으로 받습니다(<a href="#keywords">네이버 키워드</a>).
            카테고리는 상품명 만들기에 쓰지 않습니다${s.use_category_words ? "(지금은 설정에서 켜져 있음)" : ""}.
            ${Math.round(s.recombine_replace_ratio * 100)}% 확률로 덧붙이지 않고 원래 단어 자리에 바꿔 넣습니다(예: 수리용 → 수선용).
            새 단어는 <b>한글 일반명사만</b>, 아래 <b>금지 단어</b>가 들어간 말과 <b>키프리스에서 상표로 확인된 단어</b>는 넣지 않습니다.</li>
          <li>${s.recombine_fill ? `남는 칸을 ${s.name_max_len}자까지 채웁니다: 뺐던 원본 단어 → 그래도 남으면 우선순위 높은 새 단어.` : "빈칸 채우기는 꺼져 있습니다."}</li>
          <li>버리는 이름: 같은 단어가 ${s.max_word_repeat + 1}번 이상(다른 단어 안에 든 것도 셈) · 다른 스토어 이름과 같음 · 같은 원본 다른 이름과 (고정한 앞부분 뒤가) 너무 비슷함.</li>
          <li>AI·가져온 이름도 같은 단어 반복·금지 단어·상표 단어로 검사해 걸리면 버립니다.</li>
        </ol>
        <p class="muted small">숫자들은 <a href="#settings">설정 → 상품명</a>에서 바꿉니다.</p>
      </section>


      <section class="card pad" id="tm-sec">
        <div class="sec-head"><h2>상표 확인 (키프리스)</h2>
          <span class="muted small">확인한 조어 ${num(tm.stats.checked)}개 · 걸린 단어 ${num(tm.rows.filter((r) => !r.allowed && r.verdict !== "error").length)}${tm.stats.allowed ? ` · 허용 ${num(tm.stats.allowed)}` : ""} · 사전 단어로 확인돼 건너뛴 것 ${num(tm.in_dict)}</span>
          <div class="head-actions">
            <button class="btn" id="tm-all" ${tm.has_key ? "" : "disabled"} title="원본 상품명·네이버 키워드·AI/가져온 이름에 나오는 조어 중 아직 확인 안 한 것">조어 상표 확인 (${num(tm.todo)}개 남음)</button>
          </div></div>
        ${tm.has_key ? "" : `<p class="flag warn">키프리스 키가 없습니다. <a href="#settings">설정 → 상표 확인</a>에 KIPRIS Plus 키를 넣으세요.</p>`}
        ${tm.has_key && !tm.has_opendict ? `<p class="flag warn">국어사전이 없으면 사전에 있는 일반명사도 키프리스로 확인해 걸릴 수 있습니다. 위의 '국어사전'에 사전 파일을 먼저 넣으세요.</p>` : ""}
        <p class="muted small">사전에 있는 일반명사(의자·행거·수납함)는 상표가 있어도 그 상품의 보통 명칭이라 <b>확인하지 않습니다</b>.
          '효도의자'·'왕자행거'처럼 <b>일반명사를 붙여 만든 조어</b>만 확인합니다: 3글자 이상 한글 단어 중 유의어 묶음·속성 단어에 없고 우리말샘 표제어도 아닌 것.
          상표명이 정확히 같은 등록·출원 상표가 있으면 새 단어로 넣지 않고, AI·가져온 이름에 있으면(띄어 쓴 '효도 의자'도) 버리고, 원본 상품명에 있으면 경고합니다.</p>
        ${tm.rows.length ? `<div class="tm-wrap"><table class="opt-table tm-tbl"><thead><tr><th>단어</th><th>결과</th><th>분류</th><th>상표 예</th><th></th></tr></thead><tbody>
          ${tm.rows.map((r) => `<tr class="${r.allowed ? "muted" : ""}"><td><b>${esc(r.word)}</b></td>
            <td>${r.verdict === "registered" ? `<span class="flag bad">등록</span>` : r.verdict === "pending" ? `<span class="flag warn">출원 중</span>` : `<span class="flag">오류</span>`}</td>
            <td>${esc(r.classes || "")}</td><td class="small">${esc(r.titles || r.message || "")}</td>
            <td>${r.verdict === "error" ? "" : `<button class="btn" data-allow="${esc(r.word)}" data-v="${r.allowed ? 0 : 1}">${r.allowed ? "다시 막기" : "허용"}</button>`}</td></tr>`).join("")}
        </tbody></table></div>` : `<p class="muted">상표로 걸린 조어가 아직 없습니다.</p>`}
      </section>
      <div class="lx-grid">
        <section class="card pad">
          <div class="sec-head"><h2>유의어 묶음</h2><span class="muted small">한 줄에 한 묶음 · 쉼표로 구분 · 같은 줄의 단어끼리 서로 바꿔 씀</span></div>
          <textarea id="lx-groups" rows="18" spellcheck="false">${esc(d.groups)}</textarea>
          <div class="sec-head" style="margin-top:14px"><h2>우리말샘에서 받은 묶음</h2><span class="muted small">${num(d.stats.opendict)}묶음 · 찾아본 단어 ${num(d.stats.looked)}개 · 우리말샘 API 키가 있을 때만 · 이상한 건 지우고 저장</span></div>
          <textarea id="lx-opendict" rows="6" spellcheck="false">${esc(d.opendict)}</textarea>
        </section>
        <section class="card pad">
          <div class="sec-head"><h2>금지 단어</h2><span class="muted small">쉼표로 구분 · 이 말이 들어간 단어는 새로 넣지 않고, AI·가져온 이름도 버림</span></div>
          <textarea id="lx-block" rows="10" spellcheck="false">${esc(d.blocked)}</textarea>
          <p class="muted small">상표에서 온 말(포스트잇·스티로폼·호치키스 등), 브랜드, '정품·명품·스타일·호환' 같은 사칭 표현,
            근거 없이 쓰면 안 되는 효능·인증·원산지 표현(치료·무독성·항균·KC인증·국산 등)이 기본으로 들어 있습니다.
            원본 상품명에 이 단어가 있으면 원본 상품 화면에 경고로 표시됩니다(바꾼 뒤 '다시 검사').
            원본 상품명에 이미 있던 단어는 그대로 두므로, 원본 자체에 문제 단어가 있으면 원본 엑셀을 고치세요.</p>
          <div class="sec-head" style="margin-top:14px"><h2>속성 단어</h2><span class="muted small">${num(d.stats.attrs)}개 · 쉼표로 구분</span></div>
          <textarea id="lx-attrs" rows="7" spellcheck="false">${esc(d.attrs)}</textarea>
          <p class="muted small">재질·모양·색·크기처럼 같은 상품을 서로 다른 상품으로 가르는 말입니다. 네이버에서 모은 단어에 이 말이 들어 있으면
            원본 상품명·옵션·상세설명에 그 말이 있을 때만 씁니다(철제 책상에 '우드'가 들어가지 않게). 끝이 '~식·~형·~색'인 3글자 이상 단어도 속성으로 봅니다.</p>
        </section>
      </div>
    </div>`;
    $("#lx-save").addEventListener("click", () => this.save());
    $("#lx-try").addEventListener("click", () => this.preview());
    $("#lx-name").addEventListener("keydown", (e) => { if (e.key === "Enter") this.preview(); });
    $("#lx-fetch")?.addEventListener("click", () => App.startTask(App.api("/api/lexicon/fetch", { json: {} })));
    $("#lx-dictfolder").addEventListener("click", () => App.startTask(App.api("/api/lexicon/dictfolder", { json: {} })));
    $("#lx-dictfile").addEventListener("change", (e) => { if (e.target.files[0]) App.upload("/api/lexicon/dictfile", e.target.files[0]); e.target.value = ""; });
    $("#tm-all").addEventListener("click", () => App.startTask(App.api("/api/trademark/check", { json: { scope: "all" } })));
    $("#tm-sec").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-allow]");
      if (!b) return;
      try { await App.api("/api/trademark/allow", { json: { word: b.dataset.allow, allowed: b.dataset.v === "1" } }); App.route(); }
      catch (err) { App.toast(err.message, true); }
    });
    this.onDone = async (t) => { if (["lexicon", "kipris", "dictfile"].includes(t.kind)) { App.route(); } };
    App.on("task-done", this.onDone);
  },
  unmount() { App.off("task-done", this.onDone); },

  async save() {
    try {
      const d = await App.api("/api/lexicon", { json: { groups: $("#lx-groups").value, blocked: $("#lx-block").value, opendict: $("#lx-opendict").value, attrs: $("#lx-attrs").value } });
      $("#lx-msg").textContent = `저장했습니다 ✓ 묶음 ${num(d.stats.groups)}개 · 금지 단어 ${num(d.stats.blocked)}개`;
    } catch (e) { App.toast(e.message, true); }
  },

  async preview() {
    const v = $("#lx-name").value.trim();
    const m = v.match(/^#?(\d+)$/);
    try {
      const r = await App.api("/api/lexicon/preview", { json: m ? { source_id: +m[1] } : { name: v, category: $("#lx-cat")?.value.trim() || "" } });
      if (m && $("#lx-cat")) $("#lx-cat").value = r.category;
      const max = App.state.settings.name_max_len;
      const hl = (n) => n.name.split(" ").map((w) => n.new.includes(w) ? `<mark>${esc(w)}</mark>` : esc(w)).join(" ");
      const KW = { ok: `네이버 연관 키워드 ${r.kw_count}개 반영`, nokey: "네이버 키워드: 설정에 검색광고 API 키가 없음",
        off: "네이버 키워드 꺼짐(설정)", error: `네이버 키워드를 못 받음: ${r.kw_error || ""}` };
      const by = (o) => r.sources.filter((x) => x.from === o).map((x) => esc(x.word) + (x.rank >= 3 ? "<sup title='같은 카테고리 상품명에 안 쓰이는 사전 비슷한말 — 뜻이 다를 수 있어 뒤로'>?</sup>" : ""));
      $("#lx-out").innerHTML = `<div class="lx-orig"><span class="muted">원본</span> ${esc(r.original)} <span class="muted">(${r.original_len}자)</span>
          <span class="flag ${r.candidates.length < r.new_min ? "warn" : ""}">넣을 수 있는 새 단어 후보 ${r.candidates.length}개${r.candidates.length < r.new_min ? ` — 설정(최소 ${r.new_min}개)보다 적어 ${r.candidates.length}개만 넣음` : ""}</span>
          <span class="flag ${r.kw_state === "ok" ? "" : "warn"}" title="${esc(r.kw_error || "")}">${esc(KW[r.kw_state] || "")}</span>
          ${r.original_repeat ? `<span class="flag warn">원본에 '${esc(r.original_repeat)}' 반복</span>` : ""}
          ${r.marks.map((x) => `<span class="flag bad">상표 단어 '${esc(x.word)}'(${x.verdict})</span>`).join("")}</div>
        <ul class="lx-names">${r.names.map((n) => `<li><span>${hl(n)}</span>
          <span class="lx-len ${n.len >= max - 4 ? "full" : ""}">${n.len}/${max}자</span><span class="muted small">새 단어 ${n.new.length}</span></li>`).join("")
          || `<li class="muted">만들 수 있는 이름이 없습니다. 단어가 적고 넣을 새 단어도 없을 때 그렇습니다 (검색광고 API 키·사전 파일·유의어 묶음을 확인하거나 AI를 쓰세요).</li>`}</ul>
        <p class="muted small lx-pool">넣을 수 있던 새 단어 (우선순위 순)<br>
          · 네이버 연관 키워드: ${by("네이버").join(", ") || "없음"}<br>
          · 유의어 묶음: ${by("묶음").join(", ") || "없음"}<br>
          · 국어사전 비슷한말: ${by("사전").join(", ") || "없음"} <span class="muted">(? = 같은 카테고리 상품명에 안 쓰이는 말, 뜻이 다를 수 있어 뒤로)</span>
          ${by("카테고리").length ? `<br>· 카테고리: ${by("카테고리").join(", ")}` : ""}${by("태그").length ? `<br>· 태그: ${by("태그").join(", ")}` : ""}</p>`;
    } catch (e) { App.toast(e.message, true); }
  },
});
