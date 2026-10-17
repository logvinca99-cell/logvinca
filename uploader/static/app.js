/* 상품 등록기 화면.
 * 서버(web.py)의 /api/* 를 부르고, 등록 중에는 1초마다 진행 상황을 받아 다시 그린다. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n) => (n ?? 0).toLocaleString("ko-KR");
const PAGE_SIZE = 100;

const STATUS = {
  ready: "등록 대기", invalid: "오류", duplicate: "이미 등록", queued: "순서 대기",
  running: "등록 중", success: "등록 완료", fail: "실패",
};
const TILES = [
  { key: "all", label: "전체", dot: "var(--text-2)" },
  { key: "ready", label: "등록 대기", dot: "var(--idle)" },
  { key: "warn", label: "경고 있음", dot: "var(--warn)" },
  { key: "invalid", label: "오류 (고쳐야 함)", dot: "var(--err)" },
  { key: "duplicate", label: "이미 등록됨", dot: "var(--dup)" },
  { key: "success", label: "등록 완료", dot: "var(--ok)" },
  { key: "fail", label: "실패", dot: "var(--err)" },
];

const S = {
  state: null, batches: [], batchId: null, products: [], filter: "all", search: "", page: 0,
  selected: new Set(), run: null, wasRunning: false, drawerPid: null, drawerTab: "info", drawerData: null,
  lastProductsFetch: 0,
};

// ───────────────────────── 공통

async function api(path, opts = {}) {
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
}

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), isErr ? 6000 : 2800);
}

function dur(sec) {
  if (sec == null || !isFinite(sec)) return "-";
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h) return `${h}시간 ${m}분`;
  if (m) return `${m}분 ${s ? s + "초" : ""}`.trim();
  return `${s}초`;
}

function when(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function onImgError(img) {
  img.onerror = null;
  img.src = "data:image/svg+xml;utf8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" fill="#e9edf0"/>' +
    '<path d="M12 27l6-7 4 5 3-3 5 5z" fill="#c3cbd2"/><circle cx="25" cy="15" r="3" fill="#c3cbd2"/></svg>');
}
window.onImgError = onImgError;

// ───────────────────────── 화면 이동

function route() {
  const page = (location.hash || "#work").slice(1);
  $$(".page").forEach((p) => (p.hidden = p.id !== "page-" + page));
  $$(".nav-item").forEach((a) => a.classList.toggle("on", a.dataset.page === page));
  if (page === "runs") loadRuns();
  if (page === "settings") fillSettings();
}
window.addEventListener("hashchange", route);

// ───────────────────────── 상태 / 작업 목록

async function loadState() {
  S.state = await api("/api/state");
  const c = $("#conn");
  if (S.state.fake_api) { c.className = "conn warn"; c.textContent = "시연 모드 (네이버 접속 안 함)"; }
  else if (S.state.has_keys) { c.className = "conn ok"; c.textContent = "API 키 설정됨"; }
  else { c.className = "conn warn"; c.innerHTML = '<a href="#settings">API 키를 설정하세요</a>'; }
  $("#side-stats").innerHTML =
    `누적 등록 ${num(S.state.stats.registered)}개<br>네이버에 올린 이미지 ${num(S.state.stats.images)}장<br>` +
    `카테고리 ${S.state.categories ? num(S.state.categories) + "개 저장됨" : "아직 안 받음"}`;
}

async function loadBatches(selectId) {
  S.batches = await api("/api/batches");
  const sel = $("#batch-select");
  sel.innerHTML = S.batches.map((b) =>
    `<option value="${b.id}">${esc(b.name)} · ${when(b.created_at)}</option>`).join("");
  const keep = selectId ?? S.batchId;
  S.batchId = S.batches.some((b) => b.id === keep) ? keep : (S.batches[0]?.id ?? null);
  if (S.batchId) sel.value = S.batchId;
  $("#empty").hidden = !!S.batchId;
  $("#work-area").hidden = !S.batchId;
  $$("#btn-revalidate, #btn-export, #btn-delete-batch, .batch-pick").forEach((e) => (e.hidden = !S.batchId));
  if (S.batchId) await loadProducts();
}

async function loadProducts() {
  if (!S.batchId) return;
  S.products = await api(`/api/batches/${S.batchId}/products`);
  S.lastProductsFetch = Date.now();
  const valid = new Set(S.products.map((p) => p.id));
  S.selected = new Set([...S.selected].filter((id) => valid.has(id)));
  const b = S.batches.find((x) => x.id === S.batchId);
  $("#batch-meta").textContent = b ? `상품 ${num(S.products.length)}개` : "";
  $("#btn-export").href = `/api/batches/${S.batchId}/export.csv`;
  renderWork();
}

// ───────────────────────── 작업 화면

function counts() {
  const c = { all: S.products.length, ready: 0, warn: 0, invalid: 0, duplicate: 0, success: 0, fail: 0 };
  for (const p of S.products) {
    if (p.status in c) c[p.status]++;
    if (p.status === "queued" || p.status === "running") c.ready++;
    if (p.warnings.length && !["success", "invalid"].includes(p.status)) c.warn++;
  }
  return c;
}

function matches(p) {
  const f = S.filter;
  if (f === "warn" && !(p.warnings.length && !["success", "invalid"].includes(p.status))) return false;
  if (f === "ready" && !["ready", "queued", "running"].includes(p.status)) return false;
  if (!["all", "warn", "ready"].includes(f) && p.status !== f) return false;
  if (S.search) {
    const q = S.search.toLowerCase();
    return (p.name + " " + p.seller_code + " " + p.category + " " + p.row_key).toLowerCase().includes(q);
  }
  return true;
}

function renderWork() {
  const c = counts();
  $("#tiles").innerHTML = TILES.map((t) =>
    `<button class="tile ${S.filter === t.key ? "on" : ""}" data-filter="${t.key}" style="--dot:${t.dot}">
       <div class="t-label">${t.label}</div><div class="t-num">${num(c[t.key])}</div></button>`).join("");

  const list = S.products.filter(matches);
  const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  S.page = Math.min(S.page, pages - 1);
  const shown = list.slice(S.page * PAGE_SIZE, (S.page + 1) * PAGE_SIZE);

  $("#filters").innerHTML = S.selected.size
    ? `<span class="chip on">선택 ${num(S.selected.size)}개</span><button class="chip" id="clear-sel">선택 해제</button>`
    : `<span class="muted small">${num(list.length)}개 표시 · 줄을 누르면 자세히 볼 수 있습니다</span>`;

  $("#rows").innerHTML = shown.length ? shown.map(rowHtml).join("") :
    `<tr class="empty-row"><td colspan="8">조건에 맞는 상품이 없습니다.</td></tr>`;
  $("#check-all").checked = shown.length > 0 && shown.every((p) => S.selected.has(p.id));

  $("#pager").innerHTML = pages > 1 ? Array.from({ length: pages }, (_, i) =>
    `<button data-page="${i}" class="${i === S.page ? "on" : ""}">${i + 1}</button>`).join("") : "";

  renderRunIdle(c);
}

function rowHtml(p) {
  const cat = (p.category || "").split(">");
  const leaf = cat.slice(-2).join(" › ");
  const top = cat.length > 2 ? cat.slice(0, -2).join(" › ") : "";
  let msg = "", msgCls = "";
  if (p.status === "invalid") { msg = p.errors[0] || ""; msgCls = "err"; }
  else if (p.status === "fail") { msg = p.message; msgCls = "err"; }
  else if (p.status === "success") msg = `상품번호 ${p.channel_no}${p.seconds ? ` · ${p.seconds.toFixed(1)}초` : ""}`;
  else if (p.status === "duplicate") msg = p.message;
  const label = p.status === "running" ? (p.stage || STATUS.running) : STATUS[p.status];
  const flags = [
    p.warnings.length && p.status !== "invalid" ? `<span class="flag warn">경고 ${p.warnings.length}</span>` : "",
    p.has_video ? `<span class="flag video">동영상</span>` : "",
  ].join("");
  return `<tr data-id="${p.id}" class="${S.selected.has(p.id) ? "sel" : ""}">
    <td class="w-check" data-stop><input type="checkbox" ${S.selected.has(p.id) ? "checked" : ""} aria-label="선택"></td>
    <td><img class="thumb" loading="lazy" referrerpolicy="no-referrer" src="${esc(p.thumb)}" onerror="onImgError(this)" alt=""></td>
    <td><div class="p-name">${esc(p.name)}</div>
        <div class="p-sub"><span>${esc(p.seller_code || "#" + (p.idx + 1))}</span>${flags}</div></td>
    <td class="cat-td"><div class="cat">${top ? `<div class="cat-top">${esc(top)}</div>` : ""}${esc(leaf)}</div></td>
    <td class="num">${num(p.price)}원</td>
    <td class="num small-td">${p.option_count || "-"}</td>
    <td class="num small-td">${p.image_count}</td>
    <td><span class="badge s-${p.status}">${esc(label)}</span>
        ${msg ? `<div class="s-msg ${msgCls}" title="${esc(msg)}">${esc(msg)}</div>` : ""}</td>
  </tr>`;
}

// ───────────────────────── 등록 패널

function runTargets() {
  if (S.selected.size) {
    return S.products.filter((p) => S.selected.has(p.id) && ["ready", "fail", "duplicate"].includes(p.status));
  }
  return S.products.filter((p) => ["ready", "fail"].includes(p.status));
}

let estTimer, estKey = "";
function renderRunIdle() {
  const running = S.run?.running;
  $("#run-idle").hidden = !!running;
  $("#run-live").hidden = !running;
  if (running) return;
  const t = runTargets();
  const btn = $("#btn-run");
  btn.textContent = S.selected.size ? `▶ 선택한 ${num(t.length)}개 등록` : `▶ 등록 시작 · ${num(t.length)}개`;
  const blocked = !S.state?.has_keys && !S.state?.fake_api;
  btn.disabled = !t.length || blocked;
  $("#btn-run-one").disabled = !t.length || blocked;
  if (blocked) {
    $("#run-est").innerHTML = `등록하려면 먼저 <a href="#settings">설정</a>에서 커머스API 키를 넣어 주세요. 검사와 미리보기는 지금도 됩니다.`;
    return;
  }
  if (!t.length) {
    $("#run-est").innerHTML = S.selected.size ? "선택한 상품 중 등록할 수 있는 상품이 없습니다."
      : "등록할 상품이 없습니다. 오류 상품은 엑셀을 고쳐 다시 불러오세요.";
    return;
  }
  const key = S.batchId + ":" + t.map((p) => p.id).join(",");
  if (key === estKey) return;
  estKey = key;
  clearTimeout(estTimer);
  estTimer = setTimeout(async () => {
    try {
      const e = await api(`/api/batches/${S.batchId}/estimate`, { json: { ids: S.selected.size ? [...S.selected] : null } });
      $("#run-est").innerHTML =
        `예상 시간 <b>약 ${dur(e.seconds)}</b> · 이미지 <b>${num(e.images)}장</b> · 동시 ${e.workers}개<br>` +
        `<span class="muted small">${esc(e.basis)}</span>`;
    } catch (err) { $("#run-est").textContent = ""; }
  }, 250);
}

function renderRun() {
  const r = S.run;
  if (!r) return;
  const mine = r.batch_id === S.batchId;
  if (!r.running || !mine) {
    $("#run-live").hidden = true;
    $("#run-idle").hidden = false;
    if (r.running && !mine) $("#run-est").innerHTML = `<b>다른 작업을 등록하는 중입니다.</b> 끝난 뒤에 시작할 수 있습니다.`;
  } else {
    $("#run-idle").hidden = true;
    $("#run-live").hidden = false;
    $("#r-done").textContent = num(r.done);
    $("#r-total").textContent = num(r.total);
    $("#r-ok").textContent = num(r.ok);
    $("#r-fail").textContent = num(r.fail);
    $("#r-rate").textContent = r.rate_per_min ? `분당 ${r.rate_per_min.toFixed(1)}개` : "재는 중";
    $("#r-eta").textContent = r.paused ? "일시정지" : (r.eta != null ? dur(r.eta) : "재는 중");
    $("#r-img").textContent = num(r.images) + (r.images_reused ? ` (+${num(r.images_reused)} 재사용)` : "");
    $("#bar-ok").style.width = (r.total ? (r.ok / r.total) * 100 : 0) + "%";
    $("#bar-err").style.width = (r.total ? (r.fail / r.total) * 100 : 0) + "%";
    $("#btn-pause").textContent = r.paused ? "▶ 계속" : "일시정지";
    $("#btn-pause").disabled = r.stopping;
    $("#btn-stop").disabled = r.stopping;
    $("#run-state").textContent = r.stopping ? "중단하는 중… 처리 중인 상품까지만 마칩니다."
      : r.paused ? "일시정지됨. 처리 중이던 상품까지만 마칩니다." : `등록 중 · ${dur(r.elapsed)} 지남`;
    $("#current").innerHTML = r.current.map((c) =>
      `<li><span class="spin"></span><span class="c-name">${esc(c.name)}</span><span class="c-stage">${esc(c.stage)}</span></li>`).join("");
  }
  const log = r.log || [];
  $("#log-count").textContent = log.length ? `(${log.length})` : "";
  $("#log").innerHTML = log.slice().reverse().map((l) =>
    `<li class="l-${l.level}"><time>${new Date(l.t * 1000).toLocaleTimeString("ko-KR", { hour12: false })}</time><span>${esc(l.msg)}</span></li>`).join("");
}

async function startRun(limit) {
  const ids = S.selected.size ? [...S.selected] : null;
  const n = limit || runTargets().length;
  if (!limit && n > 1 && !confirm(`${num(n)}개 상품을 스마트스토어에 등록합니다. 계속할까요?`)) return;
  try {
    S.run = await api("/api/run", { json: { batch_id: S.batchId, ids, limit: limit || null } });
    $("#log-box").open = true;
    renderRun();
    await loadProducts();
  } catch (e) { toast(e.message, true); }
}

async function poll() {
  try {
    S.run = await api("/api/run");
    renderRun();
    if (S.run.running && S.run.batch_id === S.batchId && Date.now() - S.lastProductsFetch > 1800) {
      await loadProducts();
      if (S.drawerPid && S.products.find((p) => p.id === S.drawerPid)?.status !== S.drawerData?.status) openDrawer(S.drawerPid, true);
    }
    if (S.wasRunning && !S.run.running) {
      toast(`등록 끝: 성공 ${S.run.ok}개, 실패 ${S.run.fail}개`);
      estKey = "";
      await Promise.all([loadProducts(), loadState(), loadBatches()]);
      if (S.drawerPid) openDrawer(S.drawerPid, true);
    }
    S.wasRunning = S.run.running;
  } catch (e) { /* 서버가 꺼졌을 수 있음 */ }
  setTimeout(poll, S.run?.running ? 1000 : 2500);
}

// ───────────────────────── 상품 상세

async function openDrawer(pid, keepTab) {
  S.drawerPid = pid;
  if (!keepTab) S.drawerTab = "info";
  $("#drawer").hidden = false;
  $("#drawer-bg").hidden = false;
  try {
    S.drawerData = await api(`/api/products/${pid}`);
  } catch (e) { toast(e.message, true); return; }
  renderDrawer();
}

function closeDrawer() {
  S.drawerPid = null;
  S.drawerData = null;
  $("#drawer").hidden = true;
  $("#drawer-bg").hidden = true;
}

function renderDrawer() {
  const d = S.drawerData;
  if (!d) return;
  $("#d-code").textContent = `${d.seller_code || ""}  ·  엑셀 ${d.idx + 2}번째 줄`;
  $("#d-name").textContent = d.name;
  $$("#d-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === S.drawerTab));
  const body = $("#d-body");

  if (S.drawerTab === "info") {
    const notes = [];
    if (d.status === "success") {
      const links = [
        d.store_url && d.channel_no ? `<a href="${esc(d.store_url)}/products/${esc(d.channel_no)}" target="_blank" rel="noopener">스토어에서 보기</a>` : "",
        d.origin_no ? `<a href="https://sell.smartstore.naver.com/#/products/edit/${esc(d.origin_no)}" target="_blank" rel="noopener">스마트스토어센터에서 수정</a>` : "",
      ].filter(Boolean).join(" · ");
      notes.push(`<div class="notice ok"><b>등록 완료</b> · 상품번호 ${esc(d.channel_no)} (원상품 ${esc(d.origin_no)})${links ? "<br>" + links : ""}${d.message ? "<br>" + esc(d.message) : ""}</div>`);
    }
    if (d.status === "fail") notes.push(`<div class="notice err"><b>등록 실패</b><br>${esc(d.message)}</div>`);
    if (d.status === "duplicate") notes.push(`<div class="notice warn"><b>이미 등록된 판매자코드</b><br>${esc(d.message)} 그래도 올리려면 아래 [이 상품만 등록]을 누르세요.</div>`);
    if (d.errors.length) notes.push(`<div class="notice err"><b>고쳐야 등록할 수 있어요</b><ul>${d.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>`);
    if (d.warnings.length) notes.push(`<div class="notice warn"><b>확인해 보세요</b><ul>${d.warnings.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>`);

    const th = d.thumbnails;
    const gallery = th.length ? `<div class="gallery">${th.map((u, i) =>
      `<img ${i === 0 ? 'class="g-main"' : ""} src="${esc(u)}" referrerpolicy="no-referrer" onerror="onImgError(this)" alt="">`).join("")}</div>` : "";

    const kv = [
      ["판매가", num(d.price) + "원"],
      ["카테고리", `${esc(d.category)}${d.category_id ? ` <span class="muted">(${esc(d.category_id)})</span>` : ""}`],
      ...Object.entries(d.fields).map(([k, v]) => [esc(k), esc(v)]),
      ["이미지", `대표·추가 ${Math.min(th.length, 10)}장 + 상세 ${d.detail_images.length}장 → 네이버에 올릴 것 ${d.images_total}장 <span class="muted">(이미 올림 ${d.images_on_naver}장)</span>`],
    ];
    const opts = d.options.length ? `<div><h3 class="sec-title">옵션 · ${esc(d.option_group)} (${d.options.length}개)</h3>
      <table class="opt-table"><tr><th>옵션</th><th style="text-align:right">추가금</th><th style="text-align:right">재고</th></tr>
      ${d.options.map((o) => `<tr><td>${esc(o.optionName1)}${o.optionName2 ? " / " + esc(o.optionName2) : ""}</td>
        <td style="text-align:right">${o.price ? (o.price > 0 ? "+" : "") + num(o.price) + "원" : "-"}</td>
        <td style="text-align:right">${num(o.stockQuantity)}</td></tr>`).join("")}</table></div>` : "";
    const tags = d.tags.length ? `<div><h3 class="sec-title">태그 (${d.tags.length}개${d.tags.length > 10 ? ", 앞 10개만 등록" : ""})</h3>
      <div class="tags">${d.tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div></div>` : "";

    body.innerHTML = notes.join("") + gallery +
      `<dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>` + opts + tags;
  } else if (S.drawerTab === "detail") {
    body.innerHTML = `<p class="muted small" style="margin:0">엑셀의 상세설명을 그대로 보여줍니다. 등록할 때는 이미지 주소만 네이버 주소로 바뀝니다.</p>
      <iframe class="preview" sandbox referrerpolicy="no-referrer"></iframe>`;
    $("iframe", body).srcdoc = `<meta name="referrer" content="no-referrer"><style>body{margin:0;font-family:sans-serif}img{max-width:100%}</style>` + d.detail_html;
  } else {
    const b = JSON.parse(JSON.stringify(d.body));
    const dc = b?.originProduct?.detailContent;
    if (typeof dc === "string" && dc.length > 400) b.originProduct.detailContent = dc.slice(0, 400) + ` …(총 ${num(dc.length)}자)`;
    body.innerHTML = `<p class="muted small" style="margin:0">네이버 커머스API(상품 등록)에 보낼 내용입니다. 아직 네이버에 안 올린 이미지는 원본 주소로 보입니다.</p>
      <pre class="json">${esc(JSON.stringify(b, null, 2))}</pre>`;
  }

  const canRun = ["ready", "fail", "duplicate"].includes(d.status) && !S.run?.running;
  $("#d-foot").innerHTML = `<span class="muted"><span class="badge s-${d.status}">${STATUS[d.status]}</span></span>
    ${canRun ? `<button class="btn primary" id="d-run">이 상품만 등록</button>` : ""}`;
  $("#d-run")?.addEventListener("click", async () => {
    try {
      S.run = await api("/api/run", { json: { batch_id: S.batchId, ids: [d.id] } });
      toast("등록을 시작했습니다.");
      renderRun();
      await loadProducts();
      openDrawer(d.id, true);
    } catch (e) { toast(e.message, true); }
  });
}

// ───────────────────────── 실행 기록

async function loadRuns() {
  const runs = await api("/api/runs");
  await loadState();
  const done = runs.filter((r) => r.ended_at && r.ok);
  const per = done.length ? done.reduce((a, r) => a + (r.ended_at - r.started_at), 0) / done.reduce((a, r) => a + r.ok + r.fail, 0) : null;
  $("#run-tiles").innerHTML = [
    ["누적 등록 상품", num(S.state.stats.registered) + "개"],
    ["네이버에 올린 이미지", num(S.state.stats.images) + "장"],
    ["상품 하나 평균", per ? per.toFixed(1) + "초" : "-"],
    ["1,000개 예상", per ? dur(per * 1000) : "-"],
  ].map(([l, v]) => `<div class="tile static"><div class="t-label">${l}</div><div class="t-num">${v}</div></div>`).join("");
  const live = S.run?.running ? S.run : null;
  $("#run-rows").innerHTML = runs.length ? runs.map((r, i) => {
    if (i === 0 && live && !r.ended_at) Object.assign(r, { ok: live.ok, fail: live.fail, images: live.images });
    const sec = r.ended_at ? r.ended_at - r.started_at : null;
    const n = r.ok + r.fail;
    return `<tr><td>${when(r.started_at)}</td><td>${esc(r.batch_name)} <span class="muted small">${esc(r.note)}</span></td>
      <td class="num">${num(r.total)}</td><td class="num c-ok">${num(r.ok)}</td><td class="num ${r.fail ? "c-err" : ""}">${num(r.fail)}</td>
      <td class="num">${r.ended_at ? dur(sec) : "진행 중"}</td><td class="num">${n && sec ? (sec / n).toFixed(1) + "초" : "-"}</td>
      <td class="num">${num(r.images)}</td></tr>`;
  }).join("") : `<tr class="empty-row"><td colspan="8">아직 등록한 기록이 없습니다.</td></tr>`;
}

// ───────────────────────── 설정

async function fillSettings() {
  await loadState();
  const s = S.state.settings;
  const f = $("#settings");
  for (const el of f.elements) {
    if (!el.name || !(el.name in s)) continue;
    if (el.type === "checkbox") el.checked = !!s[el.name];
    else if (el.dataset.json !== undefined) el.value = JSON.stringify(s[el.name], null, 1);
    else el.value = s[el.name] ?? "";
  }
  const sec = $("#secret-input");
  sec.value = "";
  sec.placeholder = s.has_secret ? "저장됨 · 바꿀 때만 입력" : "";
  $("#save-msg").textContent = "";
}

async function saveSettings() {
  const out = {};
  for (const el of $("#settings").elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.dataset.json !== undefined) {
      try { out[el.name] = el.value.trim() ? JSON.parse(el.value) : {}; }
      catch { toast(`'${el.closest("label").firstChild.textContent.trim()}'의 JSON 형식이 올바르지 않습니다.`, true); return false; }
    } else out[el.name] = el.value.trim();
  }
  try {
    await api("/api/settings", { json: out });
    $("#save-msg").textContent = "저장했습니다 ✓";
    await loadState();
    estKey = "";
    return true;
  } catch (e) { toast(e.message, true); return false; }
}

// ───────────────────────── 엑셀 불러오기

async function uploadFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  toast(`${file.name} 불러오는 중…`);
  try {
    const r = await api("/api/batches", { method: "POST", body: fd });
    S.filter = "all"; S.page = 0; S.selected.clear(); S.search = ""; $("#search").value = "";
    await loadBatches(r.id);
    await loadState();
    const c = counts();
    toast(`불러옴: 등록 대기 ${c.ready}개 · 오류 ${c.invalid}개 · 이미 등록 ${c.duplicate}개`);
    location.hash = "#work";
  } catch (e) { toast(e.message, true); }
}

// ───────────────────────── 이벤트

function bind() {
  $("#file-input").addEventListener("change", (e) => { uploadFile(e.target.files[0]); e.target.value = ""; });
  let dragDepth = 0;
  document.addEventListener("dragenter", (e) => { if (e.dataTransfer.types.includes("Files")) { dragDepth++; document.body.classList.add("dragging"); } });
  document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => {
    e.preventDefault(); dragDepth = 0; document.body.classList.remove("dragging");
    if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
  });

  $("#batch-select").addEventListener("change", async (e) => {
    S.batchId = +e.target.value; S.selected.clear(); S.page = 0; S.filter = "all";
    await loadProducts(); renderRun();
  });
  $("#btn-revalidate").addEventListener("click", async () => {
    try { await api(`/api/batches/${S.batchId}/revalidate`, { json: {} }); estKey = ""; await loadProducts(); toast("다시 검사했습니다."); }
    catch (e) { toast(e.message, true); }
  });
  $("#btn-delete-batch").addEventListener("click", async () => {
    const b = S.batches.find((x) => x.id === S.batchId);
    if (!confirm(`'${b?.name}' 작업을 목록에서 지울까요?\n스마트스토어에 이미 등록된 상품은 지워지지 않습니다.`)) return;
    try { await api(`/api/batches/${S.batchId}`, { method: "DELETE" }); S.batchId = null; await loadBatches(); }
    catch (e) { toast(e.message, true); }
  });

  $("#tiles").addEventListener("click", (e) => {
    const t = e.target.closest("[data-filter]");
    if (!t) return;
    S.filter = t.dataset.filter; S.page = 0; renderWork();
  });
  $("#filters").addEventListener("click", (e) => { if (e.target.id === "clear-sel") { S.selected.clear(); renderWork(); } });
  let searchTimer;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { S.search = e.target.value.trim(); S.page = 0; renderWork(); }, 150);
  });
  $("#pager").addEventListener("click", (e) => {
    const b = e.target.closest("[data-page]");
    if (b) { S.page = +b.dataset.page; renderWork(); $(".table-card").scrollIntoView({ block: "start" }); }
  });
  $("#check-all").addEventListener("change", (e) => {
    const shown = S.products.filter(matches).slice(S.page * PAGE_SIZE, (S.page + 1) * PAGE_SIZE);
    shown.forEach((p) => (e.target.checked ? S.selected.add(p.id) : S.selected.delete(p.id)));
    renderWork();
  });
  $("#rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    const id = +tr.dataset.id;
    if (e.target.closest("[data-stop]")) {
      S.selected.has(id) ? S.selected.delete(id) : S.selected.add(id);
      renderWork();
      return;
    }
    openDrawer(id);
  });

  $("#btn-run").addEventListener("click", () => startRun());
  $("#btn-run-one").addEventListener("click", () => startRun(1));
  $("#btn-pause").addEventListener("click", async () => {
    S.run = await api(`/api/run/${S.run?.paused ? "resume" : "pause"}`, { method: "POST" }); renderRun();
  });
  $("#btn-stop").addEventListener("click", async () => {
    if (!confirm("등록을 중단할까요? 처리 중인 상품까지만 마치고 멈춥니다.")) return;
    S.run = await api("/api/run/stop", { method: "POST" }); renderRun();
  });

  $("#d-close").addEventListener("click", closeDrawer);
  $("#drawer-bg").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  $("#d-tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (b) { S.drawerTab = b.dataset.tab; renderDrawer(); }
  });

  $("#btn-save").addEventListener("click", saveSettings);
  $("#btn-test").addEventListener("click", async () => {
    const m = $("#test-msg");
    if (!(await saveSettings())) return;
    m.textContent = "연결 확인 중…";
    m.style.color = "";
    try {
      const r = await api("/api/settings/test", { json: {} });
      m.textContent = `연결됨 ✓ 카테고리 ${num(r.categories)}개를 받았습니다.`;
      m.style.color = "var(--ok)";
      await loadState();
      if (S.batchId) { await api(`/api/batches/${S.batchId}/revalidate`, { json: {} }); await loadProducts(); }
    } catch (e) { m.textContent = e.message; m.style.color = "var(--err)"; }
  });
}

(async function init() {
  bind();
  await loadState();
  await loadBatches();
  route();
  poll();
})();
