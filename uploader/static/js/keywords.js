/* 네이버 키워드: 검색광고 API로 핵심 키워드(검색량)와 연관 키워드를 받아 재조합 새 단어로 씀 */
"use strict";

App.page("keywords", {
  async mount(el) {
    this.el = el;
    this.page = 0;
    this.q = "";
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>네이버 키워드</h1>
        <div class="head-actions"><span class="muted" id="kw-info"></span>
          <button class="btn primary" id="kw-collect">아직 안 모은 원본 키워드 모으기</button></div></header>
      <div id="kw-top"></div>
      <section class="card">
        <div class="toolbar pad-x"><div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>
          <input id="kw-q" placeholder="핵심 키워드 찾기 (예: 책상)"></div><span class="muted small">단어를 누르면 그 핵심 키워드에서 끔 · Shift+클릭은 모든 키워드에서 끔</span></div>
        <div id="kw-rows"></div>
        <div id="kw-pager"></div>
      </section>
    </div>`;
    $("#kw-collect").addEventListener("click", () => App.startTask(App.api("/api/keywords/collect", { json: {} })));
    let timer;
    $("#kw-q").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { this.q = e.target.value.trim(); this.page = 0; this.load(); }, 300);
    });
    $("#kw-rows").addEventListener("click", (e) => this.onChip(e));
    this.onDone = (t) => { if (t.kind === "keywords") this.load(); };
    App.on("task-done", this.onDone);
    await this.load();
  },
  unmount() { App.off("task-done", this.onDone); },

  async load() {
    const d = await App.api(`/api/keywords?page=${this.page}&q=${encodeURIComponent(this.q)}`);
    const st = d.stats;
    $("#kw-info").textContent = `원본 ${num(st.done)} / ${num(st.sources)}개 모음`;
    $("#kw-top").innerHTML = `
      ${d.has_key ? "" : `<div class="notice warn"><b>검색광고 API 키가 없습니다.</b> searchad.naver.com 가입(광고비 없이 가능) → 도구 → API 사용 관리 →
        고객 ID·액세스 라이선스·비밀키를 <a href="#settings">설정 → 네이버 키워드</a>에 넣으세요. 무료. (네이버 쇼핑 검색 API는 2026년 7월 종료)</div>`}
      ${d.enabled ? "" : `<div class="notice warn">설정에서 '재조합에 네이버 키워드 쓰기'가 꺼져 있어 모은 단어를 쓰지 않습니다.</div>`}
      <section class="card pad kw-how">
        <div class="kw-stats">
          <div><b>${num(st.done)}</b><span>키워드 모은 원본</span></div>
          <div><b>${num(d.total)}</b><span>핵심 키워드</span></div>
          <div><b>${num(st.words)}</b><span>모은 단어</span></div>
          <div><b>${num(st.queries)}</b><span>연관 키워드 받은 핵심 키워드</span></div>
          <div><b>${num(st.volumes)}</b><span>검색량 받은 단어</span></div>
        </div>
        <ol class="muted small">
          <li><b>핵심 키워드</b> = 원본 상품명 앞 ${App.state.settings.core_scan_words}단어 중 <b>월간 검색량이 가장 큰 단어</b>(속성·판촉 단어 제외). 원본 화면 → 키워드 탭에서 고치면 그 단어를 기억해 같은 단어가 나오는 다른 원본에도 씁니다.</li>
          <li>핵심 키워드의 <b>연관 키워드</b> 중 핵심 키워드가 들어간 것에서 핵심을 뺀 말을 새 단어로 씁니다(예: 책상 → 컴퓨터책상 → '컴퓨터'). 월 검색량 ${num(App.state.settings.kw_min_volume)} 미만, 판촉 문구, 금지·상표 단어${App.state.settings.kw_dict_only ? ", <b>국어사전에 없는 말(브랜드 등)</b>" : ""}은 뺍니다.</li>
          <li>재조합 때 <b>속성 단어</b>(우드·접이식·화이트·대형 등)는 원본 상품명·옵션·상세설명에 있을 때만 씁니다. <a href="#lexicon">단어 사전 → 속성 단어</a>에서 고칩니다.</li>
          <li>아래에서 단어를 누르면 그 핵심 키워드에서 <b>끕니다</b>(다시 누르면 켬). <span class="kw-chip attr">속성</span> 표시는 원본에 있을 때만 쓰는 단어입니다.</li>
        </ol>
      </section>`;
    $("#kw-rows").innerHTML = d.cores.length ? `<table class="grid kw-grid"><thead><tr><th>핵심 키워드</th><th class="num">원본</th><th>새 단어 후보 (연관 키워드 검색량 순)</th></tr></thead><tbody>
      ${d.cores.map((c) => `<tr data-core="${esc(c.core)}"><td><b>${esc(c.core || "(없음)")}</b></td><td class="num">${num(c.n)}</td>
        <td><div class="kw-chips">${c.words.map((w) => this.chip(w)).join("") || `<span class="muted small">모은 단어 없음</span>`}</div></td></tr>`).join("")}
      </tbody></table>` : `<p class="muted pad">아직 모은 키워드가 없습니다. 위의 버튼이나 원본 상품 화면에서 고른 상품으로 모으세요.</p>`;
    App.pager($("#kw-pager"), { page: this.page, size: d.size, total: d.total, onPage: (p) => { this.page = p; this.load(); } });
  },

  chip(w) {
    const cls = ["kw-chip", w.off ? "off" : "", w.attr ? "attr" : "", w.bad ? "bad" : ""].join(" ");
    const tip = [`원본 ${w.n}개에서 · 연관 키워드 월 검색량 ${num(w.malls)}`,
      w.attr ? "속성 단어: 원본에 있을 때만 씀" : "", w.bad ? `${w.bad} 단어라 안 씀` : "", w.off ? (w.all_off ? "모든 키워드에서 끔" : "끔 (누르면 켬)") : "누르면 끔"]
      .filter(Boolean).join("\n");
    return `<button class="${cls}" data-word="${esc(w.word)}" data-off="${w.off ? 1 : 0}" data-all="${w.all_off ? 1 : 0}" title="${esc(tip)}">${esc(w.word)}<small>${short(w.malls)}</small>${w.bad ? `<small>${w.bad}</small>` : ""}</button>`;
  },

  async onChip(e) {
    const b = e.target.closest("[data-word]");
    if (!b) return;
    const core = b.closest("tr").dataset.core;
    const turnOff = b.dataset.off !== "1";
    let all = false;
    if (turnOff && e.shiftKey) all = true;  // Shift+클릭: 모든 핵심 키워드에서 끔
    if (!turnOff && b.dataset.all === "1") all = true;
    try {
      await App.api("/api/keywords/off", { json: { core, word: b.dataset.word, off: turnOff, all } });
      await this.load();
    } catch (err) { App.toast(err.message, true); }
  },
});

function short(n) {
  if (n >= 10000) return (n / 10000).toFixed(n >= 100000 ? 0 : 1) + "만";
  if (n >= 1000) return (n / 1000).toFixed(1) + "천";
  return String(n);
}
