/* 고객 맞춤 상품: 고객 문의로 그 고객만을 위한 상품(대량 할인·다른 출고지·주문제작)을 따로 만들어 올리기.
   보통 복사본과 따로 — 원본당 복사 수·후보상품명 칸·일괄 작업에 안 들어가고, 자동으로 내리지 않는다.
   모든 값은 직접 입력 (상품명에 무엇을 자동으로 붙이지 않음). */
"use strict";

const CUSTOM_ST = { draft: ["아직 안 올림", "muted"], running: ["보내는 중", "info"], success: ["판매 중", "ok"], fail: ["실패", "bad"], deleted: ["내림", "muted"] };
// 직접 올린 그림의 업스타 안 주소 → 화면에서 보이는 주소
const CUSTOM_LOCAL = "http://upstar.local/custom/";
const cimg = (u) => (String(u || "").startsWith(CUSTOM_LOCAL) ? "/api/custom/img/" + String(u).slice(CUSTOM_LOCAL.length) : u);
const cimgHtml = (html) => String(html || "").split(CUSTOM_LOCAL).join("/api/custom/img/");

async function copyText(t) {
  try { await navigator.clipboard.writeText(t); App.toast("복사했습니다"); }
  catch (e) { window.prompt("복사하세요", t); }
}

async function uploadCustomImage(file) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await App.api("/api/custom/img", { method: "POST", body: fd });
  return r.url;
}

Object.assign(App, {
  /* 맞춤 상품 만들기·고치기 창. o: {id} 또는 {sourceId, listingId, storeId} */
  async customEdit(o = {}, after) {
    let d;
    try {
      d = o.id ? await this.api(`/api/custom/${o.id}`)
        : await this.api(`/api/custom/start?${new URLSearchParams({ source_id: o.sourceId || "", listing_id: o.listingId || "", store_id: o.storeId || "" })}`);
    } catch (e) { return this.toast(e.message, true); }
    const stores = this.stores || [];
    const live = d.status === "success" && d.origin_no;
    const startPrice = d.price || 0;
    const st = { thumbs: [...(d.thumbs || [])] };
    const opt = d.options || { groups: ["", "", ""], rows: [], editable: true };
    const optStock = d.opt_stock || {};
    const optRow = (r = {}) => {
      const k = [r.n1 || "", r.n2 || "", r.n3 || ""].join("|");
      const stock = r.stock ?? optStock[k] ?? "";
      return `<tr class="cu-opt">
        <td><input class="cu-n1" value="${esc(r.n1 || "")}" placeholder="값 1"></td><td><input class="cu-n2" value="${esc(r.n2 || "")}" placeholder="(없으면 비움)"></td>
        <td><input class="cu-n3" value="${esc(r.n3 || "")}" placeholder="(없으면 비움)"></td>
        <td><input class="cu-op" type="number" step="100" value="${r.price || 0}" style="width:90px"></td>
        <td><input class="cu-os" type="number" min="0" value="${esc(String(stock))}" placeholder="재고" style="width:76px"></td>
        <td class="c"><input type="checkbox" class="cu-use" ${r.usable === false ? "" : "checked"} title="판매(사용)"></td>
        <td><button type="button" class="btn tiny ghost cu-del" title="이 옵션 빼기">✕</button></td></tr>`;
    };
    const fromWhat = d.from_listing_id ? `복사본 #${d.from_listing_id}에서 시작` : d.from_source_id ? `원본 #${d.from_source_id}에서 시작` : "새로 만들기";
    this.openModal({
      title: d.id ? `고객 맞춤 상품 #${d.id}${live ? " · 판매 중" : ""}` : "고객 맞춤 상품 만들기", wide: true,
      body: (b) => {
        b.innerHTML = `<div class="notice info small">고객 문의용으로 <b>따로 올리는 상품</b>입니다 — 원본당 복사 수·후보상품명 칸·최신화·일괄 가격 수정 등 일괄 작업에 들어가지 않고, <b>자동으로 내리지 않습니다</b>.
            모든 값을 직접 적고 고치세요 (${esc(fromWhat)}${d.from_source_id ? " — 원본은 바뀌지 않음" : ""}).</div>
          <div class="cu-grid">
            <label class="field">스토어<select id="cu-store" ${live ? "disabled" : ""}>${stores.map((s) => `<option value="${s.id}" ${+d.store_id === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
            <label class="field">메모 <span class="muted small">(어느 고객·문의인지 — 업스타 안에서만)</span><input id="cu-memo" value="${esc(d.memo || "")}" placeholder="예) 11/23 김OO 고객 대량 30개 문의"></label>
            <label class="field cu-wide">상품명 <span class="muted small">(적은 그대로 올라갑니다)</span><input id="cu-name" maxlength="100" value="${esc(d.name || "")}"></label>
            <div class="field">손님 가격 (원)
              <div class="cl-row"><input id="cu-price" type="number" step="10" min="100" value="${d.price || ""}" style="width:140px">
                <span class="muted small">처음 ${num(startPrice)}원 기준</span>
                <input id="cu-dn" type="number" min="0" placeholder="n" style="width:80px">
                <button type="button" class="btn sm" data-dc="won">원 할인</button><button type="button" class="btn sm" data-dc="pct">% 할인</button></div>
              <span class="muted small">네이버 판매가·즉시할인은 스토어 템플릿의 표시 할인율로 자동 계산 (손님 가격은 그대로)</span></div>
            <label class="field">재고<input id="cu-stock" type="number" min="0" value="${d.stock ?? 100}" style="width:120px"></label>
          </div>
          <div class="se-tabs"><button type="button" class="on" data-cu="img">대표·추가 이미지</button><button type="button" data-cu="detail">상세페이지</button>
            <button type="button" data-cu="opt">옵션</button><button type="button" data-cu="ship">카테고리·배송</button><button type="button" data-cu="info">원산지·브랜드·노출</button></div>
          <div data-cus="img">
            <div class="cu-thumbs" id="cu-thumbs"></div>
            <div class="cl-row" style="margin-top:8px"><label class="btn sm">이미지 파일 올리기<input type="file" id="cu-tfile" accept="image/*" multiple hidden></label>
              <input id="cu-turl" placeholder="또는 이미지 주소 (https://…)" style="flex:1;min-width:200px"><button type="button" class="btn sm" id="cu-tadd">주소로 넣기</button></div>
            <p class="muted small">첫 장이 대표 이미지, 나머지는 추가 이미지 (최대 10장). ← → 로 순서 바꾸기. 네이버가 받지 않는 형식(WEBP 등)은 올릴 때 JPG로 바뀝니다.</p></div>
          <div data-cus="detail" hidden>
            <div class="cl-row"><label class="btn sm">이미지 파일 넣기 (맨 아래)<input type="file" id="cu-dfile" accept="image/*" multiple hidden></label>
              <button type="button" class="btn sm" id="cu-dprev">미리보기 새로 그리기</button><span class="muted small">스토어 상단·하단은 올릴 때 붙음</span></div>
            <textarea id="cu-html" rows="10" spellcheck="false" style="width:100%;font-family:ui-monospace,Consolas,monospace;font-size:12px;margin-top:6px">${esc(d.detail || "")}</textarea>
            <div class="small muted" style="margin:6px 0 4px">상세 속 이미지 — 바꾸기·지우기</div><div class="cu-dimgs" id="cu-dimgs"></div>
            <iframe id="cu-frame" sandbox="allow-same-origin" title="상세 미리보기" style="width:100%;height:320px;border:1px solid var(--line);border-radius:8px;margin-top:6px;background:#fff"></iframe></div>
          <div data-cus="opt" hidden>
            ${opt.editable ? `<p class="small muted" style="margin:0 0 6px">옵션 이름(예: 색상·사이즈)·값·추가금(손님 가격에 더하는 금액, 그대로 올라감)·재고를 고치세요. 모든 옵션을 빼면 옵션 없는 상품.</p>
              <div class="cl-row"><label class="field" style="margin:0">옵션 이름 1<input id="cu-g1" value="${esc(opt.groups[0] || "")}" placeholder="예) 색상"></label>
                <label class="field" style="margin:0">옵션 이름 2<input id="cu-g2" value="${esc(opt.groups[1] || "")}" placeholder="(없으면 비움)"></label>
                <label class="field" style="margin:0">옵션 이름 3<input id="cu-g3" value="${esc(opt.groups[2] || "")}" placeholder="(없으면 비움)"></label></div>
              <div class="tbl-wrap" style="max-height:300px;margin-top:8px"><table class="grid small se-table"><thead><tr><th>값 1</th><th>값 2</th><th>값 3</th><th>추가금(원)</th><th>재고</th><th>판매</th><th></th></tr></thead>
                <tbody id="cu-rows">${opt.rows.map(optRow).join("")}</tbody></table></div>
              <button type="button" class="btn sm" id="cu-add" style="margin-top:6px">+ 옵션 더하기</button>`
            : `<div class="notice warn">${esc(opt.note || "고칠 수 없는 옵션입니다.")} — 그대로 올라갑니다.</div>`}</div>
          <div data-cus="ship" hidden>
            <div class="cu-grid">
              <div class="field cu-wide">카테고리<div class="cl-row"><input id="cu-cat" value="${esc(d.category || "")}" style="flex:1;min-width:240px" placeholder="대>중>소>세"><input id="cu-catq" placeholder="찾을 말" style="width:140px"><button type="button" class="btn sm" id="cu-catgo">찾기</button></div>
                <div id="cu-catres" class="small"></div></div>
              <label class="field">출고지 (주소록 번호)<div class="cl-row"><input id="cu-ship" value="${esc(d.ship_addr || "")}" placeholder="비우면 템플릿·기본" style="width:160px"><select id="cu-shipsel" hidden></select></div></label>
              <label class="field">반품·교환지 (주소록 번호)<div class="cl-row"><input id="cu-ret" value="${esc(d.return_addr || "")}" placeholder="비우면 템플릿·기본" style="width:160px"><select id="cu-retsel" hidden></select></div></label>
              <div class="field"><button type="button" class="btn sm" id="cu-addr">판매자센터 주소록 불러오기</button><span class="muted small"> 출고지·반품지를 목록에서 고름</span></div>
              <label class="field">배송비 (원, 0이면 무료)<input id="cu-fee" type="number" min="0" step="100" value="${d.fee || 0}" style="width:140px"></label>
            </div></div>
          <div data-cus="info" hidden>
            <label class="check"><input type="checkbox" id="cu-rules" ${d.follow_rules === 0 ? "" : "checked"}><span>원산지·브랜드·제조사·모델명은 <b>설정 규칙</b>대로 (원산지 강제·'상세페이지 참조')</span></label>
            <div class="cu-grid" id="cu-infos">
              <label class="field">원산지 <span class="muted small">(설정 → 상품 기본값 → 원산지 코드에 있는 이름, 예: 중국)</span><input id="cu-origin" value="${esc(d.origin || "")}"></label>
              <label class="field">브랜드<input id="cu-brand" value="${esc(d.brand || "")}"></label>
              <label class="field">제조사<input id="cu-maker" value="${esc(d.maker || "")}"></label>
              <label class="field">모델명<input id="cu-model" value="${esc(d.model || "")}"></label></div>
            <label class="check" style="margin-top:10px"><input type="checkbox" id="cu-search" ${d.show_search ? "checked" : ""}><span><b>네이버쇼핑 검색에 노출</b> <span class="muted small">(끄면 네이버쇼핑 검색에만 안 나옴 — 스토어 페이지와 상품 링크로는 그대로 열리고 살 수 있음. 같은 상품이 검색에 두 번 뜨지 않게 기본 끔)</span></span></label>
          </div>`;
        const drawThumbs = () => {
          $("#cu-thumbs", b).innerHTML = st.thumbs.length ? st.thumbs.map((u, i) => `<div class="cu-thumb"><img src="${esc(cimg(u))}" referrerpolicy="no-referrer" alt="" onerror="onImgError(this)">
            <div class="small">${i === 0 ? "<b>대표</b>" : `추가 ${i}`}</div>
            <div class="cu-tbtn"><button type="button" class="btn tiny" data-tl="${i}" ${i === 0 ? "disabled" : ""}>←</button><button type="button" class="btn tiny" data-tr="${i}" ${i === st.thumbs.length - 1 ? "disabled" : ""}>→</button>
              <button type="button" class="btn tiny ghost" data-tx="${i}">✕</button></div></div>`).join("") : '<p class="muted small">이미지가 없습니다 — 파일을 올리거나 주소를 넣으세요.</p>';
        };
        const draw = () => { $("#cu-frame", b).srcdoc = `<meta name="referrer" content="no-referrer"><style>body{margin:0}img{max-width:100%}video,iframe{display:block;margin:0 auto;max-width:100%}</style>` + cimgHtml($("#cu-html", b).value); };
        const drawDimgs = () => {
          const srcs = [...new Set([...$("#cu-html", b).value.matchAll(/<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']/gi)].map((m) => m[1]))];
          $("#cu-dimgs", b).innerHTML = srcs.length ? srcs.map((u, i) => `<div class="cu-thumb"><img src="${esc(cimg(u))}" referrerpolicy="no-referrer" alt="" onerror="onImgError(this)">
            <div class="cu-tbtn"><label class="btn tiny">바꾸기<input type="file" accept="image/*" data-drep="${i}" hidden></label><button type="button" class="btn tiny ghost" data-ddel="${i}">지우기</button></div></div>`).join("")
            : '<p class="muted small">상세에 이미지가 없습니다.</p>';
          b._dsrcs = srcs;
        };
        const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        drawThumbs(); draw(); drawDimgs();
        const rules = () => { $$("#cu-infos input", b).forEach((x) => { x.disabled = $("#cu-rules", b).checked; }); };
        rules();
        $("#cu-rules", b).addEventListener("change", rules);
        $$(".se-tabs button", b).forEach((t) => t.addEventListener("click", () => {
          $$(".se-tabs button", b).forEach((x) => x.classList.toggle("on", x === t));
          $$("[data-cus]", b).forEach((x) => { x.hidden = x.dataset.cus !== t.dataset.cu; });
          if (t.dataset.cu === "detail") { draw(); drawDimgs(); }
        }));
        $$("[data-dc]", b).forEach((x) => x.addEventListener("click", () => {
          const n = +$("#cu-dn", b).value || 0;
          if (!n) return App.toast("할인할 값(n)을 적으세요", true);
          const v = x.dataset.dc === "won" ? startPrice - n : Math.round((startPrice * (100 - n)) / 100 / 10) * 10;
          if (v < 100) return App.toast("할인한 가격이 너무 낮습니다", true);
          $("#cu-price", b).value = v;
        }));
        $("#cu-thumbs", b).addEventListener("click", (e) => {
          const l = e.target.closest("[data-tl]"), r = e.target.closest("[data-tr]"), x = e.target.closest("[data-tx]");
          if (l) { const i = +l.dataset.tl; [st.thumbs[i - 1], st.thumbs[i]] = [st.thumbs[i], st.thumbs[i - 1]]; }
          else if (r) { const i = +r.dataset.tr; [st.thumbs[i + 1], st.thumbs[i]] = [st.thumbs[i], st.thumbs[i + 1]]; }
          else if (x) st.thumbs.splice(+x.dataset.tx, 1);
          else return;
          drawThumbs();
        });
        $("#cu-tfile", b).addEventListener("change", async (e) => {
          for (const f of [...e.target.files]) {
            if (st.thumbs.length >= 10) { App.toast("대표·추가 이미지는 10장까지입니다", true); break; }
            try { st.thumbs.push(await uploadCustomImage(f)); } catch (err) { App.toast(`${f.name}: ${err.message}`, true); }
          }
          e.target.value = ""; drawThumbs();
        });
        $("#cu-tadd", b).addEventListener("click", () => {
          const u = $("#cu-turl", b).value.trim();
          if (!/^https?:\/\//.test(u)) return App.toast("http로 시작하는 이미지 주소를 넣으세요", true);
          if (st.thumbs.length >= 10) return App.toast("대표·추가 이미지는 10장까지입니다", true);
          st.thumbs.push(u); $("#cu-turl", b).value = ""; drawThumbs();
        });
        $("#cu-dprev", b).addEventListener("click", () => { draw(); drawDimgs(); });
        $("#cu-html", b).addEventListener("change", drawDimgs);
        $("#cu-dfile", b).addEventListener("change", async (e) => {
          let add = "";
          for (const f of [...e.target.files]) {
            try { add += `<p style="text-align:center"><img src="${await uploadCustomImage(f)}" style="max-width:100%"></p>`; } catch (err) { App.toast(`${f.name}: ${err.message}`, true); }
          }
          e.target.value = "";
          if (add) { $("#cu-html", b).value += add; draw(); drawDimgs(); }
        });
        $("#cu-dimgs", b).addEventListener("change", async (e) => {
          const inp = e.target.closest("[data-drep]");
          if (!inp || !inp.files[0]) return;
          const old = b._dsrcs[+inp.dataset.drep];
          try {
            const u = await uploadCustomImage(inp.files[0]);
            $("#cu-html", b).value = $("#cu-html", b).value.split(old).join(u);
            draw(); drawDimgs();
          } catch (err) { App.toast(err.message, true); }
        });
        $("#cu-dimgs", b).addEventListener("click", (e) => {
          const x = e.target.closest("[data-ddel]");
          if (!x) return;
          const old = b._dsrcs[+x.dataset.ddel];
          const ta = $("#cu-html", b);
          ta.value = ta.value.replace(new RegExp(`<img\\b[^>]*?\\bsrc\\s*=\\s*["']${escRe(old)}["'][^>]*>`, "gi"), "");
          draw(); drawDimgs();
        });
        $("#cu-add", b)?.addEventListener("click", () => { $("#cu-rows", b).insertAdjacentHTML("beforeend", optRow({ usable: true })); $("#cu-rows tr:last-child .cu-n1", b).focus(); });
        $("#cu-rows", b)?.addEventListener("click", (e) => { const x = e.target.closest(".cu-del"); if (x) x.closest("tr").remove(); });
        $("#cu-catgo", b).addEventListener("click", async () => {
          const q = $("#cu-catq", b).value.trim();
          if (!q) return;
          const r = await App.api(`/api/categories/search?q=${encodeURIComponent(q)}`);
          $("#cu-catres", b).innerHTML = r.length ? r.map((n) => `<button type="button" class="link-btn" data-cat="${esc(n)}">${esc(n)}</button>`).join("<br>") : "찾은 카테고리가 없습니다";
        });
        $("#cu-catres", b).addEventListener("click", (e) => { const x = e.target.closest("[data-cat]"); if (x) { $("#cu-cat", b).value = x.dataset.cat; $("#cu-catres", b).innerHTML = ""; } });
        $("#cu-addr", b).addEventListener("click", async () => {
          try {
            const list = await App.api(`/api/stores/${$("#cu-store", b).value}/addresses`);
            for (const [inp, sel] of [["#cu-ship", "#cu-shipsel"], ["#cu-ret", "#cu-retsel"]]) {
              const s = $(sel, b);
              s.innerHTML = '<option value="">(골라 넣기)</option>' + list.map((a) => `<option value="${esc(a.id)}">${esc(a.name || "")} · ${esc(a.address || "")}</option>`).join("");
              s.hidden = false;
              s.onchange = () => { if (s.value) $(inp, b).value = s.value; };
            }
          } catch (err) { App.toast(err.message, true); }
        });
      },
      buttons: [
        { label: "닫기" },
        ...(d.id && !live ? [{ label: "업스타에서 지우기", danger: true, confirm: "이 맞춤 상품을 업스타에서 지웁니다 (네이버에 올라가 있지 않은 것만).", onClick: async () => {
          await this.api(`/api/custom/${d.id}/remove`, { json: {} }); this.toast("지웠습니다"); if (after) after();
        } }] : []),
        { label: "저장만", noConfirm: true, onClick: async (b) => { const r = await this._customSave(b, d, st); if (!r) return false; this.toast("저장했습니다 (아직 네이버에 보내지 않음)" + (r.warnings?.length ? ` · ${r.warnings.join(" · ")}` : ""), !!r.warnings?.length); if (after) after(); } },
        { label: live ? "저장하고 수정해서 다시 보내기" : "저장하고 네이버에 올리기", primary: true, noPicks: true,
          get confirm() {
            const b = $("#m-body");
            const name = $("#cu-name", b)?.value || "", price = +$("#cu-price", b)?.value || 0;
            const sname = $("#cu-store", b)?.selectedOptions?.[0]?.textContent || "";
            return `<b>${esc(sname)}</b>에 ${live ? "올라가 있는 맞춤 상품을 <b>수정해서 다시 보냅니다</b> (상품번호 그대로)" : "맞춤 상품을 <b>새로 올립니다</b>"}<br>
              상품명: ${esc(name)}<br>손님 가격 ${num(price)}원 · 이미지 ${num(st.thumbs.length)}장 · 네이버쇼핑 검색 노출 ${$("#cu-search", b)?.checked ? "함" : "안 함"}`;
          },
          validate: (b) => (!$("#cu-name", b).value.trim() ? "상품명을 적어 주세요." : !st.thumbs.length ? "대표 이미지를 넣어 주세요." : !$("#cu-html", b).value.trim() ? "상세페이지가 비었습니다." : ""),
          onClick: async (b) => {
            const r = await this._customSave(b, d, st);
            if (!r) return false;
            if (r.warnings?.length) this.toast(r.warnings.join(" · "), true);
            const h = (t) => {
              if (t.kind !== "custom") return;
              this.off("task-done", h);
              if (after) after();
              if (t.status === "done" && t.result) this.customResult(t.result);
            };
            this.on("task-done", h);
            await this.startTask(this.api(`/api/custom/${r.id}/send`, { json: {} }));
          } },
      ],
    });
  },

  async _customSave(b, d, st) {
    const opt = d.options || {};
    const payload = {
      id: d.id || null, store_id: +$("#cu-store", b).value, from_source_id: d.from_source_id || null, from_listing_id: d.from_listing_id || null,
      name: $("#cu-name", b).value, price: +$("#cu-price", b).value || 0, stock: +$("#cu-stock", b).value || 0, memo: $("#cu-memo", b).value,
      thumbs: st.thumbs, detail: $("#cu-html", b).value, category: $("#cu-cat", b).value, ship_addr: $("#cu-ship", b).value, return_addr: $("#cu-ret", b).value,
      fee: +$("#cu-fee", b).value || 0, follow_rules: $("#cu-rules", b).checked, origin: $("#cu-origin", b).value, brand: $("#cu-brand", b).value,
      maker: $("#cu-maker", b).value, model: $("#cu-model", b).value, show_search: $("#cu-search", b).checked,
    };
    if (opt.editable !== false && $("#cu-g1", b)) {
      payload.options = { groups: [1, 2, 3].map((i) => $(`#cu-g${i}`, b).value),
        rows: $$(".cu-opt", b).map((tr) => ({ n1: $(".cu-n1", tr).value, n2: $(".cu-n2", tr).value, n3: $(".cu-n3", tr).value,
          price: +$(".cu-op", tr).value || 0, stock: $(".cu-os", tr).value, usable: $(".cu-use", tr).checked })) };
    }
    try { return await this.api("/api/custom/save", { json: payload }); }
    catch (e) { this.toast(e.message, true); return null; }
  },

  /* 올린 뒤: 상품 링크 복사 · 판매자센터에서 열기 · 마케팅 링크(판매자센터에서 만들기) */
  customResult(r) {
    this.openModal({
      title: "맞춤 상품 올림",
      body: `<p>${esc(r.message || "")}</p>${r.notes?.length ? `<p class="small muted">${esc(r.notes.join(" · "))}</p>` : ""}
        ${r.url ? `<div class="cl-row"><input id="cr-url" value="${esc(r.url)}" readonly style="flex:1;min-width:240px"><button type="button" class="btn sm primary" id="cr-copy">상품 링크 복사</button></div>` : '<p class="muted small">스토어 주소가 없어 링크를 만들 수 없습니다 (스토어 수정에서 주소 넣기).</p>'}
        <div class="cl-row" style="margin-top:8px">${r.seller_url ? `<a class="btn sm" href="${esc(r.seller_url)}" target="_blank" rel="noopener">판매자센터에서 이 상품 열기 ↗</a>` : ""}
          <a class="btn sm" href="${esc(r.marketing_url || "")}" target="_blank" rel="noopener" title="마케팅 링크는 판매자센터에서 만듭니다 (업스타가 자동으로 만들지 않음)">마케팅 링크 만들기 (판매자센터 열기) ↗</a></div>`,
      buttons: [{ label: "닫기" }],
    });
    $("#cr-copy")?.addEventListener("click", () => copyText(r.url));
  },
});

/* 복사본 화면 '맞춤 상품' 칸: 이 스토어 맞춤 상품 목록 */
const Custom = {
  async render(box, storeId, q = "") {
    let res;
    try { res = await App.api(`/api/custom?${new URLSearchParams({ store_id: storeId, q })}`); } catch (e) { box.innerHTML = `<p class="c-err">${esc(e.message)}</p>`; return; }
    const rows = res.rows || [];
    box.innerHTML = `<div class="card table-card"><div class="sec-head pad-x"><h2>고객 맞춤 상품 <span class="muted small">${num(rows.length)}개 — 복사본과 따로 (복사 수·일괄 작업에 안 들어감, 자동으로 내리지 않음)</span></h2>
        <button class="btn sm primary" id="cu-new">맞춤 상품 새로 만들기</button></div>
      <table class="grid"><thead><tr><th>상품명 · 메모</th><th class="w-num">손님 가격</th><th class="w-round">관리코드 · 올린 날</th><th class="w-status">상태</th><th>판매 이력</th><th></th></tr></thead>
      <tbody>${rows.length ? rows.map((r) => {
        const [lab, cls] = CUSTOM_ST[r.status] || [r.status, ""];
        return `<tr data-cid="${r.id}"><td><div class="p-name">${esc(r.name)}</div>${r.memo ? `<div class="p-sub">${esc(r.memo)}</div>` : ""}${r.message && r.status !== "success" ? `<div class="p-sub c-err">${esc(r.message)}</div>` : ""}</td>
          <td class="num">${num(r.price)}원</td><td class="small">${esc(r.seller_code)}<div class="p-sub">${r.registered_at ? ymd(r.registered_at) : "-"}${r.show_search ? "" : " · 검색 노출 안 함"}</div></td>
          <td><span class="flag ${cls}">${lab}</span>${r.locked ? ` <span class="flag" title="${esc(r.lock_note)}">잠김</span>` : ""}</td>
          <td class="small">${r.sold_count ? `${num(r.sold_count)}개` : "-"}</td>
          <td class="nowrap">${r.url ? `<button class="btn tiny" data-cu-copy="${esc(r.url)}">링크 복사</button> ` : ""}<button class="btn tiny" data-cu-edit="${r.id}">${r.status === "success" ? "고치기·다시 보내기" : "고치기·올리기"}</button>
            ${r.status === "success" && !r.locked ? ` <button class="btn tiny ghost danger" data-cu-drop="${r.id}">내리기</button>` : ""}</td></tr>`;
      }).join("") : '<tr class="empty-row"><td colspan="6">아직 맞춤 상품이 없습니다 — [맞춤 상품 새로 만들기] 또는 복사본·원본 상세의 [고객 맞춤 상품 만들기]</td></tr>'}</tbody></table></div>`;
    const again = () => this.render(box, storeId, q);
    $("#cu-new", box).addEventListener("click", () => App.customEdit({ storeId }, again));
    box.onclick = async (e) => {
      const c = e.target.closest("[data-cu-copy]"), ed = e.target.closest("[data-cu-edit]"), dr = e.target.closest("[data-cu-drop]");
      if (c) copyText(c.dataset.cuCopy);
      else if (ed) App.customEdit({ id: +ed.dataset.cuEdit }, again);
      else if (dr) {
        if (!await App.yes("맞춤 상품 내리기", "이 맞춤 상품을 네이버에서 지웁니다 (판매 이력이 있으면 잠겨 막힘 · 판매 이력 확인이 유효 시간 안일 때만).", { label: "내리기", danger: true })) return;
        try { await App.api(`/api/custom/${dr.dataset.cuDrop}/drop`, { json: {} }); App.toast("내렸습니다"); again(); } catch (err) { App.toast(err.message, true); }
      }
    };
  },
};
