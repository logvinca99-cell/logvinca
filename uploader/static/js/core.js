/* 공통: API 호출, 화면 이동, 서랍·창·알림, 뒤에서 도는 작업 표시, 등록 진행 상황 받기.
 * 각 화면(home.js, inventory.js …)은 App.page("이름", {mount, unmount})로 등록한다. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n) => (n ?? 0).toLocaleString("ko-KR");

function dur(sec) {
  if (sec == null || !isFinite(sec)) return "-";
  sec = Math.max(0, Math.round(sec));
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (d) return `${d}일 ${h}시간`;
  if (h) return `${h}시간 ${m}분`;
  if (m) return `${m}분${s ? " " + s + "초" : ""}`;
  return `${s}초`;
}

function when(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000), p = (n) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function onImgError(img) {
  img.onerror = null;
  img.src = "data:image/svg+xml;utf8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" fill="#e9edf0"/>' +
    '<path d="M12 27l6-7 4 5 3-3 5 5z" fill="#c3cbd2"/><circle cx="25" cy="15" r="3" fill="#c3cbd2"/></svg>');
}
const img = (url, cls = "thumb") =>
  `<img class="${cls}" loading="lazy" referrerpolicy="no-referrer" src="${esc(url)}" onerror="onImgError(this)" alt="">`;

const STATUS = {
  planned: "등록 대기", queued: "순서 대기", running: "처리 중", success: "판매 중", fail: "실패", deleted: "내림",
};
const OP = { create: "등록", refresh: "최신화", delete: "내리기" };

/* 상태 + 할 일을 한 낱말로: "최신화 대기", "내리기 실패" … */
function statusLabel(status, op = "create") {
  if (status === "planned") return `${OP[op] || "등록"} 대기`;
  if (status === "fail") return `${OP[op] || "등록"} 실패`;
  if (status === "running") return `${OP[op] || "등록"} 중`;
  return STATUS[status] || status;
}
function statusBadge(status, op) {
  const cls = status === "planned" && op !== "create" ? `s-${op}` : `s-${status}`;
  return `<span class="badge ${cls}">${esc(statusLabel(status, op))}</span>`;
}
/* 잠금 표시: 판매 이력으로 자동 잠금이거나 직접 잠금 → 최신화·내리기로 지우지 않음 */
function lockFlag(x) {
  if (!x.locked) return "";
  return `<span class="flag lock" title="잠금: ${esc(x.lock_note || "")} · 최신화·내리기로 지우지 않습니다">잠금${x.lock_note ? " · " + esc(x.lock_note) : ""}</span>`;
}
function salesFlag(x) {
  return (x.sold_count ? `<span class="flag sold" title="취소·반품을 뺀 판매 수량">판매 ${num(x.sold_count)}</span>` : "")
    + (x.cancel_count ? `<span class="flag" title="취소·반품 수량">취소·반품 ${num(x.cancel_count)}</span>` : "");
}

/* 올린 지 며칠 */
function age(ts) {
  if (!ts) return "";
  const d = Math.floor((Date.now() / 1000 - ts) / 86400);
  return d <= 0 ? "오늘" : `${d}일 전`;
}
function ymd(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
const ORIGIN = { original: "원본", recombine: "재조합", import: "가져옴", ai: "AI", manual: "직접" };

const App = {
  pages: {}, current: null, state: null, stores: [], run: null, listeners: {}, taskSeen: {},

  page(name, def) { this.pages[name] = def; },
  on(evt, fn) { (this.listeners[evt] ||= []).push(fn); },
  off(evt, fn) { this.listeners[evt] = (this.listeners[evt] || []).filter((f) => f !== fn); },
  emit(evt, data) { (this.listeners[evt] || []).forEach((f) => { try { f(data); } catch (e) { console.error(e); } }); },

  async api(path, opts = {}) {
    const init = { ...opts };
    if (opts.json !== undefined) {
      init.method = init.method || "POST";
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(opts.json);
    }
    const r = await fetch(path, init);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `오류 ${r.status}`);
    return j;
  },

  toast(msg, isErr = false) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "toast" + (isErr ? " err" : "");
    t.hidden = false;
    clearTimeout(this._toast);
    this._toast = setTimeout(() => (t.hidden = true), isErr ? 7000 : 3500);
  },

  // ── 화면 이동

  route() {
    const [name, query] = (location.hash.slice(1) || "home").split("?");
    const page = this.pages[name] ? name : "home";
    const params = Object.fromEntries(new URLSearchParams(query || ""));
    $$(".nav-item").forEach((a) => a.classList.toggle("on", a.dataset.page === page));
    if (this.current?.unmount) this.current.unmount();
    this.closeDrawer();
    const view = $("#view");
    view.innerHTML = "";
    view.scrollTop = 0;
    this.current = this.pages[page];
    this.current.mount(view, params);
  },
  go(hash) { if (location.hash === hash) this.route(); else location.hash = hash; },

  // ── 상태

  async refreshState() {
    this.state = await this.api("/api/state");
    const st = this.state.stats;
    const c = $("#conn");
    if (this.state.fake_api) { c.className = "conn warn"; c.textContent = "시연 모드 (네이버 접속 안 함)"; }
    else if (!st.stores) { c.className = "conn warn"; c.innerHTML = '<a href="#stores">스토어를 추가하세요</a>'; }
    else { c.className = "conn ok"; c.textContent = `스토어 ${num(st.stores)}곳`; }
    $("#side-stats").innerHTML =
      `원본 ${num(st.sources)}개 · 이름 후보 ${num(st.names_free)}개<br>` +
      `등록 완료 ${num(st.registered)}건 · 대기 ${num(st.pending)}건<br>` +
      `카테고리 ${this.state.categories ? num(this.state.categories) + "개" : "아직 안 받음"}`;
    this.renderTasks(this.state.tasks);
    return this.state;
  },

  async loadStores() {
    this.stores = await this.api("/api/stores");
    return this.stores;
  },

  // ── 뒤에서 도는 작업

  renderTasks(list) {
    const box = $("#tasks");
    const show = list.filter((t) => t.status === "running" || (t.ended_at && Date.now() / 1000 - t.ended_at < 8));
    box.innerHTML = show.map((t) => {
      const p = t.total ? Math.min(100, (t.done / t.total) * 100) : null;
      const st = { running: "", done: "끝", error: "오류", stopped: "중단됨" }[t.status];
      return `<div class="task ${t.status}">
        <div class="task-top"><b>${esc(t.title)}</b>${t.status === "running"
          ? `<button class="link-btn" data-stop-task="${t.id}">중단</button>` : `<span>${st}</span>`}</div>
        <div class="bar thin">${p != null ? `<div class="bar-ok" style="width:${p}%"></div>` : `<div class="bar-indef"></div>`}</div>
        <div class="task-msg">${esc(t.error || t.message || "준비 중…")}${t.total ? ` · ${num(t.done)}/${num(t.total)}` : ""}</div>
      </div>`;
    }).join("");
    for (const t of list) {
      const prev = this.taskSeen[t.id];
      if (prev === "running" && t.status !== "running") this.taskFinished(t);
      this.taskSeen[t.id] = t.status;
    }
    this._tasksRunning = list.some((t) => t.status === "running");
  },

  taskFinished(t) {
    if (t.status === "error") { this.toast(`${t.title}: ${t.error}`, true); }
    else {
      const r = t.result || {};
      const msg = {
        import: () => `원본 불러오기 끝: 새로 ${num(r.added)}개 · 갱신 ${num(r.updated)}개 · 오류 ${num(r.invalid)}개`,
        names: () => r.not_found !== undefined
          ? `상품명 가져오기 끝: 새 이름 ${num(r.added)}개 · 다른 이름과 중복 ${num(r.dup)}개 · 원본 못 찾음 ${num(r.not_found)}줄`
            + (r.rejected ? ` · 반복·금지 단어로 버림 ${num(r.rejected)}개 (예: ${r.rejected_examples?.[0] || ""})` : "")
          : `상품명 만들기 끝: 새 이름 ${num(r.added)}개` + (r.short ? ` · 단어가 적어 다 못 채운 상품 ${num(r.short)}개` : "")
            + (r.rejected ? ` · 반복·금지 단어로 버림 ${num(r.rejected)}개` : "")
            + (r.failed ? ` · 실패 ${num(r.failed)}개 (${r.errors?.[0] || ""})` : ""),
        keywords: () => `네이버 키워드 끝: 원본 ${num(r.sources)}개 · 검색 ${num(r.api_calls)}번 (저장한 결과 ${num(r.cached)}번) · 단어 ${num(r.words)}개`
          + (r.volumes ? ` · 검색량 ${num(r.volumes)}개` : "") + (r.errors ? ` · 실패 ${r.errors} (${r.error})` : "") + (r.volume_error ? ` · 검색량 실패 (${r.volume_error})` : ""),
        kipris: () => `상표 확인 끝: 조어 ${num(r.checked)}개 확인 · 등록 상표 ${num(r.registered)}개 · 출원 중 ${num(r.pending)}개`
          + (r.in_dict ? ` · 사전 단어라 건너뜀 ${num(r.in_dict)}개` : "")
          + (r.examples?.length ? ` (예: ${r.examples.join(", ")})` : "") + (r.errors ? ` · 오류 ${r.errors}` : ""),
        lexicon: () => `우리말샘: ${num(r.looked)}개 단어를 찾아 ${num(r.found)}개에 유의어가 있었습니다` + (r.errors ? ` · 오류 ${r.errors}` : ""),
        plan: () => `복사 계획 끝: 새로 ${num(r.created)}건${r.revived ? ` · 다시 살림 ${num(r.revived)}건` : ""}` + (r.no_name ? ` · 이름 부족 ${num(r.no_name)}` : "")
          + (r.capacity ? ` · 자리 부족 ${num(r.capacity)}` : "") + (r.exists ? ` · 이미 있음 ${num(r.exists)}` : ""),
        revalidate: () => `다시 검사 끝: ${num(r.total)}개`,
        orders: () => r.rows !== undefined
          ? `판매 이력 파일 끝: ${num(r.rows)}줄 중 복사본과 맞춘 주문 ${num(r.matched)}건 · 못 맞춘 ${num(r.unmatched)}건`
          : `주문 가져오기 끝: 스토어 ${num(r.stores)}곳 · 새 주문 ${num(r.new)}건 · 복사본과 맞춤 ${num(r.matched)}건`
            + (r.errors?.length ? ` · 실패 ${r.errors.length}곳 (${r.errors[0]})` : ""),
      }[t.kind];
      this.toast(msg ? msg() : `${t.title} 끝`);
    }
    this.emit("task-done", t);
  },

  async startTask(promise) {
    try {
      const r = await promise;
      this.taskSeen[r.task] = "running";
      await this.refreshState();
      return r;
    } catch (e) { this.toast(e.message, true); return null; }
  },

  upload(url, file) {
    const fd = new FormData();
    fd.append("file", file);
    return this.startTask(this.api(url, { method: "POST", body: fd }));
  },

  // ── 등록 진행 상황

  renderSideRun() {
    const r = this.run, el = $("#side-run");
    if (!r?.running) { el.hidden = true; return; }
    el.hidden = false;
    const p = r.total ? (r.done / r.total) * 100 : 0;
    el.innerHTML = `<a href="#listings"><div class="sr-top"><span class="spin"></span>
      <b>${r.paused ? "일시정지" : "등록 중"}</b><span>${num(r.done)}/${num(r.total)}</span></div>
      <div class="bar thin"><div class="bar-ok" style="width:${p}%"></div></div>
      <div class="muted small">남은 시간 ${r.eta != null ? dur(r.eta) : "재는 중"}</div></a>`;
  },

  async pollRun() {
    try {
      const was = this.run?.running;
      this.run = await this.api("/api/run");
      this.renderSideRun();
      this.emit("run", this.run);
      if (was && !this.run.running) {
        this.toast(`등록 끝: 성공 ${num(this.run.ok)}건, 실패 ${num(this.run.fail)}건`);
        this.emit("run-done", this.run);
        this.refreshState();
      }
    } catch (e) { /* 서버가 꺼졌을 수 있음 */ }
    setTimeout(() => this.pollRun(), this.run?.running ? 1000 : 3000);
  },

  async pollState() {
    try { await this.refreshState(); } catch (e) { /* 무시 */ }
    setTimeout(() => this.pollState(), this._tasksRunning ? 1200 : 5000);
  },

  // ── 서랍 (오른쪽 상세)

  openDrawer({ title, sub = "", tabs = [], tab, foot = "" }) {
    this._drawer = { tabs, tab: tab || tabs[0]?.key };
    $("#d-title").textContent = title;
    $("#d-sub").textContent = sub;
    $("#d-tabs").innerHTML = tabs.map((t) => `<button data-tab="${t.key}">${esc(t.label)}</button>`).join("");
    $("#d-tabs").hidden = tabs.length < 2;
    $("#d-foot").innerHTML = foot;
    $("#d-foot").hidden = !foot;
    $("#drawer").hidden = false;
    $("#drawer-bg").hidden = false;
    this.drawerTab(this._drawer.tab);
  },
  drawerTab(key) {
    if (!this._drawer) return;
    this._drawer.tab = key;
    $$("#d-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === key));
    const body = $("#d-body");
    body.innerHTML = "";
    body.scrollTop = 0;
    this._drawer.tabs.find((t) => t.key === key)?.render(body);
  },
  closeDrawer() {
    this._drawer = null;
    $("#drawer").hidden = true;
    $("#drawer-bg").hidden = true;
  },

  // ── 창 (가운데)

  openModal({ title, body, buttons = [], wide = false }) {
    $("#m-title").textContent = title;
    const b = $("#m-body");
    b.innerHTML = typeof body === "string" ? body : "";
    if (typeof body === "function") body(b);
    $("#modal").classList.toggle("wide", wide);
    $("#m-foot").innerHTML = buttons.map((x, i) =>
      `<button class="btn ${x.primary ? "primary" : ""} ${x.danger ? "danger" : ""}" data-i="${i}">${esc(x.label)}</button>`).join("");
    $$("#m-foot button").forEach((el) => el.addEventListener("click", async () => {
      const x = buttons[+el.dataset.i];
      if (!x.onClick) return this.closeModal();
      el.disabled = true;
      try { if ((await x.onClick(b)) !== false) this.closeModal(); }
      finally { el.disabled = false; }
    }));
    $("#modal-bg").hidden = false;
    setTimeout(() => $("[autofocus]", b)?.focus(), 50);
  },
  closeModal() { $("#modal-bg").hidden = true; },

  // ── 쪽 넘기기

  pager(el, { page, size, total, onPage }) {
    const pages = Math.max(1, Math.ceil(total / size));
    if (total <= size) { el.innerHTML = total ? `<span class="muted small">${num(total)}개</span>` : ""; return; }
    el.innerHTML = `<button data-p="${page - 1}" ${page <= 0 ? "disabled" : ""}>‹ 이전</button>
      <span class="muted small">${num(page * size + 1)}–${num(Math.min(total, (page + 1) * size))} / ${num(total)}</span>
      <button data-p="${page + 1}" ${page >= pages - 1 ? "disabled" : ""}>다음 ›</button>
      <input type="number" min="1" max="${pages}" value="${page + 1}" aria-label="쪽"> <span class="muted small">/ ${num(pages)}쪽</span>`;
    $$("button", el).forEach((b) => b.addEventListener("click", () => onPage(+b.dataset.p)));
    $("input", el).addEventListener("change", (e) => onPage(Math.min(pages, Math.max(1, +e.target.value)) - 1));
  },

  // ── 파일 끌어다 놓기: 원본인지 상품명인지 묻는다

  askFile(file) {
    this.openModal({
      title: "파일 불러오기",
      body: `<p><b>${esc(file.name)}</b> 파일을 무엇으로 불러올까요?</p>
        <p class="muted small">원본 상품: 수집한 상품 엑셀. 같은 판매자코드는 새로 추가하지 않고 내용만 갱신합니다.<br>
        상품명: 외부 AI 도구 등에서 만든 새 상품명 파일. 판매자코드(또는 원본상품명) 열과 상품명 열이 있어야 합니다.<br>
        판매 이력: 아바닛 등 주문 수집 웹에서 내려받은 주문 파일. 판매된 복사본은 최신화·내리기에서 빠집니다.</p>`,
      buttons: [
        { label: "취소" },
        { label: "판매 이력으로", onClick: () => this.upload("/api/orders/import", file) },
        { label: "상품명 후보로", onClick: () => this.upload("/api/names/import", file) },
        { label: "원본 상품으로", primary: true, onClick: () => this.upload("/api/sources/import", file) },
      ],
    });
  },

  bind() {
    window.addEventListener("hashchange", () => this.route());
    $("#d-close").addEventListener("click", () => this.closeDrawer());
    $("#drawer-bg").addEventListener("click", () => this.closeDrawer());
    $("#d-tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) this.drawerTab(b.dataset.tab); });
    $("#m-close").addEventListener("click", () => this.closeModal());
    $("#modal-bg").addEventListener("mousedown", (e) => { if (e.target.id === "modal-bg") this.closeModal(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") { this.closeModal(); this.closeDrawer(); } });
    $("#tasks").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-stop-task]");
      if (b) { await this.api(`/api/tasks/${b.dataset.stopTask}/stop`, { method: "POST" }); this.toast("중단을 요청했습니다."); }
    });
    let depth = 0;
    document.addEventListener("dragenter", (e) => { if (e.dataTransfer.types.includes("Files")) { depth++; document.body.classList.add("dragging"); } });
    document.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; document.body.classList.remove("dragging"); } });
    document.addEventListener("dragover", (e) => e.preventDefault());
    document.addEventListener("drop", (e) => {
      e.preventDefault(); depth = 0; document.body.classList.remove("dragging");
      if (e.dataTransfer.files[0]) this.askFile(e.dataTransfer.files[0]);
    });
  },

  async init() {
    this.bind();
    await Promise.all([this.refreshState(), this.loadStores()]);
    for (const t of this.state.tasks) this.taskSeen[t.id] = t.status;
    this.route();
    this.pollRun();
    setTimeout(() => this.pollState(), 1500);
  },
};
window.onImgError = onImgError;

/* 상태 칸(누르면 거르기) 그리기 */
function tilesHtml(defs, counts, active) {
  return defs.map((t) => `<button class="tile ${active === t.key ? "on" : ""}" data-filter="${t.key}" style="--dot:${t.dot}">
    <div class="t-label">${t.label}</div><div class="t-num">${num(counts?.[t.key] ?? 0)}</div></button>`).join("");
}

/* 사용량 막대 */
function usageBar(used, cap) {
  const p = cap ? Math.min(100, (used / cap) * 100) : 0;
  const cls = p >= 95 ? "full" : p >= 80 ? "high" : "";
  return `<div class="usage ${cls}"><div style="width:${p}%"></div></div>`;
}
