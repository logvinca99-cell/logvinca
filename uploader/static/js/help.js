/* 용어 설명: 프로그램에 나오는 말과 기능을 한곳에 (화면 곳곳의 ⓘ, 2차 확인 화면의 '용어 설명'도 이 내용을 씀).
   화면마다 맨 위 한 줄 안내(GUIDES)도 여기. */
"use strict";

const TERMS = [
  // [용어, 묶음, 설명(한 줄), 같은 말(화면에서 이 말에도 ⓘ)]
  ["원본", "상품·상품명", "업스타에 넣은 상품. 복사본의 바탕이고 원본 자체는 올라가지 않음."],
  ["복사본", "상품·상품명", "원본을 한 스토어에 올리려고 만든 것. 스토어 1곳당 1개."],
  ["타스토어 원본 상품명", "상품·상품명", "셀업 등으로 가져온 남의 상품명. 절대 올리지 않음."],
  ["업스타 기준상품명", "상품·상품명", "원본을 구분하는 이름. 완전히 같으면 같은 원본.", ["기준상품명"]],
  ["후보상품명①번·②번", "상품·상품명", "스토어에 실제로 올라가는 이름 칸. 스토어 1곳당 1칸.", ["후보상품명", "후보상품명①번", "후보상품명②번"]],
  ["ai상품명A·B", "상품·상품명", "AI 키워드로 조립한 이름. ①·②를 채우는 재료.", ["ai상품명", "ai상품명A", "ai상품명B"]],
  ["완성 상품명", "상품·상품명", "이미 바꿔 둔 이름(이름 완성 상품·판매 중 상품 연결). 그대로 ①번 — 차이는 이미 올라갔냐 뿐."],
  ["직접 입력 상품명", "상품·상품명", "직접 적거나 고친 이름."],
  ["AI 키워드", "상품·상품명", "AI가 원본마다 한 번 골라 주는 단어. 여기서 ai상품명을 조립함(비용은 원본당 1번)."],
  ["셔플", "상품·상품명", "단어 순서를 섞어 이름 만들기(비용 없음)."],
  ["금지어", "상품·상품명", "상품명에 넣지 않는 단어(상표·위험 단어)."],
  ["상표 단어", "상품·상품명", "키프리스로 상표 확인된 단어. 기준상품명에 있으면 만들기 전에 알려 주고 빼고 만들기·무시하고 넣기·건너뛰기 중 고름.", ["상표"]],
  ["AI 키워드 새로 받기", "상품·상품명", "이미 받은 원본도 키워드를 다시 받아 안 쓴 ai상품명을 새로 만들기(비용 듦, 즉시·일괄 고름).", ["키워드 새로 받기"]],
  ["상품명 중복", "상품·상품명", "띄어쓰기까지 완전히 같은 이름. 전체 스토어 통틀어 한 번만 씀."],
  ["대표 이미지 겹침", "상품·상품명", "이름은 다른데 대표 이미지가 같은 상품. 알려만 줌.", ["이미지 겹침", "대표 이미지 주소 겹침"]],
  ["이름 변경 필요", "상품·상품명", "후보상품명이 아직 없는 복사본. 올리지 않음.", ["상품명 변경 필요"]],
  ["기준 가격", "가격", "원본에 저장된 손님 가격. 모든 스토어 가격의 출발점."],
  ["스토어 가격 차이 %", "가격", "그 스토어만 기준 가격·옵션 추가금에 더하거나 빼는 %. 같은 상품이 스토어마다 같은 가격이 되지 않게 조금씩 다르게.", ["가격 차이"]],
  ["손님 가격", "가격", "손님이 실제로 내는 금액 = 기준 가격 × (1 + 스토어 가격 차이 %)."],
  ["표시 할인율", "가격", "네이버에 보이는 할인 %. 손님 가격은 바뀌지 않음.", ["네이버 판매가", "즉시할인"]],
  ["가격 확인 필요", "가격", "네이버 가격(연결 확인 때 읽음)이 업스타 가격과 다른 판매 중 상품. 업스타 가격으로 맞추거나 네이버 가격을 새 기준 가격으로.", ["가격 다름"]],
  ["역마진", "가격", "지금 가격으로는 손해인 상태. [기준 가격 수정]으로 고침."],
  ["대기", "등록", "할 일(새 등록·최신화·내리기)이 걸려 [시작]을 기다리는 상태.", ["등록 대기"]],
  ["올릴 준비", "등록", "후보상품명 있음 + 검수 완료 + 아직 안 올린 복사본."],
  ["최신화", "등록", "같은 이름으로 내렸다가 다시 올리기(상품번호가 바뀜)."],
  ["다시 올리기", "등록", "내렸거나 실패한 복사본을 같은 이름으로 다시 올리기."],
  ["내리기", "등록", "네이버에서 지우기. 복사본은 '내림'으로 남음.", ["내림"]],
  ["원본으로 되돌리기", "등록", "안 올린·내린 복사본을 없애 그 스토어 자리를 비움."],
  ["다른 스토어로 보내기", "등록", "안 올린·내린 복사본을 다른 스토어 대기로 옮김."],
  ["판매자 관리코드", "등록", "'스토어코드-원본번호-회차'. 업스타가 붙임.", ["판매자코드", "관리코드"]],
  ["상품번호", "등록", "네이버가 붙인 번호. 다시 올리면 바뀜."],
  ["회차", "등록", "같은 스토어에 다시 올린 횟수(관리코드 끝 숫자)."],
  ["잠금", "보호·검수", "팔린 적 있거나 직접 잠근 복사본. 최신화·내리기·삭제 안 함.", ["잠김", "직접 잠금"]],
  ["판매 이력 확인", "보호·검수", "주문을 확인한 스토어만 최신화·내리기 허용.", ["판매 이력"]],
  ["검수", "보호·검수", "원본을 눈으로 확인했는지. 검수 완료여야 처음 올림.", ["검수 완료", "미검수"]],
  ["눈검수", "보호·검수", "썸네일을 모아 보고 이상한 상품을 골라 지우는 화면."],
  ["생활화학 보류", "보호·검수", "인증이 필요할 수 있는 화학제품. 사람이 정하기 전엔 안 올림.", ["생활화학"]],
  ["수집 상품 넣기", "넣기·스토어·기타", "셀업 등으로 수집한 남의 상품을 원본으로. 상품명은 타스토어 원본 상품명으로 둠."],
  ["이름 완성 상품 넣기", "넣기·스토어·기타", "이미 이름을 바꿔 둔(안 올린) 상품을 원본으로. 그 이름이 후보상품명①번."],
  ["판매 중 상품 연결", "넣기·스토어·기타", "이미 스토어에 올라간 상품을 원본 + 판매 중 복사본으로 연결.", ["연결함"]],
  ["상세 정리", "넣기·스토어·기타", "수집 상품을 원본으로 넣기 전에 가격·이미지·카테고리를 고치는 곳.", ["정리함"]],
  ["상세 정리로 보내기", "넣기·스토어·기타", "이미 들어온 원본의 상세를 상세 정리에서 고치려고 보내기(원본·복사본 화면에서 골라)."],
  ["원본에 반영", "넣기·스토어·기타", "상세 정리에서 고친 상세를 원본에 덮어쓰기 — 상세만, 상품명·가격·옵션은 그대로(되돌리기 가능)."],
  ["네이버 상세 바꾸기", "넣기·스토어·기타", "원본 상세를 고치면 판매 중 복사본의 네이버 상세(+브랜드·제조사·모델명)만 바꿈 — 지우지 않아 상품번호·리뷰 그대로.", ["상세 바꾸기"]],
  ["네이버 상품 정보 바꾸기", "넣기·스토어·기타", "고른 판매 중 복사본의 상세·브랜드·제조사·모델명을 지금 원본·설정 기준으로 네이버에서 바꿈 (지우지 않음).", ["상품 정보 바꾸기"]],
  ["브랜드·제조사·모델명", "넣기·스토어·기타", "설정(기본 켬)으로 엑셀 값과 상관없이 '상세페이지 참조'로 올림 — 끄면 원본 엑셀 값."],
  ["공통 이미지", "넣기·스토어·기타", "여러 상세에 똑같이 든 이미지(예전 상하단). 골라서 뺌.", ["상하단", "상단·하단"]],
  ["그림으로 비교", "넣기·스토어·기타", "이미지를 내려받아 그림 자체로 같은지 봄. 주소가 달라도 같은 배너를 한 묶음으로 잡음.", ["그림 비교"]],
  ["상하단 자리 모아 보기", "넣기·스토어·기타", "상품마다 맨 위 3장·맨 아래 3장을 모아 보고 눈으로 골라 지우는 화면."],
  ["기억한 배너", "넣기·스토어·기타", "'다음에도 빼기'로 기억한 이미지. 넣을 때·올릴 때 늘 자동으로 뺌(내 템플릿 이미지는 절대 안 뺌).", ["다음에도 빼기"]],
  ["출처 태그", "넣기·스토어·기타", "원본이 어디서·언제 왔는지 붙이는 표시."],
  ["이 프로그램에서만 빼기", "넣기·스토어·기타", "네이버 상품은 두고 업스타에서만 지움.", ["네이버 상품은 그대로"]],
  ["스토어 템플릿", "넣기·스토어·기타", "스토어마다 정하는 가격 차이 %·할인율·상하단·배송 정보.", ["템플릿"]],
  ["고구마", "넣기·스토어·기타", "네이버에서 전시중지된 상품. 한도는 차지함.", ["전시중지"]],
  ["휴지통", "넣기·스토어·기타", "지운 원본·복사본. 되살리거나 완전히 지움."],
  ["원본·복사본 모두 삭제", "넣기·스토어·기타", "원본과 모든 스토어 복사본을 지움(판매 중은 내린 뒤, 잠긴 것은 남김)."],
  ["2차 확인", "넣기·스토어·기타", "실행 전에 무엇이 바뀌는지 한 번 더 보여 주는 창."],
];

const TERM_MAP = (() => {
  const m = {};
  TERMS.forEach(([t, g, d, alias]) => { m[t] = { term: t, group: g, desc: d }; (alias || []).forEach((a) => { m[a] = { term: t, group: g, desc: d, alias: a }; }); });
  return m;
})();
const TERM_KEYS = Object.keys(TERM_MAP).sort((a, b) => b.length - a.length);

/* 화면 맨 위 한 줄 안내 */
const GUIDES = {
  home: "원본 넣기 → 스토어로 복사 → 후보상품명 붙이기 → [시작]으로 올리기.",
  clean: "수집 상품을 원본으로 넣기 전에 가격·공통 이미지·전화번호·카테고리를 고치는 곳.",
  inventory: "가지고 있는 원본 전체. 넣기 · 기준 가격 수정 · 검수 · 스토어로 복사를 여기서.",
  listings: "스토어별 복사본. 후보상품명 있음 + 검수 완료면 '올릴 준비' → [시작].",
  lexicon: "상품명에 쓰지 않을 단어(금지어)와 상표 확인. 바꾸면 앞으로 만드는 이름부터.",
  orders: "스토어 주문(판매 이력). 팔린 복사본은 자동으로 잠김.",
  stores: "스토어와 스토어 템플릿(가격 차이 %·할인율·상하단·배송) 관리.",
  mail: "연결한 메일함의 네이버 알림(경고·주문 등).",
  runs: "실행·설정 변경 기록.",
  trash: "지운 원본·복사본. 되살리거나 완전히 지움.",
  settings: "프로그램 전체 설정. 스토어마다 다른 값은 스토어 템플릿에서.",
  adopt: "이미 올라간 상품을 원본 + 판매 중 복사본으로 연결: 엑셀 올리기 → [맞춰 보기] → [이대로 가져오기].",
  eye: "썸네일을 보며 이상한 상품을 골라 지움. [완료]를 눌러야 지워짐.",
  help: "업스타에 나오는 말의 뜻. 화면의 ⓘ에 마우스를 올려도 보임.",
};

Object.assign(App, {
  /* 용어 옆 ⓘ (마우스를 올리면 설명, 누르면 설명 창) */
  ti(term) {
    const t = TERM_MAP[term];
    return t ? `<span class="ti" data-term="${esc(term)}" title="${esc(t.term + ": " + t.desc)}">ⓘ</span>` : "";
  },
  /* 글에 나오는 용어들 (긴 것부터, 같은 뜻은 한 번) */
  termsIn(text, limit = 5) {
    const out = [], seen = new Set(), BASIC = new Set(["원본", "복사본", "대기"]);
    let s = String(text || "");
    for (const k of TERM_KEYS) {
      if (out.length >= limit) break;
      if (!s.includes(k)) continue;
      const t = TERM_MAP[k];
      s = s.split(k).join(" ");
      if (seen.has(t.term)) continue;
      seen.add(t.term);
      out.push(t);
    }
    return out.sort((a, b) => BASIC.has(a.term) - BASIC.has(b.term)).slice(0, limit);
  },
  termPop(el) {
    const t = TERM_MAP[el.dataset.term];
    if (!t) return;
    $("#term-pop")?.remove();
    const d = document.createElement("div");
    d.id = "term-pop";
    d.className = "term-pop";
    d.innerHTML = `<b>${esc(t.term)}</b>${t.alias ? ` <span class="muted small">(${esc(t.alias)})</span>` : ""}<div>${esc(t.desc)}</div>
      <a href="#help?t=${encodeURIComponent(t.term)}" class="small">용어 설명 전체 보기 →</a>`;
    document.body.appendChild(d);
    const r = el.getBoundingClientRect();
    const w = Math.min(340, window.innerWidth - 24);
    d.style.width = w + "px";
    d.style.left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left - 20)) + "px";
    d.style.top = (r.bottom + 6 + d.offsetHeight > window.innerHeight ? Math.max(8, r.top - d.offsetHeight - 6) : r.bottom + 6) + "px";
    setTimeout(() => document.addEventListener("click", function off(e) { if (!d.contains(e.target)) { d.remove(); document.removeEventListener("click", off, true); } }, true), 0);
  },
  /* 화면에 그려진 제목·칸 이름 옆에 ⓘ를 붙임 (용어 설명에 있는 말만) */
  annotateTerms(root) {
    root.querySelectorAll(".t-label, th, h1, h2, h3, dt, .ad-tile > .small, .kv dt").forEach((el) => {
      if (el.dataset.ti || el.querySelector(".ti") || el.closest("#m-confirm, .term-pop, .help-page")) return;
      const text = (el.textContent || "").trim();
      if (!text || text.length > 40) return;
      const k = TERM_KEYS.find((x) => text.includes(x));
      el.dataset.ti = "1";
      if (!k) return;
      el.insertAdjacentHTML("beforeend", " " + this.ti(k));
    });
  },
  /* 화면 맨 위 한 줄 안내 */
  pageGuide(view, page) {
    const g = GUIDES[page];
    const head = view.querySelector(".page-head");
    if (!g || !head || view.querySelector(".page-guide")) return;
    head.insertAdjacentHTML("afterend", `<p class="page-guide">ⓘ ${esc(g)} <a href="#help" class="small">용어 설명</a></p>`);
  },
  initTerms() {
    let pending = false;
    const run = () => { pending = false; ["#view", "#drawer", "#m-body"].forEach((s) => { const r = $(s); if (r) this.annotateTerms(r); });
      const v = $("#view"); if (v && this._page) this.pageGuide(v, this._page); };
    const obs = new MutationObserver(() => { if (!pending) { pending = true; requestAnimationFrame(run); } });
    ["#view", "#drawer", "#m-body"].forEach((s) => { const r = $(s); if (r) obs.observe(r, { childList: true, subtree: true }); });
    document.addEventListener("click", (e) => {
      const t = e.target.closest?.(".ti");
      if (!t) return;
      e.preventDefault(); e.stopPropagation();
      this.termPop(t);
    }, true);
  },
});

App.page("help", {
  mount(el, params) {
    const groups = [...new Set(TERMS.map((t) => t[1]))];
    el.innerHTML = `<div class="page help-page">
      <header class="page-head"><h1>용어 설명</h1>
        <div class="head-actions"><input id="h-q" class="input" placeholder="찾을 말 (예: 기준 가격, 잠금)" style="min-width:240px"></div></header>
      <section class="card pad"><div id="h-list"></div></section></div>`;
    const draw = () => {
      const q = ($("#h-q").value || "").trim();
      $("#h-list").innerHTML = groups.map((g) => {
        const rows = TERMS.filter((t) => t[1] === g && (!q || t[0].includes(q) || t[2].includes(q) || (t[3] || []).some((a) => a.includes(q))));
        return rows.length ? `<h2 class="help-group">${esc(g)}</h2><dl class="help-dl">${rows.map(([t, , d, alias]) =>
          `<dt id="term-${esc(t)}">${esc(t)}${alias ? ` <span class="muted small">(${alias.map(esc).join(", ")})</span>` : ""}</dt><dd>${esc(d)}</dd>`).join("")}</dl>` : "";
      }).join("") || '<p class="muted">찾는 말이 없습니다.</p>';
    };
    $("#h-q").addEventListener("input", draw);
    draw();
    if (params.t) {
      const x = document.getElementById("term-" + params.t);
      if (x) { x.classList.add("hl"); x.scrollIntoView({ block: "center" }); }
    }
  },
});
