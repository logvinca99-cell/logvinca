/* 설정: 모든 스토어에 공통인 값. 탭(SETTING_TABS)으로 나누고 항목은 SECTIONS 표 하나로 정한다. */
"use strict";

const SETTING_TABS = [
  ["product", "상품 등록 기본값"], ["price", "가격·할인"], ["name", "상품명 (AI)"], ["keys", "API 키"],
  ["image", "이미지·워터마크"], ["orders", "주문·잠금"], ["speed", "속도·고급"],
];

const SETTING_SECTIONS = [
  { tab: "product", title: "상품 기본값", note: "모든 스토어에 공통입니다. 스토어마다 다르게 할 것(상세 상단·하단, 관부가세, 가격 조정, 표시 할인율, 수입사)은 스토어 → 템플릿에서 정합니다.", fields: [
    ["as_phone", "A/S 전화번호", "text", { req: true, hint: "스토어에 A/S 전화가 없으면 이 값" }],
    ["as_guide", "A/S 안내"],
    ["origin_force", "원산지를 엑셀과 상관없이 일괄 지정 (아래 나라로)", "check"],
    ["origin_country", "일괄 원산지", "text", { hint: "아래 원산지 코드에 있는 이름 (기본 중국 = 수입산 > 아시아 > 중국)" }],
    ["importer_template", "수입사 (스토어별)", "text", { hint: "{store} 자리에 스토어 이름이 들어감. 예: {store}협력사 → 가나스토어협력사" }],
    ["origin_codes", "원산지 코드", "json", { hint: "이름: 네이버 원산지 코드" }],
    ["origin_default", "엑셀 원산지가 비었을 때 (일괄 지정을 끈 경우)"],
    ["customs_tax_type", "관부가세 (공통)", "select", { options: CUSTOMS_OPTS, hint: "출고지가 해외 주소면 필수. 스토어 템플릿에서 스토어마다 따로 정할 수 있음" }],
  ] },
  { tab: "product", title: "배송", fields: [
    ["delivery_company", "택배사", "select", { options: [["CJGLS", "CJ대한통운"], ["HANJIN", "한진택배"], ["LOTTE", "롯데택배"],
      ["EPOST", "우체국택배"], ["LOGEN", "로젠택배"], ["KDEXP", "경동택배"]] }],
    ["return_fee", "반품 배송비", "number"], ["exchange_fee", "교환 배송비", "number"],
  ] },
  { tab: "product", title: "복사·구분", note: "판매자 관리코드로 어느 원본의 몇 번째 등록인지 스마트스토어센터에서 바로 찾을 수 있습니다.", fields: [
    ["max_copies", "원본 하나를 올릴 수 있는 최대 스토어 수 (내린 것은 세지 않음)", "number"],
    ["seller_code_format", "판매자 관리코드 형식", "text", { hint: "{store}=스토어 코드, {source:07d}=원본 번호, {round}=회차" }],
    ["refresh_new_name", "최신화 때 상품명을 새로 (안 쓴 AI 키워드 후보 → 없으면 셔플)", "check"],
  ] },
  { tab: "price", title: "가격 (기본값)", note: "스토어 가격 = (판매가 - 할인가) × (1 + 스토어 가격 조정 %) × 흔들기(범위 안에서 상품마다 다르게), 100원 단위 올림. 흔들기를 쓰면 원본가와 똑같은 가격은 나오지 않습니다. 표시 할인율은 금액으로 걸어 정확히 그 %가 되게 판매가를 정합니다(그래서 손님 가격이 몇백 원 높아질 수 있음). 아래는 기본값이고, 스토어 → 템플릿에서 스토어마다 바꿉니다.", fields: [
    ["price_jitter_min", "흔들기 최소 %", "number", { step: 0.5 }],
    ["price_jitter_max", "흔들기 최대 %", "number", { step: 0.5 }],
    ["display_discount_pct", "표시 할인율 % (0이면 할인 없음)", "number", { step: 1 }],
    ["price_round", "단위 (원, 올림)", "number", { step: 10 }],
    ["stock_fixed", "등록 재고 (상품·옵션 모두 늘 이 수, 0이면 엑셀 재고수)", "number", { step: 100 }],
  ] },
  { tab: "price", title: "도둑방지", note: "처음 올릴 때 판매가에 금액을 더해 올리고, 원래 가격으로는 도둑방지·복사본 화면에서 직접 되돌립니다. 할인 금액은 도둑방지 전 가격 기준이라 되돌리면 표시 할인율·마진이 처음 그대로입니다.", fields: [
    ["bait_default", "도둑방지 사용 (처음 등록·최신화·다시 올리기 모두. 끄면 아직 안 올린 복사본도 원래 가격으로 올림)", "check"],
    ["bait_amount", "더할 금액 (원)", "number"],
  ] },
  { tab: "name", title: "상품명 공통", note: "모든 상품명은 모든 스토어를 통틀어 겹치지 않습니다 (띄어쓰기·기호·대소문자 무시). 금지어는 왼쪽 메뉴 '금지어'.", fields: [
    ["name_max_len", "상품명 최대 글자 수 (공백 포함)", "number"],
    ["use_original_name", "원본 상품명 그대로도 쓸 수 있음 (원본 스토어와 이름이 같아짐)", "check"],
  ] },
  { tab: "name", title: "AI 키워드 (기본 방식)", note: "AI는 원본마다 한 번 keep(지킬 원본 단어)·다른 이름(core)·맥락(ctx)만 줍니다. 이름 = [원본 앞 단어] + keep + 다른 이름 전부 + 맥락(남는 자리) + 남은 원본 단어 + 숫자·수량·연식(뒤로), 50자 안. 조립은 프로그램이 하고 원본마다 이름 A·B를 한 번에 만들어 1번째·2번째 복사본에 붙입니다. 틀린 다른 이름은 금지어 화면 → AI 다른 이름 확인에서 차단.", fields: [
    ["ctx_head_n", "앞 고정 단어 수 (숫자·수량·연식만 있는 단어는 세지 않고 뒤로)", "number"],
    ["ctx_names_per_source", "원본당 이름 수", "number"],
    ["ctx_per_request", "요청당 원본 수", "number"],
    ["ctx_structured", "구조화 출력으로 받기 (JSON이 깨지지 않게 · 실패 사유에 output_config 오류가 보이면 끄기)", "check"],
    ["ctx_model", "모델", "select", { options: [["claude-sonnet-5-5", "Claude Sonnet 5.5 (기본)"], ["claude-haiku-5-5", "Claude Haiku 5.5 (가장 저렴)"]] }],
    ["ctx_mode", "키워드 받기 기본 방식 (받기 창에서 처음 골라져 있는 것)", "select", { options: [["instant", "즉시 (1~2분, 요금 2배)"], ["batch", "일괄 (50% 할인, 몇 분~몇 시간)"]] }],
    ["krw_rate", "비용 안내 환율 (원/달러)", "number"],
  ] },
  { tab: "name", title: "AI로 짓기", note: "AI가 원본을 보고 이름 전체를 새로 짓습니다. 사용한 만큼 요금이 나옵니다.", fields: [
    ["ai_model", "모델", "select", { options: [["claude-opus-5-5", "Claude Opus 5.5 (가장 정확)"],
      ["claude-sonnet-5-5", "Claude Sonnet 5.5 (절반 가격)"], ["claude-haiku-5-5", "Claude Haiku 5.5 (가장 저렴·빠름)"]] }],
    ["ai_effort", "생각하는 정도", "select", { options: [["low", "낮음 (기본, 빠르고 저렴)"], ["medium", "보통"], ["high", "높음"]] }],
    ["ai_products_per_call", "한 번에 보낼 상품 수", "number"],
    ["ai_workers", "동시에 보낼 요청 수", "number"],
    ["ai_guide", "추가 지침 (예: 용도 단어를 앞에)", "textarea"],
  ] },
  { tab: "name", title: "셔플 (AI 안 씀)", note: "앞 단어를 고정하고 나머지 단어(+ 넣은 단어)의 순서를 섞습니다. 상품명 바꾸기 창에서 그때그때 바꿀 수 있습니다.", fields: [
    ["shuffle_fixed", "앞에서 고정할 단어 수 (기본값)", "number"],
  ] },
  { tab: "keys", title: "Anthropic (AI)", note: "console.anthropic.com에서 만든 API 키. AI 키워드와 AI로 짓기에 씁니다.", fields: [
    ["anthropic_api_key", "Anthropic API 키", "secret"],
  ] },
  { tab: "keys", title: "상표 확인 (키프리스)", note: "KIPRIS Plus(plus.kipris.or.kr) 회원가입 → 상표 정보 검색 API 활용 신청 → 받은 키. '효도의자'처럼 붙여 만든 말이 상표인지 확인합니다.", fields: [
    ["kipris_key", "키프리스 API 키 (ServiceKey)", "secret"],
    ["kipris_block_pending", "출원·공고 중(등록 전) 상표 단어도 쓰지 않음", "check"],
    ["kipris_limit", "한 번에 확인할 단어 수", "number"],
  ] },
  { tab: "keys", title: "네이버 커머스 API", note: "스토어마다 애플리케이션 ID·시크릿은 스토어 화면에서 넣습니다.", fields: [] },
  { tab: "image", title: "이미지", note: "대표·추가 이미지는 API 규칙상 스토어마다 네이버 서버에 올립니다. 한 번 내려받은 이미지는 디스크에 보관해 다시 받지 않습니다.", fields: [
    ["reupload_detail_images", "상세페이지 이미지도 네이버 서버에 올림", "check"],
    ["keep_pstatic_detail_images", "상세 이미지가 이미 네이버 이미지 서버(pstatic.net) 주소면 그대로 둠 (시간 크게 절약)", "check"],
    ["detail_video", "상세페이지 동영상", "select", { options: [["keep", "원래 주소 그대로 둠"], ["remove", "지우고 등록"]] }],
    ["image_cache_gb", "이미지 보관 용량 (GB, 0이면 보관 안 함)", "number", { step: 1 }],
  ] },
  { tab: "image", title: "워터마크 (대표 이미지)", note: "스토어마다 로고 PNG나 글자를 스토어 화면에서 정합니다. 미리보기는 도둑방지 화면에 있습니다.", fields: [
    ["wm_enabled", "워터마크 넣기 (이후 올리는 상품부터)", "check"],
    ["wm_scope", "넣을 이미지", "select", { options: [["main", "대표 이미지만"], ["all", "대표 + 추가 이미지"]] }],
    ["wm_position", "위치", "select", { options: [["bottom-right", "아래 오른쪽"], ["bottom-left", "아래 왼쪽"], ["top-right", "위 오른쪽"], ["top-left", "위 왼쪽"], ["bottom-center", "아래 가운데"], ["top-center", "위 가운데"]] }],
    ["wm_square", "직사각형 이미지", "select", { options: [["safe", "가운데 정사각형 안쪽에 넣기 (잘려도 보임)"], ["pad", "흰 여백을 붙여 정사각형으로 만든 뒤 넣기"], ["full", "이미지 전체 기준 (잘리면 안 보일 수 있음)"]] }],
    ["wm_size_pct", "크기 (정사각형 한 변의 %)", "number", { step: 1 }],
    ["wm_opacity", "불투명도 (0~1)", "number", { step: 0.05 }],
    ["wm_margin_pct", "가장자리 여백 (%)", "number", { step: 1 }],
    ["wm_font", "글자 워터마크 글꼴 파일 (비우면 맑은 고딕)", "text"],
  ] },
  { tab: "orders", title: "주문 (판매 이력)", note: "판매자센터의 주문을 커머스API로 가져옵니다. 판매 이력이 있는 복사본은 최신화·내리기에서 빠집니다.", fields: [
    ["orders_auto_sync_minutes", "자동 가져오기 간격 (분, 0이면 끔 · 프로그램이 켜져 있을 때만)", "number"],
    ["orders_initial_days", "처음 가져올 때 며칠 전부터", "number"],
    ["lock_sold", "판매 이력이 있는 복사본은 자동으로 잠금 (최신화·내리기로 지우지 않음)", "check"],
    ["lock_canceled_too", "취소·반품만 있는 복사본도 잠금", "check"],
  ] },
  { tab: "speed", title: "속도", note: "네이버 호출 한도는 스토어마다 따로라서, 스토어를 나란히 돌리면 그만큼 빨라집니다. 429(호출 초과)가 잦으면 스토어당 동시 등록 수를 줄이세요.", fields: [
    ["max_parallel_stores", "동시에 돌릴 스토어 수", "number"],
    ["workers_per_store", "스토어당 동시 등록 수 (1~8)", "number"],
    ["delay_sec", "건마다 쉬는 시간 (초)", "number", { step: 0.1 }],
  ] },
  { tab: "speed", title: "고급", fields: [["extra", "모든 상품에 덧붙일 API 필드 (JSON)", "json"]] },
];

/* 설정이 언제부터 적용되는지 (이미 만든 것에는 적용되지 않음) */
const APPLY_WHEN = {
  "상품 기본값": "다음 등록부터 · 원산지를 바꾸면 저장할 때 전체 원본을 다시 검사",
  "배송": "다음 등록부터",
  "복사·구분": "다음 복사·등록부터",
  "주문 (판매 이력)": "다음 주문 가져오기부터 (잠금 기준은 저장 즉시 다시 계산)",
  "가격": "새로 만드는 복사본부터 · 이미 만든 복사본은 위 '대기 중인 복사본 가격 다시 계산'",
  "도둑방지": "다음 복사·다음 등록부터 (이미 올라간 상품은 그대로)",
  "상품명 공통": "새로 만드는 이름부터",
  "AI 키워드 (기본 방식)": "다음 키워드 받기·이름 만들기부터 (이미 만든 후보는 그대로)",
  "AI로 짓기": "다음 AI 이름 짓기부터",
  "셔플 (AI 안 씀)": "다음 셔플부터",
  "상표 확인 (키프리스)": "확인할 때 · 출원 중 막기는 저장 즉시",
  "워터마크 (대표 이미지)": "다음 등록부터 (이미 올라간 상품은 그대로)",
  "이미지": "다음 등록부터",
  "속도": "다음 [시작]부터 (실행 중에는 그 실행에 적용 안 됨)",
  "고급": "다음 등록부터",
};

App.page("settings", {
  async mount(el) {
    const st = await App.refreshState();
    const s = st.settings;
    const field = ([key, label, type = "text", o = {}]) => {
      const v = s[key];
      if (type === "check") return `<label class="check"><input type="checkbox" name="${key}" ${v ? "checked" : ""}><span>${esc(label)}</span></label>`;
      const head = `${esc(label)}${o.req ? ' <span class="req">필수</span>' : ""}${o.hint ? ` <span class="muted">${esc(o.hint)}</span>` : ""}`;
      let input;
      if (type === "select") input = `<select name="${key}">${o.options.map(([val, l]) => `<option value="${val}" ${val === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
      else if (type === "json") input = `<textarea name="${key}" data-json rows="3" spellcheck="false">${esc(JSON.stringify(v, null, 1))}</textarea>`;
      else if (type === "textarea") input = `<textarea name="${key}" rows="3">${esc(v || "")}</textarea>`;
      else if (type === "secret") input = `<input name="${key}" type="password" placeholder="${s["has_" + key] ? "저장됨 · 바꿀 때만 입력" : ""}">`;
      else input = `<input name="${key}" type="${type}" ${o.step ? `step="${o.step}"` : ""} value="${esc(v ?? "")}">`;
      return `<label class="field">${head}${input}</label>`;
    };
    el.innerHTML = `<div class="page">
      <header class="page-head"><h1>설정</h1><div class="head-actions"><span class="muted" id="save-msg"></span>
        <button class="btn" id="cat-refresh">카테고리 새로 받기</button><button class="btn primary" id="save">저장</button></div></header>
      <div class="set-tabs" id="set-tabs">${SETTING_TABS.map(([k, l]) => `<button type="button" data-tab="${k}">${esc(l)}</button>`).join("")}</div>
      <form class="settings" id="set-form" autocomplete="off">${SETTING_SECTIONS.map((sec) => `<div class="card set" data-tab="${sec.tab}">
        <h2>${esc(sec.title)}</h2>${sec.note ? `<p class="muted">${esc(sec.note)}</p>` : ""}
        ${APPLY_WHEN[sec.title] ? `<p class="apply-when">적용: ${esc(APPLY_WHEN[sec.title])}</p>` : ""}${sec.fields.map(field).join("")}
        ${sec.title === "네이버 커머스 API" ? `<a class="btn" href="#stores">스토어 화면으로</a>` : ""}</div>`).join("")}
      </form></div>`;
    const show = (k) => {
      this.tab = k;
      try { localStorage.setItem("settings-tab", k); } catch (e) { /* 무시 */ }
      $$("#set-tabs button", el).forEach((b) => b.classList.toggle("on", b.dataset.tab === k));
      $$("#set-form [data-tab]", el).forEach((c) => { c.hidden = c.dataset.tab !== k; });
    };
    let first = "product";
    try { first = localStorage.getItem("settings-tab") || first; } catch (e) { /* 무시 */ }
    $("#set-tabs", el).addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) show(b.dataset.tab); });
    show(SETTING_TABS.some(([k]) => k === first) ? first : "product");
    $(".settings", el).insertAdjacentHTML("beforebegin", `<div class="card pad reapply">
      <div class="muted small" style="width:100%">기록·설정 폴더: <code>${esc(st.data_dir)}</code> — 프로그램 폴더와 따로 있어 새 버전을 받아도 그대로 이어집니다. 백업은 이 폴더를 복사하세요.</div>
      <div><b>설정은 저장한 뒤 새로 만드는 것부터 적용됩니다.</b> <span class="muted small">이미 만든 복사본 가격·이름 후보에 다시 적용하려면:</span></div>
      <div class="reapply-btns"><button class="btn" data-reapply="prices" title="아직 안 올린(대기·실패) 복사본의 가격을 지금 설정(±%, 100원 올림)으로 다시 계산">대기 중인 복사본 가격 다시 계산</button>
        <button class="btn" data-reapply="names" title="아직 아무 복사본에도 안 쓴 AI·셔플 이름 후보를 지움 → 새 설정으로 다시 만들 수 있음">안 쓴 이름 후보 지우기</button></div></div>`);
    $$("[data-reapply]", el).forEach((b) => b.addEventListener("click", async () => {
      const what = b.dataset.reapply;
      if (what === "names" && !confirm("아직 안 쓴 AI·셔플 이름 후보를 모두 지울까요? (복사본에 쓴 이름·직접 넣은 이름은 그대로)")) return;
      try {
        const r = await App.api("/api/settings/reapply", { json: { what } });
        App.toast(what === "prices" ? `복사본 ${num(r.count)}건의 가격을 다시 계산했습니다` : `이름 후보 ${num(r.count)}개를 지웠습니다. 원본 상품·복사본 화면에서 다시 만드세요`);
      } catch (e) { App.toast(e.message, true); }
    }));
    $("#save").addEventListener("click", () => this.save());
    $("#cat-refresh").addEventListener("click", async () => {
      try {
        const r = await App.startTask(App.api("/api/categories/refresh", { json: {} }));
        if (r) App.toast(`카테고리 ${num(r.categories)}개를 받았습니다. 전체 원본을 다시 검사합니다.`);
      } catch (e) { App.toast(e.message, true); }
    });
  },

  async save() {
    const out = {};
    for (const el of $("#set-form").elements) {
      if (!el.name) continue;
      if (el.type === "checkbox") out[el.name] = el.checked;
      else if (el.dataset.json !== undefined) {
        try { out[el.name] = el.value.trim() ? JSON.parse(el.value) : {}; }
        catch { App.toast(`'${el.closest("label").firstChild.textContent.trim()}'의 JSON 형식이 올바르지 않습니다.`, true); return; }
      } else out[el.name] = el.value.trim();
    }
    try {
      await App.api("/api/settings", { json: out });
      $("#save-msg").textContent = "저장했습니다 ✓";
      App.toast("저장했습니다. 새로 만드는 복사본·이름·다음 등록부터 적용됩니다 (각 칸의 '적용' 참고)");
      await App.refreshState();
    } catch (e) { App.toast(e.message, true); }
  },
});
