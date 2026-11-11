/* 용어 설명: 프로그램에 나오는 말과 기능을 한곳에 (화면 곳곳의 ⓘ, 2차 확인 화면의 '용어 설명'도 이 내용을 씀).
   화면마다 맨 위 한 줄 안내(GUIDES)도 여기. */
"use strict";

const TERMS = [
  // [용어, 묶음, 설명, 같은 말(화면에서 이 말에도 ⓘ)]
  ["원본", "상품", "원본 엑셀(셀업 양식)이나 기존 상품 가져오기로 들어온 상품. 복사본의 바탕이고, 원본 자체는 네이버에 올라가지 않습니다. 상품명이 완전히 같으면 같은 원본입니다."],
  ["복사본", "상품", "원본을 한 스토어에 올리려고 만든 것(스토어마다 하나). 새 상품명과 그 스토어 가격 차이 %로 정한 손님 가격으로 올라갑니다."],
  ["상품명 중복", "상품", "상품명이 띄어쓰기·순서까지 완전히 같은 것. 원본 엑셀에서는 넣지 않고(덮어쓰지 않음), 기존 상품 가져오기에서는 한 스토어에 하나만 연결합니다. 포함 관계·비슷한 이름은 중복이 아닙니다."],
  ["대표 이미지 겹침", "상품", "상품명은 다른데 대표 이미지 주소가 같은 줄. 원본 엑셀을 올릴 때 몇 개인지 보여 주고 포함할지 버릴지 고릅니다. 원본 구분 기준은 아닙니다.", ["이미지 겹침", "대표 이미지 주소 겹침"]],
  ["기준 가격", "가격", "원본에 저장된 손님 가격 — 모든 스토어 손님 가격의 출발점입니다(구매 원가가 아님). 처음 원본 파일의 판매가 − 할인가(기존 상품 가져오기로 새로 생긴 원본은 그 스토어 손님 가격)로 정해지고, 원본 엑셀을 다시 올려도 바뀌지 않습니다. 역마진 등일 때만 [기준 가격 수정]으로 바꿉니다. 스토어 가격 차이 %가 0이면 기준 가격 = 손님 가격."],
  ["손님 가격", "가격", "그 스토어에서 손님이 실제로 내는 금액 = 기준 가격 × (1 + 그 스토어 가격 차이 %), 100원 올림. 네이버 판매가·즉시할인이 어떻게 보이든 손님 가격은 1원도 바뀌지 않습니다."],
  ["스토어 가격 차이 %", "가격", "그 스토어만 기준 가격에서 더하거나 빼는 % (스토어 템플릿에서 정함, 기본 0). 마진이 아니라 스토어끼리 가격에 차이를 주는 값입니다(마진은 이미 손님 가격에 들어 있음). 손님 가격 = 기준 가격 × (1 + 스토어 가격 차이 %). 바꾸면 다음 등록·최신화 때 새 값으로 계산됩니다.", ["가격 차이"]],
  ["표시 할인율", "가격", "네이버에 보이는 할인 % (스토어 템플릿에서 정함). 네이버 판매가 = 손님 가격 ÷ (1 − 표시 할인율)을 100원 올림, 그 차이를 금액 즉시할인으로 겁니다. 손님 가격은 그대로입니다.", ["네이버 판매가", "즉시할인"]],
  ["가격 고정", "가격", "기존 상품 가져오기로 연결한 복사본은 최신화 때 네이버의 지금 손님 가격(옵션 가격 포함) 그대로 올립니다. 다른 스토어로 복사할 때는 기준 가격 × 받는 스토어 가격 차이 %."],
  ["역마진", "가격", "사들이는 값이 올라 지금 손님 가격으로는 손해인 경우. 이때는 [기준 가격 수정]으로 기준을 고치면, 판매 중 복사본은 지우지 않고 네이버 가격만 바로 바뀝니다."],
  ["판매자 관리코드", "등록", "프로그램이 스토어마다 붙이는 코드 '스토어코드-원본번호-회차'. 최신화하면 회차가 올라 바뀝니다.", ["판매자코드", "관리코드"]],
  ["상품번호", "등록", "네이버가 상품에 붙인 번호. 최신화·다시 올리기로 지우고 다시 올리면 바뀝니다."],
  ["회차", "등록", "같은 스토어에 같은 원본을 지우고 다시 올린 횟수(판매자 관리코드 끝 숫자). 회차 초기화를 하면 다음에 1회차로 올라갑니다."],
  ["최신화", "등록", "판매 중 상품을 네이버에서 지우고 새 상품명으로 다시 올리기. 상품번호·관리코드가 바뀌고 리뷰·판매 기록이 사라지므로, 판매 이력을 확인한 상품만 하고 잠긴 상품은 하지 않습니다."],
  ["다시 올리기", "등록", "판매 중 상품을 같은 이름으로 지우고 다시 올리기(상품번호가 바뀜). 최신화와 같은 보호(판매 이력·잠금)를 거칩니다."],
  ["내리기", "등록", "네이버에서 상품을 지우기. 복사본은 '내림'으로 남아 다시 올리거나 다른 스토어로 보낼 수 있습니다.", ["내림"]],
  ["원본으로 되돌리기", "등록", "아직 안 올린·내린 복사본을 없애 그 스토어 자리를 비우기(휴지통에 기록). 원본은 그대로입니다."],
  ["다른 스토어로 보내기", "등록", "아직 안 올린·내린 복사본을 다른 스토어의 새 등록 대기로 옮기기. 예전 스토어 기록은 휴지통에 남깁니다."],
  ["올릴 준비", "등록", "상품명을 바꿨고 + 원본이 검수 완료이고 + 아직 안 올린 등록 대기인 복사본. [시작]하면 올라갑니다."],
  ["이름 변경 필요", "등록", "아직 원본 상품명 그대로인 복사본. 원본 이름 그대로는 올리지 않으므로 상품명 바꾸기를 해야 올라갑니다.", ["상품명 변경 필요"]],
  ["대기", "등록", "처리할 일(새 등록·최신화·내리기)이 걸려 있고 [시작]을 기다리는 상태.", ["등록 대기"]],
  ["잠금", "보호", "팔린 적 있는(판매 이력) 복사본이나 직접 잠근 복사본. 최신화·내리기·삭제를 하지 않습니다 — 리뷰·판매 기록을 지키기 위해.", ["잠김", "직접 잠금"]],
  ["판매 이력 확인", "보호", "판매 중 상품(가져온 것 포함)은 올라간 날부터 주문을 알고 있어야 최신화·내리기를 합니다. 주문 파일을 넣거나 팔린 것을 잠근 뒤 [판매 이력 확인 완료]. 그 뒤로는 최신화 때마다 새 주문만 받아 잠급니다.", ["판매 이력"]],
  ["기존 상품 가져오기", "가져오기", "다른 방법으로 이미 스토어에 올린 상품을 업로드했던 엑셀 + 네이버 상품 목록(판매자코드로 1대1)으로 맞춰 원본 + 판매 중 복사본으로 넣기. 원본 기준은 원본 엑셀과 같은 상품명입니다.", ["가져옴"]],
  ["원본 이름 없음", "가져오기", "기존 상품 가져오기로 들어와 올라가 있던 이름이 원본 이름 자리에 있는 원본."],
  ["이 프로그램에서만 빼기", "가져오기", "네이버 상품은 그대로 두고 이 프로그램에서만 휴지통으로 옮기기(내리지 않음). 다시 가져오면 직접 잠금·예전 판매자코드를 되살립니다.", ["네이버 상품은 그대로"]],
  ["검수", "검수", "원본을 눈으로 확인했는지. 검수 완료된 원본만 새로 올립니다(이미 올린 적 있는 것의 최신화·다시 올리기는 그대로).", ["검수 완료", "미검수"]],
  ["눈검수", "검수", "썸네일을 한 화면에 모아 보고 이상한 상품을 골라 지우는 검수 화면."],
  ["생활화학 보류", "검수", "생활화학·살생물제 인증 대상 카테고리에서 화학제품이거나 애매한 상품. 사람이 '물건으로' 바꾸거나 카테고리를 바꾸기 전에는 올리지 않습니다.", ["생활화학"]],
  ["상품명 바꾸기", "상품명", "복사본에 새 이름 붙이기: AI 키워드(원본마다 AI가 준 키워드로 조합), 셔플(단어 순서 섞기), 직접 고치기. 모든 스토어 통틀어 같은 이름은 다시 쓰지 않습니다."],
  ["AI 키워드", "상품명", "원본 상품명을 보고 AI가 고른 핵심·맥락 키워드. 이걸로 스토어마다 다른 상품명(A·B)을 만듭니다(비용이 듭니다)."],
  ["셔플", "상품명", "원본 상품명의 단어 순서를 섞어 새 이름을 만들기(AI 비용 없음)."],
  ["금지어", "상품명", "상품명에 넣지 않을 단어(상표·위험 단어 등). 이 단어가 들어간 이름은 쓰지 않습니다."],
  ["상세 정리", "원본 넣기", "셀업 엑셀을 원본으로 넣기 전에 정리함에서 가격 칸·공통 이미지·전화번호·카테고리 등을 고치는 곳.", ["정리함"]],
  ["공통 이미지", "원본 넣기", "여러 상품 상세에 똑같이 들어 있는 이미지(예: 예전 스토어 상단·하단 배너). 골라서 빼면 원본 상세에서 지워집니다.", ["상하단", "상단·하단"]],
  ["출처 태그", "원본 넣기", "원본이 어디서·언제 왔는지 붙이는 표시(스토어 이름, 날짜, 직접 적은 말). 원본 화면에서 이 태그로 거를 수 있습니다."],
  ["고구마", "스토어", "네이버에서 전시중지된 상품(손님에게 안 보임). 스토어 상품 한도는 차지합니다. 스토어 카드에 수가 보이고, 연결 확인 때 자동으로 셉니다.", ["전시중지"]],
  ["스토어 템플릿", "스토어", "스토어마다 정하는 스토어 가격 차이 %·표시 할인율·상단/하단 이미지·워터마크·배송 정보 등. 그 스토어에 올리는 모든 복사본에 적용됩니다.", ["템플릿"]],
  ["휴지통", "기타", "지운 원본·복사본이 남는 곳. 되살리면 원래 자리로 돌아가고(상품명이 같은 원본이 그새 들어왔으면 건너뜀), 완전히 지우면 없어집니다."],
  ["원본·복사본 모두 삭제", "기타", "원본과 모든 스토어 복사본을 지우기. 판매 중인 것은 네이버에서 내린 뒤 지우고, 잠긴 복사본과 그 원본은 남깁니다."],
  ["2차 확인", "기타", "확인·저장·실행 버튼을 누르면 무엇이 어떻게 되는지 한 번 더 보여 주고 [확인 — 실행]을 눌러야 실행합니다."],
];

const TERM_MAP = (() => {
  const m = {};
  TERMS.forEach(([t, g, d, alias]) => { m[t] = { term: t, group: g, desc: d }; (alias || []).forEach((a) => { m[a] = { term: t, group: g, desc: d, alias: a }; }); });
  return m;
})();
const TERM_KEYS = Object.keys(TERM_MAP).sort((a, b) => b.length - a.length);

/* 화면 맨 위 한 줄 안내 */
const GUIDES = {
  home: "전체 현황입니다. 원본을 넣고(원본 상품) → 스토어에 복사하고 상품명을 바꾼 뒤(복사본) → [시작]으로 올립니다.",
  clean: "셀업 엑셀을 원본으로 넣기 전에 고치는 곳입니다. 엑셀 올리기 → 가격·공통 이미지·전화번호·카테고리 정리 → [원본 상품으로 넣기]. 상품명이 완전히 같은 원본이 있으면 넣지 않습니다.",
  inventory: "가지고 있는 원본 전체입니다. 원본 엑셀 불러오기(상품명 중복은 넣지 않음) · 기준 가격 수정 · 검수 · 스토어로 복사를 여기서 합니다.",
  listings: "스토어에 올릴(올린) 복사본입니다. 상품명 바꾸기 → 검수 완료면 '올릴 준비' → [시작]. 판매 중 상품의 최신화·내리기는 판매 이력 확인 뒤에만 합니다.",
  lexicon: "상품명에 쓰지 않을 단어(금지어)와 단어 사전을 관리합니다. 바꾸면 앞으로 만드는 이름부터 적용됩니다.",
  orders: "스토어 주문(판매 이력)입니다. 팔린 복사본은 자동으로 잠겨 최신화·내리기·삭제를 하지 않습니다.",
  stores: "스토어와 스토어 템플릿(스토어 가격 차이 %·표시 할인율·상단/하단·배송)을 관리합니다. 손님 가격 = 기준 가격 × (1 + 스토어 가격 차이 %).",
  mail: "연결한 메일함의 네이버 알림(경고·주문 등)을 모아 봅니다.",
  runs: "실행·설정 변경 기록입니다. 무엇을 언제 했는지와 결과가 남습니다.",
  trash: "지운 원본·복사본입니다. 되살리면 원래 자리로(상품명이 같은 원본이 그새 들어왔으면 건너뜀), 완전히 지우면 없어집니다.",
  settings: "프로그램 전체 설정입니다. 스토어마다 다른 값(스토어 가격 차이 % 등)은 스토어 템플릿에서 정합니다.",
  adopt: "이미 스토어에 올려 둔 상품을 가져옵니다: 업로드했던 엑셀 올리기 → [맞춰 보기](아무것도 안 바뀜) → [이대로 가져오기]. 원본 기준은 상품명(완전히 같음)입니다.",
  eye: "썸네일을 보며 이상한 상품을 골라 지웁니다. [완료]를 눌러야 고른 것이 지워집니다.",
  help: "프로그램에 나오는 말과 기능의 뜻입니다. 화면의 ⓘ를 누르거나 마우스를 올려도 볼 수 있습니다.",
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
