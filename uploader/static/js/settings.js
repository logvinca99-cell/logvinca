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
    ["refresh_new_name", "새로고침·다시 올리기 때 상품명을 새 후보로 바꿈 (끄면 같은 이름 그대로)", "check"],
  ] },
  { title: "주문 (판매 이력)", note: "판매자센터의 주문을 커머스API로 가져옵니다. 판매 이력이 있는 복사본은 새로고침·내리기에서 빠집니다.", fields: [
    ["orders_auto_sync_minutes", "자동 가져오기 간격 (분, 0이면 끔 · 프로그램이 켜져 있을 때만)", "number"],
    ["orders_initial_days", "처음 가져올 때 며칠 전부터", "number"],
  ] },
  { title: "스토어별 가격", note: "같은 상품도 스토어마다 원본가에서 조금씩 다르게 정합니다. 같은 상품·같은 스토어는 언제 계획해도 같은 가격입니다.", fields: [
    ["price_jitter_pct", "조정 범위 (± %)", "number", { step: 0.5 }],
    ["price_round", "단위 (원)", "number", { step: 10 }],
  ] },
  { title: "상품명", note: "모든 상품명은 모든 스토어를 통틀어 겹치지 않습니다 (띄어쓰기·기호·대소문자 무시).", fields: [
    ["use_original_name", "원본 상품명도 한 스토어에 쓸 수 있음 (원본 스토어와 이름이 같아짐)", "check"],
    ["auto_recombine", "계획 만들 때 이름 후보가 모자라면 재조합으로 자동으로 채움", "check"],
    ["name_max_len", "상품명 최대 글자 수", "number"],
    ["recombine_use_tags", "재조합에 엑셀 상품태그 단어도 섞기 (태그가 상품과 맞을 때만 켜세요)", "check"],
    ["recombine_max_overlap", "재조합: 같은 원본의 다른 이름과 단어가 이 비율 이상 겹치면 버림 (0~1)", "number", { step: 0.05 }],
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
