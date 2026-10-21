/* 금지어: 상품명에 넣지 않을 말(브랜드·캐릭터·명품·효능·인증 표현 등)과 키프리스 상표 확인 */
"use strict";

App.page("lexicon", {
  async mount(el) {
    const [d, tm] = await Promise.all([App.api("/api/lexicon"), App.api("/api/trademark")]);
    const count = d.blocked ? d.blocked.split(",").filter((w) => w.trim()).length : 0;
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>금지어</h1>
        <div class="head-actions"><span class="muted" id="lx-msg"></span>
          <label class="btn"><input type="file" id="lx-block-file" accept=".txt,.csv" hidden>파일에서 가져오기</label>
          <button class="btn primary" id="lx-save">저장</button></div></header>

      <section class="card pad">
        <div class="sec-head"><h2>금지어 <span class="muted small" id="lx-count">${num(count)}개</span></h2>
          <span class="muted small">쉼표나 줄바꿈으로 구분 · 파일 가져오기는 이미 있는 단어를 빼고 더합니다</span></div>
        <textarea id="lx-block" rows="16" spellcheck="false">${esc(d.blocked)}</textarea>
        <p class="muted small">원본 상품명과 AI 키워드에서 이 단어(단어 단위로 같은 것)를 빼고 이름을 만듭니다. 브랜드·캐릭터·명품 이름은 반드시 넣어 두세요.
          기본으로 상표에서 온 말(포크레인·호치키스 등), 브랜드(이케아·다이슨 등), 캐릭터·명품 이름, 근거 없이 쓰면 안 되는 효능·인증·원산지 표현이 들어 있습니다.
          원본 상품명에 이 단어가 들어 있으면 원본 상품 화면에 경고로 보입니다.</p>
      </section>

      <section class="card pad" id="tm-sec">
        <div class="sec-head"><h2>상표 확인 (키프리스)</h2>
          <span class="muted small">확인한 단어 ${num(tm.stats.checked)}개 · 걸린 단어 ${num(tm.rows.filter((r) => !r.allowed && r.verdict !== "error").length)}${tm.stats.allowed ? ` · 허용 ${num(tm.stats.allowed)}` : ""}</span>
          <div class="head-actions">
            <button class="btn" id="tm-all" ${tm.has_key ? "" : "disabled"} title="원본 상품명·AI 이름에 나오는 단어 중 아직 확인 안 한 것">상표 확인 (${num(tm.todo)}개 남음)</button>
          </div></div>
        ${tm.has_key ? "" : `<p class="flag warn">키프리스 키가 없습니다. <a href="#settings">설정 → API 키</a>에 KIPRIS Plus 키를 넣으세요.</p>`}
        <p class="muted small">'효도의자'·'왕자행거'처럼 <b>일반명사를 붙여 만든 말</b>이 상표로 등록·출원돼 있는지 확인합니다.
          걸린 단어가 들어간 이름은 쓰지 않고, 원본 상품명에 있으면 경고합니다. 상관없는 단어는 <b>허용</b>을 누르세요.</p>
        ${tm.rows.length ? `<div class="tm-wrap"><table class="opt-table tm-tbl"><thead><tr><th>단어</th><th>결과</th><th>분류</th><th>상표 예</th><th></th></tr></thead><tbody>
          ${tm.rows.map((r) => `<tr class="${r.allowed ? "muted" : ""}"><td><b>${esc(r.word)}</b></td>
            <td>${r.verdict === "registered" ? `<span class="flag bad">등록</span>` : r.verdict === "pending" ? `<span class="flag warn">출원 중</span>` : `<span class="flag">오류</span>`}</td>
            <td>${esc(r.classes || "")}</td><td class="small">${esc(r.titles || r.message || "")}</td>
            <td>${r.verdict === "error" ? "" : `<button class="btn" data-allow="${esc(r.word)}" data-v="${r.allowed ? 0 : 1}">${r.allowed ? "다시 막기" : "허용"}</button>`}</td></tr>`).join("")}
        </tbody></table></div>` : `<p class="muted">상표로 걸린 단어가 아직 없습니다.</p>`}
      </section>
    </div>`;
    const recount = () => { $("#lx-count").textContent = `${num($("#lx-block").value.split(/[,\n]/).filter((w) => w.trim()).length)}개`; };
    $("#lx-block").addEventListener("input", recount);
    $("#lx-save").addEventListener("click", async () => {
      try {
        const r = await App.api("/api/lexicon/blocked", { json: { text: $("#lx-block").value } });
        $("#lx-block").value = r.blocked; recount();
        $("#lx-msg").textContent = `저장했습니다 ✓ 금지어 ${num(r.count)}개`;
      } catch (e) { App.toast(e.message, true); }
    });
    $("#lx-block-file").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append("file", f);
      try {
        const r = await App.api("/api/lexicon/blocked/import", { method: "POST", body: fd });
        $("#lx-block").value = r.blocked; recount();
        App.toast(`금지어 가져오기: 새로 ${num(r.added)}개 · 이미 있던 ${num(r.existed)}개 (저장됨)`);
      } catch (err) { App.toast(err.message, true); }
      e.target.value = "";
    });
    $("#tm-all").addEventListener("click", () => App.startTask(App.api("/api/trademark/check", { json: { scope: "all" } })));
    $("#tm-sec").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-allow]");
      if (!b) return;
      try { await App.api("/api/trademark/allow", { json: { word: b.dataset.allow, allowed: b.dataset.v === "1" } }); App.route(); }
      catch (err) { App.toast(err.message, true); }
    });
    this.onDone = async (t) => { if (t.kind === "kipris") App.route(); };
    App.on("task-done", this.onDone);
  },
  unmount() { App.off("task-done", this.onDone); },
});
