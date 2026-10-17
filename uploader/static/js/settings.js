/* 설정: 모든 스토어에 공통인 값. 항목은 아래 SECTIONS 표 하나로 정한다. */
"use strict";

const SETTING_SECTIONS = [
  { title: "상품 기본값", note: "스토어에 A/S 전화번호가 없으면 여기 값을 씁니다.", fields: [
    ["as_phone", "A/S 전화번호", "text", { req: true }],
    ["as_guide", "A/S 안내"], ["importer", "수입자", "text", { hint: "원산지가 해외일 때" }],
    ["origin_default", "원산지 기본값"],
    ["origin_codes", "원산지 코드", "json", { hint: "나라 이름: 네이버 원산지 코드" }],
  ] },
  { title: "배송", fields: [
    ["delivery_company", "택배사", "select", { options: [["CJGLS", "CJ대한통운"], ["HANJIN", "한진택배"], ["LOTTE", "롯데택배"],
      ["EPOST", "우체국택배"], ["LOGEN", "로젠택배"], ["KDEXP", "경동택배"]] }],
    ["return_fee", "반품 배송비", "number"], ["exchange_fee", "교환 배송비", "number"],
  ] },
  { title: "복사·구분", note: "같은 원본이 여러 스토어에 있을 때 구분하는 방법입니다. 판매자 관리코드는 스마트스토어센터에서 검색할 수 있어 어느 원본의 몇 번째 등록인지 바로 알 수 있습니다.", fields: [
    ["max_copies", "원본 하나를 올릴 수 있는 최대 스토어 수 (내린 것은 세지 않음)", "number"],
    ["seller_code_format", "판매자 관리코드 형식", "text", { hint: "{store}=스토어 코드, {source:07d}=원본 번호, {round}=회차" }],
    ["refresh_new_name", "최신화·다시 올리기 때 상품명을 새 후보로 바꿈 (끄면 같은 이름 그대로)", "check"],
  ] },
  { title: "주문 (판매 이력)", note: "판매자센터의 주문을 커머스API로 가져옵니다. 판매 이력이 있는 복사본은 최신화·내리기에서 빠집니다.", fields: [
    ["orders_auto_sync_minutes", "자동 가져오기 간격 (분, 0이면 끔 · 프로그램이 켜져 있을 때만)", "number"],
    ["orders_initial_days", "처음 가져올 때 며칠 전부터", "number"],
    ["lock_sold", "판매 이력이 있는 복사본은 자동으로 잠금 (최신화·내리기로 지우지 않음)", "check"],
    ["lock_canceled_too", "취소·반품만 있는 복사본도 잠금 (끄면 실제 판매가 1건이라도 있어야 잠금)", "check"],
  ] },
  { title: "스토어별 가격", note: "같은 상품도 스토어마다 원본가에서 조금씩 다르게 정합니다. 같은 상품·같은 스토어는 언제 계획해도 같은 가격입니다.", fields: [
    ["price_jitter_pct", "조정 범위 (± %)", "number", { step: 0.5 }],
    ["price_round", "단위 (원)", "number", { step: 10 }],
  ] },
  { title: "상품명", note: "모든 상품명은 모든 스토어를 통틀어 겹치지 않습니다 (띄어쓰기·기호·대소문자 무시).", fields: [
    ["use_original_name", "원본 상품명도 한 스토어에 쓸 수 있음 (원본 스토어와 이름이 같아짐)", "check"],
    ["auto_recombine", "계획 만들 때 이름 후보가 모자라면 재조합으로 자동으로 채움", "check"],
    ["name_max_len", "상품명 최대 글자 수", "number"],
    ["recombine_fixed_prefix", "재조합: 원본의 앞 몇 단어를 그대로 맨 앞에 고정할지", "number"],
    ["recombine_replace_ratio", "재조합: 유의어를 덧붙이지 않고 원래 단어 자리에 바꿔 넣는 비율 (0~1)", "number", { step: 0.1 }],
    ["recombine_new_min", "재조합: 새로 넣을 단어 최소 개수 (단어 사전의 유의어·카테고리 단어)", "number"],
    ["recombine_new_max", "재조합: 새로 넣을 단어 최대 개수", "number"],
    ["recombine_fill", "재조합: 남는 칸을 최대 글자 수까지 채움 (노출에 유리)", "check"],
    ["use_category_words", "재조합: 카테고리 이름의 단어를 새 단어로 씀 (카테고리를 따로 정할 거면 끄세요)", "check"],
    ["max_word_repeat", "한 상품명 안에서 같은 단어 허용 횟수 (다른 단어 안에 든 것도 셈, 넘으면 버림)", "number"],
    ["recombine_use_tags", "재조합에 엑셀 상품태그 단어도 섞기 (태그가 상품과 맞을 때만 켜세요)", "check"],
    ["recombine_max_overlap", "재조합: 같은 원본의 다른 이름과 단어가 이 비율 이상 겹치면 버림 (0~1)", "number", { step: 0.05 }],
  ] },
  { title: "우리말샘 (단어 사전 유의어)", note: "국립국어원 우리말샘 오픈 API 키(무료, opendict.korean.go.kr 에서 신청)를 넣으면 단어 사전에서 유의어를 받을 수 있습니다. 한 번 찾아본 단어는 다시 묻지 않습니다.", fields: [
    ["opendict_key", "우리말샘 오픈 API 키", "secret"],
    ["opendict_daily_limit", "한 번에 찾아볼 단어 수", "number"],
  ] },
  { title: "네이버 키워드", note: "developers.naver.com → Application → 애플리케이션 등록 → 사용 API '검색' → Client ID·Secret을 넣습니다(무료, 하루 25,000회). 검색량은 선택: searchad.naver.com → 도구 → API 사용 관리에서 받은 고객 ID·액세스 라이선스·비밀키.", fields: [
    ["use_naver_keywords", "재조합에 네이버에서 모은 단어 쓰기", "check"],
    ["naver_client_id", "검색 API Client ID", "text"],
    ["naver_client_secret", "검색 API Client Secret", "secret"],
    ["core_scan_words", "핵심 키워드를 찾을 앞 단어 수", "number"],
    ["kw_min_malls", "판매자 몇 곳 이상이 쓴 단어만", "number"],
    ["kw_min_share", "검색 결과 중 이 비율 이상에 나온 단어만 (0~1)", "number", { step: 0.01 }],
    ["kw_max_words", "원본 하나에 쓸 단어 수 (많이 쓴 순)", "number"],
    ["kw_daily_limit", "한 번에 검색할 횟수 (같은 검색어는 저장한 결과 재사용)", "number"],
    ["kw_refresh_days", "이 일수가 지나면 다시 모음", "number"],
    ["searchad_customer_id", "검색광고 고객 ID (선택)", "text"],
    ["searchad_api_key", "검색광고 액세스 라이선스 (선택)", "text"],
    ["searchad_secret", "검색광고 비밀키 (선택)", "secret"],
  ] },
  { title: "상표 확인 (키프리스)", note: "KIPRIS Plus(plus.kipris.or.kr) 회원가입 → 상표 정보 검색 API 활용 신청 → 받은 키를 넣습니다. 사전에 있는 일반명사는 확인하지 않고, '효도의자'처럼 붙여 만든 조어만 확인합니다(우리말샘 키가 있으면 사전 단어인지 먼저 확인).", fields: [
    ["kipris_key", "키프리스 API 키 (ServiceKey)", "secret"],
    ["kipris_block_pending", "출원·공고 중(등록 전) 상표 단어도 쓰지 않음", "check"],
    ["kipris_limit", "한 번에 확인할 단어 수", "number"],
  ] },
  { title: "AI 상품명 (Claude API)", note: "console.anthropic.com에서 API 키를 만들어 넣습니다. 사용한 만큼 요금이 나옵니다.", fields: [
    ["anthropic_api_key", "Anthropic API 키", "secret"],
    ["ai_model", "모델", "select", { options: [["claude-opus-5-5", "Claude Opus 5.5 (기본, 가장 정확)"],
      ["claude-sonnet-5-5", "Claude Sonnet 5.5 (절반 가격)"], ["claude-haiku-5-5", "Claude Haiku 5.5 (가장 저렴·빠름)"]] }],
    ["ai_effort", "생각하는 정도", "select", { options: [["low", "낮음 (기본, 빠르고 저렴)"], ["medium", "보통"], ["high", "높음"]] }],
    ["ai_products_per_call", "한 번에 보낼 상품 수", "number"],
    ["ai_workers", "동시에 보낼 요청 수", "number"],
    ["ai_guide", "추가 지침 (예: 브랜드명은 넣지 말 것, 용도 단어를 앞에)", "textarea"],
  ] },
  { title: "이미지", note: "대표·추가 이미지는 API 규칙상 스토어마다 네이버 서버에 올립니다. 한 번 내려받은 이미지는 디스크에 보관해 다시 받지 않습니다.", fields: [
    ["reupload_detail_images", "상세페이지 이미지도 네이버 서버에 올림", "check"],
    ["keep_pstatic_detail_images", "상세 이미지가 이미 네이버 이미지 서버(pstatic.net) 주소면 그대로 둠 (시간 크게 절약)", "check"],
    ["detail_video", "상세페이지 동영상", "select", { options: [["keep", "원래 주소 그대로 둠"], ["remove", "지우고 등록"]] }],
    ["image_cache_gb", "이미지 보관 용량 (GB, 0이면 보관 안 함)", "number", { step: 1 }],
  ] },
  { title: "속도", note: "네이버 호출 한도는 스토어마다 따로라서, 스토어를 나란히 돌리면 그만큼 빨라집니다. 429(호출 초과)가 잦으면 스토어당 동시 등록 수를 줄이세요.", fields: [
    ["max_parallel_stores", "동시에 돌릴 스토어 수", "number"],
    ["workers_per_store", "스토어당 동시 등록 수 (1~8)", "number"],
    ["delay_sec", "건마다 쉬는 시간 (초)", "number", { step: 0.1 }],
  ] },
  { title: "고급", fields: [["extra", "모든 상품에 덧붙일 API 필드 (JSON)", "json"]] },
];

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
      <form class="settings" id="set-form" autocomplete="off">${SETTING_SECTIONS.map((sec) => `<div class="card set">
        <h2>${esc(sec.title)}</h2>${sec.note ? `<p class="muted">${esc(sec.note)}</p>` : ""}${sec.fields.map(field).join("")}</div>`).join("")}
      </form></div>`;
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
      await App.refreshState();
    } catch (e) { App.toast(e.message, true); }
  },
});
