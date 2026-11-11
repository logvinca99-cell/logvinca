"""폰으로 보기: 스토어에 올라간 복사본을 폰에서 보고, 누르면 네이버 스토어 상품이 바로 열리게.

두 가지 방법 (화면은 같음):
- 폰용 파일: 한 개짜리 HTML(데이터·화면 내장, 외부 파일 없음)을 내려받아 카톡 '나와의 채팅' 등으로 폰에 보내 연다 — 받은 때 기준.
- 같은 와이파이 실시간: 설정에서 켜면 업스타가 이 PC의 내부 주소로도 열리고, 열쇠(key)가 든 주소의 /m 화면만 폰에서 열린다.
  그 밖의 화면·API는 이 PC(127.0.0.1)에서만 — 폰에서는 읽기만.
순서는 업스타 그대로: 스토어 번호 순, 그 안에서 복사본 번호 순 (복사본 화면과 같음). 휴지통에 간 것은 없음.
"""

import hmac
import json
import os
import secrets
import socket
import time

from . import config, inventory

ST = {"success": "on", "planned": "wait", "fail": "fail", "queued": "run", "running": "run", "deleted": "off"}


def store_home(u):
    """core.js storeHome과 같은 규칙: 주소면 그대로(끝 / 뺌), 아니면 smartstore.naver.com/<이름>."""
    u = str(u or "").strip()
    if not u:
        return ""
    if u.startswith(("http://", "https://")):
        return u.rstrip("/")
    return "https://smartstore.naver.com/" + u.strip("/")


def data(db, store_id=None, live=False):
    """화면 자료. rows: [스토어, 순번, 상품명, 손님 가격, 상태, 잠김, 판매 수, 올린 날(초), 판매자코드, 채널상품번호, 썸네일]."""
    from . import VERSION
    stores = db.q("SELECT id, name, store_url FROM stores ORDER BY id")
    if store_id:
        stores = [s for s in stores if s["id"] == int(store_id)]
    pv = inventory.price_viewer(db)
    rows, out_stores = [], []
    for s in stores:
        n_on = 0
        seq = 0
        for r in db.q("""SELECT l.id, l.name, l.price, l.sale_shown, l.status, l.op, l.locked, l.sold_count, l.registered_at,
                l.seller_code, l.channel_no, l.origin_no, s.thumb
                FROM listings l JOIN sources s ON s.id=l.source_id WHERE l.store_id=? ORDER BY l.id""", (s["id"],)):
            seq += 1
            st = ST.get(r["status"], "wait")
            if r["op"] == "delete" and r["status"] in ("planned", "fail") and r["origin_no"]:
                st = "drop"   # 판매 중인데 내리기 대기
            n_on += st in ("on", "drop")
            final = pv(r["price"], s["id"], bool(r["origin_no"]), r["sale_shown"])["final"]
            rows.append([s["id"], seq, r["name"] or "", int(final or 0), st, int(r["locked"] or 0), int(r["sold_count"] or 0),
                         int(r["registered_at"] or 0), r["seller_code"] or "", r["channel_no"] or "", r["thumb"] or ""])
        out_stores.append({"id": s["id"], "name": s["name"], "home": store_home(s["store_url"]), "on": n_on, "n": seq})
    return {"at": time.time(), "live": bool(live), "version": VERSION, "stores": out_stores, "rows": rows}


def file_html(db, store_id=None):
    return page(data(db, store_id))


def page(d=None):
    """d가 있으면 자료를 넣은 파일, 없으면 실시간(/m/data에서 받음)."""
    blob = "null" if d is None else json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return HTML.replace("/*DATA*/null", blob)


# ── 같은 와이파이

def ensure_key(cfg=None):
    cfg = cfg or config.load()
    if not cfg.get("phone_key"):
        cfg = config.save({"phone_key": secrets.token_urlsafe(12)})
    return cfg["phone_key"]


def new_key():
    return config.save({"phone_key": secrets.token_urlsafe(12)})["phone_key"]


def key_ok(key, cfg=None):
    cfg = cfg or config.load()
    want = cfg.get("phone_key") or ""
    return bool(cfg.get("phone_view") and want and key and hmac.compare_digest(str(key), want))


def is_local(addr):
    a = str(addr or "")
    return a.startswith("127.") or a in ("::1", "localhost") or a.startswith("::ffff:127.")


def lan_ips():
    """이 PC의 내부 주소 (폰이 같은 와이파이에서 들어올 주소). 바깥으로 실제로 보내지는 않음."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for x in socket.gethostbyname_ex(socket.gethostname())[2]:
            if x not in ips:
                ips.append(x)
    except OSError:
        pass
    return [x for x in ips if not x.startswith("127.")] or ["(이 PC 내부 주소를 찾지 못함)"]


def bound_all():
    return os.environ.get("UPLOADER_BIND") == "0.0.0.0"


HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="referrer" content="no-referrer">
<title>업스타 · 폰으로 보기</title>
<style>
:root{--bg:#f4f6f5;--card:#fff;--ink:#16201b;--mute:#66736c;--line:#e2e8e4;--brand:#1f8f4e;--brand2:#e7f5ec;
--on:#1f8f4e;--wait:#8a6d00;--waitbg:#fff4cc;--fail:#c62828;--failbg:#fde7e7;--off:#6b7280;--offbg:#eceff1;--run:#1565c0;--runbg:#e3f0fd;--onbg:#e3f6ea;--lock:#7b4dc4;--lockbg:#efe7fb}
@media (prefers-color-scheme:dark){:root{--bg:#0f1412;--card:#18201c;--ink:#e8efe9;--mute:#97a49c;--line:#27312c;--brand:#3ccf7b;--brand2:#173323;
--on:#5fdc93;--onbg:#173323;--wait:#ffd45c;--waitbg:#3a3112;--fail:#ff7b7b;--failbg:#3d1a1a;--off:#a2aab3;--offbg:#262c31;--run:#7ab8ff;--runbg:#13283f;--lock:#c4a5ff;--lockbg:#2a2140}}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.4 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;-webkit-text-size-adjust:100%}
header{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 16px 8px;border-bottom:1px solid var(--line)}
.top{display:flex;align-items:center;gap:8px}.logo{font-weight:800;font-size:20px;color:var(--brand);letter-spacing:-.5px}
.when{flex:1;min-width:0;font-size:13px;color:var(--mute);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rf{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:10px;padding:7px 12px;font-size:14px}
.tabs{display:flex;gap:6px;overflow-x:auto;margin:10px -16px 0;padding:0 16px 2px;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}
.tab{flex:0 0 auto;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:8px 14px;font-size:15px;font-weight:600}
.tab small{font-weight:500;color:var(--mute);margin-left:4px}.tab.on{background:var(--brand);border-color:var(--brand);color:#fff}.tab.on small{color:#e6fff0}
.bar{display:flex;gap:8px;margin-top:10px}
.q{flex:1;min-width:0;font-size:16px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--ink)}
.home{flex:0 0 auto;display:inline-flex;align-items:center;padding:0 14px;border-radius:12px;background:var(--brand2);color:var(--brand);font-weight:700;text-decoration:none;font-size:15px}
.home.dis{opacity:.45;pointer-events:none}
.chips{display:flex;gap:6px;margin-top:8px;overflow-x:auto;scrollbar-width:none}.chips::-webkit-scrollbar{display:none}
.chip{flex:0 0 auto;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 12px;font-size:14px}
.chip.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
main{padding:10px 12px 40px}.count{font-size:13px;color:var(--mute);margin:2px 4px 8px}
.it{display:flex;gap:12px;align-items:stretch;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px;margin-bottom:8px;color:inherit;text-decoration:none;min-height:96px}
a.it:active{transform:scale(.99);background:var(--brand2)}
.it.dis{opacity:.62}
.th{flex:0 0 76px;height:76px;border-radius:10px;background:var(--line);overflow:hidden;align-self:center}.th img{width:100%;height:100%;object-fit:cover;display:block}
.bd{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px}
.l1{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--mute);min-width:0}
.seq{font-weight:700;color:var(--ink);background:var(--bg);border-radius:6px;padding:1px 6px}
.sn{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nm{font-size:15px;font-weight:600;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-all}
.l3{display:flex;align-items:center;flex-wrap:wrap;gap:6px}
.pr{font-size:17px;font-weight:800}.pr small{font-size:12px;font-weight:500;color:var(--mute);margin-left:2px}
.b{font-size:12px;font-weight:700;border-radius:6px;padding:2px 7px}
.b.on{color:var(--on);background:var(--onbg)}.b.wait{color:var(--wait);background:var(--waitbg)}.b.fail{color:var(--fail);background:var(--failbg)}
.b.off{color:var(--off);background:var(--offbg)}.b.run{color:var(--run);background:var(--runbg)}.b.drop{color:var(--fail);background:var(--failbg)}.b.lock{color:var(--lock);background:var(--lockbg)}
.b.sold{color:var(--brand);background:var(--brand2)}
.l4{font-size:12px;color:var(--mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.go{flex:0 0 auto;align-self:center;font-size:22px;color:var(--mute);padding-left:2px}
.more{display:block;width:100%;padding:14px;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:15px;font-weight:600}
.empty{text-align:center;color:var(--mute);padding:40px 10px}
.err{margin:12px;padding:14px;border-radius:12px;background:var(--failbg);color:var(--fail)}
</style></head><body>
<header>
  <div class="top"><span class="logo">업스타</span><span class="when" id="when"></span><button class="rf" id="rf" hidden>새로고침</button></div>
  <div class="tabs" id="tabs"></div>
  <div class="bar"><input class="q" id="q" type="search" placeholder="상품명·판매자코드 찾기" autocomplete="off"><a class="home" id="home" target="_blank" rel="noopener noreferrer">스토어 ↗</a></div>
  <div class="chips" id="chips"></div>
</header>
<main><div class="count" id="count"></div><div id="list"></div><button class="more" id="more" hidden>더 보기</button></main>
<script>
"use strict";
var D = /*DATA*/null;
var LABEL = {on: "판매 중", wait: "대기", fail: "실패", run: "처리 중", off: "내림", drop: "내리기 대기"};
var FILT = [["all", "전체"], ["on", "판매 중"], ["wf", "대기·실패"], ["off", "내림"], ["lock", "잠김"]];
var STEP = 100, S = {store: null, f: "all", q: "", shown: 0, list: []};
var $ = function (id) { return document.getElementById(id); };
function el(tag, cls, txt) { var e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }
function won(n) { return (n || 0).toLocaleString("ko-KR"); }
function day(t) { if (!t) return ""; var d = new Date(t * 1000); return (d.getMonth() + 1) + "/" + d.getDate(); }
function stamp(t) { var d = new Date(t * 1000), p = function (x) { return (x < 10 ? "0" : "") + x; };
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes()); }
function key() { var m = /[?&]key=([^&]+)/.exec(location.search); return m ? decodeURIComponent(m[1]) : ""; }
function storeOf(id) { for (var i = 0; i < D.stores.length; i++) if (D.stores[i].id === id) return D.stores[i]; return null; }
function match(r) {
  var f = S.f, st = r[4];
  if (S.store !== 0 && r[0] !== S.store) return false;
  if (f === "on" && st !== "on" && st !== "drop") return false;
  if (f === "wf" && st !== "wait" && st !== "fail" && st !== "run") return false;
  if (f === "off" && st !== "off") return false;
  if (f === "lock" && !r[5]) return false;
  if (S.q) { var q = S.q; if (r[2].toLowerCase().indexOf(q) < 0 && r[8].toLowerCase().indexOf(q) < 0 && r[9].indexOf(q) < 0) return false; }
  return true;
}
function card(r) {
  var s = storeOf(r[0]) || {}, url = s.home && r[9] ? s.home + "/products/" + r[9] : "";
  var a = el(url ? "a" : "div", "it" + (url ? "" : " dis"));
  if (url) { a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
  var th = el("div", "th");
  if (r[10]) { var im = el("img"); im.loading = "lazy"; im.decoding = "async"; im.referrerPolicy = "no-referrer"; im.alt = ""; im.src = r[10];
    im.onerror = function () { im.remove(); }; th.appendChild(im); }
  a.appendChild(th);
  var bd = el("div", "bd"), l1 = el("div", "l1");
  l1.appendChild(el("span", "seq", "#" + r[1]));
  if (S.store === 0) l1.appendChild(el("span", "sn", s.name || ""));
  bd.appendChild(l1);
  bd.appendChild(el("div", "nm", r[2]));
  var l3 = el("div", "l3"), pr = el("span", "pr", won(r[3])); pr.appendChild(el("small", "", "원"));
  l3.appendChild(pr);
  l3.appendChild(el("span", "b " + r[4], LABEL[r[4]] || ""));
  if (!url && r[4] !== "off") l3.appendChild(el("span", "b off", r[9] ? "스토어 주소 없음" : "아직 안 올림"));
  if (r[5]) l3.appendChild(el("span", "b lock", "잠김"));
  if (r[6]) l3.appendChild(el("span", "b sold", "판매 " + r[6]));
  bd.appendChild(l3);
  var info = [r[7] ? "올린 날 " + day(r[7]) : "", r[8]].filter(Boolean).join(" · ");
  if (info) bd.appendChild(el("div", "l4", info));
  a.appendChild(bd);
  if (url) a.appendChild(el("span", "go", "›"));
  return a;
}
function paintMore() {
  var box = $("list"), end = Math.min(S.list.length, S.shown + STEP), frag = document.createDocumentFragment();
  for (var i = S.shown; i < end; i++) frag.appendChild(card(S.list[i]));
  box.appendChild(frag); S.shown = end;
  $("more").hidden = S.shown >= S.list.length;
  $("more").textContent = "더 보기 (" + won(S.list.length - S.shown) + "개 남음)";
}
function paint() {
  S.list = D.rows.filter(match); S.shown = 0; $("list").innerHTML = "";
  var c = {all: 0, on: 0, wf: 0, off: 0, lock: 0};
  D.rows.forEach(function (r) { if (S.store !== 0 && r[0] !== S.store) return; c.all++;
    if (r[4] === "on" || r[4] === "drop") c.on++; else if (r[4] === "off") c.off++; else c.wf++; if (r[5]) c.lock++; });
  var ch = $("chips"); ch.innerHTML = "";
  FILT.forEach(function (f) { var b = el("button", "chip" + (S.f === f[0] ? " on" : ""), f[1] + " " + won(c[f[0]])); b.onclick = function () { S.f = f[0]; paint(); }; ch.appendChild(b); });
  var tb = $("tabs"); tb.innerHTML = "";
  var tabs = D.stores.length > 1 ? [{id: 0, name: "전체", on: D.stores.reduce(function (a, s) { return a + s.on; }, 0)}].concat(D.stores) : D.stores;
  tabs.forEach(function (s) { var b = el("button", "tab" + (S.store === s.id ? " on" : ""), s.name); b.appendChild(el("small", "", won(s.on)));
    b.onclick = function () { S.store = s.id; try { localStorage.setItem("upstar_store", String(s.id)); } catch (e) {} paint(); window.scrollTo(0, 0); }; tb.appendChild(b); });
  var cur = storeOf(S.store), hm = $("home");
  if (cur && cur.home) { hm.href = cur.home; hm.className = "home"; } else { hm.removeAttribute("href"); hm.className = "home dis"; }
  $("count").textContent = (S.list.length ? won(S.list.length) + "개 · 업스타 복사본 순서 · 누르면 네이버 스토어 상품" : "");
  if (!S.list.length) $("list").appendChild(el("div", "empty", "맞는 상품이 없습니다"));
  paintMore();
}
function start(d) {
  D = d;
  $("when").textContent = (d.live ? "실시간 · " + stamp(d.at) + " 갱신" : stamp(d.at) + " 기준 (받은 파일)");
  var saved = null; try { saved = +localStorage.getItem("upstar_store"); } catch (e) {}
  var ids = d.stores.map(function (s) { return s.id; });
  if (S.store === null || (S.store !== 0 && ids.indexOf(S.store) < 0)) S.store = ids.indexOf(saved) >= 0 || (saved === 0 && ids.length > 1) ? saved : (ids[0] || 0);
  paint();
}
function load() {
  $("when").textContent = "불러오는 중…";
  fetch("/m/data?key=" + encodeURIComponent(key()), {cache: "no-store"}).then(function (r) {
    if (!r.ok) throw new Error(r.status === 403 ? "열쇠가 맞지 않거나 업스타에서 '폰으로 보기'가 꺼져 있습니다. 업스타의 [폰으로 보기] 창에서 주소를 다시 확인하세요." : "업스타에 연결하지 못했습니다 (" + r.status + ")");
    return r.json(); }).then(start).catch(function (e) {
    $("when").textContent = ""; $("list").innerHTML = ""; $("list").appendChild(el("div", "err", e.message || "업스타에 연결하지 못했습니다 — PC에서 업스타가 켜져 있고 같은 와이파이인지 확인하세요."));
  });
}
$("more").onclick = paintMore;
if ("IntersectionObserver" in window) new IntersectionObserver(function (es) { if (es[0].isIntersecting && !$("more").hidden) paintMore(); }, {rootMargin: "600px"}).observe($("more"));
var tq; $("q").addEventListener("input", function () { clearTimeout(tq); tq = setTimeout(function () { S.q = $("q").value.trim().toLowerCase(); paint(); }, 200); });
if (D) start(D); else { $("rf").hidden = false; $("rf").onclick = load; load();
  document.addEventListener("visibilitychange", function () { if (!document.hidden && D && Date.now() / 1000 - D.at > 120) load(); }); }
</script></body></html>
"""
