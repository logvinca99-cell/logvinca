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

/* 초까지 시각 (작업 기록·메일함): 2026-10-28 11:44:05 */
function stamp(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function onImgError(img) {
  img.onerror = null;
  img.dataset.broken = "1";   // 크게 보기에서 뺌
  img.src = "data:image/svg+xml;utf8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" fill="#e9edf0"/>' +
    '<path d="M12 27l6-7 4 5 3-3 5 5z" fill="#c3cbd2"/><circle cx="25" cy="15" r="3" fill="#c3cbd2"/></svg>');
}
const img = (url, cls = "thumb") =>
  `<img class="${cls}" loading="lazy" referrerpolicy="no-referrer" src="${esc(url)}" onerror="onImgError(this)" alt="">`;

const STATUS = {
  planned: "등록 대기", queued: "순서 대기", running: "처리 중", success: "판매 중", fail: "실패", deleted: "내림",
};
const OP = { create: "등록", refresh: "최신화", delete: "내리기", reupload: "다시 올리기" };

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
/* 상세 옵션표 모양·강조색 (설정 공통값과 스토어 템플릿) */
const OPT_STYLES = [["strong", "강조: 제목 색 띠 + 옵션 이름 굵게 + 색 테두리"], ["basic", "표로만 (강조 끔)"],
  ["original", "원본 그대로 (안 바꿈 · 네이버에서 옵션 사진이 한 줄에 하나씩 쌓일 수 있음)"]];
const OPT_COLORS = [["#1F2937", "남색"], ["#111111", "검정"], ["#1D4ED8", "파랑"], ["#0B7A5F", "초록"], ["#B4232A", "빨강"],
  ["#C2410C", "주황"], ["#6D28D9", "보라"], ["#BE185D", "분홍"], ["#7C4A1E", "갈색"]];
/* 옵션표 미리보기 (서버 convert.naver_safe_layout과 같은 모양, 사진은 회색 칸) */
function optTablePreview(style, color) {
  if (style === "original") return '<p class="muted small" style="margin:0">원본 상세를 그대로 올립니다. 원본 옵션표는 네이버가 지우는 격자로 짜여 있어 사진이 한 줄에 하나씩 쌓이고 제목이 왼쪽으로 밀릴 수 있습니다.</p>';
  const names = ["옵션 이름 A", "옵션 이름 B"];
  const img = '<div style="height:70px;background:#c9ced6"></div>';
  const cell = (n) => style === "strong"
    ? `<td style="width:50%;border:2px solid ${color};background:#F5F6F8;padding:0;text-align:center;vertical-align:top">${img}<p style="padding:8px 4px;margin:0;font-size:13px;font-weight:700;color:#111">${n}</p></td>`
    : `<td style="width:50%;border:1px solid #EAECF0;padding:0;text-align:center;vertical-align:top">${img}<p style="padding:6px;margin:0;font-size:12px;font-weight:500;color:#111">${n}</p></td>`;
  const head = style === "strong"
    ? `<div style="background:${color};color:#fff;text-align:center;padding:8px"><b style="font-size:15px">옵션 설명</b><span style="font-size:11px"> &nbsp;총 2종</span></div>`
    : '<div style="text-align:center;font-weight:700;color:#111;padding:6px">옵션 설명</div>';
  return `${head}<table style="width:100%;border-collapse:separate;border-spacing:8px;table-layout:fixed;background:#fff"><tr>${names.map(cell).join("")}</tr></table>`;
}
const CUSTOMS_OPTS = [["", "보내지 않음"], ["EXCLUDED", "관부가세 미포함 (구매자 납부)"], ["INCLUDED", "관부가세 포함 (해외직구 노출이면 이것만)"], ["NOT_APPLICABLE", "부과 대상 아님"]];
const REGION = { overseas: "해외", domestic: "국내" };   // 스토어 출고 형태 표시 (해외 파란색 · 국내 초록색)
const regionCls = (s) => (s.ship_region ? `reg-${s.ship_region}` : "");
const SELLER_CENTER = "https://sell.smartstore.naver.com/";
/* 스토어 바로 가기 · 판매자센터 바로 가기 (새 창). 스토어 주소가 없으면 '수정'에서 넣으라고 알려 줌 */
const storeHome = (u) => (/^https?:\/\//.test(u || "") ? u.replace(/\/+$/, "") : u ? `https://smartstore.naver.com/${u.replace(/^\/+|\/+$/g, "")}` : "");
/* 원본 줄·복사본 줄의 바로 가기 (늘 같은 자리): 새 상품 ↗ · 원본 ↗ */
function goLinks({ storeUrl, channelNo, sourceId }) {
  const p = storeHome(storeUrl) && channelNo ? `${storeHome(storeUrl)}/products/${channelNo}` : "";
  return `<div class="go-links">
    ${p ? `<a class="btn sm" href="${esc(p)}" target="_blank" rel="noopener noreferrer" title="네이버에 올라간 이 상품 (새 창)">새 상품 ↗</a>`
      : channelNo === undefined ? "" : `<span class="btn sm disabled" title="${channelNo ? "스토어 주소가 없어 열 수 없음 (스토어 '수정')" : "아직 안 올림"}">새 상품 ↗</span>`}
    <a class="btn sm" href="/api/sources/${sourceId}/origin" target="_blank" rel="noopener noreferrer" title="수집한 원본 상품 페이지 (새 창)">원본 ↗</a></div>`;
}
function storeLinks(s) {
  const url = storeHome(s.store_url);
  return `<span class="st-links">${url
    ? `<a class="btn sm" href="${esc(url)}" target="_blank" rel="noopener" title="${esc(url)}">스토어 ↗</a>`
    : `<span class="btn sm disabled" title="스토어 '수정'에서 스토어 주소를 넣으면 생깁니다 (연결 확인 때 자동으로 채워지기도 함)">스토어 ↗</span>`}
    ${sellerLink(s, SELLER_CENTER, "판매자센터 ↗", "btn sm")}</span>`;
}
/* 판매자센터 링크: 스토어에 크롬 프로필이 있으면 그 프로필로 크롬을 열고(그 스토어 계정), 없으면 지금 브라우저 새 창 */
function sellerLink(s, url, label, cls = "") {
  return s && s.chrome_profile
    ? `<a class="${cls}" href="${esc(url)}" data-seller-sid="${s.id}" title="크롬 프로필 '${esc(s.chrome_profile)}'로 열기 (${esc(s.name)} 계정)">${label}</a>`
    : `<a class="${cls}" href="${esc(url)}" target="_blank" rel="noopener" title="판매자센터 (지금 로그인한 계정으로 열림 · 스토어 '수정'에서 크롬 프로필을 정하면 이 스토어 계정으로 바로 열림)">${label}</a>`;
}
/* 가격 칸: 손님 가격(크게) + 원본 대비 % + 네이버 판매가·표시 할인 (작게) */
function priceCell(x, srcPrice) {
  const fin = x.final ?? x.price;
  const diff = srcPrice ? ((fin - srcPrice) / srcPrice) * 100 : 0;
  return `<td class="num"><b>${num(fin)}원</b><div class="p-sub r">${diff ? (diff > 0 ? "+" : "") + diff.toFixed(1) + "%" : "원본가"}</div>
    ${x.off ? `<div class="p-sub r nowrap" title="네이버 판매가 ${num(x.shown)}원 · 즉시할인 ${num(x.off)}원 → 손님 가격 ${num(fin)}원">판매가 ${num(x.shown)} · ${x.disc_pct}%</div>`
      : x.old_rule ? `<div class="p-sub r" title="예전 규칙으로 올라간 상품이라 네이버 판매가·할인은 판매자센터에서 확인하세요. 최신화·다시 올리기를 하면 지금 기준으로 올라갑니다">예전 규칙</div>` : ""}</td>`;
}
const ORIGIN = { original: "원본", ctx: "AI 키워드", shuffle: "셔플", recombine: "재조합(예전)", import: "가져옴", ai: "AI", manual: "직접" };

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
    const z = $(".img-zoom"); if (z) z.hidden = true;
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
    const bs = $(".brand-sub");
    if (bs) { bs.textContent = `버전 ${this.state.version}`; bs.title = `프로그램 폴더: ${this.state.program_dir}`; }
    const c = $("#conn");
    if (this.state.fake_api) { c.className = "conn warn"; c.textContent = "시연 모드 (네이버 접속 안 함)"; }
    else if (!st.stores) { c.className = "conn warn"; c.innerHTML = '<a href="#stores">스토어를 추가하세요</a>'; }
    else { c.className = "conn ok"; c.textContent = `스토어 ${num(st.stores)}곳`; }
    const mb = $("#nav-mail");
    if (mb) { mb.hidden = !this.state.mail_warn_open; mb.textContent = this.state.mail_warn_open || ""; mb.title = "확인 안 한 경고·제재 메일"; }
    $("#side-stats").innerHTML =
      `원본 ${num(st.sources)}개 · 이름 후보 ${num(st.names_free)}개<br>` +
      `등록 완료 ${num(st.registered)}건 · 대기 ${num(st.pending)}건<br>` +
      `카테고리 ${this.state.categories ? num(this.state.categories) + "개" : "아직 안 받음"}` +
      (st.trash ? `<br><a href="#trash">휴지통 ${num(st.trash)}개</a>` : "");
    this.renderTasks(this.state.tasks);
    const nb = this.state.ctx?.batches?.length || 0;
    if (this._ctxBatches && !nb) this.emit("task-done", { kind: "ctxbatch", status: "done" });   // 일괄 처리가 끝나 이름이 붙음 → 화면 새로
    this._ctxBatches = nb;
    return this.state;
  },

  async loadStores() {
    this.stores = await this.api("/api/stores");
    return this.stores;
  },

  // ── 뒤에서 도는 작업

  /* 오른쪽 아래 현황: 도는 작업, 끝난 작업(1분 동안 결과를, 오류는 닫을 때까지), AI 키워드 일괄 처리·실패 */
  renderTasks(list) {
    const box = $("#tasks");
    const now = Date.now() / 1000;
    this.taskClosed ||= new Set();
    const show = list.filter((t) => !this.taskClosed.has(`t${t.id}`) && (t.status === "running"
      || (t.ended_at && (t.status === "error" ? now - t.ended_at < 600 : now - t.ended_at < 60))));
    const close = (key) => `<button class="link-btn" data-close-task="${key}" title="닫기">✕</button>`;
    box.innerHTML = this.ctxCards(now, close) + show.map((t) => {
      const p = t.total ? Math.min(100, (t.done / t.total) * 100) : t.status !== "running" ? 100 : null;
      const st = { running: "", done: "끝", error: "오류", stopped: "중단됨" }[t.status];
      const msg = t.status === "running" ? (t.message || "준비 중…") + (t.total ? ` · ${num(t.done)}/${num(t.total)}` : "")
        : t.status === "error" ? t.error : this.taskMsg(t);
      return `<div class="task ${t.status}">
        <div class="task-top"><b>${esc(t.title)}</b>${t.status === "running"
          ? `<button class="link-btn" data-stop-task="${t.id}">중단</button>` : `<span>${st} ${close(`t${t.id}`)}</span>`}</div>
        <div class="bar thin">${p != null ? `<div class="bar-ok" style="width:${p}%"></div>` : `<div class="bar-indef"></div>`}</div>
        <div class="task-msg">${esc(msg)}${t.status !== "running" ? ` <a href="#runs" class="small">작업 기록</a>` : ""}</div>
      </div>`;
    }).join("");
    for (const t of list) {
      const prev = this.taskSeen[t.id];
      if (prev === "running" && t.status !== "running") this.taskFinished(t);
      this.taskSeen[t.id] = t.status;
    }
    this._tasksRunning = list.some((t) => t.status === "running");
  },

  /* AI 키워드: 일괄 처리 중(보낸 지 몇 분, 마지막 확인), 실패(사유·다시 받기), 방금 끝남 */
  ctxCards(now, close) {
    const c = this.state?.ctx;
    if (!c) return "";
    const min = (s) => (s < 60 ? `${Math.round(s)}초` : s < 3600 ? `${Math.round(s / 60)}분` : `${(s / 3600).toFixed(1)}시간`);
    let out = "";
    const act = c.batches || [];
    if (act.length) {
      const n = act.reduce((a, b) => a + b.sources, 0), first = Math.min(...act.map((b) => b.created_at));
      const chk = Math.max(...act.map((b) => b.checked_at || 0));
      out += `<div class="task running">
        <div class="task-top"><b>AI 키워드 받는 중 (일괄) · 원본 ${num(n)}개</b><span><button class="link-btn" data-ctx="check">지금 확인</button> · <button class="link-btn" data-ctx="cancel">중지</button></span></div>
        <div class="bar thin"><div class="bar-indef"></div></div>
        <div class="task-msg">보낸 지 ${min(c.now - first)} · 보통 1시간 안, 길면 24시간${chk ? ` · 마지막 확인 ${min(c.now - chk)} 전` : ""} · 끝나면 이름을 만들어 복사본에 자동으로 붙입니다</div></div>`;
    }
    if (c.retry && !this.taskClosed.has(`ctxfail${c.retry}`)) {
      out += `<div class="task error">
        <div class="task-top"><b>AI 키워드 실패 · 원본 ${num(c.retry)}개</b><span><button class="link-btn" data-ctx="retry">다시 받기</button> ${close(`ctxfail${c.retry}`)}</span></div>
        <div class="task-msg">${c.retry_reasons.map((r) => `${esc(r.error || "사유 없음")} (${num(r.n)}개)`).join("<br>")}</div></div>`;
    }
    const l = c.last;
    if (l && l.ended_at && c.now - l.ended_at < 300 && !act.length && !this.taskClosed.has(`ctxrun${l.id}`)) {
      out += `<div class="task done"><div class="task-top"><b>AI 키워드 받기 끝 (${l.mode === "batch" ? "일괄" : "즉시"})</b><span>끝 ${close(`ctxrun${l.id}`)}</span></div>
        <div class="bar thin"><div class="bar-ok" style="width:100%"></div></div>
        <div class="task-msg">받음 ${num(l.ok)}개${l.failed ? ` · 실패 ${num(l.failed)}개` : ""} · 실제 약 ${num(Math.ceil(l.cost_usd * l.rate))}원 · 이름은 복사본에 자동으로 붙었습니다</div></div>`;
    }
    return out;
  },

  taskMsg(t) {
    const r = t.result || {};
    const msg = {
      import: () => `원본 불러오기 끝: 새로 ${num(r.added)}개 · 갱신 ${num(r.updated)}개 · 오류 ${num(r.invalid)}개`,
      names: () => r.not_found !== undefined
        ? `상품명 가져오기 끝: 새 이름 ${num(r.added)}개 · 다른 이름과 중복 ${num(r.dup)}개 · 원본 못 찾음 ${num(r.not_found)}줄`
          + (r.rejected ? ` · 반복·금지 단어로 버림 ${num(r.rejected)}개 (예: ${r.rejected_examples?.[0] || ""})` : "")
        : (r.kw_error ? `네이버 키워드를 못 받음(${r.kw_error}) · ` : "") + `상품명 만들기 끝: 새 이름 ${num(r.added)}개` + (r.short ? ` · 단어가 적어 다 못 채운 상품 ${num(r.short)}개` : "")
          + (r.few_words ? ` · 새 단어 후보가 설정보다 적은 원본 ${num(r.few_words)}개 (단어 사전·우리말샘·네이버 키워드로 늘리세요)` : "")
          + (r.rejected ? ` · 반복·금지 단어로 버림 ${num(r.rejected)}개` : "")
          + (r.failed ? ` · 실패 ${num(r.failed)}개 (${r.errors?.[0] || ""})` : "") + aiMsg(r.ai),
      ctxkw: () => `AI 키워드(즉시) 끝: 원본 ${num(r.ok)}개 받음` + (r.failed ? ` · 재시도 대기 ${num(r.failed)}개 (${r.errors?.[0] || ""})` : "")
        + ` · 실제 약 ${num(r.krw)}원 (예상 ${num(r.est_krw)}원)` + (r.names ? ` · 이름 후보 ${num(r.names.made)}개 · 복사본에 배정 ${num(r.names.assigned)}건` : ""),
      rename: () => r.method === "shuffle" ? `상품명 바꾸기(셔플) 끝: ${num(r.renamed)}건 바꿈` + (r.short ? ` · 못 만든 ${num(r.short)}건은 '이름 변경 필요'` : "") + (r.live ? ` · 이미 올라간 ${num(r.live)}건은 건너뜀` : "")
          + (r.dropped_extra?.length ? ` · 넣을 단어 중 쓸 수 없는 것 뺌: ${r.dropped_extra.join(", ")}` : "")
        : r.method === "ctx"
        ? `상품명 바꾸기(AI 키워드) 끝: ${num(r.renamed)}건 배정` + (r.kept ? ` · 이미 맥락 이름 ${num(r.kept)}건 그대로` : "")
          + (r.fallback ? ` · 키워드 없는 원본은 예비 방식으로 ${num(r.fallback)}건` : "")
          + (r.kw_pending ? ` · AI 키워드 받는 중인 원본 ${num(r.kw_pending)}개는 끝나면 자동으로 붙음 (오른쪽 아래 현황)` : "")
          + (r.kw_failed ? ` · AI 키워드 실패 원본 ${num(r.kw_failed)}개 (오른쪽 아래에서 사유 보고 다시 받기)` : "")
          + (r.kw_none ? ` · 키워드를 아직 안 받은 원본 ${num(r.kw_none)}개` : "")
          + (r.short ? ` · 이름을 못 만든 ${num(r.short)}건은 '이름 변경 필요'` : "") + (r.live ? ` · 이미 올라간 ${num(r.live)}건은 건너뜀` : "")
        : (r.kw_error ? `네이버 키워드를 못 받음(${r.kw_error}) · ` : "") + `상품명 바꾸기 끝: ${num(r.renamed)}건 바꿈` + (r.short ? ` · 후보를 못 만든 ${num(r.short)}건은 그대로 (단어가 적음 → 직접 입력이나 AI)` : "")
        + (r.live ? ` · 이미 올라간 ${num(r.live)}건은 건너뜀` : "")
        + (r.few_words ? ` · 새 단어 후보가 설정보다 적은 원본 ${num(r.few_words)}개` : "") + aiMsg(r.ai),
      bait: () => r.checked !== undefined ? `되돌린 가격 확인 ${num(r.checked)}건 · 고침 ${num(r.fixed)}건` + (r.failed ? ` · 실패 ${num(r.failed)}건 (${r.errors?.[0] || ""})` : "")
        : `원래 가격으로 ${num(r.restored)}건` + (r.failed ? ` · 실패 ${num(r.failed)}건 (${r.errors?.[0] || ""})` : ""),
      dictfile: () => `사전 파일 넣기 끝: 명사 ${num(r.nouns)}개 · 비슷한말 있는 단어 ${num(r.syn_words)}개 (파일 ${num(r.files)}개)`,
      keywords: () => `네이버 키워드 끝: 원본 ${num(r.sources)}개 · 새 단어 ${num(r.words)}개 · 새로 물은 단어 ${num(r.tokens)}개 (저장한 결과 ${num(r.cached)}번)`
        + (r.not_in_dict ? ` · 사전에 없어 뺀 말 ${num(r.not_in_dict)}개` : "")
        + (r.dict_unknown ? ` · 사전 확인 못 해 뺀 말 ${num(r.dict_unknown)}개 (우리말샘 API 키나 사전 파일 필요)` : "")
        + (r.errors ? ` · 실패 ${r.errors} (${r.error})` : ""),
      kipris: () => `상표 확인 끝: 조어 ${num(r.checked)}개 확인 · 등록 상표 ${num(r.registered)}개 · 출원 중 ${num(r.pending)}개`
        + (r.in_dict ? ` · 사전 단어라 건너뜀 ${num(r.in_dict)}개` : "")
        + (r.examples?.length ? ` (예: ${r.examples.join(", ")})` : "") + (r.errors ? ` · 오류 ${r.errors}` : ""),
      lexicon: () => `우리말샘: ${num(r.looked)}개 단어를 찾아 ${num(r.found)}개에 유의어가 있었습니다` + (r.errors ? ` · 오류 ${r.errors}` : ""),
      plan: () => `복사 끝: 새 복사본 ${num(r.created)}건${r.revived ? ` · 다시 살림 ${num(r.revived)}건` : ""}`
        + (r.exists ? ` · 그 스토어에 이미 있어 뺀 것 ${num(r.exists)}` : "")
        + (r.full ? ` · 최대 ${App.state.settings.max_copies}회라 일부·전부 못 보낸 원본 ${num(r.full)}개` : "")
        + (r.capacity ? ` · 스토어 자리 부족 ${num(r.capacity)}` : "") + (r.invalid ? ` · 오류 원본 ${num(r.invalid)}개는 뺌` : "")
        + (r.named ? ` · AI 키워드 이름 바로 붙음 ${num(r.named)}건` : "")
        + (r.created - (r.named || 0) > 0 ? " · 나머지는 복사본 화면 '이름 변경 필요'에서 상품명을 바꾼 뒤 올리세요" : ""),
      mail: () => `메일함: 확인 ${num(r.checked)}통 · 새로 ${num(r.new)}통` + (r.warn ? ` · 경고·제재 ${num(r.warn)}통` : "") + (r.auth ? ` · 인증번호 ${num(r.auth)}통` : ""),
      bulkedit: () => r.test
        ? (r.empty ? "시험할 상품이 없습니다 (고른 스토어에 올린 상품 없음)"
          : r.failed ? `1개로 시험 실패: ${r.store} ${r.origin_no} · ${r.errors?.[0] || ""}`
          : `1개로 시험 끝: ${r.store} 상품 ${r.origin_no} · ${r.changed?.length ? "바꾼 항목 " + r.changed.join(", ") : "이미 같은 값이라 바꾼 것 없음"} · 판매자센터에서 확인 후 '전체 시작'`)
        : `올린 상품 일괄 변경: 바꿈 ${num(r.done)}개 · 이미 같음 ${num(r.same)}개` + (r.failed ? ` · 실패 ${num(r.failed)}개 (${r.errors?.[0] || ""})` : "")
          + (r.left ? ` · 남은 ${num(r.left)}개는 '이어서'로` : ""),
      revalidate: () => `다시 검사 끝: ${num(r.total)}개` + (r.invalid !== undefined ? ` · 오류 ${num(r.invalid)}개` : ""),
      orders: () => r.rows !== undefined
        ? `판매 이력 파일 끝: ${num(r.rows)}줄 중 복사본과 맞춘 주문 ${num(r.matched)}건 · 못 맞춘 ${num(r.unmatched)}건`
        : `주문 가져오기 끝: 스토어 ${num(r.stores)}곳 · 새 주문 ${num(r.new)}건 · 복사본과 맞춤 ${num(r.matched)}건`
          + (r.errors?.length ? ` · 실패 ${r.errors.length}곳 (${r.errors[0]})` : ""),
    }[t.kind];
    return msg ? msg() : `${t.title} 끝`;
  },

  taskFinished(t) {
    if (t.status === "error") { this.toast(`${t.title}: ${t.error}`, true); }
    else if (t.status === "stopped" && t.title.includes("자동 가져오기")) this.toast("주문 자동 가져오기를 중단하고 껐습니다. 다시 켜려면 설정 → 판매 이력의 자동 가져오기 간격을 넣으세요.");
    else {
      this.toast(this.taskMsg(t));
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

  // ── 맥락 키워드: 실행 전 비용 안내 → 일괄(기본) / 즉시

  async ctxConfirm(target, after) {
    let est;
    try { est = await this.api("/api/ctx/estimate", { json: target }); } catch (e) { return this.toast(e.message, true); }
    if (!est.sources) {
      if (est.old && !target.refresh) {   // 예전 지시로 받은 것만 있음 → 자동으로는 안 받고 물어봄
        if (confirm(`고른 원본은 모두 키워드가 있습니다. 그중 ${num(est.old)}개는 예전 지시로 받은 키워드입니다.\n새 지시로 다시 받을까요? (다음 화면에 비용 안내가 나오고, 거기서 시작을 눌러야 받습니다)`))
          return this.ctxConfirm({ ...target, refresh: true }, after);
        if (after) after(false);
        return;
      }
      this.toast(`고른 원본 ${num(est.selected)}개 모두 키워드가 있습니다 · 요청 0건 (AI를 부르지 않음)`);
      if (after) after(false);
      return;
    }
    const s = this.state.settings;
    const [b, i] = await Promise.all([this.api("/api/ctx/estimate", { json: { ...target, mode: "batch" } }),
      this.api("/api/ctx/estimate", { json: { ...target, mode: "instant" } })]);
    const inst = (s.ctx_mode || "instant") === "instant";   // 기본 방식은 설정 → AI 키워드 → 처리 방식
    const line = (e, label) => `${label} 약 <b>${num(e.krw)}원</b> <span class="muted small">(캐시를 다 놓치면 최대 약 ${num(e.krw_max)}원 · 1천 개면 약 ${num(e.per_1k_krw)}원 · 1만 개면 약 ${num(e.per_10k_krw)}원)</span>`;
    this.openModal({
      title: "AI 키워드 받기 · 비용 안내",
      body: `<div class="form">
        <dl class="kv">
          <dt>대상 원본</dt><dd><b>${num(est.sources)}개</b> <span class="muted small">(고른 ${num(est.selected)}개 중 이미 키워드가 있는 ${num(est.have)}개 제외${target.refresh ? " · 예전 지시로 받은 것 포함" : ""})</span>
            ${est.old ? `<br><span class="small">예전 지시로 받은 원본 <b>${num(est.old)}개</b>는 다시 받지 않습니다. <a href="#" id="cm-refresh">이것도 새 지시로 함께 다시 받기</a></span>` : ""}</dd>
          <dt>요청 수</dt><dd>${num(est.requests)}건 <span class="muted small">(요청 1건에 원본 ${num(s.ctx_per_request)}개)</span></dd>
          <dt>예상 토큰</dt><dd>입력 ${num(est.in_tok)} · 출력 ${num(est.out_tok)}</dd>
          <dt>예상 비용</dt><dd>${line(b, "일괄")}<br>${line(i, "즉시")}<br><span class="muted small">${esc(est.model)} · 환율 ${num(est.rate)}원 · 지시문 약 ${num(est.sys_tok)}토큰(처음 한 번 기억, 이후 0.1배) + 원본당 입력 약 45 · 출력 약 130토큰 기준 어림값</span></dd>
        </dl>
        ${est.has_key ? "" : `<p class="c-err small">설정 → AI 상품명에 Anthropic API 키를 먼저 넣어야 합니다.</p>`}
        ${est.pending ? `<p class="muted small">지금 일괄 처리 중인 원본 ${num(est.pending)}개는 다시 보내지 않습니다.</p>` : ""}
        <div class="radio-cards">
          <label><input type="radio" name="cm" value="batch" ${!inst ? "checked" : ""}><div><b>일괄 처리 (50% 할인)</b>
            <span class="muted small">결과가 오기까지 몇 분~몇 시간. 프로그램을 꺼도 다시 켜면 이어서 확인합니다. 결과가 오면 이름 후보 2개를 만들고 이름 없는 복사본에 바로 배정합니다.</span></div></label>
          <label><input type="radio" name="cm" value="instant" ${inst ? "checked" : ""}><div><b>즉시</b>
            <span class="muted small">1~2분 안에 받습니다. 첫 요청 1개로 지시문을 캐시에 기억시킨 뒤 나머지를 한꺼번에 보냅니다 (요금은 일괄의 약 2배 — 원본 ${num(est.sources)}개면 차이 약 ${num(Math.max(0, i.krw - b.krw))}원).</span></div></label>
        </div>
        <p class="muted small">처음 골라져 있는 방식은 <a href="#settings">설정 → 상품명 → AI 키워드 → 처리 방식</a>에서 바꿉니다. 끝나면 실제 비용(응답의 사용량 기준)을 실행 기록에 남깁니다.</p></div>`,
      buttons: [{ label: "취소", onClick: () => { if (after) after(false); } }, { label: "키워드 받기 시작", primary: true, onClick: async (m) => {
        const mode = $("input[name=cm]:checked", m).value;
        try {
          if (mode === "instant") {
            const t = await this.startTask(this.api("/api/ctx/start", { json: { ...target, mode } }));
            if (after) after(!!t, mode);
            return !!t;
          }
          const r = await this.api("/api/ctx/start", { json: { ...target, mode } });
          this.toast(r.started ? `일괄 처리를 보냈습니다: 원본 ${num(r.sources)}개 · 요청 ${num(r.requests)}건 (예상 약 ${num(r.est_krw)}원). 오른쪽 아래에서 진행을 볼 수 있고, 끝나면 이름이 자동으로 붙습니다.` : r.message);
          this.refreshState();
          if (after) after(true, mode);
          return true;
        } catch (e) { this.toast(e.message, true); return false; }
      } }],
    });
    $("#cm-refresh")?.addEventListener("click", (e) => { e.preventDefault(); this.closeModal(); this.ctxConfirm({ ...target, refresh: true }, after); });
  },

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

  /* 네이버 카테고리 직접 정하기 (인증 때문에 안 올라가는 카테고리 등). target: /api/sources/category에 보낼 대상
     ({ids: [원본 번호]} 또는 {listing_filter: 복사본 조건}). 저장하면 그 원본(들)에 적용 → 그 원본의 모든 복사본이 다음 등록부터 이 카테고리 */
  pickCategory({ target, current = "", excel = "", what = "", after }) {
    let chosen = "";
    this.openModal({
      title: "카테고리 바꾸기", wide: true,
      body: `<div class="form">
        <p class="small" style="margin:0">${what ? esc(what) + " · " : ""}고른 카테고리는 <b>원본에 저장</b>되어, 그 원본으로 만든 <b>모든 스토어 복사본</b>이 다음에 올릴 때(실패 다시 올리기 포함) 이 카테고리로 올라갑니다. 엑셀을 다시 불러와도 남습니다.</p>
        ${current ? `<p class="small" style="margin:0">지금: <b>${esc(current)}</b>${excel && excel !== current ? ` <span class="muted">(엑셀: ${esc(excel)})</span>` : ""}</p>` : ""}
        <label class="field">네이버 카테고리 찾기 <span class="muted">(띄어 쓴 단어가 모두 들어간 것)</span>
          <input id="pc-q" placeholder="예) 미용 의자" autofocus></label>
        <div id="pc-hits" class="pc-hits"></div>
        <p class="small" id="pc-chosen">고른 카테고리: <span class="muted">없음</span></p></div>`,
      buttons: [
        { label: "취소" },
        ...(excel && excel !== current ? [{ label: "엑셀 카테고리로 되돌리기", onClick: async () => this._saveCategory(target, "", after) }] : []),
        { label: "이 카테고리로 저장", primary: true, onClick: async () => {
          if (!chosen) { this.toast("목록에서 카테고리를 골라 주세요.", true); return false; }
          return this._saveCategory(target, chosen, after);
        } },
      ],
    });
    let timer;
    $("#pc-q").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = e.target.value.trim();
        const hits = q ? await this.api(`/api/categories/search?q=${encodeURIComponent(q)}`) : [];
        $("#pc-hits").innerHTML = hits.map((h) => `<button type="button" class="cm-hit" data-cat="${esc(h)}">${esc(h)}</button>`).join("")
          || (q ? '<span class="muted small">없음 — 다른 단어로 찾아 보세요 (카테고리 목록이 오래됐으면 원본 상품 → 카테고리 맞추기에서 다시 받기)</span>' : "");
      }, 250);
    });
    $("#pc-hits").addEventListener("click", (e) => {
      const h = e.target.closest("[data-cat]");
      if (!h) return;
      chosen = h.dataset.cat;
      $$("#pc-hits .cm-hit").forEach((x) => x.classList.toggle("on", x === h));
      $("#pc-chosen").innerHTML = `고른 카테고리: <b>${esc(chosen)}</b>`;
    });
  },
  async _saveCategory(target, category, after) {
    try {
      const r = await this.api("/api/sources/category", { json: { ...target, set_category: category } });
      this.toast(category ? `원본 ${num(r.count)}개의 카테고리를 '${category}'(으)로 정했습니다. 실패한 복사본은 시작에서 '실패'를 골라 다시 올리세요.`
        : `원본 ${num(r.count)}개를 엑셀 카테고리로 되돌렸습니다.`);
      if (after) after(r);
      return true;
    } catch (e) { this.toast(e.message, true); return false; }
  },

  /* 한 번 더 묻는 창: 확인 버튼(빨강)을 눌러야 true */
  confirmDanger({ title, body, ok = "삭제합니다" }) {
    return new Promise((resolve) => {
      let done = false;
      const end = (v) => { if (!done) { done = true; resolve(v); } };
      this.openModal({
        title, body: `<div class="form">${body}</div>`,
        buttons: [{ label: "취소", onClick: () => { end(false); } }, { label: ok, danger: true, primary: true, onClick: () => { end(true); } }],
      });
      const obs = new MutationObserver(() => { if ($("#modal-bg").hidden) { obs.disconnect(); end(false); } });
      obs.observe($("#modal-bg"), { attributes: true, attributeFilter: ["hidden"] });
    });
  },

  // ── 대량 목록: 위에 붙는 막대 (선택 상태 + 할 일 버튼 + 쪽 넘기기)
  //   o: { count, selAll, total, unit, pageChecked, actions: [{ id, label, primary, danger, title, always }],
  //        page, size, onPageCheck(bool), onAll(), onClear(), onAction(id), onPage(p), onSize(n) }

  listBar(el, o) {
    const unit = o.unit || "개";
    const n = o.count || 0;
    const acts = (o.actions || []).map((x) => x === "|" ? `<span class="lb-sep"></span>`
      : `<button class="btn ${x.primary ? "primary" : ""} ${x.danger ? "danger" : ""}" data-act="${x.id}" ${n || x.always ? "" : "disabled"}
          ${x.title ? `title="${esc(x.title)}"` : ""}>${esc(x.label)}</button>`).join("");
    el.innerHTML = `<div class="lb-row">
        <div class="lb-left">
          <label class="lb-check"><input type="checkbox" data-lb="page" ${o.pageChecked ? "checked" : ""} ${o.selAll ? "disabled" : ""}>이 쪽 전체</label>
          ${n ? `<span class="lb-count">${o.selAll ? `조건에 맞는 ${num(n)}${unit} 전체` : `${num(n)}${unit}`} 선택됨<button data-lb="clear" title="선택 해제" aria-label="선택 해제">✕</button></span>`
            : `<span class="lb-none">선택한 ${esc(o.what || "상품")}이 없습니다</span>`}
          ${!o.selAll && o.total ? `<button class="btn sm outline" data-lb="all">조건에 맞는 ${num(o.total)}${unit} 모두 선택</button>` : ""}
        </div>
        <div class="lb-right">${acts}</div>
      </div>
      <div class="lb-row"><div></div><div class="pg" data-pgbox></div></div>`;
    this.pagerBar($("[data-pgbox]", el), o);
    $("[data-lb=page]", el).addEventListener("change", (e) => o.onPageCheck(e.target.checked));
    $("[data-lb=clear]", el)?.addEventListener("click", () => o.onClear());
    $("[data-lb=all]", el)?.addEventListener("click", () => o.onAll());
    $$("[data-act]", el).forEach((b) => b.addEventListener("click", () => o.onAction(b.dataset.act)));
  },

  /* 쪽 넘기기: 총 N개 · [100]개씩 · « ‹ [3] / 120쪽 › » */
  pagerBar(el, { page, size, total, onPage, onSize, unit = "개" }) {
    const pages = Math.max(1, Math.ceil(total / size));
    el.innerHTML = `<span>총 <b>${num(total)}</b>${unit}</span>
      <label><select data-pg="size">${[50, 100, 200, 500].map((x) => `<option value="${x}" ${x === size ? "selected" : ""}>${x}</option>`).join("")}</select> ${unit}씩 보기</label>
      <span class="pg-nav">
        <button data-p="0" ${page <= 0 ? "disabled" : ""} title="처음">«</button>
        <button data-p="${page - 1}" ${page <= 0 ? "disabled" : ""} title="이전 쪽">‹</button>
        <input data-pg="page" type="number" min="1" max="${pages}" value="${page + 1}" aria-label="쪽 번호 (엔터로 이동)"> / <b>${num(pages)}</b>쪽
        <button data-p="${page + 1}" ${page >= pages - 1 ? "disabled" : ""} title="다음 쪽">›</button>
        <button data-p="${pages - 1}" ${page >= pages - 1 ? "disabled" : ""} title="마지막">»</button>
      </span>`;
    $$("[data-p]", el).forEach((b) => b.addEventListener("click", () => onPage(+b.dataset.p)));
    const go = (e) => onPage(Math.min(pages, Math.max(1, +e.target.value || 1)) - 1);
    $("[data-pg=page]", el).addEventListener("change", go);
    $("[data-pg=page]", el).addEventListener("keydown", (e) => { if (e.key === "Enter") go(e); });
    $("[data-pg=size]", el).addEventListener("change", (e) => onSize(+e.target.value));
  },

  pageSize(key, def = 100) {
    try { return +localStorage.getItem("size:" + key) || def; } catch (e) { return def; }
  },
  savePageSize(key, n) { try { localStorage.setItem("size:" + key, n); } catch (e) { /* 무시 */ } },

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
      const cl = e.target.closest("[data-close-task]");
      if (cl) { (this.taskClosed ||= new Set()).add(cl.dataset.closeTask); this.renderTasks(this.state.tasks); return; }
      const cx = e.target.closest("[data-ctx]");
      if (cx) {
        try {
          if (cx.dataset.ctx === "check") {
            const r = await this.api("/api/ctx/check", { json: {} });
            this.toast(r.ended ? `일괄 처리 끝: 키워드 받은 원본 ${num(r.ok)}개` + (r.failed ? ` · 실패 ${num(r.failed)}개` : "") : "아직 처리 중입니다 (Anthropic 쪽에서 처리 중).");
          } else if (cx.dataset.ctx === "cancel") {
            if (!confirm("진행 중인 AI 키워드 일괄 처리를 중지할까요? 이미 끝난 결과는 저장하고, 나머지 원본은 실패(다시 받기)로 둡니다.")) return;
            await this.api("/api/ctx/cancel", { json: {} });
            this.toast("중지를 요청했습니다.");
          } else if (cx.dataset.ctx === "retry") {
            this.ctxConfirm({ retry: true });
          }
        } catch (err) { this.toast(err.message, true); }
        this.refreshState();
        return;
      }
      const b = e.target.closest("[data-stop-task]");
      if (b) { await this.api(`/api/tasks/${b.dataset.stopTask}/stop`, { method: "POST" }); this.toast("중단을 요청했습니다."); }
    });
    // 목록의 상품 이미지에 마우스를 올리면 크게 보기
    const zoom = document.createElement("div");
    zoom.className = "img-zoom"; zoom.hidden = true;
    document.body.appendChild(zoom);
    document.addEventListener("mouseover", (e) => {
      const im = e.target.closest?.("table.grid img.thumb");
      if (!im || !im.src || im.dataset.broken) return;
      zoom.innerHTML = `<img referrerpolicy="no-referrer" src="${esc(im.src)}" alt="">`;
      const r = im.getBoundingClientRect(), W = 360;
      const left = r.right + 12 + W < innerWidth ? r.right + 12 : Math.max(8, r.left - W - 12);
      zoom.style.left = `${left}px`;
      zoom.style.top = `${Math.max(8, Math.min(innerHeight - W - 8, r.top + r.height / 2 - W / 2))}px`;
      zoom.hidden = false;
    });
    document.addEventListener("mouseout", (e) => { if (e.target.closest?.("table.grid img.thumb")) zoom.hidden = true; });
    window.addEventListener("scroll", () => { zoom.hidden = true; }, { passive: true });
    // 화면 맨 위 제목·조작 줄은 스크롤해도 붙어 있다. 그 높이만큼 목록 막대·설정 탭을 아래에 붙인다.
    const head = () => $("#view .page-head");
    const ro = new ResizeObserver(() => { const h = head(); if (h) document.documentElement.style.setProperty("--head-h", h.offsetHeight + "px"); });
    new MutationObserver(() => { ro.disconnect(); const h = head(); if (h) ro.observe(h); }).observe($("#view"), { childList: true });
    window.addEventListener("scroll", () => head()?.classList.toggle("stuck", window.scrollY > 4), { passive: true });
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
    // 판매자센터 링크(크롬 프로필이 정해진 스토어): 프로그램이 그 프로필로 크롬을 연다. 못 열면 지금 브라우저로
    document.addEventListener("click", async (e) => {
      const a = e.target.closest("a[data-seller-sid]");
      if (!a) return;
      e.preventDefault();
      try {
        const r = await this.api(`/api/stores/${a.dataset.sellerSid}/open_seller`, { json: { url: a.href } });
        if (r.opened) { this.toast("크롬 프로필로 판매자센터를 열었습니다."); return; }
        this.toast((r.reason || "크롬으로 열지 못했습니다.") + " 이 브라우저로 엽니다.", true);
      } catch (err) { this.toast(err.message, true); }
      if (!window.open(a.href, "_blank")) this.toast("팝업이 막혔습니다. 브라우저 주소창 오른쪽에서 팝업을 허용해 주세요.", true);
    });
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

/* 재조합 AI 단어 받은 결과 한 줄 (요금은 1달러 1,400원으로 어림) */
function aiMsg(a) {
  if (!a) return "";
  const parts = [];
  if (a.asked) parts.push(`AI 단어 새로 받은 원본 ${num(a.asked)}개 (요청 ${num(a.calls)}번, 약 ${num(Math.ceil((a.cost_usd || 0) * 1400))}원)`);
  if (a.bank) parts.push(`단어 은행으로 채운 원본 ${num(a.bank)}개 (AI 안 부름)`);
  if (a.error) parts.push(a.error);
  return parts.length ? " · " + parts.join(" · ") : "";
}

/* 등록 상품명을 원본과 비교해 색으로: 같은 자리 / 자리만 바뀜 / AI 단어 / 직접 넣은 단어, 아래에 빠진 원본 단어 */
/* 상품명 비교 색칠: 서버가 정한 단어별 역할(nd = {parts:[[단어, 역할]], gone:[빠진 원본 단어]})을 그대로 그린다.
   목록·상세·원본 창 모두 같은 결과를 쓰므로 색이 화면마다 달라지지 않는다. */
const ND_ROLE = {
  fixed: ["nd-fixed", "앞 고정 단어 (원본 앞 단어 그대로 · A는 4개, B는 3개)"], keep: ["nd-keep", "지킨 원본 핵심 단어 (AI가 고른 keep)"],
  orig: ["nd-orig", "그 밖의 원본 단어"], core: ["nd-core", "AI 다른 이름·용도 (보라)"], ctx: ["nd-ai", "AI 맥락 (장소·사람·용도)"],
  ai: ["nd-ai", "AI가 넣은 말 (AI로 짓기 · 키워드를 다시 받기 전 예전 키워드)"],
  add: ["nd-add", "직접 넣은 단어 (원본에도 AI 키워드에도 없음: 직접 고친 이름 · 셔플의 '넣을 단어')"],
  same: ["nd-orig", "원본 단어"], move: ["nd-orig", "원본 단어"],
};
function nameDiff(nd) {
  if (!nd || !nd.parts) return "";
  const html = nd.parts.map(([w, r]) => { const [c, t] = ND_ROLE[r] || ND_ROLE.add; return `<span class="${c}" title="${t}">${esc(w)}</span>`; }).join(" ");
  return `<div class="nd">${html}</div>${nd.gone?.length ? `<div class="nd-gone">빠진 원본 단어: ${nd.gone.map((w) => `<s>${esc(w)}</s>`).join("")}</div>` : ""}`;
}

const ND_LEGEND = `<div class="nd-legend"><span class="nd-fixed">앞 고정</span><span class="nd-keep">원본 핵심(keep)</span>
  <span class="nd-orig">원본 단어</span><span class="nd-core">AI 다른 이름</span><span class="nd-ai">AI 맥락</span>
  <span class="nd-add" title="원본에도 AI 키워드에도 없는 단어: 직접 고친 이름이나 셔플의 '넣을 단어'에 적은 것">직접 넣은 단어</span><span><s>빠진 원본 단어</s></span></div>`;

/* 스토어 목록을 사업자별로 묶기 (순서는 서버가 사업자·스토어 순서대로 줌) → [[사업자 이름, [스토어…]], …] */
function byBusiness(stores) {
  const out = [];
  for (const s of stores) {
    const k = s.business_name || "사업자 없음";
    const last = out[out.length - 1];
    if (last && last[0] === k) last[1].push(s); else out.push([k, [s]]);
  }
  return out;
}

const NAVER_STATUS = { SALE: "판매 중", SUSPENSION: "판매중지", OUTOFSTOCK: "품절", WAIT: "판매 대기", CLOSE: "판매 종료",
  PROHIBITION: "판매 금지", UNADMISSION: "승인 대기", REJECTION: "승인 거부", DELETE: "삭제", UNKNOWN: "상태 모름" };

/* 스토어 사용량: 큰 숫자 + 막대(판매 중 / 고구마 / 등록 대기) + 범례. edit=true면 고구마 수 고치기 버튼 */
function storeUsage(s, edit = false) {
  const cap = Math.max(1, s.capacity);
  const goguma = Math.min(s.goguma || 0, s.on_naver);
  const sale = Math.max(0, s.on_naver - goguma);
  const pend = s.n_pending || 0;
  const pct = Math.round((s.used / cap) * 1000) / 10;
  const cls = pct >= 95 ? "full" : pct >= 80 ? "warn" : "";
  const w = (n) => `${Math.min(100, (n / cap) * 100)}%`;
  const gtxt = `고구마 ${num(goguma)}${s.goguma_manual != null ? " (직접)" : s.naver_suspended != null ? "" : " (확인 전)"}`;
  return `<div class="us ${cls}">
    <div class="us-top"><b>${num(s.used)}</b><span class="muted"> / ${num(s.capacity)}</span><span class="us-pct">${pct}%</span></div>
    <div class="us-bar"><i class="u-sale" style="width:${w(sale)}"></i><i class="u-goguma" style="width:${w(goguma)}"></i><i class="u-pend" style="width:${w(pend)}"></i></div>
    <div class="us-free">남은 자리 <b>${num(s.free)}</b></div>
    <div class="us-legend"><span title="네이버에 있는 상품 중 전시중지(고구마)를 뺀 것 (판매 중·판매중지·품절 등)"><i class="u-sale"></i>상품 ${num(sale)}</span>
      ${edit ? `<button class="us-goguma" data-goguma="${s.id}" title="전시중지(고구마) 상품 수 고치기"><i class="u-goguma"></i>${gtxt} ✎</button>` : `<span><i class="u-goguma"></i>${gtxt}</span>`}
      <span><i class="u-pend"></i>등록 대기 ${num(pend)}</span></div>
  </div>`;
}

/* 연결 확인 때 센 네이버 상태별 상품 수 (판매자센터와 비교용) */
function naverStatusLine(s) {
  let st = {};
  try { st = JSON.parse(s.naver_status || "{}"); } catch (e) { st = {}; }
  const parts = Object.entries(st).filter(([k, v]) => !k.startsWith("_") && v).sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${NAVER_STATUS[k] || k} ${num(v)}`);
  const hasDisp = Object.keys(st).some((k) => k.startsWith("_disp_"));
  const disp = hasDisp ? ` · 전시중지(고구마) ${num(st._disp_SUSPENSION || 0)}` : st._keys ? " · ⚠ 전시 상태를 못 받음 (고구마는 ✎로 직접)" : "";
  return parts.length ? `네이버 ${num(st._total || s.naver_count)}개: ${parts.join(" · ")}${disp}` : "";
}
