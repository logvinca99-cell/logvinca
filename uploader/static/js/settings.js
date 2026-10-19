/* 설정: 모든 스토어에 공통인 값. 항목은 아래 SECTIONS 표 하나로 정한다. */
"use strict";

const SETTING_SECTIONS = [
  { title: "상품 기본값", note: "스토어에 A/S 전화번호가 없으면 여기 값을 씁니다.", fields: [
    ["as_phone", "A/S 전화번호", "text", { req: true }],
    ["as_guide", "A/S 안내"],
    ["origin_force", "원산지를 엑셀과 상관없이 일괄 지정 (아래 나라로)", "check"],
    ["origin_country", "일괄 원산지", "text", { hint: "아래 원산지 코드에 있는 이름 (기본 중국 = 수입산 > 아시아 > 중국)" }],
    ["importer_template", "수입사 (스토어별)", "text", { hint: "{store} 자리에 스토어 이름이 들어감. 예: {store}협력사 → 가나스토어협력사. 스토어 화면에서 따로 정할 수도 있음" }],
    ["origin_codes", "원산지 코드", "json", { hint: "이름: 네이버 원산지 코드" }],
    ["origin_default", "엑셀 원산지가 비었을 때 (일괄 지정을 끈 경우)"],
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
  { title: "우리말샘 API", note: "국립국어원 우리말샘 오픈 API 키(opendict.korean.go.kr). 단어 사전 화면의 '우리말샘 API로 유의어 받기'와, 상표 확인 때 사전 단어인지 확인하는 데 씁니다(하루 50,000건). 한 번 찾아본 단어는 저장해 다시 묻지 않습니다. 사전 내려받기 파일도 함께 넣을 수 있습니다(선택).", fields: [
    ["opendict_key", "우리말샘 오픈 API 키", "secret"],
    ["opendict_daily_limit", "한 번에 찾아볼 단어 수", "number"],
  ] },
  { title: "네이버 키워드 (검색광고 API)", note: "searchad.naver.com 가입(광고비 없이 가능) → 도구 → API 사용 관리 → 고객 ID·액세스 라이선스·비밀키. 무료. (네이버 쇼핑 검색 API는 2026년 7월 종료돼 쓰지 않습니다.) 적용: 키워드를 모을 때, 그 뒤 새로 만드는 이름부터.", fields: [
    ["use_naver_keywords", "재조합에 네이버에서 모은 단어 쓰기", "check"],
    ["searchad_customer_id", "고객 ID (CUSTOMER_ID)", "text"],
    ["searchad_api_key", "액세스 라이선스 (API_KEY)", "text"],
    ["searchad_secret", "비밀키 (SECRET_KEY)", "secret"],
    ["core_scan_words", "핵심 키워드를 찾을 앞 단어 수 (검색량이 가장 큰 단어)", "number"],
    ["kw_min_volume", "연관 키워드 월간 검색량이 이만큼 이상인 것만", "number"],
    ["kw_dict_only", "국어사전에 있는 말만 쓰기 (브랜드·고유명사 거르기 · 우리말샘 API 키나 사전 파일 필요)", "check"],
    ["kw_max_words", "원본 하나에 쓸 단어 수 (검색량 순)", "number"],
    ["kw_related_max", "핵심 키워드마다 볼 연관 키워드 수", "number"],
    ["kw_daily_limit", "한 번에 부를 API 횟수 (같은 핵심 키워드는 저장한 결과 재사용)", "number"],
    ["kw_refresh_days", "이 일수가 지나면 다시 모음", "number"],
  ] },
  { title: "상표 확인 (키프리스)", note: "KIPRIS Plus(plus.kipris.or.kr) 회원가입 → 상표 정보 검색 API 활용 신청 → 받은 키를 넣습니다. 사전에 있는 일반명사는 확인하지 않고, '효도의자'처럼 붙여 만든 조어만 확인합니다(우리말샘 키가 있으면 사전 단어인지 먼저 확인).", fields: [
    ["kipris_key", "키프리스 API 키 (ServiceKey)", "secret"],
    ["kipris_block_pending", "출원·공고 중(등록 전) 상표 단어도 쓰지 않음", "check"],
    ["kipris_limit", "한 번에 확인할 단어 수", "number"],
  ] },
  { title: "도둑방지", note: "처음 올릴 때 판매가에 금액을 더해 올리고, 원래 가격으로는 도둑방지·복사본 화면에서 직접 되돌립니다. 할인 금액은 도둑방지 전 가격 기준이라 되돌리면 할인·마진이 처음 그대로입니다. 가격은 항상 100원 단위 올림.", fields: [
    ["bait_default", "등록 계획 때 '도둑방지로 올리기'를 기본으로 켬 (계획 창에서 끌 수 있음)", "check"],
    ["bait_amount", "더할 금액 (원)", "number"],
    ["bait_on_refresh", "최신화(다시 등록) 때도 높여서 올림", "check"],
  ] },
  { title: "워터마크 (대표 이미지)", note: "스토어마다 로고 PNG(투명 배경 권장)나 글자를 스토어 화면에서 정합니다. 직사각형 이미지는 네이버 목록에서 가운데 정사각형으로 잘려 보이므로 그 안쪽에 넣습니다. 미리보기는 도둑방지 화면에 있습니다.", fields: [
    ["wm_enabled", "워터마크 넣기 (이후 올리는 상품부터)", "check"],
    ["wm_scope", "넣을 이미지", "select", { options: [["main", "대표 이미지만"], ["all", "대표 + 추가 이미지"]] }],
    ["wm_position", "위치", "select", { options: [["bottom-right", "아래 오른쪽"], ["bottom-left", "아래 왼쪽"], ["top-right", "위 오른쪽"], ["top-left", "위 왼쪽"], ["bottom-center", "아래 가운데"], ["top-center", "위 가운데"]] }],
    ["wm_square", "직사각형 이미지", "select", { options: [["safe", "가운데 정사각형 안쪽에 넣기 (잘려도 보임)"], ["pad", "흰 여백을 붙여 정사각형으로 만든 뒤 넣기"], ["full", "이미지 전체 기준 (잘리면 안 보일 수 있음)"]] }],
    ["wm_size_pct", "크기 (정사각형 한 변의 %)", "number", { step: 1 }],
    ["wm_opacity", "불투명도 (0~1)", "number", { step: 0.05 }],
    ["wm_margin_pct", "가장자리 여백 (%)", "number", { step: 1 }],
    ["wm_font", "글자 워터마크 글꼴 파일 (비우면 맑은 고딕)", "text"],
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

/* 설정이 언제부터 적용되는지 (이미 만든 것에는 적용되지 않음) */
const APPLY_WHEN = {
  "상품 기본값": "다음 등록부터 · 원산지를 바꾸면 저장할 때 전체 원본을 다시 검사",
  "배송": "다음 등록부터",
  "복사·구분": "다음 복사·등록부터",
  "주문 (판매 이력)": "다음 주문 가져오기부터 (잠금 기준은 저장 즉시 다시 계산)",
  "스토어별 가격": "새로 만드는 복사본부터 · 이미 만든 복사본은 위 '대기 중인 복사본 가격 다시 계산'",
  "상품명": "새로 만드는 이름부터 · 이미 만든 후보는 위 '안 쓴 이름 후보 지우기' 뒤 다시 만들기",
  "우리말샘 API": "단어 사전에서 받을 때, 상표 확인 때",
  "네이버 키워드 (검색광고 API)": "키워드를 모을 때, 그 뒤 새로 만드는 이름부터",
  "상표 확인 (키프리스)": "확인할 때 · 출원 중 막기는 저장 즉시",
  "도둑방지": "다음 복사 창·다음 등록부터 (이미 올라간 상품은 그대로)",
  "워터마크 (대표 이미지)": "다음 등록부터 (이미 올라간 상품은 그대로)",
  "AI 상품명 (Claude API)": "다음 AI 이름 만들기부터",
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
      <form class="settings" id="set-form" autocomplete="off">${SETTING_SECTIONS.map((sec) => `<div class="card set">
        <h2>${esc(sec.title)}</h2>${sec.note ? `<p class="muted">${esc(sec.note)}</p>` : ""}
        ${APPLY_WHEN[sec.title] ? `<p class="apply-when">적용: ${esc(APPLY_WHEN[sec.title])}</p>` : ""}${sec.fields.map(field).join("")}</div>`).join("")}
      </form></div>`;
    $(".settings", el).insertAdjacentHTML("beforebegin", `<div class="card pad reapply">
      <div class="muted small" style="width:100%">기록·설정 폴더: <code>${esc(st.data_dir)}</code> — 프로그램 폴더와 따로 있어 새 버전을 받아도 그대로 이어집니다. 백업은 이 폴더를 복사하세요.</div>
      <div><b>설정은 저장한 뒤 새로 만드는 것부터 적용됩니다.</b> <span class="muted small">이미 만든 복사본 가격·이름 후보에 다시 적용하려면:</span></div>
      <div class="reapply-btns"><button class="btn" data-reapply="prices" title="아직 안 올린(대기·실패) 복사본의 가격을 지금 설정(±%, 100원 올림)으로 다시 계산">대기 중인 복사본 가격 다시 계산</button>
        <button class="btn" data-reapply="names" title="아직 아무 복사본에도 안 쓴 재조합·AI 이름 후보를 지움 → 새 설정으로 다시 만들 수 있음">안 쓴 이름 후보 지우기</button>
        <a class="btn ghost" href="#listings?status=noname">이름 변경 필요 복사본 보기</a></div></div>`);
    $$("[data-reapply]", el).forEach((b) => b.addEventListener("click", async () => {
      const what = b.dataset.reapply;
      if (what === "names" && !confirm("아직 안 쓴 재조합·AI 이름 후보를 모두 지울까요? (복사본에 쓴 이름·가져온 이름·직접 넣은 이름은 그대로)")) return;
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
